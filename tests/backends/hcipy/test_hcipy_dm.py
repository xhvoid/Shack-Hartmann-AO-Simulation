"""AO-REF-015 contracts for the HCIPy deformable-mirror backend.

Every test requires the optional HCIPy dependency and carries the ``hcipy``
marker so native CI selections never execute it.  The module is part of the
portable wheel-smoke bundle, so it imports only the installed package.
"""

from __future__ import annotations

import json
import warnings

import numpy as np
import pytest


hcipy = pytest.importorskip("hcipy")

from shwfs_ao.backends.hcipy import hcipy_version
from shwfs_ao.backends.hcipy.conversion import opd_m_from_wavefront
from shwfs_ao.backends.hcipy.dm import (
    SURFACE_COMMAND_CONVENTION,
    HcipyDmBackend,
    HcipyDmError,
    build_hcipy_deformable_mirror,
    build_hcipy_gaussian_influence_basis,
)
from shwfs_ao.core.protocols import DeformableMirrorModel
from shwfs_ao.core.types import DmCommandVector, DmSynthesisResult
from shwfs_ao.core.wavefront import masked_rms, remove_piston
from shwfs_ao.dm import DMConfig
from shwfs_ao.dm.model import (
    DeformableMirror,
    DmBackend,
    build_native_deformable_mirror,
)


pytestmark = pytest.mark.hcipy


GRID_PIXELS = 33
DIAMETER_M = 2.0
COMMAND_UNIT = "m_opd_equivalent"


