"""Native geometric Shack--Hartmann wavefront sensor.

This path measures local OPD slopes directly and deliberately has no imaging
or camera dependency.  The masked finite-difference and subaperture-averaging
algorithm is the repository's frozen geometric baseline. Positive x and y OPD
gradients produce positive x and y slope rows respectively.
"""

from __future__ import annotations

from dataclasses import dataclass
import math

import numpy as np

from ...core.hashing import stable_hash
from ...core.protocols import RandomStreams
from ...core.provenance import Provenance
from ...core.types import MeasurementVector, WfsMeasurement
from .geometry import ShackHartmannGeometry


class GeometricShackHartmannError(ValueError):
    """Raised when geometric calibration or measurement input is invalid."""


@dataclass(frozen=True)
class GeometricShackHartmannCalibration:
    """Explicit local-slope reference for the native geometric sensor."""

    __hash_schema_id__ = "shwfs_ao.wfs.GeometricShackHartmannCalibration.v1"

    geometry: ShackHartmannGeometry
    reference_slopes_rad: np.ndarray
    subaperture_ids: tuple[str, ...]
    row_ids: tuple[str, ...]
    config_hash: str
    provenance: Provenance

    def __post_init__(self) -> None:
        if not isinstance(self.geometry, ShackHartmannGeometry):
            raise GeometricShackHartmannError(
                "geometry must be a ShackHartmannGeometry."
            )
        if self.subaperture_ids != self.geometry.subaperture_ids:
            raise GeometricShackHartmannError(
                "subaperture_ids must exactly match geometry.subaperture_ids."
            )
        expected_rows = _row_ids(self.subaperture_ids)
        if self.row_ids != expected_rows:
            raise GeometricShackHartmannError(
                "row_ids must use S:x, S:y order for every subaperture."
            )
        reference = _immutable_reference(
            self.reference_slopes_rad,
            len(self.subaperture_ids),
        )
        if not isinstance(self.provenance, Provenance):
            raise GeometricShackHartmannError(
                "provenance must be a Provenance."
            )
        if not isinstance(self.config_hash, str) or not self.config_hash:
            raise GeometricShackHartmannError(
                "config_hash must be a non-empty string."
            )
        expected_hash = _calibration_hash(
            self.geometry,
            reference,
            self.provenance,
        )
        if self.config_hash != expected_hash:
            raise GeometricShackHartmannError(
                "config_hash does not match geometric calibration content."
            )
        object.__setattr__(self, "reference_slopes_rad", reference)

    @classmethod
    def zero(
        cls,
        geometry: ShackHartmannGeometry,
        *,
        provenance: Provenance | None = None,
    ) -> GeometricShackHartmannCalibration:
        """Create an explicit all-zero reference-slope calibration."""

        if not isinstance(geometry, ShackHartmannGeometry):
            raise GeometricShackHartmannError(
                "geometry must be a ShackHartmannGeometry."
            )
        resolved = _provenance(provenance)
        reference = np.zeros((len(geometry.subaperture_ids), 2), dtype=float)
        return cls(
            geometry=geometry,
            reference_slopes_rad=reference,
            subaperture_ids=geometry.subaperture_ids,
            row_ids=_row_ids(geometry.subaperture_ids),
            config_hash=_calibration_hash(geometry, reference, resolved),
            provenance=resolved,
        )

    @classmethod
    def from_reference(
        cls,
        geometry: ShackHartmannGeometry,
        reference_slopes_rad: np.ndarray,
        *,
        provenance: Provenance | None = None,
    ) -> GeometricShackHartmannCalibration:
        """Create an explicit finite per-subaperture reference calibration."""

        if not isinstance(geometry, ShackHartmannGeometry):
            raise GeometricShackHartmannError(
                "geometry must be a ShackHartmannGeometry."
            )
        resolved = _provenance(provenance)
        reference = _immutable_reference(
            reference_slopes_rad,
            len(geometry.subaperture_ids),
        )
        return cls(
            geometry=geometry,
            reference_slopes_rad=reference,
            subaperture_ids=geometry.subaperture_ids,
            row_ids=_row_ids(geometry.subaperture_ids),
            config_hash=_calibration_hash(geometry, reference, resolved),
            provenance=resolved,
        )


