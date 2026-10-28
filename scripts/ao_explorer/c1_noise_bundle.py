"""Publish a small summary of the completed C1 static noise assessment; never rerun it.

C1 is a separate static calculation (stage N15 of the S6 investigation): the stationary detector-noise component of
the reconstructed 42 m wavefront at the production photon budget, for the production damping and one selected
comparator.  It produced no images and no closed-loop trajectory.  This packager copies selected scalars from the
three accepted C1 records, which it verifies by SHA-256, into an immutable ``derived/c1-noise-<id>/`` bundle and binds
it in ``data/current.json`` as ``c1Noise``.  It imports no AO runtime and reads no array.

    python scripts/ao_explorer/c1_noise_bundle.py --decision phase_09_decision.json \
        --selection phase_06_damping_selection.json --comparator phase_07_comparator.json --web web/ao-explorer
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import shutil
import tempfile

# The accepted C1 records (attempt-01).  A different file is refused rather than published.
ACCEPTED = {
    'decision': '0887520e2c224a1713c6907b91f22fffbc87073e389af768bb78c87df76be1b1',
    'selection': 'cf5d5a22cf9123d1f0fde3b9c343be4e4f24916a7301e9d84a00a4176b68a9ef',
    'comparator': '618a40c094ff0d2748287d51b0babbd1207d857fd6e1e453cb575adc049854c6',
}
REPORT_SHA256 = '50da9ddd455aef4880798f284a0c44127d7a58ddd5772966ae8ad14814c93260'
ADAPTER_SHA256 = '1e9082048d58368d59042b9bf77b6e96f4b065a31cadaf145523a9ae5c52afe6'
PRODUCER_COMMIT = '98e10278f957c630cf44942b9d02b7a8c66e2988'
CONFIG_HASH = '1ebaf8f35f977e01e2d65a496cf9d4ea06a5a0bc79362852df97646090db8b4f'


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def summary(decision: dict, selection: dict, comparator: dict) -> dict:
    p, a = decision['primary'], decision['seven_mode_attribution']
    assert decision['C1_STATUS'] == 'QUALIFIED_BELOW_C1_TRIGGER' and comparator['COMPARATOR_STATUS'] == 'QUALIFIED_PASS'
    assert selection['selected_alpha'] == p['comparator']['alpha'] == 0.0025 and p['baseline']['alpha'] == 0.001
    kinds = {}
    for record in comparator['production_records']:
        kinds[record['kind']] = kinds.get(record['kind'], 0) + 1
    assert kinds == {'probe': 25, 'screen': 1, 'noise': 16}
    baseline_gains = selection['table'][0]['gains']
    gains = {row['label']: row['R1'] for row in decision['low_order_cost']}
    damping = lambda key, g: {
        'alpha': p[key]['alpha'], 'variance_nm2': p[key]['variance_nm2'], 'rms_nm': p[key]['rms_nm'],
        'instantaneous_rms_nm': decision['instantaneous'][f'{key}_rms_nm'],
        'one_shot_gains': {k: g[k] for k in ('tip', 'tilt', 'defocus')},
        'seven_mode_within_nm2': a[key]['within_subset_nm2'], 'complement_nm2': a[key]['complement_nm2'],
        'cross_twice_nm2': a[key]['cross_twice_nm2']}
    return {
        'schema': 'ao-explorer.c1-noise-summary.v1',
        'status': decision['C1_STATUS'],
        'meaning': ('Under the frozen static covariance and stationary linear-loop model at 1e5 detected electrons per fully '
                    'illuminated subaperture per frame, the selected admissible comparator does not meet the C1 material-benefit '
                    'trigger. C3 is therefore not triggered by this evaluation. Total closed-loop response and other operating '
                    'conditions remain unmeasured.'),
        'quantity': 'stationary detector-noise component of the reconstructed pupil wavefront (static model prediction, full cross-modal covariance)',
        'not_quantities': ['total closed-loop residual RMS', 'the RMS of a paired difference', "an estimate of a closed-loop comparison's effect size or detectability"],
        'configuration': {'profile': 'det_ccd_42m_r3band_derived@1', 'config_hash': CONFIG_HASH, 'root_seed': 1, 'realization': 0,
                          'detector_sampling': 'k2', 'detected_e_per_full_subaperture_frame': 1e5,
                          'loop_model': {'gain': 0.3, 'latency_frames': 2, 'leak': 0.0, 'modal_noise': 'temporally white'}},
        'dampings': {'baseline': damping('baseline', baseline_gains), 'comparator': damping('comparator', gains)},
        'difference': {'rms_nm': p['absolute_rms_reduction_nm'], 'relative_variance_reduction': p['relative_variance_reduction'],
                       'description': 'baseline minus comparator component RMS prediction'},
        'decision_rule': {'trigger_rms_nm': p['thresholds']['rms_nm'], 'trigger_relative_variance': p['thresholds']['relative'],
                          'guard_rms_nm': p['guard_rms_nm'], 'guard_relative': p['guard_relative'],
                          'rule': 'material benefit requires both triggers, each beyond its guard band'},
        'comparator_selection': {'rule': selection['selection']['rule'], 'admissible': selection['selection']['admissible'],
                                 'selected': selection['selected_alpha'], 'propagated': [p['baseline']['alpha'], p['comparator']['alpha']]},
        'comparator_qualification': {'status': comparator['COMPARATOR_STATUS'],
                                     'criterion_A': {'pass': comparator['prospective_by_criterion']['A']['pass'], 'of': comparator['prospective_by_criterion']['A']['comparisons']},
                                     'criterion_B': {'pass': comparator['prospective_by_criterion']['B']['pass'], 'of': comparator['prospective_by_criterion']['B']['comparisons']},
                                     'original_command_space_failures': comparator['original_full_command']['T1c_full_command']['exceeding'],
                                     'inputs': kinds},
        'numerical_consistency_indicator': {'value': decision['numerical_error_budget']['relative_variance_uncertainty_bound'],
                                            'historical_field': 'relative_variance_uncertainty_bound',
                                            'meaning': 'empirical agreement of independent numerical paths; not a certified error bound and not a statistical interval'},
        'images': 'none: C1 generated no PSFs, no images and no replay frames',
        'not_established': ['closed-loop behaviour under noise', 'other photon budgets, realizations, detector settings or masks',
                            'alpha 0.0015 and 0.002 (admissible, not propagated) and dampings outside the grid',
                            'any statistical interval (one deterministic calculation)', 'hardware performance'],
        'identities': {'decision_record_sha256': ACCEPTED['decision'], 'selection_record_sha256': ACCEPTED['selection'],
                       'comparator_record_sha256': ACCEPTED['comparator'], 'execution_report_sha256': REPORT_SHA256,
                       'adapter_sha256': ADAPTER_SHA256, 'frozen_producer_commit': PRODUCER_COMMIT,
                       'note': 'records are held in the project\'s private evidence archive and identified here by SHA-256'},
    }


README = """# C1 static noise assessment: public summary

