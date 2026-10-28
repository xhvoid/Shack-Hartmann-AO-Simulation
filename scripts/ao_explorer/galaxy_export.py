"""Focused additive exporter of the observed-template galaxy observations.

Usage::

    python scripts/ao_explorer/galaxy_export.py \\
        --series-dir /abs/path/outputs/ao_explorer_v1/series-2m180-b3e1c66 \\
        --template-fits outputs/ngc1705_inputs/legus_v1/hlsp_legus_hst_uvis_ngc1705_f814w_v1_drc.fits \\
        --quality-flc outputs/ngc1705_inputs/legus_v1_flc_f814w/*_flc.fits \\
        --web-dir web/ao-explorer --output-dir outputs/ao_explorer_galaxy \\
        [--input-manifest FILE_MANIFEST.json]

This is deterministic postprocessing of saved PSFs and one observed image; no
AO trajectory, random number or noise is involved.  For each of the eight
production cases it reads only ``movie.npz`` (the 40 retained instantaneous
PSF pairs), ``mean_psfs.npz`` (the complete 140-frame post-burn-in means
``mean_psf_*``) and ``job_record.json``, plus the frozen ``series_plan.json``.
The originals are opened read-only, hashed from the very bytes that are
parsed, and bound to the digests recorded by the published dataset
(``provenance.json`` raw evidence, the manifest's plan digest, the binary
observation's parent array digests) and, when given, to an input file
manifest.  Any mismatch stops the export before anything is written.

The fixed template ``T`` of ``galaxy_template`` (the observed LEGUS F814W
central region of NGC 1705, at its own angular scale) is convolved with every
retained PSF (``sampled``) and with the two saved mean PSFs (``mean``) by
``galaxy_scene``.  Full-precision arrays go to ``<output-dir>/<derived-id>/``
(outside the site and Git); display images and records go to
``<web-dir>/derived/<derived-id>/`` with their own manifest, which
``data/current.json`` names under ``galaxy``.  The published dataset
directory, its manifest and the binary scene are not touched.  An existing
derived directory is never overwritten.

The display uses one fixed asinh stretch referenced to the brightest template
cell, shared by the template, every sample, both mean images, both roles and
every case; no image is normalized to its own maximum.  Images are 8-bit
indexed PNGs whose palette is the recorded colour table, so a pixel's index is
its display code.  After changing page code, ``site_build.py --write``
restamps the code build.
"""

from __future__ import annotations

import argparse
import io
import json
import math
from pathlib import Path
import platform
import sys
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

import galaxy_scene
import galaxy_template
import identity


