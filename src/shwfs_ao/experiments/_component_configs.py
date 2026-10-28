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

from dataclasses import dataclass
from numbers import Integral
from typing import Any

import numpy as np

from ..control import LoopConfig
from ..control.loop import EXPOSURE_SAMPLE_RULES
from ..core.wavefront import opd_to_phase
from ..detector import CentroidConfig, CentroidValidityConfig, DetectorConfig
from ..dm import DMConfig
from ..io.configs import SystemConfig


__all__ = (
    "ExposureOverride",
    "target_rms_rad",
    "detector_config",
    "centroid_config",
    "validity_config",
    "dm_config",
    "loop_config",
    "exposure_keywords",
)


class ExposureOverrideError(ValueError):
    """Raised for an invalid WFS exposure override."""


@dataclass(frozen=True)
class ExposureOverride:
    """Run-time override of the WFS exposure quadrature (T2, G2, 2026-10-21).

    ``subsamples`` replaces the profile's ``detector_physics.exposure_subsamples``
    (``None`` keeps it); ``sample_rule`` selects the sample times:
    ``"left_point"`` (the legacy rule, samples at ``t + j*tau/n``) or
    ``"midpoint"`` (``t + (j + 1/2)*tau/n``; ``None`` keeps ``left_point``).  The
    override never enters ``SystemConfig``; it is identity-bearing through the
    loop's effective exposure (``wfs_exposure`` in the history's hash and
    metadata).  A profile without a ``detector_physics`` block keeps its
    compatibility sensor, which provides no ``measure_exposure``, so an
    override that integrates (``subsamples > 1`` or ``midpoint``) is refused by
    the loop for it.
    """

    subsamples: int | None = None
    sample_rule: str | None = None

    def __post_init__(self) -> None:
        count = self.subsamples
        if count is not None:
            if isinstance(count, (bool, np.bool_)) or not isinstance(count, Integral) or int(count) < 1:
                raise ExposureOverrideError("subsamples must be a positive integer or None.")
            object.__setattr__(self, "subsamples", int(count))
        rule = self.sample_rule
        if rule is not None and (not isinstance(rule, str) or rule not in EXPOSURE_SAMPLE_RULES):
            raise ExposureOverrideError(
                f"sample_rule must be one of {EXPOSURE_SAMPLE_RULES} or None; got {rule!r}."
            )

    @property
    def is_default(self) -> bool:
        return self.subsamples is None and self.sample_rule in (None, "left_point")


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


def exposure_keywords(
    config: SystemConfig, exposure: ExposureOverride | None = None
) -> dict[str, Any]:
    """DET-08 time quadrature, passed only when a profile (or an override) asks for it.

    Without ``exposure`` the result is exactly the historical one: ``{}`` for a
    single left-point sample, else the count and the duration.  An
    :class:`ExposureOverride` replaces the count and/or selects the midpoint
    rule; the rule keyword is added only when it is not the default, so every
    legacy left-point call keeps its keywords, hash and metadata.
    """

    if exposure is not None and not isinstance(exposure, ExposureOverride):
        raise ExposureOverrideError("exposure must be an ExposureOverride or None.")
    physics = config.detector_physics
    subsamples = 1 if physics is None else int(physics.exposure_subsamples)
    rule = "left_point"
    if exposure is not None:
        if exposure.subsamples is not None:
            subsamples = exposure.subsamples
        if exposure.sample_rule is not None:
            rule = exposure.sample_rule
    if rule == "left_point" and subsamples == 1:
        return {}
    keywords: dict[str, Any] = {
        "exposure_subsamples": subsamples,
        "exposure_s": float(config.detector.exposure_s),
    }
    if rule != "left_point":
        keywords["exposure_sample_rule"] = rule
    return keywords
