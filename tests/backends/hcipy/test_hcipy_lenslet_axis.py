"""The HCIPy lenslet axis must sit on the centre of its detector window.

``HcipyShackHartmannOptics`` measures every lenslet on its own pixel block and
centroids it about the block centre.  The published convention
(``high_order_10m_hcipy`` @1-@3) puts each microlens vertex at the geometry's
continuous cell centre instead.  Those cells span the first to the last pixel
*centre*, so they are ``(N - 1)/n`` pixels wide while the blocks are ``N/n``,
and the spot axis drifts across the blocks by up to half a pixel.  The window
is then asymmetric about the spot by an amount antisymmetric across the pupil,
and spot broadening turns that into a focus-shaped slope bias that the
zero-phase reference cannot absorb
(``docs/refactor/AO_REF_016A_HCIPY_LENSLET_AXIS.md``).

The default checks use a WFS-only analogue of the published sensor that fits
the desktop-safe fixture limits: 80 pupil pixels and 10 lenslets across at the
published 0.2083 m pitch, pad 4 (4 detector pixels per lambda/d), 8-pixel
block windows and the published 750 nm sensing wavelength, built through the
registered HCIPy factory.  No atmosphere model, DM, interaction matrix or loop
is constructed.  The published convention is kept as a strict expected failure
of each check, which shows that each check detects the defect and pins the
@1-@3 behaviour as published.

HCIPy propagates all lenslets together, and an 8-pixel window is only
2 lambda/d wide, so a broadened spot spills into its neighbours' windows.  An
interior window gets that spill from both sides; a window on the pupil
boundary gets it from one side only, which leaves an inward slope that is
independent of the lenslet axis.  In a 10-lenslet pupil the boundary is most
of the pupil and even the interior lenslets are only one ring deep.  So the
analogue's even-part check uses a deterministic defocus on interior lenslets,
with a threshold set between that shared spill floor and the published defect.
The clean comparison runs at the published 48-lenslet geometry, behind the
``elt_scale`` gate, because it needs about 0.7 GiB.

Every test requires the optional HCIPy dependency and carries the ``hcipy``
marker.  The module imports only the installed package.
"""

from __future__ import annotations

from dataclasses import replace
import math

import numpy as np
import pytest


hcipy = pytest.importorskip("hcipy")

from shwfs_ao.backends.hcipy.factory import HcipyScaoFactoryError
from shwfs_ao.backends.hcipy.shwfs import (
    HcipyShackHartmannError,
    HcipyShackHartmannOptics,
)
from shwfs_ao.core.random import NamedRandomStreams
from shwfs_ao.experiments import scao
from shwfs_ao.io.configs import load_system_profile
from shwfs_ao.wfs.shack_hartmann.geometry import lenslet_indices_from_id


pytestmark = pytest.mark.hcipy


ANALOGUE_PUPIL_PIXELS = 80
ANALOGUE_LENSLETS_ACROSS = 10
PUBLISHED_AXIS = "geometry_cell_center"
BLOCK_AXIS = "pixel_block_center"
# The published convention fails both checks below; strict, so a change that
# made it pass would be reported instead of silently relabelling @1-@3.
CONVENTIONS = (
    pytest.param(
        PUBLISHED_AXIS,
        marks=pytest.mark.xfail(
            strict=True,
            raises=AssertionError,
            reason=(
                "high_order_10m_hcipy@1-@3 lenslet axes drift across their "
                "8-pixel block windows (AO-REF-016A)"
            ),
        ),
        id="published_cell_center",
    ),
    pytest.param(BLOCK_AXIS, id="block_center"),
)

# Flat-reference spread of the 32 interior lenslets (measured 2026-10-15):
# block_center 0.0096 px with a 0.00074 px/index column trend (2.1x and 2.7x
# under the limits below), published 0.52 px and -0.104 px/index (26x and
# 52x over).
FLAT_REFERENCE_COLUMN_SPREAD_TOL_PX = 0.02
# Even-part focus gradients below were measured with both conventions on
# 2026-10-15 (Linux cloud VM, hcipy 0.7.0, numpy 2.5.0).  Each threshold is
# the geometric mean of the block-centre value and the published value, so
# both sides keep the same margin.
#
# 10-lenslet analogue, 100 nm block-centred defocus, interior lenslets:
# block_center 0.0078 px/m (neighbour-spill floor), published 0.0514 px/m.
# Margin 2.6x each side.
DEFOCUS_EDGE_OPD_M = 100.0e-9
ANALOGUE_EVEN_FOCUS_GRADIENT_TOL_PX_PER_M = 0.02
# Published 48-lenslet geometry, interior lenslets.  Defocus as above:
# block_center 0.00024 px/m, published 0.0081 px/m (margin 5.8x each side).
# Tilt-removed residual screens 0 and 1: block_center at most 0.00053 px/m,
# published at least 0.0185 px/m (margin about 6x each side).
PUBLISHED_EVEN_FOCUS_GRADIENT_TOL_PX_PER_M = 0.0014
PUBLISHED_RESIDUAL_FOCUS_GRADIENT_TOL_PX_PER_M = 0.003
RESIDUAL_SEED = 20261015
RESIDUAL_SCREENS = 2


