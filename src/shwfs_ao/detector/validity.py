"""Centroid-quality diagnostics and independent validity policy.

The diagnostic calculation preserves the repository's existing CCD signal to
noise and detector-window clipping formulas.  Centroid uncertainty is the
first-order center-of-gravity error propagation over every window pixel; the
historical spot-width proxy is retained only as a frozen legacy policy.  Policy
is applied separately so optical spot generation remains independent of
detector quality thresholds.
"""

from __future__ import annotations

from dataclasses import dataclass
import math
import numpy as np

from .centroid import CentroidEstimate
from .config import DetectorConfig, SyntheticInstrumentError


__all__ = (
    "CentroidValidityConfig",
    "CentroidQuality",
    "CentroidValidity",
    "DEFAULT_CENTROID_VALIDITY",
    "UNDEFINED_CENTROID_SIGMA_PX",
    "centroid_quality",
    "evaluate_centroid_validity",
)

UNDEFINED_CENTROID_SIGMA_PX = 1.0e6

_UNCERTAINTY_MODELS = frozenset({"first_order", "legacy_spot_width"})


@dataclass(frozen=True)
class CentroidValidityConfig:
    """Thresholds for accepting a detector-level centroid."""

    __hash_schema_id__ = "shwfs_ao.detector.CentroidValidityConfig.v1"

    min_flux_e: float = 30.0
    min_peak_snr: float = 3.0
    max_centroid_sigma_px: float = 0.5
    max_window_clipping_fraction: float = 0.15

    def __post_init__(self) -> None:
        try:
            min_flux_e = _finite_nonnegative(
                self.min_flux_e,
                label="min_flux_e",
            )
            min_peak_snr = _finite_nonnegative(
                self.min_peak_snr,
                label="min_peak_snr",
            )
            max_centroid_sigma_px = _finite_nonnegative(
                self.max_centroid_sigma_px,
                label="max_centroid_sigma_px",
            )
            max_window_clipping_fraction = _finite_fraction(
                self.max_window_clipping_fraction,
                label="max_window_clipping_fraction",
            )
        except ValueError as exc:
            raise SyntheticInstrumentError(str(exc)) from exc

        object.__setattr__(self, "min_flux_e", min_flux_e)
        object.__setattr__(self, "min_peak_snr", min_peak_snr)
        object.__setattr__(
            self,
            "max_centroid_sigma_px",
            max_centroid_sigma_px,
        )
        object.__setattr__(
            self,
            "max_window_clipping_fraction",
            max_window_clipping_fraction,
        )


@dataclass(frozen=True)
class CentroidQuality:
    """Expected-signal diagnostics used by centroid-validity policy."""

    total_flux_e: float
    background_e: float
    peak_snr: float
    total_snr: float
    centroid_sigma_px: float
    clipping_fraction: float

    def __post_init__(self) -> None:
        total_flux_e = _nonnegative_or_nan(
            self.total_flux_e,
            label="total_flux_e",
        )
        background_e = _finite_nonnegative(
            self.background_e,
            label="background_e",
        )
        peak_snr = _nonnegative_or_nan(self.peak_snr, label="peak_snr")
        total_snr = _nonnegative_or_nan(self.total_snr, label="total_snr")
        centroid_sigma_px = _finite_nonnegative(
            self.centroid_sigma_px,
            label="centroid_sigma_px",
        )
        clipping_fraction = _finite_fraction(
            self.clipping_fraction,
            label="clipping_fraction",
        )

        object.__setattr__(self, "total_flux_e", total_flux_e)
        object.__setattr__(self, "background_e", background_e)
        object.__setattr__(self, "peak_snr", peak_snr)
        object.__setattr__(self, "total_snr", total_snr)
        object.__setattr__(self, "centroid_sigma_px", centroid_sigma_px)
        object.__setattr__(self, "clipping_fraction", clipping_fraction)


