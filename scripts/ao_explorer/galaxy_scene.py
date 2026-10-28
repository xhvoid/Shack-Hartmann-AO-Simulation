"""Linear convolution of a fixed science template with the recorded PSFs.

Observation
    ``I_k = T (*) P_k``: discrete *linear* convolution with zero extension of
    a fixed template ``T`` with one saved PSF ``P_k``, as in ``binary_scene``.
    ``T`` lies on the PSF lattice (the same angular step and exact zero
    sample) but may extend beyond the 156 x 156 PSF window, so that template
    light outside the window still reaches the window through the kernel:
    with ``T`` covering twice the PSF window, every output sample inside the
    window receives the complete contribution of every template sample within
    the kernel's extent.  The full output has ``N_T + N_P - 1`` samples per
    axis on ``theta_T[0] + theta_P[0] + m * delta``; it is cropped to the
    native PSF window by coordinates (never by array midpoints).  The
    convolution is evaluated with real FFTs on arrays zero-padded to at least
    ``N_T + N_P - 1`` samples per axis, so the circular convolution of the
    padded arrays equals the linear one (no wraparound); the template
    transform is computed once and reused for every kernel.  No
    renormalization: the full-output flux equals template flux times kernel
    flux to rounding, and what falls outside the window is recorded.

The template may hold slightly negative samples (retained observational
noise); the operation is linear, so they are carried through unchanged and
only the display clips them.  One on-axis PSF is assumed over the compact
field: the SCAO model produces no field-dependent PSF.  The template never
enters the wavefront sensor, guide source or controller; it is applied only
after the recorded PSFs exist.
"""

from __future__ import annotations

from typing import Any, Dict, Tuple

import numpy as np

import binary_scene
import identity


RENDERER_REVISION = "ao-explorer.template-observation.v1"


class GalaxySceneError(ValueError):
    """Raised when a template, a kernel or a grid fails the observation contract."""


def grid_record(x_angle_rad: np.ndarray, y_angle_rad: np.ndarray) -> Dict[str, Any]:
    """A grid record in the form of the binary scene's (same ``grid_id`` for the PSF grid)."""

    x = np.asarray(x_angle_rad, dtype=float)
    y = np.asarray(y_angle_rad, dtype=float)
    return {
        "shape_yx": [int(y.size), int(x.size)],
        "x_angle_rad_sha256": identity.sha256_bytes(x.tobytes()),
        "y_angle_rad_sha256": identity.sha256_bytes(y.tobytes()),
        "x_step_rad": binary_scene.uniform_step(x, label="x axis"),
        "y_step_rad": binary_scene.uniform_step(y, label="y axis"),
        "x_zero_index": binary_scene.zero_index(x, label="x axis"),
        "y_zero_index": binary_scene.zero_index(y, label="y axis"),
        "axis_layout": "x_columns_y_rows",
        "x_direction": "column index increases with angle",
        "y_direction": "row index increases with angle",
    }


def grid_id(record: Dict[str, Any]) -> str:
    return identity.sha256_bytes(identity.canonical_json_bytes(record))


