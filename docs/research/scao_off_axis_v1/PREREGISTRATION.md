# Off-axis SCAO science: pre-registered validation plan

Prepared 2026-11-04, before any validation run was inspected. Each check
names its observable, its independent prediction, the assumptions behind it,
the acceptance criterion and the origin of the tolerance. The results are
reported in [VALIDATION.md](VALIDATION.md) against this plan without
retuning the criteria.

## Model under test

- Native layered frozen-flow atmosphere, `native_layered`
  (`shwfs_ao.backends.native.layered_atmosphere`). Layer `l` with altitude
  `h_l`, wind `v_l` and Fried parameter `r0_l = r0 f_l^(-3/5)` at 500 nm.
- Directional sample (new): phase along sky direction `theta` at time `t`,
  `phi_theta(r, t) = sum_l S_l(r + h_l theta - v_l t)`, with `S_l` the layer's
  frozen pattern (periodic band plus analytic low-frequency modes), followed by
  pupil piston removal. Zenith, small angle, thin layers, no cone effect, no
  inter-layer diffraction, no zenith stretch.
- Science image: residual `phi_theta - C(t)`, where `C(t)` is the DM correction
  the WFS saw at frame time `t` (the pre-update convention of the existing
  2.2 m observer). Instantaneous intensities from the native FFT propagator
  are averaged; peak Strehl uses `peak_strehl_from_discrete_flux` against the
  zero-OPD image of the same propagator, wavelength, grid and unit flux.

## Checks

### C1 Zero separation and loop independence (exact)

- Observable: closed-loop history arrays (`pre/post_update_residual_opd_rms_m`,
  requested/applied commands, row masks, `reconstruction_usable`), the
  history `config_hash`, and the on-axis long-exposure image and Strehl.
- Prediction: bitwise identical for (a) no science direction, (b) the default
  offset, (c) explicit `(0, 0)`, (d) `(0, 0)` listed with other offsets in any
  order, (e) WFS exposure sub-sampling enabled (left-point and midpoint).
  Sampled `(0, 0)` residual equals the loop's `pre_update_residual_opd_m`
  exactly (`max_on_axis_difference_m == 0`).
- Assumptions: the directional sample draws no random number, does not touch
  the atmosphere clock, and is taken after the WFS measurement; `h * 0.0 = 0.0`
  and `x - 0.0 = x` in IEEE arithmetic.
- Acceptance: exact equality (tolerance 0). Any nonzero difference fails.
- Evidence: unit tests on the layered 2 m profile; a 2.2 m run with four
  offsets against a bare 2.2 m run of the same length, and a reordered
  shorter 2.2 m run against the prefix of the long run.

### C2 Ground-layer limit (exact)

- Observable: directional residual OPD maps and PSFs for an atmosphere whose
  layers all have `h = 0`.
- Prediction: identical in every direction (`h theta = 0` for every layer).
- Acceptance: bitwise equality of the OPD maps (tolerance 0), hence of PSFs.

### C3 Signed fractional shift (analytic pattern)

- Observable: the directional OPD map of one layer at altitude `h` whose
  spectral content is replaced by one known mode: (i) one periodic-band
  oblique sinusoid `A cos(2 pi (f_x x + f_y y) + phi)` with
  `(k_x, k_y) = (5, -3)` screen cycles; (ii) one analytic low-frequency node of
  level 1 (a subharmonic below the FFT band). Directions chosen so that
  `h theta` equals signed fractional sample counts `(3.3, -1.7)`,
  `(-2.25, 4.6)`, `(0.4, 0)`, `(0, -0.75)`; wind `(-7, 3)` m/s at
  `t = 0.0137 s`.
- Prediction: `A cos(2 pi f . (r - s) + phi)` evaluated directly on the pupil
  grid with `s = v t - h theta`, then piston removed and scaled to OPD.
- Acceptance: max absolute difference `<= 1e-12` of the map's maximum, the
  float64 round-off of a 1600-sample FFT/matrix evaluation (machine epsilon
  `2.2e-16` times a few hundred operations). Mirrored (`-theta_x`) and
  axis-swapped directions must differ from the sample by more than `1e-3` of
  the maximum whenever both shift components are nonzero, so sign and axis
  errors are detectable.

### C4 Published anisoplanatism model (ideal on-axis correction)

Controlled case, distinct from the closed-loop demonstration: the Robo-AO-2
2.2 m layer table (`robo_ao2_22m_ngs_draft@2`: 11 layers, `r0 = 0.113 m` at
500 nm, `L0 = 25 m`), 256-sample pupil, no DM, no WFS. Residual along
`theta` under ideal on-axis correction: `eps_theta = phi_theta - phi_0`.
Separations 5, 10, 20, 30 arcsec along `+x` (40 arcsec is examined in C5
because its top-layer footprint span, 5.04 m, exceeds the 4.42 m screen
period).

- Observable A: the structure function of `eps_theta` along baselines
  parallel (`x`) and perpendicular (`y`) to `theta`, averaged over the pupil
  and over `N = 200` independent realizations (realization indices 0..199 at
  `t = 0`).
