"""Translate a :class:`~shwfs_ao.io.configs.SystemConfig` into component configurations.

These are the pure, field-by-field conversions from a serialized SCAO profile
to the configuration records of the components it builds: the compatibility
detector, the centroid estimator and its validity gates, the DM, the control
loop, the atmosphere's RMS target in phase, and the exposure-sampling keywords
of the loop.  They hold no state, read nothing but the configuration, and
cannot fail for a configuration that ``SystemConfig`` accepted.

They live apart from :mod:`shwfs_ao.experiments.scao`, which owns assembly,
the backend registry, build attestation, calibration resolution and run
dispatch, so that other experiment code (for example the paired noise study in
:mod:`shwfs_ao.experiments.detector_level`) can rebuild a component chain
without reaching into that module's private names.  ``scao`` imports these
functions under its historical private names; this module imports nothing
from ``scao``.  The schema-v7 physical camera translation,
:func:`shwfs_ao.experiments.scao.physical_detector_config`, stays in ``scao``
because it is public and refuses a configuration without a
``detector_physics`` block with ``ScaoConstructionError``.
"""

from __future__ import annotations

from typing import Any

from ..control import LoopConfig
from ..core.wavefront import opd_to_phase
from ..detector import CentroidConfig, CentroidValidityConfig, DetectorConfig
from ..dm import DMConfig
from ..io.configs import SystemConfig


__all__ = (
    "target_rms_rad",
    "detector_config",
    "centroid_config",
    "validity_config",
    "dm_config",
    "loop_config",
    "exposure_keywords",
)


def target_rms_rad(config: SystemConfig) -> float | None:
    if config.atmosphere.target_rms_opd_m is None:
        return None
    return float(
        opd_to_phase(
            config.atmosphere.target_rms_opd_m,
            config.atmosphere.r0_reference_wavelength_m,
        )
    )


def detector_config(config: SystemConfig) -> DetectorConfig:
    detector = config.detector
    source_note = (
        f"SCAO profile {config.profile.profile_name}@"
        f"{config.profile.profile_version}; detector settings are serialized "
        "profile inputs, not backend defaults."
    )
    return DetectorConfig(
        photons_per_subap_frame=detector.photons_per_subap_frame,
        read_noise_e=detector.read_noise_e,
        dark_e_per_s=detector.dark_e_per_s,
        background_e_per_pixel_frame=detector.background_e_per_pixel_frame,
        full_well_e=detector.full_well_e,
        qe=detector.qe,
        prnu_rms=detector.prnu_rms,
        exposure_s=detector.exposure_s,
        source_class=config.profile.provenance.source_class,
        source_note=source_note,
        prnu_mode=detector.prnu_mode,
        bad_pixel_fraction=detector.bad_pixel_fraction,
    )


def centroid_config(config: SystemConfig) -> CentroidConfig:
    return CentroidConfig(
        estimator=config.wfs.centroid_estimator,
        threshold_fraction=config.wfs.threshold_fraction,
        subtract_minimum=config.wfs.subtract_minimum,
    )


def validity_config(config: SystemConfig) -> CentroidValidityConfig:
    return CentroidValidityConfig(
        min_flux_e=config.wfs.min_flux_e,
        min_peak_snr=config.wfs.min_peak_snr,
        max_centroid_sigma_px=config.wfs.max_centroid_sigma_px,
        max_window_clipping_fraction=(
            config.wfs.max_window_clipping_fraction
        ),
    )


def dm_config(config: SystemConfig) -> DMConfig:
    dm = config.dm
    return DMConfig(
        telescope_diameter_m=config.telescope_diameter_m,
        n_actuators_across=config.actuators_across,
        influence_model=dm.influence_model,
        coupling_width_pitch=dm.coupling_width_pitch,
        stroke_limit_nm=dm.stroke_limit_opd_m * 1.0e9,
        include_edge_actuators=dm.include_edge_actuators,
        actuator_margin_fraction=dm.actuator_margin_fraction,
        dead_actuator_indices=dm.dead_actuator_indices,
        stuck_actuator_indices=dm.stuck_actuator_indices,
        stuck_command_nm=dm.stuck_command_opd_m * 1.0e9,
        source_class=config.profile.provenance.source_class,
        source_note=(
            f"SCAO profile {config.profile.profile_name}@"
            f"{config.profile.profile_version}; DM values are explicit."
        ),
    )


def loop_config(config: SystemConfig) -> LoopConfig:
    controller = config.controller
    return LoopConfig(
        n_steps=controller.n_steps,
        gain=controller.gain,
        leak=controller.leak,
        latency_frames=controller.latency_frames,
        frame_rate_hz=controller.frame_rate_hz,
        root_seed=config.random.root_seed,
    )


def exposure_keywords(config: SystemConfig) -> dict[str, Any]:
    """DET-08 time quadrature, passed only when a profile asks for it."""

    physics = config.detector_physics
    if physics is None or physics.exposure_subsamples == 1:
        return {}
    return {
        "exposure_subsamples": int(physics.exposure_subsamples),
        "exposure_s": float(config.detector.exposure_s),
    }
