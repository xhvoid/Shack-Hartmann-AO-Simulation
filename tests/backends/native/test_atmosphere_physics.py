"""Physical validation of the native atmosphere against turbulence theory.

Every other atmosphere test in this repository checks the generator against
itself: that a renormalizer normalized, that a formula restates itself, that a
frozen realization did not drift.  Those are necessary, and they are not
sufficient — the historical ``legacy_fourier_v1`` spectrum passes all of them
while being wrong by eight orders of magnitude in absolute amplitude and by a
factor of three to ten in its modal distribution.

The tests here compare generated screens to closed-form turbulence results:
the Kolmogorov structure function ``6.88 (r/r0)**(5/3)``, the Noll
piston-removed aperture variance, and the independently implemented HCIPy von
Karman backend.  They are what would have caught the v1 defects.
"""

from __future__ import annotations

from dataclasses import replace

import math

import numpy as np
import pytest

from shwfs_ao.backends.native.atmosphere import (
    SPECTRUM_LEGACY_V1,
    SPECTRUM_SUBHARMONIC_V2,
    TRANSLATION_FOURIER_SUBPIXEL_V2,
    TRANSLATION_LEGACY_V1,
    FrozenFlowAtmosphere,
    FrozenFlowAtmosphereConfig,
    NativeAtmosphereError,
    _cell_integrated_power,
    subharmonic_von_karman_phase_realization,
    von_karman_piston_removed_variance_rad2,
)


KOLMOGOROV_STRUCTURE_COEFFICIENT = 6.88
NOLL_PISTON_REMOVED_COEFFICIENT = 1.0299


def _structure_function(screen: np.ndarray, separations: np.ndarray) -> np.ndarray:
    """Mean-square column difference at each pixel separation."""

    return np.array(
        [float(np.mean((screen[:, s:] - screen[:, :-s]) ** 2)) for s in separations],
        dtype=float,
    )


# --------------------------------------------------------------------------
# The analytic aperture variance
# --------------------------------------------------------------------------


def test_aperture_variance_reduces_to_the_noll_kolmogorov_limit() -> None:
    """As the outer scale grows the integral must return Noll's coefficient."""

    diameter, r0 = 2.0, 0.15
    kolmogorov = NOLL_PISTON_REMOVED_COEFFICIENT * (diameter / r0) ** (5.0 / 3.0)

    variance = von_karman_piston_removed_variance_rad2(diameter, r0, 1.0e9)

    assert variance == pytest.approx(kolmogorov, rel=0.01)


def test_aperture_variance_falls_as_the_outer_scale_shrinks() -> None:
    """A finite outer scale removes power; this is what v1's target ignores."""

    diameter, r0 = 2.0, 0.15
    unbounded = von_karman_piston_removed_variance_rad2(diameter, r0, 1.0e9)
    bounded = [
        von_karman_piston_removed_variance_rad2(diameter, r0, outer_scale)
        for outer_scale in (100.0, 25.0, 10.0)
    ]

    assert bounded == sorted(bounded, reverse=True)  # monotone in outer scale
    assert all(value < unbounded for value in bounded)
    # At the shipped L0 = 25 m the correction is a factor of two in variance,
    # so applying the Kolmogorov coefficient there is not a rounding error.
    assert bounded[1] < 0.6 * unbounded


def test_aperture_variance_rejects_non_physical_inputs() -> None:
    with pytest.raises(NativeAtmosphereError):
        von_karman_piston_removed_variance_rad2(0.0, 0.15, 25.0)
    with pytest.raises(NativeAtmosphereError):
        von_karman_piston_removed_variance_rad2(2.0, -0.15, 25.0)


# --------------------------------------------------------------------------
# Absolute normalization of the v2 spectral synthesis
# --------------------------------------------------------------------------


def test_v2_synthesis_carries_the_cell_integrated_psd_variance() -> None:
    """The ensemble point second moment equals the sampled PSD integral.

    This is the exact statement the v1 generator violates: it omits the
    ``N**2 * df`` factor, so its realizations carry essentially none of this
    variance.  The expectation here is the sum of the per-cell integrals, not
    ``Phi(f) * df**2``, because the generator integrates rather than samples.
    """

    size, delta, r0, outer_scale = 128, 0.02, 0.15, 1.0e6
    frequency_step = 1.0 / (size * delta)
    frequencies = np.fft.fftfreq(size, d=delta)
    fx, fy = np.meshgrid(frequencies, frequencies)
    cell_power = _cell_integrated_power(fx, fy, frequency_step, r0, outer_scale)
    cell_power[0, 0] = 0.0
    expected = float(np.sum(cell_power))

    # The total is dominated by a handful of low-frequency modes, so the
    # per-realization estimator is heavy-tailed; average many draws.
    rng = np.random.default_rng(20260819)
    variance = float(
        np.mean(
            [
                np.mean(subharmonic_von_karman_phase_realization(
                    size, delta, r0, outer_scale, rng=rng, subharmonic_depth=0
                ) ** 2)
                for _ in range(200)
            ]
        )
    )

    assert variance == pytest.approx(expected, rel=0.10)


