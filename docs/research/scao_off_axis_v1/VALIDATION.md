# Off-axis SCAO science: validation note

Prepared 2026-11-04 against the pre-registered plan in
[PREREGISTRATION.md](PREREGISTRATION.md). Sources are in
[sources.json](sources.json); evidence files are under [evidence/](evidence/).
Implementation: `src/shwfs_ao/backends/native/layered_atmosphere.py`
(`directional_opd_at`), `src/shwfs_ao/control/loop.py`
(`science_directions_rad`, observation field `science_residual_opd_m`),
`src/shwfs_ao/science/off_axis.py`, `src/shwfs_ao/experiments/off_axis_science.py`;
user notes in [docs/scao_off_axis_science.md](../../scao_off_axis_science.md).

**Literature comparison.** The numerical predictions use the derivations
in Section 1. The initial derivation preceded access to the papers. An
[independent source check](independent_source_check_516aff0.json) on
2026-11-04 compared it with Britton (2006, R1) and the publisher's abstract
of Fried (1982, R2). Britton gives the OTF factorization in Eqs. 3–5 and
the four-term structure function in Eq. 12. Figure 2 uses a 5 m aperture
at 2.12 µm. Fried's abstract describes the high-spatial-frequency limit
of the imaging OTF. The [source ledger](sources.json) records the sections
examined and the limits of each comparison.

## 1. Model and derivations

### 1.1 Directional sample

For layer `l` at altitude `h_l` with frozen pattern `S_l` and wind `v_l`,
the on-axis pupil sees `S_l(r - v_l t)`. A ray from a target at sky offset
`theta` (radians, small angle, zenith) reaching pupil coordinate `r` crosses
the layer at `r + h_l theta`, so the target sees `S_l(r + h_l theta - v_l t)`.
The implementation applies the single real-valued shift
`s_l = v_l t - h_l theta` to the periodic band (a Fourier phase ramp
`exp(-2 pi i f . s_l)`) and to the analytic low-frequency modes (evaluated at
`r - s_l`), then removes the pupil piston. The repository units are OPD in
metres; `theta = arcsec * pi / 648000`; positive `theta_x` moves the
footprint toward larger pupil `x` (columns), positive `theta_y` toward larger
pupil `y` (rows).

### 1.2 Residual under ideal on-axis correction and its structure function

With the on-axis phase of every layer removed exactly, the residual along
`theta` is `eps(r) = sum_l [S_l(r + h_l theta) - S_l(r)]`. For one homogeneous
layer with covariance `C(u) = C(0) - D(u)/2`, expanding
`<[eps(r + rho) - eps(r)]^2>` over the four points `r, r + rho, r + h theta,
r + rho + h theta` gives

```
D_eps,l(rho) = 2 D_l(rho) + 2 D_l(h_l theta) - D_l(rho + h_l theta) - D_l(rho - h_l theta)
```

which vanishes at `rho = 0` and tends to `2 D_l(h_l theta)`, twice the
residual variance, for `|rho| >> |h_l theta|`. Independent layers add. This is
the form attributed to Britton (2006), Eq. 12 (R1); along the offset
direction the two displaced terms are `D_l(|rho| +- h_l theta)`, across it
`D_l(sqrt(rho^2 + h_l^2 theta^2))` twice. Equivalently, in the spectral
domain `Phi_eps(f) = sum_l 4 Phi_l(f) sin^2(pi f . h_l theta)`.

`D_l` is the von Karman phase structure function of `r0_l = r0 f_l^(-3/5)`
at the 500 nm reference wavelength,
`D = (L0/r0)^(5/3) 2^(1/6) Gamma(11/6) pi^(-8/3) [24 Gamma(6/5)/5]^(5/6) [Gamma(5/6)/2^(1/6) - x^(5/6) K_(5/6)(x)]`,
`x = 2 pi rho / L0`, scaled by `0.023 / 0.022896` to the repository's PSD
constant; the evidence records its agreement with direct quadrature of the
PSD (`<= 4e-9` relative for von Karman, `3e-8` for Kolmogorov). OPD is
`(lambda_ref / 2 pi)^2` times the phase structure function.

The sampled screens carry no power outside the grid band
`|f_x|, |f_y| <= 1/(2 delta)`; the band-limited structure function the
discrete model can reach is the continuous form minus
`2 int_{outside} Phi_eps(f) (1 - cos 2 pi f . rho) d^2f`, computed by polar
quadrature (`OutOfBandCorrection` in `scripts/off_axis_validation.py`).

### 1.3 Long-exposure OTF and Strehl

For a Gaussian homogeneous residual on the sampled pupil `P`, the
long-exposure OTF at pupil lag `rho` is `T(rho) exp(-D_eps(rho)/2)` with `T`
the discrete autocorrelation of `P` (the form attributed to R1 Eq. 5). The
image value at the target's nominal position, relative to the zero-OPD image
of the same propagator, is

```
S_on_axis = sum_rho T(rho) exp(-D_eps(lambda; rho)/2) / sum_rho T(rho),   D_eps(lambda) = D_eps,OPD (2 pi / lambda)^2
```

independent of the pad factor. The peak Strehl of the accumulated image is at
least `S_on_axis`.

### 1.4 Fried's small-angle factor

