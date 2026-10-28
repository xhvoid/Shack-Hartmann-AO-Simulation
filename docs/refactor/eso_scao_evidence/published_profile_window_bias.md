# Centre-of-gravity window bias in the published detector-level profiles

Date: 2026-10-15. Working tree on `public-clean-main` at base commit `e55754f`
(uncommitted ESO SCAO benchmark work present). This was an investigation only:
no profile, pinned hash, governed baseline or cache was changed.

Question: do the published detector-level system profiles carry the even-window
centre-of-gravity bias that was found in the ESO SCAO benchmark v1 profiles
(`centroid_window_bias_diagnostic.txt`, about 0.5 λ/D of static tilt at 2.2 µm
on 42 m) and fixed by the v2 23-pixel window?

## Summary

**Native 2 m profiles** (fast@1–4, portfolio@1–4, research@1–3,
eso_turbulence@1): the mechanism is present, the consequence is negligible.

- Every window is even and one pixel asymmetric about the optical-axis pixel.
  The odd neighbouring windows read exactly zero.
- The static tilt the closed loop holds is at most 2.3×10⁻⁸ rad, or
  ≤ 0.021 λ/D at 2.2 µm. That is the even-part bound in §5. The paired
  closed-loop runs measure 2–10 times less.
- The one paired value above that bound, fast@3 at 0.030 λ/D, comes from a run
  that drops 45% of its frames and is only 1.5σ from zero.
- The bias is 2.5 to 300 times smaller than the realization scatter of the
  residual tilt.
- Recommendation: no new versions.

**HCIPy profile** (high_order_10m_hcipy@1–3): a different defect.

- Its 8-pixel windows are centred on the pixel block, but the lenslet axes
  drift across the blocks by up to ±0.49 px.
- The tilt cancels across the pupil, but a focus-shaped slope pattern remains.
  A scaled analogue predicts that the published loop holds about −8 to −30 nm
  rms of static focus (Noll Z4).
- Recommendation: confirm in closed loop on a suitable host, then fix in a new
  version.

## 1. Where the window sits relative to the optical axis

### Native backend (all 2 m profiles)

`NativeShackHartmannOptics` (`backends/native/shwfs.py`) and its batched copy
(`backends/native/shwfs_batched.py`) place each lenslet's illuminated box in a
`pad_factor × ceil(pupil_pixels / lenslets_across)` canvas and form
`fftshift(fft2(ifftshift(canvas)))`. A real-amplitude field's intensity is
centro-symmetric about zero frequency, which `fftshift` puts at canvas index
`N // 2`. That pixel is the flat-spot axis of every lenslet, independent of the
lenslet's position in the pupil, and `reference_pixel_xy` is set to it.

`_center_slice(N, W)` (`shwfs.py:440`, `shwfs_batched.py:56`) crops
`[N//2 − W//2, N//2 + W//2)` for even `W` and `[N//2 − W//2, N//2 + W//2]` for
odd `W`. Relative to the axis pixel:

- An even window covers `−W/2 … W/2 − 1`, one more pixel on the negative side.
- An odd window covers `−(W−1)/2 … (W−1)/2` and is symmetric.

All 2 m profiles have `N = 3 × 11 = 33` (odd), so the axis is index 16 and no
window reaches the canvas edge.

Because the axis pixel is the same for every lenslet, the native asymmetry is a
negative slope offset of the same sign in every lenslet that grows with spot
broadening. The loop turns it into a static positive tilt. This is the same
mechanism as in the ESO v1 profiles.

### HCIPy backend (`high_order_10m_hcipy`)

`HcipyShackHartmannOptics` (`backends/hcipy/shwfs.py`) has no FFT canvas. It
propagates through an HCIPy `MicroLensArray` to the focal plane on the pupil
grid itself.

