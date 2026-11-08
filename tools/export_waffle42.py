"""Export the 42 m corner-spot case study from saved replay records.

Requires NumPy and Pillow. Nothing is simulated and no simulation package is
imported. --evidence-root names the folder of saved 42 m replays
(outputs/ao_replay_42m); each input must match its recorded size and SHA-256.
--web-dir names the site: the rendering is checked against the published mean
images there, and --write adds one immutable bundle and binds it in
data/current.json. --validate-bundle checks an existing bundle without the
scientific inputs.

Recomputed from the saved mean images and histories of eight runs: peak
Strehl of the mean PSF, the corner, edge-midpoint and halo windows, encircled
energy within 2 lambda/D, the residual and atmosphere RMS over frames 100-499,
unusable frames, saturation, dropped slope rows, the five held-out criteria
with their summary, and every image of the bundle. Carried with the hashes of
the files they come from: command projections on the checkerboard and on the
96-mode family (they need the actuator layout and the family basis, which only
the simulation package can rebuild), the superseded single-mode run and the
short prototypes. The values of one deleted run are carried from the written
record and say so.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import math
from pathlib import Path, PurePosixPath
import shutil
import tempfile

import numpy as np
from PIL import Image

SCHEMA = 'ao-explorer.waffle42-data.v1'
MANIFEST_SCHEMA = 'ao-explorer.waffle42-manifest.v1'
PROVENANCE_SCHEMA = 'ao-explorer.waffle42-provenance.v1'
ENTRY_SCHEMA = 'ao-explorer.waffle42-entry.v1'
PROFILE = 'det_ccd_42m_r3band_derived'
ARCSEC = 180 / math.pi * 3600
WINDOW = [100, 500]
HALF_WINDOW_PX = 6
CORNERS = {'++': (1, 1), '+-': (1, -1), '-+': (-1, 1), '--': (-1, -1)}
EDGES = {'+0': (1, 0), '-0': (-1, 0), '0+': (0, 1), '0-': (0, -1)}
HALO_ANGLES_DEG = [a for a in range(15, 360, 30) if a % 90 != 45]
HELD_OUT = [104, 105, 106]
CRITERIA = {'corner_spots_above': 3.0, 'corner_halo_at_most': 1.5, 'strehl_drop_at_most': 0.005, 'edge_relative_within': 0.1}
CRITERIA_KEYS = ['1_v1_corner_over_halo_above_3', '2_v2_corner_over_halo_at_most_1.5', '3_v2_peak_strehl_at_most_0.005_below_v1',
                 '4_v2_edge_over_halo_within_10_percent_of_v1', '5_no_unusable_frame_no_saturation']
TILE = 256
FIELD_HALF_ARCSEC = 0.6
ZOOM_HALF_PX = 20
ZOOM_SCALE = 6
ZOOM_CORNER = '++'
FIELD_SCALE = {'floor_over_ideal_peak': 1e-6, 'decades': 6}
ZOOM_LOG_SCALE = {'floor_over_ideal_peak': 1e-6, 'decades': 3}
NODES = np.array([[5, 9, 19], [29, 24, 67], [112, 40, 100], [219, 90, 61], [250, 193, 91], [255, 247, 217]])
SETTINGS = {
    'telescope_diameter_m': 42.0, 'lenslets_across': 84, 'actuators_across': 85, 'actuator_pitch_m': 0.5,
    'pupil_pixels': 1008, 'wfs_wavelength_m': 7e-07, 'science_wavelength_m': 2.2e-06, 'frames': 500,
    'frame_rate_hz': 500.0, 'analysis_window': WINDOW, 'gain': 0.3, 'leak': 0.0, 'latency_frames': 2,
    'damping_alpha': 0.001, 'reconstructor': 'sparse_lsmr_tikhonov', 'include_noise': True,
    'waffle_filter_cutoff': 0.35, 'band_factor': 1.5, 'local_waffle_threshold': 0.5,
}
RUNS = {'s1-v1': ('fixed-42m-500-seed1', 1, 1), 's1-v2': ('2026-11-07-waffle-family/fixed-42m-500-seed1-v2', 1, 2)}
RUNS.update({f's{s}-v{v}': (f'2026-11-08-held-out-seeds/seed{s}-v{v}', s, v) for s in HELD_OUT for v in (1, 2)})
CONFIG_HASHES = {'s1-v1': '1558ff690c01422d30e86ee97ea5c4756fae237bd90e413e81b3d7798569ddc6',
                 's1-v2': 'fa33f34f22dd9eea2eeb37a390e928b7d37efa961539fefdcf2c3a748ea57450'}
PRODUCER_COMMITS = {'s1-v1': '132fbe8c03763d587dd2d6c2e8d077f66024cc0c', 's1-v2': '21d3621942f62089b272efde0c3a1368ec424dca'}
PRODUCER_COMMITS.update({k: '1b139e5c0db923529ad7a94aeccaaed029d04b27' for k in RUNS if not k.startswith('s1-')})
SOURCE = {
    'repository': 'research repository of the simulation (not published); commits identify the code, not public links',
    'filter_commit': '21d3621942f62089b272efde0c3a1368ec424dca',
    'rerun_record_commit': 'b16e401464493bd5403345a807ca864922ad9365',
    'troubleshooting_record_commit': '765d5385a4c29c6cb24d17fa5ea28164777b068c',
    'held_out_code_commit': '1b139e5c0db923529ad7a94aeccaaed029d04b27',
    'held_out_record_commit': '8f3c6610a1bf72c1c4f6bc4736dea9b73ac121b4',
    'public_code': 'https://github.com/xhvoid/Shack-Hartmann-AO-Simulation (src/shwfs_ao/calibration/sparse.py, response_waffle_modes)',
}
# The first full replay with a penalty row on the uniform checkerboard; its run
# folder was trimmed and deleted, so these values come from the written record.
PENALTY_REPLAY = {'corner_over_halo': 11.7, 'peak_strehl': 0.7455, 'mean_residual_rms_nm_window': 506.0,
                  'final_residual_rms_nm': 646.0, 'checkerboard_projection_rms_um': 0.28,
                  'source': 'troubleshooting record (troubleshooting_record_commit); the run files were deleted'}
PROTOTYPES = {
    'base': ('reference', 'Version 1, no filter'),
    'alpha010': ('control', 'Damping alpha = 0.1, no filter'),
    'pen010': ('control', 'Penalty beta (x00 - x10 - x01 + x11) on every complete cell, beta = 0.1 r (5112 rows)'),
    'c015': ('eigenvector selection', 'Response eigenvectors below 0.15 r whose local-waffle fraction exceeds 0.5, projected out'),
    'c025': ('eigenvector selection', 'Response eigenvectors below 0.25 r whose local-waffle fraction exceeds 0.5, projected out'),
    'pre015': ('eigenvector selection, slopes too', 'As c015, and the family signature also removed from the slopes before the solve'),
    'pre025': ('eigenvector selection, slopes too', 'As c025, and the family signature also removed from the slopes before the solve'),
    'pre040': ('eigenvector selection, slopes too', 'Cutoff 0.40 r, and the family signature also removed from the slopes before the solve'),
    'dmx020': ('one-step split', 'Local-waffle eigenvectors (fraction > 0.5) of the band below 2 x cutoff, kept when their own response is below the cutoff'),
    'dmx025': ('one-step split', 'As dmx020, cutoff 0.25'),
    'dmx030': ('one-step split', 'As dmx020, cutoff 0.30'),
    'dmx035': ('one-step split', 'As dmx020, cutoff 0.35'),
    'gen020': ('generalized split', 'Local waffle against local waffle plus local mean, then response eigenvectors of the waffle part, cutoff 0.20'),
    'gen025': ('generalized split', 'As gen020, cutoff 0.25'),
    'tws030': ('two-step split', 'Split by local waffle, then response eigenvectors of the twin subspace, band below 1.5 x cutoff, cutoff 0.30'),
    'tws035': ('two-step split', 'As tws030, cutoff 0.35 (the committed version 2)'),
    'tws040': ('two-step split', 'As tws030, cutoff 0.40'),
}
QUICK_CHECK = '2026-11-07-waffle-family/prototypes/analysis/quick_check_v2.log'
COMPARISON = '2026-11-07-waffle-family/comparison.json'
HELDOUT = '2026-11-08-held-out-seeds/heldout.json'
PROTOCOL = '2026-11-08-held-out-seeds/PROTOCOL.md'
HERO = {'corrected': 'images/42m-mean-corrected.png', 'uncorrected': 'images/42m-mean-uncorrected.png'}
INPUTS = {
    'fixed-42m-500-seed1/science.npz': (98592012, 'c3a5cc49881741f8232b124d13b5cd3e330d6124d9551e72d359745ab1833540'),
    'fixed-42m-500-seed1/history.npz': (52140394, '961e05c2fc3ad31f65ded3e4db61d6875d8509bb1c3dfc0bf6f89315e42323cf'),
    'fixed-42m-500-seed1/plan.json': (15070, '47a271ee6701a50e70ddd535ef8aac05fbc57f1c160f6f402c49773321078cb8'),
    'fixed-42m-500-seed1/progress.json': (93, '01db28b9850a1b3a4eef0be8f6638c57605add053dd41e3c9aa6cf5d24b56f08'),
    '2026-11-07-waffle-family/fixed-42m-500-seed1-v2/science.npz': (98592012, 'b46b6eb3a79276ae2737ae961fd21442d13b125a2ae8e63992f9db32a7d72100'),
    '2026-11-07-waffle-family/fixed-42m-500-seed1-v2/history.npz': (52140394, 'cf9868242fd6f6a3e5cf4354b7e9f25e53c67fe70c0cf86a2d6d3c0f087bc222'),
    '2026-11-07-waffle-family/fixed-42m-500-seed1-v2/plan.json': (15855, '2b9b9a73ee7ed7d3b8aa372ee8e82be55c617cf31c8314e413553d7a91ad50d5'),
    '2026-11-07-waffle-family/fixed-42m-500-seed1-v2/progress.json': (93, 'e0fc9c2ec2022e8587adce102203665fb22cc5c42df74b6a2286c0193382e849'),
    '2026-11-08-held-out-seeds/seed104-v1/science.npz': (98592012, '8d1c0472b18f961cdc813de57efde4d6fb9ef8fff6f2420f12c192ead57c13f1'),
    '2026-11-08-held-out-seeds/seed104-v1/history.npz': (52140394, '5625a0a90a85a446065d41b0662f700adbb75428d1bf9c8bf95b04f702f247a9'),
    '2026-11-08-held-out-seeds/seed104-v1/plan.json': (15183, '88fdef37fcdae33ea7a0921edc6fbda6d31cd2403ca4b6e70421985d7a506d09'),
    '2026-11-08-held-out-seeds/seed104-v1/progress.json': (93, '9f20f74f27d0478dbeb6a0157b6fa944bd7ce23d1c3afb7664e0dc1432ef814c'),
    '2026-11-08-held-out-seeds/seed104-v2/science.npz': (98592012, '47be094bea3bc6230d53deafed9ad9d0fadc63704640c2f936c91035b51d450e'),
    '2026-11-08-held-out-seeds/seed104-v2/history.npz': (52140394, '232ad188e2c37378779fdb88979bd594a0a11c1b7cef68d29ed6de246e1c83b4'),
    '2026-11-08-held-out-seeds/seed104-v2/plan.json': (15914, '6be1a457fa36a48397162b14183fc58fca1adf9e48745dd6002efef391f276c0'),
    '2026-11-08-held-out-seeds/seed104-v2/progress.json': (93, '154215cbc0f5ce5acc1c5c8417c0af57bdb2e585e67edfc9843d68f0edf4e57d'),
    '2026-11-08-held-out-seeds/seed105-v1/science.npz': (98592012, 'cda0b128dae78ceacbeec283164e8b937a97af16affa066c987c52ac56667ce0'),
    '2026-11-08-held-out-seeds/seed105-v1/history.npz': (52140394, 'a8b5161ef45f3417a9f1cccbf46243a4da847947206c525b8ce34287e6c3a165'),
    '2026-11-08-held-out-seeds/seed105-v1/plan.json': (15183, '140fe820fb054ec43a41eab9d504328901fa55e37a2b33ea72b6e8439c0ccce3'),
    '2026-11-08-held-out-seeds/seed105-v1/progress.json': (93, '80d9455f39b906d78166ecb659a8e33a1a4b67ef680b01cdb4b457188acaa845'),
    '2026-11-08-held-out-seeds/seed105-v2/science.npz': (98592012, '00b5931e1a29caa3edff4510729deaae0fcc0fa2a46beb60c6c18d61ad133173'),
    '2026-11-08-held-out-seeds/seed105-v2/history.npz': (52140394, 'c79e0b1daa7c10431960c94042c2f172a2ae0dbeeb9ea64d9eb08889d42c9037'),
    '2026-11-08-held-out-seeds/seed105-v2/plan.json': (15914, '8174fb0b93f4c024f8bc1cb1aec1b9268bd616ca705c242e2e816f81028e6d71'),
    '2026-11-08-held-out-seeds/seed105-v2/progress.json': (92, '136ed19f893e3cc0befda9f9c57d06d257784518301fd18861d03fb17ad36cf8'),
    '2026-11-08-held-out-seeds/seed106-v1/science.npz': (98592012, '80ffef9acea3451fad33c6383a4c717f6a5577df51d52f6d1f51597ebe4177eb'),
    '2026-11-08-held-out-seeds/seed106-v1/history.npz': (52140394, 'aeae16c75e7c628833eec6cf1ef02aea82423c46a66bb5a1f01e0c5138143a49'),
    '2026-11-08-held-out-seeds/seed106-v1/plan.json': (15183, '16e22111794defeff4ad3e1a08185801d77bf6b0312e6dd67486e61c14cb8ad3'),
    '2026-11-08-held-out-seeds/seed106-v1/progress.json': (92, '51b9043228baf941d53af6ab152277e6d957f1f4ff4a64fa570ccf6b5cbe7749'),
    '2026-11-08-held-out-seeds/seed106-v2/science.npz': (98592012, '4a6a20dace4ef7576431d13eeca9b7e57f81e132f558f478f55ecf1aa40e9c45'),
    '2026-11-08-held-out-seeds/seed106-v2/history.npz': (52140394, 'eee2de3579e3b7c2515439a22802964eaf0b0d6b0256a9f901869f42cc3fa3c7'),
    '2026-11-08-held-out-seeds/seed106-v2/plan.json': (15914, 'd6d8441f8eb26fbb6eb8988e47658e380bfd8cf10045e0a81b8ad5bac8da695e'),
    '2026-11-08-held-out-seeds/seed106-v2/progress.json': (92, 'ce982c1e7f473b1a45703c7114572dfbb9260a34274847296598fba218b83b41'),
    '2026-11-07-waffle-family/comparison.json': (16685, 'fe3db3d524ec98c0a7b8785eacc88370c45b477f7b8505514810b79c9d36bff0'),
    '2026-11-08-held-out-seeds/heldout.json': (52665, 'f71a70adf219fcb02714a834994efac04166cba68beeef0ac98b7010be4c6ec3'),
    '2026-11-08-held-out-seeds/PROTOCOL.md': (4514, '05a51866cb7a67444a025056377e810c362ff62afb7659dd63afd3c29c81c8a6'),
    '2026-11-08-held-out-seeds/check-seed104.json': (1423, 'ec6284ea89ff91458c5e9e37022900b15e27b48568eef45a720abba5a893b72f'),
    '2026-11-08-held-out-seeds/check-seed105.json': (1423, 'b659d1fe79c69b9f92038d71f9729be4144e87901210a918e6f0b5615dc46550'),
    '2026-11-08-held-out-seeds/check-seed106.json': (1419, 'f5b81206b288f51bf6567bb1f88f647ebe51331c9ed681e041bfc612c5e365e6'),
    '2026-11-07-waffle-family/prototypes/results/alpha010.result.json': (818, '0cd2601e003227d020b21c3d6821b5dc1eb858c10339e8da3ef48e05b8264c62'),
    '2026-11-07-waffle-family/prototypes/results/base.result.json': (777, 'b14039b1eb97a0ad184792b07e4c706074edab7ff2b63211dee6a8080036722e'),
    '2026-11-07-waffle-family/prototypes/results/c015.result.json': (2073, '4922134519267bc9a30a5880a3deeb01c491fa95194df0a1588115051aa0d5e0'),
    '2026-11-07-waffle-family/prototypes/results/c025.result.json': (4228, '27292a25999e2d650eb807c454ad48476fe142198f0a498282775dd0976c8369'),
    '2026-11-07-waffle-family/prototypes/results/dmx020.result.json': (1096, '3183e9208480fc420e098cafcc03898ed4a979b2d7c63455679c9207447cdbd7'),
    '2026-11-07-waffle-family/prototypes/results/dmx025.result.json': (1099, 'd14d6013e6e70053e0251ec190db4a58d97dbdaaf4c63af77f36a7ea64b112f9'),
    '2026-11-07-waffle-family/prototypes/results/dmx030.result.json': (1099, '564f32a0048450693e236c4709165393fecf60440fc817098e54b90726e5233f'),
    '2026-11-07-waffle-family/prototypes/results/dmx035.result.json': (1103, '68b8d4fea513143c7be8f10185e3c4bd81a135c2beb6030e1b4346c207be022e'),
    '2026-11-07-waffle-family/prototypes/results/gen020.result.json': (1066, '9d28f61ae3291faa44571c9b4624ae5c7f7892fe53f583ca9269da0fe10b5914'),
    '2026-11-07-waffle-family/prototypes/results/gen025.result.json': (1067, 'd3f533238708e05c9df58065ebab94fb87faef9f8a36efe4ceae13d812d92244'),
    '2026-11-07-waffle-family/prototypes/results/pen010.result.json': (958, 'd2a9fb18d4a0df341fd8de32533abba9c055ba82169d679d4847b88347299007'),
    '2026-11-07-waffle-family/prototypes/results/pre015.result.json': (2087, '79a71ab81336024e6ed63d44b27f902e25f75cf3868a88ea3512e8fce2041d85'),
    '2026-11-07-waffle-family/prototypes/results/pre025.result.json': (4251, 'b86ee022f667dffa6d314e712d6475bba5a32c3d8f312045ef95ec1a8a8de800'),
    '2026-11-07-waffle-family/prototypes/results/pre040.result.json': (6120, '0a8050874185372492c7d71c663de38149e6c4bc61e4466e464af1ed6eab4965'),
    '2026-11-07-waffle-family/prototypes/results/tws030.result.json': (1079, '671fc493e6527758ba6c405903d01c049126e209afecec0ebca7455459e4a98c'),
    '2026-11-07-waffle-family/prototypes/results/tws035.result.json': (1079, '7031adda481047d133a029be0dde17b6e160ac5188f4fcf53f7b9aefacdbf234'),
    '2026-11-07-waffle-family/prototypes/results/tws040.result.json': (1079, '71090c0f47af1d1989f6c7924acbc4dd2caa52403c5338190695ab0bbb5a803f'),
    '2026-11-07-waffle-family/prototypes/analysis/quick_check_v2.log': (753, 'beb691fc5ccd7a6e9d60e7bbec973e7187cbd12d415086478bb8804bdc27e6c6'),
}


class ExportError(ValueError):
    pass


def require(ok, what):
    if not ok:
        raise ExportError(what)


def sha(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as handle:
        for block in iter(lambda: handle.read(1 << 22), b''):
            digest.update(block)
    return digest.hexdigest()


def read(path):
    def reject(s):
        raise ExportError('Nonfinite JSON constant: ' + s)
    return json.loads(Path(path).read_text(), parse_constant=reject)


def write(path, value):
    Path(path).write_text(json.dumps(value, allow_nan=False, separators=(',', ':')) + '\n')


def number(v, what):
    require(type(v) in (int, float) and math.isfinite(v), what + ': required finite number')
    return v


def same(a, b, what, rel=1e-12):
    number(a, what)
    number(b, what)
    require(abs(a - b) <= rel * max(abs(a), abs(b)), what + ': inconsistent value')


class Evidence:
    """Inputs under the evidence root, each checked against its pinned size and SHA-256."""

    def __init__(self, root):
        self.root = Path(root).resolve()
        self.consumed = {}

    def path(self, name):
        p = PurePosixPath(name)
        require(not p.is_absolute() and '..' not in p.parts and p.as_posix() == name, 'Unsafe input path')
        require(name in INPUTS, 'Unlisted input: ' + name)
        f = self.root / name
        require(f.is_file() and not f.is_symlink() and self.root in f.resolve().parents, 'Missing input: ' + name)
        size, digest = INPUTS[name]
        require(f.stat().st_size == size and sha(f) == digest, 'Input digest mismatch: ' + name)
        self.consumed[name] = {'bytes': size, 'sha256': digest}
        return f

    def json(self, name):
        return read(self.path(name))


def corner_offset_px(step):
    return SETTINGS['science_wavelength_m'] / (2 * SETTINGS['actuator_pitch_m']) / step


def field_geometry(arrays):
    x, y = arrays['x_angle_rad'], arrays['y_angle_rad']
    require(x.shape == (2016,) and y.shape == (2016,), 'Unexpected focal grid')
    step = float(np.diff(x)[0])
    require(np.allclose(np.diff(x), step) and np.allclose(np.diff(y), step), 'Nonuniform focal grid')
    return step, int(np.flatnonzero(y == 0)[0]), int(np.flatnonzero(x == 0)[0])


def image_metrics(img, ideal_peak, oy, ox, step):
    """The windows of the saved comparison (replay_42m_compare.analyze), recomputed."""

    corner_px = corner_offset_px(step)

    def window(dy, dx):
        cy, cx = oy + int(round(dy)), ox + int(round(dx))
        w = img[cy - HALF_WINDOW_PX:cy + HALF_WINDOW_PX + 1, cx - HALF_WINDOW_PX:cx + HALF_WINDOW_PX + 1]
        return {'integrated': float(w.sum()), 'peak_over_ideal': float(w.max()) / ideal_peak}

    corners = {n: window(sy * corner_px, sx * corner_px) for n, (sy, sx) in CORNERS.items()}
    edges = {n: window(sy * corner_px, sx * corner_px) for n, (sy, sx) in EDGES.items()}
    radius = corner_px * np.sqrt(2)
    halo = [window(radius * np.sin(np.deg2rad(a)), radius * np.cos(np.deg2rad(a)))['integrated'] for a in HALO_ANGLES_DEG]
    corner_mean = float(np.mean([c['integrated'] for c in corners.values()]))
    edge_mean = float(np.mean([e['integrated'] for e in edges.values()]))
    halo_mean = float(np.mean(halo))
    yy, xx = np.indices(img.shape)
    rr = np.hypot(yy - oy, xx - ox) * step
    disc = 2 * SETTINGS['science_wavelength_m'] / SETTINGS['telescope_diameter_m']
    return {
        'peak_strehl': float(img.max() / ideal_peak), 'total_flux': float(img.sum()),
        'corners': corners, 'corner_integrated_mean': corner_mean,
        'corner_peak_over_ideal_max': max(c['peak_over_ideal'] for c in corners.values()),
        'edge_midpoints': edges, 'edge_midpoint_integrated_mean': edge_mean,
        'halo_windows': halo, 'halo_reference_integrated_mean': halo_mean,
        'corner_over_halo': corner_mean / halo_mean, 'edge_over_halo': edge_mean / halo_mean,
        'encircled_energy_2_lambda_over_d': float(img[rr <= disc].sum()),
    }


def history_metrics(path):
    names = ('time_s', 'pre_update_residual_opd_rms_m', 'open_loop_opd_rms_m', 'saturation_fraction',
             'reconstruction_usable', 'valid_measurement_fraction', 'measurement_row_masks')
    with np.load(path, allow_pickle=False) as h:
        arrays = {k: h[k] for k in names}
    for k, a in arrays.items():
        boolean = k in ('reconstruction_usable', 'measurement_row_masks')
        require(a.shape == ((500, 10224) if k == 'measurement_row_masks' else (500,)), 'Malformed history: ' + k)
        require(a.dtype == (np.bool_ if boolean else np.float64), 'Malformed history type: ' + k)
        require(boolean or np.isfinite(a).all(), 'Nonfinite history: ' + k)
    require(np.allclose(arrays['time_s'], np.arange(500) / 500, rtol=0, atol=1e-12), 'History timing mismatch')
    masks = arrays['measurement_row_masks']
    require(np.allclose(arrays['valid_measurement_fraction'], masks.mean(axis=1), rtol=0, atol=1e-12), 'Row masks and validity disagree')
    first, last = WINDOW
    pre = arrays['pre_update_residual_opd_rms_m']
    dropped = (~masks).sum(axis=1)
    summary = {
        'mean_residual_rms_nm_window': float(np.mean(pre[first:last]) * 1e9),
        'mean_atmosphere_rms_nm_window': float(np.mean(arrays['open_loop_opd_rms_m'][first:last]) * 1e9),
        'max_saturation_fraction': float(arrays['saturation_fraction'].max()),
        'unusable_frames': int(np.sum(~arrays['reconstruction_usable'])),
        'dropped_slope_rows_per_frame_window': float(dropped[first:last].mean()),
        'frames_with_dropped_rows_window': int((dropped[first:last] > 0).sum()),
        'slope_rows': int(masks.shape[1]),
    }
    return summary, {'residual_nm': (pre * 1e9).tolist(), 'dropped_rows': [int(v) for v in dropped]}


def psf_rgb(a, peak, scale):
    """The site's fixed log transfer (replay_42m_export.psf_rgb) over a chosen range of decades."""

    floor, decades = scale['floor_over_ideal_peak'], scale['decades']
    t = np.clip((np.log10(np.maximum(a / peak, floor)) - math.log10(floor)) / decades, 0, 1)
    z = t * 5
    i = np.minimum(z.astype(int), 4)
    f = (z - i)[..., None]
    return np.uint8(NODES[i] * (1 - f) + NODES[i + 1] * f)


