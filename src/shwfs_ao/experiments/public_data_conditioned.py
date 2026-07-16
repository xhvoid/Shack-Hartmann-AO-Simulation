"""Public-data-conditioned observing profiles for SCAO experiments.

This module owns the physical conversion from seeing and public atmosphere
metadata to the compact observing-condition profiles used by the detector-level
demonstrator.  It deliberately performs no file or artifact I/O; callers pass
already-loaded public-data records and receive immutable in-memory configs.
"""

from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Sequence

from ..core.provenance import ALLOWED_SOURCE_CLASSES, Provenance as _Provenance
from ..io.public_data import EsoAsmSnapshot


ARCSEC_PER_RAD = 206264.80624709636
REFERENCE_SEEING_ARCSEC = 0.80
REFERENCE_PHASE_AMPLITUDE_NM = 260.0


class AOConditionError(ValueError):
    """Raised when an observing-condition preset is invalid."""


@dataclass(frozen=True)
class ObservingConditionConfig:
    """Observing/error condition for public-data-informed SCAO runs.

    Numerical scale belongs to the system profile.  This object controls
    atmosphere strength, photon budget, detector noise, latency, stroke,
    non-common-path aberration, and registration stress terms.
    """

    condition_name: str
    atmosphere_source: str
    seeing_arcsec: float
    r0_500_m: float
    tau0_s: float
    theta0_rad: float
    turbulence_speed_m_s: float
    photons_per_subap_frame: float
    photon_source: str
    read_noise_e: float
    latency_frames: int
    stroke_limit_nm: float
    ncpa_rms_nm: float
    misregistration_shift_px: tuple[float, float] = (0.0, 0.0)
    misregistration_rotation_deg: float = 0.0
    misregistration_magnification: float = 1.0
    misregistration_shear: float = 0.0
    exposure_latency_s: float = 0.0
    readout_latency_s: float = 0.0
    compute_latency_s: float = 0.0
    dm_settling_latency_s: float = 0.0
    source_class: str = "synthetic_assumed"
    source_note: str = "Synthetic observing-condition preset for Notebook 11."

    def __post_init__(self) -> None:
        if not self.condition_name.strip():
            raise AOConditionError("condition_name must be non-empty.")
        if not self.atmosphere_source.strip():
            raise AOConditionError("atmosphere_source must be non-empty.")
        if not self.photon_source.strip():
            raise AOConditionError("photon_source must be non-empty.")
        for name in (
            "seeing_arcsec",
            "r0_500_m",
            "tau0_s",
            "theta0_rad",
            "turbulence_speed_m_s",
            "stroke_limit_nm",
            "misregistration_magnification",
        ):
            _require_positive(name, getattr(self, name))
        _require_nonnegative(
            "photons_per_subap_frame",
            self.photons_per_subap_frame,
        )
        _require_nonnegative("read_noise_e", self.read_noise_e)
        _require_nonnegative("ncpa_rms_nm", self.ncpa_rms_nm)
        for name in (
            "misregistration_rotation_deg",
            "misregistration_shear",
            "exposure_latency_s",
            "readout_latency_s",
            "compute_latency_s",
            "dm_settling_latency_s",
        ):
            _require_finite(name, getattr(self, name))
        _require_integer("latency_frames", self.latency_frames, minimum=0)
        if len(self.misregistration_shift_px) != 2:
            raise AOConditionError(
                "misregistration_shift_px must contain two values."
            )
        _require_finite(
            "misregistration_shift_px[0]",
            self.misregistration_shift_px[0],
        )
        _require_finite(
            "misregistration_shift_px[1]",
            self.misregistration_shift_px[1],
        )
        _condition_provenance(self.source_class, self.source_note)

    @property
    def provenance(self) -> _Provenance:
        """Return the canonical provenance record for this condition."""

        return _condition_provenance(self.source_class, self.source_note)

    @property
    def latency_total_s(self) -> float:
        return float(
            self.exposure_latency_s
            + self.readout_latency_s
            + self.compute_latency_s
            + self.dm_settling_latency_s
        )

    @property
    def phase_amplitude_nm(self) -> float:
        return phase_amplitude_from_seeing(self.seeing_arcsec)

    @property
    def integer_misregistration_shift_px(self) -> tuple[int, int]:
        return (
            int(round(self.misregistration_shift_px[0])),
            int(round(self.misregistration_shift_px[1])),
        )


