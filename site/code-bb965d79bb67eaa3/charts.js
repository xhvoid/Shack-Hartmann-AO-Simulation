// Minimal canvas charts for recorded values.  Points are drawn exactly as
// given: no smoothing, interpolation, fitting or resampling.  A null value is
// a gap, never a zero.

export const PALETTE = ["#1f5f73", "#b3541e", "#6b5aa6", "#4d7a2a", "#7d7d7d", "#a3324e"];

function niceTicks(min, max, count = 5) {
  if (!(max > min)) return [min];
  const span = max - min;
  const step0 = span / count;
  const power = Math.pow(10, Math.floor(Math.log10(step0)));
  const step = [1, 2, 2.5, 5, 10].map((m) => m * power).find((s) => span / s <= count) || step0;
  const ticks = [];
  for (let v = Math.ceil(min / step) * step; v <= max + step * 1e-9; v += step) ticks.push(Number(v.toPrecision(12)));
  return ticks;
}

function logTicks(min, max) {
  const ticks = [];
  for (let p = Math.floor(Math.log10(min)); p <= Math.ceil(Math.log10(max)); p += 1) {
    const v = Math.pow(10, p);
    if (v >= min * 0.999 && v <= max * 1.001) ticks.push(v);
  }
  return ticks.length >= 2 ? ticks : [min, max];
}

export function formatTick(v) {
  if (v === 0) return "0";
  const a = Math.abs(v);
  if (a >= 1e4 || a < 1e-3) return v.toExponential(0);
  return String(Number(v.toPrecision(4)));
}

// The CSS width to draw at.  A canvas that is not laid out (a background
// page, a collapsed section) has no client width; it is drawn at its declared
// width, never at a previous bitmap width (which includes the device pixel
// ratio), and redrawWhenResized redraws it once it has a size.
function cssWidth(canvas) {
  if (!canvas.dataset.declaredWidth) canvas.dataset.declaredWidth = String(canvas.width);
  return Math.max(260, canvas.clientWidth || Number(canvas.dataset.declaredWidth));
}

export function redrawWhenResized(canvas, draw) {
  if (!("ResizeObserver" in window)) return false;
  new ResizeObserver(() => { if (String(canvas.clientWidth) !== canvas.dataset.drawnWidth) draw(); }).observe(canvas);
  return true;
}

function prepare(canvas, height) {
  const dpr = window.devicePixelRatio || 1;
  const width = cssWidth(canvas);
  canvas.dataset.drawnWidth = String(canvas.clientWidth);
  const h = height || canvas.height;
  canvas.width = Math.round(width * dpr);
  canvas.height = Math.round(h * dpr);
  canvas.style.height = `${h}px`;
  const ctx = canvas.getContext("2d");
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  ctx.clearRect(0, 0, width, h);
  ctx.font = "11px -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif";
  return { ctx, width, height: h };
}

function extent(values, scale) {
  const finite = values.filter((v) => v !== null && Number.isFinite(v) && (scale !== "log" || v > 0));
  if (!finite.length) return [0, 1];
  let min = Math.min(...finite);
  let max = Math.max(...finite);
  if (min === max) { min = scale === "log" ? min / 2 : min - 1; max = scale === "log" ? max * 2 : max + 1; }
  if (scale !== "log") { const pad = (max - min) * 0.06; min -= pad; max += pad; }
  else { min /= 1.3; max *= 1.3; }
  return [min, max];
}

// Legend entries flow left to right by their measured width and wrap onto
// new rows, so no label is clipped at narrow widths.
function legendLayout(ctx, series, left, right) {
  const placed = [];
  let x = left; let row = 0;
  for (const s of series) {
    const w = 16 + ctx.measureText(s.label).width + 14;
    if (x > left && x + w > right) { x = left; row += 1; }
    placed.push({ x, row });
    x += w;
  }
  return { placed, rows: series.length ? row + 1 : 0 };
}

