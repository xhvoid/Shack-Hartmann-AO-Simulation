"""Contracts for the transparent native atmosphere implementations."""

from __future__ import annotations

import ast
from dataclasses import FrozenInstanceError
import json
from pathlib import Path

import numpy as np
import pytest

from shwfs_ao.backends.native.atmosphere import (
    FrozenFlowAtmosphere,
    FrozenFlowAtmosphereConfig,
    NativeAtmosphereError,
    StaticOpdAtmosphere,
)
from shwfs_ao.core.protocols import AtmosphereModel
from shwfs_ao.core.wavefront import masked_mean, masked_rms, phase_to_opd
from shwfs_ao.legacy.phase_screen import (
    fourier_phase_screen,
    frozen_flow_shift_physical,
)


AO000_PHASE_SAMPLES_RAD = {
    (16, 16): 1.7354565683685843,
    (10, 16): -0.34353994105924057,
    (16, 10): 0.3029480034705069,
}


def _baseline_config(**changes) -> FrozenFlowAtmosphereConfig:
    values = {
        "grid_size": 32,
        "delta_m": 0.025,
        "pupil_diameter_m": 0.7,
        "r0_m": 0.18,
        "outer_scale_m": 25.0,
        "phase_reference_wavelength_m": 500.0e-9,
        "wind_m_per_s": (0.2, -0.1),
        "root_seed": 4,
        "target_rms_rad": 1.25,
        "normalize_rms": True,
    }
    values.update(changes)
    return FrozenFlowAtmosphereConfig(**values)


def _frames(
    model: FrozenFlowAtmosphere,
    times: tuple[float, ...],
) -> tuple[np.ndarray, ...]:
    return tuple(model.opd_at(time_s) for time_s in times)


def test_native_module_has_no_legacy_dependency() -> None:
    source_path = (
        Path(__file__).resolve().parents[3]
        / "src"
        / "shwfs_ao"
        / "backends"
        / "native"
        / "atmosphere.py"
    )
    tree = ast.parse(source_path.read_text(encoding="utf-8"))
    imported_modules = {
        node.module
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module is not None
    }
    imported_modules.update(
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    )
    assert not any(
        module == "legacy" or module.startswith("legacy.") or ".legacy" in module
        for module in imported_modules
    )


def test_frozen_flow_is_an_atmosphere_protocol_implementation() -> None:
    config = _baseline_config()
    model = FrozenFlowAtmosphere(config)

    assert isinstance(model, AtmosphereModel)
    assert model.backend_name == "native"
    assert len(model.config_hash) == 64
    assert model.config is config
    assert model.root_seed == 4
    assert model.realization_index == 0


def test_realization_zero_exactly_matches_legacy_fourier_and_integer_roll() -> None:
    config = _baseline_config()
    model = FrozenFlowAtmosphere(config)
    full_phase, _, _, pupil = fourier_phase_screen(
        N=config.grid_size,
        delta=config.delta_m,
        r0=config.r0_m,
        L0=config.outer_scale_m,
        diameter=config.pupil_diameter_m,
        wavelength=config.phase_reference_wavelength_m,
        seed=config.root_seed,
        target_rms_rad=config.target_rms_rad,
        normalize_rms=config.normalize_rms,
        mask_output=False,
    )

    for time_s in (0.0, 0.125, 0.25):
        legacy_phase = frozen_flow_shift_physical(
            full_phase,
            vx=config.wind_m_per_s[0],
            vy=config.wind_m_per_s[1],
            dt=time_s,
            delta=config.delta_m,
            mask=pupil,
        )
        expected_opd_m = phase_to_opd(
            legacy_phase,
            config.phase_reference_wavelength_m,
        )
        assert np.array_equal(model.opd_at(time_s), expected_opd_m, equal_nan=True)


