"""Contracts for installed, explicitly versioned SCAO system profiles."""

from __future__ import annotations

import copy
from dataclasses import FrozenInstanceError, replace
from importlib.resources import files
import inspect
import json
import math
from pathlib import Path

import pytest

from shwfs_ao.core.provenance import Provenance
from shwfs_ao.io import configs
from shwfs_ao.io.configs import (
    PROFILE_SCHEMA_NAME,
    PROFILE_SCHEMA_VERSION,
    AtmosphereConfig,
    CalibrationConfig,
    CommandProjectorConfig,
    ControllerConfig,
    DetectorSystemConfig,
    DmSystemConfig,
    ProfileProvenance,
    RandomSeedConfig,
    ReconstructorConfig,
    ScienceConfig,
    SystemConfig,
    SystemConfigError,
    WfsConfig,
    available_system_profiles,
    load_system_profile,
    system_config_from_mapping,
    system_config_to_mapping,
)


# Every published profile version stays packaged and loadable: a result
# labelled with a v1 profile must remain exactly reproducible after the v2
# review, so v2 supersedes v1 as the recommended profile without retiring it.
EXPECTED_PROFILES = (
    ("fast_2m_detector", 1),
    ("fast_2m_detector", 2),
    ("fast_2m_detector", 3),
    ("fast_2m_detector", 4),
    ("portfolio_2m_detector", 1),
    ("portfolio_2m_detector", 2),
    ("portfolio_2m_detector", 3),
    ("portfolio_2m_detector", 4),
    ("research_2m_detector", 1),
    ("research_2m_detector", 2),
    ("research_2m_detector", 3),
    ("high_order_10m_geometric", 1),
    ("high_order_10m_geometric", 2),
    ("high_order_10m_geometric", 3),
    ("high_order_10m_hcipy", 1),
    ("high_order_10m_hcipy", 2),
    ("high_order_10m_hcipy", 3),
    ("eso_turbulence_2m_detector", 1),
    ("eso_scao_smoke_5m_software", 1),
    ("eso_scao_medium_12m_derived", 1),
    ("eso_scao_medium_12m_weak_gate", 1),
    ("eso_drm_42m_scao_derived", 1),
    ("eso_scao_smoke_5m_software", 2),
    ("eso_scao_medium_12m_derived", 2),
    ("eso_scao_medium_12m_weak_gate", 2),
    ("eso_drm_42m_scao_derived", 2),
    ("det_ccd_2m_synthetic", 1),
    ("det_emccd_2m_synthetic", 1),
    ("det_cmos_2m_synthetic", 1),
    ("det_emccd_2m_plane_synthetic", 1),
    ("det_emccd_12m_medium_derived", 1),
    ("det_ccd_42m_r3band_derived", 1),
    ("det_emccd_12m_medium_derived", 2),
)
CURRENT_2M_PROFILES = (
    ("fast_2m_detector", 2),
    ("portfolio_2m_detector", 2),
    ("research_2m_detector", 2),
)


def test_required_profiles_are_explicit_versions_and_load_outside_checkout(
    tmp_path, monkeypatch
) -> None:
    monkeypatch.chdir(tmp_path)
    assert available_system_profiles() == EXPECTED_PROFILES
    assert inspect.signature(load_system_profile).parameters["version"].default is inspect.Parameter.empty

    for name, version in EXPECTED_PROFILES:
        config = load_system_profile(name, version)
        assert isinstance(config, SystemConfig)
        assert config.profile.profile_id == f"{name}@{version}"
        assert isinstance(config.profile.provenance, Provenance)
        assert config.profile.provenance.source_id == (
            f"shwfs_ao.system_profile.{name}.v{version}"
        )
        assert len(config.config_hash) == 64
        assert all(len(value) == 64 for value in config.component_config_hashes.values())


def test_profile_loader_has_no_latest_alias() -> None:
    with pytest.raises(TypeError):
        load_system_profile("fast_2m_detector")  # type: ignore[call-arg]
    # A never-published version is unknown: there is no implicit "latest" and no
    # silent fall-through to an adjacent version in either direction.
    with pytest.raises(SystemConfigError, match="unknown system profile"):
        load_system_profile("high_order_10m_hcipy", 4)
    with pytest.raises(SystemConfigError, match="unknown system profile"):
        load_system_profile("fast_2m_geometric", 2)


def test_v1_profiles_stay_loadable_beside_their_v2_successors() -> None:
    """A published profile version stays reproducible after it is superseded.

    Each v1 profile keeps its own identity (``…@1``, its own config hash) while
    describing the same physics as its v2 successor: the v2 review made
    ``photon_allocation`` explicit at the value v1 already ran with, so the two
    hold equal component *values* throughout.

    Their published component *identities* still differ in one entry.  The
    nested WFS hash is taken from the ``WfsConfig`` dataclass, whose field set
    schema v2 extended, so a v1 record's ``"wfs"`` identity is the digest of the
    twelve-field shape it was published under and a v2 record's is the digest of
    the thirteen-field one.  Keeping them equal would mean moving one of the
    two, and the published one is not ours to move.  Equal physics with distinct
    published identities is the correct outcome, and it is asserted both ways
    below.
    """

    for name, _ in CURRENT_2M_PROFILES + (
        ("high_order_10m_geometric", 2),
        ("high_order_10m_hcipy", 2),
    ):
        v1 = load_system_profile(name, 1)
        v2 = load_system_profile(name, 2)

        assert v1.profile.profile_id == f"{name}@1"
        assert v1.profile.provenance.source_id == f"shwfs_ao.system_profile.{name}.v1"
        # v1 predates the explicit field and takes the allocation it was
        # reviewed and published under, not a silently different one.
        assert v1.wfs.photon_allocation == v2.wfs.photon_allocation == "throughput_scaled"

        # Same physics: every component compares equal as a value, including
        # the WFS block, so nothing about the sensing policy changed at v2.
        assert v1.wfs == v2.wfs
        assert (v1.atmosphere, v1.detector, v1.dm, v1.controller) == (
            v2.atmosphere,
            v2.detector,
            v2.dm,
            v2.controller,
        )

        physics = dict(v1.component_config_hashes)
        successor = dict(v2.component_config_hashes)
        assert physics.pop("profile") != successor.pop("profile")
        # The WFS entry is the one identity the schema change moved, and it is
        # pinned on both sides by test_every_packaged_nested_wfs_identity_is_pinned.
        assert physics.pop("wfs") != successor.pop("wfs")
        assert physics == successor
        # Distinct published identities never collide.
        assert v1.config_hash != v2.config_hash

        # A v1 profile re-serializes under its *own* record schema and parses
        # back equal, still identifying itself as version 1.  Serializing it
        # under the current schema instead would move a published config_hash.
        record = system_config_to_mapping(v1)
        assert record["schema_version"] == 1
        assert record["profile_version"] == 1
        assert "photon_allocation" not in record["config"]["wfs"]
        assert system_config_from_mapping(record) == v1

        # Likewise a v2 profile keeps its own schema, which predates
        # clip_negative_pixels, rather than the current one.
        current = system_config_to_mapping(v2)
        assert current["schema_version"] == 2
        assert current["config"]["wfs"]["photon_allocation"] == "throughput_scaled"
        assert "clip_negative_pixels" not in current["config"]["wfs"]
        assert system_config_from_mapping(current) == v2


