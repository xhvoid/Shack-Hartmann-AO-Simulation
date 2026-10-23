"""Offline validator of the AO Simulation Explorer web bundle.

Usage::

    python scripts/ao_explorer/validate.py --web-dir web/ao-explorer [--series-dir DIR] [--record]

Structural mode (always): the entry, the manifest and every member are
checked for size and SHA-256; every JSON reference must resolve, relative to
the JSON that defines it, to a listed member with the same size and digest;
no file in the dataset directory may be unlisted; JSON may not contain NaN or
Infinity; the case/metrics/observation/scene/display/research semantics are
checked (frame counts, windows, movie indices from the frozen protocol, shared
colour limits and scene, image units, observation parents -- wavelength,
residual field, normalization, grid digests and propagator against the scene
-- and flux bookkeeping, a recorded reason for every missing value, summary
values recomputed from the per-frame rows, eight research groups with
quantitative content, byte-identical source copies and source-bound extracts),
and the page code's content build must equal the one the entry records.

Raw-evidence mode (``--series-dir``): additionally binds every case to its
retained job record and files, checks each observation parent's array digest
against ``mean_psfs.npz``, and decodes atlas tiles at frames 0, 40 and 179 to
confirm they equal the declared colour mapping of the raw ``movie.npz`` maps
(no axis flip, no hidden normalization).

``--record`` writes the external validation record (bound to the manifest's
SHA-256; the manifest never hashes itself).  Exit status 0 means every check
passed; failures are listed.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path, PurePosixPath
import sys
from typing import Any, Dict, List, Optional

import protocol
import site_build


SCIENCE_WAVELENGTH_M = protocol.SCIENCE_WAVELENGTH_M
IMAGE_UNITS = {
    "atmosphere": "nm OPD",
    "correction": "nm OPD-equivalent (not mirror surface height)",
    "residual": "nm OPD",
    "psf_uncorrected": "log10 relative intensity",
    "psf_corrected": "log10 relative intensity",
}
PARENT_FIELDS = {"corrected": "pre_update_residual_opd_m", "uncorrected": "atmosphere_opd_m (zero-DM optical counterfactual)"}
PARENT_NORMALIZATION = "unit total flux over the complete uncropped propagator grid"
PARENT_SAMPLING = "frame-start instantaneous snapshots; not a finite-shutter sub-frame integration"
PER_FRAME_SERIES = (
    "atmosphere_rms_nm",
    "residual_rms_nm",
    "peak_strehl_uncorrected",
    "peak_strehl_corrected",
    "valid_measurement_fraction",
    "valid_subaperture_fraction",
    "dm_saturation_fraction",
)


class ValidationError(Exception):
    pass


def _wavelength(value: Any) -> str:
    """A recorded wavelength for a check message: numbers in metres, anything else as recorded."""

    return f"{value!r} m" if isinstance(value, (int, float)) and not isinstance(value, bool) else f"{value!r} (not a number)"


def _strict_json(data: bytes, label: str) -> Any:
    def reject(value: str) -> Any:
        raise ValidationError(f"{label}: non-finite JSON constant {value}")

    try:
        return json.loads(data.decode("utf-8"), parse_constant=reject)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValidationError(f"{label}: invalid JSON ({exc})") from exc


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _png_size(data: bytes) -> List[int]:
    if data[:8] != b"\x89PNG\r\n\x1a\n":
        raise ValidationError("not a PNG")
    return [int.from_bytes(data[16:20], "big"), int.from_bytes(data[20:24], "big")]


class Checker:
    def __init__(self, web_dir: Path) -> None:
        self.web_dir = Path(web_dir)
        self.failures: List[str] = []
        self.passed: List[str] = []
        self.members: Dict[str, Dict[str, Any]] = {}
        self.referenced: set = set()
        self.base: Optional[Path] = None
        self.propagators: set = set()
        self.accumulators: set = set()

    def check(self, condition: bool, message: str) -> bool:
        (self.passed if condition else self.failures).append(message)
        return condition

    # Bundle structure -------------------------------------------------------

    def load_entry(self) -> Dict[str, Any]:
        entry_path = self.web_dir / "data" / "current.json"
        entry = _strict_json(entry_path.read_bytes(), "current.json")
        if entry.get("schema") != "ao-explorer.entry.v1":
            raise ValidationError("unsupported entry schema")
        manifest_path = entry_path.parent / entry["manifest"]
        data = manifest_path.read_bytes()
        if len(data) != entry["manifest_bytes"] or _sha(data) != entry["manifest_sha256"]:
            raise ValidationError("the manifest does not match the entry's size/SHA-256")
        manifest = _strict_json(data, "manifest.json")
        if manifest.get("schema") != "ao-explorer.manifest.v1" or manifest.get("dataset_id") != entry["dataset_id"]:
            raise ValidationError("unsupported manifest schema or dataset mismatch")
        self.base = manifest_path.parent
        self.entry = entry
        self.manifest = manifest
        self.manifest_sha256 = entry["manifest_sha256"]
        return manifest

    def verify_members(self) -> None:
        assert self.base is not None
        for item in self.manifest["members"]:
            path = self.base / item["path"]
            if not path.is_file():
                self.check(False, f"member {item['path']} is missing")
                continue
            data = path.read_bytes()
            ok = len(data) == item["bytes"] and _sha(data) == item["sha256"]
            self.check(ok, f"member {item['path']} size and SHA-256")
            self.members[item["path"]] = {**item, "data": data}
        listed = set(self.members) | {"manifest.json"}
        on_disk = {p.relative_to(self.base).as_posix() for p in self.base.rglob("*") if p.is_file()}
        self.check(on_disk <= listed, f"no unlisted files in the dataset directory ({sorted(on_disk - listed)[:5]})")
        siblings = [p.name for p in self.base.parent.iterdir() if p.is_dir()]
        self.check(siblings == [self.base.name], f"exactly one dataset directory under data/ ({siblings})")

    def json_member(self, relative: str) -> Any:
        item = self.members.get(relative)
        if item is None:
            raise ValidationError(f"{relative} is not a listed member")
        if item["media_type"] != "application/json":
            raise ValidationError(f"{relative} is not JSON")
        return _strict_json(item["data"], relative)

    def resolve(self, ref: Dict[str, Any], defining: str) -> str:
        href = ref["href"]
        if "://" in href or href.startswith("/"):
            raise ValidationError(f"{defining}: non-relative reference {href}")
        parts = list(PurePosixPath(defining).parent.parts)
        for part in PurePosixPath(href).parts:
            if part == "..":
                if not parts:
                    raise ValidationError(f"{defining}: {href} leaves the dataset")
                parts.pop()
            elif part != ".":
                parts.append(part)
        target = "/".join(parts)
        item = self.members.get(target)
        ok = item is not None and item["bytes"] == ref["bytes"] and item["sha256"] == ref["sha256"] and item["media_type"] == ref.get("media_type", item["media_type"])
        self.check(ok, f"{defining}: reference {href} resolves to a matching member")
        self.referenced.add(target)
        return target

    def walk_refs(self, value: Any, defining: str) -> None:
        if isinstance(value, dict):
            if set(value) >= {"href", "bytes", "sha256"}:
                self.resolve(value, defining)
            for item in value.values():
                self.walk_refs(item, defining)
        elif isinstance(value, list):
            for item in value:
                self.walk_refs(item, defining)

    # Semantics ------------------------------------------------------------------

    def check_manifest(self) -> None:
        m = self.manifest
        self.check(m["default_case"] == protocol.DEFAULT_CASE, "default case is the baseline")
        self.check(sorted(m["cases"]) == sorted(case["id"] for case in protocol.CASES), "manifest lists exactly the eight frozen cases")
        self.check(m["groups"] == protocol.GROUPS, "scenario groups equal the frozen groups (no extra combinations)")
        self.walk_refs({key: m[key] for key in ("cases", "scene", "display", "diagnostics", "results")}, "manifest.json")

    def check_scene(self) -> Dict[str, Any]:
        scene_export = self.json_member("scene/scene.json")
        self.walk_refs(scene_export, "scene/scene.json")
        scene = scene_export["scene"]
        weights = [source["weight"] for source in scene["sources"]]
        self.check(scene["schema"] == protocol.SCENE_SCHEMA, "scene schema")
        self.check(abs(scene["total_flux"] - 1.0) <= 1e-15 and abs(weights[0] - 2 / 3) <= 1e-15 and abs(weights[1] - 1 / 3) <= 1e-15, "scene weights 2/3, 1/3 and total flux 1")
        primary, secondary = scene["sources"]
        self.check(primary["angle_xy_rad"] == [0.0, 0.0], "primary at exact angular zero")
        self.check(secondary["index_yx"][0] == primary["index_yx"][0] and secondary["index_yx"][1] - primary["index_yx"][1] == protocol.SCENE_SECONDARY_OFFSET_X_CELLS, "secondary six native x cells towards +x at the same y")
        self.check(secondary["angle_xy_rad"][0] > 0.0 and secondary["angle_xy_rad"][1] == 0.0, "secondary at positive x angle")
        self.check(scene["wavelength_m"] == SCIENCE_WAVELENGTH_M, f"scene wavelength {_wavelength(scene['wavelength_m'])} is the science wavelength {_wavelength(SCIENCE_WAVELENGTH_M)}")
        return scene

    def check_display(self) -> Dict[str, Any]:
        display = self.json_member("display.json")
        self.check(len(display["opd"]["lut_rgb_hex"]) == 256 and len(display["psf"]["lut_rgb_hex"]) == 256, "display lookup tables have 256 entries")
        return display

    def check_case(self, case_id: str, scene: Dict[str, Any], display: Dict[str, Any]) -> Dict[str, Any]:
        ref_path = self.resolve(self.manifest["cases"][case_id]["case"], "manifest.json")
        case = self.json_member(ref_path)
        prefix = str(PurePosixPath(ref_path).parent)
        self.walk_refs(case, ref_path)
        t = case["time_domain"]
        movie = list(protocol.movie_indices())
        self.check(case["schema"] == "ao-explorer.case.v1" and case["case_id"] == case_id, f"{case_id}: case schema and id")
        self.check(t["frames"] == protocol.PRODUCTION_FRAMES and t["burn_in_frames"] == protocol.PRODUCTION_BURN_IN, f"{case_id}: 180 frames, burn-in 40")
        self.check(t["analysis_window"] == [40, 180] and t["analysis_count"] == 140, f"{case_id}: analysis window [40, 180), 140 samples")
        self.check(t["movie_indices"] == movie, f"{case_id}: movie indices equal the frozen rule (40 unique, incl. 0, 40, 179)")
        self.check(all(abs(time - index / 1000.0) < 1e-12 for time, index in zip(t["movie_times_s"], movie)), f"{case_id}: movie times are the frame starts")
        limits = None
        for key, unit in IMAGE_UNITS.items():
            self.check(case["images"][key].get("unit") == unit, f"{case_id}: {key} unit {case['images'][key].get('unit')!r} is the supported {unit!r}")
        psf_scale = display["psf"]
        for key in ("psf_uncorrected", "psf_corrected", "psf_average_uncorrected", "psf_average_corrected"):
            scale = case["images"][key].get("scale", {})
            self.check(all(scale.get(name) == psf_scale[name] for name in ("mapping", "ideal_peak_cell_flux", "normalization", "colormap")), f"{case_id}: {key} uses the common intensity display scale")
        self.check(case["effective_parameters"].get("explorer_science_wavelength_m") == SCIENCE_WAVELENGTH_M, f"{case_id}: science wavelength {_wavelength(case['effective_parameters'].get('explorer_science_wavelength_m'))} is {_wavelength(SCIENCE_WAVELENGTH_M)}")
        for key in ("atmosphere", "correction", "residual", "psf_uncorrected", "psf_corrected"):
            image = case["images"][key]
            atlas = self.members[self.resolve(image["atlas"], ref_path)]
            width, height = _png_size(atlas["data"])
            inside = all(x >= 0 and y >= 0 and x + w <= width and y + h <= height for x, y, w, h in image["rectangles_xywh"])
            self.check(len(image["rectangles_xywh"]) == 40 and inside and image["frame_indices"] == movie, f"{case_id}: {key} atlas tiles cover the 40 movie frames inside the PNG")
            if key in ("atmosphere", "correction", "residual"):
                piston = image.get("display_piston_nm")
                self.check(isinstance(piston, list) and len(piston) == 40 and all(isinstance(v, float) and math.isfinite(v) for v in piston) and "piston" in image, f"{case_id}: {key} records the display piston per movie frame")
                if limits is None:
                    limits = image["color_limits_nm"]
                self.check(image["color_limits_nm"] == limits and limits[0] == -limits[1] and abs(limits[1] - display["opd"]["limit_m"] * 1e9) < 1e-6, f"{case_id}: {key} uses the common symmetric OPD limits")
        for key in ("psf_average_uncorrected", "psf_average_corrected"):
            self.check(case["images"][key]["sample_count"] == 140, f"{case_id}: {key} is the 140-sample average")
        metrics = self.json_member(f"{prefix}/metrics.json")
        pf = metrics["per_frame"]
        self.check(pf["frame_index"] == list(range(180)), f"{case_id}: metrics cover frames 0-179")
        for key in PER_FRAME_SERIES:
            values = pf[key]["values"]
            self.check(len(values) == 180 and all(v is None or math.isfinite(v) for v in values), f"{case_id}: {key} has 180 finite-or-null values")
            reasons = pf[key]["null_reasons"]
            nulls = {str(index) for index, value in enumerate(values) if value is None}
            self.check(set(reasons) == nulls and all(isinstance(reason, str) and reason.strip() for reason in reasons.values()), f"{case_id}: {key} has a recorded reason for every missing value, and only for those")
        summary = metrics["summary"]
        window = pf["residual_rms_nm"]["values"][40:]
        self.check(summary["window"] == [40, 180] and summary["sample_count"] == 140, f"{case_id}: summary window")
        recomputed = sum(window) / len(window)
        self.check(abs(recomputed - summary["mean_residual_rms_nm"]) <= 1e-9 * max(1.0, recomputed), f"{case_id}: mean residual recomputed from rows")
        rms = math.sqrt(sum(v * v for v in window) / len(window))
        self.check(abs(rms - summary["root_mean_square_residual_nm"]) <= 1e-9 * max(1.0, rms), f"{case_id}: root-mean-square residual recomputed from rows")
        strehl = pf["peak_strehl_corrected"]["values"][40:]
        self.check(abs(sum(strehl) / 140 - summary["mean_instantaneous_peak_strehl_corrected"]) <= 1e-12, f"{case_id}: mean instantaneous Strehl recomputed from rows")
        self.check(summary == self.manifest["summaries"][case_id], f"{case_id}: manifest summary equals the case metrics summary")
        observation = self.json_member(f"{prefix}/observation.json")
        self.walk_refs(observation, f"{prefix}/observation.json")
        self.check(observation["scene_id"] == scene["scene_id"] and observation["scene_grid_id"] == scene["grid_id"], f"{case_id}: observation uses the shared scene and grid")
        self.check(observation["window"] == [40, 180] and observation["sample_count"] == 140 and observation["weights"] == "equal", f"{case_id}: observation is the [40, 180) equal-weight average")
        self.check("no additional science-camera noise" in observation["label"], f"{case_id}: observation label discloses no science-camera noise")
        code = observation.get("observation_code_identity") or {}
        self.check(len(code.get("sha256", "")) == 64 and set(code.get("files", {})) == {"binary_scene.py", "render.py"}, f"{case_id}: observation binds the identity of the code that computed it")
        for role in ("uncorrected", "corrected"):
            r = observation["roles"][role]
            parent = r["parent"]
            self.check(parent["role"] == role and parent["window"] == [40, 180] and parent["sample_count"] == 140 and parent["stride"] == 1, f"{case_id}: {role} parent is the full 140-frame mean")
            self.check(parent["field"] == PARENT_FIELDS[role], f"{case_id}: {role} parent field {parent['field']!r} is {PARENT_FIELDS[role]!r}")
            self.check(parent["recentering"] == "none" and parent["coaddition"] == "intensity", f"{case_id}: {role} parent: intensity co-addition, no recentring")
            self.check(parent["wavelength_m"] == SCIENCE_WAVELENGTH_M == scene["wavelength_m"], f"{case_id}: {role} parent wavelength {_wavelength(parent['wavelength_m'])} is the scene's {_wavelength(scene['wavelength_m'])}")
            self.check(parent["normalization"] == PARENT_NORMALIZATION and abs(parent["total_flux"] - 1.0) <= protocol.TOLERANCES["unit_flux"]["atol"], f"{case_id}: {role} parent normalization {parent['normalization']!r} is unit total flux")
            self.check(parent["weights"] == "equal" and parent["sampling"] == PARENT_SAMPLING, f"{case_id}: {role} parent is an equal-weight frame-start snapshot average")
            grid = scene["grid"]
            self.check(
                parent["x_angle_rad_sha256"] == grid["x_angle_rad_sha256"] and parent["y_angle_rad_sha256"] == grid["y_angle_rad_sha256"] and parent["shape"] == grid["shape_yx"],
                f"{case_id}: {role} parent axes and shape equal the scene grid",
            )
            self.propagators.add(parent["propagator_config_hash"])
            self.accumulators.add(parent["accumulator_config_hash"])
            scale = r.get("display", {}).get("scale", {})
            self.check(all(scale.get(name) == psf_scale[name] for name in ("mapping", "ideal_peak_cell_flux", "normalization")), f"{case_id}: {role} observation uses the common intensity display scale")
            self.check(abs(r["full_flux"] - r["expected_full_flux"]) <= protocol.TOLERANCES["convolution_flux"]["atol"], f"{case_id}: {role} full flux equals scene x kernel flux")
            self.check(0.0 < r["retained_fraction"] <= 1.0 and abs(r["retained_fraction"] - r["cropped_flux"] / r["full_flux"]) < 1e-15, f"{case_id}: {role} crop flux bookkeeping")
            self.check(r["crop_slices_yx"] == [[78, 234], [78, 234]] and r["full_shape_yx"] == [311, 311], f"{case_id}: {role} crop slices derived from the coordinates")
        return {"case": case, "metrics": metrics, "observation": observation, "prefix": prefix}

    def check_results(self, *, repo_root: Optional[Path]) -> Dict[str, Any]:
        results = self.json_member("research/results.json")
        self.walk_refs(results, "research/results.json")
        groups = results["groups"]
        self.check([g["id"] for g in groups] == [f"R{i}" for i in range(1, 9)], "Research Results has groups R1-R8 in order")
        sources_read = {source["path"]: source["sha256"] for source in results["sources_read"]}
        historical = {(source["commit"], source["path"]): source["sha256"] for source in results.get("historical_sources_read", [])}
        repository = results.get("source_repository", {})
        self.check(repository.get("commit") == results["source_sha"] and str(repository.get("url", "")).startswith("https://github.com/"), "research source links name the source commit's repository")
        for group in groups:
            self.check(bool(group["tables"] or group["charts"]) and bool(group["key_values"]), f"{group['id']}: quantitative content (tables/charts and key values)")
            self.check(bool(group["downloads"]), f"{group['id']}: downloadable compact evidence")
            self.check_nulls(group)
            for source in group.get("context_sources", []):
                expected = historical.get((source["commit"], source["path"])) if "commit" in source else sources_read.get(source["path"])
                self.check(expected == source["sha256"], f"{group['id']}: context source {source['path']} {source.get('commit', '')[:8]} is a recorded source read")
            self.check(bool(group["takeaway"]) and bool(group["limitations"]), f"{group['id']}: takeaway and limitations present")
            self.check(set(group["status"]) <= set(results["status_vocabulary"]), f"{group['id']}: evidence status uses the declared vocabulary")
            for figure in group["figures"]:
                item = self.members[self.resolve(figure["asset"], "research/results.json")]
                if figure["byte_identical_copy"] and figure["kind"] == "source_figure":
                    self.check(item["sha256"] == figure["source"]["sha256"], f"{group['id']}: figure {figure['source']['path']} is a byte-identical copy")
            for download in group["downloads"]:
                item = self.members[self.resolve(download["asset"], "research/results.json")]
                if download.get("kind") == "byte_identical_copy":
                    self.check(item["sha256"] == download["source"]["sha256"], f"{group['id']}: download {download['source']['path']} is a byte-identical copy")
                elif download.get("kind") == "source_bound_extract":
                    self.check_extract(group["id"], item, download, results, sources_read, repo_root)
                else:
                    self.check(False, f"{group['id']}: download {download.get('label')} has an unknown kind {download.get('kind')!r}")
        if repo_root is not None:
            for source in results["sources_read"]:
                path = repo_root / source["path"]
                self.check(path.is_file() and _sha(path.read_bytes()) == source["sha256"], f"research source {source['path']} unchanged in this tree")
            if (repo_root / ".git").exists():
                import subprocess

                for source in results.get("historical_sources_read", []):
                    shown = subprocess.run(["git", "show", f"{source['commit']}:{source['path']}"], cwd=repo_root, capture_output=True)
                    self.check(shown.returncode == 0 and _sha(shown.stdout) == source["sha256"], f"historical source {source['path']} at {source['commit'][:8]} has its recorded digest")
        r4 = groups[3]
        fits = {row["scale"]: row for row in next(t for t in r4["tables"] if t["id"] == "r4-noise-fit")["rows"]}
        self.check(fits["12 m"]["verdict_unscaled_two_se"] == "fail", "R4 keeps the failed 12 m inverse-photon test")
        definition = r4["context"].get("isolated_noise_variance", "")
        self.check("noise_variance_m2" in definition and "not the difference of the two arms' mean squares" in definition, "R4 defines dV as the paired residual-map difference (noise_variance_m2), not a difference of mean squares")
        for label, row in r4["computed_checks"]["dv_definition"].items():
            self.check(math.isclose(row["plotted_dv_mean_nm2"], row["seed_mean_noise_variance_nm2"], rel_tol=1e-12), f"R4 {label}: plotted dV is the seed mean of noise_variance_m2")
        r5 = groups[4]
        values = [row["residual_nm"] for row in next(t for t in r5["tables"] if t["id"] == "r5-s2")["rows"] if str(row.get("record", "")).startswith("S2")]
        mean = sum(values) / len(values)
        sd = math.sqrt(sum((v - mean) ** 2 for v in values) / (len(values) - 1))
        self.check(len(values) == 10 and abs(mean - 173.5895) < 5e-5 and abs(sd - 0.9414) < 5e-5, "R5 S2 mean and sample SD recomputed from the ten rows")
        return results

    def check_nulls(self, group: Dict[str, Any]) -> None:
        """Every missing table value and chart point carries a non-empty reason."""

        for table in group["tables"]:
            for index, row in enumerate(table["rows"]):
                for column in table["columns"]:
                    if row.get(column["key"]) is None:
                        reason = row.get(f"{column['key']}_null_reason")
                        self.check(isinstance(reason, str) and bool(reason.strip()), f"{group['id']}: {table['id']} row {index} {column['key']} is missing with a recorded reason")
        for chart in group["charts"]:
            missing = {item["x"] for item in chart.get("missing", []) if isinstance(item.get("reason"), str) and item["reason"].strip()}
            for series in chart.get("series", []):
                for point in series["points"]:
                    if any(value is None for value in point):
                        self.check(point[0] in missing, f"{group['id']}: {chart['id']} point at x = {point[0]} is missing with a recorded reason")

    def check_extract(self, group_id: str, item: Dict[str, Any], download: Dict[str, Any], results: Dict[str, Any], sources_read: Dict[str, str], repo_root: Optional[Path]) -> None:
        """A source-bound extract copies saved notebook outputs verbatim, with their digests."""

        extract = _strict_json(item["data"], download["asset"]["href"])
        self.check(extract.get("schema") == "ao-explorer.notebook-output-extract.v1" and extract.get("group") == group_id and extract.get("source_sha") == results["source_sha"], f"{group_id}: extract schema, group and source commit")
        self.check(bool(extract["outputs"]), f"{group_id}: extract holds saved outputs")
        notebooks = {}
        for output in extract["outputs"]:
            self.check(sources_read.get(output["notebook"]) == output["notebook_sha256"], f"{group_id}: extract output {output['cell_id']} names a recorded notebook digest")
            self.check(_sha(output["text"].encode("utf-8")) == output["text_sha256"], f"{group_id}: extract output {output['cell_id']} text matches its digest")
        for line in extract["configuration"]:
            self.check(sources_read.get(line["path"]) == line["sha256"], f"{group_id}: extract configuration {line['name']} names a recorded notebook digest")
        self.check(sorted(source["path"] for source in download["sources"]) == sorted({output["notebook"] for output in extract["outputs"]} | {line["path"] for line in extract["configuration"]}), f"{group_id}: extract download lists exactly its notebooks")
        if repo_root is None:
            return
        # Re-read the saved outputs from the notebooks themselves (the source
        # check above binds the working tree to the frozen source).
        for output in extract["outputs"] + extract["configuration"]:
            path = output.get("notebook") or output.get("path")
            if path not in notebooks:
                notebook_path = repo_root / path
                present = self.check(notebook_path.is_file(), f"{group_id}: extract notebook {path} is present in this tree")
                notebooks[path] = json.loads(notebook_path.read_text(encoding="utf-8")) if present else None
        for output in extract["outputs"]:
            if notebooks[output["notebook"]] is None:
                continue
            cells = notebooks[output["notebook"]]["cells"]
            cell = cells[output["cell_index"]]
            stored = cell.get("outputs", [])[output["output_index"]]
            text = "".join(stored["text"]) if output["mime"].startswith("stream:") else "".join(stored.get("data", {}).get(output["mime"], []))
            self.check(cell.get("id") == output["cell_id"] and text == output["text"], f"{group_id}: extract output {output['cell_id']}/{output['output_index']} equals the notebook's saved output")
        for line in extract["configuration"]:
            if notebooks[line["path"]] is None:
                continue
            cell = notebooks[line["path"]]["cells"][line["cell_index"]]
            source_lines = "".join(cell["source"]).splitlines()
            self.check(cell.get("id") == line["cell_id"] and source_lines[line["source_line"] - 1].strip() == line["text"], f"{group_id}: extract configuration {line['name']} equals the notebook's line")

    def check_code_build(self) -> None:
        report = site_build.check(self.web_dir)
        self.check(not report["problems"], f"page code build is content-addressed and recorded by the entry ({report['problems'][:3]})")
        self.code_build = report["build"]

    # Raw evidence ----------------------------------------------------------------

    def check_raw(self, series_dir: Path, cases: Dict[str, Dict[str, Any]], display: Dict[str, Any]) -> None:
        import numpy as np
        from PIL import Image
        import io

        def lut_codes(lut_hex):
            return np.array([[int(h[1:3], 16), int(h[3:5], 16), int(h[5:7], 16)] for h in lut_hex], dtype=np.uint8)

        opd_lut = lut_codes(display["opd"]["lut_rgb_hex"])
        limit = display["opd"]["limit_m"]
        for case_id, bundle in cases.items():
            provenance = self.json_member(f"{bundle['prefix']}/provenance.json")
            attempt = series_dir / "jobs" / provenance["job_id"] / provenance["attempt"]
            for name, info in provenance["raw_evidence"]["files"].items():
                path = attempt / name
                self.check(path.is_file() and _sha(path.read_bytes()) == info["sha256"], f"{case_id}: raw {name} matches its provenance digest")
            with np.load(attempt / "mean_psfs.npz") as data:
                for role, name in (("uncorrected", "mean_psf_uncorrected"), ("corrected", "mean_psf_corrected")):
                    digest = _sha(np.ascontiguousarray(data[name]).tobytes())
                    self.check(digest == bundle["observation"]["roles"][role]["parent"]["array_sha256"], f"{case_id}: {role} observation parent digest equals the retained numeric mean")
                    self.check(list(data["analysis_frames"]) == list(range(40, 180)), f"{case_id}: retained mean covers frames 40-179 (not the movie frames)")
            with np.load(attempt / "movie.npz") as data:
                mask = np.asarray(data["pupil_mask"], dtype=bool)
                indices = list(data["indices"])
                atlas_item = self.members[f"{bundle['prefix']}/atlas-residual.png"]
                atlas = np.asarray(Image.open(io.BytesIO(atlas_item["data"])).convert("RGBA"))
                rects = bundle["case"]["images"]["residual"]["rectangles_xywh"]
                pistons = bundle["case"]["images"]["residual"]["display_piston_nm"]
                for frame in (0, 40, 179):
                    position = indices.index(frame)
                    raw = np.asarray(data["pre_update_residual_opd_m"][position])
                    piston = float(np.mean(raw[mask]))
                    self.check(abs(piston * 1e9 - pistons[position]) <= 1e-9, f"{case_id}: residual display piston at frame {frame} equals the raw pupil mean")
                    values = np.where(mask, raw - piston, 0.0)
                    codes = np.clip(np.floor(np.clip((values + limit) / (2 * limit), 0.0, 1.0) * 255.0 + 0.5), 0, 255).astype(int)
                    expected = opd_lut[codes][::-1]
                    expected_alpha = np.where(mask, 255, 0)[::-1]
                    x, y, w, h = rects[position]
                    tile = atlas[y:y + h, x:x + w]
                    ok = np.array_equal(tile[..., 3], expected_alpha) and np.array_equal(tile[..., :3][expected_alpha > 0], expected[expected_alpha > 0])
                    self.check(ok, f"{case_id}: residual atlas tile at frame {frame} equals the declared mapping of the raw map minus its pupil mean (+y up, no other normalization)")

    def run(self, *, series_dir: Optional[Path], repo_root: Optional[Path]) -> Dict[str, Any]:
        self.load_entry()
        self.verify_members()
        self.check_manifest()
        scene = self.check_scene()
        display = self.check_display()
        cases = {case["id"]: self.check_case(case["id"], scene, display) for case in protocol.CASES}
        self.check(len(self.propagators) == 1 and len(self.accumulators) == 1, "every observation parent comes from one science propagator and accumulator configuration")
        self.check_code_build()
        self.json_member("diagnostics.json")
        diagnostics = self.json_member("diagnostics.json")
        self.check(diagnostics["passivity"]["identical"], "passivity: observed and observer-disabled baseline histories identical")
        self.check_results(repo_root=repo_root)
        for case_id, bundle in cases.items():
            for name in ("metrics.json", "metrics.csv", "config.json", "provenance.json", "observation.json"):
                self.referenced.add(f"{bundle['prefix']}/{name}")
        unreferenced = sorted(set(self.members) - self.referenced - {"diagnostics.json", "display.json", "research/results.json", "scene/scene.json"})
        self.check(not unreferenced, f"every member is referenced ({unreferenced[:5]})")
        if series_dir is not None:
            self.check_raw(series_dir, cases, display)
        return {
            "schema": "ao-explorer.manifest-validation.v1",
            "dataset_id": self.manifest["dataset_id"],
            "manifest_sha256": self.manifest_sha256,
            "member_count": len(self.members),
            "member_bytes": sum(item["bytes"] for item in self.members.values()),
            "checks_passed": len(self.passed),
            "failures": self.failures,
            "raw_evidence_checked": series_dir is not None,
            "code_build": getattr(self, "code_build", None),
            "valid": not self.failures,
        }


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--web-dir", type=Path, required=True)
    parser.add_argument("--series-dir", type=Path)
    parser.add_argument("--repo-root", type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument("--record", action="store_true")
    arguments = parser.parse_args(argv)
    checker = Checker(arguments.web_dir)
    try:
        report = checker.run(series_dir=arguments.series_dir, repo_root=arguments.repo_root)
    except (ValidationError, KeyError, OSError) as exc:
        print(json.dumps({"valid": False, "fatal": f"{type(exc).__name__}: {exc}"}))
        return 2
    if arguments.record:
        target = arguments.web_dir / "validation" / f"manifest-validation-{report['dataset_id']}.json"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(report, indent=1) + "\n", encoding="utf-8")
    print(json.dumps({key: report[key] for key in ("dataset_id", "manifest_sha256", "member_count", "member_bytes", "checks_passed", "valid", "raw_evidence_checked")} | {"failures": report["failures"][:20]}, indent=1))
    return 0 if report["valid"] else 1


if __name__ == "__main__":
    sys.exit(main())