`theta_0 = 0.314 r0(lambda) / hbar`, `hbar = (sum_l f_l h_l^(5/3))^(3/5)`,
and `S_aniso = exp[-(theta/theta_0)^(5/3)]` (R2). For the 2.2 m layer table
`hbar = 2677 m` and `theta_0 = 11.45 arcsec` at 1.65 um. The factor counts
the full differential-phase variance (piston and tilt included) and holds in
the asymptotic large-aperture regime, so it is tabulated for scaling only.

## 2. Results

The recorded runs were serial on two threads (Linux, CPython 3.13.18,
NumPy 2.5.4, SciPy 1.18.1, recorded in `evidence/demo_22m/run_record.json`).
Section 4 lists which evidence files are the recorded originals and which
were regenerated from this repository. Reproduction commands (repository
root, after `python -m pip install .`):

```bash
python examples/run_off_axis_science_demo.py --profile robo_ao2_22m_ngs_draft --version 2 --offsets '0,0;5,0;10,0;20,0' --wavelength-um 1.65 --burn-in 150 --block-frames 75 --output outputs/off_axis_science/22m
```

```bash
python scripts/off_axis_validation.py shift
python scripts/off_axis_validation.py ground-layer
python scripts/off_axis_validation.py closed-loop        # needs the demonstration output above
python scripts/off_axis_validation.py anisoplanatism --realizations 200
python scripts/off_axis_validation.py convergence --realizations 100
python scripts/off_axis_validation.py band-limit-bound
```

Unit tests: `tests/backends/native/test_layered_directional_sampling.py`
and `tests/science/test_off_axis.py`.

### 2.1 C1 Zero separation and loop independence (exact)

| Evidence | Compared quantities | Result |
| --- | --- | --- |
| Unit tests, layered 2 m profile (`eso_turbulence_2m_detector@1`, 12 frames) | history `config_hash` and all history arrays for no direction, default offset, explicit `(0,0)`, `(0,0)` listed first/last with `(10,0)`, `(0,-10)`, `(20,5)`; on-axis long-exposure image of `StreamingLongExposure` versus the `(0,0)` image of `OffAxisLongExposure` | bitwise equal; `max_on_axis_difference_m = 0` |
| Unit test, detector-physics 2 m profile with the ESO ten-layer atmosphere, WFS exposure sub-sampling (`subsamples=3` left-point; `subsamples=2` midpoint) | same arrays with and without `(0,0), (15,-5)` directions | bitwise equal; `max_on_axis_difference_m = 0` |
| 2.2 m demonstration (1500 frames, four offsets) versus a bare 1500-frame run without observers or directions (`evidence/closed_loop_checks_22m.json`, `bare_run`) | `config_hash` and nine history arrays (open-loop and residual RMS, requested/applied commands, saturation, validity, usability, row masks) | bitwise equal |
| 300-frame run with the offsets reversed, `[(20,0), (0,0)]`, two observers (pad 3 and pad 6) versus the first 300 frames of the demonstration (`reordered_prefix_run`) | nine history arrays | bitwise equal |
| same, instantaneous peak Strehl of the first 150 selected frames at `(0,0)` and `(20,0)` | per-frame values | equal to `<= 1.1e-15` absolute (last bit; 138-141 of 150 frames differ at that level) |

Acceptance: the loop telemetry and the on-axis maps meet the exact
criterion in every comparison. The per-frame science images of the 2.2 m
case agree bitwise within one process (unit tests) and to one unit in the
last place across two processes; the residual maps they are formed from are
identical (the history and the `(0,0)` map check are exact), so the last-bit
difference arises in the FFT propagation of identical inputs between
processes (library-level round-off, memory alignment), not in the sampling.
The exact claim therefore holds for the loop, the DM commands, the noise
draws and the residual OPD maps; the science images are reproducible to
machine precision.

Along the way the mean instantaneous on-axis H-band Strehl of the
demonstration over frames 150..1499, 0.7504, agrees with the 0.7502 recorded
for the v2 repair trajectory in
[REPAIR.md](../robo_ao2_ngs_v1/REPAIR.md) (that trajectory's outputs were
deliberately omitted from this baseline, so this is a consistency
observation, not an identity check).

### 2.2 C2 Ground-layer limit (exact)

`evidence/ground_layer_check.json`: the eleven Robo-AO-2 layers with every
altitude set to zero (their fractions and winds unchanged), 64-sample
2.2 m grid, times 0 and 0.4 s, offsets (5,0), (0,-10), (20,0), (30,30)
arcsec. Every directional map is bitwise equal to the on-axis map
(`max_abs_difference_m = 0`, `max_directional_displacement_m = 0`), hence
every PSF is identical. Pass.

### 2.3 C3 Signed fractional shift (analytic pattern)

`evidence/shift_check.json`: one layer at 8000 m with wind (-7, 3) m/s at
`t = 0.0137 s`, 40-sample 2 m grid, all other spectral content zeroed.
Footprint shifts in grid samples; the wind travel adds (-1.870, +0.801)
samples in the same frame.

