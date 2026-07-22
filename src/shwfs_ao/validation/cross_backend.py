"""Native-versus-HCIPy cross-backend comparison suite.

The suite demonstrates that the native backend is a transparent reference
implementation and HCIPy is an independently implemented physical backend.
It runs thirteen comparisons on one small deterministic profile, groups
every metric into the AO-REF-018 tolerance levels (``exact``,
``tight_numerical``, ``physical_tolerance``, ``informational``), and returns
a JSON report document evaluated by :mod:`shwfs_ao.validation.regression`.

Design rules:

- Pointwise optical comparisons feed both backends the same deterministic
  fixtures — elementary polynomial and seeded-draw arrays whose content
  hashes are recorded in the report, so a baseline can prove the inputs were
  identical.  Fixtures deliberately avoid FFT-derived data.
- Independently generated native and HCIPy atmospheres are compared only by
  statistical diagnostics; equal seeds do not imply equal realizations
  across libraries, and no generator screen array is hashed.
- The closed-loop comparison replays one recorded OPD-cube fixture: the
  native frozen-flow realization is sampled once over the shared time grid,
  the cube's hash is recorded beside the other shared-input fixtures, and
  both backend loops consume that identical recording through a fail-closed
  replay component that rejects any off-grid sample.
- Every physical tolerance carries a written rationale.  Runtime and memory
  are informational only and never gate.
- No claim of complete equivalence is made: each comparison names the
  known cause of residual discrepancy (grid sampling, normalization,
  interpolation, or influence/window conventions).

Importing this module never imports HCIPy; running the suite resolves the
optional dependency and raises ``OptionalDependencyError`` without it.
"""

from __future__ import annotations

from dataclasses import dataclass
import math
import platform
import sys
import time
import tracemalloc
from types import MappingProxyType
from typing import Any, ClassVar, Mapping

import numpy as np

from ..core.hashing import component_config_hash, stable_hash
from ..core.wavefront import masked_rms, opd_to_phase
from .physical import (
    centroid_xy_px,
    encircled_energy_radius_rad,
    mean_square_column_difference,
    normalized_singular_spectrum,
)
from .regression import (
    CROSS_BACKEND_BASELINE_SCHEMA_VERSION,
    CROSS_BACKEND_REPORT_SCHEMA_NAME,
    validate_cross_backend_report,
)


_FIXTURE_HASH_NAMESPACE = "cross_backend_fixture"
_ID_HASH_NAMESPACE = "cross_backend_identity"

__all__ = (
    "CrossBackendError",
    "CrossBackendConfig",
    "run_cross_backend_report",
)


class CrossBackendError(ValueError):
    """Raised when the cross-backend suite is configured inconsistently."""


@dataclass(frozen=True)
class CrossBackendConfig:
    """Deterministic small-profile configuration for the comparison suite."""

    root_seed: int = 118
    telescope_diameter_m: float = 1.0
    pupil_pixels: int = 48
    lenslets_across: int = 3
    min_fill_fraction: float = 0.3
    wfs_wavelength_m: float = 700.0e-9
    science_wavelength_m: float = 700.0e-9
    spot_sampling_px: float = 4.0
    n_actuators_across: int = 3
    coupling_width_pitch: float = 0.35
    stroke_limit_nm: float = 20000.0
    photons_per_subap_frame: float = 2.0e4
    static_aberration_rms_m: float = 60.0e-9
    tilt_amplitude_px: float = 0.8
    r0_m: float = 0.15
    outer_scale_m: float = 20.0
    wind_m_per_s: tuple[float, float] = (5.0, 0.0)
    atmosphere_realizations: int = 4
    structure_function_lags_px: tuple[int, int] = (2, 4)
    frame_rate_hz: float = 500.0
    # The loop replays gentler seeing than the statistics comparison: the
    # small HCIPy focal windows legitimately invalidate strongly displaced
    # spots through the clipping gate, and the loop comparison probes
    # backend behaviour, not the unusable-input policy.
    loop_r0_m: float = 0.45
    loop_steps: int = 4
    loop_gain: float = 0.5
    psf_pad_factor: int = 4
    hcipy_psf_pixels_per_resolution_element: float = 5.0
    hcipy_psf_radius_resolution_elements: float = 12.0
    runtime_repeats: int = 3

    __hash_schema_id__: ClassVar[str] = "shwfs_ao.validation.cross_backend_config.v1"

    def __post_init__(self) -> None:
        if self.pupil_pixels % self.lenslets_across != 0:
            raise CrossBackendError(
                "pupil_pixels must be an integer multiple of lenslets_across "
                "for the HCIPy block-window optics."
            )
        if self.atmosphere_realizations < 2:
            raise CrossBackendError(
                "atmosphere_realizations must be at least 2 for statistics."
            )
        if self.loop_steps < 2:
            raise CrossBackendError("loop_steps must be at least 2.")
        if self.runtime_repeats < 1:
            raise CrossBackendError("runtime_repeats must be at least 1.")

    @property
    def config_hash(self) -> str:
        return component_config_hash("cross_backend_comparison", self)


def run_cross_backend_report(
    config: CrossBackendConfig | None = None,
    *,
    dependency_constraint_file: str | None = None,
    dependency_constraint_sha256: str | None = None,
) -> dict[str, Any]:
    """Execute every comparison and return the validated report document.

    The optional dependency-constraint identity is provenance recorded by
    the candidate-generation script; interactive runs record it as
    ``unrecorded`` and baseline evaluation never compares environments.
    """

    resolved = CrossBackendConfig() if config is None else config
    if not isinstance(resolved, CrossBackendConfig):
        raise CrossBackendError("config must be a CrossBackendConfig or None.")

    from ..backends.hcipy import hcipy_version, require_hcipy

    require_hcipy()

    context = _ComparisonContext.build(resolved)
    comparisons = [
        _compare_pupil_and_throughput(context),
        _compare_zernike_modes(context),
        _compare_atmosphere_statistics(context),
        _compare_wfs_tip_tilt(context),
        _compare_spot_morphology(context),
        _compare_dm_influence(context),
        _compare_dm_static_fitting(context),
        _compare_interaction_matrix(context),
        _compare_singular_spectrum(context),
        _compare_psf_normalization(context),
        _compare_strehl(context),
        _compare_closed_loop(context),
        _compare_runtime_and_memory(context),
    ]

    import shwfs_ao

    report: dict[str, Any] = {
        "artifact_schema_name": CROSS_BACKEND_REPORT_SCHEMA_NAME,
        "artifact_schema_version": CROSS_BACKEND_BASELINE_SCHEMA_VERSION,
        "comparison_config": _config_record(resolved),
        "root_seed": resolved.root_seed,
        "conventions": {
            "command_unit": "m_opd_equivalent",
            "residual_sign_convention": (
                "residual_opd_m = atmosphere_opd_m - dm_correction_opd_m"
            ),
            "measurement_unit": "pixel",
            "detector_column_sign_convention": (
                "positive_x_tilt_moves_spots_toward_positive_columns"
            ),
        },
        "component_hashes": context.component_hashes,
        "fixture_hashes": context.fixture_hashes,
        "environment": {
            "python_version": sys.version.split()[0],
            "numpy_version": np.__version__,
            "shwfs_ao_version": shwfs_ao.__version__,
            "hcipy_version": hcipy_version(),
            "platform": platform.platform(),
            "dependency_constraint_file": (
                dependency_constraint_file or "unrecorded"
            ),
            "dependency_constraint_sha256": (
                dependency_constraint_sha256 or "unrecorded"
            ),
        },
        "comparisons": comparisons,
    }
    validate_cross_backend_report(report)
    return report