def test_canonical_serialization_reproduces_the_packaged_record() -> None:
    """The hashing basis is the packaged record itself, not a re-rendering.

    ``config_hash`` hashes the canonical serialization, so the two must be the
    same document: if serialization ever diverged from the reviewed file on
    disk — a schema version, a field set, a value — the identity every published
    result cites would silently describe something nobody reviewed.
    """

    resource_root = files("shwfs_ao.resources").joinpath("synthetic_presets")
    for name, version in EXPECTED_PROFILES:
        packaged = json.loads(
            resource_root.joinpath(f"{name}.v{version}.json").read_text(encoding="utf-8")
        )
        assert system_config_to_mapping(load_system_profile(name, version)) == packaged


def test_each_record_schema_version_has_an_exact_field_set() -> None:
    """Neither schema version may borrow the other's WFS field set."""

    v1_record = copy.deepcopy(system_config_to_mapping(load_system_profile("fast_2m_detector", 1)))
    assert v1_record["schema_version"] == 1
    # A v1 record carrying the v2 field is neither: it is rejected, not upgraded.
    v1_record["config"]["wfs"]["photon_allocation"] = "throughput_scaled"
    with pytest.raises(SystemConfigError, match="unknown=\\['photon_allocation'\\]"):
        system_config_from_mapping(v1_record)

    del v1_record["config"]["wfs"]["photon_allocation"]
    parsed = system_config_from_mapping(v1_record)
    assert parsed.wfs.photon_allocation == "throughput_scaled"
    assert parsed.record_schema_version == 1
    # What a v1 record's omission resolves to and what a v1 record is allowed to
    # hold are the same value; if they ever diverge, a v1 profile would load as
    # something its own schema forbids.
    assert (
        WfsConfig.__dataclass_fields__["photon_allocation"].default
        == configs._V1_PHOTON_ALLOCATION
        == parsed.wfs.photon_allocation
    )

    # A v2 record omitting the field is equally refused: v2 never defaults it.
    v2_record = copy.deepcopy(system_config_to_mapping(load_system_profile("fast_2m_detector", 2)))
    del v2_record["config"]["wfs"]["photon_allocation"]
    with pytest.raises(SystemConfigError, match="missing=\\['photon_allocation'\\]"):
        system_config_from_mapping(v2_record)

    # Schema v3 adds clip_negative_pixels on the same terms: a v2 record may
    # not carry it, and a v3 record may not omit it.
    v2_record = copy.deepcopy(system_config_to_mapping(load_system_profile("fast_2m_detector", 2)))
    v2_record["config"]["wfs"]["clip_negative_pixels"] = True
    with pytest.raises(SystemConfigError, match="unknown=\\['clip_negative_pixels'\\]"):
        system_config_from_mapping(v2_record)
    v3_record = copy.deepcopy(v2_record)
    v3_record["schema_version"] = 3
    assert system_config_from_mapping(v3_record).record_schema_version == 3
    del v3_record["config"]["wfs"]["clip_negative_pixels"]
    with pytest.raises(SystemConfigError, match="missing=\\['clip_negative_pixels'\\]"):
        system_config_from_mapping(v3_record)
    assert (
        WfsConfig.__dataclass_fields__["clip_negative_pixels"].default
        is configs._PRE_V3_CLIP_NEGATIVE_PIXELS
        is load_system_profile("fast_2m_detector", 2).wfs.clip_negative_pixels
    )

    # An unsupported record schema version is refused with the supported set.
    v1_record["schema_version"] = PROFILE_SCHEMA_VERSION + 1
    with pytest.raises(SystemConfigError, match="unsupported profile schema_version"):
        system_config_from_mapping(v1_record)


def test_a_configuration_cannot_claim_a_schema_that_cannot_express_it() -> None:
    """A record schema is a claim about expressibility, not a label.

    Schema v1 has no ``wfs.photon_allocation`` field, so a configuration
    carrying any other allocation is not a v1 configuration.  Serializing it as
    one would drop the value; serializing it as v2 instead would move the
    published ``@1`` identity.  Both are wrong, so the pairing is refused where
    it is made.
    """

    v1 = load_system_profile("fast_2m_detector", 1)
    with pytest.raises(SystemConfigError, match="cannot express"):
        replace(v1, wfs=replace(v1.wfs, photon_allocation="unit_sum"))

    # The same physics under the schema that *can* state it is accepted, and
    # keeps the v1 profile's identity from being reused for it.
    v2 = load_system_profile("fast_2m_detector", 2)
    modified = replace(v2, wfs=replace(v2.wfs, photon_allocation="unit_sum"))
    assert modified.record_schema_version == 2
    assert modified.config_hash != v2.config_hash

    # Keeping negative pixels is likewise inexpressible before schema v3, so
    # the configuration has to move to the current schema to state it.
    with pytest.raises(SystemConfigError, match="cannot express"):
        replace(v2, wfs=replace(v2.wfs, clip_negative_pixels=False))
    with pytest.raises(SystemConfigError, match="cannot express"):
        replace(v1, wfs=replace(v1.wfs, clip_negative_pixels=False))
    # Schema 6 can state it for this even-window sensor; schema 7 would also
    # require a window symmetric about the optical axis.
    kept = replace(
        v2,
        wfs=replace(v2.wfs, clip_negative_pixels=False),
        record_schema_version=6,
    )
    assert kept.config_hash != v2.config_hash

    with pytest.raises(SystemConfigError, match="unsupported profile schema_version"):
        replace(v1, record_schema_version=PROFILE_SCHEMA_VERSION + 1)
    # ``True`` is not a schema version, however conveniently it compares to 1.
    with pytest.raises(SystemConfigError, match="record_schema_version must be an integer"):
        replace(v1, record_schema_version=True)


