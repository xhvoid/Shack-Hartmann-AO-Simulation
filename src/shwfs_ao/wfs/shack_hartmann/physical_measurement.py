"""Shack--Hartmann sensor on the physical camera path (detector level).

:class:`PhysicalShackHartmannSensor` is the physical counterpart of
:class:`~.measurement.DetectorShackHartmannSensor`, which it leaves untouched.
Per frame it runs

    optics (unit-sum block spots and capture fractions)
    -> detected source electrons per pixel (illuminated-area budget x capture)
    -> physical camera chain (``shwfs_ao.detector.physical_camera.v1``)
    -> RTC pixel processing with fixed calibration products
    -> centroid on the central window of each block
    -> ``detector_covariance_v1`` quality and validity gates.

The optics backend returns blocks of ``window + 2 * guard`` pixels; the guard
ring exists so that electronic coupling and charge diffusion act on real
neighbouring pixels, and is excluded from the centroid window.  Reference
centroids and every interaction-matrix probe pass through the identical
fixed products on the deterministic reference path.

Temporal noise is drawn per lenslet from persistent generators of the scoped
provider ``random_streams.scoped("shack_hartmann.physical_measurement",
key=(noise_stream_identity, subaperture_id))``, one per stage domain, so a
lenslet's draws do not depend on lenslet order, batch size or the retained
subset.  The physical random domains must be registered on the root provider
(:func:`shwfs_ao.core.random.with_detector_physics_domains`).
"""

from __future__ import annotations

from collections.abc import Sequence
import math
from typing import Any

import numpy as np

from ...core.hashing import component_config_hash
from ...core.protocols import RandomStreams, ShackHartmannOpticsBackend
from ...core.random import DETECTOR_PHYSICS_RANDOM_DOMAINS
from ...core.types import (
    DetectorFrame,
    DetectorTelemetry,
    MeasurementVector,
    SpotIntensityResult,
    WfsMeasurement,
)
from ...detector.camera_maps import CameraMaps
from ...detector.centroid import CentroidConfig, estimate_centroid
from ...detector.layout import DetectorLayout
from ...detector.noise_model import (
    UNCERTAINTY_MODEL_ID,
    ExtendedCentroidQuality,
    detector_covariance_quality,
)
from ...detector.physical import POISSON_ROUNDOFF_FLOOR, apply_physical_camera
from ...detector.physical_config import PhysicalDetectorConfig, physical_budget
from ...detector.processing import CalibrationProducts, build_calibration_products, process_frames
from ...detector.validity import DEFAULT_CENTROID_VALIDITY, CentroidValidityConfig
from .calibration import row_ids_for_subapertures
from .compact_geometry import CompactShackHartmannGeometry, geometries_match
from .geometry import ShackHartmannGeometry
from .optics import validate_spot_intensity_result


__all__ = (
    "PHYSICAL_SENSOR_SCHEMA",
    "PhysicalShackHartmannError",
    "PhysicalShackHartmannSensor",
)


PHYSICAL_SENSOR_SCHEMA = "shwfs_ao.physical_shack_hartmann_sensor.v1"
_MEASUREMENT_SCOPE = "shack_hartmann.physical_measurement"
_PRODUCTS_SCOPE = "shack_hartmann.physical_calibration_products"
_TELEMETRY_LEVELS = ("full", "summary")


class PhysicalShackHartmannError(ValueError):
    """Raised when the physical sensor's inputs or state are inconsistent."""


def _illuminated_counts(geometry: Any) -> np.ndarray:
    counts = getattr(geometry, "illuminated_counts", None)
    if counts is not None:
        return np.asarray(counts, dtype=float)
    return np.asarray(
        [np.count_nonzero(mask) for mask in geometry.subaperture_masks], dtype=float
    )


