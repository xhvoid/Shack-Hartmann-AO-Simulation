// Research Results: eight groups of saved evidence, rendered from results.json.
// Figures and evidence files are verified (length + SHA-256) before use.
// Source links open the file at its recorded commit in the repository (an
// external site, only when followed); nothing is requested from it.
// Charts are derived displays of the recorded rows they name; selectors only
// highlight recorded rows/runs and never produce an uncomputed value.

import { BundleError, fetchVerified, fetchVerifiedJson, require } from "./integrity.js";
import { barChart, lineChart, redrawWhenResized } from "./charts.js";

const STATUS_LABELS = {
  executed: "Completed run",
  accepted_domain: "Passed the recorded checks",
  failed_hypothesis: "Hypothesis not supported",
  summary_only: "Summary records only",
  pending: "Pending in the original record",
  derived_analysis: "Saved-data reanalysis",
  analytic_model: "Analytical model output",
};

// Editorial notes are separate from the frozen numerical records.
const RECORD_UPDATES = {
  "R2": "The later dense precision repair also applies to TSVD and Tikhonov. The low retained condition number of the tutorial TSVD example suggests low numerical risk, but this historical trajectory was not rerun with the repaired kernel.",
  "R5": "“Current code” in the original record meant commit 2312502 in October 2026. These results were not rerun on today’s main branch.",
  "R7": "The native and HCIPy loops share the dense reconstructor. Their agreement checks the differing optical components and their combination. Separate matrix-reference tests assess the common solver; this historical comparison retains its original kernel revision.",
  "R8": "The pending detector-level studies listed below describe the original record. Later 42 m detector and spectral sampling and exposure-quadrature studies converged under their stated criteria. In the extended padding study, production EE50 remained unconverged; residual RMS, Strehl and Fourier-reference EE50 converged. These results do not establish convergence of the separate 12 m detector-level configuration."
};
const PUBLIC_DOWNLOADS = {
  "fde92e225e7ff4eae2905495b9a728c343639716640d3776c2eec0e5078f7077": {
    "href": "../evidence/public-records-46a80a01d47afca4/42m-noise-on-record.public.json",
    "bytes": 3774,
    "sha256": "4493b28810feb0713ed317f80c4903fd08942ca0cc139dc552df0b62cef8399c",
    "media_type": "application/json",
    "file_name": "42m-noise-on-record.public.json"
  },
  "b62fd20493a6d3611302ab9262a5372afdc098c66fafc98ceb8d58390e3d6942": {
    "href": "../evidence/public-records-46a80a01d47afca4/detector-noise-law.public.json",
    "bytes": 180136,
    "sha256": "a5277405bf24b6d834065a097711e09d8caa1c182b36c4e05a28dc8a48f5928c",
    "media_type": "application/json",
    "file_name": "detector-noise-law.public.json"
  }
};

let repository = null;

const RECORD_SCOPE = {
  R1: ["Tutorial geometry: 1 m pupil and small lenslet grids; the Explorer's 2 m profile is separate.", "Saved display precision is 8 or 6 decimals; uncertainty was unrecorded.", "Precision uses accepted components; availability reports their fraction."],
  R2: ["The noiseless runs last 12–16 frames, with one realization each.", "The correction-order residual combines spatial sensing, reconstruction, DM fitting and temporal tracking.", "Tutorial 04's trajectories and Tutorial 03's singular spectrum survive in the figures only."],
  R3: ["Noise-free 2 m loops with 7 × 7 lenslets; the interactive detector-level case has its own profile.", "The profiles use r0 = 0.1263 and 0.13 m at 500 nm.", "The calculation is on axis. Layer heights are metadata; science images were not recorded."],
  R4: ["Revisions @1–@3 change control policy; each retains its experiment identity.", "lost_lock compares the final post-update and open-loop residuals; zero valid measurements can still produce a false value.", "The predeclared noise-law test uses unscaled fit errors; S4 and LIM-18 remain open.", "Camera presets are synthetic engineering inputs."],
  R5: ["The noiseless capability record uses a different profile, a pre-update residual and an open-loop average including startup. Its values answer a different question from the physical-camera records.", "Producer: commit 2312502, October 2026.", "The four-second reference repeats the fastest layers' periodic bands.", "This historical group retains summaries. The separate 500-frame replay has its own evidence.", "Peak RSS is the process-lifetime ru_maxrss high-water mark; the recorded host architecture is arm64."],
  R6: ["Analytical MCAO adapter: P3 correction-band PSD, local fitting-tail completion and MASTSEL propagation.", "It has its own wavelength, residual convention, configuration and budget.", "Original producer and date fields are absent; notebook hashes identify files rather than execution dates.", "Aperture energy uses a 50 mas radius and full-field denominator.", "Contour-width bias against the annular reference is −0.50% at 5 mas pixels and −0.12% at 2.5 mas. Seeing-scan changes are differential at fixed sampling."],
  R7: ["The accepted comparison covers one small fixture.", "The reduced-scale 5 m Z4 result is summary-only; its raw comparison JSON was not retained.", "high_order_10m_hcipy@4 remains an unpublished draft."],
  R8: ["ESO tiers, detector-level profiles and the analytical adapter have separate convergence domains; the 2 November note records the later 42 m work.", "The numerical machinery and the experiments using it have separate execution records.", "Science images sample frame start; finite-shutter integration is outside this image definition."]
};

