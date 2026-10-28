"""Research Results definitions, contexts and downloads against their saved sources.

External review ER-F01 (the R4 noise estimand), ER-F02 (R1/R2 evidence downloads)
and ER-F03 (wavelength and residual-timing contexts).  The checks read the
committed bundle and the saved evidence it carries; where the repository's
notebooks or history are present they are compared directly as well.

The results are read where the entry's dataset manifest references them:
inside that dataset (v1) or in place in its declared previous dataset (v2),
bound to the reference's size and SHA-256 (R22-01).
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import posixpath
import statistics
import subprocess

import pytest


ROOT = Path(__file__).resolve().parents[2]


class ResearchResultsReferenceError(Exception):
    """The entry's dataset manifest does not bind a readable Research Results file."""


def _bound_bytes(path: Path, digest, label: str, size=None) -> bytes:
    if not path.is_file():
        raise ResearchResultsReferenceError(f"{label} {path} is missing")
    data = path.read_bytes()
    if (size is not None and len(data) != size) or hashlib.sha256(data).hexdigest() != digest:
        raise ResearchResultsReferenceError(f"{label} {path} does not match its recorded size/SHA-256")
    return data


def _research_results(entry_path: Path) -> tuple[Path, bytes]:
    """The research directory and the results bytes that the entry's dataset manifest references.

    The reference names ``research/<file>`` of the entry's own dataset or, climbing
    once, of the previous dataset that manifest declares; the owning dataset's
    manifest must list the file with the reference's size and SHA-256, and the
    file must match them.  Nothing else is searched.
    """

    data_root = entry_path.parent
    entry = json.loads(entry_path.read_bytes())
    dataset_id = entry["dataset_id"]
    if entry.get("manifest") != f"{dataset_id}/manifest.json":
        raise ResearchResultsReferenceError(f"the entry's manifest {entry.get('manifest')!r} is not {dataset_id}/manifest.json")
    manifest = json.loads(_bound_bytes(data_root / entry["manifest"], entry.get("manifest_sha256"), "the entry's manifest", entry.get("manifest_bytes")))
    ref = manifest.get("results")
    href = ref.get("href") if isinstance(ref, dict) else None
    if (not isinstance(href, str) or not href or href.startswith("/") or "\\" in href or "://" in href
            or not isinstance(ref.get("bytes"), int) or not isinstance(ref.get("sha256"), str)):
        raise ResearchResultsReferenceError(f"{dataset_id}: malformed Research Results reference {ref!r}")
    owner, _, inner = posixpath.normpath(posixpath.join(dataset_id, href)).partition("/")
    if owner == dataset_id:
        owner_manifest = manifest
    else:
        previous = manifest.get("previous_dataset") if isinstance(manifest.get("previous_dataset"), dict) else {}
        if owner != previous.get("dataset_id") or (data_root / owner).resolve().parent != data_root.resolve():
            raise ResearchResultsReferenceError(f"{dataset_id}: Research Results reference {href!r} leaves the dataset and its declared previous dataset")
        owner_manifest = json.loads(_bound_bytes(data_root / owner / "manifest.json", previous.get("manifest_sha256"), f"previous dataset {owner}: manifest"))
        if owner_manifest.get("dataset_id") != owner:
            raise ResearchResultsReferenceError(f"previous dataset {owner}: its manifest names {owner_manifest.get('dataset_id')!r}")
    if posixpath.dirname(inner) != "research":
        raise ResearchResultsReferenceError(f"{dataset_id}: Research Results reference {href!r} does not name a file of {owner}/research")
    listed = [item for item in owner_manifest.get("members", []) if isinstance(item, dict) and item.get("path") == inner]
    if not any(item.get("bytes") == ref["bytes"] and item.get("sha256") == ref["sha256"] for item in listed):
        raise ResearchResultsReferenceError(f"{owner}: {inner} is not listed by its manifest with the reference's size and SHA-256")
    research = data_root / owner / "research"
    path = research / posixpath.basename(inner)
    if path.exists() and not path.resolve().is_relative_to((data_root / owner).resolve()):
        raise ResearchResultsReferenceError(f"{owner}: {inner} resolves outside its dataset ({path.resolve()})")
    return research, _bound_bytes(path, ref["sha256"], "Research Results", ref["bytes"])


