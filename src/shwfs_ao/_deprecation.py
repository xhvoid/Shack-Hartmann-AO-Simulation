"""AO-REF-021 Phase A deprecation metadata and warning-message helpers.

The single sources of truth are two packaged resources:

- ``shwfs_ao/resources/deprecation_clock.json`` records the deprecation
  release/tag, the publication UTC date, the planned removal release, and the
  recorded earliest-removal UTC date.
- ``shwfs_ao/resources/deprecation_inventory.json`` records every installed
  root-level shim, resource alias, legacy module, and public symbol with its
  replacement.

The installed root shims build their import-time ``DeprecationWarning``
messages from these records so warning text, migration documentation, and the
machine-readable clock cannot drift apart.  This module must stay import-light:
it is pulled in by every root shim and must not import optional dependencies
or any physics module.
"""

from __future__ import annotations

from collections.abc import Mapping as _Mapping
import datetime as _datetime
from functools import lru_cache as _lru_cache
from importlib import resources as _resources
import json as _json
from types import MappingProxyType as _MappingProxyType
from typing import Any as _Any

_RESOURCE_PACKAGE = "shwfs_ao.resources"
CLOCK_RESOURCE_NAME = "deprecation_clock.json"
INVENTORY_RESOURCE_NAME = "deprecation_inventory.json"


class DeprecationMetadataError(ValueError):
    """Raised when the packaged deprecation metadata is missing or invalid."""


def _load_json_resource(name: str) -> dict[str, _Any]:
    try:
        payload = (
            _resources.files(_RESOURCE_PACKAGE).joinpath(name).read_text(encoding="utf-8")
        )
    except (FileNotFoundError, ModuleNotFoundError) as exc:
        raise DeprecationMetadataError(
            f"Packaged deprecation metadata {name!r} is not installed."
        ) from exc
    try:
        data = _json.loads(payload)
    except _json.JSONDecodeError as exc:
        raise DeprecationMetadataError(
            f"Packaged deprecation metadata {name!r} is not valid JSON: {exc}."
        ) from exc
    if not isinstance(data, dict):
        raise DeprecationMetadataError(
            f"Packaged deprecation metadata {name!r} must be a JSON object."
        )
    return data


def _deep_freeze_json_object(value: dict[str, _Any]) -> _Mapping[str, _Any]:
    """Return an immutable recursive view of one JSON object.

    Both public metadata loaders cache their result.  Freezing only the outer
    dictionary would still expose the nested dictionaries and lists from that
    cached object, allowing one caller to corrupt every later read in the
    process.  JSON arrays become tuples and every nested JSON object gets its
    own read-only mapping proxy.
    """

    return _MappingProxyType(
        {key: _deep_freeze_json_value(item) for key, item in value.items()}
    )


def _deep_freeze_json_value(value: _Any) -> _Any:
    if isinstance(value, dict):
        return _deep_freeze_json_object(value)
    if isinstance(value, list):
        return tuple(_deep_freeze_json_value(item) for item in value)
    return value


@_lru_cache(maxsize=1)
def deprecation_clock() -> _Mapping[str, _Any]:
    """Return the validated machine-readable deprecation clock."""

    clock = _load_json_resource(CLOCK_RESOURCE_NAME)
    required = {
        "schema_name",
        "schema_version",
        "deprecation_release",
        "deprecation_tag",
        "publication_status",
        "publication_utc_date",
        "planned_removal_release",
        "minimum_window_days",
        "minimum_subsequent_minor_releases",
        "subsequent_minor_release",
        "earliest_removal_utc_date",
    }
    missing = sorted(required - set(clock))
    if missing:
        raise DeprecationMetadataError(f"Deprecation clock is missing fields: {missing}.")
    if clock["schema_name"] != "shwfs_ao.deprecation_clock":
        raise DeprecationMetadataError(
            "Deprecation clock schema_name must be 'shwfs_ao.deprecation_clock'."
        )
    for label, status in (
        ("publication_status", clock["publication_status"]),
        (
            "subsequent_minor_release.publication_status",
            clock["subsequent_minor_release"].get("publication_status")
            if isinstance(clock["subsequent_minor_release"], _Mapping)
            else None,
        ),
    ):
        if status not in {"planned", "published"}:
            raise DeprecationMetadataError(
                f"Deprecation clock {label} must be 'planned' or 'published', "
                f"got {status!r}."
            )
    recorded = parse_utc_date(clock["earliest_removal_utc_date"])
    recomputed = earliest_removal_utc_date(clock)
    if recorded != recomputed:
        raise DeprecationMetadataError(
            "Recorded earliest_removal_utc_date "
            f"{recorded.isoformat()} does not match the recomputed boundary "
            f"{recomputed.isoformat()}."
        )
    return _deep_freeze_json_object(clock)


