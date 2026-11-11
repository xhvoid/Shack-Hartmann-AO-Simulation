"""Off-axis science evaluation of a layered single-NGS SCAO profile.

:func:`run_off_axis_science` is the documented entry point: it builds (or
takes) a :class:`~shwfs_ao.experiments.scao.ScaoSystem`, runs one canonical
closed loop driven by the on-axis guide star, and evaluates target-centred
long-exposure images and Strehl ratios at one or more science offsets from
the same trajectory.  The default is the guide-star direction alone, ``(0,
0)`` arcsec, which reproduces the profile's on-axis science image.

Compatible profiles are those whose ``atmosphere_model`` is
``"native_layered"`` (layer altitudes are needed to displace each layer's
footprint): ``robo_ao2_22m_ngs_draft@2``, ``eso_turbulence_2m_detector@1``
and ``eso_drm_42m_scao_derived@2`` among the packaged profiles.  A profile
with any other atmosphere backend keeps its on-axis behaviour: it may run
with the default offset only, and a nonzero offset is refused with
:class:`OffAxisScienceError` naming a supported layered profile.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from ..control import FrameObserver
from ..io.configs import SystemConfig, available_system_profiles
from ..science.long_exposure import LongExposureConfig
from ..science.off_axis import (
    OffAxisLongExposure,
    OffAxisScienceError,
    OffAxisScienceResult,
    ScienceOffset,
    footprint_report,
    science_offsets,
)
from .scao import (
    ExposureOverride,
    ScaoExecutionOptions,
    ScaoSystem,
    build_scao_system,
    run_closed_loop,
)


__all__ = (
    "DOCUMENTED_LAYERED_PROFILES",
    "LAYERED_ATMOSPHERE_MODELS",
    "layered_profiles",
    "OffAxisScienceRun",
    "check_off_axis_support",
    "run_off_axis_science",
)


LAYERED_ATMOSPHERE_MODELS = frozenset({"native_layered"})
"""Atmosphere models that provide directional sampling (layer altitudes)."""


@dataclass(frozen=True)
class OffAxisScienceRun:
    """The closed-loop history and the off-axis science images of one run."""

    history: Any
    science: OffAxisScienceResult
    offsets: tuple[ScienceOffset, ...]
    footprint: dict[str, Any]
    record: dict[str, Any]


DOCUMENTED_LAYERED_PROFILES = (
    "robo_ao2_22m_ngs_draft@2",
    "eso_turbulence_2m_detector@1",
    "eso_drm_42m_scao_derived@2",
)
"""Packaged ``native_layered`` profiles the off-axis evaluation is documented for."""


def layered_profiles() -> tuple[str, ...]:
    """Every packaged profile whose atmosphere provides directional sampling."""

    from ..io.configs import load_system_profile

    names = []
    for name, version in available_system_profiles():
        config = load_system_profile(name, version)
        if config.atmosphere_model in LAYERED_ATMOSPHERE_MODELS:
            names.append(f"{name}@{version}")
    return tuple(names)


def check_off_axis_support(
    config: SystemConfig,
    offsets: Sequence[ScienceOffset] | Sequence[tuple[float, float]] | None = None,
) -> tuple[ScienceOffset, ...]:
    """Validate the offsets against the profile's atmosphere backend.

    Returns the normalized offsets.  A nonzero offset with a non-layered
    atmosphere raises :class:`OffAxisScienceError` naming the supported
    layered profiles; on-axis-only offsets pass for every backend.
    """

    if not isinstance(config, SystemConfig):
        raise OffAxisScienceError("config must be a SystemConfig.")
    resolved = science_offsets(offsets)
    if config.atmosphere_model in LAYERED_ATMOSPHERE_MODELS:
        return resolved
    off_axis = [offset.label for offset in resolved if not offset.is_on_axis]
    if off_axis:
        raise OffAxisScienceError(
            f"science offsets {', '.join(off_axis)} need layer altitudes, but "
            f"profile {config.profile.profile_id} uses "
            f"atmosphere_model={config.atmosphere_model!r}, which has no heights. "
            "Use a 'native_layered' profile such as "
            f"{', '.join(DOCUMENTED_LAYERED_PROFILES)}, or keep the default (0, 0) offset."
        )
    return resolved


def run_off_axis_science(
    config: SystemConfig,
    *,
    offsets_arcsec: Sequence[ScienceOffset] | Sequence[tuple[float, float]] | None = None,
    wavelengths_m: Sequence[float] | None = None,
    burn_in_frames: int = 0,
    stride: int = 1,
    max_samples: int | None = None,
    realization_index: int = 0,
    system: ScaoSystem | None = None,
    execution: ScaoExecutionOptions | None = None,
    exposure: ExposureOverride | None = None,
    record_instantaneous_strehl: bool = True,
    block_frames: int | None = None,
    extra_observers: Sequence[FrameObserver] = (),
) -> OffAxisScienceRun:
    """Run one closed loop and evaluate science images at every offset.

    ``offsets_arcsec`` are ``(x_arcsec, y_arcsec)`` pairs relative to the
    on-axis guide star (default ``((0, 0),)``; conventions in
    :mod:`shwfs_ao.science.off_axis`).  ``wavelengths_m`` defaults to the
    profile's science wavelengths.  ``burn_in_frames``, ``stride`` and
    ``max_samples`` select the averaged frames exactly as
    :class:`~shwfs_ao.science.long_exposure.LongExposureConfig` does; every
    offset uses the same frames, pupil, wavelengths and image sampling.
    ``system`` reuses an already-built system (the loop resets it);
    ``execution`` and ``exposure`` are passed to the loop as usual.

    The guide-star loop is identical for any list of offsets: the returned
    ``history`` (and its ``config_hash``) equals that of a run without
    science directions.
    """

    offsets = check_off_axis_support(config, offsets_arcsec)
    wavelengths = tuple(
        config.science_wavelengths_m if wavelengths_m is None else wavelengths_m
    )
    resolved = build_scao_system(config, execution=execution) if system is None else system
    if not isinstance(resolved, ScaoSystem):
        raise OffAxisScienceError("system must be a ScaoSystem or None.")
    observer = OffAxisLongExposure(
        resolved.science_propagator,
        offsets,
        LongExposureConfig(
            wavelengths_m=wavelengths,
            burn_in_frames=burn_in_frames,
            stride=stride,
            max_samples=max_samples,
        ),
        telescope_diameter_m=config.telescope_diameter_m,
        record_instantaneous_strehl=record_instantaneous_strehl,
        block_frames=block_frames,
    )
    history = run_closed_loop(
        config,
        system=resolved,
        realization_index=realization_index,
        observers=(observer, *extra_observers),
        exposure=exposure,
        science_directions_rad=observer.directions_rad,
    )
    science = observer.result()
    metadata = resolved.atmosphere.metadata
    footprint = (
        footprint_report(metadata, offsets)
        if config.atmosphere_model in LAYERED_ATMOSPHERE_MODELS
        else {"offsets": [], "note": "non-layered atmosphere: on-axis only"}
    )
    record = {
        "profile": config.profile.profile_id,
        "config_hash": config.config_hash,
        "history_config_hash": history.config_hash,
        "atmosphere_config_hash": metadata.get("config_hash"),
        "atmosphere_model": config.atmosphere_model,
        "directional_sampling": metadata.get("directional_sampling"),
        "root_seed": config.random.root_seed,
        "realization_index": realization_index,
        "atmosphere_realization_stream_id": metadata.get("random_stream_id"),
        "n_steps": config.controller.n_steps,
        "frame_rate_hz": config.controller.frame_rate_hz,
        "wfs_exposure": history.metadata.get("wfs_exposure"),
        "offsets_arcsec": [offset.to_record() for offset in offsets],
        "wavelengths_m": list(wavelengths),
        "frame_selection": science.selection.to_record(),
        "science_psf_pad_factor": config.science.psf_pad_factor,
        "max_on_axis_difference_m": science.max_on_axis_difference_m,
    }
    return OffAxisScienceRun(
        history=history,
        science=science,
        offsets=offsets,
        footprint=footprint,
        record=record,
    )
