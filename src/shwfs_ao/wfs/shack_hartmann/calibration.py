"""Deterministic detector-level Shack--Hartmann reference calibration.

Reference centroids are produced by the same optical, detector-response, and
centroid path used for measurements.  Temporal shot and read noise are never
drawn here.  The historical per-frame PRNU mode is made replayable by deriving
one keyed ``calibration`` child seed per retained subaperture.
"""

from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Literal, cast

import numpy as np

from ...core.hashing import component_config_hash, stable_hash
from ...core.protocols import RandomStreams, ShackHartmannOpticsBackend
from ...core.provenance import Provenance
from ...core.types import DetectorPlaneSampling, SpotIntensityResult
from ...detector.centroid import CentroidConfig, estimate_centroid
from ...detector.config import DetectorConfig
from ...detector.effects import apply_detector_effects
from ...detector.random import DetectorRealization
from .geometry import ShackHartmannGeometry
from .optics import validate_spot_intensity_result


class ShackHartmannCalibrationError(ValueError):
    """Raised when calibration inputs or stored metadata disagree."""


@dataclass(frozen=True)
class ShackHartmannCalibration:
    """Immutable zero-phase detector-level reference calibration."""

    __hash_schema_id__ = "shwfs_ao.wfs.ShackHartmannCalibration.v1"

    geometry: ShackHartmannGeometry
    reference_centroids_px: np.ndarray
    wfs_wavelength_m: float
    subaperture_ids: tuple[str, ...]
    row_ids: tuple[str, ...]
    measurement_unit: Literal["pixel"]
    detector_sampling: DetectorPlaneSampling
    detector_config: DetectorConfig
    centroid_config: CentroidConfig
    detector_realization_hash: str
    config_hash: str
    provenance: Provenance

    def __post_init__(self) -> None:
        if not isinstance(self.geometry, ShackHartmannGeometry):
            raise ShackHartmannCalibrationError(
                "geometry must be a ShackHartmannGeometry."
            )
        subaperture_ids = _ids(self.subaperture_ids, label="subaperture_ids")
        if subaperture_ids != self.geometry.subaperture_ids:
            raise ShackHartmannCalibrationError(
                "subaperture_ids must exactly match geometry.subaperture_ids."
            )
        expected_rows = row_ids_for_subapertures(subaperture_ids)
        row_ids = _ids(self.row_ids, label="row_ids")
        if row_ids != expected_rows:
            raise ShackHartmannCalibrationError(
                "row_ids must use S:x, S:y order for every geometry subaperture."
            )
        reference_centroids_px = _immutable_centroids(
            self.reference_centroids_px,
            len(subaperture_ids),
        )
        wfs_wavelength_m = _positive_float(
            self.wfs_wavelength_m,
            label="wfs_wavelength_m",
        )
        if self.measurement_unit != "pixel":
            raise ShackHartmannCalibrationError(
                "measurement_unit must be 'pixel'."
            )
        if not isinstance(self.detector_sampling, DetectorPlaneSampling):
            raise ShackHartmannCalibrationError(
                "detector_sampling must be a DetectorPlaneSampling."
            )
        if not isinstance(self.detector_config, DetectorConfig):
            raise ShackHartmannCalibrationError(
                "detector_config must be a DetectorConfig."
            )
        if not isinstance(self.centroid_config, CentroidConfig):
            raise ShackHartmannCalibrationError(
                "centroid_config must be a CentroidConfig."
            )
        detector_realization_hash = _nonempty_string(
            self.detector_realization_hash,
            label="detector_realization_hash",
        )
        if not isinstance(self.provenance, Provenance):
            raise ShackHartmannCalibrationError(
                "provenance must be a Provenance."
            )
        config_hash = _nonempty_string(self.config_hash, label="config_hash")
        expected_hash = shack_hartmann_calibration_hash(
            geometry=self.geometry,
            reference_centroids_px=reference_centroids_px,
            wfs_wavelength_m=wfs_wavelength_m,
            subaperture_ids=subaperture_ids,
            row_ids=row_ids,
            detector_sampling=self.detector_sampling,
            detector_config=self.detector_config,
            centroid_config=self.centroid_config,
            detector_realization_hash=detector_realization_hash,
            provenance=self.provenance,
        )
        if config_hash != expected_hash:
            raise ShackHartmannCalibrationError(
                "config_hash does not match the complete calibration content."
            )

        object.__setattr__(self, "reference_centroids_px", reference_centroids_px)
        object.__setattr__(self, "wfs_wavelength_m", wfs_wavelength_m)
        object.__setattr__(self, "subaperture_ids", subaperture_ids)
        object.__setattr__(self, "row_ids", row_ids)
        object.__setattr__(self, "measurement_unit", "pixel")
        object.__setattr__(
            self,
            "detector_realization_hash",
            detector_realization_hash,
        )
        object.__setattr__(self, "config_hash", config_hash)


