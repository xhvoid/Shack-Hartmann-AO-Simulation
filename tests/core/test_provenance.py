"""Contracts for the canonical provenance model and its two wire formats."""

from __future__ import annotations

from dataclasses import FrozenInstanceError, fields
import json
from typing import get_args

import pytest

import shwfs_ao.core as core
import shwfs_ao.core.provenance as provenance_module
from shwfs_ao.core.provenance import (
    ALLOWED_SOURCE_CLASSES,
    Provenance,
    SourceClass,
)


SOURCE_CLASSES = {
    "direct_public_data",
    "literature_derived",
    "synthetic_literature_inspired",
    "synthetic_assumed",
    "package_reference",
}


def _complete_provenance() -> Provenance:
    return Provenance(
        "direct_public_data",
        "Direct public calibration record.",
        "calibration-42",
        "https://example.test/calibration/42",
        "2026-07-14T12:34:56Z",
        True,
        ("doi:10.1234/example", "catalog:example-42"),
    )


def test_module_exports_exact_canonical_provenance_api() -> None:
    assert provenance_module.__all__ == (
        "SourceClass",
        "ALLOWED_SOURCE_CLASSES",
        "Provenance",
    )
    assert core.SourceClass is SourceClass
    assert core.ALLOWED_SOURCE_CLASSES is ALLOWED_SOURCE_CLASSES
    assert core.Provenance is Provenance


def test_source_class_literal_and_runtime_taxonomy_have_the_exact_five_values() -> None:
    assert set(get_args(SourceClass)) == SOURCE_CLASSES
    assert type(ALLOWED_SOURCE_CLASSES) is frozenset
    assert ALLOWED_SOURCE_CLASSES == SOURCE_CLASSES


@pytest.mark.parametrize("source_class", sorted(SOURCE_CLASSES))
def test_every_canonical_source_class_is_accepted(source_class: str) -> None:
    provenance = Provenance(source_class, "A non-empty source note.")  # type: ignore[arg-type]

    assert provenance.source_class == source_class


@pytest.mark.parametrize(
    "source_class",
    [None, 3, "", "public_api", "DIRECT_PUBLIC_DATA"],
)
def test_invalid_source_class_is_rejected(source_class: object) -> None:
    with pytest.raises(ValueError, match="source_class|expected one of"):
        Provenance(source_class, "A valid note.")  # type: ignore[arg-type]


@pytest.mark.parametrize("source_note", [None, 3, "", "   \t\n"])
def test_source_note_must_be_a_nonempty_string(source_note: object) -> None:
    with pytest.raises(ValueError, match="source_note.*non-empty"):
        Provenance("synthetic_assumed", source_note)  # type: ignore[arg-type]


def test_constructor_retains_legacy_positional_order_and_adds_references_last() -> None:
    historical = Provenance(
        "package_reference",
        "A packaged baseline.",
        "baseline-v2",
        None,
        "2026-07-14T00:00:00Z",
        False,
    )
    complete = _complete_provenance()

    assert [field.name for field in fields(Provenance)] == [
        "source_class",
        "source_note",
        "source_id",
        "url",
        "access_time",
        "fallback_used",
        "references",
    ]
    assert historical.references == ()
    assert complete.references == (
        "doi:10.1234/example",
        "catalog:example-42",
    )


def test_note_is_a_read_only_alias_without_normalizing_the_source_note() -> None:
    provenance = Provenance("literature_derived", "  Citation as supplied.  ")

    assert provenance.note == provenance.source_note == "  Citation as supplied.  "
    with pytest.raises(FrozenInstanceError):
        provenance.source_note = "changed"  # type: ignore[misc]
    with pytest.raises(FrozenInstanceError):
        provenance.note = "changed"  # type: ignore[misc]


@pytest.mark.parametrize("field_name", ["source_id", "url", "access_time"])
def test_optional_text_fields_reject_non_strings(field_name: str) -> None:
    values = {field_name: 17}

    with pytest.raises(ValueError, match=field_name):
        Provenance("synthetic_assumed", "A source note.", **values)  # type: ignore[arg-type]