| Component | footprint shift `h theta` (samples x, y) | direction (arcsec) | wind travel (samples) | max error / map max | mirrored `-theta_x` discrepancy | swapped-axes discrepancy | outcome |
| --- | --- | --- | --- | --- | --- | --- | --- |
| periodic | (+3.3, -1.7) | (+4.363, -2.248) | (-1.870, +0.801) | 3.2e-15 | 1.911 | 2.000 | pass |
| periodic | (-2.25, +4.6) | (-2.975, +6.082) | (-1.870, +0.801) | 2.1e-15 | 1.519 | 1.663 | pass |
| periodic | (+0.4, 0) | (+0.529, 0) | (-1.870, +0.801) | 2.7e-15 | 0.323 | 0.258 | pass |
| periodic | (0, -0.75) | (0, -0.992) | (-1.870, +0.801) | 2.1e-15 | 0 (mirror is identity) | 0.481 | pass |
| periodic | (+2, +2) | (+2.644, +2.644) | (-1.870, +0.801) | 3.1e-15 | 1.448 | 0 (swap is identity) | pass |
| analytic | (+3.3, -1.7) | (+4.363, -2.248) | (-1.870, +0.801) | 1.5e-15 | 0.059 | 0.088 | pass |
| analytic | (-2.25, +4.6) | (-2.975, +6.082) | (-1.870, +0.801) | 1.6e-15 | 0.035 | 0.111 | pass |
| analytic | (+0.4, 0) | (+0.529, 0) | (-1.870, +0.801) | 1.3e-15 | 0.007 | 0.007 | pass |
| analytic | (0, -0.75) | (0, -0.992) | (-1.870, +0.801) | 1.3e-15 | 0 (mirror is identity) | 0.013 | pass |
| analytic | (+2, +2) | (+2.644, +2.644) | (-1.870, +0.801) | 1.3e-15 | 0.033 | 0 (swap is identity) | pass |

The periodic mode is the oblique sinusoid `(k_x, k_y) = (5, -3)` screen
cycles (1.25 and -0.75 cycles/m); the analytic mode is level-1 node (4, 7)
(a subharmonic at 0.028 and 0.034 cycles/m). The sampled maps match the
direct evaluation `A cos(2 pi f . (r - s) + phi)` with `s = v t - h theta` to
`3.2e-15` of the map maximum (tolerance `1e-12`), on both axes, both signs
and at fractional shifts, and the sign-flipped and axis-swapped alternatives
differ by `>= 0.7 %` whenever they are not identities. Pass; sign and axis
errors would have been detected. The unit test repeats four of these cases.

### 2.4 C4 Published anisoplanatism model (ideal on-axis correction)

`evidence/anisoplanatism_factor2.json|csv|*.png`: Robo-AO-2 layer table,
`r0 = 0.113 m` at 500 nm, `L0 = 25 m`, 256-sample 2.2 m pupil, screen
period 4.417 m, 200 independent realizations (indices 0..199, `t = 0`),
`theta_0 = 11.45 arcsec` at 1.65 um (`hbar = 2677 m`). The closed-form
structure function agrees with direct quadrature of the repository PSD to
`2.8e-8` relative (recorded). Elapsed 262 s.

**Structure function** (OPD, nm^2; prediction / simulation ± SE at lags of
1, 8 and 64 samples, 8.6 mm, 69 mm and 0.55 m; acceptance over all lags
`<= 1.1 m`: `|sim - pred| <= max(3 SE, 2 % pred)`):

| sep. | baseline | lag 1 | lag 8 | lag 64 | max rel. disc. | max |z| | out-of-band share at lag 1 | outcome |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 5 | parallel | 136.5 / 136.5 ± 0.3 | 2929 / 2924 ± 21 | 19024 / 19178 ± 475 | 1.4 % | 0.39 | 12.0 % | pass |
| 5 | perpendicular | 109.6 / 109.7 ± 0.2 | 1991 / 1990 ± 9 | 12236 / 12170 ± 207 | 2.6 % | 1.25 | 13.9 % | pass |
| 10 | parallel | 154.1 / 154.7 ± 0.5 | 3574 / 3619 ± 33 | 42051 / 42671 ± 1265 | 2.6 % | 1.47 | 11.8 % | pass |
| 10 | perpendicular | 128.6 / 128.8 ± 0.2 | 2677 / 2684 ± 14 | 24769 / 24717 ± 502 | 2.6 % | 0.83 | 13.3 % | pass |
| 20 | parallel | 170.3 / 170.5 ± 0.7 | 4293 / 4293 ± 45 | 67869 / 66059 ± 2218 | 3.8 % | 0.88 | 12.6 % | pass |
| 20 | perpendicular | 146.4 / 146.0 ± 0.4 | 3357 / 3320 ± 22 | 42304 / 40977 ± 984 | 4.2 % | 2.00 | 14.0 % | pass |
| 30 | parallel | 182.0 / 182.3 ± 0.8 | 4623 / 4619 ± 51 | 80718 / 79930 ± 2866 | 2.4 % | 0.46 | 13.6 % | pass |
| 30 | perpendicular | 157.2 / 156.8 ± 0.4 | 3744 / 3694 ± 27 | 53805 / 50494 ± 1384 | 9.2 % | 2.56 | 14.9 % | pass |

