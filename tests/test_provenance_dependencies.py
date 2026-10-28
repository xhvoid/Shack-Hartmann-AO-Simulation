"""AO-REF-003 physical-module provenance dependency contracts."""

from __future__ import annotations

import ast
from dataclasses import fields
import inspect
from pathlib import Path

import numpy as np
import pytest

from shwfs_ao.core.provenance import Provenance
from shwfs_ao.legacy.ao_closed_loop import ClosedLoopError, DetectorLoopConfig
from shwfs_ao.legacy.ao_diagnostics import AODiagnosticsError, ScienceBandpass
from shwfs_ao.legacy.ao_error_budget import AOErrorBudgetError, ScenarioConfig
from shwfs_ao.legacy.ao_integration import IntegrationRunResult
from shwfs_ao.legacy.dm_model import DMConfig, DMModelError
from shwfs_ao.legacy.interaction_matrix import (
    InteractionMatrixError,
    PokeMatrixConfig,
)
from shwfs_ao.legacy.synthetic_instrument_data import (
    DetectorConfig,
    ShwfsGeometryConfig,
    SyntheticInstrumentError,
)


REPO_ROOT = Path(__file__).resolve().parents[1]
PHYSICAL_MODULES = (
    "ao_closed_loop.py",
    "ao_conditions.py",
    "ao_diagnostics.py",
    "ao_error_budget.py",
    "ao_integration.py",
    "ao_validation.py",
    "atmosphere_profiles.py",
    "dm_model.py",
    "interaction_matrix.py",
    "synthetic_instrument_data.py",
)

EXPECTED_CONFIG_SIGNATURES = {
    DMConfig: (
        "telescope_diameter_m",
        "n_actuators_across",
        "influence_model",
        "coupling_width_pitch",
        "stroke_limit_nm",
        "include_edge_actuators",
        "actuator_margin_fraction",
        "dead_actuator_indices",
        "stuck_actuator_indices",
        "stuck_command_nm",
        "source_class",
        "source_note",
    ),
    PokeMatrixConfig: (
        "calibration_amplitude_nm",
        "rcond_scan_grid",
        "target_kept_mode_fraction",
        "minimum_kept_modes",
        "controlled_actuator_indices",
        "source_class",
        "source_note",
    ),
    DetectorLoopConfig: (
        "n_steps",
        "gain",
        "leak",
        "latency_frames",
        "frame_rate_hz",
        "include_detector_noise",
        "seed",
        "source_class",
        "source_note",
    ),
    ScienceBandpass: (
        "name",
        "wavelength_m",
        "transmission",
        "source_class",
        "source_note",
        "filter_id",
    ),
    DetectorConfig: (
        "photons_per_subap_frame",
        "read_noise_e",
        "dark_e_per_s",
        "background_e_per_pixel_frame",
        "full_well_e",
        "qe",
        "bad_pixel_mask",
        "prnu_rms",
        "exposure_s",
        "source_class",
        "source_note",
        "prnu_mode",
        "bad_pixel_fraction",
    ),
    ShwfsGeometryConfig: (
        "telescope_diameter_m",
        "n_pupil_pixels",
        "n_lenslets",
        "min_fill_fraction",
        "pad_factor",
        "detector_window_px",
        "threshold_fraction",
        "subtract_minimum",
        "central_obstruction_ratio",
        "spider_width_m",
        "wfs_wavelength_m",
        "source_class",
        "source_note",
    ),
    ScenarioConfig: (
        "scenario_name",
        "enabled_effects",
        "n_steps",
        "dynamic_phase",
        "phase_amplitude_nm",
        "gain",
        "leak",
        "latency_frames",
        "frame_rate_hz",
        "include_detector_noise",
        "stroke_limit_nm",
        "misregistration_shift_px",
        "misregistration_rotation_deg",
        "misregistration_magnification",
        "misregistration_shear",
        "ncpa_rms_nm",
        "tau0_s",
        "turbulence_speed_m_s",
        "seed",
        "phase_seed",
        "detector_noise_seed",
        "ncpa_seed",
        "source_class",
        "source_note",
    ),
}


