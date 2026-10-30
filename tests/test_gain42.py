"""Focused saved-data and refusal cases. No simulation imports or execution."""
from copy import deepcopy
import hashlib
import importlib.util
import json
import math
import os
from pathlib import Path

import numpy as np
import pytest

SPEC=importlib.util.spec_from_file_location('gain_export',Path(__file__).parents[1]/'tools/export_gain42.py')
g=importlib.util.module_from_spec(SPEC);SPEC.loader.exec_module(g)


def oracle(values):
    a=np.array(values);mean=float(a.mean());sd=float(a.std(ddof=1));half=4.302652729749464*sd/math.sqrt(3)
    return {'by_realization':list(values),'mean':mean,'sample_sd':sd,'ci95':[mean-half,mean+half],'df':2}


def fixture():
    rows=[]
    for gain in [.2,.3]:
        for delay in [2,3]:
            for z in range(3):
                # Hand-readable 2x2 contrasts: I = -5, -6, -7 nm.
                v=100+z+(20 if gain==.2 else 0)+(0 if delay==2 else (5-z if gain==.2 else 10))
                q={'gain':gain,'delay':delay,'realization':z,'run_key':f'g020-lat{delay}-flux100000-r{z}' if gain==.2 else f'flux100000-r{z}' if delay==2 else f'lat3-flux100000-r{z}',
                   'source':'new' if gain==.2 else 'reused','attempt':2 if (gain,delay,z)==(.3,3,2) else 1,
                   'residual_nm':[float(v)]*500,'valid_fraction':[1.]*500,
                   'history_summary':{**{n+'_mean_nm':float(v) for n in g.WINDOWS},'late_minus_early_nm':0.,'frames_valid_below_0_995':0,'valid_min':1.,'valid_min_frame':100},
                   'metrics':{'mean_pre_update_rms_nm':float(v),'peak_strehl':1-v/1000,'fourier_ee50_lambda_over_d':v/100},
                   'image_provenance':{'analysis_sha256':g.ANALYSIS_SHA},
                   'pairing':{k:str(z)+k for k in ['pupil_chain','map_chain','pupil_mask','atmosphere_stream','noise_scope','open_loop_sha256']},
                   'windowed_images':{'status':'unavailable','values':None,'reason':'not recorded'}}
                if gain==.2:q['windowed_images']={'status':'available','analysis_sha256':g.ANALYSIS_SHA,'values':{n:{'peak_strehl':.7,'samples':200 if n=='100_300' else 100,'intensity_sha256':'0'*64} for n in ['100_300','300_400','400_500']}}
                rows.append(q)
    levels={};contrasts={};at=lambda gain,l,z,m:next(r for r in rows if (r['gain'],r['delay'],r['realization'])==(gain,l,z))['metrics'][m]
    for metric in g.METRICS:
        levels[metric]={f'g{gain}-L{l}':oracle([at(gain,l,z,metric) for z in range(3)]) for gain in [.2,.3] for l in [2,3]}
        # Independent cell arithmetic, with a separate expression for interaction.
        effects={f'G_L{l}':[at(.2,l,z,metric)-at(.3,l,z,metric) for z in range(3)] for l in [2,3]}
        effects.update({f'D_g{gain}':[at(gain,3,z,metric)-at(gain,2,z,metric) for z in range(3)] for gain in [.2,.3]})
        effects['I']=[at(.2,3,z,metric)+at(.3,2,z,metric)-at(.2,2,z,metric)-at(.3,3,z,metric) for z in range(3)]
        contrasts[metric]={k:oracle(v) for k,v in effects.items()}
    return {'schema':'ao-explorer.gain42-data.v1','settings':deepcopy(g.SETTINGS),'windows':deepcopy(g.WINDOWS),'records':rows,'levels':levels,'contrasts':contrasts}


def test_independent_synthetic_contrasts():
    d=fixture();assert g.validate_display(d)['paired_contrasts']==15
    _,c=g.contrasts(d['records']);q=c['mean_pre_update_rms_nm']['I']
    assert q['by_realization']==[-5.,-6.,-7.]
    assert q['mean']==-6 and q['sample_sd']==1
    assert q['ci95']==pytest.approx([-8.48413771171955,-3.51586228828045])


@pytest.mark.parametrize('defect',[
    'gain','delay','realization','attempt','missing','duplicate','pairing','digest','nan','infinity','null','string','bool',
    'wrong_gain_sign','wrong_delay_sign','wrong_interaction','combined_interval','missing_interval','missing_baseline_zero','fake_baseline_images','window_bool','count_bool','settings_bool','trace_length','late_summary'])
