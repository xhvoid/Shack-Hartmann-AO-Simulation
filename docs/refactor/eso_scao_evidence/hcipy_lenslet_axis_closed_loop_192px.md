# HCIPy lenslet axis: closed-loop scan at 192 px

Date: 2026-10-15. Status: evidence only. No published profile, pinned hash or
governed baseline was changed.

This note keeps the closed-loop results behind AO-REF-016A
(`docs/refactor/AO_REF_016A_HCIPY_LENSLET_AXIS.md`). They were measured in a
hosted cloud session (4 vCPU, 16 GB) on `origin/hcipy-lenslet-axis-confirmation`
at 9352f6c. The raw JSON and scripts sat in that session's `/tmp` scratchpad,
which does not outlive the session. The tables below are the record.

## 1. Summary

- **The published 10 m @3 loops cannot hold lock, so the paired confirmation in
  AO-REF-016A §6 cannot run as written.**
  - **Gain.** Gain 0.65 with `latency_frames: 2` is above the integrator
    stability limit of 0.618 (z³ − z² + g = 0). The pole radius is 1.0147 at
    0.65, against 0.813 at gain 0.30 and 0.941 at 0.50.
    `high_order_10m_geometric@3` has the same gain and latency.
  - **Window.** The HCIPy sensor's 8 px window is only 2 λ/d at pad 4. It clips
    the broadened spots, validity gating drops below `min_valid_fraction`, and
    the DM freezes.
- **Full scale, @3, realization 0:** the residual is 1589 nm rms with −659 nm
  of Z4, close to open loop. The geometric @3 at the 192-px grid diverges to
  16.6 µm (20% DM saturation) at gain 0.65 and locks at 0.5 (≈ 100 nm,
  0.10× open loop, Z4 +4.3 ± 3.3 nm).
- **At 192 px, pad 2 and gain 0.30 lock both lenslet conventions on two
  atmosphere realizations.** Pad 2 is a 4 λ/d window; leak 0, rcond 0.02,
  clipping 0.15 and minimum-valid 0.75 stay as in @3.
  - **The block-centred axis removes the held focus:** Z4 −1.1 ± 3.6 and
    +0.1 ± 4.7 nm, against −53.3 ± 3.3 and −51.2 ± 4.7 nm for the published
    cell-centred axis.
  - **The paired Z4 (block − cell)** is +52.2 ± 4.9 nm (realization 0) and
    +51.3 ± 6.6 nm (realization 1), or +51.9 ± 3.9 nm combined. The sign is
    the predicted one.
  - 52 nm of focus costs a Strehl factor of 0.978, 0.962 and 0.934 at 2.2, 1.65
    and 1.25 µm.
- **When it locks, the block-centred axis holds |Z4| ≤ 3.3 nm in every
  configuration tried.** The published axis holds −6 to −53 nm, depending on
  pad, leak and TSVD cutoff (§4).
- **The magnitude test in AO-REF-016A §6 ("consistent with −8 to −30 nm")
  should be dropped before a full-scale run** (§5).

## 2. Setup

- `high_order_10m_hcipy@3` and `high_order_10m_geometric@3`, with only the
  pupil reduced: 192 px, 24 lenslets, D = 5.0 m. This keeps the published pitch
  (0.208 m), the 8 px blocks, the 750 nm WFS wavelength, r0, L0 and wind.
- Grid size:
  - At this size δ runs ±0.48 px, a gradient of −0.20 px/m.
  - The published 384 px / 48-lenslet sensor has the same ±0.49 px range, at
    −0.10 px/m.
- The two conventions:
  - **cell:** the published axis (`(N − 1)/n` cell centres);
  - **block:** `wfs.lenslet_axis = "pixel_block_center"` (9352f6c).
- Run settings:
  - 300 frames with burn-in 50; Z4 is the mean over frames 50–300, with
    standard errors.
  - Open loop is 840.07 nm (realization 0) and 1594.77 nm (realization 1).
  - No run saturated the DM.
