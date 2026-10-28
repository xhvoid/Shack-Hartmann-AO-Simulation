"""Source, exporter, environment and host identities of the explorer producer.

Three identities are kept apart (PLAN section 6):

* the core runtime: the imported ``shwfs_ao`` package digest plus the Git
  state of its source directory;
* the candidate exporter: the digest of every file under
  ``scripts/ao_explorer`` plus the Git state of that directory;
* the environment: interpreter, NumPy/SciPy, machine and the constraint lock
  the installed distributions are verified against.

The package digest uses the algorithm of
``scripts/run_detector_level_evidence.py`` (relative name and content digest
of every non-hidden, non-bytecode file), so the two records are comparable.
Records hold names, never the local checkout path.
"""

from __future__ import annotations

import hashlib
from importlib import metadata
import json
from pathlib import Path
import platform
import subprocess
import sys
from typing import Any, Dict, Optional


EXPORTER_DIR = Path(__file__).resolve().parent
REPO_ROOT = EXPORTER_DIR.parents[1]
LOCK_PATH = REPO_ROOT / "constraints" / "hcipy-py314.txt"
IGNORED_DISTRIBUTIONS = frozenset({"pip", "shack-hartmann-ao-simulation"})


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    return sha256_bytes(Path(path).read_bytes())


def canonical_json_bytes(value: Any) -> bytes:
    """Deterministic JSON bytes for hashing (sorted keys, no NaN)."""

    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")


def tree_digest(directory: Path, *, suffixes: Optional[tuple] = None) -> Dict[str, Any]:
    """Digest of a directory: each relative name and its content digest."""

    digest = hashlib.sha256()
    members: Dict[str, str] = {}
    for path in sorted(Path(directory).rglob("*")):
        relative = path.relative_to(directory)
        if any(part.startswith(".") for part in relative.parts) or "__pycache__" in relative.parts:
            continue
        if not path.is_file() or path.suffix == ".pyc":
            continue
        if suffixes is not None and path.suffix not in suffixes:
            continue
        file_digest = sha256_file(path)
        members[relative.as_posix()] = file_digest
        digest.update(relative.as_posix().encode("utf-8") + b"\0")
        digest.update(bytes.fromhex(file_digest))
    return {"sha256": digest.hexdigest(), "files": members}


def _git(*arguments: str) -> Optional[str]:
    try:
        completed = subprocess.run(
            ["git", "--literal-pathspecs", *arguments],
            cwd=REPO_ROOT,
            capture_output=True,
            check=True,
        )
    except (OSError, subprocess.CalledProcessError):
        return None
    return completed.stdout.decode("utf-8", "replace")


def git_state(relative_directory: str) -> Dict[str, Any]:
    """HEAD and the digest of uncommitted changes (tracked and untracked) below a path."""

    head = _git("rev-parse", "HEAD")
    diff = _git("diff", "HEAD", "--binary", "--", relative_directory)
    untracked = _git("ls-files", "--others", "--exclude-standard", "--", relative_directory)
    untracked_names = sorted(line for line in (untracked or "").splitlines() if line)
    untracked_digest = hashlib.sha256()
    for name in untracked_names:
        untracked_digest.update(name.encode("utf-8") + b"\0")
        untracked_digest.update(bytes.fromhex(sha256_file(REPO_ROOT / name)))
    return {
        "git_head": None if head is None else head.strip(),
        "path": relative_directory,
        "tracked_changes_sha256": None if diff is None else sha256_bytes(diff.encode("utf-8")),
        "tracked_changes_empty": diff == "",
        "untracked_files": untracked_names,
        "untracked_sha256": untracked_digest.hexdigest(),
    }


def core_identity() -> Dict[str, Any]:
    """The runtime package this process actually imports."""

    import shwfs_ao

    package = Path(shwfs_ao.__file__).resolve().parent
    inside_repo = package.is_relative_to(REPO_ROOT)
    record: Dict[str, Any] = {
        "package": "shwfs_ao",
        "package_directory_relative": (
            package.relative_to(REPO_ROOT).as_posix() if inside_repo else None
        ),
        "imported_from_task_checkout": inside_repo,
        "package_sha256": tree_digest(package)["sha256"],
        "version": getattr(shwfs_ao, "__version__", None),
    }
    record["git"] = git_state("src") if inside_repo else None
    return record