class NativeGeometricShackHartmannSensor:
    """Average masked finite-difference OPD gradients per subaperture."""

    def __init__(
        self,
        geometry_or_calibration: (
            ShackHartmannGeometry | GeometricShackHartmannCalibration
        ),
        *,
        reference_slopes_rad: np.ndarray | None = None,
        provenance: Provenance | None = None,
    ) -> None:
        if isinstance(geometry_or_calibration, GeometricShackHartmannCalibration):
            if reference_slopes_rad is not None or provenance is not None:
                raise GeometricShackHartmannError(
                    "reference_slopes_rad/provenance cannot accompany a complete "
                    "GeometricShackHartmannCalibration."
                )
            calibration = geometry_or_calibration
        elif isinstance(geometry_or_calibration, ShackHartmannGeometry):
            if reference_slopes_rad is None:
                calibration = GeometricShackHartmannCalibration.zero(
                    geometry_or_calibration,
                    provenance=provenance,
                )
            else:
                calibration = GeometricShackHartmannCalibration.from_reference(
                    geometry_or_calibration,
                    reference_slopes_rad,
                    provenance=provenance,
                )
        else:
            raise GeometricShackHartmannError(
                "geometry_or_calibration must be ShackHartmannGeometry or "
                "GeometricShackHartmannCalibration."
            )
        self._calibration = calibration
        self._config_hash = stable_hash(
            {
                "sensor": "native_geometric_shack_hartmann",
                "calibration_hash": calibration.config_hash,
                "algorithm": "masked_finite_difference_mean_v1",
            },
            namespace="wavefront_sensor_config",
        )

    @property
    def config_hash(self) -> str:
        return self._config_hash

    @property
    def row_ids(self) -> tuple[str, ...]:
        return self._calibration.row_ids

    @property
    def subaperture_ids(self) -> tuple[str, ...]:
        return self._calibration.subaperture_ids

    @property
    def geometry(self) -> ShackHartmannGeometry:
        return self._calibration.geometry

    @property
    def calibration(self) -> GeometricShackHartmannCalibration:
        return self._calibration

    def measure(
        self,
        residual_opd_m: np.ndarray,
        *,
        random_streams: RandomStreams,
        include_noise: bool,
    ) -> WfsMeasurement:
        """Return reference-subtracted local OPD gradients.

        ``random_streams`` is accepted to implement the shared sensor protocol
        but is never drawn because this sensor is deterministic.  Likewise,
        ``include_noise`` is validated and otherwise has no effect.
        """

        residual = _validated_residual(residual_opd_m, self.geometry)
        if not isinstance(include_noise, (bool, np.bool_)):
            raise GeometricShackHartmannError(
                "include_noise must be a boolean."
            )
        root_seed, scheme_id = _stream_metadata(random_streams)

        values: list[float] = []
        valid_rows: list[bool] = []
        valid_subapertures: list[bool] = []
        dx_m, dy_m = self.geometry.pupil_geometry.pixel_spacing_xy_m
        valid_gradient_samples = (
            np.asarray(self.geometry.pupil_mask, dtype=bool)
            & np.isfinite(residual)
        )
        gradient_x = _masked_axis_gradient(
            residual,
            valid_gradient_samples,
            dx_m,
            axis=1,
        )
        gradient_y = _masked_axis_gradient(
            residual,
            valid_gradient_samples,
            dy_m,
            axis=0,
        )
        slopes = mean_subaperture_slopes(
            gradient_x,
            gradient_y,
            self.geometry.subaperture_masks,
        )
        for index, gradient in enumerate(slopes):
            usable = bool(np.all(np.isfinite(gradient)))
            if usable:
                reference = self._calibration.reference_slopes_rad[index]
                delta_x = float(gradient[0] - reference[0])
                delta_y = float(gradient[1] - reference[1])
                values.extend((delta_x, delta_y))
            else:
                values.extend((math.nan, math.nan))
            valid_rows.extend((usable, usable))
            valid_subapertures.append(usable)

        vector = MeasurementVector(
            values=np.asarray(values, dtype=float),
            valid_rows=np.asarray(valid_rows, dtype=bool),
            row_ids=self.row_ids,
            measurement_unit="rad_wavefront_slope",
        )
        return WfsMeasurement(
            vector=vector,
            valid_subapertures=np.asarray(valid_subapertures, dtype=bool),
            metadata={
                "sensor_backend_name": "native_geometric",
                "sensor_config_hash": self.config_hash,
                "calibration_config_hash": self._calibration.config_hash,
                "random_root_seed": root_seed,
                "random_derivation_scheme_id": scheme_id,
                "include_noise_requested": bool(include_noise),
            },
        )


GeometricShackHartmannSensor = NativeGeometricShackHartmannSensor


