"""Audit physical units across the temporary legacy AO pipeline adapters."""

from __future__ import annotations

import io
from pathlib import Path
import re
import tokenize

import numpy as np
import pytest

from shwfs_ao.core.wavefront import (
    masked_rms,
    opd_to_phase,
    phase_to_opd,
    validate_masked_finite,
)
from shwfs_ao.legacy.dm_model import DMConfig, DMModel, synthesize_dm_opd_nm
from shwfs_ao.legacy.interaction_matrix import PokeMtxResult, tsvd_reconstruct_commands
from shwfs_ao.legacy.phase_screen import (
    fourier_phase_screen,
    phase_to_opd as legacy_phase_to_opd,
)
from shwfs_ao.legacy.psf_tools import phase_for_science_wavelength
from shwfs_ao.legacy.shwfs_detector import lenslet_spot_from_phase


WFS_WAVELENGTH_M = 700.0e-9
SCIENCE_WAVELENGTH_M = 1.4e-6
NM_PER_M = 1.0e9

UNIT_AUDIT_STAGES = (
    "atmosphere output",
    "residual input",
    "WFS input",
    "DM commands/output",
    "reconstructor output",
    "controller history",
    "science propagation input",
)


def _two_coordinate_poke_result() -> PokeMtxResult:
    """Return a diagonal detector-pixel/nm response with an exact inverse."""

    return PokeMtxResult(
        poke_matrix=np.diag([2.0, 4.0]),
        singular_values=np.asarray([4.0, 2.0]),
        kept_modes=2,
        rcond=1.0e-12,
        source_class="synthetic_assumed",
        rank=2,
        calibration_amplitude_nm=1.0,
        controlled_actuator_indices=np.asarray([0, 1], dtype=int),
        valid_subaperture_mask=np.asarray([True]),
        row_valid=np.ones(2, dtype=bool),
        condition_proxy=2.0,
        config_hash="0" * 64,
        calibration_settings={"matrix_unit": "detector_px / nm_OPD_equivalent"},
        rcond_grid=(1.0e-12,),
        rcond_scan_summary=(),
        source_note="Exact two-coordinate unit-audit response.",
    )


def _two_actuator_dm() -> DMModel:
    """Return a two-pixel-basis DM whose piston-removed output is analytic."""

    pupil_mask = np.ones((2, 2), dtype=bool)
    return DMModel(
        config=DMConfig(
            telescope_diameter_m=2.0,
            n_actuators_across=2,
            stroke_limit_nm=100.0,
            source_class="synthetic_assumed",
            source_note="Exact two-actuator unit-audit DM.",
        ),
        x_m=np.asarray([[0.0, 1.0], [0.0, 1.0]]),
        y_m=np.asarray([[0.0, 0.0], [1.0, 1.0]]),
        pupil_mask=pupil_mask,
        actuator_centers_m=np.asarray([[0.0, 0.0], [1.0, 1.0]]),
        actuator_pitch_m=1.0,
        influence_functions=np.asarray(
            [
                [[1.0, 0.0], [0.0, 0.0]],
                [[0.0, 0.0], [0.0, 1.0]],
            ]
        ),
        dead_actuator_mask=np.zeros(2, dtype=bool),
        stuck_actuator_mask=np.zeros(2, dtype=bool),
    )


