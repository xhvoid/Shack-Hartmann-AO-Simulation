# Tests verify detector-level DM poke-matrix shape, finite/non-negative SVD singular values, TSVD reconstruction, and fresh rcond scan diagnostics.

from dataclasses import replace

import numpy as np
import pytest

from dm_model import DMConfig, build_dm_model
from interaction_matrix import (
    DEFAULT_POKE_AMPLITUDE_GRID_NM,
    InteractionMatrixError,
    PokeMatrixConfig,
    build_detector_dm_poke_matrix,
    choose_rcond_from_singular_values,
    expand_controlled_commands,
    kept_modes_for_rcond,
    noise_amplification_proxy,
    poke_amplitude_scan,
    poke_matrix_summary,
    scan_tsvd_rcond,
    tikhonov_reconstruct_commands,
    tsvd_reconstruct_commands,
)
from synthetic_instrument_data import DetectorConfig, ShwfsGeometryConfig, build_detector_shwfs_calibration


@pytest.fixture(scope="module")
def interaction_matrix_case():
    geometry = ShwfsGeometryConfig(
        telescope_diameter_m=2.0,
        n_pupil_pixels=64,
        n_lenslets=6,
        min_fill_fraction=0.35,
        pad_factor=3,
        detector_window_px=20,
        threshold_fraction=0.0,
        source_class="synthetic_assumed",
        source_note="Response-matrix unit-test geometry.",
    )
    calibration = build_detector_shwfs_calibration(
        geometry=geometry,
        detector=DetectorConfig(
            photons_per_subap_frame=None,
            source_class="synthetic_assumed",
            source_note="Deterministic detector test configuration.",
        ),
    )
    dm_model = build_dm_model(
        calibration.x_m,
        calibration.y_m,
        calibration.pupil_mask,
        DMConfig(
            telescope_diameter_m=2.0,
            n_actuators_across=5,
            influence_model="gaussian",
            coupling_width_pitch=0.40,
            stroke_limit_nm=100.0,
            source_class="synthetic_literature_inspired",
            source_note="Unit-test synthetic Gaussian DM model.",
        ),
    )
    config = PokeMatrixConfig(
        calibration_amplitude_nm=12.0,
        rcond_scan_grid=(1.0e-6, 1.0e-5, 1.0e-4, 1.0e-3, 1.0e-2),
        target_kept_mode_fraction=0.85,
        source_class="synthetic_assumed",
        source_note="Unit-test central-difference poke configuration.",
    )
    return calibration, dm_model, build_detector_dm_poke_matrix(calibration, dm_model, config)


def test_poke_matrix_shape_matches_valid_lenslets_and_controlled_actuators(interaction_matrix_case):
    calibration, dm_model, poke = interaction_matrix_case

    assert poke.poke_matrix.shape == (2 * poke.n_valid_lenslets, poke.n_controlled_actuators)
    assert poke.n_valid_lenslets <= calibration.n_valid_subapertures
    assert poke.n_controlled_actuators == dm_model.n_actuators
    assert poke.row_valid.shape == (poke.poke_matrix.shape[0],)
    assert np.all(poke.row_valid)
    assert np.all(np.isfinite(poke.poke_matrix))
    assert not np.any(np.all(~np.isfinite(poke.poke_matrix), axis=0))


def test_svd_singular_values_are_finite_nonnegative_and_reported(interaction_matrix_case):
    _, _, poke = interaction_matrix_case
    summary = poke_matrix_summary(poke)

    assert np.all(np.isfinite(poke.singular_values))
    assert np.all(poke.singular_values >= 0.0)
    assert np.all(np.diff(poke.singular_values) <= 1.0e-12)
    assert poke.rank > 0
    assert 0 < poke.kept_modes <= min(poke.poke_matrix.shape)
    assert poke.kept_modes == kept_modes_for_rcond(poke.singular_values, poke.rcond)
    assert summary["matrix_shape"] == list(poke.poke_matrix.shape)
    assert summary["rank"] == poke.rank
    assert summary["source_class"] == "synthetic_assumed"
    assert summary["matrix_unit"] == "detector_px / nm_OPD_equivalent"
    assert summary["noise_amplification_proxy"] > 0.0
    assert len(poke.config_hash) == 64
    assert poke.calibration_settings["hash_schema"] == 2
    assert set(poke.calibration_settings["calibration_state"]["pupil_mask"]) == {
        "shape",
        "dtype",
        "sha256",
    }
    assert set(poke.calibration_settings["response_state"]["poke_matrix"]) == {
        "shape",
        "dtype",
        "sha256",
    }


