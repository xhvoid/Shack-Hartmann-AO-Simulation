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


def _loop(system, config, *, atmosphere=None, wfs=None, **keywords):
    return component_loop(
        scao._loop_config(config),
        random_streams=system.random_streams,
        atmosphere=system.atmosphere if atmosphere is None else atmosphere,
        wfs=system.wfs if wfs is None else wfs,
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


# -- GPT pre-refactor audit F-02 (2026-10-18): the effective quadrature is identity --

# The single-sample identity of this 3-frame system before the change; it
# must stay exactly the same.
SINGLE_SAMPLE_HASH = "02cc0257e875ed44588f24bb93211490294856ecafaa128cb882d9a6b06de7e1"


def _DeclaredExposureWfs(wfs, configured):
    """A shallow copy of the system's WFS that reports another configured count."""

    import copy

    class Declared(type(wfs)):  # type: ignore[misc, valid-type]
        @property
        def exposure_subsamples(self):
            return configured

    clone = copy.copy(wfs)
    clone.__class__ = Declared
    return clone


def test_the_effective_quadrature_is_part_of_the_run_identity() -> None:
    import json

    config = _config(n_steps=3)
    system = scao.build_scao_system(config)
    single = [_loop(system, config), _loop(system, config, exposure_subsamples=1, exposure_s=1.0e-3),
              _loop(system, config, exposure_subsamples=1, exposure_s=5.0e-4)]
    # exposure_s has no effect on one sample, so it changes nothing.
    assert {history.config_hash for history in single} == {SINGLE_SAMPLE_HASH}
    assert all("wfs_exposure" not in history.metadata for history in single)
    multi = {
        (2, 1.0e-3): _loop(system, config, exposure_subsamples=2, exposure_s=1.0e-3),
        (2, 5.0e-4): _loop(system, config, exposure_subsamples=2, exposure_s=5.0e-4),
        (4, 1.0e-3): _loop(system, config, exposure_subsamples=4, exposure_s=1.0e-3),
    }
    hashes = {key: history.config_hash for key, history in multi.items()}
    assert len(set(hashes.values()) | {SINGLE_SAMPLE_HASH}) == 4
    assert _loop(system, config, exposure_subsamples=2, exposure_s=1.0e-3).config_hash == hashes[(2, 1.0e-3)]
    for (count, duration), history in multi.items():
        record = dict(history.metadata["wfs_exposure"])
        assert record == {
            "scheme": "left_point_uniform_held_dm.v1", "subsamples": count, "duration_s": duration,
            "source": "run_closed_loop arguments", "wfs_configured_subsamples": 1,
        }
        assert json.loads(json.dumps(record)) == record  # survives serialization


def test_an_override_of_the_configured_exposure_is_recorded() -> None:
    config = _config(n_steps=3)
    system = scao.build_scao_system(config)
    # A WFS configured for two samples, run on one: the effective single
    # sample keeps the single-sample identity, and the metadata says so.
    declared = _loop(system, config, atmosphere=None, wfs=_DeclaredExposureWfs(system.wfs, 2))
    assert declared.config_hash == SINGLE_SAMPLE_HASH
    assert dict(declared.metadata["wfs_exposure"]) == {
        "scheme": "single_sample_at_frame_time.v1", "subsamples": 1, "duration_s": None,
        "source": "run_closed_loop arguments", "wfs_configured_subsamples": 2,
    }
    # Any integer type is a count (recorded as an int); other types are not.
    numpy_count = _loop(system, config, atmosphere=None, wfs=_DeclaredExposureWfs(system.wfs, np.int64(2)))
    assert numpy_count.config_hash == SINGLE_SAMPLE_HASH
    assert dict(numpy_count.metadata["wfs_exposure"]) == dict(declared.metadata["wfs_exposure"])
    assert type(numpy_count.metadata["wfs_exposure"]["wfs_configured_subsamples"]) is int
    for invalid in (0, np.int64(0), True, np.True_, 2.0):
        with pytest.raises(ControlLoopError, match="positive integer"):
            _loop(system, config, wfs=_DeclaredExposureWfs(system.wfs, invalid))


def test_a_profile_quadrature_reaches_the_run_identity() -> None:
    from shwfs_ao.experiments.detector_level import with_physics

    config = with_physics(_config(n_steps=3), exposure_subsamples=2)
    history = scao.run_closed_loop(config)
    assert dict(history.metadata["wfs_exposure"]) == {
        "scheme": "left_point_uniform_held_dm.v1", "subsamples": 2,
        "duration_s": float(config.detector.exposure_s),
        "source": "run_closed_loop arguments", "wfs_configured_subsamples": 2,
    }