@pytest.mark.parametrize("fallback_used", [0, 1, "false", None])
def test_direct_constructor_requires_a_real_boolean(fallback_used: object) -> None:
    with pytest.raises(ValueError, match="fallback_used.*bool"):
        Provenance(
            "synthetic_assumed",
            "A source note.",
            fallback_used=fallback_used,  # type: ignore[arg-type]
        )


@pytest.mark.parametrize(
    "references",
    [
        ["a-reference"],
        "a-reference",
        ("valid", 3),
    ],
)
def test_direct_constructor_requires_a_tuple_of_strings(references: object) -> None:
    with pytest.raises(ValueError, match="references"):
        Provenance(
            "synthetic_assumed",
            "A source note.",
            references=references,  # type: ignore[arg-type]
        )


def test_from_legacy_fields_extracts_all_provenance_and_ignores_enclosing_schema() -> None:
    artifact = {
        "schema_name": "some.other.artifact",
        "schema_version": "0.2",
        "data_kind": "eso_asm_snapshot",
        "source_class": "direct_public_data",
        "source_note": "An existing flat artifact note.",
        "source_id": "ESO-42",
        "url": "https://example.test/eso/42",
        "access_time": "2026-07-14T08:00:00Z",
        "fallback_used": "false",
        "references": ["ESO ASM"],
        "measurements": {"seeing": 0.7},
    }
    original = artifact.copy()

    provenance = Provenance.from_legacy_fields(artifact)

    assert provenance == Provenance(
        "direct_public_data",
        "An existing flat artifact note.",
        "ESO-42",
        "https://example.test/eso/42",
        "2026-07-14T08:00:00Z",
        False,
        ("ESO ASM",),
    )
    assert artifact == original


@pytest.mark.parametrize(
    ("legacy_value", "expected"),
    [
        (True, True),
        (False, False),
        (1, True),
        (0, False),
        ("true", True),
        (" TRUE ", True),
        ("yes", True),
        ("1", True),
        ("false", False),
        (" NO ", False),
        ("0", False),
    ],
)
def test_from_legacy_fields_supports_recognized_boolean_encodings(
    legacy_value: object,
    expected: bool,
) -> None:
    provenance = Provenance.from_legacy_fields(
        {
            "source_class": "synthetic_assumed",
            "source_note": "Legacy metadata.",
            "fallback_used": legacy_value,
        }
    )

    assert provenance.fallback_used is expected


@pytest.mark.parametrize("legacy_value", [2, -1, 0.0, "maybe", [], None])
def test_from_legacy_fields_rejects_ambiguous_boolean_encodings(
    legacy_value: object,
) -> None:
    with pytest.raises(ValueError, match="fallback_used"):
        Provenance.from_legacy_fields(
            {
                "source_class": "synthetic_assumed",
                "source_note": "Legacy metadata.",
                "fallback_used": legacy_value,
            }
        )


def test_legacy_fields_have_exact_six_key_shape_and_historical_note_name() -> None:
    provenance = Provenance(
        "direct_public_data",
        "Direct public calibration record.",
        "calibration-42",
        "https://example.test/calibration/42",
        "2026-07-14T12:34:56Z",
        True,
    )

    fields_record = provenance.to_legacy_fields()

    assert list(fields_record) == [
        "source_class",
        "source_note",
        "source_id",
        "url",
        "access_time",
        "fallback_used",
    ]
    assert "note" not in fields_record
    assert "references" not in fields_record
    assert fields_record["source_note"] == provenance.source_note
    assert json.loads(json.dumps(fields_record)) == fields_record
    assert Provenance.from_legacy_fields(fields_record) == provenance


def test_legacy_round_trip_preserves_none_empty_text_and_defaults() -> None:
    provenance = Provenance(
        "synthetic_literature_inspired",
        "Synthetic profile.",
        "",
        None,
        "",
    )

    assert Provenance.from_legacy_fields(provenance.to_legacy_fields()) == provenance


def test_to_record_emits_the_exact_schema_2_shape_and_field_order() -> None:
    provenance = _complete_provenance()

    record = provenance.to_record()

    assert list(record) == [
        "schema_name",
        "schema_version",
        "source_class",
        "note",
        "source_id",
        "url",
        "access_time",
        "fallback_used",
        "references",
    ]
    assert record == {
        "schema_name": "shwfs_ao.provenance",
        "schema_version": 2,
        "source_class": "direct_public_data",
        "note": "Direct public calibration record.",
        "source_id": "calibration-42",
        "url": "https://example.test/calibration/42",
        "access_time": "2026-07-14T12:34:56Z",
        "fallback_used": True,
        "references": ["doi:10.1234/example", "catalog:example-42"],
    }
    assert "source_note" not in record


