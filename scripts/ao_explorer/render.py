"""Derived exports of the explorer: binary observations, display images and the web bundle.

Two stages, each run as one supervised child by ``export.py``:

``derive``
    For every completed production case (and, separately, the pilot) load the
    retained full-precision numeric mean PSFs, verify their parent identity
    (job record, file digest, window, count, equal weights, grid, roles) and
    their recorded science semantics against the frozen plan and scene
    (wavelength, residual, propagator, sampling and normalization, axes), all
    before writing anything; convolve the frozen binary scene with both and
    store the full-precision observations and their records under
    ``derived/observations-<code>/``, keyed by the identity of the code that
    computes them.  No AO trajectory runs.

``web``
    Render the display PNGs from their declared source arrays (fixed common
    OPD limits, a common ideal-PSF intensity reference, no per-frame
    normalization), write the versioned case/metrics/config/provenance/image
    descriptor/scene/observation JSON and CSV, export the Research Results
    (``research.py``), and write the manifest plus its external validation
    record.  Display quantization never feeds a metric.
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import math
from pathlib import Path
import shutil
import sys
import time
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

import binary_scene
import identity
import producer
import protocol
import web_contract


WEB_SCHEMA_VERSION = "ao-explorer.web.v1"
DISPLAY_REVISION = "ao-explorer.display.v1"
PSF_DISPLAY_HALF_WIDTH_CELLS = 32  # 64 x 64 display crop about angular zero
PSF_LOG_DECADES = 4.0
ATLAS_COLUMNS = 8
OPD_LIMIT_QUANTUM_M = 50e-9
OPD_LIMIT_PERCENTILE = 99.5
MAP_KINDS = (
    ("atmosphere", "atmosphere_opd_m", "Atmospheric OPD"),
    ("correction", "held_correction_opd_m", "Held DM correction (OPD-equivalent)"),
    ("residual", "pre_update_residual_opd_m", "Residual seen by the WFS (pre-update)"),
)
PSF_KINDS = (
    ("uncorrected", "psf_uncorrected", "Matched uncorrected reference (zero DM)"),
    ("corrected", "psf_corrected", "AO-corrected instantaneous PSF (pre-update residual)"),
)


class RenderError(RuntimeError):
    """Raised when a parent or export identity check refuses."""


# Derived identities (review round 1, R1-F13).  The observation arrays are
# bound to the code that computes them; the web export to the code that
# writes the bundle.  Orchestration (export.py) and checking (validate.py)
# produce no bundle content and are not part of either identity.  The web
# export judges every production record's producer checks by the shared rule
# (web_contract.py), whose v1 contract is read from the source of producer.py
# and observer.py and whose window is the contract's (protocol.py), so those
# four sources are part of the export content identity: a change to any of
# them can change what this exporter accepts.  The derive stage does not read
# the rule, so the observation identity is unchanged.
OBSERVATION_FILES = ("binary_scene.py", "render.py")
EXPORT_FILES = ("binary_scene.py", "render.py", "research.py", "web_contract.py", "producer.py", "observer.py", "protocol.py")


def _code_identity(names: Tuple[str, ...]) -> Dict[str, Any]:
    record = identity.file_set_identity(names)
    record["git"] = identity.git_state(identity.EXPORTER_DIR.relative_to(identity.REPO_ROOT).as_posix())
    return record


def observation_identity() -> Dict[str, Any]:
    return _code_identity(OBSERVATION_FILES)


def export_identity() -> Dict[str, Any]:
    return _code_identity(EXPORT_FILES)


def observations_dir(series_dir: Path, observation_sha: str) -> Path:
    return Path(series_dir) / "derived" / f"observations-{observation_sha[:12]}"


def _attempt(series_dir: Path, job_id: str) -> Path:
    attempt = producer.completed_attempt(series_dir, job_id)
    if attempt is None:
        raise RenderError(f"{job_id} has no completed attempt")
    return attempt


# The only parent semantics this renderer supports.  Every one is checked
# against the job record, the frozen plan and the arrays before anything is
# derived (external review ER-F04), and the derived labels are taken from these
# validated values, never assumed.
PARENT_SCHEMA = "shwfs_ao.science.long_exposure_result.v1"
PARENT_RESIDUAL_FIELDS = {"pre_update": "pre_update_residual_opd_m"}
UNCORRECTED_FIELD = "atmosphere_opd_m (zero-DM optical counterfactual)"
PARENT_NORMALIZATIONS = {("unit_total_flux", "normalized_source_grid_flux"): "unit total flux over the complete uncropped propagator grid"}
PARENT_METADATA = {"recentering": "none", "coaddition": "intensity", "temporal_quadrature": "instantaneous_snapshot_rectangle_rule"}


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise RenderError(message)


def check_parent_semantics(plan: Dict[str, Any], job: Dict[str, Any], record: Dict[str, Any], arrays: Dict[str, np.ndarray], window: Tuple[int, int]) -> Dict[str, Any]:
    """Refuse a parent whose recorded science semantics differ from the frozen plan and the scene.

    Returns the validated values the derived records are labelled with.
    """

    job_id = job["job_id"]
    grid = plan["science_grid"]
    scene = plan["scene"]
    start, stop = window
    _require(record.get("series_id") == plan["series_id"] and record.get("job", {}).get("job_id") == job_id, f"{job_id}: the job record names another series or job")
    _require(record.get("config_hash") == job["config_hash"], f"{job_id}: the job record's configuration hash differs from the frozen plan")
    observer = record["observer"]
    _require({"atmosphere_opd_m", "pre_update_residual_opd_m"} <= set(observer.get("requested_fields", [])), f"{job_id}: the observer did not request the atmosphere and pre-update residual fields")
    _require(observer.get("sampling_metadata") == grid["sampling_metadata"], f"{job_id}: the recorded image sampling/normalization differs from the frozen science grid")
    _require(record.get("science_propagator_config_hash") == grid["propagator_config_hash"], f"{job_id}: the science propagator differs from the frozen science grid")
    _require(scene.get("wavelength_m") == protocol.SCIENCE_WAVELENGTH_M, "the frozen scene is not at the explorer's science wavelength")
    for axis in ("x", "y"):
        digest = identity.sha256_bytes(np.ascontiguousarray(arrays[f"{axis}_angle_rad"]).tobytes())
        _require(digest == grid[f"{axis}_angle_rad_sha256"] == scene["grid"][f"{axis}_angle_rad_sha256"], f"{job_id}: the parents' {axis} angle axis differs from the frozen science grid and scene")
    shape = list(grid["shape"])
    _require(shape == list(scene["grid"]["shape_yx"]), "the frozen science grid and scene grid differ in shape")
    frame_period = 1.0 / float(job["effective_parameters"]["frame_rate_hz"])
    validated: Dict[str, Any] = {}
    config_hashes = set()
    for role, name in (("corrected", "mean_psf_corrected"), ("uncorrected", "mean_psf_uncorrected")):
        accumulator = observer["accumulators"][role]
        selection = accumulator["selection"]
        metadata = accumulator["metadata"]
        _require(accumulator.get("schema") == PARENT_SCHEMA, f"{job_id}: {role} parent schema {accumulator.get('schema')} is not supported")
        _require(accumulator.get("wavelengths_m") == [protocol.SCIENCE_WAVELENGTH_M], f"{job_id}: {role} parent wavelength {accumulator.get('wavelengths_m')} is not [{protocol.SCIENCE_WAVELENGTH_M}] m")
        _require(all(metric.get("wavelength_m") == protocol.SCIENCE_WAVELENGTH_M for metric in accumulator.get("metrics", [])), f"{job_id}: {role} parent metrics are at another wavelength")
        residual = accumulator.get("residual")
        _require(residual in PARENT_RESIDUAL_FIELDS and selection.get("residual") == residual, f"{job_id}: {role} parent residual {residual!r} / {selection.get('residual')!r} is not the supported pre-update residual")
        _require(accumulator.get("propagator_backend") == "native" and accumulator.get("propagator_config_hash") == grid["propagator_config_hash"], f"{job_id}: {role} parent propagator differs from the frozen science grid")
        normalization = (grid["sampling_metadata"]["normalization"], accumulator.get("flux_denominator"))
        _require(normalization in PARENT_NORMALIZATIONS and metadata.get("flux_denominator") == accumulator.get("flux_denominator"), f"{job_id}: {role} parent normalization {normalization} is not supported")
        for key, expected in PARENT_METADATA.items():
            _require(metadata.get(key) == expected, f"{job_id}: {role} parent {key} is {metadata.get(key)!r}, not {expected!r}")
        _require(selection.get("temporal_quadrature") == PARENT_METADATA["temporal_quadrature"], f"{job_id}: {role} parent selection quadrature differs")
        _require(
            selection["first_frame"] == start
            and selection["last_frame"] == stop - 1
            and selection["sample_count"] == stop - start
            and selection["burn_in_frames"] == start
            and selection["stride"] == 1
            and selection["uniform_weights"] is True
            and selection["weight_sum"] == float(stop - start)
            and math.isclose(selection["frame_period_s"], frame_period, rel_tol=1e-12),
            f"{job_id}: {role} accumulator selection differs from the declared window, weights or frame period",
        )
        _require(accumulator.get("reset_count") == 0, f"{job_id}: {role} accumulator was reset during the run")
        values = arrays[name]
        _require(list(values.shape) == shape, f"{job_id}: {role} parent shape {list(values.shape)} differs from the science grid {shape}")
        _require(bool(np.all(np.isfinite(values))) and not bool(np.any(values < 0.0)), f"{job_id}: {role} parent is not finite and non-negative")
        _require(abs(float(np.sum(values)) - 1.0) <= protocol.TOLERANCES["unit_flux"]["atol"], f"{job_id}: {role} parent total flux {float(np.sum(values))!r} is not unit")
        config_hashes.add(accumulator["config_hash"])
        validated[role] = {
            "field": PARENT_RESIDUAL_FIELDS[residual] if role == "corrected" else UNCORRECTED_FIELD,
            "wavelength_m": accumulator["wavelengths_m"][0],
            "normalization": PARENT_NORMALIZATIONS[normalization],
            "recentering": metadata["recentering"],
            "coaddition": metadata["coaddition"],
        }
    _require(len(config_hashes) == 1, f"{job_id}: the corrected and uncorrected accumulators have different configurations")
    return validated


def load_parents(series_dir: Path, job_id: str, *, expected_window: Tuple[int, int], plan: Dict[str, Any]) -> Dict[str, Any]:
    """Numeric mean PSFs of one job, after identity, window, grid and semantic checks."""

    attempt = _attempt(series_dir, job_id)
    record = producer.read_json(attempt / "job_record.json")
    path = attempt / "mean_psfs.npz"
    digest = identity.sha256_file(path)
    if record["files"]["mean_psfs.npz"]["sha256"] != digest:
        raise RenderError(f"{job_id}: mean_psfs.npz digest differs from its job record")
    with np.load(path) as data:
        arrays = {name: np.array(data[name]) for name in data.files}
    start, stop = expected_window
    frames = arrays["analysis_frames"].tolist()
    if frames != list(range(start, stop)):
        raise RenderError(f"{job_id}: parent window {frames[:1]}..{frames[-1:]} is not [{start}, {stop})")
    validated = check_parent_semantics(plan, producer.plan_job(plan, job_id), record, arrays, expected_window)
    return {"attempt": attempt, "record": record, "arrays": arrays, "file_sha256": digest, "validated": validated}


def _parent_record(job_id: str, parents: Dict[str, Any], role: str, window: Tuple[int, int]) -> Dict[str, Any]:
    arrays = parents["arrays"]
    record = parents["record"]
    validated = parents["validated"][role]
    name = "mean_psf_corrected" if role == "corrected" else "mean_psf_uncorrected"
    accumulator = record["observer"]["accumulators"][role]
    start, stop = window
    return {
        "job_id": job_id,
        "role": role,
        "field": validated["field"],
        "array": name,
        "array_sha256": identity.sha256_bytes(np.ascontiguousarray(arrays[name]).tobytes()),
        "file": "mean_psfs.npz",
        "file_sha256": parents["file_sha256"],
        "shape": list(arrays[name].shape),
        "window": [start, stop],
        "sample_count": stop - start,
        "stride": 1,
        "weights": "equal",
        "frame_period_s": record["observer"]["frames"]["frame_period_s"][0],
        "first_timestamp_s": record["observer"]["frames"]["time_s"][start],
        "last_timestamp_s": record["observer"]["frames"]["time_s"][stop - 1],
        "timestamp_span_s": record["observer"]["frames"]["time_s"][stop - 1] - record["observer"]["frames"]["time_s"][start],
        "nominal_quadrature_duration_s": (stop - start) * record["observer"]["frames"]["frame_period_s"][0],
        "sampling": "frame-start instantaneous snapshots; not a finite-shutter sub-frame integration",
        "recentering": validated["recentering"],
        "coaddition": validated["coaddition"],
        "normalization": validated["normalization"],
        "accumulator_config_hash": accumulator["config_hash"],
        "propagator_config_hash": accumulator["propagator_config_hash"],
        "run_config_hash": record["config_hash"],
        "history_config_hash": record["history_config_hash"],
        "x_angle_rad_sha256": identity.sha256_bytes(arrays["x_angle_rad"].tobytes()),
        "y_angle_rad_sha256": identity.sha256_bytes(arrays["y_angle_rad"].tobytes()),
        "wavelength_m": validated["wavelength_m"],
        "total_flux": float(np.sum(arrays[name])),
    }


def command_derive(series_dir: Path) -> Dict[str, Any]:
    plan = producer.load_plan(series_dir, frozen=True)
    code = observation_identity()
    derived = observations_dir(series_dir, code["sha256"])
    if derived.exists():
        raise RenderError(f"{derived.name} exists; derived observations of this code identity are never overwritten.")
    started = time.perf_counter()
    targets = [(job["job_id"], job) for job in plan["jobs"] if job["role"] in ("production", "pilot")]
    # Every parent is checked before anything is written, so a refused parent
    # leaves no partial derived output behind.
    loaded = {job_id: load_parents(series_dir, job_id, expected_window=(job["burn_in"], job["n_steps"]), plan=plan) for job_id, job in targets}
    derived.mkdir(parents=True, exist_ok=False)
    scene_bundle: Optional[Dict[str, Any]] = None
    outputs: Dict[str, Any] = {"schema": "ao-explorer.derived-observations.v1", "renderer_revision": binary_scene.RENDERER_REVISION}
    entries = []
    arrays_out: Dict[str, np.ndarray] = {}
    for job_id, job in targets:
        window = (job["burn_in"], job["n_steps"])
        parents = loaded[job_id]
        x = parents["arrays"]["x_angle_rad"]
        y = parents["arrays"]["y_angle_rad"]
        if scene_bundle is None:
            scene_bundle = binary_scene.build_scene(
                x, y, wavelength_m=parents["validated"]["corrected"]["wavelength_m"], telescope_diameter_m=2.0
            )
            if scene_bundle["record"] != plan["scene"]:
                raise RenderError("the scene rebuilt on the parents' grid differs from the frozen plan scene")
        entry = {"job_id": job_id, "role": job["role"], "case_id": job["case_id"], "observations": {}}
        for role in ("uncorrected", "corrected"):
            kernel = parents["arrays"]["mean_psf_corrected" if role == "corrected" else "mean_psf_uncorrected"]
            result = binary_scene.observe(scene_bundle, kernel, x, y)
            key = f"{job_id}:{role}"
            arrays_out[key.replace(":", "__")] = result.pop("image")
            entry["observations"][role] = {
                "parent": _parent_record(job_id, parents, role, window),
                **result,
            }
        entries.append(entry)
    assert scene_bundle is not None
    np.savez(derived / "observations.npz", scene=scene_bundle["scene"], **arrays_out)
    outputs.update(
        {
            "scene": scene_bundle["record"],
            "policy": binary_scene.CONVOLUTION_POLICY,
            "entries": entries,
            "arrays_file": "observations.npz",
            "arrays_sha256": identity.sha256_file(derived / "observations.npz"),
            "observation_code_identity": code,
            "processing_s": time.perf_counter() - started,
        }
    )
    producer.write_json(derived / "observations.json", outputs)
    return outputs


# ---------------------------------------------------------------------------
# Display mapping


def _colormap(name: str) -> np.ndarray:
    from matplotlib import colormaps

    return (np.asarray(colormaps[name](np.linspace(0.0, 1.0, 256)))[:, :3] * 255.0 + 0.5).astype(np.uint8)


OPD_CMAP = "RdBu_r"
PSF_CMAP = "inferno"


def opd_codes(values_m: np.ndarray, mask: np.ndarray, limit_m: float) -> Tuple[np.ndarray, Dict[str, Any]]:
    """8-bit codes of an OPD map on the fixed symmetric scale; exterior masked."""

    inside = np.where(mask, np.asarray(values_m, dtype=float), 0.0)  # exterior is masked below
    scaled = (inside + limit_m) / (2.0 * limit_m)
    clipped_low = mask & (inside < -limit_m)
    clipped_high = mask & (inside > limit_m)
    codes = np.clip(np.floor(np.clip(scaled, 0.0, 1.0) * 255.0 + 0.5), 0, 255).astype(np.uint8)
    codes[~mask] = 0
    return codes, {
        "clipped_low_fraction": float(np.count_nonzero(clipped_low) / np.count_nonzero(mask)),
        "clipped_high_fraction": float(np.count_nonzero(clipped_high) / np.count_nonzero(mask)),
    }


def display_map(values_m: np.ndarray, mask: np.ndarray) -> Tuple[np.ndarray, float]:
    """The map with its pupil mean removed (display only) and that mean in metres."""

    values = np.asarray(values_m, dtype=float)
    piston = float(np.mean(values[mask]))
    out = np.full(values.shape, np.nan)
    out[mask] = values[mask] - piston
    return out, piston


def psf_codes(intensity: np.ndarray, ideal_peak: float) -> Tuple[np.ndarray, Dict[str, Any]]:
    """8-bit codes of log10(I / ideal peak) on [-decades, 0]."""

    with np.errstate(divide="ignore"):
        logarithm = np.log10(np.maximum(np.asarray(intensity, dtype=float), 0.0) / ideal_peak)
    scaled = (logarithm + PSF_LOG_DECADES) / PSF_LOG_DECADES
    above = float(np.count_nonzero(scaled > 1.0) / scaled.size)
    below = float(np.count_nonzero(scaled < 0.0) / scaled.size)
    codes = np.clip(np.floor(np.clip(scaled, 0.0, 1.0) * 255.0 + 0.5), 0, 255).astype(np.uint8)
    return codes, {"above_display_max_fraction": above, "below_display_min_fraction": below}


def _rgba(codes: np.ndarray, cmap: np.ndarray, mask: Optional[np.ndarray]) -> np.ndarray:
    rgb = cmap[codes]
    alpha = np.full(codes.shape, 255, dtype=np.uint8) if mask is None else np.where(mask, 255, 0).astype(np.uint8)
    return np.dstack([rgb, alpha])


def png_bytes(rgba: np.ndarray) -> bytes:
    from PIL import Image

    buffer = io.BytesIO()
    # Raster row 0 is the top of the image; the arrays put +y at the last
    # row, so rows are flipped once here and the descriptor says so.
    Image.fromarray(np.ascontiguousarray(rgba[::-1]), mode="RGBA").save(buffer, format="PNG", optimize=True)
    return buffer.getvalue()


def crop_bounds(axis: np.ndarray) -> Tuple[int, int]:
    zero = binary_scene.zero_index(axis, label="psf axis")
    return zero - PSF_DISPLAY_HALF_WIDTH_CELLS, zero + PSF_DISPLAY_HALF_WIDTH_CELLS


def atlas(tiles: List[np.ndarray]) -> Tuple[np.ndarray, List[List[int]]]:
    """Pack equally sized RGBA tiles row-major into an atlas; returns pixel rectangles."""

    height, width = tiles[0].shape[:2]
    rows = math.ceil(len(tiles) / ATLAS_COLUMNS)
    canvas = np.zeros((rows * height, ATLAS_COLUMNS * width, 4), dtype=np.uint8)
    rectangles = []
    for index, tile in enumerate(tiles):
        row, column = divmod(index, ATLAS_COLUMNS)
        # Tiles are already flipped to raster order by the caller.
        canvas[row * height:(row + 1) * height, column * width:(column + 1) * width] = tile
        rectangles.append([column * width, row * height, width, height])
    return canvas, rectangles


def raster(rgba: np.ndarray) -> np.ndarray:
    return np.ascontiguousarray(rgba[::-1])


def png_from_raster(raster_rgba: np.ndarray) -> bytes:
    from PIL import Image

    buffer = io.BytesIO()
    Image.fromarray(raster_rgba, mode="RGBA").save(buffer, format="PNG", optimize=True)
    return buffer.getvalue()


# ---------------------------------------------------------------------------
# Web export


class Bundle:
    """Members written under one versioned dataset directory, hashed as written."""

    def __init__(self, root: Path, dataset_dir: str) -> None:
        self.root = root
        self.dataset_dir = dataset_dir
        self.base = root / dataset_dir
        self.members: Dict[str, Dict[str, Any]] = {}

    def write(self, relative: str, data: bytes, *, media_type: str, role: str) -> Dict[str, Any]:
        path = self.base / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        entry = {"path": relative, "bytes": len(data), "sha256": identity.sha256_bytes(data), "media_type": media_type, "role": role}
        self.members[relative] = entry
        return entry

    def write_json(self, relative: str, value: Any, *, role: str) -> Dict[str, Any]:
        data = (json.dumps(value, indent=1, allow_nan=False, ensure_ascii=False) + "\n").encode("utf-8")
        return self.write(relative, data, media_type="application/json", role=role)

    def copy(self, relative: str, source: Path, *, role: str, media_type: str) -> Dict[str, Any]:
        return self.write(relative, Path(source).read_bytes(), media_type=media_type, role=role)


def ref(entry: Dict[str, Any], defining: str) -> Dict[str, Any]:
    """A member reference relative to the defining JSON's own directory."""

    defining_dir = Path(defining).parent
    relative = Path(entry["path"])
    try:
        path = relative.relative_to(defining_dir).as_posix()
    except ValueError:
        depth = len(defining_dir.parts)
        path = "/".join([".."] * depth + [relative.as_posix()])
    return {"href": path, "bytes": entry["bytes"], "sha256": entry["sha256"], "media_type": entry["media_type"]}