# The files executed by a numerical trajectory child: their digest is the
# physical producer identity a series plan binds.  Rendering, observation
# derivation, research export and validation are separate derived-export
# identities, so a display change never relabels or invalidates AO data.
PRODUCER_FILES = (
    "protocol.py",
    "identity.py",
    "admission.py",
    "observer.py",
    "producer.py",
    "run_job.py",
)
DERIVED_FILES = (
    "binary_scene.py",
    "render.py",
    "research.py",
    "export.py",
    "validate.py",
)


def file_set_identity(names: tuple) -> Dict[str, Any]:
    digest = hashlib.sha256()
    members: Dict[str, Optional[str]] = {}
    for name in names:
        path = EXPORTER_DIR / name
        file_digest = sha256_file(path) if path.is_file() else None
        members[name] = file_digest
        digest.update(name.encode("utf-8") + b"\0")
        digest.update(b"<missing>" if file_digest is None else bytes.fromhex(file_digest))
    return {"sha256": digest.hexdigest(), "files": members}


def exporter_identity() -> Dict[str, Any]:
    """The candidate producer source (the numerical child's files)."""

    directory = EXPORTER_DIR.relative_to(REPO_ROOT).as_posix()
    producer = file_set_identity(PRODUCER_FILES)
    return {
        "directory": directory,
        "sha256": producer["sha256"],
        "files": producer["files"],
        "git": git_state(directory),
    }


def derived_identity() -> Dict[str, Any]:
    """The observation/rendering/research/validation source (a separate export identity)."""

    derived = file_set_identity(DERIVED_FILES)
    return {
        "directory": EXPORTER_DIR.relative_to(REPO_ROOT).as_posix(),
        "sha256": derived["sha256"],
        "files": derived["files"],
        "git": git_state(EXPORTER_DIR.relative_to(REPO_ROOT).as_posix()),
    }


def _normalize(name: str) -> str:
    return name.strip().lower().replace("_", "-")


def lock_verification(lock_path: Path = LOCK_PATH) -> Dict[str, Any]:
    """Installed distributions against the constraint lock (installed must be pinned)."""

    pins: Dict[str, str] = {}
    for raw in Path(lock_path).read_text(encoding="utf-8").splitlines():
        line = raw.split("#", 1)[0].split(";", 1)[0].strip()
        if line and "==" in line and not line.startswith("-"):
            name, _, version = line.partition("==")
            pins[_normalize(name)] = version.strip()
    violations = []
    installed = {}
    for distribution in metadata.distributions():
        name = distribution.metadata["Name"]
        if name is None:
            continue
        normalized = _normalize(name)
        if normalized in IGNORED_DISTRIBUTIONS:
            continue
        installed[normalized] = distribution.version
        if pins.get(normalized) != distribution.version:
            violations.append(f"{normalized}=={distribution.version} (lock: {pins.get(normalized)})")
    return {
        "lock": Path(lock_path).relative_to(REPO_ROOT).as_posix(),
        "lock_sha256": sha256_file(lock_path),
        "installed_count": len(installed),
        "violations": sorted(violations),
        "verified": not violations,
        "installed": dict(sorted(installed.items())),
    }


def environment_identity() -> Dict[str, Any]:
    import numpy
    import scipy

    return {
        "python": sys.version,
        "implementation": platform.python_implementation(),
        "numpy": numpy.__version__,
        "scipy": scipy.__version__,
        "machine": platform.machine(),
        "platform": platform.platform(),
    }


def host_identity() -> Dict[str, Any]:
    def sysctl(name: str) -> Optional[str]:
        try:
            return subprocess.run(["sysctl", "-n", name], capture_output=True, text=True, check=True).stdout.strip()
        except (OSError, subprocess.CalledProcessError):
            return None

    return {
        "system": platform.system(),
        "release": platform.release(),
        "machine": platform.machine(),
        "cpu": sysctl("machdep.cpu.brand_string"),
        "logical_cpus": sysctl("hw.ncpu"),
        "physical_memory_bytes": sysctl("hw.memsize"),
    }


def source_file_digests(relative_paths: tuple) -> Dict[str, str]:
    return {path: sha256_file(REPO_ROOT / path) for path in relative_paths}
