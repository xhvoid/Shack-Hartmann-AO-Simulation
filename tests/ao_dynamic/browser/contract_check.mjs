// Node check of the page's generated-run contract (generate-contract.js)
// against real fixture records written by the pytest wrapper.
// Usage: node contract_check.mjs <code-dir> <fixture.json>
import { readFileSync } from "node:fs";
import { pathToFileURL } from "node:url";
import assert from "node:assert/strict";

const [codeDir, fixturePath] = process.argv.slice(2);
const C = await import(pathToFileURL(`${codeDir}/generate-contract.js`).href);
const fixture = JSON.parse(readFileSync(fixturePath, "utf8"));
const clone = (v) => structuredClone(v);
const results = [];

// A real run passes, with and without the requested parameters.
assert.deepEqual(C.validateRun(fixture.run), []);
assert.deepEqual(C.validateRun(fixture.run, { expectedParameters: fixture.expected, runId: fixture.run.run_id }), []);
assert.ok(C.validateRun(fixture.run, { runId: "run-other" }).some((p) => p.includes("names run")));
assert.ok(C.validateRun(fixture.run, { expectedParameters: { ...fixture.expected, controller_gain: 0.3 } }).some((p) => p.includes("controller_gain")));

// Coherent metadata changes are refused by semantics (no digest is involved).
const mutations = {
  "science wavelength": (r) => { r.conventions.science_wavelength_m = 2.2e-6; },
  "pre-update residual": (r) => { r.conventions.residual_field = "post_update_residual_opd_m"; },
  "OPD unit": (r) => { r.conventions.opd_unit = "nm"; },
  "PSF normalization": (r) => { r.conventions.psf_normalization = "peak"; },
  "phase convention": (r) => { r.conventions.phase_wrapping = "wrapped to (-pi, pi]"; },
  "analysis window": (r) => { r.analysis_window.samples_used -= 1; },
  "frame times": (r) => { r.time.time_s[3] = 0.0031; },
  "every eligible frame": (r) => { r.transported.running_sample_count[r.transported.running_sample_count.length - 1] -= 1; },
  "scene": (r) => { r.scene.sources[1].weight = 0.5; },
  "frames.bin layout": (r) => { r.arrays.frames.blocks[0].unit = "nm OPD"; },
  "delays": (r) => { r.conventions.wfs_visible_delay_frames = r.conventions.queued_latency_frames; },
  "held saturation": (r) => { r.per_frame.saturation_fraction_held[2] = 0.5; },
  "numerical checks": (r) => { r.checks.all_passed = false; },
  "unsupported API": (r) => { r.api = "ao-dynamic.api.v0"; },
  "burn-in": (r) => { r.per_frame.running_average_peak_strehl_corrected[0] = 0.5; },
  "axis layout": (r) => { r.conventions.axis_layout = "x_rows_y_columns"; },
  "wind vector": (r) => { r.effective.parameters.wind_m_per_s = [0, 10]; },
  "frames.bin size": (r) => { r.arrays.frames.bytes += 4; },
};
for (const [needle, mutate] of Object.entries(mutations)) {
  const run = clone(fixture.run); mutate(run);
  const problems = C.validateRun(run);
  assert.ok(problems.some((p) => p.includes(needle)), `${needle}: ${JSON.stringify(problems)}`);
  results.push(needle);
}

// Service description.
assert.deepEqual(C.validateInfo(fixture.info), []);
for (const [needle, mutate] of Object.entries({
  "needs ao-dynamic.api.v1": (i) => { i.api = "ao-dynamic.api.v2"; },
  "fixed scope": (i) => { i.fixed.science_wavelength_m = 2.2e-6; },
  "parameters": (i) => { i.parameters.pop(); },
  "display tables": (i) => { i.display.opd_lut_rgb_hex.pop(); },
  "array layout": (i) => { i.frame_blocks[3].shape = [128, 128]; },
  "phase-display convention": (i) => { i.display.phase_rule = "phase_rad = OPD_nm"; },
})) {
  const info = clone(fixture.info); mutate(info);
  assert.ok(C.validateInfo(info).some((p) => p.includes(needle)), `info ${needle}: ${JSON.stringify(C.validateInfo(info))}`);
}

// Pairing: replay (stride change) is paired; an AO change with identical digests is paired;
// a new seed, an r0 change or one differing digest is not.
const a = fixture.run; const b = fixture.run_stride5;
assert.equal(C.pairingVerdict(a, b).paired, true);
assert.equal(C.pairingVerdict(a, b).expected.kind, "identical_configuration");
const gain = clone(b); gain.effective.parameters.controller_gain = 0.3;
assert.equal(C.pairingVerdict(a, gain).paired, true);
assert.equal(C.pairingVerdict(a, gain).expected.calibrationRebuilt, false);
const mag = clone(b); mag.effective.parameters.guide_ab_magnitude = 8.5;
assert.equal(C.pairingVerdict(a, mag).expected.calibrationRebuilt, true);
const seed = clone(b); seed.effective.parameters.seed = 7;
assert.equal(C.pairingVerdict(a, seed).paired, false);
const r0 = clone(b); r0.effective.parameters.r0_m = 0.1;
assert.equal(C.pairingVerdict(a, r0).expected.kind, "different_physical_atmosphere");
assert.equal(C.pairingVerdict(a, r0).paired, false);
const digest = clone(gain); digest.per_frame.atmosphere_sha256[5] = "0".repeat(64);
assert.equal(C.pairingVerdict(a, digest).paired, false);

// Parity with Python: wind vectors, replay indices, phase rule and display codes.
for (const [speed, dir, vx, vy] of fixture.wind) {
  assert.ok(C.windConsistent([vx, vy], speed, dir), `wind ${speed} ${dir}`);
  if (dir % 90 === 0) assert.deepEqual(C.windVector(speed, dir), [vx, vy]);
}
for (const [n, s, idx] of fixture.transported) assert.deepEqual(C.transportedIndices(n, s), idx);
for (const [opd, lambda, phase] of fixture.phase) assert.equal(C.opdToPhaseRad(opd, lambda), phase);
for (const [v, limit, code] of fixture.opd_codes) assert.equal(C.opdCode(v, limit), code, `opd ${v}`);
for (const [v, peak, code] of fixture.psf_codes) assert.equal(C.intensityCode(v, peak, 4), code, `psf ${v}`);

// Binary views follow the recorded layout.
const frames = C.frameViews(new ArrayBuffer(4 * C.FLOATS_PER_FRAME * a.transported.indices.length), a);
assert.equal(frames.length, a.transported.indices.length);
assert.equal(frames[0].psf_corrected.length, 64 * 64);
assert.throws(() => C.frameViews(new ArrayBuffer(8), a));
console.log(JSON.stringify({ ok: true, refused_mutations: results.length }));
