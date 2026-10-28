"""Shipped detector-level SCAO profiles must close the loop they describe.

``fast_2m_detector@3`` unpinned the v2 atmosphere but kept the 18 px detector
window.  At d/r0 = 2.1 per lenslet that window cannot hold the open-loop spots:
window clipping invalidates at least one lenslet in every frame, the
``min_valid_fraction=1.0`` reconstructor fails closed on all of them, and the
DM never moves.  The published profile stays frozen; ``fast_2m_detector@4`` is
the same profile with a 24 px window.
"""

from __future__ import annotations

import warnings

import numpy as np
import pytest

from shwfs_ao.control import ControlLoopWarning
from shwfs_ao.core.types import DetectorTelemetry
from shwfs_ao.experiments import build_scao_system, run_closed_loop
from shwfs_ao.io.configs import SystemConfig, load_system_profile


# The native detector-level 2 m profiles to start new work from.
RECOMMENDED_2M_DETECTOR_PROFILES = (
    ("fast_2m_detector", 4),
    ("portfolio_2m_detector", 3),
    ("research_2m_detector", 3),
)


def _first_frame_telemetry(
    name: str,
    version: int,
) -> tuple[SystemConfig, DetectorTelemetry]:
    """Measure the first frame of a run, which is always open loop."""

    config = load_system_profile(name, version)
    system = build_scao_system(config)
    system.atmosphere.reset(realization_index=0)
    measurement = system.wfs.measure(
        system.atmosphere.opd_at(0.0),
        random_streams=system.random_streams,
        include_noise=config.controller.include_noise,
    )
    assert measurement.detector_telemetry is not None
    return config, measurement.detector_telemetry


@pytest.mark.parametrize(("name", "version"), RECOMMENDED_2M_DETECTOR_PROFILES)
def test_recommended_2m_profiles_hold_open_loop_spots_inside_the_window(
    name: str,
    version: int,
) -> None:
    config, telemetry = _first_frame_telemetry(name, version)

    # With min_valid_fraction=1.0 a single clipped open-loop spot keeps the
    # loop from ever applying its first correction.
    assert config.reconstructor.min_valid_fraction == 1.0
    assert telemetry.valid_subapertures.all(), dict(
        zip(telemetry.subaperture_ids, telemetry.clipping_fraction.round(3))
    )
    assert np.max(telemetry.clipping_fraction) <= (
        config.wfs.max_window_clipping_fraction
    )


@pytest.mark.parametrize(
    ("name", "version"),
    [
        ("fast_2m_detector", 4),
        pytest.param("portfolio_2m_detector", 3, marks=pytest.mark.slow),
        pytest.param("research_2m_detector", 3, marks=pytest.mark.slow),
    ],
)
def test_recommended_2m_profiles_close_the_loop(name: str, version: int) -> None:
    config = load_system_profile(name, version)
    with warnings.catch_warnings():
        warnings.simplefilter("error", ControlLoopWarning)
        history = run_closed_loop(config)

    assert history.metadata["reconstruction_usable_fraction"] >= 0.9
    assert np.any(history.applied_command_history_opd_m)
    settled = slice(history.n_steps // 2, None)
    closed = float(np.mean(history.post_update_residual_opd_rms_m[settled]))
    open_loop = float(np.mean(history.open_loop_opd_rms_m[settled]))
    assert closed < 0.8 * open_loop


def test_fast_2m_detector_v4_reconstructs_every_frame() -> None:
    history = run_closed_loop(load_system_profile("fast_2m_detector", 4))

    assert history.reconstruction_usable.all()
    assert history.metadata["reconstruction_usable_frames"] == history.n_steps


def test_fast_2m_detector_v3_stays_frozen_and_reports_that_it_never_closed() -> None:
    config, telemetry = _first_frame_telemetry("fast_2m_detector", 3)

    # Window clipping is the only criterion that rejects lenslets.
    assert not telemetry.valid_subapertures.all()
    assert not telemetry.valid_by_clipping.all()
    assert telemetry.valid_by_flux.all()
    assert telemetry.valid_by_snr.all()
    assert telemetry.valid_by_uncertainty.all()
    assert np.max(telemetry.clipping_fraction) > (
        config.wfs.max_window_clipping_fraction
    )

    with pytest.warns(ControlLoopWarning, match=r"min_valid_fraction=1\.0"):
        history = run_closed_loop(config)

    assert history.metadata["reconstruction_usable_frames"] == 0
    assert history.metadata["reconstruction_usable_fraction"] == 0.0
    assert not np.any(history.applied_command_history_opd_m)
    np.testing.assert_array_equal(
        history.post_update_residual_opd_rms_m,
        history.open_loop_opd_rms_m,
    )
