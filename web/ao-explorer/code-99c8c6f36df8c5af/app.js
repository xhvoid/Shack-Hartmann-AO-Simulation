// AO Simulation Explorer: 2 m experiment controller.
//
// Frame counts, the analysis window, the displayed frame subset and the
// playback durations come from the dataset's own metadata (manifest
// time_domain and playback) and are checked for consistency before use; no
// trajectory length is assumed here.  Position, play/pause, duration, view
// mode and loop are not kept here: playback.js holds them for this panel and
// the galaxy panel together, and both render from its snapshots.
// The browser only selects and replays validated, recorded data.  It never
// propagates light, runs a control loop, draws noise, interpolates between
// cases or derives a scientific metric from a coloured image.  Every member
// is fetched through integrity.js (length + SHA-256 against its defining
// JSON) and every case is semantically validated before any of it reaches
// the page; a case is then installed in one step, so labels, images,
// metrics and downloads always belong to the same case.
//
// This module is served from a content-addressed build directory
// (code-<build>/, scripts/ao_explorer/site_build.py) and refuses a dataset
// entry published with another build, so a cached older page can never run
// against newer data (external review ER-F05).

import { BundleError, fetchVerified, fetchVerifiedImage, fetchVerifiedJson, isFiniteOrNull, require } from "./integrity.js";
import { PALETTE, lineChart, redrawWhenResized } from "./charts.js";
import { renderResults, renderProjectEvidence, initNgs22 } from "./results.js";
import { initNgsReplay, initNgsControl } from "./ngs-replay.js";
import { initReplay42 } from "./replay42.js";
import { initC1Noise } from "./c1-noise.js";
import { initDmStroke } from "./dm-stroke.js";
import { initApertureComparison } from "./aperture.js";
import { initGalaxy, showGalaxyCase } from "./galaxy.js";
import * as playback from "./playback.js";

const SUPPORTED_MANIFEST = "ao-explorer.manifest.v2";
const SUPPORTED_ENTRY = "ao-explorer.entry.v1";
const FRAME_PERIOD_S = 0.001;
const CACHE_LIMIT = 2;
const CODE_BUILD = (new URL(".", import.meta.url).pathname.match(/\/code-([0-9a-f]{16})\/$/) || [])[1] || null;

// The only scientific semantics this page supports; a case whose metadata
// differs is refused before anything is shown (external review ER-F04).
const SCIENCE_WAVELENGTH_M = 1.65e-6;
const IMAGE_UNITS = {
  atmosphere: "nm OPD", correction: "nm OPD-equivalent (not mirror surface height)", residual: "nm OPD",
  psf_uncorrected: "log10 relative intensity", psf_corrected: "log10 relative intensity",
};
const PARENT_FIELDS = { corrected: "pre_update_residual_opd_m", uncorrected: "atmosphere_opd_m (zero-DM optical counterfactual)" };
const PARENT_NORMALIZATION = "unit total flux over the complete uncropped propagator grid";
// A recorded wavelength for a message; anything that is not a number is shown
// as recorded and said to be no number (round-10 review, R10-F03).
const wavelengthLabel = (m) => (typeof m !== "number" ? `${JSON.stringify(m)} (not a number)` : m < 1e-6 ? `${(m * 1e9).toFixed(1)} nm` : `${(m * 1e6).toFixed(3)} µm`);
// Labels for two compared wavelengths; when the rounded labels coincide but the
// values differ, the exact recorded values are added (round-9 review, R9-F01).
function wavelengthPair(a, b) {
  const [la, lb] = [wavelengthLabel(a), wavelengthLabel(b)];
  const exact = (m) => (typeof m === "number" ? `${m.toExponential()} m` : JSON.stringify(m));
  return la === lb && a !== b ? [`${la} (${exact(a)})`, `${lb} (${exact(b)})`] : [la, lb];
}
const PER_FRAME_SERIES = ["atmosphere_rms_nm", "residual_rms_nm", "peak_strehl_uncorrected", "peak_strehl_corrected", "valid_measurement_fraction", "valid_subaperture_fraction", "dm_saturation_fraction"];

const $ = (id) => document.getElementById(id);
const state = {
  manifest: null, manifestUrl: null, display: null, scene: null, sceneUrl: null, sceneImage: null,
  diagnostics: null, blocks: null, case: null, rms: null,
  generation: 0, controller: null, cache: new Map(), objectUrls: [],
  resultsLoaded: false, resultsLoading: false,
};
const pb = () => playback.snapshot();

// The validated time domain of the installed dataset (manifest.time_domain).
const td = () => state.manifest.time_domain;
const FRAMES = () => td().frames;
const START = () => td().analysis_window[0];
const SHOWN = () => td().display_count;
const COUNT = () => td().analysis_count;
const windowText = () => `frames ${START()}–${FRAMES() - 1}`;

// ---------------------------------------------------------------------------
// Entry and manifest

function entryUrl() {
  const params = new URLSearchParams(location.search);
  const override = params.get("entry");
  if (override !== null) {
    if (/^[a-z][a-z0-9+.-]*:/i.test(override) || override.startsWith("/") || override.includes("//")) {
      throw new BundleError("the entry override must be a relative path inside this site");
    }
    return new URL(override, location.href);
  }
  return new URL("../data/current.json", import.meta.url);
}

async function loadEntry() {
  const url = entryUrl();
  let response;
  try { response = await fetch(url, { cache: "no-store" }); } catch (error) { throw new BundleError(`could not fetch the dataset entry: ${error.message}`); }
  if (!response.ok) throw new BundleError(`could not fetch the dataset entry (HTTP ${response.status})`);
  let entry;
  try { entry = await response.json(); } catch (error) { throw new BundleError("the dataset entry is not valid JSON"); }
  require(entry.schema === SUPPORTED_ENTRY, `unsupported dataset entry schema ${entry.schema}`);
  require(CODE_BUILD !== null && entry.code_build === CODE_BUILD,
    `this page's code (build ${CODE_BUILD ?? "unknown"}) does not match the published dataset entry (build ${entry.code_build ?? "none"}); reload the page to load the matching code`);
  const ref = { href: entry.manifest, bytes: entry.manifest_bytes, sha256: entry.manifest_sha256, media_type: "application/json" };
  const { url: manifestUrl, value: manifest } = await fetchVerifiedJson(ref, url);
  validateManifest(manifest, entry);
  return { manifest, manifestUrl, entry, entryUrl: url };
}

function validateTimeDomain(t, p) {
  require(t && Number.isInteger(t.frames) && t.frames > 1, "the manifest records no trajectory length");
  require(t.frame_rate_hz === 1000 && Math.abs(t.frame_period_s - FRAME_PERIOD_S) < 1e-15, "unexpected frame rate");
  require(t.frame_indices[0] === 0 && t.frame_indices[1] === t.frames - 1, "the frame index range does not match the trajectory length");
  require(t.physical_interval_s[0] === 0 && Math.abs(t.physical_interval_s[1] - t.frames * FRAME_PERIOD_S) < 1e-12, "the physical interval does not match the frames");
  const [start, stop] = t.analysis_window;
  require(Number.isInteger(start) && start > 0 && stop === t.frames && t.analysis_count === stop - start && t.startup_exclusion_frames === start && t.burn_in_frames === start, "the analysis window is not [startup exclusion, frames)");
  const idx = t.display_indices;
  require(Array.isArray(idx) && idx.length === t.display_count && idx.length > 1, "the displayed frame list is incomplete");
  for (let i = 0; i < idx.length; i += 1) {
    require(Number.isInteger(idx[i]) && idx[i] >= 0 && idx[i] < t.frames, "a displayed frame index is out of range");
    if (i) require(idx[i] > idx[i - 1], "displayed frame indices are not unique and ordered");
    require(Math.abs(t.display_times_s[i] - idx[i] * FRAME_PERIOD_S) < 1e-12, "a displayed timestamp does not match its frame index");
  }
  require(idx[0] === 0 && idx.includes(start) && idx[idx.length - 1] === t.frames - 1, "the displayed frames must include the first frame, the start of the analysis window and the last frame");
  require(p && p.interval_s[0] === t.physical_interval_s[0] && p.interval_s[1] === t.physical_interval_s[1], "the playback interval is not the physical interval");
  require(Array.isArray(p.durations_s) && p.durations_s.length > 0 && p.durations_s.every((d) => Number.isFinite(d) && d > 0) && p.durations_s.includes(p.default_duration_s) && p.durations_s.includes(p.reduced_motion_duration_s), "unsupported playback durations");
  require(p.interpolation === "none", "playback must not interpolate");
}

function validateManifest(m, entry) {
  require(m.schema === SUPPORTED_MANIFEST, `unsupported manifest schema ${m.schema}`);
  validateTimeDomain(m.time_domain, m.playback);
  require(m.dataset_id === entry.dataset_id, "the manifest and its entry name different datasets");
  require(m.cases && typeof m.cases === "object", "the manifest lists no cases");
  require(m.cases[m.default_case], `the default case ${m.default_case} is missing`);
  for (const group of m.groups) for (const node of group.nodes) require(m.cases[node], `group ${group.id} names unknown case ${node}`);
  for (const key of ["scene", "display", "diagnostics", "results", "blocks"]) require(m[key] && m[key].sha256, `the manifest has no ${key} member`);
  for (const [id, item] of Object.entries(m.cases)) {
    require(item.case && item.case.sha256 && item.case.media_type === "application/json", `case ${id} has no verified reference`);
    require(m.summaries && m.summaries[id], `case ${id} has no recorded summary`);
  }
}

