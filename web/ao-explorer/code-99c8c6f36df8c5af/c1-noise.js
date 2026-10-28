// The separate static C1 noise assessment: one small verified summary drawn as a zero-based chart.
// Its controls change only this chart; they never touch the replay above.
import { fetchVerified, fetchVerifiedJson, require } from './integrity.js';

export function initC1Noise(entry, entryUrl) {
  const root = document.getElementById('c1-noise');
  if (!root) return;
  const node = name => document.getElementById(`c1-${name}`);
  const radios = [...root.querySelectorAll('input[name="c1-highlight"]')];
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
  let shown = 'both';
  function draw(highlight) {
    shown = highlight;
    const b = summary.dampings.baseline, c = summary.dampings.comparator, d = summary.difference, rule = summary.decision_rule;
    // Drawn at the container's own width so that text keeps its size on a phone.
    const W = Math.round(Math.min(760, Math.max(300, node('chart').clientWidth || 720))), narrow = W < 520;
    const L = narrow ? 104 : 210, R = narrow ? 76 : 120, vmax = 1.2, sx = v => L + (W - L - R) * v / vmax;
    const rows = [
      {group: narrow ? 'Detector-noise part (RMS)' : 'Predicted detector-noise part (RMS)', label: narrow ? 'α 0.001' : 'Production α 0.001', value: b.rms_nm, key: 'baseline', colour: '#5b7486'},
      {group: null, label: narrow ? 'α 0.0025' : 'Alternative α 0.0025', value: c.rms_nm, key: 'comparator', colour: '#1f5f73'},
      {group: narrow ? 'Against the C1 trigger' : 'Difference against the C1 trigger', label: narrow ? 'Difference' : 'Difference of the two', value: d.rms_nm, key: 'difference', colour: '#1f5f73'},
      {group: null, label: narrow ? 'Trigger' : 'Trigger for a new experiment', value: rule.trigger_rms_nm, key: 'trigger', colour: '#b3541e'},
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
      const dim = highlight !== 'both' && (row.key === 'baseline' || row.key === 'comparator') && row.key !== highlight;
      chart.append(svg('text', {x: L - 8, y: top + 16, 'text-anchor': 'end', class: 'c1-label'}, row.label));
      chart.append(svg('rect', {x: L, y: top, width: Math.max(sx(row.value) - L, 1.5), height: 22, fill: row.colour, opacity: dim ? .3 : 1, 'data-key': row.key}));
      chart.append(svg('text', {x: Math.max(sx(row.value), L + 1.5) + 6, y: top + 16, class: 'c1-value'}, `${row.value.toFixed(row.key === 'trigger' ? 1 : 4)} nm`));
    }
    node('chart').replaceChildren(chart);
    const pick = highlight === 'comparator' ? c : b;
    const g = pick.one_shot_gains;
    const verdict = {QUALIFIED_BELOW_C1_TRIGGER: 'below the trigger (status QUALIFIED_BELOW_C1_TRIGGER)', QUALIFIED_MATERIAL_BENEFIT: 'a material benefit (status QUALIFIED_MATERIAL_BENEFIT)', INCONCLUSIVE_NUMERICS: 'numerically inconclusive (status INCONCLUSIVE_NUMERICS)'}[summary.status];
    node('readout').textContent = highlight === 'both'
      ? `Bars start at zero. Difference ${d.rms_nm.toFixed(4)} nm (${(100 * d.relative_variance_reduction).toFixed(2)} % of the variance) against triggers of ${rule.trigger_rms_nm.toFixed(1)} nm and ${(100 * rule.trigger_relative_variance).toFixed(0)} %: ${verdict}.`
      : `${highlight === 'comparator' ? 'Alternative α 0.0025' : 'Production α 0.001'}: ${pick.rms_nm.toFixed(4)} nm RMS (${pick.variance_nm2.toFixed(4)} nm²); tip, tilt and defocus one-shot gains ${g.tip.toFixed(4)}, ${g.tilt.toFixed(4)}, ${g.defocus.toFixed(4)}.`;
  }
  function details() {
    const b = summary.dampings.baseline, c = summary.dampings.comparator, q = summary.comparator_qualification, id = summary.identities, cfg = summary.configuration;
    const rows = [
      ['Stationary detector-noise part, RMS', `${b.rms_nm.toFixed(4)} nm`, `${c.rms_nm.toFixed(4)} nm`],
      ['Stationary detector-noise part, variance', `${b.variance_nm2.toFixed(4)} nm²`, `${c.variance_nm2.toFixed(4)} nm²`],
      ['Single-frame reconstruction noise, RMS', `${b.instantaneous_rms_nm.toFixed(4)} nm`, `${c.instantaneous_rms_nm.toFixed(4)} nm`],
      ['Tip / tilt / defocus one-shot gain', ['tip', 'tilt', 'defocus'].map(k => b.one_shot_gains[k].toFixed(5)).join(' / '), ['tip', 'tilt', 'defocus'].map(k => c.one_shot_gains[k].toFixed(5)).join(' / ')],
      ['Seven flagged modes (variance within)', `${b.seven_mode_within_nm2.toFixed(4)} nm²`, `${c.seven_mode_within_nm2.toFixed(4)} nm²`],
    ];
    node('table-body').replaceChildren(...rows.map(values => {
      const tr = document.createElement('tr');
      values.forEach((text, i) => { const cell = document.createElement(i ? 'td' : 'th'); if (!i) cell.scope = 'row'; cell.textContent = text; tr.append(cell); });
      return tr;
    }));
    node('conditions').textContent = `Model conditions: ${cfg.profile}, seed ${cfg.root_seed}, realization ${cfg.realization}, detector sampling ${cfg.detector_sampling}; ${cfg.detected_e_per_full_subaperture_frame.toExponential(0)} detected electrons per full subaperture per frame; stationary linear loop with gain ${cfg.loop_model.gain}, latency ${cfg.loop_model.latency_frames} frames and leak ${cfg.loop_model.leak}, temporally white modal noise; detector covariance at a flat wavefront with independent lenslets. Not established: ${summary.not_established.join('; ')}.`;
    node('qualification').textContent = `The alternative is the largest grid damping keeping tip, tilt and defocus gains within [0.99, 1.01] (admissible: ${summary.comparator_selection.admissible.join(', ')}; propagated: ${summary.comparator_selection.propagated.join(' and ')}). Its solver passed the pupil-space checks (${q.criterion_A.pass}/${q.criterion_A.of} and ${q.criterion_B.pass}/${q.criterion_B.of}; inputs: ${q.inputs.probe} probes, ${q.inputs.screen} screen, ${q.inputs.noise} unit-noise vectors); the original command-space check fails ${q.original_command_space_failures} of 42, reported separately. Numerical consistency indicator ${summary.numerical_consistency_indicator.value.toExponential(1)}: ${summary.numerical_consistency_indicator.meaning}.`;
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
      node('status').textContent = 'Loading the C1 summary and checking its file identity…';
      require(e.schema === 'ao-explorer.c1-noise-entry.v1', 'No supported C1 summary entry');
      const m = await fetchVerifiedJson({href: e.manifest, bytes: e.manifest_bytes, sha256: e.manifest_sha256, media_type: 'application/json'}, entryUrl);
      require(m.value.schema === 'ao-explorer.c1-noise-manifest.v1' && m.value.id === e.id, 'C1 manifest identity mismatch');
      files = m.value.files; base = m.url;
      summary = (await fetchVerifiedJson(file('summary.json'), base)).value;
      validate(summary);
      node('rms-b').textContent = `${summary.dampings.baseline.rms_nm.toFixed(4)} nm`;
      node('rms-c').textContent = `${summary.dampings.comparator.rms_nm.toFixed(4)} nm`;
      draw('both'); details();
      radios.forEach(r => { r.disabled = false; });
      node('status').textContent = 'C1 summary loaded · file identity checked · existing records only';
    })().catch(error => {
      node('error').hidden = false;
      node('error').textContent = `C1 summary unavailable: ${error.message}. The replay above is unaffected; reload to retry.`;
      node('status').textContent = 'The C1 summary could not be verified.';
      radios.forEach(r => { r.disabled = true; });
    });
    return ready;
  }
  radios.forEach(r => r.addEventListener('change', () => { if (summary) draw(r.value); }));
  if ('ResizeObserver' in window) { let width = 0; new ResizeObserver(() => { const w = node('chart').clientWidth; if (summary && Math.abs(w - width) > 8) { width = w; draw(shown); } }).observe(node('chart')); }
  if ('IntersectionObserver' in window) {
    const observer = new IntersectionObserver(items => { if (items.some(i => i.isIntersecting)) { observer.disconnect(); load(); } }, {rootMargin: '200px'});
    observer.observe(root);
  } else load();
  if (location.hash === '#c1-noise' || location.hash === '#c1-provenance') { if (location.hash === '#c1-provenance') node('provenance').open = true; load(); }
}