def test_poke_hash_is_reproducible_and_tracks_response_relevant_state(interaction_matrix_case):
    calibration, dm_model, poke = interaction_matrix_case
    config = PokeMatrixConfig(
        calibration_amplitude_nm=12.0,
        rcond_scan_grid=(1.0e-6, 1.0e-5, 1.0e-4, 1.0e-3, 1.0e-2),
        target_kept_mode_fraction=0.85,
        source_class="synthetic_assumed",
        source_note="Unit-test central-difference poke configuration.",
    )

    identical = build_detector_dm_poke_matrix(calibration, dm_model, config)
    shifted_reference = replace(
        calibration,
        reference_centroids_px=calibration.reference_centroids_px
        + np.array([1.0e-3, 0.0]),
    )
    changed_reference = build_detector_dm_poke_matrix(shifted_reference, dm_model, config)
    changed_dm = replace(
        dm_model,
        influence_functions=dm_model.influence_functions * 1.001,
    )
    changed_influence = build_detector_dm_poke_matrix(calibration, changed_dm, config)

    assert identical.config_hash == poke.config_hash
    assert changed_reference.config_hash != poke.config_hash
    assert changed_influence.config_hash != poke.config_hash


def test_explicit_controlled_actuator_order_is_preserved_by_canonical_adapter(
    interaction_matrix_case,
):
    calibration, dm_model, full_poke = interaction_matrix_case
    controlled = (2, 0)
    config = PokeMatrixConfig(
        calibration_amplitude_nm=12.0,
        rcond_scan_grid=(1.0e-6, 1.0e-5, 1.0e-4, 1.0e-3, 1.0e-2),
        target_kept_mode_fraction=0.85,
        controlled_actuator_indices=controlled,
        source_class="synthetic_assumed",
        source_note="Reordered legacy actuator-subset adapter fixture.",
    )

    reordered = build_detector_dm_poke_matrix(calibration, dm_model, config)

    np.testing.assert_array_equal(reordered.controlled_actuator_indices, controlled)
    np.testing.assert_array_equal(
        reordered.valid_subaperture_mask,
        full_poke.valid_subaperture_mask,
    )
    np.testing.assert_allclose(
        reordered.poke_matrix,
        full_poke.poke_matrix[:, controlled],
        rtol=2.0e-13,
        atol=2.0e-15,
    )


def test_noise_amplification_proxy_grows_as_rcond_decreases(interaction_matrix_case):
    # Keeping weaker singular directions (smaller rcond) amplifies noise.
    _, _, poke = interaction_matrix_case
    sv = poke.singular_values

    aggressive_cut = noise_amplification_proxy(sv, 1.0e-2)  # fewer modes kept
    permissive_cut = noise_amplification_proxy(sv, 1.0e-6)  # more modes kept

    assert 0.0 < aggressive_cut <= permissive_cut
    # Matches the closed-form Frobenius norm of the kept-mode pseudo-inverse.
    kept = kept_modes_for_rcond(sv, 1.0e-6)
    expected = float(np.sqrt(np.sum((1.0 / sv[:kept]) ** 2)))
    assert permissive_cut == pytest.approx(expected)


def test_poke_amplitude_scan_reports_conditioning_diagnostics(interaction_matrix_case):
    # Poke-amplitude scan over 2, 5, 10, 20, 50 nm OPD-equivalent.
    calibration, dm_model, _ = interaction_matrix_case
    rows = poke_amplitude_scan(calibration, dm_model)

    assert [row["calibration_amplitude_nm"] for row in rows] == list(DEFAULT_POKE_AMPLITUDE_GRID_NM)
    for row in rows:
        assert row["matrix_unit"] == "detector_px / nm_OPD_equivalent"
        assert row["kept_modes"] >= 1
        assert row["noise_amplification_proxy"] > 0.0
        assert np.isfinite(row["largest_singular_value_px_per_nm"])
        assert row["source_class"] == "synthetic_assumed"
    # Central-difference normalisation makes conditioning amplitude-invariant.
    condition_values = [row["condition_proxy"] for row in rows]
    assert max(condition_values) == pytest.approx(min(condition_values), rel=1.0e-2)