`summary.json` holds selected scalars of the completed C1 assessment (stage N15 of the S6 investigation into the
42 m profile's regularization). C1 is a static calculation, separate from the 42 m replay: it predicts the
stationary detector-noise component of the reconstructed pupil wavefront at the production photon budget
(10^5 detected electrons per fully illuminated subaperture per frame) for the production damping (alpha 0.001) and
one selected comparator (alpha 0.0025). It generated no images, PSFs or closed-loop frames.

Result: `QUALIFIED_BELOW_C1_TRIGGER`. Under the frozen static covariance and stationary linear-loop model at that
budget, the selected admissible comparator does not meet the C1 material-benefit trigger (at least 1.0 nm and at
least 10 % variance reduction). The predicted component is 1.1113 nm RMS at alpha 0.001 and 1.1071 nm at alpha
0.0025. The 0.0042 nm difference of these two component predictions is not a change in total closed-loop residual,
not the RMS of a paired difference and not an estimate of what a closed-loop comparison would measure. No
closed-loop damping experiment was triggered; the production damping stays 0.001. Total closed-loop response and
other operating conditions remain unmeasured.

The recorded 2.0e-13 is an empirical numerical consistency indicator, not a certified error bound and not a
statistical interval. Model conditions: the detector covariance at a flat wavefront with fixed camera maps,
inter-lenslet independence, persistent calibration bias excluded; a stationary linear loop (gain 0.3, latency 2,
leak 0) with temporally white modal noise; one configuration, seed 1, realization 0. This is an exploratory
simulation result, not a hardware measurement.

`summary.json` names the source records by SHA-256; they stay in the project's private evidence archive.
"""


def package(decision: Path, selection: Path, comparator: Path, web: Path) -> dict:
    for name, path in (('decision', decision), ('selection', selection), ('comparator', comparator)):
        if sha(path) != ACCEPTED[name]:
            raise SystemExit(f'{name} record {path} is not the accepted C1 record')
    document = summary(json.loads(decision.read_text()), json.loads(selection.read_text()), json.loads(comparator.read_text()))
    with tempfile.TemporaryDirectory(prefix='c1-noise-publication-') as temporary:
        out = Path(temporary)
        (out / 'summary.json').write_text(json.dumps(document, indent=1) + '\n')
        (out / 'README.md').write_text(README)
        text = (out / 'summary.json').read_text() + README
        assert '/home/' not in text and '/Users/' not in text and 'ao-p3-transfer' not in text
        types = {'.json': 'application/json', '.md': 'text/markdown'}
        members = {p.name: {'bytes': p.stat().st_size, 'sha256': sha(p), 'media_type': types[p.suffix]} for p in sorted(out.iterdir())}
        identity = hashlib.sha256(json.dumps(members, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
        name = 'c1-noise-' + identity[:16]
        manifest = {'schema': 'ao-explorer.c1-noise-manifest.v1', 'id': name, 'files': members}
        (out / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
        target = web / 'derived' / name
        if target.exists():
            raise SystemExit(f'{target} exists; bundles are immutable')
        shutil.copytree(out, target)
    entry = {'schema': 'ao-explorer.c1-noise-entry.v1', 'id': name, 'manifest': f'../derived/{name}/manifest.json',
             'manifest_bytes': (target / 'manifest.json').stat().st_size, 'manifest_sha256': sha(target / 'manifest.json')}
    current = web / 'data/current.json'
    value = json.loads(current.read_text())
    value['c1Noise'] = entry
    current.write_text(json.dumps(value, indent=2) + '\n')  # the entry's existing layout
    return entry


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--decision', type=Path, required=True)
    parser.add_argument('--selection', type=Path, required=True)
    parser.add_argument('--comparator', type=Path, required=True)
    parser.add_argument('--web', type=Path, default=Path('web/ao-explorer'))
    args = parser.parse_args()
    print(json.dumps(package(args.decision, args.selection, args.comparator, args.web), indent=2))
