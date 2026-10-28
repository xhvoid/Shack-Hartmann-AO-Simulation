"""Fixed-physics convergence study of the detector-level profiles (ticket T2, roadmap AR-007).

Scans one numerical axis at a time around a packaged detector-level profile,
holding every physical input of the profile fixed, with two arms per setting
(the noiseless operating-expectation twin, the primary convergence arm, and
the noise-on arm), one fresh child process per run, two native threads,
immutable resumable run records and a summary that is written once.

Axes (``--axes`` selects a subset; every scan needs at least two settings)::

  pupil     samples per lenslet with paired turbulence input: the periodic
            band is drawn on the finest screen (``band_draw_reference_screen_size``),
            the screens use the ``pupil_diameter`` period rule, so equal signed
            FFT indices are equal physical frequencies; reading ``common`` keeps
            the coarsest screen's band on every setting (the primary scan),
            reading ``growing`` lets each setting carry its own band (a mixture
            of numerical refinement and added turbulence bandwidth).  The
            retained lenslets and illuminated areas change with the raster
            and are recorded.
  detector  detector-plane Gauss--Legendre oversampling per pixel (fixed
            window, pixel scale, diffusion, guard, maps and photon physics).
  spectrum  Gauss--Legendre nodes on the profile's 600-900 nm band (the
            detected budget is recorded, never renormalized; no power law).
  exposure  WFS exposure quadrature: the centred midpoint family n = 1, 2, 4,
            8 (same duration and frame rate, one camera read), with the
            legacy left-point rule at n = 2 as a separately labelled
            comparison that is never fitted with the midpoint family.
  science   science PSF pad (angular sampling); production metrics beside the
            validation-only Fourier encircled-energy reference.

Scales: ``ci`` (the 5 m smoke geometry with the 12 m @3 detector physics, 36
frames, burn-in 12, one realization, both arms: an integration self-check,
not a science ensemble), ``medium`` (``det_emccd_12m_medium_derived@3``) and
``full`` (``det_ccd_42m_r3band_derived@1``, twin arm, k and n checks).  The
medium and full scales are governed: they refuse without ``--enabled-by-user``
(the date and wording of the user's go-ahead) at argument parsing and again
before any build; ``--plan`` prints the plan, the protocol hashes and an
analytic cost estimate for any scale without building anything.

Run identity and resume.  Every run file ``runs/<key>.json`` carries its
protocol (the planned setting, scale, frames, burn-in, arms, configuration
hash, atmosphere options, exposure override, execution options, refinement
parameter) and its producer (the imported package digest, this driver's
digest, the digests of the result-affecting helper modules, Git where it
tracks the package, and the numerical environment), with the protocol's
SHA-256.  Before any build or child launch every saved run of the plan is
validated: readable JSON, the stored hash is its protocol's digest, the
planned fields equal this invocation's, the fields the row repeats equal its
protocol's, a completed row's results are numbers with the declared shapes,
axes and units, a refused row names its reason, every arm of a setting
shares the open-loop series digest, and all saved runs share one producer.
Runs are added only under that producer with a known code identity.  Files
in ``runs/`` that are not planned runs (another study's, S3's, T1's) are
refused as ambiguous, as are leftovers of an interrupted publication.  The
summary is written once and never rewritten; a complete compatible rerun
changes no byte and no mtime.  Run files are published atomically (complete
bytes to a temporary file, hard-linked into place, which fails if the
destination exists) and are never overwritten.

    PYTHONPATH=<tree>/src python scripts/detector_level_convergence_study.py \\
        --scale ci --output-dir outputs/t2_convergence/<run>/ci

Tolerances quoted in the summary are the convergence contract's future
declared science criteria; a ci-scale pass is machinery evidence, not
convergence.
"""

from __future__ import annotations

import _imp
import argparse
from dataclasses import dataclass, replace
import hashlib
import importlib.util
import json
import math
import os
from pathlib import Path
import platform
import secrets
import subprocess
import sys
import time
from typing import Any

import numpy as np


SCHEMA = "shwfs_ao.detector_level_convergence_study.v1"
RUN_PROTOCOL_VERSION = 1
AXES = ("pupil", "detector", "spectrum", "exposure", "science")
ARMS = ("operating_expectation", "noise_on")
PUPIL_READINGS = ("common", "growing")
WAVELENGTH_M = 2.2e-6
# The anchor of the analytic cost estimate: the ci geometry with the 12 m @3
# physics, summary telemetry (technical reference 9.2, MEASURED_CURRENT).
COST_ANCHOR = {"build_s": 1.30, "frame_s": 0.033, "label": "ci geometry, 12 m @3 physics, k = 4, 3 nodes, pad 2 (technical reference 9.2)"}
# Convergence-contract tolerances: future declared science criteria.
CONTRACT_TOLERANCES = {
    "residual_rms_nm": {"medium": 1.0, "full_ensemble": 0.3, "full_single": 0.9},
    "peak_strehl": {"medium": 0.002, "full_ensemble": 0.0006, "full_single": 0.002},
    "ee50_relative": 0.02,
    "status": "future declared science criteria of docs/research CONVERGENCE_CONTRACT.md section 6; not validation earned by a ci-scale self-check",
}

SCALES: dict[str, dict[str, Any]] = {
    "ci": {
        "description": "5 m smoke geometry (10 lenslets of 0.5 m pitch, 12 samples per lenslet) with the 12 m @3 detector physics",
        "frames": 36, "burn_in": 12, "realizations": (0,), "root_seed": 1, "governed": False,
        "telemetry_level": "summary", "band_storage": "materialized", "arms": ARMS, "paired_delta_v": True,
        "pupil_samples": (12, 16), "oversampling": (4, 8), "spectral_nodes": (3, 5),
        "midpoint_subsamples": (1, 2), "legacy_left_subsamples": (2,), "science_pads": (2, 3),
    },
    "medium": {
        "description": "det_emccd_12m_medium_derived@3",
        "frames": 200, "burn_in": 50, "realizations": (0, 1, 2), "root_seed": 1, "governed": True,
        "telemetry_level": "summary", "band_storage": "materialized", "arms": ARMS, "paired_delta_v": True,
        "pupil_samples": (12, 16, 20), "oversampling": (2, 4, 8), "spectral_nodes": (3, 5, 7),
        "midpoint_subsamples": (1, 2, 4, 8), "legacy_left_subsamples": (2,), "science_pads": (2, 3, 4),
    },
    "full": {
        "description": "det_ccd_42m_r3band_derived@1, twin arm only: k and n checks",
        "frames": 200, "burn_in": 50, "realizations": (0,), "root_seed": 1, "governed": True,
        "telemetry_level": "summary", "band_storage": "regenerate", "arms": ("operating_expectation",), "paired_delta_v": False,
        "pupil_samples": (12,), "oversampling": (2, 4), "spectral_nodes": (3,),
        "midpoint_subsamples": (1, 2), "legacy_left_subsamples": (2,), "science_pads": (2,),
    },
}
# The refinement parameter of each axis (declared; section 5 of the design note).
REFINEMENT = {
    "pupil": ("1 / samples per lenslet", True, None),
    "detector": ("1 / oversampling", True, None),
    "spectrum": ("1 / nodes (declared: no power law; Gauss-Legendre converges geometrically)", False, None),
    "exposure": ("1 / midpoint sub-samples (tau / n at fixed tau)", True, 2.0),
    "science": ("1 / science pad", True, None),
}
REPEATED_FIELDS = ("key", "scale", "axis", "setting", "realization", "root_seed", "config_hash", "n_steps", "burn_in_frames")
ARM_RESULT_FIELDS = ("post_update_rms_m", "post_update_mean_square_m2", "pre_update_rms_m", "open_loop_rms_m", "reconstruction_usable_fraction")
# The identity-bearing inputs a completed row's result must repeat from its protocol
# (the profile hash cannot carry them: the pairing options are not part of SystemConfig).
PAIRING_OPTION_FIELDS = ("band_draw_reference_screen_size", "band_limit_screen_size", "screen_period_rule")
_TEMP_MARK = ".tmp-"