def finite_or_null(values: List[float], reason: str) -> Dict[str, Any]:
    out: List[Optional[float]] = []
    reasons: Dict[str, str] = {}
    for index, value in enumerate(values):
        number = float(value)
        if math.isfinite(number):
            out.append(number)
        else:
            out.append(None)
            reasons[str(index)] = reason
    return {"values": out, "null_reasons": reasons}


def opd_limit(series_dir: Path, plan: Dict[str, Any]) -> Dict[str, Any]:
    """Common symmetric OPD display limit across every production case and panel."""

    percentiles = []
    for job in plan["jobs"]:
        if job["role"] != "production":
            continue
        with np.load(_attempt(series_dir, job["job_id"]) / "movie.npz") as data:
            mask = np.asarray(data["pupil_mask"], dtype=bool)
            for _, name, _ in MAP_KINDS:
                stack = np.asarray(data[name])[:, mask]
                stack = stack - stack.mean(axis=1, keepdims=True)
                percentiles.append(float(np.percentile(np.abs(stack), OPD_LIMIT_PERCENTILE)))
    raw = max(percentiles)
    limit = math.ceil(raw / OPD_LIMIT_QUANTUM_M) * OPD_LIMIT_QUANTUM_M
    return {
        "limit_m": limit,
        "rule": (
            f"max over production cases and the three map kinds of the {OPD_LIMIT_PERCENTILE} percentile of |OPD - pupil mean| "
            f"inside the pupil over the 40 movie frames, rounded up to {OPD_LIMIT_QUANTUM_M * 1e9:.0f} nm"
        ),
        "raw_max_percentile_m": raw,
        "colormap": OPD_CMAP,
        "scale": "linear, symmetric about zero",
    }


