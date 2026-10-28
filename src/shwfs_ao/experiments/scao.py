"""Shared SCAO system construction and closed-loop experiment orchestration."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
import json
from pathlib import PurePosixPath
from types import MappingProxyType
from typing import Any, Protocol, runtime_checkable

import numpy as np

from ..calibration import (
    DmActuatorProbeBasis,
    InteractionMatrix,
    LeastSquaresReconstructor,
    TikhonovReconstructor,
    TsvdReconstructor,
    calibrate_interaction_matrix,
)
from ..control import (
    ControlledSubsetCommandProjector,
    IdentityCommandProjector,
    LeakyIntegratorController,
    LoopConfig,
    ModalToActuatorCommandProjector,
    validate_closed_loop_components,
)
from ..control.loop import run_closed_loop as _run_component_loop
from ..core.hashing import component_config_hash
from ..core.protocols import (
    AtmosphereModel,
    CommandProjector,
    Controller,
    DeformableMirrorModel,
    RandomStreams,
    Reconstructor,
    SciencePropagator,
    WavefrontSensor,
)
from ..core.random import NamedRandomStreams
from ..detector import CentroidConfig, CentroidValidityConfig, DetectorConfig
from ..dm import DMConfig
from ..io.configs import SystemConfig
from ..io.resources import read_text_resource
from ..science.propagation import PsfSampling


__all__ = (
    "ScaoConstructionError",
    "ScaoBackendComponentFactory",
    "ScaoSystem",
    "register_scao_backend_factory",
    "build_scao_system",
    "run_closed_loop",
)


class ScaoConstructionError(ValueError):
    """Raised when a serialized SCAO configuration cannot be assembled safely."""


@runtime_checkable
class ScaoBackendComponentFactory(Protocol):
    """Structural backend construction boundary used by this experiment layer."""

    @property
    def backend_name(self) -> str:
        ...

    def build_geometry(self, **kwargs: Any) -> Any:
        ...

    def build_atmosphere(self, **kwargs: Any) -> AtmosphereModel:
        ...

    def build_wfs(self, **kwargs: Any) -> WavefrontSensor:
        ...

    def build_dm(self, **kwargs: Any) -> DeformableMirrorModel:
        ...

    def build_science_propagator(self, **kwargs: Any) -> SciencePropagator:
        ...


@dataclass(frozen=True)
class ScaoSystem:
    """A complete, identity-validated collection of SCAO protocol components."""

    random_streams: RandomStreams
    atmosphere: AtmosphereModel
    wfs: WavefrontSensor
    dm: DeformableMirrorModel
    interaction_matrix: InteractionMatrix
    reconstructor: Reconstructor
    command_projector: CommandProjector
    controller: Controller
    science_propagator: SciencePropagator
    component_hashes: Mapping[str, str]
    config_hash: str

    def __post_init__(self) -> None:
        if not isinstance(self.component_hashes, Mapping):
            raise ScaoConstructionError("component_hashes must be a mapping.")
        normalized: dict[str, str] = {}
        for key, value in self.component_hashes.items():
            if not isinstance(key, str) or not key:
                raise ScaoConstructionError(
                    "component_hashes keys must be non-empty strings."
                )
            if not isinstance(value, str) or not value:
                raise ScaoConstructionError(
                    "component_hashes values must be non-empty strings."
                )
            normalized[key] = value
        if not isinstance(self.config_hash, str) or not self.config_hash:
            raise ScaoConstructionError("config_hash must be a non-empty string.")
        object.__setattr__(
            self,
            "component_hashes",
            MappingProxyType(dict(sorted(normalized.items()))),
        )


_FACTORIES: dict[str, ScaoBackendComponentFactory] = {}


def _load_native_factory() -> ScaoBackendComponentFactory:
    from ..backends.native.factory import NATIVE_SCAO_COMPONENT_FACTORY

    return NATIVE_SCAO_COMPONENT_FACTORY


_BUILTIN_FACTORY_LOADERS: Mapping[
    str,
    Callable[[], ScaoBackendComponentFactory],
] = MappingProxyType({"native": _load_native_factory})


def register_scao_backend_factory(
    backend_name: str,
    factory: ScaoBackendComponentFactory,
    *,
    replace: bool = False,
) -> None:
    """Register an optional backend factory without changing profile physics."""

    if not isinstance(backend_name, str) or not backend_name.strip():
        raise ScaoConstructionError("backend_name must be a non-empty string.")
    name = backend_name.strip()
    if not isinstance(factory, ScaoBackendComponentFactory):
        raise ScaoConstructionError(
            "factory must implement ScaoBackendComponentFactory."
        )
    if factory.backend_name != name:
        raise ScaoConstructionError(
            "factory.backend_name must exactly equal its registry key."
        )
    if name in _FACTORIES and not replace:
        raise ScaoConstructionError(
            f"a SCAO backend factory is already registered for {name!r}."
        )
    _FACTORIES[name] = factory


def build_scao_system(
    config: SystemConfig,
    *,
    interaction_matrix: InteractionMatrix | None = None,
) -> ScaoSystem:
    """Build one complete system from a reviewed, unit-explicit configuration.

    Calibration behavior is intentionally fail-closed. ``source='build'`` is
    the only mode that calibrates. ``source='resource'`` must load its exact
    resource, and ``source='supplied'`` requires ``interaction_matrix`` here;
    neither mode silently falls back to an expensive rebuild.
    """

    if not isinstance(config, SystemConfig):
        raise ScaoConstructionError("config must be a SystemConfig.")
    factory = _factory_for(config.backend)
    streams = NamedRandomStreams(config.random.root_seed)
    if streams.derivation_scheme_id != config.random.derivation_scheme_id:
        raise ScaoConstructionError(
            "random derivation scheme does not match the serialized profile."
        )

    geometry = factory.build_geometry(
        telescope_diameter_m=config.telescope_diameter_m,
        pupil_pixels=config.pupil_pixels,
        lenslets_across=config.lenslets_across,
        min_fill_fraction=config.wfs.min_fill_fraction,
        central_obstruction_ratio=config.wfs.central_obstruction_ratio,
        spider_width_m=config.wfs.spider_width_m,
    )
    atmosphere = factory.build_atmosphere(
        model=config.atmosphere_model,
        geometry=geometry,
        random_streams=streams,
        r0_m=config.atmosphere.r0_m,
        outer_scale_m=config.atmosphere.outer_scale_m,
        phase_reference_wavelength_m=(
            config.atmosphere.r0_reference_wavelength_m
        ),
        wind_m_per_s=config.atmosphere.wind_m_per_s,
        target_rms_rad=_target_rms_rad(config),
        normalize_rms=config.atmosphere.normalize_rms,
        static_opd_rms_m=(
            0.0
            if config.atmosphere.target_rms_opd_m is None
            else config.atmosphere.target_rms_opd_m
        ),
    )
    dm = factory.build_dm(
        geometry=geometry,
        config=_dm_config(config),
    )
    detector_config = _detector_config(config)
    wfs = factory.build_wfs(
        model=config.wfs_model,
        geometry=geometry,
        wfs_wavelength_m=config.wfs_wavelength_m,
        pad_factor=config.wfs.pad_factor or 1,
        detector_window_px=config.wfs.detector_window_px,
        detector_config=detector_config,
        centroid_config=_centroid_config(config),
        validity_config=_validity_config(config),
        random_streams=streams,
    )
    science_propagator = factory.build_science_propagator(
        geometry=geometry,
        sampling=PsfSampling(pad_factor=config.science.psf_pad_factor),
    )

    matrix = _resolve_interaction_matrix(
        config,
        dm=dm,
        wfs=wfs,
        random_streams=streams,
        supplied=interaction_matrix,
    )
    if matrix.geometry_hash != geometry.geometry_hash:
        raise ScaoConstructionError(
            "interaction-matrix geometry_hash must match the constructed WFS "
            "geometry before the first frame."
        )
    reconstructor = _build_reconstructor(config, matrix)
    command_projector = _build_command_projector(config, matrix, dm)
    loop_config = _loop_config(config)
    controller = LeakyIntegratorController.from_loop_config(
        dm.actuator_ids,
        loop_config,
    )

    try:
        validate_closed_loop_components(
            loop_config,
            random_streams=streams,
            atmosphere=atmosphere,
            wfs=wfs,
            dm=dm,
            interaction_matrix=matrix,
            reconstructor=reconstructor,
            command_projector=command_projector,
            controller=controller,
            include_noise=config.controller.include_noise,
        )
    except (TypeError, ValueError) as exc:
        raise ScaoConstructionError(
            f"constructed SCAO component identities are inconsistent: {exc}"
        ) from exc

    component_hashes = {
        "random_streams": component_config_hash(
            "scao.random_streams",
            {
                "root_seed": streams.root_seed,
                "derivation_scheme_id": streams.derivation_scheme_id,
                "registered_domains": streams.registered_domains,
            },
        ),
        "pupil_geometry": geometry.geometry_hash,
        "atmosphere": atmosphere.config_hash,
        "wfs": wfs.config_hash,
        "dm": dm.config_hash,
        "interaction_matrix": matrix.matrix_hash,
        "reconstructor": _component_hash(reconstructor, "reconstructor"),
        "command_projector": command_projector.config_hash,
        "controller": controller.config_hash,
        "science_propagator": science_propagator.config_hash,
    }
    return ScaoSystem(
        random_streams=streams,
        atmosphere=atmosphere,
        wfs=wfs,
        dm=dm,
        interaction_matrix=matrix,
        reconstructor=reconstructor,
        command_projector=command_projector,
        controller=controller,
        science_propagator=science_propagator,
        component_hashes=component_hashes,
        config_hash=config.config_hash,
    )


def run_closed_loop(
    config: SystemConfig,
    *,
    system: ScaoSystem | None = None,
    interaction_matrix: InteractionMatrix | None = None,
    realization_index: int = 0,
):
    """Execute either detector-level or geometric profiles through one runner."""

    if not isinstance(config, SystemConfig):
        raise ScaoConstructionError("config must be a SystemConfig.")
    if system is not None and interaction_matrix is not None:
        raise ScaoConstructionError(
            "interaction_matrix cannot accompany an already-built system."
        )
    resolved = (
        build_scao_system(config, interaction_matrix=interaction_matrix)
        if system is None
        else system
    )
    if not isinstance(resolved, ScaoSystem):
        raise ScaoConstructionError("system must be a ScaoSystem or None.")
    if resolved.config_hash != config.config_hash:
        raise ScaoConstructionError(
            "system.config_hash must match the supplied serialized config."
        )
    return _run_component_loop(
        _loop_config(config),
        random_streams=resolved.random_streams,
        atmosphere=resolved.atmosphere,
        wfs=resolved.wfs,
        dm=resolved.dm,
        interaction_matrix=resolved.interaction_matrix,
        reconstructor=resolved.reconstructor,
        command_projector=resolved.command_projector,
        controller=resolved.controller,
        include_noise=config.controller.include_noise,
        realization_index=realization_index,
    )


def _factory_for(name: str) -> ScaoBackendComponentFactory:
    factory = _FACTORIES.get(name)
    if factory is not None:
        return factory
    loader = _BUILTIN_FACTORY_LOADERS.get(name)
    if loader is None:
        raise ScaoConstructionError(
            f"no SCAO backend factory is registered for {name!r}; "
            "optional backends never fall back to native."
        )
    factory = loader()
    register_scao_backend_factory(name, factory)
    return factory


def _target_rms_rad(config: SystemConfig) -> float | None:
    if config.atmosphere.target_rms_opd_m is None:
        return None
    return float(
        2.0
        * np.pi
        * config.atmosphere.target_rms_opd_m
        / config.atmosphere.r0_reference_wavelength_m
    )


def _detector_config(config: SystemConfig) -> DetectorConfig:
    detector = config.detector
    source_note = (
        f"SCAO profile {config.profile.profile_name}@"
        f"{config.profile.profile_version}; detector settings are serialized "
        "profile inputs, not backend defaults."
    )
    return DetectorConfig(
        photons_per_subap_frame=detector.photons_per_subap_frame,
        read_noise_e=detector.read_noise_e,
        dark_e_per_s=detector.dark_e_per_s,
        background_e_per_pixel_frame=detector.background_e_per_pixel_frame,
        full_well_e=detector.full_well_e,
        qe=detector.qe,
        prnu_rms=detector.prnu_rms,
        exposure_s=detector.exposure_s,
        source_class=config.profile.provenance.source_class,
        source_note=source_note,
        prnu_mode=detector.prnu_mode,
        bad_pixel_fraction=detector.bad_pixel_fraction,
    )


def _centroid_config(config: SystemConfig) -> CentroidConfig:
    return CentroidConfig(
        estimator=config.wfs.centroid_estimator,
        threshold_fraction=config.wfs.threshold_fraction,
        subtract_minimum=config.wfs.subtract_minimum,
    )


def _validity_config(config: SystemConfig) -> CentroidValidityConfig:
    return CentroidValidityConfig(
        min_flux_e=config.wfs.min_flux_e,
        min_peak_snr=config.wfs.min_peak_snr,
        max_centroid_sigma_px=config.wfs.max_centroid_sigma_px,
        max_window_clipping_fraction=(
            config.wfs.max_window_clipping_fraction
        ),
    )


def _dm_config(config: SystemConfig) -> DMConfig:
    dm = config.dm
    return DMConfig(
        telescope_diameter_m=config.telescope_diameter_m,
        n_actuators_across=config.actuators_across,
        influence_model=dm.influence_model,
        coupling_width_pitch=dm.coupling_width_pitch,
        stroke_limit_nm=dm.stroke_limit_opd_m * 1.0e9,
        include_edge_actuators=dm.include_edge_actuators,
        actuator_margin_fraction=dm.actuator_margin_fraction,
        dead_actuator_indices=dm.dead_actuator_indices,
        stuck_actuator_indices=dm.stuck_actuator_indices,
        stuck_command_nm=dm.stuck_command_opd_m * 1.0e9,
        source_class=config.profile.provenance.source_class,
        source_note=(
            f"SCAO profile {config.profile.profile_name}@"
            f"{config.profile.profile_version}; DM values are explicit."
        ),
    )


def _resolve_interaction_matrix(
    config: SystemConfig,
    *,
    dm: DeformableMirrorModel,
    wfs: WavefrontSensor,
    random_streams: RandomStreams,
    supplied: InteractionMatrix | None,
) -> InteractionMatrix:
    calibration = config.calibration

    def build() -> InteractionMatrix:
        if supplied is not None:
            raise ScaoConstructionError(
                "an interaction_matrix may only be supplied when "
                "calibration.source='supplied'."
            )
        if calibration.probe_kind != "dm_actuator":
            raise ScaoConstructionError(
                "the native SCAO factory currently builds only explicit "
                "dm_actuator probe bases."
            )
        try:
            probe_basis = DmActuatorProbeBasis(dm)  # type: ignore[arg-type]
        except (TypeError, ValueError) as exc:
            raise ScaoConstructionError(
                f"cannot build the configured DM probe basis: {exc}"
            ) from exc
        return calibrate_interaction_matrix(
            probe_basis,
            wfs,
            calibration.amplitude_m,
            random_streams=random_streams.scoped("scao-interaction-calibration"),
            method=calibration.method,
            include_noise=calibration.include_noise,
            repeats=calibration.repeats,
        )

    def supplied_matrix() -> InteractionMatrix:
        if supplied is None:
            raise ScaoConstructionError(
                "calibration.source='supplied' requires interaction_matrix."
            )
        if not isinstance(supplied, InteractionMatrix):
            raise ScaoConstructionError(
                "interaction_matrix must be a canonical InteractionMatrix."
            )
        return supplied

    def resource_matrix() -> InteractionMatrix:
        if supplied is not None:
            raise ScaoConstructionError(
                "interaction_matrix cannot accompany calibration.source='resource'."
            )
        assert calibration.resource_name is not None
        record = _json_resource(calibration.resource_name)
        try:
            return InteractionMatrix.from_record(record)
        except (TypeError, ValueError) as exc:
            raise ScaoConstructionError(
                f"invalid interaction-matrix resource {calibration.resource_name!r}: "
                f"{exc}"
            ) from exc

    resolvers: Mapping[str, Callable[[], InteractionMatrix]] = {
        "build": build,
        "supplied": supplied_matrix,
        "resource": resource_matrix,
    }
    try:
        resolver = resolvers[calibration.source]
    except KeyError as exc:  # SystemConfig normally rejects this first.
        raise ScaoConstructionError(
            f"unknown calibration source {calibration.source!r}."
        ) from exc
    return resolver()


def _build_reconstructor(
    config: SystemConfig,
    matrix: InteractionMatrix,
) -> Reconstructor:
    reconstructor = config.reconstructor
    common = {
        "min_valid_fraction": reconstructor.min_valid_fraction,
        "min_rank": reconstructor.min_rank,
        "max_cached_masks": reconstructor.max_cached_masks,
    }
    builders: Mapping[str, Callable[[], Reconstructor]] = {
        "least_squares": lambda: LeastSquaresReconstructor(matrix, **common),
        "tsvd": lambda: TsvdReconstructor(
            matrix,
            reconstructor.rcond,
            **common,
        ),
        "tikhonov": lambda: TikhonovReconstructor(
            matrix,
            reconstructor.alpha,
            **common,
        ),
    }
    try:
        builder = builders[reconstructor.kind]
    except KeyError as exc:
        raise ScaoConstructionError(
            f"unknown reconstructor kind {reconstructor.kind!r}."
        ) from exc
    try:
        return builder()
    except (TypeError, ValueError) as exc:
        raise ScaoConstructionError(
            f"cannot build reconstructor {reconstructor.kind!r}: {exc}"
        ) from exc


def _build_command_projector(
    config: SystemConfig,
    matrix: InteractionMatrix,
    dm: DeformableMirrorModel,
) -> CommandProjector:
    projector = config.command_projector

    def identity() -> CommandProjector:
        if matrix.coordinate_ids != dm.actuator_ids:
            raise ScaoConstructionError(
                "identity projector requires interaction coordinates to equal "
                "the full DM actuator layout; select controlled_subset explicitly."
            )
        return IdentityCommandProjector(dm.actuator_ids)

    def controlled_subset() -> CommandProjector:
        if matrix.coordinate_kind != "dm_command_opd":
            raise ScaoConstructionError(
                "controlled_subset projector requires dm_command_opd coordinates."
            )
        return ControlledSubsetCommandProjector(
            matrix.coordinate_ids,
            dm.actuator_ids,
        )

    def modal() -> CommandProjector:
        if projector.mapping_resource is None:
            raise ScaoConstructionError(
                "modal projector requires an explicit mapping_resource."
            )
        record = _json_resource(projector.mapping_resource)
        expected = {
            "schema_id",
            "modal_to_actuator_matrix",
            "input_coordinate_ids",
            "output_actuator_ids",
            "target_dm_hash",
        }
        if set(record) != expected or record.get("schema_id") != (
            "shwfs_ao.modal_command_mapping.v1"
        ):
            raise ScaoConstructionError(
                "modal mapping resource has unsupported schema or fields."
            )
        input_ids = tuple(record["input_coordinate_ids"])
        output_ids = tuple(record["output_actuator_ids"])
        if input_ids != matrix.coordinate_ids:
            raise ScaoConstructionError(
                "modal mapping input IDs must match interaction coordinates."
            )
        if output_ids != dm.actuator_ids:
            raise ScaoConstructionError(
                "modal mapping output IDs must match the full DM layout."
            )
        if record["target_dm_hash"] != dm.config_hash:
            raise ScaoConstructionError(
                "modal mapping target_dm_hash must match the constructed DM."
            )
        return ModalToActuatorCommandProjector(
            np.asarray(record["modal_to_actuator_matrix"], dtype=float),
            input_coordinate_ids=input_ids,
            output_actuator_ids=output_ids,
            target_dm_hash=dm.config_hash,
        )

    builders: Mapping[str, Callable[[], CommandProjector]] = {
        "identity": identity,
        "controlled_subset": controlled_subset,
        "modal": modal,
    }
    try:
        builder = builders[projector.kind]
    except KeyError as exc:
        raise ScaoConstructionError(
            f"unknown command projector kind {projector.kind!r}."
        ) from exc
    try:
        return builder()
    except (TypeError, ValueError) as exc:
        if isinstance(exc, ScaoConstructionError):
            raise
        raise ScaoConstructionError(
            f"cannot build command projector {projector.kind!r}: {exc}"
        ) from exc


def _loop_config(config: SystemConfig) -> LoopConfig:
    controller = config.controller
    return LoopConfig(
        n_steps=controller.n_steps,
        gain=controller.gain,
        leak=controller.leak,
        latency_frames=controller.latency_frames,
        frame_rate_hz=controller.frame_rate_hz,
        root_seed=config.random.root_seed,
    )


def _json_resource(resource_name: str) -> Mapping[str, object]:
    path = PurePosixPath(resource_name)
    if (
        path.is_absolute()
        or not path.parts
        or any(part in {"", ".", ".."} for part in path.parts)
        or path.suffix.lower() != ".json"
    ):
        raise ScaoConstructionError(
            "resource names must be safe relative .json package paths."
        )
    try:
        value = json.loads(read_text_resource(resource_name))
    except (FileNotFoundError, ModuleNotFoundError) as exc:
        raise ScaoConstructionError(
            f"required calibration resource {resource_name!r} is absent; "
            "no recalibration fallback is permitted."
        ) from exc
    except (OSError, json.JSONDecodeError) as exc:
        raise ScaoConstructionError(
            f"cannot read calibration resource {resource_name!r}: {exc}"
        ) from exc
    if not isinstance(value, Mapping):
        raise ScaoConstructionError(
            f"calibration resource {resource_name!r} must contain a JSON object."
        )
    return value


def _component_hash(component: object, label: str) -> str:
    value = getattr(component, "config_hash", None)
    if not isinstance(value, str) or not value:
        raise ScaoConstructionError(
            f"{label} must expose a non-empty config_hash."
        )
    return value
