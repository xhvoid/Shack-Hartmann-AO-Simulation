// The 2 s guide-flux comparison (bundle flux42): two saved 1000-frame
// trajectories through one atmospheric realization, 100000 versus 1000
// detected electrons per fully illuminated subaperture per frame. Residual
// means and validity counts are recomputed here; image metrics and last-50
// summaries are supplied values checked by the offline exporter.
import { require } from './integrity.js';
import { lineChart, redrawWhenResized } from './charts.js';
import { addDownloads, agrees, finitePositive, frameInspector, loadStudy, seconds, series, signed, tableRows, windowMean } from './studies42.js';

const SCHEMAS = { entry: 'ao-explorer.flux42-entry.v1', manifest: 'ao-explorer.flux42-manifest.v1' };
const COLOURS = { bright: '#1f5f73', faint: '#b3541e', difference: '#6b5aa6' };
const WINDOWS = { early: [100, 500], late: [500, 1000], full: [100, 1000] };
const WINDOW_TEXT = { early: '0.2–1.0 s · frames 100–499 · 400 samples', late: '1.0–2.0 s · frames 500–999 · 500 samples', full: '0.2–2.0 s · frames 100–999 · 900 samples' };
const FLUX = { bright: 100000, faint: 1000 };

export function initFlux42(entry, entryUrl) {
  const root = document.getElementById('flux42');
  if (!root) return;
  const node = (name) => document.getElementById(`flux42-${name}`);
  let ready, bundle, data, diff, range = 'post', windowKey = 'early', frame = 500;

  function validate(d) {
    require(d?.schema === 'ao-explorer.flux42-data.v1', 'unsupported flux-comparison data');
    require(d.frames === 1000 && d.frame_rate_hz === 500 && d.realization === 2 && d.boundary_frame === 500, 'the flux comparison does not describe 1000 frames of r2 at 500 Hz');
    require(d.startup_frames?.[0] === 0 && d.startup_frames?.[1] === 100, 'unexpected startup exclusion');
    for (const [key, [a, b]] of Object.entries(WINDOWS)) require(d.windows?.[key]?.frames?.[0] === a && d.windows[key].frames[1] === b && d.windows[key].samples === b - a, `window ${key} is not [${a},${b})`);
    for (const key of ['bright', 'faint']) {
      const run = d.runs?.[key];
      require(run && run.detected_e_per_full_subaperture_frame === FLUX[key], `the ${key} run does not record ${FLUX[key]} e⁻`);
      series(run.pre_update_residual_rms_nm, 1000, `${key} residual`, { positive: true });
      series(run.valid_measurement_fraction, 1000, `${key} valid fraction`, { fraction: true });
    }
    series(d.open_loop_rms_nm, 1000, 'open-loop RMS', { positive: true });
    const bright = d.runs.bright.pre_update_residual_rms_nm, faint = d.runs.faint.pre_update_residual_rms_nm;
    const difference = faint.map((v, k) => v - bright[k]);
    for (const [key, window] of Object.entries(WINDOWS)) {
      const s = d.summaries?.[key];
      require(s && s.samples === window[1] - window[0], `summary ${key} has the wrong sample count`);
      require(agrees(windowMean(bright, window), s.bright_mean_nm) && agrees(windowMean(faint, window), s.faint_mean_nm) && agrees(windowMean(difference, window), s.faint_minus_bright_mean_nm),
        `summary ${key} does not match the recorded frames`);
      for (const run of ['bright', 'faint']) {
        const count = d.runs[run].valid_measurement_fraction.slice(...window).filter((v) => v < 0.995).length;
        require(count === s[`${run}_frames_valid_below_0_995`], `validity count ${key} does not match the recorded frames`);
      }
    }
    const c = d.changes;
    require(agrees(c.bright_late_minus_early_nm, d.summaries.late.bright_mean_nm - d.summaries.early.bright_mean_nm)
      && agrees(c.faint_late_minus_early_nm, d.summaries.late.faint_mean_nm - d.summaries.early.faint_mean_nm)
      && agrees(c.difference_in_changes_nm, c.faint_late_minus_early_nm - c.bright_late_minus_early_nm), 'the window changes are inconsistent');
    require(d.images?.late === null, 'an image metric is claimed for frames 500–999 alone');
    for (const key of ['early', 'full']) {
      const img = d.images?.[key];
      require(img && img.frames[0] === WINDOWS[key][0] && img.frames[1] === WINDOWS[key][1], `image window ${key} is not [${WINDOWS[key]})`);
      for (const run of ['bright', 'faint']) for (const metric of ['peak_strehl', 'fourier_ee50_lambda_over_d', 'production_ee50_lambda_over_d']) finitePositive(img[run]?.[metric], `${run} ${metric} ${key}`);
    }
    return difference;
  }

  const shown = () => (range === 'post' ? 100 : 0);
  const points = (values) => values.slice(shown()).map((v, i) => [(shown() + i) / data.frame_rate_hz, v]);

  function draw() {
    const rate = data.frame_rate_hz;
    const [a, b] = WINDOWS[windowKey];
    const shade = [[a / rate, b / rate, null, 'rgba(31, 95, 115, 0.09)']];
    if (range === 'full') shade.unshift([0, 100 / rate, 'startup (excluded)']);
    const boundary = [{ x: 500 / rate, label: 'frame 500 · 1.0 s', color: '#5c6168', row: 1 }];
    const common = { x: { label: 'Simulated time', unit: 's', range: [shown() / rate, 999 / rate] }, shadeX: shade, verticalLines: boundary, cursorX: frame / rate, cursorLabel: `frame ${frame}` };
    node('chart-rms').studiesMap = lineChart(node('chart-rms'), {
      ...common, title: 'Pre-update residual RMS, bright and faint, realization r2', height: 240,
      y: { label: 'Residual RMS', unit: 'nm' },
      series: [
        { label: 'Bright · 100,000 e⁻', color: COLOURS.bright, points: points(data.runs.bright.pre_update_residual_rms_nm) },
        { label: 'Faint · 1,000 e⁻', color: COLOURS.faint, points: points(data.runs.faint.pre_update_residual_rms_nm) },
      ],
    });
    node('chart-diff').studiesMap = lineChart(node('chart-diff'), {
      ...common, cursorLabel: null, verticalLines: [{ ...boundary[0], label: '' }], title: 'Faint minus bright residual RMS, same frame', height: 190,
      y: { label: 'Faint − bright', unit: 'nm' }, referenceLines: [{ y: 0 }],
      series: [{ label: 'Faint − bright (positive: faint larger)', color: COLOURS.difference, points: points(diff) }],
    });
  }

  function describe(k) {
    const b = data.runs.bright, f = data.runs.faint;
    return [`Frame ${k} · t = ${seconds(k, data.frame_rate_hz)}${k < 100 ? ' · startup' : ''}`,
      `Bright: ${b.pre_update_residual_rms_nm[k].toFixed(1)} nm`, `Faint: ${f.pre_update_residual_rms_nm[k].toFixed(1)} nm`,
      `Faint − bright: ${signed(diff[k], 1)} nm`,
      `Valid fraction: ${b.valid_measurement_fraction[k].toFixed(4)} / ${f.valid_measurement_fraction[k].toFixed(4)}`];
  }

  function setFrame(k, announce) {
    frame = k;
    node('frame').value = String(k);
    node('frame').setAttribute('aria-valuetext', `frame ${k}, ${seconds(k, data.frame_rate_hz)}`);
    node('readout').textContent = describe(k).join(' · ');
    if (announce) node('live').textContent = node('readout').textContent;
    draw();
  }

  function summary() {
    const s = data.summaries[windowKey], img = data.images[windowKey];
    node('window-caption').textContent = `Summary window ${WINDOW_TEXT[windowKey]}. Means are arithmetic means of the per-frame values.`;
    const rows = [
      ['Mean pre-update residual RMS', `${s.bright_mean_nm.toFixed(2)} nm`, `${s.faint_mean_nm.toFixed(2)} nm`, `${signed(s.faint_minus_bright_mean_nm, 2)} nm`],
      ['Frames with valid fraction below 0.995', `${s.bright_frames_valid_below_0_995} of ${s.samples}`, `${s.faint_frames_valid_below_0_995} of ${s.samples}`, '—'],
    ];
    if (img) {
      rows.push(['Peak Strehl of the mean image (2.2 µm)', img.bright.peak_strehl.toFixed(4), img.faint.peak_strehl.toFixed(4), signed(img.faint.peak_strehl - img.bright.peak_strehl, 4)]);
      rows.push(['Fourier-reference EE50 (λ/D)', img.bright.fourier_ee50_lambda_over_d.toFixed(4), img.faint.fourier_ee50_lambda_over_d.toFixed(4), signed(img.faint.fourier_ee50_lambda_over_d - img.bright.fourier_ee50_lambda_over_d, 4)]);
    } else {
      rows.push(['Mean-image metrics', { text: 'Not recorded for 1.0–2.0 s alone: no image was averaged over this window, and whole-window values are not subtracted to make one.', colspan: 3, className: 'studies42-na' }]);
    }
    tableRows(node('table-body'), rows);
  }

  function details() {
    const s = data.summaries, c = data.changes, img = data.images;
    node('lead').textContent = `Over 0.2–1.0 s the faint run's residual averages ${s.early.faint_minus_bright_mean_nm.toFixed(1)} nm more than the bright run's; over 1.0–2.0 s the gap is ${s.late.faint_minus_bright_mean_nm.toFixed(1)} nm. From the first to the second window, the bright mean changes by ${signed(c.bright_late_minus_early_nm, 2)} nm and the faint mean by ${signed(c.faint_late_minus_early_nm, 1)} nm.`;
    node('changes').textContent = `Change of the window mean from 0.2–1.0 s to 1.0–2.0 s: bright ${signed(c.bright_late_minus_early_nm, 6)} nm, faint ${signed(c.faint_late_minus_early_nm, 6)} nm; difference in changes ${signed(c.difference_in_changes_nm, 6)} nm. Last-50-frame means (frames 450–499 → 950–999): bright ${data.last50.bright_nm[0].toFixed(2)} → ${data.last50.bright_nm[1].toFixed(2)} nm, faint ${data.last50.faint_nm[0].toFixed(2)} → ${data.last50.faint_nm[1].toFixed(2)} nm.`;
    tableRows(node('exact-body'), Object.keys(WINDOWS).map((key) => [WINDOW_TEXT[key], s[key].bright_mean_nm.toFixed(6), s[key].faint_mean_nm.toFixed(6), signed(s[key].faint_minus_bright_mean_nm, 6)]));
    tableRows(node('image-body'), ['early', 'full'].flatMap((key) => ['bright', 'faint'].map((run) => [
      `${run === 'bright' ? 'Bright' : 'Faint'} · frames ${img[key].frames[0]}–${img[key].frames[1] - 1}`,
      img[key][run].peak_strehl.toFixed(6), img[key][run].fourier_ee50_lambda_over_d.toFixed(6), img[key][run].production_ee50_lambda_over_d.toFixed(6)])));
    node('identity').textContent = `Display bundle ${bundle.id} (identity of the generated files, not of the scientific source). Source identities, input SHA-256 values and the exporter version are in provenance.json.`;
    addDownloads(node('downloads'), bundle, [['Per-frame values (CSV)', 'frames.csv'], ['Data (JSON)', 'data.json'], ['Provenance (JSON)', 'provenance.json'], ['About this bundle', 'README.md'], ['Exporter (Python)', 'exporter.py']]);
  }

  function enable() {
    for (const input of root.querySelectorAll('input[name="flux42-range"], input[name="flux42-window"]')) {
      input.disabled = false;
      input.addEventListener('change', () => {
        if (!input.checked) return;
        if (input.name === 'flux42-range') {
          range = input.value;
          node('frame').min = String(shown());
          if (frame < shown()) frame = shown();
          setFrame(frame, false);
        } else { windowKey = input.value; summary(); draw(); }
      });
    }
    node('frame').disabled = false;
    frameInspector({ canvases: [node('chart-rms'), node('chart-diff')], slider: node('frame'), rate: data.frame_rate_hz,
      firstFrame: shown, lastFrame: () => 999, describe, onFrame: setFrame });
    for (const canvas of [node('chart-rms'), node('chart-diff')]) redrawWhenResized(canvas, draw);
  }

  async function load() {
    if (ready) return ready;
    ready = (async () => {
      node('status').textContent = 'Loading and checking the flux comparison…';
      bundle = await loadStudy(entry, 'flux42', SCHEMAS, entryUrl);
      if (!bundle) { node('status').textContent = 'The flux comparison is not part of this build; the replay above is unaffected.'; return; }
      diff = validate(bundle.data);
      data = bundle.data;
      summary(); details(); enable(); setFrame(frame, false);
      node('status').textContent = '';
    })().catch((error) => {
      node('error').hidden = false;
      node('error').textContent = `Flux comparison unavailable: ${error.message}. Nothing from it is shown; the replay above is unaffected. Reload to retry.`;
      node('status').textContent = 'The flux comparison could not be verified.';
    });
    return ready;
  }

  if ('IntersectionObserver' in window) {
    const observer = new IntersectionObserver((items) => { if (items.some((i) => i.isIntersecting)) { observer.disconnect(); load(); } }, { rootMargin: '200px' });
    observer.observe(root);
  } else load();
  if (location.hash.startsWith('#flux42')) { if (location.hash === '#flux42-methods') node('methods').open = true; load(); }
}