def test_a_schema_v1_record_cannot_claim_a_later_profile_identity() -> None:
    """The two version axes are independent, but not every pairing is coherent.

    Schema v1 omits ``wfs.photon_allocation``, so a record claiming a profile
    version from the v2 review would present a *defaulted* allocation as the
    reviewed explicit one — the ambiguity schema v2 exists to remove, wearing
    the identity that says it was removed.
    """

    record = copy.deepcopy(
        system_config_to_mapping(load_system_profile("fast_2m_detector", 1))
    )
    assert record["schema_version"] == 1
    assert system_config_from_mapping(record).profile.profile_id == "fast_2m_detector@1"

    record["profile_version"] = 2
    record["provenance"]["source_id"] = "shwfs_ao.system_profile.fast_2m_detector.v2"
    with pytest.raises(
        SystemConfigError, match="cannot be recorded under schema version 1"
    ):
        system_config_from_mapping(record)

    # The converse pairing — a later record schema carrying a version-1 profile
    # — stays legal: a future schema may well be introduced while an existing
    # profile version is still current.
    upgraded = copy.deepcopy(
        system_config_to_mapping(load_system_profile("fast_2m_detector", 2))
    )
    upgraded["profile_version"] = 1
    upgraded["provenance"]["source_id"] = "shwfs_ao.system_profile.fast_2m_detector.v1"
    parsed = system_config_from_mapping(upgraded)
    assert (parsed.record_schema_version, parsed.profile.profile_version) == (2, 1)


def test_every_packaged_profile_identity_is_pinned() -> None:
    """A profile's identity must not move without being noticed.

    ``config_hash`` is the hash of the canonical serialization, so it covers
    more than the physics: ``baseline_rationale``, the provenance note, and the
    record's own ``schema_version`` are all in it.  An edit to a profile's
    *prose* therefore relabels every result that cites the profile, and these
    hashes are the tripwire for that.

    What must *not* relabel a result is a change made somewhere else entirely.
    Serializing every profile under the newest record schema did exactly that:
    adding schema v2 moved the ``@1`` identities although those five packaged
    records were untouched.  Each profile is now serialized and hashed under its
    own record schema, so the values below are the identities the packaged
    records have always hashed to under their own schema.  (The one genuine move
    in this history was AO-REF-019 rewriting a notebook path *inside* the v1
    records: their content changed, so their identity changed with it — the hash
    doing its job.)  Changing a value below is only ever correct alongside a
    deliberate edit to the corresponding packaged record.
    """

    expected = {
        ("fast_2m_detector", 1): "5702e29007fdfd93d4dbd99328ae7097fd5ad49087388bf3aef4011f49cfec21",
        ("fast_2m_detector", 2): "7f225305b5d6e1e1b56ceff73cad945856c13a2b2c4f9d81b725a287d090626b",
        ("portfolio_2m_detector", 1): "435736e01c720243453e962ef9431287ad05653aa55d5cb048be3311b7e958dc",
        ("portfolio_2m_detector", 2): "ff9d43c343dccb9e22364fa04fc69bedeae96be0578cd5d0e3713dd25946b06e",
        ("research_2m_detector", 1): "6efaf8911d27ccb3cced1fa5168ece4ea6c848084146710353f224a107cf4eb3",
        ("research_2m_detector", 2): "38fc980bddaf60543eb46bb3ac48d9b6b0432e3e978922f8369ec7b607932dcc",
        ("high_order_10m_geometric", 1): "8159e6c9a854e142e35b8340753b6f770c643deb3d1e90c98b444140f9d8c92c",
        ("high_order_10m_geometric", 2): "f8b6f9da7b42ab42b4ead3d1e17da385dece3b568c196d5251d261e6ae2a4ad2",
        ("high_order_10m_hcipy", 1): "a280a9fa5ceb7d282155b4eb37c81c59f22d5dc9dc459865d583f2a3a8b96a54",
        ("high_order_10m_hcipy", 2): "50a1f9ea0a2abb4a07c7e9a151f76d366e64369f99df7f61c894217c2dd80d4a",
        ("fast_2m_detector", 3): "e8a535fab4577b145115102da6aa8b57557a316d23d37e04e251ba67f7143c35",
        ("portfolio_2m_detector", 3): "001b934eefe20e069702811194f1e78193362ead31a6c218340e2cd54fa3f0f6",
        ("research_2m_detector", 3): "441b106f0eebc1574c4fcc62771087ca0d77e956cdacd25b86d9d44a5032b8dd",
        ("high_order_10m_geometric", 3): "4a7d80b09c861a78f45f5a3c472f63d1bff619bcaa891050b95487c6a8f9f0ca",
        ("high_order_10m_hcipy", 3): "bc73f30b8d37a1dcc5603f8d2007d9e69daf02e54ced8898eef53afb7153e65c",
        ("fast_2m_detector", 4): "8c2c96a97b464fee1cd26d3eecd665f31d0df4b4a036198c6a03d8cd4b898f46",
        ("portfolio_2m_detector", 4): "52463b37fdba955c84faa639278a569234b4692f0bf3a5cc3e54a4c9693f8e13",
        ("eso_turbulence_2m_detector", 1): "f6858605a03e5b946f00ba501c72b657a07893d7c3f410e8455d3cbfedb19157",
        # Schema-v5 ESO-derived SCAO benchmark tiers: new identities, added
        # without moving any entry above.
        ("eso_scao_smoke_5m_software", 1): "cad92b4db22b3050c041bc2bf30e3ecd6565034e91880666a4b5ee15eeaff48c",
        ("eso_scao_medium_12m_derived", 1): "42efcdad394516440a6bb43233d31c5b6ecc53a9f2b32dfad51af11e280d83da",
        ("eso_scao_medium_12m_weak_gate", 1): "4e10f6a799d697bdebc48c9385ef070a8c0c37f3b6d02bc3ca7002d57f2557a9",
        ("eso_drm_42m_scao_derived", 1): "eeee232387395158293e7fc28de8afc5a5f7370fd645a68ecda6551ab173e25c",
        # Version 2: a 23-pixel detector window symmetric about the axis.
        ("eso_scao_smoke_5m_software", 2): "7a522a8315978b3bba7c1fc785e417de762985328bc38727386ac703caf9385b",
        ("eso_scao_medium_12m_derived", 2): "659afd9993de3d9beb1d6fdc9e821ca7df7f8bcfb1bb41bf372fa445dce0a3f0",
        ("eso_scao_medium_12m_weak_gate", 2): "946b1d96a4cef1eb751ef570d2cdb32015b92fff687527dd80838ff7d0b99bb9",
        ("eso_drm_42m_scao_derived", 2): "c9c64a75e343cc57775b19b97f572d2c104887e1ad9d424f18141e782926a31d",
        # Schema-v7 detector-level families: new identities, added without
        # moving any entry above (scripts/generate_detector_level_profiles.py).
        ("det_ccd_2m_synthetic", 1): "64ba0229a312ae3d8d59cfec16e1941cdd6b182f78d887f46784725a67850f95",
        ("det_emccd_2m_synthetic", 1): "f81460c0ebeaa46663786a8b3dc4d3a16dcd9ec87c256aeb2bbcafab275e4309",
        ("det_cmos_2m_synthetic", 1): "a76a71e92ba55b40e3883d7c855f040dd0dc8cd7b8676924dad8cd03935152ee",
        ("det_emccd_2m_plane_synthetic", 1): "c6e1dc9338d23e8f543737143234fb959d6c7343cbd348037a82efb3d863eb70",
        ("det_emccd_12m_medium_derived", 1): "1c7c3231b00b4512837e8024939d52177636dd8f7ffdb4fbaccabd19f1e48723",
        ("det_ccd_42m_r3band_derived", 1): "1ebaf8f35f977e01e2d65a496cf9d4ea06a5a0bc79362852df97646090db8b4f",
        # Version 2 of the 12 m profile (calibration source, uncertainty gating).
        ("det_emccd_12m_medium_derived", 2): "a1a0ee5efcb9b7fe3c8bd82f01f4f4aebf57a1b864a3e0ad403ba9cbc6c2fc0d",
    }
    observed = {
        key: load_system_profile(*key).config_hash for key in available_system_profiles()
    }
    assert set(observed) == set(expected)
    assert observed == expected


