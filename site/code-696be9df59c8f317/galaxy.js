// Observed galaxy template: the central region of NGC 1705 in the LEGUS
// HST/WFC3 F814W mosaic, at its own angular scale, seen through each case's
// recorded PSFs (scripts/ao_explorer/galaxy_export.py).  The template keeps
// Hubble's resolution and residual noise; the PSFs add the simulated blur.
//
// The browser only selects and replays precomputed, verified images.  It
// never convolves, interpolates, draws noise or normalizes an image: every
// image uses the one display scale recorded in the galaxy manifest.  Sampled
// playback maps elapsed presentation time onto the recorded sample
// timestamps and holds each retained sample until the next retained
// timestamp; a slower pass or a loop neither adds samples nor lengthens the
// simulated interval.  The galaxy data are an additive derivative with their
// own manifest, bound by the dataset entry to the published dataset.  The
// frame count, displayed samples, analysis window and playback durations come
// from that manifest and must equal the dataset's own time domain.
//
// This panel keeps no clock of its own: the case, the displayed frame, the
// play/pause state, the duration, the view mode and the loop are those of
// playback.js, shared with the main viewer.  Until the selected case's galaxy
// assets are verified the panel shows a loading state, never another case.

import { fetchVerifiedImage, fetchVerifiedJson, require } from "./integrity.js";
import * as playback from "./playback.js";

const SUPPORTED_ENTRY = "ao-explorer.galaxy-entry.v3";
const SUPPORTED_MANIFEST = "ao-explorer.galaxy-manifest.v3";
const SUPPORTED_SCENE_EXPORT = "ao-explorer.galaxy-scene-export.v2";
const SUPPORTED_SCENE = "ao-explorer.observed-template.v1";
const SUPPORTED_OBSERVATION = "ao-explorer.galaxy-observation.v3";
const FRAME_PERIOD_S = 0.001;
const CACHE_LIMIT = 2;
const ROLES = ["uncorrected", "corrected"];
const FLUX_ATOL = 1e-12;
const CONTROLS = ["galaxy-restart", "galaxy-prev", "galaxy-play", "galaxy-next", "galaxy-seek", "galaxy-duration", "galaxy-loop"];

const $ = (id) => document.getElementById(id);
const g = {
  context: null, manifest: null, manifestUrl: null, scene: null, sourceBitmap: null,
  ready: false, visible: false, requested: null, case: null, cache: new Map(), controller: null, generation: 0,
};
const pb = () => playback.snapshot();

// The validated time domain (galaxy manifest, equal to the dataset's).
const SAMPLES = () => g.manifest.time_domain.display_count;
const FRAMES = () => g.manifest.time_domain.frames;
const START = () => g.manifest.time_domain.analysis_window[0];
const COUNT = () => g.manifest.time_domain.analysis_count;

// Manifest, scene and case validation

function validateManifest(m, entry, context) {
  require(m.schema === SUPPORTED_MANIFEST, `unsupported galaxy manifest schema ${m.schema}`);
  require(m.derived_id === entry.derived_id, "the galaxy manifest and the dataset entry name different derived sets");
  require(m.parent && m.parent.dataset_id === context.datasetId && m.parent.manifest_sha256 === context.manifestSha256, "the galaxy observations were derived from another published dataset");
  require(m.parent.binary_scene_id === context.binarySceneId, "the galaxy manifest names another binary scene");
  const ids = Object.keys(m.cases || {});
  require(ids.length === context.caseIds.length && context.caseIds.every((id) => m.cases[id] && m.cases[id].galaxy && m.cases[id].galaxy.media_type === "application/json"), "the galaxy observations do not cover exactly the recorded cases");
  const s = m.display && m.display.scale;
  require(s && s.stretch === "asinh" && s.softening_beta > 0 && s.softening_beta < 1 && s.reference_cell_flux > 0, "unsupported galaxy display scale");
  require(Array.isArray(s.lut_rgb_hex) && s.lut_rgb_hex.length === 256, "the galaxy colour table is incomplete");
  require(Array.isArray(s.colorbar_ticks) && s.colorbar_ticks.every((t) => t >= 0 && t <= 1), "the galaxy colour bar has no valid ticks");
  const w = m.display.window;
  require(w && w.cells[0] === w.cells[1] && w.cells[0] > 0 && w.cell_mas > 0, "the galaxy display window is incomplete");
  const t = m.time_domain; const d = context.timeDomain;
  for (const key of ["frames", "frame_period_s", "startup_exclusion_frames", "analysis_count", "display_count", "display_rule"]) require(t && t[key] === d[key], `the galaxy ${key} differs from the dataset's time domain`);
  for (const key of ["physical_interval_s", "analysis_window", "display_indices", "display_times_s"]) require(t[key].join() === d[key].join(), `the galaxy ${key} differs from the dataset's time domain`);
  require(Math.abs(t.frame_period_s - FRAME_PERIOD_S) < 1e-15, "unexpected galaxy frame period");
  const p = m.playback;
  require(p && Array.isArray(p.interval_s) && p.interval_s.join() === t.physical_interval_s.join(), "the playback interval is not the recorded physical interval");
  require(JSON.stringify(p) === JSON.stringify(context.playback), "the galaxy playback differs from the dataset's playback");
  require(Array.isArray(p.durations_s) && p.durations_s.length > 0 && p.durations_s.every((x) => Number.isFinite(x) && x > 0) && p.durations_s.includes(p.default_duration_s), "unsupported playback durations");
  require(p.interpolation === "none", "the galaxy playback must not interpolate");
  require(Array.isArray(m.limitations) && m.limitations.length > 0, "the galaxy manifest records no limitations");
}

