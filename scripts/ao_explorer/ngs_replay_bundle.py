"""Build a synchronized NGS replay from immutable archives; no AO runtime imports.

Only saved OPD is propagated by a centered FFT for display. All original
PSF snapshots and sampled Strehl values provide independent archived oracles.
"""
from __future__ import annotations
import csv
import hashlib
import json
from pathlib import Path
import shutil
import tempfile

import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parents[2]
WEB = ROOT / 'web/ao-explorer'
FIRST = ROOT / 'outputs/robo_ao2_ngs/20261024-first-trajectory'
REPAIR = ROOT / 'outputs/robo_ao2_ngs/20261024-loss-of-lock-repair'
TILE = 256
WAVELENGTH = 1.65e-6


def read(p):
    return json.loads(p.read_text())


def write(p, value):
    p.write_text(json.dumps(value, indent=2, allow_nan=False) + '\n')


def sha(p):
    h = hashlib.sha256()
    with p.open('rb') as f:
        for b in iter(lambda: f.read(8 * 1024**2), b''):
            h.update(b)
    return h.hexdigest()


def psf(opd, mask):
    """Frozen native convention, implemented without constructing an AO system."""
    field = np.zeros(mask.shape, complex)
    field[mask] = np.exp(1j * (2 * np.pi * opd[mask] / WAVELENGTH))
    padded = np.pad(field, ((256, 256), (256, 256)))
    intensity = abs(np.fft.fftshift(np.fft.fft2(np.fft.ifftshift(padded))))**2
    return intensity / intensity.sum()


def wave_rgb(opd, mask, limit):
    centred = (opd - np.mean(opd[mask])) * 1e9
    t = np.clip(np.nan_to_num(centred) / limit, -1, 1)[..., None]
    lo, mid, hi = np.array([[34, 82, 151], [232, 237, 239], [220, 92, 62]])
    rgb = np.where(t < 0, mid + (mid-lo)*t, mid + (hi-mid)*t)
    rgb[~mask] = [9, 17, 26]
    return np.uint8(rgb)


def psf_rgb(intensity, peak):
    z = np.clip((np.log10(np.maximum(intensity/peak, 1e-6))+6)/6, 0, 1)*5
    nodes = np.array([[5,9,19],[29,24,67],[112,40,100],[219,90,61],[250,193,91],[255,247,217]])
    i = np.minimum(z.astype(int), 4)
    f = (z-i)[..., None]
    return np.uint8(nodes[i]*(1-f)+nodes[i+1]*f)


