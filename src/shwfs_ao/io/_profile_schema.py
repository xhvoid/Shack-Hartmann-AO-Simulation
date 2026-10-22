"""Record schemas of the serialized SCAO profile: history, field sets, hash shapes.

A packaged profile is a JSON record of one schema version, and the version is
inside the hashed mapping (see :func:`shwfs_ao.io.configs.system_config_to_mapping`).
Every published identity therefore depends on three facts this module owns:

* which fields each record schema version contains (the field sets the codec
  in :mod:`shwfs_ao.io.configs` checks in both directions);
* which value an older record implies for a field it predates (a record of
  that schema can hold no other value); and
* the frozen dataclass shapes under which blocks of earlier schemas hash.
  Each pins ``__hash_schema_id__`` to the name the live class carried when
  those digests were published, so the canonical bytes are the historical
  ones (:func:`shwfs_ao.core.hashing.canonicalize_for_hash`).

Everything here is append-only history.  A new schema version adds its own
field set and, if it changes a hashed block's declared fields, its own frozen
shape; it never edits an existing one.  The live configuration records, their
validation and the codec stay in :mod:`shwfs_ao.io.configs`, which imports
from this leaf module and re-exports the public constants.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal


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
# and exposure sub-samples (docs/refactor/detector_level_development_plan.md).
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


# Field sets of each record schema version, exact in both directions.
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
_RECOVERY_FIELDS = {"rejected_frames_before_decay", "decay_per_rejected_frame", "fallback_min_valid_fraction", "fallback_min_actuator_coverage", "gain_full_valid_fraction"}
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


# Frozen hash shapes of blocks written under earlier record schemas.


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
class _ControllerConfigWithoutRecovery:
    """Hash shape of a ``controller`` block without a recovery policy.

    The same declared fields, order and schema id as before the optional
    policy existed, so records without one keep their identity.
    """

    __hash_schema_id__ = "shwfs_ao.io.configs.ControllerConfig"

    n_steps: int
    gain: float
    leak: float
    latency_frames: int
    frame_rate_hz: float
    include_noise: bool


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