// ---------------------------------------------------------------------------
// RMS diagnostics (an additive scalar derivative named by the entry)
//
// The residual RMS after tip/tilt removal of every saved pre-update residual
// map (scripts/ao_explorer/rms_diagnostics.py).  It is loaded with each case,
// so a case and its diagnostics are installed together, and it is bound to
// the exact metrics member of that case.  It is optional: if a case's file
// cannot be fetched or verified, that case is installed with its verified
// core data and the diagnostic marked unavailable on that case only.

const RMS_ENTRY = "ao-explorer.rms-diagnostics-entry.v1";
const RMS_MANIFEST = "ao-explorer.rms-diagnostics-manifest.v1";
const RMS_CASE = "ao-explorer.rms-diagnostics.v1";
const RMS_UNITS = "nm OPD";

async function loadDiagnostics(entry, entryUrl) {
  if (!entry.diagnostics) return null;
  require(entry.diagnostics.schema === RMS_ENTRY, `unsupported RMS-diagnostics entry ${entry.diagnostics.schema}`);
  const ref = { href: entry.diagnostics.manifest, bytes: entry.diagnostics.manifest_bytes, sha256: entry.diagnostics.manifest_sha256, media_type: "application/json" };
  const { url, value: m } = await fetchVerifiedJson(ref, entryUrl);
  require(m.schema === RMS_MANIFEST && m.derived_id === entry.diagnostics.derived_id, "the RMS-diagnostics manifest does not match its entry");
  require(m.parent.dataset_id === entry.dataset_id && m.parent.manifest_sha256 === entry.manifest_sha256, "the RMS diagnostics were derived from another dataset");
  require(m.definition.units === RMS_UNITS, `RMS diagnostics in ${m.definition.units}, not ${RMS_UNITS}`);
  const t = m.time_domain; const d = td();
  for (const key of ["frames", "frame_period_s", "analysis_count"]) require(t[key] === d[key], `the RMS diagnostics' ${key} differs from the dataset's`);
  for (const key of ["physical_interval_s", "analysis_window"]) require(t[key].join() === d[key].join(), `the RMS diagnostics' ${key} differs from the dataset's`);
  const ids = Object.keys(state.manifest.cases);
  require(Object.keys(m.cases).length === ids.length && ids.every((id) => m.cases[id]?.diagnostics && m.window_means[id]), "the RMS diagnostics do not cover exactly the recorded cases");
  return { manifest: m, url };
}

// The arithmetic mean of a per-frame series over the analysis window, or null
// when a frame in the window has no value; never a mean of a partial window.
function windowMean(values) {
  const part = values.slice(START(), FRAMES());
  return part.length === COUNT() && part.every((v) => typeof v === "number" && Number.isFinite(v)) ? part.reduce((sum, v) => sum + v, 0) / COUNT() : null;
}

function validateRms(id, r, c, metrics) {
  require(r.schema === RMS_CASE && r.case_id === id, `RMS diagnostics do not belong to case ${id}`);
  require(r.units === RMS_UNITS && r.frames === FRAMES() && Math.abs(r.frame_period_s - FRAME_PERIOD_S) < 1e-15, `case ${id}: RMS diagnostics have another unit or time domain`);
  const v = r.detilted_residual_rms_nm.values;
  require(Array.isArray(v) && v.length === FRAMES() && v.every((x) => typeof x === "number" && Number.isFinite(x) && x >= 0) && Object.keys(r.detilted_residual_rms_nm.null_reasons).length === 0, `case ${id}: the detilted RMS series is incomplete or not finite`);
  require(r.companions.metrics_sha256 === c.members.metrics.sha256, `case ${id}: the RMS diagnostics accompany another metrics file`);
  const w = r.window_means; const pf = metrics.per_frame;
  require(w.window.join() === td().analysis_window.join() && w.count === COUNT(), `case ${id}: the RMS window means do not cover the analysis window`);
  for (const [key, values] of [["atmosphere_rms_nm", pf.atmosphere_rms_nm.values], ["residual_rms_nm", pf.residual_rms_nm.values], ["detilted_residual_rms_nm", v]]) {
    const mean = windowMean(values);
    require(mean !== null && Math.abs(w[key] - mean) <= 1e-9 * Math.max(1, Math.abs(w[key])), `case ${id}: the recorded window mean of ${key} differs from its per-frame values`);
  }
}

// ---------------------------------------------------------------------------
// Case loading and validation

function validateCase(id, c, metrics, observation) {
  require(c.schema === "ao-explorer.case.v2", `case ${id}: unsupported schema ${c.schema}`);
  require(c.case_id === id, `case file names ${c.case_id}, expected ${id}`);
  const t = c.time_domain; const d = td();
  for (const key of ["frames", "frame_period_s", "startup_exclusion_frames", "burn_in_frames", "analysis_count", "display_count"]) require(t[key] === d[key], `case ${id}: ${key} differs from the dataset's time domain`);
  require(t.analysis_window.join() === d.analysis_window.join() && t.physical_interval_s.join() === d.physical_interval_s.join(), `case ${id}: the analysis window or physical interval differs from the dataset's`);
  const idx = t.movie_indices;
  require(idx.join() === d.display_indices.join() && t.movie_times_s.join() === d.display_times_s.join(), `case ${id}: displayed frames differ from the dataset's displayed frames`);
  const FRAMES = d.frames; const BURN_IN = d.analysis_window[0]; const SHOWN = d.display_count;
  for (const key of ["atmosphere", "correction", "residual", "psf_uncorrected", "psf_corrected"]) {
    const image = c.images[key];
    require(image && image.atlas && image.atlas.media_type === "image/png", `case ${id}: missing ${key} atlas`);
    require(image.rectangles_xywh.length === SHOWN && image.frame_indices.join() === idx.join(), `case ${id}: ${key} atlas does not cover the displayed frames`);
  }
  for (const [key, unit] of Object.entries(IMAGE_UNITS)) {
    require(c.images[key].unit === unit, `case ${id}: ${key} unit “${c.images[key].unit}” is not the supported “${unit}”`);
  }
  const psfScale = state.display.psf;
  for (const key of ["psf_uncorrected", "psf_corrected", "psf_average_uncorrected", "psf_average_corrected"]) {
    const s = c.images[key].scale;
    require(s && s.mapping === psfScale.mapping && s.ideal_peak_cell_flux === psfScale.ideal_peak_cell_flux && s.normalization === psfScale.normalization, `case ${id}: ${key} intensity scale differs from the common display scale`);
  }
  const [caseWavelength, supported] = wavelengthPair(c.effective_parameters.explorer_science_wavelength_m, SCIENCE_WAVELENGTH_M);
  require(c.effective_parameters.explorer_science_wavelength_m === SCIENCE_WAVELENGTH_M, `case ${id}: science wavelength ${caseWavelength} is not ${supported}`);
  for (const key of ["atmosphere", "correction", "residual"]) {
    const piston = c.images[key].display_piston_nm;
    require(Array.isArray(piston) && piston.length === SHOWN && piston.every((v) => Number.isFinite(v)), `case ${id}: ${key} display piston record is incomplete`);
    const lim = c.images[key].color_limits_nm;
    require(lim[0] === -lim[1] && lim[1] > 0, `case ${id}: OPD colour limits must be symmetric`);
    require(lim[1] === c.images.atmosphere.color_limits_nm[1], `case ${id}: OPD panels must share colour limits`);
    require(Math.abs(lim[1] - state.display.opd.limit_m * 1e9) < 1e-6, `case ${id}: OPD colour limits differ from the common display limit`);
  }
  for (const key of ["psf_average_uncorrected", "psf_average_corrected"]) {
    require(c.images[key] && c.images[key].sample_count === FRAMES - BURN_IN && c.images[key].window_frames.join() === `${BURN_IN},${FRAMES}`, `case ${id}: ${key} is not the ${FRAMES - BURN_IN}-sample average of frames ${BURN_IN}–${FRAMES - 1}`);
  }
  require(metrics.schema === "ao-explorer.metrics.v2" && metrics.case_id === id, `metrics do not belong to case ${id}`);
  const pf = metrics.per_frame;
  require(pf.frame_index.length === FRAMES && pf.frame_index.every((v, i) => v === i), `case ${id}: metrics must cover frames 0–${FRAMES - 1} in order`);
  require(pf.time_s.every((v, i) => Math.abs(v - i / 1000) < 1e-12), `case ${id}: metric timestamps do not match frames`);
  for (const key of PER_FRAME_SERIES) {
    require(pf[key] && pf[key].values.length === FRAMES && pf[key].values.every(isFiniteOrNull), `case ${id}: ${key} is incomplete or not finite`);
    // Every missing value has exactly one recorded, non-empty reason.
    const reasons = pf[key].null_reasons || {};
    const nulls = pf[key].values.flatMap((v, i) => (v === null ? [String(i)] : []));
    require(nulls.length === Object.keys(reasons).length && nulls.every((i) => typeof reasons[i] === "string" && reasons[i].trim() !== ""), `case ${id}: ${key} has a missing value without a recorded reason`);
  }
  require(pf.reconstruction_usable.length === FRAMES, `case ${id}: usability is incomplete`);
  require(metrics.summary.window[0] === BURN_IN && metrics.summary.window[1] === FRAMES && metrics.summary.sample_count === FRAMES - BURN_IN, `case ${id}: summary window is not [${BURN_IN}, ${FRAMES})`);
  for (const key of ["atmosphere", "correction", "residual"]) require(metrics.display_clipping[key]?.length === SHOWN, `case ${id}: ${key} clipping record is incomplete`);
  require(observation.schema === "ao-explorer.observation.v2" && observation.case_id === id, `observation does not belong to case ${id}`);
  require(observation.scene_id === state.scene.scene.scene_id && observation.scene_grid_id === state.scene.scene.grid_id, `case ${id}: observation scene differs from the shared scene`);
  require(observation.window[0] === BURN_IN && observation.window[1] === FRAMES && observation.sample_count === FRAMES - BURN_IN, `case ${id}: observation is not the [${BURN_IN}, ${FRAMES}) average`);
  for (const role of ["uncorrected", "corrected"]) {
    const r = observation.roles[role];
    require(r && r.parent.sample_count === FRAMES - BURN_IN && r.parent.window.join() === `${BURN_IN},${FRAMES}`, `case ${id}: ${role} observation parent is not the ${FRAMES - BURN_IN}-sample mean`);
    require(r.parent.weights === "equal" && typeof r.parent.array_sha256 === "string" && r.parent.array_sha256.length === 64, `case ${id}: ${role} observation parent identity is incomplete`);
    require(r.parent.role === role, `case ${id}: observation parent role mismatch`);
    require(Math.abs(r.full_flux - r.expected_full_flux) < 1e-12, `case ${id}: ${role} observation flux does not equal scene x kernel flux`);
    const p = r.parent; const scene = state.scene.scene;
    const [parentWavelength, sceneWavelength] = wavelengthPair(p.wavelength_m, scene.wavelength_m);
    require(p.wavelength_m === SCIENCE_WAVELENGTH_M && p.wavelength_m === scene.wavelength_m, `case ${id}: ${role} observation parent is at ${parentWavelength}, not the scene's ${sceneWavelength}`);
    require(p.field === PARENT_FIELDS[role], `case ${id}: ${role} observation parent field “${p.field}” is not “${PARENT_FIELDS[role]}”`);
    require(p.normalization === PARENT_NORMALIZATION, `case ${id}: ${role} observation parent normalization “${p.normalization}” is not supported`);
    require(p.x_angle_rad_sha256 === scene.grid.x_angle_rad_sha256 && p.y_angle_rad_sha256 === scene.grid.y_angle_rad_sha256 && p.shape.join() === scene.grid.shape_yx.join(), `case ${id}: ${role} observation parent grid differs from the scene grid`);
    require(p.stride === 1 && p.recentering === "none" && p.coaddition === "intensity" && Math.abs(p.total_flux - 1) <= 1e-12, `case ${id}: ${role} observation parent is not a unit-flux, intensity-co-added, uncentred average`);
    require(r.display && r.display.scale && r.display.scale.mapping === psfScale.mapping && r.display.scale.ideal_peak_cell_flux === psfScale.ideal_peak_cell_flux, `case ${id}: ${role} observation display scale differs from the common display scale`);
  }
  const [pc, pu] = [observation.roles.corrected.parent, observation.roles.uncorrected.parent];
  require(pc.propagator_config_hash === pu.propagator_config_hash && pc.accumulator_config_hash === pu.accumulator_config_hash, `case ${id}: the two observation parents come from different propagators or accumulators`);
}

