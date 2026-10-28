"""Canonical detector-level Shack--Hartmann wavefront sensor."""

from __future__ import annotations

import math

import numpy as np

from ...core.hashing import component_config_hash, stable_hash
from ...core.protocols import RandomStreams, ShackHartmannOpticsBackend
from ...core.provenance import Provenance
from ...core.types import (
    DetectorFrame,
    DetectorTelemetry,
    MeasurementVector,
    WfsMeasurement,
)
from ...detector.centroid import CentroidConfig, estimate_centroid
from ...detector.config import DetectorConfig
from ...detector.effects import (
    apply_detector_effects,
    apply_legacy_detector_effects,
)
from ...detector.random import DetectorRealization
from ...detector.validity import (
    DEFAULT_CENTROID_VALIDITY,
    CentroidValidityConfig,
    centroid_quality,
    evaluate_centroid_validity,
)
from .calibration import (
    ShackHartmannCalibration,
    ShackHartmannCalibrationError,
    calibrate_zero_phase_reference,
    legacy_calibration_seeds,
)
from .geometry import ShackHartmannGeometry
from .optics import validate_spot_intensity_result


class ShackHartmannMeasurementError(ValueError):
    """Raised when measurement state or a backend result is inconsistent."""


class DetectorShackHartmannSensor:
    """Detector-level WFS with one fixed realization and reference calibration.

    Instances are normally created with :meth:`calibrate`.  Runtime temporal
    randomness always comes from the provider passed to :meth:`measure`; the
    sensor retains no generator and constructs no hidden provider.
    """

    def __init__(
        self,
        optics_backend: ShackHartmannOpticsBackend,
        calibration: ShackHartmannCalibration,
        detector_realization: DetectorRealization,
        *,
        validity_config: CentroidValidityConfig = DEFAULT_CENTROID_VALIDITY,
        calibration_legacy_seeds: tuple[int | None, ...] | None = None,
    ) -> None:
        if not isinstance(calibration, ShackHartmannCalibration):
            raise ShackHartmannMeasurementError(
                "calibration must be a ShackHartmannCalibration."
            )
        if not isinstance(detector_realization, DetectorRealization):
            raise ShackHartmannMeasurementError(
                "detector_realization must be a DetectorRealization."
            )
        if not isinstance(validity_config, CentroidValidityConfig):
            raise ShackHartmannMeasurementError(
                "validity_config must be a CentroidValidityConfig."
            )
        backend_name, backend_hash = _backend_identity(optics_backend)
        if (
            f"optics_backend_name={backend_name}"
            not in calibration.provenance.references
        ):
            raise ShackHartmannMeasurementError(
                "optics backend name does not match calibration metadata."
            )
        if (
            f"optics_backend_config_hash={backend_hash}"
            not in calibration.provenance.references
        ):
            raise ShackHartmannMeasurementError(
                "optics backend config hash does not match calibration metadata."
            )
        if detector_realization.realization_hash != (
            calibration.detector_realization_hash
        ):
            raise ShackHartmannMeasurementError(
                "owned detector realization hash does not match calibration."
            )
        if detector_realization.config_hash != (
            calibration.detector_config.realization_config_hash
        ):
            raise ShackHartmannMeasurementError(
                "owned detector realization config does not match calibration."
            )
        if detector_realization.window_shape_px != (
            calibration.detector_sampling.window_shape_px
        ):
            raise ShackHartmannMeasurementError(
                "owned detector realization shape does not match calibration."
            )
        _validate_backend_context(
            optics_backend,
            calibration.geometry,
            calibration.wfs_wavelength_m,
        )

        seeds = _resolved_calibration_seeds(
            calibration,
            calibration_legacy_seeds,
        )
        self._optics_backend = optics_backend
        self._calibration = calibration
        self._detector_realization = detector_realization
        self._validity_config = validity_config
        self._calibration_legacy_seeds = seeds
        self._backend_name = backend_name
        self._backend_config_hash = backend_hash
        self._config_hash = component_config_hash(
            "detector_shack_hartmann_sensor",
            {
                "calibration_hash": calibration.config_hash,
                "backend_name": backend_name,
                "backend_config_hash": backend_hash,
                "validity_config": validity_config,
            },
        )

    @classmethod
    def calibrate(
        cls,
        geometry: ShackHartmannGeometry,
        optics_backend: ShackHartmannOpticsBackend,
        detector_config: DetectorConfig,
        *,
        wfs_wavelength_m: float,
        random_streams: RandomStreams,
        centroid_config: CentroidConfig | None = None,
        validity_config: CentroidValidityConfig = DEFAULT_CENTROID_VALIDITY,
        detector_realization: DetectorRealization | None = None,
        provenance: Provenance | None = None,
        realization_index: int = 0,
    ) -> DetectorShackHartmannSensor:
        """Calibrate zero phase and return a sensor owning that realization."""

        if not isinstance(geometry, ShackHartmannGeometry):
            raise ShackHartmannMeasurementError(
                "geometry must be a ShackHartmannGeometry."
            )
        if not isinstance(detector_config, DetectorConfig):
            raise ShackHartmannMeasurementError(
                "detector_config must be a DetectorConfig."
            )
        resolved_centroid = CentroidConfig() if centroid_config is None else centroid_config
        if not isinstance(resolved_centroid, CentroidConfig):
            raise ShackHartmannMeasurementError(
                "centroid_config must be a CentroidConfig or None."
            )
        _backend_identity(optics_backend)
        _validate_backend_context(optics_backend, geometry, wfs_wavelength_m)
        try:
            zero_spots = optics_backend.spot_intensities(
                np.zeros(geometry.pupil_shape, dtype=float)
            )
            validate_spot_intensity_result(zero_spots, geometry)
        except (AttributeError, TypeError, ValueError) as exc:
            raise ShackHartmannMeasurementError(
                f"zero-phase optics result is invalid: {exc}"
            ) from exc

        realization = detector_realization
        if realization is None:
            try:
                realization = DetectorRealization.create(
                    detector_config,
                    zero_spots.sampling.window_shape_px,
                    random_streams=random_streams,
                    realization_index=realization_index,
                )
            except (TypeError, ValueError) as exc:
                raise ShackHartmannMeasurementError(
                    f"detector realization creation failed: {exc}"
                ) from exc
        try:
            calibration = calibrate_zero_phase_reference(
                geometry,
                optics_backend,
                detector_config,
                resolved_centroid,
                realization,
                wfs_wavelength_m=wfs_wavelength_m,
                random_streams=random_streams,
                provenance=provenance,
                zero_phase_spots=zero_spots,
            )
            seeds = legacy_calibration_seeds(
                calibration,
                optics_backend=optics_backend,
                random_streams=random_streams,
            )
        except ShackHartmannCalibrationError as exc:
            raise ShackHartmannMeasurementError(str(exc)) from exc
        return cls(
            optics_backend,
            calibration,
            realization,
            validity_config=validity_config,
            calibration_legacy_seeds=seeds,
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
    def calibration(self) -> ShackHartmannCalibration:
        return self._calibration

    @property
    def detector_realization(self) -> DetectorRealization:
        return self._detector_realization

    @property
    def optics_backend(self) -> ShackHartmannOpticsBackend:
        return self._optics_backend

    @property
    def validity_config(self) -> CentroidValidityConfig:
        return self._validity_config

    def measure(
        self,
        residual_opd_m: np.ndarray,
        *,
        random_streams: RandomStreams,
        include_noise: bool,
    ) -> WfsMeasurement:
        """Measure reference-subtracted x/y detector shifts in pixels."""

        return self._measure(
            residual_opd_m,
            random_streams=random_streams,
            include_noise=include_noise,
            compatibility_mode=None,
            ordered_legacy_seeds=None,
            apply_quality_override=None,
        )

    def _measure_legacy(
        self,
        residual_opd_m: np.ndarray,
        *,
        random_streams: RandomStreams,
        include_noise: bool,
        compatibility_mode: str,
        ordered_legacy_seeds: tuple[int, ...] | None,
    ) -> WfsMeasurement:
        """Canonical implementation entry for frozen installed adapters.

        The compatibility entry keeps legacy seed order and detector bypass
        semantics out of the public sensor contract.  Optics, detector
        application, centroiding, reference subtraction, validity, telemetry,
        and row construction still execute in this canonical owner.
        """

        if compatibility_mode not in {"low_level", "configured"}:
            raise ShackHartmannMeasurementError(
                "compatibility_mode must be 'low_level' or 'configured'."
            )
        count = len(self.subaperture_ids)
        if ordered_legacy_seeds is not None:
            if (
                not isinstance(ordered_legacy_seeds, tuple)
                or len(ordered_legacy_seeds) != count
                or any(type(seed) is not int or seed < 0 for seed in ordered_legacy_seeds)
            ):
                raise ShackHartmannMeasurementError(
                    "ordered_legacy_seeds must contain one non-negative integer "
                    "per subaperture."
                )
        requires_seeds = bool(
            compatibility_mode == "low_level"
            or (
                bool(include_noise)
                and self._calibration.detector_config.prnu_mode
                == "per_frame_legacy"
            )
        )
        if requires_seeds != (ordered_legacy_seeds is not None):
            raise ShackHartmannMeasurementError(
                "ordered legacy seeds do not match the compatibility detector path."
            )
        apply_quality = bool(
            compatibility_mode == "configured"
            and bool(include_noise)
            and self._calibration.detector_config.photons_per_subap_frame
            is not None
        )
        return self._measure(
            residual_opd_m,
            random_streams=random_streams,
            include_noise=include_noise,
            compatibility_mode=compatibility_mode,
            ordered_legacy_seeds=ordered_legacy_seeds,
            apply_quality_override=apply_quality,
        )

    def _measure(
        self,
        residual_opd_m: np.ndarray,
        *,
        random_streams: RandomStreams,
        include_noise: bool,
        compatibility_mode: str | None,
        ordered_legacy_seeds: tuple[int, ...] | None,
        apply_quality_override: bool | None,
    ) -> WfsMeasurement:
        """Execute the canonical detector measurement pipeline."""

        residual = _validated_residual(
            residual_opd_m,
            self.geometry,
        )
        if not isinstance(include_noise, (bool, np.bool_)):
            raise ShackHartmannMeasurementError("include_noise must be a boolean.")
        noisy = bool(include_noise)
        root_seed, scheme_id = _validate_runtime_streams(
            random_streams,
            self._detector_realization,
        )
        self._verify_owned_state()

        try:
            spots = self._optics_backend.spot_intensities(residual)
            validate_spot_intensity_result(
                spots,
                self.geometry,
                sampling=self._calibration.detector_sampling,
            )
        except (AttributeError, TypeError, ValueError) as exc:
            raise ShackHartmannMeasurementError(
                f"runtime optics result is invalid: {exc}"
            ) from exc

        apply_quality = (
            bool(
                self._calibration.detector_config.photons_per_subap_frame
                is not None
            )
            if apply_quality_override is None
            else bool(apply_quality_override)
        )
        centroids: list[tuple[float, float]] = []
        values: list[float] = []
        valid_rows: list[bool] = []
        fluxes: list[float] = []
        valid_subapertures: list[bool] = []
        valid_by_flux: list[bool] = []
        valid_by_snr: list[bool] = []
        valid_by_uncertainty: list[bool] = []
        valid_by_clipping: list[bool] = []
        peak_snr: list[float] = []
        total_snr: list[float] = []
        centroid_sigma: list[float] = []
        clipping: list[float] = []
        frames = []
        runtime_stream_ids: list[str] = []

        for index, (subaperture_id, normalized_spot) in enumerate(
            zip(spots.subaperture_ids, spots.unit_sum_spots)
        ):
            transmitted_spot = (
                normalized_spot * float(spots.relative_throughput[index])
            )
            frame_streams = random_streams.scoped(
                "shack_hartmann.measurement",
                key=(self._calibration.config_hash, subaperture_id),
            )
            legacy_seed = (
                ordered_legacy_seeds[index]
                if ordered_legacy_seeds is not None
                else None
            )
            if (
                compatibility_mode is None
                and self._calibration.detector_config.prnu_mode
                == "per_frame_legacy"
            ):
                if noisy:
                    try:
                        seed_generator = frame_streams.generator(
                            "detector.shot_noise"
                        )
                        legacy_seed = int(
                            seed_generator.integers(0, 2**63 - 1)
                        )
                        runtime_stream_ids.append(
                            frame_streams.stream_id("detector.shot_noise")
                        )
                    except (AttributeError, TypeError, ValueError) as exc:
                        raise ShackHartmannMeasurementError(
                            "random_streams could not supply legacy runtime noise."
                        ) from exc
                else:
                    legacy_seed = self._calibration_legacy_seeds[index]

            try:
                if compatibility_mode == "low_level":
                    frame = apply_legacy_detector_effects(
                        transmitted_spot,
                        self._calibration.detector_config,
                        self._detector_realization,
                        random_streams=frame_streams,
                        legacy_seed=legacy_seed,
                    )
                elif (
                    compatibility_mode == "configured"
                    and not noisy
                    and self._calibration.detector_config.prnu_mode
                    == "per_frame_legacy"
                ):
                    frame = _legacy_ideal_detector_frame(transmitted_spot)
                else:
                    frame = apply_detector_effects(
                        transmitted_spot,
                        self._calibration.detector_config,
                        self._detector_realization,
                        random_streams=frame_streams,
                        include_noise=noisy,
                        legacy_seed=legacy_seed,
                    )
                estimate = estimate_centroid(
                    frame.image_e,
                    self._calibration.centroid_config,
                )
                quality = centroid_quality(
                    transmitted_spot,
                    normalized_spot,
                    self._calibration.detector_config,
                )
                decision = evaluate_centroid_validity(
                    estimate,
                    quality,
                    self._validity_config,
                    apply_quality_criteria=apply_quality,
                )
            except (TypeError, ValueError) as exc:
                raise ShackHartmannMeasurementError(
                    f"measurement failed for {subaperture_id!r}: {exc}"
                ) from exc

            centroid_xy = (
                (estimate.x_px, estimate.y_px)
                if estimate.finite
                else (math.nan, math.nan)
            )
            by_flux = bool(decision.valid_by_flux)
            by_snr = bool(decision.valid_by_snr)
            by_uncertainty = bool(decision.valid_by_uncertainty)
            by_clipping = bool(decision.valid_by_clipping)
            usable = bool(decision.valid)
            if usable:
                reference = self._calibration.reference_centroids_px[index]
                shift_x = estimate.x_px - float(reference[0])
                shift_y = estimate.y_px - float(reference[1])
            else:
                shift_x = math.nan
                shift_y = math.nan

            centroids.append(centroid_xy)
            values.extend((shift_x, shift_y))
            valid_rows.extend((usable, usable))
            fluxes.append(float(np.sum(frame.image_e, dtype=np.float64)))
            valid_subapertures.append(usable)
            valid_by_flux.append(by_flux)
            valid_by_snr.append(by_snr)
            valid_by_uncertainty.append(by_uncertainty)
            valid_by_clipping.append(by_clipping)
            peak_snr.append(float(decision.peak_snr))
            total_snr.append(float(decision.total_snr))
            centroid_sigma.append(float(decision.centroid_sigma_px))
            clipping.append(float(decision.clipping_fraction))
            frames.append(frame)

        vector = MeasurementVector(
            values=np.asarray(values, dtype=float),
            valid_rows=np.asarray(valid_rows, dtype=bool),
            row_ids=self.row_ids,
            measurement_unit="pixel",
        )
        valid_array = np.asarray(valid_subapertures, dtype=bool)
        telemetry = DetectorTelemetry(
            subaperture_ids=self.subaperture_ids,
            centroids_xy_px=np.asarray(centroids, dtype=float),
            reference_centroids_xy_px=self._calibration.reference_centroids_px,
            fluxes_e=np.asarray(fluxes, dtype=float),
            valid_subapertures=valid_array,
            valid_by_flux=np.asarray(valid_by_flux, dtype=bool),
            valid_by_snr=np.asarray(valid_by_snr, dtype=bool),
            valid_by_uncertainty=np.asarray(valid_by_uncertainty, dtype=bool),
            valid_by_clipping=np.asarray(valid_by_clipping, dtype=bool),
            peak_snr=np.asarray(peak_snr, dtype=float),
            total_snr=np.asarray(total_snr, dtype=float),
            centroid_sigma_px=np.asarray(centroid_sigma, dtype=float),
            clipping_fraction=np.asarray(clipping, dtype=float),
            detector_frames=tuple(frames),
            optical_spots=spots,
        )
        metadata = {
            "sensor_config_hash": self.config_hash,
            "calibration_config_hash": self._calibration.config_hash,
            "detector_realization_hash": (
                self._detector_realization.realization_hash
            ),
            "optics_backend_name": self._backend_name,
            "optics_backend_config_hash": self._backend_config_hash,
            "random_root_seed": root_seed,
            "random_derivation_scheme_id": scheme_id,
            "include_noise": noisy,
            "legacy_compatibility_mode": compatibility_mode,
            "legacy_runtime_stream_ids": runtime_stream_ids,
        }
        return WfsMeasurement(
            vector=vector,
            valid_subapertures=valid_array,
            metadata=metadata,
            detector_telemetry=telemetry,
        )

    def _verify_owned_state(self) -> None:
        backend_name, backend_hash = _backend_identity(self._optics_backend)
        if backend_name != self._backend_name:
            raise ShackHartmannMeasurementError(
                "optics backend name changed after calibration."
            )
        if backend_hash != self._backend_config_hash:
            raise ShackHartmannMeasurementError(
                "optics backend config hash changed after calibration."
            )
        if self._detector_realization.realization_hash != (
            self._calibration.detector_realization_hash
        ):
            raise ShackHartmannMeasurementError(
                "detector realization hash changed after calibration."
            )
        _validate_backend_context(
            self._optics_backend,
            self._calibration.geometry,
            self._calibration.wfs_wavelength_m,
        )


# Explicit descriptive alias for call sites that spell out the detector level.
DetectorLevelShackHartmannSensor = DetectorShackHartmannSensor


def _legacy_ideal_detector_frame(intensity: np.ndarray) -> DetectorFrame:
    """Represent the historical configured ``include_noise=False`` bypass."""

    image = np.array(intensity, dtype=float, copy=True)
    zeros = np.zeros(image.shape, dtype=float)
    false_mask = np.zeros(image.shape, dtype=bool)
    return DetectorFrame(
        image_e=image,
        expected_source_e=image,
        expected_background_e=zeros,
        expected_pre_poisson_e=image,
        prnu_response=np.ones(image.shape, dtype=float),
        saturated_mask=false_mask,
        bad_pixel_mask=false_mask,
        negative_clipped_mask=false_mask,
        random_stream_ids={},
    )


def build_detector_shack_hartmann_sensor(
    geometry: ShackHartmannGeometry,
    optics_backend: ShackHartmannOpticsBackend,
    detector_config: DetectorConfig,
    *,
    wfs_wavelength_m: float,
    random_streams: RandomStreams,
    centroid_config: CentroidConfig | None = None,
    validity_config: CentroidValidityConfig = DEFAULT_CENTROID_VALIDITY,
    detector_realization: DetectorRealization | None = None,
    provenance: Provenance | None = None,
    realization_index: int = 0,
) -> DetectorShackHartmannSensor:
    """Functional factory equivalent to ``DetectorShackHartmannSensor.calibrate``."""

    return DetectorShackHartmannSensor.calibrate(
        geometry,
        optics_backend,
        detector_config,
        wfs_wavelength_m=wfs_wavelength_m,
        random_streams=random_streams,
        centroid_config=centroid_config,
        validity_config=validity_config,
        detector_realization=detector_realization,
        provenance=provenance,
        realization_index=realization_index,
    )


def _resolved_calibration_seeds(
    calibration: ShackHartmannCalibration,
    supplied: tuple[int | None, ...] | None,
) -> tuple[int | None, ...]:
    count = len(calibration.subaperture_ids)
    expected: tuple[int | None, ...]
    if (
        calibration.detector_config.prnu_mode == "per_frame_legacy"
        and calibration.detector_config.prnu_rms > 0.0
    ):
        by_id: dict[str, int] = {}
        prefix = "calibration_legacy_seed="
        for reference in calibration.provenance.references:
            if reference.startswith(prefix):
                payload = reference[len(prefix) :]
                try:
                    subaperture_id, seed_text = payload.rsplit(":", 1)
                    seed = int(seed_text)
                except (ValueError, TypeError) as exc:
                    raise ShackHartmannMeasurementError(
                        "invalid calibration legacy-seed metadata."
                    ) from exc
                if seed < 0 or subaperture_id in by_id:
                    raise ShackHartmannMeasurementError(
                        "invalid calibration legacy-seed metadata."
                    )
                by_id[subaperture_id] = seed
        if tuple(by_id) != calibration.subaperture_ids:
            raise ShackHartmannMeasurementError(
                "calibration is missing ordered legacy PRNU seeds."
            )
        expected = tuple(by_id[item] for item in calibration.subaperture_ids)
    else:
        expected = tuple(None for _ in range(count))

    if supplied is None:
        return expected

    if not isinstance(supplied, tuple) or len(supplied) != count:
        raise ShackHartmannMeasurementError(
            "calibration_legacy_seeds must match the subaperture count."
        )
    normalized: list[int | None] = []
    for seed in supplied:
        if seed is not None and (type(seed) is not int or seed < 0):
            raise ShackHartmannMeasurementError(
                "calibration legacy seeds must be non-negative integers or None."
            )
        normalized.append(seed)
    resolved = tuple(normalized)
    if resolved != expected:
        raise ShackHartmannMeasurementError(
            "supplied calibration legacy seeds do not match calibration metadata."
        )
    return resolved


def _validated_residual(
    residual_opd_m: object,
    geometry: ShackHartmannGeometry,
) -> np.ndarray:
    raw = np.asarray(residual_opd_m)
    if np.iscomplexobj(raw):
        raise ShackHartmannMeasurementError(
            "residual_opd_m must contain real metre values."
        )
    try:
        result = np.array(raw, dtype=float, copy=True)
    except (TypeError, ValueError) as exc:
        raise ShackHartmannMeasurementError(
            "residual_opd_m must contain real metre values."
        ) from exc
    if result.shape != geometry.pupil_shape:
        raise ShackHartmannMeasurementError(
            f"residual_opd_m shape {result.shape} does not match "
            f"{geometry.pupil_shape}."
        )
    pupil_mask = np.asarray(geometry.pupil_mask, dtype=bool)
    if not np.all(np.isfinite(result[pupil_mask])):
        raise ShackHartmannMeasurementError(
            "residual_opd_m must be finite inside geometry.pupil_mask."
        )
    result[~pupil_mask] = 0.0
    return result


def _validate_runtime_streams(
    random_streams: RandomStreams,
    realization: DetectorRealization,
) -> tuple[int, str]:
    try:
        root_seed = random_streams.root_seed
        scheme_id = random_streams.derivation_scheme_id
        random_streams.scoped("shack_hartmann.validation", key=())
    except (AttributeError, TypeError, ValueError) as exc:
        raise ShackHartmannMeasurementError(
            "random_streams must implement the RandomStreams contract."
        ) from exc
    if type(root_seed) is not int or root_seed < 0:
        raise ShackHartmannMeasurementError(
            "random_streams.root_seed must be a non-negative integer."
        )
    if not isinstance(scheme_id, str) or not scheme_id:
        raise ShackHartmannMeasurementError(
            "random_streams.derivation_scheme_id must be a non-empty string."
        )
    if root_seed != realization.root_seed:
        raise ShackHartmannMeasurementError(
            "runtime random root seed does not match detector realization."
        )
    return root_seed, scheme_id


def _backend_identity(
    backend: ShackHartmannOpticsBackend,
) -> tuple[str, str]:
    try:
        backend_name = backend.backend_name
        config_hash = backend.config_hash
    except AttributeError as exc:
        raise ShackHartmannMeasurementError(
            "optics_backend must implement the ShackHartmannOpticsBackend contract."
        ) from exc
    if not isinstance(backend_name, str) or not backend_name.strip():
        raise ShackHartmannMeasurementError(
            "optics_backend.backend_name must be a non-empty string."
        )
    if not isinstance(config_hash, str) or not config_hash.strip():
        raise ShackHartmannMeasurementError(
            "optics_backend.config_hash must be a non-empty string."
        )
    return backend_name, config_hash


def _validate_backend_context(
    backend: ShackHartmannOpticsBackend,
    geometry: ShackHartmannGeometry,
    wavelength_m: float,
) -> None:
    declared_geometry = getattr(backend, "geometry", None)
    if declared_geometry is not None:
        if not isinstance(declared_geometry, ShackHartmannGeometry):
            raise ShackHartmannMeasurementError(
                "optics_backend.geometry must be a ShackHartmannGeometry."
            )
        if stable_hash(
            declared_geometry,
            namespace="shack_hartmann_geometry",
        ) != stable_hash(geometry, namespace="shack_hartmann_geometry"):
            raise ShackHartmannMeasurementError(
                "optics_backend geometry does not match calibration geometry."
            )
    try:
        wavelength = float(wavelength_m)
    except (TypeError, ValueError) as exc:
        raise ShackHartmannMeasurementError(
            "wfs_wavelength_m must be positive and finite."
        ) from exc
    if not math.isfinite(wavelength) or wavelength <= 0.0:
        raise ShackHartmannMeasurementError(
            "wfs_wavelength_m must be positive and finite."
        )
    declared_wavelength = getattr(backend, "wfs_wavelength_m", None)
    if declared_wavelength is not None and float(declared_wavelength) != wavelength:
        raise ShackHartmannMeasurementError(
            "optics_backend wavelength does not match wfs_wavelength_m."
        )


__all__ = (
    "ShackHartmannMeasurementError",
    "DetectorShackHartmannSensor",
    "DetectorLevelShackHartmannSensor",
    "build_detector_shack_hartmann_sensor",
)