@_lru_cache(maxsize=1)
def deprecation_inventory() -> _Mapping[str, _Any]:
    """Return the machine-readable Phase A deprecation inventory."""

    inventory = _load_json_resource(INVENTORY_RESOURCE_NAME)
    if inventory.get("schema_name") != "shwfs_ao.deprecation_inventory":
        raise DeprecationMetadataError(
            "Deprecation inventory schema_name must be 'shwfs_ao.deprecation_inventory'."
        )
    return _deep_freeze_json_object(inventory)


def parse_utc_date(value: object) -> _datetime.date:
    """Parse one ISO ``YYYY-MM-DD`` UTC calendar date."""

    if not isinstance(value, str):
        raise DeprecationMetadataError(f"UTC date must be a string, got {value!r}.")
    try:
        return _datetime.date.fromisoformat(value)
    except ValueError as exc:
        raise DeprecationMetadataError(f"Invalid UTC date {value!r}: {exc}.") from exc


def earliest_removal_utc_date(clock: _Mapping[str, _Any]) -> _datetime.date:
    """Compute the earliest legal Phase B removal date from clock fields.

    The boundary is the later of the publication date plus
    ``minimum_window_days`` and every *published* subsequent-minor-release
    date.  While the required subsequent minor release is unpublished the
    returned date is the day-count floor; :func:`removal_boundaries_satisfied`
    separately reports that the release boundary is still open.
    """

    publication = parse_utc_date(clock["publication_utc_date"])
    window_days = clock["minimum_window_days"]
    if type(window_days) is not int or window_days < 0:
        raise DeprecationMetadataError(
            f"minimum_window_days must be a non-negative integer, got {window_days!r}."
        )
    boundary = publication + _datetime.timedelta(days=window_days)
    subsequent = clock["subsequent_minor_release"]
    if not isinstance(subsequent, _Mapping):
        raise DeprecationMetadataError("subsequent_minor_release must be an object.")
    published_date = subsequent.get("publication_utc_date")
    if published_date is not None:
        boundary = max(boundary, parse_utc_date(published_date))
    return boundary


def removal_boundaries_satisfied(
    clock: _Mapping[str, _Any],
    on_utc_date: _datetime.date,
) -> bool:
    """Return whether both Phase B boundaries have elapsed on ``on_utc_date``.

    Both the recorded time window and the announced release boundary must
    hold: the date must not precede the computed earliest-removal date, the
    deprecation release must actually be published, and the required
    subsequent minor release must also be published.
    """

    if clock["publication_status"] != "published":
        return False
    subsequent = clock["subsequent_minor_release"]
    if not isinstance(subsequent, _Mapping):
        raise DeprecationMetadataError("subsequent_minor_release must be an object.")
    if subsequent.get("publication_status") != "published":
        return False
    if subsequent.get("publication_utc_date") is None:
        return False
    return on_utc_date >= earliest_removal_utc_date(clock)


@_lru_cache(maxsize=None)
def root_shim_replacement(module_name: str) -> str:
    """Return the documented replacement text for one root-level shim."""

    for record in deprecation_inventory()["root_shims"]:
        if record["module"] == module_name:
            return record["replacement"]
    raise DeprecationMetadataError(
        f"Root shim {module_name!r} is not listed in the deprecation inventory."
    )


def deprecation_release_clause() -> str:
    """Phrase the deprecation release honestly for the recorded clock state.

    While ``publication_status`` is ``"planned"`` the deprecation release has
    not been tagged, so the message must announce a schedule rather than
    assert an accomplished release; once the clock records ``"published"``
    the wording becomes the plain "as of" form with no code change.
    """

    clock = deprecation_clock()
    release = clock["deprecation_release"]
    if clock["publication_status"] == "published":
        return f"as of release {release}"
    return f"(scheduled for release {release}, not yet published)"


def root_shim_deprecation_message(module_name: str) -> str:
    """Build the import-time DeprecationWarning message for one root shim."""

    clock = deprecation_clock()
    return (
        f"Importing the root-level module {module_name!r} is deprecated "
        f"{deprecation_release_clause()}; use "
        f"{root_shim_replacement(module_name)} instead. This installed shim is "
        f"scheduled for removal in release {clock['planned_removal_release']} "
        f"(no earlier than {clock['earliest_removal_utc_date']} UTC and only "
        "after at least "
        f"{clock['minimum_subsequent_minor_releases']} further minor release). "
        "See docs/migration.md."
    )


def resource_alias_deprecation_message() -> str:
    """Build the import-time DeprecationWarning message for the resource alias."""

    clock = deprecation_clock()
    return (
        "Importing the 'ao_simulation_data' resource alias package is "
        f"deprecated {deprecation_release_clause()}; read "
        "packaged data through shwfs_ao.io.resources (canonical package "
        "shwfs_ao.resources) instead. This installed alias is scheduled for "
        f"removal in release {clock['planned_removal_release']} (no earlier "
        f"than {clock['earliest_removal_utc_date']} UTC and only after at "
        f"least {clock['minimum_subsequent_minor_releases']} further minor "
        "release). See docs/migration.md."
    )
