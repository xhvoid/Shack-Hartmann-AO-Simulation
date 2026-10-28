"""Content-completeness of the cross-backend candidate diff and acceptance.

The reviewed machine-readable diff is the acceptance gate: whatever it does
not cover can be edited after review without detection.  These tests pin
that the diff covers the complete candidate byte-for-byte — tolerances,
criteria, rationale, hashes, environment, and formatting alike — and that
the acceptance command refuses a candidate directory whose contents (or the
packaged baseline itself) changed after the diff was generated.  They drive
the script's own functions on copies of the packaged baseline, so no
comparison suite runs and no packaged resource is touched.
"""

from __future__ import annotations

import hashlib
import importlib.util
import itertools
import json
from pathlib import Path
import subprocess
import sys
import types

import numpy as np
import pytest

from shwfs_ao.core.hashing import stable_hash
from shwfs_ao.validation.numerical_identity import (
    numerical_input_failure,
    numerical_input_record,
    numerical_input_values,
)
from shwfs_ao.validation.regression import (
    load_cross_backend_baseline,
    validate_cross_backend_baseline,
    validate_cross_backend_report,
)


ROOT = Path(__file__).resolve().parents[2]

_SCRIPT_SPEC = importlib.util.spec_from_file_location(
    "cross_backend_candidate_script_for_tests",
    ROOT / "scripts" / "generate_cross_backend_candidate.py",
)
assert _SCRIPT_SPEC is not None and _SCRIPT_SPEC.loader is not None
script = importlib.util.module_from_spec(_SCRIPT_SPEC)
sys.modules[_SCRIPT_SPEC.name] = script
_SCRIPT_SPEC.loader.exec_module(script)


def _git_init(repository: Path) -> None:
    """A throwaway repository with one commit, so HEAD exists."""

    def run(*arguments: str) -> None:
        subprocess.run(
            ["git", *arguments],
            cwd=repository,
            check=True,
            capture_output=True,
            text=True,
        )

    run("init", "--quiet")
    run("config", "user.email", "contract-test@example.invalid")
    run("config", "user.name", "Contract Test")
    (repository / "tracked.txt").write_text("tracked\n", encoding="utf-8")
    run("add", "tracked.txt")
    run("commit", "--quiet", "--message", "seed")


@pytest.fixture()
def packaged_tree(tmp_path, monkeypatch):
    """A throwaway copy of the packaged baseline the script may write to."""

    destination = (
        tmp_path
        / "src"
        / "shwfs_ao"
        / "resources"
        / "reference_metrics"
        / "cross_backend"
    )
    destination.mkdir(parents=True)
    source = (
        ROOT
        / "src"
        / "shwfs_ao"
        / "resources"
        / "reference_metrics"
        / "cross_backend"
        / "cross_backend_baseline.json"
    )
    (destination / "cross_backend_baseline.json").write_bytes(
        source.read_bytes()
    )
    monkeypatch.setattr(script, "ROOT", tmp_path)
    monkeypatch.setattr(script, "DESTINATION_DIR", destination)
    return destination


def _candidate_document() -> dict:
    document = json.loads(json.dumps(dict(load_cross_backend_baseline())))
    del document["acceptance"]
    document["generator"] = {
        "generator_name": script.GENERATOR_NAME,
        "generator_version": script.GENERATOR_VERSION,
        # A real commit of this repository: acceptance verifies the object
        # exists, so a placeholder hash is no longer an acceptable stand-in.
        "source_commit": script._source_commit(),
        "source_tree_clean": True,
        # Written unconditionally by generation — null is the recorded evidence
        # that the tree matched HEAD, not the absence of evidence — so a
        # fixture that omitted it would diff against every real baseline on a
        # field neither document actually disagrees about.
        "source_patch_sha256": None,
    }
    return document


def _write_candidate(candidate_dir: Path, document: dict) -> dict:
    """Mimic generation: write candidate bytes plus the reviewed diff."""

    candidate_dir.mkdir(parents=True, exist_ok=True)
    candidate_bytes = script._canonical_bytes(document)
    diff = script._build_diff(document, candidate_bytes)
    (candidate_dir / script.CANDIDATE_FILE).write_bytes(candidate_bytes)
    (candidate_dir / script.DIFF_JSON).write_bytes(
        script._canonical_bytes(diff)
    )
    (candidate_dir / script.DIFF_MARKDOWN).write_text(
        script._render_diff_markdown(diff),
        encoding="utf-8",
    )
    return diff


