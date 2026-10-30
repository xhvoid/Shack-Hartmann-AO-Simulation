"""Fixed-physics convergence runs for the detector-level profiles .

One *setting* of a numerical axis is a :class:`~shwfs_ao.io.configs.SystemConfig`
built in code from a packaged profile by :func:`scan_configuration` (pupil
samples per lenslet, detector-plane oversampling, spectral nodes, science
pad); the WFS exposure rule and count travel as an
:class:`~shwfs_ao.experiments.scao.ExposureOverride`, the paired turbulence
input as :class:`~shwfs_ao.experiments.scao.LayeredAtmosphereOptions`.
:func:`fixed_physics_paired_run` runs one setting's two arms, the
operating-expectation twin (noiseless, deterministic given the paired input:
the primary convergence arm) and the noise-on arm, each in its own freshly
built system, with streaming reductions only:

* the loop history's scalar series (the history itself is bounded by frames
  times actuators, as in every run);
* the streamed long-exposure science image per wavelength, with the
  production metrics and the validation-only Fourier encircled-energy
  reference beside them;
* the paired per-frame ``DeltaV_t`` (piston-removed pupil mean square of the
  noisy-minus-twin post-update residual map) from a **disk-backed** float64
  record of the twin arm's post-burn-in pupil samples (``numpy`` ``.npy``
  memory map in a caller-owned scratch directory, removed after the run, its
  size recorded), streamed against the noisy arm frame by frame, so the
  resident memory is two pupil vectors rather than two map stacks.  The
  variance of a difference is never inferred from two RMS values; when the
  paired quantity is disabled it is marked unavailable;
* the retained lenslet identifiers (digest and count), the illuminated-area
  statistics of the lenslet cells, the detected-electron budget and the
  spectral nodes, the atmosphere's pairing metadata and the effective
  exposure, all recorded per arm;
* the open-loop RMS series digest of each arm, which every arm of one setting
  must share (the atmosphere is identical) and which non-pupil axes share
  across settings.

Nothing here changes a profile, a metric definition, ``paired_noise_run`` or
the gated evidence runner; the module is the experiment core of
``scripts/detector_level_convergence_study.py`` and of its tests.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import replace
import hashlib
import math
import os
from pathlib import Path
import resource
import sys
import time
from typing import Any

import numpy as np

from ..control.loop import run_closed_loop as run_component_loop
from ..detector.physical_config import BandpassConfig, physical_budget
from ..io.configs import RandomSeedConfig, SystemConfig
from ..science.long_exposure import LongExposureConfig, StreamingLongExposure
from ..validation.encircled_energy import EncircledEnergyError, fourier_encircled_energy
from ._component_configs import ExposureOverride, exposure_keywords, loop_config
from .detector_level import _OperatingExpectationSensor
from .scao import (
    LayeredAtmosphereOptions,
    ScaoExecutionOptions,
    build_scao_system,
    physical_detector_config,
)


__all__ = (
    "CONVERGENCE_RUN_SCHEMA",
    "CONVERGENCE_ARMS",
    "ConvergenceStudyError",
    "scan_configuration",
    "fixed_physics_paired_run",
    "planned_physics_record",
    "series_digest",
)

CONVERGENCE_RUN_SCHEMA = "shwfs_ao.experiments.convergence_study.paired_run.v1"
# The twin runs first: it is the primary convergence arm and the paired
# reference the noisy arm's DeltaV_t is streamed against.
CONVERGENCE_ARMS = ("operating_expectation", "noise_on")
DELTA_V_RECORD_DTYPE = "float64"


class ConvergenceStudyError(ValueError):
    """Raised for an unsupported setting or a broken paired-run contract."""


def scan_configuration(
    base: SystemConfig,
    *,
    samples_per_lenslet: int | None = None,
    oversampling: int | None = None,
    spectral_nodes: int | None = None,
    science_pad: int | None = None,
    n_steps: int | None = None,
    root_seed: int | None = None,
) -> SystemConfig:
    """One numerical setting of ``base`` built in code; every physical input stays the profile's.

    ``samples_per_lenslet`` sets ``pupil_pixels = lenslets_across * samples``
    (the detector pixel scale, window and guard are declared constants of the
    physical camera path and do not move); ``oversampling`` the detector-plane
    Gauss--Legendre order per pixel; ``spectral_nodes`` the number of
    Gauss--Legendre nodes on the profile's own band (the band edges, source
    and sky are unchanged: the detected budget converges with the nodes and
    is recorded, never renormalized); ``science_pad`` the science angular
    sampling.  Anything left ``None`` keeps the profile's value.
    """

    if not isinstance(base, SystemConfig):
        raise ConvergenceStudyError("base must be a SystemConfig.")
    config = base
    if samples_per_lenslet is not None:
        samples = _positive_int(samples_per_lenslet, "samples_per_lenslet")
        config = replace(config, pupil_pixels=int(config.lenslets_across) * samples)
    if oversampling is not None or spectral_nodes is not None:
        physics = config.detector_physics
        if physics is None:
            raise ConvergenceStudyError(
                "oversampling and spectral_nodes need a detector_physics profile."
            )
        if oversampling is not None:
            physics = replace(
                physics,
                sampling=replace(physics.sampling, oversampling=_positive_int(oversampling, "oversampling")),
            )
        if spectral_nodes is not None:
            bandpass = physics.bandpass
            if bandpass.kind != "gauss_legendre":
                raise ConvergenceStudyError(
                    "spectral_nodes refines a gauss_legendre bandpass only; the profile declares "
                    f"{bandpass.kind!r}."
                )
            physics = replace(
                physics,
                bandpass=BandpassConfig(
                    kind="gauss_legendre",
                    band_min_m=bandpass.band_min_m,
                    band_max_m=bandpass.band_max_m,
                    n_samples=_positive_int(spectral_nodes, "spectral_nodes"),
                ),
            )
        config = replace(config, detector_physics=physics)
    if science_pad is not None:
        config = replace(config, science=replace(config.science, psf_pad_factor=_positive_int(science_pad, "science_pad")))
    if n_steps is not None:
        config = replace(config, controller=replace(config.controller, n_steps=_positive_int(n_steps, "n_steps")))
    if root_seed is not None:
        config = replace(config, random=RandomSeedConfig(root_seed=_nonnegative_int(root_seed, "root_seed")))
    return config


def series_digest(values: np.ndarray) -> str:
    """SHA-256 of a float64 series' bytes (the open-loop RMS pairing check)."""

    array = np.ascontiguousarray(np.asarray(values, dtype=np.float64))
    return hashlib.sha256(array.tobytes()).hexdigest()


