// Research Results: eight groups of saved evidence, rendered from results.json.
// Figures and evidence files are verified (length + SHA-256) before use.
// Source links open the file at its recorded commit in the repository (an
// external site, only when followed); nothing is requested from it.
// Charts are derived displays of the recorded rows they name; selectors only
// highlight recorded rows/runs and never produce an uncomputed value.

import { BundleError, fetchVerified } from "./integrity.js";
import { barChart, lineChart, redrawWhenResized } from "./charts.js";

const STATUS_LABELS = {
  executed: "Executed result",
  accepted_domain: "Accepted comparison (tested domain)",
  failed_hypothesis: "Recorded failed hypothesis",
  summary_only: "Summary-only evidence",
  pending: "Pending work",
  derived_analysis: "Saved-data reanalysis",
  analytic_model: "Analytical model output",
};

let repository = null;

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
  return `<div class="table-scroll"><table><caption>${esc(table.title)}</caption><thead><tr>${head}</tr></thead><tbody>${rows}</tbody></table></div>${notes ? `<p class="hint">${notes}</p>` : ""}`;
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
  box.innerHTML = `<div class="status">Loading figure…</div><figcaption>${esc(figure.caption)}<br><span class="hint">${esc(figure.kind === "extracted_notebook_output" ? figure.transformation : "byte-identical copy of the repository figure")}; source <code>${esc(figure.source.path)}</code>${provenance ? ` (${esc(provenance)})` : ""}${figure.provenance && figure.provenance.byte_identical_to_notebook_output === false ? "; not byte-identical to the notebook's inline output" : ""}.</span></figcaption>`;
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
<header><h2>${esc(group.id)}. ${esc(group.title)}</h2><p class="question">${esc(group.question)}</p><div class="badges">${badges}</div></header>
<dl class="context">${context}</dl>
<div class="keyvals">${keyvals}</div>
<p class="takeaway"><strong>Takeaway.</strong> ${esc(group.takeaway)}</p>
<div class="selector-host"></div>
<div class="charts-host"></div>
<div class="tables-host"></div>
<div class="figures"></div>
<h3>Limitations</h3><ul class="limits">${group.limitations.map((l) => `<li>${esc(l)}</li>`).join("")}</ul>
${group.evidence_notes.length ? `<h3>Evidence notes</h3><ul class="limits">${group.evidence_notes.map((l) => `<li>${esc(l)}</li>`).join("")}</ul>` : ""}
<details><summary>Sources, producers and licence</summary>
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
    host.innerHTML = `<p class="downloads"><strong>Evidence downloads</strong> (verified against the manifest on download): </p>`;
    for (const item of group.downloads) {
      const extract = item.kind === "source_bound_extract";
      const link = document.createElement("a");
      link.href = "#"; link.textContent = `${item.label} (${extract ? "source-bound extract of saved notebook outputs" : "byte-identical copy"})`;
      link.title = extract ? `extract of ${item.sources.map((s) => s.path).join(", ")}` : `${item.source.path} — SHA-256 ${item.source.sha256}`;
      link.addEventListener("click", (event) => { event.preventDefault(); saveVerified(link, item.label, item.asset, resultsUrl, item.file_name); });
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
// (round-5 review, R5-F02), as the offline validator requires; otherwise the
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
  indexHost.innerHTML = results.groups.map((g) => `<li><a href="#result-${esc(g.id)}">${esc(g.id)} ${esc(g.title.split(":")[0])}</a></li>`).join("");
  const note = document.createElement("p");
  note.className = "hint"; note.textContent = results.separation_note;
  host.append(note);
  if (resultsBuffer) {
    const all = document.createElement("p");
    all.className = "downloads";
    const link = document.createElement("a");
    link.textContent = "results.json (every group, value, locator and digest; verified)";
    link.href = URL.createObjectURL(new Blob([resultsBuffer], { type: "application/json" }));
    link.download = "research-results.json";
    all.append(document.createTextNode("Complete Research Results record: "), link);
    host.append(all);
  }
  for (const group of results.groups) host.append(renderGroup(group, resultsUrl));
  const coverage = document.createElement("details");
  coverage.innerHTML = `<summary>Coverage of the eight required result groups</summary><div class="table-scroll"><table><thead><tr><th>Group</th><th>Figures</th><th>Tables</th><th>Charts</th><th>Key values</th><th>Downloads</th><th>Status</th></tr></thead><tbody>${results.coverage.map((c) => `<tr><td>${esc(c.group)} ${esc(c.title)}</td><td class="num">${c.figures}</td><td class="num">${c.tables}</td><td class="num">${c.charts}</td><td class="num">${c.key_values}</td><td class="num">${c.downloads}</td><td>${esc(c.status.map((s) => STATUS_LABELS[s] || s).join(", "))}</td></tr>`).join("")}</tbody></table></div>`;
  host.append(coverage);
}
