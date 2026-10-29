from pathlib import Path
import subprocess,math,json,hashlib
import numpy as np
from astropy.io import fits
import argparse
p=argparse.ArgumentParser(description='Download public F164N SCI/ERR/WHT arrays with byte-range provenance.');p.add_argument('--output-dir',type=Path,required=True);R=p.parse_args().output_dir;R.mkdir(parents=True,exist_ok=True)
U='https://mast.stsci.edu/api/v0.1/Download/file?uri=mast:JWST/product/jw01288-o001_t011_nircam_f150w2-f164n_i2d.fits'
records=[]
def get(a,b,name):
 p=R/(name+'.bin'); hp=R/(name+'.http')
 if not p.exists() or p.stat().st_size!=b-a+1:
  have=p.stat().st_size if p.exists() else 0
  tail=p.with_suffix('.tail'); th=hp.with_suffix('.tail.http')
  subprocess.run(['curl','-fLsS','--max-time','600','--range',f'{a+have}-{b}','-D',str(th),'-o',str(tail),U],check=True)
  assert f'bytes {a+have}-{b}/' in th.read_text().lower()
  with p.open('ab') as dst,tail.open('rb') as src:
   while chunk:=src.read(8*1024**2):dst.write(chunk)
  if not have:hp.write_text(th.read_text())
  tail.unlink()
 assert p.stat().st_size==b-a+1
 assert f'bytes {a}-{b}/' in hp.read_text().lower()
 records.append({'name':name,'range':[a,b],'bytes':p.stat().st_size,'sha256':hashlib.sha256(p.read_bytes()).hexdigest()});return p
off=0;exts=[]
for i in range(10):
 p=get(off,off+28799,f'header-{off}');b=p.read_bytes();end=next(j+80 for j in range(0,len(b),80) if b[j:j+8]==b'END     ');n=math.ceil(end/2880)*2880;h=fits.Header.fromstring(b[:n].decode(),sep='');name=h.get('EXTNAME','PRIMARY');(R/(name+'-source-header.txt')).write_text(h.tostring(sep='\n'));shape=[h[f'NAXIS{j}'] for j in range(1,h['NAXIS']+1)];size=(int(np.prod(shape)) if shape else 0)*abs(h['BITPIX'])//8;offset=off+n
 print(name,shape,size,flush=True);exts.append({'name':name,'shape_fits':shape,'data_offset':offset,'bytes':size,'bitpix':h['BITPIX']})
 if name in ['SCI','ERR','WHT']:get(offset,offset+size-1,name)
 off=offset+math.ceil(size/2880)*2880
 if name=='WHT':break
(R/'source-extraction.json').write_text(json.dumps({'url':U,'product':'jw01288-o001_t011_nircam_f150w2-f164n_i2d.fits','ranges':records,'extensions':exts,'note':'Full SCI, ERR and WHT arrays range-read; other extensions not retrieved; full product not hashed.'},indent=2)+'\n')
