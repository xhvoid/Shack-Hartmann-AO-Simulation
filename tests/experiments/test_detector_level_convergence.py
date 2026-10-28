"""T2: the fixed-physics convergence driver's plan, protocol, resume rules, refusals and analysis.

The driver is loaded by file.  Its child launcher is replaced by a stand-in
that writes the row a child would publish, with deterministic synthetic
results, so no simulation runs here; the producer identity is a controlled
stand-in.  The one real end-to-end self-check (fresh child processes) is the
``slow`` test at the end.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import math
import os
from pathlib import Path
import sys

import numpy as np
import pytest

from shwfs_ao.experiments import convergence_study, scao


ROOT = Path(__file__).resolve().parents[2]
_SPEC = importlib.util.spec_from_file_location(
    "detector_level_convergence_study_for_tests", ROOT / "scripts/detector_level_convergence_study.py"
)
assert _SPEC is not None and _SPEC.loader is not None
study = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = study
_SPEC.loader.exec_module(study)

CODE_A = {
    "package_directory": "src", "package_sha256": "p" * 64, "script_sha256": "script A",
    "result_affecting_helpers_sha256": {name: "h" * 64 for name in study.HELPER_MODULES},
    "git_head": "head A", "source_changes_sha256": "diff A",
}
ENVIRONMENT_A = {"python": "3.x A", "numpy": "numpy A", "scipy": "scipy A", "machine": "arm64"}
PRODUCER_A = {"code": CODE_A, "environment": ENVIRONMENT_A}
PRODUCER_B = {"code": CODE_A, "environment": {**ENVIRONMENT_A, "numpy": "numpy B"}}
UNKNOWN = {"code": {**CODE_A, "git_head": None, "source_changes_sha256": None}, "environment": ENVIRONMENT_A}


def _digest_text(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


BASE_VALUES = {"post_update_rms_m": 1.7e-7, "peak_strehl": 0.70, "ee50_radius_rad": 3.6e-7, "ee80_radius_rad": 9.0e-7}


def synthetic_h_squared(parameters: dict) -> float:
    """A sum of order-2 terms, one per axis, so each scan sees ``Q0 + C h**2`` in its own parameter."""

    return (
        (1.0 / parameters["samples_per_lenslet"]) ** 2
        + (1.0 / parameters["oversampling"]) ** 2
        + (1.0 / parameters["spectral_nodes"]) ** 2
        + (1.0 / parameters["science_pad"]) ** 2
        + ((1.0 / parameters["exposure_subsamples"]) ** 2 if parameters["exposure_rule"] == "midpoint" else 0.3)
    )


def synthetic_metric(run, arm: str, metric: str) -> float:
    """Smooth, order-2 synthetic values in every refinement parameter, distinct per arm."""

    offset = {"operating_expectation": 0.0, "noise_on": 0.01}[arm]
    return BASE_VALUES[metric] * (1.0 + 0.05 * synthetic_h_squared(run.parameters) + offset)


def stand_in_row(scale: str, run, made_by: dict, *, status: str = "completed") -> dict:
    """The row a child of ``made_by`` would publish for ``run``."""

    planned = study.planned_protocol(scale, run)
    row: dict = {name: planned[name] for name in study.REPEATED_FIELDS}
    spec = study.SCALES[scale]
    if status == "refused":
        row.update(status="refused", reason="ScaoConstructionError: stand-in refusal")
    else:
        analysed = planned["n_steps"] - planned["burn_in_frames"]
        # Non-pupil settings share the atmosphere grid: one open-loop series digest;
        # pupil settings have their own.
        atmosphere_key = f"{run.config.pupil_pixels}:{planned['atmosphere_options']}:{planned['root_seed']}:{run.realization}"
        digest = _digest_text(atmosphere_key)
        atmosphere_hash = _digest_text("atmosphere:" + atmosphere_key)
        parameters = planned["parameters"]
        if parameters["exposure_rule"] == "left_point" and parameters["exposure_subsamples"] == 1:
            exposure = None
        else:
            exposure = {
                "scheme": "midpoint_uniform_held_dm.v1" if parameters["exposure_rule"] == "midpoint" else "left_point_uniform_held_dm.v1",
                "subsamples": parameters["exposure_subsamples"], "duration_s": 0.002,
            }
        arms = {}
        for arm in planned["arms"]:
            arms[arm] = {
                "post_update_rms_m": synthetic_metric(run, arm, "post_update_rms_m"),
                "post_update_mean_square_m2": synthetic_metric(run, arm, "post_update_rms_m") ** 2,
                "pre_update_rms_m": synthetic_metric(run, arm, "post_update_rms_m") * 1.1,
                "open_loop_rms_m": 1.4e-6,
                "reconstruction_usable_fraction": 1.0,
                "open_loop_rms_series_sha256": digest,
                "science": [
                    {
                        "production": {
                            "peak_strehl": synthetic_metric(run, arm, "peak_strehl"),
                            "ee50_radius_rad": synthetic_metric(run, arm, "ee50_radius_rad"),
                            "ee80_radius_rad": synthetic_metric(run, arm, "ee80_radius_rad"),
                        },
                        "fourier_reference": {
                            "status": "available",
                            "ee50_radius_rad": 0.93 * synthetic_metric(run, arm, "ee50_radius_rad"),
                            "ee80_radius_rad": 0.95 * synthetic_metric(run, arm, "ee80_radius_rad"),
                        },
                    }
                ],
                "geometry": {"retained_lenslet_count": 72, "retained_lenslet_ids_sha256": "a" * 64, "illuminated_area_fraction": {"mean": 0.93, "min": 0.5, "max": 1.0}},
                "detector_budget": {"detected_e_full_subaperture_per_frame": 2523.0, "spectral_nodes_m": [6.4e-7, 7.5e-7, 8.6e-7][: parameters["spectral_nodes"]] + [8.7e-7] * max(0, parameters["spectral_nodes"] - 3)},
                "atmosphere": {
                    "config_hash": atmosphere_hash, "screen_size": 2 * run.config.pupil_pixels, "screen_period_m": 10.0,
                    "pairing_active": planned["atmosphere_options"] is not None, **(planned["atmosphere_options"] or {}),
                },
                "component_hashes": {"atmosphere": atmosphere_hash},
                "system_component_hashes": {"atmosphere": atmosphere_hash},
                "system_atmosphere_options": planned["atmosphere_options"],
                "wfs_exposure": exposure,
            }
        series = [1.0e-16 * (1.0 + 0.1 * math.sin(index)) for index in range(analysed)]
        paired = (
            {"status": "available", "delta_v_m2": series, "mean_m2": float(np.mean(series)), "block_standard_error_m2": 1.0e-18, "units": "m2", "series_axes": ["analysed_frame"], "series_length": analysed}
            if planned["paired_delta_v"] and len(planned["arms"]) == 2
            else {"status": "unavailable", "reason": "stand-in"}
        )
        row.update(
            status="completed",
            result={
                "schema": convergence_study.CONVERGENCE_RUN_SCHEMA,
                "config_hash": planned["config_hash"], "root_seed": planned["root_seed"], "realization_index": run.realization,
                "n_steps": planned["n_steps"], "burn_in_frames": planned["burn_in_frames"],
                "atmosphere_options": planned["atmosphere_options"], "exposure_override": planned["exposure_override"],
                "execution": {**planned["execution"], "lenslet_batch_size": 512}, "science_wavelengths_m": planned["science_wavelengths_m"],
                "arms": arms, "open_loop_rms_series_shared_by_arms": True, "paired_delta_v": paired,
                "timing": {"wall_s": 1.0 + 0.1 * len(spec["arms"])},
            },
        )
    row["ru_maxrss_bytes"] = 200 * 2**20
    row.update(study.run_protocol(scale, run, made_by))
    return row


class Launcher:
    """Stands in for ``_launch_child``: records the call and publishes the child's row."""

    def __init__(self, made_by: dict | None = None, refuse: set[str] = frozenset()) -> None:
        self.calls: list[str] = []
        self.made_by = made_by
        self.refuse = set(refuse)

    def __call__(self, scale, directory, key, path) -> None:
        self.calls.append(key)
        run = study.plan(scale)[key]
        status = "refused" if key in self.refuse else "completed"
        study._publish(path, stand_in_row(scale, run, self.made_by or study.producer(), status=status))


