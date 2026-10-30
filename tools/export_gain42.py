"""Export and validate the accepted 42 m gain–latency records; saved data only.

Requires NumPy. No simulation package, analyzer, calibration or propagation is
imported. --compact-root names the extracted, accepted compact evidence.
--write adds one immutable bundle to --web-dir and extends its entry.
--validate-bundle checks an existing bundle without the scientific inputs.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
from pathlib import Path, PurePosixPath
import shutil
import tempfile

import numpy as np

ANALYSIS_SHA = '0ec6a0375a150c84db1ec9058f82dba030a5840b04a1a3900a94ed93d39a13be'
INDEX_SHA = '7657d0f4cab74c2bf8c8edaaabcabf73d8446dfac2bf1275abac1cb2c7604798'
PLAN_SHA = '7635cd7ac82f561362417c1d39df11bc1a20a074dbe5a5e6f211fe3132b402c0'
PRODUCER = '642a5b76de97e1fbe46fc49dd5fad232fb725219'
PACKAGE_SHA = '6d6af99099df088c3e172ae5256dfebe1b6b97911f8bdce276eda7f8dbf24914'
SOURCE = {
    'repository': 'xhvoid/ao-p3-transfer', 'access': 'private evidence; identities, not public download links',
    'branch': 'study/42m-gain-latency-20261029-d06e20',
    'analysis_commit': '3e709b6ce0fa519c90d4fb800ca8d3fdde1a4f73',
    'compact_commit': '9d6e32d14415fa5cf48bc50adc75121a57dd86d6',
    'closing_addendum': '91dd938650ad81ad44a752753e82f6c7dd268fad',
    'compact_archive_bytes': 21985280,
    'compact_archive_sha256': '029335d1f3e5823308dd951b70d80ef25761135f4f1920f2089b86dd78437cde',
    'analysis_sha256': ANALYSIS_SHA, 'compact_index_sha256': INDEX_SHA,
    'producer_commit': PRODUCER, 'scientific_package_sha256': PACKAGE_SHA,
}
METRICS = {'mean_pre_update_rms_nm': 'nm', 'peak_strehl': 'dimensionless', 'fourier_ee50_lambda_over_d': 'lambda/D'}
WINDOWS = {'primary': [100, 500], 'early': [100, 300], 'late': [300, 500], 'final_block': [400, 500], 'final50': [450, 500]}
SETTINGS = {'gains': [0.2, 0.3], 'delays': [2, 3], 'realizations': [0, 1, 2],
            'frames': 500, 'frame_rate_hz': 500, 'flux_e_per_full_subap_frame': 100000,
            'noise': True, 'noise_policy': 'native scoped', 'root_seed': 1, 'leak': 0,
            'damping': 0.001, 'science_wavelength_m': 2.2e-6, 'psf_padding': 2}
T = math.sqrt(2 * .95**2 / (1 - .95**2))


class ExportError(ValueError):
    pass


def require(ok, what):
    if not ok:
        raise ExportError(what)


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def read(path):
    def reject(s):
        raise ExportError('Nonfinite JSON constant: ' + s)
    return json.loads(Path(path).read_text(), parse_constant=reject)


def write(path, value):
    Path(path).write_text(json.dumps(value, allow_nan=False, separators=(',', ':')) + '\n')


def number(v, what):
    require(type(v) in (int, float) and math.isfinite(v), what + ': required finite number')
    return v


def same(a, b, what, tol=1e-10):
    number(a, what); number(b, what)
    require(abs(a-b) <= tol * max(1, abs(b)), what + ': inconsistent value')


def flat(value, prefix=''):
    if isinstance(value, dict):
        return {k: v for n, item in value.items() for k, v in flat(item, prefix+'/'+n).items()}
    return {prefix: value}


class Package:
    def __init__(self, root):
        self.root = Path(root).resolve()
        require(sha(self.root/'COMPACT_PACKAGE.json') == INDEX_SHA, 'Compact index identity mismatch')
        self.index = read(self.root/'COMPACT_PACKAGE.json')
        self.consumed = {'COMPACT_PACKAGE.json': {'sha256': INDEX_SHA, 'bytes': (self.root/'COMPACT_PACKAGE.json').stat().st_size}}

    def path(self, name, expected=None):
        p = PurePosixPath(name)
        require(not p.is_absolute() and '..' not in p.parts and p.as_posix() == name, 'Unsafe input path')
        f = self.root/name
        ref = self.index['files'].get(name)
        require(isinstance(ref, dict) and f.is_file() and not f.is_symlink() and self.root in f.resolve().parents, 'Missing indexed input: '+name)
        require(type(ref['bytes']) is int and f.stat().st_size == ref['bytes'] and sha(f) == ref['sha256'], 'Input digest mismatch: '+name)
        if expected:
            require(ref['sha256'] == expected, 'Accepted digest mismatch: '+name)
        self.consumed[name] = ref
        return f

    def json(self, name, expected=None):
        return read(self.path(name, expected))


def selection(records):
    require(type(records) is list and len(records) == 12, 'Exactly twelve records required')
    found = set()
    for r in records:
        g, l, z = r['gain'], r['latency_frames'], r['realization_index']
        number(g, 'gain')
        require(type(l) is int and type(z) is int and g in (.2, .3) and l in (2, 3) and z in (0, 1, 2), 'Wrong gain/delay/realization')
        key = (g, l, z)
        require(key not in found, 'Duplicate record'); found.add(key)
        expected = f'g020-lat{l}-flux100000-r{z}' if g == .2 else (f'flux100000-r{z}' if l == 2 else f'lat3-flux100000-r{z}')
        require(r['run_key'] == expected and r['status'] == 'completed_verified', 'Wrong accepted record selection')
        require(r['source'] == ('new (gain 0.2)' if g == .2 else 'baseline (gain 0.3, reused)'), 'Wrong new/reused mapping')


def stats(values):
    require(type(values) is list and len(values) == 3, 'Three realization-level values required')
    for v in values: number(v, 'paired value')
    mean = sum(values)/3
    sd = math.sqrt(sum((v-mean)**2 for v in values)/2)
    half = T*sd/math.sqrt(3)
    return {'by_realization': values, 'mean': mean, 'sample_sd': sd, 'ci95': [mean-half, mean+half], 'df': 2}


def summarize(pre, valid):
    out = {n+'_mean_nm': sum(pre[a:b])/(b-a) for n, (a, b) in WINDOWS.items()}
    out.update({'late_minus_early_nm': out['late_mean_nm']-out['early_mean_nm'],
                'frames_valid_below_0_995': sum(v < .995 for v in valid[100:500]),
                'valid_min': min(valid[100:500]), 'valid_min_frame': 100+valid[100:500].index(min(valid[100:500]))})
    return out


def contrasts(records):
    m = {(r['gain'], r['delay'], r['realization']): r for r in records}
    levels, paired = {}, {}
    for metric in METRICS:
        val = lambda g,l,z: m[g,l,z]['metrics'][metric]
        levels[metric] = {f'g{g}-L{l}': stats([val(g,l,z) for z in range(3)]) for g in (.2,.3) for l in (2,3)}
        effects = {f'G_L{l}': [val(.2,l,z)-val(.3,l,z) for z in range(3)] for l in (2,3)}
        effects.update({f'D_g{g}': [val(g,3,z)-val(g,2,z) for z in range(3)] for g in (.2,.3)})
        effects['I'] = [effects['D_g0.2'][z]-effects['D_g0.3'][z] for z in range(3)]
        paired[metric] = {k: stats(v) for k,v in effects.items()}
    return levels, paired


def validate_display(d):
    require(d['schema'] == 'ao-explorer.gain42-data.v1' and d['settings'] == SETTINGS and d['windows'] == WINDOWS, 'Wrong study design')
    # Equality of dictionaries alone accepts True == 1: enforce primitive types too.
    require(json.dumps(d['settings'], sort_keys=True) == json.dumps(SETTINGS, sort_keys=True), 'Wrong setting types')
    rows = d['records']; require(type(rows) is list and len(rows) == 12, 'Missing display records')
    found = set(); atmospheres = {}
    for r in rows:
        g,l,z = r['gain'],r['delay'],r['realization']; number(g,'gain')
        require(type(l) is int and type(z) is int and g in (.2,.3) and l in (2,3) and z in (0,1,2), 'Invalid display mapping')
        key=(g,l,z); require(key not in found,'Duplicate display record'); found.add(key)
        expected = f'g020-lat{l}-flux100000-r{z}' if g == .2 else (f'flux100000-r{z}' if l == 2 else f'lat3-flux100000-r{z}')
        require(r['run_key']==expected and r['source']==('new' if g==.2 else 'reused'), 'Wrong display record identity')
        require(type(r['attempt']) is int and r['attempt']==(2 if key==(.3,3,2) else 1), 'Wrong baseline attempt')
        for name in ['residual_nm','valid_fraction']:
            a=r[name];require(type(a) is list and len(a)==500, 'Missing recorded trace')
            for v in a:
                number(v,name);require(v>0 if name=='residual_nm' else 0<=v<=1,'Invalid trace range')
        for k,v in summarize(r['residual_nm'],r['valid_fraction']).items():
            if k in ('frames_valid_below_0_995','valid_min_frame'): require(type(r['history_summary'][k]) is int, 'Invalid count type')
            same(v,r['history_summary'][k],k)
        same(r['metrics']['mean_pre_update_rms_nm'],r['history_summary']['primary_mean_nm'],'Primary residual')
        for k in METRICS: require(number(r['metrics'][k],k)>0,'Invalid primary metric')
        require(r['image_provenance']['analysis_sha256']==ANALYSIS_SHA, 'Image analysis provenance mismatch')
        win=r['windowed_images']
        require(win['status']==('available' if g==.2 else 'unavailable'), 'Wrong windowed-image availability')
        if g==.3:
            require(win['values'] is None and type(win['reason']) is str, 'Missing baseline images must be unavailable, not zero')
        else:
            require(set(win['values'])=={'100_300','300_400','400_500'} and win['analysis_sha256']==ANALYSIS_SHA, 'Wrong new image windows')
            for k,q in win['values'].items():
                require(0<number(q['peak_strehl'],'windowed Strehl')<=1 and type(q['samples']) is int and q['samples']==(200 if k=='100_300' else 100), 'Invalid image summary')
                require(type(q['intensity_sha256']) is str and len(q['intensity_sha256'])==64, 'Missing image identity')
        pairing=r['pairing']; require(type(pairing) is dict and set(pairing)=={'pupil_chain','map_chain','pupil_mask','atmosphere_stream','noise_scope','open_loop_sha256'}, 'Incomplete atmospheric pairing')
        require(all(type(v) is str and v for v in pairing.values()), 'Invalid pairing identity')
        if z in atmospheres: require(atmospheres[z]==pairing, 'Atmospheric pairing mismatch')
        else: atmospheres[z]=pairing
    require(len({a['pupil_chain'] for a in atmospheres.values()})==3, 'Realizations are not distinct')
    levels,paired=contrasts(rows)
    for name,computed in [('levels',levels),('contrasts',paired)]:
        require(set(d[name])==set(computed),'Missing metrics')
        for metric, items in computed.items():
            require(set(d[name][metric])==set(items),'Missing contrast/cell')
            for k,q in items.items():
                ref=d[name][metric][k]
                require(ref['df']==2 and type(ref['df']) is int,'Wrong interval degrees of freedom')
                for f in ['mean','sample_sd']: same(q[f],ref[f],name+'/'+metric+'/'+k+'/'+f)
                for f in ['by_realization','ci95']:
                    require(type(ref[f]) is list and len(ref[f])==len(q[f]), 'Missing paired values')
                    for a,b in zip(q[f],ref[f]): same(a,b,name+'/'+metric+'/'+k+'/'+f)
    return {'records':12,'new':6,'reused':6,'history_samples':12000,'paired_contrasts':15}


def export(root, out):
    p=Package(root);a=p.json('analysis/gl_results.json',ANALYSIS_SHA);plan=p.json('plan/GL_PLAN.json',PLAN_SHA)
    baseline=p.json('baseline/baseline_verification.json','04e383b4f16a3ef8aed2e4544615bc3df9daeea91fde883e3076805c8f5860dd')
    require(plan['source']['commit']==PRODUCER and plan['source']['package']['sha256']==PACKAGE_SHA,'Wrong scientific producer')
    selection(a['records']);rows=[];configurations={};open_loops={}
    stages=p.json('report/STAGES.json')['stages']
    require(len(p.index['records'])==12,'Wrong compact record selection')
    for record in a['records']:
        g,l,z=record['gain'],record['latency_frames'],record['realization_index'];key=f'g{g}-L{l}-r{z}'
        ir=p.index['records'][key if g==.3 else record['run_key']]
        if g==.3:
            require(ir['run_key']==record['run_key'],'Compact run mapping mismatch')
            b=plan['baselines'][f'L{l}-r{z}'];bv=baseline['baselines'][f'L{l}-r{z}']
            require(bv['eligible'] is True and b['stage_commit']==ir['stage_commit']==bv['stage_commit'],'Baseline reuse identity mismatch')
            if l==3 and z==2: require(ir['stage'].endswith('-attempt2') and ir['stage_commit']=='8114d52040c4c7829464ed164d69c6b76601e4c9','Interrupted baseline attempt selected')
            directory=f'records/baseline/{key}-{record["run_key"]}'
        else:
            stage=next(q for q in stages if q['stage']=='export/gl42m-run-'+record['run_key'])
            require(stage['receipt_all_passed'] is True and ir['source']=='new','New stage not accepted')
            ir={**ir,'stage_commit':stage['commit']}
            require(any(q['run_key']==record['run_key'] and q['gain']==g and q['latency_frames']==l and q['realization_index']==z for q in plan['runs']),'Unplanned new record')
            directory=f'records/new/{record["run_key"]}/output'
        files={}
        for n in ['config.json','identity.json','science_record.json','build_identities.json','history_metadata.json','atmosphere_digest.json','run_summary.json']:
            files[n]=p.json(directory+'/'+n,record['metrics']['files'][n]['sha256'])
        cfg=files['config.json']['effective_config'];meta=files['history_metadata.json']['metadata'];ident=files['identity.json'];build=files['build_identities.json'];atm=files['atmosphere_digest.json']
        expected={'/controller/gain':g,'/controller/latency_frames':l,'/controller/n_steps':500,'/controller/frame_rate_hz':500.,'/controller/leak':0.,'/controller/include_noise':True,'/reconstructor/alpha':.001,'/random/root_seed':1,'/science/psf_pad_factor':2,'/detector_physics/source/detected_e_per_full_subap_frame':100000.}
        flattened=flat(cfg)
        for k,v in expected.items():
            require(type(flattened.get(k)) is type(v) and flattened[k]==v, 'Config setting/type mismatch: '+k)
        require(cfg['science_wavelengths_m']==[2.2e-6] and type(meta['realization_index']) is int and meta['realization_index']==z and meta['include_noise'] is True,'Metadata setting mismatch')
        require(ident['run_key']==record['run_key'] and type(ident['realization_index']) is int and ident['realization_index']==z,'Run identity mismatch')
        # Original photon-budget identity has no delay field: its effective
        # config and saved build above/below bind delay 2 directly.
        if (g,l)!=(.3,2) or 'latency_frames' in ident:
            require(type(ident.get('latency_frames')) is int and ident['latency_frames']==l,'Run delay identity mismatch')
        require(ident['shwfs_ao_package']['sha256']==PACKAGE_SHA,'Scientific package digest mismatch')
        require(build['build_attestation']['source_config']['controller']==cfg['controller'],'Built controller mismatch')
        configurations[g,l,z]=cfg
        history=p.path(directory+'/history.npz',record['metrics']['files']['history.npz']['sha256'])
        with np.load(history,allow_pickle=False) as zf:
            arrays={k:zf[k] for k in ['time_s','pre_update_residual_opd_rms_m','open_loop_opd_rms_m','valid_measurement_fraction','reconstruction_usable','saturation_fraction']}
        for k,arr in arrays.items():
            require(arr.shape==(500,) and arr.dtype==(np.bool_ if k=='reconstruction_usable' else np.float64) and np.isfinite(arr).all(),'Malformed required history: '+k)
        require(np.allclose(arrays['time_s'],np.arange(500)/500,rtol=0,atol=1e-12) and arrays['reconstruction_usable'].all() and not arrays['saturation_fraction'].any(),'History timing/usability mismatch')
        pre=(arrays['pre_update_residual_opd_rms_m']*1e9).tolist();valid=arrays['valid_measurement_fraction'].tolist();summary=summarize(pre,valid)
        for k,n in [('early_mean_nm','pre_early_mean_nm'),('late_mean_nm','pre_late_mean_nm'),('final_block_mean_nm','pre_final_block_mean_nm'),('final50_mean_nm','pre_final50_mean_nm'),('late_minus_early_nm','pre_late_minus_early_nm'),('frames_valid_below_0_995','frames_valid_below_0_995'),('valid_min','valid_min'),('valid_min_frame','valid_min_frame')]:same(summary[k],record['late'][n],key+'/'+k)
        image=record['metrics']['image'];sc=files['science_record.json']
        same(image['peak_strehl'],sc['long_exposure_result']['metrics'][0]['peak_strehl'],'Recorded Strehl')
        require(sc['selection']['first_frame']==100 and sc['selection']['last_frame']==499 and sc['selection']['sample_count']==400,'Image selection mismatch')
        windowed={'status':'unavailable','reason':'Not recorded for reused gain-0.3 baselines; no matched baseline windowed images.','values':None}
        if g==.2:
            diagdir=f'records/new/{record["run_key"]}/diagnostics';diag=p.json(diagdir+'/diagnostics_record.json');ds=p.json(diagdir+'/diagnostics_summary.json')
            require(ds['run_key']==record['run_key'] and ds['combination_check_passed'] is True and ds['files']['diagnostics_record.json']['sha256']==sha(p.root/diagdir/'diagnostics_record.json'),'Diagnostic binding mismatch')
            vals={}
            for name,q in record['windows']['windows'].items():
                dq=next(v for v in diag['windows'] if v['window']==list(map(int,name.split('_'))))
                same(q['peak_strehl'],dq['metrics']['peak_strehl'],'Windowed image Strehl')
                require(q['intensity_sha256']==dq['intensity_sha256'],'Windowed intensity digest mismatch')
                vals[name]={'peak_strehl':q['peak_strehl'],'samples':q['sample_count'],'intensity_sha256':q['intensity_sha256']}
            windowed={'status':'available','values':vals,'analysis_sha256':ANALYSIS_SHA,'provenance':'Accepted hash-bound analysis and recorded diagnostic summaries; arrays omitted, not recalculated here.'}
        loop=arrays['open_loop_opd_rms_m'];loopsha=hashlib.sha256(loop.tobytes()).hexdigest()
        if z in open_loops: require(np.array_equal(loop,open_loops[z]),'Open-loop atmospheric pairing mismatch')
        else:open_loops[z]=loop.copy()
        pairing={'pupil_chain':atm['atmosphere_pupil_chain_sha256'],'map_chain':atm['atmosphere_full_map_chain_sha256'],'pupil_mask':atm['pupil_mask_sha256'],'atmosphere_stream':meta['atmosphere_realization_stream_id'],'noise_scope':meta['random_stream_ids']['detector.shot_noise'],'open_loop_sha256':loopsha}
        for k,n in [('pupil_chain','atmosphere_pupil_chain_sha256'),('map_chain','atmosphere_full_map_chain_sha256'),('pupil_mask','pupil_mask_sha256')]:require(pairing[k]==record['metrics']['identities'][n],'Analysis atmospheric digest mismatch')
        metrics={'mean_pre_update_rms_nm':summary['primary_mean_nm'],'peak_strehl':image['peak_strehl'],'fourier_ee50_lambda_over_d':image['fourier_ee50_lambda_over_d']}
        same(metrics['mean_pre_update_rms_nm'],record['metrics']['residual']['pre_update_rms_m']['mean']*1e9,'Primary residual analysis')
        rows.append({'run_key':record['run_key'],'gain':g,'delay':l,'realization':z,'source':'new' if g==.2 else 'reused','attempt':2 if (g,l,z)==(.3,3,2) else 1,'stage_commit':ir['stage_commit'],'residual_nm':pre,'valid_fraction':valid,'history_summary':summary,'metrics':metrics,'pairing':pairing,'image_provenance':{'analysis_sha256':ANALYSIS_SHA,'science_record_sha256':record['metrics']['files']['science_record.json']['sha256'],'mean_psf_archive_sha256':record['metrics']['files']['mean_psf.npz']['sha256'],'calculation':'carried from accepted analysis; large arrays omitted'},'windowed_images':windowed})
    for l in (2,3):
        for z in range(3):
            a0,b0=flat(configurations[.2,l,z]),flat(configurations[.3,l,z])
            require([k for k in a0 if a0[k]!=b0.get(k)]==['/controller/gain'],'Effective configuration differs beyond gain')
    levels,paired=contrasts(rows)
    for metric,items in paired.items():
        for k,q in items.items():
            ref=a['contrasts'][metric][k]
            for f,rf in [('mean','mean' if k=='I' else 'mean_difference'),('sample_sd','sample_sd')]:same(q[f],ref[rf],metric+'/'+k+'/'+f)
            for i,n in enumerate(['ci95_low','ci95_high']):same(q['ci95'][i],ref[n],metric+'/'+k+'/'+n)
            refvalues=ref['by_realization' if k=='I' else 'differences_by_realization']
            for z,v in enumerate(q['by_realization']):same(v,refvalues[str(z)],'Individual contrast sign/value')
    data={'schema':'ao-explorer.gain42-data.v1','settings':SETTINGS,'windows':WINDOWS,'units':METRICS,'records':rows,'levels':levels,'contrasts':paired,'source':SOURCE}
    validation=validate_display(data)
    out=Path(out);out.mkdir(parents=True,exist_ok=True);write(out/'data.json',data)
    write(out/'provenance.json',{'schema':'ao-explorer.gain42-provenance.v1','source':SOURCE,'inputs':p.consumed,'exporter_sha256':sha(__file__),'recomputed':['residual window means','validity minima/counts','cell means','paired values and df-2 intervals','interaction from three interaction values'],'carried':['whole-window image metrics','new-run windowed Strehl summaries'],'limitations':['Large PSF and residual-snapshot arrays omitted; no independent image or wavefront recomputation.','Three conditional atmospheric realizations, one root seed and native scoped noise policy. Frames are not replicates.']})
    with (out/'frames.csv').open('w',newline='') as f:
        writer=csv.writer(f);writer.writerow(['run_key','gain','delay','realization','frame','time_s','residual_nm','valid_fraction'])
        for r in rows:
            for k in range(500):writer.writerow([r['run_key'],r['gain'],r['delay'],r['realization'],k,k/500,r['residual_nm'][k],r['valid_fraction'][k]])
    shutil.copyfile(__file__,out/'exporter.py')
    notes=Path(__file__).parent/'gain42_notes'
    if not notes.is_dir(): notes=Path(__file__).parent
    for n in ['README.md','CORRECTIONS.md']:shutil.copyfile(notes/n,out/n)
    members={f.name:{'bytes':f.stat().st_size,'sha256':sha(f),'media_type':{'.json':'application/json','.md':'text/markdown','.csv':'text/csv','.py':'text/plain'}[f.suffix]} for f in sorted(out.iterdir())}
    identity='gain42-'+hashlib.sha256(json.dumps(members,sort_keys=True,separators=(',',':')).encode()).hexdigest()[:16]
    write(out/'manifest.json',{'schema':'ao-explorer.gain42-manifest.v1','id':identity,'files':members})
    return identity,validation


def validate_bundle(directory):
    directory=Path(directory);m=read(directory/'manifest.json')
    require(m['schema']=='ao-explorer.gain42-manifest.v1','Wrong bundle schema')
    require(m['id']=='gain42-'+hashlib.sha256(json.dumps(m['files'],sort_keys=True,separators=(',',':')).encode()).hexdigest()[:16],'Bundle content identity mismatch')
    require({p.name for p in directory.iterdir()}==set(m['files'])|{'manifest.json'},'Unlisted/missing bundle members')
    for n,q in m['files'].items():
        require(PurePosixPath(n).name==n and not (directory/n).is_symlink(),'Unsafe member')
        require(sha(directory/n)==q['sha256'] and (directory/n).stat().st_size==q['bytes'],'Member hash mismatch: '+n)
    return validate_display(read(directory/'data.json'))


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--compact-root',type=Path);parser.add_argument('--web-dir',type=Path);parser.add_argument('--write',action='store_true');parser.add_argument('--validate-bundle',type=Path)
    args=parser.parse_args()
    try:
        if args.validate_bundle: result=validate_bundle(args.validate_bundle)
        else:
            require(args.compact_root is not None,'--compact-root required')
            with tempfile.TemporaryDirectory(prefix='gain42-') as tmp:
                out=Path(tmp)/'bundle';identity,result=export(args.compact_root,out);validate_bundle(out);result['bundle']=identity
                if args.write:
                    require(args.web_dir is not None,'--web-dir required');target=args.web_dir/'derived'/identity
                    if target.exists(): require(read(target/'manifest.json')==read(out/'manifest.json'),'Immutable bundle conflict')
                    else:shutil.copytree(out,target)
                    validate_bundle(target);entrypath=args.web_dir/'data/current.json';entry=read(entrypath)
                    require('gain42' not in entry or entry['gain42']['id']==identity,'Existing gain bundle differs; explicit integration required')
                    entry['gain42']={'schema':'ao-explorer.gain42-entry.v1','id':identity,'manifest':f'../derived/{identity}/manifest.json','manifest_bytes':(target/'manifest.json').stat().st_size,'manifest_sha256':sha(target/'manifest.json')}
                    entrypath.write_text(json.dumps(entry,indent=1)+'\n')
        print(json.dumps({'passed':True,'simulation_run':False,**result},indent=2));return 0
    except (ExportError,KeyError,TypeError,ValueError,OSError) as e:
        print(json.dumps({'passed':False,'error':str(e)}));return 2


if __name__=='__main__':
    raise SystemExit(main())
