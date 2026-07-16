# Science PSF diagnostics report Strehl, Marechal check, FWHM, EE50/EE80, halo fraction, and band-aware metrics for open-loop and closed-loop cases.

"""Science-facing AO diagnostics for residual OPD maps and PSFs.

This module keeps science-image quality calculations separate from the
detector/WFS/control code. It consumes OPD maps in nanometres, or WFS phase
maps with an explicit reference wavelength, and reports scalar PSF metrics
that notebook 11 and later error-budget tables can reuse.
"""

from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Any, Mapping, Sequence

import numpy as np

from ..core import wavefront as _wavefront
from ..core.provenance import ALLOWED_SOURCE_CLASSES, Provenance as _Provenance
from ..core.types import PsfResult as _PsfResult
from ..science.bandpass import (
    AODiagnosticsError,
    DEFAULT_DIAGNOSTIC_SOURCE_CLASS,
    DEFAULT_DIAGNOSTIC_SOURCE_NOTE,
    ScienceBandpass,
    bandpass_from_filter_curve,
    monochromatic_bandpass,
    top_hat_bandpass,
)
from ..science.metrics import (
    _encircled_energy_radius_from_discrete_flux as _canonical_ee_radius,
    _weighted_scalar_fields as _canonical_weighted_scalar_fields,
    psf_scalar_metrics as _psf_scalar_metrics,
)
from .data_sources import FilterCurve
from .dm_model import DMModel, synthesize_dm_phase_rad
from .psf_tools import compute_psf_from_phase, marechal_strehl, phase_for_science_wavelength


PHASE_TWO_PI = 2.0 * np.pi
NM_TO_M = 1.0e-9
NM_PER_M = 1.0e9
ARCSEC_PER_RAD = 206264.80624709636


@dataclass(frozen=True)
class SciencePsfMetrics:
    """Scalar PSF metrics for one AO science case and one wavelength/band."""

    case_name: str
    band_name: str
    effective_wavelength_m: float
    opd_rms_nm: float
    strehl_peak: float
    strehl_marechal: float
    marechal_abs_error: float
    fwhm_px: float
    fwhm_lambda_over_d: float
    fwhm_arcsec: float
    ee50_px: float
    ee50_lambda_over_d: float
    ee50_arcsec: float
    ee80_px: float
    ee80_lambda_over_d: float
    ee80_arcsec: float
    halo_fraction: float
    halo_inner_lambda_over_d: float
    source_class: str
    source_note: str

    def as_dict(self) -> dict[str, float | str]:
        return {
            "case_name": self.case_name,
            "band_name": self.band_name,
            "effective_wavelength_m": self.effective_wavelength_m,
            "opd_rms_nm": self.opd_rms_nm,
            "strehl_peak": self.strehl_peak,
            "strehl_marechal": self.strehl_marechal,
            "marechal_abs_error": self.marechal_abs_error,
            "fwhm_px": self.fwhm_px,
            "fwhm_lambda_over_d": self.fwhm_lambda_over_d,
            "fwhm_arcsec": self.fwhm_arcsec,
            "ee50_px": self.ee50_px,
            "ee50_lambda_over_d": self.ee50_lambda_over_d,
            "ee50_arcsec": self.ee50_arcsec,
            "ee80_px": self.ee80_px,
            "ee80_lambda_over_d": self.ee80_lambda_over_d,
            "ee80_arcsec": self.ee80_arcsec,
            "halo_fraction": self.halo_fraction,
            "halo_inner_lambda_over_d": self.halo_inner_lambda_over_d,
            "source_class": self.source_class,
            "source_note": self.source_note,
        }


def phase_rad_to_opd_nm(
    phase_rad: np.ndarray,
    reference_wavelength_m: float,
    pupil_mask: np.ndarray | None = None,
    remove_piston: bool = True,
) -> np.ndarray:
    """Convert phase in radians at a named wavelength to OPD in nanometres."""

    _require_positive("reference_wavelength_m", reference_wavelength_m)
    phase = np.asarray(phase_rad, dtype=float)
    if pupil_mask is None:
        mask = np.ones_like(phase, dtype=bool)
    else:
        mask = np.asarray(pupil_mask, dtype=bool)
        if mask.shape != phase.shape:
            raise AODiagnosticsError(f"pupil_mask shape {mask.shape} != phase shape {phase.shape}.")
    _assert_masked_finite(phase, mask, "phase map")
    opd_nm = _wavefront.phase_to_opd(phase, reference_wavelength_m) * NM_PER_M
    opd_nm = np.where(mask, opd_nm, np.nan)
    if remove_piston:
        opd_nm = remove_piston_opd_nm(opd_nm, mask)
    return opd_nm


