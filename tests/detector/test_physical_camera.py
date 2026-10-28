"""DET-05: physical camera models, electronics, and persistent pixel maps.

Monte-Carlo tolerances are five standard errors computed from the sample
count: ``SE(mean) = s / sqrt(N)`` and ``SE(var) = sqrt((m4 - s**4) / N)`` with
``m4`` the sample fourth central moment.  Seeds are fixed, so every check is
deterministic; five standard errors keep a correct model inside the band with
probability above 0.99999.
"""

from __future__ import annotations

from dataclasses import replace
import math

import numpy as np
import pytest

from shwfs_ao.core.random import (
    DEFAULT_RANDOM_DOMAINS,
    DETECTOR_PHYSICS_RANDOM_DOMAINS,
    NamedRandomStreams,
    with_detector_physics_domains,
)
from shwfs_ao.detector.camera import CameraConfig, CameraConfigError
from shwfs_ao.detector.camera_maps import CameraMaps, CameraMapsError
from shwfs_ao.detector.layout import DetectorLayout, DetectorLayoutError
from shwfs_ao.detector.physical import (
    PhysicalCameraError,
    apply_coupling,
    apply_physical_camera,
    sample_em_register,
)


def camera(**overrides: object) -> CameraConfig:
    values: dict[str, object] = dict(
        model="ccd",
        preset_name="test",
        preset_version=1,
        quantum_efficiency=1.0,
        full_well_e=1.0e9,
        dark_e_per_s=0.0,
        hot_pixel_fraction=0.0,
        hot_pixel_dark_e_per_s=0.0,
        prnu_rms=0.0,
        dead_pixel_fraction=0.0,
        read_noise_e=0.0,
        conversion_gain_e_per_adu=1.0,
        bias_adu=0.0,
        offset_map_rms_adu=0.0,
        adc_bits=None,
    )
    values.update(overrides)
    return CameraConfig(**values)  # type: ignore[arg-type]


def emccd(**overrides: object) -> CameraConfig:
    values: dict[str, object] = dict(model="emccd", em_gain=300.0, register_full_well_e=1.0e15)
    values.update(overrides)
    return camera(**values)


def streams(seed: int = 7) -> NamedRandomStreams:
    return with_detector_physics_domains(NamedRandomStreams(seed))


def layout(n: int = 1, window: int = 15, guard: int = 0) -> DetectorLayout:
    return DetectorLayout("isolated_lenslet_blocks.v1", n, window, guard)


def ids(n: int) -> tuple[str, ...]:
    return tuple(f"lenslet-r{r:04d}-c{c:04d}" for c in range(n) for r in range(n))


def run_chain(cam, source, *, sky=0.0, frames=1, seed=3, include_noise=True, maps=None, exposure_s=1.0e-3, floor=0.0):
    provider = streams(seed)
    if maps is None:
        maps = {"prnu": None, "dead": None, "hot": None, "offset_adu": None, "gain_multiplier": None, "read_noise_multiplier": None}
    outputs = []
    gens: dict[tuple[int, str], np.random.Generator] = {}

    def generators(index: int, domain: str) -> np.random.Generator:
        key = (index, domain)
        if key not in gens:
            gens[key] = provider.scoped("test", key=(index,)).generator(domain)
        return gens[key]

    for _ in range(frames):
        outputs.append(
            apply_physical_camera(
                source,
                sky,
                cam,
                maps,
                exposure_s=exposure_s,
                include_noise=include_noise,
                generators=generators,
                poisson_floor_e=floor,
            )
        )
    return outputs


def _within(sample: np.ndarray, mean: float, variance: float) -> None:
    values = np.asarray(sample, dtype=float).ravel()
    count = values.size
    observed_mean = float(values.mean())
    observed_var = float(values.var(ddof=1))
    centred = values - observed_mean
    m4 = float(np.mean(centred**4))
    se_mean = math.sqrt(observed_var / count)
    se_var = math.sqrt(max(m4 - observed_var**2, 0.0) / count)
    assert abs(observed_mean - mean) <= 5.0 * se_mean, (observed_mean, mean, se_mean)
    assert abs(observed_var - variance) <= 5.0 * se_var, (observed_var, variance, se_var)