class _DiskPupilRecorder:
    """Writes each post-burn-in post-update residual map's pupil samples to a ``.npy`` memory map."""

    requested_fields = frozenset({"post_update_residual_opd_m"})

    def __init__(self, path: Path, *, start_frame: int, n_frames: int) -> None:
        self._path = Path(path)
        self._start = int(start_frame)
        self._count = int(n_frames) - self._start
        if self._count < 1:
            raise ConvergenceStudyError("burn-in leaves no analysed frame.")
        self.mask: np.ndarray | None = None
        self._store: np.memmap | None = None
        self.frames_written = 0

    def observe(self, observation: Any) -> None:
        index = int(observation.frame_index)
        if index < self._start:
            return
        opd = np.asarray(observation.post_update_residual_opd_m, dtype=float)
        if self.mask is None:
            self.mask = np.isfinite(opd)
            if self._path.exists():
                raise ConvergenceStudyError(f"{self._path} exists; the paired record is never overwritten.")
            self._store = np.lib.format.open_memmap(
                self._path, mode="w+", dtype=np.float64, shape=(self._count, int(np.count_nonzero(self.mask)))
            )
        assert self._store is not None
        slot = index - self._start
        if slot != self.frames_written or slot >= self._count:
            raise ConvergenceStudyError("frames must arrive in order within the analysed window.")
        self._store[slot] = opd[self.mask]
        self.frames_written += 1

    def close(self) -> int:
        """Flush the record and return its size in bytes."""

        if self._store is not None:
            self._store.flush()
            del self._store
            self._store = None
        return int(self._path.stat().st_size) if self._path.exists() else 0


