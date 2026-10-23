"""Generated-run semantics on 16-frame fixtures of the real profile (burn-in 6).

Three fixture jobs share one configuration: display stride 1, display stride 5
and the observer-disabled control.  They check passivity, independence of the
averages from preview throttling, running-average sample sets, the binary
observation's origin/direction/weights on the actual numerical frames, flux
bookkeeping, and the run record's semantic contract.
"""

from __future__ import annotations

import copy
import json

import numpy as np
import pytest

import contract


def _blocks(job_dir, run):
    frames = np.fromfile(job_dir / "frames.bin", dtype="<f4")
    per = sum(shape[0] * shape[1] for _n, shape, _u in contract.FRAME_BLOCKS)
    out = {}
    for position, index in enumerate(run["transported"]["indices"]):
        chunk = frames[position * per:(position + 1) * per]
        offset = 0
        blocks = {}
        for name, shape, _unit in contract.FRAME_BLOCKS:
            size = shape[0] * shape[1]
            blocks[name] = chunk[offset:offset + size].reshape(shape)
            offset += size
        out[index] = blocks
    return out


def test_observer_and_transport_are_passive(fixture_runs):
    stride1, stride5, control = fixture_runs["stride1"], fixture_runs["stride5"], fixture_runs["control"]
    assert stride1["identities"]["history_digest"] == control["history_digest"]
    assert stride1["identities"]["history_config_hash"] == control["history_config_hash"]
    assert stride1["identities"]["history_digest"] == stride5["identities"]["history_digest"]
    # Every scalar history and the completed-window summary ignore the display stride.
    assert stride1["per_frame"] == stride5["per_frame"]
    assert stride1["summary"] == stride5["summary"]


def test_averages_do_not_depend_on_preview_throttling(fixture_runs):
    root = fixture_runs["root"]
    final1 = (root / "stride1" / "final.bin").read_bytes()
    final5 = (root / "stride5" / "final.bin").read_bytes()
    assert final1 == final5
    b1 = _blocks(root / "stride1", fixture_runs["stride1"])
    b5 = _blocks(root / "stride5", fixture_runs["stride5"])
    assert sorted(b5) == [0, 5, 10, 15]
    for k in b5:
        for name, _shape, _unit in contract.FRAME_BLOCKS:
            assert np.array_equal(b1[k][name], b5[k][name], equal_nan=True), (k, name)
    assert fixture_runs["stride5"]["transported"]["running_sample_count"] == [0, 0, 5, 10]


def test_running_average_includes_every_eligible_frame(fixture_runs):
    run = fixture_runs["stride1"]
    blocks = _blocks(fixture_runs["root"] / "stride1", run)
    burn = run["effective"]["parameters"]["burn_in"]
    for k, frame in blocks.items():
        for role in ("uncorrected", "corrected"):
            running = frame[f"running_observation_{role}"]
            if k < burn:
                assert np.all(np.isnan(running))
                continue
            # Mean of the float32 crops of every instantaneous observation burn..k.
            expected = np.mean([blocks[j][f"observation_{role}"].astype(float) for j in range(burn, k + 1)], axis=0)
            assert np.allclose(running, expected, rtol=2e-6, atol=1e-12)
    counts = run["transported"]["running_sample_count"]
    assert counts == [max(0, k - burn + 1) for k in run["transported"]["indices"]]
    per_frame = run["per_frame"]
    assert per_frame["running_average_peak_strehl_corrected"][:burn] == [None] * burn
    assert all(isinstance(v, float) for v in per_frame["running_average_peak_strehl_corrected"][burn:])


def test_binary_observation_is_the_weighted_shifted_psf_on_real_frames(fixture_runs):
    """obs(x) = 2/3 PSF(x) + 1/3 PSF(x - 6 cells): origin at zero, secondary towards +x, linear, unnormalized."""

    run = fixture_runs["stride1"]
    blocks = _blocks(fixture_runs["root"] / "stride1", run)
    offset = run["scene"]["separation_native_x_cells"]
    assert offset == 6 and [s["weight"] for s in run["scene"]["sources"]] == [2 / 3, 1 / 3]
    for k in (0, 7, 15):
        for role in ("uncorrected", "corrected"):
            psf = blocks[k][f"psf_{role}"].astype(float)
            obs = blocks[k][f"observation_{role}"].astype(float)
            expected = (2 / 3) * psf[:, offset:] + (1 / 3) * psf[:, :-offset]
            assert np.allclose(obs[:, offset:], expected, rtol=1e-6, atol=1e-12), (k, role)
            # A reversed axis (secondary towards -x) would not match.
            wrong = (2 / 3) * psf[:, :-offset] + (1 / 3) * psf[:, offset:]
            assert not np.allclose(obs[:, :-offset], wrong, rtol=1e-3, atol=1e-9)