def _results(web_dir: Path):
    entry_path = web_dir / "data" / "current.json"
    if not entry_path.is_file():
        pytest.skip("no explorer web bundle in this tree")
    research, data = _research_results(entry_path)
    results = json.loads(data)
    return research, results, {group["id"]: group for group in results["groups"]}


def _download(research: Path, group, source_path: str):
    item = next(d for d in group["downloads"] if d["kind"] == "byte_identical_copy" and d["source"]["path"] == source_path)
    return json.loads((research / item["asset"]["href"]).read_bytes())


def test_r4_dv_is_the_paired_map_difference_not_a_difference_of_mean_squares(web_dir):
    research, results, groups = _results(web_dir)
    r4 = groups["R4"]
    definition = r4["context"]["isolated_noise_variance"]
    assert "noise_variance_m2" in definition and "mean_square_difference_m2" in definition
    assert "not the difference of the two arms' mean squares" in definition and "additive noise budget" in definition
    assert "difference of mean squares" not in json.dumps(r4["context"]).replace("not the difference of the two arms' mean squares", "")
    law = _download(research, r4, "docs/research/detector_noise_law/results.json")
    chart = next(chart for chart in r4["charts"] if chart["id"] == "r4-noise-chart")
    plotted = {series["label"].split(":")[0]: [point[1] for point in series["points"]] for series in chart["series"]}
    for key, scale, record_name in (("2m", "2 m", "det09_noise_isolation_2m.json"), ("12m_v3", "12 m", "det09_noise_isolation_12m_v3.json")):
        record = _download(research, r4, f"docs/refactor/detector_level_evidence/{record_name}")
        means = []
        for label, item in law["analysis"][key]["per_magnitude"].items():
            runs = [run for run in record["runs"] if run["label"] == label and run["root_seed"] in item["seeds"]]
            assert len(runs) == len(item["seeds"])
            paired = statistics.fmean(run["noise_variance_m2"] * 1e18 for run in runs)
            assert paired == pytest.approx(item["dv_mean_nm2"], rel=1e-12)
            means.append(paired)
        assert plotted[scale] == pytest.approx(means, rel=1e-12)
    # The saved counterexample: the plotted statistic and the difference of
    # the arms' mean squares disagree, even in sign.
    record = _download(research, r4, "docs/refactor/detector_level_evidence/det09_noise_isolation_2m.json")
    m5 = [run for run in record["runs"] if run["label"] == "m5"]
    assert [run["root_seed"] for run in m5] == list(range(61, 69))
    assert statistics.fmean(run["noise_variance_m2"] * 1e18 for run in m5) == pytest.approx(4.270028922227549, rel=1e-12)
    assert statistics.fmean(run["mean_square_difference_m2"] * 1e18 for run in m5) == pytest.approx(-38.55742551569499, rel=1e-9)
    check = r4["computed_checks"]["dv_definition"]["2m m5"]
    assert check["plotted_dv_mean_nm2"] == pytest.approx(4.270028922227549, rel=1e-15)
    assert check["seed_mean_arm_mean_square_difference_nm2"] == pytest.approx(-38.55742551569499, rel=1e-9)
    # The numbers and the failed 12 m verdict are unchanged.
    fits = {row["scale"]: row for row in next(t for t in r4["tables"] if t["id"] == "r4-noise-fit")["rows"]}
    assert fits["12 m"]["verdict_unscaled_two_se"] == "fail" and fits["2 m"]["verdict_unscaled_two_se"] == "pass"