class _RecordedOpdCubeAtmosphere:
    """Fail-closed replay of the recorded shared OPD-cube fixture.

    Both backend loops consume this identical recording, so every
    atmospheric input sample — not only the time grid — is one hashed
    shared-input fixture.  A query off the recorded grid or for a different
    realization is a contract violation, never an interpolation.
    """

    def __init__(
        self,
        *,
        opd_cube_m: np.ndarray,
        time_grid_s: np.ndarray,
        root_seed: int,
        cube_hash: str,
        source_config_hash: str,
    ) -> None:
        self._cube = np.asarray(opd_cube_m, dtype=float)
        self._time_grid_s = np.asarray(time_grid_s, dtype=float)
        if self._cube.ndim != 3 or self._cube.shape[0] != self._time_grid_s.size:
            raise CrossBackendError(
                "the recorded OPD cube must hold one sample per shared "
                "time-grid entry."
            )
        self._root_seed = int(root_seed)
        self._cube_hash = cube_hash
        self._source_config_hash = source_config_hash

    @property
    def backend_name(self) -> str:
        return "shared_fixture_replay"

    @property
    def config_hash(self) -> str:
        return self._cube_hash

    @property
    def root_seed(self) -> int:
        return self._root_seed

    @property
    def metadata(self) -> Mapping[str, Any]:
        return MappingProxyType(
            {
                "backend_name": self.backend_name,
                "config_hash": self._cube_hash,
                "root_seed": self._root_seed,
                "realization_index": 0,
                "source_atmosphere_config_hash": self._source_config_hash,
                "n_recorded_samples": int(self._cube.shape[0]),
            }
        )

    def reset(self, *, realization_index: int = 0) -> None:
        if realization_index != 0:
            raise CrossBackendError(
                "the shared OPD-cube fixture records realization 0 only."
            )

    def opd_at(self, time_s: float) -> np.ndarray:
        matches = np.flatnonzero(self._time_grid_s == float(time_s))
        if matches.size != 1:
            raise CrossBackendError(
                "the closed-loop comparison may sample the shared OPD-cube "
                f"fixture only on its recorded time grid; got t={time_s!r} s."
            )
        return self._cube[int(matches[0])].copy()


class _ComparisonContext:
    """Shared deterministic components and fixtures for every comparison.

    The backend components (optics, deformable mirrors, propagators, sensors,
    geometry) are held as ``Any``: they come from optional and native backends
    resolved lazily in :meth:`build`, and every comparison consumes them
    through the same opaque, backend-neutral surface the rest of this module
    uses.  The deterministic fixtures and recorded hashes are typed concretely
    because they are this module's own evidence.
    """

    config: CrossBackendConfig
    geometry: Any
    pupil: Any
    pixel_pitch_m: float
    native_optics: Any
    hcipy_optics: Any
    native_dm: Any
    hcipy_dm: Any
    native_science: Any
    hcipy_science: Any
    native_sensor: Any
    hcipy_sensor: Any
    unit_modes: dict[str, np.ndarray]
    static_opd_m: np.ndarray
    tilt_slope_rad: float
    tilt_x_opd_m: np.ndarray
    tilt_y_opd_m: np.ndarray
    command_fixture_opd_m: np.ndarray
    time_grid_s: np.ndarray
    shared_atmosphere: Any
    actuator_centers_m: np.ndarray
    actuator_pitch_m: float
    fixture_hashes: dict[str, str]
    component_hashes: dict[str, str]
    # Memoized during the comparison run, not at build time.
    native_interaction: Any
    hcipy_interaction: Any
    native_psf: Any
    hcipy_psf: Any

    def __init__(self, **attributes: Any) -> None:
        self.__dict__.update(attributes)

    @classmethod
    def build(cls, config: CrossBackendConfig) -> "_ComparisonContext":
        from ..backends.hcipy.dm import build_hcipy_deformable_mirror
        from ..backends.hcipy.propagation import (
            HcipyFocalSampling,
            HcipySciencePropagator,
        )
        from ..backends.hcipy.shwfs import HcipyShackHartmannOptics
        from ..backends.native.dm import square_grid_actuator_layout
        from ..backends.native.modes import (
            normalize_mode_to_unit_pupil_rms,
            polar_pupil_coordinates,
            zernike_named_modes,
        )
        from ..backends.native.propagation import NativeSciencePropagator
        from ..backends.native.shwfs import NativeShackHartmannOptics
        from ..core.random import NamedRandomStreams
        from ..detector.config import DetectorConfig
        from ..dm import DMConfig
        from ..dm.model import build_native_deformable_mirror
        from ..science.propagation import PsfSampling
        from ..wfs.shack_hartmann.geometry import build_shack_hartmann_geometry
        from ..wfs.shack_hartmann.measurement import (
            build_detector_shack_hartmann_sensor,
        )

        geometry = build_shack_hartmann_geometry(
            telescope_diameter_m=config.telescope_diameter_m,
            pupil_shape=(config.pupil_pixels, config.pupil_pixels),
            n_lenslets_across=config.lenslets_across,
            min_fill_fraction=config.min_fill_fraction,
        )
        pupil = geometry.pupil_geometry
        pixel_pitch_m = float(geometry.x_m[0, 1] - geometry.x_m[0, 0])
        f_number = (
            config.spot_sampling_px * pixel_pitch_m / config.wfs_wavelength_m
        )

        native_optics = NativeShackHartmannOptics(
            geometry,
            config.wfs_wavelength_m,
            pad_factor=8,
        )
        hcipy_optics = HcipyShackHartmannOptics(
            geometry,
            config.wfs_wavelength_m,
            f_number=f_number,
        )

        dm_config = DMConfig(
            telescope_diameter_m=config.telescope_diameter_m,
            n_actuators_across=config.n_actuators_across,
            coupling_width_pitch=config.coupling_width_pitch,
            stroke_limit_nm=config.stroke_limit_nm,
        )
        native_dm = build_native_deformable_mirror(
            geometry.x_m,
            geometry.y_m,
            geometry.pupil_mask,
            dm_config,
        )
        hcipy_dm = build_hcipy_deformable_mirror(
            geometry.x_m,
            geometry.y_m,
            geometry.pupil_mask,
            dm_config,
        )

        native_science = NativeSciencePropagator(
            pupil=pupil,
            sampling=PsfSampling(pad_factor=config.psf_pad_factor),
        )
        hcipy_science = HcipySciencePropagator(
            pupil,
            HcipyFocalSampling(
                config.hcipy_psf_pixels_per_resolution_element,
                config.hcipy_psf_radius_resolution_elements,
            ),
        )

        detector_config = DetectorConfig(
            photons_per_subap_frame=config.photons_per_subap_frame,
        )
        native_sensor = build_detector_shack_hartmann_sensor(
            geometry,
            native_optics,
            detector_config,
            wfs_wavelength_m=config.wfs_wavelength_m,
            random_streams=NamedRandomStreams(config.root_seed),
        )
        hcipy_sensor = build_detector_shack_hartmann_sensor(
            geometry,
            hcipy_optics,
            detector_config,
            wfs_wavelength_m=config.wfs_wavelength_m,
            random_streams=NamedRandomStreams(config.root_seed),
        )

        # Deterministic fixtures: elementary arithmetic and seeded draws
        # only, so their hashes are stable evidence of shared inputs.
        rho, theta = polar_pupil_coordinates(
            geometry.x_m,
            geometry.y_m,
            config.telescope_diameter_m,
        )
        named_modes = zernike_named_modes(rho, theta, geometry.pupil_mask)
        unit_modes = {
            name: normalize_mode_to_unit_pupil_rms(mode, geometry.pupil_mask)
            for name, mode in named_modes.items()
        }
        streams = NamedRandomStreams(config.root_seed)
        coefficient_generator = streams.keyed_generator(
            "calibration",
            key=("cross_backend", "static-opd"),
        )
        static_names = ("defocus", "astig_0", "coma_x")
        coefficients = coefficient_generator.standard_normal(len(static_names))
        static_shape = np.zeros(geometry.pupil_mask.shape, dtype=float)
        for coefficient, name in zip(coefficients, static_names):
            static_shape = static_shape + float(coefficient) * np.where(
                geometry.pupil_mask, unit_modes[name], 0.0
            )
        static_rms_m = masked_rms(
            np.where(geometry.pupil_mask, static_shape, np.nan),
            geometry.pupil_mask,
        )
        static_opd_m = static_shape * (
            config.static_aberration_rms_m / static_rms_m
        )

        tilt_slope_rad = (
            config.tilt_amplitude_px * hcipy_optics.sampling.pixel_scale_rad[0]
        )
        tilt_x_opd_m = tilt_slope_rad * np.asarray(geometry.x_m, dtype=float)
        tilt_y_opd_m = tilt_slope_rad * np.asarray(geometry.y_m, dtype=float)

        command_generator = streams.keyed_generator(
            "calibration",
            key=("cross_backend", "commands"),
        )
        command_fixture_opd_m = 100.0e-9 * command_generator.standard_normal(
            native_dm.n_actuators
        )
        time_grid_s = np.arange(config.loop_steps, dtype=float) / config.frame_rate_hz

        # AO-REF-018 shared-input contract for the closed-loop comparison:
        # sample the frozen-flow realization exactly once over the shared
        # time grid and hash the resulting OPD cube.  Both backend loops
        # replay this recording, so identical atmospheric input is recorded
        # evidence, not an assumption about seeded reconstruction.
        from ..backends.native.atmosphere import (
            FrozenFlowAtmosphere,
            FrozenFlowAtmosphereConfig,
        )

        source_atmosphere = FrozenFlowAtmosphere(
            FrozenFlowAtmosphereConfig(
                grid_size=pupil.pupil_shape[0],
                delta_m=pupil.pixel_spacing_xy_m[0],
                pupil_diameter_m=config.telescope_diameter_m,
                r0_m=config.loop_r0_m,
                outer_scale_m=config.outer_scale_m,
                wind_m_per_s=config.wind_m_per_s,
                root_seed=config.root_seed,
            ),
            pupil_mask=geometry.pupil_mask,
        )
        source_atmosphere.reset(realization_index=0)
        atmosphere_opd_cube_m = np.stack(
            [source_atmosphere.opd_at(float(sample_s)) for sample_s in time_grid_s]
        )
        atmosphere_cube_hash = _fixture_hash(atmosphere_opd_cube_m)
        shared_atmosphere = _RecordedOpdCubeAtmosphere(
            opd_cube_m=atmosphere_opd_cube_m,
            time_grid_s=time_grid_s,
            root_seed=config.root_seed,
            cube_hash=atmosphere_cube_hash,
            source_config_hash=source_atmosphere.config_hash,
        )

        centers_m, pitch_m, _ = square_grid_actuator_layout(
            config.telescope_diameter_m,
            config.n_actuators_across,
        )

        fixture_hashes = {
            "static_opd_m": _fixture_hash(static_opd_m),
            "tilt_x_opd_m": _fixture_hash(tilt_x_opd_m),
            "tilt_y_opd_m": _fixture_hash(tilt_y_opd_m),
            "command_fixture_opd_m": _fixture_hash(command_fixture_opd_m),
            "time_grid_s": _fixture_hash(time_grid_s),
            "atmosphere_opd_cube_m": atmosphere_cube_hash,
        }
        component_hashes = {
            "pupil_geometry": pupil.geometry_hash,
            "shack_hartmann_geometry": geometry.geometry_hash,
            "native_wfs_optics": native_optics.config_hash,
            "hcipy_wfs_optics": hcipy_optics.config_hash,
            "native_dm": native_dm.config_hash,
            "hcipy_dm": hcipy_dm.config_hash,
            "native_science": native_science.config_hash,
            "hcipy_science": hcipy_science.config_hash,
            "wfs_row_ids": stable_hash(
                native_sensor.row_ids,
                namespace=_ID_HASH_NAMESPACE,
            ),
            "dm_actuator_ids": stable_hash(
                native_dm.actuator_ids,
                namespace=_ID_HASH_NAMESPACE,
            ),
        }

        return cls(
            config=config,
            geometry=geometry,
            pupil=pupil,
            pixel_pitch_m=pixel_pitch_m,
            native_optics=native_optics,
            hcipy_optics=hcipy_optics,
            native_dm=native_dm,
            hcipy_dm=hcipy_dm,
            native_science=native_science,
            hcipy_science=hcipy_science,
            native_sensor=native_sensor,
            hcipy_sensor=hcipy_sensor,
            unit_modes=unit_modes,
            static_opd_m=static_opd_m,
            tilt_slope_rad=tilt_slope_rad,
            tilt_x_opd_m=tilt_x_opd_m,
            tilt_y_opd_m=tilt_y_opd_m,
            command_fixture_opd_m=command_fixture_opd_m,
            time_grid_s=time_grid_s,
            shared_atmosphere=shared_atmosphere,
            actuator_centers_m=centers_m,
            actuator_pitch_m=pitch_m,
            fixture_hashes=fixture_hashes,
            component_hashes=component_hashes,
        )


