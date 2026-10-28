// One immutable 42 m recording. Independent of the 2 m timeline and controls.
import { fetchVerified, fetchVerifiedJson, fetchVerifiedImage, require } from './integrity.js';
import { lineChart, redrawWhenResized } from './charts.js';

const $ = id => document.getElementById(`r42-${id}`);
const roles = [['atmosphere',0],['dm',1],['residual',2],['psf-u',3],['psf-c',4],['binary-u',5],['binary-c',6]];
const prefixes = ['', 'photo-'];
// Presentation slowdowns only (wall-clock seconds per simulated second); the recorded frames never change.
const SLOWDOWNS = [10, 20, 40];
const reducedMotion = window.matchMedia?.('(prefers-reduced-motion: reduce)').matches ?? false;
let data, manifest, manifestUrl, index=25, mode='frame', loaded=false, loading=false;
let playing=false, busy=false, ticket=0, last=0, cache=new Map(), pinned=new Set(), slowdown=reducedMotion ? 40 : 20;
const controls = () => document.querySelectorAll('#replay42 .r42-transport button, #replay42 .r42-transport input, #replay42 .r42-transport select, input[name="r42-mode"]');

function member(name) {
  const f=manifest.files[name]; require(f,`42 m member missing: ${name}`);
  return {...f,href:name,media_type:name.endsWith('.png')?'image/png':name.endsWith('.json')?'application/json':'application/octet-stream'};
}
function setButtons() { prefixes.forEach(p=>{$(`${p}play`).textContent=playing?'Pause':'Play';$(`${p}play`).setAttribute('aria-pressed',String(playing));}); }
function pause() { playing=false; setButtons(); }
function fail(error) {
  pause(); $('error').hidden=false; $('error').textContent=`42 m recording unavailable: ${error.message}. Any previously displayed frame remains the last frame that passed file integrity checks; reload to retry.`;
  controls().forEach(e=>e.disabled=true);
  $('viewer').removeAttribute('aria-busy');
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
  const base={x:{label:'Frame-start time',unit:'s',range:[0,1]},height:220,shadeX:[[0,.2,'startup exclusion']],cursorX:t[frame],cursorLabel:`frame ${frame}`};
  const series=(keys,scale)=>keys.map((key,i)=>({label:i?'AO-corrected':'Uncorrected',color:i?'#1f5f73':'#b3541e',points:m[key].map((v,k)=>[t[k],v*scale])}));
  lineChart($('chart-rms'),{...base,title:'42 m pupil RMS (pre-update residual)',y:{label:'Pupil RMS',unit:'nm',range:[0,Math.ceil(Math.max(...m.atmosphere_rms_m,...m.residual_rms_m)*1e9/500)*500]},series:series(['atmosphere_rms_m','residual_rms_m'],1e9)});
  lineChart($('chart-strehl'),{...base,title:'42 m instantaneous peak Strehl',y:{label:'Peak Strehl',range:[0,1]},series:series(['peak_strehl_uncorrected','peak_strehl_corrected'],1)});
}
// Only after a deliberate step, seek or pause: a live region is not updated at playback rate.
function announce(k) {
  const m=data.metrics;
  $('live').textContent=`Frame ${k} of 499, ${m.time_s[k].toFixed(3)} seconds, ${k<100?'startup':'analysis window'}. Residual ${(m.residual_rms_m[k]*1e9).toFixed(1)} nanometres; ${mode==='mean'?'images show the mean intensity':'images show this frame'}.`;
}
async function show(next, {speak=false}={}) {
  const request=++ticket;busy=true;
  const k=data.indices[next],mean=mode==='mean';
  pinned=new Set([String(k).padStart(4,'0'),...(mean?['mean']:[])]);
  // A frame that takes noticeably long to verify says so; a quick one never flashes a message.
  const slow=setTimeout(()=>{if(request===ticket){$('viewer').setAttribute('aria-busy','true');$('status').textContent=`Loading and checking recorded frame ${k}…`;}},200);
  try {
    const [raw,img]=await Promise.all([atlas(k),mean?atlas('mean'):atlas(k)]);
    if(request!==ticket)return;
    index=next;roles.forEach(([id,n])=>tile(id,n<3?raw:img,n));
    const m=data.metrics,time=m.time_s[k].toFixed(3),inWindow=k>=100;
    prefixes.forEach(p=>{const s=$(`${p}seek`);s.value=index;s.setAttribute('aria-valuetext',`frame ${k}, ${time} s`);});
    $('rms-u').textContent=`${(m.atmosphere_rms_m[k]*1e9).toFixed(1)} nm`;
    $('rms-c').textContent=`${(m.residual_rms_m[k]*1e9).toFixed(1)} nm`;
    $('frame-short').textContent=`${k} / 499`;
    $('time-short').textContent=`${time} s`;
    $('window').textContent=inWindow?'analysis':'startup (excluded)';
    $('time').textContent=`t = ${time} s / 1.000 s`;
    if(mean) {
      $('sr-label').replaceChildren('Peak Strehl ',Object.assign(document.createElement('span'),{textContent:'of the mean PSF, frames 100–499'}));
      $('sr').textContent=`${data.mean_peak_strehl.uncorrected.toFixed(4)} → ${data.mean_peak_strehl.corrected.toFixed(4)}`;
    } else {
      $('sr-label').replaceChildren('Peak Strehl ',Object.assign(document.createElement('span'),{textContent:'this frame · uncorrected → corrected'}));
      $('sr').textContent=`${m.peak_strehl_uncorrected[k].toFixed(4)} → ${m.peak_strehl_corrected[k].toFixed(4)}`;
    }
    for(const [suffix,role] of [['u','uncorrected'],['c','corrected']]) {
      const sr=mean?data.mean_peak_strehl[role]:m[`peak_strehl_${role}`][k];
      $(`strehl-${suffix}`).textContent=`${mean?'Peak Strehl of mean PSF':'Instantaneous peak Strehl'}: ${sr.toFixed(4)}`;
    }
    const readout=$('readout');
    readout.textContent=`Frame ${k} / 499 · ${time} / 1.000 s · ${inWindow?'analysis window':'startup exclusion'} · recorded snapshot ${index+1} / 126`;
    readout.dataset.frame=String(k);readout.dataset.mode=mode;
    $('photo-readout').textContent=mean?'400-frame intensity mean · 0.200–1.000 s · same image mode as the PSF panels':`Recorded instantaneous images · frame ${k} · ${time} s`;
    $('mode-note').textContent=(mean?`PSFs and binary images: mean intensity of all 400 frames 100–499 (not only the snapshots). Wavefronts and RMS: frame ${k}. `:`All wavefronts, PSFs and binary images: recorded frame ${k}. `)+`Image field ${data.field_arcsec.toFixed(3)}″ × ${data.field_arcsec.toFixed(3)}″; native sampling ${(data.step_arcsec*1000).toFixed(2)} mas.`;
    charts();
    $('status').textContent='Recorded simulation loaded · file integrity checked · 126 saved snapshots';
    if(speak&&!playing)announce(k);
    // Bounded prefetch: the next one or two snapshots only.
    for(const ahead of playing?[1,2]:[1])if(index+ahead<data.indices.length)atlas(data.indices[index+ahead]).catch(fail);
  } catch(error) { fail(error); } finally { clearTimeout(slow); if(request===ticket){busy=false;$('viewer').removeAttribute('aria-busy');} }
}
function tick(now) {
  if(!playing)return;
  if(!busy) {
    const next=Math.min(index+1,data.indices.length-1);
    const duration=(data.metrics.time_s[data.indices[next]]-data.metrics.time_s[data.indices[index]])*slowdown*1000;
    if(now-last>=duration) {
      last=now;
      if(index===data.indices.length-1){pause();announce(data.indices[index]);}else show(next);
    }
  }
  if(playing)requestAnimationFrame(tick);
}
function toggle() {
  if(!loaded)return;
  if(playing){pause();announce(data.indices[index]);return;}
  if(index===data.indices.length-1)show(0);
  playing=true;last=performance.now();setButtons();requestAnimationFrame(tick);
}
function jump(i) { if(!loaded)return; pause(); show(Math.max(0,Math.min(data.indices.length-1,i)),{speak:true}); }
function onKey(e) {
  if(!loaded||e.altKey||e.ctrlKey||e.metaKey||!e.target.closest('#replay42 .r42-keys'))return;
  const button=e.target.matches('button'), control=button||e.target.matches('input[type="range"]');
  const final=data.indices.length-1, act={ArrowLeft:()=>jump(index-1),ArrowRight:()=>jump(index+1),Home:()=>jump(0),End:()=>jump(final)}[e.key];
  if((e.key==='k'||e.key==='K')&&control){e.preventDefault();toggle();}
  else if(act&&button){e.preventDefault();act();}
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
    const replayRms=document.getElementById('c1-replay-rms');if(replayRms)replayRms.textContent=`${data.mean_rms_nm.residual.toFixed(1)} nm`;
    $('config-hash').textContent=data.config_hash;
    $('checks').textContent=`Numerical consistency checks: recorded RMS and timestamps match the loop history; separate intensity accumulations agree. Saved maps and convolution alignment/flux checks passed. ${data.trajectory_quality.unusable_reconstruction_frames} unusable reconstruction frames; maximum DM saturation fraction ${(data.trajectory_quality.max_dm_saturation_fraction*100).toFixed(3)}%. A separate eight-step check found that recording diagnostics did not change the loop history. This did not repeat the full 42 m run or validate instrument performance.`;
    for(const [label,name] of [['Source provenance','evidence/source.json'],['Linear template','evidence/binary-template.npz'],['Mean convolved images','evidence/binary-mean.npz']])download('source-downloads',label,name);
    for(const [label,name] of [['Public run plan','evidence/plan.json'],['Run summary','evidence/run-summary.json'],['All frame metrics','data.json'],['Export checks','evidence/export-checks.json'],['Source and archive identities','evidence/publication.json']])download('downloads',label,name);
    colourbars();loaded=true;await show(data.indices.indexOf(100));
    if($('error').hidden)controls().forEach(e=>e.disabled=false);
    for(const id of ['chart-rms','chart-strehl'])redrawWhenResized($(id),charts);
  }catch(error){fail(error);}finally{loading=false;}
}
export function initReplay42(entry,entryUrl) {
  prefixes.forEach(p=>{
    $(`${p}play`).addEventListener('click',toggle);
    for(const [action,offset] of [['prev',-1],['next',1]])$(`${p}${action}`).addEventListener('click',()=>jump(index+offset));
    $(`${p}restart`).addEventListener('click',()=>jump(0));
    $(`${p}end`).addEventListener('click',()=>jump(data.indices.length-1));
    $(`${p}seek`).addEventListener('input',e=>{pause();show(Number(e.target.value),{speak:true});});
  });
  const speed=$('speed');speed.value=String(slowdown);
  speed.addEventListener('change',()=>{slowdown=SLOWDOWNS.includes(Number(speed.value))?Number(speed.value):20;});
  if(reducedMotion)$('motion-note').textContent=' Reduced motion is on: playback starts only when you press Play and uses the slowest presentation by default.';
  document.querySelectorAll('input[name="r42-mode"]').forEach(e=>e.addEventListener('change',()=>{mode=e.value;show(index,{speak:true});}));
  document.addEventListener('keydown',onKey);
  document.addEventListener('visibilitychange',()=>{if(document.hidden)pause();});
  if('IntersectionObserver' in window)new IntersectionObserver(items=>{if(items.some(i=>i.isIntersecting))load(entry,entryUrl);else if(loaded)pause();},{rootMargin:'200px'}).observe(document.getElementById('replay42'));
  else load(entry,entryUrl);
  const hash=()=>{
    const id=location.hash.slice(1);
    if(['replay42-methods','replay42-source'].includes(id))document.getElementById(id).open=true;
    if(['replay42','replay42-methods','replay42-source','evidence-42m','c1-noise'].includes(id))load(entry,entryUrl);
  };
  window.addEventListener('hashchange',hash);hash();
}
