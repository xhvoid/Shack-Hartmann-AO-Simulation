// Contract of the generated-experiment mode (API ao-dynamic.api.v1), mirrored
// from scripts/ao_dynamic/contract.py.  Pure functions only (no DOM), so the
// same checks run in the page and under Node in the test suite.
//
// A generated run is installed only after these semantic checks pass: a
// response with other units, wavelengths, residual timing, windows, axes,
// layout or scene is refused even when its bytes match their digests.

export const API_VERSION = "ao-dynamic.api.v1";
export const SCHEMAS = {
  info: "ao-dynamic.info.v1", request: "ao-dynamic.request.v1", status: "ao-dynamic.status.v1",
  run: "ao-dynamic.run.v1", check: "ao-dynamic.check.v1", error: "ao-dynamic.error.v1",
};
export const SCIENCE_WAVELENGTH_M = 1.65e-6;
export const WFS_WAVELENGTH_M = 7e-7;
export const FRAME_RATE_HZ = 1000;
export const PROFILE = "det_emccd_2m_synthetic@1";
export const PARAMETER_NAMES = [
  "seed", "r0_m", "r0_reference_wavelength_m", "wind_speed_m_per_s", "wind_direction_deg", "guide_ab_magnitude",
  "controller_gain", "queued_latency_frames", "n_frames", "burn_in", "display_stride",
];
export const INTEGER_PARAMETERS = new Set(["seed", "wind_direction_deg", "queued_latency_frames", "n_frames", "burn_in", "display_stride"]);
export const PHYSICAL_PARAMETER_NAMES = PARAMETER_NAMES.filter((name) => name !== "display_stride");
// API v1 fixes the supported values (scripts/ao_dynamic/contract.py PARAMETERS);
// a service publishing other bounds or defaults is another contract.
export const PARAMETER_TABLE = {
  seed: { kind: "integer", minimum: 1, maximum: 2147483647, default: 1 },
  r0_m: { kind: "number", minimum: 0.06, maximum: 0.3, default: 0.1263371938263465 },
  r0_reference_wavelength_m: { kind: "number", minimum: 5e-7, maximum: 5e-7, default: 5e-7 },
  wind_speed_m_per_s: { kind: "number", minimum: 0, maximum: 30, default: 10 },
  wind_direction_deg: { kind: "integer", minimum: 0, maximum: 359, default: 0 },
  guide_ab_magnitude: { kind: "number", minimum: 4, maximum: 9, default: 7 },
  controller_gain: { kind: "number", minimum: 0, maximum: 1, default: 0.2 },
  queued_latency_frames: { kind: "integer", minimum: 0, maximum: 6, default: 2 },
  n_frames: { kind: "integer", minimum: 16, maximum: 400, default: 180 },
  burn_in: { kind: "integer", minimum: 0, maximum: 392, default: 40 },
  display_stride: { kind: "integer", minimum: 1, maximum: 10, default: 1 },
};
export const FIXED = {
  profile: "det_emccd_2m_synthetic@1", backend: "native", telescope_diameter_m: 2, pupil_pixels: 52, lenslets_across: 5,
  actuators_across: 5, wfs_wavelength_m: 7e-7, science_wavelength_m: 1.65e-6, atmosphere_model: "native_frozen_flow_v2",
  outer_scale_m: 25, frame_rate_hz: 1000, controller_leak: 0.02,
  camera: "synthetic_emccd@1, detector noise on in the loop",
  wfs_exposure: "legacy left point, one atmosphere sample per frame at its start",
  calibration: "built for every run: central differences of DM actuator probes, noise-free",
  reconstructor: "TSVD rcond=1e-08, min_valid_fraction=0.75", realization_index: 0,
};
// Identifiers the page shows: a conservative character set, never markup.
export const SAFE_ID = /^[A-Za-z0-9._-]{1,80}$/;
export const SERVICE_RUN_ID = /^run-[0-9]{8}T[0-9]{6}Z-[0-9a-f]{8}$/;
const HEX64 = /^[0-9a-f]{64}$/;
const HEX_COLOR = /^#[0-9a-f]{6}$/;
export const ATMOSPHERE_PARAMETERS = ["seed", "r0_m", "r0_reference_wavelength_m", "wind_speed_m_per_s", "wind_direction_deg"];
export const SAME_ATMOSPHERE_CHANGES = ["guide_ab_magnitude", "controller_gain", "queued_latency_frames"];
export const CALIBRATION_PARAMETERS = ["seed", "guide_ab_magnitude"];
export const PUPIL = [52, 52];
export const CROP = [64, 64];
export const FRAME_BLOCKS = [
  ["atmosphere_opd_m", PUPIL, "m OPD (NaN outside the pupil)"],
  ["held_correction_opd_m", PUPIL, "m OPD-equivalent (NaN outside the pupil)"],
  ["pre_update_residual_opd_m", PUPIL, "m OPD (NaN outside the pupil)"],
  ["psf_uncorrected", CROP, "relative flux per cell (unit total flux over the uncropped grid)"],
  ["psf_corrected", CROP, "relative flux per cell (unit total flux over the uncropped grid)"],
  ["observation_uncorrected", CROP, "relative flux per cell (scene total 1)"],
  ["observation_corrected", CROP, "relative flux per cell (scene total 1)"],
  ["running_observation_uncorrected", CROP, "relative flux per cell (scene total 1); NaN before burn-in"],
  ["running_observation_corrected", CROP, "relative flux per cell (scene total 1); NaN before burn-in"],
];
export const FINAL_BLOCKS = [
  ["mean_psf_uncorrected", CROP, "relative flux per cell (unit total flux over the uncropped grid)"],
  ["mean_psf_corrected", CROP, "relative flux per cell (unit total flux over the uncropped grid)"],
  ["final_observation_uncorrected", CROP, "relative flux per cell (scene total 1)"],
  ["final_observation_corrected", CROP, "relative flux per cell (scene total 1)"],
  ["scene", CROP, "relative flux per cell (scene total 1)"],
];
export const RESIDUAL_FIELD = "pre_update_residual_opd_m";
export const UNCORRECTED_FIELD = "atmosphere_opd_m (zero-DM optical counterfactual)";
export const HELD_CORRECTION_RULE = "atmosphere_opd_m - pre_update_residual_opd_m (OPD-equivalent metres, not mirror surface height)";
export const PSF_NORMALIZATION = "unit total flux over the complete uncropped propagator grid";
export const PHASE_RULE = "phase_rad = 2 * pi * OPD_m / wavelength_m";
export const PHASE_WRAPPING = "unwrapped: phase is linear in OPD and is never reduced modulo 2 pi";
export const PHASE_DISPLAY_WAVELENGTHS_M = [SCIENCE_WAVELENGTH_M, WFS_WAVELENGTH_M];
export const SCENE_WEIGHTS = [2 / 3, 1 / 3];
export const MAX_TRANSPORTED_FRAMES = 200;
export const MIN_ANALYSIS_SAMPLES = 8;
export const JOB_STATES = ["queued", "running", "completed", "cancelled", "failed"];
export const RUN_FILES = ["run.json", "frames.bin", "final.bin", "metrics.csv", "evidence.npz"];
export const TERMINAL_STATES = new Set(["completed", "cancelled", "failed"]);