The "max rel. disc." column is the largest relative discrepancy at any lag
up to 1.1 m, where the standard errors are largest (2.4-5.7 % of the
prediction at 1.1 m); the `|z|` column shows every lag within 3 SE. The
parallel and perpendicular curves separate as the model predicts (the
parallel baseline saturates at `2 var(eps)` sooner, the perpendicular one
keeps rising), so the direction of the shift is verified as well as its
size. The out-of-band share is the part of the continuous structure function
that lies above the grid Nyquist frequency at the one-sample lag; without
the band-limited reference the one-sample lag would read 12-15 % low with
0.2-0.5 % standard errors, which was the Amendment-2 finding.

Tendency worth stating: at 20 and 30 arcsec the perpendicular structure
function at baselines near 1 m runs 4-9 % below the prediction (2.0 and
2.6 SE). Section 2.5 shows the screen period is responsible.

**Long-exposure Strehl at 1.65 um** (on-axis value of the mean image;
acceptance `|sim - pred| <= max(3 SE, 0.02)`; the peak Strehl must not
exceed the on-axis value by more than the same tolerance):

| sep. (arcsec) | theta/theta_0 | pred. von Karman | pred. Kolmogorov | Fried factor | sim. on-axis | SE (10 batch means) | sim. peak | disc. | rel. disc. | tolerance | outcome |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 5 | 0.44 | 0.8810 | 0.8789 | 0.7779 | 0.8810 | 0.0025 | 0.8810 | +0.0000 | +0.0 % | 0.0200 | pass |
| 10 | 0.87 | 0.7404 | 0.7340 | 0.4505 | 0.7391 | 0.0057 | 0.7391 | -0.0013 | -0.2 % | 0.0200 | pass |
| 20 | 1.75 | 0.5554 | 0.5416 | 0.0795 | 0.5614 | 0.0102 | 0.5614 | +0.0061 | +1.1 % | 0.0307 | pass |
| 30 | 2.62 | 0.4612 | 0.4424 | 0.0069 | 0.4744 | 0.0140 | 0.4744 | +0.0132 | +2.9 % | 0.0419 | pass |

The peak of every mean image is its central sample, so peak and on-axis
Strehl coincide. The band limit of the grid changes the prediction by
`+0.7e-6` to `+1.1e-6` over the lags within eight samples (evaluated
exactly) and by at most `+2.1e-4` over all remaining lags
(`evidence/band_limit_bound.json`: `D_hf <= 4 sigma_hf^2`, with
`sigma_hf^2 = 1.2e-4` to `2.2e-4` rad^2 at 1.65 um the out-of-band variance
of the residual; the typical value is half the bound), so the band-limited
prediction lies within `[S, S + 2.1e-4]` of the continuous one, two orders
of magnitude below the tolerance. The bound was added after an
independent review noted that the first version of this note stated only
the inner-lag subtotal. The Kolmogorov prediction
differs from the von Karman one by 0.2-1.9 % (outer scale 25 m), so a
numerical match to a Kolmogorov figure would be meaningful only to that
level; the comparison is made against the von Karman equations in the same
form. Fried's factor `exp[-(theta/theta_0)^(5/3)]` falls from 0.78 to 0.007
over the same range while the finite-aperture OTF integral and the
simulation stay at 0.88-0.46: for a 2.2 m aperture at these separations the
finite-aperture peak Strehl and the high-frequency OTF factor describe
different observables in this regime (R1, Fig. 2). The simulated Strehl
met the C4 tolerance at each tested separation.

### 2.5 C5 Numerical convergence

**Screen period** (`anisoplanatism_factor4.json`, period 8.835 m, 100
realizations at 20, 30, 40 arcsec; `anisoplanatism_factor2_40arcsec.json`,
period 4.417 m, 100 realizations at 40 arcsec):

| sep. | factor | pred. | sim. on-axis ± SE | sim. peak | D max rel. disc. (par. / perp.) | D max |z| (par. / perp.) |
| --- | --- | --- | --- | --- | --- | --- |
| 20 | 2 (N=200) | 0.5554 | 0.5614 ± 0.0102 | 0.5614 | 3.8 % / 4.2 % | 0.88 / 2.00 |
| 20 | 4 (N=100) | 0.5554 | 0.5437 ± 0.0144 | 0.5437 | 9.7 % / 5.1 % | 1.45 / 1.34 |
| 30 | 2 (N=200) | 0.4612 | 0.4744 ± 0.0140 | 0.4744 | 2.4 % / 9.2 % | 0.46 / 2.56 |
| 30 | 4 (N=100) | 0.4612 | 0.4646 ± 0.0219 | 0.4646 | 0.9 % / 3.4 % | 0.51 / 0.53 |
| 40 | 2 (N=100) | 0.4080 | 0.4206 ± 0.0139 | 0.4206 | 4.1 % / 6.6 % | 1.68 / 1.15 |
| 40 | 4 (N=100) | 0.4080 | 0.4212 ± 0.0180 | 0.4212 | 7.0 % / 3.2 % | 1.35 / 0.99 |

