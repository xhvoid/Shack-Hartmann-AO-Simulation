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
gated runs of prompt section 2.5; so are the 12 m recovery, excursion,
noise-isolation and ``-v2``/``-v3`` commands.  A gated command runs only with
``--enabled-by-user`` naming the date and wording of the user's go-ahead for
that run; without it, it refuses before anything runs.  The historical records
were enabled on 2026-10-16 and keep their notes; a resume that adds runs keeps
the series' note and records its own under ``resumed_enabled_by_user``.

``e3-v3`` and ``e4-v3`` rerun E3 and E4 on ``det_emccd_12m_medium_derived@3``
(Tikhonov damping 0.1 and the reset policy), same seeds and settings as @2.

``e3-recovery --arm NAME`` reruns E3 on ``det_emccd_12m_medium_derived@2`` at
m_AB 10, 11 and 12 over root seeds 21-25 with one closed-loop recovery policy
(``controller.recovery``) set in code, or with none (``off``).  Every arm
appends to one record.  The protocol is predeclared in
DETECTOR_LEVEL_DEVELOPMENT_STATUS.md ("Closed-loop recovery policy").

``e3-excursion --arm NAME`` reruns the same E3 matrix with an arm that targets
the trigger of the excursions the reset policy recovers from (reconstructor
damping, acceptance threshold or leak, each with or without the reset).  Every
arm appends to one record; the protocol is predeclared in the status file
("Excursion trigger at m_AB = 11").

``noise-isolation-2m`` (ungated) and ``noise-isolation-12m`` (gated) run
paired noise-on / noiseless-operating loops over magnitudes and seeds to
isolate the temporal detector-noise variance (review 2026-10-16).
``e6-v3`` reruns E6 on ``det_emccd_12m_medium_derived@3`` with a
photometry-matched monochromatic arm (gated).

Records go to the directory named by ``--output-dir PATH`` (created when
needed).  Without it they go to the historical evidence directory,
``docs/refactor/detector_level_evidence``, which is kept as the compatible
default for maintaining that evidence.  Ordinary and verification runs should
name their own directory.  Every record header states the directory it was
written to; no identity depends on it.

Existing records are never replaced silently (review R6).  A command whose
record exists stops unless one of the global options says what to do:
``--output NAME`` writes a fresh record under another file name (a name, not
a directory), ``--overwrite`` replaces a one-shot record, and ``--resume``
continues a gated series.  A resume that finds every planned run already
recorded says so and leaves the record unchanged.  On
resume every saved run must carry the protocol identity this invocation would
give it (configuration hash with seed and frame count, burn-in, execution
options, and the code identity: git HEAD plus a digest of uncommitted source
changes); a mismatch stops the command, and a record without identities
cannot be resumed.  Every retained run, including the runs of other arms,
must share the record's series protocol (version, frames, burn-in, execution
options and code), so arms of ``e3-recovery`` and ``e3-excursion`` append to
one record with ``--resume`` only under the same protocol.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
import platform
import subprocess
import sys
import time
from typing import Any

import numpy as np


REPOSITORY = Path(__file__).resolve().parents[1]
EVIDENCE_DIR = REPOSITORY / "docs/refactor/detector_level_evidence"
# Protocol identity version of gated-series runs (review R6).
SERIES_PROTOCOL_VERSION = 2
# Global options, set by main(): fresh output name, overwrite, resume,
# enablement note and output directory (None selects EVIDENCE_DIR).
OPTIONS = argparse.Namespace(output=None, overwrite=False, resume=False, enabled_by_user=None, output_dir=None)
_STARTED: set[Path] = set()
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
        # Audit metadata: where this invocation writes.  No protocol,
        # configuration or code identity depends on it.
        "output_directory": _output_directory_label(),
        "output_directory_source": "legacy default" if OPTIONS.output_dir is None else "--output-dir",
    }


class EvidenceRecordExists(SystemExit):
    """An evidence record exists and no option says how to treat it."""


class EnablementMissing(SystemExit):
    """A gated run was started without the user's enablement note."""


def output_directory() -> Path:
    """The directory records go to: ``--output-dir``, else the evidence directory."""

    return EVIDENCE_DIR if OPTIONS.output_dir is None else Path(OPTIONS.output_dir)


