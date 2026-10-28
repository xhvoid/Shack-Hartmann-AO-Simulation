"""Passivity, frame semantics and streaming averages on a materialized 6-frame fixture.

The fixture is the explorer's own profile (``det_emccd_2m_synthetic@1``)
shortened to six frames with burn-in 2, so it exercises the real physical
WFS, controller queue and native propagator while staying a small
deterministic contract fixture (not an AO study).  Every frame's raw maps
and images are retained so the streamed means can be checked against an
offline mean of the materialized images.
"""

from __future__ import annotations

from dataclasses import replace

import numpy as np
import pytest

import observer as explorer_observer
import producer
import protocol


N_STEPS = 6
BURN_IN = 2


@pytest.fixture(scope="module")
def fixture_runs():
    from shwfs_ao.experiments.scao import build_scao_system, run_closed_loop

    job = dict(protocol.production_jobs()[1], n_steps=N_STEPS, burn_in=BURN_IN)
    config = producer.job_config(job)
    config = replace(config, controller=replace(config.controller, n_steps=N_STEPS))
    observed_system = build_scao_system(config)
    obs = explorer_observer.ExplorerObserver(
        observed_system.science_propagator,
        wavelength_m=protocol.SCIENCE_WAVELENGTH_M,
        n_steps=N_STEPS,
        burn_in=BURN_IN,
        display_indices=[0, BURN_IN, N_STEPS - 1],
        telescope_diameter_m=config.telescope_diameter_m,
        retain_all_frames=True,
    )
    observed = run_closed_loop(config, system=observed_system, observers=(obs,))
    plain = run_closed_loop(config, system=build_scao_system(config))
    return {"config": config, "observer": obs, "observed": observed, "plain": plain, "system": observed_system}


def test_observer_is_passive(fixture_runs):
    observed, plain = fixture_runs["observed"], fixture_runs["plain"]
    assert producer.history_digest(observed) == producer.history_digest(plain)
    assert observed.config_hash == plain.config_hash
    np.testing.assert_array_equal(observed.applied_command_history_opd_m, plain.applied_command_history_opd_m)


def test_frame_alignment_and_residual_semantics(fixture_runs):
    obs, history = fixture_runs["observer"], fixture_runs["observed"]
    frames = obs.frames
    assert frames["frame_index"] == list(range(N_STEPS))
    np.testing.assert_array_equal(frames["time_s"], history.time_s)
    assert frames["time_s"][1] == pytest.approx(1.0e-3, abs=0.0)
    # The observer's RMS of the two maps is the loop's own history, bit for bit.
    np.testing.assert_array_equal(frames["atmosphere_rms_m"], history.open_loop_opd_rms_m)
    np.testing.assert_array_equal(frames["residual_rms_m"], history.pre_update_residual_opd_rms_m)
    # The DM starts flat and the queue holds L = 2 zeros: frames 0..L see no
    # correction yet (first increment of frame 0 is released at frame 2's update).
    for index in range(fixture_runs["config"].controller.latency_frames + 1):
        snapshot = obs.all_frames[index]
        np.testing.assert_array_equal(snapshot["pre_update_residual_opd_m"], snapshot["atmosphere_opd_m"])
    later = obs.all_frames[N_STEPS - 1]
    assert np.nanmax(np.abs(later["held_correction_opd_m"])) > 0.0
    mask = obs.pupil_mask
    for snapshot in obs.all_frames.values():
        assert np.all(np.isnan(snapshot["atmosphere_opd_m"][~mask]))
        assert np.all(np.isfinite(snapshot["atmosphere_opd_m"][mask]))
        np.testing.assert_allclose(
            snapshot["atmosphere_opd_m"][mask] - snapshot["held_correction_opd_m"][mask],
            snapshot["pre_update_residual_opd_m"][mask],
            rtol=0.0,
            atol=1e-21,
        )
        # Piston-removed atmosphere (the model removes the pupil mean).
        assert abs(np.mean(snapshot["atmosphere_opd_m"][mask])) < 1e-18


