"""Observed Orion F162M through archived 2.2 m PSFs; no AO runtime execution.

Build the fixed scene first, then convolve existing OPD-derived PSFs. Image
rendering and all interpolation assumptions are explicit in the public bundle.
"""
from __future__ import annotations
import hashlib, json, shutil, csv
from pathlib import Path
import numpy as np
from astropy.io import fits
from astropy.wcs import WCS
from astropy.wcs.utils import proj_plane_pixel_scales
from scipy import ndimage, fft
from scipy.signal import convolve2d, fftconvolve
from PIL import Image, ImageDraw
from matplotlib import colormaps

ROOT=Path(__file__).resolve().parents[2]
WORK=ROOT/'outputs/orion_ngs'
WEB=ROOT/'web/ao-explorer'
TILE=256
SCENE=961
WINDOW=193
WAVELENGTH=1.65e-6

def read(p): return json.loads(p.read_text())
def write(p,x): p.write_text(json.dumps(x,indent=2,allow_nan=False)+'\n')
def sha(p):
 h=hashlib.sha256()
 with p.open('rb') as f:
  for b in iter(lambda:f.read(8*1024**2),b''):h.update(b)
 return h.hexdigest()
def psf(opd,mask):
 f=np.zeros(mask.shape,complex);f[mask]=np.exp(2j*np.pi*opd[mask]/WAVELENGTH)
 z=np.pad(f,((256,256),(256,256)));p=abs(np.fft.fftshift(np.fft.fft2(np.fft.ifftshift(z))))**2
 return p/p.sum()