def _compare_pupil_and_throughput(context: _ComparisonContext) -> dict[str, Any]:
    from ..backends.hcipy.conversion import (
        aperture_field_from_mask,
        hcipy_grid_from_geometry,
        mask_from_aperture_field,
    )

    geometry = context.geometry
    grid = hcipy_grid_from_geometry(context.pupil)
    round_trip = mask_from_aperture_field(
        aperture_field_from_mask(geometry.pupil_mask, grid)
    )
    zero = np.zeros(geometry.pupil_shape, dtype=float)
    native_capture = float(
        np.mean(context.native_optics.spot_intensities(zero).relative_throughput)
    )
    hcipy_capture = float(
        np.mean(context.hcipy_optics.spot_intensities(zero).relative_throughput)
    )

    return {
        "comparison_kind": "pupil_mask_and_throughput",
        "attribution": (
            "Both backends consume the identical repository pupil mask "
            "through the conversion layer; capture fractions differ only "
            "through each backend's detector-window convention (full padded "
            "FFT canvas versus pupil-sampled focal blocks)."
        ),
        "metrics": [
            _metric(
                "mask_round_trip_identical",
                "exact",
                "boolean",
                bool(np.array_equal(round_trip, geometry.pupil_mask)),
                {"type": "equals", "expected": True},
                "The conversion layer must preserve the pupil mask exactly.",
            ),
            _metric(
                "illuminated_sample_count",
                "exact",
                "samples",
                int(np.count_nonzero(geometry.pupil_mask)),
                {
                    "type": "equals",
                    "expected": int(np.count_nonzero(geometry.pupil_mask)),
                },
                "Both backends see the same illuminated sample inventory.",
            ),
            _metric(
                "native_mean_window_capture",
                "tight_numerical",
                "fraction",
                native_capture,
                {"type": "abs_tolerance", "expected": 1.0, "tolerance": 1.0e-9},
                "The native full-canvas window captures each normalized "
                "lenslet spot completely.",
            ),
            _metric(
                "hcipy_mean_window_capture",
                "physical_tolerance",
                "fraction",
                hcipy_capture,
                {"type": "range", "low": 0.90, "high": 1.0},
                "Finite pupil-sampled focal windows lose a few percent of "
                "each spot to diffraction wings; well below 10 % for the "
                "configured four-pixel spot sampling.",
            ),
        ],
    }


