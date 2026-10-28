# Detector model

This page describes the two Shack–Hartmann detector chains, their units,
identities and uncertainty model, and what each one supports. The execution
record and its evidence are in
[`refactor/DETECTOR_LEVEL_DEVELOPMENT_STATUS.md`](refactor/DETECTOR_LEVEL_DEVELOPMENT_STATUS.md).

## Two chains, selected explicitly

| Chain | Selected by | Sensor |
| --- | --- | --- |
| AO-REF-004 compatibility chain | every profile up to schema 6; a schema-7 profile without `detector_physics` | `wfs.shack_hartmann.DetectorShackHartmannSensor` (unchanged: stages, draws, hashes, defaults) |
| Physical camera chain `shwfs_ao.detector.physical_camera.v1` | a schema-7 profile with a `detector_physics` block | `wfs.shack_hartmann.physical_measurement.PhysicalShackHartmannSensor` |

There is no implicit physical default. `ccd` is an explicit camera type, not
the compatibility path. The compatibility chain keeps its frozen behaviour:
- PRNU is applied after the background;
- full-well clipping comes after read noise;
- `photons_per_subap_frame = None` takes its own branches;
- the adapters bypass noise.

## Units

| Name | Meaning |
| --- | --- |
| incident photons | photons per frame reaching the detector, after the optical throughput `T` (which excludes QE) |
| `input_e` | photoelectrons collected in a pixel, before electron multiplication |
| `output_e` | electrons at the output amplifier (`input_e` × EM gain) |
| `adu` | raw digital codes; conversion gain is **output** e⁻/ADU |
| `output_e_equivalent` | the raw unit when the ADC is disabled |

Processed images and every gate are in input-referred electrons. QE is
applied exactly once, by the photometry. The camera chain never applies it.
The historical `photons_per_subap_frame × qe` interface is untouched.

## Physical chain

For each lenslet block (a centroid window of `w` pixels plus a guard ring of
`g` pixels, `b = w + 2g`):

| Step | Operation | Source |
| --- | --- | --- |
| 1 | residual OPD → phase `2π OPD / λ_j` per quadrature node | DET-04 |
| 2 | focal field by matrix Fourier transform at `k × k` Gauss–Legendre nodes per pixel | DET-03 |
| 3 | `|E|²` normalized to each wavelength's total flux; sum `Σ_j w_j I_j` with detected-electron weights | DET-02/04 |
| 4 | pixel integration and charge diffusion: `P_c = ∫ I(θ) (rect_c ⊗ G_σ)(θ) dθ` | DET-03 |
| 5 | source expectation `S = N_e,a · capture · unit spot`; sky `B_sky` (QE already applied) | DET-02 |
| 6 | optical photoresponse `r = PRNU · live` multiplies `S` and `B_sky` only | DET-05 |
| 7 | `+ dark_map · t_exp` (hot pixels; not multiplied by PRNU) | DET-05 |
| 8 | Poisson source + sky + dark charge; plus a separately drawn pre-register CIC count | DET-05 |
| 9 | pixel full-well clip (flag `pixel_saturated`) | DET-05 |
| 10 | EMCCD register: `Gamma(n, G)` for `n > 0`, zero for `n = 0`, identity at `G = 1`; register-capacity clip (flag `register_saturated`) | DET-05 |
| 11 | electronic coupling `y = K q` on the realized signal; zero boundary at the block edge | DET-03 |
| 12 | read noise (per-pixel map for CMOS) | DET-05 |
| 13 | non-linearity `y + Σ c_k y^(k+2)` → conversion gain → bias + fixed pattern → ADC rounding and digital clip | DET-05 |
| 14 | RTC processing: `Y = P[(X − B̂ − D̂ − Ŝ) c / F̂]` | DET-06 |
| 15 | centre of gravity on the window; `detector_covariance_v2` quality; validity gates | DET-07 |

### Optics (DET-03, DET-04)

The intensity normalized to the lenslet's total flux is

    I(θ) = |E(θ)|² · dx dy / λ² / Σ|A|²