async function fetchCase(id, signal) {
  const manifest = state.manifest;
  const item = manifest.cases[id];
  if (!item) throw new BundleError(`case ${id} is not in this dataset (only recorded cases can be shown)`);
  const { url: caseUrl, value: c } = await fetchVerifiedJson(item.case, state.manifestUrl, { signal });
  const [metrics, observation, config, provenance, csv] = await Promise.all([
    fetchVerifiedJson(c.members.metrics, caseUrl, { signal }),
    fetchVerifiedJson(c.members.observation, caseUrl, { signal }),
    fetchVerified(c.members.config, caseUrl, { signal, expectType: "application/json" }),
    fetchVerified(c.members.provenance, caseUrl, { signal, expectType: "application/json" }),
    fetchVerified(c.members.metrics_csv, caseUrl, { signal, expectType: "text/csv" }),
  ]);
  validateCase(id, c, metrics.value, observation.value);
  // Only this optional stage may fail without failing the case; cancellation
  // always propagates, and every required member below keeps failing the load.
  let rms = null;
  let rmsError = null;
  if (state.rms) {
    try {
      const fetched = await fetchVerifiedJson(state.rms.manifest.cases[id].diagnostics, state.rms.url, { signal });
      validateRms(id, fetched.value, c, metrics.value);
      rms = fetched;
    } catch (error) {
      if (error.name === "AbortError") throw error;
      rmsError = `this case's RMS diagnostics could not be verified (${error.message})`;
    }
  } else {
    rmsError = state.rmsError ?? "this dataset entry names no RMS diagnostics";
  }
  const imageKeys = ["atmosphere", "correction", "residual", "psf_uncorrected", "psf_corrected"];
  const atlases = await Promise.all(imageKeys.map((key) => fetchVerifiedImage(c.images[key].atlas, caseUrl, { signal })));
  const averages = await Promise.all(["psf_average_uncorrected", "psf_average_corrected"].map((key) => fetchVerifiedImage(c.images[key].image, caseUrl, { signal })));
  const obsUrl = observation.url;
  const obsImages = await Promise.all(["uncorrected", "corrected"].map((role) => fetchVerified(observation.value.roles[role].display.image, obsUrl, { signal, expectType: "image/png" })));
  return {
    id, url: caseUrl, json: c, metrics: metrics.value, observation: observation.value, rms: rms ? rms.value : null, rmsError,
    files: {
      "metrics.json": metrics, "metrics.csv": csv, "config.json": config, "provenance.json": provenance, "observation.json": observation,
      ...(rms ? { "rms-diagnostics.json": rms } : {}),
    },
    provenanceText: new TextDecoder().decode(provenance.buffer),
    atlases: Object.fromEntries(imageKeys.map((key, i) => [key, atlases[i].bitmap])),
    averages: { uncorrected: averages[0].bitmap, corrected: averages[1].bitmap },
    observationPng: { uncorrected: obsImages[0].buffer, corrected: obsImages[1].buffer },
  };
}

function remember(id, data) {
  state.cache.delete(id);
  state.cache.set(id, data);
  while (state.cache.size > CACHE_LIMIT) {
    const oldest = state.cache.keys().next().value;
    if (oldest === state.case?.id) { const keep = state.cache.get(oldest); state.cache.delete(oldest); state.cache.set(oldest, keep); continue; }
    state.cache.delete(oldest);
  }
}

async function selectCase(id) {
  playback.pause();
  // Every selection supersedes every earlier one, including a return to the
  // installed case while another case is still loading (review round 1,
  // R1-F02): the pending load is aborted and its generation retired.
  const generation = ++state.generation;
  if (state.controller) { state.controller.abort(); state.controller = null; }
  if (state.case && id === state.case.id) {
    setBusy(null, false);
    hideError();
    setStatus(caseStatus(state.case));
    return;
  }
  const controller = new AbortController();
  state.controller = controller;
  setBusy(id, true);
  setStatus(`Loading case “${state.manifest.cases[id]?.label ?? id}”…`);
  hideError();
  try {
    const data = state.cache.get(id) || (await fetchCase(id, controller.signal));
    if (generation !== state.generation) return; // a newer selection won
    remember(id, data);
    commitCase(data);
    setStatus(caseStatus(data));
  } catch (error) {
    if (error.name === "AbortError" || generation !== state.generation) return;
    showError(`Could not show case “${id}”: ${error.message}`, state.case ? `Still showing the previously installed case: ${state.case.json.label}.` : "No case is installed.");
    setStatus("Case load failed.");
  } finally {
    if (generation === state.generation) setBusy(null, false);
  }
}

// The status separates the verified core case data from the optional diagnostics.
function caseStatus(data) {
  return data.rms
    ? `Showing “${data.json.label}”. All members verified against the manifest, including its RMS diagnostics.`
    : `Showing “${data.json.label}”. Core case data verified against the manifest; the optional RMS diagnostics are unavailable: ${data.rmsError}.`;
}

// ---------------------------------------------------------------------------
// Installing a case (one step)

function revokeObjectUrls() { for (const url of state.objectUrls) URL.revokeObjectURL(url); state.objectUrls = []; }
function objectUrl(buffer, type) { const url = URL.createObjectURL(new Blob([buffer], { type })); state.objectUrls.push(url); return url; }

function commitCase(data) {
  revokeObjectUrls();
  state.case = data;
  if (state.sceneImageBuffer) $("scene-img").src = objectUrl(state.sceneImageBuffer, "image/png");
  updateButtons();
  renderCaseSummary();
  renderDownloads();
  renderSummaryTable();
  renderBinary();
  renderModelNotes();
  $("provenance").textContent = data.provenanceText;
  $("observation-meta").textContent = JSON.stringify({ scene: state.scene.scene, observation: data.observation }, null, 1);
  renderBlocks();
  renderFrameTable(false);
  // The galaxy panel learns the case first (it shows a loading state until its
  // own assets for this case are verified); the shared clock then announces
  // the case to both panels, paused, at the unchanged position.
  showGalaxyCase({
    id: data.id, label: data.json.label, movieIndices: data.json.time_domain.movie_indices, movieTimes: data.json.time_domain.movie_times_s,
    meanParentSha256: { uncorrected: data.observation.roles.uncorrected.parent.array_sha256, corrected: data.observation.roles.corrected.parent.array_sha256 },
  });
  playback.setCase(data.id);
}

function updateButtons() {
  for (const button of document.querySelectorAll("#groups .node")) {
    button.setAttribute("aria-pressed", String(button.dataset.case === state.case?.id));
  }
}

function setBusy(id, busy) {
  for (const button of document.querySelectorAll("#groups .node")) button.setAttribute("aria-busy", String(busy && button.dataset.case === id));
}

// ---------------------------------------------------------------------------
// Display

const fmt = (v, d = 1) => (v === null || v === undefined || !Number.isFinite(v) ? "—" : v.toFixed(d));

