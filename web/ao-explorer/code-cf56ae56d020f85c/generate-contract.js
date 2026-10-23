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
const isHex64 = (v) => typeof v === "string" && /^[0-9a-f]{64}$/.test(v);

export function validateInfo(info) {
  const problems = [];
  if (!info || typeof info !== "object") return ["the service description is not an object"];
  req(info.schema === SCHEMAS.info, `unsupported service description schema ${JSON.stringify(info.schema)}`, problems);
  req(info.api === API_VERSION, `the service speaks ${JSON.stringify(info.api)}, this page needs ${API_VERSION}`, problems);
  if (problems.length) return problems;
  for (const [key, value] of Object.entries(SCHEMAS)) if (key !== "info") req(info.schemas?.[key] === value, `the service's ${key} schema is ${JSON.stringify(info.schemas?.[key])}, not ${value}`, problems);
  req(info.profile === PROFILE && info.fixed?.science_wavelength_m === SCIENCE_WAVELENGTH_M && info.fixed?.wfs_wavelength_m === WFS_WAVELENGTH_M,
    "the service's fixed scope (profile or wavelengths) differs from the one this page supports", problems);
  const names = (info.parameters || []).map((p) => p.name);
  req(sameArray(names, PARAMETER_NAMES), `the service's parameters ${JSON.stringify(names)} differ from this page's`, problems);
  for (const p of info.parameters || []) {
    req((p.kind === "integer") === INTEGER_PARAMETERS.has(p.name) && Number.isFinite(p.minimum) && Number.isFinite(p.maximum) && p.minimum <= p.maximum,
      `parameter ${p.name} has an unsupported kind or range`, problems);
  }
  const d = info.display || {};
  req(Array.isArray(d.opd_lut_rgb_hex) && d.opd_lut_rgb_hex.length === 256 && Array.isArray(d.intensity_lut_rgb_hex) && d.intensity_lut_rgb_hex.length === 256,
    "the service's display tables are incomplete", problems);
  req(d.phase_rule === PHASE_RULE && d.phase_wrapping === PHASE_WRAPPING && sameArray(d.phase_display_wavelengths_m, PHASE_DISPLAY_WAVELENGTHS_M),
    "the service's phase-display convention differs", problems);
  req(sameArray((info.frame_blocks || []).map((b) => [b.name, b.shape, b.unit]), FRAME_BLOCKS)
    && sameArray((info.final_blocks || []).map((b) => [b.name, b.shape, b.unit]), FINAL_BLOCKS), "the service's array layout differs", problems);
  const h = info.horizon || {};
  req(Number.isFinite(h.delta_m) && h.delta_m > 0 && Number.isFinite(h.travel_budget_px) && h.frame_rate_hz === FRAME_RATE_HZ, "the service's horizon description is incomplete", problems);
  return problems;
}

export function validateStatus(status, { runId } = {}) {
  const problems = [];
  if (!status || typeof status !== "object") return ["job status is not an object"];
  req(status.schema === SCHEMAS.status && status.api === API_VERSION, `unsupported job status schema ${JSON.stringify(status.schema)}`, problems);
  req(JOB_STATES.includes(status.state), `unknown job state ${JSON.stringify(status.state)}`, problems);
  if (runId) req(status.run_id === runId, `the status names run ${status.run_id}, not ${runId}`, problems);
  return problems;
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
    if (runId) req(run.run_id === runId, `the record names run ${run.run_id}, not ${runId}`, problems);
    const params = run.effective.parameters;
    problems.push(...validateParameterValues(params));
    if (problems.length) return problems;
    req(windConsistent(params.wind_m_per_s, params.wind_speed_m_per_s, params.wind_direction_deg), "wind vector does not follow from speed and direction", problems);
    req(isHex64(run.effective.physical_identity), "the run has no physical identity", problems);
    req(run.effective.fixed?.profile === PROFILE && run.effective.fixed?.science_wavelength_m === SCIENCE_WAVELENGTH_M, "fixed scope differs from API v1", problems);
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
    && a.atmosphere_sha256.length === b.atmosphere_sha256.length && matching === a.atmosphere_sha256.length
    && referenceRun.effective.parameters.burn_in === candidateRun.effective.parameters.burn_in;
  return { expected, timesEqual, framesCompared: common, matching, paired };
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
