"""Publish an already completed DM stroke audit; never execute its analysis."""
from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path
import shutil
import tempfile


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def package(analysis: Path, web: Path) -> dict:
    results = json.loads((analysis / 'results.json').read_text())
    provenance = json.loads((analysis / 'provenance.json').read_text())
    before = json.loads((analysis / 'integrity-before.json').read_text())['files']
    after = json.loads((analysis / 'integrity-after.json').read_text())
    assert before == after['files'] and after['all_inspected_inputs_unchanged']
    assert provenance['analysis_script_sha256'] == sha(analysis / 'analyze.py')
    cases = results['results']
    assert cases['2m']['windows']['analysis_0p2_to_1s']['issued_saturated_frames'] == 174
    assert cases['42m']['windows']['all']['issued_saturated_frames'] == 0
    copied = ['results.json', 'frames-2m.csv', 'frames-42m.csv',
              'stroke-saturation-comparison.png', 'stroke-saturation-comparison.pdf']
    with tempfile.TemporaryDirectory(prefix='dm-stroke-publication-') as temporary:
        out = Path(temporary)
        for name in copied:
            shutil.copyfile(analysis / name, out / name)
        # Keep scientific identities; omit local workstation paths and host details.
        sources = {}
        for name, record in before.items():
            if name.endswith('/attempt-01/history.npz'):
                sources['2m/raw/history.npz'] = record
            elif name.endswith('/attempt-01/case_record.json'):
                sources['2m/raw/case_record.json'] = record
            elif name.startswith('outputs/ao_replay_42m/fixed-42m-500-seed1/'):
                sources['42m/raw/' + Path(name).name] = record
            elif name.startswith(('src/', 'web/ao-explorer/')):
                sources[name] = record
        public = {
            'schema': 'ao-explorer.dm-stroke-publication.v1',
            'scope': 'Packaging completed postprocessing only; no simulation or analysis rerun.',
            'source_recordings': {
                '2m': 'series-2m1000-s624-c7241e4190d5-ef74a541b0e60/cases/baseline',
                '42m': '42m-500-31024b173527b7a6'},
            'source_input_files': sources,
            'original_analysis_source_sha256': provenance['analysis_script_sha256'],
            'original_report_sha256': sha(analysis / 'REPORT.md'),
            'original_provenance_sha256': sha(analysis / 'provenance.json'),
            'copied_artifacts': {name: sha(analysis / name) for name in copied},
            'configuration_hashes': {'2m': provenance['2m_effective_config_hash'],
                                     '42m': provenance['42m_config_hash']},
            'producer_identities': {'2m': provenance['2m_production_identity'],
                                   '42m': provenance['42m_production_core']['package_sha256']},
            'root_seed': provenance['root_seed'], 'realization_index': provenance['realization_index'],
            'analysis_environment': {k: provenance[k] for k in ['python', 'numpy', 'matplotlib', 'native_thread_limits']},
            'checks': results['checks'], 'all_inspected_analysis_inputs_unchanged': True,
            'packager_sha256': sha(Path(__file__)),
        }
        (out / 'publication.json').write_text(json.dumps(public, indent=2) + '\n')
        report = (analysis / 'REPORT.md').read_text().split('## Evidence and execution record')[0]
        report = report.replace('No simulation configuration or website content was changed.',
                                'No simulation configuration was changed. This public copy accompanies the website discussion.')
        report += '''## Evidence and publication

`results.json`, the two CSV histories and the PNG/PDF figure are byte-identical
to the completed local audit. `publication.json` retains the raw-history hashes,
configuration and producer identities, original analysis/report hashes and
checks. Source paths use scientific archive labels without workstation details.
The original analysis verified every inspected input before and after; none
changed. The public statistics preserve the original values and definitions.

Commands are in OPD-equivalent metres. RMS removes piston and retains tilt.
Strehl comes from each recorded propagated PSF at its own science wavelength;
it is not recomputed from the Marechal approximation. Population standard
deviations describe this one record and are not uncertainty estimates.
No CI, calibration, atmosphere, control-loop or optical-propagation run was
performed for this addition. The 42 m stroke surrogate is an intentional
approximation; the causal contribution of stroke to Strehl variability remains
unresolved.
'''
        assert '/Users/' not in report and not re.search(r'(?<![\w.])\.[A-Za-z_][\w.-]*/', report)
        (out / 'README.md').write_text(report)
        types = {'.json': 'application/json', '.csv': 'text/csv', '.md': 'text/markdown',
                 '.png': 'image/png', '.pdf': 'application/pdf'}
        members = {p.name: {'bytes': p.stat().st_size, 'sha256': sha(p), 'media_type': types[p.suffix]}
                   for p in sorted(out.iterdir())}
        identity = hashlib.sha256(json.dumps(members, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
        name = 'dm-stroke-' + identity[:16]
        manifest = {'schema': 'ao-explorer.dm-stroke-manifest.v1', 'id': name, 'files': members}
        (out / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
        target = web / 'derived' / name
        shutil.copytree(out, target)
    entry = {'schema': 'ao-explorer.dm-stroke-entry.v1', 'id': name,
             'manifest': f'../derived/{name}/manifest.json',
             'manifest_bytes': (target / 'manifest.json').stat().st_size,
             'manifest_sha256': sha(target / 'manifest.json')}
    current = web / 'data/current.json'
    document = json.loads(current.read_text())
    document['dmStroke'] = entry
    current.write_text(json.dumps(document, indent=1) + '\n')
    return entry


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--analysis', type=Path, required=True)
    parser.add_argument('--web', type=Path, default=Path('web/ao-explorer'))
    args = parser.parse_args()
    print(json.dumps(package(args.analysis, args.web), indent=2))