const blockFloats = (blocks) => blocks.reduce((sum, [, shape]) => sum + shape[0] * shape[1], 0);
export const FLOATS_PER_FRAME = blockFloats(FRAME_BLOCKS);
export const FINAL_FLOATS = blockFloats(FINAL_BLOCKS);

// Display conversion: phase in radians at a stated wavelength, unwrapped.
export function opdToPhaseRad(opdM, wavelengthM) { return (2 * Math.PI * opdM) / wavelengthM; }

// 8-bit display codes (the same rules as the precomputed explorer's display.json).
export function opdCode(value, limit) {
  const scaled = (value + limit) / (2 * limit);
  return Math.min(255, Math.max(0, Math.floor(Math.min(1, Math.max(0, scaled)) * 255 + 0.5)));
}
export function intensityCode(value, idealPeak, decades) {
  if (!(value > 0)) return 0;
  const scaled = (Math.log10(value / idealPeak) + decades) / decades;
  return Math.min(255, Math.max(0, Math.floor(Math.min(1, Math.max(0, scaled)) * 255 + 0.5)));
}

export function transportedIndices(nFrames, stride) {
  const indices = [];
  for (let k = 0; k < nFrames; k += stride) indices.push(k);
  if (indices[indices.length - 1] !== nFrames - 1) indices.push(nFrames - 1);
  return indices;
}

