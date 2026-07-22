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

import importlib.util
import json
from pathlib import Path
import sys

import pytest

from shwfs_ao.validation.regression import (
    load_cross_backend_baseline,
    validate_cross_backend_baseline,
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
        "source_commit": "f" * 40,
        "source_tree_clean": True,
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
        # The synthetic candidate differs from the packaged baseline only in
        # its generator commit, so the complete structural diff must contain
        # exactly that path: everything else is covered and unchanged.
        document = _candidate_document()
        diff = script._build_diff(document, script._canonical_bytes(document))
        assert [entry["path"] for entry in diff["changes"]] == [
            "generator.source_commit"
        ]


_PLATFORM_PROSE = {"linux": "Linux", "macos-arm64": "macOS-arm64"}


def _lock_header(platform_tag: str | None = None) -> str:
    """A lock header declaring a platform, as the verifier requires."""

    tag = platform_tag or script._current_platform_tag()
    return f"# Exact environment resolved for this interpreter on {_PLATFORM_PROSE[tag]}.\n"


class TestEnvironmentVerification:
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
        other = "linux" if current != "linux" else "macos-arm64"
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
        assert accepted["generator"]["source_commit"] == "f" * 40
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