def _sampled_pupil(
    pixels: int = GRID_PIXELS,
    diameter_m: float = DIAMETER_M,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    axis = np.linspace(-0.5 * diameter_m, 0.5 * diameter_m, pixels)
    x_m, y_m = np.meshgrid(axis, axis, indexing="xy")
    pupil = np.hypot(x_m, y_m) <= 0.5 * diameter_m
    return x_m, y_m, pupil


def _config(**changes) -> DMConfig:
    values = {
        "telescope_diameter_m": DIAMETER_M,
        "n_actuators_across": 5,
        "coupling_width_pitch": 0.35,
        "stroke_limit_nm": 800.0,
    }
    values.update(changes)
    return DMConfig(**values)


def _hcipy_model(config: DMConfig | None = None) -> DeformableMirror:
    x_m, y_m, pupil = _sampled_pupil()
    return build_hcipy_deformable_mirror(
        x_m,
        y_m,
        pupil,
        _config() if config is None else config,
    )


def _matched_models(
    config: DMConfig | None = None,
) -> tuple[DeformableMirror, DeformableMirror, np.ndarray]:
    x_m, y_m, pupil = _sampled_pupil()
    resolved = _config() if config is None else config
    native = build_native_deformable_mirror(x_m, y_m, pupil, resolved)
    adapted = build_hcipy_deformable_mirror(x_m, y_m, pupil, resolved)
    return native, adapted, pupil


def _backend(config: DMConfig | None = None) -> HcipyDmBackend:
    model = _hcipy_model(config)
    backend = model._backend
    assert isinstance(backend, HcipyDmBackend)
    return backend


def _command_vector(model: DeformableMirror, values: np.ndarray) -> DmCommandVector:
    return DmCommandVector(
        values_opd_m=np.asarray(values, dtype=float),
        actuator_ids=model.actuator_ids,
        command_unit=COMMAND_UNIT,
    )


def _single_command(count: int, index: int, amplitude_m: float) -> np.ndarray:
    values = np.zeros(count, dtype=float)
    values[index] = amplitude_m
    return values


class TestBackendContract:
    def test_backend_implements_the_dm_backend_protocol(self):
        backend = _backend()
        assert isinstance(backend, DmBackend)
        assert backend.backend_name == "hcipy"
        assert len(backend.config_hash) == 64
        assert backend.n_actuators == 13
        assert backend.output_shape == (GRID_PIXELS, GRID_PIXELS)

    def test_wrapper_implements_the_deformable_mirror_model_protocol(self):
        model = _hcipy_model()
        assert isinstance(model, DeformableMirrorModel)
        assert model.backend_name == "hcipy"
        assert model.metadata["backend_name"] == "hcipy"
        assert len(model.metadata["backend_config_hash"]) == 64

    def test_boundary_returns_plain_repository_arrays(self):
        """HCIPy Field/actuator arrays never cross the backend boundary."""

        backend = _backend()
        influences = backend.influence_functions()
        correction = backend.opd_from_commands(
            _single_command(backend.n_actuators, 6, 100.0e-9)
        )
        for array in (influences, correction):
            assert type(array) is np.ndarray
            assert not isinstance(array, hcipy.Field)
            assert array.dtype == np.dtype(float)
            assert not array.flags.writeable
        assert influences.shape == (13, GRID_PIXELS, GRID_PIXELS)
        assert correction.shape == (GRID_PIXELS, GRID_PIXELS)
        json.dumps(_plain_json(backend.metadata))
        assert backend.metadata["hcipy_version"] == hcipy_version()
        assert (
            backend.metadata["surface_command_convention"]
            == SURFACE_COMMAND_CONVENTION
        )

    def test_zero_commands_synthesize_an_exactly_zero_surface(self):
        backend = _backend()
        correction = backend.opd_from_commands(np.zeros(backend.n_actuators))
        assert not np.any(correction)

    def test_single_actuator_response_is_its_influence_map(self):
        backend = _backend()
        amplitude_m = 120.0e-9
        index = 6
        correction = backend.opd_from_commands(
            _single_command(backend.n_actuators, index, amplitude_m)
        )
        expected = amplitude_m * backend.influence_functions()[index]
        assert np.allclose(correction, expected, rtol=1.0e-12, atol=0.0)
        # The in-pupil peak equals the commanded OPD amplitude exactly by the
        # normalize-peak construction of the factory.
        _, _, pupil = _sampled_pupil()
        assert float(np.max(correction[pupil])) == pytest.approx(
            amplitude_m,
            rel=1.0e-12,
        )

    def test_commands_are_validated(self):
        backend = _backend()
        with pytest.raises(HcipyDmError, match="shape"):
            backend.opd_from_commands(np.zeros(backend.n_actuators - 1))
        with pytest.raises(HcipyDmError, match="finite"):
            backend.opd_from_commands(
                np.full(backend.n_actuators, np.nan)
            )
        with pytest.raises(HcipyDmError, match="real numeric"):
            backend.opd_from_commands(
                np.zeros(backend.n_actuators, dtype=complex)
            )


class TestReflectiveFactorAndSign:
    """AO-REF-015 explicit reflective factor-of-two and sign contracts."""

    def test_reflective_surface_factor_is_applied_exactly_once(self):
        """Command → half surface → HCIPy doubles back; net factor is one."""

        x_m, y_m, pupil = _sampled_pupil()
        basis = build_hcipy_gaussian_influence_basis(
            x_m,
            y_m,
            np.array([[0.0, 0.0]]),
            0.5,
            coupling_width_pitch=0.35,
            normalize_peak=True,
            pupil_mask=pupil,
        )
        backend = HcipyDmBackend(basis, x_m, y_m)
        amplitude_m = 100.0e-9
        correction = backend.opd_from_commands(np.array([amplitude_m]))

        # The raw HCIPy mirror doubles its surface into OPD.  Feeding the
        # command directly as a surface amplitude therefore yields exactly
        # twice the adapter's correction: the adapter halves once and HCIPy
        # doubles once, never twice.
        raw_mirror = hcipy.DeformableMirror(basis)
        raw_mirror.actuators = np.array([amplitude_m])
        raw_opd = np.asarray(raw_mirror.opd, dtype=float).reshape(
            correction.shape
        )
        assert np.allclose(correction, raw_opd / 2.0, rtol=1.0e-15, atol=0.0)

        peak = float(np.max(correction))
        assert peak == pytest.approx(amplitude_m, rel=1.0e-12)
        assert peak != pytest.approx(0.5 * amplitude_m, rel=1.0e-3)
        assert peak != pytest.approx(2.0 * amplitude_m, rel=1.0e-3)

    def test_correction_equals_wavefront_opd_after_hcipy_reflection(self):
        """The reported OPD is what a reflected HCIPy wavefront acquires."""

        x_m, y_m, pupil = _sampled_pupil()
        centers = np.array([[0.0, 0.0], [0.5, -0.25]])
        basis = build_hcipy_gaussian_influence_basis(
            x_m,
            y_m,
            centers,
            0.5,
            coupling_width_pitch=0.35,
            normalize_peak=True,
            pupil_mask=pupil,
        )
        backend = HcipyDmBackend(basis, x_m, y_m)
        commands_opd_m = np.array([50.0e-9, -30.0e-9])
        correction = backend.opd_from_commands(commands_opd_m)

        wavelength_m = 500.0e-9
        mirror = hcipy.DeformableMirror(basis)
        mirror.actuators = 0.5 * commands_opd_m
        grid = basis.grid
        flat = hcipy.Wavefront(
            hcipy.Field(np.ones(grid.size, dtype=complex), grid),
            wavelength=wavelength_m,
        )
        full_frame = np.ones(correction.shape, dtype=bool)
        reflected_opd_m = opd_m_from_wavefront(mirror.forward(flat), full_frame)
        assert np.allclose(
            reflected_opd_m,
            correction,
            rtol=0.0,
            atol=1.0e-15 * float(np.max(np.abs(commands_opd_m))),
        )

    def test_positive_command_is_a_positive_correction_to_subtract(self):
        """Single-mode sign test of the shared-loop convention (§3.1.1)."""

        model = _hcipy_model()
        _, _, pupil = _sampled_pupil()
        index = 6
        amplitude_m = 150.0e-9
        atmosphere_opd_m = amplitude_m * np.asarray(model.influence_functions)[index]

        result = model.opd_from_commands(
            _command_vector(
                model,
                _single_command(model.n_actuators, index, amplitude_m),
            )
        )
        correction = result.correction_opd_m
        assert np.all(correction[pupil] >= 0.0)
        assert float(np.max(correction[pupil])) == pytest.approx(
            amplitude_m,
            rel=1.0e-12,
        )

        residual_opd_m = np.where(
            pupil,
            atmosphere_opd_m - correction,
            np.nan,
        )
        residual_rms_m = masked_rms(residual_opd_m, pupil)
        atmosphere_rms_m = masked_rms(
            np.where(pupil, atmosphere_opd_m, np.nan),
            pupil,
        )
        assert residual_rms_m < 1.0e-10 * atmosphere_rms_m


class TestStatelessness:
    """The backend is memoryless: no latency queue, no command history."""

    def test_identical_repeated_calls_return_identical_corrections(self):
        backend = _backend()
        commands = np.linspace(-60.0e-9, 90.0e-9, backend.n_actuators)
        first = backend.opd_from_commands(commands)
        second = backend.opd_from_commands(commands)
        assert first is not second
        assert np.array_equal(first, second)

    def test_synthesis_history_does_not_leak_between_calls(self):
        backend = _backend()
        commands = np.linspace(-60.0e-9, 90.0e-9, backend.n_actuators)
        baseline = backend.opd_from_commands(commands)

        backend.opd_from_commands(
            np.full(backend.n_actuators, 500.0e-9)
        )
        assert np.array_equal(backend.opd_from_commands(commands), baseline)
        assert not np.any(
            backend.opd_from_commands(np.zeros(backend.n_actuators))
        )

    def test_caller_edits_to_the_construction_basis_cannot_change_synthesis(self):
        x_m, y_m, pupil = _sampled_pupil()
        centers = np.array([[-0.5, 0.0], [0.5, 0.0], [0.0, 0.5]])
        basis = build_hcipy_gaussian_influence_basis(
            x_m,
            y_m,
            centers,
            1.0,
            pupil_mask=pupil,
        )
        backend = HcipyDmBackend(basis, x_m, y_m)
        config_hash = backend.config_hash
        influences = backend.influence_functions()

        basis.transformation_matrix[...] *= 2.0

        # Commands never synthesized before, so no HCIPy surface cache hit
        # can hide which matrix the mirror evaluates.
        commands = np.array([60.0e-9, -90.0e-9, 30.0e-9])
        assert backend.config_hash == config_hash
        assert np.array_equal(backend.influence_functions(), influences)
        np.testing.assert_allclose(
            backend.opd_from_commands(commands),
            np.tensordot(commands, influences, axes=1),
            rtol=1.0e-12,
            atol=1.0e-21,
        )

    def test_wrapper_synthesis_is_repeatable_through_the_policy_layer(self):
        model = _hcipy_model()
        commands = _command_vector(
            model,
            np.linspace(-100.0e-9, 100.0e-9, model.n_actuators),
        )
        first = model.opd_from_commands(commands)
        second = model.opd_from_commands(commands)
        assert np.array_equal(first.correction_opd_m, second.correction_opd_m)
        assert np.array_equal(
            first.applied_commands_opd_m,
            second.applied_commands_opd_m,
        )


class TestLinearity:
    def test_synthesis_is_linear_below_stroke(self):
        backend = _backend()
        rng = np.random.default_rng(7)
        first = 100.0e-9 * rng.standard_normal(backend.n_actuators)
        second = 100.0e-9 * rng.standard_normal(backend.n_actuators)

        combined = backend.opd_from_commands(first + second)
        separate = backend.opd_from_commands(first) + backend.opd_from_commands(
            second
        )
        scale_m = float(np.max(np.abs(combined)))
        assert np.allclose(combined, separate, rtol=0.0, atol=1.0e-12 * scale_m)

        doubled = backend.opd_from_commands(2.0 * first)
        assert np.allclose(
            doubled,
            2.0 * backend.opd_from_commands(first),
            rtol=1.0e-12,
            atol=0.0,
        )

    def test_wrapper_applies_commands_unchanged_below_stroke(self):
        model = _hcipy_model()
        values = np.linspace(-200.0e-9, 200.0e-9, model.n_actuators)
        result = model.opd_from_commands(_command_vector(model, values))
        assert result.saturation_fraction == 0.0
        assert np.array_equal(result.applied_commands_opd_m, values)


class TestMatchedNativeComparison:
    def test_actuator_ordering_and_geometry_match_native(self):
        native, adapted, _ = _matched_models()
        assert adapted.actuator_ids == native.actuator_ids
        assert adapted.controllable_actuator_ids == native.controllable_actuator_ids
        assert adapted.n_actuators == native.n_actuators
        assert adapted.actuator_pitch_m == native.actuator_pitch_m
        np.testing.assert_array_equal(
            adapted.actuator_centers_m,
            native.actuator_centers_m,
        )

    def test_gaussian_influence_functions_match_native_inside_the_pupil(self):
        native, adapted, pupil = _matched_models()
        native_influences = np.asarray(native.influence_functions)
        adapted_influences = np.asarray(adapted.influence_functions)

        assert np.allclose(
            adapted_influences[:, pupil],
            native_influences[:, pupil],
            rtol=0.0,
            atol=1.0e-12,
        )
        # Outside the pupil the native construction stores zeros while the
        # HCIPy surface keeps its analytic Gaussian tail; both are finite.
        assert not np.any(native_influences[:, ~pupil])
        assert np.any(adapted_influences[:, ~pupil])
        assert np.all(np.isfinite(adapted_influences))

    def test_matched_synthesis_agrees_inside_the_pupil(self):
        native, adapted, pupil = _matched_models()
        rng = np.random.default_rng(23)
        values = 150.0e-9 * rng.standard_normal(native.n_actuators)
        commands_native = _command_vector(native, values)
        commands_adapted = _command_vector(adapted, values)

        native_correction = native.opd_from_commands(
            commands_native
        ).correction_opd_m
        adapted_correction = adapted.opd_from_commands(
            commands_adapted
        ).correction_opd_m
        scale_m = float(np.max(np.abs(native_correction[pupil])))
        assert np.allclose(
            adapted_correction[pupil],
            native_correction[pupil],
            rtol=0.0,
            atol=1.0e-12 * scale_m,
        )

    def test_common_static_fitting_trend_matches_native(self):
        """Least-squares fitting error falls with actuator density for both
        backends, and the matched backends agree on the residual."""

        x_m, y_m, pupil = _sampled_pupil()
        radius_sq_m2 = x_m**2 + y_m**2
        target = remove_piston(
            np.where(pupil, radius_sq_m2, np.nan),
            pupil,
        )
        target_filled = np.where(pupil, target, 0.0)
        target_filled *= 200.0e-9 / masked_rms(target_filled, pupil)
        target_masked = np.where(pupil, target_filled, np.nan)
        target_rms_m = masked_rms(target_masked, pupil)

        def fitting_residual_rms_m(model: DeformableMirror) -> float:
            design = np.asarray(model.influence_functions)[:, pupil].T
            coefficients, *_ = np.linalg.lstsq(
                design,
                target_filled[pupil],
                rcond=None,
            )
            result = model.opd_from_commands(
                _command_vector(model, coefficients)
            )
            assert result.saturation_fraction == 0.0
            return masked_rms(
                target_masked - result.correction_opd_m,
                pupil,
            )

        residuals: dict[tuple[str, int], float] = {}
        for actuators_across in (4, 7):
            config = _config(
                n_actuators_across=actuators_across,
                coupling_width_pitch=0.45,
                stroke_limit_nm=20000.0,
            )
            native = build_native_deformable_mirror(x_m, y_m, pupil, config)
            adapted = build_hcipy_deformable_mirror(x_m, y_m, pupil, config)
            residuals[("native", actuators_across)] = fitting_residual_rms_m(
                native
            )
            residuals[("hcipy", actuators_across)] = fitting_residual_rms_m(
                adapted
            )

        for backend_name in ("native", "hcipy"):
            coarse = residuals[(backend_name, 4)]
            fine = residuals[(backend_name, 7)]
            assert coarse < target_rms_m
            assert fine < 0.6 * coarse
        for actuators_across in (4, 7):
            assert residuals[("hcipy", actuators_across)] == pytest.approx(
                residuals[("native", actuators_across)],
                rel=1.0e-9,
            )


class TestCanonicalWrapperIntegration:
    def test_wrapper_returns_the_canonical_synthesis_result(self):
        model = _hcipy_model()
        values = np.linspace(-100.0e-9, 100.0e-9, model.n_actuators)
        result = model.opd_from_commands(_command_vector(model, values))

        assert isinstance(result, DmSynthesisResult)
        assert result.actuator_ids == model.actuator_ids
        assert result.command_unit == COMMAND_UNIT
        assert result.config_hash == model.config_hash
        assert result.correction_opd_m.shape == (GRID_PIXELS, GRID_PIXELS)
        assert np.all(np.isfinite(result.correction_opd_m))
        assert not result.correction_opd_m.flags.writeable
        np.testing.assert_array_equal(result.requested_commands_opd_m, values)

    def test_wrapper_owns_stroke_clipping_and_saturation(self):
        model = _hcipy_model(_config(stroke_limit_nm=100.0))
        stroke_m = model.stroke_limit_opd_m
        values = _single_command(model.n_actuators, 6, 5.0 * stroke_m)
        result = model.opd_from_commands(_command_vector(model, values))

        assert bool(result.saturated_mask[6])
        assert result.saturation_fraction == pytest.approx(
            1.0 / model.n_actuators
        )
        assert result.applied_commands_opd_m[6] == pytest.approx(stroke_m)
        _, _, pupil = _sampled_pupil()
        assert float(
            np.max(result.correction_opd_m[pupil])
        ) == pytest.approx(stroke_m, rel=1.0e-12)

    def test_wrapper_owns_dead_and_stuck_actuator_policy(self):
        model = _hcipy_model(
            _config(
                dead_actuator_indices=(6,),
                stuck_actuator_indices=(3,),
                stuck_command_nm=120.0,
            )
        )
        values = _single_command(model.n_actuators, 6, 300.0e-9)
        result = model.opd_from_commands(_command_vector(model, values))

        assert result.applied_commands_opd_m[6] == 0.0
        assert result.applied_commands_opd_m[3] == pytest.approx(120.0e-9)
        expected = 120.0e-9 * np.asarray(model.influence_functions)[3]
        assert np.allclose(
            result.correction_opd_m,
            expected,
            rtol=1.0e-12,
            atol=0.0,
        )

    def test_config_hash_tracks_backend_and_construction_identity(self):
        baseline = _hcipy_model().config_hash
        assert _hcipy_model().config_hash == baseline
        assert (
            _hcipy_model(_config(coupling_width_pitch=0.45)).config_hash
            != baseline
        )
        native, adapted, _ = _matched_models()
        assert adapted.config_hash != native.config_hash
        assert (
            adapted.metadata["backend_config_hash"]
            != native.metadata["backend_config_hash"]
        )


class TestSharedCalibrationAndLoop:
    """The canonical calibration and loop layers accept the HCIPy DM."""

    @staticmethod
    def _shared_assembly():
        from shwfs_ao.wfs.shack_hartmann.geometric import (
            NativeGeometricShackHartmannSensor,
        )
        from shwfs_ao.wfs.shack_hartmann.geometry import (
            build_shack_hartmann_geometry,
        )

        geometry = build_shack_hartmann_geometry(
            telescope_diameter_m=1.0,
            pupil_shape=(16, 16),
            n_lenslets_across=3,
            min_fill_fraction=0.3,
        )
        wfs = NativeGeometricShackHartmannSensor(geometry)
        dm = build_hcipy_deformable_mirror(
            geometry.x_m,
            geometry.y_m,
            geometry.pupil_mask,
            DMConfig(
                telescope_diameter_m=1.0,
                n_actuators_across=3,
                coupling_width_pitch=0.35,
                stroke_limit_nm=250.0,
            ),
        )
        return geometry, wfs, dm

    def test_interaction_matrix_calibration_accepts_the_hcipy_dm(self):
        from shwfs_ao.calibration import (
            DmActuatorProbeBasis,
            calibrate_interaction_matrix,
        )
        from shwfs_ao.core.random import NamedRandomStreams

        _, wfs, dm = self._shared_assembly()
        interaction = calibrate_interaction_matrix(
            DmActuatorProbeBasis(dm),
            wfs,
            amplitude_m=10.0e-9,
            random_streams=NamedRandomStreams(23).scoped("calibration-probe"),
            include_noise=False,
        )
        assert interaction.coordinate_ids == dm.controllable_actuator_ids
        assert interaction.matrix.shape == (
            len(wfs.row_ids),
            dm.n_actuators,
        )
        assert interaction.dm_hash == dm.config_hash
        assert np.any(interaction.matrix)
        assert np.all(np.isfinite(interaction.matrix[interaction.row_valid]))

    def test_common_loop_runs_with_the_hcipy_dm(self):
        from shwfs_ao.backends.native.atmosphere import (
            FrozenFlowAtmosphere,
            FrozenFlowAtmosphereConfig,
        )
        from shwfs_ao.calibration import (
            DmActuatorProbeBasis,
            calibrate_interaction_matrix,
            LeastSquaresReconstructor,
        )
        from shwfs_ao.control import (
            IdentityCommandProjector,
            LeakyIntegratorController,
            LoopConfig,
        )
        from shwfs_ao.control.loop import run_closed_loop
        from shwfs_ao.core.random import NamedRandomStreams

        root_seed = 23
        streams = NamedRandomStreams(root_seed)
        geometry, wfs, dm = self._shared_assembly()
        interaction_matrix = calibrate_interaction_matrix(
            DmActuatorProbeBasis(dm),
            wfs,
            amplitude_m=10.0e-9,
            random_streams=streams.scoped("calibration-probe"),
            include_noise=False,
        )
        pupil = geometry.pupil_geometry
        atmosphere = FrozenFlowAtmosphere(
            FrozenFlowAtmosphereConfig(
                grid_size=pupil.pupil_shape[0],
                delta_m=pupil.pixel_spacing_xy_m[0],
                pupil_diameter_m=pupil.telescope_diameter_m,
                r0_m=0.15,
                outer_scale_m=20.0,
                wind_m_per_s=(5.0, 0.0),
                root_seed=root_seed,
            ),
            pupil_mask=geometry.pupil_mask,
        )

        history = run_closed_loop(
            LoopConfig(
                n_steps=3,
                gain=0.5,
                leak=0.0,
                latency_frames=0,
                frame_rate_hz=500.0,
                root_seed=root_seed,
            ),
            random_streams=streams,
            atmosphere=atmosphere,
            wfs=wfs,
            dm=dm,
            interaction_matrix=interaction_matrix,
            reconstructor=LeastSquaresReconstructor(
                interaction_matrix,
                min_valid_fraction=0.5,
                min_rank=1,
            ),
            command_projector=IdentityCommandProjector(dm.actuator_ids),
            controller=LeakyIntegratorController(
                dm.actuator_ids,
                gain=0.5,
                leak=0.0,
                latency_frames=0,
            ),
            include_noise=False,
            realization_index=0,
        )

        assert history.metadata["backend_names"]["dm"] == "hcipy"
        assert history.metadata["backend_names"]["atmosphere"] == "native"
        assert history.n_steps == 3
        assert np.all(np.isfinite(history.post_update_residual_opd_rms_m))


class TestValidation:
    def test_factory_rejects_invalid_repository_inputs(self):
        x_m, y_m, pupil = _sampled_pupil()
        with pytest.raises(HcipyDmError, match="DMConfig"):
            build_hcipy_deformable_mirror(x_m, y_m, pupil, object())
        with pytest.raises(HcipyDmError, match="gaussian"):
            build_hcipy_deformable_mirror(
                x_m,
                y_m,
                pupil,
                _config(influence_model="pyramid_like"),
            )
        with pytest.raises(HcipyDmError, match="shape"):
            build_hcipy_deformable_mirror(
                x_m,
                y_m,
                np.ones((4, 4), dtype=bool),
                _config(),
            )
        with pytest.raises(HcipyDmError, match="boolean"):
            build_hcipy_deformable_mirror(
                x_m,
                y_m,
                np.ones_like(x_m),
                _config(),
            )
        with pytest.raises(HcipyDmError, match="at least one sample"):
            build_hcipy_deformable_mirror(
                x_m,
                y_m,
                np.zeros_like(pupil),
                _config(),
            )

    def test_basis_builder_validates_before_construction(self):
        x_m, y_m, pupil = _sampled_pupil()
        centers = np.array([[0.0, 0.0]])
        with pytest.raises(HcipyDmError, match="normalize_peak"):
            build_hcipy_gaussian_influence_basis(
                x_m,
                y_m,
                centers,
                0.5,
                normalize_peak=True,
                pupil_mask=None,
            )
        with pytest.raises(HcipyDmError, match="actuator_centers_m"):
            build_hcipy_gaussian_influence_basis(
                x_m,
                y_m,
                np.zeros((2, 3)),
                0.5,
                pupil_mask=pupil,
            )
        with pytest.raises(HcipyDmError, match="actuator_pitch_m"):
            build_hcipy_gaussian_influence_basis(
                x_m,
                y_m,
                centers,
                0.0,
                pupil_mask=pupil,
            )
        with pytest.raises(HcipyDmError, match="coupling_width_pitch"):
            build_hcipy_gaussian_influence_basis(
                x_m,
                y_m,
                centers,
                0.5,
                coupling_width_pitch=-0.35,
                pupil_mask=pupil,
            )

    def test_actuator_without_pupil_support_is_rejected(self):
        x_m, y_m, _ = _sampled_pupil()
        corner_only = np.zeros(x_m.shape, dtype=bool)
        corner_only[:2, :2] = True
        with pytest.raises(HcipyDmError, match="inside"):
            build_hcipy_gaussian_influence_basis(
                x_m,
                y_m,
                np.array([[1.0, 1.0]]),
                0.05,
                coupling_width_pitch=0.35,
                normalize_peak=True,
                pupil_mask=corner_only,
            )

    def test_backend_rejects_non_mode_basis_inputs(self):
        x_m, y_m, _ = _sampled_pupil()
        with pytest.raises(HcipyDmError, match="ModeBasis"):
            HcipyDmBackend(object(), x_m, y_m)

    def test_backend_rejects_a_basis_without_a_grid(self):
        x_m, y_m, _ = _sampled_pupil()
        matrix = np.ones((x_m.size, 2))
        with pytest.raises(HcipyDmError, match="grid"):
            HcipyDmBackend(hcipy.ModeBasis(matrix), x_m, y_m)

    def test_backend_rejects_mismatched_coordinates(self):
        x_m, y_m, pupil = _sampled_pupil()
        basis = build_hcipy_gaussian_influence_basis(
            x_m,
            y_m,
            np.array([[0.0, 0.0]]),
            0.5,
            normalize_peak=True,
            pupil_mask=pupil,
        )
        with pytest.raises(HcipyDmError, match="does not match"):
            HcipyDmBackend(basis, 2.0 * x_m, 2.0 * y_m)

    def test_backend_rejects_non_finite_influence_functions(self):
        x_m, y_m, _ = _sampled_pupil()
        matrix = np.ones((x_m.size, 2))
        matrix[0, 0] = np.nan
        grid = hcipy.CartesianGrid(
            hcipy.RegularCoords(
                [float(x_m[0, 1] - x_m[0, 0])] * 2,
                [x_m.shape[1], x_m.shape[0]],
                [float(x_m[0, 0]), float(y_m[0, 0])],
            )
        )
        with pytest.raises(HcipyDmError, match="finite"):
            HcipyDmBackend(hcipy.ModeBasis(matrix, grid), x_m, y_m)


def _plain_json(value):
    """Recursively convert immutable mappings/tuples to JSON-native types."""

    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    if hasattr(value, "keys"):
        return {str(key): _plain_json(value[key]) for key in value.keys()}
    if isinstance(value, (tuple, list)):
        return [_plain_json(item) for item in value]
    raise AssertionError(
        f"metadata contains a non-JSON-serializable value of type {type(value)!r}"
    )


class TestBuildMemory:
    """The canonical build adopts its private basis and shares immutable stacks.

    At the published 2401-actuator, 384-pixel scale one dense influence stack
    is 2.8 GB, so every redundant full copy matters.  These checks pin that the
    lean build is bit-identical to the defensive-copy path and stays near two
    dense stacks at peak.
    """

    def test_owned_basis_build_is_bit_identical_to_the_defensive_copy_path(self):
        from shwfs_ao.backends.native.dm import square_grid_actuator_layout
        from shwfs_ao.dm.config import actuator_ids_from_grid_indices

        config = _config(n_actuators_across=7)
        x_m, y_m, pupil = _sampled_pupil()
        owned = build_hcipy_deformable_mirror(x_m, y_m, pupil, config)

        centers, pitch_m, grid_indices = square_grid_actuator_layout(
            config.telescope_diameter_m,
            config.n_actuators_across,
            include_edge_actuators=config.include_edge_actuators,
            actuator_margin_fraction=config.actuator_margin_fraction,
        )
        basis = build_hcipy_gaussian_influence_basis(
            x_m,
            y_m,
            centers,
            pitch_m,
            coupling_width_pitch=config.coupling_width_pitch,
            normalize_peak=True,
            pupil_mask=pupil,
        )
        historical_matrix = np.array(basis.transformation_matrix, dtype=float, copy=True)
        copied_backend = HcipyDmBackend(basis, x_m, y_m)
        copied = DeformableMirror(
            config,
            copied_backend,
            actuator_ids=actuator_ids_from_grid_indices(grid_indices),
            actuator_centers_m=centers,
            actuator_pitch_m=pitch_m,
            x_m=x_m,
            y_m=y_m,
            pupil_mask=pupil,
        )

        # The stack the historical code built: a contiguous transposed copy.
        rows, columns = x_m.shape
        historical_stack = np.ascontiguousarray(
            historical_matrix.T.reshape(historical_matrix.shape[1], rows, columns)
        )
        assert owned.influence_functions.tobytes() == historical_stack.tobytes()
        assert copied.influence_functions.tobytes() == historical_stack.tobytes()
        assert owned.backend_config_hash == copied.backend_config_hash
        assert owned.config_hash == copied.config_hash

        owned_backend = owned._backend
        rng = np.random.default_rng(20261015)
        for _ in range(3):
            commands = rng.normal(scale=50.0e-9, size=owned.n_actuators)
            assert (
                owned_backend.opd_from_commands(commands).tobytes()
                == copied_backend.opd_from_commands(commands).tobytes()
            )

    def test_wrapper_and_backend_share_one_immutable_stack(self):
        model = _hcipy_model()
        backend = model._backend
        assert np.shares_memory(model.influence_functions, backend.influence_functions())
        # Every access is a view of the one stack, never a copy, and each view
        # has its own shape: reshaping one cannot reshape the internal stack
        # the calibration probes are built from.
        public = model.influence_functions
        assert np.shares_memory(public, model.influence_functions)
        shape = public.shape
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)  # NumPy >= 2.5
            public.shape = (public.size,)
        assert model.influence_functions.shape == shape
        assert backend.influence_functions().shape == shape
        with pytest.raises(ValueError):
            model.influence_functions.setflags(write=True)

    def test_build_adds_less_than_one_dense_stack_to_hcipys_own_peak(self, monkeypatch):
        """The build's peak stays within one stack of HCIPy's unavoidable peak.

        ``hcipy.make_gaussian_pokes`` alone holds its list of pokes and their
        stacked matrix: 2.8 dense stacks at this size, which the whole build
        now matches (measured 2026-10-15, macOS).  Before the lean build the
        repository added three to five more on top of that: defensive copies of
        the basis, a contiguous transposed stack, a second immutable copy, and
        full canonical copies inside every hash.  Comparing against HCIPy's
        own peak, after a warm-up build so lazy imports are not counted, keeps
        the bound about this repository's copies and not fixed overheads.  The
        hash block is shrunk so it stays as small relative to the stack as the
        16 MiB default is at the published scale.
        """

        import tracemalloc

        from shwfs_ao.backends.hcipy.conversion import hcipy_grid_from_coordinates
        from shwfs_ao.backends.native.dm import square_grid_actuator_layout
        from shwfs_ao.core import hashing as hashing_module

        monkeypatch.setattr(hashing_module, "_HASH_BLOCK_BYTES", 64 * 1024)
        config = _config(n_actuators_across=17)
        x_m, y_m, pupil = _sampled_pupil(pixels=96)
        build_hcipy_deformable_mirror(x_m, y_m, pupil, config)  # warm-up

        centers, pitch_m, _ = square_grid_actuator_layout(
            config.telescope_diameter_m,
            config.n_actuators_across,
            include_edge_actuators=config.include_edge_actuators,
            actuator_margin_fraction=config.actuator_margin_fraction,
        )
        grid = hcipy_grid_from_coordinates(x_m, y_m)
        positions = hcipy.CartesianGrid(
            hcipy.UnstructuredCoords((centers[:, 0].copy(), centers[:, 1].copy()))
        )
        tracemalloc.start()
        try:
            pokes = hcipy.make_gaussian_pokes(
                grid, positions, config.coupling_width_pitch * pitch_m, cutoff=None
            )
            _, hcipy_peak_bytes = tracemalloc.get_traced_memory()
        finally:
            tracemalloc.stop()
        del pokes

        tracemalloc.start()
        try:
            model = build_hcipy_deformable_mirror(x_m, y_m, pupil, config)
            _, build_peak_bytes = tracemalloc.get_traced_memory()
        finally:
            tracemalloc.stop()
        stack_bytes = model.influence_functions.nbytes
        extra = (build_peak_bytes - hcipy_peak_bytes) / stack_bytes
        assert extra < 0.75, (
            f"build peak {build_peak_bytes / stack_bytes:.2f} stacks, HCIPy's own "
            f"{hcipy_peak_bytes / stack_bytes:.2f}: {extra:.2f} stacks added"
        )
