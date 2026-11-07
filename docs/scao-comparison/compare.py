"""Compare a recorded-length 2 m exposure with the on-axis TIPTOP SCAO estimate."""

from dataclasses import replace
import json
import tempfile
from importlib.metadata import version
from pathlib import Path
import numpy as np
from shwfs_ao.io.configs import load_system_profile
from shwfs_ao.experiments.scao import build_scao_system, run_closed_loop, FrozenFlowScreenOptions

class Exposure:
    requested_fields = frozenset({'pre_update_residual_opd_m'})

    def __init__(self, pupil):
        self.pupil = np.asarray(pupil, dtype=bool)
        self.shape = tuple(3 * size for size in pupil.shape)
        self.image = np.zeros(self.shape)
        # Fit tip and tilt after removing the mean coordinate over the pupil.
        self.frames = 0
        y, x = np.indices(self.pupil.shape)
        xy = np.column_stack([x[self.pupil], y[self.pupil]])
        xy = xy - xy.mean(axis=0)
        self.tilt_basis, _ = np.linalg.qr(xy)
        self.tilt_sum = 0.0

    def observe(self, frame):
        if frame.frame_index < 200:
            return
        opd = frame.pre_update_residual_opd_m[self.pupil]
        self.tilt_sum += np.sum((self.tilt_basis.T @ opd)**2) / opd.size
        phase = np.zeros(self.pupil.shape)
        phase[self.pupil] = opd * (2 * np.pi / 1.65e-6)
        field = np.where(self.pupil, np.exp(1j * phase), 0)
        self.image += abs(np.fft.fft2(field, s=self.shape))**2
        self.frames += 1

    def strehl(self):
        return self.image.max() / (self.frames * self.pupil.sum()**2)

def time_domain_runs():
    base = load_system_profile('fast_2m_detector', 4)
    cfg = replace(
        base,
        controller=replace(base.controller, n_steps=1000, gain=0.2, leak=0.,
                           latency_frames=2, include_noise=False),
        detector=replace(base.detector, photons_per_subap_frame=100000., read_noise_e=0.),
        dm=replace(base.dm, stroke_limit_opd_m=1.),  # effectively unlimited for this comparison
        wfs=replace(base.wfs, detector_window_px=23),
    )
    assert cfg.lenslets_across == cfg.actuators_across == 5
    rows = []
    for realization in range(3):
        system = build_scao_system(cfg, atmosphere_options=FrozenFlowScreenOptions(screen_grid_size=640))
        exposure = Exposure(system.wfs.geometry.pupil_mask)
        history = run_closed_loop(cfg, system=system, realization_index=realization, observers=[exposure])
        rms = 1e9 * np.sqrt(np.mean(history.pre_update_residual_opd_rms_m[200:]**2))
        assert exposure.frames == 800
        row = {'realization': realization, 'rms_nm': float(rms), 'strehl': float(exposure.strehl())}
        if realization == 0:
            row['tilt_rms_nm'] = float(1e9 * np.sqrt(exposure.tilt_sum / exposure.frames))
        rows.append(row)
    return rows


def analytic_run(directory, field_pixels):
    from tiptop.baseSimulation import baseSimulation

    config = Path(__file__).with_name('matched.ini').read_text()
    config = config.replace('FieldOfView = 192', f'FieldOfView = {field_pixels}')
    (directory / 'model.ini').write_text(config)
    model = baseSimulation(str(directory), 'model', str(directory), 'result', verbose=False)
    model.doOverallSimulation()
    model.computeMetrics()
    return {'field_pixels': field_pixels, 'rms_nm': float(model.HO_res[0]), 'strehl': float(model.sr[0])}


def plot(results):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, axes = plt.subplots(1, 2, figsize=(8, 3.6), layout='constrained')
    native = results['time_domain']
    tip = max(results['tiptop'], key=lambda row: row['field_pixels'])
    for ax, key, title in zip(axes, ['rms_nm', 'strehl'], ['Residual wavefront RMS (nm)', 'Long-exposure peak Strehl']):
        y = [row[key] for row in native]
        ax.scatter([0.94, 1., 1.06], y, color='#126e78', s=52, label='Individual exposures')
        ax.scatter([2], [tip[key]], color='#bd5528', marker='D', s=57)
        ax.set(xlim=(0.55, 2.45), ylim=(0, 1 if key == 'strehl' else max(y + [tip[key]]) * 1.18),
               xticks=[1, 2], xticklabels=['Time domain', 'TIPTOP'], title=title)
        ax.spines[['top','right']].set_visible(False)
        ax.grid(axis='y', alpha=0.22)
    fig.suptitle('On-axis 2 m SCAO at 1.65 µm')
    fig.savefig(Path(__file__).with_name('comparison.png'), dpi=180)
    plt.close(fig)


def main():
    with tempfile.TemporaryDirectory() as temporary:
        results = {'time_domain': time_domain_runs(),
                   'tiptop': [analytic_run(Path(temporary), n) for n in (192, 384)],
                   'versions': {pkg: version(pkg) for pkg in ['astro-tiptop','astro-p3','mastsel']}}
    Path(__file__).with_name('results.json').write_text(json.dumps(results, indent=2) + '\n')
    plot(results)


if __name__ == '__main__':
    main()
