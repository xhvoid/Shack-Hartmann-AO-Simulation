"""Frozen protocol of the AO Simulation Explorer's 2 m dataset (version 1).

Everything a reviewer needs to recompute the series plan lives here: the
canonical profile, the explorer overrides, the eight production cases, the
pilot and the two diagnostic controls, the movie indices, the synthetic
binary scene and the numerical tolerances.  These values were frozen before
any production trajectory was generated; changing one makes a new series.

The module imports only the standard library so the plan, the validator and
the tests can read it without NumPy.
"""

from __future__ import annotations

from typing import Any, Dict, List, Tuple


PROTOCOL_VERSION = "ao-explorer.protocol.v1"
SERIES_PLAN_SCHEMA = "ao-explorer.series-plan.v1"
JOB_RECORD_SCHEMA = "ao-explorer.job-record.v1"
ADMISSION_SCHEMA = "ao-explorer.horizon-admission.v1"

PROFILE_NAME = "det_emccd_2m_synthetic"
PROFILE_VERSION = 1

# Explorer overrides common to every production case (PLAN section 4).
PRODUCTION_FRAMES = 180
PRODUCTION_BURN_IN = 40
ROOT_SEED = 1
REALIZATION_INDEX = 0
SCIENCE_WAVELENGTH_M = 1.65e-6
MOVIE_FRAME_COUNT = 40

# Pilot (PLAN section 4, "Pilot and resource boundary").
PILOT_FRAMES = 64
PILOT_BURN_IN = 16
PILOT_DISPLAY_INDICES: Tuple[int, ...] = (0, 8, 16, 24, 32, 40, 48, 63)

# Diagnostic controls.
SENSITIVITY_SEED = 2

# Task ceilings (assignment, "Complete-horizon admission, pilot and ceilings").
WALL_TIME_CEILING_S = 20.0 * 60.0
RAW_EVIDENCE_CEILING_BYTES = 512 * 1024 * 1024
NATIVE_THREADS = 2
# Per-child supervision limit: the policy default for new scientific examples.
CHILD_TIMEOUT_S = 120.0

# Synthetic binary scene (PLAN section 5): primary at angular zero, secondary
# six native x cells towards +x, relative weights 2/3 and 1/3.
SCENE_SCHEMA = "ao-explorer.scene.v1"
SCENE_SECONDARY_OFFSET_X_CELLS = 6
SCENE_SECONDARY_OFFSET_Y_CELLS = 0
SCENE_WEIGHTS = (2.0 / 3.0, 1.0 / 3.0)

# Numerical tolerances, frozen before production.  Each is matched to the
# computation it guards (double-precision reductions of O(1e-7) m maps and of
# unit-flux images); none is widened after seeing a comparison.
TOLERANCES: Dict[str, Dict[str, float]] = {
    # Independent pupil RMS (NumPy, piston removed) against the loop history.
    "rms_m": {"rtol": 1.0e-12, "atol": 1.0e-18},
    # Independent peak Strehl (max ratio) against the production function.
    "strehl": {"rtol": 0.0, "atol": 1.0e-12},
    # Streamed accumulator mean against an offline mean of the same images.
    "mean_psf": {"rtol": 0.0, "atol": 1.0e-15},
    # Unit-flux checks of instantaneous and mean images.
    "unit_flux": {"rtol": 0.0, "atol": 1.0e-12},
    # Binary-observation oracles and flux bookkeeping.
    "convolution": {"rtol": 0.0, "atol": 1.0e-15},
    "convolution_flux": {"rtol": 0.0, "atol": 1.0e-12},
    # Display mapping: decoded 8-bit atlas pixel against the declared mapping.
    "display_code": {"rtol": 0.0, "atol": 0.0},
}


def movie_indices(n_frames: int = PRODUCTION_FRAMES, count: int = MOVIE_FRAME_COUNT,
                  burn_in: int = PRODUCTION_BURN_IN) -> Tuple[int, ...]:
    """Deterministic, ordered, unique movie indices including 0, burn-in and last.

    Rule: round ``count`` evenly spaced points over ``[0, n_frames - 1]`` to the
    nearest integer (ties to even), then move the point nearest the burn-in
    boundary onto it.  The rule is pure integer/float arithmetic so the
    validator can recompute it without NumPy.
    """

    if count < 3 or n_frames < count:
        raise ValueError("movie needs at least three frames and no more than n_frames.")
    last = n_frames - 1
    points = [round(index * last / (count - 1)) for index in range(count)]
    nearest = min(range(count), key=lambda index: (abs(points[index] - burn_in), index))
    points[nearest] = burn_in
    if sorted(set(points)) != points or len(points) != count:
        raise ValueError("movie index rule did not produce unique ordered indices.")
    if points[0] != 0 or points[-1] != last or burn_in not in points:
        raise ValueError("movie indices must include the first, burn-in and last frames.")
    return tuple(points)