function validateScene(value, context) {
  require(value.schema === SUPPORTED_SCENE_EXPORT, `unsupported galaxy scene export ${value.schema}`);
  const sc = value.scene;
  require(sc.schema === SUPPORTED_SCENE, `unsupported galaxy template ${sc.schema}`);
  require(sc.product && sc.product.header && sc.product.header.PHOTMODE && /F814W/.test(sc.product.header.PHOTMODE), "the template is not the F814W science product");
  require(sc.target.kernel_grid_id === context.gridId, "the template is not on the lattice of the published PSFs");
  require(sc.target.angular_scale_factor === 1, "the template's angular scale is not the observed one");
  require(sc.scene_id !== context.binarySceneId, "the template reuses the binary scene identity");
  require(sc.normalization && sc.normalization.e_per_s_per_unit > 0, "the template normalization is not recorded");
  require(Math.abs(sc.target.step_mas[0] - g.manifest.display.window.cell_mas) < 1e-9, "the template step differs from the display cell");
  require(sc.peak_cell === g.manifest.display.scale.reference_cell_flux, "the display reference is not the template's brightest cell");
  require(value.display && value.display.image && value.display.image.media_type === "image/png", "the template has no display image");
}

function sameNumbers(a, b, tolerance) {
  return Array.isArray(a) && Array.isArray(b) && a.length === b.length && a.every((v, i) => Math.abs(v - b[i]) <= tolerance);
}

function validateFlux(flux, count, label) {
  const errors = count === null ? [flux.full_flux_error] : flux.full_flux_error;
  const retained = count === null ? [flux.window_fraction] : flux.window_fraction;
  require(Array.isArray(errors) && errors.length === (count ?? 1) && errors.every((v) => Number.isFinite(v) && Math.abs(v) <= FLUX_ATOL), `${label}: flux does not equal template x kernel flux`);
  require(retained.every((v) => Number.isFinite(v) && v > 0 && v <= 1 + FLUX_ATOL), `${label}: crop accounting is incomplete`);
}

