"""Derived exports of the one-second explorer dataset (``long_series.py``).

Usage (after all eight production cases completed)::

    python scripts/ao_explorer/long_export.py \\
        --series-dir outputs/ao_explorer_1s/<series-id> \\
        --template-set outputs/ao_explorer_galaxy/<prepared-template-set> \\
        --template-record web/ao-explorer/derived/<prepared-template-set>/scene/galaxy-scene.json \\
        --previous-dataset web/ao-explorer/data/<previous-dataset-id> \\
        --web-dir web/ao-explorer \\
        --derived-root outputs/ao_explorer_1s_derived --galaxy-root outputs/ao_explorer_galaxy

Deterministic postprocessing only: no AO trajectory, random number or noise.
In order, and with every input bound before anything is written:

1. every case's completed attempt and every archived file, re-hashed in
   chunks against its case record;
2. descriptive, predeclared 100-frame (100 ms) block summaries of the scalar
   records (``block_summaries.json``);
3. the NGC 1705 observations: the prepared full-precision template (reused,
   not rebuilt from the FITS products) convolved with all 1000
   instantaneous PSF pairs of every case, streamed to float64 ``.npy``
   stacks, and with the two 800-frame mean PSFs;
4. the binary scene through the same two mean PSFs;
5. the browser bundle of the new dataset, its galaxy derivative and its RMS
   diagnostics (``rms_diagnostics.py``: the residual RMS after tip/tilt
   removal of every saved residual map), then the size check, and only then
   ``data/current.json``.

The browser shows a deterministic subset of actual frames (``DISPLAY_STRIDE``):
the complete 1000-frame scalar records, means and archives stay intact.
Atmosphere-side images (atmosphere maps, uncorrected PSFs and their
observations) that are byte-identical between cases are stored once.  The
previous 180-frame dataset, its galaxy derivative and its Research Results
stay where they are; the new manifest references the Research Results in
place, byte-identical, rather than copying them.
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import math
from pathlib import Path
import platform
import sys
import time
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

import binary_scene
import galaxy_export
import galaxy_scene
import galaxy_template
import identity
import long_series
import producer
import protocol
import render
import rms_diagnostics
import web_contract


# The export's content identity: every source whose bytes can change what this exporter accepts or writes.  The
# shared producer-check rule (web_contract.py) reads long_series.py and observer.py to derive its contract, so both
# are listed as well (review R19-01); observer.py stays part of the numerical producer identity too.
CODE_FILES = (
    "long_export.py",
    "long_series.py",
    "render.py",
    "binary_scene.py",
    "galaxy_scene.py",
    "galaxy_export.py",
    "galaxy_template.py",
    "identity.py",
    "producer.py",
    "protocol.py",
    "web_contract.py",
    "observer.py",
)
MANIFEST_SCHEMA = "ao-explorer.manifest.v2"
WEB_SCHEMA_VERSION = "ao-explorer.web.v2"
DISPLAY_REVISION = "ao-explorer.display.v2"
GALAXY_MANIFEST_SCHEMA = "ao-explorer.galaxy-manifest.v3"
GALAXY_OBSERVATION_SCHEMA = "ao-explorer.galaxy-observation.v3"
GALAXY_ENTRY_SCHEMA = "ao-explorer.galaxy-entry.v3"
GALAXY_DISPLAY_REVISION = "ao-explorer.galaxy-display.v3"

N_STEPS = long_series.N_STEPS
START = long_series.STARTUP_EXCLUSION_FRAMES
COUNT = N_STEPS - START
FRAME_PERIOD_S = 0.001
# Shown frames: every 8th frame (8 ms) plus the last frame.  This keeps the
# active site under the 30 MiB budget; see DISPLAY_RULE.
DISPLAY_STRIDE = 8
DISPLAY_RULE = (
    "frames k = 0, 8, 16, ..., 992 and the last frame 999 (126 actual recorded frames, including 0, 200 and 999); "
    "every 8th frame keeps the active site within the 30 MiB budget, while all 1000 frames remain in the numerical archives, "
    "the scalar records and the 800-frame means"
)
PLAYBACK_DURATIONS_S = (20, 25, 30)
PLAYBACK_DEFAULT_S = 20
SITE_BUDGET_BYTES = 30 * 1024 * 1024
FIRST_VIEW_BUDGET_BYTES = 5 * 1024 * 1024
OPD_CODES = 255  # display codes 0..254; palette index 255 is the transparent pupil exterior
OPD_EXTERIOR_INDEX = 255
MAP_KINDS = render.MAP_KINDS
PSF_KINDS = render.PSF_KINDS
ROLES = ("uncorrected", "corrected")
FIELDS = {"corrected": "pre_update_residual_opd_m", "uncorrected": "atmosphere_opd_m (zero-DM optical counterfactual)"}
PARENT_NORMALIZATION = "unit total flux over the complete uncropped propagator grid"
IMAGE_UNITS = {"atmosphere": "nm OPD", "correction": "nm OPD-equivalent (not mirror surface height)", "residual": "nm OPD"}
# Per case: the flux accounting of every instantaneous observation and the two mean observations.
FLUX_FILE = "flux_and_means.npz"


class LongExportError(RuntimeError):
    pass


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise LongExportError(message)


def producer_check_problems(checks: Any) -> web_contract.ProducerCheckProblems:
    """A case record's producer checks judged by the validator's rule (``web_contract``) on this exporter's window.

    Every reader applies the same contract: the recorded fields, each required check literally ``True``, the
    analysis frames and count as ints, the diagnostics' keys and finite values.  A truthiness filter over the
    booleans alone would pass a missing check, a string ``"false"`` or ``null``.
    """

    return web_contract.producer_check_problems(checks, web_contract.V2.producer_checks, (START, N_STEPS), COUNT)


def case_validation(record: Dict[str, Any]) -> Dict[str, bool]:
    """The ``validation`` record of a case entry, by the same rule :func:`bind_cases` requires."""

    return {"producer_checks_passed": producer_check_problems(record["observer"]["checks"]).ok}


def display_indices() -> List[int]:
    indices = sorted(set(range(0, N_STEPS, DISPLAY_STRIDE)) | {N_STEPS - 1})
    _require(indices[0] == 0 and START in indices and indices[-1] == N_STEPS - 1, "the display subset must include frames 0, 200 and 999")
    return indices


def flux_file_record(galaxy_id: str, case_id: str, path: Path) -> Dict[str, Any]:
    """The per-case flux-accounting archive as written: name, place, size, digest and arrays."""

    path = Path(path)
    _require(path.name == FLUX_FILE and path.is_file(), f"{case_id}: {path} is not the written {FLUX_FILE}")
    with np.load(path, allow_pickle=False) as data:
        names = sorted(data.files)
    return {
        "file": FLUX_FILE,
        "path": f"{case_id}/{FLUX_FILE}",
        "directory": f"outputs/ao_explorer_galaxy/{galaxy_id}/{case_id}/",
        "bytes": path.stat().st_size,
        "sha256": long_series.sha256_file_chunked(path),
        "arrays": names,
    }


def code_identity() -> Dict[str, Any]:
    record = identity.file_set_identity(CODE_FILES)
    record["git"] = identity.git_state(identity.EXPORTER_DIR.relative_to(identity.REPO_ROOT).as_posix())
    return record


def environment() -> Dict[str, Any]:
    import matplotlib
    import PIL
    import scipy

    return {
        "python": platform.python_version(),
        "numpy": np.__version__,
        "scipy": scipy.__version__,
        "pillow": PIL.__version__,
        "matplotlib": matplotlib.__version__,
        "machine": platform.machine(),
    }


def _json_bytes(value: Any) -> bytes:
    return (json.dumps(value, indent=1, allow_nan=False, ensure_ascii=False) + "\n").encode("utf-8")


def _array_sha(array: np.ndarray) -> str:
    return identity.sha256_bytes(np.ascontiguousarray(array).tobytes())


def _stack_sha(stack: np.ndarray) -> str:
    """SHA-256 of a C-ordered stack's raw bytes, frame by frame (no whole-stack copy)."""

    import hashlib

    digest = hashlib.sha256()
    for index in range(stack.shape[0]):
        digest.update(np.ascontiguousarray(stack[index]).tobytes())
    return digest.hexdigest()


# ---------------------------------------------------------------------------
# Bundles


class Bundle:
    """Members written under one directory, hashed as written; identical images are stored once."""

    def __init__(self, base: Path) -> None:
        self.base = Path(base)
        self.members: Dict[str, Dict[str, Any]] = {}
        self._shared: Dict[str, Dict[str, Any]] = {}

    def write(self, relative: str, data: bytes, *, media_type: str, role: str, user: Optional[str] = None, share: bool = False) -> Dict[str, Any]:
        digest = identity.sha256_bytes(data)
        if share and digest in self._shared:
            entry = self._shared[digest]
            if user is not None and user not in entry["used_by"]:
                entry["used_by"].append(user)
            return entry
        path = self.base / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("xb") as handle:
            handle.write(data)
        entry = {"path": relative, "bytes": len(data), "sha256": digest, "media_type": media_type, "role": role}
        if share:
            entry["used_by"] = [] if user is None else [user]
            self._shared[digest] = entry
        self.members[relative] = entry
        return entry

    def write_json(self, relative: str, value: Any, *, role: str) -> Dict[str, Any]:
        return self.write(relative, _json_bytes(value), media_type="application/json", role=role)

    def total_bytes(self) -> int:
        return sum(item["bytes"] for item in self.members.values())


ref = render.ref