class StudyRecordError(SystemExit):
    """Saved study files this invocation must not reuse, replace or mix."""


class EnablementMissing(SystemExit):
    """A governed scale was started without the user's enablement note."""


# -- plan -----------------------------------------------------------------------


@dataclass(frozen=True)
class PlannedRun:
    key: str
    axis: str
    setting: str
    realization: int
    parameters: dict[str, Any]
    config: Any
    atmosphere_options: Any
    exposure: Any
    refinement_parameter: float | None


def base_configuration(scale: str) -> Any:
    """The scale's base configuration: a packaged profile, or the ci derivation (no system is built)."""

    from shwfs_ao.io.configs import load_system_profile

    if scale == "ci":
        from shwfs_ao.experiments.detector_level import derive_physical_config

        smoke = load_system_profile("eso_scao_smoke_5m_software", 2)
        physics = load_system_profile("det_emccd_12m_medium_derived", 3)
        config = derive_physical_config(smoke, physics, label="t2_ci_det_emccd_12m_medium_derived")
        return replace(config, science_wavelengths_m=(WAVELENGTH_M,))
    if scale == "medium":
        return load_system_profile("det_emccd_12m_medium_derived", 3)
    if scale == "full":
        return load_system_profile("det_ccd_42m_r3band_derived", 1)
    raise ValueError(f"unknown scale {scale!r}")


def _execution(scale: str) -> Any:
    from shwfs_ao.experiments.scao import ScaoExecutionOptions

    spec = SCALES[scale]
    return ScaoExecutionOptions(telemetry_level=spec["telemetry_level"], atmosphere_band_storage=spec["band_storage"])


def _baseline_parameters(base: Any) -> dict[str, Any]:
    physics = base.detector_physics
    return {
        "samples_per_lenslet": int(base.pupil_pixels) // int(base.lenslets_across),
        "oversampling": int(physics.sampling.oversampling),
        "spectral_nodes": int(physics.bandpass.n_samples),
        "exposure_rule": "left_point",
        "exposure_subsamples": int(physics.exposure_subsamples),
        "science_pad": int(base.science.psf_pad_factor),
        "reading": None,
    }


def plan(scale: str, axes: tuple[str, ...] = AXES) -> dict[str, PlannedRun]:
    """Run key -> planned run, each once; only ``SystemConfig`` objects are built here."""

    from shwfs_ao.experiments.convergence_study import scan_configuration
    from shwfs_ao.experiments.scao import ExposureOverride, LayeredAtmosphereOptions

    if scale not in SCALES:
        raise ValueError(f"unknown scale {scale!r}")
    unknown = [axis for axis in axes if axis not in AXES]
    if unknown or len(set(axes)) != len(axes):
        raise ValueError(f"axes must be distinct names from {AXES}; got {axes}")
    spec = SCALES[scale]
    base = base_configuration(scale)
    baseline = _baseline_parameters(base)
    if base.pupil_pixels % base.lenslets_across:
        raise ValueError("the base profile's pupil is not a whole number of samples per lenslet.")
    for name, family in (("samples_per_lenslet", spec["pupil_samples"]), ("oversampling", spec["oversampling"]), ("spectral_nodes", spec["spectral_nodes"]), ("science_pad", spec["science_pads"])):
        if baseline[name] not in family:
            raise ValueError(f"the profile's {name} {baseline[name]} is not in the planned family {family}.")
    if baseline["exposure_subsamples"] != 1:
        raise ValueError("the planned exposure families start from the profile's single left-point sample.")
    frames, realizations = int(spec["frames"]), tuple(spec["realizations"])
    lenslets = int(base.lenslets_across)
    plan_runs: dict[str, PlannedRun] = {}

    def add(axis: str, setting: str, parameters: dict[str, Any], config: Any, options: Any, exposure: Any, h: float | None) -> None:
        for realization in realizations:
            key = f"{scale}_{axis}_{setting}_r{realization}"
            if key in plan_runs:
                raise ValueError(f"duplicate run key {key}")
            plan_runs[key] = PlannedRun(key, axis, setting, int(realization), dict(parameters), config, options, exposure, h)

    non_pupil = [axis for axis in axes if axis != "pupil"]
    if non_pupil:
        add("baseline", "plain", baseline, scan_configuration(base, n_steps=frames), None, None, None)
    if "pupil" in axes and len(spec["pupil_samples"]) >= 2:
        finest = lenslets * max(spec["pupil_samples"])
        coarsest = lenslets * min(spec["pupil_samples"])
        reference = 2 * (finest - 1)
        common_band = 2 * (coarsest - 1)
        for reading in PUPIL_READINGS:
            for samples in spec["pupil_samples"]:
                options = LayeredAtmosphereOptions(
                    band_draw_reference_screen_size=reference,
                    band_limit_screen_size=common_band if reading == "common" else None,
                    screen_period_rule="pupil_diameter",
                )
                parameters = {**baseline, "samples_per_lenslet": int(samples), "reading": reading}
                add("pupil", f"{reading}_s{samples}", parameters, scan_configuration(base, samples_per_lenslet=int(samples), n_steps=frames), options, None, 1.0 / samples)
    if "detector" in axes:
        for k in spec["oversampling"]:
            if k == baseline["oversampling"]:
                continue
            add("detector", f"k{k}", {**baseline, "oversampling": int(k)}, scan_configuration(base, oversampling=int(k), n_steps=frames), None, None, 1.0 / k)
    if "spectrum" in axes:
        for nodes in spec["spectral_nodes"]:
            if nodes == baseline["spectral_nodes"]:
                continue
            add("spectrum", f"nodes{nodes}", {**baseline, "spectral_nodes": int(nodes)}, scan_configuration(base, spectral_nodes=int(nodes), n_steps=frames), None, None, 1.0 / nodes)
    if "exposure" in axes:
        for count in spec["midpoint_subsamples"]:
            parameters = {**baseline, "exposure_rule": "midpoint", "exposure_subsamples": int(count)}
            add("exposure", f"mid_n{count}", parameters, scan_configuration(base, n_steps=frames), None, ExposureOverride(subsamples=int(count), sample_rule="midpoint"), 1.0 / count)
        for count in spec["legacy_left_subsamples"]:
            parameters = {**baseline, "exposure_rule": "left_point", "exposure_subsamples": int(count)}
            add("exposure", f"left_n{count}", parameters, scan_configuration(base, n_steps=frames), None, ExposureOverride(subsamples=int(count), sample_rule="left_point"), None)
    if "science" in axes:
        for pad in spec["science_pads"]:
            if pad == baseline["science_pad"]:
                continue
            add("science", f"pad{pad}", {**baseline, "science_pad": int(pad)}, scan_configuration(base, science_pad=int(pad), n_steps=frames), None, None, 1.0 / pad)
    return plan_runs