def field_tile(img, ideal_peak, oy, ox, step):
    half = int(round(FIELD_HALF_ARCSEC / (step * ARCSEC)))
    cut = img[oy - half:oy + half + 1, ox - half:ox + half + 1]
    tile = Image.fromarray(np.flipud(psf_rgb(cut, ideal_peak, FIELD_SCALE))).resize((TILE, TILE), Image.Resampling.BILINEAR)
    return tile, 2 * half + 1


def corner_zoom(img, ideal_peak, oy, ox, step):
    corner_px = corner_offset_px(step)
    sy, sx = CORNERS[ZOOM_CORNER]
    cy, cx = oy + int(round(sy * corner_px)), ox + int(round(sx * corner_px))
    cut = img[cy - ZOOM_HALF_PX:cy + ZOOM_HALF_PX + 1, cx - ZOOM_HALF_PX:cx + ZOOM_HALF_PX + 1]
    side = (2 * ZOOM_HALF_PX + 1) * ZOOM_SCALE
    return Image.fromarray(np.flipud(psf_rgb(cut, ideal_peak, ZOOM_LOG_SCALE))).resize((side, side), Image.Resampling.NEAREST)


def png_bytes(image):
    buffer = io.BytesIO()
    image.save(buffer, format='PNG')
    return buffer.getvalue()