@dataclass(frozen=True)
class _LegacyCalibrationPlan:
    seeds: tuple[int | None, ...]
    provenance_references: tuple[str, ...]


def row_ids_for_subapertures(
    subaperture_ids: tuple[str, ...],
) -> tuple[str, ...]:
    """Return the canonical interleaved x/y measurement-row layout."""

    ids = _ids(subaperture_ids, label="subaperture_ids")
    return tuple(
        row_id
        for subaperture_id in ids
        for row_id in (f"{subaperture_id}:x", f"{subaperture_id}:y")
    )


def calibrate_zero_phase_reference(
    geometry: ShackHartmannGeometry,
    optics_backend: ShackHartmannOpticsBackend,
    detector_config: DetectorConfig,
    centroid_config: CentroidConfig,
    detector_realization: DetectorRealization,
    *,
    wfs_wavelength_m: float,
    random_streams: RandomStreams,
    provenance: Provenance | None = None,
    zero_phase_spots: SpotIntensityResult | None = None,
) -> ShackHartmannCalibration:
    """Build a zero-OPD reference without advancing runtime noise streams.

    ``zero_phase_spots`` is an optional already-computed backend result used by
    the sensor factory to avoid a second propagation.  It is validated exactly
    as a result produced inside this function would be.
    """

    if not isinstance(geometry, ShackHartmannGeometry):
        raise ShackHartmannCalibrationError(
            "geometry must be a ShackHartmannGeometry."
        )
    if not isinstance(detector_config, DetectorConfig):
        raise ShackHartmannCalibrationError(
            "detector_config must be a DetectorConfig."
        )
    if not isinstance(centroid_config, CentroidConfig):
        raise ShackHartmannCalibrationError(
            "centroid_config must be a CentroidConfig."
        )
    wavelength = _positive_float(wfs_wavelength_m, label="wfs_wavelength_m")
    _validate_realization(detector_config, detector_realization, random_streams)
    backend_name, backend_hash = _backend_identity(optics_backend)
    _validate_backend_declared_context(optics_backend, geometry, wavelength)

    if zero_phase_spots is None:
        try:
            spots = optics_backend.spot_intensities(
                np.zeros(geometry.pupil_shape, dtype=float)
            )
        except Exception as exc:
            raise ShackHartmannCalibrationError(
                "optics backend failed during zero-phase reference propagation."
            ) from exc
    else:
        spots = zero_phase_spots
    declared_sampling = getattr(
        optics_backend,
        "detector_sampling",
        getattr(optics_backend, "sampling", None),
    )
    if declared_sampling is not None and not isinstance(
        declared_sampling,
        DetectorPlaneSampling,
    ):
        raise ShackHartmannCalibrationError(
            "optics backend declared sampling must be DetectorPlaneSampling."
        )
    try:
        validate_spot_intensity_result(
            spots,
            geometry,
            sampling=declared_sampling,
        )
    except (TypeError, ValueError) as exc:
        raise ShackHartmannCalibrationError(str(exc)) from exc

    if detector_realization.window_shape_px != spots.sampling.window_shape_px:
        raise ShackHartmannCalibrationError(
            "detector realization shape does not match backend detector sampling."
        )

    legacy_plan = _legacy_calibration_plan(
        geometry=geometry,
        sampling=spots.sampling,
        detector_config=detector_config,
        centroid_config=centroid_config,
        backend_config_hash=backend_hash,
        random_streams=random_streams,
    )
    reference_centroids = []
    for index, (subaperture_id, normalized_spot) in enumerate(
        zip(spots.subaperture_ids, spots.unit_sum_spots)
    ):
        transmitted_spot = (
            normalized_spot * float(spots.relative_throughput[index])
        )
        scoped_streams = random_streams.scoped(
            "shack_hartmann.reference.detector",
            key=(subaperture_id,),
        )
        try:
            frame = apply_detector_effects(
                transmitted_spot,
                detector_config,
                detector_realization,
                random_streams=scoped_streams,
                include_noise=False,
                legacy_seed=legacy_plan.seeds[index],
            )
            estimate = estimate_centroid(frame.image_e, centroid_config)
        except (TypeError, ValueError) as exc:
            raise ShackHartmannCalibrationError(
                f"reference detector path failed for {subaperture_id!r}: {exc}"
            ) from exc
        if not estimate.finite:
            raise ShackHartmannCalibrationError(
                f"reference centroid for {subaperture_id!r} is not finite."
            )
        reference_centroids.append((estimate.x_px, estimate.y_px))

    references = (
        f"optics_backend_name={backend_name}",
        f"optics_backend_config_hash={backend_hash}",
        f"detector_realization_hash={detector_realization.realization_hash}",
        f"detector_root_seed={detector_realization.root_seed}",
        *legacy_plan.provenance_references,
    )
    resolved_provenance = _calibration_provenance(provenance, references)
    reference_array = np.asarray(reference_centroids, dtype=float)
    row_ids = row_ids_for_subapertures(geometry.subaperture_ids)
    config_hash = shack_hartmann_calibration_hash(
        geometry=geometry,
        reference_centroids_px=reference_array,
        wfs_wavelength_m=wavelength,
        subaperture_ids=geometry.subaperture_ids,
        row_ids=row_ids,
        detector_sampling=spots.sampling,
        detector_config=detector_config,
        centroid_config=centroid_config,
        detector_realization_hash=detector_realization.realization_hash,
        provenance=resolved_provenance,
    )
    return ShackHartmannCalibration(
        geometry=geometry,
        reference_centroids_px=reference_array,
        wfs_wavelength_m=wavelength,
        subaperture_ids=geometry.subaperture_ids,
        row_ids=row_ids,
        measurement_unit="pixel",
        detector_sampling=spots.sampling,
        detector_config=detector_config,
        centroid_config=centroid_config,
        detector_realization_hash=detector_realization.realization_hash,
        config_hash=config_hash,
        provenance=resolved_provenance,
    )