@pytest.mark.parametrize("group_id", ["R1", "R2"])
def test_r1_r2_offer_a_source_bound_extract_of_their_saved_outputs(web_dir, group_id):
    research, results, groups = _results(web_dir)
    group = groups[group_id]
    downloads = [d for d in group["downloads"] if d["kind"] == "source_bound_extract"]
    assert len(downloads) == 1
    data = (research / downloads[0]["asset"]["href"]).read_bytes()
    assert len(data) == downloads[0]["asset"]["bytes"] > 1000 and hashlib.sha256(data).hexdigest() == downloads[0]["asset"]["sha256"]
    extract = json.loads(data)
    assert extract["source_sha"] == results["source_sha"] and extract["group"] == group_id
    read = {source["path"]: source["sha256"] for source in results["sources_read"]}
    for output in extract["outputs"]:
        assert hashlib.sha256(output["text"].encode("utf-8")).hexdigest() == output["text_sha256"]
        assert read[output["notebook"]] == output["notebook_sha256"]
        notebook_path = ROOT / output["notebook"]
        if notebook_path.is_file():
            cell = json.loads(notebook_path.read_text())["cells"][output["cell_index"]]
            stored = cell["outputs"][output["output_index"]]
            text = "".join(stored["text"]) if output["mime"].startswith("stream:") else "".join(stored["data"][output["mime"]])
            assert cell["id"] == output["cell_id"] and text == output["text"]
    # Every table of the group is backed by a parsed saved table of the extract.
    used = " ".join(" ".join(output["used_for"]) for output in extract["outputs"])
    for table in group["tables"]:
        assert f"table {table['id']}" in used
    if group_id == "R1":
        parsed = next(o for o in extract["outputs"] if "table r1-precision" in o["used_for"])["parsed_table"]
        table = next(t for t in group["tables"] if t["id"] == "r1-precision")
        assert [int(row[1]) for row in parsed["rows"]] == [row["photons"] for row in table["rows"]]


def test_r2_wavelengths_are_bound_to_the_notebook_configuration(web_dir):
    research, results, groups = _results(web_dir)
    r2 = groups["R2"]
    assert r2["context"]["wfs_wavelength_m"] == 7e-07
    assert r2["context"]["h_band_estimate_wavelength_m"] == 1.65e-06
    lines = {(item["path"], item.get("name")): item for item in r2["context_sources"] if "name" in item}
    assert {key[0].split("/")[-1] for key in lines} == {"03_tsvd_regularization.ipynb", "04_closed_loop_control.ipynb", "noise_latency_gain.ipynb", "high_order_scao.ipynb"}
    assert lines[("notebooks/studies/high_order_scao.ipynb", "SCIENCE_WAVELENGTH_M")]["value"] == 1.65e-06
    for (path, name), item in lines.items():
        notebook_path = ROOT / path
        if notebook_path.is_file():
            cell = json.loads(notebook_path.read_text())["cells"][item["cell_index"]]
            assert cell["id"] == item["cell_id"]
            assert "".join(cell["source"]).splitlines()[item["source_line"] - 1].strip() == item["text"] == f"{name} = {item['text'].split('=', 1)[1].strip()}"


def test_r4_r5_separate_rms_and_science_image_timing(web_dir):
    research, results, groups = _results(web_dir)
    r5 = groups["R5"]["context"]
    assert "post-update" in r5["residual_rms"] and "pre-update" in r5["residual_rms"]
    assert "pre-update residual" in r5["science_image"] and "23125024" in r5["science_image"] and "frames 200-1999" in r5["science_image"]
    assert "unretained driver" in r5["science_image"] and "documented, not code-verified" in r5["science_image"]
    r4 = groups["R4"]["context"]
    assert "post-update" in r4["residual_rms"]
    assert r4["science_residual_of_these_records"].startswith("@3 review scan and camera comparison: pre-update")
    assert "573f875" in r4["science_residual_of_these_records"] and "@1 and @2 scans: unknown" in r4["science_residual_of_these_records"]
    for group_id in ("R4", "R5"):
        historical = [item for item in groups[group_id]["context_sources"] if "commit" in item]
        assert historical, group_id
        for item in historical:
            assert {"commit": item["commit"], "path": item["path"], "sha256": item["sha256"]}.items() <= next(
                source for source in results["historical_sources_read"] if (source["commit"], source["path"]) == (item["commit"], item["path"])
            ).items()