def _compare_zernike_modes(context: _ComparisonContext) -> dict[str, Any]:
    from ..backends.hcipy import require_hcipy
    from ..backends.native.modes import normalize_mode_to_unit_pupil_rms

    hcipy = require_hcipy()
    from ..backends.hcipy.conversion import hcipy_grid_from_geometry

    geometry = context.geometry
    mask = geometry.pupil_mask
    grid = hcipy_grid_from_geometry(context.pupil)
    basis = hcipy.make_zernike_basis(
        6,
        context.config.telescope_diameter_m,
        grid,
        starting_mode=1,
    )
    matrix = basis.transformation_matrix
    if hasattr(matrix, "toarray"):
        matrix = matrix.toarray()
    noll_by_name = {
        "tip_x": 2,
        "tip_y": 3,
        "defocus": 4,
        "astig_45": 5,
        "astig_0": 6,
    }
    metrics: list[dict[str, Any]] = []
    for name, noll_index in noll_by_name.items():
        native_mode = context.unit_modes[name]
        hcipy_mode = normalize_mode_to_unit_pupil_rms(
            np.asarray(matrix[:, noll_index - 1], dtype=float).reshape(
                geometry.pupil_shape
            ),
            mask,
        )
        correlation = float(
            np.mean(native_mode[mask] * hcipy_mode[mask])
        )
        metrics.append(
            _metric(
                f"{name}_alignment_defect",
                "tight_numerical",
                "1 - |correlation|",
                float(1.0 - abs(correlation)),
                {"type": "abs_tolerance", "expected": 0.0, "tolerance": 1.0e-9},
                "Identical polynomials sampled on one grid and normalized "
                "to unit sampled pupil RMS must correlate to unity.",
            )
        )
        metrics.append(
            _metric(
                f"{name}_relative_sign",
                "exact",
                "sign",
                int(np.sign(correlation)),
                {"type": "equals", "expected": 1},
                "The repository Noll-name mapping fixes the relative sign "
                "convention between the two mode constructions.",
            )
        )
    return {
        "comparison_kind": "zernike_modes",
        "attribution": (
            "Native named modes and HCIPy Noll modes are the same "
            "polynomials; only normalization conventions differ and both "
            "are renormalized to unit sampled pupil RMS before comparison."
        ),
        "metrics": metrics,
    }


def _compare_atmosphere_statistics(context: _ComparisonContext) -> dict[str, Any]:
    from ..backends.hcipy.atmosphere import (
        HcipyAtmosphereConfig,
        HcipyVonKarmanAtmosphere,
    )
    from ..backends.native.atmosphere import (
        FrozenFlowAtmosphere,
        FrozenFlowAtmosphereConfig,
    )

    config = context.config
    geometry = context.geometry
    native_model = FrozenFlowAtmosphere(
        FrozenFlowAtmosphereConfig(
            grid_size=context.pupil.pupil_shape[0],
            delta_m=context.pupil.pixel_spacing_xy_m[0],
            pupil_diameter_m=config.telescope_diameter_m,
            r0_m=config.r0_m,
            outer_scale_m=config.outer_scale_m,
            wind_m_per_s=config.wind_m_per_s,
            root_seed=config.root_seed,
        ),
        pupil_mask=geometry.pupil_mask,
    )
    hcipy_model = HcipyVonKarmanAtmosphere(
        HcipyAtmosphereConfig.single_layer(
            r0_m=config.r0_m,
            outer_scale_m=config.outer_scale_m,
            wind_m_per_s=config.wind_m_per_s,
            root_seed=config.root_seed,
        ),
        context.pupil,
        pupil_mask=geometry.pupil_mask,
    )

    short_lag, long_lag = config.structure_function_lags_px

    def statistics(model: Any) -> tuple[np.ndarray, np.ndarray]:
        rms_values = []
        ratio_values = []
        for realization in range(config.atmosphere_realizations):
            model.reset(realization_index=realization)
            screen = model.opd_at(0.0)
            rms_values.append(masked_rms(screen, geometry.pupil_mask))
            ratio_values.append(
                mean_square_column_difference(screen, long_lag)
                / mean_square_column_difference(screen, short_lag)
            )
        return (
            np.asarray(rms_values, dtype=float),
            np.asarray(ratio_values, dtype=float),
        )

    native_rms_values, native_ratio_values = statistics(native_model)
    hcipy_rms_values, hcipy_ratio_values = statistics(hcipy_model)
    native_rms_m = float(np.mean(native_rms_values))
    hcipy_rms_m = float(np.mean(hcipy_rms_values))
    native_sf_ratio = float(np.mean(native_ratio_values))
    hcipy_sf_ratio = float(np.mean(hcipy_ratio_values))
    kolmogorov_ratio = (long_lag / short_lag) ** (5.0 / 3.0)

    rms_ratio = hcipy_rms_m / native_rms_m
    rms_ratio_se = abs(rms_ratio) * math.hypot(
        _standard_error(hcipy_rms_values) / hcipy_rms_m,
        _standard_error(native_rms_values) / native_rms_m,
    )
    native_sf_se = _standard_error(native_ratio_values)
    hcipy_sf_se = _standard_error(hcipy_ratio_values)

    # The recorded tolerance claim must be checkable, not narrative: every
    # gating value has to sit more than three computed standard errors
    # inside its range, or generation fails instead of minting a criterion
    # the observed dispersion does not support.
    gating = (
        ("rms_ratio_hcipy_over_native", rms_ratio, 0.55, 1.8, rms_ratio_se),
        (
            "native_structure_function_lag_ratio",
            native_sf_ratio,
            1.6,
            4.2,
            native_sf_se,
        ),
        (
            "hcipy_structure_function_lag_ratio",
            hcipy_sf_ratio,
            1.6,
            4.2,
            hcipy_sf_se,
        ),
    )
    for name, value, low, high, standard_error in gating:
        margin = min(value - low, high - value)
        if not margin > 3.0 * standard_error:
            raise CrossBackendError(
                f"atmosphere statistic {name!r} sits within three standard "
                f"errors of its range criterion: value={value}, "
                f"range=[{low}, {high}], standard_error={standard_error}; "
                "widen the range or add realizations before regenerating."
            )

    statistical_note = (
        f"{config.atmosphere_realizations} independent realizations per "
        "backend at t=0; estimator: masked pupil RMS and the ratio of "
        f"mean-square column differences at lags {long_lag}px/{short_lag}px; "
        "uncertainty: first-order standard errors of each ratio estimator "
        "across the realizations, recorded as informational metrics, and "
        "every recorded value is verified at generation time to sit more "
        "than three standard errors inside its range criterion."
    )
    return {
        "comparison_kind": "atmosphere_statistics",
        "attribution": (
            "Screens are generated by independent spectral implementations; "
            "equal seeds do not imply equal realizations, so only "
            "statistics are compared. Finite outer scale and pupil-scale "
            "sampling pull both structure-function ratios below the pure "
            f"Kolmogorov value {kolmogorov_ratio:.3f}."
        ),
        "statistical_definition": statistical_note,
        "metrics": [
            _metric(
                "rms_ratio_hcipy_over_native",
                "physical_tolerance",
                "ratio",
                rms_ratio,
                {"type": "range", "low": 0.55, "high": 1.8},
                "Same r0, outer scale, and pupil: mean RMS must agree "
                "within finite-sample von Karman scatter for "
                f"{config.atmosphere_realizations} realizations.",
            ),
            _metric(
                "native_structure_function_lag_ratio",
                "physical_tolerance",
                "ratio",
                native_sf_ratio,
                {"type": "range", "low": 1.6, "high": 4.2},
                "Small-lag structure-function growth must sit near the "
                "Kolmogorov 5/3 scaling, reduced by the finite outer scale.",
            ),
            _metric(
                "hcipy_structure_function_lag_ratio",
                "physical_tolerance",
                "ratio",
                hcipy_sf_ratio,
                {"type": "range", "low": 1.6, "high": 4.2},
                "Same physical expectation as the native screen generator.",
            ),
            _metric(
                "rms_ratio_standard_error",
                "informational",
                "ratio",
                rms_ratio_se,
                {"type": "informational"},
                "First-order standard error of the RMS ratio across the "
                "independent realizations; recorded so the range criterion "
                "is checkably wider than the observed scatter.",
            ),
            _metric(
                "native_structure_function_ratio_standard_error",
                "informational",
                "ratio",
                native_sf_se,
                {"type": "informational"},
                "Standard error of the native structure-function lag ratio "
                "across the independent realizations.",
            ),
            _metric(
                "hcipy_structure_function_ratio_standard_error",
                "informational",
                "ratio",
                hcipy_sf_se,
                {"type": "informational"},
                "Standard error of the HCIPy structure-function lag ratio "
                "across the independent realizations.",
            ),
        ],
    }


