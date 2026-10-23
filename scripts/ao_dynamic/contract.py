"""Versioned contract of the dynamic (generated-experiment) AO mode, version 1.

This module is the single definition of what the computation service accepts
and what a generated run must contain.  It imports only the standard library,
so the service, the worker, the validation driver and the tests can all read
it without NumPy, and its rules are mirrored by the browser's
``generate-contract.js``.

Scope (fixed for API v1)
    Profile ``det_emccd_2m_synthetic@1`` on the native backend: 2 m aperture,
    52 pupil samples, 5 x 5 lenslets/actuators, 700 nm WFS with the synthetic
    EMCCD (noise on), ``native_frozen_flow_v2`` atmosphere (subharmonic von
    Karman spectrum, exact Fourier sub-pixel translation), 1 kHz loop, legacy
    left-point WFS exposure (one atmosphere sample per frame), science images
    at 1.65 um.  Only the parameters in :data:`PARAMETERS` may change.

Requests are validated strictly: every field is required, unknown fields are
refused, integers must be JSON integers, numbers must be finite and inside
their range.  Nothing is clamped or defaulted silently; a refused request
lists every reason.  The complete-horizon admission and the calibration are
decided later, from the actual implementation (``physics.py``).
"""

from __future__ import annotations

import hashlib
import json
import math
from typing import Any, Dict, List, Mapping, Optional, Tuple


API_VERSION = "ao-dynamic.api.v1"
INFO_SCHEMA = "ao-dynamic.info.v1"
REQUEST_SCHEMA = "ao-dynamic.request.v1"
STATUS_SCHEMA = "ao-dynamic.status.v1"
RUN_SCHEMA = "ao-dynamic.run.v1"
CHECK_SCHEMA = "ao-dynamic.check.v1"
ERROR_SCHEMA = "ao-dynamic.error.v1"

PROFILE_NAME = "det_emccd_2m_synthetic"
PROFILE_VERSION = 1
SCIENCE_WAVELENGTH_M = 1.65e-6
WFS_WAVELENGTH_M = 7.0e-7
R0_REFERENCE_WAVELENGTH_M = 5.0e-7
FRAME_RATE_HZ = 1000.0
# Wavelengths at which the browser may display OPD as phase (display only).
PHASE_DISPLAY_WAVELENGTHS_M = (SCIENCE_WAVELENGTH_M, WFS_WAVELENGTH_M)

# Profile values the defaults reproduce exactly, so the default request with
# seed 1 is the configuration of the frozen explorer's baseline case.
PROFILE_R0_M = 0.1263371938263465
PROFILE_WIND_M_PER_S = (10.0, 0.0)

# The numeric results a run carries: OPD in metres, intensities as unit-flux
# images on the native 156 x 156 propagator grid, display crops of 64 x 64
# cells about exact zero angle.
PUPIL_SHAPE = (52, 52)
PSF_SHAPE = (156, 156)
CROP_HALF_WIDTH_CELLS = 32
CROP_SHAPE = (2 * CROP_HALF_WIDTH_CELLS, 2 * CROP_HALF_WIDTH_CELLS)
MAX_TRANSPORTED_FRAMES = 200
MIN_ANALYSIS_SAMPLES = 8

