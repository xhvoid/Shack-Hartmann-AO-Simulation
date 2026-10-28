"""AO-REF-014 contracts for the HCIPy von Kármán atmosphere backend.

Every test requires the optional HCIPy dependency and carries the ``hcipy``
marker so native CI selections never execute it.  The module is part of the
portable wheel-smoke bundle, so it imports only the installed package.
"""

from __future__ import annotations

import json

import numpy as np
import pytest


hcipy = pytest.importorskip("hcipy")

from shwfs_ao.backends.hcipy import hcipy_version
from shwfs_ao.backends.hcipy.atmosphere import (
    WIND_CONVENTION,
    HcipyAtmosphereConfig,
    HcipyAtmosphereError,
    HcipyAtmosphereLayerConfig,
    HcipyVonKarmanAtmosphere,
)
from shwfs_ao.core.geometry import build_pupil_geometry
from shwfs_ao.core.protocols import AtmosphereModel
from shwfs_ao.core.random import NamedRandomStreams
from shwfs_ao.core.wavefront import masked_mean, masked_rms, opd_to_phase


pytestmark = pytest.mark.hcipy


WAVELENGTH_M = 500.0e-9
_KIND_PARAMS = pytest.mark.parametrize("kind", ("infinite", "finite"))


def _geometry(pupil_pixels: int = 32, diameter_m: float = 1.0):
    return build_pupil_geometry(
        telescope_diameter_m=diameter_m,
        pupil_shape=(pupil_pixels, pupil_pixels),
    )


def _config(**changes) -> HcipyAtmosphereConfig:
    values = {
        "r0_m": 0.15,
        "outer_scale_m": 20.0,
        "wind_m_per_s": (5.0, -2.0),
        "altitude_m": 0.0,
        "kind": "infinite",
        "r0_reference_wavelength_m": WAVELENGTH_M,
        "phase_conversion_reference_wavelength_m": WAVELENGTH_M,
        "root_seed": 7,
    }
    values.update(changes)
    return HcipyAtmosphereConfig.single_layer(**values)


def _model(
    config: HcipyAtmosphereConfig | None = None,
    *,
    pupil_pixels: int = 32,
    **model_kwargs,
) -> HcipyVonKarmanAtmosphere:
    return HcipyVonKarmanAtmosphere(
        config if config is not None else _config(),
        _geometry(pupil_pixels),
        **model_kwargs,
    )


def _square_model(config: HcipyAtmosphereConfig, pupil_pixels: int):
    """Model with an all-true pupil for full-frame spatial comparisons."""

    geometry = _geometry(pupil_pixels)
    return HcipyVonKarmanAtmosphere(
        config,
        geometry,
        pupil_mask=np.ones(geometry.pupil_shape, dtype=bool),
    )


def _frames(model, times) -> tuple[np.ndarray, ...]:
    return tuple(model.opd_at(time_s) for time_s in times)


def _assert_frames_equal(first, second) -> None:
    assert all(
        np.array_equal(a, b, equal_nan=True) for a, b in zip(first, second)
    )
    assert len(first) == len(second)


class TestProtocolAndOutputContract:
    def test_model_implements_the_atmosphere_protocol(self):
        model = _model()
        assert isinstance(model, AtmosphereModel)
        assert model.backend_name == "hcipy"
        assert len(model.config_hash) == 64
        assert model.root_seed == 7
        assert model.realization_index == 0

    def test_opd_is_finite_piston_removed_metres_on_the_configured_pupil(self):
        model = _model()
        mask = model.pupil_mask
        opd_m = model.opd_at(0.0)

        assert type(opd_m) is np.ndarray
        assert opd_m.shape == mask.shape == (32, 32)
        assert np.all(np.isfinite(opd_m[mask]))
        assert np.all(np.isnan(opd_m[~mask]))
        assert not opd_m.flags.writeable
        rms_m = masked_rms(opd_m, mask)
        assert 1.0e-9 < rms_m < 1.0e-5
        assert abs(masked_mean(opd_m, mask)) < 1.0e-12 * rms_m

    def test_output_is_a_defensive_copy(self):
        model = _model()
        first = model.opd_at(0.0)
        second = model.opd_at(0.0)
        assert first is not second
        assert np.array_equal(first, second, equal_nan=True)

    def test_supplied_pupil_mask_overrides_the_geometry_mask(self):
        geometry = _geometry(32)
        mask = np.array(geometry.pupil_mask, copy=True)
        mask[:, :4] = False
        model = HcipyVonKarmanAtmosphere(_config(), geometry, pupil_mask=mask)
        opd_m = model.opd_at(0.0)
        assert np.all(np.isnan(opd_m[:, :4]))
        assert abs(masked_mean(opd_m, mask)) < 1.0e-20


