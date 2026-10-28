"""Observed NGC 1705 central-region template from the LEGUS F814W mosaic.

Source
    The calibrated HST/WFC3 UVIS F814W drizzled science mosaic of NGC 1705
    distributed by LEGUS (HST GO-13364, PI D. Calzetti),
    ``hlsp_legus_hst_uvis_ngc1705_f814w_v1_drc.fits``: primary HDU, count
    rate in electrons per second per output pixel, TAN WCS with the geometric
    distortion already removed by drizzle (pixel scale 39.62 mas, north up).
    The aligned FLC exposures of the same visit supply the data-quality flags
    (the public mosaic carries no weight or context map).  Files are read
    once, hashed from the bytes that are parsed, and bound to recorded
    digests.

Template ``T``
    One contiguous cutout centred on the flux-weighted centroid of the
    central super star cluster NGC 1705-1, reprojected onto the lattice of the
    simulated PSFs (their actual angular step, ~55.632 mas) at angular scale
    factor 1.0: +x is west, +y is north (north up, east left when displayed).
    The local WCS Jacobian at the centre is measured; the mosaic is aligned
    with north to within the recorded rotation, so the reprojection is exact
    separable pixel-area integration: each output cell receives every input
    pixel's count rate times the fraction of that pixel's area inside the
    cell, which conserves flux.  The cutout covers twice the PSF window so
    that light outside the observation window still reaches it through the
    kernel.  ``T`` is normalized once to unit total over the cutout.

What ``T`` is (and is not)
    Observed F814W morphology, ``T ~ R (*) (O * H_HST + n_HST)``: it keeps
    Hubble's effective image response (optics, detector, drizzle) and the
    residual observational noise; the area integration adds the output-cell
    response ``R`` once.  Nothing is deconvolved, denoised, repaired, masked,
    filled, rotated or repeated, and no noise is drawn.  It is not a 1.65 um
    image: F814W morphology is used as a fixed relative-intensity template
    with the monochromatic 1.65 um PSFs.  The core of NGC 1705-1 is saturated
    in the input exposures (see the quality record); its values are kept as
    delivered and are not a faithful core profile.
"""

from __future__ import annotations

import io
import math
from typing import Any, Dict, List, Optional, Sequence, Tuple

import numpy as np

import galaxy_scene
import identity


SCHEMA = "ao-explorer.observed-template.v1"
MAS_PER_DEG = 3600.0e3
PRODUCT = {
    "name": "hlsp_legus_hst_uvis_ngc1705_f814w_v1_drc.fits",
    "url": "https://archive.stsci.edu/hlsps/legus/ngc1705/hlsp_legus_hst_uvis_ngc1705_f814w_v1_drc.fits",
    "collection": "LEGUS (Legacy ExtraGalactic UV Survey) high-level science product, MAST",
    "collection_url": "https://archive.stsci.edu/prepds/legus/dataproducts-public.html",
    "version": "v1",
    "science_hdu": 0,
    "sha256": "fac242cbfa9dd445fe0740e382467f958b9737abd7168c5d429db9f9951a78c7",
    "bytes": 153898560,
    "retrieved_utc": "2026-10-23T15:56:22Z",
}
QUALITY_PRODUCTS = [
    {"name": f"hlsp_legus_hst_wfc3_ngc1705-{root}_f814w_v1_flc.fits", "url": f"https://archive.stsci.edu/hlsps/legus/ngc1705/hlsp_legus_hst_wfc3_ngc1705-{root}_f814w_v1_flc.fits", "rootname": root}
    for root in ("icdm57rkq", "icdm57rmq", "icdm57roq")
]
CREDIT = "NGC 1705 F814W: HST/WFC3 UVIS, programme GO-13364 (LEGUS, PI D. Calzetti); high-level science product hlsp_legus_hst_uvis_ngc1705_f814w_v1 from MAST."
EXPECTED_HEADER = {"TELESCOP": "HST", "INSTRUME": "WFC3", "DETECTOR": "UVIS", "FILTER": "F814W", "BUNIT": "ELECTRONS/S", "CTYPE1": "RA---TAN", "CTYPE2": "DEC--TAN"}
HEADER_RECORD = ("TARGNAME", "PROPOSID", "PR_INV_L", "EXPTIME", "NDRIZIM", "NCOMBINE", "PHOTMODE", "PHOTFLAM", "PHOTFNU", "PHOTPLAM", "PHOTBW", "ORIENTAT",
                 "D001SCAL", "D001PIXF", "D001KERN", "D001COEF", "CRPIX1", "CRPIX2", "CRVAL1", "CRVAL2", "CD1_1", "CD1_2", "CD2_1", "CD2_2", "WCSNAME", "RA_TARG", "DEC_TARG")