function sourceHref(s) {
  if (!repository || !s.path) return null;
  const commit = s.commit || repository.commit;
  const lines = s.lines ? `#L${s.lines[0]}-L${s.lines[1]}` : "";
  return `${repository.url}/blob/${commit}/${s.path.split("/").map(encodeURIComponent).join("/")}${lines}`;
}

const esc = (text) => String(text ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", "\"": "&quot;" }[c]));

function formatValue(value, column, row) {
  if (value === null || value === undefined) {
    const reason = row[`${column.key}_null_reason`];
    return { html: "—", cls: "null", title: reason || "not recorded" };
  }
  if (typeof value === "boolean") return { html: value ? "yes" : "no", cls: "" };
  if (typeof value === "number") {
    const text = column.digits != null ? value.toFixed(column.digits) : (Number.isInteger(value) ? String(value) : String(Number(value.toPrecision(8))));
    return { html: esc(text), cls: "num" };
  }
  if (typeof value === "object") return { html: `<code>${esc(JSON.stringify(value))}</code>`, cls: "" };
  return { html: esc(value), cls: "" };
}

function renderTable(table, highlight) {
  const head = table.columns.map((c) => `<th scope="col">${esc(c.label)}${c.unit ? ` (${esc(c.unit)})` : ""}</th>`).join("");
  const rows = table.rows.map((row) => {
    const selected = highlight && Object.values(row).some((v) => v === highlight);
    return `<tr${selected ? ' class="selected" style="background:#fff3c4"' : ""}>${table.columns.map((c) => {
      const f = formatValue(row[c.key], c, row);
      return `<td class="${f.cls}"${f.title ? ` title="${esc(f.title)}"` : ""}>${f.html}${f.title ? ` <span class="null">(${esc(f.title)})</span>` : ""}</td>`;
    }).join("")}</tr>`;
  }).join("");
  const notes = [table.uncertainty && `Uncertainty: ${table.uncertainty}.`, table.precision_note, table.notes].filter(Boolean).map(esc).join(" ");
  // The title sits outside the scroll box, so it wraps at the box's width
  // rather than the table's; it names the box, a focusable region that a
  // keyboard can scroll when the table is wider than the screen.
  const titleId = esc(`table-${table.id}`);
  return `<p class="table-title" id="${titleId}">${esc(table.title)}</p><div class="table-scroll" role="region" tabindex="0" aria-labelledby="${titleId}"><table aria-labelledby="${titleId}"><thead><tr>${head}</tr></thead><tbody>${rows}</tbody></table></div>${notes ? `<p class="hint">${notes}</p>` : ""}`;
}