- Prediction A (Britton 2006 Eq. 12 form, derived independently in
  [VALIDATION.md](VALIDATION.md)):
  `D_eps(rho) = sum_l [2 D_l(rho) + 2 D_l(h_l theta) - D_l(rho + h_l theta) - D_l(rho - h_l theta)]`
  with `D_l` the von Karman phase structure function for `r0_l` and
  `L0 = 25 m` (closed form, cross-checked by quadrature of the repository's
  PSD constant `0.023 r0^(-5/3) (f^2 + L0^-2)^(-11/6)`), expressed in OPD.
  Also recorded: the Kolmogorov (`L0 = inf`) version, to quantify the
  outer-scale mismatch with the paper's Kolmogorov figure.
  *Amendment, 2026-11-04, before the production run:* the first draft of this
  line and of the script omitted the `2 D_l(h_l theta)` term. A
  10-realization smoke test of the script predicted Strehls above one, which
  exposed the omission; the term is required for `D_eps(0) = 0` and
  `D_eps(inf) = 2 var(eps)`. The acceptance criteria are unchanged.
  *Amendment 2, 2026-11-04, before the production run:* the same smoke test
  showed the simulated structure function 10-15 % below the continuous
  prediction at the one-sample lag (8.6 mm) with 1 % standard errors, and
  converging to it by a few samples. The sampled screens carry no power
  outside the grid band `|f_x|, |f_y| <= 1/(2 delta)`, so the quantity the
  discrete model can reach is the band-limited structure function. Prediction
  A is therefore the continuous closed form minus the out-of-band integral
  `2 int_{outside band} sum_l 4 Phi_l(f) sin^2(pi f . h_l theta) (1 - cos 2 pi f . rho) d^2f`
  (polar quadrature, independent of the sampler); the continuous form is
  reported beside it. The Strehl prediction B keeps the continuous form and
  additionally reports the band-limited correction over lags within eight
  samples, expected to be below 0.001. Criteria unchanged.
- Observable B: the long-exposure on-axis Strehl (image value at the target's
  nominal position, relative to the ideal image) and the peak Strehl at
  1.65 um of the intensity mean over the same realizations.
- Prediction B (Britton 2006 Eq. 5 form): `S = sum_rho T(rho) exp(-D_eps(lambda; rho)/2) / sum_rho T(rho)`
  with `T` the discrete autocorrelation of the sampled pupil on the
  propagator's padded grid, and `D_eps` in rad^2 at 1.65 um, evaluated on the
  2-D lag grid. For a Gaussian homogeneous residual this is exact for the
  long-exposure OTF, so the prediction includes the pupil's piston/tilt
  content as the simulation does (nothing removed). Also recorded: Fried's
  small-angle factor `exp[-(theta/theta_0)^(5/3)]` with
  `theta_0 = 0.314 r0(lambda) / hbar`, `hbar = (sum_l f_l h_l^(5/3))^(3/5)`
  (11.45 arcsec at 1.65 um), expected to overstate the loss at small `theta`
  (it counts tilt and piston) and to be valid only where the finite-aperture
  OTF integral reduces to it.
- Uncertainty: A, standard error over the 200 independent realizations at
  each lag; B, standard error of the mean over 10 batch means of 20
  realizations each.
- Acceptance: A, `|sim - pred| <= max(3 SE, 0.02 pred)` at every lag up to
  half the pupil (`rho <= 1.1 m`) on both baselines (2 % is the documented
  accuracy of the discrete spectrum's pupil variance, 0.6 %, with margin for
  the band's finite period); B, `|S_sim - S_pred| <= max(3 SE, 0.02)` at each
  separation for the on-axis Strehl; the peak Strehl may exceed the on-axis
  value by at most the same tolerance. A discrepancy beyond this is
  investigated and, if unresolved, reported with the claim it limits.

### C5 Numerical convergence (one setting at a time)

- Footprint / screen period: repeat C4 (A and B) at 20, 30 and 40 arcsec with
  `screen_period_factor = 4` (period 8.83 m) and `N = 100`. Prediction: at 20
  and 30 arcsec the factor-2 and factor-4 results agree within their combined
  3 SE; at 40 arcsec the factor-2 screen may show the periodic-band wrap
  (span 5.04 m > 4.42 m) as a bias beyond 3 SE, which the factor-4 screen
  removes. Reported as a limit on the usable separation of the default
  screen for the 2.2 m profile.
- Focal-plane sampling: (i) C4 B at `pad_factor = 6` versus 3 for the same
  realizations; (ii) the 2.2 m closed-loop case over frames 150..299 with
  offsets 0 and 20 arcsec at pad 3 and pad 6. Prediction: peak-Strehl change
  below 0.01 (the peak of a sampled image is biased low by at most
  `~ (pi^2/12)(dx/FWHM)^2` relative, about 0.4 % for `dx = lambda/(3D)`
  against a diffraction FWHM of `1.03 lambda/D`). Reported as whether the
  conclusion (monotonic trend, Strehl values to two decimals) is affected.

### C6 Demonstration (not a validation check; reported, not accepted)

`robo_ao2_22m_ngs_draft@2`, seed 1, realization 0, 1500 frames at 750 Hz,
offsets `(0,0), (5,0), (10,0), (20,0)` arcsec, 1.65 um, frames 150..1499
averaged (burn-in 0.2 s), pad factor 3, blocks of 75 frames (0.1 s) for the
block scatter. Expectation: Strehl decreasing with separation; the single
realization may show non-monotonic steps within the block scatter.
