"""DET-08: finite-exposure integration over atmosphere sub-samples."""

from __future__ import annotations

from dataclasses import replace

import numpy as np
import pytest

from shwfs_ao.control.loop import ControlLoopError, run_closed_loop as component_loop
from shwfs_ao.experiments import scao
from shwfs_ao.io.configs import load_system_profile


def _count_calls(monkeypatch, atmosphere) -> list[float]:
    """Record every ``opd_at`` time on the instance itself."""

    times: list[float] = []
    original = atmosphere.opd_at

    def counting(time_s):
        times.append(float(time_s))
        return original(time_s)

    monkeypatch.setattr(atmosphere, "opd_at", counting)
    return times


def _loop(system, config, *, atmosphere=None, **keywords):
    return component_loop(
        scao._loop_config(config),
        random_streams=system.random_streams,
        atmosphere=system.atmosphere if atmosphere is None else atmosphere,
        wfs=system.wfs,
        dm=system.dm,
        interaction_matrix=system.interaction_matrix,
        reconstructor=system.reconstructor,
        command_projector=system.command_projector,
        controller=system.controller,
        include_noise=config.controller.include_noise,
        **keywords,
    )


def _config(n_steps: int = 6):
    config = load_system_profile("det_ccd_2m_synthetic", 1)
    return replace(config, controller=replace(config.controller, n_steps=n_steps))


def test_one_subsample_is_bit_identical_with_one_atmosphere_call_per_frame(monkeypatch) -> None:
    config = _config()
    system = scao.build_scao_system(config)
    reference = _loop(system, config)
    times = _count_calls(monkeypatch, system.atmosphere)
    explicit = _loop(system, config, exposure_subsamples=1, exposure_s=1.0e-3)
    for name in ("open_loop_opd_rms_m", "post_update_residual_opd_rms_m", "applied_command_opd_m"):
        if hasattr(reference, name):
            assert np.array_equal(getattr(reference, name), getattr(explicit, name)), name
    assert times == [k / config.controller.frame_rate_hz for k in range(config.controller.n_steps)]


def test_subsamples_sample_within_the_exposure(monkeypatch) -> None:
    config = _config(n_steps=3)
    system = scao.build_scao_system(config)
    times = _count_calls(monkeypatch, system.atmosphere)
    _loop(system, config, exposure_subsamples=4, exposure_s=1.0e-3)
    expected = [k * 1.0e-3 + j * 2.5e-4 for k in range(3) for j in range(4)]
    assert np.allclose(times, expected, rtol=0, atol=1e-15)


def test_a_static_atmosphere_gives_the_same_frames_for_any_subsample_count() -> None:
    config = _config(n_steps=4)
    system = scao.build_scao_system(config)
    residual = np.asarray(system.atmosphere.opd_at(0.0))
    residual = np.where(np.isfinite(residual), residual, 0.0)
    single = system.wfs.measure(residual, random_streams=system.random_streams, include_noise=False)
    triple = system.wfs.measure_exposure([residual] * 3, random_streams=system.random_streams, include_noise=False)
    np.testing.assert_allclose(triple.vector.values, single.vector.values, rtol=1e-12, atol=1e-12)


def test_opposite_tilts_within_one_exposure_broaden_rather_than_cancel() -> None:
    config = _config(n_steps=2)
    system = scao.build_scao_system(config)
    geometry = system.wfs.geometry
    tilt = np.where(np.asarray(geometry.pupil_mask), 4.0e-7 * np.asarray(geometry.x_m), 0.0)
    flat = np.zeros(geometry.pupil_shape)

    def width(measurement) -> float:
        frame = measurement.detector_telemetry.detector_frames[6]
        image = np.clip(frame.expected_source_e, 0.0, None)
        x = np.arange(image.shape[1])
        profile = image.sum(axis=0)
        mean = float(np.sum(profile * x) / profile.sum())
        return float(np.sum(profile * (x - mean) ** 2) / profile.sum())

    streams = system.random_streams
    still = system.wfs.measure_exposure([flat, flat], random_streams=streams, include_noise=False)
    one_way = system.wfs.measure(tilt, random_streams=streams, include_noise=False)
    split = system.wfs.measure_exposure([tilt, -tilt], random_streams=streams, include_noise=False)
    shift = float(one_way.vector.values[12])
    assert abs(shift) > 0.5
    assert abs(split.vector.values[12]) < 0.05 * abs(shift)  # the mean centroid stays put
    # Two equal copies displaced by +-s add s^2 to the profile variance.
    assert width(split) - width(still) == pytest.approx(shift**2, rel=0.1)


def test_subsamples_need_an_exposure_and_a_capable_wfs() -> None:
    config = _config(n_steps=2)
    system = scao.build_scao_system(config)
    with pytest.raises(ControlLoopError, match="exposure_s"):
        _loop(system, config, exposure_subsamples=2)
    with pytest.raises(ControlLoopError, match="frame period"):
        _loop(system, config, exposure_subsamples=2, exposure_s=2.0e-3)
