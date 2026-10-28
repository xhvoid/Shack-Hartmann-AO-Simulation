"""ESO-07: benchmark tiers through the canonical SCAO factory and runner.

The CI tier runs here; medium and full-scale tiers are ``elt_scale`` tests that
only run with ``--enable-elt-scale`` after a reviewed resource estimate.
"""

from __future__ import annotations

from dataclasses import replace
import json

import numpy as np
import pytest

from shwfs_ao.calibration import DmActuatorProbeBasis, calibrate_interaction_matrix
from shwfs_ao.calibration.reconstructors import TikhonovReconstructor
from shwfs_ao.backends.native.dm import NativeDmBackend
from shwfs_ao.backends.native.shwfs import NativeShackHartmannOptics
from shwfs_ao.control import ControlledSubsetCommandProjector, LeakyIntegratorController
from shwfs_ao.control.loop import run_closed_loop as run_component_loop
from shwfs_ao.core.random import NamedRandomStreams
from shwfs_ao.dm import DeformableMirror
from shwfs_ao.experiments import eso_scao_benchmark as benchmark
from shwfs_ao.experiments import scao
from shwfs_ao.runtime.resource_guard import GIB, HostSnapshot, MemoryPressure, preflight
from shwfs_ao.wfs.shack_hartmann.geometry import build_shack_hartmann_geometry
from shwfs_ao.wfs.shack_hartmann.measurement import DetectorShackHartmannSensor


def _refuse_build(*args, **kwargs):
    raise AssertionError("the system must not be built")


def _require_large_run_enabled(request: pytest.FixtureRequest) -> None:
    """Refuse inside the test too, so a bundle without the repository
    conftest (the wheel smoke) can never run a large tier by marker alone."""

    if not request.config.getoption("--enable-elt-scale", default=False):
        pytest.skip("elt_scale test needs --enable-elt-scale")


def test_tiers_declare_their_frame_counts_and_large_runs_are_refused(monkeypatch, tmp_path):
    expected = {"ci": 32, "medium": 200, "medium-gate": 120, "full": 20, "reference": 2000}
    for tier, steps in expected.items():
        assert benchmark.tier_config(tier).controller.n_steps == steps
    weak = benchmark.tier_config("medium-gate")
    assert weak.atmosphere.r0_m == 0.40
    monkeypatch.setattr(scao, "build_scao_system", _refuse_build)
    for tier in sorted(benchmark.LARGE_TIERS):
        with pytest.raises(benchmark.LargeRunNotEnabled):
            benchmark.run_tier(tier, output_dir=tmp_path / tier)
        assert not (tmp_path / tier).exists()
    # A run shorter than its burn-in would select no science frame; it is
    # refused before the build instead of after the loop.
    for steps, burn_in in ((20, None), (20, 20), (32, -1)):
        with pytest.raises(ValueError, match="leaves no science frame"):
            benchmark.run_tier(
                "medium" if burn_in is None else "ci",
                output_dir=tmp_path / "short",
                n_steps=steps,
                burn_in_frames=burn_in,
                enable_large_run=True,
            )
    assert not (tmp_path / "short").exists()


def test_dry_run_estimates_never_build_and_full_scale_is_refused_on_a_desktop(
    monkeypatch, tmp_path, capsys
):
    from shwfs_ao.backends.native import dm_operator

    monkeypatch.setattr(scao, "build_scao_system", _refuse_build)
    monkeypatch.setattr(dm_operator.LinearSplineDmOperator, "__init__", _refuse_build)
    records = {tier: benchmark.dry_run_record(tier) for tier in benchmark.TIERS}
    full = records["full"]["estimate"]
    assert full["required_bytes"] > 2 * GIB
    assert records["ci"]["estimate"]["required_bytes"] < 512 * 1024**2
    desktop = HostSnapshot(
        platform="test", machine="test", cpu_count=8, physical_bytes=16 * GIB,
        available_bytes=8 * GIB, available_source="stub",
        pressure=MemoryPressure(level="normal", raw="1", source="stub"),
        timestamp_unix_s=0.0,
    )
    estimate = benchmark.estimate_tier(benchmark.tier_config("full"))
    decision = preflight(estimate, snapshot=desktop)
    assert not decision.accepted and decision.budget_bytes == 2 * GIB
    # The command line refuses a large tier without --enable-large-run.
    assert benchmark.main(["--tier", "full", "--output-dir", str(tmp_path / "f")]) == 3
    assert "NOT_RUN_RESOURCE_POLICY" in capsys.readouterr().out
    assert benchmark.main(["--tier", "reference", "--dry-run"]) == 0