class TestDeterminism:
    def test_same_configuration_and_seed_reproduce_identical_frames(self):
        times = (0.0, 0.004, 0.012)
        first = _frames(_model(), times)
        second = _frames(_model(), times)
        _assert_frames_equal(first, second)

    def test_different_root_seeds_give_different_realizations(self):
        first = _model(_config(root_seed=7)).opd_at(0.0)
        second = _model(_config(root_seed=8)).opd_at(0.0)
        assert not np.allclose(first, second, equal_nan=True)

    @_KIND_PARAMS
    def test_reset_and_replay_of_the_same_time_vector_is_exact(self, kind):
        times = (0.0, 0.004, 0.004, 0.012, 0.030)
        model = _model(_config(kind=kind))
        original = _frames(model, times)

        model.reset(realization_index=0)
        _assert_frames_equal(original, _frames(model, times))

    def test_different_realization_index_changes_the_screens(self):
        model = _model()
        baseline = model.opd_at(0.0)

        model.reset(realization_index=1)
        other = model.opd_at(0.0)
        assert not np.allclose(baseline, other, equal_nan=True)
        assert model.realization_index == 1
        assert model.metadata["realization_index"] == 1

        model.reset(realization_index=0)
        assert np.array_equal(model.opd_at(0.0), baseline, equal_nan=True)

    def test_explicit_random_streams_match_the_internal_derivation(self):
        streams = NamedRandomStreams(7)
        supplied = _model(random_streams=streams)
        internal = _model()
        assert np.array_equal(
            supplied.opd_at(0.0),
            internal.opd_at(0.0),
            equal_nan=True,
        )
        assert supplied.metadata["random_stream_id"] == streams.stream_id(
            "atmosphere",
            key=("realization", 0),
        )

    def test_scoped_random_streams_derive_an_independent_realization(self):
        scoped = _model(random_streams=NamedRandomStreams(7).scoped("replica"))
        internal = _model()
        assert not np.allclose(
            scoped.opd_at(0.0),
            internal.opd_at(0.0),
            equal_nan=True,
        )


class TestTimeSemantics:
    @_KIND_PARAMS
    def test_backward_time_is_rejected_with_a_clear_error(self, kind):
        model = _model(_config(kind=kind))
        model.opd_at(0.010)
        with pytest.raises(HcipyAtmosphereError, match="nondecreasing"):
            model.opd_at(0.005)

    @_KIND_PARAMS
    def test_repeated_same_time_is_idempotent(self, kind):
        model = _model(_config(kind=kind))
        model.opd_at(0.0)
        first = model.opd_at(0.008)
        second = model.opd_at(0.008)
        assert np.array_equal(first, second, equal_nan=True)

    def test_negative_and_non_finite_times_are_rejected(self):
        model = _model()
        with pytest.raises(HcipyAtmosphereError, match="non-negative"):
            model.opd_at(-0.001)
        with pytest.raises(HcipyAtmosphereError, match="finite"):
            model.opd_at(float("nan"))

    def test_reset_returns_the_clock_to_zero(self):
        model = _model()
        model.opd_at(0.5)
        model.reset(realization_index=0)
        model.opd_at(0.0)

    def test_time_advances_even_without_wind(self):
        model = _model(_config(wind_m_per_s=(0.0, 0.0)))
        first = model.opd_at(0.0)
        second = model.opd_at(1.0)
        assert np.array_equal(first, second, equal_nan=True)


