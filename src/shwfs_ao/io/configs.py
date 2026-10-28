"""Versioned, package-installed SCAO system profiles.

The profile loader is deliberately narrow. It reads reviewed JSON records from
the canonical ``shwfs_ao.resources`` package and converts them to immutable,
SI-valued configuration objects. The deprecated ``ao_simulation_data`` tree is
only a build-generated installed alias.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
import json
import math
from numbers import Integral, Real
import re
from types import MappingProxyType
from typing import Any, Literal, cast

from ..core.hashing import component_config_hash
from ..core.provenance import Provenance
from ..core.random import DERIVATION_SCHEME_ID
from .resources import read_text_resource


PROFILE_SCHEMA_NAME = "shwfs_ao.system_profile"
PROFILE_SCHEMA_VERSION = 1
_PROFILE_NAME = re.compile(r"^[a-z][a-z0-9_]*$")
_PROFILE_RESOURCES: dict[tuple[str, int], str] = {
    ("fast_2m_detector", 1): "synthetic_presets/fast_2m_detector.v1.json",
    ("portfolio_2m_detector", 1): "synthetic_presets/portfolio_2m_detector.v1.json",
    ("research_2m_detector", 1): "synthetic_presets/research_2m_detector.v1.json",
    ("high_order_10m_geometric", 1): "synthetic_presets/high_order_10m_geometric.v1.json",
}

BackendName = Literal["native", "hcipy"]
WfsModel = Literal["geometric", "detector_level"]
AtmosphereModelName = Literal["static", "native_frozen_flow", "hcipy"]


class SystemConfigError(ValueError):
    """Raised when a serialized SCAO profile is malformed or unsupported."""


@dataclass(frozen=True, slots=True)
class ProfileProvenance:
    profile_name: str
    profile_version: int
    baseline_rationale: str
    provenance: Provenance

    def __post_init__(self) -> None:
        name = _profile_name(self.profile_name)
        version = _integer(self.profile_version, "profile_version", minimum=1)
        rationale = _text(self.baseline_rationale, "baseline_rationale")
        if not isinstance(self.provenance, Provenance):
            raise SystemConfigError("provenance must be a Provenance record.")
        expected_source_id = f"shwfs_ao.system_profile.{name}.v{version}"
        if self.provenance.source_id != expected_source_id:
            raise SystemConfigError(
                "profile provenance source_id must be " f"{expected_source_id!r}."
            )
        object.__setattr__(self, "profile_name", name)
        object.__setattr__(self, "profile_version", version)
        object.__setattr__(self, "baseline_rationale", rationale)

    @property
    def profile_id(self) -> str:
        return f"{self.profile_name}@{self.profile_version}"

    @property
    def config_hash(self) -> str:
        return component_config_hash("scao.profile_provenance", self)


@dataclass(frozen=True, slots=True)
class AtmosphereConfig:
    r0_m: float
    r0_reference_wavelength_m: float
    outer_scale_m: float | None
    wind_m_per_s: tuple[float, float]
    target_rms_opd_m: float | None
    normalize_rms: bool

    def __post_init__(self) -> None:
        object.__setattr__(self, "r0_m", _positive(self.r0_m, "r0_m"))
        object.__setattr__(
            self,
            "r0_reference_wavelength_m",
            _positive(
                self.r0_reference_wavelength_m,
                "r0_reference_wavelength_m",
            ),
        )
        object.__setattr__(
            self,
            "outer_scale_m",
            _optional_positive(self.outer_scale_m, "outer_scale_m"),
        )
        object.__setattr__(
            self,
            "wind_m_per_s",
            _pair(self.wind_m_per_s, "wind_m_per_s"),
        )
        object.__setattr__(
            self,
            "target_rms_opd_m",
            _optional_positive(self.target_rms_opd_m, "target_rms_opd_m"),
        )
        object.__setattr__(self, "normalize_rms", _boolean(self.normalize_rms, "normalize_rms"))

    @property
    def config_hash(self) -> str:
        return component_config_hash("scao.atmosphere_config", self)


@dataclass(frozen=True, slots=True)
class DetectorSystemConfig:
    enabled: bool
    photons_per_subap_frame: float | None
    read_noise_e: float
    dark_e_per_s: float
    background_e_per_pixel_frame: float
    full_well_e: float | None
    qe: float
    prnu_rms: float
    exposure_s: float
    prnu_mode: Literal["per_frame_legacy", "persistent"]
    bad_pixel_fraction: float

    def __post_init__(self) -> None:
        enabled = _boolean(self.enabled, "enabled")
        photons = _optional_nonnegative(
            self.photons_per_subap_frame, "photons_per_subap_frame"
        )
        if enabled and photons is None:
            raise SystemConfigError(
                "enabled detector profiles require photons_per_subap_frame."
            )
        object.__setattr__(self, "enabled", enabled)
        object.__setattr__(self, "photons_per_subap_frame", photons)
        for name in (
            "read_noise_e",
            "dark_e_per_s",
            "background_e_per_pixel_frame",
            "prnu_rms",
            "bad_pixel_fraction",
        ):
            object.__setattr__(self, name, _nonnegative(getattr(self, name), name))
        object.__setattr__(self, "full_well_e", _optional_positive(self.full_well_e, "full_well_e"))
        object.__setattr__(self, "qe", _positive(self.qe, "qe"))
        object.__setattr__(self, "exposure_s", _positive(self.exposure_s, "exposure_s"))
        if self.prnu_mode not in {"per_frame_legacy", "persistent"}:
            raise SystemConfigError(
                "prnu_mode must be 'per_frame_legacy' or 'persistent'."
            )
        if self.bad_pixel_fraction > 1.0:
            raise SystemConfigError("bad_pixel_fraction must be at most 1.")

    @property
    def config_hash(self) -> str:
        return component_config_hash("scao.detector_config", self)


@dataclass(frozen=True, slots=True)
class WfsConfig:
    min_fill_fraction: float
    pad_factor: int | None
    detector_window_px: int | None
    centroid_estimator: Literal[
        "center_of_gravity", "thresholded_center_of_gravity"
    ]
    threshold_fraction: float
    subtract_minimum: bool
    min_flux_e: float
    min_peak_snr: float
    max_centroid_sigma_px: float
    max_window_clipping_fraction: float
    central_obstruction_ratio: float
    spider_width_m: float

    def __post_init__(self) -> None:
        fill = _fraction(self.min_fill_fraction, "min_fill_fraction")
        pad = _optional_integer(self.pad_factor, "pad_factor", minimum=1)
        window = _optional_integer(
            self.detector_window_px, "detector_window_px", minimum=1
        )
        if self.centroid_estimator not in {
            "center_of_gravity",
            "thresholded_center_of_gravity",
        }:
            raise SystemConfigError("unsupported centroid_estimator.")
        threshold = _nonnegative(self.threshold_fraction, "threshold_fraction")
        if self.centroid_estimator == "center_of_gravity" and threshold != 0.0:
            raise SystemConfigError(
                "center_of_gravity requires threshold_fraction=0."
            )
        clipping = _fraction(
            self.max_window_clipping_fraction,
            "max_window_clipping_fraction",
        )
        obstruction = _fraction(
            self.central_obstruction_ratio, "central_obstruction_ratio"
        )
        if obstruction >= 1.0:
            raise SystemConfigError("central_obstruction_ratio must be less than 1.")
        object.__setattr__(self, "min_fill_fraction", fill)
        object.__setattr__(self, "pad_factor", pad)
        object.__setattr__(self, "detector_window_px", window)
        object.__setattr__(self, "threshold_fraction", threshold)
        object.__setattr__(self, "subtract_minimum", _boolean(self.subtract_minimum, "subtract_minimum"))
        for name in ("min_flux_e", "min_peak_snr", "max_centroid_sigma_px"):
            object.__setattr__(self, name, _nonnegative(getattr(self, name), name))
        object.__setattr__(self, "max_window_clipping_fraction", clipping)
        object.__setattr__(self, "central_obstruction_ratio", obstruction)
        object.__setattr__(self, "spider_width_m", _nonnegative(self.spider_width_m, "spider_width_m"))

    @property
    def config_hash(self) -> str:
        return component_config_hash("scao.wfs_config", self)


@dataclass(frozen=True, slots=True)
class DmSystemConfig:
    influence_model: Literal["gaussian", "compact_gaussian", "pyramid_like"]
    coupling_width_pitch: float
    stroke_limit_opd_m: float
    include_edge_actuators: bool
    actuator_margin_fraction: float
    dead_actuator_indices: tuple[int, ...]
    stuck_actuator_indices: tuple[int, ...]
    stuck_command_opd_m: float

    def __post_init__(self) -> None:
        if self.influence_model not in {"gaussian", "compact_gaussian", "pyramid_like"}:
            raise SystemConfigError("unsupported influence_model.")
        object.__setattr__(self, "coupling_width_pitch", _positive(self.coupling_width_pitch, "coupling_width_pitch"))
        stroke = _positive(self.stroke_limit_opd_m, "stroke_limit_opd_m")
        object.__setattr__(self, "stroke_limit_opd_m", stroke)
        object.__setattr__(self, "include_edge_actuators", _boolean(self.include_edge_actuators, "include_edge_actuators"))
        object.__setattr__(self, "actuator_margin_fraction", _nonnegative(self.actuator_margin_fraction, "actuator_margin_fraction"))
        dead = _indices(self.dead_actuator_indices, "dead_actuator_indices")
        stuck = _indices(self.stuck_actuator_indices, "stuck_actuator_indices")
        if set(dead) & set(stuck):
            raise SystemConfigError("dead and stuck actuator indices must be disjoint.")
        stuck_value = _finite(self.stuck_command_opd_m, "stuck_command_opd_m")
        if abs(stuck_value) > stroke:
            raise SystemConfigError("stuck_command_opd_m must be within the stroke limit.")
        object.__setattr__(self, "dead_actuator_indices", dead)
        object.__setattr__(self, "stuck_actuator_indices", stuck)
        object.__setattr__(self, "stuck_command_opd_m", stuck_value)

    @property
    def config_hash(self) -> str:
        return component_config_hash("scao.dm_config", self)


@dataclass(frozen=True, slots=True)
class CalibrationConfig:
    source: Literal["build", "resource", "supplied"]
    method: Literal["central", "forward"]
    probe_kind: Literal["dm_actuator", "modal"]
    amplitude_m: float
    include_noise: bool
    repeats: int
    resource_name: str | None

    def __post_init__(self) -> None:
        if self.source not in {"build", "resource", "supplied"}:
            raise SystemConfigError("calibration source must be build/resource/supplied.")
        if self.method not in {"central", "forward"}:
            raise SystemConfigError("calibration method must be central or forward.")
        if self.probe_kind not in {"dm_actuator", "modal"}:
            raise SystemConfigError("probe_kind must be dm_actuator or modal.")
        object.__setattr__(self, "amplitude_m", _positive(self.amplitude_m, "amplitude_m"))
        noisy = _boolean(self.include_noise, "include_noise")
        repeats = _integer(self.repeats, "repeats", minimum=1)
        if noisy and repeats < 2:
            raise SystemConfigError("noisy calibration requires repeats >= 2.")
        if not noisy and repeats != 1:
            raise SystemConfigError("noise-free calibration requires repeats=1.")
        resource_name = _optional_text(self.resource_name, "resource_name")
        if self.source == "resource" and resource_name is None:
            raise SystemConfigError("resource calibration requires resource_name.")
        if self.source != "resource" and resource_name is not None:
            raise SystemConfigError("resource_name is valid only for source='resource'.")
        object.__setattr__(self, "include_noise", noisy)
        object.__setattr__(self, "repeats", repeats)
        object.__setattr__(self, "resource_name", resource_name)

    @property
    def config_hash(self) -> str:
        return component_config_hash("scao.calibration_config", self)


@dataclass(frozen=True, slots=True)
class ReconstructorConfig:
    kind: Literal["least_squares", "tsvd", "tikhonov"]
    rcond: float | None
    alpha: float | None
    min_valid_fraction: float
    min_rank: int
    max_cached_masks: int

    def __post_init__(self) -> None:
        if self.kind not in {"least_squares", "tsvd", "tikhonov"}:
            raise SystemConfigError("unsupported reconstructor kind.")
        rcond = _optional_positive(self.rcond, "rcond")
        alpha = _optional_nonnegative(self.alpha, "alpha")
        if self.kind == "tsvd" and rcond is None:
            raise SystemConfigError("tsvd requires rcond.")
        if self.kind != "tsvd" and rcond is not None:
            raise SystemConfigError("rcond is valid only for tsvd.")
        if self.kind == "tikhonov" and alpha is None:
            raise SystemConfigError("tikhonov requires alpha.")
        if self.kind != "tikhonov" and alpha is not None:
            raise SystemConfigError("alpha is valid only for tikhonov.")
        object.__setattr__(self, "rcond", rcond)
        object.__setattr__(self, "alpha", alpha)
        object.__setattr__(self, "min_valid_fraction", _fraction(self.min_valid_fraction, "min_valid_fraction"))
        object.__setattr__(self, "min_rank", _integer(self.min_rank, "min_rank", minimum=1))
        object.__setattr__(self, "max_cached_masks", _integer(self.max_cached_masks, "max_cached_masks", minimum=0))

    @property
    def config_hash(self) -> str:
        return component_config_hash("scao.reconstructor_config", self)


@dataclass(frozen=True, slots=True)
class CommandProjectorConfig:
    kind: Literal["identity", "controlled_subset", "modal"]
    mapping_resource: str | None

    def __post_init__(self) -> None:
        if self.kind not in {"identity", "controlled_subset", "modal"}:
            raise SystemConfigError("unsupported command-projector kind.")
        resource_name = _optional_text(self.mapping_resource, "mapping_resource")
        if self.kind == "modal" and resource_name is None:
            raise SystemConfigError("modal projector requires mapping_resource.")
        if self.kind != "modal" and resource_name is not None:
            raise SystemConfigError("mapping_resource is valid only for modal projectors.")
        object.__setattr__(self, "mapping_resource", resource_name)

    @property
    def config_hash(self) -> str:
        return component_config_hash("scao.command_projector_config", self)


@dataclass(frozen=True, slots=True)
class ControllerConfig:
    n_steps: int
    gain: float
    leak: float
    latency_frames: int
    frame_rate_hz: float
    include_noise: bool

    def __post_init__(self) -> None:
        object.__setattr__(self, "n_steps", _integer(self.n_steps, "n_steps", minimum=1))
        object.__setattr__(self, "gain", _nonnegative(self.gain, "gain"))
        leak = _fraction(self.leak, "leak")
        if leak >= 1.0:
            raise SystemConfigError("leak must be less than 1.")
        object.__setattr__(self, "leak", leak)
        object.__setattr__(self, "latency_frames", _integer(self.latency_frames, "latency_frames", minimum=0))
        object.__setattr__(self, "frame_rate_hz", _positive(self.frame_rate_hz, "frame_rate_hz"))
        object.__setattr__(self, "include_noise", _boolean(self.include_noise, "include_noise"))

    @property
    def config_hash(self) -> str:
        return component_config_hash("scao.controller_config", self)


@dataclass(frozen=True, slots=True)
class ScienceConfig:
    psf_pad_factor: int

    def __post_init__(self) -> None:
        object.__setattr__(self, "psf_pad_factor", _integer(self.psf_pad_factor, "psf_pad_factor", minimum=1))

    @property
    def config_hash(self) -> str:
        return component_config_hash("scao.science_config", self)


@dataclass(frozen=True, slots=True)
class RandomSeedConfig:
    root_seed: int
    derivation_scheme_id: str = DERIVATION_SCHEME_ID

    def __post_init__(self) -> None:
        object.__setattr__(self, "root_seed", _integer(self.root_seed, "root_seed", minimum=0))
        scheme = _text(self.derivation_scheme_id, "derivation_scheme_id")
        if scheme != DERIVATION_SCHEME_ID:
            raise SystemConfigError(
                f"derivation_scheme_id must be {DERIVATION_SCHEME_ID!r}."
            )
        object.__setattr__(self, "derivation_scheme_id", scheme)

    @property
    def config_hash(self) -> str:
        return component_config_hash("scao.random_seed_config", self)


@dataclass(frozen=True, slots=True)
class SystemConfig:
    backend: BackendName
    wfs_model: WfsModel
    atmosphere_model: AtmosphereModelName
    telescope_diameter_m: float
    pupil_pixels: int
    lenslets_across: int
    actuators_across: int
    wfs_wavelength_m: float
    science_wavelengths_m: tuple[float, ...]
    atmosphere: AtmosphereConfig
    detector: DetectorSystemConfig
    wfs: WfsConfig
    dm: DmSystemConfig
    calibration: CalibrationConfig
    reconstructor: ReconstructorConfig
    command_projector: CommandProjectorConfig
    controller: ControllerConfig
    science: ScienceConfig
    random: RandomSeedConfig
    profile: ProfileProvenance

    def __post_init__(self) -> None:
        if self.backend not in {"native", "hcipy"}:
            raise SystemConfigError("backend must be native or hcipy.")
        if self.wfs_model not in {"geometric", "detector_level"}:
            raise SystemConfigError("wfs_model must be geometric or detector_level.")
        if self.atmosphere_model not in {"static", "native_frozen_flow", "hcipy"}:
            raise SystemConfigError("unsupported atmosphere_model.")
        object.__setattr__(self, "telescope_diameter_m", _positive(self.telescope_diameter_m, "telescope_diameter_m"))
        for name in ("pupil_pixels", "lenslets_across", "actuators_across"):
            object.__setattr__(self, name, _integer(getattr(self, name), name, minimum=2))
        object.__setattr__(self, "wfs_wavelength_m", _positive(self.wfs_wavelength_m, "wfs_wavelength_m"))
        wavelengths = _positive_tuple(self.science_wavelengths_m, "science_wavelengths_m")
        if tuple(sorted(wavelengths)) != wavelengths or len(set(wavelengths)) != len(wavelengths):
            raise SystemConfigError("science_wavelengths_m must be strictly increasing.")
        object.__setattr__(self, "science_wavelengths_m", wavelengths)
        expected = (
            (self.atmosphere, AtmosphereConfig, "atmosphere"),
            (self.detector, DetectorSystemConfig, "detector"),
            (self.wfs, WfsConfig, "wfs"),
            (self.dm, DmSystemConfig, "dm"),
            (self.calibration, CalibrationConfig, "calibration"),
            (self.reconstructor, ReconstructorConfig, "reconstructor"),
            (self.command_projector, CommandProjectorConfig, "command_projector"),
            (self.controller, ControllerConfig, "controller"),
            (self.science, ScienceConfig, "science"),
            (self.random, RandomSeedConfig, "random"),
            (self.profile, ProfileProvenance, "profile"),
        )
        for value, value_type, label in expected:
            if not isinstance(value, value_type):
                raise SystemConfigError(f"{label} has the wrong configuration type.")
        if self.wfs_model == "detector_level":
            if not self.detector.enabled or self.wfs.pad_factor is None or self.wfs.detector_window_px is None:
                raise SystemConfigError("detector_level requires enabled detector and explicit pad/window sampling.")
        elif self.detector.enabled or self.wfs.pad_factor is not None or self.wfs.detector_window_px is not None:
            raise SystemConfigError("geometric WFS requires disabled detector and null pad/window sampling.")
        if self.calibration.probe_kind == "modal" and self.command_projector.kind != "modal":
            raise SystemConfigError("modal calibration requires a modal command projector.")
        if self.calibration.probe_kind == "dm_actuator" and self.command_projector.kind == "modal":
            raise SystemConfigError("DM-actuator calibration cannot use a modal projector.")

    @property
    def config_hash(self) -> str:
        return component_config_hash("scao.system_config", system_config_to_mapping(self))

    @property
    def observing_conditions_hash(self) -> str:
        return component_config_hash(
            "scao.observing_conditions",
            {
                "telescope_diameter_m": self.telescope_diameter_m,
                "wfs_wavelength_m": self.wfs_wavelength_m,
                "science_wavelengths_m": self.science_wavelengths_m,
                "atmosphere_model": self.atmosphere_model,
                "atmosphere": self.atmosphere,
                "detector": self.detector,
            },
        )

    @property
    def component_config_hashes(self) -> Mapping[str, str]:
        return MappingProxyType(
            {
                "profile": self.profile.config_hash,
                "atmosphere": self.atmosphere.config_hash,
                "detector": self.detector.config_hash,
                "wfs": self.wfs.config_hash,
                "dm": self.dm.config_hash,
                "calibration": self.calibration.config_hash,
                "reconstructor": self.reconstructor.config_hash,
                "command_projector": self.command_projector.config_hash,
                "controller": self.controller.config_hash,
                "science": self.science.config_hash,
                "random": self.random.config_hash,
            }
        )


def available_system_profiles() -> tuple[tuple[str, int], ...]:
    """Return every installed profile as an explicit ``(name, version)`` key."""

    return tuple(_PROFILE_RESOURCES)


def load_system_profile(name: str, version: int) -> SystemConfig:
    """Load one exact installed profile; no implicit latest version exists."""

    key = (_profile_name(name), _integer(version, "version", minimum=1))
    try:
        logical_name = _PROFILE_RESOURCES[key]
    except KeyError as exc:
        raise SystemConfigError(
            f"unknown system profile {key!r}; available={available_system_profiles()!r}."
        ) from exc
    try:
        payload = read_text_resource(logical_name)
        record = json.loads(
            payload,
            object_pairs_hook=_unique_object,
            parse_constant=_invalid_json_constant,
        )
    except (OSError, json.JSONDecodeError, TypeError, ValueError) as exc:
        if isinstance(exc, SystemConfigError):
            raise
        raise SystemConfigError(f"cannot load system profile {key!r}: {exc}") from exc
    config = system_config_from_mapping(_mapping(record, "profile record"))
    if (config.profile.profile_name, config.profile.profile_version) != key:
        raise SystemConfigError("profile resource identity does not match the requested key.")
    return config


def system_config_from_mapping(record: Mapping[str, object]) -> SystemConfig:
    """Parse one strict profile-schema-v1 mapping into :class:`SystemConfig`."""

    root = _mapping(record, "profile record")
    _keys(
        root,
        {
            "schema_name",
            "schema_version",
            "profile_name",
            "profile_version",
            "baseline_rationale",
            "provenance",
            "config",
        },
        "profile record",
    )
    if root["schema_name"] != PROFILE_SCHEMA_NAME:
        raise SystemConfigError(f"schema_name must be {PROFILE_SCHEMA_NAME!r}.")
    if _integer(root["schema_version"], "schema_version", minimum=1) != PROFILE_SCHEMA_VERSION:
        raise SystemConfigError(f"unsupported profile schema_version={root['schema_version']!r}.")
    profile = ProfileProvenance(
        profile_name=cast(str, root["profile_name"]),
        profile_version=cast(int, root["profile_version"]),
        baseline_rationale=cast(str, root["baseline_rationale"]),
        provenance=_provenance(root["provenance"]),
    )
    values = _mapping(root["config"], "config")
    _keys(values, _SYSTEM_FIELDS, "config")
    return SystemConfig(
        backend=cast(BackendName, values["backend"]),
        wfs_model=cast(WfsModel, values["wfs_model"]),
        atmosphere_model=cast(AtmosphereModelName, values["atmosphere_model"]),
        telescope_diameter_m=cast(float, values["telescope_diameter_m"]),
        pupil_pixels=cast(int, values["pupil_pixels"]),
        lenslets_across=cast(int, values["lenslets_across"]),
        actuators_across=cast(int, values["actuators_across"]),
        wfs_wavelength_m=cast(float, values["wfs_wavelength_m"]),
        science_wavelengths_m=_tuple_value(values["science_wavelengths_m"], "science_wavelengths_m"),
        atmosphere=_construct(AtmosphereConfig, values["atmosphere"], _ATMOSPHERE_FIELDS, "atmosphere", tuple_fields={"wind_m_per_s"}),
        detector=_construct(DetectorSystemConfig, values["detector"], _DETECTOR_FIELDS, "detector"),
        wfs=_construct(WfsConfig, values["wfs"], _WFS_FIELDS, "wfs"),
        dm=_construct(DmSystemConfig, values["dm"], _DM_FIELDS, "dm", tuple_fields={"dead_actuator_indices", "stuck_actuator_indices"}),
        calibration=_construct(CalibrationConfig, values["calibration"], _CALIBRATION_FIELDS, "calibration"),
        reconstructor=_construct(ReconstructorConfig, values["reconstructor"], _RECONSTRUCTOR_FIELDS, "reconstructor"),
        command_projector=_construct(CommandProjectorConfig, values["command_projector"], _PROJECTOR_FIELDS, "command_projector"),
        controller=_construct(ControllerConfig, values["controller"], _CONTROLLER_FIELDS, "controller"),
        science=_construct(ScienceConfig, values["science"], _SCIENCE_FIELDS, "science"),
        random=_construct(RandomSeedConfig, values["random"], _RANDOM_FIELDS, "random"),
        profile=profile,
    )


def system_config_to_mapping(config: SystemConfig) -> dict[str, object]:
    """Serialize a system config to the deterministic profile-schema-v1 model."""

    if not isinstance(config, SystemConfig):
        raise SystemConfigError("config must be a SystemConfig.")
    profile = config.profile
    return {
        "schema_name": PROFILE_SCHEMA_NAME,
        "schema_version": PROFILE_SCHEMA_VERSION,
        "profile_name": profile.profile_name,
        "profile_version": profile.profile_version,
        "baseline_rationale": profile.baseline_rationale,
        "provenance": profile.provenance.to_record(),
        "config": {
            "backend": config.backend,
            "wfs_model": config.wfs_model,
            "atmosphere_model": config.atmosphere_model,
            "telescope_diameter_m": config.telescope_diameter_m,
            "pupil_pixels": config.pupil_pixels,
            "lenslets_across": config.lenslets_across,
            "actuators_across": config.actuators_across,
            "wfs_wavelength_m": config.wfs_wavelength_m,
            "science_wavelengths_m": list(config.science_wavelengths_m),
            "atmosphere": _dataclass_mapping(config.atmosphere),
            "detector": _dataclass_mapping(config.detector),
            "wfs": _dataclass_mapping(config.wfs),
            "dm": _dataclass_mapping(config.dm),
            "calibration": _dataclass_mapping(config.calibration),
            "reconstructor": _dataclass_mapping(config.reconstructor),
            "command_projector": _dataclass_mapping(config.command_projector),
            "controller": _dataclass_mapping(config.controller),
            "science": _dataclass_mapping(config.science),
            "random": _dataclass_mapping(config.random),
        },
    }


_SYSTEM_FIELDS = {"backend", "wfs_model", "atmosphere_model", "telescope_diameter_m", "pupil_pixels", "lenslets_across", "actuators_across", "wfs_wavelength_m", "science_wavelengths_m", "atmosphere", "detector", "wfs", "dm", "calibration", "reconstructor", "command_projector", "controller", "science", "random"}
_ATMOSPHERE_FIELDS = {"r0_m", "r0_reference_wavelength_m", "outer_scale_m", "wind_m_per_s", "target_rms_opd_m", "normalize_rms"}
_DETECTOR_FIELDS = {"enabled", "photons_per_subap_frame", "read_noise_e", "dark_e_per_s", "background_e_per_pixel_frame", "full_well_e", "qe", "prnu_rms", "exposure_s", "prnu_mode", "bad_pixel_fraction"}
_WFS_FIELDS = {"min_fill_fraction", "pad_factor", "detector_window_px", "centroid_estimator", "threshold_fraction", "subtract_minimum", "min_flux_e", "min_peak_snr", "max_centroid_sigma_px", "max_window_clipping_fraction", "central_obstruction_ratio", "spider_width_m"}
_DM_FIELDS = {"influence_model", "coupling_width_pitch", "stroke_limit_opd_m", "include_edge_actuators", "actuator_margin_fraction", "dead_actuator_indices", "stuck_actuator_indices", "stuck_command_opd_m"}
_CALIBRATION_FIELDS = {"source", "method", "probe_kind", "amplitude_m", "include_noise", "repeats", "resource_name"}
_RECONSTRUCTOR_FIELDS = {"kind", "rcond", "alpha", "min_valid_fraction", "min_rank", "max_cached_masks"}
_PROJECTOR_FIELDS = {"kind", "mapping_resource"}
_CONTROLLER_FIELDS = {"n_steps", "gain", "leak", "latency_frames", "frame_rate_hz", "include_noise"}
_SCIENCE_FIELDS = {"psf_pad_factor"}
_RANDOM_FIELDS = {"root_seed", "derivation_scheme_id"}


def _construct(
    cls: type[Any],
    value: object,
    fields: set[str],
    label: str,
    *,
    tuple_fields: frozenset[str] | set[str] = frozenset(),
) -> Any:
    mapping = _mapping(value, label)
    _keys(mapping, fields, label)
    kwargs = dict(mapping)
    for name in tuple_fields:
        kwargs[name] = _tuple_value(kwargs[name], f"{label}.{name}")
    try:
        return cls(**kwargs)
    except (TypeError, ValueError) as exc:
        if isinstance(exc, SystemConfigError):
            raise
        raise SystemConfigError(f"invalid {label}: {exc}") from exc


def _dataclass_mapping(value: object) -> dict[str, object]:
    names = value.__dataclass_fields__  # type: ignore[attr-defined]
    result: dict[str, object] = {}
    for name in names:
        item = getattr(value, name)
        result[name] = list(item) if isinstance(item, tuple) else item
    return result


def _provenance(value: object) -> Provenance:
    try:
        return Provenance.from_record(_mapping(value, "provenance"))
    except ValueError as exc:
        raise SystemConfigError(f"invalid profile provenance: {exc}") from exc


def _keys(value: Mapping[str, object], expected: set[str], label: str) -> None:
    actual = set(value)
    missing = sorted(expected - actual)
    unknown = sorted(actual - expected)
    if missing or unknown:
        raise SystemConfigError(f"{label} fields mismatch; missing={missing}, unknown={unknown}.")


def _mapping(value: object, label: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping) or not all(isinstance(key, str) for key in value):
        raise SystemConfigError(f"{label} must be a string-keyed mapping.")
    return cast(Mapping[str, object], value)


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise SystemConfigError(f"duplicate JSON key {key!r}.")
        result[key] = value
    return result


def _invalid_json_constant(value: str) -> None:
    raise SystemConfigError(f"non-finite JSON number {value!r} is not permitted.")


def _text(value: object, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise SystemConfigError(f"{label} must be a non-empty string.")
    return value.strip()


def _optional_text(value: object, label: str) -> str | None:
    return None if value is None else _text(value, label)


def _profile_name(value: object) -> str:
    name = _text(value, "profile_name")
    if _PROFILE_NAME.fullmatch(name) is None:
        raise SystemConfigError("profile_name must use lowercase snake_case.")
    return name


def _boolean(value: object, label: str) -> bool:
    if not isinstance(value, bool):
        raise SystemConfigError(f"{label} must be a boolean.")
    return value


def _integer(value: object, label: str, *, minimum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, Integral):
        raise SystemConfigError(f"{label} must be an integer.")
    result = int(value)
    if result < minimum:
        raise SystemConfigError(f"{label} must be >= {minimum}.")
    return result


def _optional_integer(value: object, label: str, *, minimum: int) -> int | None:
    return None if value is None else _integer(value, label, minimum=minimum)


def _finite(value: object, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, Real):
        raise SystemConfigError(f"{label} must be a finite real number.")
    result = float(value)
    if not math.isfinite(result):
        raise SystemConfigError(f"{label} must be finite.")
    return result


def _positive(value: object, label: str) -> float:
    result = _finite(value, label)
    if result <= 0.0:
        raise SystemConfigError(f"{label} must be positive.")
    return result


def _nonnegative(value: object, label: str) -> float:
    result = _finite(value, label)
    if result < 0.0:
        raise SystemConfigError(f"{label} must be non-negative.")
    return result


def _optional_positive(value: object, label: str) -> float | None:
    return None if value is None else _positive(value, label)


def _optional_nonnegative(value: object, label: str) -> float | None:
    return None if value is None else _nonnegative(value, label)


def _fraction(value: object, label: str) -> float:
    result = _nonnegative(value, label)
    if result > 1.0:
        raise SystemConfigError(f"{label} must be at most 1.")
    return result


def _tuple_value(value: object, label: str) -> tuple[Any, ...]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        raise SystemConfigError(f"{label} must be an ordered sequence.")
    return tuple(value)


def _pair(value: object, label: str) -> tuple[float, float]:
    items = _tuple_value(value, label)
    if len(items) != 2:
        raise SystemConfigError(f"{label} must contain two values.")
    return (_finite(items[0], f"{label}[0]"), _finite(items[1], f"{label}[1]"))


def _positive_tuple(value: object, label: str) -> tuple[float, ...]:
    items = _tuple_value(value, label)
    if not items:
        raise SystemConfigError(f"{label} must not be empty.")
    return tuple(_positive(item, f"{label}[{index}]") for index, item in enumerate(items))


def _indices(value: object, label: str) -> tuple[int, ...]:
    items = _tuple_value(value, label)
    result = tuple(_integer(item, f"{label}[{index}]", minimum=0) for index, item in enumerate(items))
    if len(result) != len(set(result)):
        raise SystemConfigError(f"{label} must not contain duplicates.")
    return result


__all__ = (
    "PROFILE_SCHEMA_NAME",
    "PROFILE_SCHEMA_VERSION",
    "SystemConfigError",
    "ProfileProvenance",
    "AtmosphereConfig",
    "DetectorSystemConfig",
    "WfsConfig",
    "DmSystemConfig",
    "CalibrationConfig",
    "ReconstructorConfig",
    "CommandProjectorConfig",
    "ControllerConfig",
    "ScienceConfig",
    "RandomSeedConfig",
    "SystemConfig",
    "available_system_profiles",
    "load_system_profile",
    "system_config_from_mapping",
    "system_config_to_mapping",
)