def phase_amplitude_from_seeing(
    seeing_arcsec: float,
    reference_seeing_arcsec: float = REFERENCE_SEEING_ARCSEC,
    reference_phase_amplitude_nm: float = REFERENCE_PHASE_AMPLITUDE_NM,
) -> float:
    """Return a documented engineering phase-amplitude proxy from seeing."""

    _require_positive("seeing_arcsec", seeing_arcsec)
    _require_positive("reference_seeing_arcsec", reference_seeing_arcsec)
    _require_positive(
        "reference_phase_amplitude_nm",
        reference_phase_amplitude_nm,
    )
    return float(
        reference_phase_amplitude_nm
        * seeing_arcsec
        / reference_seeing_arcsec
    )


def r0_from_seeing_arcsec(
    seeing_arcsec: float,
    wavelength_m: float = 500.0e-9,
) -> float:
    """Return Fried parameter from seeing for synthetic condition presets."""

    _require_positive("seeing_arcsec", seeing_arcsec)
    _require_positive("wavelength_m", wavelength_m)
    return float(0.98 * wavelength_m / (seeing_arcsec / ARCSEC_PER_RAD))


def theta0_rad_from_arcsec(theta0_arcsec: float) -> float:
    """Convert isoplanatic angle from arcseconds to radians."""

    _require_positive("theta0_arcsec", theta0_arcsec)
    return float(theta0_arcsec / ARCSEC_PER_RAD)