def main():
    roots = [FIRST, REPAIR]
    folders = [FIRST/'attempt-04', REPAIR/'trajectory-v2']
    inputs = {}
    manifests = [read(p/'manifest.json') for p in roots]
    names = ['pre_update_residual_opd_m.npy', 'history.npz', 'science-psfs.npz', 'frame-metrics.csv']
    for i, folder in enumerate(folders):
        for name in names + (['atmosphere_opd_m.npy'] if i == 0 else []):
            p = folder/name
            expected = manifests[i]['artifacts'][str(p.relative_to(roots[i]))]
            actual = {'bytes': p.stat().st_size, 'sha256': sha(p)}
            assert actual == expected, p
            inputs[str(p.relative_to(ROOT))] = actual
    history = [dict(np.load(p/'history.npz')) for p in folders]
    saved = [dict(np.load(p/'science-psfs.npz')) for p in folders]
    rows = [list(csv.DictReader((p/'frame-metrics.csv').open())) for p in folders]
    mask = saved[0]['pupil_mask'].astype(bool)
    assert np.array_equal(mask, saved[1]['pupil_mask']) and mask.shape == (256,256)
    assert np.array_equal(saved[0]['ideal'], saved[1]['ideal'])
    assert np.array_equal(history[0]['time_s'], history[1]['time_s'])
    assert np.allclose(history[0]['time_s'], np.arange(1500)/750, rtol=0, atol=1e-15)
    assert all(len(r) == 1500 for r in rows)
    first_bad = int(np.flatnonzero(~history[0]['reconstruction_usable'])[0])
    assert first_bad == 736 and history[1]['reconstruction_usable'].all()
    maps = [np.load(folders[0]/'atmosphere_opd_m.npy', mmap_mode='r')]
    maps += [np.load(p/'pre_update_residual_opd_m.npy', mmap_mode='r') for p in folders]
    assert all(a.shape == (1500,256,256) for a in maps)
    # Use all recorded PSF frames plus denser *existing* OPD samples at loss of lock.
    sampled_psfs = sorted({int(k[6:]) for s in saved for k in s if k.startswith('frame_')})
    indices = sorted(set(range(0,1500,12)) | set(range(720,753)) | set(sampled_psfs) | {1499})
    max_abs_nm = 0.
    for k in indices:
        for a in maps:
            assert np.array_equal(np.isfinite(a[k]), mask)
            max_abs_nm = max(max_abs_nm, float(np.max(abs(a[k][mask]-np.mean(a[k][mask])))*1e9))
    limit_nm = float(np.ceil(max_abs_nm/500)*500)
    ideal = psf(np.zeros(mask.shape), mask)
    ideal_error = float(np.max(abs(ideal-saved[0]['ideal'])))
    assert ideal_error < 1e-14
    peak = float(ideal.max())
    step = float(np.diff(saved[0]['x_angle_rad'])[0]) * 180/np.pi*3600
    assert np.array_equal(saved[0]['x_angle_rad'], saved[0]['y_angle_rad'])
    assert np.allclose(saved[0]['x_angle_rad'], WAVELENGTH*np.fft.fftshift(np.fft.fftfreq(768, 2.2/255)), rtol=1e-12, atol=1e-16)
    half = int(np.floor(1.8/step)); cut = (slice(384-half,384+half+1),)*2
    metric_error = 0.; snapshot_error = 0.; snapshot_checks = 0
    scalar = {'time_s':history[0]['time_s'].tolist()}
    for j, name in enumerate(['v1','v2']):
        scalar[name] = {'strehl':[float(r['strehl_h']) for r in rows[j]],
            'rms_nm':(history[j]['pre_update_residual_opd_rms_m']*1e9).tolist(),
            'usable':history[j]['reconstruction_usable'].tolist(),
            'valid_fraction':history[j]['valid_measurement_fraction'].tolist()}
    scalar['uncorrected_strehl'] = [float(r['uncorrected_strehl_h']) for r in rows[0]]
    scalar['atmosphere_rms_nm'] = (history[0]['open_loop_opd_rms_m']*1e9).tolist()
    with tempfile.TemporaryDirectory(prefix='ngs-replay-') as temp:
        out = Path(temp); (out/'frames').mkdir()
        crops = []
        for k in indices:
            atlas = Image.new('RGB', (TILE*6, TILE))
            psfs = [psf(a[k], mask) for a in maps]
            for j, (a, p) in enumerate(zip(maps, psfs)):
                expected = scalar['uncorrected_strehl'][k] if j == 0 else scalar[['v1','v2'][j-1]]['strehl'][k]
                metric_error = max(metric_error, abs(float(p.max()/peak)-expected))
                if j and 'frame_'+str(k) in saved[j-1]:
                    snapshot_error = max(snapshot_error, float(np.max(abs(p-saved[j-1]['frame_'+str(k)]))))
                    snapshot_checks += 1
                atlas.paste(Image.fromarray(np.flipud(wave_rgb(a[k], mask, limit_nm))), (j*TILE,0))
                tile = Image.fromarray(np.flipud(psf_rgb(p[cut], peak))).resize((TILE,TILE), Image.Resampling.NEAREST)
                atlas.paste(tile, ((j+3)*TILE,0))
            atlas.save(out/'frames'/f'{k:04}.png', optimize=True)
            crops.append([float(p[cut].sum()) for p in psfs])
        assert snapshot_checks == 15 and snapshot_error < 1e-14
        assert metric_error < 1e-12
        data = {'schema':'ao-explorer.ngs-replay-data.v1','tile':TILE,'frames':1500,'interval_s':[0,2],
            'indices':indices,'loss_frame':first_bad,'loss_time_s':float(history[0]['time_s'][first_bad]),
            'wavelength_m':WAVELENGTH,'opd_limit_nm':limit_nm,'sampled_max_abs_opd_nm':max_abs_nm,
            'psf_field_arcsec':(2*half+1)*step,'psf_pixel_arcsec':step,'psf_crop_flux_fractions':crops,
            'metrics':scalar,'playback_durations_s':[20,40,60]}
        write(out/'data.json', data)
        write(out/'provenance.json', {'schema':'ao-explorer.ngs-replay-provenance.v1','inputs':inputs,
            'original_manifest_sha256':[sha(p/'manifest.json') for p in roots],
            'original_evidence_entry':read(WEB/'data/current.json')['ngs22'],
            'exporter_sha256':sha(Path(__file__)),
            'operations':['Read existing maps/metrics only; no AO runtime import, RNG, calibration, sensor or controller execution.',
                'Centered FFT of saved raw OPD, binary pupil, 3x padding, 1.65 um, unit total flux; no recentering or pupil tilt removal.',
                'Piston removal for wavefront display only; fixed common symmetric scale covers every displayed map without clipping.',
                'Flip both maps and PSFs vertically for positive y upwards; fixed common PSF crop and ideal-peak log scale from 1e-6 to 1.',
                'PSF crop uses nearest-neighbour enlargement for display; saved scalar curves retain all 1500 frames.',
                'Every 12th frame plus all saved PSF snapshots and each frame 720-752. No interpolation. Hold until next recorded timestamp.'],
            'checks':{'all_sources_hash_verified':True,'identical_time_arrays':True,
                'ideal_psf_max_abs_error':ideal_error,'saved_psf_snapshots_checked':snapshot_checks,
                'saved_psf_max_abs_error':snapshot_error,'sampled_strehl_max_abs_error':metric_error,
                'matched_strehl_samples':3*len(indices),'failure_frame':first_bad,'simulation_rerun':False}})
        shutil.copy2(__file__,out/'exporter.py')
        (out/'README.md').write_text('''# Synchronized 2.2 m NGS replay

Existing v1/v2 archives only. No AO trajectory is rerun. The same saved input
atmosphere accompanies both pre-update residuals. All 1500 scalar values
remain in data.json; display snapshots use their original frame-start times.
Frame 736 (0.981333333 s) is v1's first rejected reconstruction; it is not a
new estimate of when the optical quality first began to deteriorate.

PSFs are offline Fourier propagation of saved raw residuals at 1.65 um,
verified against all 15 previously archived v1/v2 snapshots and the saved
Strehl values of every displayed frame. The raw wavefront is not altered
before propagation. Only the displayed wavefront maps have piston removed;
tilt stays in all quantities. Common wavefront and PSF scales never rescale
with the frame. PSF crop flux fractions are recorded separately and cropping
never enters Strehl. No image interpolation between times is performed.

The original draft, all assumptions and repair evidence remain in the separate
NGS publication bundle referenced in provenance.json. Full raw wavefront
stacks remain local. Checks establish correspondence to that saved experiment,
not additional physical validation, a new noise realization or long-run stability.
''')
        files = {str(p.relative_to(out)):{'bytes':p.stat().st_size,'sha256':sha(p),
            'media_type':'image/png' if p.suffix=='.png' else 'application/json' if p.suffix=='.json' else 'text/plain'}
            for p in sorted(out.rglob('*')) if p.is_file()}
        digest = hashlib.sha256(json.dumps(files,sort_keys=True,separators=(',',':')).encode()).hexdigest()
        identity = 'ngs-replay-'+digest[:16]
        write(out/'manifest.json', {'schema':'ao-explorer.ngs-replay-manifest.v1','id':identity,'files':files})
        target = WEB/'recordings'/identity
        if target.exists():
            assert sha(target/'manifest.json') == sha(out/'manifest.json')
        else:
            shutil.copytree(out,target)
        entry = read(WEB/'data/current.json')
        entry['ngsReplay'] = {'schema':'ao-explorer.ngs-replay-entry.v1','id':identity,
            'manifest':'../recordings/'+identity+'/manifest.json','manifest_bytes':(target/'manifest.json').stat().st_size,
            'manifest_sha256':sha(target/'manifest.json')}
        write(WEB/'data/current.json', entry)
        print(json.dumps({'id':identity,'snapshots':len(indices),'bytes':sum(f['bytes'] for f in files.values()),
            'opd_limit_nm':limit_nm,'checks':read(out/'provenance.json')['checks']}),flush=True)

if __name__ == '__main__':
    main()