def metrics_payload(job_record: Dict[str, Any], history: Dict[str, np.ndarray], burn_in: int) -> Dict[str, Any]:
    frames = job_record["observer"]["frames"]
    n = len(frames["frame_index"])
    window = slice(burn_in, n)
    residual = np.asarray(frames["residual_rms_m"])
    atmosphere = np.asarray(frames["atmosphere_rms_m"])
    s_corr = np.asarray(frames["peak_strehl_corrected"])
    s_unc = np.asarray(frames["peak_strehl_uncorrected"])
    valid = np.asarray(history["valid_measurement_fraction"], dtype=float)
    valid_subap = np.asarray(history["valid_subaperture_fraction"], dtype=float)
    usable = np.asarray(history["reconstruction_usable"], dtype=bool)
    saturation = np.asarray(history["saturation_fraction"], dtype=float)
    corrected = job_record["observer"]["accumulators"]["corrected"]["metrics"][0]
    uncorrected = job_record["observer"]["accumulators"]["uncorrected"]["metrics"][0]
    per_frame = {
        "frame_index": list(range(n)),
        "time_s": [float(value) for value in frames["time_s"]],
        "atmosphere_rms_nm": finite_or_null((atmosphere * 1e9).tolist(), "non-finite reduction"),
        "residual_rms_nm": finite_or_null((residual * 1e9).tolist(), "non-finite reduction"),
        "peak_strehl_uncorrected": finite_or_null(s_unc.tolist(), "non-finite reduction"),
        "peak_strehl_corrected": finite_or_null(s_corr.tolist(), "non-finite reduction"),
        "valid_measurement_fraction": finite_or_null(valid.tolist(), "non-finite"),
        "valid_subaperture_fraction": finite_or_null(valid_subap.tolist(), "non-finite"),
        "reconstruction_usable": [bool(value) for value in usable],
        "dm_saturation_fraction": finite_or_null(saturation.tolist(), "non-finite"),
    }
    summary = {
        "window": [burn_in, n],
        "sample_count": n - burn_in,
        "mean_atmosphere_rms_nm": float(np.mean(atmosphere[window]) * 1e9),
        "mean_residual_rms_nm": float(np.mean(residual[window]) * 1e9),
        "root_mean_square_residual_nm": float(math.sqrt(float(np.mean(residual[window] ** 2))) * 1e9),
        "mean_instantaneous_peak_strehl_uncorrected": float(np.mean(s_unc[window])),
        "mean_instantaneous_peak_strehl_corrected": float(np.mean(s_corr[window])),
        "average_psf_peak_strehl_uncorrected": float(uncorrected["peak_strehl"]),
        "average_psf_peak_strehl_corrected": float(corrected["peak_strehl"]),
        "average_psf_on_axis_strehl_corrected": float(corrected["on_axis_strehl"]),
        "average_psf_fwhm_lambda_over_d_corrected": float(corrected["fwhm_lambda_over_d"]),
        "average_psf_fwhm_lambda_over_d_uncorrected": float(uncorrected["fwhm_lambda_over_d"]),
        "mean_valid_measurement_fraction": float(np.mean(valid[window])),
        "min_valid_measurement_fraction": float(np.min(valid[window])),
        "reconstruction_usable_fraction": float(np.mean(usable[window])),
        "mean_dm_saturation_fraction": float(np.mean(saturation[window])),
        "max_dm_saturation_fraction": float(np.max(saturation[window])),
    }
    definitions = {
        "atmosphere_rms_nm": "pupil RMS of the frame's atmosphere_opd_m after removing the pupil mean (shwfs_ao.core.wavefront.masked_rms), nm OPD",
        "residual_rms_nm": "pupil RMS of pre_update_residual_opd_m (the residual the WFS measured), piston removed, nm OPD",
        "peak_strehl_*": "peak angular surface brightness of the instantaneous 1.65 um image over that of the zero-OPD image of the same propagator and grid (shwfs_ao.science.metrics.peak_strehl_from_discrete_flux); tilt kept, no recentring",
        "valid_measurement_fraction": "effective measurement rows (calibration-valid, runtime-valid, finite) over calibration-valid rows (loop history)",
        "valid_subaperture_fraction": "valid lenslets over retained lenslets (loop history)",
        "reconstruction_usable": "the reconstructor returned an estimate for this frame (loop history); not a lock classifier",
        "dm_saturation_fraction": "fraction of actuators clipped by the stroke limit in the command issued by frame k's update (loop history saturation_fraction[k]); that command is held during frame k + 1, so the correction shown for frame k is the command issued at frame k - 1",
        "mean_dm_saturation_fraction / max_dm_saturation_fraction": "mean and maximum over the commands issued in frames 40-179 (held during frames 41-180)",
        "mean_residual_rms_nm": "mean of the per-frame residual RMS over the analysis window",
        "root_mean_square_residual_nm": "square root of the mean per-frame mean square over the analysis window",
        "mean_instantaneous_peak_strehl_*": "mean of per-frame instantaneous peak Strehl over the analysis window",
        "average_psf_peak_strehl_*": "peak Strehl of the equal-weight average of the 140 instantaneous images (production long-exposure accumulator); differs from the mean instantaneous Strehl",
    }
    return {"per_frame": per_frame, "summary": summary, "definitions": definitions, "excluded": {
        "post_update_residual": "excluded from the main page (same-sample diagnostic)",
        "lost_lock": "the history's final-frame heuristic is not exported as a lock classifier",
    }}


