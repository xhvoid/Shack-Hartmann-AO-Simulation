"""Private compatibility adapters for the canonical interaction calibrator.

The installed legacy modules retain their historical signatures and return
types.  This module contains only the unit/sign/layout glue needed to express
those calls through :mod:`shwfs_ao.calibration.interaction`; it deliberately
owns no finite-difference implementation.
"""

from __future__ import annotations

from collections.abc import Mapping
import math

import numpy as np

from ..backends.native.dm import NativeDmBackend
from ..backends.native.modes import (
    NativeModesError,
    normalize_mode_to_unit_pupil_rms,
)
from ..calibration.interaction import (
    DmActuatorProbeBasis,
    ModalProbeBasis,
    calibrate_interaction_matrix,
)
from ..core.random import NamedRandomStreams
from ..dm.config import DMConfig
from ..dm.model import DeformableMirror


def calibrate_legacy_modal_columns(
    modes: Mapping[object, np.ndarray],
    pupil_mask: np.ndarray,
    sensor,
    *,
    coefficient_amplitude: float,
    opd_m_per_raw_unit: float,
    method: str,
    random_streams: NamedRandomStreams,
) -> tuple[np.ndarray, list[object]]:
    """Calibrate raw legacy maps and restore response-per-raw-coefficient.

    Canonical modal coordinates are sampled-pupil, piston-removed unit-RMS
    OPD maps.  Historical callers instead supply arbitrary-scaled maps.  One
    canonical calibration per coordinate permits the physical poke amplitude
    to retain that raw scale exactly, including the detector paths where the
    finite-difference amplitude is expressed in phase radians.
    """

    names = list(modes.keys())
    row_count = len(tuple(sensor.row_ids))
    if not names:
        return np.empty((row_count, 0), dtype=float), names

    pupil = np.asarray(pupil_mask, dtype=bool)
    coefficient = _positive_finite(
        coefficient_amplitude,
        label="coefficient_amplitude",
    )
    conversion = _positive_finite(
        opd_m_per_raw_unit,
        label="opd_m_per_raw_unit",
    )
    columns: list[np.ndarray] = []
    for index, name in enumerate(names):
        raw_mode = _legacy_mode(modes[name], pupil)
        try:
            _, raw_scale = normalize_mode_to_unit_pupil_rms(
                raw_mode,
                pupil,
                remove_piston=True,
                return_scale=True,
            )
        except NativeModesError as exc:
            if "non-zero pupil RMS" not in str(exc):
                raise
            # A pure piston has exactly zero SH-WFS response.  The canonical
            # calibrator correctly rejects such a coordinate; the legacy APIs
            # historically returned its explicit zero column instead.
            columns.append(np.zeros(row_count, dtype=float))
            continue

        internal_id = f"legacy-modal-{index:06d}"
        basis = ModalProbeBasis(
            {internal_id: raw_mode},
            pupil,
        )
        canonical_scale = float(np.asarray(basis.normalization_scales)[0])
        if canonical_scale != raw_scale:
            raise RuntimeError(
                "ModalProbeBasis normalization scale differs from the native "
                "mode owner."
            )
        physical_per_raw_unit_m = canonical_scale * conversion
        amplitude_m = coefficient * physical_per_raw_unit_m
        try:
            interaction = calibrate_interaction_matrix(
                basis,
                sensor,
                amplitude_m,
                random_streams=random_streams,
                method=method,
                include_noise=False,
                repeats=1,
            )
        except ValueError as exc:
            # Retain the historical explicit zero response for an unobservable
            # but non-piston map.  Do not mask unrelated validation failures.
            message = str(exc).lower()
            if "zero" not in message or "column" not in message:
                raise
            columns.append(np.zeros(row_count, dtype=float))
            continue
        column = np.asarray(interaction.matrix[:, 0], dtype=float)
        columns.append(column * physical_per_raw_unit_m)

    return np.column_stack(columns), names


def calibrate_legacy_influence_columns(
    influence_functions: np.ndarray,
    pupil_mask: np.ndarray,
    x_m: np.ndarray,
    y_m: np.ndarray,
    sensor,
    *,
    amplitude_m: float,
    output_scale_m: float,
    method: str,
    random_streams: NamedRandomStreams,
) -> np.ndarray:
    """Calibrate raw influence maps through a temporary canonical DM model."""

    requested_amplitude = _positive_finite(amplitude_m, label="amplitude_m")
    output_scale = _positive_finite(output_scale_m, label="output_scale_m")
    dm = legacy_influence_dm(
        influence_functions,
        pupil_mask,
        x_m,
        y_m,
        minimum_stroke_m=requested_amplitude,
    )
    row_count = len(tuple(sensor.row_ids))
    columns: list[np.ndarray] = []
    for identifier in dm.actuator_ids:
        basis = DmActuatorProbeBasis(dm, coordinate_ids=(identifier,))
        try:
            interaction = calibrate_interaction_matrix(
                basis,
                sensor,
                requested_amplitude,
                random_streams=random_streams,
                method=method,
                include_noise=False,
                repeats=1,
            )
        except ValueError as exc:
            message = str(exc).lower()
            if "zero" not in message or "column" not in message:
                raise
            columns.append(np.zeros(row_count, dtype=float))
            continue
        columns.append(
            np.asarray(interaction.matrix[:, 0], dtype=float) * output_scale
        )
    return np.column_stack(columns)