// The service computes the vector (Python math); off the axes the last bit of
// sin/cos may differ between language runtimes, so consistency is checked
// with a relative tolerance of 1e-12 rather than bit equality.
export function windVector(speed, directionDeg) {
  const exact = { 0: [speed, 0], 90: [0, speed], 180: [-speed, 0], 270: [0, -speed] };
  if (exact[directionDeg]) return exact[directionDeg].map((v) => v + 0);
  const r = directionDeg * (Math.PI / 180);
  return [speed * Math.cos(r), speed * Math.sin(r)];
}

export function windConsistent(vector, speed, directionDeg) {
  const expected = windVector(speed, directionDeg);
  return Array.isArray(vector) && vector.length === 2 && vector.every((v, i) => Math.abs(v - expected[i]) <= 1e-12 * Math.max(1, speed));
}

const req = (condition, message, problems) => { if (!condition) problems.push(message); };
const sameArray = (a, b) => Array.isArray(a) && Array.isArray(b) && a.length === b.length && a.every((v, i) => (Array.isArray(v) ? sameArray(v, b[i]) : v === b[i]));
const isHex64 = (v) => typeof v === "string" && HEX64.test(v);
const isText = (v, max = 2000) => typeof v === "string" && v.length <= max;
const sameObject = (a, b) => !!a && typeof a === "object" && Object.keys(a).length === Object.keys(b).length
  && Object.entries(b).every(([key, value]) => a[key] === value);

// Every reason a parameter set is outside API v1 (types and ranges; derived rules too).
export function parameterProblems(params) {
  const problems = [];
  for (const [name, spec] of Object.entries(PARAMETER_TABLE)) {
    const v = params[name];
    if (spec.kind === "integer") { if (!Number.isInteger(v)) { problems.push(`${name} is not an integer`); continue; } }
    else if (typeof v !== "number" || !Number.isFinite(v)) { problems.push(`${name} is not a finite number`); continue; }
    if (v < spec.minimum || v > spec.maximum) problems.push(`${name} = ${v} is outside the supported range [${spec.minimum}, ${spec.maximum}]`);
  }
  if (!problems.length) {
    if (params.burn_in > params.n_frames - MIN_ANALYSIS_SAMPLES) problems.push("burn_in leaves fewer than 8 analysis samples");
    if (transportedIndices(params.n_frames, params.display_stride).length > MAX_TRANSPORTED_FRAMES) problems.push("display_stride keeps more than 200 frames");
  }
  return problems;
}

