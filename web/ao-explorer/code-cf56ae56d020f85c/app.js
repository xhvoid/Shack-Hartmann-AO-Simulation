// AO Simulation Explorer: 2 m experiment controller.
//
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
//
// The "Generate an experiment" section is a separate mode: generate.js is
// imported only when the visitor connects to a computation service (the
// Connect button or an explicit ?backend= address), so the precomputed
// explorer makes no additional request unless generation is asked for.

import { BundleError, fetchVerified, fetchVerifiedImage, fetchVerifiedJson, isFiniteOrNull, require } from "./integrity.js";
import { lineChart, redrawWhenResized } from "./charts.js";
import { renderResults } from "./results.js";

const SUPPORTED_MANIFEST = "ao-explorer.manifest.v1";
const SUPPORTED_ENTRY = "ao-explorer.entry.v1";
const FRAMES = 180;
const BURN_IN = 40;
const MOVIE_FRAMES = 40;
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
  diagnostics: null, case: null, position: 9, playing: false, psfMode: "instantaneous",
  generation: 0, controller: null, cache: new Map(), objectUrls: [], timer: null, nextAt: null,
  resultsLoaded: false, resultsLoading: false,
};

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
  return { manifest, manifestUrl };
}

function validateManifest(m, entry) {
  require(m.schema === SUPPORTED_MANIFEST, `unsupported manifest schema ${m.schema}`);
  require(m.dataset_id === entry.dataset_id, "the manifest and its entry name different datasets");
  require(m.cases && typeof m.cases === "object", "the manifest lists no cases");
  require(m.cases[m.default_case], `the default case ${m.default_case} is missing`);
  for (const group of m.groups) for (const node of group.nodes) require(m.cases[node], `group ${group.id} names unknown case ${node}`);
  for (const key of ["scene", "display", "diagnostics", "results"]) require(m[key] && m[key].sha256, `the manifest has no ${key} member`);
  for (const [id, item] of Object.entries(m.cases)) {
    require(item.case && item.case.sha256 && item.case.media_type === "application/json", `case ${id} has no verified reference`);
    require(m.summaries && m.summaries[id], `case ${id} has no recorded summary`);
  }
}

// ---------------------------------------------------------------------------
// Case loading and validation