def planned_protocol(scale: str, run: PlannedRun) -> dict[str, Any]:
    """What a run is, apart from who produced it."""

    from shwfs_ao.experiments.convergence_study import scan_configuration

    spec = SCALES[scale]
    config = scan_configuration(run.config, root_seed=int(spec["root_seed"]))
    return {
        "run_protocol_version": RUN_PROTOCOL_VERSION,
        "schema": SCHEMA,
        "scale": scale,
        "key": run.key,
        "axis": run.axis,
        "setting": run.setting,
        "realization": run.realization,
        "root_seed": int(spec["root_seed"]),
        "n_steps": int(spec["frames"]),
        "burn_in_frames": int(spec["burn_in"]),
        "arms": list(spec["arms"]),
        "paired_delta_v": bool(spec["paired_delta_v"]),
        "parameters": run.parameters,
        "refinement_parameter": run.refinement_parameter,
        "config_hash": config.config_hash,
        "profile": f"{run.config.profile.profile_name}@{run.config.profile.profile_version}",
        "science_wavelengths_m": [float(v) for v in run.config.science_wavelengths_m],
        "atmosphere_options": None if run.atmosphere_options is None else run.atmosphere_options.to_record(),
        "exposure_override": None if run.exposure is None else {"subsamples": run.exposure.subsamples, "sample_rule": run.exposure.sample_rule},
        "execution": {"telemetry_level": spec["telemetry_level"], "atmosphere_band_storage": spec["band_storage"]},
    }


# -- producer identity (third copy of the hardened helpers; semantics unchanged) --

HELPER_MODULES = (
    "shwfs_ao.experiments.convergence_study",
    "shwfs_ao.validation.encircled_energy",
    "shwfs_ao.validation.richardson",
    "shwfs_ao.validation.atmosphere_pairing",
)


def _unchecked_bytecode(source: Path) -> bool:
    """Whether Python would run cached bytecode of ``source`` without checking it against the source (PEP 552)."""

    try:
        with Path(importlib.util.cache_from_source(str(source))).open("rb") as handle:
            header = handle.read(8)
    except (OSError, NotImplementedError):
        return False
    flags = int.from_bytes(header[4:8], "little") if len(header) == 8 else 0
    never = getattr(_imp, "check_hash_based_pycs", "default") == "never"
    return bool(flags & 0b01) and (not flags & 0b10 or never)


def _package_sha256(package: Path) -> str | None:
    """SHA-256 over the files of a package; None when the files cannot bind the imported code."""

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


def _code_identity(package: Path | None = None) -> dict[str, Any]:
    """The code a run executes: the imported package, this driver, the helpers, and Git where it tracks the package."""

    if package is None:
        import shwfs_ao

        package = Path(shwfs_ao.__file__).parent
    package = package.resolve()
    source = package.parent
    package_sha256 = _package_sha256(package)
    helpers: dict[str, str | None] = {}
    for name in HELPER_MODULES:
        path = package / Path(*name.split(".")[1:]).with_suffix(".py")
        helpers[name] = hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None
    identity: dict[str, Any] = {
        "package_directory": source.name,
        "package_sha256": package_sha256,
        "script_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "result_affecting_helpers_sha256": helpers,
        "git_head": None,
        "source_changes_sha256": None,
    }
    if package_sha256 is None:
        return identity

    def git(*arguments: str, cwd: Path) -> subprocess.CompletedProcess:
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
    import scipy

    return {"python": sys.version, "numpy": np.__version__, "scipy": scipy.__version__, "machine": platform.machine()}


def producer() -> dict[str, Any]:
    return {"code": _code_identity(), "environment": producer_environment()}


def _canonical(value: object) -> str:
    return json.dumps(value, sort_keys=True, default=str)


def _digest(payload: object) -> str:
    return hashlib.sha256(_canonical(payload).encode("utf-8")).hexdigest()


def run_protocol(scale: str, run: PlannedRun, made_by: dict[str, Any]) -> dict[str, Any]:
    payload = {**planned_protocol(scale, run), "code": made_by["code"], "environment": made_by["environment"]}
    return {"protocol_hash": _digest(payload), "protocol": payload}


def _run_producer(row: dict[str, Any]) -> dict[str, Any]:
    return {"code": row["protocol"]["code"], "environment": row["protocol"]["environment"]}


# -- row validation ------------------------------------------------------------------


def _number(value: object) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _finite_number(value: object) -> bool:
    return _number(value) and math.isfinite(float(value))


def _hex_digest(value: object) -> bool:
    return isinstance(value, str) and len(value) == 64 and all(c in "0123456789abcdef" for c in value)


