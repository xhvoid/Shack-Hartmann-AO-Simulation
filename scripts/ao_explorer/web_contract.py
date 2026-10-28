"""The supported web-bundle contracts of the AO Simulation Explorer (standard library only).

``validate.py`` checks the committed 2 m dataset against one of two dataset
contracts.  The contract is selected explicitly from the pair (entry schema,
manifest schema) that the committed entry names; every other combination is
refused.  The contract, not the manifest under test, supplies the expected
frame counts, analysis window, displayed frames, colour levels, member roles
and record schemas:

* ``v1`` -- the 180-frame dataset written by ``export.py``/``render.py`` under
  the frozen ``protocol.py``: 180 frames at 1 kHz, burn-in 40, analysis
  window [40, 180) of 140 frames, 40 movie frames from
  ``protocol.movie_indices()``, 256-level OPD atlases, Research Results and
  diagnostics inside the dataset, one dataset directory under ``data/``.
* ``v2`` -- the one-second dataset written by ``long_series.py`` and
  ``long_export.py``: 1000 frames at 1 kHz, startup exclusion 200, analysis
  window [200, 1000) of 800 frames, 126 displayed frames (every 8th frame and
  frame 999), 255-level OPD atlases with a transparent exterior index, 100-frame
  block summaries, playback and screen metadata, the previous dataset preserved
  under ``data/`` with its Research Results referenced in place.

Frame counts, windows and the block length come from the versioned producer
modules (``protocol`` for v1, ``long_series`` for v2).  The display and export
constants that ``long_export.py``, ``render.py`` and ``binary_scene.py`` define
next to NumPy code are restated here so that this module and the validator stay
importable without NumPy; ``tests/ao_explorer/test_validate_contracts.py``
checks that the restated values still equal the exporters'.  The v2 producer's
record checks (the ``checks`` mapping every case record carries and the v2
provenance copies) are read from the source of ``long_series.run_case`` and the
observers it uses, without importing them (``producer_checks_v2``).
"""

from __future__ import annotations

import ast
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, FrozenSet, Optional, Tuple

import long_series
import protocol


ENTRY_SCHEMA = "ao-explorer.entry.v1"
SCENE_EXPORT_SCHEMA = "ao-explorer.scene-export.v1"
BLOCKS_SCHEMA = "ao-explorer.blocks.v1"
SAMPLING_RULE = "one atmosphere sample per frame at its start, t_k = k / f"

