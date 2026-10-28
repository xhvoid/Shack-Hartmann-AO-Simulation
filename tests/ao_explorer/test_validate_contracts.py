"""Both supported dataset contracts validate, and v2 semantic defects, unsupported schema pairs and raw-mode misuse are refused.

The legacy case uses the preserved 180-frame dataset of the committed site as an offline fixture (copied byte for byte
behind a synthesized entry).  Every negative case copies the site, applies one defect and re-hashes the affected
member, the manifest and the entry, so the defect reaches the semantic check it targets instead of stopping at a
digest mismatch.  No AO trajectory, image or scientific record is generated.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import posixpath
import shutil
import subprocess
import sys

import pytest

import long_series
import protocol
import validate
import web_contract


DIGEST_FAILURES = ("size and SHA-256", "resolves to a matching member", "is missing", "unlisted files")


def _bundle_or_skip(web_dir: Path) -> Path:
    if not (web_dir / "data" / "current.json").is_file():
        pytest.skip("no explorer web bundle in this tree")
    return web_dir


def _run(site: Path, repo_root=None, series_dir=None):
    return validate.Checker(site).run(series_dir=series_dir, repo_root=repo_root)


def _entry(site: Path) -> dict:
    return json.loads((site / "data" / "current.json").read_text())


def _manifest_path(site: Path) -> Path:
    return site / "data" / _entry(site)["manifest"]


def _manifest(site: Path) -> dict:
    return json.loads(_manifest_path(site).read_text())


def _dataset_dir(site: Path) -> Path:
    return _manifest_path(site).parent


def _dumps(value) -> bytes:
    return (json.dumps(value, indent=1, allow_nan=False, ensure_ascii=False) + "\n").encode("utf-8")


def _copy(web_dir: Path, tmp_path: Path) -> Path:
    """What the validator reads: the datasets under data/, the page and its code directory."""

    source = _bundle_or_skip(web_dir)
    target = tmp_path / "site"
    target.mkdir(parents=True)
    shutil.copytree(source / "data", target / "data")
    shutil.copy2(source / "index.html", target / "index.html")
    for code in source.glob("code-*"):
        shutil.copytree(code, target / code.name)
    return target


def _write_manifest(site: Path, manifest: dict) -> None:
    """Write the manifest and rebind the entry to its new size and SHA-256."""

    data = _dumps(manifest)
    _manifest_path(site).write_bytes(data)
    entry_path = site / "data" / "current.json"
    entry = json.loads(entry_path.read_text())
    entry.update(manifest_bytes=len(data), manifest_sha256=hashlib.sha256(data).hexdigest())
    entry_path.write_text(json.dumps(entry, indent=2) + "\n")


def _update_refs(value, relative_to_manifest: str, data: bytes, defining_dir: str = "") -> None:
    """Point every hash-bound reference to ``relative_to_manifest`` (as seen from ``defining_dir``) at the new bytes."""

    digest = hashlib.sha256(data).hexdigest()
    if isinstance(value, dict):
        href = value.get("href")
        if isinstance(href, str) and set(value) >= {"bytes", "sha256"} and posixpath.normpath(posixpath.join(defining_dir, href)) == relative_to_manifest:
            value.update(bytes=len(data), sha256=digest)
        for item in value.values():
            _update_refs(item, relative_to_manifest, data, defining_dir)
    elif isinstance(value, list):
        for item in value:
            _update_refs(item, relative_to_manifest, data, defining_dir)


def _write_dataset_member(site: Path, relative: str, data: bytes) -> None:
    """Rewrite a member referenced from the manifest itself (display, blocks, diagnostics, scene) coherently."""

    base = _dataset_dir(site)
    (base / relative).write_bytes(data)
    manifest = _manifest(site)
    digest = hashlib.sha256(data).hexdigest()
    for item in manifest["members"]:
        if item["path"] == relative:
            item.update(bytes=len(data), sha256=digest)
    _update_refs({key: manifest[key] for key in manifest if key != "members"}, relative, data)
    _write_manifest(site, manifest)


def _write_case_member(site: Path, case_id: str, leaf: str, payload) -> None:
    """Rewrite a case-level member (case.json or one the case record references) and re-hash the chain above it."""

    base = _dataset_dir(site)
    relative = f"cases/{case_id}/{leaf}"
    data = _dumps(payload)
    (base / relative).write_bytes(data)
    manifest = _manifest(site)
    digest = hashlib.sha256(data).hexdigest()
    for item in manifest["members"]:
        if item["path"] == relative:
            item.update(bytes=len(data), sha256=digest)
    if leaf != "case.json":
        case_path = base / "cases" / case_id / "case.json"
        case = json.loads(case_path.read_text())
        _update_refs(case, relative, data, f"cases/{case_id}")
        case_data = _dumps(case)
        case_path.write_bytes(case_data)
        case_digest = hashlib.sha256(case_data).hexdigest()
        for item in manifest["members"]:
            if item["path"] == f"cases/{case_id}/case.json":
                item.update(bytes=len(case_data), sha256=case_digest)
        _update_refs(manifest["cases"], f"cases/{case_id}/case.json", case_data)
    else:
        _update_refs(manifest["cases"], relative, data)
    _write_manifest(site, manifest)


def _member(site: Path, case_id: str, leaf: str):
    return json.loads((_dataset_dir(site) / "cases" / case_id / leaf).read_text())


def _v2_or_skip(site: Path):
    manifest = _manifest(site)
    if manifest.get("schema") != web_contract.V2.manifest_schema:
        pytest.skip("the committed dataset is not a v2 (one-second) dataset")
    return manifest


# ---------------------------------------------------------------------------
# Contracts


def test_v2_contract_values_come_from_the_producer_modules():
    c = web_contract.V2
    assert c.frames == long_series.N_STEPS == 1000
    assert c.burn_in == long_series.STARTUP_EXCLUSION_FRAMES == 200
    assert c.analysis_window == (200, 1000) and c.analysis_count == 800
    assert c.block_frames == long_series.BLOCK_FRAMES == 100 and c.screen_grid_size == long_series.SCREEN_GRID_SIZE == 624
    assert c.display_count == 126 and c.display_indices[:3] == (0, 8, 16) and c.display_indices[-2:] == (992, 999)
    assert {0, 200, 999} <= set(c.display_indices) and len(set(c.display_indices)) == 126
    assert c.raw_probe_frames == (0, 200, 999) and c.opd_levels == 255 and c.opd_exterior_index == 255


def test_v1_contract_values_come_from_the_frozen_protocol():
    c = web_contract.V1
    assert c.frames == protocol.PRODUCTION_FRAMES == 180 and c.burn_in == protocol.PRODUCTION_BURN_IN == 40
    assert c.display_indices == tuple(protocol.movie_indices()) and c.display_count == 40
    assert c.raw_probe_frames == (0, 40, 179) and c.opd_levels == 256 and c.opd_exterior_index is None
    assert c.analysis_window == (40, 180) and c.analysis_count == 140


def test_contract_constants_match_the_exporters():
    # The display constants are restated for a NumPy-free validator; they must not drift from the exporters.
    pytest.importorskip("numpy")
    import binary_scene
    import long_export
    import render

    assert web_contract.V2.manifest_schema == long_export.MANIFEST_SCHEMA
    assert web_contract.V2.web_schema_version == long_export.WEB_SCHEMA_VERSION
    assert web_contract.V2.display_schema == long_export.DISPLAY_REVISION
    assert list(web_contract.V2.display_indices) == long_export.display_indices()
    assert web_contract.V2_DISPLAY_STRIDE == long_export.DISPLAY_STRIDE
    assert web_contract.V2.display_rule == long_export.DISPLAY_RULE
    assert web_contract.V2.playback_durations_s == long_export.PLAYBACK_DURATIONS_S
    assert web_contract.V2.playback_default_s == long_export.PLAYBACK_DEFAULT_S
    assert web_contract.V2.opd_levels == long_export.OPD_CODES and web_contract.V2.opd_exterior_index == long_export.OPD_EXTERIOR_INDEX
    assert web_contract.V2.frame_period_s == long_export.FRAME_PERIOD_S
    assert web_contract.PARENT_NORMALIZATION == long_export.PARENT_NORMALIZATION
    assert web_contract.PARENT_FIELDS == long_export.FIELDS
    assert {k: web_contract.IMAGE_UNITS[k] for k in long_export.IMAGE_UNITS} == long_export.IMAGE_UNITS
    assert web_contract.V1.web_schema_version == render.WEB_SCHEMA_VERSION and web_contract.V1.display_schema == render.DISPLAY_REVISION
    assert web_contract.PSF_LOG_DECADES == render.PSF_LOG_DECADES and web_contract.ATLAS_COLUMNS == render.ATLAS_COLUMNS
    assert web_contract.OPD_LIMIT_QUANTUM_M == render.OPD_LIMIT_QUANTUM_M
    assert web_contract.OPD_COLORMAP == render.OPD_CMAP and web_contract.PSF_COLORMAP == render.PSF_CMAP
    assert web_contract.PSF_DISPLAY_HALF_WIDTH_CELLS == render.PSF_DISPLAY_HALF_WIDTH_CELLS
    assert web_contract.PARENT_RECENTERING == render.PARENT_METADATA["recentering"] and web_contract.PARENT_COADDITION == render.PARENT_METADATA["coaddition"]
    assert web_contract.OBSERVATION_RENDERER_REVISION == binary_scene.RENDERER_REVISION
    assert web_contract.CONVOLUTION_POLICY == binary_scene.CONVOLUTION_POLICY


@pytest.mark.parametrize(
    "entry_schema,manifest_schema",
    [("ao-explorer.entry.v1", "ao-explorer.manifest.v3"), ("ao-explorer.entry.v2", "ao-explorer.manifest.v2"), ("ao-explorer.entry.v1", None), ("ao-explorer.entry.v1", "ao-explorer.galaxy-manifest.v3")],
)
def test_unlisted_schema_pairs_are_refused(entry_schema, manifest_schema):
    with pytest.raises(web_contract.UnsupportedContract, match="unsupported"):
        web_contract.select(entry_schema, manifest_schema)
    assert web_contract.select("ao-explorer.entry.v1", "ao-explorer.manifest.v2") is web_contract.V2
    assert web_contract.select("ao-explorer.entry.v1", "ao-explorer.manifest.v1") is web_contract.V1


# ---------------------------------------------------------------------------
# Legacy (v1) compatibility on an offline fixture built from the preserved dataset


def _v1_fixture(web_dir: Path, tmp_path: Path) -> Path:
    source = _bundle_or_skip(web_dir)
    candidates = [p.parent for p in (source / "data").glob("*/manifest.json") if json.loads(p.read_text()).get("schema") == web_contract.V1.manifest_schema]
    if len(candidates) != 1:
        pytest.skip("the committed site does not preserve exactly one v1 dataset")
    dataset = candidates[0]
    site = tmp_path / "v1-site"
    (site / "data").mkdir(parents=True)
    shutil.copytree(dataset, site / "data" / dataset.name)
    shutil.copy2(source / "index.html", site / "index.html")
    code = next(source.glob("code-*"))
    shutil.copytree(code, site / code.name)
    manifest_bytes = (dataset / "manifest.json").read_bytes()
    entry = {"schema": "ao-explorer.entry.v1", "dataset_id": dataset.name, "manifest": f"{dataset.name}/manifest.json", "manifest_bytes": len(manifest_bytes),
             "manifest_sha256": hashlib.sha256(manifest_bytes).hexdigest(), "code_build": _entry(source)["code_build"]}
    (site / "data" / "current.json").write_text(json.dumps(entry, indent=1) + "\n")
    return site


def test_preserved_v1_dataset_validates_under_the_v1_contract(web_dir, tmp_path):
    site = _v1_fixture(web_dir, tmp_path)
    report = _run(site)
    assert report["valid"], report["failures"][:10]
    assert report["contract"]["name"] == "v1" and report["contract"]["frames"] == 180 and report["contract"]["display_count"] == 40
    assert report["previous_dataset"] is None and report["checks_passed"] > 500
    # The preserved dataset's committed validation record describes the same bundle.
    record_path = web_dir / "validation" / f"manifest-validation-{report['dataset_id']}.json"
    if record_path.is_file():
        record = json.loads(record_path.read_text())
        assert (record["manifest_sha256"], record["member_count"], record["member_bytes"]) == (report["manifest_sha256"], report["member_count"], report["member_bytes"])


def test_v1_contract_refuses_a_v2_dataset_directory_beside_it(web_dir, tmp_path):
    # A v1 entry sees exactly one dataset directory under data/; a stray second one is refused.
    site = _v1_fixture(web_dir, tmp_path)
    (site / "data" / "series-other").mkdir()
    report = _run(site)
    assert any("dataset directories under data/ are exactly" in failure for failure in report["failures"]), report["failures"][:5]


def test_v1_movie_frames_are_the_frozen_rule(web_dir, tmp_path):
    site = _v1_fixture(web_dir, tmp_path)
    case = _member(site, "baseline", "case.json")
    case["time_domain"]["movie_indices"][9] = 41
    _write_case_member(site, "baseline", "case.json", case)
    report = _run(site)
    assert any("baseline: movie indices equal the frozen rule (40 unique, incl. 0, 40, 179)" in failure for failure in report["failures"]), report["failures"][:5]
    assert not [failure for failure in report["failures"] if any(word in failure for word in DIGEST_FAILURES)], report["failures"][:5]


# ---------------------------------------------------------------------------
# Unsupported or inconsistent schema combinations on the committed (v2) site


def test_unsupported_manifest_schema_is_refused(web_dir, tmp_path):
    site = _copy(web_dir, tmp_path)
    manifest = _manifest(site)
    manifest["schema"] = "ao-explorer.manifest.v3"
    _write_manifest(site, manifest)
    with pytest.raises(web_contract.UnsupportedContract, match="unsupported manifest schema"):
        _run(site)


def test_unsupported_entry_schema_is_refused(web_dir, tmp_path):
    site = _copy(web_dir, tmp_path)
    entry_path = site / "data" / "current.json"
    entry = json.loads(entry_path.read_text())
    entry["schema"] = "ao-explorer.entry.v2"
    entry_path.write_text(json.dumps(entry, indent=2) + "\n")
    with pytest.raises(web_contract.UnsupportedContract, match="unsupported schema combination"):
        _run(site)


def test_inconsistent_schema_and_web_version_are_refused(web_dir, tmp_path):
    # A v2 manifest string over v1 content, or the reverse, is not a supported contract.
    site = _copy(web_dir, tmp_path)
    manifest = _manifest(site)
    other = web_contract.V1 if manifest["schema"] == web_contract.V2.manifest_schema else web_contract.V2
    manifest["web_schema_version"] = other.web_schema_version
    _write_manifest(site, manifest)
    with pytest.raises(web_contract.UnsupportedContract, match="web_schema_version"):
        _run(site)
    site2 = _copy(web_dir, tmp_path / "second")
    manifest = _manifest(site2)
    manifest["schema"] = other.manifest_schema
    _write_manifest(site2, manifest)
    with pytest.raises(web_contract.UnsupportedContract, match="web_schema_version"):
        _run(site2)


def test_dataset_id_mismatch_is_refused(web_dir, tmp_path):
    site = _copy(web_dir, tmp_path)
    manifest = _manifest(site)
    manifest["dataset_id"] = "series-other"
    _write_manifest(site, manifest)
    with pytest.raises(validate.ValidationError, match="differs from the entry's"):
        _run(site)


# ---------------------------------------------------------------------------
# v2 semantic defects, coherently re-hashed so that only the targeted check fails


def _set(path, value):
    def mutate(payload):
        target = payload
        for key in path[:-1]:
            target = target[key]
        target[path[-1]] = value

    return mutate


def _add(path, delta):
    def mutate(payload):
        target = payload
        for key in path[:-1]:
            target = target[key]
        target[path[-1]] += delta

    return mutate


MANIFEST_DEFECTS = [
    ("analysis-count", _set(("time_domain", "analysis_count"), 799), "manifest: analysis window [200, 1000), 800 samples"),
    ("display-count", _set(("time_domain", "display_count"), 125), "manifest: display indices equal the frozen rule (126 unique, incl. 0, 200, 999)"),
    ("display-time", _set(("time_domain", "display_times_s", 3), 0.025), "manifest: display times are the frame starts"),
    ("startup-exclusion", _set(("time_domain", "startup_exclusion_frames"), 100), "manifest: startup exclusion equals the burn-in (200 frames)"),
    ("playback-durations", _set(("playback", "durations_s"), [20, 25, 35]), "playback durations are the exporter's 20, 25, 30 s"),
    ("playback-default", _set(("playback", "default_duration_s"), 15), "playback default duration is listed"),
    ("playback-interpolation", _set(("playback", "interpolation"), "linear"), "playback does not interpolate"),
    ("screen-budget", _set(("screen", "travel_budget_px"), 300.0), "screen travel budget is (screen - pupil) / 2 pixels"),
    ("summary-arithmetic", _add(("summaries", "baseline", "mean_residual_rms_nm"), 0.5), "baseline: manifest summary equals the case metrics summary"),
    ("previous-manifest-sha", _set(("previous_dataset", "manifest_sha256"), "0" * 64), "manifest SHA-256 equals the recorded"),
    ("series-id-rule", _set(("series", "production_sha256"), "f" * 64), "series id follows the producer's rule"),
]


@pytest.mark.parametrize("name,mutate,expected", MANIFEST_DEFECTS, ids=[item[0] for item in MANIFEST_DEFECTS])
def test_v2_manifest_defects_are_refused(web_dir, tmp_path, name, mutate, expected):
    site = _copy(web_dir, tmp_path)
    manifest = _v2_or_skip(site)
    mutate(manifest)
    _write_manifest(site, manifest)
    report = _run(site)
    assert not report["valid"]
    assert any(expected in failure for failure in report["failures"]), report["failures"][:5]
    assert not [failure for failure in report["failures"] if any(word in failure for word in DIGEST_FAILURES)], report["failures"][:5]


def _blocks(mutate):
    def apply(site):
        blocks = json.loads((_dataset_dir(site) / "blocks.json").read_text())
        mutate(blocks)
        _write_dataset_member(site, "blocks.json", _dumps(blocks))

    return apply


def _display(mutate):
    def apply(site):
        display = json.loads((_dataset_dir(site) / "display.json").read_text())
        mutate(display)
        _write_dataset_member(site, "display.json", _dumps(display))

    return apply


def _diagnostics(mutate):
    def apply(site):
        diagnostics = json.loads((_dataset_dir(site) / "diagnostics.json").read_text())
        mutate(diagnostics)
        _write_dataset_member(site, "diagnostics.json", _dumps(diagnostics))

    return apply


def _case_member(case_id, leaf, mutate):
    def apply(site):
        payload = _member(site, case_id, leaf)
        mutate(payload)
        _write_case_member(site, case_id, leaf, payload)

    return apply


def _first_bool_check_false(provenance):
    key = next(key for key, value in provenance["checks"].items() if value is True)
    provenance["checks"][key] = False


MEMBER_DEFECTS = [
    # frame / time / sample alignment
    ("metrics-time", _case_member("baseline", "metrics.json", _set(("per_frame", "time_s", 5), 0.006)), "baseline: metrics sample times are k / 1000 s"),
    ("metrics-frame-index", _case_member("baseline", "metrics.json", _set(("per_frame", "frame_index", 10), 11)), "baseline: metrics cover frames 0-999"),
    ("metrics-display-indices", _case_member("baseline", "metrics.json", _set(("display_indices", 1), 9)), "baseline: metrics display indices equal the frozen rule"),
    ("case-display-count", _case_member("baseline", "case.json", _set(("time_domain", "display_count"), 125)), "baseline: display indices equal the frozen rule (126 unique, incl. 0, 200, 999)"),
    ("case-movie-time", _case_member("baseline", "case.json", _set(("time_domain", "movie_times_s", 4), 0.033)), "baseline: movie times are the frame starts"),
    ("case-time-domain-differs", _case_member("baseline", "case.json", _set(("time_domain", "frame_rate_hz"), 500.0)), "baseline: case time domain equals the manifest time domain"),
    # analysis windows and counts
    ("average-sample-count", _case_member("baseline", "case.json", _set(("images", "psf_average_corrected", "sample_count"), 126)), "baseline: psf_average_corrected is the 800-sample average"),
    ("average-window", _case_member("baseline", "case.json", _set(("images", "psf_average_corrected", "window_frames"), [100, 1000])), "baseline: psf_average_corrected names the analysis window"),
    ("observation-window", _case_member("baseline", "observation.json", _set(("window",), [100, 1000])), "baseline: observation is the [200, 1000) equal-weight average"),
    # atlas indices and bounds
    ("atlas-duplicate-tile", _case_member("baseline", "case.json", _set(("images", "residual", "rectangles_xywh", 9), [0, 0, 52, 52])), "baseline: residual tiles are 52 x 52 px in the 8-column atlas layout"),
    ("atlas-frame-index", _case_member("baseline", "case.json", _set(("images", "atmosphere", "frame_indices", 1), 9)), "baseline: atmosphere atlas tiles cover the 126 movie frames inside the PNG"),
    ("atlas-out-of-bounds", _case_member("baseline", "case.json", _set(("images", "psf_corrected", "rectangles_xywh", 0), [0, 5000, 64, 64])), "baseline: psf_corrected atlas tiles cover the 126 movie frames inside the PNG"),
    ("atlas-tile-size", _case_member("baseline", "case.json", _set(("images", "correction", "tile_px"), [64, 64])), "baseline: correction tiles are 52 x 52 px in the 8-column atlas layout"),
    # summary arithmetic and the mean-image distinction
    ("summary-mean-residual", _case_member("baseline", "metrics.json", _add(("summary", "mean_residual_rms_nm"), 1e-3)), "baseline: mean residual recomputed from rows"),
    ("summary-rms", _case_member("baseline", "metrics.json", _add(("summary", "root_mean_square_residual_nm"), 1e-3)), "baseline: root-mean-square residual recomputed from rows"),
    ("summary-usable-fraction", _case_member("baseline", "metrics.json", _set(("summary", "reconstruction_usable_fraction"), 0.5)), "baseline: usable-reconstruction fraction recomputed from rows"),
    ("summary-saturation-max", _case_member("baseline", "metrics.json", _set(("summary", "max_dm_saturation_fraction"), 0.5)), "baseline: DM saturation mean and maximum recomputed from rows"),
    ("summary-mean-image-conflated", _case_member("baseline", "metrics.json", _set(("definitions", "average_psf_peak_strehl_*"), "peak Strehl of the averaged image")), "baseline: definitions distinguish the mean image's Strehl from the mean instantaneous Strehl over the 800 analysis frames"),
    ("summary-mean-image-missing", _case_member("baseline", "metrics.json", _set(("summary", "average_psf_peak_strehl_corrected"), 0.0)), "baseline: metrics of the mean intensity image are recorded as separate finite quantities"),
    ("per-frame-value-vs-csv", _case_member("baseline", "metrics.json", _add(("per_frame", "residual_rms_nm", "values", 300), 1.0)), "baseline: metrics.csv rows equal the JSON per-frame records"),
    # block summaries
    ("block-mean", _blocks(_add(("cases", "baseline", "blocks", 2, "residual_rms_nm", "mean"), 1.0)), "baseline: block 2 (200-299) statistics recomputed from the per-frame rows"),
    ("block-window-flag", _blocks(_set(("cases", "baseline", "blocks", 1, "in_analysis_window"), True)), "baseline: block 1 (100-199) statistics recomputed from the per-frame rows"),
    ("block-clipped-count", _blocks(_add(("cases", "baseline", "blocks", 0, "saturation_fraction", "frames_with_any_clipped"), 1)), "baseline: block 0 (0-99) statistics recomputed from the per-frame rows"),
    ("block-definition", _blocks(_set(("definition", "block_frames"), 50)), "block definition tiles the 1000 frames in 100-frame blocks"),
    ("block-analysis-count", _blocks(_set(("cases", "baseline", "analysis_blocks", "count"), 7)), "baseline: analysis-block summary recomputed from the block means"),
    # observation parents: timing, identity and units
    ("parent-first-timestamp", _case_member("baseline", "observation.json", _set(("roles", "corrected", "parent", "first_timestamp_s"), 0.1)), "baseline: corrected parent timestamps span frames 200-999 at the frame period"),
    ("parent-quadrature", _case_member("baseline", "observation.json", _set(("roles", "corrected", "parent", "nominal_quadrature_duration_s"), 0.126)), "baseline: corrected parent timestamps span frames 200-999 at the frame period"),
    ("parent-case", _case_member("baseline", "observation.json", _set(("roles", "corrected", "parent", "case_id"), "lower-gain")), "baseline: corrected parent names this case"),
    ("parent-run-hash", _case_member("baseline", "observation.json", _set(("roles", "corrected", "parent", "run_config_hash"), "a" * 64)), "baseline: one run configuration hash across provenance, config and observation parents"),
    ("parent-wavelength", _case_member("baseline", "observation.json", _set(("roles", "uncorrected", "parent", "wavelength_m"), 2.2e-6)), "baseline: uncorrected parent wavelength"),
    ("parent-flux-unit", _case_member("baseline", "observation.json", _set(("roles", "uncorrected", "parent", "total_flux"), 0.9)), "baseline: uncorrected parent normalization"),
    # configuration, provenance, pairing
    ("config-frame-contract", _case_member("baseline", "config.json", _set(("frame_contract", "n_steps"), 180)), "baseline: config frame contract equals the v2 contract"),
    ("config-original-binding", _case_member("baseline", "config.json", _set(("original_binding", "recorded_n_steps"), 200)), "baseline: original binding names the recorded 180-frame case and differs only in n_steps"),
    ("provenance-horizon", _case_member("baseline", "provenance.json", _set(("run", "horizon_runtime_check", "exceeded_travel_budget"), True)), "baseline: the atmosphere travelled exactly the admitted distance within the budget"),
    ("provenance-check-failed", _case_member("baseline", "provenance.json", _first_bool_check_false), "baseline: every producer check recorded in the provenance passed"),
    ("pairing-status", _case_member("brighter-guide", "case.json", _set(("pairing", "status"), "different_atmosphere")), "brighter-guide: atmosphere pairing status is 'paired'"),
    # display and diagnostics
    ("display-lut-length", _display(lambda d: d["opd"]["lut_rgb_hex"].pop()), "display lookup tables have 255 OPD and 256 PSF entries"),
    ("display-limit", _display(_set(("opd", "limit_m"), 2.0e-6)), "OPD display limit is the recorded percentile rounded up to the 50 nm quantum"),
    ("diagnostics-claims-control", _diagnostics(_set(("passivity", "status"), "identical")), "diagnostics declare that no passivity control or seed-sensitivity run exists for this dataset"),
]


@pytest.mark.parametrize("name,apply,expected", MEMBER_DEFECTS, ids=[item[0] for item in MEMBER_DEFECTS])
def test_v2_member_defects_are_refused(web_dir, tmp_path, name, apply, expected):
    site = _copy(web_dir, tmp_path)
    _v2_or_skip(site)
    apply(site)
    report = _run(site)
    assert not report["valid"]
    assert any(expected in failure for failure in report["failures"]), report["failures"][:5]
    # Coherently re-hashed: no digest or reference check fails, so the defect reached its semantic check.
    assert not [failure for failure in report["failures"] if any(word in failure for word in DIGEST_FAILURES)], report["failures"][:5]


# ---------------------------------------------------------------------------
# Review R18-03: the observation parents' mean-file digest is the provenance's mean-archive digest


ARCHIVE_ROLES_AGREE = "baseline: the uncorrected and corrected parents name one mean archive with one file digest"
ARCHIVE_BOUND = "baseline: provenance binds the retained mean archive mean_psfs.npz by SHA-256"


def _archive_binding(role):
    return f"baseline: {role} observation parent's file digest equals the provenance's mean_psfs.npz digest"


def _parent(role, key, value):
    return _case_member("baseline", "observation.json", _set(("roles", role, "parent", key), value))


def _both_parents(key, value):
    def apply(site):
        _parent("uncorrected", key, value)(site)
        _parent("corrected", key, value)(site)

    return apply


def _drop_parent_key(role, key):
    return _case_member("baseline", "observation.json", lambda payload: payload["roles"][role]["parent"].pop(key))


def _drop_bound_archive(payload):
    payload["raw_evidence"]["files"].pop("mean_psfs.npz")


def _with_trailing_newlines(site):
    # Parents and provenance agree on the same digest plus a newline: equal, but not a SHA-256.
    digest = _member(site, "baseline", "provenance.json")["raw_evidence"]["files"]["mean_psfs.npz"]["sha256"] + "\n"
    _both_parents("file_sha256", digest)(site)
    _case_member("baseline", "provenance.json", _set(("raw_evidence", "files", "mean_psfs.npz", "sha256"), digest))(site)


MEAN_ARCHIVE_DEFECTS = [
    ("wrong-observation-file-digest", _both_parents("file_sha256", "a" * 64), [_archive_binding("uncorrected"), _archive_binding("corrected")]),
    ("wrong-provenance-file-digest", _case_member("baseline", "provenance.json", _set(("raw_evidence", "files", "mean_psfs.npz", "sha256"), "b" * 64)),
     [_archive_binding("uncorrected"), _archive_binding("corrected")]),
    ("inconsistent-roles", _parent("corrected", "file_sha256", "a" * 64), [ARCHIVE_ROLES_AGREE, _archive_binding("corrected")]),
    ("parent-names-another-file", _parent("uncorrected", "file", "metrics.json"),
     [ARCHIVE_ROLES_AGREE, _archive_binding("uncorrected"), "baseline: uncorrected parent records its array, file and configuration digests"]),
    ("missing-parent-file-digest", _drop_parent_key("corrected", "file_sha256"),
     [ARCHIVE_ROLES_AGREE, _archive_binding("corrected"), "baseline: corrected parent records its array, file and configuration digests"]),
    ("missing-provenance-binding", _case_member("baseline", "provenance.json", _drop_bound_archive),
     [ARCHIVE_BOUND, _archive_binding("uncorrected"), _archive_binding("corrected"), "baseline: raw-evidence file digests recorded"]),
    # A recorded failure, not a crash: an unhashable digest used to raise TypeError in the role comparison.
    ("parent-digest-not-a-string", _parent("corrected", "file_sha256", ["a" * 64]),
     [ARCHIVE_ROLES_AGREE, _archive_binding("corrected"), "baseline: corrected parent records its array, file and configuration digests"]),
    ("digests-with-trailing-newline", _with_trailing_newlines,
     [ARCHIVE_BOUND, _archive_binding("uncorrected"), _archive_binding("corrected"), "baseline: raw-evidence file digests recorded",
      "baseline: uncorrected parent records its array, file and configuration digests", "baseline: corrected parent records its array, file and configuration digests"]),
]


def _site_of(contract, web_dir, tmp_path):
    if contract == "v1":
        return _v1_fixture(web_dir, tmp_path)
    site = _copy(web_dir, tmp_path)
    _v2_or_skip(site)
    return site


@pytest.mark.parametrize("contract", ["v1", "v2"])
@pytest.mark.parametrize("name,apply,expected", MEAN_ARCHIVE_DEFECTS, ids=[item[0] for item in MEAN_ARCHIVE_DEFECTS])
def test_observation_parents_must_name_the_provenance_mean_archive(web_dir, tmp_path, contract, name, apply, expected):
    site = _site_of(contract, web_dir, tmp_path)
    apply(site)
    report = _run(site)
    assert not report["valid"]
    for reason in expected:
        assert any(reason in failure for failure in report["failures"]), (reason, report["failures"][:6])
    # Coherently re-hashed: exactly the expected checks fail, no digest or reference check.
    assert len(report["failures"]) == len(expected), report["failures"][:8]


@pytest.mark.parametrize("contract", ["v1", "v2"])
def test_the_mean_archive_binding_holds_on_the_committed_datasets(web_dir, tmp_path, contract):
    # Control: every case of the unchanged dataset passes the join, re-hashed or not.
    site = _site_of(contract, web_dir, tmp_path)
    report = _run(site)
    assert report["valid"], report["failures"][:5]
    checker = validate.Checker(site)
    checker.run(series_dir=None, repo_root=None)
    case_ids = sorted(_manifest(site)["cases"])
    assert len(case_ids) == len(protocol.CASES) == 8
    for case_id in case_ids:
        assert any(message.startswith(f"{case_id}: the uncorrected and corrected parents name one mean archive with one file digest") for message in checker.passed)
        assert f"{case_id}: provenance binds the retained mean archive mean_psfs.npz by SHA-256" in " ".join(checker.passed)
        for role in ("uncorrected", "corrected"):
            assert any(message.startswith(f"{case_id}: {role} observation parent's file digest equals the provenance's mean_psfs.npz digest") for message in checker.passed)
    _write_case_member(site, "baseline", "observation.json", _member(site, "baseline", "observation.json"))
    _write_case_member(site, "baseline", "provenance.json", _member(site, "baseline", "provenance.json"))
    rehashed = _run(site)
    assert rehashed["valid"] and rehashed["checks_passed"] == report["checks_passed"], rehashed["failures"][:5]


# ---------------------------------------------------------------------------
# The producer's record checks copied into the v2 provenance


# Written out from long_series.run_case and the observers by hand: the oracle for the parsed contract.
PRODUCER_REQUIRED_TRUE = (
    "atmosphere_rms_matches_history", "residual_rms_matches_history", "times_match_history", "times_are_k_over_1000",
    "frame_indices_complete", "usable_matches_history", "saturation_matches_history", "per_frame_reductions_within_tolerance",
    "streaming_within_tolerance", "instantaneous_unit_flux",
)
PRODUCER_DIAGNOSTICS = {
    "per_frame_independent_reductions_max": (("atmosphere_rms_abs_error_m", "residual_rms_abs_error_m", "uncorrected_strehl_abs_error",
                                              "corrected_strehl_abs_error", "held_correction_identity_max_abs_m"), True),
    "streaming_max_abs_difference": (("uncorrected", "corrected"), True),
    "mean_unit_flux": (("uncorrected", "corrected"), False),
    "archive_mean_vs_own_mean_max_abs": (("uncorrected", "corrected"), True),
    "archive_mean_vs_accumulator_max_abs": (("uncorrected", "corrected"), True),
}


# Written out from producer.run_job and ExplorerObserver.finish by hand: the oracle for the parsed v1 contract.  The v1
# producer records its verdicts without refusing, so the required checks are its bool/all verdicts (the exporter
# requires them literally true before a case is published); its analysis window is the job record's burn_in and
# n_steps, not a field of the checks mapping.
V1_PRODUCER_REQUIRED_TRUE = (
    "atmosphere_rms_matches_history", "residual_rms_matches_history", "times_match_history", "usable_matches_history",
    "saturation_matches_history", "display_frame_reductions_within_tolerance", "streaming_within_tolerance", "instantaneous_unit_flux",
)
V1_PRODUCER_DIAGNOSTICS = {"streaming_max_abs_difference": (("uncorrected", "corrected"), True), "mean_unit_flux": (("uncorrected", "corrected"), False)}
V1_PRODUCER_RECORD_LISTS = {
    "display_frame_independent_reductions": (
        ("frame", "atmosphere_rms_abs_error_m", "residual_rms_abs_error_m", "uncorrected_strehl_abs_error", "corrected_strehl_abs_error",
         "held_correction_identity_max_abs_m"),
        ("atmosphere_rms_abs_error_m", "residual_rms_abs_error_m", "uncorrected_strehl_abs_error", "corrected_strehl_abs_error",
         "held_correction_identity_max_abs_m"),
    ),
}


def test_v1_producer_checks_are_read_from_the_producer_source():
    checks = web_contract.V1.producer_checks
    assert checks is not None and checks.source == "producer.run_job" and checks.required_true == V1_PRODUCER_REQUIRED_TRUE
    assert checks.window_fields == ("burn_in", "n_steps") and checks.window_in_checks is False
    assert checks.diagnostics == V1_PRODUCER_DIAGNOSTICS and checks.record_lists == V1_PRODUCER_RECORD_LISTS
    assert set(checks.recorded) == set(V1_PRODUCER_REQUIRED_TRUE) | set(V1_PRODUCER_DIAGNOSTICS) | set(V1_PRODUCER_RECORD_LISTS) and len(checks.recorded) == 11
    # The contract is applied by the v1 exporter before a case is written and by the validator on the v1 provenance's
    # copy, with the window read from the case record's time domain (test_validate_v1_provenance.py).
    assert web_contract.V1.producer_checks is not web_contract.V2.producer_checks


def test_v2_producer_checks_are_read_from_the_producer_source(web_dir):
    checks = web_contract.V2.producer_checks
    assert checks.source == "long_series.run_case" and checks.required_true == PRODUCER_REQUIRED_TRUE
    assert checks.window_fields == ("analysis_frames", "analysis_count") and checks.window_in_checks is True and checks.record_lists == {}
    assert checks.diagnostics == PRODUCER_DIAGNOSTICS
    assert set(checks.recorded) == set(PRODUCER_REQUIRED_TRUE) | set(checks.window_fields) | set(PRODUCER_DIAGNOSTICS) and len(checks.recorded) == 17
    # The parsed modules are the ones that produced the committed dataset (its recorded production identity).
    site = _bundle_or_skip(web_dir)
    manifest = _manifest(site)
    if manifest.get("schema") != web_contract.V2.manifest_schema:
        pytest.skip("the committed dataset is not a v2 (one-second) dataset")
    recorded = json.loads((_dataset_dir(site) / "cases" / "baseline" / "provenance.json").read_text())["production_identity"]["material"]["producer_modules"]
    for name in ("long_series.py", "observer.py"):
        assert hashlib.sha256((Path(long_series.__file__).with_name(name)).read_bytes()).hexdigest() == recorded[name]


@pytest.mark.parametrize("old,new,reason", [
    ('        for name in (\n            "atmosphere_rms_matches_history",', '        for name in EXTRA + (\n            "atmosphere_rms_matches_history",', "literal tuple of names"),
    ('checks["analysis_count"] != N_STEPS - STARTUP_EXCLUSION_FRAMES', 'checks["analysis_count"] < 0', "no longer requires analysis_count"),
    ('        "mean_unit_flux": {\n            "uncorrected": float(np.sum(finish["mean_psf_uncorrected"])),\n'
     '            "corrected": float(np.sum(finish["mean_psf_corrected"])),\n        },',
     '        "mean_unit_flux": float(np.sum(finish["mean_psf_corrected"])),', "neither a required check"),
])
def test_v2_producer_check_contract_refuses_a_changed_producer_shape(tmp_path, monkeypatch, old, new, reason):
    # The contract is read, never guessed: a producer whose source no longer has the expected shape is refused.
    source = Path(long_series.__file__)
    text = source.read_text(encoding="utf-8")
    assert text.count(old) == 1
    changed = text.replace(old, new)
    compile(changed, "long_series.py", "exec")
    (tmp_path / "long_series.py").write_text(changed, encoding="utf-8")
    shutil.copy2(source.with_name("observer.py"), tmp_path / "observer.py")
    monkeypatch.setattr(long_series, "__file__", str(tmp_path / "long_series.py"))
    with pytest.raises(ValueError, match=reason):
        web_contract.producer_checks_v2()


def _checks(mutate):
    def apply(provenance):
        mutate(provenance["checks"])

    return apply


def _drop(key):
    def mutate(payload):
        del payload[key]

    return mutate


PRODUCER_CHECK_DEFECTS = [
    ("required-missing", "baseline", _checks(_drop("atmosphere_rms_matches_history")),
     ["baseline: every producer check recorded in the provenance passed (required checks present and literally true; ['atmosphere_rms_matches_history missing'])",
      "baseline: provenance records exactly the producer's check fields (missing ['atmosphere_rms_matches_history'], unexpected [])"]),
    ("required-false", "baseline", _checks(_set(("residual_rms_matches_history",), False)), ["literally true; ['residual_rms_matches_history=False']"]),
    ("required-string-false", "baseline", _checks(_set(("atmosphere_rms_matches_history",), "false")), ["literally true; [\"atmosphere_rms_matches_history='false'\"]"]),
    ("required-string-true", "baseline", _checks(_set(("times_are_k_over_1000",), "true")), ["literally true; [\"times_are_k_over_1000='true'\"]"]),
    ("required-null", "baseline", _checks(_set(("times_match_history",), None)), ["literally true; ['times_match_history=None']"]),
    ("required-integer-one", "baseline", _checks(_set(("streaming_within_tolerance",), 1)), ["literally true; ['streaming_within_tolerance=1']"]),
    ("required-integer-zero", "baseline", _checks(_set(("instantaneous_unit_flux",), 0)), ["literally true; ['instantaneous_unit_flux=0']"]),
    ("required-false-other-case", "lower-gain", _checks(_set(("per_frame_reductions_within_tolerance",), False)),
     ["lower-gain: every producer check recorded in the provenance passed (required checks present and literally true; ['per_frame_reductions_within_tolerance=False'])"]),
    ("analysis-count-zero", "baseline", _checks(_set(("analysis_count",), 0)), ["baseline: producer analysis count is the v2 contract's 800 (recorded 0)"]),
    ("analysis-count-off-by-one", "baseline", _checks(_set(("analysis_count",), 799)), ["producer analysis count is the v2 contract's 800 (recorded 799)"]),
    ("analysis-count-float", "baseline", _checks(_set(("analysis_count",), 800.0)), ["producer analysis count is the v2 contract's 800 (recorded 800.0)"]),
    ("analysis-count-missing", "baseline", _checks(_drop("analysis_count")), ["producer analysis count is the v2 contract's 800 (recorded None)", "missing ['analysis_count']"]),
    ("analysis-window-start", "baseline", _checks(_set(("analysis_frames",), [100, 1000])), ["baseline: producer analysis frames are the v2 window [200, 1000) (recorded [100, 1000])"]),
    ("analysis-window-closed-end", "baseline", _checks(_set(("analysis_frames",), [200, 999])), ["producer analysis frames are the v2 window [200, 1000) (recorded [200, 999])"]),
    ("analysis-window-float", "baseline", _checks(_set(("analysis_frames",), [200.0, 1000])), ["producer analysis frames are the v2 window [200, 1000) (recorded [200.0, 1000])"]),
    ("diagnostic-string", "baseline", _checks(_set(("streaming_max_abs_difference", "corrected"), "0.0")), ["producer diagnostics", "streaming_max_abs_difference.corrected='0.0'"]),
    ("diagnostic-negative-maximum", "baseline", _checks(_set(("archive_mean_vs_own_mean_max_abs", "uncorrected"), -1e-18)), ["archive_mean_vs_own_mean_max_abs.uncorrected=-1e-18"]),
    ("diagnostic-null", "baseline", _checks(_set(("mean_unit_flux", "corrected"), None)), ["mean_unit_flux.corrected=None"]),
    ("diagnostic-boolean", "baseline", _checks(_set(("per_frame_independent_reductions_max", "held_correction_identity_max_abs_m"), False)), ["per_frame_independent_reductions_max.held_correction_identity_max_abs_m=False"]),
    ("diagnostic-keys", "baseline", _checks(lambda checks: checks["mean_unit_flux"].pop("corrected")), ["mean_unit_flux keys ['uncorrected']"]),
    ("diagnostic-type", "baseline", _checks(_set(("per_frame_independent_reductions_max",), True)), ["per_frame_independent_reductions_max keys bool"]),
    ("unexpected-field", "baseline", _checks(_set(("operator_override",), True)), ["provenance records exactly the producer's check fields (missing [], unexpected ['operator_override'])"]),
    ("checks-not-object", "baseline", _set(("checks",), [True]), ["baseline: every producer check recorded in the provenance passed (the checks record is list, not an object)"]),
    ("checks-absent", "baseline", _drop("checks"), ["(the checks record is NoneType, not an object)"]),
]


@pytest.mark.parametrize("name,case_id,mutate,expected", PRODUCER_CHECK_DEFECTS, ids=[item[0] for item in PRODUCER_CHECK_DEFECTS])
def test_v2_producer_check_defects_are_refused(web_dir, tmp_path, name, case_id, mutate, expected):
    site = _copy(web_dir, tmp_path)
    _v2_or_skip(site)
    _case_member(case_id, "provenance.json", mutate)(site)
    report = _run(site)
    assert not report["valid"]
    for reason in expected:
        assert any(reason in failure for failure in report["failures"]), (reason, report["failures"][:5])
    # Coherently re-hashed: only the producer-check checks of this case fail, no digest or reference check.
    assert all(failure.startswith(f"{case_id}: ") and "producer" in failure for failure in report["failures"]), report["failures"][:5]
    assert not [failure for failure in report["failures"] if any(word in failure for word in DIGEST_FAILURES)], report["failures"][:5]


def test_v2_producer_checks_unchanged_and_legitimate_diagnostics_are_accepted(web_dir, tmp_path):
    # Control: the unchanged record validates, and so do other finite diagnostic values (no tolerance is invented).
    site = _copy(web_dir, tmp_path)
    _v2_or_skip(site)
    control = _run(site)
    assert control["valid"], control["failures"][:5]
    # Five producer-check checks per case: field set, required checks, analysis frames, analysis count, diagnostics.
    assert control["checks_by_area"]["provenance"]["failed"] == 0 and control["checks_by_area"]["provenance"]["passed"] >= 5 * len(protocol.CASES)
    _case_member("baseline", "provenance.json", _checks(lambda checks: checks["streaming_max_abs_difference"].update(corrected=1e-17)))(site)
    _case_member("baseline", "provenance.json", _checks(lambda checks: checks["mean_unit_flux"].update(corrected=0.9999999999999996)))(site)
    report = _run(site)
    assert report["valid"], report["failures"][:5]
    assert report["checks_passed"] == control["checks_passed"]


def test_coherent_rehash_of_every_member_kind_is_accepted(web_dir, tmp_path):
    # Control for the fixtures above: the same rewrite chain with unchanged content validates.
    site = _copy(web_dir, tmp_path)
    _v2_or_skip(site)
    for leaf in ("observation.json", "metrics.json", "config.json", "provenance.json", "case.json"):
        _write_case_member(site, "baseline", leaf, _member(site, "baseline", leaf))
    for name in ("blocks.json", "display.json", "diagnostics.json"):
        _write_dataset_member(site, name, _dumps(json.loads((_dataset_dir(site) / name).read_text())))
    report = _run(site)
    assert report["valid"], report["failures"][:5]


def test_in_place_research_reference_must_match_the_previous_manifest(web_dir, tmp_path):
    site = _copy(web_dir, tmp_path)
    manifest = _v2_or_skip(site)
    manifest["results"]["sha256"] = "0" * 64
    _write_manifest(site, manifest)
    report = _run(site)
    failures = " | ".join(report["failures"])
    assert "Research Results reference equals the previous dataset's own manifest record" in failures
    assert "manifest.json (in place, previous dataset" in failures and "resolves to a matching member" in failures


def test_in_place_member_bytes_are_verified(web_dir, tmp_path):
    # A changed byte in a preserved research figure is found through the in-place reference chain (results -> figure).
    site = _copy(web_dir, tmp_path)
    manifest = _v2_or_skip(site)
    previous = site / "data" / manifest["previous_dataset"]["dataset_id"]
    previous_manifest = json.loads((previous / "manifest.json").read_text())
    figure = next(item["path"] for item in previous_manifest["members"] if item["role"] == "research_figure")
    target = previous / figure
    data = bytearray(target.read_bytes())
    data[-1] ^= 0x01
    target.write_bytes(bytes(data))
    report = _run(site)
    assert any(failure.startswith("previous dataset") and f"member {figure} size and SHA-256" in failure for failure in report["failures"]), report["failures"][:5]
    # An unparsable in-place JSON member is a fatal refusal, not a silent pass.
    site2 = _copy(web_dir, tmp_path / "second")
    results = site2 / "data" / manifest["previous_dataset"]["dataset_id"] / "research" / "results.json"
    results.write_bytes(results.read_bytes()[:-2] + b"|\n")
    with pytest.raises(validate.ValidationError, match="invalid JSON"):
        _run(site2)


def test_missing_previous_dataset_is_refused(web_dir, tmp_path):
    site = _copy(web_dir, tmp_path)
    manifest = _v2_or_skip(site)
    shutil.rmtree(site / "data" / manifest["previous_dataset"]["dataset_id"])
    with pytest.raises(validate.ValidationError, match="preserved previous dataset .* is missing"):
        _run(site)


def test_unknown_member_role_is_refused(web_dir, tmp_path):
    site = _copy(web_dir, tmp_path)
    manifest = _v2_or_skip(site)
    manifest["members"][0]["role"] = "research_results"  # a v1 role in a v2 manifest
    _write_manifest(site, manifest)
    report = _run(site)
    assert any("member roles belong to the v2 contract" in failure for failure in report["failures"]), report["failures"][:5]


# ---------------------------------------------------------------------------
# Raw-evidence mode is version-specific and never implied


def test_raw_mode_uses_the_contract_layout_and_is_not_implied(web_dir, tmp_path):
    site = _bundle_or_skip(web_dir)
    contract = validate.web_contract.CONTRACTS[_manifest(site)["schema"]]
    structural = _run(site)
    assert structural["raw_evidence_checked"] is False and structural["raw_evidence_layout"] is None
    empty_series = tmp_path / "no-series"
    empty_series.mkdir()
    report = _run(site, series_dir=empty_series)
    assert report["raw_evidence_checked"] is True and report["raw_evidence_layout"] == contract.raw_layout
    assert not report["valid"]
    expected_dir = "cases/baseline/attempt-" if contract.raw_layout == "frame_stacks" else "jobs/case-baseline/attempt-"
    assert any("raw attempt directory" in failure and expected_dir in failure and contract.raw_layout in failure for failure in report["failures"]), report["failures"][:5]
    # The structural checks are unaffected by the missing raw inputs.
    assert [f for f in report["failures"] if "raw" not in f] == []


# ---------------------------------------------------------------------------
# Command line


def test_command_line_reports_the_contract_and_exit_codes(web_dir, tmp_path, scripts_dir):
    site = _bundle_or_skip(web_dir)
    command = [sys.executable, "-B", str(scripts_dir / "validate.py"), "--web-dir", str(site), "--repo-root", str(web_dir.parents[1])]
    completed = subprocess.run(command, capture_output=True, text=True)
    assert completed.returncode == 0, completed.stdout[-2000:] + completed.stderr[-2000:]
    summary = json.loads(completed.stdout)
    assert summary["valid"] is True and summary["contract"]["manifest_schema"] == _manifest(site)["schema"]
    assert summary["checks_passed"] > 500 and summary["checks_by_area"]["metrics"]["passed"] > 0
    copy_site = _copy(web_dir, tmp_path)
    manifest = _manifest(copy_site)
    manifest["schema"] = "ao-explorer.manifest.v9"
    _write_manifest(copy_site, manifest)
    completed = subprocess.run([sys.executable, "-B", str(scripts_dir / "validate.py"), "--web-dir", str(copy_site)], capture_output=True, text=True)
    assert completed.returncode == 2 and "unsupported manifest schema" in json.loads(completed.stdout)["fatal"]
