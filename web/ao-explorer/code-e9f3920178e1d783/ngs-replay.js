// A single clock commits one verified atlas, readout and chart cursor together.
// Independent of the 2 m/42 m players. No optical calculation in the browser.
import {fetchVerified, fetchVerifiedJson, fetchVerifiedImage, require} from './integrity.js';
import {lineChart, redrawWhenResized} from './charts.js';

export function initNgsReplay(entry, entryUrl) {
  const root=document.getElementById('ngs22-replay');
  if(!root)return;
  const $=name=>document.getElementById(`ngsr-${name}`);
  const roles=['atmosphere','residual-v1','residual-v2','psf-u','psf-v1','psf-v2'];
  let data,manifest,base,loading,index=0,requested=-1,ticket=0,playing=false,timer=null,busy=false,failed=false;
  let duration=matchMedia('(prefers-reduced-motion: reduce)').matches?60:40;
  const cache=new Map();
  const file=name=>{require(manifest.files[name],`Replay member missing: ${name}`);return {href:name,...manifest.files[name]};};
  function pause(){playing=false;clearTimeout(timer);$('play').textContent='Play';$('play').setAttribute('aria-pressed','false');}
  function fail(error){
    failed=true;pause();++ticket;busy=false;
    $('error').hidden=false;$('error').textContent=`Replay unavailable: ${error.message}. Any visible images and cursor remain at the last verified frame. Reload to retry.`;
    root.querySelectorAll('button,input,select').forEach(e=>e.disabled=true);
    $('status').textContent='The requested replay asset could not be verified.';
  }
  function trim(){
    for(const [k,item] of cache){
      if(cache.size<=12)break;
      if(item.bitmap && k!==data.indices[index] && k!==requested){item.bitmap.close();cache.delete(k);}
    }
  }
  function atlas(k){
    if(!cache.has(k)){
      const item={};
      item.promise=fetchVerifiedImage(file(`frames/${String(k).padStart(4,'0')}.png`),base).then(({bitmap})=>{
        require(bitmap.width===6*data.tile && bitmap.height===data.tile,'Unexpected atlas dimensions');item.bitmap=bitmap;return bitmap;
      });cache.set(k,item);
    }
    const item=cache.get(k);cache.delete(k);cache.set(k,item);return item.promise;
  }
  function chart(){
    if(!data)return;
    const k=data.indices[index],m=data.metrics;
    lineChart($('strehl'),{title:'2.2 m instantaneous H-band Strehl; v1 loss of lock at 0.981333 s',height:260,
      x:{label:'Frame-start time',unit:'s',range:[0,2]},y:{label:'Peak Strehl',range:[0,1]},
      shadeX:[[0,.2,'startup exclusion'],[data.loss_time_s,2,'v1 reconstruction unusable']],
      verticalLines:[{x:data.loss_time_s,color:'#a3324e',label:'v1 loss · 0.981333 s'}],cursorX:m.time_s[k],
      series:[{label:'Original v1',color:'#b3541e',points:m.v1.strehl.map((v,i)=>[m.time_s[i],v])},
        {label:'Repaired v2',color:'#4d7a2a',points:m.v2.strehl.map((v,i)=>[m.time_s[i],v])},
        {label:'Uncorrected',color:'#7d7d7d',style:'dashed',points:m.uncorrected_strehl.map((v,i)=>[m.time_s[i],v])}]});
  }
  function labels(){
    const k=data.indices[index],m=data.metrics,t=m.time_s[k];
    $('seek').value=index;$('seek').setAttribute('aria-valuetext',`Frame ${k}, ${t.toFixed(6)} seconds, sample ${index+1} of ${data.indices.length}`);
    $('readout').textContent=`Frame ${k} / 1499 · ${t.toFixed(6)} s / 2.000 s · snapshot ${index+1}/${data.indices.length} · ${k<150?'startup exclusion':'analysis window'}`;
    $('readout').dataset.frame=String(k);
    $('event').textContent=k<data.loss_frame
      ? `Before v1's first rejected reconstruction (${((data.loss_time_s-t)*1000).toFixed(3)} ms before frame 736).`
      : k===data.loss_frame?'Loss marker: frame 736 is v1’s first rejected reconstruction; v2 remains usable.'
      : `After v1’s first rejected reconstruction (${((t-data.loss_time_s)*1000).toFixed(3)} ms later). V1 continues to be displayed, including its failed frames.`;
    $('event').dataset.phase=k<data.loss_frame?'before':k===data.loss_frame?'loss':'after';
    $('atmosphere-caption').textContent=`Shared atmosphere · RMS ${m.atmosphere_rms_nm[k].toFixed(1)} nm`;
    $('psf-u-caption').textContent=`Uncorrected · Strehl ${m.uncorrected_strehl[k].toFixed(4)}`;
    for(const id of ['v1','v2']){
      const v=m[id];
      $(`residual-${id}-caption`).textContent=`${id==='v1'?'Original v1':'Repaired v2'} residual · RMS ${v.rms_nm[k].toFixed(1)} nm`;
      $(`psf-${id}-caption`).textContent=`${id==='v1'?'Original v1':'Repaired v2'} PSF · Strehl ${v.strehl[k].toFixed(4)}`;
      $(`valid-${id}`).textContent=`${id==='v1'?'Original v1':'Repaired v2'}: ${v.usable[k]?'usable reconstruction':'RECONSTRUCTION REJECTED'} · ${(v.valid_fraction[k]*100).toFixed(2)}% valid rows`;
    }
    const until=index+1<data.indices.length?m.time_s[data.indices[index+1]]:2;
    $('timing').textContent=`One pass: ${duration} s (${duration/2}× slower). This snapshot is held to ${until.toFixed(6)} s of recorded time. No interpolation; loading or background tabs may extend playback.`;
    $('status').textContent='Synchronized saved-wavefront replay · images and all 1500 curve samples verified';
    $('previous').disabled=index===0;$('next').disabled=index===data.indices.length-1;
  }
  async function show(next){
    if(failed||!data)return false;
    next=Math.max(0,Math.min(data.indices.length-1,next));
    const token=++ticket,k=data.indices[next];requested=k;busy=true;
    $('seek').value=index;$('status').textContent=`Loading and checking frame ${k}… displayed frame remains ${data.indices[index]}.`;
    try{
      const bitmap=await atlas(k);
      if(token!==ticket)return false;
      // One atlas prevents mixed-frame before/after images, even on fast seeks.
      roles.forEach((role,n)=>{const c=$(role);c.getContext('2d').drawImage(bitmap,n*data.tile,0,data.tile,data.tile,0,0,c.width,c.height);c.dataset.frame=String(k);});
      index=next;labels();chart();trim();return true;
    }catch(error){if(token===ticket)fail(error);return false;}
    finally{if(token===ticket)busy=false;}
  }
  function schedule(){
    clearTimeout(timer);if(!playing||busy||failed)return;
    const times=data.metrics.time_s;
    const end=index+1<data.indices.length?times[data.indices[index+1]]:2;
    timer=setTimeout(async()=>{
      if(!playing)return;
      if(index===data.indices.length-1){pause();return;}
      if(await show(index+1))schedule();
    },(end-times[data.indices[index]])*duration/2*1000);
  }
  async function seek(next){pause();await show(next);}
  async function toggle(){
    if(playing){pause();return;}
    if(busy||failed)return;
    if(index===data.indices.length-1 && !await show(0))return;
    playing=true;$('play').textContent='Pause';$('play').setAttribute('aria-pressed','true');schedule();
  }
  function bars(){
    const wave=[ [34,82,151],[232,237,239],[220,92,62] ];
    const psf=[[5,9,19],[29,24,67],[112,40,100],[219,90,61],[250,193,91],[255,247,217]];
    for(const [name,nodes] of [['wave',wave],['psf',psf]]){
      const c=$(`${name}-scale`),ctx=c.getContext('2d');
      for(let x=0;x<c.width;x++){
        const z=x/(c.width-1)*(nodes.length-1),i=Math.min(Math.floor(z),nodes.length-2),f=z-i;
        ctx.fillStyle=`rgb(${nodes[i].map((v,j)=>Math.trunc(v*(1-f)+nodes[i+1][j]*f)).join(',')})`;ctx.fillRect(x,0,1,c.height);
      }
    }
    $('wave-scale-text').textContent=`−${data.opd_limit_nm.toFixed(0)} nm · 0 · +${data.opd_limit_nm.toFixed(0)} nm OPD (fixed)`;
    $('field').textContent=`All PSFs: H band, 1.65 µm; ${data.psf_field_arcsec.toFixed(3)}″ × ${data.psf_field_arcsec.toFixed(3)}″ field, ${(data.psf_pixel_arcsec*1000).toFixed(2)} mas native pixels. No recentering; brightness relative to the same ideal PSF peak.`;
  }
  function download(label,name){
    const a=document.createElement('a');a.href=new URL(name,base);a.textContent=label;
    a.addEventListener('click',async e=>{e.preventDefault();try{
      const {buffer}=await fetchVerified(file(name),base);const u=URL.createObjectURL(new Blob([buffer],{type:file(name).media_type}));
      const link=document.createElement('a');link.href=u;link.download=name;link.click();setTimeout(()=>URL.revokeObjectURL(u),30000);
    }catch(error){a.textContent=`${label} unavailable: ${error.message}`;}});$('downloads').append(a);
  }
  async function load(){
    if(loading)return loading;
    loading=(async()=>{
      const e=entry.ngsReplay;require(e?.schema==='ao-explorer.ngs-replay-entry.v1','No supported NGS replay');
      const r=await fetchVerifiedJson({href:e.manifest,bytes:e.manifest_bytes,sha256:e.manifest_sha256,media_type:'application/json'},entryUrl);
      manifest=r.value;base=r.url;require(manifest.schema==='ao-explorer.ngs-replay-manifest.v1'&&manifest.id===e.id,'NGS replay identity mismatch');
      data=(await fetchVerifiedJson(file('data.json'),base)).value;
      require(data.schema==='ao-explorer.ngs-replay-data.v1'&&data.tile===256&&data.frames===1500&&data.wavelength_m===1.65e-6,'Unexpected NGS replay layout');
      const m=data.metrics,t=m.time_s;
      require(t?.length===1500&&t.every((v,i)=>Number.isFinite(v)&&Math.abs(v-i/750)<1e-12),'NGS time axis mismatch');
      require(data.loss_frame===736&&data.loss_time_s===t[736]&&m.v1.usable.findIndex(v=>!v)===736&&m.v2.usable.every(v=>v===true),'NGS loss marker mismatch');
      require(data.indices[0]===0&&data.indices.at(-1)===1499&&data.indices.includes(735)&&data.indices.includes(736)&&data.indices.includes(737)&&data.indices.every((v,i)=>Number.isInteger(v)&&v>=0&&v<1500&&(!i||v>data.indices[i-1])),'Invalid replay sampling');
      for(const key of ['v1','v2']){
        for(const field of ['strehl','rms_nm','valid_fraction'])require(m[key][field].length===1500&&m[key][field].every(Number.isFinite),`Incomplete ${key} ${field}`);
        require(m[key].usable.length===1500&&m[key].usable.every(v=>typeof v==='boolean'),`Invalid ${key} validity`);
      }
      for(const field of ['uncorrected_strehl','atmosphere_rms_nm'])require(m[field].length===1500&&m[field].every(Number.isFinite),`Incomplete ${field}`);
      index=data.indices.indexOf(150);require(index>=0,'Missing analysis-window start');
      $('seek').max=data.indices.length-1;$('duration').value=String(duration);bars();
      root.querySelectorAll('button,input,select').forEach(e=>e.disabled=false);
      $('sampling').textContent=`${data.indices.length} existing wavefront snapshots: every 12th frame, all archived PSF snapshot times, and every frame 720–752 around loss of lock. The curves show all 1500 saved measurements. Both runs always show the same timestamp.`;
      for(const [label,name] of [['All replay metrics','data.json'],['Replay provenance and checks','provenance.json'],['Replay methods','README.md'],['Offline exporter','exporter.py']])download(label,name);
      await show(index);redrawWhenResized($('strehl'),chart);
    })();return loading;
  }
  $('play').addEventListener('click',()=>{toggle().catch(fail);});
  $('previous').addEventListener('click',()=>seek(index-1));$('next').addEventListener('click',()=>seek(index+1));
  $('restart').addEventListener('click',()=>seek(0));$('seek').addEventListener('input',e=>seek(Number(e.target.value)));
  for(const [id,k] of [['before',735],['loss',736],['after',737]])$(id).addEventListener('click',()=>seek(data.indices.indexOf(k)));
  $('duration').addEventListener('change',()=>{duration=Number($('duration').value);labels();schedule();});
  document.addEventListener('visibilitychange',()=>{if(document.hidden)pause();});
  const open=()=>load().catch(fail);
  if('IntersectionObserver' in window){const o=new IntersectionObserver(entries=>{if(entries.some(e=>e.isIntersecting)){o.disconnect();open();}},{rootMargin:'200px'});o.observe(root);}else open();
  window.addEventListener('hashchange',()=>{if(location.hash==='#ngs22-replay')open();});
  if(location.hash==='#ngs22-replay')open();
}
