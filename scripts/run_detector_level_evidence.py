"""Run the detector-level evidence experiments and write JSON records.

Subcommands
-----------
``gain-scan``  predeclared controller-gain scan (DET-09, B11) for the 2 m
               profiles and, on the ``ci`` geometry, for the 12 m and 42 m
               detector physics.
``e1``         centroid-noise Monte Carlo per camera type (DET-07 harness).
``e2``         open-loop slope- and reconstruction-noise propagation, 2 m.
``ensemble``   noise-on closed loops over independent root seeds, 2 m.
``cost``       per-feature SH measurement time per frame, 2 m and ci tiers.

Every record stores the command, versions, configuration hashes and seeds.
``e2-12m``, ``e3``, ``e4``, ``e6``, ``det08`` (12 m) and ``e5`` (42 m) are the
gated runs of prompt section 2.5.  They were enabled by the user on
2026-10-16; anyone rerunning them must obtain the same enablement.
"""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
import platform
import sys
import time
from typing import Any

import numpy as np


EVIDENCE_DIR = Path(__file__).resolve().parents[1] / "docs/refactor/detector_level_evidence"
GAINS = (0.2, 0.3, 0.4, 0.5)
TWO_METRE_PROFILES = (
    "det_ccd_2m_synthetic",
    "det_emccd_2m_synthetic",
    "det_cmos_2m_synthetic",
    "det_emccd_2m_plane_synthetic",
)


def _header(command: str) -> dict[str, Any]:
    import scipy

    return {
        "command": command,
        "argv": sys.argv,
        "python": sys.version,
        "numpy": np.__version__,
        "scipy": scipy.__version__,
        "machine": platform.machine(),
        "started_unix_s": time.time(),
    }


def _write(name: str, record: dict[str, Any]) -> Path:
    EVIDENCE_DIR.mkdir(parents=True, exist_ok=True)
    path = EVIDENCE_DIR / name
    path.write_text(json.dumps(record, indent=2, default=float) + "\n")
    print(f"wrote {path}")
    return path


def gain_scan(arguments: argparse.Namespace) -> None:
    from shwfs_ao.experiments.detector_level import derive_physical_config, gain_scan as scan
    from shwfs_ao.io.configs import load_system_profile

    record = _header("gain-scan")
    results = []
    for name in TWO_METRE_PROFILES:
        config = load_system_profile(name, 1)
        result = scan(config, GAINS, realizations=(0, 1, 2))
        results.append(result)
        print(name, "selected", result["selected_gain"], flush=True)
    smoke = load_system_profile("eso_scao_smoke_5m_software", 2)
    for name in ("det_emccd_12m_medium_derived", "det_ccd_42m_r3band_derived"):
        physics = load_system_profile(name, 1)
        derived = derive_physical_config(smoke, physics, label=f"scan_ci_{name}")
        result = scan(derived, GAINS, realizations=(0, 1, 2), n_steps=60)
        result["scan_tier_for"] = f"{name}@1"
        results.append(result)
        print(name, "(ci geometry) selected", result["selected_gain"], flush=True)
    record["results"] = results
    record["wall_s"] = time.time() - record["started_unix_s"]
    _write("det09_gain_scan.json", record)


E1_FLUXES = (10.0, 30.0, 100.0, 300.0, 1.0e3, 3.0e3, 1.0e4, 3.0e4, 1.0e5)
E1_CAMERAS = (("synthetic_ccd", 1), ("synthetic_emccd", 1), ("synthetic_cmos", 1))


def _slope(fluxes: list[float], sigmas: list[float]) -> float | None:
    points = [(math.log(f), math.log(s)) for f, s in zip(fluxes, sigmas) if s > 0 and math.isfinite(s)]
    if len(points) < 2:
        return None
    x = np.array([p[0] for p in points])
    y = np.array([p[1] for p in points])
    return float(np.polyfit(x, y, 1)[0])