def test_every_packaged_nested_wfs_identity_is_pinned() -> None:
    """The nested WFS hash is published too, and moves under the same rules.

    ``component_config_hashes`` is the public per-component identity: a stored
    result cites the ``"wfs"`` entry to say which sensing policy produced it.
    It is hashed from the ``WfsConfig`` dataclass rather than from the record
    mapping, and :func:`shwfs_ao.core.hashing.canonicalize_for_hash` walks a
    dataclass through its *declared* fields, so adding ``photon_allocation``
    moved the nested identity of the five packaged v1 profiles even though
    ``SystemConfig.config_hash`` was kept stable for them.  The v1 values below
    are the ones those records hashed to before the field existed; the v2 values
    are the current shape.  They differ on purpose, and neither may move without
    a deliberate edit to the corresponding packaged record.
    """

    expected = {
        ("fast_2m_detector", 1): "92c752a0ae71abb97e5894742bdfc319a63090da59d80194b57f19d1a40ae204",
        ("fast_2m_detector", 2): "dbf9dd715cb775abed56a42551734817868c101395339cbac69e6ed4d01add03",
        ("portfolio_2m_detector", 1): "58ec89ed72496cbb7e562efaa88149969c4f1aea57b6ac4956c7f7d93dd81c30",
        ("portfolio_2m_detector", 2): "f44dd42a39c0f67318484e3d01b3b43195f379719be65d0c491a4e31a875eb0e",
        ("research_2m_detector", 1): "84448107529e71309fdef7a41db7663d2e62c3996a1ab27c89e5259ff42b273d",
        ("research_2m_detector", 2): "241f18d74988683fab9b4e8d748a86d11e5482bc6020d338a0d66b24c0b6c469",
        ("high_order_10m_geometric", 1): "d8b7d58d7b898624bd64d8151d2203959d8399f309d14e72a738d265dd7d9ce5",
        ("high_order_10m_geometric", 2): "0dca580f4af5fccdf3ba0126a697f1549fd11753c93c97d121faa148aa72584a",
        ("high_order_10m_hcipy", 1): "5f83323a842d7f73f04b02aab3e12ed95cd315bdbed4496c2e9f0d666982e48b",
        ("high_order_10m_hcipy", 2): "45b4f2e0544cdab27e89ef1e88caed8b86c9012270cdfd1e1a7e4a45e64b6078",
        # v3 changes the atmosphere and the controller, never the WFS policy,
        # so each v3 nested WFS identity is deliberately its v2 value.
        ("fast_2m_detector", 3): "dbf9dd715cb775abed56a42551734817868c101395339cbac69e6ed4d01add03",
        ("portfolio_2m_detector", 3): "f44dd42a39c0f67318484e3d01b3b43195f379719be65d0c491a4e31a875eb0e",
        ("research_2m_detector", 3): "241f18d74988683fab9b4e8d748a86d11e5482bc6020d338a0d66b24c0b6c469",
        ("high_order_10m_geometric", 3): "0dca580f4af5fccdf3ba0126a697f1549fd11753c93c97d121faa148aa72584a",
        ("high_order_10m_hcipy", 3): "45b4f2e0544cdab27e89ef1e88caed8b86c9012270cdfd1e1a7e4a45e64b6078",
        # v4 widens the fast and portfolio detector windows, so their WFS
        # identities move.
        ("fast_2m_detector", 4): "beec50d4ead5615c7ff5d19c71b26ffbe07540eafdcb991e0422fdf1010f34b6",
        ("portfolio_2m_detector", 4): "cbe410044085adb9dc0d8b2c5535a36c54ce6e01f9b7b352d4ddf94ea49274e9",
        # The ESO-turbulence profile keeps portfolio_2m_detector@4's WFS, but
        # as a schema-v4 record it hashes the current WfsConfig shape (with
        # clip_negative_pixels) rather than the schema-v2 stand-in.
        ("eso_turbulence_2m_detector", 1): "0df31b2c43b7cfa8915f81e75fb8448bd5e9bbd316747f841de8c45c40f66979",
        # The four ESO SCAO benchmark tiers share one WFS policy.
        ("eso_scao_smoke_5m_software", 1): "a1d51021742aee68894e73cfe203b00f9d508a9bc5af4ac161b2ce8ae7cbc175",
        ("eso_scao_medium_12m_derived", 1): "a1d51021742aee68894e73cfe203b00f9d508a9bc5af4ac161b2ce8ae7cbc175",
        ("eso_scao_medium_12m_weak_gate", 1): "a1d51021742aee68894e73cfe203b00f9d508a9bc5af4ac161b2ce8ae7cbc175",
        ("eso_drm_42m_scao_derived", 1): "a1d51021742aee68894e73cfe203b00f9d508a9bc5af4ac161b2ce8ae7cbc175",
        # Version 2 moves exactly the WFS identity (the detector window).
        ("eso_scao_smoke_5m_software", 2): "f52f89c98e2d44bcbe0706a1fc29c2aab4da7b927c5747db746919d484d8809d",
        ("eso_scao_medium_12m_derived", 2): "f52f89c98e2d44bcbe0706a1fc29c2aab4da7b927c5747db746919d484d8809d",
        ("eso_scao_medium_12m_weak_gate", 2): "f52f89c98e2d44bcbe0706a1fc29c2aab4da7b927c5747db746919d484d8809d",
        ("eso_drm_42m_scao_derived", 2): "f52f89c98e2d44bcbe0706a1fc29c2aab4da7b927c5747db746919d484d8809d",
        # Schema-v7 detector-level families (odd centroid windows, no
        # clipping of negative pixels; the detector physics is its own block).
        ("det_ccd_2m_synthetic", 1): "ca6f5fb3f50bd573e81ae46610ff432c8db4f6649166175e37ce48914a0f20a5",
        ("det_emccd_2m_synthetic", 1): "ca6f5fb3f50bd573e81ae46610ff432c8db4f6649166175e37ce48914a0f20a5",
        ("det_cmos_2m_synthetic", 1): "ca6f5fb3f50bd573e81ae46610ff432c8db4f6649166175e37ce48914a0f20a5",
        ("det_emccd_2m_plane_synthetic", 1): "b7a1276266977b16352f2f81d1002f91a71fab8321989bb6b658ffab93a6b770",
        ("det_emccd_12m_medium_derived", 1): "4deb8116b7d99d52dafcae7ce3343809054b877535e8735bcd5bf66c9c9af548",
        ("det_ccd_42m_r3band_derived", 1): "4deb8116b7d99d52dafcae7ce3343809054b877535e8735bcd5bf66c9c9af548",
        ("det_emccd_12m_medium_derived", 2): "3291d15ad27d43c266b8078f54ff45d1fe0bf3e137d797564e42f2d455214e80",
    }
    observed = {
        key: load_system_profile(*key).component_config_hashes["wfs"]
        for key in available_system_profiles()
    }
    assert set(observed) == set(expected)
    assert observed == expected