function validateCase(id, c, info) {
  require(c.schema === SUPPORTED_OBSERVATION, `galaxy ${id}: unsupported schema ${c.schema}`);
  require(c.case_id === id, `galaxy file names ${c.case_id}, expected ${id}`);
  require(c.scene_id === g.scene.scene.scene_id && c.kernel_grid_id === g.scene.scene.target.kernel_grid_id, `galaxy ${id}: another template or grid`);
  const s = c.sampled;
  require(s.count === SAMPLES() && s.retained_observations === FRAMES() && s.burn_in_frames === START() && Math.abs(s.frame_period_s - FRAME_PERIOD_S) < 1e-15, `galaxy ${id}: not the ${SAMPLES()} displayed samples of ${FRAMES()} retained observations`);
  require(s.frame_indices.join() === info.movieIndices.join(), `galaxy ${id}: sample indices differ from the case's movie indices`);
  require(sameNumbers(s.time_s, info.movieTimes, 1e-12) && s.time_s.every((t, i) => !i || t > s.time_s[i - 1]), `galaxy ${id}: sample times differ from the case's movie times`);
  require(s.time_s[0] === 0 && s.time_s[SAMPLES() - 1] < g.manifest.playback.interval_s[1], `galaxy ${id}: samples lie outside the playback interval`);
  for (const role of ROLES) {
    const r = s.roles[role];
    require(r && r.atlas && r.atlas.media_type === "image/png" && r.rectangles_xywh.length === SAMPLES() && r.rectangles_xywh.every((q) => q.length === 4), `galaxy ${id}: incomplete ${role} atlas`);
    validateFlux(r.flux.displayed, SAMPLES(), `galaxy ${id} ${role} samples`);
    require(r.flux.all_frames.count === FRAMES() && Math.abs(r.flux.all_frames.max_abs_full_flux_error) <= FLUX_ATOL, `galaxy ${id} ${role}: flux accounting of all ${FRAMES()} observations is incomplete`);
    const m = c.mean.roles[role];
    require(m && m.image && m.image.media_type === "image/png", `galaxy ${id}: missing ${role} mean image`);
    validateFlux(m.flux, null, `galaxy ${id} ${role} mean`);
    // The mean kernel is the same saved analysis-window mean that the published binary observation used.
    require(m.kernel_array_sha256 === info.meanParentSha256[role], `galaxy ${id}: ${role} mean kernel differs from the published ${COUNT()}-frame mean`);
  }
  require(c.mean.window[0] === START() && c.mean.window[1] === FRAMES() && c.mean.sample_count === COUNT() && c.mean.weights === "equal", `galaxy ${id}: mean is not the [${START()}, ${FRAMES()}) equal-weight mean`);
  require(c.display.scale_revision === g.manifest.display.revision, `galaxy ${id}: another display scale`);
}

// Loading

export async function initGalaxy(entry, entryUrl, context) {
  bindControls();
  setControlsDisabled(true);
  if (!entry.galaxy) {
    setStatus("This dataset entry names no galaxy observations.");
    return;
  }
  try {
    require(entry.galaxy.schema === SUPPORTED_ENTRY, `unsupported galaxy entry ${entry.galaxy.schema}`);
    g.context = context;
    const ref = { href: entry.galaxy.manifest, bytes: entry.galaxy.manifest_bytes, sha256: entry.galaxy.manifest_sha256, media_type: "application/json" };
    const { url, value } = await fetchVerifiedJson(ref, entryUrl);
    validateManifest(value, entry.galaxy, context);
    g.manifest = value; g.manifestUrl = url;
    const scene = await fetchVerifiedJson(value.scene, url);
    validateScene(scene.value, context);
    const source = await fetchVerifiedImage(scene.value.display.image, scene.url);
    g.scene = scene.value; g.sourceBitmap = source.bitmap;
    setupDurations();
    setupColorbar();
    renderNotes();
    g.ready = true;
    setStatus(g.visible ? "Loading the galaxy observation…" : "The galaxy observation loads when this panel is in view.");
    playback.subscribe(onPlayback);
    observeVisibility();
    if (g.requested) loadRequested();
  } catch (error) {
    setStatus("The galaxy observation could not be loaded.");
    showError(`The galaxy observation could not be loaded: ${error.message}`, "The rest of the page is unaffected.");
  }
}

// Called whenever the page installs a case; the galaxy follows it lazily and
// shows a loading state, not the previous case, until it has the new one.
export function showGalaxyCase(info) {
  g.requested = info;
  if (!g.ready) return;
  if (!g.case || g.case.id !== info.id) showPending();
  loadRequested();
}

function observeVisibility() {
  const panel = $("galaxy-panel");
  if (!("IntersectionObserver" in window)) { g.visible = true; return; }
  new IntersectionObserver((entries) => {
    if (entries.some((e) => e.isIntersecting) && !g.visible) { g.visible = true; loadRequested(); }
  }, { rootMargin: "200px" }).observe(panel);
}

async function fetchCase(id, info, signal) {
  const item = g.manifest.cases[id];
  require(item, `case ${id} has no galaxy observation`);
  const { url, value: c, buffer } = await fetchVerifiedJson(item.galaxy, g.manifestUrl, { signal });
  validateCase(id, c, info);
  const atlases = await Promise.all(ROLES.map((role) => fetchVerifiedImage(c.sampled.roles[role].atlas, url, { signal })));
  const means = await Promise.all(ROLES.map((role) => fetchVerifiedImage(c.mean.roles[role].image, url, { signal })));
  return {
    id, label: item.label, json: c, text: new TextDecoder().decode(buffer),
    atlases: { uncorrected: atlases[0].bitmap, corrected: atlases[1].bitmap },
    means: { uncorrected: means[0].bitmap, corrected: means[1].bitmap },
  };
}