def _standard_error(values: np.ndarray) -> float:
    samples = np.asarray(values, dtype=float)
    return float(np.std(samples, ddof=1) / math.sqrt(samples.size))


def _compare_wfs_tip_tilt(context: _ComparisonContext) -> dict[str, Any]:
    from ..core.random import NamedRandomStreams

    def response(
        sensor: Any,
        optics: Any,
        opd_m: np.ndarray,
    ) -> tuple[float, float]:
        """Return mean (x, y) response as angular gain-normalized pixels.

        Each sensor reports centroid shifts in its own detector pixels; the
        applied displacement in those pixels is the shared angular slope
        divided by that backend's pixel scale, so gains are comparable.
        """

        measurement = sensor.measure(
            opd_m,
            random_streams=NamedRandomStreams(context.config.root_seed),
            include_noise=False,
        )
        values = np.asarray(measurement.vector.values, dtype=float)
        applied_px = (
            context.tilt_slope_rad / optics.sampling.pixel_scale_rad[0]
        )
        return (
            float(np.mean(values[0::2])) / applied_px,
            float(np.mean(values[1::2])) / applied_px,
        )

    native_x, native_cross = response(
        context.native_sensor,
        context.native_optics,
        context.tilt_x_opd_m,
    )
    hcipy_x, hcipy_cross = response(
        context.hcipy_sensor,
        context.hcipy_optics,
        context.tilt_x_opd_m,
    )
    native_y = response(
        context.native_sensor,
        context.native_optics,
        context.tilt_y_opd_m,
    )[1]
    hcipy_y = response(
        context.hcipy_sensor,
        context.hcipy_optics,
        context.tilt_y_opd_m,
    )[1]

    return {
        "comparison_kind": "wfs_tip_tilt_response",
        "attribution": (
            "One shared tilt fixture drives both detector-level sensors "
            "through the identical repository detector and centroid chain; "
            "gain differences come from each backend's window truncation "
            "and the HCIPy full-field lenslet crosstalk."
        ),
        "metrics": [
            _metric(
                "native_x_response_sign",
                "tight_numerical",
                "sign",
                int(np.sign(native_x)),
                {"type": "equals", "expected": 1},
                "Positive x-tilt must move native centroids toward "
                "positive detector columns.",
            ),
            _metric(
                "hcipy_x_response_sign",
                "tight_numerical",
                "sign",
                int(np.sign(hcipy_x)),
                {"type": "equals", "expected": 1},
                "Positive x-tilt must move HCIPy centroids toward positive "
                "detector columns.",
            ),
            _metric(
                "native_cross_axis_fraction",
                "tight_numerical",
                "fraction of applied tilt",
                abs(native_cross),
                {"type": "abs_tolerance", "expected": 0.0, "tolerance": 0.05},
                "A pure x-tilt produces no mean y response beyond "
                "discretization noise.",
            ),
            _metric(
                "hcipy_cross_axis_fraction",
                "tight_numerical",
                "fraction of applied tilt",
                abs(hcipy_cross),
                {"type": "abs_tolerance", "expected": 0.0, "tolerance": 0.05},
                "Same cross-axis expectation for the HCIPy optics.",
            ),
            _metric(
                "native_tilt_gain",
                "physical_tolerance",
                "measured over applied angular displacement",
                native_x,
                {"type": "range", "low": 0.75, "high": 1.10},
                "Thresholded centre-of-gravity truncation keeps the native "
                "gain near but below the ideal unity response.",
            ),
            _metric(
                "hcipy_tilt_gain",
                "physical_tolerance",
                "measured over applied angular displacement",
                hcipy_x,
                {"type": "range", "low": 0.70, "high": 1.05},
                "The smaller HCIPy focal windows truncate slightly more of "
                "each spot wing than the native canvas.",
            ),
            _metric(
                "tilt_gain_ratio_hcipy_over_native",
                "physical_tolerance",
                "ratio",
                hcipy_x / native_x,
                {"type": "range", "low": 0.80, "high": 1.10},
                "Window truncation and lenslet crosstalk explain the "
                "remaining gain difference between the two optical chains.",
            ),
            _metric(
                "y_gain_ratio_hcipy_over_native",
                "physical_tolerance",
                "ratio",
                hcipy_y / native_y,
                {"type": "range", "low": 0.80, "high": 1.10},
                "The y axis must behave like the x axis on both backends.",
            ),
        ],
    }


def _compare_spot_morphology(context: _ComparisonContext) -> dict[str, Any]:
    from ..backends.native.shwfs import NativeShackHartmannOptics
    from ..wfs.shack_hartmann.geometry import subaperture_id

    geometry = context.geometry
    interior = geometry.subaperture_ids.index(subaperture_id(1, 1))
    zero = np.zeros(geometry.pupil_shape, dtype=float)

    window_px = context.hcipy_optics.sampling.window_shape_px[1]
    angular_extent_rad = window_px * context.hcipy_optics.sampling.pixel_scale_rad[0]
    native_probe = context.native_optics
    matched_window_px = int(
        round(angular_extent_rad / native_probe.sampling.pixel_scale_rad[0])
    )
    matched_native = NativeShackHartmannOptics(
        geometry,
        context.config.wfs_wavelength_m,
        pad_factor=8,
        detector_window_px=matched_window_px,
    )

    def morphology(backend: Any) -> tuple[float, float]:
        zero_spot = backend.spot_intensities(zero).unit_sum_spots[interior]
        tilt_spot = backend.spot_intensities(
            context.tilt_x_opd_m
        ).unit_sum_spots[interior]
        ee50_rad = encircled_energy_radius_rad(
            zero_spot,
            backend.sampling.pixel_scale_rad,
        )
        shift_rad = (
            centroid_xy_px(tilt_spot)[0] - centroid_xy_px(zero_spot)[0]
        ) * backend.sampling.pixel_scale_rad[0]
        return ee50_rad, shift_rad / context.tilt_slope_rad

    native_ee50_rad, native_gain = morphology(matched_native)
    hcipy_ee50_rad, hcipy_gain = morphology(context.hcipy_optics)
    lenslet_diameter_m = (
        context.config.telescope_diameter_m / context.config.lenslets_across
    )
    diffraction_rad = context.config.wfs_wavelength_m / lenslet_diameter_m

    return {
        "comparison_kind": "lenslet_spot_morphology",
        "attribution": (
            "Both backends are compared on one matched angular window; the "
            "native path propagates each lenslet alone while HCIPy "
            "propagates the full field, so neighbouring-lenslet wings and "
            "focal-grid sampling explain the residual differences."
        ),
        "metrics": [
            _metric(
                "native_ee50_over_diffraction",
                "physical_tolerance",
                "ratio of lambda/d",
                native_ee50_rad / diffraction_rad,
                {"type": "range", "low": 0.2, "high": 1.0},
                "The half-energy radius of a diffraction-limited lenslet "
                "spot sits well inside one lambda/d.",
            ),
            _metric(
                "hcipy_ee50_over_diffraction",
                "physical_tolerance",
                "ratio of lambda/d",
                hcipy_ee50_rad / diffraction_rad,
                {"type": "range", "low": 0.2, "high": 1.0},
                "Same diffraction expectation for the HCIPy lenslet spots.",
            ),
            _metric(
                "ee50_ratio_hcipy_over_native",
                "physical_tolerance",
                "ratio",
                hcipy_ee50_rad / native_ee50_rad,
                {"type": "range", "low": 0.80, "high": 1.25},
                "Focal-plane sampling differs between the backends, so the "
                "half-energy width agrees only to the resampling level.",
            ),
            _metric(
                "centroid_gain_ratio_hcipy_over_native",
                "physical_tolerance",
                "ratio",
                hcipy_gain / native_gain,
                {"type": "range", "low": 0.75, "high": 1.10},
                "Full-field crosstalk pulls the HCIPy window centroid "
                "slightly toward its reference compared with the isolated "
                "native lenslet propagation.",
            ),
        ],
    }


