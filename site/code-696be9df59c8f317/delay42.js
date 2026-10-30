// The controller-delay comparison (bundle delay42): nine saved 500-frame
// records, delays of 1, 2 and 3 frames in realizations r0-r2.  The per-record
// means, per-delay summaries and paired intervals are recomputed here from the
// recorded values and must agree with the bundle before anything is drawn.
import { fetchVerifiedImage, require } from './integrity.js';
import { lineChart, redrawWhenResized } from './charts.js';
import { addDownloads, agrees, finitePositive, frameInspector, loadStudy, seconds, series, signed, tableRows, windowMean } from './studies42.js';

const SCHEMAS = { entry: 'ao-explorer.delay42-entry.v1', manifest: 'ao-explorer.delay42-manifest.v1' };
const COLOURS = { 1: '#4d7a2a', 2: '#1f5f73', 3: '#a3324e' };
const DELAYS = [1, 2, 3], REALIZATIONS = [0, 1, 2], WINDOW = [100, 500];
const T_0975_DF2 = 0.95 * Math.sqrt(2 / (1 - 0.95 * 0.95));  // analytic Student-t quantile, two degrees of freedom
const SHAPES = ['circle', 'square', 'triangle'];

export function initDelay42(entry, entryUrl) {
  const root = document.getElementById('delay42');
  if (!root) return;
  const node = (name) => document.getElementById(`delay42-${name}`);
  let ready, bundle, data, records, realization = 0, range = 'post', frame = 344, extents;

  const record = (delay, r) => records.get(`${delay}:${r}`);

  function paired(values) {
    const mean = values.reduce((s, v) => s + v, 0) / 3;
    const sd = Math.sqrt(values.reduce((s, v) => s + (v - mean) ** 2, 0) / 2);
    const half = T_0975_DF2 * sd / Math.sqrt(3);
    return { mean, sd, low: mean - half, high: mean + half };
  }

  function validate(d) {
    require(d?.schema === 'ao-explorer.delay42-data.v1', 'unsupported controller-delay data');
    require(d.frames === 500 && d.frame_rate_hz === 500 && d.window?.frames?.[0] === 100 && d.window.frames[1] === 500 && d.window.samples === 400, 'the delay data do not describe 500 frames at 500 Hz with window [100,500)');
    require(JSON.stringify(d.delays) === '[1,2,3]' && JSON.stringify(d.realizations) === '[0,1,2]' && d.production_delay === 2, 'unexpected delays or realizations');
    require(Array.isArray(d.records) && d.records.length === 9, 'the delay data do not hold nine records');
    const map = new Map();
    for (const r of d.records) {
      require(DELAYS.includes(r.delay_frames) && REALIZATIONS.includes(r.realization), `unexpected record ${r.run_key}`);
      const key = `${r.delay_frames}:${r.realization}`;
      require(!map.has(key), `two records for delay ${r.delay_frames}, r${r.realization}`);
      require(r.source === (r.delay_frames === 2 ? 'reused baseline' : 'new'), `${r.run_key} has an unexpected source`);
      require(r.attempt === (r.delay_frames === 3 && r.realization === 2 ? 2 : 1), `${r.run_key} is not the accepted attempt`);
      series(r.pre_update_residual_rms_nm, 500, `${r.run_key} residual`, { positive: true });
      series(r.valid_measurement_fraction, 500, `${r.run_key} valid fraction`, { fraction: true });
      require(r.summary?.samples === 400 && agrees(windowMean(r.pre_update_residual_rms_nm, WINDOW), r.summary.mean_pre_update_rms_nm), `${r.run_key} window mean does not match its recorded frames`);
      require(r.summary.frames_valid_below_0_995 === r.valid_measurement_fraction.slice(...WINDOW).filter((v) => v < 0.995).length, `${r.run_key} validity count does not match its recorded frames`);
      for (const m of ['peak_strehl', 'fourier_ee50_lambda_over_d', 'production_ee50_lambda_over_d', 'rms_of_frame_pre_update_rms_nm']) finitePositive(r.summary[m], `${r.run_key} ${m}`);
      map.set(key, r);
    }
    for (const r of REALIZATIONS) series(d.open_loop_rms_nm?.[String(r)], 500, `open-loop RMS r${r}`, { positive: true });
    for (const metric of ['mean_pre_update_rms_nm', 'peak_strehl', 'fourier_ee50_lambda_over_d']) {
      for (const delay of DELAYS) {
        const values = REALIZATIONS.map((r) => map.get(`${delay}:${r}`).summary[metric]);
        const level = d.levels?.[metric]?.[String(delay)];
        require(level && values.every((v, i) => v === level.by_realization[i]) && agrees(paired(values).mean, level.mean), `${metric} delay ${delay} does not match its records`);
      }
      for (const [comparison, other] of [['1_minus_2', 1], ['3_minus_2', 3]]) {
        const differences = REALIZATIONS.map((r) => map.get(`${other}:${r}`).summary[metric] - map.get(`2:${r}`).summary[metric]);
        const recomputed = paired(differences), recorded = d.paired?.[metric]?.[comparison];
        require(recorded && differences.every((v, i) => agrees(v, recorded.by_realization[i])) && agrees(recomputed.mean, recorded.mean)
          && agrees(recomputed.low, recorded.ci95[0]) && agrees(recomputed.high, recorded.ci95[1]) && agrees(T_0975_DF2, recorded.t_0975_df2, 1e-12),
          `paired ${metric} ${comparison} does not match its records`);
      }
    }
    const x = d.excursion_r2, r3 = map.get('3:2');
    require(x && x.attempt === 2 && x.first_rise_frames[0] === 338 && x.first_rise_frames[1] === 344 && x.second_rise_frames[0] === 446 && x.second_rise_frames[1] === 447, 'the r2 description names unexpected frames');
    require(x.first_rise_nm[0] === r3.pre_update_residual_rms_nm[338] && x.first_rise_nm[1] === r3.pre_update_residual_rms_nm[344] && x.frame_339_nm === r3.pre_update_residual_rms_nm[339]
      && x.second_rise_nm[0] === r3.pre_update_residual_rms_nm[446] && x.second_rise_nm[1] === r3.pre_update_residual_rms_nm[447]
      && x.second_rise_valid_fraction[0] === r3.valid_measurement_fraction[446] && x.second_rise_valid_fraction[1] === r3.valid_measurement_fraction[447]
      && agrees(windowMean(r3.valid_measurement_fraction, [345, 500]), x.valid_mean_frames_345_500) && agrees(windowMean(r3.valid_measurement_fraction, [100, 300]), x.valid_mean_frames_100_300)
      && x.frames_valid_below_0_995_in_window === r3.summary.frames_valid_below_0_995, 'the r2 description does not match the delay-3 record');
    const s = d.strehl_asymmetry, st = d.levels.peak_strehl;
    require(agrees(s.loss_2_to_3, st['2'].mean - st['3'].mean) && agrees(s.gain_2_to_1, st['1'].mean - st['2'].mean) && agrees(s.ratio, s.loss_2_to_3 / s.gain_2_to_1), 'the Strehl asymmetry is inconsistent');
    return map;
  }

  function computeExtents() {
    const out = {};
    for (const [name, first] of [['post', 100], ['full', 0]]) {
      const residual = [], valid = [];
      for (const r of records.values()) { residual.push(...r.pre_update_residual_rms_nm.slice(first)); valid.push(...r.valid_measurement_fraction.slice(first)); }
      const span = (lo, hi, pad) => [lo - pad * (hi - lo), hi + 3 * pad * (hi - lo)];  // headroom above for marker labels
      out[name] = { residual: span(Math.min(...residual), Math.max(...residual), 0.05), valid: span(Math.min(...valid, 0.995), 1, 0.05) };
    }
    return out;
  }

  const shown = () => (range === 'post' ? 100 : 0);

  function draw() {
    const rate = data.frame_rate_hz, first = shown();
    const pts = (values) => values.slice(first).map((v, i) => [(first + i) / rate, v]);
    const shade = range === 'full' ? [[0, 100 / rate, 'startup (excluded)']] : [];
    const marks = [];
    if (realization === 2) {
      shade.push([338 / rate, 345 / rate, 'post hoc: 338→344', 'rgba(163, 50, 78, 0.12)']);
      marks.push({ x: 447 / rate, label: 'post hoc: 446→447', color: '#a3324e', row: 1 });
    }
    const common = { x: { label: 'Simulated time', unit: 's', range: [first / rate, 499 / rate] }, shadeX: shade, verticalLines: marks, cursorX: frame / rate, cursorLabel: `frame ${frame}` };
    node('chart-rms').studiesMap = lineChart(node('chart-rms'), {
      ...common, title: `Pre-update residual RMS, realization r${realization}, delays 1, 2 and 3 frames`, height: 240,
      y: { label: 'Residual RMS', unit: 'nm', range: extents[range].residual },
      series: DELAYS.map((delay) => ({ label: `Delay ${delay}${delay === 2 ? ' (replay setting)' : ''}`, color: COLOURS[delay], points: pts(record(delay, realization).pre_update_residual_rms_nm) })),
    });
    node('chart-valid').studiesMap = lineChart(node('chart-valid'), {
      ...common, cursorLabel: null, verticalLines: marks.map((m) => ({ ...m, label: '' })), title: `Valid-measurement fraction, realization r${realization}`, height: 170,
      y: { label: 'Valid fraction', range: extents[range].valid }, referenceLines: [{ y: 0.995 }],
      series: DELAYS.map((delay) => ({ label: `Delay ${delay}`, color: COLOURS[delay], points: pts(record(delay, realization).valid_measurement_fraction) })),
    });
  }

  function describe(k) {
    return [`Frame ${k} · t = ${seconds(k, data.frame_rate_hz)} · r${realization}${k < 100 ? ' · startup' : ''}`,
      ...DELAYS.map((delay) => { const r = record(delay, realization); return `Delay ${delay}: ${r.pre_update_residual_rms_nm[k].toFixed(1)} nm · valid ${r.valid_measurement_fraction[k].toFixed(4)}`; })];
  }

  function setFrame(k, announce) {
    frame = k;
    node('frame').value = String(k);
    node('frame').setAttribute('aria-valuetext', `frame ${k}, ${seconds(k, data.frame_rate_hz)}`);
    node('readout').textContent = describe(k).join(' · ');
    if (announce) node('live').textContent = node('readout').textContent;
    draw();
  }

  function realizationText() {
    const means = DELAYS.map((delay) => record(delay, realization).summary.mean_pre_update_rms_nm);
    node('realization-summary').textContent = `r${realization}, frames 100–499: mean pre-update residual ${means.map((v, i) => `${v.toFixed(1)} nm at delay ${i + 1}`).join(', ')}; delay 3 minus delay 2 is ${signed(means[2] - means[1], 1)} nm in this realization.`;
    node('show-r2').hidden = realization === 2;
  }

  const svg = (tag, attrs = {}, text) => {
    const e = document.createElementNS('http://www.w3.org/2000/svg', tag);
    for (const [k, v] of Object.entries(attrs)) e.setAttribute(k, v);
    if (text != null) e.textContent = text;
    return e;
  };

  function marker(shape, x, y, colour) {
    if (shape === 'circle') return svg('circle', { cx: x, cy: y, r: 5, fill: colour });
    if (shape === 'square') return svg('rect', { x: x - 4.5, y: y - 4.5, width: 9, height: 9, fill: colour });
    return svg('path', { d: `M ${x} ${y - 6} L ${x + 5.5} ${y + 4} L ${x - 5.5} ${y + 4} Z`, fill: colour });
  }

  function dots() {
    const p = data.paired.mean_pre_update_rms_nm;
    const rows = [{ key: '1_minus_2', label: 'Delay 1 − delay 2', colour: COLOURS[1] }, { key: '3_minus_2', label: 'Delay 3 − delay 2', colour: COLOURS[3] }];
    const W = Math.round(Math.min(760, Math.max(300, node('dots').clientWidth || 720))), narrow = W < 520;
    const L = narrow ? 24 : 140, R = 28, top = narrow ? 30 : 16, rowH = narrow ? 82 : 64;
    const all = rows.flatMap((row) => [...p[row.key].by_realization, ...p[row.key].ci95]);
    const lo = Math.min(0, ...all), hi = Math.max(0, ...all), step = 10;
    const x0 = Math.floor(lo / step) * step - (lo % step === 0 ? step / 2 : 0), x1 = Math.ceil(hi / step) * step;
    const sx = (v) => L + (W - L - R) * (v - x0) / (x1 - x0);
    const H = top + rows.length * rowH + 40;
    const chart = svg('svg', { viewBox: `0 0 ${W} ${H}`, width: W, height: H, role: 'img',
      'aria-label': rows.map((row) => { const q = p[row.key]; return `${row.label}: r0 ${signed(q.by_realization[0], 2)}, r1 ${signed(q.by_realization[1], 2)}, r2 ${signed(q.by_realization[2], 2)} nm; mean ${signed(q.mean, 2)} nm, exploratory 95% interval ${signed(q.ci95[0], 2)} to ${signed(q.ci95[1], 2)} nm`; }).join('. ') + '. The dashed line marks zero.' });
    const bottom = top + rows.length * rowH;
    for (let t = Math.ceil(x0 / step) * step; t <= x1; t += step) {
      chart.append(svg('line', { x1: sx(t), x2: sx(t), y1: top - 6, y2: bottom, stroke: '#e6e2da' }));
      chart.append(svg('text', { x: sx(t), y: bottom + 15, 'text-anchor': 'middle', class: 'd42-tick' }, t === 0 ? '0' : signed(t, 0)));
    }
    chart.append(svg('line', { x1: sx(0), x2: sx(0), y1: top - 10, y2: bottom, stroke: '#23262a', 'stroke-width': 1.5, 'stroke-dasharray': '5 4' }));
    chart.append(svg('text', { x: (L + W - R) / 2, y: bottom + 32, 'text-anchor': 'middle', class: 'd42-tick' }, narrow ? 'Paired change, nm' : 'Paired change in mean residual RMS, nm (frames 100–499)'));
    rows.forEach((row, i) => {
      const q = p[row.key], y = top + i * rowH + (narrow ? 40 : 32);
      if (narrow) chart.append(svg('text', { x: L, y: y - 26, class: 'd42-label' }, row.label));
      else chart.append(svg('text', { x: L - 10, y: y + 4, 'text-anchor': 'end', class: 'd42-label' }, row.label));
      chart.append(svg('line', { x1: sx(q.ci95[0]), x2: sx(q.ci95[1]), y1: y, y2: y, stroke: row.colour, 'stroke-width': 6, 'stroke-opacity': 0.3, 'stroke-linecap': 'round', 'data-key': `${row.key}-interval` }));
      chart.append(svg('line', { x1: sx(q.mean), x2: sx(q.mean), y1: y - 22, y2: y + 22, stroke: row.colour, 'stroke-width': 2.5, 'data-key': `${row.key}-mean` }));
      // Realizations are dodged vertically (r0 above, r2 below) so that nearly equal values stay distinguishable;
      // labels of markers closer than 24 px share one column to the right of that cluster.
      const xs = q.by_realization.map(sx);
      q.by_realization.forEach((v, r) => {
        const yr = y + (r - 1) * 14;
        const labelX = Math.max(...xs.filter((x) => Math.abs(x - xs[r]) < 24)) + 9;
        chart.append(marker(SHAPES[r], xs[r], yr, row.colour));
        chart.append(svg('text', { x: labelX, y: yr + 4, class: 'd42-point' }, `r${r}`));
      });
    });
    node('dots').replaceChildren(chart);
  }

  function tables() {
    const p = data.paired, lv = data.levels;
    const interval = (q, d) => `${signed(q.mean, d)} [${signed(q.ci95[0], d)}, ${signed(q.ci95[1], d)}]`;
    const each = (q, d) => q.by_realization.map((v) => signed(v, d)).join(' / ');
    tableRows(node('paired-body'), [
      ['Mean residual RMS (nm)', interval(p.mean_pre_update_rms_nm['1_minus_2'], 2), each(p.mean_pre_update_rms_nm['1_minus_2'], 2), interval(p.mean_pre_update_rms_nm['3_minus_2'], 2), each(p.mean_pre_update_rms_nm['3_minus_2'], 2)],
      ['Peak Strehl of the mean image', interval(p.peak_strehl['1_minus_2'], 4), each(p.peak_strehl['1_minus_2'], 4), interval(p.peak_strehl['3_minus_2'], 4), each(p.peak_strehl['3_minus_2'], 4)],
      ['Fourier-reference EE50 (λ/D)', interval(p.fourier_ee50_lambda_over_d['1_minus_2'], 3), each(p.fourier_ee50_lambda_over_d['1_minus_2'], 3), interval(p.fourier_ee50_lambda_over_d['3_minus_2'], 3), each(p.fourier_ee50_lambda_over_d['3_minus_2'], 3)],
    ]);
    const level = (metric, delay, d) => `${lv[metric][delay].mean.toFixed(d)}`;
    const per = (metric, delay, d) => lv[metric][delay].by_realization.map((v) => v.toFixed(d)).join(' / ');
    tableRows(node('image-body'), DELAYS.map((delay) => [
      `${delay} frame${delay > 1 ? 's' : ''}${delay === 2 ? ' (replay setting; reused records)' : ''}`,
      `${level('mean_pre_update_rms_nm', delay, 2)} nm`, per('mean_pre_update_rms_nm', delay, 1),
      level('peak_strehl', delay, 4), per('peak_strehl', delay, 4),
      level('fourier_ee50_lambda_over_d', delay, 3), per('fourier_ee50_lambda_over_d', delay, 3)]));
    tableRows(node('exact-body'), DELAYS.map((delay) => [`Delay ${delay}`, lv.mean_pre_update_rms_nm[delay].mean.toFixed(6), lv.peak_strehl[delay].mean.toFixed(6), lv.fourier_ee50_lambda_over_d[delay].mean.toFixed(6), lv.production_ee50_lambda_over_d[delay].mean.toFixed(6)]));
    tableRows(node('records-body'), data.records.map((r) => [r.run_key, `${r.delay_frames}`, `r${r.realization}`,
      r.source === 'new' ? (r.attempt === 2 ? 'new · accepted second attempt' : 'new') : 'reused photon-budget baseline',
      r.summary.mean_pre_update_rms_nm.toFixed(6), r.summary.rms_of_frame_pre_update_rms_nm.toFixed(6), `${r.summary.frames_valid_below_0_995}`]));
    const s = data.strehl_asymmetry;
    node('asymmetry').textContent = `For the peak Strehl of the mean image, the average loss from delay 2 to delay 3 (${s.loss_2_to_3.toFixed(4)}) is ${s.ratio.toFixed(2)} times the average gain from delay 2 to delay 1 (${s.gain_2_to_1.toFixed(4)}), at gain 0.3 in these three realizations. This ratio describes this metric and this sample; it is not a general cost multiplier for latency.`;
  }

  function details() {
    const x = data.excursion_r2;
    node('r2-text').textContent = `Around 0.68 s every delay shows a disturbance in r2. At delay 3, the residual rises from ${x.first_rise_nm[0].toFixed(1)} nm at frame 338 (${x.frame_339_nm.toFixed(1)} nm at frame 339) to ${x.first_rise_nm[1].toFixed(1)} nm at frame 344, coinciding with a larger dip of the valid-measurement fraction (minimum ${x.valid_minimum.value.toFixed(3)} at frame ${x.valid_minimum.frame}). Validity then recovers only partly: its mean over frames 345–499 is ${x.valid_mean_frames_345_500.toFixed(4)}, against ${x.valid_mean_frames_100_300.toFixed(4)} over frames 100–299, and ${x.frames_valid_below_0_995_in_window} of the 400 main-window frames lie below 0.995. A second rise follows at frames 446 → 447, from ${x.second_rise_nm[0].toFixed(1)} to ${x.second_rise_nm[1].toFixed(1)} nm, without a simultaneous validity drop (${x.second_rise_valid_fraction[0].toFixed(5)} → ${x.second_rise_valid_fraction[1].toFixed(5)}).`;
    node('identity').textContent = `Display bundle ${bundle.id} (identity of the generated files, not of the scientific source). Source identities, input SHA-256 values, attempt selection and the exporter version are in provenance.json.`;
    addDownloads(node('downloads'), bundle, [['Per-frame values (CSV)', 'frames.csv'], ['Data (JSON)', 'data.json'], ['Provenance (JSON)', 'provenance.json'], ['About this bundle', 'README.md'], ['Exporter (Python)', 'exporter.py']]);
    node('psf-details').addEventListener('toggle', async () => {
      if (!node('psf-details').open || node('psf').dataset.loaded) return;
      node('psf').dataset.loaded = 'loading';
      try {
        const { buffer } = await fetchVerifiedImage(bundle.member('psf_panels.png'), bundle.base, { expectType: 'image/png' });
        node('psf').src = URL.createObjectURL(new Blob([buffer], { type: 'image/png' }));
        node('psf').hidden = false;
        node('psf-status').textContent = '';
      } catch (error) { node('psf-status').textContent = `The figure could not be verified: ${error.message}`; node('psf').dataset.loaded = ''; }
    });
  }

  function enable() {
    for (const input of root.querySelectorAll('input[name="delay42-realization"], input[name="delay42-range"]')) {
      input.disabled = false;
      input.addEventListener('change', () => {
        if (!input.checked) return;
        if (input.name === 'delay42-realization') { realization = Number(input.value); realizationText(); }
        else { range = input.value; node('frame').min = String(shown()); if (frame < shown()) frame = shown(); }
        setFrame(frame, false);
      });
    }
    node('show-r2').disabled = false;
    node('show-r2').addEventListener('click', () => {
      const r2 = root.querySelector('input[name="delay42-realization"][value="2"]');
      r2.checked = true; r2.dispatchEvent(new Event('change')); node('chart-rms').scrollIntoView({ block: 'center' });
    });
    node('frame').disabled = false;
    frameInspector({ canvases: [node('chart-rms'), node('chart-valid')], slider: node('frame'), rate: data.frame_rate_hz,
      firstFrame: shown, lastFrame: () => 499, describe, onFrame: setFrame });
    for (const canvas of [node('chart-rms'), node('chart-valid')]) redrawWhenResized(canvas, draw);
    if ('ResizeObserver' in window) { let width = 0; new ResizeObserver(() => { const w = node('dots').clientWidth; if (Math.abs(w - width) > 8) { width = w; dots(); } }).observe(node('dots')); }
  }

  async function load() {
    if (ready) return ready;
    ready = (async () => {
      node('status').textContent = 'Loading and checking the controller-delay records…';
      bundle = await loadStudy(entry, 'delay42', SCHEMAS, entryUrl);
      if (!bundle) { node('status').textContent = 'The controller-delay comparison is not part of this build; the replay above is unaffected.'; return; }
      records = validate(bundle.data);
      data = bundle.data;
      extents = computeExtents();
      const lv = data.levels, p = data.paired.mean_pre_update_rms_nm;
      node('lead').textContent = `Averaged over frames 100–499 and the three realizations, the residual is ${[1, 2, 3].map((d) => lv.mean_pre_update_rms_nm[d].mean.toFixed(1)).join(', ')} nm for delays of 1, 2 and 3 frames, and the peak Strehl of the mean image at 2.2 µm is ${[1, 2, 3].map((d) => lv.peak_strehl[d].mean.toFixed(3)).join(', ')}.`;
      node('paired-text').textContent = `Against delay 2, one frame less lowers the residual in every realization (mean ${signed(p['1_minus_2'].mean, 1)} nm; exploratory 95% interval ${signed(p['1_minus_2'].ci95[0], 1)} to ${signed(p['1_minus_2'].ci95[1], 1)} nm). One frame more raises it in every realization, by ${p['3_minus_2'].by_realization.map((v) => signed(v, 1)).join(', ')} nm for r0, r1 and r2; the mean is ${signed(p['3_minus_2'].mean, 1)} nm, but with three realizations and the larger r2 value the exploratory interval, ${signed(p['3_minus_2'].ci95[0], 1)} to ${signed(p['3_minus_2'].ci95[1], 1)} nm, includes zero.`;
      tables(); details(); dots(); realizationText(); enable(); setFrame(frame, false);
      node('status').textContent = '';
    })().catch((error) => {
      node('error').hidden = false;
      node('error').textContent = `Controller-delay comparison unavailable: ${error.message}. Nothing from it is shown; the replay above is unaffected. Reload to retry.`;
      node('status').textContent = 'The controller-delay comparison could not be verified.';
    });
    return ready;
  }

  if ('IntersectionObserver' in window) {
    const observer = new IntersectionObserver((items) => { if (items.some((i) => i.isIntersecting)) { observer.disconnect(); load(); } }, { rootMargin: '200px' });
    observer.observe(root);
  } else load();
  if (location.hash.startsWith('#delay42')) { if (location.hash === '#delay42-methods') node('methods').open = true; load(); }
}
