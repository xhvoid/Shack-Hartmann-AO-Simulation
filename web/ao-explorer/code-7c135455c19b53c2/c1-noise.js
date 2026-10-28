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
    const verdict = {QUALIFIED_BELOW_C1_TRIGGER: 'below the threshold', QUALIFIED_MATERIAL_BENEFIT: 'meets the threshold', INCONCLUSIVE_NUMERICS: 'numerically inconclusive'}[summary.status];
    node('readout').textContent = `Predicted difference: ${d.rms_nm.toFixed(4)} nm, a ${(100 * d.relative_variance_reduction).toFixed(2)} % reduction in this noise variance. Thresholds for a new experiment: ${rule.trigger_rms_nm.toFixed(1)} nm and ${(100 * rule.trigger_relative_variance).toFixed(0)} %. Result: ${verdict}. Bars start at zero.`;
  }
  function details() {
    const b = summary.dampings.baseline, c = summary.dampings.comparator, q = summary.comparator_qualification, id = summary.identities, cfg = summary.configuration;
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
    node('conditions').textContent = `Model conditions: ${cfg.profile}, seed ${cfg.root_seed}, realization ${cfg.realization}, detector sampling ${cfg.detector_sampling}; ${cfg.detected_e_per_full_subaperture_frame.toExponential(0)} detected electrons per full subaperture per frame; stationary linear loop with gain ${cfg.loop_model.gain}, latency ${cfg.loop_model.latency_frames} frames and leak ${cfg.loop_model.leak}, temporally white modal noise; detector covariance at a flat wavefront with independent lenslets. Outside this calculation: ${summary.not_established.join('; ')}.`;
    node('qualification').textContent = `I selected the largest damping on the grid that kept tip, tilt and defocus gains within [0.99, 1.01] (eligible settings: ${summary.comparator_selection.admissible.join(', ')}; propagated: ${summary.comparator_selection.propagated.join(' and ')}). Its solver passed the pupil-space checks (${q.criterion_A.pass}/${q.criterion_A.of} and ${q.criterion_B.pass}/${q.criterion_B.of}; inputs: ${q.inputs.probe} probes, ${q.inputs.screen} screen, ${q.inputs.noise} unit-noise vectors); the original command-space check fails ${q.original_command_space_failures} of 42, reported separately. Numerical consistency indicator ${summary.numerical_consistency_indicator.value.toExponential(1)}: ${summary.numerical_consistency_indicator.meaning}.`;
    node('identities').textContent = `Identities (SHA-256): decision record ${id.decision_record_sha256}; damping selection ${id.selection_record_sha256}; comparator record ${id.comparator_record_sha256}; execution report ${id.execution_report_sha256}; calculation adapter ${id.adapter_sha256}; frozen producer commit ${id.frozen_producer_commit}; configuration ${cfg.config_hash}. ${id.note}.`;
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