`E` is evaluated with the `numpy.fft` sign, so with `k = 1` (one node at the
pixel centre) and the legacy pixel scale `λ/(pad n_s dx)` the model
reproduces the frozen FFT spots to 1e-12.

The pixel response `R_c = rect_c ⊗ G_σ` uses a Gaussian truncated at ±5σ and
renormalized. The responses of all pixels sum to one at every angle, so
diffusion redistributes flux without creating or destroying any.

Losses are reported, never renormalized away:
- `optical_field_loss`: flux outside the represented grid;
- `diffusion_outflow`: flux diffused beyond the block;
- the block capture fraction (`relative_throughput`).

Fail-closed conditions:
- The sampled pupil makes the far field periodic with period `λ/dx`. A
  represented extent that reaches one period at the shortest wavelength
  fails closed.
- A polychromatic band requires the MFT sampling.
- The HCIPy backend fails closed for every physical-path feature.

### Photometry (DET-02)

The detected electrons of an aperture of illuminated area `A_a`, over an
exposure `t`, are

    N_e,a = A_a t ∫ f_λ T QE λ / (h c) dλ

AB magnitudes follow Oke & Gunn (1983):
`m_AB = −2.5 log₁₀ f_ν[cgs] − 48.60`, so `f_ν,0 = 3630.78 Jy` (3631 Jy when
rounded).

The sky contribution per pixel is a surface brightness times the pixel solid
angle.

Budgets scale with each subaperture's illuminated area, so a partially
illuminated lenslet or a central obstruction is counted once. Window capture
is applied afterwards.

### Camera presets (DET-05)

| Preset | Type | QE | Read noise (output) | Gain | Other |
| --- | --- | --- | --- | --- | --- |
| `synthetic_ccd@1` | CCD | 0.80 | 3 e⁻ | 1.6 e⁻/ADU, 16 bit | full well 1e5 e⁻, dark 0.1 e⁻/s |
| `synthetic_emccd@1` | EMCCD | 0.90 | 60 e⁻ (0.2 e⁻ input) | 15 e⁻/ADU, 16 bit | G = 300, CIC 0.005 e⁻/px/read, register 8e5 e⁻ |
| `synthetic_cmos@1` | CMOS | 0.70 | 1.6 e⁻ median, lognormal σ_ln 0.3 | 0.5 e⁻/ADU × (1 ± 0.02 map) | offset map 3 ADU rms |
| `synthetic_emccd_coupled@1` | EMCCD | as `synthetic_emccd@1` | | | plus a synthetic coupling kernel (1 % nearest, 0.2 % diagonal) |

All presets are `synthetic_assumed`. No datasheet is cited, and no
commercial camera is named or implied.

The EM register uses the Gamma model, which is valid only for `G ≥ 100`. In
that regime its `F² = 2` lies within 2 % of the finite-stage value (D2).
Gains with `1 < G < 100` are rejected.

## Persistent maps and pixel identity

The layout `isolated_lenslet_blocks.v1` gives lenslet `lenslet-rRRRR-cCCCC`
the block whose detector origin is `(R·b, C·b)`. Pixel IDs are global
row-major indices on the `(n b) × (n b)` synthetic detector.

Each map is drawn from `detector.realization`, keyed by
`(map, maps-config hash, layout hash, R, C, realization)`. The maps are
PRNU, dead, hot, offset, CMOS gain and CMOS read noise. A pixel therefore
keeps its value for every:
- frame and calibration step;
- dense or batched execution;
- lenslet order and batch size;
- retained-lenslet subset.

The realization hash binds:
- the layout;
- the map-generating settings;
- the derivation;
- a content digest.

## Deterministic reference versus stochastic path

`include_noise=False` substitutes the following and keeps every
deterministic stage:
- charge means for Poisson;
- the mean CIC rate;
- `G·n` for the register;
- zero read noise.

In the reference path the ADC is the quantizer's expectation under the
declared read-noise dither, `E[round(x + n)]`. That is exactly `rint` for a
noiseless readout, and differs from `x` by at most 2.3e-3 ADU at
σ = 0.5 ADU (decision D00-3a).

