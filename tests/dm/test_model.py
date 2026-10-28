"""Repository-policy contracts for the canonical deformable mirror."""

from __future__ import annotations

from dataclasses import fields
from types import MappingProxyType

import numpy as np
import pytest

from shwfs_ao.backends.native.dm import NativeDmBackend
from shwfs_ao.core.protocols import DeformableMirrorModel
from shwfs_ao.core.types import DmCommandVector, DmSynthesisResult
from shwfs_ao.dm import (
    COMMAND_UNIT,
    DMConfig,
    DMConfigError,
    DMModelError,
    DeformableMirror,
    DeformableMirrorError,
    DmBackend,
    DmConfig,
    actuator_id,
    build_deformable_mirror,
    build_native_deformable_mirror,
)


@pytest.fixture
def sampled_pupil() -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    axis = np.linspace(-1.0, 1.0, 33)
    x_m, y_m = np.meshgrid(axis, axis)
    pupil = x_m**2 + y_m**2 <= 1.0
    return x_m, y_m, pupil


def _native_model(
    sampled_pupil: tuple[np.ndarray, np.ndarray, np.ndarray],
    **overrides: object,
) -> DeformableMirror:
    values: dict[str, object] = {
        "telescope_diameter_m": 2.0,
        "n_actuators_across": 5,
        "stroke_limit_nm": 100.0,
    }
    values.update(overrides)
    return build_native_deformable_mirror(*sampled_pupil, DMConfig(**values))


def _commands(model: DeformableMirror, values_opd_m: np.ndarray) -> DmCommandVector:
    return DmCommandVector(values_opd_m, model.actuator_ids, COMMAND_UNIT)


def test_config_preserves_frozen_fields_identity_and_si_conversion() -> None:
    assert DmConfig is DMConfig
    assert DMConfigError is DMModelError
    assert DMModelError.__name__ == "DMModelError"
    assert tuple(field.name for field in fields(DMConfig)) == (
        "telescope_diameter_m",
        "n_actuators_across",
        "influence_model",
        "coupling_width_pitch",
        "stroke_limit_nm",
        "include_edge_actuators",
        "actuator_margin_fraction",
        "dead_actuator_indices",
        "stuck_actuator_indices",
        "stuck_command_nm",
        "source_class",
        "source_note",
    )
    config = DMConfig(stroke_limit_nm=825.0, stuck_command_nm=-17.5)
    assert config.stroke_limit_opd_m == pytest.approx(825.0e-9)
    assert config.stuck_command_opd_m == pytest.approx(-17.5e-9)
    assert config.provenance.source_class == config.source_class
    assert config.provenance.source_note == config.source_note
    assert len(config.config_hash) == 64


@pytest.mark.parametrize(
    "effect",
    [
        {"n_actuators_across": True},
        {"coupling_width_pitch": np.inf},
        {"stroke_limit_nm": 0.0},
        {"stroke_limit_nm": np.nextafter(0.0, 1.0)},
        {"dead_actuator_indices": [1]},
        {"dead_actuator_indices": (1, 1)},
        {"source_class": "private_calibration"},
        {"source_note": ""},
        {"source_note": object()},
        {"source_class": []},
    ],
)
def test_config_rejects_ambiguous_or_invalid_policy(effect: dict[str, object]) -> None:
    with pytest.raises(DMConfigError):
        DMConfig(**effect)


def test_native_factory_has_stable_physical_ids_and_controllable_subset(
    sampled_pupil: tuple[np.ndarray, np.ndarray, np.ndarray],
) -> None:
    model = _native_model(
        sampled_pupil,
        dead_actuator_indices=(1, 6),
        stuck_actuator_indices=(2, 6),
    )

    assert isinstance(model, DeformableMirrorModel)
    assert model.n_actuators == 13
    assert model.actuator_ids == (
        actuator_id(2, 0),
        actuator_id(1, 1),
        actuator_id(2, 1),
        actuator_id(3, 1),
        actuator_id(0, 2),
        actuator_id(1, 2),
        actuator_id(2, 2),
        actuator_id(3, 2),
        actuator_id(4, 2),
        actuator_id(1, 3),
        actuator_id(2, 3),
        actuator_id(3, 3),
        actuator_id(2, 4),
    )
    assert model.controllable_actuator_ids == tuple(
        identifier
        for index, identifier in enumerate(model.actuator_ids)
        if index not in {1, 2, 6}
    )
    assert isinstance(model.metadata, MappingProxyType)
    assert model.metadata["command_unit"] == "m_opd_equivalent"
    assert model.metadata["command_convention"] == (
        "positive_command_produces_positive_correction_opd"
    )
    assert model.actuator_metadata[6]["dead"] is True
    assert model.actuator_metadata[6]["stuck"] is True
    assert model.actuator_metadata[6]["controllable"] is False
    with pytest.raises(TypeError):
        model.actuator_metadata[0]["dead"] = True