def remove_piston_opd_nm(opd_nm: np.ndarray, pupil_mask: np.ndarray) -> np.ndarray:
    """Remove piston from an OPD map inside the pupil."""

    opd = np.asarray(opd_nm, dtype=float).copy()
    mask = np.asarray(pupil_mask, dtype=bool)
    if opd.shape != mask.shape:
        raise AODiagnosticsError(f"opd_nm shape {opd.shape} != pupil_mask shape {mask.shape}.")
    finite = mask & np.isfinite(opd)
    if not np.any(finite):
        raise AODiagnosticsError("No finite OPD samples are available inside the pupil.")
    centered = _wavefront.remove_piston(opd, finite)
    opd[finite] = centered[finite]
    opd[~mask] = np.nan
    return opd


def residual_opd_nm_from_command(
    atmosphere_phase_rad: np.ndarray,
    command_nm: Sequence[float],
    dm_model: DMModel,
    reference_wavelength_m: float,
) -> np.ndarray:
    """Compute residual OPD from a WFS phase map and a DM command vector."""

    dm_phase, _ = synthesize_dm_phase_rad(
        command_nm,
        dm_model,
        wavelength_m=reference_wavelength_m,
        remove_piston=True,
    )
    residual_phase = np.asarray(atmosphere_phase_rad, dtype=float) - dm_phase
    return phase_rad_to_opd_nm(residual_phase, reference_wavelength_m, dm_model.pupil_mask)


def science_psf_metrics_from_opd(
    opd_nm: np.ndarray,
    pupil_mask: np.ndarray,
    wavelength_m: float,
    telescope_diameter_m: float,
    case_name: str = "case",
    band_name: str = "monochromatic",
    pad_factor: int = 4,
    halo_inner_lambda_over_d: float = 3.0,
    source_class: str = DEFAULT_DIAGNOSTIC_SOURCE_CLASS,
    source_note: str = DEFAULT_DIAGNOSTIC_SOURCE_NOTE,
) -> SciencePsfMetrics:
    """Compute monochromatic science PSF metrics from an OPD map.

    Args:
        opd_nm: Residual OPD map in nanometres. Values outside the pupil may be
            NaN.
        pupil_mask: Boolean science pupil mask.
        wavelength_m: Science wavelength in metres.
        telescope_diameter_m: Telescope diameter for angular metric labels.
        case_name: Science case label, such as ``open_loop`` or
            ``realistic_closed_loop``.
        band_name: Band label used in the metric table.
        pad_factor: FFT padding factor.
        halo_inner_lambda_over_d: Radius outside which PSF energy is counted
            as halo fraction.
        source_class: Provenance class for this diagnostic.
        source_note: Human-readable provenance note.

    Returns:
        :class:`SciencePsfMetrics` for one wavelength.

    Raises:
        AODiagnosticsError: If maps, PSFs, or scalar metrics become non-finite.

    Physics note:
        OPD is converted to science phase at ``wavelength_m`` before PSF
        generation. Strehl comparisons across bands therefore go through OPD
        rescaling, not direct reuse of WFS phase.
    """

    _require_positive("wavelength_m", wavelength_m)
    _require_positive("telescope_diameter_m", telescope_diameter_m)
    if int(pad_factor) < 1:
        raise AODiagnosticsError("pad_factor must be >= 1.")
    _require_nonnegative("halo_inner_lambda_over_d", halo_inner_lambda_over_d)
    _validate_source(source_class, source_note)

    mask = np.asarray(pupil_mask, dtype=bool)
    opd = remove_piston_opd_nm(opd_nm, mask)
    phase = _wavefront.opd_to_phase(opd * NM_TO_M, float(wavelength_m))
    _assert_masked_finite(phase, mask, "science phase map")
    try:
        psf_intensity = compute_psf_from_phase(
            phase,
            mask,
            pad_factor=int(pad_factor),
        )
        ideal_intensity = compute_psf_from_phase(
            np.zeros_like(phase),
            mask,
            pad_factor=int(pad_factor),
        )
        psf = _legacy_psf_result(
            psf_intensity,
            wavelength_m=float(wavelength_m),
            telescope_diameter_m=float(telescope_diameter_m),
            pupil_size_px=mask.shape[0],
            pad_factor=int(pad_factor),
        )
        ideal = _legacy_psf_result(
            ideal_intensity,
            wavelength_m=float(wavelength_m),
            telescope_diameter_m=float(telescope_diameter_m),
            pupil_size_px=mask.shape[0],
            pad_factor=int(pad_factor),
        )
        opd_m = opd * NM_TO_M
        focal_pixel_scale_rad = float(np.diff(psf.x_angle_rad)[0])
        lambda_over_d_rad = float(wavelength_m) / float(telescope_diameter_m)
        canonical = _psf_scalar_metrics(
            psf,
            ideal,
            opd_m,
            mask,
            float(telescope_diameter_m),
            halo_inner_lambda_over_d=float(halo_inner_lambda_over_d),
        )
    except (TypeError, ValueError) as exc:
        raise AODiagnosticsError(str(exc)) from exc

    fwhm_px = canonical.fwhm_rad / focal_pixel_scale_rad
    # NumPy's historical default argsort was quicksort.  Preserve that tie
    # ordering in the frozen pixel facade while keeping the public canonical
    # physical metric deterministically stable-sorted.
    ee50_px = _canonical_ee_radius(
        psf.intensity,
        psf.x_angle_rad,
        psf.y_angle_rad,
        0.50,
        sort_kind="legacy_quicksort",
    ) / focal_pixel_scale_rad
    ee80_px = _canonical_ee_radius(
        psf.intensity,
        psf.x_angle_rad,
        psf.y_angle_rad,
        0.80,
        sort_kind="legacy_quicksort",
    ) / focal_pixel_scale_rad
    lambda_over_d_arcsec = lambda_over_d_rad * ARCSEC_PER_RAD
    return SciencePsfMetrics(
        case_name=case_name,
        band_name=band_name,
        effective_wavelength_m=float(wavelength_m),
        opd_rms_nm=canonical.opd_rms_m * NM_PER_M,
        strehl_peak=canonical.peak_strehl,
        strehl_marechal=canonical.marechal_strehl,
        marechal_abs_error=canonical.marechal_abs_difference,
        fwhm_px=fwhm_px,
        fwhm_lambda_over_d=fwhm_px / float(pad_factor),
        fwhm_arcsec=fwhm_px / float(pad_factor) * lambda_over_d_arcsec,
        ee50_px=ee50_px,
        ee50_lambda_over_d=ee50_px / float(pad_factor),
        ee50_arcsec=ee50_px / float(pad_factor) * lambda_over_d_arcsec,
        ee80_px=ee80_px,
        ee80_lambda_over_d=ee80_px / float(pad_factor),
        ee80_arcsec=ee80_px / float(pad_factor) * lambda_over_d_arcsec,
        halo_fraction=canonical.halo_fraction,
        halo_inner_lambda_over_d=float(halo_inner_lambda_over_d),
        source_class=source_class,
        source_note=source_note,
    )