def test_canonical_opd_m_unit_ledger_across_legacy_adapters() -> None:
    """Every shared stage is OPD metres; old phase/nm units stay at adapters."""

    pupil_mask = np.ones((2, 2), dtype=bool)

    # The temporary native atmosphere still exposes phase radians. Convert that
    # compatibility output immediately to canonical OPD metres.
    expected_atmosphere_opd_m = np.asarray(
        [[100.0, -100.0], [50.0, -50.0]],
        dtype=float,
    ) * 1.0e-9
    atmosphere_phase_rad = opd_to_phase(expected_atmosphere_opd_m, WFS_WAVELENGTH_M)
    atmosphere_output_opd_m = legacy_phase_to_opd(
        atmosphere_phase_rad,
        WFS_WAVELENGTH_M,
    )
    np.testing.assert_allclose(
        atmosphere_output_opd_m,
        expected_atmosphere_opd_m,
        rtol=2.0e-14,
        atol=1.0e-24,
    )

    # The legacy detector interaction matrix is pixels per nm OPD-equivalent.
    # Its reconstructed nanometres are converted exactly once at the adapter.
    reconstruction = tsvd_reconstruct_commands(
        np.asarray([10.0, 12.0]),
        _two_coordinate_poke_result(),
    )
    np.testing.assert_allclose(reconstruction.commands_nm, [5.0, 3.0])
    reconstructor_output_opd_m = reconstruction.commands_nm / NM_PER_M
    np.testing.assert_allclose(
        reconstructor_output_opd_m,
        [5.0e-9, 3.0e-9],
        rtol=2.0e-14,
        atol=1.0e-24,
    )

    # Reproduce the leaky-integrator equation in canonical command metres. The
    # compatibility LoopHistory representation remains nanometres at its edge.
    previous_commands_opd_m = np.asarray([2.0e-9, -4.0e-9])
    gain = 0.5
    leak = 0.1
    requested_commands_opd_m = (
        (1.0 - leak) * previous_commands_opd_m
        + gain * reconstructor_output_opd_m
    )
    controller_history_opd_m = requested_commands_opd_m[None, :]
    legacy_command_history_nm = controller_history_opd_m * NM_PER_M
    np.testing.assert_allclose(
        requested_commands_opd_m,
        [4.3e-9, -2.1e-9],
        rtol=2.0e-14,
        atol=1.0e-24,
    )
    np.testing.assert_allclose(legacy_command_history_nm, [[4.3, -2.1]])

    # The legacy DM accepts and returns nm OPD-equivalent values. Both adapter
    # conversions are explicit, and the canonical correction remains metres.
    dm_model = _two_actuator_dm()
    legacy_requested_commands_nm = requested_commands_opd_m * NM_PER_M
    synthesis = synthesize_dm_opd_nm(
        legacy_requested_commands_nm,
        dm_model,
        remove_piston=True,
    )
    dm_correction_opd_m = synthesis.opd_nm / NM_PER_M
    expected_dm_correction_opd_m = np.asarray(
        [[3.75, -0.55], [-0.55, -2.65]],
        dtype=float,
    ) * 1.0e-9
    np.testing.assert_allclose(
        synthesis.clipped_commands_nm / NM_PER_M,
        requested_commands_opd_m,
        rtol=2.0e-14,
        atol=1.0e-24,
    )
    np.testing.assert_allclose(
        dm_correction_opd_m,
        expected_dm_correction_opd_m,
        rtol=2.0e-14,
        atol=1.0e-24,
    )

    # The residual sign convention is atmosphere minus positive DM correction.
    residual_input_opd_m = atmosphere_output_opd_m - dm_correction_opd_m
    expected_residual_opd_m = np.asarray(
        [[96.25, -99.45], [50.55, -47.35]],
        dtype=float,
    ) * 1.0e-9
    np.testing.assert_allclose(
        residual_input_opd_m,
        expected_residual_opd_m,
        rtol=2.0e-14,
        atol=1.0e-24,
    )

    # Canonical WFS input is the same residual OPD map. The old detector model
    # receives phase only after a wavelength-explicit boundary conversion.
    wfs_input_opd_m = residual_input_opd_m.copy()
    legacy_wfs_phase_rad = opd_to_phase(wfs_input_opd_m, WFS_WAVELENGTH_M)
    np.testing.assert_allclose(
        phase_to_opd(legacy_wfs_phase_rad, WFS_WAVELENGTH_M),
        wfs_input_opd_m,
        rtol=2.0e-14,
        atol=1.0e-24,
    )
    spot = lenslet_spot_from_phase(
        legacy_wfs_phase_rad,
        pupil_mask,
        pad_factor=2,
    )
    assert np.sum(spot) == pytest.approx(1.0, abs=1.0e-15)

    # Science propagation receives residual OPD, never WFS phase. Its legacy
    # phase adapter uses the science wavelength, which is twice the WFS value.
    science_propagation_input_opd_m = residual_input_opd_m.copy()
    legacy_science_phase_rad = phase_for_science_wavelength(
        science_propagation_input_opd_m,
        SCIENCE_WAVELENGTH_M,
    )
    canonical_science_phase_rad = opd_to_phase(
        science_propagation_input_opd_m,
        SCIENCE_WAVELENGTH_M,
    )
    np.testing.assert_allclose(
        legacy_science_phase_rad,
        canonical_science_phase_rad,
        rtol=2.0e-14,
        atol=1.0e-24,
    )
    np.testing.assert_allclose(
        canonical_science_phase_rad,
        0.5 * legacy_wfs_phase_rad,
        rtol=2.0e-14,
        atol=1.0e-24,
    )

    # This named ledger is the acceptance audit: all seven shared stages retain
    # OPD metres. The DM stage records its command vector and correction map.
    canonical_opd_m_ledger = {
        "atmosphere output": {
            "unit": "m_opd",
            "values": (atmosphere_output_opd_m,),
        },
        "residual input": {
            "unit": "m_opd",
            "values": (residual_input_opd_m,),
        },
        "WFS input": {
            "unit": "m_opd",
            "values": (wfs_input_opd_m,),
        },
        "DM commands/output": {
            "unit": "m_opd",
            "values": (
                requested_commands_opd_m,
                dm_correction_opd_m,
            ),
        },
        "reconstructor output": {
            "unit": "m_opd",
            "values": (reconstructor_output_opd_m,),
        },
        "controller history": {
            "unit": "m_opd",
            "values": (controller_history_opd_m,),
        },
        "science propagation input": {
            "unit": "m_opd",
            "values": (science_propagation_input_opd_m,),
        },
    }
    assert tuple(canonical_opd_m_ledger) == UNIT_AUDIT_STAGES
    for stage_record in canonical_opd_m_ledger.values():
        assert stage_record["unit"] == "m_opd"
        for values_opd_m in stage_record["values"]:
            array = np.asarray(values_opd_m)
            assert array.dtype.kind == "f"
            assert np.all(np.isfinite(array))
            # Metre-scale AO wavefronts are safely below this bound. A leaked
            # nanometre-valued array (for example 5.0 instead of 5e-9) fails it.
            assert float(np.max(np.abs(array))) < 1.0e-5