# -- EM register ------------------------------------------------------------------


@pytest.mark.parametrize("gain", [100.0, 1000.0])
@pytest.mark.parametrize("n_in", [1, 5, 40])
def test_register_alone_has_gamma_conditional_moments(gain: float, n_in: int) -> None:
    generator = np.random.default_rng(11)
    counts = np.full(100_000, float(n_in))
    output = sample_em_register(counts, gain, generator)
    _within(output, gain * n_in, n_in * gain**2)


@pytest.mark.parametrize("gain", [100.0, 1000.0])
@pytest.mark.parametrize("mu", [0.5, 4.0, 30.0])
def test_poisson_through_register_has_excess_factor_two(gain: float, mu: float) -> None:
    cam = emccd(em_gain=gain)
    source = np.full((4, 25, 25), mu)  # 2500 pixels per frame
    frames = run_chain(cam, source, frames=40, exposure_s=1.0e-3)
    output = np.concatenate([frame.raw.ravel() for frame in frames])  # 100 000 samples
    _within(output, gain * mu, 2.0 * gain**2 * mu)
    assert cam.excess_noise_factor_squared == 2.0


def test_unity_gain_register_adds_no_variance_and_zero_stays_zero() -> None:
    generator = np.random.default_rng(5)
    counts = np.array([0.0, 1.0, 7.0, 0.0])
    assert np.array_equal(sample_em_register(counts, 1.0, generator), counts)
    high = sample_em_register(np.zeros(1000), 300.0, generator)
    assert np.all(high == 0.0)
    cam = emccd(em_gain=1.0)
    source = np.full((2, 15, 15), 9.0)
    frame = run_chain(cam, source, frames=1)[0]
    # G = 1, no read noise: the raw output equals the Poisson charge exactly.
    assert np.all(frame.raw == np.floor(frame.raw))


def test_intermediate_em_gain_is_rejected() -> None:
    with pytest.raises(CameraConfigError, match="supported regime"):
        emccd(em_gain=10.0)
    with pytest.raises(CameraConfigError, match="emccd"):
        camera(em_gain=300.0)
    with pytest.raises(PhysicalCameraError):
        sample_em_register(np.array([1.0]), 10.0, np.random.default_rng(0))


def test_pre_register_cic_is_drawn_once_and_receives_full_gain() -> None:
    cic = 0.05
    cam = emccd(em_gain=200.0, cic_e_per_pixel_read=cic)
    source = np.zeros((4, 25, 25))
    frames = run_chain(cam, source, frames=40, exposure_s=0.0)
    output = np.concatenate([frame.raw.ravel() for frame in frames])
    # CIC alone: Poisson(cic) through the register, F^2 = 2.
    _within(output, 200.0 * cic, 2.0 * 200.0**2 * cic)
    reference = run_chain(cam, source, include_noise=False)[0]
    assert np.allclose(reference.raw, 200.0 * cic, rtol=1e-14, atol=0)
    with pytest.raises(CameraConfigError, match="emccd"):
        camera(cic_e_per_pixel_read=0.01)


# -- saturation ordering ------------------------------------------------------------


def test_overfilled_pixels_saturate_before_read_noise() -> None:
    read = 4.0
    cam = camera(full_well_e=1000.0, read_noise_e=read)
    source = np.full((4, 25, 25), 1.0e6)
    frames = run_chain(cam, source, frames=40)
    output = np.concatenate([frame.raw.ravel() for frame in frames])
    assert all(frame.pixel_saturated.all() for frame in frames)
    assert not any(frame.register_saturated.any() or frame.digital_saturated.any() for frame in frames)
    _within(output, 1000.0, read**2)


