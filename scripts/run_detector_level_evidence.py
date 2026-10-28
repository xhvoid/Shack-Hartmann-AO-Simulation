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
``noise-isolation-2m-traced`` (ungated), ``noise-isolation-12m-traced`` and
``noise-isolation-12m-masklocked`` (both gated) are the S4 traced family
(ticket T1, 2026-10-20): the same paired runs observed per frame, each with
one allow-pickle-free NumPy sidecar beside the record, a diagnostic protocol
binding the tracing semantics beside the unchanged physical protocol, and
atomic, never-clobbering publication (see the traced section below).  The
mask-locked command is arm B of the contract: the twin runs first and the
noisy arm replays its effective rows through a separately identified wrapper.
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
recorded says so and leaves the record unchanged; it stops instead when the
imported package cannot be digested (below), since it cannot verify them.  On
resume every saved run must carry the protocol identity this invocation would
give it (configuration hash with seed and frame count, burn-in, execution
options, the code identity and the producing environment: Python, NumPy,
SciPy and machine); a mismatch stops the command, and a record without
identities cannot be resumed.  The code identity is the code the process
runs: a digest of the ``shwfs_ao`` package it imports (bytecode and hidden
files left out) and of this script, with the Git HEAD and a digest of the
uncommitted changes of the package's source directory when the repository
that holds the package tracks it; otherwise those two are null and the code
identity is unknown.  It is unknown too, with a null package digest, when the
package's files cannot bind the code imported from it (a zip import, a
symlinked directory, unbound bytecode; OBS-15, 2026-10-20).  Every retained
run, including the runs of other arms, must share the record's series
protocol (version, frames, burn-in, execution options, code and environment),
so arms of ``e3-recovery`` and ``e3-excursion`` append to one record with
``--resume`` only under the same protocol.  Each run's protocol names the
environment that produced it (series protocol version 3, 2026-10-18, GPT
pre-refactor audit F-03); version-2 records do not, so they cannot be
continued, and nothing is attributed to them after the fact.  Series
protocol version 4 (2026-10-20, OBS-07) takes the code identity from the
imported package: a version-3 code identity named this script's repository,
which need not hold the package a run imported, so version-3 records cannot
be continued either and are never relabelled.  A
resume that would add runs also stops when the code identity is unknown.  A
saved record must also agree with itself (GPT independent review AR-016,
2026-10-20): every run's stored protocol hash is recomputed from its stored
protocol; the label, seed, configuration hash, frame count and burn-in a run
repeats must equal its protocol's; each label and seed is recorded once; and
the header's series fields and environment must be its runs'.  An
inconsistent or unreadable record stops the command before anything runs and
is left byte for byte as it was.
"""

from __future__ import annotations

import _imp
import argparse
import hashlib
import importlib.util
import json
import math
import os
from pathlib import Path
import platform
import subprocess
import sys
import time
from typing import Any
import zipfile

import numpy as np


REPOSITORY = Path(__file__).resolve().parents[1]
EVIDENCE_DIR = REPOSITORY / "docs/refactor/detector_level_evidence"
# Protocol identity version of gated-series runs (review R6).  Version 3
# (2026-10-18) adds the producing environment to the shared protocol; version
# 4 (2026-10-20, OBS-07) takes the code identity from the imported package
# instead of this script's repository.
SERIES_PROTOCOL_VERSION = 4
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
    return {
        "command": command,
        "argv": sys.argv,
        # The producing environment's four fields, as every run's protocol has them.
        **producer_environment(),
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


def _unchecked_bytecode(source: Path) -> bool:
    """Whether Python would run cached bytecode of ``source`` without checking it against the source.

    The cache is the one this interpreter reads: in ``__pycache__``, or under
    ``sys.pycache_prefix`` (review RV-07).  An unchecked hash-based cache is
    never checked (PEP 552), and under ``--check-hash-based-pycs never`` no
    hash-based cache is.  A missing or unreadable cache is not run: Python
    compiles the source instead (review RV-08).
    """

    try:
        with Path(importlib.util.cache_from_source(str(source))).open("rb") as handle:
            header = handle.read(8)
    except (OSError, NotImplementedError):
        return False
    flags = int.from_bytes(header[4:8], "little") if len(header) == 8 else 0
    # The switch importlib itself reads before it checks a hash-based cache.
    never = getattr(_imp, "check_hash_based_pycs", "default") == "never"
    return bool(flags & 0b01) and (not flags & 0b10 or never)


def _package_sha256(package: Path) -> str | None:
    """SHA-256 over the files of a package: each relative name and content digest.

    Bytecode and hidden files or folders are left out, as in the S3 driver:
    Finder metadata (``.DS_Store``, ``._*``) and the like can appear without
    any code change and must not change the identity.  None when the files
    cannot bind the code Python imports from the package (OBS-15, review
    RV-01, RV-05): it is not a directory with an ``__init__.py`` (a zip
    import, a missing directory), or it holds a symlinked directory (not
    followed), sourceless bytecode outside ``__pycache__`` (imported, never
    digested) or a source whose cache Python would run unchecked.
    """

    if not (package / "__init__.py").is_file():
        return None
    digest = hashlib.sha256()
    for path in sorted(package.rglob("*")):
        relative = path.relative_to(package)
        if any(part.startswith(".") for part in relative.parts) or "__pycache__" in relative.parts:
            continue
        if (path.is_dir() and path.is_symlink()) or (path.is_file() and path.suffix == ".pyc"):
            return None
        if path.is_file():
            if path.suffix == ".py" and _unchecked_bytecode(path):
                return None
            digest.update(relative.as_posix().encode("utf-8") + b"\0")
            digest.update(hashlib.sha256(path.read_bytes()).digest())
    return digest.hexdigest()


def code_identity(package: Path | None = None) -> dict[str, Any]:
    """The code a run executes: the imported package, this script, and Git where it tracks the package.

    ``package`` defaults to the directory of the ``shwfs_ao`` this process
    imports, which need not lie in this script's repository: without
    PYTHONPATH a shared environment's editable install can supply another
    checkout's package (OBS-07, review CR-02).  ``package_sha256`` digests
    that package and ``script_sha256`` this script, so two processes that
    import different package files never share a known identity (bytecode
    caches are not digested: LIM-11 names the stale-cache case).  Git HEAD
    and the digest of the uncommitted changes under the package's source
    directory are recorded only when the repository that holds the package
    tracks it, its paths read literally (OBS-16); for a copy in an ignored or
    foreign directory, or without Git, they are null, and the code identity
    counts as unknown.  It is unknown too, with a null package digest, when
    the package's files cannot bind the code imported from it (a zip import,
    a symlinked directory, unbound bytecode; OBS-15).  The S3 driver records
    the same code identity.
    """

    if package is None:
        import shwfs_ao

        package = Path(shwfs_ao.__file__).parent
    package = package.resolve()
    source = package.parent
    package_sha256 = _package_sha256(package)
    # Names only: a record must not carry the local checkout path.
    identity: dict[str, Any] = {
        "package_directory": source.name,
        "package_sha256": package_sha256,
        "script_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "git_head": None,
        "source_changes_sha256": None,
    }
    if package_sha256 is None:
        return identity

    def git(*arguments: str, cwd: Path) -> subprocess.CompletedProcess:
        # Literal paths: a copy at ``copy[1]/`` must not match a tracked ``copy1/``.
        return subprocess.run(["git", "--literal-pathspecs", *arguments], cwd=cwd, capture_output=True, check=True)

    try:
        top = Path(git("rev-parse", "--show-toplevel", cwd=package).stdout.decode().strip()).resolve()
        git("ls-files", "--error-unmatch", "--", (package / "__init__.py").relative_to(top).as_posix(), cwd=top)
        head = git("rev-parse", "HEAD", cwd=top).stdout.decode().strip()
        diff = git("diff", "HEAD", "--", source.relative_to(top).as_posix(), cwd=top).stdout
    except (OSError, ValueError, subprocess.CalledProcessError):
        return identity
    identity["git_head"] = head
    identity["source_changes_sha256"] = hashlib.sha256(diff).hexdigest()
    return identity


def producer_environment() -> dict[str, str]:
    """The numerical environment a run is produced in (the header's fields)."""

    import scipy

    return {
        "python": sys.version,
        "numpy": np.__version__,
        "scipy": scipy.__version__,
        "machine": platform.machine(),
    }


def _shared_protocol(
    n_steps: int, burn_in: int, execution: Any, code: dict[str, Any], environment: dict[str, str]
) -> dict[str, Any]:
    """The protocol fields every run of one record must share."""

    return {
        "series_protocol_version": SERIES_PROTOCOL_VERSION,
        "n_steps": int(n_steps),
        "burn_in_frames": int(burn_in),
        "execution": repr(execution),
        "code": code,
        "environment": environment,
    }


def run_protocol(
    label: str,
    config: Any,
    seed: int,
    *,
    n_steps: int,
    burn_in: int,
    execution: Any,
    code: dict[str, Any],
    environment: dict[str, str] | None = None,
) -> dict[str, Any]:
    """The identity a gated-series run must match to be reused on resume.

    ``environment`` defaults to :func:`producer_environment`.
    """

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
        **_shared_protocol(
            n_steps, burn_in, execution, code, producer_environment() if environment is None else environment
        ),
    }
    return {"protocol_hash": protocol_digest(payload), "protocol": payload}