Because of this dither, with the ADC on the read noise shapes the
reference response. `CameraConfig.deterministic_response_config`, and with
it the sensor's `response_hash`, therefore binds the read noise and the
dither model (`gaussian_read_noise_expectation_v1`). Two sensors that share
a response hash have identical reference and probe responses. With the ADC
off the reference does not depend on read noise, and the hash does not
either. (Before the 2026-10-16 review, R1, the read noise was left out, and
two references 0.46 ADU apart shared one hash.)

The reference path is not the expected noisy response after saturation,
non-linearity or clipping. The noisy-response identity is kept separate.

A declared non-linearity acts after read noise, so it must be monotonic over
the whole output range, widened by six read-noise sigmas on each side. For a
multiplying EMCCD the range ends at the register capacity, because a Gamma
register can carry a single input electron far above `G` (review R7).

A CMOS read-noise map makes some pixels noisier than the median, so
`CameraMaps.create` repeats the check with the realized map's largest
per-pixel read noise and raises `CameraMapsError` if it fails (re-review
S3). Whether a non-linear CMOS configuration is accepted therefore depends on
its realized map. Every packaged preset is linear.

## Calibration products (DET-06)

Each product is the mean of its frames, minus the products already defined:
- `B̂`: bias frames (it contains the CIC mean);
- `D̂`: dark frames − `B̂`;
- `Ŝ`: sky frames − `B̂` − `D̂`;
- flat: flat frames − `B̂` − `D̂`, converted like measurements and
  normalized over valid pixels.

`B̂ + D̂ + Ŝ` telescopes to the mean of the sky frames (or of the dark
frames when there are no sky frames). So nothing is subtracted twice, and
the shared-frame covariance follows from the algebra.

Gain is a known engineering input. The CMOS gain map is applied once, as
per-pixel conversion gain, and the flat then carries PRNU only.

Masters are fixed for a run. Regenerating them is a new calibration
realization, which moves the conditioned response identity.

`oracle` processing uses the deterministic reference products instead.
`raw_readout` centroids the raw codes and shows the pedestal gain loss.

### Calibration source (optional)