def test_factory_alias_and_model_arrays_are_defensively_immutable(
    sampled_pupil: tuple[np.ndarray, np.ndarray, np.ndarray],
) -> None:
    assert build_deformable_mirror is build_native_deformable_mirror
    model = _native_model(sampled_pupil)
    for array in (
        model.influence_functions,
        model.dead_actuator_mask,
        model.stuck_actuator_mask,
        model.actuator_centers_m,
        model.x_m,
        model.y_m,
        model.pupil_mask,
    ):
        assert isinstance(array, np.ndarray)
        assert not array.flags.writeable
        with pytest.raises(ValueError):
            array.setflags(write=True)


def test_below_stroke_synthesis_is_linear_positive_and_raw(
    sampled_pupil: tuple[np.ndarray, np.ndarray, np.ndarray],
) -> None:
    model = _native_model(sampled_pupil)
    first = np.linspace(-8.0e-9, 6.0e-9, model.n_actuators)
    second = np.linspace(4.0e-9, -3.0e-9, model.n_actuators)
    first_result = model.opd_from_commands(_commands(model, first))
    second_result = model.opd_from_commands(_commands(model, second))
    combined = model.opd_from_commands(_commands(model, first + second))

    assert isinstance(combined, DmSynthesisResult)
    np.testing.assert_allclose(
        combined.correction_opd_m,
        first_result.correction_opd_m + second_result.correction_opd_m,
        rtol=2.0e-15,
        atol=2.0e-24,
    )
    np.testing.assert_array_equal(combined.requested_commands_opd_m, first + second)
    np.testing.assert_array_equal(combined.applied_commands_opd_m, first + second)
    assert combined.actuator_ids == model.actuator_ids
    assert combined.command_unit == COMMAND_UNIT
    assert combined.config_hash == model.config_hash
    assert np.all(np.isfinite(combined.correction_opd_m))

    one = np.zeros(model.n_actuators)
    one[6] = 10.0e-9
    positive = model.opd_from_commands(_commands(model, one))
    np.testing.assert_array_equal(
        positive.correction_opd_m,
        10.0e-9 * model.influence_functions[6],
    )
    assert np.max(positive.correction_opd_m) == pytest.approx(10.0e-9)
    assert float(np.mean(positive.correction_opd_m[model.pupil_mask])) > 0.0


def test_stroke_boundary_diagnostics_and_fault_precedence_are_exact(
    sampled_pupil: tuple[np.ndarray, np.ndarray, np.ndarray],
) -> None:
    model = _native_model(
        sampled_pupil,
        stroke_limit_nm=100.0,
        dead_actuator_indices=(1, 3),
        stuck_actuator_indices=(2, 3),
        stuck_command_nm=250.0,
    )
    stroke = model.stroke_limit_opd_m
    values = np.zeros(model.n_actuators)
    values[:5] = [
        stroke,
        np.nextafter(stroke, np.inf),
        -1.5 * stroke,
        17.0e-9,
        -stroke,
    ]
    result = model.opd_from_commands(_commands(model, values))

    np.testing.assert_array_equal(result.requested_commands_opd_m, values)
    np.testing.assert_allclose(
        result.applied_commands_opd_m[:5],
        np.asarray([stroke, 0.0, stroke, stroke, -stroke]),
        rtol=0.0,
        atol=1.0e-24,
    )
    np.testing.assert_array_equal(
        result.saturated_mask[:5],
        np.asarray([False, True, True, False, False]),
    )
    assert result.saturation_fraction == pytest.approx(2.0 / model.n_actuators)
    # Index 3 is both dead and stuck: the stuck policy wins.  Its clipped
    # preset does not create a saturation diagnostic of its own.
    assert result.applied_commands_opd_m[3] == pytest.approx(100.0e-9)
    assert not result.saturated_mask[3]


