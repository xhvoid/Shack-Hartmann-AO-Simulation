"""Export the reviewed 42 m guide-flux and controller-delay records for the website; never run AO.

Only saved evidence is read: NumPy history archives (loaded with pickle
disabled), JSON records and the file listings of two accepted compact evidence
packages.  Nothing from the simulation package is imported, no telescope model
is built and no trajectory is regenerated.  Every consumed file must appear in
its package listing with the same size and SHA-256; the analysis records must
carry the SHA-256 accepted at review; each history must carry the hash its
analysis names.  Any missing, malformed or mismatched input stops the export.

Two separate display bundles are produced, each with its own identity:

``derived/flux42-r2-<16 hex>/``
    the two 1000-frame realization-2 trajectories at 100000 and 1000 detected
    electrons per fully illuminated subaperture per frame (one matched atmosphere);
``derived/delay42-<16 hex>/``
    the nine 500-frame records at configured controller delays of 1, 2 and 3
    frames in realizations 0, 1 and 2 (delay 2: the reused photon-budget
    baselines; delay 3 in realization 2: the accepted second attempt).

A bundle identity is the first 16 hex digits of the SHA-256 of its canonical
file listing.  It identifies the generated display files, not the scientific
source; the source identities are recorded in each bundle's provenance.json.

Usage::

    python tools/export_42m_studies.py --flux-root DIR --delay-root DIR --web-dir site [--write]

The roots are the extracted compact packages (the directories that hold
``COMPACT_PACKAGE.json``).  Without ``--write`` the inputs are verified and both
bundles are built in a temporary directory only; with it the bundles are copied
to ``site/derived/`` and bound in ``site/data/current.json``.  Restamp the page
afterwards with ``tools/site_build.py --write``.  Use two numerical threads.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
from pathlib import Path, PurePosixPath
import shutil
import sys
import tempfile
from typing import Any, Dict, List, Optional, Sequence, Tuple
import zipfile

import numpy as np


EXPORTER_VERSION = 1


class ExportError(RuntimeError):
    """A required input is missing, malformed or differs from its recorded identity."""


# Accepted evidence (reviews of 2026-10-29).  The archive repository is private;
# as in the C1 summary it is identified publicly by branch, commit and hashes.
PRODUCER = {"commit": "642a5b76de97e1fbe46fc49dd5fad232fb725219", "tree": "2538aee871f8a8959a08ed0f4bab6c0a6c9d70c9"}
FLUX_SOURCE = {
    "archive": "private project evidence archive",
    "branch": "study/42m-bright-r2-1000frames-20261029-2b97cb",
    "closing_commit": "35e3f7c6fbbb72cc39326bd8fd6231fd96d00778",
    "compact_archive_sha256": "50021242ac1f8eed0d5a0f01cc09e16ac6f8532e46a8ae83c37c3f24242cf4ec",
    "faint_extension": {"branch": "study/42m-photon-budget-r2-a3-20261029-298377",
                        "closing_commit": "876c5d062957cd56f67a8e6cdc44e6b219d5d4a2"},
    "accepted": "2026-10-29 bright-control review (faint attempt 3 accepted in its own review the same day)",
}
FLUX_ANALYSES = {
    "analysis/pair_bright_faint/pair_results.json": "fca0be941e14c7e744f57824409d6b1848331424436b58112fbc7efe6be7975c",
    "analysis/bright1/ext_results.json": "2db64499f2a666540a84e69716d1671610e3077ccd89f13c82efd04459845b1b",
    "faint_flux1000-r2-attempt3/analysis/ext_results.json": "771f2935e13c717f9180d42bb21cb39f5a2fc6635faa069b98d99783d1d5b7b6",
}
DELAY_SOURCE = {
    "archive": "private project evidence archive",
    "branch": "study/42m-latency-20261029-f4ba53",
    "closing_commit": "30a788048e5b1e7f30760990294d7f9fa5845554",
    "compact_stage_commit": "4a64096494568900147df8ce7582c4b95472d54d",
    "compact_archive_sha256": "ae76a2170935734068a0961073cb8a7d18372061f3b48c1fb65026339a75f4c9",
    "accepted": "2026-10-29 latency review, with wording corrections LAT-R01 to LAT-R04",
}
DELAY_ANALYSES = {"analysis/lat_results.json": "a5b611a6cca62bcd973b58398f1369d55f61baa12104d9502941f4f394e4d603"}

# Acceptance anchors (six or nine decimals as accepted); compared within half a unit of the last digit.
FLUX_ANCHORS = {"early": (187.116593, 206.817766, 19.701172), "late": (186.975858, 264.708271, 77.732413),
                "full": (187.038407, 238.979158, 51.940751), "changes": (-0.140735, 57.890505)}
DELAY_ANCHORS = {
    "mean_pre_update_rms_nm": {1: 181.942132, 2: 188.185068, 3: 208.047971},
    "peak_strehl": {1: 0.764616, 2: 0.750978, 3: 0.719687},
    "fourier_ee50_lambda_over_d": {1: 0.803450, 2: 0.834135, 3: 0.970731},
    "1_minus_2": (-6.242937, -7.271193, -5.214681),
    "3_minus_2": (19.862903, -4.475983, 44.201789),
    "3_minus_2_by_realization": (14.894791, 13.544476, 31.149443),
    "strehl_ratio": 2.294402,
}
EXCURSION_ANCHORS = {
    "pre_nm": {338: 202.761403, 339: 208.842077, 344: 255.093974, 446: 248.795052, 447: 273.001961},
    "valid": {446: 0.993153365, 447: 0.993740219},
    "valid_mean_345_500": 0.991961987, "valid_mean_100_300": 0.999310446, "frames_below_0_995": 137,
}

FRAME_RATE_HZ = 500.0
STARTUP = (0, 100)
VALIDITY_MARK = 0.995
REQUIRED_SERIES = ("time_s", "pre_update_residual_opd_rms_m", "open_loop_opd_rms_m",
                   "valid_measurement_fraction", "reconstruction_usable", "saturation_fraction")
COMMON_SETTINGS = {"controller/gain": 0.3, "controller/leak": 0.0, "controller/frame_rate_hz": 500.0,
                   "reconstructor/alpha": 0.001, "random/root_seed": 1,
                   "detector_physics/source/detected_e_per_full_subap_frame": None}

FLUX_RUNS = {
    "bright": {"dir": "runs/ext-flux100000-r2-n1000.bright1/output", "flux": 100000.0, "run_key": "ext-flux100000-r2-n1000"},
    "faint": {"dir": "faint_flux1000-r2-attempt3", "flux": 1000.0, "run_key": "ext-flux1000-r2-n1000"},
}
FLUX_ORIGINAL_BRIGHT = "original_flux100000-r2"
FLUX_WINDOWS = {"early": (100, 500), "late": (500, 1000), "full": (100, 1000)}
PAIR_WINDOW = {"early": "original_comparable", "late": "additional", "full": "full_extended"}
PAIR_IMAGE = {"early": "window_100_500", "full": "window_100_1000"}

DELAYS = (1, 2, 3)
REALIZATIONS = (0, 1, 2)
DELAY_WINDOW = (100, 500)
ATTEMPT_SELECTION = {
    "lat3-flux100000-r2": {
        "selected_attempt": 2, "selected_dir": "attempt2/runs/lat3-flux100000-r2/output", "amendment": "AM3",
        "excluded_attempt": 1, "excluded_dir": "records/new/lat3-flux100000-r2",
        "excluded_status": "lost to a computing-container restart during the closed loop; no completed history; kept as failed/incomplete history",
    },
}
DELAY_METRICS = ("mean_pre_update_rms_nm", "peak_strehl", "fourier_ee50_lambda_over_d", "production_ee50_lambda_over_d")
PSF_FIGURE = "analysis/figures/fig4_psf_panels.png"
MEDIA_TYPES = {".json": "application/json", ".csv": "text/csv", ".md": "text/markdown", ".py": "text/plain", ".png": "image/png"}


# --- small helpers -----------------------------------------------------------

def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def strict_json(path: Path) -> Any:
    def reject(value: str) -> Any:
        raise ExportError(f"{Path(path).name}: non-finite JSON constant {value}")

    try:
        return json.loads(Path(path).read_text(encoding="utf-8"), parse_constant=reject)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ExportError(f"{Path(path).name}: invalid JSON ({exc})") from exc


def write_json(path: Path, value: Any, *, compact: bool = False) -> None:
    text = json.dumps(value, allow_nan=False, separators=(",", ":") if compact else None, indent=None if compact else 2)
    Path(path).write_text(text + "\n", encoding="utf-8")


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ExportError(message)


def close(value: float, reference: float, what: str, *, rtol: float = 1e-12, atol: float = 1e-12) -> None:
    require(isinstance(value, (int, float)) and isinstance(reference, (int, float)) and math.isfinite(value) and math.isfinite(reference),
            f"{what}: missing or non-finite value")
    require(abs(value - reference) <= atol + rtol * abs(reference), f"{what}: {value!r} differs from the recorded {reference!r}")


def anchored(value: float, anchor: float, what: str, decimals: int = 6) -> None:
    """The exported value must round to the accepted anchor (half a unit of its last digit, plus float slack)."""
    close(value, anchor, f"{what} (acceptance anchor)", rtol=0.0, atol=0.5 * 10.0 ** -decimals + 1e-12)


def flatten(value: Any, prefix: str = "") -> Dict[str, Any]:
    if isinstance(value, dict):
        out: Dict[str, Any] = {}
        for key, item in value.items():
            out.update(flatten(item, f"{prefix}/{key}" if prefix else str(key)))
        return out
    return {prefix: value}


def config_differences(a: Dict[str, Any], b: Dict[str, Any]) -> List[str]:
    fa, fb = flatten(a), flatten(b)
    return sorted(key for key in set(fa) | set(fb) if fa.get(key) != fb.get(key))


def window_mean(values: np.ndarray, window: Sequence[int]) -> Tuple[float, int]:
    """Arithmetic mean over the half-open frame window [start, stop) and its sample count."""
    start, stop = window
    require(isinstance(start, int) and isinstance(stop, int) and 0 <= start < stop <= len(values),
            f"window [{start},{stop}) does not lie inside {len(values)} frames")
    part = np.asarray(values[start:stop], dtype=np.float64)
    require(bool(np.all(np.isfinite(part))), f"window [{start},{stop}) holds non-finite values")
    return float(np.mean(part)), int(part.size)


def t_quantile_df2(p: float) -> float:
    """Student-t quantile for two degrees of freedom, from the analytic CDF F(t) = 1/2 + t / (2 sqrt(2 + t^2))."""
    a = 2.0 * p - 1.0
    return a * math.sqrt(2.0 / (1.0 - a * a))


def paired_summary(differences: Sequence[float]) -> Dict[str, Any]:
    """Mean, sample SD and exploratory 95 % paired t interval of three paired differences (df = 2)."""
    values = [float(v) for v in differences]
    require(len(values) == 3 and all(math.isfinite(v) for v in values), "a paired summary needs three finite differences")
    mean = sum(values) / 3.0
    sd = math.sqrt(sum((v - mean) ** 2 for v in values) / 2.0)
    t = t_quantile_df2(0.975)
    half = t * sd / math.sqrt(3.0)
    return {"by_realization": values, "mean": mean, "sample_sd": sd, "t_0975_df2": t, "ci95": [mean - half, mean + half]}


class Package:
    """An extracted compact evidence package; every consumed file is checked against its listing."""

    def __init__(self, root: Path) -> None:
        self.root = Path(root).resolve()
        listing = self.root / "COMPACT_PACKAGE.json"
        require(listing.is_file() and not listing.is_symlink(), f"{listing.name} is missing from the evidence root")
        self.listing_sha256 = sha256_file(listing)
        value = strict_json(listing)
        require(isinstance(value, dict) and isinstance(value.get("files"), dict) and value["files"], "the compact listing names no files")
        self.schema = value.get("schema")
        self.files: Dict[str, Dict[str, Any]] = value["files"]
        self.consumed: Dict[str, Dict[str, Any]] = {}

    def path(self, relative: str, expected_sha256: Optional[str] = None) -> Path:
        parts = PurePosixPath(relative)
        require(not parts.is_absolute() and ".." not in parts.parts and relative == parts.as_posix(), f"{relative} is not a plain relative path")
        record = self.files.get(relative)
        require(isinstance(record, dict), f"{relative} is not listed in the compact package")
        path = self.root / relative
        require(path.is_file() and not path.is_symlink() and self.root in path.resolve().parents, f"{relative} is missing or not a regular file")
        size, sha = path.stat().st_size, sha256_file(path)
        require(size == record.get("bytes") and sha == record.get("sha256"),
                f"{relative} has {size} bytes / SHA-256 {sha[:12]}; the package lists {record.get('bytes')} / {str(record.get('sha256'))[:12]}")
        if expected_sha256 is not None:
            require(sha == expected_sha256, f"{relative} has SHA-256 {sha[:12]}, not the accepted {expected_sha256[:12]}")
        self.consumed[relative] = {"bytes": size, "sha256": sha}
        return path

    def json(self, relative: str, expected_sha256: Optional[str] = None) -> Any:
        return strict_json(self.path(relative, expected_sha256))

    def absent(self, relative: str) -> None:
        require(relative not in self.files and not (self.root / relative).exists(), f"{relative} exists; the selected record would be ambiguous")


def load_history(path: Path, frames: int, frame_rate_hz: float = FRAME_RATE_HZ) -> Dict[str, np.ndarray]:
    """The required scalar series of a saved history, refused if any is missing, malformed or non-finite."""
    name = Path(path).name
    try:
        with np.load(path, allow_pickle=False) as archive:
            missing = [key for key in REQUIRED_SERIES if key not in archive.files]
            require(not missing, f"{name}: missing series {missing}")
            arrays = {key: np.asarray(archive[key]) for key in REQUIRED_SERIES}
    except (OSError, ValueError, zipfile.BadZipFile) as exc:
        raise ExportError(f"{name}: unreadable history ({exc})") from exc
    for key, array in arrays.items():
        require(array.ndim == 1 and array.shape[0] == frames, f"{name}: {key} has shape {array.shape}, expected ({frames},)")
        if key == "reconstruction_usable":
            require(array.dtype == np.bool_, f"{name}: {key} is not boolean")
        else:
            require(array.dtype == np.float64 and bool(np.all(np.isfinite(array))), f"{name}: {key} is not finite float64")
    for key in ("pre_update_residual_opd_rms_m", "open_loop_opd_rms_m"):
        require(bool(np.all(arrays[key] > 0)), f"{name}: {key} holds non-positive values")
    valid = arrays["valid_measurement_fraction"]
    require(bool(np.all((valid >= 0) & (valid <= 1))), f"{name}: valid_measurement_fraction outside [0, 1]")
    expected_time = np.arange(frames, dtype=np.float64) / frame_rate_hz
    require(bool(np.allclose(arrays["time_s"], expected_time, rtol=0.0, atol=1e-12)),
            f"{name}: time_s is not frame index / {frame_rate_hz:g} Hz")
    require(bool(np.all(arrays["reconstruction_usable"])), f"{name}: a reconstruction is recorded as unusable")
    require(not bool(np.any(arrays["saturation_fraction"])), f"{name}: saturation is recorded")
    return arrays


def check_settings(effective: Dict[str, Any], metadata: Dict[str, Any], *, flux: float, delay: int, steps: int, realization: int, what: str) -> None:
    flat = flatten(effective)
    expected = dict(COMMON_SETTINGS)
    expected["detector_physics/source/detected_e_per_full_subap_frame"] = flux
    expected["controller/latency_frames"] = delay
    expected["controller/n_steps"] = steps
    for key, value in expected.items():
        require(flat.get(key) == value, f"{what}: {key} is {flat.get(key)!r}, expected {value!r}")
    require(flat.get("science_wavelengths_m/0", effective.get("science_wavelengths_m", [None])[0]) == 2.2e-06, f"{what}: science wavelength is not 2.2 um")
    require(metadata.get("frame_rate_hz") == FRAME_RATE_HZ and metadata.get("root_seed") == 1, f"{what}: history metadata frame rate or seed differ")
    require(metadata.get("realization_index") == realization, f"{what}: realization index {metadata.get('realization_index')!r}, expected {realization}")


def run_files(package: Package, directory: str, names: Sequence[str]) -> None:
    for name in names:
        package.path(f"{directory}/{name}")


def as_nm(array_m: np.ndarray) -> np.ndarray:
    return np.asarray(array_m, dtype=np.float64) * 1e9


def floats(array: np.ndarray) -> List[float]:
    return [float(v) for v in array]


def finish_bundle(out: Path, prefix: str, schema: str) -> Tuple[str, Dict[str, Any]]:
    files = {}
    for path in sorted(out.iterdir()):
        require(path.is_file() and path.suffix in MEDIA_TYPES, f"unexpected bundle member {path.name}")
        files[path.name] = {"bytes": path.stat().st_size, "sha256": sha256_file(path), "media_type": MEDIA_TYPES[path.suffix]}
    digest = hashlib.sha256(json.dumps(files, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()
    identity = f"{prefix}-{digest[:16]}"
    manifest = {"schema": schema, "id": identity, "files": files}
    write_json(out / "manifest.json", manifest)
    return identity, manifest


def verify_bundle(directory: Path, schema: str) -> Dict[str, Any]:
    """Re-read a written bundle: manifest schema and identity, every member's size and SHA-256, no stray file."""
    directory = Path(directory)
    manifest = strict_json(directory / "manifest.json")
    require(manifest.get("schema") == schema and isinstance(manifest.get("files"), dict), f"{directory.name}: unexpected manifest")
    files = manifest["files"]
    digest = hashlib.sha256(json.dumps(files, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()
    require(manifest.get("id", "").endswith(digest[:16]) and directory.name == manifest["id"], f"{directory.name}: identity does not match its listing")
    present = sorted(path.name for path in directory.iterdir())
    require(present == sorted(list(files) + ["manifest.json"]), f"{directory.name}: members {present} differ from the listing")
    for name, record in files.items():
        path = directory / name
        require(path.is_file() and not path.is_symlink() and path.stat().st_size == record["bytes"] and sha256_file(path) == record["sha256"],
                f"{directory.name}/{name} does not match its manifest record")
    return manifest


# --- guide-flux comparison ---------------------------------------------------

def export_flux(root: Path, out: Path, exporter_sha256: str) -> Dict[str, Any]:
    package = Package(root)
    analyses = {relative: package.json(relative, sha) for relative, sha in FLUX_ANALYSES.items()}
    pair = analyses["analysis/pair_bright_faint/pair_results.json"]
    require(pair.get("schema") == "pb42mbr2_pair_analysis.v1", "unexpected paired-analysis schema")
    require(pair["atmosphere_pairing"].get("atmosphere_paired_over_1000_frames") is True, "the paired analysis does not record a matched atmosphere")
    extension = {"bright": analyses["analysis/bright1/ext_results.json"], "faint": analyses["faint_flux1000-r2-attempt3/analysis/ext_results.json"]}

    runs: Dict[str, Dict[str, Any]] = {}
    for label, spec in FLUX_RUNS.items():
        source, directory = pair["sources"][label], spec["dir"]
        require(source.get("run_key") == spec["run_key"] and source.get("flux_e_per_full_subap_frame") == spec["flux"], f"{label}: paired analysis names another run")
        require(source.get("results_sha256") == FLUX_ANALYSES[("analysis/bright1/ext_results.json" if label == "bright" else "faint_flux1000-r2-attempt3/analysis/ext_results.json")],
                f"{label}: paired analysis binds another extension analysis")
        history = package.path(f"{directory}/history.npz", source["history_npz_sha256"])
        package.path(f"{directory}/run_summary.json", source["run_summary_sha256"])
        package.path(f"{directory}/atmosphere_digest.json", source["atmosphere_digest_sha256"])
        run_files(package, directory, ("science_record.json", "identity.json", "build_identities.json", "prefix_checkpoint.json"))
        config = package.json(f"{directory}/config.json")
        metadata = package.json(f"{directory}/history_metadata.json")["metadata"]
        check_settings(config["effective_config"], metadata, flux=spec["flux"], delay=2, steps=1000, realization=2, what=label)
        require(extension[label].get("run_key") == spec["run_key"] and extension[label].get("frames") == 1000, f"{label}: extension analysis names another run")
        launch_dir = "runs/ext-flux100000-r2-n1000.bright1" if label == "bright" else directory
        launch = package.json(f"{launch_dir}/launch.json")
        require(launch.get("checkout") == {"head": PRODUCER["commit"], "tree": PRODUCER["tree"]}, f"{label}: launched from another producer revision")
        runs[label] = {"config": config, "arrays": load_history(history, 1000)}

    bright, faint = runs["bright"]["arrays"], runs["faint"]["arrays"]
    require(config_differences(runs["bright"]["config"]["effective_config"], runs["faint"]["config"]["effective_config"])
            == ["detector_physics/source/detected_e_per_full_subap_frame"], "bright and faint configurations differ in more than the detected flux")
    require(bool(np.array_equal(bright["open_loop_opd_rms_m"], faint["open_loop_opd_rms_m"])), "bright and faint open-loop histories differ: atmosphere not matched")

    # The bright extension shares frames 0-499 with the original 500-frame bright run (the latency study's delay-2, r2 record).
    original_history = package.path(f"{FLUX_ORIGINAL_BRIGHT}/history.npz")
    original_config = package.json(f"{FLUX_ORIGINAL_BRIGHT}/config.json")
    original = load_history(original_history, 500)
    for key in ("pre_update_residual_opd_rms_m", "open_loop_opd_rms_m", "valid_measurement_fraction"):
        require(bool(np.array_equal(bright[key][:500], original[key])), f"bright frames 0-499 of {key} differ from the original 500-frame run")
    require(config_differences(original_config["effective_config"], runs["bright"]["config"]["effective_config"]) == ["controller/n_steps"],
            "the bright extension differs from its original run in more than the number of frames")

    pre = {label: as_nm(runs[label]["arrays"]["pre_update_residual_opd_rms_m"]) for label in FLUX_RUNS}
    valid = {label: runs[label]["arrays"]["valid_measurement_fraction"] for label in FLUX_RUNS}
    summaries: Dict[str, Any] = {}
    for key, window in FLUX_WINDOWS.items():
        (b, n), (f, _) = window_mean(pre["bright"], window), window_mean(pre["faint"], window)
        d, _ = window_mean(pre["faint"] - pre["bright"], window)
        recorded = PAIR_WINDOW[key]
        close(b, pair["per_run"]["bright"]["pre_mean_nm"][recorded], f"bright mean {window}")
        close(f, pair["per_run"]["faint"]["pre_mean_nm"][recorded], f"faint mean {window}")
        close(d, pair["faint_minus_bright"]["pre_mean_nm"][recorded], f"faint minus bright {window}")
        close(d, f - b, f"mean difference versus difference of means {window}")
        require(pair["faint_minus_bright"]["per_frame_pre_difference_nm"][recorded]["count"] == n, f"sample count {window}")
        for value, anchor, what in zip((b, f, d), FLUX_ANCHORS[key], ("bright", "faint", "faint minus bright")):
            anchored(value, anchor, f"{what} {window}")
        start, stop = window
        summaries[key] = {
            "frames": list(window), "samples": n, "seconds": n / FRAME_RATE_HZ,
            "bright_mean_nm": b, "faint_mean_nm": f, "faint_minus_bright_mean_nm": d,
            "bright_frames_valid_below_0_995": int(np.sum(valid["bright"][start:stop] < VALIDITY_MARK)),
            "faint_frames_valid_below_0_995": int(np.sum(valid["faint"][start:stop] < VALIDITY_MARK)),
            "faint_above_bright_frames": int(np.sum(pre["faint"][start:stop] > pre["bright"][start:stop])),
        }
    require(summaries["late"]["faint_frames_valid_below_0_995"] == 417 and summaries["late"]["bright_frames_valid_below_0_995"] == 0,
            "validity counts in frames 500-999 differ from the accepted 417 / 0")
    changes = {
        "bright_late_minus_early_nm": summaries["late"]["bright_mean_nm"] - summaries["early"]["bright_mean_nm"],
        "faint_late_minus_early_nm": summaries["late"]["faint_mean_nm"] - summaries["early"]["faint_mean_nm"],
    }
    changes["difference_in_changes_nm"] = changes["faint_late_minus_early_nm"] - changes["bright_late_minus_early_nm"]
    close(changes["bright_late_minus_early_nm"], pair["per_run"]["bright"]["added_minus_original_pre_nm"], "bright change", rtol=1e-9)
    close(changes["faint_late_minus_early_nm"], pair["per_run"]["faint"]["added_minus_original_pre_nm"], "faint change", rtol=1e-9)
    close(changes["difference_in_changes_nm"], pair["faint_minus_bright"]["difference_in_changes_pre_nm"], "difference in changes", rtol=1e-9)
    anchored(changes["bright_late_minus_early_nm"], FLUX_ANCHORS["changes"][0], "bright change")
    anchored(changes["faint_late_minus_early_nm"], FLUX_ANCHORS["changes"][1], "faint change")
    last50 = {label: [window_mean(pre[label], (450, 500))[0], window_mean(pre[label], (950, 1000))[0]] for label in FLUX_RUNS}
    for label in FLUX_RUNS:
        for value, recorded in zip(last50[label], pair["per_run"][label]["last50_pre_mean_nm"]):
            close(value, recorded, f"{label} last-50 mean", rtol=1e-11)

    images: Dict[str, Any] = {"late": None}
    for key, recorded in PAIR_IMAGE.items():
        images[key] = {"frames": list(FLUX_WINDOWS[key]), "source": f"analysis/pair_bright_faint/pair_results.json: images.<run>.{recorded}"}
        for label in FLUX_RUNS:
            values = pair["images"][label][recorded]
            entry = {name: values[name] for name in ("peak_strehl", "fourier_ee50_lambda_over_d", "production_ee50_lambda_over_d")}
            for name, value in entry.items():
                require(isinstance(value, float) and math.isfinite(value) and value > 0, f"{label} {recorded} {name} is not a positive number")
            if key == "full":
                close(entry["peak_strehl"], extension[label]["image_100_1000"]["peak_strehl"], f"{label} [100,1000) Strehl")
                close(entry["production_ee50_lambda_over_d"], extension[label]["image_100_1000"]["production_ee50_lambda_over_d"], f"{label} [100,1000) production EE50")
            images[key][label] = entry

    data = {
        "schema": "ao-explorer.flux42-data.v1",
        "frames": 1000, "frame_rate_hz": FRAME_RATE_HZ, "realization": 2, "root_seed": 1,
        "time": "t = k / frame_rate_hz for 0-based frame k; the pre-update residual of frame k is sampled at t, before that frame's control update",
        "startup_frames": list(STARTUP), "boundary_frame": 500,
        "boundary": "frame 500 (t = 1.000 s) separates the two analysis windows; the loop was not restarted there",
        "windows": {key: {"frames": list(window), "samples": window[1] - window[0]} for key, window in FLUX_WINDOWS.items()},
        "settings": {"profile": "det_ccd_42m_r3band_derived@1", "gain": 0.3, "leak": 0.0, "damping_alpha": 0.001,
                     "controller_delay_frames": 2, "science_wavelength_um": 2.2, "detector_noise": "on (native scoped policy)"},
        "runs": {label: {"run_key": spec["run_key"], "detected_e_per_full_subaperture_frame": spec["flux"],
                         "pre_update_residual_rms_nm": floats(pre[label]), "valid_measurement_fraction": floats(valid[label])}
                 for label, spec in FLUX_RUNS.items()},
        "open_loop_rms_nm": floats(as_nm(bright["open_loop_opd_rms_m"])),
        "summaries": summaries, "changes": changes,
        "last50": {"frames": [[450, 500], [950, 1000]], "bright_nm": last50["bright"], "faint_nm": last50["faint"]},
        "images": images,
        "image_note": "Peak Strehl and EE50 of the mean intensity image over the stated frames at 2.2 um. Fourier-reference EE50 is the primary width; production EE50 is secondary and sampling-sensitive. No image was accumulated over frames 500-999 alone, and no value for that window is derived by subtracting whole-window summaries.",
    }
    write_json(out / "data.json", data, compact=True)
    with (out / "frames.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle, lineterminator="\n")
        writer.writerow(["frame", "time_s", "bright_pre_update_residual_rms_nm", "faint_pre_update_residual_rms_nm",
                         "faint_minus_bright_nm", "bright_valid_measurement_fraction", "faint_valid_measurement_fraction", "open_loop_rms_nm"])
        for k in range(1000):
            writer.writerow([k, repr(k / FRAME_RATE_HZ), repr(float(pre["bright"][k])), repr(float(pre["faint"][k])),
                             repr(float(pre["faint"][k] - pre["bright"][k])), repr(float(valid["bright"][k])),
                             repr(float(valid["faint"][k])), repr(float(data["open_loop_rms_nm"][k]))])
    provenance = {
        "schema": "ao-explorer.flux42-provenance.v1",
        "source": FLUX_SOURCE, "producer_source": PRODUCER,
        "compact_listing": {"schema": package.schema, "sha256": package.listing_sha256},
        "inputs": dict(sorted(package.consumed.items())),
        "runs": {label: {"run_key": spec["run_key"], "directory": spec["dir"], "detected_e_per_full_subaperture_frame": spec["flux"],
                         "frames": 1000, "history_sha256": pair["sources"][label]["history_npz_sha256"],
                         "config_hash": runs[label]["config"].get("config_hash")}
                 for label, spec in FLUX_RUNS.items()},
        "faint_attempts": "Attempt 1 failed before its closed loop (tooling defect); attempt 2 was interrupted by a restart, with no persisted prefix verdict and an unknown completed-frame count; attempt 3 completed and is the trajectory shown. Earlier attempts remain recorded history.",
        "prefix": {"bright_original": FLUX_ORIGINAL_BRIGHT, "bright_original_history_sha256": package.consumed[f"{FLUX_ORIGINAL_BRIGHT}/history.npz"]["sha256"],
                   "relation": "frames 0-499 of both extensions repeat their original 500-frame runs exactly; frames 500-999 continue the same loop. The shared prefix is counted once and the extension is not an additional realization."},
        "image_sources": {"definition": "max(mean intensity) / max(ideal intensity) and encircled-energy radii of the mean pre-update intensity image at 2.2 um",
                          "mean_image_retrieval": "full-grid mean images are omitted from the compact package; their SHA-256 and retrieval stages are listed in its COMPACT_PACKAGE.json (mean_image_retrieval)"},
        "exporter": {"name": "export_42m_studies.py", "version": EXPORTER_VERSION, "sha256": exporter_sha256},
        "definitions": {
            "pre_update_residual_rms_nm": "piston-removed residual OPD RMS over the pupil before the control update of the frame, in nm",
            "window_mean": "arithmetic mean of the instantaneous per-frame RMS values over a half-open frame window (not the root mean square of frame RMS values)",
            "faint_minus_bright_nm": "faint minus bright pre-update residual of the same frame; positive means the faint run has the larger residual",
            "valid_measurement_fraction": "fraction of calibrated slope rows accepted in the frame",
            "detected_flux": "detected electrons per fully illuminated subaperture per frame",
        },
        "checks": {"simulation_run": False, "analysis_hashes_accepted": True, "histories_match_analysis_hashes": True,
                   "frames_per_run": 1000, "time_from_frame_index": True, "atmosphere_open_loop_identical": True,
                   "configs_differ_only_in_detected_flux": True, "bright_prefix_equals_original": True,
                   "window_means_match_analysis_and_anchors": True, "unusable_frames": 0, "saturated_frames": 0},
    }
    write_json(out / "provenance.json", provenance)
    (out / "README.md").write_text(FLUX_README, encoding="utf-8")
    shutil.copyfile(Path(__file__), out / "exporter.py")
    identity, manifest = finish_bundle(out, "flux42-r2", "ao-explorer.flux42-manifest.v1")
    return {"identity": identity, "manifest": manifest, "summaries": summaries, "changes": changes,
            "original_bright_history_sha256": provenance["prefix"]["bright_original_history_sha256"], "inputs": package.consumed}


FLUX_README = """# 42 m guide-flux comparison, realization 2, 1000 frames

Two saved closed-loop trajectories of the synthetic 42 m SCAO profile
(det_ccd_42m_r3band_derived@1), identical except for the guide-source flux:
100000 and 1000 detected electrons per fully illuminated subaperture per
frame.  Both run 1000 frames at 500 Hz (2 s) through the same atmospheric
realization (r2, root seed 1), with gain 0.3, leak 0, two queued frames and
production damping 0.001.  This bundle only re-expresses saved values; no
atmosphere, sensor, reconstructor, controller or PSF was run to make it.

Files: data.json (per-frame pre-update residual RMS in nm, valid-measurement
fraction, the shared open-loop RMS, window summaries and recorded image
metrics), frames.csv (the same per-frame values), provenance.json (source
identities, input hashes, definitions and checks) and exporter.py.

Time is t = k / 500 Hz for frame k.  Window means are arithmetic means of the
per-frame RMS values over half-open frame windows: [100,500) 400 frames,
[500,1000) 500 frames and [100,1000) 900 frames.  Frame 500 is an analysis
boundary, not a restart.  Frames 0-499 of each run repeat its original
500-frame run exactly, so the extension is one longer trajectory, not an
additional realization.

What it shows: in this one matched realization, the faint run's residual
grows much more after frame 500 than the bright run's.  The bright window
means are nearly unchanged (186.98 versus 187.12 nm), although its last-50
mean rises by about 5 nm.  What it does not show: the change of flux also
changes the native WFS noise derivation and the calibration/reconstructor
identities, so measurement noise is not isolated; one realization gives no
ensemble or long-term stability statement, and no damping conclusion.

Image metrics exist for frames 100-499 and 100-999 only.  No image was
accumulated over frames 500-999 alone; none is derived by subtraction.
Fourier-reference EE50 is the primary width; production EE50 is secondary and
sampling-sensitive.
"""


# --- controller-delay comparison ---------------------------------------------

def delay_run_key(delay: int, realization: int) -> str:
    return f"flux100000-r{realization}" if delay == 2 else f"lat{delay}-flux100000-r{realization}"


def delay_directory(run_key: str, delay: int) -> str:
    if run_key in ATTEMPT_SELECTION:
        return ATTEMPT_SELECTION[run_key]["selected_dir"]
    return f"records/baseline/{run_key}" if delay == 2 else f"records/new/{run_key}/output"


def select_attempt(package: Package, run_key: str, expected_history_sha256: str) -> Tuple[str, Dict[str, Any]]:
    """The accepted attempt's directory; refused if an excluded attempt holds a history or the ledger disagrees."""
    selection = ATTEMPT_SELECTION[run_key]
    package.absent(f"{selection['excluded_dir']}/output/history.npz")
    package.absent(f"{selection['excluded_dir']}/history.npz")
    ledger = package.json("attempt2/runs/LEDGER.json")
    inspections = [event for event in ledger.get("events", []) if event.get("run_key") == run_key and event.get("event") == "inspected"]
    require(inspections and inspections[-1].get("attempt") == selection["selected_attempt"] and inspections[-1].get("classification") == "completed_verified",
            f"{run_key}: the attempt ledger does not end with a verified inspection of attempt {selection['selected_attempt']}")
    directory = selection["selected_dir"]
    package.path(f"{directory}/history.npz", expected_history_sha256)
    return directory, {key: selection[key] for key in ("selected_attempt", "amendment", "excluded_attempt", "excluded_status")}


def export_delay(root: Path, out: Path, exporter_sha256: str) -> Dict[str, Any]:
    package = Package(root)
    results = package.json("analysis/lat_results.json", DELAY_ANALYSES["analysis/lat_results.json"])
    require(results.get("schema") == "lat42m_analysis.v1", "unexpected latency-analysis schema")
    require(results["window"]["half_open"] == list(DELAY_WINDOW) and results["window"]["samples"] == 400, "unexpected analysis window")
    require(results["accounting"]["records"] == 9 and not results["accounting"]["not_available"], "the analysis does not account for nine records")
    by_key = {record["run_key"]: record for record in results["records"]}
    require(len(by_key) == 9, "duplicate analysis records")

    records: List[Dict[str, Any]] = []
    arrays: Dict[Tuple[int, int], Dict[str, np.ndarray]] = {}
    configs: Dict[Tuple[int, int], Dict[str, Any]] = {}
    for realization in REALIZATIONS:
        for delay in DELAYS:
            key = delay_run_key(delay, realization)
            record = by_key.get(key)
            require(record is not None and record["latency_frames"] == delay and record["realization_index"] == realization, f"{key}: no matching analysis record")
            require(record["status"] == "completed_verified" and record["source"] == ("baseline" if delay == 2 else "new"), f"{key}: unexpected status or source")
            files = record["metrics"]["files"]
            attempt: Dict[str, Any] = {"selected_attempt": 1}
            if key in ATTEMPT_SELECTION:
                directory, attempt = select_attempt(package, key, files["history.npz"]["sha256"])
            else:
                directory = delay_directory(key, delay)
            history = package.path(f"{directory}/history.npz", files["history.npz"]["sha256"])
            for name in ("config.json", "history_metadata.json", "run_summary.json", "science_record.json", "atmosphere_digest.json", "identity.json", "build_identities.json"):
                package.path(f"{directory}/{name}", files[name]["sha256"])
            config = package.json(f"{directory}/config.json")
            metadata = package.json(f"{directory}/history_metadata.json")["metadata"]
            check_settings(config["effective_config"], metadata, flux=100000.0, delay=delay, steps=500, realization=realization, what=key)
            if delay != 2:
                require(record["launch_json"]["checkout"] == {"head": PRODUCER["commit"], "tree": PRODUCER["tree"]}, f"{key}: launched from another producer revision")
            arrays[(delay, realization)] = load_history(history, 500)
            configs[(delay, realization)] = config["effective_config"]
            records.append({"run_key": key, "delay_frames": delay, "realization": realization, "directory": directory,
                            "source": "reused baseline" if delay == 2 else "new", "attempt": attempt,
                            "history_sha256": files["history.npz"]["sha256"], "analysis_record": record})

    for realization in REALIZATIONS:
        for delay in (1, 3):
            require(config_differences(configs[(2, realization)], configs[(delay, realization)]) == ["controller/latency_frames"],
                    f"r{realization}: delay {delay} differs from its baseline in more than the configured delay")
            require(bool(np.array_equal(arrays[(2, realization)]["open_loop_opd_rms_m"], arrays[(delay, realization)]["open_loop_opd_rms_m"])),
                    f"r{realization}: open-loop histories differ across delays; atmosphere not matched")
    require(len({arrays[(2, r)]["open_loop_opd_rms_m"].tobytes() for r in REALIZATIONS}) == 3, "the three realizations do not have distinct atmospheres")

    levels = results["levels"]
    exported_records = []
    for item in records:
        delay, realization = item["delay_frames"], item["realization"]
        h = arrays[(delay, realization)]
        pre = as_nm(h["pre_update_residual_opd_rms_m"])
        valid = h["valid_measurement_fraction"]
        mean, samples = window_mean(pre, DELAY_WINDOW)
        rms_of_frames = float(np.sqrt(np.mean(pre[DELAY_WINDOW[0]:DELAY_WINDOW[1]] ** 2)))
        r = str(realization)
        close(mean, levels["mean_pre_update_rms_nm"][str(delay)]["by_realization"][r], f"{item['run_key']} mean pre-update RMS")
        close(rms_of_frames, levels["rms_of_frame_pre_update_rms_nm"][str(delay)]["by_realization"][r], f"{item['run_key']} RMS of frame RMS")
        require(rms_of_frames > mean, f"{item['run_key']}: RMS of frame RMS is not above the arithmetic mean")
        valid_mean, _ = window_mean(valid, DELAY_WINDOW)
        close(valid_mean, levels["valid_measurement_fraction_mean"][str(delay)]["by_realization"][r], f"{item['run_key']} valid fraction")
        image = item["analysis_record"]["metrics"]["image"]
        summary = {"mean_pre_update_rms_nm": mean, "samples": samples, "rms_of_frame_pre_update_rms_nm": rms_of_frames,
                   "valid_fraction_mean": valid_mean,
                   "frames_valid_below_0_995": int(np.sum(valid[DELAY_WINDOW[0]:DELAY_WINDOW[1]] < VALIDITY_MARK)),
                   "peak_strehl": levels["peak_strehl"][str(delay)]["by_realization"][r],
                   "fourier_ee50_lambda_over_d": levels["fourier_ee50_lambda_over_d"][str(delay)]["by_realization"][r],
                   "production_ee50_lambda_over_d": levels["production_ee50_lambda_over_d"][str(delay)]["by_realization"][r]}
        close(summary["peak_strehl"], image["peak_strehl"], f"{item['run_key']} Strehl")
        close(summary["fourier_ee50_lambda_over_d"], image["fourier_ee50"]["ee50_lambda_over_d"], f"{item['run_key']} Fourier EE50")
        close(summary["production_ee50_lambda_over_d"], image["production_ee50_lambda_over_d"], f"{item['run_key']} production EE50")
        exported_records.append({
            "run_key": item["run_key"], "delay_frames": delay, "realization": realization, "source": item["source"],
            "attempt": item["attempt"]["selected_attempt"],
            "pre_update_residual_rms_nm": floats(pre), "valid_measurement_fraction": floats(valid), "summary": summary,
        })

    def value(metric: str, delay: int, realization: int) -> float:
        record = next(r for r in exported_records if r["delay_frames"] == delay and r["realization"] == realization)
        return record["summary"][metric]

    level_out: Dict[str, Any] = {}
    paired_out: Dict[str, Any] = {}
    for metric in DELAY_METRICS:
        level_out[metric] = {}
        for delay in DELAYS:
            values = [value(metric, delay, r) for r in REALIZATIONS]
            mean = sum(values) / 3.0
            sd = math.sqrt(sum((v - mean) ** 2 for v in values) / 2.0)
            recorded = levels[metric][str(delay)]
            close(mean, recorded["mean"], f"{metric} delay {delay} mean")
            close(sd, recorded["sample_sd"], f"{metric} delay {delay} SD", rtol=1e-9)
            level_out[metric][str(delay)] = {"by_realization": values, "mean": mean, "sample_sd": sd}
            if metric in DELAY_ANCHORS:
                anchored(mean, DELAY_ANCHORS[metric][delay], f"{metric} delay {delay}")
        paired_out[metric] = {}
        for comparison, other in (("1_minus_2", 1), ("3_minus_2", 3)):
            summary = paired_summary([value(metric, other, r) - value(metric, 2, r) for r in REALIZATIONS])
            recorded = results["paired"][metric][comparison]
            for r in REALIZATIONS:
                close(summary["by_realization"][r], recorded["differences_by_realization"][str(r)], f"{metric} {comparison} r{r}", rtol=1e-9)
            close(summary["mean"], recorded["mean_difference"], f"{metric} {comparison} mean", rtol=1e-9)
            close(summary["t_0975_df2"], recorded["t_0975_df2"], "t quantile", rtol=1e-12)
            close(summary["ci95"][0], recorded["ci95_low"], f"{metric} {comparison} lower bound", rtol=1e-9)
            close(summary["ci95"][1], recorded["ci95_high"], f"{metric} {comparison} upper bound", rtol=1e-9)
            paired_out[metric][comparison] = summary
    for comparison in ("1_minus_2", "3_minus_2"):
        summary = paired_out["mean_pre_update_rms_nm"][comparison]
        for got, anchor in zip([summary["mean"], *summary["ci95"]], DELAY_ANCHORS[comparison]):
            anchored(got, anchor, f"residual {comparison}")
    for got, anchor in zip(paired_out["mean_pre_update_rms_nm"]["3_minus_2"]["by_realization"], DELAY_ANCHORS["3_minus_2_by_realization"]):
        anchored(got, anchor, "residual 3 minus 2 by realization")
    require(paired_out["mean_pre_update_rms_nm"]["3_minus_2"]["ci95"][0] < 0 < paired_out["mean_pre_update_rms_nm"]["3_minus_2"]["ci95"][1],
            "the 3-2 residual interval no longer crosses zero")

    strehl = level_out["peak_strehl"]
    loss = strehl["2"]["mean"] - strehl["3"]["mean"]
    gain = strehl["1"]["mean"] - strehl["2"]["mean"]
    anchored(loss / gain, DELAY_ANCHORS["strehl_ratio"], "Strehl loss/gain ratio")

    h3 = arrays[(3, 2)]
    pre3, valid3 = as_nm(h3["pre_update_residual_opd_rms_m"]), h3["valid_measurement_fraction"]
    for frame, anchor in EXCURSION_ANCHORS["pre_nm"].items():
        anchored(float(pre3[frame]), anchor, f"delay-3 r2 frame {frame}")
    for frame, anchor in EXCURSION_ANCHORS["valid"].items():
        anchored(float(valid3[frame]), anchor, f"delay-3 r2 validity frame {frame}", decimals=9)
    valid_late, _ = window_mean(valid3, (345, 500))
    valid_early, _ = window_mean(valid3, (100, 300))
    anchored(valid_late, EXCURSION_ANCHORS["valid_mean_345_500"], "validity mean [345,500)", decimals=9)
    anchored(valid_early, EXCURSION_ANCHORS["valid_mean_100_300"], "validity mean [100,300)", decimals=9)
    below = int(np.sum(valid3[100:500] < VALIDITY_MARK))
    require(below == EXCURSION_ANCHORS["frames_below_0_995"], f"delay-3 r2 has {below} frames below 0.995, not 137")
    minimum_frame = int(np.argmin(valid3))
    excursion = {
        "status": "post-hoc description, not part of the planned analysis",
        "record": "lat3-flux100000-r2", "delay_frames": 3, "realization": 2, "attempt": 2,
        "first_rise_frames": [338, 344], "first_rise_nm": [float(pre3[338]), float(pre3[344])], "frame_339_nm": float(pre3[339]),
        "second_rise_frames": [446, 447], "second_rise_nm": [float(pre3[446]), float(pre3[447])],
        "second_rise_valid_fraction": [float(valid3[446]), float(valid3[447])],
        "valid_minimum": {"frame": minimum_frame, "value": float(valid3[minimum_frame])},
        "valid_mean_frames_100_300": valid_early, "valid_mean_frames_345_500": valid_late,
        "frames_valid_below_0_995_in_window": below,
        "other_delays_r2_max_nm": {str(d): {"frame": int(np.argmax(as_nm(arrays[(d, 2)]["pre_update_residual_opd_rms_m"])[300:400]) + 300),
                                            "value": float(np.max(as_nm(arrays[(d, 2)]["pre_update_residual_opd_rms_m"])[300:400]))} for d in (1, 2)},
        "wording": "Observational only (LAT-R01): around the same time in r2 every delay shows a disturbance; at delay 3 a larger validity dip coincides with the first residual rise, followed by a second rise without a simultaneous validity drop. The mechanism (closed-loop state, sensor validity, native noise) is unresolved.",
    }
    require(minimum_frame == 344, "the validity minimum is not at frame 344")

    open_loop = {str(r): floats(as_nm(arrays[(2, r)]["open_loop_opd_rms_m"])) for r in REALIZATIONS}
    baselines = results["provenance"]
    data = {
        "schema": "ao-explorer.delay42-data.v1",
        "frames": 500, "frame_rate_hz": FRAME_RATE_HZ, "root_seed": 1,
        "time": "t = k / frame_rate_hz for 0-based frame k; the pre-update residual of frame k is sampled at t, before that frame's control update",
        "startup_frames": list(STARTUP), "window": {"frames": list(DELAY_WINDOW), "samples": 400},
        "delays": list(DELAYS), "realizations": list(REALIZATIONS), "production_delay": 2,
        "timing": "An increment reconstructed at frame k is released at frame k+L and first sensed in the pre-update residual at k+L+1. L is the configured controller queue length, not a measured end-to-end instrument latency.",
        "settings": {"profile": "det_ccd_42m_r3band_derived@1", "detected_e_per_full_subaperture_frame": 100000.0, "gain": 0.3, "leak": 0.0,
                     "damping_alpha": 0.001, "science_wavelength_um": 2.2, "detector_noise": "on (native scoped policy)"},
        "records": exported_records, "open_loop_rms_nm": open_loop,
        "levels": level_out, "paired": paired_out,
        "strehl_asymmetry": {"loss_2_to_3": loss, "gain_2_to_1": gain, "ratio": loss / gain,
                             "definition": "sample-mean peak-Strehl loss from delay 2 to 3 divided by the gain from delay 2 to 1, gain 0.3, realizations r0-r2 (LAT-R04); not a general latency cost multiplier and not the same for other metrics"},
        "excursion_r2": excursion,
    }
    write_json(out / "data.json", data, compact=True)
    with (out / "frames.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle, lineterminator="\n")
        writer.writerow(["run_key", "delay_frames", "realization", "source", "attempt", "frame", "time_s",
                         "pre_update_residual_rms_nm", "valid_measurement_fraction", "open_loop_rms_nm"])
        for record in exported_records:
            for k in range(500):
                writer.writerow([record["run_key"], record["delay_frames"], record["realization"], record["source"], record["attempt"], k,
                                 repr(k / FRAME_RATE_HZ), repr(record["pre_update_residual_rms_nm"][k]),
                                 repr(record["valid_measurement_fraction"][k]), repr(open_loop[str(record["realization"])][k])])
    shutil.copyfile(package.path(PSF_FIGURE), out / "psf_panels.png")
    provenance = {
        "schema": "ao-explorer.delay42-provenance.v1",
        "source": DELAY_SOURCE, "producer_source": PRODUCER,
        "compact_listing": {"schema": package.schema, "sha256": package.listing_sha256},
        "inputs": dict(sorted(package.consumed.items())),
        "records": [{"run_key": item["run_key"], "delay_frames": item["delay_frames"], "realization": item["realization"],
                     "source": item["source"], "directory": item["directory"], "history_sha256": item["history_sha256"],
                     "attempt": item["attempt"],
                     **({"baseline_stage_commit": baselines[str(item["realization"])]["stage_commit"],
                         "baseline_archive_sha256": baselines[str(item["realization"])]["archive_sha256"]} if item["delay_frames"] == 2 else {})}
                    for item in records],
        "attempt_selection": ATTEMPT_SELECTION,
        "accounting": "six new successful trajectories (delays 1 and 3) and three reused delay-2 baselines from the photon-budget study: nine analyzed records, three realization pairs per comparison. Seven new scientific attempts were made; the interrupted first delay-3/r2 attempt is excluded.",
        "static_figure": {"member": "psf_panels.png", "source": PSF_FIGURE, "sha256": package.consumed[PSF_FIGURE]["sha256"],
                          "note": "copied byte for byte from the accepted analysis; mean PSFs over frames 100-499 at 2.2 um; not regenerated"},
        "exporter": {"name": "export_42m_studies.py", "version": EXPORTER_VERSION, "sha256": exporter_sha256},
        "definitions": {
            "pre_update_residual_rms_nm": "piston-removed residual OPD RMS over the pupil before the control update of the frame, in nm",
            "mean_pre_update_rms_nm": "arithmetic mean of the per-frame RMS values over [100,500), 400 frames (not the root mean square of frame RMS values, which is also given for reference)",
            "paired_difference": "delay L minus delay 2 within the same realization; the interval is an exploratory 95 % paired t interval with df = 2 over three conditional realizations (one seed, native scoped noise policy); the 400 correlated frames are not replicates",
            "image_metrics": "peak Strehl and EE50 of the mean intensity image over [100,500) at 2.2 um; Fourier-reference EE50 primary, production EE50 secondary and sampling-sensitive",
        },
        "wording_corrections": "LAT-R01 to LAT-R04 of the 2026-10-29 latency review are applied in this bundle and on the page; the frozen study reports are unchanged.",
        "checks": {"simulation_run": False, "analysis_hash_accepted": True, "histories_match_analysis_hashes": True,
                   "frames_per_record": 500, "records": 9, "time_from_frame_index": True,
                   "configs_differ_from_baseline_only_in_delay": True, "atmosphere_matched_within_realization": True,
                   "realizations_distinct": True, "failed_attempt_excluded": True,
                   "window_means_levels_and_intervals_match_analysis_and_anchors": True, "unusable_frames": 0, "saturated_frames": 0},
    }
    write_json(out / "provenance.json", provenance)
    (out / "README.md").write_text(DELAY_README, encoding="utf-8")
    shutil.copyfile(Path(__file__), out / "exporter.py")
    identity, manifest = finish_bundle(out, "delay42", "ao-explorer.delay42-manifest.v1")
    baseline_r2 = next(item["history_sha256"] for item in records if item["delay_frames"] == 2 and item["realization"] == 2)
    return {"identity": identity, "manifest": manifest, "levels": level_out, "paired": paired_out,
            "baseline_r2_history_sha256": baseline_r2, "excursion": excursion, "inputs": package.consumed}


DELAY_README = """# 42 m controller-delay comparison, realizations 0-2, 500 frames

Nine saved closed-loop records of the synthetic 42 m SCAO profile
(det_ccd_42m_r3band_derived@1) at 100000 detected electrons per fully
illuminated subaperture per frame, gain 0.3, leak 0, damping 0.001, 500 Hz.
Only the configured controller delay changes: 1, 2 or 3 frames, each in the
same three atmospheric realizations (r0, r1, r2; root seed 1).  The six delay-1
and delay-3 trajectories are new; the three delay-2 records are the reused
photon-budget baselines.  The delay-3/r2 record is the accepted second attempt;
the first attempt was lost to a container restart and has no history.  This
bundle only re-expresses saved values; nothing was simulated to make it.

Timing: an increment reconstructed at frame k is released at frame k+L and
first sensed in the pre-update residual at frame k+L+1.  L is a queue length
in the simulation, not a measured end-to-end instrument latency.

Files: data.json (per-frame pre-update residual RMS in nm and valid fraction
for all nine records, the open-loop RMS of each realization, per-delay
summaries, paired differences against delay 2 with exploratory intervals,
the Strehl asymmetry and the post-hoc r2 description), frames.csv,
psf_panels.png (the accepted analysis figure, copied unchanged),
provenance.json and exporter.py.

Main window [100,500): 400 frames, 0.8 s per record.  Paired intervals are
exploratory 95 % t intervals with df = 2 over three conditional realizations;
the 400 correlated frames are not replicates.  The 3-2 residual interval,
[-4.48, +44.20] nm, includes zero; all three differences are positive and r2
is the largest.  The about 2.3 ratio is the sample-mean peak-Strehl loss from
delay 2 to 3 divided by the gain from 2 to 1, at gain 0.3, in these three
realizations; it is not a general cost multiplier.  The results establish no
stability boundary, optimal gain, hardware requirement or behaviour after
frame 499.

Wording corrections (latency review of 2026-10-29), applied here and on the
page while the frozen study reports and their hashes stay unchanged:
LAT-R01 the r2 excursion is described observationally, without a proven
atmospheric cause; LAT-R02 the similar whole-window mean-image Strehl of r2
does not measure the excursion's effect on the image; LAT-R03 202.761403 nm
is frame 338 (339: 208.842077, 344: 255.093974), frames 446->447 rise from
248.795052 to 273.001961 nm without a simultaneous validity drop (0.993153365
-> 0.993740219), validity recovers only partly (mean 0.991961987 over
[345,500) versus 0.999310446 over [100,300)), 137 window frames are below
0.995; LAT-R04 the ratio is tied to Strehl, the sample and gain 0.3.
"""


# --- binding -----------------------------------------------------------------

def bind(web_dir: Path, built: Dict[str, Tuple[Path, str, str]]) -> Dict[str, Any]:
    """Copy each built bundle into site/derived (an existing directory must be byte-identical) and record it in the entry."""
    web_dir = Path(web_dir)
    entry_path = web_dir / "data" / "current.json"
    entry = strict_json(entry_path)
    require(entry.get("schema") == "ao-explorer.entry.v1", "the site entry is not an ao-explorer.entry.v1 document")
    for key, (source, identity, schema) in built.items():
        target = web_dir / "derived" / identity
        if target.exists():
            require(sha256_file(target / "manifest.json") == sha256_file(source / "manifest.json"), f"{target.name} exists with other content")
        else:
            shutil.copytree(source, target)
        verify_bundle(target, schema.replace("-entry.", "-manifest."))
        manifest = target / "manifest.json"
        entry[key] = {"schema": schema, "id": identity, "manifest": f"../derived/{identity}/manifest.json",
                      "manifest_bytes": manifest.stat().st_size, "manifest_sha256": sha256_file(manifest)}
    entry_path.write_text(json.dumps(entry, indent=2) + "\n", encoding="utf-8")
    return entry


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--flux-root", type=Path, required=True)
    parser.add_argument("--delay-root", type=Path, required=True)
    parser.add_argument("--web-dir", type=Path, required=True)
    parser.add_argument("--write", action="store_true")
    arguments = parser.parse_args(argv)
    exporter_sha256 = sha256_file(Path(__file__))
    try:
        with tempfile.TemporaryDirectory(prefix="studies42-") as temp:
            flux_dir, delay_dir = Path(temp) / "flux", Path(temp) / "delay"
            flux_dir.mkdir(); delay_dir.mkdir()
            flux = export_flux(arguments.flux_root, flux_dir, exporter_sha256)
            delay = export_delay(arguments.delay_root, delay_dir, exporter_sha256)
            require(flux["original_bright_history_sha256"] == delay["baseline_r2_history_sha256"],
                    "the original bright r2 history and the delay-2 r2 baseline are not the same saved record")
            flux_final, delay_final = Path(temp) / flux["identity"], Path(temp) / delay["identity"]
            flux_dir.rename(flux_final); delay_dir.rename(delay_final)
            verify_bundle(flux_final, "ao-explorer.flux42-manifest.v1")
            verify_bundle(delay_final, "ao-explorer.delay42-manifest.v1")
            if arguments.write:
                bind(arguments.web_dir, {"flux42": (flux_final, flux["identity"], "ao-explorer.flux42-entry.v1"),
                                         "delay42": (delay_final, delay["identity"], "ao-explorer.delay42-entry.v1")})
            report = {
                "written": arguments.write, "simulation_run": False, "exporter_sha256": exporter_sha256, "exporter_version": EXPORTER_VERSION,
                "flux42": {"id": flux["identity"], "members": {k: v["bytes"] for k, v in flux["manifest"]["files"].items()},
                           "inputs_verified": len(flux["inputs"]),
                           "window_means_nm": {k: [v["bright_mean_nm"], v["faint_mean_nm"], v["faint_minus_bright_mean_nm"], v["samples"]] for k, v in flux["summaries"].items()},
                           "changes_nm": flux["changes"]},
                "delay42": {"id": delay["identity"], "members": {k: v["bytes"] for k, v in delay["manifest"]["files"].items()},
                            "inputs_verified": len(delay["inputs"]),
                            "mean_pre_update_rms_nm": {k: v["mean"] for k, v in delay["levels"]["mean_pre_update_rms_nm"].items()},
                            "paired_pre_nm": {k: [v["mean"], *v["ci95"]] for k, v in delay["paired"]["mean_pre_update_rms_nm"].items()}},
                "shared_record": {"delay2_r2_equals_original_bright_r2": True, "history_sha256": delay["baseline_r2_history_sha256"]},
            }
    except ExportError as exc:
        print(json.dumps({"exported": False, "error": str(exc)}))
        return 2
    print(json.dumps(report, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
