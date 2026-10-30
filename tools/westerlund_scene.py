"""Replay the approved Westerlund 2 cutout using archived OPDs, without an AO run."""
from __future__ import annotations
import argparse, hashlib, json, shutil
from pathlib import Path
import numpy as np
from scipy import fft
from PIL import Image, ImageDraw, ImageFont
from matplotlib import colormaps, get_data_path

WAVELENGTH=1.65e-6
N=80
LO,HI,SOFT=0.,80.,2.
LUT=np.uint8(colormaps['magma'](np.linspace(0,1,256))[...,:3]*255)

def read(p):return json.loads(p.read_text())
def write(p,x):p.write_text(json.dumps(x,indent=2,allow_nan=False)+'\n')
def sha(p):
 h=hashlib.sha256()
 with p.open('rb') as f:
  for b in iter(lambda:f.read(8*1024**2),b''):h.update(b)
 return h.hexdigest()
def meta(p):return {'bytes':p.stat().st_size,'sha256':sha(p)}
def checked(p,m):assert meta(p)=={k:m[k]for k in ['bytes','sha256']},str(p);return p
def psf(opd,mask):
 a=np.zeros(mask.shape,complex);a[mask]=np.exp(2j*np.pi*opd[mask]/WAVELENGTH)
 p=abs(np.fft.fftshift(np.fft.fft2(np.fft.ifftshift(np.pad(a,256)))))**2
 return p/p.sum()
def rgb(a):
 t=np.arcsinh(np.clip(a,LO,HI)/SOFT)/np.arcsinh(HI/SOFT)
 return Image.fromarray(np.flipud(LUT[np.minimum((t*256).astype(int),255)]))