def protocol_digest(payload: Any) -> str:
    """SHA-256 of the key-sorted JSON of a run's protocol payload."""

    return hashlib.sha256(_canonical(payload).encode("utf-8")).hexdigest()


def _canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, default=str)


# Fields a saved run repeats from its protocol, and header fields that repeat
# the series protocol of the record's runs (GPT independent review AR-016).
_REPEATED_RUN_FIELDS = ("label", "root_seed", "config_hash", "n_steps", "burn_in_frames")
_REPEATED_HEADER_FIELDS = {
    "series_protocol_version": "series_protocol_version",
    "n_steps": "n_steps",
    "burn_in_frames": "burn_in_frames",
    "code_identity": "code",
}


def _inconsistencies(previous: dict[str, Any]) -> list[str]:
    """How a saved series record contradicts itself (empty when it does not).

    Every run's stored protocol hash must be the digest of its stored
    protocol, and the label, seed, configuration hash, frame count and burn-in
    it repeats must equal its protocol's; a (label, seed) is recorded once.
    The header's series fields and environment must be its runs', and the
    enablement notes a resume carries over must be text.
    """

    problems: list[str] = []
    seen: set[str] = set()
    for index, entry in enumerate(previous["runs"]):
        protocol = entry["protocol"]
        if not isinstance(protocol, dict) or protocol_digest(protocol) != entry["protocol_hash"]:
            problems.append(f"run {index}: the stored protocol hash is not the digest of its protocol")
            continue
        for name in _REPEATED_RUN_FIELDS:
            # The label and seed identify the run, so they must be present.
            if (name in ("label", "root_seed") or name in entry) and _canonical(entry.get(name)) != _canonical(protocol.get(name)):
                problems.append(f"run {index}: {name} {entry.get(name)!r} is not its protocol's {protocol.get(name)!r}")
        key = _canonical([entry.get("label"), entry.get("root_seed")])
        if key in seen:
            problems.append(f"run {index}: label and seed {key} are recorded twice")
        seen.add(key)
    if problems:
        return problems
    runs = previous["runs"]
    for header_name, name in _REPEATED_HEADER_FIELDS.items():
        if header_name in previous and any(_canonical(entry["protocol"].get(name)) != _canonical(previous[header_name]) for entry in runs):
            problems.append(f"the header's {header_name} is not its runs'")
    environments = [entry["protocol"]["environment"] for entry in runs if isinstance(entry["protocol"].get("environment"), dict)]
    for name in ("python", "numpy", "scipy", "machine"):
        if name in previous and any(_canonical(environment.get(name)) != _canonical(previous[name]) for environment in environments):
            problems.append(f"the header's {name} is not its runs' producing environment")
    if not isinstance(previous.get("enabled_by_user"), (str, type(None))):
        problems.append("enabled_by_user is not a note")
    resumed_notes = previous.get("resumed_enabled_by_user", [])
    if not isinstance(resumed_notes, list) or not all(isinstance(note, str) for note in resumed_notes):
        problems.append("resumed_enabled_by_user is not a list of notes")
    return problems


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
    run_context: bool = False,
    validate_retained: Any = None,
    header_extra: dict[str, Any] | None = None,
) -> None:
    """Run ``(label, config, root_seed)`` entries one at a time, saving after each.

    ``runner`` (default :func:`~shwfs_ao.experiments.detector_level.science_run`)
    is called as ``runner(config, root_seed=, n_steps=, burn_in_frames=,
    execution=)``.  An existing record is continued only with ``--resume``, and
    only runs whose protocol identity matches are reused (review R6).

    The three optional hooks serve the traced family (T1) and default to the
    legacy behaviour: with ``run_context`` the runner also receives
    ``context=`` (the run's label, its protocol identity, the record path, the
    code identity and the environment); ``validate_retained(path, runs)`` is
    called with the retained runs (an empty list for a fresh record) after the
    legacy checks and before anything runs, and must raise
    :class:`EvidenceRecordExists` to refuse; ``header_extra`` adds fields to
    the record header.
    """

    from shwfs_ao.calibration.interaction import InteractionMatrixError
    from shwfs_ao.experiments.detector_level import science_run, summarize_runs

    from shwfs_ao.experiments.scao import ScaoConstructionError

    run = science_run if runner is None else runner
    path = _record_path(name)
    code = code_identity()
    environment = producer_environment()
    record = _header(command)
    note = OPTIONS.enabled_by_user or enabled_by_user
    record["enabled_by_user"] = note
    record["n_steps"] = n_steps
    record["burn_in_frames"] = burn_in
    record["series_protocol_version"] = SERIES_PROTOCOL_VERSION
    record["code_identity"] = code
    if header_extra:
        record.update(header_extra)
    record["runs"] = []
    expected = {
        (label, int(seed)): run_protocol(
            label, config, seed, n_steps=n_steps, burn_in=burn_in, execution=execution, code=code,
            environment=environment,
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
        try:
            previous = json.loads(path.read_text())
        except (OSError, UnicodeDecodeError, ValueError) as exc:
            raise EvidenceRecordExists(
                f"{path} is not readable JSON ({exc}); nothing ran and it is unchanged.  Pass "
                "--output NAME for a fresh record."
            ) from None
        if not isinstance(previous, dict) or not isinstance(previous.get("runs"), list):
            raise EvidenceRecordExists(
                f"{path} has no list of runs, so it is not a gated-series record; nothing ran and it "
                "is unchanged.  Pass --output NAME for a fresh record."
            )
        for entry in previous["runs"]:
            if not isinstance(entry, dict) or "protocol_hash" not in entry or "protocol" not in entry:
                raise EvidenceRecordExists(
                    f"{path} predates run protocol identities and cannot be resumed; "
                    "pass --output NAME for a fresh record."
                )
        # A saved record must agree with itself before its runs are compared
        # with this invocation's (GPT independent review AR-016).
        problems = _inconsistencies(previous)
        if problems:
            raise EvidenceRecordExists(
                f"{path} is inconsistent in itself ({'; '.join(problems[:3])}"
                f"{'; ...' if len(problems) > 3 else ''}); nothing ran and it is unchanged.  "
                "Pass --output NAME for a fresh record."
            )
        # Every retained run, in this plan or not (another comparison arm),
        # must share the series protocol: version, frames, burn-in, execution,
        # code (re-review S2) and producing environment (GPT audit F-03).
        # Runs of this plan must also match their own configuration.
        shared = _shared_protocol(n_steps, burn_in, execution, code, environment)
        mismatched = []
        unattributed = []
        superseded = []
        for entry in previous["runs"]:
            key = (entry.get("label"), entry.get("root_seed"))
            if "environment" not in entry["protocol"]:
                unattributed.append(key)
                continue
            version = entry["protocol"].get("series_protocol_version")
            if _canonical(version) != _canonical(SERIES_PROTOCOL_VERSION):
                superseded.append((key, version))
                continue
            saved = {name: entry["protocol"].get(name) for name in shared}
            if _canonical(saved) != _canonical(shared):
                mismatched.append(key)
            elif key in expected and entry["protocol_hash"] != expected[key]["protocol_hash"]:
                mismatched.append(key)
        if unattributed:
            raise EvidenceRecordExists(
                f"{path}: saved runs {unattributed} do not name the environment that "
                "produced them (series protocol version < 3), so a resume cannot show "
                "they share this one.  Pass --output NAME for a fresh record."
            )
        if superseded:
            # Series protocol 4 (OBS-07): a version-3 run's code identity names
            # the runner's repository, not the package the run imported, so
            # it cannot be compared with this one.  It is not relabelled.
            versions = sorted({_canonical(version) for _, version in superseded})
            reason = (
                "a version-3 code identity names the runner's repository, not the package the run "
                "imported, so a resume cannot show the saved runs share this invocation's code"
                if _canonical(3) in versions
                else "a run of another series protocol cannot be compared with this runner's"
            )
            raise EvidenceRecordExists(
                f"{path}: saved runs {[key for key, _ in superseded]} were made under series "
                f"protocol version {', '.join(versions)}, and this runner continues version "
                f"{SERIES_PROTOCOL_VERSION} only: {reason}.  The record is neither continued nor "
                "relabelled; pass --output NAME for a fresh record."
            )
        if mismatched:
            raise EvidenceRecordExists(
                f"{path}: saved runs {mismatched} were made under another protocol "
                "(configuration, frames, burn-in, execution, code or producing "
                "environment).  Pass --output NAME for a fresh record."
            )
        record["runs"] = list(previous.get("runs", []))
        record["resumed_from_started_unix_s"] = previous.get("started_unix_s")
        # The series keeps the go-ahead it started under; a resume that runs
        # more records its own note beside it instead of rewriting that one.
        record["enabled_by_user"] = previous.get("enabled_by_user")
        resumed_notes = list(previous.get("resumed_enabled_by_user", []))
        resumed = True
    if validate_retained is not None:
        # The family's own checks (sidecars, diagnostic protocol, leftovers):
        # read-only, before any decision to run or to leave the record alone.
        validate_retained(path, list(record["runs"]))
    done = {(entry["label"], entry["root_seed"]) for entry in record["runs"]}
    pending = [(label, seed) for label, _, seed in plan if (label, seed) not in done]
    if pending and note is None:
        raise EnablementMissing(
            f"{command}: a gated run needs --enabled-by-user (the date and wording of the "
            "user's go-ahead for this run); nothing ran."
        )
    if resumed and pending and code.get("git_head") is None:
        raise EvidenceRecordExists(
            f"{path}: the code identity of this invocation is unknown (no Git repository "
            "tracks the imported package, or its files cannot bind the code it runs), so runs "
            "added now could not be shown to use the code of the saved runs.  Pass --output "
            "NAME for a fresh record."
        )
    if resumed and not pending and "package_sha256" in code and code["package_sha256"] is None:
        # Nothing to add, and nothing to verify with (review RV-06): every
        # package without a digest has this identity, whatever its code.
        raise EvidenceRecordExists(
            f"{path}: all {len(plan)} planned runs are recorded, but the imported package's files "
            "cannot be digested (a zip import, a symlinked directory or unbound bytecode), so this "
            "invocation cannot verify that its code made them; nothing ran and the record is "
            "unchanged."
        )
    if resumed and pending:
        record["resumed_enabled_by_user"] = [*resumed_notes, note]
    ran = 0
    for label, config, seed in plan:
        if (label, seed) in done:
            continue
        ran += 1
        try:
            if run_context:
                result = run(
                    config, root_seed=seed, n_steps=n_steps, burn_in_frames=burn_in, execution=execution,
                    context={
                        "label": label, "protocol": expected[(label, int(seed))], "record_path": path,
                        "code": code, "environment": environment,
                    },
                )
            else:
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


# -- S4 traced noise isolation (ticket T1, 2026-10-20) --------------------------
#
# A separate record family beside the recorded ``noise-isolation-*`` studies:
# the same paired runs, observed per frame (``paired_noise_run_traced``), with
# one allow-pickle-free NumPy sidecar per run next to the JSON record.  The
# physical run identity is the series protocol 4 payload, unchanged; the
# tracing semantics (trace fields, frame domain, arm order, mask source, map
# retention, dtypes) are bound by a separate diagnostic protocol with its own
# hash, so a traced record is never accepted under other tracing semantics
# merely because its physical hash matches.  A sidecar's digest is output
# integrity, recorded in the run row and never part of any protocol payload
# (no circular hash).  Publication is atomic and never clobbers: the complete
# bytes go to a temporary file, are hard-linked into place (refused if the
# destination exists), re-read and digested; only then is the run row with the
# reference appended to the record.  An interrupted invocation therefore leaves
# at most a sidecar without a row (an orphan) or a temporary file; both are
# refused as ambiguous leftovers on the next invocation and are never deleted,
# repaired or overwritten by this script.
TRACE_FAMILY = "noise_isolation_traced"
TRACE_SIDECAR_SCHEMA = "shwfs_ao.noise_isolation_trace_sidecar.v1"
DIAGNOSTIC_PROTOCOL_VERSION = 1
_SIDECAR_TEMP_MARK = ".tmp-"
# Residual maps are retained for one predeclared seed per magnitude (the S4
# contract's default); the 2 m m8 and the 12 m m11 selections take the seed
# that showed the recorded excursion (seed 68 and seed 72), the others the
# first seed of the study.  Declared here, before any traced run.
NOISE_ISOLATION_2M_TRACED = {
    **NOISE_ISOLATION_2M,
    "record": "det09_noise_isolation_2m_traced.json",
    "map_seeds": {"m5": 61, "m6": 61, "m7": 61, "m8": 68},
}
NOISE_ISOLATION_12M_TRACED = {
    **NOISE_ISOLATION_12M,
    "record": "det09_noise_isolation_12m_traced.json",
    "map_seeds": {"m8": 71, "m9": 71, "m10": 71, "m11": 72},
}
# Arm B of the S4 contract: m_AB 11, root seeds 71-80, the noisy arm replaying
# the twin's effective rows.  Conditional on A1's analysis; gated.
NOISE_ISOLATION_12M_MASKLOCKED = {
    "profile": ("det_emccd_12m_medium_derived", 3), "magnitudes": (11.0,),
    "seeds": (71, 72, 73, 74, 75, 76, 77, 78, 79, 80), "n_steps": 400, "burn_in": 100,
    "record": "det09_noise_isolation_12m_masklocked.json",
    "map_seeds": {"m11": 72},
}
# Units and axes of every sidecar array (the sidecar's metadata repeats them).
_SIDECAR_SHARED_ARRAYS = {
    "frame_index": ("frame", "frame index 0..n_steps-1", ("frame",)),
    "analysed_frame_index": ("frame", "frames after burn-in, the domain of the three series below", ("analysed_frame",)),
    "delta_v_m2": ("m2", "DeltaV_t: piston-removed pupil mean square of the residual-map difference (noisy minus twin, float32-recorded maps)", ("analysed_frame",)),
    "mean_square_difference_m2": ("m2", "msd_t: noisy minus twin post-update mean-square residual (float64 history)", ("analysed_frame",)),
    "cross_term_m2": ("m2", "X_t = msd_t - DeltaV_t", ("analysed_frame",)),
    "mask_disagreement_rows": ("rows", "rows on which the two arms' effective masks differ", ("frame",)),
    "calibration_valid_rows": ("bool", "calibration-valid rows (the denominator of valid_measurement_fraction)", ("row",)),
    "row_ids": ("id", "measurement row IDs in row order (x then y per lenslet)", ("row",)),
}
_SIDECAR_HISTORY_ARRAYS = {
    "measurement_row_masks": ("bool", "effective rows used by the reconstructor", ("frame", "row")),
    "valid_measurement_fraction": ("fraction", "effective rows over calibration-valid rows", ("frame",)),
    "valid_subaperture_fraction": ("fraction", "sensor-valid lenslets over retained lenslets", ("frame",)),
    "saturation_fraction": ("fraction", "clipped actuators of the applied command", ("frame",)),
    "reconstruction_usable": ("bool", "a usable reconstruction reached the controller", ("frame",)),
    "open_loop_opd_rms_m": ("m", "piston-removed pupil RMS of the atmosphere", ("frame",)),
    "pre_update_residual_opd_rms_m": ("m", "residual the sensor saw", ("frame",)),
    "post_update_residual_opd_rms_m": ("m", "residual after the frame's update", ("frame",)),
    "subaperture_ids": ("id", "retained lenslet IDs in lenslet order", ("lenslet",)),
}
_SIDECAR_TELEMETRY_ARRAYS = {
    "centroids_xy_px": ("px", "noisy processed centroid in window pixel coordinates (x = column, y = row); NaN where not finite", ("frame", "lenslet", "xy")),
    "expected_centroids_xy_px": ("px", "plain centre of gravity of the expected processed window of the same frame, same coordinates; NaN where the window total is not positive", ("frame", "lenslet", "xy")),
    "centroid_sigma_xy_px": ("px", "detector_covariance_v2 temporal sigma per axis at the frame's own expected spot; NaN where unsupported", ("frame", "lenslet", "xy")),
    "fluxes_e": ("e", "model-expected processed window flux (the flux gate's input)", ("frame", "lenslet")),
    "peak_snr": ("1", "peak-pixel SNR", ("frame", "lenslet")),
    "total_snr": ("1", "window-total SNR (SNR_T)", ("frame", "lenslet")),
    "centroid_sigma_px": ("px", "larger-axis model sigma; 1e6 where undefined", ("frame", "lenslet")),
    "clipping_fraction": ("fraction", "expected flux outside the window (1 - capture)", ("frame", "lenslet")),
    "centroid_calibration_sigma_px": ("px", "calibration-ensemble sigma (persistent per-run bias)", ("frame", "lenslet")),
    "masked_pixel_fraction": ("fraction", "masked (bad) fraction of the centroid window", ("frame", "lenslet")),
    "saturated_pixel_count": ("pixels", "saturated pixels per block", ("frame", "lenslet")),
    "valid_subapertures": ("bool", "sensor validity (aggregate of the four gates); for the mask-locked arm the locked validity", ("frame", "lenslet")),
    "valid_by_flux": ("bool", "flux gate", ("frame", "lenslet")),
    "valid_by_snr": ("bool", "peak-SNR gate", ("frame", "lenslet")),
    "valid_by_uncertainty": ("bool", "centroid-sigma gate", ("frame", "lenslet")),
    "valid_by_clipping": ("bool", "window-clipping gate", ("frame", "lenslet")),
    "uncertainty_supported": ("bool", "detector_covariance_v2 supports the lenslet", ("frame", "lenslet")),
}
_SIDECAR_WEIGHT_ARRAYS = {
    "propagation_weights__weights_m2_per_px2": ("m2_opd_per_px2", "pupil variance of the DM response to a unit slope in the row (fixed reconstructor)", ("row",)),
}
_SIDECAR_MAP_ARRAYS = {
    "residual_maps__pupil_mask": ("bool", "pupil samples kept by the map recorder", ("y", "x")),
}
# The retained residual maps of one arm (``residual_maps__<arm>``).
_SIDECAR_RESIDUAL_MAP_ARM = ("m", "post-update residual OPD at the pupil samples (float32)", ("analysed_frame", "pupil_sample"))
_SIDECAR_LOCK_ARRAYS = {
    "mask_lock__rows_removed": ("rows", "rows the lock removed from the noisy arm's own validity", ("frame",)),
    "mask_lock__rows_added": ("rows", "rows the lock forced valid", ("frame",)),
    "mask_lock__rows_unaddable": ("rows", "scheduled rows that could not be forced (partial lock only)", ("frame",)),
    "mask_lock__own_valid_subapertures": ("bool", "the noisy sensor's own gate decisions before the lock", ("frame", "lenslet")),
}


class TraceSidecarError(SystemExit):
    """A trace sidecar could not be published or verified; nothing is repaired."""


def _text_array(values: Any) -> np.ndarray:
    """A fixed-width unicode array: loadable without pickle."""

    return np.array([str(value) for value in values], dtype=str)


def _jsonable(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    if isinstance(value, np.generic):
        return value.item()
    if isinstance(value, np.ndarray):
        return value.tolist()
    return value


def diagnostic_protocol(
    *,
    mode: str,
    label: str,
    root_seed: int,
    retain_residual_maps: bool,
    propagation_weights: bool,
    allow_partial_lock: bool | None,
) -> dict[str, Any]:
    """The tracing semantics a traced run is bound to, beside its physical protocol.

    ``map_retention`` is the only per-run field; everything else is shared by
    every run of one traced record.  The physical protocol (series protocol 4)
    is unchanged; this payload never includes a sidecar digest.
    """

    from shwfs_ao.experiments.detector_level import (
        MASK_LOCK_SCHEMA,
        MASK_LOCKED_NOISE_ARMS,
        PAIRED_NOISE_ARMS,
        TRACE_SCHEMA,
    )

    if mode not in ("traced", "mask_locked"):
        raise ValueError("mode must be 'traced' or 'mask_locked'.")
    locked = mode == "mask_locked"
    return {
        "diagnostic_protocol_version": DIAGNOSTIC_PROTOCOL_VERSION,
        "family": TRACE_FAMILY,
        "mode": mode,
        "trace_schema": TRACE_SCHEMA,
        "sidecar_schema": TRACE_SIDECAR_SCHEMA,
        "arm_order": list(MASK_LOCKED_NOISE_ARMS if locked else PAIRED_NOISE_ARMS),
        "mask_source": "operating_expectation twin of the same run and seed, frame by frame" if locked else None,
        "mask_lock_schema": MASK_LOCK_SCHEMA if locked else None,
        "forced_row_policy": (
            None if not locked else ("keep_unaddable_rows_invalid" if allow_partial_lock else "refuse_nonfinite_forced_rows")
        ),
        "frame_domain": (
            "masks and telemetry for every frame 0..n_steps-1; delta_v_m2, mean_square_difference_m2 and "
            "cross_term_m2 for frames >= burn_in_frames; residual maps for frames >= burn_in_frames"
        ),
        "trace_fields": {
            "history": sorted(name for name in _SIDECAR_HISTORY_ARRAYS if name != "subaperture_ids"),
            "telemetry": sorted(_SIDECAR_TELEMETRY_ARRAYS),
            "series": sorted(name for name in _SIDECAR_SHARED_ARRAYS if name not in ("row_ids", "calibration_valid_rows")),
        },
        "dtypes": {"telemetry_floats": "float64", "masks": "bool", "residual_maps": "float32", "series": "float64"},
        "propagation_weights": bool(propagation_weights),
        "map_retention": {"label": label, "root_seed": int(root_seed), "retained": bool(retain_residual_maps)},
    }


def _shared_diagnostic(protocol: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in protocol.items() if key != "map_retention"}


def sidecar_name(stem: str, label: str, root_seed: int) -> str:
    return f"{stem}__{label}__seed{int(root_seed)}.npz"


def _sidecar_arrays(trace: dict[str, Any]) -> tuple[dict[str, np.ndarray], dict[str, Any]]:
    """Flatten a trace payload into sidecar arrays and their declared units and axes."""

    arrays: dict[str, np.ndarray] = {}
    declared: dict[str, Any] = {}

    def put(name: str, value: np.ndarray, unit: str, meaning: str, axes: tuple[str, ...]) -> None:
        array = np.ascontiguousarray(value)
        arrays[name] = array
        declared[name] = {"dtype": str(array.dtype), "shape": [int(size) for size in array.shape], "units": unit, "meaning": meaning, "axes": list(axes)}

    for name, (unit, meaning, axes) in _SIDECAR_SHARED_ARRAYS.items():
        value = trace[name]
        put(name, _text_array(value) if name == "row_ids" else np.asarray(value), unit, meaning, axes)
    for arm in trace["arm_order"]:
        entry = trace["arms"][arm]
        for name, (unit, meaning, axes) in _SIDECAR_HISTORY_ARRAYS.items():
            value = entry[name]
            put(f"{arm}__{name}", _text_array(value) if name == "subaperture_ids" else np.asarray(value), unit, meaning, axes)
        for name, array in entry["telemetry"].items():
            unit, meaning, axes = _SIDECAR_TELEMETRY_ARRAYS[name]
            put(f"{arm}__telemetry__{name}", array, unit, meaning, axes)
    weights = trace.get("propagation_weights")
    if weights is not None and weights.get("available"):
        unit, meaning, axes = _SIDECAR_WEIGHT_ARRAYS["propagation_weights__weights_m2_per_px2"]
        put("propagation_weights__weights_m2_per_px2", np.asarray(weights["weights_m2_per_px2"], dtype=float), unit, meaning, axes)
    maps = trace.get("residual_maps")
    if maps is not None:
        unit, meaning, axes = _SIDECAR_MAP_ARRAYS["residual_maps__pupil_mask"]
        put("residual_maps__pupil_mask", np.asarray(maps["pupil_mask"], dtype=bool), unit, meaning, axes)
        for arm in trace["arm_order"]:
            put(f"residual_maps__{arm}", np.asarray(maps[arm], dtype=np.float32), *_SIDECAR_RESIDUAL_MAP_ARM)
    lock = trace.get("mask_lock")
    if lock is not None:
        for name, (unit, meaning, axes) in _SIDECAR_LOCK_ARRAYS.items():
            put(name, np.asarray(lock[name.split("__", 1)[1]]), unit, meaning, axes)
    return arrays, declared


def publish_sidecar(destination: Path, arrays: dict[str, np.ndarray], metadata: dict[str, Any]) -> dict[str, Any]:
    """Write the complete sidecar atomically, never over an existing file, and return its reference.

    The archive is built in memory, digested, written to a temporary file in
    the same directory, synced, hard-linked into place (which fails if the
    destination exists), read back and compared with the digest.  The
    reference names the file, its SHA-256, its size and its schema.
    """

    import io
    import secrets

    destination = Path(destination)
    if destination.exists():
        raise TraceSidecarError(
            f"{destination} exists and is not referenced by the record being written: an ambiguous leftover "
            "(an interrupted invocation, or another study's file).  Move it aside or pass --output NAME; "
            "nothing is overwritten."
        )
    buffer = io.BytesIO()
    np.savez_compressed(buffer, metadata_json=np.array(json.dumps(metadata, sort_keys=True, default=str)), **arrays)
    payload = buffer.getvalue()
    digest = hashlib.sha256(payload).hexdigest()
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(f"{destination.name}{_SIDECAR_TEMP_MARK}{os.getpid()}-{secrets.token_hex(4)}")
    with open(temporary, "xb") as handle:
        handle.write(payload)
        handle.flush()
        os.fsync(handle.fileno())
    try:
        os.link(temporary, destination)
    except FileExistsError:
        temporary.unlink()
        raise TraceSidecarError(f"{destination} appeared while the sidecar was being written; nothing was overwritten.") from None
    temporary.unlink()
    directory = os.open(destination.parent, os.O_RDONLY)
    try:
        os.fsync(directory)
    finally:
        os.close(directory)
    published = destination.read_bytes()
    if hashlib.sha256(published).hexdigest() != digest or len(published) != len(payload):
        raise TraceSidecarError(f"{destination} does not read back as the bytes written; the file is left as it is.")
    read_sidecar(destination, expected_sha256=digest)
    return {"file": destination.name, "sha256": digest, "bytes": len(payload), "schema": TRACE_SIDECAR_SCHEMA}


def read_sidecar(path: Path, *, expected_sha256: str | None = None) -> tuple[dict[str, Any], dict[str, np.ndarray]]:
    """Load and validate a sidecar without pickle; refuse corruption or undeclared content."""

    path = Path(path)
    if not path.is_file():
        raise TraceSidecarError(f"{path} is missing.")
    payload = path.read_bytes()
    digest = hashlib.sha256(payload).hexdigest()
    if expected_sha256 is not None and digest != expected_sha256:
        raise TraceSidecarError(f"{path}: SHA-256 {digest} is not the recorded {expected_sha256}.")
    try:
        with np.load(path, allow_pickle=False) as archive:
            names = set(archive.files)
            if "metadata_json" not in names:
                raise TraceSidecarError(f"{path}: no metadata_json entry.")
            metadata = json.loads(archive["metadata_json"].item())
            arrays = {name: archive[name] for name in names if name != "metadata_json"}
    except (OSError, ValueError, KeyError, zipfile.BadZipFile) as exc:
        raise TraceSidecarError(f"{path}: not a readable sidecar ({exc}).") from None
    if not isinstance(metadata, dict) or metadata.get("schema") != TRACE_SIDECAR_SCHEMA:
        raise TraceSidecarError(f"{path}: schema {metadata.get('schema') if isinstance(metadata, dict) else None!r} is not {TRACE_SIDECAR_SCHEMA}.")
    declared = metadata.get("arrays")
    if not isinstance(declared, dict) or set(declared) != set(arrays):
        raise TraceSidecarError(f"{path}: the arrays present do not match the declared arrays.")
    for name, spec in declared.items():
        array = arrays[name]
        if str(array.dtype) != spec.get("dtype") or [int(size) for size in array.shape] != list(spec.get("shape", [])):
            raise TraceSidecarError(f"{path}: array {name} has dtype {array.dtype} and shape {array.shape}, declared {spec}.")
    return metadata, arrays


def _expected_sidecar_layout(
    *,
    diagnostic: dict[str, Any],
    n_steps: int,
    burn_in: int,
    n_rows: int,
    n_lenslets: int,
    telemetry_unavailable: dict[str, list[str]],
    weights_available: bool,
) -> dict[str, tuple[str, tuple[int, ...] | None, str, str, tuple[str, ...]]]:
    """Every array a sidecar of this diagnostic protocol must hold: dtype, shape, units, meaning, axes.

    A ``None`` shape leaves one axis free (the pupil-sample count of retained
    maps, the two axes of the pupil mask); everything else is fixed by the
    frame count, the burn-in, the row count and the lenslet count.  Units,
    meaning and axes are the canonical declarations the writer uses, so a
    reader can compare values, not only the presence of the keys.
    """

    analysed = n_steps - burn_in
    layout: dict[str, tuple[str, tuple[int, ...] | None, str, str, tuple[str, ...]]] = {}
    series_dtypes = {
        "frame_index": ("int64", (n_steps,)),
        "analysed_frame_index": ("int64", (analysed,)),
        "delta_v_m2": ("float64", (analysed,)),
        "mean_square_difference_m2": ("float64", (analysed,)),
        "cross_term_m2": ("float64", (analysed,)),
        "mask_disagreement_rows": ("int64", (n_steps,)),
        "calibration_valid_rows": ("bool", (n_rows,)),
        "row_ids": ("str", (n_rows,)),
    }
    for name, (dtype, shape) in series_dtypes.items():
        unit, meaning, axes = _SIDECAR_SHARED_ARRAYS[name]
        layout[name] = (dtype, shape, unit, meaning, axes)
    for arm in diagnostic["arm_order"]:
        for name, (unit, meaning, axes) in _SIDECAR_HISTORY_ARRAYS.items():
            if name == "subaperture_ids":
                dtype, shape = "str", (n_lenslets,)
            elif unit == "bool":
                dtype, shape = "bool", ((n_steps, n_rows) if "row" in axes else (n_steps,))
            else:
                dtype, shape = "float64", (n_steps,)
            layout[f"{arm}__{name}"] = (dtype, shape, unit, meaning, axes)
        for name in diagnostic["trace_fields"]["telemetry"]:
            if name in telemetry_unavailable.get(arm, []):
                continue
            unit, meaning, axes = _SIDECAR_TELEMETRY_ARRAYS[name]
            shape = (n_steps, n_lenslets, 2) if "xy" in axes else (n_steps, n_lenslets)
            layout[f"{arm}__telemetry__{name}"] = ("bool" if unit == "bool" else "float64", shape, unit, meaning, axes)
    if weights_available:
        unit, meaning, axes = _SIDECAR_WEIGHT_ARRAYS["propagation_weights__weights_m2_per_px2"]
        layout["propagation_weights__weights_m2_per_px2"] = ("float64", (n_rows,), unit, meaning, axes)
    if diagnostic["map_retention"]["retained"]:
        unit, meaning, axes = _SIDECAR_MAP_ARRAYS["residual_maps__pupil_mask"]
        layout["residual_maps__pupil_mask"] = ("bool", None, unit, meaning, axes)
        for arm in diagnostic["arm_order"]:
            layout[f"residual_maps__{arm}"] = ("float32", None, *_SIDECAR_RESIDUAL_MAP_ARM)
    if diagnostic["mode"] == "mask_locked":
        for name, (unit, meaning, axes) in _SIDECAR_LOCK_ARRAYS.items():
            dtype, shape = ("bool", (n_steps, n_lenslets)) if unit == "bool" else ("int64", (n_steps,))
            layout[name] = (dtype, shape, unit, meaning, axes)
    return layout


def validate_trace_payload(
    metadata: dict[str, Any],
    arrays: dict[str, np.ndarray],
    *,
    label: str,
    root_seed: int,
    n_steps: int,
    burn_in: int,
    diagnostic: dict[str, Any],
    diagnostic_hash: str,
    where: str,
) -> None:
    """Refuse a sidecar whose content does not carry the intended trace semantics.

    Beyond the digest and the self-declared array table, the archive must
    embed the run's frame counts, the row's diagnostic protocol (equal to the
    embedded hash and to the row's), the protocol's trace schema and arm
    order, and exactly the arrays that protocol requires, each with its
    dtype and shape fixed by the frame, row and lenslet counts and with the
    protocol's own units, axes and meaning declared (values compared, not
    key presence); frame indices that are the declared domains; one lenslet
    order shared by every arm and the canonical interleaved x/y rows of that
    order (independent review T1-02, 2026-10-20 and its round 2 of
    2026-10-21).  Nothing is repaired.
    """

    def refuse(reason: str) -> None:
        raise TraceSidecarError(f"{where}: {reason}")

    if int(metadata.get("n_steps", -1)) != int(n_steps) or int(metadata.get("burn_in_frames", -1)) != int(burn_in):
        refuse(f"embeds n_steps {metadata.get('n_steps')!r} and burn_in_frames {metadata.get('burn_in_frames')!r}, the run has {n_steps} and {burn_in}")
    if metadata.get("label") != label or metadata.get("root_seed") != int(root_seed):
        refuse("embeds another label or seed than its run")
    embedded = metadata.get("diagnostic_protocol")
    if not isinstance(embedded, dict) or protocol_digest(embedded) != metadata.get("diagnostic_protocol_hash"):
        refuse("its embedded diagnostic protocol is not the payload of its embedded diagnostic hash")
    if _canonical(embedded) != _canonical(diagnostic) or metadata.get("diagnostic_protocol_hash") != diagnostic_hash:
        refuse("its embedded diagnostic protocol is not the run row's")
    if metadata.get("trace_schema") != diagnostic["trace_schema"] or list(metadata.get("arm_order", [])) != list(diagnostic["arm_order"]):
        refuse(f"embeds trace schema {metadata.get('trace_schema')!r} and arm order {metadata.get('arm_order')!r}, the protocol expects {diagnostic['trace_schema']!r} and {diagnostic['arm_order']!r}")
    arms = metadata.get("arms")
    if not isinstance(arms, dict) or set(arms) != set(diagnostic["arm_order"]):
        refuse("its per-arm metadata does not name exactly the protocol's arms")
    noisy = next(arm for arm in diagnostic["arm_order"] if arm.startswith("noise_on"))
    twin = next(arm for arm in diagnostic["arm_order"] if arm != noisy)
    if metadata.get("noisy_arm") != noisy or metadata.get("twin_arm") != twin:
        refuse("its noisy and twin arm names do not follow the protocol's arm order")
    unavailable = {arm: list(arms[arm].get("telemetry_unavailable", [])) for arm in arms}
    for arm, names in unavailable.items():
        unknown = [name for name in names if name not in _SIDECAR_TELEMETRY_ARRAYS]
        if unknown:
            refuse(f"arm {arm} declares unknown unavailable telemetry fields {unknown}")
    if "row_ids" not in arrays or "calibration_valid_rows" not in arrays:
        refuse("has no row layout (row_ids and calibration_valid_rows)")
    n_rows = int(arrays["row_ids"].shape[0]) if arrays["row_ids"].ndim == 1 else -1
    first_ids = arrays.get(f"{noisy}__subaperture_ids")
    if first_ids is None or first_ids.ndim != 1:
        refuse("has no lenslet layout for the noisy arm")
    n_lenslets = int(first_ids.shape[0])
    if n_rows != 2 * n_lenslets or n_rows < 2:
        refuse(f"has {n_rows} rows for {n_lenslets} lenslets; the Shack-Hartmann layout needs two rows per lenslet")
    weights_available = bool((metadata.get("propagation_weights") or {}).get("available")) if diagnostic.get("propagation_weights") else False
    if "propagation_weights__weights_m2_per_px2" in arrays and not weights_available:
        refuse("holds propagation weights its metadata does not declare available")
    layout = _expected_sidecar_layout(
        diagnostic=diagnostic, n_steps=n_steps, burn_in=burn_in, n_rows=n_rows, n_lenslets=n_lenslets,
        telemetry_unavailable=unavailable, weights_available=weights_available,
    )
    missing = sorted(set(layout) - set(arrays))
    extra = sorted(set(arrays) - set(layout))
    if missing or extra:
        refuse(f"does not hold exactly the protocol's arrays (missing {missing[:8]}{'...' if len(missing) > 8 else ''}, undeclared {extra[:8]}{'...' if len(extra) > 8 else ''})")
    declared = metadata.get("arrays", {})
    for name, (dtype, shape, unit, meaning, axes) in layout.items():
        array = arrays[name]
        spec = declared.get(name, {})
        # Values, not only keys: the declaration must be the canonical one of
        # the protocol (independent review round 2, T1-02).
        if spec.get("units") != unit or list(spec.get("axes", [])) != list(axes) or spec.get("meaning") != meaning:
            refuse(f"array {name} is declared with units {spec.get('units')!r}, axes {spec.get('axes')!r} and meaning {spec.get('meaning')!r}; the protocol defines {unit!r}, {list(axes)!r}, {meaning!r}")
        if dtype == "str":
            if array.dtype.kind != "U":
                refuse(f"array {name} must hold unicode identifiers")
        elif str(array.dtype) != dtype:
            refuse(f"array {name} has dtype {array.dtype}, the protocol requires {dtype}")
        if shape is not None and tuple(int(size) for size in array.shape) != tuple(shape):
            refuse(f"array {name} has shape {array.shape}, the protocol requires {shape}")
    if not np.array_equal(arrays["frame_index"], np.arange(n_steps)):
        refuse("frame_index is not 0..n_steps-1")
    if not np.array_equal(arrays["analysed_frame_index"], np.arange(burn_in, n_steps)):
        refuse("analysed_frame_index is not burn_in..n_steps-1")
    # One lenslet order for every arm, and the canonical interleaved x/y rows
    # of that order: masks, centroid axes and weights refer to the same rows.
    from shwfs_ao.wfs.shack_hartmann.calibration import row_ids_for_subapertures

    lenslet_ids = tuple(str(item) for item in first_ids.tolist())
    if len(set(lenslet_ids)) != n_lenslets:
        refuse("the lenslet identifiers are duplicated")
    for arm in diagnostic["arm_order"]:
        if tuple(str(item) for item in arrays[f"{arm}__subaperture_ids"].tolist()) != lenslet_ids:
            refuse(f"arm {arm} lists the lenslets in another order than arm {noisy}")
    canonical_rows = row_ids_for_subapertures(lenslet_ids)
    if tuple(str(item) for item in arrays["row_ids"].tolist()) != canonical_rows:
        refuse("row_ids are not the canonical interleaved x/y rows of the lenslet order")
    if diagnostic["map_retention"]["retained"]:
        mask = arrays["residual_maps__pupil_mask"]
        if mask.ndim != 2:
            refuse("the retained pupil mask is not a 2-D map")
        samples = int(np.count_nonzero(mask))
        for arm in diagnostic["arm_order"]:
            maps = arrays[f"residual_maps__{arm}"]
            if maps.shape != (n_steps - burn_in, samples):
                refuse(f"retained maps of arm {arm} have shape {maps.shape}, the mask and burn-in require {(n_steps - burn_in, samples)}")


def traced_run_factory(
    settings: dict[str, Any], *, mode: str, allow_partial_lock: bool = False, propagation_weights: bool = True
) -> Any:
    """A gated-series runner that traces each paired run and publishes its sidecar.

    Called by :func:`_gated_series` with ``run_context=True``; the context
    carries the run's label and physical protocol, which the sidecar embeds.
    A :class:`MaskLockError` is a refused run (recorded as such, no sidecar).
    """

    from shwfs_ao.calibration.interaction import InteractionMatrixError
    from shwfs_ao.experiments.detector_level import (
        MaskLockError,
        paired_noise_run_mask_locked,
        paired_noise_run_traced,
    )
    from shwfs_ao.experiments.scao import ScaoConstructionError

    map_seeds = settings["map_seeds"]

    def run(config: Any, *, root_seed: int, n_steps: int, burn_in_frames: int, execution: Any, context: dict[str, Any]) -> dict[str, Any]:
        label = context["label"]
        retain = map_seeds.get(label) == int(root_seed)
        diagnostic = diagnostic_protocol(
            mode=mode, label=label, root_seed=root_seed, retain_residual_maps=retain,
            propagation_weights=propagation_weights, allow_partial_lock=allow_partial_lock if mode == "mask_locked" else None,
        )
        diagnostic_hash = protocol_digest(diagnostic)
        destination = output_directory() / sidecar_name(_record_stem(context["record_path"]), label, root_seed)
        if destination.exists():
            raise TraceSidecarError(
                f"{destination} exists before its run: an ambiguous leftover of an interrupted invocation.  "
                "Move it aside or pass --output NAME; nothing is overwritten."
            )
        try:
            if mode == "mask_locked":
                result = paired_noise_run_mask_locked(
                    config, root_seed=root_seed, n_steps=n_steps, burn_in_frames=burn_in_frames, execution=execution,
                    allow_partial_lock=allow_partial_lock, retain_residual_maps=retain, propagation_weights=propagation_weights,
                )
            else:
                result = paired_noise_run_traced(
                    config, root_seed=root_seed, n_steps=n_steps, burn_in_frames=burn_in_frames, execution=execution,
                    retain_residual_maps=retain, propagation_weights=propagation_weights,
                )
        except (MaskLockError, ScaoConstructionError, InteractionMatrixError) as exc:
            # Every supported refusal keeps the diagnostic identity it was
            # planned under, so the record stays resumable (independent
            # review T1-03, 2026-10-20); the legacy handler in _gated_series
            # is not reached for traced runs.
            return {"status": "refused", "reason": str(exc)[:500], "root_seed": int(root_seed), "diagnostic_protocol": diagnostic, "diagnostic_protocol_hash": diagnostic_hash}
        trace = result.pop("trace")
        arrays, declared = _sidecar_arrays(trace)
        weights = trace.get("propagation_weights")
        metadata = {
            "schema": TRACE_SIDECAR_SCHEMA,
            "family": TRACE_FAMILY,
            "record_stem": _record_stem(context["record_path"]),
            "label": label,
            "root_seed": int(root_seed),
            "config_hash": result["config_hash"],
            "n_steps": int(n_steps),
            "burn_in_frames": int(burn_in_frames),
            "protocol_hash": context["protocol"]["protocol_hash"],
            "series_protocol_version": SERIES_PROTOCOL_VERSION,
            "code": context["protocol"]["protocol"]["code"],
            "environment": context["protocol"]["protocol"]["environment"],
            "diagnostic_protocol": diagnostic,
            "diagnostic_protocol_hash": diagnostic_hash,
            "trace_schema": trace["schema"],
            "arm_order": trace["arm_order"],
            "noisy_arm": trace["noisy_arm"],
            "twin_arm": trace["twin_arm"],
            "arms": {
                arm: {
                    "history_config_hash": entry["history_config_hash"],
                    "component_hashes": entry["component_hashes"],
                    "random_stream_ids": entry["random_stream_ids"],
                    "recovery": entry["recovery"],
                    "wfs_exposure": entry["wfs_exposure"],
                    "telemetry_unavailable": entry["telemetry_unavailable"],
                    "telemetry_frames": entry["telemetry_frames"],
                }
                for arm, entry in trace["arms"].items()
            },
            "propagation_weights": None if weights is None else {key: value for key, value in weights.items() if key != "weights_m2_per_px2"},
            "residual_maps": None if trace.get("residual_maps") is None else {"precision": trace["residual_maps"]["precision"]},
            "arrays": declared,
            "created_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        }
        if "lock" in result:
            metadata["lock"] = result["lock"]
        result["sidecar"] = publish_sidecar(destination, arrays, _jsonable(metadata))
        written_metadata, written_arrays = read_sidecar(destination, expected_sha256=result["sidecar"]["sha256"])
        validate_trace_payload(
            written_metadata, written_arrays, label=label, root_seed=int(root_seed), n_steps=int(n_steps), burn_in=int(burn_in_frames),
            diagnostic=diagnostic, diagnostic_hash=diagnostic_hash, where=f"published sidecar {destination.name}",
        )
        result["diagnostic_protocol"] = diagnostic
        result["diagnostic_protocol_hash"] = diagnostic_hash
        return _jsonable(result)

    return run


def _record_stem(record_path: Path) -> str:
    return Path(record_path).stem


def traced_record_validator(settings: dict[str, Any], *, mode: str, allow_partial_lock: bool = False, propagation_weights: bool = True) -> Any:
    """The retained-run validator of a traced record: payload, digest and protocol before anything runs.

    Every retained row must carry a diagnostic protocol whose digest is its
    stored hash and whose shared part is this invocation's; its sidecar must
    exist in the record's directory with the recorded size and SHA-256, load
    without pickle with exactly its declared arrays, embed the row's label,
    seed, configuration hash, physical protocol hash, diagnostic hash and
    producer (code identity and environment), and pass
    :func:`validate_trace_payload` against the row's protocol (frame counts,
    trace schema, arm order, required arrays with their dtypes, shapes and
    declared units, frame domains, row and lenslet layout, map retention).  Every sidecar of the
    record's stem in the directory must be referenced by a retained row, and
    no temporary file of an interrupted publication may remain.  A refused
    retained row (``status == "refused"``) has no sidecar.  Nothing is
    written, so a complete no-op invocation leaves bytes and mtimes alone.
    """

    def validate(path: Path, retained: list[dict[str, Any]]) -> None:
        directory = Path(path).parent
        record_stem = Path(path).stem
        reference = diagnostic_protocol(
            mode=mode, label="", root_seed=0, retain_residual_maps=False,
            propagation_weights=propagation_weights, allow_partial_lock=allow_partial_lock if mode == "mask_locked" else None,
        )
        shared = _shared_diagnostic(reference)
        referenced: set[str] = set()
        for index, row in enumerate(retained):
            label, seed = row.get("label"), row.get("root_seed")
            diagnostic = row.get("diagnostic_protocol")
            if not isinstance(diagnostic, dict) or protocol_digest(diagnostic) != row.get("diagnostic_protocol_hash"):
                raise EvidenceRecordExists(
                    f"{path}: run {index} ({label}, {seed}) has no diagnostic protocol or its hash is not the digest of its "
                    "payload; nothing ran and the record is unchanged.  Pass --output NAME for a fresh record."
                )
            if _canonical(_shared_diagnostic(diagnostic)) != _canonical(shared):
                raise EvidenceRecordExists(
                    f"{path}: run {index} ({label}, {seed}) was traced under other diagnostic semantics (trace fields, "
                    "frame domain, arm order, mask source or dtypes) than this invocation's, although its physical "
                    "protocol may match; nothing ran and the record is unchanged.  Pass --output NAME for a fresh record."
                )
            retention = diagnostic.get("map_retention", {})
            if retention.get("label") != label or retention.get("root_seed") != seed:
                raise EvidenceRecordExists(f"{path}: run {index} ({label}, {seed}) carries another run's map retention; nothing ran.")
            intended = settings["map_seeds"].get(label) == seed if label in settings["map_seeds"] else bool(retention.get("retained"))
            if bool(retention.get("retained")) != intended:
                raise EvidenceRecordExists(
                    f"{path}: run {index} ({label}, {seed}) retained residual maps = {retention.get('retained')}, "
                    f"but this study retains them for {label} at seed {settings['map_seeds'].get(label)}; nothing ran."
                )
            if row.get("status") == "refused":
                continue
            sidecar = row.get("sidecar")
            if not isinstance(sidecar, dict) or not all(isinstance(sidecar.get(key), str) for key in ("file", "sha256", "schema")) or not isinstance(sidecar.get("bytes"), int):
                raise EvidenceRecordExists(f"{path}: run {index} ({label}, {seed}) has no complete sidecar reference; nothing ran.")
            if sidecar["file"] != sidecar_name(record_stem, label, seed) or sidecar["schema"] != TRACE_SIDECAR_SCHEMA:
                raise EvidenceRecordExists(f"{path}: run {index} ({label}, {seed}) references sidecar {sidecar['file']!r} of another name or schema; nothing ran.")
            file = directory / sidecar["file"]
            if not file.is_file():
                raise EvidenceRecordExists(f"{path}: the referenced sidecar {file} is missing; nothing ran and the record is unchanged.")
            if file.stat().st_size != sidecar["bytes"]:
                raise EvidenceRecordExists(f"{path}: sidecar {file} has {file.stat().st_size} bytes, recorded {sidecar['bytes']}; nothing ran.")
            try:
                metadata, arrays = read_sidecar(file, expected_sha256=sidecar["sha256"])
            except TraceSidecarError as exc:
                raise EvidenceRecordExists(f"{path}: {exc}; nothing ran and the record is unchanged.") from None
            protocol = row.get("protocol", {})
            try:
                validate_trace_payload(
                    metadata, arrays, label=label, root_seed=int(seed), n_steps=int(protocol.get("n_steps", -1)),
                    burn_in=int(protocol.get("burn_in_frames", -1)), diagnostic=diagnostic,
                    diagnostic_hash=row["diagnostic_protocol_hash"], where=f"sidecar {file.name}",
                )
            except TraceSidecarError as exc:
                raise EvidenceRecordExists(f"{path}: {exc}; malformed or inconsistent evidence is not reused; nothing ran and the record is unchanged.") from None
            expected_fields = {
                "label": label, "root_seed": seed, "config_hash": row.get("config_hash"),
                "protocol_hash": row.get("protocol_hash"), "diagnostic_protocol_hash": row.get("diagnostic_protocol_hash"),
                "record_stem": record_stem, "family": TRACE_FAMILY,
            }
            for key, expected in expected_fields.items():
                if _canonical(metadata.get(key)) != _canonical(expected):
                    raise EvidenceRecordExists(f"{path}: sidecar {file.name} records {key} = {metadata.get(key)!r}, the run row {expected!r}: inconsistent metadata; nothing ran.")
            if _canonical(metadata.get("code")) != _canonical(protocol.get("code")) or _canonical(metadata.get("environment")) != _canonical(protocol.get("environment")):
                raise EvidenceRecordExists(f"{path}: sidecar {file.name} was produced by another code or environment than its run row: mixed producers; nothing ran.")
            referenced.add(file.name)
        leftovers = sorted(
            candidate.name for candidate in directory.glob(f"{record_stem}__*.npz*")
            if candidate.name not in referenced
        )
        if leftovers:
            raise EvidenceRecordExists(
                f"{path}: sidecar files {leftovers} are not referenced by any retained run (an interrupted invocation "
                "leaves such orphans or temporary files); they are ambiguous leftovers.  Move them aside or pass "
                "--output NAME; nothing ran and nothing was deleted."
            )

    return validate


def _traced_series(settings: dict[str, Any], command: str, *, mode: str, **keywords: Any) -> None:
    from shwfs_ao.experiments.detector_level import with_magnitude
    from shwfs_ao.io.configs import load_system_profile

    base = load_system_profile(*settings["profile"])
    plan = [
        (f"m{magnitude:g}", with_magnitude(base, magnitude), seed)
        for magnitude in settings["magnitudes"]
        for seed in settings["seeds"]
    ]
    _gated_series(
        settings["record"], command, plan, n_steps=settings["n_steps"], burn_in=settings["burn_in"],
        execution=_summary_execution(), runner=traced_run_factory(settings, mode=mode), run_context=True,
        validate_retained=traced_record_validator(settings, mode=mode),
        header_extra={
            "record_family": TRACE_FAMILY,
            "diagnostic_protocol_shared": _shared_diagnostic(
                diagnostic_protocol(mode=mode, label="", root_seed=0, retain_residual_maps=False, propagation_weights=True,
                                    allow_partial_lock=False if mode == "mask_locked" else None)
            ),
            "residual_map_seeds": dict(settings["map_seeds"]),
        },
        **keywords,
    )


def noise_isolation_2m_traced(arguments: argparse.Namespace) -> None:
    _traced_series(
        NOISE_ISOLATION_2M_TRACED, "noise-isolation-2m-traced", mode="traced",
        enabled_by_user="not gated: 2 m tier (prompt section 2.5)",
    )


def noise_isolation_12m_traced(arguments: argparse.Namespace) -> None:
    _traced_series(
        NOISE_ISOLATION_12M_TRACED, "noise-isolation-12m-traced (profile @3)", mode="traced",
        enabled_by_user=arguments.enabled_by_user,
    )


def noise_isolation_12m_masklocked(arguments: argparse.Namespace) -> None:
    _traced_series(
        NOISE_ISOLATION_12M_MASKLOCKED, "noise-isolation-12m-masklocked (profile @3, arm B)", mode="mask_locked",
        enabled_by_user=arguments.enabled_by_user,
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
    # The S4 traced family (T1): the 2 m command is ungated like the recorded
    # 2 m study; both 12 m commands refuse at argument parsing without the
    # user's enablement note, before any profile is loaded or system built.
    commands["noise-isolation-2m-traced"] = noise_isolation_2m_traced
    sub.add_parser("noise-isolation-2m-traced")
    commands["noise-isolation-12m-traced"] = noise_isolation_12m_traced
    sub.add_parser("noise-isolation-12m-traced").add_argument("--enabled-by-user", required=True)
    commands["noise-isolation-12m-masklocked"] = noise_isolation_12m_masklocked
    sub.add_parser("noise-isolation-12m-masklocked").add_argument("--enabled-by-user", required=True)
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
