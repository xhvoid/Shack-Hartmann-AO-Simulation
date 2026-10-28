"""Transcode the existing NGC 602 presentation; never import or run AO code."""
from __future__ import annotations
import argparse, hashlib, json, math, shutil, struct, subprocess
from pathlib import Path
import numpy as np
from PIL import Image
ROOT=Path(__file__).resolve().parents[2]
WEB=ROOT/'web/ao-explorer';WORK=ROOT/'outputs/ngc602_mp4';FPS=60

def read(p):return json.loads(p.read_text())
def write(p,x):p.write_text(json.dumps(x,indent=2,allow_nan=False)+'\n')
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def checked(p,meta):
 assert p.stat().st_size==meta['bytes'] and sha(p)==meta['sha256'],str(p)
 return p

def main(ffmpeg):
 WORK.mkdir(exist_ok=True);out=WORK/'bundle';out.mkdir(exist_ok=True);checks=WORK/'checks';checks.mkdir(exist_ok=True)
 entry=read(WEB/'data/current.json');parent=entry['ngc602Replay'];mp=(WEB/'data'/parent['manifest']).resolve()
 checked(mp,{'bytes':parent['manifest_bytes'],'sha256':parent['manifest_sha256']});manifest=read(mp)
 assert manifest['id']==parent['id']
 source=checked(mp.parent/'ngc602-comparison.webp',manifest['files']['ngc602-comparison.webp'])
 timing=read(checked(mp.parent/'movie-timing.json',manifest['files']['movie-timing.json']))
 data=read(checked(mp.parent/'data.json',manifest['files']['data.json']))
 assert timing['indices']==data['indices'] and timing['duration_ms']==40000 and data['loss_frame']==736
 # Integer arithmetic: output sample n occurs at n*1000/FPS milliseconds.
 # Each image is held until the next saved source boundary; no blending.
 boundaries=np.r_[0,np.cumsum(timing['frame_durations_ms'])]
 count=timing['duration_ms']*FPS//1000
 select=np.searchsorted(boundaries*FPS,np.arange(count)*1000,side='right')-1
 counts=np.bincount(select,minlength=len(timing['indices']));assert np.all(counts>0) and count==2400
 first=np.r_[0,np.cumsum(counts)[:-1]];delay_ms=first*1000/FPS-boundaries[:-1]
 assert delay_ms.min()>-1e-10 and delay_ms.max()<1000/FPS
 loss_pos=timing['indices'].index(736);selected_frames=[0,int(first[loss_pos]),count-1]
 source_refs={}
 with Image.open(source) as images:
  width,height=images.size;assert [width,height]==timing['dimensions'] and width%2==height%2==0
  assert images.n_frames==len(timing['indices'])
  video=out/'ngc602-2p2m-ao-comparison.mp4'
  command=[str(ffmpeg),'-y','-hide_banner','-loglevel','warning','-f','rawvideo','-pixel_format','rgb24','-video_size',f'{width}x{height}','-framerate',str(FPS),'-i','pipe:0','-an','-vf','scale=in_range=full:out_range=limited:out_color_matrix=bt709,setparams=range=limited:color_primaries=bt709:color_trc=iec61966-2-1:colorspace=bt709','-c:v','libx264','-preset','medium','-crf','18','-threads','4','-pix_fmt','yuv420p','-profile:v','high','-level:v','4.1','-color_range','tv','-colorspace','bt709','-color_primaries','bt709','-color_trc','iec61966-2-1','-movflags','+faststart','-metadata','title=NGC 602 through recorded 2.2 m AO PSFs','-metadata','comment=Existing 2 s record shown 20x slower. No AO rerun. Multiband colour illustration; same 1.65 um PSF in all RGB channels.',str(video)]
  with (WORK/'encode.log').open('wb') as log:
   proc=subprocess.Popen(command,stdin=subprocess.PIPE,stderr=log)
   try:
    for i,n in enumerate(counts):
     images.seek(i);images.load();assert images.info['duration']==timing['frame_durations_ms'][i]
     im=images.convert('RGB');raw=im.tobytes()
     for frame in selected_frames:
      if select[frame]==i:source_refs[frame]=np.asarray(im).copy()
     if i==len(counts)-1:im.save(out/'poster.png')
     for _ in range(int(n)):proc.stdin.write(raw)
     if i%40==0:print(f'encoded source image {i+1}/{len(counts)}',flush=True)
   finally:proc.stdin.close()
   assert proc.wait()==0,(WORK/'encode.log').read_text()
 # One decode checks every output timestamp and also extracts three visual oracles.
 filt='select='+ '+'.join(f'eq(n\\,{i})' for i in selected_frames)
 verify=[str(ffmpeg),'-y','-hide_banner','-loglevel','error','-i',str(video),'-map','0:v:0','-f','framemd5',str(checks/'decoded.framemd5'),'-map','0:v:0','-vf',filt,'-fps_mode','vfr',str(checks/'frame-%02d.png')]
 subprocess.run(verify,check=True)
 rows=[line.split(',') for line in (checks/'decoded.framemd5').read_text().splitlines() if line and not line.startswith('#')]
 assert len(rows)==count and all(int(row[2])==i and int(row[3])==1 for i,row in enumerate(rows))
 assert '#tb 0: 1/60' in (checks/'decoded.framemd5').read_text()
 fidelity=[]
 for j,n in enumerate(selected_frames,1):
  actual=np.asarray(Image.open(checks/f'frame-{j:02}.png').convert('RGB')).astype(float);expected=source_refs[n].astype(float)
  mse=float(np.mean((actual-expected)**2));psnr=10*math.log10(255**2/mse)
  assert psnr>30,(n,psnr)
  fidelity.append({'video_frame':n,'source_frame':int(timing['indices'][select[n]]),'psnr_db_vs_existing_webp':psnr,'mean_abs_rgb_error':float(np.mean(abs(actual-expected)))})
 atoms=[]
 with video.open('rb') as f:
  while (header:=f.read(8)):
   size,kind=struct.unpack('>I4s',header);start=f.tell()-8
   if size==1:size=struct.unpack('>Q',f.read(8))[0]
   if size==0:size=video.stat().st_size-start
   atoms.append(kind.decode());f.seek(start+size)
 assert atoms.index('moov')<atoms.index('mdat')
 probe=subprocess.run([str(ffmpeg),'-hide_banner','-i',str(video)],capture_output=True,text=True).stderr
 assert 'Video: h264 (High)' in probe and 'yuv420p' in probe and '960x896' in probe and '60 fps' in probe and 'Duration: 00:00:40.00' in probe and 'bt709/bt709/iec61966-2-1' in probe
 (WORK/'video-info.txt').write_text(probe)
 video_meta={'schema':'ao-explorer.ngc602-video-data.v1','parent_replay_entry':parent,'parent_movie_sha256':manifest['files']['ngc602-comparison.webp']['sha256'],'parent_timing_sha256':manifest['files']['movie-timing.json']['sha256'],'parent_scene_data_sha256':manifest['files']['data.json']['sha256'],'duration_s':40,'simulation_duration_s':2,'slowdown':20,'fps':FPS,'dimensions':[width,height],'video_frames':count,'source_indices':timing['indices'],'source_boundaries_ms':boundaries[:-1].tolist(),'source_first_video_frames':first.tolist(),'source_held_video_frame_counts':counts.tolist(),'loss_frame':736,'loss_time_s':data['loss_time_s'],'loss_first_video_frame':int(first[loss_pos]),'loss_first_video_time_s':float(first[loss_pos]/FPS),'max_hold_boundary_delay_ms':float(delay_ms.max()),'format':{'container':'MP4','codec':'H.264 High 4.1','pixel_format':'yuv420p','colour':'BT.709 primaries/matrix; sRGB transfer; limited video range','crf':18,'audio':False,'faststart':True},'checks':{'all_159_source_images_retained':True,'all_2400_output_frames_decoded':True,'uniform_60fps_timestamps':True,'source_bytes_hash_verified':True,'moov_before_mdat':True,'sampled_image_fidelity':fidelity},'simulation_rerun':False,'temporal_interpolation':False}
 write(out/'data.json',video_meta)
 write(out/'provenance.json',{'source_movie':{'path':str(source.relative_to(ROOT)),**manifest['files']['ngc602-comparison.webp']},'ffmpeg_version':subprocess.check_output([str(ffmpeg),'-version'],text=True).splitlines()[0],'ffmpeg_sha256':sha(ffmpeg),'encoder_arguments':command[1:-1]+[video.name],'exporter_sha256':sha(Path(__file__)),'operations':['Decode the already published 960x896 WebP presentation. No optical model, convolution, AO or metrics are recalculated.','Repeat each existing image at constant 60 fps. Preserve every original image, including frame 736. No blending or motion interpolation.','Encode H.264 with 4:2:0 chroma and fast-start MP4. This is a lossy sharing copy, not scientific image data.']})
 (out/'README.md').write_text('''# NGC 602: shareable MP4

40 seconds, 960 x 896, 60 fps, H.264 High 4.1 / yuv420p, no audio.
The MP4 fast-start header is at the beginning for progressive playback.

This is a transcode of the existing NGC 602 WebP presentation, with its full
field, linked magnifiers, all 1500 Strehl curve points, moving cursor and
0.981333 s loss marker already drawn. No AO simulation, PSF convolution or
scientific metric was rerun. Both compression stages are lossy.

All 159 source images are retained. They are held, never blended or
interpolated, on a 60 fps video grid. The transition delay is less than
1/60 second of playback (less than 0.834 ms in the 20x-slower simulation
clock), relative to the existing WebP's millisecond boundaries. Exact
frame mappings and the first MP4 frame showing loss are in data.json.
The whole movie is 40 seconds; it contains one 2-second recorded trajectory.

The source is an observed multiband colour composite, retaining JWST's
response and display processing. The same 1.65 um PSF was applied to each
RGB channel with a spatially constant on-axis assumption over the field.
These illustrations are not quantitative multiband instrument predictions.
All original assumptions and evidence remain in the parent website bundle.

Original image credit: ESA/Webb, NASA & CSA, P. Zeidler, E. Sabbi, A. Nota,
M. Zamani (ESA/Webb). https://esawebb.org/images/weic2425c/
CC BY 4.0: https://esawebb.org/copyright/
Modified by resampling, additional PSF blurring and video encoding.

To reproduce in the repository, place exporter.py at
scripts/ao_explorer/ngc602_mp4.py and run it with --ffmpeg /path/to/ffmpeg.
The pre-existing parent bundle is required; no AO runtime is called.
''')
 shutil.copy2(__file__,out/'exporter.py')
 files={p.name:{'bytes':p.stat().st_size,'sha256':sha(p),'media_type':'video/mp4' if p.suffix=='.mp4' else 'image/png' if p.suffix=='.png' else 'application/json' if p.suffix=='.json' else 'text/plain'} for p in sorted(out.iterdir()) if p.is_file() and p.name!='manifest.json'}
 identity='ngc602-mp4-'+hashlib.sha256(json.dumps(files,sort_keys=True,separators=(',',':')).encode()).hexdigest()[:16]
 write(out/'manifest.json',{'schema':'ao-explorer.ngc602-video-manifest.v1','id':identity,'files':files});target=WEB/'derived'/identity
 if not target.exists():shutil.copytree(out,target)
 else:assert sha(target/'manifest.json')==sha(out/'manifest.json')
 entry['ngc602Video']={'schema':'ao-explorer.ngc602-video-entry.v1','id':identity,'manifest':'../derived/'+identity+'/manifest.json','manifest_bytes':(target/'manifest.json').stat().st_size,'manifest_sha256':sha(target/'manifest.json')};write(WEB/'data/current.json',entry)
 print(json.dumps({'id':identity,'video_bytes':video.stat().st_size,'loss_first_video_frame':int(first[loss_pos]),'checks':video_meta['checks']}),flush=True)

if __name__=='__main__':
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--ffmpeg',required=True,type=Path);args=p.parse_args();main(args.ffmpeg.resolve())