def test_fast_2m_detector_v4_is_v3_with_only_a_wider_detector_window() -> None:
    """@3 stays frozen as published; @4 changes exactly one reviewed value.

    The 18 px window of @3 cannot hold its own unpinned open-loop spots, so
    window clipping rejects a lenslet in every frame and the loop never closes
    (``tests/experiments/test_scao_profile_closure.py``).  Fixing that in place
    would relabel every result that cites @3, so the wider window is a new
    version under otherwise identical physics.
    """

    v3 = load_system_profile("fast_2m_detector", 3)
    v4 = load_system_profile("fast_2m_detector", 4)

    assert (v3.wfs.detector_window_px, v4.wfs.detector_window_px) == (18, 24)
    assert replace(v4.wfs, detector_window_px=18) == v3.wfs
    assert replace(v4, profile=v3.profile, wfs=v3.wfs) == v3
    assert v4.observing_conditions_hash == v3.observing_conditions_hash
    assert {
        key
        for key, value in v4.component_config_hashes.items()
        if value != v3.component_config_hashes[key]
    } == {"profile", "wfs"}


def test_a_bare_wfs_config_hashes_under_the_current_record_schema() -> None:
    """``WfsConfig.config_hash`` answers for the shape the class actually has.

    The schema-aware variant exists so a *record* keeps the identity it was
    published with, not so a ``WfsConfig`` can hide a field.  A bare block
    therefore hashes under the newest schema, which is the same convention
    ``SystemConfig.record_schema_version`` defaults to, and two blocks that
    differ only in ``photon_allocation`` must never share a digest.
    """

    v1 = load_system_profile("fast_2m_detector", 1)
    v2 = load_system_profile("fast_2m_detector", 2)

    # Identical physics, so the bare-object identity is identical: only the
    # record schema each one belongs to distinguishes their nested hashes.
    # Both records predate the current schema's clip_negative_pixels field, so
    # each keeps its own published digest instead of the bare one.
    assert v1.wfs == v2.wfs
    assert v1.wfs.config_hash == v2.wfs.config_hash
    assert v2.wfs.config_hash != v2.component_config_hashes["wfs"]
    assert v2.component_config_hashes["wfs"] == v2.wfs.config_hash_for_record_schema(2)
    assert v1.wfs.config_hash != v1.component_config_hashes["wfs"]
    assert v1.wfs.config_hash == v1.wfs.config_hash_for_record_schema(
        PROFILE_SCHEMA_VERSION
    )

    # The v1 payload drops the field, so hashing a non-default allocation under
    # schema 1 would publish an identity that silently omits a real change to
    # the WFS photon budget.  That is refused rather than approximated.
    unit_sum = replace(v2.wfs, photon_allocation="unit_sum")
    assert unit_sum.config_hash != v2.wfs.config_hash
    with pytest.raises(SystemConfigError, match="cannot express"):
        unit_sum.config_hash_for_record_schema(1)

    # Keeping negative pixels changes the bare identity and has no field in
    # either earlier schema, so it is refused there too.
    kept = replace(v2.wfs, clip_negative_pixels=False)
    assert kept.config_hash != v2.wfs.config_hash
    for older in (1, 2):
        with pytest.raises(SystemConfigError, match="cannot express"):
            kept.config_hash_for_record_schema(older)

    # An unknown schema is not silently treated as the newest one.
    with pytest.raises(SystemConfigError, match="unsupported profile schema_version"):
        v2.wfs.config_hash_for_record_schema(PROFILE_SCHEMA_VERSION + 1)
    with pytest.raises(SystemConfigError, match="record_schema_version must be an integer"):
        v2.wfs.config_hash_for_record_schema(True)  # type: ignore[arg-type]


def test_profile_round_trip_is_exact_and_deterministic() -> None:
    first = load_system_profile("fast_2m_detector", 2)
    second = load_system_profile("fast_2m_detector", 2)
    record = system_config_to_mapping(first)

    assert record["schema_name"] == PROFILE_SCHEMA_NAME
    assert record["schema_version"] == first.record_schema_version == 2
    assert system_config_from_mapping(record) == first == second
    assert first.config_hash == second.config_hash
    assert dict(first.component_config_hashes) == dict(second.component_config_hashes)

    with pytest.raises(FrozenInstanceError):
        first.pupil_pixels = 64  # type: ignore[misc]


def test_wfs_negative_pixel_clipping_is_a_schema_v3_field() -> None:
    """Schema v3 records state whether negative pixels are clipped.

    A configuration built in code belongs to the current schema, so it
    serializes the field, round-trips it, and hashes a change of it, while
    every published record keeps the identity it was published with.
    """

    assert PROFILE_SCHEMA_VERSION >= 3
    v2 = load_system_profile("fast_2m_detector", 2)
    current = replace(v2, record_schema_version=3)
    record = system_config_to_mapping(current)
    assert record["schema_version"] == 3
    assert record["config"]["wfs"]["clip_negative_pixels"] is True
    assert system_config_from_mapping(record) == current

    kept = replace(current, wfs=replace(current.wfs, clip_negative_pixels=False))
    kept_record = system_config_to_mapping(kept)
    assert kept_record["config"]["wfs"]["clip_negative_pixels"] is False
    assert system_config_from_mapping(kept_record) == kept
    assert kept.config_hash != current.config_hash
    assert kept.component_config_hashes["wfs"] != current.component_config_hashes["wfs"]
    with pytest.raises(SystemConfigError, match="clip_negative_pixels must be a boolean"):
        replace(current.wfs, clip_negative_pixels=0)