def numerical_gradient(
    wavefront: np.ndarray,
    dx: float,
    mask: np.ndarray | None = None,
) -> tuple[np.ndarray, np.ndarray]:
    """Differentiate without crossing invalid pupil edges.

    Central differences are used where both neighbours are valid. At a mask
    boundary the frozen baseline uses a second-order one-sided difference when
    two samples exist, with a first-order fallback for one neighbour. The
    return order is ``(dW/dx, dW/dy)`` because array axis 1 is physical x.
    """

    if isinstance(dx, (bool, np.bool_)):
        raise GeometricShackHartmannError("dx must be positive.")
    try:
        spacing = float(dx)
    except (TypeError, ValueError) as exc:
        raise GeometricShackHartmannError("dx must be positive.") from exc
    if not math.isfinite(spacing) or spacing <= 0.0:
        raise GeometricShackHartmannError("dx must be positive.")
    values = np.asarray(wavefront, dtype=float)
    if values.ndim != 2:
        raise GeometricShackHartmannError("wavefront must be a 2-D map.")
    if mask is None:
        valid = np.isfinite(values)
    else:
        pupil = np.asarray(mask, dtype=bool)
        if pupil.shape != values.shape:
            raise GeometricShackHartmannError(
                "mask must have the same shape as wavefront."
            )
        valid = pupil & np.isfinite(values)

    dW_dx = _masked_axis_gradient(values, valid, spacing, axis=1)
    dW_dy = _masked_axis_gradient(values, valid, spacing, axis=0)
    return dW_dx, dW_dy


def mean_subaperture_slopes(
    gradient_x: np.ndarray,
    gradient_y: np.ndarray,
    subaperture_masks: tuple[np.ndarray, ...],
) -> np.ndarray:
    """Average finite x/y gradients in each ordered subaperture mask."""

    x_values = np.asarray(gradient_x, dtype=float)
    y_values = np.asarray(gradient_y, dtype=float)
    if x_values.ndim != 2 or y_values.shape != x_values.shape:
        raise GeometricShackHartmannError(
            "gradient_x and gradient_y must be matching 2-D arrays."
        )
    if not isinstance(subaperture_masks, tuple) or not subaperture_masks:
        raise GeometricShackHartmannError(
            "subaperture_masks must be a non-empty ordered tuple."
        )
    slopes: list[tuple[float, float]] = []
    for index, mask in enumerate(subaperture_masks):
        selected = np.asarray(mask, dtype=bool)
        if selected.shape != x_values.shape:
            raise GeometricShackHartmannError(
                f"subaperture_masks[{index}] has the wrong shape."
            )
        finite_x = x_values[selected]
        finite_y = y_values[selected]
        finite_x = finite_x[np.isfinite(finite_x)]
        finite_y = finite_y[np.isfinite(finite_y)]
        mean_x = float(np.mean(finite_x)) if finite_x.size else math.nan
        mean_y = float(np.mean(finite_y)) if finite_y.size else math.nan
        slopes.append((mean_x, mean_y))
    return np.asarray(slopes, dtype=float)


def _masked_axis_gradient(
    values: np.ndarray,
    valid: np.ndarray,
    spacing: float,
    axis: int,
) -> np.ndarray:
    previous = np.full_like(values, np.nan, dtype=float)
    following = np.full_like(values, np.nan, dtype=float)
    previous_two = np.full_like(values, np.nan, dtype=float)
    following_two = np.full_like(values, np.nan, dtype=float)
    previous_valid = np.zeros_like(valid, dtype=bool)
    following_valid = np.zeros_like(valid, dtype=bool)
    previous_two_valid = np.zeros_like(valid, dtype=bool)
    following_two_valid = np.zeros_like(valid, dtype=bool)

    if axis == 0:
        previous[1:, :] = values[:-1, :]
        following[:-1, :] = values[1:, :]
        previous_two[2:, :] = values[:-2, :]
        following_two[:-2, :] = values[2:, :]
        previous_valid[1:, :] = valid[:-1, :]
        following_valid[:-1, :] = valid[1:, :]
        previous_two_valid[2:, :] = valid[:-2, :]
        following_two_valid[:-2, :] = valid[2:, :]
    elif axis == 1:
        previous[:, 1:] = values[:, :-1]
        following[:, :-1] = values[:, 1:]
        previous_two[:, 2:] = values[:, :-2]
        following_two[:, :-2] = values[:, 2:]
        previous_valid[:, 1:] = valid[:, :-1]
        following_valid[:, :-1] = valid[:, 1:]
        previous_two_valid[:, 2:] = valid[:, :-2]
        following_two_valid[:, :-2] = valid[:, 2:]
    else:  # pragma: no cover - private caller is limited to two axes
        raise GeometricShackHartmannError("axis must be 0 or 1.")

    gradient = np.full_like(values, np.nan, dtype=float)
    central = valid & previous_valid & following_valid
    gradient[central] = (following[central] - previous[central]) / (
        2.0 * spacing
    )

    forward = valid & ~previous_valid & following_valid
    forward_second_order = forward & following_two_valid
    gradient[forward_second_order] = (
        -3.0 * values[forward_second_order]
        + 4.0 * following[forward_second_order]
        - following_two[forward_second_order]
    ) / (2.0 * spacing)
    forward_first_order = forward & ~following_two_valid
    gradient[forward_first_order] = (
        following[forward_first_order] - values[forward_first_order]
    ) / spacing

    backward = valid & previous_valid & ~following_valid
    backward_second_order = backward & previous_two_valid
    gradient[backward_second_order] = (
        3.0 * values[backward_second_order]
        - 4.0 * previous[backward_second_order]
        + previous_two[backward_second_order]
    ) / (2.0 * spacing)
    backward_first_order = backward & ~previous_two_valid
    gradient[backward_first_order] = (
        values[backward_first_order] - previous[backward_first_order]
    ) / spacing
    return gradient