def act_as(monkeypatch: pytest.MonkeyPatch, made_by: dict) -> None:
    monkeypatch.setattr(study, "_code_identity", lambda: json.loads(json.dumps(made_by["code"])))
    monkeypatch.setattr(study, "producer_environment", lambda: dict(made_by["environment"]))


@pytest.fixture(autouse=True)
def controlled(monkeypatch: pytest.MonkeyPatch) -> Launcher:
    act_as(monkeypatch, PRODUCER_A)
    launcher = Launcher()
    monkeypatch.setattr(study, "_launch_child", launcher)
    return launcher


@pytest.fixture(autouse=True)
def no_system_is_ever_built(monkeypatch: pytest.MonkeyPatch) -> None:
    """Every build and run boundary is inert in these tests, imported aliases included."""

    def boundary(*arguments, **keywords):
        raise AssertionError("a build or run boundary was reached in a driver test")

    monkeypatch.setattr(scao, "build_scao_system", boundary)
    monkeypatch.setattr(convergence_study, "build_scao_system", boundary)
    monkeypatch.setattr(convergence_study, "fixed_physics_paired_run", boundary)
    monkeypatch.setattr(convergence_study, "run_component_loop", boundary)
    monkeypatch.setattr(study, "_run_child", boundary)


def run(directory: Path, scale: str = "ci", *extra: str) -> int:
    return study.main(["--scale", scale, "--output-dir", str(directory), *extra])