def band_averaged_psf_metrics_from_opd(
    opd_nm: np.ndarray,
    pupil_mask: np.ndarray,
    bandpass: ScienceBandpass,
    telescope_diameter_m: float,
    case_name: str = "case",
    pad_factor: int = 4,
    halo_inner_lambda_over_d: float = 3.0,
) -> SciencePsfMetrics:
    """Compute transmission-weighted scalar PSF metrics over a bandpass.

    The returned metrics describe a synthetic PSF calculation even when the
    bandpass is defined by a direct public filter curve. The filter provenance
    is retained in ``source_note`` rather than assigned to the simulated
    metrics themselves.
    """

    metric_source_note = (
        "Synthetic PSF diagnostic computed from a simulation residual OPD map; "
        f"bandpass provenance ({bandpass.source_class}): {bandpass.source_note}"
    )
    weighted = []
    for wavelength, weight in zip(bandpass.wavelength_m, bandpass.weights):
        metrics = science_psf_metrics_from_opd(
            opd_nm,
            pupil_mask,
            wavelength_m=float(wavelength),
            telescope_diameter_m=telescope_diameter_m,
            case_name=case_name,
            band_name=bandpass.name,
            pad_factor=pad_factor,
            halo_inner_lambda_over_d=halo_inner_lambda_over_d,
            source_class="synthetic_assumed",
            source_note=metric_source_note,
        )
        weighted.append((float(weight), metrics))
    field_names = (
        "opd_rms_nm",
        "strehl_peak",
        "strehl_marechal",
        "marechal_abs_error",
        "fwhm_px",
        "fwhm_lambda_over_d",
        "fwhm_arcsec",
        "ee50_px",
        "ee50_lambda_over_d",
        "ee50_arcsec",
        "ee80_px",
        "ee80_lambda_over_d",
        "ee80_arcsec",
        "halo_fraction",
    )
    rows = tuple(metric for _, metric in weighted)
    weights = tuple(weight for weight, _ in weighted)
    try:
        averaged = _canonical_weighted_scalar_fields(rows, weights, field_names)
    except ValueError as exc:
        raise AODiagnosticsError(str(exc)) from exc
    first = rows[0]
    return SciencePsfMetrics(
        case_name=case_name,
        band_name=bandpass.name,
        effective_wavelength_m=bandpass.effective_wavelength_m,
        **averaged,
        halo_inner_lambda_over_d=float(halo_inner_lambda_over_d),
        source_class="synthetic_assumed",
        source_note=first.source_note,
    )


