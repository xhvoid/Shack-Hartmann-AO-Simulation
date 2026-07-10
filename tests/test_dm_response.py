# Tests verify zero-command DM phase, localized influence, stroke clipping, dead/stuck actuator handling, and synthetic DM preset loading.

import numpy as np
import pytest

from dm_model import (
    DMConfig,
    build_dm_model,
    load_dm_config_from_json,
    synthesize_dm_opd_nm,
    synthesize_dm_phase_rad,
    actuator_metadata,
    fit_static_opd_with_dm,
)
from synthetic_instrument_data import ShwfsGeometryConfig, make_pupil_grid_and_mask


def _pupil_grid():
    geometry = ShwfsGeometryConfig(
        telescope_diameter_m=2.0,
        n_pupil_pixels=80,
        n_lenslets=8,
        source_note="DM unit-test pupil geometry.",
    )
    return make_pupil_grid_and_mask(geometry)


def _model(influence_model: str = "gaussian", stroke_limit_nm: float = 100.0):
    x_m, y_m, mask, _ = _pupil_grid()
    config = DMConfig(
        telescope_diameter_m=2.0,
        n_actuators_across=7,
        influence_model=influence_model,
        coupling_width_pitch=0.35,
        stroke_limit_nm=stroke_limit_nm,
        source_class="synthetic_literature_inspired",
        source_note="Unit-test synthetic DM model.",
    )
    return build_dm_model(x_m, y_m, mask, config)


def test_zero_commands_yield_zero_piston_removed_dm_phase():
    model = _model()
    commands_nm = np.zeros(model.n_actuators)

    phase_rad, synthesis = synthesize_dm_phase_rad(commands_nm, model, wavelength_m=700.0e-9)

    assert np.allclose(phase_rad[model.pupil_mask], 0.0)
    assert np.all(np.isnan(phase_rad[~model.pupil_mask]))
    assert np.allclose(synthesis.opd_nm[model.pupil_mask], 0.0)
    assert np.all(synthesis.clipped_commands_nm == 0.0)


def test_single_actuator_command_produces_finite_localized_influence():
    model = _model()
    center_index = int(np.argmin(np.sum(model.actuator_centers_m**2, axis=1)))
    commands_nm = np.zeros(model.n_actuators)
    commands_nm[center_index] = 50.0

    synthesis = synthesize_dm_opd_nm(commands_nm, model)
    max_index = np.nanargmax(synthesis.opd_nm)
    max_y, max_x = np.unravel_index(max_index, synthesis.opd_nm.shape)
    max_position = np.array([model.x_m[max_y, max_x], model.y_m[max_y, max_x]])

    assert np.all(np.isfinite(synthesis.opd_nm[model.pupil_mask]))
    assert np.nanmax(synthesis.opd_nm) > 0.0
    assert np.linalg.norm(max_position - model.actuator_centers_m[center_index]) < model.actuator_pitch_m


def test_command_clipping_respects_stroke_and_dead_stuck_actuators():
    x_m, y_m, mask, _ = _pupil_grid()
    config = DMConfig(
        telescope_diameter_m=2.0,
        n_actuators_across=7,
        stroke_limit_nm=25.0,
        dead_actuator_indices=(0,),
        stuck_actuator_indices=(1,),
        stuck_command_nm=15.0,
        source_class="synthetic_assumed",
        source_note="Stroke/dead/stuck actuator test model.",
    )
    model = build_dm_model(x_m, y_m, mask, config)
    commands_nm = np.full(model.n_actuators, 100.0)

    synthesis = synthesize_dm_opd_nm(commands_nm, model)

    assert np.max(np.abs(synthesis.clipped_commands_nm)) <= config.stroke_limit_nm
    assert synthesis.clipped_commands_nm[0] == pytest.approx(0.0)
    assert synthesis.clipped_commands_nm[1] == pytest.approx(config.stuck_command_nm)
    assert synthesis.saturation_fraction > 0.0


def test_influence_model_options_are_finite_inside_pupil():
    for influence_model in ("gaussian", "compact_gaussian", "pyramid_like"):
        model = _model(influence_model=influence_model)
        assert model.influence_functions.shape[0] == model.n_actuators
        assert np.all(np.isfinite(model.influence_functions[:, model.pupil_mask]))
        assert np.nanmax(model.influence_functions) == pytest.approx(1.0)


def test_synthetic_dm_preset_loads_with_metadata():
    config = load_dm_config_from_json("data/synthetic_presets/dm_2m_fast_gaussian.json")
    x_m, y_m, mask, _ = _pupil_grid()
    model = build_dm_model(x_m, y_m, mask, config)
    metadata = actuator_metadata(model)

    assert config.source_class == "synthetic_literature_inspired"
    assert config.stroke_limit_nm == pytest.approx(800.0)
    assert metadata["command_unit"] == "nm_OPD_equivalent"
    assert metadata["n_actuators"] == model.n_actuators
    assert len(metadata["actuator_centers_m"]) == model.n_actuators


def test_static_fit_reduces_simple_defocus_like_target():
    model = _model(stroke_limit_nm=500.0)
    radius2 = model.x_m**2 + model.y_m**2
    target_nm = np.where(model.pupil_mask, 80.0 * (radius2 - np.nanmean(radius2[model.pupil_mask])), np.nan)

    fit = fit_static_opd_with_dm(target_nm, model)
    target_rms = np.sqrt(np.mean((target_nm[model.pupil_mask] - np.mean(target_nm[model.pupil_mask])) ** 2))

    assert fit.residual_rms_nm < target_rms
    assert fit.rank > 0
    assert np.all(np.isfinite(fit.singular_values))