def test_historical_producer_sources_match_their_commits(web_dir):
    research, results, groups = _results(web_dir)
    if not (ROOT / ".git").exists():
        pytest.skip("no repository history in this tree")
    for source in results["historical_sources_read"]:
        shown = subprocess.run(["git", "show", f"{source['commit']}:{source['path']}"], cwd=ROOT, capture_output=True, check=True).stdout
        assert hashlib.sha256(shown).hexdigest() == source["sha256"]
        assert subprocess.run(["git", "merge-base", "--is-ancestor", source["commit"], results["source_sha"]], cwd=ROOT).returncode == 0


def test_every_result_group_has_downloads_and_source_links(web_dir):
    research, results, groups = _results(web_dir)
    assert results["source_repository"]["commit"] == results["source_sha"]
    assert results["source_repository"]["url"] == "https://github.com/xhvoid/Shack-Hartmann-AO-Simulation"
    for group in groups.values():
        assert group["downloads"], group["id"]
        for download in group["downloads"]:
            data = (research / download["asset"]["href"]).read_bytes()
            assert len(data) == download["asset"]["bytes"] > 0


def test_r4_reruns_carry_the_source_identity_of_573f875(web_dir):
    # Round-5 review, R5-F01: the reruns' source-change digest is that of the
    # 663df161 -> 573f875 diff of src and scripts; the 2 m isolation record's
    # digest is not, and the @1/@2 scans carry no identity.
    research, results, groups = _results(web_dir)
    r4 = groups["R4"]
    identity = r4["computed_checks"]["rerun_source_identity"]
    for name in ("det09_e3_magnitude_scan_12m_v3_review.json", "det09_e4_camera_comparison_12m_v3_review.json", "det09_noise_isolation_12m_v3.json"):
        code = _download(research, r4, f"docs/refactor/detector_level_evidence/{name}")["code_identity"]
        assert (code["git_head"], code["source_changes_sha256"]) == (identity["recorded_head"], identity["source_change_sha256"])
    two_m = _download(research, r4, "docs/refactor/detector_level_evidence/det09_noise_isolation_2m.json")["code_identity"]
    assert two_m["source_changes_sha256"] != identity["source_change_sha256"]
    for name in ("det09_e3_magnitude_scan_12m.json", "det09_e3_magnitude_scan_12m_v2.json"):
        assert "code_identity" not in _download(research, r4, f"docs/refactor/detector_level_evidence/{name}")
    if (ROOT / ".git").exists():
        import research

        assert research.Sources().source_change_digest(identity["recorded_head"], identity["equivalent_commit"]) == identity["source_change_sha256"]