SCHEMA_MANIFEST = "ao-explorer.galaxy-manifest.v2"
SCHEMA_SCENE_EXPORT = "ao-explorer.galaxy-scene-export.v2"
SCHEMA_OBSERVATION = "ao-explorer.galaxy-observation.v2"
SCHEMA_ENTRY_REF = "ao-explorer.galaxy-entry.v2"
DISPLAY_REVISION = "ao-explorer.galaxy-display.v2"
CODE_FILES = ("galaxy_template.py", "galaxy_scene.py", "galaxy_export.py", "binary_scene.py", "identity.py")
ATLAS_COLUMNS = 8
DISPLAY_CELLS = 128  # observation crop: the central 128 x 128 cells of the native window (about 7.1 arcsec)
ASINH_SOFTENING = 0.001
COLORBAR_TICKS = [1, 0.1, 0.01, 0.001, 0]
COLORMAP = "inferno"
MOVIE_FRAMES = 40
FRAMES = 180
BURN_IN = 40
FRAME_PERIOD_S = 0.001
PLAYBACK_DURATIONS_S = (8, 12, 20)
PLAYBACK_DEFAULT_S = 8
MOVIE_ARRAYS = ("indices", "time_s", "psf_uncorrected", "psf_corrected", "x_angle_rad", "y_angle_rad")
MEAN_ARRAYS = ("mean_psf_uncorrected", "mean_psf_corrected", "analysis_frames", "x_angle_rad", "y_angle_rad")
ROLES = ("uncorrected", "corrected")
FIELDS = {"corrected": "pre_update_residual_opd_m", "uncorrected": "atmosphere_opd_m (zero-DM optical counterfactual)"}
REFERENCES = [
    {
        "citation": "Leschinski, K. et al. (2016), SimCADO - an instrument data simulator package for MICADO at the E-ELT, section 3.4 and Figure 3",
        "url": "https://arxiv.org/pdf/1609.01480",
        "used_for": "the fixed source -> optical PSF -> observed image method",
    },
    {
        "citation": "Simioni, M. et al. (2026), The MICADO first light imager for the ELT: simulated observations of star forming clumps at cosmic noon, MNRAS 552, stag1714, section 5.2 and Figure 5",
        "url": "https://academic.oup.com/mnras/article/552/1/stag1714/8789687",
        "used_for": "using an observed HST/LEGUS image of NGC 1705 as a source template (their three-copy arrangement and assumed redshift are not reproduced)",
    },
]
REFERENCE_NOTE = "Method only: no MICADO/ELT angular resolution, exposure, sensitivity or performance assumption is transferred to this 2 m simulation."
DATA_REFERENCES = [
    {"citation": "Calzetti, D. et al. (2015), Legacy Extragalactic UV Survey (LEGUS) with the Hubble Space Telescope. I. Survey description, AJ 149, 51", "url": "https://archive.stsci.edu/prepds/legus/dataproducts-public.html", "used_for": "the F814W science mosaic and aligned exposures (LEGUS public data table, NGC 1705 row)"},
    {"citation": "LEGUS NGC 1705 photometric catalogs", "url": "https://archive.stsci.edu/prepds/legus/photometric_catalogs/ngc1705.html", "used_for": "context for the resolved stellar population (not used numerically)"},
    {"citation": "DrizzlePac handbook, section 3.2: the drizzle concept", "url": "https://hst-docs.stsci.edu/drizzpac/chapter-3-description-of-the-drizzle-algorithm/3-2-drizzle-concept", "used_for": "why the mosaic retains Hubble's optical PSF, pixel response and drizzle response"},
    {"citation": "Hubble Legacy Archive FAQ: science images, weight maps and correlated noise", "url": "https://hla.stsci.edu/hla_faq.html", "used_for": "interpretation of the residual (correlated) image noise"},
]
VISUAL_REFERENCE = {"title": "NGC 1705 (multi-band presentation image)", "url": "https://esahubble.org/images/potw2205a/", "credit": "ESA/Hubble & NASA, R. Chandar", "role": "visual reference only, not the numerical input"}
LIMITATIONS = [
    "The input is observed HST/WFC3 F814W (red optical, I band) morphology used as a fixed relative-intensity template; the added PSFs are monochromatic at 1.65 µm. This is not a calibrated H-band image or prediction.",
    "The template keeps Hubble's own resolution (optics, detector and drizzle response) and its residual observational noise; nothing is deconvolved or denoised. The input panel is therefore not intrinsic truth, and the AO-corrected panel cannot recover detail absent from the HST image.",
    "The core of the central cluster NGC 1705-1 is saturated in all three input exposures. Its values are kept as delivered and are not a faithful core profile or flux; the core's true flux is not recoverable from these data. The dashed box on the page is a deliberately enlarged envelope of the flagged pixels, not the exact saturated extent.",
    "All observed structure in the cutout is retained. Membership in NGC 1705 was not determined for individual sources, so unrelated foreground stars or background galaxies cannot be excluded.",
    "One on-axis PSF is assumed across the compact field (a spatially invariant kernel); off-axis AO correction is not modelled, and fitting the field inside the grid does not establish it.",
    "No science-camera noise, sky or detector is added: no claim about the galaxy's true near-infrared surface brightness, photon counts, sensitivity, signal-to-noise ratio or broadband performance. The AO Strehl values describe the simulated PSFs, not the sharpness of these images.",
    "Sampled mode shows the 40 retained instantaneous PSF pairs, frame-start snapshots irregularly spaced over 0–179 ms. The other 140 of the 180 frames have metrics but no saved PSF images, so they cannot be shown.",
    "Mean mode uses the saved 140-frame post-burn-in mean PSFs (frames 40–179); for the fixed template this equals the mean of the 140 corresponding observations under the linear imaging model. It is a discrete average of frame-start snapshots, not a newly simulated long exposure, and it cannot be inverted into the missing individual PSFs.",
    "Slower playback and looping change presentation only: they do not lengthen the simulated 180 ms or add samples. A loop repeats the same realization and can jump at its boundary. Nothing is interpolated.",
    "The template does not rotate, move or vary; every change in the observed images comes from the recorded PSFs. Display enlargement is nearest-neighbour and adds no resolving power.",
]


class GalaxyExportError(RuntimeError):
    pass


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise GalaxyExportError(message)


def _read_json_bytes(data: bytes) -> Any:
    return json.loads(data.decode("utf-8"))


def _json_bytes(value: Any) -> bytes:
    return (json.dumps(value, indent=1, allow_nan=False, ensure_ascii=False) + "\n").encode("utf-8")


def _array_sha(array: np.ndarray) -> str:
    return identity.sha256_bytes(np.ascontiguousarray(array).tobytes())


def _load_npz(data: bytes, names: Tuple[str, ...]) -> Dict[str, np.ndarray]:
    """Arrays parsed from the hashed bytes themselves, made read-only."""

    with np.load(io.BytesIO(data), allow_pickle=False) as archive:
        arrays = {name: np.array(archive[name]) for name in names}
    for array in arrays.values():
        array.setflags(write=False)
    return arrays


def code_identity() -> Dict[str, Any]:
    here = Path(__file__).resolve().parent
    files = {name: identity.sha256_file(here / name) for name in CODE_FILES}
    return {"sha256": identity.sha256_bytes(identity.canonical_json_bytes(files)), "files": files}