def check_run(path: Path, row: object, planned: dict[str, Any]) -> str | None:
    """Why a saved run is not the planned run ``planned`` or is inconsistent in itself, else None."""

    if not isinstance(row, dict) or "protocol" not in row or "protocol_hash" not in row:
        return f"{path} carries no run protocol (not a run of this driver, or another record family); it is neither reused nor relabelled"
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
    if repeated:
        return f"{path}: the fields {repeated} disagree with the run's protocol"
    status = row.get("status")
    if status == "refused":
        if not isinstance(row.get("reason"), str) or not row["reason"] or "result" in row:
            return f"{path}: a refused run must name its reason and carry no result"
        return None
    if status != "completed":
        return f"{path}: status {status!r} is neither completed nor refused"
    result = row.get("result")
    if not isinstance(result, dict):
        return f"{path}: a completed run has no result"
    expected_schema = "shwfs_ao.experiments.convergence_study.paired_run.v1"
    if result.get("schema") != expected_schema:
        return f"{path}: result schema {result.get('schema')!r} is not {expected_schema}"
    for name in ("config_hash", "n_steps", "burn_in_frames", "root_seed"):
        if _canonical(result.get(name)) != _canonical(protocol[name]):
            return f"{path}: the result's {name} disagrees with the run's protocol"
    if result.get("realization_index") != protocol["realization"]:
        return f"{path}: the result's realization disagrees with the run's protocol"
    for name in ("atmosphere_options", "exposure_override", "science_wavelengths_m"):
        if _canonical(result.get(name)) != _canonical(protocol[name]):
            return f"{path}: the result's {name} disagrees with the run's protocol"
    execution = result.get("execution")
    if not isinstance(execution, dict) or any(
        _canonical(execution.get(name)) != _canonical(value) for name, value in protocol["execution"].items()
    ):
        return f"{path}: the result's execution options disagree with the run's protocol"
    arms = result.get("arms")
    if not isinstance(arms, dict) or list(arms) != list(protocol["arms"]):
        return f"{path}: the result's arms are not the planned {protocol['arms']} in order"
    digests = set()
    atmosphere_hashes = set()
    for arm, entry in arms.items():
        if not isinstance(entry, dict):
            return f"{path}: arm {arm} is not a record"
        missing = [name for name in ARM_RESULT_FIELDS if not _number(entry.get(name))]
        if missing:
            return f"{path}: arm {arm} results {missing} are missing or not numbers"
        if not _hex_digest(entry.get("open_loop_rms_series_sha256")):
            return f"{path}: arm {arm} has no open-loop series digest"
        digests.add(entry["open_loop_rms_series_sha256"])
        science = entry.get("science")
        if not isinstance(science, list) or len(science) != len(protocol["science_wavelengths_m"]):
            return f"{path}: arm {arm} has {None if not isinstance(science, list) else len(science)} science images for {len(protocol['science_wavelengths_m'])} wavelengths"
        for image in science:
            production = image.get("production") if isinstance(image, dict) else None
            if not isinstance(production, dict) or not all(_number(production.get(name)) for name in ("peak_strehl", "ee50_radius_rad", "ee80_radius_rad")):
                return f"{path}: arm {arm} has incomplete production science metrics"
            reference = image.get("fourier_reference")
            if not isinstance(reference, dict) or reference.get("status") not in ("available", "unavailable"):
                return f"{path}: arm {arm} has no Fourier reference status"
            if reference["status"] == "available" and not all(_number(reference.get(name)) for name in ("ee50_radius_rad", "ee80_radius_rad")):
                return f"{path}: arm {arm} has an available Fourier reference without its radii"
        geometry = entry.get("geometry")
        if not isinstance(geometry, dict) or not isinstance(geometry.get("retained_lenslet_count"), int) or not _hex_digest(geometry.get("retained_lenslet_ids_sha256")):
            return f"{path}: arm {arm} has no retained-lenslet record"
        if not isinstance(entry.get("detector_budget"), dict) or not _number(entry["detector_budget"].get("detected_e_full_subaperture_per_frame")):
            return f"{path}: arm {arm} has no detector budget"
        options = protocol["atmosphere_options"]
        if _canonical(entry.get("system_atmosphere_options")) != _canonical(options):
            return f"{path}: arm {arm} was built with other atmosphere options than the plan"
        atmosphere = entry.get("atmosphere")
        if not isinstance(atmosphere, dict) or not _hex_digest(atmosphere.get("config_hash")):
            return f"{path}: arm {arm} has no atmosphere record"
        if options is None:
            if atmosphere.get("pairing_active") is not False or any(name in atmosphere for name in PAIRING_OPTION_FIELDS):
                return f"{path}: arm {arm} records pairing options the plan did not ask for"
        elif atmosphere.get("pairing_active") is not True or any(
            _canonical(atmosphere.get(name)) != _canonical(options[name]) for name in PAIRING_OPTION_FIELDS
        ):
            return f"{path}: arm {arm} atmosphere metadata does not carry the planned pairing options"
        hashes = {
            atmosphere["config_hash"],
            (entry.get("component_hashes") or {}).get("atmosphere"),
            (entry.get("system_component_hashes") or {}).get("atmosphere"),
        }
        if len(hashes) != 1:
            return f"{path}: arm {arm} atmosphere hashes are missing or disagree between its metadata, loop and system records"
        atmosphere_hashes.add(atmosphere["config_hash"])
        exposure = entry.get("wfs_exposure")
        rule = protocol["parameters"]["exposure_rule"]
        count = protocol["parameters"]["exposure_subsamples"]
        if rule == "left_point" and count == 1:
            if exposure is not None:
                return f"{path}: arm {arm} records an exposure quadrature the plan did not ask for"
        else:
            expected_scheme = "midpoint_uniform_held_dm.v1" if rule == "midpoint" else "left_point_uniform_held_dm.v1"
            if not isinstance(exposure, dict) or exposure.get("scheme") != expected_scheme or exposure.get("subsamples") != count:
                return f"{path}: arm {arm} exposure metadata {exposure!r} is not the planned {expected_scheme} with {count} sub-samples"
    if len(digests) != 1:
        return f"{path}: the arms saw different open-loop series (digests {sorted(digests)})"
    if len(atmosphere_hashes) != 1:
        return f"{path}: the arms were built with different atmospheres (hashes {sorted(atmosphere_hashes)})"
    if result.get("open_loop_rms_series_shared_by_arms") is not True:
        return f"{path}: the result does not declare the arms' shared open-loop series"
    paired = result.get("paired_delta_v")
    if not isinstance(paired, dict) or paired.get("status") not in ("available", "unavailable"):
        return f"{path}: no paired DeltaV status"
    if protocol["paired_delta_v"] and len(protocol["arms"]) == 2:
        if paired["status"] != "available":
            return f"{path}: the plan asked for the paired DeltaV and the result marks it unavailable"
        series = paired.get("delta_v_m2")
        length = protocol["n_steps"] - protocol["burn_in_frames"]
        if not isinstance(series, list) or len(series) != length or not all(_finite_number(v) for v in series):
            return f"{path}: delta_v_m2 is not a series of {length} finite numbers"
        if paired.get("units") != "m2" or paired.get("series_axes") != ["analysed_frame"] or paired.get("series_length") != length:
            return f"{path}: delta_v_m2 is not declared with units m2 over the analysed_frame axis of length {length}"
        if not _number(paired.get("mean_m2")) or not math.isclose(float(paired["mean_m2"]), float(np.mean(series)), rel_tol=1.0e-12, abs_tol=0.0):
            return f"{path}: the DeltaV mean is not the mean of its series"
    elif paired["status"] != "unavailable":
        return f"{path}: the plan did not ask for the paired DeltaV and the result reports one"
    timing = result.get("timing")
    if not isinstance(timing, dict) or not _number(timing.get("wall_s")):
        return f"{path}: no timing"
    if not isinstance(row.get("ru_maxrss_bytes"), int):
        return f"{path}: no child peak RSS"
    return None


# -- files -----------------------------------------------------------------------------