def test_source_change_digest_ignores_git_configuration(web_dir, monkeypatch, tmp_path_factory):
    # Round-6 review, R6-F03: the digest must not depend on diff-text settings
    # or on how long git abbreviates object names in a growing repository.
    if not (ROOT / ".git").exists():
        pytest.skip("no repository history in this tree")
    import research

    research_dir, results, groups = _results(web_dir)
    identity = groups["R4"]["computed_checks"]["rerun_source_identity"]
    args = (identity["recorded_head"], identity["equivalent_commit"])
    hostile = {"core.abbrev": "12", "diff.noprefix": "true", "diff.mnemonicPrefix": "true", "diff.algorithm": "histogram", "color.diff": "always", "diff.context": "7"}
    plain = subprocess.run(["git", "-c", "core.abbrev=12", "diff", *args, "--", "src", "scripts"], cwd=ROOT, capture_output=True, check=True).stdout
    assert hashlib.sha256(plain).hexdigest() != identity["source_change_sha256"]  # an unpinned diff does change
    # Configuration injected through the environment is dropped ...
    monkeypatch.setenv("GIT_CONFIG_COUNT", str(len(hostile)))
    for index, (key, value) in enumerate(hostile.items()):
        monkeypatch.setenv(f"GIT_CONFIG_KEY_{index}", key)
        monkeypatch.setenv(f"GIT_CONFIG_VALUE_{index}", value)
    assert research.Sources().source_change_digest(*args) == identity["source_change_sha256"]
    # Object-directory variables are dropped too (round-10 review, R10-F01):
    # with this one honoured the throwaway git dir would find no objects.
    monkeypatch.setenv("GIT_OBJECT_DIRECTORY", str(tmp_path_factory.mktemp("no-objects") / "missing"))
    assert research.Sources().source_change_digest(*args) == identity["source_change_sha256"]
    monkeypatch.delenv("GIT_OBJECT_DIRECTORY")
    # ... and a hostile global configuration, order file and attributes
    # (round-7 review, R7-F01) are overridden by the pinned options.
    home = tmp_path_factory.mktemp("home")
    # Reversed against git's default order for this diff (scripts/ sorts
    # before src/), so the order file really takes effect (round-8 review, R8-F01).
    (home / "order").write_text("src/*\nscripts/*\n")
    # A template that would plant an attributes rule in every new git dir
    # (round-9 review, R9-F02: the digest runs in a throwaway git dir).
    (home / "template" / "info").mkdir(parents=True)
    (home / "template" / "info" / "attributes").write_text("*.py diff=python\n")
    for variant, attributes in (("driver", "*.py diff=python\n"), ("binary", "*.py -diff\n")):
        (home / f"attributes-{variant}").write_text(attributes)
        settings = {
            **hostile,
            "diff.orderFile": str(home / "order"),
            "diff.suppressBlankEmpty": "true",
            "diff.srcPrefix": "left/",
            "diff.dstPrefix": "right/",
            "core.attributesFile": str(home / f"attributes-{variant}"),
            "init.templateDir": str(home / "template"),
            # Every file counts as binary by size unless --text (R10-F01).
            "core.bigFileThreshold": "1",
        }
        sections = {}
        for key, value in settings.items():
            section, name = key.split(".")
            sections.setdefault(section, []).append(f"\t{name} = {value}")
        (home / ".gitconfig").write_text("".join(f"[{section}]\n" + "\n".join(lines) + "\n" for section, lines in sections.items()))
        monkeypatch.setenv("HOME", str(home))
        monkeypatch.setenv("XDG_CONFIG_HOME", str(home))
        unpinned = subprocess.run(["git", "diff", *args, "--", "src", "scripts"], cwd=ROOT, capture_output=True, check=True, env=research._plain_git_environment()).stdout
        assert hashlib.sha256(unpinned).hexdigest() != identity["source_change_sha256"], variant  # the configuration does take effect
        assert research.Sources().source_change_digest(*args) == identity["source_change_sha256"], variant
    # Repository-level cases, each in its own throwaway shared clone (the real
    # repository is never touched), compared with a clean clone so that each
    # assertion isolates its own setting.
    monkeypatch.setenv("HOME", str(tmp_path_factory.mktemp("empty-home")))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path_factory.mktemp("empty-xdg")))

    def shared_clone(name):
        path = tmp_path_factory.mktemp(name) / "repo"
        subprocess.run(["git", "clone", "--quiet", "--shared", "--no-checkout", str(ROOT), str(path)], check=True, capture_output=True, env=research._plain_git_environment())
        return path

    def git_in(path, *command, stdin=None):
        return subprocess.run(["git", *command], cwd=path, input=stdin, capture_output=True, text=True, check=True, env=research._plain_git_environment()).stdout.strip()

    def unpinned(path):
        diff = subprocess.run(["git", "--no-pager", "diff", *args, "--", "src", "scripts"], cwd=path, capture_output=True, check=True, env=research._plain_git_environment()).stdout
        return hashlib.sha256(diff).hexdigest()

    def pinned(path):
        monkeypatch.setattr(research.identity, "REPO_ROOT", path)
        return research.Sources().source_change_digest(*args)

    baseline = unpinned(shared_clone("clean"))

    def repository_config(path):
        for key, value in (("diff.suppressBlankEmpty", "true"), ("diff.orderFile", str(home / "order")), ("diff.srcPrefix", "left/"), ("diff.noprefix", "true"), ("core.bigFileThreshold", "1")):
            git_in(path, "config", key, value)

    def worktree_attributes(path):
        (path / ".gitattributes").write_text("*.py diff=python\n")

    def info_attributes(rule):
        def setup(path):
            (path / ".git" / "info").mkdir(exist_ok=True)
            (path / ".git" / "info" / "attributes").write_text(rule)
        return setup

    def global_attr_tree(path):
        # A tree written into this clone's objects only, whose .gitattributes
        # sets a diff driver; --attr-source must override attr.tree.
        blob = git_in(path, "hash-object", "-w", "--stdin", stdin="*.py diff=python\n")
        tree = git_in(path, "mktree", stdin=f"100644 blob {blob}\t.gitattributes\n")
        attr_home = tmp_path_factory.mktemp("attr-home")
        (attr_home / ".gitconfig").write_text(f"[attr]\n\ttree = {tree}\n")
        monkeypatch.setenv("HOME", str(attr_home))

    cases = {
        "repository configuration": repository_config,
        "working-tree .gitattributes": worktree_attributes,
        "info/attributes diff=python": info_attributes("*.py diff=python\n"),
        "info/attributes -diff": info_attributes("*.py -diff\n"),
        "global attr.tree": global_attr_tree,
    }
    for name, setup in cases.items():
        clone = shared_clone(name.replace(" ", "-").replace("/", "-").replace("=", "-"))
        setup(clone)
        assert unpinned(clone) != baseline, name  # this setting alone does change an unpinned diff
        assert pinned(clone) == identity["source_change_sha256"], name
        monkeypatch.setenv("HOME", str(tmp_path_factory.mktemp("empty-home")))