@dataclass(frozen=True)
class CentroidValidity:
    """Per-criterion flags, aggregate decision, and quality diagnostics."""

    valid: bool
    valid_by_flux: bool
    valid_by_snr: bool
    valid_by_uncertainty: bool
    valid_by_clipping: bool
    peak_snr: float
    total_snr: float
    centroid_sigma_px: float
    clipping_fraction: float

    def __post_init__(self) -> None:
        valid = _boolean(self.valid, label="valid")
        valid_by_flux = _boolean(self.valid_by_flux, label="valid_by_flux")
        valid_by_snr = _boolean(self.valid_by_snr, label="valid_by_snr")
        valid_by_uncertainty = _boolean(
            self.valid_by_uncertainty,
            label="valid_by_uncertainty",
        )
        valid_by_clipping = _boolean(
            self.valid_by_clipping,
            label="valid_by_clipping",
        )
        peak_snr = _nonnegative_or_nan(self.peak_snr, label="peak_snr")
        total_snr = _nonnegative_or_nan(self.total_snr, label="total_snr")
        centroid_sigma_px = _finite_nonnegative(
            self.centroid_sigma_px,
            label="centroid_sigma_px",
        )
        clipping_fraction = _finite_fraction(
            self.clipping_fraction,
            label="clipping_fraction",
        )

        criterion_flags = (
            valid_by_flux,
            valid_by_snr,
            valid_by_uncertainty,
            valid_by_clipping,
        )
        if valid and not all(criterion_flags):
            raise ValueError(
                "valid cannot be true when a validity criterion is false."
            )

        object.__setattr__(self, "valid", valid)
        object.__setattr__(self, "valid_by_flux", valid_by_flux)
        object.__setattr__(self, "valid_by_snr", valid_by_snr)
        object.__setattr__(
            self,
            "valid_by_uncertainty",
            valid_by_uncertainty,
        )
        object.__setattr__(self, "valid_by_clipping", valid_by_clipping)
        object.__setattr__(self, "peak_snr", peak_snr)
        object.__setattr__(self, "total_snr", total_snr)
        object.__setattr__(self, "centroid_sigma_px", centroid_sigma_px)
        object.__setattr__(self, "clipping_fraction", clipping_fraction)


