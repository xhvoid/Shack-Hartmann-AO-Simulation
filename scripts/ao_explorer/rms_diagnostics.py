"""Per-frame residual RMS after tip/tilt removal: a scalar derivative of the one-second dataset.

Usage (applies to the dataset named by the active entry; ``long_export.py``
calls :func:`build` itself for a new export)::

    python scripts/ao_explorer/rms_diagnostics.py \\
        --web-dir web/ao-explorer --series-dir outputs/ao_explorer_1s/<series-id> \\
        --derived-root outputs/ao_explorer_1s_derived

Deterministic postprocessing of the saved maps; no AO run, no random number,
no image.  For every frame ``k`` of every case it takes the archived
pre-update residual map (``frames/pre_update_residual_opd_m.npy[k]``: the
wavefront whose image is that frame's AO-corrected PSF) and fits, by
equal-weight least squares over the illuminated pupil samples of the saved
pupil mask, a plane ``p(x, y) = a + b x + c y`` in the actual pupil-grid
coordinates.  The diagnostic is

    detilted_rms_nm[k] = 1e9 * sqrt(mean((r - p)^2 over the pupil))

in float64; the fitted intercept removes piston.  Samples outside the pupil
are excluded (they are NaN in the archive); a non-finite value inside the
pupil refuses the computation.  Before anything is written, each map is bound
to its frame by the SHA-256 the observer streamed for it, its piston-removed
RMS is recomputed and compared with the recorded total residual RMS, and the
archive files are re-hashed against the case record.

The atmosphere RMS and the total residual RMS are not recomputed here: they
are the dataset's existing per-frame series (piston removed, tilt retained),
which the page already shows.  Each case record of this derivative names the
SHA-256 of the dataset's metrics member it accompanies.  The dataset, its
images and its galaxy derivative are unchanged; the derivative has its own
identity and is bound by a ``diagnostics`` block of ``data/current.json``.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
import platform
import sys
from typing import Any, Dict, List, Optional

import numpy as np

import identity
import long_series
import producer
import protocol


SCHEMA_CASE = "ao-explorer.rms-diagnostics.v1"
SCHEMA_MANIFEST = "ao-explorer.rms-diagnostics-manifest.v1"
SCHEMA_ENTRY = "ao-explorer.rms-diagnostics-entry.v1"
REVISION = "detilted-residual-rms-v1"
CODE_FILES = ("rms_diagnostics.py", "long_series.py", "producer.py", "protocol.py", "identity.py")
RESIDUAL_STACK = "frames/pre_update_residual_opd_m.npy"
UNITS = "nm OPD"

DEFINITION = {
    "quantity": "residual RMS after tip/tilt removal (piston and fitted tilt removed)",
    "field": (
        "pre_update_residual_opd_m of frame k: the frame's recorded atmosphere minus the DM correction held while the frame was "
        "measured; the same wavefront whose image is the AO-corrected instantaneous PSF of frame k"
    ),
    "fit": "p(x, y) = a + b x + c y, equal-weight linear least squares over the illuminated pupil samples of the saved pupil mask",
    "formula": "detilted_rms_nm[k] = 1e9 * sqrt(mean((r_k - p_k)^2 over the pupil samples)); the fitted intercept a removes piston",
    "units": UNITS,
    "weighting": "every illuminated pupil sample has equal weight, as in the existing piston-removed RMS (shwfs_ao.core.wavefront.masked_rms)",
    "exterior": "samples outside the pupil are excluded (NaN in the archive), never treated as zero; a non-finite value inside the pupil refuses the computation",
    "precision": "float64 throughout",
    "timing": "frame-start sampling: frame k starts at t_k = k / 1000 s; the residual is the pre-update residual the WFS measured in frame k",
    "frame_mapping": "values[k] belongs to numerical frame k (k = 0..999); the page maps its displayed position through time_domain.display_indices to k and never interpolates",
    "companions": {
        "atmosphere_rms_nm": "the dataset's existing per-frame series: pupil RMS of atmosphere_opd_m, piston removed, tilt retained",
        "residual_rms_nm": "the dataset's existing per-frame series: pupil RMS of pre_update_residual_opd_m, piston removed, tilt retained (total residual)",
    },
    "scope": [
        "Tilt is removed only in this calculation. The displayed PSFs and galaxy images keep their original image motion and morphology; no correction was applied to them.",
        "The total residual includes tilt; the residual after tip/tilt removal separates the fitted wavefront tilt from the remaining higher-order error.",
        "A fitted wavefront plane is not the same quantity as a measured image-centroid motion.",
        "The atmosphere RMS keeps its tilt while this residual has its fitted tilt removed, so their ratio alone is not a like-for-like measure of AO correction efficiency.",
        "A smaller detilted RMS is not evidence of convergence and is not an additional correction applied to the images.",
    ],
}


class DiagnosticsError(RuntimeError):
    pass


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise DiagnosticsError(message)


def _json_bytes(value: Any) -> bytes:
    return (json.dumps(value, indent=1, allow_nan=False, ensure_ascii=False) + "\n").encode("utf-8")


def _array_sha(array: np.ndarray) -> str:
    return identity.sha256_bytes(np.ascontiguousarray(array).tobytes())


def code_identity() -> Dict[str, Any]:
    record = identity.file_set_identity(CODE_FILES)
    record["git"] = identity.git_state(identity.EXPORTER_DIR.relative_to(identity.REPO_ROOT).as_posix())
    return record


def pupil_coordinates(plan: Dict[str, Any]) -> Dict[str, Any]:
    """The actual pupil-grid coordinates of the native geometry (built, not assumed)."""

    case = long_series.plan_case(plan, long_series.CASE_ORDER[0])
    geometry = long_series.native_geometry(producer.job_config(case))
    x = np.ascontiguousarray(np.asarray(geometry.x_m, dtype=np.float64))
    y = np.ascontiguousarray(np.asarray(geometry.y_m, dtype=np.float64))
    spacing = case["admission"]["pupil_spacing"]
    _require(x.shape == y.shape == tuple(case["admission"]["pupil_shape"]), "the pupil coordinates do not have the admitted pupil shape")
    _require([float(x.min()), float(x.max())] == spacing["x_range_m"] and [float(y.min()), float(y.max())] == spacing["y_range_m"], "the pupil coordinates differ from the admitted coordinate range")
    return {
        "x": x,
        "y": y,
        "mask": np.asarray(geometry.pupil_mask, dtype=bool),
        "record": {
            "source": "native Shack-Hartmann geometry of the plan's configuration (x_m, y_m), as admitted before production",
            "convention": spacing["convention"],
            "x_axis": "columns, metres; y_axis: rows, metres",
            "x_range_m": spacing["x_range_m"],
            "y_range_m": spacing["y_range_m"],
            "spacing_xy_m": spacing["from_coordinates_xy_m"],
            "x_m_sha256": _array_sha(x),
            "y_m_sha256": _array_sha(y),
            "geometry_hash": geometry.geometry_hash,
        },
    }


def bind_case(series_dir: Path, plan: Dict[str, Any], case_id: str) -> Dict[str, Any]:
    attempt = long_series.completed_attempt(series_dir, case_id)
    _require(attempt is not None, f"{case_id} has no completed attempt")
    record_bytes = (attempt / "case_record.json").read_bytes()
    record = json.loads(record_bytes.decode("utf-8"))
    case = long_series.plan_case(plan, case_id)
    _require(record["series_id"] == plan["series_id"] and record["case"]["case_id"] == case_id and record["config_hash"] == case["config_hash"], f"{case_id}: the case record names another series, case or configuration")
    _require(record["identities"]["production_sha256"] == plan["identities"]["production"]["sha256"], f"{case_id}: produced by another producer identity")
    files = {}
    for name in (RESIDUAL_STACK, "mean_psfs.npz"):
        item = record["files"][name]
        path = attempt / name
        digest = long_series.sha256_file_chunked(path)
        _require(path.stat().st_size == item["bytes"] and digest == item["sha256"], f"{case_id}/{name}: size or SHA-256 differs from the case record")
        files[name] = {"bytes": item["bytes"], "sha256": digest}
    with np.load(attempt / "mean_psfs.npz", allow_pickle=False) as data:
        mask = np.array(data["pupil_mask"], dtype=bool)
    return {"attempt": attempt, "record": record, "record_sha256": identity.sha256_bytes(record_bytes), "files": files, "mask": mask}


def detilted_rms(bound: Dict[str, Any], coordinates: Dict[str, Any]) -> Dict[str, Any]:
    """The plane fit of every archived residual map, with its binding checks."""

    record = bound["record"]
    frames = record["observer"]["frames"]
    mask = bound["mask"]
    _require(np.array_equal(mask, coordinates["mask"]), "the saved pupil mask differs from the geometry's pupil mask")
    stack = np.load(bound["attempt"] / RESIDUAL_STACK, mmap_mode="r")
    count = len(frames["frame_index"])
    _require(stack.dtype == np.float64 and stack.shape == (count, *mask.shape) and frames["frame_index"] == list(range(count)), "the residual archive does not hold one float64 map per recorded frame")
    samples = int(np.count_nonzero(mask))
    design = np.column_stack([np.ones(samples), coordinates["x"][mask], coordinates["y"][mask]])
    values = np.empty((count, samples), dtype=np.float64)
    for k in range(count):
        frame = np.ascontiguousarray(stack[k], dtype=np.float64)
        _require(hashlib.sha256(frame.tobytes()).hexdigest() == frames["residual_sha256"][k], f"frame {k}: the archived residual map is not the one the observer recorded for this frame")
        inside = frame[mask]
        _require(bool(np.all(np.isfinite(inside))), f"frame {k}: a non-finite residual value lies inside the pupil")
        _require(not bool(np.any(np.isfinite(frame[~mask]))), f"frame {k}: the residual map has values outside the saved pupil")
        values[k] = inside
    del stack
    coefficients, _, rank, _ = np.linalg.lstsq(design, values.T, rcond=None)
    _require(rank == 3, "the pupil samples do not determine a plane")
    fitted = (design @ coefficients).T
    detilted = np.sqrt(np.mean((values - fitted) ** 2, axis=1))
    centred = values - values.mean(axis=1, keepdims=True)
    total = np.sqrt(np.mean(centred ** 2, axis=1))
    recorded = np.asarray(frames["residual_rms_m"], dtype=np.float64)
    tolerance = protocol.TOLERANCES["rms_m"]
    difference = np.abs(total - recorded)
    _require(bool(np.all(difference <= tolerance["atol"] + tolerance["rtol"] * recorded)), "the recomputed piston-removed RMS differs from the recorded total residual RMS")
    _require(bool(np.all(detilted <= total * (1.0 + 1e-12))), "a detilted RMS exceeds its piston-removed RMS")
    return {
        "detilted_rms_m": detilted,
        "plane_coefficients": coefficients.T.copy(),
        "total_rms_recomputed_m": total,
        "check": {
            "per_frame_map_digests_match_observer": True,
            "frames": count,
            "pupil_samples": samples,
            "total_residual_max_abs_difference_m": float(difference.max()),
            "tolerance": tolerance,
        },
    }


def _verified_member(base: Path, ref: Dict[str, Any], defining: str) -> bytes:
    path = (base / Path(defining).parent / ref["href"]).resolve()
    data = path.read_bytes()
    _require(len(data) == ref["bytes"] and identity.sha256_bytes(data) == ref["sha256"], f"{ref['href']} differs from its recorded size or SHA-256")
    return data


def build(series_dir: Path, plan: Dict[str, Any], dataset_dir: Path, manifest_bytes: bytes, web_dir: Path, derived_root: Path) -> Dict[str, Any]:
    """Write the derivative for the dataset bundle in ``dataset_dir``; returns its entry block."""

    series_dir = Path(series_dir)
    manifest = json.loads(manifest_bytes.decode("utf-8"))
    dataset_id = manifest["dataset_id"]
    _require(manifest["series"]["series_id"] == plan["series_id"], "the dataset was not made from this series")
    manifest_sha = identity.sha256_bytes(manifest_bytes)
    time_domain = manifest["time_domain"]
    start, stop = time_domain["analysis_window"]
    coordinates = pupil_coordinates(plan)
    code = code_identity()
    key = identity.sha256_bytes(identity.canonical_json_bytes({"dataset": dataset_id, "manifest": manifest_sha, "code": code["sha256"], "revision": REVISION}))[:12]
    derived_id = f"rms-{plan['series_id'].removeprefix('series-')}-d{key}"
    web_base = Path(web_dir) / "derived" / derived_id
    out_base = Path(derived_root) / dataset_id / derived_id
    _require(not web_base.exists() and not out_base.exists(), f"{derived_id} exists; a derivative is never overwritten")

    computed: Dict[str, Any] = {}
    for case_id in manifest["cases"]:
        bound = bind_case(series_dir, plan, case_id)
        case_bytes = _verified_member(Path(dataset_dir), manifest["cases"][case_id]["case"], "manifest.json")
        case = json.loads(case_bytes.decode("utf-8"))
        defining = manifest["cases"][case_id]["case"]["href"]
        metrics_ref = case["members"]["metrics"]
        metrics = json.loads(_verified_member(Path(dataset_dir), metrics_ref, defining).decode("utf-8"))
        result = detilted_rms(bound, coordinates)
        per_frame = metrics["per_frame"]
        _require(per_frame["frame_index"] == list(range(len(result["detilted_rms_m"]))), f"{case_id}: the metrics do not cover the same frames")
        computed[case_id] = {"bound": bound, "result": result, "metrics_ref": metrics_ref, "per_frame": per_frame, "label": manifest["cases"][case_id]["label"]}

    out_base.mkdir(parents=True)
    members: List[Dict[str, Any]] = []
    cases_out: Dict[str, Any] = {}
    window_means: Dict[str, Any] = {}
    for case_id, item in computed.items():
        result, bound, per_frame = item["result"], item["bound"], item["per_frame"]
        np.savez(
            out_base / f"{case_id}.npz",
            detilted_rms_m=result["detilted_rms_m"],
            plane_coefficients=result["plane_coefficients"],
            total_rms_recomputed_m=result["total_rms_recomputed_m"],
        )
        detilted_nm = (result["detilted_rms_m"] * 1e9).tolist()
        _require(all(math.isfinite(value) for value in detilted_nm), f"{case_id}: non-finite diagnostic")
        means = {
            "window": [start, stop],
            "count": stop - start,
            "interval_s": [start * time_domain["frame_period_s"], stop * time_domain["frame_period_s"]],
            "label": f"Mean of per-frame RMS, {start * time_domain['frame_period_s']:.3f}–{stop * time_domain['frame_period_s']:.3f} s, {stop - start} frames",
            "definition": "arithmetic mean of the per-frame RMS values of frames in the window; a temporal mean of scalars, not the RMS of an averaged wavefront and not inferred from the average PSF",
            "atmosphere_rms_nm": float(np.mean(np.asarray(per_frame["atmosphere_rms_nm"]["values"][start:stop], dtype=np.float64))),
            "residual_rms_nm": float(np.mean(np.asarray(per_frame["residual_rms_nm"]["values"][start:stop], dtype=np.float64))),
            "detilted_residual_rms_nm": float(np.mean(np.asarray(detilted_nm[start:stop], dtype=np.float64))),
        }
        window_means[case_id] = means
        relative = f"cases/{case_id}/rms.json"
        payload = {
            "schema": SCHEMA_CASE,
            "case_id": case_id,
            "label": item["label"],
            "frames": len(detilted_nm),
            "frame_period_s": time_domain["frame_period_s"],
            "frame_mapping": DEFINITION["frame_mapping"],
            "units": UNITS,
            "detilted_residual_rms_nm": {"values": detilted_nm, "null_reasons": {}},
            "window_means": means,
            "companions": {"metrics_sha256": item["metrics_ref"]["sha256"], "series": ["atmosphere_rms_nm", "residual_rms_nm"], "rule": "the atmosphere and total residual RMS are the dataset metrics member with this SHA-256"},
            "source": {
                "series_id": plan["series_id"],
                "attempt": bound["attempt"].name,
                "case_record_sha256": bound["record_sha256"],
                "residual_stack": {"path": f"outputs/ao_explorer_1s/{plan['series_id']}/cases/{case_id}/{bound['attempt'].name}/{RESIDUAL_STACK}", **bound["files"][RESIDUAL_STACK]},
                "pupil_mask": {"file": "mean_psfs.npz", "array": "pupil_mask", **bound["files"]["mean_psfs.npz"], "array_sha256": _array_sha(bound["mask"])},
                "check": result["check"],
            },
            "derived_arrays": {"file": f"{case_id}.npz", "location": f"outputs/ao_explorer_1s_derived/{dataset_id}/{derived_id}/", "arrays": ["detilted_rms_m", "plane_coefficients (a [m], b [m/m], c [m/m] per frame)", "total_rms_recomputed_m"]},
        }
        data = _json_bytes(payload)
        path = web_base / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("xb") as handle:
            handle.write(data)
        member = {"path": relative, "bytes": len(data), "sha256": identity.sha256_bytes(data), "media_type": "application/json", "role": "rms_diagnostics"}
        members.append(member)
        cases_out[case_id] = {"label": item["label"], "diagnostics": {"href": relative, "bytes": member["bytes"], "sha256": member["sha256"], "media_type": "application/json"}}

    import scipy

    derived_manifest = {
        "schema": SCHEMA_MANIFEST,
        "derived_id": derived_id,
        "title": "Per-frame residual RMS after tip/tilt removal",
        "revision": REVISION,
        "parent": {
            "dataset_id": dataset_id,
            "manifest_sha256": manifest_sha,
            "series_id": plan["series_id"],
            "plan_sha256": identity.sha256_file(series_dir / long_series.PLAN_NAME),
            "relation": "additive scalar derivative of the saved residual maps; the dataset, its PSFs, its images and its galaxy derivative are unchanged",
        },
        "definition": DEFINITION,
        "coordinates": coordinates["record"],
        "time_domain": {key: time_domain[key] for key in ("frames", "frame_period_s", "physical_interval_s", "analysis_window", "analysis_count")},
        "cases": cases_out,
        "window_means": window_means,
        "code_identity": code,
        "environment": {"python": platform.python_version(), "numpy": np.__version__, "scipy": scipy.__version__, "machine": platform.machine()},
        "members": sorted(members, key=lambda member: member["path"]),
    }
    derived_bytes = _json_bytes(derived_manifest)
    (web_base / "manifest.json").write_bytes(derived_bytes)
    block = {
        "schema": SCHEMA_ENTRY,
        "derived_id": derived_id,
        "manifest": f"../derived/{derived_id}/manifest.json",
        "manifest_bytes": len(derived_bytes),
        "manifest_sha256": identity.sha256_bytes(derived_bytes),
    }
    producer.write_json(out_base / "record.json", {
        "schema": "ao-explorer.rms-diagnostics-record.v1",
        **block,
        "dataset_id": dataset_id,
        "dataset_manifest_sha256": manifest_sha,
        "definition": DEFINITION,
        "coordinates": coordinates["record"],
        "window_means": window_means,
        "checks": {case_id: item["result"]["check"] for case_id, item in computed.items()},
        "arrays_sha256": {case_id: long_series.sha256_file_chunked(out_base / f"{case_id}.npz") for case_id in computed},
        "web_bytes": sum(member["bytes"] for member in members) + len(derived_bytes),
        "code_identity": code,
        "created_utc": producer.utc_now(),
    })
    return block


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--web-dir", type=Path, required=True)
    parser.add_argument("--series-dir", type=Path, required=True)
    parser.add_argument("--derived-root", type=Path, required=True)
    arguments = parser.parse_args(argv)
    try:
        entry_path = arguments.web_dir / "data" / "current.json"
        entry = json.loads(entry_path.read_bytes().decode("utf-8"))
        dataset_dir = entry_path.parent / entry["dataset_id"]
        manifest_bytes = (entry_path.parent / entry["manifest"]).read_bytes()
        _require(len(manifest_bytes) == entry["manifest_bytes"] and identity.sha256_bytes(manifest_bytes) == entry["manifest_sha256"], "the active dataset manifest differs from its entry")
        _require("diagnostics" not in entry, "the active entry already names RMS diagnostics")
        plan = long_series.load_plan(arguments.series_dir)
        block = build(arguments.series_dir, plan, dataset_dir, manifest_bytes, arguments.web_dir, arguments.derived_root)
        entry["diagnostics"] = block
        entry_path.write_text(json.dumps(entry, indent=1) + "\n", encoding="utf-8")
    except (DiagnosticsError, long_series.LongSeriesError) as exc:
        print(json.dumps({"written": False, "error": str(exc)}))
        return 2
    print(json.dumps({"written": True, **block}, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