def snapshot(directory: Path) -> dict[str, tuple[bytes, int]]:
    return {
        str(path.relative_to(directory)): (path.read_bytes(), path.stat().st_mtime_ns)
        for path in sorted(directory.rglob("*"))
        if path.is_file()
    }


def save(directory: Path, scale: str, keys: list[str], made_by: dict) -> None:
    (directory / "runs").mkdir(parents=True, exist_ok=True)
    plan = study.plan(scale)
    for key in keys:
        (directory / "runs" / f"{key}.json").write_text(json.dumps(stand_in_row(scale, plan[key], made_by), indent=1) + "\n")


def refused(directory: Path, launcher: Launcher, match: str, scale: str = "ci") -> None:
    before = snapshot(directory)
    with pytest.raises(study.StudyRecordError, match=match):
        run(directory, scale)
    assert launcher.calls == []
    assert snapshot(directory) == before


CI_KEYS = list(study.plan("ci"))


def test_the_plans_build_no_system_and_cover_every_axis_twice() -> None:
    for scale in ("ci", "medium", "full"):
        plan = study.plan(scale)
        protocols = {key: study.planned_protocol(scale, item) for key, item in plan.items()}
        assert len(set(study._digest(value) for value in protocols.values())) == len(plan)  # every run its own protocol
        estimate = study.cost_estimate(scale, plan)
        assert estimate["label"] == "ANALYTIC_ESTIMATE" and estimate["total_s"] > 0.0
    ci = study.plan("ci")
    settings = {(item.axis, item.setting) for item in ci.values()}
    assert len(ci) == 11
    for axis in ("pupil", "detector", "spectrum", "exposure", "science"):
        family = {setting for a, setting in settings if a == axis}
        if axis != "pupil":
            family.add("baseline_plain")  # the shared plain baseline is the non-pupil axes' first setting
        assert len(family) >= 2, axis
    assert ("exposure", "mid_n1") in settings and ("exposure", "left_n2") in settings
    assert {s for a, s in settings if a == "pupil"} == {"common_s12", "common_s16", "growing_s12", "growing_s16"}
    pupil = ci["ci_pupil_common_s16_r0"]
    assert pupil.atmosphere_options.to_record() == {"band_draw_reference_screen_size": 318, "band_limit_screen_size": 238, "screen_period_rule": "pupil_diameter"}
    assert ci["ci_pupil_growing_s12_r0"].atmosphere_options.band_limit_screen_size is None
    assert ci["ci_exposure_mid_n1_r0"].exposure.sample_rule == "midpoint" and ci["ci_exposure_mid_n1_r0"].refinement_parameter == 1.0
    assert ci["ci_exposure_left_n2_r0"].refinement_parameter is None
    # The medium and full plans only load profiles and replace fields: no 12 m or 42 m system.
    medium = study.plan("medium")
    assert len(medium) == 54 and all(item.config.telescope_diameter_m == 12.0 for item in medium.values())
    full = study.plan("full")
    assert {item.setting for item in full.values()} == {"plain", "k4", "mid_n1", "mid_n2", "left_n2"}
    assert all(study.SCALES["full"]["arms"] == ("operating_expectation",) for _ in full)


def test_governed_scales_refuse_before_any_build_with_every_boundary_inert(tmp_path: Path, controlled: Launcher) -> None:
    for scale in ("medium", "full"):
        with pytest.raises(study.EnablementMissing, match="governed"):
            run(tmp_path, scale)
        with pytest.raises(study.EnablementMissing):
            study.main(["--scale", scale, "--output-dir", str(tmp_path), "--child", f"{scale}_baseline_plain_r0", str(tmp_path / "out.json")])
        assert controlled.calls == [] and not list(tmp_path.rglob("*"))
    # --plan works for a governed scale without enablement and writes nothing.
    assert run(tmp_path, "medium", "--plan") == 0
    assert not list(tmp_path.rglob("*"))


