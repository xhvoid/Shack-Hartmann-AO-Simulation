"""HCIPy microlens-array optics behind the canonical Shack-Hartmann boundary.

The adapter owns every repository-facing convention; HCIPy provides only the
parabolic microlens array and the Fresnel propagation to its focal plane:

- ``spot_intensities(residual_opd_m)`` returns the Section 4
  ``SpotIntensityResult`` and nothing detector-specific: one finite,
  non-negative, unit-sum, full-window spot per retained repository
  subaperture ID, in the exact geometry order, with relative lenslet
  throughput reported separately.  Detector noise, centroiding, and validity
  remain the repository detector chain.
- The microlens array is built at the repository's nominal lenslet cell
  centres — including cells the geometry rejected, so their light is still
  focused by a lens instead of leaking unphysically — and HCIPy's
  closest-centre lenslet assignment provably reproduces the repository
  index-block partition; construction verifies that equivalence and fails
  loudly on any drift.
- The detector plane is the pupil-sampled focal plane: each retained
  subaperture's window is its own pixel block, ``pixel_scale_rad`` is the
  detector pixel pitch divided by the lenslet focal length, and the window
  reference pixel is the nominal window centre.  The per-lenslet subpixel
  offset of each optical axis is real, deterministic, and absorbed by the
  repository zero-phase reference calibration, exactly as for the native
  backend.
- The repository phase convention ``phase = 2π · OPD / λ`` and detector
  orientation are preserved: increasing positive x-tilt moves the reported
  spot toward increasing detector column x, and positive y-tilt toward
  increasing detector row y.  HCIPy's chain was measured to satisfy this
  directly; the sign tests pin it.
- The optional HCIPy estimator is exposed only as comparison telemetry
  through :meth:`hcipy_estimator_centroids_px`; it never enters the
  measurement path, and no HCIPy ``Field`` or estimator result crosses the
  backend boundary.

Importing this module never imports HCIPy; repository-side validation runs
before the optional dependency is resolved, so invalid construction raises
:class:`HcipyShackHartmannError` even on installations without HCIPy.
"""

from __future__ import annotations

import math
from numbers import Real
import warnings

import numpy as np

from ...core.hashing import component_config_hash
from ...core.types import DetectorPlaneSampling, SpotIntensityResult
from ...wfs.shack_hartmann.geometry import (
    ShackHartmannGeometry,
    lenslet_indices_from_id,
)
from ...wfs.shack_hartmann.optics import (
    make_detector_plane_sampling,
    validate_spot_intensity_result,
)
from . import hcipy_version, require_hcipy
from .conversion import (
    HcipyConversionError,
    hcipy_grid_from_coordinates,
    wavefront_from_opd,
)


_BACKEND_NAME = "hcipy"
_PROPAGATION_ID = "parabolic-mla-fresnel-focal-plane-v1"
"""Identifier of the HCIPy optical construction (part of the config hash)."""

_WINDOW_MAPPING_ID = "nominal-index-block-windows-center-reference-v1"
"""Identifier of the field-to-window extraction (part of the config hash)."""

_THROUGHPUT_SEMANTICS = "window_flux_over_lenslet_input_flux_clipped"
"""Meaning of ``relative_throughput``: detector-window capture fraction."""

__all__ = (
    "HcipyShackHartmannError",
    "HcipyShackHartmannOptics",
)


class HcipyShackHartmannError(ValueError):
    """Raised when HCIPy SH-WFS construction or propagation input is invalid."""


