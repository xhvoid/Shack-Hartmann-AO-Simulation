"""Retrieve bounded ranges of a public calibrated mosaic; preserve source headers."""
from pathlib import Path
import subprocess,json,math,hashlib
import numpy as np
from astropy.io import fits
from astropy.wcs import WCS
ROOT=Path(__file__).parent
URL='https://mast.stsci.edu/api/v0.1/Download/file?uri=mast:JWST/product/jw01256-o001_t001_nircam_f150w2-f162m_i2d.fits'
records=[]
def get(lo,hi,label):
 p=ROOT/(label+'.bin');hp=ROOT/(label+'.http')
 if not p.exists() or p.stat().st_size!=hi-lo+1:
  subprocess.run(['curl','-fLsS','--retry','2','--max-time','180','--range',f'{lo}-{hi}','-D',str(hp),'-o',str(p),URL],check=True)
 assert p.stat().st_size==hi-lo+1,(p,p.stat().st_size,hi-lo+1)
 b=p.read_bytes();records.append({'label':label,'range':[lo,hi],'bytes':len(b),'sha256':hashlib.sha256(b).hexdigest()});return b

def header(offset):
 b=get(offset,offset+28799,f'header-{offset}')
 end=next(i+80 for i in range(0,len(b),80) if b[i:i+8]==b'END     ')
 n=math.ceil(end/2880)*2880
 return fits.Header.fromstring(b[:n].decode('ascii'),sep=''),n
ph,n=header(0);hdus=[fits.PrimaryHDU(header=ph)]
off=n;bounds=None;source=[]
for num in range(9):
 h,n=header(off);name=h.get('EXTNAME','UNKNOWN');shape=[h.get('NAXIS'+str(i),1) for i in range(1,h.get('NAXIS',0)+1)];size=int(np.prod(shape))*abs(h['BITPIX'])//8;dataoffset=off+n
 print(name,shape,'offset',dataoffset,flush=True)
 source.append({'name':name,'header_offset':off,'data_offset':dataoffset,'shape_fits':shape,'bitpix':h['BITPIX']})
 (ROOT/f'{name}-source-header.txt').write_text(h.tostring(sep='\n'))
 if name in ('SCI','ERR','WHT'):
  if name=='SCI':
   w=WCS(h);cx,cy=w.world_to_pixel_values(83.825,-5.399);half=1200;cx,cy=round(float(cx)),round(float(cy));bounds=[cx-half,cx+half+1,cy-half,cy+half+1];print('bounds',bounds,'center',cx,cy,flush=True)
  x0,x1,y0,y1=bounds;nx,ny=shape;nb=abs(h['BITPIX'])//8
  b=get(dataoffset+y0*nx*nb,dataoffset+y1*nx*nb-1,f'{name}-rows-{y0}-{y1}')
  dtype={-32:'>f4',-64:'>f8',32:'>i4'}[h['BITPIX']];a=np.frombuffer(b,dtype=dtype).reshape(y1-y0,nx)[:,x0:x1].copy()
  
  if 'CRPIX1' in h: h['CRPIX1']-=x0;h['CRPIX2']-=y0
  h['HISTORY']='Spatial cutout only; no rescaling, masking or background subtraction.'
  hdus.append(fits.ImageHDU(a,header=h,name=name));print(name,'finite',int(np.isfinite(a).sum()),'pixels',a.size,'min/max',float(np.nanmin(a)),float(np.nanmax(a)),flush=True)
 off=dataoffset+math.ceil(size/2880)*2880
 if name=='WHT':break
fits.HDUList(hdus).writeto(ROOT/'orion-f162m-cutout.fits',overwrite=True,checksum=True)
(ROOT/'source-extraction.json').write_text(json.dumps({'url':URL,'product':ph['FILENAME'],'source_total_bytes':26467335360,'source_filter':ph['FILTER'],'source_pupil':ph['PUPIL'],'calibration_version':ph['CAL_VER'],'bounds_xy':bounds,'ranges':records,'extensions':source,'operation':'Exact rectangular SCI/ERR/WHT extraction; source file was range-read, not downloaded or hashed in full. Source range hashes identify retrieved bytes.'},indent=2)+'\n')
print('DONE',flush=True)