export function validateInfo(info) {
  const problems = [];
  if (!info || typeof info !== "object") return ["the service description is not an object"];
  req(info.schema === SCHEMAS.info, `unsupported service description schema ${JSON.stringify(info.schema)}`, problems);
  req(info.api === API_VERSION, `the service speaks ${JSON.stringify(info.api)}, this page needs ${API_VERSION}`, problems);
  if (problems.length) return problems;
  for (const [key, value] of Object.entries(SCHEMAS)) if (key !== "info") req(info.schemas?.[key] === value, `the service's ${key} schema is ${JSON.stringify(info.schemas?.[key])}, not ${value}`, problems);
  req(info.profile === PROFILE && info.fixed?.science_wavelength_m === SCIENCE_WAVELENGTH_M && info.fixed?.wfs_wavelength_m === WFS_WAVELENGTH_M,
    "the service's fixed scope (profile or wavelengths) differs from the one this page supports", problems);
  req(sameObject(info.fixed, FIXED), "the service's fixed scope differs from API v1", problems);
  const names = (info.parameters || []).map((p) => p.name);
  req(sameArray(names, PARAMETER_NAMES), `the service's parameters ${JSON.stringify(names)} differ from this page's`, problems);
  for (const p of info.parameters || []) {
    const spec = PARAMETER_TABLE[p.name];
    req(!!spec && p.kind === spec.kind && p.minimum === spec.minimum && p.maximum === spec.maximum && p.default === spec.default,
      `parameter ${JSON.stringify(p.name)} has another kind, range or default than API v1`, problems);
    req(isText(p.label, 120) && isText(p.unit, 40) && isText(p.note, 600) && isText(p.class, 40), `parameter ${JSON.stringify(p.name)} has malformed descriptive text`, problems);
  }
  const d = info.display || {};
  req(Array.isArray(d.opd_lut_rgb_hex) && d.opd_lut_rgb_hex.length === 256 && Array.isArray(d.intensity_lut_rgb_hex) && d.intensity_lut_rgb_hex.length === 256
    && [...d.opd_lut_rgb_hex, ...d.intensity_lut_rgb_hex].every((c) => typeof c === "string" && HEX_COLOR.test(c)),
    "the service's display tables are incomplete", problems);
  req(d.phase_rule === PHASE_RULE && d.phase_wrapping === PHASE_WRAPPING && sameArray(d.phase_display_wavelengths_m, PHASE_DISPLAY_WAVELENGTHS_M),
    "the service's phase-display convention differs", problems);
  req(sameArray((info.frame_blocks || []).map((b) => [b.name, b.shape, b.unit]), FRAME_BLOCKS)
    && sameArray((info.final_blocks || []).map((b) => [b.name, b.shape, b.unit]), FINAL_BLOCKS), "the service's array layout differs", problems);
  const h = info.horizon || {};
  req(Number.isFinite(h.delta_m) && h.delta_m > 0 && Number.isFinite(h.travel_budget_px) && h.frame_rate_hz === FRAME_RATE_HZ
    && Number.isInteger(h.generated_screen_px), "the service's horizon description is incomplete", problems);
  const s = info.service || {}; const l = info.limits || {};
  req(typeof s.instance_id === "string" && SAFE_ID.test(s.instance_id) && isText(s.kind, 200), "the service's instance description is malformed", problems);
  req(isHex64(info.producer?.worker?.sha256) && isHex64(info.core?.package_sha256), "the service's code identities are malformed", problems);
  req(["max_active_jobs", "job_timeout_s", "abandon_after_s"].every((k) => Number.isFinite(l[k]) && l[k] > 0), "the service's limits are malformed", problems);
  return problems;
}

export function validateStatus(status, { runId } = {}) {
  const problems = [];
  if (!status || typeof status !== "object") return ["job status is not an object"];
  req(status.schema === SCHEMAS.status && status.api === API_VERSION, `unsupported job status schema ${JSON.stringify(status.schema)}`, problems);
  req(JOB_STATES.includes(status.state), `unknown job state ${JSON.stringify(status.state)}`, problems);
  req(typeof status.run_id === "string" && SERVICE_RUN_ID.test(status.run_id), "the status has a malformed run id", problems);
  if (runId) req(status.run_id === runId, `the status names run ${status.run_id}, not ${runId}`, problems);
  const p = status.progress || {};
  req(Number.isInteger(status.seed) && Number.isInteger(p.frames_done) && Number.isInteger(p.n_frames) && (p.physical_time_s === null || Number.isFinite(p.physical_time_s))
    && (status.queue_position === null || Number.isInteger(status.queue_position)) && (status.computation_wall_s === null || Number.isFinite(status.computation_wall_s))
    && ["specified", "allocated_by_service"].includes(status.seed_source) && (status.reason === null || isText(status.reason)) && isText(p.stage, 200),
  "the job status is malformed", problems);
  if (status.files !== null && status.files !== undefined) {
    // File references must be the service's own relative paths: never another
    // origin or scheme (a javascript: link in a download would run script).
    req(RUN_FILES.every((name) => {
      const ref = status.files[name];
      return ref && ref.href === `files/${name}` && Number.isInteger(ref.bytes) && ref.bytes >= 0 && isHex64(ref.sha256);
    }) && Object.keys(status.files).length === RUN_FILES.length, "the status's file references are malformed", problems);
  }
  return problems;
}

