"""Package the verified local 42 m replay for the existing static explorer.

Copies scientific/display assets byte-for-byte. Host details and local UI files
are omitted; the public plan is explicitly a projection of the frozen original.
No simulation or deployment is performed.
"""
from pathlib import Path
import argparse
import hashlib
import json
import shutil
import tempfile


def sha(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()


def write(p,value):
    p.parent.mkdir(parents=True,exist_ok=True)
    p.write_text(json.dumps(value,indent=2,ensure_ascii=False)+'\n')


def package(local,run,web):
    old=json.loads((local/'manifest.json').read_text())
    for name,ref in old['files'].items():
        p=local/name
        assert p.stat().st_size==ref['bytes'] and sha(p)==ref['sha256'],name
    with tempfile.TemporaryDirectory(prefix='ao42m-bundle-') as tmp:
        out=Path(tmp)
        names=['data.json','source.png','evidence/source.json','evidence/export-checks.json',
               'evidence/run-summary.json','evidence/binary-template.npz','evidence/binary-mean.npz']
        names += [p.relative_to(local).as_posix() for p in sorted((local/'frames').glob('*.png'))]
        for name in names:
            (out/name).parent.mkdir(parents=True,exist_ok=True)
            shutil.copyfile(local/name,out/name)
        plan=json.loads((run/'plan.json').read_text())
        public={k:v for k,v in plan.items() if k not in ('host','authorization','core')}
        public['core']={k:v for k,v in plan['core'].items() if k!='git'}
        public['core']['git']={k:v for k,v in plan['core']['git'].items() if k!='untracked_files'}
        public['schema']='ao-explorer.42m-public-plan.v1'
        public['original_plan_sha256']=sha(run/'plan.json')
        public['projection']='Scientific configuration, environment versions, execution options and content identities retained; host, authorization text and working-tree inventory omitted. Original plan unchanged in local archive.'
        write(out/'evidence/plan.json',public)
        for p in (run/'producer-source').iterdir():
            dest=out/'evidence/producer-source'/p.name;dest.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(p,dest)
        for name in ('replay_42m_export.py','replay_42m_bundle.py'):
            shutil.copyfile(Path(__file__).parent/name,out/'evidence'/name)
        provenance={'schema':'ao-explorer.42m-publication-provenance.v1',
                    'original_local_manifest_sha256':sha(local/'manifest.json'),
                    'original_plan_sha256':sha(run/'plan.json'),
                    'original_record_sha256':json.loads((local/'evidence/run-summary.json').read_text())['original_record_sha256'],
                    'unchanged_assets':{n:old['files'][n] for n in names},
                    'raw_archive':'500 full-precision OPD map pairs, 126 full-grid PSF pairs, 500-step history and 400-frame intensity means retained locally; not bundled for the browser.',
                    'scope':'One fixed exploratory trajectory; no rerun or changes to its scientific/display arrays during publication.'}
        write(out/'evidence/publication.json',provenance)
        files={p.relative_to(out).as_posix():{'bytes':p.stat().st_size,'sha256':sha(p)} for p in sorted(out.rglob('*')) if p.is_file()}
        digest=hashlib.sha256(json.dumps(files,sort_keys=True,separators=(',',':')).encode()).hexdigest()
        recording='42m-500-'+digest[:16]
        write(out/'manifest.json',{'schema':'ao-explorer.recording42.v1','recording_id':recording,'files':files})
        dest=web/'recordings'/recording
        if dest.exists():
            assert sha(dest/'manifest.json')==sha(out/'manifest.json'),'Existing recording differs'
        else:shutil.copytree(out,dest)
    entry_path=web/'data/current.json';entry=json.loads(entry_path.read_text())
    entry['replay42']={'schema':'ao-explorer.recording42-entry.v1','recording_id':recording,
                       'manifest':f'../recordings/{recording}/manifest.json',
                       'manifest_bytes':(dest/'manifest.json').stat().st_size,'manifest_sha256':sha(dest/'manifest.json')}
    write(entry_path,entry)
    print(json.dumps({'recording':recording,'files':len(files),'bytes':sum(v['bytes'] for v in files.values())}))


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--local',type=Path,default=Path('outputs/ao_replay_42m/local-preview'));p.add_argument('--run',type=Path,default=Path('outputs/ao_replay_42m/fixed-42m-500-seed1'));p.add_argument('--web',type=Path,default=Path('web/ao-explorer'))
    a=p.parse_args();package(a.local,a.run,a.web)