function sourceList(items) {
  const flat = [];
  const visit = (item) => {
    if (!item) return;
    if (Array.isArray(item)) { item.forEach(visit); return; }
    if (item.path) flat.push(item);
  };
  items.forEach(visit);
  const seen = new Set();
  return flat.filter((s) => { const key = `${s.path}|${s.locator || s.lines}`; if (seen.has(key)) return false; seen.add(key); return true; })
    .map((s) => {
      const href = sourceHref(s);
      const at = s.commit ? ` at historical producer ${esc(s.commit.slice(0, 12))}` : "";
      return `<li><code>${esc(s.path)}</code>${at}${s.locator ? ` — ${esc(s.locator)}` : ""}${s.lines ? ` — lines ${s.lines.join("–")} (contains “${esc(s.contains)}”)` : ""}${href ? ` — <a href="${esc(href)}" target="_blank" rel="noopener noreferrer">view at ${esc((s.commit || repository.commit).slice(0, 12))}</a>` : ""}<br><span class="hint">SHA-256 ${esc(s.sha256)}</span></li>`;
    }).join("");
}

async function attachFigure(figure, resultsUrl, host) {
  const box = document.createElement("figure");
  const provenance = figure.provenance?.notebook_output?.locator || figure.source?.locator || "";
  box.innerHTML = `<div class="status">Loading figure…</div><figcaption>${esc(figure.caption.replace("closed-loop RMS and H-band Marechal estimate", "closed-loop RMS and its H-band Maréchal conversion"))}<br><span class="hint">${esc(figure.kind === "extracted_notebook_output" ? figure.transformation : "byte-identical copy of the repository figure")}; source <code>${esc(figure.source.path)}</code>${provenance ? ` (${esc(provenance)})` : ""}${figure.provenance && figure.provenance.byte_identical_to_notebook_output === false ? "; exported at a different rendering resolution from the inline notebook image" : ""}.</span></figcaption>`;
  host.append(box);
  try {
    const { buffer } = await fetchVerified(figure.asset, resultsUrl, { expectType: "image/png" });
    const img = document.createElement("img");
    img.alt = figure.alt; img.width = figure.pixel_size[0]; img.height = figure.pixel_size[1]; img.loading = "lazy";
    img.src = URL.createObjectURL(new Blob([buffer], { type: "image/png" }));
    box.querySelector(".status").replaceWith(img);
  } catch (error) {
    box.querySelector(".status").outerHTML = `<div class="error" role="alert"><strong>Figure unavailable.</strong>${esc(error.message)}</div>`;
  }
}

function drawChart(canvas, chart, highlight) {
  if (chart.type === "bar") { barChart(canvas, chart); return; }
  const series = chart.series.map((s) => ({ ...s, style: chart.type === "scatter" ? "points" : s.style }));
  let extra = [];
  if (highlight && chart.type === "scatter") {
    const seed = Number(String(highlight).replace(/\D/g, ""));
    const rows = chart._rows || [];
    const row = rows.find((r) => r.root_seed === seed && String(r.record || "").startsWith("S2"));
    if (row) extra = [{ label: `selected: seed ${seed}`, points: [[row.residual_nm, row.peak_strehl_2p2um]], style: "points", color: "#a3324e" }];
  }
  lineChart(canvas, { ...chart, series: [...series, ...extra], highlight: chart.type === "line" ? highlight : null, shadeX: chart.shade_x, referenceLines: chart.reference_lines, height: 260 });
}

// Context values are recorded in SI units; show them with a readable unit.
function contextEntry(key, value) {
  let label = key.replaceAll("_", " ");
  if (key.endsWith("_m")) label = label.replace(/ m$/, key.endsWith("_wavelength_m") ? "" : " (m)");
  let text;
  if (typeof value === "number" && key.endsWith("_wavelength_m")) {
    text = value < 1e-6 ? `${(value * 1e9).toFixed(0)} nm` : `${(value * 1e6).toFixed(2)} µm`;
  } else if (typeof value === "number" && key.endsWith("_m")) {
    label = label.replace(/ \(m\)$/, "");
    text = `${value} m`;
  } else if (Array.isArray(value)) {
    text = value.join(", ");
  } else if (value && typeof value === "object") {
    text = Object.entries(value).map(([k, v]) => `${k} ${v}`).join(", ");
  } else {
    text = String(value);
  }
  return `<dt>${esc(label)}</dt><dd>${esc(text)}</dd>`;
}

