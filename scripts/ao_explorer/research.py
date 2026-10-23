"""Research Results export: the project's eight main result groups, bound to saved evidence.

Every value, row and figure here is read from the frozen source tree
(``git show <SOURCE_SHA>:<path>``), never typed in: saved JSON/CSV records,
the stored outputs of notebooks (parsed, not executed) and canonical figure
files.  Nothing is simulated, executed or regenerated.  Each exported item
records its source path, the SHA-256 of the source bytes and a locator (JSON
key path, CSV rows/columns, notebook cell and output, or document lines with
a phrase the exporter checks is really there).

Copied figures and evidence downloads are byte-identical to their sources,
except the *source-bound extracts* of saved notebook outputs (R1, R2): JSON
files that copy the stored output text and configuration lines verbatim with
their notebook, cell, output and text digests, because the notebooks
themselves are too large to bundle.  Charts the browser draws are *derived
displays* of recorded rows, labelled as such with their transformation.
Missing or contradictory evidence is reported in the group's
``evidence_notes`` instead of being filled in.

Statements about historical producers (the science-image residual of the
42 m and 12 m runs) are bound to the producer's own commit, read the same way
but recorded separately in ``historical_sources_read``; where a producer ran
on a tree with uncommitted changes, the result says the identity is unknown.

The group texts (context, takeaway, limitations) are the explorer's own
summaries of those records; every number in them is formatted from the
extracted value it names.
"""

from __future__ import annotations

import ast
import base64
import csv
import hashlib
import html.parser
import io
import json
import math
import os
import re
import statistics
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import identity


SOURCE_SHA = "8053d25216ac180e327bf0b53afd93d1fc08d4ca"
RESULTS_SCHEMA = "ao-explorer.research-results.v1"
EXPORT_REVISION = "ao-explorer.research-export.v2"
EXTRACT_SCHEMA = "ao-explorer.notebook-output-extract.v1"
# Source links on the site open files at their recorded commit here.
REPOSITORY_URL = "https://github.com/xhvoid/Shack-Hartmann-AO-Simulation"
# Historical producers named by the records (both are ancestors of SOURCE_SHA).
PRODUCER_42M = "23125024e77769d067f53d837e035b340fc2139a"
PRODUCER_12M = "663df161d893d536a02244ea78bb8948167c854b"
# The 12 m review reruns name PRODUCER_12M plus uncommitted changes whose
# digest equals that of the PRODUCER_12M -> this commit diff of src and scripts
# (round-5 review, R5-F01): they ran on this commit's code.
PRODUCER_12M_RERUN = "573f875770212f6c5a2a718ca391abe2dfc51fc9"
EMPTY_TREE = "4b825dc642cb6eb9a060e54bf8d69288fbee4904"  # git's empty tree (SHA-1 object format)

STATUS_WORDS = {
    "executed": "Executed result (saved record of a completed run)",
    "accepted_domain": "Accepted comparison within its tested domain",
    "failed_hypothesis": "Recorded failed hypothesis",
    "summary_only": "Summary-only evidence (raw payload not retained)",
    "pending": "Pending work",
    "derived_analysis": "Saved-data reanalysis (no new simulation)",
    "analytic_model": "Analytical model output (not a time-domain simulation)",
}


class ResearchExportError(RuntimeError):
    """Raised when a required source, locator or value check fails."""


# ---------------------------------------------------------------------------
# Source access


class Sources:
    """Byte access to the frozen tree with a ledger of everything read."""

    def __init__(self, sha: str = SOURCE_SHA) -> None:
        self.tree_sha = sha
        self.read: Dict[str, Dict[str, Any]] = {}
        self.historical: Dict[str, Dict[str, Any]] = {}

    @staticmethod
    def _show(commit: str, path: str) -> bytes:
        try:
            return subprocess.run(
                ["git", "show", f"{commit}:{path}"],
                cwd=identity.REPO_ROOT,
                capture_output=True,
                check=True,
            ).stdout
        except subprocess.CalledProcessError as exc:
            raise ResearchExportError(f"missing source {path} at {commit}") from exc

    def bytes(self, path: str) -> bytes:
        data = self._show(self.tree_sha, path)
        digest = hashlib.sha256(data).hexdigest()
        working = identity.REPO_ROOT / path
        self.read[path] = {
            "path": path,
            "sha256": digest,
            "bytes": len(data),
            "working_tree_identical": working.is_file() and identity.sha256_file(working) == digest,
        }
        return data

    def json(self, path: str) -> Any:
        return json.loads(self.bytes(path).decode("utf-8"))

    def text(self, path: str) -> str:
        return self.bytes(path).decode("utf-8")

    def sha(self, path: str) -> str:
        if path not in self.read:
            self.bytes(path)
        return self.read[path]["sha256"]

    def lines(self, path: str, first: int, last: int, must_contain: str) -> Dict[str, Any]:
        """A document locator whose lines are checked to contain a phrase."""

        text = self.text(path).splitlines()
        window = "\n".join(text[first - 1:last])
        if must_contain not in window:
            raise ResearchExportError(f"{path}:{first}-{last} does not contain {must_contain!r}")
        return {"path": path, "lines": [first, last], "sha256": self.sha(path), "contains": must_contain}

    def source_change_digest(self, base: str, commit: str) -> str:
        """The digest a record's code identity gives a run on ``commit``'s src and scripts with HEAD at ``base``.

        The recording script (``run_detector_level_evidence.code_identity``)
        hashes ``git diff HEAD -- src scripts`` and then any untracked files;
        with none untracked this is the digest of the ``base``..``commit`` diff.
        The diff text is pinned to git's defaults of the recording run
        (round-6 review R6-F03; R7-F01, R9-F02 and R10-F01):

        - the diff runs in a throwaway bare git dir that borrows this
          repository's objects through ``objects/info/alternates`` and has
          no template, worktree or ``info/attributes``, and no configuration
          beyond the defaults ``git init`` writes, so nothing in the
          repository's git dir or worktree can reach it;
        - attributes come from the empty tree only (``--attr-source``) and no
          attributes file is read;
        - the options below override the user and system settings that change
          the text of this diff (prefixes, algorithm, order, context, blank
          lines, renames, quoting, colour, external diff and text conversion);
        - ``--text`` keeps git from treating a file as binary by size
          (``core.bigFileThreshold``, which is not pinned) or by attribute;
        - git configuration and object-directory variables in the
          environment are dropped, so they can neither inject settings nor
          redirect the borrowed objects;
        - object names are taken in full and cut to the 7 characters the
          record used, so a growing object database cannot lengthen them.

        Remaining requirements: git >= 2.42 (for ``--attr-source``) and a
        SHA-1 repository (``EMPTY_TREE``); otherwise git fails and the
        comparison fails closed, never succeeding falsely.
        """

        import tempfile

        environment = _plain_git_environment()

        def git(*args: str, cwd: Any) -> str:
            return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, check=True, env=environment).stdout.strip()

        objects = Path(git("rev-parse", "--path-format=absolute", "--git-common-dir", cwd=identity.REPO_ROOT)) / "objects"
        object_format = git("rev-parse", "--show-object-format", cwd=identity.REPO_ROOT)
        with tempfile.TemporaryDirectory(prefix="ao-explorer-digest-") as scratch:
            template = Path(scratch) / "template"
            template.mkdir()
            git_dir = Path(scratch) / "git"
            git("init", "--quiet", "--bare", f"--template={template}", f"--object-format={object_format}", str(git_dir), cwd=scratch)
            if (git_dir / "info" / "attributes").exists():
                raise ResearchExportError("the throwaway git dir has an info/attributes file")
            (git_dir / "objects" / "info").mkdir(parents=True, exist_ok=True)
            (git_dir / "objects" / "info" / "alternates").write_text(f"{objects}\n", encoding="utf-8")
            command = [
                "git",
                f"--git-dir={git_dir}",
                f"--attr-source={EMPTY_TREE}",
                "-c", f"core.attributesFile={os.devnull}",
                "-c", "diff.suppressBlankEmpty=false",
                "-c", "diff.noprefix=false",
                "-c", "diff.mnemonicPrefix=false",
                "-c", "diff.relative=false",
                "-c", "diff.algorithm=myers",
                "-c", "diff.indentHeuristic=true",
                "-c", "diff.renames=true",
                "-c", "core.quotePath=true",
                "diff", "--no-color", "--no-ext-diff", "--no-textconv", "--text", f"-O{os.devnull}", "--src-prefix=a/", "--dst-prefix=b/",
                "--full-index", "--unified=3", "--inter-hunk-context=0",
                base, commit, "--", "src", "scripts",
            ]
            diff = subprocess.run(command, cwd=scratch, capture_output=True, check=True, env=environment).stdout
        diff = re.sub(rb"^index ([0-9a-f]{40})\.\.([0-9a-f]{40})", lambda m: b"index " + m.group(1)[:7] + b".." + m.group(2)[:7], diff, flags=re.M)
        return hashlib.sha256(diff).hexdigest()

    def historical_lines(self, commit: str, path: str, phrase: str, span: int = 0, *, after: Optional[str] = None) -> Dict[str, Any]:
        """A line locator in a historical producer's own commit.

        The phrase must occur exactly once, or, with ``after``, be the first
        occurrence following the unique ``after`` line (e.g. inside one function).
        """

        if subprocess.run(["git", "merge-base", "--is-ancestor", commit, self.tree_sha], cwd=identity.REPO_ROOT).returncode != 0:
            raise ResearchExportError(f"{commit} is not an ancestor of the source commit {self.tree_sha}")
        data = self._show(commit, path)
        lines = data.decode("utf-8").splitlines()
        start = 0
        if after is not None:
            anchors = [index + 1 for index, line in enumerate(lines) if after in line]
            if len(anchors) != 1:
                raise ResearchExportError(f"{path} at {commit}: anchor {after!r} occurs {len(anchors)} times")
            start = anchors[0]
        hits = [index + 1 for index, line in enumerate(lines) if index + 1 > start and phrase in line]
        if after is not None:
            hits = hits[:1]
        if len(hits) != 1:
            raise ResearchExportError(f"{path} at {commit}: phrase {phrase!r} occurs {len(hits)} times")
        digest = hashlib.sha256(data).hexdigest()
        self.historical[f"{commit}:{path}"] = {"commit": commit, "path": path, "sha256": digest, "bytes": len(data)}
        return {"path": path, "commit": commit, "lines": [hits[0], hits[0] + span], "sha256": digest, "contains": phrase}


def _plain_git_environment() -> Dict[str, str]:
    """The process environment without variables that inject git configuration."""

    dropped = ("GIT_EXTERNAL_DIFF", "GIT_DIFF_OPTS", "GIT_ATTR_SOURCE", "GIT_TEMPLATE_DIR", "GIT_OBJECT_DIRECTORY", "GIT_ALTERNATE_OBJECT_DIRECTORIES")
    return {key: value for key, value in os.environ.items() if not key.startswith("GIT_CONFIG") and key not in dropped}


def phrase_lines(sources: Sources, path: str, phrase: str, span: int = 0) -> Dict[str, Any]:
    """Document locator found by its phrase (exactly one match), checked like ``lines``."""

    lines = sources.text(path).splitlines()
    hits = [index + 1 for index, line in enumerate(lines) if phrase in line]
    if len(hits) != 1:
        raise ResearchExportError(f"{path}: phrase {phrase!r} occurs {len(hits)} times")
    return sources.lines(path, hits[0], hits[0] + span, phrase)


def _first_after(sources: Sources, path: str, anchor: str, phrase: str, span: int = 0) -> Dict[str, Any]:
    """Document locator of the first ``phrase`` after the unique ``anchor`` line (e.g. inside one function)."""

    lines = sources.text(path).splitlines()
    start = phrase_lines(sources, path, anchor)["lines"][0]
    hits = [index + 1 for index, line in enumerate(lines) if index + 1 > start and phrase in line]
    if not hits:
        raise ResearchExportError(f"{path}: {phrase!r} does not follow {anchor!r}")
    return sources.lines(path, hits[0], hits[0] + span, phrase)


def locator(sources: Sources, path: str, where: str) -> Dict[str, Any]:
    return {"path": path, "sha256": sources.sha(path), "locator": where}


# Notebook outputs (parsed, never executed)