def _publish(path: Path, value: dict[str, Any]) -> None:
    """Write the complete bytes to a temporary file and hard-link them into place; never over an existing file."""

    path = Path(path)
    payload = (json.dumps(value, indent=1, default=float) + "\n").encode("utf-8")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f"{path.name}{_TEMP_MARK}{os.getpid()}-{secrets.token_hex(4)}")
    with open(temporary, "xb") as handle:
        handle.write(payload)
        handle.flush()
        os.fsync(handle.fileno())
    try:
        os.link(temporary, path)
    except FileExistsError:
        temporary.unlink()
        raise StudyRecordError(f"{path} exists; nothing is overwritten.") from None
    temporary.unlink()
    directory = os.open(path.parent, os.O_RDONLY)
    try:
        os.fsync(directory)
    finally:
        os.close(directory)
    if path.read_bytes() != payload:
        raise StudyRecordError(f"{path} does not read back as the bytes written; the file is left as it is.")


def _read_json(path: Path) -> tuple[Any, str | None]:
    try:
        return json.loads(path.read_text()), None
    except (OSError, UnicodeDecodeError, ValueError) as exc:
        return None, f"{path} is not readable JSON ({exc})"


def _summary_path(directory: Path, scale: str) -> Path:
    return directory / f"convergence_{scale}.json"


# -- analysis ---------------------------------------------------------------------------


def _metric_values(row: dict[str, Any], arm: str) -> dict[str, float | None]:
    entry = row["result"]["arms"][arm]
    science = entry["science"][0]
    reference = science["fourier_reference"]
    paired = row["result"].get("paired_delta_v", {})
    return {
        "post_update_rms_nm": entry["post_update_rms_m"] * 1.0e9,
        "pre_update_rms_nm": entry["pre_update_rms_m"] * 1.0e9,
        "peak_strehl": science["production"]["peak_strehl"],
        "ee50_production_rad": science["production"]["ee50_radius_rad"],
        "ee50_fourier_rad": reference.get("ee50_radius_rad") if reference.get("status") == "available" else None,
        "ee80_production_rad": science["production"]["ee80_radius_rad"],
        "ee80_fourier_rad": reference.get("ee80_radius_rad") if reference.get("status") == "available" else None,
        "paired_delta_v_mean_nm2": None if paired.get("status") != "available" else paired["mean_m2"] * 1.0e18,
        "paired_delta_v_block_se_nm2": None if paired.get("status") != "available" or paired.get("block_standard_error_m2") is None else paired["block_standard_error_m2"] * 1.0e18,
    }


def _setting_statistics(rows: list[dict[str, Any]], arm: str) -> dict[str, Any]:
    """Mean and seed scatter of each metric over the realizations of one setting."""

    per_run = [_metric_values(row, arm) for row in rows]
    out: dict[str, Any] = {"realizations": len(per_run)}
    for name in per_run[0]:
        values = [run[name] for run in per_run if run[name] is not None]
        if not values:
            out[name] = {"mean": None, "seed_sd": None, "seed_se": None, "n": 0}
            continue
        array = np.asarray(values, dtype=float)
        sd = float(np.std(array, ddof=1)) if array.size > 1 else None
        out[name] = {"mean": float(np.mean(array)), "seed_sd": sd, "seed_se": None if sd is None else sd / math.sqrt(array.size), "n": int(array.size)}
    return out


