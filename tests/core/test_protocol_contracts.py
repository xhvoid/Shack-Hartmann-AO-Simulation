"""AO-REF-003A executable contracts for backend-neutral protocols."""

from __future__ import annotations

import ast
import inspect
from pathlib import Path

import numpy as np

from shwfs_ao.core import protocols
from shwfs_ao.core.protocols import (
    AtmosphereModel,
    CommandProjector,
    Controller,
    DeformableMirrorModel,
    RandomStreams,
    Reconstructor,
    SciencePropagator,
    ShackHartmannOpticsBackend,
    WavefrontSensor,
)
from shwfs_ao.core.random import NamedRandomStreams


ROOT = Path(__file__).resolve().parents[2]

PROTOCOL_EXPORTS = (
    "RandomStreams",
    "AtmosphereModel",
    "ShackHartmannOpticsBackend",
    "WavefrontSensor",
    "DeformableMirrorModel",
    "Reconstructor",
    "CommandProjector",
    "Controller",
    "SciencePropagator",
)

EXPECTED_MEMBERS = {
    RandomStreams: {
        "root_seed",
        "derivation_scheme_id",
        "reset",
        "generator",
        "keyed_generator",
        "stream_id",
        "scoped",
    },
    AtmosphereModel: {"backend_name", "config_hash", "metadata", "reset", "opd_at"},
    ShackHartmannOpticsBackend: {
        "backend_name",
        "config_hash",
        "spot_intensities",
    },
    WavefrontSensor: {"config_hash", "row_ids", "measure"},
    DeformableMirrorModel: {
        "config_hash",
        "n_actuators",
        "actuator_ids",
        "controllable_actuator_ids",
        "opd_from_commands",
    },
    Reconstructor: {"matrix_hash", "reconstruct"},
    CommandProjector: {
        "config_hash",
        "input_coordinate_ids",
        "input_coordinate_kind",
        "input_coordinate_unit",
        "output_actuator_ids",
        "project",
    },
    Controller: {
        "config_hash",
        "actuator_ids",
        "reset",
        "update",
        "accept_applied_commands",
    },
    SciencePropagator: {"backend_name", "config_hash", "psf_from_opd"},
}


class _AtmosphereDouble:
    @property
    def backend_name(self):
        return "test"

    @property
    def config_hash(self):
        return "atmosphere-hash"

    @property
    def metadata(self):
        return {"test": True}

    def reset(self, *, realization_index=0):
        self.realization_index = realization_index

    def opd_at(self, time_s):
        return np.full((2, 2), time_s)


class _OpticsDouble:
    @property
    def backend_name(self):
        return "test"

    @property
    def config_hash(self):
        return "optics-hash"

    def spot_intensities(self, residual_opd_m):
        return None


class _WfsDouble:
    @property
    def config_hash(self):
        return "wfs-hash"

    @property
    def row_ids(self):
        return ("S0:x", "S0:y")

    def measure(self, residual_opd_m, *, random_streams, include_noise):
        return None


class _DmDouble:
    @property
    def config_hash(self):
        return "dm-hash"

    @property
    def n_actuators(self):
        return 2

    @property
    def actuator_ids(self):
        return ("A0", "A1")

    @property
    def controllable_actuator_ids(self):
        return self.actuator_ids

    def opd_from_commands(self, commands):
        return None


class _ReconstructorDouble:
    @property
    def matrix_hash(self):
        return "matrix-hash"

    def reconstruct(self, measurement):
        return None


class _ProjectorDouble:
    @property
    def config_hash(self):
        return "projector-hash"

    @property
    def input_coordinate_ids(self):
        return ("M0", "M1")

    @property
    def input_coordinate_kind(self):
        return "modal_opd"

    @property
    def input_coordinate_unit(self):
        return "m_opd_rms"

    @property
    def output_actuator_ids(self):
        return ("A0", "A1")

    def project(self, estimate):
        return None


