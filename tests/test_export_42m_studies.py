"""Regression tests for tools/export_42m_studies.py.

Synthetic fixtures cover the refusal paths (missing, malformed, mismatched or
ambiguous inputs).  The final test exports the real accepted evidence when
STUDIES42_FLUX_ROOT and STUDIES42_DELAY_ROOT name the extracted compact
packages; it is skipped otherwise.  Nothing here runs a simulation.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import math
import os
from pathlib import Path

import numpy as np
import pytest


TOOLS = Path(__file__).resolve().parents[1] / "tools"
spec = importlib.util.spec_from_file_location("export_42m_studies", TOOLS / "export_42m_studies.py")
studies = importlib.util.module_from_spec(spec)
spec.loader.exec_module(studies)
ExportError = studies.ExportError


def history(path: Path, frames: int = 500, **changes) -> Path:
    arrays = {
        "time_s": np.arange(frames) / 500.0,
        "pre_update_residual_opd_rms_m": np.full(frames, 2.0e-7),
        "open_loop_opd_rms_m": np.full(frames, 2.0e-6),
        "valid_measurement_fraction": np.full(frames, 0.999),
        "reconstruction_usable": np.ones(frames, dtype=bool),
        "saturation_fraction": np.zeros(frames),
    }
    for key, value in changes.items():
        if value is None:
            arrays.pop(key)
        else:
            arrays[key] = value
    np.savez(path, **arrays)
    return path


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def package(root: Path, files: dict) -> Path:
    """A compact-package directory whose listing records every given file."""
    listing = {}
    for relative, content in files.items():
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(content, Path):
            path.write_bytes(content.read_bytes())
        else:
            path.write_text(json.dumps(content))
        listing[relative] = {"bytes": path.stat().st_size, "sha256": sha(path)}
    (root / "COMPACT_PACKAGE.json").write_text(json.dumps({"schema": "test", "files": listing}))
    return root


def test_window_mean_is_half_open_arithmetic_and_counts_samples():
    values = np.arange(1000, dtype=float)
    assert studies.window_mean(values, (100, 500)) == (299.5, 400)
    assert studies.window_mean(values, (500, 1000))[1] == 500
    assert studies.window_mean(values, (100, 1000))[1] == 900
    # Mean instantaneous RMS, not the root mean square of the frame RMS values.
    assert studies.window_mean(np.array([1.0, 3.0]), (0, 2))[0] == 2.0
    for window in [(0, 1001), (500, 500), (-1, 10), (100.0, 500)]:
        with pytest.raises(ExportError):
            studies.window_mean(values, window)
    with pytest.raises(ExportError):
        studies.window_mean(np.array([1.0, np.nan]), (0, 2))


def test_paired_interval_uses_df2_t_and_keeps_the_zero_crossing():
    assert math.isclose(studies.t_quantile_df2(0.975), 4.302652729749462, rel_tol=1e-13)
    summary = studies.paired_summary([14.894791, 13.544476, 31.149443])
    assert abs(summary["mean"] - 19.862903) < 1e-6
    low, high = summary["ci95"]
    assert abs(low + 4.475983) < 2e-6 and abs(high - 44.201789) < 2e-6
    assert low < 0 < high
    with pytest.raises(ExportError):
        studies.paired_summary([1.0, 2.0])
    with pytest.raises(ExportError):
        studies.paired_summary([1.0, 2.0, float("nan")])


def test_history_loader_accepts_a_complete_record(tmp_path):
    arrays = studies.load_history(history(tmp_path / "h.npz"), 500)
    assert arrays["pre_update_residual_opd_rms_m"].shape == (500,)


@pytest.mark.parametrize("changes", [
    {"pre_update_residual_opd_rms_m": None},                                   # missing series
    {"valid_measurement_fraction": np.full(499, 0.999)},                       # short series
    {"pre_update_residual_opd_rms_m": np.r_[np.full(499, 2e-7), np.nan]},      # non-finite value
    {"pre_update_residual_opd_rms_m": np.zeros(500)},                          # zero is not a valid RMS
    {"time_s": (np.arange(500) + 0.5) / 500.0},                                # shifted time axis
    {"reconstruction_usable": np.r_[np.ones(499, dtype=bool), False]},         # unusable frame
    {"valid_measurement_fraction": np.full(500, 1.5)},                         # fraction out of range
    {"reconstruction_usable": np.ones(500)},                                   # wrong dtype
    {"pre_update_residual_opd_rms_m": np.array([object()] * 500, dtype=object)},  # needs pickle
])
def test_history_loader_refuses_malformed_records(tmp_path, changes):
    with pytest.raises(ExportError):
        studies.load_history(history(tmp_path / "h.npz", **changes), 500)


def test_history_loader_refuses_a_corrupt_archive(tmp_path):
    path = tmp_path / "h.npz"
    path.write_bytes(b"not a zip archive")
    with pytest.raises(ExportError):
        studies.load_history(path, 500)


def test_package_checks_listing_size_hash_and_paths(tmp_path):
    root = package(tmp_path / "pkg", {"a.json": {"x": 1}})
    p = studies.Package(root)
    assert p.json("a.json") == {"x": 1}
    assert "a.json" in p.consumed
    with pytest.raises(ExportError):
        p.path("a.json", "0" * 64)                     # not the accepted hash
    (root / "b.json").write_text("{}")
    with pytest.raises(ExportError):
        p.path("b.json")                               # present but unlisted
    for bad in ["../a.json", "/a.json", "./a.json", "x/../a.json"]:
        with pytest.raises(ExportError):
            p.path(bad)
    (root / "a.json").write_text(json.dumps({"x": 2}))
    with pytest.raises(ExportError):
        p.path("a.json")                               # modified after listing
    with pytest.raises(ExportError):
        studies.Package(tmp_path / "missing")


def test_package_refuses_a_symlinked_member(tmp_path):
    root = package(tmp_path / "pkg", {"a.json": {"x": 1}})
    (tmp_path / "outside.json").write_bytes((root / "a.json").read_bytes())
    (root / "a.json").unlink()
    (root / "a.json").symlink_to(tmp_path / "outside.json")
    with pytest.raises(ExportError):
        studies.Package(root).path("a.json")


def test_strict_json_refuses_non_finite_constants(tmp_path):
    path = tmp_path / "x.json"
    path.write_text('{"v": NaN}')
    with pytest.raises(ExportError):
        studies.strict_json(path)


def test_record_mapping_selects_baselines_and_the_second_attempt():
    assert studies.delay_run_key(2, 1) == "flux100000-r1"
    assert studies.delay_run_key(3, 2) == "lat3-flux100000-r2"
    assert studies.delay_directory("flux100000-r0", 2) == "records/baseline/flux100000-r0"
    assert studies.delay_directory("lat1-flux100000-r2", 1) == "records/new/lat1-flux100000-r2/output"
    assert studies.delay_directory("lat3-flux100000-r2", 3) == "attempt2/runs/lat3-flux100000-r2/output"


def ledger(classification="completed_verified", attempt=2):
    return {"events": [
        {"event": "inspected", "run_key": "lat3-flux100000-r2", "attempt": 2, "classification": "completed_but_invalid"},
        {"event": "inspected", "run_key": "lat3-flux100000-r2", "attempt": attempt, "classification": classification},
    ]}


def test_attempt_selection_uses_attempt_two(tmp_path):
    h = history(tmp_path / "h.npz")
    root = package(tmp_path / "pkg", {"attempt2/runs/LEDGER.json": ledger(),
                                      "attempt2/runs/lat3-flux100000-r2/output/history.npz": h,
                                      "records/new/lat3-flux100000-r2/launch.json": {}})
    directory, attempt = studies.select_attempt(studies.Package(root), "lat3-flux100000-r2", sha(h))
    assert directory == "attempt2/runs/lat3-flux100000-r2/output"
    assert attempt["selected_attempt"] == 2 and attempt["excluded_attempt"] == 1


@pytest.mark.parametrize("case", ["failed_attempt_has_history", "ledger_not_verified", "ledger_names_attempt_one", "wrong_history"])
def test_attempt_selection_refuses_ambiguous_or_unverified_records(tmp_path, case):
    h = history(tmp_path / "h.npz")
    files = {"attempt2/runs/LEDGER.json": ledger(), "attempt2/runs/lat3-flux100000-r2/output/history.npz": h}
    expected = sha(h)
    if case == "failed_attempt_has_history":
        files["records/new/lat3-flux100000-r2/output/history.npz"] = h
    elif case == "ledger_not_verified":
        files["attempt2/runs/LEDGER.json"] = ledger("completed_but_invalid")
    elif case == "ledger_names_attempt_one":
        files["attempt2/runs/LEDGER.json"] = ledger(attempt=1)
    else:
        expected = "0" * 64
    root = package(tmp_path / "pkg", files)
    with pytest.raises(ExportError):
        studies.select_attempt(studies.Package(root), "lat3-flux100000-r2", expected)


def test_bundle_identity_is_content_addressed_and_tampering_is_found(tmp_path):
    out = tmp_path / "build"
    out.mkdir()
    (out / "data.json").write_text('{"schema":"x"}\n')
    (out / "README.md").write_text("readme\n")
    identity, manifest = studies.finish_bundle(out, "flux42-r2", "ao-explorer.flux42-manifest.v1")
    digest = hashlib.sha256(json.dumps(manifest["files"], sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    assert identity == "flux42-r2-" + digest[:16]
    target = tmp_path / identity
    out.rename(target)
    studies.verify_bundle(target, "ao-explorer.flux42-manifest.v1")
    with pytest.raises(ExportError):
        studies.verify_bundle(target, "ao-explorer.delay42-manifest.v1")
    (target / "stray.txt").write_text("x")
    with pytest.raises(ExportError):
        studies.verify_bundle(target, "ao-explorer.flux42-manifest.v1")
    (target / "stray.txt").unlink()
    (target / "data.json").write_text('{"schema":"y"}\n')
    with pytest.raises(ExportError):
        studies.verify_bundle(target, "ao-explorer.flux42-manifest.v1")


def test_config_differences_name_every_changed_leaf():
    a = {"controller": {"latency_frames": 2, "gain": 0.3}, "reconstructor": {"alpha": 0.001}}
    b = {"controller": {"latency_frames": 3, "gain": 0.3}, "reconstructor": {"alpha": 0.001}}
    assert studies.config_differences(a, b) == ["controller/latency_frames"]
    b["reconstructor"]["alpha"] = 0.0025
    assert studies.config_differences(a, b) == ["controller/latency_frames", "reconstructor/alpha"]


@pytest.mark.skipif(not (os.environ.get("STUDIES42_FLUX_ROOT") and os.environ.get("STUDIES42_DELAY_ROOT")),
                    reason="the accepted evidence packages are local only")
def test_real_evidence_matches_the_acceptance_anchors(tmp_path):
    sha_exporter = studies.sha256_file(TOOLS / "export_42m_studies.py")
    (tmp_path / "f").mkdir()
    (tmp_path / "d").mkdir()
    flux = studies.export_flux(Path(os.environ["STUDIES42_FLUX_ROOT"]), tmp_path / "f", sha_exporter)
    delay = studies.export_delay(Path(os.environ["STUDIES42_DELAY_ROOT"]), tmp_path / "d", sha_exporter)
    data = json.loads((tmp_path / "f" / "data.json").read_text())
    assert [len(run["pre_update_residual_rms_nm"]) for run in data["runs"].values()] == [1000, 1000]
    assert {k: v["samples"] for k, v in data["summaries"].items()} == {"early": 400, "late": 500, "full": 900}
    assert data["images"]["late"] is None
    pre = np.array(data["runs"]["faint"]["pre_update_residual_rms_nm"]) - np.array(data["runs"]["bright"]["pre_update_residual_rms_nm"])
    assert abs(pre[500:].mean() - 77.732413) < 5e-7
    d = json.loads((tmp_path / "d" / "data.json").read_text())
    assert len(d["records"]) == 9 and all(len(r["pre_update_residual_rms_nm"]) == 500 for r in d["records"])
    chosen = [r for r in d["records"] if r["run_key"] == "lat3-flux100000-r2"]
    assert len(chosen) == 1 and chosen[0]["attempt"] == 2
    assert all(r["source"] == "reused baseline" for r in d["records"] if r["delay_frames"] == 2)
    for record in d["records"]:
        values = np.array(record["pre_update_residual_rms_nm"][100:500])
        assert record["summary"]["mean_pre_update_rms_nm"] == pytest.approx(values.mean(), rel=1e-13)
        assert record["summary"]["rms_of_frame_pre_update_rms_nm"] > record["summary"]["mean_pre_update_rms_nm"]
    assert flux["original_bright_history_sha256"] == delay["baseline_r2_history_sha256"]
    assert d["excursion_r2"]["first_rise_frames"] == [338, 344] and d["excursion_r2"]["frames_valid_below_0_995_in_window"] == 137
