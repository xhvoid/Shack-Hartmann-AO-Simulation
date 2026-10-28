"""Export a completed fixed 42 m recording and a calibrated HST binary template.

No AO trajectories run here. Linear observed-template convolution preserves
the original HST PSF, angular scale and signed background-subtracted pixels.
"""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import time

import numpy as np
from astropy.io import fits
from astropy.wcs import WCS
from astropy.wcs.utils import proj_plane_pixel_scales
from PIL import Image
from scipy.signal import fftconvolve, convolve2d

from long_series import sha256_file_chunked
import producer

ARCSEC = 180 / np.pi * 3600
TILE = 256


def verify(path, digest):
    if sha256_file_chunked(path) != digest:
        raise ValueError(f'Identity mismatch: {path}')


def area_weights(n, step, old_n, old_step):
    a = (np.arange(n+1)-n/2)*step
    b = (np.arange(old_n+1)-old_n/2)*old_step
    return np.maximum(0, np.minimum(a[1:,None], b[None,1:])-np.maximum(a[:-1,None],b[None,:-1]))/old_step


def observed_template(path, step):
    with fits.open(path) as hdus:
        h = hdus['SCI'].header
        d = hdus['SCI'].data.astype(float)
        weight = hdus['WHT'].data
        scales = proj_plane_pixel_scales(WCS(h))*3600
        assert np.allclose(scales, .025, rtol=1e-6), scales
        # Fixed crop selected from the archival observation, independent of AO results.
        cy, cx, radius = 506, 676, 80
        ys, xs = slice(cy-radius,cy+radius+1),slice(cx-radius,cx+radius+1)
        raw = d[ys,xs].copy()
        assert raw.shape == (161,161) and np.isfinite(raw).all()
        assert np.all(weight[ys,xs]>0), 'Uncovered source pixels'
        yy,xx=np.indices(raw.shape); r=np.hypot(yy-radius,xx-radius)
        background=float(np.median(raw[(r>=55)&(r<=78)]))
        signed=raw-background
        source_sum=float(signed.sum()); assert source_sum>0
        n=int(np.ceil(raw.shape[0]*scales[0]/step))
        if n%2==0:n+=1
        w=area_weights(n,step,raw.shape[0],scales[0])
        scene=w@signed@w.T/source_sum
        assert abs(scene.sum()-1)<1e-12
        record={
            'target':'2MASS J0746425+200032 AB', 'facility':'NASA/ESA HST · ACS/HRC',
            'dataset':'j6kt02020_drz.fits','program':9451,'filter':'F775W',
            'date_obs':hdus[0].header['DATE-OBS'],'exposure_s':hdus[0].header['EXPTIME'],
            'uri':'mast:HST/product/j6kt02020_drz.fits',
            'download_url':'https://mast.stsci.edu/api/v0.1/Download/file?uri=mast:HST/product/j6kt02020_drz.fits',
            'sha256':sha256_file_chunked(path),'hdu':'SCI,1','bunit':h['BUNIT'],
            'native_pixel_arcsec':scales.tolist(),'orientation_y_east_of_north_deg':h['ORIENTAT'],
            'crop_yx_zero_based':[cy-radius,cy+radius+1,cx-radius,cx+radius+1],
            'background':background,'background_method':'median in 55–78 pixel annulus about crop centre',
            'negative_pixels_retained':True,'source_crop_sum_before_normalization':source_sum,
            'resampling':'exact rectangular pixel-area overlap; integrated pixel flux; original image-axis orientation retained',
            'resampled_shape':list(scene.shape),'resampled_pixel_arcsec':step,
            'resampled_total':float(scene.sum()),'quality':'finite SCI values and positive WHT across crop; calibrated archive product; no independent photometric recalibration',
            'interpretation':'Observed morphology template. Original HST PSF and noise retained. No deconvolution, component fitting, separation scaling or K-band photometry.',
            'model':'One spatially invariant on-axis 2.2 micrometre simulation PSF applied across this compact source. Illustrative extra blurring of an F775W observation.',
            'credit':'NASA/ESA Hubble Space Telescope; ACS/HRC program 9451; calibrated data retrieved from MAST (STScI).',
            'data_policy':'https://archive.stsci.edu/publishing/data-use',
        }
        sky=WCS(h).all_pix2world([[cx,cy]],0)
    dq_checks=[]
    for n in range(1,5):
        exposure=path.parent/f'j6kt02l{n}q_flt.fits'
        with fits.open(exposure) as h:
            xy=WCS(h['SCI'].header,h).all_world2pix(sky,0)[0]
            ix,iy=np.rint(xy).astype(int)
            dq=h['DQ'].data[iy-15:iy+16,ix-15:ix+16]
            saturated=int(np.count_nonzero(dq&(256|2048)))
            assert dq.shape==(31,31) and saturated==0, 'Saturated or incomplete binary core'
            dq_checks.append({'file':exposure.name,'sha256':sha256_file_chunked(exposure),
                              'core_centre_xy':xy.tolist(),'core_size_px':31,
                              'saturation_bits':[256,2048],'saturated_core_pixels':saturated,
                              'core_dq_values':np.unique(dq).tolist()})
    record['input_exposure_quality']=dq_checks
    record['dq_definition']='https://hst-docs.stsci.edu/acsdhb/chapter-3-acs-calibration-pipeline/3-4-calacs-processing-steps'
    return scene,raw,signed,record