def test_v1_synthesis_is_not_absolutely_normalized() -> None:
    """Pin the known v1 defect so a future 'fix' cannot land silently.

    If this test ever fails because the ratio approaches one, the legacy
    generator has been changed and every accepted baseline is invalid.
    """

    from shwfs_ao.backends.native.atmosphere import (
        fourier_von_karman_phase_realization,
    )

    size, delta, r0, outer_scale = 128, 0.02, 0.15, 1.0e6
    rng = np.random.default_rng(4)
    legacy = fourier_von_karman_phase_realization(
        size, delta, r0, outer_scale, rng=rng
    )
    rng = np.random.default_rng(4)
    corrected = subharmonic_von_karman_phase_realization(
        size, delta, r0, outer_scale, rng=rng, subharmonic_depth=0
    )

    # The corrected screen is larger by roughly the omitted N**2 * df factor;
    # the exact ratio also carries the cell-integration correction, so this
    # asserts the order of magnitude rather than a precise value.
    ratio = float(np.std(corrected) / np.std(legacy))
    assert 0.3 * (size / delta) < ratio < 3.0 * (size / delta)


# --------------------------------------------------------------------------
# Structure function against Kolmogorov theory
# --------------------------------------------------------------------------


@pytest.mark.slow
def test_v2_structure_function_follows_the_kolmogorov_five_thirds_law() -> None:
    """``D(r) = 6.88 (r/r0)**(5/3)`` over nearly two decades of separation.

    An effectively infinite outer scale requires deeper low-frequency
    coverage than the shipped finite-L0=25m configuration: three levels
    omit about17% at the largest separation here, nine reduce that cutoff
    error below3%. The smallest separation also loses about7% to the
    Nyquist band limit. Resolve both before testing against continuum theory.
    """

    size, delta, r0, outer_scale = 512, 0.02, 0.15, 1.0e6
    separations = np.array([1, 2, 4, 8, 16, 32, 64])
    radii = separations * delta
    theory = KOLMOGOROV_STRUCTURE_COEFFICIENT * (radii / r0) ** (5.0 / 3.0)

    rng = np.random.default_rng(20260819)
    measured = np.zeros(separations.size)
    realizations = 32
    for _ in range(realizations):
        screen = subharmonic_von_karman_phase_realization(
            size, delta, r0, outer_scale, rng=rng, subharmonic_depth=9
        )
        measured += _structure_function(screen, separations)
    measured /= realizations

    ratio = measured / theory
    assert np.all(ratio > 0.85), f"structure function too weak: {ratio}"
    assert np.all(ratio < 1.15), f"structure function too strong: {ratio}"

    slope = float(np.polyfit(np.log(radii), np.log(measured), 1)[0])
    assert slope == pytest.approx(5.0 / 3.0, abs=0.05)


@pytest.mark.slow
def test_v1_structure_function_does_not_follow_the_five_thirds_law() -> None:
    """The discriminating check v1 fails, recorded so the gap is explicit."""

    from shwfs_ao.backends.native.atmosphere import (
        fourier_von_karman_phase_realization,
    )

    size, delta, r0, outer_scale = 512, 0.02, 0.15, 1.0e6
    separations = np.array([1, 4, 16, 64])
    radii = separations * delta

    rng = np.random.default_rng(20260819)
    measured = np.zeros(separations.size)
    for _ in range(4):
        screen = fourier_von_karman_phase_realization(
            size, delta, r0, outer_scale, rng=rng
        )
        measured += _structure_function(screen, separations)
    measured /= 4.0

    slope = float(np.polyfit(np.log(radii), np.log(measured), 1)[0])
    # Measured at about 1.47 rather than 1.667: the low frequencies are absent.
    assert slope < 1.55


# --------------------------------------------------------------------------
# Agreement with the independent HCIPy backend
# --------------------------------------------------------------------------