# Per-frame float32 blocks of frames.bin, in order (little endian).
FRAME_BLOCKS: Tuple[Tuple[str, Tuple[int, int], str], ...] = (
    ("atmosphere_opd_m", PUPIL_SHAPE, "m OPD (NaN outside the pupil)"),
    ("held_correction_opd_m", PUPIL_SHAPE, "m OPD-equivalent (NaN outside the pupil)"),
    ("pre_update_residual_opd_m", PUPIL_SHAPE, "m OPD (NaN outside the pupil)"),
    ("psf_uncorrected", CROP_SHAPE, "relative flux per cell (unit total flux over the uncropped grid)"),
    ("psf_corrected", CROP_SHAPE, "relative flux per cell (unit total flux over the uncropped grid)"),
    ("observation_uncorrected", CROP_SHAPE, "relative flux per cell (scene total 1)"),
    ("observation_corrected", CROP_SHAPE, "relative flux per cell (scene total 1)"),
    ("running_observation_uncorrected", CROP_SHAPE, "relative flux per cell (scene total 1); NaN before burn-in"),
    ("running_observation_corrected", CROP_SHAPE, "relative flux per cell (scene total 1); NaN before burn-in"),
)
# Completed analysis-window averages (final.bin), float32.
FINAL_BLOCKS: Tuple[Tuple[str, Tuple[int, int], str], ...] = (
    ("mean_psf_uncorrected", CROP_SHAPE, "relative flux per cell (unit total flux over the uncropped grid)"),
    ("mean_psf_corrected", CROP_SHAPE, "relative flux per cell (unit total flux over the uncropped grid)"),
    ("final_observation_uncorrected", CROP_SHAPE, "relative flux per cell (scene total 1)"),
    ("final_observation_corrected", CROP_SHAPE, "relative flux per cell (scene total 1)"),
    ("scene", CROP_SHAPE, "relative flux per cell (scene total 1)"),
)
RUN_FILES = ("run.json", "frames.bin", "final.bin", "metrics.csv", "evidence.npz")

RESIDUAL_FIELD = "pre_update_residual_opd_m"
UNCORRECTED_FIELD = "atmosphere_opd_m (zero-DM optical counterfactual)"
HELD_CORRECTION_RULE = "atmosphere_opd_m - pre_update_residual_opd_m (OPD-equivalent metres, not mirror surface height)"
PSF_NORMALIZATION = "unit total flux over the complete uncropped propagator grid"
PHASE_RULE = "phase_rad = 2 * pi * OPD_m / wavelength_m"
PHASE_WRAPPING = "unwrapped: phase is linear in OPD and is never reduced modulo 2 pi"
AXIS_LAYOUT = "x_columns_y_rows"
SCENE_WEIGHTS = (2.0 / 3.0, 1.0 / 3.0)
SCENE_SECONDARY_OFFSET_X_CELLS = 6
OPD_LIMIT_QUANTUM_M = 50e-9
OPD_LIMIT_PERCENTILE = 99.5
PSF_LOG_DECADES = 4.0


# ---------------------------------------------------------------------------
# Parameters