def test_realization_zero_reproduces_ao_ref_000_phase_baseline() -> None:
    config = _baseline_config(wind_m_per_s=(0.0, 0.0))
    model = FrozenFlowAtmosphere(config)
    opd_m = model.opd_at(0.0)
    pupil = model.pupil_mask
    phase_rad = opd_m * (2.0 * np.pi) / config.phase_reference_wavelength_m

    assert int(np.sum(pupil)) == 609
    assert masked_rms(phase_rad, pupil) == pytest.approx(1.25, abs=1.0e-10, rel=1.0e-10)
    assert masked_mean(phase_rad, pupil) == pytest.approx(0.0, abs=1.0e-12)
    for index, expected in AO000_PHASE_SAMPLES_RAD.items():
        assert phase_rad[index] == pytest.approx(expected, abs=2.0e-9, rel=2.0e-9)


def test_frozen_flow_outputs_are_canonical_read_only_defensive_opd() -> None:
    model = FrozenFlowAtmosphere(_baseline_config())
    first = model.opd_at(0.0)
    second = model.opd_at(0.0)
    pupil = model.pupil_mask

    assert first.shape == pupil.shape == (32, 32)
    assert np.all(np.isfinite(first[pupil]))
    assert np.all(np.isnan(first[~pupil]))
    assert masked_mean(first, pupil) == pytest.approx(0.0, abs=1.0e-20)
    assert not first.flags.writeable
    assert not pupil.flags.writeable
    assert not np.shares_memory(first, second)
    with pytest.raises(ValueError):
        first[pupil] = 0.0
    with pytest.raises(ValueError):
        first.setflags(write=True)
    with pytest.raises(ValueError):
        pupil.setflags(write=True)


def test_absolute_time_is_nondecreasing_and_repeated_time_is_idempotent() -> None:
    model = FrozenFlowAtmosphere(_baseline_config())
    first = model.opd_at(0.125)
    repeated = model.opd_at(0.125)

    assert np.array_equal(first, repeated, equal_nan=True)
    with pytest.raises(NativeAtmosphereError, match="nondecreasing"):
        model.opd_at(0.124)
    with pytest.raises(NativeAtmosphereError, match="non-negative"):
        model.reset()
        model.opd_at(-0.1)
    with pytest.raises(NativeAtmosphereError, match="finite real scalar"):
        model.opd_at(np.nan)


def test_reset_replays_same_index_and_changes_different_stochastic_index() -> None:
    model = FrozenFlowAtmosphere(_baseline_config())
    times = (0.0, 0.125, 0.25)

    model.reset(realization_index=2)
    first_replay = _frames(model, times)
    stream_id = model.metadata["random_stream_id"]
    model.reset(realization_index=2)
    second_replay = _frames(model, times)
    assert all(
        np.array_equal(first, second, equal_nan=True)
        for first, second in zip(first_replay, second_replay)
    )
    assert model.metadata["random_stream_id"] == stream_id

    model.reset(realization_index=3)
    different = model.opd_at(0.0)
    assert not np.array_equal(first_replay[0], different, equal_nan=True)

    model.reset(realization_index=0)
    root_realization = model.opd_at(0.0)
    reference = FrozenFlowAtmosphere(_baseline_config()).opd_at(0.0)
    assert np.array_equal(root_realization, reference, equal_nan=True)


def test_config_hash_and_metadata_are_stable_complete_and_json_safe() -> None:
    first = FrozenFlowAtmosphere(_baseline_config())
    second = FrozenFlowAtmosphere(_baseline_config())
    changed = FrozenFlowAtmosphere(_baseline_config(wind_m_per_s=(0.3, -0.1)))

    assert first.config_hash == second.config_hash
    assert first.config_hash != changed.config_hash
    original_hash = first.config_hash
    first.reset(realization_index=8)
    assert first.config_hash == original_hash
    assert first.metadata["config_hash"] == original_hash
    assert first.metadata["root_seed"] == 4
    assert first.metadata["realization_index"] == 8
    assert first.metadata["realization_invariant"] is False
    assert first.metadata["opd_unit"] == "m"
    assert first.metadata["frozen_flow_discretization"] == "nearest_integer_periodic_numpy_roll"
    json.dumps(dict(first.metadata), allow_nan=False)
    with pytest.raises(TypeError):
        first.metadata["root_seed"] = 9