class TestTemporalEvolution:
    @_KIND_PARAMS
    def test_wind_produces_nonzero_temporal_evolution(self, kind):
        model = _model(_config(kind=kind))
        first = model.opd_at(0.0)
        second = model.opd_at(0.050)
        assert not np.allclose(first, second, equal_nan=True)

    @_KIND_PARAMS
    def test_subpixel_displacement_changes_the_screen(self, kind):
        """The backend must not be restricted to integer-pixel translation."""

        pixels = 32
        geometry = _geometry(pixels)
        spacing_m = geometry.pixel_spacing_xy_m[0]
        model = _model(
            _config(kind=kind, wind_m_per_s=(1.0, 0.0)),
            pupil_pixels=pixels,
        )
        first = model.opd_at(0.0)
        second = model.opd_at(0.4 * spacing_m)
        assert not np.allclose(first, second, equal_nan=True)

    @_KIND_PARAMS
    @pytest.mark.parametrize("wind", ((1.0, 0.0), (0.0, 1.0), (1.0, -1.0)))
    def test_pattern_advects_with_positive_wind(self, kind, wind):
        """Displacement direction follows the repository wind convention.

        With wind ``(wx, wy)`` the frame at time t must match the t=0 frame
        translated by ``+wind·t`` — the same convention as the native
        backend — for both HCIPy layer kinds despite their different raw
        velocity semantics.
        """

        pixels = 64
        shift_px = 4
        margin = 12
        config = _config(kind=kind, wind_m_per_s=wind, outer_scale_m=20.0)
        model = _square_model(config, pixels)
        spacing_m = _geometry(pixels).pixel_spacing_xy_m[0]
        time_s = shift_px * spacing_m

        first = model.opd_at(0.0)
        second = model.opd_at(time_s)
        expected_dx = int(round(shift_px * wind[0]))
        expected_dy = int(round(shift_px * wind[1]))

        forward = _shifted_correlation(
            first,
            second,
            dx=expected_dx,
            dy=expected_dy,
            margin=margin,
        )
        reverse = _shifted_correlation(
            first,
            second,
            dx=-expected_dx,
            dy=-expected_dy,
            margin=margin,
        )
        assert forward > 0.99
        assert forward > reverse + 0.05


class TestPhysicalScaling:
    def test_r0_scaling_trend_at_the_explicit_reference_wavelength(self):
        strong = _model(_config(r0_m=0.10, wind_m_per_s=(0.0, 0.0)))
        weak = _model(_config(r0_m=0.20, wind_m_per_s=(0.0, 0.0)))
        mask = strong.pupil_mask

        rms_ratio = masked_rms(strong.opd_at(0.0), mask) / masked_rms(
            weak.opd_at(0.0),
            mask,
        )
        # Same seed, same unit noise: amplitude scales exactly with the
        # von Kármán PSD, i.e. (r0_strong / r0_weak) ** (-5/6).
        assert rms_ratio == pytest.approx((0.10 / 0.20) ** (-5.0 / 6.0), rel=1.0e-6)

    def test_r0_reference_wavelength_defines_the_same_physical_atmosphere(self):
        reference = _model(
            _config(
                r0_m=0.10,
                r0_reference_wavelength_m=500.0e-9,
                wind_m_per_s=(0.0, 0.0),
            )
        )
        rescaled = _model(
            _config(
                r0_m=0.10 * (1000.0 / 500.0) ** (6.0 / 5.0),
                r0_reference_wavelength_m=1000.0e-9,
                wind_m_per_s=(0.0, 0.0),
            )
        )
        first = reference.opd_at(0.0)
        second = rescaled.opd_at(0.0)
        scale_m = float(np.nanmax(np.abs(first)))
        assert np.allclose(
            first,
            second,
            rtol=1.0e-9,
            atol=1.0e-9 * scale_m,
            equal_nan=True,
        )

    def test_opd_is_invariant_under_the_phase_conversion_wavelength(self):
        """Only the HCIPy query/conversion wavelength changes; OPD must not."""

        times = (0.0, 0.006)
        base = _model(
            _config(phase_conversion_reference_wavelength_m=500.0e-9)
        )
        other = _model(
            _config(phase_conversion_reference_wavelength_m=850.0e-9)
        )
        for first, second in zip(_frames(base, times), _frames(other, times)):
            scale_m = float(np.nanmax(np.abs(first)))
            assert np.allclose(
                first,
                second,
                rtol=1.0e-12,
                atol=1.0e-12 * scale_m,
                equal_nan=True,
            )

    def test_structure_function_matches_kolmogorov_scaling(self):
        """Piston-removed phase structure function is sane at small lags."""

        pixels = 48
        r0_m = 0.15
        config = HcipyAtmosphereConfig.single_layer(
            r0_m=r0_m,
            outer_scale_m=100.0,
            wind_m_per_s=(0.0, 0.0),
            kind="finite",
            r0_reference_wavelength_m=WAVELENGTH_M,
            phase_conversion_reference_wavelength_m=WAVELENGTH_M,
            root_seed=101,
        )
        model = _square_model(config, pixels)
        spacing_m = _geometry(pixels).pixel_spacing_xy_m[0]

        for lag_px in (2, 4):
            estimates = []
            for realization in range(6):
                model.reset(realization_index=realization)
                phase_rad = opd_to_phase(model.opd_at(0.0), WAVELENGTH_M)
                differences = phase_rad[:, lag_px:] - phase_rad[:, :-lag_px]
                estimates.append(float(np.mean(differences**2)))
            lag_m = lag_px * spacing_m
            kolmogorov = 6.88 * (lag_m / r0_m) ** (5.0 / 3.0)
            ratio = float(np.mean(estimates)) / kolmogorov
            assert 0.35 < ratio < 1.8