const OVERRIDE_ROWS = { r0_scale: "r0", ab_magnitude: "source", gain: "controller_gain", latency_frames: "queued_latency" };

function paramRows(p, override) {
  const changedRows = new Set(Object.keys(override || {}).map((key) => OVERRIDE_ROWS[key]));
  const changed = (key) => (changedRows.has(key) ? " class=\"changed\"" : "");
  return [
    [`r0 at ${(p.r0_reference_wavelength_m * 1e9).toFixed(0)} nm`, `${p.r0_m.toFixed(4)} m`, "r0"],
    ["Outer scale", `${p.outer_scale_m} m`, "outer"],
    ["Wind", `${p.wind_m_per_s[0]} m/s towards +x`, "wind"],
    ["Guide source (WFS input)", `AB ${p.source_ab_magnitude.toFixed(1)} mag, flat in f_nu, synthetic`, "source"],
    ["Controller gain / leak", `${p.controller_gain} / ${p.controller_leak}`, "controller_gain"],
    ["Queued command delay", `${p.queued_latency_frames} frames (seen by the WFS ${p.wfs_visible_delay_frames} frames later)`, "queued_latency"],
    ["Frame rate", `${p.frame_rate_hz} Hz`, "rate"],
    ["WFS / science wavelength", `${(p.wfs_wavelength_m * 1e9).toFixed(0)} nm / ${(p.explorer_science_wavelength_m * 1e6).toFixed(2)} µm`, "wl"],
    ["Detector", `${p.camera_preset}, noise ${p.detector_noise_in_loop ? "on" : "off"}`, "det"],
  ].map(([label, value, key]) => `<li><span${changed(key)}>${label}: ${value}</span></li>`).join("");
}

function renderCaseSummary() {
  const c = state.case.json;
  const p = c.effective_parameters;
  const changes = Object.entries(c.override).map(([k, v]) => ({ r0_scale: `r0 × ${v}`, ab_magnitude: `guide AB magnitude ${v}`, gain: `gain ${v}`, latency_frames: `queued delay ${v} frames` }[k])).join(", ");
  $("case-summary").innerHTML = `<p><strong>${c.label}</strong> — ${changes ? `changed from the baseline: <span class="changed">${changes}</span>` : "the baseline: profile det_emccd_2m_synthetic@1 with the explorer overrides only"}. ${c.question}</p><details><summary>Full selected-case parameters</summary><ul class="params">${paramRows(p, c.override)}</ul></details>`;
  $("evidence-2m-title").textContent = `Parameters & evidence · 2 m ${c.label}`;
  $("e2-pupil").textContent = `${p.telescope_diameter_m} m; ${p.pupil_pixels}² pupil samples; ${p.lenslets_across} × ${p.lenslets_across} lenslet grid; ${p.actuators_across} × ${p.actuators_across} DM grid.`;
  $("e2-wavelength").textContent = `${(p.wfs_wavelength_m*1e9).toFixed(0)} nm WFS reference / ${(p.explorer_science_wavelength_m*1e6).toFixed(2)} µm science; on-axis.`;
  $("e2-atmosphere").textContent = `Single frozen-flow layer; r₀ = ${p.r0_m.toFixed(4)} m at ${(p.r0_reference_wavelength_m*1e9).toFixed(0)} nm; L₀ = ${p.outer_scale_m} m; wind ${p.wind_m_per_s[0]} m/s along +x.`;
  $("e2-source").textContent = `Synthetic AB ${p.source_ab_magnitude.toFixed(1)}, flat fν; ${p.camera_preset}; detector noise ${p.detector_noise_in_loop?'on':'off'}.`;
  $("e2-control").textContent = `${p.frame_rate_hz} Hz; gain ${p.controller_gain}; leak ${p.controller_leak}; ${p.queued_latency_frames} queued frames (${(p.queued_latency_frames/p.frame_rate_hz*1000).toFixed(1)} ms); ±${(p.dm_stroke_limit_opd_m*1e6).toFixed(1)} µm OPD.`;
  $("e2-record").textContent = `Seed ${p.root_seed}; ${p.n_steps} frames, ${(p.n_steps/p.frame_rate_hz).toFixed(3)} s; analysis [0.2, 1.0) s. One realization, no confidence interval over realizations.`;
}

function setupColorbars() {
  const d = state.display;
  for (const [id, lut] of [["cbar-opd", d.opd.lut_rgb_hex], ["cbar-psf", d.psf.lut_rgb_hex]]) {
    const canvas = $(id); const ctx = canvas.getContext("2d");
    for (let i = 0; i < 200; i += 1) { ctx.fillStyle = lut[Math.round((1 - i / 199) * (lut.length - 1))]; ctx.fillRect(0, i, canvas.width, 1); }
  }
  const L = d.opd.limit_m * 1e9;
  $("cbar-opd-labels").innerHTML = [L, L / 2, 0, -L / 2, -L].map((v, i) => `<span style="top:${i * 25}%">${v > 0 ? "+" : ""}${v.toFixed(0)} nm</span>`).join("");
  $("cbar-opd-note").textContent = `Fixed ±${L.toFixed(0)} nm for all cases and all three panels; values beyond are clipped to the end colours. Grey = outside the pupil (masked).`;
  $("cbar-psf-labels").innerHTML = [0, -1, -2, -3, -4].map((v, i) => `<span style="top:${i * 25}%">10^${v}</span>`).join("");
  $("cbar-psf-note").textContent = "Intensity relative to the ideal (zero-OPD) peak, log scale, common to every image; display crop ±1.8″.";
}

function drawTile(canvasId, bitmap, rect, smooth) {
  const canvas = $(canvasId); const ctx = canvas.getContext("2d");
  ctx.imageSmoothingEnabled = !!smooth;
  ctx.clearRect(0, 0, canvas.width, canvas.height);
  ctx.drawImage(bitmap, rect[0], rect[1], rect[2], rect[3], 0, 0, canvas.width, canvas.height);
}

function drawWhole(canvasId, bitmap) {
  const canvas = $(canvasId); const ctx = canvas.getContext("2d");
  ctx.imageSmoothingEnabled = false;
  ctx.clearRect(0, 0, canvas.width, canvas.height);
  ctx.drawImage(bitmap, 0, 0, canvas.width, canvas.height);
}

function frameIndex() { return state.case.json.time_domain.movie_indices[pb().position]; }

function renderFrame() {
  const c = state.case; if (!c) return;
  const { position, mode } = pb();
  const images = c.json.images;
  for (const key of ["atmosphere", "correction", "residual"]) drawTile(`map-${key}`, c.atlases[key], images[key].rectangles_xywh[position]);
  if (mode === "average") {
    drawWhole("psf-uncorrected", c.averages.uncorrected);
    drawWhole("psf-corrected", c.averages.corrected);
  } else {
    drawTile("psf-uncorrected", c.atlases.psf_uncorrected, images.psf_uncorrected.rectangles_xywh[position]);
    drawTile("psf-corrected", c.atlases.psf_corrected, images.psf_corrected.rectangles_xywh[position]);
  }
  const k = frameIndex();
  const pf = c.metrics.per_frame;
  const t = c.json.time_domain.movie_times_s[position];
  $("seek").value = String(position);
  $("seek").setAttribute("aria-valuetext", `displayed frame ${position + 1} of ${SHOWN()}, frame ${k}, ${ms(t)}`);
  $("frame-readout").textContent = `Frame ${k} of 0–${FRAMES() - 1} · simulated time ${ms(t)} of the recorded ${ms(0)}–${ms(td().physical_interval_s[1])} · displayed frame ${position + 1}/${SHOWN()} · ${holdText(position)}${k < START() ? ` · startup exclusion (frames 0–${START() - 1})` : ""}`;
  // DM saturation at index k belongs to the command issued at the end of
  // frame k (held from k + 1); the correction shown for frame k is the
  // command issued at frame k - 1 (review round 1, R1-F05).
  const saturation = pf.dm_saturation_fraction.values;
  const held = k === 0 ? "none recorded (initial flat command)" : fmt(saturation[k - 1], 3);
  $("current-frame").textContent = `Frame ${k}: atmosphere ${fmt(pf.atmosphere_rms_nm.values[k])} nm, residual ${fmt(pf.residual_rms_nm.values[k])} nm RMS (piston removed); instantaneous peak Strehl ${fmt(pf.peak_strehl_uncorrected.values[k], 3)} uncorrected, ${fmt(pf.peak_strehl_corrected.values[k], 3)} corrected; valid measurement fraction ${fmt(pf.valid_measurement_fraction.values[k], 3)}; reconstruction ${pf.reconstruction_usable[k] ? "usable" : "not usable"}; DM saturation of the held command (issued at frame ${k === 0 ? "start" : k - 1}) ${held}, of the command issued at this frame ${fmt(saturation[k], 3)}.`;
  for (const key of ["atmosphere", "correction", "residual"]) {
    const piston = images[key].display_piston_nm[position];
    const clip = c.metrics.display_clipping[key][position];
    const clipped = clip.clipped_low_fraction + clip.clipped_high_fraction;
    const rounded = Math.round(piston);
    $(`note-${key}`).textContent = `Frame ${k}: pupil mean ${rounded > 0 ? "+" : rounded < 0 ? "−" : ""}${Math.abs(rounded)} nm removed for display; ${clipped > 0 ? `${(clipped * 100).toFixed(2)} % of pupil samples beyond the colour limits (clipped)` : "no clipping"}.`;
  }
  renderCharts(k);
  renderRmsReadout(k, t, mode);
  updatePsfLabels();
}

