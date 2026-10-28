"""The committed explorer bundle validates, and malformed bundles are refused.

Each negative case copies the bundle, applies one defect and re-hashes the
affected members (and the manifest/entry) where needed, so the defect reaches
the semantic check it targets rather than stopping at a digest mismatch.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import shutil

import pytest

import validate


def _bundle_or_skip(web_dir: Path) -> Path:
    if not (web_dir / "data" / "current.json").is_file():
        pytest.skip("no explorer web bundle in this tree")
    return web_dir


def _run(web_dir: Path):
    checker = validate.Checker(web_dir)
    return checker.run(series_dir=None, repo_root=None)


def test_committed_bundle_is_valid(web_dir):
    report = _run(_bundle_or_skip(web_dir))
    assert report["valid"], report["failures"][:10]
    assert report["checks_passed"] > 500


def test_no_bundle_member_is_hidden_by_an_ignore_rule(web_dir):
    # Review round 1 (R1-F01): a repository-wide ignore pattern silently kept
    # part of the bundle out of the commit.  Every file the entry, the manifest
    # and the validation records name must be committable.
    import subprocess

    site = _bundle_or_skip(web_dir)
    repo = site.parents[1]
    if not (repo / ".git").exists():
        pytest.skip("not a git checkout")
    entry = json.loads((site / "data" / "current.json").read_text())
    base = site / "data" / entry["dataset_id"]
    manifest = json.loads((base / "manifest.json").read_text())
    paths = [site / "data" / "current.json", base / "manifest.json", *[base / item["path"] for item in manifest["members"]]]
    paths += sorted((site / "validation").glob("*.json"))
    paths += [site / "index.html", *sorted(path for code in site.glob("code-*") for path in code.iterdir())]
    relative = [path.relative_to(repo).as_posix() for path in paths]
    completed = subprocess.run(
        ["git", "check-ignore", "--no-index", "--stdin", "-v"],
        cwd=repo,
        input="\n".join(relative),
        capture_output=True,
        text=True,
    )
    # git check-ignore exits 1 when no path is ignored, 0 when some path is,
    # and 128 on an error; only 1 is a pass (review round 2, R2-F03).
    assert completed.returncode == 1, f"git check-ignore exit {completed.returncode}: {completed.stdout[:500]} {completed.stderr[:500]}"
    assert completed.stdout.strip() == "", f"ignored bundle files: {completed.stdout[:500]}"


def _copy(web_dir: Path, tmp_path: Path) -> Path:
    target = tmp_path / "site"
    shutil.copytree(_bundle_or_skip(web_dir), target)
    return target


def _rehash(site: Path, relative: str, data: bytes) -> None:
    entry_path = site / "data" / "current.json"
    entry = json.loads(entry_path.read_text())
    base = entry_path.parent / entry["dataset_id"]
    (base / relative).write_bytes(data)
    manifest_path = base / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    digest = hashlib.sha256(data).hexdigest()
    for item in manifest["members"]:
        if item["path"] == relative:
            item.update(bytes=len(data), sha256=digest)

    def update(value):
        if isinstance(value, dict):
            # Manifest references are relative to the manifest, i.e. the member path itself.
            if value.get("href") == relative and set(value) >= {"bytes", "sha256"}:
                value.update(bytes=len(data), sha256=digest)
            for item in value.values():
                update(item)
        elif isinstance(value, list):
            for item in value:
                update(item)

    update({key: manifest[key] for key in ("cases", "scene", "display", "diagnostics", "results")})
    manifest_bytes = (json.dumps(manifest, indent=1) + "\n").encode()
    manifest_path.write_bytes(manifest_bytes)
    entry.update(manifest_bytes=len(manifest_bytes), manifest_sha256=hashlib.sha256(manifest_bytes).hexdigest())
    entry_path.write_text(json.dumps(entry, indent=1) + "\n")


def _case_json(site: Path, case_id: str):
    entry = json.loads((site / "data" / "current.json").read_text())
    path = site / "data" / entry["dataset_id"] / "cases" / case_id / "case.json"
    return path, json.loads(path.read_text())


def _mutated_case(web_dir, tmp_path, case_id, mutate):
    site = _copy(web_dir, tmp_path)
    path, payload = _case_json(site, case_id)
    mutate(payload)
    _rehash(site, f"cases/{case_id}/case.json", (json.dumps(payload, indent=1) + "\n").encode())
    return site


@pytest.mark.parametrize(
    "mutate,expected",
    [
        (lambda c: c["time_domain"]["movie_indices"].__setitem__(9, 41), "movie indices"),
        (lambda c: c["time_domain"].__setitem__("analysis_window", [39, 180]), "analysis window"),
        (lambda c: c["images"]["residual"].__setitem__("color_limits_nm", [-1000.0, 1000.0]), "common symmetric OPD limits"),
        (lambda c: c["images"]["atmosphere"]["rectangles_xywh"].__setitem__(0, [5000, 0, 52, 52]), "atlas tiles"),
        (lambda c: c.__setitem__("case_id", "baseline"), "case schema and id"),
    ],
)
def test_semantic_defects_are_refused(web_dir, tmp_path, mutate, expected):
    site = _mutated_case(web_dir, tmp_path, "higher-gain", mutate)
    report = _run(site)
    assert not report["valid"]
    assert any(expected in failure for failure in report["failures"]), report["failures"][:5]


def test_corrupted_and_missing_members_are_refused(web_dir, tmp_path):
    site = _copy(web_dir, tmp_path)
    entry = json.loads((site / "data" / "current.json").read_text())
    base = site / "data" / entry["dataset_id"]
    png = base / "cases" / "fainter-guide" / "atlas-residual.png"
    data = bytearray(png.read_bytes())
    data[200] ^= 0xFF
    png.write_bytes(bytes(data))
    (base / "cases" / "lower-gain" / "metrics.csv").unlink()
    report = _run(site)
    failures = " | ".join(report["failures"])
    assert "fainter-guide/atlas-residual.png size and SHA-256" in failures
    assert "lower-gain/metrics.csv is missing" in failures


def test_non_finite_json_and_manifest_mismatch_are_refused(web_dir, tmp_path):
    site = _copy(web_dir, tmp_path)
    entry = json.loads((site / "data" / "current.json").read_text())
    base = site / "data" / entry["dataset_id"]
    metrics_path = base / "cases" / "baseline" / "metrics.json"
    text = metrics_path.read_text().replace('"values": [', '"values": [NaN, ', 1)
    _rehash(site, "cases/baseline/metrics.json", text.encode())
    with pytest.raises(validate.ValidationError, match="non-finite"):
        _run(site)
    site2 = _copy(web_dir, tmp_path / "second")
    entry_path = site2 / "data" / "current.json"
    entry = json.loads(entry_path.read_text())
    entry["manifest_sha256"] = "0" * 64
    entry_path.write_text(json.dumps(entry))
    with pytest.raises(validate.ValidationError, match="manifest does not match"):
        _run(site2)


def test_observation_parent_window_defect_is_refused(web_dir, tmp_path):
    site = _copy(web_dir, tmp_path)
    entry = json.loads((site / "data" / "current.json").read_text())
    path = site / "data" / entry["dataset_id"] / "cases" / "baseline" / "observation.json"
    payload = json.loads(path.read_text())
    payload["roles"]["corrected"]["parent"]["sample_count"] = 40  # the movie frames are no substitute
    payload["roles"]["corrected"]["parent"]["window"] = [140, 180]
    _rehash(site, "cases/baseline/observation.json", (json.dumps(payload, indent=1) + "\n").encode())
    report = _run(site)
    assert any("corrected parent is the full 140-frame mean" in failure for failure in report["failures"])


def test_research_results_are_independent_of_the_2m_controls(web_dir):
    site = _bundle_or_skip(web_dir)
    entry = json.loads((site / "data" / "current.json").read_text())
    results_text = (site / "data" / entry["dataset_id"] / "research" / "results.json").read_text()
    results = json.loads(results_text)
    # The research export binds only saved evidence of the frozen source; it
    # names no 2 m case, dataset or series of the new experiment.
    assert entry["dataset_id"] not in results_text
    for case in ("weaker-turbulence", "stronger-turbulence", "brighter-guide", "fainter-guide", "lower-gain", "higher-gain", "longer-delay"):
        assert case not in results_text
    for group in results["groups"]:
        selector = group.get("selector")
        if selector:
            assert "nothing is interpolated" in selector["note"] or "no row is interpolated" in selector["note"]


# ---------------------------------------------------------------------------
# Scientific semantics (external review ER-F04): coherently rehashed defects, so that
# no digest check can hide a semantic gap.  Each fixture must fail only on the
# semantic check it targets.

DIGEST_FAILURES = ("size and SHA-256", "resolves to a matching member", "is missing", "unlisted files")


def _rehash_case_member(site: Path, case_id: str, leaf: str, payload) -> None:
    entry = json.loads((site / "data" / "current.json").read_text())
    base = site / "data" / entry["dataset_id"]
    data = (json.dumps(payload, indent=1, ensure_ascii=False) + "\n").encode()
    if leaf == "case.json":
        _rehash(site, f"cases/{case_id}/case.json", data)
        return
    relative = f"cases/{case_id}/{leaf}"
    (base / relative).write_bytes(data)
    manifest = json.loads((base / "manifest.json").read_text())
    for item in manifest["members"]:
        if item["path"] == relative:
            item.update(bytes=len(data), sha256=hashlib.sha256(data).hexdigest())
    (base / "manifest.json").write_text(json.dumps(manifest, indent=1) + "\n")
    case_path, case = _case_json(site, case_id)
    key = {"metrics.json": "metrics", "observation.json": "observation"}[leaf]
    case["members"][key].update(bytes=len(data), sha256=hashlib.sha256(data).hexdigest())
    _rehash(site, f"cases/{case_id}/case.json", (json.dumps(case, indent=1, ensure_ascii=False) + "\n").encode())


def _member(site: Path, case_id: str, leaf: str):
    entry = json.loads((site / "data" / "current.json").read_text())
    return json.loads((site / "data" / entry["dataset_id"] / "cases" / case_id / leaf).read_text())


def _parent(role):
    return lambda o: o["roles"][role]["parent"]


SEMANTIC_DEFECTS = [
    ("wrong-parent-wavelength", "observation.json", lambda o: _parent("corrected")(o).__setitem__("wavelength_m", 700e-9), "corrected parent wavelength"),
    ("wrong-parent-axis-digest", "observation.json", lambda o: _parent("corrected")(o).__setitem__("x_angle_rad_sha256", "0" * 64), "corrected parent axes and shape equal the scene grid"),
    ("wrong-parent-normalization", "observation.json", lambda o: _parent("corrected")(o).__setitem__("normalization", "calibrated detector electrons"), "corrected parent normalization"),
    ("wrong-parent-residual", "observation.json", lambda o: _parent("corrected")(o).__setitem__("field", "post_update_residual_opd_m"), "corrected parent field"),
    ("wrong-opd-unit", "case.json", lambda c: c["images"]["atmosphere"].__setitem__("unit", "rad phase"), "atmosphere unit"),
    ("wrong-psf-scale", "case.json", lambda c: c["images"]["psf_corrected"]["scale"].__setitem__("mapping", "linear peak-normalized"), "psf_corrected uses the common intensity display scale"),
    ("null-without-reason", "metrics.json", lambda m: m["per_frame"]["residual_rms_nm"]["values"].__setitem__(0, None), "residual_rms_nm has a recorded reason for every missing value"),
]


@pytest.mark.parametrize("name,leaf,mutate,expected", SEMANTIC_DEFECTS, ids=[item[0] for item in SEMANTIC_DEFECTS])
def test_rehashed_semantic_defects_are_refused(web_dir, tmp_path, name, leaf, mutate, expected):
    site = _copy(web_dir, tmp_path)
    payload = _member(site, "baseline", leaf)
    mutate(payload)
    _rehash_case_member(site, "baseline", leaf, payload)
    report = _run(site)
    assert not report["valid"]
    assert any(expected in failure for failure in report["failures"]), report["failures"][:5]
    # The fixture is coherently rehashed: no digest or reference check fails.
    assert not [failure for failure in report["failures"] if any(word in failure for word in DIGEST_FAILURES)], report["failures"][:5]


def test_coherent_rehash_without_a_defect_is_accepted(web_dir, tmp_path):
    # Control for the fixtures above: the same rehash chain with unchanged
    # content (re-serialized bytes) validates.
    site = _copy(web_dir, tmp_path)
    for leaf in ("observation.json", "metrics.json", "case.json"):
        _rehash_case_member(site, "baseline", leaf, _member(site, "baseline", leaf))
    report = _run(site)
    assert report["valid"], report["failures"][:5]


# ---------------------------------------------------------------------------
# Content-addressed page code (external review ER-F05)


def test_page_code_is_content_addressed_and_bound_to_the_entry(web_dir):
    import re

    import site_build

    site = _bundle_or_skip(web_dir)
    report = site_build.check(site)
    assert report["problems"] == [], report["problems"]
    code = site / report["code_dir"]
    index = (site / "index.html").read_text()
    # No stable-name code reference is left in the page.
    assert not re.search(r'(href|src)="(styles\.css|app\.js)"', index)
    # Module imports stay inside the build directory and name existing files.
    for name in ("app.js", "results.js", "charts.js", "integrity.js"):
        for target in re.findall(r'from "([^"]+)"', (code / name).read_text()):
            assert target.startswith("./") and (code / target[2:]).is_file(), (name, target)
    assert 'new URL("../data/current.json", import.meta.url)' in (code / "app.js").read_text()
    assert json.loads((site / "data" / "current.json").read_text())["code_build"] == report["build"]


def test_changed_code_or_entry_build_is_detected(web_dir, tmp_path):
    import site_build

    site = _copy(web_dir, tmp_path)
    code = next(site.glob("code-*"))
    app = code / "app.js"
    app.write_text(app.read_text() + "\n// changed\n")
    problems = site_build.check(site)["problems"]
    assert any("does not carry its content build" in problem for problem in problems), problems
    assert not _run(site)["valid"]
    report = site_build.write(site)  # renames the directory, restamps the page and the entry
    assert report["problems"] == [] and report["code_dir"] != code.name
    assert _run(site)["valid"]
    entry_path = site / "data" / "current.json"
    entry = json.loads(entry_path.read_text())
    entry["code_build"] = "0" * 16
    entry_path.write_text(json.dumps(entry, indent=1) + "\n")
    report = _run(site)
    assert any("page code build" in failure for failure in report["failures"]), report["failures"][:5]