def test_pixel_register_and_digital_limits_flag_separately() -> None:
    pixel = run_chain(emccd(full_well_e=10.0, register_full_well_e=1.0e9), np.full((1, 5, 5), 1.0e3), include_noise=False)[0]
    assert pixel.pixel_saturated.all() and not pixel.register_saturated.any()
    register = run_chain(emccd(full_well_e=1.0e9, register_full_well_e=1.0e4), np.full((1, 5, 5), 1.0e3), include_noise=False)[0]
    assert register.register_saturated.all() and not register.pixel_saturated.any()
    assert np.allclose(register.raw, 1.0e4)
    digital = run_chain(camera(adc_bits=8, conversion_gain_e_per_adu=1.0), np.full((1, 5, 5), 1.0e3), include_noise=False)[0]
    assert digital.digital_saturated.all() and not digital.pixel_saturated.any()
    assert np.all(digital.raw == 255.0)


# -- photoresponse, dark, dead and hot pixels ----------------------------------------


def test_prnu_multiplies_source_and_sky_only() -> None:
    cam = camera(dark_e_per_s=1000.0, prnu_rms=0.1)
    maps = CameraMaps.create(cam, layout(), ids(1), random_streams=streams())
    arrays = maps.subset(np.arange(1))
    source = np.full((1, 15, 15), 50.0)
    frame = run_chain(cam, source, sky=3.0, maps=arrays, include_noise=False, exposure_s=1.0e-3)[0]
    response = np.asarray(maps.prnu)
    assert np.allclose(frame.expected_source_e, 50.0 * response, rtol=1e-15)
    assert np.allclose(frame.expected_background_e, 3.0 * response + 1.0, rtol=1e-14)
    cam_more = replace(cam, prnu_rms=0.3)
    maps_more = CameraMaps.create(cam_more, layout(), ids(1), random_streams=streams())
    frame_more = run_chain(cam_more, source, sky=0.0, maps=maps_more.subset(np.arange(1)), include_noise=False)[0]
    # The dark expectation is independent of PRNU.
    assert np.allclose(frame_more.expected_background_e, 1.0, rtol=1e-14)


def test_dead_pixels_keep_dark_bias_and_read_noise_and_hot_pixels_add_dark() -> None:
    cam = camera(dead_pixel_fraction=0.02, hot_pixel_fraction=0.02, hot_pixel_dark_e_per_s=5.0e4, dark_e_per_s=100.0, bias_adu=10.0)
    lay = layout(n=3, window=21)
    maps = CameraMaps.create(cam, lay, ids(3), random_streams=streams())
    dead = np.asarray(maps.dead)
    hot = np.asarray(maps.hot)
    assert dead.any() and hot.any()
    source = np.full(maps.shape, 200.0)
    frame = run_chain(cam, source, maps=maps.subset(np.arange(9)), include_noise=False, exposure_s=1.0e-3)[0]
    expected = np.where(dead, 0.0, 200.0) + np.where(hot, 50.0, 0.1) + 10.0
    assert np.allclose(frame.raw, expected, rtol=1e-13)


def test_adc_quantization_variance_bias_and_clipping() -> None:
    bias = 100.0
    cam = camera(adc_bits=12, bias_adu=bias, conversion_gain_e_per_adu=1.0)
    rng = np.random.default_rng(3)
    signal = rng.uniform(10.0, 2000.0, size=(4, 50, 50))
    frame = run_chain(cam, signal, include_noise=False)[0]
    error = frame.raw - (signal + bias)
    count = error.size
    # Uniform error on [-1/2, 1/2): variance 1/12, fourth moment 1/80.
    se_var = math.sqrt((1.0 / 80.0 - (1.0 / 12.0) ** 2) / count)
    assert abs(np.var(error) - 1.0 / 12.0) <= 5.0 * se_var
    assert abs(np.mean(error)) <= 5.0 * math.sqrt(1.0 / 12.0 / count)
    dark = run_chain(cam, np.zeros((1, 5, 5)), include_noise=False)[0]
    assert np.all(dark.raw == bias)
    hot = run_chain(cam, np.full((1, 5, 5), 1.0e5), include_noise=False)[0]
    assert np.all(hot.raw == 4095.0) and hot.digital_saturated.all()


