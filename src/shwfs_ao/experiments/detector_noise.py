"""Monte-Carlo harness for the physical camera noise model (DET-07, E1).

A :class:`NoiseFixture` is one lenslet block: a camera, a centroid window
inside a block of ``window + 2 * guard`` pixels, an expected detected-source
image, sky, exposure and the pixel-processing protocol.  Three estimators of
the centroid scatter are compared:

* :func:`model_prediction` - the ``detector_covariance_v2`` Jacobian model;
* :func:`temporal_trials` - frames with fixed calibration products (the
  frame-to-frame precision the validity gates use);
* :func:`calibration_trials` - independently regenerated products applied to
  the noiseless reference frame (the persistent per-run bias distribution).

Draws are made in chunks whose scratch stays below 64 MiB.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
import math
from typing import Any

import numpy as np

from ..core.random import NamedRandomStreams, with_detector_physics_domains
from ..detector.camera import CameraConfig
from ..detector.camera_maps import CameraMaps
from ..detector.centroid import CentroidConfig
from ..detector.layout import DetectorLayout
from ..detector.noise_model import ExtendedCentroidQuality, detector_covariance_quality
from ..detector.physical import apply_physical_camera
from ..detector.processing import (
    CalibrationProducts,
    PixelProcessingConfig,
    build_calibration_products,
    process_frames,
)


__all__ = (
    "SCRATCH_LIMIT_BYTES",
    "NoiseFixture",
    "gaussian_spot",
    "fixture_products",
    "model_prediction",
    "temporal_trials",
    "calibration_trials",
    "centre_of_gravity",
    "summarize_trials",
)


SCRATCH_LIMIT_BYTES = 64 * 1024**2
_SUBAPERTURE = "lenslet-r0000-c0000"


def gaussian_spot(block_px: int, total_e: float, sigma_px: float, offset_px: tuple[float, float] = (0.0, 0.0)) -> np.ndarray:
    """Pixel-integrated circular Gaussian of ``total_e`` electrons (erf exact)."""

    centre = (block_px - 1) / 2.0
    edges = np.arange(block_px + 1, dtype=float) - 0.5
    erf = np.vectorize(math.erf, otypes=[float])

    def cdf(x: np.ndarray, mean: float) -> np.ndarray:
        return 0.5 * (1.0 + erf((x - mean) / (math.sqrt(2.0) * sigma_px)))

    px = np.diff(cdf(edges, centre + offset_px[0]))
    py = np.diff(cdf(edges, centre + offset_px[1]))
    return total_e * np.outer(py, px)


@dataclass(frozen=True)
class NoiseFixture:
    """One lenslet block with a camera and a processing protocol."""

    camera: CameraConfig
    processing: PixelProcessingConfig
    source_e: np.ndarray
    window_px: int
    guard_px: int = 0
    sky_e_per_pixel: float = 0.0
    exposure_s: float = 1.0e-3
    seed: int = 1
    centroid: CentroidConfig = field(default_factory=CentroidConfig)
    calibration_realization: int = 0

    @property
    def block_px(self) -> int:
        return self.window_px + 2 * self.guard_px

    def layout(self) -> DetectorLayout:
        return DetectorLayout("isolated_lenslet_blocks.v1", 1, self.window_px, self.guard_px)

    def streams(self) -> NamedRandomStreams:
        return with_detector_physics_domains(NamedRandomStreams(self.seed))

    def maps(self) -> CameraMaps:
        return CameraMaps.create(self.camera, self.layout(), (_SUBAPERTURE,), random_streams=self.streams())

    def window(self) -> tuple[slice, slice]:
        return self.layout().window_slice


def fixture_products(fixture: NoiseFixture, *, realization: int | None = None) -> CalibrationProducts | None:
    if fixture.processing.mode == "raw_readout":
        return None
    index = fixture.calibration_realization if realization is None else realization
    return build_calibration_products(
        fixture.camera,
        fixture.maps(),
        fixture.processing,
        exposure_s=fixture.exposure_s,
        sky_e_per_pixel=fixture.sky_e_per_pixel,
        random_streams=fixture.streams().scoped("fixture_products", key=(int(index),)),
    )


def model_prediction(fixture: NoiseFixture, products: CalibrationProducts | None = None) -> ExtendedCentroidQuality:
    maps = fixture.maps()
    arrays = maps.subset(np.arange(1))
    products = fixture_products(fixture) if products is None else products
    batch = apply_physical_camera(
        fixture.source_e[None],
        fixture.sky_e_per_pixel,
        fixture.camera,
        arrays,
        exposure_s=fixture.exposure_s,
        include_noise=False,
        generators=None,
        poisson_floor_e=0.0,
    )
    return detector_covariance_quality(
        expected_source_e=batch.expected_source_e,
        expected_background_e=batch.expected_background_e,
        camera=fixture.camera,
        maps=arrays,
        products=products,
        processing=fixture.processing,
        centroid_config=fixture.centroid,
        window=fixture.window(),
        sky_e_per_pixel=fixture.sky_e_per_pixel,
        dark_e_map=maps.dark_rate_e_per_s(fixture.camera) * fixture.exposure_s,
        optical_response=maps.optical_response(),
    )


def centre_of_gravity(images: np.ndarray, config: CentroidConfig | None = None) -> np.ndarray:
    """Independent CoG (optionally thresholded) of a batch of windows."""

    resolved = CentroidConfig() if config is None else config
    values = np.array(images, dtype=float)
    if resolved.subtract_minimum:
        values = np.maximum(values - values.min(axis=(1, 2), keepdims=True), 0.0)
    if resolved.estimator == "thresholded_center_of_gravity" and resolved.threshold_fraction > 0.0:
        peaks = values.max(axis=(1, 2), keepdims=True)
        values = np.where(values < resolved.threshold_fraction * peaks, 0.0, values)
    total = values.sum(axis=(1, 2))
    rows, columns = values.shape[1:]
    with np.errstate(invalid="ignore", divide="ignore"):
        cx = np.einsum("nrc,c->n", values, np.arange(columns, dtype=float)) / total
        cy = np.einsum("nrc,r->n", values, np.arange(rows, dtype=float)) / total
    result = np.stack([cx, cy], axis=1)
    result[~(total > 0.0)] = np.nan
    return result


def _chunk(fixture: NoiseFixture) -> int:
    per_trial = fixture.block_px**2 * 8 * 12
    return max(1, SCRATCH_LIMIT_BYTES // per_trial)


def temporal_trials(
    fixture: NoiseFixture,
    trials: int,
    *,
    products: CalibrationProducts | None = None,
    return_processed: bool = False,
) -> dict[str, Any]:
    """Centroids of ``trials`` noisy frames with fixed calibration products."""

    maps = fixture.maps()
    arrays = maps.subset(np.arange(1))
    products = fixture_products(fixture) if products is None else products
    provider = fixture.streams().scoped("temporal_trials")
    generators = {domain: provider.generator(domain) for domain in (
        "detector.shot_noise", "detector.cic", "detector.em_gain", "detector.read_noise"
    )}
    rows, cols = fixture.window()
    centroids = []
    processed_sum = None
    processed_outer: dict[str, Any] = {}
    kept = []
    remaining = int(trials)
    chunk = _chunk(fixture)
    while remaining > 0:
        count = min(chunk, remaining)
        remaining -= count
        repeated = {
            key: (None if value is None else np.repeat(value, count, axis=0))
            for key, value in arrays.items()
        }
        batch = apply_physical_camera(
            np.repeat(fixture.source_e[None], count, axis=0),
            fixture.sky_e_per_pixel,
            fixture.camera,
            repeated,
            exposure_s=fixture.exposure_s,
            include_noise=True,
            generators=lambda index, domain: generators[domain],
            poisson_floor_e=0.0,
        )
        processed = process_frames(
            batch.raw, products, fixture.processing, indices=np.zeros(count, dtype=int)
        )
        window = processed[:, rows, cols]
        centroids.append(centre_of_gravity(window, fixture.centroid))
        if return_processed:
            kept.append(processed)
    result: dict[str, Any] = {"centroids_px": np.concatenate(centroids), "products": products}
    if return_processed:
        result["processed"] = np.concatenate(kept)
    del processed_sum, processed_outer
    return result


def calibration_trials(fixture: NoiseFixture, realizations: int, *, first: int = 1) -> dict[str, Any]:
    """Noiseless-frame centroids processed with independently regenerated products."""

    maps = fixture.maps()
    arrays = maps.subset(np.arange(1))
    batch = apply_physical_camera(
        fixture.source_e[None],
        fixture.sky_e_per_pixel,
        fixture.camera,
        arrays,
        exposure_s=fixture.exposure_s,
        include_noise=False,
        generators=None,
        poisson_floor_e=0.0,
    )
    rows, cols = fixture.window()
    centroids = []
    for realization in range(first, first + int(realizations)):
        products = fixture_products(fixture, realization=realization)
        processed = process_frames(batch.raw, products, fixture.processing)
        centroids.append(centre_of_gravity(processed[:, rows, cols], fixture.centroid)[0])
    return {"centroids_px": np.array(centroids)}


def summarize_trials(centroids: np.ndarray) -> dict[str, float]:
    """Mean, standard deviation and its standard error per axis."""

    finite = centroids[np.all(np.isfinite(centroids), axis=1)]
    count = finite.shape[0]
    std = finite.std(axis=0, ddof=1) if count > 1 else np.full(2, math.nan)
    return {
        "trials": int(centroids.shape[0]),
        "finite_trials": int(count),
        "invalid_fraction": float(1.0 - count / max(centroids.shape[0], 1)),
        "mean_x_px": float(finite[:, 0].mean()) if count else math.nan,
        "mean_y_px": float(finite[:, 1].mean()) if count else math.nan,
        "std_x_px": float(std[0]),
        "std_y_px": float(std[1]),
        "std_relative_se": float(1.0 / math.sqrt(2.0 * max(count - 1, 1))),
    }


def with_source(fixture: NoiseFixture, total_e: float, sigma_px: float = 1.2) -> NoiseFixture:
    """The fixture with a centred Gaussian spot of ``total_e`` electrons."""

    return replace(fixture, source_e=gaussian_spot(fixture.block_px, total_e, sigma_px))
