"""Strict offline loading of the packaged physical-camera presets.

Presets live in ``benchmarks/detector_camera_presets.v1.json`` and are
addressed by ``(name, version)``; there is no implicit latest version.  Every
packaged preset is ``synthetic_assumed``.
"""

from __future__ import annotations

import json
from typing import Any, Final

from ..detector.camera import CameraConfig, CameraConfigError, camera_config_from_mapping
from .resources import read_text_resource


__all__ = (
    "CAMERA_PRESETS_RESOURCE",
    "CameraPresetError",
    "available_camera_presets",
    "load_camera_preset",
)


CAMERA_PRESETS_RESOURCE: Final = "benchmarks/detector_camera_presets.v1.json"


class CameraPresetError(ValueError):
    """Raised when a camera preset is unknown or its record is malformed."""


def _unique(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise CameraPresetError(f"duplicate key {key!r} in the camera presets.")
        result[key] = value
    return result


def _records() -> dict[tuple[str, int], dict[str, Any]]:
    try:
        record = json.loads(read_text_resource(CAMERA_PRESETS_RESOURCE), object_pairs_hook=_unique)
    except (OSError, json.JSONDecodeError) as exc:
        raise CameraPresetError(f"cannot read the camera presets: {exc}") from exc
    if record.get("schema_name") != "shwfs_ao.camera_presets" or record.get("schema_version") != 1:
        raise CameraPresetError("camera preset resource schema mismatch.")
    presets: dict[tuple[str, int], dict[str, Any]] = {}
    for entry in record.get("presets", []):
        key = (entry.get("preset_name"), entry.get("preset_version"))
        if key in presets:
            raise CameraPresetError(f"duplicate camera preset {key!r}.")
        presets[key] = entry
    return presets


def available_camera_presets() -> tuple[tuple[str, int], ...]:
    """Every packaged preset as an explicit ``(name, version)`` key."""

    return tuple(_records())


def load_camera_preset(name: str, version: int) -> CameraConfig:
    """Load one exact packaged preset; unknown keys are rejected."""

    records = _records()
    key = (name, version)
    if key not in records:
        raise CameraPresetError(
            f"unknown camera preset {key!r}; available={sorted(records)!r}."
        )
    try:
        return camera_config_from_mapping(dict(records[key]))
    except CameraConfigError as exc:
        raise CameraPresetError(f"camera preset {key!r} is invalid: {exc}") from exc
