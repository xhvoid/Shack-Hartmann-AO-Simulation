"""Published-bundle and refusal checks of the 42 m corner-spot study. No simulation imports or execution."""
from copy import deepcopy
import importlib.util
import json
import math
from pathlib import Path
import shutil

import numpy as np
import pytest
from PIL import Image

ROOT = Path(__file__).parents[1]
SITE = ROOT / 'site'
SPEC = importlib.util.spec_from_file_location('waffle_export', ROOT / 'tools/export_waffle42.py')
w = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(w)


def published():
    entry = json.loads((SITE / 'data/current.json').read_text())['waffle42']
    directory = (SITE / 'data' / entry['manifest']).resolve().parent
    assert entry['schema'] == w.ENTRY_SCHEMA and directory.name == entry['id']
    return directory


def data():
    return w.read(published() / 'data.json')


def test_published_bundle_validates():
    result = w.validate_bundle(published())
    assert result == {'runs': 8, 'held_out_seeds': 3, 'criteria_met': 20, 'prototypes': 17, 'images': 10}


def test_published_values():
    d = data()
    runs = d['runs']
    expected = {'s1-v1': (10.84, 0.7535, 186.7), 's1-v2': (0.91, 0.7670, 180.7), 's104-v1': (10.15, 0.7525, 187.5), 's104-v2': (0.92, 0.7652, 181.9),
                's105-v1': (12.76, 0.7492, 189.4), 's105-v2': (0.98, 0.7657, 181.3), 's106-v1': (9.42, 0.7525, 187.5), 's106-v2': (0.88, 0.7647, 181.7)}
    for key, (ratio, strehl, residual) in expected.items():
        r = runs[key]
        assert r['corrected']['corner_over_halo'] == pytest.approx(ratio, abs=0.005)
        assert r['corrected']['peak_strehl'] == pytest.approx(strehl, abs=0.00005)
        assert r['history']['mean_residual_rms_nm_window'] == pytest.approx(residual, abs=0.05)
        assert r['history']['unusable_frames'] == 0 and r['history']['max_saturation_fraction'] == 0
    assert d['geometry']['corner_offset_arcsec'] == pytest.approx(0.4538, abs=0.0001)
    assert d['geometry']['corner_offset_px'] == pytest.approx(84.08, abs=0.01)
    assert d['held_out']['all_passed'] is True
    assert all(q['passed'] and all(q['criteria'].values()) for q in d['held_out']['per_seed'].values())
    assert d['held_out']['summary']['corner_over_halo/v2']['mean'] == pytest.approx(0.925, abs=0.0005)
    assert [p['modes'] for p in d['prototypes'] if p['group'] == 'two-step split'] == [68, 96, 130]
    assert d['discarded']['single_mode_projection']['corrected']['corner_over_halo'] == pytest.approx(8.22, abs=0.005)


def test_version1_tile_is_the_overview_image():
    with Image.open(published() / 'mean-corrected-v1.png') as mine, Image.open(SITE / 'images/42m-mean-corrected.png') as shown:
        assert mine.size == shown.size == (256, 256)
        assert np.array_equal(np.asarray(mine.convert('RGB')), np.asarray(shown.convert('RGB')))


def test_the_downloaded_exporter_finds_its_notes(tmp_path):
    bundle = published()
    spec = importlib.util.spec_from_file_location('waffle_download', bundle / 'exporter.py')
    downloaded = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(downloaded)
    assert downloaded.notes_file() == (bundle / 'README.md').resolve()
    assert w.notes_file() == (ROOT / 'tools/waffle42_notes/README.md').resolve()
    assert (bundle / 'README.md').read_bytes() == (ROOT / 'tools/waffle42_notes/README.md').read_bytes()
    assert (bundle / 'exporter.py').read_bytes() == (ROOT / 'tools/export_waffle42.py').read_bytes()
    lonely = tmp_path / 'exporter.py'
    shutil.copyfile(bundle / 'exporter.py', lonely)
    with pytest.raises(w.ExportError, match='notes not found'):
        w.notes_file(lonely)


def test_windows_on_a_synthetic_image():
    # A flat floor with extra flux in the centre pixel of each corner window.
    step = w.SETTINGS['science_wavelength_m'] / (2 * w.SETTINGS['actuator_pitch_m']) / 84.08341608739086
    img = np.full((2016, 2016), 1e-7)
    for sy, sx in w.CORNERS.values():
        img[1008 + sy * 84, 1008 + sx * 84] += 169e-7
    m = w.image_metrics(img, 1.0, 1008, 1008, step)
    assert m['corner_over_halo'] == pytest.approx(2.0, rel=1e-12)
    assert m['edge_over_halo'] == pytest.approx(1.0, rel=1e-12)
    assert m['halo_reference_integrated_mean'] == pytest.approx(169e-7, rel=1e-12)
    assert len(m['halo_windows']) == 8 == len(w.HALO_ANGLES_DEG)


