"""Render a calibrated F164N scene with archived 2.2 m OPDs, never an AO run.

Requires NumPy, SciPy, Astropy, Pillow and Matplotlib. Run with two native threads.
The MAST range extraction in --source-dir supplies SCI/ERR/WHT arrays and headers.
"""
from __future__ import annotations
import argparse, hashlib, json, shutil
from pathlib import Path
import numpy as np
from scipy import fft, sparse, ndimage
from scipy.signal import convolve2d, fftconvolve
from astropy.io import fits
from astropy.wcs import WCS
from astropy.wcs.utils import proj_plane_pixel_scales
from PIL import Image, ImageDraw, ImageFont
from matplotlib import colormaps, get_data_path

WAVELENGTH=1.65e-6
DETAIL=384
WIDE=(930,1152)
CENTER=(7650.,3450.)
DETAIL_CENTER=(8090.,3400.)
LO,HI,SOFT=30.,400.,15.
CREDIT='NASA / ESA / CSA JWST NIRCam | ERS 1288, O. Berne / PDRs4All | MAST (STScI)'

def read(p): return json.loads(p.read_text())
def write(p,x): p.write_text(json.dumps(x,indent=2,allow_nan=False)+'\n')
def sha(p):
 h=hashlib.sha256()
 with p.open('rb') as f:
  for b in iter(lambda:f.read(8*1024**2),b''):h.update(b)
 return h.hexdigest()
def meta(p):return {'bytes':p.stat().st_size,'sha256':sha(p)}
def psf(opd,mask):
 f=np.zeros(mask.shape,complex);f[mask]=np.exp(2j*np.pi*opd[mask]/WAVELENGTH)
 p=abs(np.fft.fftshift(np.fft.fft2(np.fft.ifftshift(np.pad(f,256)))))**2
 return p/p.sum()
def weights(n,step,oldn,oldstep,c):
 edges=(np.arange(n+1)-n/2)*step/oldstep+c+.5
 a=np.maximum(0,np.minimum(edges[1:,None],np.arange(oldn)+1)-np.maximum(edges[:-1,None],np.arange(oldn)))/(step/oldstep)
 assert np.max(abs(a.sum(axis=1)-1))<1e-11
 return sparse.csr_matrix(a)
LUT=np.uint8(colormaps['magma'](np.linspace(0,1,256))[...,:3]*255)
def rgb(a):
 t=np.arcsinh(np.maximum(a-LO,0)/SOFT)/np.arcsinh((HI-LO)/SOFT)
 return Image.fromarray(np.flipud(LUT[np.rint(np.clip(t,0,1)*255).astype('uint8')]))