def _validated_residual(
    residual_opd_m: object,
    geometry: ShackHartmannGeometry,
) -> np.ndarray:
    raw = np.asarray(residual_opd_m)
    if np.iscomplexobj(raw):
        raise GeometricShackHartmannError(
            "residual_opd_m must contain real metre values."
        )
    try:
        result = np.array(raw, dtype=float, copy=True)
    except (TypeError, ValueError) as exc:
        raise GeometricShackHartmannError(
            "residual_opd_m must contain real metre values."
        ) from exc
    if result.shape != geometry.pupil_shape:
        raise GeometricShackHartmannError(
            f"residual_opd_m shape {result.shape} does not match "
            f"{geometry.pupil_shape}."
        )
    pupil = np.asarray(geometry.pupil_mask, dtype=bool)
    if not np.all(np.isfinite(result[pupil])):
        raise GeometricShackHartmannError(
            "residual_opd_m must be finite inside geometry.pupil_mask."
        )
    result[~pupil] = 0.0
    return result


def _stream_metadata(random_streams: RandomStreams) -> tuple[int, str]:
    try:
        root_seed = random_streams.root_seed
        scheme_id = random_streams.derivation_scheme_id
    except AttributeError as exc:
        raise GeometricShackHartmannError(
            "random_streams must implement the RandomStreams contract."
        ) from exc
    if type(root_seed) is not int or root_seed < 0:
        raise GeometricShackHartmannError(
            "random_streams.root_seed must be a non-negative integer."
        )
    if not isinstance(scheme_id, str) or not scheme_id:
        raise GeometricShackHartmannError(
            "random_streams.derivation_scheme_id must be a non-empty string."
        )
    return root_seed, scheme_id


def _immutable_reference(value: object, count: int) -> np.ndarray:
    raw = np.asarray(value)
    if np.iscomplexobj(raw):
        raise GeometricShackHartmannError(
            "reference_slopes_rad must contain real values."
        )
    try:
        result = np.array(raw, dtype=float, copy=True)
    except (TypeError, ValueError) as exc:
        raise GeometricShackHartmannError(
            "reference_slopes_rad must contain real values."
        ) from exc
    if result.shape != (count, 2) or not np.all(np.isfinite(result)):
        raise GeometricShackHartmannError(
            "reference_slopes_rad must have shape (n_subapertures, 2) "
            "and contain only finite values."
        )
    contiguous = np.ascontiguousarray(result)
    immutable = np.frombuffer(contiguous.tobytes(order="C"), dtype=contiguous.dtype)
    return immutable.reshape(contiguous.shape)


def _row_ids(subaperture_ids: tuple[str, ...]) -> tuple[str, ...]:
    return tuple(
        row_id
        for subaperture_id in subaperture_ids
        for row_id in (f"{subaperture_id}:x", f"{subaperture_id}:y")
    )


def _calibration_hash(
    geometry: ShackHartmannGeometry,
    reference_slopes_rad: np.ndarray,
    provenance: Provenance,
) -> str:
    return stable_hash(
        {
            "schema": "shwfs_ao.geometric_shack_hartmann_calibration.v1",
            "geometry": geometry,
            "reference_slopes_rad": np.asarray(
                reference_slopes_rad,
                dtype=float,
            ),
            "subaperture_ids": geometry.subaperture_ids,
            "row_ids": _row_ids(geometry.subaperture_ids),
            "measurement_unit": "rad_wavefront_slope",
            "algorithm": "masked_finite_difference_mean_v1",
            "provenance": provenance.to_record(),
        },
        namespace="geometric_shack_hartmann_calibration",
    )


def _provenance(provenance: Provenance | None) -> Provenance:
    if provenance is None:
        return Provenance(
            source_class="synthetic_assumed",
            source_note=(
                "Explicit local-slope reference for the native geometric "
                "Shack-Hartmann sensor."
            ),
            references=("algorithm=masked_finite_difference_mean_v1",),
        )
    if not isinstance(provenance, Provenance):
        raise GeometricShackHartmannError(
            "provenance must be a Provenance or None."
        )
    return provenance


__all__ = (
    "GeometricShackHartmannError",
    "GeometricShackHartmannCalibration",
    "NativeGeometricShackHartmannSensor",
    "GeometricShackHartmannSensor",
    "numerical_gradient",
    "mean_subaperture_slopes",
)
