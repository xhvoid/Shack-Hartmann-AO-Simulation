"""Canonical provenance taxonomy and serialization helpers.

The core representation is deliberately independent from data loading and
artifact I/O.  Legacy artifacts use flat ``source_*`` fields, while canonical
records carry an explicit schema name and version.  The adapters below keep
those two representations distinct so an enclosing artifact's schema version
cannot accidentally be interpreted as a provenance schema version.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Literal, cast


SourceClass = Literal[
    "direct_public_data",
    "literature_derived",
    "synthetic_literature_inspired",
    "synthetic_assumed",
    "package_reference",
]

ALLOWED_SOURCE_CLASSES: frozenset[str] = frozenset(
    {
        "direct_public_data",
        "literature_derived",
        "synthetic_literature_inspired",
        "synthetic_assumed",
        "package_reference",
    }
)

_SCHEMA_NAME = "shwfs_ao.provenance"
_SCHEMA_VERSION = 2
_STRUCTURED_FIELD_ORDER = (
    "schema_name",
    "schema_version",
    "source_class",
    "note",
    "source_id",
    "url",
    "access_time",
    "fallback_used",
    "references",
)
_STRUCTURED_FIELDS = frozenset(_STRUCTURED_FIELD_ORDER)

__all__ = (
    "SourceClass",
    "ALLOWED_SOURCE_CLASSES",
    "Provenance",
)


@dataclass(frozen=True)
class Provenance:
    """Immutable source metadata shared by AO domain objects.

    The first six fields intentionally retain the positional order of the
    historical data-loader model.  ``references`` is trailing so adding it
    does not reinterpret an existing positional construction.
    """

    source_class: SourceClass
    source_note: str
    source_id: str | None = None
    url: str | None = None
    access_time: str | None = None
    fallback_used: bool = False
    references: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if (
            not isinstance(self.source_class, str)
            or self.source_class not in ALLOWED_SOURCE_CLASSES
        ):
            raise ValueError(
                f"Invalid source_class={self.source_class!r}; expected one of "
                f"{sorted(ALLOWED_SOURCE_CLASSES)}."
            )
        if not isinstance(self.source_note, str) or not self.source_note.strip():
            raise ValueError("source_note must be a non-empty string.")

        for field_name in ("source_id", "url", "access_time"):
            value = getattr(self, field_name)
            if value is not None and not isinstance(value, str):
                raise ValueError(
                    f"{field_name} must be a string or None; got {value!r}."
                )
        if not isinstance(self.fallback_used, bool):
            raise ValueError(
                "fallback_used must be a bool; "
                f"got {self.fallback_used!r}."
            )
        if not isinstance(self.references, tuple):
            raise ValueError(
                "references must be a tuple of strings; "
                f"got {type(self.references).__name__}."
            )
        for index, reference in enumerate(self.references):
            if not isinstance(reference, str):
                raise ValueError(
                    f"references[{index}] must be a string; got {reference!r}."
                )

    @property
    def note(self) -> str:
        """Return the canonical short name for the historical source note."""

        return self.source_note

    @classmethod
    def from_legacy_fields(cls, fields: Mapping[str, object]) -> Provenance:
        """Create provenance from flat historical ``source_*`` fields.

        ``fields`` may be an entire JSON/CSV artifact metadata mapping.  Keys
        unrelated to provenance, including an enclosing ``schema_version``,
        are intentionally ignored.
        """

        mapping = _require_mapping(fields, label="legacy provenance fields")
        references = _references_from_value(
            mapping.get("references", ()),
            label="references",
        )
        return cls(
            source_class=cast(SourceClass, mapping.get("source_class")),
            source_note=cast(str, mapping.get("source_note")),
            source_id=_optional_string(mapping.get("source_id"), "source_id"),
            url=_optional_string(mapping.get("url"), "url"),
            access_time=_optional_string(mapping.get("access_time"), "access_time"),
            fallback_used=_legacy_boolean(mapping.get("fallback_used", False)),
            references=references,
        )

    def to_legacy_fields(self) -> dict[str, object]:
        """Return deterministic flat fields using historical key names."""

        return {
            "source_class": self.source_class,
            "source_note": self.source_note,
            "source_id": self.source_id,
            "url": self.url,
            "access_time": self.access_time,
            "fallback_used": self.fallback_used,
        }

    @classmethod
    def from_record(cls, record: Mapping[str, object]) -> Provenance:
        """Deserialize a canonical schema-version-2 provenance record."""

        mapping = _require_mapping(record, label="provenance record")
        unknown_fields = sorted(
            (str(key) for key in mapping if key not in _STRUCTURED_FIELDS)
        )
        if unknown_fields:
            raise ValueError(
                f"Unsupported provenance record fields: {unknown_fields}."
            )

        schema_name = mapping.get("schema_name")
        if schema_name != _SCHEMA_NAME:
            raise ValueError(
                f"Invalid provenance schema_name={schema_name!r}; "
                f"expected {_SCHEMA_NAME!r}."
            )
        _validate_schema_version(mapping.get("schema_version"))
        missing_fields = [
            field_name
            for field_name in _STRUCTURED_FIELD_ORDER
            if field_name not in mapping
        ]
        if missing_fields:
            raise ValueError(
                f"Provenance record is missing required fields: {missing_fields}."
            )
        return cls(
            source_class=cast(SourceClass, mapping.get("source_class")),
            source_note=cast(str, mapping["note"]),
            source_id=_optional_string(mapping.get("source_id"), "source_id"),
            url=_optional_string(mapping.get("url"), "url"),
            access_time=_optional_string(mapping.get("access_time"), "access_time"),
            fallback_used=_strict_boolean(
                mapping.get("fallback_used", False),
                label="fallback_used",
            ),
            references=_references_from_json_list(mapping["references"]),
        )

    def to_record(self, schema_version: int = _SCHEMA_VERSION) -> dict[str, object]:
        """Serialize to a deterministic canonical provenance record."""

        _validate_schema_version(schema_version)
        return {
            "schema_name": _SCHEMA_NAME,
            "schema_version": _SCHEMA_VERSION,
            "source_class": self.source_class,
            "note": self.source_note,
            "source_id": self.source_id,
            "url": self.url,
            "access_time": self.access_time,
            "fallback_used": self.fallback_used,
            "references": list(self.references),
        }


def _require_mapping(value: object, *, label: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{label} must be a mapping; got {type(value).__name__}.")
    return cast(Mapping[str, object], value)


def _optional_string(value: object, label: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError(f"{label} must be a string or None; got {value!r}.")
    return value


def _strict_boolean(value: object, *, label: str) -> bool:
    if not isinstance(value, bool):
        raise ValueError(f"{label} must be a bool; got {value!r}.")
    return value


def _legacy_boolean(value: object) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"1", "true", "yes"}:
            return True
        if normalized in {"0", "false", "no"}:
            return False
    if isinstance(value, int) and not isinstance(value, bool) and value in {0, 1}:
        return bool(value)
    raise ValueError(
        "fallback_used must be a bool or a recognized legacy boolean "
        f"value; got {value!r}."
    )


def _references_from_value(value: object, *, label: str) -> tuple[str, ...]:
    if not isinstance(value, (list, tuple)):
        raise ValueError(f"{label} must be a list or tuple of strings.")
    references = tuple(value)
    for index, reference in enumerate(references):
        if not isinstance(reference, str):
            raise ValueError(
                f"{label}[{index}] must be a string; got {reference!r}."
            )
    return references


def _references_from_json_list(value: object) -> tuple[str, ...]:
    if not isinstance(value, list):
        raise ValueError("references must be a JSON list of strings.")
    return _references_from_value(value, label="references")


def _validate_schema_version(value: object) -> None:
    if type(value) is not int or value != _SCHEMA_VERSION:
        raise ValueError(
            f"Unsupported provenance schema_version={value!r}; "
            f"only version {_SCHEMA_VERSION} is supported."
        )