// The three RMS values: of the exact displayed frame in instantaneous mode, the
// temporal means of the per-frame values over the analysis window in average
// mode.  Never the RMS of an averaged wavefront or a value inferred from a PSF.
function renderRmsReadout(k, t, mode) {
  const c = state.case; const pf = c.metrics.per_frame; const r = c.rms;
  const average = mode === "average";
  const [lo, hi] = [START() * FRAME_PERIOD_S, FRAMES() * FRAME_PERIOD_S];
  // Atmosphere and total residual RMS always come from the case's verified
  // metrics; only the third value depends on the optional diagnostics.
  const values = average
    ? [windowMean(pf.atmosphere_rms_nm.values), windowMean(pf.residual_rms_nm.values), r ? windowMean(r.detilted_residual_rms_nm.values) : null]
    : [pf.atmosphere_rms_nm.values[k], pf.residual_rms_nm.values[k], r ? r.detilted_residual_rms_nm.values[k] : null];
  const head = average
    ? `Mean of per-frame RMS, ${lo.toFixed(3)}–${hi.toFixed(3)} s, ${COUNT()} frames`
    : `Frame ${k} · frame-start time ${ms(t)} (${t.toFixed(3)} s)`;
  const rows = [
    ["Atmosphere RMS", "piston removed; tilt retained", values[0]],
    ["Total residual RMS", "piston removed; tilt retained", values[1]],
    ["Residual RMS after tip/tilt removal", r ? "piston and fitted tilt removed" : `piston and fitted tilt removed; unavailable for this case: ${c.rmsError}`, values[2]],
  ];
  const markup = `<p class="rms-head">${head}</p><dl class="rms-values">${rows.map(([name, rule, value]) => `<div><dt>${name} <span>${escapeHtml(rule)}</span></dt><dd>${value === null ? "unavailable" : `${fmt(value)} nm OPD`}</dd></div>`).join("")}</dl>`;
  for (const id of ["rms-readout", "galaxy-rms-readout"]) $(id).innerHTML = markup;
  $("galaxy-rms-mode-note").textContent = average
    ? "Temporal means of the per-frame RMS values over the analysis window, not the RMS of an averaged wavefront. Images retain their original tip/tilt."
    : "The same recorded case and frame as the PSFs, galaxy animation and chart cursor. Tip/tilt removal applies only to the third RMS value; the images retain their original tip/tilt.";
  const third = r ? "" : " The residual RMS after tip/tilt removal is unavailable for this case, so only the two recorded series are shown.";
  $("rms-mode-note").textContent = average
    ? `Average mode: temporal means of the per-frame RMS values over frames ${START()}–${FRAMES() - 1} (${lo.toFixed(3)}–${hi.toFixed(3)} s, ${COUNT()} frames). They are not the RMS of an averaged wavefront and not inferred from the average PSF. The chart cursor only marks the paused frame ${k}; it is not part of these statistics.${third}`
    : `Instantaneous mode: the values of displayed frame ${k}, the same frame as the pupil maps, the PSFs and the galaxy panel${r ? "; the dashed curve is the residual after tip/tilt removal of each frame's map" : ""}.${third}`;
}

function updatePsfLabels() {
  if (pb().mode === "average") {
    $("psf-unc-title").textContent = "Uncorrected — analysis-window average";
    $("psf-ao-title").textContent = "AO-corrected — analysis-window average";
    $("psf-unc-sub").textContent = `${windowText()}, ${COUNT()} equal-weight samples, ${wavelengthText()}`;
    $("psf-ao-sub").textContent = `${windowText()}, ${COUNT()} equal-weight samples, ${wavelengthText()}`;
  } else {
    $("psf-unc-title").textContent = "Matched uncorrected image";
    $("psf-ao-title").textContent = "AO-corrected image";
    $("psf-unc-sub").textContent = `same atmosphere, zero DM, frame ${frameIndex()}, ${wavelengthText()}`;
    $("psf-ao-sub").textContent = `pre-update residual, frame ${frameIndex()}, ${wavelengthText()}`;
  }
}

// Wavelength labels come from the validated parent metadata of the installed case.
function wavelengthText() { return `${(state.case.observation.roles.corrected.parent.wavelength_m * 1e6).toFixed(2)} µm`; }

function seriesFrom(values) { return values.map((v, i) => [i, v]); }

function renderCharts(cursor) {
  const pf = state.case.metrics.per_frame;
  const shade = [[0, START(), "startup exclusion"]];
  const range = [0, FRAMES() - 1];
  const x = { label: "Frame-start time", unit: "ms; frame k starts at k ms", range };
  const rms = state.case.rms;
  const series = [
    { label: "Atmosphere RMS (tilt retained)", points: seriesFrom(pf.atmosphere_rms_nm.values), color: PALETTE[0], width: 1.4 },
    { label: "Total residual RMS (tilt retained)", points: seriesFrom(pf.residual_rms_nm.values), color: PALETTE[1], width: 1.8 },
  ];
  if (rms) series.push({ label: "Residual RMS after tip/tilt removal", points: seriesFrom(rms.detilted_residual_rms_nm.values), color: PALETTE[2], width: 1.8, style: "dashed" });
  const cursorLabel = pb().mode === "average" ? `paused frame ${cursor}` : null;
  lineChart($("chart-rms"), {
    title: "Pupil RMS", height: 240, x, y: { label: "RMS", unit: "nm OPD" },
    series, shadeX: shade, cursorX: cursor, cursorLabel,
  });
  lineChart($("chart-strehl"), {
    title: "Instantaneous peak Strehl", height: 220, x, y: { label: "Peak Strehl", unit: "", range: [0, 1] },
    series: [{ label: "Uncorrected", points: seriesFrom(pf.peak_strehl_uncorrected.values) }, { label: "AO-corrected", points: seriesFrom(pf.peak_strehl_corrected.values) }],
    shadeX: shade, cursorX: cursor, cursorLabel,
  });
  lineChart($("chart-valid"), {
    title: "Validity", height: 160, x, y: { label: "Fraction", unit: "", range: [0, 1.05] },
    series: [{ label: "Valid measurement fraction", points: seriesFrom(pf.valid_measurement_fraction.values) }, { label: "DM saturation (command of frame k)", points: seriesFrom(pf.dm_saturation_fraction.values) }],
    shadeX: shade, cursorX: cursor, cursorLabel,
    ticksBelow: pf.reconstruction_usable.map((u, i) => (u ? null : { x: i })).filter(Boolean),
  });
}

function renderSummaryTable() {
  // The detilted row appears only when the installed case's own diagnostics were verified.
  const caseRms = state.case.rms;
  const baselineMean = state.rms?.manifest.window_means[state.manifest.default_case]?.detilted_residual_rms_nm ?? null;
  const s = { ...state.manifest.summaries[state.case.id], mean_detilted_residual_rms_nm: caseRms ? windowMean(caseRms.detilted_residual_rms_nm.values) : null };
  const b = { ...state.manifest.summaries[state.manifest.default_case], mean_detilted_residual_rms_nm: baselineMean };
  const rows = [
    ["Mean atmosphere RMS (mean of per-frame RMS, tilt retained)", "mean_atmosphere_rms_nm", "nm OPD", 1],
    ["Mean total residual RMS (mean of per-frame RMS, tilt retained)", "mean_residual_rms_nm", "nm OPD", 1],
    ...(caseRms ? [["Mean residual RMS after tip/tilt removal (mean of per-frame RMS)", "mean_detilted_residual_rms_nm", "nm OPD", 1]] : []),
    ["Total residual RMS (root of the mean square)", "root_mean_square_residual_nm", "nm OPD", 1],
    ["Mean instantaneous peak Strehl, uncorrected", "mean_instantaneous_peak_strehl_uncorrected", "", 4],
    ["Mean instantaneous peak Strehl, AO-corrected", "mean_instantaneous_peak_strehl_corrected", "", 4],
    ["Peak Strehl of the averaged image, uncorrected", "average_psf_peak_strehl_uncorrected", "", 4],
    ["Peak Strehl of the averaged image, AO-corrected", "average_psf_peak_strehl_corrected", "", 4],
    ["FWHM of the averaged AO image", "average_psf_fwhm_lambda_over_d_corrected", "λ/D", 3],
    ["Mean valid measurement fraction", "mean_valid_measurement_fraction", "", 4],
    ["Minimum valid measurement fraction", "min_valid_measurement_fraction", "", 4],
    ["Reconstruction usable fraction", "reconstruction_usable_fraction", "", 3],
    ["Mean DM saturation fraction of the commands issued in the window", "mean_dm_saturation_fraction", "", 4],
    [`Max DM saturation of the commands issued in ${windowText()}`, "max_dm_saturation_fraction", "", 3],
  ];
  const isBase = state.case.id === state.manifest.default_case;
  $("summary-table-title").textContent = `${windowText().charAt(0).toUpperCase()}${windowText().slice(1)}, ${COUNT()} equal-weight samples, one realization (no confidence intervals)`;
  $("summary-table").innerHTML = `<table aria-labelledby="summary-table-title"><thead><tr><th>Quantity</th><th>${state.case.json.label}</th>${isBase ? "" : "<th>Baseline</th><th>Difference</th>"}<th>Unit</th></tr></thead><tbody>${rows.map(([label, key, unit, d]) => `<tr><th scope="row">${label}</th><td class="num">${fmt(s[key], d)}</td>${isBase ? "" : `<td class="num">${fmt(b[key], d)}</td><td class="num">${s[key] - b[key] >= 0 ? "+" : ""}${fmt(s[key] - b[key], d)}</td>`}<td>${unit}</td></tr>`).join("")}</tbody></table>`;
  const pairing = state.case.json.pairing;
  $("pairing-note").textContent = isBase
    ? "The baseline is the reference case for the comparisons."
    : pairing.status === "paired"
      ? `Paired comparison: all ${pairing.matching_frames} atmosphere samples are byte-identical to the baseline's (streamed digest per frame), so the difference isolates the changed parameter in this one realization.`
      : `Not a paired comparison: ${pairing.matching_frames} of ${pairing.frames} atmosphere samples match the baseline. ${pairing.note.charAt(0).toUpperCase()}${pairing.note.slice(1)}.`;
}