class PhysicalShackHartmannSensor:
    """Detector-level SH-WFS with a physical camera and RTC pixel processing."""

    def __init__(
        self,
        *,
        optics_backend: ShackHartmannOpticsBackend,
        geometry: ShackHartmannGeometry | CompactShackHartmannGeometry,
        config: PhysicalDetectorConfig,
        wfs_wavelength_m: float,
        layout: DetectorLayout,
        maps: CameraMaps,
        products: CalibrationProducts | None,
        detected_e_per_subap: np.ndarray,
        sky_e_per_pixel: np.ndarray,
        reference_centroids_px: np.ndarray,
        centroid_config: CentroidConfig,
        validity_config: CentroidValidityConfig,
        calibration_realization_index: int,
        telemetry_level: str = "full",
        area_fraction: np.ndarray | None = None,
    ) -> None:
        if telemetry_level not in _TELEMETRY_LEVELS:
            raise PhysicalShackHartmannError("telemetry_level must be 'full' or 'summary'.")
        self._optics = optics_backend
        self._geometry = geometry
        self._config = config
        self._camera = config.camera
        self._wavelength = float(wfs_wavelength_m)
        self._layout = layout
        self._maps = maps
        self._map_arrays = maps.subset(np.arange(len(maps.subaperture_ids)))
        self._products = products
        self._budget = np.array(detected_e_per_subap, dtype=float)
        self._budget.flags.writeable = False
        self._sky = np.array(sky_e_per_pixel, dtype=float)
        self._sky.flags.writeable = False
        # With a declared internal calibration source the reference path
        # observes it (scaled by illuminated area, no sky) instead of the star.
        source = config.calibration_source_detected_e_per_full_subap_frame
        if source is None:
            self._reference_budget = self._budget
            self._reference_sky = self._sky
        else:
            if area_fraction is None:
                raise PhysicalShackHartmannError(
                    "a calibration source needs each subaperture's illuminated-area fraction."
                )
            reference_budget = float(source) * np.asarray(area_fraction, dtype=float)
            if reference_budget.shape != self._budget.shape:
                raise PhysicalShackHartmannError("area_fraction must have one value per subaperture.")
            self._reference_budget = reference_budget
            self._reference_budget.flags.writeable = False
            self._reference_sky = np.zeros_like(self._sky)
        self._area_fraction = None if area_fraction is None else np.array(area_fraction, dtype=float)
        reference = np.array(reference_centroids_px, dtype=float)
        reference.flags.writeable = False
        self._reference = reference
        self._centroid_config = centroid_config
        self._validity = validity_config
        self._telemetry_level = telemetry_level
        self._calibration_realization_index = int(calibration_realization_index)
        self._subaperture_ids = tuple(geometry.subaperture_ids)
        self._row_ids = row_ids_for_subapertures(self._subaperture_ids)
        backend_name = str(optics_backend.backend_name)
        backend_hash = str(optics_backend.config_hash)
        sampling = getattr(
            optics_backend, "detector_sampling", getattr(optics_backend, "sampling", None)
        )
        self._sampling_hash = None if sampling is None else sampling.sampling_hash
        self._dark_e_map = maps.dark_rate_e_per_s(self._camera) * float(config.exposure_s)
        self._optical_response = maps.optical_response()
        floor_budget = self._budget + np.max(self._sky) + float(np.max(self._dark_e_map))
        self._poisson_floor = POISSON_ROUNDOFF_FLOOR * floor_budget
        products_hash = None if products is None else products.content_hash

        # Declared identity keying temporal noise: no realized float content.
        self._noise_stream_identity = component_config_hash(
            "physical_shack_hartmann_noise_stream_identity",
            {
                "schema": PHYSICAL_SENSOR_SCHEMA,
                "geometry_hash": geometry.geometry_hash,
                "subaperture_ids": self._subaperture_ids,
                "wfs_wavelength_m": self._wavelength,
                "sampling_hash": self._sampling_hash,
                "physical_config_hash": config.config_hash,
                "optics_backend_name": backend_name,
                "optics_backend_config_hash": backend_hash,
                "maps_derivation": maps.derivation_identity,
                "calibration_realization_index": self._calibration_realization_index,
            },
        )
        self._detector_hash = component_config_hash(
            "physical_shack_hartmann_detector",
            {
                "camera_config_hash": self._camera.config_hash,
                "layout_hash": layout.layout_hash,
                "maps_realization_hash": maps.realization_hash,
                "calibration_products_hash": products_hash,
            },
        )
        # Deterministic reference response conditional on the fixed products.
        self._response_hash = component_config_hash(
            "physical_shack_hartmann_response",
            {
                "schema": PHYSICAL_SENSOR_SCHEMA,
                "geometry_hash": geometry.geometry_hash,
                "optics_backend_name": backend_name,
                "optics_backend_config_hash": backend_hash,
                "wfs_wavelength_m": self._wavelength,
                "camera_deterministic_response": self._camera.deterministic_response_config,
                "layout_hash": layout.layout_hash,
                "maps_realization_hash": maps.realization_hash,
                "detected_e_per_subap": self._reference_budget,
                "sky_e_per_pixel": self._reference_sky,
                "exposure_s": float(config.exposure_s),
                "exposure_subsamples": int(config.exposure_subsamples),
                "bandpass": config.bandpass,
                "sampling": config.sampling,
                "processing_config_hash": config.processing.config_hash,
                "calibration_products_hash": products_hash,
                "centroid_config": centroid_config,
                "measurement_unit": "pixel",
            },
        )
        if source is not None:
            # The response identity is the calibration source's; bind the
            # source and the operating budget the noisy measurements use.
            self._response_hash = component_config_hash(
                "physical_shack_hartmann_response_with_calibration_source",
                {
                    "response_hash": self._response_hash,
                    "calibration_source_detected_e_per_full_subap_frame": float(source),
                },
            )
        noisy_payload: dict[str, Any] = {
            "response_hash": self._response_hash,
            "temporal_noise": self._camera.temporal_noise_config,
        }
        if source is not None:
            noisy_payload["operating_detected_e_per_subap"] = self._budget
            noisy_payload["operating_sky_e_per_pixel"] = self._sky
        self._noisy_response_hash = component_config_hash(
            "physical_shack_hartmann_noisy_response",
            noisy_payload,
        )
        self._config_hash = component_config_hash(
            "physical_shack_hartmann_sensor",
            {
                "schema": PHYSICAL_SENSOR_SCHEMA,
                "response_hash": self._response_hash,
                "noisy_response_hash": self._noisy_response_hash,
                "detector_hash": self._detector_hash,
                "validity_config": validity_config,
                "reference_centroids_px": self._reference,
                "noise_stream_identity": self._noise_stream_identity,
                "uncertainty_model": UNCERTAINTY_MODEL_ID,
            },
        )

    # -- construction -------------------------------------------------------

    @classmethod
    def calibrate(
        cls,
        geometry: ShackHartmannGeometry | CompactShackHartmannGeometry,
        optics_backend: ShackHartmannOpticsBackend,
        config: PhysicalDetectorConfig,
        *,
        wfs_wavelength_m: float,
        random_streams: RandomStreams,
        centroid_config: CentroidConfig | None = None,
        validity_config: CentroidValidityConfig = DEFAULT_CENTROID_VALIDITY,
        realization_index: int = 0,
        calibration_realization_index: int = 0,
        telemetry_level: str = "full",
        products: CalibrationProducts | None = None,
    ) -> PhysicalShackHartmannSensor:
        """Build maps, budgets and calibration products, then the reference."""

        if not isinstance(config, PhysicalDetectorConfig):
            raise PhysicalShackHartmannError("config must be a PhysicalDetectorConfig.")
        if not isinstance(geometry, (ShackHartmannGeometry, CompactShackHartmannGeometry)):
            raise PhysicalShackHartmannError("geometry must be a Shack-Hartmann geometry.")
        missing = [
            domain
            for domain in DETECTOR_PHYSICS_RANDOM_DOMAINS
            if domain not in getattr(random_streams, "registered_domains", ())
        ]
        if missing:
            raise PhysicalShackHartmannError(
                f"random_streams must register the physical detector domains {missing}; "
                "use shwfs_ao.core.random.with_detector_physics_domains on the root provider."
            )
        resolved_centroid = CentroidConfig() if centroid_config is None else centroid_config
        declared_geometry = getattr(optics_backend, "geometry", None)
        if declared_geometry is not None and not geometries_match(declared_geometry, geometry):
            raise PhysicalShackHartmannError("optics backend geometry does not match.")
        zero = optics_backend.spot_intensities(np.zeros(geometry.pupil_shape, dtype=float))
        validate_spot_intensity_result(zero, geometry)
        rows, columns = zero.sampling.window_shape_px
        if rows != columns:
            raise PhysicalShackHartmannError("the physical path needs square blocks.")
        window = rows - 2 * config.guard_px
        if window < 1:
            raise PhysicalShackHartmannError("the guard ring leaves no centroid window.")
        if window % 2 != 1:
            raise PhysicalShackHartmannError(
                "the physical path needs an odd centroid window, symmetric about "
                "the optical-axis pixel (see published_profile_window_bias.md)."
            )
        layout = DetectorLayout(
            config.layout_scheme,  # type: ignore[arg-type]
            int(geometry.n_lenslets_across),
            window,
            config.guard_px,
        )
        maps = CameraMaps.create(
            config.camera,
            layout,
            tuple(geometry.subaperture_ids),
            random_streams=random_streams,
            realization_index=realization_index,
        )
        dx = float(geometry.x_m[0, 1] - geometry.x_m[0, 0])
        dy = float(geometry.y_m[1, 0] - geometry.y_m[0, 0])
        full_area = (float(geometry.telescope_diameter_m) / float(geometry.n_lenslets_across)) ** 2
        pixel_scale = zero.sampling.pixel_scale_rad
        budget = physical_budget(
            config,
            wfs_wavelength_m=wfs_wavelength_m,
            full_subaperture_area_m2=full_area,
            pixel_solid_angle_sr=float(pixel_scale[0]) * float(pixel_scale[1]),
        )
        area_fraction = _illuminated_counts(geometry) * abs(dx * dy) / full_area
        detected = budget.detected_e_full_subap * area_fraction
        sky = budget.sky_e_per_pixel_full_subap * area_fraction
        if products is None and config.processing.mode != "raw_readout":
            products = build_calibration_products(
                config.camera,
                maps,
                config.processing,
                exposure_s=config.exposure_s,
                sky_e_per_pixel=sky,
                random_streams=random_streams.scoped(
                    _PRODUCTS_SCOPE, key=(int(calibration_realization_index),)
                ),
                include_noise=True,
            )
        sensor = cls(
            optics_backend=optics_backend,
            geometry=geometry,
            config=config,
            wfs_wavelength_m=wfs_wavelength_m,
            layout=layout,
            maps=maps,
            products=products,
            detected_e_per_subap=detected,
            sky_e_per_pixel=sky,
            reference_centroids_px=np.zeros((len(geometry.subaperture_ids), 2)),
            centroid_config=resolved_centroid,
            validity_config=validity_config,
            calibration_realization_index=calibration_realization_index,
            telemetry_level=telemetry_level,
            area_fraction=area_fraction,
        )
        reference = sensor._centroids_from_spots(zero, random_streams=None, include_noise=False)[0]
        if not np.all(np.isfinite(reference)):
            raise PhysicalShackHartmannError("a zero-phase reference centroid is not finite.")
        return cls(
            optics_backend=optics_backend,
            geometry=geometry,
            config=config,
            wfs_wavelength_m=wfs_wavelength_m,
            layout=layout,
            maps=maps,
            products=products,
            detected_e_per_subap=detected,
            sky_e_per_pixel=sky,
            reference_centroids_px=reference,
            centroid_config=resolved_centroid,
            validity_config=validity_config,
            calibration_realization_index=calibration_realization_index,
            telemetry_level=telemetry_level,
            area_fraction=area_fraction,
        )

    def with_telemetry_level(self, level: str) -> PhysicalShackHartmannSensor:
        """The same sensor (same identities) with another telemetry level."""

        return PhysicalShackHartmannSensor(
            optics_backend=self._optics,
            geometry=self._geometry,
            config=self._config,
            wfs_wavelength_m=self._wavelength,
            layout=self._layout,
            maps=self._maps,
            products=self._products,
            detected_e_per_subap=self._budget,
            sky_e_per_pixel=self._sky,
            reference_centroids_px=self._reference,
            centroid_config=self._centroid_config,
            validity_config=self._validity,
            calibration_realization_index=self._calibration_realization_index,
            telemetry_level=level,
            area_fraction=self._area_fraction,
        )

    # -- identities and state ---------------------------------------------------

    @property
    def config_hash(self) -> str:
        return self._config_hash

    @property
    def response_hash(self) -> str:
        """Deterministic reference response conditional on fixed products."""

        return self._response_hash

    @property
    def noisy_response_hash(self) -> str:
        return self._noisy_response_hash

    @property
    def detector_hash(self) -> str:
        return self._detector_hash

    @property
    def noise_stream_identity(self) -> str:
        return self._noise_stream_identity

    @property
    def row_ids(self) -> tuple[str, ...]:
        return self._row_ids

    @property
    def subaperture_ids(self) -> tuple[str, ...]:
        return self._subaperture_ids

    @property
    def geometry(self) -> ShackHartmannGeometry | CompactShackHartmannGeometry:
        return self._geometry

    @property
    def geometry_hash(self) -> str:
        return self._geometry.geometry_hash

    @property
    def optics_backend(self) -> ShackHartmannOpticsBackend:
        return self._optics

    @property
    def physical_config(self) -> PhysicalDetectorConfig:
        return self._config

    @property
    def layout(self) -> DetectorLayout:
        return self._layout

    @property
    def camera_maps(self) -> CameraMaps:
        return self._maps

    @property
    def calibration_products(self) -> CalibrationProducts | None:
        return self._products

    @property
    def detected_e_per_subap(self) -> np.ndarray:
        return self._budget

    @property
    def sky_e_per_pixel(self) -> np.ndarray:
        return self._sky

    @property
    def reference_centroids_px(self) -> np.ndarray:
        return self._reference

    @property
    def validity_config(self) -> CentroidValidityConfig:
        return self._validity

    @property
    def centroid_config(self) -> CentroidConfig:
        return self._centroid_config

    @property
    def telemetry_level(self) -> str:
        return self._telemetry_level

    @property
    def exposure_subsamples(self) -> int:
        return int(self._config.exposure_subsamples)

    def noise_model(self, residual_opd_m: np.ndarray) -> ExtendedCentroidQuality:
        """``detector_covariance_v1`` prediction at a fixed residual (no draws).

        Returns the :class:`~shwfs_ao.detector.noise_model.ExtendedCentroidQuality`
        the validity gates would see for this residual, including each
        lenslet's 2x2 temporal centroid covariance.
        """

        residual = np.array(residual_opd_m, dtype=float, copy=True)
        mask = np.asarray(self._geometry.pupil_mask, dtype=bool)
        residual[~mask] = 0.0
        source, _ = self._expected_source(self._optics.spot_intensities(residual))
        batch = apply_physical_camera(
            source,
            self._sky,
            self._camera,
            self._map_arrays,
            exposure_s=self._config.exposure_s,
            include_noise=False,
            generators=None,
            poisson_floor_e=self._poisson_floor,
        )
        return detector_covariance_quality(
            expected_source_e=batch.expected_source_e,
            expected_background_e=batch.expected_background_e,
            camera=self._camera,
            maps=self._map_arrays,
            products=self._products,
            processing=self._config.processing,
            centroid_config=self._centroid_config,
            window=self._layout.window_slice,
            sky_e_per_pixel=self._sky,
            dark_e_map=self._dark_e_map,
            optical_response=self._optical_response,
        )

    # -- measurement --------------------------------------------------------------

    def measure(
        self,
        residual_opd_m: np.ndarray,
        *,
        random_streams: RandomStreams,
        include_noise: bool,
    ) -> WfsMeasurement:
        """Measure reference-subtracted x/y centroid shifts in pixels."""

        return self.measure_exposure((residual_opd_m,), random_streams=random_streams, include_noise=include_noise)

    def measure_exposure(
        self,
        residual_opd_samples: Sequence[np.ndarray],
        *,
        random_streams: RandomStreams,
        include_noise: bool,
    ) -> WfsMeasurement:
        """Measure one exposure whose optical intensity averages the samples.

        The detector applies its noise once to the averaged expected image
        (DET-08); the DM state is whatever produced each residual sample.
        """

        if not isinstance(include_noise, (bool, np.bool_)):
            raise PhysicalShackHartmannError("include_noise must be a boolean.")
        samples = tuple(residual_opd_samples)
        if not samples:
            raise PhysicalShackHartmannError("at least one residual sample is required.")
        spots = []
        for sample in samples:
            residual = np.array(sample, dtype=float, copy=True)
            if residual.shape != self._geometry.pupil_shape:
                raise PhysicalShackHartmannError("residual OPD shape does not match the pupil.")
            mask = np.asarray(self._geometry.pupil_mask, dtype=bool)
            if not np.all(np.isfinite(residual[mask])):
                raise PhysicalShackHartmannError("residual OPD must be finite in the pupil.")
            residual[~mask] = 0.0
            spots.append(self._optics.spot_intensities(residual))
        root_seed = random_streams.root_seed
        if root_seed != self._maps.root_seed:
            raise PhysicalShackHartmannError("runtime root seed does not match the camera maps.")
        centroids, telemetry_parts = self._centroids_from_spots(
            spots[0] if len(spots) == 1 else tuple(spots),
            random_streams=random_streams if include_noise else None,
            include_noise=bool(include_noise),
            telemetry=True,
        )
        return self._measurement(centroids, telemetry_parts, include_noise=bool(include_noise), random_streams=random_streams)

    def _expected_source(
        self,
        spots: SpotIntensityResult | tuple[SpotIntensityResult, ...],
        budget: np.ndarray | None = None,
    ) -> tuple[np.ndarray, np.ndarray]:
        """Expected detected source electrons per block pixel, and window capture."""

        results = spots if isinstance(spots, tuple) else (spots,)
        accumulated = None
        window_capture = None
        rows, cols = self._layout.window_slice
        for result in results:
            unit = np.stack(result.unit_sum_spots)
            capture = np.asarray(result.relative_throughput, dtype=float)
            physical = unit * capture[:, None, None]
            accumulated = physical if accumulated is None else accumulated + physical
            inner = np.sum(physical[:, rows, cols], axis=(1, 2))
            window_capture = inner if window_capture is None else window_capture + inner
        assert accumulated is not None and window_capture is not None
        count = float(len(results))
        scale = self._budget if budget is None else budget
        source = accumulated / count * scale[:, None, None]
        return source, window_capture / count

    def _centroids_from_spots(
        self,
        spots: SpotIntensityResult | tuple[SpotIntensityResult, ...],
        *,
        random_streams: RandomStreams | None,
        include_noise: bool,
        telemetry: bool = False,
    ) -> tuple[np.ndarray, dict[str, Any]]:
        # The deterministic reference path observes the calibration source when
        # one is declared; noisy measurements observe the star and the sky.
        budget = self._budget if include_noise else self._reference_budget
        sky = self._sky if include_noise else self._reference_sky
        source, window_capture = self._expected_source(spots, budget)
        generators = None
        scoped: list[Any] = []
        if include_noise:
            assert random_streams is not None
            scoped = [
                random_streams.scoped(_MEASUREMENT_SCOPE, key=(self._noise_stream_identity, identifier))
                for identifier in self._subaperture_ids
            ]

            def generators(index: int, domain: str) -> np.random.Generator:
                return scoped[index].generator(domain)

        batch = apply_physical_camera(
            source,
            sky,
            self._camera,
            self._map_arrays,
            exposure_s=self._config.exposure_s,
            include_noise=include_noise,
            generators=generators,
            poisson_floor_e=self._poisson_floor,
        )
        processed = process_frames(batch.raw, self._products, self._config.processing)
        rows, cols = self._layout.window_slice
        window = processed[:, rows, cols]
        centroids = _window_centroids(window, self._centroid_config)
        parts: dict[str, Any] = {}
        if telemetry:
            parts = {
                "batch": batch,
                "processed": processed,
                "window": window,
                "window_capture": window_capture,
                "spots": spots if isinstance(spots, SpotIntensityResult) else None,
                "n_samples": 1 if isinstance(spots, SpotIntensityResult) else len(spots),
                "scoped": scoped,
                "sky": sky,
            }
        return centroids, parts

    def _measurement(
        self,
        centroids: np.ndarray,
        parts: dict[str, Any],
        *,
        include_noise: bool,
        random_streams: RandomStreams,
    ) -> WfsMeasurement:
        batch = parts["batch"]
        n = centroids.shape[0]
        quality = detector_covariance_quality(
            expected_source_e=batch.expected_source_e,
            expected_background_e=batch.expected_background_e,
            camera=self._camera,
            maps=self._map_arrays,
            products=self._products,
            processing=self._config.processing,
            centroid_config=self._centroid_config,
            window=self._layout.window_slice,
            sky_e_per_pixel=parts["sky"],
            dark_e_map=self._dark_e_map,
            optical_response=self._optical_response,
        )
        clipping = np.clip(1.0 - np.asarray(parts["window_capture"], dtype=float), 0.0, 1.0)
        finite = np.all(np.isfinite(centroids), axis=1)
        config = self._validity
        by_flux = quality.total_flux_e >= config.min_flux_e
        by_snr = quality.peak_snr >= config.min_peak_snr
        by_uncertainty = quality.centroid_sigma_px <= config.max_centroid_sigma_px
        by_clipping = clipping <= config.max_window_clipping_fraction
        usable = finite & by_flux & by_snr & by_uncertainty & by_clipping
        shifts = centroids - self._reference
        values = np.where(usable[:, None], shifts, np.nan).reshape(-1)
        valid_rows = np.repeat(usable, 2)
        vector = MeasurementVector(
            values=values,
            valid_rows=valid_rows,
            row_ids=self._row_ids,
            measurement_unit="pixel",
        )
        bad = (
            np.zeros(batch.raw.shape, dtype=bool)
            if self._products is None
            else np.asarray(self._products.bad, dtype=bool)
        )
        rows, cols = self._layout.window_slice
        masked_fraction = np.mean(bad[:, rows, cols], axis=(1, 2))
        saturated = batch.pixel_saturated | batch.register_saturated | batch.digital_saturated
        frames = None
        optical_spots = None
        if self._telemetry_level == "full":
            products_hash = None if self._products is None else self._products.content_hash
            frame_list = []
            for index in range(n):
                stream_ids: dict[str, str] = {}
                if include_noise and parts["scoped"]:
                    view = parts["scoped"][index]
                    for domain in ("detector.shot_noise", "detector.cic", "detector.em_gain", "detector.read_noise"):
                        stream_ids[domain] = view.stream_id(domain)
                negative = (
                    np.zeros(batch.raw.shape[1:], dtype=bool)
                    if not self._config.processing.clip_negative
                    else parts["processed"][index] <= 0.0
                )
                frame_list.append(
                    DetectorFrame(
                        image_e=parts["processed"][index],
                        expected_source_e=batch.expected_source_e[index],
                        expected_background_e=batch.expected_background_e[index],
                        expected_pre_poisson_e=batch.expected_source_e[index]
                        + batch.expected_background_e[index]
                        + batch.expected_cic_e,
                        prnu_response=batch.optical_response[index],
                        saturated_mask=saturated[index],
                        bad_pixel_mask=bad[index],
                        negative_clipped_mask=negative,
                        random_stream_ids=stream_ids,
                        raw_image=batch.raw[index],
                        raw_unit=batch.raw_unit,
                        pixel_saturated_mask=batch.pixel_saturated[index],
                        register_saturated_mask=batch.register_saturated[index],
                        digital_saturated_mask=batch.digital_saturated[index],
                        response_model=batch.response_model,
                        calibration_products_hash=products_hash,
                    )
                )
            frames = tuple(frame_list)
            optical_spots = parts["spots"]
        telemetry = DetectorTelemetry(
            subaperture_ids=self._subaperture_ids,
            centroids_xy_px=np.where(finite[:, None], centroids, np.nan),
            reference_centroids_xy_px=self._reference,
            # The model-expected processed window flux, the flux gate's input.
            # The measured processed sum is background-subtracted and can be
            # negative for a faint lenslet, which is not a flux.
            fluxes_e=np.maximum(quality.total_flux_e, 0.0),
            valid_subapertures=usable,
            valid_by_flux=by_flux,
            valid_by_snr=by_snr,
            valid_by_uncertainty=by_uncertainty,
            valid_by_clipping=by_clipping,
            peak_snr=quality.peak_snr,
            total_snr=quality.total_snr,
            centroid_sigma_px=quality.centroid_sigma_px,
            clipping_fraction=clipping,
            detector_frames=frames,
            optical_spots=optical_spots,
            telemetry_level=self._telemetry_level,
            centroid_calibration_sigma_px=quality.calibration_sigma_px,
            uncertainty_supported=quality.supported,
            masked_pixel_fraction=masked_fraction,
            saturated_pixel_count=np.sum(saturated, axis=(1, 2)).astype(float),
        )
        metadata = {
            "sensor_config_hash": self._config_hash,
            "noise_stream_identity": self._noise_stream_identity,
            "response_model": self._camera.response_model,
            "uncertainty_model": UNCERTAINTY_MODEL_ID,
            "camera_model": self._camera.model,
            "camera_preset": f"{self._camera.preset_name}@{self._camera.preset_version}",
            "processing_mode": self._config.processing.mode,
            "calibration_products_hash": (
                None if self._products is None else self._products.content_hash
            ),
            "camera_maps_realization_hash": self._maps.realization_hash,
            "random_root_seed": int(random_streams.root_seed),
            "random_derivation_scheme_id": random_streams.derivation_scheme_id,
            "include_noise": bool(include_noise),
            "telemetry_level": self._telemetry_level,
            "optics_backend_name": str(self._optics.backend_name),
            "exposure_samples": int(parts["n_samples"]),
        }
        return WfsMeasurement(
            vector=vector,
            valid_subapertures=usable,
            metadata=metadata,
            detector_telemetry=telemetry,
        )


def _window_centroids(window: np.ndarray, config: CentroidConfig) -> np.ndarray:
    """Centre-of-gravity centroids of every window, absolute window coordinates."""

    if config.estimator == "center_of_gravity" and not config.subtract_minimum:
        n, rows, columns = window.shape
        total = np.sum(window, axis=(1, 2))
        x = np.arange(columns, dtype=float)
        y = np.arange(rows, dtype=float)
        with np.errstate(invalid="ignore", divide="ignore"):
            cx = np.einsum("nrc,c->n", window, x) / total
            cy = np.einsum("nrc,r->n", window, y) / total
        good = (total > 0.0) & np.isfinite(cx) & np.isfinite(cy)
        result = np.full((n, 2), math.nan)
        result[good, 0] = cx[good]
        result[good, 1] = cy[good]
        return result
    result = np.full((window.shape[0], 2), math.nan)
    for index in range(window.shape[0]):
        estimate = estimate_centroid(window[index], config)
        if estimate.finite:
            result[index] = (estimate.x_px, estimate.y_px)
    return result