def test_a_fresh_ci_study_runs_each_planned_run_once_and_writes_one_summary(tmp_path: Path, controlled: Launcher) -> None:
    assert run(tmp_path) == 0
    assert controlled.calls == CI_KEYS
    record = json.loads((tmp_path / "convergence_ci.json").read_text())
    assert record["schema"] == study.SCHEMA and record["scale"] == "ci"
    assert record["run_producer"] == record["summarized_by"] == PRODUCER_A
    assert set(record["runs"]) == set(CI_KEYS) and set(record["plan"]) == set(CI_KEYS)
    for key, row in record["runs"].items():
        assert row == json.loads((tmp_path / "runs" / f"{key}.json").read_text())
        assert row["protocol_hash"] == study._digest(row["protocol"])
    analysis = record["analysis"]
    assert set(analysis["axes"]) == set(study.AXES)
    exposure = analysis["axes"]["exposure"]["scans"]
    assert exposure["midpoint_centred_family"]["settings"] == ["mid_n1", "mid_n2"]
    assert exposure["legacy_left_point_comparison"]["settings"] == ["baseline_plain", "left_n2", "mid_n2"]
    richardson = exposure["midpoint_centred_family"]["metrics"]["operating_expectation/post_update_rms_nm"]["richardson"]
    assert richardson["status"] == "NOT_ESTIMATED" and "fewer than three" in richardson["reason"]
    assert analysis["axes"]["spectrum"]["scans"]["scan"]["power_law_declared"] is False
    pairing = analysis["axes"]["pupil"]["pairing"]
    assert pairing["common"]["exact_physical_pairing"] is True and pairing["growing"]["common_band"] is False
    assert pairing["common"]["adjacent_dilation"][0]["exact_physical_pairing"] is True
    assert analysis["axes"]["detector"]["pairing"]["open_loop_series_shared_by_all_settings"] is True
    assert analysis["contract_tolerances"]["status"].startswith("future declared")
    assert record["science_claims"].startswith("none")
    assert not list(tmp_path.rglob(f"*{study._TEMP_MARK}*"))


def test_a_finished_study_is_left_byte_for_byte_unchanged(tmp_path: Path, controlled: Launcher, monkeypatch, capsys) -> None:
    assert run(tmp_path) == 0
    controlled.calls.clear()
    before = snapshot(tmp_path)
    for made_by in (PRODUCER_A, PRODUCER_B):
        act_as(monkeypatch, made_by)
        capsys.readouterr()
        assert run(tmp_path) == 0
        assert "nothing ran and no file was changed" in capsys.readouterr().out
        assert controlled.calls == [] and snapshot(tmp_path) == before


def test_an_interrupted_study_continues_with_only_the_missing_runs(tmp_path: Path, controlled: Launcher) -> None:
    save(tmp_path, "ci", CI_KEYS[:3], PRODUCER_A)
    kept = snapshot(tmp_path)
    assert run(tmp_path) == 0
    assert controlled.calls == CI_KEYS[3:]
    assert {name: value for name, value in snapshot(tmp_path).items() if name in kept} == kept
    whole = tmp_path / "whole"
    assert run(whole) == 0
    assert json.loads((tmp_path / "convergence_ci.json").read_text()) == json.loads((whole / "convergence_ci.json").read_text())


def test_a_refused_run_is_recorded_and_resumable(tmp_path: Path, monkeypatch) -> None:
    launcher = Launcher(refuse={"ci_detector_k8_r0"})
    monkeypatch.setattr(study, "_launch_child", launcher)
    assert run(tmp_path) == 0
    record = json.loads((tmp_path / "convergence_ci.json").read_text())
    assert record["runs"]["ci_detector_k8_r0"]["status"] == "refused"
    assert record["analysis"]["refused_runs"] == {"ci_detector_k8_r0": "ScaoConstructionError: stand-in refusal"}
    assert "detector" not in record["analysis"]["axes"] or "k8" not in record["analysis"]["axes"].get("detector", {}).get("settings", {})
    before = snapshot(tmp_path)
    launcher.calls.clear()
    assert run(tmp_path) == 0 and launcher.calls == [] and snapshot(tmp_path) == before


def _rehash(row: dict) -> None:
    row["protocol_hash"] = study._digest(row["protocol"])


def _result_edit(**changes):
    def edit(row: dict) -> None:
        row["result"].update(changes)
    return edit