class _TableParser(html.parser.HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.rows: List[List[str]] = []
        self._row: Optional[List[str]] = None
        self._cell: Optional[List[str]] = None

    def handle_starttag(self, tag, attrs):
        if tag == "tr":
            self._row = []
        elif tag in ("td", "th") and self._row is not None:
            self._cell = []

    def handle_endtag(self, tag):
        if tag in ("td", "th") and self._row is not None and self._cell is not None:
            self._row.append("".join(self._cell).strip())
            self._cell = None
        elif tag == "tr" and self._row is not None:
            self.rows.append(self._row)
            self._row = None

    def handle_data(self, data):
        if self._cell is not None:
            self._cell.append(data)


def notebook_cell(sources: Sources, path: str, cell_id: str) -> Dict[str, Any]:
    notebook = sources.json(path)
    for index, cell in enumerate(notebook["cells"]):
        if cell.get("id") == cell_id:
            return {"index": index, "cell": cell}
    raise ResearchExportError(f"{path} has no cell {cell_id}")


def notebook_table(sources: Sources, path: str, cell_id: str) -> Tuple[List[str], List[List[str]], Dict[str, Any]]:
    found = notebook_cell(sources, path, cell_id)
    for output_index, output in enumerate(found["cell"].get("outputs", [])):
        html_lines = output.get("data", {}).get("text/html")
        if html_lines:
            parser = _TableParser()
            parser.feed("".join(html_lines))
            header = parser.rows[0]
            rows = parser.rows[1:]
            where = f"cell {cell_id} (index {found['index']}) output {output_index} text/html table"
            return header, rows, locator(sources, path, where)
    raise ResearchExportError(f"{path} cell {cell_id} has no HTML table output")


def notebook_stream(sources: Sources, path: str, cell_id: str) -> Tuple[str, Dict[str, Any]]:
    found = notebook_cell(sources, path, cell_id)
    for output_index, output in enumerate(found["cell"].get("outputs", [])):
        if output.get("output_type") == "stream":
            where = f"cell {cell_id} (index {found['index']}) output {output_index} stream"
            return "".join(output["text"]), locator(sources, path, where)
    raise ResearchExportError(f"{path} cell {cell_id} has no stream output")


def notebook_png(sources: Sources, path: str, cell_id: str) -> Tuple[bytes, Dict[str, Any]]:
    found = notebook_cell(sources, path, cell_id)
    pngs = [
        (index, output)
        for index, output in enumerate(found["cell"].get("outputs", []))
        if "image/png" in output.get("data", {})
    ]
    if len(pngs) != 1:
        raise ResearchExportError(f"{path} cell {cell_id} has {len(pngs)} PNG outputs; expected one")
    index, output = pngs[0]
    data = base64.b64decode("".join(output["data"]["image/png"]))
    where = f"cell {cell_id} (index {found['index']}) output {index} image/png"
    return data, locator(sources, path, where)


def notebook_output_record(sources: Sources, path: str, cell_id: str, kind: str, used_for: List[str]) -> Dict[str, Any]:
    """The stored text of a cell's first ``stream`` or ``text/html`` output, verbatim, with its identity.

    These are the same outputs ``notebook_stream`` and ``notebook_table`` read.
    ``text_sha256`` is the SHA-256 of the UTF-8 text, the stored lines joined
    without separators.
    """

    found = notebook_cell(sources, path, cell_id)
    for output_index, output in enumerate(found["cell"].get("outputs", [])):
        if kind == "stream" and output.get("output_type") == "stream":
            text, mime = "".join(output["text"]), f"stream:{output.get('name', 'stdout')}"
        elif kind == "text/html" and output.get("data", {}).get("text/html"):
            text, mime = "".join(output["data"]["text/html"]), "text/html"
        else:
            continue
        record = {
            "notebook": path,
            "notebook_sha256": sources.sha(path),
            "cell_id": cell_id,
            "cell_index": found["index"],
            "execution_count": found["cell"].get("execution_count"),
            "output_index": output_index,
            "output_type": output.get("output_type"),
            "mime": mime,
            "text": text,
            "text_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
            "used_for": used_for,
        }
        if kind == "text/html":
            parser = _TableParser()
            parser.feed(text)
            record["parsed_table"] = {"header": parser.rows[0], "rows": parser.rows[1:], "parser": "HTML <tr>/<td>/<th> text, stripped; values are the stored display strings"}
        return record
    raise ResearchExportError(f"{path} cell {cell_id} has no {kind} output")


def notebook_assignment(sources: Sources, path: str, cell_id: str, name: str) -> Tuple[Any, Dict[str, Any]]:
    """The literal value of one ``NAME = literal`` line of a configuration cell, with its locator."""

    found = notebook_cell(sources, path, cell_id)
    lines = "".join(found["cell"]["source"]).splitlines()
    hits = [(number, line.strip()) for number, line in enumerate(lines, 1) if re.fullmatch(rf"{re.escape(name)}\s*=\s*\S.*", line.strip())]
    if len(hits) != 1:
        raise ResearchExportError(f"{path} cell {cell_id}: {name} is assigned {len(hits)} times")
    number, line = hits[0]
    value = ast.literal_eval(line.split("=", 1)[1].strip())
    where = f"cell {cell_id} (index {found['index']}) source line {number}: {line}"
    return value, {
        "path": path,
        "sha256": sources.sha(path),
        "locator": where,
        "cell_id": cell_id,
        "cell_index": found["index"],
        "source_line": number,
        "text": line,
        "name": name,
        "value": value,
    }


def png_size(data: bytes) -> List[int]:
    if data[:8] != b"\x89PNG\r\n\x1a\n":
        raise ResearchExportError("not a PNG")
    return [int.from_bytes(data[16:20], "big"), int.from_bytes(data[20:24], "big")]


def number(text: str) -> Optional[float]:
    text = text.strip()
    if text in ("NaN", "nan", ""):
        return None
    return float(text)


def fmt(value: float, digits: int) -> str:
    return f"{value:.{digits}f}"


# ---------------------------------------------------------------------------
# Export helpers


class Writer:
    def __init__(self, bundle: Any, sources: Sources) -> None:
        self.bundle = bundle
        self.sources = sources

    def figure(self, source_path: str, *, caption: str, provenance: Dict[str, Any], alt: str) -> Dict[str, Any]:
        data = self.sources.bytes(source_path)
        name = "research/assets/" + source_path.replace("/", "__")
        entry = self.bundle.write(name, data, media_type="image/png", role="research_figure")
        return {
            "kind": "source_figure",
            "asset": _ref(entry),
            "source": locator(self.sources, source_path, "whole file"),
            "byte_identical_copy": True,
            "pixel_size": png_size(data),
            "caption": caption,
            "alt": alt,
            "provenance": provenance,
        }

    def extracted_png(self, notebook: str, cell_id: str, *, caption: str, alt: str) -> Dict[str, Any]:
        data, where = notebook_png(self.sources, notebook, cell_id)
        name = f"research/assets/{notebook.replace('/', '__')}__{cell_id}.png"
        entry = self.bundle.write(name, data, media_type="image/png", role="research_figure")
        return {
            "kind": "extracted_notebook_output",
            "asset": _ref(entry),
            "source": where,
            "byte_identical_copy": True,
            "transformation": "base64-decoded saved image/png output; not executed, not re-rendered",
            "pixel_size": png_size(data),
            "caption": caption,
            "alt": alt,
        }

    def download(self, source_path: str, *, label: str, media_type: str = "application/json") -> Dict[str, Any]:
        data = self.sources.bytes(source_path)
        name = "research/evidence/" + source_path.replace("/", "__")
        entry = self.bundle.write(name, data, media_type=media_type, role="research_evidence")
        return {
            "label": label,
            "kind": "byte_identical_copy",
            "asset": _ref(entry),
            "source": locator(self.sources, source_path, "whole file"),
            "file_name": source_path.split("/")[-1],
        }

    def extract(self, group_id: str, *, label: str, outputs: List[Dict[str, Any]], configuration: List[Dict[str, Any]], figures: List[Dict[str, Any]]) -> Dict[str, Any]:
        """A source-bound extract of saved notebook outputs (external review ER-F02), offered as a download."""

        payload = {
            "schema": EXTRACT_SCHEMA,
            "group": group_id,
            "source_sha": self.sources.tree_sha,
            "repository": REPOSITORY_URL,
            "extraction": (
                "Saved outputs and configuration lines copied verbatim from the notebooks committed at source_sha; the notebooks "
                "were parsed, never executed. text_sha256 is the SHA-256 of the UTF-8 output text (stored lines joined without "
                "separators); notebook_sha256 is the SHA-256 of the whole notebook file. Figures are bound by file and output digest only."
            ),
            "outputs": outputs,
            "configuration": [{key: item[key] for key in ("path", "sha256", "cell_id", "cell_index", "source_line", "text", "name", "value")} for item in configuration],
            "figures": figures,
        }
        data = (json.dumps(payload, indent=1, allow_nan=False, ensure_ascii=False) + "\n").encode("utf-8")
        entry = self.bundle.write(f"research/evidence/{group_id}__saved_notebook_outputs.json", data, media_type="application/json", role="research_extract")
        notebooks = sorted({item["notebook"] for item in outputs} | {item["path"] for item in configuration})
        return {
            "label": label,
            "kind": "source_bound_extract",
            "asset": _ref(entry),
            "sources": [locator(self.sources, path, "whole file") for path in notebooks],
            "file_name": f"{group_id}-saved-notebook-outputs.json",
        }


def _ref(entry: Dict[str, Any]) -> Dict[str, Any]:
    # Members are referenced relative to research/results.json.
    path = entry["path"]
    if not path.startswith("research/"):
        raise ResearchExportError("research members live under research/")
    return {"href": path[len("research/"):], "bytes": entry["bytes"], "sha256": entry["sha256"], "media_type": entry["media_type"]}


def _extract_figure(sources: Sources, figure_path: str, output_png: bytes, output_loc: Dict[str, Any]) -> Dict[str, Any]:
    output_sha = hashlib.sha256(output_png).hexdigest()
    return {
        "figure": figure_path,
        "figure_sha256": sources.sha(figure_path),
        "notebook_output": output_loc,
        "output_png_sha256": output_sha,
        "byte_identical_to_notebook_output": output_sha == sources.sha(figure_path),
    }


def mean_sd(values: List[float]) -> Tuple[float, float]:
    return statistics.fmean(values), statistics.stdev(values)


# ---------------------------------------------------------------------------
# R1 - sensing


def group_r1(w: Writer) -> Dict[str, Any]:
    s = w.sources
    nb1 = "notebooks/tutorials/01_geometric_shwfs.ipynb"
    nb2 = "notebooks/tutorials/02_detector_centroiding.ipynb"
    stream, stream_loc = notebook_stream(s, nb1, "e3efd106")
    match = re.search(r"Co-axis measured / geometric gain: \[([0-9.]+) ([0-9.]+)\]", stream)
    if not match:
        raise ResearchExportError("R1 response ratio string not found")
    ratio = float(match.group(1))
    header, rows, table_loc = notebook_table(s, nb2, "7f485086")
    precision_rows = []
    for row in rows:
        photons, rms, fraction, components, reference = row[1], row[2], row[3], row[4], row[5]
        rms_value = number(rms)
        precision_rows.append(
            {
                "photons": int(photons),
                "rms_px": rms_value,
                "rms_px_null_reason": None if rms_value is not None else "no valid centroid component at this budget (NaN in the source; not zero error)",
                "valid_fraction": float(fraction),
                "valid_components": int(components),
                "inverse_sqrt_reference_px": float(reference),
            }
        )
    by_photons = {row["photons"]: row for row in precision_rows}
    configuration = []
    for notebook, cell in ((nb1, "b6324452"), (nb2, "84a59143")):
        for name in ("TELESCOPE_DIAMETER_M", "WFS_WAVELENGTH_M"):
            configuration.append(notebook_assignment(s, notebook, cell, name)[1])
    apertures = {item["value"] for item in configuration if item["name"] == "TELESCOPE_DIAMETER_M"}
    wavelengths = {item["value"] for item in configuration if item["name"] == "WFS_WAVELENGTH_M"}
    if len(apertures) != 1 or len(wavelengths) != 1:
        raise ResearchExportError(f"R1 tutorials differ in aperture {apertures} or WFS wavelength {wavelengths}")
    figures = []
    extract_figures = []
    for figure_path, notebook, cell, caption, alt in (
        (
            "figures/canonical_sensor_calibration.png",
            nb1,
            "040f62ee",
            "Driven-axis tilt response of the geometric Shack-Hartmann tutorial: measured centroid displacement against the geometric prediction.",
            "Tutorial 01 sensor calibration figure",
        ),
        (
            "figures/canonical_detector_centroiding.png",
            nb2,
            "c9ff2808",
            "Detector-level centroid precision over valid components and valid-measurement availability against photon budget (12 realizations per budget).",
            "Tutorial 02 detector centroiding figure",
        ),
    ):
        output_png, output_loc = notebook_png(s, notebook, cell)
        same = hashlib.sha256(output_png).hexdigest() == s.sha(figure_path)
        figures.append(
            w.figure(
                figure_path,
                caption=caption,
                alt=alt,
                provenance={"notebook_output": output_loc, "byte_identical_to_notebook_output": same, "registry": locator(s, "figures/README.md", "lines 9-24 canonical figure table")},
            )
        )
        extract_figures.append(_extract_figure(s, figure_path, output_png, output_loc))
    s.lines("figures/README.md", 18, 24, "12 realizations per photon")
    low, high = by_photons[1000], by_photons[100000]
    outputs = [
        notebook_output_record(s, nb1, "e3efd106", "stream", ["key value: co-axis measured / geometric gain"]),
        notebook_output_record(s, nb2, "7f485086", "text/html", ["table r1-precision", "chart r1-precision-chart", "key values: centroid RMS, valid components"]),
    ]
    extract = w.extract("R1", label="Saved notebook outputs behind the R1 values (JSON extract)", outputs=outputs, configuration=configuration, figures=extract_figures)
    return {
        "id": "R1",
        "title": "Sensing: calibrated response, precision and measurement availability",
        "question": "How faithfully does the Shack-Hartmann sensor measure tilt, and when do its measurements stop being usable?",
        "context": {
            "model_family": "native time-domain SCAO components (tutorial configurations)",
            "aperture_m": apertures.pop(),
            "profile": "tutorial notebook configurations (not the explorer's 2 m profile)",
            "wfs_wavelength_m": wavelengths.pop(),
            "noise_policy": "tutorial 01: geometric, noiseless; tutorial 02: detector chain with photon noise (read noise not set in this tutorial)",
            "realizations": "12 per photon budget (tutorial 02)",
            "uncertainty": "none stored; RMS pooled over the valid components of 12 realizations",
        },
        "status": ["executed"],
        "key_values": [
            {"label": "Co-axis measured / geometric gain", "value": ratio, "display": fmt(ratio, 8), "unit": "", "source": stream_loc},
            {"label": "Centroid RMS at 1,000 photons", "value": low["rms_px"], "display": fmt(low["rms_px"], 6), "unit": "px", "source": table_loc},
            {"label": "Centroid RMS at 100,000 photons", "value": high["rms_px"], "display": fmt(high["rms_px"], 6), "unit": "px", "source": table_loc},
            {"label": "Valid components at 500 photons", "value": by_photons[500]["valid_components"], "display": str(by_photons[500]["valid_components"]), "unit": "", "source": table_loc},
        ],
        "tables": [
            {
                "id": "r1-precision",
                "title": "Centroid precision and availability against photon budget (tutorial 02)",
                "columns": [
                    {"key": "photons", "label": "Photons per sub-aperture", "unit": ""},
                    {"key": "rms_px", "label": "Valid-component RMS error", "unit": "px", "digits": 6},
                    {"key": "valid_fraction", "label": "Valid component fraction", "unit": "", "digits": 1},
                    {"key": "valid_components", "label": "Valid components", "unit": ""},
                    {"key": "inverse_sqrt_reference_px", "label": "N^-1/2 reference (anchored at 1,000)", "unit": "px", "digits": 6},
                ],
                "rows": precision_rows,
                "source": table_loc,
                "precision_note": "values are the notebook's saved 6-decimal display; no higher-precision copy is stored",
            }
        ],
        "charts": [
            {
                "id": "r1-precision-chart",
                "type": "line",
                "title": "Centroid RMS error against photon budget",
                "x": {"label": "Photons per sub-aperture", "unit": "", "scale": "log"},
                "y": {"label": "Valid-component RMS error", "unit": "px", "scale": "log"},
                "series": [
                    {"label": "Measured (valid components)", "points": [[row["photons"], row["rms_px"]] for row in precision_rows], "style": "points"},
                    {"label": "N^-1/2 reference", "points": [[row["photons"], row["inverse_sqrt_reference_px"]] for row in precision_rows], "style": "dashed"},
                ],
                "missing": [{"x": 500, "reason": "no valid component; precision undefined (shown as a gap, not zero)"}],
                "derived_from": "r1-precision",
                "transformation": "plotted directly from the recorded table rows",
            }
        ],
        "figures": figures,
        "takeaway": (
            f"In the 1 m tutorial geometry the measured co-axis response is {fmt(ratio, 4)} of the geometric prediction, so the "
            "sensor gain is calibrated rather than assumed. Valid-component centroid error falls from "
            f"{fmt(low['rms_px'], 4)} px at 1,000 photons to {fmt(high['rms_px'], 4)} px at 100,000 photons, close to the "
            "inverse-square-root reference; at 500 photons no component is valid, so precision is undefined there, not small."
        ),
        "limitations": [
            "Tutorial configurations (1 m aperture, small lenslet grids); they illustrate the sensing chain, not the explorer's 2 m profile.",
            "Values are the notebooks' saved display strings (8 and 6 decimals); no uncertainty is stored.",
            "Precision is reported over valid components only; availability is shown beside it so rejected measurements are not counted as zero error.",
        ],
        "evidence_notes": [
            "Tutorial 02's question cell mentions read noise, but the tutorial sets no read noise (DetectorConfig default 0 e-).",
        ],
        "producer": {"commit": "absent", "host": "absent", "note": "saved notebook outputs; only notebook execution metadata exists"},
        "licence": "Repository-authored notebooks and figures (MIT, see LICENSE).",
        "downloads": [extract],
        "sources": [stream_loc, table_loc],
        "context_sources": configuration,
    }


# ---------------------------------------------------------------------------
# R2 - reconstruction and feedback


def group_r2(w: Writer) -> Dict[str, Any]:
    s = w.sources
    nb3 = "notebooks/tutorials/03_tsvd_regularization.ipynb"
    nb4 = "notebooks/tutorials/04_closed_loop_control.ipynb"
    nbg = "notebooks/studies/noise_latency_gain.ipynb"
    nbo = "notebooks/studies/high_order_scao.ipynb"
    header, rows, tsvd_loc = notebook_table(s, nb3, "cc250317")
    tsvd = [{"rcond": float(r[1]), "kept_modes": int(r[2]), "command_rms_nm": float(r[3])} for r in rows]
    header, rows, loop_loc = notebook_table(s, nb4, "7711ca5c")
    loop = {r[1]: r[2] for r in rows}
    open_loop = float(loop["Open-loop RMS (final half)"])
    closed_loop = float(loop["Closed-loop RMS (final half)"])
    fraction = float(loop["Residual fraction"])
    header, rows, gl_loc = notebook_table(s, nbg, "73818237")
    gains = [float(h.replace("gain", "").strip()) for h in header[1:]]
    gain_latency = []
    for r in rows:
        latency = int(r[0].split()[1])
        for gain, value in zip(gains, r[1:]):
            gain_latency.append({"latency_frames": latency, "gain": gain, "rms_ratio": float(value)})
    gl_stream, gl_stream_loc = notebook_stream(s, nbg, "73818237")
    header, rows, order_loc = notebook_table(s, nbo, "59b3a84e")
    order = [
        {
            "actuators_across": int(r[1]),
            "active_actuators": int(r[2]),
            "open_loop_rms_nm": float(r[3]),
            "closed_loop_rms_nm": float(r[4]),
            "marechal_h_band": float(r[5]),
        }
        for r in rows
    ]
    figures = []
    extract_figures = []
    for figure_path, notebook, cell, caption in (
        ("figures/canonical_tsvd_regularization.png", nb3, "8489efca", "TSVD regularization: command error against the number of kept modes (one noise realization at 4e3 photons)."),
        ("figures/canonical_closed_loop_control.png", nb4, "f3661b4a", "12-frame noiseless native closed loop: open-loop and corrected residual RMS."),
        ("figures/canonical_gain_latency.png", nbg, "5f7971a4", "Gain and delay: matched-window RMS ratio for latencies of 0, 1 and 2 frames (noise disabled)."),
        ("figures/canonical_correction_order.png", nbo, "2e99ae6f", "Correction order at 1.5 m: closed-loop RMS and H-band Marechal estimate for 5, 7 and 9 actuators across."),
    ):
        output_png, output_loc = notebook_png(s, notebook, cell)
        figures.append(
            w.figure(
                figure_path,
                caption=caption,
                alt=caption,
                provenance={"notebook_output": output_loc, "byte_identical_to_notebook_output": hashlib.sha256(output_png).hexdigest() == s.sha(figure_path)},
            )
        )
        extract_figures.append(_extract_figure(s, figure_path, output_png, output_loc))
    best = min(row["command_rms_nm"] for row in tsvd)
    best_modes = min(row["kept_modes"] for row in tsvd if row["command_rms_nm"] == best)
    latency2 = {row["gain"]: row["rms_ratio"] for row in gain_latency if row["latency_frames"] == 2}
    # Wavelengths and apertures from each notebook's configuration cell
    # (external review ER-F03); the H-band estimate uses SCIENCE_WAVELENGTH_M in the
    # Marechal line of the correction-order study.
    configuration = []
    for notebook, cell in ((nb3, "e83ec727"), (nb4, "164f45d8"), (nbg, "e440722e"), (nbo, "cc8585d2")):
        for name in ("TELESCOPE_DIAMETER_M", "WFS_WAVELENGTH_M"):
            configuration.append(notebook_assignment(s, notebook, cell, name)[1])
    science_wavelength, science_loc = notebook_assignment(s, nbo, "cc8585d2", "SCIENCE_WAVELENGTH_M")
    configuration.append(science_loc)
    wavelengths = {item["value"] for item in configuration if item["name"] == "WFS_WAVELENGTH_M"}
    if len(wavelengths) != 1:
        raise ResearchExportError(f"R2 notebooks differ in WFS wavelength: {wavelengths}")
    apertures = {item["path"]: item["value"] for item in configuration if item["name"] == "TELESCOPE_DIAMETER_M"}
    if [apertures[nb3], apertures[nb4], apertures[nbg], apertures[nbo]] != [1.0, 1.0, 1.0, 1.5]:
        raise ResearchExportError(f"R2 apertures differ from the stated 1 m / 1.5 m: {apertures}")
    marechal = notebook_cell(s, nbo, "63d37537")
    marechal_line = next((line.strip() for line in "".join(marechal["cell"]["source"]).splitlines() if "np.exp(-((2 * np.pi * settled / SCIENCE_WAVELENGTH_M) ** 2))" in line), None)
    if marechal_line is None:
        raise ResearchExportError("R2: the Marechal line of the correction-order study was not found")
    marechal_loc = locator(s, nbo, f"cell 63d37537 (index {marechal['index']}): {marechal_line}")
    outputs = [
        notebook_output_record(s, nb3, "cc250317", "text/html", ["table r2-tsvd", "key value: TSVD minimum command error"]),
        notebook_output_record(s, nb4, "7711ca5c", "text/html", ["key value and takeaway: tutorial 04 open loop -> closed loop"]),
        notebook_output_record(s, nbg, "73818237", "text/html", ["table r2-gain-latency", "chart r2-gain-latency-chart", "key value: two-frame delay RMS ratio"]),
        notebook_output_record(s, nbg, "73818237", "stream", ["table r2-gain-latency notes"]),
        notebook_output_record(s, nbo, "59b3a84e", "text/html", ["table r2-order", "takeaway: correction order"]),
    ]
    extract = w.extract("R2", label="Saved notebook outputs behind the R2 values (JSON extract)", outputs=outputs, configuration=configuration, figures=extract_figures)
    return {
        "id": "R2",
        "title": "Reconstruction and feedback: correction, delay and controllable order",
        "question": "How do regularization, loop gain, delay and the number of actuators shape the correction?",
        "context": {
            "model_family": "native time-domain SCAO (tutorial and study notebooks)",
            "aperture_m": "1 m (tutorials 03 and 04, gain/delay study); 1.5 m (correction-order study)",
            "wfs_wavelength_m": wavelengths.pop(),
            "h_band_estimate_wavelength_m": science_wavelength,
            "h_band_estimate": "Marechal exp(-(2 pi sigma / lambda)^2) at lambda = SCIENCE_WAVELENGTH_M, with sigma the mean post-update residual RMS over the final half of the 14 frames (correction-order study); no science image is propagated",
            "noise_policy": "tutorial 04, gain/delay and correction-order runs: detector noise disabled; TSVD scan: one noise realization at 4e3 photons",
            "residual": "post-update residual RMS (history.post_update_residual_opd_rms_m) in tutorial 04, the gain/delay study and the correction-order study; the TSVD scan reports command error, not a residual",
            "window": "tutorial 04: final half of 12 frames; gain/delay: final half of 16 frames; correction order: final half of 14 frames",
            "realizations": "single realization per configuration",
            "uncertainty": "none stored",
        },
        "status": ["executed"],
        "key_values": [
            {"label": "Tutorial 04 open loop -> closed loop", "value": [open_loop, closed_loop], "display": f"{fmt(open_loop, 6)} -> {fmt(closed_loop, 6)}", "unit": "nm", "source": loop_loc},
            {"label": "TSVD minimum command error", "value": best, "display": f"{fmt(best, 6)} (at {best_modes} kept modes)", "unit": "nm", "source": tsvd_loc},
            {"label": "Two-frame delay RMS ratio, gain 0.2 -> 1.0", "value": [latency2[0.2], latency2[1.0]], "display": f"{fmt(latency2[0.2], 6)} -> {fmt(latency2[1.0], 6)}", "unit": "", "source": gl_loc},
        ],
        "tables": [
            {"id": "r2-tsvd", "title": "TSVD truncation scan (tutorial 03)", "columns": [
                {"key": "rcond", "label": "rcond", "unit": ""}, {"key": "kept_modes", "label": "Kept modes", "unit": ""}, {"key": "command_rms_nm", "label": "Command RMS error", "unit": "nm", "digits": 6}],
             "rows": tsvd, "source": tsvd_loc},
            {"id": "r2-gain-latency", "title": "Matched-window RMS ratio by gain and latency (noise disabled)", "columns": [
                {"key": "latency_frames", "label": "Latency", "unit": "frames"}, {"key": "gain", "label": "Gain", "unit": ""}, {"key": "rms_ratio", "label": "RMS ratio (closed / open)", "unit": "", "digits": 6}],
             "rows": gain_latency, "source": gl_loc, "notes": gl_stream.strip()},
            {"id": "r2-order", "title": "Correction order at 1.5 m (H-band Marechal estimate includes tilt)", "columns": [
                {"key": "actuators_across", "label": "Actuators across", "unit": ""}, {"key": "active_actuators", "label": "Active actuators", "unit": ""},
                {"key": "open_loop_rms_nm", "label": "Open-loop RMS", "unit": "nm", "digits": 6}, {"key": "closed_loop_rms_nm", "label": "Closed-loop RMS", "unit": "nm", "digits": 6},
                {"key": "marechal_h_band", "label": "H-band Marechal estimate", "unit": "", "digits": 6}],
             "rows": order, "source": order_loc},
        ],
        "charts": [
            {
                "id": "r2-gain-latency-chart",
                "type": "line",
                "title": "RMS ratio against gain for each latency",
                "x": {"label": "Integrator gain", "unit": "", "scale": "linear"},
                "y": {"label": "Closed / open RMS ratio", "unit": "", "scale": "linear"},
                "series": [
                    {"label": f"latency {latency} frame(s)", "points": [[row["gain"], row["rms_ratio"]] for row in gain_latency if row["latency_frames"] == latency]}
                    for latency in sorted({row["latency_frames"] for row in gain_latency})
                ],
                "reference_lines": [{"y": 1.0, "label": "no correction"}],
                "derived_from": "r2-gain-latency",
                "transformation": "plotted directly from the recorded table rows",
            }
        ],
        "figures": figures,
        "takeaway": (
            f"The 12-frame noiseless tutorial loop reduces the final-half residual from {fmt(open_loop, 1)} to {fmt(closed_loop, 1)} nm "
            f"(fraction {fmt(fraction, 3)}). TSVD reaches its {fmt(best, 2)} nm minimum command error once {best_modes} modes are kept. "
            f"Delay limits usable gain: with two frames of latency the RMS ratio rises from {fmt(latency2[0.2], 3)} at gain 0.2 to "
            f"{fmt(latency2[1.0], 3)} at gain 1.0, i.e. the loop amplifies the disturbance. More actuators help at 1.5 m "
            f"({fmt(order[0]['closed_loop_rms_nm'], 1)} -> {fmt(order[-1]['closed_loop_rms_nm'], 1)} nm from {order[0]['actuators_across']} to {order[-1]['actuators_across']} across)."
        ),
        "limitations": [
            "Short single-realization runs (12-16 frames) with noise disabled; they do not establish general stability limits.",
            "Tutorials 03 and 04 are different systems; the reconstruction-to-correction chain is illustrative, not one pipeline.",
            "The correction-order H-band value is a Marechal estimate from the residual RMS (tilt included), not a propagated image Strehl, and not a pure fitting-error decomposition.",
            "Tutorial 04's 12-frame trajectories and tutorial 03's singular spectrum are stored only inside the figures, so they are shown as figures, not re-plotted.",
        ],
        "evidence_notes": [],
        "producer": {"commit": "absent", "host": "absent", "note": "saved notebook outputs"},
        "licence": "Repository-authored notebooks and figures (MIT, see LICENSE).",
        "downloads": [extract],
        "sources": [tsvd_loc, loop_loc, gl_loc, gl_stream_loc, order_loc],
        "context_sources": configuration + [marechal_loc],
    }


# ---------------------------------------------------------------------------
# R3 - ESO ten-layer turbulence


def _csv_rows(text: str) -> List[Dict[str, str]]:
    return list(csv.DictReader(io.StringIO(text)))


def group_r3(w: Writer) -> Dict[str, Any]:
    s = w.sources
    base = "figures/eso_elt_turbulence/"
    profile = _csv_rows(s.text(base + "eso_elt_turbulence_profile.csv"))
    structure = _csv_rows(s.text(base + "eso_elt_structure_function.csv"))
    loop_rows = _csv_rows(s.text(base + "eso_elt_closed_loop.csv"))
    profiles = sorted({row["profile"] for row in loop_rows})
    summary = []
    per_frame_series = []
    for name in profiles:
        rows = [row for row in loop_rows if row["profile"] == name]
        atmosphere = rows[0]["atmosphere"]
        window = [row for row in rows if int(row["frame"]) >= 50]
        realizations = sorted({int(row["realization_index"]) for row in rows})
        frames = sorted({int(row["frame"]) for row in rows})
        per_real = []
        for realization in realizations:
            values = [float(row["residual_rms_nm"]) for row in window if int(row["realization_index"]) == realization]
            per_real.append(statistics.fmean(values))
        mean_open = statistics.fmean(float(row["open_loop_rms_nm"]) for row in window)
        mean_res = statistics.fmean(float(row["residual_rms_nm"]) for row in window)
        summary.append(
            {
                "profile": name,
                "atmosphere": atmosphere,
                "realizations": len(realizations),
                "frames": f"{frames[0]}-{frames[-1]}",
                "window": "frames 50-149",
                "mean_open_loop_rms_nm": mean_open,
                "mean_residual_rms_nm": mean_res,
                "realization_sd_of_mean_residual_nm": statistics.stdev(per_real),
            }
        )
        means = []
        for frame in frames:
            values = [float(row["residual_rms_nm"]) for row in rows if int(row["frame"]) == frame]
            means.append([frame, statistics.fmean(values)])
        per_frame_series.append({"label": f"{name} ({atmosphere})", "points": means})
    figure = w.figure(
        base + "eso_elt_turbulence_demo.png",
        caption="ESO ten-layer turbulence demonstration: layer profile, phase structure function against von Karman, and the closed-loop comparison with a single 10 m/s layer.",
        alt="ESO ten-layer turbulence demonstration figure",
        provenance={"producer_script": locator(s, "examples/run_eso_elt_turbulence_demo.py", "whole file"), "definitions": s.lines("docs/eso_elt_turbulence_model.md", 289, 294, "8 realizations")},
    )
    profile_rows = [
        {
            "altitude_m": float(row["altitude_m"]),
            "published_cn2_fraction": float(row["published_cn2_fraction"]),
            "cn2_fraction": float(row["cn2_fraction"]),
            "wind_speed_m_per_s": float(row["wind_speed_m_per_s"]),
            "layer_r0_500nm_m": float(row["layer_r0_500nm_m"]),
        }
        for row in profile
    ]
    structure_rows = [{key: float(value) for key, value in row.items()} for row in structure]
    lookup = {row["profile"]: row for row in summary}
    ten = next(row for row in summary if "eso_turbulence" in row["profile"])
    single = next(row for row in summary if "portfolio" in row["profile"])
    ratios = [row["ratio"] for row in structure_rows]
    return {
        "id": "R3",
        "title": "ESO ten-layer turbulence and its 2 m time-domain consequences",
        "question": "Does the layered atmosphere reproduce its statistics, and how does it change a 2 m closed loop?",
        "context": {
            "model_family": "native time-domain SCAO with the native layered atmosphere",
            "aperture_m": 2.0,
            "profiles": profiles,
            "wfs_wavelength_m": 7.0e-7,
            "structure_function_reference_wavelength_m": 5.0e-7,
            "noise_policy": "controller.include_noise is false in both profiles: the loop comparison is noise-free",
            "residual": "post_update_residual_opd_rms_m per frame",
            "window": "frames 50-149 of 150",
            "realizations": "8 per profile",
            "uncertainty": "sample SD across the 8 realization means (derived here from the saved per-frame rows)",
        },
        "status": ["executed"],
        "key_values": [
            {"label": f"{single['profile']} open loop -> residual", "value": [single["mean_open_loop_rms_nm"], single["mean_residual_rms_nm"]], "display": f"{fmt(single['mean_open_loop_rms_nm'], 4)} -> {fmt(single['mean_residual_rms_nm'], 4)}", "unit": "nm", "source": locator(s, base + "eso_elt_closed_loop.csv", f"rows profile == {single['profile']}, frame >= 50; arithmetic means")},
            {"label": f"{ten['profile']} open loop -> residual", "value": [ten["mean_open_loop_rms_nm"], ten["mean_residual_rms_nm"]], "display": f"{fmt(ten['mean_open_loop_rms_nm'], 4)} -> {fmt(ten['mean_residual_rms_nm'], 4)}", "unit": "nm", "source": locator(s, base + "eso_elt_closed_loop.csv", f"rows profile == {ten['profile']}, frame >= 50; arithmetic means")},
        ],
        "tables": [
            {"id": "r3-loop", "title": "Closed-loop comparison, frames 50-149 (derived means of saved rows)", "columns": [
                {"key": "profile", "label": "Profile", "unit": ""}, {"key": "atmosphere", "label": "Atmosphere", "unit": ""},
                {"key": "realizations", "label": "Realizations", "unit": ""},
                {"key": "mean_open_loop_rms_nm", "label": "Mean open-loop RMS", "unit": "nm", "digits": 4},
                {"key": "mean_residual_rms_nm", "label": "Mean residual RMS", "unit": "nm", "digits": 4},
                {"key": "realization_sd_of_mean_residual_nm", "label": "SD of realization means", "unit": "nm", "digits": 2}],
             "rows": summary, "source": locator(s, base + "eso_elt_closed_loop.csv", "all 2400 rows; means over frame >= 50"), "uncertainty": "sample SD (n = 8)"},
            {"id": "r3-profile", "title": "Ten-layer profile (published and normalized Cn2 fractions)", "columns": [
                {"key": "altitude_m", "label": "Altitude", "unit": "m"}, {"key": "published_cn2_fraction", "label": "Published fraction", "unit": "", "digits": 3},
                {"key": "cn2_fraction", "label": "Normalized fraction", "unit": "", "digits": 4}, {"key": "wind_speed_m_per_s", "label": "Wind speed", "unit": "m/s", "digits": 1},
                {"key": "layer_r0_500nm_m", "label": "Layer r0 at 500 nm", "unit": "m", "digits": 3}],
             "rows": profile_rows, "source": locator(s, base + "eso_elt_turbulence_profile.csv", "all rows")},
            {"id": "r3-structure", "title": "Phase structure function against von Karman (256 screens)", "columns": [
                {"key": "separation_m", "label": "Separation", "unit": "m", "digits": 4}, {"key": "measured_rad2", "label": "Measured", "unit": "rad^2", "digits": 4},
                {"key": "von_karman_rad2", "label": "von Karman", "unit": "rad^2", "digits": 4}, {"key": "ratio", "label": "Ratio", "unit": "", "digits": 4}],
             "rows": structure_rows, "source": locator(s, base + "eso_elt_structure_function.csv", "all rows")},
        ],
        "charts": [
            {
                "id": "r3-loop-chart",
                "type": "line",
                "title": "Residual RMS per frame, mean over 8 realizations",
                "x": {"label": "Frame", "unit": "", "scale": "linear"},
                "y": {"label": "Residual RMS", "unit": "nm", "scale": "linear"},
                "series": per_frame_series,
                "shade_x": [[0, 50, "excluded from the window"]],
                "derived_from": "eso_elt_closed_loop.csv",
                "transformation": "per-frame arithmetic mean of the saved residual_rms_nm over the 8 realizations; no smoothing",
            }
        ],
        "figures": [figure],
        "takeaway": (
            f"The ten-layer structure function agrees with von Karman to a ratio of {fmt(min(ratios[1:]), 3)}-{fmt(max(ratios[1:]), 3)} beyond the first "
            f"separation ({fmt(ratios[0], 3)} at one pixel). In the noise-free 2 m loop the ten-layer residual is {fmt(ten['mean_residual_rms_nm'], 1)} nm "
            f"against {fmt(single['mean_residual_rms_nm'], 1)} nm for one 10 m/s layer, but the realization scatter is "
            f"{fmt(ten['realization_sd_of_mean_residual_nm'], 0)} and {fmt(single['realization_sd_of_mean_residual_nm'], 0)} nm and the two profiles do not share r0, "
            "so the difference is not a controlled layering effect."
        ),
        "limitations": [
            "Noise-free loops (controller.include_noise false) on a 7x7-lenslet 2 m system; this is not the explorer's detector-level profile.",
            "The two profiles differ in r0 (0.1263 m against 0.13 m at 500 nm) as well as in layering.",
            "Layer altitudes are recorded but no anisoplanatism, tomography or LGS cone effect is simulated; the profiles list J/H/K wavelengths but this evidence has no science images.",
        ],
        "evidence_notes": [
            "The closed-loop means are derived here from the saved per-frame CSV rows; the CSV stores no summary scalar.",
        ],
        "producer": {"commit": "absent from the files (added to the repository in de58ab7, 2026-10-14)", "host": "absent"},
        "licence": "Repository-generated data and figure (MIT). ESO E-ELT DRM layer parameters are transcribed with citation (DATA_LICENSES.md: ESO terms; Le Louarn et al. 2004).",
        "licence_source": s.lines("DATA_LICENSES.md", 26, 26, "ESO E-ELT Design Reference Mission"),
        "downloads": [
            w.download(base + "eso_elt_closed_loop.csv", label="Closed-loop per-frame rows (CSV)", media_type="text/csv"),
            w.download(base + "eso_elt_turbulence_profile.csv", label="Layer profile (CSV)", media_type="text/csv"),
            w.download(base + "eso_elt_structure_function.csv", label="Structure function (CSV)", media_type="text/csv"),
        ],
        "sources": [locator(s, base + name, "whole file") for name in ("eso_elt_closed_loop.csv", "eso_elt_turbulence_profile.csv", "eso_elt_structure_function.csv")],
        "selector": {"kind": "recorded_series", "options": [row["profile"] for row in summary], "note": "selects a recorded profile's series; nothing is interpolated"},
        "_lookup": lookup,
    }


# ---------------------------------------------------------------------------
# R4 - detector path, 12 m progression and the negative noise-law result


def _scan_rows(record: Dict[str, Any], version: str) -> List[Dict[str, Any]]:
    rows = []
    for label, item in record["summary"].items():
        magnitude = float(label.split()[-1][1:])
        rows.append(
            {
                "version": version,
                "label": label,
                "magnitude_ab": magnitude,
                "runs": item["runs"],
                "residual_nm": item["post_update_rms_mean_m"] * 1e9,
                "residual_seed_sd_nm": item["post_update_rms_seed_std_m"] * 1e9,
                "peak_strehl_2p2um": item["peak_strehl_mean"],
                "peak_strehl_seed_sd": item["peak_strehl_seed_std"],
                "valid_fraction": item["valid_fraction_mean"],
                "lost_lock_runs": item["lost_lock_runs"],
            }
        )
    return rows


def group_r4(w: Writer) -> Dict[str, Any]:
    s = w.sources
    e = "docs/refactor/detector_level_evidence/"
    v1 = s.json(e + "det09_e3_magnitude_scan_12m.json")
    v2 = s.json(e + "det09_e3_magnitude_scan_12m_v2.json")
    v3 = s.json(e + "det09_e3_magnitude_scan_12m_v3_review.json")
    e4 = s.json(e + "det09_e4_camera_comparison_12m_v3_review.json")
    e1 = s.json(e + "det07_e1_centroid_noise_review.json")
    e2 = s.json(e + "det09_e2_noise_propagation_12m_review.json")
    e2_2m = s.json(e + "det09_e2_noise_propagation_review.json")
    law = s.json("docs/research/detector_noise_law/results.json")
    rows = _scan_rows(v1, "@1") + _scan_rows(v2, "@2") + _scan_rows(v3, "@3 (review rerun)")
    m12 = [run for run in v3["runs"] if run["label"] == "m12"]
    m12_note = {
        "runs": len(m12),
        "valid_fraction": [run["valid_measurement_fraction"] for run in m12],
        "usable_fraction": [run["reconstruction_usable_fraction"] for run in m12],
        "recovery_decayed_frames": [run.get("recovery", {}).get("decayed_frames") for run in m12],
        "post_equals_open_loop": [run["post_update_rms_m"] == run["open_loop_rms_m"] for run in m12],
        "lost_lock_flags": [run["lost_lock"] for run in m12],
    }
    camera_rows = []
    for label, item in e4["summary"].items():
        camera, magnitude = label.split()
        camera_rows.append(
            {
                "camera": camera,
                "magnitude_ab": float(magnitude[1:]),
                "runs": item["runs"],
                "residual_nm": item["post_update_rms_mean_m"] * 1e9,
                "residual_seed_sd_nm": item["post_update_rms_seed_std_m"] * 1e9,
                "peak_strehl_2p2um": item["peak_strehl_mean"],
                "valid_fraction": item["valid_fraction_mean"],
                "lost_lock_runs": item["lost_lock_runs"],
            }
        )
    cmos10 = next(row for row in camera_rows if row["camera"] == "synthetic_cmos@1" and row["magnitude_ab"] == 10.0)
    e1_rows = [
        {"camera": item["camera"], "variant": item["variant"], "max_abs_ratio_error_supported": item["max_abs_ratio_error_supported"],
         "max_abs_ratio_error_supported_null_reason": (
             None if item["max_abs_ratio_error_supported"] is not None
             else "no flux point inside the model's supported domain (processing outside the model)"),
         "supported_points": sum(1 for point in item["points"] if point["model_supported"]), "points": len(item["points"])}
        for item in e1["results"]
    ]
    supported_errors = [row["max_abs_ratio_error_supported"] for row in e1_rows if row["max_abs_ratio_error_supported"] is not None]
    unsupported_variants = sorted({row["variant"] for row in e1_rows if row["max_abs_ratio_error_supported"] is None})
    supported_variants = sorted({row["variant"] for row in e1_rows if row["max_abs_ratio_error_supported"] is not None})
    e2_rows = []
    for name, record in (("2 m", e2_2m), ("12 m", e2)):
        for item in record["results"]:
            ratio = item["slope_variance_ratio_measured_over_predicted"]
            e2_rows.append({"scale": name, "profile": item.get("profile"), "trials": item.get("trials"), "slope_variance_ratio_mean": ratio["mean"], "slope_variance_ratio_min": ratio["min"], "slope_variance_ratio_max": ratio["max"], "expected_relative_se_per_entry": ratio["expected_relative_se_per_entry"]})
    # The plotted dV is the reanalysis's dv_mean_nm2: the seed mean of each
    # run's noise_variance_m2 (the paired residual-map difference), not the
    # difference of the two arms' mean squares (external review ER-F01).  Bind that
    # identity to the saved per-run records before exporting a single point.
    isolation = {"2m": s.json(e + "det09_noise_isolation_2m.json"), "12m_v3": s.json(e + "det09_noise_isolation_12m_v3.json")}
    definition_check = {}
    for key, record in isolation.items():
        for label, item in law["analysis"][key]["per_magnitude"].items():
            runs = [run for run in record["runs"] if run["label"] == label and run["root_seed"] in item["seeds"]]
            if sorted(run["root_seed"] for run in runs) != sorted(item["seeds"]):
                raise ResearchExportError(f"R4 {key} {label}: the isolation record lacks the reanalysis seeds")
            paired = statistics.fmean(run["noise_variance_m2"] for run in runs) * 1e18
            arm_difference = statistics.fmean(run["mean_square_difference_m2"] for run in runs) * 1e18
            if not math.isclose(paired, item["dv_mean_nm2"], rel_tol=1e-12):
                raise ResearchExportError(f"R4 {key} {label}: dv_mean_nm2 is not the seed mean of noise_variance_m2")
            definition_check[f"{key} {label}"] = {
                "plotted_dv_mean_nm2": item["dv_mean_nm2"],
                "seed_mean_noise_variance_nm2": paired,
                "seed_mean_arm_mean_square_difference_nm2": arm_difference,
                "seeds": item["seeds"],
            }
    dv_example = definition_check["2m m5"]
    fits = {}
    noise_series = []
    for key, scale in (("2m", "2 m"), ("12m_v3", "12 m")):
        analysis = law["analysis"][key]
        fit = analysis["historical_fit"]
        fits[scale] = {
            "slope": fit["slope"],
            "slope_se_unscaled": fit["slope_se_unscaled"],
            "slope_se_scaled": fit["slope_se_scaled"],
            "chi2_dof": fit["chi2_dof"],
            "z_from_minus_one_unscaled": fit["se_from_minus_one_unscaled"],
            "verdict_unscaled_two_se": fit["verdict_unscaled_two_se"],
            "verdict_scaled_two_se": fit["verdict_scaled_two_se"],
            "magnitudes": fit["labels"],
        }
        points = []
        for label, item in analysis["per_magnitude"].items():
            points.append([item["ne_e"], item["dv_mean_nm2"], item["dv_seed_se_nm2"]])
        noise_series.append({"label": f"{scale}: dV (paired residual-map difference)", "points": points, "error": "SE of the seed mean"})
    dip = law["analysis"]["12m_v3"]["ratio_changes"]["adjacent"]["m10_vs_m9"]["mean_ratio_change_percent"]
    drift = law["analysis"]["2m"]["ratio_changes"]["gate_quiet_end_to_end_per_seed_paired"]["mean_percent"]
    m11 = next(row for row in rows if row["version"].startswith("@3") and row["magnitude_ab"] == 11.0)
    lim18 = s.lines("docs/current_limitations.md", 515, 528, "6.7 %")
    # Definitions bound to their sources (external review ER-F01, ER-F03).
    estimand_doc = phrase_lines(s, "docs/research/detector_noise_law/report.md", "| `noise_variance_m2` (ΔV) |", 1)
    estimand_code = _first_after(s, "src/shwfs_ao/experiments/detector_level.py", "def _paired_noise_core(", "    delta = on - off", 3)
    recorder_code = phrase_lines(s, "src/shwfs_ao/experiments/detector_level.py", 'requested_fields = frozenset({"post_update_residual_opd_m"})')
    # Which code the 12 m reruns ran (round-5 review, R5-F01): their
    # source-change digest is that of the 663df161 -> 573f875 diff, so they
    # ran on 573f875's src and scripts.  The 2 m isolation record's digest
    # matches no commit after 663df161 and stays unknown.
    rerun_digest = s.source_change_digest(PRODUCER_12M, PRODUCER_12M_RERUN)
    for name in ("det09_e3_magnitude_scan_12m_v3_review.json", "det09_e4_camera_comparison_12m_v3_review.json", "det09_noise_isolation_12m_v3.json"):
        code = s.json(e + name).get("code_identity", {})
        if (code.get("git_head"), code.get("source_changes_sha256")) != (PRODUCER_12M, rerun_digest):
            raise ResearchExportError(f"R4: {name} no longer has the source identity of commit {PRODUCER_12M_RERUN[:8]}")
    two_m = s.json(e + "det09_noise_isolation_2m.json")["code_identity"]
    later = subprocess.run(["git", "rev-list", f"{PRODUCER_12M}..{s.tree_sha}"], cwd=identity.REPO_ROOT, capture_output=True, text=True, check=True).stdout.split()
    if two_m["git_head"] != PRODUCER_12M or two_m["source_changes_sha256"] in {s.source_change_digest(PRODUCER_12M, commit) for commit in later} | {identity.sha256_bytes(b"")}:
        raise ResearchExportError("R4: the 2 m isolation record's source identity now matches a commit; revisit the unknown-identity statement")
    for v in (v1, v2):
        if v.get("code_identity") is not None:
            raise ResearchExportError("R4: an @1/@2 scan record now carries a code identity; revisit the unknown-identity statement")
    rerun_config = s.historical_lines(PRODUCER_12M_RERUN, "src/shwfs_ao/experiments/detector_level.py", "        LongExposureConfig(", 3, after="def science_run(")
    rerun_default = s.historical_lines(PRODUCER_12M_RERUN, "src/shwfs_ao/science/long_exposure.py", 'residual: Literal["pre_update", "post_update"] = "pre_update"')
    rerun_rms = s.historical_lines(PRODUCER_12M_RERUN, "src/shwfs_ao/experiments/detector_level.py", "    post = np.asarray(history.post_update_residual_opd_rms_m, dtype=float)[window]", after="def science_run(")
    rerun_estimator = s.historical_lines(PRODUCER_12M_RERUN, "src/shwfs_ao/experiments/detector_level.py", "    delta = on - off", 3, after="def paired_noise_run(")
    rerun_identity = s.historical_lines(PRODUCER_12M_RERUN, "scripts/run_detector_level_evidence.py", '["git", "diff", "HEAD", "--", "src", "scripts"]')
    return {
        "id": "R4",
        "title": "Physical detector path, 12 m control-policy progression and a negative noise result",
        "question": "Does the physical camera model hold, what limits the 12 m faint end, and does detector noise follow an inverse-photon law?",
        "context": {
            "model_family": "native time-domain SCAO with the physical detector path",
            "aperture_m": "12 m scans (det_emccd_12m_medium_derived@1/@2/@3); 2 m noise isolation (det_emccd_2m_synthetic@1)",
            "wfs_wavelength_m": 7.0e-7,
            "science_wavelength_m": 2.2e-6,
            "noise_policy": "detector noise on; the isolation study pairs each noise-on loop with its noiseless operating twin",
            "residual_rms": "scan and camera records: mean over frames 100-399 of the per-frame pupil RMS of the post-update residual (post_update_rms_m)",
            "science_image": (
                "2.2 um peak Strehl of the scan's long-exposure science accumulator: the equal-weight average of instantaneous "
                "frame-start images over frames 100-399."
            ),
            "science_residual_of_these_records": (
                "@3 review scan and camera comparison: pre-update. They name 663df161 with a source-change digest equal to that "
                "of the 663df161 -> 573f875 diff of src and scripts (no untracked files), so they ran on the code of commit "
                "573f875, whose science_run builds the accumulator without a residual argument and so uses the default pre-update "
                "residual. @1 and @2 scans: unknown (their records carry no code identity)."
            ),
            "isolated_noise_variance": (
                "dV = noise_variance_m2 of each paired run: for every frame from burn-in on, the noise-on loop's post-update "
                "residual map minus that of its noiseless operating twin, piston removed over the pupil; dV is the mean over "
                "those frames of the pupil mean of the squared difference. Points are seed means (dv_mean_nm2). This is not the "
                "difference of the two arms' mean squares (mean_square_difference_m2), and a paired difference of two nonlinear "
                "closed loops need not form an additive noise budget. The 12 m record ran on the code of commit 573f875, which "
                "computes this estimator. The 2 m record's source digest matches no commit, so its estimator is documented, "
                "not reproduced: the saved-data reanalysis describes it and re-derives the record's quoted aggregates, but "
                "cannot recompute dV because no residual maps were saved."
            ),
            "window": "12 m scans: 400 frames, burn-in 100; isolation: 2 m 200/50, 12 m 400/100",
            "realizations": "scans: 5 seeds per magnitude; camera comparison: 3; isolation: 8 (2 m) and 5 (12 m)",
            "uncertainty": "scan *_seed_std are sample SDs over seeds; isolation points carry the SE of the seed mean; fit slope errors are unscaled weighted-least-squares errors (scaled values also shown)",
        },
        "status": ["executed", "failed_hypothesis", "derived_analysis"],
        "key_values": [
            {"label": "@3 review, m_AB 11: residual / 2.2 um peak Strehl", "value": [m11["residual_nm"], m11["peak_strehl_2p2um"]], "display": f"{fmt(m11['residual_nm'], 4)} nm / {fmt(m11['peak_strehl_2p2um'], 6)}", "unit": "", "source": locator(s, e + "det09_e3_magnitude_scan_12m_v3_review.json", "summary.m11")},
            {"label": "@3 review, m_AB 12: valid measurement fraction", "value": m12_note["valid_fraction"], "display": ", ".join(fmt(v, 1) for v in m12_note["valid_fraction"]), "unit": "", "source": locator(s, e + "det09_e3_magnitude_scan_12m_v3_review.json", "runs[label == m12].valid_measurement_fraction")},
            {"label": "Reviewed CMOS m_AB 10: residual / Strehl", "value": [cmos10["residual_nm"], cmos10["peak_strehl_2p2um"]], "display": f"{fmt(cmos10['residual_nm'], 4)} nm / {fmt(cmos10['peak_strehl_2p2um'], 6)}", "unit": "", "source": locator(s, e + "det09_e4_camera_comparison_12m_v3_review.json", "summary['synthetic_cmos@1 m10']")},
            {"label": "2 m noise-law slope (unscaled SE)", "value": [fits["2 m"]["slope"], fits["2 m"]["slope_se_unscaled"]], "display": f"{fmt(fits['2 m']['slope'], 6)} +/- {fmt(fits['2 m']['slope_se_unscaled'], 6)} ({fits['2 m']['verdict_unscaled_two_se']})", "unit": "", "source": locator(s, "docs/research/detector_noise_law/results.json", "analysis['2m'].historical_fit")},
            {"label": "12 m noise-law slope (unscaled SE)", "value": [fits["12 m"]["slope"], fits["12 m"]["slope_se_unscaled"]], "display": f"{fmt(fits['12 m']['slope'], 6)} +/- {fmt(fits['12 m']['slope_se_unscaled'], 6)} ({fits['12 m']['verdict_unscaled_two_se']}; chi2/dof {fmt(fits['12 m']['chi2_dof'], 2)})", "unit": "", "source": locator(s, "docs/research/detector_noise_law/results.json", "analysis['12m_v3'].historical_fit")},
        ],
        "tables": [
            {"id": "r4-scan", "title": "12 m magnitude scans by profile revision (versions kept distinct)", "columns": [
                {"key": "version", "label": "Profile revision", "unit": ""}, {"key": "magnitude_ab", "label": "m_AB", "unit": ""}, {"key": "runs", "label": "Seeds", "unit": ""},
                {"key": "residual_nm", "label": "Residual (mean)", "unit": "nm", "digits": 1}, {"key": "residual_seed_sd_nm", "label": "Seed SD", "unit": "nm", "digits": 1},
                {"key": "peak_strehl_2p2um", "label": "2.2 um peak Strehl", "unit": "", "digits": 4}, {"key": "valid_fraction", "label": "Valid fraction", "unit": "", "digits": 4},
                {"key": "lost_lock_runs", "label": "lost_lock_runs (heuristic)", "unit": ""}],
             "rows": rows, "source": [locator(s, e + name, "summary") for name in ("det09_e3_magnitude_scan_12m.json", "det09_e3_magnitude_scan_12m_v2.json", "det09_e3_magnitude_scan_12m_v3_review.json")],
             "uncertainty": "sample SD over seeds (n = 5)"},
            {"id": "r4-camera", "title": "Camera comparison at 12 m (@3, review rerun)", "columns": [
                {"key": "camera", "label": "Camera", "unit": ""}, {"key": "magnitude_ab", "label": "m_AB", "unit": ""}, {"key": "runs", "label": "Seeds", "unit": ""},
                {"key": "residual_nm", "label": "Residual (mean)", "unit": "nm", "digits": 1}, {"key": "residual_seed_sd_nm", "label": "Seed SD", "unit": "nm", "digits": 1},
                {"key": "peak_strehl_2p2um", "label": "2.2 um peak Strehl", "unit": "", "digits": 4}, {"key": "valid_fraction", "label": "Valid fraction", "unit": "", "digits": 4}],
             "rows": camera_rows, "source": locator(s, e + "det09_e4_camera_comparison_12m_v3_review.json", "summary"), "uncertainty": "sample SD over seeds (n = 3)"},
            {"id": "r4-noise-fit", "title": "Predeclared inverse-photon test of the isolated detector noise", "columns": [
                {"key": "scale", "label": "Scale", "unit": ""}, {"key": "slope", "label": "Fitted slope", "unit": "", "digits": 6}, {"key": "slope_se_unscaled", "label": "Unscaled SE", "unit": "", "digits": 6},
                {"key": "slope_se_scaled", "label": "Scaled SE", "unit": "", "digits": 6}, {"key": "chi2_dof", "label": "chi2/dof", "unit": "", "digits": 3},
                {"key": "verdict_unscaled_two_se", "label": "Verdict (unscaled, 2 SE)", "unit": ""}, {"key": "verdict_scaled_two_se", "label": "Verdict (scaled, 2 SE)", "unit": ""}],
             "rows": [{"scale": scale, **fit} for scale, fit in fits.items()], "source": locator(s, "docs/research/detector_noise_law/results.json", "analysis[*].historical_fit"),
             "uncertainty": "fit standard errors; the predeclared test uses the unscaled errors"},
            {"id": "r4-e1", "title": "Monte-Carlo centroid noise against the model (supported domain)", "columns": [
                {"key": "camera", "label": "Camera", "unit": ""}, {"key": "variant", "label": "Variant", "unit": ""},
                {"key": "max_abs_ratio_error_supported", "label": "Max |measured/model - 1| (supported)", "unit": "", "digits": 4},
                {"key": "supported_points", "label": "Supported flux points", "unit": ""}, {"key": "points", "label": "Flux points", "unit": ""}],
             "rows": e1_rows, "source": locator(s, e + "det07_e1_centroid_noise_review.json", "results[*]"), "uncertainty": "10^4 trials per point"},
            {"id": "r4-e2", "title": "Open-loop propagation of slope noise (measured / predicted variance)", "columns": [
                {"key": "scale", "label": "Scale", "unit": ""}, {"key": "trials", "label": "Trials", "unit": ""},
                {"key": "slope_variance_ratio_mean", "label": "Mean ratio", "unit": "", "digits": 4}, {"key": "slope_variance_ratio_min", "label": "Min", "unit": "", "digits": 4},
                {"key": "slope_variance_ratio_max", "label": "Max", "unit": "", "digits": 4}, {"key": "expected_relative_se_per_entry", "label": "Expected relative SE", "unit": "", "digits": 4}],
             "rows": e2_rows, "source": [locator(s, e + "det09_e2_noise_propagation_review.json", "results[*]"), locator(s, e + "det09_e2_noise_propagation_12m_review.json", "results[*]")]},
        ],
        "charts": [
            {
                "id": "r4-scan-chart",
                "type": "line",
                "title": "12 m residual against guide magnitude, by recorded profile revision",
                "x": {"label": "m_AB", "unit": "", "scale": "linear"},
                "y": {"label": "Post-update residual RMS", "unit": "nm", "scale": "log"},
                "series": [
                    {"label": version, "points": [[row["magnitude_ab"], row["residual_nm"], row["residual_seed_sd_nm"]] for row in rows if row["version"] == version], "error": "sample SD over seeds"}
                    for version in ("@1", "@2", "@3 (review rerun)")
                ],
                "annotations": [{"x": 12.0, "text": "m_AB 12: zero valid measurements; the residual equals open loop"}],
                "derived_from": "r4-scan",
                "transformation": "plotted directly from the recorded summary rows",
            },
            {
                "id": "r4-noise-chart",
                "type": "line",
                "title": "Paired residual-map noise variance dV against detected electrons",
                "x": {"label": "Detected electrons per full sub-aperture", "unit": "e-", "scale": "log"},
                "y": {"label": "dV (mean square of the paired map difference)", "unit": "nm^2", "scale": "log"},
                "series": noise_series,
                "derived_from": "docs/research/detector_noise_law/results.json analysis[*].per_magnitude",
                "transformation": (
                    "seed means dv_mean_nm2 (= seed mean of each run's noise_variance_m2 x 1e18, checked against the isolation records) "
                    "and their SEs exactly as saved by the saved-data reanalysis; no fit line is drawn"
                ),
            },
        ],
        "figures": [],
        "takeaway": (
            f"For {' and '.join(supported_variants)} pixel processing the camera model's centroid noise agrees with Monte-Carlo to within "
            f"{fmt(max(supported_errors) * 100.0, 1)} % at every supported flux point; the {' and '.join(unsupported_variants)} variants have no point "
            f"inside the model's domain. Open-loop slope-noise propagation agrees with prediction (mean measured/predicted variance "
            f"{fmt(min(row['slope_variance_ratio_mean'] for row in e2_rows), 3)}-{fmt(max(row['slope_variance_ratio_mean'] for row in e2_rows), 3)}). "
            f"At 12 m the faint end is set by measurement validity and reconstruction policy: the @3 review "
            f"rerun reaches {fmt(m11['residual_nm'], 1)} nm and Strehl {fmt(m11['peak_strehl_2p2um'], 3)} at m_AB 11, while at m_AB 12 no "
            "measurement is valid and the residual equals open loop, even though the lost_lock_runs field reads 0. The predeclared "
            f"inverse-photon test fails at 12 m (slope {fmt(fits['12 m']['slope'], 4)} +/- {fmt(fits['12 m']['slope_se_unscaled'], 4)}, "
            f"chi2/dof {fmt(fits['12 m']['chi2_dof'], 2)}) and passes at 2 m ({fmt(fits['2 m']['slope'], 4)} +/- {fmt(fits['2 m']['slope_se_unscaled'], 4)}); "
            f"the {fmt(abs(dip), 1)} % dip at m_AB 10 and the 2 m drift remain unexplained."
        ),
        "limitations": [
            "Profile revisions @1, @2 and @3 differ in control policy and are post-hoc revisions; their rows are not one experiment.",
            "lost_lock only compares the final post-update residual with the final open-loop residual; it is not a lock classifier, and a run with zero valid measurements reads as not lost.",
            "The noise-law verdict depends on using the unscaled fit errors (scaled errors would pass at 12 m); the test was predeclared with unscaled errors. S4 and LIM-18 are not closed.",
            "Synthetic engineering camera presets without datasheets; this is not measured instrument performance.",
        ],
        "evidence_notes": [
            (
                f"dV is not a difference of variances: for 2 m m_AB 5 (seeds {dv_example['seeds'][0]}-{dv_example['seeds'][-1]}) the plotted "
                f"dV is {fmt(dv_example['plotted_dv_mean_nm2'], 4)} nm^2, while the seed mean of the arms' mean-square difference "
                f"(mean_square_difference_m2) is {fmt(dv_example['seed_mean_arm_mean_square_difference_nm2'], 4)} nm^2. The latter is not plotted."
            ),
            "The 12 m isolation record has the source identity of commit 573f875 (its digest equals the 663df161 -> 573f875 diff), whose paired_noise_run computes noise_variance_m2 as defined here. The 2 m record names 663df161 with uncommitted changes that match no commit; its estimator is the one the saved-data reanalysis documents (report.md, section 2) and later committed as detector_level._paired_noise_core. The reanalysis re-derives the record's quoted aggregates but cannot recompute dV (no residual maps were saved), so the 2 m estimator is documented, not reproduced.",
            "The paired-noise fits are not stored in the run records (their summary is empty); they are read from the saved-data reanalysis docs/research/detector_noise_law/results.json, whose recorded script path predates its rename.",
            "The README's 279 nm CMOS figure is a rounding of an earlier (non-review) record's 278.46 nm; the reviewed value is shown here.",
            "E3/E4 records carry no profile-id field; the revision comes from each record's command and the status document.",
        ],
        "m12_detail": m12_note,
        "limitation_locators": [lim18, s.lines("docs/current_limitations.md", 120, 125, "LIM-16"), s.lines("docs/roadmap.md", 60, 60, "S4")],
        "producer": {
            "commit": "@3 review scan, camera comparison and 12 m isolation records: 663df161 plus uncommitted changes identical to commit 573f875 (src, scripts); 2 m isolation record: 663df161 plus unidentified uncommitted changes; @1/@2 scan records: no code identity",
            "host": "machine arm64 only",
        },
        "licence": "Repository-authored records (MIT). Camera presets are synthetic engineering values.",
        "downloads": [
            w.download(e + "det09_e3_magnitude_scan_12m_v3_review.json", label="E3 @3 review scan record"),
            w.download(e + "det09_e3_magnitude_scan_12m_v2.json", label="E3 @2 scan record"),
            w.download(e + "det09_e3_magnitude_scan_12m.json", label="E3 @1 scan record"),
            w.download(e + "det09_e4_camera_comparison_12m_v3_review.json", label="E4 camera comparison record"),
            w.download(e + "det09_noise_isolation_12m_v3.json", label="12 m noise isolation record"),
            w.download(e + "det09_noise_isolation_2m.json", label="2 m noise isolation record"),
            w.download("docs/research/detector_noise_law/results.json", label="Saved-data noise-law reanalysis"),
        ],
        "sources": [locator(s, e + name, "whole file") for name in (
            "det09_e3_magnitude_scan_12m.json", "det09_e3_magnitude_scan_12m_v2.json", "det09_e3_magnitude_scan_12m_v3_review.json",
            "det09_e4_camera_comparison_12m_v3_review.json", "det07_e1_centroid_noise_review.json", "det09_e2_noise_propagation_review.json",
            "det09_e2_noise_propagation_12m_review.json", "det09_noise_isolation_2m.json", "det09_noise_isolation_12m_v3.json")],
        "context_sources": [estimand_doc, estimand_code, recorder_code, rerun_identity, rerun_config, rerun_default, rerun_rms, rerun_estimator],
        "selector": {"kind": "recorded_versions", "options": ["@1", "@2", "@3 (review rerun)"], "note": "highlights one recorded profile revision; no row is interpolated"},
        "_values": {
            "dip_percent": dip,
            "drift_percent": drift,
            "dv_definition": definition_check,
            "rerun_source_identity": {"recorded_head": PRODUCER_12M, "equivalent_commit": PRODUCER_12M_RERUN, "source_change_sha256": rerun_digest, "rule": "sha256 of git diff <recorded_head> <equivalent_commit> -- src scripts"},
        },
    }


# ---------------------------------------------------------------------------
# R5 - 42 m SCAO


def group_r5(w: Writer) -> Dict[str, Any]:
    s = w.sources
    e = "docs/refactor/detector_level_evidence/"
    s1 = s.json(e + "det09_e5_42m_noise_on_current_2312502.json")
    run = s1["runs"][0]
    seeds = []
    for seed in range(2, 12):
        record = s.json(e + f"det09_s2_42m_seed{seed}.json")
        item = record["runs"][0]
        seeds.append(
            {
                "root_seed": item["root_seed"],
                "open_loop_rms_nm": item["open_loop_rms_m"] * 1e9,
                "residual_nm": item["post_update_rms_m"] * 1e9,
                "peak_strehl_2p2um": item["science"][0]["peak_strehl"],
                "min_valid_fraction": item["min_valid_measurement_fraction"],
                "per_frame_s": item["per_frame_s"],
                "process_peak_rss_gib": item["process_peak_rss_bytes"] / 2**30,
            }
        )
    residual_mean, residual_sd = mean_sd([row["residual_nm"] for row in seeds])
    strehl_mean, strehl_sd = mean_sd([row["peak_strehl_2p2um"] for row in seeds])
    manifest = s.json("docs/refactor/eso_scao_evidence/reference_tier_v2_manifest.json")
    erratum = s.lines("docs/refactor/eso_scao_evidence/v2_manifest_atmosphere_record_erratum.txt", 1, 20, "reference_tier_v2")
    s1_row = {
        "record": "S1 replay (2312502)",
        "root_seed": run["root_seed"],
        "open_loop_rms_nm": run["open_loop_rms_m"] * 1e9,
        "residual_nm": run["post_update_rms_m"] * 1e9,
        "peak_strehl_2p2um": run["science"][0]["peak_strehl"],
        "per_frame_s": run["per_frame_s"],
        "process_peak_rss_gib": run["process_peak_rss_bytes"] / 2**30,
    }
    s1_window = [run["burn_in_frames"], run["n_steps"]]
    s2_windows = sorted({(s.json(e + f"det09_s2_42m_seed{seed}.json")["runs"][0]["burn_in_frames"], s.json(e + f"det09_s2_42m_seed{seed}.json")["runs"][0]["n_steps"]) for seed in range(2, 12)})
    if len(s2_windows) != 1:
        raise ResearchExportError("S2 runs do not share one window")
    selection = manifest["science"]["selection"]
    # Science-image timing of S1/S2, bound to their clean producer (external review
    # ER-F03): science_run builds the accumulator without a residual
    # argument, whose default is the pre-update residual; the RMS summary is
    # the post-update residual over the same frames.
    for record in [s1] + [s.json(e + f"det09_s2_42m_seed{seed}.json") for seed in range(2, 12)]:
        code = record.get("code_identity", {})
        if code.get("git_head") != PRODUCER_42M or code.get("source_changes_sha256") != identity.sha256_bytes(b""):
            raise ResearchExportError("R5: an S1/S2 record does not name the clean producer 23125024")
    # S1 ran the committed e5 command; S2 ran an unretained driver (round-5
    # review, R5-F03) that the status document describes as the same runner
    # machinery, so the S2 science timing is documented, not code-verified.
    if not any(str(item).endswith("scripts/run_detector_level_evidence.py") for item in s1["argv"]):
        raise ResearchExportError("R5: the S1 record no longer names the committed evidence script")
    s2_drivers = {s.json(e + f"det09_s2_42m_seed{seed}.json")["argv"][0] for seed in range(2, 12)}
    if s2_drivers != {"outputs/large_experiments/2026-10-18/s2/run_one_seed.py"}:
        raise ResearchExportError(f"R5: unexpected S2 drivers {sorted(s2_drivers)}")
    s2_driver_doc = phrase_lines(s, "docs/refactor/CLEANUP_REFACTOR_STATUS.md", "| S2 | `s2/run_one_seed.py` through the same runner machinery")
    # The whole e5 call (round-6 review observation): it passes no runner, so
    # _gated_series uses its default, science_run.
    e5_call = s.historical_lines(PRODUCER_42M, "scripts/run_detector_level_evidence.py", "def e5(arguments: argparse.Namespace) -> None:", 11)
    e5_text = s._show(PRODUCER_42M, "scripts/run_detector_level_evidence.py").decode("utf-8").splitlines()[e5_call["lines"][0] - 1:e5_call["lines"][1]]
    if "    _gated_series(" not in e5_text or e5_text[-1] != "    )" or any("runner" in line for line in e5_text):
        raise ResearchExportError("R5: the bound e5 lines are not one complete _gated_series call without a runner")
    science_sources = [
        e5_call,
        s.historical_lines(PRODUCER_42M, "src/shwfs_ao/experiments/detector_level.py", "        LongExposureConfig(", 3, after="def science_run("),
        s.historical_lines(PRODUCER_42M, "src/shwfs_ao/science/long_exposure.py", 'residual: Literal["pre_update", "post_update"] = "pre_update"'),
        s.historical_lines(PRODUCER_42M, "src/shwfs_ao/experiments/detector_level.py", "    post = np.asarray(history.post_update_residual_opd_rms_m, dtype=float)[window]", after="def science_run("),
        s.historical_lines(PRODUCER_42M, "scripts/run_detector_level_evidence.py", "    run = science_run if runner is None else runner"),
        s2_driver_doc,
        locator(s, "docs/refactor/eso_scao_evidence/reference_tier_v2_manifest.json", "science.selection, timing_semantics.science_residual"),
    ]
    if (selection["residual"], manifest["timing_semantics"]["science_residual"]) != ("pre_update", "pre-update residual measured by the WFS at each selected frame"):
        raise ResearchExportError("R5: the capability manifest's science residual is not the recorded pre-update residual")
    physical = s.json("src/shwfs_ao/resources/synthetic_presets/det_ccd_42m_r3band_derived.v1.json")["config"]
    capability = s.json("src/shwfs_ao/resources/synthetic_presets/eso_drm_42m_scao_derived.v2.json")["config"]
    band = physical["detector_physics"]["bandpass"]
    noiseless = {
        "profile": manifest["profile"],
        "open_loop_window": f"all {manifest['n_steps']} frames (burn-in included)",
        "residual_window": f"frames {selection['first_frame']}-{selection['last_frame']} ({selection['sample_count']} samples)",
        "open_loop_rms_nm": manifest["loop"]["mean_open_loop_rms_nm"],
        "residual_nm": manifest["loop"]["mean_post_burn_in_residual_rms_nm"],
        "residual_definition": manifest["science"]["residual"],
        "peak_strehl_2p2um": manifest["science"]["metrics"][0]["peak_strehl"],
        "n_steps": manifest["n_steps"],
        "per_frame_mean_s": manifest["timings_s"]["per_frame_mean_s"],
        "process_peak_rss_gib": manifest["execution"]["process_peak_rss_bytes"] / 2**30,
        "host": f"{manifest['execution']['host']['platform']} {manifest['execution']['host']['machine']}, {manifest['execution']['host']['cpu_count']} CPUs, {manifest['execution']['host']['physical_bytes'] / 2**30:.0f} GiB",
    }
    return {
        "id": "R5",
        "title": "Large-scale 42 m SCAO: replay, realization scatter and implementation cost",
        "question": "Does the 42 m physical-camera result hold on current code, and how much does it vary between atmosphere realizations?",
        "context": {
            "model_family": "native time-domain SCAO, sparse high-order path",
            "aperture_m": 42.0,
            "profile": "det_ccd_42m_r3band_derived@1 (physical camera); separately eso_drm_42m_scao_derived@2 (noiseless capability run)",
            "science_wavelength_m": 2.2e-6,
            "noise_policy": "physical camera with detector noise (S1/S2); deterministic noiseless sensing (capability run)",
            "residual_rms": (
                f"S1/S2: mean over frames {s1_window[0]}-{s1_window[1] - 1} of the per-frame pupil RMS of the post-update residual "
                f"(post_update_rms_m); capability run: mean over frames {selection['first_frame']}-{selection['last_frame']} of the "
                "pre-update residual RMS (loop.mean_post_burn_in_residual_rms_nm)"
            ),
            "science_image": (
                f"2.2 um peak Strehl of the equal-weight average of instantaneous frame-start images of the pre-update residual over "
                f"frames {s1_window[0]}-{s1_window[1] - 1} ({s1_window[1] - s1_window[0]} samples). S1 ran the committed e5 command of the "
                "clean producer 23125024, whose science_run builds the accumulator without a residual argument, so the default "
                "pre-update residual applies. S2 ran through an unretained driver (outputs/large_experiments/2026-10-18/s2/run_one_seed.py, "
                "in no commit; the records' code identity covers only src and scripts) that the status document describes as the same "
                "runner machinery and protocol as S1: its use of the same default is documented, not code-verified. "
                f"Capability run: pre-update as its manifest records ({selection['sample_count']} samples). The adjacent RMS of S1/S2 "
                "is post-update, so RMS and Strehl use different residual samples of the same frames."
            ),
            "wfs_wavelength_m": physical["wfs_wavelength_m"],
            "wfs_band": f"physical camera {band['band_min_m'] * 1e9:.0f}-{band['band_max_m'] * 1e9:.0f} nm ({band['kind']}, {band['n_samples']} samples); capability run monochromatic {capability['wfs_wavelength_m'] * 1e9:.0f} nm",
            "window": (
                f"S1/S2: {s1_window[1]} frames, burn-in {s1_window[0]}; open-loop and residual are means over frames {s1_window[0]}-{s1_window[1] - 1}. "
                f"Capability run: open-loop mean over all {manifest['n_steps']} frames, residual over frames {selection['first_frame']}-{selection['last_frame']}"
            ),
            "realizations": "S1: the original seed replayed; S2: ten new seeds 2-11",
            "uncertainty": "S2 mean +/- sample SD over n = 10 (not a standard error or confidence interval)",
        },
        "status": ["executed"],
        "key_values": [
            {"label": "S1 open loop -> residual", "value": [s1_row["open_loop_rms_nm"], s1_row["residual_nm"]], "display": f"{fmt(s1_row['open_loop_rms_nm'], 4)} -> {fmt(s1_row['residual_nm'], 4)}", "unit": "nm", "source": locator(s, e + "det09_e5_42m_noise_on_current_2312502.json", "runs[0].open_loop_rms_m, post_update_rms_m")},
            {"label": "S1 2.2 um peak Strehl", "value": s1_row["peak_strehl_2p2um"], "display": fmt(s1_row["peak_strehl_2p2um"], 6), "unit": "", "source": locator(s, e + "det09_e5_42m_noise_on_current_2312502.json", "runs[0].science[0].peak_strehl")},
            {"label": "S2 residual, mean +/- sample SD (n = 10)", "value": [residual_mean, residual_sd], "display": f"{fmt(residual_mean, 4)} +/- {fmt(residual_sd, 4)}", "unit": "nm", "source": locator(s, e + "det09_s2_42m_seed2.json", "seed2..seed11 runs[0].post_update_rms_m; mean and sample SD computed here")},
            {"label": "S2 Strehl, mean +/- sample SD (n = 10)", "value": [strehl_mean, strehl_sd], "display": f"{fmt(strehl_mean, 6)} +/- {fmt(strehl_sd, 6)}", "unit": "", "source": locator(s, e + "det09_s2_42m_seed2.json", "seed2..seed11 runs[0].science[0].peak_strehl")},
        ],
        "tables": [
            {"id": "r5-s2", "title": "Physical-camera 42 m: S1 replay and ten S2 realizations", "columns": [
                {"key": "record", "label": "Record", "unit": ""}, {"key": "root_seed", "label": "Seed", "unit": ""},
                {"key": "open_loop_rms_nm", "label": "Open loop", "unit": "nm", "digits": 1}, {"key": "residual_nm", "label": "Residual", "unit": "nm", "digits": 3},
                {"key": "peak_strehl_2p2um", "label": "2.2 um peak Strehl", "unit": "", "digits": 6},
                {"key": "per_frame_s", "label": "Time per frame", "unit": "s", "digits": 3}, {"key": "process_peak_rss_gib", "label": "Peak RSS", "unit": "GiB", "digits": 3}],
             "rows": [s1_row] + [{"record": f"S2 seed {row['root_seed']}", **row} for row in seeds],
             "source": [locator(s, e + "det09_e5_42m_noise_on_current_2312502.json", "runs[0]")] + [locator(s, e + f"det09_s2_42m_seed{seed}.json", "runs[0]") for seed in range(2, 12)],
             "uncertainty": "per-run values; the S2 aggregate is mean +/- sample SD"},
            {"id": "r5-noiseless", "title": "Separate noiseless capability run (different profile; not a controlled noise comparison)", "columns": [
                {"key": "profile", "label": "Profile", "unit": ""}, {"key": "n_steps", "label": "Frames", "unit": ""},
                {"key": "open_loop_rms_nm", "label": "Open loop", "unit": "nm", "digits": 4}, {"key": "residual_nm", "label": "Residual", "unit": "nm", "digits": 4},
                {"key": "residual_definition", "label": "Residual sample (RMS and image)", "unit": ""}, {"key": "open_loop_window", "label": "Open-loop window", "unit": ""}, {"key": "residual_window", "label": "Residual window", "unit": ""},
                {"key": "peak_strehl_2p2um", "label": "2.2 um peak Strehl", "unit": "", "digits": 6},
                {"key": "per_frame_mean_s", "label": "Time per frame", "unit": "s", "digits": 3}, {"key": "process_peak_rss_gib", "label": "Peak RSS", "unit": "GiB", "digits": 3}, {"key": "host", "label": "Host", "unit": ""}],
             "rows": [noiseless], "source": locator(s, "docs/refactor/eso_scao_evidence/reference_tier_v2_manifest.json", "loop, science.metrics[0], timings_s, execution")},
        ],
        "charts": [
            {
                "id": "r5-scatter",
                "type": "scatter",
                "title": "42 m physical-camera realizations: residual against Strehl",
                "x": {"label": "Post-update residual RMS", "unit": "nm", "scale": "linear"},
                "y": {"label": "2.2 um peak Strehl", "unit": "", "scale": "linear"},
                "series": [
                    {"label": "S2 seeds 2-11", "points": [[row["residual_nm"], row["peak_strehl_2p2um"]] for row in seeds]},
                    {"label": "S1 replay (original seed)", "points": [[s1_row["residual_nm"], s1_row["peak_strehl_2p2um"]]]},
                ],
                "derived_from": "r5-s2",
                "transformation": "plotted directly from the recorded per-run values",
            }
        ],
        "figures": [],
        "takeaway": (
            f"Replayed in October 2026 on the code of commit 2312502, the original 42 m physical-camera run gives {fmt(s1_row['open_loop_rms_nm'], 1)} -> {fmt(s1_row['residual_nm'], 1)} nm "
            f"(frames {s1_window[0]}-{s1_window[1] - 1}) and 2.2 um Strehl {fmt(s1_row['peak_strehl_2p2um'], 3)}. Ten new realizations on the same code give {fmt(residual_mean, 2)} +/- {fmt(residual_sd, 2)} nm "
            f"and {fmt(strehl_mean, 4)} +/- {fmt(strehl_sd, 4)} (sample SD), so the single original result sits inside the realization scatter. "
            f"The sparse path runs this case at about {fmt(s1_row['per_frame_s'], 2)} s per frame and {fmt(s1_row['process_peak_rss_gib'], 2)} GiB on the recorded desktop."
        ),
        "limitations": [
            "The noiseless capability run uses a different profile (eso_drm_42m_scao_derived@2), a pre-update residual and an open-loop mean over all 2000 frames (burn-in included); its 1674.9 -> 173.2 nm is not comparable with the physical-camera 1683.2 nm and gives no controlled detector-noise effect.",
            "These are historical records produced on commit 2312502; they were not recomputed by this site's producer.",
            "The 4 s reference run repeats the fastest layers' periodic atmosphere bands; realizations are not fully independent long exposures.",
            "Stored summaries only: there is no recoverable 42 m movie, live scale slider or measured observatory performance.",
            "Peak RSS is a process-lifetime high-water mark (ru_maxrss); the host is recorded only as arm64 in the run records.",
        ],
        "evidence_notes": [
            "The capability manifest's atmosphere block records max_travel_m 0.0 and periodic_band_repeated false; its erratum gives 134.7326 m and true.",
            "docs/eso_scao_benchmark.md line 207 quotes 1683 nm for the reference run, while its manifest records 1674.9 nm; the manifest value is shown.",
            "Some documents still describe the 42 m result as one realization; the S2 records supersede that.",
        ],
        "erratum": erratum,
        "doc_contradiction": s.lines("docs/eso_scao_benchmark.md", 207, 207, "1683"),
        "limitation_locators": [s.lines("docs/current_limitations.md", 479, 508, "periodic")],
        "producer": {"commit": "23125024 (clean) for S1 and S2", "date": "October 2026 (S1 started 2026-10-18)", "host": "arm64 (run records); capability manifest: darwin arm64, 8 CPUs, 16 GiB"},
        "licence": "Repository-authored records (MIT).",
        "downloads": [w.download(e + "det09_e5_42m_noise_on_current_2312502.json", label="S1 replay record")]
        + [w.download(e + f"det09_s2_42m_seed{seed}.json", label=f"S2 seed {seed} record") for seed in range(2, 12)]
        + [w.download("docs/refactor/eso_scao_evidence/reference_tier_v2_manifest.json", label="Noiseless capability manifest"),
           w.download("docs/refactor/eso_scao_evidence/v2_manifest_atmosphere_record_erratum.txt", label="Manifest atmosphere erratum", media_type="text/plain")],
        "sources": [locator(s, e + "det09_e5_42m_noise_on_current_2312502.json", "whole file")] + [locator(s, e + f"det09_s2_42m_seed{seed}.json", "whole file") for seed in range(2, 12)],
        "context_sources": science_sources,
        "selector": {"kind": "recorded_runs", "options": [f"seed {row['root_seed']}" for row in seeds], "note": "highlights a recorded realization; nothing is interpolated"},
        "_values": {"s2_residual_mean": residual_mean, "s2_residual_sd": residual_sd, "s2_strehl_mean": strehl_mean, "s2_strehl_sd": strehl_sd},
    }


# ---------------------------------------------------------------------------
# R6 - analytical MCAO


def group_r6(w: Writer) -> Dict[str, Any]:
    s = w.sources
    path = "notebooks/studies/tiptop_validation.json"
    record = s.json(path)
    seeing = record["seeing_records"]
    ee_first = seeing[0]["completed EE(50 mas)"]
    ee_last = seeing[-1]["completed EE(50 mas)"]
    ee_drop = (ee_first - ee_last) / ee_first * 100.0
    fwhm = [row["completed FWHM (mas)"] for row in seeing]
    bias_rows = [
        {
            "pixel_mas": row["pixel (mas)"],
            "continuous_fwhm_mas": row["continuous annular FWHM (mas)"],
            "sampled_fwhm_mas": row["sampled contour FWHM (mas)"],
            "bias_percent": row["fractional sampling bias"] * 100.0,
        }
        for row in record["annular_reference_records"]
    ]
    bias_note = phrase_lines(s, "docs/notebook12_tiptop_portfolio_notes.md", "The seeing-sweep FWHM change of 0.256 mas", 2)
    budget_terms = ["fitting", "aliasing", "servo-lag", "tomography", "noise", "diff. refraction", "chromatism"]
    budget_rows = [{"regime": row["index"], **{term: row[term] for term in budget_terms}, "completed total": row["completed total"]} for row in record["budget_records"]]
    figures = []
    for name, caption in (
        ("tiptop_baseline_psf.png", "Analytical MCAO baseline PSF at 1.65 um (P3 correction band plus completed fitting tail, MASTSEL propagation)."),
        ("tiptop_error_budget.png", "Completed analytical error budget by term and regime."),
        ("tiptop_seeing_sensitivity.png", "Seeing sensitivity: Strehl, energy within a 50 mas radius and core width."),
        ("tiptop_atmosphere_structure.png", "Turbulence altitude distribution used by the analytical study."),
        ("tiptop_asterism_geometry.png", "Laser guide star asterism and evaluation directions."),
    ):
        figures.append(
            w.figure(
                f"figures/{name}",
                caption=caption,
                alt=caption,
                provenance={
                    "writer": "notebooks/studies/12_TIPTOP_performance_modelling.ipynb (fig.savefig at 150 dpi)",
                    "byte_identical_to_notebook_output": False,
                    "note": "the notebook's inline outputs are 120 dpi renders with different bytes; figures/README.md names the notebook but no cell IDs",
                },
            )
        )
    s.lines("figures/README.md", 28, 34, "not unmodified TIPTOP predictions")
    return {
        "id": "R6",
        "title": "Analytical MCAO: science PSFs, completed error budget and aperture energy",
        "question": "What does a separate analytical multi-conjugate model predict for an 8 m, eight-LGS, three-DM system at 1.65 um?",
        "context": {
            "model_family": "analytical adapter: P3 sampled correction-band PSD plus a continuous fitting-tail completion, propagated by MASTSEL (not a time-domain simulation)",
            "aperture_m": 8.0,
            "configuration": "eight laser guide stars, three deformable mirrors; adapted from a public MavisMCAO.ini",
            "science_wavelength_m": 1.65e-6,
            "metric_definitions": "peak Strehl; energy within a 50 mas RADIUS with the full-field flux as denominator; FWHM in mas",
            "evaluations": f"{record['n_model_evaluations']} model evaluations, {record['n_completed_science_psfs']} completed direction PSFs",
            "versions": record["versions"],
            "uncertainty": "deterministic model outputs; numerical checks in R8",
        },
        "status": ["analytic_model", "executed"],
        "key_values": [
            {"label": "Completed on-axis total residual", "value": record["baseline_completed_total_nm"][0], "display": fmt(record["baseline_completed_total_nm"][0], 4), "unit": "nm", "source": locator(s, path, "$.baseline_completed_total_nm[0]")},
            {"label": "Peak Strehl at 1.65 um", "value": record["baseline_completed_strehl"][0], "display": fmt(record["baseline_completed_strehl"][0], 6), "unit": "", "source": locator(s, path, "$.baseline_completed_strehl[0]")},
            {"label": "Energy within a 50 mas radius", "value": record["baseline_completed_ee50mas"][0], "display": fmt(record["baseline_completed_ee50mas"][0], 6), "unit": "", "source": locator(s, path, "$.baseline_completed_ee50mas[0]")},
            {"label": "Fitting: original grid -> larger native field -> completed tail", "value": [record["baseline_raw_fitting_nm"], record["baseline_wide_raw_fitting_nm"], record["baseline_completed_fitting_nm"]], "display": f"{fmt(record['baseline_raw_fitting_nm'], 4)} -> {fmt(record['baseline_wide_raw_fitting_nm'], 4)} -> {fmt(record['baseline_completed_fitting_nm'], 4)}", "unit": "nm", "source": locator(s, path, "$.baseline_raw_fitting_nm, $.baseline_wide_raw_fitting_nm, $.baseline_completed_fitting_nm")},
        ],
        "tables": [
            {"id": "r6-seeing", "title": "Seeing scan (completed model)", "columns": [
                {"key": "seeing (arcsec)", "label": "Seeing", "unit": "arcsec", "digits": 2}, {"key": "completed Strehl", "label": "Peak Strehl", "unit": "", "digits": 4},
                {"key": "completed EE(50 mas)", "label": "Energy within 50 mas radius", "unit": "", "digits": 4}, {"key": "completed FWHM (mas)", "label": "FWHM", "unit": "mas", "digits": 3},
                {"key": "completed fitting (nm)", "label": "Completed fitting", "unit": "nm", "digits": 2}, {"key": "completed total (nm)", "label": "Completed total", "unit": "nm", "digits": 2}],
             "rows": seeing, "source": locator(s, path, "$.seeing_records")},
            {"id": "r6-fwhm-bias", "title": "FWHM estimator bias against an analytic annular-aperture reference", "columns": [
                {"key": "pixel_mas", "label": "Focal pixel", "unit": "mas", "digits": 1}, {"key": "continuous_fwhm_mas", "label": "Continuous FWHM", "unit": "mas", "digits": 4},
                {"key": "sampled_fwhm_mas", "label": "Sampled-contour FWHM", "unit": "mas", "digits": 4}, {"key": "bias_percent", "label": "Estimator bias", "unit": "%", "digits": 3}],
             "rows": bias_rows, "source": locator(s, path, "$.annular_reference_records")},
            {"id": "r6-budget", "title": "Completed error budget by regime (nm)", "columns": [{"key": "regime", "label": "Regime", "unit": ""}] + [{"key": term, "label": term, "unit": "nm", "digits": 2} for term in budget_terms] + [{"key": "completed total", "label": "Completed total", "unit": "nm", "digits": 2}],
             "rows": budget_rows, "source": locator(s, path, "$.budget_records")},
        ],
        "charts": [
            {
                "id": "r6-seeing-chart",
                "type": "line",
                "title": "Seeing scan: peak Strehl and energy within a 50 mas radius",
                "x": {"label": "Seeing", "unit": "arcsec", "scale": "linear"},
                "y": {"label": "Fraction", "unit": "", "scale": "linear"},
                "series": [
                    {"label": "Peak Strehl", "points": [[row["seeing (arcsec)"], row["completed Strehl"]] for row in seeing]},
                    {"label": "Energy within 50 mas radius", "points": [[row["seeing (arcsec)"], row["completed EE(50 mas)"]] for row in seeing]},
                ],
                "derived_from": "r6-seeing",
                "transformation": "plotted directly from the recorded seeing rows",
            }
        ],
        "figures": figures,
        "takeaway": (
            f"In this analytical MCAO adapter the completed on-axis residual is {fmt(record['baseline_completed_total_nm'][0], 1)} nm, peak Strehl "
            f"{fmt(record['baseline_completed_strehl'][0], 3)} and energy within a 50 mas radius {fmt(record['baseline_completed_ee50mas'][0], 3)} at 1.65 um. "
            f"Completing the fitting tail matters: fitting grows from {fmt(record['baseline_raw_fitting_nm'], 1)} nm on the original grid to "
            f"{fmt(record['baseline_completed_fitting_nm'], 1)} nm. Across the recorded seeing scan the 50 mas energy falls {fmt(ee_drop, 1)} % "
            f"while the sampled core width changes by only {fmt(max(fwhm) - min(fwhm), 2)} mas; that is a differential change at fixed 5 mas sampling, "
            f"comparable to the {fmt(abs(bias_rows[0]['bias_percent']), 2)} % ({fmt(abs(bias_rows[0]['continuous_fwhm_mas'] - bias_rows[0]['sampled_fwhm_mas']), 2)} mas) bias of the width estimator, not an absolute width."
        ),
        "limitations": [
            "A separate analytical study: not a time-domain LGS/MCAO extension of the native SCAO loop and not an unmodified TIPTOP prediction.",
            "Its wavelength, residual convention, profile and budget are not comparable to the native SCAO results in R1-R5 or the 2 m experiment.",
            "Original producer and date fields are absent from the record; a current notebook hash does not establish current-code execution.",
            "Energy is within a 50 mas radius (not diameter), with the full-field flux as denominator.",
            "FWHM values are sampled-contour estimates with a -0.50 % (5 mas pixels) / -0.12 % (2.5 mas) bias against the analytic annular reference; the seeing-scan width change is differential and must not be quoted as an absolute width.",
        ],
        "evidence_notes": [
            "The five figures were written by fig.savefig at 150 dpi and are not byte-identical to the notebook's 120 dpi inline outputs; they are bound by file hash.",
            "The 27.1 % energy drop is computed here from $.seeing_records[0] and [-1]; it is not a stored scalar.",
            "The notebook attributes the configuration to P3's MavisMCAO.ini, the README to TIPTOP's; the source is ambiguous.",
            "No TIPTOP, P3 or MASTSEL licence text is recorded in the repository; versions are pinned (astro-tiptop 1.5.1, astro-p3 1.6.2, mastsel 1.5.2).",
        ],
        "limitation_locators": [s.lines("docs/notebook12_tiptop_portfolio_notes.md", 29, 41, "50 mas"), bias_note],
        "producer": {"commit": "absent", "date": "absent from the record", "environment": "pinned upstream versions only"},
        "licence": "Repository-generated figures and record (MIT) produced with upstream TIPTOP/P3/MASTSEL, whose licence texts are not recorded in the repository.",
        "downloads": [w.download(path, label="Analytical study validation record")],
        "sources": [locator(s, path, "whole file")],
        "_values": {"ee_drop_percent": ee_drop},
    }


# ---------------------------------------------------------------------------
# R7 - cross-backend validation


def _criterion_outcome(metric: Dict[str, Any]) -> str:
    """Outcome of one stored criterion: the four types the baseline uses, bounds inclusive."""

    criterion = metric.get("pass_criterion")
    value = metric.get("value")
    if not criterion:
        return "unrecognized criterion (missing)"
    kind = criterion["type"]
    if kind == "informational":
        return "informational"
    if kind == "equals":
        return "pass" if value == criterion["expected"] else "fail"
    if kind == "abs_tolerance":
        return "pass" if abs(float(value) - float(criterion["expected"])) <= float(criterion["tolerance"]) else "fail"
    if kind == "range":
        return "pass" if float(criterion["low"]) <= float(value) <= float(criterion["high"]) else "fail"
    return f"unrecognized criterion {kind}"


def group_r7(w: Writer) -> Dict[str, Any]:
    s = w.sources
    path = "src/shwfs_ao/resources/reference_metrics/cross_backend/cross_backend_baseline.json"
    baseline = s.json(path)
    rows = []
    for group_index, group in enumerate(baseline["comparisons"]):
        for metric_index, metric in enumerate(group["metrics"]):
            rows.append(
                {
                    "group": group["comparison_kind"],
                    "metric": metric["name"],
                    "category": metric["level"],
                    "value": metric["value"],
                    "units": metric.get("units"),
                    "criterion": metric.get("pass_criterion"),
                    "outcome_recomputed": _criterion_outcome(metric),
                    "locator": f"comparisons[{group_index}].metrics[{metric_index}]",
                }
            )
    counts: Dict[str, int] = {}
    outcomes: Dict[str, int] = {}
    for row in rows:
        counts[row["category"]] = counts.get(row["category"], 0) + 1
        outcomes[row["outcome_recomputed"]] = outcomes.get(row["outcome_recomputed"], 0) + 1
    unknown = [row for row in rows if row["outcome_recomputed"].startswith("unrecognized")]
    if unknown:
        raise ResearchExportError(f"unrecognized cross-backend criteria: {sorted({row['criterion']['type'] for row in unknown})}")
    figure = w.extracted_png(
        "notebooks/studies/native_vs_hcipy.ipynb",
        "558504c2",
        caption="Native against HCIPy metric ratios from the accepted small-fixture comparison (saved notebook output).",
        alt="Native versus HCIPy comparison ratio figure",
    )
    z4_path = "docs/refactor/eso_scao_evidence/hcipy_lenslet_axis_closed_loop_192px.md"
    z4 = s.lines(z4_path, 33, 35, "+51.9")
    z4_text = " ".join(s.text(z4_path).splitlines()[32:35])
    z4_match = re.search(r"\+([0-9.]+) ± ([0-9.]+) nm combined", z4_text)
    if not z4_match:
        raise ResearchExportError("R7 combined Z4 summary not found in its document lines")
    z4_value, z4_se = float(z4_match.group(1)), float(z4_match.group(2))
    draft = s.lines("docs/refactor/AO_REF_016A_HCIPY_LENSLET_AXIS.md", 13, 14, "not published")
    generator = baseline["generator"]
    return {
        "id": "R7",
        "title": "Independent backends and the supported comparison domain",
        "question": "Do the native and HCIPy implementations agree, and where does that agreement stop?",
        "context": {
            "model_family": "native and HCIPy time-domain components on one accepted small fixture",
            "aperture_m": 1.0,
            "fixture": "48 px pupil, 3x3 lenslets, 700 nm, 4 loop steps",
            "comparison": f"{len(baseline['comparisons'])} comparison groups, {len(rows)} metrics",
            "uncertainty": "deterministic fixture metrics with declared tolerance classes",
        },
        "status": ["accepted_domain", "summary_only", "pending"],
        "key_values": [
            {"label": "Comparison groups / metrics", "value": [len(baseline["comparisons"]), len(rows)], "display": f"{len(baseline['comparisons'])} / {len(rows)}", "unit": "", "source": locator(s, path, "comparisons[*].metrics[*]")},
            {"label": "Exact / tight numerical / physical tolerance / informational", "value": [counts.get("exact", 0), counts.get("tight_numerical", 0), counts.get("physical_tolerance", 0), counts.get("informational", 0)], "display": f"{counts.get('exact', 0)} / {counts.get('tight_numerical', 0)} / {counts.get('physical_tolerance', 0)} / {counts.get('informational', 0)}", "unit": "", "source": locator(s, path, "comparisons[*].metrics[*].level")},
            {"label": "Criteria recomputed: pass / fail / informational", "value": [outcomes.get("pass", 0), outcomes.get("fail", 0), outcomes.get("informational", 0)], "display": f"{outcomes.get('pass', 0)} / {outcomes.get('fail', 0)} / {outcomes.get('informational', 0)}", "unit": "", "source": locator(s, path, "comparisons[*].metrics[*].pass_criterion (recomputed here)")},
            {"label": "Reduced-scale HCIPy axis change, paired Z4 (SE)", "value": [z4_value, z4_se], "display": f"+{z4_value:g} +/- {z4_se:g}", "unit": "nm", "source": z4},
        ],
        "tables": [
            {"id": "r7-metrics", "title": "Cross-backend metrics (accepted baseline)", "columns": [
                {"key": "group", "label": "Group", "unit": ""}, {"key": "metric", "label": "Metric", "unit": ""}, {"key": "category", "label": "Category", "unit": ""},
                {"key": "value", "label": "Recorded value", "unit": ""}, {"key": "units", "label": "Units", "unit": ""}, {"key": "outcome_recomputed", "label": "Criterion (recomputed)", "unit": ""}],
             "rows": rows, "source": locator(s, path, "comparisons[*].metrics[*]"),
             "notes": "The baseline stores criteria, not pass flags; outcomes are recomputed here from each stored criterion. Native and HCIPy values appear as separately named metrics."},
        ],
        "charts": [
            {
                "id": "r7-categories",
                "type": "bar",
                "title": "Metrics per tolerance category",
                "categories": ["exact", "tight_numerical", "physical_tolerance", "informational"],
                "values": [counts.get(key, 0) for key in ("exact", "tight_numerical", "physical_tolerance", "informational")],
                "y": {"label": "Metrics", "unit": ""},
                "derived_from": "r7-metrics",
                "transformation": "count of recorded metrics per stored level",
            }
        ],
        "figures": [figure],
        "takeaway": (
            f"On the accepted 1 m fixture the two independent backends agree on all {outcomes.get('pass', 0)} criteria-bearing metrics "
            f"({counts.get('exact', 0)} exact, {counts.get('tight_numerical', 0)} tight numerical, {counts.get('physical_tolerance', 0)} physical tolerance), "
            f"with {counts.get('informational', 0)} informational metrics. A reduced-scale (5 m, 192 px) HCIPy study moves the paired Z4 by +{z4_value:g} +/- {z4_se:g} nm "
            "(standard error) when the lenslet axis is block-centred; that result is summary-only and its published-scale confirmation is pending."
        ),
        "limitations": [
            "Agreement is established on one small fixture; it is not a proof of universal backend equivalence or an operational-instrument validation.",
            "The Z4 result is a 5 m reduced-scale summary; its raw comparison JSON was not retained.",
            "The high_order_10m_hcipy@4 draft is not published and is not an accepted result.",
        ],
        "evidence_notes": [
            "docs/validation.md lists 'mask round trip' as tight numerical, while the baseline records it as exact; the baseline is used.",
        ],
        "z4_summary": z4,
        "draft_status": draft,
        "producer": {"commit": f"{generator['source_commit'][:12]} (clean tree)", "accepted": baseline["acceptance"]["accepted_at_utc"], "review": baseline["acceptance"]["review_reference"]},
        "licence": "Repository-authored baseline (MIT); HCIPy is an upstream library (version pinned in the baseline environment).",
        "downloads": [w.download(path, label="Accepted cross-backend baseline")],
        "sources": [locator(s, path, "whole file"), figure["source"]],
        "_values": {"counts": counts, "outcomes": outcomes},
    }


# ---------------------------------------------------------------------------
# R8 - numerical verification and open questions


def group_r8(w: Writer) -> Dict[str, Any]:
    s = w.sources
    rows = []
    ee_rows = []
    for scale, name in (("12 m", "paired_convergence_medium.json"), ("42 m", "paired_convergence_full.json")):
        path = f"docs/refactor/eso_scao_evidence/{name}"
        record = s.json(path)
        for scan, content in record["scans"].items():
            for metric, item in content["convergence"].items():
                rows.append(
                    {
                        "scale": scale,
                        "scan": scan,
                        "metric": metric,
                        "relative_change_finest_two": item["relative_change_finest_two"],
                        "paired_se": item.get("paired_relative_difference_se"),
                        "within_declared_tolerance": item["within_declared_tolerance"],
                        "declared_tolerance": record["declared_tolerance"],
                        "realizations": record["realizations"],
                    }
                )
        entries = {entry["setting"]: entry for entry in record["scans"]["science_psf_pad_factor"]["entries"]}
        settings = sorted(entries, key=lambda key: int(re.sub(r"\D", "", key)))
        coarse, fine = entries[settings[0]], entries[settings[-1]]
        ee_rows.append(
            {
                "scale": scale,
                "coarse_setting": settings[0],
                "reference_setting": settings[-1],
                "ee50_coarse_mas": coarse["ee50_radius_rad_mean"] * 180 / math.pi * 3600e3,
                "ee50_reference_mas": fine["ee50_radius_rad_mean"] * 180 / math.pi * 3600e3,
                "relative_excess_percent": (coarse["ee50_radius_rad_mean"] / fine["ee50_radius_rad_mean"] - 1.0) * 100.0,
            }
        )
    tiptop = s.json("notebooks/studies/tiptop_validation.json")
    checks = [
        {"check": name, "value": tiptop[name]}
        for name in (
            "max_1024_2048_strehl_change",
            "max_1024_2048_ee_change",
            "max_1024_2048_fwhm_mas_change",
            "max_1024_2048_crop_energy_change",
            "max_quadrature_relative_change",
            "max_completed_psf_change_native_fov400_to800",
            "max_focal_pixel_fwhm_relative_change",
            "max_budget_closure_nm",
            "repeat_max_psf_difference",
        )
    ]
    medium = s.json("docs/refactor/eso_scao_evidence/paired_convergence_medium.json")
    full = s.json("docs/refactor/eso_scao_evidence/paired_convergence_full.json")
    if (medium["frames"], medium["burn_in"], medium["wavelength_m"]) != (full["frames"], full["burn_in"], full["wavelength_m"]):
        raise ResearchExportError("the two convergence records differ in frames, burn-in or wavelength")
    open_questions = [
        {"id": "LIM-18 / S4", "question": "Why the 12 m isolated detector noise departs from an inverse-photon law (6.7 % dip, 2 m drift)", "status": "open", "source": s.lines("docs/current_limitations.md", 515, 528, "unexplained")},
        {"id": "LIM-07", "question": "Spatial convergence of the detector-level profiles (ESO-tier results do not transfer)", "status": "open", "source": s.lines("docs/current_limitations.md", 310, 318, "7.3 %")},
        {"id": "LIM-05", "question": "Finite-exposure science integration (the science observer samples the frame start)", "status": "open", "source": s.lines("docs/current_limitations.md", 261, 268, "frame start")},
        {"id": "LIM-08", "question": "Periodic-band repetition and statistical limits of long runs", "status": "open", "source": s.lines("docs/current_limitations.md", 340, 353, "periodic")},
        {"id": "LIM-01", "question": "No calibration against an operational AO instrument", "status": "open", "source": s.lines("docs/current_limitations.md", 166, 170, "operational AO instrument")},
    ]
    eleven, forty_two = ee_rows
    return {
        "id": "R8",
        "title": "Numerical verification, provenance and open questions",
        "question": "Which numbers are numerically converged and reproducible, and what remains unresolved?",
        "context": {
            "model_family": "ESO-tier native SCAO convergence studies; analytical-study numerical checks",
            "aperture_m": "12 m and 42 m ESO tiers (eso_scao_* profiles); 8 m analytical study",
            "realizations": f"{len(medium['realizations'])} paired realizations per convergence setting",
            "science_wavelength_m": medium["wavelength_m"],
            "window": f"{medium['frames']} frames, burn-in {medium['burn_in']} (both ESO tiers)",
            "declared_tolerance": f"{medium['declared_tolerance']} relative (finest two settings)",
            "uncertainty": "convergence: finest-two relative change and paired SE over 3 realizations; analytical checks: deterministic maxima",
            "evidence_classes": "CI/regression/replay, numerical verification and measured hardware validation are separate classes; this group contains the first two only",
        },
        "status": ["executed", "pending"],
        "key_values": [
            {"label": "EE50 at science pad 2 against pad 4, 12 m", "value": eleven["relative_excess_percent"], "display": f"+{fmt(eleven['relative_excess_percent'], 2)} %", "unit": "", "source": locator(s, "docs/refactor/eso_scao_evidence/paired_convergence_medium.json", "scans.science_psf_pad_factor.entries[*].ee50_radius_rad_mean (ratio computed here)")},
            {"label": "EE50 at science pad 2 against pad 4, 42 m", "value": forty_two["relative_excess_percent"], "display": f"+{fmt(forty_two['relative_excess_percent'], 2)} %", "unit": "", "source": locator(s, "docs/refactor/eso_scao_evidence/paired_convergence_full.json", "scans.science_psf_pad_factor.entries[*].ee50_radius_rad_mean (ratio computed here)")},
        ],
        "tables": [
            {"id": "r8-convergence", "title": "ESO-tier sampling convergence (finest two settings)", "columns": [
                {"key": "scale", "label": "Scale", "unit": ""}, {"key": "scan", "label": "Scan", "unit": ""}, {"key": "metric", "label": "Metric", "unit": ""},
                {"key": "relative_change_finest_two", "label": "Relative change", "unit": "", "digits": 5}, {"key": "paired_se", "label": "Paired SE", "unit": "", "digits": 5},
                {"key": "declared_tolerance", "label": "Declared tolerance", "unit": ""}, {"key": "within_declared_tolerance", "label": "Within tolerance", "unit": ""}],
             "rows": rows, "source": [locator(s, "docs/refactor/eso_scao_evidence/paired_convergence_medium.json", "scans[*].convergence"), locator(s, "docs/refactor/eso_scao_evidence/paired_convergence_full.json", "scans[*].convergence")],
             "uncertainty": "paired SE over 3 realizations"},
            {"id": "r8-ee50", "title": "EE50 pixel limitation (science pad 2 against the finest pad)", "columns": [
                {"key": "scale", "label": "Scale", "unit": ""}, {"key": "coarse_setting", "label": "Coarse", "unit": ""}, {"key": "reference_setting", "label": "Reference", "unit": ""},
                {"key": "ee50_coarse_mas", "label": "EE50 radius, coarse", "unit": "mas", "digits": 3}, {"key": "ee50_reference_mas", "label": "EE50 radius, reference", "unit": "mas", "digits": 3},
                {"key": "relative_excess_percent", "label": "Excess", "unit": "%", "digits": 2}],
             "rows": ee_rows, "source": [locator(s, "docs/refactor/eso_scao_evidence/paired_convergence_medium.json", "scans.science_psf_pad_factor.entries"), locator(s, "docs/refactor/eso_scao_evidence/paired_convergence_full.json", "scans.science_psf_pad_factor.entries")]},
            {"id": "r8-tiptop", "title": "Analytical-study numerical checks", "columns": [{"key": "check", "label": "Check", "unit": ""}, {"key": "value", "label": "Recorded maximum", "unit": ""}],
             "rows": checks, "source": locator(s, "notebooks/studies/tiptop_validation.json", "top-level check fields")},
            {"id": "r8-open", "title": "Open questions kept discoverable", "columns": [{"key": "id", "label": "Item", "unit": ""}, {"key": "question", "label": "Question", "unit": ""}, {"key": "status", "label": "Status", "unit": ""}],
             "rows": [{key: item[key] for key in ("id", "question", "status")} for item in open_questions], "source": [item["source"] for item in open_questions]},
        ],
        "charts": [
            {
                "id": "r8-convergence-chart",
                "type": "bar",
                "title": "Finest-two relative change by scan and metric",
                "categories": [f"{row['scale']} {SCAN_LABELS[row['scan']]}: {METRIC_LABELS[row['metric']]}" for row in rows],
                "values": [row["relative_change_finest_two"] * 100.0 for row in rows],
                "y": {"label": "Relative change", "unit": "%"},
                "derived_from": "r8-convergence",
                "transformation": "relative_change_finest_two x 100",
            }
        ],
        "figures": [],
        "takeaway": (
            "On the ESO tiers the peak Strehl is converged in pupil, WFS and science sampling, while the EE50 radius is pixel-limited at "
            f"science pad 2 (+{fmt(eleven['relative_excess_percent'], 1)} % at 12 m and +{fmt(forty_two['relative_excess_percent'], 1)} % at 42 m against the finest pad). "
            "The analytical study's grid, quadrature and budget-closure checks are recorded. These are numerical verifications on their own profiles; "
            "they do not transfer to the detector-level profiles, and none is a hardware validation."
        ),
        "limitations": [
            "ESO-tier convergence does not transfer to the distinct detector-level profiles, whose convergence studies are prepared but unrun.",
            "Accepting the T1/T2 diagnostic and convergence machinery is not the execution of the pending larger studies.",
            "Science images sample the frame start; finite science-exposure integration is not modelled.",
            "Numerical and backend agreement are not operational-instrument calibration.",
        ],
        "evidence_notes": [
            "The 7.3 % / 3.6 % EE50 excess is computed here from stored scan means; it is not a stored scalar.",
            "The convergence records name producer 2312502 (clean) and carry no date.",
        ],
        "open_questions": open_questions,
        "producer": {"commit": "2312502 (clean) for the convergence records; absent for the analytical record"},
        "licence": "Repository-authored records (MIT).",
        "downloads": [
            w.download("docs/refactor/eso_scao_evidence/paired_convergence_medium.json", label="12 m paired convergence record"),
            w.download("docs/refactor/eso_scao_evidence/paired_convergence_full.json", label="42 m paired convergence record"),
        ],
        "sources": [locator(s, "docs/refactor/eso_scao_evidence/paired_convergence_medium.json", "whole file"), locator(s, "docs/refactor/eso_scao_evidence/paired_convergence_full.json", "whole file"), locator(s, "notebooks/studies/tiptop_validation.json", "whole file")],
    }


SCAN_LABELS = {"pupil_samples_per_lenslet": "pupil sampling", "wfs_pad_factor": "WFS pad", "science_psf_pad_factor": "science pad"}
METRIC_LABELS = {"peak_strehl": "Strehl", "ee50_radius_rad": "EE50 radius"}

GROUPS = (group_r1, group_r2, group_r3, group_r4, group_r5, group_r6, group_r7, group_r8)


def _check_repository_url() -> None:
    """The source links must point at this checkout's own remote repository."""

    completed = subprocess.run(["git", "remote", "get-url", "origin"], cwd=identity.REPO_ROOT, capture_output=True, text=True)
    remote = completed.stdout.strip()
    normalized = re.sub(r"^git@github\.com:", "https://github.com/", remote)
    normalized = normalized[:-4] if normalized.endswith(".git") else normalized
    if normalized != REPOSITORY_URL:
        raise ResearchExportError(f"origin {remote!r} is not {REPOSITORY_URL}; the site's source links would be wrong")


def export(bundle: Any, *, series_dir: Path) -> Dict[str, Any]:
    sources = Sources()
    writer = Writer(bundle, sources)
    groups = []
    for builder in GROUPS:
        group = builder(writer)
        group.pop("_lookup", None)
        group["computed_checks"] = group.pop("_values", None)
        groups.append(group)
    ids = [group["id"] for group in groups]
    if ids != [f"R{index}" for index in range(1, 9)]:
        raise ResearchExportError(f"result groups {ids} are not R1..R8")
    coverage = []
    for group in groups:
        coverage.append(
            {
                "group": group["id"],
                "title": group["title"],
                "figures": len(group["figures"]),
                "tables": len(group["tables"]),
                "charts": len(group["charts"]),
                "key_values": len(group["key_values"]),
                "downloads": len(group["downloads"]),
                "status": group["status"],
                "quantitative": bool(group["tables"] or group["charts"]),
            }
        )
    _check_repository_url()
    payload = {
        "schema": RESULTS_SCHEMA,
        "export_revision": EXPORT_REVISION,
        "source_sha": sources.tree_sha,
        "source_repository": {
            "url": REPOSITORY_URL,
            "commit": sources.tree_sha,
            "link_rule": "{url}/blob/{commit}/{path}, with #L{first}-L{last} for line locators; a locator with its own commit names a historical producer",
            "note": "source links open the repository at the recorded commit on GitHub, an external site; the page itself requests nothing from it",
        },
        "status_vocabulary": STATUS_WORDS,
        "separation_note": (
            "These results come from saved records of their own studies. They are not produced by, and do not respond to, "
            "the 2 m experiment's controls; selectors here only highlight recorded rows or runs."
        ),
        "groups": groups,
        "coverage": coverage,
        "sources_read": sorted(sources.read.values(), key=lambda item: item["path"]),
        "historical_sources_read": sorted(sources.historical.values(), key=lambda item: (item["commit"], item["path"])),
    }
    if not all(item["working_tree_identical"] for item in payload["sources_read"]):
        raise ResearchExportError("a research source differs between the frozen tree and the working tree")
    return bundle.write_json("research/results.json", payload, role="research_results")
