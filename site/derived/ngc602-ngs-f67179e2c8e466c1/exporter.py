"""Full-field NGC 602 RGB illustration using saved 2.2 m OPDs only."""
from __future__ import annotations
import hashlib, json, shutil, io, xml.etree.ElementTree as ET
from pathlib import Path
import numpy as np
from scipy import fft, sparse
from PIL import Image, ImageCms, ImageDraw, ImageFont
from matplotlib import get_data_path
ROOT=Path(__file__).resolve().parents[2]
WORK=ROOT/'outputs/ngc602_ngs'; WEB=ROOT/'web/ao-explorer'
WAVELENGTH=1.65e-6; DETAIL=384; OVERVIEW=576
CREDIT='ESA/Webb, NASA & CSA, P. Zeidler, E. Sabbi, A. Nota, M. Zamani (ESA/Webb)'
def read(p):return json.loads(p.read_text())
def write(p,x):p.write_text(json.dumps(x,indent=2,allow_nan=False)+'\n')
def sha(p):
 h=hashlib.sha256()
 with p.open('rb') as f:
  for b in iter(lambda:f.read(8*1024**2),b''):h.update(b)
 return h.hexdigest()
def psf(opd,mask):
 f=np.zeros(mask.shape,complex);f[mask]=np.exp(2j*np.pi*opd[mask]/WAVELENGTH)
 p=abs(np.fft.fftshift(np.fft.fft2(np.fft.ifftshift(np.pad(f,256)))))**2
 return p/p.sum()
def weights(n,step,oldn,oldstep,center=None,edge=False):
 center=(oldn-1)/2 if center is None else center
 edges=(np.arange(n+1)-n/2)*step/oldstep+center+.5
 lo=np.arange(oldn);hi=lo+1
 a=np.clip(np.minimum(edges[1:,None],hi)-np.maximum(edges[:-1,None],lo),0,None)/(step/oldstep)
 if edge:
  a[:,0]+=np.clip(np.minimum(edges[1:],0)-edges[:-1],0,None)/(step/oldstep)
  a[:,-1]+=np.clip(edges[1:]-np.maximum(edges[:-1],oldn),0,None)/(step/oldstep)
 return sparse.csr_matrix(a)
def area(a,shape,step,oldstep,center=None):
 h,w=shape; cy,cx=((a.shape[0]-1)/2,(a.shape[1]-1)/2) if center is None else center
 wy=weights(h,step,a.shape[0],oldstep,cy,True);wx=weights(w,step,a.shape[1],oldstep,cx,True)
 assert np.max(abs(np.array(wy.sum(axis=1))-1))<1e-11 and np.max(abs(np.array(wx.sum(axis=1))-1))<1e-11
 return np.stack([(wx@(wy@a[:,:,c]).T).T for c in range(3)],axis=-1).astype('f4')
def decode(a):return np.where(a<=.04045,a/12.92,((a+.055)/1.055)**2.4)
def rgb(a):
 a=np.clip(a,0,1);a=np.where(a<=.0031308,12.92*a,1.055*a**(1/2.4)-.055)
 return Image.fromarray(np.rint(a*255).astype('uint8'))
