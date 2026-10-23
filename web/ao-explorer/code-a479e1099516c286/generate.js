// Generated-experiment mode: connects to an explicitly configured computation
// service (API ao-dynamic.api.v1), submits bounded requests, follows the job,
// and installs a completed run for replay.
//
// This module is imported only after the visitor connects (app.js), so the
// precomputed explorer makes exactly the requests it made before.  The page
// never computes AO science: every frame, metric and average comes from the
// service's numerical run, after the semantic checks of generate-contract.js
// and size/SHA-256 checks of every file.  Pending form values are separate from
// the immutable configuration of the displayed run, and every install is
// atomic and guarded by a generation token, so a late or superseded response
// can never replace a newer run or appear under its labels.

import { sha256Hex } from "./integrity.js";
import { lineChart, redrawWhenResized } from "./charts.js";
import * as C from "./generate-contract.js";

const $ = (id) => document.getElementById(id);

// Every value from the service is data.  Markup is built only through the html
// tag below, which escapes every interpolated value unless it is itself the
// result of html (review R1-F01); innerHTML is assigned only via setHtml.
class SafeHtml { constructor(text) { this.text = text; } }
const escapeHtml = (text) => String(text).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", "\"": "&quot;", "'": "&#39;" }[c]));
const renderValue = (value) => (value instanceof SafeHtml ? value.text : Array.isArray(value) ? value.map(renderValue).join("")
  : value === null || value === undefined || value === false ? "" : escapeHtml(value));
function html(strings, ...values) {
  let out = strings[0];
  values.forEach((value, index) => { out += renderValue(value) + strings[index + 1]; });
  return new SafeHtml(out);
}
function setHtml(element, safe) {
  if (!(safe instanceof SafeHtml)) throw new TypeError("markup must be built with html``");
  element.innerHTML = safe.text;
}

const STORAGE_KEY = "ao-dynamic-active-job";
const CACHE_LIMIT = 3;
const POLL_MS = 500;
const MAX_BACKOFF_MS = 5000;
const MAP_KEYS = [["atmosphere", "atmosphere_opd_m"], ["correction", "held_correction_opd_m"], ["residual", "pre_update_residual_opd_m"]];
const LOCKED_FOR_COMPARISON = ["seed", "r0_m", "r0_reference_wavelength_m", "wind_speed_m_per_s", "wind_direction_deg", "n_frames", "burn_in"];

const g = {
  base: null, info: null, connectGeneration: 0, bound: false,
  installed: null, reference: null, cache: new Map(), loadGeneration: 0, loadController: null,
  job: null, jobGeneration: 0, pollTimer: null, failures: 0,
  position: 0, playing: false, timer: null, nextAt: null, quantity: "opd", obsMode: "instantaneous",
  objectUrls: [], luts: null, offscreen: new Map(), submitting: false,
};

// ---------------------------------------------------------------------------
// Connection