class TestMultiLayer:
    def test_independent_layers_add_in_variance(self):
        layer = HcipyAtmosphereLayerConfig(
            r0_m=0.20,
            outer_scale_m=20.0,
            wind_m_per_s=(0.0, 0.0),
        )
        single = _model(
            HcipyAtmosphereConfig(layers=(layer,), root_seed=7)
        )
        double = _model(
            HcipyAtmosphereConfig(layers=(layer, layer), root_seed=7)
        )
        mask = single.pupil_mask

        # Layer 0 derives from the same stream in both models, so the double
        # model is exactly the single screen plus one independent screen of
        # equal strength; the variance ratio averages to about two.
        assert (
            double.metadata["layer_random_stream_ids"][0]
            == single.metadata["layer_random_stream_ids"][0]
        )
        single_vars = []
        double_vars = []
        for realization in range(16):
            single.reset(realization_index=realization)
            double.reset(realization_index=realization)
            single_vars.append(masked_rms(single.opd_at(0.0), mask) ** 2)
            double_vars.append(masked_rms(double.opd_at(0.0), mask) ** 2)
        ratio = float(np.mean(double_vars) / np.mean(single_vars))
        assert 1.3 < ratio < 2.8

    def test_layers_use_independent_random_streams(self):
        layer = HcipyAtmosphereLayerConfig(r0_m=0.20, wind_m_per_s=(0.0, 0.0))
        model = _model(HcipyAtmosphereConfig(layers=(layer, layer), root_seed=7))
        ids = model.metadata["layer_random_stream_ids"]
        assert len(ids) == 2
        assert ids[0] != ids[1]

    def test_mixed_kind_multi_layer_model_evolves(self):
        config = HcipyAtmosphereConfig(
            layers=(
                HcipyAtmosphereLayerConfig(
                    r0_m=0.25,
                    wind_m_per_s=(3.0, 0.0),
                    kind="infinite",
                ),
                HcipyAtmosphereLayerConfig(
                    r0_m=0.25,
                    wind_m_per_s=(-1.0, 6.0),
                    altitude_m=5000.0,
                    kind="finite",
                ),
            ),
            root_seed=7,
        )
        model = _model(config)
        first = model.opd_at(0.0)
        second = model.opd_at(0.02)
        assert model.metadata["n_layers"] == 2
        assert not np.allclose(first, second, equal_nan=True)

    def test_total_r0_combines_layer_strengths(self):
        layer = HcipyAtmosphereLayerConfig(r0_m=0.20)
        config = HcipyAtmosphereConfig(layers=(layer, layer))
        assert config.total_r0_m == pytest.approx(
            0.20 * 2.0 ** (-3.0 / 5.0),
            rel=1.0e-12,
        )