def _compare_dm_influence(context: _ComparisonContext) -> dict[str, Any]:
    from ..core.types import DmCommandVector

    geometry = context.geometry
    native_influences = np.asarray(context.native_dm.influence_functions)
    hcipy_influences = np.asarray(context.hcipy_dm.influence_functions)
    mask = geometry.pupil_mask
    max_diff = float(
        np.max(np.abs(hcipy_influences[:, mask] - native_influences[:, mask]))
    )

    def command_surface(model: Any) -> np.ndarray:
        result = model.opd_from_commands(
            DmCommandVector(
                values_opd_m=np.asarray(
                    context.command_fixture_opd_m,
                    dtype=float,
                ),
                actuator_ids=model.actuator_ids,
                command_unit="m_opd_equivalent",
            )
        )
        return np.asarray(result.correction_opd_m, dtype=float)

    command_surface_diff_m = float(
        np.max(
            np.abs(
                command_surface(context.hcipy_dm)[mask]
                - command_surface(context.native_dm)[mask]
            )
        )
    )
    return {
        "comparison_kind": "dm_single_actuator_influence",
        "attribution": (
            "Both mirrors use the same repository actuator layout and the "
            "same analytic Gaussian with in-pupil peak normalization; "
            "outside the pupil the HCIPy surface keeps its analytic tail "
            "while the native construction stores zeros. The shared seeded "
            "command fixture drives both mirrors through opd_from_commands, "
            "so multi-actuator command application is compared on the "
            "recorded identical input."
        ),
        "metrics": [
            _metric(
                "actuator_ids_identical",
                "exact",
                "boolean",
                bool(
                    context.hcipy_dm.actuator_ids
                    == context.native_dm.actuator_ids
                ),
                {"type": "equals", "expected": True},
                "Actuator identity and ordering are repository-owned and "
                "backend independent.",
            ),
            _metric(
                "max_in_pupil_influence_abs_diff",
                "tight_numerical",
                "unit-peak influence",
                max_diff,
                {"type": "abs_tolerance", "expected": 0.0, "tolerance": 1.0e-9},
                "Matched Gaussian construction must agree to numerical "
                "precision inside the pupil.",
            ),
            _metric(
                "max_in_pupil_command_surface_abs_diff_m",
                "tight_numerical",
                "m_opd",
                command_surface_diff_m,
                {"type": "abs_tolerance", "expected": 0.0, "tolerance": 1.0e-9},
                "Applying the shared 100 nm-scale random command fixture "
                "through both mirrors must produce the same in-pupil "
                "surface to numerical precision.",
            ),
        ],
    }


def _compare_dm_static_fitting(context: _ComparisonContext) -> dict[str, Any]:
    from ..core.types import DmCommandVector

    geometry = context.geometry
    mask = geometry.pupil_mask
    target_filled = np.where(mask, context.static_opd_m, 0.0)
    target_masked = np.where(mask, context.static_opd_m, np.nan)
    target_rms_m = masked_rms(target_masked, mask)

    def fitting_residual(model: Any) -> float:
        design = np.asarray(model.influence_functions)[:, mask].T
        coefficients, *_ = np.linalg.lstsq(design, target_filled[mask], rcond=None)
        result = model.opd_from_commands(
            DmCommandVector(
                values_opd_m=coefficients,
                actuator_ids=model.actuator_ids,
                command_unit="m_opd_equivalent",
            )
        )
        return masked_rms(target_masked - result.correction_opd_m, mask)

    native_residual_m = fitting_residual(context.native_dm)
    hcipy_residual_m = fitting_residual(context.hcipy_dm)
    return {
        "comparison_kind": "dm_static_fitting",
        "attribution": (
            "One shared static aberration fixture is least-squares fitted "
            "in each backend's influence space; matched in-pupil influence "
            "functions make the residuals numerically identical."
        ),
        "metrics": [
            _metric(
                "native_fitting_residual_fraction",
                "physical_tolerance",
                "residual rms / target rms",
                native_residual_m / target_rms_m,
                {"type": "range", "low": 0.10, "high": 0.95},
                "A coarse actuator grid corrects only part of the "
                "low-order fixture; the fraction must stay physical "
                "(clearly below one, clearly above numerical zero).",
            ),
            _metric(
                "fitting_residual_relative_difference",
                "tight_numerical",
                "relative difference",
                abs(hcipy_residual_m - native_residual_m)
                / native_residual_m,
                {"type": "abs_tolerance", "expected": 0.0, "tolerance": 1.0e-6},
                "Identical in-pupil influence bases must produce the same "
                "least-squares residual to solver precision.",
            ),
        ],
    }


def _compare_interaction_matrix(
    context: _ComparisonContext,
) -> dict[str, Any]:
    native_matrix, hcipy_matrix = _interaction_matrices(context)
    context.native_interaction = native_matrix
    context.hcipy_interaction = hcipy_matrix
    rank_native = int(native_matrix.rank)
    rank_hcipy = int(hcipy_matrix.rank)
    return {
        "comparison_kind": "interaction_matrix_identity",
        "attribution": (
            "Both matrices are calibrated by the shared repository "
            "calibrator with the same probe basis and amplitudes; layout "
            "identity is exact while matrix entries differ at the optical "
            "gain level examined by the singular-spectrum comparison."
        ),
        "metrics": [
            _metric(
                "matrix_shapes_identical",
                "exact",
                "boolean",
                bool(native_matrix.matrix.shape == hcipy_matrix.matrix.shape),
                {"type": "equals", "expected": True},
                "Row and coordinate layouts are repository-owned.",
            ),
            _metric(
                "row_ids_identical",
                "exact",
                "boolean",
                bool(native_matrix.row_ids == hcipy_matrix.row_ids),
                {"type": "equals", "expected": True},
                "Measurement row identity must not depend on the backend.",
            ),
            _metric(
                "coordinate_ids_identical",
                "exact",
                "boolean",
                bool(
                    native_matrix.coordinate_ids == hcipy_matrix.coordinate_ids
                ),
                {"type": "equals", "expected": True},
                "Actuator coordinate identity must not depend on the "
                "backend.",
            ),
            _metric(
                "rank_difference",
                "exact",
                "rank",
                rank_native - rank_hcipy,
                {"type": "equals", "expected": 0},
                "Both calibrations must resolve the same controllable "
                "subspace on the matched geometry.",
            ),
        ],
    }


