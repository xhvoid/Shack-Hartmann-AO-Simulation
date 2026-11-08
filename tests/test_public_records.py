"""Edited public copies of research records and the links of the research catalogs. No simulation."""
import hashlib
import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[1]
SITE = ROOT / 'site'
SPEC = importlib.util.spec_from_file_location('check_bindings', ROOT / 'tools/check_bindings.py')
cb = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(cb)


def public_records():
    entry = json.loads((SITE / 'data/current.json').read_text())['publicEvidenceCopies']
    directory = (SITE / 'data' / entry['manifest']).resolve().parent
    return directory, json.loads((directory / 'manifest.json').read_text())


def strict(path):
    return cb._strict_json(path.read_bytes(), path.name)


def test_every_public_copy_is_standard_json():
    directory, manifest = public_records()
    for name in manifest['files']:
        if name.endswith('.json'):
            strict(directory / name)


def test_the_noise_law_copy_writes_its_missing_estimates_as_null():
    directory, _ = public_records()
    copy = strict(directory / 'detector-noise-law.public.json')
    block = copy['_public_copy']['non_finite_values']
    assert block['original_constant'] == 'NaN' and block['written_as'] is None and block['count'] == len(block['pointers']) == 48
    for pointer in block['pointers']:
        value = copy
        for key in pointer.lstrip('/').split('/'):
            value = value[int(key)] if isinstance(value, list) else value[key]
        assert value is None


def test_the_public_catalog_links_resolve_and_keep_the_original_identities():
    directory, manifest = public_records()
    catalog_path = directory / 'research-results.public.json'
    catalog = strict(catalog_path)
    report, problems = cb.check_catalog_links(SITE.resolve(), {catalog_path.resolve(): catalog}, cb._Digests())
    assert problems == [] and report[catalog_path.resolve().relative_to(SITE.resolve()).as_posix()] == {'links': 42, 'replaced_by_public_copy': []}
    sources = {s['original_sha256']: s for s in strict(directory / 'sources.json')}
    edited = [item for group in catalog['groups'] for item in group.get('downloads', []) if item['kind'] == 'edited_public_copy']
    assert len(edited) == 2
    for item in edited:
        original = item['original_asset']
        assert original['served'] is False and original['url'] == sources[original['sha256']]['original_url']
        assert item['asset']['href'] in manifest['files'] and item['asset']['sha256'] == manifest['files'][item['asset']['href']]['sha256']
    bound = SITE / catalog['_public_copy']['original_path']
    assert hashlib.sha256(bound.read_bytes()).hexdigest() == catalog['_public_copy']['original_sha256']


def _catalog(site, name, downloads):
    path = site / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({'schema': 'ao-explorer.research-results.v1', 'groups': [{'id': 'R1', 'downloads': downloads}]}))
    return path


def test_the_binding_check_follows_catalog_links(tmp_path):
    site = tmp_path.resolve()
    (site / 'a.json').write_bytes(b'{}')
    good = {'href': 'a.json', 'bytes': 2, 'sha256': hashlib.sha256(b'{}').hexdigest()}
    gone = {'href': 'gone.json', 'bytes': 2, 'sha256': '1' * 64}
    wrong = {'href': 'a.json', 'bytes': 2, 'sha256': '2' * 64}
    first = _catalog(site, 'results.json', [{'asset': good}, {'asset': gone}, {'asset': wrong}, {'asset': {'href': '../outside.json', 'bytes': 1, 'sha256': '3' * 64}}])
    catalogs = cb._catalogs(site, iter([first]))
    report, problems = cb.check_catalog_links(site, catalogs, cb._Digests())
    assert report['results.json']['links'] == 4 and len(problems) == 3
    assert any('gone.json is missing' in p for p in problems) and any('records 2' in p for p in problems) and any('outside the site' in p for p in problems)
    # A target that is not served is accepted only when a catalog declares an edited public copy of it.
    second = _catalog(site, 'copy/results.public.json', [{'kind': 'edited_public_copy', 'asset': {'href': '../a.json', 'bytes': 2, 'sha256': good['sha256']},
                                                          'original_asset': {'sha256': '1' * 64, 'bytes': 2, 'served': False}}])
    report, problems = cb.check_catalog_links(site, cb._catalogs(site, iter([first, second])), cb._Digests())
    assert report['results.json']['replaced_by_public_copy'] == ['/groups/0/downloads/1/asset: gone.json'] and len(problems) == 2


def test_the_binding_check_refuses_a_catalog_that_is_not_standard_json(tmp_path):
    path = tmp_path / 'results.json'
    path.write_text('{"schema": "ao-explorer.research-results.v1", "value": NaN}')
    with pytest.raises(cb.BindingError):
        cb._catalogs(tmp_path.resolve(), iter([path.resolve()]))