class TestMetadata:
    def test_metadata_exposes_the_complete_ao_ref_014_identity(self):
        model = _model()
        metadata = model.metadata

        assert metadata["backend_name"] == "hcipy"
        assert metadata["config_hash"] == model.config_hash
        assert metadata["hcipy_version"] == hcipy_version()
        assert metadata["root_seed"] == 7
        assert type(metadata["realization_index"]) is int
        assert metadata["realization_index"] == 0
        assert metadata["random_stream_id"]
        assert metadata["opd_unit"] == "m"
        assert metadata["outside_pupil_fill"] == "nan"
        assert metadata["grid_shape"] == (32, 32)
        assert metadata["pupil_geometry_hash"] == _geometry(32).geometry_hash
        assert metadata["pupil_mask_hash"]
        assert metadata["r0_reference_wavelength_m"] == WAVELENGTH_M
        assert (
            metadata["phase_conversion_reference_wavelength_m"] == WAVELENGTH_M
        )
        assert metadata["wind_convention"] == WIND_CONVENTION
        assert metadata["scintillation"] is False

        (layer,) = metadata["layers"]
        assert layer["kind"] == "infinite"
        assert layer["r0_m"] == 0.15
        assert layer["outer_scale_m"] == 20.0
        assert layer["wind_m_per_s"] == (5.0, -2.0)
        assert layer["altitude_m"] == 0.0
        assert layer["integrated_cn_squared_m_1_3"] > 0.0
        assert layer["random_stream_id"]

    def test_the_two_reference_wavelengths_are_recorded_distinctly(self):
        model = _model(
            _config(
                r0_reference_wavelength_m=500.0e-9,
                phase_conversion_reference_wavelength_m=850.0e-9,
            )
        )
        metadata = model.metadata
        assert metadata["r0_reference_wavelength_m"] == 500.0e-9
        assert metadata["phase_conversion_reference_wavelength_m"] == 850.0e-9

    def test_metadata_is_immutable_and_json_serializable(self):
        model = _model()
        with pytest.raises(TypeError):
            model.metadata["backend_name"] = "other"  # type: ignore[index]
        json.dumps(_plain_json(model.metadata))

    def test_config_hash_tracks_physical_and_conversion_identity(self):
        baseline = _model().config_hash
        assert _model().config_hash == baseline
        assert _model(_config(r0_m=0.16)).config_hash != baseline
        assert _model(_config(root_seed=8)).config_hash != baseline
        assert (
            _model(
                _config(phase_conversion_reference_wavelength_m=850.0e-9)
            ).config_hash
            != baseline
        )


class TestValidation:
    def test_layer_configuration_rejects_invalid_physics(self):
        with pytest.raises(HcipyAtmosphereError, match="r0_m"):
            HcipyAtmosphereLayerConfig(r0_m=0.0)
        with pytest.raises(HcipyAtmosphereError, match="outer_scale_m"):
            HcipyAtmosphereLayerConfig(r0_m=0.15, outer_scale_m=-1.0)
        with pytest.raises(HcipyAtmosphereError, match="wind_m_per_s"):
            HcipyAtmosphereLayerConfig(r0_m=0.15, wind_m_per_s=(1.0,))  # type: ignore[arg-type]
        with pytest.raises(HcipyAtmosphereError, match="altitude_m"):
            HcipyAtmosphereLayerConfig(r0_m=0.15, altitude_m=-10.0)
        with pytest.raises(HcipyAtmosphereError, match="kind"):
            HcipyAtmosphereLayerConfig(r0_m=0.15, kind="periodic")  # type: ignore[arg-type]

    def test_infinite_outer_scale_normalizes_to_none(self):
        assert HcipyAtmosphereLayerConfig(r0_m=0.15, outer_scale_m=None).outer_scale_m is None
        assert (
            HcipyAtmosphereLayerConfig(
                r0_m=0.15,
                outer_scale_m=float("inf"),
            ).outer_scale_m
            is None
        )

    def test_model_configuration_rejects_invalid_composition(self):
        layer = HcipyAtmosphereLayerConfig(r0_m=0.15)
        with pytest.raises(HcipyAtmosphereError, match="layers"):
            HcipyAtmosphereConfig(layers=())
        with pytest.raises(HcipyAtmosphereError, match="layers"):
            HcipyAtmosphereConfig(layers=(layer, object()))  # type: ignore[arg-type]
        with pytest.raises(HcipyAtmosphereError, match="root_seed"):
            HcipyAtmosphereConfig(layers=(layer,), root_seed=-1)
        with pytest.raises(
            HcipyAtmosphereError,
            match="r0_reference_wavelength_m",
        ):
            HcipyAtmosphereConfig(layers=(layer,), r0_reference_wavelength_m=0.0)

    def test_model_construction_rejects_inconsistent_inputs(self):
        geometry = _geometry(32)
        with pytest.raises(HcipyAtmosphereError, match="HcipyAtmosphereConfig"):
            HcipyVonKarmanAtmosphere(object(), geometry)  # type: ignore[arg-type]
        with pytest.raises(HcipyAtmosphereError, match="PupilGeometry"):
            HcipyVonKarmanAtmosphere(_config(), object())  # type: ignore[arg-type]
        with pytest.raises(HcipyAtmosphereError, match="shape"):
            HcipyVonKarmanAtmosphere(
                _config(),
                geometry,
                pupil_mask=np.ones((16, 16), dtype=bool),
            )
        with pytest.raises(HcipyAtmosphereError, match="root_seed"):
            HcipyVonKarmanAtmosphere(
                _config(root_seed=7),
                geometry,
                random_streams=NamedRandomStreams(8),
            )
        with pytest.raises(HcipyAtmosphereError, match="realization_index"):
            _model().reset(realization_index=-1)