def default_observing_conditions(
    asm_snapshot: EsoAsmSnapshot,
    catalog_photons_per_subap_frame: float,
    photon_source: str,
) -> tuple[ObservingConditionConfig, ...]:
    """Build the five public-data-informed observing conditions."""

    _require_nonnegative(
        "catalog_photons_per_subap_frame",
        catalog_photons_per_subap_frame,
    )
    measurements = asm_snapshot.measurements
    seeing = float(measurements["seeing_arcsec_500nm"])
    r0 = float(measurements["r0_500_m"])
    tau0 = float(measurements["tau0_s"])
    theta0_rad = theta0_rad_from_arcsec(
        float(measurements["theta0_arcsec"])
    )
    speed = float(measurements["turbulence_speed_ms"])
    atmosphere_source = "ESO ASM nighttime direct_public_data cache"
    common_note = (
        "Notebook 11 public-data-informed synthetic AO condition: atmosphere "
        "and/or catalog photometry may come from public caches, while DM, "
        "detector, latency, NCPA, registration, and RTC behaviour remain "
        "synthetic engineering proxies."
    )
    return (
        ObservingConditionConfig(
            condition_name="nominal_synthetic",
            atmosphere_source="synthetic nominal seeing proxy",
            seeing_arcsec=REFERENCE_SEEING_ARCSEC,
            r0_500_m=r0_from_seeing_arcsec(REFERENCE_SEEING_ARCSEC),
            tau0_s=0.0035,
            theta0_rad=theta0_rad_from_arcsec(2.0),
            turbulence_speed_m_s=10.0,
            photons_per_subap_frame=8000.0,
            photon_source="synthetic nominal fixed photon level",
            read_noise_e=1.0,
            latency_frames=1,
            stroke_limit_nm=1000.0,
            ncpa_rms_nm=15.0,
            source_class="synthetic_assumed",
            source_note=(
                "Notebook 11 nominal synthetic condition for regression "
                "comparison."
            ),
        ),
        ObservingConditionConfig(
            condition_name="paranal_night_asm",
            atmosphere_source=atmosphere_source,
            seeing_arcsec=seeing,
            r0_500_m=r0,
            tau0_s=tau0,
            theta0_rad=theta0_rad,
            turbulence_speed_m_s=speed,
            photons_per_subap_frame=200.0,
            photon_source=(
                "engineering 200 photons/subap/frame level, not measured "
                "telemetry"
            ),
            read_noise_e=1.0,
            latency_frames=1,
            stroke_limit_nm=500.0,
            ncpa_rms_nm=25.0,
            exposure_latency_s=0.0005,
            readout_latency_s=0.0002,
            compute_latency_s=0.0002,
            dm_settling_latency_s=0.0001,
            source_class="synthetic_assumed",
            source_note=common_note,
        ),
        ObservingConditionConfig(
            condition_name="poor_seeing",
            atmosphere_source=(
                "ESO ASM nighttime scaled engineering poor-seeing proxy"
            ),
            seeing_arcsec=max(1.15, 1.35 * seeing),
            r0_500_m=r0_from_seeing_arcsec(max(1.15, 1.35 * seeing)),
            tau0_s=max(0.0015, 0.7 * tau0),
            theta0_rad=theta0_rad_from_arcsec(1.4),
            turbulence_speed_m_s=1.2 * speed,
            photons_per_subap_frame=200.0,
            photon_source=(
                "engineering 200 photons/subap/frame level, not measured "
                "telemetry"
            ),
            read_noise_e=1.5,
            latency_frames=2,
            stroke_limit_nm=220.0,
            ncpa_rms_nm=35.0,
            misregistration_shift_px=(0.4, 0.0),
            misregistration_rotation_deg=0.15,
            exposure_latency_s=0.0005,
            readout_latency_s=0.0005,
            compute_latency_s=0.0005,
            dm_settling_latency_s=0.0005,
            source_class="synthetic_assumed",
            source_note=common_note,
        ),
        ObservingConditionConfig(
            condition_name="faint_ngs",
            atmosphere_source=atmosphere_source,
            seeing_arcsec=seeing,
            r0_500_m=r0,
            tau0_s=tau0,
            theta0_rad=theta0_rad,
            turbulence_speed_m_s=speed,
            photons_per_subap_frame=max(
                1.0e-3,
                catalog_photons_per_subap_frame,
            ),
            photon_source=photon_source,
            read_noise_e=3.0,
            latency_frames=2,
            stroke_limit_nm=180.0,
            ncpa_rms_nm=45.0,
            misregistration_shift_px=(0.5, 0.0),
            misregistration_rotation_deg=0.2,
            exposure_latency_s=0.0010,
            readout_latency_s=0.0005,
            compute_latency_s=0.0003,
            dm_settling_latency_s=0.0002,
            source_class="synthetic_assumed",
            source_note=common_note,
        ),
        ObservingConditionConfig(
            condition_name="stress_all_effects",
            atmosphere_source=(
                "ESO ASM nighttime scaled engineering stress proxy"
            ),
            seeing_arcsec=max(1.25, 1.5 * seeing),
            r0_500_m=r0_from_seeing_arcsec(max(1.25, 1.5 * seeing)),
            tau0_s=max(0.0012, 0.6 * tau0),
            theta0_rad=theta0_rad_from_arcsec(1.2),
            turbulence_speed_m_s=1.4 * speed,
            photons_per_subap_frame=max(
                1.0e-3,
                catalog_photons_per_subap_frame,
            ),
            photon_source=photon_source,
            read_noise_e=5.0,
            latency_frames=3,
            stroke_limit_nm=120.0,
            ncpa_rms_nm=70.0,
            misregistration_shift_px=(0.8, 0.3),
            misregistration_rotation_deg=0.3,
            misregistration_magnification=1.01,
            misregistration_shear=0.005,
            exposure_latency_s=0.0010,
            readout_latency_s=0.0008,
            compute_latency_s=0.0007,
            dm_settling_latency_s=0.0005,
            source_class="synthetic_assumed",
            source_note=common_note,
        ),
    )


