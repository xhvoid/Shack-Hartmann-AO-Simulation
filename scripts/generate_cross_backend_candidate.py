#!/usr/bin/env python3
"""Generate, review, and explicitly accept the cross-backend baseline.

Candidate generation and baseline acceptance are deliberately separate
operations.  Tests, notebooks, and examples only ever read the packaged
baseline; nothing updates it as a side effect, and acceptance requires an
explicit command with a human-readable reason and a review reference.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
# Where files are read and written, and which repository the recorded
# provenance refers to, are two different questions.  Keeping them separate
# lets provenance always be checked against the real source repository even
# when the resource tree under test is a copy.
REPO_ROOT = ROOT

GENERATOR_NAME = "scripts/generate_cross_backend_candidate.py"
# Bumped whenever a change here alters what a candidate's provenance actually
# attests to.  Acceptance refuses any candidate whose recorded
# generator_version differs from this constant, so the bump is the mechanism
# that retires candidates written by an earlier, weaker generator: nothing in
# the candidate document itself reveals that its clean-tree claim was made
# without looking for concealed index entries, that its commit and patch hash
# were sampled non-atomically, or that only the top-level package was checked
# against this checkout.  Version 3 is the first that closes all three.
GENERATOR_VERSION = "4"
CANDIDATE_FILE = "cross_backend_candidate.json"
DIFF_JSON = "cross_backend_diff.json"
DIFF_MARKDOWN = "cross_backend_diff.md"
DESTINATION_DIR = (
    ROOT / "src" / "shwfs_ao" / "resources" / "reference_metrics" / "cross_backend"
)
BASELINE_NAME = "cross_backend_baseline.json"


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Generate a cross-backend candidate or accept a separately "
            "reviewed candidate. Acceptance never runs the suite implicitly."
        )
    )
    operation = parser.add_mutually_exclusive_group()
    operation.add_argument(
        "--generate-candidate",
        action="store_true",
        help="Run the suite and write a candidate plus diffs to --candidate-dir.",
    )
    operation.add_argument(
        "--accept-baseline-update",
        action="store_true",
        help="Accept an existing reviewed candidate; never generates one.",
    )
    parser.add_argument(
        "--candidate-dir",
        type=Path,
        help="Explicit caller-owned candidate directory outside packaged resources.",
    )
    parser.add_argument(
        "--reason",
        help="Required concise scientific reason when accepting a candidate.",
    )
    parser.add_argument(
        "--review-reference",
        help="Required review/issue/PR reference when accepting a candidate.",
    )
    args = parser.parse_args()

    if not args.generate_candidate and not args.accept_baseline_update:
        parser.error(
            "--accept-baseline-update is required for acceptance; use "
            "--generate-candidate to create a reviewable candidate instead."
        )
    if args.candidate_dir is None:
        parser.error("--candidate-dir is required for both generation and acceptance.")

    candidate_dir = args.candidate_dir.expanduser().resolve()
    _reject_packaged_destination(candidate_dir, parser)

    # Both operations execute repository code and write provenance about it, so
    # both run in an interpreter whose bytecode cache and import state this
    # script controls.  Placed after argument validation so a mistyped command
    # is still answered immediately, by the process the maintainer started.
    if not os.environ.get(_CONTROLLED_INTERPRETER):
        _reexec_in_a_controlled_interpreter()
    if args.generate_candidate:
        if args.reason is not None or args.review_reference is not None:
            parser.error("Acceptance metadata is not valid during candidate generation.")
        _generate_candidate(candidate_dir)
        return

    if not args.reason or not args.reason.strip():
        parser.error("--reason is required when --accept-baseline-update is used.")
    if not args.review_reference or not args.review_reference.strip():
        parser.error(
            "--review-reference is required when --accept-baseline-update is used."
        )
    if os.environ.get("PYTEST_CURRENT_TEST"):
        raise SystemExit(
            "Baseline acceptance is forbidden while pytest is running."
        )
    _accept_reviewed_candidate(
        candidate_dir,
        reason=args.reason.strip(),
        review_reference=args.review_reference.strip(),
    )


_CONTROLLED_INTERPRETER = "SHWFS_AO_CROSS_BACKEND_CONTROLLED_INTERPRETER"


def _reexec_in_a_controlled_interpreter() -> None:
    """Re-run this generation in a fresh interpreter, and exit with its status.

    Two properties a baseline's provenance depends on cannot be established from
    inside a process that is already running, because both are decided before
    the first line of it executes.

    The first is which bytes actually execute.  ``source_commit`` and
    ``source_patch_sha256`` describe tracked ``.py`` files, but CPython runs
    whatever it finds in ``__pycache__``, and ``__pycache__`` is ignored by git —
    so it contributes nothing to the patch hash and leaves the tree looking
    clean.  A ``.pyc`` whose recorded size and mtime match its source is used
    without recompiling, which makes a poisoned cache a way to run uncommitted
    code under a tracked path with clean provenance.  Pointing
    ``PYTHONPYCACHEPREFIX`` at an empty directory moves the whole cache lookup
    out of the checkout: nothing is found there, every module is compiled from
    the ``.py`` the hash covers, and the poisoned entries are simply never
    consulted.  It has to be an environment variable on a new interpreter
    because the cache location is read at startup.

    The second is that provenance is sampled before any repository code loads.
    In a process that has already imported part of ``shwfs_ao``, the earliest
    possible sample still comes after those imports, so a checkout that moved
    in between is invisible: the sample and the post-run re-read agree with each
    other and with the tree, while the loaded modules came from a commit neither
    of them names.  A fresh interpreter has imported nothing yet, so the sample
    can precede every import and the re-read can close the bracket.

    The child is invoked with this process's own argv, so it takes exactly the
    same arguments through exactly the same parser.
    """

    import tempfile

    with tempfile.TemporaryDirectory(prefix="shwfs-ao-pycache-") as cache_dir:
        environment = dict(os.environ)
        environment[_CONTROLLED_INTERPRETER] = "1"
        environment["PYTHONPYCACHEPREFIX"] = cache_dir
        # Belt and braces: -B stops the child writing bytecode anywhere, so the
        # fresh cache stays empty and a second run cannot inherit the first's.
        completed = subprocess.run(
            [sys.executable, "-B", *sys.argv],
            env=environment,
        )
    raise SystemExit(completed.returncode)


def _generate_candidate(candidate_dir: Path) -> None:
    # The recorded commit describes this repository, so the code that runs must
    # be this repository's — otherwise the baseline is credited to a checkout
    # Read before shwfs_ao is imported at all — including by the package-origin
    # check below, whose own `import shwfs_ao` executes repository code.  A
    # checkout that moves between the import and the sample lets the suite run
    # one commit's code while the candidate records another, and both halves
    # look clean because they are: the recorded commit exists, the tree matches
    # it, and only the already-loaded modules disagree.  Sampling first makes
    # the post-run re-read (below) able to catch exactly that, because the two
    # reads then bracket every import instead of sitting on one side of them.
    source_commit, source_patch = _sample_source_identity()

    # The recorded commit describes this repository, so the code that runs must
    # be this repository's — otherwise the baseline is credited to a checkout
    # that never produced it.  Checked before anything is created on disk.
    _require_executed_package_is_this_checkout()
    candidate_dir.mkdir(parents=True, exist_ok=True)
    collisions = [
        candidate_dir / name
        for name in (CANDIDATE_FILE, DIFF_JSON, DIFF_MARKDOWN)
    ]
    existing = [path for path in collisions if path.exists()]
    if existing:
        joined = ", ".join(str(path) for path in existing)
        raise SystemExit(
            f"Candidate generation refuses to overwrite existing files: {joined}"
        )

    from shwfs_ao.validation.cross_backend import run_cross_backend_report
    from shwfs_ao.validation.regression import validate_cross_backend_report

    # The opening check could only judge the modules imported up to that point.
    # These two lines are what pull in the code that computes the numbers, so
    # the guard runs again over what they brought into sys.modules.
    _require_executed_package_is_this_checkout()

    constraint_file, constraint_sha256 = _verified_constraint_identity()

    report = run_cross_backend_report(
        dependency_constraint_file=constraint_file,
        dependency_constraint_sha256=constraint_sha256,
    )
    # The suite imports the rest of the package lazily as it runs, so the last
    # word on which code executed can only be had once it has finished.  This
    # still precedes every write, so nothing a foreign module produced is
    # recorded.
    _require_executed_package_is_this_checkout()
    _require_source_unchanged(source_commit, source_patch)
    candidate: dict[str, Any] = dict(report)
    candidate["generator"] = {
        "generator_name": GENERATOR_NAME,
        "generator_version": GENERATOR_VERSION,
        "source_commit": source_commit,
        "source_tree_clean": source_patch is None,
        "source_patch_sha256": source_patch,
    }
    validate_cross_backend_report(candidate)

    candidate_bytes = _canonical_bytes(candidate)
    # Derive the diff and its Markdown from the persisted canonical bytes, not
    # the in-memory document: acceptance re-reads the file, so building from
    # the same round-tripped form makes the reviewed diff exactly reproducible
    # and lets acceptance bind both the machine and human renderings.
    diff = _build_diff(json.loads(candidate_bytes), candidate_bytes)
    (candidate_dir / CANDIDATE_FILE).write_bytes(candidate_bytes)
    (candidate_dir / DIFF_JSON).write_bytes(_canonical_bytes(diff))
    (candidate_dir / DIFF_MARKDOWN).write_text(
        _render_diff_markdown(diff),
        encoding="utf-8",
    )
    print(f"Generated candidate in {candidate_dir}")
    print(
        f"Review {candidate_dir / DIFF_MARKDOWN} before running the "
        "acceptance command."
    )


def _accept_reviewed_candidate(
    candidate_dir: Path,
    *,
    reason: str,
    review_reference: str,
) -> None:
    from datetime import datetime, timezone

    # Acceptance validates the candidate against the packaged schema and then
    # rewrites this repository's baseline and resource manifest, so the code
    # doing it must be this repository's too.
    _require_executed_package_is_this_checkout()

    from shwfs_ao.validation.regression import (
        baseline_from_report,
        validate_baseline_against_schema,
        validate_cross_backend_report,
    )

    # Same reason as in generation: the guard can only judge what is already
    # imported, and these are the names that decide whether the candidate is
    # valid and then rewrite the packaged baseline from it.
    _require_executed_package_is_this_checkout()

    candidate_path = candidate_dir / CANDIDATE_FILE
    if not candidate_path.is_file():
        raise SystemExit(f"Missing reviewed candidate: {candidate_path}")
    candidate_bytes = candidate_path.read_bytes()
    candidate = json.loads(candidate_bytes.decode("utf-8"))
    validate_cross_backend_report(candidate)
    generator = candidate.get("generator")
    if not isinstance(generator, dict) or not generator:
        raise SystemExit(
            "Candidate is missing its generator block; regenerate it with "
            "this script."
        )
    _verify_candidate_provenance(generator)

    # The recomputed diff embeds content hashes of the candidate file bytes
    # and the current packaged baseline, so any modification to either after
    # the reviewed diff was generated — a tolerance, a rationale, a hash, or
    # formatting alone — forces regeneration and a fresh review.
    diff = _build_diff(candidate, candidate_bytes)
    checked_diff_path = candidate_dir / DIFF_JSON
    if not checked_diff_path.is_file():
        raise SystemExit(f"Missing generated machine-readable diff: {checked_diff_path}")
    checked_diff = json.loads(checked_diff_path.read_text(encoding="utf-8"))
    if checked_diff != diff:
        raise SystemExit(
            "Candidate or accepted baseline changed after diff generation; "
            "regenerate and review the diff."
        )
    # The human reviews the Markdown, so it too must still describe exactly the
    # candidate and baseline being accepted, not a stale rendering.
    checked_markdown_path = candidate_dir / DIFF_MARKDOWN
    if not checked_markdown_path.is_file():
        raise SystemExit(
            f"Missing generated human-readable diff: {checked_markdown_path}"
        )
    if checked_markdown_path.read_text(encoding="utf-8") != _render_diff_markdown(diff):
        raise SystemExit(
            "The reviewed Markdown diff no longer matches the candidate and "
            "baseline; regenerate and review the diff."
        )

    report_body = {
        key: value for key, value in candidate.items() if key != "generator"
    }
    baseline = baseline_from_report(
        report_body,
        generator=generator,
        acceptance={
            "reason": reason,
            "review_reference": review_reference,
            "accepted_at_utc": datetime.now(timezone.utc).isoformat(),
        },
    )
    # The acceptance workflow is the only writer of the packaged baseline, so
    # it must satisfy the packaged JSON Schema as well as the custom contract.
    validate_baseline_against_schema(baseline)
    DESTINATION_DIR.mkdir(parents=True, exist_ok=True)
    target = DESTINATION_DIR / BASELINE_NAME
    target.write_text(
        json.dumps(baseline, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(f"Updated {target.relative_to(ROOT)} from {candidate_path}")
    _refresh_resource_manifest()


# Two consecutive samples must agree before the source identity is trusted.
# Five attempts is far more than a checkout nobody is writing to ever needs, and
# a tree that still disagrees after them is being modified concurrently — a
# state no single recorded provenance can describe.
_SOURCE_IDENTITY_ATTEMPTS = 5


def _sample_source_identity() -> tuple[str, str | None]:
    """Return a ``(commit, patch)`` pair that describes one state of the tree.

    The commit and the patch hash come from separate git invocations, so a HEAD
    that moves between them yields a pair that never existed: one half names the
    commit from before the move and the other describes the tree after it.  Both
    halves are then individually plausible, which is what makes the mixture
    dangerous — a pre-run pair mixed one way and a post-run pair mixed the other
    can agree field for field while the suite ran against a commit neither of
    them names.

    Consistency is established the only way an external process can establish
    it: by re-reading until two consecutive samples agree, so the pair that is
    returned was observed twice with no change in between.  A checkout that will
    not settle within :data:`_SOURCE_IDENTITY_ATTEMPTS` reads is refused rather
    than described by whichever sample happened to be last.
    """

    def bracketed() -> tuple[str, str | None] | None:
        """One sample whose own two git calls describe a single state, or None.

        Re-reading until two *samples* agree is not enough on its own, because a
        sample is itself two git invocations: HEAD can move between them, and
        the resulting pair — a commit from before the move, a patch hash from
        after — never described the checkout at any instant.  Two such pairs can
        even agree with each other.  Reading the commit again on the far side
        closes that window: a commit that is the same before and after the patch
        was hashed is a commit the patch was hashed under.
        """

        opening = _source_commit()
        patch = _source_patch_sha256()
        if _source_commit() != opening:
            return None
        return (opening, patch)

    previous = bracketed()
    for _ in range(_SOURCE_IDENTITY_ATTEMPTS - 1):
        current = bracketed()
        if current is not None and current == previous:
            return current
        previous = current
    last_seen = (
        "no sample completed with HEAD stationary across it"
        if previous is None
        else f"last seen commit {previous[0]} with patch {previous[1]!r}"
    )
    raise SystemExit(
        "The source identity did not settle: the commit or the working tree "
        f"changed during or between every one of {_SOURCE_IDENTITY_ATTEMPTS} "
        f"consecutive reads ({last_seen}). A baseline names one commit and one "
        "patch hash as the origin of its numbers, so it cannot be generated "
        "from a checkout that is being written to. Stop whatever is moving HEAD "
        "or the working tree and re-run."
    )


def _require_source_unchanged(source_commit: str, source_patch: str | None) -> None:
    """Refuse a candidate whose source moved while the suite was running.

    Both halves of the recorded source identity are re-read after the run.  The
    commit is checked in its own right rather than left to the patch hash:
    switching between two clean commits leaves the patch hash ``None`` on both
    sides, so the candidate would record the commit the suite started on while
    the rest of it executed a different one — provenance naming code that never
    produced these numbers.

    The re-read goes through :func:`_sample_source_identity`, exactly as the
    pre-run read did, so the two sides compare quantities of the same kind: one
    self-consistent description of the checkout each.  Comparing a
    non-atomically sampled pair against another non-atomically sampled pair is
    what let HEAD move unnoticed between the commit read and the patch read on
    either side, with both fields matching afterwards.
    """

    current_commit, current_patch = _sample_source_identity()
    if current_commit != source_commit:
        raise SystemExit(
            f"HEAD moved from {source_commit} while the comparison suite ran, "
            "so the recorded source_commit would not name the code that "
            "produced this report. Re-run from a stationary checkout."
        )
    if current_patch != source_patch:
        raise SystemExit(
            "The working tree changed while the comparison suite ran, so the "
            "recorded source_patch_sha256 would not describe the tree that "
            "produced this report. Re-run from a quiescent tree."
        )


def _require_executed_package_is_this_checkout() -> Path:
    """Refuse unless the imported ``shwfs_ao`` is this repository's source tree.

    ``source_commit`` and ``source_patch_sha256`` are read from ``REPO_ROOT``,
    but the physics is executed by whichever ``shwfs_ao`` the interpreter
    resolves — an ordinary wheel in the active environment, a stale editable
    install pointing somewhere else, or a copy vendored into another project.
    Nothing connects the two, so results produced by a foreign or outdated
    package could be recorded as this commit's, and the reproduction step the
    provenance promises ("check out this commit and re-run") would not
    reproduce them.

    Requiring the package to *be* ``<repo>/src/shwfs_ao`` is what makes the
    recorded commit describe the executed code.  An installed copy under the
    repository (a built wheel in a virtualenv here, say) is refused for the same
    reason a foreign one is: its contents are a snapshot, not the tracked tree
    the commit and patch hash describe.

    The top-level ``__path__`` is not sufficient on its own.  Import binds each
    submodule to the file it was first loaded from and caches it in
    ``sys.modules`` for the life of the process, so a foreign
    ``shwfs_ao.validation.cross_backend`` left there by an earlier ``sys.path``,
    a conftest, a plugin, or a half-replaced installation keeps executing no
    matter where the parent package resolves afterwards.  Every ``shwfs_ao``
    module the interpreter holds is therefore located individually, and one that
    cannot say where it came from is refused rather than skipped: an unlocatable
    module is precisely the one this check cannot clear.

    A walk of ``sys.modules`` can only see what is already imported, so the
    callers invoke this again after each deferred ``from shwfs_ao...`` import and
    once more after the comparison suite returns, which is where the package's
    remaining modules are pulled in.  Re-checking is a handful of dictionary
    lookups.  Importing everything up front instead would be simpler to read but
    strictly worse: a shadowing package that merely lacks the submodule would
    then fail with a bare ImportError rather than the refusal above, which is the
    message that tells a maintainer what is actually wrong.
    """

    import shwfs_ao

    expected = (REPO_ROOT / "src" / "shwfs_ao").resolve()
    locations = [
        Path(entry).resolve() for entry in getattr(shwfs_ao, "__path__", []) or []
    ]
    if locations != [expected]:
        observed = ", ".join(str(path) for path in locations) or "<unknown>"
        raise SystemExit(
            f"The imported shwfs_ao package is {observed}, not {expected}. A "
            "cross-backend baseline records this repository's commit as the "
            "origin of its numbers, so it must be generated by this "
            "repository's code; install the checkout in editable mode (python "
            "-m pip install -e .) or run with this source tree first on the "
            "import path."
        )
    for name, module in sorted(sys.modules.items()):
        if not name.startswith("shwfs_ao."):
            continue
        located = _module_locations(module)
        if not located:
            raise SystemExit(
                f"The imported {name} module reports no filesystem location, so "
                "there is no way to tell whether it came from this checkout. A "
                "baseline names this repository's commit as the origin of its "
                "numbers, so an unlocatable module cannot be allowed to produce "
                "them; remove it from sys.modules or generate the candidate in "
                "a fresh interpreter."
            )
        foreign = [
            path
            for path in located
            if path != expected and expected not in path.parents
        ]
        if foreign:
            observed = ", ".join(str(path) for path in foreign)
            raise SystemExit(
                f"The imported {name} module is loaded from {observed}, which is "
                f"not under {expected}. Python caches every imported submodule "
                "for the life of the process, so this one would execute even "
                "though the shwfs_ao package itself resolves to this checkout, "
                "and the candidate would credit this repository's commit with "
                "numbers another tree produced. Generate the candidate in a "
                "fresh interpreter running only this source tree."
            )
    return expected


def _module_locations(module: Any) -> list[Path]:
    """Every filesystem location an imported module can be traced to.

    A package contributes its search path as well as its file, and both matter:
    the file is the code that already ran, the search path is where all of its
    further submodules will be loaded from.  Both are resolved, so a symlink
    into the checkout is recognised as the checkout and one out of it is not
    mistaken for it.  A module with neither — a ``None`` placeholder, a bare
    module object, an incompletely initialised namespace package — yields an
    empty list, which the caller treats as a refusal rather than as consent.
    """

    entries = [Path(entry) for entry in getattr(module, "__path__", None) or []]
    filename = getattr(module, "__file__", None)
    if filename is not None:
        entries.append(Path(filename))
    return [entry.resolve() for entry in entries]


def _verify_candidate_provenance(generator: dict[str, Any]) -> None:
    """Check the generator block against the repository, not just its shape.

    The installed validator can only check that ``source_commit`` *looks* like a
    commit; acceptance is the one step that runs inside the source repository,
    so it is the only place the claim can actually be tested.  Without this a
    candidate could name any 40 hexadecimal characters — a commit that never
    existed — and be accepted as the reproducible origin of the baseline.
    """

    for field, expected in (
        ("generator_name", GENERATOR_NAME),
        ("generator_version", GENERATOR_VERSION),
    ):
        recorded = generator.get(field)
        if recorded != expected:
            raise SystemExit(
                f"Candidate generator.{field} is {recorded!r}, but this script "
                f"is {expected!r}. Accepting it would credit the baseline to a "
                "generator that did not produce it; regenerate the candidate."
            )

    commit = generator.get("source_commit")
    if not isinstance(commit, str) or not re.fullmatch(r"[0-9a-f]{40}", commit):
        raise SystemExit(
            f"Candidate generator.source_commit {commit!r} is not a "
            "40-character lowercase git commit hash."
        )
    try:
        resolved = subprocess.run(
            ["git", "rev-parse", "--verify", "--quiet", f"{commit}^{{commit}}"],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError) as exc:
        raise SystemExit(
            f"Candidate generator.source_commit {commit} is not a commit in "
            "this repository. A baseline's provenance must be reproducible "
            "from the commit it names, so acceptance stops here."
        ) from exc
    if resolved != commit:
        raise SystemExit(
            f"Candidate generator.source_commit {commit} resolves to "
            f"{resolved}, so it does not name a commit object."
        )

    # A tree recorded as clean has nothing that diverged from that commit, so
    # patch evidence of a divergence contradicts the record.  One of the two is
    # wrong, and acceptance cannot tell which.
    if generator.get("source_tree_clean") is True and (
        generator.get("source_patch_sha256") is not None
    ):
        raise SystemExit(
            "Candidate generator records source_tree_clean=true together with "
            f"source_patch_sha256={generator['source_patch_sha256']!r}. A clean "
            "tree has no divergence to hash; regenerate the candidate."
        )
    # A dirty candidate may be generated and read — that is how a maintainer
    # inspects work in progress — but it may never become the packaged
    # baseline.  The patch hash is a digest of a divergence that is recorded
    # nowhere: acceptance can confirm it is well formed and that it matches the
    # tree at this instant, and nothing more.  The moment the working tree moves
    # on, the bytes it summarised are gone, so the baseline names a state no
    # checkout can be returned to.  AO-REF-018 asks for provenance that is
    # reproducible rather than merely labelled dirty, and a hash of vanished
    # bytes is the second of those, so this refuses instead of pretending.
    if generator.get("source_tree_clean") is not True:
        raise SystemExit(
            "Candidate generator records source_tree_clean="
            f"{generator.get('source_tree_clean')!r} with source_patch_sha256="
            f"{generator.get('source_patch_sha256')!r}. A baseline must be "
            "reproducible from the commit it names, and a patch hash summarises "
            "a divergence this repository does not store: whoever checks out "
            "that commit cannot reconstruct the tree these numbers came from. "
            "Commit or stash the divergence and regenerate the candidate from a "
            "clean checkout."
        )


def _refresh_resource_manifest() -> None:
    import tempfile

    from shwfs_ao.io.resources import render_resource_manifest

    # The manifest records the content hashes the packaged resources are served
    # under, so the renderer is as much this repository's code as the validator
    # is; it is imported here, after the caller's guard ran, and so needs its
    # own check.
    _require_executed_package_is_this_checkout()

    resource_root = DESTINATION_DIR.parents[1]
    manifest_path = resource_root / "resource_manifest.json"
    rendered = render_resource_manifest(resource_root)
    temporary_name: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=resource_root,
            prefix=".resource_manifest.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            handle.write(rendered)
            handle.flush()
            os.fsync(handle.fileno())
            temporary_name = handle.name
        os.replace(temporary_name, manifest_path)
        temporary_name = None
    finally:
        if temporary_name is not None:
            Path(temporary_name).unlink(missing_ok=True)
    print(f"Updated {manifest_path.relative_to(ROOT)}")


def _build_diff(
    candidate: dict[str, Any],
    candidate_bytes: bytes,
) -> dict[str, Any]:
    current = _load_current_baseline()
    current_bytes = _current_baseline_bytes()
    candidate_metrics = _metric_values(candidate)
    current_metrics = _metric_values(current) if current is not None else {}
    keys = sorted(set(candidate_metrics) | set(current_metrics))
    entries = []
    for kind, name in keys:
        entries.append(
            {
                "comparison_kind": kind,
                "metric": name,
                "old_value": current_metrics.get((kind, name)),
                "new_value": candidate_metrics.get((kind, name)),
            }
        )
    return {
        "schema_name": "shwfs_ao.cross_backend_diff",
        "schema_version": 1,
        "baseline_present": current is not None,
        "old_config_hash": (
            None
            if current is None
            else current["comparison_config"]["config_hash"]
        ),
        "new_config_hash": candidate["comparison_config"]["config_hash"],
        "current_baseline_sha256": (
            None
            if current_bytes is None
            else hashlib.sha256(current_bytes).hexdigest()
        ),
        "candidate_sha256": hashlib.sha256(candidate_bytes).hexdigest(),
        "metrics": entries,
        "changes": _document_changes(current, candidate),
    }


def _document_changes(
    current: dict[str, Any] | None,
    candidate: dict[str, Any],
) -> list[dict[str, Any]]:
    """Return every leaf-level difference between baseline and candidate.

    Comparisons are keyed by ``comparison_kind`` and metrics by ``name`` so a
    changed tolerance reads as one stable path instead of an array-index
    shuffle.  The top-level ``acceptance`` block is excluded: candidates never
    carry one, and acceptance provenance is minted at accept time.  An absent
    side is rendered as null.
    """

    old_document = {} if current is None else dict(current)
    new_document = dict(candidate)
    old_document.pop("acceptance", None)
    new_document.pop("acceptance", None)
    changes: list[dict[str, Any]] = []
    _collect_changes("", old_document, new_document, changes)
    return changes


_ABSENT = object()


def _collect_changes(
    path: str,
    old: Any,
    new: Any,
    changes: list[dict[str, Any]],
) -> None:
    if old is _ABSENT or new is _ABSENT or type(old) is not type(new):
        changes.append(
            {
                "path": path,
                "old": None if old is _ABSENT else old,
                "new": None if new is _ABSENT else new,
            }
        )
        return
    if isinstance(old, dict):
        for key in sorted(set(old) | set(new)):
            _collect_changes(
                f"{path}.{key}" if path else str(key),
                old.get(key, _ABSENT),
                new.get(key, _ABSENT),
                changes,
            )
        return
    if isinstance(old, list):
        keyed_old = _keyed_elements(path, old)
        keyed_new = _keyed_elements(path, new)
        if keyed_old is not None and keyed_new is not None:
            for key in sorted(set(keyed_old) | set(keyed_new)):
                _collect_changes(
                    f"{path}[{key}]",
                    keyed_old.get(key, _ABSENT),
                    keyed_new.get(key, _ABSENT),
                    changes,
                )
            return
        for index in range(max(len(old), len(new))):
            _collect_changes(
                f"{path}[{index}]",
                old[index] if index < len(old) else _ABSENT,
                new[index] if index < len(new) else _ABSENT,
                changes,
            )
        return
    if old != new:
        changes.append({"path": path, "old": old, "new": new})


def _keyed_elements(
    path: str,
    elements: list[Any],
) -> dict[str, Any] | None:
    key_field = (
        "comparison_kind"
        if path.endswith("comparisons")
        else "name" if path.endswith(".metrics") else None
    )
    if key_field is None:
        return None
    keyed: dict[str, Any] = {}
    for element in elements:
        if not isinstance(element, dict) or key_field not in element:
            return None
        label = str(element[key_field])
        if label in keyed:
            return None
        keyed[label] = element
    return keyed


def _canonical_bytes(document: dict[str, Any]) -> bytes:
    return (json.dumps(document, indent=2, sort_keys=True) + "\n").encode(
        "utf-8"
    )


def _md_cell(value: object) -> str:
    """Escape a value for safe interpolation into a Markdown table cell.

    Structural characters in a recorded unit, path, or value (a literal ``|``,
    or a newline) would otherwise split the row or inject extra Markdown into
    the reviewed diff.  Backslash is escaped first so the other escapes are not
    themselves re-escaped, ``|`` is escaped, and any newline becomes a ``<br>``.
    """

    text = str(value).replace("\\", "\\\\").replace("|", "\\|")
    return text.replace("\r\n", "<br>").replace("\r", "<br>").replace("\n", "<br>")


def _render_diff_markdown(diff: dict[str, Any]) -> str:
    lines = [
        "# Cross-backend baseline candidate diff",
        "",
        f"- baseline present: {diff['baseline_present']}",
        f"- old config hash: {diff['old_config_hash']}",
        f"- new config hash: {diff['new_config_hash']}",
        f"- current baseline SHA-256: {diff['current_baseline_sha256']}",
        f"- candidate SHA-256: {diff['candidate_sha256']}",
        "",
        "## Metric values",
        "",
        "| comparison | metric | old | new |",
        "| --- | --- | --- | --- |",
    ]
    for entry in diff["metrics"]:
        lines.append(
            f"| {_md_cell(entry['comparison_kind'])} | {_md_cell(entry['metric'])} "
            f"| {_md_cell(entry['old_value'])} | {_md_cell(entry['new_value'])} |"
        )
    lines.extend(
        (
            "",
            "## All other changes (tolerances, criteria, rationale, hashes, "
            "environment; null = absent)",
            "",
        )
    )
    changes = [
        entry
        for entry in diff["changes"]
        if not (
            entry["path"].endswith(".value")
            and entry["path"].startswith("comparisons[")
        )
    ]
    if not changes:
        lines.append("None.")
    else:
        lines.extend(("| path | old | new |", "| --- | --- | --- |"))
        for entry in changes:
            lines.append(
                f"| `{_md_cell(entry['path'])}` | {_md_cell(entry['old'])} | "
                f"{_md_cell(entry['new'])} |"
            )
    return "\n".join(lines) + "\n"


def _metric_values(document: dict[str, Any]) -> dict[tuple[str, str], Any]:
    return {
        (comparison["comparison_kind"], metric["name"]): metric["value"]
        for comparison in document.get("comparisons", [])
        for metric in comparison.get("metrics", [])
    }


def _load_current_baseline() -> dict[str, Any] | None:
    path = DESTINATION_DIR / BASELINE_NAME
    if not path.is_file():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def _current_baseline_bytes() -> bytes | None:
    path = DESTINATION_DIR / BASELINE_NAME
    if not path.is_file():
        return None
    return path.read_bytes()


def _constraint_profile_name() -> str:
    version = sys.version_info
    return f"constraints/hcipy-py{version.major}{version.minor}.txt"


_IGNORED_LOCK_DISTRIBUTIONS = frozenset(
    {"pip", "shack-hartmann-ao-simulation"}
)


def _installed_distributions() -> dict[str, str]:
    """Normalized name -> version for every non-ignored installed dist."""

    from importlib import metadata

    installed: dict[str, str] = {}
    for distribution in metadata.distributions():
        name = distribution.metadata["Name"]
        if name is None:
            continue
        normalized = re.sub(r"[-_.]+", "-", name.strip()).lower()
        if normalized in _IGNORED_LOCK_DISTRIBUTIONS:
            continue
        installed[normalized] = distribution.version
    return installed


# A lock is resolved for one operating system *and one architecture*: Linux
# aarch64 and Linux x86-64 resolve different wheels from the same requirement
# set, so an architecture-blind "linux" tag could be claimed by a machine the
# lock was never resolved on whenever the pinned versions happened to coincide.
_LOCK_PLATFORMS = {
    "Linux-x86-64": "linux-x86-64",
    "Linux-aarch64": "linux-aarch64",
    "macOS-arm64": "macos-arm64",
}
# Longest first, so "Linux-x86-64" can never be matched as a bare "Linux".
_LOCK_PLATFORM_DECLARATION = re.compile(
    r"\bon[ \t]*(?:\r?\n[ \t]*#[ \t]*)?("
    + "|".join(
        re.escape(name) for name in sorted(_LOCK_PLATFORMS, key=len, reverse=True)
    )
    + r")\b"
)
_MACHINE_TAGS = {
    "x86_64": "x86-64",
    "amd64": "x86-64",
    "aarch64": "aarch64",
    "arm64": "aarch64",
}


def _current_platform_tag() -> str:
    """The reproducible-lock platform tag for the running interpreter."""

    import platform as _platform

    system = _platform.system()
    machine = _platform.machine()
    architecture = _MACHINE_TAGS.get(machine.lower())
    if system == "Linux" and architecture is not None:
        return f"linux-{architecture}"
    if system == "Darwin" and architecture == "aarch64":
        return "macos-arm64"
    raise SystemExit(
        "Cross-backend baselines are only locked for "
        f"{', '.join(sorted(_LOCK_PLATFORMS.values()))}; the running platform "
        f"{system}/{machine} has no reproducible lock, so generating one here "
        "would record an unverifiable environment."
    )


def _lock_platform_tag(header_text: str, profile: str) -> str:
    """The platform a constraint lock declares in its header prose.

    Only the leading comment block is read.  The body is a list of pins, and a
    package name, URL or note there that happens to contain a platform token is
    not a declaration — searching the whole file would let a lock that declares
    nothing at all resolve from an incidental mention.  The declaration may be
    wrapped across the header's comment lines, so a single comment continuation
    between ``on`` and the platform name is accepted; nothing else is, because a
    lock that does not name its architecture cannot be matched to the
    environment that resolved it.
    """

    header_lines: list[str] = []
    for line in header_text.splitlines():
        if not line.lstrip().startswith("#"):
            break
        header_lines.append(line)
    match = _LOCK_PLATFORM_DECLARATION.search("\n".join(header_lines))
    if match is None:
        expected = ", ".join(f"'on {name}'" for name in sorted(_LOCK_PLATFORMS))
        raise SystemExit(
            f"Constraint profile {profile} does not declare its platform and "
            f"architecture (expected one of {expected} in its header)."
        )
    return _LOCK_PLATFORMS[match.group(1)]


def _verified_constraint_identity() -> tuple[str, str]:
    """Return the (file, sha256) constraint identity of this environment.

    The named profile is only recorded after a strict lock check that mirrors
    scripts/verify_environment_lock.py: the profile must exist for the running
    Python minor version, must pin numpy and hcipy, and every installed
    distribution must appear in the profile at exactly its installed version.
    Skipping missing pins or tolerating installed-but-unpinned distributions
    would let a drifted or foreign-platform profile — the profiles are
    resolved per platform — silently generate the baseline; an installed
    distribution the profile does not pin surfaces that here instead.
    """

    profile = _constraint_profile_name()
    path = ROOT / profile
    if not path.is_file():
        raise SystemExit(
            f"Missing constraint profile {profile} for the running Python "
            f"{sys.version_info.major}.{sys.version_info.minor} "
            "environment; freeze the maintainer environment into that file "
            "before generating a candidate."
        )
    text = path.read_text(encoding="utf-8")
    # The lock is selected by Python version alone, but each lock is frozen for
    # one platform (the py3.11 hcipy lane is Linux, the py3.14 one is
    # macOS-arm64).  Require the lock's declared platform to match the running
    # one, so a foreign-platform lock cannot silently generate the baseline.
    declared_platform = _lock_platform_tag(text, profile)
    current_platform = _current_platform_tag()
    if declared_platform != current_platform:
        raise SystemExit(
            f"Constraint profile {profile} is frozen for {declared_platform}, "
            f"but this environment is {current_platform}; a cross-platform lock "
            "cannot reproduce the baseline."
        )
    pins = _parse_constraint_pins(text)
    for required in ("numpy", "hcipy"):
        if required not in pins:
            raise SystemExit(
                f"Constraint profile {profile} does not pin {required}."
            )
    installed = _installed_distributions()
    mismatches = []
    for name in sorted(installed):
        if name not in pins:
            mismatches.append(
                f"{name}=={installed[name]} is installed but {profile} does "
                "not pin it"
            )
        elif pins[name] != installed[name]:
            mismatches.append(
                f"{name}: installed {installed[name]} != pinned {pins[name]}"
            )
    if mismatches:
        raise SystemExit(
            f"The running environment does not satisfy {profile}: "
            + "; ".join(mismatches)
        )
    return profile, hashlib.sha256(path.read_bytes()).hexdigest()


def _parse_constraint_pins(text: str) -> dict[str, str]:
    pins: dict[str, str] = {}
    for raw_line in text.splitlines():
        line = raw_line.split("#", 1)[0].split(";", 1)[0].strip()
        if not line or line.startswith("-"):
            continue
        if "==" in line:
            name, _, version = line.partition("==")
            canonical = re.sub(r"[-_.]+", "-", name.strip()).lower()
            pins[canonical] = version.strip()
    return pins


def _source_commit() -> str:
    """Return the current 40-character commit, or refuse to generate.

    A failed lookup previously became the accepted string ``"unknown"``, so a
    baseline could be generated with unverifiable provenance.  A candidate is
    now refused unless git reports a real commit hash.
    """

    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            check=True,
        )
    except (OSError, subprocess.CalledProcessError) as exc:
        raise SystemExit(
            "Cannot record source provenance: 'git rev-parse HEAD' failed. "
            "A cross-backend baseline must be generated from a real commit."
        ) from exc
    commit = result.stdout.strip()
    if not re.fullmatch(r"[0-9a-f]{40}", commit):
        raise SystemExit(
            f"Refusing to record a non-canonical source commit {commit!r}."
        )
    return commit


def _source_patch_sha256() -> str | None:
    """Content hash of the working tree's divergence from HEAD, or None if none.

    Binds both tracked modifications (``git diff HEAD --binary``) and the sorted
    paths and contents of untracked, non-ignored files.  Untracked scientific
    inputs can change a generated result just as much as a tracked edit, so a
    dirty tree records verifiable evidence of exactly what diverged from the
    recorded commit (the documented ``source_patch_sha256`` contract) instead of
    hiding it.  Every divergence contributes its real bytes: anything that
    reduced to a placeholder would let two different working trees record the
    same evidence.  Returns ``None`` only when the tree matches HEAD exactly.

    Both commands below are blind to entries the index tells git not to look at,
    so the concealment check runs first — see
    :func:`_require_no_concealed_index_entries`.  It sits here rather than at the
    call sites because ``_source_tree_clean()`` is defined as this function
    returning ``None``: guarding the one place both answers come from is what
    makes a concealed modification impossible to record as a clean tree.
    """

    _require_no_concealed_index_entries()
    # Everything here is handled as bytes.  A working tree can hold paths and
    # file contents that are not valid UTF-8, and a content hash has no business
    # decoding them: text mode would both corrupt the evidence (newline
    # translation) and crash on the first undecodable byte.
    try:
        tracked = subprocess.run(
            # --binary carries the actual changed bytes.  A plain diff of a
            # modified binary input — a .npy fixture, say — records only
            # "Binary files differ" plus abbreviated blob hashes, which is not
            # evidence of what the run actually read.
            #
            # --no-ext-diff and --no-textconv make the diff independent of the
            # environment it runs in.  git otherwise honours an external diff
            # driver (GIT_EXTERNAL_DIFF, diff.external, or a .gitattributes
            # textconv), and a driver that prints nothing turns a dirty tree
            # into an empty diff — which this function would then record as a
            # clean checkout of the recorded commit.
            ["git", "diff", "HEAD", "--binary", "--no-ext-diff", "--no-textconv"],
            cwd=REPO_ROOT,
            capture_output=True,
            check=True,
        ).stdout
        status = subprocess.run(
            # -z emits raw, NUL-delimited paths.  The default line-oriented form
            # quotes any path containing a space, a quote, or a non-ASCII byte,
            # so the parsed path would not exist on disk and the file's real
            # contents would never reach this hash.
            ["git", "status", "--porcelain", "-z", "--untracked-files=all"],
            cwd=REPO_ROOT,
            capture_output=True,
            check=True,
        ).stdout
    except (OSError, subprocess.CalledProcessError) as exc:
        raise SystemExit(
            "Cannot record source provenance: reading the working-tree "
            "divergence from HEAD failed."
        ) from exc
    untracked = _untracked_paths(status)
    if not tracked and not untracked:
        return None
    # Every field is length-prefixed.  Separator bytes alone do not frame this
    # stream, because a file's *contents* may legally contain them: an untracked
    # file holding the separator sequence could otherwise imitate a second file,
    # so two different working trees would record the same evidence.  A length
    # cannot be imitated by the bytes it counts.
    hasher = hashlib.sha256()

    def absorb(label: bytes, payload: bytes) -> None:
        hasher.update(label)
        hasher.update(len(payload).to_bytes(8, "big"))
        hasher.update(payload)

    absorb(b"tracked-diff", tracked)
    absorb(b"untracked-count", len(untracked).to_bytes(8, "big"))
    for path in untracked:
        absorb(b"untracked-path", path)
        try:
            contents = (REPO_ROOT / os.fsdecode(path)).read_bytes()
        except IsADirectoryError as exc:
            # git reports an untracked directory as a single record only when it
            # is a repository of its own, which this one cannot read or hash.
            raise SystemExit(
                "Cannot record source provenance: the untracked path "
                f"{os.fsdecode(path)!r} is a directory, which git reports as a "
                "single entry when it contains its own .git — a nested clone or "
                "worktree. Its contents cannot be hashed as evidence. Move it "
                "outside the repository, or add it to .gitignore if it cannot "
                "affect a generated result."
            ) from exc
        except OSError as exc:
            # Fail closed.  A placeholder standing in for unreadable contents
            # gives two different working trees the same patch hash, which is
            # exactly the evidence this hash exists to provide.
            raise SystemExit(
                "Cannot record source provenance: the untracked working-tree "
                f"input {os.fsdecode(path)!r} could not be read ({exc}). Its "
                "contents can change the generated result, so a patch hash that "
                "stood in a placeholder for them would not be evidence of "
                "anything."
            ) from exc
        absorb(b"untracked-content", contents)
    return hasher.hexdigest()


def _require_no_concealed_index_entries() -> None:
    """Refuse a tree whose index hides tracked modifications from git itself.

    ``git update-index --assume-unchanged`` and ``--skip-worktree`` both tell git
    to believe the worktree copy of an entry matches the index and to stop
    stat-ing it.  ``git diff HEAD`` and ``git status`` then report nothing for
    that path no matter how it has been edited, and since the patch hash is built
    from exactly those two commands, such a tree reproduces as
    ``source_tree_clean=true`` with no patch hash at all while the run reads
    modified source — the fail-open the patch hash exists to prevent.

    There is no honest hash to record instead: the divergence is invisible to the
    very tooling that would have to describe it, and a candidate that quietly
    hashed the worktree bytes anyway would contradict what ``git diff`` reports
    for the same commit.  Refusing is therefore the only correct answer, and it
    costs the maintainer nothing, because both bits are deliberate local settings
    they can clear.
    """

    try:
        listing = subprocess.run(
            # -v tags every index entry; a lowercase tag marks assume-unchanged
            # and 'S' marks skip-worktree.  -z emits the paths raw, for the same
            # reason `git status -z` is used above: the default form quotes any
            # path containing a space, a quote, or a non-ASCII byte, and a
            # refusal that named a path which does not exist on disk would send
            # the maintainer looking for the wrong file.
            ["git", "ls-files", "-z", "-v"],
            cwd=REPO_ROOT,
            capture_output=True,
            check=True,
        ).stdout
    except (OSError, subprocess.CalledProcessError) as exc:
        raise SystemExit(
            "Cannot record source provenance: reading the index entry flags "
            "('git ls-files -v') failed, so whether the tree hides tracked "
            "modifications from git is unknown and cannot be assumed benign."
        ) from exc
    concealed = _concealed_index_paths(listing)
    if not concealed:
        return
    joined = ", ".join(os.fsdecode(path) for path in concealed)
    raise SystemExit(
        "Cannot record source provenance: the index marks "
        f"{joined} assume-unchanged or skip-worktree. git diff and git status "
        "skip those entries, so an edit to any of them would be recorded as a "
        "clean checkout of the current commit with no patch hash describing it. "
        "Clear the bits (git update-index --no-assume-unchanged / "
        "--no-skip-worktree on those paths) and re-run."
    )


def _concealed_index_paths(listing: bytes) -> list[bytes]:
    """Sorted paths from ``git ls-files -z -v`` whose worktree state git ignores.

    Each record is a one-character tag, a space, and the raw path.  ``-v``
    lowercases the tag of an assume-unchanged entry, and ``S`` — or ``s``, when
    the entry carries both bits — is skip-worktree.  Paths stay bytes for the
    same reason the rest of this module keeps them so: a worktree may hold names
    that are not valid UTF-8, and a refusal that crashed while decoding one would
    be no refusal at all.
    """

    concealed: list[bytes] = []
    for record in listing.split(b"\0"):
        if not record:
            continue
        tag = record[:1]
        if tag.islower() or tag == b"S":
            concealed.append(record[2:])
    return sorted(concealed)


def _untracked_paths(status: bytes) -> list[bytes]:
    """Sorted untracked paths from NUL-delimited ``git status`` output.

    Each record is a two-character status code, a space, and the raw path; a
    rename or copy is followed by its origin path as a separate NUL-delimited
    field, which is consumed here so it can never be mistaken for a record of
    its own.  NUL is the one byte a path cannot contain, so this parse is exact
    for every path git can report — including paths that are not valid UTF-8.
    """

    records = iter(status.split(b"\0"))
    untracked: list[bytes] = []
    for record in records:
        if not record:
            continue
        code, path = record[:2], record[3:]
        if b"R" in code or b"C" in code:
            next(records, None)
        if code == b"??":
            untracked.append(path)
    return sorted(untracked)


def _source_tree_clean() -> bool:
    """True only when the tree matches HEAD, counting untracked inputs as dirty.

    An unknown git state surfaces as a refusal in :func:`_source_patch_sha256`
    rather than being silently recorded as clean.
    """

    return _source_patch_sha256() is None


def _reject_packaged_destination(
    candidate_dir: Path,
    parser: argparse.ArgumentParser,
) -> None:
    packaged_root = (ROOT / "src" / "shwfs_ao" / "resources").resolve()
    if candidate_dir == packaged_root or packaged_root in candidate_dir.parents:
        parser.error(
            "--candidate-dir must lie outside the packaged resource tree."
        )


if __name__ == "__main__":
    main()
