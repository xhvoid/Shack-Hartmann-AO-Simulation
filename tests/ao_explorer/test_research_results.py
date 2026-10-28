"""Research Results definitions, contexts and downloads against their saved sources.

External review ER-F01 (the R4 noise estimand), ER-F02 (R1/R2 evidence downloads)
and ER-F03 (wavelength and residual-timing contexts).  The checks read the
committed bundle and the saved evidence it carries; where the repository's
notebooks or history are present they are compared directly as well.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import statistics
import subprocess

import pytest


ROOT = Path(__file__).resolve().parents[2]


def _results(web_dir: Path):
    entry_path = web_dir / "data" / "current.json"
    if not entry_path.is_file():
        pytest.skip("no explorer web bundle in this tree")
    base = entry_path.parent / json.loads(entry_path.read_text())["dataset_id"]
    research = base / "research"
    results = json.loads((research / "results.json").read_text())
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