def movie(out,replay,data):
 fontpath=Path(get_data_path())/'fonts/ttf/DejaVuSans.ttf'
 f=lambda s:ImageFont.truetype(str(fontpath),s)
 title,label,small,tiny=f(29),f(19),f(16),f(14)
 base=Image.new('RGB',(1280,720),'#faf9f6');draw=ImageDraw.Draw(base)
 draw.text((24,14),'Westerlund 2 · F162M | Recorded 2.2 m AO correction',font=title,fill='#20252a')
 draw.text((24,51),'Same 4.109″ field · 0.05136″ per model pixel · fixed 0–80 MJy/sr asinh scale · no AO rerun',font=small,fill='#555')
 titles=['Observed JWST','No AO correction','Original v1','Repaired v2']
 colours=['#333','#6c7075','#b3541e','#4d7a2a'];left=[24+314*j for j in range(4)]
 for j,t in enumerate(titles):draw.text((left[j],80),t,font=label,fill=colours[j])
 ref=Image.open(out/'reference.png').crop((0,0,N,N)).resize((288,288),Image.Resampling.NEAREST)
 base.paste(ref,(24,109))
 # Scale bar represents the same sky angle in all four panels.
 def bar(d,x):
  x0=x+15;y=378;d.line((x0,y,x0+.5/data['pixel_arcsec']*288/N,y),fill='white',width=3)
  d.text((x0,y-24),'0.5″',font=tiny,fill='white')
 bar(draw,24);draw.text((24,402),'JWST PSF and noise retained',font=tiny,fill='#555')
 # Shared calibrated transfer, including accurately positioned non-linear ticks.
 scale=Image.fromarray(np.tile(LUT[None,:,:],(12,1,1))).resize((360,12))
 base.paste(scale,(24,438))
 for value in [0,2,5,10,20,40,80]:
  x=24+359*np.arcsinh(value/SOFT)/np.arcsinh(HI/SOFT)
  draw.text((x,451),str(value),font=tiny,anchor='mt',fill='#444')
 draw.text((399,437),'MJy/sr · one display stretch for every image',font=tiny,fill='#555')
 x0,x1,y0,y1=70,1240,511,632
 xy=lambda t,s:(x0+(x1-x0)*t/2,y1-(y1-y0)*s)
 draw.rectangle((x0,y0,x1,y1),fill='white',outline='#b8bbc1')
 for value in [0,.5,1]:
  y=xy(0,value)[1];draw.line((x0,y,x1,y),fill='#e0e2e4');draw.text((x0-8,y),str(value),font=tiny,anchor='rm',fill='#555')
 for t in [0,.5,1,1.5,2]:draw.text((xy(t,0)[0],y1+3),f'{t:g} s',font=tiny,anchor='mt',fill='#555')
 m=replay['metrics'];times=m['time_s']
 for values,col in [(m['uncorrected_strehl'],colours[1]),(m['v1']['strehl'],colours[2]),(m['v2']['strehl'],colours[3])]:
  draw.line([xy(t,v)for t,v in zip(times,values)],fill=col,width=2)
 loss_x=xy(data['loss_time_s'],0)[0]
 for y in range(y0,y1,9):draw.line((loss_x,y,loss_x,min(y+5,y1)),fill='#a3324e',width=2)
 draw.text((loss_x+8,y0+3),'First v1 rejection: 0.981333 s',font=tiny,fill='#a3324e')
 draw.text((24,484),'Point-source Strehl · all 1500 saved measurements',font=small,fill='#333')
 draw.text((24,662),'F162M 1.627 µm approximated by existing 1.65 µm PSFs. Outside-field saturated stars can affect image edges.',font=tiny,fill='#444')
 draw.text((24,684),'NASA / ESA / CSA JWST · program 3523 / EWOCS · MAST. Source PSF/noise retained; one on-axis PSF; no band/exposure integration.',font=tiny,fill='#555')
 frames=[]
 for k in data['indices']:
  im=base.copy();d=ImageDraw.Draw(im);atlas=Image.open(out/'frames'/f'{k:04}.webp')
  for j,name in enumerate(['uncorrected','v1','v2'],1):
   panel=atlas.crop(((j-1)*N,0,j*N,N)).resize((288,288),Image.Resampling.NEAREST);im.paste(panel,(left[j],109));bar(d,left[j])
   strehl=m['uncorrected_strehl'][k]if name=='uncorrected'else m[name]['strehl'][k]
   d.text((left[j],402),f'Point-source Strehl {strehl:.4f}',font=tiny,fill=colours[j])
  d.text((820,434),f't = {times[k]:.6f} s · frame {k}',font=label,fill='#20252a')
  d.text((820,461),'v1 reconstruction rejected'if k>=736 else'before first v1 rejection',font=small,fill='#a3324e'if k>=736 else'#555')
  cursor=xy(times[k],0)[0];d.line((cursor,y0,cursor,y1),fill='#13181e',width=2)
  for values,col in [(m['uncorrected_strehl'],colours[1]),(m['v1']['strehl'],colours[2]),(m['v2']['strehl'],colours[3])]:
   x,y=xy(times[k],values[k]);d.ellipse((x-3,y-3,x+3,y+3),fill=col,outline='white')
  frames.append(im)
 durations=np.diff([round(times[k]*20000)for k in data['indices']]+[40000]).tolist()
 frames[-1].save(out/'poster.png')
 for k in [0,735,736,1499]:frames[data['indices'].index(k)].save(out/f'preview-{k:04}.png')
 frames[0].save(out/'science-comparison.webp',save_all=True,append_images=frames[1:],duration=durations,loop=0,lossless=True,method=4)
 with Image.open(out/'science-comparison.webp')as check:
  assert check.n_frames==len(frames);total=0
  for k in range(check.n_frames):check.seek(k);check.load();total+=check.info['duration']
  assert total==40000
 write(out/'movie-timing.json',{'duration_ms':40000,'indices':data['indices'],'frame_durations_ms':durations,'temporal_interpolation':False,'format':'lossless animated WebP presentation','dimensions':[1280,720]})