function serviceBase(address) {
  const text = String(address || "").trim();
  if (!text) throw new Error("enter the address of a computation service");
  let url;
  if (text.startsWith("/") && !text.startsWith("//")) url = new URL(text, location.origin);
  else if (/^https?:\/\//i.test(text)) url = new URL(text);
  else throw new Error("the service address must start with http:// or https:// (or / for this page's own server)");
  if (url.search || url.hash) throw new Error("the service address must not contain a query or fragment");
  if (!url.pathname.endsWith("/")) url.pathname += "/";
  return new URL("api/v1/", url);
}

async function fetchJson(url, { method = "GET", body, signal, timeoutMs = 15000 } = {}) {
  const signals = [AbortSignal.timeout(timeoutMs)];
  if (signal) signals.push(signal);
  const response = await fetch(url, {
    method, cache: "no-store", credentials: "omit", signal: AbortSignal.any(signals),
    headers: body === undefined ? {} : { "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  let value = null;
  try { value = await response.json(); } catch (error) { throw new Error(`the service answered HTTP ${response.status} without valid JSON`); }
  return { status: response.status, ok: response.ok, value };
}

export async function connect(address) {
  const generation = ++g.connectGeneration;
  stopPolling();
  let base;
  try { base = serviceBase(address); } catch (error) { setConnection(`Not connected: ${error.message}.`); return; }
  setConnection(`Connecting to ${base.origin}…`);
  hideError();
  let info;
  try {
    const { ok, status, value } = await fetchJson(new URL("info", base));
    if (!ok) throw new Error(`HTTP ${status}`);
    info = value;
  } catch (error) {
    if (generation !== g.connectGeneration) return;
    disconnected(`Could not reach a computation service at ${base.origin} (${error.message}). Generation is unavailable; the precomputed experiment remains available.`);
    return;
  }
  if (generation !== g.connectGeneration) return;
  const problems = C.validateInfo(info);
  if (problems.length) {
    disconnected(`The service at ${base.origin} is not compatible with this page and was not used.`);
    showError("Incompatible computation service", problems);
    return;
  }
  g.base = base; g.info = info;
  g.luts = { opd: info.display.opd_lut_rgb_hex.map(hexRgb), intensity: info.display.intensity_lut_rgb_hex.map(hexRgb) };
  $("gen-app").hidden = false;
  $("gen-disconnect").hidden = false;
  if (!g.bound) { bindControls(); g.bound = true; }
  buildForm();
  setComputeEnabled(true);
  setConnection(`Connected to ${base.origin}: ${info.api}, service instance ${info.service.instance_id} (${info.service.kind}); worker code ${info.producer.worker.sha256.slice(0, 12)}, core package ${info.core.package_sha256.slice(0, 12)}. One numerical job runs at a time; at most ${info.limits.max_active_jobs} may wait or run.`);
  refreshRuns();
  reattach();
}

export function disconnect() {
  g.connectGeneration += 1;
  stopPolling();
  g.jobGeneration += 1;
  disconnected(`Disconnected. The displayed run stays on the page. A job already sent keeps running on the service until it finishes, is cancelled, or is abandoned (no status request for ${g.info?.limits.abandon_after_s ?? "a few hundred"} s).`);
}

function disconnected(message) {
  g.base = null;
  setConnection(message);
  setComputeEnabled(false);
  $("gen-disconnect").hidden = true;
}

function setConnection(text) { $("gen-conn-state").textContent = text; }

function setComputeEnabled(enabled) {
  for (const id of ["gen-check", "gen-runs-refresh"]) $(id).disabled = !enabled;
  updateRunButtons();
}

// ---------------------------------------------------------------------------
// Pending parameters (never computed by editing)

function buildForm() {
  const form = $("gen-form");
  const previous = g.installed ? paramsOf(g.installed.run) : null;
  form.replaceChildren();
  for (const spec of g.info.parameters) {
    // Names, kinds, ranges and defaults were checked against API v1 (validateInfo).
    const id = `gen-p-${spec.name}`;
    const row = document.createElement("div");
    row.className = "gen-field";
    const fixed = spec.minimum === spec.maximum;
    const value = previous ? previous[spec.name] : spec.default;
    setHtml(row, html`<label for="${id}">${spec.label}${spec.unit ? html` <span class="unit">(${spec.unit})</span>` : ""}</label>
<input id="${id}" name="${spec.name}" type="number" step="${spec.kind === "integer" ? "1" : "any"}" min="${spec.minimum}" max="${spec.maximum}" value="${value}" aria-describedby="${id}-note">
<small id="${id}-note">${fixed ? "" : `Supported ${spec.minimum}–${spec.maximum}. `}${spec.note}</small>`);
    if (fixed) row.querySelector("input").readOnly = true;
    form.append(row);
  }
  updatePending();
}

function readForm() {
  const params = {};
  for (const spec of g.info.parameters) {
    const raw = $(`gen-p-${spec.name}`).value.trim();
    // No clamping or rounding: the service validates and refuses with reasons.
    params[spec.name] = raw === "" ? null : (Number.isFinite(Number(raw)) ? Number(raw) : raw);
  }
  return params;
}

function paramsOf(run) {
  const p = {};
  for (const name of C.PARAMETER_NAMES) p[name] = run.effective.parameters[name];
  return p;
}

function updatePending() {
  if (!g.info) return;
  const pending = readForm();
  const hints = [];
  const speed = pending.wind_speed_m_per_s;
  const h = g.info.horizon;
  if (typeof speed === "number" && speed > 0) {
    const max = Math.floor((h.travel_budget_px * h.delta_m * h.frame_rate_hz) / speed) + 1;
    hints.push(`At ${speed} m/s the ${h.generated_screen_px}-sample screen supports about ${max} frames (${h.travel_budget_px} px of travel at ${(h.delta_m * 1000).toFixed(1)} mm per sample); the service's admission decides exactly and refuses anything beyond, without slack.`);
  } else if (speed === 0) {
    hints.push("Zero wind: the realization does not move; every frame samples the same atmosphere.");
  }
  if (typeof pending.n_frames === "number" && typeof pending.display_stride === "number" && pending.display_stride >= 1) {
    const kept = Number.isInteger(pending.n_frames) && Number.isInteger(pending.display_stride) ? C.transportedIndices(pending.n_frames, pending.display_stride).length : null;
    if (kept) hints.push(`${kept} of ${pending.n_frames} frames would be kept for replay (at most ${C.MAX_TRANSPORTED_FRAMES}); histories and averages always use every frame.`);
  }
  $("gen-hints").textContent = hints.join(" ");
  if (!g.installed) { $("gen-pending").textContent = "No run is displayed yet; these values are only pending."; return; }
  const shown = paramsOf(g.installed.run);
  const diffs = C.PARAMETER_NAMES.filter((name) => pending[name] !== shown[name]).map((name) => `${name} ${JSON.stringify(pending[name])} (displayed run: ${JSON.stringify(shown[name])})`);
  $("gen-pending").textContent = diffs.length ? `Pending, not computed: ${diffs.join("; ")}.` : "The pending values equal the displayed run's configuration.";
}

// ---------------------------------------------------------------------------
// Jobs

function requestBody(params, policy) {
  return { schema: C.SCHEMAS.request, api: C.API_VERSION, seed_policy: policy, parameters: params };
}

async function submit(kind) {
  if (!g.base || g.submitting) return;
  hideError();
  let params = readForm();
  let policy = "specified";
  let reference = null;
  if (kind === "new") { params = { ...params, seed: null }; policy = "allocate"; }
  if (kind === "reproduce") params = paramsOf(g.installed.run);
  if (kind === "compare") {
    reference = g.installed;
    const shown = paramsOf(reference.run);
    for (const name of LOCKED_FOR_COMPARISON) params[name] = shown[name];
    if (C.SAME_ATMOSPHERE_CHANGES.every((name) => params[name] === shown[name])) {
      showError("Nothing to compare", ["Change the guide magnitude, controller gain or queued delay first; with none of them changed the request is a replay (use Reproduce)."]);
      return;
    }
    $("gen-compare-note").hidden = false;
    $("gen-compare-note").textContent = `Comparison request: ${C.SAME_ATMOSPHERE_CHANGES.map((n) => `${n} ${params[n]}`).join(", ")}; seed, r0, wind, frames and burn-in are taken from the displayed run (${reference.run.run_id}).`;
  }
  // One submission at a time: the start buttons stay disabled until the
  // service has answered, so no job can be created that the page does not track
  // (review R1-F02).
  g.submitting = true;
  updateRunButtons();
  const base = g.base;
  try {
    if (g.job && !C.TERMINAL_STATES.has(g.job.state) && g.job.runId) await cancelJob("superseded");
    await submitTo(base, kind, params, policy, reference);
  } finally {
    g.submitting = false;
    updateRunButtons();
  }
}

async function submitTo(base, kind, params, policy, reference) {
  const generation = ++g.jobGeneration;
  g.job = { generation, kind, runId: null, state: "submitting", requested: params, policy, reference, referenceId: reference?.run.run_id ?? null, base };
  renderJobText(`Submitting ${describeKind(kind)}…`);
  let answer;
  try {
    answer = await fetchJson(new URL("runs", base), { method: "POST", body: requestBody(params, policy) });
  } catch (error) {
    if (generation !== g.jobGeneration) return;
    g.job.state = "failed";
    renderJobText(`The request could not be sent: ${error.message}. Nothing was started.`);
    return;
  }
  if (generation !== g.jobGeneration) {
    // The page moved on (disconnect) while the service was creating this job:
    // cancel it rather than leave an untracked job holding the worker.
    if (answer.ok && typeof answer.value?.run_id === "string" && C.SERVICE_RUN_ID.test(answer.value.run_id)) {
      fetchJson(new URL(`runs/${answer.value.run_id}/cancel`, base), { method: "POST", body: { reason: "superseded" } }).catch(() => {});
    }
    return;
  }
  if (answer.status === 422 || answer.status === 429 || !answer.ok) {
    g.job.state = "failed";
    const v = answer.value || {};
    renderJobText(answer.status === 429 ? "The service is busy; nothing was started. Try again when the running job has finished." : "The service refused the request; nothing was computed.");
    const details = [...(v.reasons || [])];
    if (v.admission) details.push(`Admission: ${v.admission.outcome}; maximum travel ${fmt(v.admission.max_travel_px, 3)} px of a ${v.admission.travel_budget_px} px budget over ${v.admission.request_count} atmosphere requests.`);
    showError(v.message || `HTTP ${answer.status}`, details);
    return;
  }
  const problems = C.validateStatus(answer.value);
  if (problems.length) { g.job.state = "failed"; showError("Unsupported job status from the service", problems); return; }
  g.job.runId = answer.value.run_id;
  g.job.state = answer.value.state;
  g.job.allocatedSeed = answer.value.seed;
  g.job.seedSource = answer.value.seed_source;
  try { sessionStorage.setItem(STORAGE_KEY, JSON.stringify({ base: base.href, runId: g.job.runId, kind, referenceId: g.job.referenceId })); } catch (error) { /* storage is optional */ }
  renderStatus(answer.value);
  schedulePoll(generation, 0);
}

function describeKind(kind) {
  return { run: "a run with these parameters", new: "a new random realization", reproduce: "a reproduction of the displayed run", compare: "a same-turbulence comparison", reattach: "the job of this session" }[kind] || "a run";
}

async function cancelJob(reason) {
  const job = g.job;
  if (!job || !job.runId || !g.base) return;
  renderJobText(`Cancelling ${job.runId} (${reason === "superseded" ? "superseded by a newer request" : "requested"})…`);
  try {
    const { value } = await fetchJson(new URL(`runs/${job.runId}/cancel`, job.base || g.base), { method: "POST", body: { reason }, timeoutMs: 20000 });
    if (!C.validateStatus(value, { runId: job.runId }).length) { job.state = value.state; if (job === g.job) renderStatus(value); }
  } catch (error) {
    renderJobText(`Cancelling ${job.runId} failed (${error.message}); the service will abandon it if no page asks about it.`);
  }
}

function stopPolling() { clearTimeout(g.pollTimer); g.pollTimer = null; }

function schedulePoll(generation, delay) {
  stopPolling();
  g.pollTimer = setTimeout(() => poll(generation), delay);
}

async function poll(generation) {
  const job = g.job;
  if (!job || generation !== g.jobGeneration || !g.base) return;
  let status;
  try {
    const answer = await fetchJson(new URL(`runs/${job.runId}`, g.base), { timeoutMs: 10000 });
    if (!answer.ok) throw new Error(answer.value?.message || `HTTP ${answer.status}`);
    status = answer.value;
    const problems = C.validateStatus(status, { runId: job.runId });
    if (problems.length) throw new Error(problems.join("; "));
    g.failures = 0;
  } catch (error) {
    if (generation !== g.jobGeneration) return;
    g.failures += 1;
    const wait = Math.min(MAX_BACKOFF_MS, POLL_MS * 2 ** g.failures);
    renderJobText(`Service unreachable (${error.message}); retrying in ${(wait / 1000).toFixed(1)} s. The job keeps running on the service; the displayed run is unchanged.`);
    schedulePoll(generation, wait);
    return;
  }
  if (generation !== g.jobGeneration) return;
  job.state = status.state;
  renderStatus(status);
  if (status.state === "completed") {
    const expected = { ...job.requested };
    if (job.policy === "allocate") {
      if (status.seed_source !== "allocated_by_service" || status.seed !== job.allocatedSeed) { showError("The service changed the allocated seed", [`expected ${job.allocatedSeed}, status names ${status.seed}`]); return; }
      expected.seed = job.allocatedSeed;
    }
    const reference = job.kind === "compare" ? job.reference || g.cache.get(job.referenceId) || null : null;
    const outcome = await loadRun(status.run_id, { expected, status, reference, origin: job.kind });
    // Keep the session's record while the result could still be fetched after
    // a reconnect; drop it once the run was installed or refused by the checks.
    if (outcome === "installed" || outcome === "refused") clearStoredJob(job.runId);
    return;
  }
  if (C.TERMINAL_STATES.has(status.state)) { clearStoredJob(job.runId); return; }
  schedulePoll(generation, POLL_MS);
}

function clearStoredJob(runId) {
  try { const stored = JSON.parse(sessionStorage.getItem(STORAGE_KEY) || "null"); if (stored?.runId === runId) sessionStorage.removeItem(STORAGE_KEY); } catch (error) { /* optional */ }
}

async function reattach() {
  let stored = null;
  try { stored = JSON.parse(sessionStorage.getItem(STORAGE_KEY) || "null"); } catch (error) { stored = null; }
  if (!stored || stored.base !== g.base.href || !/^run-[0-9TZ-]+[0-9a-f]{8}$/.test(stored.runId || "")) return;
  const generation = ++g.jobGeneration;
  g.job = { generation, kind: "reattach", runId: stored.runId, state: "unknown", requested: {}, policy: "specified", referenceId: stored.referenceId, base: g.base };
  try {
    const { ok, value } = await fetchJson(new URL(`runs/${stored.runId}`, g.base));
    if (!ok || C.validateStatus(value, { runId: stored.runId }).length) { clearStoredJob(stored.runId); g.job = null; return; }
    g.job.requested = Object.fromEntries(C.PARAMETER_NAMES.map((name) => [name, value.parameters[name]]));
    g.job.allocatedSeed = value.seed;
    renderJobText(`Reattached to ${stored.runId} from this browser session.`);
    schedulePoll(generation, 0);
  } catch (error) { g.job = null; }
}

function renderJobText(text) { $("gen-job-state").textContent = text; }

function renderStatus(status) {
  const p = status.progress;
  const n = p.n_frames;
  const done = p.frames_done;
  $("gen-progress").value = n ? done / n : 0;
  const physical = p.physical_time_s == null ? "not started" : `${(p.physical_time_s * 1000).toFixed(0)} ms reached`;
  $("gen-progress-text").textContent = ` ${done} of ${n} frames computed · physical time ${physical} · computation wall time ${status.computation_wall_s == null ? "—" : `${status.computation_wall_s.toFixed(1)} s`}`;
  const seed = status.seed_source === "allocated_by_service" ? `new seed ${status.seed} allocated by the service` : `seed ${status.seed}`;
  const where = status.state === "queued" ? ` (position ${status.queue_position + 1} in the queue)` : "";
  const text = {
    queued: `Queued${where}: ${status.run_id}, ${seed}.`,
    running: `Computing ${status.run_id} (${seed}): ${p.stage}.`,
    completed: `Completed ${status.run_id} (${seed}); verifying and installing the result…`,
    cancelled: `Cancelled ${status.run_id}: ${status.reason}. No result was installed; the displayed run is unchanged.`,
    failed: `Failed ${status.run_id}: ${status.reason}. No result was installed; the displayed run is unchanged.`,
  }[status.state];
  renderJobText(text);
  $("gen-cancel").disabled = !["queued", "running"].includes(status.state);
}

// ---------------------------------------------------------------------------
// Loading and installing a completed run (atomic, generation-guarded)

async function fetchVerifiedBytes(url, ref, signal) {
  const response = await fetch(url, { signal, cache: "no-cache", credentials: "omit" });
  if (!response.ok) throw new Error(`${ref.href}: HTTP ${response.status}`);
  const buffer = await response.arrayBuffer();
  if (buffer.byteLength !== ref.bytes) throw new Error(`${ref.href} has ${buffer.byteLength} bytes; ${ref.bytes} were recorded`);
  if ((await sha256Hex(buffer)) !== ref.sha256) throw new Error(`${ref.href} does not match its recorded SHA-256`);
  return buffer;
}

async function loadRun(runId, { expected = null, status = null, reference = null, origin = "list" } = {}) {
  const generation = ++g.loadGeneration;
  if (g.loadController) g.loadController.abort();
  const controller = new AbortController();
  g.loadController = controller;
  pause();
  if (g.cache.has(runId) && !expected) {
    install(g.cache.get(runId), { reference: g.reference, origin });
    return "installed";
  }
  const base = g.base;
  const connection = g.connectGeneration;
  if (!base) return "aborted";
  try {
    let current = status;
    if (!current) {
      const answer = await fetchJson(new URL(`runs/${runId}`, base), { signal: controller.signal });
      if (!answer.ok) throw new Error(answer.value?.message || `HTTP ${answer.status}`);
      current = answer.value;
    }
    const statusProblems = C.validateStatus(current, { runId });
    if (statusProblems.length) throw new Error(statusProblems.join("; "));
    if (current.state !== "completed" || !current.files) throw new Error(`run ${runId} is ${current.state}${current.evicted ? " and was evicted from the service's storage" : ""}`);
    const files = current.files;
    const runUrl = new URL(`runs/${runId}/`, base);
    const runBuffer = await fetchVerifiedBytes(new URL(files["run.json"].href, runUrl), files["run.json"], controller.signal);
    const run = JSON.parse(new TextDecoder().decode(runBuffer));
    // A run started here must have the requested parameters; a run loaded from
    // the list must have the parameters its own status names.
    const problems = C.validateRun(run, { expectedParameters: expected || current.parameters, runId });
    if (!problems.length && (await C.physicalIdentity(run.effective.parameters)) !== run.effective.physical_identity) {
      problems.push("the physical identity does not follow from the recorded parameters");
    }
    if (problems.length) {
      const error = new Error("the run's metadata is not supported by this page");
      error.details = problems;
      error.refused = true;
      throw error;
    }
    const refs = { "frames.bin": run.arrays.frames, "final.bin": run.arrays.final, "metrics.csv": run.arrays.metrics_csv };
    for (const [name, ref] of Object.entries(refs)) {
      if (files[name].bytes !== ref.bytes || files[name].sha256 !== ref.sha256) throw new Error(`${name} of the status and of run.json disagree`);
    }
    const [framesBuffer, finalBuffer, csvBuffer] = await Promise.all(Object.entries(refs).map(([name, ref]) => fetchVerifiedBytes(new URL(files[name].href, runUrl), ref, controller.signal)));
    const data = {
      id: runId, run, runBuffer, csvBuffer, framesBuffer, finalBuffer,
      frames: C.frameViews(framesBuffer, run), final: C.finalViews(finalBuffer),
      evidenceUrl: new URL(files["evidence.npz"].href, runUrl).href, base: base.href, serviceOrigin: base.origin,
    };
    if (generation !== g.loadGeneration) return "superseded"; // a newer selection or run won
    if (connection !== g.connectGeneration) return "aborted"; // disconnected meanwhile
    remember(runId, data);
    install(data, { reference: origin === "compare" ? reference : g.reference, origin });
    return "installed";
  } catch (error) {
    if (error.name === "AbortError" || generation !== g.loadGeneration) return "superseded";
    if (connection !== g.connectGeneration) return "aborted";
    if (origin !== "list") {
      renderJobText(error.refused
        ? `The completed run ${runId} was refused by this page's checks; nothing was installed and the displayed run is unchanged.`
        : `The completed run ${runId} could not be fetched (${error.message}); the displayed run is unchanged.`);
    }
    showError(`Run ${runId} was not installed: ${error.message}.`, [...(error.details || []), g.installed ? `Still showing ${g.installed.id}.` : "No generated run is displayed."]);
    return error.refused ? "refused" : "failed";
  }
}

function remember(id, data) {
  g.cache.delete(id);
  g.cache.set(id, data);
  while (g.cache.size > CACHE_LIMIT) {
    const oldest = [...g.cache.keys()].find((key) => key !== g.installed?.id && key !== g.reference?.id);
    if (oldest === undefined) break;
    g.cache.delete(oldest);
  }
}

function install(data, { reference, origin }) {
  pause();
  revokeObjectUrls();
  g.installed = data;
  g.reference = reference && reference.id !== data.id ? reference : null;
  if (g.reference) remember(g.reference.id, g.reference);
  g.position = 0;
  const run = data.run;
  $("gen-seek").max = String(run.transported.indices.length - 1);
  $("gen-seek").value = "0";
  renderRunHeader(origin);
  renderWarnings();
  renderColorbars();
  drawField("gen-scene", data.final.scene, C.CROP, (v) => C.intensityCode(v, run.display.ideal_peak_cell_flux, run.display.psf_log_decades), g.luts.intensity);
  renderSummary();
  renderDownloads();
  renderModelNotes();
  $("gen-provenance").textContent = JSON.stringify({
    run_id: run.run_id, seed_source: run.seed_source, effective: run.effective, identities: run.identities,
    admission: run.admission, time: { ...run.time, time_s: `${run.time.time_s.length} values` }, conventions: run.conventions,
    grids: run.grids, scene: run.scene, checks: run.checks, resources: run.resources, limitations: run.limitations,
  }, null, 1);
  updateRunButtons();
  updatePending();
  renderFrame();
  hideError();
  if (!g.job || C.TERMINAL_STATES.has(g.job.state)) renderJobText(`Displaying ${run.run_id}${origin === "list" ? " (loaded from the service's completed runs)" : ""}. Every file was verified (size, SHA-256) and its metadata checked against API v1.`);
}

function updateRunButtons() {
  const ready = !!g.base && !g.submitting;
  $("gen-run").disabled = !ready;
  $("gen-new").disabled = !ready;
  $("gen-reproduce").disabled = !ready || !g.installed;
  $("gen-compare").disabled = !ready || !g.installed;
  $("gen-set-reference").disabled = !g.installed || g.reference?.id === g.installed?.id;
  $("gen-clear-reference").disabled = !g.reference;
}

// ---------------------------------------------------------------------------
// Rendering

const fmt = (v, d = 1) => (v === null || v === undefined || !Number.isFinite(v) ? "—" : v.toFixed(d));
const nm = (m) => (m == null ? null : m * 1e9);

function renderRunHeader(origin) {
  const run = g.installed.run; const p = run.effective.parameters;
  const seed = run.seed_source === "allocated_by_service" ? `seed ${p.seed} (new realization allocated by the service)` : `seed ${p.seed}`;
  setHtml($("gen-run-id"), html`<strong>${run.run_id}</strong> · ${seed} · r0 ${p.r0_m} m at ${p.r0_reference_wavelength_m * 1e9} nm · wind ${p.wind_speed_m_per_s} m/s towards ${p.wind_direction_deg}° from +x · guide AB ${p.guide_ab_magnitude} · gain ${p.controller_gain} · queued delay ${p.queued_latency_frames} frames (seen by the WFS ${p.queued_latency_frames + 1} frames later) · ${p.n_frames} frames, burn-in ${p.burn_in} · computed ${run.completed_utc} by the service at ${g.installed.serviceOrigin} · physical identity <code>${run.effective.physical_identity.slice(0, 12)}</code> · calibration <code>${run.identities.calibration.interaction_matrix_hash.slice(0, 12)}</code>${origin === "compare" ? " · comparison run" : ""}`);
}

function renderWarnings() {
  const s = g.installed.run.summary;
  const items = [];
  if (!s.controller_linear_model_stable) items.push(`The controller's linear model is unstable for this gain and delay (largest pole modulus ${fmt(s.controller_max_pole_modulus, 3)} ≥ 1); the run is shown as computed.`);
  if (s.frames_with_dm_saturation) items.push(`DM stroke saturation occurred in ${s.frames_with_dm_saturation} issued commands (maximum fraction ${fmt(s.max_dm_saturation_fraction_issued, 3)}).`);
  if (s.min_valid_measurement_fraction < 1) items.push(`Some WFS measurements were invalid (minimum valid fraction ${fmt(s.min_valid_measurement_fraction, 3)}).`);
  if (s.frames_with_unusable_reconstruction) items.push(`${s.frames_with_unusable_reconstruction} frames had no usable reconstruction.`);
  if (s.frames_corrected_strehl_below_uncorrected) items.push(`In ${s.frames_corrected_strehl_below_uncorrected} frames the AO-corrected instantaneous Strehl is below the uncorrected one; correction is not guaranteed to improve every frame.`);
  setHtml($("gen-warnings"), html`${items.map((t) => html`<li>${t}</li>`)}`);
}

function quantity() {
  const run = g.installed.run;
  const L = run.display.opd_limit_m;
  if (g.quantity === "opd") return { scale: 1e9, unit: "nm", limit: L, label: "OPD", wavelength: null };
  const wavelength = g.quantity === "phase-science" ? C.SCIENCE_WAVELENGTH_M : C.WFS_WAVELENGTH_M;
  return { scale: (2 * Math.PI) / wavelength, unit: "rad", limit: L, label: `phase at ${(wavelength * 1e6).toFixed(2)} µm`, wavelength };
}

function renderColorbars() {
  const q = quantity();
  const run = g.installed.run;
  for (const [id, lut] of [["gen-cbar-opd", g.luts.opd], ["gen-cbar-psf", g.luts.intensity]]) {
    const canvas = $(id); const ctx = canvas.getContext("2d");
    for (let i = 0; i < 200; i += 1) { const c = lut[Math.round((1 - i / 199) * 255)]; ctx.fillStyle = `rgb(${c[0]},${c[1]},${c[2]})`; ctx.fillRect(0, i, canvas.width, 1); }
  }
  const top = q.limit * q.scale;
  const digits = q.unit === "nm" ? 0 : 2;
  setHtml($("gen-cbar-opd-labels"), html`${[top, top / 2, 0, -top / 2, -top].map((v, i) => html`<span style="top:${i * 25}%">${v > 0 ? "+" : ""}${v.toFixed(digits)} ${q.unit}</span>`)}`);
  const phaseNote = q.wavelength ? ` Phase = 2π × OPD / ${(q.wavelength * 1e6).toFixed(2)} µm, unwrapped (never reduced modulo 2π); ${q.wavelength === C.SCIENCE_WAVELENGTH_M ? "the science wavelength" : "the WFS wavelength, not the science wavelength"}.` : "";
  $("gen-cbar-opd-note").textContent = `One limit (±${(run.display.opd_limit_m * 1e9).toFixed(0)} nm OPD) for all frames and all three maps of this run; beyond it values are clipped to the end colours. Grey = outside the pupil.${phaseNote}`;
  setHtml($("gen-cbar-psf-labels"), html`${[0, -1, -2, -3, -4].map((v, i) => html`<span style="top:${i * 25}%">10^${v}</span>`)}`);
  $("gen-cbar-psf-note").textContent = "Relative to the ideal (zero-OPD) peak cell flux, log scale; common to every PSF, observation and the scene of this run.";
  for (const [key] of MAP_KEYS) {
    $(`gen-unit-${key}`).textContent = {
      atmosphere: `${q.label}, ${q.unit}`,
      correction: `atmosphere minus residual, ${q.label === "OPD" ? "OPD-equivalent" : q.label}, ${q.unit}`,
      residual: `pre-update residual, ${q.label}, ${q.unit}`,
    }[key];
  }
}

function hexRgb(hex) { return [1, 3, 5].map((i) => parseInt(hex.slice(i, i + 2), 16)); }

function offscreen(width, height) {
  const key = `${width}x${height}`;
  if (!g.offscreen.has(key)) { const c = document.createElement("canvas"); c.width = width; c.height = height; g.offscreen.set(key, c); }
  return g.offscreen.get(key);
}

// Array row index increases with +y; the canvas draws +y upwards and +x to the right.
function drawField(canvasId, values, shape, codeOf, lut) {
  const [ny, nx] = shape;
  const off = offscreen(nx, ny);
  const octx = off.getContext("2d");
  const image = octx.createImageData(nx, ny);
  for (let row = 0; row < ny; row += 1) {
    const source = (ny - 1 - row) * nx;
    for (let column = 0; column < nx; column += 1) {
      const v = values[source + column];
      const o = (row * nx + column) * 4;
      if (Number.isNaN(v)) { image.data[o + 3] = 0; continue; }
      const c = lut[codeOf(v)];
      image.data[o] = c[0]; image.data[o + 1] = c[1]; image.data[o + 2] = c[2]; image.data[o + 3] = 255;
    }
  }
  octx.putImageData(image, 0, 0);
  const canvas = $(canvasId); const ctx = canvas.getContext("2d");
  ctx.imageSmoothingEnabled = false;
  ctx.clearRect(0, 0, canvas.width, canvas.height);
  ctx.drawImage(off, 0, 0, canvas.width, canvas.height);
}

function blankField(canvasId, text) {
  const canvas = $(canvasId); const ctx = canvas.getContext("2d");
  ctx.clearRect(0, 0, canvas.width, canvas.height);
  ctx.fillStyle = "#5c6168"; ctx.font = "13px sans-serif"; ctx.textAlign = "center";
  ctx.fillText(text, canvas.width / 2, canvas.height / 2);
}

function renderFrame() {
  const data = g.installed; if (!data) return;
  const run = data.run; const p = run.effective.parameters;
  const frame = data.frames[g.position];
  const k = run.transported.indices[g.position];
  const tMs = run.transported.time_s[g.position] * 1000;
  const q = quantity();
  const L = run.display.opd_limit_m;
  for (const [key, block] of MAP_KEYS) {
    const piston = run.display.piston_removed_m[key][g.position];
    drawField(`gen-map-${key}`, frame[block], C.PUPIL, (v) => C.opdCode(v - piston, L), g.luts.opd);
    const clipped = run.display.clipped_fraction[key][g.position];
    const pistonShown = q.unit === "nm" ? `${fmt(piston * 1e9, 1)} nm` : `${fmt(piston * q.scale, 3)} rad`;
    $(`gen-note-${key}`).textContent = `t = ${tMs.toFixed(0)} ms: pupil mean ${pistonShown} removed for display; ${clipped > 0 ? `${(clipped * 100).toFixed(2)} % of pupil samples clipped` : "no clipping"}.`;
  }
  const peak = run.display.ideal_peak_cell_flux; const decades = run.display.psf_log_decades;
  const intensity = (v) => C.intensityCode(v, peak, decades);
  drawField("gen-psf-uncorrected", frame.psf_uncorrected, C.CROP, intensity, g.luts.intensity);
  drawField("gen-psf-corrected", frame.psf_corrected, C.CROP, intensity, g.luts.intensity);
  $("gen-psf-unc-sub").textContent = `frame ${k} (t = ${tMs.toFixed(0)} ms): this frame's atmosphere with zero DM, 1.65 µm`;
  $("gen-psf-ao-sub").textContent = `frame ${k} (t = ${tMs.toFixed(0)} ms): this frame's pre-update residual, 1.65 µm`;
  renderObservations(frame, k, tMs);
  const burnIn = k < p.burn_in;
  const stride = p.display_stride;
  $("gen-seek").value = String(g.position);
  $("gen-seek").setAttribute("aria-valuetext", `physical time ${tMs.toFixed(0)} ms, frame ${k}`);
  $("gen-readout").textContent = `Physical time ${tMs.toFixed(0)} ms · frame ${k} of 0–${p.n_frames - 1}${burnIn ? " · burn-in" : ""} · replay frame ${g.position + 1}/${run.transported.indices.length}${stride > 1 ? ` (one frame in every ${stride}, and the last, were kept for replay)` : ""}`;
  $("gen-replay-note").textContent = `Replay ${g.playing ? "playing" : "paused"} at ${$("gen-speed").value} replay frames per second of animation time; each replay frame advances physical time by ${stride} ms${stride > 1 ? " (the last step may be shorter)" : ""}. ${$("gen-loop").checked ? "Loop replay is on: after the last frame the replay restarts at t = 0 ms of the same recorded run; it is a replay, not a continuation of the atmosphere." : "The finite run ends at its last frame."}`;
  const pf = run.per_frame;
  const sat = pf.saturation_fraction_issued;
  $("gen-current").textContent = `Frame ${k} (t = ${tMs.toFixed(0)} ms): atmosphere ${fmt(nm(pf.atmosphere_rms_m[k]))} nm, residual ${fmt(nm(pf.residual_rms_m[k]))} nm RMS (piston removed); instantaneous peak Strehl ${fmt(pf.peak_strehl_uncorrected[k], 3)} uncorrected, ${fmt(pf.peak_strehl_corrected[k], 3)} AO-corrected; running averaged-intensity Strehl ${pf.running_average_peak_strehl_corrected[k] == null ? "unavailable before burn-in" : fmt(pf.running_average_peak_strehl_corrected[k], 3)} (AO); valid measurement fraction ${fmt(pf.valid_measurement_fraction[k], 3)}; reconstruction ${pf.reconstruction_usable[k] ? "usable" : "not usable"}; DM saturation of the held command (issued at frame ${k === 0 ? "start" : k - 1}) ${k === 0 ? "none recorded (initial flat command)" : fmt(sat[k - 1], 3)}, of the command issued at this frame ${fmt(sat[k], 3)}.`;
  renderCharts(k);
}

function renderObservations(frame, k, tMs) {
  const data = g.installed; const run = data.run; const p = run.effective.parameters;
  const peak = run.display.ideal_peak_cell_flux; const decades = run.display.psf_log_decades;
  const intensity = (v) => C.intensityCode(v, peak, decades);
  const sc = run.scene;
  const peakFlux = run.display.ideal_peak_cell_flux;
  $("gen-scene-caption").textContent = `primary at 0, secondary +${sc.separation_mas.toFixed(1)} mas in x (${sc.separation_lambda_over_d.toFixed(2)} λ/D, ${sc.separation_native_x_cells} native cells); weights 2/3 and 1/3 (flux ratio 2:1); total flux 1; identical for every run and guide magnitude. On the shared scale both scene cells exceed the ideal PSF peak cell flux (${peakFlux.toFixed(4)}) and are clipped to the top colour, so the 2:1 ratio is stated here, not shown.`;
  const pct = (x) => `${(x * 100).toFixed(2)} %`;
  let unc; let ao; let title; let caption; let flux;
  if (g.obsMode === "instantaneous") {
    unc = frame.observation_uncorrected; ao = frame.observation_corrected;
    title = `instantaneous, frame ${k} (t = ${tMs.toFixed(0)} ms)`;
    flux = { unc: run.transported.instantaneous_flux.uncorrected[g.position], ao: run.transported.instantaneous_flux.corrected[g.position] };
    caption = "scene convolved with this frame's PSF";
  } else if (g.obsMode === "running") {
    const count = run.transported.running_sample_count[g.position];
    if (count === 0) {
      blankField("gen-obs-uncorrected", "unavailable before burn-in");
      blankField("gen-obs-corrected", "unavailable before burn-in");
      $("gen-obs-unc-title").textContent = "Uncorrected running average";
      $("gen-obs-ao-title").textContent = "AO-corrected running average";
      const text = `Unavailable at t = ${tMs.toFixed(0)} ms: the analysis window starts at frame ${p.burn_in}, so burn-in has not supplied a sample yet.`;
      $("gen-obs-unc-caption").textContent = text; $("gen-obs-ao-caption").textContent = text;
      $("gen-obs-note").textContent = observationNote();
      return;
    }
    unc = frame.running_observation_uncorrected; ao = frame.running_observation_corrected;
    title = `running average of ${count} samples, frames ${p.burn_in}–${k} (t = ${p.burn_in}–${tMs.toFixed(0)} ms)`;
    flux = { unc: run.transported.running_flux.uncorrected[g.position], ao: run.transported.running_flux.corrected[g.position] };
    caption = `equal-weight mean of every frame's observation since burn-in (${count} physical samples, not only replay frames)`;
  } else {
    unc = data.final.final_observation_uncorrected; ao = data.final.final_observation_corrected;
    title = `completed window, frames ${p.burn_in}–${p.n_frames - 1} (${p.n_frames - p.burn_in} samples)`;
    const f = run.final_average.observation_flux;
    flux = { unc: { full_flux: f.uncorrected.full_flux, native_window_fraction: f.uncorrected.retained_fraction, display_crop_fraction: f.uncorrected.display_crop_fraction },
      ao: { full_flux: f.corrected.full_flux, native_window_fraction: f.corrected.retained_fraction, display_crop_fraction: f.corrected.display_crop_fraction } };
    caption = "scene convolved with the mean PSF of the completed window (fixed; does not follow the cursor)";
  }
  drawField("gen-obs-uncorrected", unc, C.CROP, intensity, g.luts.intensity);
  drawField("gen-obs-corrected", ao, C.CROP, intensity, g.luts.intensity);
  $("gen-obs-unc-title").textContent = `Uncorrected — ${title}`;
  $("gen-obs-ao-title").textContent = `AO-corrected — ${title}`;
  const line = (f) => `${caption}; full-convolution flux ${f.full_flux.toFixed(6)}, ${pct(f.native_window_fraction)} inside the native ±${(run.grids.psf.native_extent_mas[1] / 1000).toFixed(1)}″ window, ${pct(f.display_crop_fraction)} inside this ±${(run.grids.psf.crop_extent_mas[1] / 1000).toFixed(1)}″ crop`;
  $("gen-obs-unc-caption").textContent = line(flux.unc);
  $("gen-obs-ao-caption").textContent = line(flux.ao);
  $("gen-obs-note").textContent = observationNote();
}

function observationNote() {
  return "Synthetic observation: the fixed incoherent binary convolved (exact linear, zero-extended, no wraparound) with the numerical PSFs of this run, relative flux per cell, the same scale for both arms and all modes; no per-image normalization and no science-camera noise, counts, SNR or detection claim. One spatially invariant on-axis PSF is assumed across the scene (illustrative).";
}

function seriesFrom(values, scale = 1) { return values.map((v, i) => [i, v == null ? null : v * scale]); }

function renderCharts(cursor) {
  const run = g.installed.run; const pf = run.per_frame; const p = run.effective.parameters;
  const ref = g.reference?.run;
  const shade = [[0, p.burn_in, "burn-in"]];
  const x = { label: "Physical time", unit: "ms = frame index", range: [0, Math.max(p.n_frames - 1, ref ? ref.effective.parameters.n_frames - 1 : 0)] };
  const refSeries = (key, label, scale = 1) => (ref ? [{ label: `Reference: ${label}`, points: seriesFrom(ref.per_frame[key], scale), style: "dashed", color: "#7d7d7d" }] : []);
  lineChart($("gen-chart-rms"), {
    title: "Pupil RMS", height: 220, x, y: { label: "RMS", unit: "nm" },
    series: [{ label: "Atmosphere", points: seriesFrom(pf.atmosphere_rms_m, 1e9) }, { label: "Residual seen by the WFS", points: seriesFrom(pf.residual_rms_m, 1e9) }, ...refSeries("residual_rms_m", "residual", 1e9)],
    shadeX: shade, cursorX: cursor,
  });
  lineChart($("gen-chart-strehl"), {
    title: "Peak Strehl", height: 220, x, y: { label: "Peak Strehl", unit: "", range: [0, 1] },
    series: [
      { label: "Uncorrected (instantaneous)", points: seriesFrom(pf.peak_strehl_uncorrected) },
      { label: "AO-corrected (instantaneous)", points: seriesFrom(pf.peak_strehl_corrected) },
      { label: "AO-corrected, running averaged intensity", points: seriesFrom(pf.running_average_peak_strehl_corrected), style: "dashed", color: "#6b5aa6" },
      ...refSeries("peak_strehl_corrected", "AO-corrected (instantaneous)"),
    ],
    shadeX: shade, cursorX: cursor,
  });
  lineChart($("gen-chart-valid"), {
    title: "Validity", height: 160, x, y: { label: "Fraction", unit: "", range: [0, 1.05] },
    series: [{ label: "Valid measurement fraction", points: seriesFrom(pf.valid_measurement_fraction) }, { label: "DM saturation (command issued at frame k)", points: seriesFrom(pf.saturation_fraction_issued) }],
    shadeX: shade, cursorX: cursor, ticksBelow: pf.reconstruction_usable.map((u, i) => (u ? null : { x: i })).filter(Boolean),
  });
  $("gen-curves-hint").textContent = `Every one of the ${p.n_frames} frames (1 ms each), including burn-in (shaded). The cursor marks the displayed physical time.${ref ? ` Dashed grey: the comparison reference ${ref.run_id}.` : ""}`;
}

function renderSummary() {
  const run = g.installed.run; const s = run.summary; const p = run.effective.parameters;
  const ref = g.reference?.run; const r = ref?.summary;
  const rows = [
    ["Mean atmosphere RMS", "mean_atmosphere_rms_m", "nm", 1, 1e9],
    ["Mean residual RMS (mean of per-frame RMS)", "mean_residual_rms_m", "nm", 1, 1e9],
    ["Residual RMS (root of the mean square)", "root_mean_square_residual_m", "nm", 1, 1e9],
    ["Mean instantaneous peak Strehl, uncorrected", "mean_instantaneous_peak_strehl_uncorrected", "", 4, 1],
    ["Mean instantaneous peak Strehl, AO-corrected", "mean_instantaneous_peak_strehl_corrected", "", 4, 1],
    ["Peak Strehl of the averaged intensity, uncorrected", "averaged_intensity_peak_strehl_uncorrected", "", 4, 1],
    ["Peak Strehl of the averaged intensity, AO-corrected", "averaged_intensity_peak_strehl_corrected", "", 4, 1],
    ["Mean valid measurement fraction", "mean_valid_measurement_fraction", "", 4, 1],
    ["Frames with unusable reconstruction (whole run)", "frames_with_unusable_reconstruction", "", 0, 1],
    ["Maximum DM saturation of issued commands (whole run)", "max_dm_saturation_fraction_issued", "", 3, 1],
    ["Controller largest pole modulus (linear model)", "controller_max_pole_modulus", "", 3, 1],
  ];
  const head = html`<tr><th>Quantity</th><th>${run.run_id}</th>${ref ? html`<th>Reference ${ref.run_id}</th><th>Difference</th>` : ""}<th>Unit</th></tr>`;
  const body = rows.map(([label, key, unit, d, scale]) => {
    const a = s[key] * scale; const b = r ? r[key] * scale : null;
    return html`<tr><th scope="row">${label}</th><td class="num">${fmt(a, d)}</td>${ref ? html`<td class="num">${fmt(b, d)}</td><td class="num">${a - b >= 0 ? "+" : ""}${fmt(a - b, d)}</td>` : ""}<td>${unit}</td></tr>`;
  });
  const windows = ref && ref.effective.parameters.burn_in !== p.burn_in ? ` The reference's window is frames ${ref.effective.parameters.burn_in}–${ref.effective.parameters.n_frames - 1}; the two summaries cover different frames.` : "";
  $("gen-summary-table-title").textContent = `Frames ${p.burn_in}–${p.n_frames - 1}, ${p.n_frames - p.burn_in} equal-weight samples of one realization (no confidence intervals).${windows}`;
  setHtml($("gen-summary-table"), html`<table aria-labelledby="gen-summary-table-title"><thead>${head}</thead><tbody>${body}</tbody></table>`);
  if (!ref) { $("gen-pairing").textContent = "No comparison reference. Use “Compare using the same turbulence” or set the displayed run as the reference before loading another run."; return; }
  const v = C.pairingVerdict(ref, run);
  const calibration = v.expected.calibrationRebuilt
    ? ` Calibration rebuilt (${v.expected.calibrationChanges.join(", ")} changed): interaction matrix ${ref.identities.calibration.interaction_matrix_hash.slice(0, 12)} → ${run.identities.calibration.interaction_matrix_hash.slice(0, 12)}.`
    : ` Calibration identity ${run.identities.calibration.interaction_matrix_hash === ref.identities.calibration.interaction_matrix_hash ? "unchanged" : "changed"}.`;
  $("gen-pairing").textContent = v.paired
    ? `Paired comparison: the time grids are identical and all ${v.matching} atmosphere samples are byte-identical (per-frame SHA-256), so the differences isolate ${v.expected.changed.join(", ") || "nothing (identical configuration: an exact replay)"} in this one realization.${calibration}`
    : `Not a paired comparison: ${v.expected.text}. ${v.matching} of ${v.framesCompared} compared atmosphere samples match; time grids ${v.timesEqual ? "equal" : "differ"}.${calibration}`;
}

function revokeObjectUrls() { for (const url of g.objectUrls) URL.revokeObjectURL(url); g.objectUrls = []; }
function objectUrl(buffer, type) { const url = URL.createObjectURL(new Blob([buffer], { type })); g.objectUrls.push(url); return url; }

function renderDownloads() {
  const data = g.installed; const id = data.id;
  const links = [
    [objectUrl(data.runBuffer, "application/json"), `${id}-run.json`, "run.json (configuration, identities, histories, checks)"],
    [objectUrl(data.csvBuffer, "text/csv"), `${id}-metrics.csv`, "metrics.csv (every frame)"],
    [objectUrl(data.framesBuffer, "application/octet-stream"), `${id}-frames.bin`, "frames.bin (float32 replay frames)"],
    [objectUrl(data.finalBuffer, "application/octet-stream"), `${id}-final.bin`, "final.bin (completed-window averages)"],
  ];
  const evidence = data.run.arrays.evidence_npz;
  setHtml($("gen-downloads"), html`<p>Verified files of <strong>${id}</strong>: ${links.map(([url, name, label]) => html`<a href="${url}" download="${name}">${label}</a> `)}</p>
<p class="hint">Full-precision numeric evidence (evidence.npz, ${(evidence.bytes / 1048576).toFixed(1)} MiB, SHA-256 ${String(evidence.sha256).slice(0, 16)}… recorded in run.json) is served by the computation service at ${data.serviceOrigin}: <a href="${data.evidenceUrl}" download="${id}-evidence.npz">evidence.npz</a>. It is not verified by this page and is available while the service keeps this run.</p>`);
}

function renderModelNotes() {
  const run = g.installed.run; const p = run.effective.parameters;
  setHtml($("gen-model-notes"), html`<ul>
<li>One seeded realization (seed ${p.seed}) of the ${run.effective.fixed.atmosphere_model} atmosphere is generated at t = 0 and evolved by frozen flow at ${p.wind_speed_m_per_s} m/s; it is never redrawn, wrapped, reset or blended. Before computing, every atmosphere request time was admitted against the finite screen (maximum travel ${fmt(run.admission.max_travel_px, 3)} px of ${run.admission.travel_budget_px} px). The run ends normally at its last frame.</li>
<li>Each frame samples the atmosphere once, at its start (t = k ms). The residual is the pre-update residual the WFS measured; the held correction is atmosphere minus that residual (OPD-equivalent, not mirror surface height).</li>
<li>The uncorrected PSF propagates the frame's atmosphere with zero DM; the AO-corrected PSF propagates its pre-update residual. Both use the canonical native propagator at 1.65 µm, unit total flux on the uncropped ${run.grids.psf.shape_yx.join(" × ")} grid, shown cropped to ${C.CROP[0]} × ${C.CROP[1]} cells (${run.grids.psf.cell_mas.toFixed(1)} mas each) about exact zero angle. Tilt is kept and nothing is recentred.</li>
<li>Instantaneous Strehl is per frame; the mean instantaneous Strehl and the Strehl of the averaged intensity are different quantities. Averages are equal-weight means of intensities of every frame in the window (never of OPD or phase), of frame-start snapshots rather than a finite-shutter exposure.</li>
<li>Queued delay ${p.queued_latency_frames} frames: a reconstruction from frame k is released at the update of frame k + ${p.queued_latency_frames} and first seen by the WFS at frame k + ${p.queued_latency_frames + 1}. WFS detector noise is part of the loop.</li>
<li>Calibration is rebuilt for every run; its identity depends on the seed and the guide magnitude, not on gain, delay, r0 or wind.</li>
</ul>`);
}

// ---------------------------------------------------------------------------
// Replay (viewing only; never touches a job)

function setPosition(position) {
  if (!g.installed) return;
  g.position = Math.max(0, Math.min(g.installed.run.transported.indices.length - 1, position));
  renderFrame();
}

function pause() {
  g.playing = false;
  clearTimeout(g.timer);
  $("gen-play").setAttribute("aria-pressed", "false");
  $("gen-play").textContent = "Play";
}

function play() {
  if (!g.installed) return;
  const last = g.installed.run.transported.indices.length - 1;
  if (g.position >= last) setPosition(0);
  g.playing = true; g.nextAt = null;
  $("gen-play").setAttribute("aria-pressed", "true");
  $("gen-play").textContent = "Pause";
  schedule();
}

function schedule() {
  clearTimeout(g.timer);
  if (!g.playing) return;
  const period = 1000 / Number($("gen-speed").value);
  const now = performance.now();
  g.nextAt = g.nextAt == null || g.nextAt < now - period ? now + period : g.nextAt + period;
  g.timer = setTimeout(tick, Math.max(0, g.nextAt - now));
}

function tick() {
  if (!g.playing || !g.installed) return;
  const last = g.installed.run.transported.indices.length - 1;
  if (g.position >= last) {
    if ($("gen-loop").checked) { setPosition(0); schedule(); return; }
    pause(); renderFrame(); return;
  }
  setPosition(g.position + 1);
  schedule();
}

// ---------------------------------------------------------------------------
// Controls, status and errors

async function refreshRuns() {
  if (!g.base) return;
  try {
    const { ok, value } = await fetchJson(new URL("runs", g.base));
    if (!ok || !Array.isArray(value.runs)) return;
    const select = $("gen-runs");
    // Only well-formed entries are offered; everything shown is escaped.
    const runs = value.runs.filter((r) => C.validRunListEntry(r) && r.state === "completed" && r.evicted === false);
    setHtml(select, html`<option value="">—</option>${runs.map((r) => html`<option value="${r.run_id}">${r.run_id} · seed ${r.seed} · ${r.parameters.n_frames} frames · gain ${r.parameters.controller_gain} · AB ${r.parameters.guide_ab_magnitude}</option>`)}`);
  } catch (error) { /* the list is a convenience */ }
}

async function check() {
  if (!g.base) return;
  hideError();
  try {
    const { ok, value } = await fetchJson(new URL("check", g.base), { method: "POST", body: requestBody(readForm(), "specified") });
    if (ok) renderJobText(`Admitted (nothing computed): ${value.admission.request_count} atmosphere requests, maximum travel ${fmt(value.admission.max_travel_px, 3)} px of ${value.admission.travel_budget_px} px (margin ${fmt(value.admission.margin_px, 3)} px).`);
    else { renderJobText("Not admitted (nothing computed)."); showError(value.message || "refused", value.reasons || []); }
  } catch (error) { showError("The check could not be sent", [error.message]); }
}

function bindControls() {
  $("gen-run").addEventListener("click", () => submit("run"));
  $("gen-new").addEventListener("click", () => submit("new"));
  $("gen-reproduce").addEventListener("click", () => submit("reproduce"));
  $("gen-compare").addEventListener("click", () => submit("compare"));
  $("gen-check").addEventListener("click", check);
  $("gen-form").addEventListener("input", updatePending);
  $("gen-cancel").addEventListener("click", () => cancelJob("visitor"));
  $("gen-disconnect").addEventListener("click", disconnect);
  $("gen-runs-refresh").addEventListener("click", refreshRuns);
  $("gen-runs").addEventListener("change", (event) => { if (event.target.value) loadRun(event.target.value, { origin: "list" }); });
  $("gen-set-reference").addEventListener("click", () => { g.reference = g.installed; remember(g.installed.id, g.installed); updateRunButtons(); renderSummary(); renderCharts(g.installed.run.transported.indices[g.position]); });
  $("gen-clear-reference").addEventListener("click", () => { g.reference = null; updateRunButtons(); renderSummary(); if (g.installed) renderCharts(g.installed.run.transported.indices[g.position]); });
  $("gen-play").addEventListener("click", () => (g.playing ? pause() : play()));
  $("gen-prev").addEventListener("click", () => { pause(); setPosition(g.position - 1); });
  $("gen-next").addEventListener("click", () => { pause(); setPosition(g.position + 1); });
  $("gen-restart").addEventListener("click", () => { pause(); setPosition(0); });
  $("gen-seek").addEventListener("input", (event) => { pause(); setPosition(Number(event.target.value)); });
  $("gen-speed").addEventListener("change", () => { if (g.installed) renderFrame(); });
  $("gen-loop").addEventListener("change", () => { if (g.installed) renderFrame(); });
  for (const input of document.querySelectorAll('input[name="gen-quantity"]')) input.addEventListener("change", (event) => { g.quantity = event.target.value; if (g.installed) { renderColorbars(); renderFrame(); } });
  for (const input of document.querySelectorAll('input[name="gen-obs-mode"]')) input.addEventListener("change", (event) => { g.obsMode = event.target.value; if (g.installed) renderFrame(); });
  const redraw = () => g.installed && renderCharts(g.installed.run.transported.indices[g.position]);
  const observed = ["gen-chart-rms", "gen-chart-strehl", "gen-chart-valid"].map((id) => redrawWhenResized($(id), redraw)).every(Boolean);
  if (!observed) window.addEventListener("resize", redraw);
  if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) $("gen-speed").value = "2";
}

function showError(message, details = []) {
  const box = $("gen-error");
  box.hidden = false;
  setHtml(box, html`<strong>${message}</strong>${details.length ? html`<ul>${details.map((d) => html`<li>${d}</li>`)}</ul>` : ""}`);
}
function hideError() { $("gen-error").hidden = true; $("gen-error").textContent = ""; }