class HcipyShackHartmannOptics:
    """HCIPy Fresnel microlens backend for the canonical SH-WFS optics contract.

    Parameters
    ----------
    geometry:
        Validated repository lenslet geometry.  Every pupil axis must contain
        an integer number of pixels per lenslet so each retained subaperture
        maps to one full detector window; other samplings remain the native
        backend's territory.
    wfs_wavelength_m:
        Wavelength converting residual OPD to phase.  It is explicit; there
        is no default.
    f_number:
        Lenslet focal ratio.  The focal length is ``f_number`` times the
        lenslet pitch, and the diffraction-limited spot then spans
        ``λ · f_number / pixel_pitch`` detector pixels.

    Notes
    -----
    The instance holds only HCIPy's own optical state (grid, microlens
    array, propagator).  It is memoryless with respect to measurements: the
    same residual OPD always produces the same spots.
    """

    def __init__(
        self,
        geometry: ShackHartmannGeometry,
        wfs_wavelength_m: float,
        *,
        f_number: float,
    ) -> None:
        if not isinstance(geometry, ShackHartmannGeometry):
            raise HcipyShackHartmannError(
                "geometry must be a ShackHartmannGeometry."
            )
        wavelength_m = _positive("wfs_wavelength_m", wfs_wavelength_m)
        focal_ratio = _positive("f_number", f_number)

        rows, columns = geometry.pupil_shape
        count = geometry.n_lenslets_across
        if rows % count != 0 or columns % count != 0:
            raise HcipyShackHartmannError(
                f"pupil_shape {geometry.pupil_shape} must be an integer "
                f"multiple of n_lenslets_across {count} per axis for the "
                "HCIPy block-window backend; use the native backend for "
                "other samplings."
            )
        window_rows = rows // count
        window_columns = columns // count

        dx_m = float(geometry.x_m[0, 1] - geometry.x_m[0, 0])
        dy_m = float(geometry.y_m[1, 0] - geometry.y_m[0, 0])
        lenslet_pitch_m = geometry.telescope_diameter_m / count
        focal_length_m = focal_ratio * lenslet_pitch_m
        sampling = make_detector_plane_sampling(
            window_shape_px=(window_rows, window_columns),
            pixel_scale_rad=(dx_m / focal_length_m, dy_m / focal_length_m),
            reference_pixel_xy=(
                0.5 * (window_columns - 1),
                0.5 * (window_rows - 1),
            ),
        )

        window_slices, lenslet_input_flux = _validated_block_windows(
            geometry,
            window_rows=window_rows,
            window_columns=window_columns,
        )
        nominal_centers_xy_m = _nominal_cell_centers_xy_m(geometry)
        _validate_retained_centers(geometry, nominal_centers_xy_m)

        self._geometry = geometry
        self._wfs_wavelength_m = wavelength_m
        self._f_number = focal_ratio
        self._focal_length_m = focal_length_m
        self._sampling = sampling
        self._window_slices = window_slices
        self._lenslet_input_flux = lenslet_input_flux
        self._config_hash = component_config_hash(
            "hcipy.shack_hartmann_optics",
            {
                "geometry_hash": geometry.geometry_hash,
                "wfs_wavelength_m": wavelength_m,
                "f_number": focal_ratio,
                "focal_length_m": focal_length_m,
                "window_shape_px": (window_rows, window_columns),
                "detector_sampling_hash": sampling.sampling_hash,
                "nominal_lenslet_centers_xy_m": nominal_centers_xy_m,
                "propagation": _PROPAGATION_ID,
                "window_mapping": _WINDOW_MAPPING_ID,
                "relative_throughput_semantics": _THROUGHPUT_SEMANTICS,
                "remove_local_piston": False,
            },
        )

        # Resolving the optional dependency is the last construction step, so
        # every repository-side validation error above is raised even on
        # installations without HCIPy.
        hcipy = require_hcipy()
        self._hcipy_version = hcipy_version()
        try:
            self._grid = hcipy_grid_from_coordinates(geometry.x_m, geometry.y_m)
        except HcipyConversionError as exc:
            raise HcipyShackHartmannError(str(exc)) from exc
        self._lenslet_grid = hcipy.CartesianGrid(
            hcipy.UnstructuredCoords(
                (
                    np.array(nominal_centers_xy_m[:, 0], copy=True),
                    np.array(nominal_centers_xy_m[:, 1], copy=True),
                )
            ),
            lenslet_pitch_m**2,
        )
        self._micro_lens_array = hcipy.MicroLensArray(
            self._grid,
            self._lenslet_grid,
            focal_length_m,
        )
        self._propagator = hcipy.FresnelPropagator(self._grid, focal_length_m)
        _validate_mla_assignment(
            self._micro_lens_array,
            geometry,
            window_rows=window_rows,
            window_columns=window_columns,
        )

    @property
    def backend_name(self) -> str:
        return _BACKEND_NAME

    @property
    def config_hash(self) -> str:
        return self._config_hash

    @property
    def geometry(self) -> ShackHartmannGeometry:
        return self._geometry

    @property
    def geometry_hash(self) -> str:
        return self._geometry.geometry_hash

    @property
    def wfs_wavelength_m(self) -> float:
        return self._wfs_wavelength_m

    @property
    def f_number(self) -> float:
        return self._f_number

    @property
    def focal_length_m(self) -> float:
        return self._focal_length_m

    @property
    def hcipy_backend_version(self) -> str:
        return self._hcipy_version

    @property
    def sampling(self) -> DetectorPlaneSampling:
        return self._sampling

    @property
    def detector_sampling(self) -> DetectorPlaneSampling:
        """Calibration-facing alias for :attr:`sampling`."""

        return self._sampling

    @property
    def subaperture_ids(self) -> tuple[str, ...]:
        return self._geometry.subaperture_ids

    def spot_intensities(self, residual_opd_m: np.ndarray) -> SpotIntensityResult:
        """Return one unit-sum noiseless detector-window spot per lenslet."""

        intensity = self._focal_plane_intensity(residual_opd_m)
        spots: list[np.ndarray] = []
        capture_fractions: list[float] = []
        for index, (y_slice, x_slice) in enumerate(self._window_slices):
            window = np.array(
                intensity[y_slice, x_slice],
                dtype=float,
                copy=True,
            )
            total = float(np.sum(window, dtype=np.float64))
            if not math.isfinite(total) or total <= 0.0:
                raise HcipyShackHartmannError(
                    f"Lenslet {self._geometry.subaperture_ids[index]!r} has "
                    "no finite intensity inside its detector window."
                )
            capture_fractions.append(
                float(
                    np.clip(total / self._lenslet_input_flux[index], 0.0, 1.0)
                )
            )
            spots.append(window / total)

        rows, columns = self._sampling.window_shape_px
        reference_x, reference_y = self._sampling.reference_pixel_xy
        x_axis = np.arange(columns, dtype=float) - reference_x
        y_axis = np.arange(rows, dtype=float) - reference_y
        result = SpotIntensityResult(
            unit_sum_spots=tuple(spots),
            subaperture_ids=self._geometry.subaperture_ids,
            relative_throughput=np.asarray(capture_fractions, dtype=float),
            x_px=tuple(x_axis for _ in spots),
            y_px=tuple(y_axis for _ in spots),
            sampling=self._sampling,
            normalization="unit_sum_per_subaperture",
        )
        return validate_spot_intensity_result(
            result,
            self._geometry,
            sampling=self._sampling,
        )

    def hcipy_estimator_centroids_px(
        self,
        residual_opd_m: np.ndarray,
    ) -> np.ndarray:
        """Return HCIPy's own centroid estimates as comparison telemetry.

        The result is a plain read-only ``(n_subapertures, 2)`` array of
        ``(x, y)`` centroid offsets in detector pixels relative to each
        retained lenslet's optical axis, in repository subaperture order.
        This diagnostic never participates in calibration or measurement and
        must not be written into ``WfsMeasurement``.
        """

        hcipy = require_hcipy()
        intensity = self._focal_plane_intensity(residual_opd_m)
        geometry = self._geometry
        count = geometry.n_lenslets_across
        nominal_indices = np.asarray(
            [
                row * count + column
                for row, column in (
                    lenslet_indices_from_id(identifier)
                    for identifier in geometry.subaperture_ids
                )
            ],
            dtype=int,
        )
        retained = np.zeros(count * count, dtype=bool)
        retained[nominal_indices] = True
        estimator = hcipy.ShackHartmannWavefrontSensorEstimator(
            self._lenslet_grid,
            self._micro_lens_array.mla_index,
            estimation_subapertures=retained,
        )
        try:
            # HCIPy 0.7 reaches scipy.ndimage.measurements, a namespace the
            # pinned SciPy still provides but marks deprecated; silence only
            # that noise for exactly this diagnostic call.
            with warnings.catch_warnings():
                warnings.simplefilter("ignore", DeprecationWarning)
                raw_estimate = estimator.estimate(
                    [hcipy.Field(intensity.ravel(order="C"), self._grid)]
                )
        except Exception as exc:
            raise HcipyShackHartmannError(
                "The HCIPy comparison estimator failed in this environment."
            ) from exc
        estimate_m = np.asarray(raw_estimate, dtype=float)
        if estimate_m.shape != (2, nominal_indices.size):
            raise HcipyShackHartmannError(
                "HCIPy estimator returned an unexpected centroid shape "
                f"{estimate_m.shape}."
            )
        # The estimator orders columns by ascending nominal lenslet index;
        # map them back onto the repository subaperture order.
        estimator_position = np.argsort(np.argsort(nominal_indices))
        dx_m = float(geometry.x_m[0, 1] - geometry.x_m[0, 0])
        dy_m = float(geometry.y_m[1, 0] - geometry.y_m[0, 0])
        centroids_px = np.column_stack(
            (
                estimate_m[0, estimator_position] / dx_m,
                estimate_m[1, estimator_position] / dy_m,
            )
        )
        if not np.all(np.isfinite(centroids_px)):
            raise HcipyShackHartmannError(
                "HCIPy estimator returned non-finite centroids."
            )
        return _readonly_copy(centroids_px)

    def _focal_plane_intensity(self, residual_opd_m: np.ndarray) -> np.ndarray:
        opd_m = _validated_residual_opd(residual_opd_m, self._geometry)
        try:
            wavefront = wavefront_from_opd(
                opd_m,
                self._geometry.pupil_mask,
                self._grid,
                wavelength_m=self._wfs_wavelength_m,
            )
        except HcipyConversionError as exc:
            raise HcipyShackHartmannError(str(exc)) from exc
        focal_wavefront = self._propagator.forward(
            self._micro_lens_array.forward(wavefront)
        )
        intensity = np.asarray(focal_wavefront.intensity, dtype=float).reshape(
            self._geometry.pupil_shape
        )
        if not np.all(np.isfinite(intensity)):
            raise HcipyShackHartmannError(
                "HCIPy propagation produced non-finite focal intensity."
            )
        return intensity


