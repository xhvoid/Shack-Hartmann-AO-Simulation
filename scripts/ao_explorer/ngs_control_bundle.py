"""Export recorded NGS control telemetry for the website; never run AO."""
from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path
import shutil
import tempfile

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
WEB = ROOT / 'web/ao-explorer'
FIRST = ROOT / 'outputs/robo_ao2_ngs/20261024-first-trajectory'
REPAIR = ROOT / 'outputs/robo_ao2_ngs/20261024-loss-of-lock-repair'


def read(path):
    return json.loads(path.read_text())


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write(path, data, *, compact=False):
    path.write_text(json.dumps(data, allow_nan=False,
                              indent=None if compact else 2) + '\n')


def main():
    entry = read(WEB/'data/current.json')
    evidence = (WEB/'data'/entry['ngs22']['manifest']).resolve().parent
    inputs, runs = {}, {}
    for label, root, folder in [('v1', FIRST, FIRST/'attempt-04'),
                                ('v2', REPAIR, REPAIR/'trajectory-v2')]:
        manifest = read(root/'manifest.json')['artifacts']
        for name in ['history.npz', 'frame-metrics.csv']:
            path = folder/name
            record = {'bytes': path.stat().st_size, 'sha256': sha(path)}
            assert record == manifest[str(path.relative_to(root))]
            inputs[str(path.relative_to(ROOT))] = record
        h = dict(np.load(folder/'history.npz'))
        rows = list(csv.DictReader((folder/'frame-metrics.csv').open()))
        times = h['time_s']
        assert len(rows) == 1500 and np.allclose(times, np.arange(1500)/750, rtol=0, atol=1e-15)
        assert np.array_equal(times, [float(r['time_s']) for r in rows])
        count = h['measurement_row_masks'].sum(axis=1)
        assert np.allclose(count/374, h['valid_measurement_fraction'], rtol=0, atol=1e-15)
        usable = h['reconstruction_usable']
        assert np.array_equal(usable, count/374 >= .75)
        applied = h['applied_command_history_opd_m']
        requested = h['requested_command_history_opd_m']
        assert applied.shape == requested.shape == (1500, 197)
        # Match the archived component's nm-to-m conversion (one ULP above 3.5e-6).
        limit = 3.5e-6 * 1e9 * 1e-9
        assert np.array_equal(applied, np.clip(requested, -limit, limit))
        clipped = np.mean(abs(requested) > limit, axis=1)
        assert np.array_equal(clipped, h['saturation_fraction'])
        issued_boundary = np.count_nonzero(abs(applied) >= limit, axis=1)
        # loop.py stores applied[k] after update k; exposure k uses applied[k-1].
        held_boundary = np.r_[0, issued_boundary[:-1]]
        archived_delta = h['delta_command_norm_m'] * 1e6
        assert np.all(archived_delta[~usable] == 0)
        values = [float(r['strehl_h']) for r in rows]
        published_name = 'draft_22m_v1.csv' if label == 'v1' else 'repaired_22m_v2.csv'
        published = list(csv.DictReader((evidence/published_name).open()))
        assert np.array_equal(values, [float(r['strehl_h']) for r in published])
        assert np.array_equal(issued_boundary/197,
                              [float(r['applied_boundary_actuator_fraction']) for r in published])
        runs[label] = {
            'valid_rows': count.tolist(), 'usable': usable.tolist(),
            'increment_l2_um': [float(v) if ok else None for v, ok in zip(archived_delta, usable)],
            'held_boundary_actuators': held_boundary.tolist(),
            'issued_clipped_fraction': clipped.tolist(), 'strehl': values,
        }
    assert np.flatnonzero(~np.array(runs['v1']['usable']))[0] == 736
    assert not any(runs['v1']['usable'][736:]) and all(runs['v2']['usable'])
    assert not any(runs['v2']['held_boundary_actuators'])
    assert runs['v1']['valid_rows'][736] == 278
    assert runs['v1']['held_boundary_actuators'][736:739] == [8, 11, 8]
    assert all(v == 8 for v in runs['v1']['held_boundary_actuators'][738:])
    diagnosis = read(evidence/'diagnosis.json')
    peak_record = next(x for x in diagnosis['selected_saved_residual_noiseless_measurements'] if x['frame'] == 732)
    assert abs(runs['v1']['increment_l2_um'][732] - peak_record['original_increment_norm_um']) < 1e-10
    with tempfile.TemporaryDirectory(prefix='ngs-control-') as temp:
        out = Path(temp)
        data = {'schema': 'ao-explorer.ngs-control-data.v1', 'time_s': times.tolist(),
                'frames': 1500, 'frame_rate_hz': 750, 'calibrated_rows': 374,
                'actuators': 197, 'minimum_valid_fraction': .75,
                'loss_frame': 736, 'loss_time_s': float(times[736]),
                'focus_interval_s': [.92, 1.04], 'full_interval_s': [0, 2], 'runs': runs}
        write(out/'data.json', data, compact=True)
        with (out/'frames.csv').open('w', newline='') as f:
            writer = csv.writer(f)
            writer.writerow(['run', 'frame', 'time_s', 'valid_rows_of_374', 'reconstruction_usable',
                             'increment_l2_um_opd', 'held_boundary_actuators_of_197',
                             'issued_clipped_fraction', 'strehl_h'])
            for label, run in runs.items():
                for k, t in enumerate(times):
                    writer.writerow([label, k, t, *[run[key][k] for key in
                        ['valid_rows', 'usable', 'increment_l2_um', 'held_boundary_actuators',
                         'issued_clipped_fraction', 'strehl']]])
        write(out/'provenance.json', {
            'schema': 'ao-explorer.ngs-control-provenance.v1', 'inputs': inputs,
            'original_evidence_entry': entry['ngs22'], 'exporter_sha256': sha(Path(__file__)),
            'source_loop_sha256': sha(REPAIR/'runtime/src/shwfs_ao/control/loop.py'),
            'definitions': {
                'valid_rows': 'Count of true saved effective measurement-row mask entries, out of 374 calibrated rows.',
                'increment_l2_um': 'Saved projected reconstructed command-vector L2 norm before normal controller gain/queue, in micrometres OPD-equivalent. Not pupil RMS or individual actuator stroke. Null on rejected reconstruction; archived zero is a sentinel.',
                'held_boundary_actuators': 'Count of abs(applied[k-1]) >= effective stroke limit. Frame 0 is the recorded flat-DM start. Matches the pre-update exposure/PSF timing.',
                'issued_clipped_fraction': 'Saved fraction of new requests beyond the bound after update k. It can remain nonzero while the queue drains after reconstruction rejection.',
                'strehl': 'Unchanged saved H-band (1.65 um) pre-update instantaneous peak Strehl.',
            },
            'checks': {'input_hashes_match_archives': True, 'saved_time_arrays_checked': True,
                       'valid_row_counts_match_fractions': True, 'clipping_reconstructed_exactly': True,
                       'published_strehl_and_post_update_boundaries_match': True,
                       'first_rejected_frame': 736, 'held_boundary_counts_frames_736_to_738': [8,11,8],
                       'revision_reconstructs_all_1500_frames': True, 'simulation_run': False},
        })
        (out/'README.md').write_text('''# Saved NGS control timeline

Only existing v1/v2 telemetry and scalar PSF metrics are read. No atmosphere,
sensor, reconstructor, controller, PSF propagation or AO runtime is executed.
All 1500 samples per trajectory are retained; 0.920–1.040 s is the default
inspection window and 0–2 s remains available. The marker at 0.981333333 s
is the first rejected reconstruction, not an independent lock classifier.

Rows, reconstructed increment and Strehl belong to frame k. The DM shape
held during that exposure comes from the update at k-1. Boundary occupancy
is shifted accordingly; it is distinct from newly clipped requests after
update k, whose unshifted fraction is also provided in the readout/CSV.
Frame 0 starts with a flat DM. Unlike the original comparison table, which
counts post-update applied states, this timeline aligns held states with PSFs.

A rejected reconstruction has no valid increment estimate. Its archived
zero sentinel is exported as null (empty CSV), shown as a gap, never as a
successful zero-error estimate. The increment is an actuator-vector L2 norm,
not a single actuator stroke and not a wavefront RMS. V1's delayed commands
continue through update 737; exposure 738 starts the persistent eight-actuator
boundary state. V2 has neither rejection nor boundary occupancy in this run.

This is descriptive telemetry from one paired realization. The existing
diagnosis provides selected modal checks; the timeline alone does not isolate
a unique initiating noise event or establish robust hardware performance.
The original bundles, draft and all assumptions are retained unchanged.
''')
        shutil.copy2(__file__, out/'exporter.py')
        files = {p.name: {'bytes': p.stat().st_size, 'sha256': sha(p),
                         'media_type': 'application/json' if p.suffix == '.json' else
                         'text/csv' if p.suffix == '.csv' else 'text/plain'}
                 for p in sorted(out.iterdir())}
        digest = hashlib.sha256(json.dumps(files, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
        identity = 'ngs-control-' + digest[:16]
        write(out/'manifest.json', {'schema': 'ao-explorer.ngs-control-manifest.v1', 'id': identity, 'files': files})
        target = WEB/'derived'/identity
        if target.exists():
            assert sha(target/'manifest.json') == sha(out/'manifest.json')
        else:
            shutil.copytree(out, target)
        entry['ngsControl'] = {'schema': 'ao-explorer.ngs-control-entry.v1', 'id': identity,
                               'manifest': '../derived/'+identity+'/manifest.json',
                               'manifest_bytes': (target/'manifest.json').stat().st_size,
                               'manifest_sha256': sha(target/'manifest.json')}
        write(WEB/'data/current.json', entry)
        print(json.dumps({'id': identity, 'frames_per_run': 1500,
                          'bytes': sum(v['bytes'] for v in files.values()), 'simulation_run': False}))


if __name__ == '__main__':
    main()
