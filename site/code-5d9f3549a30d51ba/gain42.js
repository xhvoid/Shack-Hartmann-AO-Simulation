// Twelve accepted gain/delay records. Only saved traces and configuration
// selectors are used; no gain interpolation or simulation runs in this view.
import { require } from './integrity.js';
import { lineChart, redrawWhenResized } from './charts.js';
import { addDownloads, agrees, frameInspector, loadStudy, series, signed, tableRows, windowMean } from './studies42.js';

const ANALYSIS = '0ec6a0375a150c84db1ec9058f82dba030a5840b04a1a3900a94ed93d39a13be';
const METRICS = {
  mean_pre_update_rms_nm: { label: 'Mean pre-update residual RMS', unit: 'nm', digits: 2, better: 'Lower is better' },
  peak_strehl: { label: 'Peak Strehl of the mean PSF', unit: 'dimensionless', digits: 4, better: 'Higher is better' },
  fourier_ee50_lambda_over_d: { label: 'Fourier EE50 radius', unit: 'λ/D', digits: 3, better: 'Lower is better' },
};
const EFFECTS = { G_L2: 'Gain 0.2 − 0.3 · delay 2', G_L3: 'Gain 0.2 − 0.3 · delay 3',
  'D_g0.2': 'Delay 3 − 2 · gain 0.2', 'D_g0.3': 'Delay 3 − 2 · gain 0.3', I: 'Interaction: D(0.2) − D(0.3)' };
const COLOUR = { '0.3': '#1f5f73', '0.2': '#b3541e' };
const T = Math.sqrt(2 * .95 ** 2 / (1 - .95 ** 2));
const finite = (v) => typeof v === 'number' && Number.isFinite(v);
const paired = (v) => {
  require(v.length === 3 && v.every(finite), 'Three finite realization values required');
  const mean = v.reduce((s, x) => s + x, 0) / 3;
  const sd = Math.sqrt(v.reduce((s, x) => s + (x - mean) ** 2, 0) / 2), h = T * sd / Math.sqrt(3);
  return { mean, sd, ci95: [mean - h, mean + h] };
};
const sum = (r) => ({ primary_mean_nm: windowMean(r.residual_nm, [100, 500]),
  early_mean_nm: windowMean(r.residual_nm, [100, 300]), late_mean_nm: windowMean(r.residual_nm, [300, 500]),
  final_block_mean_nm: windowMean(r.residual_nm, [400, 500]), final50_mean_nm: windowMean(r.residual_nm, [450, 500]),
  late_minus_early_nm: windowMean(r.residual_nm, [300, 500]) - windowMean(r.residual_nm, [100, 300]),
  frames_valid_below_0_995: r.valid_fraction.slice(100).filter(v => v < .995).length,
  valid_min: Math.min(...r.valid_fraction.slice(100)), valid_min_frame: 100 + r.valid_fraction.slice(100).indexOf(Math.min(...r.valid_fraction.slice(100))) });