def test_seeded_normalized_atmosphere_converts_to_target_opd_rms_m() -> None:
    """A fixed phase-screen seed and target normalize to the requested OPD RMS."""

    target_opd_rms_m = 100.0e-9
    target_phase_rms_rad = float(
        opd_to_phase(np.asarray(target_opd_rms_m), WFS_WAVELENGTH_M)
    )
    generation_kwargs = {
        "N": 32,
        "delta": 0.05,
        "r0": 0.15,
        "diameter": 1.0,
        "wavelength": WFS_WAVELENGTH_M,
        "seed": 17,
        "target_rms_rad": target_phase_rms_rad,
        "normalize_rms": True,
        "mask_output": True,
    }

    phase_rad, _, _, pupil_mask = fourier_phase_screen(**generation_kwargs)
    repeated_phase_rad, _, _, repeated_mask = fourier_phase_screen(
        **generation_kwargs
    )
    np.testing.assert_allclose(
        repeated_phase_rad,
        phase_rad,
        rtol=0.0,
        atol=0.0,
        equal_nan=True,
    )
    np.testing.assert_array_equal(repeated_mask, pupil_mask)

    atmosphere_opd_m = phase_to_opd(phase_rad, WFS_WAVELENGTH_M)
    validate_masked_finite(
        atmosphere_opd_m,
        pupil_mask,
        "seeded normalized atmosphere OPD",
    )
    assert np.all(np.isnan(atmosphere_opd_m[~pupil_mask]))
    assert masked_rms(atmosphere_opd_m, pupil_mask) == pytest.approx(
        target_opd_rms_m,
        rel=1.0e-12,
        abs=1.0e-20,
    )