`detector_physics.calibration_source_detected_e_per_full_subap_frame`
declares a bright internal calibration source. With a source declared:
- the deterministic reference path observes the source (scaled by each
  subaperture's illuminated area, no sky), so reference centroids and
  interaction-matrix probes no longer depend on the guide-star magnitude;
- noisy measurements observe the star and the sky;
- the source is observed without sky, so its frames subtract the bias and
  dark masters only (`processing.without_sky_master`); before the
  2026-10-16 review, R3, they also subtracted the operating sky master,
  which left a negative pedestal of one sky level per pixel;
- its calibration-ensemble uncertainty follows the same products: a
  one-frame dark master shared with the flat, not the operating sky master's
  frame count (re-review S1);
- `response_hash` binds the source and that subtraction, and
  `noisy_response_hash` binds the operating budget.

`PhysicalShackHartmannSensor.measure_operating_expectation` is the noiseless
expectation of an operating exposure: the star and sky through the
operating products. It differs from `measure(..., include_noise=False)`,
which is the calibration observation.

Without a source (every version-1 profile), calibration observes the
operating flux. Faint stars then have no calibratable rows, and
`det_emccd_12m_medium_derived@1` refused to build from m_AB = 11 (E3).

### Exposure sub-samples

With `exposure_subsamples = n`, the atmosphere is sampled at
`t + j τ / n` for `j = 0 … n − 1`, with the DM held fixed. The intensities
are averaged and noise is applied once. `n = 1`, the default, is a snapshot
at the *start* of the exposure, so integration moves the effective sample
time later, to `t + τ(n − 1)/(2n)`. At 12 m and m_AB = 8 that lowered the
residual by 3–5 nm, within the seed scatter (DET-08).

## Uncertainty model `detector_covariance_v2` (DET-07)

With centroid Jacobian `j`, bad-pixel back-projection `u = Pᵀ j`, and
`w = u / (f G m')`:

    Var_t(c) = Σ_k w_k² (σ_k² + q_k²/12) + G² F² Σ_l μ_l (Kᵀ w)_l²

This is the temporal variance, conditional on fixed products, and it is
what the validity gates use. Kᵀw is evaluated as a local correlation; no
dense detector covariance is ever formed.

The conditional mean, and with it the Jacobian, the total flux and the
SNRs, subtracts the realized additive master that processing actually
removes, with its bias and offset pedestal taken out. Version 1 used the
ideal background there. With a one-frame sky master, version 1 put the
processed flux at 993 e⁻ instead of 822 e⁻, and the scatter 23 % too
low (review R2). Version 2 matches the measurement to 3e-14 and Monte Carlo
to within 2.4 %.

The calibration-ensemble variance is linearized about the nominal
(expected) background instead, and its master protocol comes from the
products actually used: with a sky product the background error is the sky
master's, otherwise it is the dark mean shared with the flat. It adds:
- the background-master error;
- the flat error (normalization is common-mode and moves no centroid);
- the shared-dark cross-covariance.

It is reported separately as `centroid_calibration_sigma_px`, a persistent
per-run bias.

Scalar limit:

    Var(Z_k) = F²(S_k + B_k + C) + (σ_k/G)² + q_k²/12

The model is **supported** only for:
- a plain centre of gravity;
- no negative clipping;
- no expected saturation (pixel, register or ADC above 90 % of capacity);
- every block pixel's expected ADC code, bias and offset map included, at
  least 5 temporal noise sigmas inside both ADC limits (version 1 checked
  only the upper limit, without offsets, and accepted zero-bias clipping at
  code 0 that made the scatter 27 % lower than predicted; review R4);
- no non-linearity;
- read noise of at least 0.5 ADU;
- `SNR_T ≥ 7`.

Outside that domain it reports an undefined sigma, and the lenslet is
invalid. Monte Carlo (E1) shows the first-order sigma low by about
`4/SNR_T²` near the floor.

## Low valid fraction: frozen DM, waffle, and version 3

The detector model marks lenslets outside its supported domain invalid. It
does not change the control policy. When fewer than `min_valid_fraction`
(0.5) of the lenslets are valid, the reconstructor returns no estimate.
The integrator then receives no increment, so with zero leak the
deformable mirror holds its last commands.

**The latch-up on @2.** At 12 m and m_AB = 11 (SNR_T ≈ 8.6),
`det_emccd_12m_medium_derived@2` loses lock:
- An excursion drops the valid fraction below 0.5.
- The frozen DM never brings the spots back into the validity domain.
- A leak of 0.02 lowers the residual but does not prevent the collapse.

**Opt-in recovery.** `controller.recovery` (schema 7) can reset the DM to
flat after consecutive rejected frames. With that policy the loop
re-closes from flat, but excursions still recur 4–12 times per 400
frames.

**Their trigger is under-regularization.** The relative Tikhonov damping
of 0.001 leaves the global waffle mode unregularized.
- Waffle is sensed about 40 times more weakly than a typical mode, so the
  SH barely restores it.
- Centroid noise drives it as a random walk.
- At m_AB = 11 its wander broadens and clips spots that sit close to the
  validity limits.

**Version 3.** `det_emccd_12m_medium_derived@3` sets
`reconstructor.alpha = 0.1` and keeps the reset as a safety net. In the
predeclared evaluation (root seeds 21–25), m_AB = 11:
- holds 195 nm with a K-band Strehl of 0.71, against 377 nm with the reset
  alone and 1.9 µm on @2;
- has no rejected frame at all.

The same damping lowers the residual at m_AB = 10 by 9 nm. m_AB = 12 is
unchanged, because no lenslet reaches SNR_T ≥ 7 there.

Details: status file, "Closed-loop recovery policy", "Excursion trigger at
m_AB = 11" and "`det_emccd_12m_medium_derived@3`".

## Supported claim

See the status file for the claim wording each piece of evidence supports.
Not claimed:
- a digital twin of any commercial camera or ESO instrument;
- validation against on-sky or laboratory data;
- HCIPy parity for any physical-path feature;
- a 42 m ensemble (one 42 m realization was run);
- a faint-star limiting magnitude independent of the control policy.