def centroid_quality(
    cropped_spot_norm: np.ndarray,
    full_spot_norm: np.ndarray,
    detector: DetectorConfig,
    *,
    source_spot_norm: np.ndarray | None = None,
    uncertainty_model: str = "first_order",
) -> CentroidQuality:
    """Calculate expected-photon-budget diagnostics for one lenslet spot.

    The CCD equations are evaluated from expected source signal, detector
    background, and read noise rather than a noisy frame realization.  A
    detector with ``photons_per_subap_frame=None`` denotes an ideal reference
    path: flux and SNR are not applicable (NaN), while the uncertainty is
    zero.  Window clipping remains diagnostic in both modes.

    Window clipping always compares ``cropped_spot_norm`` with
    ``full_spot_norm``, so it measures optical capture.  The expected source
    image defaults to ``cropped_spot_norm``; ``source_spot_norm`` supplies it
    separately when the photon budget is allocated independently of that
    capture, as a unit-sum allocation does.

    With the default ``uncertainty_model="first_order"``, ``centroid_sigma_px``
    linearizes the center of gravity about the expected source image ``S``.
    Every window pixel carries variance ``S_i + B + RN**2`` (source and
    background/dark shot noise plus read noise), so per axis::

        Var(c_x) = sum_i (x_i - c_x)**2 * (S_i + B + RN**2) / sum_i(S_i)**2

    and the reported value is the larger of the two per-axis standard
    deviations.  It is the source-position uncertainty of a plain,
    unthresholded center of gravity without negative clipping, saturation, or
    bad pixels, expressed in pixels.  A raw-frame estimate that keeps the
    background pedestal scatters less, by ``sum(S) / sum(S + B)`` for a spot
    centred in the window and by somewhat more off centre, but its response
    to spot motion shrinks by that same factor.  The value is a first-order
    approximation for that estimator, not a bound for any other.  Negative
    clipping lowers the raw scatter of faint spots while biasing them toward
    the window centre; a Shack-Hartmann sensor built with
    ``clip_negative_pixels=False`` keeps negative pixels, and its plain center
    of gravity then scatters as stated to first order.  Thresholding is not
    modelled at all: noise switches pixels near the threshold in and out, so
    a spot with structure near the threshold level, such as a secondary peak,
    can scatter many times the reported value and still pass
    ``max_centroid_sigma_px``.
    PRNU, saturation, and bad pixels are not modelled either.
    For pure photon noise it is the larger per-axis spot RMS width over
    ``sqrt(flux)``: equal to the legacy proxy for a round spot and up to
    ``sqrt(2)`` times larger for an elongated one.

    ``uncertainty_model="legacy_spot_width"`` is the frozen historical proxy,
    the intensity-weighted spot RMS divided by ``total_snr``.  It applies the
    spot lever arm to window-wide read and background noise and is retained
    only for the bit-pinned legacy facades.
    """

    if uncertainty_model not in _UNCERTAINTY_MODELS:
        raise ValueError(
            "uncertainty_model must be 'first_order' or 'legacy_spot_width'; "
            f"got {uncertainty_model!r}."
        )
    cropped = _validated_spot(cropped_spot_norm, label="cropped_spot_norm")
    full = _validated_spot(full_spot_norm, label="full_spot_norm")
    if source_spot_norm is None:
        source = cropped
    else:
        source = _validated_spot(source_spot_norm, label="source_spot_norm")
        if source.shape != cropped.shape:
            raise ValueError(
                "source_spot_norm must share the cropped_spot_norm window "
                f"shape {cropped.shape}; got {source.shape}."
            )

    n_pixels = int(cropped.size)
    full_sum = float(np.sum(full, dtype=np.float64))
    crop_sum = float(np.sum(cropped, dtype=np.float64))
    if full_sum <= 0.0:
        clipping_fraction = 0.0
    else:
        clipping_fraction = float(
            min(max(1.0 - crop_sum / full_sum, 0.0), 1.0)
        )

    read_noise_e = _detector_scalar(
        detector,
        "read_noise_e",
        nonnegative=True,
    )
    background_per_pixel_e = _detector_scalar(
        detector,
        "background_e_per_pixel_frame",
        nonnegative=True,
    )
    dark_e_per_s = _detector_scalar(
        detector,
        "dark_e_per_s",
        nonnegative=True,
    )
    exposure_s = _detector_scalar(
        detector,
        "exposure_s",
        nonnegative=True,
    )
    background_per_pixel_e += dark_e_per_s * exposure_s
    if not math.isfinite(background_per_pixel_e):
        raise ValueError("detector background expectation must be finite.")
    background_e = background_per_pixel_e * n_pixels

    try:
        photons_value = detector.photons_per_subap_frame
    except AttributeError as exc:
        raise TypeError(
            "detector must define photons_per_subap_frame."
        ) from exc
    if photons_value is None:
        return CentroidQuality(
            total_flux_e=math.nan,
            background_e=background_e,
            peak_snr=math.nan,
            total_snr=math.nan,
            centroid_sigma_px=0.0,
            clipping_fraction=clipping_fraction,
        )

    photons = _finite_nonnegative(
        photons_value,
        label="detector.photons_per_subap_frame",
    )
    quantum_efficiency = _detector_scalar(
        detector,
        "qe",
        nonnegative=True,
    )
    with np.errstate(over="ignore", invalid="ignore"):
        signal_per_pixel_e = photons * quantum_efficiency * source
    if not np.all(np.isfinite(signal_per_pixel_e)):
        raise ValueError("expected source-electron image must be finite.")

    total_flux_e = float(np.sum(signal_per_pixel_e, dtype=np.float64))
    peak_signal_e = (
        float(np.max(signal_per_pixel_e))
        if signal_per_pixel_e.size
        else 0.0
    )
    peak_noise_e = math.sqrt(
        max(
            peak_signal_e + background_per_pixel_e + read_noise_e**2,
            0.0,
        )
    )
    peak_snr = peak_signal_e / peak_noise_e if peak_noise_e > 0.0 else 0.0
    total_noise_e = math.sqrt(
        max(
            total_flux_e
            + n_pixels * (background_per_pixel_e + read_noise_e**2),
            0.0,
        )
    )
    total_snr = total_flux_e / total_noise_e if total_noise_e > 0.0 else 0.0
    if total_snr <= 1.0e-9:
        centroid_sigma_px = UNDEFINED_CENTROID_SIGMA_PX
    elif uncertainty_model == "legacy_spot_width":
        sigma_spot_px = _intensity_weighted_rms_px(signal_per_pixel_e)
        centroid_sigma_px = sigma_spot_px / total_snr
    else:
        centroid_sigma_px = _first_order_cog_sigma_px(
            signal_per_pixel_e,
            background_per_pixel_e + read_noise_e**2,
        )
    centroid_sigma_px = float(
        min(centroid_sigma_px, UNDEFINED_CENTROID_SIGMA_PX)
    )
    return CentroidQuality(
        total_flux_e=total_flux_e,
        background_e=background_e,
        peak_snr=peak_snr,
        total_snr=total_snr,
        centroid_sigma_px=centroid_sigma_px,
        clipping_fraction=clipping_fraction,
    )


