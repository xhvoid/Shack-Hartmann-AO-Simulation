"""Paired spatial-sampling convergence of the ESO-derived SCAO tiers (roadmap S3).

Extends the smoke-tier study (``scripts/eso_scao_convergence_study.py``, which
could not resolve its 2 % criterion because its screens were unpaired and its
SH field of view changed with the sampling) to the ``medium`` (12 m) and
``full`` (42 m) tiers.  Three one-parameter scans start from the tier's
baseline (12 pupil samples per lenslet; WFS pad 2 with the 23-pixel window;
science pad 2) and change one sampling at a time:

* pupil samples per lenslet ``s`` = 12, 16 (and 20 at 12 m).  The WFS keeps
  pad 2 and the 23-pixel window, so its pixel scale and its field of view
  (11.5 lambda/d) stay fixed;
* WFS detector sampling: pad 2, 3, 4 with windows 23, 35, 47 pixels, the
  pixels symmetric about the optical-axis pixel; the field of view stays
  11.5-11.75 lambda/d;
* science image sampling: ``science.psf_pad_factor`` 2, 3, 4.

**Paired atmospheric inputs.**  The layered atmosphere draws each layer's
band coefficients in array order on its own screen grid, so two pupil
samplings would see unrelated screens.  For the duration of a study process
this script replaces that one draw: every setting of a scale draws on the
finest screen grid of the scale (the same keyed generator, consuming the
same number of normals), and a coarser grid takes the coefficients at its own
spatial frequencies.  The screen period (two diameters), and so the frequency
spacing, is the same for every setting, so a coarser screen is the
band-limited version of the finest one, and the subharmonic draws that follow
see the same generator state.  The WFS and science scans keep the grid and
share the same paired draws.  The statistics of each setting are unchanged:
every coefficient is still an independent complex normal scaled by that
grid's own band power.

**Runs.**  Realizations 0, 1, 2 per setting, noiseless; 200 frames with a
50-frame burn-in (the 42 m loop settles within 20 frames); long-exposure
2.2 um peak Strehl and EE50 over the frames after burn-in.  Each run is its
own process, so the recorded ``ru_maxrss`` is that run's peak; a finished run
is never repeated (rerunning the command resumes).

**Run identity and resume** (independent review AR-014, 2026-10-20).
Every run file is named by scale and setting (``full_s12_wfs2_sci2_r0``) and
carries its run protocol: the planned setting, scale, frames, burn-in,
wavelength, paired grid, band storage and configuration hash, and the
producer -- the code identity (a digest of the imported package, null where
its files cannot bind the imported code, the driver's digest, and Git where it
tracks that package) and the numerical environment of the process that made
the run -- with the protocol's SHA-256.
Before any run is launched or any file written, every saved run of the plan
must be its planned run: the stored hash must be its protocol's digest, the
planned fields must equal this invocation's, the fields the row repeats must
equal its protocol's, and its results must be numbers (a non-finite result
is kept and reported as found; it is written as the ``NaN``/``Infinity``
token Python's ``json`` reads back, which strict JSON parsers reject).  All saved runs must have one producer, and
runs are added only when that producer is this invocation's, with a known
code identity.  A run file without a protocol (the version-1 records,
produced 2026-10-18) is neither reused nor relabelled; a summary that exists
is never rewritten -- a rerun with every run and a matching summary recorded
changes nothing.  Any of these cases stops with :class:`StudyRecordError`
before anything runs, leaving every file as it was.  A run a child has just
written is checked the same way and must name this invocation's producer;
if it does not (the tree or environment changed during the study), the study
stops there with that run file kept as written.  A later invocation continues
only while all saved runs share its producer, so once runs of two producers
are saved a fresh ``--output-dir`` is needed.  The summary names the runs'
producer (``run_producer``) apart from the process that wrote it
(``summarized_by``).

**Criterion, declared before the runs.**  For each scan, the realization-mean
peak Strehl and EE50 of the two finest settings agree within 2 % (relative).
The paired per-realization differences and their standard errors are
reported beside it.  A failure is reported as found; nothing is re-tuned.

    PYTHONPATH=<tree>/src python scripts/eso_scao_paired_convergence_study.py \\
        --scale medium --output-dir outputs/s3_medium

``--scale ci`` runs a reduced self-check (one realization, 40 frames) of the
machinery on the 5 m smoke tier.
"""

from __future__ import annotations

import _imp
import argparse
from dataclasses import replace
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import platform
import resource
import subprocess
import sys
import time
from typing import Any