With the doubled period the 30 arcsec perpendicular deficit (2.56 SE at
factor 2) disappears (0.53 SE), and the factor-2 and factor-4 Strehls agree
within their combined errors at 20, 30 and 40 arcsec (0.6-1.0 SE apart).
The deficit tracks the largest pairwise separation the sampler is asked for
(`|h theta| + rho`, 3.1 m at 30 arcsec and a 1 m baseline): the periodic
band and the inner quadrature cells resolve frequencies at the spacing of
the screen period, and separations approaching the period are where that
discretization is coarsest. At 40 arcsec the on-axis and displaced
footprints of the top layer overlap through the periodic wrap of the
default screen (span 5.04 m > 4.42 m, flagged by `footprint_report`), yet
the Strehl and the structure functions show no bias beyond 1.7 SE at either
factor: the overlapping part of the band is a tiny share of the residual
variance at that separation. Conclusion: for the 2.2 m profile with the
default screen the directional structure function is accurate to the
stated tolerance up to 20 arcsec, to about 9 % at 30 arcsec baselines near
1 m, and the Strehl is converged in the screen period at every separation
tested; the demonstration's offsets (<= 20 arcsec) are inside the converged
range. Above 30 arcsec a larger `screen_period_factor` should be used when
the structure function itself is the observable.

**Focal-plane sampling** (`closed_loop_checks_22m.json`, `focal_sampling`
and `demonstration_interpolated_peaks`). (i) Ideal-correction case, pad 6
on the first 50 realizations: peak minus on-axis Strehl 0.0000 at 5, 10 and
30 arcsec and 0.0026 at 20 arcsec, versus 0.0000 at pad 3; the on-axis value
is pad independent by construction. (ii) 2.2 m closed loop, frames
150..299, same residual maps propagated at pad 3 and pad 6:

| offset | discrete peak Strehl pad 3 | pad 6 | interpolated peak (pad 3 image) | interpolated peak (pad 6 image) | on-axis Strehl (both) |
| --- | --- | --- | --- | --- | --- |
| (0, 0) | 0.7253 | 0.7863 | 0.7921 | 0.7921 | 0.3665 |
| (20, 0) | 0.5624 | 0.5624 | 0.5702 | 0.5702 | 0.2863 |

The pre-registered expectation (change below 0.01) was wrong for the
on-axis image: the discrete peak changed by 0.061. The cause is not the
propagation but the definition of the peak as the maximum sample: this
0.2 s exposure is nearly diffraction limited with a static sub-pixel tilt
(its true peak sits 0.47 and 0.33 pad-3 pixels from the maximum sample), and
an Airy core read half a pad-3 pixel off its peak is 6.4 % low. A
band-limited image's trigonometric interpolant is the continuous image (the
pad-3 grid is Nyquist sampled), and the interpolated peaks of the pad-3 and
pad-6 images agree to `1.4e-5`, as do the on-axis values to `1e-16`. For the
1350-frame demonstration images the interpolated peaks are 0.4444, 0.4333,
0.3957 and 0.3372 against the discrete 0.4370, 0.4264, 0.3882 and 0.3260
(1.6-3.3 % low; the true peaks lie 0.03-0.4 pixel from the central sample).
Conclusion: the ordering and the monotonic trend of the demonstration are
unaffected; the discrete peak Strehl values are biased low by up to 3 % for
the demonstration and up to 8 % for a short, nearly diffraction-limited
exposure. The repository's peak-Strehl definition is kept, and this bias is
stated beside the demonstration table; where the peak is the quantity of
interest, use the interpolated peak on a supported grid.

**Peak estimates from the science observer.** The production observer returns
`interpolated_peak_strehl` for the mean intensity, using one subpixel
estimator (`shwfs_ao.science._psf_peak.interpolated_peak`) for the science
and the zero-OPD ideal images. The 300-frame check above was run on
2026-11-04 with the loop of this implementation; its pad-3 and pad-6
long-exposure images of frames 150..299 and their ideals were saved as
`outputs/off_axis_science/22m_prefix300_images.npz` (git-ignored,
70,780,402 bytes, SHA-256
`4eeea44ca754d639acf91c6d9012b28633f5e4ee3bc2a9db050325f50aa5145d`) and
recorded in `evidence/closed_loop_checks_22m.json` (SHA-256
`63cf0b2713341a87bc5b289da8c02c3d810cc3e83a474f4c558c5ecf1f987df5`); the
demonstration's images and history were saved as
`outputs/off_axis_science/22m/psfs.npz`
(`79a444ae92bb55db6b1195ee756871d0176832e58e35420059370669668f1b5d`) and
`history.npz` (`59feb80841b635ad3c1d6a7951844c9ad7f3c76abcd4ddc8442b8ba36c6d6f65`).
A replay of the 300 frames at the reviewed revision reproduced the saved
pad-3 and pad-6 images bitwise. An earlier replay against an archived
residual set from October 2026 is not reproducible from this repository and
is not reported here.

*Original C5 result (registered observable).* At zero separation the
brightest-pixel Strehl changed from 0.72532877 (pad 3) to 0.78629241
(pad 6), a change of 0.06096 that exceeds the registered 0.01 tolerance:
fail, as stated above. At 20 arcsec it changed by 2e-16: pass.