def test_static_opd_is_realization_invariant_and_records_that_fact() -> None:
    y, x = np.indices((9, 9), dtype=float)
    pupil = (x - 4.0) ** 2 + (y - 4.0) ** 2 <= 3.5**2
    source = np.where(pupil, (x - 4.0) * 2.0e-9 + 7.0e-9, np.nan)
    model = StaticOpdAtmosphere(source, pupil, root_seed=17)
    source[pupil] = 99.0
    first = model.opd_at(0.0)
    model.reset(realization_index=99)
    second = model.opd_at(12.0)

    assert isinstance(model, AtmosphereModel)
    assert np.array_equal(first, second, equal_nan=True)
    assert np.all(np.isfinite(first[pupil]))
    assert np.all(np.isnan(first[~pupil]))
    assert masked_mean(first, pupil) == pytest.approx(0.0, abs=1.0e-22)
    assert model.root_seed == 17
    assert model.realization_index == 99
    assert model.metadata["realization_invariant"] is True
    assert model.metadata["realization_invariant_reason"] == "user_supplied_static_opd"
    assert model.metadata["opd_unit"] == "m"
    json.dumps(dict(model.metadata), allow_nan=False)
    with pytest.raises(TypeError):
        model.metadata["realization_index"] = 0


def test_static_opd_obeys_absolute_time_and_reset_contract() -> None:
    pupil = np.ones((3, 3), dtype=bool)
    model = StaticOpdAtmosphere(np.arange(9, dtype=float).reshape(3, 3) * 1.0e-9, pupil)

    expected = model.opd_at(2.0)
    with pytest.raises(NativeAtmosphereError, match="nondecreasing"):
        model.opd_at(1.0)
    model.reset(realization_index=4)
    assert np.array_equal(model.opd_at(0.0), expected, equal_nan=True)


def test_config_and_root_seed_are_immutable() -> None:
    config = _baseline_config()
    model = FrozenFlowAtmosphere(config)

    with pytest.raises(FrozenInstanceError):
        config.root_seed = 99
    with pytest.raises(AttributeError):
        model.root_seed = 99


@pytest.mark.parametrize(
    "changes",
    (
        {"grid_size": 1},
        {"delta_m": 0.0},
        {"pupil_diameter_m": -1.0},
        {"r0_m": np.nan},
        {"outer_scale_m": 0.0},
        {"phase_reference_wavelength_m": 0.0},
        {"wind_m_per_s": (1.0,)},
        {"wind_m_per_s": (np.inf, 0.0)},
        {"root_seed": -1},
        {"target_rms_rad": -1.0},
        {"normalize_rms": 1},
    ),
)
def test_frozen_flow_config_rejects_invalid_values(changes) -> None:
    with pytest.raises(NativeAtmosphereError):
        _baseline_config(**changes)


def test_atmospheres_reject_invalid_pupils_and_static_opd() -> None:
    config = _baseline_config()
    with pytest.raises(NativeAtmosphereError, match="shape"):
        FrozenFlowAtmosphere(config, pupil_mask=np.ones((31, 32), dtype=bool))
    with pytest.raises(NativeAtmosphereError, match="at least one"):
        FrozenFlowAtmosphere(config, pupil_mask=np.zeros((32, 32), dtype=bool))
    with pytest.raises(NativeAtmosphereError, match="boolean"):
        FrozenFlowAtmosphere(config, pupil_mask=np.ones((32, 32), dtype=np.uint8))
    with pytest.raises(NativeAtmosphereError, match="finite"):
        StaticOpdAtmosphere(
            np.asarray([[0.0, np.nan], [1.0, 2.0]]),
            np.ones((2, 2), dtype=bool),
        )
    with pytest.raises(NativeAtmosphereError, match="two-dimensional"):
        StaticOpdAtmosphere(np.ones(4), np.ones(4, dtype=bool))


def test_reset_rejects_invalid_realization_indices() -> None:
    model = FrozenFlowAtmosphere(_baseline_config())

    for value in (-1, 1.5, True):
        with pytest.raises(NativeAtmosphereError, match="realization_index"):
            model.reset(realization_index=value)