def same_pixels(image, path):
    with Image.open(path) as published:
        return published.size == image.size and np.array_equal(np.asarray(published.convert('RGB')), np.asarray(image.convert('RGB')))


def compare_saved(mine, saved, what):
    """Recomputed image windows against the saved analysis of the same run."""

    for k in ('peak_strehl', 'corner_integrated_mean', 'corner_peak_over_ideal_max', 'edge_midpoint_integrated_mean',
              'halo_reference_integrated_mean', 'corner_over_halo', 'encircled_energy_2_lambda_over_d'):
        same(mine[k], saved[k], f'{what}/{k}')
    for group, names in (('corners', CORNERS), ('edge_midpoints', EDGES)):
        for n in names:
            for k in ('integrated', 'peak_over_ideal'):
                same(mine[group][n][k], saved[group][n][k], f'{what}/{group}/{n}/{k}')


def criteria(v1, v2):
    """The five pass criteria fixed before the held-out runs."""

    c1, c2 = v1['corrected'], v2['corrected']
    e1, e2 = c1['edge_over_halo'], c2['edge_over_halo']
    return {
        CRITERIA_KEYS[0]: c1['corner_over_halo'] > CRITERIA['corner_spots_above'],
        CRITERIA_KEYS[1]: c2['corner_over_halo'] <= CRITERIA['corner_halo_at_most'],
        CRITERIA_KEYS[2]: c2['peak_strehl'] >= c1['peak_strehl'] - CRITERIA['strehl_drop_at_most'],
        CRITERIA_KEYS[3]: abs(e2 - e1) <= CRITERIA['edge_relative_within'] * e1,
        CRITERIA_KEYS[4]: all(r['history']['unusable_frames'] == 0 and r['history']['max_saturation_fraction'] == 0 for r in (v1, v2)),
    }


