"""Passive observer of one generated run: the explorer observer plus observations.

``DynamicObserver`` *is* the frozen explorer observer
(``scripts/ao_explorer/observer.py``): every frame goes through
``ExplorerObserver.observe`` first, which computes the matched uncorrected
image (the frame's atmosphere, zero DM) and the AO-corrected image (its
pre-update residual) with the canonical science propagator, the masked RMS
and peak Strehl values, the atmosphere/residual digests and the two
production long-exposure accumulators.  The explorer observer is asked to hand
over every frame's snapshot (its display set is the whole run); this class
takes each snapshot as soon as it arrives and keeps only what replay needs,
so memory does not grow with the run.

For every frame it adds, from the numerical images (never from a rendered
picture):

* the instantaneous synthetic observations ``scene (*) PSF_unc(t)`` and
  ``scene (*) PSF_AO(t)`` -- exact linear zero-extended convolution of the
  fixed binary with the frame's PSF, cropped to the native angular window by
  coordinates (``scripts/ao_explorer/binary_scene.py``), with full/cropped
  flux bookkeeping;
* for frames in the analysis window ``[burn_in, n)``: running equal-weight sums
  of those observation images and of the PSFs.  Every eligible frame is
  added, whether or not it is kept for replay, so the running and final
  averages do not depend on the display stride;
* per-kind display statistics of the three OPD maps (pupil mean removed for
  display and the 99.5th percentile of the remainder) used to choose one
  colour limit for the whole run.

At the transported (replay) frames it keeps float32 display crops of the
maps, PSFs, instantaneous observations and running-average observations at
that physical time, plus the float64 maps for the display bookkeeping.

The observer only reads the read-only snapshots the loop hands to observers;
it cannot reach the atmosphere, random streams, WFS, controller or DM.  The
optional ``progress`` callback receives (frame index, physical time) after
the frame is fully processed; it is a pure notification.
"""

from __future__ import annotations

import math
from typing import Any, Callable, Dict, List, Optional, Sequence

import numpy as np

import binary_scene
import contract
from observer import ExplorerObserver, ExplorerObserverError, independent_peak_strehl, independent_rms


MAP_KEYS = (
    ("atmosphere", "atmosphere_opd_m"),
    ("correction", "held_correction_opd_m"),
    ("residual", "pre_update_residual_opd_m"),
)


def direct_dft_psf(opd_m: np.ndarray, mask: np.ndarray, wavelength_m: float, pupil_x_m: np.ndarray,
                   pupil_y_m: np.ndarray, x_angle_rad: np.ndarray, y_angle_rad: np.ndarray) -> np.ndarray:
    """Independent unit-flux PSF by an explicit discrete Fourier sum (no FFT, no shifts).

    ``E(x, y) = mask * exp(i 2 pi OPD / lambda)``;
    ``I(tx, ty) = |sum_xy E exp(-i 2 pi (x tx + y ty) / lambda)|^2``, normalized to
    unit total flux over the evaluated grid.  The pupil origin only adds a
    linear phase to the focal field, so it does not enter ``I``.
    """

    field = np.where(mask, np.exp(1j * 2.0 * math.pi * np.where(mask, opd_m, 0.0) / wavelength_m), 0.0)
    fx = np.exp(-2j * math.pi * np.outer(x_angle_rad, pupil_x_m) / wavelength_m)
    fy = np.exp(-2j * math.pi * np.outer(y_angle_rad, pupil_y_m) / wavelength_m)
    focal = fy @ field @ fx.T
    intensity = np.abs(focal) ** 2
    return intensity / intensity.sum()


