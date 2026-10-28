"""AO-REF-018 contracts for the cross-backend validation package.

These tests are deliberately unmarked: they run in the native CI selection
and need no optional dependency.  They pin the backend-neutral physical
estimators, the report/baseline document contract, the integrity of the
packaged baseline, the evaluation semantics, and the completeness of every
failure message (observed value, expected value or range, tolerance with
units, and the compared hashes).  The ``hcipy`` marker stays reserved for
tests that execute the suite itself.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import subprocess
import sys

import numpy as np
import pytest

from shwfs_ao.backends.hcipy import (
    OptionalDependencyError,
    hcipy_installed,
)
from shwfs_ao.validation.cross_backend import (
    CrossBackendConfig,
    CrossBackendError,
    comparison_config_record,
    run_cross_backend_report,
    statistical_definition_for,
)
from shwfs_ao.validation.physical import (
    PhysicalEstimatorError,
    centroid_xy_px,
    encircled_energy_radius_rad,
    mean_square_column_difference,
    normalized_singular_spectrum,
)
from shwfs_ao.validation.regression import (
    CROSS_BACKEND_BASELINE_SCHEMA_NAME,
    CROSS_BACKEND_BASELINE_SCHEMA_VERSION,
    CROSS_BACKEND_REPORT_SCHEMA_NAME,
    CROSS_BACKEND_BASELINE_SCHEMA_RESOURCE,
    COMPARISONS_REQUIRING_STATISTICAL_DEFINITION,
    METRIC_CONTRACT,
    REQUIRED_COMPARISON_KINDS,
    REQUIRED_COMPONENT_HASH_KEYS,
    REQUIRED_FIXTURE_HASH_KEYS,
    REQUIRED_METRIC_NAMES,
    BaselineContractError,
    baseline_from_report,
    evaluate_report_against_baseline,
    load_cross_backend_baseline,
    validate_baseline_against_schema,
    validate_cross_backend_baseline,
    validate_cross_backend_report,
)
from shwfs_ao.io.resources import read_text_resource
from shwfs_ao.core.hashing import (
    HASH_SCHEMA_ID, canonical_json_bytes, stable_array_descriptor, stable_hash,
)
from shwfs_ao.validation.numerical_identity import (
    NUMERICAL_INPUTS,
    dm_semantic_hash,
    dm_source_failure,
    numerical_input_failure,
    numerical_input_record,
    numerical_input_values,
)


HCIPY_INSTALLED = hcipy_installed()

TICKET_COMPARISON_KINDS = (
    "pupil_mask_and_throughput",
    "zernike_modes",
    "atmosphere_statistics",
    "wfs_tip_tilt_response",
    "lenslet_spot_morphology",
    "dm_single_actuator_influence",
    "dm_static_fitting",
    "interaction_matrix_identity",
    "normalized_singular_spectrum",
    "psf_normalization",
    "strehl_ratio",
    "closed_loop_residual",
    "runtime_and_memory",
)

# The library is the single source of truth for the required inventory; the
# packaged baseline and every synthetic contract fixture reuse it.
SHARED_FIXTURE_HASH_KEYS = set(REQUIRED_FIXTURE_HASH_KEYS)

COMPONENT_HASH_KEYS = set(REQUIRED_COMPONENT_HASH_KEYS)


def _hash64(seed: str) -> str:
    return hashlib.sha256(seed.encode("utf-8")).hexdigest()


def _probe_metric(kind: str, name: str) -> dict:
    # Shape each probe metric to satisfy its pinned METRIC_CONTRACT (level,
    # units, criterion type, and canonical expectation), so the synthetic report
    # is a valid document under the scientific-meaning contract.
    level, units, criterion_type, expected = METRIC_CONTRACT[kind][name]
    metric = {
        "name": name,
        "level": level,
        "units": units,
        "rationale": "Contract-test probe metric.",
    }
    if criterion_type == "equals":
        # A pinned universal expectation is a bool/int/str; a baseline-specific
        # one (the sentinel) gets a neutral placeholder the equals gate accepts.
        value = expected if isinstance(expected, (bool, int, str)) else 1
        metric["value"] = value
        metric["pass_criterion"] = {"type": "equals", "expected": value}
    elif criterion_type == "abs_tolerance":
        metric["value"] = 0.0
        metric["pass_criterion"] = {
            "type": "abs_tolerance",
            "expected": 0.0,
            "tolerance": 1.0,
        }
    elif criterion_type == "range":
        metric["value"] = 1.0
        metric["pass_criterion"] = {"type": "range", "low": 0.5, "high": 1.5}
    else:  # informational
        metric["value"] = 0.5
        metric["pass_criterion"] = {"type": "informational"}
    return metric


def _probe_comparison(kind: str) -> dict:
    # Emit exactly the required metric inventory for the kind, each metric shaped
    # to satisfy its pinned scientific-meaning contract.
    comparison = {
        "comparison_kind": kind,
        "attribution": "Synthetic comparison for contract tests.",
        "metrics": [
            _probe_metric(kind, name)
            for name in sorted(REQUIRED_METRIC_NAMES[kind])
        ],
    }
    # An estimated comparison must state its estimator and uncertainty, and
    # must do so as the four checkable fields rather than as prose.
    if kind in COMPARISONS_REQUIRING_STATISTICAL_DEFINITION:
        comparison["statistical_definition"] = _probe_statistical_definition()
    return comparison


# One real configuration, so the report's comparison_config is a record the
# producer could have minted: the contract now binds config_hash to the fields
# beside it, and a stub mapping carrying an arbitrary hash is exactly what that
# binding exists to reject.
_CONTRACT_TEST_CONFIG = CrossBackendConfig(root_seed=7)


def _probe_statistical_definition() -> dict:
    """The smallest statistical_definition the contract accepts.

    The prose is written out here rather than imported, so a field quietly
    dropped from the contract shows up as a test that stops exercising it.  The
    sample count and the lag record are not prose and are not written out: they
    are determined by the configuration this fixture reports under, and the
    contract now requires them to agree with it.  Stating them independently
    would make this fixture the one document in the suite whose statistics
    describe a different run than its own configuration.
    """

    return {
        **statistical_definition_for(_CONTRACT_TEST_CONFIG),
        "estimator": "Synthetic contract-test estimator over probe values.",
        "uncertainty_method": (
            "Synthetic contract-test standard error across the probe values."
        ),
        "narrative": (
            "Synthetic contract-test estimator over the probe values; "
            "uncertainty is not measured in this fixture."
        ),
    }


def _minimal_report() -> dict:
    report = {
        "artifact_schema_name": CROSS_BACKEND_REPORT_SCHEMA_NAME,
        "artifact_schema_version": CROSS_BACKEND_BASELINE_SCHEMA_VERSION,
        "comparison_config": comparison_config_record(_CONTRACT_TEST_CONFIG),
        "root_seed": _CONTRACT_TEST_CONFIG.root_seed,
        "conventions": {
            "command_unit": "m_opd_equivalent",
            "residual_sign_convention": (
                "residual_opd_m = atmosphere_opd_m - dm_correction_opd_m"
            ),
            "measurement_unit": "pixel",
        },
        "component_hashes": {
            key: _hash64(key) for key in REQUIRED_COMPONENT_HASH_KEYS
        },
        "fixture_hashes": {
            key: _hash64(key) for key in REQUIRED_FIXTURE_HASH_KEYS
        },
        "environment": {
            "python_version": "3.14.0",
            "numpy_version": "2.5.0",
            "shwfs_ao_version": "0.1.0",
            "hcipy_version": "0.7.0",
            "platform": "contract-test",
            "dependency_constraint_file": "unrecorded",
            "dependency_constraint_sha256": "unrecorded",
        },
        "comparisons": [
            _probe_comparison(kind) for kind in REQUIRED_COMPARISON_KINDS
        ],
    }
    report["numerical_inputs"] = {}
    for index, (name, (group, _, _, _)) in enumerate(NUMERICAL_INPUTS.items()):
        values = np.array([float(index)])
        payload = None
        backend_payload = None
        config_hash = _hash64(name)
        if group == "fixture_hashes":
            report[group][name] = stable_hash(
                values, namespace="cross_backend_fixture",
            )
        else:
            config = dict.fromkeys((
                "config", "sampled_x_m", "sampled_y_m", "pupil_mask",
                "actuator_ids", "actuator_centers_m", "actuator_pitch_m",
                "dead_actuator_mask", "stuck_actuator_mask", "command_unit",
                "command_convention", "synthesis_convention", "backend_identity",
                "backend_name", "backend_config_hash", "influence_functions",
            ))
            config["influence_functions"] = values
            backend_name = name.removesuffix("_dm")
            config["backend_name"] = backend_name
            config["backend_identity"] = (
                "shwfs_ao.backends.native.dm.NativeDmBackend" if name == "native_dm"
                else "shwfs_ao.backends.hcipy.dm.HcipyDmBackend"
            )
            backend_payload = canonical_json_bytes({
                "hash_schema": HASH_SCHEMA_ID, "namespace": "component_config",
                "value": {"component_name": f"{backend_name}.dm_spatial_backend",
                          "config": {"influence_functions": values,
                                     "command_unit": "m_opd_equivalent"}},
            }).decode()
            config["backend_config_hash"] = hashlib.sha256(backend_payload.encode()).hexdigest()
            payload = canonical_json_bytes({
                "hash_schema": HASH_SCHEMA_ID, "namespace": "component_config",
                "value": {"component_name": "deformable_mirror", "config": config},
            }).decode()
            report[group][name] = hashlib.sha256(payload.encode()).hexdigest()
            config_hash = dm_semantic_hash(payload, backend_payload)
        report["numerical_inputs"][name] = numerical_input_record(
            values,
            source_hash=report[group][name],
            configuration_hash=config_hash,
            source_payload=payload,
            backend_source_payload=backend_payload,
        )
    return report


def _minimal_baseline() -> dict:
    return baseline_from_report(
        _minimal_report(),
        generator={
            "generator_name": "contract-test-generator",
            "generator_version": "1",
            "source_commit": _hash64("commit")[:40],
            "source_tree_clean": True,
        },
        acceptance={
            "reason": "Contract-test acceptance.",
            "review_reference": "AO-REF-018",
            "accepted_at_utc": "2026-07-17T00:00:00+00:00",
        },
    )


def _replace_numerical_input(report: dict, name: str, values: np.ndarray) -> None:
    """Simulate a fresh platform run, including honest byte provenance."""
    group = NUMERICAL_INPUTS[name][0]
    record = report["numerical_inputs"][name]
    payload = None
    backend_payload = None
    if group == "fixture_hashes":
        source_hash = stable_hash(values, namespace="cross_backend_fixture")
    else:
        backend = json.loads(record["backend_source_payload"])
        backend_config = dict(dict(backend["$mapping"])["value"]["$mapping"])["config"]["$mapping"]
        for pair in backend_config:
            if pair[0] == "influence_functions":
                pair[1] = {"$array": stable_array_descriptor(values)}
        backend_payload = json.dumps(backend, sort_keys=True, separators=(",", ":"))
        parsed = json.loads(record["source_payload"])
        envelope = dict(parsed["$mapping"])
        config = dict(envelope["value"]["$mapping"])["config"]["$mapping"]
        for pair in config:
            if pair[0] == "influence_functions":
                pair[1] = {"$array": stable_array_descriptor(values)}
            if pair[0] == "backend_config_hash":
                pair[1] = hashlib.sha256(backend_payload.encode()).hexdigest()
        payload = json.dumps(parsed, sort_keys=True, separators=(",", ":"))
        source_hash = hashlib.sha256(payload.encode()).hexdigest()
    report[group][name] = source_hash
    report["numerical_inputs"][name] = numerical_input_record(
        values, source_hash=source_hash,
        configuration_hash=record["configuration_hash"],
        source_payload=payload,
        backend_source_payload=backend_payload,
    )


def _drifted_raw_hash(baseline: dict, name: str) -> str:
    """The raw hash an honest run records when ``name`` drifts by 1 %."""
    run = _report_copy(baseline)
    values = numerical_input_values(run["numerical_inputs"][name])
    _replace_numerical_input(run, name, 1.01 * values)
    return run[NUMERICAL_INPUTS[name][0]][name]


def _dm_config_pairs(parsed: dict) -> list:
    """The mutable ``[key, value]`` config pairs of a parsed DM hash preimage."""
    return dict(dict(parsed["$mapping"])["value"]["$mapping"])["config"]["$mapping"]


def _canonical_text(parsed: dict) -> str:
    return json.dumps(
        parsed, ensure_ascii=False, allow_nan=False,
        sort_keys=True, separators=(",", ":"),
    )


def _set_pairs(pairs: list, fields: dict) -> None:
    found = {pair[0] for pair in pairs} & set(fields)
    assert found == set(fields), f"preimage has no {set(fields) - found}"
    for pair in pairs:
        if pair[0] in fields:
            pair[1] = fields[pair[0]]


def _rewrite_dm_hash_preimages(
    document: dict, name: str, *,
    model: dict | None = None,
    backend: dict | None = None,
    backend_text: str | None = None,
) -> None:
    """Edit one DM witness's hash preimages and re-mint every hash over them.

    The model preimage's ``backend_config_hash``, the witness ``source_hash``
    and the raw component hash beside it are recomputed from the edited text,
    so no preimage check can object to anything but the edit itself.
    ``configuration_hash`` is left as it was; a caller whose edit changes the
    semantics re-mints it explicitly.  ``backend_text`` replaces the backend
    preimage verbatim, for text that is not a parseable preimage at all.
    """
    record = document["numerical_inputs"][name]
    if backend_text is None:
        parsed_backend = json.loads(record["backend_source_payload"])
        _set_pairs(_dm_config_pairs(parsed_backend), backend or {})
        backend_text = _canonical_text(parsed_backend)
    backend_hash = hashlib.sha256(
        backend_text.encode("utf-8", "surrogatepass")
    ).hexdigest()
    parsed = json.loads(record["source_payload"])
    _set_pairs(
        _dm_config_pairs(parsed),
        {**(model or {}), "backend_config_hash": backend_hash},
    )
    payload = _canonical_text(parsed)
    record.update(
        source_payload=payload,
        backend_source_payload=backend_text,
        source_hash=hashlib.sha256(payload.encode()).hexdigest(),
    )
    document["component_hashes"][name] = record["source_hash"]


@pytest.mark.parametrize("name", tuple(NUMERICAL_INPUTS))
def test_platform_roundoff_keeps_numerical_identity(name, packaged_baseline):
    report = _report_copy(packaged_baseline)
    values = numerical_input_values(report["numerical_inputs"][name]).copy()
    # Perturb every value, including zero and sign changes in tiny samples.
    # No rounding bins are used, so adjacent floats remain comparable even
    # when they straddle a decimal quantization boundary.
    for _ in range(8):
        values = np.nextafter(values, np.inf)
    _replace_numerical_input(report, name, values)
    group = NUMERICAL_INPUTS[name][0]
    assert report[group][name] != packaged_baseline[group][name]
    assert evaluate_report_against_baseline(report, packaged_baseline) == ()


@pytest.mark.parametrize("name", tuple(NUMERICAL_INPUTS))
def test_one_drifted_input_sample_fails_before_physics(name, packaged_baseline):
    report = _report_copy(packaged_baseline)
    values = numerical_input_values(report["numerical_inputs"][name]).copy()
    _, units, rtol, atol = NUMERICAL_INPUTS[name]
    index = np.unravel_index(int(np.nanargmax(np.abs(values))), values.shape)
    values[index] += 100 * (atol + rtol * abs(values[index]))
    _replace_numerical_input(report, name, values)
    failures = evaluate_report_against_baseline(report, packaged_baseline)
    assert len(failures) == 1
    assert name in failures[0]
    assert "sample" in failures[0]
    assert units in failures[0]
    assert "metric tolerances do not apply" in failures[0]


def test_same_dm_hash_does_not_hide_a_changed_influence(packaged_baseline):
    report = _report_copy(packaged_baseline)
    record = report["numerical_inputs"]["native_dm"]
    values = numerical_input_values(record).copy()
    values.flat[0] += 1e-7
    report["numerical_inputs"]["native_dm"] = numerical_input_record(
        values, source_hash=record["source_hash"],
        configuration_hash=record["configuration_hash"],
        source_payload=record["source_payload"],
        backend_source_payload=record["backend_source_payload"],
    )
    failures = evaluate_report_against_baseline(report, packaged_baseline)
    assert len(failures) == 1
    assert "native_dm" in failures[0]


def test_changed_dm_semantics_fail_even_with_identical_arrays(packaged_baseline):
    report = _report_copy(packaged_baseline)
    report["numerical_inputs"]["hcipy_dm"]["configuration_hash"] = _hash64("new")
    failures = evaluate_report_against_baseline(report, packaged_baseline)
    assert len(failures) == 1
    assert "configuration_hash does not bind" in failures[0]


@pytest.mark.parametrize("name", ["native_dm", "hcipy_dm"])
def test_self_consistent_arbitrary_dm_hash_is_rejected(name):
    baseline = _minimal_baseline()
    report = _report_copy(baseline)
    report["component_hashes"][name] = "f" * 64
    report["numerical_inputs"][name]["source_hash"] = "f" * 64
    failures = evaluate_report_against_baseline(report, baseline)
    assert len(failures) == 1
    assert "raw DM hash does not match source_payload" in failures[0]
    with pytest.raises(BaselineContractError, match="raw DM hash"):
        validate_cross_backend_baseline(report)


@pytest.mark.parametrize("change", ["whitespace", "duplicate", "backend_hash", "component_name", "sibling"])
def test_noncanonical_or_unbound_dm_payload_is_rejected(change):
    baseline = _minimal_baseline()
    report = _report_copy(baseline)
    record = report["numerical_inputs"]["native_dm"]
    parsed = json.loads(record["source_payload"])
    config = dict(dict(parsed["$mapping"])["value"]["$mapping"])["config"]["$mapping"]
    if change == "duplicate":
        config.insert(0, ["command_unit", "incorrect_and_discarded"])
    elif change == "backend_hash":
        next(pair for pair in config if pair[0] == "backend_config_hash")[1] = "f" * 64
    elif change == "component_name":
        value = dict(parsed["$mapping"])["value"]["$mapping"]
        next(pair for pair in value if pair[0] == "component_name")[1] = "native.dm_spatial_backend"
    elif change == "sibling":
        parsed["discarded"] = "invalid canonical sibling"
    payload = (
        json.dumps(parsed, indent=2) if change == "whitespace" else
        json.dumps(parsed, sort_keys=True, separators=(",", ":"))
    )
    record["source_payload"] = payload
    record["source_hash"] = hashlib.sha256(payload.encode()).hexdigest()
    report["component_hashes"]["native_dm"] = record["source_hash"]
    failures = evaluate_report_against_baseline(report, baseline)
    assert len(failures) == 1
    assert "source_payload" in failures[0]
    with pytest.raises(BaselineContractError, match="source_payload"):
        validate_cross_backend_baseline(report)


def test_inner_backend_semantics_remain_exact_even_with_matching_influences():
    baseline = _minimal_baseline()
    report = _report_copy(baseline)
    record = report["numerical_inputs"]["native_dm"]
    parsed = json.loads(record["backend_source_payload"])
    config = dict(dict(parsed["$mapping"])["value"]["$mapping"])["config"]["$mapping"]
    next(pair for pair in config if pair[0] == "command_unit")[1] = "different"
    backend_payload = json.dumps(parsed, sort_keys=True, separators=(",", ":"))
    parsed = json.loads(record["source_payload"])
    config = dict(dict(parsed["$mapping"])["value"]["$mapping"])["config"]["$mapping"]
    next(pair for pair in config if pair[0] == "backend_config_hash")[1] = hashlib.sha256(backend_payload.encode()).hexdigest()
    payload = json.dumps(parsed, sort_keys=True, separators=(",", ":"))
    record.update(
        source_payload=payload, backend_source_payload=backend_payload,
        source_hash=hashlib.sha256(payload.encode()).hexdigest(),
        configuration_hash=dm_semantic_hash(payload, backend_payload),
    )
    report["component_hashes"]["native_dm"] = record["source_hash"]
    failures = evaluate_report_against_baseline(report, baseline)
    assert len(failures) == 1
    assert "configuration_hash differs" in failures[0]


# Each binding between raw byte provenance and its witness gets a case that
# only that binding can refuse.  The witnessed samples stay exactly the
# baseline's, so the full-array comparison passes; every other hash is
# re-minted, so every other check passes.  In the hash and influence cases,
# without the binding under test the evaluator would accept a run whose
# recorded bytes are a 1 % drifted input; the backend-identity case guards a
# baseline that mislabels the backend class behind its witness.


@pytest.mark.parametrize(
    "name",
    [name for name, spec in NUMERICAL_INPUTS.items() if spec[0] == "fixture_hashes"],
)
def test_a_fixture_raw_hash_must_be_the_hash_of_its_witnessed_array(
    name, packaged_baseline,
):
    report = _report_copy(packaged_baseline)
    drifted = _drifted_raw_hash(packaged_baseline, name)
    # The raw hash and the witness agree with each other, but name an array
    # other than the one the witness carries.
    report["fixture_hashes"][name] = drifted
    report["numerical_inputs"][name]["source_hash"] = drifted
    failures = evaluate_report_against_baseline(report, packaged_baseline)
    assert len(failures) == 1
    assert "raw fixture hash does not match the witnessed array" in failures[0]
    with pytest.raises(BaselineContractError, match="raw fixture hash"):
        validate_cross_backend_baseline(report)


@pytest.mark.parametrize("name", tuple(NUMERICAL_INPUTS))
def test_a_witness_must_name_the_raw_hash_recorded_beside_it(
    name, packaged_baseline,
):
    report = _report_copy(packaged_baseline)
    drifted = _drifted_raw_hash(packaged_baseline, name)
    if NUMERICAL_INPUTS[name][0] == "fixture_hashes":
        # The raw hash is the stable hash of the witnessed array, but the
        # witness claims to be the record of a different one.
        report["numerical_inputs"][name]["source_hash"] = drifted
    else:
        # The witness is the baseline's own, preimages included, and is
        # self-consistent; the run's raw DM hash is that of a drifted stack.
        report["component_hashes"][name] = drifted
    failures = evaluate_report_against_baseline(report, packaged_baseline)
    assert len(failures) == 1
    assert "raw hash does not match the numerical input witness" in failures[0]
    with pytest.raises(BaselineContractError, match="numerical input witness"):
        validate_cross_backend_baseline(report)


@pytest.mark.parametrize(
    ("name", "identity"),
    [
        ("native_dm", "shwfs_ao.backends.hcipy.dm.HcipyDmBackend"),
        ("hcipy_dm", "shwfs_ao.backends.native.dm.NativeDmBackend"),
    ],
)
def test_a_dm_preimage_must_name_the_backend_of_its_witness(
    name, identity, packaged_baseline,
):
    # A preimage naming the other backend's class changes the semantic hash,
    # so against a correct baseline configuration_hash would differ anyway.
    # Only a baseline that records the mislabel throughout, semantic hash
    # included, isolates the identity check, and acceptance must refuse it.
    # The backend_name half of the check cannot be isolated this way: the
    # semantic hash decodes the backend preimage under the recorded name and
    # the backend preimage check under the witness's own, so once the two
    # names differ no backend preimage satisfies both.  The next test pins
    # that half's diagnostic instead.
    baseline = _report_copy(packaged_baseline)
    _rewrite_dm_hash_preimages(baseline, name, model={"backend_identity": identity})
    record = baseline["numerical_inputs"][name]
    record["configuration_hash"] = dm_semantic_hash(
        record["source_payload"], record["backend_source_payload"],
    )
    with pytest.raises(BaselineContractError, match="does not match its named backend"):
        validate_cross_backend_baseline(baseline)
    with pytest.raises(BaselineContractError, match="does not match its named backend"):
        evaluate_report_against_baseline(_report_copy(baseline), baseline)


@pytest.mark.parametrize(("name", "other"), [("native_dm", "hcipy"), ("hcipy_dm", "native")])
def test_a_dm_preimage_naming_another_backend_is_reported_as_such(
    name, other, packaged_baseline,
):
    # Without the backend_name check this relabel is still refused, later and
    # as an undecodable backend preimage, because the semantic hash decodes
    # that preimage under the recorded name.  The failure must name the
    # mislabel rather than a malformed payload.
    report = _report_copy(packaged_baseline)
    _rewrite_dm_hash_preimages(report, name, model={"backend_name": other})
    detail = "DM source_payload does not match its named backend"
    assert dm_source_failure(name, report["numerical_inputs"][name]) == detail
    failures = evaluate_report_against_baseline(report, packaged_baseline)
    assert len(failures) == 1
    assert detail in failures[0]
    with pytest.raises(BaselineContractError, match="does not match its named backend"):
        validate_cross_backend_baseline(report)


@pytest.mark.parametrize("name", ["native_dm", "hcipy_dm"])
@pytest.mark.parametrize(
    ("preimage", "detail"),
    [
        ("model", "DM source_payload does not bind the witnessed influence array"),
        (
            "backend",
            "DM backend source_payload does not bind the witnessed influence array",
        ),
    ],
)
def test_each_dm_preimage_must_bind_the_witnessed_influence_array(
    name, preimage, detail, packaged_baseline,
):
    # Neither semantic hash includes the influence descriptor, so the edited
    # preimage leaves configuration_hash valid and only this binding remains.
    report = _report_copy(packaged_baseline)
    values = numerical_input_values(report["numerical_inputs"][name])
    drifted = {"influence_functions": {"$array": stable_array_descriptor(1.01 * values)}}
    _rewrite_dm_hash_preimages(report, name, **{preimage: drifted})
    failures = evaluate_report_against_baseline(report, packaged_baseline)
    assert len(failures) == 1
    assert detail in failures[0]
    with pytest.raises(BaselineContractError, match="witnessed influence array"):
        validate_cross_backend_baseline(report)


@pytest.mark.parametrize("field", ["source_payload", "backend_source_payload"])
@pytest.mark.parametrize(
    "text",
    [
        # A JSON document can carry a lone surrogate as an escape; it has no
        # UTF-8 encoding and therefore no hash preimage.
        '{"$mapping":[["hash_schema","\ud800"]]}',
        # 5 000 levels decode on Python 3.14 and exhaust the interpreter in
        # the canonical-order walk; 100 000 exhaust the JSON decoder itself.
        "[" * 5_000 + "]" * 5_000,
        "[" * 100_000 + "]" * 100_000,
    ],
    ids=["lone_surrogate", "nested_5000", "nested_100000"],
)
def test_an_unencodable_or_deeply_nested_dm_preimage_is_an_ordinary_failure(
    field, text,
):
    baseline = _minimal_baseline()
    report = _report_copy(baseline)
    if field == "source_payload":
        record = report["numerical_inputs"]["native_dm"]
        record["source_payload"] = text
        record["source_hash"] = hashlib.sha256(
            text.encode("utf-8", "surrogatepass")
        ).hexdigest()
        report["component_hashes"]["native_dm"] = record["source_hash"]
    else:
        _rewrite_dm_hash_preimages(report, "native_dm", backend_text=text)
    failures = evaluate_report_against_baseline(report, baseline)
    assert len(failures) == 1
    assert "invalid canonical DM source_payload" in failures[0]
    with pytest.raises(BaselineContractError, match="invalid canonical DM"):
        validate_cross_backend_baseline(report)
    # The producer derives configuration_hash through the same decoder.
    with pytest.raises(ValueError, match="invalid canonical DM source_payload"):
        dm_semantic_hash(text, text)


def test_numerical_mask_is_exact_even_when_finite_values_agree():
    options = {"source_hash": _hash64("source"), "configuration_hash": _hash64("cfg")}
    expected = numerical_input_record(np.array([1e-7, np.nan]), **options)
    observed = numerical_input_record(np.array([1e-7, 0.0]), **options)
    assert numerical_input_failure("static_opd_m", expected, expected) is None
    assert numerical_input_failure("static_opd_m", observed, expected) == "non-finite pupil-mask locations differ"


def test_numerical_witness_is_endian_independent_and_content_checked():
    values = np.array([0, -1, 0.123456789012345, 1e-20])
    options = {"source_hash": _hash64("source"), "configuration_hash": _hash64("cfg")}
    record = numerical_input_record(values.astype("<f8"), **options)
    assert record == numerical_input_record(values.astype(">f8"), **options)
    np.testing.assert_array_equal(numerical_input_values(record), values)
    record["values_sha256"] = _hash64("wrong data")
    with pytest.raises(ValueError, match="does not match its data"):
        numerical_input_values(record)


@pytest.mark.parametrize("change", ["missing", "shape", "encoding", "data", "extra"])
def test_report_rejects_incomplete_or_corrupt_numerical_witness(change):
    report = _minimal_report()
    inputs = report["numerical_inputs"]
    if change == "missing":
        del inputs["static_opd_m"]
    elif change == "extra":
        inputs["static_opd_m"]["rtol"] = 1e9
    else:
        inputs["static_opd_m"][change] = {
            "shape": [1000000000000], "encoding": "unknown", "data": "broken",
        }[change]
    with pytest.raises(BaselineContractError, match="numerical_input"):
        validate_cross_backend_report(report)


@pytest.fixture(scope="module")
def packaged_baseline() -> dict:
    return json.loads(json.dumps(dict(load_cross_backend_baseline())))


def _report_copy(baseline: dict) -> dict:
    return json.loads(json.dumps(baseline))


def _reconfigured_report(baseline: dict, **overrides) -> dict:
    """A copy of ``baseline`` that honestly describes a different configuration.

    Overwriting ``config_hash`` in place no longer produces a document anything
    will evaluate: the hash is bound to the fields recorded beside it, and the
    seed is recorded twice and required to agree, so an edited field without a
    reminted hash is malformed rather than merely different.  Reaching the
    evaluation-time identity gate therefore means minting a real configuration
    record — which is also the only thing a second run could actually produce.
    """

    report = _report_copy(baseline)
    config = CrossBackendConfig(**overrides)
    report["comparison_config"] = comparison_config_record(config)
    report["root_seed"] = config.root_seed
    return report


def _set_metric_value(document: dict, kind: str, name: str, value) -> None:
    for comparison in document["comparisons"]:
        if comparison["comparison_kind"] != kind:
            continue
        for metric in comparison["metrics"]:
            if metric["name"] == name:
                metric["value"] = value
                return
    raise AssertionError(f"metric {kind}/{name} not found")


def _remove_metric(document: dict, kind: str, name: str) -> None:
    for comparison in document["comparisons"]:
        if comparison["comparison_kind"] == kind:
            metrics = [
                metric
                for metric in comparison["metrics"]
                if metric["name"] != name
            ]
            assert len(metrics) == len(comparison["metrics"]) - 1
            comparison["metrics"] = metrics
            return
    raise AssertionError(f"comparison {kind} not found")


class TestPhysicalEstimators:
    def test_centroid_of_a_point_mass_is_its_column_row_position(self):
        spot = np.zeros((7, 9))
        spot[2, 5] = 3.0
        assert centroid_xy_px(spot) == (5.0, 2.0)

    def test_centroid_weights_flux_between_two_points(self):
        spot = np.zeros((5, 9))
        spot[2, 5] = 1.0
        spot[2, 7] = 3.0
        x_px, y_px = centroid_xy_px(spot)
        assert x_px == pytest.approx(6.5)
        assert y_px == pytest.approx(2.0)

    def test_centroid_rejects_flat_negative_and_non_2d_input(self):
        with pytest.raises(PhysicalEstimatorError, match="positive total flux"):
            centroid_xy_px(np.zeros((4, 4)))
        with pytest.raises(PhysicalEstimatorError, match="non-negative"):
            centroid_xy_px(np.array([[1.0, -1.0], [1.0, 1.0]]))
        with pytest.raises(PhysicalEstimatorError, match="2-D"):
            centroid_xy_px(np.ones(5))
        with pytest.raises(PhysicalEstimatorError, match="finite"):
            centroid_xy_px(np.array([[1.0, np.nan], [1.0, 1.0]]))

    def test_encircled_energy_radius_of_a_point_mass_is_zero(self):
        spot = np.zeros((9, 9))
        spot[4, 4] = 2.0
        assert encircled_energy_radius_rad(spot, (1.0e-6, 1.0e-6)) == 0.0

    def test_encircled_energy_radius_grows_with_spot_width_and_scale(self):
        rows, columns = np.mgrid[0:33, 0:33]
        radius_sq = (rows - 16.0) ** 2 + (columns - 16.0) ** 2

        def gaussian(sigma_px: float) -> np.ndarray:
            return np.exp(-radius_sq / (2.0 * sigma_px**2))

        narrow = encircled_energy_radius_rad(gaussian(2.0), (1.0e-6, 1.0e-6))
        wide = encircled_energy_radius_rad(gaussian(4.0), (1.0e-6, 1.0e-6))
        rescaled = encircled_energy_radius_rad(gaussian(2.0), (2.0e-6, 2.0e-6))
        assert wide > narrow > 0.0
        assert rescaled == pytest.approx(2.0 * narrow)

    def test_encircled_energy_radius_rejects_bad_fraction_and_scale(self):
        spot = np.ones((4, 4))
        for fraction in (0.0, 1.0, True):
            with pytest.raises(PhysicalEstimatorError, match="fraction"):
                encircled_energy_radius_rad(
                    spot,
                    (1.0e-6, 1.0e-6),
                    fraction=fraction,
                )
        with pytest.raises(PhysicalEstimatorError, match="pixel_scale"):
            encircled_energy_radius_rad(spot, (0.0, 1.0e-6))

    def test_mean_square_column_difference_matches_a_linear_ramp(self):
        values = 0.5 * np.tile(np.arange(10.0), (4, 1))
        assert mean_square_column_difference(values, 3) == pytest.approx(2.25)

    def test_mean_square_column_difference_ignores_nan_samples(self):
        values = 0.5 * np.tile(np.arange(10.0), (4, 1))
        values[:, 4] = np.nan
        assert mean_square_column_difference(values, 3) == pytest.approx(2.25)

    @pytest.mark.parametrize("infinite", (np.inf, -np.inf))
    def test_mean_square_column_difference_rejects_infinite_samples(
        self, infinite
    ):
        values = 0.5 * np.tile(np.arange(10.0), (4, 1))
        values[0, 4] = infinite
        with pytest.raises(PhysicalEstimatorError, match="infinite samples"):
            mean_square_column_difference(values, 3)

    def test_mean_square_column_difference_rejects_bad_lags(self):
        values = np.zeros((3, 6))
        for lag in (0, 6, True):
            with pytest.raises(PhysicalEstimatorError, match="lag_px"):
                mean_square_column_difference(values, lag)
        with pytest.raises(PhysicalEstimatorError, match="2-D"):
            mean_square_column_difference(np.zeros(6), 2)
        with pytest.raises(PhysicalEstimatorError, match="finite sample pair"):
            mean_square_column_difference(np.full((3, 6), np.nan), 2)

    def test_normalized_singular_spectrum_divides_by_the_leading_value(self):
        spectrum = normalized_singular_spectrum(np.diag([3.0, 2.0, 1.0]))
        assert spectrum == pytest.approx([1.0, 2.0 / 3.0, 1.0 / 3.0])
        assert np.all(np.diff(spectrum) <= 0.0)

    def test_normalized_singular_spectrum_rejects_degenerate_input(self):
        with pytest.raises(PhysicalEstimatorError, match="positive largest"):
            normalized_singular_spectrum(np.zeros((3, 3)))
        with pytest.raises(PhysicalEstimatorError, match="finite"):
            normalized_singular_spectrum(np.array([[1.0, np.inf]]))
        with pytest.raises(PhysicalEstimatorError, match="non-empty"):
            normalized_singular_spectrum(np.zeros((0, 3)))


class TestDocumentContract:
    def test_minimal_report_and_baseline_round_trip(self):
        report = _minimal_report()
        assert validate_cross_backend_report(report) is report
        baseline = _minimal_baseline()
        assert (
            baseline["artifact_schema_name"] == CROSS_BACKEND_BASELINE_SCHEMA_NAME
        )
        validate_cross_backend_baseline(baseline)

    def test_baseline_from_report_never_mutates_its_input(self):
        report = _minimal_report()
        snapshot = json.loads(json.dumps(report))
        _minimal_baseline()
        assert report == snapshot

    @pytest.mark.parametrize(
        "field",
        (
            "artifact_schema_name",
            "comparison_config",
            "conventions",
            "component_hashes",
            "fixture_hashes",
            "numerical_inputs",
            "environment",
            "comparisons",
        ),
    )
    def test_report_requires_every_top_level_field(self, field):
        report = _minimal_report()
        del report[field]
        with pytest.raises(BaselineContractError, match="missing required"):
            validate_cross_backend_report(report)

    def test_report_rejects_unknown_schema_identity(self):
        report = _minimal_report()
        report["artifact_schema_name"] = "shwfs_ao.other_artifact"
        with pytest.raises(BaselineContractError, match="artifact_schema_name"):
            validate_cross_backend_report(report)
        for version in (999, "1", 1.0, True):
            # ``True`` is the interesting one: it equals 1, so a plain equality
            # check reads a boolean field as "version 1" and validates the
            # document against a contract it never declared.
            report = _minimal_report()
            report["artifact_schema_version"] = version
            with pytest.raises(
                BaselineContractError,
                match="artifact_schema_version",
            ):
                validate_cross_backend_report(report)

    def test_a_version_1_document_is_refused_by_its_version(self):
        # Version 1 predates numerical_inputs.  Checking required fields before
        # the version reported such a document as merely incomplete, which
        # invites adding the field rather than regenerating and reviewing.
        report = _minimal_report()
        del report["numerical_inputs"]
        report["artifact_schema_version"] = 1
        with pytest.raises(
            BaselineContractError,
            match="artifact_schema_version 1 is no longer accepted",
        ) as excinfo:
            validate_cross_backend_report(report)
        assert "missing required fields" not in str(excinfo.value)
        assert "Regenerate a version-2 candidate" in str(excinfo.value)

    def test_the_schema_gate_also_names_a_version_1_document_by_its_version(
        self, packaged_baseline,
    ):
        # Errors at the root sort before every field path, so without the
        # identity coming first the schema gate reported the missing field.
        document = _report_copy(packaged_baseline)
        del document["numerical_inputs"]
        document["artifact_schema_version"] = 1
        with pytest.raises(
            BaselineContractError,
            match="at artifact_schema_version: 2 was expected",
        ):
            validate_baseline_against_schema(document)

    def test_report_rejects_a_config_without_hash_and_short_hashes(self):
        report = _minimal_report()
        report["comparison_config"] = {"root_seed": 7}
        with pytest.raises(BaselineContractError, match="config_hash"):
            validate_cross_backend_report(report)
        report = _minimal_report()
        report["fixture_hashes"]["static_opd_m"] = "abc123"
        with pytest.raises(BaselineContractError, match="64-character"):
            validate_cross_backend_report(report)

    def test_report_rejects_duplicate_comparisons_and_metric_names(self):
        report = _minimal_report()
        report["comparisons"].append(
            json.loads(json.dumps(report["comparisons"][0]))
        )
        with pytest.raises(BaselineContractError, match="duplicate comparison"):
            validate_cross_backend_report(report)
        report = _minimal_report()
        report["comparisons"][0]["metrics"].append(
            json.loads(json.dumps(report["comparisons"][0]["metrics"][0]))
        )
        with pytest.raises(BaselineContractError, match="duplicate metric"):
            validate_cross_backend_report(report)

    def test_the_required_kind_inventory_matches_the_ticket(self):
        assert REQUIRED_COMPARISON_KINDS == TICKET_COMPARISON_KINDS

    def test_report_rejects_a_missing_required_comparison_kind(self):
        report = _minimal_report()
        del report["comparisons"][2]
        with pytest.raises(
            BaselineContractError,
            match="required comparison kinds",
        ) as excinfo:
            validate_cross_backend_report(report)
        assert "atmosphere_statistics" in str(excinfo.value)

    def test_report_rejects_an_unknown_extra_comparison_kind(self):
        report = _minimal_report()
        report["comparisons"][0]["comparison_kind"] = "unit_probe"
        with pytest.raises(
            BaselineContractError,
            match="required comparison kinds",
        ) as excinfo:
            validate_cross_backend_report(report)
        assert "unit_probe" in str(excinfo.value)

    def test_report_rejects_a_reordered_comparison_inventory(self):
        report = _minimal_report()
        comparisons = report["comparisons"]
        comparisons[0], comparisons[1] = comparisons[1], comparisons[0]
        with pytest.raises(
            BaselineContractError,
            match="canonical order",
        ):
            validate_cross_backend_report(report)

    def test_report_rejects_a_missing_or_extra_required_hash_key(self):
        report = _minimal_report()
        del report["fixture_hashes"]["atmosphere_opd_cube_m"]
        with pytest.raises(BaselineContractError, match="exactly the required"):
            validate_cross_backend_report(report)
        report = _minimal_report()
        report["component_hashes"]["unreviewed_extra"] = _hash64("extra")
        with pytest.raises(BaselineContractError, match="exactly the required"):
            validate_cross_backend_report(report)

    def test_report_rejects_a_dropped_or_added_required_metric(self):
        report = _minimal_report()
        _remove_metric(
            report,
            "closed_loop_residual",
            "both_loops_consumed_shared_opd_cube",
        )
        with pytest.raises(
            BaselineContractError,
            match="exactly its required metrics",
        ) as excinfo:
            validate_cross_backend_report(report)
        assert "both_loops_consumed_shared_opd_cube" in str(excinfo.value)

    def test_report_requires_exact_metrics_to_gate_on_equality(self):
        report = _minimal_report()
        metric = report["comparisons"][0]["metrics"][0]
        metric["level"] = "exact"
        # An exact metric may not gate on a wideable range.
        metric["pass_criterion"] = {"type": "range", "low": 0.0, "high": 1.0e9}
        with pytest.raises(BaselineContractError, match="must be 'equals'"):
            validate_cross_backend_report(report)

    def test_baseline_requires_equal_value_for_an_equals_criterion(self):
        # mask_round_trip_identical is a pinned exact/equals(True) identity gate;
        # recording a value that disagrees with the expectation must be rejected
        # (the recorded value is the expectation the gate fires on).
        baseline = _minimal_baseline()
        _set_metric_value(
            baseline,
            "pupil_mask_and_throughput",
            "mask_round_trip_identical",
            False,
        )
        with pytest.raises(
            BaselineContractError,
            match="must equal the criterion expectation",
        ):
            validate_cross_backend_baseline(baseline)

    def test_baseline_never_lets_a_boolean_satisfy_a_numeric_expectation(self):
        # bool is a subclass of int in Python, so False == 0 and 1 == True.  A
        # baseline that records a count as a flag (or a flag as a count) would
        # otherwise validate and then gate on a value of a different kind.
        baseline = _minimal_baseline()
        _set_metric_value(
            baseline,
            "interaction_matrix_identity",
            "rank_difference",
            False,  # the criterion expects the integer 0
        )
        with pytest.raises(
            BaselineContractError,
            match="must equal the criterion expectation",
        ):
            validate_cross_backend_baseline(baseline)

        baseline = _minimal_baseline()
        _set_metric_value(
            baseline,
            "pupil_mask_and_throughput",
            "mask_round_trip_identical",
            1,  # the criterion expects the boolean True
        )
        with pytest.raises(
            BaselineContractError,
            match="must equal the criterion expectation",
        ):
            validate_cross_backend_baseline(baseline)

    def test_a_comparison_estimated_from_realizations_must_define_its_statistics(
        self,
    ):
        # The packaged JSON Schema requires this record; so must the application
        # validator, because acceptance is the only writer of a baseline and a
        # ratio without its estimator and uncertainty is uninterpretable.  Prose
        # is refused outright: any non-empty string satisfied the old contract,
        # so "x" documented nothing at all.
        assert COMPARISONS_REQUIRING_STATISTICAL_DEFINITION == frozenset(
            {"atmosphere_statistics"}
        )
        prose = "4 realizations; estimator: RMS; uncertainty: standard error."
        for absent in (None, "", "   ", "x", prose):
            baseline = _minimal_baseline()
            for comparison in baseline["comparisons"]:
                if comparison["comparison_kind"] != "atmosphere_statistics":
                    continue
                if absent is None:
                    del comparison["statistical_definition"]
                else:
                    comparison["statistical_definition"] = absent
            with pytest.raises(
                BaselineContractError,
                match="statistical_definition",
            ):
                validate_cross_backend_baseline(baseline)

    def test_a_statistical_definition_must_carry_all_four_elements(self):
        """Each element is required in its own right and in its own type.

        The four are not interchangeable: a sample count without an estimator
        does not say what was averaged, and an estimator without a sample count
        does not say over how much.  Dropping any one, or degrading its type,
        must be refused individually rather than covered by the presence of the
        others.
        """

        degradations = (
            {"sample_count": 1},
            {"sample_count": True},
            {"sample_count": "4"},
            {"estimator": ""},
            {"uncertainty_method": "   "},
            {"narrative": ""},
            {"bins_or_lags": {"kind": "lags", "values": []}},
            {"bins_or_lags": {"kind": "", "values": [4]}},
            {"bins_or_lags": {"values": [4]}},
            {"bins_or_lags": [4, 2]},
        )
        for override in degradations:
            baseline = _minimal_baseline()
            for comparison in baseline["comparisons"]:
                if comparison["comparison_kind"] != "atmosphere_statistics":
                    continue
                comparison["statistical_definition"].update(override)
            with pytest.raises(
                BaselineContractError, match="statistical_definition"
            ):
                validate_cross_backend_baseline(baseline)

        for dropped in _probe_statistical_definition():
            baseline = _minimal_baseline()
            for comparison in baseline["comparisons"]:
                if comparison["comparison_kind"] != "atmosphere_statistics":
                    continue
                del comparison["statistical_definition"][dropped]
            with pytest.raises(
                BaselineContractError, match="statistical_definition"
            ):
                validate_cross_backend_baseline(baseline)

    def test_both_gates_refuse_whitespace_where_prose_is_required(self):
        """The schema must refuse exactly what the application validator does.

        Acceptance runs both, and the schema is documented as mirroring the
        application rules.  ``minLength: 1`` alone does not: it admits "   ",
        which every application check rejects by reading the value through
        ``str.strip()``.  That divergence made the packaged schema the weaker
        of the two gates while claiming to be the same one, so an all-
        whitespace estimator, rationale or acceptance reason — documenting
        nothing — passed it.
        """

        def refused_by_both(document, label):
            with pytest.raises(BaselineContractError):
                validate_cross_backend_baseline(document)
            with pytest.raises(BaselineContractError):
                validate_baseline_against_schema(document)

        for field in ("estimator", "uncertainty_method", "narrative"):
            baseline = _minimal_baseline()
            for comparison in baseline["comparisons"]:
                if comparison["comparison_kind"] != "atmosphere_statistics":
                    continue
                comparison["statistical_definition"][field] = "   "
            refused_by_both(baseline, field)

        baseline = _minimal_baseline()
        for comparison in baseline["comparisons"]:
            if comparison["comparison_kind"] != "atmosphere_statistics":
                continue
            comparison["statistical_definition"]["bins_or_lags"]["kind"] = "  "
        refused_by_both(baseline, "bins_or_lags.kind")

        # The same shared definition guards the acceptance evidence, which is
        # the other place an all-whitespace string would document nothing.
        for field in ("reason", "review_reference"):
            baseline = _minimal_baseline()
            baseline["acceptance"][field] = "   "
            with pytest.raises(BaselineContractError):
                validate_baseline_against_schema(baseline)

    def test_both_gates_refuse_the_same_malformed_numerical_witnesses(
        self, packaged_baseline,
    ):
        """The schema's witness definitions are as strict as the runtime's.

        Each case changes one field of the packaged baseline, which passes both
        gates, so the schema must refuse at that field and nowhere else.  The
        hash and ``data`` cases end in a newline because jsonschema matches
        patterns with ``re.search``, whose ``$`` also matches before a final
        newline: the pattern alone admitted them.
        """

        validate_cross_backend_baseline(packaged_baseline)
        validate_baseline_against_schema(packaged_baseline)
        data = packaged_baseline["numerical_inputs"]["static_opd_m"]["data"]
        digest = packaged_baseline["numerical_inputs"]["tilt_x_opd_m"]["source_hash"]
        cases = (
            # Direct array fixtures have no hash preimage to carry.
            ("static_opd_m", "source_payload", "unverified text"),
            ("time_grid_s", "backend_source_payload", ""),
            # The DM raw hashes are hashes of these preimages.
            ("native_dm", "source_payload", None),
            ("hcipy_dm", "backend_source_payload", None),
            ("hcipy_dm", "source_payload", ""),
            # Padded standard base64 only.
            ("static_opd_m", "data", data + "\n"),
            ("static_opd_m", "data", "*" + data[1:]),
            ("static_opd_m", "data", data[:-1]),
            # Exactly 64 lowercase hexadecimal characters.
            ("static_opd_m", "values_sha256", digest + "\n"),
            ("tilt_x_opd_m", "source_hash", digest + "\n"),
            ("native_dm", "configuration_hash", digest + "\n"),
        )
        for name, field, value in cases:
            document = _report_copy(packaged_baseline)
            document["numerical_inputs"][name][field] = value
            with pytest.raises(BaselineContractError, match=name):
                validate_cross_backend_baseline(document)
            with pytest.raises(
                BaselineContractError,
                match=f"at numerical_inputs/{name}/{field}:",
            ):
                validate_baseline_against_schema(document)

        # JSON Schema counts 48.0 as an integer, so only the runtime can
        # refuse an integer-valued float shape entry (docs/artifact_schemas.md).
        document = _report_copy(packaged_baseline)
        document["numerical_inputs"]["static_opd_m"]["shape"] = [48.0, 48]
        with pytest.raises(BaselineContractError, match="shape must be bounded positive"):
            validate_cross_backend_baseline(document)
        validate_baseline_against_schema(document)

    def test_a_measured_magnitude_cannot_be_recorded_as_negative(self):
        """Standard errors, runtimes and peak memory are magnitudes.

        Every one of them is informational, so no gate ever reads its value:
        without a domain rule a standard error of -1.0 sits under the ratios it
        is supposed to qualify and nothing in the document objects, while a
        reader takes the uncertainty at face value.
        """

        for kind, name in (
            ("atmosphere_statistics", "rms_ratio_standard_error"),
            ("runtime_and_memory", "native_wfs_propagation_s"),
            ("runtime_and_memory", "comparison_peak_traced_memory_mb"),
        ):
            for value in (-1.0, -1e-12):
                baseline = _minimal_baseline()
                _set_metric_value(baseline, kind, name, value)
                with pytest.raises(
                    BaselineContractError,
                    match="finite non-negative number",
                ):
                    validate_cross_backend_baseline(baseline)
            # Zero is a legitimate measurement and must stay accepted.
            baseline = _minimal_baseline()
            _set_metric_value(baseline, kind, name, 0.0)
            validate_cross_backend_baseline(baseline)

    def test_metric_contract_forbids_gating_an_identity_on_the_wrong_value(self):
        # both_loops_consumed_shared_opd_cube is a pinned exact/equals(True)
        # gate; recording it as equals(False) — even self-consistently — must be
        # rejected so a run that never consumed the shared cube cannot pass.
        baseline = _minimal_baseline()
        for comparison in baseline["comparisons"]:
            if comparison["comparison_kind"] != "closed_loop_residual":
                continue
            for metric in comparison["metrics"]:
                if metric["name"] == "both_loops_consumed_shared_opd_cube":
                    metric["value"] = False
                    metric["pass_criterion"] = {"type": "equals", "expected": False}
        with pytest.raises(
            BaselineContractError,
            match="canonical expectation",
        ):
            validate_cross_backend_baseline(baseline)

    def test_metric_contract_forbids_demoting_an_exact_gate_to_a_range(self):
        # rank_difference is a pinned exact/equals(0) gate; it cannot be recorded
        # as a wide range that a later edit could widen into an always-pass.
        baseline = _minimal_baseline()
        for comparison in baseline["comparisons"]:
            if comparison["comparison_kind"] != "interaction_matrix_identity":
                continue
            for metric in comparison["metrics"]:
                if metric["name"] == "rank_difference":
                    metric["level"] = "physical_tolerance"
                    metric["value"] = 0
                    metric["pass_criterion"] = {
                        "type": "range",
                        "low": -1000,
                        "high": 1000,
                    }
        with pytest.raises(BaselineContractError, match="pinned"):
            validate_cross_backend_baseline(baseline)

    def test_metric_contract_forbids_promoting_a_runtime_metric_to_a_gate(self):
        # runtime_and_memory metrics are pinned informational; they cannot be
        # promoted into a scientific correctness gate.
        baseline = _minimal_baseline()
        for comparison in baseline["comparisons"]:
            if comparison["comparison_kind"] != "runtime_and_memory":
                continue
            metric = comparison["metrics"][0]
            metric["level"] = "physical_tolerance"
            metric["pass_criterion"] = {"type": "range", "low": 0.0, "high": 1.0}
        with pytest.raises(BaselineContractError, match="pinned"):
            validate_cross_backend_baseline(baseline)

    def test_baseline_rejects_forged_or_unknown_source_commit(self):
        for forged in ("unknown", "abc123", "F" * 40):
            baseline = _minimal_baseline()
            baseline["generator"]["source_commit"] = forged
            with pytest.raises(
                BaselineContractError,
                match="40-character lowercase git",
            ):
                validate_cross_backend_baseline(baseline)

    def test_baseline_requires_a_recorded_clean_state_flag(self):
        baseline = _minimal_baseline()
        del baseline["generator"]["source_tree_clean"]
        with pytest.raises(
            BaselineContractError,
            match="source_tree_clean must be recorded",
        ):
            validate_cross_backend_baseline(baseline)

    def test_baseline_requires_patch_evidence_when_the_tree_is_dirty(self):
        # A dirty tree cannot masquerade as reproducible: it must carry the
        # source_patch_sha256 hash of exactly what diverged from the commit.
        baseline = _minimal_baseline()
        baseline["generator"]["source_tree_clean"] = False
        with pytest.raises(
            BaselineContractError,
            match="source_patch_sha256 must be the 64-character",
        ):
            validate_cross_backend_baseline(baseline)
        for forged in ("", "not-a-hash", "abc123", "F" * 64):
            baseline["generator"]["source_patch_sha256"] = forged
            with pytest.raises(
                BaselineContractError,
                match="source_patch_sha256 must be the 64-character",
            ):
                validate_cross_backend_baseline(baseline)
        # Valid 64-hex patch evidence is accepted for a dirty tree.
        baseline["generator"]["source_patch_sha256"] = _hash64("patch-evidence")
        validate_cross_backend_baseline(baseline)

    def test_baseline_rejects_any_patch_evidence_when_the_tree_is_clean(self):
        # A clean tree has no divergence from the recorded commit, so patch
        # evidence of one contradicts it — and a well-formed hash is the
        # dangerous case, because it is the one that looks like real evidence.
        for contradiction in ("not-a-hash", _hash64("well-formed"), ""):
            baseline = _minimal_baseline()
            assert baseline["generator"]["source_tree_clean"] is True
            baseline["generator"]["source_patch_sha256"] = contradiction
            with pytest.raises(
                BaselineContractError,
                match="must be null or absent when source_tree_clean is true",
            ):
                validate_cross_backend_baseline(baseline)

        # Null and absent both mean "nothing diverged", and both are accepted.
        baseline = _minimal_baseline()
        baseline["generator"]["source_patch_sha256"] = None
        validate_cross_backend_baseline(baseline)
        del baseline["generator"]["source_patch_sha256"]
        validate_cross_backend_baseline(baseline)

    @pytest.mark.parametrize(
        "criterion, message",
        (
            (
                {"type": "abs_tolerance", "expected": 0.0, "tolerance": -1e-9},
                "non-negative",
            ),
            (
                {
                    "type": "abs_tolerance",
                    "expected": 0.0,
                    "tolerance": float("nan"),
                },
                "non-negative",
            ),
            (
                {
                    "type": "abs_tolerance",
                    "expected": float("inf"),
                    "tolerance": 1e-9,
                },
                "finite number",
            ),
            (
                {"type": "abs_tolerance", "expected": 0.0, "tolerance": True},
                "non-negative",
            ),
            (
                {"type": "range", "low": 2.0, "high": 1.0},
                "must not exceed",
            ),
            (
                {"type": "range", "low": float("-inf"), "high": 1.0},
                "finite",
            ),
            (
                {"type": "range", "low": 0.0, "high": float("nan")},
                "finite",
            ),
            (
                {"type": "equals", "expected": float("nan")},
                "finite",
            ),
        ),
    )
    def test_report_rejects_degenerate_criterion_numerics(
        self,
        criterion,
        message,
    ):
        report = _minimal_report()
        report["comparisons"][0]["metrics"][0]["pass_criterion"] = criterion
        with pytest.raises(BaselineContractError, match=message):
            validate_cross_backend_report(report)

    def test_report_accepts_boolean_and_string_equality_expectations(self):
        # The pinned contract includes boolean identity gates (e.g.
        # mask_round_trip_identical == True) and string identity gates (e.g.
        # native_backend_name == "native"); a conforming report validates and
        # preserves both expectation types.
        report = _minimal_report()
        validate_cross_backend_report(report)
        equals_expectations = {
            metric["name"]: metric["pass_criterion"]["expected"]
            for comparison in report["comparisons"]
            for metric in comparison["metrics"]
            if metric["pass_criterion"]["type"] == "equals"
        }
        assert equals_expectations["mask_round_trip_identical"] is True
        assert equals_expectations["native_backend_name"] == "native"

    def test_a_baseline_rejects_a_non_finite_recorded_gating_value(self):
        # A fresh report may observe NaN — evaluation reports that as a
        # metric failure with full context — but an accepted baseline's
        # recorded value is an expectation and must be finite.
        report = _minimal_report()
        report["comparisons"][0]["metrics"][0]["value"] = float("nan")
        validate_cross_backend_report(report)
        baseline = _minimal_baseline()
        baseline["comparisons"][0]["metrics"][0]["value"] = float("nan")
        with pytest.raises(BaselineContractError, match="finite"):
            validate_cross_backend_baseline(baseline)

    def test_report_rejects_a_non_hex_content_hash(self):
        report = _minimal_report()
        report["component_hashes"]["pupil_geometry"] = "Z" * 64
        with pytest.raises(BaselineContractError, match="hexadecimal"):
            validate_cross_backend_report(report)

    def test_report_rejects_unknown_levels_and_incomplete_criteria(self):
        report = _minimal_report()
        report["comparisons"][0]["metrics"][0]["level"] = "loose"
        with pytest.raises(BaselineContractError, match="unknown level"):
            validate_cross_backend_report(report)
        for broken in (
            {"type": "abs_tolerance", "expected": 0.0},
            {"type": "range", "low": 0.0},
            {"type": "equals"},
            {"type": "close_enough"},
        ):
            report = _minimal_report()
            report["comparisons"][0]["metrics"][0]["pass_criterion"] = broken
            with pytest.raises(BaselineContractError):
                validate_cross_backend_report(report)

    def test_report_ties_the_informational_level_to_its_criterion(self):
        report = _minimal_report()
        report["comparisons"][0]["metrics"][0]["pass_criterion"] = {
            "type": "informational",
        }
        with pytest.raises(BaselineContractError, match="informational"):
            validate_cross_backend_report(report)
        report = _minimal_report()
        report["comparisons"][0]["metrics"][0]["level"] = "informational"
        with pytest.raises(BaselineContractError, match="informational"):
            validate_cross_backend_report(report)

    def test_baseline_rejects_missing_generator_or_acceptance(self):
        baseline = _minimal_baseline()
        del baseline["generator"]
        with pytest.raises(BaselineContractError, match="generator"):
            validate_cross_backend_baseline(baseline)
        baseline = _minimal_baseline()
        del baseline["acceptance"]
        with pytest.raises(BaselineContractError, match="acceptance"):
            validate_cross_backend_baseline(baseline)

    @pytest.mark.parametrize(
        "block, field",
        (
            ("generator", "generator_name"),
            ("generator", "generator_version"),
            ("generator", "source_commit"),
            ("acceptance", "reason"),
            ("acceptance", "review_reference"),
            ("acceptance", "accepted_at_utc"),
        ),
    )
    def test_baseline_rejects_empty_provenance_fields(self, block, field):
        baseline = _minimal_baseline()
        baseline[block][field] = "  "
        with pytest.raises(BaselineContractError, match="non-empty"):
            validate_cross_backend_baseline(baseline)

    def test_baseline_rejects_a_metric_without_scientific_rationale(self):
        baseline = _minimal_baseline()
        baseline["comparisons"][0]["metrics"][0]["rationale"] = "   "
        with pytest.raises(BaselineContractError, match="rationale"):
            validate_cross_backend_baseline(baseline)

    def test_baseline_rejects_the_plain_report_schema_name(self):
        baseline = _minimal_baseline()
        baseline["artifact_schema_name"] = CROSS_BACKEND_REPORT_SCHEMA_NAME
        with pytest.raises(BaselineContractError, match="baseline"):
            validate_cross_backend_baseline(baseline)


class TestPackagedBaseline:
    def test_packaged_baseline_validates_and_covers_the_ticket_comparisons(
        self,
        packaged_baseline,
    ):
        kinds = tuple(
            comparison["comparison_kind"]
            for comparison in packaged_baseline["comparisons"]
        )
        assert kinds == TICKET_COMPARISON_KINDS

    def test_packaged_baseline_matches_the_default_configuration(
        self,
        packaged_baseline,
    ):
        config = CrossBackendConfig()
        assert (
            packaged_baseline["comparison_config"]["config_hash"]
            == config.config_hash
        )
        assert packaged_baseline["root_seed"] == config.root_seed

    def test_packaged_baseline_records_shared_inputs_and_identities(
        self,
        packaged_baseline,
    ):
        assert set(packaged_baseline["fixture_hashes"]) == (
            SHARED_FIXTURE_HASH_KEYS
        )
        assert set(packaged_baseline["component_hashes"]) == (
            COMPONENT_HASH_KEYS
        )
        conventions = packaged_baseline["conventions"]
        assert conventions["command_unit"] == "m_opd_equivalent"
        assert "residual_opd_m" in conventions["residual_sign_convention"]
        assert conventions["measurement_unit"] == "pixel"

    def test_packaged_baseline_records_environment_and_provenance(
        self,
        packaged_baseline,
    ):
        environment = packaged_baseline["environment"]
        for field in (
            "python_version",
            "numpy_version",
            "shwfs_ao_version",
            "hcipy_version",
            "dependency_constraint_file",
            "dependency_constraint_sha256",
        ):
            assert environment[field].strip()
        generator = packaged_baseline["generator"]
        assert generator["generator_name"] == (
            "scripts/generate_cross_backend_candidate.py"
        )
        assert packaged_baseline["acceptance"]["review_reference"].strip()

    def test_packaged_statistical_comparison_documents_its_estimator(
        self,
        packaged_baseline,
    ):
        atmosphere = next(
            comparison
            for comparison in packaged_baseline["comparisons"]
            if comparison["comparison_kind"] == "atmosphere_statistics"
        )
        definition = atmosphere["statistical_definition"]
        # The four elements are read as fields, not searched for as words: the
        # packaged artifact must be interpretable by a consumer that never
        # parses English.
        assert definition["sample_count"] >= 2
        assert definition["estimator"].strip()
        assert definition["uncertainty_method"].strip()
        assert definition["bins_or_lags"]["kind"].strip()
        assert definition["bins_or_lags"]["values"]
        # The sample count must be the realization count the suite actually
        # ran, not a number written beside it.
        assert definition["sample_count"] == (
            packaged_baseline["comparison_config"]["atmosphere_realizations"]
        )
        # The reviewed paragraph survives beside the structured fields; it is
        # what a human reads, and it is not a substitute for them.
        assert "realizations" in definition["narrative"]

    def test_packaged_range_criteria_exceed_the_recorded_dispersion(
        self,
        packaged_baseline,
    ):
        # The statistical claim is checkable from the artifact alone: each
        # recorded gating value sits more than three recorded standard
        # errors inside its range criterion.
        atmosphere = next(
            comparison
            for comparison in packaged_baseline["comparisons"]
            if comparison["comparison_kind"] == "atmosphere_statistics"
        )
        metrics = {
            metric["name"]: metric for metric in atmosphere["metrics"]
        }
        # The artifact must state the three-standard-error margin it is about
        # to be held to, so the check below verifies a documented claim rather
        # than one this test invented.
        definition = atmosphere["statistical_definition"]
        assert "standard error" in definition["uncertainty_method"]
        assert "three" in definition["uncertainty_method"]
        assert "three standard errors" in definition["narrative"]
        pairs = (
            ("rms_ratio_hcipy_over_native", "rms_ratio_standard_error"),
            (
                "native_structure_function_lag_ratio",
                "native_structure_function_ratio_standard_error",
            ),
            (
                "hcipy_structure_function_lag_ratio",
                "hcipy_structure_function_ratio_standard_error",
            ),
        )
        for gating_name, error_name in pairs:
            gating = metrics[gating_name]
            standard_error = metrics[error_name]
            assert standard_error["level"] == "informational"
            assert standard_error["value"] >= 0.0
            criterion = gating["pass_criterion"]
            margin = min(
                gating["value"] - criterion["low"],
                criterion["high"] - gating["value"],
            )
            assert margin > 3.0 * standard_error["value"], gating_name

    def test_packaged_baseline_consumes_every_recorded_fixture(
        self,
        packaged_baseline,
    ):
        by_kind = {
            comparison["comparison_kind"]: {
                metric["name"]: metric for metric in comparison["metrics"]
            }
            for comparison in packaged_baseline["comparisons"]
        }
        influence = by_kind["dm_single_actuator_influence"]
        assert "max_in_pupil_command_surface_abs_diff_m" in influence
        loop = by_kind["closed_loop_residual"]
        assert (
            loop["executed_time_grid_matches_shared_fixture"]["value"] is True
        )

    def test_packaged_generator_records_verifiable_provenance(
        self,
        packaged_baseline,
    ):
        generator = packaged_baseline["generator"]
        # Pinned, not read from the script: a baseline accepted under an earlier
        # generator must fail this rather than silently re-describe itself as
        # the current one.  Version 3 was the first to verify every executed
        # submodule's origin and to refuse assume-unchanged/skip-worktree trees;
        # version 4 is the first to run from a controlled bytecode cache, to
        # sample provenance ahead of every repository import, and to bracket
        # each sample so its two git reads describe one state; version 5 is the
        # first to establish those interpreter conditions by checking them
        # rather than by trusting the marker that claims them, which a v4
        # candidate could have been produced without. Version 6 additionally
        # records complete numerical input witnesses and their hash preimages.
        assert generator["generator_version"] == "6"
        assert generator["source_tree_clean"] is True
        commit = generator["source_commit"]
        assert len(commit) == 40
        assert set(commit) <= set("0123456789abcdef")

    def test_packaged_environment_matches_its_named_constraint_profile(
        self,
        packaged_baseline,
    ):
        # The named profile must be the one that could have produced the
        # recorded interpreter and library versions.  The constraints tree
        # exists only in a source checkout, so the wheel-smoke bundle skips.
        environment = packaged_baseline["environment"]
        profile = environment["dependency_constraint_file"]
        repository_root = Path(__file__).resolve().parents[2]
        profile_path = repository_root / profile
        if not (repository_root / "constraints").is_dir():
            pytest.skip("constraints profiles are not part of this bundle")
        assert profile_path.is_file(), profile
        payload = profile_path.read_bytes()
        assert (
            hashlib.sha256(payload).hexdigest()
            == environment["dependency_constraint_sha256"]
        )
        suffix = profile_path.stem.rsplit("py", 1)[-1]
        major, minor = suffix[0], suffix[1:]
        assert environment["python_version"].startswith(f"{major}.{minor}.")
        pins = {}
        for raw_line in payload.decode("utf-8").splitlines():
            line = raw_line.split("#", 1)[0].split(";", 1)[0].strip()
            if line and "==" in line and not line.startswith("-"):
                name, _, version = line.partition("==")
                pins[name.strip().lower().replace("_", "-")] = version.strip()
        assert pins["numpy"] == environment["numpy_version"]
        assert pins["hcipy"] == environment["hcipy_version"]

    def test_packaged_baseline_evaluates_cleanly_against_itself(
        self,
        packaged_baseline,
    ):
        assert (
            evaluate_report_against_baseline(
                packaged_baseline,
                packaged_baseline,
            )
            == ()
        )

    def test_packaged_baseline_validates_against_the_json_schema(
        self,
        packaged_baseline,
    ):
        # The independent structural gate the acceptance workflow also runs.
        validate_baseline_against_schema(packaged_baseline)

    def test_schema_enumerations_match_the_required_inventory(self):
        # The JSON Schema and the Python inventory are one contract: they must
        # name the same required hash keys and per-kind metrics, so neither can
        # drift from the other without a deliberate, reviewed edit to both.
        schema = json.loads(read_text_resource(CROSS_BACKEND_BASELINE_SCHEMA_RESOURCE))
        properties = schema["properties"]
        assert set(properties["fixture_hashes"]["required"]) == set(
            REQUIRED_FIXTURE_HASH_KEYS
        )
        assert set(properties["component_hashes"]["required"]) == set(
            REQUIRED_COMPONENT_HASH_KEYS
        )
        for item in properties["comparisons"]["prefixItems"]:
            kind = item["properties"]["comparison_kind"]["const"]
            schema_names = {
                clause["contains"]["properties"]["name"]["const"]
                for clause in item["properties"]["metrics"]["allOf"]
            }
            assert schema_names == set(REQUIRED_METRIC_NAMES[kind]), kind

    def test_schema_validation_rejects_a_removed_required_field(self):
        broken = _report_copy(load_cross_backend_baseline())
        del broken["conventions"]
        with pytest.raises(BaselineContractError, match="JSON Schema"):
            validate_baseline_against_schema(broken)

    def test_schema_requires_a_content_hash_for_the_constraint_lock(self):
        # The environment's dependency_constraint_sha256 must be a real content
        # hash, not arbitrary text such as "unrecorded".
        broken = _report_copy(load_cross_backend_baseline())
        broken["environment"]["dependency_constraint_sha256"] = "unrecorded"
        with pytest.raises(BaselineContractError, match="JSON Schema"):
            validate_baseline_against_schema(broken)

    def test_schema_pins_each_metric_meaning(self):
        # Defence in depth: the JSON Schema mirrors METRIC_CONTRACT, so an exact
        # identity gate recorded on the wrong side of the identity is rejected by
        # the schema as well as the application contract.
        broken = _report_copy(load_cross_backend_baseline())
        for comparison in broken["comparisons"]:
            if comparison["comparison_kind"] != "closed_loop_residual":
                continue
            for metric in comparison["metrics"]:
                if metric["name"] == "both_loops_consumed_shared_opd_cube":
                    metric["value"] = False
                    metric["pass_criterion"] = {"type": "equals", "expected": False}
        with pytest.raises(BaselineContractError, match="JSON Schema"):
            validate_baseline_against_schema(broken)


class TestEvaluationSemantics:
    def test_a_range_violation_reports_value_range_units_and_hashes(
        self,
        packaged_baseline,
    ):
        report = _report_copy(packaged_baseline)
        _set_metric_value(
            report,
            "atmosphere_statistics",
            "rms_ratio_hcipy_over_native",
            5.0,
        )
        (failure,) = evaluate_report_against_baseline(
            report,
            packaged_baseline,
        )
        assert "comparison=atmosphere_statistics" in failure
        assert "metric=rms_ratio_hcipy_over_native" in failure
        assert "observed=5.0" in failure
        assert "expected-range=[0.55, 1.8] ratio" in failure
        assert "level=physical_tolerance" in failure
        assert "config_hash=" in failure
        assert "fixtures[" in failure

    def test_an_abs_tolerance_violation_reports_the_tolerance_with_units(
        self,
        packaged_baseline,
    ):
        report = _report_copy(packaged_baseline)
        _set_metric_value(
            report,
            "psf_normalization",
            "native_total_flux_error",
            0.5,
        )
        (failure,) = evaluate_report_against_baseline(
            report,
            packaged_baseline,
        )
        assert "observed=0.5" in failure
        assert "expected=0.0" in failure
        assert "tolerance=±1e-09 flux" in failure

    def test_an_exact_violation_reports_exact_tolerance(
        self,
        packaged_baseline,
    ):
        report = _report_copy(packaged_baseline)
        _set_metric_value(
            report,
            "interaction_matrix_identity",
            "rank_difference",
            1,
        )
        (failure,) = evaluate_report_against_baseline(
            report,
            packaged_baseline,
        )
        assert "observed=1" in failure
        assert "expected=0" in failure
        assert "tolerance=exact" in failure

    def test_a_non_finite_observation_fails_instead_of_passing(
        self,
        packaged_baseline,
    ):
        report = _report_copy(packaged_baseline)
        _set_metric_value(
            report,
            "strehl_ratio",
            "strehl_abs_difference",
            float("nan"),
        )
        (failure,) = evaluate_report_against_baseline(
            report,
            packaged_baseline,
        )
        assert "metric=strehl_abs_difference" in failure
        assert "observed=nan" in failure

    def test_a_report_missing_a_required_metric_is_surfaced_with_full_context(
        self,
        packaged_baseline,
    ):
        # A dropped gate is surfaced as a rich per-metric failure carrying the
        # same complete context a value violation would (expected value or
        # range, tolerance, units, level, and hashes), not a terse inventory
        # rejection that hides them (F8).
        report = _report_copy(packaged_baseline)
        _remove_metric(
            report,
            "strehl_ratio",
            "strehl_abs_difference",
        )
        (failure,) = evaluate_report_against_baseline(report, packaged_baseline)
        assert "metric=strehl_abs_difference" in failure
        assert "absent" in failure
        assert "Strehl" in failure
        assert "level=physical_tolerance" in failure

    def test_informational_metrics_never_gate(self, packaged_baseline):
        report = _report_copy(packaged_baseline)
        _set_metric_value(
            report,
            "runtime_and_memory",
            "native_wfs_propagation_s",
            1.0e9,
        )
        assert (
            evaluate_report_against_baseline(report, packaged_baseline) == ()
        )

    def test_informational_metrics_are_required_evidence_even_though_they_never_gate(
        self, packaged_baseline
    ):
        # Their values are free, but their absence is not: the standard errors
        # qualify the atmosphere ratios and the runtime block is the only
        # measurement of cost, so a report that drops them has lost the evidence
        # its gated numbers are read against.
        report = _report_copy(packaged_baseline)
        report["comparisons"] = [
            comparison
            for comparison in report["comparisons"]
            if comparison["comparison_kind"] != "runtime_and_memory"
        ]
        failures = evaluate_report_against_baseline(report, packaged_baseline)
        assert len(failures) == 5
        assert all("runtime_and_memory" in failure for failure in failures)
        assert all("<absent: missing from the fresh report>" in failure for failure in failures)

        report = _report_copy(packaged_baseline)
        for comparison in report["comparisons"]:
            if comparison["comparison_kind"] != "atmosphere_statistics":
                continue
            comparison["metrics"] = [
                metric
                for metric in comparison["metrics"]
                if "standard_error" not in metric["name"]
            ]
        failures = evaluate_report_against_baseline(report, packaged_baseline)
        assert len(failures) == 3
        assert all("standard_error" in failure for failure in failures)

    def test_a_numpy_boolean_is_a_flag_and_not_a_number(self, packaged_baseline):
        """NumPy's bool_ is not a Python bool, so the kind check must not ask.

        ``numpy.bool_`` compares equal to 0 and 1 while failing
        ``isinstance(x, bool)``, which inverts a bool-only guard exactly: the
        flag satisfies the numeric gate and fails the boolean one.  A metric
        producer that computes an identity as ``(a == b).all()`` hands back
        precisely this type.
        """

        numpy = pytest.importorskip("numpy")

        # A flag may not satisfy a gate on a count...
        report = _report_copy(packaged_baseline)
        _set_metric_value(
            report,
            "interaction_matrix_identity",
            "rank_difference",
            numpy.bool_(False),
        )
        failures = evaluate_report_against_baseline(report, packaged_baseline)
        assert len(failures) == 1
        assert "metric=rank_difference" in failures[0]

        # ...and a genuine boolean measurement must still satisfy its own gate,
        # whichever scalar type carried it.
        report = _report_copy(packaged_baseline)
        _set_metric_value(
            report,
            "pupil_mask_and_throughput",
            "mask_round_trip_identical",
            numpy.bool_(True),
        )
        assert evaluate_report_against_baseline(report, packaged_baseline) == ()

        # A NumPy float is a real measurement and stays acceptable.
        report = _report_copy(packaged_baseline)
        observed = next(
            metric["value"]
            for comparison in report["comparisons"]
            if comparison["comparison_kind"] == "strehl_ratio"
            for metric in comparison["metrics"]
            if metric["name"] == "native_strehl"
        )
        _set_metric_value(
            report, "strehl_ratio", "native_strehl", numpy.float64(observed)
        )
        assert evaluate_report_against_baseline(report, packaged_baseline) == ()

    def test_an_object_cannot_assert_its_way_past_an_equality_gate(
        self, packaged_baseline
    ):
        # A value of no recognised scalar kind never compares equal, so a
        # permissive __eq__ cannot answer a gate on the value's behalf.
        class Always:
            def __eq__(self, other):  # noqa: D105
                return True

        report = _report_copy(packaged_baseline)
        _set_metric_value(
            report, "interaction_matrix_identity", "rank_difference", Always()
        )
        assert len(evaluate_report_against_baseline(report, packaged_baseline)) == 1

    def test_a_boolean_observation_never_satisfies_a_numeric_gate(
        self, packaged_baseline
    ):
        # bool is a Python Real, so a boolean observation would otherwise be
        # measured as 1.0 or 0.0.  These cases are chosen because that number
        # SATISFIES the gate: each one evaluated clean before the fix, so the
        # test discriminates.  (A boolean whose numeric value happens to fall
        # outside the gate was already caught and would prove nothing.)
        for kind, name, observed in (
            ("closed_loop_residual", "native_correction_effect", False),
            ("wfs_tip_tilt_response", "hcipy_tilt_gain", True),
        ):
            report = _report_copy(packaged_baseline)
            _set_metric_value(report, kind, name, observed)
            failures = evaluate_report_against_baseline(report, packaged_baseline)
            assert len(failures) == 1, (kind, name, failures)
            assert f"metric={name}" in failures[0]
            assert f"observed={observed}" in failures[0]

        # And the reverse: an equality gate on a count is not met by a flag.
        report = _report_copy(packaged_baseline)
        _set_metric_value(report, "interaction_matrix_identity", "rank_difference", False)
        failures = evaluate_report_against_baseline(report, packaged_baseline)
        assert len(failures) == 1
        assert "observed=False" in failures[0]

    def test_evaluation_flags_convention_and_seed_drift(self, packaged_baseline):
        # A report whose config_hash and metric values coincide with the
        # baseline but whose measurement conventions or root seed differ is not
        # comparable, so evaluation must surface the drift instead of passing.
        report = _report_copy(packaged_baseline)
        report["conventions"]["residual_sign_convention"] = "flipped convention"
        convention_failures = evaluate_report_against_baseline(
            report, packaged_baseline
        )
        assert any(
            "conventions['residual_sign_convention']" in failure
            for failure in convention_failures
        )

        # A seed cannot drift quietly any more.  It is recorded twice — at the
        # top level and inside comparison_config — the two are required to
        # agree, and the configuration record is bound to its own hash, so a
        # reseeded run is a different configuration by construction.  Editing
        # the top-level value alone no longer produces a comparable document at
        # all; it produces one that fails validation before evaluation begins.
        half_edited = _report_copy(packaged_baseline)
        half_edited["root_seed"] = int(packaged_baseline["root_seed"]) + 1
        with pytest.raises(BaselineContractError, match="disagree"):
            evaluate_report_against_baseline(half_edited, packaged_baseline)

        # Reseeded consistently, it is still refused — at the configuration
        # identity, which is the gate that now carries the seed.
        seed_report = _reconfigured_report(packaged_baseline, root_seed=119)
        seed_failures = evaluate_report_against_baseline(
            seed_report, packaged_baseline
        )
        assert any(
            "comparison_config.config_hash mismatch" in failure
            for failure in seed_failures
        )

    def test_a_config_hash_mismatch_short_circuits_metric_checks(
        self,
        packaged_baseline,
    ):
        # A report that genuinely describes another configuration, rather than
        # one whose hash was overwritten: the recorded fields and the hash are
        # bound to each other now, so a bare relabelling is refused as
        # malformed and would never reach evaluation.
        report = _reconfigured_report(packaged_baseline, root_seed=119)
        _set_metric_value(
            report,
            "interaction_matrix_identity",
            "rank_difference",
            1,
        )
        failures = evaluate_report_against_baseline(
            report,
            packaged_baseline,
        )
        assert len(failures) == 1
        assert "comparison_config.config_hash mismatch" in failures[0]
        assert report["comparison_config"]["config_hash"] in failures[0]
        assert (
            packaged_baseline["comparison_config"]["config_hash"]
            in failures[0]
        )

    def test_a_fixture_hash_mismatch_short_circuits_metric_checks(
        self,
        packaged_baseline,
    ):
        report = _report_copy(packaged_baseline)
        report["fixture_hashes"]["static_opd_m"] = _hash64("drifted-input")
        _set_metric_value(
            report,
            "interaction_matrix_identity",
            "rank_difference",
            1,
        )
        failures = evaluate_report_against_baseline(
            report,
            packaged_baseline,
        )
        assert len(failures) == 1
        assert "fixture_hashes['static_opd_m'] mismatch" in failures[0]
        assert "shared inputs drifted" in failures[0]

    def test_evaluation_flags_a_changed_statistical_definition(
        self,
        packaged_baseline,
    ):
        """The estimated comparison's numbers mean what its estimator says.

        Its ranges were reviewed against one estimator and one uncertainty
        model.  A report that averaged a different number of realizations, or
        measured the structure function at different lags, can land inside those
        ranges while not being the quantity they were set for — and every hash in
        the document would still match, because none of them covers the prose.
        """

        report = _report_copy(packaged_baseline)
        for comparison in report["comparisons"]:
            if comparison["comparison_kind"] == "atmosphere_statistics":
                comparison["statistical_definition"] = {
                    **comparison["statistical_definition"],
                    "estimator": "a different estimator entirely",
                }
        failures = evaluate_report_against_baseline(report, packaged_baseline)
        # Reported element by element, so the message names which part of the
        # estimator moved rather than printing two records and leaving the
        # reader to diff them.
        assert any(
            "statistical_definition['estimator'] mismatch" in failure
            and "a different estimator entirely" in failure
            for failure in failures
        )

        # The two elements the configuration determines cannot drift this far:
        # they are bound to comparison_config, so a document that restates them
        # is refused outright rather than compared. Editing both documents the
        # same way — which used to evaluate clean, because nothing related the
        # estimator to the run it described — is refused for the same reason.
        for edited in ("report only", "both documents"):
            drifted = _report_copy(packaged_baseline)
            targets = [drifted]
            if edited == "both documents":
                targets.append(_report_copy(packaged_baseline))
            for document in targets:
                for comparison in document["comparisons"]:
                    if comparison["comparison_kind"] != "atmosphere_statistics":
                        continue
                    comparison["statistical_definition"] = {
                        **comparison["statistical_definition"],
                        "sample_count": 999,
                        "bins_or_lags": {
                            "kind": "invented_lags",
                            "values": [11, 5],
                        },
                    }
            with pytest.raises(
                BaselineContractError, match="the configuration it was produced under"
            ):
                evaluate_report_against_baseline(drifted, targets[-1])

        # Dropping it entirely never becomes a silent pass either: the report is
        # then structurally invalid, which evaluation refuses outright.
        dropped = _report_copy(packaged_baseline)
        for comparison in dropped["comparisons"]:
            comparison.pop("statistical_definition", None)
        with pytest.raises(
            BaselineContractError,
            match="statistical_definition",
        ):
            evaluate_report_against_baseline(dropped, packaged_baseline)

        # A report missing the whole estimated comparison is a different fact,
        # and it must not be flattened into "the definition differs": the
        # per-metric failures below carry the expected ranges and hashes, and
        # this check runs before them, so it must stay silent here.
        absent = _report_copy(packaged_baseline)
        absent["comparisons"] = [
            comparison
            for comparison in absent["comparisons"]
            if comparison["comparison_kind"] != "atmosphere_statistics"
        ]
        failures = evaluate_report_against_baseline(absent, packaged_baseline)
        assert failures
        assert not any("statistical_definition" in failure for failure in failures)
        assert all(
            "<absent: missing from the fresh report>" in failure
            for failure in failures
        )

    def test_evaluation_flags_reordered_and_unreviewed_inventory(
        self,
        packaged_baseline,
    ):
        """A baseline gates exactly the evidence it was reviewed against.

        Walking only the baseline's inventory notices what a report is missing
        and nothing it adds, so an extra comparison, an extra metric, or a
        different comparison order evaluated clean — the report could carry
        measurements no reviewer ever saw and still be reported as covered.
        """

        reordered = _report_copy(packaged_baseline)
        reordered["comparisons"] = list(reversed(reordered["comparisons"]))
        failures = evaluate_report_against_baseline(reordered, packaged_baseline)
        assert any("out of canonical order" in f for f in failures)

        added = _report_copy(packaged_baseline)
        added["comparisons"].append(
            {
                "comparison_kind": "unreviewed_comparison",
                "attribution": "Not in the accepted baseline.",
                "metrics": [
                    {
                        "name": "unreviewed_metric",
                        "level": "informational",
                        "units": "ratio",
                        "value": 1.0,
                        "rationale": "Not reviewed.",
                        "pass_criterion": {"type": "informational"},
                    }
                ],
            }
        )
        failures = evaluate_report_against_baseline(added, packaged_baseline)
        assert any(
            "unreviewed_comparison" in failure
            and "comparisons the baseline does not record" in failure
            for failure in failures
        )

        # Dropping a comparison stays a rich per-metric report, not a terse
        # inventory line: the evidence for what is missing is more useful than
        # a second statement that it is missing.
        dropped = _report_copy(packaged_baseline)
        dropped["comparisons"] = [
            comparison
            for comparison in dropped["comparisons"]
            if comparison["comparison_kind"] != "runtime_and_memory"
        ]
        failures = evaluate_report_against_baseline(dropped, packaged_baseline)
        assert all("<absent: missing from the fresh report>" in f for f in failures)

        extra_metric = _report_copy(packaged_baseline)
        for comparison in extra_metric["comparisons"]:
            if comparison["comparison_kind"] == "strehl_ratio":
                comparison["metrics"].append(
                    {
                        "name": "unreviewed_strehl_variant",
                        "level": "informational",
                        "units": "ratio",
                        "value": 1.0,
                        "rationale": "Not reviewed.",
                        "pass_criterion": {"type": "informational"},
                    }
                )
        failures = evaluate_report_against_baseline(extra_metric, packaged_baseline)
        assert any(
            "reports metrics the baseline does not record" in failure
            and "unreviewed_strehl_variant" in failure
            for failure in failures
        )


class TestSuiteEntryPoint:
    def test_the_validation_package_never_imports_hcipy_eagerly(self):
        program = (
            "import sys\n"
            "import shwfs_ao.validation\n"
            "import shwfs_ao.validation.cross_backend\n"
            "import shwfs_ao.validation.physical\n"
            "import shwfs_ao.validation.regression\n"
            "raise SystemExit(1 if 'hcipy' in sys.modules else 0)\n"
        )
        result = subprocess.run(
            [sys.executable, "-c", program],
            capture_output=True,
            text=True,
            check=False,
        )
        assert result.returncode == 0, result.stderr

    def test_configuration_validation_precedes_the_dependency_requirement(
        self,
    ):
        with pytest.raises(CrossBackendError, match="CrossBackendConfig"):
            run_cross_backend_report(config=object())
        with pytest.raises(CrossBackendError, match="integer multiple"):
            CrossBackendConfig(pupil_pixels=50)
        with pytest.raises(CrossBackendError, match="at least 2"):
            CrossBackendConfig(atmosphere_realizations=1)
        with pytest.raises(CrossBackendError, match="loop_steps"):
            CrossBackendConfig(loop_steps=1)
        with pytest.raises(CrossBackendError, match="runtime_repeats"):
            CrossBackendConfig(runtime_repeats=0)

    def test_the_comparison_config_hash_is_deterministic(self):
        assert (
            CrossBackendConfig().config_hash == CrossBackendConfig().config_hash
        )
        assert (
            CrossBackendConfig(root_seed=119).config_hash
            != CrossBackendConfig().config_hash
        )

    @pytest.mark.skipif(
        HCIPY_INSTALLED,
        reason="requires an environment without the optional HCIPy dependency",
    )
    def test_running_the_suite_without_hcipy_names_the_missing_dependency(
        self,
    ):
        with pytest.raises(OptionalDependencyError) as excinfo:
            run_cross_backend_report()
        assert "pip install 'shack-hartmann-ao-simulation[hcipy]'" in str(
            excinfo.value
        )

    def test_the_hcipy_suite_file_never_enters_the_native_selection(self):
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "pytest",
                "-p",
                "no:cacheprovider",
                "--collect-only",
                "-q",
                "-m",
                "not hcipy and not slow",
                str(Path(__file__).with_name("test_native_vs_hcipy.py")),
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        # Exit code 5 is pytest's "no tests collected": every test in the
        # suite module must carry the hcipy marker and be deselected.
        assert result.returncode == 5, result.stdout + result.stderr
        assert "::" not in result.stdout
