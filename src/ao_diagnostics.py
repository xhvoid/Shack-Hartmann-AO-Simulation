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

from data_sources import ALLOWED_SOURCE_CLASSES, FilterCurve
from dm_model import DMModel, synthesize_dm_phase_rad
from psf_tools import compute_psf_from_phase, marechal_strehl, phase_for_science_wavelength


DEFAULT_DIAGNOSTIC_SOURCE_CLASS = "synthetic_assumed"
DEFAULT_DIAGNOSTIC_SOURCE_NOTE = (
    "Synthetic science diagnostic settings for the 2 m AO demonstrator; "
    "bandpass fallback is not an on-sky calibration."
)
PHASE_TWO_PI = 2.0 * np.pi
NM_TO_M = 1.0e-9
NM_PER_M = 1.0e9
ARCSEC_PER_RAD = 206264.80624709636


class AODiagnosticsError(ValueError):
    """Raised when science diagnostics receive invalid data or settings."""


@dataclass(frozen=True)
class ScienceBandpass:
    """Science bandpass used for scalar band-aware PSF metrics.

    Args:
        name: Human-readable band name.
        wavelength_m: Wavelength samples in metres.
        transmission: Non-negative throughput samples.
        source_class: Provenance class from the documented source-class taxonomy.
        source_note: Human-readable source note.
        filter_id: Optional filter identifier from SVO-style data.

    Returns:
        Immutable bandpass with normalized nonzero weights available through
        the ``weights`` property.

    Raises:
        AODiagnosticsError: If wavelengths/transmissions are malformed.

    Physics note:
        The current implementation band-averages scalar metrics over the
        transmission curve. It does not resample PSFs onto a common physical
        detector grid.
    """

    name: str
    wavelength_m: np.ndarray
    transmission: np.ndarray
    source_class: str = DEFAULT_DIAGNOSTIC_SOURCE_CLASS
    source_note: str = DEFAULT_DIAGNOSTIC_SOURCE_NOTE
    filter_id: str | None = None

    def __post_init__(self) -> None:
        if not str(self.name).strip():
            raise AODiagnosticsError("ScienceBandpass name must be non-empty.")
        wavelengths = np.asarray(self.wavelength_m, dtype=float).reshape(-1)
        transmission = np.asarray(self.transmission, dtype=float).reshape(-1)
        if wavelengths.shape != transmission.shape:
            raise AODiagnosticsError("wavelength_m and transmission must have the same shape.")
        if wavelengths.size == 0:
            raise AODiagnosticsError("ScienceBandpass must contain at least one wavelength sample.")
        _assert_all_finite(wavelengths, "bandpass wavelengths")
        _assert_all_finite(transmission, "bandpass transmission")
        if np.any(wavelengths <= 0.0):
            raise AODiagnosticsError("bandpass wavelengths must be positive.")
        if np.any(transmission < 0.0):
            raise AODiagnosticsError("bandpass transmission must be non-negative.")
        if np.sum(transmission) <= 0.0:
            raise AODiagnosticsError("bandpass transmission must have positive total weight.")
        if wavelengths.size > 1 and np.any(np.diff(wavelengths) <= 0.0):
            raise AODiagnosticsError("bandpass wavelengths must be strictly increasing.")
        if self.source_class not in ALLOWED_SOURCE_CLASSES:
            raise AODiagnosticsError(
                f"source_class={self.source_class!r} is not in the permitted taxonomy "
                f"{sorted(ALLOWED_SOURCE_CLASSES)}."
            )
        if not str(self.source_note).strip():
            raise AODiagnosticsError("ScienceBandpass source_note must be non-empty.")
        object.__setattr__(self, "wavelength_m", wavelengths)
        object.__setattr__(self, "transmission", transmission)

    @property
    def weights(self) -> np.ndarray:
        return self.transmission / np.sum(self.transmission)

    @property
    def effective_wavelength_m(self) -> float:
        return float(np.sum(self.wavelength_m * self.weights))


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


def monochromatic_bandpass(
    name: str,
    wavelength_m: float,
    source_class: str = DEFAULT_DIAGNOSTIC_SOURCE_CLASS,
    source_note: str = DEFAULT_DIAGNOSTIC_SOURCE_NOTE,
) -> ScienceBandpass:
    """Create a one-sample science bandpass."""

    _require_positive("wavelength_m", wavelength_m)
    return ScienceBandpass(
        name=name,
        wavelength_m=np.asarray([float(wavelength_m)]),
        transmission=np.asarray([1.0]),
        source_class=source_class,
        source_note=source_note,
        filter_id=name,
    )