def e1(arguments: argparse.Namespace) -> None:
    from dataclasses import replace

    from shwfs_ao.detector.centroid import CentroidConfig
    from shwfs_ao.detector.processing import PixelProcessingConfig
    from shwfs_ao.experiments.detector_noise import (
        NoiseFixture,
        calibration_trials,
        gaussian_spot,
        model_prediction,
        summarize_trials,
        temporal_trials,
    )
    from shwfs_ao.io.camera_presets import load_camera_preset

    record = _header("e1")
    processing = PixelProcessingConfig(
        mode="estimated", n_bias_frames=32, n_dark_frames=32, n_sky_frames=32, n_flat_frames=32,
        flat_level_e=1000.0, hot_pixel_threshold_e=1.0e9,
    )
    variants = {
        "plain": dict(sky=0.0, centroid=CentroidConfig(), clip=False, trials=10_000),
        "background": dict(sky=5.0, centroid=CentroidConfig(), clip=False, trials=10_000),
        "thresholded": dict(sky=5.0, centroid=CentroidConfig(estimator="thresholded_center_of_gravity", threshold_fraction=0.2), clip=False, trials=4_000),
        "negative_clipped": dict(sky=5.0, centroid=CentroidConfig(), clip=True, trials=4_000),
    }
    results = []
    for key in E1_CAMERAS:
        camera = load_camera_preset(*key)
        for name, variant in variants.items():
            proc = replace(processing, clip_negative=variant["clip"])
            points = []
            for flux in E1_FLUXES:
                fixture = NoiseFixture(
                    camera=camera, processing=proc, source_e=gaussian_spot(15, flux, 1.2),
                    window_px=15, sky_e_per_pixel=variant["sky"], exposure_s=1.0e-3,
                    seed=17, centroid=variant["centroid"],
                )
                quality = model_prediction(fixture)
                summary = summarize_trials(temporal_trials(fixture, variant["trials"])["centroids_px"])
                model_sigma = float(np.max(quality.centroid_sigma_xy_px[0]))
                measured = max(summary["std_x_px"], summary["std_y_px"])
                point = {
                    "flux_e": flux,
                    "model_sigma_px": model_sigma,
                    "model_supported": bool(quality.supported[0]),
                    "total_snr": float(quality.total_snr[0]),
                    "measured_sigma_px": measured,
                    "ratio_measured_over_model": measured / model_sigma if model_sigma > 0 else None,
                    "measured_bias_x_px": summary["mean_x_px"] - 7.0,
                    "measured_bias_y_px": summary["mean_y_px"] - 7.0,
                    "invalid_fraction": summary["invalid_fraction"],
                    "trials": summary["trials"],
                    "std_relative_se": summary["std_relative_se"],
                }
                if name == "plain" and flux in (300.0, 3.0e3, 3.0e4):
                    ensemble = calibration_trials(fixture, 200)["centroids_px"]
                    point["calibration_model_sigma_px"] = float(np.max(quality.calibration_sigma_xy_px[0]))
                    point["calibration_measured_sigma_px"] = float(np.max(ensemble.std(axis=0, ddof=1)))
                points.append(point)
                print(key[0], name, flux, f"ratio={point['ratio_measured_over_model']}", flush=True)
            supported = [p for p in points if p["model_supported"]]
            results.append(
                {
                    "camera": f"{key[0]}@{key[1]}",
                    "variant": name,
                    "points": points,
                    "max_abs_ratio_error_supported": (
                        max(abs(p["ratio_measured_over_model"] - 1.0) for p in supported) if supported else None
                    ),
                    "log_slope_low_flux": _slope(E1_FLUXES[:3], [p["measured_sigma_px"] for p in points[:3]]),
                    "log_slope_high_flux": _slope(E1_FLUXES[-3:], [p["measured_sigma_px"] for p in points[-3:]]),
                }
            )
    record["results"] = results
    record["wall_s"] = time.time() - record["started_unix_s"]
    _write("det07_e1_centroid_noise.json", record)


def e2(arguments: argparse.Namespace) -> None:
    from shwfs_ao.experiments.detector_level import open_loop_noise_propagation
    from shwfs_ao.io.configs import load_system_profile

    record = _header("e2")
    record["results"] = []
    for name in TWO_METRE_PROFILES:
        result = open_loop_noise_propagation(load_system_profile(name, 1), trials=4000)
        record["results"].append(result)
        print(name, result["slope_variance_ratio_measured_over_predicted"]["mean"], result["command_trace_ratio"], flush=True)
    record["wall_s"] = time.time() - record["started_unix_s"]
    _write("det09_e2_noise_propagation.json", record)


