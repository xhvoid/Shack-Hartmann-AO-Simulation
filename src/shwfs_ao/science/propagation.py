"""Backend-independent science-propagation construction API.

Pupil geometry and focal sampling are immutable configuration.  Runtime
protocol calls therefore vary only residual OPD and science wavelength.  The
transparent NumPy implementation lives in ``shwfs_ao.backends.native``;
future backends use the same ``PsfResult`` contract.
"""

from __future__ import annotations

from dataclasses import dataclass
from numbers import Integral
from typing import ClassVar

import numpy as np

from ..core.geometry import PupilGeometry
from ..core.types import PsfResult


__all__ = (
    "SciencePropagationError",
    "PsfSampling",
    "monochromatic_psf",
)


class SciencePropagationError(ValueError):
    """Raised when science-propagation configuration or input is invalid."""


@dataclass(frozen=True, slots=True)
class PsfSampling:
    """Immutable focal-plane sampling requested from a science backend.

    ``pad_factor`` multiplies both pupil dimensions for the initial native
    FFT backend.  Cropping and interpolation are absent and recorded as such;
    a future backend must translate this repository-owned contract explicitly.
    """

    pad_factor: int = 4

    __hash_schema_id__: ClassVar[str] = "shwfs_ao.science.psf_sampling.v1"

    def __post_init__(self) -> None:
        padding = _positive_integer(self.pad_factor, label="pad_factor")
        object.__setattr__(self, "pad_factor", padding)


def monochromatic_psf(
    opd_m: np.ndarray,
    pupil: PupilGeometry,
    wavelength_m: float,
    *,
    backend: str,
    sampling: PsfSampling,
) -> PsfResult:
    """Construct a fixed backend propagator and generate one PSF.

    The initial registry contains only ``"native"``.  Unknown identifiers are
    rejected rather than silently changing optical or sampling semantics.
    """

    if not isinstance(pupil, PupilGeometry):
        raise SciencePropagationError("pupil must be a PupilGeometry.")
    if not isinstance(sampling, PsfSampling):
        raise SciencePropagationError("sampling must be a PsfSampling.")
    if not isinstance(backend, str) or backend != "native":
        raise SciencePropagationError(
            "backend must be 'native'; HCIPy propagation is not available yet."
        )

    # Local import keeps this construction layer backend-neutral and avoids a
    # module cycle while the native backend imports the sampling contract.
    from ..backends.native.propagation import NativeSciencePropagator

    propagator = NativeSciencePropagator(pupil=pupil, sampling=sampling)
    return propagator.psf_from_opd(opd_m, wavelength_m)


def _positive_integer(value: object, *, label: str) -> int:
    if not isinstance(value, Integral) or isinstance(value, (bool, np.bool_)):
        raise SciencePropagationError(f"{label} must be an integer.")
    result = int(value)
    if result < 1:
        raise SciencePropagationError(f"{label} must be at least 1.")
    return result