def environment() -> Dict[str, Any]:
    import astropy
    import matplotlib
    import PIL
    import scipy

    return {
        "python": platform.python_version(),
        "numpy": np.__version__,
        "scipy": scipy.__version__,
        "astropy": astropy.__version__,
        "pillow": PIL.__version__,
        "matplotlib": matplotlib.__version__,
        "machine": platform.machine(),
    }


# ---------------------------------------------------------------------------
# Display


def _colormap() -> np.ndarray:
    from matplotlib import colormaps

    return (np.asarray(colormaps[COLORMAP](np.linspace(0.0, 1.0, 256)))[:, :3] * 255.0 + 0.5).astype(np.uint8)


def display_codes(intensity: np.ndarray, reference: float) -> Tuple[np.ndarray, Dict[str, float]]:
    """8-bit codes of the common asinh stretch; the scale never depends on the image."""

    value = np.arcsinh(np.maximum(np.asarray(intensity, dtype=float), 0.0) / (ASINH_SOFTENING * reference)) / math.asinh(1.0 / ASINH_SOFTENING)
    codes = np.clip(np.floor(np.clip(value, 0.0, 1.0) * 255.0 + 0.5), 0, 255).astype(np.uint8)
    return codes, {
        "above_display_max_fraction": float(np.count_nonzero(value > 1.0) / value.size),
        "negative_fraction": float(np.count_nonzero(np.asarray(intensity) < 0.0) / value.size),
        "zero_code_fraction": float(np.count_nonzero(codes == 0) / codes.size),
    }


def raster(codes: np.ndarray) -> np.ndarray:
    """Codes in raster order: row 0 is the +y (north) edge (rows flipped once)."""

    return np.ascontiguousarray(codes[::-1])


def png_bytes(raster_codes: np.ndarray, cmap: np.ndarray) -> bytes:
    """An 8-bit indexed PNG whose palette is the colour table: index = display code."""

    from PIL import Image

    codes = np.ascontiguousarray(raster_codes, dtype=np.uint8)
    image = Image.frombytes("P", (codes.shape[1], codes.shape[0]), codes.tobytes())
    image.putpalette(cmap.reshape(-1).tolist())
    buffer = io.BytesIO()
    image.save(buffer, format="PNG", optimize=True)
    return buffer.getvalue()


def atlas(tiles: List[np.ndarray]) -> Tuple[np.ndarray, List[List[int]]]:
    height, width = tiles[0].shape[:2]
    rows = math.ceil(len(tiles) / ATLAS_COLUMNS)
    canvas = np.zeros((rows * height, ATLAS_COLUMNS * width), dtype=np.uint8)
    rectangles = []
    for index, tile in enumerate(tiles):
        row, column = divmod(index, ATLAS_COLUMNS)
        canvas[row * height:(row + 1) * height, column * width:(column + 1) * width] = tile
        rectangles.append([column * width, row * height, width, height])
    return canvas, rectangles


# ---------------------------------------------------------------------------
# Bundle


class Bundle:
    """Members written under one derived directory, hashed as written."""

    def __init__(self, base: Path) -> None:
        self.base = base
        self.members: List[Dict[str, Any]] = []

    def write(self, relative: str, data: bytes, *, media_type: str, role: str) -> Dict[str, Any]:
        path = self.base / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        entry = {"path": relative, "bytes": len(data), "sha256": identity.sha256_bytes(data), "media_type": media_type, "role": role}
        self.members.append(entry)
        return entry

    def write_json(self, relative: str, value: Any, *, role: str) -> Dict[str, Any]:
        return self.write(relative, _json_bytes(value), media_type="application/json", role=role)


def ref(entry: Dict[str, Any], defining: str) -> Dict[str, Any]:
    """A member reference relative to the defining JSON's own directory."""

    defining_dir = Path(defining).parent
    relative = Path(entry["path"])
    try:
        path = relative.relative_to(defining_dir).as_posix()
    except ValueError:
        path = "/".join([".."] * len(defining_dir.parts) + [relative.as_posix()])
    return {"href": path, "bytes": entry["bytes"], "sha256": entry["sha256"], "media_type": entry["media_type"]}


# ---------------------------------------------------------------------------
# Inputs


