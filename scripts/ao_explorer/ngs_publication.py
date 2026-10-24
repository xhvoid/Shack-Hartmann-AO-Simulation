"""Package existing 2.2 m NGS evidence for the static site; never run AO."""
from __future__ import annotations
import csv,hashlib,json,mimetypes,shutil,tempfile
from pathlib import Path
import numpy as np

ROOT=Path(__file__).resolve().parents[2]
WEB=ROOT/'web/ao-explorer'
FIRST=ROOT/'outputs/robo_ao2_ngs/20261024-first-trajectory'
REPAIR=ROOT/'outputs/robo_ao2_ngs/20261024-loss-of-lock-repair'
DRAFT=ROOT/'docs/research/robo_ao2_ngs_v1'
def read(p):return json.loads(p.read_text())
def sha(p):
    h=hashlib.sha256()
    with p.open('rb') as f:
        for block in iter(lambda:f.read(8*1024**2),b''):h.update(block)
    return h.hexdigest()
def write(p,d):p.write_text(json.dumps(d,indent=2,allow_nan=False)+'\n')
def main():
    sources={}; original_manifest=read(REPAIR/'manifest.json')
    with tempfile.TemporaryDirectory(prefix='ngs-publish-') as temp:
        out=Path(temp)
        def copy(src,dest,verify=None):
            if verify is not None:
                assert src.stat().st_size==verify['bytes'] and sha(src)==verify['sha256'],src.name
            target=out/dest;target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(src,target)
            sources[dest]={'source_relative_path':str(src.relative_to(ROOT)),'source_sha256':sha(src),'byte_identical':True}
        for name in ['results.json','validation.json','diagnosis.json','comparison.png','comparison.pdf','effective-config-v2.json']:
            copy(REPAIR/name,name,original_manifest['artifacts'][name])
        copy(FIRST/'effective-config.json','effective-config-v1.json')
        copy(FIRST/'baseline-config.json','baseline-2m-config.json')
        for name in ['PARAMETERS.md','candidate-config.json','parameter-ledger.json','sources.json']:
            copy(DRAFT/name,'draft/'+name)
        assert len(read(out/'draft/parameter-ledger.json')['parameters'])==131
        # All scalar timestamps/values come from saved histories; no optical calculations.
        old_rows=list(csv.DictReader((FIRST/'comparison-frames.csv').open()))
        for label,directory in [('original_2m',None),('draft_22m_v1',FIRST/'attempt-04'),('repaired_22m_v2',REPAIR/'trajectory-v2')]:
            target=out/(label+'.csv')
            fields=['frame','time_s','strehl_h','residual_rms_nm','clipped_actuator_fraction','applied_boundary_actuator_fraction','reconstruction_usable']
            with target.open('w',newline='') as f:
                writer=csv.DictWriter(f,fieldnames=fields);writer.writeheader()
                if directory is None:
                    rows=[{k:r[k] for k in fields} for r in old_rows if r['scenario']=='original_2m']
                    assert len(rows)==1000;writer.writerows(rows)
                else:
                    with np.load(directory/'history.npz') as h:
                        metrics=list(csv.DictReader((directory/'frame-metrics.csv').open()))
                        boundary=np.mean(abs(h['applied_command_history_opd_m'])>=3.5e-6*1e9*1e-9,axis=1)
                        assert len(metrics)==1500
                        for k,r in enumerate(metrics):
                            assert float(r['time_s'])==h['time_s'][k]
                            writer.writerow(dict(zip(fields,[k,r['time_s'],r['strehl_h'],h['pre_update_residual_opd_rms_m'][k]*1e9,
                                h['saturation_fraction'][k],boundary[k],bool(h['reconstruction_usable'][k])])))
                    sources[label+'.csv']={'source_history_sha256':sha(directory/'history.npz'),
                        'source_metrics_sha256':sha(directory/'frame-metrics.csv'),'byte_identical':False,
                        'operation':'Select saved scalar columns; boundary occupancy = abs(applied) >= effective component limit.'}
        sources['original_2m.csv']={'source_table_sha256':sha(FIRST/'comparison-frames.csv'),'byte_identical':False,'operation':'Select original_2m rows and existing scalar columns.'}
        changes=read(REPAIR/'repair-plan.json')['differences']
        write(out/'revision-assumptions.json',{'parent_ledger':'draft/parameter-ledger.json','parent_field_count':131,
            'original_draft_preserved':True,'unchanged_fields_retain_original_classifications':True,
            'changes':[dict(d,classification='local_engineering_assumption',hardware_operating_value=False) for d in changes],
            'rcond_rationale':'Bound retained inverse sensitivity relative to the strongest singular mode by 20; full-support minimum ratio 0.0735125 retains all 197 modes.',
            'recovery_rationale':'After 3 consecutive rejected frames, decay the requested command by 5% per further rejection; no fallback or gain schedule. Not activated in this validation.',
            'validation_scope':'One identical 2-second atmosphere realization; no cutoff sweep, long-run or multi-seed robustness claim.'})
        record=read(REPAIR/'trajectory-v2/run-record.json')
        write(out/'publication.json',{'schema':'ao-explorer.ngs-publication.v1','date':'2026-10-24',
            'operation':'Publication of existing results and scalar-table extraction only; no simulation rerun.',
            'original_draft':'draft/PARAMETERS.md is the unchanged preparation checkpoint; its unregistered/not-run wording is historical.',
            'sources':sources,'original_first_trajectory_manifest_sha256':sha(FIRST/'manifest.json'),
            'original_repair_manifest_sha256':sha(REPAIR/'manifest.json'),
            'producer_source_files':original_manifest['runtime_source_files'],
            'profile_hashes':{'v1':read(FIRST/'plan.json')['config_hash'],'v2':record['config_hash']},
            'history_hash_v2':record['history_config_hash'],
            'recovery_statistics':record['recovery_statistics'],
            'archive_scope':'Full raw OPD stacks and command archives remain local; this site publishes scalar histories, checks, figures, configurations and all assumptions.',
            'execution_corrections':'Before completion of v1, an exported negative-SNR diagnostic was bounded at zero without altering quality gates or draws; 745 preceding frames replayed bitwise. After full serialization, a nominal/effective stroke-limit comparison failed by one ULP; saved data were verified offline. These are separate from the physical loss of lock. Exact unavailable v1 run metadata remains unavailable.',
            'exporter_sha256':sha(Path(__file__))})
        (out/'README.md').write_text('''# 2.2 m natural-guide-star model: original draft and repair

This bundle publishes existing results. No AO simulation was run to publish it.
The browser displays saved statistics and images, and checks asset hashes.

`results.json` contains the primary [0.2, 1.0) s comparison with the saved
2 m baseline and the separate [0.2, 2.0) s v1/v2 comparison. H-band Strehl is
the instantaneous, flux-normalized peak of each pre-update residual PSF,
relative to its own ideal pupil/grid. SD is population temporal SD, not an
error bar on the mean. Invalid frames are included. The 2 m baseline ends
at one second and is not paired with the different 2.2 m atmosphere.

The original 2.2 m run rejects reconstruction from frame 736 (0.981333 s).
Weak modes of the changing masked inverse amplify command increments;
more spots fail quality gates, and the usable fraction drops below 75%.
After its delayed queue drains, the zero-leak controller holds a saturated
shape. `diagnosis.json` retains the fixed-state and modal checks.

v2 changes the TSVD cutoff from 0.001 to 0.05 and adds rejection decay.
Its atmosphere and calibration arrays match v1 exactly. All 1500 frames
reconstruct, no actuator clips or remains at its boundary, and the recovery
policy never activates. This supports the preventive cutoff repair on this
realization. It is not a proof of long-term stability or measured Robo-AO-2
hardware performance. All other physical values, including stroke, are unchanged.

New clipping means a requested command exceeds the effective limit;
boundary occupancy also includes commands held exactly at that limit.
Fractions in the CSVs are per actuator, not percentages of frames. Summary
tables count frames where any actuator meets the respective criterion.

The four `draft/` files are byte-identical preparation artifacts. They retain
all 131 field annotations and original assumptions. Statements that the
draft was not registered or run refer to that historical checkpoint;
original relative local-file references in the Markdown are also preserved.
Use `baseline-2m-config.json`, `effective-config-v1.json`, and
`effective-config-v2.json` for the executed configurations.
`revision-assumptions.json` explicitly overlays the two local engineering
choices; no published hardware value is claimed for either.

`publication.json` records original source hashes and the distinction between
byte copies and selected scalar exports. Full raw OPD stacks remain local.
The unchanged PNG/PDF are scientific figures generated during the completed
analysis. `validation.json` records prior checks; it is not evidence that
tests or simulations were repeated during publication.
''')
        files={str(p.relative_to(out)):{'bytes':p.stat().st_size,'sha256':sha(p),
            'media_type':('text/markdown' if p.suffix=='.md' else mimetypes.guess_type(p.name)[0] or 'application/octet-stream')}
            for p in sorted(out.rglob('*')) if p.is_file()}
        digest=hashlib.sha256(json.dumps(files,sort_keys=True,separators=(',',':')).encode()).hexdigest()
        identity='ngs-22m-'+digest[:16]
        write(out/'manifest.json',{'schema':'ao-explorer.ngs-manifest.v1','id':identity,'files':files})
        dest=WEB/'derived'/identity
        if dest.exists():assert sha(dest/'manifest.json')==sha(out/'manifest.json')
        else:shutil.copytree(out,dest)
        current=read(WEB/'data/current.json');current['ngs22']={'schema':'ao-explorer.ngs-entry.v1','id':identity,
            'manifest':'../derived/'+identity+'/manifest.json','manifest_bytes':(dest/'manifest.json').stat().st_size,
            'manifest_sha256':sha(dest/'manifest.json')}
        write(WEB/'data/current.json',current)
        print(json.dumps({'bundle':identity,'members':len(files),'bytes':sum(f['bytes'] for f in files.values()),'simulation_run':False}))
if __name__=='__main__':main()