def test_nonlinearity_must_be_monotonic_and_is_applied_in_output_electrons() -> None:
    with pytest.raises(CameraConfigError, match="strictly increasing"):
        camera(full_well_e=1.0e4, nonlinearity_coefficients=(-1.0e-4,))
    cam = camera(full_well_e=1.0e4, nonlinearity_coefficients=(-1.0e-6,))
    frame = run_chain(cam, np.full((1, 3, 3), 1000.0), include_noise=False)[0]
    assert np.allclose(frame.raw, 1000.0 - 1.0e-6 * 1000.0**2)



def test_emccd_nonlinearity_is_checked_over_the_register_capacity() -> None:
    # One input electron can leave a Gamma(1, G) register far above G, so
    # full_well * G bounds only the conditional mean (review R7).  Here the
    # response turns over at 250 e- while full_well * G is 100 e-.
    with pytest.raises(CameraConfigError, match="strictly increasing"):
        emccd(full_well_e=1.0, em_gain=100.0, register_full_well_e=1.0e4, nonlinearity_coefficients=(-0.002,))
    multiplying = emccd(full_well_e=1.0, em_gain=100.0, register_full_well_e=1.0e4)
    assert multiplying.max_output_signal_e == 1.0e4
    unity = emccd(full_well_e=50.0, em_gain=1.0, register_full_well_e=1.0e4)
    assert unity.max_output_signal_e == 50.0
    # Accepted: monotonic up to the register capacity plus read-noise excursions.
    emccd(full_well_e=1.0, em_gain=100.0, register_full_well_e=1.0e4, read_noise_e=50.0, nonlinearity_coefficients=(-1.0e-5,))


def test_nonlinearity_is_checked_over_negative_read_noise_excursions() -> None:
    # y + c y**2 has slope 1 + 2 c y, which a positive c turns over at
    # y = -1 / (2 c) = -25 e-: inside 6 sigma of 10 e- read noise, outside 6
    # sigma of 3 e- read noise.
    with pytest.raises(CameraConfigError, match="strictly increasing"):
        camera(full_well_e=1.0e3, read_noise_e=10.0, nonlinearity_coefficients=(0.02,))
    camera(full_well_e=1.0e3, read_noise_e=3.0, nonlinearity_coefficients=(0.02,))


def test_cmos_nonlinearity_is_checked_against_the_realized_read_noise_map() -> None:
    # The configuration check uses the median read noise (6 x 3 e- = 18 e-),
    # but y + 0.02 y**2 turns over at -25 e-, inside six sigmas of the many
    # pixels that a lognormal map with sigma 1.5 makes noisier (re-review S3).
    nonlinear = dict(model="cmos", read_noise_e=3.0, full_well_e=1000.0, nonlinearity_coefficients=(0.02,))
    wide = camera(cmos_read_noise_lognormal_sigma=1.5, **nonlinear)
    with pytest.raises(CameraMapsError, match="not monotonic"):
        CameraMaps.create(wide, layout(), ids(1), random_streams=streams())
    # A narrow map keeps every pixel's six sigmas above the turnover.
    narrow = camera(cmos_read_noise_lognormal_sigma=0.05, **nonlinear)
    maps = CameraMaps.create(narrow, layout(), ids(1), random_streams=streams())
    assert 6.0 * float(np.max(maps.read_noise_e(narrow))) < 25.0
    # Linear cameras are never constrained by their map.
    CameraMaps.create(camera(model="cmos", read_noise_e=3.0, cmos_read_noise_lognormal_sigma=1.5), layout(), ids(1), random_streams=streams())