@pytest.fixture(scope="module")
def ci_manifest(tmp_path_factory):
    output = tmp_path_factory.mktemp("ci")
    return benchmark.run_tier("ci", output_dir=output, verify_observer_neutrality=True), output


def test_ci_tier_runs_end_to_end_and_records_its_evidence(ci_manifest):
    manifest, output = ci_manifest
    assert manifest["profile"] == "eso_scao_smoke_5m_software@2"
    counts = manifest["counts"]["actuators"]
    assert counts["calibrated_coordinates"] + sum(counts["excluded_by_reason"].values()) == (
        counts["retained_layout"]
    )
    assert counts["nominal"] == 121 and manifest["counts"]["lenslets"]["nominal"] == 100
    loop = manifest["loop"]
    assert loop["max_saturation_fraction"] == 0.0  # A08: finite stroke never reached
    assert loop["reconstruction_usable_fraction"] == 1.0
    assert loop["mean_post_burn_in_residual_rms_nm"] < 0.3 * loop["mean_open_loop_rms_nm"]
    assert manifest["observer_neutrality"]["passed"]
    assert manifest["solver"]["rejected"] == 0
    # The travel record describes the recorded run: the fastest layer over the
    # 31 frame intervals, not the one-frame timing probe that follows it.
    config = benchmark.tier_config("ci")
    fastest = max(float(np.hypot(*layer.wind_m_per_s)) for layer in config.atmosphere.layers)
    travel = fastest * (config.controller.n_steps - 1) / config.controller.frame_rate_hz
    assert manifest["atmosphere"]["max_travel_m"] == pytest.approx(travel, rel=1e-12)
    assert not manifest["atmosphere"]["periodic_band_repeated"]
    for metrics in manifest["science"]["metrics"]:
        assert 0.0 < metrics["peak_strehl"] <= 1.0
        assert np.isfinite(metrics["ee80_radius_rad"])
        assert metrics["flux_denominator"] == "normalized_source_grid_flux"
    assert manifest["timing_semantics"]["measured_to_first_seen_delay_frames"] == 3
    assert set(manifest["ledgers"]) == {
        "benchmarks/eso_scao_source_ledger.v1.json",
        "benchmarks/eso_drm_42m_scao_derived.assumptions.v2.json",
    }
    for name in ("manifest.json", "telemetry.npz", *manifest["science_files"].values()):
        assert (output / name).is_file()
    with np.load(output / "telemetry.npz") as telemetry:
        assert telemetry["applied_command_history_opd_m"].shape == (32, counts["retained_layout"])


def test_repeated_ci_runs_reproduce_their_outputs(ci_manifest, tmp_path):
    first, _ = ci_manifest
    second = benchmark.run_tier("ci", output_dir=tmp_path)
    assert second["loop"]["loop_hash"] == first["loop"]["loop_hash"]
    assert second["telemetry_sha256"] == first["telemetry_sha256"]
    assert second["science_sha256"] == first["science_sha256"]
    assert second["system_component_hashes"] == first["system_component_hashes"]


def test_calibration_cache_reuse_keeps_identity_and_skips_calibration(monkeypatch, tmp_path):
    cache = tmp_path / "cache"
    fresh = benchmark.run_tier("ci", output_dir=tmp_path / "a", calibration_cache_dir=cache)
    assert not fresh["calibration"]["reused_from_cache"]
    monkeypatch.setattr(scao, "calibrate_sparse_interaction_matrix", _refuse_build)
    reused = benchmark.run_tier("ci", output_dir=tmp_path / "b", calibration_cache_dir=cache)
    assert reused["calibration"]["reused_from_cache"]
    assert reused["calibration"]["calibration_hash"] == fresh["calibration"]["calibration_hash"]
    assert reused["system_component_hashes"] == fresh["system_component_hashes"]
    assert reused["telemetry_sha256"] == fresh["telemetry_sha256"]
    # A tampered cache entry fails closed instead of recalibrating.
    entry = next(cache.glob("sparse_calibration_*.json"))
    record = json.loads(entry.read_text())
    record["data"][0] *= 1.001
    entry.write_text(json.dumps(record))
    with pytest.raises(scao.ScaoConstructionError, match="content hash|unreadable"):
        benchmark.run_tier("ci", output_dir=tmp_path / "c", calibration_cache_dir=cache)