*Subpixel result (reported separately, same images).* The production
estimator gives 0.79207972 (pad 3) and 0.79209421 (pad 6) at zero
separation and 0.57015233 at both pads at 20 arcsec. The 1.45e-5 pad-3
versus pad-6 difference is a numerical difference in locating the peak:
the final refinement grid is 1/64 of a pad-3 pixel in one case and 1/64 of
a pad-6 pixel in the other, and the residual against the core curvature is
of that order. An independent reference, direct DFT propagation of every
frame's pupil field onto a 1/64-pad-3-pixel focal grid around the located
peak (no image interpolation; replay of the same 300 frames), gives
0.7920954 at zero separation and 0.5701533 at 20 arcsec: the estimator is
within 1.6e-5 (pad 3) and 1.2e-6 (pad 6) on axis and 1.0e-6 at 20 arcsec.

*Competing-core regression (independent review of the first estimator).*
The first estimator refined only the brightest half-pixel sample. Two
incoherent copies of the 2.2 m pupil PSF at 1.65 um, one core at (0.25,
0.25) pad-3 pixels and a second on grid 12 pixels away with relative weight
0.975, give a direct-propagation global peak Strehl of 0.50687 while the
brightest sample belongs to the fainter core: the first estimator returned
0.49422 at pad 3 (error -0.0127) and 0.50687 at pad 6, where the brighter core
falls on a half-pixel node. The estimator now refines
every local maximum of the half-pixel grid within 0.85 of its largest value
(at most 64, strongest first) and returns the best: error 2e-16 at pad 3 and
3e-16 at pad 6 (`tests/science/test_off_axis.py`,
`test_a_brighter_core_between_samples_beats_a_fainter_on_grid_core`). The
single-core 300-frame and demonstration values above are unchanged to seven
decimals; the cost is 0.4 s (pad 3) and 2.8 s (pad 6) per image pair with
about 35 MiB more peak memory. Remaining limit: the rule refines at most 64 local maxima of the
half-pixel-grid interpolant whose values reach 85 % of that grid's largest
value. The fraction was set from one measured case, the unaberrated image
of the 256-sample, unobstructed 2.2 m pupil at 1.65 um tilted a quarter
pixel in both axes (the farthest a true peak can lie from a half-pixel
node), whose brightest sample reads 0.9259 (pad 2), 0.9665 (pad 3) or
0.9915 (pad 6) of its peak; no lower bound for every aberrated PSF the
propagator can produce has been derived, so a core narrower than that
diffraction core could be read below the fraction and skipped, and
candidates beyond the 64 strongest are not refined. The 3 % crossover
of the example is specific to that PSF and sampling. The direct-propagation
comparison establishes the peak accuracy for the cases tested here.

The band-limit argument (image spectrum confined to the pupil
autocorrelation support, hence Nyquist sampling at pad 2) and the Strehl
definition follow standard texts (Goodman, *Introduction to Fourier
Optics*; Hardy, *Adaptive Optics for Astronomical Telescopes*); no section
locator is given.

### 2.6 C6 Demonstration, `robo_ao2_22m_ngs_draft@2` at 1.65 um

`evidence/demo_22m/off_axis_strehl.csv` and `run_record.json` are the
table and the run record written by the original run of the example
(sampled peak only, before the subpixel estimator existed).
`evidence/demo_22m/regenerated/off_axis_strehl.csv` is the same table
regenerated from the saved images of that run with the final production
estimator; `regenerated/regeneration_record.json` lists the inputs with
their SHA-256, the command, the 44 fields recomputed from the arrays and
checked for exact value equality against the saved record, and the fields
carried forward from the saved record. The regeneration script and the
saved arrays (`psfs.npz`, `history.npz`, hashes above) are not part of this
repository; `evidence/demo_22m/reproduction/` holds the artifacts of a
repeat of the command from a fresh clone (Section 4). One closed-loop
trajectory: seed 1, realization
index 0, atmosphere realization stream
`shwfs_ao.random.sha256-json-pcg64-v1:4b86fc8b66fed351f137f5e17da9735319da578a16cbd4c7f4fd0b4e410e6c80`,
profile `config_hash a6ffdbc0…`, `history_config_hash fa1a0474…`, 1500
frames at 750 Hz, one WFS sample per frame, frames 150..1499 averaged (1350
frames, 1.8 s), PSF pad factor 3 (51.4 mas pixels), blocks of 75 frames.
Every reconstruction was usable and no actuator saturated. Elapsed 1373 s.

| x (arcsec) | y | r | frames | long-exposure peak Strehl (discrete) | interpolated peak | on-axis Strehl | mean instantaneous peak Strehl ± SD | block peak Strehl SD (18 blocks) | FWHM (mas) |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 0 | 0 | 0 | 1350 | 0.437 | 0.444 | 0.437 | 0.750 ± 0.069 | 0.051 | 215 |
| 5 | 0 | 5 | 1350 | 0.426 | 0.433 | 0.426 | 0.720 ± 0.068 | 0.050 | 212 |
| 10 | 0 | 10 | 1350 | 0.388 | 0.396 | 0.388 | 0.657 ± 0.076 | 0.051 | 214 |
| 20 | 0 | 20 | 1350 | 0.326 | 0.337 | 0.326 | 0.599 ± 0.088 | 0.080 | 226 |