import numpy as np


SCHEMA = "shwfs_ao.eso_scao_paired_convergence_study.v2"
# Version 2 (2026-10-20) gives every run its own protocol identity; version-1
# rows (the records produced 2026-10-18) carry none.
RUN_PROTOCOL_VERSION = 2
TOLERANCE = 0.02
WAVELENGTH_M = 2.2e-6
LENSLETS = {"ci": 10, "medium": 24, "full": 84}
TIER = {"ci": "ci", "medium": "medium", "full": "full"}
PUPIL_SAMPLES = {"ci": (12, 16), "medium": (12, 16, 20), "full": (12, 16)}
WFS_PADS = {"ci": (2, 3), "medium": (2, 3, 4), "full": (2, 3, 4)}
SCIENCE_PADS = {"ci": (2, 3), "medium": (2, 3, 4), "full": (2, 3, 4)}
FRAMES = {"ci": 40, "medium": 200, "full": 200}
BURN_IN = {"ci": 10, "medium": 50, "full": 50}
REALIZATIONS = {"ci": (0,), "medium": (0, 1, 2), "full": (0, 1, 2)}
# Regenerate the bands on the finest 42 m grid only, to keep its peak memory
# near the 12-sample run's; the storage mode is identity-neutral.
REGENERATE = {("full", 16)}
# Fields a run row repeats from its protocol, and the results the summary and
# the progress lines read.
REPEATED_FIELDS = (
    "label",
    "samples_per_lenslet",
    "wfs_pad_factor",
    "wfs_window_px",
    "science_psf_pad_factor",
    "realization",
    "config_hash",
    "paired_reference_screen_size",
    "atmosphere_band_storage",
)
RESULT_FIELDS = ("peak_strehl", "ee50_radius_rad", "residual_rms_nm", "open_loop_rms_nm", "build_s", "loop_s", "ru_maxrss")


class StudyRecordError(SystemExit):
    """Saved study files that this invocation must not reuse or replace."""


def _settings(scale: str) -> dict[str, list[tuple[str, int, int, int]]]:
    """Scan name -> [(label, samples per lenslet, wfs pad, science pad)]."""

    return {
        "pupil_samples_per_lenslet": [(f"s{s}", s, 2, 2) for s in PUPIL_SAMPLES[scale]],
        "wfs_pad_factor": [(f"wfs_pad{p}", 12, p, 2) for p in WFS_PADS[scale]],
        "science_psf_pad_factor": [(f"science_pad{p}", 12, 2, p) for p in SCIENCE_PADS[scale]],
    }


def _config(scale: str, samples: int, wfs_pad: int, science_pad: int):
    from shwfs_ao.experiments.eso_scao_benchmark import tier_config

    base = tier_config(TIER[scale])
    return replace(
        base,
        pupil_pixels=LENSLETS[scale] * samples,
        science_wavelengths_m=(WAVELENGTH_M,),
        # The window is the pad * 12 - 1 pixels symmetric about the
        # optical-axis pixel: 23, 35, 47 at pad 2, 3, 4, whatever ``samples``.
        wfs=replace(base.wfs, pad_factor=wfs_pad, detector_window_px=12 * wfs_pad - 1),
        science=replace(base.science, psf_pad_factor=science_pad),
        controller=replace(base.controller, n_steps=FRAMES[scale]),
    )


def _install_paired_band_draw(reference_size: int) -> None:
    """Make every layered screen a sub-band of one draw on ``reference_size``."""

    from shwfs_ao.backends.native import layered_atmosphere

    def paired_band_draw(self, rng: np.random.Generator, amplitude: float) -> np.ndarray:
        size = self._config.screen_size
        if size > reference_size:
            raise ValueError(f"screen size {size} exceeds the paired reference {reference_size}")
        draws = rng.normal(size=(reference_size, reference_size)) + 1j * rng.normal(
            size=(reference_size, reference_size)
        )
        if size != reference_size:
            index = np.rint(np.fft.fftfreq(size) * size).astype(int) % reference_size
            draws = draws[np.ix_(index, index)]
        # As the library's draw: numpy's inverse FFT divides by size**2.
        return draws * (np.sqrt(self._band_power_rad2) * amplitude * size**2)

    layered_atmosphere.LayeredFrozenFlowAtmosphere._band_draw = paired_band_draw