CORRUPTIONS = {
    "stored hash": (lambda row: row.update(protocol_hash="0" * 64), "not the digest"),
    "payload under a stale hash": (lambda row: row["protocol"].update(config_hash="changed"), "not the digest"),
    "another configuration": (lambda row: (row["protocol"].update(config_hash="changed"), _rehash(row)), "differs in \\['config_hash'\\]"),
    "another field set": (lambda row: (row["protocol"].update(extra=1), _rehash(row)), "other fields"),
    "repeated realization": (lambda row: row.update(realization=7), "disagree"),
    "repeated seed as boolean": (lambda row: row.update(root_seed=True), "disagree"),
    "missing arm result": (lambda row: row["result"]["arms"]["noise_on"].pop("post_update_rms_m"), "missing or not numbers"),
    "boolean result": (lambda row: row["result"]["arms"]["noise_on"].update(post_update_rms_m=True), "missing or not numbers"),
    "arms out of order": (lambda row: row["result"].update(arms={k: row["result"]["arms"][k] for k in reversed(list(row["result"]["arms"]))}), "in order"),
    "different open-loop series per arm": (lambda row: row["result"]["arms"]["noise_on"].update(open_loop_rms_series_sha256="b" * 64), "different open-loop series"),
    "delta_v series length": (lambda row: row["result"]["paired_delta_v"]["delta_v_m2"].pop(), "finite numbers"),
    "delta_v units": (lambda row: row["result"]["paired_delta_v"].update(units="nm2"), "units m2"),
    "delta_v axis": (lambda row: row["result"]["paired_delta_v"].update(series_axes=["frame"]), "analysed_frame"),
    "delta_v mean": (lambda row: row["result"]["paired_delta_v"].update(mean_m2=1.0), "mean of its series"),
    "delta_v unavailable although planned": (lambda row: row["result"].update(paired_delta_v={"status": "unavailable", "reason": "x"}), "marks it unavailable"),
    "exposure metadata where none was planned": (lambda row: row["result"]["arms"]["noise_on"].update(wfs_exposure={"scheme": "midpoint_uniform_held_dm.v1", "subsamples": 1}), "did not ask for"),
    "result schema": (lambda row: row["result"].update(schema="other"), "result schema"),
    "result config": (lambda row: row["result"].update(config_hash="x"), "disagrees with the run's protocol"),
    "science count": (lambda row: row["result"]["arms"]["noise_on"]["science"].append({}), "science images"),
    "fourier reference status": (lambda row: row["result"]["arms"]["noise_on"]["science"][0].update(fourier_reference={"status": "maybe"}), "Fourier reference status"),
    "lenslet record": (lambda row: row["result"]["arms"]["noise_on"].update(geometry={}), "retained-lenslet record"),
    "unknown status": (lambda row: row.update(status="pending"), "neither completed nor refused"),
    "refused without reason": (lambda row: (row.update(status="refused"), row.pop("result")), "name its reason"),
    "refused with a result": (lambda row: row.update(status="refused", reason="x"), "carry no result"),
    "no child peak": (lambda row: row.pop("ru_maxrss_bytes"), "child peak RSS"),
    "result atmosphere options": (lambda row: row["result"].update(atmosphere_options={"band_draw_reference_screen_size": 999, "band_limit_screen_size": 99, "screen_period_rule": "pupil_array"}), "atmosphere_options disagrees"),
    "result exposure override": (lambda row: row["result"].update(exposure_override={"subsamples": 7, "sample_rule": "midpoint"}), "exposure_override disagrees"),
    "result science wavelengths": (lambda row: row["result"].update(science_wavelengths_m=[1.65e-6]), "science_wavelengths_m disagrees"),
    "result execution": (lambda row: row["result"]["execution"].update(atmosphere_band_storage="regenerate"), "execution options disagree"),
    "arm built with other atmosphere options": (lambda row: row["result"]["arms"]["noise_on"].update(system_atmosphere_options={"band_draw_reference_screen_size": 999, "band_limit_screen_size": 99, "screen_period_rule": "pupil_array"}), "other atmosphere options than the plan"),
    "arm without an atmosphere record": (lambda row: row["result"]["arms"]["noise_on"].pop("atmosphere"), "no atmosphere record"),
    "atmosphere hashes disagree within an arm": (lambda row: row["result"]["arms"]["noise_on"]["component_hashes"].update(atmosphere="c" * 64), "atmosphere hashes are missing or disagree"),
    "arms built with different atmospheres": (
        lambda row: [row["result"]["arms"]["noise_on"][part].update(**{field: "d" * 64}) for part, field in (("atmosphere", "config_hash"), ("component_hashes", "atmosphere"), ("system_component_hashes", "atmosphere"))],
        "different atmospheres",
    ),
    "producer not an identity": (lambda row: (row["protocol"].update(code="head A"), _rehash(row)), "not a code identity"),
}