function renderGroup(group, resultsUrl) {
  const card = document.createElement("article");
  card.className = "result"; card.id = `result-${group.id}`;
  const context = Object.entries(group.context).map(([k, v]) => contextEntry(k, v)).join("");
  const badges = group.status.map((s) => `<span class="badge ${esc(s)}">${esc(STATUS_LABELS[s] || s)}</span>`).join("");
  const keyvals = group.key_values.map((k) => `<div class="keyval"><div class="v">${esc(k.display)}${k.unit ? ` ${esc(k.unit)}` : ""}</div><div class="l">${esc(k.label)}</div></div>`).join("");
  card.innerHTML = `
<header><p class="hint">Historical record ${esc(group.id)}</p><h2>${esc(group.id === "R7" ? "Native and HCIPy component comparisons" : group.title)}</h2><p class="question">${esc(group.id === "R5" ? "What did the October 2026 replay show, and how much did the result vary between realizations?" : group.question)}</p><div class="badges">${badges}</div></header>
${RECORD_UPDATES[group.id] ? `<aside class="panel"><p><strong>Interpretation updated 2 November 2026.</strong> ${esc(RECORD_UPDATES[group.id])}</p><a href="evidence/verification-update-2026-11-02.md">Scope and current qualifications →</a></aside>` : ""}
<dl class="context">${context}</dl>
<div class="keyvals">${keyvals}</div>
<p class="takeaway"><strong>Recorded result.</strong> ${esc(group.id === "R7" ? group.takeaway.replace("the two independent backends", "the native and HCIPy optical paths") : group.takeaway)}</p>
<div class="selector-host"></div>
<div class="charts-host"></div>
<div class="tables-host"></div>
<div class="figures"></div>
<h3>Scope of the record</h3><ul class="limits">${RECORD_SCOPE[group.id].map((l) => `<li>${esc(l)}</li>`).join("")}</ul>
${group.evidence_notes.length ? `<h3>Notes on the source records</h3><ul class="limits">${group.evidence_notes.map((l) => `<li>${esc(l)}</li>`).join("")}</ul>` : ""}
<details><summary>Sources, generation details and licence</summary>
<p class="hint">Producer: ${esc(Object.entries(group.producer).map(([k, v]) => `${k}: ${v}`).join("; "))}.</p>
<p class="hint">Licence: ${esc(group.licence)}</p>
<ul class="limits">${sourceList([group.sources, group.context_sources, ...group.tables.map((t) => t.source), group.key_values.map((k) => k.source), group.limitation_locators, group.erratum, group.doc_contradiction, group.z4_summary, group.draft_status, group.licence_source])}</ul>
</details>
<div class="downloads-host"></div>`;
  const chartsHost = card.querySelector(".charts-host");
  const tablesHost = card.querySelector(".tables-host");
  const canvases = [];
  const rowsById = Object.fromEntries(group.tables.map((t) => [t.id, t.rows]));
  for (const chart of group.charts) {
    const figure = document.createElement("figure");
    figure.className = "chart";
    const canvas = document.createElement("canvas");
    canvas.width = 720; canvas.height = 260; canvas.setAttribute("role", "img");
    figure.append(canvas);
    const caption = document.createElement("figcaption");
    caption.innerHTML = `${esc(chart.title)} — derived display of recorded values (${esc(chart.transformation)}; from ${esc(chart.derived_from)}).${chart.missing ? ` ${chart.missing.map((m) => esc(m.reason)).join(" ")}` : ""}${chart.annotations ? ` ${chart.annotations.map((a) => esc(a.text)).join(" ")}` : ""}`;
    figure.append(caption);
    chartsHost.append(figure);
    chart._rows = rowsById[chart.derived_from] || [];
    canvases.push([canvas, chart]);
  }
  let current = null;
  const drawCharts = () => { for (const [canvas, chart] of canvases) drawChart(canvas, chart, current); };
  const redraw = (highlight) => { current = highlight; drawCharts(); tablesHost.innerHTML = group.tables.map((t) => renderTable(t, highlight && t.id === "r5-s2" ? Number(String(highlight).replace(/\D/g, "")) : null)).join(""); };
  if (group.selector) {
    const host = card.querySelector(".selector-host");
    const id = `sel-${group.id}`;
    host.innerHTML = `<label class="selector" for="${id}">Highlight a recorded ${esc(group.selector.kind === "recorded_versions" ? "profile revision" : group.selector.kind === "recorded_runs" ? "realization" : "series")}: <select id="${id}"><option value="">none</option>${group.selector.options.map((o) => `<option>${esc(o)}</option>`).join("")}</select></label> <span class="hint">${esc(group.selector.note)}</span>`;
    host.querySelector("select").addEventListener("change", (event) => {
      let value = event.target.value || null;
      if (value && group.id === "R3") value = (group.charts[0].series.find((s) => s.label.startsWith(value)) || {}).label || value;
      redraw(value);
    });
  }
  // A timer, not requestAnimationFrame: the card must render its tables and
  // charts even in a background page, once it is in the document.
  setTimeout(() => redraw(null), 0);
  // Charts follow their own width (a card drawn while not laid out is redrawn
  // when it gets a size); the window resize event is the fallback.
  const observed = canvases.map(([canvas]) => redrawWhenResized(canvas, drawCharts)).every(Boolean);
  if (!observed) window.addEventListener("resize", drawCharts);
  const figures = card.querySelector(".figures");
  for (const figure of group.figures) attachFigure(figure, resultsUrl, figures);
  if (group.downloads.length) {
    const host = card.querySelector(".downloads-host");
    host.innerHTML = `<p class="downloads"><strong>Data and analysis downloads</strong> (file hashes checked on download): </p>`;
    for (const item of group.downloads) {
      const extract = item.kind === "source_bound_extract";
      const publicCopy = PUBLIC_DOWNLOADS[item.asset.sha256];
      const label = item.label.replace(/^Accepted /, "Recorded ");
      const link = document.createElement("a");
      link.href = "#"; link.textContent = `${label} (${publicCopy ? "public copy; administrative field omitted" : extract ? "source-bound extract of saved notebook outputs" : "byte-identical copy"})`;
      link.title = publicCopy ? `Edited public copy. Original SHA-256 ${item.asset.sha256}; source and edit are recorded inside the copy.` : extract ? `extract of ${item.sources.map((s) => s.path).join(", ")}` : `${item.source.path} — SHA-256 ${item.source.sha256}`;
      link.addEventListener("click", (event) => { event.preventDefault(); saveVerified(link, label, publicCopy || item.asset, publicCopy ? import.meta.url : resultsUrl, publicCopy ? publicCopy.file_name : item.file_name); });
      host.querySelector(".downloads").append(link, document.createTextNode(" "));
    }
  }
  return card;
}

