"""Postprocess existing wavefront archives only; no simulation imports or RNG."""
from pathlib import Path
import csv
import hashlib
import json
import platform

import numpy as np
from scipy.ndimage import map_coordinates
import scipy
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.colors import Normalize
from matplotlib.patches import Circle
from PIL import Image, ImageDraw, ImageFont

import argparse
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--web', type=Path, required=True, help='Existing web/ao-explorer directory')
parser.add_argument('--raw-2m', type=Path, required=True, help='Existing 1000 x 52 x 52 atmosphere NPY')
parser.add_argument('--raw-42m', type=Path, required=True, help='Existing 500 x 1008 x 1008 atmosphere NPY')
parser.add_argument('--output', type=Path, required=True, help='New output directory')
args = parser.parse_args()
OUT = args.output.resolve()
OUT.mkdir(parents=True, exist_ok=False)
WEB = args.web.resolve()
D2 = WEB / 'data/series-2m1000-s624-c7241e4190d5-ef74a541b0e60'
D42 = WEB / 'recordings/42m-500-31024b173527b7a6'
RAW2, RAW42 = args.raw_2m.resolve(), args.raw_42m.resolve()
read = lambda p: json.loads(p.read_text())
digest = lambda p: hashlib.sha256(p.read_bytes()).hexdigest()

provenance = read(D2 / 'cases/baseline/provenance.json')
hash2 = digest(RAW2)
assert hash2 == provenance['raw_evidence']['files']['frames/atmosphere_opd_m.npy']['sha256']
m2 = read(D2 / 'cases/baseline/metrics.json')['per_frame']
m42 = read(D42 / 'data.json')['metrics']
a2 = np.load(RAW2, mmap_mode='r')
a42 = np.load(RAW42, mmap_mode='r')
assert a2.shape == (1000, 52, 52) and a42.shape == (500, 1008, 1008)

# Geometry chosen before reading crop values: an unobstructed, fixed pupil patch.
center = (10., 0.)
x = np.linspace(-1., 1., 52)
xx, yy = np.meshgrid(x, x)
mask = xx**2 + yy**2 <= 1.
assert np.array_equal(mask, np.isfinite(a2[0]))
dx42 = 42. / 1007
query = np.array([(yy + center[1] + 21.) / dx42,
                  (xx + center[0] + 21.) / dx42])
indices42 = np.arange(100, 500)
indices2 = indices42 * 2
times = indices42 / 500.
assert np.array_equal(times, indices2 / 1000.)
waves2, waves42, nearest42 = [], [], []
hash_checks = []
max_metric_error_nm = 0.
for k2, k42 in zip(indices2, indices42):
    source = np.asarray(a42[k42])
    h = hashlib.sha256(np.ascontiguousarray(source).tobytes()).hexdigest()
    assert h == m42['atmosphere_sha256'][k42]
    hash_checks.append({'frame': int(k42), 'sha256': h})
    b = np.array(a2[k2], copy=True)
    assert np.array_equal(np.isfinite(b), mask)
    max_metric_error_nm = max(max_metric_error_nm,
        abs(float(np.std(b[mask])) * 1e9 - m2['atmosphere_rms_nm']['values'][k2]))
    c = map_coordinates(source, query, order=1, mode='constant', cval=np.nan, prefilter=False)
    n = map_coordinates(source, query, order=0, mode='constant', cval=np.nan, prefilter=False)
    assert np.isfinite(c[mask]).all() and np.isfinite(n[mask]).all()
    for source_map, target in [(b, waves2), (c, waves42), (n, nearest42)]:
        source_map = source_map - np.mean(source_map[mask])
        source_map[~mask] = np.nan
        target.append(source_map * 1e9)
waves2, waves42, nearest42 = [np.asarray(v) for v in (waves2, waves42, nearest42)]
assert max_metric_error_nm < 1e-8
assert max(abs(np.nanmean(v, axis=(1, 2))).max() for v in (waves2, waves42)) < 1e-8

def spatial_rms(stack):
    return np.sqrt(np.mean(stack[:, mask] ** 2, axis=1))

