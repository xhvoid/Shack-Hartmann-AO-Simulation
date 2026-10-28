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

// The separate static C1 noise assessment: one small verified summary drawn as a zero-based chart.
// Its controls change only this chart; they never touch the replay above.
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

// Separate, immutable postprocessing evidence. These controls never alter either AO replay.
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