def test_the_adc_dither_is_part_of_the_deterministic_response_identity() -> None:
    # With the ADC on, the reference quantizer depends on read noise, so its
    # identity must too (review R1); with the ADC off it does not.
    quiet = camera(adc_bits=12, bias_adu=100.0)
    noisy = replace(quiet, read_noise_e=1.0)
    source = np.full((1, 1, 1), 0.25)
    references = [run_chain(cam, source, include_noise=False)[0].raw[0, 0, 0] for cam in (quiet, noisy)]
    assert references[0] == 100.0 and references[1] == pytest.approx(100.25, abs=1e-6)
    assert quiet.deterministic_response_config != noisy.deterministic_response_config
    analog = camera(bias_adu=100.0)
    analog_noisy = replace(analog, read_noise_e=1.0)
    assert analog.deterministic_response_config == analog_noisy.deterministic_response_config
    assert run_chain(analog, source, include_noise=False)[0].raw[0, 0, 0] == run_chain(
        analog_noisy, source, include_noise=False
    )[0].raw[0, 0, 0]


# -- electronic coupling ------------------------------------------------------------


def test_coupling_kernel_is_normalized_and_identity_is_exact() -> None:
    cam = camera(coupling_nearest=0.02, coupling_diagonal=0.005)
    kernel = cam.coupling_kernel
    assert math.isclose(float(kernel.sum()), 1.0, rel_tol=0, abs_tol=1e-15)
    assert np.all(kernel >= 0.0)
    rng = np.random.default_rng(1)
    signal = rng.uniform(0.0, 10.0, size=(2, 9, 9))
    identity = np.zeros((3, 3))
    identity[1, 1] = 1.0
    assert np.array_equal(apply_coupling(signal, identity), signal)
    padded = np.zeros((1, 11, 11))
    padded[0, 5, 5] = 1.0
    coupled = apply_coupling(padded, kernel)
    assert np.allclose(coupled[0, 4:7, 4:7], kernel, rtol=0, atol=1e-16)
    assert math.isclose(float(coupled.sum()), 1.0, abs_tol=1e-15)
    # A centred pixel loses nothing; an edge pixel loses its outward share.
    edge = np.zeros((1, 5, 5))
    edge[0, 0, 2] = 1.0
    lost = 1.0 - float(apply_coupling(edge, kernel).sum())
    assert math.isclose(lost, 0.02 + 2 * 0.005, rel_tol=1e-12)


# -- persistent maps and pixel identity ----------------------------------------------


def _map_camera() -> CameraConfig:
    return camera(
        model="cmos",
        prnu_rms=0.05,
        dead_pixel_fraction=0.01,
        hot_pixel_fraction=0.01,
        hot_pixel_dark_e_per_s=10.0,
        offset_map_rms_adu=2.0,
        cmos_gain_map_rms=0.03,
        cmos_read_noise_lognormal_sigma=0.3,
    )


def test_maps_follow_physical_pixels_not_order_batch_or_subset() -> None:
    cam = _map_camera()
    lay = layout(n=4, window=9, guard=1)
    full_ids = ids(4)
    maps = CameraMaps.create(cam, lay, full_ids, random_streams=streams())
    reordered = tuple(reversed(full_ids))
    maps_reordered = CameraMaps.create(cam, lay, reordered, random_streams=streams())
    subset_ids = full_ids[3:9]
    maps_subset = CameraMaps.create(cam, lay, subset_ids, random_streams=streams())
    for name in ("prnu", "dead", "hot", "offset_adu", "gain_multiplier", "read_noise_multiplier"):
        values = getattr(maps, name)
        by_id = dict(zip(full_ids, values))
        for identifier, block in zip(reordered, getattr(maps_reordered, name)):
            assert np.array_equal(block, by_id[identifier]), name
        for identifier, block in zip(subset_ids, getattr(maps_subset, name)):
            assert np.array_equal(block, by_id[identifier]), name
    # Distinct pixels do not alias one repeated window map.
    blocks = np.asarray(maps.prnu)
    assert all(not np.array_equal(blocks[0], blocks[i]) for i in range(1, blocks.shape[0]))
    assert maps.realization_hash != maps_subset.realization_hash