export function lineChart(canvas, spec) {
  // Shaded-band labels get their own strip above the plot area, where no data
  // is drawn; inside a band narrower than its label they ran into the curves.
  const strip = (spec.shadeX || []).some((shade) => shade[2]) ? 14 : 0;
  const { ctx, width, height } = prepare(canvas, spec.height && spec.height + strip);
  const legend = legendLayout(ctx, spec.series, 8, width - 8);
  const m = { l: 58, r: 12, t: 8 + legend.rows * 14 + 4 + strip, b: 34 };
  const xs = []; const ys = [];
  for (const s of spec.series) for (const p of s.points) {
    xs.push(p[0]); ys.push(p[1]);
    if (p.length > 2 && p[2] != null && p[1] != null) { ys.push(p[1] + p[2]); ys.push(p[1] - p[2]); }
  }
  for (const r of spec.referenceLines || []) if (r.y != null) ys.push(r.y);
  const xScale = spec.x.scale || "linear"; const yScale = spec.y.scale || "linear";
  let [x0, x1] = spec.x.range || extent(xs, xScale);
  let [y0, y1] = spec.y.range || extent(ys, yScale);
  const tx = (v) => m.l + (xScale === "log" ? (Math.log10(v) - Math.log10(x0)) / (Math.log10(x1) - Math.log10(x0)) : (v - x0) / (x1 - x0)) * (width - m.l - m.r);
  const ty = (v) => height - m.b - (yScale === "log" ? (Math.log10(v) - Math.log10(y0)) / (Math.log10(y1) - Math.log10(y0)) : (v - y0) / (y1 - y0)) * (height - m.t - m.b);
  ctx.strokeStyle = "#ddd6ca"; ctx.fillStyle = "#5c6168"; ctx.lineWidth = 1;
  for (const shade of spec.shadeX || []) {
    ctx.fillStyle = shade[3] || "rgba(92, 97, 104, 0.10)";
    const a = tx(Math.max(shade[0], x0)); const b = tx(Math.min(shade[1], x1));
    ctx.fillRect(a, m.t, b - a, height - m.t - m.b);
    if (shade[2]) { ctx.fillStyle = "#5c6168"; ctx.fillText(shade[2], Math.min(a + 4, width - m.r - ctx.measureText(shade[2]).width), m.t - 4); }
  }
  ctx.fillStyle = "#5c6168";
  const xt = xScale === "log" ? logTicks(x0, x1) : niceTicks(x0, x1, 6);
  const yt = yScale === "log" ? logTicks(y0, y1) : niceTicks(y0, y1, 4);
  ctx.textAlign = "center";
  for (const v of xt) { const x = tx(v); ctx.beginPath(); ctx.moveTo(x, m.t); ctx.lineTo(x, height - m.b); ctx.stroke(); ctx.fillText(formatTick(v), x, height - m.b + 13); }
  ctx.textAlign = "right";
  for (const v of yt) { const y = ty(v); ctx.beginPath(); ctx.moveTo(m.l, y); ctx.lineTo(width - m.r, y); ctx.stroke(); ctx.fillText(formatTick(v), m.l - 5, y + 3); }
  ctx.textAlign = "center";
  ctx.fillText(`${spec.x.label}${spec.x.unit ? ` (${spec.x.unit})` : ""}`, (m.l + width - m.r) / 2, height - 4);
  ctx.save(); ctx.translate(12, (m.t + height - m.b) / 2); ctx.rotate(-Math.PI / 2);
  ctx.fillText(`${spec.y.label}${spec.y.unit ? ` (${spec.y.unit})` : ""}`, 0, 0); ctx.restore();
  for (const r of spec.referenceLines || []) {
    if (r.y == null) continue;
    ctx.setLineDash([3, 3]); ctx.strokeStyle = "#7d7d7d"; ctx.beginPath(); ctx.moveTo(m.l, ty(r.y)); ctx.lineTo(width - m.r, ty(r.y)); ctx.stroke(); ctx.setLineDash([]);
    ctx.textAlign = "left"; ctx.fillStyle = "#5c6168"; ctx.fillText(r.label || "", m.l + 4, ty(r.y) - 3);
  }
  spec.series.forEach((s, index) => {
    const color = s.color || PALETTE[index % PALETTE.length];
    const emphasis = spec.highlight == null || spec.highlight === s.label;
    ctx.globalAlpha = emphasis ? 1 : 0.3;
    ctx.strokeStyle = color; ctx.fillStyle = color; ctx.lineWidth = s.width || 1.6;
    if (s.style === "dashed") ctx.setLineDash([5, 4]);
    if (s.style !== "points") {
      ctx.beginPath(); let open = false;
      for (const p of s.points) {
        if (p[1] == null || !Number.isFinite(p[1])) { open = false; continue; }
        const x = tx(p[0]); const y = ty(p[1]);
        if (!open) { ctx.moveTo(x, y); open = true; } else ctx.lineTo(x, y);
      }
      ctx.stroke();
    }
    ctx.setLineDash([]);
    if (s.style === "points" || s.markers || s.points.length <= 40) {
      for (const p of s.points) {
        if (p[1] == null || !Number.isFinite(p[1])) continue;
        const x = tx(p[0]); const y = ty(p[1]);
        if (p.length > 2 && p[2] != null) {
          ctx.beginPath(); ctx.moveTo(x, ty(Math.max(p[1] - p[2], yScale === "log" ? y0 : -Infinity))); ctx.lineTo(x, ty(p[1] + p[2])); ctx.stroke();
        }
        ctx.beginPath(); ctx.arc(x, y, 2.6, 0, 2 * Math.PI); ctx.fill();
      }
    }
    ctx.globalAlpha = 1;
  });
  for (const miss of spec.missing || []) {
    const x = tx(miss.x); ctx.fillStyle = "#a3324e"; ctx.textAlign = "center";
    ctx.fillText("no valid value", x, m.t + 10);
  }
  for (const event of spec.verticalLines || []) {
    if (!Number.isFinite(event.x) || event.x < x0 || event.x > x1) continue;
    const x = tx(event.x);
    ctx.strokeStyle = event.color || "#a3324e"; ctx.lineWidth = 1.5; ctx.setLineDash([5, 4]);
    ctx.beginPath(); ctx.moveTo(x, m.t); ctx.lineTo(x, height - m.b); ctx.stroke(); ctx.setLineDash([]);
    const label = event.label || "";
    ctx.fillStyle = event.color || "#a3324e"; ctx.textAlign = "left";
    ctx.fillText(label, Math.max(m.l + 2, Math.min(x + 5, width - m.r - ctx.measureText(label).width)), m.t + 13 + 12 * (event.row || 0));
  }
  if (spec.cursorX != null) {
    ctx.strokeStyle = "#23262a"; ctx.lineWidth = 1; ctx.beginPath(); ctx.moveTo(tx(spec.cursorX), m.t); ctx.lineTo(tx(spec.cursorX), height - m.b); ctx.stroke();
    // An optional label says what the cursor marks (for example a paused frame).
    if (spec.cursorLabel) {
      const right = tx(spec.cursorX) > (m.l + width - m.r) / 2;
      ctx.fillStyle = "#23262a"; ctx.textAlign = right ? "right" : "left";
      ctx.fillText(spec.cursorLabel, tx(spec.cursorX) + (right ? -4 : 4), m.t + 11);
    }
  }
  for (const tick of spec.ticksBelow || []) {
    ctx.fillStyle = tick.color || "#a3324e"; ctx.fillRect(tx(tick.x) - 1, height - m.b + 1, 2, 5);
  }
  ctx.textAlign = "left";
  spec.series.forEach((s, index) => {
    const color = s.color || PALETTE[index % PALETTE.length];
    const { x, row } = legend.placed[index];
    const y = 14 + row * 14;
    if (s.style === "dashed") {
      // The legend repeats a dashed series' line style, not only its colour.
      ctx.strokeStyle = color; ctx.lineWidth = 2; ctx.setLineDash([4, 2]);
      ctx.beginPath(); ctx.moveTo(x, y - 5.5); ctx.lineTo(x + 12, y - 5.5); ctx.stroke(); ctx.setLineDash([]);
    } else {
      ctx.fillStyle = color; ctx.fillRect(x, y - 7, 12, 3);
    }
    ctx.fillStyle = "#23262a"; ctx.fillText(s.label, x + 16, y - 2);
  });
  canvas.setAttribute("aria-label", `${spec.title || "Chart"}: ${spec.series.map((s) => s.label).join("; ")}`);
  // The drawn x mapping (linear axes), so a caller can turn a pointer position back into a data value.
  return { toValue: (px) => x0 + ((px - m.l) / (width - m.l - m.r)) * (x1 - x0), left: m.l, right: width - m.r };
}