function remember(id, data) {
  g.cache.delete(id);
  g.cache.set(id, data);
  while (g.cache.size > CACHE_LIMIT) {
    const oldest = g.cache.keys().next().value;
    if (oldest === g.case?.id) { const keep = g.cache.get(oldest); g.cache.delete(oldest); g.cache.set(oldest, keep); continue; }
    g.cache.delete(oldest);
  }
}

// Every request supersedes the earlier ones: a pending load is aborted and
// its generation retired, so a late response is never installed.
async function loadRequested() {
  if (!g.ready || !g.visible || !g.requested) return;
  const info = g.requested;
  const generation = ++g.generation;
  if (g.controller) { g.controller.abort(); g.controller = null; }
  if (g.case && g.case.id === info.id) { hideError(); setStatus(""); render(); return; }
  const controller = new AbortController();
  g.controller = controller;
  showPending();
  setStatus(`Loading the galaxy observation for “${info.label}”…`);
  hideError();
  try {
    const data = g.cache.get(info.id) || (await fetchCase(info.id, info, controller.signal));
    if (generation !== g.generation) return;
    remember(info.id, data);
    install(data);
    setStatus("");
  } catch (error) {
    if (error.name === "AbortError" || generation !== g.generation) return;
    showError(`Could not show the galaxy for “${info.label}”: ${error.message}`, "No galaxy image is shown for this case; the rest of the page is unaffected.");
    setStatus("Galaxy load failed.");
  } finally {
    if (generation === g.generation) g.controller = null;
  }
}

// Display

function install(data) {
  g.case = data;
  $("galaxy-meta").textContent = data.text;
  render();
}

function draw(canvasId, bitmap, rect) {
  const canvas = $(canvasId); const ctx = canvas.getContext("2d");
  ctx.imageSmoothingEnabled = false;
  ctx.clearRect(0, 0, canvas.width, canvas.height);
  if (rect) ctx.drawImage(bitmap, rect[0], rect[1], rect[2], rect[3], 0, 0, canvas.width, canvas.height);
  else ctx.drawImage(bitmap, 0, 0, canvas.width, canvas.height);
  drawScaleBar(ctx, canvas);
}

// Display marks only, drawn over the images: a scale bar of the recorded
// angular length (same in all three panels) and, on the template, the box of
// cells touching the enlarged saturation envelope (not the exact extent).
function drawScaleBar(ctx, canvas) {
  const w = g.manifest.display.window;
  const perCell = canvas.width / w.cells[0];
  const length = (g.manifest.display.scale_bar_arcsec * 1000 / w.cell_mas) * perCell;
  const x = 10; const y = canvas.height - 12;
  ctx.save();
  ctx.lineWidth = 5; ctx.strokeStyle = "rgba(0,0,0,0.7)";
  ctx.beginPath(); ctx.moveTo(x, y); ctx.lineTo(x + length, y); ctx.stroke();
  ctx.lineWidth = 2; ctx.strokeStyle = "#ffffff";
  ctx.beginPath(); ctx.moveTo(x, y); ctx.lineTo(x + length, y); ctx.stroke();
  ctx.font = "bold 16px sans-serif"; ctx.lineWidth = 3; ctx.strokeStyle = "rgba(0,0,0,0.7)"; ctx.fillStyle = "#ffffff";
  const label = `${g.manifest.display.scale_bar_arcsec}″`;
  ctx.strokeText(label, x, y - 7); ctx.fillText(label, x, y - 7);
  ctx.restore();
}

function drawSaturatedBox(canvasId) {
  const box = g.manifest.display.window.saturation_envelope_box_cells;
  if (!box) return;
  const canvas = $(canvasId); const ctx = canvas.getContext("2d");
  const cells = g.manifest.display.window.cells[0]; const s = canvas.width / cells;
  ctx.save();
  ctx.setLineDash([4, 3]); ctx.lineWidth = 1.5; ctx.strokeStyle = "#7fe3ff";
  // Box rows are counted from the south edge; canvas rows from the north edge.
  ctx.strokeRect(box.x[0] * s - 2, (cells - box.y[1]) * s - 2, (box.x[1] - box.x[0]) * s + 4, (box.y[1] - box.y[0]) * s + 4);
  ctx.restore();
}

const ms = (seconds) => `${Math.round(seconds * 1000)} ms`;
const percent = (value) => `${(value * 100).toFixed(2)} %`;