def _output_directory_label() -> str:
    """The output directory as recorded: relative to the repository when inside it.

    A committed record then carries no local checkout path; a directory the
    caller chose outside the repository is recorded as its absolute path.
    """

    directory = output_directory().resolve()
    try:
        return directory.relative_to(REPOSITORY).as_posix()
    except ValueError:
        return str(directory)


def _record_path(name: str) -> Path:
    return output_directory() / (OPTIONS.output or name)


def _write(name: str, record: dict[str, Any], *, resumed: bool = False) -> Path:
    """Write a record; the first write of an invocation never replaces silently."""

    output_directory().mkdir(parents=True, exist_ok=True)
    path = _record_path(name)
    if path not in _STARTED:
        if path.exists() and not (OPTIONS.overwrite or resumed):
            raise EvidenceRecordExists(
                f"{path} exists.  Pass --output NAME for a fresh record, --overwrite to "
                "replace it, or --resume to continue a gated series."
            )
        _STARTED.add(path)
    path.write_text(json.dumps(record, indent=2, default=float) + "\n")
    print(f"wrote {path}")
    return path


def code_identity() -> dict[str, Any]:
    """Git HEAD and a digest of uncommitted changes under ``src`` and ``scripts``."""

    try:
        head = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=REPOSITORY, capture_output=True, text=True, check=True
        ).stdout.strip()
        diff = subprocess.run(
            ["git", "diff", "HEAD", "--", "src", "scripts"], cwd=REPOSITORY, capture_output=True, check=True
        ).stdout
        untracked = subprocess.run(
            ["git", "ls-files", "--others", "--exclude-standard", "--", "src", "scripts"],
            cwd=REPOSITORY, capture_output=True, text=True, check=True,
        ).stdout.split()
    except (OSError, subprocess.CalledProcessError):
        return {"git_head": None, "source_changes_sha256": None}
    digest = hashlib.sha256(diff)
    for name in sorted(untracked):
        digest.update(name.encode("utf-8"))
        digest.update((REPOSITORY / name).read_bytes())
    return {"git_head": head, "source_changes_sha256": digest.hexdigest()}


def _shared_protocol(n_steps: int, burn_in: int, execution: Any, code: dict[str, Any]) -> dict[str, Any]:
    """The protocol fields every run of one record must share."""

    return {
        "series_protocol_version": SERIES_PROTOCOL_VERSION,
        "n_steps": int(n_steps),
        "burn_in_frames": int(burn_in),
        "execution": repr(execution),
        "code": code,
    }


def run_protocol(
    label: str, config: Any, seed: int, *, n_steps: int, burn_in: int, execution: Any, code: dict[str, Any]
) -> dict[str, Any]:
    """The identity a gated-series run must match to be reused on resume."""

    from dataclasses import replace

    from shwfs_ao.io.configs import RandomSeedConfig

    run_config = replace(
        config,
        random=RandomSeedConfig(root_seed=int(seed)),
        controller=replace(config.controller, n_steps=int(n_steps)),
    )
    payload = {
        "label": label,
        "root_seed": int(seed),
        "config_hash": run_config.config_hash,
        **_shared_protocol(n_steps, burn_in, execution, code),
    }
    encoded = json.dumps(payload, sort_keys=True, default=str).encode("utf-8")
    return {"protocol_hash": hashlib.sha256(encoded).hexdigest(), "protocol": payload}


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