def test_independent_reductions(fixture_runs):
    obs = fixture_runs["observer"]
    tol = protocol.TOLERANCES
    ideal = obs.ideal_psf.intensity
    for index, snapshot in obs.all_frames.items():
        rms = explorer_observer.independent_rms(snapshot["pre_update_residual_opd_m"], obs.pupil_mask)
        assert rms == pytest.approx(obs.frames["residual_rms_m"][index], rel=tol["rms_m"]["rtol"], abs=tol["rms_m"]["atol"])
        strehl = explorer_observer.independent_peak_strehl(snapshot["psf_corrected"], ideal)
        assert abs(strehl - obs.frames["peak_strehl_corrected"][index]) <= tol["strehl"]["atol"]


def test_uncorrected_image_is_the_zero_dm_atmosphere(fixture_runs):
    obs, system = fixture_runs["observer"], fixture_runs["system"]
    snapshot = obs.all_frames[N_STEPS - 1]
    direct = system.science_propagator.psf_from_opd(snapshot["atmosphere_opd_m"], protocol.SCIENCE_WAVELENGTH_M)
    np.testing.assert_array_equal(direct.intensity, snapshot["psf_uncorrected"])


def test_streamed_means_equal_offline_means_of_materialized_images(fixture_runs):
    obs = fixture_runs["observer"]
    finish = obs.finish()
    assert finish["analysis_frames"] == list(range(BURN_IN, N_STEPS))
    assert finish["analysis_count"] == N_STEPS - BURN_IN
    selected = [obs.all_frames[index] for index in range(BURN_IN, N_STEPS)]
    offline_corrected = np.mean(np.stack([item["psf_corrected"] for item in selected]), axis=0)
    offline_uncorrected = np.mean(np.stack([item["psf_uncorrected"] for item in selected]), axis=0)
    atol = protocol.TOLERANCES["mean_psf"]["atol"]
    np.testing.assert_allclose(finish["mean_psf_corrected"], offline_corrected, rtol=0.0, atol=atol)
    np.testing.assert_allclose(finish["mean_psf_uncorrected"], offline_uncorrected, rtol=0.0, atol=atol)
    # Mean of instantaneous intensities, not the image of a mean OPD.
    mean_opd = np.mean(np.stack([item["pre_update_residual_opd_m"] for item in selected]), axis=0)
    image_of_mean = fixture_runs["system"].science_propagator.psf_from_opd(mean_opd, protocol.SCIENCE_WAVELENGTH_M)
    assert np.max(np.abs(image_of_mean.intensity - finish["mean_psf_corrected"])) > 1e-6
    # Mean instantaneous Strehl differs from the Strehl of the averaged image.
    strehl_of_mean = np.max(finish["mean_psf_corrected"]) / np.max(finish["ideal_psf"])
    mean_strehl = np.mean(obs.frames["peak_strehl_corrected"][BURN_IN:])
    assert strehl_of_mean <= mean_strehl + 1e-12


def test_observer_refuses_out_of_order_or_bad_contracts(fixture_runs):
    system = fixture_runs["system"]
    with pytest.raises(explorer_observer.ExplorerObserverError):
        explorer_observer.ExplorerObserver(
            system.science_propagator,
            wavelength_m=protocol.SCIENCE_WAVELENGTH_M,
            n_steps=4,
            burn_in=4,
            display_indices=[0],
            telescope_diameter_m=2.0,
        )
    with pytest.raises(explorer_observer.ExplorerObserverError):
        explorer_observer.ExplorerObserver(
            system.science_propagator,
            wavelength_m=protocol.SCIENCE_WAVELENGTH_M,
            n_steps=4,
            burn_in=1,
            display_indices=[2, 1],
            telescope_diameter_m=2.0,
        )