TEMPLATE_CELLS = 312  # twice the 156-cell PSF window: complete kernel reach for every window sample
CENTRE_SEARCH_ARCSEC = 15.0
CENTRE_CENTROID_RADIUS_PX = 6.0
SKY_INNER_ARCSEC = 120.0
MAX_ROTATION_DEG = 1e-3
DQ_SATURATION = 256 | 2048  # full-well and A-to-D saturation (WFC3 UVIS DQ)
DQ_COSMIC_RAY = 4096 | 8192
DQ_OTHER_BAD = 4 | 32 | 128 | 512 | 1024  # bad detector pixel, CTE tail, bad column, bad flat, charge trap
DQ_ACCEPTED = 16 | 64  # hot and warm pixels (corrected by the dark), accepted as AstroDrizzle does by default
RESOLUTION_ANNULUS_ARCSEC = (25.0, 60.0)


class TemplateError(ValueError):
    pass


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise TemplateError(message)


def _open(data: bytes):
    from astropy.io import fits

    return fits.open(io.BytesIO(data), memmap=False, lazy_load_hdus=False)


def read_bytes(path, expected_sha256: Optional[str] = None) -> Tuple[bytes, str]:
    with open(path, "rb") as stream:
        data = stream.read()
    digest = identity.sha256_bytes(data)
    if expected_sha256 is not None:
        _require(digest == expected_sha256, f"{path}: SHA-256 {digest} differs from the recorded {expected_sha256}")
    return data, digest


# ---------------------------------------------------------------------------
# Geometry


def local_jacobian(wcs, x: float, y: float) -> np.ndarray:
    """Pixel offsets (dx, dy) -> (west, north) offsets in mas at pixel (x, y), from the WCS."""

    from astropy.coordinates import SkyCoord
    import astropy.units as u

    centre = wcs.pixel_to_world(x, y)
    columns = []
    for dx, dy in ((1.0, 0.0), (0.0, 1.0)):
        point = wcs.pixel_to_world(x + dx, y + dy)
        offset_east, offset_north = centre.spherical_offsets_to(point)
        columns.append([-offset_east.to(u.mas).value, offset_north.to(u.mas).value])
    _ = SkyCoord  # spherical offsets come from astropy's exact great-circle geometry
    return np.array(columns).T


def overlap_matrix(target_edges: np.ndarray, source_count: int) -> np.ndarray:
    """Fraction of each source pixel [p - 0.5, p + 0.5] inside each target interval."""

    lo = np.arange(source_count, dtype=float) - 0.5
    hi = lo + 1.0
    a = target_edges[:-1, None]
    b = target_edges[1:, None]
    return np.clip(np.minimum(b, hi[None, :]) - np.maximum(a, lo[None, :]), 0.0, None)


# ---------------------------------------------------------------------------
# Quality flags from the aligned exposures


def exposure_flags(flc_data: bytes, sky_ra: np.ndarray, sky_dec: np.ndarray) -> Dict[str, Any]:
    """Nearest-pixel DQ of one exposure (both chips) at each given sky position."""

    from astropy.wcs import WCS

    covered = np.zeros(sky_ra.shape, dtype=bool)
    dq = np.zeros(sky_ra.shape, dtype=np.int64)
    with _open(flc_data) as hdus:
        header0 = hdus[0].header
        chips = [hdu for hdu in hdus if hdu.name == "SCI"]
        record = {"rootname": header0.get("ROOTNAME"), "exptime_s": float(header0.get("EXPTIME")), "filter": header0.get("FILTER"), "chips": []}
        for sci in chips:
            version = sci.ver
            wcs = WCS(sci.header, hdus)
            dq_array = np.asarray(hdus["DQ", version].data)
            px, py = wcs.all_world2pix(sky_ra, sky_dec, 0)
            ix = np.rint(px).astype(np.int64)
            iy = np.rint(py).astype(np.int64)
            inside = (ix >= 0) & (iy >= 0) & (ix < dq_array.shape[1]) & (iy < dq_array.shape[0])
            take = inside & ~covered
            dq[take] = dq_array[iy[take], ix[take]]
            covered |= inside
            record["chips"].append({"extver": int(version), "ccdchip": sci.header.get("CCDCHIP"), "pixels_hit": int(np.count_nonzero(inside))})
    return {"covered": covered, "dq": dq, "record": record}