def palette_png(raster_codes: np.ndarray, lut: np.ndarray, *, transparent_index: Optional[int] = None) -> bytes:
    """An 8-bit indexed PNG: palette index = display code (optionally one transparent index)."""

    from PIL import Image

    codes = np.ascontiguousarray(raster_codes, dtype=np.uint8)
    image = Image.frombytes("P", (codes.shape[1], codes.shape[0]), codes.tobytes())
    image.putpalette(np.asarray(lut, dtype=np.uint8).reshape(-1).tolist())
    buffer = io.BytesIO()
    if transparent_index is None:
        image.save(buffer, format="PNG", optimize=True)
    else:
        image.save(buffer, format="PNG", optimize=True, transparency=transparent_index)
    return buffer.getvalue()


def opd_lut() -> np.ndarray:
    from matplotlib import colormaps

    rgb = (np.asarray(colormaps[render.OPD_CMAP](np.linspace(0.0, 1.0, OPD_CODES)))[:, :3] * 255.0 + 0.5).astype(np.uint8)
    return np.vstack([rgb, np.array([[128, 128, 128]], dtype=np.uint8)])


def opd_codes(values_m: np.ndarray, mask: np.ndarray, limit_m: float) -> Tuple[np.ndarray, Dict[str, float]]:
    """Codes 0..254 of an OPD map on the fixed symmetric scale; the exterior is index 255."""

    inside = np.where(mask, np.asarray(values_m, dtype=float), 0.0)
    scaled = (inside + limit_m) / (2.0 * limit_m)
    codes = np.clip(np.floor(np.clip(scaled, 0.0, 1.0) * (OPD_CODES - 1) + 0.5), 0, OPD_CODES - 1).astype(np.uint8)
    codes[~mask] = OPD_EXTERIOR_INDEX
    count = np.count_nonzero(mask)
    return codes, {
        "clipped_low_fraction": float(np.count_nonzero(mask & (inside < -limit_m)) / count),
        "clipped_high_fraction": float(np.count_nonzero(mask & (inside > limit_m)) / count),
    }


def code_atlas(tiles: List[np.ndarray], fill: int = 0) -> Tuple[np.ndarray, List[List[int]]]:
    height, width = tiles[0].shape
    rows = math.ceil(len(tiles) / render.ATLAS_COLUMNS)
    canvas = np.full((rows * height, render.ATLAS_COLUMNS * width), fill, dtype=np.uint8)
    rectangles = []
    for index, tile in enumerate(tiles):
        row, column = divmod(index, render.ATLAS_COLUMNS)
        canvas[row * height:(row + 1) * height, column * width:(column + 1) * width] = tile
        rectangles.append([column * width, row * height, width, height])
    return canvas, rectangles


# ---------------------------------------------------------------------------
# Inputs