@pytest.fixture(scope="module")
def analogue():
    """The published @3 sensor with only the pupil cut to 10 lenslets."""

    published = load_system_profile("high_order_10m_hcipy", 3)
    pitch_m = published.telescope_diameter_m / published.lenslets_across
    config = replace(
        published,
        pupil_pixels=ANALOGUE_PUPIL_PIXELS,
        lenslets_across=ANALOGUE_LENSLETS_ACROSS,
        telescope_diameter_m=pitch_m * ANALOGUE_LENSLETS_ACROSS,
    )
    return _hcipy_sensors(config)


@pytest.fixture(scope="module")
def published_scale():
    """The published @3 sensor at its own 384-pixel, 48-lenslet geometry.

    Only ``elt_scale`` tests request it, and ``tests/conftest.py`` skips those
    before any fixture is set up unless ``--enable-elt-scale`` is passed.
    """

    return _hcipy_sensors(load_system_profile("high_order_10m_hcipy", 3))


def _hcipy_sensors(config):
    """Build ``config``'s geometry and a per-convention sensor builder."""

    factory = scao._factory_for("hcipy")
    geometry = factory.build_geometry(
        telescope_diameter_m=config.telescope_diameter_m,
        pupil_pixels=config.pupil_pixels,
        lenslets_across=config.lenslets_across,
        min_fill_fraction=config.wfs.min_fill_fraction,
        central_obstruction_ratio=config.wfs.central_obstruction_ratio,
        spider_width_m=config.wfs.spider_width_m,
    )
    sensors = {}

    def sensor(lenslet_axis: str):
        if lenslet_axis not in sensors:
            # build_scao_system passes the keyword only for a profile that
            # opts in, so the published path is built without it.
            keywords = (
                {} if lenslet_axis == PUBLISHED_AXIS
                else {"lenslet_axis": lenslet_axis}
            )
            sensors[lenslet_axis] = factory.build_wfs(
                model=config.wfs_model,
                geometry=geometry,
                wfs_wavelength_m=config.wfs_wavelength_m,
                pad_factor=config.wfs.pad_factor,
                detector_window_px=config.wfs.detector_window_px,
                detector_config=scao._detector_config(config),
                centroid_config=scao._centroid_config(config),
                validity_config=scao._validity_config(config),
                random_streams=NamedRandomStreams(config.random.root_seed),
                photon_allocation=config.wfs.photon_allocation,
                clip_negative_pixels=config.wfs.clip_negative_pixels,
                **keywords,
            )
        return sensors[lenslet_axis]

    return config, geometry, sensor


def _row_column(geometry) -> np.ndarray:
    return np.asarray(
        [lenslet_indices_from_id(identifier) for identifier in geometry.subaperture_ids]
    )


def _interior(geometry) -> np.ndarray:
    """Full lenslets whose eight neighbours are full lenslets as well.

    Their spots see the same neighbour crosstalk on every side, so only the
    position of the axis inside the block can move their flat centroid.
    """

    block = geometry.pupil_shape[0] // geometry.n_lenslets_across
    indices = _row_column(geometry)
    full = {
        (int(row), int(column))
        for (row, column), mask in zip(indices, geometry.subaperture_masks)
        if int(np.count_nonzero(mask)) == block * block
    }
    return np.asarray(
        [
            all(
                (int(row) + d_row, int(column) + d_column) in full
                for d_row in (-1, 0, 1)
                for d_column in (-1, 0, 1)
            )
            for row, column in indices
        ]
    )