class TestSharedLoopRunner:
    """The common component loop switches atmosphere backends by configuration."""

    @staticmethod
    def _atmosphere_from_configuration(atmosphere_backend: str, geometry, root_seed: int):
        """Tiny configuration dispatch mirroring a profile-level selection."""

        from shwfs_ao.backends.native.atmosphere import (
            FrozenFlowAtmosphere,
            FrozenFlowAtmosphereConfig,
        )

        pupil = geometry.pupil_geometry
        if atmosphere_backend == "native_frozen_flow":
            return FrozenFlowAtmosphere(
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
        if atmosphere_backend == "hcipy_von_karman":
            return HcipyVonKarmanAtmosphere(
                HcipyAtmosphereConfig.single_layer(
                    r0_m=0.15,
                    outer_scale_m=20.0,
                    wind_m_per_s=(5.0, 0.0),
                    root_seed=root_seed,
                ),
                pupil,
                pupil_mask=geometry.pupil_mask,
            )
        raise AssertionError(f"unknown atmosphere backend {atmosphere_backend!r}")

    @pytest.mark.parametrize(
        "atmosphere_backend",
        ("native_frozen_flow", "hcipy_von_karman"),
    )
    def test_common_loop_runs_native_and_hcipy_atmospheres(
        self,
        atmosphere_backend,
    ):
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
        from shwfs_ao.dm import DMConfig, build_native_deformable_mirror
        from shwfs_ao.wfs.shack_hartmann.geometric import (
            NativeGeometricShackHartmannSensor,
        )
        from shwfs_ao.wfs.shack_hartmann.geometry import (
            build_shack_hartmann_geometry,
        )

        root_seed = 23
        streams = NamedRandomStreams(root_seed)
        geometry = build_shack_hartmann_geometry(
            telescope_diameter_m=1.0,
            pupil_shape=(16, 16),
            n_lenslets_across=3,
            min_fill_fraction=0.3,
        )
        wfs = NativeGeometricShackHartmannSensor(geometry)
        dm = build_native_deformable_mirror(
            geometry.x_m,
            geometry.y_m,
            geometry.pupil_mask,
            DMConfig(
                telescope_diameter_m=1.0,
                n_actuators_across=3,
                coupling_width_pitch=0.35,
                stroke_limit_nm=250.0,
                actuator_margin_fraction=0.0,
            ),
        )
        interaction_matrix = calibrate_interaction_matrix(
            DmActuatorProbeBasis(dm),
            wfs,
            amplitude_m=10.0e-9,
            random_streams=streams.scoped("calibration-probe"),
            include_noise=False,
        )
        atmosphere = self._atmosphere_from_configuration(
            atmosphere_backend,
            geometry,
            root_seed,
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

        expected_backend = (
            "native" if atmosphere_backend == "native_frozen_flow" else "hcipy"
        )
        assert history.metadata["backend_names"]["atmosphere"] == expected_backend
        assert history.n_steps == 3
        assert np.all(np.isfinite(history.post_update_residual_opd_rms_m))


def _shifted_correlation(
    first: np.ndarray,
    second: np.ndarray,
    *,
    dx: int,
    dy: int,
    margin: int,
) -> float:
    """Correlate ``second`` with ``first`` translated by ``(dx, dy)`` pixels."""

    rolled = np.roll(np.roll(first, dy, axis=0), dx, axis=1)
    a = second[margin:-margin, margin:-margin].ravel()
    b = rolled[margin:-margin, margin:-margin].ravel()
    a = a - np.mean(a)
    b = b - np.mean(b)
    return float(np.sum(a * b) / np.sqrt(np.sum(a**2) * np.sum(b**2)))


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
