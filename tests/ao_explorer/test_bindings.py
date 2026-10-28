"""Every bundle bound by data/current.json is intact, and broken bindings are refused.

The committed site is checked as it is.  The negative cases use a small
synthetic site with both manifest families (a ``members`` list with an in-place
member and a hash-bound reference, and a ``files`` map) and apply one defect
each, so that each case reaches the check it targets.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import subprocess
import sys

import pytest

import check_bindings


def _record(path: Path) -> dict:
    data = path.read_bytes()
    return {"bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()}


def _write(path: Path, data: bytes) -> dict:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return _record(path)


def _bind(site: Path, entry: dict, key: str | None, manifest: Path) -> None:
    record = _record(manifest)
    target = entry if key is None else entry[key]
    target.update(manifest_bytes=record["bytes"], manifest_sha256=record["sha256"])


def _mini_site(root: Path) -> Path:
    site = root / "site"
    dataset = site / "data" / "series-x"
    case = _write(dataset / "cases" / "a" / "case.json", b'{"frames": 3}\n')
    shared = _write(site / "derived" / "export-y" / "mean.png", b"\x89PNG not really\n")
    dataset_manifest = dataset / "manifest.json"
    dataset_manifest.write_text(json.dumps({
        "schema": "ao-explorer.manifest.v2", "dataset_id": "series-x",
        "cases": {"a": {"case": {"href": "cases/a/case.json", **case}}},
        "members": [{"path": "cases/a/case.json", **case}, {"path": "../../derived/export-y/mean.png", "in_place": True, **shared}],
    }, indent=1))
    bundle = site / "derived" / "extra-abc"
    readme = _write(bundle / "README.md", b"# extra\n")
    bundle_manifest = bundle / "manifest.json"
    bundle_manifest.write_text(json.dumps({"schema": "ao-explorer.extra-manifest.v1", "id": "extra-abc", "files": {"README.md": readme}}, indent=1))
    entry = {"schema": "ao-explorer.entry.v1", "dataset_id": "series-x", "manifest": "series-x/manifest.json", "code_build": "0" * 16,
             "extra": {"schema": "ao-explorer.extra-entry.v1", "id": "extra-abc", "manifest": "../derived/extra-abc/manifest.json"}}
    _bind(site, entry, None, dataset_manifest)
    _bind(site, entry, "extra", bundle_manifest)
    (site / "data" / "current.json").write_text(json.dumps(entry, indent=2) + "\n")
    return site


def _problems(site: Path) -> list:
    return check_bindings.check(site)["problems"]


def test_committed_site_bindings_hold(web_dir):
    if not (web_dir / "data" / "current.json").is_file():
        pytest.skip("no explorer web bundle in this tree")
    report = check_bindings.check(web_dir)
    assert report["problems"] == [], report["problems"][:10]
    entry = json.loads((web_dir / "data" / "current.json").read_text())
    assert set(report["bundles"]) == {name for name, _ in check_bindings.bound_entries(entry)}
    assert all(bundle["members"] > 0 for bundle in report["bundles"].values())


def test_synthetic_site_bindings_hold(tmp_path):
    report = check_bindings.check(_mini_site(tmp_path))
    assert report["problems"] == []
    assert report["bundles"]["dataset"]["members"] == 2 and report["bundles"]["extra"]["members"] == 1
    assert report["unbound_directories"] == [{"directory": "derived/export-y", "files": 1, "files_referenced_by_bound_manifests": 1}]


def _changed_byte(site: Path) -> None:
    path = site / "derived" / "extra-abc" / "README.md"
    data = bytearray(path.read_bytes())
    data[0] ^= 1
    path.write_bytes(bytes(data))


def _missing_member(site: Path) -> None:
    (site / "data" / "series-x" / "cases" / "a" / "case.json").unlink()


def _extra_file(site: Path) -> None:
    (site / "derived" / "extra-abc" / "notes.txt").write_text("not listed\n")


def _changed_in_place_member(site: Path) -> None:
    (site / "derived" / "export-y" / "mean.png").write_bytes(b"replaced\n")


def _manifest_not_rebound(site: Path) -> None:
    path = site / "derived" / "extra-abc" / "manifest.json"
    path.write_text(path.read_text() + "\n")


def _identity_mismatch(site: Path) -> None:
    path = site / "data" / "current.json"
    entry = json.loads(path.read_text())
    entry["extra"]["id"] = "extra-other"
    path.write_text(json.dumps(entry, indent=2) + "\n")


def _member_outside_site(site: Path) -> None:
    manifest_path = site / "derived" / "extra-abc" / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    manifest["files"]["../../../outside.txt"] = {"bytes": 1, "sha256": "0" * 64}
    manifest_path.write_text(json.dumps(manifest, indent=1))
    entry_path = site / "data" / "current.json"
    entry = json.loads(entry_path.read_text())
    _bind(site, entry, "extra", manifest_path)
    entry_path.write_text(json.dumps(entry, indent=2) + "\n")


@pytest.mark.parametrize(
    "defect, expected",
    [
        (_changed_byte, "extra: /files/README.md: derived/extra-abc/README.md has 8 bytes / SHA-256"),
        (_missing_member, "dataset: /members/0: data/series-x/cases/a/case.json is missing"),
        (_extra_file, "extra: unlisted file derived/extra-abc/notes.txt in the bundle directory"),
        (_changed_in_place_member, "dataset: /members/1: derived/export-y/mean.png has 9 bytes"),
        (_manifest_not_rebound, "extra: manifest has"),
        (_identity_mismatch, "extra: manifest id 'extra-abc' differs from the entry's 'extra-other'"),
        (_member_outside_site, "extra: /files/../../../outside.txt: ../../../outside.txt lies outside the site"),
    ],
    ids=["changed-byte", "missing-member", "extra-file", "changed-in-place-member", "manifest-not-rebound", "identity-mismatch", "outside-site"],
)
def test_broken_bindings_are_refused(tmp_path, defect, expected):
    site = _mini_site(tmp_path)
    defect(site)
    problems = _problems(site)
    assert any(problem.startswith(expected) for problem in problems), problems


def test_command_line_exit_status(tmp_path, scripts_dir):
    site = _mini_site(tmp_path)
    command = [sys.executable, str(scripts_dir / "check_bindings.py"), "--web-dir", str(site)]
    assert subprocess.run(command, capture_output=True, text=True).returncode == 0
    _extra_file(site)
    completed = subprocess.run(command, capture_output=True, text=True)
    assert completed.returncode == 1 and json.loads(completed.stdout)["bindings_hold"] is False
    (site / "data" / "current.json").write_text('{"schema": NaN}')
    assert subprocess.run(command, capture_output=True, text=True).returncode == 2
