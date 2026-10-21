"""Synthetic trace payloads for the S4 traced-family tests (no physics, no package loop)."""

from __future__ import annotations

from dataclasses import replace
import hashlib
import json
from typing import Any

import numpy as np

from shwfs_ao.experiments.detector_level import MASK_LOCK_SCHEMA, MASK_LOCKED_NOISE_ARMS, PAIRED_NOISE_ARMS, TRACE_SCHEMA
from shwfs_ao.io.configs import RandomSeedConfig


def fake_trace(
    *,
    n_steps: int,
    burn_in: int,
    n_lenslets: int = 3,
    seed: int = 0,
    mode: str = "traced",
    delta_v_level: float = 1.0e-17,
    sigma_px: float = 0.05,
) -> dict[str, Any]:
    """A trace payload with the declared shapes: white centroid noise about a fixed expected centroid."""

    rng = np.random.default_rng(seed)
    arms = list(MASK_LOCKED_NOISE_ARMS if mode == "mask_locked" else PAIRED_NOISE_ARMS)
    rows = 2 * n_lenslets
    masks = np.ones((n_steps, rows), dtype=bool)
    analysed = n_steps - burn_in

    def arm(name: str) -> dict[str, Any]:
        telemetry = {
            "centroids_xy_px": 7.0 + sigma_px * rng.standard_normal((n_steps, n_lenslets, 2)),
            "expected_centroids_xy_px": np.full((n_steps, n_lenslets, 2), 7.0),
            "centroid_sigma_xy_px": np.full((n_steps, n_lenslets, 2), sigma_px),
            "fluxes_e": np.full((n_steps, n_lenslets), 500.0),
            "peak_snr": np.full((n_steps, n_lenslets), 10.0),
            "total_snr": np.full((n_steps, n_lenslets), 30.0),
            "centroid_sigma_px": np.full((n_steps, n_lenslets), sigma_px),
            "clipping_fraction": np.zeros((n_steps, n_lenslets)),
            "centroid_calibration_sigma_px": np.zeros((n_steps, n_lenslets)),
            "masked_pixel_fraction": np.zeros((n_steps, n_lenslets)),
            "saturated_pixel_count": np.zeros((n_steps, n_lenslets)),
            "valid_subapertures": np.ones((n_steps, n_lenslets), dtype=bool),
            "valid_by_flux": np.ones((n_steps, n_lenslets), dtype=bool),
            "valid_by_snr": np.ones((n_steps, n_lenslets), dtype=bool),
            "valid_by_uncertainty": np.ones((n_steps, n_lenslets), dtype=bool),
            "valid_by_clipping": np.ones((n_steps, n_lenslets), dtype=bool),
            "uncertainty_supported": np.ones((n_steps, n_lenslets), dtype=bool),
        }
        return {
            "measurement_row_masks": masks.copy(),
            "valid_measurement_fraction": np.ones(n_steps),
            "valid_subaperture_fraction": np.ones(n_steps),
            "saturation_fraction": np.zeros(n_steps),
            "reconstruction_usable": np.ones(n_steps, dtype=bool),
            "open_loop_opd_rms_m": np.full(n_steps, 5.0e-7),
            "pre_update_residual_opd_rms_m": np.full(n_steps, 3.0e-7),
            "post_update_residual_opd_rms_m": np.full(n_steps, 3.0e-7),
            "telemetry": telemetry,
            "telemetry_unavailable": [],
            "telemetry_frames": n_steps,
            "subaperture_ids": tuple(f"L{index}" for index in range(n_lenslets)),
            "history_config_hash": f"{name}-history",
            "component_hashes": {"wfs": f"{name}-wfs"},
            "random_stream_ids": {"atmosphere": "stream"},
            "recovery": None,
            "wfs_exposure": None,
        }

    delta_v = delta_v_level * (1.0 + 0.1 * rng.standard_normal(analysed))
    payload: dict[str, Any] = {
        "schema": TRACE_SCHEMA,
        "arm_order": arms,
        "noisy_arm": arms[0] if arms[0].startswith("noise_on") else arms[1],
        "twin_arm": "operating_expectation",
        "n_steps": n_steps,
        "burn_in_frames": burn_in,
        "frame_index": np.arange(n_steps, dtype=np.int64),
        "analysed_frame_index": np.arange(burn_in, n_steps, dtype=np.int64),
        "delta_v_m2": delta_v,
        "mean_square_difference_m2": delta_v + 1.0e-18,
        "cross_term_m2": np.full(analysed, 1.0e-18),
        "mask_disagreement_rows": np.zeros(n_steps, dtype=np.int64),
        "row_ids": tuple(f"L{index}:{axis}" for index in range(n_lenslets) for axis in "xy"),
        "calibration_valid_rows": np.ones(rows, dtype=bool),
        "arms": {name: arm(name) for name in arms},
        "propagation_weights": {
            "available": True, "definition": "fake", "units": "m2_opd_per_px2", "row_order": "x then y",
            "weights_m2_per_px2": np.full(rows, 1.0e-16), "saturated_probe_rows": 0,
        },
        "residual_maps": None,
    }
    if mode == "mask_locked":
        payload["mask_lock"] = {
            "rows_removed": np.zeros(n_steps, dtype=np.int64), "rows_added": np.zeros(n_steps, dtype=np.int64),
            "rows_unaddable": np.zeros(n_steps, dtype=np.int64), "own_valid_subapertures": np.ones((n_steps, n_lenslets), dtype=bool),
        }
    return payload