def test_flux_bookkeeping_and_crop(fixture_runs):
    run = fixture_runs["stride1"]
    for role in ("uncorrected", "corrected"):
        for item in run["transported"]["instantaneous_flux"][role]:
            assert abs(item["full_flux"] - 1.0) <= 1e-12 and abs(item["full_flux_error"]) <= 1e-12
            assert 0.99 < item["native_window_fraction"] <= 1.0
            assert item["display_crop_fraction"] < item["native_window_fraction"]
        final = run["final_average"]["observation_flux"][role]
        assert abs(final["full_flux"] - final["expected_full_flux"]) <= 1e-12
        assert final["cropped_flux"] + final["lost_fraction"] * final["full_flux"] == pytest.approx(final["full_flux"], abs=1e-12)
    grid = run["grids"]["psf"]
    assert grid["crop_slices_yx"] == [[46, 110], [46, 110]] and grid["x_zero_index"] == 78
    assert run["grids"]["observation"]["full_shape_yx"] == [311, 311]


def test_numerical_self_checks_and_oracles(fixture_runs):
    run = fixture_runs["stride1"]
    checks = run["checks"]
    assert checks["all_passed"] and all(checks["passed"])
    for item in checks["oracle_frames"]:
        assert item["uncorrected_psf_max_abs_difference"] <= 1e-15
        assert item["corrected_strehl_abs_difference"] <= 1e-12
        assert item["phase_rule_max_abs_difference_rad"] <= 1e-12
    assert [item["frame"] for item in checks["oracle_frames"]] == [0, 6, 15]
    assert checks["atmosphere_digests_distinct_when_wind"] is True
    assert checks["horizon"]["equal"] and not checks["horizon"]["exceeded_travel_budget"]


def test_frame_zero_has_no_correction_and_delay_semantics(fixture_runs):
    run = fixture_runs["stride1"]
    blocks = _blocks(fixture_runs["root"] / "stride1", run)
    zero = blocks[0]
    mask = np.isfinite(zero["atmosphere_opd_m"])
    assert np.all(zero["held_correction_opd_m"][mask] == 0.0)
    assert np.array_equal(zero["pre_update_residual_opd_m"], zero["atmosphere_opd_m"], equal_nan=True)
    assert run["conventions"]["wfs_visible_delay_frames"] == run["conventions"]["queued_latency_frames"] + 1
    assert run["per_frame"]["saturation_fraction_held"][1:] == run["per_frame"]["saturation_fraction_issued"][:-1]


def test_run_record_semantics_are_enforced(fixture_runs):
    run = fixture_runs["stride1"]
    assert contract.validate_run_record(run) == []
    expected = contract.effective_parameters(fixture_runs["params"])
    assert contract.validate_run_record(run, expected_parameters=expected) == []
    assert any("controller_gain" in p for p in contract.validate_run_record(run, expected_parameters={**expected, "controller_gain": 0.3}))
    mutations = {
        "science wavelength": lambda r: r["conventions"].__setitem__("science_wavelength_m", 2.2e-6),
        "pre-update residual": lambda r: r["conventions"].__setitem__("residual_field", "post_update_residual_opd_m"),
        "OPD unit": lambda r: r["conventions"].__setitem__("opd_unit", "nm"),
        "PSF normalization": lambda r: r["conventions"].__setitem__("psf_normalization", "peak"),
        "analysis window": lambda r: r["analysis_window"].__setitem__("samples_used", 5),
        "frame times": lambda r: r["time"]["time_s"].__setitem__(3, 0.0031),
        "every eligible frame": lambda r: r["transported"]["running_sample_count"].__setitem__(-1, 3),
        "scene": lambda r: r["scene"]["sources"][1].__setitem__("weight", 0.5),
        "frames.bin block": lambda r: r["arrays"]["frames"]["blocks"][0].__setitem__("unit", "nm OPD"),
        "delays": lambda r: r["conventions"].__setitem__("wfs_visible_delay_frames", 2),
        "held saturation": lambda r: r["per_frame"]["saturation_fraction_held"].__setitem__(2, 0.5),
        "numerical checks": lambda r: r["checks"].__setitem__("all_passed", False),
        "unsupported API": lambda r: r.__setitem__("api", "ao-dynamic.api.v0"),
        "burn-in": lambda r: r["per_frame"]["running_average_peak_strehl_corrected"].__setitem__(0, 0.5),
        "zero-angle sample": lambda r: r["grids"]["psf"].__setitem__("crop_slices_yx", [[45, 109], [46, 110]]),
        "+6 x cells": lambda r: r["scene"]["sources"][1].__setitem__("index_yx", [78, 72]),
        "fixed scope": lambda r: r["effective"]["fixed"].__setitem__("telescope_diameter_m", 8.0),
        "physical identity": lambda r: r["effective"].__setitem__("physical_identity", "0" * 64),
        "r0_m = 5.0": lambda r: r["effective"]["parameters"].__setitem__("r0_m", 5.0),
    }
    for needle, mutate in mutations.items():
        mutated = copy.deepcopy(run)
        mutate(mutated)
        problems = contract.validate_run_record(mutated)
        assert problems and any(needle in p for p in problems), (needle, problems)
    # Pairing needs equal analysis windows as well as equal atmosphere samples.
    other = copy.deepcopy(fixture_runs["stride5"])
    other["effective"]["parameters"]["burn_in"] = 4
    verdict = contract.pairing_verdict(run, other)
    assert verdict["matching_atmosphere_samples"] == 16 and not verdict["paired"]
    assert verdict["expected"]["kind"] == "different_analysis_window"
    assert contract.pairing_verdict(run, fixture_runs["stride5"])["paired"]
    # The record is valid JSON without NaN or Infinity.
    json.loads(json.dumps(run, allow_nan=False))