class _StreamingDeltaV:
    """Streams the noisy arm's maps against the twin's disk record: per-frame ``DeltaV_t`` only."""

    requested_fields = frozenset({"post_update_residual_opd_m"})

    def __init__(self, path: Path, mask: np.ndarray, *, start_frame: int) -> None:
        self._store = np.load(path, mmap_mode="r")
        self._mask = np.asarray(mask, dtype=bool)
        self._start = int(start_frame)
        self.delta_v_m2: list[float] = []
        self.noisy_mean_square_m2: list[float] = []
        self.twin_mean_square_m2: list[float] = []

    def observe(self, observation: Any) -> None:
        index = int(observation.frame_index)
        if index < self._start:
            return
        slot = index - self._start
        if slot != len(self.delta_v_m2):
            raise ConvergenceStudyError("frames must arrive in order within the analysed window.")
        opd = np.asarray(observation.post_update_residual_opd_m, dtype=float)
        if not np.array_equal(np.isfinite(opd), self._mask):
            raise ConvergenceStudyError("the noisy arm's pupil support differs from the twin's.")
        noisy = opd[self._mask]
        twin = np.asarray(self._store[slot], dtype=float)
        delta = noisy - twin
        delta -= np.mean(delta)
        self.delta_v_m2.append(float(np.mean(delta * delta)))
        centred_noisy = noisy - np.mean(noisy)
        centred_twin = twin - np.mean(twin)
        self.noisy_mean_square_m2.append(float(np.mean(centred_noisy * centred_noisy)))
        self.twin_mean_square_m2.append(float(np.mean(centred_twin * centred_twin)))

    def close(self) -> None:
        del self._store