def analyze(scale: str, runs: dict[str, dict[str, Any]], plan_runs: dict[str, PlannedRun]) -> dict[str, Any]:
    """Per axis: the settings table, the change table and the Richardson result per metric and arm."""

    from shwfs_ao.validation.atmosphere_pairing import physical_frequency_dilation
    from shwfs_ao.validation.richardson import change_table, richardson_estimate

    spec = SCALES[scale]
    arms = tuple(spec["arms"])
    baseline_keys = [key for key, run in plan_runs.items() if run.axis == "baseline"]
    completed = {key: row for key, row in runs.items() if row.get("status") == "completed"}
    refused = {key: row["reason"] for key, row in runs.items() if row.get("status") == "refused"}
    analysis: dict[str, Any] = {"axes": {}, "refused_runs": refused, "contract_tolerances": CONTRACT_TOLERANCES}

    def family(axis: str) -> dict[str, list[dict[str, Any]]]:
        """Setting -> completed rows (all realizations), for the axis plus the shared baseline where it applies."""

        settings: dict[str, list[dict[str, Any]]] = {}
        for key, run in plan_runs.items():
            if run.axis != axis or key not in completed:
                continue
            settings.setdefault(run.setting, []).append(completed[key])
        if axis != "pupil" and baseline_keys:
            baseline_rows = [completed[key] for key in baseline_keys if key in completed]
            if baseline_rows:
                settings["baseline_plain"] = baseline_rows
        return settings

    def refinement_of(axis: str, setting: str, rows: list[dict[str, Any]]) -> float | None:
        parameters = rows[0]["protocol"]["parameters"]
        if setting == "baseline_plain":
            return {
                "detector": 1.0 / parameters["oversampling"], "spectrum": 1.0 / parameters["spectral_nodes"],
                "science": 1.0 / parameters["science_pad"], "exposure": None,
            }.get(axis)
        return rows[0]["protocol"]["refinement_parameter"]

    for axis in AXES:
        settings = family(axis)
        if not settings:
            continue
        description, power_law, assumed = REFINEMENT[axis]
        axis_record: dict[str, Any] = {"refinement_parameter": description, "settings": {}, "scans": {}}
        for setting, rows in settings.items():
            axis_record["settings"][setting] = {
                "parameters": rows[0]["protocol"]["parameters"],
                "refinement_parameter": refinement_of(axis, setting, rows),
                "config_hash": rows[0]["protocol"]["config_hash"],
                "atmosphere_options": rows[0]["protocol"]["atmosphere_options"],
                "exposure_override": rows[0]["protocol"]["exposure_override"],
                "open_loop_rms_series_sha256": sorted({row["result"]["arms"][arm]["open_loop_rms_series_sha256"] for row in rows for arm in arms}),
                "retained_lenslets": rows[0]["result"]["arms"][arms[0]]["geometry"]["retained_lenslet_count"],
                "illuminated_area_fraction_mean": rows[0]["result"]["arms"][arms[0]]["geometry"]["illuminated_area_fraction"]["mean"],
                "detected_e_full_subaperture_per_frame": rows[0]["result"]["arms"][arms[0]]["detector_budget"]["detected_e_full_subaperture_per_frame"],
                "spectral_nodes_m": rows[0]["result"]["arms"][arms[0]]["detector_budget"]["spectral_nodes_m"],
                "arms": {arm: _setting_statistics(rows, arm) for arm in arms},
                "wall_s_mean": float(np.mean([row["result"]["timing"]["wall_s"] for row in rows])),
                "ru_maxrss_bytes_max": int(max(row["ru_maxrss_bytes"] for row in rows)),
            }
        # Scans: the centred midpoint family and the legacy comparison are kept apart;
        # the pupil axis has one scan per reading; the other axes one scan each.
        scans: dict[str, list[str]] = {}
        if axis == "pupil":
            for reading in PUPIL_READINGS:
                scans[reading] = [name for name in settings if name.startswith(f"{reading}_")]
        elif axis == "exposure":
            scans["midpoint_centred_family"] = [name for name in settings if name.startswith("mid_")]
            scans["legacy_left_point_comparison"] = (
                [name for name in ("baseline_plain",) if name in settings]
                + sorted(name for name in settings if name.startswith("left_"))
                + [name for name in ("mid_n2",) if name in settings]
            )
        else:
            scans["scan"] = list(settings)
        for scan_name, members in scans.items():
            members = [name for name in members if name in settings]
            if len(members) < 2:
                axis_record["scans"][scan_name] = {"status": "not scanned at this scale (fewer than two settings)", "settings": members}
                continue
            if scan_name == "legacy_left_point_comparison":
                # A comparison of rules at equal duration, never a refinement family:
                # pairwise differences only, no refinement parameter, no order.
                comparison: dict[str, Any] = {
                    "settings": members,
                    "note": "left-point n = 1 (the frame-start snapshot), left-point n = 2 and midpoint n = 2 at the same exposure duration; differences of rules, no Richardson fit",
                    "metrics": {},
                }
                for arm in arms:
                    for metric in ("post_update_rms_nm", "peak_strehl", "ee50_production_rad", "ee50_fourier_rad"):
                        values = {name: axis_record["settings"][name]["arms"][arm][metric]["mean"] for name in members}
                        reference = values.get("baseline_plain")
                        comparison["metrics"][f"{arm}/{metric}"] = {
                            "values": values,
                            "difference_vs_left_point_n1": None if reference is None else {
                                name: None if value is None else value - reference for name, value in values.items() if name != "baseline_plain"
                            },
                            "midpoint_minus_left_point_at_n2": (
                                None if values.get("mid_n2") is None or values.get("left_n2") is None else values["mid_n2"] - values["left_n2"]
                            ),
                        }
                axis_record["scans"][scan_name] = comparison
                continue
            fits_power_law = power_law
            scan_record: dict[str, Any] = {"settings": members, "metrics": {}, "power_law_declared": fits_power_law}
            ordered = sorted(members, key=lambda name: -(refinement_of(axis, name, settings[name]) or 0.0))
            h = [refinement_of(axis, name, settings[name]) for name in ordered]
            for arm in arms:
                for metric in ("post_update_rms_nm", "peak_strehl", "ee50_production_rad", "ee50_fourier_rad", "paired_delta_v_mean_nm2"):
                    stats = [axis_record["settings"][name]["arms"][arm][metric] for name in ordered]
                    values = [item["mean"] for item in stats]
                    if any(value is None for value in values) or any(value is None for value in h):
                        scan_record["metrics"][f"{arm}/{metric}"] = {"status": "not available for every setting"}
                        continue
                    uncertainties = [item["seed_se"] for item in stats]
                    have_uncertainty = all(value is not None for value in uncertainties)
                    table = change_table(h, values, uncertainties=uncertainties if have_uncertainty else None)
                    estimate = richardson_estimate(
                        h, values, uncertainties=uncertainties if have_uncertainty else None,
                        assumed_order=assumed if fits_power_law else None, power_law=fits_power_law,
                    )
                    scan_record["metrics"][f"{arm}/{metric}"] = {"settings_coarse_to_fine": ordered, "change_table": table, "richardson": estimate.to_record()}
            axis_record["scans"][scan_name] = scan_record
        # Pairing checks.
        if axis == "pupil":
            pairing: dict[str, Any] = {}
            for reading in PUPIL_READINGS:
                members = sorted((name for name in settings if name.startswith(f"{reading}_")), key=lambda name: settings[name][0]["protocol"]["parameters"]["samples_per_lenslet"])
                if len(members) < 2:
                    continue
                configs = []
                for name in members:
                    row = settings[name][0]
                    atmosphere = row["result"]["arms"][arms[0]]["atmosphere"]
                    configs.append({"setting": name, **{key: atmosphere.get(key) for key in ("screen_size", "screen_period_m", "band_draw_reference_screen_size", "band_limit_screen_size", "screen_period_rule", "band_power_retained_fraction")}})
                periods = {item["screen_period_m"] for item in configs}
                pairing[reading] = {
                    "settings": configs,
                    "one_physical_period": max(periods) - min(periods) < 1.0e-9 * max(periods),
                    "exact_physical_pairing": max(periods) - min(periods) < 1.0e-9 * max(periods) and len({item["band_draw_reference_screen_size"] for item in configs}) == 1,
                    "common_band": reading == "common",
                    "interpretation": (
                        "common band on one physical period: the same continuous input on every grid; differences are raster, propagation and sensing discretization"
                        if reading == "common" else
                        "growing band: each setting carries the turbulence bandwidth its grid holds; the scan mixes numerical refinement with added physical bandwidth"
                    ),
                }
                dilations = []
                for coarse_name, fine_name in zip(members, members[1:]):
                    coarse_run, fine_run = plan_runs[next(k for k in plan_runs if plan_runs[k].setting == coarse_name)], plan_runs[next(k for k in plan_runs if plan_runs[k].setting == fine_name)]
                    dilations.append({"pair": [coarse_name, fine_name], **_dilation_from_plan(coarse_run, fine_run, physical_frequency_dilation)})
                pairing[reading]["adjacent_dilation"] = dilations
            axis_record["pairing"] = pairing
        else:
            digests = {name: entry["open_loop_rms_series_sha256"] for name, entry in axis_record["settings"].items()}
            axis_record["pairing"] = {
                "open_loop_series_shared_by_all_settings": len({tuple(value) for value in digests.values()}) == 1 and all(len(value) == 1 for value in digests.values()),
                "digests": digests,
                "interpretation": "non-pupil axes share the atmosphere grid, so every setting must see the identical open-loop series",
            }
        analysis["axes"][axis] = axis_record
    analysis["cost"] = {
        "runs_completed": len(completed),
        "total_wall_s": float(sum(row["result"]["timing"]["wall_s"] for row in completed.values())),
        "per_run_wall_s": {key: row["result"]["timing"]["wall_s"] for key, row in completed.items()},
        "per_run_ru_maxrss_bytes": {key: row["ru_maxrss_bytes"] for key, row in runs.items() if "ru_maxrss_bytes" in row},
        "max_ru_maxrss_bytes": max((row["ru_maxrss_bytes"] for row in runs.values() if "ru_maxrss_bytes" in row), default=None),
        "label": "MEASURED_CURRENT (fresh child process per run; ru_maxrss is each child's own peak)",
    }
    return analysis


def _dilation_from_plan(coarse: PlannedRun, fine: PlannedRun, physical_frequency_dilation: Any) -> dict[str, Any]:
    """The analytic dilation report of two planned pupil settings (no system is built)."""

    from shwfs_ao.backends.native.layered_atmosphere import FrozenFlowLayer, LayeredFrozenFlowAtmosphereConfig

    def config_of(run: PlannedRun) -> Any:
        system = run.config
        layers = tuple(FrozenFlowLayer(cn2_fraction=layer.cn2_fraction, wind_m_per_s=tuple(layer.wind_m_per_s), altitude_m=layer.altitude_m) for layer in system.atmosphere.layers)
        options = run.atmosphere_options
        return LayeredFrozenFlowAtmosphereConfig(
            grid_size=int(system.pupil_pixels), delta_m=float(system.telescope_diameter_m) / (int(system.pupil_pixels) - 1),
            pupil_diameter_m=float(system.telescope_diameter_m), r0_m=system.atmosphere.r0_m, layers=layers,
            outer_scale_m=system.atmosphere.outer_scale_m, root_seed=1,
            **({} if options is None else options.factory_keywords()),
        )

    return physical_frequency_dilation(config_of(coarse), config_of(fine)).to_record()