PARAMETERS: Tuple[Dict[str, Any], ...] = (
    {
        "name": "seed",
        "label": "Realization seed",
        "kind": "integer",
        "minimum": 1,
        "maximum": 2_147_483_647,
        "default": 1,
        "unit": "",
        "class": "realization",
        "note": "Root seed of the named random streams (atmosphere, WFS noise, calibration identity). "
                "Seed 1 is the realization of the frozen explorer.",
    },
    {
        "name": "r0_m",
        "label": "Fried parameter r0 at 500 nm",
        "kind": "number",
        "minimum": 0.06,
        "maximum": 0.30,
        "default": PROFILE_R0_M,
        "unit": "m",
        "class": "atmosphere",
        "note": "Specified at r0_reference_wavelength_m. Lower bound keeps the 39.2 mm pupil sampling below "
                "half of r0 at the 700 nm WFS wavelength; the upper bound limits the initial range.",
    },
    {
        "name": "r0_reference_wavelength_m",
        "label": "r0 reference wavelength",
        "kind": "number",
        "minimum": R0_REFERENCE_WAVELENGTH_M,
        "maximum": R0_REFERENCE_WAVELENGTH_M,
        "default": R0_REFERENCE_WAVELENGTH_M,
        "unit": "m",
        "class": "atmosphere",
        "note": "Fixed at 500 nm in API v1; stated with every r0.",
    },
    {
        "name": "wind_speed_m_per_s",
        "label": "Wind speed",
        "kind": "number",
        "minimum": 0.0,
        "maximum": 30.0,
        "default": 10.0,
        "unit": "m/s",
        "class": "atmosphere",
        "note": "Frozen-flow speed. The finite screen supports a limited travel, so faster wind admits fewer frames.",
    },
    {
        "name": "wind_direction_deg",
        "label": "Wind direction",
        "kind": "integer",
        "minimum": 0,
        "maximum": 359,
        "default": 0,
        "unit": "deg",
        "class": "atmosphere",
        "note": "Direction of the flow measured counter-clockwise from +x (0 = towards +x, 90 = towards +y).",
    },
    {
        "name": "guide_ab_magnitude",
        "label": "Guide-source AB magnitude",
        "kind": "number",
        "minimum": 4.0,
        "maximum": 9.0,
        "default": 7.0,
        "unit": "AB mag",
        "class": "wfs",
        "note": "WFS photon budget (synthetic flat-f_nu source at 700 nm). Changes the WFS identity and requires "
                "a rebuilt calibration; outside about 4-9 mag the noise-free calibration finds no valid rows.",
    },
    {
        "name": "controller_gain",
        "label": "Controller gain",
        "kind": "number",
        "minimum": 0.0,
        "maximum": 1.0,
        "default": 0.2,
        "unit": "",
        "class": "controller",
        "note": "Leaky-integrator gain (leak 0.02 fixed). Unstable combinations are allowed and labelled.",
    },
    {
        "name": "queued_latency_frames",
        "label": "Queued command delay",
        "kind": "integer",
        "minimum": 0,
        "maximum": 6,
        "default": 2,
        "unit": "frames",
        "class": "controller",
        "note": "A reconstruction from frame k is released at the update of frame k + L and first seen by the WFS "
                "at frame k + L + 1.",
    },
    {
        "name": "n_frames",
        "label": "Frames",
        "kind": "integer",
        "minimum": 16,
        "maximum": 400,
        "default": 180,
        "unit": "frames (1 ms each)",
        "class": "time_grid",
        "note": "Finite run length. Every frame time must be admitted by the frozen-flow screen.",
    },
    {
        "name": "burn_in",
        "label": "Burn-in",
        "kind": "integer",
        "minimum": 0,
        "maximum": 400 - MIN_ANALYSIS_SAMPLES,
        "default": 40,
        "unit": "frames",
        "class": "analysis",
        "note": f"Frames before the analysis window; at least {MIN_ANALYSIS_SAMPLES} analysis samples must remain.",
    },
    {
        "name": "display_stride",
        "label": "Display stride",
        "kind": "integer",
        "minimum": 1,
        "maximum": 10,
        "default": 1,
        "unit": "frames",
        "class": "transport",
        "note": f"Every stride-th frame (and the last) is kept for replay, at most {MAX_TRANSPORTED_FRAMES}. "
                "Display sampling only: histories and averages use every frame.",
    },
)
PARAMETER_NAMES = tuple(spec["name"] for spec in PARAMETERS)
PHYSICAL_PARAMETER_NAMES = tuple(spec["name"] for spec in PARAMETERS if spec["class"] != "transport")
SEED_POLICIES = ("specified", "allocate")
# Parameters a same-atmosphere comparison may change; everything else equals
# the reference run.  Burn-in is held so the analysis windows coincide.
SAME_ATMOSPHERE_CHANGES = ("guide_ab_magnitude", "controller_gain", "queued_latency_frames")
ATMOSPHERE_PARAMETERS = ("seed", "r0_m", "r0_reference_wavelength_m", "wind_speed_m_per_s", "wind_direction_deg")
CALIBRATION_PARAMETERS = ("seed", "guide_ab_magnitude")