// Horizontal bars: one row per category with its full label, so labels never
// overlap or clip at any width.
export function barChart(canvas, spec) {
  const rowHeight = 22;
  const probe = canvas.getContext("2d");
  probe.font = "11px -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif";
  const available = cssWidth(canvas);
  const labelWidth = Math.min(Math.max(...spec.categories.map((c) => probe.measureText(c).width), 10) + 10, available * 0.55);
  const height = 30 + rowHeight * spec.categories.length + 24;
  const { ctx, width } = prepare(canvas, height);
  const m = { l: labelWidth, r: 56, t: 10, b: 30 };
  const values = spec.values;
  const max = Math.max(...values.map((v) => Math.abs(v)), 1e-12);
  const xt = niceTicks(0, max * 1.05, 4);
  // The axis always extends past the largest value so its bar and label fit.
  const right = Math.max(xt[xt.length - 1], max * 1.12);
  const tx = (v) => m.l + (v / right) * (width - m.l - m.r);
  ctx.strokeStyle = "#ddd6ca"; ctx.fillStyle = "#5c6168"; ctx.textAlign = "center";
  for (const v of xt) { const x = tx(v); ctx.beginPath(); ctx.moveTo(x, m.t); ctx.lineTo(x, height - m.b); ctx.stroke(); ctx.fillText(formatTick(v), x, height - m.b + 13); }
  ctx.fillText(`${spec.y.label}${spec.y.unit ? ` (${spec.y.unit})` : ""}`, (m.l + width - m.r) / 2, height - 4);
  values.forEach((v, i) => {
    const y = m.t + i * rowHeight;
    ctx.fillStyle = PALETTE[0];
    ctx.fillRect(m.l, y + 4, Math.max(1, tx(Math.abs(v)) - m.l), rowHeight - 8);
    ctx.fillStyle = "#23262a"; ctx.textAlign = "right";
    // Shorten with the ellipsis included in the fitted width, so the label
    // never reaches past the canvas edge.
    let label = spec.categories[i];
    if (ctx.measureText(label).width > m.l - 8) {
      while (label.length > 1 && ctx.measureText(`${label}…`).width > m.l - 8) label = label.slice(0, -1);
      label = `${label}…`;
    }
    ctx.fillText(label, m.l - 6, y + rowHeight / 2 + 4);
    ctx.textAlign = "left"; ctx.fillStyle = "#5c6168";
    ctx.fillText(formatTick(v), tx(Math.abs(v)) + 4, y + rowHeight / 2 + 4);
  });
  canvas.setAttribute("aria-label", `${spec.title || "Bar chart"}: ${spec.categories.map((c, i) => `${c} ${formatTick(values[i])}`).join("; ")}`);
}