// Descriptive 100 ms block summaries of the installed case (blocks.json).
function renderBlocks() {
  const b = state.blocks.cases[state.case.id];
  const f = (s, d) => `${fmt(s.mean, d)} ± ${fmt(s.std, d)}`;
  $("blocks-title").textContent = `${state.case.json.label}: non-overlapping ${state.blocks.definition.block_frames}-frame (${state.blocks.definition.block_frames} ms) blocks of all ${FRAMES()} frames (mean ± standard deviation within each block)`;
  const rows = b.blocks.map((r) => `<tr${r.in_analysis_window ? "" : " class=\"excluded\""}><th scope="row">${r.frames[0]}–${r.frames[1] - 1}${r.in_analysis_window ? "" : " (excluded)"}</th><td class="num">${f(r.residual_rms_nm, 1)}</td><td class="num">${f(r.peak_strehl_corrected, 3)}</td><td class="num">${f(r.peak_strehl_uncorrected, 3)}</td><td class="num">${fmt(r.saturation_fraction.mean, 4)}</td><td class="num">${fmt(r.saturation_fraction.max, 3)}</td><td class="num">${r.saturation_fraction.frames_with_any_clipped}</td><td class="num">${r.unusable_reconstructions}</td></tr>`);
  $("blocks-table").innerHTML = `<table aria-labelledby="blocks-title"><thead><tr><th>Frames</th><th>Residual RMS (nm)</th><th>Strehl, AO</th><th>Strehl, uncorrected</th><th>Mean DM saturation</th><th>Max DM saturation</th><th>Frames with any clipped actuator</th><th>Unusable reconstructions</th></tr></thead><tbody>${rows.join("")}</tbody></table>`;
  const a = b.analysis_blocks;
  $("blocks-note").textContent = `Within the analysis window the ${a.count} block means of the residual RMS range from ${fmt(a.residual_rms_nm_block_means_range[0])} to ${fmt(a.residual_rms_nm_block_means_range[1])} nm and of the AO peak Strehl from ${fmt(a.peak_strehl_corrected_block_means_range[0], 3)} to ${fmt(a.peak_strehl_corrected_block_means_range[1], 3)}. r0, the outer scale and the wind are fixed within the case; these changes accompany the frozen-flow realization moving across the pupil, and a loop that keeps tracking a changing input fluctuates with it, so they do not by themselves show controller divergence. ${state.blocks.notice} DM saturation: ${state.blocks.definition.saturation_definition}; it may limit the correction but is not isolated as a cause here.`;
}

function renderBinary() {
  const o = state.case.observation;
  $("obs-unc").src = objectUrl(state.case.observationPng.uncorrected, "image/png");
  $("obs-ao").src = objectUrl(state.case.observationPng.corrected, "image/png");
  const sc = state.scene.scene;
  const sep = sc.separation_mas; const ld = sc.separation_lambda_over_d;
  $("scene-caption").textContent = `primary at 0, secondary +${sep.toFixed(1)} mas in x (${ld.toFixed(2)} λ/D, 6 native cells); weights 2/3 and 1/3; total flux 1`;
  $("obs-unc-caption").textContent = `${state.case.json.label}: mean uncorrected PSF; ${(o.roles.uncorrected.retained_fraction * 100).toFixed(3)} % of the full-convolution flux lies inside the native ±4.3″ window`;
  $("obs-ao-caption").textContent = `${state.case.json.label}: mean AO PSF; ${(o.roles.corrected.retained_fraction * 100).toFixed(3)} % of the full-convolution flux lies inside the native ±4.3″ window`;
  $("binary-label").textContent = `${o.label}. Static: ${windowText()} (${COUNT()} samples); it does not follow the movie cursor or the PSF view switch.`;
  $("binary-note").textContent = o.limitations.join(" ");
}

function renderDownloads() {
  const links = Object.entries(state.case.files).map(([name, file]) => {
    const type = name.endsWith(".csv") ? "text/csv" : "application/json";
    const url = objectUrl(file.buffer, type);
    return `<a href="${url}" download="${state.case.id}-${name}">${name}</a>`;
  });
  const missing = state.case.rms ? "" : ` The optional RMS diagnostics of this case are unavailable and are not offered (${escapeHtml(state.case.rmsError)}).`;
  $("downloads").innerHTML = `<p>Verified files of <strong>${state.case.json.label}</strong>: ${links.join(" ")}${missing}</p>`;
}

function renderFrameTable(force) {
  const details = $("frame-table").closest("details");
  if (!force && !details.open) { $("frame-table-title").textContent = ""; $("frame-table").innerHTML = ""; return; }
  const pf = state.case.metrics.per_frame;
  const detilted = state.case.rms ? state.case.rms.detilted_residual_rms_nm.values : null;
  const rows = pf.frame_index.map((k) => `<tr><td class="num">${k}</td><td class="num">${fmt(pf.atmosphere_rms_nm.values[k], 3)}</td><td class="num">${fmt(pf.residual_rms_nm.values[k], 3)}</td><td class="num">${detilted ? fmt(detilted[k], 3) : "—"}</td><td class="num">${fmt(pf.peak_strehl_uncorrected.values[k], 4)}</td><td class="num">${fmt(pf.peak_strehl_corrected.values[k], 4)}</td><td class="num">${fmt(pf.valid_measurement_fraction.values[k], 4)}</td><td>${pf.reconstruction_usable[k] ? "yes" : "no"}</td><td class="num">${fmt(pf.dm_saturation_fraction.values[k], 3)}</td></tr>`);
  $("frame-table-title").textContent = `${state.case.json.label}: all ${FRAMES()} frames (display rounding; full precision in the downloads)`;
  $("frame-table").innerHTML = `<table aria-labelledby="frame-table-title"><thead><tr><th>Frame</th><th>Atmosphere RMS (nm OPD)</th><th>Total residual RMS (nm OPD)</th><th>Residual RMS after tip/tilt removal (nm OPD${detilted ? "" : "; unavailable for this case"})</th><th>Strehl, uncorrected</th><th>Strehl, AO</th><th>Valid fraction</th><th>Usable</th><th>DM saturation</th></tr></thead><tbody>${rows.join("")}</tbody></table>`;
}

function renderModelNotes() {
  const p = state.case.json.effective_parameters;
  $("model-notes").innerHTML = `<ul>
<li>Each frame samples the atmosphere once, at its start (t = k ms, k = 0–${FRAMES() - 1}, so the trajectory covers the physical interval [0.000, ${(td().physical_interval_s[1]).toFixed(3)}) s). The <em>residual seen by the WFS</em> is the atmosphere minus the DM correction held while that frame was measured (pre-update residual). The <em>held correction</em> is atmosphere minus that residual, in OPD-equivalent nm (not mirror surface height). Post-update residuals are a same-sample diagnostic and are not shown.</li>
<li>The <em>uncorrected image</em> propagates the same recorded atmosphere with the DM at zero: an optical counterfactual, not a separate sensor/control run. The <em>AO-corrected image</em> propagates the frame's pre-update residual. Both are monochromatic at ${wavelengthText()} on the native 156 × 156 grid (shown cropped to ±32 cells); tilt is kept and nothing is recentred.</li>
<li>The averaged images are the equal-weight mean of the ${COUNT()} instantaneous intensities of ${windowText()} (timestamps ${START()}–${FRAMES() - 1} ms; nominal quadrature ${COUNT()} × 1 ms). Frames 0–${START() - 1} are a startup exclusion chosen before the run, not a demonstrated settling time. The averages are of frame-start snapshots, not a finite-shutter exposure, and are never made from an averaged wavefront; they are correct for this window but are not shown to be converged long-exposure images.</li>
<li>The movie shows ${SHOWN()} of the ${FRAMES()} recorded frames (${td().display_rule}). The curves, tables, block summaries and averages use every frame.</li>
<li>Queued command delay is ${p.queued_latency_frames} frames: a reconstruction from frame k is applied in the update of frame k + ${p.queued_latency_frames} and first seen by the WFS at frame k + ${p.wfs_visible_delay_frames}.</li>
<li>The guide-source magnitude is a WFS photon-budget input (synthetic AB source at 700 nm), not the brightness of the science scene. Detector noise is on in the loop.</li>
<li>One seed (1) and one realization on a ${state.manifest.screen.generated_screen_px} × ${state.manifest.screen.generated_screen_px} screen; no seed-sensitivity run or ensemble uncertainty exists for this dataset.</li>
</ul>`;
}

// ---------------------------------------------------------------------------
// Playback
//
// The clock, the position, play/pause, the duration, the view mode and the
// loop live in playback.js and are shared with the galaxy panel; this panel
// only binds its controls to that module and renders its snapshots.

const ms = (seconds) => `${Math.round(seconds * 1000)} ms`;
const TIME_CONTROLS = ["btn-restart", "btn-prev", "btn-play", "btn-next", "seek", "duration"];

function holdText(position) {
  const end = playback.holdEnd(position);
  return position + 1 < SHOWN() ? `shown until the next displayed frame at ${ms(end)}` : `the last frame, shown for its 1 ms period to ${ms(end)}`;
}