def _gated_series(
    name: str,
    command: str,
    plan: list[tuple[str, Any, int]],
    *,
    n_steps: int,
    burn_in: int,
    execution: Any,
    enabled_by_user: str | None = None,
    runner: Any = None,
) -> None:
    """Run ``(label, config, root_seed)`` entries one at a time, saving after each.

    ``runner`` (default :func:`~shwfs_ao.experiments.detector_level.science_run`)
    is called as ``runner(config, root_seed=, n_steps=, burn_in_frames=,
    execution=)``.  An existing record is continued only with ``--resume``, and
    only runs whose protocol identity matches are reused (review R6).
    """

    from shwfs_ao.calibration.interaction import InteractionMatrixError
    from shwfs_ao.experiments.detector_level import science_run, summarize_runs

    from shwfs_ao.experiments.scao import ScaoConstructionError

    run = science_run if runner is None else runner
    path = _record_path(name)
    code = code_identity()
    record = _header(command)
    note = OPTIONS.enabled_by_user or enabled_by_user
    record["enabled_by_user"] = note
    record["n_steps"] = n_steps
    record["burn_in_frames"] = burn_in
    record["series_protocol_version"] = SERIES_PROTOCOL_VERSION
    record["code_identity"] = code
    record["runs"] = []
    expected = {
        (label, int(seed)): run_protocol(
            label, config, seed, n_steps=n_steps, burn_in=burn_in, execution=execution, code=code
        )
        for label, config, seed in plan
    }
    resumed = False
    if path.exists():
        if not OPTIONS.resume:
            raise EvidenceRecordExists(
                f"{path} exists.  Pass --resume to continue it (runs are reused only when "
                "their protocol identity matches) or --output NAME for a fresh record."
            )
        previous = json.loads(path.read_text())
        # Every retained run, in this plan or not (another comparison arm),
        # must share the series protocol: version, frames, burn-in, execution
        # and code (re-review S2).  Runs of this plan must also match their
        # own configuration.
        shared = _shared_protocol(n_steps, burn_in, execution, code)
        mismatched = []
        for entry in previous.get("runs", []):
            key = (entry.get("label"), entry.get("root_seed"))
            if "protocol_hash" not in entry or "protocol" not in entry:
                raise EvidenceRecordExists(
                    f"{path} predates run protocol identities and cannot be resumed; "
                    "pass --output NAME for a fresh record."
                )
            saved = {name: entry["protocol"].get(name) for name in shared}
            if saved != shared:
                mismatched.append(key)
            elif key in expected and entry["protocol_hash"] != expected[key]["protocol_hash"]:
                mismatched.append(key)
        if mismatched:
            raise EvidenceRecordExists(
                f"{path}: saved runs {mismatched} were made under another protocol "
                "(configuration, frames, burn-in, execution or code).  Pass --output NAME "
                "for a fresh record."
            )
        record["runs"] = list(previous.get("runs", []))
        record["resumed_from_started_unix_s"] = previous.get("started_unix_s")
        # The series keeps the go-ahead it started under; a resume that runs
        # more records its own note beside it instead of rewriting that one.
        record["enabled_by_user"] = previous.get("enabled_by_user")
        resumed_notes = list(previous.get("resumed_enabled_by_user", []))
        resumed = True
    done = {(entry["label"], entry["root_seed"]) for entry in record["runs"]}
    pending = [(label, seed) for label, _, seed in plan if (label, seed) not in done]
    if pending and note is None:
        raise EnablementMissing(
            f"{command}: a gated run needs --enabled-by-user (the date and wording of the "
            "user's go-ahead for this run); nothing ran."
        )
    if resumed and pending:
        record["resumed_enabled_by_user"] = [*resumed_notes, note]
    ran = 0
    for label, config, seed in plan:
        if (label, seed) in done:
            continue
        ran += 1
        try:
            result = run(config, root_seed=seed, n_steps=n_steps, burn_in_frames=burn_in, execution=execution)
        except (ScaoConstructionError, InteractionMatrixError) as exc:
            # A configuration the system refuses to build (for example a
            # calibration whose rows the validity gates reject) is a result.
            result = {"status": "refused", "reason": str(exc)[:500], "root_seed": seed}
        result["label"] = label
        result.update(expected[(label, int(seed))])
        record["runs"].append(result)
        groups: dict[str, list[dict[str, Any]]] = {}
        for entry in record["runs"]:
            if entry.get("status") != "refused" and "post_update_rms_m" in entry:
                groups.setdefault(entry["label"], []).append(entry)
        record["summary"] = {key: summarize_runs(value) for key, value in groups.items()}
        record["refused"] = [
            {"label": entry["label"], "root_seed": entry["root_seed"], "reason": entry["reason"]}
            for entry in record["runs"]
            if entry.get("status") == "refused"
        ]
        record["wall_s"] = time.time() - record["started_unix_s"]
        _write(name, record, resumed=resumed or path in _STARTED)
        if result.get("status") == "refused":
            print(label, seed, "REFUSED", result["reason"][:120], flush=True)
            continue
        if "post_update_rms_m" in result:
            print(
                label, seed,
                f"rms={1e9 * result['post_update_rms_m']:.1f}nm valid={result['valid_measurement_fraction']:.3f}",
                f"strehl={result['science'][0]['peak_strehl']:.3f} frame={result['per_frame_s']:.3f}s",
                flush=True,
            )
        else:
            print(
                label, seed,
                f"noise_var={1e18 * result['noise_variance_m2']:.1f}"
                f"+-{1e18 * (result['noise_variance_standard_error_m2'] or 0.0):.1f}nm2",
                f"ms_diff={1e18 * result['mean_square_difference_m2']:.0f}nm2",
                f"Ne={result['detected_e_full_subap']:.0f} wall={result['wall_s']:.1f}s",
                flush=True,
            )
    if resumed and ran == 0:
        # A resume with nothing left to run must say so: nothing ran, and
        # the record on disk is unchanged.
        print(
            f"{path}: all {len(plan)} planned runs are already recorded under this "
            "protocol; nothing ran and the record is unchanged.",
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

    if OPTIONS.enabled_by_user is None:
        raise EnablementMissing(
            "e2-12m: a gated run needs --enabled-by-user (the date and wording of the "
            "user's go-ahead for this run); nothing ran."
        )
    record = _header("e2-12m")
    record["enabled_by_user"] = OPTIONS.enabled_by_user
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
    from shwfs_ao.experiments.detector_level import with_matched_photometry, with_physics

    base = _medium(version)
    physics = base.detector_physics
    mono = with_physics(
        base, bandpass=BandpassConfig(kind="monochromatic", band_min_m=5.5e-7, band_max_m=8.5e-7)
    )
    # The 550-850 nm band changes the photometry along with the optics: +5.7 %
    # detected source and sky electrons against the R3 band (review R5).  The
    # @1/@2 records keep their original label for this arm.
    mono_label = "monochromatic 700 nm" if version < 3 else "monochromatic 700 nm (band and photometry change together)"
    variants = {
        "baseline (MFT k=4, diffusion 0.2, R3 3 nodes, estimated)": base,
        "point sampling (k=1, no diffusion)": with_physics(
            base, sampling=replace(physics.sampling, oversampling=1, diffusion_sigma_px=0.0)
        ),
        mono_label: mono,
        "oracle processing": with_physics(base, processing=replace(physics.processing, mode="oracle")),
    }
    if version >= 3:
        # The controlled comparison: 700 nm optics with the baseline's electrons.
        variants["monochromatic 700 nm, photometry matched to the baseline"] = with_matched_photometry(mono, base)
    plan = [(label, config, seed) for label, config in variants.items() for seed in (41, 42, 43)]
    name = "det09_e6_effect_sizes_12m.json" if version == 1 else f"det09_e6_effect_sizes_12m_v{version}.json"
    _gated_series(
        name, f"e6 (profile @{version})", plan, n_steps=400, burn_in=100, execution=_summary_execution(),
        enabled_by_user=getattr(arguments, "enabled_by_user", None),
    )


# Closed-loop recovery arms (controller.recovery), fixed by the predeclared
# protocol from development runs on root seeds 11 and 12, never on 21-25.
RECOVERY_ARMS: dict[str, dict[str, Any] | None] = {
    "off": None,
    "reset": {"rejected_frames_before_decay": 2, "decay_per_rejected_frame": 1.0},
    "guarded_fallback": {"fallback_min_valid_fraction": 0.1, "fallback_min_actuator_coverage": 0.5},
    "gain_schedule": {"fallback_min_valid_fraction": 0.1, "gain_full_valid_fraction": 0.9},
}


def e3_recovery(arguments: argparse.Namespace) -> None:
    from dataclasses import replace

    from shwfs_ao.experiments.detector_level import with_magnitude
    from shwfs_ao.io.configs import RecoveryPolicyConfig

    arm = arguments.arm
    fields = RECOVERY_ARMS[arm]
    base = _medium(2)
    if fields is not None:
        policy = RecoveryPolicyConfig(
            **{
                "rejected_frames_before_decay": None,
                "decay_per_rejected_frame": None,
                "fallback_min_valid_fraction": None,
                "fallback_min_actuator_coverage": None,
                "gain_full_valid_fraction": None,
                **fields,
            }
        )
        base = replace(base, controller=replace(base.controller, recovery=policy))
    plan = [
        (f"{arm} m{magnitude:g}", with_magnitude(base, magnitude), seed)
        for magnitude in (10.0, 11.0, 12.0)
        for seed in (21, 22, 23, 24, 25)
    ]
    _gated_series(
        "det_recovery_e3_12m_v2.json",
        f"e3-recovery --arm {arm} (profile @2)",
        plan,
        n_steps=400,
        burn_in=100,
        execution=_summary_execution(),
    )


# Excursion-trigger arms: each names its controller.recovery policy and the
# reconstructor / controller fields it changes from @2.  Fixed by the
# predeclared protocol from development runs on root seeds 11 and 12 only.
_RESET = {"rejected_frames_before_decay": 2, "decay_per_rejected_frame": 1.0}
EXCURSION_ARMS: dict[str, dict[str, Any]] = {
    "reset": {"recovery": _RESET, "reconstructor": {}, "controller": {}},
    "damped_reset": {"recovery": _RESET, "reconstructor": {"alpha": 0.1}, "controller": {}},
    "damped": {"recovery": None, "reconstructor": {"alpha": 0.1}, "controller": {}},
    "strict_reset": {"recovery": _RESET, "reconstructor": {"min_valid_fraction": 0.7}, "controller": {}},
    "strict": {"recovery": None, "reconstructor": {"min_valid_fraction": 0.7}, "controller": {}},
    "leaky_reset": {"recovery": _RESET, "reconstructor": {}, "controller": {"leak": 0.01}},
}


def e3_excursion(arguments: argparse.Namespace) -> None:
    from dataclasses import replace

    from shwfs_ao.experiments.detector_level import with_magnitude
    from shwfs_ao.io.configs import RecoveryPolicyConfig

    arm = arguments.arm
    fields = EXCURSION_ARMS[arm]
    base = _medium(2)
    controller = replace(base.controller, **fields["controller"])
    if fields["recovery"] is not None:
        policy = RecoveryPolicyConfig(
            **{
                "rejected_frames_before_decay": None,
                "decay_per_rejected_frame": None,
                "fallback_min_valid_fraction": None,
                "fallback_min_actuator_coverage": None,
                "gain_full_valid_fraction": None,
                **fields["recovery"],
            }
        )
        controller = replace(controller, recovery=policy)
    base = replace(
        base,
        reconstructor=replace(base.reconstructor, **fields["reconstructor"]),
        controller=controller,
    )
    plan = [
        (f"{arm} m{magnitude:g}", with_magnitude(base, magnitude), seed)
        for magnitude in (10.0, 11.0, 12.0)
        for seed in (21, 22, 23, 24, 25)
    ]
    _gated_series(
        "det_excursion_e3_12m_v2.json",
        f"e3-excursion --arm {arm} (profile @2)",
        plan,
        n_steps=400,
        burn_in=100,
        execution=_summary_execution(),
    )


def det08(arguments: argparse.Namespace) -> None:
    from shwfs_ao.experiments.detector_level import with_physics

    base = _medium()
    plan = [
        (f"n_sub={count}", with_physics(base, exposure_subsamples=count), seed)
        for count in (1, 2, 4)
        for seed in (51, 52, 53, 54, 55)
    ]
    _gated_series("det08_exposure_subsamples_12m.json", "det08", plan, n_steps=400, burn_in=100, execution=_summary_execution())


# Isolated temporal detector-noise variance (review 2026-10-16, DET-09).  The
# protocol is predeclared in the status file ("Isolated detector-noise
# variance").
# The 2 m screen supports about 204 frames of travel, so the 2 m study runs
# 200 frames over more seeds.  The 2 m profile corrects only to m_AB = 8 (its
# inherited peak-SNR gate), so the magnitudes are 5-8 (amendments recorded
# in the status file).
NOISE_ISOLATION_2M = {
    "profile": ("det_emccd_2m_synthetic", 1), "magnitudes": (5.0, 6.0, 7.0, 8.0),
    "seeds": (61, 62, 63, 64, 65, 66, 67, 68), "n_steps": 200, "burn_in": 50,
}
NOISE_ISOLATION_12M = {
    "profile": ("det_emccd_12m_medium_derived", 3), "magnitudes": (8.0, 9.0, 10.0, 11.0),
    "seeds": (71, 72, 73, 74, 75), "n_steps": 400, "burn_in": 100,
}


def _noise_isolation(settings: dict[str, Any], name: str, command: str, **keywords: Any) -> None:
    from shwfs_ao.experiments.detector_level import paired_noise_run, with_magnitude
    from shwfs_ao.io.configs import load_system_profile

    base = load_system_profile(*settings["profile"])
    plan = [
        (f"m{magnitude:g}", with_magnitude(base, magnitude), seed)
        for magnitude in settings["magnitudes"]
        for seed in settings["seeds"]
    ]
    _gated_series(
        name, command, plan, n_steps=settings["n_steps"], burn_in=settings["burn_in"],
        execution=_summary_execution(), runner=paired_noise_run, **keywords,
    )


def noise_isolation_2m(arguments: argparse.Namespace) -> None:
    _noise_isolation(
        NOISE_ISOLATION_2M, "det09_noise_isolation_2m.json", "noise-isolation-2m",
        enabled_by_user="not gated: 2 m tier (prompt section 2.5)",
    )


def noise_isolation_12m(arguments: argparse.Namespace) -> None:
    _noise_isolation(
        NOISE_ISOLATION_12M, "det09_noise_isolation_12m_v3.json", "noise-isolation-12m (profile @3)",
        enabled_by_user=arguments.enabled_by_user,
    )


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


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument(
        "--output-dir",
        type=Path,
        help="write records into this directory (default: docs/refactor/detector_level_evidence)",
    )
    parser.add_argument("--output", help="write a fresh record under this file name in the output directory")
    parser.add_argument("--overwrite", action="store_true", help="replace an existing one-shot record")
    parser.add_argument("--resume", action="store_true", help="continue a gated series after validating each saved run")
    parser.add_argument("--enabled-by-user", dest="global_enabled_by_user", help="record this enablement note in a gated record (date and wording of the user's go-ahead)")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("gain-scan")
    commands = {
        "gain-scan": gain_scan, "e1": e1, "e2": e2, "ensemble": ensemble, "cost": cost,
        "e2-12m": e2_12m, "e3": e3, "e4": e4, "e6": e6, "det08": det08, "e5": e5,
        "e3-v2": lambda arguments: e3(arguments, version=2),
        "e4-v2": lambda arguments: e4(arguments, version=2),
        "e6-v2": lambda arguments: e6(arguments, version=2),
        "e3-v3": lambda arguments: e3(arguments, version=3),
        "e4-v3": lambda arguments: e4(arguments, version=3),
        "noise-isolation-2m": noise_isolation_2m,
    }
    for name in commands:
        if name != "gain-scan":
            sub.add_parser(name)
    commands["e3-recovery"] = e3_recovery
    sub.add_parser("e3-recovery").add_argument("--arm", required=True, choices=sorted(RECOVERY_ARMS))
    commands["e3-excursion"] = e3_excursion
    sub.add_parser("e3-excursion").add_argument("--arm", required=True, choices=sorted(EXCURSION_ARMS))
    # Gated runs added by the review: record who enabled them, and when.
    commands["noise-isolation-12m"] = noise_isolation_12m
    sub.add_parser("noise-isolation-12m").add_argument("--enabled-by-user", required=True)
    commands["e6-v3"] = lambda arguments: e6(arguments, version=3)
    sub.add_parser("e6-v3").add_argument("--enabled-by-user", required=True)
    arguments = parser.parse_args(argv)
    OPTIONS.output_dir = arguments.output_dir
    OPTIONS.output = arguments.output
    OPTIONS.overwrite = arguments.overwrite
    OPTIONS.resume = arguments.resume
    OPTIONS.enabled_by_user = arguments.global_enabled_by_user
    commands[arguments.command](arguments)
    return 0


if __name__ == "__main__":
    sys.exit(main())
