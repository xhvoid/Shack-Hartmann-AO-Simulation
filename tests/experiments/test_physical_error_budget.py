"""Contracts for the physically-conditioned error-budget disturbance.

The shipped ``control_space_proxy`` disturbance is synthesized *from the
deformable mirror*, so it lies entirely inside the mirror's controllable span
and a budget built on it contains no fitting error at all.  These tests pin
that fact, pin the corrected alternative against turbulence theory, and pin the
gap between them so neither can be mistaken for the other again.
"""

from __future__ import annotations


import numpy as np
import pytest

from shwfs_ao.experiments.atmospheric_disturbance import (
    PHASE_SOURCE_ATMOSPHERIC_SCREEN,
    PHASE_SOURCE_CONTROL_SPACE,
    build_atmospheric_phase_sequence,
    build_phase_sequence,
    physical_error_budget_scenarios,
)
from shwfs_ao.experiments.error_budget import (
    AOErrorBudgetError,
    ScenarioConfig,
    build_control_space_phase_sequence,
    default_jhk_bandpasses,
    run_error_budget_scenario,
)
from shwfs_ao.legacy.dm_model import (
    DMConfig,
    build_dm_model,
    fit_static_opd_with_dm,
)
from shwfs_ao.legacy.interaction_matrix import (
    PokeMatrixConfig,
    build_detector_dm_poke_matrix,
)
from shwfs_ao.legacy.synthetic_instrument_data import (
    DetectorConfig,
    ShwfsGeometryConfig,
    build_detector_shwfs_calibration,
    make_pupil_grid_and_mask,
)


R0_M = 0.1263371938263465
SOURCE = {
    "source_class": "synthetic_assumed",
    "source_note": "Physical error-budget contract test.",
}


@pytest.fixture(scope="module")
def instrument():
    geometry = ShwfsGeometryConfig(
        telescope_diameter_m=2.0,
        n_pupil_pixels=52,
        n_lenslets=5,
        detector_window_px=18,
        pad_factor=3,
        source_note="Physical error-budget contract test.",
    )
    x_m, y_m, mask, _ = make_pupil_grid_and_mask(geometry)
    dm_model = build_dm_model(
        x_m,
        y_m,
        mask,
        DMConfig(
            telescope_diameter_m=2.0,
            n_actuators_across=5,
            influence_model="gaussian",
            coupling_width_pitch=0.40,
            stroke_limit_nm=1000.0,
            source_class="synthetic_literature_inspired",
            source_note="Physical error-budget contract test.",
        ),
    )
    calibration = build_detector_shwfs_calibration(
        geometry,
        DetectorConfig(
            read_noise_e=1.0,
            qe=1.0,
            source_class="synthetic_literature_inspired",
            source_note="Physical error-budget contract test.",
        ),
    )
    poke = build_detector_dm_poke_matrix(
        calibration,
        dm_model,
        PokeMatrixConfig(
            calibration_amplitude_nm=10.0,
            target_kept_mode_fraction=1.0,
            source_class="synthetic_literature_inspired",
            source_note="Physical error-budget contract test.",
        ),
    )
    return calibration, dm_model, poke, mask


def _scenario(**changes) -> ScenarioConfig:
    values = {
        "scenario_name": "contract",
        "enabled_effects": ("multi_component_dynamic_phase",),
        "n_steps": 24,
        "frame_rate_hz": 1000.0,
        "latency_frames": 2,
        **SOURCE,
    }
    values.update(changes)
    return ScenarioConfig(**values)


def test_the_proxy_disturbance_carries_no_fitting_error(instrument) -> None:
    """The shipped disturbance is a DM surface, so the DM fits it exactly."""

    calibration, dm_model, poke, mask = instrument
    sequence = build_control_space_phase_sequence(
        calibration, dm_model, poke, _scenario(phase_amplitude_nm=260.0)
    )
    wavelength_m = calibration.geometry.wfs_wavelength_m
    opd_nm = sequence[0] * wavelength_m / (2.0 * np.pi) * 1.0e9
    residual = np.asarray(
        fit_static_opd_with_dm(np.nan_to_num(opd_nm), dm_model).residual_opd_nm
    )

    input_rms = float(np.nanstd(opd_nm[mask]))
    residual_rms = float(np.nanstd(residual[mask]))
    assert input_rms > 1.0
    assert residual_rms / input_rms < 1.0e-9


def test_a_real_screen_leaves_substantial_fitting_error(instrument) -> None:
    """A von Karman screen on a 5x5 actuator grid is largely uncorrectable."""

    calibration, dm_model, poke, mask = instrument
    sequence = build_atmospheric_phase_sequence(
        calibration,
        dm_model,
        poke,
        _scenario(phase_source=PHASE_SOURCE_ATMOSPHERIC_SCREEN, r0_m=R0_M),
    )
    wavelength_m = calibration.geometry.wfs_wavelength_m
    opd_nm = sequence[0] * wavelength_m / (2.0 * np.pi) * 1.0e9
    residual = np.asarray(
        fit_static_opd_with_dm(np.nan_to_num(opd_nm), dm_model).residual_opd_nm
    )

    ratio = float(np.nanstd(residual[mask])) / float(np.nanstd(opd_nm[mask]))
    assert 0.2 < ratio < 0.8, f"fitting residual fraction {ratio:.3f}"