def _config_instances() -> tuple[object, ...]:
    return (
        DMConfig(),
        PokeMatrixConfig(),
        DetectorLoopConfig(),
        ScienceBandpass(
            "H",
            np.asarray([1.5e-6, 1.8e-6]),
            np.asarray([1.0, 1.0]),
        ),
        DetectorConfig(),
        ShwfsGeometryConfig(),
        ScenarioConfig("provenance_contract", ("none",)),
    )


def test_physical_modules_import_taxonomy_only_from_core() -> None:
    legacy_dir = REPO_ROOT / "src" / "shwfs_ao" / "legacy"
    for filename in PHYSICAL_MODULES:
        tree = ast.parse((legacy_dir / filename).read_text(encoding="utf-8"))
        provenance_imports = []
        for node in ast.walk(tree):
            if not isinstance(node, ast.ImportFrom):
                continue
            imported_names = {alias.name for alias in node.names}
            assert not (
                node.level == 2 and node.module == "io.public_data"
            ), f"{filename} must not depend on public-data I/O"
            if node.module in {"data_sources", "io.public_data"}:
                assert not ({"ALLOWED_SOURCE_CLASSES", "Provenance"} & imported_names), filename
            if node.level == 2 and node.module == "core.provenance":
                provenance_imports.extend(node.names)

        aliases = {alias.name: alias.asname for alias in provenance_imports}
        assert aliases == {
            "ALLOWED_SOURCE_CLASSES": None,
            "Provenance": "_Provenance",
        }, filename


def test_high_value_config_signatures_and_positional_construction_are_stable() -> None:
    for config_type, expected_parameters in EXPECTED_CONFIG_SIGNATURES.items():
        assert tuple(inspect.signature(config_type).parameters) == expected_parameters

    for config in _config_instances():
        positional_values = tuple(getattr(config, field.name) for field in fields(config))
        positional_copy = type(config)(*positional_values)
        assert positional_copy.source_class == config.source_class
        assert positional_copy.source_note == config.source_note
        assert positional_copy.provenance == config.provenance


def test_high_value_configs_expose_canonical_computed_provenance() -> None:
    for config in _config_instances():
        provenance = config.provenance
        assert isinstance(provenance, Provenance)
        assert provenance.source_class == config.source_class
        assert provenance.source_note == config.source_note


def test_integration_result_derives_provenance_from_flat_reference_metadata() -> None:
    result = IntegrationRunResult(
        "fast",
        (),
        (),
        {
            "schema_version": 999,
            "source_class": "synthetic_assumed",
            "source_note": "Existing flat integration result metadata.",
        },
        (),
        0.25,
        "synthetic_assumed",
        "a" * 64,
    )

    assert result.provenance == Provenance(
        "synthetic_assumed",
        "Existing flat integration result metadata.",
    )


@pytest.mark.parametrize(
    ("factory", "error_type", "expected_message"),
    (
        (
            lambda: DMConfig(source_note=""),
            DMModelError,
            "source_note must be a non-empty string.",
        ),
        (
            lambda: PokeMatrixConfig(source_note=""),
            InteractionMatrixError,
            "source_note must be a non-empty string.",
        ),
        (
            lambda: DetectorLoopConfig(source_note=""),
            ClosedLoopError,
            "source_note must be a non-empty string.",
        ),
        (
            lambda: ScienceBandpass("H", np.asarray([1.65e-6]), np.asarray([1.0]), source_note=""),
            AODiagnosticsError,
            "ScienceBandpass source_note must be non-empty.",
        ),
        (
            lambda: DetectorConfig(source_note=""),
            SyntheticInstrumentError,
            "source_note must be a non-empty string.",
        ),
        (
            lambda: ShwfsGeometryConfig(source_note=""),
            SyntheticInstrumentError,
            "source_note must be a non-empty string.",
        ),
        (
            lambda: ScenarioConfig("invalid", ("none",), source_note=""),
            AOErrorBudgetError,
            "source_note must be a non-empty string.",
        ),
    ),
)
def test_core_validation_retains_module_specific_errors(factory, error_type, expected_message) -> None:
    with pytest.raises(error_type) as exc_info:
        factory()
    assert str(exc_info.value) == expected_message