SUMMARY = {
    'corner_over_halo': (lambda r: r['corrected']['corner_over_halo'], 'Corner / halo'),
    'peak_strehl': (lambda r: r['corrected']['peak_strehl'], 'Peak Strehl of the mean corrected PSF'),
    'mean_residual_rms_nm_window': (lambda r: r['history']['mean_residual_rms_nm_window'], 'Mean residual RMS, nm (window)'),
    'edge_over_halo': (lambda r: r['corrected']['edge_over_halo'], 'Edge-midpoint / halo'),
    'checkerboard_per_actuator_nm': (lambda r: r['commands']['checkerboard_per_actuator_nm'], 'Waffle amplitude per actuator RMS, nm (window)'),
}


def stats(values):
    a = np.asarray(values, dtype=float)
    return {'mean': float(a.mean()), 'sd': float(a.std(ddof=1)), 'min': float(a.min()), 'max': float(a.max()), 'n': int(a.size)}


def held_out_summary(runs):
    return {f'{name}/v{v}': stats([get(runs[f's{s}-v{v}']) for s in HELD_OUT]) for name, (get, _) in SUMMARY.items() for v in (1, 2)}


def image_names():
    return ['mean-corrected-v1.png', 'mean-corrected-v2.png'] + [f'corner-{key}.png' for key in RUNS]


