// Separate, immutable postprocessing evidence. These controls never alter either AO replay.
import { fetchVerified, fetchVerifiedJson, require } from './integrity.js';

export function initDmStroke(entry, entryUrl) {
  const root = document.getElementById('dm-stroke');
  if (!root) return;
  const node = name => document.getElementById(`stroke-${name}`);
  let ready, evidence, base;
  const file = name => {
    require(evidence?.files[name], `Stroke evidence member missing: ${name}`);
    return {href: name, ...evidence.files[name]};
  };
  async function loadStroke() {
    if (ready) return ready;
    ready = (async () => {
      node('status').textContent = 'Loading the saved saturation check…';
      const e = entry.dmStroke;
      require(e?.schema === 'ao-explorer.dm-stroke-entry.v1', 'No supported stroke evidence entry');
      const result = await fetchVerifiedJson({href:e.manifest, bytes:e.manifest_bytes, sha256:e.manifest_sha256, media_type:'application/json'}, entryUrl);
      evidence = result.value; base = result.url;
      require(evidence.schema === 'ao-explorer.dm-stroke-manifest.v1' && evidence.id === e.id, 'Stroke evidence identity mismatch');
      const report = (await fetchVerifiedJson(file('results.json'), base)).value.results;
      const small = report['2m'], large = report['42m'];
      const a = small.windows.analysis_0p2_to_1s, b = large.windows.analysis_0p2_to_1s;
      require(a.frames === 800 && b.frames === 400 && small.limit_um_opd_symmetric === 1 && large.limit_um_opd_symmetric === 100, 'Unexpected stroke comparison configuration');
      const clipped = x => `${x.issued_saturated_frames}/${x.frames} (${(100*x.issued_saturated_frame_fraction).toFixed(2)}%)`;
      const rows = [
        ['Symmetric OPD command limit', '±1 µm', '±100 µm'],
        ['Recorded actuator channels', String(small.actuators_in_record), String(large.actuators_in_record)],
        ['Frames with any clipped command', clipped(a), clipped(b)],
        ['Mean clipped actuator fraction', `${(100*a.issued_actuator_time_fraction).toFixed(2)}%`, `${(100*b.issued_actuator_time_fraction).toFixed(2)}%`],
        ['Maximum simultaneously clipped actuators', String(a.max_simultaneous_saturated_actuators), String(b.max_simultaneous_saturated_actuators)],
        ['Largest requested magnitude (µm OPD)', a.peak_requested_abs_um_opd.toFixed(3), b.peak_requested_abs_um_opd.toFixed(3)],
        ['Instantaneous peak Strehl, mean ± temporal SD', `${a.strehl.mean.toFixed(4)} ± ${a.strehl.std_population.toFixed(4)}`, `${b.strehl.mean.toFixed(4)} ± ${b.strehl.std_population.toFixed(4)}`],
        ['Science wavelength (µm)', small.science_wavelength_um.toFixed(2), large.science_wavelength_um.toFixed(2)]
      ];
      node('table-body').replaceChildren(...rows.map(values => {
        const tr = document.createElement('tr');
        values.forEach((text,i) => {const cell = document.createElement(i ? 'td' : 'th'); if (!i) cell.scope = 'row'; cell.textContent = text; tr.append(cell);});
        return tr;
      }));
      const {buffer} = await fetchVerified(file('stroke-saturation-comparison.png'), base);
      const imageUrl = URL.createObjectURL(new Blob([buffer], {type:'image/png'}));
      node('figure').src = imageUrl; await node('figure').decode(); node('figure').hidden = false;
      node('figure-full').href = imageUrl;
      for (const [label,name] of [['Methods and hardware sources','README.md'],['Numerical results','results.json'],['2 m per-frame values (CSV)','frames-2m.csv'],['42 m per-frame values (CSV)','frames-42m.csv'],['Figure (PDF)','stroke-saturation-comparison.pdf'],['Source identities and checks','publication.json']]) {
        const link = document.createElement('a'); link.textContent = label; link.href = new URL(name,base);
        link.addEventListener('click', async event => {
          event.preventDefault(); link.textContent = `Checking ${label}…`;
          try {
            const {buffer} = await fetchVerified(file(name),base);
            const url = URL.createObjectURL(new Blob([buffer],{type:file(name).media_type}));
            const a = document.createElement('a'); a.href = url; a.download = name; a.click();
            setTimeout(() => URL.revokeObjectURL(url),30000); link.textContent = label;
          } catch(error) { link.textContent = `${label} unavailable: ${error.message}`; }
        });
        node('downloads').append(link);
      }
      node('status').textContent = 'Saved saturation check loaded · existing data only';
    })();
    return ready;
  }
  const start = () => loadStroke().catch(error => {
    node('error').hidden = false; node('error').textContent = `Stroke evidence unavailable: ${error.message}. Reload to retry.`;
    node('status').textContent = 'The saved stroke evidence could not be verified.';
  });
  if ('IntersectionObserver' in window) {
    const observer = new IntersectionObserver(entries => {if (entries.some(e => e.isIntersecting)) {observer.disconnect();start();}}, {rootMargin:'200px'});
    observer.observe(root);
  } else start();
}