def fake_traced_run(
    config: Any,
    *,
    root_seed: int,
    n_steps: int,
    burn_in_frames: int,
    execution: Any,
    retain_residual_maps: bool = False,
    propagation_weights: bool = True,
    delta_v_level: float | None = None,
    **keywords: Any,
) -> dict[str, Any]:
    """A stand-in for ``paired_noise_run_traced`` (or the mask-locked sibling when ``allow_partial_lock`` is passed)."""

    run_config = replace(
        config, random=RandomSeedConfig(root_seed=int(root_seed)), controller=replace(config.controller, n_steps=int(n_steps))
    )
    mode = "mask_locked" if "allow_partial_lock" in keywords else "traced"
    level = 1.0e-17 if delta_v_level is None else delta_v_level
    trace = fake_trace(n_steps=n_steps, burn_in=burn_in_frames, seed=int(root_seed), mode=mode, delta_v_level=level)
    if retain_residual_maps:
        trace["residual_maps"] = {
            "pupil_mask": np.ones((2, 2), dtype=bool), "precision": "float32",
            **{arm: np.zeros((n_steps - burn_in_frames, 4), dtype=np.float32) for arm in trace["arm_order"]},
        }
    result: dict[str, Any] = {
        "config_hash": run_config.config_hash, "root_seed": int(root_seed), "n_steps": int(n_steps), "burn_in_frames": int(burn_in_frames),
        "block_frames": 25, "arms": {arm: {"post_update_rms_m": 3.0e-7} for arm in trace["arm_order"]},
        "predicted_centroid_variance_px2": 0.002, "supported_lenslet_fraction": 1.0, "detected_e_full_subap": 2061.0,
        "noise_variance_m2": float(np.mean(trace["delta_v_m2"])), "noise_variance_standard_error_m2": None,
        "mean_square_difference_m2": float(np.mean(trace["mean_square_difference_m2"])), "mean_square_difference_standard_error_m2": None,
        "operating_state": {"available": True, "equal_weight": {"ratio_variance_over_model": 1.0}}, "trace_summary": {"gate_quiet": True},
        "trace": trace, "wall_s": 0.0,
    }
    if mode == "mask_locked":
        result["lock"] = {"exact": True}
        result["mask_lock_protocol"] = {"schema": MASK_LOCK_SCHEMA}
    return result


# -- Sidecar mutations of the two independent review rounds (T1-02) -----------
#
# Each entry: mode, a function (arrays, metadata) -> (arrays, metadata) that
# changes one semantic element of a valid archive, the refusal text expected
# from the evidence runner and the one expected from the analysis loader.  The
# declared array table is refreshed for dtype and shape after the mutation so
# only the semantics are wrong, as the reviewer's probes did.


def _refresh_declarations(arrays: dict[str, np.ndarray], metadata: dict[str, Any]) -> dict[str, Any]:
    default = {"units": "m2", "axes": ["analysed_frame"], "meaning": "inert"}
    metadata["arrays"] = {
        name: {**metadata["arrays"].get(name, default), "dtype": str(array.dtype), "shape": list(array.shape)}
        for name, array in arrays.items()
    }
    return metadata