def _nominal_cell_centers_xy_m(geometry: ShackHartmannGeometry) -> np.ndarray:
    """Return all nominal lenslet cell centres in nominal-index order.

    The nominal flat index is ``row * n_lenslets_across + column``, matching
    the repository lenslet cell edges spanning the sampled pupil extent.
    """

    count = geometry.n_lenslets_across
    x_edges_m = np.linspace(
        float(np.min(geometry.x_m)),
        float(np.max(geometry.x_m)),
        count + 1,
    )
    y_edges_m = np.linspace(
        float(np.min(geometry.y_m)),
        float(np.max(geometry.y_m)),
        count + 1,
    )
    x_centers_m = 0.5 * (x_edges_m[:-1] + x_edges_m[1:])
    y_centers_m = 0.5 * (y_edges_m[:-1] + y_edges_m[1:])
    centers = [
        (float(x_centers_m[column]), float(y_centers_m[row]))
        for row in range(count)
        for column in range(count)
    ]
    return np.asarray(centers, dtype=float)


def _validate_retained_centers(
    geometry: ShackHartmannGeometry,
    nominal_centers_xy_m: np.ndarray,
) -> None:
    count = geometry.n_lenslets_across
    scale_m = max(float(geometry.telescope_diameter_m), 1.0)
    for identifier, expected_xy_m in zip(
        geometry.subaperture_ids,
        geometry.subaperture_centers_m,
    ):
        row, column = lenslet_indices_from_id(identifier)
        nominal_xy_m = nominal_centers_xy_m[row * count + column]
        if not np.allclose(
            nominal_xy_m,
            np.asarray(expected_xy_m, dtype=float),
            rtol=0.0,
            atol=1.0e-9 * scale_m,
        ):
            raise HcipyShackHartmannError(
                f"Nominal cell centre for {identifier!r} does not match the "
                "geometry subaperture centre."
            )


