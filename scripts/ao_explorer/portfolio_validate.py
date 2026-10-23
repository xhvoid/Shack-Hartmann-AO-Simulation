"""Independent publication checks for the 42 m portfolio integration.

No simulation, network, CI, or producer/exporter imports. The baseline is the
last pre-integration site commit; raw arrays are read only when --run is given.
"""
import argparse
import hashlib
import json
from html.parser import HTMLParser
from pathlib import Path
import re
import subprocess

import numpy as np
from PIL import Image

BASELINE = '132fbe8c03763d587dd2d6c2e8d077f66024cc0c'


def sha(path):
    h = hashlib.sha256()
    with path.open('rb') as f:
        for chunk in iter(lambda: f.read(8 * 1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()


def read(path):
    return json.loads(path.read_text())


def old(name):
    return subprocess.check_output(['git', 'show', f'{BASELINE}:{name}'])


class Page(HTMLParser):
    def __init__(self):
        super().__init__()
        self.ids, self.refs = [], []

    def handle_starttag(self, tag, attrs):
        d = dict(attrs)
        if 'id' in d:
            self.ids.append(d['id'])
        for key in ('src', 'href'):
            if key in d:
                self.refs.append(d[key])


def check(web, local, run):
    entry = read(web / 'data/current.json')
    previous = json.loads(old('web/ao-explorer/data/current.json'))
    assert {k: v for k, v in entry.items() if k not in ('code_build', 'replay42')} == {k: v for k, v in previous.items() if k != 'code_build'}
    html = (web / 'index.html').read_text()
    before = old('web/ao-explorer/index.html').decode()
    # The complete 2 m section, including all controls and descriptive text.
    section = lambda s: re.search(r'<section id="explore".*?(?=<section id="(?:results|project)")', s, re.S).group().strip()
    assert section(html) == section(before), '2 m section changed'
    page = Page(); page.feed(html)
    assert len(page.ids) == len(set(page.ids)), 'Duplicate HTML IDs'
    for ref in page.refs:
        if ref.startswith('#'):
            assert ref[1:] in page.ids or re.fullmatch(r'result-R[1-8]', ref[1:]), ref
        elif not re.match(r'[a-zA-Z][a-zA-Z0-9+.-]*:', ref):
            assert (web / ref.split('?')[0]).is_file(), ref
    changes = subprocess.check_output(['git', 'diff', '--name-only', BASELINE, '--', str(web / 'data'), str(web / 'derived')], text=True).splitlines()
    assert changes == [str(web / 'data/current.json')], changes
    e = entry['replay42']; mpath = (web / 'data' / e['manifest']).resolve()
    assert mpath.stat().st_size == e['manifest_bytes'] and sha(mpath) == e['manifest_sha256']
    manifest = read(mpath); bundle = mpath.parent
    assert manifest['recording_id'] == e['recording_id']
    digest = hashlib.sha256(json.dumps(manifest['files'], sort_keys=True, separators=(',', ':')).encode()).hexdigest()
    assert e['recording_id'] == '42m-500-' + digest[:16]
    for name, ref in manifest['files'].items():
        p = bundle / name
        assert p.resolve().is_relative_to(bundle)
        assert p.stat().st_size == ref['bytes'] and sha(p) == ref['sha256'], name
        if p.suffix == '.png':
            with Image.open(p) as im:
                im.load()
                assert im.size == ((1792, 256) if name.startswith('frames/') else (256, 256)), name
    provenance = read(bundle / 'evidence/publication.json')
    assert sha(local / 'manifest.json') == provenance['original_local_manifest_sha256']
    for name, ref in provenance['unchanged_assets'].items():
        assert sha(local / name) == sha(bundle / name) == ref['sha256'], name
    data = read(bundle / 'data.json'); plan = read(bundle / 'evidence/plan.json')
    assert data['indices'] == list(range(0, 500, 4)) + [499]
    assert sorted(p.name for p in (bundle / 'frames').glob('*.png')) == sorted([f'{i:04d}.png' for i in data['indices']] + ['mean.png'])
    assert data['config_hash'] == plan['config_hash']
    assert not {'host', 'authorization'} & plan.keys()
    assert 'untracked_files' not in plan['core']['git']
    assert re.fullmatch('[a-f0-9]{40}', plan['core']['git']['git_head'])
    assert '/Users/' not in json.dumps(plan)
    research = read(web / 'data/series-2m180-b3e1c66-e0d60cbaccc6b/research/results.json')
    assert [g['id'] for g in research['groups']] == [f'R{i}' for i in range(1, 9)]
    layers = next(t for t in research['groups'][2]['tables'] if t['id'] == 'r3-profile')['rows']
    for row, layer in zip(layers, plan['config']['atmosphere']['layers'], strict=True):
        assert row['altitude_m'] == layer['altitude_m'] and row['cn2_fraction'] == layer['cn2_fraction']
        assert row['wind_speed_m_per_s'] == np.linalg.norm(layer['wind_m_per_s'])
    m = data['metrics']; window = slice(100, 500)
    np.testing.assert_allclose(m['time_s'], np.arange(500) / 500, rtol=0, atol=1e-12)
    for role in ('uncorrected', 'corrected'):
        np.testing.assert_allclose(np.mean(m['peak_strehl_' + role][window]), data['mean_instantaneous_strehl'][role], rtol=1e-14)
    for role in ('atmosphere', 'residual'):
        np.testing.assert_allclose(np.mean(m[role + '_rms_m'][window]) * 1e9, data['mean_rms_nm'][role], rtol=1e-14)
    report = {'status': 'PASS', 'baseline_commit': BASELINE, 'code_build': entry['code_build'], 'recording_id': e['recording_id'], 'manifest_sha256': sha(mpath), 'verified_members': len(manifest['files']), 'unchanged_local_assets': len(provenance['unchanged_assets']), 'two_m_html_and_data_unchanged': True, 'archived_research_unchanged': True, 'html_ids_and_links': True, 'layer_profile_matches_run': True, 'public_plan_private_fields_omitted': True}
    if run:
        assert m == read(run / 'frames.json')
        original = read(run / 'plan.json')
        assert sha(run / 'plan.json') == plan['original_plan_sha256'] == provenance['original_plan_sha256']
        assert plan['config'] == original['config']
        assert sha(run / 'record.json') == provenance['original_record_sha256']
        with np.load(run / 'history.npz') as h, np.load(run / 'science.npz') as s:
            for public, raw in [('time_s', 'time_s'), ('atmosphere_rms_m', 'open_loop_opd_rms_m'), ('residual_rms_m', 'pre_update_residual_opd_rms_m')]:
                np.testing.assert_array_equal(m[public], h[raw])
            assert np.all(h['reconstruction_usable']) and not np.any(h['saturation_fraction'])
            mask = s['pupil_mask'].astype(bool); peak = s['ideal'].max()
            for role in ('uncorrected', 'corrected'):
                np.testing.assert_allclose(s['mean_' + role].max() / peak, data['mean_peak_strehl'][role], rtol=1e-14)
            for public, filename in [('atmosphere', 'atmosphere_opd_m.npy'), ('residual', 'pre_update_residual_opd_m.npy')]:
                a = np.load(run / filename, mmap_mode='r')
                for k in (0, 100, 256, 499):
                    np.testing.assert_allclose(np.std(a[k][mask]), m[public + '_rms_m'][k], rtol=1e-13)
            for k in (0, 100, 256, 499):
                with np.load(run / f'samples/{k:04d}.npz') as sample:
                    for role in ('uncorrected', 'corrected'):
                        np.testing.assert_allclose(sample['psf_' + role].max() / peak, m['peak_strehl_' + role][k], rtol=1e-13)
        report['raw_history_and_science_checks'] = 'PASS; all scalar history, both mean PSFs, four independently recomputed map RMS/PSF samples'
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--web', type=Path, default=Path('web/ao-explorer'))
    parser.add_argument('--local', type=Path, default=Path('outputs/ao_replay_42m/local-preview'))
    parser.add_argument('--run', type=Path)
    parser.add_argument('--report', type=Path)
    args = parser.parse_args()
    result = check(args.web, args.local, args.run)
    text = json.dumps(result, indent=2) + '\n'
    if args.report:
        args.report.write_text(text)
    print(text)