function setupPlayback() {
  const p = state.manifest.playback;
  $("duration").innerHTML = p.durations_s.map((d) => `<option value="${d}">${d} s</option>`).join("");
  $("seek").max = String(SHOWN() - 1);
  playback.configure({
    times: td().display_times_s, interval: p.interval_s, durations: p.durations_s,
    defaultDuration: p.default_duration_s, reducedMotionDuration: p.reduced_motion_duration_s,
    reducedMotion: window.matchMedia("(prefers-reduced-motion: reduce)").matches,
    // Start at the first displayed frame of the analysis window.
    position: td().display_indices.indexOf(START()),
  });
}

function syncControls(p) {
  const average = p.mode === "average";
  for (const id of TIME_CONTROLS) $(id).disabled = average;
  $("btn-play").setAttribute("aria-pressed", String(p.playing));
  $("btn-play").textContent = p.playing ? "Pause" : "Play";
  $("seek").value = String(p.position);
  $("duration").value = String(p.duration);
  for (const input of document.querySelectorAll('input[name="psf-mode"]')) input.checked = input.value === p.mode;
  const note = $("mode-note");
  note.hidden = !average;
  note.textContent = average
    ? `Analysis-window average: both images are the equal-weight means of ${windowText()} (${COUNT()} samples, every frame of the window, not only the displayed ones). Playback and time controls are disabled in this panel and in the galaxy panel; the wavefront maps stay frozen at the selected frame and the curves keep its cursor. Switch back to Instantaneous (or Sampled instantaneous in the galaxy panel) to continue from the same frame.`
    : "";
  const [lo, hi] = p.interval;
  $("speed-note").textContent = `Presentation only: one pass over the recorded ${ms(lo)}–${ms(hi)} (${(hi - lo).toFixed(3)} s of simulated time, frames 0–${FRAMES() - 1} at 1 ms each) takes ${p.duration} s, ${p.slowdown.toFixed(0)}× slower than real time. The movie shows ${SHOWN()} of the ${FRAMES()} recorded frames; each is held until the next displayed timestamp. Nothing is interpolated and no frame is added. These controls and the galaxy panel's operate one shared timeline, so both panels show the same case and frame.${p.loop ? " Loop (set in the galaxy panel) is on: it repeats the same recording from frame 0 and does not extend the simulation." : ""}`;
}

function onPlayback(p) {
  if (!p.configured || !state.manifest) return;
  syncControls(p);
  if (state.case) renderFrame();
}

// ---------------------------------------------------------------------------
// Status and errors

function setStatus(text) { $("status").textContent = text; }
function showError(message, detail) {
  const box = $("error");
  box.hidden = false;
  box.innerHTML = `<strong>${escapeHtml(message)}</strong> ${detail ? escapeHtml(detail.trim()) : ""}`;
}
function hideError() { $("error").hidden = true; $("error").textContent = ""; }
function escapeHtml(text) { return String(text).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", "\"": "&quot;" }[c])); }

// ---------------------------------------------------------------------------
// Research Results and Methods (lazy)

// "#results", "#methods" and deep links such as "#result-R6" load the
// Research Results; a deep link is scrolled into view once rendered
// (review round 1, R1-F12).
function wantsResults() { return ["#project", "#appendix", "#results", "#methods"].includes(location.hash) || location.hash.startsWith("#result-"); }

function revealHash() {
  if (!location.hash.startsWith("#result-") && location.hash !== "#methods") return;
  const target = document.getElementById(location.hash.slice(1));
  if (target) { if (target.tagName === "DETAILS") target.open = true; target.scrollIntoView({ behavior: "instant", block: "start" }); }
}

async function loadResults() {
  if (state.resultsLoaded) { revealHash(); return; }
  if (state.resultsLoaded || state.resultsLoading || !state.manifest) return;
  state.resultsLoading = true;
  $("results-status").textContent = "Loading Research Results…";
  try {
    const { url, value, buffer } = await fetchVerifiedJson(state.manifest.results, state.manifestUrl);
    require(value.schema === "ao-explorer.research-results.v1", `unsupported research schema ${value.schema}`);
    require(value.groups.length === 8 && value.groups.every((g, i) => g.id === `R${i + 1}`), "Research Results must contain groups R1-R8");
    await renderResults(value, url, $("results-body"), $("results-index"), buffer);
    renderProjectEvidence(value);
    renderMethodsStatus(value);
    state.resultsLoaded = true;
    revealHash();
    $("results-status").textContent = `Eight result groups from saved evidence at source ${value.source_sha.slice(0, 12)}; figures and evidence files are verified against the manifest as they load.`;
  } catch (error) {
    $("results-status").textContent = "";
    showResultsError(error);
  } finally {
    state.resultsLoading = false;
  }
}

function showResultsError(error) {
  const box = document.createElement("div");
  box.className = "error"; box.setAttribute("role", "alert");
  box.innerHTML = `<strong>Research Results could not be shown.</strong> ${escapeHtml(error.message)}`;
  $("results-body").replaceChildren(box);
}

function renderMethodsStatus(results) {
  $("methods-status").innerHTML = Object.entries(results.status_vocabulary).map(([key, text]) => `<li><strong>${key}</strong>: ${text}.</li>`).join("")
    + "<li>No status is a general “validated” badge: each one names what kind of evidence stands behind a result.</li>";
  const open = results.groups.find((g) => g.id === "R8").open_questions;
  $("methods-open").innerHTML = open.map((q) => `<li><strong>${q.id}</strong> — ${q.question} (${q.status}; <code>${q.source.path}</code> lines ${q.source.lines.join("–")}).</li>`).join("");
}

function renderMethods() {
  const m = state.manifest; const d = state.diagnostics; const t = td(); const sc = m.screen;
  $("methods-2m").innerHTML = `
<li>Profile <code>det_emccd_2m_synthetic@1</code> (native optics, 2 m, 52 pupil samples, 5 × 5 lenslets and actuators, 700 nm WFS, synthetic EMCCD with noise on, TSVD reconstructor, leaky integrator). Explorer overrides: ${t.frames} frames at 1 kHz (the physical interval [0.000, ${t.physical_interval_s[1].toFixed(3)}) s), root seed 1, realization 0, science at 1.65 µm. The profile resource is unchanged.</li>
<li>Eight recorded cases: baseline; r0 × 1.25 and × 0.80; guide AB magnitude 6 and 8; gain 0.10 and 0.30; queued delay 4 frames. Every other parameter is fixed and equals the recorded configuration of the earlier 180-frame series. Only these nodes exist.</li>
<li>Atmosphere: <code>native_frozen_flow_v2</code>, generated at ${sc.generated_screen_px} × ${sc.generated_screen_px} pixels through an explicit construction option (the historical default is ${sc.historical_default_px} × ${sc.historical_default_px}); the size is part of every atmosphere identity. With the ${sc.pupil_px}-pixel pupil (${(sc.delta_m * 100).toFixed(2)} cm per pixel) and ${sc.wind_m_per_s[0]} m/s wind the screen supports ${sc.travel_budget_px} px of travel, ${sc.supported_travel_duration_s.toFixed(3)} s. Before any trajectory ran, every request time was checked against that budget: the last frame start (${ms(t.sample_times_s[1])}) travels ${sc.max_requested_travel_px.toFixed(3)} px, and the runtime travel equalled the admitted value. The larger screen is a different realization of the same seed, so this dataset does not reproduce the earlier 180-frame trajectory.</li>
<li>Frames 0–${START() - 1} are a startup exclusion declared before the run, an analysis choice rather than a demonstrated settling time. The averages use the half-open window [${START()}, ${t.frames}), exactly ${COUNT()} equal-weight frames; they are the correctly computed averages for that 0.200–1.000 s window, which by itself does not establish convergence to a long-exposure ensemble result.</li>
<li>Within each case r0, the outer scale and the wind are fixed. The frozen-flow realization moves across the pupil, so the realized wavefront RMS inside the pupil can change substantially although the configured turbulence strength does not change with time. A working AO loop keeps tracking that changing input, so residual fluctuations, or a late rise, do not by themselves show controller divergence or a failure to settle.</li>
<li>The late residual increase accompanies stronger realized wavefront variations within the pupil, especially residual tip/tilt. It does not by itself demonstrate controller divergence. The records do not separate the contributions of fitting error, delay, controller leakage and actuator saturation; saturation may limit the correction but is not shown to be the cause. The saved ${COUNT()}-frame mean is the valid average for the declared 0.200–1.000 s window, but this single-realization record does not establish a converged long-exposure PSF. A nearly unchanged scalar mean can coexist with a mean image that still depends on the chosen interval (the implementation record gives a baseline example for the two halves of the window). The peak Strehl of an averaged PSF is not the average of the instantaneous peak Strehl values.</li>
<li>All ${t.frames} instantaneous PSF pairs and pupil maps are kept at full precision outside this site; the page shows ${SHOWN()} of them (${t.display_rule}).</li>
<li>${d.passivity.note} ${d.seed2_sensitivity.note}</li>
<li>The binary observation convolves one fixed scene with each case's two ${COUNT()}-sample mean PSFs (exact linear convolution, zero extension, crop to the native angular window by coordinates). One on-axis PSF is assumed across the scene: an illustration, not field-dependent imaging.</li>
<li>The galaxy view convolves one fixed observed template, the central region of NGC 1705 from the LEGUS HST/WFC3 F814W mosaic at its real angular scale, with all ${t.frames} instantaneous PSF pairs of each case (${SHOWN()} shown) and with its ${COUNT()}-frame mean PSFs, by the same linear-convolution rule. The template keeps Hubble's resolution, its residual noise and the saturated core of the central cluster; F814W morphology is used as a relative-intensity template with the 1.65 µm PSFs, not as an H-band image or an intrinsic, deconvolved galaxy. It makes no surface-brightness, photon-count, sensitivity, signal-to-noise or off-axis claim.</li>`;
  $("methods-identity").innerHTML = `
<li>Dataset <code>${m.dataset_id}</code>; plan SHA-256 <code>${m.series.plan_sha256.slice(0, 16)}…</code>; production identity <code>${m.series.production_sha256.slice(0, 16)}…</code>, which binds the producer files and the core package by content because the working tree was uncommitted at production (base commit <code>${m.series.source_sha?.slice(0, 12) ?? "unknown"}</code>); page code build <code>${CODE_BUILD}</code> (recorded by the dataset entry).</li>
<li>The earlier 180-frame dataset <code>${m.previous_dataset.dataset_id}</code> is preserved unchanged and is not combined with this one. The Research Results are its byte-identical files, referenced in place; they do not depend on either explorer trajectory.</li>
${state.rms ? `<li>RMS diagnostics <code>${state.rms.manifest.derived_id}</code>: the residual RMS after tip/tilt removal of all ${t.frames} saved residual maps of every case, an additive scalar derivative bound to this dataset's manifest; each case's values name the SHA-256 of the metrics they accompany, and each map was matched to its frame by the digest the observer recorded during the run.</li>` : `<li>RMS diagnostics: ${state.rmsError ?? "not named by this dataset entry"}.</li>`}
<li>Every file is listed in the manifest with its size and SHA-256 and is checked in the browser before use; the manifest itself is bound by the entry file.</li>
<li>Raw numerical evidence (pupil maps and PSFs of every frame, full-precision mean PSFs, histories, the galaxy observations of every frame) stays in the producer's output directories and is not part of this site.</li>`;
  $("footer-identity").textContent = `Dataset ${m.dataset_id}.`;
  const lede = $("explore-lede");
  if (lede) lede.textContent = `A precomputed native 2 m Shack-Hartmann SCAO loop with a synthetic on-axis guide source: one seed, ${t.frames} frames at 1 kHz (${t.physical_interval_s[1].toFixed(3)} s of simulated time), averages over ${windowText()}. Your browser replays ${SHOWN()} of the recorded frames, slowed down, and selects recorded cases; it does not simulate, interpolate or draw noise.`;
  const hint = $("curves-hint");
  if (hint) hint.textContent = `All ${t.frames} frames, including the startup exclusion (shaded, frames 0–${START() - 1}). Summaries use ${windowText()} only (${COUNT()} equal-weight samples). The cursor marks the displayed frame.`;
}

