"""Compatibility contracts for the legacy closed-loop DM spatial wrappers."""

from __future__ import annotations

import inspect

import numpy as np
import pytest

from shwfs_ao.legacy import ao_closed_loop


EXPECTED_PUBLIC_NAMES = {
    "ALLOWED_SOURCE_CLASSES",
    "Any",
    "ClosedLoopError",
    "DEFAULT_CENTROID_VALIDITY",
    "DEFAULT_LOOP_SOURCE_CLASS",
    "DEFAULT_LOOP_SOURCE_NOTE",
    "DMModel",
    "DetectorLoopConfig",
    "DetectorShwfsCalibration",
    "LoopHistory",
    "NM_PER_M",
    "PHASE_TWO_PI",
    "PokeMtxResult",
    "actuator_centers_on_pupil",
    "annotations",
    "build_detector_dm_poke_matrix_from_calibration",
    "build_dm_detector_response_matrix",
    "build_dm_wfs_response_matrix",
    "dataclass",
    "expand_controlled_commands",
    "frozen_flow_shift",
    "frozen_flow_shift_physical",
    "gain_scan",
    "gaussian_influence_functions",
    "hashlib",
    "json",
    "loop_history_summary",
    "math",
    "measure_centroid_shifts",
    "measure_detector_shwfs",
    "measure_slopes",
    "np",
    "reconstruct_dm_delta",
    "reference_centroids",
    "rms",
    "run_closed_loop_ao",
    "run_closed_loop_ao_detector",
    "run_detector_integrator_loop",
    "shifted_atmosphere",
    "stable_array_descriptor",
    "strehl_ratio",
    "synthesize_dm_phase",
    "synthesize_dm_phase_rad",
    "tsvd_reconstruct_commands",
    "vectorize_detector_measurement",
}


def test_exact_public_surface_and_spatial_signatures_remain_frozen() -> None:
    assert {name for name in vars(ao_closed_loop) if not name.startswith("_")} == (
        EXPECTED_PUBLIC_NAMES
    )
    assert str(inspect.signature(ao_closed_loop.actuator_centers_on_pupil)) == (
        "(diameter: 'float' = 1.0, n_actuators: 'int' = 8, "
        "include_edge: 'bool' = True) -> 'tuple[np.ndarray, float]'"
    )
    assert str(inspect.signature(ao_closed_loop.gaussian_influence_functions)) == (
        "(X: 'np.ndarray', Y: 'np.ndarray', pupil_mask: 'np.ndarray', "
        "centers: 'np.ndarray', pitch: 'float', coupling: 'float' = 0.35, "
        "normalize_peak: 'bool' = True) -> 'np.ndarray'"
    )
    assert str(inspect.signature(ao_closed_loop.synthesize_dm_phase)) == (
        "(commands: 'np.ndarray', influence_functions: 'np.ndarray', "
        "pupil_mask: 'np.ndarray', remove_mean: 'bool' = True) -> 'np.ndarray'"
    )


def test_actuator_center_wrapper_delegates_and_restores_writable_array(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[float, int, bool]] = []

    def fake_native(
        diameter: float,
        count: int,
        *,
        include_edge_actuators: bool,
    ) -> tuple[np.ndarray, float]:
        calls.append((diameter, count, include_edge_actuators))
        values = np.asarray([[-0.25, 0.0], [0.25, 0.0]])
        values.setflags(write=False)
        return values, 0.5

    monkeypatch.setattr(
        ao_closed_loop,
        "_native_square_grid_actuator_centers",
        fake_native,
    )
    centers, pitch = ao_closed_loop.actuator_centers_on_pupil(
        1.0,
        4,
        include_edge=False,
    )

    assert calls == [(1.0, 4, False)]
    np.testing.assert_array_equal(centers, [[-0.25, 0.0], [0.25, 0.0]])
    assert pitch == 0.5
    assert centers.flags.writeable