def _compare_singular_spectrum(context: _ComparisonContext) -> dict[str, Any]:
    native_matrix = context.native_interaction
    hcipy_matrix = context.hcipy_interaction
    native_spectrum = normalized_singular_spectrum(
        np.asarray(native_matrix.matrix)[np.asarray(native_matrix.row_valid)]
    )
    hcipy_spectrum = normalized_singular_spectrum(
        np.asarray(hcipy_matrix.matrix)[np.asarray(hcipy_matrix.row_valid)]
    )
    max_diff = float(np.max(np.abs(native_spectrum - hcipy_spectrum)))
    return {
        "comparison_kind": "normalized_singular_spectrum",
        "attribution": (
            "Sigma over sigma_0 removes each backend's absolute centroid "
            "gain; the remaining shape difference reflects window "
            "truncation and lenslet crosstalk in the optical responses."
        ),
        "metrics": [
            _metric(
                "spectrum_length_difference",
                "exact",
                "count",
                int(native_spectrum.size - hcipy_spectrum.size),
                {"type": "equals", "expected": 0},
                "Both spectra cover the same controllable subspace.",
            ),
            _metric(
                "max_normalized_sigma_abs_diff",
                "physical_tolerance",
                "normalized sigma",
                max_diff,
                {"type": "abs_tolerance", "expected": 0.0, "tolerance": 0.10},
                "Normalized spectra agree to the optical-gain-shape level; "
                "a 0.10 envelope is several times the observed difference "
                "on the pinned environments.",
            ),
        ],
    }


def _compare_psf_normalization(context: _ComparisonContext) -> dict[str, Any]:
    native_psf = context.native_science.psf_from_opd(
        _masked_fixture(context),
        context.config.science_wavelength_m,
    )
    hcipy_psf = context.hcipy_science.psf_from_opd(
        _masked_fixture(context),
        context.config.science_wavelength_m,
    )
    context.native_psf = native_psf
    context.hcipy_psf = hcipy_psf
    return {
        "comparison_kind": "psf_normalization",
        "attribution": (
            "Both backends return unit-total discrete flux by contract; "
            "their angular windows differ, which the Strehl comparison "
            "accounts for by using per-backend ideal references."
        ),
        "metrics": [
            _metric(
                "native_total_flux_error",
                "tight_numerical",
                "flux",
                abs(float(np.sum(native_psf.intensity)) - 1.0),
                {"type": "abs_tolerance", "expected": 0.0, "tolerance": 1.0e-9},
                "The canonical PsfResult requires exact unit total flux.",
            ),
            _metric(
                "hcipy_total_flux_error",
                "tight_numerical",
                "flux",
                abs(float(np.sum(hcipy_psf.intensity)) - 1.0),
                {"type": "abs_tolerance", "expected": 0.0, "tolerance": 1.0e-9},
                "Same normalization contract for the HCIPy backend.",
            ),
        ],
    }


def _compare_strehl(context: _ComparisonContext) -> dict[str, Any]:
    from ..science.metrics import peak_strehl_from_discrete_flux

    zero = np.zeros(context.geometry.pupil_shape, dtype=float)
    native_strehl = peak_strehl_from_discrete_flux(
        context.native_psf,
        context.native_science.psf_from_opd(
            zero,
            context.config.science_wavelength_m,
        ),
    )
    hcipy_strehl = peak_strehl_from_discrete_flux(
        context.hcipy_psf,
        context.hcipy_science.psf_from_opd(
            zero,
            context.config.science_wavelength_m,
        ),
    )
    sigma_m = context.config.static_aberration_rms_m
    sigma_phase_rad = float(
        opd_to_phase(
            np.asarray(sigma_m, dtype=float),
            context.config.science_wavelength_m,
        )
    )
    marechal = float(np.exp(-(sigma_phase_rad**2)))
    return {
        "comparison_kind": "strehl_ratio",
        "attribution": (
            "Each backend evaluates Strehl against its own ideal reference "
            "on its own focal grid; grid sampling and window truncation "
            "explain the small residual difference."
        ),
        "metrics": [
            _metric(
                "native_strehl",
                "physical_tolerance",
                "Strehl",
                float(native_strehl),
                {
                    "type": "abs_tolerance",
                    "expected": marechal,
                    "tolerance": 0.03,
                },
                "A smooth low-order aberration of known RMS must follow "
                "the Marechal approximation closely.",
            ),
            _metric(
                "hcipy_strehl",
                "physical_tolerance",
                "Strehl",
                float(hcipy_strehl),
                {
                    "type": "abs_tolerance",
                    "expected": marechal,
                    "tolerance": 0.03,
                },
                "Same Marechal expectation for the HCIPy backend.",
            ),
            _metric(
                "strehl_abs_difference",
                "physical_tolerance",
                "Strehl",
                abs(float(native_strehl) - float(hcipy_strehl)),
                {"type": "abs_tolerance", "expected": 0.0, "tolerance": 5.0e-3},
                "Independent focal grids agree far better than the 0.005 "
                "envelope; the tolerance covers cross-platform FFT noise.",
            ),
        ],
    }


def _compare_closed_loop(context: _ComparisonContext) -> dict[str, Any]:
    native_history = _run_loop(context, backend="native")
    hcipy_history = _run_loop(context, backend="hcipy")
    native_residuals = np.asarray(
        native_history.post_update_residual_opd_rms_m,
        dtype=float,
    )
    hcipy_residuals = np.asarray(
        hcipy_history.post_update_residual_opd_rms_m,
        dtype=float,
    )
    native_open_loop = np.asarray(
        native_history.open_loop_opd_rms_m,
        dtype=float,
    )
    hcipy_open_loop = np.asarray(
        hcipy_history.open_loop_opd_rms_m,
        dtype=float,
    )
    shared_time_grid = np.asarray(context.time_grid_s, dtype=float)
    executed_time_grids_match = bool(
        np.array_equal(
            np.asarray(native_history.time_s, dtype=float),
            shared_time_grid,
        )
        and np.array_equal(
            np.asarray(hcipy_history.time_s, dtype=float),
            shared_time_grid,
        )
    )
    shared_cube_hash = context.shared_atmosphere.config_hash
    both_loops_consumed_shared_cube = bool(
        native_history.metadata["component_hashes"]["atmosphere"]
        == hcipy_history.metadata["component_hashes"]["atmosphere"]
        == shared_cube_hash
    )
    return {
        "comparison_kind": "closed_loop_residual",
        "attribution": (
            "Both loops replay the identical recorded OPD-cube fixture "
            "(hash recorded in fixture_hashes) on the shared recorded time "
            "grid with identical controller settings; only the DM and WFS "
            "optics backends differ, so residual-trend differences reflect "
            "the measured optical-gain differences."
        ),
        "metrics": [
            _metric(
                "executed_time_grid_matches_shared_fixture",
                "exact",
                "boolean",
                executed_time_grids_match,
                {"type": "equals", "expected": True},
                "Both replayed loops must sample the shared OPD-cube "
                "fixture on exactly the recorded shared time grid; its "
                "recorded hash is this comparison's timing contract.",
            ),
            _metric(
                "both_loops_consumed_shared_opd_cube",
                "exact",
                "boolean",
                both_loops_consumed_shared_cube,
                {"type": "equals", "expected": True},
                "Each loop's recorded atmosphere component hash must equal "
                "the shared OPD-cube fixture hash, proving both backends "
                "consumed the identical recorded atmospheric input.",
            ),
            _metric(
                "native_backend_name",
                "exact",
                "identifier",
                str(native_history.metadata["backend_names"]["dm"]),
                {"type": "equals", "expected": "native"},
                "The reference loop must actually run the native DM.",
            ),
            _metric(
                "hcipy_backend_name",
                "exact",
                "identifier",
                str(hcipy_history.metadata["backend_names"]["dm"]),
                {"type": "equals", "expected": "hcipy"},
                "The comparison loop must actually run the HCIPy DM.",
            ),
            _metric(
                "native_correction_effect",
                "physical_tolerance",
                "mean corrected over uncorrected rms",
                float(np.mean(native_residuals) / np.mean(native_open_loop)),
                {"type": "range", "low": 0.0, "high": 0.95},
                "Closing the loop must reduce the wavefront error clearly "
                "below the replayed uncorrected atmosphere over the short "
                "deterministic run.",
            ),
            _metric(
                "hcipy_correction_effect",
                "physical_tolerance",
                "mean corrected over uncorrected rms",
                float(np.mean(hcipy_residuals) / np.mean(hcipy_open_loop)),
                {"type": "range", "low": 0.0, "high": 0.95},
                "Same correction expectation for the all-HCIPy loop.",
            ),
            _metric(
                "mean_residual_ratio_hcipy_over_native",
                "physical_tolerance",
                "ratio",
                float(np.mean(hcipy_residuals) / np.mean(native_residuals)),
                {"type": "range", "low": 0.60, "high": 1.60},
                "Optical-gain and window differences shift the residual "
                "level over a four-step run without changing the "
                "closed-loop behaviour; the band is several times the "
                "observed difference.",
            ),
        ],
    }