def _dilate(mask: np.ndarray) -> np.ndarray:
    from scipy import ndimage

    return ndimage.binary_dilation(mask, structure=np.ones((3, 3), dtype=bool))


# ---------------------------------------------------------------------------
# Template


def prepare(product_path, quality_paths: Sequence, kernel_x: np.ndarray, kernel_y: np.ndarray,
            quality_sha256: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    """The frozen template on the kernel lattice, with its full preparation record."""

    from astropy.stats import sigma_clipped_stats
    from astropy.wcs import WCS

    data, digest = read_bytes(product_path, PRODUCT["sha256"])
    _require(len(data) == PRODUCT["bytes"], "the science mosaic has an unexpected size")
    with _open(data) as hdus:
        header = hdus[PRODUCT["science_hdu"]].header.copy()
        science = np.asarray(hdus[PRODUCT["science_hdu"]].data, dtype=np.float64)
        extensions = [hdu.name for hdu in hdus]
    for key, value in EXPECTED_HEADER.items():
        _require(str(header.get(key, "")).strip() == value, f"science header {key} = {header.get(key)!r}, expected {value!r}")
    wcs = WCS(header)
    _require(wcs.pixel_n_dim == 2 and not wcs.has_distortion, "the mosaic WCS must be a distortion-free 2-D celestial WCS")

    # Centre: flux-weighted centroid of the brightest compact peak (NGC 1705-1) near the target position.
    tx, ty = (float(v) for v in wcs.world_to_pixel_values(header["RA_TARG"], header["DEC_TARG"]))
    scale_guess = abs(header["CD2_2"]) * MAS_PER_DEG
    search = int(math.ceil(CENTRE_SEARCH_ARCSEC * 1000.0 / scale_guess))
    x0s, y0s = int(round(tx)) - search, int(round(ty)) - search
    window = science[y0s:y0s + 2 * search + 1, x0s:x0s + 2 * search + 1]
    py, px = np.unravel_index(int(np.argmax(window)), window.shape)
    py, px = py + y0s, px + x0s
    yy, xx = np.mgrid[py - 8:py + 9, px - 8:px + 9]
    weights = science[py - 8:py + 9, px - 8:px + 9] * (np.hypot(xx - px, yy - py) <= CENTRE_CENTROID_RADIUS_PX)
    cx = float((weights * xx).sum() / weights.sum())
    cy = float((weights * yy).sum() / weights.sum())
    centre_sky = wcs.pixel_to_world(cx, cy)
    # The mosaic pixels are a linear grid on the TAN projection plane (CD matrix), so the
    # template axes follow that plane: +x towards west and +y towards north of the
    # projection centre.  Local north at the template centre differs by the meridian
    # convergence, measured from exact spherical offsets and recorded.
    plane = np.array([[-header["CD1_1"], -header["CD1_2"]], [header["CD2_1"], header["CD2_2"]]], dtype=float) * MAS_PER_DEG
    scale_x, scale_y = float(plane[0, 0]), float(plane[1, 1])
    rotation_deg = math.degrees(math.atan2(plane[1, 0], plane[0, 0]))
    skew_deg = math.degrees(math.atan2(-plane[0, 1], plane[1, 1]))
    _require(scale_x > 0 and scale_y > 0, "the mosaic is not north up / east left (+x west, +y north)")
    _require(abs(rotation_deg) < MAX_ROTATION_DEG and abs(skew_deg) < MAX_ROTATION_DEG, "the mosaic grid is rotated on its projection plane; separable area integration would not be exact")
    jacobian = local_jacobian(wcs, cx, cy)
    local_north_deg = math.degrees(math.atan2(-jacobian[0, 1], jacobian[1, 1]))
    local_scale = [float(np.hypot(*jacobian[:, 0])), float(np.hypot(*jacobian[:, 1]))]

    # Target lattice: the kernel's step, exact zero sample at the centre, TEMPLATE_CELLS per axis.
    tax = galaxy_scene.lattice_axis(kernel_x, TEMPLATE_CELLS)
    tay = galaxy_scene.lattice_axis(kernel_y, TEMPLATE_CELLS)
    step_x_mas = float(tax[1] - tax[0]) * 180.0 / math.pi * MAS_PER_DEG
    step_y_mas = float(tay[1] - tay[0]) * 180.0 / math.pi * MAS_PER_DEG
    edges_x = cx + (np.append(tax - (tax[1] - tax[0]) / 2, tax[-1] + (tax[1] - tax[0]) / 2) * 180.0 / math.pi * MAS_PER_DEG) / scale_x
    edges_y = cy + (np.append(tay - (tay[1] - tay[0]) / 2, tay[-1] + (tay[1] - tay[0]) / 2) * 180.0 / math.pi * MAS_PER_DEG) / scale_y
    sx0, sx1 = int(math.floor(edges_x[0] + 0.5)) - 1, int(math.ceil(edges_x[-1] + 0.5)) + 1
    sy0, sy1 = int(math.floor(edges_y[0] + 0.5)) - 1, int(math.ceil(edges_y[-1] + 0.5)) + 1
    _require(sx0 >= 0 and sy0 >= 0 and sx1 <= science.shape[1] and sy1 <= science.shape[0], "the template cutout leaves the mosaic")
    cutout = science[sy0:sy1, sx0:sx1]
    _require(np.all(np.isfinite(cutout)), "the cutout holds non-finite values")
    zero_pixels = int(np.count_nonzero(cutout == 0.0))
    _require(zero_pixels == 0, f"the cutout holds {zero_pixels} zero-valued (uncovered) pixels")
    ax = overlap_matrix(edges_x - sx0, cutout.shape[1])
    ay = overlap_matrix(edges_y - sy0, cutout.shape[0])
    raw = ay @ cutout @ ax.T  # electrons per second per output cell
    covered_source_flux = float((cutout * np.outer(ay.sum(axis=0), ax.sum(axis=0))).sum())
    _require(abs(raw.sum() - covered_source_flux) <= 1e-9 * abs(covered_source_flux), "the reprojection does not conserve flux")
    full_pixels_x = np.isclose(ax.sum(axis=0), 1.0, rtol=0.0, atol=1e-12)
    full_pixels_y = np.isclose(ay.sum(axis=0), 1.0, rtol=0.0, atol=1e-12)

    # Residual sky: the mosaic is already sky-subtracted by the pipeline; the outermost
    # covered annulus is measured, but the galaxy envelope still declines there, so the
    # level is recorded as an upper bound and not subtracted.
    rows = np.arange(science.shape[0])[:, None]
    columns = np.arange(science.shape[1])[None, :]
    radius_arcsec = np.hypot((columns - cx) * scale_x, (rows - cy) * scale_y) / 1000.0
    sky_pixels = science[(radius_arcsec >= SKY_INNER_ARCSEC) & (science != 0.0)]
    sky_mean, sky_median, sky_std = (float(v) for v in sigma_clipped_stats(sky_pixels, sigma=3.0, maxiters=10))
    cell_area_px = (step_x_mas / scale_x) * (step_y_mas / scale_y)
    sky_effect = sky_median * cell_area_px * raw.size / float(raw.sum())

    # Quality: DQ of the aligned exposures at every cutout pixel centre (nearest pixel).
    # The undilated saturation flags give an approximate extent of the saturated core;
    # flags dilated by one mosaic pixel give a deliberately enlarged envelope (the page
    # marker and the conservative usability counts).  Neither is an exact footprint.
    gy, gx = np.mgrid[sy0:sy1, sx0:sx1]
    ra, dec = wcs.all_pix2world(gx.astype(float), gy.astype(float), 0)
    exposures = []
    flags = {"covered": [], "saturated_nearest": [], "saturated": [], "cosmic_ray": [], "other_bad": []}
    for path in quality_paths:
        qdata, qdigest = read_bytes(path, None if quality_sha256 is None else quality_sha256.get(str(path).rsplit("/", 1)[-1]))
        result = exposure_flags(qdata, ra, dec)
        dq = result["dq"]
        flags["covered"].append(result["covered"])
        flags["saturated_nearest"].append(result["covered"] & ((dq & DQ_SATURATION) != 0))
        flags["saturated"].append(_dilate(flags["saturated_nearest"][-1]))
        flags["cosmic_ray"].append(_dilate(result["covered"] & ((dq & DQ_COSMIC_RAY) != 0)))
        flags["other_bad"].append(result["covered"] & ((dq & DQ_OTHER_BAD) != 0))
        exposures.append({**result["record"], "file": str(path).rsplit("/", 1)[-1], "sha256": qdigest, "bytes": len(qdata)})
    covered = np.array(flags["covered"])
    saturated = np.array(flags["saturated"])
    usable = covered & ~saturated & ~np.array(flags["cosmic_ray"]) & ~np.array(flags["other_bad"])
    saturated_nearest = np.array(flags["saturated_nearest"])
    flagged_all = covered.any(axis=0) & ~(covered & ~saturated_nearest).any(axis=0)
    flagged_any = saturated_nearest.any(axis=0)
    saturated_all = covered.any(axis=0) & ~(covered & ~saturated).any(axis=0)  # conservative envelope
    no_usable = ~usable.any(axis=0)
    cosmic_any = np.array(flags["cosmic_ray"]).any(axis=0)
    no_usable_outside = no_usable & ~saturated_all
    template_mask_cells = (ay @ saturated_all.astype(float) @ ax.T) > 0.0
    flagged_flux = float(cutout[flagged_all].sum())
    envelope_flux = float(cutout[saturated_all].sum())

    def extent_arcsec(bounds):
        return None if bounds is None else [(bounds[0][1] - bounds[0][0]) * scale_x / 1000.0, (bounds[1][1] - bounds[1][0]) * scale_y / 1000.0]

    # Indicative image resolution from isolated unsaturated point sources away from the centre.
    resolution = indicative_resolution(science, cx, cy, scale_x)

    total = float(raw.sum())
    template = raw / total
    negative = template < 0.0
    grid = galaxy_scene.grid_record(tax, tay)
    kernel_grid = galaxy_scene.grid_record(kernel_x, kernel_y)
    half_x = TEMPLATE_CELLS // 2
    window = slice(half_x - kernel_grid["x_zero_index"], half_x - kernel_grid["x_zero_index"] + kernel_grid["shape_yx"][1])
    record = {
        "schema": SCHEMA,
        "kind": "observed HST/WFC3 UVIS F814W morphology of the central region of NGC 1705, reprojected at angular scale factor 1.0",
        "object": "NGC 1705 (central region around the super star cluster NGC 1705-1)",
        "product": {**PRODUCT, "sha256": digest, "bytes": len(data), "extensions": extensions,
                    "header": {key: (header.get(key) if not isinstance(header.get(key), float) else float(header.get(key))) for key in HEADER_RECORD},
                    "units": "electrons per second per output pixel (BUNIT ELECTRONS/S)",
                    "weight_map": "not distributed with the public mosaic (the header names f814w_exp_drc_wht.fits, which is not part of the product)"},
        "quality_products": [{**q, **e} for q, e in zip(QUALITY_PRODUCTS, exposures)],
        "credit": CREDIT,
        "band_policy": "F814W morphology used as a fixed relative-intensity template with the monochromatic 1.65 um PSFs; no colour, spectral conversion or H-band prediction",
        "centre": {
            "method": f"flux-weighted centroid within {CENTRE_CENTROID_RADIUS_PX:g} px of the brightest pixel within {CENTRE_SEARCH_ARCSEC:g} arcsec of the target position (NGC 1705-1)",
            "ra_deg": float(centre_sky.ra.deg),
            "dec_deg": float(centre_sky.dec.deg),
            "pixel_xy_0based": [cx, cy],
            "brightest_pixel_xy_0based": [int(px), int(py)],
        },
        "wcs": {
            "source_scale_mas": [scale_x, scale_y],
            "rotation_deg": rotation_deg,
            "skew_deg": skew_deg,
            "handedness": "north up, east left (+x west, +y north); determinant of CD negative",
            "distortion": "removed by drizzle (TAN WCS without SIP or lookup tables)",
            "plane_jacobian_mas_per_px": plane.tolist(),
            "local_jacobian_mas_per_px": jacobian.tolist(),
            "local_scale_mas": local_scale,
            "local_north_rotation_deg": local_north_deg,
            "local_north_note": "the template axes follow the projection plane; at the template centre local north is rotated by this angle from +y (meridian convergence), and the local scale differs from the plane scale by the recorded amount",
        },
        "target": {
            "cells": [TEMPLATE_CELLS, TEMPLATE_CELLS],
            "step_mas": [step_x_mas, step_y_mas],
            "extent_arcsec": [TEMPLATE_CELLS * step_x_mas / 1000.0, TEMPLATE_CELLS * step_y_mas / 1000.0],
            "angular_scale_factor": 1.0,
            "orientation": "+x west, +y north; displayed north up, east left. The simulated PSFs have no sky orientation of their own; this mapping is a presentation choice.",
            "grid": grid,
            "grid_id": galaxy_scene.grid_id(grid),
            "kernel_grid_id": galaxy_scene.grid_id(kernel_grid),
            "kernel_window_cells": [kernel_grid["shape_yx"][1], kernel_grid["shape_yx"][0]],
            "kernel_window_slice": [window.start, window.stop],
            "source_pixel_bounds_xy_0based": [[sx0, sx1], [sy0, sy1]],
            "source_pixels_fully_used": [int(full_pixels_x.sum()), int(full_pixels_y.sum())],
        },
        "resampling": {
            "method": "exact separable pixel-area integration: each output cell sums every input pixel's count rate times the fraction of its area inside the cell (flux conserving; equivalent to a square kernel of one input pixel)",
            "added_response": "one output-cell box of the target step (R); the input's own pixel and drizzle response is part of the observed image and is not added again",
            "covered_source_flux_e_per_s": covered_source_flux,
            "template_sum_e_per_s": total,
            "conservation_relative_error": (float(raw.sum()) - covered_source_flux) / covered_source_flux,
        },
        "sky": {
            "pipeline": "the drizzled mosaic is sky-subtracted by the pipeline (per-exposure MDRIZSKY recorded in the header table)",
            "residual_estimate": f"3-sigma-clipped median of covered pixels at r >= {SKY_INNER_ARCSEC:g} arcsec from the centre",
            "residual_median_e_per_s_per_px": sky_median,
            "residual_clipped_std_e_per_s_per_px": sky_std,
            "pixels": int(sky_pixels.size),
            "subtracted": False,
            "reason": "the galaxy envelope still declines at that radius, so the level is an upper bound on residual sky rather than sky alone",
            "template_flux_fraction_if_subtracted": sky_effect,
        },
        "quality": {
            "method": "nearest exposure pixel at each cutout pixel centre through the aligned FLC WCS (with its distortion); this approximates, but is not, each exposure pixel's drizzle footprint",
            "flags": {"saturation": DQ_SATURATION, "cosmic_ray": DQ_COSMIC_RAY, "other_bad": DQ_OTHER_BAD, "accepted": DQ_ACCEPTED},
            "exposures_covering_min_max": [int(covered.sum(axis=0).min()), int(covered.sum(axis=0).max())],
            "saturated_core": {
                "definition": "cutout pixels whose nearest exposure pixel is saturation-flagged in every covering exposure, without dilation: an approximate extent of the saturated core of NGC 1705-1, not an exact one",
                "pixels": int(flagged_all.sum()),
                "bounds_xy_0based": _bounds(flagged_all, sx0, sy0),
                "bounding_box_arcsec": extent_arcsec(_bounds(flagged_all, sx0, sy0)),
                "delivered_flux_fraction_of_cutout": flagged_flux / covered_source_flux,
            },
            "conservative_envelope": {
                "definition": "each exposure's saturation flags dilated by one mosaic pixel, then intersected across exposures: a deliberately enlarged region that contains the flagged core and unsaturated neighbours; it is the region marked on the page",
                "pixels": int(saturated_all.sum()),
                "bounds_xy_0based": _bounds(saturated_all, sx0, sy0),
                "bounding_box_arcsec": extent_arcsec(_bounds(saturated_all, sx0, sy0)),
                "delivered_flux_fraction_of_cutout": envelope_flux / covered_source_flux,
                "template_cells": int(template_mask_cells.sum()),
            },
            "flux_note": "the delivered flux inside either region is limited by saturation and depends on the approximate region definition; it is neither the core's true flux nor a bound on it, and the true core flux is not recoverable from these data",
            "pixels_saturation_flagged_in_any_exposure": int(flagged_any.sum()),
            "conservative_counts": {
                "definition": "with saturation and cosmic-ray flags dilated by one mosaic pixel (an upper estimate)",
                "pixels_without_usable_exposure": int(no_usable.sum()),
                "pixels_without_usable_exposure_outside_envelope": int(no_usable_outside.sum()),
                "bounds_outside_envelope_xy_0based": _bounds(no_usable_outside, sx0, sy0),
                "pixels_cosmic_ray_flagged_in_any_exposure": int(cosmic_any.sum()),
            },
            "treatment": "no repair, fill, clipping or masking: the delivered values are kept and the saturated core is disclosed; its peak and flux are not faithful and no detail is invented",
            "membership": "no object was masked and all observed structure is retained; membership in NGC 1705 was not determined for individual sources, so unrelated foreground stars or background galaxies cannot be excluded from this single band",
        },
        "normalization": {"rule": "unit total over the full template cutout", "e_per_s_per_unit": total},
        "noise": {
            "policy": "residual observational noise retained; no denoising, smoothing or new noise draws",
            "negative_cells": int(negative.sum()),
            "negative_flux_fraction": float(template[negative].sum()),
        },
        "observational_psf": {
            "policy": "the template keeps Hubble's effective F814W image response (optics, detector, drizzle with gaussian kernel, pixfrac 0.9); it is not removed, modelled or matched",
            "model": "not quantified as a PSF model",
            "indicative_resolution": resolution,
        },
        "peak_cell": float(template.max()),
        "window_flux_fraction": float(template[window, window].sum()),
        "template_array_sha256": identity.sha256_bytes(np.ascontiguousarray(template).tobytes()),
    }
    record["scene_id"] = identity.sha256_bytes(identity.canonical_json_bytes(
        {key: record[key] for key in ("schema", "product", "centre", "target", "resampling", "sky", "quality", "normalization", "template_array_sha256")}
    ))
    return {"template": template, "x_axis": tax, "y_axis": tay, "record": record, "saturated_cells": template_mask_cells}


def _bounds(mask: np.ndarray, x0: int, y0: int) -> Optional[List[List[int]]]:
    if not mask.any():
        return None
    rows, columns = np.nonzero(mask)
    return [[int(columns.min()) + x0, int(columns.max()) + x0 + 1], [int(rows.min()) + y0, int(rows.max()) + y0 + 1]]


def indicative_resolution(science: np.ndarray, cx: float, cy: float, scale_mas: float) -> Dict[str, Any]:
    """Second-moment FWHM of isolated, unsaturated point sources in an annulus (not a PSF model)."""

    from scipy import ndimage

    inner, outer = (r * 1000.0 / scale_mas for r in RESOLUTION_ANNULUS_ARCSEC)
    half = int(math.ceil(outer)) + 13
    x0, y0 = int(round(cx)) - half, int(round(cy)) - half
    sub = science[y0:y0 + 2 * half, x0:x0 + 2 * half]
    peaks = np.argwhere((sub == ndimage.maximum_filter(sub, size=25)) & (sub > 3.0) & (sub < 60.0))
    widths = []
    yy, xx = np.mgrid[-12:13, -12:13]
    rr = np.hypot(xx, yy)
    for py, px in peaks:
        r = math.hypot(px + x0 - cx, py + y0 - cy)
        if not (inner <= r <= outer) or py < 12 or px < 12 or py >= sub.shape[0] - 12 or px >= sub.shape[1] - 12:
            continue
        box = sub[py - 12:py + 13, px - 12:px + 13]
        if np.any(box == 0.0):
            continue
        background = float(np.median(box[rr >= 9]))
        core = box - background
        peak = core[12, 12]
        if np.any(core[rr > 3] > 0.2 * peak):
            continue
        w = np.clip(core, 0.0, None) * (rr <= 4)
        sigma = math.sqrt(float((w * rr ** 2).sum() / w.sum()) / 2.0)
        widths.append(2.3548 * sigma * scale_mas)
    widths = np.array(sorted(widths))
    return {
        "method": f"isolated local maxima 3-60 e-/s, {RESOLUTION_ANNULUS_ARCSEC[0]:g}-{RESOLUTION_ANNULUS_ARCSEC[1]:g} arcsec from the centre, no neighbour above 20 % of the peak within 12 px; FWHM = 2.355 x the background-subtracted second-moment radius within 4 px",
        "sources": int(widths.size),
        "fwhm_mas_median": float(np.median(widths)) if widths.size else None,
        "fwhm_mas_quartiles": [float(np.percentile(widths, 25)), float(np.percentile(widths, 75))] if widths.size else None,
        "caveat": "a crude, estimator-dependent indication of the mosaic's effective resolution (truncated moments of faint sources, some possibly compact clusters); not a measured PSF",
    }