# Shared science/display semantics (render.py, long_export.py, binary_scene.py).
IMAGE_UNITS = {
    "atmosphere": "nm OPD",
    "correction": "nm OPD-equivalent (not mirror surface height)",
    "residual": "nm OPD",
    "psf_uncorrected": "log10 relative intensity",
    "psf_corrected": "log10 relative intensity",
}
OPD_KINDS = ("atmosphere", "correction", "residual")
PSF_KINDS = ("psf_uncorrected", "psf_corrected")
AVERAGE_KINDS = ("psf_average_uncorrected", "psf_average_corrected")
PARENT_FIELDS = {"corrected": "pre_update_residual_opd_m", "uncorrected": "atmosphere_opd_m (zero-DM optical counterfactual)"}
PARENT_NORMALIZATION = "unit total flux over the complete uncropped propagator grid"
PARENT_SAMPLING = "frame-start instantaneous snapshots; not a finite-shutter sub-frame integration"
PARENT_RECENTERING = "none"
PARENT_COADDITION = "intensity"
PER_FRAME_SERIES = (
    "atmosphere_rms_nm",
    "residual_rms_nm",
    "peak_strehl_uncorrected",
    "peak_strehl_corrected",
    "valid_measurement_fraction",
    "valid_subaperture_fraction",
    "dm_saturation_fraction",
)
CSV_COLUMNS = (
    "frame_index",
    "time_s",
    "atmosphere_rms_nm",
    "residual_rms_nm",
    "peak_strehl_uncorrected",
    "peak_strehl_corrected",
    "valid_measurement_fraction",
    "valid_subaperture_fraction",
    "reconstruction_usable",
    "dm_saturation_fraction",
)
SUMMARY_KEYS = (
    "window",
    "sample_count",
    "mean_atmosphere_rms_nm",
    "mean_residual_rms_nm",
    "root_mean_square_residual_nm",
    "mean_instantaneous_peak_strehl_uncorrected",
    "mean_instantaneous_peak_strehl_corrected",
    "average_psf_peak_strehl_uncorrected",
    "average_psf_peak_strehl_corrected",
    "average_psf_on_axis_strehl_corrected",
    "average_psf_fwhm_lambda_over_d_corrected",
    "average_psf_fwhm_lambda_over_d_uncorrected",
    "mean_valid_measurement_fraction",
    "min_valid_measurement_fraction",
    "reconstruction_usable_fraction",
    "mean_dm_saturation_fraction",
    "max_dm_saturation_fraction",
)
# Metrics of the mean intensity image: recorded by the production accumulator,
# never recomputed from the per-frame rows, and distinct from the mean
# instantaneous metrics.
AVERAGE_IMAGE_KEYS = (
    "average_psf_peak_strehl_uncorrected",
    "average_psf_peak_strehl_corrected",
    "average_psf_on_axis_strehl_corrected",
    "average_psf_fwhm_lambda_over_d_corrected",
    "average_psf_fwhm_lambda_over_d_uncorrected",
)
OBSERVATION_RENDERER_REVISION = "ao-explorer.binary-observation.v1"
CONVOLUTION_POLICY = {
    "kind": "discrete linear convolution, zero extension",
    "full_shape_rule": "N + M - 1 samples per axis",
    "evaluation": "explicit sum of weight-scaled kernels at each non-zero scene cell (exact, no FFT, no wrap)",
    "kernel_origin": "the kernel sample at exactly zero angle on both actual axes",
    "output_axes": "theta_S[0] + theta_P[0] + m * delta for full index m",
    "crop": "full-output samples whose angles equal the native PSF grid, matched from coordinates",
    "boundary": "zero outside both arrays",
    "renormalization": "none (no peak, cropped-sum or per-image normalization)",
    "spatial_invariance": "one on-axis PSF assumed throughout the compact scene (illustrative)",
}
OPD_COLORMAP = "RdBu_r"
PSF_COLORMAP = "inferno"
PSF_LOG_DECADES = 4.0
PSF_DISPLAY_HALF_WIDTH_CELLS = 32
ATLAS_COLUMNS = 8
OPD_LIMIT_QUANTUM_M = 50e-9
V1_MEMBER_ROLES = frozenset({
    "case", "config", "diagnostics", "display", "display_atlas", "display_average", "metrics", "metrics_csv", "observation",
    "provenance", "research_evidence", "research_extract", "research_figure", "research_results", "scene", "scene_reference",
})
V2_MEMBER_ROLES = frozenset({
    "block_summaries", "case", "config", "diagnostics", "display", "display_atlas", "display_average", "metrics", "metrics_csv",
    "observation", "provenance", "scene", "scene_reference",
})
V2_DISPLAY_STRIDE = 8
V2_DISPLAY_RULE = (
    "frames k = 0, 8, 16, ..., 992 and the last frame 999 (126 actual recorded frames, including 0, 200 and 999); "
    "every 8th frame keeps the active site within the 30 MiB budget, while all 1000 frames remain in the numerical archives, "
    "the scalar records and the 800-frame means"
)
V2_PLAYBACK_DURATIONS_S = (20, 25, 30)
V2_PLAYBACK_DEFAULT_S = 20
V2_OPD_CODES = 255
V2_OPD_EXTERIOR_INDEX = 255


class UnsupportedContract(Exception):
    """The entry/manifest schema pair is not one of the supported contracts."""


@dataclass(frozen=True)
class ProducerChecks:
    """The ``checks`` mapping a producer writes into every case record, as its own source defines it.

    ``required_true`` are the checks without which the producer refuses to write the record, so a record it
    wrote carries each of them literally ``true``; ``window_fields`` name the recorded analysis frames
    (half-open ``[first, last + 1)``) and count, which the producer also requires to equal the contract's;
    ``diagnostics`` are the numeric records kept beside them: their keys and whether every value is an absolute
    deviation (so non-negative).  The diagnostics carry no tolerance here; the producer judged them already.
    """

    source: str
    recorded: Tuple[str, ...]
    required_true: Tuple[str, ...]
    window_fields: Tuple[str, str]
    diagnostics: Dict[str, Tuple[Tuple[str, ...], bool]]


def _function(tree: ast.AST, name: str, owner: Optional[str] = None) -> ast.FunctionDef:
    scope: Optional[ast.AST] = tree
    if owner is not None:
        scope = next((node for node in ast.walk(tree) if isinstance(node, ast.ClassDef) and node.name == owner), None)
    for node in ast.walk(scope) if scope is not None else ():
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return node
    raise ValueError(f"producer source has no {owner + '.' if owner else ''}{name}")


