"""Registered native component construction for shared SCAO experiments.

This module is deliberately below the experiment and configuration layers.  It
accepts explicit primitives and canonical component configs, and it never
chooses observing defaults from the backend name.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Literal

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
from ...wfs.shack_hartmann.compact_geometry import (
    CompactShackHartmannGeometry,
    build_compact_shack_hartmann_geometry,
)
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
    NativeAtmosphereError,
    StaticOpdAtmosphere,
)
from .layered_atmosphere import (
    FrozenFlowLayer,
    LayeredFrozenFlowAtmosphere,
    LayeredFrozenFlowAtmosphereConfig,
)
from .propagation import NativeSciencePropagator
from .shwfs import NativeShackHartmannOptics
from .shwfs_batched import DEFAULT_LENSLET_BATCH_SIZE, BatchedNativeShackHartmannOptics


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
        representation: Literal["dense", "compact_cells"] = "dense",
    ) -> ShackHartmannGeometry | CompactShackHartmannGeometry:
        """Build the lenslet geometry.

        ``representation="compact_cells"`` (schema-v5 scalable profiles) stores
        per-lenslet cell bounds instead of a full-pupil mask per lenslet; it is
        passed only for such profiles, so the default dense geometry and every
        published identity are unchanged.
        """

        if representation == "compact_cells":
            return build_compact_shack_hartmann_geometry(
                telescope_diameter_m=telescope_diameter_m,
                pupil_shape=(pupil_pixels, pupil_pixels),
                n_lenslets_across=lenslets_across,
                min_fill_fraction=min_fill_fraction,
                central_obstruction_ratio=central_obstruction_ratio,
                spider_width_m=spider_width_m,
            )
        if representation != "dense":
            raise NativeScaoFactoryError(
                f"unknown geometry representation {representation!r}."
            )
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
        band_coefficient_storage: str = "materialized",
        band_draw_reference_screen_size: int | None = None,
        band_limit_screen_size: int | None = None,
        screen_period_rule: str | None = None,
        screen_grid_size: int | None = None,
    ) -> AtmosphereModel:
        """Build the atmosphere named by ``model``.

        ``band_draw_reference_screen_size``, ``band_limit_screen_size`` and
        ``screen_period_rule`` are the fixed-physics pairing options of the
        native layered atmosphere (T2, G1).  ``screen_grid_size`` replaces the
        default generated screen of the ``native_frozen_flow_v2`` model
        (``SCREEN_OVERSIZE_FACTOR`` times the pupil array).  All are
        identity-bearing, accepted only for their own model and passed only
        when set, so every other model and every default build is unchanged.
        """

        pairing = {
            name: value
            for name, value in (
                ("band_draw_reference_screen_size", band_draw_reference_screen_size),
                ("band_limit_screen_size", band_limit_screen_size),
                ("screen_period_rule", screen_period_rule),
            )
            if value is not None
        }
        if pairing and model != "native_layered":
            raise NativeScaoFactoryError(
                "the fixed-physics pairing options "
                f"{sorted(pairing)} apply to the 'native_layered' atmosphere only."
            )
        if screen_grid_size is not None and model != "native_frozen_flow_v2":
            raise NativeScaoFactoryError(
                "screen_grid_size applies to the 'native_frozen_flow_v2' atmosphere only."
            )
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
            # Off-grid quadrature modes are translated by exact spectral
            # replay, not periodic interpolation. Four-by-four spectral
            # quadrature plus subharmonics approximates continuum covariance;
            # finite-band/depth errors still require convergence checks. The
            # oversize primarily supplies travel room, not an RMS correction.
            # An explicit `screen_grid_size` replaces the default oversize for
            # a longer run; it changes the realization and the component hash.
            "native_frozen_flow_v2": lambda: FrozenFlowAtmosphere(
                FrozenFlowAtmosphereConfig(
                    grid_size=geometry.pupil_shape[0],
                    screen_grid_size=(
                        SCREEN_OVERSIZE_FACTOR * geometry.pupil_shape[0]
                        if screen_grid_size is None
                        else screen_grid_size
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
            # Several independent von Karman layers, each with its own Cn2
            # fraction and wind, summed on axis.  Absolutely normalized by r0
            # and L0 and free of any travel budget: see layered_atmosphere.
            "native_layered": lambda: _layered_atmosphere(
                geometry=geometry,
                random_streams=random_streams,
                r0_m=r0_m,
                outer_scale_m=outer_scale_m,
                phase_reference_wavelength_m=phase_reference_wavelength_m,
                target_rms_rad=target_rms_rad,
                normalize_rms=normalize_rms,
                layers=layers,
                band_coefficient_storage=band_coefficient_storage,
                pairing=pairing,
            ),
        }
        try:
            builder = builders[model]
        except KeyError as exc:
            raise NativeScaoFactoryError(
                f"native atmosphere model {model!r} is not registered; "
                "expected 'static', 'native_frozen_flow', "
                "'native_frozen_flow_v2', or 'native_layered'.  The 'hcipy' "
                "and 'hcipy_layered' models build through backend='hcipy'."
            ) from exc
        # Each layer exposes altitude_m, cn2_fraction and wind_m_per_s (the
        # profile's AtmosphereLayerConfig); this layer never imports io.
        if bool(layers) != (model == "native_layered"):
            raise NativeScaoFactoryError(
                "atmosphere layers are accepted by, and required for, exactly "
                "the 'native_layered' model."
            )
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
        clip_negative_pixels: bool = True,
        lenslet_batch_size: int = DEFAULT_LENSLET_BATCH_SIZE,
        physical_detector: Any = None,
        telemetry_level: str = "full",
    ) -> WavefrontSensor:
        """Build the WFS.

        ``physical_detector`` (a
        :class:`~shwfs_ao.detector.physical_config.PhysicalDetectorConfig`)
        selects the physical camera path; it is passed only for schema-v7
        profiles that declare one, so every earlier profile builds the
        compatibility sensor unchanged.  ``detector_window_px`` is then the
        centroid window and the optics return blocks of ``window + 2 * guard``
        pixels.  ``telemetry_level`` is identity-neutral.
        """
        def geometric() -> WavefrontSensor:
            if isinstance(geometry, CompactShackHartmannGeometry):
                raise NativeScaoFactoryError(
                    "the compact lenslet geometry supports the detector_level WFS only."
                )
            return NativeGeometricShackHartmannSensor(geometry)

        def physical() -> WavefrontSensor:
            from ...wfs.shack_hartmann.physical_measurement import (
                PhysicalShackHartmannSensor,
            )
            from .shwfs_mft import build_mft_optics

            if detector_window_px is None:
                raise NativeScaoFactoryError("the physical path needs an explicit window.")
            block = int(detector_window_px) + 2 * int(physical_detector.guard_px)
            optics: Any
            if physical_detector.sampling.kind == "legacy_fft":
                if isinstance(geometry, CompactShackHartmannGeometry):
                    optics = BatchedNativeShackHartmannOptics(
                        geometry,
                        wfs_wavelength_m,
                        pad_factor=pad_factor,
                        detector_window_px=block,
                        batch_size=lenslet_batch_size,
                    )
                else:
                    optics = NativeShackHartmannOptics(
                        geometry,
                        wfs_wavelength_m,
                        pad_factor=pad_factor,
                        detector_window_px=block,
                    )
            else:
                optics = build_mft_optics(
                    geometry,
                    physical_detector,
                    wfs_wavelength_m=wfs_wavelength_m,
                    block_px=block,
                    batch_size=lenslet_batch_size,
                )
            return PhysicalShackHartmannSensor.calibrate(
                geometry,
                optics,
                physical_detector,
                wfs_wavelength_m=wfs_wavelength_m,
                random_streams=random_streams.scoped("native-detector-wfs"),
                centroid_config=centroid_config,
                validity_config=validity_config,
                telemetry_level=telemetry_level,
            )

        def detector_level() -> WavefrontSensor:
            if physical_detector is not None:
                return physical()
            optics: NativeShackHartmannOptics | BatchedNativeShackHartmannOptics
            if isinstance(geometry, CompactShackHartmannGeometry):
                # Batch size is an execution setting outside the identity.
                optics = BatchedNativeShackHartmannOptics(
                    geometry,
                    wfs_wavelength_m,
                    pad_factor=pad_factor,
                    detector_window_px=detector_window_px,
                    batch_size=lenslet_batch_size,
                )
            else:
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
                clip_negative_pixels=clip_negative_pixels,
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


def _layered_atmosphere(
    *,
    geometry: ShackHartmannGeometry,
    random_streams: RandomStreams,
    r0_m: float,
    outer_scale_m: float | None,
    phase_reference_wavelength_m: float,
    target_rms_rad: float | None,
    normalize_rms: bool,
    layers: Sequence[Any],
    band_coefficient_storage: str = "materialized",
    pairing: Mapping[str, Any] | None = None,
) -> LayeredFrozenFlowAtmosphere:
    if normalize_rms or target_rms_rad is not None:
        raise NativeScaoFactoryError(
            "the native_layered atmosphere is absolutely normalized; it takes "
            "neither normalize_rms nor a target RMS."
        )
    try:
        config = LayeredFrozenFlowAtmosphereConfig(
            grid_size=geometry.pupil_shape[0],
            delta_m=geometry.pupil_geometry.pixel_spacing_xy_m[0],
            pupil_diameter_m=geometry.telescope_diameter_m,
            r0_m=r0_m,
            layers=tuple(
                FrozenFlowLayer(
                    cn2_fraction=layer.cn2_fraction,
                    wind_m_per_s=tuple(layer.wind_m_per_s),
                    altitude_m=layer.altitude_m,
                )
                for layer in layers
            ),
            outer_scale_m=outer_scale_m,
            phase_reference_wavelength_m=phase_reference_wavelength_m,
            root_seed=random_streams.root_seed,
            # Pairing options are passed only when set, so the default config
            # (and its identity payload) is exactly the historical one.
            **dict(pairing or {}),
        )
    except NativeAtmosphereError as exc:
        raise NativeScaoFactoryError(f"invalid layered atmosphere configuration: {exc}") from exc
    return LayeredFrozenFlowAtmosphere(
        config,
        pupil_mask=geometry.pupil_mask,
        random_streams=random_streams.scoped("native-atmosphere"),
        band_coefficient_storage=band_coefficient_storage,
    )