def _mutation(name: str, arrays: dict[str, np.ndarray], metadata: dict[str, Any]) -> tuple[dict[str, np.ndarray], dict[str, Any]]:
    arrays = {key: value.copy() for key, value in arrays.items()}
    metadata = json.loads(json.dumps(metadata))
    if name == "original_empty_payload":
        arrays = {"delta_v_m2": np.empty(0, dtype=np.float64)}
    elif name == "original_inconsistent_metadata":
        metadata.update(n_steps=999, burn_in_frames=998, trace_schema="wrong.trace.schema", arm_order=["wrong_arm"], diagnostic_protocol={"other_semantics": True})
        metadata["diagnostic_protocol_hash"] = hashlib.sha256(json.dumps(metadata["diagnostic_protocol"], sort_keys=True).encode()).hexdigest()
    elif name == "embedded_diagnostic_payload_only":
        metadata["diagnostic_protocol"]["frame_domain"] = "wrong domain"
    elif name == "frame_domain":
        arrays["analysed_frame_index"] = np.arange(arrays["analysed_frame_index"].size, dtype=np.int64)
    elif name == "delta_units_nm2":
        metadata["arrays"]["delta_v_m2"]["units"] = "nm2"
    elif name == "centroid_axes_swapped":
        metadata["arrays"]["noise_on__telemetry__centroids_xy_px"]["axes"] = ["frame", "xy", "lenslet"]
    elif name == "meaning_changed":
        metadata["arrays"]["cross_term_m2"]["meaning"] = "another quantity"
    elif name == "twin_lenslet_order":
        arrays["operating_expectation__subaperture_ids"] = arrays["operating_expectation__subaperture_ids"][::-1].copy()
    elif name == "row_xy_order":
        arrays["row_ids"][[0, 1]] = arrays["row_ids"][[1, 0]]
    elif name == "duplicate_rows":
        arrays["row_ids"][1] = arrays["row_ids"][0]
    elif name == "centroid_one_axis":
        arrays["noise_on__telemetry__centroids_xy_px"] = arrays["noise_on__telemetry__centroids_xy_px"][:, :, :1].copy()
    elif name == "wrong_centroid_dtype":
        arrays["noise_on__telemetry__centroids_xy_px"] = arrays["noise_on__telemetry__centroids_xy_px"].astype(np.float32)
    elif name == "missing_available_weights":
        del arrays["propagation_weights__weights_m2_per_px2"]
    elif name == "missing_locked_arrays":
        arrays = {key: value for key, value in arrays.items() if not key.startswith("mask_lock__")}
    elif name == "extra_declared_array":
        arrays["unexpected_extra"] = np.zeros(3, dtype=np.float64)
        metadata["arrays"]["unexpected_extra"] = {"units": "1", "axes": ["unexpected"], "meaning": "not a declared trace field"}
    elif name == "wrong_mask_dtype":
        arrays["noise_on__measurement_row_masks"] = arrays["noise_on__measurement_row_masks"].astype(np.int64)
    elif name == "other_run_embedded":
        metadata["root_seed"] = 99
    else:
        raise AssertionError(name)
    return arrays, _refresh_declarations(arrays, metadata)


SIDECAR_MUTATIONS: dict[str, tuple[str, str, str]] = {
    # name: (mode, runner refusal text, analysis refusal text)
    "original_empty_payload": ("traced", "no row layout|exactly the protocol's arrays", "no row or lenslet layout|exactly the protocol's arrays"),
    "original_inconsistent_metadata": ("traced", "n_steps|diagnostic protocol", "frame counts|diagnostic"),
    "embedded_diagnostic_payload_only": ("traced", "diagnostic", "diagnostic"),
    "frame_domain": ("traced", "analysed_frame_index", "frame indices"),
    "delta_units_nm2": ("traced", "units", "units"),
    "centroid_axes_swapped": ("traced", "axes", "axes"),
    "meaning_changed": ("traced", "meaning", "units"),
    "twin_lenslet_order": ("traced", "another order", "another order"),
    "row_xy_order": ("traced", "canonical interleaved", "canonical interleaved"),
    "duplicate_rows": ("traced", "canonical interleaved|duplicated", "canonical interleaved|duplicated"),
    "centroid_one_axis": ("traced", "shape", "shape"),
    "wrong_centroid_dtype": ("traced", "dtype", "dtype"),
    "missing_available_weights": ("traced", "exactly the protocol's arrays", "exactly the protocol's arrays"),
    "missing_locked_arrays": ("mask_locked", "exactly the protocol's arrays", "exactly the protocol's arrays"),
    "extra_declared_array": ("traced", "exactly the protocol's arrays", "exactly the protocol's arrays"),
    "wrong_mask_dtype": ("traced", "dtype", "dtype"),
    "other_run_embedded": ("traced", "another label or seed", "root_seed|another label or seed"),
}


def mutate_sidecar(name: str, arrays: dict[str, np.ndarray], metadata: dict[str, Any]) -> tuple[dict[str, np.ndarray], dict[str, Any]]:
    """Apply one named mutation to copies of a valid sidecar's arrays and metadata."""

    return _mutation(name, arrays, metadata)