def _string_keys(node: ast.Dict, where: str) -> Tuple[str, ...]:
    keys = tuple(key.value for key in node.keys if isinstance(key, ast.Constant) and isinstance(key.value, str))
    if len(keys) != len(node.keys):
        raise ValueError(f"{where}: every key must be a string literal")
    return keys


def _absolute(node: ast.AST) -> bool:
    """Whether the expression takes an absolute value (``abs(...)`` or ``np.abs(...)``)."""

    return any(isinstance(call, ast.Call) and ((isinstance(call.func, ast.Name) and call.func.id == "abs") or (isinstance(call.func, ast.Attribute) and call.func.attr == "abs"))
               for call in ast.walk(node))


def _assigned_dict(function: ast.FunctionDef, target: str) -> ast.Dict:
    """The dict literal assigned to ``target`` (a name or ``self.<attribute>``) inside ``function``."""

    for node in ast.walk(function):
        if isinstance(node, (ast.Assign, ast.AnnAssign)) and isinstance(node.value, ast.Dict):
            for name in node.targets if isinstance(node, ast.Assign) else [node.target]:
                if ast.unparse(name) == target:
                    return node.value
    raise ValueError(f"{function.name}: no dict literal assigned to {target}")


def producer_checks_v2() -> ProducerChecks:
    """Read the one-second producer's record checks from ``long_series.run_case`` and its observers' source.

    Parsed, never imported (both modules need NumPy and the AO package).  Any change to the shape read here --
    the ``checks`` literal and its later entries, the ``failed`` names the producer refuses a record on, the
    analysis-count guard, the observers' diagnostic dicts -- raises instead of guessing.
    """

    series_path = Path(long_series.__file__)
    series = ast.parse(series_path.read_text(encoding="utf-8"))
    observer = ast.parse(series_path.with_name("observer.py").read_text(encoding="utf-8"))
    run_case = _function(series, "run_case")
    literal = _assigned_dict(run_case, "checks")
    values = dict(zip(_string_keys(literal, "run_case checks"), literal.values))
    for node in ast.walk(run_case):
        if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Subscript) and ast.unparse(node.targets[0].value) == "checks":
            key = node.targets[0].slice
            if not (isinstance(key, ast.Constant) and isinstance(key.value, str)) or key.value in values:
                raise ValueError("run_case: a later checks entry is not a new string-literal key")
            values[key.value] = node.value
    failed = next((node.value for node in ast.walk(run_case) if isinstance(node, ast.Assign) and [ast.unparse(t) for t in node.targets] == ["failed"]), None)
    names = failed.generators[0].iter if isinstance(failed, ast.ListComp) and len(failed.generators) == 1 else None
    if not isinstance(names, ast.Tuple) or not all(isinstance(item, ast.Constant) and isinstance(item.value, str) for item in names.elts):
        raise ValueError("run_case: the checks the producer refuses a record on are not a literal tuple of names")
    required = tuple(item.value for item in names.elts)
    missing = [name for name in required if name not in values]
    if missing:
        raise ValueError(f"run_case: required checks {missing} are not recorded")
    if "checks['analysis_count'] != N_STEPS - STARTUP_EXCLUSION_FRAMES" not in {ast.unparse(node) for node in ast.walk(run_case) if isinstance(node, ast.Compare)}:
        raise ValueError("run_case: the producer no longer requires analysis_count == N_STEPS - STARTUP_EXCLUSION_FRAMES")
    window = ("analysis_frames", "analysis_count")
    if [ast.unparse(values[key]) if key in values else None for key in window] != ["[finish['analysis_frames'][0], finish['analysis_frames'][-1] + 1]", "finish['analysis_count']"]:
        raise ValueError("run_case: the recorded analysis frames and count are no longer the observer's half-open window and count")
    returned = next((node.value for node in ast.walk(_function(observer, "finish", "ExplorerObserver")) if isinstance(node, ast.Return) and isinstance(node.value, ast.Dict)), None)
    if returned is None:
        raise ValueError("ExplorerObserver.finish no longer returns a dict literal")
    finish = dict(zip(_string_keys(returned, "ExplorerObserver.finish"), returned.values))
    archive_keys = _string_keys(_assigned_dict(_function(series, "__init__", "ArchiveObserver"), "self.max_errors"), "ArchiveObserver.max_errors")
    archive_errors = _assigned_dict(_function(series, "observe", "ArchiveObserver"), "errors")
    if _string_keys(archive_errors, "ArchiveObserver.observe errors") != archive_keys:
        raise ValueError("ArchiveObserver: the per-frame errors and their running maxima name different keys")
    diagnostics: Dict[str, Tuple[Tuple[str, ...], bool]] = {}
    for key, value in values.items():
        if key in required or key in window:
            continue
        if ast.unparse(value) == "archive.max_errors":
            diagnostics[key] = (archive_keys, all(_absolute(item) for item in archive_errors.values))
            continue
        if isinstance(value, ast.Subscript) and ast.unparse(value.value) == "finish" and isinstance(value.slice, ast.Constant):
            value = finish.get(value.slice.value, value)
        if not isinstance(value, ast.Dict):
            raise ValueError(f"run_case: checks entry {key!r} is neither a required check, the analysis window nor a diagnostic record")
        diagnostics[key] = (_string_keys(value, f"checks[{key!r}]"), all(_absolute(item) for item in value.values))
    return ProducerChecks(source="long_series.run_case", recorded=tuple(values), required_true=required, window_fields=window, diagnostics=diagnostics)