// Renders the shared frame and mode, or the loading state while the shared
// case's assets are not installed here.
function render(p = pb()) {
  const c = g.case;
  if (!c || c.id !== p.caseId) { showPending(); return; }
  $("galaxy-panel").setAttribute("aria-busy", "false");
  draw("galaxy-source", g.sourceBitmap);
  drawSaturatedBox("galaxy-source");
  const s = c.json.sampled;
  if (p.mode === "average") {
    for (const role of ROLES) draw(`galaxy-${role}`, c.means[role]);
  } else {
    for (const role of ROLES) draw(`galaxy-${role}`, c.atlases[role], s.roles[role].rectangles_xywh[p.position]);
  }
  updateLabels(p);
}

function showPending() {
  const info = g.requested;
  if (!info) return;
  $("galaxy-panel").setAttribute("aria-busy", "true");
  if (g.sourceBitmap) { draw("galaxy-source", g.sourceBitmap); drawSaturatedBox("galaxy-source"); }
  for (const role of ROLES) { const canvas = $(`galaxy-${role}`); canvas.getContext("2d").clearRect(0, 0, canvas.width, canvas.height); }
  const waiting = g.visible ? `Loading the galaxy observation for “${info.label}”…` : `The galaxy observation for “${info.label}” loads when this panel is in view.`;
  $("galaxy-unc-title").textContent = "HST image + uncorrected PSF";
  $("galaxy-ao-title").textContent = "HST image + AO-corrected PSF";
  $("galaxy-unc-sub").textContent = waiting;
  $("galaxy-ao-sub").textContent = waiting;
  $("galaxy-readout").textContent = `Loading images for “${info.label}”. Once checked, they will follow the main viewer’s frame and image mode.`;
}

function updateLabels(p) {
  const c = g.case.json; const s = c.sampled;
  const [lo, hi] = p.interval;
  if (p.mode === "average") {
    const mean = c.mean.roles;
    const frames = `frames ${START()}–${FRAMES() - 1}`;
    $("galaxy-unc-title").textContent = "HST image + uncorrected PSF (analysis-window mean)";
    $("galaxy-ao-title").textContent = "HST image + AO-corrected PSF (analysis-window mean)";
    $("galaxy-unc-sub").textContent = `${g.case.label}: saved mean PSF of ${frames} (${COUNT()} PSFs); ${percent(mean.uncorrected.flux.window_fraction)} of the convolved template flux falls inside the native ±4.3″ window`;
    $("galaxy-ao-sub").textContent = `${g.case.label}: saved mean PSF of ${frames} (${COUNT()} PSFs); ${percent(mean.corrected.flux.window_fraction)} of the convolved template flux falls inside the native ±4.3″ window`;
    $("galaxy-readout").textContent = `Analysis-window mean · ${frames} · ${COUNT()} equal-weight PSFs per image · static (no timeline)`;
  } else {
    const k = s.frame_indices[p.position]; const t = s.time_s[p.position];
    const phase = k < START() ? `startup exclusion (frames 0–${START() - 1})` : "analysis window";
    $("galaxy-unc-title").textContent = "HST image + uncorrected PSF";
    $("galaxy-ao-title").textContent = "HST image + AO-corrected PSF";
    $("galaxy-unc-sub").textContent = `${g.case.label}: same atmosphere, zero DM, frame ${k}; ${percent(s.roles.uncorrected.flux.displayed.window_fraction[p.position])} of the convolved template flux inside the native window`;
    $("galaxy-ao-sub").textContent = `${g.case.label}: pre-update residual, frame ${k}; ${percent(s.roles.corrected.flux.displayed.window_fraction[p.position])} of the convolved template flux inside the native window`;
    const until = p.position + 1 < SAMPLES() ? `held until the next displayed sample at ${ms(p.holdEnd)}` : `the last frame, held for its 1 ms period to ${ms(hi)}`;
    $("galaxy-readout").textContent = `Sample ${p.position + 1} of ${SAMPLES()} shown (of ${FRAMES()} computed) · frame ${k} · simulated time ${ms(t)} of ${ms(lo)}–${ms(hi)} (${until}) · ${phase} · same frame as the main viewer`;
    $("galaxy-seek").setAttribute("aria-valuetext", `sample ${p.position + 1} of ${SAMPLES()}, frame ${k}, ${ms(t)}`);
  }
}

