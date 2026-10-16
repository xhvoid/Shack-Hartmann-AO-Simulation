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
lenslet model actually measures on.  ``wfs.lenslet_axis`` (schema v6) is
consulted by this backend only: it places the microlens vertices
(:class:`~shwfs_ao.backends.hcipy.shwfs.HcipyShackHartmannOptics`), and the
experiment layer passes it only for a profile that opts in.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
import math
from typing import Any, Literal

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
from .atmosphere import (
    HcipyAtmosphereConfig,
    HcipyAtmosphereLayerConfig,
    HcipyVonKarmanAtmosphere,
)
from .dm import build_hcipy_deformable_mirror
from .propagation import HcipySciencePropagator, focal_sampling_from_psf_sampling
from .shwfs import HcipyShackHartmannOptics, LensletAxis


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
        layers: Sequence[Any] = (),
    ) -> AtmosphereModel:
        if model not in ("hcipy", "hcipy_layered"):
            raise HcipyScaoFactoryError(
                f"HCIPy atmosphere model {model!r} is not registered; this "
                "backend builds only 'hcipy' (single-layer von Karman frozen "
                "flow) and 'hcipy_layered' (one HCIPy layer per "
                "atmosphere.layers entry).  The 'static', 'native_frozen_flow', "
                "'native_frozen_flow_v2' and 'native_layered' models build "
                "through backend='native'."
            )
        # Each layer exposes altitude_m, cn2_fraction and wind_m_per_s (the
        # profile's AtmosphereLayerConfig); this layer never imports io.
        if bool(layers) != (model == "hcipy_layered"):
            raise HcipyScaoFactoryError(
                "atmosphere layers are accepted by, and required for, exactly "
                "the 'hcipy_layered' model; 'hcipy' is single-layer and is "
                "never flattened from, or expanded into, several layers."
            )
        if normalize_rms or target_rms_rad is not None:
            raise HcipyScaoFactoryError(
                "the HCIPy atmosphere adapter has no RMS normalization; "
                "profiles selecting it must set normalize_rms=false and "
                "target_rms_opd_m=null, or use backend='native'."
            )
        if layers:
            config = _layered_config(
                r0_m=r0_m,
                outer_scale_m=outer_scale_m,
                phase_reference_wavelength_m=phase_reference_wavelength_m,
                wind_m_per_s=wind_m_per_s,
                root_seed=random_streams.root_seed,
                layers=layers,
            )
        else:
            config = HcipyAtmosphereConfig.single_layer(
                r0_m=r0_m,
                outer_scale_m=outer_scale_m,
                wind_m_per_s=wind_m_per_s,
                r0_reference_wavelength_m=phase_reference_wavelength_m,
                phase_conversion_reference_wavelength_m=(
                    phase_reference_wavelength_m
                ),
                root_seed=random_streams.root_seed,
            )
        return HcipyVonKarmanAtmosphere(
            config,
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
        photon_allocation: Literal["throughput_scaled", "unit_sum"] = (
            "throughput_scaled"
        ),
        clip_negative_pixels: bool = True,
        lenslet_axis: LensletAxis = "geometry_cell_center",
        physical_detector: object = None,
    ) -> WavefrontSensor:
        if physical_detector is not None:
            raise HcipyScaoFactoryError(
                "the physical camera path (detector_physics: physical camera, "
                "pixel integration, diffusion, coupling, polychromatic sensing, "
                "pixel processing) is not implemented on the HCIPy backend; it "
                "fails closed rather than silently skipping those stages."
            )
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
            lenslet_axis=lenslet_axis,
        )
        return DetectorShackHartmannSensor.calibrate(
            geometry,
            optics,
            detector_config,
            wfs_wavelength_m=wfs_wavelength_m,
            random_streams=random_streams.scoped("hcipy-detector-wfs"),
            centroid_config=centroid_config,
            validity_config=validity_config,
            photon_allocation=photon_allocation,
            clip_negative_pixels=clip_negative_pixels,
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

# Same tolerance the profile layer applies to normalized Cn2 fractions.
_LAYER_FRACTION_ABS_TOL = 1.0e-9


def _layered_config(
    *,
    r0_m: float,
    outer_scale_m: float | None,
    phase_reference_wavelength_m: float,
    wind_m_per_s: tuple[float, float],
    root_seed: int,
    layers: Sequence[Any],
) -> HcipyAtmosphereConfig:
    """One infinite HCIPy layer per profile layer, holding its Cn2 share.

    A layer carrying the fraction ``f`` of the integrated turbulence has Fried
    parameter ``r0 * f**(-3/5)``, so the layers' Cn2 add up to exactly the
    profile's ``r0`` — the split the native ``native_layered`` model uses.
    """

    fractions = tuple(float(layer.cn2_fraction) for layer in layers)
    if not all(math.isfinite(value) and value > 0.0 for value in fractions):
        raise HcipyScaoFactoryError(
            f"layer cn2_fraction values must be finite and positive; got {fractions!r}."
        )
    total = math.fsum(fractions)
    if not math.isclose(total, 1.0, rel_tol=0.0, abs_tol=_LAYER_FRACTION_ABS_TOL):
        raise HcipyScaoFactoryError(
            f"layer cn2_fraction values must sum to 1; got {total!r}."
        )
    if tuple(wind_m_per_s) != (0.0, 0.0):
        raise HcipyScaoFactoryError(
            "a layered atmosphere carries its winds per layer; the block-level "
            "wind_m_per_s must be (0, 0)."
        )
    return HcipyAtmosphereConfig(
        layers=tuple(
            HcipyAtmosphereLayerConfig(
                r0_m=r0_m * fraction ** (-3.0 / 5.0),
                outer_scale_m=outer_scale_m,
                wind_m_per_s=tuple(layer.wind_m_per_s),
                altitude_m=layer.altitude_m,
            )
            for fraction, layer in zip(fractions, layers)
        ),
        r0_reference_wavelength_m=phase_reference_wavelength_m,
        phase_conversion_reference_wavelength_m=phase_reference_wavelength_m,
        root_seed=root_seed,
    )
