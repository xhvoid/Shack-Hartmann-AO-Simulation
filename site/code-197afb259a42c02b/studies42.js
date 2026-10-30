// Shared parts of the two later 42 m studies (guide flux, controller delay):
// verified bundle loading, strict checks of the recorded series, number
// formatting and a frame inspector for the trace charts.  Values are shown as
// recorded; a missing or malformed value stops the view instead of becoming 0.
import { fetchVerified, fetchVerifiedJson, require } from './integrity.js';

export const MINUS = '−';
export const fixed = (v, d) => `${v < 0 ? MINUS : ''}${Math.abs(v).toFixed(d)}`;
export const signed = (v, d) => `${v > 0 ? '+' : v < 0 ? MINUS : ''}${Math.abs(v).toFixed(d)}`;
export const seconds = (frame, rate) => `${(frame / rate).toFixed(3)} s`;

// Agreement of a value recomputed in the browser with the bundle's recorded value.
export function agrees(a, b, scale = 1e-9) {
  return Number.isFinite(a) && Number.isFinite(b) && Math.abs(a - b) <= scale * Math.max(1, Math.abs(b));
}

export function series(values, length, what, { positive = false, fraction = false } = {}) {
  require(Array.isArray(values) && values.length === length, `${what} does not hold ${length} frames`);
  for (const v of values) {
    require(typeof v === 'number' && Number.isFinite(v), `${what} holds a missing or non-finite value`);
    if (positive) require(v > 0, `${what} holds a non-positive RMS value`);
    if (fraction) require(v >= 0 && v <= 1, `${what} holds a fraction outside [0, 1]`);
  }
  return values;
}

// Arithmetic mean of the per-frame values over the half-open frame window [a, b).
export function windowMean(values, [a, b]) {
  require(Number.isInteger(a) && Number.isInteger(b) && 0 <= a && a < b && b <= values.length, `window [${a},${b}) is outside the record`);
  let sum = 0;
  for (let k = a; k < b; k += 1) sum += values[k];
  return sum / (b - a);
}

export function finitePositive(value, what) {
  require(typeof value === 'number' && Number.isFinite(value) && value > 0, `${what} is missing or not a positive number`);
  return value;
}

// Manifest and data of one study bundle, each verified by size and SHA-256 against the record that names it.
export async function loadStudy(entry, key, schemas, entryUrl) {
  const e = entry[key];
  if (!e) return null;
  require(e.schema === schemas.entry && typeof e.id === 'string', `no supported ${key} entry`);
  const m = await fetchVerifiedJson({ href: e.manifest, bytes: e.manifest_bytes, sha256: e.manifest_sha256, media_type: 'application/json' }, entryUrl);
  require(m.value.schema === schemas.manifest && m.value.id === e.id && m.value.files && typeof m.value.files === 'object', `${key} manifest identity mismatch`);
  const files = m.value.files;
  const member = (name) => { require(files[name], `${key} member missing: ${name}`); return { href: name, ...files[name] }; };
  const data = (await fetchVerifiedJson(member('data.json'), m.url)).value;
  return { id: e.id, base: m.url, member, data };
}

// Download links that hand over the exact verified bytes.
export function addDownloads(container, bundle, items) {
  for (const [label, name] of items) {
    const link = document.createElement('a');
    link.textContent = label;
    link.href = new URL(name, bundle.base);
    link.addEventListener('click', async (event) => {
      event.preventDefault();
      link.textContent = `Checking ${label}…`;
      try {
        const ref = bundle.member(name);
        const { buffer } = await fetchVerified(ref, bundle.base);
        const url = URL.createObjectURL(new Blob([buffer], { type: ref.media_type }));
        const a = document.createElement('a'); a.href = url; a.download = name; a.click();
        setTimeout(() => URL.revokeObjectURL(url), 30000);
        link.textContent = label;
      } catch (error) { link.textContent = `${label} unavailable: ${error.message}`; }
    });
    container.append(link);
  }
}

export function cell(tag, text, attrs = {}) {
  const element = document.createElement(tag);
  element.textContent = text;
  for (const [k, v] of Object.entries(attrs)) element.setAttribute(k, v);
  return element;
}

export function tableRows(body, rows) {
  body.replaceChildren(...rows.map((values) => {
    const tr = document.createElement('tr');
    values.forEach((value, i) => {
      const item = typeof value === 'object' && value !== null ? value : { text: value };
      const element = cell(i ? 'td' : 'th', item.text, i ? {} : { scope: 'row' });
      if (item.colspan) element.colSpan = item.colspan;
      if (item.className) element.className = item.className;
      tr.append(element);
    });
    return tr;
  }));
}

// Hovering a trace chart shows the recorded values of the nearest frame; the
// range input does the same from the keyboard.  Both move one shared cursor.
export function frameInspector({ canvases, slider, rate, firstFrame, lastFrame, describe, onFrame }) {
  const tips = new Map();
  for (const canvas of canvases) {
    const figure = canvas.parentElement;
    const tip = document.createElement('div');
    tip.className = 'studies42-tip'; tip.hidden = true; tip.setAttribute('aria-hidden', 'true');
    figure.append(tip); tips.set(canvas, tip);
    canvas.addEventListener('pointermove', (event) => {
      const map = canvas.studiesMap;
      if (!map) return;
      const rect = canvas.getBoundingClientRect();
      const px = event.clientX - rect.left;
      if (px < map.left || px > map.right) { tip.hidden = true; return; }
      const frame = Math.min(lastFrame(), Math.max(firstFrame(), Math.round(map.toValue(px) * rate)));
      tip.replaceChildren(...describe(frame).map((line) => cell('div', line)));
      tip.hidden = false;
      const left = Math.min(Math.max(0, px + 12), Math.max(0, rect.width - tip.offsetWidth));
      tip.style.left = `${left + canvas.offsetLeft}px`;
      tip.style.top = `${Math.max(0, event.clientY - rect.top - tip.offsetHeight - 10) + canvas.offsetTop}px`;
      onFrame(frame, false);
    });
    canvas.addEventListener('pointerleave', () => { tip.hidden = true; });
  }
  slider.addEventListener('input', () => onFrame(Number(slider.value), true));
}