- **Window.** Each lenslet's window is its own `pupil_pixels // lenslets_across
  = 8` pixel block, and `reference_pixel_xy = (W − 1)/2 = 3.5` is the block's
  geometric centre.
- **Spot axis.** HCIPy 0.7 applies OPD `−r²/2f` about each pixel's nearest
  lenslet centre (`micro_lens_array.py`), so the spot axis is the lenslet
  centre `subaperture_centers_m`.
- **Mismatch.** The pupil grid is `linspace(−D/2, D/2, N)`
  (`core/geometry.py:125`), and lenslet cell edges are spaced between the first
  and last pixel *centres* (`wfs/shack_hartmann/geometry.py:525`). Cells are
  therefore `(N − 1)/n = 383/48 = 7.979` pixels wide, while the blocks are 8
  pixels wide.

Within block `c` the axis sits at `3.5 + δ_c` with

    δ_c = 0.4896 − 0.0208 c   (pixels; c = 0 … 47; −0.10 px per metre of x)

and the same holds for rows in y. The window is symmetric only near the pupil
centre. Edge lenslets are offset by ±0.49 px, almost the native even-window
asymmetry, with opposite signs on opposite sides of the pupil. The mean (tilt)
bias cancels, and a slope pattern `s_x ∝ +x, s_y ∝ +y` remains. A closed loop
holds the static defocus that cancels it. The scaled probe in §6 confirms that
the flat reference spot follows the lenslet axis and not the block centre.

## 2. Classification

| Profile | Backend | Pupil px / lenslets | Canvas N (axis) | Window W, pad | Window offsets from the axis | Symmetric? |
|---|---|---|---|---|---|---|
| fast_2m_detector@1, @2, @3 | native | 52 / 5 | 33 (16) | 18, 3 | −9 … +8 | no |
| fast_2m_detector@4 | native | 52 / 5 | 33 (16) | 24, 3 | −12 … +11 | no |
| portfolio_2m_detector@1, @2, @3 | native | 72 / 7 | 33 (16) | 20, 3 | −10 … +9 | no |
| portfolio_2m_detector@4 | native | 72 / 7 | 33 (16) | 28, 3 | −14 … +13 | no |
| research_2m_detector@1, @2, @3 | native | 96 / 9 | 33 (16) | 22, 3 | −11 … +10 | no |
| eso_turbulence_2m_detector@1 | native | 72 / 7 | 33 (16) | 28, 3 | −14 … +13 | no |
| high_order_10m_hcipy@1, @2, @3 | hcipy | 384 / 48 | none: 8 px block | 8, 4 | −(3.5 + δ_c) … +(3.5 − δ_c), δ_c from +0.49 to −0.49 | only near the centre; antisymmetric across the pupil |

Every published detector-level window is even. The ESO SCAO v2 profiles
(23 px) are the only odd ones.

Each 2 m family's `@1` and `@2` differ only in an explicit
`photon_allocation = "throughput_scaled"`, which equals the loader default. Their
closed loops agree bit for bit (checked on fast_2m_detector, two realizations),
and their open-loop readings are identical for every family. They are reported
together below.

## 3. Method

The probe scripts are in this session's scratchpad (not in the repository).
Each one loads a published profile and changes only `wfs.detector_window_px`,
`controller.n_steps`, or (HCIPy analogue only) the pupil size in an in-memory
copy. Nothing is written back.

- **Open loop (noiseless).** Every lenslet gets the same symmetric local
  defocus `a·r²/(d/2)²` about its own centre. Here `a` is the OPD at the
  mid-edge of the subaperture, and `d` is the lenslet pitch. A least-squares
  geometric oracle gives a mean true slope below 10⁻¹⁴ px, so any mean reading
  is window bias. Each profile was measured at `W` and at `W ± 1`, the same
  test as `test_symmetric_window_removes_the_centroid_bias`.
- **Paired closed loop (noiseless, as published).**
  - Setup: 200 frames, burn-in 50, `realization_index` 0–7. Each window uses
    the same 8 atmosphere realizations.
  - Run length: 200 frames is the longest the 52-pixel `native_frozen_flow_v2`
    screen supports at 10 m/s (a 300-frame run raised the wrap-seam error).
  - Tilt: per frame, a least-squares tilt of the pre-update residual OPD over
    the pupil, as in the 42 m diagnostic.
  - Bias estimate: `T(W) − ½[T(W−1) + T(W+1)]`, where `T` is a realization's
    mean tilt after burn-in. A regression `d_i = a + b·T_ref,i` removes the
    part proportional to the realization's own tilt (window-dependent centroid
    gain), and its intercept `a` is quoted.
  - Realization scatter: the standard deviation of `T(W)` across the 8
    realizations.
- **Even part (asymmetry only).** Recorded residual OPD snapshots (every 10th
  frame after burn-in, 4 realizations, 60 frames) are measured as `s(φ)` and
  `s(−φ)`. For a window symmetric about the axis, `φ → −φ` point-reflects each
  spot about the axis pixel and exactly negates its centre of gravity, so the
  even part `[s(φ) + s(−φ)]/2` is identically zero. It reads 10⁻¹⁷ px for the
  23-pixel control. For an even window it is the asymmetry bias at the spot
  width the loop actually produces, free of the frame-gating noise of the
  paired runs. The tilt the loop would hold if it converted this mean-slope
  bias one for one is `−⟨even⟩ × pixel_scale`.
- **Units.** λ/D refers to 2.2 µm on 2 m (1.10 µrad).
- **Resources.** Every job ran one at a time through
  `shwfs_ao.runtime.resource_guard` with 2 threads, a 300 MiB audited estimate
  (600 MiB required after the 2× margin, against a 1.05–1.1 GiB budget) and a
  120 s wall limit. Of the 72 launches, 69 completed with normal pressure. One
  was stopped by the guard on host **warn** memory pressure (research@3,
  window 21, realizations 4–7) and rerun after pressure returned to normal.
  Two failed immediately (a probe argument error, and the 300-frame screen
  limit) and were rerun. The peak RSS was 185 MiB.

## 4. Open-loop readings: symmetric local defocus, mean slope in pixels

| Profile (window) | 50 nm | 100 nm | 200 nm | 400 nm | `W − 1`, `W + 1` at all amplitudes | Pixel scale |
|---|---|---|---|---|---|---|
| fast@1–3 (18) | −0.00057 | −0.00231 | −0.00995 | −0.05001 | 0 (≤ 10⁻¹⁵) | 0.541 µrad |
| fast@4 (24) | −0.00030 | −0.00121 | −0.00518 | −0.02716 | 0 | 0.541 µrad |
| portfolio@1–3 (20) | −0.00036 | −0.00149 | −0.00693 | −0.04036 | 0 | 0.753 µrad |
| portfolio@4 (28) | −0.00026 | −0.00105 | −0.00456 | −0.02380 | 0 | 0.753 µrad |
| eso_turbulence@1 (28) | −0.00026 | −0.00105 | −0.00456 | −0.02380 | 0 | 0.753 µrad |
| research@1–3 (22) | −0.00038 | −0.00155 | −0.00681 | −0.03781 | 0 | 1.008 µrad |

- The x and y readings are identical.
- All lenslets stay valid, except portfolio@1–3 at 400 nm (82% valid for both
  19 and 20 px).
- The bias grows roughly as the square of the defocus amplitude.
- These are the same −10⁻³ px-level readings as the ESO SCAO v1 24-pixel
  window in `centroid_window_bias_diagnostic.txt` (CI tier: −0.00100 px at
  200 nm).

## 5. Closed loop: static tilt from the even window

Tilts are in units of 10⁻⁹ rad, x then y. The paired values are regression
intercepts ± 1σ; the even-part values are the predicted G-tilt with its pixel
reading in parentheses.

| Profile (W) | Residual (nm rms) | Usable frames W / W−1 / W+1 | Paired closed-loop tilt | Even-part predicted tilt (even slope, px) | Largest, in λ/D at 2.2 µm | Realization scatter | Largest / scatter |
|---|---|---|---|---|---|---|---|
| fast@4 (24) | 316 | 1.00 / 1.00 / 1.00 | +1.0 ± 0.2, +2.0 ± 0.5 | +4.7, +5.7 (−0.0086, −0.0105) | 0.005 | 442, 210 | 0.03 |
| fast@3 (18) | 360 | 0.55 / 0.30 / 0.81 | +33 ± 23, −4 ± 21 | +16, +16 (−0.030, −0.029) | 0.030 (paired, 1.5σ); 0.015 (even) | 529, 249 | 0.06 |
| fast@1, @2 (18) | 194 | 0.70 / 0.65 / 0.90 | +7.5 ± 3.8, −4 ± 12 | +13, +12 (−0.024, −0.022) | 0.012 | 36, 113 | 0.37 |
| portfolio@4 (28) | 307 | 1.00 / 1.00 / 1.00 | +0.76 ± 0.06, +0.91 ± 0.09 | +7.2, +7.4 (−0.0096, −0.0099) | 0.007 | 366, 294 | 0.03 |
| portfolio@3 (20) | 306 | 0.98 / 0.91 / 1.00 | +4.1 ± 1.4, +5.2 ± 0.6 | +23, +21 (−0.031, −0.028) | 0.021 | 362, 292 | 0.07 |
| portfolio@1, @2 (20) | 154 | 0.99 / 0.95 / 1.00 | +4.5 ± 0.8, +4.5 ± 0.5 | +15, +15 (−0.019, −0.020) | 0.014 | 36, 77 | 0.40 |
| research@3 (22) | 373 | 1.00 / 1.00 / 1.00 | −0.69 ± 0.17, −0.54 ± 0.12 | +1.5, +1.0 (−0.0015, −0.0010) | 0.0013 | 463, 516 | 0.003 |
| research@1, @2 (22) | 136 | 1.00 / 1.00 / 1.00 | −0.29 ± 0.06, −0.06 ± 0.07 | +1.5, +2.3 (−0.0014, −0.0023) | 0.0021 | 24, 68 | 0.06 |
| eso_turbulence@1 (28) | 364 | 1.00 / 1.00 / 1.00 | +0.72 ± 0.08, +0.94 ± 0.10 | +7.0, +7.4 (−0.0093, −0.0098) | 0.007 | 504, 367 | 0.02 |

How to read the table:

- **The two estimators bracket the effect.** The even part is the exact
  asymmetry bias in the measured mean slope, and every even window shows it.
  The paired closed-loop tilt is 2–10 times smaller (slightly negative for
  research). Two contributions are visible:
  1. The paired difference also contains changes of about 10⁻⁹ rad in the
     linear (odd) response between window sizes. The symmetric control
     `T(W−1) − T(W+1)` is of that size, for example −4×10⁻⁹ rad on fast@4.
  2. Probably, though not separately tested: the per-lenslet bias is not
     uniform (partial edge lenslets have broader spots). The DM then cancels
     part of the slope bias with shapes that carry mean slope (G-tilt) but no
     least-squares (Z-)tilt.

  The even-part value is therefore used as the conservative bound.
- **fast@1–3 gating.** With `min_valid_fraction = 1.0`, the clipping gate drops
  frames, and the dropped frames differ between window sizes. The paired
  values there are noisy upper bounds. The published 60-frame fast@3 run never
  closes, as its successor's rationale states, so the bias cannot act there at
  all.
- **Sign.** The even part is negative in every case, which predicts the
  positive tilt that the precise paired runs (fast@4, portfolio, eso) also
  show.
- **Why 2 m is benign when 42 m was not.**
  - The decisive factor is scale. The 42 m offset was 2.6×10⁻⁸ rad, which is
    0.037 px at 0.70 µrad per pixel and 0.5 λ/D at 2.2 µm. The science λ/D of
    a 2 m pupil is 21 times larger, while the WFS pixel scale is similar
    (0.54–1.0 µrad).
  - The worst 2 m offset (0.021 λ/D) lowers an Airy peak by about
    (π · 0.021)²/4 ≈ 1×10⁻³.

## 6. HCIPy: scaled analogue of the published sensor

The full published probe is not feasible on this desktop.
`ShackHartmannGeometry` stores one full-pupil boolean mask per retained lenslet,
about 1,850 × 384² B ≈ 270 MB and possibly twice that during validation. That
gives roughly 850 MiB raw, or 1.7 GiB required, above the current
1.05–1.1 GiB budget (NOT_RUN_RESOURCE_POLICY). The HCIPy closed loop is out of
reach on any desktop budget: `build_hcipy_deformable_mirror` keeps a dense
influence stack of up to 2401 × 384² × 8 B ≈ 2.8 GB plus a copy
(NOT_RUN_RESOURCE_POLICY; it needs another host and explicit user enabling).

### Analogue setup

`high_order_10m_hcipy@3` with only the pupil changed: 80 px and 10 lenslets on
D = 2.083 m. That keeps the published lenslet pitch (0.208 m), the 8-px block
window, pad 4 (λ/d = 4 px, 0.90 µrad pixels), the WFS wavelength (750 nm) and
d/r0 = 1.01. The geometry is built with the same `(N − 1)/n` convention, so
cells are 7.9 px wide and `δ_c` runs from +0.45 to −0.45 px (−0.48 px per
metre). The published sensor has the same ±0.45–0.49 px edge offsets at
−0.10 px per metre. The run used 76 lenslets, took 2.6 s and peaked at
185 MiB.

### Results

- **The flat reference follows the lenslet axis.** Its centroid moves 1.25 px
  per pixel of `δ_c`, so the spot sits on the lenslet axis, not the block
  centre.
- **Symmetric local defocus (even part).** The mean slope is ≤ 3×10⁻¹⁴ px at
  all amplitudes, so the tilt cancels. The focus-shaped gradient is
  `k = +0.0054, +0.021, +0.082, +0.33` px/m at 25, 50, 100 and 200 nm, and the
  outward edge-lenslet slope is +0.0014 to +0.082 px.
- **Closed-loop-like residual proxies.** Six von Kármán screens at r0 = 0.206 m
  (750 nm) were used with piston and least-squares tilt removed per lenslet,
  which keeps the intra-lenslet structure that broadens spots. That gives
  45–50 nm rms, and a second set was scaled ×0.5 (23–25 nm). In the even part:
  - the mean slope scatters around zero (−0.0075 … +0.0090 px)
  - the focus gradient is positive in all six screens: +0.034 … +0.050 px/m
    at full scale and +0.009 … +0.015 px/m at half scale
- **Mapped to the published geometry.** Using the fitted slope per pixel of
  axis offset (β = −0.06 to −0.13 at full scale, −0.014 to −0.035 at half
  scale) and the published δ gradient, the loop would hold this static focus:

  | Proxy amplitude | Predicted static Z4 (published sensor) | Mean |
  |---|---|---|
  | Full scale | −18 to −41 nm rms | −30 nm |
  | Half scale | −5 to −11 nm rms | −8 nm |

  The HCIPy profile's integrator has no leak, so it would hold the full value.
  30 nm rms of focus costs a Strehl factor of 0.993 at 2.2 µm, 0.987 at
  1.65 µm and 0.978 at 1.25 µm.

### Caveats

- This is an analogue, not the published system.
- The mapping assumes a bias linear in `δ` and a loop that fully cancels the
  focus pattern.
- The real closed-loop spot broadening may differ from the proxy. The DM
  partly corrects curvature across lenslets, while servo lag adds residual.
- Only a closed loop on a suitable host can confirm the held focus.

## 7. Recommendations (proposed, not applied)

1. **Native 2 m profiles (fast, portfolio, research, eso_turbulence): no
   action, no new profile version.**
   - The asymmetry is real and is now documented here.
   - The tilt it holds is ≤ 0.021 λ/D at 2.2 µm (even-part bound; 0.030 λ/D at
     1.5σ in the frame-dropping fast@3 paired run). That is 2.5–300 times
     smaller than the realization scatter of the residual tilt.
   - Changing `W` would move pinned hashes and governed baselines without a
     measurable science change.
2. **If a 2 m family is re-versioned for another reason, take an odd window at
   the same time.** Use the odd neighbour that keeps the clipping margin:
   fast 25, portfolio and eso_turbulence 29, research 23. The odd window
   removes the bias exactly (§4, §5), and `W + 1` had the highest usable-frame
   fraction of the three windows in every comparison above.
3. **Guard future profiles.** A cheap test could require an odd
   `detector_window_px` for native detector-level profiles published after
   this date, with the existing even-window profiles listed explicitly as
   grandfathered. The ESO SCAO v2 profiles already comply.
4. **HCIPy profile: likely worth a new version after confirmation.**
   - The predicted static focus (−8 to −30 nm rms) is a systematic modelling
     error caused by a 0.26% lenslet/pixel scale mismatch, not by the window
     setting. `W` must equal the block size for this backend.
   - Confirm it with a closed loop on a host that fits the dense DM.
   - Then fix the convention for the HCIPy backend only, as a new geometry
     convention used by a new `high_order_10m_hcipy@4`. Either place the cell
     edges on pixel edges, so lenslet centres fall at block centres, or set
     each lenslet's reference pixel at its true axis.
   - Either fix changes the HCIPy component hashes, so it cannot be a silent
     edit of @1–3. The shared geometry is also used by native profiles, so the
     change must not alter their geometry hashes.

## Files

- Probe scripts and per-job JSON/guard records are in the session scratchpad,
  not in the repository: `window_bias_probe.py`, `analyze_cl.py`,
  `even_part_probe.py`, `hcipy_window_probe.py` and `out/`.
- A hand-over note with their absolute paths is in the side-session notes
  folder.