// ---------------------------------------------------------------------------
// Start

function buildGroups() {
  const m = state.manifest;
  const host = $("groups");
  host.innerHTML = "";
  for (const group of m.groups) {
    const box = document.createElement("div");
    box.className = "group";
    box.innerHTML = `<h3>${group.label}</h3>`;
    const nodes = document.createElement("div");
    nodes.className = "nodes";
    for (const id of group.nodes) {
      const button = document.createElement("button");
      button.type = "button"; button.className = "node"; button.dataset.case = id;
      button.setAttribute("aria-pressed", "false");
      button.innerHTML = `${m.cases[id].label}`;
      button.addEventListener("click", () => selectCase(id));
      nodes.append(button);
    }
    box.append(nodes);
    host.append(box);
  }
}

function bindControls() {
  $("btn-play").addEventListener("click", () => playback.toggle());
  $("btn-prev").addEventListener("click", () => playback.step(-1));
  $("btn-next").addEventListener("click", () => playback.step(1));
  $("btn-restart").addEventListener("click", () => playback.restart());
  $("seek").addEventListener("input", (event) => playback.seek(Number(event.target.value)));
  for (const input of document.querySelectorAll('input[name="psf-mode"]')) input.addEventListener("change", (event) => playback.setMode(event.target.value));
  $("zoom").addEventListener("change", (event) => document.querySelector(".binary").classList.toggle("fullwindow", event.target.checked));
  $("duration").addEventListener("change", (event) => playback.setDuration(Number(event.target.value)));
  playback.subscribe(onPlayback);
  $("frame-table").closest("details").addEventListener("toggle", () => state.case && renderFrameTable(false));
  const redrawCharts = () => state.case && renderCharts(frameIndex());
  const observed = ["chart-rms", "chart-strehl", "chart-valid"].map((id) => redrawWhenResized($(id), redrawCharts)).every(Boolean);
  if (!observed) window.addEventListener("resize", redrawCharts);
  document.querySelectorAll('[data-topic]').forEach(button => button.addEventListener('click', () => {
    document.querySelectorAll('[data-topic]').forEach(b => b.setAttribute('aria-pressed', String(b === button)));
    document.querySelectorAll('.topic-panel').forEach(panel => { panel.hidden = panel.id !== `topic-${button.dataset.topic}`; });
  }));
  if ("IntersectionObserver" in window) {
    const observer = new IntersectionObserver((entries) => { if (entries.some((e) => e.isIntersecting)) loadResults(); }, { rootMargin: "200px" });
    observer.observe($("project")); observer.observe($("appendix"));
  }
  window.addEventListener("hashchange", () => { if (wantsResults()) loadResults(); });
}

async function start() {
  const initialHash = location.hash;
  bindControls();
  for (const id of ["btn-restart", "btn-prev", "btn-play", "btn-next", "seek", "duration"]) $(id).disabled = true;
  try {
    const { manifest, manifestUrl, entry, entryUrl: galaxyEntryUrl } = await loadEntry();
    state.manifest = manifest; state.manifestUrl = manifestUrl;
    initReplay42(entry, galaxyEntryUrl);
    initApertureComparison(entry, galaxyEntryUrl);
    initDmStroke(entry, galaxyEntryUrl);
    initC1Noise(entry, galaxyEntryUrl);
    initNgs22(entry, galaxyEntryUrl);
    initNgsReplay(entry, galaxyEntryUrl);
    initNgsControl(entry, galaxyEntryUrl);
    const [display, scene, diagnostics, blocks] = await Promise.all([
      fetchVerifiedJson(manifest.display, manifestUrl),
      fetchVerifiedJson(manifest.scene, manifestUrl),
      fetchVerifiedJson(manifest.diagnostics, manifestUrl),
      fetchVerifiedJson(manifest.blocks, manifestUrl),
    ]);
    require(display.value.schema === "ao-explorer.display.v2", "unsupported display schema");
    require(display.value.opd.lut_rgb_hex.length === display.value.opd.levels && display.value.psf.lut_rgb_hex.length === 256, "the display colour tables are incomplete");
    require(diagnostics.value.schema === "ao-explorer.diagnostics.v2", "unsupported diagnostics schema");
    require(blocks.value.schema === "ao-explorer.blocks.v1" && Object.keys(manifest.cases).every((id) => blocks.value.cases[id]), "the block summaries do not cover every case");
    const b = blocks.value.definition;
    require(b.blocks.length * b.block_frames === manifest.time_domain.frames && b.blocks.every((r, i) => r[0] === i * b.block_frames && r[1] === (i + 1) * b.block_frames), "the block summaries do not tile the trajectory");
    require(scene.value.schema === "ao-explorer.scene-export.v1" && scene.value.scene.total_flux > 0.999999999999, "unsupported or invalid scene");
    const [sceneWavelength, supported] = wavelengthPair(scene.value.scene.wavelength_m, SCIENCE_WAVELENGTH_M);
    require(scene.value.scene.wavelength_m === SCIENCE_WAVELENGTH_M, `the scene is at ${sceneWavelength}, not ${supported}`);
    state.display = display.value; state.scene = scene.value; state.sceneUrl = scene.url; state.diagnostics = diagnostics.value; state.blocks = blocks.value;
    // The scalar derivative is additive: if it cannot be verified the page runs without it and says so.
    try { state.rms = await loadDiagnostics(entry, galaxyEntryUrl); } catch (error) { state.rms = null; state.rmsError = `the RMS diagnostics could not be verified (${error.message})`; }
    const sceneImage = await fetchVerified(scene.value.display.image, scene.url, { expectType: "image/png" });
    state.sceneImageBuffer = sceneImage.buffer;
    // The galaxy view loads its own small manifest now and its case data only when in view.
    initGalaxy(entry, galaxyEntryUrl, {
      datasetId: manifest.dataset_id, manifestSha256: entry.manifest_sha256, binarySceneId: scene.value.scene.scene_id,
      gridId: scene.value.scene.grid_id, caseIds: Object.keys(manifest.cases),
      timeDomain: manifest.time_domain, playback: manifest.playback,
    });
    buildGroups();
    setupColorbars();
    renderMethods();
    setupPlayback();
    const requested = new URLSearchParams(location.search).get("case");
    await selectCase(manifest.default_case);
    if (requested && requested !== manifest.default_case) {
      if (manifest.cases[requested]) await selectCase(requested);
      else showError(`The requested case “${requested}” is not a recorded case of this dataset.`, " Only the listed scenario buttons exist; the baseline is shown.");
    }
    if (wantsResults()) await loadResults();
    // Restore a direct section link after the asynchronous 2 m tables settle.
    if (location.hash === initialHash && ["#project", "#replay42", "#c1-noise", "#aperture-comparison", "#dm-stroke", "#elt-m4-stroke", "#ngs22", "#ngs22-replay", "#ngs22-control", "#evidence-2m", "#evidence-42m", "#evidence-ngs22", "#references", "#appendix", "#results"].includes(initialHash)) {
      document.getElementById(initialHash.slice(1))?.scrollIntoView({ behavior: "instant", block: "start" });
    }
  } catch (error) {
    setStatus("The dataset could not be loaded.");
    showError(`The 2 m experiment could not be loaded: ${error.message}`, " Nothing from an unverified or incomplete bundle is shown.");
  }
}

start();
