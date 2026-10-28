"""Package the completed aperture comparison; never runs an AO simulation."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import shutil
import tempfile
import numpy as np

from PIL import Image


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def package(analysis: Path, web: Path) -> dict:
    original = json.loads((analysis / 'comparison.json').read_text())
    recorded = json.loads((analysis / 'manifest.json').read_text())['files']
    names = ['comparison_008ms.png', 'comparison_100ms.png', 'comparison_500ms.png',
             'temporal_comparison.png', 'crop_location.png', 'animation_preview.png',
             'matched_wavefronts.npz', 'timeseries.csv', 'README.md']
    for name in names + ['synchronized_comparison.gif', 'comparison.json', 'compare.py']:
        assert sha(analysis / name) == recorded[name]['sha256'], f'Changed analysis artifact: {name}'
    with tempfile.TemporaryDirectory(prefix='aperture-comparison-') as scratch:
        out = Path(scratch)
        for name in names:
            shutil.copyfile(analysis / name, out / name)
        # Public evidence names scientific inputs without exposing workstation paths.
        public = {k:v for k,v in original.items() if k not in ['inputs_sha256', 'raw42_path']}
        public['schema'] = 'ao-explorer.aperture-comparison.v1'
        public['original_analysis_sha256'] = sha(analysis / 'comparison.json')
        public['original_analysis_source_sha256'] = sha(analysis / 'compare.py')
        public['source_recordings'] = {
            '2m': 'series-2m1000-s624-c7241e4190d5-ef74a541b0e60/cases/baseline',
            '42m': '42m-500-31024b173527b7a6'}
        public['source_input_hashes'] = {
            ('2m/raw/atmosphere_opd_m.npy' if name.endswith('/frames/atmosphere_opd_m.npy')
             else name.removeprefix('web/ao-explorer/')): value
            for name, value in original['inputs_sha256'].items()}
        public['publication_note'] = 'Projection of the unchanged local analysis, omitting host paths; source hashes and all numerical results retained.'
        # Further descriptive arithmetic on the same saved scalar histories.
        baseline = json.loads((web/'data/series-2m1000-s624-c7241e4190d5-ef74a541b0e60/cases/baseline/metrics.json').read_text())['per_frame']['atmosphere_rms_nm']['values']
        large = json.loads((web/'recordings/42m-500-31024b173527b7a6/data.json').read_text())['metrics']['atmosphere_rms_m']
        changes = {}
        for label, values, hz in [('2m',baseline,1000),('42m',large,500)]:
            values = np.asarray(values)
            changes[label] = {}
            for ms in (40,100):
                lag = round(ms*hz/1000)
                ratios = np.maximum(values[lag:]/values[:-lag],values[:-lag]/values[lag:])
                k = int(np.argmax(ratios))
                changes[label][str(ms)] = {'max_larger_over_smaller':float(ratios[k]),
                    'start_s':k/hz,'end_s':(k+lag)/hz,'pair_count':len(ratios)}
        public['whole_pupil_rms_changes'] = {'definition':'Maximum of larger RMS / smaller RMS across every time pair at the stated lag in each complete one-second record; descriptive extrema, not typical changes.', 'values':changes}
        public['publication_note'] += ' Additional whole-pupil RMS ratios use the same saved scalar histories and are separate from the unchanged crop analysis.'
        (out / 'comparison.json').write_text(json.dumps(public, indent=2)+'\n')
        configs = {
            '2m': web/'data/series-2m1000-s624-c7241e4190d5-ef74a541b0e60/cases/baseline/config.json',
            '42m': web/'recordings/42m-500-31024b173527b7a6/evidence/plan.json'}
        metrics = {
            '2m': web/'data/series-2m1000-s624-c7241e4190d5-ef74a541b0e60/cases/baseline/metrics.json',
            '42m': web/'recordings/42m-500-31024b173527b7a6/data.json'}
        controls = {'schema':'ao-explorer.aperture-controls.v1',
            'sampling':'400 common times, 0.200 to 0.998 s inclusive, 2 ms spacing',
            'ratio_definition':'Per-frame piston-removed pre-update residual OPD RMS divided by whole-pupil input atmosphere OPD RMS; tilt retained. Population temporal standard deviation.',
            'limitation':'Descriptive combined residual fraction, not isolated controller efficiency or matched transfer functions.',
            'naive_assumption':'Comparable loop response and similar, temporally constant residual/input RMS ratios would pass smaller input RMS fluctuations into smaller residual RMS fluctuations. Comparable residual phase variance and consistent science-image definitions are additionally needed to infer relative Strehl stability.',
            'cases':{}}
        for label in configs:
            config_document = json.loads(configs[label].read_text())
            config = config_document['effective_configuration' if label=='2m' else 'config']
            history = json.loads(metrics[label].read_text())
            if label=='2m':
                history = history['per_frame']
                input_rms = np.asarray(history['atmosphere_rms_nm']['values'][200::2])
                residual_rms = np.asarray(history['residual_rms_nm']['values'][200::2])
            else:
                history = history['metrics']
                input_rms = np.asarray(history['atmosphere_rms_m'][100:])
                residual_rms = np.asarray(history['residual_rms_m'][100:])
            ratio = residual_rms/input_rms
            assert len(ratio)==400 and np.all(np.isfinite(ratio))
            controller = config['controller']
            controls['cases'][label] = {
                'config_path':str(configs[label].relative_to(web)), 'config_sha256':sha(configs[label]),
                'metrics_path':str(metrics[label].relative_to(web)), 'metrics_sha256':sha(metrics[label]),
                'effective_configuration':config,
                'pupil_sample_spacing_m':config['telescope_diameter_m']/(config['pupil_pixels']-1),
                'nominal_lenslet_pitch_m':config['telescope_diameter_m']/config['lenslets_across'],
                'queued_latency_s':controller['latency_frames']/controller['frame_rate_hz'],
                'first_wfs_visible_latency_s':(controller['latency_frames']+1)/controller['frame_rate_hz'],
                'mean_per_frame_residual_input_rms_ratio':float(np.mean(ratio)),
                'temporal_std_of_ratio':float(np.std(ratio)),
                'ratio_min':float(np.min(ratio)), 'ratio_max':float(np.max(ratio)),
                'sample_count':len(ratio)}
        (out/'control_comparison.json').write_text(json.dumps(controls,indent=2)+'\n')
        checks = json.loads((analysis / 'verification.json').read_text())
        checks.pop('workspace_note', None)
        (out / 'verification.json').write_text(json.dumps(checks, indent=2)+'\n')
        # Lossless display conversion only; retain the original GIF identity.
        frames = []
        with Image.open(analysis / 'synchronized_comparison.gif') as source:
            for i in range(source.n_frames):
                source.seek(i)
                frames.append(source.convert('RGB').copy())
        frames[0].save(out / 'synchronized_comparison.webp', save_all=True,
            append_images=frames[1:], duration=160, loop=0, lossless=True, method=6)
        with Image.open(out / 'synchronized_comparison.webp') as converted:
            assert converted.n_frames == len(frames)
            for i, frame in enumerate(frames):
                converted.seek(i)
                assert converted.convert('RGB').tobytes() == frame.tobytes()
        # Reusable source: only input/output path discovery differs from the original.
        source = (analysis / 'compare.py').read_text()
        start = source.index("ROOT = Path('/Users/")
        stop = source.index('read = lambda p:')
        source = source[:start] + '''import argparse
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
''' + source[stop:]
        source = source.replace('str(p.relative_to(ROOT)):digest(p)', 'str(p):digest(p)')
        source = source.replace("font_path='/System/Library/Fonts/Supplemental/Arial.ttf'", "from matplotlib.font_manager import findfont\nfont_path=findfont('DejaVu Sans')")
        assert '/Users/' not in source and '.claude/' not in source
        (out / 'analysis.py').write_text(source)
        notes = (out / 'README.md').read_text().replace('synchronized_comparison.gif', 'synchronized_comparison.webp')
        notes = notes.replace('`compare.py` is the postprocessing source.', '`analysis.py` is a portable adaptation of the postprocessing source, with input paths supplied as arguments; numerical operations are unchanged. The original source hash is retained in `comparison.json`.')
        notes = notes.replace('The raw 2 m archive was found in the existing galaxy-observation worktree, not in the main checkout outputs. Both sources were opened read-only.', 'The original raw archives were opened read-only.')
        notes += '\n## Publication\n\nThe animation is losslessly converted to WebP; all 99 decoded RGB frames were checked against the original GIF. `publication.json` records the source identities. Matched numerical arrays are provided as a download and are not used to run a simulation in the browser.\n'
        notes += '\n## Whole-pupil input RMS changes\n\nAcross the complete one-second scalar histories, the largest larger/smaller RMS ratios over 40 ms are 1.509 (2 m) and 1.009 (42 m); over 100 ms they are 2.147 and 1.021. These are extrema over matched physical lags, not typical changes or a claim of several-fold changes in a few computed frames. They describe whole-pupil input error strength; they do not establish that DM tracking is easier. `comparison.json` records the exact values and time pairs.\n'
        notes += '\n## Control comparison and a naive assumption\n\nIf loop response and the residual/input RMS ratio are comparable, and that ratio stays approximately constant, smaller input RMS fluctuations should produce smaller residual RMS fluctuations. At comparable residual phase variance and consistent science-image definitions this can help Strehl remain near a steady value. This is a conditional explanation, not a premise established by these runs.\n\nThe saved configurations have similar r0 and physical grid/lenslet sampling, but differ in loop rate (1000/500 Hz), gain (0.2/0.3), leak (0.02/0), first WFS-visible delay (3/6 ms), DM influence functions and OPD stroke limits (1/100 micrometres), reconstruction, detector/flux conventions, winds and science wavelength (1.65/2.2 micrometres). Over the same 400 times the mean per-frame residual/input RMS ratios are 0.687/0.119, with temporal standard deviations 0.118/0.0028. These combine multiple error sources and do not isolate controller efficiency. `control_comparison.json` retains the configurations, source hashes, definitions and exact scalar results. No new loop was run.\n'
        (out / 'README.md').write_text(notes)
        publication = {'schema':'ao-explorer.aperture-publication.v1',
            'original_manifest_sha256':sha(analysis / 'manifest.json'),
            'original_animation_sha256':sha(analysis / 'synchronized_comparison.gif'),
            'animation_conversion':'Lossless WebP; all decoded RGB frames equal original GIF frames.',
            'animation_frames':len(frames), 'frame_duration_ms':160,
            'analysis_source_adaptation':'Input/output arguments and portable font lookup only; no numerical algorithm changes.',
            'packager_sha256':sha(Path(__file__))}
        (out / 'publication.json').write_text(json.dumps(publication, indent=2)+'\n')
        types = {'.png':'image/png','.webp':'image/webp','.json':'application/json',
                 '.md':'text/markdown','.csv':'text/csv','.py':'text/x-python','.npz':'application/octet-stream'}
        members = {p.name:{'bytes':p.stat().st_size, 'sha256':sha(p), 'media_type':types[p.suffix]}
                   for p in sorted(out.iterdir())}
        identity = hashlib.sha256(json.dumps(members,sort_keys=True,separators=(',',':')).encode()).hexdigest()
        name = 'aperture-comparison-' + identity[:16]
        target = web / 'derived' / name
        (out / 'manifest.json').write_text(json.dumps({'schema':'ao-explorer.aperture-manifest.v1',
            'id':name,'files':members},indent=2)+'\n')
        shutil.copytree(out,target)
    entry = {'schema':'ao-explorer.aperture-entry.v1','id':name,
        'manifest':f'../derived/{name}/manifest.json',
        'manifest_bytes':(target/'manifest.json').stat().st_size,
        'manifest_sha256':sha(target/'manifest.json')}
    current_path = web / 'data/current.json'
    current = json.loads(current_path.read_text())
    current['apertureComparison'] = entry
    current_path.write_text(json.dumps(current,indent=1)+'\n')
    return {'entry':entry,'bytes':sum(f['bytes'] for f in members.values())}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--analysis', type=Path, required=True)
    parser.add_argument('--web', type=Path, default=Path('web/ao-explorer'))
    args = parser.parse_args()
    print(json.dumps(package(args.analysis,args.web),indent=2))