def test_symmetric_window_removes_the_centroid_bias():
    """The A05c revision: a symmetric spot must read zero slope.

    Every lenslet gets the same symmetric local defocus, whose true mean slope
    is zero.  On version 1's even 24-pixel window the centre of gravity reads a
    negative slope (the canvas has one more pixel on the negative side of the
    axis pixel); on version 2's 23-pixel window it reads exactly zero.
    """

    from shwfs_ao.io.configs import load_system_profile

    readings = {}
    for version in (1, 2):
        config = load_system_profile("eso_scao_smoke_5m_software", version)
        system = scao.build_scao_system(replace(config, controller=replace(config.controller, n_steps=2)))
        geometry = system.wfs.geometry
        opd = np.zeros(geometry.pupil_shape)
        for (r0, r1, c0, c1), (xc, yc) in zip(
            geometry.lenslet_bounds_rc, geometry.subaperture_centers_m
        ):
            dx = geometry.x_m[r0:r1, c0:c1] - xc
            dy = geometry.y_m[r0:r1, c0:c1] - yc
            opd[r0:r1, c0:c1] = 4.0e-7 * (dx * dx + dy * dy) / 0.25**2
        measurement = system.wfs.measure(
            opd, random_streams=system.random_streams, include_noise=False
        )
        slopes = measurement.vector.values.reshape(-1, 2)[measurement.valid_subapertures]
        readings[version] = slopes.mean(axis=0)
    assert np.all(readings[1] < -1e-3)
    np.testing.assert_allclose(readings[2], 0.0, atol=1e-12)


def test_batch_size_is_outside_every_identity():
    config = benchmark.tier_config("ci")
    small = scao.build_scao_system(config, execution=scao.ScaoExecutionOptions(lenslet_batch_size=1))
    large = scao.build_scao_system(config, execution=scao.ScaoExecutionOptions(lenslet_batch_size=4096))
    assert dict(small.component_hashes) == dict(large.component_hashes)


def test_noiseless_slopes_are_invariant_to_the_electron_scale():
    config = benchmark.tier_config("ci")
    systems = [
        scao.build_scao_system(
            replace(config, detector=replace(config.detector, photons_per_subap_frame=photons))
        )
        for photons in (1.0e4, 1.0e5, 1.0e6)
    ]
    system = systems[0]
    system.atmosphere.reset(realization_index=0)
    opd = np.asarray(system.atmosphere.opd_at(0.0)) * 0.05
    measurements = [
        s.wfs.measure(opd, random_streams=s.random_streams, include_noise=False) for s in systems
    ]
    for other in measurements[1:]:
        np.testing.assert_array_equal(other.vector.valid_rows, measurements[0].vector.valid_rows)
        np.testing.assert_allclose(
            other.vector.values, measurements[0].vector.values, rtol=0.0, atol=1e-12
        )
    # The noiseless response identity does not depend on the scale either.
    assert len({s.wfs.response_hash for s in systems}) == 1