def _zernike_variance_fraction(
    screens: list[np.ndarray],
    pupil_mask: np.ndarray,
    diameter: float,
    delta: float,
) -> tuple[float, float]:
    """Return (variance fraction in the first 14 Zernikes, total variance)."""

    from shwfs_ao.legacy.zernike import generate_zernike_modes

    size = pupil_mask.shape[0]
    coordinates = (np.arange(size, dtype=float) - size // 2) * delta
    x_m, y_m = np.meshgrid(coordinates, coordinates)
    radius = np.hypot(x_m, y_m)
    rho = np.where(pupil_mask, radius / (diameter / 2.0), 0.0)
    theta = np.arctan2(y_m, x_m)
    modes = generate_zernike_modes(
        rho, theta, pupil_mask, max_radial_order=4, include_piston=False
    )
    basis = np.array(
        [np.nan_to_num(mode, nan=0.0)[pupil_mask] for mode in modes.values()]
    )
    pixels = int(pupil_mask.sum())
    inverse_gram = np.linalg.pinv(basis @ basis.T / pixels)

    variance = np.zeros(basis.shape[0])
    total = 0.0
    for screen in screens:
        values = np.nan_to_num(screen, nan=0.0)[pupil_mask]
        values = values - values.mean()
        variance += (inverse_gram @ (basis @ values / pixels)) ** 2
        total += float(np.mean(values**2))
    variance /= len(screens)
    total /= len(screens)
    return float(variance[:14].sum() / total), total


@pytest.mark.hcipy
@pytest.mark.slow
def test_v2_matches_the_hcipy_backend_in_total_rms_and_modal_content() -> None:
    """Two independent implementations of the same physics must agree.

    This is the acceptance criterion the cross-backend suite is missing: it
    compares the backends to *each other* rather than holding both against a
    band wide enough to admit either.  Under v1 the total RMS ratio is about
    1.5 and the low-order variance fraction is 0.78 against HCIPy's 0.95.
    """

    pytest.importorskip("hcipy")
    from shwfs_ao.backends.hcipy.atmosphere import (
        HcipyAtmosphereConfig,
        HcipyVonKarmanAtmosphere,
    )
    from shwfs_ao.backends.native.factory import NativeScaoComponentFactory

    diameter, pixels, r0, outer_scale = 2.0, 128, 0.15, 25.0
    delta = diameter / pixels
    geometry = NativeScaoComponentFactory().build_geometry(
        telescope_diameter_m=diameter,
        pupil_pixels=pixels,
        lenslets_across=8,
        min_fill_fraction=0.5,
        central_obstruction_ratio=0.0,
        spider_width_m=0.0,
    )
    mask = geometry.pupil_mask
    realizations = 40

    native_screens = []
    for index in range(realizations):
        model = FrozenFlowAtmosphere(
            FrozenFlowAtmosphereConfig(
                grid_size=pixels,
                delta_m=delta,
                pupil_diameter_m=diameter,
                r0_m=r0,
                outer_scale_m=outer_scale,
                wind_m_per_s=(0.0, 0.0),
                root_seed=5000 + index,
                normalize_rms=False,
                spectrum_model=SPECTRUM_SUBHARMONIC_V2,
            ),
            pupil_mask=mask,
        )
        model.reset(realization_index=0)
        native_screens.append(np.asarray(model.opd_at(0.0), dtype=float))

    hcipy_screens = []
    for index in range(realizations):
        model = HcipyVonKarmanAtmosphere(
            HcipyAtmosphereConfig.single_layer(
                r0_m=r0,
                outer_scale_m=outer_scale,
                wind_m_per_s=(0.0, 0.0),
                root_seed=5000 + index,
            ),
            geometry.pupil_geometry,
            pupil_mask=mask,
        )
        model.reset(realization_index=0)
        hcipy_screens.append(np.asarray(model.opd_at(0.0), dtype=float))

    native_fraction, native_total = _zernike_variance_fraction(
        native_screens, mask, diameter, delta
    )
    hcipy_fraction, hcipy_total = _zernike_variance_fraction(
        hcipy_screens, mask, diameter, delta
    )

    rms_ratio = math.sqrt(native_total / hcipy_total)
    assert rms_ratio == pytest.approx(1.0, abs=0.15), (
        f"native/HCIPy total RMS ratio {rms_ratio:.3f} is outside finite-sample "
        "scatter; the two spectra no longer describe the same atmosphere."
    )
    assert native_fraction == pytest.approx(hcipy_fraction, abs=0.05), (
        f"low-order variance fraction {native_fraction:.3f} does not match "
        f"HCIPy's {hcipy_fraction:.3f}: the modal distributions disagree."
    )


# --------------------------------------------------------------------------
# Sub-pixel frozen flow
# --------------------------------------------------------------------------


def _flow_config(**changes) -> FrozenFlowAtmosphereConfig:
    values = {
        "grid_size": 64,
        "delta_m": 0.03,
        "pupil_diameter_m": 1.5,
        "r0_m": 0.15,
        "outer_scale_m": 25.0,
        "wind_m_per_s": (9.0, 0.0),
        "root_seed": 17,
    }
    values.update(changes)
    return FrozenFlowAtmosphereConfig(**values)


def test_fourier_translation_reproduces_roll_at_whole_pixel_offsets() -> None:
    """The sub-pixel model must be a strict generalization, not a new screen."""

    legacy = FrozenFlowAtmosphere(_flow_config())
    subpixel = FrozenFlowAtmosphere(
        _flow_config(translation_model=TRANSLATION_FOURIER_SUBPIXEL_V2)
    )
    delta, (wind_x, _) = legacy.config.delta_m, legacy.config.wind_m_per_s

    for whole_pixels in (0, 1, 3, 7):
        legacy.reset(realization_index=0)
        subpixel.reset(realization_index=0)
        time_s = whole_pixels * delta / wind_x
        rolled = legacy.opd_at(time_s)
        shifted = subpixel.opd_at(time_s)
        finite = np.isfinite(rolled)
        assert np.abs(rolled[finite] - shifted[finite]).max() < 1.0e-18


def test_fourier_translation_removes_the_temporal_staircase() -> None:
    """Sub-pixel-per-frame wind must still advance the atmosphere every frame.

    With the integer-roll model a 10 m/s wind on a 1 kHz loop over 0.0385 m
    pixels leaves consecutive frames byte-identical about three quarters of
    the time, which silently removes the temporal error term from any loop
    study built on it.
    """

    frame_rate_hz, frames = 1000.0, 12
    legacy = FrozenFlowAtmosphere(_flow_config(wind_m_per_s=(10.0, 0.0)))
    subpixel = FrozenFlowAtmosphere(
        _flow_config(
            wind_m_per_s=(10.0, 0.0),
            translation_model=TRANSLATION_FOURIER_SUBPIXEL_V2,
        )
    )

    def distinct_frames(model: FrozenFlowAtmosphere) -> int:
        model.reset(realization_index=0)
        finite = np.isfinite(model.opd_at(0.0))
        model.reset(realization_index=0)
        keys = {
            np.asarray(model.opd_at(index / frame_rate_hz))[finite].tobytes()
            for index in range(frames)
        }
        return len(keys)

    assert distinct_frames(legacy) < frames
    assert distinct_frames(subpixel) == frames


def test_fourier_translation_preserves_screen_statistics() -> None:
    """An exact rigid translation must not damp the screen it moves."""

    model = FrozenFlowAtmosphere(
        _flow_config(
            wind_m_per_s=(10.0, 3.0),
            translation_model=TRANSLATION_FOURIER_SUBPIXEL_V2,
        )
    )
    model.reset(realization_index=0)
    first = model.opd_at(0.0)
    finite = np.isfinite(first)
    reference = float(np.std(first[finite]))

    for index in range(1, 20):
        frame = model.opd_at(index * 1.0e-3)
        assert float(np.std(frame[finite])) == pytest.approx(reference, rel=0.25)
        assert np.all(np.isfinite(frame[finite]))


# --------------------------------------------------------------------------
# Identity and configuration contracts
# --------------------------------------------------------------------------


def test_legacy_selectors_leave_the_config_hash_untouched() -> None:
    """Existing accepted baselines must survive the arrival of the v2 models.

    The two selector fields are omitted from the hash payload whenever they
    hold their legacy values, so every configuration written before they
    existed hashes exactly as it did.
    """

    explicit = FrozenFlowAtmosphere(
        _flow_config(
            spectrum_model=SPECTRUM_LEGACY_V1,
            translation_model=TRANSLATION_LEGACY_V1,
        )
    )
    implicit = FrozenFlowAtmosphere(_flow_config())

    assert explicit.config_hash == implicit.config_hash
    assert implicit.config.uses_legacy_numerics is True
    assert (
        implicit.metadata["frozen_flow_discretization"]
        == "nearest_integer_periodic_numpy_roll"
    )


@pytest.mark.parametrize(
    "changes",
    [
        {"spectrum_model": SPECTRUM_SUBHARMONIC_V2},
        {"translation_model": TRANSLATION_FOURIER_SUBPIXEL_V2},
        {
            "spectrum_model": SPECTRUM_SUBHARMONIC_V2,
            "translation_model": TRANSLATION_FOURIER_SUBPIXEL_V2,
        },
    ],
)
def test_v2_selectors_change_the_recorded_identity(changes: dict) -> None:
    """Provenance must distinguish a v2 run from a v1 run."""

    legacy = FrozenFlowAtmosphere(_flow_config())
    upgraded = FrozenFlowAtmosphere(_flow_config(**changes))

    assert upgraded.config_hash != legacy.config_hash
    assert upgraded.config.uses_legacy_numerics is False
    for key, value in changes.items():
        assert upgraded.metadata[key] == value


def test_v2_spectrum_records_that_it_is_absolutely_normalized() -> None:
    model = FrozenFlowAtmosphere(
        _flow_config(spectrum_model=SPECTRUM_SUBHARMONIC_V2, normalize_rms=False)
    )

    assert model.metadata["absolutely_normalized"] is True
    assert model.metadata["raw_spectrum_absolutely_normalized"] is True
    assert model.metadata["realization_rms_rescaled"] is False
    assert model.metadata["spectral_quadrature_scheme"] == "midpoint_frequency_quadrature_v1"
    assert model.metadata["spectral_quadrature_subsamples"] == 4
    assert model.metadata["subharmonic_depth"] == 3


def test_v2_default_rms_target_honours_the_outer_scale() -> None:
    """With ``normalize_rms`` the v2 target must be the von Karman variance."""

    bounded = FrozenFlowAtmosphere(
        _flow_config(
            spectrum_model=SPECTRUM_SUBHARMONIC_V2,
            outer_scale_m=25.0,
            normalize_rms=True,
        )
    )
    legacy = FrozenFlowAtmosphere(_flow_config(outer_scale_m=25.0))

    v2_target = bounded.metadata["target_rms_rad"]
    v1_target = legacy.metadata["target_rms_rad"]
    expected = math.sqrt(
        von_karman_piston_removed_variance_rad2(
            bounded.config.pupil_diameter_m, bounded.config.r0_m, 25.0
        )
    )

    assert v2_target == pytest.approx(expected, rel=1.0e-9)
    assert bounded.metadata["absolutely_normalized"] is False
    assert bounded.metadata["raw_spectrum_absolutely_normalized"] is True
    assert bounded.metadata["realization_rms_rescaled"] is True
    # v1 applies the infinite-outer-scale coefficient regardless of L0.
    assert v1_target > 1.2 * v2_target


@pytest.mark.parametrize(
    "field, value",
    [
        ("spectrum_model", "kolmogorov_v3"),
        ("translation_model", "bilinear"),
        ("spectrum_model", ""),
    ],
)
def test_unknown_model_names_are_rejected(field: str, value: str) -> None:
    with pytest.raises(NativeAtmosphereError, match="is not one of"):
        _flow_config(**{field: value})


def test_factory_exposes_the_corrected_atmosphere_by_name() -> None:
    """A profile must be able to select the corrected screen without code.

    ``native_frozen_flow`` keeps the frozen legacy numerics every accepted
    baseline was generated from; ``native_frozen_flow_v2`` is the corrected
    model, and the two must be distinguishable by their recorded identity.
    """

    from shwfs_ao.backends.native.factory import (
        NativeScaoComponentFactory,
        NativeScaoFactoryError,
    )
    from shwfs_ao.core.random import NamedRandomStreams

    factory = NativeScaoComponentFactory()
    geometry = factory.build_geometry(
        telescope_diameter_m=2.0,
        pupil_pixels=64,
        lenslets_across=8,
        min_fill_fraction=0.5,
        central_obstruction_ratio=0.0,
        spider_width_m=0.0,
    )

    def build(model: str):
        return factory.build_atmosphere(
            model=model,
            geometry=geometry,
            random_streams=NamedRandomStreams(31),
            r0_m=0.15,
            outer_scale_m=25.0,
            phase_reference_wavelength_m=500.0e-9,
            wind_m_per_s=(10.0, 0.0),
            target_rms_rad=None,
            normalize_rms=False,
            static_opd_rms_m=0.0,
        )

    legacy = build("native_frozen_flow")
    corrected = build("native_frozen_flow_v2")

    assert legacy.metadata["spectrum_model"] == SPECTRUM_LEGACY_V1
    assert corrected.metadata["spectrum_model"] == SPECTRUM_SUBHARMONIC_V2
    assert corrected.metadata["translation_model"] == TRANSLATION_FOURIER_SUBPIXEL_V2
    assert corrected.config_hash != legacy.config_hash

    with pytest.raises(NativeScaoFactoryError, match="not registered"):
        build("native_frozen_flow_v3")


def test_system_config_accepts_the_corrected_atmosphere_model() -> None:
    """The profile schema must admit the corrected model name."""

    from shwfs_ao.io.configs import SystemConfigError, load_system_profile

    config = load_system_profile("fast_2m_detector", 2)
    upgraded = replace(config, atmosphere_model="native_frozen_flow_v2")

    assert upgraded.atmosphere_model == "native_frozen_flow_v2"
    with pytest.raises(SystemConfigError, match="unsupported atmosphere_model"):
        replace(config, atmosphere_model="native_frozen_flow_v9")


# --------------------------------------------------------------------------
# Oversized screens: keeping the non-periodic seam out of the pupil
# --------------------------------------------------------------------------


def test_v2_screens_are_not_periodic_so_wrapping_is_a_real_discontinuity() -> None:
    """Both shifted quadrature nodes and subharmonics are off-grid.

    The v1 screen contains only on-grid frequencies and is periodic. V2
    cannot be safely wrapped, even when its subharmonic depth is zero.
    """

    from shwfs_ao.backends.native.atmosphere import (
        fourier_von_karman_phase_realization,
    )

    size, delta, r0, outer_scale = 128, 0.02, 0.15, 25.0

    def wrap_ratio(screen: np.ndarray) -> float:
        edge = float(np.median(np.abs(screen[:, 0] - screen[:, -1])))
        interior = float(np.median(np.abs(np.diff(screen, axis=1))))
        return edge / interior

    periodic = wrap_ratio(
        fourier_von_karman_phase_realization(
            size, delta, r0, outer_scale, rng=np.random.default_rng(3)
        )
    )
    assert periodic < 2.0
    for depth in (0, 3):
        ratios = [
            wrap_ratio(subharmonic_von_karman_phase_realization(
                size, delta, r0, outer_scale,
                rng=np.random.default_rng(seed), subharmonic_depth=depth,
            ))
            for seed in range(8)
        ]
        assert np.median(ratios) > 5.0


def test_oversized_screen_keeps_the_seam_out_of_the_pupil() -> None:
    """Inside the travel budget the pupil must never see the wrap seam."""

    pixels, diameter = 52, 2.0
    delta = diameter / pixels
    coordinates = (np.arange(pixels) - pixels // 2) * delta
    x_m, y_m = np.meshgrid(coordinates, coordinates)
    mask = np.hypot(x_m, y_m) <= diameter / 2.0

    def worst_pupil_gradient(screen_size: int, frames: int) -> tuple[float, bool]:
        model = FrozenFlowAtmosphere(
            FrozenFlowAtmosphereConfig(
                grid_size=pixels,
                delta_m=delta,
                pupil_diameter_m=diameter,
                r0_m=0.1263371938263465,
                outer_scale_m=25.0,
                wind_m_per_s=(10.0, 0.0),
                root_seed=5,
                normalize_rms=False,
                spectrum_model=SPECTRUM_SUBHARMONIC_V2,
                translation_model=TRANSLATION_FOURIER_SUBPIXEL_V2,
                screen_grid_size=screen_size,
            ),
            pupil_mask=mask,
        )
        model.reset(realization_index=0)
        interior = mask[:, 1:] & mask[:, :-1]
        worst = 0.0
        for index in range(frames):
            frame = np.nan_to_num(
                np.asarray(model.opd_at(index / 1000.0), dtype=float), nan=0.0
            )
            gradient = np.abs(np.diff(frame, axis=1))[interior]
            worst = max(worst, float(gradient.max()) * 1.0e9)
        return worst, model.exceeded_travel_budget

    padded, exceeded = worst_pupil_gradient(3 * pixels, 150)

    assert not exceeded
    assert padded > 0.0


def test_unpadded_subharmonic_screen_refuses_any_nonzero_travel() -> None:
    """A zero-padding v2 screen has no safe translated frame."""

    model = FrozenFlowAtmosphere(
        FrozenFlowAtmosphereConfig(
            grid_size=52,
            delta_m=2.0 / 52,
            pupil_diameter_m=2.0,
            r0_m=0.15,
            outer_scale_m=25.0,
            wind_m_per_s=(10.0, 0.0),
            root_seed=1,
            normalize_rms=False,
            spectrum_model=SPECTRUM_SUBHARMONIC_V2,
            translation_model=TRANSLATION_FOURIER_SUBPIXEL_V2,
        )
    )

    assert np.any(np.isfinite(model.opd_at(0.0)))
    with pytest.raises(NativeAtmosphereError, match="0.0 px.*wrap seam"):
        model.opd_at(1.0e-3)
    assert model.exceeded_travel_budget
    assert model.travelled_px > 0.0
    model.reset(realization_index=0)
    assert not model.exceeded_travel_budget
    assert model.travelled_px == 0.0


def test_travel_budget_reports_when_a_run_outlives_its_screen() -> None:
    pixels, delta = 52, 2.0 / 52
    config = FrozenFlowAtmosphereConfig(
        grid_size=pixels,
        delta_m=delta,
        pupil_diameter_m=2.0,
        r0_m=0.15,
        outer_scale_m=25.0,
        wind_m_per_s=(10.0, 0.0),
        root_seed=1,
        normalize_rms=False,
        spectrum_model=SPECTRUM_SUBHARMONIC_V2,
        translation_model=TRANSLATION_FOURIER_SUBPIXEL_V2,
        screen_grid_size=2 * pixels,
    )
    assert config.travel_budget_px == pytest.approx(pixels / 2.0)

    model = FrozenFlowAtmosphere(config)
    model.reset(realization_index=0)
    model.opd_at(0.05)  # 0.05 s * 10 m/s -> 13 px, inside the budget
    assert not model.exceeded_travel_budget
    assert model.travelled_px == pytest.approx(13.0, rel=1e-9)

    # Beyond the padding the promise the oversized screen makes is broken, so
    # the frame is refused rather than returned looking ordinary.
    with pytest.raises(NativeAtmosphereError, match="wrap seam"):
        model.opd_at(0.5)  # 130 px, well outside
    assert model.exceeded_travel_budget
    assert model.travelled_px == pytest.approx(130.0, rel=1e-9)


def test_a_wrapping_run_is_refused_rather_than_silently_seamed() -> None:
    """The failure must arrive at the frame that would carry the seam."""

    pixels, delta = 52, 2.0 / 52
    model = FrozenFlowAtmosphere(
        FrozenFlowAtmosphereConfig(
            grid_size=pixels,
            delta_m=delta,
            pupil_diameter_m=2.0,
            r0_m=0.15,
            outer_scale_m=25.0,
            wind_m_per_s=(10.0, 0.0),
            root_seed=1,
            normalize_rms=False,
            spectrum_model=SPECTRUM_SUBHARMONIC_V2,
            translation_model=TRANSLATION_FOURIER_SUBPIXEL_V2,
            screen_grid_size=2 * pixels,
        )
    )
    model.reset(realization_index=0)
    budget = model.config.travel_budget_px  # 26 px -> 100 ms at 10 m/s

    delivered = 0
    with pytest.raises(NativeAtmosphereError):
        for index in range(200):
            model.opd_at(index / 1000.0)
            delivered += 1

    # Every frame inside the budget was delivered, and the first one outside it
    # raised instead of returning a seamed frame.
    assert delivered == int(budget * delta / 10.0 * 1000.0) + 1
    assert model.exceeded_travel_budget


def test_the_legacy_periodic_model_still_wraps_without_complaint() -> None:
    """The exactly periodic legacy spectrum may still wrap indefinitely."""

    model = FrozenFlowAtmosphere(_flow_config(wind_m_per_s=(10.0, 0.0)))
    model.reset(realization_index=0)
    frame = model.opd_at(10.0)  # many screen widths of travel

    assert np.any(np.isfinite(frame))
    assert not model.exceeded_travel_budget


def test_shipped_v2_ensemble_variance_and_realization_scatter() -> None:
    """Compare mean variance, not mean RMS, on the actual shipped pupil."""

    from scipy.signal import fftconvolve
    from scipy.special import gamma, kv
    from shwfs_ao.backends.native.factory import SCREEN_OVERSIZE_FACTOR

    pixels, diameter, r0, outer_scale = 52, 2.0, 0.1263371938263465, 25.0
    # The physical calibration uses linspace endpoints, not D / pixels.
    delta = diameter / (pixels - 1)
    coordinates = np.linspace(-diameter / 2, diameter / 2, pixels)
    x_m, y_m = np.meshgrid(coordinates, coordinates)
    mask = np.hypot(x_m, y_m) <= diameter / 2
    size = SCREEN_OVERSIZE_FACTOR * pixels
    start = (size - pixels) // 2

    # Independent continuous von Karman covariance, averaged over every pair
    # of actual pupil samples. This accounts for rasterization without using
    # the generator's frequencies or any cell-power helper.
    lags = np.arange(1 - pixels, pixels) * delta
    lag_x, lag_y = np.meshgrid(lags, lags)
    z = 2 * np.pi * np.hypot(lag_x, lag_y) / outer_scale
    alpha = 5 / 6
    b0 = np.pi * 0.023 * r0 ** (-5 / 3) * (6 / 5) * outer_scale ** (5 / 3)
    safe_z = np.where(z == 0, 1.0, z)
    covariance = b0 * 2 ** (1 - alpha) / gamma(alpha) * safe_z**alpha * kv(alpha, safe_z)
    covariance[z == 0] = b0
    pairs = fftconvolve(mask.astype(float), mask[::-1, ::-1].astype(float), mode="full")
    theory = float(np.sum(pairs * (b0 - covariance)) / mask.sum()**2)

    rng = np.random.default_rng(20260922)
    variances = []
    for _ in range(512):
        screen = subharmonic_von_karman_phase_realization(
            size, delta, r0, outer_scale, rng=rng
        )
        window = screen[start : start + pixels, start : start + pixels]
        variances.append(float(np.var(window[mask])))
    values = np.asarray(variances)
    mean = float(values.mean())
    sem = float(values.std(ddof=1) / np.sqrt(values.size))
    # Three standard errors plus a 1% finite-band/quadrature allowance. The
    # previous ~19% bias fails this bound with the same independent seed.
    assert 3 * sem < 0.12 * theory
    assert abs(mean - theory) < 3 * sem + 0.01 * theory, (
        f"mean variance {mean:.4f} +/- {sem:.4f} SEM vs {theory:.4f} rad^2"
    )
    # An RMS-pinned realization could pass the mean test while destroying the
    # physical ensemble; require substantial independent realization scatter.
    assert values.std(ddof=1) / mean > 0.4



def test_oversizing_the_legacy_spectrum_is_refused() -> None:
    with pytest.raises(NativeAtmosphereError, match="requires spectrum_model"):
        _flow_config(screen_grid_size=128)


def test_odd_padding_is_refused_so_the_window_stays_centred() -> None:
    with pytest.raises(NativeAtmosphereError, match="must be even"):
        _flow_config(
            spectrum_model=SPECTRUM_SUBHARMONIC_V2,
            screen_grid_size=_flow_config().grid_size + 1,
        )


def _independent_quadrature_variance(subsamples: int, factor: int = 3) -> float:
    """Integrate PSD times a circular-pupil piston filter at spectral nodes."""

    from scipy.special import j1

    diameter, r0, outer_scale = 2.0, 0.1263371938263465, 25.0
    size, delta = factor * 52, diameter / 51
    step = 1 / (size * delta)
    offsets = (np.arange(subsamples) + 0.5) / subsamples - 0.5

    def integrand(fx: np.ndarray, fy: np.ndarray) -> np.ndarray:
        f = np.hypot(fx, fy)
        argument = np.pi * diameter * f
        safe = np.where(argument == 0, 1, argument)
        pupil_filter = np.where(argument == 0, 0, 1 - (2 * j1(safe) / safe)**2)
        return 0.023 * r0**(-5 / 3) * (f*f + outer_scale**-2)**(-11 / 6) * pupil_filter

    frequencies = np.fft.fftfreq(size, delta)
    fx, fy = np.meshgrid(frequencies, frequencies)
    total = 0.0
    for ox in offsets:
        for oy in offsets:
            weighted = integrand(fx + ox * step, fy + oy * step)
            weighted[0, 0] = 0
            total += float(weighted.sum()) * (step / subsamples)**2
    for level in (1, 2, 3):
        width = step / 3**level
        for cx in (-1, 0, 1):
            for cy in (-1, 0, 1):
                if cx == 0 and cy == 0:
                    continue
                fx, fy = np.meshgrid((cx + offsets) * width, (cy + offsets) * width)
                total += float(integrand(fx, fy).sum()) * (width / subsamples)**2
    return total


def test_v2_spectral_quadrature_converges_to_continuum_pupil_variance() -> None:
    """Resolve frequency *locations*, not only cell-integrated power."""

    theory = von_karman_piston_removed_variance_rad2(2.0, 0.1263371938263465, 25.0)
    errors = [abs(_independent_quadrature_variance(n) / theory - 1) for n in (1, 2, 4, 8)]
    assert errors == sorted(errors, reverse=True)
    assert errors[2] < 0.005
    # The output-grid padding is a travel budget, not a variance calibration.
    for factor in (1, 3, 6):
        assert _independent_quadrature_variance(4, factor) == pytest.approx(theory, rel=0.012)


def test_v2_raw_spectrum_scales_with_fried_parameter() -> None:
    weak = subharmonic_von_karman_phase_realization(
        52, 2 / 51, 0.3, 25.0, rng=np.random.default_rng(14)
    )
    strong = subharmonic_von_karman_phase_realization(
        52, 2 / 51, 0.15, 25.0, rng=np.random.default_rng(14)
    )
    np.testing.assert_allclose(strong, weak * 2**(5 / 6), rtol=1e-12, atol=1e-12)


@pytest.mark.parametrize("subsamples", [0, -1, True, 1.5])
def test_v2_quadrature_rejects_invalid_subsample_counts(subsamples) -> None:
    with pytest.raises(NativeAtmosphereError, match="frequency_subsamples"):
        subharmonic_von_karman_phase_realization(
            8, 0.1, 0.15, 25.0, rng=np.random.default_rng(1),
            frequency_subsamples=subsamples,
        )


def _direct_quadrature_at_points(
    config: FrozenFlowAtmosphereConfig, x_m: np.ndarray, y_m: np.ndarray
) -> np.ndarray:
    """Tiny-grid oracle: sum every plane wave directly, with no FFTs."""

    rng = np.random.default_rng(config.root_seed)
    assert config.outer_scale_m is not None
    size = config.generated_grid_size
    step = 1 / (size * config.delta_m)
    offsets = np.array([-3, -1, 1, 3]) / 8
    base = np.fft.fftfreq(size, config.delta_m)
    result = np.zeros(x_m.size)

    def add_nodes(fx: np.ndarray, fy: np.ndarray, width: float, dc: slice | int) -> None:
        nonlocal result
        power = 0.023 * config.r0_m**(-5 / 3) * (
            fx*fx + fy*fy + config.outer_scale_m**-2
        )**(-11 / 6) * (width / 4)**2
        power[dc, dc] = 0
        coefficients = (
            rng.normal(size=power.shape) + 1j * rng.normal(size=power.shape)
        ) * np.sqrt(power)
        result += np.real(np.exp(2j * np.pi * (
            x_m[:, None] * fx.ravel() + y_m[:, None] * fy.ravel()
        )) @ coefficients.ravel())

    for ox in offsets:
        for oy in offsets:
            fx, fy = np.meshgrid(base + ox * step, base + oy * step)
            add_nodes(fx, fy, step, 0)
    for level in (1, 2, 3):
        width = step / 3**level
        nodes = (np.array([-1, 0, 1])[:, None] + offsets).ravel() * width
        fx, fy = np.meshgrid(nodes, nodes)
        add_nodes(fx, fy, width, slice(4, 8))
    return result


@pytest.mark.parametrize("normalize", [False, True])
@pytest.mark.parametrize("wind", [(0.3, 0.0), (-0.18, 0.24)])
def test_v2_subpixel_flow_matches_direct_off_grid_plane_waves(
    normalize: bool, wind: tuple[float, float]
) -> None:
    """Exact spectral replay stays accurate even near the travel boundary."""

    config = FrozenFlowAtmosphereConfig(
        grid_size=6, screen_grid_size=18, delta_m=0.3, pupil_diameter_m=1.5,
        r0_m=0.15, outer_scale_m=25.0, root_seed=37,
        spectrum_model=SPECTRUM_SUBHARMONIC_V2,
        translation_model=TRANSLATION_FOURIER_SUBPIXEL_V2,
        normalize_rms=normalize, wind_m_per_s=wind,
    )
    coords = np.linspace(-0.75, 0.75, 6)
    x, y = np.meshgrid(coords, coords)
    mask = np.hypot(x, y) <= 0.75
    model = FrozenFlowAtmosphere(config, pupil_mask=mask)
    # Generated coordinates start at zero; the six-pixel window starts at 6.
    xx, yy = np.meshgrid((np.arange(6) + 6) * 0.3, (np.arange(6) + 6) * 0.3)
    initial = _direct_quadrature_at_points(config, xx[mask], yy[mask])
    gain = (
        float(model.metadata["target_rms_rad"]) / float(initial.std())
        if normalize else 1.0
    )
    for time_s in (0.0, 0.25, 0.5, 3.5, 5.5):
        phase = _direct_quadrature_at_points(
            config, xx[mask] - wind[0] * time_s, yy[mask] - wind[1] * time_s
        )
        expected = (phase - phase.mean()) * gain * 500e-9 / (2 * np.pi)
        np.testing.assert_allclose(model.opd_at(time_s)[mask], expected, rtol=1e-11, atol=1e-18)
    assert model.metadata["frozen_flow_discretization"] == "exact_nonperiodic_spectral_subpixel"
    # Query cadence must not advance the saved spectral random state.
    model.reset(realization_index=0)
    np.testing.assert_allclose(model.opd_at(5.5)[mask], expected, rtol=1e-11, atol=1e-18)