def convolution(scene,kernel,origin):
    full=fftconvolve(scene,kernel,mode='full')
    error=abs(float(full.sum())-float(scene.sum()*kernel.sum()))
    oy,ox=origin
    result=full[oy:oy+scene.shape[0],ox:ox+scene.shape[1]]
    return result,error


def convolution_check():
    s=np.arange(15,dtype=float).reshape(3,5)/105
    k=np.arange(24,dtype=float).reshape(4,6)/276
    full=fftconvolve(s,k,mode='full'); direct=convolve2d(s,k,mode='full')
    assert np.max(abs(full-direct))<1e-14
    out,error=convolution(s,k,(2,3))
    assert np.allclose(out,direct[2:5,3:8],rtol=0,atol=1e-14)
    delta=np.zeros((4,6));delta[2,3]=1
    identity,_=convolution(s,delta,(2,3))
    assert np.allclose(identity,s,rtol=0,atol=1e-14)
    return {'direct_full_max_error':float(np.max(abs(full-direct))), 'even_kernel_origin_identity_max_error':float(np.max(abs(identity-s))), 'passed':True}


def rgb_wave(a,limit):
    t=np.clip(a/limit,-1,1)
    neg=np.array([34,82,151]);mid=np.array([232,237,239]);pos=np.array([220,92,62])
    c=np.where((t[...,None]<0),mid+(mid-neg)*t[...,None],mid+(pos-mid)*t[...,None])
    c[~np.isfinite(a)]=[9,17,26]
    return np.uint8(np.nan_to_num(c))


def grey(a,maximum,soft):
    return np.repeat(np.uint8(np.clip(np.arcsinh(np.maximum(a,0)/soft)/np.arcsinh(maximum/soft),0,1)*255)[...,None],3,axis=2)


def psf_rgb(a,peak):
    t=np.clip((np.log10(np.maximum(a/peak,1e-6))+6)/6,0,1)
    # Fixed continuous black–violet–orange–cream transfer, same for all frames.
    nodes=np.array([[5,9,19],[29,24,67],[112,40,100],[219,90,61],[250,193,91],[255,247,217]])
    z=t*5;i=np.minimum(z.astype(int),4);f=(z-i)[...,None]
    return np.uint8(nodes[i]*(1-f)+nodes[i+1]*f)


def tile(a):
    return Image.fromarray(np.flipud(a)).resize((TILE,TILE),Image.Resampling.BILINEAR)