def metrics_csv(per_frame: Dict[str, Any]) -> bytes:
    columns = [
        "frame_index",
        "time_s",
        "atmosphere_rms_nm",
        "residual_rms_nm",
        "peak_strehl_uncorrected",
        "peak_strehl_corrected",
        "valid_measurement_fraction",
        "valid_subaperture_fraction",
        "reconstruction_usable",
        "dm_saturation_fraction",
    ]
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(columns)
    for index in per_frame["frame_index"]:
        row = []
        for column in columns:
            value = per_frame[column]
            item = value["values"][index] if isinstance(value, dict) else value[index]
            row.append("" if item is None else repr(item) if isinstance(item, float) else str(item).lower() if isinstance(item, bool) else str(item))
        writer.writerow(row)
    return buffer.getvalue().encode("utf-8")


def producer_record_problems(record: Any, *, window: Tuple[int, int], count: int) -> web_contract.ProducerCheckProblems:
    """A v1 job record's producer checks judged by the validator's rule (``web_contract``) on the declared window.

    Every reader applies the same contract: the recorded fields, each verdict literally ``True``, the job record's
    ``burn_in`` and ``n_steps`` as ints naming ``window`` and ``count``, the diagnostics' keys and finite values.  A
    truthiness filter over the booleans alone would pass a missing check, a string ``"false"``, ``null`` or an empty
    checks mapping.
    """

    observer = record.get("observer") if isinstance(record, dict) else None
    checks = observer.get("checks") if isinstance(observer, dict) else None
    job = record.get("job") if isinstance(record, dict) else None
    return web_contract.producer_check_problems(checks, web_contract.V1.producer_checks, window, count, job=job)