def check_plan(plan, key, seed, version):
    cfg = plan['config']
    require(plan['profile'] == f'{PROFILE}@{version}' and plan['root_seed'] == seed and type(plan['root_seed']) is int, 'Wrong run identity: ' + key)
    require(plan['n_steps'] == SETTINGS['frames'] and plan['analysis_window'] == WINDOW and plan['frame_rate_hz'] == SETTINGS['frame_rate_hz'], 'Wrong run length: ' + key)
    require(plan['science_wavelength_m'] == SETTINGS['science_wavelength_m'] and plan['averaging'].startswith('equal-weight'), 'Wrong science image: ' + key)
    for k in ('telescope_diameter_m', 'lenslets_across', 'actuators_across', 'pupil_pixels', 'wfs_wavelength_m'):
        require(type(cfg[k]) is type(SETTINGS[k]) and cfg[k] == SETTINGS[k], f'Wrong geometry {k}: {key}')
    require(SETTINGS['telescope_diameter_m'] / SETTINGS['lenslets_across'] == SETTINGS['actuator_pitch_m'], 'Pitch mismatch')
    c, r = cfg['controller'], cfg['reconstructor']
    for k, name in (('gain', 'gain'), ('leak', 'leak'), ('latency_frames', 'latency_frames'), ('include_noise', 'include_noise')):
        require(type(c[k]) is type(SETTINGS[name]) and c[k] == SETTINGS[name], f'Wrong controller {k}: {key}')
    require(c['n_steps'] == 500 and c['frame_rate_hz'] == 500.0 and c['recovery'] is None, 'Wrong controller: ' + key)
    require(r['kind'] == SETTINGS['reconstructor'] and r['alpha'] == SETTINGS['damping_alpha'], 'Wrong reconstructor: ' + key)
    if version == 2:
        require(r.get('waffle_filter_cutoff') == SETTINGS['waffle_filter_cutoff'], 'Wrong filter cutoff: ' + key)
    else:
        # Plans written after the filter commit record the absent field as null.
        require(r.get('waffle_filter_cutoff') is None and 'waffle_filter' not in r, 'Version 1 carries a filter: ' + key)
    git = plan['core']['git']
    require(git['git_head'] == PRODUCER_COMMITS[key] and git['tracked_changes_empty'] is True and git['untracked_files'] == [], 'Wrong or unclean producer: ' + key)
    if key in CONFIG_HASHES:
        require(plan['config_hash'] == CONFIG_HASHES[key], 'Configuration hash mismatch: ' + key)
    require(plan.get('recording', 'full') == ('full' if seed == 1 else 'summary_only'), 'Wrong recording mode: ' + key)