def _reference_screen_size(scale: str) -> int:
    # The layered screen is two pupils across (screen_size = 2 * pupil_pixels;
    # every run checks this), so the finest pupil sampling sets the reference.
    return 2 * LENSLETS[scale] * max(PUPIL_SAMPLES[scale])


def _storage(scale: str, samples: int) -> str:
    return "regenerate" if (scale, samples) in REGENERATE else "materialized"


def _run_child(scale: str, label: str, samples: int, wfs_pad: int, science_pad: int, realization: int) -> dict:
    from shwfs_ao.experiments.scao import ScaoExecutionOptions, build_scao_system, run_closed_loop
    from shwfs_ao.science.long_exposure import LongExposureConfig, StreamingLongExposure

    reference = _reference_screen_size(scale)
    _install_paired_band_draw(reference)
    config = _config(scale, samples, wfs_pad, science_pad)
    storage = _storage(scale, samples)
    started = time.perf_counter()
    system = build_scao_system(config, execution=ScaoExecutionOptions(atmosphere_band_storage=storage))
    built = time.perf_counter()
    if system.atmosphere.config.screen_size != 2 * config.pupil_pixels:
        raise RuntimeError("unexpected layered screen size; the paired draw assumes 2 * pupil_pixels")
    burn_in = BURN_IN[scale]
    accumulator = StreamingLongExposure(
        system.science_propagator,
        LongExposureConfig(wavelengths_m=(WAVELENGTH_M,), burn_in_frames=burn_in),
        telescope_diameter_m=config.telescope_diameter_m,
    )
    history = run_closed_loop(config, system=system, realization_index=realization, observers=(accumulator,))
    finished = time.perf_counter()
    metrics = accumulator.result().images[0].metrics
    return {
        "label": label,
        "samples_per_lenslet": samples,
        "wfs_pad_factor": wfs_pad,
        "wfs_window_px": 12 * wfs_pad - 1,
        "science_psf_pad_factor": science_pad,
        "realization": realization,
        "config_hash": config.config_hash,
        "paired_reference_screen_size": reference,
        "screen_size": int(system.atmosphere.config.screen_size),
        "atmosphere_band_storage": storage,
        "peak_strehl": float(metrics.peak_strehl),
        "ee50_radius_rad": float(metrics.ee50_radius_rad),
        "residual_rms_nm": float(np.mean(history.pre_update_residual_opd_rms_m[burn_in:]) * 1e9),
        "open_loop_rms_nm": float(np.mean(history.open_loop_opd_rms_m[burn_in:]) * 1e9),
        "first_frame_open_loop_rms_nm": float(history.open_loop_opd_rms_m[0] * 1e9),
        "usable_fraction": float(np.mean(history.reconstruction_usable)),
        "max_saturation": float(np.max(history.saturation_fraction)),
        "rejected_solves": int(system.reconstructor.statistics["rejected"]),
        "build_s": built - started,
        "loop_s": finished - built,
        "ru_maxrss": int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss),
    }


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

    Bytecode and hidden files or folders are left out: Finder metadata
    (``.DS_Store``, ``._*``) and the like can appear without any code change
    and must not change the identity (review CR-07).  None when the files
    cannot bind the code Python imports from the package (OBS-15, review
    RV-05): it is not a directory with an ``__init__.py`` (a zip import, a
    missing directory), or it holds a symlinked directory (not followed),
    sourceless bytecode outside ``__pycache__`` (imported, never digested) or
    a source whose cache Python would run unchecked.
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