def _von_karman_opd_m(config, geometry, rng) -> np.ndarray:
    """One FFT von Karman OPD screen at the profile's r0 and outer scale."""

    rows, columns = geometry.pupil_shape
    dx_m = float(geometry.x_m[0, 1] - geometry.x_m[0, 0])
    size = 2 * rows
    frequencies = np.fft.fftfreq(size, dx_m)
    fx, fy = np.meshgrid(frequencies, frequencies)
    outer_scale_m = config.atmosphere.outer_scale_m
    r0_m = config.atmosphere.r0_m
    psd = 0.023 * r0_m ** (-5.0 / 3.0) * (
        fx**2 + fy**2 + outer_scale_m**-2
    ) ** (-11.0 / 6.0)
    psd[0, 0] = 0.0
    coefficients = (
        rng.standard_normal((size, size)) + 1j * rng.standard_normal((size, size))
    ) * np.sqrt(psd) / (size * dx_m)
    phase_rad = np.real(np.fft.ifft2(coefficients))[:rows, :columns] * size * size
    return phase_rad * config.atmosphere.r0_reference_wavelength_m / (2.0 * math.pi)


def _tilt_removed(opd_m: np.ndarray, geometry) -> np.ndarray:
    """Remove piston and least-squares tilt inside every lenslet.

    What is left is a closed-loop-like residual: its intra-lenslet structure
    broadens the spots without moving them.
    """

    residual = np.zeros_like(opd_m)
    for mask in geometry.subaperture_masks:
        inside = np.asarray(mask, dtype=bool)
        basis = np.column_stack(
            (
                np.ones(int(np.count_nonzero(inside))),
                geometry.x_m[inside],
                geometry.y_m[inside],
            )
        )
        coefficients, *_ = np.linalg.lstsq(basis, opd_m[inside], rcond=None)
        residual[inside] = opd_m[inside] - basis @ coefficients
    return residual


def _block_defocus_opd_m(config, geometry, edge_opd_m: float) -> np.ndarray:
    """The same defocus in every lenslet, centred on its pixel block.

    ``edge_opd_m`` is the OPD at the middle of a block edge.  Each lenslet's
    phase is then symmetric about its aperture centre, so it has no true slope
    and its spot is symmetric about the lens axis.
    """

    block = geometry.pupil_shape[0] // geometry.n_lenslets_across
    half_pitch_m = 0.5 * config.telescope_diameter_m / config.lenslets_across
    opd_m = np.zeros(geometry.pupil_shape)
    for identifier, mask in zip(geometry.subaperture_ids, geometry.subaperture_masks):
        row, column = lenslet_indices_from_id(identifier)
        x0_m = float(np.mean(geometry.x_m[0, column * block:(column + 1) * block]))
        y0_m = float(np.mean(geometry.y_m[row * block:(row + 1) * block, 0]))
        inside = np.asarray(mask, dtype=bool)
        dx_m = geometry.x_m[inside] - x0_m
        dy_m = geometry.y_m[inside] - y0_m
        opd_m[inside] = edge_opd_m * (dx_m * dx_m + dy_m * dy_m) / half_pitch_m**2
    return opd_m


def _even_part_px(sensor, opd_m: np.ndarray, root_seed: int) -> tuple[np.ndarray, np.ndarray]:
    """``[s(phi) + s(-phi)]/2`` and the lenslets valid for both signs.

    ``phi -> -phi`` point-reflects each lenslet's own spot about its axis, so
    for a window symmetric about the axis the even part keeps only neighbour
    crosstalk.  For the published axes it also holds the window asymmetry,
    an outward slope pattern that a closed loop cancels with a static focus.
    """

    plus, plus_valid = _slopes_px(sensor, opd_m, root_seed)
    minus, minus_valid = _slopes_px(sensor, -opd_m, root_seed)
    return 0.5 * (plus + minus), plus_valid & minus_valid


def _slopes_px(sensor, opd_m: np.ndarray, root_seed: int) -> tuple[np.ndarray, np.ndarray]:
    measurement = sensor.measure(
        opd_m,
        random_streams=NamedRandomStreams(root_seed),
        include_noise=False,
    )
    values = np.asarray(measurement.vector.values, dtype=float).reshape(-1, 2)
    return values, np.asarray(measurement.valid_subapertures, dtype=bool)


def _focus_gradient_px_per_m(slopes_px, centers_m, usable) -> float:
    """Fit ``s_x = t_x + k x`` and ``s_y = t_y + k y`` and return ``k``.

    ``k`` is the slope pattern of a defocus; a loop holds the static focus
    that cancels it.
    """

    x_m = centers_m[usable, 0]
    y_m = centers_m[usable, 1]
    zeros = np.zeros_like(x_m)
    ones = np.ones_like(x_m)
    design = np.vstack(
        (
            np.column_stack((ones, zeros, x_m)),
            np.column_stack((zeros, ones, y_m)),
        )
    )
    target = np.concatenate((slopes_px[usable, 0], slopes_px[usable, 1]))
    coefficients, *_ = np.linalg.lstsq(design, target, rcond=None)
    return float(coefficients[2])