function validateCase(id, c, metrics, observation) {
  require(c.schema === "ao-explorer.case.v1", `case ${id}: unsupported schema ${c.schema}`);
  require(c.case_id === id, `case file names ${c.case_id}, expected ${id}`);
  const t = c.time_domain;
  require(t.frames === FRAMES && t.burn_in_frames === BURN_IN, `case ${id}: unexpected trajectory length or burn-in`);
  require(t.analysis_window[0] === BURN_IN && t.analysis_window[1] === FRAMES && t.analysis_count === FRAMES - BURN_IN, `case ${id}: analysis window is not [40, 180)`);
  require(t.frame_rate_hz === 1000 && Math.abs(t.frame_period_s - 0.001) < 1e-15, `case ${id}: unexpected frame rate`);
  const idx = t.movie_indices;
  require(Array.isArray(idx) && idx.length === MOVIE_FRAMES, `case ${id}: movie must have 40 indices`);
  for (let i = 0; i < idx.length; i += 1) {
    require(Number.isInteger(idx[i]) && idx[i] >= 0 && idx[i] < FRAMES, `case ${id}: movie index out of range`);
    if (i) require(idx[i] > idx[i - 1], `case ${id}: movie indices are not unique and ordered`);
    require(Math.abs(t.movie_times_s[i] - idx[i] / 1000) < 1e-12, `case ${id}: movie time does not match its index`);
  }
  require(idx[0] === 0 && idx.includes(BURN_IN) && idx[idx.length - 1] === FRAMES - 1, `case ${id}: movie must include frames 0, 40 and 179`);
  for (const key of ["atmosphere", "correction", "residual", "psf_uncorrected", "psf_corrected"]) {
    const image = c.images[key];
    require(image && image.atlas && image.atlas.media_type === "image/png", `case ${id}: missing ${key} atlas`);
    require(image.rectangles_xywh.length === MOVIE_FRAMES && image.frame_indices.join() === idx.join(), `case ${id}: ${key} atlas does not cover the movie frames`);
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
    require(Array.isArray(piston) && piston.length === MOVIE_FRAMES && piston.every((v) => Number.isFinite(v)), `case ${id}: ${key} display piston record is incomplete`);
    const lim = c.images[key].color_limits_nm;
    require(lim[0] === -lim[1] && lim[1] > 0, `case ${id}: OPD colour limits must be symmetric`);
    require(lim[1] === c.images.atmosphere.color_limits_nm[1], `case ${id}: OPD panels must share colour limits`);
    require(Math.abs(lim[1] - state.display.opd.limit_m * 1e9) < 1e-6, `case ${id}: OPD colour limits differ from the common display limit`);
  }
  for (const key of ["psf_average_uncorrected", "psf_average_corrected"]) {
    require(c.images[key] && c.images[key].sample_count === FRAMES - BURN_IN, `case ${id}: ${key} is not the 140-sample average`);
  }
  require(metrics.schema === "ao-explorer.metrics.v1" && metrics.case_id === id, `metrics do not belong to case ${id}`);
  const pf = metrics.per_frame;
  require(pf.frame_index.length === FRAMES && pf.frame_index.every((v, i) => v === i), `case ${id}: metrics must cover frames 0-179 in order`);
  require(pf.time_s.every((v, i) => Math.abs(v - i / 1000) < 1e-12), `case ${id}: metric timestamps do not match frames`);
  for (const key of PER_FRAME_SERIES) {
    require(pf[key] && pf[key].values.length === FRAMES && pf[key].values.every(isFiniteOrNull), `case ${id}: ${key} is incomplete or not finite`);
    // Every missing value has exactly one recorded, non-empty reason.
    const reasons = pf[key].null_reasons || {};
    const nulls = pf[key].values.flatMap((v, i) => (v === null ? [String(i)] : []));
    require(nulls.length === Object.keys(reasons).length && nulls.every((i) => typeof reasons[i] === "string" && reasons[i].trim() !== ""), `case ${id}: ${key} has a missing value without a recorded reason`);
  }
  require(pf.reconstruction_usable.length === FRAMES, `case ${id}: usability is incomplete`);
  require(metrics.summary.window[0] === BURN_IN && metrics.summary.sample_count === FRAMES - BURN_IN, `case ${id}: summary window is not [40, 180)`);
  for (const key of ["atmosphere", "correction", "residual"]) require(metrics.display_clipping[key]?.length === MOVIE_FRAMES, `case ${id}: ${key} clipping record is incomplete`);
  require(observation.schema === "ao-explorer.observation.v1" && observation.case_id === id, `observation does not belong to case ${id}`);
  require(observation.scene_id === state.scene.scene.scene_id && observation.scene_grid_id === state.scene.scene.grid_id, `case ${id}: observation scene differs from the shared scene`);
  require(observation.window[0] === BURN_IN && observation.window[1] === FRAMES && observation.sample_count === FRAMES - BURN_IN, `case ${id}: observation is not the [40, 180) average`);
  for (const role of ["uncorrected", "corrected"]) {
    const r = observation.roles[role];
    require(r && r.parent.sample_count === FRAMES - BURN_IN && r.parent.window.join() === `${BURN_IN},${FRAMES}`, `case ${id}: ${role} observation parent is not the 140-sample mean`);
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
  const imageKeys = ["atmosphere", "correction", "residual", "psf_uncorrected", "psf_corrected"];
  const atlases = await Promise.all(imageKeys.map((key) => fetchVerifiedImage(c.images[key].atlas, caseUrl, { signal })));
  const averages = await Promise.all(["psf_average_uncorrected", "psf_average_corrected"].map((key) => fetchVerifiedImage(c.images[key].image, caseUrl, { signal })));
  const obsUrl = observation.url;
  const obsImages = await Promise.all(["uncorrected", "corrected"].map((role) => fetchVerified(observation.value.roles[role].display.image, obsUrl, { signal, expectType: "image/png" })));
  return {
    id, url: caseUrl, json: c, metrics: metrics.value, observation: observation.value,
    files: {
      "metrics.json": metrics, "metrics.csv": csv, "config.json": config, "provenance.json": provenance, "observation.json": observation,
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
  pause();
  // Every selection supersedes every earlier one, including a return to the
  // installed case while another case is still loading (review round 1,
  // R1-F02): the pending load is aborted and its generation retired.
  const generation = ++state.generation;
  if (state.controller) { state.controller.abort(); state.controller = null; }
  if (state.case && id === state.case.id) {
    setBusy(null, false);
    hideError();
    setStatus(`Showing “${state.case.json.label}”. All members verified against the manifest.`);
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
    setStatus(`Showing “${data.json.label}”. All members verified against the manifest.`);
  } catch (error) {
    if (error.name === "AbortError" || generation !== state.generation) return;
    showError(`Could not show case “${id}”: ${error.message}`, state.case ? `Still showing the previously installed case: ${state.case.json.label}.` : "No case is installed.");
    setStatus("Case load failed.");
  } finally {
    if (generation === state.generation) setBusy(null, false);
  }
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
  renderFrameTable(false);
  renderFrame();
}

function updateButtons() {
  for (const button of document.querySelectorAll(".node")) {
    button.setAttribute("aria-pressed", String(button.dataset.case === state.case?.id));
  }
}

function setBusy(id, busy) {
  for (const button of document.querySelectorAll(".node")) button.setAttribute("aria-busy", String(busy && button.dataset.case === id));
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
  $("case-summary").innerHTML = `<p><strong>${c.label}</strong> — ${changes ? `changed from the baseline: <span class="changed">${changes}</span>` : "the baseline: profile det_emccd_2m_synthetic@1 with the explorer overrides only"}. ${c.question}</p><ul class="params">${paramRows(p, c.override)}</ul>`;
}

function setupColorbars() {
  const d = state.display;
  for (const [id, lut] of [["cbar-opd", d.opd.lut_rgb_hex], ["cbar-psf", d.psf.lut_rgb_hex]]) {
    const canvas = $(id); const ctx = canvas.getContext("2d");
    for (let i = 0; i < 200; i += 1) { ctx.fillStyle = lut[Math.round((1 - i / 199) * 255)]; ctx.fillRect(0, i, canvas.width, 1); }
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

function frameIndex() { return state.case.json.time_domain.movie_indices[state.position]; }

function renderFrame() {
  const c = state.case; if (!c) return;
  const images = c.json.images;
  for (const key of ["atmosphere", "correction", "residual"]) drawTile(`map-${key}`, c.atlases[key], images[key].rectangles_xywh[state.position]);
  if (state.psfMode === "average") {
    drawWhole("psf-uncorrected", c.averages.uncorrected);
    drawWhole("psf-corrected", c.averages.corrected);
  } else {
    drawTile("psf-uncorrected", c.atlases.psf_uncorrected, images.psf_uncorrected.rectangles_xywh[state.position]);
    drawTile("psf-corrected", c.atlases.psf_corrected, images.psf_corrected.rectangles_xywh[state.position]);
  }
  const k = frameIndex();
  const pf = c.metrics.per_frame;
  $("seek").value = String(state.position);
  $("seek").setAttribute("aria-valuetext", `frame ${k}, ${k} ms`);
  $("frame-readout").textContent = `Frame ${k} of 0–179 · physical time ${k.toFixed(0)} ms · movie frame ${state.position + 1}/40${k < BURN_IN ? " · burn-in" : ""}`;
  // DM saturation at index k belongs to the command issued at the end of
  // frame k (held from k + 1); the correction shown for frame k is the
  // command issued at frame k - 1 (review round 1, R1-F05).
  const saturation = pf.dm_saturation_fraction.values;
  const held = k === 0 ? "none recorded (initial flat command)" : fmt(saturation[k - 1], 3);
  $("current-frame").textContent = `Frame ${k}: atmosphere ${fmt(pf.atmosphere_rms_nm.values[k])} nm, residual ${fmt(pf.residual_rms_nm.values[k])} nm RMS (piston removed); instantaneous peak Strehl ${fmt(pf.peak_strehl_uncorrected.values[k], 3)} uncorrected, ${fmt(pf.peak_strehl_corrected.values[k], 3)} corrected; valid measurement fraction ${fmt(pf.valid_measurement_fraction.values[k], 3)}; reconstruction ${pf.reconstruction_usable[k] ? "usable" : "not usable"}; DM saturation of the held command (issued at frame ${k === 0 ? "start" : k - 1}) ${held}, of the command issued at this frame ${fmt(saturation[k], 3)}.`;
  for (const key of ["atmosphere", "correction", "residual"]) {
    const piston = images[key].display_piston_nm[state.position];
    const clip = c.metrics.display_clipping[key][state.position];
    const clipped = clip.clipped_low_fraction + clip.clipped_high_fraction;
    const rounded = Math.round(piston);
    $(`note-${key}`).textContent = `Frame ${k}: pupil mean ${rounded > 0 ? "+" : rounded < 0 ? "−" : ""}${Math.abs(rounded)} nm removed for display; ${clipped > 0 ? `${(clipped * 100).toFixed(2)} % of pupil samples beyond the colour limits (clipped)` : "no clipping"}.`;
  }
  renderCharts(k);
  updatePsfLabels();
}

function updatePsfLabels() {
  if (state.psfMode === "average") {
    $("psf-unc-title").textContent = "Uncorrected — post-burn-in average";
    $("psf-ao-title").textContent = "AO-corrected — post-burn-in average";
    $("psf-unc-sub").textContent = `frames 40–179, 140 equal-weight samples, ${wavelengthText()}`;
    $("psf-ao-sub").textContent = `frames 40–179, 140 equal-weight samples, ${wavelengthText()}`;
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
  const shade = [[0, BURN_IN, "burn-in"]];
  lineChart($("chart-rms"), {
    title: "Pupil RMS", height: 220, x: { label: "Frame", unit: "1 ms each", range: [0, 179] }, y: { label: "RMS", unit: "nm" },
    series: [{ label: "Atmosphere", points: seriesFrom(pf.atmosphere_rms_nm.values) }, { label: "Residual seen by the WFS", points: seriesFrom(pf.residual_rms_nm.values) }],
    shadeX: shade, cursorX: cursor,
  });
  lineChart($("chart-strehl"), {
    title: "Instantaneous peak Strehl", height: 220, x: { label: "Frame", unit: "1 ms each", range: [0, 179] }, y: { label: "Peak Strehl", unit: "", range: [0, 1] },
    series: [{ label: "Uncorrected", points: seriesFrom(pf.peak_strehl_uncorrected.values) }, { label: "AO-corrected", points: seriesFrom(pf.peak_strehl_corrected.values) }],
    shadeX: shade, cursorX: cursor,
  });
  lineChart($("chart-valid"), {
    title: "Validity", height: 160, x: { label: "Frame", unit: "1 ms each", range: [0, 179] }, y: { label: "Fraction", unit: "", range: [0, 1.05] },
    series: [{ label: "Valid measurement fraction", points: seriesFrom(pf.valid_measurement_fraction.values) }, { label: "DM saturation (command of frame k)", points: seriesFrom(pf.dm_saturation_fraction.values) }],
    shadeX: shade, cursorX: cursor,
    ticksBelow: pf.reconstruction_usable.map((u, i) => (u ? null : { x: i })).filter(Boolean),
  });
}

function renderSummaryTable() {
  const s = state.manifest.summaries[state.case.id];
  const b = state.manifest.summaries[state.manifest.default_case];
  const rows = [
    ["Mean atmosphere RMS", "mean_atmosphere_rms_nm", "nm", 1],
    ["Mean residual RMS (mean of per-frame RMS)", "mean_residual_rms_nm", "nm", 1],
    ["Residual RMS (root of the mean square)", "root_mean_square_residual_nm", "nm", 1],
    ["Mean instantaneous peak Strehl, uncorrected", "mean_instantaneous_peak_strehl_uncorrected", "", 4],
    ["Mean instantaneous peak Strehl, AO-corrected", "mean_instantaneous_peak_strehl_corrected", "", 4],
    ["Peak Strehl of the averaged image, uncorrected", "average_psf_peak_strehl_uncorrected", "", 4],
    ["Peak Strehl of the averaged image, AO-corrected", "average_psf_peak_strehl_corrected", "", 4],
    ["FWHM of the averaged AO image", "average_psf_fwhm_lambda_over_d_corrected", "λ/D", 3],
    ["Mean valid measurement fraction", "mean_valid_measurement_fraction", "", 4],
    ["Minimum valid measurement fraction", "min_valid_measurement_fraction", "", 4],
    ["Reconstruction usable fraction", "reconstruction_usable_fraction", "", 3],
    ["Max DM saturation of the commands issued in frames 40–179", "max_dm_saturation_fraction", "", 3],
  ];
  const isBase = state.case.id === state.manifest.default_case;
  $("summary-table-title").textContent = "Frames 40–179, 140 equal-weight samples, one realization (no confidence intervals)";
  $("summary-table").innerHTML = `<table aria-labelledby="summary-table-title"><thead><tr><th>Quantity</th><th>${state.case.json.label}</th>${isBase ? "" : "<th>Baseline</th><th>Difference</th>"}<th>Unit</th></tr></thead><tbody>${rows.map(([label, key, unit, d]) => `<tr><th scope="row">${label}</th><td class="num">${fmt(s[key], d)}</td>${isBase ? "" : `<td class="num">${fmt(b[key], d)}</td><td class="num">${s[key] - b[key] >= 0 ? "+" : ""}${fmt(s[key] - b[key], d)}</td>`}<td>${unit}</td></tr>`).join("")}</tbody></table>`;
  const pairing = state.case.json.pairing;
  $("pairing-note").textContent = isBase
    ? "The baseline is the reference case for the comparisons."
    : pairing.status === "paired"
      ? `Paired comparison: all ${pairing.matching_frames} atmosphere samples are byte-identical to the baseline's (streamed digest per frame), so the difference isolates the changed parameter in this one realization.`
      : `Not a paired comparison: ${pairing.matching_frames} of 180 atmosphere samples match the baseline. ${pairing.note.charAt(0).toUpperCase()}${pairing.note.slice(1)}.`;
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
  $("binary-label").textContent = o.label + ". Static: frames 40–179 (140 samples); it does not follow the movie cursor or the PSF view switch.";
  $("binary-note").textContent = o.limitations.join(" ");
}

function renderDownloads() {
  const links = Object.entries(state.case.files).map(([name, file]) => {
    const type = name.endsWith(".csv") ? "text/csv" : "application/json";
    const url = objectUrl(file.buffer, type);
    return `<a href="${url}" download="${state.case.id}-${name}">${name}</a>`;
  });
  $("downloads").innerHTML = `<p>Verified files of <strong>${state.case.json.label}</strong>: ${links.join(" ")}</p>`;
}

function renderFrameTable(force) {
  const details = $("frame-table").closest("details");
  if (!force && !details.open) { $("frame-table-title").textContent = ""; $("frame-table").innerHTML = ""; return; }
  const pf = state.case.metrics.per_frame;
  const rows = pf.frame_index.map((k) => `<tr><td class="num">${k}</td><td class="num">${fmt(pf.atmosphere_rms_nm.values[k], 3)}</td><td class="num">${fmt(pf.residual_rms_nm.values[k], 3)}</td><td class="num">${fmt(pf.peak_strehl_uncorrected.values[k], 4)}</td><td class="num">${fmt(pf.peak_strehl_corrected.values[k], 4)}</td><td class="num">${fmt(pf.valid_measurement_fraction.values[k], 4)}</td><td>${pf.reconstruction_usable[k] ? "yes" : "no"}</td><td class="num">${fmt(pf.dm_saturation_fraction.values[k], 3)}</td></tr>`);
  $("frame-table-title").textContent = `${state.case.json.label}: all 180 frames (display rounding; full precision in the downloads)`;
  $("frame-table").innerHTML = `<table aria-labelledby="frame-table-title"><thead><tr><th>Frame</th><th>Atmosphere RMS (nm)</th><th>Residual RMS (nm)</th><th>Strehl, uncorrected</th><th>Strehl, AO</th><th>Valid fraction</th><th>Usable</th><th>DM saturation</th></tr></thead><tbody>${rows.join("")}</tbody></table>`;
}

function renderModelNotes() {
  const p = state.case.json.effective_parameters;
  $("model-notes").innerHTML = `<ul>
<li>Each frame samples the atmosphere once, at its start (t = k ms). The <em>residual seen by the WFS</em> is the atmosphere minus the DM correction held while that frame was measured (pre-update residual). The <em>held correction</em> is atmosphere minus that residual, in OPD-equivalent nm (not mirror surface height). Post-update residuals are a same-sample diagnostic and are not shown.</li>
<li>The <em>uncorrected image</em> propagates the same recorded atmosphere with the DM at zero: an optical counterfactual, not a separate sensor/control run. The <em>AO-corrected image</em> propagates the frame's pre-update residual. Both are monochromatic at ${wavelengthText()} on the native 156 × 156 grid (shown cropped to ±32 cells); tilt is kept and nothing is recentred.</li>
<li>The averaged images are the equal-weight mean of the 140 instantaneous intensities of frames 40–179 (timestamps 40–179 ms, span 139 ms; nominal quadrature 140 × 1 ms). They are averages of frame-start snapshots, not a finite-shutter exposure, and are never made from an averaged wavefront.</li>
<li>Queued command delay is ${p.queued_latency_frames} frames: a reconstruction from frame k is applied in the update of frame k + ${p.queued_latency_frames} and first seen by the WFS at frame k + ${p.wfs_visible_delay_frames}.</li>
<li>The guide-source magnitude is a WFS photon-budget input (synthetic AB source at 700 nm), not the brightness of the science scene. Detector noise is on in the loop.</li>
<li>One seed (1) and one realization. A seed-2 run of the baseline is a sensitivity check only (see Methods &amp; Limits); no ensemble uncertainty is shown.</li>
</ul>`;
}

// ---------------------------------------------------------------------------
// Playback

function setPosition(position) {
  state.position = Math.max(0, Math.min(MOVIE_FRAMES - 1, position));
  renderFrame();
}

function pause() {
  state.playing = false;
  clearTimeout(state.timer);
  $("btn-play").setAttribute("aria-pressed", "false");
  $("btn-play").textContent = "Play";
}

function play() {
  if (state.psfMode === "average" || !state.case) return;
  if (state.position >= MOVIE_FRAMES - 1) setPosition(0);
  state.playing = true;
  state.nextAt = null;
  $("btn-play").setAttribute("aria-pressed", "true");
  $("btn-play").textContent = "Pause";
  schedule();
}

// A timer (not requestAnimationFrame) so playback also advances in a
// throttled or background tab; each step shows the next recorded frame.
// Steps are scheduled against a fixed timeline, so render time does not
// lengthen the period (review round 2, R2-F02); if the page falls more than a
// period behind, the timeline restarts instead of skipping frames.
function schedule() {
  clearTimeout(state.timer);
  if (!state.playing) return;
  const period = 1000 / Number($("speed").value);
  const now = performance.now();
  state.nextAt = state.nextAt == null || state.nextAt < now - period ? now + period : state.nextAt + period;
  state.timer = setTimeout(tick, Math.max(0, state.nextAt - now));
}

// Exactly one recorded movie frame per tick: playback never skips a frame
// when the timer runs late (review round 1, R1-F11); a late timer only makes
// the display slower, never different.
function tick() {
  if (!state.playing) return;
  if (state.position + 1 >= MOVIE_FRAMES - 1) { setPosition(MOVIE_FRAMES - 1); pause(); return; }
  setPosition(state.position + 1);
  schedule();
}

function setPsfMode(mode) {
  state.psfMode = mode;
  const average = mode === "average";
  if (average) pause();
  for (const id of ["btn-restart", "btn-prev", "btn-play", "btn-next", "seek", "speed"]) $(id).disabled = average;
  const note = $("mode-note");
  note.hidden = !average;
  note.textContent = average
    ? "Post-burn-in average: both images are the equal-weight means of frames 40–179 (140 samples). Playback and time controls are disabled; the wavefront maps stay frozen at the selected frame and the curves keep its cursor. Switch back to Instantaneous to replay."
    : "";
  renderFrame();
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
function wantsResults() { return location.hash === "#results" || location.hash === "#methods" || location.hash.startsWith("#result-"); }

function revealHash() {
  if (!location.hash.startsWith("#result-")) return;
  const target = document.getElementById(location.hash.slice(1));
  if (target) target.scrollIntoView({ behavior: "instant", block: "start" });
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
  const m = state.manifest; const d = state.diagnostics;
  const seed2 = d.seed2_sensitivity.summary;
  const base = m.summaries[m.default_case];
  $("methods-2m").innerHTML = `
<li>Profile <code>det_emccd_2m_synthetic@1</code> (native optics, 2 m, 52 pupil samples, 5 × 5 lenslets and actuators, 700 nm WFS, synthetic EMCCD with noise on, TSVD reconstructor, leaky integrator). Explorer overrides: 180 frames, burn-in 40, root seed 1, realization 0, science at 1.65 µm. The profile resource is unchanged.</li>
<li>Eight recorded cases: baseline; r0 × 1.25 and × 0.80; guide AB magnitude 6 and 8; gain 0.10 and 0.30; queued delay 4 frames. Every other parameter is fixed. Only these nodes exist.</li>
<li>Before any trajectory ran, every atmosphere request time of each run (180 frame starts; no exposure sub-samples in this profile) was checked against the frozen-flow screen's travel budget: maximum 45.645 px of 52 px. The runtime travel equalled the admitted value.</li>
<li>Passivity: the baseline run with the explorer's observer and a run with no observer have identical loop histories (${d.passivity.identical ? "all" : "NOT all"} ${d.passivity.members_compared.length} recorded members equal).</li>
<li>Seed sensitivity (baseline, seed 2 instead of 1): mean residual ${fmt(seed2.mean_residual_rms_nm)} nm against ${fmt(base.mean_residual_rms_nm)} nm, averaged-image AO peak Strehl ${fmt(seed2.average_psf_peak_strehl_corrected, 3)} against ${fmt(base.average_psf_peak_strehl_corrected, 3)}. One extra seed shows how much a single realization can move; it is not an ensemble or a confidence interval.</li>
<li>The binary observation convolves one fixed scene with each case's two 140-sample mean PSFs (exact linear convolution, zero extension, crop to the native angular window by coordinates). One on-axis PSF is assumed across the scene: an illustration, not field-dependent imaging.</li>`;
  $("methods-identity").innerHTML = `
<li>Dataset <code>${m.dataset_id}</code>; series plan SHA-256 <code>${m.series.plan_sha256.slice(0, 16)}…</code>; runtime source <code>${m.series.source_sha?.slice(0, 12) ?? "unknown"}</code>; page code build <code>${CODE_BUILD}</code> (recorded by the dataset entry).</li>
<li>Every file is listed in the manifest with its size and SHA-256 and is checked in the browser before use; the manifest itself is bound by the entry file and an external validation record.</li>
<li>Raw numerical evidence (OPD maps, full-precision mean PSFs, histories) stays in the producer's output directory and is not part of this site.</li>`;
  $("footer-identity").textContent = `Dataset ${m.dataset_id}.`;
}

// ---------------------------------------------------------------------------
// Generated experiments (lazy, explicit)

let generateModule = null;

async function generateMode() {
  if (!generateModule) generateModule = await import("./generate.js");
  return generateModule;
}

async function connectGenerate(address) {
  try {
    (await generateMode()).connect(address);
  } catch (error) {
    $("gen-conn-state").textContent = `The generation code could not be loaded (${error.message}); a newer version of the site may have replaced it. Reload the page.`;
  }
}

function bindGenerate() {
  $("gen-connect-form").addEventListener("submit", (event) => { event.preventDefault(); connectGenerate($("gen-url").value); });
  const requested = new URLSearchParams(location.search).get("backend");
  if (requested !== null) {
    $("gen-url").value = requested;
    connectGenerate(requested);
  }
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
  $("btn-play").addEventListener("click", () => (state.playing ? pause() : play()));
  $("btn-prev").addEventListener("click", () => { pause(); setPosition(state.position - 1); });
  $("btn-next").addEventListener("click", () => { pause(); setPosition(state.position + 1); });
  $("btn-restart").addEventListener("click", () => { pause(); setPosition(0); });
  $("seek").addEventListener("input", (event) => { pause(); setPosition(Number(event.target.value)); });
  for (const input of document.querySelectorAll('input[name="psf-mode"]')) input.addEventListener("change", (event) => setPsfMode(event.target.value));
  $("zoom").addEventListener("change", (event) => document.querySelector(".binary").classList.toggle("fullwindow", event.target.checked));
  $("frame-table").closest("details").addEventListener("toggle", () => state.case && renderFrameTable(false));
  const redrawCharts = () => state.case && renderCharts(frameIndex());
  const observed = ["chart-rms", "chart-strehl", "chart-valid"].map((id) => redrawWhenResized($(id), redrawCharts)).every(Boolean);
  if (!observed) window.addEventListener("resize", redrawCharts);
  if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) $("speed").value = "2";
  const results = $("results");
  if ("IntersectionObserver" in window) {
    new IntersectionObserver((entries) => { if (entries.some((e) => e.isIntersecting)) loadResults(); }, { rootMargin: "200px" }).observe(results);
  }
  window.addEventListener("hashchange", () => { if (wantsResults()) loadResults(); });
}

async function start() {
  bindControls();
  bindGenerate();
  for (const id of ["btn-restart", "btn-prev", "btn-play", "btn-next", "seek", "speed"]) $(id).disabled = true;
  try {
    const { manifest, manifestUrl } = await loadEntry();
    state.manifest = manifest; state.manifestUrl = manifestUrl;
    const [display, scene, diagnostics] = await Promise.all([
      fetchVerifiedJson(manifest.display, manifestUrl),
      fetchVerifiedJson(manifest.scene, manifestUrl),
      fetchVerifiedJson(manifest.diagnostics, manifestUrl),
    ]);
    require(display.value.schema === "ao-explorer.display.v1", "unsupported display schema");
    require(scene.value.schema === "ao-explorer.scene-export.v1" && scene.value.scene.total_flux > 0.999999999999, "unsupported or invalid scene");
    const [sceneWavelength, supported] = wavelengthPair(scene.value.scene.wavelength_m, SCIENCE_WAVELENGTH_M);
    require(scene.value.scene.wavelength_m === SCIENCE_WAVELENGTH_M, `the scene is at ${sceneWavelength}, not ${supported}`);
    state.display = display.value; state.scene = scene.value; state.sceneUrl = scene.url; state.diagnostics = diagnostics.value;
    const sceneImage = await fetchVerified(scene.value.display.image, scene.url, { expectType: "image/png" });
    state.sceneImageBuffer = sceneImage.buffer;
    buildGroups();
    setupColorbars();
    renderMethods();
    const requested = new URLSearchParams(location.search).get("case");
    for (const id of ["btn-restart", "btn-prev", "btn-play", "btn-next", "seek", "speed"]) $(id).disabled = false;
    await selectCase(manifest.default_case);
    if (requested && requested !== manifest.default_case) {
      if (manifest.cases[requested]) await selectCase(requested);
      else showError(`The requested case “${requested}” is not a recorded case of this dataset.`, " Only the listed scenario buttons exist; the baseline is shown.");
    }
    if (wantsResults()) loadResults();
  } catch (error) {
    setStatus("The dataset could not be loaded.");
    showError(`The 2 m experiment could not be loaded: ${error.message}`, " Nothing from an unverified or incomplete bundle is shown.");
  }
}

start();