def export(root, web_dir, out):
    ev = Evidence(root)
    comparison = ev.json(COMPARISON)
    heldout = ev.json(HELDOUT)
    ev.path(PROTOCOL)
    require(heldout['held_out_seeds'] == HELD_OUT and heldout['all_passed'] is True, 'Unexpected held-out record')
    require(heldout['criteria_constants'] == {**CRITERIA, 'cutoff': SETTINGS['waffle_filter_cutoff']}, 'Held-out criteria differ')
    entries = {e['seed']: e for e in heldout['entries']}
    require(sorted(entries) == [1] + HELD_OUT and entries[1]['reference'] is True, 'Held-out entries mismatch')
    checks = {s: ev.json(f'2026-11-08-held-out-seeds/check-seed{s}.json') for s in HELD_OUT}
    runs, rendered, geometry = {}, {}, None
    for key, (directory, seed, version) in RUNS.items():
        plan = ev.json(directory + '/plan.json')
        progress = ev.json(directory + '/progress.json')
        require(progress['status'] == 'COMPLETED' and progress['frames'] == 500 == progress['total'], 'Incomplete run: ' + key)
        check_plan(plan, key, seed, version)
        with np.load(ev.path(directory + '/science.npz'), allow_pickle=False) as z:
            arrays = {k: z[k] for k in ('mean_corrected', 'mean_uncorrected', 'ideal', 'x_angle_rad', 'y_angle_rad')}
        for k in ('mean_corrected', 'mean_uncorrected', 'ideal'):
            a = arrays[k]
            require(a.shape == (2016, 2016) and a.dtype == np.float64 and np.isfinite(a).all() and a.min() >= 0, 'Malformed image: ' + k)
            require(abs(float(a.sum()) - 1) < 1e-9, 'Image is not normalized to unit flux: ' + k)
        step, oy, ox = field_geometry(arrays)
        ideal_peak = float(arrays['ideal'].max())
        here = {'step_arcsec': step * ARCSEC, 'corner_offset_px': corner_offset_px(step), 'ideal_peak': ideal_peak, 'origin_px': [oy, ox]}
        if geometry is None:
            geometry = here
        else:
            require(here == geometry, 'Focal geometry differs between runs: ' + key)
        corrected = image_metrics(arrays['mean_corrected'], ideal_peak, oy, ox, step)
        uncorrected = float(arrays['mean_uncorrected'].max() / ideal_peak)
        hist, trace = history_metrics(ev.path(directory + '/history.npz'))
        saved = entries[seed][f'v{version}']
        require(saved['profile'] == plan['profile'] and saved['config_hash'] == plan['config_hash'] and saved['root_seed'] == seed, 'Saved analysis names another run: ' + key)
        same(here['corner_offset_px'], saved['corner_offset_px'], key + '/corner offset')
        same(here['step_arcsec'], saved['step_arcsec'], key + '/step')
        same(ideal_peak, saved['ideal_peak'], key + '/ideal peak')
        compare_saved(corrected, saved['corrected'], key + '/corrected')
        same(uncorrected, saved['uncorrected']['peak_strehl'], key + '/uncorrected Strehl')
        for k in ('mean_residual_rms_nm_window', 'mean_atmosphere_rms_nm_window'):
            same(hist[k], saved[k], f'{key}/{k}')
        require(hist['unusable_frames'] == saved['unusable_frames'] and hist['max_saturation_fraction'] == saved['max_saturation_fraction'], 'Usability mismatch: ' + key)
        waffle, family = saved['waffle'], saved['waffle_family']
        if seed == 1:
            other = comparison['before' if version == 1 else 'after']
            require(other['config_hash'] == plan['config_hash'], 'Comparison names another run: ' + key)
            compare_saved(corrected, other['corrected'], key + '/comparison')
            for k in ('projection_rms_m_window', 'per_actuator_amplitude_rms_m_window', 'fraction_of_command_energy_window'):
                same(other['waffle'][k], waffle[k], f'{key}/waffle/{k}')
            same(other['waffle_family']['projection_rms_m_window'], family['projection_rms_m_window'], key + '/family', rel=1e-9)
        require(type(family['modes']) is int and family['modes'] > 0 and waffle['controllable_actuators'] == 5873, 'Malformed command projections: ' + key)
        runs[key] = {
            'seed': seed, 'version': version, 'role': 'tuning' if seed == 1 else 'held_out', 'profile': plan['profile'],
            'config_hash': plan['config_hash'], 'producer_commit': PRODUCER_COMMITS[key], 'recording': plan.get('recording', 'full'),
            'corrected': corrected, 'uncorrected_peak_strehl': uncorrected, 'history': hist,
            'commands': {
                'checkerboard_projection_rms_um': waffle['projection_rms_m_window'] * 1e6,
                'checkerboard_per_actuator_nm': waffle['per_actuator_amplitude_rms_m_window'] * 1e9,
                'checkerboard_fraction_of_command_energy': waffle['fraction_of_command_energy_window'],
                'family_modes': family['modes'], 'family_projection_rms_um': family['projection_rms_m_window'] * 1e6,
                'source': 'carried from heldout.json; rebuilding the actuator layout and the family needs the simulation package',
            },
            'residual_nm': trace['residual_nm'], 'dropped_rows': trace['dropped_rows'],
        }
        if key == 's1-v1':
            tile, native = field_tile(arrays['mean_corrected'], ideal_peak, oy, ox, step)
            hero, _ = field_tile(arrays['mean_uncorrected'], ideal_peak, oy, ox, step)
            require(same_pixels(tile, Path(web_dir) / HERO['corrected']), 'The version-1 tile differs from the published corrected image')
            require(same_pixels(hero, Path(web_dir) / HERO['uncorrected']), 'The version-1 tile differs from the published uncorrected image')
            rendered['mean-corrected-v1.png'] = (tile, {'run': key, 'kind': 'field', 'native_px': native})
        if key == 's1-v2':
            tile, native = field_tile(arrays['mean_corrected'], ideal_peak, oy, ox, step)
            rendered['mean-corrected-v2.png'] = (tile, {'run': key, 'kind': 'field', 'native_px': native})
        rendered[f'corner-{key}.png'] = (corner_zoom(arrays['mean_corrected'], ideal_peak, oy, ox, step),
                                         {'run': key, 'kind': 'corner', 'native_px': 2 * ZOOM_HALF_PX + 1})
    per_seed = {}
    for seed in [1] + HELD_OUT:
        tests = criteria(runs[f's{seed}-v1'], runs[f's{seed}-v2'])
        require(tests == entries[seed]['criteria'] and entries[seed]['passed'] is all(tests.values()), f'Criteria disagree with the saved report: seed {seed}')
        if seed != 1:
            require(tests == checks[seed]['criteria'] and checks[seed]['passed'] is True and checks[seed]['seed'] == seed, f'Criteria disagree with the seed check: {seed}')
            require(all(checks[seed]['conformance'].values()), f'Seed {seed} departed from the protocol')
        per_seed[str(seed)] = {'reference': seed == 1, 'criteria': tests, 'passed': all(tests.values())}
    summary = held_out_summary(runs)
    for name, (_, label) in SUMMARY.items():
        for v in (1, 2):
            mine, saved = summary[f'{name}/v{v}'], heldout['summary'][f'{label} [v{v}]']
            for k in ('mean', 'sd', 'min', 'max'):
                same(mine[k], saved[k], f'summary {name}/v{v}/{k}', rel=1e-9)
            require(mine['n'] == saved['n'] == 3, 'Summary count mismatch')
    m = comparison['intermediate']
    require(m['config_hash'].startswith('285e1eb8') and m['reconstructor'].get('waffle_filter') == 1.0 and m['root_seed'] == 1, 'Unexpected intermediate run')
    mc = m['corrected']
    superseded = {
        'design': 'Exact projection of the least sensed checkerboard mode after every solve',
        'test': 'full 500-frame replay, seed 1', 'config_hash': m['config_hash'],
        'corrected': {k: mc[k] for k in ('peak_strehl', 'corner_integrated_mean', 'corner_peak_over_ideal_max',
                                         'halo_reference_integrated_mean', 'corner_over_halo', 'edge_midpoint_integrated_mean',
                                         'encircled_energy_2_lambda_over_d')},
        'edge_over_halo': mc['edge_midpoint_integrated_mean'] / mc['halo_reference_integrated_mean'],
        'mean_residual_rms_nm_window': m['mean_residual_rms_nm_window'], 'unusable_frames': m['unusable_frames'],
        'max_saturation_fraction': m['max_saturation_fraction'],
        'commands': {'checkerboard_projection_rms_um': m['waffle']['projection_rms_m_window'] * 1e6,
                     'checkerboard_per_actuator_nm': m['waffle']['per_actuator_amplitude_rms_m_window'] * 1e9,
                     'family_projection_rms_um': m['waffle_family']['projection_rms_m_window'] * 1e6},
        'source': 'carried from comparison.json; the run folder was later deleted',
    }
    text = ev.path(QUICK_CHECK).read_text()
    q = json.loads(text[text.index('\n{') + 1:text.rindex('}') + 1])
    quick = {'design': 'Penalty row on the least sensed checkerboard mode (0.022 r)', 'test': '120-frame closed-loop check, seed 1',
             'max_abs_command_um': q['max_abs_command_m'] * 1e6, 'residual_rms_nm_every_20': q['residual_rms_nm_every_20'],
             'unusable_frames': q['unusable'], 'source': 'carried from quick_check_v2.log'}
    require(len(q['residual_rms_nm_every_20']) == 6 and q['unusable'] == 0, 'Unexpected quick check')
    prototypes = []
    for label, (group, design) in PROTOTYPES.items():
        r = ev.json(f'2026-11-07-waffle-family/prototypes/results/{label}.result.json')
        require(r['label'] == label and r['N'] == 150 and r['burn'] == 50, 'Unexpected prototype: ' + label)
        mm = r['metrics']
        prototypes.append({
            'label': label, 'group': group, 'design': design, 'frames': 150, 'psf_frames': [50, 150],
            'cutoff': r['cutoff'] if type(r['cutoff']) is float else None, 'setting': r['cutoff'] if isinstance(r['cutoff'], str) else None,
            'modes': r.get('modes'), 'corner_over_halo': mm['corner_over_halo'], 'peak_strehl': mm['peak_strehl'],
            'residual_rms_nm_window': mm['residual_rms_nm_window'], 'edge_over_halo': mm['edge_mid_over_halo'],
            'max_abs_command_um': mm['max_abs_command_m'] * 1e6, 'unusable_frames': mm['unusable'],
        })
    images = {}
    for name in image_names():
        image, meta = rendered[name]
        scale = FIELD_SCALE if meta['kind'] == 'field' else ZOOM_LOG_SCALE
        images[name] = {**meta, 'size_px': list(image.size), 'field_arcsec': meta['native_px'] * geometry['step_arcsec'], 'scale': scale,
                        **({'corner': ZOOM_CORNER} if meta['kind'] == 'corner' else {}),
                        'orientation': '+y up, +x right; rows flipped for display'}
    data = {
        'schema': SCHEMA, 'settings': SETTINGS,
        'geometry': {**geometry, 'corner_offset_arcsec': SETTINGS['science_wavelength_m'] / (2 * SETTINGS['actuator_pitch_m']) * ARCSEC,
                     'window_px': 2 * HALF_WINDOW_PX + 1, 'halo_angles_deg': HALO_ANGLES_DEG, 'corners': list(CORNERS), 'edge_midpoints': list(EDGES)},
        'runs': runs,
        'held_out': {'seeds': HELD_OUT, 'criteria_constants': CRITERIA, 'per_seed': per_seed, 'summary': summary,
                     'all_passed': all(per_seed[str(s)]['passed'] for s in HELD_OUT)},
        'discarded': {'checkerboard_penalty_replay': {'design': 'Penalty row on the uniform checkerboard, beta = 10 r', 'test': 'full 500-frame replay, seed 1', **PENALTY_REPLAY},
                      'mode_penalty_check': quick, 'single_mode_projection': superseded},
        'prototypes': prototypes, 'images': images, 'source': SOURCE,
    }
    validation = validate_display(data)
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    write(out / 'data.json', data)
    for name in image_names():
        (out / name).write_bytes(png_bytes(rendered[name][0]))
    with (out / 'frames.csv').open('w', newline='') as f:
        writer = csv.writer(f)
        writer.writerow(['run', 'seed', 'version', 'frame', 'time_s', 'pre_update_residual_rms_nm', 'dropped_slope_rows'])
        for key, r in runs.items():
            for k in range(500):
                writer.writerow([key, r['seed'], r['version'], k, k / 500, r['residual_nm'][k], r['dropped_rows'][k]])
    write(out / 'provenance.json', {
        'schema': PROVENANCE_SCHEMA, 'source': SOURCE, 'inputs': ev.consumed, 'exporter_sha256': sha(__file__),
        'published_images_reproduced': {path: sha(Path(web_dir) / path) for path in HERO.values()},
        'recomputed': ['peak Strehl of the mean corrected and uncorrected PSFs', 'corner, edge-midpoint and halo windows and their ratios',
                       'encircled energy within 2 lambda/D', 'residual and atmosphere RMS over frames 100-499', 'unusable frames, saturation and dropped slope rows',
                       'the five held-out criteria and the held-out mean, sample SD, minimum and maximum', 'every image of the bundle'],
        'carried': ['command projections on the unit checkerboard and on each run\'s 96-mode family', 'the superseded single-mode run (comparison.json)',
                    'the 120-frame mode-penalty check', 'the 150-frame prototypes', 'the checkerboard-penalty replay, from the written record'],
        'limitations': ['Each evaluation covers 0.8 s of one 1 s run. The cutoff was chosen on frames 50-149 of seed 1.',
                        'The held-out seeds share the turbulence profile, guide-star flux, geometry and run length of seed 1.',
                        'Prototype values average frames 50-149 of 150-frame runs and are not comparable with full replays.'],
    })
    shutil.copyfile(__file__, out / 'exporter.py')
    notes = Path(__file__).parent / 'waffle42_notes'
    shutil.copyfile(notes / 'README.md', out / 'README.md')
    media = {'.json': 'application/json', '.md': 'text/markdown', '.csv': 'text/csv', '.py': 'text/plain', '.png': 'image/png'}
    members = {f.name: {'bytes': f.stat().st_size, 'sha256': sha(f), 'media_type': media[f.suffix]} for f in sorted(out.iterdir())}
    identity = 'waffle42-' + hashlib.sha256(json.dumps(members, sort_keys=True, separators=(',', ':')).encode()).hexdigest()[:16]
    write(out / 'manifest.json', {'schema': MANIFEST_SCHEMA, 'id': identity, 'files': members})
    return identity, validation