def _code_identity(package: Path | None = None) -> dict[str, object]:
    """The code a run executes: the imported package, this driver, and Git where it describes them.

    ``package_sha256`` digests the imported ``shwfs_ao`` package itself, so two
    processes that import different package files never share a known
    identity, whatever Git says (review CR-01 of finding AR-014; bytecode
    caches are not digested: LIM-11 names the stale-cache case).  Git HEAD
    and the digest of the uncommitted ``src`` changes are recorded only when
    the repository that holds the package tracks it, its paths read literally
    (OBS-16); for a copy in an ignored or foreign directory, or without Git,
    they are null, and the code identity counts as unknown.  It is unknown
    too, with a null package digest, when the package's files cannot bind the
    code imported from it (a zip import, a symlinked directory, unbound
    bytecode; OBS-15).
    """

    if package is None:
        import shwfs_ao

        package = Path(shwfs_ao.__file__).parent
    package = package.resolve()
    source = package.parent
    package_sha256 = _package_sha256(package)
    # Names only: a record must not carry the local checkout path.
    identity: dict[str, object] = {
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
    """The numerical environment a run is produced in (as the detector evidence runner binds it)."""

    import scipy

    return {
        "python": sys.version,
        "numpy": np.__version__,
        "scipy": scipy.__version__,
        "machine": platform.machine(),
    }


def producer() -> dict[str, Any]:
    """The code identity and environment of this process."""

    return {"code": _code_identity(), "environment": producer_environment()}


def _canonical(value: object) -> str:
    return json.dumps(value, sort_keys=True, default=str)


def _digest(payload: object) -> str:
    return hashlib.sha256(_canonical(payload).encode("utf-8")).hexdigest()


def _planned_protocol(scale: str, label: str, samples: int, wfs_pad: int, science_pad: int, realization: int) -> dict:
    """What a run of this setting is, apart from who produced it."""

    return {
        "run_protocol_version": RUN_PROTOCOL_VERSION,
        "scale": scale,
        "tier": TIER[scale],
        "label": label,
        "samples_per_lenslet": samples,
        "wfs_pad_factor": wfs_pad,
        "wfs_window_px": 12 * wfs_pad - 1,
        "science_psf_pad_factor": science_pad,
        "realization": realization,
        "frames": FRAMES[scale],
        "burn_in": BURN_IN[scale],
        "wavelength_m": WAVELENGTH_M,
        "paired_reference_screen_size": _reference_screen_size(scale),
        "atmosphere_band_storage": _storage(scale, samples),
        "config_hash": _config(scale, samples, wfs_pad, science_pad).config_hash,
    }


def run_protocol(
    scale: str, label: str, samples: int, wfs_pad: int, science_pad: int, realization: int, made_by: dict
) -> dict:
    """A run's protocol (its planned setting and its producer ``made_by``) and the protocol's hash."""

    payload = {
        **_planned_protocol(scale, label, samples, wfs_pad, science_pad, realization),
        "code": made_by["code"],
        "environment": made_by["environment"],
    }
    return {"protocol_hash": _digest(payload), "protocol": payload}


def _run_producer(row: dict) -> dict:
    return {"code": row["protocol"]["code"], "environment": row["protocol"]["environment"]}


def _number(value: object) -> bool:
    # A result may be NaN or infinite: a failed run is reported as found.
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _check_run(path: Path, row: object, planned: dict) -> str | None:
    """Why a saved run is not the planned run ``planned`` or is inconsistent in itself, else None."""

    if not isinstance(row, dict) or "protocol" not in row or "protocol_hash" not in row:
        return (
            f"{path} carries no run protocol (a version-1 row, or not a run), so its scale, configuration "
            "and producer cannot be shown; it is neither reused nor relabelled"
        )
    protocol = row["protocol"]
    if not isinstance(protocol, dict) or _digest(protocol) != row["protocol_hash"]:
        return f"{path}: the stored protocol hash is not the digest of its protocol"
    if set(protocol) != set(planned) | {"code", "environment"}:
        return f"{path}: its protocol has other fields than run protocol {RUN_PROTOCOL_VERSION}"
    if not isinstance(protocol["code"], dict) or not isinstance(protocol["environment"], dict):
        return f"{path}: the run's producer is not a code identity and an environment"
    differ = sorted(name for name in planned if _canonical(protocol[name]) != _canonical(planned[name]))
    if differ:
        return f"{path} is not this study's planned run (its protocol differs in {differ})"
    repeated = [name for name in REPEATED_FIELDS if _canonical(row.get(name)) != _canonical(protocol[name])]
    if _canonical(row.get("screen_size")) != _canonical(2 * LENSLETS[protocol["scale"]] * protocol["samples_per_lenslet"]):
        repeated.append("screen_size")
    if repeated:
        return f"{path}: the fields {repeated} disagree with the run's protocol"
    missing = [name for name in RESULT_FIELDS if not _number(row.get(name))]
    if missing:
        return f"{path}: the results {missing} are missing or not numbers"
    return None


def _mean_std(values: list[float]) -> tuple[float, float | None]:
    array = np.asarray(values, dtype=float)
    return float(array.mean()), (float(array.std(ddof=1)) if array.size > 1 else None)


def _summarize(scale: str, runs: dict[str, dict]) -> dict:
    scans = {}
    for scan, settings in _settings(scale).items():
        entries = []
        for label, samples, wfs_pad, science_pad in settings:
            rows = [runs[_run_key(scale, samples, wfs_pad, science_pad, r)] for r in REALIZATIONS[scale]]
            entry = {"setting": label, "runs": len(rows)}
            for key in ("peak_strehl", "ee50_radius_rad", "residual_rms_nm", "open_loop_rms_nm"):
                entry[f"{key}_mean"], entry[f"{key}_std"] = _mean_std([row[key] for row in rows])
            entries.append((entry, rows))
        convergence = {}
        (finest, finest_rows), (second, second_rows) = entries[-1], entries[-2]
        for key in ("peak_strehl", "ee50_radius_rad"):
            change = abs(finest[f"{key}_mean"] - second[f"{key}_mean"]) / abs(finest[f"{key}_mean"])
            paired = [a[key] / b[key] - 1.0 for a, b in zip(second_rows, finest_rows)]
            mean, std = _mean_std(paired)
            convergence[key] = {
                "relative_change_finest_two": change,
                "paired_relative_difference_mean": mean,
                "paired_relative_difference_se": None if std is None else std / np.sqrt(len(paired)),
                "within_declared_tolerance": change <= TOLERANCE,
            }
        scans[scan] = {"entries": [entry for entry, _ in entries], "convergence": convergence}
    return scans


def _run_key(scale: str, samples: int, wfs_pad: int, science_pad: int, realization: int) -> str:
    # The scale is part of the key: the 12 m and 42 m studies share settings.
    return f"{scale}_s{samples}_wfs{wfs_pad}_sci{science_pad}_r{realization}"


def _legacy_run_key(samples: int, wfs_pad: int, science_pad: int, realization: int) -> str:
    """The version-1 run file name, which names no scale."""

    return f"s{samples}_wfs{wfs_pad}_sci{science_pad}_r{realization}"


def _plan(scale: str) -> dict[str, tuple[str, int, int, int, int]]:
    """Run key -> (label, samples per lenslet, wfs pad, science pad, realization); each run once."""

    plan: dict[str, tuple[str, int, int, int, int]] = {}
    for settings in _settings(scale).values():
        for label, samples, wfs_pad, science_pad in settings:
            for realization in REALIZATIONS[scale]:
                plan.setdefault(
                    _run_key(scale, samples, wfs_pad, science_pad, realization),
                    (label, samples, wfs_pad, science_pad, realization),
                )
    return plan


def _write_json(path: Path, value: dict) -> None:
    """Write a whole file or none: an interrupted write leaves no truncated record."""

    partial = path.with_name(path.name + ".partial")
    partial.write_text(json.dumps(value, indent=1) + "\n")
    os.replace(partial, path)


def _launch_child(scale: str, directory: Path, setting: tuple[str, int, int, int, int], path: Path) -> None:
    """Make one planned run in its own process, which writes its row to ``path``."""

    label, samples, wfs_pad, science_pad, realization = setting
    subprocess.run(
        [sys.executable, __file__, "--scale", scale, "--output-dir", str(directory),
         "--child", label, str(samples), str(wfs_pad), str(science_pad), str(realization), str(path)],
        check=True,
    )


def _record(scale: str, runs: dict[str, dict], summarized_by: dict) -> dict:
    return {
        "schema": SCHEMA,
        "scale": scale,
        "tier": TIER[scale],
        "declared_tolerance": TOLERANCE,
        "frames": FRAMES[scale],
        "burn_in": BURN_IN[scale],
        "realizations": list(REALIZATIONS[scale]),
        "wavelength_m": WAVELENGTH_M,
        "paired_reference_screen_size": _reference_screen_size(scale),
        # The producer of every run, read from the runs' own protocols, and
        # the process that wrote this summary: they need not be the same.
        "run_producer": _run_producer(next(iter(runs.values()))),
        "summarized_by": summarized_by,
        "runs": runs,
        "scans": _summarize(scale, runs),
    }


def _read_json(path: Path) -> tuple[Any, str | None]:
    try:
        return json.loads(path.read_text()), None
    except (OSError, UnicodeDecodeError, ValueError) as exc:
        return None, f"{path} is not readable JSON ({exc})"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--scale", choices=sorted(LENSLETS), required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--child", nargs=6, metavar=("LABEL", "S", "WFS_PAD", "SCI_PAD", "R", "OUT"), help=argparse.SUPPRESS)
    arguments = parser.parse_args(argv)
    if arguments.child:
        label, samples, wfs_pad, science_pad, realization, out = arguments.child
        setting = (int(samples), int(wfs_pad), int(science_pad), int(realization))
        # The producer is taken before the run: the code this process imported.
        made_by = producer()
        row = _run_child(arguments.scale, label, *setting)
        row.update(run_protocol(arguments.scale, label, *setting, made_by))
        _write_json(Path(out), row)
        return 0
    scale, directory = arguments.scale, arguments.output_dir
    runs_directory = directory / "runs"
    summary_path = directory / f"paired_convergence_{scale}.json"
    current = producer()
    plan = _plan(scale)
    planned = {key: _planned_protocol(scale, *setting) for key, setting in plan.items()}
    # Everything saved is checked before anything runs or is written.
    unchanged = "Nothing ran and no file was changed; choose a fresh --output-dir."
    legacy = sorted(
        {f"{_legacy_run_key(*setting[1:])}.json" for setting in plan.values()}
        & {path.name for path in runs_directory.glob("*.json")}
    )
    if legacy:
        raise StudyRecordError(
            f"{runs_directory} holds version-1 run files {legacy}, which name no scale and carry no "
            f"run protocol; they are neither reused nor relabelled.  {unchanged}"
        )
    saved: dict[str, dict] = {}
    for key in plan:
        path = runs_directory / f"{key}.json"
        if path.exists():
            row, problem = _read_json(path)
            problem = problem or _check_run(path, row, planned[key])
            if problem:
                raise StudyRecordError(f"{problem}.  {unchanged}")
            saved[key] = row
    pending = [key for key in plan if key not in saved]
    producers = {_canonical(_run_producer(row)) for row in saved.values()}
    if len(producers) > 1:
        raise StudyRecordError(
            f"{runs_directory}: the saved runs have {len(producers)} different producers (code identity "
            f"or environment); one study has one producer.  {unchanged}"
        )
    if saved and pending:
        if current["code"].get("git_head") is None:
            raise StudyRecordError(
                f"{runs_directory}: the code identity of this invocation is unknown (no git HEAD), so runs "
                f"added now could not be shown to share the saved runs' code.  {unchanged}"
            )
        if producers != {_canonical(current)}:
            raise StudyRecordError(
                f"{runs_directory}: the saved runs were produced by another code identity or environment "
                f"than this invocation's; adding runs would mix producers.  {unchanged}"
            )
    if summary_path.exists():
        if pending:
            raise StudyRecordError(
                f"{summary_path} exists while {len(pending)} planned runs are missing; a summary is never "
                f"rewritten.  {unchanged}"
            )
        existing, problem = _read_json(summary_path)
        expected = json.loads(_canonical(_record(scale, {key: saved[key] for key in plan}, current)))
        # The summary may have been written by another process; all else must agree.
        if not problem and not (
            isinstance(existing, dict)
            and "summarized_by" in existing
            and _canonical({**existing, "summarized_by": None}) == _canonical({**expected, "summarized_by": None})
        ):
            problem = f"{summary_path} does not match its saved runs, or is another schema"
        if problem:
            raise StudyRecordError(f"{problem}; a summary is never rewritten.  {unchanged}")
        print(
            f"{summary_path}: all {len(plan)} planned runs and their summary are recorded; nothing ran "
            "and no file was changed.",
            flush=True,
        )
        return 0
    runs_directory.mkdir(parents=True, exist_ok=True)
    for key in pending:
        path = runs_directory / f"{key}.json"
        print(f"{time.strftime('%H:%M:%S')} run {key}", flush=True)
        _launch_child(scale, directory, plan[key], path)
        row, problem = _read_json(path)
        problem = problem or _check_run(path, row, planned[key])
        if not problem and _canonical(_run_producer(row)) != _canonical(current):
            problem = f"{path} was produced by another code identity or environment than this invocation"
        if problem:
            raise StudyRecordError(f"{problem}; the study stops, and the run file is kept as written.")
        saved[key] = row
    runs = {key: saved[key] for key in plan}
    for key, row in runs.items():
        print(
            f"  {key}: Strehl {row['peak_strehl']:.4f}  EE50 {row['ee50_radius_rad']:.4e} rad  "
            f"residual {row['residual_rms_nm']:.1f} nm  open loop {row['open_loop_rms_nm']:.1f} nm  "
            f"wall {row['build_s'] + row['loop_s']:.0f} s  peak {row['ru_maxrss'] / 2**30:.2f} GiB",
            flush=True,
        )
    record = _record(scale, runs, current)
    _write_json(summary_path, record)
    print(json.dumps({scan: data["convergence"] for scan, data in record["scans"].items()}, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