def test_scalable_ci_system_matches_an_independent_dense_assembly():
    """Dense geometry, dense optics, dense influences, dense SVD Tikhonov."""

    config = replace(
        benchmark.tier_config("ci"),
        controller=replace(benchmark.tier_config("ci").controller, n_steps=12),
    )
    system = scao.build_scao_system(config)
    dm = system.dm
    geometry = build_shack_hartmann_geometry(
        telescope_diameter_m=config.telescope_diameter_m,
        pupil_shape=(config.pupil_pixels, config.pupil_pixels),
        n_lenslets_across=config.lenslets_across,
        min_fill_fraction=config.wfs.min_fill_fraction,
        central_obstruction_ratio=config.wfs.central_obstruction_ratio,
    )
    streams = NamedRandomStreams(config.random.root_seed)
    sensor = DetectorShackHartmannSensor.calibrate(
        geometry,
        NativeShackHartmannOptics(
            geometry,
            config.wfs_wavelength_m,
            pad_factor=config.wfs.pad_factor,
            detector_window_px=config.wfs.detector_window_px,
        ),
        scao._detector_config(config),
        wfs_wavelength_m=config.wfs_wavelength_m,
        random_streams=streams.scoped("native-detector-wfs"),
        centroid_config=scao._centroid_config(config),
        validity_config=scao._validity_config(config),
    )
    dense_dm = DeformableMirror(
        dm.config,
        NativeDmBackend(np.asarray(dm.influence_functions)),
        actuator_ids=dm.actuator_ids,
        actuator_centers_m=dm.actuator_centers_m,
        actuator_pitch_m=dm.actuator_pitch_m,
        x_m=dm.x_m,
        y_m=dm.y_m,
        pupil_mask=dm.pupil_mask,
    )
    coordinates = system.interaction_matrix.coordinate_ids
    matrix = calibrate_interaction_matrix(
        DmActuatorProbeBasis(dense_dm, coordinate_ids=coordinates),
        sensor,
        config.calibration.amplitude_m,
        random_streams=streams.scoped("scao-interaction-calibration"),
    )
    np.testing.assert_allclose(
        system.interaction_matrix.to_dense(), matrix.matrix, rtol=0.0,
        atol=1e-12 * np.nanmax(np.abs(matrix.matrix)),
    )
    reconstructor = TikhonovReconstructor(
        matrix, system.reconstructor.damping_absolute, min_valid_fraction=0.5,
        min_rank=1, max_cached_masks=4,
    )
    loop_config = scao._loop_config(config)
    dense_history = run_component_loop(
        loop_config,
        random_streams=streams,
        atmosphere=system.atmosphere,
        wfs=sensor,
        dm=dense_dm,
        interaction_matrix=matrix,
        reconstructor=reconstructor,
        command_projector=ControlledSubsetCommandProjector(coordinates, dense_dm.actuator_ids),
        controller=LeakyIntegratorController.from_loop_config(dense_dm.actuator_ids, loop_config),
        include_noise=False,
    )
    scalable_history = scao.run_closed_loop(config, system=system)
    # LSMR stops at atol = btol = 1e-8, which leaves per-frame command errors
    # up to ~1e-5 relative to the exact Tikhonov solve (the ESO-06 target);
    # integrated over 12 frames the residual RMS agrees to 1.5e-5 relative
    # (3e-12 m) on version 2, so the gate is 1e-4.
    np.testing.assert_allclose(
        scalable_history.post_update_residual_opd_rms_m,
        dense_history.post_update_residual_opd_rms_m,
        rtol=1e-4,
    )
    applied = scalable_history.applied_command_history_opd_m
    reference = dense_history.applied_command_history_opd_m
    columns = [dm.actuator_ids.index(identifier) for identifier in coordinates]
    difference = applied[:, columns] - reference[:, columns]
    # DM piston is (nearly) unsensed: LSMR stopped at 1e-8 leaves a small
    # unconverged piston component that the exact Tikhonov solve does not.  It
    # changes neither the piston-removed residual nor the image, so commands are
    # compared after removing each frame's mean over the calibrated actuators.
    piston = difference.mean(axis=1, keepdims=True)
    scale = np.max(np.abs(applied))
    np.testing.assert_allclose(difference - piston, 0.0, rtol=0.0, atol=1e-5 * scale)
    assert np.max(np.abs(piston)) < 1e-2 * scale
    excluded = [index for index in range(dm.n_actuators) if index not in set(columns)]
    assert np.all(applied[:, excluded] == 0.0) and np.all(reference[:, excluded] == 0.0)


@pytest.mark.elt_scale
@pytest.mark.parametrize("tier", ("medium", "medium-gate"))
def test_medium_tiers_close_the_loop_with_full_retained_coordinates(tier, tmp_path, request):
    _require_large_run_enabled(request)
    manifest = benchmark.run_tier(
        tier,
        output_dir=tmp_path / tier,
        calibration_cache_dir=tmp_path / "cache",
        enable_large_run=True,
    )
    assert manifest["loop"]["max_saturation_fraction"] == 0.0
    if tier == "medium-gate":
        assert manifest["gates"]["control_gate"]["passed"]
    reused = benchmark.run_tier(
        tier,
        output_dir=tmp_path / f"{tier}-reused",
        calibration_cache_dir=tmp_path / "cache",
        enable_large_run=True,
        n_steps=20,
        burn_in_frames=10,
    )
    assert reused["calibration"]["reused_from_cache"]


@pytest.mark.elt_scale
def test_full_spatial_scale_capability(tmp_path, request):
    _require_large_run_enabled(request)
    manifest = benchmark.run_tier("full", output_dir=tmp_path, enable_large_run=True)
    assert manifest["gates"]["capability_gate"]["passed"]
    assert manifest["counts"]["actuators"]["calibrated_coordinates"] > 4000
