"""One fixed 42 m trajectory and a disk-streamed, source-bound replay archive.

The production run is 500 frames at the profile's 500 Hz, seed 1, with a
predeclared [100,500) analysis window. All atmosphere/residual maps are kept;
126 actual display frames retain full-grid PSFs. The existing observer
computes every frame's PSFs and independent streaming intensity means.
No existing profile, trajectory or published website is changed.
"""
from __future__ import annotations

import argparse
from dataclasses import replace
import json
from pathlib import Path
import resource
import shutil
import sys
import time

import numpy as np
import identity
import producer
from long_series import NpyStreamWriter, sha256_file_chunked, utc_now
from observer import ExplorerObserver, independent_rms, independent_peak_strehl
from shwfs_ao.experiments.scao import ScaoExecutionOptions, build_scao_system, run_closed_loop
from shwfs_ao.io.configs import load_system_profile


class StreamReplay:
    requested_fields = ExplorerObserver.requested_fields

    def __init__(self, system, config, output, n_steps, burn_in, indices, wavelength):
        self.output = Path(output)
        self.inner = ExplorerObserver(system.science_propagator, wavelength_m=wavelength,
            n_steps=n_steps, burn_in=burn_in, display_indices=indices,
            telescope_diameter_m=config.telescope_diameter_m)
        self.writers = {name: NpyStreamWriter(self.output / f'{name}.npy',
            (n_steps, config.pupil_pixels, config.pupil_pixels))
            for name in ('atmosphere_opd_m', 'pre_update_residual_opd_m')}
        self.samples = []
        self.n_steps = n_steps
        self.start = time.monotonic()
        self.max_rms_error = 0.0
        self.max_strehl_error = 0.0

    def observe(self, observation):
        k = int(observation.frame_index)
        if time.monotonic() - self.start > 3 * 3600:
            raise TimeoutError('Three-hour trajectory timeout exceeded')
        self.inner.observe(observation)
        for name, writer in self.writers.items():
            writer.write(k, getattr(observation, name))
        mask = self.inner.pupil_mask
        for name, key in [('atmosphere_opd_m','atmosphere_rms_m'),
                          ('pre_update_residual_opd_m','residual_rms_m')]:
            error = abs(independent_rms(getattr(observation, name), mask) - self.inner.frames[key][-1])
            self.max_rms_error = max(self.max_rms_error, error)
        if k in self.inner.display:
            frame = self.inner.display.pop(k)
            path = self.output / 'samples' / f'{k:04d}.npz'
            np.savez(path, psf_uncorrected=frame['psf_uncorrected'], psf_corrected=frame['psf_corrected'])
            for role in ('uncorrected','corrected'):
                error = abs(independent_peak_strehl(frame[f'psf_{role}'], self.inner.ideal_psf.intensity)
                            - self.inner.frames[f'peak_strehl_{role}'][-1])
                self.max_strehl_error = max(self.max_strehl_error, error)
            self.samples.append({'frame':k, 'path':str(path.relative_to(self.output)),
                                 'bytes':path.stat().st_size, 'sha256':sha256_file_chunked(path)})
        if k == 0 or (k + 1) % 10 == 0 or k + 1 == self.n_steps:
            progress = {'status':'RUNNING','frames':k+1,'total':self.n_steps,
                        'elapsed_s':round(time.monotonic()-self.start,2),'updated_utc':utc_now()}
            producer.write_json(self.output / 'progress.json',progress)
            print(json.dumps(progress),flush=True)