// One entry of GET /api/v1/runs, before it is offered in the run list.
export function validRunListEntry(entry) {
  return !!entry && typeof entry.run_id === "string" && SERVICE_RUN_ID.test(entry.run_id) && JOB_STATES.includes(entry.state)
    && Number.isInteger(entry.seed) && !!entry.parameters && parameterProblems(entry.parameters).length === 0;
}

function validateParameterValues(params) {
  const problems = [];
  for (const name of PARAMETER_NAMES) {
    const v = params[name];
    if (INTEGER_PARAMETERS.has(name)) req(Number.isInteger(v), `${name} is not an integer`, problems);
    else req(typeof v === "number" && Number.isFinite(v), `${name} is not a finite number`, problems);
  }
  return problems;
}

export function validateRun(run, { expectedParameters = null, runId = null, fileSizes = null } = {}) {
  const problems = [];
  if (!run || typeof run !== "object") return ["run record is not an object"];
  req(run.schema === SCHEMAS.run, `unsupported run schema ${JSON.stringify(run.schema)}`, problems);
  req(run.api === API_VERSION, `unsupported API ${JSON.stringify(run.api)}`, problems);
  req(run.status === "COMPLETED", `run status is ${JSON.stringify(run.status)}, not COMPLETED`, problems);
  if (problems.length) return problems;
  try {
    req(typeof run.run_id === "string" && SAFE_ID.test(run.run_id), "the record has a malformed run id", problems);
    if (runId) req(run.run_id === runId, `the record names run ${run.run_id}, not ${runId}`, problems);
    const params = run.effective.parameters;
    problems.push(...validateParameterValues(params));
    if (problems.length) return problems;
    problems.push(...parameterProblems(params).map((p) => `recorded parameters: ${p}`));
    if (problems.length) return problems;
    req(windConsistent(params.wind_m_per_s, params.wind_speed_m_per_s, params.wind_direction_deg), "wind vector does not follow from speed and direction", problems);
    req(isHex64(run.effective.physical_identity), "the run has no physical identity", problems);
    req(sameObject(run.effective.fixed, FIXED), "fixed scope differs from API v1", problems);
    const ids = run.identities;
    req(isHex64(ids?.calibration?.interaction_matrix_hash) && isHex64(ids?.history_digest?.sha256) && isText(run.completed_utc, 40) && isText(run.seed_source ?? "", 40),
      "the run's displayed identities are malformed", problems);
    if (expectedParameters) {
      for (const [name, value] of Object.entries(expectedParameters)) {
        if (name === "seed" && value === null) continue;
        req(Array.isArray(value) ? sameArray(params[name], value) : params[name] === value, `${name} is ${JSON.stringify(params[name])}, not the requested ${JSON.stringify(value)}`, problems);
      }
    }
    const n = params.n_frames; const burn = params.burn_in; const stride = params.display_stride;
    req(n >= 1 && burn >= 0 && burn <= n - MIN_ANALYSIS_SAMPLES, "frames and burn-in are inconsistent", problems);
    const c = run.conventions;
    req(c.science_wavelength_m === SCIENCE_WAVELENGTH_M, `science wavelength ${c.science_wavelength_m} m is not 1.65e-6 m`, problems);
    req(c.wfs_wavelength_m === WFS_WAVELENGTH_M, "WFS wavelength is not 7e-7 m", problems);
    req(c.opd_unit === "m", `OPD unit ${JSON.stringify(c.opd_unit)} is not metres`, problems);
    req(c.residual_field === RESIDUAL_FIELD, `residual field ${JSON.stringify(c.residual_field)} is not the pre-update residual`, problems);
    req(c.uncorrected_field === UNCORRECTED_FIELD, "uncorrected field is not the zero-DM atmosphere", problems);
    req(c.held_correction === HELD_CORRECTION_RULE, "held-correction rule differs", problems);
    req(c.psf_normalization === PSF_NORMALIZATION, `PSF normalization ${JSON.stringify(c.psf_normalization)} is not supported`, problems);
    req(c.phase_rule === PHASE_RULE && c.phase_wrapping === PHASE_WRAPPING && sameArray(c.phase_display_wavelengths_m, PHASE_DISPLAY_WAVELENGTHS_M), "phase convention differs", problems);
    req(c.axis_layout === "x_columns_y_rows", "axis layout differs", problems);
    req(c.queued_latency_frames === params.queued_latency_frames && c.wfs_visible_delay_frames === params.queued_latency_frames + 1, "queued and WFS-visible delays are inconsistent", problems);
    const t = run.time;
    req(t.frame_rate_hz === FRAME_RATE_HZ && t.n_frames === n, "time grid header differs", problems);
    req(Array.isArray(t.time_s) && t.time_s.length === n && t.time_s.every((v, k) => Math.abs(v - k / FRAME_RATE_HZ) <= 1e-12), "frame times are not k / 1000 s", problems);
    const w = run.analysis_window;
    req(w.start === burn && w.stop === n && w.count === n - burn && w.samples_used === n - burn, "analysis window is not every frame of [burn_in, n_frames)", problems);
    const pf = run.per_frame;
    for (const key of ["frame_index", "time_s", "atmosphere_rms_m", "residual_rms_m", "peak_strehl_uncorrected", "peak_strehl_corrected", "valid_measurement_fraction",
      "reconstruction_usable", "saturation_fraction_issued", "saturation_fraction_held", "atmosphere_sha256", "running_average_peak_strehl_uncorrected", "running_average_peak_strehl_corrected"]) {
      req(Array.isArray(pf[key]) && pf[key].length === n, `per-frame ${key} does not cover ${n} frames`, problems);
    }
    if (problems.length) return problems;
    req(pf.frame_index.every((v, i) => v === i) && sameArray(pf.time_s, t.time_s), "per-frame indices or times differ from the time grid", problems);
    for (const key of ["running_average_peak_strehl_uncorrected", "running_average_peak_strehl_corrected"]) {
      req(pf[key].every((v, k) => (k < burn ? v === null : typeof v === "number")), `${key} must be unavailable before burn-in and present after it`, problems);
    }
    req(pf.saturation_fraction_held[0] === null && pf.saturation_fraction_held.slice(1).every((v, k) => v === pf.saturation_fraction_issued[k]), "held saturation is not the previous frame's issued command", problems);
    const tr = run.transported;
    const indices = transportedIndices(n, stride);
    req(sameArray(tr.indices, indices), "transported frames do not follow the display stride", problems);
    req(sameArray(tr.time_s, indices.map((k) => t.time_s[k])), "transported times differ from the time grid", problems);
    req(sameArray(tr.running_sample_count, indices.map((k) => Math.max(0, k - burn + 1))), "running averages do not count every eligible frame", problems);
    const a = run.arrays;
    req(a.frames.dtype === "<f4" && sameArray(a.frames.blocks.map((b) => [b.name, b.shape, b.unit]), FRAME_BLOCKS), "frames.bin layout differs", problems);
    req(a.frames.bytes === 4 * FLOATS_PER_FRAME * indices.length, "frames.bin size does not match the transported frames", problems);
    req(a.final.dtype === "<f4" && sameArray(a.final.blocks.map((b) => [b.name, b.shape, b.unit]), FINAL_BLOCKS) && a.final.bytes === 4 * FINAL_FLOATS, "final.bin layout differs", problems);
    if (fileSizes) {
      req(fileSizes["frames.bin"] === a.frames.bytes && fileSizes["final.bin"] === a.final.bytes, "binary files differ in size from the record", problems);
    }
    const s = run.scene;
    req(sameArray(s.sources.map((x) => x.weight), SCENE_WEIGHTS) && s.separation_native_x_cells === 6 && s.wavelength_m === SCIENCE_WAVELENGTH_M, "scene differs from the fixed binary", problems);
    const g = run.grids.psf;
    req(sameArray(g.shape_yx, [156, 156]) && sameArray(g.crop_shape_yx, CROP), "PSF grid or crop differs", problems);
    // Even 156-sample grid: exact zero angle at index 78; the crop is centred on it.
    req(g.x_zero_index === 78 && g.y_zero_index === 78 && sameArray(g.crop_slices_yx, [[46, 110], [46, 110]]), "the crop is not centred on the zero-angle sample", problems);
    req(s.sources[0].index_yx?.[0] === 78 && s.sources[0].index_yx?.[1] === 78 && s.sources[1].index_yx?.[1] === 84 && s.sources[1].index_yx?.[0] === 78,
      "the scene is not at the zero-angle sample and +6 x cells", problems);
    req(g.x_angle_rad_sha256 === s.grid.x_angle_rad_sha256 && g.y_angle_rad_sha256 === s.grid.y_angle_rad_sha256, "scene grid differs from the PSF grid", problems);
    const d = run.display;
    req(d.psf_log_decades === 4 && d.opd_limit_m > 0 && d.ideal_peak_cell_flux > 0, "display mapping differs", problems);
    req(["atmosphere", "correction", "residual"].every((k) => d.piston_removed_m[k].length === indices.length && d.clipped_fraction[k].length === indices.length),
      "display piston/clipping records do not cover the transported frames", problems);
    const f = run.final_average;
    req(f.sample_count === n - burn && sameArray(f.window, [burn, n]), "final average is not the completed window", problems);
    req(run.checks?.all_passed === true, "the run's own numerical checks did not all pass", problems);
  } catch (error) {
    problems.push(`run record is incomplete: ${error.message}`);
  }
  return problems;
}

