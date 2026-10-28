"""The one-second exporter's content identity binds the shared producer-check rule and the sources it reads (R19-01).

``long_export.code_identity()["sha256"]`` keys every new dataset and is recorded in its provenance.  Since the exporter
judges producer records with ``web_contract.producer_check_problems``, whose contract is derived from the source of
``long_series.py`` and ``observer.py``, a change to any of these must change that digest.  Mutated sources live only in
disposable copies under pytest's temporary directory.  The semantic checks run in isolated child interpreters
(``python -I -B``) that import the copy's modules, call ``long_export.code_identity()`` and the copy's rule on two fixed
synthetic records, and report the ``shwfs_ao`` modules they imported (none of the experiment or control modules may
be among them).  No exporter run, no real data, no AO computation.
"""

from __future__ import annotations

import ast
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys

import pytest

import identity
import long_export
import web_contract


SCRIPTS = Path(identity.EXPORTER_DIR)
SRC = SCRIPTS.parents[1] / "src"


@pytest.fixture(autouse=True)
def _no_science(monkeypatch):
    import shwfs_ao.control.loop
    import shwfs_ao.experiments.detector_level
    import shwfs_ao.experiments.scao

    originals = (
        shwfs_ao.experiments.detector_level.science_run,
        shwfs_ao.experiments.scao.build_scao_system,
        shwfs_ao.experiments.scao.run_closed_loop,
        shwfs_ao.control.loop.run_closed_loop,
    )

    def forbidden(*_, **__):
        raise AssertionError("an exporter identity test reached a production or science entry point")

    monkeypatch.setattr(long_export.long_series, "run_case", forbidden)
    # Every loaded reference, import-time aliases included (``from .scao import build_scao_system`` and the like).
    for module in [module for name, module in list(sys.modules.items()) if name == "shwfs_ao" or name.startswith("shwfs_ao.")]:
        for name, value in list(vars(module).items()):
            if any(value is original for original in originals):
                monkeypatch.setattr(module, name, forbidden)


def rule_sources() -> list:
    """The files the shared rule reads, from web_contract.py itself: its sibling imports and the sources it parses."""

    tree = ast.parse((SCRIPTS / "web_contract.py").read_text(encoding="utf-8"))
    imported = {alias.name.split(".")[0] for node in ast.walk(tree) if isinstance(node, ast.Import) for alias in node.names}
    imported |= {node.module.split(".")[0] for node in ast.walk(tree) if isinstance(node, ast.ImportFrom) and node.module and node.level == 0}
    parsed = {node.args[0].value for node in ast.walk(tree)
              if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "with_name"
              and node.args and isinstance(node.args[0], ast.Constant) and isinstance(node.args[0].value, str)}
    siblings = {f"{name}.py" for name in imported if (SCRIPTS / f"{name}.py").is_file()}
    return sorted({"web_contract.py"} | siblings | parsed)


def _copy(tmp_path: Path) -> Path:
    copy = tmp_path / "repo" / "scripts" / "ao_explorer"
    copy.mkdir(parents=True)
    for path in SCRIPTS.glob("*.py"):
        shutil.copy2(path, copy / path.name)
    return copy


def _identity_of(copy: Path, monkeypatch) -> dict:
    # The real implementation, pointed at the copy (its Git state is that of a directory outside any repository).
    with monkeypatch.context() as scoped:
        scoped.setattr(identity, "EXPORTER_DIR", copy)
        scoped.setattr(identity, "REPO_ROOT", copy.parents[1])
        return long_export.code_identity()


def test_the_rule_reads_what_the_review_traced():
    assert rule_sources() == ["long_series.py", "observer.py", "protocol.py", "web_contract.py"]


def test_the_export_identity_lists_and_hashes_every_rule_source():
    code = long_export.code_identity()
    for name in rule_sources():
        assert name in long_export.CODE_FILES and code["files"][name] == hashlib.sha256((SCRIPTS / name).read_bytes()).hexdigest(), name
    assert code["sha256"] == identity.file_set_identity(long_export.CODE_FILES)["sha256"]
    # The numerical producer identity is a separate file set; observer.py stays in it, web_contract.py does not enter it.
    assert "observer.py" in identity.PRODUCER_FILES and "web_contract.py" not in identity.PRODUCER_FILES