def main():
 out=WORK/'bundle';out.mkdir(exist_ok=True);(out/'frames').mkdir(exist_ok=True)
 entry=read(WEB/'data/current.json');rp=(WEB/'data'/entry['ngsReplay']['manifest']).resolve();replay=read(rp.parent/'data.json');prior=read(rp.parent/'provenance.json')
 folders=[ROOT/'outputs/robo_ao2_ngs/20261024-first-trajectory/attempt-04',ROOT/'outputs/robo_ao2_ngs/20261024-loss-of-lock-repair/trajectory-v2']
 inputs={}
 for folder in folders:
  for name in ['pre_update_residual_opd_m.npy','science-psfs.npz']:
   p=folder/name;key=str(p.relative_to(ROOT));actual={'bytes':p.stat().st_size,'sha256':sha(p)};assert prior['inputs'][key]==actual;inputs[key]=actual
 p=folders[0]/'atmosphere_opd_m.npy';key=str(p.relative_to(ROOT));actual={'bytes':p.stat().st_size,'sha256':sha(p)};assert prior['inputs'][key]==actual;inputs[key]=actual
 saved=[dict(np.load(p/'science-psfs.npz')) for p in folders];mask=saved[0]['pupil_mask'].astype(bool);assert np.array_equal(mask,saved[1]['pupil_mask'])
 step=float(np.diff(saved[0]['x_angle_rad'])[0])*180/np.pi*3600;coarse=2*step
 sourcepath=WORK/'weic2425c.jpg';im=Image.open(sourcepath);native_size=im.size
 xmp=ET.fromstring(im.info['xmp']);ns={'a':'http://www.communicatingastronomy.org/avm/1.0/','r':'http://www.w3.org/1999/02/22-rdf-syntax-ns#'}
 scales=[float(e.text) for e in xmp.findall('.//a:Spatial.Scale/r:Seq/r:li',ns)];native=abs(scales[0])*3600;assert abs(scales[0])==abs(scales[1])
 profile=ImageCms.ImageCmsProfile(io.BytesIO(im.info['icc_profile']));profile_name=ImageCms.getProfileDescription(profile).strip()
 im=ImageCms.profileToProfile(im,profile,ImageCms.createProfile('sRGB'),outputMode='RGB');source=decode(np.asarray(im,dtype='f4')/255)
 field=[native*n for n in native_size];coarse_shape=[int(np.ceil(field[1]/coarse)),int(np.ceil(field[0]/coarse))]
 # Full source retained. At most half a computational pixel of edge extension.
 scene=area(source,coarse_shape,coarse,native)
 # The linked detail is supplemental to the two complete overview panels.
 center_xy=[.43*(native_size[0]-1),.48*(native_size[1]-1)]
 context=area(source,(DETAIL+768,DETAIL+768),step,native,center_xy[::-1]);detail_ref=context[384:384+DETAIL,384:384+DETAIL]
 ideal=psf(np.zeros(mask.shape),mask);assert np.max(abs(ideal-saved[0]['ideal']))<1e-14;peak=float(ideal.max())
 # Pixel mass is split by exact interval overlap. Kernel support and zero-angle stay fixed.
 # Old centers -384..383; new centers -384,-382,..384 (in native pixel units).
 edge=(np.arange(386)-192.5)*2;lo=np.arange(768)-384-.5
 kw=sparse.csr_matrix(np.clip(np.minimum(edge[1:,None],lo+1)-np.maximum(edge[:-1,None],lo),0,None))
 assert np.max(abs(np.array(kw.sum(axis=0))-1))<1e-14
 def bin_kernel(p):return (kw@(kw@p).T).T
 padded=np.pad(scene,((192,192),(192,192),(0,0)),mode='edge')
 shape=tuple(fft.next_fast_len(n+384,real=True) for n in padded.shape[:2]);spectrum=fft.rfft2(padded,s=shape,axes=(0,1),workers=2)
 ds=tuple(fft.next_fast_len(n+767,real=True) for n in context.shape[:2]);dspectrum=fft.rfft2(context,s=ds,axes=(0,1),workers=2)
 flux_error=0.;mass_error=0.
 def observe(p):
  nonlocal flux_error,mass_error
  q=bin_kernel(p);mass_error=max(mass_error,abs(q.sum()-1))
  full=fft.irfft2(spectrum*fft.rfft2(q.astype('f4'),s=shape,workers=2)[:,:,None],s=shape,axes=(0,1),workers=2)
  flux_error=max(flux_error,float(np.max(abs(full.sum(axis=(0,1),dtype='f8')/padded.sum(axis=(0,1),dtype='f8')-1))))
  wide=full[384:384+scene.shape[0],384:384+scene.shape[1]]
  dfull=fft.irfft2(dspectrum*fft.rfft2(p.astype('f4'),s=ds,workers=2)[:,:,None],s=ds,axes=(0,1),workers=2)
  zoom=dfull[768:768+DETAIL,768:768+DETAIL]
  return wide,zoom
 delta=np.zeros((768,768));delta[384,384]=1
 dw,dd=observe(delta);delta_error=max(float(abs(dw-scene).max()),float(abs(dd-detail_ref).max()));assert delta_error<2e-6
 oh=round(OVERVIEW*native_size[1]/native_size[0]);atlas_shape=[2*OVERVIEW,oh+DETAIL]
 def overview(a):return rgb(a).resize((OVERVIEW,oh),Image.Resampling.LANCZOS)
 ref=Image.new('RGB',(2*DETAIL,DETAIL));ref.paste(rgb(detail_ref),(0,0));idealwide,idealzoom=observe(ideal);ref.paste(rgb(idealzoom),(DETAIL,0));ref.save(out/'reference.png')
 overview(scene).save(out/'full-source.png');shutil.copy2(sourcepath,out/'source-original.jpg')
 # Region box at source angular coordinates, independent of overview downsampling.
 box=[(center_xy[0]*native-DETAIL*step/2)/field[0],(center_xy[1]*native-DETAIL*step/2)/field[1],DETAIL*step/field[0],DETAIL*step/field[1]]
 maps=[np.load(folders[0]/'atmosphere_opd_m.npy',mmap_mode='r')]+[np.load(p/'pre_update_residual_opd_m.npy',mmap_mode='r') for p in folders]
 metric_error=0.;snapshot_error=0.;checks=0
 for pos,k in enumerate(replay['indices']):
  atlas=Image.new('RGB',tuple(atlas_shape));
  for j,a in enumerate(maps):
   p=psf(a[k],mask);expected=replay['metrics']['uncorrected_strehl'][k] if j==0 else replay['metrics'][['v1','v2'][j-1]]['strehl'][k];metric_error=max(metric_error,abs(float(p.max()/peak)-expected))
   if j and 'frame_'+str(k) in saved[j-1]:snapshot_error=max(snapshot_error,float(abs(p-saved[j-1]['frame_'+str(k)]).max()));checks+=1
   wide,zoom=observe(p)
   if j:atlas.paste(overview(wide),((j-1)*OVERVIEW,0))
   atlas.paste(rgb(zoom),(j*DETAIL,oh))
  atlas.save(out/'frames'/f'{k:04}.webp',lossless=True,method=3)
  if pos%20==0:print(f'rendered {pos+1}/{len(replay["indices"])}',flush=True)
 assert checks==15 and snapshot_error<1e-14 and metric_error<1e-12 and flux_error<2e-6 and mass_error<1e-12
 source_meta={'object':'NGC 602','id':'weic2425c','page':'https://esawebb.org/images/weic2425c/','url':'https://cdn.esawebb.org/archives/images/large/weic2425c.jpg','sha256':sha(sourcepath),'bytes':sourcepath.stat().st_size,'dimensions':native_size,'native_pixel_arcsec':native,'scale_source':'Embedded AVM Spatial.Scale; original dimensions match AVM reference dimensions.','field_arcsec':field,'bands_um':[1.15,1.4,1.5,2.1,2.77,3.35,3.56,4.8,10],'credit':CREDIT,'license':'CC BY 4.0','license_url':'https://esawebb.org/copyright/','embedded_icc':profile_name}
 check={'all_ao_inputs_hash_verified':True,'saved_psf_checks':checks,'saved_psf_max_abs_error':snapshot_error,'sampled_strehl_max_abs_error':metric_error,'sampled_strehl_values':3*len(replay['indices']),'full_convolution_flux_max_relative_error_float32':flux_error,'delta_kernel_max_abs_error_linear_rgb':delta_error,'rebinned_kernel_mass_max_abs_error':mass_error}
 data={'schema':'ao-explorer.ngc602-replay-data.v1','frames':1500,'indices':replay['indices'],'parent_replay_id':entry['ngsReplay']['id'],'parent_replay_data_sha256':sha(rp.parent/'data.json'),'loss_frame':736,'loss_time_s':736/750,'wavelength_m':WAVELENGTH,'pixel_arcsec':step,'overview_pixel_arcsec':coarse,'detail_field_arcsec':DETAIL*step,'detail':DETAIL,'overview':[OVERVIEW,oh],'atlas':atlas_shape,'detail_box_fraction':box,'source':source_meta,'checks':check}
 write(out/'data.json',data)
 write(out/'provenance.json',{'schema':'ao-explorer.ngc602-provenance.v1','simulation_rerun':False,'source':source_meta,'archive_inputs':inputs,'parent_replay_entry':entry['ngsReplay'],'parent_replay_data_sha256':sha(rp.parent/'data.json'),'checks':check,'processing':{'precision':'float32 FFT; float64 PSFs and checks','source_transfer':'ICC-managed sRGB decoded to linear-light RGB; not calibrated astronomical intensity','convolution':'Same unit-flux 1.65 um PSF applied to each RGB channel; full 768x768 support and native tilt, no recentring or PSF scale multiplier','overview':'Full source footprint; pixel-area averaged to 2x native PSF grid. Kernel flux exactly redistributed by area overlap to 385x385. Final overview reduced with Lanczos.','detail':'Native PSF pixel grid; 384x384 output plus full 768 pixel surrounding source context; no missing source pixels','boundary':'Overview extends edge values by full kernel support. Unknown external sky affects outer ~19.8 arcsec; central magnifier is independent of this edge assumption.','orientation':'Source image axes retained; PSF row order assigned to image rows by convention, not a fitted sky/pupil alignment','field_assumption':'One spatially invariant on-axis PSF across entire ~3 arcmin field: illustrative only, not predicted wide-field AO correction','display':'One sRGB transfer for all frames and panels, no exposure/contrast adjustment, no colour reassignment; lossless WebP frames','time':'All 159 existing image times; no interpolation; Strehl remains native point-source metric'}})
 shutil.copy2(__file__,out/'exporter.py')
 (out/'README.md').write_text(f'''# NGC 602 through saved 2.2 m PSFs

Full official colour image, with a linked central-cluster detail. No AO run.

Credit: {CREDIT}. Source: https://esawebb.org/images/weic2425c/
CC BY 4.0: https://esawebb.org/copyright/ . Modified by resampling and convolution.
The unmodified source JPEG is included with its ICC and AVM metadata and hash.

This is a multiband colour illustration, not calibrated simulated science data.
The already processed NIRCam + MIRI image (1.15–10 um) is converted using its
embedded ICC profile to sRGB and decoded to linear-light RGB. That operation
does not undo the original astronomical stretches or recover band fluxes.
The same 1.65 um PSF is applied to each channel. The original JWST response,
diffraction spikes, nonlinear colour choices and observational noise remain.
No added detector noise, deconvolution or per-panel brightness fitting.

The source angular pixel scale comes from embedded AVM metadata. Both main
panels retain the entire image; the supplementary {DETAIL*step:.3f} arcsec
magnifier marks the same central region. PSFs keep their original angular
size and tilt. The overview uses a coarser computational grid (2 native
PSF cells), with exact area redistribution of every PSF pixel's flux.
The magnifier uses native PSF sampling. Full linear FFT convolution is used.
Outside the original full-field boundary, edge values are extended; the
outer ~19.8 arcsec depend on this unknown-sky assumption. The central detail
has enough real context for the entire kernel and uses no extrapolated sky.
The two grid choices are for display only; point-source Strehl is always
verified on the original native PSF, without binning.

A constant on-axis PSF across ~3 arcminutes is a visualization assumption.
Anisoplanatism, band-specific PSFs and the actual instrument field are not
modelled. These images do not predict real Robo-AO-2 wide-field performance.
All original instrument draft assumptions and repair evidence remain on the
site. All 159 existing replay times and all 1500 curve points are retained.
Frame 736 at 0.981333 s is the first rejected v1 reconstruction. The default
late frame highlights the subsequent divergence, not a discontinuity at 736.

The standalone 40 s compressed WebP preview (quality 92, width 960 pixels;
interactive site frames remain lossless) repeats the same 2 s record at 20x slower
speed, with no temporal interpolation. Timing is in movie-timing.json.
''')
 render_movie(out,replay,data)
 seal(out,entry)