def ensemble(arguments: argparse.Namespace) -> None:
    from shwfs_ao.experiments.detector_level import seed_ensemble
    from shwfs_ao.io.configs import load_system_profile

    record = _header("ensemble")
    record["results"] = []
    for name in TWO_METRE_PROFILES:
        result = seed_ensemble(load_system_profile(name, 1), (11, 12, 13, 14, 15))
        record["results"].append(result)
        print(name, result["post_update_rms_mean_m"], result["post_update_rms_seed_std_m"], flush=True)
    noiseless = load_system_profile("fast_2m_detector", 4)
    record["reference_compatibility_profile"] = seed_ensemble(noiseless, (11, 12, 13, 14, 15))
    record["wall_s"] = time.time() - record["started_unix_s"]
    _write("det09_closed_loop_ensemble_2m.json", record)


def _sh_time_per_frame(config, frames: int, *, include_noise: bool = True) -> dict[str, float]:
    from shwfs_ao.experiments.scao import build_scao_system

    started = time.perf_counter()
    system = build_scao_system(config)
    build_s = time.perf_counter() - started
    period = 1.0 / config.controller.frame_rate_hz
    system.atmosphere.reset(realization_index=0)
    residuals = []
    for index in range(frames):
        opd = np.asarray(system.atmosphere.opd_at(period * index), dtype=float)
        residuals.append(np.where(np.isfinite(opd), opd, 0.0))
    system.wfs.measure(residuals[0], random_streams=system.random_streams, include_noise=include_noise)
    times = []
    for residual in residuals:
        started = time.perf_counter()
        system.wfs.measure(residual, random_streams=system.random_streams, include_noise=include_noise)
        times.append(time.perf_counter() - started)
    times_array = np.array(times)
    return {
        "build_s": build_s,
        "sh_measure_median_s": float(np.median(times_array)),
        "sh_measure_mean_s": float(times_array.mean()),
        "frames": frames,
    }


def cost(arguments: argparse.Namespace) -> None:
    from dataclasses import replace

    from shwfs_ao.detector.physical_config import BandpassConfig
    from shwfs_ao.experiments.detector_level import derive_physical_config
    from shwfs_ao.io.configs import load_system_profile

    record = _header("cost")
    rows = []
    base_2m = load_system_profile("det_emccd_2m_synthetic", 1)
    plane = load_system_profile("det_emccd_2m_plane_synthetic", 1)
    smoke = load_system_profile("eso_scao_smoke_5m_software", 2)
    medium_physics = load_system_profile("det_emccd_12m_medium_derived", 1)

    def physics_variant(config, **changes):
        physics = config.detector_physics
        return replace(config, detector_physics=replace(physics, **changes))

    variants = [
        ("2m compatibility fast_2m_detector@4 (feature off)", load_system_profile("fast_2m_detector", 4)),
        ("2m physical EMCCD, legacy FFT, estimated products", base_2m),
        ("2m physical EMCCD, oracle products", physics_variant(base_2m, processing=replace(base_2m.detector_physics.processing, mode="oracle"))),
    ]
    for samples in (1, 3, 5, 7):
        bandpass = BandpassConfig(kind="gauss_legendre", band_min_m=6.0e-7, band_max_m=9.0e-7, n_samples=samples)
        variants.append((f"2m MFT k=4, diffusion 0.25, coupling, {samples} wavelength(s)", physics_variant(plane, bandpass=bandpass)))
    for k in (1, 2, 4, 8):
        sampling = replace(plane.detector_physics.sampling, oversampling=k)
        variants.append((f"2m MFT oversampling k={k}, 3 wavelengths", physics_variant(plane, sampling=sampling)))
    variants.append(("ci compatibility eso_scao_smoke_5m_software@2 (feature off)", smoke))
    ci_physics = derive_physical_config(smoke, medium_physics, label="cost_ci_det_emccd_12m_medium_derived")
    variants.append(("ci + 12 m detector physics (MFT k=4, 3 wavelengths, coupled EMCCD)", ci_physics))
    for label, config in variants:
        result = _sh_time_per_frame(config, 20)
        result["variant"] = label
        rows.append(result)
        print(label, f"{1e3 * result['sh_measure_median_s']:.2f} ms", flush=True)
    record["results"] = rows
    record["wall_s"] = time.time() - record["started_unix_s"]
    _write("det10_feature_costs.json", record)