def _validated_block_windows(
    geometry: ShackHartmannGeometry,
    *,
    window_rows: int,
    window_columns: int,
) -> tuple[tuple[tuple[slice, slice], ...], tuple[float, ...]]:
    """Derive each retained lenslet's pixel block and validate mask identity."""

    window_slices: list[tuple[slice, slice]] = []
    input_flux: list[float] = []
    for identifier, mask in zip(
        geometry.subaperture_ids,
        geometry.subaperture_masks,
    ):
        row, column = lenslet_indices_from_id(identifier)
        y_slice = slice(row * window_rows, (row + 1) * window_rows)
        x_slice = slice(column * window_columns, (column + 1) * window_columns)
        block = np.zeros(geometry.pupil_shape, dtype=bool)
        block[y_slice, x_slice] = True
        expected_mask = block & np.asarray(geometry.pupil_mask, dtype=bool)
        if not np.array_equal(np.asarray(mask, dtype=bool), expected_mask):
            raise HcipyShackHartmannError(
                f"Retained subaperture {identifier!r} does not coincide with "
                "its nominal pixel block; the HCIPy window mapping cannot "
                "represent this geometry."
            )
        illuminated = int(np.count_nonzero(expected_mask))
        if illuminated == 0:
            raise HcipyShackHartmannError(
                f"Retained subaperture {identifier!r} has no illuminated "
                "samples."
            )
        window_slices.append((y_slice, x_slice))
        input_flux.append(float(illuminated))
    return tuple(window_slices), tuple(input_flux)