export function validateGain42(d) {
  require(d?.schema === 'ao-explorer.gain42-data.v1', 'Unsupported gain study');
  const settings = { gains: [.2,.3], delays: [2,3], realizations: [0,1,2], frames: 500, frame_rate_hz: 500,
    flux_e_per_full_subap_frame: 100000, noise: true, noise_policy: 'native scoped', root_seed: 1, leak: 0,
    damping: .001, science_wavelength_m: 2.2e-6, psf_padding: 2 };
  for (const [k,v] of Object.entries(settings)) require(JSON.stringify(d.settings?.[k]) === JSON.stringify(v), `Wrong study setting ${k}`);
  require(JSON.stringify(d.windows) === JSON.stringify({ primary:[100,500], early:[100,300], late:[300,500], final_block:[400,500], final50:[450,500] }), 'Wrong analysis windows');
  require(Array.isArray(d.records) && d.records.length === 12, 'Exactly twelve records required');
  const records = new Map(), atmospheres = new Map();
  for (const r of d.records) {
    require([.2,.3].includes(r.gain) && [2,3].includes(r.delay) && [0,1,2].includes(r.realization), 'Wrong recorded configuration');
    const key = `${r.gain}:${r.delay}:${r.realization}`;
    require(!records.has(key), 'Duplicate recorded configuration'); records.set(key,r);
    const expected = r.gain === .2 ? `g020-lat${r.delay}-flux100000-r${r.realization}` : r.delay === 2 ? `flux100000-r${r.realization}` : `lat3-flux100000-r${r.realization}`;
    require(r.run_key === expected && r.source === (r.gain === .2 ? 'new' : 'reused'), 'Wrong record identity or origin');
    require(r.attempt === (key === '0.3:3:2' ? 2 : 1), 'Wrong accepted baseline attempt');
    series(r.residual_nm,500,'Residual',{positive:true}); series(r.valid_fraction,500,'Validity',{fraction:true});
    for (const [k,v] of Object.entries(sum(r))) require(agrees(v,r.history_summary?.[k]) && (!['frames_valid_below_0_995','valid_min_frame'].includes(k) || Number.isInteger(r.history_summary[k])), `History summary mismatch: ${k}`);
    for (const k of Object.keys(METRICS)) require(finite(r.metrics?.[k]) && r.metrics[k] > 0, 'Missing primary metric');
    require(agrees(r.metrics.mean_pre_update_rms_nm,r.history_summary.primary_mean_nm), 'Primary residual mismatch');
    require(r.image_provenance?.analysis_sha256 === ANALYSIS, 'Image provenance mismatch');
    const p=r.pairing, keys=['pupil_chain','map_chain','pupil_mask','atmosphere_stream','noise_scope','open_loop_sha256'];
    require(p && keys.every(k => typeof p[k] === 'string' && p[k].length > 0), 'Missing pairing identity');
    const signature=JSON.stringify(keys.map(k=>p[k]));
    if (atmospheres.has(r.realization)) require(atmospheres.get(r.realization)===signature, 'Atmospheric pairing mismatch');
    else atmospheres.set(r.realization,signature);
    const w=r.windowed_images;
    if (r.gain===.3) require(w?.status==='unavailable' && w.values===null && typeof w.reason==='string', 'Baseline windowed images must be unavailable');
    else {
      require(w?.status==='available' && w.analysis_sha256===ANALYSIS && Object.keys(w.values).sort().join(',')==='100_300,300_400,400_500', 'Missing new-run image summary');
      for (const [key,q] of Object.entries(w.values)) require(finite(q.peak_strehl) && q.peak_strehl>0 && q.peak_strehl<=1 && q.samples===(key==='100_300'?200:100) && typeof q.intensity_sha256==='string' && q.intensity_sha256.length===64, 'Invalid windowed image summary');
    }
  }
  require(new Set(atmospheres.values()).size===3, 'Realizations must be distinct');
  const at=(g,l,z)=>records.get(`${g}:${l}:${z}`);
  for (const metric of Object.keys(METRICS)) {
    const val=(g,l,z)=>at(g,l,z).metrics[metric];
    const effects={};
    for (const g of [.2,.3]) for (const l of [2,3]) {
      const values=[0,1,2].map(z=>val(g,l,z)), q=d.levels?.[metric]?.[`g${g}-L${l}`], computed=paired(values);
      require(q && q.by_realization.length===3 && values.every((v,i)=>agrees(v,q.by_realization[i])) && agrees(computed.mean,q.mean), 'Cell summary mismatch');
    }
    for (const l of [2,3]) effects[`G_L${l}`]=[0,1,2].map(z=>val(.2,l,z)-val(.3,l,z));
    for (const g of [.2,.3]) effects[`D_g${g}`]=[0,1,2].map(z=>val(g,3,z)-val(g,2,z));
    effects.I=[0,1,2].map(z=>effects['D_g0.2'][z]-effects['D_g0.3'][z]);
    for (const [key,values] of Object.entries(effects)) {
      const p=paired(values), q=d.contrasts?.[metric]?.[key];
      require(q && q.df===2 && q.by_realization.length===3 && values.every((v,i)=>agrees(v,q.by_realization[i])) && agrees(p.mean,q.mean) && agrees(p.sd,q.sample_sd) && q.ci95.length===2 && p.ci95.every((v,i)=>agrees(v,q.ci95[i])), `Paired contrast/interval mismatch: ${metric} ${key}`);
    }
  }
  return records;
}