def science_case_metrics_table(
    cases_opd_nm: Mapping[str, np.ndarray],
    pupil_mask: np.ndarray,
    bandpasses: Sequence[ScienceBandpass],
    telescope_diameter_m: float,
    pad_factor: int = 4,
    halo_inner_lambda_over_d: float = 3.0,
) -> tuple[SciencePsfMetrics, ...]:
    """Report science PSF metrics for multiple AO cases and bands."""

    if not cases_opd_nm:
        raise AODiagnosticsError("cases_opd_nm must contain at least one case.")
    if not bandpasses:
        raise AODiagnosticsError("bandpasses must contain at least one band.")
    rows = []
    for case_name, opd_nm in cases_opd_nm.items():
        if not str(case_name).strip():
            raise AODiagnosticsError("case names must be non-empty.")
        for bandpass in bandpasses:
            rows.append(
                band_averaged_psf_metrics_from_opd(
                    opd_nm,
                    pupil_mask,
                    bandpass,
                    telescope_diameter_m=telescope_diameter_m,
                    case_name=case_name,
                    pad_factor=pad_factor,
                    halo_inner_lambda_over_d=halo_inner_lambda_over_d,
                )
            )
    return tuple(rows)


def science_metrics_as_dicts(metrics: Sequence[SciencePsfMetrics]) -> tuple[dict[str, float | str], ...]:
    """Convert metric dataclasses into table-friendly dictionaries."""

    return tuple(metric.as_dict() for metric in metrics)


def _legacy_psf_result(
    intensity: np.ndarray,
    *,
    wavelength_m: float,
    telescope_diameter_m: float,
    pupil_size_px: int,
    pad_factor: int,
) -> _PsfResult:
    """Attach physical axes to the frozen pixel-centred pupil convention."""

    pupil_spacing_m = telescope_diameter_m / pupil_size_px
    shape = np.asarray(intensity).shape
    x_angle_rad = wavelength_m * np.fft.fftshift(
        np.fft.fftfreq(shape[1], d=pupil_spacing_m)
    )
    y_angle_rad = wavelength_m * np.fft.fftshift(
        np.fft.fftfreq(shape[0], d=pupil_spacing_m)
    )
    return _PsfResult(
        intensity=intensity,
        x_angle_rad=x_angle_rad,
        y_angle_rad=y_angle_rad,
        wavelength_m=wavelength_m,
        normalization="unit_total_flux",
        backend_name="native_legacy_pixel_centred_adapter",
        sampling_metadata={
            "schema_id": "shwfs_ao.science.legacy_psf_sampling.v1",
            "pupil_size_px": pupil_size_px,
            "pupil_pixel_spacing_m": pupil_spacing_m,
            "padded_fft_shape_px": shape,
            "pad_factor": pad_factor,
            "cropping": "none",
            "interpolation": "none",
            "normalization": "unit_total_flux",
        },
    )


def _assert_masked_finite(values: np.ndarray, pupil_mask: np.ndarray, label: str) -> None:
    try:
        _wavefront.validate_masked_finite(values, pupil_mask, label)
    except ValueError as exc:
        array = np.asarray(values, dtype=float)
        mask = np.asarray(pupil_mask, dtype=bool)
        if array.shape == mask.shape and np.any(mask):
            finite = np.isfinite(array[mask])
            if not np.all(finite):
                finite_frac = float(np.mean(finite)) if finite.size else 0.0
                raise AODiagnosticsError(
                    f"Non-finite values inside {label}; "
                    f"finite_frac={finite_frac:.3f}."
                ) from exc
        raise AODiagnosticsError(str(exc)) from exc


def _validate_source(source_class: str, source_note: str) -> None:
    try:
        _Provenance(source_class=source_class, source_note=str(source_note))
    except (TypeError, ValueError) as exc:
        if source_class not in ALLOWED_SOURCE_CLASSES:
            raise AODiagnosticsError(
                f"source_class={source_class!r} is not in the permitted taxonomy {sorted(ALLOWED_SOURCE_CLASSES)}."
            ) from exc
        raise AODiagnosticsError("source_note must be a non-empty string.") from exc


def _require_positive(field_name: str, value: float) -> None:
    _require_finite(field_name, value)
    if float(value) <= 0.0:
        raise AODiagnosticsError(f"{field_name} must be positive; got {value!r}.")


def _require_nonnegative(field_name: str, value: float) -> None:
    _require_finite(field_name, value)
    if float(value) < 0.0:
        raise AODiagnosticsError(f"{field_name} must be non-negative; got {value!r}.")


def _require_finite(field_name: str, value: float) -> None:
    if not math.isfinite(float(value)):
        raise AODiagnosticsError(f"{field_name} must be finite; got {value!r}.")
