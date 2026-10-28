"""Passive frame observer of the explorer's 2 m trajectories.

``ExplorerObserver`` satisfies :class:`shwfs_ao.control.FrameObserver`.  It
requests only ``atmosphere_opd_m`` and ``pre_update_residual_opd_m``, which
the loop hands over as read-only snapshots after the frame's DM update; it
cannot reach the atmosphere, the random streams, the WFS, the controller or
the DM, so the loop's history and identity are unchanged by it (checked
against an observer-disabled control run).

Per frame ``k`` (sampled once, at the frame start ``k / f``) it records:

* the masked, piston-removed pupil RMS of the atmosphere and of the
  pre-update residual (``shwfs_ao.core.wavefront.masked_rms``, the loop's
  own definition), in metres OPD;
* the instantaneous peak Strehl of the matched uncorrected image (the same
  recorded atmosphere with zero DM) and of the AO-corrected image (the
  pre-update residual), from ``peak_strehl_from_discrete_flux`` against the
  zero-OPD image of the same propagator, wavelength and grid;
* SHA-256 digests of both OPD snapshots (atmosphere pairing evidence).

Over the analysis window ``[burn_in, n_steps)`` it averages instantaneous
intensities with equal weights through two production accumulators
(``science.StreamingLongExposure``; the uncorrected one is fed the recorded
atmosphere with ``add_opd``) and, as an independent second path, through
its own float64 running sums of the very images it propagated.  The mean
OPD is never propagated, nothing is recentred and residual tilt is kept.

At the declared display indices it retains the raw maps and images.  No
full image cube is kept.
"""

from __future__ import annotations

import hashlib
import math
from typing import Any, Dict, List, Optional, Sequence

import numpy as np


class ExplorerObserverError(ValueError):
    """Raised when an observation breaks the explorer's frame contract."""


