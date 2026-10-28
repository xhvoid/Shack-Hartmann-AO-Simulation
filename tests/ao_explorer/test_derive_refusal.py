"""Derivation refuses parents whose recorded science semantics differ from the plan (external review ER-F04).

Each case builds a disposable copy of the retained series (records copied,
large arrays linked), changes one recorded field of the baseline job --
re-hashing the arrays file into its job record where the arrays change, so
the digest check cannot be what refuses -- and requires ``command_derive`` to
refuse before it writes any derived output.  No AO trajectory runs.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import shutil

import numpy as np
import pytest

import render


SERIES = Path(__file__).resolve().parents[2] / "outputs" / "ao_explorer_v1" / "series-2m180-b3e1c66"


def _series_or_skip() -> Path:
    if not (SERIES / "series_plan.json").is_file():
        pytest.skip("the retained explorer series is not in this tree (caller-owned, ignored)")
    return SERIES


def _disposable(tmp_path: Path) -> Path:
    source = _series_or_skip()
    target = tmp_path / source.name
    target.mkdir()
    shutil.copy2(source / "series_plan.json", target / "series_plan.json")
    plan = json.loads((source / "series_plan.json").read_text())
    for job in plan["jobs"]:
        if job["role"] not in ("production", "pilot"):
            continue
        attempt = render._attempt(source, job["job_id"])
        copy = target / "jobs" / job["job_id"] / attempt.name
        copy.mkdir(parents=True)
        for name in ("status.json", "job_record.json"):
            shutil.copy2(attempt / name, copy / name)
        (copy / "mean_psfs.npz").symlink_to(attempt / "mean_psfs.npz")
    return target


def _baseline(series: Path):
    attempt = render._attempt(series, "case-baseline")
    path = attempt / "job_record.json"
    return attempt, path, json.loads(path.read_text())


def _accumulator(record, role="corrected"):
    return record["observer"]["accumulators"][role]


def _shift_axis(attempt: Path, record) -> None:
    link = attempt / "mean_psfs.npz"
    with np.load(link) as data:
        arrays = {name: np.array(data[name]) for name in data.files}
    link.unlink()
    arrays["x_angle_rad"] = arrays["x_angle_rad"] * (1.0 + 1e-9)
    np.savez(attempt / "mean_psfs.npz", **arrays)
    record["files"]["mean_psfs.npz"]["sha256"] = hashlib.sha256((attempt / "mean_psfs.npz").read_bytes()).hexdigest()


DEFECTS = [
    ("wavelength", lambda attempt, r: _accumulator(r).__setitem__("wavelengths_m", [7e-07]), "parent wavelength"),
    ("post-update-residual", lambda attempt, r: _accumulator(r).__setitem__("residual", "post_update"), "pre-update residual"),
    ("normalization", lambda attempt, r: _accumulator(r).__setitem__("flux_denominator", "calibrated_detector_electrons"), "normalization"),
    ("image-sampling", lambda attempt, r: r["observer"]["sampling_metadata"].__setitem__("normalization", "peak"), "sampling/normalization"),
    ("weights", lambda attempt, r: _accumulator(r, "uncorrected")["selection"].__setitem__("uniform_weights", False), "window, weights"),
    ("recentring", lambda attempt, r: _accumulator(r)["metadata"].__setitem__("recentering", "peak"), "recentering"),
    ("axis", _shift_axis, "x angle axis"),
]


@pytest.mark.parametrize("name,mutate,expected", DEFECTS, ids=[item[0] for item in DEFECTS])
def test_derive_refuses_incompatible_parent_semantics(tmp_path, name, mutate, expected):
    series = _disposable(tmp_path)
    attempt, path, record = _baseline(series)
    mutate(attempt, record)
    path.write_text(json.dumps(record, indent=1) + "\n")
    with pytest.raises(render.RenderError, match=expected):
        render.command_derive(series)
    assert not (series / "derived").exists(), "a refused derivation must not leave derived output"


def test_derive_accepts_the_retained_parents(tmp_path):
    # Control: the same disposable copy, unchanged, derives the nine targets
    # with labels taken from the validated parent metadata.
    series = _disposable(tmp_path)
    outputs = render.command_derive(series)
    assert len(outputs["entries"]) == 9
    parent = outputs["entries"][1]["observations"]["corrected"]["parent"]
    assert parent["field"] == "pre_update_residual_opd_m" and parent["wavelength_m"] == 1.65e-6
    assert parent["normalization"] == "unit total flux over the complete uncropped propagator grid"