def _validate_mla_assignment(
    micro_lens_array: object,
    geometry: ShackHartmannGeometry,
    *,
    window_rows: int,
    window_columns: int,
) -> None:
    """Require HCIPy's closest-centre lenslet map to equal the block partition."""

    count = geometry.n_lenslets_across
    assignment = np.asarray(
        micro_lens_array.mla_index,  # type: ignore[attr-defined]
        dtype=int,
    ).reshape(geometry.pupil_shape)
    expected_rows = np.repeat(np.arange(count), window_rows)
    expected_columns = np.repeat(np.arange(count), window_columns)
    expected = (
        expected_rows[:, None] * count + expected_columns[None, :]
    )
    if not np.array_equal(assignment, expected):
        raise HcipyShackHartmannError(
            "HCIPy closest-centre lenslet assignment does not reproduce the "
            "repository index-block partition."
        )


def _validated_residual_opd(
    value: object,
    geometry: ShackHartmannGeometry,
) -> np.ndarray:
    try:
        opd_m = np.asarray(value, dtype=float)
    except (TypeError, ValueError) as exc:
        raise HcipyShackHartmannError(
            "residual_opd_m must be a numeric array."
        ) from exc
    if opd_m.shape != geometry.pupil_shape:
        raise HcipyShackHartmannError(
            f"residual_opd_m shape {opd_m.shape} does not match geometry "
            f"pupil_shape {geometry.pupil_shape}."
        )
    if np.any(np.isinf(opd_m)):
        raise HcipyShackHartmannError(
            "residual_opd_m must not contain infinite values."
        )
    if not np.all(np.isfinite(opd_m[geometry.pupil_mask])):
        raise HcipyShackHartmannError(
            "residual_opd_m must be finite throughout the illuminated pupil."
        )
    return opd_m


def _positive(field_name: str, value: object) -> float:
    if isinstance(value, (bool, np.bool_)) or not isinstance(value, Real):
        raise HcipyShackHartmannError(
            f"{field_name} must be a positive finite scalar; got {value!r}."
        )
    number = float(value)
    if not math.isfinite(number) or number <= 0.0:
        raise HcipyShackHartmannError(
            f"{field_name} must be a positive finite scalar; got {value!r}."
        )
    return number


def _readonly_copy(values: np.ndarray) -> np.ndarray:
    contiguous = np.ascontiguousarray(np.array(values, dtype=float, copy=True))
    result = np.frombuffer(contiguous.tobytes(order="C"), dtype=contiguous.dtype)
    return result.reshape(contiguous.shape)