_CONSTANT_PI_NAME = re.compile(r"_*(?:[A-Z][A-Z0-9]*_)*PI\Z")


def _logical_lines(
    source_text: str,
) -> "list[tuple[int, list[tokenize.TokenInfo]]]":
    """Group a module's tokens into logical lines (statements).

    A per-physical-line scan misses an inline conversion whose ``pi`` factor
    and ``wavelength`` divisor are wrapped onto separate physical lines.
    Tokenising and regrouping by ``NEWLINE`` restores the statement so the
    two halves are examined together.
    """

    logical: list[tuple[int, list[tokenize.TokenInfo]]] = []
    current: list[tokenize.TokenInfo] = []
    start_line: int | None = None
    reader = io.StringIO(source_text).readline
    for token in tokenize.generate_tokens(reader):
        if token.type == tokenize.NEWLINE:
            if current:
                logical.append((start_line or current[0].start[0], current))
            current = []
            start_line = None
        elif token.type in (
            tokenize.NL,
            tokenize.INDENT,
            tokenize.DEDENT,
            tokenize.ENCODING,
            tokenize.COMMENT,
            tokenize.ENDMARKER,
        ):
            continue
        else:
            if start_line is None:
                start_line = token.start[0]
            current.append(token)
    if current:
        logical.append((start_line or current[0].start[0], current))
    return logical


def _references_pi(tokens: "list[tokenize.TokenInfo]") -> bool:
    for index, token in enumerate(tokens):
        # ``np.pi`` / ``numpy.pi`` / ``math.pi``
        if (
            token.type == tokenize.NAME
            and token.string == "pi"
            and index >= 2
            and tokens[index - 1].string == "."
            and tokens[index - 2].string in ("np", "numpy", "math")
        ):
            return True
        # A precomputed pi multiple such as ``PI``, ``TWO_PI``, or ``_TWO_PI``.
        if token.type == tokenize.NAME and _CONSTANT_PI_NAME.match(token.string):
            return True
    return False


def _references_wavelength(tokens: "list[tokenize.TokenInfo]") -> bool:
    return any(
        token.type == tokenize.NAME and "wavelength" in token.string.lower()
        for token in tokens
    )


def test_canonical_code_routes_phase_opd_conversion_through_core_wavefront():
    """core.wavefront is the sole non-legacy conversion authority (AO-REF-002).

    Any canonical statement combining pi with a wavelength is treated as an
    inline phase/OPD conversion, whether pi is written as ``np.pi``, folded
    into a ``TWO_PI``-style constant, or split across physical lines.  Frozen
    legacy adapters and the isolated experimental PWFS branch keep their
    historical formulas and are the only exclusions besides the authority
    module itself.
    """

    source_root = Path(__file__).resolve().parents[2] / "src" / "shwfs_ao"
    if not source_root.is_dir():
        pytest.skip("source scan requires the repository checkout")

    offenders: list[str] = []
    for path in sorted(source_root.rglob("*.py")):
        relative = path.relative_to(source_root).as_posix()
        if (
            relative == "core/wavefront.py"
            or relative.startswith("legacy/")
            or relative.startswith("experimental/")
        ):
            continue
        source_text = path.read_text(encoding="utf-8")
        for line_number, tokens in _logical_lines(source_text):
            if _references_pi(tokens) and _references_wavelength(tokens):
                offenders.append(f"{relative}:{line_number}")
    assert offenders == []