def run(output: Path, *, small=False):
    output.mkdir(parents=True, exist_ok=False)
    (output/'samples').mkdir()
    started = time.monotonic()
    n, burn, stride = (8,2,2) if small else (500,100,4)
    name = 'det_emccd_2m_synthetic' if small else 'det_ccd_42m_r3band_derived'
    base = load_system_profile(name,1)
    config = replace(base,controller=replace(base.controller,n_steps=n),
                     random=replace(base.random,root_seed=1))
    wave = 2.2e-6
    indices = sorted(set(range(0,n,stride)) | {n-1,burn})
    core = identity.core_identity()
    sources = {name:identity.sha256_file(Path(__file__).parent/name)
               for name in ('replay_42m.py','observer.py','long_series.py','producer.py','identity.py','protocol.py')}
    lock = identity.lock_verification()
    # The shared environment also has analytical-study packages installed.
    # Require every pinned version to match; disclose extras, never call this
    # an exact locked environment when extra distributions are present.
    incompatible = [v for v in lock['violations'] if not v.endswith('(lock: None)')]
    if incompatible:
        raise RuntimeError(f'Pinned dependency version mismatch: {incompatible}')
    lock['pinned_versions_compatible'] = True
    expected_bytes = 2*n*config.pupil_pixels**2*8 + 2*len(indices)*(config.pupil_pixels*config.science.psf_pad_factor)**2*8
    if shutil.disk_usage(output).free < expected_bytes + 2*1024**3:
        raise RuntimeError('Insufficient disk space for full-precision recording')
    plan = {'schema':'ao-explorer.42m-plan.v1','created_utc':utc_now(),'profile':f'{name}@1',
            'config':producer.to_jsonable(config),'config_hash':config.config_hash,
            'root_seed':1,'realization_index':0,'n_steps':n,'burn_in_frames':burn,
            'analysis_window':[burn,n],'science_wavelength_m':wave,'display_indices':indices,
            'frame_rate_hz':config.controller.frame_rate_hz,'physical_duration_s':n/config.controller.frame_rate_hz,
            'residual':'pre_update','uncorrected':'same atmosphere, zero DM optical counterfactual',
            'averaging':'equal-weight instantaneous intensities over analysis_window; no recentering',
            'scope':'single-realization recorded demonstration; startup exclusion is not a convergence result',
            'authorization':'User requested one fixed 42 m recorded trajectory and local preview; no publication',
            'raw_storage_estimate_bytes':expected_bytes,'timeout_s':10800,
            'core':core,'producer_sources':sources,'environment':identity.environment_identity(),
            'lock':lock,'host':identity.host_identity(),
            'execution':{'lenslet_batch_size':128,'atmosphere_band_storage':'materialized' if small else 'regenerate','telemetry_level':'summary','native_threads':2}}
    producer.write_json(output/'plan.json',plan)
    for filename in sources:
        target=output/'producer-source'/filename
        target.parent.mkdir(exist_ok=True)
        shutil.copyfile(Path(__file__).parent/filename,target)
    options = ScaoExecutionOptions(lenslet_batch_size=128,atmosphere_band_storage='materialized' if small else 'regenerate',telemetry_level='summary')
    print(json.dumps({'status':'BUILDING','plan':str(output/'plan.json'),'raw_bytes_estimate':expected_bytes}),flush=True)
    system = build_scao_system(config,execution=options)
    build_s = time.monotonic()-started
    archive = StreamReplay(system,config,output,n,burn,indices,wave)
    history = run_closed_loop(config,system=system,observers=(archive,),realization_index=0)
    raw = {name:writer.close() for name,writer in archive.writers.items()}
    # finish() checks that display frames are retained; the disk archive owns them now.
    archive.inner.display = {k:None for k in indices}
    result=archive.inner.finish()
    arrays=producer.history_arrays(history)
    np.savez(output/'history.npz',**arrays)
    np.savez(output/'science.npz',mean_uncorrected=result['mean_psf_uncorrected'],
             mean_corrected=result['mean_psf_corrected'],ideal=result['ideal_psf'],
             pupil_mask=archive.inner.pupil_mask,**archive.inner.axes)
    producer.write_json(output/'frames.json',archive.inner.frames)
    checks = {
        'atmosphere_rms_matches_history':np.array_equal(archive.inner.frames['atmosphere_rms_m'], arrays['open_loop_opd_rms_m']),
        'residual_rms_matches_history':np.array_equal(archive.inner.frames['residual_rms_m'], arrays['pre_update_residual_opd_rms_m']),
        'times_match_history':np.array_equal(archive.inner.frames['time_s'],arrays['time_s']),
        'max_independent_rms_error_m':archive.max_rms_error,
        'max_independent_strehl_error':archive.max_strehl_error,
        'streaming_mean_max_abs_difference':result['streaming_max_abs_difference'],
    }
    if small:
        control=run_closed_loop(config,execution=options)
        checks['observer_neutral_history']=producer.history_digest(control)==producer.history_digest(history)
    passed = all(checks[k] for k in ('atmosphere_rms_matches_history','residual_rms_matches_history','times_match_history'))
    passed &= archive.max_rms_error<1e-15 and archive.max_strehl_error<1e-12
    passed &= max(result['streaming_max_abs_difference'].values())<1e-12
    passed &= checks.get('observer_neutral_history', True)
    if not passed: raise RuntimeError(f'Archive verification failed: {checks}')
    record={'schema':'ao-explorer.42m-record.v1','status':'COMPLETED','completed_utc':utc_now(),
            'plan_sha256':sha256_file_chunked(output/'plan.json'),'config_hash':config.config_hash,
            'core_sha256_after':identity.core_identity()['package_sha256'],
            'build_s':build_s,'wall_s':time.monotonic()-started,
            'process_peak_rss_bytes':resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
            'checks':checks,'raw_maps':raw,'samples':archive.samples,
            'history_metadata':producer.to_jsonable(history.metadata),
            'atmosphere_metadata':producer.to_jsonable(system.atmosphere.metadata),
            'science_corrected':producer.to_jsonable(result['corrected_result']),
            'science_uncorrected':producer.to_jsonable(result['uncorrected_result'])}
    if record['core_sha256_after']!=core['package_sha256']: raise RuntimeError('Core changed during run')
    record['files']={f:{'sha256':sha256_file_chunked(output/f),'bytes':(output/f).stat().st_size}
                     for f in ('plan.json','frames.json','history.npz','science.npz')}
    producer.write_json(output/'record.json',record)
    producer.write_json(output/'progress.json',{'status':'COMPLETED','frames':n,'total':n,'wall_s':record['wall_s']})
    print(json.dumps({'status':'COMPLETED','output':str(output),'wall_s':record['wall_s'],'checks':checks}),flush=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',required=True,type=Path)
    parser.add_argument('--small-check',action='store_true')
    args=parser.parse_args()
    try:
        run(args.output,small=args.small_check)
    except Exception as exc:
        if args.output.exists(): producer.write_json(args.output/'failure.json',{'utc':utc_now(),'error':repr(exc)})
        raise