export function comparisonClass(reference, candidate) {
  const changed = PHYSICAL_PARAMETER_NAMES.filter((name) => reference[name] !== candidate[name]);
  const atmosphere = changed.filter((name) => ATMOSPHERE_PARAMETERS.includes(name));
  const calibration = changed.filter((name) => CALIBRATION_PARAMETERS.includes(name));
  let kind; let text;
  if (changed.includes("seed")) { kind = "different_realization"; text = "different random realization (new seed): not a paired comparison"; }
  else if (atmosphere.length) { kind = "different_physical_atmosphere"; text = `different physical atmosphere (${atmosphere.join(", ")} changed; same seed and random draws): not a paired comparison`; }
  else if (changed.includes("n_frames")) { kind = "different_time_grid"; text = "different time grid (frame count changed): not a paired comparison"; }
  else if (changed.includes("burn_in")) { kind = "different_analysis_window"; text = "different analysis window (burn_in changed): the summaries cover different frames, so this is not a paired comparison even where the atmosphere samples match"; }
  else if (!changed.length) { kind = "identical_configuration"; text = "identical physical configuration (replay)"; }
  else { kind = "same_atmosphere_expected"; text = `same atmosphere expected (${changed.join(", ")} changed); paired only if every atmosphere sample digest and frame time match`; }
  return { changed, kind, text, calibrationRebuilt: calibration.length > 0, calibrationChanges: calibration };
}