# -- cost estimate (planning only) ----------------------------------------------------


def cost_estimate(scale: str, plan_runs: dict[str, PlannedRun]) -> dict[str, Any]:
    """ANALYTIC_ESTIMATE of the plan from the ci anchor and the design note's factors."""

    spec = SCALES[scale]
    frames = int(spec["frames"])
    base = _baseline_parameters(base_configuration(scale))
    per_run = {}
    total = 0.0
    scale_factor = {"ci": 1.0, "medium": (288.0 / 120.0) ** 2 * 1.3, "full": (1008.0 / 120.0) ** 2 * 1.3}[scale]
    for key, run in plan_runs.items():
        p = run.parameters
        factor = (p["samples_per_lenslet"] / base["samples_per_lenslet"]) ** 2
        factor *= 0.4 + 0.6 * (p["oversampling"] / base["oversampling"]) ** 2
        factor *= 0.5 + 0.5 * p["spectral_nodes"] / base["spectral_nodes"]
        factor *= 1.0 + 0.6 * (p["exposure_subsamples"] - 1) + (0.6 if p["exposure_rule"] == "midpoint" else 0.0)
        factor *= 1.0 + 0.1 * (p["science_pad"] - base["science_pad"])
        arms = len(spec["arms"])
        seconds = arms * (COST_ANCHOR["build_s"] * scale_factor * (p["samples_per_lenslet"] / base["samples_per_lenslet"]) ** 2 + frames * COST_ANCHOR["frame_s"] * scale_factor * factor) + 1.5
        per_run[key] = round(seconds, 1)
        total += seconds
    return {
        "label": "ANALYTIC_ESTIMATE",
        "anchor": COST_ANCHOR,
        "per_run_s": per_run,
        "total_s": round(total, 1),
        "note": "historical extrapolation for medium and full (not measured T2 results); the ci target of two minutes and about 0.2 GiB is an estimate, measured by the self-check",
    }


# -- running --------------------------------------------------------------------------


def _child_environment() -> dict[str, str]:
    from shwfs_ao.runtime.resource_guard import limited_environment

    environment = limited_environment(threads=2)
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    return environment


def _launch_child(scale: str, directory: Path, key: str, path: Path) -> None:
    """Make one planned run in its own process, which publishes its row to ``path``."""

    command = [sys.executable, __file__, "--scale", scale, "--output-dir", str(directory), "--child", key, str(path)]
    completed = subprocess.run(command, env=_child_environment())
    if completed.returncode != 0:
        raise StudyRecordError(f"the child for {key} exited with status {completed.returncode}; the study stops and any row it published is kept.")


def _run_child(scale: str, key: str, directory: Path) -> dict[str, Any]:
    """The child's work: validate the key, run the setting, return the row (without the protocol)."""

    import resource

    from shwfs_ao.calibration.interaction import InteractionMatrixError
    from shwfs_ao.experiments.convergence_study import ConvergenceStudyError, fixed_physics_paired_run
    from shwfs_ao.experiments.scao import ScaoConstructionError

    try:
        from shwfs_ao.backends.native.factory import NativeScaoFactoryError
    except ImportError:  # pragma: no cover
        NativeScaoFactoryError = ValueError  # type: ignore[misc,assignment]

    plan_runs = plan(scale)
    if key not in plan_runs:
        raise StudyRecordError(f"{key} is not a planned run of scale {scale}.")
    run = plan_runs[key]
    spec = SCALES[scale]
    protocol = planned_protocol(scale, run)
    row: dict[str, Any] = {name: protocol[name] for name in REPEATED_FIELDS}
    try:
        result = fixed_physics_paired_run(
            run.config,
            root_seed=int(spec["root_seed"]),
            realization_index=run.realization,
            n_steps=int(spec["frames"]),
            burn_in_frames=int(spec["burn_in"]),
            execution=_execution(scale),
            atmosphere_options=run.atmosphere_options,
            exposure=run.exposure,
            arms=tuple(spec["arms"]),
            paired_delta_v=bool(spec["paired_delta_v"]),
            scratch_directory=directory / "scratch",
        )
    except (ScaoConstructionError, InteractionMatrixError, NativeScaoFactoryError, ConvergenceStudyError) as exc:
        # A configuration the system refuses to build is a recorded, resumable result.
        row.update(status="refused", reason=f"{type(exc).__name__}: {exc}"[:500])
    else:
        row.update(status="completed", result=result)
    peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    row["ru_maxrss_bytes"] = int(peak if sys.platform == "darwin" else peak * 1024)
    row["ru_maxrss_semantics"] = "this child process's own lifetime peak resident set (fresh process per run)"
    return row


def _record(scale: str, plan_runs: dict[str, PlannedRun], runs: dict[str, dict[str, Any]], summarized_by: dict[str, Any], note: str | None) -> dict[str, Any]:
    spec = SCALES[scale]
    return {
        "schema": SCHEMA,
        "scale": scale,
        "description": spec["description"],
        "governed": bool(spec["governed"]),
        "enabled_by_user": note,
        "frames": int(spec["frames"]),
        "burn_in": int(spec["burn_in"]),
        "realizations": list(spec["realizations"]),
        "root_seed": int(spec["root_seed"]),
        "arms": list(spec["arms"]),
        "axes_planned": sorted({run.axis for run in plan_runs.values()}),
        "wavelength_m": WAVELENGTH_M,
        "plan": {key: planned_protocol(scale, run) for key, run in plan_runs.items()},
        "run_producer": _run_producer(next(iter(runs.values()))),
        "summarized_by": summarized_by,
        "runs": runs,
        "analysis": analyze(scale, runs, plan_runs),
        "science_claims": "none: a self-check record at ci scale is machinery evidence; medium and full records need their own enablement and review",
    }