class ExplorerObserver:
    requested_fields = frozenset({"atmosphere_opd_m", "pre_update_residual_opd_m"})

    def __init__(
        self,
        propagator: Any,
        *,
        wavelength_m: float,
        n_steps: int,
        burn_in: int,
        display_indices: Sequence[int],
        telescope_diameter_m: float,
        retain_all_frames: bool = False,
    ) -> None:
        from shwfs_ao.science.long_exposure import LongExposureConfig, StreamingLongExposure

        if not 0 <= int(burn_in) < int(n_steps):
            raise ExplorerObserverError("burn_in must lie inside the trajectory.")
        indices = [int(value) for value in display_indices]
        if indices != sorted(set(indices)) or any(not 0 <= value < n_steps for value in indices):
            raise ExplorerObserverError("display indices must be unique, ordered and inside the run.")
        self._propagator = propagator
        self._wavelength = float(wavelength_m)
        self._n_steps = int(n_steps)
        self._burn_in = int(burn_in)
        self._display = frozenset(indices)
        self._display_order = tuple(indices)
        self._retain_all = bool(retain_all_frames)
        analysis_count = self._n_steps - self._burn_in
        accumulator_config = LongExposureConfig(
            wavelengths_m=(self._wavelength,),
            burn_in_frames=self._burn_in,
            stride=1,
            max_samples=analysis_count,
            residual="pre_update",
        )
        self.corrected_accumulator = StreamingLongExposure(
            propagator, accumulator_config, telescope_diameter_m=telescope_diameter_m
        )
        self.uncorrected_accumulator = StreamingLongExposure(
            propagator, accumulator_config, telescope_diameter_m=telescope_diameter_m
        )
        self._ideal: Optional[Any] = None
        self._mask: Optional[np.ndarray] = None
        self._next = 0
        self._sum_uncorrected: Optional[np.ndarray] = None
        self._sum_corrected: Optional[np.ndarray] = None
        self._analysis_frames: List[int] = []
        self.frames: Dict[str, List[Any]] = {
            name: []
            for name in (
                "frame_index",
                "time_s",
                "frame_period_s",
                "latency_frames",
                "reconstruction_usable",
                "saturation_fraction",
                "atmosphere_rms_m",
                "residual_rms_m",
                "peak_strehl_uncorrected",
                "peak_strehl_corrected",
                "flux_uncorrected",
                "flux_corrected",
                "atmosphere_sha256",
                "residual_sha256",
            )
        }
        self.display: Dict[int, Dict[str, np.ndarray]] = {}
        self.all_frames: Dict[int, Dict[str, np.ndarray]] = {}
        self.axes: Optional[Dict[str, np.ndarray]] = None
        self.sampling_metadata: Optional[Dict[str, Any]] = None

    @property
    def ideal_psf(self) -> Any:
        if self._ideal is None:
            raise ExplorerObserverError("no frame observed yet.")
        return self._ideal

    @property
    def pupil_mask(self) -> np.ndarray:
        if self._mask is None:
            raise ExplorerObserverError("no frame observed yet.")
        return self._mask

    def observe(self, observation: Any) -> None:
        from shwfs_ao.core.wavefront import masked_rms
        from shwfs_ao.science.metrics import peak_strehl_from_discrete_flux

        index = int(observation.frame_index)
        if index != self._next:
            raise ExplorerObserverError(f"frames must arrive in order: expected {self._next}, got {index}.")
        self._next = index + 1
        atmosphere = observation.atmosphere_opd_m
        residual = observation.pre_update_residual_opd_m
        if atmosphere is None or residual is None:
            raise ExplorerObserverError("the loop did not provide the requested OPD maps.")
        atmosphere = np.asarray(atmosphere, dtype=float)
        residual = np.asarray(residual, dtype=float)
        finite = np.isfinite(atmosphere)
        if self._mask is None:
            self._mask = finite.copy()
            self._mask.setflags(write=False)
            self._ideal = self._propagator.psf_from_opd(
                np.zeros(atmosphere.shape, dtype=float), self._wavelength
            )
        elif not np.array_equal(finite, self._mask):
            raise ExplorerObserverError("the pupil support changed between frames.")
        if not np.array_equal(np.isfinite(residual), self._mask):
            raise ExplorerObserverError("residual and atmosphere pupil supports differ.")
        uncorrected = self._propagator.psf_from_opd(atmosphere, self._wavelength)
        corrected = self._propagator.psf_from_opd(residual, self._wavelength)
        if self.axes is None:
            self.axes = {
                "x_angle_rad": np.array(uncorrected.x_angle_rad, dtype=float),
                "y_angle_rad": np.array(uncorrected.y_angle_rad, dtype=float),
            }
            self.sampling_metadata = dict(uncorrected.sampling_metadata)
        for psf in (uncorrected, corrected):
            if not (
                np.array_equal(psf.x_angle_rad, self.axes["x_angle_rad"])
                and np.array_equal(psf.y_angle_rad, self.axes["y_angle_rad"])
            ):
                raise ExplorerObserverError("instantaneous images changed their angular grid.")
        frames = self.frames
        frames["frame_index"].append(index)
        frames["time_s"].append(float(observation.time_s))
        frames["frame_period_s"].append(float(observation.frame_period_s))
        frames["latency_frames"].append(int(observation.latency_frames))
        frames["reconstruction_usable"].append(bool(observation.reconstruction_usable))
        frames["saturation_fraction"].append(float(observation.saturation_fraction))
        frames["atmosphere_rms_m"].append(masked_rms(atmosphere, self._mask))
        frames["residual_rms_m"].append(masked_rms(residual, self._mask))
        frames["peak_strehl_uncorrected"].append(float(peak_strehl_from_discrete_flux(uncorrected, self._ideal)))
        frames["peak_strehl_corrected"].append(float(peak_strehl_from_discrete_flux(corrected, self._ideal)))
        frames["flux_uncorrected"].append(float(np.sum(uncorrected.intensity)))
        frames["flux_corrected"].append(float(np.sum(corrected.intensity)))
        frames["atmosphere_sha256"].append(hashlib.sha256(np.ascontiguousarray(atmosphere).tobytes()).hexdigest())
        frames["residual_sha256"].append(hashlib.sha256(np.ascontiguousarray(residual).tobytes()).hexdigest())

        # Production accumulators: the corrected one consumes the observation
        # itself (pre-update residual); the uncorrected one the same frame's
        # recorded atmosphere through the documented direct-feed path.
        self.corrected_accumulator.observe(observation)
        self.uncorrected_accumulator.add_opd(
            atmosphere,
            frame_index=index,
            time_s=float(observation.time_s),
            frame_period_s=float(observation.frame_period_s),
        )
        if index >= self._burn_in:
            if self._sum_uncorrected is None:
                self._sum_uncorrected = np.zeros_like(uncorrected.intensity, dtype=float)
                self._sum_corrected = np.zeros_like(corrected.intensity, dtype=float)
            assert self._sum_corrected is not None
            self._sum_uncorrected += np.asarray(uncorrected.intensity, dtype=float)
            self._sum_corrected += np.asarray(corrected.intensity, dtype=float)
            self._analysis_frames.append(index)
        if index in self._display or self._retain_all:
            snapshot = {
                "atmosphere_opd_m": atmosphere.copy(),
                "pre_update_residual_opd_m": residual.copy(),
                "held_correction_opd_m": atmosphere - residual,
                "psf_uncorrected": np.array(uncorrected.intensity, dtype=float),
                "psf_corrected": np.array(corrected.intensity, dtype=float),
            }
            if index in self._display:
                self.display[index] = snapshot
            if self._retain_all:
                self.all_frames[index] = snapshot

    def finish(self) -> Dict[str, Any]:
        """Means, accumulator results and the streaming self-consistency check."""

        if self._next != self._n_steps:
            raise ExplorerObserverError(f"observed {self._next} frames, expected {self._n_steps}.")
        expected = list(range(self._burn_in, self._n_steps))
        if self._analysis_frames != expected:
            raise ExplorerObserverError("the analysis window is not the declared contiguous interval.")
        missing = sorted(self._display - set(self.display))
        if missing:
            raise ExplorerObserverError(f"display frames {missing} were not retained.")
        count = len(expected)
        assert self._sum_uncorrected is not None and self._sum_corrected is not None
        own_uncorrected = self._sum_uncorrected / count
        own_corrected = self._sum_corrected / count
        corrected_result = self.corrected_accumulator.result()
        uncorrected_result = self.uncorrected_accumulator.result()
        accumulator_corrected = np.array(corrected_result.images[0].psf.intensity, dtype=float)
        accumulator_uncorrected = np.array(uncorrected_result.images[0].psf.intensity, dtype=float)
        for result in (corrected_result, uncorrected_result):
            selection = result.selection
            if (
                selection.first_frame != self._burn_in
                or selection.last_frame != self._n_steps - 1
                or selection.sample_count != count
                or selection.stride != 1
                or not selection.uniform_weights
            ):
                raise ExplorerObserverError("an accumulator selected a different sample set.")
        return {
            "analysis_frames": expected,
            "analysis_count": count,
            "mean_psf_uncorrected": accumulator_uncorrected,
            "mean_psf_corrected": accumulator_corrected,
            "own_mean_psf_uncorrected": own_uncorrected,
            "own_mean_psf_corrected": own_corrected,
            "streaming_max_abs_difference": {
                "uncorrected": float(np.max(np.abs(accumulator_uncorrected - own_uncorrected))),
                "corrected": float(np.max(np.abs(accumulator_corrected - own_corrected))),
            },
            "corrected_result": corrected_result,
            "uncorrected_result": uncorrected_result,
            "ideal_psf": np.array(self.ideal_psf.intensity, dtype=float),
        }


def independent_rms(values: np.ndarray, mask: np.ndarray) -> float:
    """Pupil RMS after removing the pupil mean, written without the package helper."""

    samples = np.asarray(values, dtype=float)[np.asarray(mask, dtype=bool)]
    centred = samples - samples.sum() / samples.size
    return math.sqrt(float(np.dot(centred, centred)) / samples.size)


def independent_peak_strehl(intensity: np.ndarray, ideal: np.ndarray) -> float:
    """Peak ratio on a uniform grid (equal cell solid angles)."""

    return float(np.max(intensity) / np.max(ideal))