def overlap(n,step,oldn,oldstep):
 edges=(np.arange(n+1)-n//2-.5)*step/oldstep+(oldn-1)/2
 lo=np.arange(oldn)-.5;hi=lo+1
 return np.clip(np.minimum(edges[1:,None],hi)-np.maximum(edges[:-1,None],lo),0,None)/(step/oldstep)

def prepare(step,out):
 record=read(WORK/'source-extraction.json');cx,cy=9340,8786;r=900
 arrays={}
 nx=record['extensions'][0]['shape_fits'][0];y0,y1=record['bounds_xy'][2:]
 for name in ['SCI','ERR','WHT']:
  rows=np.memmap(WORK/f'{name}-rows-{y0}-{y1}.bin',dtype='>f4',mode='r',shape=(y1-y0,nx))
  arrays[name]=np.array(rows[cy-r-y0:cy+r+1-y0,cx-r:cx+r+1],dtype=np.float64)
 h=fits.Header.fromstring((WORK/'SCI-source-header.txt').read_text(),sep='\n')
 w=WCS(h);scale=proj_plane_pixel_scales(w)*3600
 assert np.allclose(scale,scale[0],rtol=1e-10)
 a=arrays['SCI'];bad=~np.isfinite(a)|(arrays['WHT']<=0)|~np.isfinite(arrays['ERR'])
 idx=ndimage.distance_transform_edt(bad,return_distances=False,return_indices=True)
 filled=a.copy();filled[bad]=a[tuple(idx[:,bad])]
 assert np.isfinite(filled).all()
 weights=overlap(SCENE,step,a.shape[0],scale[0]);assert np.max(abs(weights.sum(axis=1)-1))<1e-12
 scene=weights@filled@weights.T
 # The missing-context component measures sensitivity to replacing the nominal
 # nearest-valid fill by zero or twice that fill; not a bound on unknown flux.
 missing=weights@np.where(bad,filled,0)@weights.T
 bad_fraction=weights@bad.astype(float)@weights.T
 c=SCENE//2;q=WINDOW//2;view=np.s_[c-q:c+q+1,c-q:c+q+1]
 assert not np.any(bad_fraction[view]),'Displayed source must contain no replaced pixels'
 np.savez_compressed(out/'scene.npz',surface_brightness_mjy_sr=scene,missing_context_component_mjy_sr=missing,
                     missing_area_fraction=bad_fraction,angular_step_arcsec=np.array(step))
 # Public original source cutout in the display footprint (plus one native pixel).
 rad=int(np.ceil((q+.5)*step/scale[0]))+1;s=np.s_[r-rad:r+rad+1,r-rad:r+rad+1]
 hdr=h.copy();hdr['CRPIX1']-=cx-rad;hdr['CRPIX2']-=cy-rad
 hdus=[fits.PrimaryHDU(),fits.ImageHDU(arrays['SCI'][s].astype('f4'),hdr,name='SCI')]
 hdus += [fits.ImageHDU(arrays[n][s].astype('f4'),name=n) for n in ['ERR','WHT']]
 fits.HDUList(hdus).writeto(out/'source-display.fits',overwrite=True,checksum=True)
 assert np.isfinite(arrays['SCI'][s]).all() and np.all(arrays['WHT'][s]>0)
 coords=w.pixel_to_world(cx,cy)
 meta={'object':'Orion Nebula: compact dark silhouette, nebulosity and nearby star',
       'product':record['product'],'url':record['url'],'program':1256,'filter':'F150W2 + F162M',
       'pivot_wavelength_um':1.626,'simulation_wavelength_um':1.65,'bunit':'MJy/sr',
       'date_obs':'2022-09-28 to 2022-10-02','calibration_version':record['calibration_version'],
       'source_center_xy_zero_based':[cx,cy],'center_icrs_deg':[float(coords.ra.deg),float(coords.dec.deg)],
       'source_context_bounds_xy':[cx-r,cx+r+1,cy-r,cy+r+1],'source_context_shape':list(a.shape),
       'native_pixel_arcsec':scale.tolist(),'simulation_pixel_arcsec':step,'scene_shape':list(scene.shape),
       'display_shape':[WINDOW,WINDOW],'display_field_arcsec':WINDOW*step,
       'scene_field_arcsec':SCENE*step,'context_bad_pixels':int(bad.sum()),'context_pixels':a.size,
       'display_replaced_pixels':0,'display_min_weight':float(arrays['WHT'][s].min()),
       'display_finite_error':bool(np.isfinite(arrays['ERR'][s]).all()),
       'preprocessing':'Pixel-area averaging of calibrated linear surface brightness. No background subtraction, deconvolution, noise draw or photometric renormalization. Original image axes retained.',
       'missing_data_assumption':'Only outside the displayed field: replace nonfinite SCI/ERR or nonpositive WHT pixels by the nearest valid SCI pixel. Original bad-pixel contribution exported separately. Zero and twice-fill sensitivity assessed for every displayed PSF. This does not reconstruct saturated flux or bound its true value.',
       'quality_limit':'Finite SCI/ERR and positive WHT verified in the displayed field. No independent per-exposure saturation or absolute-photometry audit. Existing JWST PSF, diffraction spikes and observational noise remain.',
       'orientation':'Native mosaic axes, vertically flipped for display; alignment to simulated pupil is arbitrary. No claim of a measured instrument position angle.',
       'credit':'NASA/ESA/CSA JWST NIRCam; GTO 1256, PI Mark J. McCaughrean; calibrated public product from MAST (STScI). Single-band display processing for this experiment.',
       'reference_page':'https://www.esa.int/Science_Exploration/Space_Science/Webb/Webb_s_wide-angle_view_of_the_Orion_Nebula_is_released_in_ESASky',
       'data_policy':'https://archive.stsci.edu/publishing/data-use'}
 context=np.arcsinh(np.maximum(filled-50,0)/70);context=np.clip(context/np.arcsinh(3000/70),0,1)
 im=Image.fromarray(np.uint8(colormaps['magma'](np.flipud(context))[...,:3]*255)).resize((600,600),Image.Resampling.LANCZOS)
 d=ImageDraw.Draw(im);half=(q+.5)*step/scale[0]*600/a.shape[0];d.rectangle([300-half,300-half,300+half,300+half],outline='white',width=2)
 d.rectangle((8,8,297,33),fill=(10,10,20));d.text((15,15),'F162M context / white box = replay',fill='white');im.save(out/'context.png')
 return scene,missing,view,meta,record


def render_movie(out,replay):
 """A self-contained 40 s animated WebP, holding each actual saved timestamp."""
 from PIL import ImageFont
 from matplotlib import get_data_path
 fontfile=str(Path(get_data_path())/'fonts/ttf/DejaVuSans.ttf')
 font=ImageFont.truetype(fontfile,16);small=ImageFont.truetype(fontfile,13);title=ImageFont.truetype(fontfile,23)
 data=read(out/'data.json');indices=replay['indices'];m=replay['metrics'];times=m['time_s'];frames=[]
 # Rounded absolute boundaries avoid cumulative millisecond drift.
 boundaries=[round(times[k]*20000) for k in indices]+[40000]
 durations=np.diff(boundaries).tolist();assert sum(durations)==40000 and min(durations)>0
 x0,x1,y0,y1=65,1035,485,650
 def xy(t,y):return (x0+(x1-x0)*t/2,y1-(y1-y0)*y)
 base=Image.new('RGB',(1100,740),(247,245,239));d=ImageDraw.Draw(base)
 d.text((24,16),'Orion F162M | the same sky, before and after AO repair',font=title,fill='#20252a')
 d.text((24,49),'Existing 2.2 m record | 1.65 um PSFs | 9.913 arcsec per panel | fixed intensity scale',font=small,fill='#42484d')
 labels=['Observed JWST','No correction','Original v1','Repaired v2'];colors=['#30363c','#6e7379','#b3541e','#4d7a2a']
 for j,label in enumerate(labels):d.text((26+j*270,80),label,font=font,fill=colors[j])
 ref=Image.open(out/'reference.png').crop((0,0,256,256));base.paste(ref,(20,108))
 d.text((24,400),'Point-source Strehl (all 1500 saved samples); source image is not used to measure Strehl.',font=small,fill='#42484d')
 d.text((24,421),'Original v1',font=small,fill=colors[2]);d.text((135,421),'Repaired v2',font=small,fill=colors[3]);d.text((250,421),'No correction',font=small,fill=colors[1])
 d.rectangle((x0,y0,x1,y1),fill='white',outline='#aaa')
 for val in [0,.25,.5,.75,1]:
  y=xy(0,val)[1];d.line((x0,y,x1,y),fill='#ddd');d.text((24,y-7),f'{val:g}',font=small,fill='#555')
 for t in [0,.5,1,1.5,2]:
  x=xy(t,0)[0];d.text((x-8,y1+8),f'{t:g}',font=small,fill='#555')
 loss=xy(736/750,0)[0];d.line((loss,y0,loss,y1),fill='#af3351',width=2);d.text((loss+6,y0+6),'0.981333 s',font=small,fill='#af3351')
 for vals,col in [(m['uncorrected_strehl'],colors[1]),(m['v1']['strehl'],colors[2]),(m['v2']['strehl'],colors[3])]:d.line([xy(t,y) for t,y in zip(times,vals)],fill=col,width=2)
 d.text((24,691),'Observed JWST PSF retained; monochromatic false colour. One 2 s record shown 20x slower.',font=small,fill='#42484d')
 d.text((24,712),'NASA / ESA / CSA JWST NIRCam | GTO 1256, M. McCaughrean | calibrated public MAST data',font=small,fill='#42484d')
 for k in indices:
  im=base.copy();draw=ImageDraw.Draw(im);atlas=Image.open(out/'frames'/f'{k:04}.png')
  for j in range(3):im.paste(atlas.crop((j*256,0,(j+1)*256,256)),(20+(j+1)*270,108))
  draw.text((26,372),f't = {times[k]:.6f} s   |   frame {k:04d} / 1499',font=font,fill='#20252a')
  phase='v1 reconstruction rejected' if k>=736 else 'before first rejected v1 reconstruction'
  draw.text((570,372),phase,font=font,fill='#af3351' if k>=736 else '#42484d')
  x=xy(times[k],0)[0];draw.line((x,y0,x,y1),fill='#151515',width=2)
  for j,v in enumerate([m['uncorrected_strehl'][k],m['v1']['strehl'][k],m['v2']['strehl'][k]]):draw.text((26+(j+1)*270,447),f'Strehl {v:.4f}',font=small,fill=colors[j+1])
  frames.append(im)
 frames[0].save(out/'orion-comparison.webp',save_all=True,append_images=frames[1:],duration=durations,loop=0,lossless=True,method=4)
 frames[indices.index(736)].save(out/'movie-poster.png')
 with Image.open(out/'orion-comparison.webp') as check:
  assert check.n_frames==len(indices);total=0
  for i in range(check.n_frames):check.seek(i);check.load();total+=check.info['duration']
  assert total==40000
 write(out/'movie-timing.json',{'format':'animated WebP, lossless','dimensions':[1100,740],'duration_ms':40000,'indices':indices,'frame_durations_ms':durations,'loop':'repeats the same recording','temporal_interpolation':False,'source':'All 159 existing replay image times; curves retain all 1500 points. No new AO simulation.'})

def main():
 out=WORK/'bundle';out.mkdir(exist_ok=True);(out/'frames').mkdir(exist_ok=True)
 entry=read(WEB/'data/current.json');rp=(WEB/'data'/entry['ngsReplay']['manifest']).resolve();replay=read(rp.parent/'data.json');prior=read(rp.parent/'provenance.json')
 folders=[ROOT/'outputs/robo_ao2_ngs/20261024-first-trajectory/attempt-04',ROOT/'outputs/robo_ao2_ngs/20261024-loss-of-lock-repair/trajectory-v2']
 inputs={}
 for folder in folders:
  for name in ['pre_update_residual_opd_m.npy','science-psfs.npz']:
   p=folder/name;key=str(p.relative_to(ROOT));actual={'bytes':p.stat().st_size,'sha256':sha(p)};assert prior['inputs'][key]==actual;inputs[key]=actual
 p=folders[0]/'atmosphere_opd_m.npy';key=str(p.relative_to(ROOT));actual={'bytes':p.stat().st_size,'sha256':sha(p)};assert prior['inputs'][key]==actual;inputs[key]=actual
 saved=[dict(np.load(p/'science-psfs.npz')) for p in folders];mask=saved[0]['pupil_mask'].astype(bool)
 assert np.array_equal(mask,saved[1]['pupil_mask'])
 step=float(np.diff(saved[0]['x_angle_rad'])[0])*180/np.pi*3600
 scene,missing,view,source,extraction=prepare(step,out)
 ideal=psf(np.zeros(mask.shape),mask);assert np.max(abs(ideal-saved[0]['ideal']))<1e-14;peak=float(ideal.max())
 maps=[np.load(folders[0]/'atmosphere_opd_m.npy',mmap_mode='r')]+[np.load(p/'pre_update_residual_opd_m.npy',mmap_mode='r') for p in folders]
 # Full linear convolution; zero-angle PSF sample is index 384, not 383.
 shape=tuple(fft.next_fast_len(n,real=True) for n in (SCENE+767,SCENE+767));spectrum=fft.rfft2(scene,s=shape);missing_spectrum=fft.rfft2(missing,s=shape)
 q=WINDOW//2;offset=384+SCENE//2-q;cut=np.s_[offset:offset+WINDOW,offset:offset+WINDOW]
 max_flux_error=0.
 def observe(p,other=False):
  nonlocal max_flux_error
  full=fft.irfft2((missing_spectrum if other else spectrum)*fft.rfft2(p,s=shape),s=shape)[:SCENE+767,:SCENE+767]
  expected=float((missing if other else scene).sum())*float(p.sum());max_flux_error=max(max_flux_error,abs(float(full.sum())-expected)/max(abs(expected),1))
  return full[cut]
 ref=scene[view].copy();ideal_view=observe(ideal)
 # An independent direct-convolution oracle and exact zero-angle delta check.
 s=np.arange(15,dtype=float).reshape(3,5);k=np.arange(24,dtype=float).reshape(4,6)
 direct_error=float(np.max(abs(fftconvolve(s,k)-convolve2d(s,k))));assert direct_error<1e-10
 delta=np.zeros((768,768));delta[384,384]=1;delta_error=float(np.max(abs(observe(delta)-ref)));assert delta_error<1e-9
 lo=float(np.percentile(ref,1));hi=float(np.max(ref));soft=(hi-lo)/25
 assert hi>lo
 lut=np.uint8(colormaps['magma'](np.linspace(0,1,256))[...,:3]*255)
 def rgb(a):
  t=np.arcsinh(np.maximum(a-lo,0)/soft)/np.arcsinh((hi-lo)/soft)
  return lut[np.rint(np.clip(t,0,1)*255).astype(np.uint8)]
 def tile(a):return Image.fromarray(np.flipud(rgb(a))).resize((TILE,TILE),Image.Resampling.NEAREST)
 static=Image.new('RGB',(TILE*2,TILE));static.paste(tile(ref),(0,0));static.paste(tile(ideal_view),(TILE,0));static.save(out/'reference.png',optimize=True)
 np.savez_compressed(out/'reference-linear.npz',observed=ref,ideal_22m=ideal_view)
 metric_error=0.;snapshot_error=0.;checks=0;sensitivity=[];fluxes=[];window_stack=[]
 for pos,k in enumerate(replay['indices']):
  ps=[psf(a[k],mask) for a in maps];images=[];sens=[]
  for j,p in enumerate(ps):
   expected=replay['metrics']['uncorrected_strehl'][k] if j==0 else replay['metrics'][['v1','v2'][j-1]]['strehl'][k]
   metric_error=max(metric_error,abs(float(p.max()/peak)-expected))
   if j and 'frame_'+str(k) in saved[j-1]:
    snapshot_error=max(snapshot_error,float(np.max(abs(p-saved[j-1]['frame_'+str(k)]))));checks+=1
   a=observe(p);perturb=observe(p,True);images.append(a)
   nominal=rgb(a).astype(int);zero=rgb(a-perturb).astype(int);twice=rgb(a+perturb).astype(int)
   sens.append({'max_abs_mjy_sr':float(abs(perturb).max()),'max_fraction_display_span':float(abs(perturb).max()/(hi-lo)),
                'max_rgb_code_change':int(max(abs(nominal-zero).max(),abs(nominal-twice).max()))})
  atlas=Image.new('RGB',(TILE*3,TILE))
  for j,a in enumerate(images):atlas.paste(tile(a),(j*TILE,0))
  atlas.save(out/'frames'/f'{k:04}.png',optimize=True)
  sensitivity.append(sens);fluxes.append([float(a.sum()) for a in images]);window_stack.append(np.asarray(images,dtype=np.float32))
  if pos%30==0:print(f'rendered {pos+1}/{len(replay["indices"])}',flush=True)
 assert checks==15 and snapshot_error<1e-14 and metric_error<1e-12 and max_flux_error<1e-12
 np.savez_compressed(WORK/'linear-frames.npz',indices=replay['indices'],intensity=np.asarray(window_stack),reference=ref,ideal=ideal_view)
 provenance={'schema':'ao-explorer.orion-provenance.v1','simulation_rerun':False,'source':source,'source_extraction':extraction,
  'archive_inputs':inputs,'parent_replay_entry':entry['ngsReplay'],'parent_replay_data_sha256':sha(rp.parent/'data.json'),
  'exporter_sha256':sha(Path(__file__)),'operations':[
   'Fixed observed F162M morphology with existing JWST optical response and noise; no deconvolution.',
   'Exact rectangular overlap averages surface brightness onto the native simulation PSF grid; native sky axes retained.',
   'All full 768x768 unit-flux PSFs retained, with original tilt; linear FFT convolution padded to at least scene+kernel-1. Crop only after convolution.',
   'Local missing-data fill is restricted to outer context. Sensitivity uses zero and twice nominal fills, not a bound on unknown true flux.',
   'One spatially invariant on-axis PSF over a compact field. Scene does not enter the WFS or controller. No added detector or sky noise.',
   'One fixed asinh stretch and sequential single-band colour map for every frame and panel. No independent auto-contrast, temporal interpolation or recentering.'],
  'checks':{'all_ao_inputs_hash_verified':True,'saved_psf_checks':checks,'saved_psf_max_abs_error':snapshot_error,
    'sampled_strehl_max_abs_error':metric_error,'sampled_strehl_values':3*len(replay['indices']),
    'full_convolution_flux_max_relative_error':max_flux_error,'independent_direct_convolution_max_abs_error':direct_error,
    'delta_kernel_max_abs_error_mjy_sr':delta_error,'display_original_missing_pixels':0,
    'outer_fill_max_fraction_display_span':max(x['max_fraction_display_span'] for row in sensitivity for x in row),
    'outer_fill_max_rgb_code_change':max(x['max_rgb_code_change'] for row in sensitivity for x in row)},
  'outer_fill_sensitivity_per_frame':sensitivity,'display_window_surface_brightness_sums':fluxes}
 write(out/'provenance.json',provenance)
 data={'schema':'ao-explorer.orion-replay-data.v1','tile':TILE,'frames':1500,'indices':replay['indices'],
  'parent_replay_id':entry['ngsReplay']['id'],'parent_replay_data_sha256':sha(rp.parent/'data.json'),
  'loss_frame':736,'loss_time_s':736/750,'wavelength_m':WAVELENGTH,'field_arcsec':WINDOW*step,'pixel_arcsec':step,
  'roles':['uncorrected','v1','v2'],'reference_roles':['observed','ideal_22m'],
  'stretch':{'kind':'asinh','low_mjy_sr':lo,'high_mjy_sr':hi,'softening_mjy_sr':soft,'lut_rgb':lut.tolist()},
  'source':source,'checks':provenance['checks']}
 write(out/'data.json',data)
 shutil.copy2(__file__,out/'exporter.py');shutil.copy2(WORK/'fetch_cutout.py',out/'source-extractor.py')
 (out/'README.md').write_text('''# Orion F162M through the saved 2.2 m NGS experiment

This is an illustrative convolution of an observed JWST image, not a new AO
trajectory, an intrinsic-sky reconstruction or a prediction of Robo-AO-2
photometry. The sky image remains fixed as the recorded PSFs change.

## Source and quality

NASA/ESA/CSA JWST NIRCam, GTO 1256 (PI Mark J. McCaughrean), MAST calibrated
F150W2+F162M mosaic, pipeline 3.0.0. See provenance.json for the exact product,
HTTP byte ranges, hashes, WCS coordinates and SCI/ERR/WHT extraction. The
large source file was not hashed as a whole: the range hashes and delivered
cutout identify the retrieved data. The author's separate Zenodo reduction
was evaluated as an alternative but is NOT the source of these frames.

source-display.fits preserves calibrated linear SCI, ERR and WHT around the
displayed region. All displayed source pixels are finite and covered; no
replacement occurs there. A small number of missing outer-context pixels
are assigned their nearest valid SCI value. scene.npz includes that missing
component and its area fractions. Every frame is also evaluated with zero
and twice that fill; sensitivity is in provenance.json. This is a local
assumption, not a recovery or upper bound on saturated stellar flux. No
independent input-exposure saturation audit or absolute calibration is claimed.

## Forward display model

F162M has pivot wavelength approximately 1.626 um. The unchanged simulation
PSFs are monochromatic 1.65 um. This close but nonidentical band match, a
spatially constant on-axis PSF, and arbitrary alignment of source axes to
simulation pupil remain assumptions. The observed JWST PSF, diffraction
spikes, drizzle response and observational noise remain in the scene.

Surface brightness in MJy/sr is averaged by exact rectangular pixel overlap
onto the simulation angular lattice. No background subtraction or flux
renormalization is performed. Each complete 768x768 PSF has unit total
flux. All convolution is linear with sufficient zero padding; the 961x961
scene covers the entire kernel reach of the central 193x193 display. No
PSF wing is discarded and no recentering occurs. Source pixels outside
this context cannot reach the displayed field under the finite saved kernel.

The JWST reference is the resampled observed source. The optional ideal
2.2 m reference adds the same model's zero-aberration pupil PSF; it also
retains JWST's original response. The other panels add the existing zero-DM,
v1 residual and v2 residual PSFs. They never enter the AO loop.

One fixed asinh transfer and single-band magma palette applies to all frames
and panels, after convolution. Bright/dark clipping affects display only.
The images are false-colour intensity, not the ESA multiband publicity image.
All 159 original replay timestamps are retained, including each frame near
736 (0.981333333 s). Existing Strehl values retain their original definition
from point-source PSFs; they are not derived from the extended Orion image.

The full original parameter draft, all assumptions and loss-of-lock repair
evidence remain in the site's separate NGS publication. No 2 m, 2.2 m or
42 m simulation was rerun for this image experiment.
''')
 with (out/'README.md').open('a') as f:f.write('\n## Standalone animation\n\norion-comparison.webp is a lossless 40-second animation of the same 159\nimage times, with the full 1500-sample Strehl curves and the 0.981333 s\nmarker. It repeats the same 2-second record. Timing is recorded in\nmovie-timing.json; no image or time interpolation is introduced.\n')
 render_movie(out,replay)
 seal(out,entry)

def seal(out,entry):
 files={str(p.relative_to(out)):{'bytes':p.stat().st_size,'sha256':sha(p),'media_type':'image/webp' if p.suffix=='.webp' else 'image/png' if p.suffix=='.png' else 'application/json' if p.suffix=='.json' else 'application/octet-stream' if p.suffix in ('.npz','.fits') else 'text/plain'} for p in sorted(out.rglob('*')) if p.is_file() and p.name!='manifest.json'}
 digest=hashlib.sha256(json.dumps(files,sort_keys=True,separators=(',',':')).encode()).hexdigest();identity='orion-ngs-'+digest[:16]
 write(out/'manifest.json',{'schema':'ao-explorer.orion-replay-manifest.v1','id':identity,'files':files})
 target=WEB/'derived'/identity
 if target.exists():assert sha(target/'manifest.json')==sha(out/'manifest.json')
 else:shutil.copytree(out,target)
 entry['orionReplay']={'schema':'ao-explorer.orion-replay-entry.v1','id':identity,'manifest':'../derived/'+identity+'/manifest.json','manifest_bytes':(target/'manifest.json').stat().st_size,'manifest_sha256':sha(target/'manifest.json')}
 write(WEB/'data/current.json',entry)
 print(json.dumps({'id':identity,'bytes':sum(f['bytes'] for f in files.values())}),flush=True)

if __name__=='__main__':main()