export function pairingVerdict(referenceRun, candidateRun) {
  const expected = comparisonClass(referenceRun.effective.parameters, candidateRun.effective.parameters);
  const a = referenceRun.per_frame; const b = candidateRun.per_frame;
  const timesEqual = sameArray(a.time_s, b.time_s);
  const common = Math.min(a.atmosphere_sha256.length, b.atmosphere_sha256.length);
  let matching = 0;
  for (let i = 0; i < common; i += 1) if (a.atmosphere_sha256[i] === b.atmosphere_sha256[i]) matching += 1;
  const paired = ["same_atmosphere_expected", "identical_configuration"].includes(expected.kind) && timesEqual
    && a.atmosphere_sha256.length === b.atmosphere_sha256.length && matching === a.atmosphere_sha256.length;
  return { expected, timesEqual, framesCompared: common, matching, paired };
}

// Python's float repr (json.dumps of a float): shortest round-trip digits, with
// ".0" for integral values and the exponent form below 1e-4 or from 1e16 up.
export function pythonFloat(x) {
  if (!Number.isFinite(x)) throw new Error("non-finite number");
  if (x === 0) return Object.is(x, -0) ? "-0.0" : "0.0";
  const [mantissa, exponentText] = x.toExponential().split("e");
  const exponent = Number(exponentText);
  const negative = mantissa.startsWith("-");
  const digits = mantissa.replace("-", "").replace(".", "");
  let text;
  if (exponent < -4 || exponent >= 16) {
    text = `${digits[0]}${digits.length > 1 ? `.${digits.slice(1)}` : ""}e${exponent < 0 ? "-" : "+"}${String(Math.abs(exponent)).padStart(2, "0")}`;
  } else if (exponent >= 0) {
    const whole = digits.length > exponent + 1 ? digits.slice(0, exponent + 1) : digits.padEnd(exponent + 1, "0");
    const fraction = digits.length > exponent + 1 ? digits.slice(exponent + 1) : "0";
    text = `${whole}.${fraction}`;
  } else {
    text = `0.${"0".repeat(-exponent - 1)}${digits}`;
  }
  return negative ? `-${text}` : text;
}