class _ControllerDouble:
    @property
    def config_hash(self):
        return "controller-hash"

    @property
    def actuator_ids(self):
        return ("A0", "A1")

    def reset(self):
        return None

    def update(self, reconstructed_delta):
        return None

    def accept_applied_commands(self, commands):
        return None


class _ScienceDouble:
    @property
    def backend_name(self):
        return "test"

    @property
    def config_hash(self):
        return "science-hash"

    def psf_from_opd(self, opd_m, wavelength_m):
        return None


def test_protocol_surface_is_exact_and_runtime_checkable():
    assert protocols.__all__ == PROTOCOL_EXPORTS

    for protocol, expected_members in EXPECTED_MEMBERS.items():
        actual_members = {
            name for name in vars(protocol) if not name.startswith("_")
        }
        assert actual_members == expected_members

    instances = (
        (_AtmosphereDouble(), AtmosphereModel),
        (_OpticsDouble(), ShackHartmannOpticsBackend),
        (_WfsDouble(), WavefrontSensor),
        (_DmDouble(), DeformableMirrorModel),
        (_ReconstructorDouble(), Reconstructor),
        (_ProjectorDouble(), CommandProjector),
        (_ControllerDouble(), Controller),
        (_ScienceDouble(), SciencePropagator),
        (NamedRandomStreams(7), RandomStreams),
    )
    assert all(isinstance(instance, protocol) for instance, protocol in instances)


def test_protocol_method_parameter_names_and_keyword_only_boundaries_are_frozen():
    expected_parameters = {
        (RandomStreams, "reset"): ("self",),
        (RandomStreams, "generator"): ("self", "domain"),
        (RandomStreams, "keyed_generator"): ("self", "domain", "key"),
        (RandomStreams, "stream_id"): ("self", "domain", "key"),
        (RandomStreams, "scoped"): ("self", "scope", "key"),
        (AtmosphereModel, "reset"): ("self", "realization_index"),
        (AtmosphereModel, "opd_at"): ("self", "time_s"),
        (ShackHartmannOpticsBackend, "spot_intensities"): (
            "self",
            "residual_opd_m",
        ),
        (WavefrontSensor, "measure"): (
            "self",
            "residual_opd_m",
            "random_streams",
            "include_noise",
        ),
        (DeformableMirrorModel, "opd_from_commands"): ("self", "commands"),
        (Reconstructor, "reconstruct"): ("self", "measurement"),
        (CommandProjector, "project"): ("self", "estimate"),
        (Controller, "reset"): ("self",),
        (Controller, "update"): ("self", "reconstructed_delta"),
        (Controller, "accept_applied_commands"): ("self", "commands"),
        (SciencePropagator, "psf_from_opd"): (
            "self",
            "opd_m",
            "wavelength_m",
        ),
    }

    for (protocol, method_name), names in expected_parameters.items():
        signature = inspect.signature(getattr(protocol, method_name))
        assert tuple(signature.parameters) == names

    for protocol, method_name, parameter_name in (
        (RandomStreams, "keyed_generator", "key"),
        (RandomStreams, "stream_id", "key"),
        (RandomStreams, "scoped", "key"),
        (AtmosphereModel, "reset", "realization_index"),
        (WavefrontSensor, "measure", "random_streams"),
        (WavefrontSensor, "measure", "include_noise"),
    ):
        parameter = inspect.signature(getattr(protocol, method_name)).parameters[
            parameter_name
        ]
        assert parameter.kind is inspect.Parameter.KEYWORD_ONLY


def test_protocol_and_random_modules_have_no_physical_or_io_dependencies():
    forbidden = {"backends", "detector", "experiment", "experiments", "io", "legacy"}

    for relative_path in (
        "src/shwfs_ao/core/protocols.py",
        "src/shwfs_ao/core/random.py",
    ):
        path = ROOT / relative_path
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        imported_parts: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported_parts.update(
                    part for alias in node.names for part in alias.name.split(".")
                )
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported_parts.update(node.module.split("."))
        assert imported_parts.isdisjoint(forbidden), (path, imported_parts & forbidden)