// The options only; the selected duration is the shared clock's.
function setupDurations() {
  const p = g.manifest.playback;
  $("galaxy-duration").innerHTML = p.durations_s.map((d) => `<option value="${d}">${d} s</option>`).join("");
  $("galaxy-seek").max = String(SAMPLES() - 1);
}

function setupColorbar() {
  const s = g.manifest.display.scale;
  const canvas = $("cbar-galaxy"); const ctx = canvas.getContext("2d");
  for (let i = 0; i < 200; i += 1) { ctx.fillStyle = s.lut_rgb_hex[Math.round((1 - i / 199) * 255)]; ctx.fillRect(0, i, canvas.width, 1); }
  const v = (f) => Math.asinh(f / s.softening_beta) / Math.asinh(1 / s.softening_beta);
  $("cbar-galaxy-labels").innerHTML = s.colorbar_ticks.map((f) => `<span style="top:${((1 - v(f)) * 100).toFixed(1)}%">${f}</span>`).join("");
  $("cbar-galaxy-note").textContent = `Relative flux per cell, as a fraction of the template's brightest cell; asinh stretch (β = ${s.softening_beta}). One scale for all three panels, every sample, both modes and every case.`;
}

const sentence = (text) => `${text.charAt(0).toUpperCase()}${text.slice(1)}`;

function escapeHtml(text) { return String(text).replace(/[&<>"]/g, (ch) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", "\"": "&quot;" }[ch])); }

function sexagesimal(deg, hours) {
  const value = hours ? deg / 15 : Math.abs(deg);
  const a = Math.floor(value); const b = Math.floor((value - a) * 60); const c = ((value - a) * 60 - b) * 60;
  const sign = hours ? "" : deg < 0 ? "−" : "+";
  return `${sign}${String(a).padStart(2, "0")}${hours ? "h" : "°"}${String(b).padStart(2, "0")}${hours ? "m" : "′"}${c.toFixed(hours ? 2 : 1).padStart(hours ? 5 : 4, "0")}${hours ? "s" : "″"}`;
}