def test_atmospheric_amplitude_follows_r0_not_a_free_parameter(instrument) -> None:
    """Halving r0 must raise the disturbance by the von Karman scaling."""

    calibration, dm_model, poke, mask = instrument
    wavelength_m = calibration.geometry.wfs_wavelength_m

    def rms_nm(r0_m: float) -> float:
        sequence = build_atmospheric_phase_sequence(
            calibration,
            dm_model,
            poke,
            _scenario(
                phase_source=PHASE_SOURCE_ATMOSPHERIC_SCREEN,
                r0_m=r0_m,
                n_steps=4,
            ),
        )
        frames = sequence * wavelength_m / (2.0 * np.pi) * 1.0e9
        return float(np.mean([np.nanstd(frame[mask]) for frame in frames]))

    weak = rms_nm(2.0 * R0_M)
    strong = rms_nm(R0_M)

    # Variance scales as r0^(-5/3); the finite outer scale damps this somewhat,
    # so the RMS ratio sits below the 2^(5/6) = 1.78 Kolmogorov value.
    assert 1.2 < strong / weak < 1.9


def test_atmospheric_amplitude_ignores_phase_amplitude_nm(instrument) -> None:
    calibration, dm_model, poke, mask = instrument

    def rms(amplitude_nm: float) -> float:
        sequence = build_atmospheric_phase_sequence(
            calibration,
            dm_model,
            poke,
            _scenario(
                phase_source=PHASE_SOURCE_ATMOSPHERIC_SCREEN,
                r0_m=R0_M,
                phase_amplitude_nm=amplitude_nm,
                n_steps=4,
            ),
        )
        return float(np.nanstd(sequence[0][mask]))

    assert rms(100.0) == pytest.approx(rms(900.0), rel=1.0e-12)


def test_phase_source_dispatch_selects_the_requested_disturbance(instrument) -> None:
    calibration, dm_model, poke, _ = instrument

    proxy = build_phase_sequence(
        calibration, dm_model, poke, _scenario(n_steps=4)
    )
    reference_proxy = build_control_space_phase_sequence(
        calibration, dm_model, poke, _scenario(n_steps=4)
    )
    # Frames are NaN outside the pupil, so identity needs equal_nan.
    assert np.array_equal(proxy, reference_proxy, equal_nan=True)

    physical = build_phase_sequence(
        calibration,
        dm_model,
        poke,
        _scenario(
            phase_source=PHASE_SOURCE_ATMOSPHERIC_SCREEN, r0_m=R0_M, n_steps=4
        ),
    )
    assert physical.shape == proxy.shape
    assert not np.allclose(physical, proxy)


def test_atmospheric_source_requires_r0() -> None:
    with pytest.raises(AOErrorBudgetError, match="requires r0_m"):
        _scenario(phase_source=PHASE_SOURCE_ATMOSPHERIC_SCREEN)


def test_unknown_phase_source_is_rejected() -> None:
    with pytest.raises(AOErrorBudgetError, match="is not one of"):
        _scenario(phase_source="kolmogorov_cube")


def test_a_run_that_outlives_its_screen_fails_loudly(instrument) -> None:
    """Silently wrapping the screen through the pupil is not an option."""

    calibration, dm_model, poke, _ = instrument
    with pytest.raises(AOErrorBudgetError, match="travel|seam"):
        build_atmospheric_phase_sequence(
            calibration,
            dm_model,
            poke,
            _scenario(
                phase_source=PHASE_SOURCE_ATMOSPHERIC_SCREEN,
                r0_m=R0_M,
                n_steps=4000,
                turbulence_speed_m_s=40.0,
            ),
        )


@pytest.mark.slow
def test_the_physical_budget_is_materially_harder_than_the_proxy(instrument) -> None:
    """The headline consequence, pinned.

    The proxy matrix reports a nearly perfect system because the disturbance is
    exactly correctable and the loop has no latency.  The physical matrix must
    report a system that a 5x5 actuator grid genuinely cannot correct.
    """

    calibration, dm_model, poke, _ = instrument
    bandpasses = default_jhk_bandpasses()

    proxy = run_error_budget_scenario(
        calibration,
        dm_model,
        poke,
        _scenario(phase_amplitude_nm=260.0, latency_frames=0, n_steps=24),
        bandpasses,
        telescope_diameter_m=2.0,
    )
    physical = run_error_budget_scenario(
        calibration,
        dm_model,
        poke,
        _scenario(
            phase_source=PHASE_SOURCE_ATMOSPHERIC_SCREEN, r0_m=R0_M, n_steps=24
        ),
        bandpasses,
        telescope_diameter_m=2.0,
    )

    assert proxy.strehl_H > 0.95
    assert physical.strehl_H < 0.85
    assert physical.open_rms_nm > 3.0 * proxy.open_rms_nm
    assert physical.closed_over_open_rms > proxy.closed_over_open_rms