def top_hat_bandpass(
    name: str,
    wavelength_min_m: float,
    wavelength_max_m: float,
    n_samples: int = 9,
    source_class: str = DEFAULT_DIAGNOSTIC_SOURCE_CLASS,
    source_note: str = DEFAULT_DIAGNOSTIC_SOURCE_NOTE,
) -> ScienceBandpass:
    """Create a documented top-hat fallback bandpass."""

    _require_positive("wavelength_min_m", wavelength_min_m)
    _require_positive("wavelength_max_m", wavelength_max_m)
    if wavelength_max_m <= wavelength_min_m:
        raise AODiagnosticsError("wavelength_max_m must exceed wavelength_min_m.")
    if int(n_samples) < 1:
        raise AODiagnosticsError("n_samples must be >= 1.")
    wavelengths = np.linspace(float(wavelength_min_m), float(wavelength_max_m), int(n_samples))
    return ScienceBandpass(
        name=name,
        wavelength_m=wavelengths,
        transmission=np.ones_like(wavelengths),
        source_class=source_class,
        source_note=source_note,
        filter_id=f"{name}.top_hat",
    )


def bandpass_from_filter_curve(curve: FilterCurve, name: str | None = None) -> ScienceBandpass:
    """Convert a SVO-style filter curve into a science bandpass."""

    return ScienceBandpass(
        name=name or curve.filter_id,
        wavelength_m=np.asarray(curve.wavelength_m, dtype=float),
        transmission=np.asarray(curve.transmission, dtype=float),
        source_class=curve.source_class,
        source_note=curve.provenance.source_note,
        filter_id=curve.filter_id,
    )


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
    opd_nm = phase * float(reference_wavelength_m) / PHASE_TWO_PI * NM_PER_M
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
    opd[finite] -= float(np.mean(opd[finite]))
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
    phase = phase_for_science_wavelength(opd * NM_TO_M, float(wavelength_m))
    _assert_masked_finite(phase, mask, "science phase map")
    psf = compute_psf_from_phase(phase, mask, pad_factor=int(pad_factor))
    ideal = compute_psf_from_phase(np.zeros_like(phase), mask, pad_factor=int(pad_factor))
    _assert_psf(psf, "science PSF")
    _assert_psf(ideal, "ideal PSF")

    peak_ideal = float(np.max(ideal))
    if peak_ideal <= 0.0:
        raise AODiagnosticsError("Ideal PSF peak must be positive.")
    strehl_peak = float(np.max(psf) / peak_ideal)
    strehl_marechal = marechal_strehl(phase, mask)
    _require_fraction("strehl_peak", strehl_peak, upper=1.5)
    _require_fraction("strehl_marechal", strehl_marechal, upper=1.0)

    fwhm_px = _fwhm_diameter_px(psf)
    ee50_px = _encircled_energy_radius_px(psf, 0.50)
    ee80_px = _encircled_energy_radius_px(psf, 0.80)
    lambda_over_d_arcsec = float(wavelength_m) / float(telescope_diameter_m) * ARCSEC_PER_RAD
    halo_fraction = _halo_fraction(psf, float(halo_inner_lambda_over_d) * int(pad_factor))
    return SciencePsfMetrics(
        case_name=case_name,
        band_name=band_name,
        effective_wavelength_m=float(wavelength_m),
        opd_rms_nm=_masked_rms(opd, mask),
        strehl_peak=strehl_peak,
        strehl_marechal=strehl_marechal,
        marechal_abs_error=abs(strehl_peak - strehl_marechal),
        fwhm_px=fwhm_px,
        fwhm_lambda_over_d=fwhm_px / float(pad_factor),
        fwhm_arcsec=fwhm_px / float(pad_factor) * lambda_over_d_arcsec,
        ee50_px=ee50_px,
        ee50_lambda_over_d=ee50_px / float(pad_factor),
        ee50_arcsec=ee50_px / float(pad_factor) * lambda_over_d_arcsec,
        ee80_px=ee80_px,
        ee80_lambda_over_d=ee80_px / float(pad_factor),
        ee80_arcsec=ee80_px / float(pad_factor) * lambda_over_d_arcsec,
        halo_fraction=halo_fraction,
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
    return _weighted_metrics(case_name, bandpass, weighted, halo_inner_lambda_over_d)


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


def _weighted_metrics(
    case_name: str,
    bandpass: ScienceBandpass,
    weighted: Sequence[tuple[float, SciencePsfMetrics]],
    halo_inner_lambda_over_d: float,
) -> SciencePsfMetrics:
    if not weighted:
        raise AODiagnosticsError("Cannot average an empty metric list.")

    def avg(field_name: str) -> float:
        return float(sum(weight * float(getattr(metric, field_name)) for weight, metric in weighted))

    first = weighted[0][1]
    return SciencePsfMetrics(
        case_name=case_name,
        band_name=bandpass.name,
        effective_wavelength_m=bandpass.effective_wavelength_m,
        opd_rms_nm=avg("opd_rms_nm"),
        strehl_peak=avg("strehl_peak"),
        strehl_marechal=avg("strehl_marechal"),
        marechal_abs_error=avg("marechal_abs_error"),
        fwhm_px=avg("fwhm_px"),
        fwhm_lambda_over_d=avg("fwhm_lambda_over_d"),
        fwhm_arcsec=avg("fwhm_arcsec"),
        ee50_px=avg("ee50_px"),
        ee50_lambda_over_d=avg("ee50_lambda_over_d"),
        ee50_arcsec=avg("ee50_arcsec"),
        ee80_px=avg("ee80_px"),
        ee80_lambda_over_d=avg("ee80_lambda_over_d"),
        ee80_arcsec=avg("ee80_arcsec"),
        halo_fraction=avg("halo_fraction"),
        halo_inner_lambda_over_d=float(halo_inner_lambda_over_d),
        source_class="synthetic_assumed",
        source_note=first.source_note,
    )


def _fwhm_diameter_px(psf: np.ndarray) -> float:
    radius_px, profile = _radial_profile_fraction(psf)
    peak = float(profile[0])
    if peak <= 0.0:
        raise AODiagnosticsError("PSF radial-profile peak must be positive.")
    half = 0.5 * peak
    below = np.flatnonzero(profile <= half)
    if below.size == 0:
        raise AODiagnosticsError("PSF radial profile never falls below half maximum.")
    idx = int(below[0])
    if idx == 0:
        radius_half = 0.0
    else:
        x0 = float(radius_px[idx - 1])
        x1 = float(radius_px[idx])
        y0 = float(profile[idx - 1])
        y1 = float(profile[idx])
        if y1 == y0:
            radius_half = x1
        else:
            radius_half = x0 + (half - y0) * (x1 - x0) / (y1 - y0)
    return float(2.0 * radius_half)


def _encircled_energy_radius_px(psf: np.ndarray, fraction: float) -> float:
    _require_fraction("encircled-energy fraction", fraction, upper=1.0)
    y, x = np.indices(psf.shape)
    center_y = (psf.shape[0] - 1) / 2.0
    center_x = (psf.shape[1] - 1) / 2.0
    radius = np.sqrt((x - center_x) ** 2 + (y - center_y) ** 2).ravel()
    values = np.asarray(psf, dtype=float).ravel()
    order = np.argsort(radius)
    radius_sorted = radius[order]
    cumulative = np.cumsum(values[order])
    if cumulative[-1] <= 0.0:
        raise AODiagnosticsError("PSF total energy must be positive.")
    cumulative /= cumulative[-1]
    idx = int(np.searchsorted(cumulative, float(fraction), side="left"))
    if idx <= 0:
        return float(radius_sorted[0])
    if idx >= radius_sorted.size:
        return float(radius_sorted[-1])
    c0 = float(cumulative[idx - 1])
    c1 = float(cumulative[idx])
    r0 = float(radius_sorted[idx - 1])
    r1 = float(radius_sorted[idx])
    if c1 == c0:
        return r1
    return float(r0 + (float(fraction) - c0) * (r1 - r0) / (c1 - c0))


def _halo_fraction(psf: np.ndarray, inner_radius_px: float) -> float:
    _require_nonnegative("inner_radius_px", inner_radius_px)
    y, x = np.indices(psf.shape)
    center_y = (psf.shape[0] - 1) / 2.0
    center_x = (psf.shape[1] - 1) / 2.0
    radius = np.sqrt((x - center_x) ** 2 + (y - center_y) ** 2)
    total = float(np.sum(psf))
    if total <= 0.0:
        raise AODiagnosticsError("PSF total energy must be positive.")
    halo = float(np.sum(psf[radius >= float(inner_radius_px)]) / total)
    _require_fraction("halo_fraction", halo, upper=1.0)
    return halo


def _radial_profile_fraction(psf: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    _assert_psf(psf, "PSF radial-profile input")
    y, x = np.indices(psf.shape)
    center_y = (psf.shape[0] - 1) / 2.0
    center_x = (psf.shape[1] - 1) / 2.0
    radius = np.sqrt((x - center_x) ** 2 + (y - center_y) ** 2)
    r_int = np.floor(radius).astype(int)
    counts = np.bincount(r_int.ravel())
    sums = np.bincount(r_int.ravel(), weights=np.asarray(psf, dtype=float).ravel())
    profile = np.divide(sums, counts, out=np.zeros_like(sums, dtype=float), where=counts > 0)
    return np.arange(profile.size, dtype=float), profile


def _masked_rms(values: np.ndarray, pupil_mask: np.ndarray) -> float:
    samples = np.asarray(values, dtype=float)[pupil_mask]
    samples = samples[np.isfinite(samples)]
    if samples.size == 0:
        raise AODiagnosticsError("No finite pupil samples are available for RMS calculation.")
    samples = samples - float(np.mean(samples))
    rms_value = float(np.sqrt(np.mean(samples**2)))
    _require_nonnegative("masked RMS", rms_value)
    return rms_value


def _assert_psf(psf: np.ndarray, label: str) -> None:
    array = np.asarray(psf, dtype=float)
    if array.ndim != 2:
        raise AODiagnosticsError(f"{label} must be 2-D.")
    _assert_all_finite(array, label)
    if np.any(array < -1.0e-15):
        raise AODiagnosticsError(f"{label} contains negative values.")
    total = float(np.sum(array))
    if not math.isfinite(total) or total <= 0.0:
        raise AODiagnosticsError(f"{label} must have positive finite total flux.")


def _assert_masked_finite(values: np.ndarray, pupil_mask: np.ndarray, label: str) -> None:
    array = np.asarray(values, dtype=float)
    mask = np.asarray(pupil_mask, dtype=bool)
    if array.shape != mask.shape:
        raise AODiagnosticsError(f"{label} shape {array.shape} != pupil mask shape {mask.shape}.")
    inside = array[mask]
    if not np.all(np.isfinite(inside)):
        finite_frac = float(np.mean(np.isfinite(inside))) if inside.size else 0.0
        raise AODiagnosticsError(f"Non-finite values inside {label}; finite_frac={finite_frac:.3f}.")


def _assert_all_finite(values: np.ndarray, label: str) -> None:
    array = np.asarray(values, dtype=float)
    if not np.all(np.isfinite(array)):
        finite_frac = float(np.mean(np.isfinite(array))) if array.size else 0.0
        raise AODiagnosticsError(f"Non-finite values in {label}; finite_frac={finite_frac:.3f}.")


def _validate_source(source_class: str, source_note: str) -> None:
    if source_class not in ALLOWED_SOURCE_CLASSES:
        raise AODiagnosticsError(
            f"source_class={source_class!r} is not in the permitted taxonomy {sorted(ALLOWED_SOURCE_CLASSES)}."
        )
    if not str(source_note).strip():
        raise AODiagnosticsError("source_note must be a non-empty string.")


def _require_positive(field_name: str, value: float) -> None:
    _require_finite(field_name, value)
    if float(value) <= 0.0:
        raise AODiagnosticsError(f"{field_name} must be positive; got {value!r}.")


def _require_nonnegative(field_name: str, value: float) -> None:
    _require_finite(field_name, value)
    if float(value) < 0.0:
        raise AODiagnosticsError(f"{field_name} must be non-negative; got {value!r}.")


def _require_fraction(field_name: str, value: float, upper: float) -> None:
    _require_finite(field_name, value)
    if float(value) < 0.0 or float(value) > float(upper):
        raise AODiagnosticsError(f"{field_name} must be between 0 and {upper}; got {value!r}.")


def _require_finite(field_name: str, value: float) -> None:
    if not math.isfinite(float(value)):
        raise AODiagnosticsError(f"{field_name} must be finite; got {value!r}.")
