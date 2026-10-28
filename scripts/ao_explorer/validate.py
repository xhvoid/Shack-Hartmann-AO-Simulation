"""Offline validator of the AO Simulation Explorer web bundle.

Usage::

    python scripts/ao_explorer/validate.py --web-dir web/ao-explorer [--series-dir DIR] [--record]

The entry ``data/current.json`` names the active 2 m dataset.  The validator
selects one of the two supported dataset contracts (``web_contract.py``: the
180-frame ``v1`` dataset and the one-second ``v2`` dataset) from the entry
and manifest schemas and refuses every other combination.  The contract, not
the manifest under test, supplies the expected frame counts, analysis window,
displayed frames, colour levels, record schemas and member roles.

Structural mode (always): the entry, the manifest and every member are
checked for size and SHA-256; every JSON reference must resolve, relative to
the JSON that defines it, to a listed member with the same size and digest
(a v2 manifest may reference the preserved previous dataset's members in
place, which are then verified byte for byte); no file in the dataset
directory may be unlisted; JSON may not contain NaN or Infinity; the
case/metrics/observation/scene/display/research semantics are checked (frame
counts, sample times, analysis windows and counts, displayed frames from the
contract's rule, atlas tile layout and bounds, shared colour limits and
scene, image units, observation parents -- wavelength, residual field,
normalization, timestamps, grid digests and propagator against the scene --
and flux bookkeeping, a recorded reason for every missing value, per-frame
series and CSV coherence, summary values recomputed from the per-frame rows
with the metrics of the mean intensity image kept apart from the mean
instantaneous metrics, v2 block summaries and playback/screen/series
metadata, each provenance's copy of the producer's record checks against
that producer's own contract -- every required check literally true, the
analysis frames and count, the diagnostics' keys and types; the window from
the checks mapping under v2 and, under v1, from the case record's hash-bound
time domain through an adapter, as the v1 provenance holds no job record --
eight research groups with quantitative content, byte-identical source
copies and source-bound extracts), and the page code's content build must
equal the one the entry records.

Raw-evidence mode (``--series-dir``): additionally binds every case to its
retained attempt directory and files (the layout is the contract's: the v1
``jobs/<job>/<attempt>`` with ``movie.npz``, or the v2
``cases/<case>/<attempt>`` with per-frame ``.npy`` stacks), checks that the
bytes of ``mean_psfs.npz`` are the file both observation parents name by
SHA-256, checks each parent's array digest against that archive's arrays
(read from the same bytes), and decodes the
residual atlas tiles at the first, burn-in and last frames to confirm they
equal the declared colour mapping of the raw maps (no axis flip, no hidden
normalization).  Without ``--series-dir`` nothing about raw arrays is
claimed; the report says so.

``--record`` writes the external validation record (bound to the manifest's
SHA-256; the manifest never hashes itself).  Exit status 0 means every check
passed; 1 lists the failures; 2 means the bundle could not be read against a
supported contract.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import math
import posixpath
import re
from pathlib import Path, PurePosixPath
import sys
from typing import Any, Dict, List, Optional, Sequence
import zipfile

import long_series
import protocol
import site_build
import web_contract
from web_contract import (
    AVERAGE_IMAGE_KEYS,
    AVERAGE_KINDS,
    CSV_COLUMNS,
    IMAGE_UNITS,
    OPD_KINDS,
    PARENT_COADDITION,
    PARENT_FIELDS,
    PARENT_NORMALIZATION,
    PARENT_RECENTERING,
    PARENT_SAMPLING,
    PER_FRAME_SERIES,
    PSF_KINDS,
    SUMMARY_KEYS,
    Contract,
    UnsupportedContract,
)


SCIENCE_WAVELENGTH_M = protocol.SCIENCE_WAVELENGTH_M
RECORD_SCHEMA = "ao-explorer.manifest-validation.v2"
_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_RGB = re.compile(r"^#[0-9a-f]{6}$")
PAIRING_STATUSES = ("reference", "paired", "different_atmosphere")
# The retained mean archive both observation parents are averaged into, under its name in the raw evidence.
MEAN_ARCHIVE = "mean_psfs.npz"
ROLES = ("uncorrected", "corrected")
# What reading a retained raw archive raises when it is missing, truncated, mis-shaped or not the declared kind of file.
RAW_READ_ERRORS = (OSError, ValueError, KeyError, IndexError, EOFError, zipfile.BadZipFile)
# Atmosphere-side images that paired cases share with the baseline (long_export stores them once).
SHARED_IMAGE_KEYS = (("images", "atmosphere", "atlas"), ("images", "psf_uncorrected", "atlas"), ("images", "psf_average_uncorrected", "image"))


class ValidationError(Exception):
    pass


def _wavelength(value: Any) -> str:
    """A recorded wavelength for a check message: numbers in metres, anything else as recorded."""

    return f"{value!r} m" if _finite(value) else f"{value!r} (not a number)"


def _strict_json(data: bytes, label: str) -> Any:
    def reject(value: str) -> Any:
        raise ValidationError(f"{label}: non-finite JSON constant {value}")

    try:
        return json.loads(data.decode("utf-8"), parse_constant=reject)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValidationError(f"{label}: invalid JSON ({exc})") from exc


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _sha_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 24), b""):
            digest.update(block)
    return digest.hexdigest()


def _png_size(data: bytes) -> List[int]:
    if data[:8] != b"\x89PNG\r\n\x1a\n":
        raise ValidationError("not a PNG")
    return [int.from_bytes(data[16:20], "big"), int.from_bytes(data[20:24], "big")]


def _finite(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _hex64(value: Any) -> bool:
    return isinstance(value, str) and bool(_HEX64.fullmatch(value))  # fullmatch: "$" alone would admit a trailing newline


def _close(a: Any, b: float, rel: float = 1e-9, absolute: float = 0.0) -> bool:
    return _finite(a) and abs(a - b) <= max(absolute, rel * max(1.0, abs(b)))


def _complete(values: Any) -> Optional[List[float]]:
    """The values as floats when every one is a finite number, else None."""

    if not isinstance(values, list) or not values or not all(_finite(v) for v in values):
        return None
    return [float(v) for v in values]


def _mean(values: Sequence[float]) -> float:
    return sum(values) / len(values)


def _std(values: Sequence[float]) -> float:
    mean = _mean(values)
    return math.sqrt(sum((v - mean) ** 2 for v in values) / len(values))


# The v1 provenance holds the producer's ``checks`` mapping but no producer job record; the window those checks were
# made on is the recorded time domain of the hash-bound case record, in these fields (review R24 follow-up).
V1_TIME_DOMAIN_FIELDS = ("frames", "burn_in_frames", "analysis_window", "analysis_count")


def v1_window_record(time_domain: Any) -> Dict[str, Any]:
    """Adapter: a v1 case record's recorded time domain as the shared rule's job-record window fields.

    The v1 producer contract (``web_contract.producer_checks_v1``) reads its analysis window from a job record's
    ``burn_in`` and ``n_steps``.  Historical v1 provenance carries no such record; the observed window lives in the
    case record's ``time_domain`` (``frames``, ``burn_in_frames``, ``analysis_window``, ``analysis_count``).  The
    recorded ``burn_in_frames`` and ``frames`` are handed to the rule under the job-record names exactly as recorded
    -- no coercion, no default, no expected constant filled in -- so the rule judges the observed values (exact ints
    equal to the contract window, the count by their difference).  This is a view of the recorded values, not a job
    record present in the provenance; :func:`v1_window_consistent` judges the other two recorded fields against them.
    """

    record = time_domain if isinstance(time_domain, dict) else {}
    return {"burn_in": record.get("burn_in_frames"), "n_steps": record.get("frames")}


def v1_window_consistent(time_domain: Any) -> bool:
    """Whether a v1 case record's recorded window and count are exact ints consistent with its burn-in and frame count.

    ``analysis_window`` must be the list ``[burn_in_frames, frames]`` and ``analysis_count`` must equal
    ``frames - burn_in_frames``, every value an exact ``int`` (a bool, float or string is not one).  Which window that
    is -- the contract's -- is the shared rule's judgement through :func:`v1_window_record`.
    """

    record = time_domain if isinstance(time_domain, dict) else {}
    frames, burn_in, window, count = (record.get(key) for key in V1_TIME_DOMAIN_FIELDS)
    exact = type(frames) is int and type(burn_in) is int and type(count) is int
    return (exact and isinstance(window, list) and len(window) == 2 and all(type(value) is int for value in window)
            and window == [burn_in, frames] and count == frames - burn_in)


class Dataset:
    """One dataset directory: its manifest and members, verified against the manifest when read."""

    def __init__(self, checker: "Checker", base: Path, manifest: Dict[str, Any], manifest_sha256: str, label: str) -> None:
        self.checker = checker
        self.base = Path(base)
        self.manifest = manifest
        self.manifest_sha256 = manifest_sha256
        self.label = label
        self.members: Dict[str, Dict[str, Any]] = {}
        for item in manifest.get("members", []):
            if isinstance(item, dict) and isinstance(item.get("path"), str):
                self.members[item["path"]] = dict(item)
        self.verified: Dict[str, bool] = {}

    @property
    def name(self) -> str:
        return self.base.name

    def _prefix(self) -> str:
        return "" if self.label == "active" else f"{self.label}: "

    def verify(self, path: str) -> Optional[Dict[str, Any]]:
        """The member with its bytes loaded; its size and SHA-256 are checked once (None when it is not listed or missing)."""

        item = self.members.get(path)
        if item is None:
            return None
        if path not in self.verified:
            file_path = self.base / path
            if not file_path.is_file():
                self.checker.check(False, f"{self._prefix()}member {path} is missing", area="members")
                self.verified[path] = False
                return None
            data = file_path.read_bytes()
            ok = len(data) == item.get("bytes") and _sha(data) == item.get("sha256")
            self.checker.check(ok, f"{self._prefix()}member {path} size and SHA-256", area="members")
            item["data"] = data
            self.verified[path] = ok
        return item if "data" in item else None

    def verify_all(self) -> None:
        for path in list(self.members):
            self.verify(path)


class Checker:
    def __init__(self, web_dir: Path) -> None:
        self.web_dir = Path(web_dir)
        self.failures: List[str] = []
        self.passed: List[str] = []
        self.areas: Dict[str, Dict[str, int]] = {}
        self.contract: Optional[Contract] = None
        self.entry: Dict[str, Any] = {}
        self.active: Optional[Dataset] = None
        self.previous: Optional[Dataset] = None
        self.referenced: Dict[str, set] = {}
        self.propagators: set = set()
        self.accumulators: set = set()
        self.code_build: Optional[str] = None
        self.research_sources_changed: List[str] = []

    # Bookkeeping -----------------------------------------------------------------

    def check(self, condition: bool, message: str, *, area: str = "semantics") -> bool:
        (self.passed if condition else self.failures).append(message)
        counts = self.areas.setdefault(area, {"passed": 0, "failed": 0})
        counts["passed" if condition else "failed"] += 1
        return bool(condition)

    @property
    def c(self) -> Contract:
        assert self.contract is not None
        return self.contract

    @property
    def manifest(self) -> Dict[str, Any]:
        assert self.active is not None
        return self.active.manifest

    # Bundle structure -------------------------------------------------------

    def load_entry(self) -> Dict[str, Any]:
        entry_path = self.web_dir / "data" / "current.json"
        entry = _strict_json(entry_path.read_bytes(), "current.json")
        if not isinstance(entry, dict) or not isinstance(entry.get("manifest"), str):
            raise ValidationError("current.json is not an entry object naming a manifest")
        manifest_path = (entry_path.parent / entry["manifest"]).resolve()
        data_root = entry_path.parent.resolve()
        if manifest_path.parent.parent != data_root or manifest_path.name != "manifest.json":
            raise ValidationError("the entry's manifest must be data/<dataset-id>/manifest.json")
        if not manifest_path.is_file():
            raise ValidationError(f"the manifest {entry['manifest']} is missing")
        data = manifest_path.read_bytes()
        if len(data) != entry.get("manifest_bytes") or _sha(data) != entry.get("manifest_sha256"):
            raise ValidationError("the manifest does not match the entry's size/SHA-256")
        manifest = _strict_json(data, "manifest.json")
        if not isinstance(manifest, dict):
            raise ValidationError("manifest.json is not an object")
        contract = web_contract.select(entry.get("schema"), manifest.get("schema"))
        if manifest.get("dataset_id") != entry.get("dataset_id"):
            raise ValidationError(f"manifest dataset_id {manifest.get('dataset_id')!r} differs from the entry's {entry.get('dataset_id')!r}")
        if manifest.get("web_schema_version") != contract.web_schema_version:
            raise UnsupportedContract(
                f"unsupported schema combination: manifest {contract.manifest_schema!r} declares web_schema_version "
                f"{manifest.get('web_schema_version')!r}; the {contract.name} contract requires {contract.web_schema_version!r}")
        if manifest_path.parent.name != entry["dataset_id"]:
            raise ValidationError(f"the manifest directory {manifest_path.parent.name!r} is not named after the dataset id {entry['dataset_id']!r}")
        if not isinstance(manifest.get("members"), list) or not manifest["members"]:
            raise ValidationError("the manifest lists no members")
        self.contract = contract
        self.entry = entry
        self.active = Dataset(self, manifest_path.parent, manifest, entry["manifest_sha256"], "active")
        self.check(True, f"entry {entry['schema']} and manifest {contract.manifest_schema} select the supported {contract.name} contract ({contract.web_schema_version})", area="entry")
        if contract.previous_dataset_required:
            self.load_previous_dataset()
        return manifest

    def load_previous_dataset(self) -> None:
        previous = self.manifest.get("previous_dataset")
        if not isinstance(previous, dict) or not isinstance(previous.get("dataset_id"), str) or not _hex64(previous.get("manifest_sha256")):
            raise ValidationError(f"the {self.c.name} manifest must name the preserved previous dataset and its manifest SHA-256")
        previous_id = previous["dataset_id"]
        base = self.web_dir / "data" / previous_id
        if previous_id == self.active.name or not (base / "manifest.json").is_file():
            raise ValidationError(f"the preserved previous dataset {previous_id} is missing under data/")
        data = (base / "manifest.json").read_bytes()
        self.check(_sha(data) == previous["manifest_sha256"], f"previous dataset {previous_id}: manifest SHA-256 equals the recorded {previous['manifest_sha256'][:12]}", area="entry")
        manifest = _strict_json(data, f"{previous_id}/manifest.json")
        expected = web_contract.PREVIOUS_DATASET_CONTRACT
        self.check(isinstance(manifest, dict) and manifest.get("schema") == expected.manifest_schema and manifest.get("dataset_id") == previous_id,
                   f"previous dataset {previous_id}: a {expected.manifest_schema} manifest naming itself", area="entry")
        self.check(isinstance(previous.get("relation"), str) and "preserved unchanged" in previous["relation"], f"previous dataset {previous_id}: relation declares it preserved unchanged", area="entry")
        self.previous = Dataset(self, base, manifest if isinstance(manifest, dict) else {}, previous["manifest_sha256"], f"previous dataset {previous_id}")

    def verify_members(self) -> None:
        active = self.active
        assert active is not None
        active.verify_all()
        listed = set(active.members) | {"manifest.json"}
        on_disk = {p.relative_to(active.base).as_posix() for p in active.base.rglob("*") if p.is_file()}
        self.check(on_disk <= listed, f"no unlisted files in the dataset directory ({sorted(on_disk - listed)[:5]})", area="members")
        bad_roles = sorted(path for path, item in active.members.items() if item.get("role") not in self.c.member_roles)
        self.check(not bad_roles, f"member roles belong to the {self.c.name} contract ({bad_roles[:5]})", area="members")
        bad_records = sorted(path for path, item in active.members.items()
                             if not (isinstance(item.get("bytes"), int) and _hex64(item.get("sha256")) and isinstance(item.get("media_type"), str)))
        self.check(not bad_records, f"every member records an integer size, a SHA-256 and a media type ({bad_records[:5]})", area="members")
        siblings = sorted(p.name for p in active.base.parent.iterdir() if p.is_dir())
        expected = sorted({active.name} | ({self.previous.name} if self.previous is not None else set()))
        self.check(siblings == expected, f"dataset directories under data/ are exactly {expected} ({siblings})", area="members")

    def json_member(self, relative: str, dataset: Optional[Dataset] = None) -> Any:
        dataset = dataset or self.active
        assert dataset is not None
        item = dataset.verify(relative)
        if item is None:
            raise ValidationError(f"{dataset.label}: {relative} is not a listed, readable member")
        if item.get("media_type") != "application/json":
            raise ValidationError(f"{relative} is not JSON")
        return _strict_json(item["data"], relative)

    def resolve(self, ref: Dict[str, Any], defining: str, dataset: Optional[Dataset] = None) -> Optional[Dict[str, Any]]:
        """The member a reference names, checked against the reference's size, digest and media type.

        References are relative to the JSON that defines them.  A reference that
        climbs out of the dataset is refused, except, under a contract that
        preserves the previous dataset, one that names that dataset's member in
        place; that member is then verified byte for byte against its own
        manifest.
        """

        dataset = dataset or self.active
        assert dataset is not None
        href = ref.get("href")
        if not isinstance(href, str) or "://" in href or href.startswith("/"):
            raise ValidationError(f"{defining}: non-relative reference {href!r}")
        target = posixpath.normpath(posixpath.join(posixpath.dirname(defining), href))
        owner = dataset
        if target.startswith("../") or target == "..":
            rest = target[3:]
            sibling, _, inner = rest.partition("/")
            if dataset is not self.active or self.previous is None or rest.startswith("../") or sibling != self.previous.name or not inner:
                raise ValidationError(f"{defining}: {href} leaves the dataset")
            owner, target = self.previous, inner
        item = owner.verify(target)
        ok = item is not None and item.get("bytes") == ref.get("bytes") and item.get("sha256") == ref.get("sha256") and item.get("media_type") == ref.get("media_type", item.get("media_type"))
        where = defining if owner is dataset else f"{defining} (in place, {owner.label})"
        self.check(ok, f"{where}: reference {href} resolves to a matching member", area="references")
        self.referenced.setdefault(owner.label, set()).add(target)
        return item if ok else None

    def walk_refs(self, value: Any, defining: str, dataset: Optional[Dataset] = None) -> None:
        if isinstance(value, dict):
            if set(value) >= {"href", "bytes", "sha256"}:
                self.resolve(value, defining, dataset)
            for item in value.values():
                self.walk_refs(item, defining, dataset)
        elif isinstance(value, list):
            for item in value:
                self.walk_refs(item, defining, dataset)

    # Manifest-level semantics -------------------------------------------------

    def check_manifest(self) -> None:
        m, c = self.manifest, self.c
        self.check(m.get("default_case") == protocol.DEFAULT_CASE, "default case is the baseline", area="manifest")
        cases = m.get("cases") if isinstance(m.get("cases"), dict) else {}
        self.check(sorted(cases) == sorted(case["id"] for case in protocol.CASES), "manifest lists exactly the eight frozen cases", area="manifest")
        self.check(m.get("groups") == protocol.GROUPS, "scenario groups equal the frozen groups (no extra combinations)", area="manifest")
        for case_id, item in cases.items():
            frozen = next((case for case in protocol.CASES if case["id"] == case_id), None)
            self.check(frozen is not None and isinstance(item, dict) and item.get("label") == frozen["label"] and item.get("group") == frozen["group"],
                       f"{case_id}: manifest label and group equal the frozen case", area="manifest")
        missing = [key for key in c.manifest_keys if key not in m]
        self.check(not missing, f"manifest carries the {c.name} contract's top-level keys ({missing})", area="manifest")
        self.walk_refs({key: m[key] for key in c.manifest_ref_keys if key in m}, "manifest.json")
        series = m.get("series") if isinstance(m.get("series"), dict) else {}
        series_id = series.get("series_id")
        dataset_id = str(m.get("dataset_id", ""))
        self.check(isinstance(series_id, str) and dataset_id.startswith(f"{series_id}-"), "dataset id is derived from the series id", area="manifest")
        self.check(_hex64(series.get("plan_sha256")), "series plan SHA-256 recorded", area="manifest")
        results = m.get("results") if isinstance(m.get("results"), dict) else {}
        if c.research_in_dataset:
            self.check(isinstance(results.get("href"), str) and not results["href"].startswith(".."), "Research Results are a member of this dataset", area="manifest")
        else:
            previous_name = self.previous.name if self.previous is not None else None
            self.check(isinstance(results.get("href"), str) and results["href"].startswith(f"../{previous_name}/research/"),
                       "Research Results are referenced in place from the preserved previous dataset", area="manifest")
            self.check(isinstance(m.get("results_origin"), str) and previous_name is not None and previous_name in m["results_origin"], "results_origin names the previous dataset", area="manifest")
        if c.time_domain_in_manifest:
            self.check_time_domain(m.get("time_domain"), "manifest")
        if c.playback_required:
            self.check_playback(m.get("playback"))
        if c.screen_grid_size is not None:
            self.check_screen(m.get("screen"))
            production = series.get("production_sha256")
            self.check(_hex64(production) and series_id == long_series.series_id_for({"sha256": production}),
                       "series id follows the producer's rule (series-2m1000-s624-<production identity[:12]>)", area="manifest")
            key = dataset_id[len(series_id) + 2:] if isinstance(series_id, str) else ""
            self.check(isinstance(series_id, str) and dataset_id == f"{series_id}-e{key}" and len(key) == 12 and all(ch in "0123456789abcdef" for ch in key),
                       "dataset id is the series id with a 12-hex export key", area="manifest")

    def check_time_domain(self, t: Any, where: str) -> None:
        c = self.c
        if not isinstance(t, dict):
            self.check(False, f"{where}: time domain is an object", area="time_domain")
            return
        self.check(t.get("frames") == c.frames and t.get("burn_in_frames") == c.burn_in, f"{where}: {c.frames} frames, burn-in {c.burn_in}", area="time_domain")
        self.check(t.get("frame_rate_hz") == c.frame_rate_hz and t.get("frame_period_s") == c.frame_period_s, f"{where}: frame rate {c.frame_rate_hz:g} Hz, period {c.frame_period_s:g} s", area="time_domain")
        self.check(t.get("analysis_window") == list(c.analysis_window) and t.get("analysis_count") == c.analysis_count,
                   f"{where}: analysis window [{c.burn_in}, {c.frames}), {c.analysis_count} samples", area="time_domain")
        self.check(t.get("sampling") == web_contract.SAMPLING_RULE, f"{where}: sampling rule is one atmosphere sample per frame at its start", area="time_domain")
        if not c.time_domain_in_manifest:
            return
        last_time = c.display_time(c.last_frame)
        times = t.get("sample_times_s")
        self.check(t.get("frame_indices") == [0, c.last_frame] and isinstance(times, list) and len(times) == 2 and times[0] == 0.0 and _close(times[1], last_time, 1e-12)
                   and t.get("physical_interval_s") == [0.0, c.frames * c.frame_period_s],
                   f"{where}: frame indices, sample times and physical interval cover frames 0-{c.last_frame}", area="time_domain")
        self.check(t.get("startup_exclusion_frames") == c.burn_in, f"{where}: startup exclusion equals the burn-in ({c.burn_in} frames)", area="time_domain")
        self.check(t.get("display_indices") == list(c.display_indices) and t.get("display_count") == c.display_count,
                   f"{where}: display indices equal the frozen rule ({c.display_count} unique, incl. 0, {c.burn_in}, {c.last_frame})", area="time_domain")
        shown = t.get("display_times_s")
        self.check(isinstance(shown, list) and len(shown) == c.display_count and all(_close(time, c.display_time(index), 1e-12) for time, index in zip(shown, c.display_indices)),
                   f"{where}: display times are the frame starts", area="time_domain")
        self.check(t.get("display_rule") == c.display_rule, f"{where}: display rule text is the exporter's", area="time_domain")
        self.check(t.get("retained_full_precision_frames") == c.frames, f"{where}: all {c.frames} frames retained at full precision", area="time_domain")
        self.check(isinstance(t.get("analysis_rule"), str) and "predeclared" in t["analysis_rule"], f"{where}: analysis window declared as predeclared", area="time_domain")

    def check_playback(self, p: Any) -> None:
        c = self.c
        if not isinstance(p, dict):
            self.check(False, "playback metadata is an object", area="playback")
            return
        interval = p.get("interval_s")
        self.check(isinstance(interval, list) and len(interval) == 2 and interval[0] == 0.0 and _close(interval[1], c.frames * c.frame_period_s, 1e-12),
                   f"playback interval is the physical interval [0, {c.frames * c.frame_period_s:.3f}) s", area="playback")
        durations = p.get("durations_s")
        self.check(durations == list(c.playback_durations_s) and all(_finite(d) and d > 0 for d in c.playback_durations_s),
                   f"playback durations are the exporter's {', '.join(str(d) for d in c.playback_durations_s)} s", area="playback")
        self.check(p.get("default_duration_s") == c.playback_default_s and isinstance(durations, list) and c.playback_default_s in durations, "playback default duration is listed", area="playback")
        self.check(p.get("reduced_motion_duration_s") == max(c.playback_durations_s), "reduced-motion duration is the slowest listed", area="playback")
        self.check(p.get("loop_default") is False, "playback does not loop by default", area="playback")
        self.check(p.get("interpolation") == "none", "playback does not interpolate", area="playback")

    def check_screen(self, s: Any) -> None:
        c = self.c
        if not isinstance(s, dict):
            self.check(False, "screen metadata is an object", area="screen")
            return
        self.check(s.get("generated_screen_px") == c.screen_grid_size and s.get("atmosphere_model") == "native_frozen_flow_v2",
                   f"screen is a native_frozen_flow_v2 screen generated at {c.screen_grid_size} px", area="screen")
        pupil, delta, wind = s.get("pupil_px"), s.get("delta_m"), s.get("wind_m_per_s")
        ok_inputs = isinstance(pupil, int) and _finite(delta) and delta > 0 and isinstance(wind, list) and len(wind) == 2 and all(_finite(v) for v in wind)
        budget = (c.screen_grid_size - pupil) / 2 if ok_inputs else float("nan")
        speed = math.hypot(*wind) if ok_inputs else float("nan")
        self.check(ok_inputs and _close(s.get("travel_budget_px"), budget), "screen travel budget is (screen - pupil) / 2 pixels", area="screen")
        supported = budget * delta / speed if ok_inputs and speed > 0 else float("nan")
        self.check(ok_inputs and _close(s.get("supported_travel_duration_s"), supported), "supported travel duration is budget x pixel spacing / wind speed", area="screen")
        requested = s.get("max_requested_travel_px")
        self.check(ok_inputs and _finite(requested) and requested <= budget and _close(s.get("margin_px"), budget - requested, 1e-9, 1e-9),
                   "the requested travel stays within the budget with the recorded margin", area="screen")
        self.check(ok_inputs and supported >= c.frames * c.frame_period_s, "the screen supports the whole physical interval", area="screen")

    # Scene, display -------------------------------------------------------------

    def check_scene(self) -> Dict[str, Any]:
        scene_export = self.json_member("scene/scene.json")
        self.walk_refs(scene_export, "scene/scene.json")
        self.check(scene_export.get("schema") == web_contract.SCENE_EXPORT_SCHEMA, "scene export schema", area="scene")
        scene = scene_export["scene"]
        weights = [source["weight"] for source in scene["sources"]]
        self.check(scene["schema"] == protocol.SCENE_SCHEMA, "scene schema", area="scene")
        self.check(abs(scene["total_flux"] - 1.0) <= 1e-15 and abs(weights[0] - 2 / 3) <= 1e-15 and abs(weights[1] - 1 / 3) <= 1e-15, "scene weights 2/3, 1/3 and total flux 1", area="scene")
        primary, secondary = scene["sources"]
        self.check(primary["angle_xy_rad"] == [0.0, 0.0], "primary at exact angular zero", area="scene")
        self.check(secondary["index_yx"][0] == primary["index_yx"][0] and secondary["index_yx"][1] - primary["index_yx"][1] == protocol.SCENE_SECONDARY_OFFSET_X_CELLS, "secondary six native x cells towards +x at the same y", area="scene")
        self.check(secondary["angle_xy_rad"][0] > 0.0 and secondary["angle_xy_rad"][1] == 0.0, "secondary at positive x angle", area="scene")
        self.check(scene["wavelength_m"] == SCIENCE_WAVELENGTH_M, f"scene wavelength {_wavelength(scene['wavelength_m'])} is the science wavelength {_wavelength(SCIENCE_WAVELENGTH_M)}", area="scene")
        grid = scene["grid"]
        self.check(_hex64(grid.get("x_angle_rad_sha256")) and _hex64(grid.get("y_angle_rad_sha256")) and _hex64(scene.get("grid_id")) and _hex64(scene.get("scene_id"))
                   and isinstance(grid.get("shape_yx"), list) and len(grid["shape_yx"]) == 2, "scene records its grid digests, grid id and scene id", area="scene")
        self.check(0 <= grid["x_zero_index"] < grid["shape_yx"][1] and primary["index_yx"] == [grid["y_zero_index"], grid["x_zero_index"]], "primary sits on the grid's zero-angle cell", area="scene")
        if self.previous is not None:
            previous_scene = self.json_member("scene/scene.json", self.previous)
            self.check(previous_scene.get("scene") == scene, "binary scene record equals the preserved previous dataset's (shared grid identity)", area="scene")
        return scene

    def check_display(self, scene: Dict[str, Any]) -> Dict[str, Any]:
        c = self.c
        display = self.json_member("display.json")
        self.check(display.get("schema") == c.display_schema and display.get("revision") == c.display_schema, f"display schema and revision are the {c.name} contract's", area="display")
        opd, psf = display["opd"], display["psf"]
        self.check(len(opd["lut_rgb_hex"]) == c.opd_levels and len(psf["lut_rgb_hex"]) == 256, f"display lookup tables have {c.opd_levels} OPD and 256 PSF entries", area="display")
        self.check(all(isinstance(h, str) and _RGB.match(h) for h in opd["lut_rgb_hex"] + psf["lut_rgb_hex"]), "lookup table entries are #rrggbb colours", area="display")
        if c.opd_exterior_index is not None:
            rule = str(opd.get("code_rule", ""))
            self.check(opd.get("levels") == c.opd_levels and f"index {c.opd_exterior_index}" in rule and f"* {c.opd_levels - 1}" in rule,
                       f"OPD code rule declares {c.opd_levels} display codes and the transparent exterior index {c.opd_exterior_index}", area="display")
        limit, raw = opd.get("limit_m"), opd.get("raw_max_percentile_m")
        quantum = web_contract.OPD_LIMIT_QUANTUM_M
        self.check(_finite(limit) and _finite(raw) and 0.0 < raw <= limit < raw + quantum + 1e-15 and abs(limit / quantum - round(limit / quantum)) < 1e-6,
                   "OPD display limit is the recorded percentile rounded up to the 50 nm quantum", area="display")
        self.check(opd.get("scale") == "linear, symmetric about zero" and opd.get("colormap") == web_contract.OPD_COLORMAP, "OPD display is linear, symmetric and uses the declared colormap", area="display")
        decades = web_contract.PSF_LOG_DECADES
        self.check(psf.get("decades") == decades and psf.get("mapping") == f"log10(I / I_ideal_peak) clipped to [-{decades:g}, 0]" and _finite(psf.get("ideal_peak_cell_flux"))
                   and psf["ideal_peak_cell_flux"] > 0 and psf.get("colormap") == web_contract.PSF_COLORMAP and "no per-image peak normalization" in str(psf.get("normalization", "")),
                   "PSF display scale is the common logarithmic scale against the ideal peak", area="display")
        window = display.get("psf_window", {})
        half = web_contract.PSF_DISPLAY_HALF_WIDTH_CELLS
        grid = scene["grid"]
        self.check(window.get("x_index") == [grid["x_zero_index"] - half, grid["x_zero_index"] + half] and window.get("y_index") == [grid["y_zero_index"] - half, grid["y_zero_index"] + half],
                   f"PSF display window is the {2 * half} x {2 * half} crop about the scene grid's zero angle", area="display")
        return display

    # Cases ---------------------------------------------------------------------

    @staticmethod
    def _series(metrics: Dict[str, Any], key: str) -> Any:
        pf = metrics["per_frame"]
        return pf[key]["values"] if isinstance(pf.get(key), dict) else pf.get(key)

    def check_case(self, case_id: str, scene: Dict[str, Any], display: Dict[str, Any]) -> Dict[str, Any]:
        c = self.c
        protocol_case = protocol.case_by_id(case_id)
        case_ref = self.manifest["cases"][case_id]["case"]
        case_item = self.resolve(case_ref, "manifest.json")
        ref_path = f"cases/{case_id}/case.json"
        if case_item is not None:
            resolved = posixpath.normpath(case_ref["href"])
            self.check(resolved == ref_path, f"{case_id}: case record lives at {ref_path}", area="case")
            ref_path = resolved
        case = self.json_member(ref_path)
        prefix = str(PurePosixPath(ref_path).parent)
        self.walk_refs(case, ref_path)
        self.check(case.get("schema") == c.case_schema and case.get("case_id") == case_id, f"{case_id}: case schema and id", area="case")
        self.check(case.get("label") == protocol_case["label"] and case.get("group") == protocol_case["group"] and case.get("question") == protocol_case["question"]
                   and case.get("override") == protocol_case["override"], f"{case_id}: label, group, question and override equal the frozen case", area="case")
        parameters = case.get("effective_parameters", {})
        self.check(parameters.get("explorer_science_wavelength_m") == SCIENCE_WAVELENGTH_M,
                   f"{case_id}: science wavelength {_wavelength(parameters.get('explorer_science_wavelength_m'))} is {_wavelength(SCIENCE_WAVELENGTH_M)}", area="case")
        self.check(parameters.get("n_steps") == c.frames and parameters.get("frame_rate_hz") == c.frame_rate_hz and parameters.get("root_seed") == protocol.ROOT_SEED,
                   f"{case_id}: effective parameters record {c.frames} frames at {c.frame_rate_hz:g} Hz with root seed {protocol.ROOT_SEED}", area="case")
        t = case["time_domain"]
        movie = list(c.display_indices)
        self.check_time_domain(t, case_id)
        self.check(t.get("movie_indices") == movie, f"{case_id}: movie indices equal the frozen rule ({c.display_count} unique, incl. 0, {c.burn_in}, {c.last_frame})", area="time_domain")
        movie_times = t.get("movie_times_s")
        self.check(isinstance(movie_times, list) and len(movie_times) == c.display_count and all(_close(time, c.display_time(index), 1e-12) for time, index in zip(movie_times, movie)),
                   f"{case_id}: movie times are the frame starts", area="time_domain")
        if c.time_domain_in_manifest:
            without_movie = {key: value for key, value in t.items() if key not in ("movie_indices", "movie_times_s")}
            self.check(without_movie == self.manifest.get("time_domain"), f"{case_id}: case time domain equals the manifest time domain", area="time_domain")
        self.check(case.get("validation", {}).get("producer_checks_passed") is True, f"{case_id}: the producer's record checks passed", area="case")

        images = case["images"]
        limits = None
        for key, unit in IMAGE_UNITS.items():
            self.check(images[key].get("unit") == unit, f"{case_id}: {key} unit {images[key].get('unit')!r} is the supported {unit!r}", area="images")
        psf_scale = display["psf"]
        for key in PSF_KINDS + AVERAGE_KINDS:
            scale = images[key].get("scale", {})
            self.check(all(scale.get(name) == psf_scale[name] for name in ("mapping", "ideal_peak_cell_flux", "normalization", "colormap")), f"{case_id}: {key} uses the common intensity display scale", area="images")
            self.check(images[key].get("window") == display.get("psf_window"), f"{case_id}: {key} declares the common PSF display window", area="images")
        pupil_px = parameters.get("pupil_pixels")
        half = web_contract.PSF_DISPLAY_HALF_WIDTH_CELLS
        columns = web_contract.ATLAS_COLUMNS
        for key in OPD_KINDS + PSF_KINDS:
            image = images[key]
            atlas = self.resolve(image["atlas"], ref_path)
            rectangles = image.get("rectangles_xywh", [])
            expected_tile = [pupil_px, pupil_px] if key in OPD_KINDS else [2 * half, 2 * half]
            if atlas is None:
                self.check(False, f"{case_id}: {key} atlas tiles cover the {c.display_count} movie frames inside the PNG", area="images")
                continue
            width, height = _png_size(atlas["data"])
            well_formed = isinstance(rectangles, list) and all(isinstance(r, list) and len(r) == 4 and all(isinstance(v, int) for v in r) for r in rectangles)
            inside = well_formed and all(x >= 0 and y >= 0 and x + w <= width and y + h <= height for x, y, w, h in rectangles)
            self.check(len(rectangles) == c.display_count and inside and image.get("frame_indices") == movie, f"{case_id}: {key} atlas tiles cover the {c.display_count} movie frames inside the PNG", area="images")
            tile_w, tile_h = expected_tile
            layout = well_formed and all(r == [(index % columns) * tile_w, (index // columns) * tile_h, tile_w, tile_h] for index, r in enumerate(rectangles))
            self.check(image.get("tile_px") == expected_tile and layout, f"{case_id}: {key} tiles are {tile_w} x {tile_h} px in the {columns}-column atlas layout", area="images")
            if key in OPD_KINDS:
                piston = image.get("display_piston_nm")
                self.check(isinstance(piston, list) and len(piston) == c.display_count and all(_finite(v) for v in piston) and "piston" in image, f"{case_id}: {key} records the display piston per movie frame", area="images")
                if limits is None:
                    limits = image.get("color_limits_nm")
                self.check(isinstance(limits, list) and image.get("color_limits_nm") == limits and len(limits) == 2 and _finite(limits[1]) and limits[0] == -limits[1]
                           and abs(limits[1] - display["opd"]["limit_m"] * 1e9) < 1e-6, f"{case_id}: {key} uses the common symmetric OPD limits", area="images")
                self.check(image.get("colormap") == display["opd"]["colormap"] and "transparent" in str(image.get("mask", "")), f"{case_id}: {key} uses the OPD colormap with a transparent pupil exterior", area="images")
                if c.opd_exterior_index is not None:
                    self.check(f"index {c.opd_exterior_index}" in str(image.get("encoding", "")), f"{case_id}: {key} encoding names the exterior palette index", area="images")
        for key in AVERAGE_KINDS:
            image = images[key]
            self.check(image.get("sample_count") == c.analysis_count, f"{case_id}: {key} is the {c.analysis_count}-sample average", area="images")
            if c.time_domain_in_manifest:
                self.check(image.get("window_frames") == list(c.analysis_window), f"{case_id}: {key} names the analysis window", area="images")

        members = case.get("members", {})
        expected_members = {"metrics": "metrics.json", "metrics_csv": "metrics.csv", "config": "config.json", "provenance": "provenance.json", "observation": "observation.json"}
        self.check(all(isinstance(members.get(key), dict) and posixpath.normpath(str(members[key].get("href", ""))) == name for key, name in expected_members.items()),
                   f"{case_id}: case names its metrics, CSV, config, provenance and observation members", area="case")
        metrics = self.json_member(f"{prefix}/metrics.json")
        self.check_metrics(case_id, metrics)
        self.check_csv(case_id, metrics, self.active.verify(f"{prefix}/metrics.csv"))
        observation = self.json_member(f"{prefix}/observation.json")
        self.walk_refs(observation, f"{prefix}/observation.json")
        run_hashes = self.check_observation(case_id, observation, scene, psf_scale)
        config = self.json_member(f"{prefix}/config.json")
        self.check_config(case_id, config, case, protocol_case)
        provenance = self.json_member(f"{prefix}/provenance.json")
        self.check_provenance(case_id, provenance, config, run_hashes, case)
        self.check_mean_archive_binding(case_id, observation, provenance)
        self.check_pairing(case_id, case, protocol_case)
        return {"case": case, "metrics": metrics, "observation": observation, "provenance": provenance, "prefix": prefix}

    def check_metrics(self, case_id: str, metrics: Dict[str, Any]) -> None:
        c = self.c
        self.check(metrics.get("schema") == c.metrics_schema and metrics.get("case_id") == case_id, f"{case_id}: metrics schema and id", area="metrics")
        pf = metrics["per_frame"]
        self.check(pf.get("frame_index") == list(range(c.frames)), f"{case_id}: metrics cover frames 0-{c.last_frame}", area="metrics")
        times = pf.get("time_s")
        self.check(isinstance(times, list) and len(times) == c.frames and all(_close(time, index * c.frame_period_s, 1e-12) for index, time in enumerate(times)),
                   f"{case_id}: metrics sample times are k / {c.frame_rate_hz:g} s", area="metrics")
        for key in PER_FRAME_SERIES:
            values = pf[key]["values"]
            self.check(len(values) == c.frames and all(v is None or _finite(v) for v in values), f"{case_id}: {key} has {c.frames} finite-or-null values", area="metrics")
            reasons = pf[key]["null_reasons"]
            nulls = {str(index) for index, value in enumerate(values) if value is None}
            self.check(set(reasons) == nulls and all(isinstance(reason, str) and reason.strip() for reason in reasons.values()), f"{case_id}: {key} has a recorded reason for every missing value, and only for those", area="metrics")
        usable = pf.get("reconstruction_usable")
        self.check(isinstance(usable, list) and len(usable) == c.frames and all(isinstance(v, bool) for v in usable), f"{case_id}: reconstruction_usable has {c.frames} boolean values", area="metrics")
        clipping = metrics.get("display_clipping", {})
        for kind in OPD_KINDS + PSF_KINDS:
            rows = clipping.get(kind)
            self.check(isinstance(rows, list) and len(rows) == c.display_count and all(isinstance(r, dict) and r and all(_finite(v) and 0.0 <= v <= 1.0 for v in r.values()) for r in rows),
                       f"{case_id}: display clipping recorded for the {c.display_count} displayed {kind} frames", area="metrics")
        if c.metrics_display_indices:
            self.check(metrics.get("display_indices") == list(c.display_indices), f"{case_id}: metrics display indices equal the frozen rule", area="metrics")
        summary = metrics["summary"]
        self.check(summary.get("window") == list(c.analysis_window) and summary.get("sample_count") == c.analysis_count, f"{case_id}: summary window", area="metrics")
        self.check(all(key in summary for key in SUMMARY_KEYS), f"{case_id}: summary carries every declared quantity", area="metrics")
        start, stop = c.analysis_window
        window = {key: _complete(pf[key]["values"][start:stop]) for key in PER_FRAME_SERIES}
        self.check(all(values is not None and len(values) == c.analysis_count for values in window.values()), f"{case_id}: per-frame rows in the analysis window are complete", area="metrics")
        residual = window["residual_rms_nm"]
        if residual is not None:
            self.check(_close(summary.get("mean_residual_rms_nm"), _mean(residual)), f"{case_id}: mean residual recomputed from rows", area="metrics")
            rms = math.sqrt(sum(v * v for v in residual) / len(residual))
            self.check(_close(summary.get("root_mean_square_residual_nm"), rms), f"{case_id}: root-mean-square residual recomputed from rows", area="metrics")
        if window["atmosphere_rms_nm"] is not None:
            self.check(_close(summary.get("mean_atmosphere_rms_nm"), _mean(window["atmosphere_rms_nm"])), f"{case_id}: mean atmosphere RMS recomputed from rows", area="metrics")
        if window["peak_strehl_corrected"] is not None:
            self.check(_close(summary.get("mean_instantaneous_peak_strehl_corrected"), _mean(window["peak_strehl_corrected"]), 0.0, 1e-12), f"{case_id}: mean instantaneous Strehl recomputed from rows", area="metrics")
        if window["peak_strehl_uncorrected"] is not None:
            self.check(_close(summary.get("mean_instantaneous_peak_strehl_uncorrected"), _mean(window["peak_strehl_uncorrected"]), 0.0, 1e-12), f"{case_id}: mean instantaneous uncorrected Strehl recomputed from rows", area="metrics")
        if window["valid_measurement_fraction"] is not None:
            valid = window["valid_measurement_fraction"]
            self.check(_close(summary.get("mean_valid_measurement_fraction"), _mean(valid), 0.0, 1e-12) and _close(summary.get("min_valid_measurement_fraction"), min(valid), 0.0, 1e-12),
                       f"{case_id}: valid-measurement fractions recomputed from rows", area="metrics")
        if window["dm_saturation_fraction"] is not None:
            saturation = window["dm_saturation_fraction"]
            self.check(_close(summary.get("mean_dm_saturation_fraction"), _mean(saturation), 0.0, 1e-12) and _close(summary.get("max_dm_saturation_fraction"), max(saturation), 0.0, 1e-12),
                       f"{case_id}: DM saturation mean and maximum recomputed from rows", area="metrics")
        if isinstance(usable, list) and len(usable) == c.frames:
            fraction = sum(1 for v in usable[start:stop] if v is True) / c.analysis_count
            self.check(_close(summary.get("reconstruction_usable_fraction"), fraction, 0.0, 1e-12), f"{case_id}: usable-reconstruction fraction recomputed from rows", area="metrics")
        # Metrics of the mean intensity image come from the production accumulator: recorded, finite, distinct
        # quantities that are never recomputed from the instantaneous rows.
        averages = [summary.get(key) for key in AVERAGE_IMAGE_KEYS]
        self.check(all(_finite(v) and v > 0.0 for v in averages) and all(v <= 1.0 for v in averages[:3]), f"{case_id}: metrics of the mean intensity image are recorded as separate finite quantities", area="metrics")
        definition = str(metrics.get("definitions", {}).get("average_psf_peak_strehl_*", ""))
        self.check("differs from the mean instantaneous Strehl" in definition and str(c.analysis_count) in definition,
                   f"{case_id}: definitions distinguish the mean image's Strehl from the mean instantaneous Strehl over the {c.analysis_count} analysis frames", area="metrics")
        self.check(summary == self.manifest.get("summaries", {}).get(case_id), f"{case_id}: manifest summary equals the case metrics summary", area="metrics")

    def check_csv(self, case_id: str, metrics: Dict[str, Any], item: Optional[Dict[str, Any]]) -> None:
        c = self.c
        if item is None:
            self.check(False, f"{case_id}: metrics.csv rows equal the JSON per-frame records", area="metrics")
            return
        rows = list(csv.reader(io.StringIO(item["data"].decode("utf-8"))))
        ok = bool(rows) and rows[0] == list(CSV_COLUMNS) and len(rows) == c.frames + 1
        if ok:
            columns = {column: self._series(metrics, column) for column in CSV_COLUMNS}
            for index, row in enumerate(rows[1:]):
                if len(row) != len(CSV_COLUMNS):
                    ok = False
                    break
                for column, text in zip(CSV_COLUMNS, row):
                    values = columns[column]
                    expected = values[index] if isinstance(values, list) and index < len(values) else None
                    if column == "frame_index":
                        ok = text == str(index) and expected == index
                    elif column == "reconstruction_usable":
                        ok = isinstance(expected, bool) and text == str(expected).lower()
                    elif expected is None:
                        ok = text == ""
                    else:
                        ok = text != "" and _finite(expected) and float(text) == expected
                    if not ok:
                        break
                if not ok:
                    break
        self.check(ok, f"{case_id}: metrics.csv rows equal the JSON per-frame records", area="metrics")

    def check_observation(self, case_id: str, observation: Dict[str, Any], scene: Dict[str, Any], psf_scale: Dict[str, Any]) -> set:
        c = self.c
        self.check(observation.get("schema") == c.observation_schema and observation.get("case_id") == case_id, f"{case_id}: observation schema and id", area="observation")
        self.check(observation["scene_id"] == scene["scene_id"] and observation["scene_grid_id"] == scene["grid_id"], f"{case_id}: observation uses the shared scene and grid", area="observation")
        self.check(isinstance(observation.get("scene"), dict) and observation["scene"].get("sha256") == self.manifest["scene"].get("sha256"), f"{case_id}: observation references the shared scene record", area="observation")
        self.check(observation["window"] == list(c.analysis_window) and observation["sample_count"] == c.analysis_count and observation["weights"] == "equal",
                   f"{case_id}: observation is the [{c.burn_in}, {c.frames}) equal-weight average", area="observation")
        label = str(observation.get("label", ""))
        self.check("no additional science-camera noise" in label, f"{case_id}: observation label discloses no science-camera noise", area="observation")
        if c.time_domain_in_manifest:
            self.check(f"frames {c.burn_in}-{c.last_frame}" in label, f"{case_id}: observation label names the analysis frames", area="observation")
        self.check(observation.get("renderer_revision") == web_contract.OBSERVATION_RENDERER_REVISION and observation.get("policy") == web_contract.CONVOLUTION_POLICY,
                   f"{case_id}: observation renderer revision and convolution policy are the declared ones", area="observation")
        if c.observation_identity == "code_identity":
            code = observation.get("observation_code_identity") or {}
            self.check(_hex64(code.get("sha256")) and set(code.get("files", {})) == {"binary_scene.py", "render.py"}, f"{case_id}: observation binds the identity of the code that computed it", area="observation")
        else:
            derived = observation.get("derived_arrays") or {}
            self.check(derived.get("file") == "binary_observations.npz" and self.manifest["dataset_id"] in str(derived.get("location", "")) and "outside the site" in str(derived.get("location", "")),
                       f"{case_id}: observation names its derived arrays outside the site", area="observation")
        grid = scene["grid"]
        ny, nx = grid["shape_yx"]
        run_hashes: set = set()
        first, last = c.display_time(c.burn_in), c.display_time(c.last_frame)
        for role in ("uncorrected", "corrected"):
            r = observation["roles"][role]
            parent = r["parent"]
            self.check(parent["role"] == role and parent["window"] == list(c.analysis_window) and parent["sample_count"] == c.analysis_count and parent["stride"] == 1,
                       f"{case_id}: {role} parent is the full {c.analysis_count}-frame mean", area="observation")
            self.check(parent["field"] == PARENT_FIELDS[role], f"{case_id}: {role} parent field {parent['field']!r} is {PARENT_FIELDS[role]!r}", area="observation")
            self.check(parent["recentering"] == PARENT_RECENTERING and parent["coaddition"] == PARENT_COADDITION, f"{case_id}: {role} parent: intensity co-addition, no recentring", area="observation")
            self.check(parent["wavelength_m"] == SCIENCE_WAVELENGTH_M == scene["wavelength_m"], f"{case_id}: {role} parent wavelength {_wavelength(parent['wavelength_m'])} is the scene's {_wavelength(scene['wavelength_m'])}", area="observation")
            self.check(parent["normalization"] == PARENT_NORMALIZATION and _finite(parent.get("total_flux")) and abs(parent["total_flux"] - 1.0) <= protocol.TOLERANCES["unit_flux"]["atol"],
                       f"{case_id}: {role} parent normalization {parent['normalization']!r} is unit total flux", area="observation")
            self.check(parent["weights"] == "equal" and parent["sampling"] == PARENT_SAMPLING, f"{case_id}: {role} parent is an equal-weight frame-start snapshot average", area="observation")
            self.check(parent["x_angle_rad_sha256"] == grid["x_angle_rad_sha256"] and parent["y_angle_rad_sha256"] == grid["y_angle_rad_sha256"] and parent["shape"] == grid["shape_yx"],
                       f"{case_id}: {role} parent axes and shape equal the scene grid", area="observation")
            self.check(parent.get("frame_period_s") == c.frame_period_s and _close(parent.get("first_timestamp_s"), first, 1e-12) and _close(parent.get("last_timestamp_s"), last, 1e-12)
                       and _close(parent.get("timestamp_span_s"), last - first, 1e-12) and _close(parent.get("nominal_quadrature_duration_s"), c.analysis_count * c.frame_period_s, 1e-12),
                       f"{case_id}: {role} parent timestamps span frames {c.burn_in}-{c.last_frame} at the frame period", area="observation")
            expected_identity = case_id if c.parent_identity_key == "case_id" else f"case-{case_id}"
            self.check(parent.get(c.parent_identity_key) == expected_identity, f"{case_id}: {role} parent names this case", area="observation")
            self.check(all(_hex64(parent.get(key)) for key in ("array_sha256", "file_sha256", "accumulator_config_hash", "propagator_config_hash", "run_config_hash", "history_config_hash"))
                       and parent.get("file") == "mean_psfs.npz" and parent.get("array") == f"mean_psf_{role}", f"{case_id}: {role} parent records its array, file and configuration digests", area="observation")
            self.propagators.add(parent.get("propagator_config_hash"))
            self.accumulators.add(parent.get("accumulator_config_hash"))
            run_hashes.add(parent.get("run_config_hash"))
            scale = r.get("display", {}).get("scale", {})
            self.check(all(scale.get(name) == psf_scale[name] for name in ("mapping", "ideal_peak_cell_flux", "normalization")), f"{case_id}: {role} observation uses the common intensity display scale", area="observation")
            self.check(_finite(r.get("full_flux")) and _finite(r.get("expected_full_flux")) and abs(r["full_flux"] - r["expected_full_flux"]) <= protocol.TOLERANCES["convolution_flux"]["atol"],
                       f"{case_id}: {role} full flux equals scene x kernel flux", area="observation")
            self.check(_finite(r.get("retained_fraction")) and 0.0 < r["retained_fraction"] <= 1.0 and _finite(r.get("cropped_flux")) and abs(r["retained_fraction"] - r["cropped_flux"] / r["full_flux"]) < 1e-15
                       and _close(r.get("lost_fraction"), 1.0 - r["retained_fraction"], 0.0, 1e-15), f"{case_id}: {role} crop flux bookkeeping", area="observation")
            y0, x0 = grid["y_zero_index"], grid["x_zero_index"]
            self.check(r["crop_slices_yx"] == [[y0, y0 + ny], [x0, x0 + nx]] and r["full_shape_yx"] == [2 * ny - 1, 2 * nx - 1], f"{case_id}: {role} crop slices derived from the coordinates", area="observation")
            self.check(_hex64(r.get("image_sha256")), f"{case_id}: {role} observation records its array digest", area="observation")
        return run_hashes

    def check_config(self, case_id: str, config: Dict[str, Any], case: Dict[str, Any], protocol_case: Dict[str, Any]) -> None:
        c = self.c
        self.check(config.get("schema") == c.config_schema and config.get("case_id") == case_id, f"{case_id}: config schema and id", area="config")
        self.check(config.get("base_profile") == f"{protocol.PROFILE_NAME}@{protocol.PROFILE_VERSION}", f"{case_id}: config names the frozen base profile", area="config")
        self.check(config.get("case_override") == protocol_case["override"] and config.get("root_seed") == protocol.ROOT_SEED and config.get("realization_index") == protocol.REALIZATION_INDEX,
                   f"{case_id}: config override, root seed and realization equal the frozen protocol", area="config")
        self.check(config.get("effective_parameters") == case.get("effective_parameters"), f"{case_id}: config effective parameters equal the case's", area="config")
        self.check(_hex64(config.get("effective_config_hash")), f"{case_id}: config records its effective configuration hash", area="config")
        controller = config.get("effective_configuration", {}).get("controller", {})
        self.check(controller.get("n_steps") == c.frames and controller.get("frame_rate_hz") == c.frame_rate_hz, f"{case_id}: effective configuration runs {c.frames} steps at {c.frame_rate_hz:g} Hz", area="config")
        if c.time_domain_in_manifest:
            fc = config.get("frame_contract", {})
            self.check(fc.get("n_steps") == c.frames and fc.get("frame_rate_hz") == c.frame_rate_hz and fc.get("frame_period_s") == c.frame_period_s and fc.get("frame_indices") == [0, c.last_frame]
                       and fc.get("physical_interval_s") == [0.0, c.frames * c.frame_period_s] and fc.get("root_seed") == protocol.ROOT_SEED and fc.get("science_wavelength_m") == SCIENCE_WAVELENGTH_M,
                       f"{case_id}: config frame contract equals the {c.name} contract", area="config")
            self.check(config.get("screen") == self.manifest.get("screen"), f"{case_id}: config screen record equals the manifest's", area="config")
            binding = config.get("original_binding", {})
            self.check(binding.get("recorded_n_steps") == protocol.PRODUCTION_FRAMES and binding.get("recorded_burn_in") == protocol.PRODUCTION_BURN_IN and binding.get("recorded_root_seed") == protocol.ROOT_SEED
                       and binding.get("differences") == {"n_steps": [protocol.PRODUCTION_FRAMES, c.frames]} and binding.get("case_override") == protocol_case["override"] and _hex64(binding.get("recorded_config_hash")),
                       f"{case_id}: original binding names the recorded {protocol.PRODUCTION_FRAMES}-frame case and differs only in n_steps", area="config")
        else:
            overrides = config.get("explorer_overrides", {})
            self.check(overrides.get("n_steps") == c.frames and overrides.get("burn_in_frames") == c.burn_in and overrides.get("root_seed") == protocol.ROOT_SEED
                       and overrides.get("realization_index") == protocol.REALIZATION_INDEX and overrides.get("science_wavelength_m") == SCIENCE_WAVELENGTH_M,
                       f"{case_id}: explorer overrides equal the frozen protocol", area="config")

    def check_provenance(self, case_id: str, provenance: Dict[str, Any], config: Dict[str, Any], run_hashes: set, case: Dict[str, Any]) -> None:
        c = self.c
        series = self.manifest.get("series", {})
        self.check(provenance.get("schema") == c.provenance_schema and provenance.get("case_id") == case_id, f"{case_id}: provenance schema and id", area="provenance")
        self.check(provenance.get("series_id") == series.get("series_id"), f"{case_id}: provenance names the manifest's series", area="provenance")
        run = provenance.get("run", {})
        self.check(_hex64(run.get("config_hash")) and run.get("config_hash") == config.get("effective_config_hash") and run_hashes == {run.get("config_hash")},
                   f"{case_id}: one run configuration hash across provenance, config and observation parents", area="provenance")
        files = provenance.get("raw_evidence", {}).get("files", {})
        self.check(bool(files) and all(isinstance(v, dict) and isinstance(v.get("bytes"), int) and _hex64(v.get("sha256")) for v in files.values()) and "mean_psfs.npz" in files,
                   f"{case_id}: raw-evidence file digests recorded", area="provenance")
        self.check(isinstance(provenance.get("attempt"), str) and provenance["attempt"].startswith("attempt-"), f"{case_id}: provenance names the completed attempt", area="provenance")
        if c.time_domain_in_manifest:
            self.check(provenance.get("plan_sha256") == series.get("plan_sha256") and provenance.get("production_identity", {}).get("sha256") == series.get("production_sha256"),
                       f"{case_id}: provenance plan and production identity equal the manifest's series record", area="provenance")
            screen = provenance.get("screen", {})
            self.check(screen.get("generated_screen_px") == c.screen_grid_size and screen.get("option") == {"screen_grid_size": c.screen_grid_size}, f"{case_id}: provenance records the {c.screen_grid_size} px screen option", area="provenance")
            horizon = run.get("horizon_runtime_check", {})
            self.check(horizon.get("equal") is True and horizon.get("exceeded_travel_budget") is False, f"{case_id}: the atmosphere travelled exactly the admitted distance within the budget", area="provenance")
            if c.producer_checks is not None:
                self.check_producer_checks(case_id, provenance.get("checks"))
            self.check(provenance.get("derived_export", {}).get("dataset_id") == self.manifest["dataset_id"], f"{case_id}: provenance names this dataset as its derived export", area="provenance")
            self.check(provenance.get("atmosphere_pairing") == case.get("pairing"), f"{case_id}: provenance pairing equals the case pairing", area="provenance")
        else:
            self.check(provenance.get("job_id") == f"case-{case_id}", f"{case_id}: provenance names the case job", area="provenance")
            if c.producer_checks is not None:
                self.check_v1_producer_checks(case_id, provenance.get("checks"), case.get("time_domain"))

    def check_mean_archive_binding(self, case_id: str, observation: Dict[str, Any], provenance: Dict[str, Any]) -> None:
        """The observation parents' file digest is the mean archive's digest the provenance binds (review R18-03).

        Both parents must name one archive with one digest, and the provenance must record that archive's
        digest; without this join a parent could name other bytes than the ones the provenance (and raw-evidence
        mode) verifies.  The parents' array digests are a separate check, made in raw-evidence mode against the
        archive's arrays.
        """

        parents = {role: observation["roles"][role]["parent"] for role in ROLES}
        named = {role: (parent.get("file"), parent.get("file_sha256")) for role, parent in parents.items()}
        shown = ", ".join(f"{role} {name!r} {str(digest)[:12]}" for role, (name, digest) in named.items())
        self.check(named["uncorrected"] == named["corrected"], f"{case_id}: the uncorrected and corrected parents name one mean archive with one file digest ({shown})", area="observation")
        bound = provenance.get("raw_evidence", {}).get("files", {}).get(MEAN_ARCHIVE)
        recorded = bound.get("sha256") if isinstance(bound, dict) else None
        self.check(_hex64(recorded), f"{case_id}: provenance binds the retained mean archive {MEAN_ARCHIVE} by SHA-256 (recorded {recorded!r})", area="provenance")
        for role, (name, digest) in named.items():
            self.check(name == MEAN_ARCHIVE and _hex64(digest) and digest == recorded,
                       f"{case_id}: {role} observation parent's file digest equals the provenance's {MEAN_ARCHIVE} digest (parent {name!r} {str(digest)[:12]}, provenance {str(recorded)[:12]})", area="provenance")

    def check_v1_producer_checks(self, case_id: str, checks: Any, time_domain: Any) -> None:
        """The v1 provenance's copy of the producer's record checks, judged on the window the case record names.

        The v1 exporter (``render.py``) applies the shared contract at the export boundary; the validator applies the
        same rule to what the dataset carries (review R24 follow-up).  The v1 contract reads its window from a job
        record, which the historical provenance does not hold, so the rule is given :func:`v1_window_record`, the
        adapter over the hash-bound case record's recorded ``burn_in_frames`` and ``frames``; the recorded
        ``analysis_window`` and ``analysis_count`` must be exact ints consistent with those two fields
        (:func:`v1_window_consistent`).  A pilot window, ``[16, 64)``, is self-consistent and still refused: the
        rule compares the recorded values with the production contract's ``[40, 180)`` and 140 frames.
        """

        record = time_domain if isinstance(time_domain, dict) else {}
        shown = ", ".join(f"{key} {record.get(key)!r}" for key in V1_TIME_DOMAIN_FIELDS)
        self.check(v1_window_consistent(time_domain),
                   f"{case_id}: the case record's time domain names the analysis window [burn_in_frames, frames) with analysis_count = frames - burn_in_frames "
                   f"as exact integers (recorded {shown})", area="provenance")
        self.check_producer_checks(case_id, checks, job=v1_window_record(time_domain))

    def check_producer_checks(self, case_id: str, checks: Any, job: Any = None) -> None:
        """The provenance's copy of the producer's record checks against the producer's own contract.

        Each check the producer refuses a record without must be recorded and literally ``true`` (a string,
        number or null is not a pass); the recorded analysis frames and count must be the selected contract's
        window -- read from the checks mapping (v2) or from the job-record view ``job`` (v1, the adapter over the
        case record's time domain); the numeric diagnostics must carry the producer's keys with finite numbers,
        absolute deviations non-negative.  No tolerance is applied to the diagnostics' values.
        """

        c = self.c
        expected = c.producer_checks
        assert expected is not None
        problems = web_contract.producer_check_problems(checks, expected, c.analysis_window, c.analysis_count, job=job)
        if problems.kind is not None:
            self.check(False, f"{case_id}: every producer check recorded in the provenance passed (the checks record is {problems.kind}, not an object)", area="provenance")
            return
        missing, unexpected, not_true = list(problems.missing), list(problems.unexpected), list(problems.not_true)
        self.check(not missing and not unexpected, f"{case_id}: provenance records exactly the producer's check fields (missing {missing}, unexpected {unexpected})", area="provenance")
        self.check(not not_true, f"{case_id}: every producer check recorded in the provenance passed (required checks present and literally true; {not_true})", area="provenance")
        first, second = expected.window_fields
        if expected.window_in_checks:
            recorded_frames, recorded_count = repr(checks.get(first)), repr(checks.get(second))
        else:
            record = job if isinstance(job, dict) else {}
            start, stop = record.get(first), record.get(second)
            recorded_frames = f"{first} {start!r}, {second} {stop!r}"
            recorded_count = f"{second} - {first} = {stop - start!r}" if type(start) is int and type(stop) is int else f"{second} - {first} undefined"
        self.check(not problems.frames_wrong, f"{case_id}: producer analysis frames are the {c.name} window [{c.burn_in}, {c.frames}) (recorded {recorded_frames})", area="provenance")
        self.check(not problems.count_wrong, f"{case_id}: producer analysis count is the {c.name} contract's {c.analysis_count} (recorded {recorded_count})", area="provenance")
        self.check(not problems.diagnostics, f"{case_id}: producer diagnostics carry the producer's keys and finite numbers, absolute deviations non-negative ({list(problems.diagnostics)})", area="provenance")

    def check_pairing(self, case_id: str, case: Dict[str, Any], protocol_case: Dict[str, Any]) -> None:
        c = self.c
        pairing = case.get("pairing", {})
        if case_id == protocol.DEFAULT_CASE:
            expected = "reference"
        elif "r0_scale" in protocol_case["override"]:
            expected = "different_atmosphere"
        else:
            expected = "paired"
        self.check(pairing.get("status") == expected and pairing.get("status") in PAIRING_STATUSES, f"{case_id}: atmosphere pairing status is {expected!r}", area="case")
        if expected != "different_atmosphere":
            self.check(pairing.get("matching_frames") == c.frames, f"{case_id}: all {c.frames} atmosphere samples match the baseline's", area="case")

    def check_shared_images(self, cases: Dict[str, Dict[str, Any]]) -> None:
        baseline = cases[protocol.DEFAULT_CASE]["case"]
        for case_id, bundle in cases.items():
            if bundle["case"].get("pairing", {}).get("status") != "paired":
                continue
            for path in SHARED_IMAGE_KEYS:
                mine: Any = bundle["case"]
                theirs: Any = baseline
                for key in path:
                    mine = mine.get(key) if isinstance(mine, dict) else None
                    theirs = theirs.get(key) if isinstance(theirs, dict) else None
                self.check(isinstance(mine, dict) and isinstance(theirs, dict) and mine.get("sha256") == theirs.get("sha256"),
                           f"{case_id}: shares the baseline's {path[1]} image (same recorded atmosphere)", area="images")

    # Blocks, diagnostics, results -------------------------------------------------

    def check_blocks(self, cases: Dict[str, Dict[str, Any]]) -> None:
        c = self.c
        blocks = self.json_member("blocks.json")
        self.check(blocks.get("schema") == web_contract.BLOCKS_SCHEMA and blocks.get("series_id") == self.manifest.get("series", {}).get("series_id"), "block summaries schema and series", area="blocks")
        definition = blocks.get("definition", {})
        length = c.block_frames or 0
        expected_blocks = [[i * length, (i + 1) * length] for i in range(c.frames // length)] if length else []
        self.check(definition.get("block_frames") == c.block_frames and definition.get("blocks") == expected_blocks and bool(expected_blocks) and expected_blocks[-1][1] == c.frames,
                   f"block definition tiles the {c.frames} frames in {c.block_frames}-frame blocks", area="blocks")
        self.check(set(blocks.get("cases", {})) == {case["id"] for case in protocol.CASES}, "block summaries cover exactly the eight cases", area="blocks")
        notice = str(blocks.get("notice", ""))
        self.check("not" in notice and "converge" in notice.lower(), "block notice states what the blocks do not establish", area="blocks")
        for case_id, bundle in cases.items():
            case_blocks = blocks.get("cases", {}).get(case_id)
            if not isinstance(case_blocks, dict):
                self.check(False, f"{case_id}: block summaries present", area="blocks")
                continue
            metrics = bundle["metrics"]
            series = {key: self._series(metrics, key) for key in ("residual_rms_nm", "peak_strehl_corrected", "peak_strehl_uncorrected", "dm_saturation_fraction", "reconstruction_usable")}
            rows = case_blocks.get("blocks", [])
            self.check(isinstance(rows, list) and len(rows) == len(expected_blocks), f"{case_id}: one block summary per block", area="blocks")
            analysis_means: List[Any] = []
            analysis_strehls: List[Any] = []
            clipped_total = 0
            for index, (row, (start, stop)) in enumerate(zip(rows if isinstance(rows, list) else [], expected_blocks)):
                if not isinstance(row, dict):
                    self.check(False, f"{case_id}: block {index} ({start}-{stop - 1}) statistics recomputed from the per-frame rows", area="blocks")
                    continue
                ok = row.get("frames") == [start, stop] and row.get("time_ms") == [start, stop] and row.get("in_analysis_window") == (start >= c.burn_in)
                for key, name in (("residual_rms_nm", "residual_rms_nm"), ("peak_strehl_corrected", "peak_strehl_corrected"), ("peak_strehl_uncorrected", "peak_strehl_uncorrected"), ("saturation_fraction", "dm_saturation_fraction")):
                    values = _complete(series[name][start:stop]) if isinstance(series[name], list) else None
                    stats = row.get(key) if isinstance(row.get(key), dict) else {}
                    ok = ok and values is not None and _close(stats.get("mean"), _mean(values)) and _close(stats.get("std"), _std(values), 1e-9, 1e-12) \
                        and _close(stats.get("min"), min(values), 0.0, 0.0) and _close(stats.get("max"), max(values), 0.0, 0.0)
                    if key == "saturation_fraction":
                        ok = ok and values is not None and stats.get("frames_with_any_clipped") == sum(1 for v in values if v > 0.0)
                usable = series["reconstruction_usable"]
                ok = ok and isinstance(usable, list) and row.get("unusable_reconstructions") == sum(1 for v in usable[start:stop] if v is not True)
                self.check(ok, f"{case_id}: block {index} ({start}-{stop - 1}) statistics recomputed from the per-frame rows", area="blocks")
                if start >= c.burn_in and isinstance(row.get("residual_rms_nm"), dict) and isinstance(row.get("peak_strehl_corrected"), dict):
                    analysis_means.append(row["residual_rms_nm"].get("mean"))
                    analysis_strehls.append(row["peak_strehl_corrected"].get("mean"))
                    clipped = row.get("saturation_fraction", {}).get("frames_with_any_clipped") if isinstance(row.get("saturation_fraction"), dict) else None
                    clipped_total += clipped if isinstance(clipped, int) else 0
            analysis = case_blocks.get("analysis_blocks", {})
            means, strehls = _complete(analysis_means), _complete(analysis_strehls)
            ok = means is not None and strehls is not None and length > 0 and analysis.get("count") == len(means) == c.analysis_count // length \
                and analysis.get("residual_rms_nm_block_means_range") == [min(means), max(means)] and _close(analysis.get("residual_rms_nm_block_means_std"), _std(means), 1e-9, 1e-12) \
                and analysis.get("peak_strehl_corrected_block_means_range") == [min(strehls), max(strehls)] and _close(analysis.get("first_minus_last_residual_rms_nm"), means[0] - means[-1], 1e-9, 1e-12) \
                and analysis.get("frames_with_any_clipped") == clipped_total
            self.check(ok, f"{case_id}: analysis-block summary recomputed from the block means", area="blocks")

    def check_diagnostics(self) -> None:
        c = self.c
        diagnostics = self.json_member("diagnostics.json")
        self.check(diagnostics.get("schema") == c.diagnostics_schema, f"diagnostics schema is the {c.name} contract's", area="diagnostics")
        passivity = diagnostics.get("passivity", {})
        if c.passivity == "identical":
            self.check(passivity.get("identical") is True and _hex64(passivity.get("history_digest_observed")) and passivity.get("history_digest_observed") == passivity.get("history_digest_control"),
                       "passivity: observed and observer-disabled baseline histories identical", area="diagnostics")
            self.check(isinstance(diagnostics.get("seed2_sensitivity", {}).get("summary"), dict) and diagnostics["seed2_sensitivity"].get("root_seed") == protocol.SENSITIVITY_SEED,
                       "seed-sensitivity summary recorded for the frozen sensitivity seed", area="diagnostics")
        else:
            self.check(passivity.get("status") == c.passivity and diagnostics.get("seed2_sensitivity", {}).get("status") == c.passivity,
                       "diagnostics declare that no passivity control or seed-sensitivity run exists for this dataset", area="diagnostics")
            historical = passivity.get("historical", {})
            previous = self.previous
            self.check(previous is not None and historical.get("dataset_id") == previous.name and historical.get("series_id") == previous.manifest.get("series", {}).get("series_id"),
                       "historical passivity evidence names the preserved previous dataset", area="diagnostics")
            if isinstance(historical.get("diagnostics"), dict):
                item = self.resolve(historical["diagnostics"], "diagnostics.json")
                self.check(item is not None and previous is not None and item.get("sha256") == previous.manifest.get("diagnostics", {}).get("sha256"),
                           "historical diagnostics reference is the previous dataset's diagnostics member", area="diagnostics")
            else:
                self.check(False, "historical diagnostics reference present", area="diagnostics")

    def check_results(self, *, repo_root: Optional[Path]) -> Dict[str, Any]:
        owner = self.active if self.c.research_in_dataset else self.previous
        assert owner is not None
        results_ref = self.manifest["results"]
        href = posixpath.normpath(str(results_ref.get("href", "")))
        if self.c.research_in_dataset:
            results_path = href
        else:
            # ../<previous dataset>/research/results.json -> research/results.json inside the previous dataset.
            inside = href[3:] if href.startswith("../") else ""
            results_path = inside.partition("/")[2]
            if not results_path:
                raise ValidationError(f"the Research Results reference {href!r} does not name a member of the previous dataset")
            recorded = owner.members.get(results_path, {})
            self.check(recorded.get("sha256") == results_ref.get("sha256") and recorded.get("bytes") == results_ref.get("bytes"),
                       "Research Results reference equals the previous dataset's own manifest record (byte-identical in place)", area="results")
        results = self.json_member(results_path, owner)
        self.walk_refs(results, results_path, owner)
        groups = results["groups"]
        self.check([g["id"] for g in groups] == [f"R{i}" for i in range(1, 9)], "Research Results has groups R1-R8 in order", area="results")
        sources_read = {source["path"]: source["sha256"] for source in results["sources_read"]}
        historical = {(source["commit"], source["path"]): source["sha256"] for source in results.get("historical_sources_read", [])}
        repository = results.get("source_repository", {})
        self.check(repository.get("commit") == results["source_sha"] and str(repository.get("url", "")).startswith("https://github.com/"), "research source links name the source commit's repository", area="results")
        for group in groups:
            self.check(bool(group["tables"] or group["charts"]) and bool(group["key_values"]), f"{group['id']}: quantitative content (tables/charts and key values)", area="results")
            self.check(bool(group["downloads"]), f"{group['id']}: downloadable compact evidence", area="results")
            self.check_nulls(group)
            for source in group.get("context_sources", []):
                expected = historical.get((source["commit"], source["path"])) if "commit" in source else sources_read.get(source["path"])
                self.check(expected == source["sha256"], f"{group['id']}: context source {source['path']} {source.get('commit', '')[:8]} is a recorded source read", area="results")
            self.check(bool(group["takeaway"]) and bool(group["limitations"]), f"{group['id']}: takeaway and limitations present", area="results")
            self.check(set(group["status"]) <= set(results["status_vocabulary"]), f"{group['id']}: evidence status uses the declared vocabulary", area="results")
            for figure in group["figures"]:
                item = self.resolve(figure["asset"], results_path, owner)
                if item is not None and figure["byte_identical_copy"] and figure["kind"] == "source_figure":
                    self.check(item["sha256"] == figure["source"]["sha256"], f"{group['id']}: figure {figure['source']['path']} is a byte-identical copy", area="results")
            for download in group["downloads"]:
                item = self.resolve(download["asset"], results_path, owner)
                if item is None:
                    continue
                if download.get("kind") == "byte_identical_copy":
                    self.check(item["sha256"] == download["source"]["sha256"], f"{group['id']}: download {download['source']['path']} is a byte-identical copy", area="results")
                elif download.get("kind") == "source_bound_extract":
                    self.check_extract(group["id"], item, download, results, sources_read, self._source_reader(results, repo_root))
                else:
                    self.check(False, f"{group['id']}: download {download.get('label')} has an unknown kind {download.get('kind')!r}", area="results")
        if repo_root is not None:
            self.check_research_sources(results, repo_root)
        r4 = groups[3]
        fits = {row["scale"]: row for row in next(t for t in r4["tables"] if t["id"] == "r4-noise-fit")["rows"]}
        self.check(fits["12 m"]["verdict_unscaled_two_se"] == "fail", "R4 keeps the failed 12 m inverse-photon test", area="results")
        definition = r4["context"].get("isolated_noise_variance", "")
        self.check("noise_variance_m2" in definition and "not the difference of the two arms' mean squares" in definition, "R4 defines dV as the paired residual-map difference (noise_variance_m2), not a difference of mean squares", area="results")
        for label, row in r4["computed_checks"]["dv_definition"].items():
            self.check(math.isclose(row["plotted_dv_mean_nm2"], row["seed_mean_noise_variance_nm2"], rel_tol=1e-12), f"R4 {label}: plotted dV is the seed mean of noise_variance_m2", area="results")
        r5 = groups[4]
        values = [row["residual_nm"] for row in next(t for t in r5["tables"] if t["id"] == "r5-s2")["rows"] if str(row.get("record", "")).startswith("S2")]
        mean = sum(values) / len(values)
        sd = math.sqrt(sum((v - mean) ** 2 for v in values) / (len(values) - 1))
        self.check(len(values) == 10 and abs(mean - 173.5895) < 5e-5 and abs(sd - 0.9414) < 5e-5, "R5 S2 mean and sample SD recomputed from the ten rows", area="results")
        return results

    def _git_blob(self, repo_root: Path, commit: str, path: str) -> Optional[bytes]:
        """The bytes of ``path`` at ``commit`` in the checkout at ``repo_root``, or None when Git cannot show it."""

        if not (repo_root / ".git").exists():
            return None
        import subprocess

        shown = subprocess.run(["git", "show", f"{commit}:{path}"], cwd=repo_root, capture_output=True)
        return shown.stdout if shown.returncode == 0 else None

    def _source_reader(self, results: Dict[str, Any], repo_root: Optional[Path]) -> Optional[Any]:
        """How research sources are re-read: the working tree under v1, the recorded source commit under v2 (None without a tree)."""

        if repo_root is None:
            return None
        if self.c.research_in_dataset:
            return lambda path: (repo_root / path).read_bytes() if (repo_root / path).is_file() else None
        return lambda path: self._git_blob(repo_root, str(results.get("source_sha", "")), path)

    def check_research_sources(self, results: Dict[str, Any], repo_root: Path) -> None:
        """The sources the Research Results were read from still have their recorded digests.

        Under the v1 contract the dataset was produced from this tree, so the working tree must still hold the
        recorded bytes.  Under the v2 contract the Research Results are a preserved appendix referenced in place and
        bound to their own source commit, so the digests are checked against that commit; files the working tree has
        since edited are listed in the report, not failed.
        """

        source_sha = str(results.get("source_sha", ""))
        for source in results["sources_read"]:
            tree_path = repo_root / source["path"]
            tree_same = tree_path.is_file() and _sha(tree_path.read_bytes()) == source["sha256"]
            if self.c.research_in_dataset:
                self.check(tree_same, f"research source {source['path']} unchanged in this tree", area="results")
            else:
                data = self._git_blob(repo_root, source_sha, source["path"])
                self.check(data is not None and _sha(data) == source["sha256"], f"research source {source['path']} at {source_sha[:8]} has its recorded digest", area="results")
                if not tree_same:
                    self.research_sources_changed.append(source["path"])
        for source in results.get("historical_sources_read", []):
            data = self._git_blob(repo_root, source["commit"], source["path"])
            self.check(data is not None and _sha(data) == source["sha256"], f"historical source {source['path']} at {source['commit'][:8]} has its recorded digest", area="results")

    def check_nulls(self, group: Dict[str, Any]) -> None:
        """Every missing table value and chart point carries a non-empty reason."""

        for table in group["tables"]:
            for index, row in enumerate(table["rows"]):
                for column in table["columns"]:
                    if row.get(column["key"]) is None:
                        reason = row.get(f"{column['key']}_null_reason")
                        self.check(isinstance(reason, str) and bool(reason.strip()), f"{group['id']}: {table['id']} row {index} {column['key']} is missing with a recorded reason", area="results")
        for chart in group["charts"]:
            missing = {item["x"] for item in chart.get("missing", []) if isinstance(item.get("reason"), str) and item["reason"].strip()}
            for series in chart.get("series", []):
                for point in series["points"]:
                    if any(value is None for value in point):
                        self.check(point[0] in missing, f"{group['id']}: {chart['id']} point at x = {point[0]} is missing with a recorded reason", area="results")

    def check_extract(self, group_id: str, item: Dict[str, Any], download: Dict[str, Any], results: Dict[str, Any], sources_read: Dict[str, str], read_source: Optional[Any]) -> None:
        """A source-bound extract copies saved notebook outputs verbatim, with their digests.

        ``read_source(path)`` returns the notebook bytes (working tree under v1, the recorded source commit under v2)
        or None; without it the notebooks are not re-read.
        """

        extract = _strict_json(item["data"], download["asset"]["href"])
        self.check(extract.get("schema") == "ao-explorer.notebook-output-extract.v1" and extract.get("group") == group_id and extract.get("source_sha") == results["source_sha"], f"{group_id}: extract schema, group and source commit", area="results")
        self.check(bool(extract["outputs"]), f"{group_id}: extract holds saved outputs", area="results")
        notebooks: Dict[str, Any] = {}
        for output in extract["outputs"]:
            self.check(sources_read.get(output["notebook"]) == output["notebook_sha256"], f"{group_id}: extract output {output['cell_id']} names a recorded notebook digest", area="results")
            self.check(_sha(output["text"].encode("utf-8")) == output["text_sha256"], f"{group_id}: extract output {output['cell_id']} text matches its digest", area="results")
        for line in extract["configuration"]:
            self.check(sources_read.get(line["path"]) == line["sha256"], f"{group_id}: extract configuration {line['name']} names a recorded notebook digest", area="results")
        self.check(sorted(source["path"] for source in download["sources"]) == sorted({output["notebook"] for output in extract["outputs"]} | {line["path"] for line in extract["configuration"]}), f"{group_id}: extract download lists exactly its notebooks", area="results")
        if read_source is None:
            return
        # Re-read the saved outputs from the notebooks themselves (the source
        # check binds them to the frozen source: the tree under v1, the recorded commit under v2).
        for output in extract["outputs"] + extract["configuration"]:
            path = output.get("notebook") or output.get("path")
            if path not in notebooks:
                data = read_source(path)
                present = self.check(data is not None, f"{group_id}: extract notebook {path} is readable from its frozen source", area="results")
                notebooks[path] = json.loads(data.decode("utf-8")) if present else None
        for output in extract["outputs"]:
            if notebooks[output["notebook"]] is None:
                continue
            cells = notebooks[output["notebook"]]["cells"]
            cell = cells[output["cell_index"]]
            stored = cell.get("outputs", [])[output["output_index"]]
            text = "".join(stored["text"]) if output["mime"].startswith("stream:") else "".join(stored.get("data", {}).get(output["mime"], []))
            self.check(cell.get("id") == output["cell_id"] and text == output["text"], f"{group_id}: extract output {output['cell_id']}/{output['output_index']} equals the notebook's saved output", area="results")
        for line in extract["configuration"]:
            if notebooks[line["path"]] is None:
                continue
            cell = notebooks[line["path"]]["cells"][line["cell_index"]]
            source_lines = "".join(cell["source"]).splitlines()
            self.check(cell.get("id") == line["cell_id"] and source_lines[line["source_line"] - 1].strip() == line["text"], f"{group_id}: extract configuration {line['name']} equals the notebook's line", area="results")

    def check_code_build(self) -> None:
        report = site_build.check(self.web_dir)
        self.check(not report["problems"], f"page code build is content-addressed and recorded by the entry ({report['problems'][:3]})", area="code_build")
        self.code_build = report["build"]

    # Raw evidence ----------------------------------------------------------------

    def check_raw(self, series_dir: Path, cases: Dict[str, Dict[str, Any]], display: Dict[str, Any]) -> None:
        """Bind the bundle to the retained raw archives, with the contract's own layout and frame indexing."""

        import numpy as np

        c = self.c
        series_dir = Path(series_dir)
        self.check(series_dir.is_dir(), f"raw evidence: series directory {series_dir} exists ({c.name} layout: {c.raw_layout})", area="raw")
        opd_lut = np.array([[int(h[1:3], 16), int(h[3:5], 16), int(h[5:7], 16)] for h in display["opd"]["lut_rgb_hex"]], dtype=np.uint8)
        for case_id, bundle in cases.items():
            provenance = bundle["provenance"]
            if c.raw_layout == "movie_npz":
                attempt = series_dir / "jobs" / str(provenance.get("job_id")) / str(provenance.get("attempt"))
            else:
                attempt = series_dir / "cases" / case_id / str(provenance.get("attempt"))
            if not self.check(attempt.is_dir(), f"{case_id}: raw attempt directory {attempt} exists ({c.raw_layout} layout)", area="raw"):
                continue
            try:
                self.check_raw_case(case_id, attempt, bundle, opd_lut, display["opd"]["limit_m"])
            except RAW_READ_ERRORS as exc:
                # A missing or malformed archive is a recorded failure of this case, not a crash of the run.
                self.check(False, f"{case_id}: raw evidence in {attempt} is readable ({type(exc).__name__}: {exc})", area="raw")

    def check_raw_case(self, case_id: str, attempt: Path, bundle: Dict[str, Any], opd_lut: Any, limit: float) -> None:
        """One case's retained archives: file digests, retained means, analysis frames, mask and the residual probe tiles."""

        import numpy as np
        from PIL import Image

        c = self.c
        provenance = bundle["provenance"]
        for name, info in provenance["raw_evidence"]["files"].items():
            path = attempt / name
            self.check(path.is_file() and path.stat().st_size == info["bytes"] and _sha_file(path) == info["sha256"], f"{case_id}: raw {name} matches its provenance digest", area="raw")
        # The archive's bytes are read once: their digest is joined to the parents' file digest, and the same bytes
        # are decoded for the array checks, so the arrays checked are those of the archive whose digest was checked.
        archive = (attempt / MEAN_ARCHIVE).read_bytes()
        archive_sha256 = _sha(archive)
        for role in ROLES:
            parent = bundle["observation"]["roles"][role]["parent"]
            self.check(parent.get("file") == MEAN_ARCHIVE and parent.get("file_sha256") == archive_sha256,
                       f"{case_id}: raw {MEAN_ARCHIVE} is the file the {role} observation parent names (name and SHA-256 of its bytes)", area="raw")
        retained_mask = None
        with np.load(io.BytesIO(archive), allow_pickle=False) as data:
            for role, name in (("uncorrected", "mean_psf_uncorrected"), ("corrected", "mean_psf_corrected")):
                digest = _sha(np.ascontiguousarray(data[name]).tobytes())
                self.check(digest == bundle["observation"]["roles"][role]["parent"]["array_sha256"], f"{case_id}: {role} observation parent digest equals the retained numeric mean", area="raw")
            self.check([int(v) for v in data["analysis_frames"]] == list(range(c.burn_in, c.frames)), f"{case_id}: retained mean covers frames {c.burn_in}-{c.last_frame} (not the displayed frames)", area="raw")
            if "pupil_mask" in data.files:
                retained_mask = np.asarray(data["pupil_mask"], dtype=bool)
        atlas_item = self.active.verify(f"{bundle['prefix']}/atlas-residual.png")
        if atlas_item is None:
            return
        atlas = np.asarray(Image.open(io.BytesIO(atlas_item["data"])).convert("RGBA"))
        rects = bundle["case"]["images"]["residual"]["rectangles_xywh"]
        pistons = bundle["case"]["images"]["residual"]["display_piston_nm"]
        if c.raw_layout == "movie_npz":
            with np.load(attempt / "movie.npz", allow_pickle=False) as movie:
                mask = np.asarray(movie["pupil_mask"], dtype=bool)
                indices = [int(v) for v in movie["indices"]]
                maps = np.asarray(movie["pre_update_residual_opd_m"], dtype=float)
            self.check(indices == list(c.display_indices), f"{case_id}: raw movie indices equal the frozen rule", area="raw")
            raw_maps = {frame: maps[indices.index(frame)] for frame in c.raw_probe_frames if frame in indices and indices.index(frame) < len(maps)}
        else:
            stack = np.load(attempt / "frames" / "pre_update_residual_opd_m.npy", mmap_mode="r")
            self.check(stack.ndim == 3 and stack.shape[0] == c.frames, f"{case_id}: raw residual stack holds {c.frames} frames (shape {list(stack.shape)})", area="raw")
            mask = np.isfinite(np.asarray(stack[0]))
            raw_maps = {frame: np.asarray(stack[frame], dtype=float) for frame in c.raw_probe_frames if frame < stack.shape[0]}
        if retained_mask is not None:
            self.check(bool(np.array_equal(mask, retained_mask)), f"{case_id}: raw pupil mask equals the retained mask", area="raw")
        levels = c.opd_levels
        positions = {frame: index for index, frame in enumerate(c.display_indices)}
        for frame in c.raw_probe_frames:
            if not self.check(frame in raw_maps, f"{case_id}: raw residual map of frame {frame} is in the archive", area="raw"):
                continue
            position = positions[frame]
            raw = raw_maps[frame]
            piston = float(np.mean(raw[mask]))
            self.check(abs(piston * 1e9 - pistons[position]) <= 1e-9, f"{case_id}: residual display piston at frame {frame} equals the raw pupil mean", area="raw")
            values = np.where(mask, raw - piston, 0.0)
            codes = np.clip(np.floor(np.clip((values + limit) / (2 * limit), 0.0, 1.0) * (levels - 1) + 0.5), 0, levels - 1).astype(int)
            expected = opd_lut[codes][::-1]
            expected_alpha = np.where(mask, 255, 0)[::-1]
            x, y, w, h = rects[position]
            tile = atlas[y:y + h, x:x + w]
            ok = tile.shape[:2] == expected_alpha.shape and np.array_equal(tile[..., 3], expected_alpha) and np.array_equal(tile[..., :3][expected_alpha > 0], expected[expected_alpha > 0])
            self.check(ok, f"{case_id}: residual atlas tile at frame {frame} equals the declared {levels}-level mapping of the raw map minus its pupil mean (+y up, no other normalization)", area="raw")

    # Driver ----------------------------------------------------------------------

    def run(self, *, series_dir: Optional[Path], repo_root: Optional[Path]) -> Dict[str, Any]:
        self.load_entry()
        self.verify_members()
        self.check_manifest()
        scene = self.check_scene()
        display = self.check_display(scene)
        cases = {case["id"]: self.check_case(case["id"], scene, display) for case in protocol.CASES}
        self.check(len(self.propagators) == 1 and len(self.accumulators) == 1, "every observation parent comes from one science propagator and accumulator configuration", area="observation")
        if self.c.shared_images:
            self.check_shared_images(cases)
        if self.c.blocks_required:
            self.check_blocks(cases)
        self.check_code_build()
        self.check_diagnostics()
        self.check_results(repo_root=repo_root)
        unreferenced = sorted(set(self.active.members) - self.referenced.get("active", set()))
        self.check(not unreferenced, f"every member is referenced ({unreferenced[:5]})", area="references")
        if series_dir is not None:
            self.check_raw(series_dir, cases, display)
        previous = None
        if self.previous is not None:
            previous = {
                "dataset_id": self.previous.name,
                "manifest_sha256": self.previous.manifest_sha256,
                "members_verified_in_place": sorted(path for path, ok in self.previous.verified.items() if ok),
            }
        return {
            "schema": RECORD_SCHEMA,
            "contract": self.c.summary(),
            "dataset_id": self.manifest["dataset_id"],
            "manifest_sha256": self.active.manifest_sha256,
            "member_count": len(self.active.members),
            "member_bytes": sum(item["bytes"] for item in self.active.members.values()),
            "previous_dataset": previous,
            "checks_passed": len(self.passed),
            "checks_failed": len(self.failures),
            "checks_by_area": self.areas,
            "failures": self.failures,
            "research_sources_changed_in_working_tree": sorted(self.research_sources_changed),
            "raw_evidence_checked": series_dir is not None,
            "raw_evidence_layout": self.c.raw_layout if series_dir is not None else None,
            "code_build": self.code_build,
            "valid": not self.failures,
        }


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--web-dir", type=Path, required=True)
    parser.add_argument("--series-dir", type=Path)
    parser.add_argument("--repo-root", type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument("--record", action="store_true")
    arguments = parser.parse_args(argv)
    checker = Checker(arguments.web_dir)
    try:
        report = checker.run(series_dir=arguments.series_dir, repo_root=arguments.repo_root)
    except (ValidationError, UnsupportedContract, KeyError, TypeError, ValueError, IndexError, OSError) as exc:
        print(json.dumps({"valid": False, "fatal": f"{type(exc).__name__}: {exc}", "contract": checker.contract.summary() if checker.contract else None}))
        return 2
    if arguments.record:
        target = arguments.web_dir / "validation" / f"manifest-validation-{report['dataset_id']}.json"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(report, indent=1) + "\n", encoding="utf-8")
    summary = {key: report[key] for key in ("contract", "dataset_id", "manifest_sha256", "member_count", "member_bytes", "checks_passed", "checks_failed", "checks_by_area", "raw_evidence_checked", "raw_evidence_layout", "code_build", "valid")}
    if report["previous_dataset"] is not None:
        summary["previous_dataset"] = {**report["previous_dataset"], "members_verified_in_place": len(report["previous_dataset"]["members_verified_in_place"])}
    if report["research_sources_changed_in_working_tree"]:
        summary["research_sources_changed_in_working_tree"] = report["research_sources_changed_in_working_tree"]
    summary["failures"] = report["failures"][:20]
    print(json.dumps(summary, indent=1))
    return 0 if report["valid"] else 1


if __name__ == "__main__":
    sys.exit(main())