def test_an_isolated_defect_stays_on_its_pixel() -> None:
    cam = camera(dead_pixel_fraction=0.003)
    lay = layout(n=6, window=11)
    maps = CameraMaps.create(cam, lay, ids(6), random_streams=streams(12))
    dead = np.asarray(maps.dead)
    counts = dead.sum(axis=(1, 2))
    assert counts.sum() >= 1
    first = int(np.argmax(counts > 0))
    pixel_ids = lay.pixel_ids(ids(6)[first])[dead[first]]
    again = CameraMaps.create(cam, lay, (ids(6)[first],), random_streams=streams(12))
    assert np.array_equal(lay.pixel_ids(ids(6)[first])[np.asarray(again.dead)[0]], pixel_ids)


def test_realization_hash_tracks_exactly_the_map_generating_settings() -> None:
    lay = layout(n=2, window=9)
    base = _map_camera()

    def hash_of(cam: CameraConfig) -> str:
        return CameraMaps.create(cam, lay, ids(2), random_streams=streams()).realization_hash

    reference = hash_of(base)
    for unchanged in (
        replace(base, read_noise_e=5.0),
        replace(base, conversion_gain_e_per_adu=2.0),
        replace(base, dark_e_per_s=3.0),
        replace(base, bias_adu=50.0),
        replace(base, full_well_e=1.0e4),
    ):
        assert hash_of(unchanged) == reference
    for changed in (
        replace(base, hot_pixel_fraction=0.02),
        replace(base, hot_pixel_dark_e_per_s=20.0),
        replace(base, cmos_gain_map_rms=0.04),
        replace(base, cmos_read_noise_lognormal_sigma=0.2),
        replace(base, offset_map_rms_adu=3.0),
        replace(base, prnu_rms=0.06),
    ):
        assert hash_of(changed) != reference
    assert CameraMaps.create(base, layout(n=2, window=9, guard=1), ids(2), random_streams=streams()).realization_hash != reference


def test_layout_rejects_unplaceable_or_shared_lenslets() -> None:
    lay = layout(n=2, window=5)
    with pytest.raises(DetectorLayoutError):
        lay.validate_subapertures(("lenslet-r0000-c0002",))
    with pytest.raises(DetectorLayoutError):
        lay.validate_subapertures(("sub-1",))
    with pytest.raises(DetectorLayoutError):
        lay.validate_subapertures(("lenslet-r0000-c0001", "lenslet-r00-c01"))
    pixel = lay.pixel_ids("lenslet-r0001-c0000")
    assert pixel[0, 0] == 5 * 10 and pixel.flags.writeable is False


def test_registering_physics_domains_leaves_existing_draws_identical() -> None:
    plain = NamedRandomStreams(99)
    extended = with_detector_physics_domains(NamedRandomStreams(99))
    assert extended.registered_domains == (*DEFAULT_RANDOM_DOMAINS, *DETECTOR_PHYSICS_RANDOM_DOMAINS)
    for domain in DEFAULT_RANDOM_DOMAINS:
        assert plain.stream_id(domain) == extended.stream_id(domain)
        assert np.array_equal(plain.generator(domain).random(16), extended.generator(domain).random(16))
        assert np.array_equal(
            plain.keyed_generator(domain, key=("k", 1)).random(8),
            extended.keyed_generator(domain, key=("k", 1)).random(8),
        )


def test_the_reference_path_is_deterministic_and_equals_expectations_in_the_linear_regime() -> None:
    cam = emccd(em_gain=300.0, cic_e_per_pixel_read=0.01, read_noise_e=50.0, conversion_gain_e_per_adu=10.0, bias_adu=100.0)
    source = np.full((2, 7, 7), 12.0)
    first = run_chain(cam, source, include_noise=False)[0]
    second = run_chain(cam, source, include_noise=False, seed=99)[0]
    assert np.array_equal(first.raw, second.raw)
    # ADC off: raw readout in output_e_equivalent = signal + bias * conversion gain.
    assert np.allclose(first.raw, 300.0 * (12.0 + 0.01) + 100.0 * 10.0, rtol=1e-14)
