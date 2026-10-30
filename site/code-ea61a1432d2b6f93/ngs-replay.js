// A single clock commits one verified atlas, readout and chart cursor together.
// Independent of the 2 m/42 m players. No optical calculation in the browser.
import {fetchVerified, fetchVerifiedJson, fetchVerifiedImage, require} from './integrity.js';
import {lineChart, redrawWhenResized} from './charts.js';

export function initNgsReplay(entry, entryUrl) {
  const root=document.getElementById('ngs22-replay');
  if(!root)return;
  const $=name=>document.getElementById(`ngsr-${name}`);
  const roles=['atmosphere','residual-v1','residual-v2','psf-u','psf-v1','psf-v2'];
  let data,manifest,base,science,scienceManifest,scienceBase,scienceReference,referenceMode=0,loading,index=0,requested=-1,ticket=0,playing=false,timer=null,busy=false,failed=false;
  let duration=matchMedia('(prefers-reduced-motion: reduce)').matches?60:40;
  const cache=new Map(),scienceCache=new Map();
  const scienceFile=name=>{require(scienceManifest.files[name],`F162M science member missing: ${name}`);return {href:name,...scienceManifest.files[name]};};
  const file=name=>{require(manifest.files[name],`Replay member missing: ${name}`);return {href:name,...manifest.files[name]};};
  function pause(){playing=false;clearTimeout(timer);$('play').textContent='Play';$('play').setAttribute('aria-pressed','false');$('science-play').textContent='Play';$('science-play').setAttribute('aria-pressed','false');}
  function fail(error){
    failed=true;pause();++ticket;busy=false;
    $('error').hidden=false;$('error').textContent=`Replay unavailable: ${error.message}. The viewer is paused at the last checked frame. Reload to try again.`;
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
  function scienceAtlas(k){
    if(!scienceCache.has(k)){
      const item={};
      item.promise=fetchVerifiedImage(scienceFile(`frames/${String(k).padStart(4,'0')}.webp`),scienceBase,{expectType:'image/webp'}).then(({bitmap})=>{
        require(bitmap.width===science.atlas[0]&&bitmap.height===science.atlas[1],'Unexpected F162M science atlas dimensions');item.bitmap=bitmap;return bitmap;
      });scienceCache.set(k,item);
    }
    return scienceCache.get(k).promise;
  }
  function paintScience(canvas,bitmap,sx=0){
    const ctx=canvas.getContext('2d');ctx.imageSmoothingEnabled=false;
    ctx.drawImage(bitmap,sx,0,science.detail,science.detail,0,0,canvas.width,canvas.height);
    const x=canvas.width*.06,y=canvas.height*.92,len=.5/science.detail_field_arcsec*canvas.width;
    ctx.strokeStyle='white';ctx.lineWidth=3;ctx.beginPath();ctx.moveTo(x,y);ctx.lineTo(x+len,y);ctx.stroke();
    ctx.fillStyle='white';ctx.font='14px sans-serif';ctx.fillText('0.5″',x,y-8);
  }
  function reference(){
    if(!scienceReference)return;
    const c=$('science-reference');paintScience(c,scienceReference,referenceMode*science.detail);
    $('science-reference-caption').textContent=referenceMode?'Observed JWST + ideal 2.2 m pupil PSF':'Observed JWST · resampled, original JWST PSF retained';
    $('science-observed').setAttribute('aria-pressed',String(referenceMode===0));$('science-ideal').setAttribute('aria-pressed',String(referenceMode===1));
  }
  async function loadScience(){
    const e=entry.scienceReplay;require(e?.schema==='ao-explorer.science-replay-entry.v1','Missing F162M science scene');
    const r=await fetchVerifiedJson({href:e.manifest,bytes:e.manifest_bytes,sha256:e.manifest_sha256,media_type:'application/json'},entryUrl);
    scienceManifest=r.value;scienceBase=r.url;require(scienceManifest.schema==='ao-explorer.science-replay-manifest.v1'&&scienceManifest.id===e.id,'F162M science identity mismatch');
    science=(await fetchVerifiedJson(scienceFile('data.json'),scienceBase)).value;
    require(science.schema==='ao-explorer.science-replay-data.v1'&&science.layout==='compact-same-field-v1'&&science.detail===80&&science.parent_replay_id===entry.ngsReplay.id,'F162M science parent mismatch');
    require(science.parent_replay_data_sha256===manifest.files['data.json'].sha256&&JSON.stringify(science.indices)===JSON.stringify(data.indices),'F162M science timestamps or source differ');
    require(science.wavelength_m===data.wavelength_m&&science.loss_frame===data.loss_frame&&science.loss_time_s===data.loss_time_s,'F162M science physics/timing mismatch');
    const rimg=await fetchVerifiedImage(scienceFile('reference.png'),scienceBase);
    require(rimg.bitmap.width===2*science.detail&&rimg.bitmap.height===science.detail,'Invalid F162M science reference');scienceReference=rimg.bitmap;reference();
    require(JSON.stringify(science.atlas)==='[240,80]','Unexpected F162M science layout');
    const field=science.detail_field_arcsec;
    $('science-field').textContent=`Every panel: ${field.toFixed(3)}″ × ${field.toFixed(3)}″; ${(science.pixel_arcsec*1000).toFixed(2)} mas per model pixel. Same accepted field, angular scale and surface-brightness transfer at every time. Source orientation retained.`;
    $('science-quality').textContent=`All ${science.checks.sampled_strehl_values} replay Strehl values and ${science.checks.saved_psf_checks} archived PSFs agree with the original records. The nine accepted static images agree within ${science.checks.approved_static_max_abs_difference_mjy_sr.toPrecision(3)} MJy/sr. No source region was reselected and no AO trajectory was rerun.`;
    require(science.source.bunit==='MJy/sr'&&science.source.pivot_wavelength_um===1.627&&science.display.fixed_for_all_frames_and_panels===true,'Scientific image units or display mismatch');
    require(science.display.min_mjy_sr===0&&science.display.max_mjy_sr===80&&science.display.softening_mjy_sr===2,'Accepted image transfer mismatch');
    for(const [name,id]of [['source-context.png','science-context'],['intensity-scale.png','science-scale']]){
      const {bitmap}=await fetchVerifiedImage(scienceFile(name),scienceBase);const canvas=$(id);canvas.width=bitmap.width;canvas.height=bitmap.height;canvas.getContext('2d').drawImage(bitmap,0,0);bitmap.close();
    }
    const q=science.source.quality,c=science.checks,diagnostic=c.saturation_diagnostic;
    require(q.display_direct_invalid_resampled_pixels===0&&q.display_sat_guard_resampled_pixels===0,'Source quality no longer matches accepted field');
    $('science-missing').textContent=`Four contributor exposures have no mapped SATURATED flag inside this field after a ${q.guard_arcsec.toFixed(3)}″ guard; no source pixel here is directly filled. The wider convolution context still includes saturated stars. Across all ${science.indices.length} image times, zeroing or doubling their supplied guarded values changes a pixel by up to ${c.saturation_context_max_change_mjy_sr.toPrecision(3)} MJy/sr. The analogous missing-context change is ${c.missing_context_max_change_mjy_sr.toPrecision(3)} MJy/sr. These tests do not bound unknown true saturated flux. The downloadable full-replay diagnostic marks ${(100*diagnostic.fraction_above_threshold).toFixed(2)}% of positions above ${diagnostic.threshold_mjy_sr.toFixed(1)} MJy/sr; it is not applied to the default view. The static quality figure uses only its three epochs.`;
    for(const [label,name]of [['Download 40 s lossless WebP','science-comparison.webp'],['Animation timing','movie-timing.json'],['Image methods','README.md'],['Source and checks','provenance.json'],['Accepted three-epoch figure','static-comparison.png'],['Three-epoch quality figure','static-quality.png'],['Calibrated cutout (FITS.gz)','source-detail.fits.gz'],['Linear output samples','linear-samples.npz'],['All-frame sensitivity results','sensitivity.json'],['All-frame sensitivity mask','saturation-sensitivity-mask.png'],['Numerical sensitivity maps','saturation-sensitivity-map.npz'],['Resampled science context','scene-context.npz'],['Exposure DQ provenance','quality-extraction.json'],['Offline image exporter','exporter.py']]){
      const a=document.createElement('a');a.href=new URL(name,scienceBase);a.textContent=label;
      a.addEventListener('click',async e=>{e.preventDefault();try{const {buffer}=await fetchVerified(scienceFile(name),scienceBase);const u=URL.createObjectURL(new Blob([buffer],{type:scienceFile(name).media_type}));const link=document.createElement('a');link.href=u;link.download=name;link.click();setTimeout(()=>URL.revokeObjectURL(u),30000);}catch(error){a.textContent=`${label} unavailable: ${error.message}`;}});$('science-downloads').append(a);
    }
  }
  async function loadScienceVideo(){
    const e=entry.scienceVideo;require(e?.schema==='ao-explorer.science-video-entry.v1','No MP4 export entry');
    const r=await fetchVerifiedJson({href:e.manifest,bytes:e.manifest_bytes,sha256:e.manifest_sha256,media_type:'application/json'},entryUrl);
    const m=r.value;require(m.schema==='ao-explorer.science-video-manifest.v1'&&m.id===e.id,'MP4 identity mismatch');
    const member=name=>{require(m.files[name],`MP4 member missing: ${name}`);return {href:name,...m.files[name]};};
    const v=(await fetchVerifiedJson(member('data.json'),r.url)).value;
    require(v.schema==='ao-explorer.science-video-data.v1'&&v.parent_replay_entry.id===entry.scienceReplay.id&&v.parent_replay_entry.manifest_sha256===entry.scienceReplay.manifest_sha256,'MP4 parent mismatch');
    require(v.parent_movie_sha256===scienceManifest.files['science-comparison.webp'].sha256&&v.parent_scene_data_sha256===scienceManifest.files['data.json'].sha256,'MP4 source mismatch');
    require(JSON.stringify(v.source_indices)===JSON.stringify(science.indices)&&v.loss_frame===data.loss_frame&&v.loss_time_s===data.loss_time_s&&v.duration_s===40&&v.fps===60&&v.video_frames===2400&&JSON.stringify(v.dimensions)==='[1280,720]'&&v.simulation_rerun===false&&v.temporal_interpolation===false,'MP4 timing mismatch');
    const p=$('science-video');p.textContent='Share this comparison: ';
    for(const [label,name] of [[`Download MP4 · 40 s · ${(m.files['westerlund2-f162m-2p2m-ao-comparison.mp4'].bytes/1e6).toFixed(1)} MB`,'westerlund2-f162m-2p2m-ao-comparison.mp4'],['Video timing & checks','data.json']]){
      const a=document.createElement('a');a.href=new URL(name,r.url);a.textContent=label;
      a.addEventListener('click',async event=>{event.preventDefault();try{const {buffer}=await fetchVerified(member(name),r.url);const u=URL.createObjectURL(new Blob([buffer],{type:member(name).media_type}));const link=document.createElement('a');link.href=u;link.download=name;link.click();setTimeout(()=>URL.revokeObjectURL(u),30000);}catch(error){a.textContent=`${label} unavailable: ${error.message}`;}});
      p.append(a,document.createTextNode(' · '));
    }
    p.append(document.createTextNode('H.264, 1280 × 720, 60 fps, no audio. Existing images are held without interpolation.'));
  }
  function chart(){
    if(!data)return;
    const k=data.indices[index],m=data.metrics;
    $('strehl').dataset.frame=String(k);
    lineChart($('strehl'),{title:'2.2 m instantaneous H-band Strehl; v1 loss of lock at 0.981333 s',height:260,
      x:{label:'Frame-start time',unit:'s',range:[0,2]},y:{label:'Peak Strehl',range:[0,1]},
      shadeX:[[0,.2,'startup exclusion'],[data.loss_time_s,2,'v1 reconstruction unusable']],
      verticalLines:[{x:data.loss_time_s,color:'#a3324e',label:'v1 loss · 0.981333 s'}],cursorX:m.time_s[k],
      series:[{label:'Original v1',color:'#b3541e',points:m.v1.strehl.map((v,i)=>[m.time_s[i],v])},
        {label:'Revised v2',color:'#4d7a2a',points:m.v2.strehl.map((v,i)=>[m.time_s[i],v])},
        {label:'Uncorrected',color:'#7d7d7d',style:'dashed',points:m.uncorrected_strehl.map((v,i)=>[m.time_s[i],v])}]});
  }
  function labels(){
    const k=data.indices[index],m=data.metrics,t=m.time_s[k];
    $('seek').value=index;$('seek').setAttribute('aria-valuetext',`Frame ${k}, ${t.toFixed(6)} seconds, sample ${index+1} of ${data.indices.length}`);
    $('readout').textContent=`Frame ${k} / 1499 · ${t.toFixed(6)} s / 2.000 s · snapshot ${index+1}/${data.indices.length} · ${k<150?'startup exclusion':'analysis window'}`;
    $('readout').dataset.frame=String(k);
    $('science-time').textContent=`${t.toFixed(6)} s · frame ${k} · ${k>=736?'v1 reconstruction rejected':'before first v1 rejection'}`;
    $('science-time').dataset.frame=String(k);
    $('event').textContent=k<data.loss_frame
      ? `Before v1's first rejected reconstruction (${((data.loss_time_s-t)*1000).toFixed(3)} ms before frame 736).`
      : k===data.loss_frame?'Loss marker: frame 736 is v1’s first rejected reconstruction; v2 remains usable.'
      : `After v1’s first rejected reconstruction (${((t-data.loss_time_s)*1000).toFixed(3)} ms later). V1 continues to be displayed, including its failed frames.`;
    $('event').dataset.phase=k<data.loss_frame?'before':k===data.loss_frame?'loss':'after';
    $('atmosphere-caption').textContent=`Shared atmosphere · RMS ${m.atmosphere_rms_nm[k].toFixed(1)} nm`;
    $('psf-u-caption').textContent=`Uncorrected · Strehl ${m.uncorrected_strehl[k].toFixed(4)}`;
    for(const id of ['v1','v2']){
      const v=m[id];
      $(`residual-${id}-caption`).textContent=`${id==='v1'?'Original v1':'Revised v2'} residual · RMS ${v.rms_nm[k].toFixed(1)} nm`;
      $(`psf-${id}-caption`).textContent=`${id==='v1'?'Original v1':'Revised v2'} PSF · Strehl ${v.strehl[k].toFixed(4)}`;
      $(`valid-${id}`).textContent=`${id==='v1'?'Original v1':'Revised v2'}: ${v.usable[k]?'usable reconstruction':'reconstruction rejected'} · ${(v.valid_fraction[k]*100).toFixed(2)}% valid rows`;
    }
    const until=index+1<data.indices.length?m.time_s[data.indices[index+1]]:2;
    $('timing').textContent=`One pass: ${duration} s (${duration/2}× slower). This snapshot is held to ${until.toFixed(6)} s of recorded time. No interpolation; loading or background tabs may extend playback.`;
    $('status').textContent='';
    $('science-u-caption').textContent=`No correction · point-source Strehl ${m.uncorrected_strehl[k].toFixed(4)}`;
    for(const id of ['v1','v2'])$(`science-${id}-caption`).textContent=`${id==='v1'?'Original v1':'Revised v2'} · point-source Strehl ${m[id].strehl[k].toFixed(4)}`;
    $('previous').disabled=index===0;$('next').disabled=index===data.indices.length-1;
  }
  async function show(next){
    if(failed||!data)return false;
    next=Math.max(0,Math.min(data.indices.length-1,next));
    const token=++ticket,k=data.indices[next];requested=k;busy=true;
    $('seek').value=index;
    // Keep short frame fetches quiet; the status row always reserves its space.
    const loadingNotice=setTimeout(()=>{
      if(token===ticket)$('status').textContent='Loading frame…';
    },250);
    try{
      const [bitmap,scene]=await Promise.all([atlas(k),scienceAtlas(k)]);
      if(token!==ticket)return false;
      // One atlas prevents mixed-frame before/after images, even on fast seeks.
      roles.forEach((role,n)=>{const c=$(role);c.getContext('2d').drawImage(bitmap,n*data.tile,0,data.tile,data.tile,0,0,c.width,c.height);c.dataset.frame=String(k);});
      ['u','v1','v2'].forEach((role,n)=>{const c=$(`science-${role}`);paintScience(c,scene,n*science.detail);c.dataset.frame=String(k);});
      index=next;labels();chart();trim();
      document.dispatchEvent(new CustomEvent('ao:ngs-frame', {detail: {frame:k}}));
      for(const [key,item] of scienceCache){if(scienceCache.size<=12)break;if(item.bitmap&&key!==k){item.bitmap.close();scienceCache.delete(key);}}
      return true;
    }catch(error){if(token===ticket)fail(error);return false;}
    finally{clearTimeout(loadingNotice);if(token===ticket)busy=false;}
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
    playing=true;$('play').textContent='Pause';$('play').setAttribute('aria-pressed','true');$('science-play').textContent='Pause';$('science-play').setAttribute('aria-pressed','true');schedule();
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
      await loadScience();
      loadScienceVideo().catch(error=>{$('science-video').textContent=`MP4 download unavailable: ${error.message}`;});
      index=data.indices.indexOf(1499);require(index>=0,'Missing final frame');
      $('seek').max=data.indices.length-1;$('duration').value=String(duration);bars();
      root.querySelectorAll('button,input,select').forEach(e=>e.disabled=false);
      $('sampling').textContent=`${data.indices.length} existing wavefront snapshots: every 12th frame, all archived PSF snapshot times, and every frame 720–752 around loss of lock. The curves show all 1500 saved measurements. Both runs always show the same timestamp.`;
      for(const [label,name] of [['All replay metrics','data.json'],['Replay provenance and checks','provenance.json'],['Replay methods','README.md'],['Offline exporter','exporter.py']])download(label,name);
      await show(index);redrawWhenResized($('strehl'),chart);
    })();return loading;
  }
  $('science-observed').addEventListener('click',()=>{referenceMode=0;reference();});
  $('science-ideal').addEventListener('click',()=>{referenceMode=1;reference();});
  $('science-play').addEventListener('click',()=>{toggle().catch(fail);});
  $('science-before').addEventListener('click',()=>seek(data.indices.indexOf(735)));
  $('science-loss').addEventListener('click',()=>seek(data.indices.indexOf(736)));
  $('science-late').addEventListener('click',()=>seek(data.indices.indexOf(1499)));
  $('play').addEventListener('click',()=>{toggle().catch(fail);});
  $('previous').addEventListener('click',()=>seek(index-1));$('next').addEventListener('click',()=>seek(index+1));
  $('restart').addEventListener('click',()=>seek(0));$('seek').addEventListener('input',e=>seek(Number(e.target.value)));
  for(const [id,k] of [['before',735],['loss',736],['after',737],['late',1499]])$(id).addEventListener('click',()=>seek(data.indices.indexOf(k)));
  $('duration').addEventListener('change',()=>{duration=Number($('duration').value);labels();schedule();});
  document.addEventListener('visibilitychange',()=>{if(document.hidden)pause();});
  document.addEventListener('ao:viewchange', pause);
  document.addEventListener('ao:ngs-pause', pause);
  const open=()=>load().catch(fail);
  if('IntersectionObserver' in window){const o=new IntersectionObserver(entries=>{if(entries.some(e=>e.isIntersecting)){o.disconnect();open();}},{rootMargin:'200px'});o.observe(root);}else open();
  window.addEventListener('hashchange',()=>{if(['#ngs22-replay','#ngs22-science','#ngs22-ngc602','#ngs22-orion'].includes(location.hash))open();});
  if(['#ngs22-replay','#ngs22-science','#ngs22-ngc602','#ngs22-orion'].includes(location.hash))open();
}