# The eight production cases (assignment "Frozen scientific scope").  Each
# override is applied to the effective baseline in addition to the common
# explorer overrides; nothing else changes.
CASES: List[Dict[str, Any]] = [
    {
        "id": "baseline",
        "group": None,
        "label": "Baseline",
        "question": "What does this AO loop do?",
        "override": {},
    },
    {
        "id": "weaker-turbulence",
        "group": "atmosphere",
        "label": "Weaker turbulence",
        "question": "What changes in weaker turbulence?",
        "override": {"r0_scale": 1.25},
    },
    {
        "id": "stronger-turbulence",
        "group": "atmosphere",
        "label": "Stronger turbulence",
        "question": "What changes in stronger turbulence?",
        "override": {"r0_scale": 0.80},
    },
    {
        "id": "brighter-guide",
        "group": "guide",
        "label": "Brighter guide source",
        "question": "What changes with more guide-star photons?",
        "override": {"ab_magnitude": 6.0},
    },
    {
        "id": "fainter-guide",
        "group": "guide",
        "label": "Fainter guide source",
        "question": "What changes with fewer guide-star photons?",
        "override": {"ab_magnitude": 8.0},
    },
    {
        "id": "lower-gain",
        "group": "gain",
        "label": "Lower gain",
        "question": "What changes when correction is less aggressive?",
        "override": {"gain": 0.10},
    },
    {
        "id": "higher-gain",
        "group": "gain",
        "label": "Higher gain",
        "question": "What changes when correction is more aggressive?",
        "override": {"gain": 0.30},
    },
    {
        "id": "longer-delay",
        "group": "delay",
        "label": "Longer queued delay",
        "question": "What changes with extra command delay?",
        "override": {"latency_frames": 4},
    },
]

GROUPS: List[Dict[str, Any]] = [
    {"id": "atmosphere", "label": "Atmosphere", "nodes": ["stronger-turbulence", "baseline", "weaker-turbulence"]},
    {"id": "guide", "label": "Guide brightness", "nodes": ["fainter-guide", "baseline", "brighter-guide"]},
    {"id": "gain", "label": "Gain", "nodes": ["lower-gain", "baseline", "higher-gain"]},
    {"id": "delay", "label": "Delay", "nodes": ["baseline", "longer-delay"]},
]

DEFAULT_CASE = "baseline"


def production_jobs() -> List[Dict[str, Any]]:
    """Every trajectory the series may run, in execution order."""

    jobs: List[Dict[str, Any]] = [
        {
            "job_id": "pilot-baseline",
            "role": "pilot",
            "case_id": "baseline",
            "n_steps": PILOT_FRAMES,
            "burn_in": PILOT_BURN_IN,
            "root_seed": ROOT_SEED,
            "observer": True,
            "display_indices": list(PILOT_DISPLAY_INDICES),
        }
    ]
    for case in CASES:
        jobs.append(
            {
                "job_id": f"case-{case['id']}",
                "role": "production",
                "case_id": case["id"],
                "n_steps": PRODUCTION_FRAMES,
                "burn_in": PRODUCTION_BURN_IN,
                "root_seed": ROOT_SEED,
                "observer": True,
                "display_indices": list(movie_indices()),
            }
        )
    jobs.append(
        {
            "job_id": "control-baseline-no-observer",
            "role": "passivity_control",
            "case_id": "baseline",
            "n_steps": PRODUCTION_FRAMES,
            "burn_in": PRODUCTION_BURN_IN,
            "root_seed": ROOT_SEED,
            "observer": False,
            "display_indices": [],
        }
    )
    jobs.append(
        {
            "job_id": "sensitivity-baseline-seed2",
            "role": "seed_sensitivity",
            "case_id": "baseline",
            "n_steps": PRODUCTION_FRAMES,
            "burn_in": PRODUCTION_BURN_IN,
            "root_seed": SENSITIVITY_SEED,
            "observer": True,
            # Scalars and the numeric mean PSFs only; no public movie.
            "display_indices": [],
        }
    )
    return jobs


def case_by_id(case_id: str) -> Dict[str, Any]:
    for case in CASES:
        if case["id"] == case_id:
            return case
    raise KeyError(f"unknown explorer case {case_id!r}")