@pytest.mark.parametrize("corruption", sorted(CORRUPTIONS))
def test_an_inconsistent_saved_run_is_refused_before_anything_runs(tmp_path: Path, controlled: Launcher, corruption: str) -> None:
    save(tmp_path, "ci", CI_KEYS[:2], PRODUCER_A)
    path = tmp_path / "runs" / f"{CI_KEYS[0]}.json"
    row = json.loads(path.read_text())
    change, match = CORRUPTIONS[corruption]
    change(row)
    path.write_text(json.dumps(row))
    refused(tmp_path, controlled, match)


def test_exposure_metadata_must_be_the_planned_rule(tmp_path: Path, controlled: Launcher) -> None:
    key = "ci_exposure_mid_n2_r0"
    save(tmp_path, "ci", [key], PRODUCER_A)
    path = tmp_path / "runs" / f"{key}.json"
    row = json.loads(path.read_text())
    row["result"]["arms"]["noise_on"]["wfs_exposure"]["scheme"] = "left_point_uniform_held_dm.v1"
    path.write_text(json.dumps(row))
    refused(tmp_path, controlled, "not the planned midpoint_uniform_held_dm.v1")


def test_foreign_unplanned_and_leftover_files_are_refused(tmp_path: Path, controlled: Launcher) -> None:
    (tmp_path / "runs").mkdir()
    # An S3-style row under a planned key: it carries no T2 protocol.
    (tmp_path / "runs" / f"{CI_KEYS[0]}.json").write_text(json.dumps({"label": "s12", "peak_strehl": 0.5, "protocol": None}))
    refused(tmp_path, controlled, "carries no run protocol|not the digest")
    (tmp_path / "runs" / f"{CI_KEYS[0]}.json").unlink()
    # A T1 record or any other file in runs/ is an ambiguous stranger.
    (tmp_path / "runs" / "det09_noise_isolation_2m_traced.json").write_text("{}")
    refused(tmp_path, controlled, "not planned runs")
    (tmp_path / "runs" / "det09_noise_isolation_2m_traced.json").unlink()
    (tmp_path / "runs" / f"{CI_KEYS[1]}.json{study._TEMP_MARK}123-abcd").write_text("partial")
    refused(tmp_path, controlled, "interrupted publication")
    (tmp_path / "runs" / f"{CI_KEYS[1]}.json{study._TEMP_MARK}123-abcd").unlink()
    (tmp_path / "runs" / "medium_baseline_plain_r0.json").write_text("{}")  # another scale's run
    refused(tmp_path, controlled, "not planned runs")


def test_an_unreadable_run_file_is_refused(tmp_path: Path, controlled: Launcher) -> None:
    (tmp_path / "runs").mkdir()
    (tmp_path / "runs" / f"{CI_KEYS[0]}.json").write_text("{")
    refused(tmp_path, controlled, "not readable JSON")


@pytest.mark.parametrize("change", ["environment", "code"])
def test_runs_are_not_added_under_another_producer(tmp_path: Path, controlled: Launcher, monkeypatch, change: str) -> None:
    save(tmp_path, "ci", CI_KEYS[:2], PRODUCER_A)
    other = PRODUCER_B if change == "environment" else {"code": {**CODE_A, "git_head": "head B"}, "environment": ENVIRONMENT_A}
    act_as(monkeypatch, other)
    refused(tmp_path, controlled, "would mix producers")


def test_runs_are_not_added_while_the_code_identity_is_unknown(tmp_path: Path, controlled: Launcher, monkeypatch) -> None:
    save(tmp_path, "ci", CI_KEYS[:2], UNKNOWN)
    act_as(monkeypatch, UNKNOWN)
    refused(tmp_path, controlled, "code identity of this invocation is unknown")


def test_runs_of_two_producers_are_not_summarized_together(tmp_path: Path, controlled: Launcher) -> None:
    save(tmp_path, "ci", CI_KEYS[:2], PRODUCER_A)
    save(tmp_path, "ci", CI_KEYS[2:], PRODUCER_B)
    refused(tmp_path, controlled, "2 different producers")


SUMMARY_TAMPERING = {
    "an analysis value": lambda record: record["analysis"]["cost"].update(total_wall_s=1.0e9),
    "the run producer": lambda record: record.update(run_producer=PRODUCER_B),
    "an embedded run": lambda record: record["runs"][CI_KEYS[0]]["result"]["arms"]["noise_on"].update(post_update_rms_m=0.1),
    "the schema": lambda record: record.update(schema="shwfs_ao.detector_level_convergence_study.v0"),
}