const svg=(tag,attrs={},text)=>{
  const e=document.createElementNS('http://www.w3.org/2000/svg',tag);
  for(const [k,v]of Object.entries(attrs))e.setAttribute(k,v);
  if(text!==undefined)e.textContent=text;return e;
};
function marker(r,x,y,c) {
  if(r===0)return svg('circle',{cx:x,cy:y,r:4.5,fill:c});
  if(r===1)return svg('rect',{x:x-4,y:y-4,width:8,height:8,fill:c});
  return svg('path',{d:`M ${x} ${y-5} L ${x+5} ${y+4} L ${x-5} ${y+4} Z`,fill:c});
}

export function initGain42(entry,entryUrl) {
  const root=document.getElementById('gain42');if(!root)return;
  const node=n=>document.getElementById(`gain42-${n}`);
  let bundle,data,records,ready,metric='peak_strehl',delay=3,realization=2,frame=344,range='post',imageGain=.3;
  const record=g=>records.get(`${g}:${delay}:${realization}`);
  const first=()=>range==='full'?0:100;
  function plots() {
    const m=METRICS[metric];node('metric-note').textContent=`${m.label} · ${m.unit}. ${m.better}. Dots: ● r0, ■ r1, ▲ r2. The short vertical stroke marks the mean.`;
    const whole=[.3,.2].flatMap(g=>[2,3].map(l=>({label:`Gain ${g} · delay ${l}`,q:data.levels[metric][`g${g}-L${l}`],colour:COLOUR[g]})));
    const pairedRows=Object.entries(EFFECTS).map(([key,label],i)=>({label,key,q:data.contrasts[metric][key],colour:['#1f5f73','#a3324e','#b3541e','#1f5f73','#6b5aa6'][i]}));
    function plot(container,rows,intervals) {
      const W=Math.max(280,Math.min(850,container.clientWidth||800)),narrow=W<600,L=narrow?22:230,R=25,step=narrow?91:65,top=15,H=top+rows.length*step+45;
      const values=rows.flatMap(r=>[...r.q.by_realization,...(intervals?r.q.ci95:[])]);
      let lo=Math.min(...values,...(intervals?[0]:[])),hi=Math.max(...values,...(intervals?[0]:[]));
      const pad=(hi-lo||1)*.1;lo-=pad;hi+=pad;
      const sx=v=>L+(W-L-R)*(v-lo)/(hi-lo),bottom=top+rows.length*step;
      const chart=svg('svg',{viewBox:`0 0 ${W} ${H}`,width:W,height:H,role:'img','aria-label':`${intervals?'Paired contrasts and exploratory 95% intervals':'All three realization values'} for ${m.label}, ${m.unit}. Exact values are in the adjacent table.`});
      for(let i=0;i<5;i++){
        const v=lo+(hi-lo)*i/4,x=sx(v);
        chart.append(svg('line',{x1:x,x2:x,y1:top,y2:bottom,stroke:'#e6e2da'}));
        chart.append(svg('text',{x,y:bottom+18,'text-anchor':'middle',class:'d42-tick'},v.toFixed(metric==='peak_strehl'?3:metric==='mean_pre_update_rms_nm'?1:2)));
      }
      if(intervals)chart.append(svg('line',{x1:sx(0),x2:sx(0),y1:top,y2:bottom,stroke:'#23262a','stroke-width':1.5,'stroke-dasharray':'5 4','data-zero':'true'}));
      rows.forEach((r,i)=>{
        const y=top+i*step+(narrow?53:31);
        if(narrow)chart.append(svg('rect',{x:L-3,y:y-44,width:W-L-R+6,height:18,fill:'#fff'}));
        chart.append(svg('text',{x:narrow?L:L-12,y:narrow?y-31:y+4,'text-anchor':narrow?'start':'end',class:'d42-label'},r.label));
        if(intervals) {
          chart.append(svg('line',{x1:sx(r.q.ci95[0]),x2:sx(r.q.ci95[1]),y1:y,y2:y,stroke:r.colour,'stroke-width':6,'stroke-opacity':.28,'data-interval':r.key}));
          for(const v of r.q.ci95)chart.append(svg('line',{x1:sx(v),x2:sx(v),y1:y-5,y2:y+5,stroke:r.colour}));
        }
        chart.append(svg('line',{x1:sx(r.q.mean),x2:sx(r.q.mean),y1:y-22,y2:y+22,stroke:r.colour,'stroke-width':2}));
        r.q.by_realization.forEach((v,z)=>chart.append(marker(z,sx(v),y+(z-1)*14,r.colour)));
      });
      chart.append(svg('text',{x:(L+W-R)/2,y:H-5,'text-anchor':'middle',class:'d42-tick'},`${intervals?'Paired change · ':''}${m.unit}`));container.replaceChildren(chart);
    }
    plot(node('whole-plot'),whole,false);plot(node('contrasts-plot'),pairedRows,true);
    tableRows(node('contrasts-body'),pairedRows.map(({key,label,q})=>[label,...q.by_realization.map(v=>signed(v,m.digits)),signed(q.mean,m.digits),`[${q.ci95.map(v=>signed(v,m.digits)).join(', ')}]`,q.ci95[0]<=0&&q.ci95[1]>=0?'Includes zero':'Excludes zero']));
    node('contrasts-caption').textContent=`${m.label} (${m.unit}) · three paired realizations · exploratory 95% Student t intervals, df 2`;
  }
  function traces() {
    const start=first(),rms=[],valid=[];
    for(const r of data.records){rms.push(...r.residual_nm.slice(start));valid.push(...r.valid_fraction.slice(start));}
    const lo=Math.min(...rms),hi=Math.max(...rms),span=hi-lo;
    const shade=range==='full'?[[0,.2,'startup (excluded)']]:[];
    const common={x:{label:'Simulated time',unit:'s',range:[start/500,499/500]},shadeX:shade,
      verticalLines:[{x:.6,label:'early → late',color:'#7d7d7d',row:1}],cursorX:frame/500,cursorLabel:`frame ${frame}`};
    const points=values=>values.slice(start).map((v,i)=>[(start+i)/500,v]);
    node('rms').studiesMap=lineChart(node('rms'),{...common,title:`Residual RMS · r${realization} · configured queue delay ${delay}`,height:250,
      y:{label:'Pre-update residual RMS',unit:'nm',range:[lo-.04*span,hi+.15*span]},series:[.3,.2].map(g=>({label:`Gain ${g}`,color:COLOUR[g],points:points(record(g).residual_nm)}))});
    node('valid').studiesMap=lineChart(node('valid'),{...common,cursorLabel:null,verticalLines:[{x:.6}],title:'Valid-measurement fraction',height:180,
      y:{label:'Valid fraction',range:[Math.min(...valid,.995)-.002,1.006]},referenceLines:[{y:.995}],series:[.3,.2].map(g=>({label:`Gain ${g}`,color:COLOUR[g],points:points(record(g).valid_fraction)}))});
  }
  function describe(k) {return [`r${realization} · configured delay ${delay} · frame ${k} · ${(k/500).toFixed(3)} s${k<100?' · startup excluded':''}`,...[.3,.2].map(g=>`Gain ${g}: ${record(g).residual_nm[k].toFixed(3)} nm; valid ${record(g).valid_fraction[k].toFixed(6)}`)];}
  function setFrame(k,announce=false) {frame=k;node('frame').value=k;node('frame').setAttribute('aria-valuetext',describe(k).join('. '));node('readout').textContent=describe(k).join(' · ');if(announce)node('live').textContent=node('readout').textContent;traces();}
  function late() {
    tableRows(node('late-body'),[.3,.2].map(g=>{const s=record(g).history_summary;return [`Gain ${g}`,...['early_mean_nm','late_mean_nm','final_block_mean_nm','final50_mean_nm','late_minus_early_nm'].map(k=>s[k].toFixed(4)),`${s.frames_valid_below_0_995}`,`${s.valid_min.toFixed(6)} · frame ${s.valid_min_frame}`];}));
    node('late-caption').textContent=`r${realization} · configured controller queue delay ${delay} · residual values in nm; validity count over [100,500)`;
    const w=record(imageGain).windowed_images;
    node('window-status').textContent=w.status==='unavailable'?w.reason:'Available only for the six new gain-0.2 runs. Accepted hash-bound analysis and diagnostic summaries; large image arrays were omitted and were not independently recalculated for this display.';
    tableRows(node('window-body'),['100_300','300_400','400_500'].map(k=>[k.replace('_','–')+' (half-open)',w.status==='available'?w.values[k].peak_strehl.toFixed(6):'Unavailable',w.status==='available'?`${w.values[k].samples}`:'Not recorded']));
    setFrame(frame);
  }
  function enable() {
    for(const input of root.querySelectorAll('select,input'))input.disabled=false;
    node('metric').addEventListener('change',()=>{metric=node('metric').value;plots();});
    for(const n of ['delay','realization','image-gain','range'])node(n).addEventListener('change',()=>{
      delay=Number(node('delay').value);realization=Number(node('realization').value);imageGain=Number(node('image-gain').value);range=node('range').value;
      node('frame').min=first();frame=Math.max(frame,first());late();
    });
    node('show-r2').disabled=false;node('show-r2').addEventListener('click',()=>{delay=3;realization=2;node('delay').value='3';node('realization').value='2';late();node('rms').scrollIntoView({block:'center'});node('delay').focus({preventScroll:true});});
    frameInspector({canvases:[node('rms'),node('valid')],slider:node('frame'),rate:500,firstFrame:first,lastFrame:()=>499,describe,onFrame:setFrame});
    for(const c of [node('rms'),node('valid')])redrawWhenResized(c,traces);
    let width=0;new ResizeObserver(()=>{const w=node('whole-plot').clientWidth;if(Math.abs(w-width)>8){width=w;plots();}}).observe(node('whole-plot'));
  }
  async function load() {
    if(ready)return ready;
    ready=(async()=>{
      bundle=await loadStudy(entry,'gain42',{entry:'ao-explorer.gain42-entry.v1',manifest:'ao-explorer.gain42-manifest.v1'},entryUrl);
      require(bundle,'Missing required gain study bundle');records=validateGain42(bundle.data);data=bundle.data;
      // Nothing containing scientific values is exposed until all checks pass.
      node('content').hidden=false;
      tableRows(node('whole-body'),data.records.map(r=>[`${r.gain}`,`${r.delay}`,`r${r.realization}`,`${r.source}${r.attempt===2?' · attempt 2':''}`,...Object.keys(METRICS).map(k=>r.metrics[k].toFixed(METRICS[k].digits))]));
      plots();late();enable();
      node('identity').textContent=`Bundle ${bundle.id}. Scientific producer ${data.source.producer_commit}. Analysis ${ANALYSIS}. Evidence closing addendum ${data.source.closing_addendum}.`;
      addDownloads(node('downloads'),bundle,[['Methods and limitations','README.md'],['GL-R01 / GL-R02 corrections','CORRECTIONS.md'],['All display values','data.json'],['Recorded traces (CSV)','frames.csv'],['Source identities and hashes','provenance.json'],['Offline exporter','exporter.py']]);
      node('status').textContent='Twelve records verified: six new, six reused. Residual summaries and paired statistics agree with the saved values.';
    })().catch(error=>{
      node('content').hidden=true;node('error').hidden=false;node('error').textContent=`Gain–delay study unavailable: ${error.message}. No values from this study are shown. Reload to retry.`;node('status').textContent='The gain–delay records could not be verified.';
      for(const e of root.querySelectorAll('input,select,button'))e.disabled=true;
    });return ready;
  }
  if('IntersectionObserver'in window){const o=new IntersectionObserver(items=>{if(items.some(i=>i.isIntersecting)){o.disconnect();load();}},{rootMargin:'200px'});o.observe(root);}else load();
  if(location.hash.startsWith('#gain42'))load();
}