def test_structured_record_has_an_exact_json_round_trip() -> None:
    provenance = _complete_provenance()
    json_record = json.loads(json.dumps(provenance.to_record()))
    original = json_record.copy()

    recovered = Provenance.from_record(json_record)

    assert recovered == provenance
    assert recovered.to_record() == json_record
    assert json_record == original


def test_from_record_uses_canonical_note_and_never_substitutes_source_note() -> None:
    legacy_named_record = {
        "schema_name": "shwfs_ao.provenance",
        "schema_version": 2,
        "source_class": "synthetic_assumed",
        "source_note": "This legacy key is invalid in a structured record.",
    }

    with pytest.raises(ValueError, match="source_note|note"):
        Provenance.from_record(legacy_named_record)


def test_from_record_rejects_unknown_fields_instead_of_losing_them() -> None:
    record = _complete_provenance().to_record()
    record["unmodeled_extension"] = "would be lost"

    with pytest.raises(ValueError, match="Unsupported.*unmodeled_extension"):
        Provenance.from_record(record)


@pytest.mark.parametrize(
    "schema_name",
    [None, "", "shwfs_ao.Provenance", "other.provenance"],
)
def test_from_record_rejects_the_wrong_schema_name(schema_name: object) -> None:
    record = _complete_provenance().to_record()
    record["schema_name"] = schema_name

    with pytest.raises(ValueError, match="schema_name.*shwfs_ao.provenance"):
        Provenance.from_record(record)


@pytest.mark.parametrize("schema_version", [None, 1, 3, "2", 2.0, True])
def test_from_record_rejects_unsupported_or_loosely_typed_versions(
    schema_version: object,
) -> None:
    record = _complete_provenance().to_record()
    record["schema_version"] = schema_version

    with pytest.raises(ValueError, match="Unsupported.*schema_version.*version 2"):
        Provenance.from_record(record)


def test_unsupported_version_is_identified_even_when_the_record_is_incomplete() -> None:
    with pytest.raises(ValueError, match="Unsupported.*schema_version=3"):
        Provenance.from_record(
            {
                "schema_name": "shwfs_ao.provenance",
                "schema_version": 3,
            }
        )


@pytest.mark.parametrize("schema_version", [1, 3, "2", 2.0, True])
def test_to_record_rejects_every_requested_version_except_integer_two(
    schema_version: object,
) -> None:
    with pytest.raises(ValueError, match="Unsupported.*schema_version.*version 2"):
        _complete_provenance().to_record(schema_version)  # type: ignore[arg-type]


def test_structured_record_requires_all_nine_keys_for_exact_round_trips() -> None:
    record = {
        "schema_name": "shwfs_ao.provenance",
        "schema_version": 2,
        "source_class": "package_reference",
        "note": "Packaged reference.",
    }

    with pytest.raises(ValueError, match="missing required fields.*source_id.*references"):
        Provenance.from_record(record)


def test_structured_record_is_strict_about_boolean_and_reference_json_types() -> None:
    record = _complete_provenance().to_record()
    record["fallback_used"] = "false"
    with pytest.raises(ValueError, match="fallback_used.*bool"):
        Provenance.from_record(record)

    record = _complete_provenance().to_record()
    record["references"] = "one reference"
    with pytest.raises(ValueError, match="references"):
        Provenance.from_record(record)

    record = _complete_provenance().to_record()
    record["references"] = tuple(record["references"])
    with pytest.raises(ValueError, match="JSON list"):
        Provenance.from_record(record)


@pytest.mark.parametrize("factory", [Provenance.from_legacy_fields, Provenance.from_record])
@pytest.mark.parametrize("not_a_mapping", [None, [], "record", 3])
def test_deserializers_reject_non_mapping_inputs(factory, not_a_mapping: object) -> None:
    with pytest.raises(ValueError, match="mapping"):
        factory(not_a_mapping)  # type: ignore[arg-type]