@dataclass(frozen=True)
class Contract:
    name: str
    entry_schema: str
    manifest_schema: str
    web_schema_version: str
    case_schema: str
    metrics_schema: str
    observation_schema: str
    config_schema: str
    provenance_schema: str
    display_schema: str
    diagnostics_schema: str
    frames: int
    frame_rate_hz: float
    frame_period_s: float
    burn_in: int
    display_indices: Tuple[int, ...]
    opd_levels: int
    opd_exterior_index: Optional[int]
    member_roles: FrozenSet[str]
    manifest_keys: Tuple[str, ...]
    manifest_ref_keys: Tuple[str, ...]
    # v2 features
    time_domain_in_manifest: bool
    previous_dataset_required: bool
    research_in_dataset: bool
    blocks_required: bool
    block_frames: Optional[int]
    playback_required: bool
    playback_durations_s: Tuple[int, ...]
    playback_default_s: Optional[int]
    screen_grid_size: Optional[int]
    display_rule: Optional[str]
    passivity: str                      # "identical" (control run exists) or "not_run_for_this_dataset"
    observation_identity: str           # "code_identity" (v1) or "derived_arrays" (v2)
    parent_identity_key: str            # "job_id" (v1) or "case_id" (v2)
    shared_images: bool                 # paired cases reference the baseline's atmosphere-side images (v2)
    raw_layout: str                     # "movie_npz" (v1) or "frame_stacks" (v2)
    metrics_display_indices: bool
    producer_checks: Optional[ProducerChecks] = None   # v2: the producer's record checks copied into the provenance
    extras: Dict[str, Any] = field(default_factory=dict)

    @property
    def analysis_window(self) -> Tuple[int, int]:
        return (self.burn_in, self.frames)

    @property
    def analysis_count(self) -> int:
        return self.frames - self.burn_in

    @property
    def display_count(self) -> int:
        return len(self.display_indices)

    @property
    def last_frame(self) -> int:
        return self.frames - 1

    @property
    def raw_probe_frames(self) -> Tuple[int, int, int]:
        """Frames whose atlas tiles raw-evidence mode decodes: first, burn-in boundary, last."""

        return (0, self.burn_in, self.frames - 1)

    def display_time(self, frame: int) -> float:
        return frame * self.frame_period_s

    def summary(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "entry_schema": self.entry_schema,
            "manifest_schema": self.manifest_schema,
            "web_schema_version": self.web_schema_version,
            "frames": self.frames,
            "frame_period_s": self.frame_period_s,
            "analysis_window": list(self.analysis_window),
            "analysis_count": self.analysis_count,
            "display_count": self.display_count,
            "opd_levels": self.opd_levels,
            "raw_layout": self.raw_layout,
        }


def v2_display_indices() -> Tuple[int, ...]:
    """The displayed frames of the one-second dataset: every 8th frame and the last (long_export.display_indices)."""

    frames = long_series.N_STEPS
    indices = sorted(set(range(0, frames, V2_DISPLAY_STRIDE)) | {frames - 1})
    if indices[0] != 0 or long_series.STARTUP_EXCLUSION_FRAMES not in indices or indices[-1] != frames - 1:
        raise ValueError("the display subset must include the first frame, the startup boundary and the last frame.")
    return tuple(indices)