// Native telemetry has its own frame selector: it includes every recorded frame,
// whereas the image player above contains a documented subset of snapshots.
export function initNgsControl(entry, entryUrl) {
  const root=document.getElementById('ngs22-control');
  if(!root)return;
  const $=name=>document.getElementById(`ngsc-${name}`);
  let data,manifest,base,loading,frame=736,view='focus';
  const names={v1:'Original v1',v2:'Revised v2'},colors={v1:'#b3541e',v2:'#4d7a2a'};
  const members=name=>{require(manifest.files[name],`Control member missing: ${name}`);return {href:name,...manifest.files[name]};};
  const limits=()=>view==='focus'?[690,780]:[0,1499];
  const fail=error=>{
    $('error').hidden=false;$('error').textContent=`Control timeline unavailable: ${error.message}. Reload to retry.`;
    $('status').textContent='Saved telemetry could not be verified.';
    root.querySelectorAll('button,input').forEach(x=>x.disabled=true);
  };
  function plot(id,key,transform,y,extra={}) {
    const range=view==='focus'?data.focus_interval_s:data.full_interval_s;
    const [lo,hi]=limits();
    lineChart($(id),{title:`${id} at native telemetry frame ${frame}`,height:190,
      x:{label:'Frame-start time',unit:'s',range},y,
      verticalLines:[{x:data.loss_time_s,color:'#a3324e',label:'v1 rejection'}],
      cursorX:data.time_s[frame],
      series:Object.keys(names).map(run=>({label:names[run],color:colors[run],
        points:data.time_s.slice(lo,hi+1).map((t,j)=>{
          const value=data.runs[run][key][lo+j];return [t,value===null?null:transform(value)];
        })})),...extra});
    $(id).dataset.frame=String(frame);
  }
  function charts() {
    if(!data)return;
    plot('valid','valid_rows',n=>100*n/data.calibrated_rows,{label:'Valid rows',unit:'%',range:[0,100]},
      {referenceLines:[{y:75,label:'75% gate'}]});
    const max=Math.max(...Object.values(data.runs).flatMap(r=>r.increment_l2_um.filter(v=>v!==null)));
    plot('increment','increment_l2_um',v=>v,{label:'Increment L2',unit:'µm OPD',range:[0,Math.ceil(max/5)*5]});
    const bound=Math.max(...Object.values(data.runs).flatMap(r=>r.held_boundary_actuators));
    plot('boundary','held_boundary_actuators',v=>100*v/data.actuators,{label:'Held at bound',unit:'%',range:[0,Math.max(1,Math.ceil(100*bound/data.actuators))]});
    plot('strehl','strehl',v=>v,{label:'Peak Strehl',range:[0,1]});
  }
  function show(k=frame, follow=false) {
    if(!data)return;
    if(!follow)document.dispatchEvent(new Event('ao:ngs-pause'));
    const [lo,hi]=limits();frame=Math.max(lo,Math.min(hi,k));
    $('seek').min=lo;$('seek').max=hi;$('seek').value=frame;
    $('seek').setAttribute('aria-valuetext',`Frame ${frame}, ${data.time_s[frame].toFixed(6)} seconds`);
    $('previous').disabled=frame===lo;$('next').disabled=frame===hi;
    $('focus').setAttribute('aria-pressed',String(view==='focus'));$('full').setAttribute('aria-pressed',String(view==='full'));
    $('readout').textContent=`Telemetry frame ${frame} / 1499 · ${data.time_s[frame].toFixed(6)} s · ${view==='focus'?'failure detail':'whole recording'} · all four cursors aligned`;
    $('readout').dataset.frame=String(frame);
    const rows=[
      ['Valid measurement rows',r=>`${r.valid_rows[frame]}/374 (${(100*r.valid_rows[frame]/374).toFixed(2)}%)`],
      ['Reconstruction',r=>r.usable[frame]?'Usable':'REJECTED — no estimate'],
      ['Reconstructed increment · vector L2',r=>r.increment_l2_um[frame]===null?'No usable estimate':`${r.increment_l2_um[frame].toFixed(3)} µm OPD`],
      ['DM held at boundary during exposure',r=>`${r.held_boundary_actuators[frame]}/197 (${(100*r.held_boundary_actuators[frame]/197).toFixed(2)}%)`],
      ['Newly clipped requests after this update',r=>`${(100*r.issued_clipped_fraction[frame]).toFixed(2)}% of actuators`],
      ['Instantaneous H-band Strehl',r=>r.strehl[frame].toFixed(4)],
    ];
    $('values').replaceChildren(...rows.map(([label,value])=>{
      const tr=document.createElement('tr');
      for(const [i,text] of [label,value(data.runs.v1),value(data.runs.v2)].entries()){
        const cell=document.createElement(i?'td':'th');if(!i)cell.scope='row';cell.textContent=text;tr.append(cell);
      }return tr;
    }));charts();
  }
  function download(label,name) {
    const a=document.createElement('a');a.textContent=label;a.href=new URL(name,base);
    a.addEventListener('click',async e=>{e.preventDefault();try{
      const {buffer}=await fetchVerified(members(name),base);
      const url=URL.createObjectURL(new Blob([buffer],{type:members(name).media_type}));
      const link=document.createElement('a');link.href=url;link.download=name;link.click();setTimeout(()=>URL.revokeObjectURL(url),30000);
    }catch(error){a.textContent=`${label} unavailable: ${error.message}`;}});$('downloads').append(a);
  }
  async function load() {
    if(loading)return loading;
    loading=(async()=>{
      const e=entry.ngsControl;require(e?.schema==='ao-explorer.ngs-control-entry.v1','Missing control entry');
      const m=await fetchVerifiedJson({href:e.manifest,bytes:e.manifest_bytes,sha256:e.manifest_sha256,media_type:'application/json'},entryUrl);
      manifest=m.value;base=m.url;require(manifest.schema==='ao-explorer.ngs-control-manifest.v1'&&manifest.id===e.id,'Control identity mismatch');
      data=(await fetchVerifiedJson(members('data.json'),base)).value;
      require(data.schema==='ao-explorer.ngs-control-data.v1'&&data.frames===1500&&data.frame_rate_hz===750&&data.calibrated_rows===374&&data.actuators===197&&data.minimum_valid_fraction===.75,'Unexpected control contract');
      require(data.time_s?.length===1500&&data.time_s.every((v,i)=>Number.isFinite(v)&&Math.abs(v-i/750)<1e-12),'Control time axis mismatch');
      require(data.loss_frame===736&&data.loss_time_s===data.time_s[736]&&JSON.stringify(data.focus_interval_s)==='[0.92,1.04]'&&JSON.stringify(data.full_interval_s)==='[0,2]','Control interval mismatch');
      for(const run of ['v1','v2']){
        const r=data.runs[run];
        for(const key of ['valid_rows','held_boundary_actuators','issued_clipped_fraction','strehl'])require(r[key]?.length===1500&&r[key].every(Number.isFinite),`Incomplete ${run} ${key}`);
        require(r.usable?.length===1500&&r.usable.every((v,i)=>typeof v==='boolean'&&v===(r.valid_rows[i]/374>=.75)),`Invalid ${run} reconstruction mask`);
        require(r.increment_l2_um?.length===1500&&r.increment_l2_um.every((v,i)=>r.usable[i]?Number.isFinite(v)&&v>=0:v===null),`Invalid ${run} rejected-increment gaps`);
        require(r.valid_rows.every(v=>Number.isInteger(v)&&v>=0&&v<=374)&&r.held_boundary_actuators.every(v=>Number.isInteger(v)&&v>=0&&v<=197),`Invalid ${run} counts`);
        require(r.issued_clipped_fraction.every(v=>v>=0&&v<=1)&&r.strehl.every(v=>v>=0&&v<=1+1e-12),`Invalid ${run} bounded metric`);
      }
      require(data.runs.v1.usable.findIndex(v=>!v)===736&&data.runs.v2.usable.every(v=>v)&&data.runs.v1.held_boundary_actuators.slice(736,739).join(',')==='8,11,8','Control event mismatch');
      root.querySelectorAll('button,input').forEach(x=>x.disabled=false);show();
      for(const id of ['valid','increment','boundary','strehl'])redrawWhenResized($(id),charts);
      for(const [label,name] of [['All 3000 telemetry rows (CSV)','frames.csv'],['Native arrays (JSON)','data.json'],['Timing and definitions','README.md'],['Source identities and checks','provenance.json'],['Offline exporter','exporter.py']])download(label,name);
      $('status').textContent='';
    })();return loading;
  }
  $('seek').addEventListener('input',e=>show(Number(e.target.value)));
  $('previous').addEventListener('click',()=>show(frame-1));$('next').addEventListener('click',()=>show(frame+1));
  for(const [id,k] of [['growth',732],['loss',736],['held',738]])$(id).addEventListener('click',()=>show(k));
  for(const mode of ['focus','full'])$(mode).addEventListener('click',()=>{view=mode;const [lo,hi]=limits();show(frame<lo||frame>hi?736:frame);});
  function followImage(k) {
    if(!data)return;
    const [lo,hi]=limits();
    if(k<lo||k>hi)view='full';
    show(k,true);
  }
  document.addEventListener('ao:ngs-frame', event=>followImage(event.detail.frame));
  $('follow').addEventListener('click',()=>followImage(Number(document.getElementById('ngsr-readout').dataset.frame)));
  const open=()=>load().then(()=>{const k=document.getElementById('ngsr-readout').dataset.frame;if(k!==undefined)followImage(Number(k));}).catch(fail);
  if('IntersectionObserver' in window){const observer=new IntersectionObserver(es=>{if(es.some(e=>e.isIntersecting)){observer.disconnect();open();}},{rootMargin:'200px'});observer.observe(root);}else open();
  window.addEventListener('hashchange',()=>{if(location.hash==='#ngs22-control')open();});
  if(location.hash==='#ngs22-control')open();
}
