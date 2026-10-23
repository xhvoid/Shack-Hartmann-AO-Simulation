"""Static incoherent binary scene and its relative synthetic observations.

Scene (frozen before any AO result was inspected)
    On the native science PSF grid (its actual x/y angular axes), the primary
    sits on the sample whose angle is exactly zero on both axes and the
    secondary six native x cells towards +x at the same y sample.  Relative
    weights are 2/3 and 1/3 (flux ratio 2:1), so the scene's total flux is one.
    Values are relative flux per numerical cell.

Observation
    ``J = S (*) P``: discrete *linear* convolution with zero extension.  The
    full result has ``N + M - 1`` samples per axis; with scene samples at
    ``theta_S[p]`` and kernel samples at ``theta_P[i]`` the full output sample
    ``m = p + i`` lies at ``theta_S[p] + theta_P[i]``, so the output axis is
    ``theta_S[0] + theta_P[0] + m * delta``.  The display crop is the set of
    full-output samples whose angles equal the native PSF grid, found from
    those coordinates (never from array midpoints or a library ``same``
    crop).  Positive x is the column direction of increasing angle, as in the
    propagator (``axis_layout = x_columns_y_rows``).

The convolution is evaluated exactly as the definition: every non-zero scene
cell adds its weight times the kernel into the full array at its index
offset.  This is exact for the sparse scene and has no wraparound; the tests
compare it with ``scipy.signal.convolve2d(..., mode="full")`` and with an
FFT on padded arrays.

The spatially invariant on-axis PSF over this compact scene is an
illustrative assumption: the SCAO model produces no field-dependent PSF.
"""

from __future__ import annotations

from typing import Any, Dict, List, Tuple

import numpy as np

import identity
import protocol


RENDERER_REVISION = "ao-explorer.binary-observation.v1"
CONVOLUTION_POLICY = {
    "kind": "discrete linear convolution, zero extension",
    "full_shape_rule": "N + M - 1 samples per axis",
    "evaluation": "explicit sum of weight-scaled kernels at each non-zero scene cell (exact, no FFT, no wrap)",
    "kernel_origin": "the kernel sample at exactly zero angle on both actual axes",
    "output_axes": "theta_S[0] + theta_P[0] + m * delta for full index m",
    "crop": "full-output samples whose angles equal the native PSF grid, matched from coordinates",
    "boundary": "zero outside both arrays",
    "renormalization": "none (no peak, cropped-sum or per-image normalization)",
    "spatial_invariance": "one on-axis PSF assumed throughout the compact scene (illustrative)",
}


class BinarySceneError(ValueError):
    """Raised when a scene, parent PSF or grid fails the observation contract."""


def zero_index(axis: np.ndarray, *, label: str) -> int:
    """Index of the sample at exactly zero angle (the axis must contain it)."""

    values = np.asarray(axis, dtype=float)
    hits = np.flatnonzero(values == 0.0)
    if hits.size != 1:
        raise BinarySceneError(f"{label} has {hits.size} samples at exactly zero angle; expected one.")
    return int(hits[0])


def uniform_step(axis: np.ndarray, *, label: str) -> float:
    values = np.asarray(axis, dtype=float)
    steps = np.diff(values)
    step = float(steps[0])
    if step <= 0.0 or not np.allclose(steps, step, rtol=1e-12, atol=0.0):
        raise BinarySceneError(f"{label} is not a uniform increasing axis.")
    return step


def build_scene(x_angle_rad: np.ndarray, y_angle_rad: np.ndarray, *, wavelength_m: float,
                telescope_diameter_m: float) -> Dict[str, Any]:
    """The frozen binary on a given native grid, with its exported coordinates."""

    x = np.asarray(x_angle_rad, dtype=float)
    y = np.asarray(y_angle_rad, dtype=float)
    ix0 = zero_index(x, label="x axis")
    iy0 = zero_index(y, label="y axis")
    ix1 = ix0 + protocol.SCENE_SECONDARY_OFFSET_X_CELLS
    iy1 = iy0 + protocol.SCENE_SECONDARY_OFFSET_Y_CELLS
    if not (0 <= ix1 < x.size and 0 <= iy1 < y.size):
        raise BinarySceneError("the secondary falls outside the native grid.")
    weights = protocol.SCENE_WEIGHTS
    scene = np.zeros((y.size, x.size), dtype=float)
    scene[iy0, ix0] = weights[0]
    scene[iy1, ix1] += weights[1]
    separation = float(x[ix1] - x[ix0])
    lambda_over_d = float(wavelength_m) / float(telescope_diameter_m)
    grid_record = {
        "shape_yx": [int(y.size), int(x.size)],
        "x_angle_rad_sha256": identity.sha256_bytes(x.tobytes()),
        "y_angle_rad_sha256": identity.sha256_bytes(y.tobytes()),
        "x_step_rad": uniform_step(x, label="x axis"),
        "y_step_rad": uniform_step(y, label="y axis"),
        "x_zero_index": ix0,
        "y_zero_index": iy0,
        "axis_layout": "x_columns_y_rows",
        "x_direction": "column index increases with angle",
        "y_direction": "row index increases with angle",
    }
    grid_id = identity.sha256_bytes(identity.canonical_json_bytes(grid_record))
    sources = [
        {
            "role": "primary",
            "weight": weights[0],
            "index_yx": [iy0, ix0],
            "angle_xy_rad": [float(x[ix0]), float(y[iy0])],
        },
        {
            "role": "secondary",
            "weight": weights[1],
            "index_yx": [iy1, ix1],
            "angle_xy_rad": [float(x[ix1]), float(y[iy1])],
        },
    ]
    record = {
        "schema": protocol.SCENE_SCHEMA,
        "kind": "static incoherent binary, two point sources on native grid cells",
        "wavelength_m": float(wavelength_m),
        "flux_unit": "relative flux per numerical cell (scene total = 1)",
        "flux_ratio_primary_to_secondary": 2.0,
        "total_flux": float(scene.sum()),
        "grid": grid_record,
        "grid_id": grid_id,
        "sources": sources,
        "separation_rad": separation,
        "separation_mas": separation * 180.0 / np.pi * 3600.0e3,
        "separation_lambda_over_d": separation / lambda_over_d,
        "separation_native_x_cells": protocol.SCENE_SECONDARY_OFFSET_X_CELLS,
        "lambda_over_d_rad": lambda_over_d,
        "discretization": "each source occupies exactly one native cell; positions are grid-aligned, not sub-pixel",
        "guide_source_relation": "independent of the WFS guide-source magnitude; identical for every case",
        "scene_array_sha256": identity.sha256_bytes(scene.tobytes()),
    }
    record["scene_id"] = identity.sha256_bytes(identity.canonical_json_bytes(
        {key: record[key] for key in ("schema", "wavelength_m", "grid_id", "sources", "scene_array_sha256")}
    ))
    return {"scene": scene, "record": record}