def shack_hartmann_calibration_hash(
    *,
    geometry: ShackHartmannGeometry,
    reference_centroids_px: np.ndarray,
    wfs_wavelength_m: float,
    subaperture_ids: tuple[str, ...],
    row_ids: tuple[str, ...],
    detector_sampling: DetectorPlaneSampling,
    detector_config: DetectorConfig,
    centroid_config: CentroidConfig,
    detector_realization_hash: str,
    provenance: Provenance,
) -> str:
    """Hash every configuration and realized datum defining a calibration."""

    return stable_hash(
        {
            "schema": "shwfs_ao.shack_hartmann_calibration.v1",
            "geometry": geometry,
            "reference_centroids_px": np.asarray(
                reference_centroids_px,
                dtype=float,
            ),
            "wfs_wavelength_m": float(wfs_wavelength_m),
            "subaperture_ids": tuple(subaperture_ids),
            "row_ids": tuple(row_ids),
            "measurement_unit": "pixel",
            "detector_sampling_hash": detector_sampling.sampling_hash,
            "detector_config_hash": detector_config.config_hash,
            "centroid_config_hash": component_config_hash(
                "centroid",
                centroid_config,
            ),
            "detector_realization_hash": detector_realization_hash,
            "provenance": provenance.to_record(),
        },
        namespace="shack_hartmann_calibration",
    )