def _gated_series(name: str, command: str, plan: list[tuple[str, Any, int]], *, n_steps: int, burn_in: int, execution: Any) -> None:
    """Run ``(label, config, root_seed)`` entries one at a time, saving after each."""

    from shwfs_ao.experiments.detector_level import science_run, summarize_runs

    from shwfs_ao.experiments.scao import ScaoConstructionError

    path = EVIDENCE_DIR / name
    record = _header(command)
    record["enabled_by_user"] = "2026-10-16: every gated run enabled, one at a time"
    record["n_steps"] = n_steps
    record["burn_in_frames"] = burn_in
    record["runs"] = []
    if path.exists():
        # Resume: keep completed runs of an interrupted series.
        previous = json.loads(path.read_text())
        record["runs"] = list(previous.get("runs", []))
        record["resumed_from_started_unix_s"] = previous.get("started_unix_s")
    done = {(run["label"], run["root_seed"]) for run in record["runs"]}
    for label, config, seed in plan:
        if (label, seed) in done:
            continue
        try:
            result = science_run(config, root_seed=seed, n_steps=n_steps, burn_in_frames=burn_in, execution=execution)
        except ScaoConstructionError as exc:
            # A configuration the system refuses to build (for example a
            # calibration whose rows the validity gates reject) is a result.
            result = {"status": "refused", "reason": str(exc)[:500], "root_seed": seed}
        result["label"] = label
        record["runs"].append(result)
        groups: dict[str, list[dict[str, Any]]] = {}
        for run in record["runs"]:
            if run.get("status") != "refused":
                groups.setdefault(run["label"], []).append(run)
        record["summary"] = {key: summarize_runs(value) for key, value in groups.items()}
        record["refused"] = [
            {"label": run["label"], "root_seed": run["root_seed"], "reason": run["reason"]}
            for run in record["runs"]
            if run.get("status") == "refused"
        ]
        record["wall_s"] = time.time() - record["started_unix_s"]
        _write(name, record)
        if result.get("status") == "refused":
            print(label, seed, "REFUSED", result["reason"][:120], flush=True)
            continue
        print(
            label, seed,
            f"rms={1e9 * result['post_update_rms_m']:.1f}nm valid={result['valid_measurement_fraction']:.3f}",
            f"strehl={result['science'][0]['peak_strehl']:.3f} frame={result['per_frame_s']:.3f}s",
            flush=True,
        )


def _medium(version: int = 1):
    from shwfs_ao.io.configs import load_system_profile

    return load_system_profile("det_emccd_12m_medium_derived", version)


def _summary_execution(**keywords: Any) -> Any:
    from shwfs_ao.experiments.scao import ScaoExecutionOptions

    return ScaoExecutionOptions(telemetry_level="summary", **keywords)


def e2_12m(arguments: argparse.Namespace) -> None:
    from shwfs_ao.experiments.detector_level import open_loop_noise_propagation

    record = _header("e2-12m")
    record["enabled_by_user"] = "2026-10-16"
    result = open_loop_noise_propagation(_medium(), trials=4000, execution=_summary_execution())
    record["results"] = [result]
    record["wall_s"] = time.time() - record["started_unix_s"]
    _write("det09_e2_noise_propagation_12m.json", record)
    print(result["slope_variance_ratio_measured_over_predicted"], result["command_trace_ratio"], flush=True)


