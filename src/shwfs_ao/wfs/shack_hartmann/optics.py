"""SH-WFS optical-result construction and strict backend boundary checks."""

from __future__ import annotations

from collections.abc import Sequence

import numpy as np

from ...core.hashing import detector_plane_sampling_hash
from ...core.types import DetectorPlaneSampling, SpotIntensityResult
from .geometry import ShackHartmannGeometry


__all__ = (
    "ShackHartmannOpticsError",
    "make_detector_plane_sampling",
    "validate_spot_intensity_result",
    "validate_optics_backend_result",
)


class ShackHartmannOpticsError(ValueError):
    """Raised when an optics backend violates geometry or sampling identity."""


def make_detector_plane_sampling(
    *,
    window_shape_px: tuple[int, int],
    pixel_scale_rad: tuple[float, float],
    reference_pixel_xy: tuple[float, float],
) -> DetectorPlaneSampling:
    """Construct a detector sampling with its canonical content hash.

    ``pixel_scale_rad`` is ordered ``(x/column, y/row)`` and
    ``reference_pixel_xy`` identifies the zero-angle FFT sample in the window.
    """

    return DetectorPlaneSampling(
        window_shape_px=window_shape_px,
        pixel_scale_rad=pixel_scale_rad,
        reference_pixel_xy=reference_pixel_xy,
        sampling_hash=detector_plane_sampling_hash(
            window_shape_px=window_shape_px,
            pixel_scale_rad=pixel_scale_rad,
            reference_pixel_xy=reference_pixel_xy,
        ),
    )


def validate_spot_intensity_result(
    result: SpotIntensityResult,
    geometry: ShackHartmannGeometry | Sequence[str],
    *,
    sampling: DetectorPlaneSampling | None = None,
) -> SpotIntensityResult:
    """Require exact subaperture identity/order and optional detector sampling.

    This check belongs at every alternate-backend boundary.  Set equality is
    intentionally insufficient: serialized calibrations depend on the exact
    geometry order, so a backend may not reorder otherwise valid IDs.
    """

    if not isinstance(result, SpotIntensityResult):
        raise ShackHartmannOpticsError(
            "Optics backend must return a SpotIntensityResult."
        )
    expected_ids = _expected_ids(geometry)
    actual_ids = tuple(result.subaperture_ids)
    if len(actual_ids) != len(set(actual_ids)):
        raise ShackHartmannOpticsError(
            "Optics backend returned duplicate subaperture IDs."
        )
    actual_set = set(actual_ids)
    expected_set = set(expected_ids)
    if actual_set != expected_set:
        missing = tuple(identifier for identifier in expected_ids if identifier not in actual_set)
        unexpected = tuple(identifier for identifier in actual_ids if identifier not in expected_set)
        raise ShackHartmannOpticsError(
            "Optics backend subaperture IDs do not match geometry; "
            f"missing={missing}, unexpected={unexpected}."
        )
    if actual_ids != expected_ids:
        raise ShackHartmannOpticsError(
            "Optics backend returned reordered subaperture IDs."
        )
    if np.any(result.relative_throughput > 1.0):
        raise ShackHartmannOpticsError(
            "Optics backend relative_throughput must contain detector-window "
            "capture fractions in [0, 1]."
        )
    if sampling is not None:
        if not isinstance(sampling, DetectorPlaneSampling):
            raise ShackHartmannOpticsError(
                "sampling must be a DetectorPlaneSampling or None."
            )
        if result.sampling.sampling_hash != sampling.sampling_hash:
            raise ShackHartmannOpticsError(
                "Optics backend detector sampling does not match calibration."
            )
    return result


def validate_optics_backend_result(
    result: SpotIntensityResult,
    geometry: ShackHartmannGeometry | Sequence[str],
    *,
    sampling: DetectorPlaneSampling | None = None,
) -> SpotIntensityResult:
    """Readable alias for :func:`validate_spot_intensity_result`."""

    return validate_spot_intensity_result(result, geometry, sampling=sampling)


def _expected_ids(
    geometry: ShackHartmannGeometry | Sequence[str],
) -> tuple[str, ...]:
    if isinstance(geometry, ShackHartmannGeometry):
        return geometry.subaperture_ids
    if isinstance(geometry, (str, bytes)):
        raise ShackHartmannOpticsError(
            "geometry must be a ShackHartmannGeometry or ordered ID sequence."
        )
    try:
        identifiers = tuple(geometry)
    except TypeError as exc:
        raise ShackHartmannOpticsError(
            "geometry must be a ShackHartmannGeometry or ordered ID sequence."
        ) from exc
    if not identifiers or any(
        not isinstance(identifier, str) or not identifier
        for identifier in identifiers
    ):
        raise ShackHartmannOpticsError(
            "Expected subaperture IDs must be non-empty strings."
        )
    if len(identifiers) != len(set(identifiers)):
        raise ShackHartmannOpticsError(
            "Expected subaperture IDs must not contain duplicates."
        )
    return identifiers