The long-exposure Strehl decreases monotonically with separation in this
realization (0.437, 0.426, 0.388, 0.326), as does the mean instantaneous
Strehl (0.750, 0.720, 0.657, 0.599). The two statistics differ by a factor
near 1.7 because the model has no separate tip-tilt loop: the target's
residual image motion over 1.8 s broadens the long exposure (the peak sits
at the central sample for every offset) while each frame remains sharp. The
block (0.1 s) peak Strehls range 0.58-0.79 on axis and 0.41-0.68 at 20
arcsec; their scatter is an indicator of the single realization's
variability, not a standard error of the long-exposure value, and the
block images are sharper than the full exposure because the tilt wanders
less within 0.1 s. The anisoplanatic loss at 20 arcsec (factor 0.75 in the
long exposure, 0.80 instantaneous) is milder than the ideal-correction
factor 0.5554/1 of Section 2.4 because the closed loop's own residual
dominates the on-axis budget. Footprint displacements of the top layer:
0.35, 0.71 and 1.42 m at 5, 10 and 20 arcsec (41, 82 and 164 samples); no
periodic-band wrap overlap at any demonstrated offset.

## 3. Summary of outcomes

| Check | Outcome | Limit on the claim |
| --- | --- | --- |
| C1 zero separation, loop independence | pass (exact for the loop telemetry and residual maps; science images to 1 ulp across processes) | none |
| C2 ground layer | pass (exact) | none |
| C3 signed fractional shift | pass (3e-15 relative; sign/axis alternatives distinguishable) | none |
| C4 structure function | pass at 5, 10, 20, 30 arcsec on both baselines (every lag within 3 SE) | 30 arcsec perpendicular runs 4-9 % low near 1 m baselines with the default screen (2.6 SE) |
| C4 long-exposure Strehl | pass (0.0 to +2.9 %, within 1 SE) | ideal correction, von Karman L0 = 25 m; the Kolmogorov form of the papers differs by up to 1.9 % |
| C5 screen period | converged for the Strehl at all separations; structure function converged to 20 arcsec with factor 2, to 40 arcsec with factor 4 | use factor >= 4 above 30 arcsec for structure-function work |
| C5 focal sampling | registered observable (brightest pixel): change 0.06096 at zero separation, limit 0.01, fail; 2e-16 at 20 arcsec, pass. Reported separately: the subpixel estimate differs by 1.45e-5 between pads (peak-location numerics) and by <= 1.6e-5 from direct propagation | discrete peaks depend on the core position within a pixel; the subpixel estimate refines all half-pixel local maxima within 0.85 of the largest |
| C6 demonstration | monotonic decrease 0.437 -> 0.326 (discrete peak), 0.444 -> 0.337 (interpolated), one realization | single seed; no tip-tilt loop; not a performance prediction |

**Verified against theory:** the directional sampling geometry (shift sign,
axes, fractional shifts in both spectral components, ground-layer limit),
its neutrality for the guide-star loop, and the anisoplanatic second-order
statistics and long-exposure Strehl of an ideally corrected multi-layer
von Karman atmosphere, to the tolerances above.

**Not validated against on-sky measurements:** nothing in this note is
compared with observations. The Robo-AO-2 layer table is a published
simulation input, the 2.2 m loop is the project's draft model (no tip-tilt
loop, no measured pupil or DM maps), and the papers' observational tests were
not reproduced. The equation attributions to R1 and R2 were confirmed by the
independent review recorded in `independent_source_check_516aff0.json`.

**Software note:** the public tests of this evaluation are
`tests/science/test_off_axis.py` (16 tests, including the competing-core
regression at pads 3 and 6) and
`tests/backends/native/test_layered_directional_sampling.py` (12 tests);
`tests/wfs/test_physical_sensor_background.py` covers the telemetry bound
that the 2.2 m profile's first trajectory required. All pass with the
repository's two earlier public test files (59 tests).

**Limits of agreement.** The original discrete peak exceeds the C5
tolerance on the short on-axis exposure; that registered result stands. The
subpixel estimate, reported separately, is pad independent to 1.5e-5 and
agrees with direct propagation to 1.6e-5 on the same images. The default
screen also limits structure-function claims above about 20 arcsec, where
the perpendicular structure function at baselines near 1 m shows a
dependence on screen period.

**Profiles:** `robo_ao2_22m_ngs_draft@2` exercised numerically (closed loop
and ideal-correction benchmark); `eso_turbulence_2m_detector@1` exercised
numerically in the unit tests (short closed loops with offsets);
`eso_drm_42m_scao_derived@2` checked for compatibility only (profile loads,
offsets accepted, footprint report from its layer table) with its scalable
code path exercised numerically on the desktop tier
`eso_scao_smoke_5m_software@2` through `run_off_axis_science` and
`StreamingLongExposure`; no 42 m trajectory was run.

## 4. Evidence files in this repository

The evidence under `evidence/` comes from two sources. Files of the
original run (Linux x86_64, CPython 3.13.18, NumPy 2.5.4, SciPy 1.18.1,
2026-11-04) are kept as recorded; two JSON records are edited public copies
whose only change is the removal of a machine path from a command string,
and each carries the SHA-256 of its original under `public_copy`. The other
files were regenerated from the locally tested candidate revision
`d335e48` on an Apple M1 Pro (macOS 26.5, arm64, CPython 3.14.3, NumPy
2.5.4, SciPy 1.18.1) on 2026-11-06 with the commands of Section 2.