def lag_stats(stack, lag_steps):
    u, v = stack[:-lag_steps, mask], stack[lag_steps:, mask]
    d = v-u
    return {'pair_count': len(d),
            'space_time_rms_nm': float(np.sqrt(np.mean(d*d))),
            'mean_spatial_rms_nm': float(np.mean(np.sqrt(np.mean(d*d, axis=1)))),
            'mean_spatial_correlation': float(np.mean(np.sum(u*v, axis=1) /
                np.sqrt(np.sum(u*u, axis=1)*np.sum(v*v, axis=1))))}

lags = [4, 50, 250]  # 8, 100, 500 ms on the common 2 ms timeline.
summary = {}
for name, stack in [('2m_baseline', waves2), ('42m_2m_crop', waves42), ('42m_crop_nearest_sensitivity', nearest42)]:
    rms = spatial_rms(stack)
    summary[name] = {'mean_spatial_rms_nm': float(rms.mean()),
        'temporal_std_of_spatial_rms_nm': float(rms.std()),
        'min_spatial_rms_nm': float(rms.min()), 'max_spatial_rms_nm': float(rms.max()),
        'relative_temporal_std': float(rms.std()/rms.mean()),
        'lag_statistics': {str(lag*2): lag_stats(stack, lag) for lag in lags}}
    summary[name]['selected_pairs'] = {
        str(lag*2): {'start_s': .2, 'end_s': float(times[lag]),
            'start_rms_nm': float(rms[0]), 'end_rms_nm': float(rms[lag]),
            'difference_rms_nm': float(np.sqrt(np.mean((stack[lag,mask]-stack[0,mask])**2)))}
        for lag in lags}

full42 = np.array(m42['atmosphere_rms_m'])[indices42] * 1e9
summary['42m_full_pupil'] = {'mean_spatial_rms_nm': float(full42.mean()),
    'temporal_std_of_spatial_rms_nm': float(full42.std()),
    'relative_temporal_std': float(full42.std()/full42.mean())}

# One symmetric range covers BOTH data sets, all sampled times and all displayed differences.
peak = max(float(np.nanmax(np.abs(v))) for v in (waves2, waves42))
for v in (waves2, waves42):
    for lag in lags:
        peak = max(peak, float(np.nanmax(np.abs(v[lag:] - v[:-lag]))))
limit = float(np.ceil(peak / 100.) * 100.)
cmap = matplotlib.colormaps['RdBu_r'].copy()
cmap.set_bad('#e4e7eb')
norm = Normalize(-limit, limit)
plt.rcParams.update({'font.family': 'DejaVu Sans', 'font.size': 11,
    'axes.spines.top': False, 'axes.spines.right': False, 'savefig.facecolor': 'white'})

def save_pair(lag):
    fig, axes = plt.subplots(2, 3, figsize=(11.2, 7.6), layout='constrained')
    for row, (name, stack) in enumerate([('2 m baseline', waves2), ('42 m: fixed 2 m crop', waves42)]):
        for col, (array, title) in enumerate([
            (stack[0], 't = 0.200 s'), (stack[lag], f't = {times[lag]:.3f} s'),
            (stack[lag]-stack[0], f'Difference: later - earlier\nDelta t = {lag*2} ms')]):
            ax = axes[row, col]
            im = ax.imshow(array, origin='lower', extent=[-1-1/51,1+1/51,-1-1/51,1+1/51],
                cmap=cmap, norm=norm, interpolation='nearest')
            ax.add_patch(Circle((0, 0), 1, facecolor='none', edgecolor='#485463', lw=.7))
            ax.set(xlim=(-1.03,1.03), ylim=(-1.03,1.03), xticks=[-1,0,1], yticks=[-1,0,1], xlabel='Local x (m)',
                title=title)
            if col == 0: ax.set_ylabel(name+'\nLocal y (m)')
            rms = float(np.sqrt(np.mean(array[mask]**2)))
            ax.text(.03,.97,f'RMS {rms:.1f} nm', transform=ax.transAxes, va='top', fontsize=10,
                bbox={'facecolor':'white','alpha':.9,'edgecolor':'none','pad':3})
    fig.suptitle('Same 2 m aperture, same physical times, one OPD color scale', fontsize=15, weight='bold')
    fig.colorbar(im, ax=axes, label='OPD / OPD difference (nm)', fraction=.03, pad=.025)
    fig.supxlabel('Local piston removed at every time; tilt retained. No amplitude rescaling.\n42 m crop center: (10, 0) m; bilinear spatial sampling onto the 2 m grid.', fontsize=10)
    fig.savefig(OUT/f'comparison_{lag*2:03d}ms.png', dpi=170)
    fig.savefig(OUT/f'comparison_{lag*2:03d}ms.svg')
    plt.close(fig)

