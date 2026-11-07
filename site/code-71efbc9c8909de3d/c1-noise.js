// The separate static C1 noise assessment: one small verified summary drawn as a zero-based chart.
import { fetchVerified, fetchVerifiedJson, require } from './integrity.js';

export function initC1Noise(entry, entryUrl) {
  const root = document.getElementById('c1-noise');
  if (!root) return;
  const node = name => document.getElementById(`c1-${name}`);
  let ready, summary, files, base;
  const file = name => { require(files?.[name], `C1 summary member missing: ${name}`); return {href: name, ...files[name]}; };
  const finite = (x, what) => { require(Number.isFinite(x) && x >= 0, `C1 ${what} is not a finite non-negative number`); return x; };
  function validate(s) {
    require(s?.schema === 'ao-explorer.c1-noise-summary.v1', 'Unsupported C1 summary');
    require(['QUALIFIED_BELOW_C1_TRIGGER', 'QUALIFIED_MATERIAL_BENEFIT', 'INCONCLUSIVE_NUMERICS'].includes(s.status), `Unsupported C1 status ${s.status}`);
    const b = s.dampings?.baseline, c = s.dampings?.comparator;
    require(b?.alpha === 0.001 && c?.alpha === 0.0025, 'C1 summary names unexpected dampings');
    for (const [k, v] of Object.entries({b_rms: b.rms_nm, c_rms: c.rms_nm, b_var: b.variance_nm2, c_var: c.variance_nm2, d: s.difference.rms_nm, r: s.difference.relative_variance_reduction, t: s.decision_rule.trigger_rms_nm})) finite(v, k);
    // Consistency of the published scalars with each other (no science is recomputed here).
    require(Math.abs(b.rms_nm - c.rms_nm - s.difference.rms_nm) < 1e-12 && Math.abs(b.rms_nm ** 2 - b.variance_nm2) < 1e-12 * b.variance_nm2 + 1e-15, 'C1 summary values are inconsistent');
  }
  const svg = (tag, attrs = {}, text) => {
    const e = document.createElementNS('http://www.w3.org/2000/svg', tag);
    for (const [k, v] of Object.entries(attrs)) e.setAttribute(k, v);
    if (text != null) e.textContent = text;
    return e;
  };
  function draw() {
    const b = summary.dampings.baseline, c = summary.dampings.comparator, d = summary.difference, rule = summary.decision_rule;
    // Drawn at the container's own width so that text keeps its size on a phone.
    const W = Math.round(Math.min(760, Math.max(300, node('chart').clientWidth || 720))), narrow = W < 520;
    const L = narrow ? 104 : 210, R = narrow ? 76 : 120, vmax = 1.2, sx = v => L + (W - L - R) * v / vmax;
    const rows = [
      {group: narrow ? 'Detector-noise part (RMS)' : 'Predicted detector-noise contribution (RMS)', label: narrow ? 'α 0.001' : 'Replay setting α 0.001', value: b.rms_nm, key: 'baseline', colour: '#5b7486'},
      {group: null, label: narrow ? 'α 0.0025' : 'Alternative α 0.0025', value: c.rms_nm, key: 'comparator', colour: '#1f5f73'},
      {group: narrow ? 'Against the threshold' : 'Difference against the experiment threshold', label: narrow ? 'Difference' : 'Predicted difference', value: d.rms_nm, key: 'difference', colour: '#1f5f73'},
      {group: null, label: narrow ? 'Trigger' : 'Threshold for a new experiment', value: rule.trigger_rms_nm, key: 'trigger', colour: '#b3541e'},
    ];
    const bars = [];
    let y = 10;
    for (const row of rows) { if (row.group) { bars.push({heading: row.group, y: y + 12}); y += 18; } bars.push({row, y}); y += 32; }
    const bottom = y - 4, H = bottom + 40;
    const chart = svg('svg', {viewBox: `0 0 ${W} ${H}`, width: W, height: H, role: 'img', 'aria-label':
      `Bar chart starting at zero. Predicted detector-noise part: ${b.rms_nm.toFixed(4)} nm at α 0.001 and ${c.rms_nm.toFixed(4)} nm at α 0.0025. Their difference, ${d.rms_nm.toFixed(4)} nm, against the ${rule.trigger_rms_nm.toFixed(1)} nm trigger.`});
    for (const t of narrow ? [0, .4, .8, 1.2] : [0, .2, .4, .6, .8, 1, 1.2]) {
      chart.append(svg('line', {x1: sx(t), x2: sx(t), y1: 4, y2: bottom, stroke: '#ddd6ca'}));
      chart.append(svg('text', {x: sx(t), y: bottom + 15, 'text-anchor': 'middle', class: 'c1-tick'}, t.toFixed(1)));
    }
    chart.append(svg('text', {x: (L + W - R) / 2, y: bottom + 32, 'text-anchor': 'middle', class: 'c1-tick'}, 'nm (axis starts at 0)'));
    for (const item of bars) {
      if (item.heading) { chart.append(svg('text', {x: 8, y: item.y, class: 'c1-group'}, item.heading)); continue; }
      const {row} = item, top = item.y;
      chart.append(svg('text', {x: L - 8, y: top + 16, 'text-anchor': 'end', class: 'c1-label'}, row.label));
      chart.append(svg('rect', {x: L, y: top, width: Math.max(sx(row.value) - L, 1.5), height: 22, fill: row.colour, 'data-key': row.key}));
      chart.append(svg('text', {x: Math.max(sx(row.value), L + 1.5) + 6, y: top + 16, class: 'c1-value'}, `${row.value.toFixed(row.key === 'trigger' ? 1 : 4)} nm`));
    }
    node('chart').replaceChildren(chart);
    node('readout').textContent = `The alternative reduced the predicted variance by ${(100*d.relative_variance_reduction).toFixed(2)}%. My thresholds for a new run were a ${rule.trigger_relative_variance*100}% reduction in variance and a ${rule.trigger_rms_nm.toFixed(0)} nm reduction in RMS.`;
  }
  function details() {
    const b = summary.dampings.baseline, c = summary.dampings.comparator, q = summary.comparator_qualification, cfg = summary.configuration;
    const rows = [
      ['Stationary detector-noise contribution, RMS', `${b.rms_nm.toFixed(4)} nm`, `${c.rms_nm.toFixed(4)} nm`],
      ['Stationary detector-noise contribution, variance', `${b.variance_nm2.toFixed(4)} nm²`, `${c.variance_nm2.toFixed(4)} nm²`],
      ['Single-frame reconstruction noise, RMS', `${b.instantaneous_rms_nm.toFixed(4)} nm`, `${c.instantaneous_rms_nm.toFixed(4)} nm`],
      ['Tip / tilt / defocus one-shot gain', ['tip', 'tilt', 'defocus'].map(k => b.one_shot_gains[k].toFixed(5)).join(' / '), ['tip', 'tilt', 'defocus'].map(k => c.one_shot_gains[k].toFixed(5)).join(' / ')],
      ['Seven flagged modes (variance within)', `${b.seven_mode_within_nm2.toFixed(4)} nm²`, `${c.seven_mode_within_nm2.toFixed(4)} nm²`],
    ];
    node('table-body').replaceChildren(...rows.map(values => {
      const tr = document.createElement('tr');
      values.forEach((text, i) => { const cell = document.createElement(i ? 'td' : 'th'); if (!i) cell.scope = 'row'; cell.textContent = text; tr.append(cell); });
      return tr;
    }));
    node('conditions').textContent = `I calculated the detector covariance for a flat wavefront and treated the lenslets as independent. The stationary linear loop used gain ${cfg.loop_model.gain}, a queue of ${cfg.loop_model.latency_frames} frames and leak ${cfg.loop_model.leak}.`;
    node('qualification').textContent = `I chose the largest damping on the grid that kept the tip, tilt and defocus gains within 1% of unity. The solver met the two pupil-space criteria. In command space, ${q.original_command_space_failures} of 42 checks missed the original tolerance.`;
    node('identities').textContent = `Numerical inputs and source identifiers are available in the C1 summary below.`;
    for (const [label, name] of [['C1 summary (JSON)', 'summary.json'], ['About this summary', 'README.md']]) {
      const link = document.createElement('a'); link.textContent = label; link.href = new URL(name, base);
      link.addEventListener('click', async event => {
        event.preventDefault(); link.textContent = `Checking ${label}…`;
        try {
          const {buffer} = await fetchVerified(file(name), base);
          const url = URL.createObjectURL(new Blob([buffer], {type: file(name).media_type}));
          const a = document.createElement('a'); a.href = url; a.download = name; a.click();
          setTimeout(() => URL.revokeObjectURL(url), 30000); link.textContent = label;
        } catch (error) { link.textContent = `${label} unavailable: ${error.message}`; }
      });
      node('downloads').append(link);
    }
  }
  async function load() {
    if (ready) return ready;
    ready = (async () => {
      const e = entry.c1Noise;
      if (!e) { node('status').textContent = 'The C1 summary is not part of this build; the replay above is unaffected.'; return; }
      node('status').textContent = 'Loading the detector-noise summary…';
      require(e.schema === 'ao-explorer.c1-noise-entry.v1', 'No supported C1 summary entry');
      const m = await fetchVerifiedJson({href: e.manifest, bytes: e.manifest_bytes, sha256: e.manifest_sha256, media_type: 'application/json'}, entryUrl);
      require(m.value.schema === 'ao-explorer.c1-noise-manifest.v1' && m.value.id === e.id, 'C1 manifest identity mismatch');
      files = m.value.files; base = m.url;
      summary = (await fetchVerifiedJson(file('summary.json'), base)).value;
      validate(summary);
      node('rms-b').textContent = `${summary.dampings.baseline.rms_nm.toFixed(4)} nm`;
      node('rms-c').textContent = `${summary.dampings.comparator.rms_nm.toFixed(4)} nm`;
      draw(); details();
      node('status').textContent = '';
    })().catch(error => {
      node('error').hidden = false;
      node('error').textContent = `C1 summary unavailable: ${error.message}. The replay above is unaffected; reload to retry.`;
      node('status').textContent = 'The C1 summary could not be verified.';
    });
    return ready;
  }
  if ('ResizeObserver' in window) { let width = 0; new ResizeObserver(() => { const w = node('chart').clientWidth; if (summary && Math.abs(w - width) > 8) { width = w; draw(); } }).observe(node('chart')); }
  if ('IntersectionObserver' in window) {
    const observer = new IntersectionObserver(items => { if (items.some(i => i.isIntersecting)) { observer.disconnect(); load(); } }, {rootMargin: '200px'});
    observer.observe(root);
  } else load();
  if (location.hash === '#c1-noise' || location.hash === '#c1-provenance') { if (location.hash === '#c1-provenance') node('provenance').open = true; load(); }
}