def e3(arguments: argparse.Namespace, *, version: int = 1) -> None:
    from shwfs_ao.experiments.detector_level import with_magnitude

    base = _medium(version)
    plan = [
        (f"m{magnitude:g}", with_magnitude(base, magnitude), seed)
        for magnitude in (8.0, 9.0, 10.0, 11.0, 12.0, 13.0)
        for seed in (21, 22, 23, 24, 25)
    ]
    name = "det09_e3_magnitude_scan_12m.json" if version == 1 else f"det09_e3_magnitude_scan_12m_v{version}.json"
    _gated_series(name, f"e3 (profile @{version})", plan, n_steps=400, burn_in=100, execution=_summary_execution())


def e4(arguments: argparse.Namespace, *, version: int = 1) -> None:
    from shwfs_ao.experiments.detector_level import with_magnitude, with_physics

    base = _medium(version)
    plan = []
    for camera in ("synthetic_ccd", "synthetic_emccd", "synthetic_cmos"):
        cam_config = with_physics(base, camera_preset_name=camera, camera_preset_version=1)
        for magnitude in (8.0, 10.0, 12.0):
            for seed in (31, 32, 33):
                plan.append((f"{camera}@1 m{magnitude:g}", with_magnitude(cam_config, magnitude), seed))
    name = "det09_e4_camera_comparison_12m.json" if version == 1 else f"det09_e4_camera_comparison_12m_v{version}.json"
    _gated_series(name, f"e4 (profile @{version})", plan, n_steps=400, burn_in=100, execution=_summary_execution())


def e6(arguments: argparse.Namespace, *, version: int = 1) -> None:
    from dataclasses import replace

    from shwfs_ao.detector.physical_config import BandpassConfig
    from shwfs_ao.experiments.detector_level import with_physics

    base = _medium(version)
    physics = base.detector_physics
    variants = {
        "baseline (MFT k=4, diffusion 0.2, R3 3 nodes, estimated)": base,
        "point sampling (k=1, no diffusion)": with_physics(
            base, sampling=replace(physics.sampling, oversampling=1, diffusion_sigma_px=0.0)
        ),
        "monochromatic 700 nm": with_physics(
            base, bandpass=BandpassConfig(kind="monochromatic", band_min_m=5.5e-7, band_max_m=8.5e-7)
        ),
        "oracle processing": with_physics(base, processing=replace(physics.processing, mode="oracle")),
    }
    plan = [(label, config, seed) for label, config in variants.items() for seed in (41, 42, 43)]
    name = "det09_e6_effect_sizes_12m.json" if version == 1 else f"det09_e6_effect_sizes_12m_v{version}.json"
    _gated_series(name, f"e6 (profile @{version})", plan, n_steps=400, burn_in=100, execution=_summary_execution())


def det08(arguments: argparse.Namespace) -> None:
    from shwfs_ao.experiments.detector_level import with_physics

    base = _medium()
    plan = [
        (f"n_sub={count}", with_physics(base, exposure_subsamples=count), seed)
        for count in (1, 2, 4)
        for seed in (51, 52, 53, 54, 55)
    ]
    _gated_series("det08_exposure_subsamples_12m.json", "det08", plan, n_steps=400, burn_in=100, execution=_summary_execution())


def e5(arguments: argparse.Namespace) -> None:
    from shwfs_ao.io.configs import load_system_profile

    config = load_system_profile("det_ccd_42m_r3band_derived", 1)
    _gated_series(
        "det09_e5_42m_noise_on.json",
        "e5",
        [("det_ccd_42m_r3band_derived@1", config, 1)],
        n_steps=2000,
        burn_in=200,
        execution=_summary_execution(atmosphere_band_storage="regenerate"),
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("gain-scan")
    commands = {
        "gain-scan": gain_scan, "e1": e1, "e2": e2, "ensemble": ensemble, "cost": cost,
        "e2-12m": e2_12m, "e3": e3, "e4": e4, "e6": e6, "det08": det08, "e5": e5,
        "e3-v2": lambda arguments: e3(arguments, version=2),
        "e4-v2": lambda arguments: e4(arguments, version=2),
        "e6-v2": lambda arguments: e6(arguments, version=2),
    }
    for name in commands:
        if name != "gain-scan":
            sub.add_parser(name)
    arguments = parser.parse_args()
    commands[arguments.command](arguments)
    return 0


if __name__ == "__main__":
    sys.exit(main())