def test_wfs_lenslet_axis_is_a_schema_v6_field_for_hcipy_only() -> None:
    """Schema v6 records state where the HCIPy lens vertices sit.

    Every earlier record keeps the cell-centred vertices it was published
    with.  A configuration may opt into block-centred vertices only under
    schema v6 and only for the HCIPy detector-level sensor, the one sensor
    that places lens vertices (AO-REF-016A).
    """

    assert PROFILE_SCHEMA_VERSION >= 6
    assert (
        WfsConfig.__dataclass_fields__["lenslet_axis"].default
        == configs._PRE_V6_LENSLET_AXIS
        == "geometry_cell_center"
    )
    for key in available_system_profiles():
        assert load_system_profile(*key).wfs.lenslet_axis == "geometry_cell_center"

    hcipy_v3 = load_system_profile("high_order_10m_hcipy", 3)
    current = replace(hcipy_v3, record_schema_version=6)
    record = system_config_to_mapping(current)
    assert record["config"]["wfs"]["lenslet_axis"] == "geometry_cell_center"
    assert system_config_from_mapping(record) == current

    block = replace(
        current, wfs=replace(current.wfs, lenslet_axis="pixel_block_center")
    )
    block_record = system_config_to_mapping(block)
    assert block_record["config"]["wfs"]["lenslet_axis"] == "pixel_block_center"
    assert system_config_from_mapping(block_record) == block
    assert block.config_hash != current.config_hash
    assert (
        block.component_config_hashes["wfs"]
        != current.component_config_hashes["wfs"]
    )
    assert block.observing_conditions_hash == hcipy_v3.observing_conditions_hash

    # A v5 record may not carry the field, and a v6 record may not omit it.
    v5_record = copy.deepcopy(record)
    v5_record["schema_version"] = 5
    with pytest.raises(SystemConfigError, match="unknown=\\['lenslet_axis'\\]"):
        system_config_from_mapping(v5_record)
    del v5_record["config"]["wfs"]["lenslet_axis"]
    assert system_config_from_mapping(v5_record).record_schema_version == 5
    del record["config"]["wfs"]["lenslet_axis"]
    with pytest.raises(SystemConfigError, match="missing=\\['lenslet_axis'\\]"):
        system_config_from_mapping(record)

    # No earlier schema can express block-centred vertices, as a record or
    # as a nested hash.
    for older in range(1, 6):
        with pytest.raises(SystemConfigError, match="cannot express"):
            block.wfs.config_hash_for_record_schema(older)
    with pytest.raises(SystemConfigError, match="cannot express"):
        replace(hcipy_v3, wfs=replace(hcipy_v3.wfs, lenslet_axis="pixel_block_center"))

    # Only the HCIPy detector-level sensor consults the field.
    native = replace(
        load_system_profile("portfolio_2m_detector", 4), record_schema_version=6
    )
    with pytest.raises(SystemConfigError, match="HCIPy detector-level sensor only"):
        replace(native, wfs=replace(native.wfs, lenslet_axis="pixel_block_center"))
    with pytest.raises(SystemConfigError, match="lenslet_axis"):
        replace(current.wfs, lenslet_axis="nearest_pixel")  # type: ignore[arg-type]


def test_draft_high_order_10m_hcipy_v4_is_v3_with_only_block_centred_axes() -> None:
    """The unpublished @4 draft changes exactly the HCIPy lens vertices.

    The draft lives in ``docs/refactor/drafts`` and is not registered, so it
    has no published identity yet: ``load_system_profile`` still refuses
    ``high_order_10m_hcipy@4``.  Publishing it means moving the file into
    ``synthetic_presets``, registering it, and pinning its two hashes here,
    after the closed-loop confirmation AO-REF-016A lists as not run.
    """

    draft_path = (
        Path(__file__).resolve().parents[2]
        / "docs"
        / "refactor"
        / "drafts"
        / "high_order_10m_hcipy.v4.json"
    )
    if not draft_path.is_file():
        pytest.skip("the @4 draft is a source-checkout document, not a package resource")
    draft_record = json.loads(draft_path.read_text(encoding="utf-8"))
    draft = system_config_from_mapping(draft_record)
    assert system_config_to_mapping(draft) == draft_record
    assert draft.profile.profile_id == "high_order_10m_hcipy@4"
    assert draft.record_schema_version == 6
    assert ("high_order_10m_hcipy", 4) not in available_system_profiles()

    v3 = load_system_profile("high_order_10m_hcipy", 3)
    assert draft.wfs.lenslet_axis == "pixel_block_center"
    assert replace(draft.wfs, lenslet_axis="geometry_cell_center") == v3.wfs
    assert (
        replace(
            draft,
            profile=v3.profile,
            wfs=v3.wfs,
            record_schema_version=v3.record_schema_version,
        )
        == v3
    )
    assert draft.observing_conditions_hash == v3.observing_conditions_hash
    assert {
        key
        for key, value in draft.component_config_hashes.items()
        if value != v3.component_config_hashes.get(key)
    } == {"profile", "wfs", "scalable"}
    assert draft.component_config_hashes["scalable"] == configs.component_config_hash(
        "scao.scalable_path_config", None
    )
    assert {
        key
        for key in draft_record["provenance"]
        if draft_record["provenance"][key] != system_config_to_mapping(v3)["provenance"][key]
    } == {"note", "source_id", "references"}


def test_wfs_photon_allocation_is_required_serialized_and_hashed() -> None:
    profile = load_system_profile("fast_2m_detector", 2)
    # The reviewed v2 profiles record the allocation policy explicitly.
    assert profile.wfs.photon_allocation == "throughput_scaled"

    # The choice is a serialized, round-tripping part of the WFS block.
    record = system_config_to_mapping(profile)
    assert record["config"]["wfs"]["photon_allocation"] == "throughput_scaled"
    assert system_config_from_mapping(record) == profile

    # Schema v2 requires the field: a record that omits it is rejected rather
    # than silently defaulted, so a profile's identity is never ambiguous.
    missing = copy.deepcopy(record)
    del missing["config"]["wfs"]["photon_allocation"]
    with pytest.raises(SystemConfigError, match="wfs"):
        system_config_from_mapping(missing)

    # Switching the policy is a real configuration change: it round-trips and
    # moves the WFS component hash (which keys the seeded RNG scope).
    unit_sum = replace(
        profile, wfs=replace(profile.wfs, photon_allocation="unit_sum")
    )
    assert unit_sum.wfs.photon_allocation == "unit_sum"
    assert (
        unit_sum.component_config_hashes["wfs"]
        != profile.component_config_hashes["wfs"]
    )
    assert system_config_from_mapping(system_config_to_mapping(unit_sum)) == unit_sum

    # Unknown policies are rejected at construction.
    with pytest.raises(SystemConfigError, match="photon_allocation"):
        replace(profile.wfs, photon_allocation="per_lenslet")  # type: ignore[arg-type]


def test_2m_profiles_change_scale_without_changing_observing_conditions() -> None:
    profiles = [load_system_profile(name, version) for name, version in CURRENT_2M_PROFILES]
    assert [(p.pupil_pixels, p.lenslets_across, p.actuators_across) for p in profiles] == [
        (52, 5, 5),
        (72, 7, 7),
        (96, 9, 9),
    ]
    assert [p.wfs.detector_window_px for p in profiles] == [18, 20, 22]
    assert [p.controller.n_steps for p in profiles] == [12, 18, 30]
    assert len({p.observing_conditions_hash for p in profiles}) == 1
    assert all(p.detector.photons_per_subap_frame == 8000.0 for p in profiles)
    assert all(p.detector.read_noise_e == 1.0 for p in profiles)
    assert all(p.atmosphere.r0_m == profiles[0].atmosphere.r0_m for p in profiles)