@pytest.mark.parametrize("tampering", sorted(SUMMARY_TAMPERING))
def test_a_summary_that_does_not_match_its_runs_is_never_rewritten(tmp_path: Path, controlled: Launcher, tampering: str) -> None:
    assert run(tmp_path) == 0
    controlled.calls.clear()
    summary = tmp_path / "convergence_ci.json"
    record = json.loads(summary.read_text())
    SUMMARY_TAMPERING[tampering](record)
    summary.write_text(json.dumps(record, indent=1) + "\n")
    refused(tmp_path, controlled, "does not match the summary")


def test_a_summary_with_missing_runs_is_never_rewritten(tmp_path: Path, controlled: Launcher) -> None:
    assert run(tmp_path) == 0
    controlled.calls.clear()
    (tmp_path / "runs" / f"{CI_KEYS[-1]}.json").unlink()
    refused(tmp_path, controlled, "planned runs are missing")


def test_a_child_row_of_another_producer_or_an_inconsistent_child_row_stops_the_study(tmp_path: Path, monkeypatch) -> None:
    launcher = Launcher(made_by=PRODUCER_B)
    monkeypatch.setattr(study, "_launch_child", launcher)
    with pytest.raises(study.StudyRecordError, match="another code identity or environment"):
        run(tmp_path)
    assert launcher.calls == CI_KEYS[:1] and (tmp_path / "runs" / f"{CI_KEYS[0]}.json").exists()
    assert not (tmp_path / "convergence_ci.json").exists()

    class CorruptLauncher(Launcher):
        def __call__(self, scale, directory, key, path) -> None:
            run_item = study.plan(scale)[key]
            row = stand_in_row(scale, run_item, PRODUCER_A)
            row["protocol_hash"] = "0" * 64
            study._publish(path, row)

    other = tmp_path / "other"
    monkeypatch.setattr(study, "_launch_child", CorruptLauncher())
    with pytest.raises(study.StudyRecordError, match="not the digest.*the study stops"):
        run(other)


def test_publication_never_overwrites_and_leaves_no_temporary_file(tmp_path: Path) -> None:
    path = tmp_path / "row.json"
    study._publish(path, {"a": 1})
    with pytest.raises(study.StudyRecordError, match="nothing is overwritten"):
        study._publish(path, {"a": 2})
    assert json.loads(path.read_text()) == {"a": 1}
    assert [p.name for p in tmp_path.iterdir()] == ["row.json"]


def test_the_child_entry_publishes_its_own_protocol(tmp_path: Path, monkeypatch) -> None:
    key = CI_KEYS[1]
    run_item = study.plan("ci")[key]
    body = {name: value for name, value in stand_in_row("ci", run_item, PRODUCER_A).items() if name not in ("protocol", "protocol_hash")}
    monkeypatch.setattr(study, "_run_child", lambda scale, key, directory: dict(body))
    out = tmp_path / f"{key}.json"
    assert study.main(["--scale", "ci", "--output-dir", str(tmp_path), "--child", key, str(out)]) == 0
    row = json.loads(out.read_text())
    assert row["protocol"]["code"] == CODE_A and row["protocol"]["environment"] == ENVIRONMENT_A
    assert study.check_run(out, row, study.planned_protocol("ci", run_item)) is None
    with pytest.raises(study.StudyRecordError, match="not a planned run"):
        study.main(["--scale", "ci", "--output-dir", str(tmp_path), "--child", "ci_nothing_r0", str(tmp_path / "x.json")])