for lag in lags: save_pair(lag)

fig, axes = plt.subplots(1,3,figsize=(14,4.7),layout='constrained')
colors = ['#2369a0','#bd4e32']
for name, stack, color in zip(['2 m baseline','42 m: 2 m crop'],[waves2,waves42],colors):
    axes[0].plot(times,spatial_rms(stack),label=name,color=color,lw=1.6)
axes[0].plot(times,full42,label='42 m: full pupil',color='#7c8490',lw=1.2,ls='--')
axes[0].set(xlabel='Time (s)',ylabel='Piston-removed spatial RMS (nm)',title='Local fluctuations emerge after cropping')
axes[0].legend(fontsize=8,loc='upper right')
lag_grid = np.unique(np.r_[np.arange(1,26),np.arange(30,251,10)])
for name, stack, color in zip(['2 m baseline','42 m: 2 m crop'],[waves2,waves42],colors):
    stats = [lag_stats(stack,int(k)) for k in lag_grid]
    axes[1].plot(lag_grid*2,[s['space_time_rms_nm'] for s in stats],label=name,color=color,lw=1.8)
    axes[2].plot(lag_grid*2,[s['mean_spatial_correlation'] for s in stats],color=color,lw=1.8)
axes[1].set(xlabel='Time separation (ms)',ylabel='Space-time RMS of wavefront difference (nm)',title='Temporal changes on the same footprint')
axes[1].legend(fontsize=8)
axes[2].set(xlabel='Time separation (ms)',ylabel='Mean spatial correlation',title='Pattern similarity across time',ylim=(-.55,1.05))
for ax in axes: ax.grid(alpha=.2)
fig.suptitle('Existing recordings only: 0.200–0.998 s at matching 2 ms samples',fontsize=14,weight='bold')
fig.supxlabel('All available pairs at each lag; pair count decreases with lag. One realization per model; curves are descriptive, not confidence intervals.',fontsize=10)
fig.savefig(OUT/'temporal_comparison.png',dpi=170)
fig.savefig(OUT/'temporal_comparison.svg')
plt.close(fig)

# Locate the chosen patch on the original pupil without changing its source scale.
fig, ax = plt.subplots(figsize=(6,5.5),layout='constrained')
raw = np.asarray(a42[100])*1e9
im=ax.imshow(raw,origin='lower',extent=[-21-dx42/2,21+dx42/2,-21-dx42/2,21+dx42/2],
    cmap=cmap,vmin=-6700,vmax=6700,interpolation='nearest')
ax.add_patch(Circle(center,1,fill=False,color='#19ce72',lw=2))
ax.annotate('Fixed 2 m diameter crop\ncenter (10, 0) m',xy=center,xytext=(1,-15),color='#143a23',
    bbox={'facecolor':'white','alpha':.95,'edgecolor':'none'},arrowprops={'arrowstyle':'->','color':'#143a23'})
ax.set(xlabel='Pupil x (m)',ylabel='Pupil y (m)',title='42 m atmosphere at t = 0.200 s')
fig.colorbar(im,ax=ax,label='OPD (nm)')
fig.savefig(OUT/'crop_location.png',dpi=160);plt.close(fig)

with (OUT/'timeseries.csv').open('w',newline='') as f:
    w=csv.writer(f);w.writerow(['time_s','2m_frame','42m_frame','2m_rms_nm','42m_crop_rms_nm','42m_full_rms_nm'])
    w.writerows(zip(times,indices2,indices42,spatial_rms(waves2),spatial_rms(waves42),full42))