| File | Origin | Agreement with the tables above |
| --- | --- | --- |
| `closed_loop_checks_22m.json` | recorded (SHA-256 `63cf0b27…`) | the source of Sections 2.1 and 2.5 |
| `band_limit_bound.json` | recorded | regenerated values agree to 1e-13 relative |
| `demo_22m/off_axis_strehl.csv`, `demo_22m/run_record.json` | recorded (run record edited as described) | Section 2.6 |
| `demo_22m/regenerated/off_axis_strehl.csv`, `regeneration_record.json` | recorded (record edited as described) | Section 2.6, interpolated column |
| `shift_check.json` | regenerated | every row accepted; largest relative error 3.1e-15 (recorded 3.2e-15); mirrored and swapped discrepancies as tabulated in Section 2.3 |
| `ground_layer_check.json` | regenerated | every directional map bitwise equal to the on-axis map |
| `anisoplanatism_factor2.{json,csv}` and its two PNGs | regenerated, 200 realizations, 76 s | on-axis Strehl 0.8810 ± 0.0025, 0.7391 ± 0.0057, 0.5614 ± 0.0102, 0.4744 ± 0.0140 and the structure-function discrepancies of Section 2.4 at the printed precision; pad-6 peak minus on-axis Strehl 0.0026 at 20 arcsec |
| `anisoplanatism_factor4.{json,csv}` and PNGs | regenerated, 100 realizations | 0.5437 ± 0.0144, 0.4646 ± 0.0219, 0.4212 ± 0.0180 as in Section 2.5 |
| `anisoplanatism_factor2_40arcsec.{json,csv}` and PNGs | regenerated, 100 realizations | 0.4206 ± 0.0139 as in Section 2.5 |
| `demo_22m/reproduction/` | regenerated: the demonstration command run once from a fresh clone, with its own `closed_loop_checks_22m.json` and the tolerance declared before the run | see below |

The realizations of the ideal-correction checks are seeded, so the
regenerated statistics are the recorded ones up to round-off; the agreement
at the printed precision is a check of the public code, not an independent
sample.

**Demonstration repeat.** The repeat finished in 331 s. Its interpolated
long-exposure peak Strehls are 0.44752, 0.43625, 0.39799 and 0.33762 at 0,
5, 10 and 20 arcsec, against the recorded 0.44441, 0.43330, 0.39569 and
0.33722: differences of +3.1e-3, +3.0e-3, +2.3e-3 and +4.0e-4, outside the
1e-4 declared beforehand (`reproduction/pre_run_tolerance.json`). The
profile, atmosphere and realization identifiers agree. The loop configuration
identifier `history_config_hash` includes the calibrated interaction matrix
and differs between Linux (`fa1a0474…`) and macOS (`3e6e8b54…`). On the repeat's
own closed-loop check (`reproduction/closed_loop_checks_22m.json`) the
registered C5 observable gives a sampled-peak change of 0.05992 between pad
3 and pad 6 at zero separation (limit 0.01, fail, as in the recorded run)
and an interpolated change of 1.2e-5; the per-process round-off of the
science images is 1e-15, as in the recorded run. Repeating the command on
the same machine is bit-identical in every history array and image, and
the residual maps of frames 150 to 299 agree to 4e-21 m with an archived
trajectory of the same profile computed on the same machine on 2026-10-24
with the code that preceded this feature (archive hash `a7a73add…`, not in
this repository). A 1500-frame bare run in a process with a different memory layout differs
from the repeat's history by at most 1.6e-21 m in the residual RMS and in
the DM commands (1e-15 relative) over all frames, with identical validity
and row masks, so round-off between processes does not grow in this loop.
The recorded run's first three
instantaneous Strehls after the burn-in differ from the repeat's by 3e-3 to
2e-2, so the two trajectories separate early. A second repeat on Linux
x86_64 (Intel Xeon with AVX-512, CPython 3.13.18, NumPy 2.5.4 and SciPy
1.18.1 with OpenBLAS, 814 s), made from public main with the same code,
reproduced the four five-decimal reference values to within 4e-6. Its
`history_config_hash` matched the original Linux value (`fa1a0474…`), and
the first instantaneous Strehls matched bit for bit. Section 2.5 records
the SHA-256 of the original `history.npz` file separately. The Linux repeat's
open-loop OPD RMS agrees with the macOS repeat to 1e-13 nm over the three
open-loop frames; the first difference is at the first closed-loop frame
(pre-update residual RMS 257.78 nm on Linux, 263.20 nm on macOS), so the
platforms separate at the first DM update. The masked TSVD cutoff is not
the reason: all 374 calibrated slope rows are valid at that frame, all 197 modes
are retained, and no masked singular-value ratio comes within 0.012 of the
0.05 cutoff in the whole run. Which part of the first measurement or
command differs between the platforms has not been identified. The four
demonstration values are therefore reproducible bit for bit on one machine,
reproduced on Linux x86_64 to 4e-6, and differ by up to 3.1e-3 on macOS
arm64.

Not in this repository: the saved image and history arrays of the original
run (`psfs.npz`, `history.npz`, `22m_prefix300_images.npz`, hashes in
Section 2.5), the regeneration script, the original run's PNG figures, and
the October residual archive.