// Offer verified bytes as a file; a failed check replaces the link text with the reason.
async function saveVerified(link, label, ref, resultsUrl, fileName) {
  try {
    const { buffer } = await fetchVerified(ref, resultsUrl);
    const a = document.createElement("a");
    a.href = URL.createObjectURL(new Blob([buffer], { type: ref.media_type }));
    a.download = fileName;
    document.body.append(a); a.click(); a.remove();
  } catch (error) {
    link.textContent = `${label} (unavailable: ${error.message})`;
  }
}

// Every missing table value and chart point must carry a recorded reason
//, as the offline validator requires; otherwise the
// Research Results are refused rather than shown with an unexplained gap.
function checkMissingValues(results) {
  for (const group of results.groups) {
    for (const table of group.tables) {
      table.rows.forEach((row, index) => {
        for (const column of table.columns) {
          if (row[column.key] !== null && row[column.key] !== undefined) continue;
          const reason = row[`${column.key}_null_reason`];
          if (typeof reason !== "string" || !reason.trim()) throw new BundleError(`${group.id}: table ${table.id} row ${index} has a missing ${column.key} without a recorded reason`);
        }
      });
    }
    for (const chart of group.charts) {
      const explained = new Set((chart.missing || []).filter((m) => typeof m.reason === "string" && m.reason.trim()).map((m) => m.x));
      for (const series of chart.series || []) {
        for (const point of series.points) {
          if (point.some((v) => v === null || v === undefined) && !explained.has(point[0])) throw new BundleError(`${group.id}: chart ${chart.id} has a missing point at x = ${point[0]} without a recorded reason`);
        }
      }
    }
  }
}

