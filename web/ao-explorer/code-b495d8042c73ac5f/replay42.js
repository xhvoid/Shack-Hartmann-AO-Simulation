// One immutable 42 m recording. Independent of the 2 m timeline and controls.
import { fetchVerified, fetchVerifiedJson, fetchVerifiedImage, require } from './integrity.js';
import { lineChart, redrawWhenResized } from './charts.js';

const $ = id => document.getElementById(`r42-${id}`);
const roles = [['atmosphere',0],['dm',1],['residual',2],['psf-u',3],['psf-c',4],['binary-u',5],['binary-c',6]];
const prefixes = ['', 'photo-'];
let data, manifest, manifestUrl, index=25, mode='frame', loaded=false, loading=false;
let playing=false, busy=false, ticket=0, last=0, cache=new Map(), pinned=new Set();

function member(name) {
  const f=manifest.files[name]; require(f,`42 m member missing: ${name}`);
  return {...f,href:name,media_type:name.endsWith('.png')?'image/png':name.endsWith('.json')?'application/json':'application/octet-stream'};
}
function setButtons() { prefixes.forEach(p=>{$(`${p}play`).textContent=playing?'Pause':'Play';$(`${p}play`).setAttribute('aria-pressed',String(playing));}); }
function pause() { playing=false; setButtons(); }
function fail(error) {
  pause(); $('error').hidden=false; $('error').textContent=`42 m recording unavailable: ${error.message}. Any previously displayed frame remains the last frame that passed file integrity checks; reload to retry.`;
  document.querySelectorAll('#replay42 .transport button, #replay42 .transport input, input[name="r42-mode"]').forEach(e=>e.disabled=true);
  $('status').textContent='The requested recording or asset failed its integrity checks.';
}
function atlas(k) {
  const key=k==='mean'?'mean':String(k).padStart(4,'0');
  if (!cache.has(key)) cache.set(key,fetchVerifiedImage(member(`frames/${key}.png`),manifestUrl).then(r=>r.bitmap));
  const p=cache.get(key);cache.delete(key);cache.set(key,p);
  while(cache.size>24) {
    const old=[...cache.keys()].find(k=>!pinned.has(k)); if(!old)break;
    cache.get(old).then(b=>b.close()).catch(()=>{});cache.delete(old);
  }
  return p;
}
function tile(id,bitmap,n) {
  const c=$(id),ctx=c.getContext('2d');ctx.clearRect(0,0,c.width,c.height);
  ctx.drawImage(bitmap,n*256,0,256,256,0,0,c.width,c.height);
}
function charts() {
  if(!data)return;
  const m=data.metrics,t=m.time_s,frame=data.indices[index];
  const base={x:{label:'Frame-start time',unit:'s',range:[0,1]},height:220,shadeX:[[0,.2,'startup exclusion']],cursorX:t[frame]};
  const series=(keys,scale)=>keys.map((key,i)=>({label:i?'AO-corrected':'Uncorrected',color:i?'#1f5f73':'#b3541e',points:m[key].map((v,k)=>[t[k],v*scale])}));
  lineChart($('chart-rms'),{...base,title:'42 m pupil RMS',y:{label:'Pupil RMS',unit:'nm',range:[0,Math.ceil(Math.max(...m.atmosphere_rms_m,...m.residual_rms_m)*1e9/500)*500]},series:series(['atmosphere_rms_m','residual_rms_m'],1e9)});
  lineChart($('chart-strehl'),{...base,title:'42 m instantaneous peak Strehl',y:{label:'Peak Strehl',range:[0,1]},series:series(['peak_strehl_uncorrected','peak_strehl_corrected'],1)});
}
async function show(next) {
  const request=++ticket;busy=true;
  const k=data.indices[next],mean=mode==='mean';
  pinned=new Set([String(k).padStart(4,'0'),...(mean?['mean']:[])]);
  try {
    const [raw,img]=await Promise.all([atlas(k),mean?atlas('mean'):atlas(k)]);
    if(request!==ticket)return;
    index=next;roles.forEach(([id,n])=>tile(id,n<3?raw:img,n));
    const m=data.metrics,time=m.time_s[k].toFixed(3);
    prefixes.forEach(p=>$(`${p}seek`).value=index);
    $('rms-u').textContent=`${(m.atmosphere_rms_m[k]*1e9).toFixed(1)} nm`;
    $('rms-c').textContent=`${(m.residual_rms_m[k]*1e9).toFixed(1)} nm`;
    $('frame-short').textContent=`${k} · ${time} s`;
    for(const [suffix,role] of [['u','uncorrected'],['c','corrected']]) {
      const sr=mean?data.mean_peak_strehl[role]:m[`peak_strehl_${role}`][k];
      $(`strehl-${suffix}`).textContent=`${mean?'Peak Strehl of mean PSF':'Instantaneous peak Strehl'}: ${sr.toFixed(4)}`;
    }
    $('readout').textContent=`Frame ${k} / 499 · ${time} / 1.000 s · ${k<100?'startup exclusion':'analysis window'} · recorded snapshot ${index+1} / 126`;
    $('photo-readout').textContent=mean?'400-frame intensity mean · 0.200–1.000 s · same image mode as the PSF panels':`Recorded instantaneous images · frame ${k} · ${time} s`;
    $('mode-note').textContent=(mean?`PSFs and binary images: 400-frame intensity mean. Wavefronts and RMS: frame ${k}. `:`All wavefronts, PSFs and binary images: recorded frame ${k}. `)+`Image field ${data.field_arcsec.toFixed(3)}″ × ${data.field_arcsec.toFixed(3)}″; native sampling ${(data.step_arcsec*1000).toFixed(2)} mas.`;
    charts();
    $('status').textContent='Recorded simulation loaded · file integrity checked · 126 saved snapshots';
    if(index+1<data.indices.length)atlas(data.indices[index+1]).catch(fail);
  } catch(error) { fail(error); } finally { if(request===ticket)busy=false; }
}
function tick(now) {
  if(!playing)return;
  if(!busy) {
    const next=Math.min(index+1,data.indices.length-1);
    const duration=(data.metrics.time_s[data.indices[next]]-data.metrics.time_s[data.indices[index]])*20000;
    if(now-last>=duration) {
      last=now;
      if(index===data.indices.length-1)pause();else show(next);
    }
  }
  if(playing)requestAnimationFrame(tick);
}
function toggle() {
  if(playing){pause();return;}
  if(index===data.indices.length-1)show(0);
  playing=true;last=performance.now();setButtons();requestAnimationFrame(tick);
}
function colourbars() {
  const wave=t=>{
    const lo=[34,82,151],mid=[232,237,239],hi=[220,92,62];
    return mid.map((m,i)=>Math.round(t<0?m+(m-lo[i])*t:m+(hi[i]-m)*t));
  };
  const nodes=[[5,9,19],[29,24,67],[112,40,100],[219,90,61],[250,193,91],[255,247,217]];
  const psf=t=>{const z=t*5,i=Math.min(Math.floor(z),4),f=z-i;return nodes[i].map((v,k)=>Math.round(v*(1-f)+nodes[i+1][k]*f));};
  for(const kind of ['opd','psf']) {
    const c=$(`cbar-${kind}`),ctx=c.getContext('2d');
    for(let j=0;j<c.height;j++){const t=1-j/(c.height-1);ctx.fillStyle=`rgb(${(kind==='opd'?wave(t*2-1):psf(t)).join(',')})`;ctx.fillRect(0,j,c.width,1);}
    const labels=kind==='opd'?[`+${data.opd_limit_um.toFixed(1)} µm`,'0',`−${data.opd_limit_um.toFixed(1)} µm`]:['1','10⁻³','10⁻⁶'];
    $(`${kind}-labels`).replaceChildren(...labels.map((label,i)=>{const s=document.createElement('span');s.textContent=label;s.style.top=`${i*50}%`;return s;}));
  }
}
function download(host,label,name) {
  const link=document.createElement('a');link.href=new URL(name,manifestUrl);link.textContent=label;
  link.addEventListener('click',async e=>{
    e.preventDefault();link.textContent=`Verifying ${label}…`;
    try{const {buffer}=await fetchVerified(member(name),manifestUrl);const url=URL.createObjectURL(new Blob([buffer],{type:member(name).media_type}));const a=document.createElement('a');a.href=url;a.download=name.split('/').at(-1);a.click();setTimeout(()=>URL.revokeObjectURL(url),30000);link.textContent=label;}catch(error){link.textContent=`${label} unavailable: ${error.message}`;}
  });$(host).append(link);
}
async function load(entry,entryUrl) {
  if(loaded||loading)return;loading=true;$('status').textContent='Loading the 42 m simulation recording and checking file integrity…';
  try {
    const e=entry.replay42;require(e?.schema==='ao-explorer.recording42-entry.v1','No supported 42 m recording entry');
    const r=await fetchVerifiedJson({href:e.manifest,bytes:e.manifest_bytes,sha256:e.manifest_sha256,media_type:'application/json'},entryUrl);
    manifest=r.value;manifestUrl=r.url;require(manifest.schema==='ao-explorer.recording42.v1'&&manifest.recording_id===e.recording_id,'42 m manifest identity mismatch');
    data=(await fetchVerifiedJson(member('data.json'),manifestUrl)).value;
    require(data.schema==='ao-replay.42m.local.v1'&&data.tile===256,'Unsupported 42 m data');
    const indices=Array.from({length:125},(_,i)=>i*4).concat([499]);
    require(JSON.stringify(data.indices)===JSON.stringify(indices),'42 m replay indices differ from the recorded contract');
    for(const key of ['time_s','atmosphere_rms_m','residual_rms_m','peak_strehl_uncorrected','peak_strehl_corrected'])require(data.metrics[key]?.length===500&&data.metrics[key].every(Number.isFinite),`42 m ${key} is incomplete`);
    require(data.metrics.time_s.every((v,i)=>Math.abs(v-i/500)<1e-12),'42 m timestamps are inconsistent');
    const source=await fetchVerifiedImage(member('source.png'),manifestUrl);$('source').getContext('2d').drawImage(source.bitmap,0,0);source.bitmap.close();
    document.querySelectorAll('.r42-scale').forEach(e=>e.style.width=`${.2/data.field_arcsec*100}%`);
    $('mean-rms-u').textContent=`${data.mean_rms_nm.atmosphere.toFixed(1)} nm`;$('mean-rms-c').textContent=`${data.mean_rms_nm.residual.toFixed(1)} nm`;$('mean-strehl').textContent=`≈ ${data.mean_peak_strehl.corrected.toFixed(2)}`;
    $('config-hash').textContent=data.config_hash;
    $('checks').textContent=`Numerical consistency checks: recorded RMS and timestamps match the loop history; separate intensity accumulations agree. Saved maps and convolution alignment/flux checks passed. ${data.trajectory_quality.unusable_reconstruction_frames} unusable reconstruction frames; maximum DM saturation fraction ${(data.trajectory_quality.max_dm_saturation_fraction*100).toFixed(3)}%. A separate eight-step check found that recording diagnostics did not change the loop history. This did not repeat the full 42 m run or validate instrument performance.`;
    for(const [label,name] of [['Source provenance','evidence/source.json'],['Linear template','evidence/binary-template.npz'],['Mean convolved images','evidence/binary-mean.npz']])download('source-downloads',label,name);
    for(const [label,name] of [['Public run plan','evidence/plan.json'],['Run summary','evidence/run-summary.json'],['All frame metrics','data.json'],['Export checks','evidence/export-checks.json'],['Source and archive identities','evidence/publication.json']])download('downloads',label,name);
    colourbars();loaded=true;await show(data.indices.indexOf(100));
    if($('error').hidden)document.querySelectorAll('#replay42 .transport button, #replay42 .transport input, input[name="r42-mode"]').forEach(e=>e.disabled=false);
    for(const id of ['chart-rms','chart-strehl'])redrawWhenResized($(id),charts);
  }catch(error){fail(error);}finally{loading=false;}
}
export function initReplay42(entry,entryUrl) {
  prefixes.forEach(p=>{
    $(`${p}play`).addEventListener('click',toggle);
    for(const [action,offset] of [['prev',-1],['next',1]])$(`${p}${action}`).addEventListener('click',()=>{pause();show(Math.max(0,Math.min(data.indices.length-1,index+offset)));});
    $(`${p}restart`).addEventListener('click',()=>{pause();show(0);});
    $(`${p}seek`).addEventListener('input',e=>{pause();show(Number(e.target.value));});
  });
  document.querySelectorAll('input[name="r42-mode"]').forEach(e=>e.addEventListener('change',()=>{mode=e.value;show(index);}));
  document.addEventListener('visibilitychange',()=>{if(document.hidden)pause();});
  if('IntersectionObserver' in window)new IntersectionObserver(items=>{if(items.some(i=>i.isIntersecting))load(entry,entryUrl);else if(loaded)pause();},{rootMargin:'200px'}).observe(document.getElementById('replay42'));
  else load(entry,entryUrl);
  const hash=()=>{
    const id=location.hash.slice(1);
    if(['replay42-methods','replay42-source'].includes(id))document.getElementById(id).open=true;
    if(['replay42','replay42-methods','replay42-source'].includes(id))load(entry,entryUrl);
  };
  window.addEventListener('hashchange',hash);hash();
}

// Separate, immutable postprocessing evidence. These controls never alter either AO replay.
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