def test_the_analogue_keeps_the_published_sampling(analogue) -> None:
    config, geometry, sensor = analogue
    published = load_system_profile("high_order_10m_hcipy", 3)

    assert config.telescope_diameter_m / config.lenslets_across == pytest.approx(
        published.telescope_diameter_m / published.lenslets_across
    )
    assert geometry.pupil_shape[0] // geometry.n_lenslets_across == (
        published.pupil_pixels // published.lenslets_across
    ) == config.wfs.detector_window_px == 8
    # The defect's lever arm: (N - 1)/n-pixel cells on N/n-pixel blocks.
    cell_px = (ANALOGUE_PUPIL_PIXELS - 1) / ANALOGUE_LENSLETS_ACROSS
    assert cell_px == pytest.approx(7.9)
    sampling = sensor(BLOCK_AXIS).calibration.detector_sampling
    assert sampling.window_shape_px == (8, 8)
    assert sampling.reference_pixel_xy == (3.5, 3.5)
    assert int(np.count_nonzero(_interior(geometry))) >= 12


@pytest.mark.parametrize("lenslet_axis", CONVENTIONS)
def test_flat_reference_centroids_are_independent_of_lenslet_column(
    analogue, lenslet_axis
) -> None:
    """A flat wavefront puts every interior spot at the same window position.

    With the axis drifting by ``0.5 - 0.1 (c + 1/2)`` pixels in column ``c``,
    the published flat references follow the column instead.
    """

    _, geometry, sensor = analogue
    reference_px = np.asarray(
        sensor(lenslet_axis).calibration.reference_centroids_px, dtype=float
    ).reshape(-1, 2)
    indices = _row_column(geometry)
    interior = _interior(geometry)

    for axis, index_column in ((0, 1), (1, 0)):  # x with column, y with row
        values = reference_px[interior, axis]
        assert float(np.ptp(values)) < FLAT_REFERENCE_COLUMN_SPREAD_TOL_PX
        trend = np.polyfit(indices[interior, index_column], values, 1)[0]
        assert abs(float(trend)) < 0.1 * FLAT_REFERENCE_COLUMN_SPREAD_TOL_PX


@pytest.mark.parametrize("lenslet_axis", CONVENTIONS)
def test_even_part_of_a_block_centred_defocus_has_no_interior_focus_gradient(
    analogue, lenslet_axis
) -> None:
    """Deterministic analogue check on interior lenslets.

    The fit leaves out boundary lenslets, whose one-sided neighbour spill is
    shared by both conventions.  The 0.0078 px/m that remains for
    block_center is spill from the lopsided second ring of a 10-lenslet pupil;
    it falls to 0.00024 px/m at the published geometry (see the elt_scale
    checks below).  Random screens are not used here: their interior
    gradients overlap between the two conventions at this size.
    """

    config, geometry, sensor = analogue
    centers_m = np.asarray(geometry.subaperture_centers_m, dtype=float)
    even, usable = _even_part_px(
        sensor(lenslet_axis),
        _block_defocus_opd_m(config, geometry, DEFOCUS_EDGE_OPD_M),
        config.random.root_seed,
    )
    assert bool(np.all(usable))
    gradient = _focus_gradient_px_per_m(even, centers_m, usable & _interior(geometry))
    assert abs(gradient) < ANALOGUE_EVEN_FOCUS_GRADIENT_TOL_PX_PER_M