FIXED = {
    "profile": f"{PROFILE_NAME}@{PROFILE_VERSION}",
    "backend": "native",
    "telescope_diameter_m": 2.0,
    "pupil_pixels": 52,
    "lenslets_across": 5,
    "actuators_across": 5,
    "wfs_wavelength_m": WFS_WAVELENGTH_M,
    "science_wavelength_m": SCIENCE_WAVELENGTH_M,
    "atmosphere_model": "native_frozen_flow_v2",
    "outer_scale_m": 25.0,
    "frame_rate_hz": FRAME_RATE_HZ,
    "controller_leak": 0.02,
    "camera": "synthetic_emccd@1, detector noise on in the loop",
    "wfs_exposure": "legacy left point, one atmosphere sample per frame at its start",
    "calibration": "built for every run: central differences of DM actuator probes, noise-free",
    "reconstructor": "TSVD rcond=1e-08, min_valid_fraction=0.75",
    "realization_index": 0,
}


class ContractError(ValueError):
    """Raised when a request, status or run record breaks the contract."""


def parameter(name: str) -> Dict[str, Any]:
    for spec in PARAMETERS:
        if spec["name"] == name:
            return spec
    raise KeyError(name)


def default_parameters() -> Dict[str, Any]:
    return {spec["name"]: spec["default"] for spec in PARAMETERS}


