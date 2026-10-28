"""Registered HCIPy component construction for shared SCAO experiments.

This module is deliberately below the experiment and configuration layers: it
accepts explicit primitives and canonical component configs, and it never
chooses observing defaults from the backend name.  Importing it does not
require HCIPy — every adapter defers ``require_hcipy`` to construction — so
the experiment layer can always resolve the factory and fail with the
canonical :class:`~shwfs_ao.backends.hcipy.OptionalDependencyError` only when
a component is actually built without the optional dependency installed.

The serialized profile fields keep one meaning across backends.  For the
detector-level HCIPy sensor, ``wfs.pad_factor`` is the spot sampling in
detector pixels per lambda/d — the native optics realizes it by FFT
zero-padding, this backend by the equivalent lenslet f-number
``pad_factor * pixel_pitch_m / wavelength_m`` (the derivation the accepted
cross-backend baseline uses) — and ``wfs.detector_window_px`` must equal the
fixed block window ``pupil_pixels // lenslets_across`` that the HCIPy
lenslet model actually measures on.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Literal

from ...core.protocols import (
    AtmosphereModel,
    DeformableMirrorModel,
    RandomStreams,
    SciencePropagator,
    WavefrontSensor,
)
from ...detector.centroid import CentroidConfig
from ...detector.config import DetectorConfig
from ...detector.validity import CentroidValidityConfig
from ...dm import DMConfig
from ...science.propagation import PsfSampling
from ...wfs.shack_hartmann.geometry import (
    ShackHartmannGeometry,
    build_shack_hartmann_geometry,
)
from ...wfs.shack_hartmann.measurement import DetectorShackHartmannSensor
from .atmosphere import HcipyAtmosphereConfig, HcipyVonKarmanAtmosphere
from .dm import build_hcipy_deformable_mirror
from .propagation import HcipySciencePropagator, focal_sampling_from_psf_sampling
from .shwfs import HcipyShackHartmannOptics


__all__ = (
    "HcipyScaoFactoryError",
    "HcipyScaoComponentFactory",
    "HCIPY_SCAO_COMPONENT_FACTORY",
)


class HcipyScaoFactoryError(ValueError):
    """Raised when explicit HCIPy construction inputs are inconsistent."""


@dataclass(frozen=True, slots=True)
class HcipyScaoComponentFactory:
    """Construct HCIPy protocol implementations from explicit inputs."""

    backend_name: Literal["hcipy"] = "hcipy"

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
        if model != "hcipy":
            raise HcipyScaoFactoryError(
                f"HCIPy atmosphere model {model!r} is not registered; this "
                "backend builds only 'hcipy' (single-layer von Karman "
                "frozen flow).  The 'static' and 'native_frozen_flow' "
                "models build through backend='native'."
            )
        if normalize_rms or target_rms_rad is not None:
            raise HcipyScaoFactoryError(
                "the HCIPy atmosphere adapter has no RMS normalization; "
                "profiles selecting it must set normalize_rms=false and "
                "target_rms_opd_m=null, or use backend='native'."
            )
        return HcipyVonKarmanAtmosphere(
            HcipyAtmosphereConfig.single_layer(
                r0_m=r0_m,
                outer_scale_m=outer_scale_m,
                wind_m_per_s=wind_m_per_s,
                r0_reference_wavelength_m=phase_reference_wavelength_m,
                phase_conversion_reference_wavelength_m=(
                    phase_reference_wavelength_m
                ),
                root_seed=random_streams.root_seed,
            ),
            geometry.pupil_geometry,
            pupil_mask=geometry.pupil_mask,
            random_streams=random_streams.scoped("hcipy-atmosphere"),
        )

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
    ) -> WavefrontSensor:
        if model != "detector_level":
            raise HcipyScaoFactoryError(
                f"HCIPy WFS model {model!r} is not registered; the HCIPy "
                "backend has no geometric sensor, so only 'detector_level' "
                "builds here.  Use backend='native' for geometric profiles."
            )
        rows, _ = geometry.pupil_shape
        block_window_px = rows // geometry.n_lenslets_across
        if detector_window_px != block_window_px:
            raise HcipyScaoFactoryError(
                "the HCIPy lenslet backend measures on fixed block windows "
                f"of pupil_pixels // lenslets_across = {block_window_px} "
                f"pixels; the profile declares detector_window_px="
                f"{detector_window_px!r}."
            )
        pixel_pitch_m = float(geometry.x_m[0, 1] - geometry.x_m[0, 0])
        f_number = pad_factor * pixel_pitch_m / wfs_wavelength_m
        optics = HcipyShackHartmannOptics(
            geometry,
            wfs_wavelength_m,
            f_number=f_number,
        )
        return DetectorShackHartmannSensor.calibrate(
            geometry,
            optics,
            detector_config,
            wfs_wavelength_m=wfs_wavelength_m,
            random_streams=random_streams.scoped("hcipy-detector-wfs"),
            centroid_config=centroid_config,
            validity_config=validity_config,
        )

    def build_dm(
        self,
        *,
        geometry: ShackHartmannGeometry,
        config: DMConfig,
    ) -> DeformableMirrorModel:
        return build_hcipy_deformable_mirror(
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
        return HcipySciencePropagator(
            geometry.pupil_geometry,
            focal_sampling_from_psf_sampling(geometry.pupil_geometry, sampling),
        )


HCIPY_SCAO_COMPONENT_FACTORY = HcipyScaoComponentFactory()