// SHA-256 of the canonical JSON the service hashes (contract.physical_identity).
export async function physicalIdentity(params) {
  const entries = PHYSICAL_PARAMETER_NAMES.slice().sort().map((name) => {
    const value = params[name];
    return `"${name}":${INTEGER_PARAMETERS.has(name) ? String(value) : pythonFloat(value)}`;
  });
  const text = `{"api":"${API_VERSION}","parameters":{${entries.join(",")}},"profile":"${PROFILE}"}`;
  const digest = await globalThis.crypto.subtle.digest("SHA-256", new TextEncoder().encode(text));
  return Array.from(new Uint8Array(digest), (b) => b.toString(16).padStart(2, "0")).join("");
}

// Typed views of the verified binary files, one object per transported frame.
export function frameViews(buffer, run) {
  const out = [];
  const count = run.transported.indices.length;
  require32(buffer, 4 * FLOATS_PER_FRAME * count);
  let offset = 0;
  for (let i = 0; i < count; i += 1) {
    const frame = {};
    for (const [name, shape] of FRAME_BLOCKS) {
      const size = shape[0] * shape[1];
      frame[name] = new Float32Array(buffer, offset * 4, size);
      offset += size;
    }
    out.push(frame);
  }
  return out;
}

export function finalViews(buffer) {
  require32(buffer, 4 * FINAL_FLOATS);
  const out = {}; let offset = 0;
  for (const [name, shape] of FINAL_BLOCKS) { const size = shape[0] * shape[1]; out[name] = new Float32Array(buffer, offset * 4, size); offset += size; }
  return out;
}

function require32(buffer, bytes) {
  if (!(buffer instanceof ArrayBuffer) || buffer.byteLength !== bytes) throw new Error(`binary member has ${buffer?.byteLength} bytes, expected ${bytes}`);
  // Float32Array uses the platform byte order; the files are little endian.
  if (new Uint8Array(new Uint16Array([1]).buffer)[0] !== 1) throw new Error("this platform is big-endian; the little-endian float32 files cannot be viewed directly");
}