def _block_mean_and_error(values: Sequence[float], block_frames: int) -> tuple[float, float | None]:
    array = np.asarray(values, dtype=float)
    usable = array[: array.size // block_frames * block_frames]
    blocks = usable.reshape(-1, block_frames).mean(axis=1) if usable.size else np.empty(0)
    error = float(np.std(blocks, ddof=1) / math.sqrt(blocks.size)) if blocks.size > 1 else None
    return float(np.mean(array)), error


def _geometry_record(geometry: Any) -> dict[str, Any]:
    """Retained lenslet identifiers (digest and count) and illuminated-area statistics."""

    ids = tuple(str(item) for item in geometry.subaperture_ids)
    counts = np.asarray(geometry.illuminated_counts, dtype=float) if hasattr(geometry, "illuminated_counts") else None
    bounds = getattr(geometry, "lenslet_bounds_rc", None)
    if counts is not None and bounds is not None:
        cells = np.asarray([(r1 - r0) * (c1 - c0) for r0, r1, c0, c1 in np.asarray(bounds)], dtype=float)
        fractions = counts / cells
    else:
        masks = geometry.subaperture_masks
        rows, columns = geometry.pupil_shape
        cell = (rows / geometry.n_lenslets_across) * (columns / geometry.n_lenslets_across)
        fractions = np.asarray([np.count_nonzero(mask) for mask in masks], dtype=float) / cell
    return {
        "retained_lenslet_count": len(ids),
        "retained_lenslet_ids_sha256": hashlib.sha256("\n".join(ids).encode("utf-8")).hexdigest(),
        "pupil_shape": [int(value) for value in geometry.pupil_shape],
        "pupil_samples": int(np.count_nonzero(np.asarray(geometry.pupil_mask))),
        "illuminated_area_fraction": {
            "mean": float(np.mean(fractions)),
            "min": float(np.min(fractions)),
            "max": float(np.max(fractions)),
            "unit": "fraction of the lenslet cell's samples",
        },
        "geometry_hash": str(geometry.geometry_hash),
    }


def _budget_record(config: SystemConfig, wfs: Any) -> dict[str, Any]:
    """The detected-electron budget and spectral nodes the sensor was built with."""

    physics = physical_detector_config(config)
    geometry = wfs.geometry
    full_area = (float(geometry.telescope_diameter_m) / float(geometry.n_lenslets_across)) ** 2
    pixel_scale = physics.sampling.pixel_scale_rad
    if pixel_scale is None:
        raise ConvergenceStudyError("the detector-plane sampling declares no pixel scale.")
    scale = float(pixel_scale)
    budget = physical_budget(
        physics,
        wfs_wavelength_m=config.wfs_wavelength_m,
        full_subaperture_area_m2=full_area,
        pixel_solid_angle_sr=scale * scale,
    )
    detected = np.asarray(wfs.detected_e_per_subap, dtype=float)
    return {
        "detected_e_full_subaperture_per_frame": budget.detected_e_full_subap,
        "sky_e_per_pixel_full_subaperture_per_frame": budget.sky_e_per_pixel_full_subap,
        "retained_lenslet_detected_e": {"max": float(np.max(detected)), "mean": float(np.mean(detected)), "min": float(np.min(detected))},
        "spectral_nodes_m": [float(value) for value in budget.wavelength_m],
        "spectral_weights": [float(value) for value in budget.spectral_weights],
        "bandpass": {"kind": physics.bandpass.kind, "band_min_m": physics.bandpass.band_min_m, "band_max_m": physics.bandpass.band_max_m, "n_samples": physics.bandpass.n_samples},
        "pixel_scale_rad": scale,
        "oversampling": int(physics.sampling.oversampling),
        "diffusion_sigma_px": float(physics.sampling.diffusion_sigma_px),
        "exposure_s": float(physics.exposure_s),
        "configured_exposure_subsamples": int(physics.exposure_subsamples),
    }


def planned_physics_record(
    config: SystemConfig,
    *,
    exposure: ExposureOverride | None = None,
    atmosphere_options: Any = None,
) -> dict[str, Any]:
    """The physical inputs a run of ``config`` must record, derived from the plan alone.

    No system is built.  The detector physics comes from the profile block, the
    spectral nodes from its bandpass quadrature at the WFS wavelength (the call
    :func:`physical_budget` makes), the exposure keywords from the override, and
    the screen geometry from the layered-atmosphere configuration the native
    factory builds (``None`` for another atmosphere model).  A study's row check
    compares a retained row against this record, so a retained result cannot
    carry a physical input the plan did not ask for, however consistent its own
    fields are with one another.
    """

    physics = physical_detector_config(config)
    quadrature = physics.bandpass.quadrature(config.wfs_wavelength_m)
    pixel_scale = physics.sampling.pixel_scale_rad
    record: dict[str, Any] = {
        "exposure_s": float(physics.exposure_s),
        "configured_exposure_subsamples": int(physics.exposure_subsamples),
        "oversampling": int(physics.sampling.oversampling),
        "pixel_scale_rad": None if pixel_scale is None else float(pixel_scale),
        "diffusion_sigma_px": float(physics.sampling.diffusion_sigma_px),
        "bandpass": {
            "kind": physics.bandpass.kind, "band_min_m": physics.bandpass.band_min_m,
            "band_max_m": physics.bandpass.band_max_m, "n_samples": physics.bandpass.n_samples,
        },
        "spectral_nodes_m": [float(value) for value in quadrature.wavelength_m],
        "exposure_keywords": _jsonable(exposure_keywords(config, exposure)),
        "atmosphere": None,
    }
    if config.atmosphere_model == "native_layered":
        # Imported here: the experiment layer stays backend-neutral at import time.
        from ..backends.native.layered_atmosphere import FrozenFlowLayer, LayeredFrozenFlowAtmosphereConfig

        layers = tuple(
            FrozenFlowLayer(
                cn2_fraction=layer.cn2_fraction,
                wind_m_per_s=(float(layer.wind_m_per_s[0]), float(layer.wind_m_per_s[1])),
                altitude_m=layer.altitude_m,
            )
            for layer in config.atmosphere.layers
        )
        keywords = {} if atmosphere_options is None else atmosphere_options.factory_keywords()
        layered = LayeredFrozenFlowAtmosphereConfig(
            grid_size=int(config.pupil_pixels),
            delta_m=float(config.telescope_diameter_m) / (int(config.pupil_pixels) - 1),
            pupil_diameter_m=float(config.telescope_diameter_m),
            r0_m=config.atmosphere.r0_m,
            layers=layers,
            outer_scale_m=config.atmosphere.outer_scale_m,
            root_seed=1,
            **keywords,
        )
        reference = layered.band_draw_reference_screen_size
        record["atmosphere"] = {
            "model_kind": "layered_fourier_frozen_flow",
            "grid_shape": [int(config.pupil_pixels), int(config.pupil_pixels)],
            "grid_delta_m": float(layered.delta_m),
            "pupil_diameter_m": float(layered.pupil_diameter_m),
            "screen_size": int(layered.screen_size),
            "screen_period_m": float(layered.screen_period_m),
            "pairing_active": bool(layered.pairing_active),
            "band_limit_half_width_index": layered.band_limit_half_width_index,
            "reference_draw_normals_per_layer": None if reference is None else 2 * reference * reference,
            "frequency_spacing_per_m": 1.0 / float(layered.screen_period_m),
        }
    return record


def _atmosphere_record(atmosphere: Any) -> dict[str, Any]:
    metadata = dict(atmosphere.metadata)
    keys = (
        "config_hash", "model_kind", "grid_shape", "grid_delta_m", "pupil_diameter_m", "screen_size", "screen_period_m",
        "realization_index", "random_stream_id", "band_coefficient_storage",
        "band_draw_reference_screen_size", "band_limit_screen_size", "band_limit_half_width_index",
        "screen_period_rule", "paired_band_algorithm", "band_power_retained_fraction", "frequency_spacing_per_m",
        "frequency_unit", "reference_draw_normals_per_layer",
    )
    record = {key: _jsonable(metadata[key]) for key in keys if key in metadata}
    record["pairing_active"] = bool(getattr(getattr(atmosphere, "config", None), "pairing_active", False))
    return record


def _jsonable(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    if isinstance(value, np.generic):
        return value.item()
    if isinstance(value, np.ndarray):
        return value.tolist()
    if hasattr(value, "items") and not isinstance(value, (str, bytes)):
        return {str(key): _jsonable(item) for key, item in dict(value).items()}
    return value


def _science_record(result: Any, *, window_frames: int) -> list[dict[str, Any]]:
    """Production metrics beside the Fourier reference, per wavelength."""

    records = []
    for image in result.images:
        psf = image.psf
        entry: dict[str, Any] = {
            "production": image.metrics.to_record(),
            "psf_sum": float(np.sum(psf.intensity)),
            "psf_shape": [int(value) for value in psf.intensity.shape],
            "psf_pad_factor": int(psf.sampling_metadata["pad_factor"]),
            "focal_pixel_scale_xy_rad": [float(v) for v in psf.sampling_metadata["focal_pixel_scale_xy_rad"]],
            "frames_integrated": int(window_frames),
        }
        try:
            oracle = fourier_encircled_energy(psf.intensity, psf.x_angle_rad, psf.y_angle_rad)
            ideal = fourier_encircled_energy(image.ideal_psf.intensity, image.ideal_psf.x_angle_rad, image.ideal_psf.y_angle_rad)
            entry["fourier_reference"] = {
                **oracle.to_record(),
                "ee50_radius_rad": oracle.radius(0.5),
                "ee80_radius_rad": oracle.radius(0.8),
                "ideal_ee50_radius_rad": ideal.radius(0.5),
                "ideal_ee80_radius_rad": ideal.radius(0.8),
                "fraction_at_production_ee50": oracle.fraction(float(image.metrics.ee50_radius_rad)),
                "monotone_fraction_scan": oracle.monotone_fraction_scan(),
                "status": "available",
            }
        except EncircledEnergyError as exc:
            entry["fourier_reference"] = {"status": "unavailable", "reason": str(exc)[:300]}
        records.append(entry)
    return records


def _arm_record(history: Any, window: slice) -> dict[str, Any]:
    post = np.asarray(history.post_update_residual_opd_rms_m, dtype=float)
    pre = np.asarray(history.pre_update_residual_opd_rms_m, dtype=float)
    open_loop = np.asarray(history.open_loop_opd_rms_m, dtype=float)
    valid = np.asarray(history.valid_measurement_fraction, dtype=float)
    usable = np.asarray(history.reconstruction_usable, dtype=bool)
    saturation = np.asarray(history.saturation_fraction, dtype=float)
    metadata = dict(history.metadata)
    return {
        "loop_config_hash": history.config_hash,
        "component_hashes": dict(metadata["component_hashes"]),
        "random_stream_ids": dict(metadata["random_stream_ids"]),
        "atmosphere_realization_stream_id": metadata.get("atmosphere_realization_stream_id"),
        "wfs_exposure": _jsonable(metadata.get("wfs_exposure")),
        "recovery": _jsonable(metadata.get("recovery")),
        "retained_subaperture_count": int(metadata["retained_subaperture_count"]),
        "open_loop_rms_series_sha256": series_digest(open_loop),
        "open_loop_rms_m": float(np.mean(open_loop[window])),
        "post_update_rms_m": float(np.mean(post[window])),
        "post_update_mean_square_m2": float(np.mean(post[window] ** 2)),
        "pre_update_rms_m": float(np.mean(pre[window])),
        "pre_update_mean_square_m2": float(np.mean(pre[window] ** 2)),
        "final_post_update_rms_m": float(post[-1]),
        "lost_lock": bool(post[-1] > open_loop[-1]),
        "valid_measurement_fraction": {"mean": float(np.mean(valid[window])), "min": float(np.min(valid[window]))},
        "reconstruction_usable_fraction": float(np.mean(usable[window])),
        "rejected_frames_after_burn_in": int(np.count_nonzero(~usable[window])),
        "saturation_fraction": {"max": float(np.max(saturation[window])), "mean": float(np.mean(saturation[window]))},
        "units": {"rms": "m", "mean_square": "m2", "fractions": "1"},
        "metric_time_convention": "frame-start residual (the atmosphere sample at t); the WFS exposure samples later times only",
    }


def _peak_rss_bytes() -> int:
    peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return int(peak if sys.platform == "darwin" else peak * 1024)


def fixed_physics_paired_run(
    config: SystemConfig,
    *,
    root_seed: int,
    realization_index: int,
    n_steps: int,
    burn_in_frames: int,
    execution: ScaoExecutionOptions | None = None,
    atmosphere_options: LayeredAtmosphereOptions | None = None,
    exposure: ExposureOverride | None = None,
    arms: Sequence[str] = CONVERGENCE_ARMS,
    paired_delta_v: bool = True,
    scratch_directory: Path | None = None,
    block_frames: int = 10,
) -> dict[str, Any]:
    """Run one setting's arms with streaming reductions and return a JSON-ready record.

    ``config`` is the setting (see :func:`scan_configuration`); its root seed
    and frame count are replaced by ``root_seed`` and ``n_steps``.  Each arm
    builds its own system with the same ``atmosphere_options`` and runs the
    component loop with the ``exposure`` override's keywords.  With
    ``paired_delta_v`` and both arms, the twin's post-burn-in pupil samples go
    to a ``.npy`` memory map under ``scratch_directory`` (required then) and
    are streamed against the noisy arm; the file is removed afterwards and its
    size recorded.  The per-arm records keep every quantity apart (no RMS is
    turned into a variance of a difference).
    """

    arm_names = tuple(arms)
    unknown = [arm for arm in arm_names if arm not in CONVERGENCE_ARMS]
    if unknown or len(set(arm_names)) != len(arm_names) or not arm_names:
        raise ConvergenceStudyError(f"arms must be a non-empty subset of {CONVERGENCE_ARMS} in that order.")
    if list(arm_names) != [arm for arm in CONVERGENCE_ARMS if arm in arm_names]:
        raise ConvergenceStudyError(f"arms must keep the order {CONVERGENCE_ARMS} (twin first).")
    frames = _positive_int(n_steps, "n_steps")
    burn_in = _nonnegative_int(burn_in_frames, "burn_in_frames")
    if burn_in >= frames:
        raise ConvergenceStudyError("burn_in_frames must leave at least one analysed frame.")
    if isinstance(block_frames, bool) or not isinstance(block_frames, int) or block_frames < 1:
        raise ConvergenceStudyError("block_frames must be a positive integer.")
    paired = bool(paired_delta_v) and set(arm_names) == set(CONVERGENCE_ARMS)
    if paired and scratch_directory is None:
        raise ConvergenceStudyError("paired DeltaV needs a scratch_directory for the twin arm's disk record.")
    run_config = scan_configuration(config, n_steps=frames, root_seed=root_seed)
    window = slice(burn_in, None)
    record_path: Path | None = None
    twin_mask: np.ndarray | None = None
    record_bytes = 0
    result: dict[str, Any] = {
        "schema": CONVERGENCE_RUN_SCHEMA,
        "config_hash": run_config.config_hash,
        "root_seed": int(root_seed),
        "realization_index": int(realization_index),
        "n_steps": frames,
        "burn_in_frames": burn_in,
        "analysed_frames": frames - burn_in,
        "block_frames": int(block_frames),
        "arms_order": list(arm_names),
        "atmosphere_options": None if atmosphere_options is None else atmosphere_options.to_record(),
        "exposure_override": None if exposure is None else {"subsamples": exposure.subsamples, "sample_rule": exposure.sample_rule},
        "exposure_keywords": _jsonable(exposure_keywords(run_config, exposure)),
        "execution": None if execution is None else {
            "telemetry_level": execution.telemetry_level, "atmosphere_band_storage": execution.atmosphere_band_storage,
            "lenslet_batch_size": execution.lenslet_batch_size,
        },
        "science_wavelengths_m": [float(value) for value in run_config.science_wavelengths_m],
        "arms": {},
        "timing": {},
    }
    started = time.perf_counter()
    delta: _StreamingDeltaV | None = None
    try:
        for arm in arm_names:
            build_started = time.perf_counter()
            system = build_scao_system(run_config, execution=execution, atmosphere_options=atmosphere_options)
            build_s = time.perf_counter() - build_started
            wfs = system.wfs if arm == "noise_on" else _OperatingExpectationSensor(system.wfs)
            accumulator = StreamingLongExposure(
                system.science_propagator,
                LongExposureConfig(wavelengths_m=tuple(run_config.science_wavelengths_m), burn_in_frames=burn_in),
                telescope_diameter_m=run_config.telescope_diameter_m,
            )
            observers: list[Any] = [accumulator]
            recorder: _DiskPupilRecorder | None = None
            if paired and arm == "operating_expectation":
                assert scratch_directory is not None
                Path(scratch_directory).mkdir(parents=True, exist_ok=True)
                record_path = Path(scratch_directory) / f"twin_pupil_samples_{os.getpid()}_{int(root_seed)}_{int(realization_index)}.npy"
                recorder = _DiskPupilRecorder(record_path, start_frame=burn_in, n_frames=frames)
                observers.append(recorder)
            if paired and arm == "noise_on":
                assert record_path is not None and twin_mask is not None
                delta = _StreamingDeltaV(record_path, twin_mask, start_frame=burn_in)
                observers.append(delta)
            loop_started = time.perf_counter()
            history = run_component_loop(
                loop_config(run_config),
                random_streams=system.random_streams,
                atmosphere=system.atmosphere,
                wfs=wfs,
                dm=system.dm,
                interaction_matrix=system.interaction_matrix,
                reconstructor=system.reconstructor,
                command_projector=system.command_projector,
                controller=system.controller,
                include_noise=arm == "noise_on",
                realization_index=int(realization_index),
                recovery=system.recovery_policy,
                observers=tuple(observers),
                **exposure_keywords(run_config, exposure),
            )
            loop_s = time.perf_counter() - loop_started
            science = accumulator.result()
            entry = _arm_record(history, window)
            entry["science"] = _science_record(science, window_frames=frames - burn_in)
            sensor: Any = system.wfs
            entry["geometry"] = _geometry_record(sensor.geometry)
            entry["detector_budget"] = _budget_record(run_config, sensor)
            entry["atmosphere"] = _atmosphere_record(system.atmosphere)
            entry["system_component_hashes"] = dict(system.component_hashes)
            entry["system_atmosphere_options"] = None if system.atmosphere_options is None else system.atmosphere_options.to_record()
            entry["wfs_config_hash"] = str(wfs.config_hash)
            result["arms"][arm] = entry
            result["timing"][arm] = {"build_s": build_s, "loop_s": loop_s, "per_frame_s": loop_s / frames}
            if recorder is not None:
                twin_mask = recorder.mask
                record_bytes = recorder.close()
                if recorder.frames_written != frames - burn_in:
                    raise ConvergenceStudyError("the twin arm's disk record is incomplete.")
            del system, wfs, accumulator, history, science
        digests = {arm: entry["open_loop_rms_series_sha256"] for arm, entry in result["arms"].items()}
        result["open_loop_rms_series_shared_by_arms"] = len(set(digests.values())) == 1
        if not result["open_loop_rms_series_shared_by_arms"]:
            raise ConvergenceStudyError("the arms of one setting saw different atmospheres.")
        if paired:
            assert delta is not None
            if len(delta.delta_v_m2) != frames - burn_in:
                raise ConvergenceStudyError("the paired DeltaV stream is incomplete.")
            mean, error = _block_mean_and_error(delta.delta_v_m2, block_frames)
            difference = [n - t for n, t in zip(delta.noisy_mean_square_m2, delta.twin_mean_square_m2)]
            difference_mean, difference_error = _block_mean_and_error(difference, block_frames)
            result["paired_delta_v"] = {
                "status": "available",
                "definition": "DeltaV_t: piston-removed pupil mean square of the noise_on minus operating_expectation post-update residual map, per analysed frame",
                "units": "m2",
                "delta_v_m2": [float(v) for v in delta.delta_v_m2],
                "mean_m2": mean,
                "block_standard_error_m2": error,
                "mean_square_difference_m2": difference_mean,
                "mean_square_difference_block_standard_error_m2": difference_error,
                "cross_term_mean_m2": difference_mean - mean,
                "series_axes": ["analysed_frame"],
                "series_length": frames - burn_in,
                "twin_record": {"storage": "numpy .npy memory map on disk, float64, removed after the run", "bytes": record_bytes, "dtype": DELTA_V_RECORD_DTYPE},
            }
        else:
            result["paired_delta_v"] = {
                "status": "unavailable",
                "reason": "paired DeltaV disabled or a single arm requested; it is never inferred from two RMS values",
            }
    finally:
        if delta is not None:
            delta.close()
        if record_path is not None and record_path.exists():
            record_path.unlink()
    result["timing"]["wall_s"] = time.perf_counter() - started
    result["process_peak_rss_bytes_lifetime"] = _peak_rss_bytes()
    return result


def _positive_int(value: object, label: str) -> int:
    if isinstance(value, (bool, np.bool_)) or not isinstance(value, (int, np.integer)) or int(value) < 1:
        raise ConvergenceStudyError(f"{label} must be a positive integer.")
    return int(value)


def _nonnegative_int(value: object, label: str) -> int:
    if isinstance(value, (bool, np.bool_)) or not isinstance(value, (int, np.integer)) or int(value) < 0:
        raise ConvergenceStudyError(f"{label} must be a non-negative integer.")
    return int(value)