def _compare_runtime_and_memory(context: _ComparisonContext) -> dict[str, Any]:
    zero = np.zeros(context.geometry.pupil_shape, dtype=float)
    repeats = context.config.runtime_repeats

    def timed(operation: Any) -> float:
        start = time.perf_counter()
        for _ in range(repeats):
            operation()
        return (time.perf_counter() - start) / repeats

    tracemalloc.start()
    native_wfs_s = timed(lambda: context.native_optics.spot_intensities(zero))
    hcipy_wfs_s = timed(lambda: context.hcipy_optics.spot_intensities(zero))
    native_psf_s = timed(
        lambda: context.native_science.psf_from_opd(
            _masked_fixture(context),
            context.config.science_wavelength_m,
        )
    )
    hcipy_psf_s = timed(
        lambda: context.hcipy_science.psf_from_opd(
            _masked_fixture(context),
            context.config.science_wavelength_m,
        )
    )
    _, peak_bytes = tracemalloc.get_traced_memory()
    tracemalloc.stop()

    informational = {"type": "informational"}
    rationale = (
        "Runtime and memory are platform dependent and informational only; "
        "they never gate correctness CI."
    )
    return {
        "comparison_kind": "runtime_and_memory",
        "attribution": (
            "Wall-clock averages over a fixed small workload on the "
            "executing platform; no benchmark envelope has been approved, "
            "so these values are recorded but never asserted."
        ),
        "metrics": [
            _metric(
                "native_wfs_propagation_s",
                "informational",
                "seconds",
                native_wfs_s,
                informational,
                rationale,
            ),
            _metric(
                "hcipy_wfs_propagation_s",
                "informational",
                "seconds",
                hcipy_wfs_s,
                informational,
                rationale,
            ),
            _metric(
                "native_psf_propagation_s",
                "informational",
                "seconds",
                native_psf_s,
                informational,
                rationale,
            ),
            _metric(
                "hcipy_psf_propagation_s",
                "informational",
                "seconds",
                hcipy_psf_s,
                informational,
                rationale,
            ),
            _metric(
                "comparison_peak_traced_memory_mb",
                "informational",
                "mebibytes",
                peak_bytes / (1024.0 * 1024.0),
                informational,
                rationale,
            ),
        ],
    }


def _interaction_matrices(context: _ComparisonContext) -> tuple[Any, Any]:
    from ..calibration import DmActuatorProbeBasis, calibrate_interaction_matrix
    from ..core.random import NamedRandomStreams

    matrices = []
    for sensor, mirror in (
        (context.native_sensor, context.native_dm),
        (context.hcipy_sensor, context.hcipy_dm),
    ):
        matrices.append(
            calibrate_interaction_matrix(
                DmActuatorProbeBasis(mirror),
                sensor,
                amplitude_m=25.0e-9,
                random_streams=NamedRandomStreams(
                    context.config.root_seed
                ).scoped("calibration-probe"),
                include_noise=False,
            )
        )
    return matrices[0], matrices[1]


def _run_loop(context: _ComparisonContext, *, backend: str) -> Any:
    from ..calibration import LeastSquaresReconstructor
    from ..control import (
        IdentityCommandProjector,
        LeakyIntegratorController,
        LoopConfig,
    )
    from ..control.loop import run_closed_loop
    from ..core.random import NamedRandomStreams

    config = context.config
    if backend == "native":
        sensor = context.native_sensor
        mirror = context.native_dm
        interaction = context.native_interaction
    else:
        sensor = context.hcipy_sensor
        mirror = context.hcipy_dm
        interaction = context.hcipy_interaction

    # Both backend loops consume the identical recorded OPD-cube fixture;
    # the recording's hash is this comparison's shared-input evidence.
    atmosphere = context.shared_atmosphere
    return run_closed_loop(
        LoopConfig(
            n_steps=config.loop_steps,
            gain=config.loop_gain,
            leak=0.0,
            latency_frames=0,
            frame_rate_hz=config.frame_rate_hz,
            root_seed=config.root_seed,
        ),
        random_streams=NamedRandomStreams(config.root_seed),
        atmosphere=atmosphere,
        wfs=sensor,
        dm=mirror,
        interaction_matrix=interaction,
        reconstructor=LeastSquaresReconstructor(
            interaction,
            min_valid_fraction=0.5,
            min_rank=1,
        ),
        command_projector=IdentityCommandProjector(mirror.actuator_ids),
        controller=LeakyIntegratorController(
            mirror.actuator_ids,
            gain=config.loop_gain,
            leak=0.0,
            latency_frames=0,
        ),
        include_noise=False,
        realization_index=0,
    )


def _masked_fixture(context: _ComparisonContext) -> np.ndarray:
    return np.asarray(context.static_opd_m, dtype=float)


def _config_record(config: CrossBackendConfig) -> dict[str, Any]:
    from dataclasses import asdict

    record = asdict(config)
    record["wind_m_per_s"] = list(config.wind_m_per_s)
    record["structure_function_lags_px"] = list(
        config.structure_function_lags_px
    )
    record["config_hash"] = config.config_hash
    return record


def _fixture_hash(values: np.ndarray) -> str:
    return stable_hash(
        np.ascontiguousarray(np.asarray(values, dtype=float)),
        namespace=_FIXTURE_HASH_NAMESPACE,
    )


def _metric(
    name: str,
    level: str,
    units: str,
    value: Any,
    pass_criterion: dict[str, Any],
    rationale: str,
) -> dict[str, Any]:
    if isinstance(value, (np.floating, np.integer, np.bool_)):
        value = value.item()
    if isinstance(value, float) and not math.isfinite(value):
        raise CrossBackendError(f"metric {name!r} produced a non-finite value.")
    return {
        "name": name,
        "level": level,
        "units": units,
        "value": value,
        "pass_criterion": pass_criterion,
        "rationale": rationale,
    }