class TestDiffContentCompleteness:
    def test_diff_records_content_hashes_of_candidate_and_baseline(
        self,
        packaged_tree,
        tmp_path,
    ):
        document = _candidate_document()
        candidate_bytes = script._canonical_bytes(document)
        diff = script._build_diff(document, candidate_bytes)
        assert diff["schema_name"] == "shwfs_ao.cross_backend_diff"
        assert diff["baseline_present"] is True
        import hashlib

        assert diff["candidate_sha256"] == (
            hashlib.sha256(candidate_bytes).hexdigest()
        )
        assert diff["current_baseline_sha256"] == (
            hashlib.sha256(
                (packaged_tree / "cross_backend_baseline.json").read_bytes()
            ).hexdigest()
        )

    def test_a_tolerance_change_appears_in_the_reviewed_changes(
        self,
        packaged_tree,
    ):
        document = _candidate_document()
        metric = next(
            metric
            for comparison in document["comparisons"]
            if comparison["comparison_kind"] == "strehl_ratio"
            for metric in comparison["metrics"]
            if metric["name"] == "strehl_abs_difference"
        )
        metric["pass_criterion"]["tolerance"] = 0.5
        diff = script._build_diff(document, script._canonical_bytes(document))
        tolerance_changes = [
            entry
            for entry in diff["changes"]
            if entry["path"]
            == (
                "comparisons[strehl_ratio]"
                ".metrics[strehl_abs_difference].pass_criterion.tolerance"
            )
        ]
        assert tolerance_changes == [
            {
                "path": (
                    "comparisons[strehl_ratio]"
                    ".metrics[strehl_abs_difference].pass_criterion.tolerance"
                ),
                "old": 0.005,
                "new": 0.5,
            }
        ]
        rendered = script._render_diff_markdown(diff)
        assert "pass_criterion.tolerance" in rendered

    def test_markdown_diff_escapes_structural_characters_in_values(self):
        # A recorded unit, path, or value containing a pipe or a newline must not
        # split a table row or inject extra Markdown into the reviewed diff.
        diff = {
            "baseline_present": True,
            "old_config_hash": "a" * 64,
            "new_config_hash": "b" * 64,
            "current_baseline_sha256": "c" * 64,
            "candidate_sha256": "d" * 64,
            "metrics": [
                {
                    "comparison_kind": "closed_loop_residual",
                    "metric": "native_backend_name",
                    "old_value": "native",
                    "new_value": "a|b\nc",
                }
            ],
            "numerical_inputs": [],
            "changes": [
                {
                    "path": "comparisons[k].metrics[m].units",
                    "old": "ratio",
                    "new": "x | y",
                }
            ],
        }
        rendered = script._render_diff_markdown(diff)
        assert "a\\|b<br>c" in rendered
        assert "x \\| y" in rendered
        # The raw, unescaped injected forms never reach the rendered table.
        assert "a|b" not in rendered
        assert "| y" not in rendered.replace("\\| y", "")

    def test_an_unchanged_candidate_reports_only_generator_changes(
        self,
        packaged_tree,
    ):
        # Both halves are stated against the baseline's own recorded commit
        # rather than against HEAD.  Whether HEAD happens to equal the commit
        # the packaged baseline was accepted at is a property of when this test
        # runs, not of the diff, and pinning it to HEAD made the test pass
        # immediately after a regeneration and fail on the next commit.
        baseline_commit = dict(load_cross_backend_baseline())["generator"][
            "source_commit"
        ]

        # Regenerated at that commit, the candidate differs from the packaged
        # baseline in nothing at all, so the diff must be empty rather than
        # reporting a change it cannot name.
        document = _candidate_document()
        document["generator"]["source_commit"] = baseline_commit
        unchanged = script._build_diff(
            document, script._canonical_bytes(document)
        )
        assert unchanged["changes"] == []

        # Moved to a different real commit and otherwise untouched, the
        # complete structural diff must contain exactly that one path:
        # everything else is covered and genuinely unchanged.  A real commit,
        # because acceptance verifies the object exists.
        history = subprocess.run(
            ["git", "rev-list", "-n", "10", "HEAD"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=True,
        ).stdout.split()
        other_commit = next(
            commit for commit in history if commit != baseline_commit
        )
        document["generator"]["source_commit"] = other_commit
        diff = script._build_diff(document, script._canonical_bytes(document))
        assert [entry["path"] for entry in diff["changes"]] == [
            "generator.source_commit"
        ]


# Longest line a reviewed Markdown diff may contain: a table row of short
# fields or one evaluator failure message.  Rendering the witness subtree as a
# plain leaf put 136,574 characters on a single line for the 343f3c1 -> a66db3d
# (schema v1 -> v2) baseline diff.
_REVIEWABLE_LINE_CHARACTERS = 300


def _reviewable_markdown(diff: dict) -> str:
    rendered = script._render_diff_markdown(diff)
    longest = max(rendered.splitlines(), key=len)
    assert len(longest) <= _REVIEWABLE_LINE_CHARACTERS, longest[:200]
    return rendered


def _rewitness(document: dict, name: str, values: np.ndarray) -> None:
    """Replace one fixture witness exactly as generation would record it.

    The raw fixture hash is re-derived from the new samples too, so the
    candidate stays a valid report and only the samples differ in substance.
    """

    record = document["numerical_inputs"][name]
    source_hash = stable_hash(values, namespace="cross_backend_fixture")
    document["numerical_inputs"][name] = numerical_input_record(
        values,
        source_hash=source_hash,
        configuration_hash=record["configuration_hash"],
    )
    document["fixture_hashes"][name] = source_hash
    validate_cross_backend_report(document)


def _witness(diff: dict, name: str) -> dict:
    (entry,) = [
        entry for entry in diff["numerical_inputs"] if entry["witness"] == name
    ]
    return entry


def _scaled_largest_sample(name: str, factor: float) -> dict:
    """A candidate whose largest-magnitude sample of ``name`` is scaled."""

    document = _candidate_document()
    values = numerical_input_values(document["numerical_inputs"][name]).copy()
    index = np.unravel_index(int(np.nanargmax(np.abs(values))), values.shape)
    scaled = values[index] * factor
    assert scaled != values[index]
    values[index] = scaled
    _rewitness(document, name, values)
    return document


class TestWitnessReview:
    """The reviewed diff tells roundoff from input drift without printing blobs.

    Each witness present on both sides is compared at the evaluator's own
    ``NUMERICAL_INPUTS`` tolerances with the candidate as the observation and
    the packaged baseline as the expectation, and its verdict is the one
    ``numerical_input_failure`` returns for that pair.
    """

    def test_roundoff_in_one_sample_is_within_the_contract_tolerance(
        self,
        packaged_tree,
    ):
        document = _scaled_largest_sample("static_opd_m", 1.0 + 1.0e-15)
        diff = script._build_diff(document, script._canonical_bytes(document))
        witness = _witness(diff, "static_opd_m")
        assert witness["change"] == "changed"
        assert witness["changed_fields"] == ["data", "source_hash", "values_sha256"]
        comparison = witness["comparison"]
        assert comparison["shape_equal"] is True
        assert comparison["nan_mask_equal"] is True
        assert comparison["max_abs_delta"] > 0.0
        # A few ulp of a ~1.7e-7 m sample against 1e-20 m + 1e-12 * |sample|.
        assert 0.0 < comparison["max_delta_over_allowed"] < 1.0e-2
        assert comparison["passes_contract"] is True
        assert comparison["contract_failure"] is None
        for other in diff["numerical_inputs"]:
            if other["witness"] != "static_opd_m":
                assert other["change"] == "unchanged"
                assert other["comparison"]["max_abs_delta"] == 0.0
        # Acceptance compares the recomputed diff with the one read back from
        # disk, so the reported magnitudes must survive the JSON round trip.
        assert json.loads(script._canonical_bytes(diff)) == diff

        rendered = _reviewable_markdown(diff)
        old = load_cross_backend_baseline()["numerical_inputs"]["static_opd_m"]
        new = document["numerical_inputs"]["static_opd_m"]
        row = next(
            line for line in rendered.splitlines()
            if line.startswith("| `static_opd_m` | changed |")
        )
        assert f"`{old['values_sha256'][:12]}` → `{new['values_sha256'][:12]}`" in row
        assert "| same |" in row  # configuration_hash
        assert any(
            line.startswith("| `static_opd_m` | 1e-20 m_opd")
            and line.endswith("| equal | pass |")
            for line in rendered.splitlines()
        )
        assert "Contract failures:" not in rendered
        assert new["data"] not in rendered and old["data"] not in rendered

    def test_a_relative_drift_of_1e_9_exceeds_the_contract_tolerance(
        self,
        packaged_tree,
    ):
        document = _scaled_largest_sample("static_opd_m", 1.0 + 1.0e-9)
        diff = script._build_diff(document, script._canonical_bytes(document))
        comparison = _witness(diff, "static_opd_m")["comparison"]
        assert comparison["max_delta_over_allowed"] > 1.0e2
        assert comparison["passes_contract"] is False
        # The verdict is the evaluator's, not a re-derivation of it.
        assert comparison["contract_failure"] == numerical_input_failure(
            "static_opd_m",
            document["numerical_inputs"]["static_opd_m"],
            load_cross_backend_baseline()["numerical_inputs"]["static_opd_m"],
        )
        assert comparison["contract_failure"].startswith("sample ")

        rendered = _reviewable_markdown(diff)
        assert any(
            line.startswith("| `static_opd_m` | 1e-20 m_opd")
            and line.endswith("| equal | fail |")
            for line in rendered.splitlines()
        )
        assert (
            f"- `static_opd_m`: {comparison['contract_failure']}" in rendered
        )

    @pytest.mark.parametrize(
        ("name", "rendered_shape", "nan_mask", "failure"),
        (
            ("time_grid_s", "[4] → [5]", "n/a", "shape observed=(5,) expected=(4,)"),
            (
                "atmosphere_opd_cube_m",
                "[4, 48, 48]",
                "differs",
                "non-finite pupil-mask locations differ",
            ),
        ),
    )
    def test_a_shape_or_nan_mask_change_is_reported_and_fails(
        self,
        packaged_tree,
        name,
        rendered_shape,
        nan_mask,
        failure,
    ):
        document = _candidate_document()
        values = numerical_input_values(document["numerical_inputs"][name]).copy()
        if name == "time_grid_s":
            values = np.append(values, values[-1] + (values[1] - values[0]))
        else:
            # One pupil-mask sample becomes finite; every other sample is kept.
            values[np.unravel_index(int(np.argmax(np.isnan(values))), values.shape)] = 0.0
        _rewitness(document, name, values)
        diff = script._build_diff(document, script._canonical_bytes(document))
        comparison = _witness(diff, name)["comparison"]
        assert comparison["shape_equal"] is (name != "time_grid_s")
        assert comparison["nan_mask_equal"] is (
            None if name == "time_grid_s" else False
        )
        assert comparison["passes_contract"] is False
        assert comparison["contract_failure"] == failure

        rendered = _reviewable_markdown(diff)
        assert f"| `{name}` | changed | {rendered_shape} |" in rendered
        assert any(
            line.startswith(f"| `{name}` |") and line.endswith(f"| {nan_mask} | fail |")
            for line in rendered.splitlines()
        )
        assert f"- `{name}`: {failure}" in rendered

    def test_a_dm_payload_change_is_fingerprinted_not_printed(
        self,
        packaged_tree,
    ):
        document = _candidate_document()
        record = document["numerical_inputs"]["native_dm"]
        old_payload = record["backend_source_payload"]
        record["backend_source_payload"] = old_payload.replace("{", "{ ", 1)
        diff = script._build_diff(document, script._canonical_bytes(document))
        witness = _witness(diff, "native_dm")
        assert witness["changed_fields"] == ["backend_source_payload"]
        # The samples did not move, and the evaluator's check does not read
        # the payload, so the contract still passes.
        assert witness["comparison"]["passes_contract"] is True
        assert witness["new"]["backend_source_payload"] == {
            "characters": len(old_payload) + 1,
            "sha256": hashlib.sha256(
                record["backend_source_payload"].encode("utf-8")
            ).hexdigest(),
        }
        # The machine-readable change list still carries the payload in full.
        assert {
            "path": "numerical_inputs.native_dm.backend_source_payload",
            "old": old_payload,
            "new": record["backend_source_payload"],
        } in diff["changes"]

        rendered = _reviewable_markdown(diff)
        new_digest = witness["new"]["backend_source_payload"]["sha256"]
        assert (
            f"- `native_dm` backend_source_payload: {len(old_payload)} chars, "
            f"SHA-256 `{witness['old']['backend_source_payload']['sha256'][:12]}` "
            f"→ {len(old_payload) + 1} chars, SHA-256 `{new_digest[:12]}`"
        ) in rendered
        assert old_payload not in rendered
        assert record["backend_source_payload"] not in rendered
        assert "numerical_inputs.native_dm" not in rendered

    def test_an_undecodable_baseline_witness_is_reported_not_compared(
        self,
        packaged_tree,
    ):
        # The packaged baseline is not re-validated by the diff, so a record it
        # cannot decode must be named in the review rather than crash it.
        baseline_path = packaged_tree / "cross_backend_baseline.json"
        baseline = json.loads(baseline_path.read_text(encoding="utf-8"))
        baseline["numerical_inputs"]["static_opd_m"]["note"] = "x" * 500
        baseline_path.write_bytes(script._canonical_bytes(baseline))

        document = _candidate_document()
        diff = script._build_diff(document, script._canonical_bytes(document))
        witness = _witness(diff, "static_opd_m")
        assert witness["change"] == "changed"
        assert witness["changed_fields"] == ["note"]
        assert witness["comparison"] is None
        assert witness["old"]["decode_error"] == (
            "numerical input must have exactly the required fields"
        )
        assert witness["new"]["decode_error"] is None

        rendered = _reviewable_markdown(diff)
        assert "- `static_opd_m` note: not summarised" in rendered
        assert (
            "- `static_opd_m` (old side does not decode): numerical input must "
            "have exactly the required fields"
        ) in rendered
        assert "x" * 100 not in rendered

    def test_a_v1_baseline_diff_summarises_the_added_witnesses(
        self,
        packaged_tree,
    ):
        # The 343f3c1 -> a66db3d acceptance: the old baseline is schema v1 and
        # carries no witnesses at all, so every witness is added at once.
        baseline_path = packaged_tree / "cross_backend_baseline.json"
        v1_baseline = json.loads(baseline_path.read_text(encoding="utf-8"))
        del v1_baseline["numerical_inputs"]
        v1_baseline["artifact_schema_version"] = 1
        baseline_path.write_bytes(script._canonical_bytes(v1_baseline))

        document = _candidate_document()
        diff = script._build_diff(document, script._canonical_bytes(document))
        records = document["numerical_inputs"]
        assert [entry["witness"] for entry in diff["numerical_inputs"]] == sorted(
            records
        )
        assert all(
            entry["change"] == "added"
            and entry["old"] is None
            and entry["comparison"] is None
            for entry in diff["numerical_inputs"]
        )
        # Complete for machines: the added subtree is recorded verbatim.
        assert [
            entry for entry in diff["changes"]
            if entry["path"].startswith("numerical_inputs")
        ] == [{"path": "numerical_inputs", "old": None, "new": records}]

        rendered = _reviewable_markdown(diff)
        for name, record in records.items():
            assert (
                f"| `{name}` | added | {record['shape']} | "
                f"`{record['values_sha256'][:12]}` | "
                f"`{record['source_hash'][:12]}` | "
                f"`{record['configuration_hash'][:12]}` | n/a |"
            ) in rendered
            assert record["data"][:40] not in rendered
            for payload in ("source_payload", "backend_source_payload"):
                if record[payload] is not None:
                    assert record[payload][:40] not in rendered
        assert "None: no witness is present and decodable on both sides" in rendered
        assert "| `artifact_schema_version` | 1 | 2 |" in rendered
        assert "`numerical_inputs`" not in rendered
        assert len(rendered) < 20_000


# The declared prose for each tag, inverted from the script's own table so a
# new platform can never be added to one side alone.
_PLATFORM_PROSE = {tag: name for name, tag in script._LOCK_PLATFORMS.items()}


def _lock_header(platform_tag: str | None = None) -> str:
    """A lock header declaring a platform and architecture, as required."""

    tag = platform_tag or script._current_platform_tag()
    return f"# Exact environment resolved for this interpreter on {_PLATFORM_PROSE[tag]}.\n"


@pytest.mark.parametrize("version", [(3, 10), (3, 12), (3, 13), (3, 15)])
def test_candidate_generation_rejects_unsupported_python(version):
    with pytest.raises(SystemExit, match="unsupported on Python"):
        script._constraint_profile_name(version)


@pytest.mark.parametrize("version", [(3, 11), (3, 14)])
def test_candidate_generation_selects_an_existing_profile(version):
    assert (ROOT / script._constraint_profile_name(version)).is_file()


class TestEnvironmentVerification:
    @pytest.fixture(autouse=True)
    def supported_profile(self, monkeypatch):
        # These are lock-verification tests, runnable in the Python 3.10 core
        # lane too. Model a supported generator runtime explicitly; support
        # selection itself is tested separately below.
        select = script._constraint_profile_name
        monkeypatch.setattr(
            script, "_constraint_profile_name", lambda: select((3, 11)),
        )

    def test_constraint_pins_parse_names_versions_and_ignore_noise(self):
        pins = script._parse_constraint_pins(
            "# resolved profile\n"
            "numpy==2.5.0\n"
            "ruff==0.14.0  # inline comment\n"
            "Astropy_IERS-data==1.0\n"
            "packaging==26.0 ; python_version >= '3.9'\n"
            "-e git+https://example.invalid/repo.git#egg=self\n"
            "--find-links wheels/\n"
        )
        assert pins == {
            "numpy": "2.5.0",
            "ruff": "0.14.0",
            "astropy-iers-data": "1.0",
            "packaging": "26.0",
        }

    def test_generation_refuses_a_missing_profile_for_this_interpreter(
        self,
        tmp_path,
        monkeypatch,
    ):
        monkeypatch.setattr(script, "ROOT", tmp_path)
        with pytest.raises(SystemExit, match="Missing constraint profile"):
            script._verified_constraint_identity()

    def test_generation_refuses_a_profile_without_the_backend_pins(
        self,
        tmp_path,
        monkeypatch,
    ):
        monkeypatch.setattr(script, "ROOT", tmp_path)
        profile = tmp_path / script._constraint_profile_name()
        profile.parent.mkdir(parents=True)
        profile.write_text(_lock_header() + "numpy==1.0\n", encoding="utf-8")
        with pytest.raises(SystemExit, match="does not pin hcipy"):
            script._verified_constraint_identity()

    def test_generation_refuses_a_profile_the_environment_contradicts(
        self,
        tmp_path,
        monkeypatch,
    ):
        # numpy is installed in every lane, so a numpy pin that matches no
        # release always contradicts the running environment.
        monkeypatch.setattr(script, "ROOT", tmp_path)
        profile = tmp_path / script._constraint_profile_name()
        profile.parent.mkdir(parents=True)
        profile.write_text(
            _lock_header() + "numpy==0.0.0.dev0\nhcipy==9.9.9\n",
            encoding="utf-8",
        )
        with pytest.raises(SystemExit, match="does not satisfy"):
            script._verified_constraint_identity()

    def test_a_complete_lock_is_recorded_with_its_content_hash(
        self,
        tmp_path,
        monkeypatch,
    ):
        import hashlib

        monkeypatch.setattr(script, "ROOT", tmp_path)
        # A profile is only recorded when it is a complete lock of the running
        # environment: every installed distribution pinned at its version.
        # ``hcipy`` must be pinned even in a lane that does not install it.
        pins = dict(script._installed_distributions())
        pins.setdefault("hcipy", "9.9.9")
        profile = tmp_path / script._constraint_profile_name()
        profile.parent.mkdir(parents=True)
        profile.write_text(
            _lock_header()
            + "".join(f"{name}=={version}\n" for name, version in sorted(pins.items())),
            encoding="utf-8",
        )
        recorded_name, recorded_sha = script._verified_constraint_identity()
        assert recorded_name == script._constraint_profile_name()
        assert recorded_sha == hashlib.sha256(profile.read_bytes()).hexdigest()

    def test_generation_refuses_an_installed_but_unpinned_distribution(
        self,
        tmp_path,
        monkeypatch,
    ):
        # A profile that omits an installed distribution is not a lock; the
        # strict verifier must reject it rather than skip the gap.
        monkeypatch.setattr(script, "ROOT", tmp_path)
        pins = dict(script._installed_distributions())
        pins.setdefault("hcipy", "9.9.9")
        dropped = next(
            name for name in sorted(pins) if name not in ("numpy", "hcipy")
        )
        del pins[dropped]
        profile = tmp_path / script._constraint_profile_name()
        profile.parent.mkdir(parents=True)
        profile.write_text(
            _lock_header()
            + "".join(f"{name}=={version}\n" for name, version in sorted(pins.items())),
            encoding="utf-8",
        )
        with pytest.raises(SystemExit, match="is installed but"):
            script._verified_constraint_identity()

    def test_source_tree_cleanliness_is_reported_as_a_boolean(self):
        assert isinstance(script._source_tree_clean(), bool)

    def test_untracked_paths_survive_quoting_renames_and_odd_bytes(self):
        # git quotes any path with a space, a quote, or a non-ASCII byte in its
        # default output; -z emits them raw, and NUL is the one byte a path
        # cannot contain.  A rename's origin path is a separate field and must
        # never be read as a status record of its own.  Paths are handled as
        # bytes, so a name that is not valid UTF-8 survives too.
        umlaut = "messkurve-fräsen.npy".encode("utf-8")
        status = (
            b"?? input data.npy\0"
            b"?? plain.npy\0"
            b'?? "quoted".npy\0'
            b"?? " + umlaut + b"\0"
            b"?? undecodable-\xff\xfe.npy\0"
            b"R  renamed/new.py\0renamed/?? origin.py\0"
            b"C  copied/new.py\0copied/old.py\0"
            b"UU conflicted.py\0"
            b" M tracked.py\0"
            b"?? nested/deep file.txt"  # no trailing NUL
        )
        assert script._untracked_paths(status) == [
            b'"quoted".npy',
            b"input data.npy",
            umlaut,
            b"nested/deep file.txt",
            b"plain.npy",
            b"undecodable-\xff\xfe.npy",
        ]
        assert script._untracked_paths(b"") == []

    def test_a_dirty_patch_hash_follows_the_contents_of_a_spaced_untracked_file(
        self,
        tmp_path,
        monkeypatch,
    ):
        # The review's reproduction: an untracked scientific input whose name
        # contains a space.  Its contents can change the generated result, so
        # two different contents must never share one patch hash.
        repository = tmp_path / "repo"
        repository.mkdir()
        _git_init(repository)
        monkeypatch.setattr(script, "REPO_ROOT", repository)
        assert script._source_patch_sha256() is None

        spaced = repository / "input data.npy"
        spaced.write_bytes(b"first contents")
        first = script._source_patch_sha256()
        assert first is not None
        spaced.write_bytes(b"second contents")
        second = script._source_patch_sha256()
        assert second is not None and second != first

    def test_a_dirty_patch_hash_follows_the_contents_of_a_tracked_binary_input(
        self,
        tmp_path,
        monkeypatch,
    ):
        # The same defect class as the untracked case: a plain `git diff HEAD`
        # reduces a modified binary to "Binary files differ" plus abbreviated
        # blob hashes, so the evidence would not bind the bytes the run read.
        # The second fixture has no NUL, so git classifies it as *text* and
        # emits its raw non-UTF-8 bytes inline — the diff must never be decoded.
        repository = tmp_path / "repo"
        repository.mkdir()
        _git_init(repository)
        (repository / "high-bytes.npy").write_bytes(b"\x93NUMPY" + b"A" * 32)
        fixture = repository / "input.npy"
        fixture.write_bytes(b"\x93NUMPY\x01\x00" + b"A" * 64)
        subprocess.run(
            ["git", "add", "input.npy", "high-bytes.npy"],
            cwd=repository,
            check=True,
            capture_output=True,
        )
        subprocess.run(
            ["git", "commit", "--quiet", "--message", "fixture"],
            cwd=repository,
            check=True,
            capture_output=True,
        )
        monkeypatch.setattr(script, "REPO_ROOT", repository)
        assert script._source_patch_sha256() is None

        fixture.write_bytes(b"\x93NUMPY\x01\x00" + b"B" * 64)
        first = script._source_patch_sha256()
        fixture.write_bytes(b"\x93NUMPY\x01\x00" + b"C" * 64)
        second = script._source_patch_sha256()
        assert first is not None and second is not None and first != second

        # A git-classified *text* file whose bytes are not valid UTF-8 must not
        # crash the hash, and its contents must still move it.
        fixture.write_bytes(b"\x93NUMPY\x01\x00" + b"A" * 64)
        (repository / "high-bytes.npy").write_bytes(b"\x93NUMPY" + b"B" * 32)
        third = script._source_patch_sha256()
        (repository / "high-bytes.npy").write_bytes(b"\x93NUMPY" + b"C" * 32)
        fourth = script._source_patch_sha256()
        assert third is not None and fourth is not None and third != fourth

    def test_the_diff_is_taken_with_every_flag_the_evidence_depends_on(self):
        """Each flag on the tracked-diff command carries a distinct guarantee.

        Read from the source, because the guarantees are only observable in
        environments this test cannot create: ``--binary`` makes a modified
        binary contribute its bytes rather than "Binary files differ";
        ``--no-textconv`` stops a ``.gitattributes`` diff driver rewriting them;
        ``--no-ext-diff`` stops an external driver replacing them entirely.
        """

        source = (ROOT / "scripts" / "generate_cross_backend_candidate.py").read_text(
            encoding="utf-8"
        )
        start = source.index('["git", "diff", "HEAD"')
        command = source[start : source.index("]", start) + 1]
        for flag in ("--binary", "--no-ext-diff", "--no-textconv"):
            assert flag in command, (flag, command)

    def test_a_textconv_driver_cannot_rewrite_the_patch_evidence(
        self,
        tmp_path,
        monkeypatch,
    ):
        # A .gitattributes textconv driver is repository content, not
        # environment: a clone carrying one would rewrite every diff of the
        # matched files, and the recorded evidence would describe the driver's
        # output rather than the bytes the run read.
        repository = tmp_path / "repo"
        repository.mkdir()
        _git_init(repository)
        fixture = repository / "input.npy"
        fixture.write_bytes(b"\x93NUMPY\x01\x00" + b"A" * 32)
        (repository / ".gitattributes").write_text("*.npy diff=flat\n", encoding="utf-8")
        subprocess.run(
            ["git", "config", "diff.flat.textconv", "/usr/bin/true"],
            cwd=repository,
            check=True,
            capture_output=True,
        )
        subprocess.run(
            ["git", "add", "-A"], cwd=repository, check=True, capture_output=True
        )
        subprocess.run(
            ["git", "commit", "--quiet", "--message", "fixture"],
            cwd=repository,
            check=True,
            capture_output=True,
        )
        monkeypatch.setattr(script, "REPO_ROOT", repository)
        assert script._source_patch_sha256() is None

        fixture.write_bytes(b"\x93NUMPY\x01\x00" + b"B" * 32)
        first = script._source_patch_sha256()
        fixture.write_bytes(b"\x93NUMPY\x01\x00" + b"C" * 32)
        second = script._source_patch_sha256()
        # The driver collapses both revisions to nothing; the real bytes must
        # still separate them.
        assert first is not None and second is not None and first != second

    def test_an_external_diff_driver_cannot_empty_the_patch_evidence(
        self,
        tmp_path,
        monkeypatch,
    ):
        # git honours GIT_EXTERNAL_DIFF, diff.external and .gitattributes
        # textconv drivers.  A driver that prints nothing would turn a dirty
        # tree into an empty diff, which this function would then record as a
        # clean checkout of the recorded commit — a fail-open on the exact
        # claim the patch hash exists to make.
        repository = tmp_path / "repo"
        repository.mkdir()
        _git_init(repository)
        fixture = repository / "input.npy"
        fixture.write_bytes(b"\x93NUMPY\x01\x00" + b"A" * 32)
        subprocess.run(
            ["git", "add", "input.npy"], cwd=repository, check=True, capture_output=True
        )
        subprocess.run(
            ["git", "commit", "--quiet", "--message", "fixture"],
            cwd=repository,
            check=True,
            capture_output=True,
        )
        monkeypatch.setattr(script, "REPO_ROOT", repository)
        fixture.write_bytes(b"\x93NUMPY\x01\x00" + b"B" * 32)

        honest = script._source_patch_sha256()
        assert honest is not None

        monkeypatch.setenv("GIT_EXTERNAL_DIFF", "/usr/bin/true")
        assert script._source_patch_sha256() == honest
        assert script._source_tree_clean() is False

    def test_two_different_working_trees_cannot_record_the_same_evidence(
        self,
        tmp_path,
        monkeypatch,
    ):
        # The hashed stream is framed by length, not by separators alone: a
        # file whose *contents* spell the separator sequence would otherwise
        # imitate a second file, so two different trees would record one hash.
        digests = []
        for index, files in enumerate(
            (
                {"a.npy": b"\0untracked\0b.npy\0content\0X"},
                {"a.npy": b"", "b.npy": b"X"},
            )
        ):
            repository = tmp_path / f"repo{index}"
            repository.mkdir()
            _git_init(repository)
            monkeypatch.setattr(script, "REPO_ROOT", repository)
            for name, payload in files.items():
                (repository / name).write_bytes(payload)
            digest = script._source_patch_sha256()
            assert digest is not None
            digests.append(digest)
        assert digests[0] != digests[1]

    def test_an_untracked_nested_repository_names_itself_and_its_remedy(
        self,
        tmp_path,
        monkeypatch,
    ):
        # git reports a directory containing its own .git as a single '?? dir/'
        # record, so its contents cannot be hashed.  Refusing is right; refusing
        # without naming the cause or the remedy is not.
        repository = tmp_path / "repo"
        repository.mkdir()
        _git_init(repository)
        nested = repository / "vendor-data"
        nested.mkdir()
        _git_init(nested)
        monkeypatch.setattr(script, "REPO_ROOT", repository)
        assert script._untracked_paths(
            subprocess.run(
                ["git", "status", "--porcelain", "-z", "--untracked-files=all"],
                cwd=repository,
                check=True,
                capture_output=True,
            ).stdout
        ) == [b"vendor-data/"]
        with pytest.raises(SystemExit, match="is a directory") as excinfo:
            script._source_patch_sha256()
        message = str(excinfo.value)
        assert "vendor-data/" in message
        assert ".gitignore" in message and "outside the repository" in message

    def test_an_unreadable_untracked_input_fails_closed(
        self,
        tmp_path,
        monkeypatch,
    ):
        # Hashing a placeholder would give every unreadable input the same
        # evidence, which is the opposite of what the hash is for.
        repository = tmp_path / "repo"
        repository.mkdir()
        _git_init(repository)
        monkeypatch.setattr(script, "REPO_ROOT", repository)
        broken = repository / "dangling.npy"
        broken.symlink_to(repository / "missing-target.npy")
        with pytest.raises(SystemExit, match="could not be read"):
            script._source_patch_sha256()

    @pytest.mark.parametrize(
        ("bit", "remedy"),
        (
            ("--assume-unchanged", "--no-assume-unchanged"),
            ("--skip-worktree", "--no-skip-worktree"),
        ),
    )
    def test_an_index_bit_that_hides_a_modification_is_refused(
        self,
        tmp_path,
        monkeypatch,
        bit,
        remedy,
    ):
        # The review's reproduction.  Both bits tell git to believe the worktree
        # copy of an entry matches the index, so ``git diff HEAD`` and ``git
        # status`` report nothing at all for a file that has in fact been
        # edited.  The patch hash is built from exactly those two commands, so
        # such a tree reproduced as source_tree_clean=true with no patch hash
        # while the run read modified source.
        repository = tmp_path / "repo"
        repository.mkdir()
        _git_init(repository)
        monkeypatch.setattr(script, "REPO_ROOT", repository)
        assert script._source_patch_sha256() is None

        subprocess.run(
            ["git", "update-index", bit, "tracked.txt"],
            cwd=repository,
            check=True,
            capture_output=True,
        )
        (repository / "tracked.txt").write_text(
            "edited behind git's back\n",
            encoding="utf-8",
        )
        # git itself now reports an unmodified tree, which is what makes the
        # concealment silent rather than merely inconvenient.
        assert (
            subprocess.run(
                ["git", "status", "--porcelain", "--untracked-files=all"],
                cwd=repository,
                check=True,
                capture_output=True,
            ).stdout
            == b""
        )

        with pytest.raises(
            SystemExit, match="assume-unchanged or skip-worktree"
        ) as excinfo:
            script._source_patch_sha256()
        message = str(excinfo.value)
        assert "tracked.txt" in message
        assert remedy in message
        # ``_source_tree_clean()`` is defined as ``_source_patch_sha256() is
        # None``, so the refusal has to cover the clean answer as well: this
        # tree must never be reported as matching HEAD.
        with pytest.raises(SystemExit, match="assume-unchanged or skip-worktree"):
            script._source_tree_clean()

    def test_concealed_index_paths_are_parsed_as_raw_bytes(self):
        # ``git ls-files -v`` tags every index entry: a lowercase tag marks
        # assume-unchanged, 'S' marks skip-worktree, and 's' is an entry
        # carrying both.  -z emits the paths raw, so a name with a space or an
        # undecodable byte is reported exactly as it exists on disk and the
        # refusal can name it without decoding anything.
        listing = (
            b"H tracked.py\0"
            b"h assumed unchanged.npy\0"
            b"S skipped.npy\0"
            b"s both-\xff\xfe.npy\0"
            b"C modified.py\0"
            b"R removed.py\0"
        )
        assert script._concealed_index_paths(listing) == [
            b"assumed unchanged.npy",
            b"both-\xff\xfe.npy",
            b"skipped.npy",
        ]
        assert script._concealed_index_paths(b"") == []

    def test_the_platform_tag_names_the_architecture(self):
        # A lock is resolved for one operating system and one architecture; an
        # arch-blind tag could be claimed by a machine it was never resolved on.
        tag = script._current_platform_tag()
        assert tag in set(script._LOCK_PLATFORMS.values())
        assert tag in ("linux-x86-64", "linux-aarch64", "macos-arm64")
        assert tag != "linux"

        # A lock still declaring the arch-blind platform is refused outright.
        with pytest.raises(SystemExit, match="does not declare its platform"):
            script._lock_platform_tag(
                "# Exact environment resolved on Linux.\n", "stale.txt"
            )
        # Only the header declares.  The body is a list of pins, so a package
        # name, URL or note there that happens to carry a platform token must
        # not stand in for a declaration the lock never made.
        with pytest.raises(SystemExit, match="does not declare its platform"):
            script._lock_platform_tag(
                "numpy==2.5.0\n# note: wheels also published on macOS-arm64\n",
                "body-only.txt",
            )
        assert (
            script._lock_platform_tag(
                "# Exact environment resolved for CPython 3.11 on\n"
                "# Linux-x86-64: the extras.\n"
                "numpy==2.5.0\n"
                "# a later note mentioning macOS-arm64\n",
                "header-wins.txt",
            )
            == "linux-x86-64"
        )
        # The declaration is still found when the header prose wraps it across
        # comment lines, which is how the packaged locks are written.
        assert (
            script._lock_platform_tag(
                "# Exact environment resolved for CPython 3.11 on\n"
                "# Linux-x86-64: the extras.\n",
                "wrapped.txt",
            )
            == "linux-x86-64"
        )

    def test_every_packaged_lock_declares_a_platform_and_architecture(self):
        # A lock is resolved for one operating system AND one architecture, so
        # naming only the operating system does not identify the environment it
        # reproduces.  Every packaged profile must say which, and the
        # declaration has to be findable in the file as written — not only in a
        # synthetic header, which is what let the pre-fix matcher pass while
        # matching nothing in the real locks.
        locks = sorted((ROOT / "constraints").glob("*.txt"))
        assert len(locks) == 4, [lock.name for lock in locks]
        declared = {
            lock.name: script._lock_platform_tag(
                lock.read_text(encoding="utf-8"), lock.name
            )
            for lock in locks
        }
        assert set(declared.values()) <= set(script._LOCK_PLATFORMS.values())
        assert all("-" in tag for tag in declared.values()), declared
        # The lock this interpreter would actually select is one of them.
        assert (ROOT / script._constraint_profile_name()) in set(locks)

    def test_the_frozen_contract_records_the_current_ci_lock_hashes(self):
        # The CI lock hashes in the AO-REF-000 contract manifest are a
        # deliberate-change gate, not immutable evidence: the documented relock
        # procedure requires updating them in the same commit as a lock edit.
        # This pins that they were in fact updated together.
        manifest = json.loads(
            (
                ROOT
                / "src/shwfs_ao/resources/reference_metrics/refactor_contract_manifest.json"
            ).read_text(encoding="utf-8")
        )
        for item in manifest["ci_contract"]["matrix"]:
            lock = ROOT / item["constraints"]
            assert (
                hashlib.sha256(lock.read_bytes()).hexdigest()
                == item["constraints_sha256"]
            ), item["constraints"]
            assert script._lock_platform_tag(
                lock.read_text(encoding="utf-8"), lock.name
            ) == "linux-x86-64"

    def test_generation_refuses_a_foreign_platform_lock(
        self,
        tmp_path,
        monkeypatch,
    ):
        # A lock frozen for a different platform is refused even when its pins
        # satisfy the running environment: the version-only selection cannot let
        # a foreign-platform profile silently generate the baseline.
        monkeypatch.setattr(script, "ROOT", tmp_path)
        current = script._current_platform_tag()
        other = next(tag for tag in _PLATFORM_PROSE if tag != current)
        pins = dict(script._installed_distributions())
        pins.setdefault("hcipy", "9.9.9")
        profile = tmp_path / script._constraint_profile_name()
        profile.parent.mkdir(parents=True)
        profile.write_text(
            _lock_header(other)
            + "".join(f"{name}=={version}\n" for name, version in sorted(pins.items())),
            encoding="utf-8",
        )
        with pytest.raises(SystemExit, match="frozen for"):
            script._verified_constraint_identity()

    def test_a_lock_without_a_platform_declaration_is_refused(
        self,
        tmp_path,
        monkeypatch,
    ):
        monkeypatch.setattr(script, "ROOT", tmp_path)
        profile = tmp_path / script._constraint_profile_name()
        profile.parent.mkdir(parents=True)
        profile.write_text("numpy==1.0\nhcipy==1.0\n", encoding="utf-8")
        with pytest.raises(SystemExit, match="does not declare its platform"):
            script._verified_constraint_identity()


class TestGenerationOrdering:
    def test_provenance_is_established_before_the_comparison_suite_runs(
        self,
        packaged_tree,
        tmp_path,
        monkeypatch,
    ):
        # Both provenance checks can refuse and the suite takes minutes, so a
        # tree that cannot be recorded must be reported before the run, not
        # after it has been paid for and discarded.
        order: list[str] = []

        def refusing_patch() -> str | None:
            order.append("provenance")
            raise SystemExit("refused for the test")

        monkeypatch.setattr(script, "_source_patch_sha256", refusing_patch)
        monkeypatch.setattr(
            script, "_verified_constraint_identity", lambda: ("constraints/x.txt", "0" * 64)
        )
        monkeypatch.setattr(
            script,
            "_source_commit",
            lambda: order.append("commit") or "a" * 40,  # type: ignore[func-returns-value]
        )

        import shwfs_ao.validation.cross_backend as cross_backend

        def spy_suite(**kwargs: object) -> dict:
            order.append("suite")
            raise AssertionError("the suite must not run once provenance refuses")

        monkeypatch.setattr(cross_backend, "run_cross_backend_report", spy_suite)

        with pytest.raises(SystemExit, match="refused for the test"):
            script._generate_candidate(tmp_path / "candidate")
        assert order == ["commit", "provenance"]
        assert "suite" not in order

    def test_a_working_tree_that_changes_during_the_suite_is_refused(
        self,
        packaged_tree,
        tmp_path,
        monkeypatch,
    ):
        # Evidence that does not describe the tree the results came from is not
        # evidence, so a suite that dirtied the tree invalidates the run.  Each
        # side samples until two consecutive reads agree, so the stub answers in
        # pairs: a settled dirty tree before the run and a different settled one
        # after it.
        answers = iter(["a" * 64, "a" * 64, "b" * 64, "b" * 64])
        monkeypatch.setattr(script, "_source_patch_sha256", lambda: next(answers))
        monkeypatch.setattr(
            script, "_verified_constraint_identity", lambda: ("constraints/x.txt", "0" * 64)
        )
        monkeypatch.setattr(script, "_source_commit", lambda: "a" * 40)

        import shwfs_ao.validation.cross_backend as cross_backend

        monkeypatch.setattr(
            cross_backend, "run_cross_backend_report", lambda **kwargs: {"comparisons": []}
        )
        with pytest.raises(SystemExit, match="changed while the comparison suite ran"):
            script._generate_candidate(tmp_path / "candidate")

    def test_a_checkout_that_will_not_hold_still_never_reaches_the_suite(
        self,
        packaged_tree,
        tmp_path,
        monkeypatch,
    ):
        # The commit and the patch hash are separate git invocations, so a HEAD
        # that moves between them yields a pair describing two different states
        # — and the pre-run and post-run pairs could then agree field by field
        # while the suite ran against a commit neither of them names.  A
        # checkout that never presents one self-consistent identity cannot be
        # recorded at all, and refusing before the run is what saves the
        # maintainer the minutes the suite would spend producing a discard.
        moving = itertools.cycle(("a" * 40, "b" * 40))
        monkeypatch.setattr(script, "_source_commit", lambda: next(moving))
        monkeypatch.setattr(script, "_source_patch_sha256", lambda: None)
        monkeypatch.setattr(
            script,
            "_verified_constraint_identity",
            lambda: ("constraints/x.txt", "0" * 64),
        )

        import shwfs_ao.validation.cross_backend as cross_backend

        def spy_suite(**kwargs: object) -> dict:
            raise AssertionError("the suite must not run on a moving checkout")

        monkeypatch.setattr(cross_backend, "run_cross_backend_report", spy_suite)

        with pytest.raises(SystemExit, match="did not settle"):
            script._generate_candidate(tmp_path / "candidate")

    def test_the_executed_package_is_rechecked_after_the_validation_imports(
        self,
        packaged_tree,
        tmp_path,
        monkeypatch,
    ):
        # The guard walks ``sys.modules``, so it can only judge what has already
        # been imported.  ``shwfs_ao.validation.cross_backend`` — the module
        # that computes the numbers — is imported *after* the opening call, so a
        # foreign copy of it cached there would never be examined by a check
        # that ran once at the top.  The recording shim reports this checkout's
        # own file, so nothing here weakens the guard itself; it only observes
        # when the import happens relative to the guard.
        order: list[str] = []

        import shwfs_ao.validation.cross_backend as cross_backend

        class _RecordingModule(types.ModuleType):
            def __getattr__(self, name: str) -> object:
                order.append("import")
                return getattr(cross_backend, name)

        shim = _RecordingModule("shwfs_ao.validation.cross_backend")
        shim.__file__ = cross_backend.__file__
        monkeypatch.setitem(
            sys.modules, "shwfs_ao.validation.cross_backend", shim
        )
        monkeypatch.setattr(
            script,
            "_require_executed_package_is_this_checkout",
            lambda: order.append("check"),
        )
        monkeypatch.setattr(
            script,
            "_verified_constraint_identity",
            lambda: ("constraints/x.txt", "0" * 64),
        )
        monkeypatch.setattr(script, "_source_commit", lambda: "a" * 40)
        monkeypatch.setattr(script, "_source_patch_sha256", lambda: None)

        def spy_suite(**kwargs: object) -> dict:
            order.append("suite")
            raise SystemExit("stop before the suite does any work")

        monkeypatch.setattr(cross_backend, "run_cross_backend_report", spy_suite)

        with pytest.raises(SystemExit, match="stop before the suite"):
            script._generate_candidate(tmp_path / "candidate")
        assert order[0] == "check", order
        assert "check" in order[order.index("import") : order.index("suite")], order


class TestAcceptanceFreshness:
    def test_an_untampered_candidate_is_accepted_with_provenance(
        self,
        packaged_tree,
        tmp_path,
    ):
        candidate_dir = tmp_path / "candidate"
        _write_candidate(candidate_dir, _candidate_document())
        script._accept_reviewed_candidate(
            candidate_dir,
            reason="Contract-test acceptance of an unchanged candidate.",
            review_reference="AO-REF-018-TEST",
        )
        accepted = json.loads(
            (packaged_tree / "cross_backend_baseline.json").read_text(
                encoding="utf-8"
            )
        )
        validate_cross_backend_baseline(accepted)
        assert accepted["acceptance"]["reason"] == (
            "Contract-test acceptance of an unchanged candidate."
        )
        assert accepted["acceptance"]["review_reference"] == "AO-REF-018-TEST"
        assert accepted["acceptance"]["accepted_at_utc"]
        assert accepted["generator"]["source_commit"] == script._source_commit()
        manifest = json.loads(
            (
                packaged_tree.parents[1] / "resource_manifest.json"
            ).read_text(encoding="utf-8")
        )
        names = [record["logical_name"] for record in manifest["resources"]]
        assert (
            "reference_metrics/cross_backend/cross_backend_baseline.json"
            in names
        )

    def test_acceptance_refuses_a_candidate_naming_a_nonexistent_commit(
        self,
        packaged_tree,
        tmp_path,
    ):
        # 40 hexadecimal characters is a shape, not a provenance.  Acceptance is
        # the only step that runs inside the source repository, so it is the
        # only place the claimed commit can actually be looked up.
        candidate_dir = tmp_path / "candidate"
        document = _candidate_document()
        document["generator"]["source_commit"] = "f" * 40
        _write_candidate(candidate_dir, document)
        with pytest.raises(SystemExit, match="is not a commit in this repository"):
            script._accept_reviewed_candidate(
                candidate_dir,
                reason="forged commit",
                review_reference="AO-REF-018-TEST",
            )

    def test_acceptance_refuses_a_commit_that_is_not_a_commit_object(
        self,
        packaged_tree,
        tmp_path,
    ):
        # A tree or blob hash exists in the repository but is not a commit, so
        # it cannot be the origin the baseline is reproducible from.
        tree = subprocess.run(
            ["git", "rev-parse", "HEAD^{tree}"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
        candidate_dir = tmp_path / "candidate"
        document = _candidate_document()
        document["generator"]["source_commit"] = tree
        _write_candidate(candidate_dir, document)
        with pytest.raises(SystemExit, match="is not a commit in this repository"):
            script._accept_reviewed_candidate(
                candidate_dir,
                reason="tree hash",
                review_reference="AO-REF-018-TEST",
            )

    @pytest.mark.parametrize(
        ("field", "value"),
        (
            ("generator_name", "scripts/some_other_generator.py"),
            ("generator_version", "1"),
        ),
    )
    def test_acceptance_refuses_a_foreign_generator_identity(
        self,
        packaged_tree,
        tmp_path,
        field,
        value,
    ):
        # The generator block is credited as the producer of the baseline, so a
        # candidate written by something else must not be accepted under this
        # script's identity.
        candidate_dir = tmp_path / "candidate"
        document = _candidate_document()
        document["generator"][field] = value
        _write_candidate(candidate_dir, document)
        with pytest.raises(SystemExit, match=f"generator.{field} is"):
            script._accept_reviewed_candidate(
                candidate_dir,
                reason="foreign generator",
                review_reference="AO-REF-018-TEST",
            )

    def test_acceptance_retires_candidates_from_the_pre_fix_generator(
        self,
        packaged_tree,
        tmp_path,
    ):
        # Everything the provenance fixes added is invisible in the candidate
        # document: a candidate generated before them looks exactly like one
        # generated after, while its clean-tree claim was never checked against
        # concealed index entries and its commit and patch were sampled
        # non-atomically.  The generator version is the only field that can
        # separate the two, so leaving it at the pre-fix value "2" would let
        # those candidates keep passing acceptance.
        candidate_dir = tmp_path / "candidate"
        document = _candidate_document()
        document["generator"]["generator_version"] = "2"
        _write_candidate(candidate_dir, document)
        assert script.GENERATOR_VERSION != "2"
        with pytest.raises(SystemExit, match="generator.generator_version is '2'"):
            script._accept_reviewed_candidate(
                candidate_dir,
                reason="candidate from the pre-provenance-fix generator",
                review_reference="AO-REF-018-TEST",
            )

    def test_acceptance_refuses_a_clean_tree_carrying_patch_evidence(
        self,
        packaged_tree,
        tmp_path,
    ):
        # The two records contradict each other and acceptance cannot tell which
        # is true, so it refuses rather than believing one of them.
        candidate_dir = tmp_path / "candidate"
        document = _candidate_document()
        document["generator"]["source_tree_clean"] = True
        document["generator"]["source_patch_sha256"] = "a" * 64
        _write_candidate(candidate_dir, document)
        with pytest.raises(SystemExit, match="A clean tree has no divergence"):
            script._accept_reviewed_candidate(
                candidate_dir,
                reason="contradictory provenance",
                review_reference="AO-REF-018-TEST",
            )

    def test_a_post_review_tolerance_edit_is_refused(
        self,
        packaged_tree,
        tmp_path,
    ):
        # The metric values are untouched, so the pre-fix value-only diff
        # would have accepted this candidate.
        candidate_dir = tmp_path / "candidate"
        _write_candidate(candidate_dir, _candidate_document())
        tampered = json.loads(
            (candidate_dir / script.CANDIDATE_FILE).read_text(
                encoding="utf-8"
            )
        )
        for comparison in tampered["comparisons"]:
            for metric in comparison["metrics"]:
                if metric["pass_criterion"]["type"] == "abs_tolerance":
                    metric["pass_criterion"]["tolerance"] = 1.0e6
        (candidate_dir / script.CANDIDATE_FILE).write_bytes(
            script._canonical_bytes(tampered)
        )
        with pytest.raises(SystemExit, match="changed after diff generation"):
            script._accept_reviewed_candidate(
                candidate_dir,
                reason="tampered",
                review_reference="AO-REF-018-TEST",
            )

    def test_a_formatting_only_edit_is_refused(self, packaged_tree, tmp_path):
        candidate_dir = tmp_path / "candidate"
        _write_candidate(candidate_dir, _candidate_document())
        candidate_path = candidate_dir / script.CANDIDATE_FILE
        reserialized = json.dumps(
            json.loads(candidate_path.read_text(encoding="utf-8")),
            indent=4,
            sort_keys=True,
        )
        candidate_path.write_text(reserialized + "\n", encoding="utf-8")
        with pytest.raises(SystemExit, match="changed after diff generation"):
            script._accept_reviewed_candidate(
                candidate_dir,
                reason="reformatted",
                review_reference="AO-REF-018-TEST",
            )

    def test_a_baseline_change_after_diff_generation_is_refused(
        self,
        packaged_tree,
        tmp_path,
    ):
        candidate_dir = tmp_path / "candidate"
        _write_candidate(candidate_dir, _candidate_document())
        baseline_path = packaged_tree / "cross_backend_baseline.json"
        drifted = json.loads(baseline_path.read_text(encoding="utf-8"))
        drifted["acceptance"]["reason"] = "silently rewritten"
        baseline_path.write_bytes(script._canonical_bytes(drifted))
        with pytest.raises(SystemExit, match="changed after diff generation"):
            script._accept_reviewed_candidate(
                candidate_dir,
                reason="baseline drifted",
                review_reference="AO-REF-018-TEST",
            )

    def test_a_pre_rewrite_value_only_diff_is_refused(
        self,
        packaged_tree,
        tmp_path,
    ):
        # A stale diff generated by the value-only differ must never satisfy
        # the content-complete acceptance check.
        candidate_dir = tmp_path / "candidate"
        document = _candidate_document()
        _write_candidate(candidate_dir, document)
        legacy_diff = {
            "baseline_present": True,
            "old_config_hash": document["comparison_config"]["config_hash"],
            "new_config_hash": document["comparison_config"]["config_hash"],
            "metrics": [],
        }
        (candidate_dir / script.DIFF_JSON).write_bytes(
            script._canonical_bytes(legacy_diff)
        )
        with pytest.raises(SystemExit, match="changed after diff generation"):
            script._accept_reviewed_candidate(
                candidate_dir,
                reason="stale diff",
                review_reference="AO-REF-018-TEST",
            )

    def test_a_diff_in_an_earlier_diff_format_is_named_as_such(
        self,
        packaged_tree,
        tmp_path,
    ):
        # Neither document moved, only the diff format did, so the refusal says
        # that instead of reporting a post-review edit.
        candidate_dir = tmp_path / "candidate"
        diff = _write_candidate(candidate_dir, _candidate_document())
        earlier = {
            key: value for key, value in diff.items() if key != "numerical_inputs"
        }
        earlier["schema_version"] = 1
        (candidate_dir / script.DIFF_JSON).write_bytes(
            script._canonical_bytes(earlier)
        )
        with pytest.raises(
            SystemExit,
            match=(
                "shwfs_ao.cross_backend_diff version 1, but this script writes "
                f"version {script.DIFF_SCHEMA_VERSION}"
            ),
        ):
            script._accept_reviewed_candidate(
                candidate_dir,
                reason="earlier diff format",
                review_reference="AO-REF-018-TEST",
            )
