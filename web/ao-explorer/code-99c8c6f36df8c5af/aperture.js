// Separate, immutable postprocessing evidence: the matched aperture comparison. These controls never alter either AO replay.
import { fetchVerified, fetchVerifiedJson, require } from './integrity.js';

export function initApertureComparison(entry, entryUrl) {
  const root = document.getElementById('aperture-comparison');
  if (!root) return;
  const node = name => document.getElementById(`comparison-${name}`);
  let ready, evidence, base, request = 0, animationRequest = 0, animating = false;
  const urls = new Map();
  const buttons = [...root.querySelectorAll('[data-comparison-lag]')];
  const file = name => {
    require(evidence?.files[name], `Comparison member missing: ${name}`);
    return {href: name, ...evidence.files[name]};
  };
  const asset = name => {
    if (!urls.has(name)) urls.set(name, fetchVerified(file(name), base).then(({buffer}) =>
      URL.createObjectURL(new Blob([buffer], {type: file(name).media_type}))));
    return urls.get(name);
  };
  async function picture(id, name, full) {
    const url = await asset(name);
    node(id).src = url;
    await node(id).decode();
    node(id).hidden = false;
    if (full) node(full).href = url;
  }
  function failure(error) {
    stopAnimation();
    node('error').hidden = false;
    node('error').textContent = `Comparison unavailable: ${error.message}. Any existing figure remains the last one that passed file integrity checks; reload to retry.`;
    node('status').textContent = 'A comparison asset could not be verified.';
    buttons.forEach(button => button.disabled = true);
    node('animation-toggle').disabled = true;
  }
  async function showLag(ms) {
    const id = ++request;
    const url = await asset(`comparison_${String(ms).padStart(3,'0')}ms.png`);
    if (id !== request) return;
    node('map').src = url;
    await node('map').decode();
    if (id !== request) return;
    node('map').hidden = false;
    node('map-full').href = url;
    node('map').alt = `Independent 2 m baseline above and fixed 2 m patch from 42 m below: maps at 0.200 and ${(0.2+ms/1000).toFixed(3)} seconds and their difference, with one shared color scale.`;
    node('map-caption').textContent = `Top: independent 2 m baseline. Bottom: fixed 2 m patch from 42 m. Columns: 0.200 s, ${(0.2+ms/1000).toFixed(3)} s, and later minus earlier (${ms} ms). Every panel uses ±2500 nm OPD. Open the image for full resolution.`;
    buttons.forEach(button => button.setAttribute('aria-pressed',String(Number(button.dataset.comparisonLag)===ms)));
  }
  function addDownload(label, name) {
    const link = document.createElement('a');
    link.textContent = label; link.href = new URL(name,base);
    link.addEventListener('click', async event => {
      event.preventDefault(); link.textContent = `Checking ${label}…`;
      try {
        const url = await asset(name);
        const a = document.createElement('a'); a.href = url; a.download = name; a.click();
        link.textContent = label;
      } catch(error) { link.textContent = `${label} unavailable: ${error.message}`; }
    });
    node('downloads').append(link);
  }
  async function loadComparison() {
    if (ready) return ready;
    ready = (async () => {
      node('status').textContent = 'Loading saved figures and checking their file identities…';
      const e = entry.apertureComparison;
      require(e?.schema==='ao-explorer.aperture-entry.v1','No supported aperture-comparison entry');
      const manifestResult = await fetchVerifiedJson({href:e.manifest,bytes:e.manifest_bytes,sha256:e.manifest_sha256,media_type:'application/json'},entryUrl);
      evidence = manifestResult.value; base = manifestResult.url;
      require(evidence.schema==='ao-explorer.aperture-manifest.v1' && evidence.id===e.id,'Comparison manifest identity mismatch');
      const report = (await fetchVerifiedJson(file('comparison.json'),base)).value;
      require(report.schema==='ao-explorer.aperture-comparison.v1' && report.samples===400 && report.time_step_s===.002 && report.color_limit_nm===2500,'Unsupported comparison sampling');
      const b=report.summary['2m_baseline'], c=report.summary['42m_2m_crop'];
      const rows=[
        ['Mean spatial RMS (nm OPD)',b.mean_spatial_rms_nm.toFixed(1),c.mean_spatial_rms_nm.toFixed(1)],
        ['Temporal standard deviation of RMS (nm)',b.temporal_std_of_spatial_rms_nm.toFixed(1),c.temporal_std_of_spatial_rms_nm.toFixed(1)],
        ['Relative temporal fluctuation of RMS',`${(100*b.relative_temporal_std).toFixed(1)}%`,`${(100*c.relative_temporal_std).toFixed(1)}%`],
        ...[8,100,500].map(ms=>[`Wavefront difference RMS, ${ms} ms (nm)`,b.lag_statistics[ms].space_time_rms_nm.toFixed(1),c.lag_statistics[ms].space_time_rms_nm.toFixed(1)])
      ];
      node('table-body').replaceChildren(...rows.map(values=>{
        const tr=document.createElement('tr');
        values.forEach((text,i)=>{const cell=document.createElement(i?'td':'th');if(!i)cell.scope='row';cell.textContent=text;tr.append(cell);});return tr;
      }));
      await Promise.all([showLag(100),picture('temporal','temporal_comparison.png','temporal-full')]);
      for (const [label,name] of [['Methods','README.md'],['Numerical results','comparison.json'],['Control comparison','control_comparison.json'],['Per-time values (CSV)','timeseries.csv'],['Matched wavefront arrays (12 MB)','matched_wavefronts.npz'],['Postprocessing source','analysis.py'],['Verification record','verification.json'],['Publication provenance','publication.json']]) addDownload(label,name);
      buttons.forEach(button=>button.disabled=false); node('animation-toggle').disabled=false;
      node('status').textContent='Saved comparison loaded · file identities checked · existing data only';
    })();
    return ready;
  }
  function stopAnimation() {
    ++animationRequest;
    if (!animating) return;
    animating=false;
    node('animation-toggle').textContent='Play comparison';
    node('animation-toggle').setAttribute('aria-pressed','false');
    node('animation-caption').textContent='Stopped. The preview returns to t = 0.200 s; another play starts the same recording again.';
    picture('animation-image','animation_preview.png').catch(failure);
  }
  node('animation-toggle').addEventListener('click',async()=>{
    if(animating){stopAnimation();return;}
    const id=++animationRequest;
    node('animation-toggle').disabled=true;
    node('animation-toggle').textContent='Loading animation…';
    try {
      const url=await asset('synchronized_comparison.webp');
      if(id!==animationRequest){node('animation-toggle').textContent='Play comparison';return;}
      node('animation-image').src=url;await node('animation-image').decode();node('animation-image').hidden=false;
      if(id!==animationRequest || !node('animation').open || document.hidden){
        node('animation-toggle').textContent='Play comparison';
        await picture('animation-image','animation_preview.png');return;
      }
      animating=true;node('animation-toggle').textContent='Stop comparison';node('animation-toggle').setAttribute('aria-pressed','true');
      node('animation-caption').textContent='Playing 99 saved samples at 20× slower speed: 0.200–0.984 s, with 8 ms differences through 0.992 s. Each loop repeats the same recording.';
    }catch(error){failure(error);}finally{node('animation-toggle').disabled=!node('error').hidden;}
  });
  buttons.forEach(button=>button.addEventListener('click',()=>showLag(Number(button.dataset.comparisonLag)).catch(failure)));
  node('location').addEventListener('toggle',()=>{if(node('location').open)loadComparison().then(()=>picture('location-image','crop_location.png')).catch(failure);});
  node('animation').addEventListener('toggle',()=>{
    if(node('animation').open)loadComparison().then(()=>picture('animation-image','animation_preview.png')).catch(failure);
    else stopAnimation();
  });
  document.addEventListener('visibilitychange',()=>{if(document.hidden)stopAnimation();});
  if('IntersectionObserver' in window){
    const observer=new IntersectionObserver(entries=>{if(entries.some(e=>e.isIntersecting)){observer.disconnect();loadComparison().catch(failure);}},{rootMargin:'200px'});observer.observe(root);
  } else loadComparison().catch(failure);
}
