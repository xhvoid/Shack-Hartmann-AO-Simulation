"""Registered native component construction for shared SCAO experiments.

This module is deliberately below the experiment and configuration layers.  It
accepts explicit primitives and canonical component configs, and it never
chooses observing defaults from the backend name.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Literal

import numpy as np

from ...core.protocols import (
    AtmosphereModel,
    DeformableMirrorModel,
    RandomStreams,
    SciencePropagator,
    WavefrontSensor,
)
from ...core.wavefront import masked_rms, remove_piston
from ...detector.centroid import CentroidConfig
from ...detector.config import DetectorConfig
from ...detector.validity import CentroidValidityConfig
from ...dm import DMConfig, build_native_deformable_mirror
from ...science.propagation import PsfSampling
from ...wfs.shack_hartmann.geometric import (
    NativeGeometricShackHartmannSensor,
)
from ...wfs.shack_hartmann.geometry import (
    ShackHartmannGeometry,
    build_shack_hartmann_geometry,
)
from ...wfs.shack_hartmann.measurement import DetectorShackHartmannSensor
from .atmosphere import (
    SPECTRUM_SUBHARMONIC_V2,
    TRANSLATION_FOURIER_SUBPIXEL_V2,
    FrozenFlowAtmosphere,
    FrozenFlowAtmosphereConfig,
    StaticOpdAtmosphere,
)
from .propagation import NativeSciencePropagator
from .shwfs import NativeShackHartmannOptics


__all__ = (
    "NativeScaoFactoryError",
    "NativeScaoComponentFactory",
    "NATIVE_SCAO_COMPONENT_FACTORY",
    "SCREEN_OVERSIZE_FACTOR",
)

SCREEN_OVERSIZE_FACTOR = 3
"""Generated-screen size as a multiple of the pupil array, for the v2 model.