V1 = Contract(
    name="v1",
    entry_schema=ENTRY_SCHEMA,
    manifest_schema="ao-explorer.manifest.v1",
    web_schema_version="ao-explorer.web.v1",
    case_schema="ao-explorer.case.v1",
    metrics_schema="ao-explorer.metrics.v1",
    observation_schema="ao-explorer.observation.v1",
    config_schema="ao-explorer.config.v1",
    provenance_schema="ao-explorer.provenance.v1",
    display_schema="ao-explorer.display.v1",
    diagnostics_schema="ao-explorer.diagnostics.v1",
    frames=protocol.PRODUCTION_FRAMES,
    frame_rate_hz=1000.0,
    frame_period_s=0.001,
    burn_in=protocol.PRODUCTION_BURN_IN,
    display_indices=tuple(protocol.movie_indices()),
    opd_levels=256,
    opd_exterior_index=None,
    member_roles=V1_MEMBER_ROLES,
    manifest_keys=("schema", "web_schema_version", "dataset_id", "default_case", "groups", "cases", "scene", "display", "diagnostics", "results", "summaries", "series", "members"),
    manifest_ref_keys=("cases", "scene", "display", "diagnostics", "results"),
    time_domain_in_manifest=False,
    previous_dataset_required=False,
    research_in_dataset=True,
    blocks_required=False,
    block_frames=None,
    playback_required=False,
    playback_durations_s=(),
    playback_default_s=None,
    screen_grid_size=None,
    display_rule=None,
    passivity="identical",
    observation_identity="code_identity",
    parent_identity_key="job_id",
    shared_images=False,
    raw_layout="movie_npz",
    metrics_display_indices=False,
)

V2 = Contract(
    name="v2",
    entry_schema=ENTRY_SCHEMA,
    manifest_schema="ao-explorer.manifest.v2",
    web_schema_version="ao-explorer.web.v2",
    case_schema="ao-explorer.case.v2",
    metrics_schema="ao-explorer.metrics.v2",
    observation_schema="ao-explorer.observation.v2",
    config_schema="ao-explorer.config.v2",
    provenance_schema="ao-explorer.provenance.v2",
    display_schema="ao-explorer.display.v2",
    diagnostics_schema="ao-explorer.diagnostics.v2",
    frames=long_series.N_STEPS,
    frame_rate_hz=1000.0,
    frame_period_s=0.001,
    burn_in=long_series.STARTUP_EXCLUSION_FRAMES,
    display_indices=v2_display_indices(),
    opd_levels=V2_OPD_CODES,
    opd_exterior_index=V2_OPD_EXTERIOR_INDEX,
    member_roles=V2_MEMBER_ROLES,
    manifest_keys=("schema", "web_schema_version", "dataset_id", "default_case", "groups", "cases", "scene", "display", "diagnostics", "blocks", "results",
                   "results_origin", "summaries", "time_domain", "playback", "screen", "series", "previous_dataset", "members"),
    manifest_ref_keys=("cases", "scene", "display", "diagnostics", "blocks", "results"),
    time_domain_in_manifest=True,
    previous_dataset_required=True,
    research_in_dataset=False,
    blocks_required=True,
    block_frames=long_series.BLOCK_FRAMES,
    playback_required=True,
    playback_durations_s=V2_PLAYBACK_DURATIONS_S,
    playback_default_s=V2_PLAYBACK_DEFAULT_S,
    screen_grid_size=long_series.SCREEN_GRID_SIZE,
    display_rule=V2_DISPLAY_RULE,
    passivity="not_run_for_this_dataset",
    observation_identity="derived_arrays",
    parent_identity_key="case_id",
    shared_images=True,
    raw_layout="frame_stacks",
    metrics_display_indices=True,
    producer_checks=producer_checks_v2(),
)

CONTRACTS: Dict[str, Contract] = {V1.manifest_schema: V1, V2.manifest_schema: V2}
# The preserved previous dataset a v2 manifest names must be a v1 dataset.
PREVIOUS_DATASET_CONTRACT = V1


def select(entry_schema: Any, manifest_schema: Any) -> Contract:
    """The contract for an (entry schema, manifest schema) pair; anything unlisted is refused."""

    contract = CONTRACTS.get(manifest_schema) if isinstance(manifest_schema, str) else None
    if contract is None:
        raise UnsupportedContract(
            f"unsupported manifest schema {manifest_schema!r}; supported: {sorted(CONTRACTS)}")
    if entry_schema != contract.entry_schema:
        raise UnsupportedContract(
            f"unsupported schema combination: entry {entry_schema!r} with manifest {manifest_schema!r} "
            f"(the {contract.name} contract requires entry {contract.entry_schema!r})")
    return contract