def evaluate_centroid_validity(
    estimate: CentroidEstimate,
    quality: CentroidQuality,
    config: CentroidValidityConfig | None = None,
    *,
    apply_quality_criteria: bool = True,
) -> CentroidValidity:
    """Apply independent validity thresholds to one centroid estimate."""

    if not isinstance(estimate, CentroidEstimate):
        raise TypeError(
            "estimate must be a CentroidEstimate; "
            f"got {type(estimate).__name__}."
        )
    if not isinstance(quality, CentroidQuality):
        raise TypeError(
            f"quality must be a CentroidQuality; got {type(quality).__name__}."
        )
    resolved = DEFAULT_CENTROID_VALIDITY if config is None else config
    if not isinstance(resolved, CentroidValidityConfig):
        raise TypeError(
            "config must be a CentroidValidityConfig; "
            f"got {type(resolved).__name__}."
        )
    apply_quality = _boolean(
        apply_quality_criteria,
        label="apply_quality_criteria",
    )

    if apply_quality:
        valid_by_flux = bool(quality.total_flux_e >= resolved.min_flux_e)
        valid_by_snr = bool(quality.peak_snr >= resolved.min_peak_snr)
        valid_by_uncertainty = bool(
            quality.centroid_sigma_px <= resolved.max_centroid_sigma_px
        )
    else:
        valid_by_flux = True
        valid_by_snr = True
        valid_by_uncertainty = True
    valid_by_clipping = bool(
        quality.clipping_fraction
        <= resolved.max_window_clipping_fraction
    )
    valid = bool(
        estimate.finite
        and valid_by_flux
        and valid_by_snr
        and valid_by_uncertainty
        and valid_by_clipping
    )
    return CentroidValidity(
        valid=valid,
        valid_by_flux=valid_by_flux,
        valid_by_snr=valid_by_snr,
        valid_by_uncertainty=valid_by_uncertainty,
        valid_by_clipping=valid_by_clipping,
        peak_snr=quality.peak_snr,
        total_snr=quality.total_snr,
        centroid_sigma_px=quality.centroid_sigma_px,
        clipping_fraction=quality.clipping_fraction,
    )


def _first_order_cog_sigma_px(
    signal_e: np.ndarray,
    floor_variance_e2: float,
) -> float:
    """Return the larger per-axis first-order center-of-gravity sigma.

    ``floor_variance_e2`` is the signal-independent per-pixel variance, the
    background/dark expectation plus the read-noise variance.  Each pixel is
    weighted by its own lever arm about the source centroid, so distant
    pixels dominate the read and background terms.
    """

    total = float(np.sum(signal_e, dtype=np.float64))
    if total <= 0.0:
        return UNDEFINED_CENTROID_SIGMA_PX
    rows, columns = signal_e.shape
    y_px = np.arange(rows, dtype=float)[:, None]
    x_px = np.arange(columns, dtype=float)[None, :]
    centroid_x = float(np.sum(signal_e * x_px, dtype=np.float64) / total)
    centroid_y = float(np.sum(signal_e * y_px, dtype=np.float64) / total)
    pixel_variance_e2 = signal_e + floor_variance_e2
    variance_x = float(
        np.sum(
            pixel_variance_e2 * (x_px - centroid_x) ** 2,
            dtype=np.float64,
        )
    ) / total / total
    variance_y = float(
        np.sum(
            pixel_variance_e2 * (y_px - centroid_y) ** 2,
            dtype=np.float64,
        )
    ) / total / total
    return math.sqrt(max(variance_x, variance_y, 0.0))


