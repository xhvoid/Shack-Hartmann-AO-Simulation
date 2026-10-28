"""Shared helpers of the post-T2 packet tools (not runtime code).

* :func:`load_script_module` imports one of the two study drivers by path,
  registered in ``sys.modules`` before execution so that their dataclasses
  (``from __future__ import annotations``) resolve their annotations
  (review round 1, finding 1).
* :func:`add_configuration_arguments` / :func:`configuration_from_arguments`
  give the traced pilot and the linear model the same configuration choice:
  a packaged profile (``--profile``/``--profile-version``) or the convergence
  driver's ci derivation (``--ci-geometry``), with the optional guide-star
  magnitude and the diagnostic reconstructor damping override ``--alpha``
  (tool validation only; it changes the configuration hash and is recorded,
  and is never part of a governed series).
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import resource
import sys
from typing import Any

import numpy as np

REPO = Path(__file__).resolve().parents[4]
SCRIPTS = REPO / "scripts"
GOVERNED_PROFILES = {"det_emccd_12m_medium_derived", "det_ccd_42m_r3band_derived"}


def load_script_module(stem: str) -> Any:
    """Import ``scripts/<stem>.py`` as module ``stem`` (registered first, loaded once)."""

    if stem in sys.modules:
        return sys.modules[stem]
    path = SCRIPTS / f"{stem}.py"
    spec = importlib.util.spec_from_file_location(stem, path)
    if spec is None or spec.loader is None:
        raise SystemExit(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[stem] = module
    try:
        spec.loader.exec_module(module)
    except BaseException:
        del sys.modules[stem]
        raise
    return module


def add_configuration_arguments(parser: Any, *, default_profile: str = "det_emccd_12m_medium_derived", default_version: int = 3) -> None:
    parser.add_argument("--profile", default=default_profile, help=f"packaged profile name (default {default_profile})")
    parser.add_argument("--profile-version", type=int, default=default_version)
    parser.add_argument("--ci-geometry", action="store_true", help="the convergence driver's ci derivation (5 m smoke geometry with the 12 m @3 detector physics) instead of a profile")
    parser.add_argument("--magnitude", type=float, help="guide-star AB magnitude override (configurations with an AB source only)")
    parser.add_argument("--alpha", type=float, help="DIAGNOSTIC reconstructor damping override (tool validation only; changes the configuration hash; never for a governed series)")


def configuration_from_arguments(arguments: Any) -> tuple[Any, str, bool]:
    """``(config, description, governed)`` for the parsed configuration arguments."""

    from dataclasses import replace

    from shwfs_ao.experiments.detector_level import with_magnitude
    from shwfs_ao.io.configs import load_system_profile

    if arguments.ci_geometry:
        driver = load_script_module("detector_level_convergence_study")
        config = driver.base_configuration("ci")
        described = "ci derivation of scripts/detector_level_convergence_study.py (eso_scao_smoke_5m_software@2 geometry with det_emccd_12m_medium_derived@3 physics)"
        governed = False
    else:
        config = load_system_profile(arguments.profile, int(arguments.profile_version))
        described = f"{arguments.profile}@{arguments.profile_version}"
        governed = arguments.profile in GOVERNED_PROFILES
    if arguments.magnitude is not None:
        config = with_magnitude(config, float(arguments.magnitude))
        described += f", m_AB {arguments.magnitude:g}"
    if arguments.alpha is not None:
        config = replace(config, reconstructor=replace(config.reconstructor, alpha=float(arguments.alpha)))
        described += f", DIAGNOSTIC reconstructor alpha {arguments.alpha:g}"
    return config, described, governed


def run_configuration(config: Any, *, root_seed: int, n_steps: int) -> Any:
    """The configuration a paired run hashes: the seed and the frame count applied as the experiment core applies them."""

    from dataclasses import replace

    from shwfs_ao.io.configs import RandomSeedConfig

    return replace(config, random=RandomSeedConfig(root_seed=int(root_seed)), controller=replace(config.controller, n_steps=int(n_steps)))


def jsonable(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [jsonable(item) for item in value]
    if isinstance(value, np.generic):
        return value.item()
    if isinstance(value, np.ndarray):
        return value.tolist()
    if isinstance(value, Path):
        return str(value)
    return value


def peak_rss_bytes() -> int:
    peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return int(peak if sys.platform == "darwin" else peak * 1024)


def write_record_once(path: Path, record: dict[str, Any]) -> None:
    """Write one JSON record; never over an existing file."""

    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "x", encoding="utf-8") as handle:
        json.dump(record, handle, indent=1, default=float)
        handle.write("\n")


def write_npz_once(path: Path, arrays: dict[str, np.ndarray], metadata: dict[str, Any]) -> dict[str, Any]:
    """Write a pilot trace archive (sidecar layout, ``metadata_json`` entry) once; return its reference."""

    import hashlib
    import io

    path = Path(path)
    if path.exists():
        raise SystemExit(f"{path} exists; nothing is overwritten.")
    buffer = io.BytesIO()
    np.savez_compressed(buffer, metadata_json=np.array(json.dumps(metadata, sort_keys=True, default=str)), **arrays)
    payload = buffer.getvalue()
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "xb") as handle:
        handle.write(payload)
    return {"file": path.name, "sha256": hashlib.sha256(payload).hexdigest(), "bytes": len(payload), "schema": metadata.get("schema")}
