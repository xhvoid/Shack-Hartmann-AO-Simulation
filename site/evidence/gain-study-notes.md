# Integrator gain and controller delay

Reading copy revised 2 November 2026. The original methods in the frozen
study bundle are unchanged. File names below refer to that bundle.

Among the two tested gains, gain 0.3 produced better whole-window image quality
at both configured delays. Lowering gain reduced the observed delay penalty and
the r2 late excursion, but incurred a larger overall image-quality cost.

Six new gain-0.2 trajectories and six reused gain-0.3 records form two
gains × configured controller queue delays 2/3 × realizations r0/r1/r2. The
delay-3/r2 baseline is completed attempt 2; the interrupted first attempt is
retained in the historical latency evidence and excluded here. No baseline was
rerun. The astronomical replay on the site is a separate recorded case.

Each record has 500 frames at 500 Hz. The primary window is [100,500), 400
correlated frames over 0.8 s. Fixed settings: 100000 electrons per full
subaperture per frame, noise on, root seed 1, native scoped noise policy,
leak 0, damping 0.001, wavelength 2.2 µm, PSF padding 2.

The primary metrics are the mean pre-update frame residual RMS (nm), peak
Strehl of the mean PSF (dimensionless), and Fourier-interpolant EE50 radius
(λ/D). The production EE50 estimator remains sampling-sensitive and secondary.
Residual means and validity summaries are recomputed from saved histories.
Image metrics are carried from the saved analysis bound by file hashes. Large PSF and
residual-snapshot arrays are omitted; no image metrics or wavefronts were
independently recalculated for this display.

G(L,r) = M(0.2,L,r) − M(0.3,L,r).
D(g,r) = M(g,3,r) − M(g,2,r).
I(r) = D(0.2,r) − D(0.3,r).

Each exploratory 95% Student t interval uses the three paired realization-level
values, df 2. Interaction uncertainty uses the three interaction values.
Frames are not independent replicates. Negative changes favour lower residual
and EE50; positive changes favour higher Strehl. Only the Strehl interaction
interval excludes zero. An interval containing zero does not establish
equivalence.

At delay 3/r2, late-minus-early residual ([300,500) − [100,300)) is 40.7402 nm
at gain 0.3 and 3.6643 nm at gain 0.2; 137 versus 8 primary-window frames have
valid fraction below 0.995. This is an observed contrast in one realization,
with no demonstrated causal mechanism. It does not reverse the whole-window
image-quality result. Windowed Strehl summaries exist only for the six new
runs; baseline windowed images are unavailable, never zero.

The findings identify neither an optimal gain nor a stability boundary,
hardware latency budget, temporal-error decomposition or on-sky validation.
The earlier command-space failures (T1c/T4) and unresolved outcome I still
stand. The first 42 m static attempt (N13) remained unqualified. The later
attempt (N14) met its prospective pupil-space bounds while retaining the
command-space failure. The detector-noise calculation (C1) is static: its
approximately 0.0042 nm benefit is a predicted noise component and did not
trigger the proposed closed-loop comparison (C3). Earlier photon-budget and
latency failures and corrections also remain in the record.

`provenance.json` in the frozen study bundle gives recorded source identities and consumed-file hashes.
The source code is public at
https://github.com/xhvoid/Shack-Hartmann-AO-Simulation/tree/642a5b76de97e1fbe46fc49dd5fad232fb725219.
The evidence archive is private; its commit identities are references, not
public download links. `frames.csv` contains all saved residual/validity
samples. `data.json` contains values, paired contrasts and availability.
`manifest.json` binds every member, including the offline exporter.

Read [the wording corrections](gain-study-corrections.md) with the original execution reports.
It is an additive clarification; historical reports and hashes are unchanged.