def test_portfolio_2m_detector_v4_is_v3_with_only_a_wider_detector_window() -> None:
    """@3 stays frozen as published; @4 changes exactly one reviewed value.

    The 20 px window of @3 leaves no clipping margin under its unpinned
    atmosphere: lenslets clip past the limit, and the
    ``min_valid_fraction=1.0`` reconstructor drops frames in most sampled
    atmosphere realizations (``docs/refactor/AO_REF_011_SCAO.md``).  Widening
    it in place would relabel every result that cites @3, so the 28 px window
    is a new version under otherwise identical physics, and
    ``tests/experiments/test_scao.py`` checks that it reconstructs every frame.
    """

    v3 = load_system_profile("portfolio_2m_detector", 3)
    v4 = load_system_profile("portfolio_2m_detector", 4)
    assert (v3.wfs.detector_window_px, v4.wfs.detector_window_px) == (20, 28)

    v3_record = system_config_to_mapping(v3)
    v4_record = system_config_to_mapping(v4)
    widened = copy.deepcopy(v3_record["config"])
    widened["wfs"]["detector_window_px"] = 28
    assert v4_record["config"] == widened
    # Outside the configuration only the published identity and its account
    # of the change differ: the record schema, the profile name, and the
    # provenance's source class and note are @3's.
    assert {key for key in v3_record if v4_record[key] != v3_record[key]} == {
        "profile_version",
        "baseline_rationale",
        "provenance",
        "config",
    }
    assert {
        key
        for key in v3_record["provenance"]
        if v4_record["provenance"][key] != v3_record["provenance"][key]
    } == {"source_id", "references"}

    assert v4.observing_conditions_hash == v3.observing_conditions_hash
    assert {
        key
        for key, value in v4.component_config_hashes.items()
        if value != v3.component_config_hashes[key]
    } == {"profile", "wfs"}


def test_high_order_profile_matches_notebook_09_extreme_mode_in_si_units() -> None:
    config = load_system_profile("high_order_10m_geometric", 2)
    assert config.backend == "native"
    assert config.wfs_model == "geometric"
    assert config.telescope_diameter_m == 10.0
    assert (config.pupil_pixels, config.lenslets_across, config.actuators_across) == (
        384,
        48,
        49,
    )
    assert config.wfs_wavelength_m == 750.0e-9
    assert config.wfs.min_fill_fraction == 0.45
    assert config.wfs.pad_factor is None
    assert not config.detector.enabled
    assert config.dm.coupling_width_pitch == 0.70
    assert config.dm.actuator_margin_fraction == 0.12
    assert config.controller.n_steps == 160
    assert config.controller.frame_rate_hz == 500.0
    assert config.controller.gain == 0.65
    assert config.reconstructor.rcond == 0.02
    assert config.calibration.amplitude_m == pytest.approx(
        750.0e-9 / (2.0 * math.pi)
    )
    assert config.dm.stroke_limit_opd_m == pytest.approx(
        180.0 * 750.0e-9 / (2.0 * math.pi)
    )


def test_high_order_hcipy_profile_pairs_the_geometric_scale_through_hcipy() -> None:
    config = load_system_profile("high_order_10m_hcipy", 2)
    geometric = load_system_profile("high_order_10m_geometric", 2)

    assert config.backend == "hcipy"
    assert config.wfs_model == "detector_level"
    assert config.atmosphere_model == "hcipy"

    # Same observing target and numerical scale as the geometric profile.
    assert config.telescope_diameter_m == geometric.telescope_diameter_m
    assert (config.pupil_pixels, config.lenslets_across, config.actuators_across) == (
        geometric.pupil_pixels,
        geometric.lenslets_across,
        geometric.actuators_across,
    )
    assert config.wfs_wavelength_m == geometric.wfs_wavelength_m
    assert config.science_wavelengths_m == geometric.science_wavelengths_m
    assert config.atmosphere.r0_m == geometric.atmosphere.r0_m
    assert (
        config.atmosphere.r0_reference_wavelength_m
        == geometric.atmosphere.r0_reference_wavelength_m
    )
    assert config.atmosphere.outer_scale_m == geometric.atmosphere.outer_scale_m
    assert config.atmosphere.wind_m_per_s == geometric.atmosphere.wind_m_per_s
    assert config.dm == geometric.dm
    assert config.calibration == geometric.calibration
    assert config.controller == geometric.controller
    assert config.science == geometric.science
    assert config.random == geometric.random

    # The HCIPy atmosphere adapter has no RMS normalization, so this is the
    # one deliberate observing-condition difference from the geometric pair.
    assert config.atmosphere.normalize_rms is False
    assert config.atmosphere.target_rms_opd_m is None
    assert geometric.atmosphere.normalize_rms is True
    assert (
        config.observing_conditions_hash != geometric.observing_conditions_hash
    )

    # Detector-level sensing on the fixed HCIPy block window with the
    # established cross-backend spot sampling of 4 px per lambda/d.
    assert config.wfs.detector_window_px == (
        config.pupil_pixels // config.lenslets_across
    )
    assert config.wfs.detector_window_px == 8
    assert config.wfs.pad_factor == 4
    assert config.detector.enabled
    assert config.detector.photons_per_subap_frame == 8000.0
    assert config.detector.read_noise_e == 1.0
    assert config.detector.exposure_s == pytest.approx(
        1.0 / config.controller.frame_rate_hz
    )

    # The small block windows legitimately clip strongly displaced open-loop
    # spots, so the validity floor sits below the measured open-loop
    # fraction (0.82-0.84) instead of the geometric profile's 1.0.
    assert config.reconstructor.min_valid_fraction == 0.75
    assert config.wfs.max_window_clipping_fraction == 0.15


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        (lambda record: record.update(extra=True), "fields mismatch"),
        (lambda record: record.update(schema_version=99), "unsupported profile"),
        (
            lambda record: record["config"]["atmosphere"].update(extra=True),
            "fields mismatch",
        ),
        (
            lambda record: record["config"].update(science_wavelengths_m=[1.0e-6, 0.9e-6]),
            "strictly increasing",
        ),
        (
            lambda record: record["provenance"].update(schema_version=1),
            "provenance",
        ),
    ],
)
def test_mapping_parser_rejects_unknown_or_inconsistent_records(mutation, message) -> None:
    record = copy.deepcopy(
        system_config_to_mapping(load_system_profile("fast_2m_detector", 2))
    )
    mutation(record)
    with pytest.raises(SystemConfigError, match=message):
        system_config_from_mapping(record)


