"""Closed-loop stability of every published profile's integrator settings.

``run_closed_loop`` measures frame ``k`` against the DM correction ``c[k]``
applied while it is exposed, and ``LeakyIntegratorController`` releases that
residual ``latency_frames = L`` updates later.  Per controlled mode, with the
WFS, reconstructor, command projector and DM acting as a unit-gain plant, the
loop is

    c[k + 1] = (1 - leak) c[k] + gain (phi[k - L] - c[k - L]),

with characteristic polynomial

    z**(L + 1) - (1 - leak) z**L + gain.

With no leak the loop is stable only for ``gain < 2 sin(pi / (2 (2 L + 1)))``,
which is 0.618 at ``L = 2``.  Profiles are pinned by config hash alone, and a
hash cannot tell a stable gain from an unstable one.
"""

from __future__ import annotations

import math

import numpy as np
import pytest
from scipy.signal import lfilter

from shwfs_ao.control.controller import LeakyIntegratorController
from shwfs_ao.core.types import DmCommandVector
from shwfs_ao.io.configs import available_system_profiles, load_system_profile


ACTUATOR_IDS = ("A0",)

# A pole this close to the unit circle decays over 100 frames or more, which is
# no working AO loop even though it is formally stable.
POLE_MARGIN = 0.01

# Published profiles are immutable: an unstable one stays packaged and is
# listed here rather than edited.  The xfails are strict, so a listed profile
# that passes fails the run.
_UNSTABLE_EVIDENCE = (
    "docs/refactor/eso_scao_evidence/hcipy_lenslet_axis_closed_loop_192px.md"
)
KNOWN_UNSTABLE_PROFILES = {
    ("high_order_10m_geometric", 3): (
        "gain 0.65 with latency_frames 2 is above the 0.618 limit "
        f"(max |pole| 1.0147); see {_UNSTABLE_EVIDENCE}"
    ),
    ("high_order_10m_hcipy", 3): (
        "gain 0.65 with latency_frames 2 is above the 0.618 limit "
        f"(max |pole| 1.0147); see {_UNSTABLE_EVIDENCE}"
    ),
}


def _characteristic_polynomial(
    gain: float,
    leak: float,
    latency_frames: int,
) -> np.ndarray:
    """Return ``z**(L+1) - (1-leak) z**L + gain``, highest power first."""

    coefficients = np.zeros(latency_frames + 2, dtype=float)
    coefficients[0] = 1.0
    coefficients[1] = -(1.0 - leak)
    # At L = 0 the gain shares the constant term with the leak term.
    coefficients[-1] += gain
    return coefficients


def _max_pole_modulus(gain: float, leak: float, latency_frames: int) -> float:
    poles = np.roots(_characteristic_polynomial(gain, leak, latency_frames))
    return float(np.max(np.abs(poles)))


def _command(value: float) -> DmCommandVector:
    return DmCommandVector(
        np.asarray([value], dtype=float),
        ACTUATOR_IDS,
        "m_opd_equivalent",
    )


@pytest.mark.parametrize(
    ("gain", "leak", "latency_frames"),
    [
        (0.32, 0.02, 0),
        (0.32, 0.02, 2),
        (0.4, 0.0, 2),
        (0.65, 0.0, 0),
        (0.65, 0.0, 2),
        (0.5, 0.05, 1),
        (0.3, 0.0, 3),
    ],
)
def test_polynomial_is_the_denominator_of_the_controller_loop(
    gain: float,
    leak: float,
    latency_frames: int,
) -> None:
    controller = LeakyIntegratorController(
        ACTUATOR_IDS,
        gain=gain,
        leak=leak,
        latency_frames=latency_frames,
    )
    disturbance = np.random.default_rng(20261015).standard_normal(80)
    correction = np.empty_like(disturbance)
    applied = 0.0
    # The sequencing of run_closed_loop: measure frame k against the correction
    # applied during it, update, and apply the request before frame k + 1.
    for frame, phi in enumerate(disturbance):
        correction[frame] = applied
        requested = controller.update(_command(phi - applied))
        controller.accept_applied_commands(requested)
        applied = float(requested.values_opd_m[0])

    numerator = np.zeros(latency_frames + 2, dtype=float)
    numerator[-1] = gain
    expected = lfilter(
        numerator,
        _characteristic_polynomial(gain, leak, latency_frames),
        disturbance,
    )
    np.testing.assert_allclose(correction, expected, rtol=1e-10, atol=1e-12)


@pytest.mark.parametrize("latency_frames", range(5))
def test_leak_free_stability_limit_matches_the_closed_form(
    latency_frames: int,
) -> None:
    limit = 2.0 * math.sin(math.pi / (2.0 * (2 * latency_frames + 1)))

    assert _max_pole_modulus(limit, 0.0, latency_frames) == pytest.approx(
        1.0, abs=1e-9
    )
    assert _max_pole_modulus(limit * (1.0 - 1e-3), 0.0, latency_frames) < 1.0
    assert _max_pole_modulus(limit * (1.0 + 1e-3), 0.0, latency_frames) > 1.0


def _published_profiles() -> list[object]:
    params: list[object] = []
    for name, version in available_system_profiles():
        reason = KNOWN_UNSTABLE_PROFILES.get((name, version))
        marks = (
            []
            if reason is None
            else [pytest.mark.xfail(raises=AssertionError, strict=True, reason=reason)]
        )
        params.append(
            pytest.param(name, version, id=f"{name}@{version}", marks=marks)
        )
    return params


@pytest.mark.parametrize(("name", "version"), _published_profiles())
def test_published_profile_gain_is_below_its_stability_limit(
    name: str,
    version: int,
) -> None:
    controller = load_system_profile(name, version).controller
    modulus = _max_pole_modulus(
        controller.gain,
        controller.leak,
        controller.latency_frames,
    )

    assert modulus < 1.0 - POLE_MARGIN, (
        f"{name}@{version}: gain {controller.gain}, leak {controller.leak} and "
        f"latency_frames {controller.latency_frames} give a closed-loop pole "
        f"of modulus {modulus:.4f}; it must stay below {1.0 - POLE_MARGIN}."
    )


def test_known_unstable_profiles_are_published() -> None:
    assert set(KNOWN_UNSTABLE_PROFILES) <= set(available_system_profiles())