def condition_rows(
    conditions: Sequence[ObservingConditionConfig],
) -> list[dict[str, object]]:
    """Convert condition presets to stable table-ready dictionaries."""

    rows: list[dict[str, object]] = []
    for condition in conditions:
        rows.append(
            {
                "condition_name": condition.condition_name,
                "atmosphere_source": condition.atmosphere_source,
                "seeing_arcsec": condition.seeing_arcsec,
                "r0_500_m": condition.r0_500_m,
                "tau0_s": condition.tau0_s,
                "theta0_rad": condition.theta0_rad,
                "turbulence_speed_m_s": condition.turbulence_speed_m_s,
                "phase_amplitude_nm": condition.phase_amplitude_nm,
                "photons_per_subap_frame": (
                    condition.photons_per_subap_frame
                ),
                "photon_source": condition.photon_source,
                "read_noise_e": condition.read_noise_e,
                "latency_frames": condition.latency_frames,
                "latency_total_s": condition.latency_total_s,
                "stroke_limit_nm": condition.stroke_limit_nm,
                "ncpa_rms_nm": condition.ncpa_rms_nm,
                "misregistration_shift_x_px": (
                    condition.misregistration_shift_px[0]
                ),
                "misregistration_shift_y_px": (
                    condition.misregistration_shift_px[1]
                ),
                "misregistration_rotation_deg": (
                    condition.misregistration_rotation_deg
                ),
                "misregistration_magnification": (
                    condition.misregistration_magnification
                ),
                "misregistration_shear": condition.misregistration_shear,
                "source_class": condition.source_class,
                "source_note": condition.source_note,
            }
        )
    return rows


def _condition_provenance(
    source_class: str,
    source_note: str,
) -> _Provenance:
    """Build provenance while retaining condition-specific errors."""

    if source_class not in ALLOWED_SOURCE_CLASSES:
        raise AOConditionError(
            f"source_class={source_class!r} is not in the permitted taxonomy "
            f"{sorted(ALLOWED_SOURCE_CLASSES)}."
        )
    if not source_note.strip():
        raise AOConditionError("source_note must be non-empty.")
    try:
        return _Provenance(
            source_class=source_class,
            source_note=source_note,
        )
    except (TypeError, ValueError) as exc:
        raise AOConditionError(str(exc)) from exc


def _require_positive(name: str, value: float) -> None:
    _require_finite(name, value)
    if float(value) <= 0.0:
        raise AOConditionError(f"{name} must be positive.")


def _require_integer(name: str, value: int, minimum: int) -> None:
    if isinstance(value, bool) or not isinstance(value, int):
        raise AOConditionError(
            f"{name} must be an integer; got {value!r}."
        )
    if value < minimum:
        raise AOConditionError(
            f"{name} must be >= {minimum}; got {value!r}."
        )


def _require_nonnegative(name: str, value: float) -> None:
    _require_finite(name, value)
    if float(value) < 0.0:
        raise AOConditionError(f"{name} must be non-negative.")


def _require_finite(name: str, value: float) -> None:
    if not math.isfinite(float(value)):
        raise AOConditionError(f"{name} must be finite.")


__all__ = (
    "AOConditionError",
    "ARCSEC_PER_RAD",
    "ObservingConditionConfig",
    "REFERENCE_PHASE_AMPLITUDE_NM",
    "REFERENCE_SEEING_ARCSEC",
    "condition_rows",
    "default_observing_conditions",
    "phase_amplitude_from_seeing",
    "r0_from_seeing_arcsec",
    "theta0_rad_from_arcsec",
)