def render_movie(out,replay,data):
 fontfile=str(Path(get_data_path())/'fonts/ttf/DejaVuSans.ttf');font=ImageFont.truetype(fontfile,16);small=ImageFont.truetype(fontfile,12);title=ImageFont.truetype(fontfile,23)
 ow,oh=data['overview'];base=Image.new('RGB',(1200,1140),'#f7f5ef');d=ImageDraw.Draw(base)
 d.text((24,15),'NGC 602 | full field, same recorded atmosphere',font=title,fill='#20252a')
 d.text((24,48),'Original v1',font=font,fill='#b3541e');d.text((624,48),'Repaired v2',font=font,fill='#4d7a2a')
 # Overview row 576 x 465, followed by 4 matched magnifiers.
 zoom_y=oh+110;ref=Image.open(out/'reference.png').crop((0,0,DETAIL,DETAIL))
 labels=['Observed JWST','No correction','Original v1','Repaired v2'];colors=['#333','#777','#b3541e','#4d7a2a']
 for j,label in enumerate(labels):d.text((24+294*j,zoom_y-25),label+' | linked detail',font=small,fill=colors[j])
 base.paste(ref.resize((270,270),Image.Resampling.LANCZOS),(24,zoom_y))
 chart_y=zoom_y+320;x0,x1,y0,y1=65,1160,chart_y,chart_y+125
 def xy(t,y):return x0+(x1-x0)*t/2,y1-(y1-y0)*y
 d.rectangle((x0,y0,x1,y1),fill='white',outline='#bbb')
 for v in [0,.5,1]:
  y=xy(0,v)[1];d.line((x0,y,x1,y),fill='#ddd');d.text((27,y-7),str(v),font=small,fill='#555')
 m=replay['metrics'];times=m['time_s'];lx=xy(736/750,0)[0];d.line((lx,y0,lx,y1),fill='#af3351',width=2);d.text((lx+5,y0+3),'0.981333 s',font=small,fill='#af3351')
 for vals,col in [(m['uncorrected_strehl'],'#777'),(m['v1']['strehl'],'#b3541e'),(m['v2']['strehl'],'#4d7a2a')]:d.line([xy(t,y) for t,y in zip(times,vals)],fill=col,width=2)
 d.text((24,y1+14),'Point-source Strehl | 0–2 s | all 1500 saved samples | 40 s replay, 20x slower',font=small,fill='#333')
 d.text((24,y1+37),'Colour illustration: same 1.65 um PSF on all RGB channels; constant on-axis PSF over full field assumed.',font=small,fill='#333')
 d.text((24,y1+57),CREDIT,font=small,fill='#333');d.text((24,y1+75),'CC BY 4.0 | esawebb.org/images/weic2425c/ | Modified: resampling and extra blur from saved PSFs.',font=small,fill='#333')
 base=base.crop((0,0,1200,y1+100));frames=[];box=data['detail_box_fraction']
 for k in replay['indices']:
  a=Image.open(out/'frames'/f'{k:04}.webp');im=base.copy();draw=ImageDraw.Draw(im)
  for j in range(2):
   im.paste(a.crop((j*ow,0,(j+1)*ow,oh)),(24+600*j,75));draw.rectangle((24+600*j+box[0]*ow,75+box[1]*oh,24+600*j+(box[0]+box[2])*ow,75+(box[1]+box[3])*oh),outline='#ffe7a5',width=2)
  for j in range(3):im.paste(a.crop((j*DETAIL,oh,(j+1)*DETAIL,oh+DETAIL)).resize((270,270),Image.Resampling.LANCZOS),(24+294*(j+1),zoom_y))
  draw.text((24,zoom_y+282),f't = {times[k]:.6f} s | frame {k}/1499 | v1 '+('reconstruction rejected' if k>=736 else 'before first rejection'),font=font,fill='#333')
  x=xy(times[k],0)[0];draw.line((x,y0,x,y1),fill='#111',width=2);frames.append(im.resize((960,round(im.height*.8)),Image.Resampling.LANCZOS))
 durations=np.diff([round(times[k]*20000) for k in replay['indices']]+[40000]).tolist();assert sum(durations)==40000
 frames[-1].save(out/'poster.png');frames[0].save(out/'ngc602-comparison.webp',save_all=True,append_images=frames[1:],duration=durations,loop=0,lossless=False,quality=92,method=4)
 with Image.open(out/'ngc602-comparison.webp') as check:
  assert check.n_frames==len(frames);total=0
  for k in range(check.n_frames):check.seek(k);check.load();total+=check.info['duration']
  assert total==40000
 write(out/'movie-timing.json',{'duration_ms':40000,'indices':replay['indices'],'frame_durations_ms':durations,'temporal_interpolation':False,'format':'animated WebP preview, quality 92; site frames remain lossless','dimensions':frames[0].size})