export async function renderResults(results, resultsUrl, host, indexHost, resultsBuffer) {
  checkMissingValues(results);
  repository = results.source_repository || null;
  host.replaceChildren();
  const note = document.createElement("p");
  note.className = "hint"; note.textContent = results.separation_note;
  host.append(note);
  const update = document.createElement("p");
  update.className = "hint";
  update.innerHTML = 'These are historical records. <a href="evidence/verification-update-2026-11-02.md">Read the 2 November interpretation notes</a> for the shared-solver limits, later 42 m sampling studies and edited public downloads. The saved numerical files retain their original bytes.';
  host.append(update);
  if (resultsBuffer) {
    const all = document.createElement("p");
    all.className = "downloads";
    const link = document.createElement("a");
    link.textContent = "results.json (original records and source hashes; see dated interpretation notes)";
    link.href = URL.createObjectURL(new Blob([resultsBuffer], { type: "application/json" }));
    link.download = "research-results.json";
    all.append(document.createTextNode("Download all experiment records: "), link);
    host.append(all);
  }
  const topics = {
    R4: ['12 m detector behaviour', 'Measurement availability, reconstruction policy and an unresolved noise-law discrepancy.'],
    R6: ['Separate analytical MCAO study', 'A separate model family using P3 and MASTSEL, with its own assumptions and checks.'],
    R5: ['Historical 42 m runs and realization scatter', 'Earlier detector-model runs, with different analysis windows and source versions from the replay above.'],
    R1: ['Sensing and centroid precision', 'Tutorial response calibration, photon budget and measurement availability.'],
    R2: ['Reconstruction and feedback experiments', 'Small-system correction, delay and controllable-order studies.'],
    R3: ['Ten-layer atmosphere: full records', 'Layer profile, structure function and the separate 2 m comparison.'],
    R7: ['Native and HCIPy component comparisons', 'Small-fixture checks with a shared reconstructor, plus a separate reduced-scale study.'],
    R8: ['Numerical sampling, provenance and open questions', 'Profile-specific convergence records and unresolved work.'],
  };
  indexHost.innerHTML = '';
  for (const id of ['R4','R6','R5','R1','R2','R3','R7','R8']) {
    const group=results.groups.find(g=>g.id===id), [title,description]=topics[id];
    const detail=document.createElement('details');detail.className='appendix-record panel';detail.id=`result-${id}`;
    const summary=document.createElement('summary');summary.textContent=title;
    const note=document.createElement('p');note.className='hint';note.textContent=description;
    detail.append(summary,note);let built=false;
    detail.addEventListener('toggle',()=>{
      if(!detail.open||built)return;built=true;
      const card=renderGroup(group,resultsUrl);card.id=`record-${id}`;detail.append(card);
    });host.append(detail);
  }
  const coverage = document.createElement("details");
  coverage.innerHTML = `<summary>Index of archived results</summary><div class="table-scroll" role="region" tabindex="0" aria-label="Index of archived results"><table><thead><tr><th>Group</th><th>Figures</th><th>Tables</th><th>Charts</th><th>Key values</th><th>Downloads</th><th>Status</th></tr></thead><tbody>${results.coverage.map((c) => `<tr><td>${esc(c.group)} ${esc(c.group === "R7" ? "Native and HCIPy component comparisons" : c.title)}</td><td class="num">${c.figures}</td><td class="num">${c.tables}</td><td class="num">${c.charts}</td><td class="num">${c.key_values}</td><td class="num">${c.downloads}</td><td>${esc(c.status.map((s) => STATUS_LABELS[s] || s).join(", "))}</td></tr>`).join("")}</tbody></table></div>`;
  host.append(coverage);
}

export function renderProjectEvidence(results) {
  const group=results.groups.find(g=>g.id==='R3');
  const layers=group.tables.find(t=>t.id==='r3-profile').rows;
  const host=document.getElementById('layer-profile');host.replaceChildren();
  for(const layer of [...layers].reverse()) {
    const row=document.createElement('div');row.className='layer-row';
    row.innerHTML=`<span>${(layer.altitude_m/1000).toFixed(1)} km</span><span class="layer-track"><i style="width:${layer.cn2_fraction*100}%"></i></span><span>${(layer.cn2_fraction*100).toFixed(1)}%</span><span>${layer.wind_speed_m_per_s.toFixed(1)} m/s</span>`;
    host.append(row);
  }
  const rows=group.tables.find(t=>t.id==='r3-structure').rows;
  const canvas=document.getElementById('atmosphere-structure');
  const draw=()=>lineChart(canvas,{title:'Saved ten-layer phase structure function',height:260,
    x:{label:'Separation',unit:'m',scale:'log'},y:{label:'Measured / von Kármán',range:[.88,1.06]},
    referenceLines:[{y:1,label:'reference'}],series:[{label:'256-screen measured ratio',points:rows.map(r=>[r.separation_m,r.ratio]),markers:true}]});
  redrawWhenResized(canvas,draw);draw();
  const ratios=rows.slice(1).map(r=>r.ratio);
  document.getElementById('structure-caption').textContent=`Recorded ratios: ${Math.min(...ratios).toFixed(3)}–${Math.max(...ratios).toFixed(3)} beyond one pixel; ${rows[0].ratio.toFixed(3)} at the first separation. The chart and R3 table read the same 256-screen CSV; the denominator is the separately evaluated von Kármán reference.`;
}