def legacy_influence_dm(
    influence_functions: np.ndarray,
    pupil_mask: np.ndarray,
    x_m: np.ndarray,
    y_m: np.ndarray,
    *,
    minimum_stroke_m: float,
) -> DeformableMirror:
    """Wrap an ordered legacy influence stack in repository DM policy."""

    influences = np.asarray(influence_functions, dtype=float)
    pupil = np.asarray(pupil_mask, dtype=bool)
    x_grid = np.asarray(x_m, dtype=float)
    y_grid = np.asarray(y_m, dtype=float)
    if influences.ndim != 3 or influences.shape[0] < 1:
        raise ValueError(
            "influence_functions must have non-empty shape (n_actuators, ny, nx)."
        )
    if influences.shape[1:] != pupil.shape:
        raise ValueError("influence_functions must match pupil_mask shape.")
    if x_grid.shape != pupil.shape or y_grid.shape != pupil.shape:
        raise ValueError("X, Y, and pupil_mask must have matching shapes.")
    if not np.all(np.isfinite(influences[:, pupil])):
        raise ValueError("influence_functions must be finite inside pupil_mask.")
    cleaned = np.where(pupil[None, :, :], influences, 0.0)
    diameter = max(
        float(np.nanmax(x_grid) - np.nanmin(x_grid)),
        float(np.nanmax(y_grid) - np.nanmin(y_grid)),
    )
    if not math.isfinite(diameter) or diameter <= 0.0:
        raise ValueError("X and Y must span a positive finite diameter.")
    minimum_stroke = _positive_finite(
        minimum_stroke_m,
        label="minimum_stroke_m",
    )
    # DMConfig retains a legacy nm-facing field.  Keep generous finite policy
    # headroom so this compatibility-only virtual model never clips a poke.
    stroke_limit_nm = max(1.0e12, 2.0 * minimum_stroke * 1.0e9)
    config = DMConfig(
        telescope_diameter_m=diameter,
        n_actuators_across=2,
        stroke_limit_nm=stroke_limit_nm,
        source_class="synthetic_assumed",
        source_note=(
            "Compatibility-only virtual DM wrapping caller-supplied legacy "
            "influence functions for canonical interaction calibration."
        ),
    )
    identifiers = tuple(
        f"legacy-actuator-{index:06d}" for index in range(cleaned.shape[0])
    )
    return DeformableMirror(
        config,
        NativeDmBackend(cleaned),
        actuator_ids=identifiers,
        x_m=np.asarray(x_grid, dtype=float),
        y_m=np.asarray(y_grid, dtype=float),
        pupil_mask=np.asarray(pupil, dtype=bool),
    )


def legacy_y_up_matrix(matrix: np.ndarray) -> np.ndarray:
    """Convert canonical detector-row-positive y rows to legacy y-up rows."""

    values = np.array(matrix, dtype=float, copy=True)
    if values.ndim != 2 or values.shape[0] % 2:
        raise ValueError("interaction matrix must have interleaved x/y rows.")
    values[1::2, :] *= -1.0
    return values


def legacy_streams(root_seed: int = 1) -> NamedRandomStreams:
    """Return the explicit stream provider used by deterministic adapters."""

    return NamedRandomStreams(int(root_seed))


def _legacy_mode(value: object, pupil: np.ndarray) -> np.ndarray:
    try:
        mode = np.asarray(value, dtype=float)
    except (TypeError, ValueError) as exc:
        raise ValueError("mode maps must contain real numeric values.") from exc
    if mode.shape != pupil.shape:
        raise ValueError("mode maps must match pupil_mask shape.")
    if not np.all(np.isfinite(mode[pupil])):
        raise ValueError("mode maps must be finite inside pupil_mask.")
    return np.where(pupil, mode, 0.0)


def _positive_finite(value: object, *, label: str) -> float:
    if isinstance(value, (bool, np.bool_)):
        raise ValueError(f"{label} must be a positive finite number.")
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{label} must be a positive finite number.") from exc
    if not math.isfinite(result) or result <= 0.0:
        raise ValueError(f"{label} must be a positive finite number.")
    return result


__all__: tuple[str, ...] = ()