def canonical_json_bytes(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _is_integer(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _is_number(value: Any) -> bool:
    return (isinstance(value, (int, float)) and not isinstance(value, bool)) and math.isfinite(float(value))


def wind_vector(speed_m_per_s: float, direction_deg: float) -> Tuple[float, float]:
    """Wind components; the four axis directions are exact (no 1e-16 residues)."""

    speed = float(speed_m_per_s)
    direction = int(direction_deg)
    exact = {0: (speed, 0.0), 90: (0.0, speed), 180: (-speed, 0.0), 270: (0.0, -speed)}
    if direction in exact:
        vx, vy = exact[direction]
        return (vx + 0.0, vy + 0.0)  # normalize -0.0
    radians = math.radians(direction)
    return (speed * math.cos(radians), speed * math.sin(radians))


def transported_indices(n_frames: int, stride: int) -> List[int]:
    """Frames kept for replay: every ``stride``-th frame from 0, plus the last frame."""

    indices = list(range(0, int(n_frames), int(stride)))
    if indices[-1] != n_frames - 1:
        indices.append(n_frames - 1)
    return indices


def validate_parameters(parameters: Any) -> List[str]:
    """Every reason a parameter set is outside the contract (empty when valid)."""

    if not isinstance(parameters, dict):
        return ["parameters must be a JSON object"]
    reasons: List[str] = []
    unknown = sorted(set(parameters) - set(PARAMETER_NAMES))
    if unknown:
        reasons.append(f"unknown parameters {unknown}; API v1 accepts only {list(PARAMETER_NAMES)}")
    for spec in PARAMETERS:
        name = spec["name"]
        if name not in parameters:
            reasons.append(f"{name} is required")
            continue
        value = parameters[name]
        if spec["kind"] == "integer":
            if not _is_integer(value):
                reasons.append(f"{name} must be an integer, got {value!r}")
                continue
        elif not _is_number(value):
            reasons.append(f"{name} must be a finite number, got {value!r}")
            continue
        if not spec["minimum"] <= value <= spec["maximum"]:
            reasons.append(
                f"{name} = {value!r} is outside the supported range [{spec['minimum']!r}, {spec['maximum']!r}] {spec['unit']}".rstrip()
            )
    if reasons:
        return reasons
    n_frames = parameters["n_frames"]
    burn_in = parameters["burn_in"]
    if burn_in > n_frames - MIN_ANALYSIS_SAMPLES:
        reasons.append(
            f"burn_in = {burn_in} leaves {n_frames - burn_in} analysis samples of {n_frames} frames; "
            f"at least {MIN_ANALYSIS_SAMPLES} are required"
        )
    kept = len(transported_indices(n_frames, parameters["display_stride"]))
    if kept > MAX_TRANSPORTED_FRAMES:
        reasons.append(
            f"display_stride = {parameters['display_stride']} keeps {kept} of {n_frames} frames for replay; "
            f"at most {MAX_TRANSPORTED_FRAMES} may be kept (choose a stride of at least "
            f"{math.ceil((n_frames - 1) / (MAX_TRANSPORTED_FRAMES - 1))})"
        )
    return reasons


def validate_request(request: Any) -> List[str]:
    if not isinstance(request, dict):
        return ["the request must be a JSON object"]
    reasons: List[str] = []
    allowed = {"schema", "api", "seed_policy", "parameters", "client_token"}
    unknown = sorted(set(request) - allowed)
    if unknown:
        reasons.append(f"unknown request fields {unknown}")
    if request.get("schema") != REQUEST_SCHEMA:
        reasons.append(f"schema must be {REQUEST_SCHEMA!r}, got {request.get('schema')!r}")
    if request.get("api") != API_VERSION:
        reasons.append(f"api must be {API_VERSION!r}, got {request.get('api')!r}")
    policy = request.get("seed_policy")
    if policy not in SEED_POLICIES:
        reasons.append(f"seed_policy must be one of {list(SEED_POLICIES)}, got {policy!r}")
    token = request.get("client_token")
    if token is not None and (not isinstance(token, str) or len(token) > 80):
        reasons.append("client_token must be a string of at most 80 characters")
    parameters = request.get("parameters")
    if policy == "allocate":
        if not isinstance(parameters, dict) or parameters.get("seed") is not None:
            reasons.append("seed_policy 'allocate' needs parameters.seed = null (the service allocates a new seed)")
        else:
            reasons.extend(validate_parameters({**parameters, "seed": 1}))
    else:
        reasons.extend(validate_parameters(parameters))
    return reasons


def effective_parameters(parameters: Mapping[str, Any]) -> Dict[str, Any]:
    """The validated parameters plus the derived wind vector, as recorded in a run."""

    record = {name: parameters[name] for name in PARAMETER_NAMES}
    for name in PARAMETER_NAMES:
        if parameter(name)["kind"] == "number":
            record[name] = float(record[name])
    vx, vy = wind_vector(record["wind_speed_m_per_s"], record["wind_direction_deg"])
    record["wind_m_per_s"] = [vx, vy]
    return record


def physical_identity(parameters: Mapping[str, Any]) -> str:
    """Digest of the physical parameters (everything except display sampling)."""

    physical = {name: parameters[name] for name in PHYSICAL_PARAMETER_NAMES}
    return sha256_bytes(canonical_json_bytes({"api": API_VERSION, "profile": FIXED["profile"], "parameters": physical}))


def comparison_class(reference: Mapping[str, Any], candidate: Mapping[str, Any]) -> Dict[str, Any]:
    """What a change between two effective parameter sets means physically (before digests)."""

    changed = sorted(name for name in PHYSICAL_PARAMETER_NAMES if reference[name] != candidate[name])
    atmosphere = [name for name in changed if name in ATMOSPHERE_PARAMETERS]
    time_grid = [name for name in changed if name in ("n_frames",)]
    calibration = [name for name in changed if name in CALIBRATION_PARAMETERS]
    if "seed" in changed:
        kind = "different_realization"
        text = "different random realization (new seed): not a paired comparison"
    elif atmosphere:
        kind = "different_physical_atmosphere"
        text = (f"different physical atmosphere ({', '.join(atmosphere)} changed; same seed and random draws): "
                "not a paired comparison")
    elif time_grid:
        kind = "different_time_grid"
        text = "different time grid (frame count changed): not a paired comparison"
    elif not changed:
        kind = "identical_configuration"
        text = "identical physical configuration (replay)"
    else:
        kind = "same_atmosphere_expected"
        text = (f"same atmosphere expected ({', '.join(changed)} changed); paired only if every atmosphere "
                "sample digest and frame time match")
    return {
        "changed": changed,
        "kind": kind,
        "text": text,
        "calibration_rebuilt_identity_expected": bool(calibration),
        "calibration_changes": calibration,
    }


def pairing_verdict(reference_run: Mapping[str, Any], candidate_run: Mapping[str, Any]) -> Dict[str, Any]:
    """Label a comparison 'paired' only from matching time grids and atmosphere digests."""

    expected = comparison_class(reference_run["effective"]["parameters"], candidate_run["effective"]["parameters"])
    ref_frames = reference_run["per_frame"]
    cand_frames = candidate_run["per_frame"]
    times_equal = ref_frames["time_s"] == cand_frames["time_s"]
    ref_digests = ref_frames["atmosphere_sha256"]
    cand_digests = cand_frames["atmosphere_sha256"]
    common = min(len(ref_digests), len(cand_digests))
    matching = sum(1 for index in range(common) if ref_digests[index] == cand_digests[index])
    paired = (
        expected["kind"] in ("same_atmosphere_expected", "identical_configuration")
        and times_equal
        and len(ref_digests) == len(cand_digests)
        and matching == len(ref_digests)
        and reference_run["effective"]["parameters"]["burn_in"] == candidate_run["effective"]["parameters"]["burn_in"]
    )
    return {
        "expected": expected,
        "time_grids_equal": times_equal,
        "frames_compared": common,
        "matching_atmosphere_samples": matching,
        "paired": paired,
        "label": "paired: same atmosphere samples and time grid" if paired else "not paired",
    }


# ---------------------------------------------------------------------------
# Run record semantics (mirrored in web/ao-explorer/code-*/generate-contract.js)


def _require(condition: bool, message: str, problems: List[str]) -> None:
    if not condition:
        problems.append(message)


def validate_run_record(run: Any, *, expected_parameters: Optional[Mapping[str, Any]] = None,
                        file_sizes: Optional[Mapping[str, int]] = None) -> List[str]:
    """Semantic problems of a run record (empty when it is a supported, coherent run).

    Digests alone never accept a run: a coherently rehashed record with other
    units, wavelengths, residual timing, windows, axes or scene is refused.
    """

    problems: List[str] = []
    if not isinstance(run, dict):
        return ["run record is not an object"]
    _require(run.get("schema") == RUN_SCHEMA, f"unsupported run schema {run.get('schema')!r}", problems)
    _require(run.get("api") == API_VERSION, f"unsupported API {run.get('api')!r}", problems)
    _require(run.get("status") == "COMPLETED", f"run status is {run.get('status')!r}, not COMPLETED", problems)
    if problems:
        return problems
    try:
        effective = run["effective"]
        params = effective["parameters"]
        problems.extend(f"recorded parameters: {reason}" for reason in validate_parameters(
            {name: params[name] for name in PARAMETER_NAMES if name in params} | {
                name: None for name in PARAMETER_NAMES if name not in params}))
        if problems:
            return problems
        _require(params["wind_m_per_s"] == list(wind_vector(params["wind_speed_m_per_s"], params["wind_direction_deg"])),
                 "wind vector does not follow from speed and direction", problems)
        _require(effective["physical_identity"] == physical_identity(params), "physical identity does not match the parameters", problems)
        _require(effective["fixed"] == FIXED, "fixed scope differs from API v1", problems)
        if expected_parameters is not None:
            for name, value in expected_parameters.items():
                if name == "seed" and value is None:
                    continue
                _require(params.get(name) == value, f"{name} is {params.get(name)!r}, not the requested {value!r}", problems)
        n = params["n_frames"]
        burn = params["burn_in"]
        stride = params["display_stride"]
        conv = run["conventions"]
        _require(conv["science_wavelength_m"] == SCIENCE_WAVELENGTH_M, f"science wavelength {conv['science_wavelength_m']!r} is not 1.65e-06 m", problems)
        _require(conv["wfs_wavelength_m"] == WFS_WAVELENGTH_M, "WFS wavelength is not 7e-07 m", problems)
        _require(conv["opd_unit"] == "m", f"OPD unit {conv['opd_unit']!r} is not metres", problems)
        _require(conv["residual_field"] == RESIDUAL_FIELD, f"residual field {conv['residual_field']!r} is not the pre-update residual", problems)
        _require(conv["uncorrected_field"] == UNCORRECTED_FIELD, "uncorrected field is not the zero-DM atmosphere", problems)
        _require(conv["held_correction"] == HELD_CORRECTION_RULE, "held-correction rule differs", problems)
        _require(conv["psf_normalization"] == PSF_NORMALIZATION, f"PSF normalization {conv['psf_normalization']!r} is not supported", problems)
        _require(conv["phase_rule"] == PHASE_RULE and conv["phase_wrapping"] == PHASE_WRAPPING, "phase convention differs", problems)
        _require(list(conv["phase_display_wavelengths_m"]) == list(PHASE_DISPLAY_WAVELENGTHS_M), "phase display wavelengths differ", problems)
        _require(conv["axis_layout"] == AXIS_LAYOUT, "axis layout differs", problems)
        _require(conv["queued_latency_frames"] == params["queued_latency_frames"]
                 and conv["wfs_visible_delay_frames"] == params["queued_latency_frames"] + 1,
                 "queued and WFS-visible delays are inconsistent", problems)
        time = run["time"]
        _require(time["frame_rate_hz"] == FRAME_RATE_HZ and time["n_frames"] == n, "time grid header differs", problems)
        _require(len(time["time_s"]) == n and all(abs(t - k / FRAME_RATE_HZ) <= 1e-12 for k, t in enumerate(time["time_s"])),
                 "frame times are not k / 1000 s", problems)
        window = run["analysis_window"]
        _require([window["start"], window["stop"], window["count"]] == [burn, n, n - burn], "analysis window is not [burn_in, n_frames)", problems)
        _require(window["samples_used"] == n - burn, "analysis window did not use every eligible frame", problems)
        per_frame = run["per_frame"]
        for key in ("frame_index", "time_s", "atmosphere_rms_m", "residual_rms_m", "peak_strehl_uncorrected",
                    "peak_strehl_corrected", "valid_measurement_fraction", "reconstruction_usable",
                    "saturation_fraction_issued", "saturation_fraction_held", "atmosphere_sha256", "running_average_peak_strehl_uncorrected",
                    "running_average_peak_strehl_corrected"):
            _require(isinstance(per_frame.get(key), list) and len(per_frame[key]) == n, f"per-frame {key} does not cover {n} frames", problems)
        if problems:
            return problems
        _require(per_frame["frame_index"] == list(range(n)), "per-frame indices are not 0..n-1", problems)
        _require(per_frame["time_s"] == time["time_s"], "per-frame times differ from the time grid", problems)
        for key in ("running_average_peak_strehl_uncorrected", "running_average_peak_strehl_corrected"):
            values = per_frame[key]
            _require(all(v is None for v in values[:burn]) and all(isinstance(v, (int, float)) for v in values[burn:]),
                     f"{key} must be unavailable before burn-in and present after it", problems)
        _require(per_frame["saturation_fraction_held"] == [None] + per_frame["saturation_fraction_issued"][:-1],
                 "held saturation is not the previous frame's issued command", problems)
        transported = run["transported"]
        indices = transported_indices(n, stride)
        _require(transported["indices"] == indices, "transported frames do not follow the display stride", problems)
        _require(transported["time_s"] == [time["time_s"][k] for k in indices], "transported times differ from the time grid", problems)
        expected_counts = [max(0, k - burn + 1) for k in indices]
        _require(transported["running_sample_count"] == expected_counts, "running averages do not count every eligible frame", problems)
        arrays = run["arrays"]
        frames = arrays["frames"]
        _require(frames["dtype"] == "<f4" and [b["name"] for b in frames["blocks"]] == [b[0] for b in FRAME_BLOCKS],
                 "frames.bin layout differs", problems)
        _require(all(list(b["shape"]) == list(spec[1]) and b["unit"] == spec[2] for b, spec in zip(frames["blocks"], FRAME_BLOCKS)),
                 "frames.bin block shapes or units differ", problems)
        per_frame_floats = sum(spec[1][0] * spec[1][1] for spec in FRAME_BLOCKS)
        _require(frames["bytes"] == 4 * per_frame_floats * len(indices), "frames.bin size does not match the transported frames", problems)
        final = arrays["final"]
        _require([b["name"] for b in final["blocks"]] == [b[0] for b in FINAL_BLOCKS]
                 and final["bytes"] == 4 * sum(s[1][0] * s[1][1] for s in FINAL_BLOCKS), "final.bin layout differs", problems)
        if file_sizes is not None:
            for name in ("frames", "final"):
                file_name = arrays[name]["href"]
                _require(file_sizes.get(file_name) == arrays[name]["bytes"], f"{file_name} size differs from the record", problems)
        scene = run["scene"]
        weights = [source["weight"] for source in scene["sources"]]
        _require(weights == list(SCENE_WEIGHTS) and scene["separation_native_x_cells"] == SCENE_SECONDARY_OFFSET_X_CELLS
                 and scene["wavelength_m"] == SCIENCE_WAVELENGTH_M, "scene differs from the fixed binary", problems)
        grid = run["grids"]["psf"]
        _require(list(grid["shape_yx"]) == list(PSF_SHAPE) and list(grid["crop_shape_yx"]) == list(CROP_SHAPE), "PSF grid or crop differs", problems)
        _require(grid["x_angle_rad_sha256"] == scene["grid"]["x_angle_rad_sha256"] and grid["y_angle_rad_sha256"] == scene["grid"]["y_angle_rad_sha256"],
                 "scene grid differs from the PSF grid", problems)
        display = run["display"]
        _require(display["psf_log_decades"] == PSF_LOG_DECADES and display["opd_limit_m"] > 0, "display mapping differs", problems)
        _require(len(display["piston_removed_m"]["atmosphere"]) == len(indices) and len(display["clipped_fraction"]["residual"]) == len(indices),
                 "display piston/clipping records do not cover the transported frames", problems)
        final_avg = run["final_average"]
        _require(final_avg["sample_count"] == n - burn and final_avg["window"] == [burn, n], "final average is not the completed window", problems)
        checks = run["checks"]
        _require(checks.get("all_passed") is True, "the run's own numerical checks did not all pass", problems)
    except (KeyError, TypeError, IndexError) as exc:
        problems.append(f"run record is incomplete: missing or malformed {exc}")
    return problems


def validate_status(status: Any) -> List[str]:
    problems: List[str] = []
    if not isinstance(status, dict):
        return ["status is not an object"]
    _require(status.get("schema") == STATUS_SCHEMA, f"unsupported status schema {status.get('schema')!r}", problems)
    _require(status.get("api") == API_VERSION, "unsupported API", problems)
    _require(status.get("state") in JOB_STATES, f"unknown job state {status.get('state')!r}", problems)
    return problems


JOB_STATES = ("queued", "running", "completed", "cancelled", "failed")
TERMINAL_STATES = ("completed", "cancelled", "failed")


def info_parameters() -> List[Dict[str, Any]]:
    return [dict(spec) for spec in PARAMETERS]


def bounds_table() -> List[Dict[str, Any]]:
    """Human-readable table of supported values (documentation and /info)."""

    return [
        {key: spec[key] for key in ("name", "label", "kind", "minimum", "maximum", "default", "unit", "class", "note")}
        for spec in PARAMETERS
    ]