def case_validation(record: Any, *, window: Tuple[int, int], count: int) -> Dict[str, bool]:
    """The ``validation`` record of a case entry, by the same rule :func:`bind_case_records` requires."""

    return {"producer_checks_passed": producer_record_problems(record, window=window, count=count).ok}


def bind_case_records(series_dir: Path, plan: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    """Every production case's completed attempt and job record, judged before anything is written.

    The plan's production window must be the v1 contract's; each record's producer checks must meet the producer's
    contract and name that window.  A refused record leaves no bundle, dataset directory or entry behind.
    """

    contract = web_contract.V1
    window, count = contract.analysis_window, contract.analysis_count
    bound: Dict[str, Dict[str, Any]] = {}
    for case in protocol.CASES:
        job_id = f"case-{case['id']}"
        job = producer.plan_job(plan, job_id)
        _require(job.get("role") == "production" and (job.get("burn_in"), job.get("n_steps")) == window,
                 f"{job_id}: the plan's window [{job.get('burn_in')!r}, {job.get('n_steps')!r}) is not the {contract.name} contract's [{window[0]}, {window[1]})")
        attempt = _attempt(series_dir, job_id)
        record = producer.read_json(attempt / "job_record.json")
        problems = producer_record_problems(record, window=window, count=count)
        _require(problems.kind is None and not (problems.missing or problems.unexpected or problems.not_true or problems.diagnostics),
                 f"{job_id}: the production record checks do not meet the producer's contract ({problems})")
        _require(not (problems.frames_wrong or problems.count_wrong), f"{job_id}: the record's analysis window is not [{window[0]}, {window[1]}) with {count} frames")
        bound[job_id] = {"attempt": attempt, "record": record, "validation": case_validation(record, window=window, count=count)}
    return bound


def command_web(series_dir: Path, web_dir: Path) -> Dict[str, Any]:
    import research
    import site_build

    started = time.perf_counter()
    # The entry records the page code's content build (external review ER-F05); the
    # code must already sit in its content-addressed directory.
    site = site_build.check(web_dir, entry=False)
    if site["problems"]:
        raise RenderError("the site code is not in its content-addressed build directory: " + "; ".join(site["problems"]))
    plan = producer.load_plan(series_dir, frozen=True)
    # Every production record is judged before anything is written (the derive stage does the same for its parents).
    bound_records = bind_case_records(series_dir, plan)
    observation_code = observation_identity()
    observation_dir = observations_dir(series_dir, observation_code["sha256"])
    if not (observation_dir / "observations.json").exists():
        raise RenderError(f"no derived observations for the current observation code ({observation_dir.name}); run derive first")
    derived = producer.read_json(observation_dir / "observations.json")
    if derived["observation_code_identity"]["sha256"] != observation_code["sha256"]:
        raise RenderError("the derived observations were made by different observation code")
    if identity.sha256_file(observation_dir / "observations.npz") != derived["arrays_sha256"]:
        raise RenderError("the derived observation arrays differ from their record")
    derived_identity = export_identity()
    export_key = identity.sha256_bytes(
        identity.canonical_json_bytes({"series": plan["series_id"], "plan": identity.sha256_file(series_dir / producer.FROZEN_PLAN_NAME), "export_code": derived_identity["sha256"], "observation_code": observation_code["sha256"], "display": DISPLAY_REVISION})
    )[:12]
    dataset_id = f"{plan['series_id']}-e{export_key}"
    data_root = Path(web_dir) / "data"
    if (data_root / dataset_id).exists():
        raise RenderError(f"dataset directory {dataset_id} exists; an export is never overwritten")
    bundle = Bundle(data_root, dataset_id)
    limits = opd_limit(series_dir, plan)
    opd_cmap = _colormap(OPD_CMAP)
    psf_cmap = _colormap(PSF_CMAP)

    baseline_record = producer.read_json(_attempt(series_dir, "case-baseline") / "job_record.json")
    with np.load(_attempt(series_dir, "case-baseline") / "mean_psfs.npz") as data:
        ideal = np.array(data["ideal_psf"])
        x_axis = np.array(data["x_angle_rad"])
        y_axis = np.array(data["y_angle_rad"])
    ideal_peak = float(np.max(ideal))
    x0, x1 = crop_bounds(x_axis)
    y0, y1 = crop_bounds(y_axis)
    mas = 180.0 / math.pi * 3600.0e3
    step = float(x_axis[1] - x_axis[0])
    psf_window = {
        "x_index": [x0, x1],
        "y_index": [y0, y1],
        "x_extent_mas": [(float(x_axis[x0]) - step / 2) * mas, (float(x_axis[x1 - 1]) + step / 2) * mas],
        "y_extent_mas": [(float(y_axis[y0]) - step / 2) * mas, (float(y_axis[y1 - 1]) + step / 2) * mas],
        "cell_mas": step * mas,
        "native_extent_mas": [(float(x_axis[0]) - step / 2) * mas, (float(x_axis[-1]) + step / 2) * mas],
        "note": "display crop of the native 156 x 156 grid about exact zero angle; metrics use the full uncropped grid",
    }
    psf_scale = {
        "mapping": f"log10(I / I_ideal_peak) clipped to [-{PSF_LOG_DECADES:g}, 0]",
        "ideal_peak_cell_flux": ideal_peak,
        "ideal_reference": "zero-OPD image of the same native propagator, wavelength and grid (unit total flux)",
        "colormap": PSF_CMAP,
        "normalization": "common to every frame, case, role, average image, observation and the scene reference; no per-image peak normalization",
    }

    display_payload = {
        "schema": "ao-explorer.display.v1",
        "revision": DISPLAY_REVISION,
        "opd": {
            **limits,
            "code_rule": "code = round(clip((OPD + L) / (2 L), 0, 1) * 255); exterior transparent",
            "lut_rgb_hex": ["#%02x%02x%02x" % tuple(int(v) for v in row) for row in opd_cmap],
        },
        "psf": {
            **psf_scale,
            "decades": PSF_LOG_DECADES,
            "code_rule": f"code = round(clip((log10(I / I_ideal_peak) + {PSF_LOG_DECADES:g}) / {PSF_LOG_DECADES:g}, 0, 1) * 255)",
            "lut_rgb_hex": ["#%02x%02x%02x" % tuple(int(v) for v in row) for row in psf_cmap],
        },
        "psf_window": psf_window,
        "raster": "PNG row 0 is the +y edge (rows flipped once at encoding); columns increase with +x",
        "upscaling": "nearest-neighbour in the browser (image smoothing disabled); no interpolation of values",
    }
    display_entry = bundle.write_json("display.json", display_payload, role="display")

    scene_record = derived["scene"]
    with np.load(observation_dir / "observations.npz") as data:
        observations = {name: np.array(data[name]) for name in data.files}
    scene_codes, scene_clip = psf_codes(observations["scene"], ideal_peak)
    scene_png = bundle.write("scene/scene-reference.png", png_bytes(_rgba(scene_codes, psf_cmap, None)), media_type="image/png", role="scene_reference")
    scene_json = {
        "schema": "ao-explorer.scene-export.v1",
        "scene": scene_record,
        "display": {
            "image": None,
            "scale": psf_scale,
            "clipping": scene_clip,
            "note": "Point sources occupy single cells; their values exceed the display maximum and are shown clipped.",
            "raster": "row 0 of the PNG is +y top; columns increase with +x",
            "extent_mas": psf_window["native_extent_mas"],
        },
    }
    scene_json["display"]["image"] = ref(scene_png, "scene/scene.json")
    scene_entry = bundle.write_json("scene/scene.json", scene_json, role="scene")

    cases_out: Dict[str, Any] = {}
    case_index_entries = {}
    baseline_digests = baseline_record["observer"]["frames"]["atmosphere_sha256"]
    for case in protocol.CASES:
        job_id = f"case-{case['id']}"
        job = producer.plan_job(plan, job_id)
        attempt = bound_records[job_id]["attempt"]
        record = bound_records[job_id]["record"]
        with np.load(attempt / "history.npz") as data:
            history = {name: np.array(data[name]) for name in data.files}
        with np.load(attempt / "movie.npz") as data:
            movie = {name: np.array(data[name]) for name in data.files}
        with np.load(attempt / "mean_psfs.npz") as data:
            means = {name: np.array(data[name]) for name in data.files}
        mask = np.asarray(movie["pupil_mask"], dtype=bool)
        indices = [int(value) for value in movie["indices"]]
        if indices != job["display_indices"]:
            raise RenderError(f"{job_id}: retained movie indices differ from the plan")
        prefix = f"cases/{case['id']}"
        images: Dict[str, Any] = {}
        clip_tables: Dict[str, Any] = {}
        for kind, name, label in MAP_KINDS:
            tiles = []
            clips = []
            pistons = []
            for position in range(len(indices)):
                values, piston = display_map(movie[name][position], mask)
                codes, clip = opd_codes(values, mask, limits["limit_m"])
                tiles.append(raster(_rgba(codes, opd_cmap, mask)))
                clips.append(clip)
                pistons.append(piston * 1e9)
            canvas, rectangles = atlas(tiles)
            entry = bundle.write(f"{prefix}/atlas-{kind}.png", png_from_raster(canvas), media_type="image/png", role="display_atlas")
            images[kind] = {
                "label": label,
                "source": f"movie.npz:{name} (job {job_id})",
                "unit": "nm OPD" if kind != "correction" else "nm OPD-equivalent (not mirror surface height)",
                "atlas": ref(entry, f"{prefix}/case.json"),
                "tile_px": [int(mask.shape[1]), int(mask.shape[0])],
                "rectangles_xywh": rectangles,
                "frame_indices": indices,
                "color_limits_nm": [-limits["limit_m"] * 1e9, limits["limit_m"] * 1e9],
                "colormap": OPD_CMAP,
                "mask": "pupil exterior transparent (not zero OPD)",
                "piston": "the pupil mean (piston) of each displayed map is removed for display only; the removed value per movie frame is display_piston_nm. A Shack-Hartmann sensor does not sense piston, piston does not change the image, and every RMS on this site is piston-removed. Raw maps keep their piston in the evidence.",
                "display_piston_nm": pistons,
                "axes": "x right, +y up (raster rows flipped once at encoding); pupil coordinates -1..1 m",
                "extent_m": [-1.0, 1.0, -1.0, 1.0],
                "resampling": "none (one pupil sample per tile pixel)",
            }
            clip_tables[kind] = clips
        for kind, name, label in PSF_KINDS:
            tiles = []
            clips = []
            for position in range(len(indices)):
                codes, clip = psf_codes(movie[name][position][y0:y1, x0:x1], ideal_peak)
                tiles.append(raster(_rgba(codes, psf_cmap, None)))
                clips.append(clip)
            canvas, rectangles = atlas(tiles)
            entry = bundle.write(f"{prefix}/atlas-psf-{kind}.png", png_from_raster(canvas), media_type="image/png", role="display_atlas")
            images[f"psf_{kind}"] = {
                "label": label,
                "source": f"movie.npz:{name} (job {job_id})",
                "unit": "log10 relative intensity",
                "atlas": ref(entry, f"{prefix}/case.json"),
                "tile_px": [x1 - x0, y1 - y0],
                "rectangles_xywh": rectangles,
                "frame_indices": indices,
                "scale": psf_scale,
                "window": psf_window,
                "axes": "x right, +y up (raster rows flipped once at encoding)",
                "zero_angle_cell_in_tile_column_row": [PSF_DISPLAY_HALF_WIDTH_CELLS, PSF_DISPLAY_HALF_WIDTH_CELLS - 1],
            }
            clip_tables[f"psf_{kind}"] = clips
        for kind, name, label in (
            ("uncorrected", "mean_psf_uncorrected", "Post-burn-in average, uncorrected reference"),
            ("corrected", "mean_psf_corrected", "Post-burn-in average, AO-corrected"),
        ):
            codes, clip = psf_codes(means[name][y0:y1, x0:x1], ideal_peak)
            entry = bundle.write(f"{prefix}/psf-average-{kind}.png", png_bytes(_rgba(codes, psf_cmap, None)), media_type="image/png", role="display_average")
            images[f"psf_average_{kind}"] = {
                "label": label,
                "source": f"mean_psfs.npz:{name} (job {job_id}); equal weights over frames [{job['burn_in']}, {job['n_steps']})",
                "image": ref(entry, f"{prefix}/case.json"),
                "scale": psf_scale,
                "window": psf_window,
                "clipping": clip,
                "sample_count": job["n_steps"] - job["burn_in"],
            }
        metrics = metrics_payload(record, history, job["burn_in"])
        metrics["schema"] = "ao-explorer.metrics.v1"
        metrics["case_id"] = case["id"]
        metrics["display_clipping"] = clip_tables
        metrics_entry = bundle.write_json(f"{prefix}/metrics.json", metrics, role="metrics")
        csv_entry = bundle.write(f"{prefix}/metrics.csv", metrics_csv(metrics["per_frame"]), media_type="text/csv", role="metrics_csv")
        config = producer.job_config(job)
        config_payload = {
            "schema": "ao-explorer.config.v1",
            "case_id": case["id"],
            "base_profile": f"{protocol.PROFILE_NAME}@{protocol.PROFILE_VERSION}",
            "base_profile_config_hash": plan["profile"]["config_hash"],
            "explorer_overrides": plan["explorer_overrides"],
            "case_override": case["override"],
            "root_seed": job["root_seed"],
            "realization_index": protocol.REALIZATION_INDEX,
            "effective_config_hash": record["config_hash"],
            "effective_parameters": job["effective_parameters"],
            "effective_configuration": producer.to_jsonable(config),
        }
        config_entry = bundle.write_json(f"{prefix}/config.json", config_payload, role="config")
        digests = record["observer"]["frames"]["atmosphere_sha256"]
        same = sum(1 for a, b in zip(digests, baseline_digests) if a == b)
        if case["id"] == "baseline":
            pairing = {"status": "reference", "matching_frames": same}
        elif same == len(digests):
            pairing = {"status": "paired", "matching_frames": same, "note": "all 180 atmosphere samples are byte-identical to the baseline's (streamed SHA-256 per frame)"}
        else:
            pairing = {
                "status": "different_atmosphere",
                "matching_frames": same,
                "note": "the atmosphere samples differ from the baseline's; r0 changes change the physical phase strength by construction, so differences are not a paired effect size",
            }
        unique_digests = len(set(digests))
        provenance = {
            "schema": "ao-explorer.provenance.v1",
            "case_id": case["id"],
            "series_id": plan["series_id"],
            "job_id": job_id,
            "attempt": attempt.name,
            "runtime_source": plan["identities"]["core"],
            "producer_exporter": record["identities"]["exporter"],
            "environment": record["identities"]["environment"],
            "lock": {key: record["identities"]["lock"][key] for key in ("lock", "lock_sha256", "installed_count", "verified", "violations")},
            "host": plan["identities"]["host"],
            "run": {
                "config_hash": record["config_hash"],
                "history_config_hash": record["history_config_hash"],
                "component_hashes": record["component_hashes"],
                "science_propagator_config_hash": record["science_propagator_config_hash"],
                "history_digest": record["history_digest"]["sha256"],
                "admission_sha256": record["admission_sha256"],
                "horizon_runtime_check": record["horizon_runtime_check"],
                "build_s": record["build_s"],
                "loop_s": record["loop_s"],
                "child_peak_rss_bytes": record["child_peak_rss_bytes"],
            },
            "raw_evidence": {
                "location": f"outputs/ao_explorer_v1/{plan['series_id']}/jobs/{job_id}/{attempt.name}/ (caller-owned, not in the web bundle)",
                "files": record["files"],
                "job_record_sha256": identity.sha256_file(attempt / "job_record.json"),
            },
            "derived_export": {"export_code_identity": derived_identity, "observation_code_identity": derived["observation_code_identity"], "observations_dir": observation_dir.name, "display_revision": DISPLAY_REVISION, "dataset_id": dataset_id},
            "atmosphere_pairing": pairing,
            "atmosphere_repetition": {"unique_frame_digests": unique_digests, "frames": len(digests), "repeated": unique_digests != len(digests)},
            "checks": record["observer"]["checks"],
        }
        provenance_entry = bundle.write_json(f"{prefix}/provenance.json", provenance, role="provenance")
        observation_entry = next(item for item in derived["entries"] if item["job_id"] == job_id)
        observation_images = {}
        for role in ("uncorrected", "corrected"):
            array = observations[f"{job_id}__{role}"]
            codes, clip = psf_codes(array, ideal_peak)
            entry = bundle.write(f"{prefix}/observation-{role}.png", png_bytes(_rgba(codes, psf_cmap, None)), media_type="image/png", role="observation")
            info = dict(observation_entry["observations"][role])
            info["display"] = {"image": ref(entry, f"{prefix}/observation.json"), "scale": psf_scale, "clipping": clip, "extent_mas": psf_window["native_extent_mas"]}
            observation_images[role] = info
        observation_payload = {
            "schema": "ao-explorer.observation.v1",
            "case_id": case["id"],
            "label": "Synthetic binary observation -- post-burn-in average; relative flux per numerical cell; no additional science-camera noise",
            "scene_id": scene_record["scene_id"],
            "scene_grid_id": scene_record["grid_id"],
            "scene": ref(scene_entry, f"{prefix}/observation.json"),
            "window": [job["burn_in"], job["n_steps"]],
            "sample_count": job["n_steps"] - job["burn_in"],
            "weights": "equal",
            "renderer_revision": binary_scene.RENDERER_REVISION,
            "policy": derived["policy"],
            "derived_arrays_sha256": derived["arrays_sha256"],
            "observation_code_identity": {"sha256": derived["observation_code_identity"]["sha256"], "files": derived["observation_code_identity"]["files"]},
            "roles": observation_images,
            "limitations": [
                "WFS detector noise is on and affects the AO residual; no science-camera noise, counts, SNR, limiting magnitude or detection significance is modelled.",
                "One spatially invariant on-axis PSF is assumed across the compact scene; no off-axis, isoplanatic or sky-coverage validation is implied.",
                "Frame-start snapshot average (140 x 1 ms nominal quadrature, timestamp span 0.139 s), not a finite-shutter exposure.",
                "The highest pixel of a binary image is not a Strehl ratio; Strehl stays a PSF metric.",
                "The guide-source magnitude is a WFS input; the scene's relative flux is the same in every case.",
            ],
        }
        obs_entry = bundle.write_json(f"{prefix}/observation.json", observation_payload, role="observation")
        case_payload = {
            "schema": "ao-explorer.case.v1",
            "case_id": case["id"],
            "label": case["label"],
            "group": case["group"],
            "question": case["question"],
            "override": case["override"],
            "effective_parameters": job["effective_parameters"],
            "time_domain": {
                "frames": job["n_steps"],
                "frame_rate_hz": job["effective_parameters"]["frame_rate_hz"],
                "frame_period_s": record["observer"]["frames"]["frame_period_s"][0],
                "sampling": "one atmosphere sample per frame at its start, t_k = k / f",
                "burn_in_frames": job["burn_in"],
                "analysis_window": [job["burn_in"], job["n_steps"]],
                "analysis_count": job["n_steps"] - job["burn_in"],
                "movie_indices": indices,
                "movie_times_s": [float(value) for value in movie["time_s"]],
            },
            "images": images,
            "members": {
                "metrics": ref(metrics_entry, f"{prefix}/case.json"),
                "metrics_csv": ref(csv_entry, f"{prefix}/case.json"),
                "config": ref(config_entry, f"{prefix}/case.json"),
                "provenance": ref(provenance_entry, f"{prefix}/case.json"),
                "observation": ref(obs_entry, f"{prefix}/case.json"),
            },
            "pairing": pairing,
            "validation": bound_records[job_id]["validation"],
            "limitations": [
                "Short single-realization synthetic SCAO demonstration (one seed, 180 frames); no ensemble uncertainty is shown.",
                "Science samples are frame-start snapshots; averages are equal-weight means of sampled instantaneous images.",
                "Recorded nodes only: no interpolation between cases and no unlisted parameter combination.",
                "The uncorrected image is a zero-DM optical counterfactual of the same recorded atmosphere, not a separate sensor/control trajectory.",
            ],
        }
        case_entry = bundle.write_json(f"{prefix}/case.json", case_payload, role="case")
        case_index_entries[case["id"]] = case_entry
        cases_out[case["id"]] = metrics["summary"]

    # The pilot exercises the same observation renderer on its own parents
    # ([16, 64), 48 samples).  Its images stay in the evidence directory with
    # pilot-only labels; they are never part of the public bundle.
    pilot_entry = next(item for item in derived["entries"] if item["job_id"] == "pilot-baseline")
    pilot_dir = observation_dir / f"pilot-render-{dataset_id}"
    pilot_dir.mkdir(parents=True, exist_ok=False)
    pilot_record = {"schema": "ao-explorer.pilot-render.v1", "label": "PILOT ONLY - not a production case", "roles": {}}
    for role in ("uncorrected", "corrected"):
        codes, clip = psf_codes(observations[f"pilot-baseline__{role}"], ideal_peak)
        data = png_bytes(_rgba(codes, psf_cmap, None))
        (pilot_dir / f"pilot-observation-{role}.png").write_bytes(data)
        pilot_record["roles"][role] = {
            "parent": pilot_entry["observations"][role]["parent"],
            "retained_fraction": pilot_entry["observations"][role]["retained_fraction"],
            "png_sha256": identity.sha256_bytes(data),
            "png_bytes": len(data),
            "clipping": clip,
            "scale": psf_scale,
        }
    producer.write_json(pilot_dir / "pilot-render.json", pilot_record)

    seed2 = producer.read_json(_attempt(series_dir, "sensitivity-baseline-seed2") / "job_record.json")
    control = producer.read_json(_attempt(series_dir, "control-baseline-no-observer") / "job_record.json")
    with np.load(_attempt(series_dir, "sensitivity-baseline-seed2") / "history.npz") as data:
        seed2_history = {name: np.array(data[name]) for name in data.files}
    diagnostics = {
        "schema": "ao-explorer.diagnostics.v1",
        "passivity": {
            "observed_job": "case-baseline",
            "control_job": "control-baseline-no-observer",
            "history_digest_observed": baseline_record["history_digest"]["sha256"],
            "history_digest_control": control["history_digest"]["sha256"],
            "identical": baseline_record["history_digest"] == control["history_digest"],
            "members_compared": sorted(baseline_record["history_digest"]["members"]),
        },
        "seed2_sensitivity": {
            "job": "sensitivity-baseline-seed2",
            "root_seed": protocol.SENSITIVITY_SEED,
            "summary": metrics_payload(seed2, seed2_history, protocol.PRODUCTION_BURN_IN)["summary"],
            "note": "One additional seed of the baseline only: a sensitivity check, not an ensemble, confidence interval or parameter scan.",
        },
    }
    diagnostics_entry = bundle.write_json("diagnostics.json", diagnostics, role="diagnostics")

    research_entry = research.export(bundle, series_dir=series_dir)

    manifest = {
        "schema": "ao-explorer.manifest.v1",
        "web_schema_version": WEB_SCHEMA_VERSION,
        "dataset_id": dataset_id,
        "title": "AO Simulation Explorer",
        "experiment_title": "2 m Interactive AO Experiment",
        "default_case": protocol.DEFAULT_CASE,
        "groups": protocol.GROUPS,
        "cases": {
            case["id"]: {
                "label": case["label"],
                "group": case["group"],
                "case": ref(case_index_entries[case["id"]], "manifest.json"),
            }
            for case in protocol.CASES
        },
        "scene": ref(scene_entry, "manifest.json"),
        "display": ref(display_entry, "manifest.json"),
        "diagnostics": ref(diagnostics_entry, "manifest.json"),
        "results": ref(research_entry, "manifest.json"),
        "summaries": cases_out,
        "series": {
            "series_id": plan["series_id"],
            "plan_sha256": identity.sha256_file(series_dir / producer.FROZEN_PLAN_NAME),
            "source_sha": plan["identities"]["core"]["git"]["git_head"],
        },
        "members": sorted(bundle.members.values(), key=lambda item: item["path"]),
    }
    manifest_bytes = (json.dumps(manifest, indent=1, allow_nan=False) + "\n").encode("utf-8")
    (bundle.base / "manifest.json").write_bytes(manifest_bytes)
    entry_pointer = {
        "schema": "ao-explorer.entry.v1",
        "dataset_id": dataset_id,
        "manifest": f"{dataset_id}/manifest.json",
        "manifest_bytes": len(manifest_bytes),
        "manifest_sha256": identity.sha256_bytes(manifest_bytes),
        "code_build": site["build"],
    }
    data_root.mkdir(parents=True, exist_ok=True)
    (data_root / "current.json").write_text(json.dumps(entry_pointer, indent=1) + "\n", encoding="utf-8")
    validation_dir = Path(web_dir) / "validation"
    validation_dir.mkdir(parents=True, exist_ok=True)
    export_record = {
        "schema": "ao-explorer.export-record.v1",
        "dataset_id": dataset_id,
        "manifest_sha256": entry_pointer["manifest_sha256"],
        "member_count": len(manifest["members"]),
        "member_bytes": sum(item["bytes"] for item in manifest["members"]),
        "export_code_identity": derived_identity,
        "observation_code_identity": derived["observation_code_identity"],
        "observations_dir": observation_dir.name,
        "series_plan_sha256": manifest["series"]["plan_sha256"],
        "processing_s": time.perf_counter() - started,
        "opd_display_limit": limits,
        "created_utc": producer.utc_now(),
    }
    (validation_dir / f"export-{dataset_id}.json").write_text(json.dumps(export_record, indent=1) + "\n", encoding="utf-8")
    shutil.copyfile(validation_dir / f"export-{dataset_id}.json", observation_dir / f"export-{dataset_id}.json")
    return export_record


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("stage", choices=("derive", "web"))
    parser.add_argument("--series-dir", type=Path, required=True)
    parser.add_argument("--web-dir", type=Path)
    arguments = parser.parse_args(argv)
    try:
        if arguments.stage == "derive":
            result = command_derive(arguments.series_dir)
            print(json.dumps({"status": "COMPLETED", "stage": "derive", "processing_s": result["processing_s"]}))
        else:
            if arguments.web_dir is None:
                parser.error("web needs --web-dir")
            result = command_web(arguments.series_dir, arguments.web_dir)
            print(json.dumps({"status": "COMPLETED", "stage": "web", "dataset_id": result["dataset_id"], "processing_s": result["processing_s"]}))
    except (RenderError, producer.ProducerError, binary_scene.BinarySceneError) as exc:
        print(json.dumps({"status": "REFUSED", "stage": arguments.stage, "reason": str(exc)}))
        return 3
    return 0


if __name__ == "__main__":
    sys.exit(main())