def _intensity_weighted_rms_px(image: np.ndarray) -> float:
    total = float(np.sum(image, dtype=np.float64))
    if total <= 0.0:
        return 0.0
    rows, columns = image.shape
    y_px = np.arange(rows, dtype=float)[:, None]
    x_px = np.arange(columns, dtype=float)[None, :]
    centroid_x = float(np.sum(image * x_px, dtype=np.float64) / total)
    centroid_y = float(np.sum(image * y_px, dtype=np.float64) / total)
    variance = float(
        np.sum(
            image
            * ((x_px - centroid_x) ** 2 + (y_px - centroid_y) ** 2),
            dtype=np.float64,
        )
        / total
    ) / 2.0
    return math.sqrt(max(variance, 0.0))


def _validated_spot(value: np.ndarray, *, label: str) -> np.ndarray:
    raw = np.asarray(value)
    if raw.ndim != 2:
        raise ValueError(f"{label} must be two-dimensional; got shape {raw.shape}.")
    if np.iscomplexobj(raw):
        raise ValueError(f"{label} must contain real intensities.")
    try:
        result = np.array(raw, dtype=float, copy=True)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{label} must contain real intensities.") from exc
    if not np.all(np.isfinite(result)):
        raise ValueError(f"{label} must contain only finite pixels.")
    if np.any(result < 0.0):
        raise ValueError(f"{label} must contain non-negative intensities.")
    return result


def _detector_scalar(
    detector: DetectorConfig,
    field: str,
    *,
    nonnegative: bool,
) -> float:
    try:
        value = getattr(detector, field)
    except AttributeError as exc:
        raise TypeError(f"detector must define {field}.") from exc
    label = f"detector.{field}"
    if nonnegative:
        return _finite_nonnegative(value, label=label)
    return _finite_float(value, label=label)


def _float(value: object, *, label: str) -> float:
    if isinstance(value, (bool, np.bool_)):
        raise ValueError(f"{label} must be a real scalar, not a boolean.")
    array = np.asarray(value)
    if array.shape != () or np.iscomplexobj(array):
        raise ValueError(f"{label} must be a real scalar; got {value!r}.")
    try:
        return float(array)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{label} must be a real scalar; got {value!r}.") from exc


def _finite_float(value: object, *, label: str) -> float:
    result = _float(value, label=label)
    if not math.isfinite(result):
        raise ValueError(f"{label} must be finite; got {value!r}.")
    return result


def _finite_nonnegative(value: object, *, label: str) -> float:
    result = _finite_float(value, label=label)
    if result < 0.0:
        raise ValueError(f"{label} must be non-negative; got {value!r}.")
    return result


def _nonnegative_or_nan(value: object, *, label: str) -> float:
    result = _float(value, label=label)
    if math.isnan(result):
        return result
    if not math.isfinite(result) or result < 0.0:
        raise ValueError(
            f"{label} must be non-negative or NaN; got {value!r}."
        )
    return result


def _finite_fraction(value: object, *, label: str) -> float:
    result = _finite_float(value, label=label)
    if result < 0.0 or result > 1.0:
        raise ValueError(f"{label} must be between zero and one; got {value!r}.")
    return result


def _boolean(value: object, *, label: str) -> bool:
    if not isinstance(value, (bool, np.bool_)):
        raise ValueError(f"{label} must be a boolean; got {value!r}.")
    return bool(value)


DEFAULT_CENTROID_VALIDITY = CentroidValidityConfig()