def test_gaussian_wrapper_delegates_and_restores_nan_outside(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pupil = np.asarray([[False, True], [True, False]])
    centers = np.asarray([[0.0, 0.0], [0.2, 0.1]])
    captured: dict[str, object] = {}

    def fake_native(
        x_m: np.ndarray,
        y_m: np.ndarray,
        native_pupil: np.ndarray,
        native_centers: np.ndarray,
        pitch_m: float,
        *,
        coupling_width_pitch: float,
        normalize_peak: bool,
    ) -> np.ndarray:
        captured.update(
            pupil=native_pupil,
            centers=native_centers,
            pitch=pitch_m,
            coupling=coupling_width_pitch,
            normalize=normalize_peak,
        )
        return np.asarray(
            [
                [[0.0, 1.0], [0.5, 0.0]],
                [[0.0, 0.25], [1.0, 0.0]],
            ]
        )

    monkeypatch.setattr(
        ao_closed_loop,
        "_native_gaussian_influence_functions",
        fake_native,
    )
    result = ao_closed_loop.gaussian_influence_functions(
        np.zeros((2, 2)),
        np.zeros((2, 2)),
        pupil,
        centers,
        0.4,
        coupling=0.3,
        normalize_peak=False,
    )

    np.testing.assert_array_equal(captured["pupil"], pupil)
    np.testing.assert_array_equal(captured["centers"], centers)
    assert captured["pitch"] == 0.4
    assert captured["coupling"] == 0.3
    assert captured["normalize"] is False
    assert np.all(np.isnan(result[:, ~pupil]))
    np.testing.assert_array_equal(result[:, pupil], [[1.0, 0.5], [0.25, 1.0]])
    assert result.flags.writeable


def test_synthesis_wrapper_delegates_clean_array_then_restores_legacy_mask(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pupil = np.asarray([[False, True], [True, False]])
    influences = np.asarray(
        [
            [[np.nan, 1.0], [0.5, np.nan]],
            [[np.nan, 0.25], [1.0, np.nan]],
        ]
    )
    commands = np.asarray([2.0, -0.5])
    captured: dict[str, np.ndarray] = {}

    def fake_native(
        native_commands: np.ndarray,
        native_influences: np.ndarray,
    ) -> np.ndarray:
        captured["commands"] = native_commands.copy()
        captured["influences"] = native_influences.copy()
        return np.asarray([[0.0, 1.875], [0.5, 0.0]])

    monkeypatch.setattr(ao_closed_loop, "_native_synthesize_opd", fake_native)
    result = ao_closed_loop.synthesize_dm_phase(
        commands,
        influences,
        pupil,
        remove_mean=False,
    )

    np.testing.assert_array_equal(captured["commands"], commands)
    assert np.all(np.isfinite(captured["influences"]))
    assert np.all(captured["influences"][:, ~pupil] == 0.0)
    assert np.all(np.isnan(result[~pupil]))
    np.testing.assert_array_equal(result[pupil], [1.875, 0.5])


def test_delegated_spatial_wrappers_preserve_frozen_numerics_and_mean_policy() -> None:
    axis = np.linspace(-0.5, 0.5, 31)
    x_m, y_m = np.meshgrid(axis, axis)
    pupil = x_m**2 + y_m**2 <= 0.5**2
    centers, pitch = ao_closed_loop.actuator_centers_on_pupil(
        diameter=1.0,
        n_actuators=5,
        include_edge=True,
    )
    influences = ao_closed_loop.gaussian_influence_functions(
        x_m,
        y_m,
        pupil,
        centers,
        pitch,
        coupling=0.35,
        normalize_peak=True,
    )

    commands = np.linspace(-3.0, 5.0, len(centers))
    expected_raw = np.nansum(
        commands[:, None, None] * np.nan_to_num(influences),
        axis=0,
    )
    expected_raw = np.where(pupil, expected_raw, np.nan)
    raw = ao_closed_loop.synthesize_dm_phase(
        commands,
        influences,
        pupil,
        remove_mean=False,
    )
    centered = ao_closed_loop.synthesize_dm_phase(
        commands,
        influences,
        pupil,
        remove_mean=True,
    )

    np.testing.assert_array_equal(raw, expected_raw)
    assert float(np.nanmean(centered[pupil])) == pytest.approx(0.0, abs=1.0e-15)
    assert np.all(np.isnan(centered[~pupil]))


@pytest.mark.parametrize(
    ("call", "message"),
    [
        (
            lambda: ao_closed_loop.actuator_centers_on_pupil(n_actuators=1),
            "n_actuators must be >= 2",
        ),
        (
            lambda: ao_closed_loop.actuator_centers_on_pupil(diameter=0.0),
            "diameter must be positive",
        ),
        (
            lambda: ao_closed_loop.gaussian_influence_functions(
                np.zeros((2, 2)),
                np.zeros((2, 2)),
                np.ones((2, 2), dtype=bool),
                np.asarray([[0.0, 0.0]]),
                0.0,
            ),
            "pitch must be positive",
        ),
        (
            lambda: ao_closed_loop.synthesize_dm_phase(
                np.ones(2),
                np.ones((1, 2, 2)),
                np.ones((2, 2), dtype=bool),
            ),
            "Number of commands must match number of influence functions",
        ),
    ],
)
def test_legacy_validation_messages_remain(call: object, message: str) -> None:
    with pytest.raises(ValueError, match=message):
        call()