def test_physical_scenario_matrix_covers_the_required_rows() -> None:
    scenarios = physical_error_budget_scenarios()
    names = tuple(scenario.scenario_name for scenario in scenarios)

    from shwfs_ao.experiments.error_budget import REQUIRED_SCENARIO_NAMES

    assert names == REQUIRED_SCENARIO_NAMES
    assert all(
        scenario.phase_source == PHASE_SOURCE_ATMOSPHERIC_SCREEN
        for scenario in scenarios
    )
    assert all(scenario.r0_m is not None for scenario in scenarios)
    by_name = {scenario.scenario_name: scenario for scenario in scenarios}
    assert by_name["ideal_static"].latency_frames == 0
    assert by_name["latency"].latency_frames > by_name["all_effects"].latency_frames
    assert by_name["all_effects"].latency_frames == 2


def test_default_matrix_still_uses_the_proxy_so_baselines_hold() -> None:
    from shwfs_ao.experiments.error_budget import default_error_budget_scenarios

    assert all(
        scenario.phase_source == PHASE_SOURCE_CONTROL_SPACE
        for scenario in default_error_budget_scenarios()
    )


# --------------------------------------------------------------------------
# Identity stability of the frozen proxy scenarios
# --------------------------------------------------------------------------


def test_atmosphere_selectors_are_absent_from_a_proxy_scenario_hash() -> None:
    """Appending the selectors must not move a frozen scenario's identity.

    The four atmosphere fields were added to ``ScenarioConfig`` after the fast
    baselines were accepted.  Hashing the dataclass wholesale would have
    silently changed the recorded ``config_hash`` of every proxy row even
    though none of their physics moved, and no table test compares that column.
    """

    from shwfs_ao.experiments.error_budget import _scenario_hash_payload

    proxy = _scenario(n_steps=4)
    payload = _scenario_hash_payload(proxy)

    for field in (
        "phase_source",
        "r0_m",
        "outer_scale_m",
        "r0_reference_wavelength_m",
    ):
        assert field not in payload, field
    assert payload == {
        key: value
        for key, value in proxy.__dict__.items()
        if key
        not in {
            "phase_source",
            "r0_m",
            "outer_scale_m",
            "r0_reference_wavelength_m",
        }
    }


def test_an_atmospheric_scenario_hashes_its_selectors() -> None:
    """Opting into the real atmosphere must change the recorded identity."""

    from shwfs_ao.experiments.error_budget import _scenario_hash_payload

    physical = _scenario(
        n_steps=4, phase_source=PHASE_SOURCE_ATMOSPHERIC_SCREEN, r0_m=R0_M
    )
    payload = _scenario_hash_payload(physical)

    assert payload["phase_source"] == PHASE_SOURCE_ATMOSPHERIC_SCREEN
    assert payload["r0_m"] == R0_M
    assert _scenario_hash_payload(_scenario(n_steps=4)) != payload


def test_the_atmospheric_screen_samples_the_calibration_grid(instrument) -> None:
    """The screen must inherit the pupil's own spacing, not a re-derivation.

    ``make_pupil_grid_and_mask`` spans the full diameter with a linspace, so
    its spacing is ``D/(pixels-1)``.  Assuming ``D/pixels`` samples the screen
    about 2 % too finely and biases D/r0 by roughly 3 % in variance.
    """

    from shwfs_ao.experiments.error_budget import calibration_grid_spacing_m

    calibration, _, _, _ = instrument
    x_m = np.asarray(calibration.x_m, dtype=float)
    pixels = x_m.shape[0]
    diameter = calibration.geometry.telescope_diameter_m

    spacing = calibration_grid_spacing_m(calibration)
    assert spacing == pytest.approx(diameter / (pixels - 1), rel=1e-12)
    assert spacing != pytest.approx(diameter / pixels, rel=1e-6)
    assert spacing * (pixels - 1) == pytest.approx(diameter, rel=1e-12)


def test_grid_spacing_rejects_a_degenerate_calibration_grid() -> None:
    from types import SimpleNamespace

    from shwfs_ao.experiments.error_budget import calibration_grid_spacing_m

    with pytest.raises(AOErrorBudgetError, match="at least two columns"):
        calibration_grid_spacing_m(SimpleNamespace(x_m=np.zeros((4, 1))))
    with pytest.raises(AOErrorBudgetError, match="increasing in x"):
        calibration_grid_spacing_m(
            SimpleNamespace(x_m=np.tile(np.array([1.0, 1.0]), (2, 1)))
        )
