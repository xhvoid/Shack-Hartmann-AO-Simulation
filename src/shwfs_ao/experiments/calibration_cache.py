"""Explicit on-disk reuse of scalable (sparse) interaction calibrations.

A full-scale grouped calibration is deterministic: the same probe basis,
sensor, amplitude, method and random scope always produce the same sparse
response, bit for bit, and therefore the same ``calibration_hash``.  A
:class:`SparseCalibrationCache` stores that response under a key derived from
exactly those inputs, in a directory the caller names, and reuses it on a
later build.  A reused response is verified field by field against what this
build would calibrate (coordinate IDs and exclusions, sensor, response,
geometry and DM identities, amplitude, method, strategy, probe-basis hash and
random scope) and its content hash is re-derived on load; any disagreement
fails closed instead of recalibrating silently.  Nothing is written unless a
cache is passed.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from ..calibration.sparse import (
    GROUPED_LOCAL_STRATEGY,
    LocalDmProbeBasis,
    SparseCalibrationError,
    SparseInteractionMatrix,
)
from ..core.hashing import component_config_hash
from ..core.protocols import RandomStreams


__all__ = ("SparseCalibrationCache", "SparseCalibrationCacheError")


class SparseCalibrationCacheError(ValueError):
    """Raised when a cached calibration does not match the build requesting it."""


class SparseCalibrationCache:
    """Directory of verified sparse calibrations keyed by their inputs."""

    def __init__(self, directory: str | os.PathLike[str]) -> None:
        self._directory = Path(directory)
        self.hits = 0
        self.misses = 0
        self.last_key: str | None = None
        self.last_path: Path | None = None

    @property
    def directory(self) -> Path:
        return self._directory

    @staticmethod
    def key(
        *,
        probe_basis: LocalDmProbeBasis,
        sensor: Any,
        amplitude_m: float,
        method: str,
        random_streams: RandomStreams,
    ) -> str:
        return component_config_hash(
            "scao.sparse_calibration_cache_key",
            {
                "strategy": GROUPED_LOCAL_STRATEGY,
                "probe_basis_hash": probe_basis.config_hash,
                "dm_hash": probe_basis.dm_hash,
                "sensor_config_hash": sensor.config_hash,
                "sensor_response_hash": getattr(sensor, "response_hash", None),
                "geometry_hash": sensor.geometry.geometry_hash,
                "amplitude_m": float(amplitude_m),
                "method": method,
                "root_seed": random_streams.root_seed,
                "derivation_scheme_id": random_streams.derivation_scheme_id,
                "calibration_stream_id": random_streams.stream_id("calibration"),
            },
        )

    def path_for(self, key: str) -> Path:
        return self._directory / f"sparse_calibration_{key}.json"

    def load(
        self,
        key: str,
        *,
        probe_basis: LocalDmProbeBasis,
        sensor: Any,
        amplitude_m: float,
        method: str,
        root_seed: int,
    ) -> SparseInteractionMatrix | None:
        path = self.path_for(key)
        self.last_key = key
        self.last_path = path
        if not path.is_file():
            self.misses += 1
            return None
        try:
            record = json.loads(path.read_text(encoding="utf-8"))
            matrix = SparseInteractionMatrix.from_record(record)
        except (OSError, ValueError, SparseCalibrationError) as exc:
            raise SparseCalibrationCacheError(
                f"cached calibration {path} is unreadable or fails its content "
                f"hash: {exc}"
            ) from exc
        expected = {
            "coordinate_ids": probe_basis.coordinate_ids,
            "exclusions": probe_basis.exclusions,
            "sensor_config_hash": sensor.config_hash,
            "sensor_response_hash": getattr(sensor, "response_hash", None),
            "geometry_hash": sensor.geometry.geometry_hash,
            "dm_hash": probe_basis.dm_hash,
            "calibration_amplitude_m": float(amplitude_m),
            "method": method,
            "strategy": GROUPED_LOCAL_STRATEGY,
        }
        mismatched = [name for name, value in expected.items() if getattr(matrix, name) != value]
        references = set(matrix.provenance.references)
        for reference in (
            f"probe_basis_hash={probe_basis.config_hash}",
            f"random_root_seed={root_seed}",
        ):
            if reference not in references:
                mismatched.append(reference.split("=")[0])
        if mismatched:
            raise SparseCalibrationCacheError(
                f"cached calibration {path} does not match this build: {mismatched}."
            )
        self.hits += 1
        return matrix

    def store(self, key: str, matrix: SparseInteractionMatrix) -> Path:
        self._directory.mkdir(parents=True, exist_ok=True)
        path = self.path_for(key)
        temporary = path.with_suffix(".json.tmp")
        temporary.write_text(json.dumps(matrix.to_record()), encoding="utf-8")
        os.replace(temporary, path)
        self.last_key = key
        self.last_path = path
        return path