def legacy_calibration_seeds(
    calibration: ShackHartmannCalibration,
    *,
    optics_backend: ShackHartmannOpticsBackend,
    random_streams: RandomStreams,
) -> tuple[int | None, ...]:
    """Re-derive the non-stateful keyed PRNU seeds recorded by calibration."""

    _, backend_hash = _backend_identity(optics_backend)
    plan = _legacy_calibration_plan(
        geometry=calibration.geometry,
        sampling=calibration.detector_sampling,
        detector_config=calibration.detector_config,
        centroid_config=calibration.centroid_config,
        backend_config_hash=backend_hash,
        random_streams=random_streams,
    )
    for reference in plan.provenance_references:
        if reference not in calibration.provenance.references:
            raise ShackHartmannCalibrationError(
                "calibration random scope/key metadata does not match the "
                "supplied RandomStreams provider."
            )
    return plan.seeds


def _legacy_calibration_plan(
    *,
    geometry: ShackHartmannGeometry,
    sampling: DetectorPlaneSampling,
    detector_config: DetectorConfig,
    centroid_config: CentroidConfig,
    backend_config_hash: str,
    random_streams: RandomStreams,
) -> _LegacyCalibrationPlan:
    count = len(geometry.subaperture_ids)
    if (
        detector_config.prnu_mode != "per_frame_legacy"
        or detector_config.prnu_rms <= 0.0
    ):
        return _LegacyCalibrationPlan(
            seeds=tuple(None for _ in range(count)),
            provenance_references=(),
        )

    scope_name = "shack_hartmann.zero_phase_reference"
    scope_key = (
        stable_hash(geometry, namespace="shack_hartmann_geometry"),
        sampling.sampling_hash,
        detector_config.config_hash,
        component_config_hash("centroid", centroid_config),
        backend_config_hash,
    )
    try:
        scoped = random_streams.scoped(scope_name, key=scope_key)
    except (AttributeError, TypeError, ValueError) as exc:
        raise ShackHartmannCalibrationError(
            "random_streams could not create the calibration scope."
        ) from exc

    seeds: list[int | None] = []
    references: list[str] = [
        f"calibration_random_scope={scope_name}",
        "calibration_random_scope_key="
        + stable_hash(scope_key, namespace="calibration_scope_key"),
    ]
    for subaperture_id in geometry.subaperture_ids:
        key = ("legacy_prnu", subaperture_id)
        try:
            generator = scoped.keyed_generator("calibration", key=key)
            stream_id = scoped.stream_id("calibration", key=key)
        except (AttributeError, TypeError, ValueError) as exc:
            raise ShackHartmannCalibrationError(
                "random_streams could not derive a keyed calibration child."
            ) from exc
        seed = int(generator.integers(0, 2**63 - 1))
        seeds.append(seed)
        references.extend(
            (
                f"calibration_random_key={subaperture_id}:legacy_prnu",
                f"calibration_random_stream_id={subaperture_id}:{stream_id}",
                f"calibration_legacy_seed={subaperture_id}:{seed}",
            )
        )
    return _LegacyCalibrationPlan(tuple(seeds), tuple(references))


def _validate_realization(
    detector_config: DetectorConfig,
    detector_realization: DetectorRealization,
    random_streams: RandomStreams,
) -> None:
    if not isinstance(detector_realization, DetectorRealization):
        raise ShackHartmannCalibrationError(
            "detector_realization must be a DetectorRealization."
        )
    if detector_realization.config_hash != detector_config.realization_config_hash:
        raise ShackHartmannCalibrationError(
            "detector realization configuration does not match detector_config."
        )
    try:
        root_seed = random_streams.root_seed
    except AttributeError as exc:
        raise ShackHartmannCalibrationError(
            "random_streams must implement the RandomStreams contract."
        ) from exc
    if detector_realization.root_seed != root_seed:
        raise ShackHartmannCalibrationError(
            "detector realization root seed does not match random_streams."
        )


def _backend_identity(
    optics_backend: ShackHartmannOpticsBackend,
) -> tuple[str, str]:
    try:
        backend_name = optics_backend.backend_name
        backend_hash = optics_backend.config_hash
    except AttributeError as exc:
        raise ShackHartmannCalibrationError(
            "optics_backend must implement the ShackHartmannOpticsBackend contract."
        ) from exc
    return (
        _nonempty_string(backend_name, label="optics_backend.backend_name"),
        _nonempty_string(backend_hash, label="optics_backend.config_hash"),
    )