def validate_display(d):
    require(d['schema'] == SCHEMA, 'Wrong data schema')
    # Equality of dictionaries alone accepts True == 1: compare the serialized forms too.
    require(d['settings'] == SETTINGS and json.dumps(d['settings'], sort_keys=True) == json.dumps(SETTINGS, sort_keys=True), 'Wrong settings')
    runs = d['runs']
    require(type(runs) is dict and set(runs) == set(RUNS), 'Wrong run selection')
    for key, r in runs.items():
        _, seed, version = RUNS[key]
        require(type(r['seed']) is int and r['seed'] == seed and type(r['version']) is int and r['version'] == version, 'Wrong run identity: ' + key)
        require(r['profile'] == f'{PROFILE}@{version}' and type(r['config_hash']) is str and len(r['config_hash']) == 64, 'Wrong profile: ' + key)
        require(r['producer_commit'] == PRODUCER_COMMITS[key], 'Wrong producer: ' + key)
        c = r['corrected']
        require(set(c['corners']) == set(CORNERS) and set(c['edge_midpoints']) == set(EDGES), 'Missing windows: ' + key)
        require(type(c['halo_windows']) is list and len(c['halo_windows']) == len(HALO_ANGLES_DEG), 'Missing halo windows: ' + key)
        for group in ('corners', 'edge_midpoints'):
            for q in c[group].values():
                require(number(q['integrated'], key) > 0 and number(q['peak_over_ideal'], key) > 0, 'Invalid window: ' + key)
        for v in c['halo_windows']:
            require(number(v, key + '/halo') > 0, 'Invalid halo window: ' + key)
        same(c['corner_integrated_mean'], sum(q['integrated'] for q in c['corners'].values()) / 4, key + '/corner mean', rel=1e-9)
        same(c['edge_midpoint_integrated_mean'], sum(q['integrated'] for q in c['edge_midpoints'].values()) / 4, key + '/edge mean', rel=1e-9)
        same(c['halo_reference_integrated_mean'], sum(c['halo_windows']) / len(c['halo_windows']), key + '/halo mean', rel=1e-9)
        same(c['corner_peak_over_ideal_max'], max(q['peak_over_ideal'] for q in c['corners'].values()), key + '/corner peak')
        same(c['corner_over_halo'], c['corner_integrated_mean'] / c['halo_reference_integrated_mean'], key + '/corner ratio')
        same(c['edge_over_halo'], c['edge_midpoint_integrated_mean'] / c['halo_reference_integrated_mean'], key + '/edge ratio')
        require(0 < number(r['uncorrected_peak_strehl'], key) < number(c['peak_strehl'], key) <= 1, 'Invalid Strehl: ' + key)
        require(0 < number(c['encircled_energy_2_lambda_over_d'], key) < 1 and abs(number(c['total_flux'], key) - 1) < 1e-9, 'Invalid flux: ' + key)
        h, trace, dropped = r['history'], r['residual_nm'], r['dropped_rows']
        require(type(trace) is list and len(trace) == 500 and type(dropped) is list and len(dropped) == 500, 'Missing traces: ' + key)
        for v in trace:
            require(number(v, key + '/residual') > 0, 'Invalid residual: ' + key)
        for v in dropped:
            require(type(v) is int and 0 <= v <= h['slope_rows'], 'Invalid dropped-row count: ' + key)
        first, last = WINDOW
        same(h['mean_residual_rms_nm_window'], sum(trace[first:last]) / (last - first), key + '/residual mean', rel=1e-9)
        same(h['dropped_slope_rows_per_frame_window'], sum(dropped[first:last]) / (last - first), key + '/dropped rows', rel=1e-9)
        require(type(h['frames_with_dropped_rows_window']) is int and h['frames_with_dropped_rows_window'] == sum(v > 0 for v in dropped[first:last]), 'Dropped-frame count mismatch: ' + key)
        require(type(h['unusable_frames']) is int and h['unusable_frames'] >= 0 and number(h['max_saturation_fraction'], key) >= 0, 'Invalid usability: ' + key)
        cm = r['commands']
        require(type(cm['family_modes']) is int and cm['family_modes'] > 0, 'Invalid family: ' + key)
        for k in ('checkerboard_projection_rms_um', 'checkerboard_per_actuator_nm', 'checkerboard_fraction_of_command_energy', 'family_projection_rms_um'):
            require(number(cm[k], key + '/' + k) >= 0, 'Invalid projection: ' + key)
    held = d['held_out']
    require(held['seeds'] == HELD_OUT and held['criteria_constants'] == CRITERIA, 'Wrong held-out design')
    require(set(held['per_seed']) == {str(s) for s in [1] + HELD_OUT}, 'Missing held-out seeds')
    for seed in [1] + HELD_OUT:
        q, tests = held['per_seed'][str(seed)], criteria(runs[f's{seed}-v1'], runs[f's{seed}-v2'])
        require(q['criteria'] == tests and q['passed'] is all(tests.values()) and q['reference'] is (seed == 1), f'Criteria mismatch: seed {seed}')
    require(held['all_passed'] is all(held['per_seed'][str(s)]['passed'] for s in HELD_OUT), 'Wrong held-out verdict')
    summary = held_out_summary(runs)
    require(set(held['summary']) == set(summary), 'Missing held-out summary')
    for name, q in summary.items():
        for k in ('mean', 'sd', 'min', 'max'):
            same(held['summary'][name][k], q[k], 'summary ' + name, rel=1e-9)
        require(held['summary'][name]['n'] == 3, 'Wrong summary count')
    gone = d['discarded']
    require(set(gone) == {'checkerboard_penalty_replay', 'mode_penalty_check', 'single_mode_projection'}, 'Missing discarded designs')
    s = gone['single_mode_projection']['corrected']
    same(s['corner_over_halo'], s['corner_integrated_mean'] / s['halo_reference_integrated_mean'], 'single-mode ratio')
    for k in ('corner_over_halo', 'peak_strehl', 'mean_residual_rms_nm_window'):
        number(gone['checkerboard_penalty_replay'][k], 'penalty replay ' + k)
    require(number(gone['mode_penalty_check']['max_abs_command_um'], 'mode penalty') > 0, 'Invalid mode-penalty check')
    protos = d['prototypes']
    require([p['label'] for p in protos] == list(PROTOTYPES), 'Wrong prototype selection')
    for p in protos:
        require(p['frames'] == 150 and p['psf_frames'] == [50, 150], 'Wrong prototype window: ' + p['label'])
        for k in ('corner_over_halo', 'peak_strehl', 'residual_rms_nm_window', 'edge_over_halo', 'max_abs_command_um'):
            require(number(p[k], p['label'] + '/' + k) > 0, 'Invalid prototype value: ' + p['label'])
    require(list(d['images']) == image_names(), 'Wrong image list')
    for name, q in d['images'].items():
        require(q['run'] in RUNS and q['kind'] in ('field', 'corner') and type(q['size_px']) is list and len(q['size_px']) == 2, 'Invalid image record: ' + name)
    return {'runs': len(runs), 'held_out_seeds': len(HELD_OUT), 'criteria_met': sum(sum(q['criteria'].values()) for q in held['per_seed'].values()),
            'prototypes': len(protos), 'images': len(d['images'])}