def published_dataset(web_dir: Path) -> Dict[str, Any]:
    """The published entry, manifest and the tracked metadata the export binds to."""

    entry_path = web_dir / "data" / "current.json"
    entry = _read_json_bytes(entry_path.read_bytes())
    manifest_path = entry_path.parent / entry["manifest"]
    manifest_data = manifest_path.read_bytes()
    _require(len(manifest_data) == entry["manifest_bytes"] and identity.sha256_bytes(manifest_data) == entry["manifest_sha256"], "the published manifest does not match its entry")
    manifest = _read_json_bytes(manifest_data)
    _require(manifest["dataset_id"] == entry["dataset_id"], "the published manifest names another dataset")
    base = manifest_path.parent
    members = {item["path"]: item for item in manifest["members"]}

    def member(relative: str) -> Tuple[Any, Dict[str, Any]]:
        data = (base / relative).read_bytes()
        item = members[relative]
        _require(len(data) == item["bytes"] and identity.sha256_bytes(data) == item["sha256"], f"published member {relative} differs from the manifest")
        return _read_json_bytes(data), item

    display, _ = member("display.json")
    scene, _ = member("scene/scene.json")
    cases = {}
    for case_id, item in manifest["cases"].items():
        prefix = f"cases/{case_id}"
        case, case_item = member(f"{prefix}/case.json")
        observation, observation_item = member(f"{prefix}/observation.json")
        provenance, provenance_item = member(f"{prefix}/provenance.json")
        cases[case_id] = {
            "label": item["label"],
            "case": case,
            "observation": observation,
            "provenance": provenance,
            "tracked": {name: {"path": it["path"], "sha256": it["sha256"]} for name, it in (("case.json", case_item), ("observation.json", observation_item), ("provenance.json", provenance_item))},
        }
    return {"entry": entry, "entry_path": entry_path, "manifest": manifest, "display": display, "scene": scene, "cases": cases}


def read_inputs(series_dir: Path, case_id: str, published: Dict[str, Any], input_manifest: Optional[Dict[str, str]]) -> Dict[str, Any]:
    """One case's originals, read once, hashed and bound before use."""

    job_id = f"case-{case_id}"
    attempt = series_dir / "jobs" / job_id / "attempt-01"
    provenance = published["cases"][case_id]["provenance"]
    raw = provenance["raw_evidence"]
    files = {}
    for name in ("movie.npz", "mean_psfs.npz", "job_record.json"):
        with (attempt / name).open("rb") as stream:
            data = stream.read()
        digest = identity.sha256_bytes(data)
        expected = raw["job_record_sha256"] if name == "job_record.json" else raw["files"][name]["sha256"]
        _require(digest == expected, f"{job_id}/{name}: SHA-256 differs from the published provenance record")
        relative = f"{series_dir.name}/jobs/{job_id}/attempt-01/{name}"
        if input_manifest is not None:
            _require(input_manifest.get(relative) == digest, f"{relative}: SHA-256 differs from the input manifest")
        files[name] = {"data": data, "sha256": digest, "bytes": len(data)}
    record = _read_json_bytes(files["job_record.json"]["data"])
    _require(record["files"]["movie.npz"]["sha256"] == files["movie.npz"]["sha256"] and record["files"]["mean_psfs.npz"]["sha256"] == files["mean_psfs.npz"]["sha256"], f"{job_id}: the job record names other movie/mean files")
    movie = _load_npz(files["movie.npz"]["data"], MOVIE_ARRAYS)
    means = _load_npz(files["mean_psfs.npz"]["data"], MEAN_ARRAYS)
    return {"job_id": job_id, "files": files, "movie": movie, "means": means}


def check_case_arrays(case_id: str, inputs: Dict[str, Any], published: Dict[str, Any], kernel_grid: Dict[str, Any]) -> None:
    movie, means = inputs["movie"], inputs["means"]
    case = published["cases"][case_id]["case"]
    time_domain = case["time_domain"]
    indices = [int(v) for v in movie["indices"]]
    _require(indices == time_domain["movie_indices"] and len(indices) == MOVIE_FRAMES, f"{case_id}: retained indices differ from the published movie indices")
    _require(all(b > a for a, b in zip(indices, indices[1:])) and indices[0] == 0 and indices[-1] == FRAMES - 1, f"{case_id}: retained indices are not ordered over 0-179")
    _require(np.array_equal(movie["time_s"], np.asarray(time_domain["movie_times_s"], dtype=float)), f"{case_id}: retained timestamps differ from the published movie times")
    for role in ROLES:
        stack = movie[f"psf_{role}"]
        _require(stack.shape == (MOVIE_FRAMES, *kernel_grid["shape_yx"]) and stack.dtype == np.float64, f"{case_id}: psf_{role} is not a (40, 156, 156) float64 stack")
    for source in (movie, means):
        _require(galaxy_scene.grid_record(source["x_angle_rad"], source["y_angle_rad"]) == kernel_grid, f"{case_id}: PSF axes differ from the published PSF grid")
    _require([int(v) for v in means["analysis_frames"]] == list(range(BURN_IN, FRAMES)), f"{case_id}: the mean PSFs do not cover frames 40-179")
    observation = published["cases"][case_id]["observation"]
    for role in ROLES:
        parent = observation["roles"][role]["parent"]
        _require(parent["array"] == f"mean_psf_{role}" and parent["sample_count"] == FRAMES - BURN_IN, f"{case_id}: published {role} observation parent is not mean_psf_{role}")
        _require(_array_sha(means[f"mean_psf_{role}"]) == parent["array_sha256"], f"{case_id}: mean_psf_{role} differs from the published observation parent")
        _require(parent["file_sha256"] == inputs["files"]["mean_psfs.npz"]["sha256"], f"{case_id}: the published observation parent names another mean_psfs.npz")
        _require(parent["field"] == FIELDS[role], f"{case_id}: unexpected {role} parent field")