function renderNotes() {
  const sc = g.scene.scene; const pr = sc.product; const h = pr.header; const q = sc.quality; const t = sc.target;
  const w = g.manifest.display.window; const res = sc.observational_psf.indicative_resolution;
  const fmt = (v, d = 0) => Number(v).toFixed(d);
  $("galaxy-label").textContent = `I convolved an HST/WFC3 F814W image of NGC 1705 (LEGUS) with the simulated 1.65 µm PSFs, keeping its angular scale. Hubble’s original resolution and noise remain. This illustration applies one on-axis PSF across the ${fmt(w.extent_arcsec, 1)}″ field; it uses relative flux and adds no noise.`;
  $("galaxy-source-caption").textContent = `HST F814W morphology at angular scale 1.0 (one cell = ${fmt(w.cell_mas, 1)} mas), north up, east left; fixed for every sample and case. White bar: ${g.manifest.display.scale_bar_arcsec}″. Dashed box: enlarged envelope around the saturated core of NGC 1705-1 (the saturated values are unreliable).`;
  const rows = [
    ["Data product", `<a href="${escapeHtml(pr.url)}" rel="noopener">${escapeHtml(pr.name)}</a> (${escapeHtml(pr.version)}, ${escapeHtml(pr.collection)}); SHA-256 <code>${pr.sha256.slice(0, 16)}…</code>; retrieved ${escapeHtml(pr.retrieved_utc)}`],
    ["Instrument and band", `HST WFC3/UVIS, ${escapeHtml(h.PHOTMODE)} (pivot ${fmt(h.PHOTPLAM)} Å); programme ${h.PROPOSID} (PI ${escapeHtml(h.PR_INV_L)}); ${fmt(h.EXPTIME)} s in ${h.NCOMBINE} exposures; science HDU ${pr.science_hdu}, ${escapeHtml(pr.units)}`],
    ["Original sampling", `${fmt(sc.wcs.source_scale_mas[0], 2)} mas per pixel, TAN projection, distortion removed by drizzle (${escapeHtml(h.D001KERN)} kernel, pixfrac ${h.D001PIXF}); grid rotation ${sc.wcs.rotation_deg.toExponential(1)}°`],
    ["Centre", `${sexagesimal(sc.centre.ra_deg, true)} ${sexagesimal(sc.centre.dec_deg, false)} (ICRS): ${escapeHtml(sc.centre.method)}`],
    ["Template grid", `${t.cells[0]} × ${t.cells[1]} cells of ${fmt(t.step_mas[0], 3)} mas (${fmt(t.extent_arcsec[0], 1)}″), angular scale factor ${t.angular_scale_factor}; +x west, +y north; local north differs by ${fmt(sc.wcs.local_north_rotation_deg, 3)}°. Mosaic pixels x ${t.source_pixel_bounds_xy_0based[0].join("–")}, y ${t.source_pixel_bounds_xy_0based[1].join("–")}. Observation crop: central ${w.cells[0]} × ${w.cells[1]} cells (${fmt(w.extent_arcsec, 2)}″)`],
    ["Reprojection", `${escapeHtml(sc.resampling.method)}; relative flux error ${sc.resampling.conservation_relative_error.toExponential(1)}`],
    ["Sky", `Pipeline sky-subtracted; residual ${sc.sky.residual_median_e_per_s_per_px.toExponential(2)} e⁻/s per pixel beyond 120″, not subtracted (would change the template flux by ${fmt(sc.sky.template_flux_fraction_if_subtracted * 100, 2)} %): ${escapeHtml(sc.sky.reason)}`],
    ["Quality", `Core of NGC 1705-1 saturated in all ${q.exposures_covering_min_max[1]} exposures: about ${q.saturated_core.pixels} mosaic pixels flagged in every exposure (nearest-pixel mapping, bounding box ${q.saturated_core.bounding_box_arcsec.map((v) => v.toFixed(2)).join("″ × ")}″), an approximate extent. The dashed box marks a deliberately enlarged envelope (${q.conservative_envelope.pixels} pixels, flags dilated by one pixel). ${escapeHtml(sentence(q.flux_note))}. ${q.conservative_counts.pixels_without_usable_exposure_outside_envelope} further pixels lack a usable exposure (conservative count). ${escapeHtml(sentence(q.treatment))}. ${escapeHtml(sentence(q.membership))}.`],
    ["Noise", `${escapeHtml(sc.noise.policy)}; ${sc.noise.negative_cells} negative cells`],
    ["Hubble PSF", `${escapeHtml(sc.observational_psf.policy)}; ${escapeHtml(sc.observational_psf.model)}. Indicative FWHM ${res.fwhm_mas_median ? fmt(res.fwhm_mas_median) : "—"} mas (quartiles ${res.fwhm_mas_quartiles ? res.fwhm_mas_quartiles.map((v) => fmt(v)).join("–") : "—"}) from ${res.sources} isolated point sources: ${escapeHtml(res.caveat)}`],
    ["Normalization", `unit total over the ${fmt(t.extent_arcsec[0], 1)}″ cutout; 1 unit = ${fmt(sc.normalization.e_per_s_per_unit)} e⁻/s in F814W`],
  ];
  const list = (items) => items.map((r) => `<li>${escapeHtml(r.citation)} — <a href="${escapeHtml(r.url)}" rel="noopener">${escapeHtml(r.url)}</a> (${escapeHtml(r.used_for)}).</li>`).join("");
  const v = g.manifest.visual_reference;
  $("galaxy-notes").innerHTML = `
<p class="table-title" id="galaxy-table-title">Observed template: source and preparation</p>
<div class="table-scroll" role="region" tabindex="0" aria-labelledby="galaxy-table-title"><table aria-labelledby="galaxy-table-title"><tbody>${rows.map((r) => `<tr><th scope="row">${r[0]}</th><td class="shape">${r[1]}</td></tr>`).join("")}</tbody></table></div>
<ul>
<li>Each image is the exact linear convolution of the fixed template with one saved PSF (zero-padded FFT, no wraparound), cropped to the native window by coordinates without renormalization; the template extends to twice the PSF window so light from outside the field still reaches it. All ${FRAMES()} instantaneous PSF pairs were convolved and kept at full precision; sampled mode shows ${SAMPLES()} of them (${escapeHtml(g.manifest.time_domain.display_rule)}). Mean mode uses the saved ${COUNT()}-frame mean PSFs of frames ${START()}–${FRAMES() - 1}, which for the fixed template equals the mean of the ${COUNT()} corresponding observations.</li>
<li>The prepared numerical template is reused unchanged (identity <code>${escapeHtml(g.manifest.template_reuse.scene_id.slice(0, 16))}…</code>, array SHA-256 <code>${escapeHtml(g.manifest.template_reuse.template_array_sha256.slice(0, 16))}…</code>); the HST products were not re-read for this dataset.</li>
<li>Response: the output keeps Hubble's effective F814W response and noise, adds the cell response of the reprojection once, and adds the simulated PSF. The AO-corrected panel cannot recover detail absent from the Hubble image.</li>
<li>The template is a science-channel scene only: the guide source, wavefront-sensor inputs and controller are those of the recorded run. Template identity <code>${sc.scene_id.slice(0, 16)}…</code>, distinct from the binary scene.</li>
${g.manifest.limitations.map((x) => `<li>${escapeHtml(x)}</li>`).join("")}
</ul>
<p>Credit: ${escapeHtml(g.manifest.credit)} Visual reference only (not the numerical input): <a href="${escapeHtml(v.url)}" rel="noopener">${escapeHtml(v.title)}</a>, ${escapeHtml(v.credit)}.</p>
<p>Data references:</p>
<ul>${list(g.manifest.data_references)}</ul>
<p>Methodological references (${escapeHtml(g.manifest.reference_note)}):</p>
<ul>${list(g.manifest.references)}</ul>
<p>Derived set <code>${escapeHtml(g.manifest.derived_id)}</code> from dataset <code>${escapeHtml(g.manifest.parent.dataset_id)}</code>; the arrays and images were generated by exporter code <code>${g.manifest.code_identity.sha256.slice(0, 16)}…</code>.${revisionNote()}</p>`;
}