def run(ratio, strehl, edge, unusable=0, saturation=0.0):
    return {'corrected': {'corner_over_halo': ratio, 'peak_strehl': strehl, 'edge_over_halo': edge},
            'history': {'unusable_frames': unusable, 'max_saturation_fraction': saturation}}


def test_criteria_boundaries():
    assert all(w.criteria(run(10, .75, 2), run(.9, .76, 2.1)).values())
    assert not w.criteria(run(3.0, .75, 2), run(.9, .76, 2))[w.CRITERIA_KEYS[0]]
    assert w.criteria(run(10, .75, 2), run(1.5, .76, 2))[w.CRITERIA_KEYS[1]]
    assert not w.criteria(run(10, .75, 2), run(1.51, .76, 2))[w.CRITERIA_KEYS[1]]
    assert w.criteria(run(10, .75, 2), run(.9, .746, 2))[w.CRITERIA_KEYS[2]]
    assert not w.criteria(run(10, .75, 2), run(.9, .744, 2))[w.CRITERIA_KEYS[2]]
    assert w.criteria(run(10, .75, 2), run(.9, .76, 2.19))[w.CRITERIA_KEYS[3]]
    assert not w.criteria(run(10, .75, 2), run(.9, .76, 2.21))[w.CRITERIA_KEYS[3]]
    assert not w.criteria(run(10, .75, 2, unusable=1), run(.9, .76, 2))[w.CRITERIA_KEYS[4]]
    assert not w.criteria(run(10, .75, 2), run(.9, .76, 2, saturation=1e-4))[w.CRITERIA_KEYS[4]]


@pytest.mark.parametrize('defect', ['ratio', 'criterion', 'passed', 'summary', 'missing_run', 'seed_bool', 'settings_bool', 'nan',
                                    'residual_trace', 'dropped_rows', 'halo', 'profile', 'prototype_order', 'image_list', 'discarded'])
def test_rejects_altered_display(defect):
    d = data()
    runs = d['runs']
    if defect == 'ratio':
        runs['s1-v2']['corrected']['corner_over_halo'] = 0.5
    elif defect == 'criterion':
        d['held_out']['per_seed']['104']['criteria'][w.CRITERIA_KEYS[0]] = False
    elif defect == 'passed':
        d['held_out']['per_seed']['105']['passed'] = False
    elif defect == 'summary':
        d['held_out']['summary']['corner_over_halo/v2']['mean'] += 0.01
    elif defect == 'missing_run':
        del runs['s106-v2']
    elif defect == 'seed_bool':
        runs['s1-v1']['seed'] = True
    elif defect == 'settings_bool':
        d['settings']['include_noise'] = 1
    elif defect == 'nan':
        runs['s1-v1']['corrected']['peak_strehl'] = math.nan
    elif defect == 'residual_trace':
        runs['s1-v1']['residual_nm'][150] += 10
    elif defect == 'dropped_rows':
        runs['s1-v2']['dropped_rows'][200] = -1
    elif defect == 'halo':
        runs['s1-v1']['corrected']['halo_windows'].pop()
    elif defect == 'profile':
        runs['s1-v2']['profile'] = w.PROFILE + '@1'
    elif defect == 'prototype_order':
        d['prototypes'].reverse()
    elif defect == 'image_list':
        del d['images']['corner-s1-v1.png']
    else:
        del d['discarded']['single_mode_projection']
    with pytest.raises((w.ExportError, KeyError)):
        w.validate_display(d)


@pytest.mark.parametrize('defect', ['image_byte', 'stray_file', 'manifest_id'])
def test_rejects_altered_bundle(tmp_path, defect):
    copy = tmp_path / 'bundle'
    shutil.copytree(published(), copy)
    if defect == 'image_byte':
        raw = bytearray((copy / 'corner-s1-v2.png').read_bytes())
        raw[-20] ^= 1
        (copy / 'corner-s1-v2.png').write_bytes(bytes(raw))
    elif defect == 'stray_file':
        (copy / 'extra.json').write_text('{}')
    else:
        manifest = w.read(copy / 'manifest.json')
        manifest['id'] = 'waffle42-' + '0' * 16
        w.write(copy / 'manifest.json', manifest)
    with pytest.raises(w.ExportError):
        w.validate_bundle(copy)


def test_input_refusals(tmp_path, monkeypatch):
    f = tmp_path / 'tiny.json'
    f.write_text('{"value":1}')
    monkeypatch.setattr(w, 'INPUTS', {'tiny.json': (f.stat().st_size, w.sha(f))})
    evidence = w.Evidence(tmp_path)
    assert evidence.json('tiny.json') == {'value': 1}
    for name in ('../tiny.json', '/tiny.json', 'other.json'):
        with pytest.raises(w.ExportError):
            evidence.path(name)
    f.write_text('{"value":2}')
    with pytest.raises(w.ExportError):
        evidence.path('tiny.json')