# ---------------------------------------------------------------------------
# Export


def export(series_dir: Path, template_fits: Path, quality_flc: List[Path], web_dir: Path, output_dir: Path,
           input_manifest_path: Optional[Path]) -> Dict[str, Any]:
    series_dir = Path(series_dir)
    web_dir = Path(web_dir)
    published = published_dataset(web_dir)
    manifest = published["manifest"]
    input_manifest = None
    input_manifest_record = None
    if input_manifest_path is not None:
        data = Path(input_manifest_path).read_bytes()
        listing = _read_json_bytes(data)
        input_manifest = {item["path"]: item["sha256"] for item in listing["files"]}
        input_manifest_record = {"schema": listing.get("schema"), "file_count": listing.get("file_count"), "sha256": identity.sha256_bytes(data)}
    plan_data = (series_dir / "series_plan.json").read_bytes()
    plan_sha = identity.sha256_bytes(plan_data)
    _require(plan_sha == manifest["series"]["plan_sha256"], "series_plan.json differs from the published plan digest")
    _require(series_dir.name == manifest["series"]["series_id"], "the series directory is not the published series")
    if input_manifest is not None:
        _require(input_manifest.get(f"{series_dir.name}/series_plan.json") == plan_sha, "series_plan.json differs from the input manifest")
    _require(sorted(Path(p).name for p in quality_flc) == sorted(q["name"] for q in galaxy_template.QUALITY_PRODUCTS), "the quality exposures are not the three F814W FLC files of the visit")

    case_ids = list(manifest["cases"])
    baseline = published["cases"][manifest["default_case"]]["case"]["effective_parameters"]
    wavelength = baseline["explorer_science_wavelength_m"]
    diameter = baseline["telescope_diameter_m"]
    for case_id in case_ids:
        parameters = published["cases"][case_id]["case"]["effective_parameters"]
        _require(parameters["explorer_science_wavelength_m"] == wavelength and parameters["telescope_diameter_m"] == diameter, f"{case_id}: science wavelength or aperture differs between cases")

    first = read_inputs(series_dir, manifest["default_case"], published, input_manifest)
    x_axis, y_axis = first["means"]["x_angle_rad"], first["means"]["y_angle_rad"]
    kernel_grid = galaxy_scene.grid_record(x_axis, y_axis)
    _require(galaxy_scene.grid_id(kernel_grid) == published["scene"]["scene"]["grid_id"], "the PSF grid differs from the published scene grid")
    prepared = galaxy_template.prepare(template_fits, sorted(quality_flc, key=lambda p: Path(p).name), x_axis, y_axis)
    template, template_record = prepared["template"], prepared["record"]
    _require(template_record["target"]["kernel_grid_id"] == published["scene"]["scene"]["grid_id"], "the template is not on the published PSF lattice")
    convolver = galaxy_scene.Convolver(template, prepared["x_axis"], prepared["y_axis"], x_axis, y_axis)
    _require(convolver.context_complete, "the template does not cover the kernel reach of the window")
    code = code_identity()
    zero = kernel_grid["x_zero_index"]
    d0, d1 = zero - DISPLAY_CELLS // 2, zero + DISPLAY_CELLS // 2
    t0 = galaxy_template.TEMPLATE_CELLS // 2 - DISPLAY_CELLS // 2
    t1 = t0 + DISPLAY_CELLS
    derived_key = identity.sha256_bytes(identity.canonical_json_bytes({
        "parent_dataset": manifest["dataset_id"],
        "parent_manifest_sha256": published["entry"]["manifest_sha256"],
        "plan_sha256": plan_sha,
        "scene_id": template_record["scene_id"],
        "code": code["sha256"],
        "display": DISPLAY_REVISION,
    }))[:12]
    derived_id = f"ngc1705-f814w-{manifest['series']['series_id'].removeprefix('series-')}-g{derived_key}"
    web_base = web_dir / "derived" / derived_id
    out_base = Path(output_dir) / derived_id
    _require(not web_base.exists() and not out_base.exists(), f"derived directory {derived_id} exists; an export is never overwritten")

    reference = float(template_record["peak_cell"])
    cell_mas = template_record["target"]["step_mas"][0]
    cmap = _colormap()
    scale = {
        "mapping": f"asinh(I / (beta I_ref)) / asinh(1 / beta), beta = {ASINH_SOFTENING:g}, clipped to [0, 1]",
        "stretch": "asinh",
        "softening_beta": ASINH_SOFTENING,
        "reference": "brightest cell of the prepared template (in the saturated core region of NGC 1705-1; a fixed display number, not a physical peak)",
        "reference_cell_flux": reference,
        "colormap": COLORMAP,
        "colorbar_ticks": COLORBAR_TICKS,
        "code_rule": f"code = round(clip(asinh(max(I, 0) / ({ASINH_SOFTENING:g} I_ref)) / asinh({1 / ASINH_SOFTENING:g}), 0, 1) * 255); PNG palette index = code",
        "normalization": "common to the template, every retained sample, both mean images, both roles and every case; no image is normalized to its own maximum",
        "lut_rgb_hex": ["#%02x%02x%02x" % tuple(int(v) for v in row) for row in cmap],
    }
    sat_rows, sat_cols = np.nonzero(prepared["saturated_cells"][t0:t1, t0:t1])
    display_window = {
        "cells": [DISPLAY_CELLS, DISPLAY_CELLS],
        "native_window_index": [[d0, d1], [d0, d1]],
        "template_index": [[t0, t1], [t0, t1]],
        "cell_mas": cell_mas,
        "extent_arcsec": DISPLAY_CELLS * cell_mas / 1000.0,
        "extent_mas": [(-DISPLAY_CELLS // 2 - 0.5) * cell_mas, (DISPLAY_CELLS // 2 - 0.5) * cell_mas],
        "orientation": "north up, east left (+x west, +y north on the template's projection plane)",
        "saturation_envelope_box_cells": None if sat_rows.size == 0 else {"x": [int(sat_cols.min()), int(sat_cols.max()) + 1], "y": [int(sat_rows.min()), int(sat_rows.max()) + 1], "rows": "counted from the -y (south) edge", "definition": "template cells touching the conservative saturation envelope (flags dilated by one mosaic pixel); an enlarged marker, not the exact saturated extent"},
        "note": "the observation crop is declared separately from the PSF panels' 64 x 64 crop; the native window (156 cells, about 8.7 arcsec) is recorded in the flux accounting and the template extends to 312 cells for convolution context",
    }

    bundle = Bundle(web_base)
    template_codes, template_clip = display_codes(template[t0:t1, t0:t1], reference)
    template_png = bundle.write("scene/template.png", png_bytes(raster(template_codes), cmap), media_type="image/png", role="galaxy_template")
    scene_export = {
        "schema": SCHEMA_SCENE_EXPORT,
        "scene": template_record,
        "display": {
            "image": ref(template_png, "scene/galaxy-scene.json"),
            "window": display_window,
            "window_flux_fraction": float(template[t0:t1, t0:t1].sum()),
            "clipping": template_clip,
            "raster": "row 0 of the PNG is the north (+y) edge; columns increase towards the west (+x)",
        },
        "references": REFERENCES,
        "reference_note": REFERENCE_NOTE,
        "data_references": DATA_REFERENCES,
        "visual_reference": VISUAL_REFERENCE,
    }
    scene_entry = bundle.write_json("scene/galaxy-scene.json", scene_export, role="galaxy_scene")

    out_base.mkdir(parents=True)
    np.savez_compressed(out_base / "template.npz", template=template, x_angle_rad=prepared["x_axis"], y_angle_rad=prepared["y_axis"], saturated_cells=prepared["saturated_cells"])
    case_refs: Dict[str, Any] = {}
    flux_summary: Dict[str, Any] = {}
    for case_id in case_ids:
        inputs = first if case_id == manifest["default_case"] else read_inputs(series_dir, case_id, published, input_manifest)
        check_case_arrays(case_id, inputs, published, kernel_grid)
        movie, means = inputs["movie"], inputs["means"]
        prefix = f"cases/{case_id}"
        arrays: Dict[str, np.ndarray] = {}
        sampled_roles: Dict[str, Any] = {}
        mean_roles: Dict[str, Any] = {}
        worst_error = 0.0
        for role in ROLES:
            stack = movie[f"psf_{role}"]
            images = np.empty_like(stack)
            tiles = []
            accounting: Dict[str, List[float]] = {key: [] for key in ("kernel_flux", "full_flux", "full_flux_error", "window_fraction", "display_window_fraction", "min_value")}
            above = 0.0
            for position in range(MOVIE_FRAMES):
                image, flux = convolver.observe(stack[position])
                images[position] = image
                worst_error = max(worst_error, abs(flux["full_flux_error"]))
                for key in ("kernel_flux", "full_flux", "full_flux_error", "window_fraction", "min_value"):
                    accounting[key].append(flux[key])
                accounting["display_window_fraction"].append(float(image[d0:d1, d0:d1].sum()) / flux["full_flux"])
                codes, clip = display_codes(image[d0:d1, d0:d1], reference)
                above = max(above, clip["above_display_max_fraction"])
                tiles.append(raster(codes))
            arrays[f"sampled_{role}"] = images
            canvas, rectangles = atlas(tiles)
            atlas_entry = bundle.write(f"{prefix}/galaxy-sampled-{role}.png", png_bytes(canvas, cmap), media_type="image/png", role=f"galaxy_sampled_{role}")
            sampled_roles[role] = {
                "kernel": f"movie.npz psf_{role}[k] (field {FIELDS[role]})",
                "kernel_array_sha256": _array_sha(stack),
                "atlas": ref(atlas_entry, f"{prefix}/galaxy.json"),
                "rectangles_xywh": rectangles,
                "image_array_sha256": _array_sha(images),
                "flux": {
                    "template_flux": convolver.template_flux,
                    **accounting,
                    "max_abs_full_flux_error": max(abs(v) for v in accounting["full_flux_error"]),
                },
                "clipping": {"max_above_display_max_fraction": above},
            }
            kernel = means[f"mean_psf_{role}"]
            image, flux = convolver.observe(kernel)
            worst_error = max(worst_error, abs(flux["full_flux_error"]))
            arrays[f"mean_{role}"] = image
            codes, clip = display_codes(image[d0:d1, d0:d1], reference)
            mean_entry = bundle.write(f"{prefix}/galaxy-mean-{role}.png", png_bytes(raster(codes), cmap), media_type="image/png", role=f"galaxy_mean_{role}")
            mean_roles[role] = {
                "kernel": f"mean_psfs.npz mean_psf_{role} (field {FIELDS[role]})",
                "kernel_array_sha256": _array_sha(kernel),
                "kernel_matches_binary_observation_parent": True,
                "image": ref(mean_entry, f"{prefix}/galaxy.json"),
                "image_array_sha256": _array_sha(image),
                "flux": {"template_flux": convolver.template_flux, **flux, "display_window_fraction": float(image[d0:d1, d0:d1].sum()) / flux["full_flux"]},
                "clipping": clip,
            }
        _require(worst_error <= 1e-12, f"{case_id}: convolution flux differs from template x kernel flux by {worst_error:.3e}")
        np.savez_compressed(out_base / f"{case_id}.npz", **arrays)
        derived_arrays = {name: _array_sha(value) for name, value in arrays.items()}
        files = inputs["files"]
        observation = {
            "schema": SCHEMA_OBSERVATION,
            "case_id": case_id,
            "label": f"{published['cases'][case_id]['label']}: observed NGC 1705 F814W template through the simulated 1.65 µm PSFs; relative flux per numerical cell, no added noise",
            "scene_id": template_record["scene_id"],
            "kernel_grid_id": template_record["target"]["kernel_grid_id"],
            "scene": ref(scene_entry, f"{prefix}/galaxy.json"),
            "renderer_revision": galaxy_scene.RENDERER_REVISION,
            "policy": convolver.policy(),
            "response": "I_k = T (*) P_k with T ~ R (*) (O * H_HST + n_HST): the output keeps Hubble's effective response and noise, the cell response R once, and adds the simulated PSF P_k",
            "parents": {
                "series_id": manifest["series"]["series_id"],
                "plan_sha256": plan_sha,
                "job_id": inputs["job_id"],
                "attempt": "attempt-01",
                "files": {name: {"bytes": item["bytes"], "sha256": item["sha256"]} for name, item in files.items()},
                "location": f"outputs/ao_explorer_v1/{series_dir.name}/jobs/{inputs['job_id']}/attempt-01/ (caller-owned, read-only, not in the web bundle)",
                "published_metadata": published["cases"][case_id]["tracked"],
                "binding": "file digests equal the published provenance raw-evidence record; mean kernels equal the binary observation's parent arrays",
            },
            "sampled": {
                "count": MOVIE_FRAMES,
                "frame_indices": [int(v) for v in movie["indices"]],
                "time_s": [float(v) for v in movie["time_s"]],
                "burn_in_frames": BURN_IN,
                "frame_period_s": FRAME_PERIOD_S,
                "sampling": "the 40 retained instantaneous PSF pairs of movie.npz: frame-start snapshots at their recorded indices and times",
                "roles": sampled_roles,
            },
            "mean": {
                "window": [BURN_IN, FRAMES],
                "sample_count": FRAMES - BURN_IN,
                "weights": "equal",
                "kernels": "the saved complete post-burn-in mean PSFs (mean_psf_*, frames 40-179), not an average of the retained movie samples",
                "linearity": "for the fixed template, T (*) mean PSF equals the mean of the 140 per-frame observations under the linear imaging model; the display stretch is applied afterwards",
                "roles": mean_roles,
            },
            "display": {"scale_revision": DISPLAY_REVISION, "window": display_window, "raster": "PNG row 0 is the north (+y) edge; columns increase towards the west (+x)"},
            "derived_arrays": {"file": f"{case_id}.npz", "location": f"<output-dir>/{derived_id}/ (full-precision native-window arrays; outside the site and Git)", "sha256": derived_arrays},
            "code_identity": code,
        }
        observation_entry = bundle.write_json(f"{prefix}/galaxy.json", observation, role="galaxy_observation")
        case_refs[case_id] = {"label": published["cases"][case_id]["label"], "galaxy": ref(observation_entry, "manifest.json")}
        flux_summary[case_id] = {
            role: {
                "sampled_window_fraction_range": [min(sampled_roles[role]["flux"]["window_fraction"]), max(sampled_roles[role]["flux"]["window_fraction"])],
                "mean_window_fraction": mean_roles[role]["flux"]["window_fraction"],
                "max_abs_full_flux_error": max(sampled_roles[role]["flux"]["max_abs_full_flux_error"], abs(mean_roles[role]["flux"]["full_flux_error"])),
            }
            for role in ROLES
        }

    galaxy_manifest = {
        "schema": SCHEMA_MANIFEST,
        "derived_id": derived_id,
        "title": "NGC 1705 central region: observed HST/F814W template through the simulated PSFs",
        "parent": {
            "dataset_id": manifest["dataset_id"],
            "manifest_sha256": published["entry"]["manifest_sha256"],
            "series_id": manifest["series"]["series_id"],
            "plan_sha256": plan_sha,
            "binary_scene_id": published["scene"]["scene"]["scene_id"],
            "relation": "additive derivative: the published dataset, its binary scene, metrics and evidence are unchanged",
        },
        "supersedes": "the uncommitted analytic host-plus-three-Gaussian scene (never published); its scene identity is not reused",
        "default_case": manifest["default_case"],
        "scene": ref(scene_entry, "manifest.json"),
        "cases": case_refs,
        "display": {"revision": DISPLAY_REVISION, "scale": scale, "window": display_window, "upscaling": "nearest-neighbour in the browser (image smoothing disabled); no interpolation of values", "scale_bar_arcsec": 1.0},
        "playback": {
            "interval_s": [0.0, (FRAMES - 1) * FRAME_PERIOD_S + FRAME_PERIOD_S],
            "interval_rule": "from the start of frame 0 to the end of frame 179 (180 frames of 1 ms)",
            "durations_s": list(PLAYBACK_DURATIONS_S),
            "default_duration_s": PLAYBACK_DEFAULT_S,
            "hold": "each retained sample is shown from its own timestamp until the next retained timestamp; frame 179 for its 1 ms frame period",
            "loop_default": False,
            "loop": "optional; repeats the same realization from frame 0 and can jump at the boundary",
            "interpolation": "none",
        },
        "flux_summary": flux_summary,
        "credit": galaxy_template.CREDIT,
        "references": REFERENCES,
        "reference_note": REFERENCE_NOTE,
        "data_references": DATA_REFERENCES,
        "visual_reference": VISUAL_REFERENCE,
        "limitations": LIMITATIONS,
        "code_identity": code,
        "environment": environment(),
        "inputs": {
            "series_dir": f"outputs/ao_explorer_v1/{series_dir.name} (read-only)",
            "files_per_case": ["movie.npz", "mean_psfs.npz", "job_record.json"],
            "plan": "series_plan.json",
            "input_manifest": input_manifest_record,
            "template_product": {key: template_record["product"][key] for key in ("name", "url", "version", "sha256", "bytes", "retrieved_utc")},
            "quality_products": [{key: q[key] for key in ("name", "url", "sha256", "bytes")} for q in template_record["quality_products"]],
        },
        "members": None,
    }
    galaxy_manifest["members"] = bundle.members
    manifest_data = _json_bytes(galaxy_manifest)
    (web_base / "manifest.json").write_bytes(manifest_data)
    record = {"derived_id": derived_id, "manifest_sha256": identity.sha256_bytes(manifest_data), "manifest_bytes": len(manifest_data), "code_identity": code, "scene_id": template_record["scene_id"], "flux_summary": flux_summary}
    (out_base / "export_record.json").write_bytes(_json_bytes(record))

    entry = dict(published["entry"])
    entry["galaxy"] = {
        "schema": SCHEMA_ENTRY_REF,
        "derived_id": derived_id,
        "manifest": f"../derived/{derived_id}/manifest.json",
        "manifest_bytes": len(manifest_data),
        "manifest_sha256": identity.sha256_bytes(manifest_data),
    }
    published["entry_path"].write_text(json.dumps(entry, indent=1) + "\n", encoding="utf-8")
    return {"derived_id": derived_id, "web_dir": str(web_base), "output_dir": str(out_base), "members": len(bundle.members), "bytes": sum(item["bytes"] for item in bundle.members) + len(manifest_data), "scene_id": template_record["scene_id"], "flux_summary": flux_summary}


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--series-dir", type=Path, required=True)
    parser.add_argument("--template-fits", type=Path, required=True)
    parser.add_argument("--quality-flc", type=Path, nargs="+", required=True)
    parser.add_argument("--web-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--input-manifest", type=Path)
    arguments = parser.parse_args(argv)
    try:
        report = export(arguments.series_dir, arguments.template_fits, arguments.quality_flc, arguments.web_dir, arguments.output_dir, arguments.input_manifest)
    except (GalaxyExportError, galaxy_template.TemplateError, galaxy_scene.GalaxySceneError) as exc:
        print(json.dumps({"exported": False, "error": str(exc)}))
        return 2
    print(json.dumps({"exported": True, **report}, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