np.savez_compressed(OUT/'matched_wavefronts.npz',time_s=times,x_m=x,y_m=x,pupil_mask=mask,
    frame_2m=indices2,frame_42m=indices42,baseline_opd_nm=waves2,crop42_opd_nm=waves42,crop_center_m=center)

# A compact synchronized movie: each saved animation frame advances exactly 8 ms.
from matplotlib.font_manager import findfont
font_path=findfont('DejaVu Sans')
font=ImageFont.truetype(font_path,18)
small=ImageFont.truetype(font_path,15)
movie=[]
for i in range(0,len(times)-4,4):
    canvas=Image.new('RGB',(820,745),'white');draw=ImageDraw.Draw(canvas)
    draw.text((22,12),f'Existing data | t = {times[i]:.3f} s | one color scale: +/- {limit:.0f} nm',fill='#182d40',font=font)
    draw.text((22,39),'Left: wavefront. Right: change over the next 8 ms (later - earlier).',fill='#445566',font=small)
    for row,(label,stack) in enumerate([('2 m baseline',waves2),('42 m: fixed 2 m crop',waves42)]):
        for col,values in enumerate([stack[i],stack[i+4]-stack[i]]):
            rgba=(cmap(norm(np.ma.masked_invalid(values)))*255).astype('uint8')
            img=Image.fromarray(rgba[::-1],mode='RGBA').convert('RGB').resize((300,300),resample=Image.Resampling.NEAREST)
            left,top=25+col*395,100+row*320
            canvas.paste(img,(left,top))
            title=label if col==0 else f'Difference RMS: {np.sqrt(np.mean(values[mask]**2)):.1f} nm'
            draw.text((left,top-23),title,fill='#182d40',font=small)
    draw.text((22,727),'2 m diameter; local piston removed, tilt retained. Playback: 20x slower.',fill='#445566',font=small)
    movie.append(canvas)
movie[0].save(OUT/'synchronized_comparison.gif',save_all=True,append_images=movie[1:],duration=160,loop=0,optimize=False)

inputs={str(p):digest(p) for p in [RAW2,D2/'cases/baseline/config.json',
    D2/'cases/baseline/metrics.json',D2/'cases/baseline/provenance.json',D42/'evidence/plan.json',D42/'data.json']}
record={'scope':'Postprocessing of existing archives only; no simulator or RNG used.',
    'crop_center_m':center,'crop_diameter_m':2.,'times_s':[float(times[0]),float(times[-1])],
    'time_step_s':.002,'samples':len(times),'common_grid_shape':[52,52],
    'common_grid_spacing_m':2/51,'source_42m_grid_spacing_m':dx42,
    'spatial_sampling':'2 m native samples; 42 m bilinear samples at translated identical coordinates; no temporal interpolation.',
    'piston':'Remove the arithmetic mean of the same 2032 valid pupil samples independently at each time; retain tilt.',
    'difference_definition':'piston-removed OPD(t+lag) minus piston-removed OPD(t)',
    'color_limit_nm':limit,'color_rule':'One symmetric range rounded up to 100 nm covers both series and all three lag differences; no clipping.',
    'inputs_sha256':inputs,'raw42_verified_frames':hash_checks,'raw42_path':str(RAW42),
    'max_2m_metric_error_nm':max_metric_error_nm,'summary':summary,
    'environment':{'python':platform.python_version(),'numpy':np.__version__,'scipy':scipy.__version__,'matplotlib':matplotlib.__version__},
    'limitations':['One fixed crop and one realization for each model. Not a controlled model or aperture-only experiment.',
        'Different layer profiles, winds, seeds and slight r0 difference remain.',
        'Bilinear spatial interpolation mildly filters the 42 m crop; nearest-neighbor sensitivity is reported separately.',
        'Overlapping time pairs are correlated; statistics are descriptive.']}
(OUT/'comparison.json').write_text(json.dumps(record,indent=2)+'\n')
print(json.dumps({'color_limit_nm':limit,'summary':summary,'max_2m_metric_error_nm':max_metric_error_nm},indent=2))