def seal(out,entry):
 files={str(p.relative_to(out)):{'bytes':p.stat().st_size,'sha256':sha(p),'media_type':'image/webp' if p.suffix=='.webp' else 'image/png' if p.suffix=='.png' else 'image/jpeg' if p.suffix=='.jpg' else 'application/json' if p.suffix=='.json' else 'text/plain'} for p in sorted(out.rglob('*')) if p.is_file() and p.name!='manifest.json'}
 digest=hashlib.sha256(json.dumps(files,sort_keys=True,separators=(',',':')).encode()).hexdigest();identity='ngc602-ngs-'+digest[:16]
 write(out/'manifest.json',{'schema':'ao-explorer.ngc602-replay-manifest.v1','id':identity,'files':files});target=WEB/'derived'/identity
 if target.exists():assert sha(target/'manifest.json')==sha(out/'manifest.json')
 else:shutil.copytree(out,target)
 entry.pop('orionReplay',None);entry['ngc602Replay']={'schema':'ao-explorer.ngc602-replay-entry.v1','id':identity,'manifest':'../derived/'+identity+'/manifest.json','manifest_bytes':(target/'manifest.json').stat().st_size,'manifest_sha256':sha(target/'manifest.json')};write(WEB/'data/current.json',entry)
 print(json.dumps({'id':identity,'bytes':sum(f['bytes'] for f in files.values())}),flush=True)
if __name__=='__main__':main()