@pytest.mark.slow
@pytest.mark.elt_scale
@pytest.mark.parametrize("lenslet_axis", CONVENTIONS)
def test_published_geometry_even_part_has_no_interior_focus_gradient(
    published_scale, lenslet_axis
) -> None:
    """The even-part focus check at the published 384-pixel, 48-lenslet scale.

    WFS only: no atmosphere model, DM, interaction matrix or loop.  On a
    4-vCPU Linux VM both conventions together took 18 s with a 707 MiB peak
    RSS, above the desktop-safe default, so the test runs only with
    ``--enable-elt-scale``.  It checks the deterministic block-centred
    defocus and the closed-loop-like tilt-removed residual screens, both on
    interior lenslets.
    """

    config, geometry, sensor = published_scale
    wfs = sensor(lenslet_axis)
    centers_m = np.asarray(geometry.subaperture_centers_m, dtype=float)
    interior = _interior(geometry)
    seed = config.random.root_seed

    even, usable = _even_part_px(
        wfs, _block_defocus_opd_m(config, geometry, DEFOCUS_EDGE_OPD_M), seed
    )
    assert float(np.mean(usable)) > 0.99
    gradient = _focus_gradient_px_per_m(even, centers_m, usable & interior)
    assert abs(gradient) < PUBLISHED_EVEN_FOCUS_GRADIENT_TOL_PX_PER_M

    rng = np.random.default_rng(RESIDUAL_SEED)
    for _ in range(RESIDUAL_SCREENS):
        residual_m = _tilt_removed(_von_karman_opd_m(config, geometry, rng), geometry)
        even, usable = _even_part_px(wfs, residual_m, seed)
        assert float(np.mean(usable)) > 0.9
        gradient = _focus_gradient_px_per_m(even, centers_m, usable & interior)
        assert abs(gradient) < PUBLISHED_RESIDUAL_FOCUS_GRADIENT_TOL_PX_PER_M


def test_the_block_centre_axis_changes_only_the_optics_identity(analogue) -> None:
    """The fix moves lens vertices only: no geometry or published optics hash."""

    config, geometry, sensor = analogue
    f_number = (
        config.wfs.pad_factor
        * float(geometry.x_m[0, 1] - geometry.x_m[0, 0])
        / config.wfs_wavelength_m
    )
    implicit = HcipyShackHartmannOptics(
        geometry, config.wfs_wavelength_m, f_number=f_number
    )
    published = HcipyShackHartmannOptics(
        geometry,
        config.wfs_wavelength_m,
        f_number=f_number,
        lenslet_axis=PUBLISHED_AXIS,
    )
    block = HcipyShackHartmannOptics(
        geometry,
        config.wfs_wavelength_m,
        f_number=f_number,
        lenslet_axis=BLOCK_AXIS,
    )

    assert implicit.lenslet_axis == published.lenslet_axis == PUBLISHED_AXIS
    assert block.lenslet_axis == BLOCK_AXIS
    assert implicit.config_hash == published.config_hash
    assert block.config_hash != published.config_hash
    assert block.geometry_hash == published.geometry_hash == geometry.geometry_hash
    assert block.sampling == published.sampling
    assert (
        sensor(BLOCK_AXIS).calibration.reference_centroids_px.shape
        == sensor(PUBLISHED_AXIS).calibration.reference_centroids_px.shape
    )

    # Every block-centred vertex is the mean of its own block's sample
    # coordinates, inside its geometry cell, within half a pixel of the
    # published vertex.
    dx_m = float(geometry.x_m[0, 1] - geometry.x_m[0, 0])
    window = config.wfs.detector_window_px
    for identifier, cell_center in zip(
        geometry.subaperture_ids, geometry.subaperture_centers_m
    ):
        row, column = lenslet_indices_from_id(identifier)
        vertex = block.lenslet_vertices_xy_m[row * config.lenslets_across + column]
        expected = (
            float(np.mean(geometry.x_m[0, column * window:(column + 1) * window])),
            float(np.mean(geometry.y_m[row * window:(row + 1) * window, 0])),
        )
        np.testing.assert_allclose(vertex, expected, rtol=0.0, atol=1.0e-12)
        assert np.all(np.abs(vertex - cell_center) < 0.5 * dx_m)


def test_unknown_lenslet_axis_conventions_are_refused(analogue) -> None:
    config, geometry, _ = analogue
    with pytest.raises(HcipyShackHartmannError, match="lenslet_axis"):
        HcipyShackHartmannOptics(
            geometry,
            config.wfs_wavelength_m,
            f_number=10.0,
            lenslet_axis="nearest_pixel",
        )
    with pytest.raises((HcipyShackHartmannError, HcipyScaoFactoryError), match="lenslet_axis"):
        scao._factory_for("hcipy").build_wfs(
            model=config.wfs_model,
            geometry=geometry,
            wfs_wavelength_m=config.wfs_wavelength_m,
            pad_factor=config.wfs.pad_factor,
            detector_window_px=config.wfs.detector_window_px,
            detector_config=scao._detector_config(config),
            centroid_config=scao._centroid_config(config),
            validity_config=scao._validity_config(config),
            random_streams=NamedRandomStreams(config.random.root_seed),
            lenslet_axis="nearest_pixel",
        )