def test_model_requires_exact_command_type_ids_and_unit(
    sampled_pupil: tuple[np.ndarray, np.ndarray, np.ndarray],
) -> None:
    model = _native_model(sampled_pupil)
    values = np.zeros(model.n_actuators)
    with pytest.raises(DeformableMirrorError, match="DmCommandVector"):
        model.opd_from_commands(values)  # type: ignore[arg-type]
    with pytest.raises(DeformableMirrorError, match="exactly match"):
        model.opd_from_commands(
            DmCommandVector(values, tuple(reversed(model.actuator_ids)), COMMAND_UNIT)
        )
    with pytest.raises(ValueError, match="command_unit"):
        DmCommandVector(values, model.actuator_ids, "m_surface")  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="finite"):
        DmCommandVector(
            np.full(model.n_actuators, np.nan),
            model.actuator_ids,
            COMMAND_UNIT,
        )


def test_reflective_surface_factor_of_two_is_applied_exactly_once_at_boundary() -> None:
    class ReflectiveBoundaryBackend:
        def __init__(self) -> None:
            self.surface_displacement_m: np.ndarray | None = None

        def influence_functions(self) -> np.ndarray:
            return np.asarray([[[0.0, 1.0], [0.25, 0.0]]])

        def opd_from_commands(self, commands_opd_m: np.ndarray) -> np.ndarray:
            # A physical reflective primitive accepts half the canonical OPD
            # amplitude.  Reflection creates twice that surface motion in OPD.
            self.surface_displacement_m = commands_opd_m / 2.0
            reflected_opd_m = 2.0 * self.surface_displacement_m
            return np.sum(
                reflected_opd_m[:, None, None] * self.influence_functions(),
                axis=0,
            )

    backend = ReflectiveBoundaryBackend()
    model = DeformableMirror(
        DMConfig(stroke_limit_nm=100.0),
        backend,
        actuator_ids=("reflective-actuator",),
    )
    command = np.asarray([10.0e-9])
    result = model.opd_from_commands(_commands(model, command))

    assert backend.surface_displacement_m is not None
    assert backend.surface_displacement_m[0] == pytest.approx(5.0e-9)
    assert np.max(result.correction_opd_m) == pytest.approx(10.0e-9)


class _ArrayBackend:
    def __init__(self, influences: object, output: object | None = None) -> None:
        self.influences = influences
        self.output = output
        self.received: np.ndarray | None = None

    def influence_functions(self) -> np.ndarray:
        return self.influences  # type: ignore[return-value]

    def opd_from_commands(self, commands_opd_m: np.ndarray) -> np.ndarray:
        self.received = np.array(commands_opd_m, copy=True)
        if self.output is not None:
            return self.output  # type: ignore[return-value]
        return np.sum(
            commands_opd_m[:, None, None] * np.asarray(self.influences),
            axis=0,
        )


class _BrokenBackendName(_ArrayBackend):
    @property
    def backend_name(self) -> str:
        raise RuntimeError("unreadable backend name")


class _BrokenBackendHash(_ArrayBackend):
    @property
    def config_hash(self) -> str:
        raise RuntimeError("unreadable backend hash")


@pytest.mark.parametrize(
    ("influences", "message"),
    [
        (np.ones((2, 3)), "positive shape"),
        (np.asarray([[[np.nan]]]), "finite"),
        (np.asarray([[[np.inf]]]), "finite"),
        ([np.ones((2, 2))], "numpy.ndarray"),
    ],
)
def test_model_rejects_malformed_backend_influences(
    influences: object,
    message: str,
) -> None:
    with pytest.raises(DeformableMirrorError, match=message):
        DeformableMirror(
            DMConfig(),
            _ArrayBackend(influences),
            actuator_ids=("actuator",),
        )