def validate_bundle(directory):
    directory = Path(directory)
    m = read(directory / 'manifest.json')
    require(m['schema'] == MANIFEST_SCHEMA, 'Wrong bundle schema')
    require(m['id'] == 'waffle42-' + hashlib.sha256(json.dumps(m['files'], sort_keys=True, separators=(',', ':')).encode()).hexdigest()[:16], 'Bundle content identity mismatch')
    require({p.name for p in directory.iterdir()} == set(m['files']) | {'manifest.json'}, 'Unlisted/missing bundle members')
    for n, q in m['files'].items():
        require(PurePosixPath(n).name == n and not (directory / n).is_symlink(), 'Unsafe member')
        require(sha(directory / n) == q['sha256'] and (directory / n).stat().st_size == q['bytes'], 'Member hash mismatch: ' + n)
    d = read(directory / 'data.json')
    result = validate_display(d)
    for name, q in d['images'].items():
        require(name in m['files'] and m['files'][name]['media_type'] == 'image/png', 'Missing image member: ' + name)
        with Image.open(directory / name) as image:
            require(image.format == 'PNG' and image.mode == 'RGB' and list(image.size) == q['size_px'], 'Image does not match its record: ' + name)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--evidence-root', type=Path)
    parser.add_argument('--web-dir', type=Path)
    parser.add_argument('--write', action='store_true')
    parser.add_argument('--validate-bundle', type=Path)
    args = parser.parse_args()
    try:
        if args.validate_bundle:
            result = validate_bundle(args.validate_bundle)
        else:
            require(args.evidence_root is not None and args.web_dir is not None, '--evidence-root and --web-dir required')
            with tempfile.TemporaryDirectory(prefix='waffle42-') as tmp:
                out = Path(tmp) / 'bundle'
                identity, result = export(args.evidence_root, args.web_dir, out)
                validate_bundle(out)
                result['bundle'] = identity
                if args.write:
                    target = args.web_dir / 'derived' / identity
                    if target.exists():
                        require(read(target / 'manifest.json') == read(out / 'manifest.json'), 'Immutable bundle conflict')
                    else:
                        shutil.copytree(out, target)
                    validate_bundle(target)
                    entrypath = args.web_dir / 'data/current.json'
                    entry = read(entrypath)
                    require('waffle42' not in entry or entry['waffle42']['id'] == identity, 'Existing waffle bundle differs; explicit integration required')
                    entry['waffle42'] = {'schema': ENTRY_SCHEMA, 'id': identity, 'manifest': f'../derived/{identity}/manifest.json',
                                         'manifest_bytes': (target / 'manifest.json').stat().st_size, 'manifest_sha256': sha(target / 'manifest.json')}
                    entrypath.write_text(json.dumps(entry, indent=1) + '\n')
        print(json.dumps({'passed': True, 'simulation_run': False, **result}, indent=2))
        return 0
    except (ExportError, KeyError, TypeError, ValueError, OSError) as e:
        print(json.dumps({'passed': False, 'error': f'{type(e).__name__}: {e}'}))
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