// A metadata revision changes records only; the generation provenance above stays the generator's.
function revisionNote() {
  const r = g.manifest.metadata_revision;
  if (!r) return "";
  return ` This is a metadata revision (<code>${escapeHtml(r.revision)}</code>) of <code>${escapeHtml(r.supersedes.derived_id)}</code>: ${escapeHtml(r.correction)} Unchanged: ${escapeHtml(r.unchanged)}.`;
}

// Playback (the shared clock of playback.js)

function syncControls(p) {
  const mean = p.mode === "average";
  setControlsDisabled(mean);
  $("galaxy-play").setAttribute("aria-pressed", String(p.playing));
  $("galaxy-play").textContent = p.playing ? "Pause" : "Play";
  $("galaxy-seek").value = String(p.position);
  $("galaxy-duration").value = String(p.duration);
  $("galaxy-loop").checked = p.loop;
  for (const input of document.querySelectorAll('input[name="galaxy-mode"]')) input.checked = input.value === (mean ? "mean" : "sampled");
  const note = $("galaxy-mode-note");
  note.hidden = !mean;
  note.textContent = mean
    ? `Analysis-window mean: both observations use the saved means of the ${COUNT()} PSFs of frames ${START()}–${FRAMES() - 1}, not the ${SAMPLES()} displayed samples. Playback is disabled here and in the main viewer; switch back to Sampled instantaneous (or Instantaneous above) to continue from the same frame.`
    : "";
  const [lo, hi] = p.interval;
  $("galaxy-playback-note").textContent = `Playback shows ${SAMPLES()} of ${FRAMES()} saved images over ${ms(lo)}–${ms(hi)} of simulated time. One pass takes ${p.duration} s (${p.slowdown.toFixed(0)}× slower), with no interpolation. These controls share the main viewer’s timeline. Looping repeats the same recording and may jump at the end.`;
}

function onPlayback(p) {
  syncControls(p);
  render(p);
}

function setControlsDisabled(disabled) { for (const id of CONTROLS) $(id).disabled = disabled; }

function bindControls() {
  $("galaxy-play").addEventListener("click", () => playback.toggle());
  $("galaxy-prev").addEventListener("click", () => playback.step(-1));
  $("galaxy-next").addEventListener("click", () => playback.step(1));
  $("galaxy-restart").addEventListener("click", () => playback.restart());
  $("galaxy-seek").addEventListener("input", (event) => playback.seek(Number(event.target.value)));
  $("galaxy-duration").addEventListener("change", (event) => playback.setDuration(Number(event.target.value)));
  $("galaxy-loop").addEventListener("change", (event) => playback.setLoop(event.target.checked));
  for (const input of document.querySelectorAll('input[name="galaxy-mode"]')) input.addEventListener("change", (event) => playback.setMode(event.target.value === "mean" ? "average" : "instantaneous"));
}

// Status and errors

function setStatus(text) { $("galaxy-status").textContent = text; }
function showError(message, detail) {
  const box = $("galaxy-error");
  box.hidden = false;
  box.innerHTML = `<strong>${escapeHtml(message)}</strong> ${detail ? escapeHtml(detail) : ""}`;
}
function hideError() { $("galaxy-error").hidden = true; $("galaxy-error").textContent = ""; }