def main(run,source,output):
    started=time.monotonic()
    plan=producer.read_json(run/'plan.json');record=producer.read_json(run/'record.json')
    assert record['status']=='COMPLETED'
    verify(run/'plan.json',record['plan_sha256'])
    for name,entry in record['files'].items(): verify(run/name,entry['sha256'])
    for name,entry in record['raw_maps'].items(): verify(run/f'{name}.npy',entry['sha256'])
    assert plan['n_steps']==500 and plan['analysis_window']==[100,500]
    assert record['config_hash']==plan['config_hash']
    assert record['core_sha256_after']==plan['core']['package_sha256']
    for role in ('corrected','uncorrected'):
        r=record[f'science_{role}'];s=r['selection'];m=r['metadata']
        assert (s['first_frame'],s['last_frame'],s['sample_count'],s['stride'])==(100,499,400,1)
        assert s['uniform_weights'] and s['weight_sum']==400 and s['residual']=='pre_update'
        assert m['recentering']=='none' and m['coaddition']=='intensity'
        assert r['images'][0]['psf']['wavelength_m']==2.2e-6
        assert r['images'][0]['psf']['normalization']=='unit_total_flux'
    output.mkdir(parents=True,exist_ok=False);(output/'frames').mkdir();(output/'evidence').mkdir()
    science=np.load(run/'science.npz');x=science['x_angle_rad'];y=science['y_angle_rad']
    step=float(np.diff(x)[0])*ARCSEC
    assert np.allclose(np.diff(x)*ARCSEC,step,rtol=1e-10)
    assert np.allclose(np.diff(y)*ARCSEC,step,rtol=1e-10)
    origin=(int(np.flatnonzero(y==0)[0]),int(np.flatnonzero(x==0)[0]))
    scene,raw,signed,source_record=observed_template(source,step)
    np.savez_compressed(output/'evidence'/'binary-template.npz',scene=scene,raw_crop=raw,background_subtracted_crop=signed)
    producer.write_json(output/'evidence'/'source.json',source_record)
    half=int(round(.6/step));side=2*half+1
    pcut=(slice(origin[0]-half,origin[0]+half+1),slice(origin[1]-half,origin[1]+half+1))
    centre=scene.shape[0]//2;scut=(slice(centre-half,centre+half+1),)*2
    maximum=float(scene.max());soft=maximum/100
    tile(grey(scene[scut],maximum,soft)).save(output/'source.png')
    maps={k:np.load(run/f'{k}.npy',mmap_mode='r') for k in ('atmosphere_opd_m','pre_update_residual_opd_m')}
    mask=science['pupil_mask'];factor=4;npix=mask.shape[0]//factor
    def reduced(a):
        a=a-np.mean(a[mask]);valid=np.isfinite(a)
        sums=np.where(valid,a,0).reshape(npix,factor,npix,factor).sum((1,3))
        counts=valid.reshape(npix,factor,npix,factor).sum((1,3))
        return np.divide(sums,counts,out=np.full(sums.shape,np.nan),where=counts>0)
    display=plan['display_indices'];reduced_maps=[]
    for k in display:
        a=maps['atmosphere_opd_m'][k];r=maps['pre_update_residual_opd_m'][k]
        reduced_maps.append([reduced(a),reduced(a-r),reduced(r)])
    limit=float(np.ceil(max(np.nanmax(abs(a)) for frames in reduced_maps for a in frames)*1e6*10)/10/1e6)
    ideal_peak=float(science['ideal'].max());flux_checks=[];derived=[]
    for j,k in enumerate(display+['mean']):
        if k=='mean':
            images={role:science[f'mean_{role}'] for role in ('uncorrected','corrected')}
            panels=[np.zeros((TILE,TILE,3),dtype=np.uint8)]*3
        else:
            entry=next(s for s in record['samples'] if s['frame']==k)
            verify(run/entry['path'],entry['sha256'])
            with np.load(run/entry['path']) as z: images={role:z[f'psf_{role}'] for role in ('uncorrected','corrected')}
            panels=[rgb_wave(a,limit) for a in reduced_maps[j]]
        observed={}
        for role,psf in images.items():
            assert abs(psf.sum()-1)<1e-10 and psf.min()>=0
            obs,error=convolution(scene,psf,origin);flux_checks.append(error)
            observed[role]=obs[scut].copy()
            panels.append(psf_rgb(psf[pcut],ideal_peak))
        for role in ('uncorrected','corrected'): panels.append(grey(observed[role],maximum,soft))
        atlas=Image.new('RGB',(TILE*7,TILE))
        for i,a in enumerate(panels):atlas.paste(tile(a),(TILE*i,0))
        name='mean' if k=='mean' else f'{k:04d}'
        atlas.save(output/'frames'/f'{name}.png')
        derived.append({'frame':k,'uncorrected_crop_flux':float(observed['uncorrected'].sum()),'corrected_crop_flux':float(observed['corrected'].sum())})
        if k=='mean':np.savez_compressed(output/'evidence'/'binary-mean.npz',**observed)
        if j%20==0:print(f'Exported {j}/{len(display)} replay samples',flush=True)
    checks=convolution_check();checks['max_full_convolution_flux_error']=max(flux_checks)
    assert max(flux_checks)<1e-12
    metrics=producer.read_json(run/'frames.json')
    # Independent numerical replay checks against original full-resolution maps.
    errors=[];hash_checks=[]
    for k in (0,100,248,499):
        for key,mkey,hkey in [('atmosphere_opd_m','atmosphere_rms_m','atmosphere_sha256'),('pre_update_residual_opd_m','residual_rms_m','residual_sha256')]:
            a=maps[key][k];rms=float(np.std(a[mask]));errors.append(abs(rms-metrics[mkey][k]))
            hash_checks.append(hashlib.sha256(np.ascontiguousarray(a).tobytes()).hexdigest()==metrics[hkey][k])
    assert max(errors)<1e-15 and all(hash_checks)
    checks.update(raw_map_rms_error_m=max(errors),raw_map_hashes_match=all(hash_checks))
    data={'schema':'ao-replay.42m.local.v1','indices':display,'metrics':metrics,'config_hash':plan['config_hash'],
          'step_arcsec':step,'field_arcsec':side*step,'opd_limit_um':limit*1e6,'tile':TILE,
          'source':source_record,'source_peak':maximum,'source_softening':soft,'psf_ideal_peak':ideal_peak,
          'mean_peak_strehl':{r:float(science[f'mean_{r}'].max()/ideal_peak) for r in ('uncorrected','corrected')},
          'mean_rms_nm':{r:float(np.mean(metrics[f'{r}_rms_m'][100:]))*1e9 for r in ('atmosphere','residual')},
          'mean_instantaneous_strehl':{r:float(np.mean(metrics[f'peak_strehl_{r}'][100:])) for r in ('uncorrected','corrected')},
          'trajectory_quality':{'unusable_reconstruction_frames':int(sum(not v for v in metrics['reconstruction_usable'])),
                                'max_dm_saturation_fraction':float(max(metrics['saturation_fraction']))},
          'derived_crop_fluxes':derived,'checks':checks,'wall_s':record['wall_s'],
          'rendering':{'wavefront':'piston removed; 4×4 valid-pupil average; fixed common symmetric range covering all display maps',
                       'PSF':'fixed log scale, 1e-6 to 1 of ideal peak; full-grid flux normalization retained',
                       'binary':'fixed shared asinh mapping, softening = source peak/100; signed values retained numerically; display clips negative to black',
                       'orientation':'source image axes preserved; positive model y displayed upwards; no sky-orientation claim for simulated pupil'}}
    producer.write_json(output/'data.json',data)
    shutil.copyfile(run/'plan.json',output/'evidence'/'plan.json')
    # Compact summary: original run record remains untouched in the raw archive.
    summary={k:v for k,v in record.items() if k not in ('science_corrected','science_uncorrected')}
    summary['original_record_sha256']=sha256_file_chunked(run/'record.json')
    for role in ('corrected','uncorrected'):
        rr=record[f'science_{role}'];summary[f'science_{role}']={k:v for k,v in rr.items() if k!='images'}
        summary[f'science_{role}']['metrics']=[im['metrics'] for im in rr['images']]
    producer.write_json(output/'evidence'/'run-summary.json',summary)
    producer.write_json(output/'evidence'/'export-checks.json',checks)
    for name in ('replay_42m_export.py','replay_42m_viewer.html'):
        shutil.copyfile(Path(__file__).parent/name,output/'evidence'/name)
    shutil.copyfile(Path(__file__).parent/'replay_42m_viewer.html',output/'index.html')
    files={p.relative_to(output).as_posix():{'bytes':p.stat().st_size,'sha256':sha256_file_chunked(p)} for p in output.rglob('*') if p.is_file()}
    producer.write_json(output/'manifest.json',{'schema':'ao-replay.manifest.v1','files':files,'export_wall_s':time.monotonic()-started})
    print(json.dumps({'output':str(output),'checks':checks,'bytes':sum(v['bytes'] for v in files.values()),'mean_rms_nm':data['mean_rms_nm'],'mean_peak_strehl':data['mean_peak_strehl']}),flush=True)


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--run',type=Path,required=True);p.add_argument('--source',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    a=p.parse_args();main(a.run,a.source,a.output)