def _validate_backend_declared_context(
    optics_backend: ShackHartmannOpticsBackend,
    geometry: ShackHartmannGeometry,
    wavelength_m: float,
) -> None:
    declared_geometry = getattr(optics_backend, "geometry", None)
    if declared_geometry is not None:
        if not isinstance(declared_geometry, ShackHartmannGeometry):
            raise ShackHartmannCalibrationError(
                "optics_backend.geometry must be a ShackHartmannGeometry."
            )
        if stable_hash(
            declared_geometry,
            namespace="shack_hartmann_geometry",
        ) != stable_hash(geometry, namespace="shack_hartmann_geometry"):
            raise ShackHartmannCalibrationError(
                "optics_backend geometry does not match calibration geometry."
            )
    declared_wavelength = getattr(optics_backend, "wfs_wavelength_m", None)
    if declared_wavelength is not None and not math.isclose(
        float(declared_wavelength),
        wavelength_m,
        rel_tol=0.0,
        abs_tol=0.0,
    ):
        raise ShackHartmannCalibrationError(
            "optics_backend wavelength does not match wfs_wavelength_m."
        )


def _calibration_provenance(
    provenance: Provenance | None,
    references: tuple[str, ...],
) -> Provenance:
    base = provenance
    if base is None:
        base = Provenance(
            source_class="synthetic_assumed",
            source_note=(
                "Deterministic zero-phase Shack-Hartmann reference produced "
                "by the canonical optical and detector pipeline."
            ),
        )
    if not isinstance(base, Provenance):
        raise ShackHartmannCalibrationError(
            "provenance must be a Provenance or None."
        )
    merged = tuple(dict.fromkeys((*base.references, *references)))
    return Provenance(
        source_class=base.source_class,
        source_note=base.source_note,
        source_id=base.source_id,
        url=base.url,
        access_time=base.access_time,
        fallback_used=base.fallback_used,
        references=merged,
    )


def _immutable_centroids(value: object, count: int) -> np.ndarray:
    raw = np.asarray(value)
    if np.iscomplexobj(raw):
        raise ShackHartmannCalibrationError(
            "reference_centroids_px must contain real values."
        )
    try:
        result = np.array(raw, dtype=float, copy=True)
    except (TypeError, ValueError) as exc:
        raise ShackHartmannCalibrationError(
            "reference_centroids_px must contain real values."
        ) from exc
    if result.shape != (count, 2) or not np.all(np.isfinite(result)):
        raise ShackHartmannCalibrationError(
            "reference_centroids_px must have shape (n_subapertures, 2) "
            "and contain only finite values."
        )
    contiguous = np.ascontiguousarray(result)
    immutable = np.frombuffer(contiguous.tobytes(order="C"), dtype=contiguous.dtype)
    return immutable.reshape(contiguous.shape)


def _ids(value: object, *, label: str) -> tuple[str, ...]:
    if not isinstance(value, tuple) or not value:
        raise ShackHartmannCalibrationError(
            f"{label} must be a non-empty tuple of unique strings."
        )
    if any(not isinstance(item, str) or not item for item in value):
        raise ShackHartmannCalibrationError(
            f"{label} must be a non-empty tuple of unique strings."
        )
    if len(value) != len(set(value)):
        raise ShackHartmannCalibrationError(f"{label} must not contain duplicates.")
    return cast(tuple[str, ...], value)


def _positive_float(value: object, *, label: str) -> float:
    if isinstance(value, (bool, np.bool_)):
        raise ShackHartmannCalibrationError(f"{label} must be positive and finite.")
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise ShackHartmannCalibrationError(
            f"{label} must be positive and finite."
        ) from exc
    if not math.isfinite(result) or result <= 0.0:
        raise ShackHartmannCalibrationError(f"{label} must be positive and finite.")
    return result


def _nonempty_string(value: object, *, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ShackHartmannCalibrationError(f"{label} must be a non-empty string.")
    return value


__all__ = (
    "ShackHartmannCalibrationError",
    "ShackHartmannCalibration",
    "row_ids_for_subapertures",
    "calibrate_zero_phase_reference",
    "shack_hartmann_calibration_hash",
    "legacy_calibration_seeds",
)