def test_profile_identity_and_numerical_content_both_affect_config_hash() -> None:
    original = load_system_profile("fast_2m_detector", 2)
    changed = replace(original, pupil_pixels=54)
    assert changed.config_hash != original.config_hash

    source = original.profile.provenance
    v3_source = replace(
        source,
        source_id="shwfs_ao.system_profile.fast_2m_detector.v3",
    )
    v3_profile = replace(
        original.profile,
        profile_version=3,
        provenance=v3_source,
        baseline_rationale="Reviewed numerical change for a hypothetical v3.",
    )
    versioned = replace(original, profile=v3_profile)
    assert versioned.config_hash != original.config_hash


def test_nested_public_configuration_types_and_source_policies() -> None:
    config = load_system_profile("fast_2m_detector", 2)
    assert isinstance(config.profile, ProfileProvenance)
    assert isinstance(config.atmosphere, AtmosphereConfig)
    assert isinstance(config.detector, DetectorSystemConfig)
    assert isinstance(config.wfs, WfsConfig)
    assert isinstance(config.dm, DmSystemConfig)
    assert isinstance(config.calibration, CalibrationConfig)
    assert isinstance(config.reconstructor, ReconstructorConfig)
    assert isinstance(config.command_projector, CommandProjectorConfig)
    assert isinstance(config.controller, ControllerConfig)
    assert isinstance(config.science, ScienceConfig)
    assert isinstance(config.random, RandomSeedConfig)

    with pytest.raises(SystemConfigError, match="resource calibration requires"):
        replace(config.calibration, source="resource")
    with pytest.raises(SystemConfigError, match="modal projector requires"):
        CommandProjectorConfig(kind="modal", mapping_resource=None)


def test_static_model_has_no_implicit_file_or_generated_profile_lookup() -> None:
    config = load_system_profile("fast_2m_detector", 2)
    static = replace(config, atmosphere_model="static")
    record = system_config_to_mapping(static)
    atmosphere = record["config"]["atmosphere"]
    assert set(atmosphere) == {
        "r0_m",
        "r0_reference_wavelength_m",
        "outer_scale_m",
        "wind_m_per_s",
        "target_rms_opd_m",
        "normalize_rms",
    }
    assert not any("path" in key or "resource" in key for key in atmosphere)


def test_schema_v4_states_atmosphere_layers_and_older_schemas_cannot() -> None:
    """``atmosphere.layers`` is a schema-v4 field with the usual exactness.

    A v4 record must state the list (empty for one layer); a v1-v3 record may
    not carry it; and only ``native_layered`` accepts a non-empty list.
    """

    v2 = load_system_profile("portfolio_2m_detector", 4)
    eso = load_system_profile("eso_turbulence_2m_detector", 1)
    assert (v2.record_schema_version, eso.record_schema_version) == (2, 4)

    v4_record = copy.deepcopy(system_config_to_mapping(eso))
    assert len(v4_record["config"]["atmosphere"]["layers"]) == 10
    del v4_record["config"]["atmosphere"]["layers"]
    with pytest.raises(SystemConfigError, match="missing=\\['layers'\\]"):
        system_config_from_mapping(v4_record)

    v2_record = copy.deepcopy(system_config_to_mapping(v2))
    v2_record["config"]["atmosphere"]["layers"] = []
    with pytest.raises(SystemConfigError, match="unknown=\\['layers'\\]"):
        system_config_from_mapping(v2_record)

    # A single-layer configuration moved to schema v4 states an empty list.
    single_v4 = replace(v2, record_schema_version=4)
    assert system_config_to_mapping(single_v4)["config"]["atmosphere"]["layers"] == []
    assert system_config_from_mapping(system_config_to_mapping(single_v4)) == single_v4

    with pytest.raises(SystemConfigError, match="cannot express atmosphere.layers"):
        replace(eso, record_schema_version=3)
    with pytest.raises(SystemConfigError, match="requires atmosphere.layers"):
        replace(eso, atmosphere_model="native_frozen_flow_v2")
    with pytest.raises(SystemConfigError, match="requires atmosphere.layers"):
        replace(single_v4, atmosphere_model="native_layered")


def test_a_layered_atmosphere_block_is_strictly_validated() -> None:
    atmosphere = load_system_profile("eso_turbulence_2m_detector", 1).atmosphere
    layers = atmosphere.layers

    with pytest.raises(SystemConfigError, match="must sum to 1"):
        replace(atmosphere, layers=layers[:-1])
    with pytest.raises(SystemConfigError, match="wind_m_per_s must be \\[0, 0\\]"):
        replace(atmosphere, wind_m_per_s=(10.0, 0.0))
    with pytest.raises(SystemConfigError, match="absolutely normalized"):
        replace(atmosphere, normalize_rms=True)
    with pytest.raises(SystemConfigError, match="absolutely normalized"):
        replace(atmosphere, target_rms_opd_m=1.0e-7)
    with pytest.raises(SystemConfigError, match="cn2_fraction must be positive"):
        replace(layers[0], cn2_fraction=0.0)
    with pytest.raises(SystemConfigError, match="altitude_m must be non-negative"):
        replace(layers[0], altitude_m=-1.0)
    with pytest.raises(SystemConfigError, match="AtmosphereLayerConfig"):
        replace(atmosphere, layers=({"cn2_fraction": 1.0},))


def test_single_layer_atmosphere_identities_do_not_depend_on_the_layers_field() -> None:
    """Adding ``layers`` moved no published atmosphere or observing identity.

    A single-layer block hashes as its pre-v4 shape under every record schema,
    so the same physics recorded under schema v4 keeps the nested atmosphere
    hash and the observing-conditions hash of its published original.
    """

    published = load_system_profile("portfolio_2m_detector", 4)
    restated = replace(published, record_schema_version=4)

    assert restated.config_hash != published.config_hash
    assert restated.observing_conditions_hash == published.observing_conditions_hash
    assert (
        restated.component_config_hashes["atmosphere"]
        == published.component_config_hashes["atmosphere"]
        == published.atmosphere.config_hash
    )
    eso = load_system_profile("eso_turbulence_2m_detector", 1)
    assert eso.atmosphere.config_hash != published.atmosphere.config_hash
    assert eso.observing_conditions_hash != published.observing_conditions_hash


def test_the_eso_profile_changes_only_the_atmosphere_of_portfolio_v4() -> None:
    portfolio = load_system_profile("portfolio_2m_detector", 4)
    eso = load_system_profile("eso_turbulence_2m_detector", 1)

    assert eso.profile.provenance.source_id == (
        "shwfs_ao.system_profile.eso_turbulence_2m_detector.v1"
    )
    assert eso.atmosphere.r0_m == 0.13
    assert eso.atmosphere.outer_scale_m == 25.0
    assert replace(
        eso,
        atmosphere_model=portfolio.atmosphere_model,
        atmosphere=portfolio.atmosphere,
        profile=portfolio.profile,
        record_schema_version=portfolio.record_schema_version,
    ) == portfolio