def test_the_analysis_recovers_a_synthetic_order_on_the_medium_plan() -> None:
    """The medium plan's 54 rows with order-2 synthetic values: observed order 2 on three-setting scans."""

    plan = study.plan("medium")
    rows = {key: stand_in_row("medium", item, PRODUCER_A) for key, item in plan.items()}
    analysis = study.analyze("medium", rows, plan)
    detector = analysis["axes"]["detector"]["scans"]["scan"]["metrics"]["operating_expectation/post_update_rms_nm"]
    assert detector["settings_coarse_to_fine"] == ["k2", "baseline_plain", "k8"]
    assert detector["richardson"]["status"] == "ESTIMATED"
    assert detector["richardson"]["observed_order"] == pytest.approx(2.0, abs=1.0e-6)
    # The limit is the synthetic value with the detector term driven to zero.
    baseline = next(item for item in plan.values() if item.axis == "baseline").parameters
    rest = synthetic_h_squared(baseline) - (1.0 / baseline["oversampling"]) ** 2
    assert detector["richardson"]["extrapolated_limit"] == pytest.approx(170.0 * (1.0 + 0.05 * rest), rel=1.0e-9)
    assert detector["richardson"]["uncertainty_available"] is True  # three realizations give a seed SE
    midpoint = analysis["axes"]["exposure"]["scans"]["midpoint_centred_family"]["metrics"]["noise_on/peak_strehl"]
    assert midpoint["settings_coarse_to_fine"] == ["mid_n1", "mid_n2", "mid_n4", "mid_n8"]
    assert midpoint["richardson"]["assumed_order"] == 2.0 and midpoint["richardson"]["status"] == "ESTIMATED"
    spectrum = analysis["axes"]["spectrum"]["scans"]["scan"]["metrics"]["operating_expectation/post_update_rms_nm"]["richardson"]
    assert spectrum["status"] == "NOT_ESTIMATED" and "Gauss" in spectrum["reason"]
    legacy = analysis["axes"]["exposure"]["scans"]["legacy_left_point_comparison"]
    assert "richardson" not in json.dumps(legacy) and legacy["metrics"]["operating_expectation/post_update_rms_nm"]["midpoint_minus_left_point_at_n2"] is not None
    pupil = analysis["axes"]["pupil"]["scans"]["common"]["metrics"]["operating_expectation/ee50_fourier_rad"]
    assert pupil["settings_coarse_to_fine"] == ["common_s12", "common_s16", "common_s20"]
    assert analysis["axes"]["pupil"]["pairing"]["common"]["adjacent_dilation"][0]["exact_physical_pairing"] is True
    json.dumps(analysis)


def test_the_code_identity_binds_the_driver_and_the_helpers(tmp_path: Path, monkeypatch) -> None:
    # The producer binds this driver and the result-affecting helper modules (digested inside the package too).
    monkeypatch.undo()
    identity = study._code_identity()
    assert identity["script_sha256"] == hashlib.sha256((ROOT / "scripts/detector_level_convergence_study.py").read_bytes()).hexdigest()
    for name, digest in identity["result_affecting_helpers_sha256"].items():
        path = ROOT / "src" / Path(*name.split(".")).with_suffix(".py")
        assert digest == hashlib.sha256(path.read_bytes()).hexdigest(), name


@pytest.mark.slow
def test_the_real_ci_self_check_runs_in_fresh_child_processes_on_the_exposure_axis(tmp_path: Path, monkeypatch) -> None:
    """Four real runs (baseline, midpoint n = 1, 2, left n = 2) in fresh children, then an exact no-op."""

    monkeypatch.undo()
    environment = {**os.environ, "PYTHONPATH": str(ROOT / "src")}
    monkeypatch.setattr(os, "environ", environment)
    assert study.main(["--scale", "ci", "--output-dir", str(tmp_path), "--axes", "exposure"]) == 0
    record = json.loads((tmp_path / "convergence_ci.json").read_text())
    assert set(record["runs"]) == {"ci_baseline_plain_r0", "ci_exposure_mid_n1_r0", "ci_exposure_mid_n2_r0", "ci_exposure_left_n2_r0"}
    assert all(row["status"] == "completed" for row in record["runs"].values())
    assert record["analysis"]["axes"]["exposure"]["pairing"]["open_loop_series_shared_by_all_settings"] is True
    before = snapshot(tmp_path)
    assert study.main(["--scale", "ci", "--output-dir", str(tmp_path), "--axes", "exposure"]) == 0
    assert snapshot(tmp_path) == before


def test_the_arms_must_carry_exactly_the_planned_atmosphere_options(tmp_path: Path, controlled: Launcher) -> None:
    # Review round 1, F-01: the result's options and each arm's atmosphere metadata are bound to the plan.
    paired = "ci_pupil_common_s12_r0"
    save(tmp_path, "ci", [paired], PRODUCER_A)
    path = tmp_path / "runs" / f"{paired}.json"
    row = json.loads(path.read_text())
    atmosphere = row["result"]["arms"]["operating_expectation"]["atmosphere"]
    for name in ("band_draw_reference_screen_size", "band_limit_screen_size", "screen_period_rule"):
        atmosphere.pop(name)
    atmosphere["pairing_active"] = False
    path.write_text(json.dumps(row))
    refused(tmp_path, controlled, "does not carry the planned pairing options")
    plain = "ci_baseline_plain_r0"
    second = tmp_path / "plain"
    second.mkdir()
    save(second, "ci", [plain], PRODUCER_A)
    path = second / "runs" / f"{plain}.json"
    row = json.loads(path.read_text())
    row["result"]["arms"]["noise_on"]["atmosphere"].update(pairing_active=True, band_limit_screen_size=238)
    path.write_text(json.dumps(row))
    refused(second, controlled, "pairing options the plan did not ask for")