def test_rejects_malformed_display(defect):
    d=fixture();r=d['records'][0]
    if defect=='gain':r['gain']=.4
    elif defect=='delay':r['delay']=1
    elif defect=='realization':r['realization']=True
    elif defect=='attempt':next(r for r in d['records'] if r['attempt']==2)['attempt']=1
    elif defect=='missing':d['records'].pop()
    elif defect=='duplicate':d['records'][1]=deepcopy(r)
    elif defect=='pairing':r['pairing']['map_chain']='different'
    elif defect=='digest':r['image_provenance']['analysis_sha256']='0'*64
    elif defect in ['nan','infinity','null','string','bool']:r['metrics']['peak_strehl']={'nan':math.nan,'infinity':math.inf,'null':None,'string':'0.7','bool':True}[defect]
    elif defect=='wrong_gain_sign':d['contrasts']['peak_strehl']['G_L2']['mean']*=-1
    elif defect=='wrong_delay_sign':d['contrasts']['peak_strehl']['D_g0.2']['by_realization'][0]*=-1
    elif defect=='wrong_interaction':d['contrasts']['mean_pre_update_rms_nm']['I']['by_realization'][0]=5
    elif defect=='combined_interval':d['contrasts']['mean_pre_update_rms_nm']['I']['ci95']=[-100,100]
    elif defect=='missing_interval':d['contrasts']['mean_pre_update_rms_nm']['I']['ci95']=[]
    elif defect in ['missing_baseline_zero','fake_baseline_images']:
        b=next(r for r in d['records'] if r['gain']==.3);b['windowed_images']['values']=0 if defect=='missing_baseline_zero' else {};b['windowed_images']['status']='available'
    elif defect=='window_bool':r['windowed_images']['values']['100_300']['peak_strehl']=True
    elif defect=='count_bool':r['history_summary']['frames_valid_below_0_995']=False
    elif defect=='settings_bool':d['settings']['root_seed']=True
    elif defect=='trace_length':r['residual_nm'].pop()
    elif defect=='late_summary':r['history_summary']['final50_mean_nm']+=1
    with pytest.raises(g.ExportError):g.validate_display(d)


@pytest.mark.parametrize('defect',['gain','delay','realization','missing','duplicate','run_key','source'])
def test_exact_source_selection(defect):
    rows=[{'gain':r['gain'],'latency_frames':r['delay'],'realization_index':r['realization'],'run_key':r['run_key'],'status':'completed_verified','source':'new (gain 0.2)' if r['gain']==.2 else 'baseline (gain 0.3, reused)'} for r in fixture()['records']]
    g.selection(rows)
    if defect in ['gain','delay','realization']:rows[0][{'gain':'gain','delay':'latency_frames','realization':'realization_index'}[defect]]=True
    elif defect=='missing':rows.pop()
    elif defect=='duplicate':rows[1]=deepcopy(rows[0])
    elif defect=='run_key':rows[0]['run_key']='interrupted-attempt1'
    else:rows[0]['source']='reused'
    with pytest.raises(g.ExportError):g.selection(rows)


def test_input_hash_refusal(tmp_path,monkeypatch):
    f=tmp_path/'tiny.json';f.write_text('{"value":1}')
    index={'files':{'tiny.json':{'sha256':g.sha(f),'bytes':f.stat().st_size}}}
    (tmp_path/'COMPACT_PACKAGE.json').write_text(json.dumps(index));monkeypatch.setattr(g,'INDEX_SHA',g.sha(tmp_path/'COMPACT_PACKAGE.json'))
    p=g.Package(tmp_path);p.path('tiny.json')
    with pytest.raises(g.ExportError):p.path('tiny.json','0'*64)
    with pytest.raises(g.ExportError):p.path('../outside')
    f.write_text('{"value":2}')
    with pytest.raises(g.ExportError):p.path('tiny.json')


def test_accepted_real_bundle():
    p=Path(os.environ['GAIN42_REAL_BUNDLE']);d=g.read(p/'data.json');assert g.validate_bundle(p)['records']==12
    expected={'mean_pre_update_rms_nm':{'G_L2':[24.83,23.04,26.62],'G_L3':[13.29,-10.65,37.22],'I':[-11.55,-36.22,13.13]},'peak_strehl':{'G_L2':[-.0592,-.0647,-.0536],'G_L3':[-.0475,-.0538,-.0412],'I':[.0117,.0097,.0137]},'fourier_ee50_lambda_over_d':{'G_L2':[.561,.521,.601],'G_L3':[.515,.505,.526],'I':[-.045,-.096,.005]}}
    for metric,items in expected.items():
        tol=.0051 if metric.startswith('mean') else .000051 if metric=='peak_strehl' else .00051
        for key,values in items.items():
            # The review labels interaction anchors approximate; retain the
            # exact analysis (Strehl upper bound 0.013647354...), not its prose.
            q=d['contrasts'][metric][key];assert [q['mean'],*q['ci95']]==pytest.approx(values,abs=.0001 if metric=='peak_strehl' and key=='I' else tol)
    for r in d['records']:
        if r['gain']==.3:assert r['windowed_images']['values'] is None
    r03=next(r for r in d['records'] if (r['gain'],r['delay'],r['realization'])==(.3,3,2));r02=next(r for r in d['records'] if (r['gain'],r['delay'],r['realization'])==(.2,3,2))
    assert r03['history_summary']['late_minus_early_nm']==pytest.approx(40.7402,abs=.00005)
    assert r02['history_summary']['late_minus_early_nm']==pytest.approx(3.6643,abs=.00005)
    assert [r03['history_summary']['frames_valid_below_0_995'],r02['history_summary']['frames_valid_below_0_995']]==[137,8]