def test_r5_s2_records_name_the_unretained_driver(web_dir):
    research, results, groups = _results(web_dir)
    r5 = groups["R5"]
    for seed in range(2, 12):
        record = _download(research, r5, f"docs/refactor/detector_level_evidence/det09_s2_42m_seed{seed}.json")
        assert record["argv"][0] == "outputs/large_experiments/2026-10-18/s2/run_one_seed.py"
    assert any(source["path"] == "docs/refactor/CLEANUP_REFACTOR_STATUS.md" for source in r5["context_sources"])


# ---------------------------------------------------------------------------
# R22-01: the loader follows the dataset manifest's Research Results reference.
# Tiny synthetic bundles; the expected directories and contents are written out
# by the tests, never derived from the loader.

OLDER_RESULTS = {"groups": [{"id": "R1", "downloads": [{"kind": "byte_identical_copy", "source": {"path": "docs/a.json"}, "asset": {"href": "evidence/a.json"}}]}]}
DECOY_RESULTS = {"groups": [{"id": "DECOY", "downloads": []}]}


def _json_bytes(value) -> bytes:
    return (json.dumps(value, indent=1) + "\n").encode()


def _put(path: Path, data: bytes) -> dict:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return {"bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()}


def _edit(path: Path, change) -> None:
    value = json.loads(path.read_bytes())
    change(value)
    path.write_bytes(_json_bytes(value))


def _bind(web: Path) -> None:
    """Re-record the previous dataset's manifest digest and the entry's manifest binding after an edit."""

    data = web / "data"
    entry = json.loads((data / "current.json").read_bytes())
    manifest = json.loads((data / entry["manifest"]).read_bytes())
    previous = manifest.get("previous_dataset")
    if isinstance(previous, dict) and (data / str(previous.get("dataset_id")) / "manifest.json").is_file():
        previous["manifest_sha256"] = hashlib.sha256((data / previous["dataset_id"] / "manifest.json").read_bytes()).hexdigest()
    record = _put(data / entry["manifest"], _json_bytes(manifest))
    entry.update(manifest_bytes=record["bytes"], manifest_sha256=record["sha256"])
    (data / "current.json").write_bytes(_json_bytes(entry))


def _bundle(tmp_path: Path, entry_dataset: str = "active") -> Path:
    """``data/older``: a v1 dataset holding ``research/results.json`` and its evidence.

    ``data/active``: a v2 dataset that references those results in place and has a decoy
    ``research`` directory of its own, which no reference names.
    """

    web = tmp_path / "web"
    data = web / "data"
    members = [{"path": path, **_put(data / "older" / path, payload), "media_type": "application/json"}
               for path, payload in (("research/results.json", _json_bytes(OLDER_RESULTS)), ("research/evidence/a.json", _json_bytes({"owner": "older"})))]
    binding = {"bytes": members[0]["bytes"], "sha256": members[0]["sha256"], "media_type": "application/json"}
    _put(data / "older" / "manifest.json", _json_bytes({"schema": "ao-explorer.manifest.v1", "dataset_id": "older", "results": {"href": "research/results.json", **binding}, "members": members}))
    _put(data / "active" / "research" / "results.json", _json_bytes(DECOY_RESULTS))
    _put(data / "active" / "research" / "evidence" / "a.json", _json_bytes({"owner": "active"}))
    _put(data / "active" / "manifest.json", _json_bytes({
        "schema": "ao-explorer.manifest.v2", "dataset_id": "active", "results": {"href": "../older/research/results.json", **binding},
        "previous_dataset": {"dataset_id": "older", "manifest_sha256": None, "relation": "preserved unchanged"}, "members": [],
    }))
    _put(data / "current.json", _json_bytes({"dataset_id": entry_dataset, "manifest": f"{entry_dataset}/manifest.json"}))
    _bind(web)
    return web


@pytest.mark.parametrize(("entry_dataset", "href"), [("older", "research/results.json"), ("active", "../older/research/results.json")])
def test_results_follow_the_manifest_reference_to_their_own_research_directory(tmp_path, entry_dataset, href):
    web = _bundle(tmp_path, entry_dataset)
    assert json.loads((web / "data" / entry_dataset / "manifest.json").read_bytes())["results"]["href"] == href
    research, results, groups = _results(web)
    assert research == tmp_path / "web" / "data" / "older" / "research"
    assert results == OLDER_RESULTS
    # Downloads resolve in the research directory that owns the results, not in the active dataset's decoy.
    assert _download(research, groups["R1"], "docs/a.json") == {"owner": "older"}


def test_committed_entry_reads_the_preserved_research_results_in_place(web_dir):
    research, results, groups = _results(web_dir)
    assert research == web_dir / "data" / "series-2m180-b3e1c66-e0d60cbaccc6b" / "research"
    data = (research / "results.json").read_bytes()
    assert len(data) == 234897 and hashlib.sha256(data).hexdigest() == "71d0f81f7ebe92b6186d053e549a09fa837d2fd3fc969ddbbb0ca84eb7428484"
    assert list(groups) == [f"R{i}" for i in range(1, 9)]


def test_a_missing_declared_results_file_fails_without_a_fallback(tmp_path):
    web = _bundle(tmp_path)
    (web / "data" / "older" / "research" / "results.json").unlink()
    assert (web / "data" / "active" / "research" / "results.json").is_file()
    with pytest.raises(ResearchResultsReferenceError, match="Research Results .* is missing"):
        _results(web)


@pytest.mark.parametrize("damage", ["flipped byte", "truncated", "appended"])
def test_a_corrupted_results_file_fails_its_size_and_digest(tmp_path, damage):
    web = _bundle(tmp_path)
    path = web / "data" / "older" / "research" / "results.json"
    data = path.read_bytes()
    path.write_bytes({"flipped byte": data[:10] + bytes([data[10] ^ 1]) + data[11:], "truncated": data[:-1], "appended": data + b" "}[damage])
    with pytest.raises(ResearchResultsReferenceError, match="Research Results .* does not match its recorded size/SHA-256"):
        _results(web)


@pytest.mark.parametrize(("manifest", "change"), [
    ("active", lambda m: m["results"].update(bytes=m["results"]["bytes"] + 1)),
    ("active", lambda m: m["results"].update(sha256="0" * 64)),
    ("older", lambda m: m["members"][0].update(sha256="0" * 64)),
], ids=["reference size", "reference digest", "owner's member record"])
def test_a_reference_that_disagrees_with_the_owning_manifest_fails(tmp_path, manifest, change):
    web = _bundle(tmp_path)
    _edit(web / "data" / manifest / "manifest.json", change)
    _bind(web)
    with pytest.raises(ResearchResultsReferenceError, match="is not listed by its manifest with the reference's size and SHA-256"):
        _results(web)


@pytest.mark.parametrize(("href", "message"), [
    (None, "malformed"),
    ("", "malformed"),
    ("/data/older/research/results.json", "malformed"),
    ("https://example.org/data/older/research/results.json", "malformed"),
    ("..\\older\\research\\results.json", "malformed"),
    ("../../outside/research/results.json", "leaves the dataset and its declared previous dataset"),
    ("../older/../../outside/research/results.json", "leaves the dataset and its declared previous dataset"),
    ("../other/research/results.json", "leaves the dataset and its declared previous dataset"),
    ("../older/evidence/results.json", "does not name a file of older/research"),
])
def test_a_malformed_or_escaping_reference_fails(tmp_path, href, message):
    web = _bundle(tmp_path)
    # Readable, correctly sized copies wait at the escaping targets (an undeclared sibling even lists its copy):
    # the refusal must not depend on their absence.
    payload = (web / "data" / "older" / "research" / "results.json").read_bytes()
    record = _put(web / "outside" / "research" / "results.json", payload)
    _put(web / "data" / "older" / "evidence" / "results.json", payload)
    _put(web / "data" / "other" / "research" / "results.json", payload)
    _put(web / "data" / "other" / "manifest.json", _json_bytes({"dataset_id": "other", "members": [{"path": "research/results.json", **record}]}))
    _edit(web / "data" / "active" / "manifest.json", lambda m: m["results"].update(href=href))
    _bind(web)
    with pytest.raises(ResearchResultsReferenceError, match=message):
        _results(web)


@pytest.mark.parametrize("results", [
    "../older/research/results.json",
    {"href": "../older/research/results.json"},
    {"href": "../older/research/results.json", "bytes": "1", "sha256": "0" * 64},
], ids=["bare string", "no size or digest", "size not an integer"])
def test_a_reference_without_its_binding_is_malformed(tmp_path, results):
    web = _bundle(tmp_path)
    _edit(web / "data" / "active" / "manifest.json", lambda m: m.update(results=results))
    _bind(web)
    with pytest.raises(ResearchResultsReferenceError, match="malformed Research Results reference"):
        _results(web)


def test_the_previous_dataset_must_be_declared_and_bound(tmp_path):
    web = _bundle(tmp_path)
    _edit(web / "data" / "active" / "manifest.json", lambda m: m.pop("previous_dataset"))
    _bind(web)
    with pytest.raises(ResearchResultsReferenceError, match="leaves the dataset and its declared previous dataset"):
        _results(web)
    web = _bundle(tmp_path / "changed")
    _edit(web / "data" / "older" / "manifest.json", lambda m: m.update(title="changed after it was recorded"))
    with pytest.raises(ResearchResultsReferenceError, match="previous dataset older: manifest .* does not match its recorded size/SHA-256"):
        _results(web)
    web = _bundle(tmp_path / "renamed")
    _edit(web / "data" / "older" / "manifest.json", lambda m: m.update(dataset_id="other"))
    _bind(web)
    with pytest.raises(ResearchResultsReferenceError, match="its manifest names 'other'"):
        _results(web)


def test_a_results_file_linked_out_of_the_data_tree_is_refused(tmp_path):
    web = _bundle(tmp_path)
    path = web / "data" / "older" / "research" / "results.json"
    _put(tmp_path / "outside.json", path.read_bytes())
    path.unlink()
    try:
        path.symlink_to(tmp_path / "outside.json")
    except OSError:
        pytest.skip("symbolic links are unavailable here")
    with pytest.raises(ResearchResultsReferenceError, match="resolves outside its dataset"):
        _results(web)
