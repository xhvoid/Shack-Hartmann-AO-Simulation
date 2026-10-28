"""Versioned, package-installed SCAO system profiles.

The profile loader is deliberately narrow. It reads reviewed JSON records from
the canonical ``shwfs_ao.resources`` package and converts them to immutable,
SI-valued configuration objects. The deprecated ``ao_simulation_data`` tree is
only a build-generated installed alias.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
import json
import math
from numbers import Integral, Real
import re
from types import MappingProxyType
from typing import Any, Literal, cast

from ..core.hashing import component_config_hash
from ..core.provenance import Provenance
from ..core.random import DERIVATION_SCHEME_ID
from .resources import read_text_resource


PROFILE_SCHEMA_NAME = "shwfs_ao.system_profile"
# Schema v2 makes wfs.photon_allocation an explicit, required field.  The v1
# profiles omitted it and relied on the "throughput_scaled" default on load,
# which left their recorded WFS/system identity implicit; the reviewed v2
# profiles record it explicitly so their identity is unambiguous.  v2 is what
# a *new* record is written under, but v1 records are still read *and written
# back under their own schema*: the record schema version is inside the hashed
# mapping, so re-serializing a v1 profile as a v2 record would change the
# ``config_hash`` of a resource nobody edited and silently relabel every result
# that cites it.  Each config therefore carries the record schema version it
# belongs to (:attr:`SystemConfig.record_schema_version`), and that is the
# version it serializes and hashes under.
# Schema v3 adds wfs.clip_negative_pixels on the same terms.  The canonical
# sensor used to clip negative detector pixels to zero unconditionally, which
# turns zero-mean read noise into a positive pedestal under a center of
# gravity; a v3 record states whether its sensor does.  v1 and v2 records
# predate the field and keep the clipping their profiles were published with.
# Schema v4 adds atmosphere.layers, the per-layer Cn2 fractions and winds of a
# multi-layer atmosphere (atmosphere_model="native_layered", or its HCIPy
# counterpart "hcipy_layered").  A single-layer block states an empty list;
# v1-v3 records predate the field and can only describe single-layer
# atmospheres.
# Schema v5 adds the optional ``scalable`` block (the sparse/compact
# high-order execution path: local linear-spline DM operator, compact lenslet
# geometry, grouped noiseless calibration, and an LSMR Tikhonov solver), the
# ``linear_spline`` DM influence model, and the ``sparse_lsmr_tikhonov``
# reconstructor kind.  All three are expressible only in a v5 record, so no
# v1-v4 record can carry them and no published identity moves.
# Schema v6 adds wfs.lenslet_axis, where the HCIPy microlens vertices sit.
# Every earlier record ran with "geometry_cell_center", whose axes drift
# across their detector windows; "pixel_block_center" centres them
# (docs/refactor/AO_REF_016A_HCIPY_LENSLET_AXIS.md).  v1-v5 records omit the
# field and keep the vertices they were published with.
# Schema v7 adds the optional ``detector_physics`` block, which selects the
# physical camera path (shwfs_ao.detector.physical_camera.v1): a packaged
# camera preset, the detector-pixel layout, the photometric source and sky
# budget, the WFS bandpass, the detector-plane sampling, RTC pixel processing
# and exposure sub-samples (docs/refactor/DETECTOR_LEVEL_DEVELOPMENT_PROMPT.md).
# The existing detector and wfs blocks keep their field lists, so no nested
# hash moves; a v1-v6 record cannot carry the block.  A v7 record also
# requires an exposure no longer than the frame period and a centroid window
# symmetric about the optical-axis pixel.
PROFILE_SCHEMA_VERSION = 7
SUPPORTED_PROFILE_SCHEMA_VERSIONS: tuple[int, ...] = (1, 2, 3, 4, 5, 6, 7)
# The WFS photon allocation the schema-v1 profiles were reviewed and published
# under.  A v1 record omits the field entirely, so this is the only allocation a
# configuration claiming record schema 1 can legitimately hold.  It must stay
# equal to :class:`WfsConfig`'s default, which is what a v1 record's omission
# resolves to on load; ``tests/io/test_configs.py`` holds the two together.
_V1_PHOTON_ALLOCATION = "throughput_scaled"
# The negative-pixel policy every schema-v1 and schema-v2 profile ran with.
# Those records omit wfs.clip_negative_pixels, so this is the only value a
# configuration claiming either schema can hold; like the allocation above it
# must equal :class:`WfsConfig`'s default.
_PRE_V3_CLIP_NEGATIVE_PIXELS = True
# The lens-vertex convention every schema-v1 to v5 profile ran with, on the same
# terms: those records omit wfs.lenslet_axis, so this is the only value a
# configuration claiming any of those schemas can hold.
_PRE_V6_LENSLET_AXIS = "geometry_cell_center"
_PROFILE_NAME = re.compile(r"^[a-z][a-z0-9_]*$")
_PROFILE_RESOURCES: dict[tuple[str, int], str] = {
    ("fast_2m_detector", 1): "synthetic_presets/fast_2m_detector.v1.json",
    ("fast_2m_detector", 2): "synthetic_presets/fast_2m_detector.v2.json",
    ("fast_2m_detector", 3): "synthetic_presets/fast_2m_detector.v3.json",
    ("fast_2m_detector", 4): "synthetic_presets/fast_2m_detector.v4.json",
    ("portfolio_2m_detector", 1): "synthetic_presets/portfolio_2m_detector.v1.json",
    ("portfolio_2m_detector", 2): "synthetic_presets/portfolio_2m_detector.v2.json",
    ("portfolio_2m_detector", 3): "synthetic_presets/portfolio_2m_detector.v3.json",
    ("portfolio_2m_detector", 4): "synthetic_presets/portfolio_2m_detector.v4.json",
    ("research_2m_detector", 1): "synthetic_presets/research_2m_detector.v1.json",
    ("research_2m_detector", 2): "synthetic_presets/research_2m_detector.v2.json",
    ("research_2m_detector", 3): "synthetic_presets/research_2m_detector.v3.json",
    ("high_order_10m_geometric", 1): "synthetic_presets/high_order_10m_geometric.v1.json",
    ("high_order_10m_geometric", 2): "synthetic_presets/high_order_10m_geometric.v2.json",
    ("high_order_10m_geometric", 3): "synthetic_presets/high_order_10m_geometric.v3.json",
    ("high_order_10m_hcipy", 1): "synthetic_presets/high_order_10m_hcipy.v1.json",
    ("high_order_10m_hcipy", 2): "synthetic_presets/high_order_10m_hcipy.v2.json",
    ("high_order_10m_hcipy", 3): "synthetic_presets/high_order_10m_hcipy.v3.json",
    ("eso_turbulence_2m_detector", 1): "synthetic_presets/eso_turbulence_2m_detector.v1.json",
    # ESO-derived SCAO benchmark tiers (docs/eso_scao_benchmark.md).  The smoke
    # tier is a software check, the medium tiers a distinct lower-order
    # experiment, and eso_drm_42m_scao_derived the full nominal spatial scale.
    ("eso_scao_smoke_5m_software", 1): "synthetic_presets/eso_scao_smoke_5m_software.v1.json",
    ("eso_scao_medium_12m_derived", 1): "synthetic_presets/eso_scao_medium_12m_derived.v1.json",
    ("eso_scao_medium_12m_weak_gate", 1): "synthetic_presets/eso_scao_medium_12m_weak_gate.v1.json",
    ("eso_drm_42m_scao_derived", 1): "synthetic_presets/eso_drm_42m_scao_derived.v1.json",
    # Version 2 of each tier: a detector window symmetric about the optical
    # axis (23 instead of 24 pixels) removes a centre-of-gravity bias that left
    # a static tilt in version 1's corrected wavefront.
    ("eso_scao_smoke_5m_software", 2): "synthetic_presets/eso_scao_smoke_5m_software.v2.json",
    ("eso_scao_medium_12m_derived", 2): "synthetic_presets/eso_scao_medium_12m_derived.v2.json",
    ("eso_scao_medium_12m_weak_gate", 2): "synthetic_presets/eso_scao_medium_12m_weak_gate.v2.json",
    ("eso_drm_42m_scao_derived", 2): "synthetic_presets/eso_drm_42m_scao_derived.v2.json",
    # Schema-v7 detector-level noise-on families (physical camera path;
    # docs/detector_model.md, scripts/generate_detector_level_profiles.py).
    ("det_ccd_2m_synthetic", 1): "synthetic_presets/det_ccd_2m_synthetic.v1.json",
    ("det_emccd_2m_synthetic", 1): "synthetic_presets/det_emccd_2m_synthetic.v1.json",
    ("det_cmos_2m_synthetic", 1): "synthetic_presets/det_cmos_2m_synthetic.v1.json",
    ("det_emccd_2m_plane_synthetic", 1): "synthetic_presets/det_emccd_2m_plane_synthetic.v1.json",
    ("det_emccd_12m_medium_derived", 1): "synthetic_presets/det_emccd_12m_medium_derived.v1.json",
    ("det_ccd_42m_r3band_derived", 1): "synthetic_presets/det_ccd_42m_r3band_derived.v1.json",
    # Version 2 after its E3 magnitude scan: bright internal calibration source
    # and validity gating on the detector_covariance_v1 domain.
    ("det_emccd_12m_medium_derived", 2): "synthetic_presets/det_emccd_12m_medium_derived.v2.json",
}

BackendName = Literal["native", "hcipy"]
WfsModel = Literal["geometric", "detector_level"]
AtmosphereModelName = Literal[
    "static",
    "native_frozen_flow",
    "native_frozen_flow_v2",
    "native_layered",
    "hcipy",
    "hcipy_layered",
]
# The models that take atmosphere.layers, one per backend; no other accepts them.
_LAYERED_ATMOSPHERE_MODELS = frozenset({"native_layered", "hcipy_layered"})
# Same tolerance the public-data loader applies to normalized Cn2 weights.
_LAYER_FRACTION_ABS_TOL = 1.0e-9


class SystemConfigError(ValueError):
    """Raised when a serialized SCAO profile is malformed or unsupported."""


@dataclass(frozen=True, slots=True)
class ProfileProvenance:
    profile_name: str
    profile_version: int
    baseline_rationale: str
    provenance: Provenance

    def __post_init__(self) -> None:
        name = _profile_name(self.profile_name)
        version = _integer(self.profile_version, "profile_version", minimum=1)
        rationale = _text(self.baseline_rationale, "baseline_rationale")
        if not isinstance(self.provenance, Provenance):
            raise SystemConfigError("provenance must be a Provenance record.")
        expected_source_id = f"shwfs_ao.system_profile.{name}.v{version}"
        if self.provenance.source_id != expected_source_id:
            raise SystemConfigError(
                "profile provenance source_id must be " f"{expected_source_id!r}."
            )
        object.__setattr__(self, "profile_name", name)
        object.__setattr__(self, "profile_version", version)
        object.__setattr__(self, "baseline_rationale", rationale)

    @property
    def profile_id(self) -> str:
        return f"{self.profile_name}@{self.profile_version}"

    @property
    def config_hash(self) -> str:
        return component_config_hash("scao.profile_provenance", self)


@dataclass(frozen=True, slots=True)
class AtmosphereLayerConfig:
    """One frozen-flow layer of a multi-layer atmosphere.

    Layers are taken by ``native_layered`` and ``hcipy_layered``, which split
    the turbulence identically and differ only in the screen generator.

    ``cn2_fraction`` is this layer's share of the integrated turbulence
    strength, so the layer's own Fried parameter is
    ``r0_m * cn2_fraction**(-3/5)``.  ``wind_m_per_s`` is the layer's
    translation velocity on the pupil grid.  ``altitude_m`` is the height above
    the telescope; it is recorded for provenance and has no effect on an
    on-axis, geometric-optics propagation.
    """

    altitude_m: float
    cn2_fraction: float
    wind_m_per_s: tuple[float, float]

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "altitude_m", _nonnegative(self.altitude_m, "altitude_m")
        )
        object.__setattr__(
            self, "cn2_fraction", _positive(self.cn2_fraction, "cn2_fraction")
        )
        object.__setattr__(
            self, "wind_m_per_s", _pair(self.wind_m_per_s, "wind_m_per_s")
        )


@dataclass(frozen=True, slots=True)
class _AtmosphereConfigSchemaV3:
    """The exact :class:`AtmosphereConfig` shape single-layer blocks hash as.

    Schema v4 added ``layers``, which moves the declared field list the nested
    atmosphere hash walks (see :class:`_WfsConfigSchemaV1` for the mechanism).
    A single-layer block states ``layers=()`` and describes exactly what it
    described before the field existed, so it keeps hashing as these six
    fields under the published schema id, whichever record schema it belongs
    to.  That keeps ``component_config_hashes["atmosphere"]`` and
    :attr:`SystemConfig.observing_conditions_hash` of every published profile
    at their published values, and lets a v4 single-layer profile share
    observing conditions with the v1-v3 profiles it matches.
    """

    __hash_schema_id__ = "shwfs_ao.io.configs.AtmosphereConfig"

    r0_m: float
    r0_reference_wavelength_m: float
    outer_scale_m: float | None
    wind_m_per_s: tuple[float, float]
    target_rms_opd_m: float | None
    normalize_rms: bool


@dataclass(frozen=True, slots=True)
class AtmosphereConfig:
    """Serialized atmosphere block of a SCAO profile.

    ``r0_m`` is the integrated Fried parameter at
    ``r0_reference_wavelength_m``.  A non-empty ``layers`` tuple describes a
    multi-layer atmosphere: the layers split that integrated strength by their
    normalized ``cn2_fraction`` and carry their own winds, so the block-level
    ``wind_m_per_s`` must then be zero.  A layered atmosphere is absolutely
    normalized by r0 and the outer scale; it has no RMS rescaling.
    """

    r0_m: float
    r0_reference_wavelength_m: float
    outer_scale_m: float | None
    wind_m_per_s: tuple[float, float]
    target_rms_opd_m: float | None
    normalize_rms: bool
    layers: tuple[AtmosphereLayerConfig, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "r0_m", _positive(self.r0_m, "r0_m"))
        object.__setattr__(
            self,
            "r0_reference_wavelength_m",
            _positive(
                self.r0_reference_wavelength_m,
                "r0_reference_wavelength_m",
            ),
        )
        object.__setattr__(
            self,
            "outer_scale_m",
            _optional_positive(self.outer_scale_m, "outer_scale_m"),
        )
        object.__setattr__(
            self,
            "wind_m_per_s",
            _pair(self.wind_m_per_s, "wind_m_per_s"),
        )
        object.__setattr__(
            self,
            "target_rms_opd_m",
            _optional_positive(self.target_rms_opd_m, "target_rms_opd_m"),
        )
        object.__setattr__(self, "normalize_rms", _boolean(self.normalize_rms, "normalize_rms"))
        layers = _tuple_value(self.layers, "layers")
        for index, layer in enumerate(layers):
            if not isinstance(layer, AtmosphereLayerConfig):
                raise SystemConfigError(
                    f"layers[{index}] must be an AtmosphereLayerConfig."
                )
        if layers:
            total = math.fsum(layer.cn2_fraction for layer in layers)
            if not math.isclose(
                total, 1.0, rel_tol=0.0, abs_tol=_LAYER_FRACTION_ABS_TOL
            ):
                raise SystemConfigError(
                    f"layers cn2_fraction values must sum to 1; got {total!r}."
                )
            if self.wind_m_per_s != (0.0, 0.0):
                raise SystemConfigError(
                    "a layered atmosphere carries its winds per layer; "
                    "wind_m_per_s must be [0, 0]."
                )
            if self.normalize_rms or self.target_rms_opd_m is not None:
                raise SystemConfigError(
                    "a layered atmosphere is absolutely normalized by r0 and "
                    "the outer scale; normalize_rms must be false and "
                    "target_rms_opd_m null."
                )
        object.__setattr__(self, "layers", layers)

    @property
    def config_hash(self) -> str:
        return component_config_hash("scao.atmosphere_config", self._hash_view())

    def _hash_view(self) -> object:
        """Return the value this block is hashed as (see the v3 stand-in)."""

        if self.layers:
            return self
        return _AtmosphereConfigSchemaV3(
            r0_m=self.r0_m,
            r0_reference_wavelength_m=self.r0_reference_wavelength_m,
            outer_scale_m=self.outer_scale_m,
            wind_m_per_s=self.wind_m_per_s,
            target_rms_opd_m=self.target_rms_opd_m,
            normalize_rms=self.normalize_rms,
        )


@dataclass(frozen=True, slots=True)
class DetectorSystemConfig:
    enabled: bool
    photons_per_subap_frame: float | None
    read_noise_e: float
    dark_e_per_s: float
    background_e_per_pixel_frame: float
    full_well_e: float | None
    qe: float
    prnu_rms: float
    exposure_s: float
    prnu_mode: Literal["per_frame_legacy", "persistent"]
    bad_pixel_fraction: float

    def __post_init__(self) -> None:
        enabled = _boolean(self.enabled, "enabled")
        photons = _optional_nonnegative(
            self.photons_per_subap_frame, "photons_per_subap_frame"
        )
        # Whether an enabled detector needs this photon budget depends on the
        # schema-v7 detector_physics block, so SystemConfig checks it.
        object.__setattr__(self, "enabled", enabled)
        object.__setattr__(self, "photons_per_subap_frame", photons)
        for name in (
            "read_noise_e",
            "dark_e_per_s",
            "background_e_per_pixel_frame",
            "prnu_rms",
            "bad_pixel_fraction",
        ):
            object.__setattr__(self, name, _nonnegative(getattr(self, name), name))
        object.__setattr__(self, "full_well_e", _optional_positive(self.full_well_e, "full_well_e"))
        object.__setattr__(self, "qe", _positive(self.qe, "qe"))
        object.__setattr__(self, "exposure_s", _positive(self.exposure_s, "exposure_s"))
        if self.prnu_mode not in {"per_frame_legacy", "persistent"}:
            raise SystemConfigError(
                "prnu_mode must be 'per_frame_legacy' or 'persistent'."
            )
        if self.bad_pixel_fraction > 1.0:
            raise SystemConfigError("bad_pixel_fraction must be at most 1.")

    @property
    def config_hash(self) -> str:
        return component_config_hash("scao.detector_config", self)


@dataclass(frozen=True, slots=True)
class _WfsConfigSchemaV1:
    """The exact :class:`WfsConfig` shape the schema-v1 records published under.

    :func:`~shwfs_ao.core.hashing.canonicalize_for_hash` walks a dataclass
    through its *declared* fields and stamps the payload with a schema id taken
    from the type, so a nested component hash is a function of the field list
    and of the class name as much as of the values.  Adding
    ``photon_allocation`` to :class:`WfsConfig` therefore moved the published
    ``component_config_hashes["wfs"]`` of every v1 profile, although those
    records were never edited and the field only restates the allocation they
    already ran with.  ``SystemConfig.config_hash`` survived that because it
    hashes :func:`system_config_to_mapping`, which drops the field for a v1
    record; the nested hash had no such basis and moved.

    This stand-in restores it: the twelve v1 fields in their published order,
    and ``__hash_schema_id__`` pinned to the name :class:`WfsConfig` carried
    when those digests were published, so the canonical bytes are the historical
    ones rather than a re-derivation that merely resembles them.  It is a
    separate frozen declaration on purpose.  A filtered view of the live class
    would track every later edit to it, which is exactly the coupling that moved
    these hashes once already; a schema v3 that adds a WFS field must leave this
    declaration untouched and add its own.  No validation is repeated here
    because nothing constructs it from untrusted input: the only caller is
    :meth:`WfsConfig.config_hash_for_record_schema`, which copies fields off an
    already-validated block.
    """

    __hash_schema_id__ = "shwfs_ao.io.configs.WfsConfig"

    min_fill_fraction: float
    pad_factor: int | None
    detector_window_px: int | None
    centroid_estimator: Literal[
        "center_of_gravity", "thresholded_center_of_gravity"
    ]
    threshold_fraction: float
    subtract_minimum: bool
    min_flux_e: float
    min_peak_snr: float
    max_centroid_sigma_px: float
    max_window_clipping_fraction: float
    central_obstruction_ratio: float
    spider_width_m: float


@dataclass(frozen=True, slots=True)
class _WfsConfigSchemaV2:
    """The exact :class:`WfsConfig` shape the schema-v2 records published under.

    Schema v3 added ``clip_negative_pixels``, which moves the declared field
    list the nested WFS hash walks, exactly as ``photon_allocation`` once did
    for the v1 records (see :class:`_WfsConfigSchemaV1`).  These thirteen
    fields, in their published order and under the schema id those digests
    were published with, keep every v2 record's
    ``component_config_hashes["wfs"]`` at its published value.  It is a frozen
    declaration of its own for the same reason as its v1 sibling.
    """

    __hash_schema_id__ = "shwfs_ao.io.configs.WfsConfig"

    min_fill_fraction: float
    pad_factor: int | None
    detector_window_px: int | None
    centroid_estimator: Literal[
        "center_of_gravity", "thresholded_center_of_gravity"
    ]
    threshold_fraction: float
    subtract_minimum: bool
    min_flux_e: float
    min_peak_snr: float
    max_centroid_sigma_px: float
    max_window_clipping_fraction: float
    central_obstruction_ratio: float
    spider_width_m: float
    photon_allocation: Literal["throughput_scaled", "unit_sum"]


@dataclass(frozen=True, slots=True)
class _WfsConfigSchemaV3:
    """The exact :class:`WfsConfig` shape the schema-v3 to v5 records published under.

    Schema v6 added ``lenslet_axis``, which moves the declared field list
    the nested WFS hash walks (see :class:`_WfsConfigSchemaV1`).  These
    fourteen fields, in their published order and under the schema id those
    digests were published with, keep every v3, v4 and v5 record's
    ``component_config_hashes["wfs"]`` at its published value.
    """

    __hash_schema_id__ = "shwfs_ao.io.configs.WfsConfig"

    min_fill_fraction: float
    pad_factor: int | None
    detector_window_px: int | None
    centroid_estimator: Literal[
        "center_of_gravity", "thresholded_center_of_gravity"
    ]
    threshold_fraction: float
    subtract_minimum: bool
    min_flux_e: float
    min_peak_snr: float
    max_centroid_sigma_px: float
    max_window_clipping_fraction: float
    central_obstruction_ratio: float
    spider_width_m: float
    photon_allocation: Literal["throughput_scaled", "unit_sum"]
    clip_negative_pixels: bool


@dataclass(frozen=True, slots=True)
class WfsConfig:
    min_fill_fraction: float
    pad_factor: int | None
    detector_window_px: int | None
    centroid_estimator: Literal[
        "center_of_gravity", "thresholded_center_of_gravity"
    ]
    threshold_fraction: float
    subtract_minimum: bool
    min_flux_e: float
    min_peak_snr: float
    max_centroid_sigma_px: float
    max_window_clipping_fraction: float
    central_obstruction_ratio: float
    spider_width_m: float
    photon_allocation: Literal["throughput_scaled", "unit_sum"] = (
        "throughput_scaled"
    )
    # Whether the detector-level sensor clips negative pixels to zero before
    # centroiding.  Clipping turns zero-mean read noise into a positive
    # pedestal that pulls a center of gravity toward the window centre and
    # lowers its response to spot motion; keeping negative pixels removes that
    # bias and leaves it approximately unbiased.  True is the behaviour every
    # published profile ran with.
    clip_negative_pixels: bool = True
    # Where the HCIPy backend puts each microlens vertex, and so each spot
    # axis.  "geometry_cell_center" uses the geometry's continuous cell
    # centres, which drift across the 8-pixel block windows by up to half a
    # pixel and leave a static focus in closed loop.  "pixel_block_center"
    # centres each axis in its window.  Only the HCIPy detector-level sensor
    # places lens vertices; every other sensor must keep the default, which it
    # never consults.  The default is the behaviour every published profile
    # ran with.
    lenslet_axis: Literal["geometry_cell_center", "pixel_block_center"] = (
        "geometry_cell_center"
    )

    def __post_init__(self) -> None:
        fill = _fraction(self.min_fill_fraction, "min_fill_fraction")
        pad = _optional_integer(self.pad_factor, "pad_factor", minimum=1)
        window = _optional_integer(
            self.detector_window_px, "detector_window_px", minimum=1
        )
        if self.centroid_estimator not in {
            "center_of_gravity",
            "thresholded_center_of_gravity",
        }:
            raise SystemConfigError("unsupported centroid_estimator.")
        threshold = _nonnegative(self.threshold_fraction, "threshold_fraction")
        if self.centroid_estimator == "center_of_gravity" and threshold != 0.0:
            raise SystemConfigError(
                "center_of_gravity requires threshold_fraction=0."
            )
        clipping = _fraction(
            self.max_window_clipping_fraction,
            "max_window_clipping_fraction",
        )
        obstruction = _fraction(
            self.central_obstruction_ratio, "central_obstruction_ratio"
        )
        if obstruction >= 1.0:
            raise SystemConfigError("central_obstruction_ratio must be less than 1.")
        object.__setattr__(self, "min_fill_fraction", fill)
        object.__setattr__(self, "pad_factor", pad)
        object.__setattr__(self, "detector_window_px", window)
        object.__setattr__(self, "threshold_fraction", threshold)
        object.__setattr__(self, "subtract_minimum", _boolean(self.subtract_minimum, "subtract_minimum"))
        for name in ("min_flux_e", "min_peak_snr", "max_centroid_sigma_px"):
            object.__setattr__(self, name, _nonnegative(getattr(self, name), name))
        object.__setattr__(self, "max_window_clipping_fraction", clipping)
        object.__setattr__(self, "central_obstruction_ratio", obstruction)
        object.__setattr__(self, "spider_width_m", _nonnegative(self.spider_width_m, "spider_width_m"))
        if self.photon_allocation not in {"throughput_scaled", "unit_sum"}:
            raise SystemConfigError(
                "photon_allocation must be 'throughput_scaled' or 'unit_sum'."
            )
        object.__setattr__(
            self,
            "clip_negative_pixels",
            _boolean(self.clip_negative_pixels, "clip_negative_pixels"),
        )
        if self.lenslet_axis not in {"geometry_cell_center", "pixel_block_center"}:
            raise SystemConfigError(
                "lenslet_axis must be 'geometry_cell_center' or "
                "'pixel_block_center'."
            )

    @property
    def config_hash(self) -> str:
        """This block's identity under the current profile record schema.

        A :class:`WfsConfig` on its own belongs to no record, so it answers for
        the shape the class actually has — the same convention as
        :attr:`SystemConfig.record_schema_version`'s default.  That keeps this
        property meaningful as a public identity: two blocks that differ only in
        ``photon_allocation`` still hash differently, which is what callers
        keying caches or result labels off it rely on.  A block that came from a
        record published under an older schema must be hashed through
        :meth:`config_hash_for_record_schema` instead, which is what
        :attr:`SystemConfig.component_config_hashes` does.
        """

        return self.config_hash_for_record_schema(PROFILE_SCHEMA_VERSION)

    def config_hash_for_record_schema(self, record_schema_version: int) -> str:
        """Return this block's identity as the given record schema publishes it.

        The schema version lives on :class:`SystemConfig`, not here, so the
        caller must state it; a :class:`WfsConfig` cannot infer which record it
        was parsed out of.  Schemas v1, v2 and v3-v5 need payloads of their
        own, because they predate ``photon_allocation``,
        ``clip_negative_pixels`` and ``lenslet_axis`` respectively — see
        :class:`_WfsConfigSchemaV1` for why the historical bytes have to be
        reproduced rather than recomputed.

        Refusing an unknown version matters as much as reproducing the known
        ones: treating an unrecognized schema as "probably the newest" would
        publish a digest under a schema whose field set nobody has checked, and
        the mistake would only surface as results that no longer reproduce their
        own identity.
        """

        version = _integer(
            record_schema_version, "record_schema_version", minimum=1
        )
        if version not in SUPPORTED_PROFILE_SCHEMA_VERSIONS:
            raise SystemConfigError(
                f"unsupported profile schema_version={record_schema_version!r}; "
                f"supported={list(SUPPORTED_PROFILE_SCHEMA_VERSIONS)}."
            )
        if version >= 6:
            return component_config_hash("scao.wfs_config", self)
        # No earlier schema has a field for the lens-vertex convention, so a
        # block-centred sensor hashed under one would lose that change.
        if self.lenslet_axis != _PRE_V6_LENSLET_AXIS:
            raise SystemConfigError(
                f"record_schema_version={version} cannot express "
                f"wfs.lenslet_axis={self.lenslet_axis!r}: that schema has no "
                "such field, so the value would be missing from the hash "
                f"rather than recorded in it. Hash this block under schema "
                f"{PROFILE_SCHEMA_VERSION} instead."
            )
        if version >= 3:
            historical_v3 = tuple(_WfsConfigSchemaV3.__dataclass_fields__)
            declared_v3 = tuple(
                name for name in self.__dataclass_fields__ if name != "lenslet_axis"
            )
            if declared_v3 != historical_v3:
                raise SystemConfigError(
                    f"WfsConfig declares {list(declared_v3)} beside "
                    "lenslet_axis, but the frozen schema-3 hash payload "
                    f"declares {list(historical_v3)}; a schema that changes the "
                    "WFS field set needs its own payload, because editing the "
                    "schema-3 one moves every published v3-v5 nested WFS hash."
                )
            return component_config_hash(
                "scao.wfs_config",
                _WfsConfigSchemaV3(
                    min_fill_fraction=self.min_fill_fraction,
                    pad_factor=self.pad_factor,
                    detector_window_px=self.detector_window_px,
                    centroid_estimator=self.centroid_estimator,
                    threshold_fraction=self.threshold_fraction,
                    subtract_minimum=self.subtract_minimum,
                    min_flux_e=self.min_flux_e,
                    min_peak_snr=self.min_peak_snr,
                    max_centroid_sigma_px=self.max_centroid_sigma_px,
                    max_window_clipping_fraction=self.max_window_clipping_fraction,
                    central_obstruction_ratio=self.central_obstruction_ratio,
                    spider_width_m=self.spider_width_m,
                    photon_allocation=self.photon_allocation,
                    clip_negative_pixels=self.clip_negative_pixels,
                ),
            )
        # Neither earlier schema has a field to keep negative pixels, so such a
        # block would hash as a clipping sensor; refuse it, as for the
        # allocation below.
        if self.clip_negative_pixels != _PRE_V3_CLIP_NEGATIVE_PIXELS:
            raise SystemConfigError(
                f"record_schema_version={version} cannot express "
                f"wfs.clip_negative_pixels={self.clip_negative_pixels!r}: that "
                "schema has no such field, so the value would be missing from "
                "the hash rather than recorded in it. Hash this block under "
                f"schema {PROFILE_SCHEMA_VERSION} instead."
            )
        if version == 2:
            historical_v2 = tuple(_WfsConfigSchemaV2.__dataclass_fields__)
            declared_v2 = tuple(
                name
                for name in self.__dataclass_fields__
                if name not in {"clip_negative_pixels", "lenslet_axis"}
            )
            if declared_v2 != historical_v2:
                raise SystemConfigError(
                    f"WfsConfig declares {list(declared_v2)} beside "
                    "clip_negative_pixels, but the frozen schema-2 hash payload "
                    f"declares {list(historical_v2)}; a schema that changes the "
                    "WFS field set needs its own payload, because editing the "
                    "schema-2 one moves every published v2 nested WFS hash."
                )
            return component_config_hash(
                "scao.wfs_config",
                _WfsConfigSchemaV2(
                    min_fill_fraction=self.min_fill_fraction,
                    pad_factor=self.pad_factor,
                    detector_window_px=self.detector_window_px,
                    centroid_estimator=self.centroid_estimator,
                    threshold_fraction=self.threshold_fraction,
                    subtract_minimum=self.subtract_minimum,
                    min_flux_e=self.min_flux_e,
                    min_peak_snr=self.min_peak_snr,
                    max_centroid_sigma_px=self.max_centroid_sigma_px,
                    max_window_clipping_fraction=self.max_window_clipping_fraction,
                    central_obstruction_ratio=self.central_obstruction_ratio,
                    spider_width_m=self.spider_width_m,
                    photon_allocation=self.photon_allocation,
                ),
            )
        # Schema v1 has no field to carry a non-default allocation, so hashing
        # such a block under it would publish an identity that silently omits a
        # real change to the WFS photon budget: two physically different sensors
        # would share one digest.  :meth:`SystemConfig.__post_init__` already
        # refuses that pairing for a whole configuration; this is the same rule
        # at the one other door into the v1 payload.
        if self.photon_allocation != _V1_PHOTON_ALLOCATION:
            raise SystemConfigError(
                "record_schema_version=1 cannot express "
                f"wfs.photon_allocation={self.photon_allocation!r}: that schema "
                "has no such field, so the value would be missing from the hash "
                "rather than recorded in it. Hash this block under schema "
                f"{PROFILE_SCHEMA_VERSION} instead."
            )
        # The v1 payload is frozen, so it must not quietly absorb a field this
        # class gains later: a schema v3 addition has to decide for itself what
        # a v1 record's WFS block looks like.  Comparing the declared names in
        # order — the canonical payload is an ordered field list, so a reordering
        # moves the digest just as an addition does — turns that decision into a
        # failure here instead of ten silently relabelled published records.
        historical = tuple(_WfsConfigSchemaV1.__dataclass_fields__)
        declared = tuple(
            name
            for name in self.__dataclass_fields__
            if name not in {"photon_allocation", "clip_negative_pixels", "lenslet_axis"}
        )
        if declared != historical:
            raise SystemConfigError(
                f"WfsConfig declares {list(declared)} beside photon_allocation, "
                f"but the frozen schema-1 hash payload declares {list(historical)}; "
                "a schema that changes the WFS field set needs its own payload, "
                "because editing the schema-1 one moves every published v1 "
                "nested WFS hash."
            )
        return component_config_hash(
            "scao.wfs_config",
            _WfsConfigSchemaV1(
                min_fill_fraction=self.min_fill_fraction,
                pad_factor=self.pad_factor,
                detector_window_px=self.detector_window_px,
                centroid_estimator=self.centroid_estimator,
                threshold_fraction=self.threshold_fraction,
                subtract_minimum=self.subtract_minimum,
                min_flux_e=self.min_flux_e,
                min_peak_snr=self.min_peak_snr,
                max_centroid_sigma_px=self.max_centroid_sigma_px,
                max_window_clipping_fraction=self.max_window_clipping_fraction,
                central_obstruction_ratio=self.central_obstruction_ratio,
                spider_width_m=self.spider_width_m,
            ),
        )


@dataclass(frozen=True, slots=True)
class DmSystemConfig:
    influence_model: Literal[
        "gaussian", "compact_gaussian", "pyramid_like", "linear_spline"
    ]
    coupling_width_pitch: float
    stroke_limit_opd_m: float
    include_edge_actuators: bool
    actuator_margin_fraction: float
    dead_actuator_indices: tuple[int, ...]
    stuck_actuator_indices: tuple[int, ...]
    stuck_command_opd_m: float

    def __post_init__(self) -> None:
        if self.influence_model not in {
            "gaussian",
            "compact_gaussian",
            "pyramid_like",
            "linear_spline",
        }:
            raise SystemConfigError("unsupported influence_model.")
        if self.influence_model == "linear_spline" and self.coupling_width_pitch != 1.0:
            raise SystemConfigError(
                "linear_spline influences have a one-pitch support; "
                "coupling_width_pitch must be 1.0."
            )
        object.__setattr__(self, "coupling_width_pitch", _positive(self.coupling_width_pitch, "coupling_width_pitch"))
        stroke = _positive(self.stroke_limit_opd_m, "stroke_limit_opd_m")
        object.__setattr__(self, "stroke_limit_opd_m", stroke)
        object.__setattr__(self, "include_edge_actuators", _boolean(self.include_edge_actuators, "include_edge_actuators"))
        object.__setattr__(self, "actuator_margin_fraction", _nonnegative(self.actuator_margin_fraction, "actuator_margin_fraction"))
        dead = _indices(self.dead_actuator_indices, "dead_actuator_indices")
        stuck = _indices(self.stuck_actuator_indices, "stuck_actuator_indices")
        if set(dead) & set(stuck):
            raise SystemConfigError("dead and stuck actuator indices must be disjoint.")
        stuck_value = _finite(self.stuck_command_opd_m, "stuck_command_opd_m")
        if abs(stuck_value) > stroke:
            raise SystemConfigError("stuck_command_opd_m must be within the stroke limit.")
        object.__setattr__(self, "dead_actuator_indices", dead)
        object.__setattr__(self, "stuck_actuator_indices", stuck)
        object.__setattr__(self, "stuck_command_opd_m", stuck_value)

    @property
    def config_hash(self) -> str:
        return component_config_hash("scao.dm_config", self)


@dataclass(frozen=True, slots=True)
class CalibrationConfig:
    source: Literal["build", "resource", "supplied"]
    method: Literal["central", "forward"]
    probe_kind: Literal["dm_actuator", "modal"]
    amplitude_m: float
    include_noise: bool
    repeats: int
    resource_name: str | None

    def __post_init__(self) -> None:
        if self.source not in {"build", "resource", "supplied"}:
            raise SystemConfigError("calibration source must be build/resource/supplied.")
        if self.method not in {"central", "forward"}:
            raise SystemConfigError("calibration method must be central or forward.")
        if self.probe_kind not in {"dm_actuator", "modal"}:
            raise SystemConfigError("probe_kind must be dm_actuator or modal.")
        object.__setattr__(self, "amplitude_m", _positive(self.amplitude_m, "amplitude_m"))
        noisy = _boolean(self.include_noise, "include_noise")
        repeats = _integer(self.repeats, "repeats", minimum=1)
        if noisy and repeats < 2:
            raise SystemConfigError("noisy calibration requires repeats >= 2.")
        if not noisy and repeats != 1:
            raise SystemConfigError("noise-free calibration requires repeats=1.")
        resource_name = _optional_text(self.resource_name, "resource_name")
        if self.source == "resource" and resource_name is None:
            raise SystemConfigError("resource calibration requires resource_name.")
        if self.source != "resource" and resource_name is not None:
            raise SystemConfigError("resource_name is valid only for source='resource'.")
        object.__setattr__(self, "include_noise", noisy)
        object.__setattr__(self, "repeats", repeats)
        object.__setattr__(self, "resource_name", resource_name)

    @property
    def config_hash(self) -> str:
        return component_config_hash("scao.calibration_config", self)


@dataclass(frozen=True, slots=True)
class ReconstructorConfig:
    """Reconstruction objective.

    ``alpha`` is the absolute Tikhonov parameter (matrix units) for
    ``tikhonov``.  For ``sparse_lsmr_tikhonov`` it is *dimensionless*: the
    damping relative to the RMS column norm of the calibration-valid response,
    solved by LSMR with the tolerances of the profile's ``scalable`` block.
    """

    kind: Literal["least_squares", "tsvd", "tikhonov", "sparse_lsmr_tikhonov"]
    rcond: float | None
    alpha: float | None
    min_valid_fraction: float
    min_rank: int
    max_cached_masks: int

    def __post_init__(self) -> None:
        if self.kind not in {"least_squares", "tsvd", "tikhonov", "sparse_lsmr_tikhonov"}:
            raise SystemConfigError("unsupported reconstructor kind.")
        rcond = _optional_positive(self.rcond, "rcond")
        alpha = _optional_nonnegative(self.alpha, "alpha")
        if self.kind == "tsvd" and rcond is None:
            raise SystemConfigError("tsvd requires rcond.")
        if self.kind != "tsvd" and rcond is not None:
            raise SystemConfigError("rcond is valid only for tsvd.")
        uses_alpha = self.kind in {"tikhonov", "sparse_lsmr_tikhonov"}
        if uses_alpha and alpha is None:
            raise SystemConfigError(f"{self.kind} requires alpha.")
        if not uses_alpha and alpha is not None:
            raise SystemConfigError("alpha is valid only for Tikhonov reconstructors.")
        object.__setattr__(self, "rcond", rcond)
        object.__setattr__(self, "alpha", alpha)
        object.__setattr__(self, "min_valid_fraction", _fraction(self.min_valid_fraction, "min_valid_fraction"))
        object.__setattr__(self, "min_rank", _integer(self.min_rank, "min_rank", minimum=1))
        object.__setattr__(self, "max_cached_masks", _integer(self.max_cached_masks, "max_cached_masks", minimum=0))

    @property
    def config_hash(self) -> str:
        return component_config_hash("scao.reconstructor_config", self)


@dataclass(frozen=True, slots=True)
class ScalablePathConfig:
    """Opt-in high-order execution path (schema v5).

    Every field changes what a run computes and is part of the configuration
    identity.  Pure execution settings -- lenslet batch size, probe chunking,
    thread counts -- are runtime arguments and deliberately absent.

    ``dm_operator``
        ``linear_spline_local_sparse``: the sparse bilinear-tent operator of
        ``shwfs_ao.backends.native.dm_operator``; no influence cube.
    ``wfs_geometry``
        ``compact_cells``: per-lenslet cell bounds and local masks with
        batched native lenslet FFTs; no full-pupil mask per lenslet.
    ``calibration_strategy``
        ``grouped_local_noiseless``: disjoint-lenslet probe groups with one
        zero reference, equal to per-actuator central differences; noiseless
        only.
    ``solver``
        ``lsmr`` on the usable rows with ``solver_atol``/``solver_btol``,
        at most ``solver_max_iterations``, from ``x0 = 0``; a solve that does
        not converge is rejected (``nonconverged_policy="reject"``) or used.
    """

    dm_operator: Literal["linear_spline_local_sparse"]
    wfs_geometry: Literal["compact_cells"]
    calibration_strategy: Literal["grouped_local_noiseless"]
    solver: Literal["lsmr"]
    solver_atol: float
    solver_btol: float
    solver_max_iterations: int
    nonconverged_policy: Literal["reject", "accept"]

    def __post_init__(self) -> None:
        for name, allowed in (
            ("dm_operator", {"linear_spline_local_sparse"}),
            ("wfs_geometry", {"compact_cells"}),
            ("calibration_strategy", {"grouped_local_noiseless"}),
            ("solver", {"lsmr"}),
            ("nonconverged_policy", {"reject", "accept"}),
        ):
            if getattr(self, name) not in allowed:
                raise SystemConfigError(f"unsupported scalable.{name}.")
        object.__setattr__(self, "solver_atol", _positive(self.solver_atol, "solver_atol"))
        object.__setattr__(self, "solver_btol", _positive(self.solver_btol, "solver_btol"))
        object.__setattr__(
            self,
            "solver_max_iterations",
            _integer(self.solver_max_iterations, "solver_max_iterations", minimum=1),
        )

    @property
    def config_hash(self) -> str:
        return component_config_hash("scao.scalable_path_config", self)


@dataclass(frozen=True, slots=True)
class CommandProjectorConfig:
    kind: Literal["identity", "controlled_subset", "modal"]
    mapping_resource: str | None

    def __post_init__(self) -> None:
        if self.kind not in {"identity", "controlled_subset", "modal"}:
            raise SystemConfigError("unsupported command-projector kind.")
        resource_name = _optional_text(self.mapping_resource, "mapping_resource")
        if self.kind == "modal" and resource_name is None:
            raise SystemConfigError("modal projector requires mapping_resource.")
        if self.kind != "modal" and resource_name is not None:
            raise SystemConfigError("mapping_resource is valid only for modal projectors.")
        object.__setattr__(self, "mapping_resource", resource_name)

    @property
    def config_hash(self) -> str:
        return component_config_hash("scao.command_projector_config", self)


@dataclass(frozen=True, slots=True)
class ControllerConfig:
    n_steps: int
    gain: float
    leak: float
    latency_frames: int
    frame_rate_hz: float
    include_noise: bool

    def __post_init__(self) -> None:
        object.__setattr__(self, "n_steps", _integer(self.n_steps, "n_steps", minimum=1))
        object.__setattr__(self, "gain", _nonnegative(self.gain, "gain"))
        leak = _fraction(self.leak, "leak")
        if leak >= 1.0:
            raise SystemConfigError("leak must be less than 1.")
        object.__setattr__(self, "leak", leak)
        object.__setattr__(self, "latency_frames", _integer(self.latency_frames, "latency_frames", minimum=0))
        object.__setattr__(self, "frame_rate_hz", _positive(self.frame_rate_hz, "frame_rate_hz"))
        object.__setattr__(self, "include_noise", _boolean(self.include_noise, "include_noise"))

    @property
    def config_hash(self) -> str:
        return component_config_hash("scao.controller_config", self)


@dataclass(frozen=True, slots=True)
class ScienceConfig:
    psf_pad_factor: int

    def __post_init__(self) -> None:
        object.__setattr__(self, "psf_pad_factor", _integer(self.psf_pad_factor, "psf_pad_factor", minimum=1))

    @property
    def config_hash(self) -> str:
        return component_config_hash("scao.science_config", self)


@dataclass(frozen=True, slots=True)
class RandomSeedConfig:
    root_seed: int
    derivation_scheme_id: str = DERIVATION_SCHEME_ID

    def __post_init__(self) -> None:
        object.__setattr__(self, "root_seed", _integer(self.root_seed, "root_seed", minimum=0))
        scheme = _text(self.derivation_scheme_id, "derivation_scheme_id")
        if scheme != DERIVATION_SCHEME_ID:
            raise SystemConfigError(
                f"derivation_scheme_id must be {DERIVATION_SCHEME_ID!r}."
            )
        object.__setattr__(self, "derivation_scheme_id", scheme)

    @property
    def config_hash(self) -> str:
        return component_config_hash("scao.random_seed_config", self)


@dataclass(frozen=True, slots=True)
class DetectorPhysicsConfig:
    """Schema-v7 physical camera path (``detector_physics`` block).

    ``camera`` names a packaged preset by name and version
    (``benchmarks/detector_camera_presets.v1.json``).  The nested blocks are
    the detector layer's own typed configurations; their identities are this
    block's identity.  Its presence selects the physical response; its
    absence keeps the AO-REF-004 compatibility chain.
    """

    camera_preset_name: str
    camera_preset_version: int
    layout_scheme: str
    guard_px: int
    source: Any
    bandpass: Any
    sampling: Any
    processing: Any
    exposure_subsamples: int
    # Optional bright internal calibration source (detected photoelectrons per
    # frame of a full subaperture).  Absent from a record when null, so every
    # record without one keeps its identity.
    calibration_source_detected_e_per_full_subap_frame: float | None = None

    def __post_init__(self) -> None:
        from ..detector.physical_config import (
            BandpassConfig,
            DetectorPlaneSamplingConfig,
            SourceBudgetConfig,
        )
        from ..detector.processing import PixelProcessingConfig
        from .camera_presets import CameraPresetError, load_camera_preset

        object.__setattr__(self, "camera_preset_name", _text(self.camera_preset_name, "camera_preset_name"))
        object.__setattr__(self, "camera_preset_version", _integer(self.camera_preset_version, "camera_preset_version", minimum=1))
        if self.layout_scheme != "isolated_lenslet_blocks.v1":
            raise SystemConfigError("layout_scheme must be 'isolated_lenslet_blocks.v1'.")
        object.__setattr__(self, "guard_px", _integer(self.guard_px, "guard_px", minimum=0))
        object.__setattr__(self, "exposure_subsamples", _integer(self.exposure_subsamples, "exposure_subsamples", minimum=1))
        for name, kind in (
            ("source", SourceBudgetConfig),
            ("bandpass", BandpassConfig),
            ("sampling", DetectorPlaneSamplingConfig),
            ("processing", PixelProcessingConfig),
        ):
            if not isinstance(getattr(self, name), kind):
                raise SystemConfigError(f"detector_physics.{name} has the wrong type.")
        try:
            camera = load_camera_preset(self.camera_preset_name, self.camera_preset_version)
        except CameraPresetError as exc:
            raise SystemConfigError(f"detector_physics.camera: {exc}") from exc
        if camera.has_coupling and self.guard_px < 1:
            raise SystemConfigError(
                "a camera with electronic coupling needs detector_physics.guard_px >= 1."
            )
        if self.calibration_source_detected_e_per_full_subap_frame is not None:
            object.__setattr__(
                self,
                "calibration_source_detected_e_per_full_subap_frame",
                _positive(
                    self.calibration_source_detected_e_per_full_subap_frame,
                    "calibration_source_detected_e_per_full_subap_frame",
                ),
            )

    @property
    def camera(self) -> Any:
        from .camera_presets import load_camera_preset

        return load_camera_preset(self.camera_preset_name, self.camera_preset_version)

    @property
    def config_hash(self) -> str:
        if self.calibration_source_detected_e_per_full_subap_frame is None:
            return component_config_hash(
                "scao.detector_physics_config",
                _DetectorPhysicsConfigWithoutCalibrationSource(
                    camera_preset_name=self.camera_preset_name,
                    camera_preset_version=self.camera_preset_version,
                    layout_scheme=self.layout_scheme,
                    guard_px=self.guard_px,
                    source=self.source,
                    bandpass=self.bandpass,
                    sampling=self.sampling,
                    processing=self.processing,
                    exposure_subsamples=self.exposure_subsamples,
                ),
            )
        return component_config_hash("scao.detector_physics_config", self)


@dataclass(frozen=True, slots=True)
class _DetectorPhysicsConfigWithoutCalibrationSource:
    """Hash shape of a ``detector_physics`` block without a calibration source.

    The same declared fields, order and schema id as before the optional
    source existed, so records without one keep their identity.
    """

    __hash_schema_id__ = "shwfs_ao.io.configs.DetectorPhysicsConfig"

    camera_preset_name: str
    camera_preset_version: int
    layout_scheme: str
    guard_px: int
    source: Any
    bandpass: Any
    sampling: Any
    processing: Any
    exposure_subsamples: int


@dataclass(frozen=True, slots=True)
class SystemConfig:
    backend: BackendName
    wfs_model: WfsModel
    atmosphere_model: AtmosphereModelName
    telescope_diameter_m: float
    pupil_pixels: int
    lenslets_across: int
    actuators_across: int
    wfs_wavelength_m: float
    science_wavelengths_m: tuple[float, ...]
    atmosphere: AtmosphereConfig
    detector: DetectorSystemConfig
    wfs: WfsConfig
    dm: DmSystemConfig
    calibration: CalibrationConfig
    reconstructor: ReconstructorConfig
    command_projector: CommandProjectorConfig
    controller: ControllerConfig
    science: ScienceConfig
    random: RandomSeedConfig
    profile: ProfileProvenance
    # Which profile record schema this configuration is a member of.  It is the
    # schema a parsed record declared, and the schema this configuration
    # serializes and hashes under, so a published record's identity never moves
    # because a later schema version was added.  Configurations built in code
    # rather than read from a record belong to the current schema.
    record_schema_version: int = PROFILE_SCHEMA_VERSION
    # Schema v5: the opt-in scalable high-order path, or None for the dense
    # reference path every earlier profile uses.
    scalable: ScalablePathConfig | None = None
    # Schema v7: the physical camera path, or None for the AO-REF-004
    # compatibility detector every earlier profile uses.
    detector_physics: DetectorPhysicsConfig | None = None

    def __post_init__(self) -> None:
        if self.backend not in {"native", "hcipy"}:
            raise SystemConfigError("backend must be native or hcipy.")
        if self.wfs_model not in {"geometric", "detector_level"}:
            raise SystemConfigError("wfs_model must be geometric or detector_level.")
        if self.atmosphere_model not in {
            "static",
            "native_frozen_flow",
            "native_frozen_flow_v2",
            "native_layered",
            "hcipy",
            "hcipy_layered",
        }:
            raise SystemConfigError("unsupported atmosphere_model.")
        object.__setattr__(self, "telescope_diameter_m", _positive(self.telescope_diameter_m, "telescope_diameter_m"))
        for name in ("pupil_pixels", "lenslets_across", "actuators_across"):
            object.__setattr__(self, name, _integer(getattr(self, name), name, minimum=2))
        object.__setattr__(self, "wfs_wavelength_m", _positive(self.wfs_wavelength_m, "wfs_wavelength_m"))
        wavelengths = _positive_tuple(self.science_wavelengths_m, "science_wavelengths_m")
        if tuple(sorted(wavelengths)) != wavelengths or len(set(wavelengths)) != len(wavelengths):
            raise SystemConfigError("science_wavelengths_m must be strictly increasing.")
        object.__setattr__(self, "science_wavelengths_m", wavelengths)
        expected = (
            (self.atmosphere, AtmosphereConfig, "atmosphere"),
            (self.detector, DetectorSystemConfig, "detector"),
            (self.wfs, WfsConfig, "wfs"),
            (self.dm, DmSystemConfig, "dm"),
            (self.calibration, CalibrationConfig, "calibration"),
            (self.reconstructor, ReconstructorConfig, "reconstructor"),
            (self.command_projector, CommandProjectorConfig, "command_projector"),
            (self.controller, ControllerConfig, "controller"),
            (self.science, ScienceConfig, "science"),
            (self.random, RandomSeedConfig, "random"),
            (self.profile, ProfileProvenance, "profile"),
        )
        for value, value_type, label in expected:
            if not isinstance(value, value_type):
                raise SystemConfigError(f"{label} has the wrong configuration type.")
        if (self.atmosphere_model in _LAYERED_ATMOSPHERE_MODELS) != bool(
            self.atmosphere.layers
        ):
            raise SystemConfigError(
                "atmosphere_model='native_layered' or 'hcipy_layered' requires "
                "atmosphere.layers, and no other atmosphere model accepts them."
            )
        physics = self.detector_physics
        if physics is not None and not isinstance(physics, DetectorPhysicsConfig):
            raise SystemConfigError("detector_physics has the wrong configuration type.")
        mft_sampling = physics is not None and physics.sampling.kind == "mft_pixel_integrated"
        if self.wfs_model == "detector_level":
            if not self.detector.enabled or self.wfs.detector_window_px is None:
                raise SystemConfigError("detector_level requires enabled detector and explicit pad/window sampling.")
            if mft_sampling:
                if self.wfs.pad_factor is not None:
                    raise SystemConfigError(
                        "mft_pixel_integrated sampling declares its pixel scale; "
                        "wfs.pad_factor must be null (declare one mapping, not both)."
                    )
            elif self.wfs.pad_factor is None:
                raise SystemConfigError("detector_level requires enabled detector and explicit pad/window sampling.")
        elif self.detector.enabled or self.wfs.pad_factor is not None or self.wfs.detector_window_px is not None:
            raise SystemConfigError("geometric WFS requires disabled detector and null pad/window sampling.")
        if self.detector.enabled and physics is None and self.detector.photons_per_subap_frame is None:
            raise SystemConfigError(
                "enabled detector profiles require photons_per_subap_frame."
            )
        if self.calibration.probe_kind == "modal" and self.command_projector.kind != "modal":
            raise SystemConfigError("modal calibration requires a modal command projector.")
        if self.calibration.probe_kind == "dm_actuator" and self.command_projector.kind == "modal":
            raise SystemConfigError("DM-actuator calibration cannot use a modal projector.")
        record_version = _integer(
            self.record_schema_version, "record_schema_version", minimum=1
        )
        if record_version not in SUPPORTED_PROFILE_SCHEMA_VERSIONS:
            raise SystemConfigError(
                f"unsupported profile schema_version={self.record_schema_version!r}; "
                f"supported={list(SUPPORTED_PROFILE_SCHEMA_VERSIONS)}."
            )
        # A configuration may only claim a record schema that can express it.
        # Schema v1 has no wfs.photon_allocation field and predates the v2
        # profile review, so a v1 record carrying either a non-default
        # allocation or a later profile version would present a *defaulted*
        # policy as the explicitly reviewed one — exactly the ambiguity schema
        # v2 exists to remove.  Refusing is the only outcome that keeps a
        # record and the identity it hashes to describing the same thing:
        # silently promoting to v2 would move a published hash, and silently
        # dropping the field would lose physics.
        if record_version == 1:
            if self.profile.profile_version != 1:
                raise SystemConfigError(
                    f"profile {self.profile.profile_id} cannot be recorded under "
                    "schema version 1: that schema predates "
                    "wfs.photon_allocation, so the profile's allocation policy "
                    "would be defaulted rather than stated."
                )
            if self.wfs.photon_allocation != _V1_PHOTON_ALLOCATION:
                raise SystemConfigError(
                    "record_schema_version=1 cannot express "
                    f"wfs.photon_allocation={self.wfs.photon_allocation!r}: that "
                    "schema has no such field, so the value would be lost. Build "
                    f"this configuration from a schema-{PROFILE_SCHEMA_VERSION} "
                    "profile instead."
                )
        # Schemas v1 and v2 have no field to keep negative pixels, so a record
        # under either would present a clipping sensor; refuse it by the same
        # rule.  Recording it needs the current schema, for example through
        # ``replace(config, record_schema_version=PROFILE_SCHEMA_VERSION)``.
        if (
            record_version < 3
            and self.wfs.clip_negative_pixels != _PRE_V3_CLIP_NEGATIVE_PIXELS
        ):
            raise SystemConfigError(
                f"record_schema_version={record_version} cannot express "
                f"wfs.clip_negative_pixels={self.wfs.clip_negative_pixels!r}: "
                "that schema has no such field, so the value would be lost. "
                f"Record this configuration under schema {PROFILE_SCHEMA_VERSION} "
                "instead."
            )
        # Schemas v1-v5 have no wfs.lenslet_axis field, so a record under one
        # of them would present a block-centred HCIPy sensor as a published
        # cell-centred one; refuse it by the same rule.
        if (
            record_version < 6
            and self.wfs.lenslet_axis != _PRE_V6_LENSLET_AXIS
        ):
            raise SystemConfigError(
                f"record_schema_version={record_version} cannot express "
                f"wfs.lenslet_axis={self.wfs.lenslet_axis!r}: that schema has "
                "no such field, so the value would be lost. Record this "
                f"configuration under schema {PROFILE_SCHEMA_VERSION} instead."
            )
        # Only the HCIPy detector-level sensor places lens vertices.  Any other
        # sensor would ignore a non-default convention while its identity
        # claimed it, so the pairing is refused.
        if self.wfs.lenslet_axis != _PRE_V6_LENSLET_AXIS and (
            self.backend != "hcipy" or self.wfs_model != "detector_level"
        ):
            raise SystemConfigError(
                f"wfs.lenslet_axis={self.wfs.lenslet_axis!r} applies to the "
                "HCIPy detector-level sensor only; the native optics centre "
                "every spot on its own FFT canvas and never consult it."
            )
        # Schemas v1-v3 have no atmosphere.layers field: a record under one of
        # them can describe only a single-layer atmosphere.
        if record_version < 4 and self.atmosphere.layers:
            raise SystemConfigError(
                f"record_schema_version={record_version} cannot express "
                "atmosphere.layers: that schema has no such field, so the "
                "layers would be lost. Record this configuration under schema "
                f"{PROFILE_SCHEMA_VERSION} instead."
            )
        # Schema v5 alone can express the scalable path and its two new
        # vocabulary items; an older record carrying any of them would lose it.
        if record_version < 5:
            if self.scalable is not None:
                raise SystemConfigError(
                    f"record_schema_version={record_version} cannot express the "
                    "scalable block; record this configuration under schema 5."
                )
            if self.dm.influence_model == "linear_spline":
                raise SystemConfigError(
                    f"record_schema_version={record_version} cannot express "
                    "dm.influence_model='linear_spline'."
                )
            if self.reconstructor.kind == "sparse_lsmr_tikhonov":
                raise SystemConfigError(
                    f"record_schema_version={record_version} cannot express "
                    "reconstructor.kind='sparse_lsmr_tikhonov'."
                )
        if self.scalable is not None and not isinstance(self.scalable, ScalablePathConfig):
            raise SystemConfigError("scalable has the wrong configuration type.")
        _validate_scalable_pairing(self)
        if record_version < 7 and physics is not None:
            raise SystemConfigError(
                f"record_schema_version={record_version} cannot express the "
                "detector_physics block; record this configuration under schema 7."
            )
        if record_version >= 7:
            _validate_schema7_rules(self)
        object.__setattr__(self, "record_schema_version", record_version)

    @property
    def config_hash(self) -> str:
        return component_config_hash("scao.system_config", system_config_to_mapping(self))

    @property
    def observing_conditions_hash(self) -> str:
        conditions: dict[str, object] = {
            "telescope_diameter_m": self.telescope_diameter_m,
            "wfs_wavelength_m": self.wfs_wavelength_m,
            "science_wavelengths_m": self.science_wavelengths_m,
            "atmosphere_model": self.atmosphere_model,
            # Single-layer blocks hash as their pre-v4 shape, so a
            # published profile's observing conditions keep their identity.
            "atmosphere": self.atmosphere._hash_view(),
            "detector": self.detector,
        }
        # The physical source/sky budget, band and camera are observing
        # conditions; the key exists only when the v7 block does.
        if self.detector_physics is not None:
            conditions["detector_physics_source"] = self.detector_physics.source
            conditions["detector_physics_bandpass"] = self.detector_physics.bandpass
            conditions["detector_physics_camera"] = (
                self.detector_physics.camera_preset_name,
                self.detector_physics.camera_preset_version,
            )
        return component_config_hash("scao.observing_conditions", conditions)

    @property
    def component_config_hashes(self) -> Mapping[str, str]:
        """Per-component identities as this configuration's record publishes them.

        These are public identities: a stored result cites the ``"wfs"`` entry to
        say which sensing policy produced it, so they are subject to the same
        rule as :attr:`config_hash` — a record's identity may not move because a
        later schema version was added elsewhere.  ``"wfs"`` is the one entry
        that cannot simply delegate to its component's ``config_hash``, because
        the nested hash is taken from the :class:`WfsConfig` dataclass rather
        than from :func:`system_config_to_mapping`, and schema v2 added a field
        to that dataclass.  Passing the record schema down is what keeps a v1
        record's nested WFS hash at the value it was published with, exactly as
        deleting the field from the serialized mapping keeps ``config_hash``
        there.  Every other component's field set is schema-independent, so
        their plain ``config_hash`` is already the published value.
        """

        hashes = {
                "profile": self.profile.config_hash,
                "atmosphere": self.atmosphere.config_hash,
                "detector": self.detector.config_hash,
                "wfs": self.wfs.config_hash_for_record_schema(
                    self.record_schema_version
                ),
                "dm": self.dm.config_hash,
                "calibration": self.calibration.config_hash,
                "reconstructor": self.reconstructor.config_hash,
                "command_projector": self.command_projector.config_hash,
                "controller": self.controller.config_hash,
                "science": self.science.config_hash,
                "random": self.random.config_hash,
        }
        # The key exists only for schema-v5 records, so earlier records keep
        # exactly the identity map they were published with.
        if self.record_schema_version >= 5:
            hashes["scalable"] = (
                component_config_hash("scao.scalable_path_config", None)
                if self.scalable is None
                else self.scalable.config_hash
            )
        # Likewise only schema-v7 records carry the detector_physics key.
        if self.record_schema_version >= 7:
            hashes["detector_physics"] = (
                component_config_hash("scao.detector_physics_config", None)
                if self.detector_physics is None
                else self.detector_physics.config_hash
            )
        return MappingProxyType(hashes)


def _validate_scalable_pairing(config: SystemConfig) -> None:
    """The scalable path is all-or-nothing and native, detector-level only."""

    scalable = config.scalable
    sparse_solver = config.reconstructor.kind == "sparse_lsmr_tikhonov"
    linear_spline = config.dm.influence_model == "linear_spline"
    if scalable is None:
        if sparse_solver or linear_spline:
            raise SystemConfigError(
                "linear_spline DMs and the sparse_lsmr_tikhonov reconstructor "
                "require the scalable block."
            )
        return
    requirements = (
        (config.backend == "native", "backend='native'"),
        (config.wfs_model == "detector_level", "wfs_model='detector_level'"),
        (linear_spline, "dm.influence_model='linear_spline'"),
        (config.calibration.probe_kind == "dm_actuator", "calibration.probe_kind='dm_actuator'"),
        (not config.calibration.include_noise, "calibration.include_noise=false"),
        (config.calibration.source in {"build", "supplied"}, "calibration.source build or supplied"),
        (sparse_solver, "reconstructor.kind='sparse_lsmr_tikhonov'"),
        (config.command_projector.kind == "controlled_subset", "command_projector.kind='controlled_subset'"),
    )
    missing = [label for ok, label in requirements if not ok]
    if missing:
        raise SystemConfigError(
            "the scalable path requires " + ", ".join(missing) + "."
        )


def _validate_schema7_rules(config: SystemConfig) -> None:
    """New-schema rules: exposure within the frame, symmetric window, physics pairing."""

    detector = config.detector
    frame_period_s = 1.0 / config.controller.frame_rate_hz
    if config.wfs_model == "detector_level" and detector.exposure_s > frame_period_s * (1.0 + 1.0e-12):
        raise SystemConfigError(
            f"detector.exposure_s={detector.exposure_s!r} exceeds the frame period "
            f"{frame_period_s!r} s; a schema-7 record integrates within one frame."
        )
    window = config.wfs.detector_window_px
    if config.wfs_model == "detector_level" and window is not None:
        if config.backend == "native" and window % 2 != 1:
            raise SystemConfigError(
                "a schema-7 native detector-level record needs an odd "
                "wfs.detector_window_px, symmetric about the optical-axis pixel "
                "(docs/refactor/eso_scao_evidence/published_profile_window_bias.md)."
            )
        if config.backend == "hcipy" and config.wfs.lenslet_axis != "pixel_block_center":
            raise SystemConfigError(
                "a schema-7 HCIPy detector-level record needs "
                "wfs.lenslet_axis='pixel_block_center' so each spot axis is "
                "symmetric in its block window."
            )
    physics = config.detector_physics
    if physics is None:
        return
    requirements = (
        (config.backend == "native", "backend='native' (HCIPy fails closed for the physical camera path)"),
        (config.wfs_model == "detector_level", "wfs_model='detector_level'"),
        (detector.enabled, "detector.enabled=true"),
        (detector.photons_per_subap_frame is None, "detector.photons_per_subap_frame=null (the source block owns the budget)"),
        (detector.qe == 1.0, "detector.qe=1 (the camera preset owns QE, applied once)"),
        (detector.read_noise_e == 0.0, "detector.read_noise_e=0"),
        (detector.dark_e_per_s == 0.0, "detector.dark_e_per_s=0"),
        (detector.background_e_per_pixel_frame == 0.0, "detector.background_e_per_pixel_frame=0"),
        (detector.full_well_e is None, "detector.full_well_e=null"),
        (detector.prnu_rms == 0.0, "detector.prnu_rms=0"),
        (detector.bad_pixel_fraction == 0.0, "detector.bad_pixel_fraction=0"),
        (detector.prnu_mode == "persistent", "detector.prnu_mode='persistent'"),
        (config.wfs.photon_allocation == "throughput_scaled", "wfs.photon_allocation='throughput_scaled'"),
        (not config.wfs.clip_negative_pixels or physics.processing.clip_negative,
         "wfs.clip_negative_pixels=false unless the processing block clips (the processing block owns clipping)"),
    )
    missing = [label for ok, label in requirements if not ok]
    if missing:
        raise SystemConfigError(
            "the detector_physics block requires " + "; ".join(missing) + "."
        )
    if physics.sampling.kind == "legacy_fft" and physics.bandpass.kind != "monochromatic":
        raise SystemConfigError("a polychromatic bandpass needs mft_pixel_integrated sampling.")
    if physics.bandpass.kind == "monochromatic" and not (
        physics.bandpass.band_min_m <= config.wfs_wavelength_m <= physics.bandpass.band_max_m
    ):
        raise SystemConfigError("wfs_wavelength_m must lie inside the declared monochromatic band.")
    if physics.exposure_subsamples > 1 and config.atmosphere_model == "static":
        raise SystemConfigError("exposure sub-samples need a time-dependent atmosphere.")


def available_system_profiles() -> tuple[tuple[str, int], ...]:
    """Return every installed profile as an explicit ``(name, version)`` key."""

    return tuple(_PROFILE_RESOURCES)


def load_system_profile(name: str, version: int) -> SystemConfig:
    """Load one exact installed profile; no implicit latest version exists."""

    key = (_profile_name(name), _integer(version, "version", minimum=1))
    try:
        logical_name = _PROFILE_RESOURCES[key]
    except KeyError as exc:
        raise SystemConfigError(
            f"unknown system profile {key!r}; available={available_system_profiles()!r}."
        ) from exc
    try:
        payload = read_text_resource(logical_name)
        record = json.loads(
            payload,
            object_pairs_hook=_unique_object,
            parse_constant=_invalid_json_constant,
        )
    except (OSError, json.JSONDecodeError, TypeError, ValueError) as exc:
        if isinstance(exc, SystemConfigError):
            raise
        raise SystemConfigError(f"cannot load system profile {key!r}: {exc}") from exc
    config = system_config_from_mapping(_mapping(record, "profile record"))
    if (config.profile.profile_name, config.profile.profile_version) != key:
        raise SystemConfigError("profile resource identity does not match the requested key.")
    return config


def system_config_from_mapping(record: Mapping[str, object]) -> SystemConfig:
    """Parse one strict profile-schema mapping into :class:`SystemConfig`.

    Every version in :data:`SUPPORTED_PROFILE_SCHEMA_VERSIONS` parses, because a
    published profile must stay readable for exactly as long as results cite it.
    Schema v2 requires ``wfs.photon_allocation``; schema v1 predates the field
    and must omit it, taking the ``throughput_scaled`` allocation the v1
    profiles were reviewed and published under.  Schema v3 likewise requires
    ``wfs.clip_negative_pixels``, which v1 and v2 records omit, taking the
    clipping they were published with.  Schema v4 requires
    ``atmosphere.layers`` (an empty list for a single-layer atmosphere), which
    v1-v3 records omit.  Schema v6 requires ``wfs.lenslet_axis``, which v1-v5
    records omit, taking the ``geometry_cell_center`` vertices they were
    published with.  Each version's field set is exact in both directions,
    so an older record can neither carry a later field nor be silently
    upgraded, and a newer record can never omit one.
    """

    root = _mapping(record, "profile record")
    _keys(
        root,
        {
            "schema_name",
            "schema_version",
            "profile_name",
            "profile_version",
            "baseline_rationale",
            "provenance",
            "config",
        },
        "profile record",
    )
    if root["schema_name"] != PROFILE_SCHEMA_NAME:
        raise SystemConfigError(f"schema_name must be {PROFILE_SCHEMA_NAME!r}.")
    schema_version = _integer(root["schema_version"], "schema_version", minimum=1)
    if schema_version not in SUPPORTED_PROFILE_SCHEMA_VERSIONS:
        raise SystemConfigError(
            f"unsupported profile schema_version={root['schema_version']!r}; "
            f"supported={list(SUPPORTED_PROFILE_SCHEMA_VERSIONS)}."
        )
    profile = ProfileProvenance(
        profile_name=cast(str, root["profile_name"]),
        profile_version=cast(int, root["profile_version"]),
        baseline_rationale=cast(str, root["baseline_rationale"]),
        provenance=_provenance(root["provenance"]),
    )
    # The two versions are independent axes, but not every pairing is coherent;
    # :meth:`SystemConfig.__post_init__` owns that rule, because it must hold
    # for a configuration however it was made, not only for a parsed record.
    values = _mapping(root["config"], "config")
    system_fields = set(_SYSTEM_FIELDS)
    if schema_version >= 5:
        system_fields.add("scalable")
    if schema_version >= 7:
        system_fields.add("detector_physics")
    _keys(values, system_fields, "config")
    scalable_record = values.get("scalable") if schema_version >= 5 else None
    physics_record = values.get("detector_physics") if schema_version >= 7 else None
    return SystemConfig(
        backend=cast(BackendName, values["backend"]),
        wfs_model=cast(WfsModel, values["wfs_model"]),
        atmosphere_model=cast(AtmosphereModelName, values["atmosphere_model"]),
        telescope_diameter_m=cast(float, values["telescope_diameter_m"]),
        pupil_pixels=cast(int, values["pupil_pixels"]),
        lenslets_across=cast(int, values["lenslets_across"]),
        actuators_across=cast(int, values["actuators_across"]),
        wfs_wavelength_m=cast(float, values["wfs_wavelength_m"]),
        science_wavelengths_m=_tuple_value(values["science_wavelengths_m"], "science_wavelengths_m"),
        atmosphere=_atmosphere_config(values["atmosphere"], schema_version),
        detector=_construct(DetectorSystemConfig, values["detector"], _DETECTOR_FIELDS, "detector"),
        wfs=_construct(
            WfsConfig,
            values["wfs"],
            (
                _WFS_FIELDS
                if schema_version >= 6
                else _WFS_FIELDS_V5
                if schema_version >= 3
                else _WFS_FIELDS_V2
                if schema_version == 2
                else _WFS_FIELDS_V1
            ),
            "wfs",
        ),
        dm=_construct(DmSystemConfig, values["dm"], _DM_FIELDS, "dm", tuple_fields={"dead_actuator_indices", "stuck_actuator_indices"}),
        calibration=_construct(CalibrationConfig, values["calibration"], _CALIBRATION_FIELDS, "calibration"),
        reconstructor=_construct(ReconstructorConfig, values["reconstructor"], _RECONSTRUCTOR_FIELDS, "reconstructor"),
        command_projector=_construct(CommandProjectorConfig, values["command_projector"], _PROJECTOR_FIELDS, "command_projector"),
        controller=_construct(ControllerConfig, values["controller"], _CONTROLLER_FIELDS, "controller"),
        science=_construct(ScienceConfig, values["science"], _SCIENCE_FIELDS, "science"),
        random=_construct(RandomSeedConfig, values["random"], _RANDOM_FIELDS, "random"),
        profile=profile,
        record_schema_version=schema_version,
        scalable=(
            None
            if scalable_record is None
            else _construct(ScalablePathConfig, scalable_record, _SCALABLE_FIELDS, "scalable")
        ),
        detector_physics=(
            None if physics_record is None else _detector_physics_config(physics_record)
        ),
    )


def system_config_to_mapping(config: SystemConfig) -> dict[str, object]:
    """Serialize a system config to its own deterministic record schema.

    Serialization is to :attr:`SystemConfig.record_schema_version` — the schema
    the configuration belongs to, which for a parsed record is the schema that
    record declared.  This mapping is the canonical hashing basis, so one config
    always has one serialized form, and a record round-trips to a byte-identical
    mapping through the schema it was published under.

    That is what keeps a published identity stable, because the schema version
    is *inside* the hashed mapping.  Serializing every configuration under the
    newest schema would change ``SystemConfig.config_hash`` for profiles whose
    physics and whose packaged record never changed, so a result labelled with
    such a profile would stop reproducing its own hash.  Adding a schema version
    therefore only affects records written under it; ``tests/io/test_configs.py``
    pins every packaged identity so any movement is caught.
    """

    if not isinstance(config, SystemConfig):
        raise SystemConfigError("config must be a SystemConfig.")
    profile = config.profile
    wfs_fields = _dataclass_mapping(config.wfs)
    # Earlier schemas lack these fields, and __post_init__ has already refused
    # any configuration whose value an omission would lose.
    if config.record_schema_version < 6:
        del wfs_fields["lenslet_axis"]
    if config.record_schema_version < 3:
        del wfs_fields["clip_negative_pixels"]
    if config.record_schema_version < 2:
        del wfs_fields["photon_allocation"]
    atmosphere_fields = _dataclass_mapping(config.atmosphere)
    if config.record_schema_version < 4:
        del atmosphere_fields["layers"]
    else:
        atmosphere_fields["layers"] = [
            _dataclass_mapping(layer) for layer in config.atmosphere.layers
        ]
    record: dict[str, object] = {
        "schema_name": PROFILE_SCHEMA_NAME,
        "schema_version": config.record_schema_version,
        "profile_name": profile.profile_name,
        "profile_version": profile.profile_version,
        "baseline_rationale": profile.baseline_rationale,
        "provenance": profile.provenance.to_record(),
        "config": {
            "backend": config.backend,
            "wfs_model": config.wfs_model,
            "atmosphere_model": config.atmosphere_model,
            "telescope_diameter_m": config.telescope_diameter_m,
            "pupil_pixels": config.pupil_pixels,
            "lenslets_across": config.lenslets_across,
            "actuators_across": config.actuators_across,
            "wfs_wavelength_m": config.wfs_wavelength_m,
            "science_wavelengths_m": list(config.science_wavelengths_m),
            "atmosphere": atmosphere_fields,
            "detector": _dataclass_mapping(config.detector),
            "wfs": wfs_fields,
            "dm": _dataclass_mapping(config.dm),
            "calibration": _dataclass_mapping(config.calibration),
            "reconstructor": _dataclass_mapping(config.reconstructor),
            "command_projector": _dataclass_mapping(config.command_projector),
            "controller": _dataclass_mapping(config.controller),
            "science": _dataclass_mapping(config.science),
            "random": _dataclass_mapping(config.random),
        },
    }
    if config.record_schema_version >= 5:
        config_record = record["config"]
        assert isinstance(config_record, dict)
        config_record["scalable"] = (
            None if config.scalable is None else _dataclass_mapping(config.scalable)
        )
    if config.record_schema_version >= 7:
        config_record = record["config"]
        assert isinstance(config_record, dict)
        config_record["detector_physics"] = (
            None
            if config.detector_physics is None
            else _detector_physics_mapping(config.detector_physics)
        )
    return record


_SYSTEM_FIELDS = {"backend", "wfs_model", "atmosphere_model", "telescope_diameter_m", "pupil_pixels", "lenslets_across", "actuators_across", "wfs_wavelength_m", "science_wavelengths_m", "atmosphere", "detector", "wfs", "dm", "calibration", "reconstructor", "command_projector", "controller", "science", "random"}
_ATMOSPHERE_FIELDS = {"r0_m", "r0_reference_wavelength_m", "outer_scale_m", "wind_m_per_s", "target_rms_opd_m", "normalize_rms", "layers"}
# Schemas v1-v3 predate atmosphere.layers and describe single-layer atmospheres.
_ATMOSPHERE_FIELDS_V3 = _ATMOSPHERE_FIELDS - {"layers"}
_ATMOSPHERE_LAYER_FIELDS = {"altitude_m", "cn2_fraction", "wind_m_per_s"}
_DETECTOR_FIELDS = {"enabled", "photons_per_subap_frame", "read_noise_e", "dark_e_per_s", "background_e_per_pixel_frame", "full_well_e", "qe", "prnu_rms", "exposure_s", "prnu_mode", "bad_pixel_fraction"}
_WFS_FIELDS = {"min_fill_fraction", "pad_factor", "detector_window_px", "centroid_estimator", "threshold_fraction", "subtract_minimum", "min_flux_e", "min_peak_snr", "max_centroid_sigma_px", "max_window_clipping_fraction", "central_obstruction_ratio", "spider_width_m", "photon_allocation", "clip_negative_pixels", "lenslet_axis"}
# Schema v6 requires lenslet_axis: it moves every HCIPy spot axis, so a v6
# record states it.  Schemas v3-v5 predate it.
_WFS_FIELDS_V5 = _WFS_FIELDS - {"lenslet_axis"}
# Schema v3 requires clip_negative_pixels for the same reason: whether negative
# pixels are clipped changes every noisy centroid, so a v3 record states it.
_WFS_FIELDS_V2 = _WFS_FIELDS_V5 - {"clip_negative_pixels"}
# Schema v2 requires photon_allocation in every profile: it materially affects
# the WFS photon budget and therefore the recorded identity, so a v2 record
# never defaults it silently.  Schema v1 predates the field, so a v1 record must
# omit it and takes the reviewed "throughput_scaled" default it was published
# with; carrying it would make the record neither a valid v1 nor a valid v2.
_WFS_FIELDS_V1 = _WFS_FIELDS_V2 - {"photon_allocation"}
_DM_FIELDS = {"influence_model", "coupling_width_pitch", "stroke_limit_opd_m", "include_edge_actuators", "actuator_margin_fraction", "dead_actuator_indices", "stuck_actuator_indices", "stuck_command_opd_m"}
_CALIBRATION_FIELDS = {"source", "method", "probe_kind", "amplitude_m", "include_noise", "repeats", "resource_name"}
_RECONSTRUCTOR_FIELDS = {"kind", "rcond", "alpha", "min_valid_fraction", "min_rank", "max_cached_masks"}
_PROJECTOR_FIELDS = {"kind", "mapping_resource"}
_CONTROLLER_FIELDS = {"n_steps", "gain", "leak", "latency_frames", "frame_rate_hz", "include_noise"}
_SCIENCE_FIELDS = {"psf_pad_factor"}
_SCALABLE_FIELDS = {"dm_operator", "wfs_geometry", "calibration_strategy", "solver", "solver_atol", "solver_btol", "solver_max_iterations", "nonconverged_policy"}
_RANDOM_FIELDS = {"root_seed", "derivation_scheme_id"}
_PHYSICS_FIELDS = {"camera", "layout", "source", "bandpass", "sampling", "processing", "exposure_subsamples"}
_PHYSICS_CAMERA_FIELDS = {"preset_name", "preset_version"}
_PHYSICS_LAYOUT_FIELDS = {"scheme", "guard_px"}
_PHYSICS_SOURCE_FIELDS = {"kind", "ab_magnitude", "incident_photons_per_full_subap_frame", "detected_e_per_full_subap_frame", "throughput_excluding_qe", "sky_ab_mag_per_arcsec2"}
_PHYSICS_BANDPASS_FIELDS = {"kind", "band_min_m", "band_max_m", "n_samples"}
_PHYSICS_SAMPLING_FIELDS = {"kind", "pixel_scale_rad", "oversampling", "diffusion_sigma_px"}
_PHYSICS_PROCESSING_FIELDS = {"mode", "n_bias_frames", "n_dark_frames", "n_sky_frames", "n_flat_frames", "flat_level_e", "hot_pixel_threshold_e", "flat_low_threshold", "flat_high_threshold", "bad_pixel_policy", "gain_treatment", "clip_negative"}


def _detector_physics_config(value: object) -> DetectorPhysicsConfig:
    from ..detector.physical_config import (
        BandpassConfig,
        DetectorPlaneSamplingConfig,
        SourceBudgetConfig,
    )
    from ..detector.processing import PixelProcessingConfig

    record = _mapping(value, "detector_physics")
    _keys(
        record,
        _PHYSICS_FIELDS | {"calibration_source_detected_e_per_full_subap_frame"},
        "detector_physics",
        optional={"calibration_source_detected_e_per_full_subap_frame"},
    )
    camera = _mapping(record["camera"], "detector_physics.camera")
    _keys(camera, _PHYSICS_CAMERA_FIELDS, "detector_physics.camera")
    layout = _mapping(record["layout"], "detector_physics.layout")
    _keys(layout, _PHYSICS_LAYOUT_FIELDS, "detector_physics.layout")
    try:
        return DetectorPhysicsConfig(
            camera_preset_name=cast(str, camera["preset_name"]),
            camera_preset_version=cast(int, camera["preset_version"]),
            layout_scheme=cast(str, layout["scheme"]),
            guard_px=cast(int, layout["guard_px"]),
            source=_construct(SourceBudgetConfig, record["source"], _PHYSICS_SOURCE_FIELDS, "detector_physics.source"),
            bandpass=_construct(BandpassConfig, record["bandpass"], _PHYSICS_BANDPASS_FIELDS, "detector_physics.bandpass"),
            sampling=_construct(DetectorPlaneSamplingConfig, record["sampling"], _PHYSICS_SAMPLING_FIELDS, "detector_physics.sampling"),
            processing=_construct(PixelProcessingConfig, record["processing"], _PHYSICS_PROCESSING_FIELDS, "detector_physics.processing"),
            exposure_subsamples=cast(int, record["exposure_subsamples"]),
            calibration_source_detected_e_per_full_subap_frame=cast(
                float | None,
                record.get("calibration_source_detected_e_per_full_subap_frame"),
            ),
        )
    except (TypeError, ValueError) as exc:
        if isinstance(exc, SystemConfigError):
            raise
        raise SystemConfigError(f"invalid detector_physics: {exc}") from exc


def _detector_physics_mapping(config: DetectorPhysicsConfig) -> dict[str, object]:
    mapping = _detector_physics_base_mapping(config)
    if config.calibration_source_detected_e_per_full_subap_frame is not None:
        mapping["calibration_source_detected_e_per_full_subap_frame"] = (
            config.calibration_source_detected_e_per_full_subap_frame
        )
    return mapping


def _detector_physics_base_mapping(config: DetectorPhysicsConfig) -> dict[str, object]:
    return {
        "camera": {
            "preset_name": config.camera_preset_name,
            "preset_version": config.camera_preset_version,
        },
        "layout": {"scheme": config.layout_scheme, "guard_px": config.guard_px},
        "source": _dataclass_mapping(config.source),
        "bandpass": _dataclass_mapping(config.bandpass),
        "sampling": _dataclass_mapping(config.sampling),
        "processing": _dataclass_mapping(config.processing),
        "exposure_subsamples": config.exposure_subsamples,
    }


def _atmosphere_config(value: object, schema_version: int) -> AtmosphereConfig:
    if schema_version < 4:
        return _construct(
            AtmosphereConfig,
            value,
            _ATMOSPHERE_FIELDS_V3,
            "atmosphere",
            tuple_fields={"wind_m_per_s"},
        )
    mapping = dict(_mapping(value, "atmosphere"))
    _keys(mapping, _ATMOSPHERE_FIELDS, "atmosphere")
    mapping["layers"] = tuple(
        _construct(
            AtmosphereLayerConfig,
            layer,
            _ATMOSPHERE_LAYER_FIELDS,
            f"atmosphere.layers[{index}]",
            tuple_fields={"wind_m_per_s"},
        )
        for index, layer in enumerate(
            _tuple_value(mapping["layers"], "atmosphere.layers")
        )
    )
    return _construct(
        AtmosphereConfig,
        mapping,
        _ATMOSPHERE_FIELDS,
        "atmosphere",
        tuple_fields={"wind_m_per_s"},
    )


def _construct(
    cls: type[Any],
    value: object,
    fields: set[str],
    label: str,
    *,
    tuple_fields: frozenset[str] | set[str] = frozenset(),
    optional_fields: frozenset[str] | set[str] = frozenset(),
) -> Any:
    mapping = _mapping(value, label)
    _keys(mapping, fields, label, optional=optional_fields)
    kwargs = dict(mapping)
    for name in tuple_fields:
        kwargs[name] = _tuple_value(kwargs[name], f"{label}.{name}")
    try:
        return cls(**kwargs)
    except (TypeError, ValueError) as exc:
        if isinstance(exc, SystemConfigError):
            raise
        raise SystemConfigError(f"invalid {label}: {exc}") from exc


def _dataclass_mapping(value: object) -> dict[str, object]:
    names = value.__dataclass_fields__  # type: ignore[attr-defined]
    result: dict[str, object] = {}
    for name in names:
        item = getattr(value, name)
        result[name] = list(item) if isinstance(item, tuple) else item
    return result


def _provenance(value: object) -> Provenance:
    try:
        return Provenance.from_record(_mapping(value, "provenance"))
    except ValueError as exc:
        raise SystemConfigError(f"invalid profile provenance: {exc}") from exc


def _keys(
    value: Mapping[str, object],
    expected: set[str],
    label: str,
    *,
    optional: frozenset[str] | set[str] = frozenset(),
) -> None:
    actual = set(value)
    missing = sorted(expected - optional - actual)
    unknown = sorted(actual - expected)
    if missing or unknown:
        raise SystemConfigError(f"{label} fields mismatch; missing={missing}, unknown={unknown}.")


def _mapping(value: object, label: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping) or not all(isinstance(key, str) for key in value):
        raise SystemConfigError(f"{label} must be a string-keyed mapping.")
    return cast(Mapping[str, object], value)


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise SystemConfigError(f"duplicate JSON key {key!r}.")
        result[key] = value
    return result


def _invalid_json_constant(value: str) -> None:
    raise SystemConfigError(f"non-finite JSON number {value!r} is not permitted.")


def _text(value: object, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise SystemConfigError(f"{label} must be a non-empty string.")
    return value.strip()


def _optional_text(value: object, label: str) -> str | None:
    return None if value is None else _text(value, label)


def _profile_name(value: object) -> str:
    name = _text(value, "profile_name")
    if _PROFILE_NAME.fullmatch(name) is None:
        raise SystemConfigError("profile_name must use lowercase snake_case.")
    return name


def _boolean(value: object, label: str) -> bool:
    if not isinstance(value, bool):
        raise SystemConfigError(f"{label} must be a boolean.")
    return value


def _integer(value: object, label: str, *, minimum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, Integral):
        raise SystemConfigError(f"{label} must be an integer.")
    result = int(value)
    if result < minimum:
        raise SystemConfigError(f"{label} must be >= {minimum}.")
    return result


def _optional_integer(value: object, label: str, *, minimum: int) -> int | None:
    return None if value is None else _integer(value, label, minimum=minimum)


def _finite(value: object, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, Real):
        raise SystemConfigError(f"{label} must be a finite real number.")
    result = float(value)
    if not math.isfinite(result):
        raise SystemConfigError(f"{label} must be finite.")
    return result


def _positive(value: object, label: str) -> float:
    result = _finite(value, label)
    if result <= 0.0:
        raise SystemConfigError(f"{label} must be positive.")
    return result


def _nonnegative(value: object, label: str) -> float:
    result = _finite(value, label)
    if result < 0.0:
        raise SystemConfigError(f"{label} must be non-negative.")
    return result


def _optional_positive(value: object, label: str) -> float | None:
    return None if value is None else _positive(value, label)


def _optional_nonnegative(value: object, label: str) -> float | None:
    return None if value is None else _nonnegative(value, label)


def _fraction(value: object, label: str) -> float:
    result = _nonnegative(value, label)
    if result > 1.0:
        raise SystemConfigError(f"{label} must be at most 1.")
    return result


def _tuple_value(value: object, label: str) -> tuple[Any, ...]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        raise SystemConfigError(f"{label} must be an ordered sequence.")
    return tuple(value)


def _pair(value: object, label: str) -> tuple[float, float]:
    items = _tuple_value(value, label)
    if len(items) != 2:
        raise SystemConfigError(f"{label} must contain two values.")
    return (_finite(items[0], f"{label}[0]"), _finite(items[1], f"{label}[1]"))


def _positive_tuple(value: object, label: str) -> tuple[float, ...]:
    items = _tuple_value(value, label)
    if not items:
        raise SystemConfigError(f"{label} must not be empty.")
    return tuple(_positive(item, f"{label}[{index}]") for index, item in enumerate(items))


def _indices(value: object, label: str) -> tuple[int, ...]:
    items = _tuple_value(value, label)
    result = tuple(_integer(item, f"{label}[{index}]", minimum=0) for index, item in enumerate(items))
    if len(result) != len(set(result)):
        raise SystemConfigError(f"{label} must not contain duplicates.")
    return result


__all__ = (
    "PROFILE_SCHEMA_NAME",
    "PROFILE_SCHEMA_VERSION",
    "SUPPORTED_PROFILE_SCHEMA_VERSIONS",
    "DetectorPhysicsConfig",
    "SystemConfigError",
    "ProfileProvenance",
    "AtmosphereLayerConfig",
    "AtmosphereConfig",
    "DetectorSystemConfig",
    "WfsConfig",
    "DmSystemConfig",
    "CalibrationConfig",
    "ReconstructorConfig",
    "CommandProjectorConfig",
    "ScalablePathConfig",
    "ControllerConfig",
    "ScienceConfig",
    "RandomSeedConfig",
    "SystemConfig",
    "available_system_profiles",
    "load_system_profile",
    "system_config_from_mapping",
    "system_config_to_mapping",
)