A factor of three gives a travel budget of exactly ``pupil_pixels`` pixels
before the pupil window reaches the screen's non-periodic wrap boundary.
"""


class NativeScaoFactoryError(ValueError):
    """Raised when explicit native construction inputs are inconsistent."""


@dataclass(frozen=True, slots=True)
class NativeScaoComponentFactory:
    """Construct native protocol implementations from explicit inputs."""

    backend_name: Literal["native"] = "native"

    def build_geometry(
        self,
        *,
        telescope_diameter_m: float,
        pupil_pixels: int,
        lenslets_across: int,
        min_fill_fraction: float,
        central_obstruction_ratio: float,
        spider_width_m: float,
    ) -> ShackHartmannGeometry:
        return build_shack_hartmann_geometry(
            telescope_diameter_m=telescope_diameter_m,
            pupil_shape=(pupil_pixels, pupil_pixels),
            n_lenslets_across=lenslets_across,
            min_fill_fraction=min_fill_fraction,
            central_obstruction_ratio=central_obstruction_ratio,
            spider_width_m=spider_width_m,
        )

    def build_atmosphere(
        self,
        *,
        model: str,
        geometry: ShackHartmannGeometry,
        random_streams: RandomStreams,
        r0_m: float,
        outer_scale_m: float | None,
        phase_reference_wavelength_m: float,
        wind_m_per_s: tuple[float, float],
        target_rms_rad: float | None,
        normalize_rms: bool,
        static_opd_rms_m: float,
    ) -> AtmosphereModel:
        builders: dict[str, Callable[[], AtmosphereModel]] = {
            "static": lambda: StaticOpdAtmosphere(
                _static_opd(
                    geometry,
                    target_rms_m=static_opd_rms_m,
                ),
                geometry.pupil_mask,
                root_seed=random_streams.root_seed,
            ),
            "native_frozen_flow": lambda: FrozenFlowAtmosphere(
                FrozenFlowAtmosphereConfig(
                    grid_size=geometry.pupil_shape[0],
                    delta_m=geometry.pupil_geometry.pixel_spacing_xy_m[0],
                    pupil_diameter_m=geometry.telescope_diameter_m,
                    r0_m=r0_m,
                    outer_scale_m=outer_scale_m,
                    phase_reference_wavelength_m=phase_reference_wavelength_m,
                    wind_m_per_s=wind_m_per_s,
                    root_seed=random_streams.root_seed,
                    target_rms_rad=target_rms_rad,
                    normalize_rms=normalize_rms,
                ),
                pupil_mask=geometry.pupil_mask,
                random_streams=random_streams.scoped("native-atmosphere"),
            ),
            # The physically corrected screen: absolutely normalized von
            # Karman spectrum with subharmonics, and exact sub-pixel frozen
            # flow.  Selected by name so that existing profiles keep the
            # frozen legacy numerics their accepted baselines were built from.
            #
            # The screen is generated at SCREEN_OVERSIZE_FACTOR times the pupil
            # array.  Subharmonic modes have periods longer than the screen, so
            # a v2 screen is not periodic and its wrap boundary is a real
            # discontinuity; oversizing keeps that boundary outside the pupil
            # window for `pupil_pixels` pixels of travel, which covers every
            # shipped run.  A longer run fails at the first frame outside that
            # budget, before the wrap seam can enter the pupil; the rejected
            # attempt also leaves `atmosphere.exceeded_travel_budget` true.
            # The oversize does not change the physics: the
            # ensemble pupil RMS is screen-size independent and matches the von
            # Karman aperture variance, because the subharmonics — not the grid
            # extent — carry the low frequencies.
            "native_frozen_flow_v2": lambda: FrozenFlowAtmosphere(
                FrozenFlowAtmosphereConfig(
                    grid_size=geometry.pupil_shape[0],
                    screen_grid_size=(
                        SCREEN_OVERSIZE_FACTOR * geometry.pupil_shape[0]
                    ),
                    delta_m=geometry.pupil_geometry.pixel_spacing_xy_m[0],
                    pupil_diameter_m=geometry.telescope_diameter_m,
                    r0_m=r0_m,
                    outer_scale_m=outer_scale_m,
                    phase_reference_wavelength_m=phase_reference_wavelength_m,
                    wind_m_per_s=wind_m_per_s,
                    root_seed=random_streams.root_seed,
                    target_rms_rad=target_rms_rad,
                    normalize_rms=normalize_rms,
                    spectrum_model=SPECTRUM_SUBHARMONIC_V2,
                    translation_model=TRANSLATION_FOURIER_SUBPIXEL_V2,
                ),
                pupil_mask=geometry.pupil_mask,
                random_streams=random_streams.scoped("native-atmosphere"),
            ),
        }
        try:
            builder = builders[model]
        except KeyError as exc:
            raise NativeScaoFactoryError(
                f"native atmosphere model {model!r} is not registered; "
                "expected 'static', 'native_frozen_flow', or "
                "'native_frozen_flow_v2'."
            ) from exc
        return builder()

    def build_wfs(
        self,
        *,
        model: str,
        geometry: ShackHartmannGeometry,
        wfs_wavelength_m: float,
        pad_factor: int,
        detector_window_px: int | None,
        detector_config: DetectorConfig,
        centroid_config: CentroidConfig,
        validity_config: CentroidValidityConfig,
        random_streams: RandomStreams,
        photon_allocation: Literal["throughput_scaled", "unit_sum"] = (
            "throughput_scaled"
        ),
    ) -> WavefrontSensor:
        def geometric() -> WavefrontSensor:
            return NativeGeometricShackHartmannSensor(geometry)

        def detector_level() -> WavefrontSensor:
            optics = NativeShackHartmannOptics(
                geometry,
                wfs_wavelength_m,
                pad_factor=pad_factor,
                detector_window_px=detector_window_px,
            )
            return DetectorShackHartmannSensor.calibrate(
                geometry,
                optics,
                detector_config,
                wfs_wavelength_m=wfs_wavelength_m,
                random_streams=random_streams.scoped("native-detector-wfs"),
                centroid_config=centroid_config,
                validity_config=validity_config,
                photon_allocation=photon_allocation,
            )

        builders: dict[str, Callable[[], WavefrontSensor]] = {
            "geometric": geometric,
            "detector_level": detector_level,
        }
        try:
            builder = builders[model]
        except KeyError as exc:
            raise NativeScaoFactoryError(
                f"native WFS model {model!r} is not registered; expected "
                "'geometric' or 'detector_level'."
            ) from exc
        return builder()

    def build_dm(
        self,
        *,
        geometry: ShackHartmannGeometry,
        config: DMConfig,
    ) -> DeformableMirrorModel:
        return build_native_deformable_mirror(
            geometry.x_m,
            geometry.y_m,
            geometry.pupil_mask,
            config,
        )

    def build_science_propagator(
        self,
        *,
        geometry: ShackHartmannGeometry,
        sampling: PsfSampling,
    ) -> SciencePropagator:
        return NativeSciencePropagator(
            pupil=geometry.pupil_geometry,
            sampling=sampling,
        )


NATIVE_SCAO_COMPONENT_FACTORY = NativeScaoComponentFactory()


def _static_opd(
    geometry: ShackHartmannGeometry,
    *,
    target_rms_m: float,
) -> np.ndarray:
    """Return a deterministic piston-free astigmatic static OPD realization."""

    if not np.isfinite(target_rms_m) or target_rms_m < 0.0:
        raise NativeScaoFactoryError("static_opd_rms_m must be finite and non-negative.")
    pupil = np.asarray(geometry.pupil_mask, dtype=bool)
    diameter = float(geometry.telescope_diameter_m)
    normalized_x = 2.0 * np.asarray(geometry.x_m, dtype=float) / diameter
    normalized_y = 2.0 * np.asarray(geometry.y_m, dtype=float) / diameter
    raw = normalized_x**2 - normalized_y**2 + 0.15 * normalized_x
    opd = remove_piston(raw, pupil)
    current_rms = masked_rms(opd, pupil)
    if target_rms_m == 0.0:
        opd = np.zeros_like(opd)
        opd[~pupil] = np.nan
        return opd
    if current_rms <= 0.0:
        raise NativeScaoFactoryError("static OPD template has zero pupil RMS.")
    return remove_piston(opd * (target_rms_m / current_rms), pupil)