@pytest.mark.parametrize("name", rule_sources())
def test_changing_only_one_rule_source_changes_the_export_digest(tmp_path, monkeypatch, name):
    copy = _copy(tmp_path)
    control = _identity_of(copy, monkeypatch)
    assert control["sha256"] == long_export.code_identity()["sha256"] and control["files"] == long_export.code_identity()["files"]
    (copy / name).write_bytes((copy / name).read_bytes() + b"\n# a change to this file alone\n")
    changed = _identity_of(copy, monkeypatch)
    assert changed["sha256"] != control["sha256"]
    assert [member for member in changed["files"] if changed["files"][member] != control["files"][member]] == [name]
    (copy / name).write_bytes((SCRIPTS / name).read_bytes())
    assert _identity_of(copy, monkeypatch) == control  # the same bytes give the same identity


CHILD = r'''
import json, sys
copy, src, records_in, out = sys.argv[1:5]
sys.path[:0] = [copy, src]
import long_export, web_contract
contract = web_contract.V2.producer_checks
window, count = (long_export.START, long_export.N_STEPS), long_export.COUNT
records = json.load(open(records_in))
judged = {name: web_contract.producer_check_problems(record, contract, window, count).ok for name, record in records.items()}
json.dump({"sha256": long_export.code_identity()["sha256"], "files": long_export.code_identity()["files"], "accepted": judged,
           "web_contract_file": web_contract.__file__, "shwfs_ao_modules": sorted(m for m in sys.modules if m.startswith("shwfs_ao"))}, open(out, "x"))
'''


def _records(tmp_path: Path) -> Path:
    contract = web_contract.V2.producer_checks
    conforming = {}
    for name in contract.recorded:
        if name in contract.required_true:
            conforming[name] = True
        elif name == contract.window_fields[0]:
            conforming[name] = [long_export.START, long_export.N_STEPS]
        elif name == contract.window_fields[1]:
            conforming[name] = long_export.COUNT
        else:
            conforming[name] = {key: 0.0 for key in contract.diagnostics[name][0]}
    path = tmp_path / "records.json"
    path.write_text(json.dumps({"conforming": conforming, "required_check_string_false": {**conforming, contract.required_true[0]: "false"}}))
    return path


def _child(copy: Path, records: Path, out: Path) -> dict:
    completed = subprocess.run([sys.executable, "-I", "-B", "-c", CHILD, str(copy), str(SRC), str(records), str(out)],
                               capture_output=True, text=True, timeout=300, check=False)
    assert completed.returncode == 0, completed.stderr[-3000:]
    seen = json.loads(out.read_text())
    assert Path(seen["web_contract_file"]).parent == copy  # the child judged with the copy's rule
    assert not [m for m in seen["shwfs_ao_modules"] if m.startswith(("shwfs_ao.experiments", "shwfs_ao.control"))], seen["shwfs_ao_modules"]
    return seen


MUTATIONS = {
    # The rule itself: a required check recorded as the string "false" would pass.
    "web_contract.py": ("for name in expected.required_true if checks.get(name) is not True)",
                        "for name in expected.required_true if checks.get(name) is not True and checks.get(name) != \"false\")",
                        {"conforming": True, "required_check_string_false": True}),
    # A source the rule parses: one diagnostic record's key renamed, so a conforming record no longer conforms.
    "observer.py": ("\"uncorrected\": float(np.max(np.abs(accumulator_uncorrected - own_uncorrected))),",
                    "\"uncorrected_renamed\": float(np.max(np.abs(accumulator_uncorrected - own_uncorrected))),",
                    {"conforming": False, "required_check_string_false": False}),
}


@pytest.mark.parametrize("name", sorted(MUTATIONS))
def test_a_rule_change_that_changes_acceptance_changes_the_export_digest(tmp_path, name):
    copy = _copy(tmp_path)
    records = _records(tmp_path)
    control = _child(copy, records, tmp_path / "control.json")
    assert control["accepted"] == {"conforming": True, "required_check_string_false": False}  # N19's strict rule
    assert control["sha256"] == long_export.code_identity()["sha256"]
    old, new, accepted = MUTATIONS[name]
    text = (copy / name).read_text(encoding="utf-8")
    assert text.count(old) == 1
    (copy / name).write_text(text.replace(old, new), encoding="utf-8")
    mutated = _child(copy, records, tmp_path / "mutated.json")
    assert mutated["accepted"] == accepted  # the mutation changes what the exporter accepts ...
    assert mutated["sha256"] != control["sha256"]  # ... and the content digest records it
    assert [member for member in mutated["files"] if mutated["files"][member] != control["files"][member]] == [name]