def _refuse_unplanned_files(runs_directory: Path, plan_runs: dict[str, PlannedRun], unchanged: str) -> None:
    if not runs_directory.exists():
        return
    expected = {f"{key}.json" for key in plan_runs}
    strangers = sorted(path.name for path in runs_directory.iterdir() if path.name not in expected)
    if strangers:
        raise StudyRecordError(
            f"{runs_directory} holds files that are not planned runs of this study {strangers[:8]}"
            f"{'...' if len(strangers) > 8 else ''}: another study's or scale's records, a foreign record family (S3, T1) "
            f"or leftovers of an interrupted publication; they are neither reused nor relabelled.  {unchanged}"
        )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0], formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--scale", choices=sorted(SCALES), required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--axes", default=",".join(AXES), help=f"comma-separated subset of {','.join(AXES)}")
    parser.add_argument("--plan", action="store_true", help="print the plan, protocol hashes and cost estimate; build and write nothing")
    parser.add_argument("--enabled-by-user", help="date and wording of the user's go-ahead (required for medium and full)")
    parser.add_argument("--child", nargs=2, metavar=("KEY", "OUT"), help=argparse.SUPPRESS)
    arguments = parser.parse_args(argv)
    scale, directory = arguments.scale, Path(arguments.output_dir)
    axes = tuple(name.strip() for name in arguments.axes.split(",") if name.strip())
    governed = bool(SCALES[scale]["governed"])
    if arguments.child:
        key, out = arguments.child
        if governed and arguments.enabled_by_user is None and not os.environ.get("SHWFS_AO_T2_CHILD_ENABLED"):
            raise EnablementMissing(f"{scale}: a governed child needs the parent's enablement; nothing ran.")
        made_by = producer()
        row = _run_child(scale, key, directory)
        row.update(run_protocol(scale, key_run(scale, key), made_by))
        _publish(Path(out), row)
        return 0
    if governed and arguments.enabled_by_user is None and not arguments.plan:
        raise EnablementMissing(
            f"{scale} is a governed scale: pass --enabled-by-user with the date and wording of the user's go-ahead "
            "(or --plan to see the plan without building anything); nothing ran."
        )
    plan_runs = plan(scale, axes)
    planned = {key: planned_protocol(scale, run) for key, run in plan_runs.items()}
    if arguments.plan:
        print(json.dumps({
            "scale": scale, "description": SCALES[scale]["description"], "governed": governed, "axes": list(axes),
            "runs": {key: {"axis": run.axis, "setting": run.setting, "realization": run.realization, "parameters": run.parameters,
                           "refinement_parameter": run.refinement_parameter, "config_hash": planned[key]["config_hash"],
                           "atmosphere_options": planned[key]["atmosphere_options"], "exposure_override": planned[key]["exposure_override"]}
                     for key, run in plan_runs.items()},
            "planned_protocol_digests": {key: _digest(value) for key, value in planned.items()},
            "cost_estimate": cost_estimate(scale, plan_runs),
            "nothing_built": True,
        }, indent=1))
        return 0
    runs_directory = directory / "runs"
    summary_path = _summary_path(directory, scale)
    current = producer()
    unchanged = "Nothing ran and no file was changed; choose a fresh --output-dir."
    _refuse_unplanned_files(runs_directory, plan_runs, unchanged)
    saved: dict[str, dict[str, Any]] = {}
    for key in plan_runs:
        path = runs_directory / f"{key}.json"
        if path.exists():
            row, problem = _read_json(path)
            problem = problem or check_run(path, row, planned[key])
            if problem:
                raise StudyRecordError(f"{problem}.  {unchanged}")
            saved[key] = row
    pending = [key for key in plan_runs if key not in saved]
    producers = {_canonical(_run_producer(row)) for row in saved.values()}
    if len(producers) > 1:
        raise StudyRecordError(f"{runs_directory}: the saved runs have {len(producers)} different producers; one study has one producer.  {unchanged}")
    if saved and pending:
        if current["code"].get("git_head") is None:
            raise StudyRecordError(f"{runs_directory}: the code identity of this invocation is unknown (no Git HEAD binds the imported package), so runs added now could not be shown to share the saved runs' code.  {unchanged}")
        if producers != {_canonical(current)}:
            raise StudyRecordError(f"{runs_directory}: the saved runs were produced by another code identity or environment than this invocation's; adding runs would mix producers.  {unchanged}")
    if summary_path.exists():
        if pending:
            raise StudyRecordError(f"{summary_path} exists while {len(pending)} planned runs are missing; a summary is never rewritten.  {unchanged}")
        existing, problem = _read_json(summary_path)
        expected = json.loads(_canonical(_record(scale, plan_runs, {key: saved[key] for key in plan_runs}, current, arguments.enabled_by_user)))
        if not problem and not (
            isinstance(existing, dict) and "summarized_by" in existing
            and _canonical({**existing, "summarized_by": None, "enabled_by_user": None}) == _canonical({**expected, "summarized_by": None, "enabled_by_user": None})
        ):
            problem = (
                f"{summary_path} does not match the summary this driver computes from its saved runs (another "
                "schema, an edited file, or an analysis written by another version of this driver)"
            )
        if problem:
            raise StudyRecordError(f"{problem}; a summary is never rewritten.  {unchanged}")
        print(f"{summary_path}: all {len(plan_runs)} planned runs and their summary are recorded; nothing ran and no file was changed.", flush=True)
        return 0
    if pending and governed and arguments.enabled_by_user is None:
        raise EnablementMissing(f"{scale}: a governed run needs --enabled-by-user; nothing ran.")  # pragma: no cover - checked above
    runs_directory.mkdir(parents=True, exist_ok=True)
    (directory / "scratch").mkdir(parents=True, exist_ok=True)
    for key in pending:
        path = runs_directory / f"{key}.json"
        print(f"{time.strftime('%H:%M:%S')} run {key}", flush=True)
        if governed:
            os.environ["SHWFS_AO_T2_CHILD_ENABLED"] = arguments.enabled_by_user or ""
        _launch_child(scale, directory, key, path)
        row, problem = _read_json(path)
        problem = problem or check_run(path, row, planned[key])
        if not problem and _canonical(_run_producer(row)) != _canonical(current):
            problem = f"{path} was produced by another code identity or environment than this invocation"
        if problem:
            raise StudyRecordError(f"{problem}; the study stops, and the run file is kept as written.")
        saved[key] = row
        status = row["status"]
        if status == "completed":
            arms = row["result"]["arms"]
            twin = arms[next(iter(arms))]
            print(f"  {key}: {status}; twin residual {twin['post_update_rms_m'] * 1e9:.1f} nm, Strehl {twin['science'][0]['production']['peak_strehl']:.4f}, "
                  f"wall {row['result']['timing']['wall_s']:.1f} s, peak {row['ru_maxrss_bytes'] / 2**20:.0f} MiB", flush=True)
        else:
            print(f"  {key}: REFUSED {row['reason'][:120]}", flush=True)
    runs = {key: saved[key] for key in plan_runs}
    record = _record(scale, plan_runs, runs, current, arguments.enabled_by_user)
    _publish(summary_path, record)
    print(json.dumps({axis: {scan: {metric: entry.get("richardson", {}).get("status") for metric, entry in data.get("metrics", {}).items()} for scan, data in value["scans"].items()} for axis, value in record["analysis"]["axes"].items()}, indent=1))
    return 0


def key_run(scale: str, key: str) -> PlannedRun:
    plan_runs = plan(scale)
    if key not in plan_runs:
        raise StudyRecordError(f"{key} is not a planned run of scale {scale}.")
    return plan_runs[key]


if __name__ == "__main__":
    raise SystemExit(main())