def test_tsvd_reconstructs_measurement_in_matrix_column_space(interaction_matrix_case):
    _, dm_model, poke = interaction_matrix_case
    true_commands_nm = np.zeros(poke.n_controlled_actuators)
    true_commands_nm[0] = 2.5
    true_commands_nm[-1] = -1.5
    measurement_px = poke.poke_matrix @ true_commands_nm

    result = tsvd_reconstruct_commands(measurement_px, poke, rcond=1.0e-12)
    full_commands = expand_controlled_commands(result.commands_nm, poke, dm_model)

    assert result.kept_modes >= poke.rank
    assert result.residual_norm_px < 1.0e-10
    assert np.all(np.isfinite(result.commands_nm))
    assert full_commands.shape == (dm_model.n_actuators,)
    assert np.linalg.norm(poke.poke_matrix @ result.commands_nm - measurement_px) < 1.0e-10


def test_rcond_scan_uses_current_matrix_and_kept_modes_are_monotonic(interaction_matrix_case):
    _, _, poke = interaction_matrix_case
    command_vector = np.linspace(-2.0, 2.0, poke.n_controlled_actuators)
    measurement_px = poke.poke_matrix @ command_vector

    scan = scan_tsvd_rcond(measurement_px, poke, rcond_values=(1.0e-8, 1.0e-5, 1.0e-3, 1.0e-1))

    assert scan.source_class == poke.source_class
    assert np.all(np.isfinite(scan.command_norms_nm))
    assert np.all(np.isfinite(scan.residual_norms_px))
    assert np.all(np.diff(scan.kept_modes) <= 0)


def test_tikhonov_placeholder_returns_finite_commands(interaction_matrix_case):
    _, _, poke = interaction_matrix_case
    measurement_px = poke.poke_matrix @ np.ones(poke.n_controlled_actuators)

    result = tikhonov_reconstruct_commands(measurement_px, poke, alpha=1.0e-3)

    assert result.alpha == pytest.approx(1.0e-3)
    assert result.source_class == poke.source_class
    assert np.all(np.isfinite(result.commands_nm))
    assert np.isfinite(result.residual_norm_px)


@pytest.mark.parametrize("alpha", [0.0, 1.0e-12, 1.0e-3])
def test_interaction_tikhonov_handles_rank_deficient_matrix(interaction_matrix_case, alpha):
    _, _, poke = interaction_matrix_case
    matrix = np.array(
        [
            [1.0, 1.0],
            [2.0, 2.0],
            [3.0, 3.0],
            [4.0, 4.0],
        ]
    )
    singular_values = np.linalg.svd(matrix, compute_uv=False)
    rank_deficient = replace(
        poke,
        poke_matrix=matrix,
        singular_values=singular_values,
        kept_modes=1,
        rank=1,
        controlled_actuator_indices=np.array([0, 1]),
        valid_subaperture_mask=np.array([True, True]),
        row_valid=np.ones(4, dtype=bool),
    )
    measurement = matrix @ np.array([1.0, 1.0])

    result = tikhonov_reconstruct_commands(measurement, rank_deficient, alpha=alpha)

    assert np.all(np.isfinite(result.commands_nm))
    assert matrix @ result.commands_nm == pytest.approx(measurement, rel=1.0e-6, abs=1.0e-9)
    assert result.commands_nm[0] == pytest.approx(result.commands_nm[1], rel=1.0e-6, abs=1.0e-9)


def test_impossible_minimum_kept_modes_request_raises():
    with pytest.raises(InteractionMatrixError, match="exceeds numerical rank"):
        choose_rcond_from_singular_values(
            singular_values=(4.0, 1.0, 0.0),
            rcond_grid=(1.0e-8, 1.0e-4),
            minimum_kept_modes=3,
        )


def test_rcond_grid_that_cannot_meet_lower_bound_raises():
    with pytest.raises(InteractionMatrixError, match="No rcond_grid value"):
        choose_rcond_from_singular_values(
            singular_values=(4.0, 1.0, 0.1),
            rcond_grid=(0.5, 0.75),
            target_kept_mode_fraction=1.0,
            minimum_kept_modes=1,
        )


def test_rejects_poke_amplitude_that_would_be_clipped(interaction_matrix_case):
    calibration, dm_model, _ = interaction_matrix_case
    bad_config = PokeMatrixConfig(
        calibration_amplitude_nm=dm_model.config.stroke_limit_nm + 1.0,
        source_note="Invalid clipped-poke test configuration.",
    )

    with pytest.raises(InteractionMatrixError, match="exceeds DM stroke"):
        build_detector_dm_poke_matrix(calibration, dm_model, bad_config)