def lattice_axis(kernel_axis: np.ndarray, cells: int) -> np.ndarray:
    """``cells`` samples on the kernel's lattice with the exact zero sample at ``cells // 2``."""

    kernel = np.asarray(kernel_axis, dtype=float)
    step = binary_scene.uniform_step(kernel, label="kernel axis")
    zero = binary_scene.zero_index(kernel, label="kernel axis")
    if not np.allclose(kernel, (np.arange(kernel.size) - zero) * step, rtol=0.0, atol=1e-9 * step):
        raise GalaxySceneError("the kernel axis is not an integer lattice about zero.")
    return (np.arange(cells, dtype=float) - cells // 2) * step


class Convolver:
    """Linear convolution of one fixed template with many kernels on one lattice."""

    def __init__(self, template: np.ndarray, template_x: np.ndarray, template_y: np.ndarray,
                 kernel_x: np.ndarray, kernel_y: np.ndarray) -> None:
        from scipy import fft

        self._fft = fft
        self.template = np.asarray(template, dtype=float)
        tx, ty = np.asarray(template_x, dtype=float), np.asarray(template_y, dtype=float)
        kx, ky = np.asarray(kernel_x, dtype=float), np.asarray(kernel_y, dtype=float)
        if self.template.shape != (ty.size, tx.size) or not np.all(np.isfinite(self.template)):
            raise GalaxySceneError("the template does not match its axes or is not finite.")
        for t, k, label in ((tx, kx, "x"), (ty, ky, "y")):
            if not np.allclose(t, lattice_axis(k, t.size), rtol=0.0, atol=1e-9 * binary_scene.uniform_step(k, label=label)):
                raise GalaxySceneError(f"the template {label} axis is not on the kernel lattice.")
        self.kernel_shape = (ky.size, kx.size)
        self.kernel_grid = grid_record(kx, ky)
        self.full_shape = (ty.size + ky.size - 1, tx.size + kx.size - 1)
        self.fft_shape = tuple(fft.next_fast_len(n, real=True) for n in self.full_shape)
        self.template_spectrum = fft.rfft2(self.template, s=self.fft_shape)
        full_x = binary_scene.full_output_axis(tx, kx)
        full_y = binary_scene.full_output_axis(ty, ky)
        self.full_axis_first_rad = [float(full_x[0]), float(full_y[0])]
        self.crop_x = binary_scene.crop_slice(full_x, kx, label="x")
        self.crop_y = binary_scene.crop_slice(full_y, ky, label="y")
        self.template_flux = float(self.template.sum())
        # Template samples whose light can reach the window through the kernel.
        self.context_complete = bool(tx.size >= 2 * kx.size - 1 and ty.size >= 2 * ky.size - 1)

    def policy(self) -> Dict[str, Any]:
        return {
            "kind": "discrete linear convolution, zero extension",
            "full_shape_rule": "N_T + N_P - 1 samples per axis",
            "evaluation": f"real FFT of both arrays zero-padded to {list(self.fft_shape)} >= {list(self.full_shape)} samples (no wraparound); template transform reused for every kernel",
            "kernel_origin": "the kernel sample at exactly zero angle on both actual axes",
            "template_lattice": "the template samples lie on the kernel lattice (same step, exact zero sample); the template extends beyond the kernel window",
            "context": "every output sample in the native window receives the complete contribution of all template samples within the kernel extent" if self.context_complete else "incomplete context",
            "output_axes": "theta_T[0] + theta_P[0] + m * delta for full index m",
            "crop": "full-output samples whose angles equal the native PSF grid, matched from coordinates",
            "boundary": "zero outside both arrays (the template is cut at its own edge, beyond the kernel reach of the window)",
            "renormalization": "none (no peak, cropped-sum or per-image normalization)",
            "rounding": "FFT rounding leaves values of order 1e-17 relative where the exact result is zero or tiny",
            "spatial_invariance": "one on-axis PSF assumed throughout the compact field (illustrative)",
        }

    def observe(self, kernel: np.ndarray) -> Tuple[np.ndarray, Dict[str, Any]]:
        """The native-window observation of one kernel and its flux accounting."""

        k = np.asarray(kernel, dtype=float)
        if k.shape != self.kernel_shape:
            raise GalaxySceneError("the kernel shape differs from the kernel grid.")
        if not np.all(np.isfinite(k)) or np.any(k < 0.0):
            raise GalaxySceneError("the kernel must be finite and non-negative.")
        fft = self._fft
        product = self.template_spectrum * fft.rfft2(k, s=self.fft_shape)
        full = fft.irfft2(product, s=self.fft_shape)[: self.full_shape[0], : self.full_shape[1]]
        image = np.ascontiguousarray(full[self.crop_y[0]:self.crop_y[1], self.crop_x[0]:self.crop_x[1]])
        full_flux = float(full.sum())
        kernel_flux = float(k.sum())
        cropped_flux = float(image.sum())
        return image, {
            "kernel_flux": kernel_flux,
            "full_flux": full_flux,
            "expected_full_flux": self.template_flux * kernel_flux,
            "full_flux_error": full_flux - self.template_flux * kernel_flux,
            "window_flux": cropped_flux,
            "window_fraction": cropped_flux / full_flux,
            "min_value": float(image.min()),
        }