- **Lock** means two things (the cloud run's criterion):
  - the rms over frames 200–300 is within 10% of frames 50–150 ("late/early");
  - every frame is usable.

## 3. Results

### Pad 4 (published sampling)

- **No setting locked both conventions.** Gains, `max_window_clipping_fraction`
  0.15/0.25/0.35 and several `min_valid_fraction` values were scanned.
- **Residual:** the floor sits at 260–480 nm, and it grows.
- **Paired Z4:** +104 to +301 nm. These loops were unlocked, so the values are
  only a preview.

### Pad 3 and pad 2 (realization 0)

| Pad | Gain | Axis | Min valid | Frames 50–150 | Frames 200–300 | Late/early | Mean/open | Z4 | Lock |
|---|---|---|---|---|---|---|---|---|---|
| 3 | 0.30 | cell | 0.879 | 298 nm | 489 nm | 1.64 | 0.45 | −21.3 ± 8.2 nm | no |
| 3 | 0.30 | block | 0.886 | 272 nm | 372 nm | 1.37 | 0.38 | +8.4 ± 8.7 nm | no |
| 3 | 0.40 | cell | 0.853 | 462 nm | 857 nm | 1.85 | 0.80 | −59.4 ± 12.3 nm | no |
| 3 | 0.40 | block | 0.846 | 409 nm | 569 nm | 1.39 | 0.56 | +59.2 ± 10.6 nm | no |
| 3 | 0.50 | cell | 0.833 | 625 nm | 976 nm | 1.56 | 0.96 | −132.2 ± 16.0 nm | no |
| 3 | 0.50 | block | 0.837 | 436 nm | 616 nm | 1.41 | 0.63 | +63.4 ± 8.7 nm | no |
| 2 | 0.30 | cell | 1.000 | 136 nm | 137 nm | 1.01 | 0.16 | −53.3 ± 3.3 nm | yes |
| 2 | 0.30 | block | 0.975 | 135 nm | 147 nm | 1.09 | 0.17 | −1.1 ± 3.6 nm | yes |
| 2 | 0.40 | cell | 0.998 | 137 nm | 135 nm | 0.99 | 0.16 | −51.8 ± 2.5 nm | yes |
| 2 | 0.40 | block | 0.958 | 170 nm | 198 nm | 1.16 | 0.22 | +5.6 ± 2.1 nm | no |
| 2 | 0.50 | cell | 0.993 | 156 nm | 152 nm | 0.98 | 0.18 | −54.1 ± 1.9 nm | yes |
| 2 | 0.50 | block | 0.946 | 330 nm | 436 nm | 1.32 | 0.46 | −1.3 ± 2.7 nm | no |

Every run was fully usable. The paired Z4 (block − cell), by gain 0.30 / 0.40 /
0.50:

- pad 3: +29.7 ± 12.0, +118.6 ± 16.2 and +195.6 ± 18.3 nm;
- pad 2: +52.2 ± 4.9, +57.4 ± 3.3 and +52.8 ± 3.4 nm.

Only pad 2 at gain 0.30 compares two locked loops.

### Realization 1, pad 2, gain 0.30

| Axis | Min valid | Frames 50–150 | Frames 200–300 | Z4 |
|---|---|---|---|---|
| cell | 0.998 | 126 nm | 137 nm | −51.2 ± 4.7 nm |
| block | 0.973 | 140 nm | 136 nm | +0.1 ± 4.7 nm |

The paired Z4 is +51.3 ± 6.6 nm.

### Leak and TSVD cutoff (pad 3, gain 0.30, realization 0)

Each convention was calibrated once, then reused for every variant.

| Leak | rcond | Cell late/early | Cell mean/open | Cell Z4 | Block late/early | Block mean/open | Block Z4 | Both lock | Paired Z4 |
|---|---|---|---|---|---|---|---|---|---|
| 0 | 0.02 | 1.64 | 0.45 | −21.3 ± 8.2 nm | 1.37 | 0.38 | +8.4 ± 8.7 nm | no | +29.7 ± 12.0 nm |
| 0.01 | 0.02 | 0.97 | 0.32 | −32.5 ± 3.8 nm | 1.15 | 0.24 | +3.8 ± 5.0 nm | no | +36.3 ± 6.3 nm |
| 0.02 | 0.02 | 0.86 | 0.28 | −28.0 ± 6.5 nm | 1.06 | 0.22 | −2.2 ± 4.7 nm | yes | +25.8 ± 8.0 nm |
| 0 | 0.05 | 1.10 | 0.18 | −5.7 ± 3.3 nm | 1.09 | 0.18 | −1.0 ± 3.2 nm | yes (limit) | +4.7 ± 4.6 nm |
| 0.02 | 0.05 | 1.07 | 0.17 | −8.3 ± 3.9 nm | 1.08 | 0.18 | −1.4 ± 3.8 nm | yes | +6.9 ± 5.4 nm |

At pad 2, gain 0.30 with leak 0.02, both conventions lock:

- cell: 138 → 145 nm, Z4 −48.7 ± 3.7 nm;
- block: 135 → 137 nm, Z4 −3.3 ± 3.7 nm;
- paired: +45.4 ± 5.2 nm.

### Mode diagnostic

The 541-mode interaction matrix has 24 (cell) and 22 (block) modes below
s/s_max = 0.02 at pad 3, and 50 and 46 below 0.05.

- **Pad 3 without a leak.** The DM command grows:
  - cell 742 → 837 → 970 nm, block 711 → 747 → 791 nm, at frames 100, 200 and
    300.
  - The weakest 10% of modes carry 24–25% of the command change from frame
    100 to 300.
  - Most of the fastest-growing modes are weakly sensed (s/s_max 0.01–0.05) edge modes,
    with 70–99% of their energy on edge actuators, which are 31% of all
    actuators. None is a waffle mode (checkerboard correlation ≤ 0.08).
- **Pad 3 with leak 0.02.** The command stays flat, and the cell axis's leading
  drift modes collapse. Some block-axis edge modes still swing without raising
  the residual, because those actuators sit mostly outside the pupil.
- **Pad 2.** There is no steady growth, even without a leak.

## 4. Interpretation

- **The defect and the fix are confirmed in a locked closed loop at 192 px.**
  - The published axis holds negative focus.
  - The block-centred axis holds none.
  - The paired difference is about 13σ from zero, and it repeats on a second
    realization.
- **The held focus depends on the configuration, not only on the axis offset.**
  - **Residual.** At pad 3 the paired Z4 grows with the residual (gain
    0.30 → 0.50). At pad 2 the residual stays flat, and so does the paired Z4.
    This fits the mechanism in `published_profile_window_bias.md` §6: the
    window clips a broadened spot asymmetrically about the axis, so the bias
    grows with spot broadening.
  - **TSVD cutoff.** At a similar residual, rcond 0.05 cuts the held focus at
    pad 3 from ≈ 26–30 nm to ≈ 5–7 nm.
    - Our reading, not tested: the bias slopes are largest at the edge
      lenslets.
    - So the way the reconstructor treats weakly sensed edge modes changes how
      much of the bias becomes DM focus.
- **The −8 to −30 nm prediction is not a usable acceptance band.**
  - **The proxy was too small.** The prediction used 23–50 nm rms proxy
    residuals at pad 4. The loops that lock have ≈ 135 nm residuals.
  - **The full scale has a larger lever arm.** At full scale the δ gradient
    times D² is about 2× the 192-px value.
  - **A rough scaling, not a measurement:** if the per-pixel bias stayed the
    same, a full-scale pad-2 / gain-0.30 cell-axis loop would hold about
    −100 nm.
- **The block axis has the thinner stability margin at pad 2.**
  - It loses lock at gain 0.40, where the cell axis still holds.
  - Its minimum valid fraction is lower (0.946–0.975 against 0.993–1.000).
  - The cause is not known. Leak 0.02 restores its margin (late/early 1.01) and
    lowers the paired Z4 by ≈ 7 nm.

## 5. Implications for AO-REF-016A (proposed, not applied)

1. **Draft `@4` cannot be "@3 with only the axis changed".** That draft cannot
   hold lock. The smallest change that locks both axes at 192 px is:
   - `wfs.pad_factor` 4 → 2;
   - `controller.gain` 0.65 → 0.30.

   Confirm it at full scale as a pair that differs only in
   `wfs.lenslet_axis`:
   - a cell-axis twin with the same pad and gain, run as a configuration
     override, not a profile;
   - draft `@4`.

   `test_draft_high_order_10m_hcipy_v4_is_v3_with_only_block_centred_axes`
   would then need to change: it pins "only the WFS identity differs", and the
   gain is a controller setting.

   If the block axis drifts at full scale, the fallback is leak 0.02.
2. **Acceptance criteria.**
   - Keep:
     - the sign, with the paired difference outside 2 standard errors;
     - `@4` Z4 within its realization scatter of zero;
     - `@4`'s residual no worse than the cell twin's.
   - Replace the "−8 to −30 nm" band: report the measured value instead.
3. **The geometric 10 m family has the same gain problem.** At 192 px it locks
   at gain 0.5, and that fix belongs in its own re-version.
   `tests/control/test_profile_stability.py` now checks every published
   profile's loop poles. The leak-free limit is 2 sin(π / (2(2L + 1))), and
   the two @3 profiles are strict xfails.

## 6. Memory of the full-scale build (da189f3)

The memory fix (da189f3) and the lenslet-axis test revision (394d175) were
applied together to 9352f6c in the cloud and checked there. The fix streams
array hashing, shares immutable influence stacks, and streams the calibration
probe-map digests.

- **Full suite:** 2147 passed, 27 skipped, 2 xfailed.
  - The one failure is environmental: the cloud venv has no build backend for
    `test_pep660_editable_install_generates_resource_alias_only_in_environment`.
  - The gated lenslet-axis test: 1 passed, 1 xfailed.
- **mypy and ruff:**
  - mypy on Linux shows only the known `resource_guard.py:349` error.
  - mypy on macOS is clean.
  - ruff is clean.
- **`build_scao_system(high_order_10m_hcipy@3)`, full scale, no loop:**

  | Code | Peak |
  |---|---|
  | Unpatched | killed above 13.3 GiB |
  | The cloud session's own fix | 8.03 GiB |
  | This fix | 5.70 GiB (5,978,864 KiB) |

  - The DM build was finished 3 minutes in, peaking at 5.63 GiB.
  - Calibration then ran steady at 5.43 GiB, for 2842 s in all.
- **Identity:**
  - `config_hash` `bc73f30b8d37a1dcc5603f8d2007d9e69daf02e54ced8898eef53afb7153e65c`
    equals the pinned @3 hash.
  - The interaction matrix is 3608 × 2125.
  - At 192 px, every component hash matched the unpatched tree.
  - At full scale, the unpatched code cannot build on that host, so its
    component hashes could not be compared.