def prepare(src,out,step):
 record=read(src/'source-extraction.json'); headers={k:fits.Header.fromstring((src/(k+'-source-header.txt')).read_text(),sep='\n') for k in ['PRIMARY','SCI','ERR','WHT']}
 ph,h=headers['PRIMARY'],headers['SCI'];shape=(h['NAXIS2'],h['NAXIS1']);w=WCS(h);scale=proj_plane_pixel_scales(w)*3600
 assert ph['PUPIL']=='F164N' and ph['FILTER']=='F150W2' and h['BUNIT']=='MJy/sr' and np.allclose(scale,scale[0],rtol=1e-11)
 arrays={}
 for name in ['SCI','ERR','WHT']:
  p=src/(name+'.bin');expected=next(x for x in record['ranges'] if x['name']==name)
  assert meta(p)=={k:expected[k] for k in ['bytes','sha256']}
  arrays[name]=np.memmap(p,dtype='>f4',mode='r',shape=shape)
 native=float(scale[0]); contexts={};quality={};source_cuts={}
 for label,center,dims in [('wide',CENTER,(WIDE[0]+768,WIDE[1]+768)),('detail',DETAIL_CENTER,(DETAIL+768,DETAIL+768))]:
  cy,cx=center[1],center[0]; halfy=dims[0]*step/native/2;halfx=dims[1]*step/native/2
  x0,x1=int(np.floor(cx-halfx))-2,int(np.ceil(cx+halfx))+3;y0,y1=int(np.floor(cy-halfy))-2,int(np.ceil(cy+halfy))+3
  ss=np.s_[y0:y1,x0:x1];a=np.array(arrays['SCI'][ss],dtype='f8');err=arrays['ERR'][ss];weight=arrays['WHT'][ss]
  bad=~np.isfinite(a)|~np.isfinite(err)|(weight<=0)|~np.isfinite(weight)
  near=ndimage.distance_transform_edt(bad,return_distances=False,return_indices=True);filled=a.copy();filled[bad]=a[tuple(near[:,bad])]
  wy=weights(dims[0],step,a.shape[0],native,cy-y0);wx=weights(dims[1],step,a.shape[1],native,cx-x0)
  area=lambda z:(wx@(wy@z).T).T
  scene=area(filled);missing=area(np.where(bad,filled,0));fraction=area(bad.astype(float))
  view=np.s_[384:-384,384:-384];display_bad=int(np.count_nonzero(fraction[view]))
  if label=='detail':assert display_bad==0,'No missing source samples allowed in the magnifier'
  np.savez_compressed(out/f'{label}-scene.npz',surface_brightness_mjy_sr=scene.astype('f4'),missing_context_component_mjy_sr=missing.astype('f4'),missing_area_fraction=fraction.astype('f4'),pixel_arcsec=step)
  contexts[label]=(scene,missing,view);source_cuts[label]=(x0,x1,y0,y1)
  quality[label]={'context_bounds_xy':source_cuts[label],'context_bad_native_pixels':int(bad.sum()),'context_native_pixels':int(bad.size),'display_bad_resampled_pixels':display_bad,'display_min_mjy_sr':float(scene[view].min()),'display_max_mjy_sr':float(scene[view].max())}
 # Include unmodified native SCI/ERR/WHT of the detail, with its exact cutout WCS.
 rad=int(np.ceil(DETAIL*step/native/2))+1;cx,cy=map(int,DETAIL_CENTER);bounds=[cx-rad,cx+rad+1,cy-rad,cy+rad+1];x0,x1,y0,y1=bounds
 hdus=[fits.PrimaryHDU(header=ph)]
 for name in arrays:
  ch=headers[name].copy()
  if 'CRPIX1' in ch:ch['CRPIX1']-=x0;ch['CRPIX2']-=y0
  if name!='SCI':ch['BUNIT']=headers[name].get('BUNIT','')
  ch['HISTORY']='Exact spatial extraction for the AO Explorer; pixel values unchanged.'
  hdus.append(fits.ImageHDU(np.array(arrays[name][y0:y1,x0:x1]),header=ch,name=name))
 fits.HDUList(hdus).writeto(out/'source-detail.fits.gz',overwrite=True,checksum=True)
 # Complete mosaic for context only. Block means in linear intensity, not a new scene.
 a=arrays['SCI'];fac=10;ny,nx=shape;pad=np.full((int(np.ceil(ny/fac))*fac,int(np.ceil(nx/fac))*fac),np.nan,dtype='f4');pad[:ny,:nx]=a
 blocks=pad.reshape(pad.shape[0]//fac,fac,pad.shape[1]//fac,fac);valid=np.isfinite(blocks);den=valid.sum(axis=(1,3));num=np.where(valid,blocks,0).sum(axis=(1,3),dtype='f8');overview=np.divide(num,den,out=np.zeros_like(num),where=den>0)
 im=rgb(overview);pix=np.array(im);pix[np.flipud(den==0)]=[32,37,42];im=Image.fromarray(pix);draw=ImageDraw.Draw(im)
 for center,dims,col in [(CENTER,WIDE,'#8cd8ff'),(DETAIL_CENTER,(DETAIL,DETAIL),'#ffe7a5')]:
  cx,cy=center;hh,ww=np.array(dims)*step/native/2;draw.rectangle(((cx-ww)/fac,(ny-(cy+hh))/fac,(cx+ww)/fac,(ny-(cy-hh))/fac),outline=col,width=2)
 im.save(out/'source-context.png')
 coords=w.pixel_to_world(*DETAIL_CENTER)
 source={'object':'Orion Nebula','product':ph['FILENAME'],'program':1288,'filter':'F164N (with F150W2 blocking filter)','pivot_wavelength_um':1.645,'bandwidth_um':.020,'simulation_wavelength_um':1.65,'bunit':'MJy/sr','calibration_version':ph['CAL_VER'],'crds_context':ph['CRDS_CTX'],'date_obs':ph['DATE-OBS'],'native_dimensions_xy':[nx,ny],'native_pixel_arcsec':native,'field_arcsec':[WIDE[1]*step,WIDE[0]*step],'mosaic_field_arcsec':[nx*native,ny*native],'source_center_xy_zero_based':CENTER,'detail_center_xy_zero_based':DETAIL_CENTER,'detail_center_icrs_deg':[float(coords.ra.deg),float(coords.dec.deg)],'detail_cutout_bounds_xy':bounds,'url':record['url'],'credit':CREDIT,'data_policy':'https://archive.stsci.edu/publishing/data-use','quality':quality}
 write(out/'source-extraction.json',record)
 return contexts,source

def mask_overviews(out,maximum):
 """One exclusion mask across both states and every time; threshold 1% of span."""
 threshold=(HI-LO)*.01
 small=np.flipud(maximum.reshape(465,2,576,2).max(axis=(1,3)))
 mask=small>threshold
 yy,xx=np.indices(mask.shape);hatch=np.where(((xx+yy)//5)%2,52,76).astype('uint8')
 colour=np.repeat(hatch[:,:,None],3,axis=2)
 for p in sorted((out/'frames').glob('*.webp')):
  a=np.array(Image.open(p).convert('RGB'))
  for j in range(2):a[:465,j*576:(j+1)*576][mask]=colour[mask]
  Image.fromarray(a).save(p,lossless=True,method=3)
 a=np.array(Image.open(out/'field-source.png'));a[mask]=colour[mask];Image.fromarray(a).save(out/'field-source.png')
 Image.fromarray(np.uint8(mask)*255).save(out/'overview-exclusion-mask.png')
 np.savez_compressed(out/'missing-sensitivity-map.npz',maximum_change_mjy_sr=maximum.astype('f4'),threshold_mjy_sr=threshold)
 return {'threshold_mjy_sr':threshold,'criterion':'Maximum absolute zero/twice-fill sensitivity across both model states and all 159 times; mask if above 1% of the fixed display span. Same mask in every overview. This is not a bound on unknown source flux.','masked_overview_pixels':int(mask.sum()),'overview_pixels':int(mask.size),'masked_fraction':float(mask.mean()),'maximum_unmasked_tested_change_mjy_sr':float(small[~mask].max())}

def movie(out,replay,data):
 f=str(Path(get_data_path())/'fonts/ttf/DejaVuSans.ttf');font=ImageFont.truetype(f,16);small=ImageFont.truetype(f,12);title=ImageFont.truetype(f,23)
 base=Image.new('RGB',(1200,1120),'#f7f5ef');d=ImageDraw.Draw(base);d.text((24,12),'Orion F164N | calibrated sky, recorded AO correction',font=title,fill='#20252a')
 d.text((24,44),'1.645 um observed band | 1.65 um model PSFs | one fixed intensity scale | no AO rerun',font=small,fill='#444')
 for j,label in enumerate(['Original v1','Repaired v2']):d.text((24+600*j,64),label+' | 59.17 x 47.77 arcsec',font=font,fill=['#b3541e','#4d7a2a'][j])
 zy=592;labels=['Observed JWST','No correction','Original v1','Repaired v2'];cols=['#333','#777','#b3541e','#4d7a2a']
 for j,l in enumerate(labels):d.text((24+294*j,zy-24),l+' | 19.72 arcsec detail',font=small,fill=cols[j])
 ref=Image.open(out/'reference.png').crop((0,0,DETAIL,DETAIL));base.paste(ref.resize((270,270),Image.Resampling.LANCZOS),(24,zy))
 y0,y1=909,1022;x0,x1=65,1160
 def xy(t,y):return x0+(x1-x0)*t/2,y1-(y1-y0)*y
 d.rectangle((x0,y0,x1,y1),fill='white',outline='#bbb')
 for v in [0,.5,1]:
  y=xy(0,v)[1];d.line((x0,y,x1,y),fill='#ddd');d.text((27,y-7),str(v),font=small,fill='#555')
 for t in [0,.5,1,1.5,2]:d.text((xy(t,0)[0]-8,y1+3),str(t)+' s',font=small,fill='#555')
 m=replay['metrics'];times=m['time_s'];lx=xy(data['loss_time_s'],0)[0];d.line((lx,y0,lx,y1),fill='#af3351',width=2);d.text((lx+5,y0+3),'v1 loss: 0.981333 s',font=small,fill='#af3351')
 for vals,col in [(m['uncorrected_strehl'],cols[1]),(m['v1']['strehl'],cols[2]),(m['v2']['strehl'],cols[3])]:d.line([xy(t,y) for t,y in zip(times,vals)],fill=col,width=2)
 d.text((24,1045),'Point-source Strehl | 1500 saved samples | 40 s replay, 20x slower | single-band false colour',font=small,fill='#333')
 d.text((24,1065),'30–400 MJy/sr, fixed asinh. Gray hatch: excluded missing-data sensitivity. JWST PSF/noise retained.',font=small,fill='#333')
 d.text((24,1085),CREDIT,font=small,fill='#333');frames=[];box=data['detail_box_fraction']
 for k in data['indices']:
  a=Image.open(out/'frames'/f'{k:04}.webp');im=base.copy();draw=ImageDraw.Draw(im)
  for j in range(2):
   im.paste(a.crop((j*576,0,(j+1)*576,465)),(24+600*j,89));draw.rectangle((24+600*j+box[0]*576,89+box[1]*465,24+600*j+(box[0]+box[2])*576,89+(box[1]+box[3])*465),outline='#ffe7a5',width=2)
  for j in range(3):im.paste(a.crop((j*DETAIL,465,(j+1)*DETAIL,849)).resize((270,270),Image.Resampling.LANCZOS),(24+294*(j+1),zy))
  draw.text((24,875),f't = {times[k]:.6f} s | frame {k}/1499 | '+('v1 reconstruction rejected' if k>=736 else 'before first v1 rejection'),font=font,fill='#333')
  x=xy(times[k],0)[0];draw.line((x,y0,x,y1),fill='#111',width=2);frames.append(im.resize((960,896),Image.Resampling.LANCZOS))
 durations=np.diff([round(times[k]*20000) for k in data['indices']]+[40000]).tolist();frames[-1].save(out/'poster.png')
 frames[0].save(out/'science-comparison.webp',save_all=True,append_images=frames[1:],duration=durations,loop=0,lossless=False,quality=92,method=4)
 with Image.open(out/'science-comparison.webp') as check:
  assert check.n_frames==len(frames);total=0
  for k in range(check.n_frames):check.seek(k);check.load();total+=check.info['duration']
  assert total==40000
 write(out/'movie-timing.json',{'duration_ms':40000,'indices':data['indices'],'frame_durations_ms':durations,'temporal_interpolation':False,'format':'animated WebP preview, quality 92; site frames remain lossless','dimensions':[960,896]})

def main(args):
 out=args.source_dir/'bundle';out.mkdir(exist_ok=True);(out/'frames').mkdir(exist_ok=True)
 web=args.web_dir;entry=read(web/'data/current.json');rp=(web/'data'/entry['ngsReplay']['manifest']).resolve();parent=read(rp);assert meta(rp)=={'bytes':entry['ngsReplay']['manifest_bytes'],'sha256':entry['ngsReplay']['manifest_sha256']}
 replay=read(rp.parent/'data.json');prior=read(rp.parent/'provenance.json');assert meta(rp.parent/'data.json')=={k:parent['files']['data.json'][k] for k in ['bytes','sha256']}
 folders=[args.archive_root/'outputs/robo_ao2_ngs/20261024-first-trajectory/attempt-04',args.archive_root/'outputs/robo_ao2_ngs/20261024-loss-of-lock-repair/trajectory-v2'];inputs={}
 for folder in folders:
  for name in ['pre_update_residual_opd_m.npy','science-psfs.npz']:
   p=folder/name;key=str(p.relative_to(args.archive_root));assert meta(p)==prior['inputs'][key];inputs[key]=meta(p)
 p=folders[0]/'atmosphere_opd_m.npy';key=str(p.relative_to(args.archive_root));assert meta(p)==prior['inputs'][key];inputs[key]=meta(p)
 saved=[dict(np.load(f/'science-psfs.npz')) for f in folders];mask=saved[0]['pupil_mask'].astype(bool);assert np.array_equal(mask,saved[1]['pupil_mask'])
 step=float(np.diff(saved[0]['x_angle_rad'])[0])*180/np.pi*3600;contexts,source=prepare(args.source_dir,out,step);ideal=psf(np.zeros(mask.shape),mask);assert np.max(abs(ideal-saved[0]['ideal']))<1e-14;peak=float(ideal.max());plans={}
 for label,(scene,missing,view) in contexts.items():
  shape=tuple(fft.next_fast_len(n+767,real=True) for n in scene.shape);plans[label]=(shape,fft.rfft2(scene,s=shape,workers=2),fft.rfft2(missing,s=shape,workers=2))
 maxflux=0.;maximum_missing=np.zeros(WIDE)
 def observe(p,label,missing=False):
  nonlocal maxflux
  scene=contexts[label][1 if missing else 0];shape,spec,mspec=plans[label];full=fft.irfft2((mspec if missing else spec)*fft.rfft2(p,s=shape,workers=2),s=shape,workers=2)
  expected=scene.sum()*p.sum();maxflux=max(maxflux,float(abs(full.sum()-expected)/max(abs(expected),1)))
  h,w=scene.shape;return full[768:h,768:w]
 delta=np.zeros((768,768));delta[384,384]=1;deltaerror=0
 for label,(scene,missing,view) in contexts.items():deltaerror=max(deltaerror,float(abs(observe(delta,label)-scene[view]).max()))
 assert deltaerror<1e-8
 small=np.arange(15.).reshape(3,5);kernel=np.arange(24.).reshape(4,6);directerror=float(abs(fftconvolve(small,kernel)-convolve2d(small,kernel)).max());assert directerror<1e-10
 refs=Image.new('RGB',(768,384));refs.paste(rgb(contexts['detail'][0][contexts['detail'][2]]),(0,0));refs.paste(rgb(observe(ideal,'detail')),(384,0));refs.save(out/'reference.png')
 rgb(contexts['wide'][0][contexts['wide'][2]]).resize((576,465),Image.Resampling.LANCZOS).save(out/'field-source.png')
 scale=Image.fromarray(np.tile(LUT[None,:,:],(16,1,1)));scale.save(out/'intensity-scale.png')
 maps=[np.load(folders[0]/'atmosphere_opd_m.npy',mmap_mode='r')]+[np.load(f/'pre_update_residual_opd_m.npy',mmap_mode='r') for f in folders]
 metricerror=0.;snapshoterror=0.;count=0;sensitivity=[];linear_examples={}
 for pos,k in enumerate(replay['indices']):
  atlas=Image.new('RGB',(1152,849));sens={'frame':k}
  for j,a in enumerate(maps):
   p=psf(a[k],mask);expected=replay['metrics']['uncorrected_strehl'][k] if j==0 else replay['metrics'][['v1','v2'][j-1]]['strehl'][k];metricerror=max(metricerror,abs(float(p.max()/peak)-expected))
   if j and 'frame_'+str(k) in saved[j-1]:snapshoterror=max(snapshoterror,float(abs(p-saved[j-1]['frame_'+str(k)]).max()));count+=1
   zoom=observe(p,'detail');zm=observe(p,'detail',True);sens['detail_'+str(j)]=float(abs(zm).max());atlas.paste(rgb(zoom),(j*384,465))
   if j:
    wide=observe(p,'wide');wm=observe(p,'wide',True);sens['wide_'+str(j)]=float(abs(wm).max());maximum_missing=np.maximum(maximum_missing,abs(wm));atlas.paste(rgb(wide).resize((576,465),Image.Resampling.LANCZOS),((j-1)*576,0))
   if k in [0,736,1499]:linear_examples[f'detail_{k}_{j}']=zoom.astype('f4')
  atlas.save(out/'frames'/f'{k:04}.webp',lossless=True,method=3);sensitivity.append(sens)
  if pos%20==0:print(f'rendered {pos+1}/{len(replay["indices"])}',flush=True)
 assert count==15 and snapshoterror<1e-14 and metricerror<1e-12 and maxflux<1e-12
 maskcheck=mask_overviews(out,maximum_missing)
 np.savez_compressed(out/'linear-samples.npz',**linear_examples)
 native=source['native_pixel_arcsec'];offset=(np.array(DETAIL_CENTER)-CENTER)*native/step
 box=[.5+(offset[0]-DETAIL/2)/WIDE[1],.5-(offset[1]+DETAIL/2)/WIDE[0],DETAIL/WIDE[1],DETAIL/WIDE[0]]
 check={'overview_exclusion':maskcheck,'all_ao_inputs_hash_verified':True,'saved_psf_checks':count,'saved_psf_max_abs_error':snapshoterror,'sampled_strehl_values':3*len(replay['indices']),'sampled_strehl_max_abs_error':metricerror,'full_convolution_flux_max_relative_error':maxflux,'delta_kernel_max_abs_error_mjy_sr':deltaerror,'direct_convolution_oracle_max_abs_error':directerror,'missing_context_max_perturbation_mjy_sr':{key:max(row[key] for row in sensitivity) for key in sensitivity[0] if key!='frame'}}
 data={'schema':'ao-explorer.science-replay-data.v1','frames':1500,'indices':replay['indices'],'parent_replay_id':entry['ngsReplay']['id'],'parent_replay_data_sha256':sha(rp.parent/'data.json'),'loss_frame':736,'loss_time_s':736/750,'wavelength_m':WAVELENGTH,'pixel_arcsec':step,'detail_field_arcsec':DETAIL*step,'detail':DETAIL,'overview':[576,465],'atlas':[1152,849],'detail_box_fraction':box,'source':source,'display':{'type':'asinh','min_mjy_sr':LO,'max_mjy_sr':HI,'softening_mjy_sr':SOFT,'colormap':'magma','fixed_for_all_frames_and_panels':True},'checks':check}
 write(out/'data.json',data);write(out/'sensitivity.json',sensitivity)
 write(out/'provenance.json',{'schema':'ao-explorer.science-provenance.v1','simulation_rerun':False,'source':source,'archive_inputs':inputs,'parent_replay_entry':entry['ngsReplay'],'checks':check,'processing':{'source':'Calibrated SCI surface brightness in MJy/sr, with ERR/WHT quality checks. Negative values retained until display.','convolution':'Float64, full linear FFT convolution of pixel-area averaged intensity; native 768x768 unit-flux 1.65 um PSF with tilt retained, no recentering or size multiplier.','boundary':'Both fields have real source context covering the entire kernel; no external-sky extrapolation.','missing':'Nearest-valid fill where SCI/ERR are nonfinite or WHT is nonpositive/nonfinite. Wide field can include such points. Detail includes none directly. Zero and twice nominal fill sensitivity is measured for every frame; it is not a bound on unknown saturated flux.','band':'F164N 1.645 um, bandwidth 0.020 um approximated by archived monochromatic 1.65 um PSF. No band integration, colour composite or continuum subtraction.','source_psf':'Observed JWST PSF, mosaic resampling, diffraction spikes and noise retained; no deconvolution. Effective image response includes both JWST and model PSFs.','field':'One on-axis PSF over the selected 59.17 x 47.77 arcsec field; no anisoplanatism or real instrument footprint prediction.','display':'Fixed asinh 30–400 MJy/sr, softening 15 MJy/sr, magma pseudocolour after linear convolution; lower and upper tails clipped for display only. Native axes, vertical flip; pupil alignment is assumed.','time':'159 archived image times, 1500 original point-source Strehl samples; no interpolation, exposure integration, new AO trajectory or extra detector noise.'}})
 shutil.copy2(Path(__file__),out/'exporter.py')
 movie(out,replay,data)
 # README is separately maintained, not invented by the renderer.
 shutil.copy2(args.source_dir/'METHODS.md',out/'README.md')
 files={str(p.relative_to(out)):{**meta(p),'media_type':'image/webp' if p.suffix=='.webp' else 'image/png' if p.suffix=='.png' else 'application/json' if p.suffix=='.json' else 'application/octet-stream' if p.suffix in ['.npz','.gz'] else 'text/plain'} for p in sorted(out.rglob('*')) if p.is_file() and p.name!='manifest.json'}
 identity='orion-f164n-'+hashlib.sha256(json.dumps(files,sort_keys=True,separators=(',',':')).encode()).hexdigest()[:16]
 write(out/'manifest.json',{'schema':'ao-explorer.science-replay-manifest.v1','id':identity,'files':files});target=web/'derived'/identity
 if not target.exists():shutil.copytree(out,target)
 else:assert sha(target/'manifest.json')==sha(out/'manifest.json')
 # Retain the old colour bundles and their stable download URLs as archives.
 entry.pop('ngc602Replay',None);entry.pop('ngc602Video',None)
 entry['scienceReplay']={'schema':'ao-explorer.science-replay-entry.v1','id':identity,'manifest':'../derived/'+identity+'/manifest.json','manifest_bytes':(target/'manifest.json').stat().st_size,'manifest_sha256':sha(target/'manifest.json')};write(web/'data/current.json',entry)
 print(json.dumps({'id':identity,'bundle_bytes':sum(v['bytes'] for v in files.values()),'checks':check}),flush=True)
if __name__=='__main__':
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--archive-root',type=Path,required=True);p.add_argument('--source-dir',type=Path,required=True);p.add_argument('--web-dir',type=Path,default=Path(__file__).resolve().parents[1]/'site');main(p.parse_args())