def bind_cases(series_dir: Path, plan: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    """Every case's completed attempt, its record and its archives re-hashed against the record."""

    cases: Dict[str, Dict[str, Any]] = {}
    for case_id in long_series.CASE_ORDER:
        attempt = long_series.completed_attempt(series_dir, case_id)
        _require(attempt is not None, f"{case_id} has no completed attempt")
        record_path = attempt / "case_record.json"
        record_bytes = record_path.read_bytes()
        record = json.loads(record_bytes.decode("utf-8"))
        case = long_series.plan_case(plan, case_id)
        _require(record["series_id"] == plan["series_id"] and record["case"]["case_id"] == case_id, f"{case_id}: the record names another series or case")
        _require(record["config_hash"] == case["config_hash"] and record["admission_sha256"] == case["admission_sha256"], f"{case_id}: the record's configuration or admission differs from the plan")
        _require(record["identities"]["production_sha256"] == plan["identities"]["production"]["sha256"], f"{case_id}: produced by another producer identity")
        problems = producer_check_problems(record["observer"]["checks"])
        _require(problems.kind is None and not (problems.missing or problems.unexpected or problems.not_true or problems.diagnostics),
                 f"{case_id}: the production record checks do not meet the producer's contract ({problems})")
        _require(not (problems.frames_wrong or problems.count_wrong), f"{case_id}: the analysis window is not [{START}, {N_STEPS}) with {COUNT} frames")
        _require(record["screen"]["generated_screen_px"] == long_series.SCREEN_GRID_SIZE and record["screen"]["option"] == {"screen_grid_size": long_series.SCREEN_GRID_SIZE}, f"{case_id}: not the 624 x 624 screen")
        rehashed = {}
        for relative, item in record["files"].items():
            path = attempt / relative
            digest = long_series.sha256_file_chunked(path)
            _require(path.stat().st_size == item["bytes"] and digest == item["sha256"], f"{case_id}/{relative}: size or SHA-256 differs from the case record")
            rehashed[relative] = {"bytes": item["bytes"], "sha256": digest}
        cases[case_id] = {
            "attempt": attempt,
            "record": record,
            "record_sha256": identity.sha256_bytes(record_bytes),
            "files": rehashed,
            "frames_dir": attempt / "frames",
        }
    return cases


def load_stack(case: Dict[str, Any], name: str) -> np.ndarray:
    stack = np.load(case["frames_dir"] / f"{name}.npy", mmap_mode="r")
    _require(stack.dtype == np.float64 and stack.shape[0] == N_STEPS and stack.flags["C_CONTIGUOUS"], f"{name}: not a C-ordered float64 stack of 1000 frames")
    return stack


def load_means(case: Dict[str, Any]) -> Dict[str, np.ndarray]:
    with np.load(case["attempt"] / "mean_psfs.npz", allow_pickle=False) as data:
        arrays = {name: np.array(data[name]) for name in data.files}
    _require(arrays["analysis_frames"].tolist() == list(range(START, N_STEPS)), "the mean PSFs do not cover frames 200-999")
    return arrays


def load_history(case: Dict[str, Any]) -> Dict[str, np.ndarray]:
    with np.load(case["attempt"] / "history.npz", allow_pickle=False) as data:
        return {name: np.array(data[name]) for name in data.files}


def check_parent(case_id: str, case: Dict[str, Any], means: Dict[str, np.ndarray], grid: Dict[str, Any]) -> None:
    """The recorded science semantics of the two mean PSFs (as render.check_parent_semantics, for [200, 1000))."""

    record = case["record"]
    observer = record["observer"]
    _require({"atmosphere_opd_m", "pre_update_residual_opd_m"} <= set(observer["requested_fields"]), f"{case_id}: the observer did not request both OPD fields")
    _require(observer["sampling_metadata"]["normalization"] == "unit_total_flux", f"{case_id}: unexpected image normalization")
    hashes = set()
    for role in ROLES:
        accumulator = observer["accumulators"][role]
        selection = accumulator["selection"]
        metadata = accumulator["metadata"]
        _require(accumulator["schema"] == render.PARENT_SCHEMA and accumulator["wavelengths_m"] == [protocol.SCIENCE_WAVELENGTH_M], f"{case_id}: {role} parent schema or wavelength")
        _require(accumulator["residual"] == "pre_update" and selection["residual"] == "pre_update", f"{case_id}: {role} parent residual")
        _require(accumulator["propagator_backend"] == "native" and accumulator["propagator_config_hash"] == record["science_propagator_config_hash"], f"{case_id}: {role} parent propagator")
        _require(accumulator["flux_denominator"] == "normalized_source_grid_flux" and metadata == {**render.PARENT_METADATA, "flux_denominator": "normalized_source_grid_flux"}, f"{case_id}: {role} parent metadata")
        _require(
            selection["first_frame"] == START and selection["last_frame"] == N_STEPS - 1 and selection["sample_count"] == COUNT
            and selection["burn_in_frames"] == START and selection["stride"] == 1 and selection["uniform_weights"] is True
            and selection["weight_sum"] == float(COUNT) and math.isclose(selection["frame_period_s"], FRAME_PERIOD_S, rel_tol=1e-12)
            and selection["temporal_quadrature"] == render.PARENT_METADATA["temporal_quadrature"],
            f"{case_id}: {role} accumulator selection is not the equal-weight [200, 1000) window",
        )
        _require(accumulator["reset_count"] == 0, f"{case_id}: {role} accumulator was reset")
        values = means[f"mean_psf_{role}"]
        _require(list(values.shape) == grid["shape_yx"] and bool(np.all(np.isfinite(values))) and not bool(np.any(values < 0.0)), f"{case_id}: {role} mean PSF shape or values")
        _require(abs(float(np.sum(values)) - 1.0) <= protocol.TOLERANCES["unit_flux"]["atol"], f"{case_id}: {role} mean PSF flux is not unit")
        hashes.add(accumulator["config_hash"])
    _require(len(hashes) == 1, f"{case_id}: the two accumulators have different configurations")
    for axis in ("x", "y"):
        _require(_array_sha(means[f"{axis}_angle_rad"]) == grid[f"{axis}_angle_rad_sha256"], f"{case_id}: the {axis} axis differs from the PSF grid")


def parent_record(case_id: str, case: Dict[str, Any], means: Dict[str, np.ndarray], role: str) -> Dict[str, Any]:
    record = case["record"]
    accumulator = record["observer"]["accumulators"][role]
    frames = record["observer"]["frames"]
    name = f"mean_psf_{role}"
    return {
        "case_id": case_id,
        "role": role,
        "field": FIELDS[role],
        "array": name,
        "array_sha256": _array_sha(means[name]),
        "file": "mean_psfs.npz",
        "file_sha256": case["files"]["mean_psfs.npz"]["sha256"],
        "shape": list(means[name].shape),
        "window": [START, N_STEPS],
        "sample_count": COUNT,
        "stride": 1,
        "weights": "equal",
        "frame_period_s": frames["frame_period_s"][0],
        "first_timestamp_s": frames["time_s"][START],
        "last_timestamp_s": frames["time_s"][N_STEPS - 1],
        "timestamp_span_s": frames["time_s"][N_STEPS - 1] - frames["time_s"][START],
        "nominal_quadrature_duration_s": COUNT * frames["frame_period_s"][0],
        "sampling": "frame-start instantaneous snapshots; not a finite-shutter sub-frame integration",
        "recentering": "none",
        "coaddition": "intensity",
        "normalization": PARENT_NORMALIZATION,
        "accumulator_config_hash": accumulator["config_hash"],
        "propagator_config_hash": accumulator["propagator_config_hash"],
        "run_config_hash": record["config_hash"],
        "history_config_hash": record["history_config_hash"],
        "x_angle_rad_sha256": _array_sha(means["x_angle_rad"]),
        "y_angle_rad_sha256": _array_sha(means["y_angle_rad"]),
        "wavelength_m": accumulator["wavelengths_m"][0],
        "total_flux": float(np.sum(means[name])),
    }


# ---------------------------------------------------------------------------
# Scalars


def block_summaries(plan: Dict[str, Any], cases: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
    out = {}
    for case_id, case in cases.items():
        frames = case["record"]["observer"]["frames"]
        residual = np.asarray(frames["residual_rms_m"], dtype=float) * 1e9
        strehl_ao = np.asarray(frames["peak_strehl_corrected"], dtype=float)
        strehl_open = np.asarray(frames["peak_strehl_uncorrected"], dtype=float)
        saturation = np.asarray(frames["saturation_fraction"], dtype=float)
        usable = np.asarray(frames["reconstruction_usable"], dtype=bool)

        def stats(values: np.ndarray, part: slice) -> Dict[str, float]:
            piece = values[part]
            return {"mean": float(np.mean(piece)), "std": float(np.std(piece)), "min": float(np.min(piece)), "max": float(np.max(piece))}

        blocks = []
        for start, stop in plan["block_summaries"]["blocks"]:
            part = slice(start, stop)
            blocks.append({
                "frames": [start, stop],
                "time_ms": [start, stop],
                "in_analysis_window": start >= START,
                "residual_rms_nm": stats(residual, part),
                "peak_strehl_corrected": stats(strehl_ao, part),
                "peak_strehl_uncorrected": stats(strehl_open, part),
                "saturation_fraction": {**stats(saturation, part), "frames_with_any_clipped": int(np.count_nonzero(saturation[part] > 0.0))},
                "unusable_reconstructions": int(np.count_nonzero(~usable[part])),
            })
        analysis = [block for block in blocks if block["in_analysis_window"]]
        means = [block["residual_rms_nm"]["mean"] for block in analysis]
        strehls = [block["peak_strehl_corrected"]["mean"] for block in analysis]
        out[case_id] = {
            "blocks": blocks,
            "analysis_blocks": {
                "count": len(analysis),
                "residual_rms_nm_block_means_range": [min(means), max(means)],
                "residual_rms_nm_block_means_std": float(np.std(means)),
                "peak_strehl_corrected_block_means_range": [min(strehls), max(strehls)],
                "first_minus_last_residual_rms_nm": means[0] - means[-1],
                "frames_with_any_clipped": sum(block["saturation_fraction"]["frames_with_any_clipped"] for block in analysis),
            },
        }
    return {
        "schema": "ao-explorer.blocks.v1",
        "series_id": plan["series_id"],
        "definition": plan["block_summaries"],
        "notice": (
            "Descriptive statistics of one realization of each case.  The 200-frame startup exclusion is a predeclared "
            "analysis choice, not a demonstrated controller settling time.  r0, the outer scale and the wind are fixed "
            "within a case; block-to-block changes accompany the frozen-flow realization moving across the pupil and do "
            "not by themselves show controller divergence or a change of the configured turbulence strength.  One second "
            "does not establish convergence of the finite-window average to a long-exposure result."
        ),
        "cases": out,
    }


def finite_series(values: List[float], reason: str) -> Dict[str, Any]:
    return render.finite_or_null(values, reason)


def metrics_payload(case_id: str, case: Dict[str, Any], history: Dict[str, np.ndarray]) -> Dict[str, Any]:
    record = case["record"]
    frames = record["observer"]["frames"]
    window = slice(START, N_STEPS)
    residual = np.asarray(frames["residual_rms_m"])
    atmosphere = np.asarray(frames["atmosphere_rms_m"])
    s_corr = np.asarray(frames["peak_strehl_corrected"])
    s_unc = np.asarray(frames["peak_strehl_uncorrected"])
    valid = np.asarray(history["valid_measurement_fraction"], dtype=float)
    valid_subap = np.asarray(history["valid_subaperture_fraction"], dtype=float)
    usable = np.asarray(history["reconstruction_usable"], dtype=bool)
    saturation = np.asarray(history["saturation_fraction"], dtype=float)
    corrected = record["observer"]["accumulators"]["corrected"]["metrics"][0]
    uncorrected = record["observer"]["accumulators"]["uncorrected"]["metrics"][0]
    _require(len(frames["frame_index"]) == N_STEPS and usable.size == N_STEPS, f"{case_id}: incomplete scalar records")
    per_frame = {
        "frame_index": list(range(N_STEPS)),
        "time_s": [float(value) for value in frames["time_s"]],
        "atmosphere_rms_nm": finite_series((atmosphere * 1e9).tolist(), "non-finite reduction"),
        "residual_rms_nm": finite_series((residual * 1e9).tolist(), "non-finite reduction"),
        "peak_strehl_uncorrected": finite_series(s_unc.tolist(), "non-finite reduction"),
        "peak_strehl_corrected": finite_series(s_corr.tolist(), "non-finite reduction"),
        "valid_measurement_fraction": finite_series(valid.tolist(), "non-finite"),
        "valid_subaperture_fraction": finite_series(valid_subap.tolist(), "non-finite"),
        "reconstruction_usable": [bool(value) for value in usable],
        "dm_saturation_fraction": finite_series(saturation.tolist(), "non-finite"),
    }
    summary = {
        "window": [START, N_STEPS],
        "sample_count": COUNT,
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
        "dm_saturation_fraction": "fraction of DM actuators whose requested command magnitude exceeds the 1 um OPD stroke limit and is clipped, for the command issued by frame k's update (loop history saturation_fraction[k]); that command is held during frame k + 1, so the correction shown for frame k is the command issued at frame k - 1",
        "mean_dm_saturation_fraction / max_dm_saturation_fraction": f"mean and maximum over the commands issued in frames {START}-{N_STEPS - 1} (held during frames {START + 1}-{N_STEPS})",
        "mean_residual_rms_nm": "mean of the per-frame residual RMS over the analysis window",
        "root_mean_square_residual_nm": "square root of the mean per-frame mean square over the analysis window",
        "mean_instantaneous_peak_strehl_*": "mean of per-frame instantaneous peak Strehl over the analysis window",
        "average_psf_peak_strehl_*": f"peak Strehl of the equal-weight average of the {COUNT} instantaneous images of frames {START}-{N_STEPS - 1} (production long-exposure accumulator); differs from the mean instantaneous Strehl",
    }
    return {
        "schema": "ao-explorer.metrics.v2",
        "case_id": case_id,
        "per_frame": per_frame,
        "summary": summary,
        "definitions": definitions,
        "excluded": {
            "post_update_residual": "excluded from the main page (same-sample diagnostic)",
            "lost_lock": "the history's final-frame heuristic is not exported as a lock classifier",
        },
    }


# ---------------------------------------------------------------------------
# Export


def opd_limit(cases: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
    percentiles = []
    for case in cases.values():
        for _, name, _ in MAP_KINDS:
            stack = load_stack(case, name)
            mask = np.isfinite(stack[0])
            values = np.empty((N_STEPS, int(np.count_nonzero(mask))), dtype=float)
            for index in range(N_STEPS):
                frame = np.asarray(stack[index])[mask]
                values[index] = frame - frame.mean()
            percentiles.append(float(np.percentile(np.abs(values), render.OPD_LIMIT_PERCENTILE)))
            del values, stack
    raw = max(percentiles)
    limit = math.ceil(raw / render.OPD_LIMIT_QUANTUM_M) * render.OPD_LIMIT_QUANTUM_M
    return {
        "limit_m": limit,
        "rule": (
            f"max over the eight cases and the three map kinds of the {render.OPD_LIMIT_PERCENTILE} percentile of |OPD - pupil mean| "
            f"inside the pupil over all {N_STEPS} frames, rounded up to {render.OPD_LIMIT_QUANTUM_M * 1e9:.0f} nm"
        ),
        "raw_max_percentile_m": raw,
        "colormap": render.OPD_CMAP,
        "scale": "linear, symmetric about zero",
    }


def export(arguments: argparse.Namespace) -> Dict[str, Any]:
    import site_build

    started = time.perf_counter()
    series_dir = Path(arguments.series_dir).resolve()
    web_dir = Path(arguments.web_dir)
    site = site_build.check(web_dir, entry=False)
    _require(not site["problems"], "the site code is not in its content-addressed build directory: " + "; ".join(site["problems"]))
    plan = long_series.load_plan(series_dir)
    plan_sha = identity.sha256_file(series_dir / long_series.PLAN_NAME)
    production_now = long_series.production_identity()
    _require(production_now["sha256"] == plan["identities"]["production"]["sha256"], "the producer files changed since production; the archives would not be bound to the current source")
    cases = bind_cases(series_dir, plan)
    indices = display_indices()
    positions = {frame: position for position, frame in enumerate(indices)}

    # Previous dataset: binary scene and grid identity, Research Results (referenced in place).
    previous_dir = Path(arguments.previous_dataset)
    previous_manifest_bytes = (previous_dir / "manifest.json").read_bytes()
    previous_manifest = json.loads(previous_manifest_bytes.decode("utf-8"))
    previous_members = {item["path"]: item for item in previous_manifest["members"]}
    previous_scene = json.loads((previous_dir / "scene" / "scene.json").read_bytes().decode("utf-8"))
    _require(identity.sha256_file(previous_dir / "scene" / "scene.json") == previous_members["scene/scene.json"]["sha256"], "the previous scene record differs from its manifest")
    research_item = previous_members["research/results.json"]
    _require(identity.sha256_file(previous_dir / "research" / "results.json") == research_item["sha256"], "the previous Research Results differ from their manifest")
    research_members = [item for path, item in previous_members.items() if path.startswith("research/")]
    for item in research_members:
        _require(identity.sha256_file(previous_dir / item["path"]) == item["sha256"], f"previous research member {item['path']} differs from its manifest")

    # Prepared template: the full-precision array and its record, reused (no FITS reprocessing).
    template_set = Path(arguments.template_set)
    template_path = template_set / "template.npz"
    template_record_path = Path(arguments.template_record)
    template_export = json.loads(template_record_path.read_bytes().decode("utf-8"))
    template_record = template_export["scene"]
    with np.load(template_path, allow_pickle=False) as data:
        template = np.array(data["template"])
        template_x = np.array(data["x_angle_rad"])
        template_y = np.array(data["y_angle_rad"])
        saturated_cells = np.array(data["saturated_cells"])
    _require(_array_sha(template) == template_record["template_array_sha256"], "the prepared template array differs from its record")
    target_grid = template_record["target"]["grid"]
    _require(_array_sha(template_x) == target_grid["x_angle_rad_sha256"] and _array_sha(template_y) == target_grid["y_angle_rad_sha256"], "the prepared template axes differ from their record")

    baseline_means = load_means(cases["baseline"])
    x_axis, y_axis = baseline_means["x_angle_rad"], baseline_means["y_angle_rad"]
    grid = galaxy_scene.grid_record(x_axis, y_axis)
    _require(galaxy_scene.grid_id(grid) == previous_scene["scene"]["grid_id"] == template_record["target"]["kernel_grid_id"], "the PSF grid differs from the binary-scene grid or the template's kernel grid")
    scene_bundle = binary_scene.build_scene(x_axis, y_axis, wavelength_m=protocol.SCIENCE_WAVELENGTH_M, telescope_diameter_m=2.0)
    _require(scene_bundle["record"] == previous_scene["scene"], "the binary scene rebuilt on this grid differs from the published scene record")
    convolver = galaxy_scene.Convolver(template, template_x, template_y, x_axis, y_axis)
    _require(convolver.context_complete, "the template does not cover the kernel reach of the window")
    ideal = np.array(baseline_means["ideal_psf"])
    ideal_peak = float(np.max(ideal))

    code = code_identity()
    dataset_key = identity.sha256_bytes(identity.canonical_json_bytes({
        "series": plan["series_id"], "plan": plan_sha, "export_code": code["sha256"], "display": DISPLAY_REVISION, "display_indices": indices,
    }))[:12]
    dataset_id = f"{plan['series_id']}-e{dataset_key}"
    data_root = web_dir / "data"
    derived_dir = Path(arguments.derived_root) / dataset_id
    _require(not (data_root / dataset_id).exists() and not derived_dir.exists(), f"{dataset_id} exists; an export is never overwritten")
    galaxy_key = identity.sha256_bytes(identity.canonical_json_bytes({
        "dataset": dataset_id, "plan": plan_sha, "scene_id": template_record["scene_id"], "code": code["sha256"], "display": GALAXY_DISPLAY_REVISION,
    }))[:12]
    galaxy_id = f"ngc1705-f814w-{plan['series_id'].removeprefix('series-')}-g{galaxy_key}"
    galaxy_web = web_dir / "derived" / galaxy_id
    galaxy_out = Path(arguments.galaxy_root) / galaxy_id
    _require(not galaxy_web.exists() and not galaxy_out.exists(), f"{galaxy_id} exists; an export is never overwritten")

    blocks = block_summaries(plan, cases)
    limits = opd_limit(cases)
    opd_palette = opd_lut()
    psf_palette = render._colormap(render.PSF_CMAP)
    galaxy_palette = galaxy_export._colormap()
    x0, x1 = render.crop_bounds(x_axis)
    y0, y1 = render.crop_bounds(y_axis)
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
        "mapping": f"log10(I / I_ideal_peak) clipped to [-{render.PSF_LOG_DECADES:g}, 0]",
        "ideal_peak_cell_flux": ideal_peak,
        "ideal_reference": "zero-OPD image of the same native propagator, wavelength and grid (unit total flux)",
        "colormap": render.PSF_CMAP,
        "normalization": "common to every frame, case, role, average image, observation and the scene reference; no per-image peak normalization",
    }
    times = [index * FRAME_PERIOD_S for index in indices]
    recorded_times = cases["baseline"]["record"]["observer"]["frames"]["time_s"]
    _require(all(recorded_times[k] == k / 1000.0 for k in range(N_STEPS)), "recorded sample times are not k / 1000 s")
    display_times = [float(recorded_times[k]) for k in indices]
    playback = {
        "interval_s": [0.0, N_STEPS * FRAME_PERIOD_S],
        "interval_rule": f"from the start of frame 0 to the end of frame {N_STEPS - 1} ({N_STEPS} frames of 1 ms): the physical interval [0.000, 1.000) s",
        "durations_s": list(PLAYBACK_DURATIONS_S),
        "default_duration_s": PLAYBACK_DEFAULT_S,
        "reduced_motion_duration_s": max(PLAYBACK_DURATIONS_S),
        "timing": "the wall-clock instant of simulated time t is anchor + t x (duration / 1.000 s); each displayed frame is shown from its recorded timestamp until the next displayed timestamp, the last (frame 999) until 1.000 s",
        "loop_default": False,
        "loop": "optional; repeats the same recorded trajectory from frame 0 and can jump at the boundary; it does not extend the simulation",
        "interpolation": "none",
    }
    time_domain = {
        "frames": N_STEPS,
        "frame_rate_hz": 1000.0,
        "frame_period_s": FRAME_PERIOD_S,
        "frame_indices": [0, N_STEPS - 1],
        "sample_times_s": [0.0, float(recorded_times[-1])],
        "physical_interval_s": [0.0, N_STEPS * FRAME_PERIOD_S],
        "sampling": "one atmosphere sample per frame at its start, t_k = k / f",
        "startup_exclusion_frames": START,
        "burn_in_frames": START,
        "analysis_window": [START, N_STEPS],
        "analysis_count": COUNT,
        "analysis_rule": plan["analysis_window"]["declared"],
        "display_indices": indices,
        "display_times_s": display_times,
        "display_count": len(indices),
        "display_rule": DISPLAY_RULE,
        "retained_full_precision_frames": N_STEPS,
    }
    _require(np.allclose(display_times, times, rtol=0.0, atol=1e-15), "display timestamps differ from their indices")

    bundle = Bundle(data_root / dataset_id)
    display_payload = {
        "schema": "ao-explorer.display.v2",
        "revision": DISPLAY_REVISION,
        "opd": {
            **limits,
            "levels": OPD_CODES,
            "code_rule": f"code = round(clip((OPD + L) / (2 L), 0, 1) * {OPD_CODES - 1}); PNG palette index = code; index {OPD_EXTERIOR_INDEX} = pupil exterior (transparent)",
            "lut_rgb_hex": ["#%02x%02x%02x" % tuple(int(v) for v in row) for row in opd_palette[:OPD_CODES]],
        },
        "psf": {
            **psf_scale,
            "decades": render.PSF_LOG_DECADES,
            "code_rule": f"code = round(clip((log10(I / I_ideal_peak) + {render.PSF_LOG_DECADES:g}) / {render.PSF_LOG_DECADES:g}, 0, 1) * 255); PNG palette index = code",
            "lut_rgb_hex": ["#%02x%02x%02x" % tuple(int(v) for v in row) for row in psf_palette],
        },
        "psf_window": psf_window,
        "encoding": "8-bit indexed PNG atlases whose palette is the recorded colour table",
        "raster": "PNG row 0 is the +y edge (rows flipped once at encoding); columns increase with +x",
        "upscaling": "nearest-neighbour in the browser (image smoothing disabled); no interpolation of values",
    }
    display_entry = bundle.write_json("display.json", display_payload, role="display")
    scene_codes, scene_clip = render.psf_codes(scene_bundle["scene"], ideal_peak)
    scene_png = bundle.write("scene/scene-reference.png", palette_png(render.raster(scene_codes), psf_palette), media_type="image/png", role="scene_reference")
    scene_json = {
        "schema": "ao-explorer.scene-export.v1",
        "scene": scene_bundle["record"],
        "display": {
            "image": ref(scene_png, "scene/scene.json"),
            "scale": psf_scale,
            "clipping": scene_clip,
            "note": "Point sources occupy single cells; their values exceed the display maximum and are shown clipped.",
            "raster": "row 0 of the PNG is +y top; columns increase with +x",
            "extent_mas": psf_window["native_extent_mas"],
        },
    }
    scene_entry = bundle.write_json("scene/scene.json", scene_json, role="scene")
    blocks_entry = bundle.write_json("blocks.json", blocks, role="block_summaries")

    galaxy_bundle = Bundle(galaxy_web)
    zero = grid["x_zero_index"]
    cells = galaxy_export.DISPLAY_CELLS
    d0, d1 = zero - cells // 2, zero + cells // 2
    t0 = galaxy_template.TEMPLATE_CELLS // 2 - cells // 2
    t1 = t0 + cells
    reference = float(template_record["peak_cell"])
    galaxy_scale = {
        "mapping": f"asinh(I / (beta I_ref)) / asinh(1 / beta), beta = {galaxy_export.ASINH_SOFTENING:g}, clipped to [0, 1]",
        "stretch": "asinh",
        "softening_beta": galaxy_export.ASINH_SOFTENING,
        "reference": "brightest cell of the prepared template (in the saturated core region of NGC 1705-1; a fixed display number, not a physical peak)",
        "reference_cell_flux": reference,
        "colormap": galaxy_export.COLORMAP,
        "colorbar_ticks": galaxy_export.COLORBAR_TICKS,
        "code_rule": f"code = round(clip(asinh(max(I, 0) / ({galaxy_export.ASINH_SOFTENING:g} I_ref)) / asinh({1 / galaxy_export.ASINH_SOFTENING:g}), 0, 1) * 255); PNG palette index = code",
        "normalization": "common to the template, every displayed sample, both mean images, both roles and every case; no image is normalized to its own maximum",
        "lut_rgb_hex": ["#%02x%02x%02x" % tuple(int(v) for v in row) for row in galaxy_palette],
    }
    sat_rows, sat_cols = np.nonzero(saturated_cells[t0:t1, t0:t1])
    galaxy_window = {
        "cells": [cells, cells],
        "native_window_index": [[d0, d1], [d0, d1]],
        "template_index": [[t0, t1], [t0, t1]],
        "cell_mas": template_record["target"]["step_mas"][0],
        "extent_arcsec": cells * template_record["target"]["step_mas"][0] / 1000.0,
        "extent_mas": [(-cells // 2 - 0.5) * template_record["target"]["step_mas"][0], (cells // 2 - 0.5) * template_record["target"]["step_mas"][0]],
        "orientation": "north up, east left (+x west, +y north on the template's projection plane)",
        "saturation_envelope_box_cells": None if sat_rows.size == 0 else {"x": [int(sat_cols.min()), int(sat_cols.max()) + 1], "y": [int(sat_rows.min()), int(sat_rows.max()) + 1], "rows": "counted from the -y (south) edge", "definition": "template cells touching the conservative saturation envelope (flags dilated by one mosaic pixel); an enlarged marker, not the exact saturated extent"},
        "note": "the observation crop is declared separately from the PSF panels' 64 x 64 crop; the native window (156 cells, about 8.7 arcsec) is recorded in the flux accounting and the template extends to 312 cells for convolution context",
    }
    template_codes, template_clip = galaxy_export.display_codes(template[t0:t1, t0:t1], reference)
    template_png = galaxy_bundle.write("scene/template.png", galaxy_export.png_bytes(galaxy_export.raster(template_codes), galaxy_palette), media_type="image/png", role="galaxy_template")
    galaxy_scene_export = {
        "schema": galaxy_export.SCHEMA_SCENE_EXPORT,
        "scene": template_record,
        "display": {
            "image": ref(template_png, "scene/galaxy-scene.json"),
            "window": galaxy_window,
            "window_flux_fraction": float(template[t0:t1, t0:t1].sum()),
            "clipping": template_clip,
            "raster": "row 0 of the PNG is the north (+y) edge; columns increase towards the west (+x)",
        },
        "references": galaxy_export.REFERENCES,
        "reference_note": galaxy_export.REFERENCE_NOTE,
        "data_references": galaxy_export.DATA_REFERENCES,
        "visual_reference": galaxy_export.VISUAL_REFERENCE,
    }
    galaxy_scene_entry = galaxy_bundle.write_json("scene/galaxy-scene.json", galaxy_scene_export, role="galaxy_scene")

    derived_dir.mkdir(parents=True)
    galaxy_out.mkdir(parents=True)
    binary_arrays: Dict[str, np.ndarray] = {}
    case_entries: Dict[str, Dict[str, Any]] = {}
    summaries: Dict[str, Any] = {}
    galaxy_case_refs: Dict[str, Any] = {}
    galaxy_case_records: Dict[str, Any] = {}
    flux_summary: Dict[str, Any] = {}
    baseline_digests = cases["baseline"]["record"]["observer"]["frames"]["atmosphere_sha256"]
    timings: Dict[str, float] = {}
    for case_id in long_series.CASE_ORDER:
        case_started = time.perf_counter()
        case = cases[case_id]
        record = case["record"]
        protocol_case = protocol.case_by_id(case_id)
        plan_entry = long_series.plan_case(plan, case_id)
        means = load_means(case)
        check_parent(case_id, case, means, grid)
        history = load_history(case)
        prefix = f"cases/{case_id}"
        defining = f"{prefix}/case.json"
        images: Dict[str, Any] = {}
        clip_tables: Dict[str, Any] = {}
        for kind, name, label in MAP_KINDS:
            stack = load_stack(case, name)
            mask = np.isfinite(stack[0])
            tiles, clips, pistons = [], [], []
            for frame in indices:
                values, piston = render.display_map(stack[frame], mask)
                codes, clip = opd_codes(values, mask, limits["limit_m"])
                tiles.append(np.ascontiguousarray(codes[::-1]))
                clips.append(clip)
                pistons.append(piston * 1e9)
            canvas, rectangles = code_atlas(tiles, fill=OPD_EXTERIOR_INDEX)
            entry = bundle.write(f"{prefix}/atlas-{kind}.png", palette_png(canvas, opd_palette, transparent_index=OPD_EXTERIOR_INDEX), media_type="image/png", role="display_atlas", user=case_id, share=True)
            images[kind] = {
                "label": label,
                "source": f"frames/{name}.npy (case {case_id}, {case['attempt'].name})",
                "unit": IMAGE_UNITS[kind],
                "atlas": ref(entry, defining),
                "encoding": f"8-bit indexed PNG; palette index = display code 0..{OPD_CODES - 1}; index {OPD_EXTERIOR_INDEX} = pupil exterior (transparent)",
                "tile_px": [int(mask.shape[1]), int(mask.shape[0])],
                "rectangles_xywh": rectangles,
                "frame_indices": indices,
                "color_limits_nm": [-limits["limit_m"] * 1e9, limits["limit_m"] * 1e9],
                "colormap": render.OPD_CMAP,
                "mask": "pupil exterior transparent (not zero OPD)",
                "piston": "the pupil mean (piston) of each displayed map is removed for display only; the removed value per displayed frame is display_piston_nm. A Shack-Hartmann sensor does not sense piston, piston does not change the image, and every RMS on this site is piston-removed. Raw maps keep their piston in the archives.",
                "display_piston_nm": pistons,
                "axes": "x right, +y up (raster rows flipped once at encoding); pupil coordinates -1..1 m",
                "extent_m": [-1.0, 1.0, -1.0, 1.0],
                "resampling": "none (one pupil sample per tile pixel)",
            }
            clip_tables[kind] = clips
            del stack
        for kind, name, label in PSF_KINDS:
            stack = load_stack(case, name)
            tiles, clips = [], []
            for frame in indices:
                codes, clip = render.psf_codes(np.asarray(stack[frame])[y0:y1, x0:x1], ideal_peak)
                tiles.append(np.ascontiguousarray(codes[::-1]))
                clips.append(clip)
            canvas, rectangles = code_atlas(tiles)
            entry = bundle.write(f"{prefix}/atlas-psf-{kind}.png", palette_png(canvas, psf_palette), media_type="image/png", role="display_atlas", user=case_id, share=True)
            images[f"psf_{kind}"] = {
                "label": label,
                "source": f"frames/{name}.npy (case {case_id}, {case['attempt'].name})",
                "unit": "log10 relative intensity",
                "atlas": ref(entry, defining),
                "encoding": "8-bit indexed PNG; palette index = display code",
                "tile_px": [x1 - x0, y1 - y0],
                "rectangles_xywh": rectangles,
                "frame_indices": indices,
                "scale": psf_scale,
                "window": psf_window,
                "axes": "x right, +y up (raster rows flipped once at encoding)",
                "zero_angle_cell_in_tile_column_row": [render.PSF_DISPLAY_HALF_WIDTH_CELLS, render.PSF_DISPLAY_HALF_WIDTH_CELLS - 1],
            }
            clip_tables[f"psf_{kind}"] = clips
            del stack
        for role in ROLES:
            codes, clip = render.psf_codes(means[f"mean_psf_{role}"][y0:y1, x0:x1], ideal_peak)
            entry = bundle.write(f"{prefix}/psf-average-{role}.png", palette_png(render.raster(codes), psf_palette), media_type="image/png", role="display_average", user=case_id, share=True)
            images[f"psf_average_{role}"] = {
                "label": f"Average of frames {START}-{N_STEPS - 1}, {'AO-corrected' if role == 'corrected' else 'uncorrected reference'}",
                "source": f"mean_psfs.npz:mean_psf_{role} (case {case_id}); equal weights over frames [{START}, {N_STEPS})",
                "image": ref(entry, defining),
                "scale": psf_scale,
                "window": psf_window,
                "clipping": clip,
                "window_frames": [START, N_STEPS],
                "sample_count": COUNT,
            }

        metrics = metrics_payload(case_id, case, history)
        metrics["display_clipping"] = clip_tables
        metrics["display_indices"] = indices
        metrics_entry = bundle.write_json(f"{prefix}/metrics.json", metrics, role="metrics")
        csv_entry = bundle.write(f"{prefix}/metrics.csv", render.metrics_csv(metrics["per_frame"]), media_type="text/csv", role="metrics_csv")
        config = producer.job_config(plan_entry)
        config_entry = bundle.write_json(f"{prefix}/config.json", {
            "schema": "ao-explorer.config.v2",
            "case_id": case_id,
            "base_profile": f"{protocol.PROFILE_NAME}@{protocol.PROFILE_VERSION}",
            "frame_contract": plan["frame_contract"],
            "screen": plan["screen"],
            "case_override": protocol_case["override"],
            "root_seed": plan_entry["root_seed"],
            "realization_index": long_series.REALIZATION_INDEX,
            "effective_config_hash": record["config_hash"],
            "effective_parameters": plan_entry["effective_parameters"],
            "original_binding": plan_entry["original_binding"],
            "effective_configuration": producer.to_jsonable(config),
        }, role="config")

        digests = record["observer"]["frames"]["atmosphere_sha256"]
        same = sum(1 for a, b in zip(digests, baseline_digests) if a == b)
        if case_id == "baseline":
            pairing = {"status": "reference", "matching_frames": same, "frames": N_STEPS}
        elif same == N_STEPS:
            pairing = {"status": "paired", "matching_frames": same, "frames": N_STEPS, "note": f"all {N_STEPS} atmosphere samples are byte-identical to the baseline's (streamed SHA-256 per frame)"}
        else:
            pairing = {"status": "different_atmosphere", "matching_frames": same, "frames": N_STEPS, "note": "the atmosphere samples differ from the baseline's; r0 changes change the physical phase strength by construction, so differences are not a paired effect size"}

        # Binary scene through the two 800-frame means.
        binary_roles = {}
        for role in ROLES:
            result = binary_scene.observe(scene_bundle, means[f"mean_psf_{role}"], x_axis, y_axis)
            image = result.pop("image")
            binary_arrays[f"{case_id}__{role}"] = image
            codes, clip = render.psf_codes(image, ideal_peak)
            entry = bundle.write(f"{prefix}/observation-{role}.png", palette_png(render.raster(codes), psf_palette), media_type="image/png", role="observation", user=case_id, share=True)
            binary_roles[role] = {
                "parent": parent_record(case_id, case, means, role),
                **result,
                "display": {"image": ref(entry, f"{prefix}/observation.json"), "scale": psf_scale, "clipping": clip, "extent_mas": psf_window["native_extent_mas"]},
            }
        observation_entry = bundle.write_json(f"{prefix}/observation.json", {
            "schema": "ao-explorer.observation.v2",
            "case_id": case_id,
            "label": f"Synthetic binary observation -- average of frames {START}-{N_STEPS - 1}; relative flux per numerical cell; no additional science-camera noise",
            "scene_id": scene_bundle["record"]["scene_id"],
            "scene_grid_id": scene_bundle["record"]["grid_id"],
            "scene": ref(scene_entry, f"{prefix}/observation.json"),
            "window": [START, N_STEPS],
            "sample_count": COUNT,
            "weights": "equal",
            "renderer_revision": binary_scene.RENDERER_REVISION,
            "policy": binary_scene.CONVOLUTION_POLICY,
            "derived_arrays": {"file": "binary_observations.npz", "location": f"outputs/ao_explorer_1s_derived/{dataset_id}/ (outside the site and Git)"},
            "roles": binary_roles,
            "limitations": [
                "WFS detector noise is on and affects the AO residual; no science-camera noise, counts, SNR, limiting magnitude or detection significance is modelled.",
                "One spatially invariant on-axis PSF is assumed across the compact scene; no off-axis, isoplanatic or sky-coverage validation is implied.",
                f"Frame-start snapshot average ({COUNT} x 1 ms nominal quadrature, timestamp span 0.799 s), not a finite-shutter exposure.",
                "The highest pixel of a binary image is not a Strehl ratio; Strehl stays a PSF metric.",
                "The guide-source magnitude is a WFS input; the scene's relative flux is the same in every case.",
            ],
        }, role="observation")

        # NGC 1705: every instantaneous pair (streamed to disk) and the two means.
        galaxy_case_dir = galaxy_out / case_id
        galaxy_case_dir.mkdir()
        sampled_roles: Dict[str, Any] = {}
        mean_roles: Dict[str, Any] = {}
        accounting_arrays: Dict[str, np.ndarray] = {}
        galaxy_defining = f"{prefix}/galaxy.json"
        worst = 0.0
        for role in ROLES:
            stack = load_stack(case, f"psf_{role}")
            writer = long_series.NpyStreamWriter(galaxy_case_dir / f"sampled_{role}.npy", (N_STEPS, *grid["shape_yx"]))
            accounting = {key: np.empty(N_STEPS) for key in ("kernel_flux", "full_flux", "full_flux_error", "window_fraction", "display_window_fraction", "min_value")}
            tiles = []
            above = 0.0
            for frame in range(N_STEPS):
                image, flux = convolver.observe(np.asarray(stack[frame]))
                writer.write(frame, image)
                for key in ("kernel_flux", "full_flux", "full_flux_error", "window_fraction", "min_value"):
                    accounting[key][frame] = flux[key]
                accounting["display_window_fraction"][frame] = float(image[d0:d1, d0:d1].sum()) / flux["full_flux"]
                worst = max(worst, abs(flux["full_flux_error"]))
                if frame in positions:
                    codes, clip = galaxy_export.display_codes(image[d0:d1, d0:d1], reference)
                    above = max(above, clip["above_display_max_fraction"])
                    tiles.append(galaxy_export.raster(codes))
            stack_record = writer.close()
            kernel_sha = _stack_sha(stack)
            del stack
            for key, values in accounting.items():
                accounting_arrays[f"{role}__{key}"] = values
            canvas, rectangles = code_atlas(tiles)
            atlas_entry = galaxy_bundle.write(f"{prefix}/galaxy-sampled-{role}.png", galaxy_export.png_bytes(canvas, galaxy_palette), media_type="image/png", role=f"galaxy_sampled_{role}", user=case_id, share=True)
            sampled_roles[role] = {
                "kernel": f"frames/psf_{role}.npy[k] (field {FIELDS[role]})",
                "kernel_stack_sha256": kernel_sha,
                "kernel_file_sha256": case["files"][f"frames/psf_{role}.npy"]["sha256"],
                "atlas": ref(atlas_entry, galaxy_defining),
                "rectangles_xywh": rectangles,
                "observations_file": {"file": f"{case_id}/sampled_{role}.npy", **stack_record},
                "flux": {
                    "template_flux": convolver.template_flux,
                    "displayed": {key: [float(accounting[key][k]) for k in indices] for key in ("kernel_flux", "full_flux", "full_flux_error", "window_fraction", "display_window_fraction", "min_value")},
                    "all_frames": {
                        "count": N_STEPS,
                        "max_abs_full_flux_error": float(np.max(np.abs(accounting["full_flux_error"]))),
                        "window_fraction_range": [float(accounting["window_fraction"].min()), float(accounting["window_fraction"].max())],
                        "display_window_fraction_range": [float(accounting["display_window_fraction"].min()), float(accounting["display_window_fraction"].max())],
                    },
                },
                "clipping": {"max_above_display_max_fraction_displayed": above},
            }
            kernel = means[f"mean_psf_{role}"]
            image, flux = convolver.observe(kernel)
            worst = max(worst, abs(flux["full_flux_error"]))
            accounting_arrays[f"mean_{role}"] = image
            codes, clip = galaxy_export.display_codes(image[d0:d1, d0:d1], reference)
            mean_entry = galaxy_bundle.write(f"{prefix}/galaxy-mean-{role}.png", galaxy_export.png_bytes(galaxy_export.raster(codes), galaxy_palette), media_type="image/png", role=f"galaxy_mean_{role}", user=case_id, share=True)
            mean_roles[role] = {
                "kernel": f"mean_psfs.npz mean_psf_{role} (field {FIELDS[role]}; equal-weight mean of frames {START}-{N_STEPS - 1})",
                "kernel_array_sha256": _array_sha(kernel),
                "kernel_matches_binary_observation_parent": _array_sha(kernel) == binary_roles[role]["parent"]["array_sha256"],
                "image": ref(mean_entry, galaxy_defining),
                "image_array_sha256": _array_sha(image),
                "flux": {"template_flux": convolver.template_flux, **flux, "display_window_fraction": float(image[d0:d1, d0:d1].sum()) / flux["full_flux"]},
                "clipping": clip,
            }
        _require(worst <= 1e-12, f"{case_id}: convolution flux differs from template x kernel flux by {worst:.3e}")
        np.savez(galaxy_case_dir / FLUX_FILE, **accounting_arrays)
        flux_file = flux_file_record(galaxy_id, case_id, galaxy_case_dir / FLUX_FILE)
        for role in ROLES:
            sampled_roles[role]["flux"]["all_frames"].update(flux_file)
        galaxy_case = {
            "schema": GALAXY_OBSERVATION_SCHEMA,
            "case_id": case_id,
            "label": f"{protocol_case['label']}: observed NGC 1705 F814W template through the simulated 1.65 µm PSFs; relative flux per numerical cell, no added noise",
            "scene_id": template_record["scene_id"],
            "kernel_grid_id": template_record["target"]["kernel_grid_id"],
            "scene": ref(galaxy_scene_entry, galaxy_defining),
            "renderer_revision": galaxy_scene.RENDERER_REVISION,
            "policy": convolver.policy(),
            "response": "I_k = T (*) P_k with T ~ R (*) (O * H_HST + n_HST): the output keeps Hubble's effective response and noise, the cell response R once, and adds the simulated PSF P_k",
            "parents": {
                "series_id": plan["series_id"],
                "plan_sha256": plan_sha,
                "case_id": case_id,
                "attempt": case["attempt"].name,
                "case_record_sha256": case["record_sha256"],
                "files": {name: case["files"][name] for name in ("frames/psf_uncorrected.npy", "frames/psf_corrected.npy", "mean_psfs.npz")},
                "location": f"outputs/ao_explorer_1s/{plan['series_id']}/cases/{case_id}/{case['attempt'].name}/ (read-only, not in the web bundle)",
                "binding": "kernel files re-hashed against the case record; mean kernels equal the binary observation's parent arrays",
            },
            "sampled": {
                "count": len(indices),
                "frame_indices": indices,
                "time_s": display_times,
                "retained_observations": N_STEPS,
                "burn_in_frames": START,
                "frame_period_s": FRAME_PERIOD_S,
                "sampling": f"all {N_STEPS} instantaneous PSF pairs are convolved and kept at full precision; the page shows the displayed subset ({DISPLAY_RULE})",
                "roles": sampled_roles,
            },
            "mean": {
                "window": [START, N_STEPS],
                "sample_count": COUNT,
                "weights": "equal",
                "kernels": f"the complete {COUNT}-frame means (mean_psf_*, frames {START}-{N_STEPS - 1}), not an average of the displayed samples",
                "linearity": f"for the fixed template, T (*) mean PSF equals the mean of the {COUNT} per-frame observations under the linear imaging model; the display stretch is applied afterwards",
                "roles": mean_roles,
            },
            "display": {"scale_revision": GALAXY_DISPLAY_REVISION, "window": galaxy_window, "raster": "PNG row 0 is the north (+y) edge; columns increase towards the west (+x)"},
            "derived_arrays": {"location": f"outputs/ao_explorer_galaxy/{galaxy_id}/{case_id}/ (full-precision native-window arrays; outside the site and Git)"},
            "code_identity": {"sha256": code["sha256"], "files": code["files"]},
        }
        galaxy_entry = galaxy_bundle.write_json(galaxy_defining, galaxy_case, role="galaxy_observation")
        galaxy_case_refs[case_id] = {"label": protocol_case["label"], "galaxy": ref(galaxy_entry, "manifest.json")}
        galaxy_case_records[case_id] = galaxy_case
        flux_summary[case_id] = {
            role: {
                "sampled_window_fraction_range": sampled_roles[role]["flux"]["all_frames"]["window_fraction_range"],
                "mean_window_fraction": mean_roles[role]["flux"]["window_fraction"],
                "max_abs_full_flux_error": max(sampled_roles[role]["flux"]["all_frames"]["max_abs_full_flux_error"], abs(mean_roles[role]["flux"]["full_flux_error"])),
            }
            for role in ROLES
        }

        provenance_entry = bundle.write_json(f"{prefix}/provenance.json", {
            "schema": "ao-explorer.provenance.v2",
            "case_id": case_id,
            "series_id": plan["series_id"],
            "plan_sha256": plan_sha,
            "attempt": case["attempt"].name,
            "production_identity": plan["identities"]["production"],
            "runtime_source": plan["identities"]["core"],
            "environment": plan["identities"]["environment"],
            "host": plan["identities"]["host"],
            "screen": record["screen"],
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
                "export_s": record["export_s"],
                "child_wall_s": record["child_wall_s"],
                "child_peak_rss_bytes": record["child_peak_rss_bytes"],
            },
            "raw_evidence": {
                "location": f"outputs/ao_explorer_1s/{plan['series_id']}/cases/{case_id}/{case['attempt'].name}/ (not in the web bundle)",
                "files": case["files"],
                "case_record_sha256": case["record_sha256"],
            },
            "derived_export": {"export_code_identity": code, "display_revision": DISPLAY_REVISION, "dataset_id": dataset_id, "galaxy_derived_id": galaxy_id},
            "atmosphere_pairing": pairing,
            "atmosphere_repetition": {"unique_frame_digests": len(set(digests)), "frames": len(digests), "repeated": len(set(digests)) != len(digests)},
            "checks": record["observer"]["checks"],
        }, role="provenance")
        case_entry = bundle.write_json(defining, {
            "schema": "ao-explorer.case.v2",
            "case_id": case_id,
            "label": protocol_case["label"],
            "group": protocol_case["group"],
            "question": protocol_case["question"],
            "override": protocol_case["override"],
            "effective_parameters": plan_entry["effective_parameters"],
            "time_domain": {**time_domain, "movie_indices": indices, "movie_times_s": display_times},
            "images": images,
            "members": {
                "metrics": ref(metrics_entry, defining),
                "metrics_csv": ref(csv_entry, defining),
                "config": ref(config_entry, defining),
                "provenance": ref(provenance_entry, defining),
                "observation": ref(observation_entry, defining),
            },
            "pairing": pairing,
            "validation": case_validation(record),
            "limitations": [
                f"Single-realization synthetic SCAO demonstration (one seed, {N_STEPS} frames = 1.000 s); no ensemble uncertainty is shown.",
                "Science samples are frame-start snapshots; averages are equal-weight means of sampled instantaneous images.",
                "Recorded nodes only: no interpolation between cases and no unlisted parameter combination.",
                "The uncorrected image is a zero-DM optical counterfactual of the same recorded atmosphere, not a separate sensor/control trajectory.",
                f"The page shows {len(indices)} of the {N_STEPS} recorded frames ({DISPLAY_RULE}); curves and summaries use all frames.",
            ],
        }, role="case")
        case_entries[case_id] = case_entry
        summaries[case_id] = metrics["summary"]
        timings[case_id] = time.perf_counter() - case_started
        print(json.dumps({"exported_case": case_id, "s": round(timings[case_id], 1)}), flush=True)

    np.savez(derived_dir / "binary_observations.npz", scene=scene_bundle["scene"], **binary_arrays)
    producer.write_json(derived_dir / "block_summaries.json", blocks)
    diagnostics_entry = bundle.write_json("diagnostics.json", {
        "schema": "ao-explorer.diagnostics.v2",
        "passivity": {
            "status": "not_run_for_this_dataset",
            "note": "No observer-disabled control trajectory was run for the 1000-frame dataset (outside its scope). The same ExplorerObserver class was shown passive in the historical 180-frame series; that is evidence about the observer, not a check of this dataset.",
            "historical": {"dataset_id": previous_manifest["dataset_id"], "series_id": previous_manifest["series"]["series_id"], "diagnostics": ref(previous_members["diagnostics.json"], "diagnostics.json") | {"href": f"../{previous_dir.name}/diagnostics.json"}},
        },
        "seed2_sensitivity": {
            "status": "not_run_for_this_dataset",
            "note": "No seed-sensitivity trajectory was run for the 1000-frame dataset (outside its scope). The historical 180-frame seed-2 check belongs to the previous dataset and its 156 x 156 screen.",
        },
    }, role="diagnostics")
    research_ref = {
        "href": f"../{previous_dir.name}/research/results.json",
        "bytes": research_item["bytes"],
        "sha256": research_item["sha256"],
        "media_type": research_item["media_type"],
    }
    manifest = {
        "schema": MANIFEST_SCHEMA,
        "web_schema_version": WEB_SCHEMA_VERSION,
        "dataset_id": dataset_id,
        "title": "AO Simulation Explorer",
        "experiment_title": "2 m Interactive AO Experiment",
        "default_case": protocol.DEFAULT_CASE,
        "groups": protocol.GROUPS,
        "cases": {
            case_id: {"label": protocol.case_by_id(case_id)["label"], "group": protocol.case_by_id(case_id)["group"], "case": ref(case_entries[case_id], "manifest.json")}
            for case_id in long_series.CASE_ORDER
        },
        "scene": ref(scene_entry, "manifest.json"),
        "display": ref(display_entry, "manifest.json"),
        "diagnostics": ref(diagnostics_entry, "manifest.json"),
        "blocks": ref(blocks_entry, "manifest.json"),
        "results": research_ref,
        "results_origin": f"the Research Results of {previous_manifest['dataset_id']}, referenced in place and byte-identical; they do not depend on either explorer trajectory",
        "summaries": summaries,
        "time_domain": time_domain,
        "playback": playback,
        "screen": plan["screen"],
        "series": {
            "series_id": plan["series_id"],
            "plan_sha256": plan_sha,
            "source_sha": plan["identities"]["core"]["git"]["git_head"],
            "source_state": "uncommitted working tree at production; the production identity binds the producer files and the core package by content",
            "production_sha256": plan["identities"]["production"]["sha256"],
        },
        "previous_dataset": {
            "dataset_id": previous_manifest["dataset_id"],
            "manifest_sha256": identity.sha256_bytes(previous_manifest_bytes),
            "relation": "preserved unchanged; its 180-frame trajectories, 140-frame means and evidence are not combined with this dataset",
        },
        "members": sorted(bundle.members.values(), key=lambda item: item["path"]),
    }
    manifest_bytes = _json_bytes(manifest)
    (bundle.base / "manifest.json").write_bytes(manifest_bytes)
    manifest_sha = identity.sha256_bytes(manifest_bytes)

    galaxy_manifest = {
        "schema": GALAXY_MANIFEST_SCHEMA,
        "derived_id": galaxy_id,
        "title": "NGC 1705 central region: observed HST/F814W template through the simulated PSFs",
        "parent": {
            "dataset_id": dataset_id,
            "manifest_sha256": manifest_sha,
            "series_id": plan["series_id"],
            "plan_sha256": plan_sha,
            "binary_scene_id": scene_bundle["record"]["scene_id"],
            "relation": "derived from the 1000-frame dataset named here; not combined with the previous 180-frame dataset",
        },
        "template_reuse": {
            "scene_id": template_record["scene_id"],
            "template_array_sha256": template_record["template_array_sha256"],
            "template_file": f"outputs/ao_explorer_galaxy/{template_set.name}/template.npz",
            "template_file_sha256": identity.sha256_file(template_path),
            "template_record": f"web/ao-explorer/derived/{template_set.name}/scene/galaxy-scene.json",
            "template_record_sha256": identity.sha256_file(template_record_path),
            "rule": "the prepared full-precision template is reused unchanged (same crop centre, angular scale factor 1.0, orientation, grid and normalization); the FITS products are not re-read",
        },
        "default_case": protocol.DEFAULT_CASE,
        "scene": ref(galaxy_scene_entry, "manifest.json"),
        "cases": galaxy_case_refs,
        "display": {"revision": GALAXY_DISPLAY_REVISION, "scale": galaxy_scale, "window": galaxy_window, "upscaling": "nearest-neighbour in the browser (image smoothing disabled); no interpolation of values", "scale_bar_arcsec": 1.0},
        "time_domain": {key: time_domain[key] for key in ("frames", "frame_period_s", "physical_interval_s", "startup_exclusion_frames", "analysis_window", "analysis_count", "display_indices", "display_times_s", "display_count", "display_rule")},
        "playback": playback,
        "flux_summary": flux_summary,
        "credit": galaxy_template.CREDIT,
        "references": galaxy_export.REFERENCES,
        "reference_note": galaxy_export.REFERENCE_NOTE,
        "data_references": galaxy_export.DATA_REFERENCES,
        "visual_reference": galaxy_export.VISUAL_REFERENCE,
        "limitations": [
            *galaxy_export.LIMITATIONS[:6],
            f"Sampled mode shows {len(indices)} of the {N_STEPS} instantaneous observations ({DISPLAY_RULE}). All {N_STEPS} are computed and kept at full precision outside the site; nothing between displayed frames is interpolated.",
            f"Mean mode uses the complete {COUNT}-frame mean PSFs (frames {START}-{N_STEPS - 1}); for the fixed template this equals the mean of the {COUNT} corresponding observations under the linear imaging model. This is an intensity average of {COUNT} frame-start PSFs from one realization over the declared {START * FRAME_PERIOD_S:.3f}-{N_STEPS * FRAME_PERIOD_S:.3f} s interval. This record alone does not establish convergence to a long-exposure PSF.",
            "Slower playback and looping change presentation only: one pass shows the recorded 1.000 s; a loop repeats the same recorded trajectory and can jump at its boundary. Nothing is interpolated.",
            galaxy_export.LIMITATIONS[9],
        ],
        "code_identity": code,
        "environment": environment(),
        "members": sorted(galaxy_bundle.members.values(), key=lambda item: item["path"]),
    }
    galaxy_manifest_bytes = _json_bytes(galaxy_manifest)
    (galaxy_web / "manifest.json").write_bytes(galaxy_manifest_bytes)
    diagnostics_block = rms_diagnostics.build(series_dir, plan, bundle.base, manifest_bytes, web_dir, Path(arguments.derived_root))
    diagnostics_web = web_dir / "derived" / diagnostics_block["derived_id"]
    diagnostics_bytes = sum(path.stat().st_size for path in diagnostics_web.rglob("*") if path.is_file())

    # Size: the active site is everything the page can load for this entry.
    code_bytes = sum((web_dir / site["code_dir"] / name).stat().st_size for name in site_build.CODE_FILES) + (web_dir / "index.html").stat().st_size
    research_bytes = sum(item["bytes"] for item in research_members)
    entry_pointer = {
        "schema": "ao-explorer.entry.v1",
        "dataset_id": dataset_id,
        "manifest": f"{dataset_id}/manifest.json",
        "manifest_bytes": len(manifest_bytes),
        "manifest_sha256": manifest_sha,
        "code_build": site["build"],
        "galaxy": {
            "schema": GALAXY_ENTRY_SCHEMA,
            "derived_id": galaxy_id,
            "manifest": f"../derived/{galaxy_id}/manifest.json",
            "manifest_bytes": len(galaxy_manifest_bytes),
            "manifest_sha256": identity.sha256_bytes(galaxy_manifest_bytes),
        },
        "diagnostics": diagnostics_block,
    }
    entry_bytes = (json.dumps(entry_pointer, indent=1) + "\n").encode("utf-8")
    dataset_bytes = bundle.total_bytes() + len(manifest_bytes)
    galaxy_bytes = galaxy_bundle.total_bytes() + len(galaxy_manifest_bytes)
    active_bytes = code_bytes + len(entry_bytes) + dataset_bytes + galaxy_bytes + research_bytes + diagnostics_bytes
    default_case = f"cases/{protocol.DEFAULT_CASE}/"
    first_view_paths = {"display.json", "scene/scene.json", "scene/scene-reference.png", "diagnostics.json", "blocks.json"}
    baseline_payload = json.loads((bundle.base / f"{default_case}case.json").read_bytes())
    first_view = code_bytes + len(entry_bytes) + len(manifest_bytes) + len(galaxy_manifest_bytes)
    first_view += sum(bundle.members[path]["bytes"] for path in first_view_paths)
    first_view += bundle.members[f"{default_case}case.json"]["bytes"]
    referenced = [baseline_payload["members"][key] for key in ("metrics", "metrics_csv", "config", "provenance", "observation")]
    referenced += [baseline_payload["images"][key]["atlas"] for key in ("atmosphere", "correction", "residual", "psf_uncorrected", "psf_corrected")]
    referenced += [baseline_payload["images"][key]["image"] for key in ("psf_average_uncorrected", "psf_average_corrected")]
    first_view += sum(item["bytes"] for item in referenced)
    baseline_observation = json.loads((bundle.base / f"{default_case}observation.json").read_bytes())
    first_view += sum(baseline_observation["roles"][role]["display"]["image"]["bytes"] for role in ROLES)
    first_view += galaxy_bundle.members["scene/galaxy-scene.json"]["bytes"] + galaxy_bundle.members["scene/template.png"]["bytes"]
    first_view += diagnostics_block["manifest_bytes"] + (diagnostics_web / "cases" / protocol.DEFAULT_CASE / "rms.json").stat().st_size
    size = {
        "budget_bytes": SITE_BUDGET_BYTES,
        "active_site_bytes": active_bytes,
        "dataset_bytes": dataset_bytes,
        "galaxy_bytes": galaxy_bytes,
        "research_bytes_referenced": research_bytes,
        "code_and_index_bytes": code_bytes,
        "rms_diagnostics_bytes": diagnostics_bytes,
        "first_view_bytes": first_view,
        "first_view_budget_bytes": FIRST_VIEW_BUDGET_BYTES,
        "first_view_definition": "page, code, entry, the dataset, galaxy and RMS-diagnostics manifests, display/scene/diagnostics/blocks, the default case's JSON (with its RMS diagnostics), atlases, averages and binary observations, and the galaxy scene; galaxy case images load only when their panel is in view",
        "displayed_frames": len(indices),
        "simulated_frames": N_STEPS,
        "shared_images": sum(1 for item in [*bundle.members.values(), *galaxy_bundle.members.values()] if len(item.get("used_by", [])) > 1),
    }
    _require(active_bytes <= SITE_BUDGET_BYTES, f"the active site would be {active_bytes} bytes, over the {SITE_BUDGET_BYTES}-byte budget; the entry is not switched")
    _require(first_view <= FIRST_VIEW_BUDGET_BYTES, f"the first view would be {first_view} bytes, over the {FIRST_VIEW_BUDGET_BYTES}-byte budget; the entry is not switched")

    export_record = {
        "schema": "ao-explorer.long-export-record.v1",
        "dataset_id": dataset_id,
        "galaxy_derived_id": galaxy_id,
        "manifest_sha256": manifest_sha,
        "galaxy_manifest_sha256": identity.sha256_bytes(galaxy_manifest_bytes),
        "series_id": plan["series_id"],
        "plan_sha256": plan_sha,
        "export_code_identity": code,
        "environment": environment(),
        "display_rule": DISPLAY_RULE,
        "display_indices": indices,
        "opd_display_limit": limits,
        "size": size,
        "case_timings_s": timings,
        "binary_observations_sha256": long_series.sha256_file_chunked(derived_dir / "binary_observations.npz"),
        "block_summaries_sha256": identity.sha256_file(derived_dir / "block_summaries.json"),
        "galaxy_outputs": f"outputs/ao_explorer_galaxy/{galaxy_id}/",
        "processing_s": time.perf_counter() - started,
        "created_utc": producer.utc_now(),
    }
    producer.write_json(derived_dir / "export_record.json", export_record)
    producer.write_json(galaxy_out / "export_record.json", {k: export_record[k] for k in ("dataset_id", "galaxy_derived_id", "manifest_sha256", "galaxy_manifest_sha256", "export_code_identity", "created_utc")} | {"flux_summary": flux_summary, "template_reuse": galaxy_manifest["template_reuse"]})
    # The switch: only now, with both bundles complete and within budget.
    (data_root / "current.json").write_bytes(entry_bytes)
    return export_record


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--series-dir", type=Path, required=True)
    parser.add_argument("--template-set", type=Path, required=True)
    parser.add_argument("--template-record", type=Path, required=True)
    parser.add_argument("--previous-dataset", type=Path, required=True)
    parser.add_argument("--web-dir", type=Path, required=True)
    parser.add_argument("--derived-root", type=Path, required=True)
    parser.add_argument("--galaxy-root", type=Path, required=True)
    arguments = parser.parse_args(argv)
    try:
        record = export(arguments)
    except (LongExportError, long_series.LongSeriesError, galaxy_scene.GalaxySceneError, binary_scene.BinarySceneError, rms_diagnostics.DiagnosticsError) as exc:
        print(json.dumps({"status": "REFUSED", "reason": str(exc)}))
        return 3
    print(json.dumps({"status": "COMPLETED", "dataset_id": record["dataset_id"], "galaxy_derived_id": record["galaxy_derived_id"], "size": record["size"], "processing_s": round(record["processing_s"], 1)}, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