def main(args):
 out=args.output_dir;out.mkdir(exist_ok=True,parents=True);(out/'frames').mkdir(exist_ok=True)
 web=args.web_dir;entry=read(web/'data/current.json');rp=(web/'data'/entry['ngsReplay']['manifest']).resolve()
 checked(rp,{'bytes':entry['ngsReplay']['manifest_bytes'],'sha256':entry['ngsReplay']['manifest_sha256']});parent=read(rp)
 replay=read(checked(rp.parent/'data.json',parent['files']['data.json']));prior=read(rp.parent/'provenance.json')
 sm=read(args.static_dir/'manifest.json');static=read(checked(args.static_dir/'results.json',sm['files']['results.json']))
 context=np.load(checked(args.static_dir/'scene-context.npz',sm['files']['scene-context.npz']))
 approved=np.load(checked(args.static_dir/'linear-comparison.npz',sm['files']['linear-comparison.npz']))
 assert static['source']['center_mosaic_xy_zero_based']==[9090.,3670.]and approved['observed_reference'].shape==(N,N)
 scene=context['surface_brightness_mjy_sr'];missing=context['missing_component_mjy_sr'];sat=context['saturation_guard_component_mjy_sr']
 assert scene.shape==(N+768,N+768)
 folders=[args.archive_root/'outputs/robo_ao2_ngs/20261024-first-trajectory/attempt-04',args.archive_root/'outputs/robo_ao2_ngs/20261024-loss-of-lock-repair/trajectory-v2']
 inputs={}
 for folder,names in [(folders[0],['science-psfs.npz','pre_update_residual_opd_m.npy','atmosphere_opd_m.npy']),(folders[1],['science-psfs.npz','pre_update_residual_opd_m.npy'])]:
  for name in names:
   p=folder/name;key=str(p.relative_to(args.archive_root));checked(p,prior['inputs'][key]);inputs[key]=meta(p)
 saved=[dict(np.load(f/'science-psfs.npz'))for f in folders];mask=saved[0]['pupil_mask'].astype(bool)
 assert np.array_equal(mask,saved[1]['pupil_mask'])
 step=float(np.diff(saved[0]['x_angle_rad'])[0])*180/np.pi*3600
 assert abs(step-static['source']['model_pixel_arcsec'])<1e-15
 ideal=psf(np.zeros(mask.shape),mask);assert abs(ideal-saved[0]['ideal']).max()<1e-14
 shape=tuple(fft.next_fast_len(n+767,real=True)for n in scene.shape)
 spectra=[fft.rfft2(a,s=shape,workers=2)for a in [scene,missing,sat]]
 fluxerror=0.
 def observe(p,j=0):
  nonlocal fluxerror
  full=fft.irfft2(spectra[j]*fft.rfft2(p,s=shape,workers=2),s=shape,workers=2)
  expected=[scene,missing,sat][j].sum()*p.sum();fluxerror=max(fluxerror,float(abs(full.sum()-expected)/max(abs(expected),1)))
  return full[768:scene.shape[0],768:scene.shape[1]]
 reference=scene[384:-384,384:-384];assert np.array_equal(reference,approved['observed_reference'])
 delta=np.zeros_like(ideal);delta[384,384]=1;deltaerror=float(abs(observe(delta)-reference).max());assert deltaerror<1e-8
 refs=Image.new('RGB',(2*N,N));refs.paste(rgb(reference),(0,0));refs.paste(rgb(observe(ideal)),(N,0));refs.save(out/'reference.png')
 Image.fromarray(np.tile(LUT[None,:,:],(16,1,1))).save(out/'intensity-scale.png')
 maps=[np.load(folders[0]/'atmosphere_opd_m.npy',mmap_mode='r')]+[np.load(f/'pre_update_residual_opd_m.npy',mmap_mode='r')for f in folders]
 metricerror=0.;snapshoterror=0.;count=0;staticerror=0.;maximum_missing=np.zeros((N,N));maximum_sat=np.zeros((N,N));sensitivity=[];linear={}
 for pos,k in enumerate(replay['indices']):
  atlas=Image.new('RGB',(3*N,N));row={'frame':k,'time_s':replay['metrics']['time_s'][k]}
  for j,name in enumerate(['uncorrected','v1','v2']):
   p=psf(maps[j][k],mask);expected=replay['metrics']['uncorrected_strehl'][k]if j==0 else replay['metrics'][name]['strehl'][k]
   metricerror=max(metricerror,abs(float(p.max()/ideal.max())-expected))
   if j and 'frame_'+str(k)in saved[j-1]:snapshoterror=max(snapshoterror,float(abs(p-saved[j-1]['frame_'+str(k)]).max()));count+=1
   a=observe(p);mi=observe(p,1);sa=observe(p,2);atlas.paste(rgb(a),(j*N,0))
   maximum_missing=np.maximum(maximum_missing,abs(mi));maximum_sat=np.maximum(maximum_sat,abs(sa))
   row[name]={'missing_zero_twice_max_mjy_sr':float(abs(mi).max()),'outside_sat_zero_twice_max_mjy_sr':float(abs(sa).max()),'outside_sat_mean_mjy_sr':float(sa.mean())}
   if k in [735,736,1499]:staticerror=max(staticerror,float(abs(a-approved[f'{name}_{k}']).max()));linear[f'{name}_{k}']=a
  atlas.save(out/'frames'/f'{k:04}.webp',lossless=True,method=4);sensitivity.append(row)
  if pos%30==0:print(f'rendered {pos+1}/{len(replay["indices"])}',flush=True)
 assert count==15 and metricerror<1e-12 and snapshoterror<1e-14 and staticerror<1e-9 and fluxerror<1e-12
 np.savez_compressed(out/'linear-samples.npz',observed_reference=reference,**linear,pixel_arcsec=step)
 threshold=.01*(HI-LO);excluded=maximum_sat>threshold
 np.savez_compressed(out/'saturation-sensitivity-map.npz',maximum_change_mjy_sr=maximum_sat,maximum_missing_change_mjy_sr=maximum_missing,threshold_mjy_sr=threshold,excluded=excluded)
 # Diagnostic only: the approved unmasked presentation remains the default.
 Image.fromarray(np.flipud(np.uint8(excluded)*255)).save(out/'saturation-sensitivity-mask.png')
 for old,new in [('source-cutout.fits.gz','source-detail.fits.gz'),('westerlund2-f162m-field.png','source-context.png'),('westerlund2-f162m-three-epochs.png','static-comparison.png'),('westerlund2-f162m-three-epochs-quality.png','static-quality.png'),('README.md','static-methods.md'),('results.json','static-results.json'),('scene-context.npz','scene-context.npz')]:
  p=checked(args.static_dir/old,sm['files'][old]);shutil.copy2(p,out/new)
 for old,new in [('source/source-extraction.json','source-extraction.json'),('source/quality-extraction-b1.json','quality-extraction.json')]:
  p=checked(args.static_dir/old,sm['files'][old]);shutil.copy2(p,out/new)
 write(out/'sensitivity.json',sensitivity)
 source={**static['source'],'bunit':'MJy/sr','pivot_wavelength_um':1.627,'bandwidth_um':.168,'field_arcsec':[N*step,N*step]}
 checks={'all_ao_inputs_hash_verified':True,'approved_static_source_hash_verified':True,'sampled_strehl_values':3*len(replay['indices']),'sampled_strehl_max_abs_error':metricerror,'saved_psf_checks':count,'saved_psf_max_abs_error':snapshoterror,'approved_static_max_abs_difference_mjy_sr':staticerror,'full_convolution_flux_max_relative_error':fluxerror,'delta_kernel_max_error_mjy_sr':deltaerror,'missing_context_max_change_mjy_sr':float(maximum_missing.max()),'saturation_context_max_change_mjy_sr':float(maximum_sat.max()),'saturation_diagnostic':{'threshold_mjy_sr':threshold,'fraction_above_threshold':float(excluded.mean()),'applied_to_default_replay':False,'covers_all_replay_frames':True,'maximum_unmasked_tested_change_mjy_sr':float(maximum_sat[~excluded].max())if (~excluded).any()else None}}
 data={'schema':'ao-explorer.science-replay-data.v1','layout':'compact-same-field-v1','frames':1500,'indices':replay['indices'],'parent_replay_id':entry['ngsReplay']['id'],'parent_replay_data_sha256':sha(rp.parent/'data.json'),'loss_frame':736,'loss_time_s':736/750,'wavelength_m':WAVELENGTH,'pixel_arcsec':step,'detail_field_arcsec':N*step,'detail':N,'atlas':[3*N,N],'source':source,'display':{'type':'asinh','min_mjy_sr':LO,'max_mjy_sr':HI,'softening_mjy_sr':SOFT,'colormap':'magma','fixed_for_all_frames_and_panels':True},'checks':checks}
 write(out/'data.json',data)
 write(out/'provenance.json',{'simulation_rerun':False,'approved_static_manifest_sha256':sha(args.static_dir/'manifest.json'),'approved_static_inputs':{name:sm['files'][name]for name in ['scene-context.npz','results.json','linear-comparison.npz']},'archive_inputs':inputs,'source':source,'checks':checks,'operations':['Reuse the approved 4.109 arcsec source context without selecting, recropping or resampling the field again.','Calculate only Fourier-optics PSFs from existing archived OPD samples; no AO controller, atmosphere evolution, RNG, calibration or reconstruction is run.','Apply full linear, unit-flux convolution with retained tilt. Keep the shared 0–80 MJy/sr asinh transfer.','Preserve all 159 parent image timestamps and all 1500 Strehl measurements, including every frame 720–752 around first rejection.','Retain the observed JWST PSF, diffraction structure, calibration and noise. Approximate F162M by existing monochromatic 1.65 um PSFs.','Quantify outside-field saturation-guard and missing-context sensitivity at all image times. This is not a bound on unknown true saturated flux. No mask alters the approved default image presentation.']})
 movie(out,replay,data)
 shutil.copy2(__file__,out/'exporter.py')
 shutil.copy2(args.methods,out/'README.md')
 files={str(p.relative_to(out)):{**meta(p),'media_type':'image/webp'if p.suffix=='.webp'else'image/png'if p.suffix=='.png'else'application/json'if p.suffix=='.json'else'application/octet-stream'if p.suffix in ['.npz','.gz']else'text/plain'}for p in sorted(out.rglob('*'))if p.is_file()and p.name!='manifest.json'}
 identity='westerlund2-f162m-'+hashlib.sha256(json.dumps(files,sort_keys=True,separators=(',',':')).encode()).hexdigest()[:16]
 write(out/'manifest.json',{'schema':'ao-explorer.science-replay-manifest.v1','id':identity,'files':files})
 target=web/'derived'/identity
 if not target.exists():shutil.copytree(out,target)
 else:assert sha(target/'manifest.json')==sha(out/'manifest.json')
 entry['scienceReplay']={'schema':'ao-explorer.science-replay-entry.v1','id':identity,'manifest':'../derived/'+identity+'/manifest.json','manifest_bytes':(target/'manifest.json').stat().st_size,'manifest_sha256':sha(target/'manifest.json')};write(web/'data/current.json',entry)
 print(json.dumps({'id':identity,'checks':checks,'bundle_bytes':sum(v['bytes']for v in files.values())}),flush=True)

if __name__=='__main__':
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--archive-root',type=Path,required=True);p.add_argument('--static-dir',type=Path,required=True);p.add_argument('--web-dir',type=Path,required=True);p.add_argument('--output-dir',type=Path,required=True);p.add_argument('--methods',type=Path,required=True);main(p.parse_args())