def linear_convolution_full(scene: np.ndarray, kernel: np.ndarray) -> np.ndarray:
    """Exact full linear convolution with zero extension (sparse scene)."""

    s = np.asarray(scene, dtype=float)
    k = np.asarray(kernel, dtype=float)
    out = np.zeros((s.shape[0] + k.shape[0] - 1, s.shape[1] + k.shape[1] - 1), dtype=float)
    rows, columns = np.nonzero(s)
    for row, column in zip(rows.tolist(), columns.tolist()):
        out[row:row + k.shape[0], column:column + k.shape[1]] += s[row, column] * k
    return out


def full_output_axis(scene_axis: np.ndarray, kernel_axis: np.ndarray) -> np.ndarray:
    step_s = uniform_step(scene_axis, label="scene axis")
    step_k = uniform_step(kernel_axis, label="kernel axis")
    if not np.isclose(step_s, step_k, rtol=1e-12, atol=0.0):
        raise BinarySceneError("scene and kernel axes have different sampling.")
    count = scene_axis.size + kernel_axis.size - 1
    return float(scene_axis[0]) + float(kernel_axis[0]) + np.arange(count, dtype=float) * step_k


def crop_slice(full_axis: np.ndarray, native_axis: np.ndarray, *, label: str) -> Tuple[int, int]:
    """Full-output index range whose angles equal the native grid."""

    step = uniform_step(native_axis, label=label)
    start = int(round((float(native_axis[0]) - float(full_axis[0])) / step))
    stop = start + native_axis.size
    if start < 0 or stop > full_axis.size:
        raise BinarySceneError(f"{label}: native window is not inside the full output.")
    window = full_axis[start:stop]
    if not np.allclose(window, native_axis, rtol=0.0, atol=1e-9 * step):
        raise BinarySceneError(f"{label}: full-output angles do not match the native grid.")
    return start, stop


def observe(scene_bundle: Dict[str, Any], kernel: np.ndarray, x_angle_rad: np.ndarray,
            y_angle_rad: np.ndarray) -> Dict[str, Any]:
    """Convolve the frozen scene with one numeric mean PSF and crop to the native window."""

    scene = scene_bundle["scene"]
    record = scene_bundle["record"]
    x = np.asarray(x_angle_rad, dtype=float)
    y = np.asarray(y_angle_rad, dtype=float)
    if identity.sha256_bytes(x.tobytes()) != record["grid"]["x_angle_rad_sha256"] or identity.sha256_bytes(
        y.tobytes()
    ) != record["grid"]["y_angle_rad_sha256"]:
        raise BinarySceneError("the parent PSF grid differs from the scene grid.")
    k = np.asarray(kernel, dtype=float)
    if k.shape != scene.shape:
        raise BinarySceneError("the parent PSF shape differs from the scene grid.")
    if not np.all(np.isfinite(k)) or np.any(k < 0.0):
        raise BinarySceneError("the parent PSF must be finite and non-negative.")
    full = linear_convolution_full(scene, k)
    full_x = full_output_axis(x, x)
    full_y = full_output_axis(y, y)
    x_start, x_stop = crop_slice(full_x, x, label="x")
    y_start, y_stop = crop_slice(full_y, y, label="y")
    cropped = full[y_start:y_stop, x_start:x_stop]
    full_flux = float(full.sum())
    cropped_flux = float(cropped.sum())
    expected_full = float(scene.sum()) * float(k.sum())
    return {
        "image": cropped,
        "full_shape_yx": [int(full.shape[0]), int(full.shape[1])],
        "full_axis_first_rad": [float(full_x[0]), float(full_y[0])],
        "crop_slices_yx": [[y_start, y_stop], [x_start, x_stop]],
        "scene_flux": float(scene.sum()),
        "kernel_flux": float(k.sum()),
        "full_flux": full_flux,
        "expected_full_flux": expected_full,
        "full_flux_error": full_flux - expected_full,
        "cropped_flux": cropped_flux,
        "retained_fraction": cropped_flux / full_flux,
        "lost_fraction": 1.0 - cropped_flux / full_flux,
        "image_sha256": identity.sha256_bytes(np.ascontiguousarray(cropped).tobytes()),
    }


def source_positions(record: Dict[str, Any]) -> List[Dict[str, Any]]:
    return [dict(source) for source in record["sources"]]