class DynamicObserver(ExplorerObserver):
    def __init__(
        self,
        propagator: Any,
        *,
        wavelength_m: float,
        n_steps: int,
        burn_in: int,
        transported: Sequence[int],
        telescope_diameter_m: float,
        scene_bundle: Dict[str, Any],
        pupil_x_m: np.ndarray,
        pupil_y_m: np.ndarray,
        oracle_frames: Sequence[int] = (),
        progress: Optional[Callable[[int, float], None]] = None,
    ) -> None:
        super().__init__(
            propagator,
            wavelength_m=wavelength_m,
            n_steps=n_steps,
            burn_in=burn_in,
            display_indices=list(range(int(n_steps))),
            telescope_diameter_m=telescope_diameter_m,
        )
        indices = [int(value) for value in transported]
        if indices != sorted(set(indices)) or any(not 0 <= value < n_steps for value in indices):
            raise ExplorerObserverError("transported frames must be unique, ordered and inside the run.")
        self.transported = tuple(indices)
        self._transported_set = frozenset(indices)
        self._scene = scene_bundle
        self._pupil_x = np.asarray(pupil_x_m, dtype=float)
        self._pupil_y = np.asarray(pupil_y_m, dtype=float)
        self._oracle_frames = frozenset(int(value) for value in oracle_frames)
        self._progress = progress
        self._crop: Optional[tuple] = None
        self._count = 0
        self._psf_sum: Dict[str, Optional[np.ndarray]] = {"uncorrected": None, "corrected": None}
        self._obs_sum: Dict[str, Optional[np.ndarray]] = {"uncorrected": None, "corrected": None}
        self._full_flux_sum = {"uncorrected": 0.0, "corrected": 0.0}
        self.display_percentile_m: Dict[str, List[float]] = {key: [] for key, _ in MAP_KEYS}
        self.running_strehl: Dict[str, List[Optional[float]]] = {"uncorrected": [], "corrected": []}
        self.observation_flux: Dict[str, List[Dict[str, float]]] = {"uncorrected": [], "corrected": []}
        self.independent: Dict[str, float] = {
            "atmosphere_rms_max_abs_error_m": 0.0,
            "residual_rms_max_abs_error_m": 0.0,
            "uncorrected_strehl_max_abs_error": 0.0,
            "corrected_strehl_max_abs_error": 0.0,
            "held_correction_identity_max_abs_m": 0.0,
            "running_observation_linearity_max_abs": 0.0,
        }
        self.oracle: List[Dict[str, Any]] = []
        self.frames_kept: Dict[int, Dict[str, Any]] = {}

    # ------------------------------------------------------------------

    def _crop_slices(self) -> tuple:
        if self._crop is None:
            assert self.axes is not None
            half = contract.CROP_HALF_WIDTH_CELLS
            x0 = binary_scene.zero_index(self.axes["x_angle_rad"], label="x axis")
            y0 = binary_scene.zero_index(self.axes["y_angle_rad"], label="y axis")
            self._crop = (slice(y0 - half, y0 + half), slice(x0 - half, x0 + half))
        return self._crop

    def _crop32(self, image: np.ndarray) -> np.ndarray:
        rows, columns = self._crop_slices()
        return np.ascontiguousarray(np.asarray(image, dtype=float)[rows, columns], dtype="<f4")

    def _flux_record(self, result: Dict[str, Any]) -> Dict[str, float]:
        rows, columns = self._crop_slices()
        crop_flux = float(np.asarray(result["image"])[rows, columns].sum())
        return {
            "full_flux": result["full_flux"],
            "expected_full_flux": result["expected_full_flux"],
            "full_flux_error": result["full_flux_error"],
            "native_window_fraction": result["retained_fraction"],
            "display_crop_fraction": crop_flux / result["full_flux"],
        }

    def observe(self, observation: Any) -> None:
        super().observe(observation)
        index = int(observation.frame_index)
        snapshot = self.display[index]
        # The explorer observer's finish() only checks that every handed-over
        # frame arrived; the heavy arrays are released here.
        self.display[index] = {}
        mask = self.pupil_mask
        atmosphere = snapshot["atmosphere_opd_m"]
        residual = snapshot["pre_update_residual_opd_m"]
        correction = snapshot["held_correction_opd_m"]
        maps = {"atmosphere": atmosphere, "correction": correction, "residual": residual}
        frames = self.frames

        # Independent reductions of every frame (not only replay frames).
        ideal = np.asarray(self.ideal_psf.intensity, dtype=float)
        checks = self.independent
        checks["atmosphere_rms_max_abs_error_m"] = max(checks["atmosphere_rms_max_abs_error_m"], abs(independent_rms(atmosphere, mask) - frames["atmosphere_rms_m"][index]))
        checks["residual_rms_max_abs_error_m"] = max(checks["residual_rms_max_abs_error_m"], abs(independent_rms(residual, mask) - frames["residual_rms_m"][index]))
        checks["uncorrected_strehl_max_abs_error"] = max(checks["uncorrected_strehl_max_abs_error"], abs(independent_peak_strehl(snapshot["psf_uncorrected"], ideal) - frames["peak_strehl_uncorrected"][index]))
        checks["corrected_strehl_max_abs_error"] = max(checks["corrected_strehl_max_abs_error"], abs(independent_peak_strehl(snapshot["psf_corrected"], ideal) - frames["peak_strehl_corrected"][index]))
        checks["held_correction_identity_max_abs_m"] = max(checks["held_correction_identity_max_abs_m"], float(np.max(np.abs((atmosphere - correction - residual)[mask]))))

        for key, _ in MAP_KEYS:
            values = maps[key][mask]
            self.display_percentile_m[key].append(float(np.percentile(np.abs(values - values.mean()), contract.OPD_LIMIT_PERCENTILE)))

        assert self.axes is not None
        x_axis, y_axis = self.axes["x_angle_rad"], self.axes["y_angle_rad"]
        observations = {}
        for role, key in (("uncorrected", "psf_uncorrected"), ("corrected", "psf_corrected")):
            result = binary_scene.observe(self._scene, snapshot[key], x_axis, y_axis)
            observations[role] = result
            self.observation_flux[role].append(self._flux_record(result))

        if index >= self._burn_in:
            self._count += 1
            for role, key in (("uncorrected", "psf_uncorrected"), ("corrected", "psf_corrected")):
                psf = np.asarray(snapshot[key], dtype=float)
                image = np.asarray(observations[role]["image"], dtype=float)
                if self._psf_sum[role] is None:
                    self._psf_sum[role] = np.zeros_like(psf)
                    self._obs_sum[role] = np.zeros_like(image)
                self._psf_sum[role] += psf
                self._obs_sum[role] += image
                self._full_flux_sum[role] += observations[role]["full_flux"]
                running_psf = self._psf_sum[role] / self._count
                self.running_strehl[role].append(float(np.max(running_psf) / np.max(ideal)))
        else:
            for role in ("uncorrected", "corrected"):
                self.running_strehl[role].append(None)

        if index in self._oracle_frames:
            self.oracle.append(self._oracle(index, snapshot, mask, ideal))

        if index in self._transported_set:
            kept: Dict[str, Any] = {"maps_m": {key: np.array(maps[key], dtype=float) for key in maps}}
            kept["crops"] = {
                "atmosphere_opd_m": np.ascontiguousarray(atmosphere, dtype="<f4"),
                "held_correction_opd_m": np.ascontiguousarray(correction, dtype="<f4"),
                "pre_update_residual_opd_m": np.ascontiguousarray(residual, dtype="<f4"),
                "psf_uncorrected": self._crop32(snapshot["psf_uncorrected"]),
                "psf_corrected": self._crop32(snapshot["psf_corrected"]),
                "observation_uncorrected": self._crop32(observations["uncorrected"]["image"]),
                "observation_corrected": self._crop32(observations["corrected"]["image"]),
            }
            running_flux: Dict[str, Optional[Dict[str, float]]] = {"uncorrected": None, "corrected": None}
            for role in ("uncorrected", "corrected"):
                name = f"running_observation_{role}"
                if self._count == 0:
                    kept["crops"][name] = np.full(contract.CROP_SHAPE, np.nan, dtype="<f4")
                    continue
                running = self._obs_sum[role] / self._count
                kept["crops"][name] = self._crop32(running)
                # Linearity oracle: the mean of the instantaneous observations
                # equals the observation of the running-mean PSF.
                convolved = binary_scene.observe(self._scene, self._psf_sum[role] / self._count, x_axis, y_axis)
                self.independent["running_observation_linearity_max_abs"] = max(
                    self.independent["running_observation_linearity_max_abs"],
                    float(np.max(np.abs(convolved["image"] - running))),
                )
                rows, columns = self._crop_slices()
                full = self._full_flux_sum[role] / self._count
                running_flux[role] = {
                    "full_flux": full,
                    "native_window_fraction": float(running.sum()) / full,
                    "display_crop_fraction": float(running[rows, columns].sum()) / full,
                }
            kept["running_sample_count"] = self._count
            kept["running_flux"] = running_flux
            self.frames_kept[index] = kept

        if self._progress is not None:
            self._progress(index, float(observation.time_s))

    def _oracle(self, index: int, snapshot: Dict[str, np.ndarray], mask: np.ndarray, ideal: np.ndarray) -> Dict[str, Any]:
        """Independent PSF, Strehl and phase-unit checks at one frame."""

        from shwfs_ao.core.wavefront import opd_to_phase

        assert self.axes is not None
        x_axis, y_axis = self.axes["x_angle_rad"], self.axes["y_angle_rad"]
        zero = np.zeros(mask.shape)
        ideal_direct = direct_dft_psf(zero, mask, self._wavelength, self._pupil_x, self._pupil_y, x_axis, y_axis)
        record: Dict[str, Any] = {"frame": index}
        for role, field in (("uncorrected", "atmosphere_opd_m"), ("corrected", "pre_update_residual_opd_m")):
            direct = direct_dft_psf(snapshot[field], mask, self._wavelength, self._pupil_x, self._pupil_y, x_axis, y_axis)
            production = np.asarray(snapshot[f"psf_{role}"], dtype=float)
            record[f"{role}_psf_max_abs_difference"] = float(np.max(np.abs(direct - production)))
            record[f"{role}_strehl_direct"] = float(direct.max() / ideal_direct.max())
            frame_strehl = self.frames[f"peak_strehl_{role}"][index]
            record[f"{role}_strehl_abs_difference"] = abs(record[f"{role}_strehl_direct"] - frame_strehl)
        opd = np.asarray(snapshot["atmosphere_opd_m"], dtype=float)[mask]
        independent_phase = 2.0 * math.pi * opd / contract.SCIENCE_WAVELENGTH_M
        record["phase_rule_max_abs_difference_rad"] = float(np.max(np.abs(np.asarray(opd_to_phase(opd, contract.SCIENCE_WAVELENGTH_M)) - independent_phase)))
        record["phase_rms_rad_at_science"] = float(np.sqrt(np.mean((independent_phase - independent_phase.mean()) ** 2)))
        record["ideal_psf_max_abs_difference"] = float(np.max(np.abs(ideal_direct - ideal)))
        return record

    def finish_dynamic(self) -> Dict[str, Any]:
        """The explorer observer's finish plus the dynamic averages and their oracles."""

        finish = super().finish()
        count = finish["analysis_count"]
        if self._count != count:
            raise ExplorerObserverError("the dynamic running sums did not include every eligible frame.")
        assert self.axes is not None
        x_axis, y_axis = self.axes["x_angle_rad"], self.axes["y_angle_rad"]
        result: Dict[str, Any] = {"explorer": finish, "observations": {}, "sum_consistency": {}}
        for role in ("uncorrected", "corrected"):
            own_mean = self._psf_sum[role] / count
            explorer_own = finish[f"own_mean_psf_{role}"]
            accumulator = finish[f"mean_psf_{role}"]
            final = binary_scene.observe(self._scene, accumulator, x_axis, y_axis)
            mean_of_observations = self._obs_sum[role] / count
            result["observations"][role] = final
            result["sum_consistency"][role] = {
                "dynamic_psf_sum_equals_explorer_sum_max_abs": float(np.max(np.abs(own_mean - explorer_own))),
                "accumulator_minus_own_mean_max_abs": float(np.max(np.abs(accumulator - own_mean))),
                "final_observation_linearity_max_abs": float(np.max(np.abs(final["image"] - mean_of_observations))),
                "mean_full_flux_of_instantaneous": self._full_flux_sum[role] / count,
            }
        return result