// This additive section selects archived statistics; no simulation or metric
// calculation runs in the browser. The preparation ledger remains unchanged.
export function initNgs22(entry, entryUrl) {
  const root = document.getElementById('ngs22');
  if (!root) return;
  const node = name => document.getElementById(`ngs22-${name}`);
  const buttons = [...root.querySelectorAll('[data-ngs-window]')];
  const labels = {original_2m:'Saved 2 m · ±1 µm OPD', draft_22m_v1:'2.2 m original draft · v1', repaired_22m_v2:'2.2 m revision · v2'};
  let ready, manifest, base, results, ledger;
  const member = name => { require(manifest?.files[name], `NGS evidence member missing: ${name}`); return {href:name,...manifest.files[name]}; };
  const fail = error => {node('error').hidden=false;node('error').textContent=`NGS results unavailable: ${error.message}. Reload to retry.`;node('status').textContent='The NGS results could not be loaded or checked.';};
  function showWindow(key) {
    require(['primary','secondary'].includes(key),'Unknown NGS interval');
    node('table-body').replaceChildren(...Object.entries(results[key]).map(([id,x]) => {
      const tr=document.createElement('tr');
      const percent=(n,p)=>`${n}/${x.frames} (${p.toFixed(2)}%)`;
      const values=[labels[id],String(x.frames),x.mean.toFixed(4),x.population_sd.toFixed(4),`${(100*x.cv).toFixed(2)}%`,
        percent(x.clipped_frames,x.clipped_frames_pct),percent(x.applied_boundary_frames,x.applied_boundary_frames_pct),String(x.unusable_frames)];
      values.forEach((text,i)=>{const cell=document.createElement(i?'td':'th');if(!i)cell.scope='row';cell.textContent=text;tr.append(cell);});
      return tr;
    }));
    buttons.forEach(button=>button.setAttribute('aria-pressed',String(button.dataset.ngsWindow===key)));
    node('window-note').textContent=key==='primary'
      ? 'Primary interval [0.2, 1.0) s: 800 saved 2 m frames and 600 frames per 2.2 m run. Different physical scenarios; no framewise pairing with the 2 m baseline.'
      : 'Longer interval [0.2, 2.0) s: 1350 frames per 2.2 m run, with the same atmosphere. The saved 2 m baseline ends at 1.0 s and is omitted here.';
  }
  function valueCell(value) {
    const cell=document.createElement('td');const text=JSON.stringify(value);
    if(text.length<100)cell.textContent=text;
    else {const details=document.createElement('details'),summary=document.createElement('summary'),pre=document.createElement('pre');summary.textContent='Show full value';pre.textContent=JSON.stringify(value,null,2);details.append(summary,pre);cell.append(details);}
    return cell;
  }
  function showLedger() {
    const query=node('filter').value.trim().toLowerCase();
    const rows=ledger.parameters.filter(row=>JSON.stringify(row).toLowerCase().includes(query));
    node('ledger-count').textContent=`${rows.length} of ${ledger.parameters.length} parameter notes shown. The changed settings are listed above.`;
    node('ledger-body').replaceChildren(...rows.map(row=>{
      const tr=document.createElement('tr'),path=document.createElement('th'),status=document.createElement('td'),note=document.createElement('td');
      path.scope='row';path.textContent=row.path;status.textContent=`${row.classification.replaceAll('_',' ')}${row.sources.length?' · '+row.sources.join(', '):''}`;note.textContent=row.note;
      tr.append(path,valueCell(row.baseline_value),valueCell(row.candidate_value),status,note);return tr;
    }));
  }
  async function load() {
    if(ready)return ready;
    ready=(async()=>{
      node('status').textContent='Loading the NGS results…';
      const e=entry.ngs22;require(e?.schema==='ao-explorer.ngs-entry.v1','No supported NGS entry');
      const m=await fetchVerifiedJson({href:e.manifest,bytes:e.manifest_bytes,sha256:e.manifest_sha256,media_type:'application/json'},entryUrl);
      manifest=m.value;base=m.url;require(manifest.schema==='ao-explorer.ngs-manifest.v1'&&manifest.id===e.id,'NGS evidence identity mismatch');
      const [r,l,v]=await Promise.all(['results.json','draft/parameter-ledger.json','validation.json'].map(name=>fetchVerifiedJson(member(name),base)));
      results=r.value;ledger=l.value;
      require(results.science_wavelength_m===1.65e-6 && results.primary.original_2m.frames===800 && results.primary.repaired_22m_v2.frames===600 && results.secondary.repaired_22m_v2.frames===1350,'Unexpected NGS comparison definition');
      require(ledger.parameters.length===131 && results.atmosphere_frames_bitwise_identical===1500 && results.calibration_arrays_identical,'NGS assumptions or pairing evidence incomplete');
      require(v.value.all_1500_atmosphere_maps_matched_bitwise && v.value.baseline_files_unchanged===12,'NGS validation record incomplete');
      showWindow('primary');showLedger();buttons.forEach(b=>b.disabled=false);node('filter').disabled=false;
      const image=await fetchVerified(member('comparison.png'),base,{expectType:'image/png'});
      const imageUrl=URL.createObjectURL(new Blob([image.buffer],{type:'image/png'}));
      node('figure').src=imageUrl;await node('figure').decode();node('figure').hidden=false;node('figure-full').href=imageUrl;
      node('validation').textContent='All 1500 atmosphere maps and the calibration arrays match between v1 and v2; the saved 2 m archive is unchanged.';
      const downloads=[['Methods and definitions','README.md'],['Numerical results','results.json'],['Original 2 m frames (CSV)','original_2m.csv'],
        ['Original 2.2 m frames (CSV)','draft_22m_v1.csv'],['Revised 2.2 m frames (CSV)','repaired_22m_v2.csv'],['Figure (PDF)','comparison.pdf'],
        ['Original parameter draft · historical checkpoint','draft/PARAMETERS.md'],['Original configuration bundle','draft/candidate-config.json'],
        ['All 131 field annotations','draft/parameter-ledger.json'],['Literature source ledger','draft/sources.json'],['Revision assumptions','revision-assumptions.json'],
        ['Executed original 2 m configuration','baseline-2m-config.json'],['Executed 2.2 m v1 configuration','effective-config-v1.json'],['Executed 2.2 m v2 configuration','effective-config-v2.json'],
        ['Loss-of-lock diagnosis','diagnosis.json'],['Recorded verification','validation.json'],['Publication and source hashes','publication.json']];
      for(const [label,name] of downloads){
        const link=document.createElement('a');link.textContent=label;link.href=new URL(name,base);
        link.addEventListener('click',async event=>{
          event.preventDefault();link.textContent=`Checking ${label}…`;
          try{const {buffer}=await fetchVerified(member(name),base);const url=URL.createObjectURL(new Blob([buffer],{type:member(name).media_type}));
            const save=document.createElement('a');save.href=url;save.download=name.split('/').pop();save.click();setTimeout(()=>URL.revokeObjectURL(url),30000);link.textContent=label;
          }catch(error){link.textContent=`${label} unavailable: ${error.message}`;}
        });node('downloads').append(link);
      }
      node('status').textContent='';
    })();return ready;
  }
  buttons.forEach(button=>button.addEventListener('click',()=>{try{showWindow(button.dataset.ngsWindow);}catch(error){fail(error);}}));
  node('filter').addEventListener('input',showLedger);
  if('IntersectionObserver' in window){const observer=new IntersectionObserver(entries=>{if(entries.some(e=>e.isIntersecting)){observer.disconnect();load().catch(fail);}},{rootMargin:'200px'});observer.observe(root);}
  else load().catch(fail);
}
