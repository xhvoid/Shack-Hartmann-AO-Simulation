# 42 m guide-flux comparison, realization 2, 1000 frames

Two saved closed-loop trajectories of the synthetic 42 m SCAO profile
(det_ccd_42m_r3band_derived@1), identical except for the guide-source flux:
100000 and 1000 detected electrons per fully illuminated subaperture per
frame.  Both run 1000 frames at 500 Hz (2 s) through the same atmospheric
realization (r2, root seed 1), with gain 0.3, leak 0, two queued frames and
production damping 0.001.  This bundle only re-expresses saved values; no
atmosphere, sensor, reconstructor, controller or PSF was run to make it.

Files: data.json (per-frame pre-update residual RMS in nm, valid-measurement
fraction, the shared open-loop RMS, window summaries and recorded image
metrics), frames.csv (the same per-frame values), provenance.json (source
identities, input hashes, definitions and checks) and exporter.py.

Time is t = k / 500 Hz for frame k.  Window means are arithmetic means of the
per-frame RMS values over half-open frame windows: [100,500) 400 frames,
[500,1000) 500 frames and [100,1000) 900 frames.  Frame 500 is an analysis
boundary, not a restart.  Frames 0-499 of each run repeat its original
500-frame run exactly, so the extension is one longer trajectory, not an
additional realization.

What it shows: in this one matched realization, the faint run's residual
grows much more after frame 500 than the bright run's.  The bright window
means are nearly unchanged (186.98 versus 187.12 nm), although its last-50
mean rises by about 5 nm.  What it does not show: the change of flux also
changes the native WFS noise derivation and the calibration/reconstructor
identities, so measurement noise is not isolated; one realization gives no
ensemble or long-term stability statement, and no damping conclusion.

Image metrics exist for frames 100-499 and 100-999 only.  No image was
accumulated over frames 500-999 alone; none is derived by subtraction.
Fourier-reference EE50 is the primary width; production EE50 is secondary and
sampling-sensitive.