def test_model_rejects_complex_geometry_instead_of_truncating_it() -> None:
    backend = NativeDmBackend(np.ones((1, 2, 2)))
    with pytest.raises(DeformableMirrorError, match="real numeric"):
        DeformableMirror(
            DMConfig(),
            backend,
            actuator_ids=("a",),
            actuator_centers_m=np.asarray([[1.0 + 2.0j, 0.0]]),
            actuator_pitch_m=1.0,
        )
    with pytest.raises(DeformableMirrorError, match="real numeric"):
        DeformableMirror(
            DMConfig(),
            backend,
            actuator_ids=("a",),
            x_m=np.ones((2, 2), dtype=complex),
            y_m=np.ones((2, 2)),
            pupil_mask=np.ones((2, 2), dtype=bool),
        )


@pytest.mark.parametrize("backend_type", [_BrokenBackendName, _BrokenBackendHash])
def test_model_wraps_optional_backend_metadata_failures(
    backend_type: type[_ArrayBackend],
) -> None:
    with pytest.raises(DeformableMirrorError, match="could not be read"):
        DeformableMirror(
            DMConfig(),
            backend_type(np.ones((1, 2, 2))),
            actuator_ids=("a",),
        )


@pytest.mark.parametrize(
    ("output", "message"),
    [
        (np.ones((3, 2)), "shape"),
        (np.asarray([[np.nan, 0.0], [0.0, 0.0]]), "finite"),
        (np.asarray([[np.inf, 0.0], [0.0, 0.0]]), "finite"),
        ([[0.0, 0.0], [0.0, 0.0]], "numpy.ndarray"),
    ],
)
def test_model_rejects_malformed_backend_correction(
    output: object,
    message: str,
) -> None:
    backend = _ArrayBackend(np.ones((1, 2, 2)), output)
    model = DeformableMirror(
        DMConfig(),
        backend,
        actuator_ids=("actuator",),
    )
    with pytest.raises(DeformableMirrorError, match=message):
        model.opd_from_commands(
            DmCommandVector(np.zeros(1), model.actuator_ids, COMMAND_UNIT)
        )


def test_applied_vector_is_exact_backend_input() -> None:
    backend = _ArrayBackend(np.ones((3, 2, 2)))
    model = DeformableMirror(
        DMConfig(
            stroke_limit_nm=10.0,
            dead_actuator_indices=(1,),
            stuck_actuator_indices=(2,),
            stuck_command_nm=-4.0,
        ),
        backend,
        actuator_ids=("a", "b", "c"),
    )
    requested = np.asarray([20.0, 5.0, 9.0]) * 1.0e-9
    result = model.opd_from_commands(_commands(model, requested))

    np.testing.assert_array_equal(backend.received, result.applied_commands_opd_m)
    np.testing.assert_allclose(
        result.applied_commands_opd_m,
        np.asarray([10.0, 0.0, -4.0]) * 1.0e-9,
        rtol=0.0,
        atol=1.0e-24,
    )


def test_complete_model_hash_is_stable_and_sensitive(
    sampled_pupil: tuple[np.ndarray, np.ndarray, np.ndarray],
) -> None:
    first = _native_model(sampled_pupil)
    identical = _native_model(sampled_pupil)
    changed_fault = _native_model(sampled_pupil, dead_actuator_indices=(0,))
    changed_provenance = _native_model(sampled_pupil, source_note="changed source")
    assert first.config_hash == identical.config_hash
    assert first.config_hash != changed_fault.config_hash
    assert first.config_hash != changed_provenance.config_hash

    influences = np.ones((1, 2, 2))
    changed_influences = np.array(influences, copy=True)
    changed_influences[0, 0, 0] += 1.0e-12
    base = DeformableMirror(
        DMConfig(),
        NativeDmBackend(influences),
        actuator_ids=("a",),
        actuator_centers_m=np.asarray([[0.0, 0.0]]),
        actuator_pitch_m=1.0,
    )
    changed_backend = DeformableMirror(
        DMConfig(),
        NativeDmBackend(changed_influences),
        actuator_ids=("a",),
        actuator_centers_m=np.asarray([[0.0, 0.0]]),
        actuator_pitch_m=1.0,
    )
    shifted_center = DeformableMirror(
        DMConfig(),
        NativeDmBackend(influences),
        actuator_ids=("a",),
        actuator_centers_m=np.asarray([[1.0e-12, 0.0]]),
        actuator_pitch_m=1.0,
    )
    assert base.config_hash != changed_backend.config_hash
    assert base.config_hash != shifted_center.config_hash
