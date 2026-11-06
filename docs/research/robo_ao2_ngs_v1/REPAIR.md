# NGS v2: loss-of-lock diagnosis and control repair

The first v1 run lost reconstruction at 0.981333 s. The saved slope
measurements and DM commands trace the loss to the response to rejected
lenslets. The trajectory is archived under
`outputs/robo_ao2_ngs/20261024-first-trajectory` in the development archive.

## Established mechanism

At frame 736 (zero based), only 278 of 374 calibrated slope rows are usable:
74.33%, below the unchanged 75% threshold. Rejection is correct under that
policy. With zero leak, no recovery supervisor and a two-frame delay, the
remaining queued updates are applied through frame 737, after which the DM
holds its shape indefinitely while rejection continues.

The earlier trigger is a spatially masked inverse problem. The full calibration
is not severely ill-conditioned: its smallest/largest singular-value ratio is
0.0735125, and v1's TSVD cutoff 0.001 removes no full-support mode. Once
lenslets are rejected, the current row mask can create much weaker response
modes. At frame 732 the retained inverse condition reaches 900.74 and the
reconstructed increment norm reaches 45.82 µm OPD in actuator coordinates.
This norm is not the stroke of one actuator. Removing modes below a relative
singular value of 0.05 from that saved increment removes 98.43% of its squared
norm. At frame 735 the corresponding fraction is 99.32%.

Selected noiseless measurements of the saved residuals reproduce all their
effective row counts. Loss of peak SNR starts before window clipping and
centroid-uncertainty rejection spread; no detector pixels are saturated in
the checked states. These are model-predicted quality gates, not solely a
bad random camera draw. At saved times 736, 800 and 1499, replacing the held
DM correction with a flat DM restores 100% of the calibrated rows for the
same atmosphere in the deterministic check. Thus the persistent low validity
is maintained by the held correction, not an intrinsically unmeasurable
atmosphere at those times.

The evidence supports the chain: lenslet rejection → weakly constrained
masked inversion → excessive increments → DM clipping and further degraded
spots → reconstruction rejection → held saturated DM. It does not identify
the first noisy lenslet fluctuation as a unique cause or imply that all
Shack–Hartmann losses of lock have this mechanism.

## Explicit changes and assumptions

`robo_ao2_22m_ngs_draft@2` keeps all v1 physical values, including gain 0.4,
750 Hz sampling, two-frame latency, ±3.5 µm model OPD limit, photon budget,
atmosphere, seed, pupil and DM geometry. Only these runtime settings change:

| Field | v1 | v2 | Status and rationale |
|---|---:|---:|---|
| `reconstructor.rcond` | 0.001 | 0.05 | Local engineering assumption. Bounds retained relative inverse sensitivity by 20 instead of 1000; retains all 197 modes under the full calibration mask. Applied again to each runtime mask. |
| `controller.recovery.rejected_frames_before_decay` | Absent | 3 | Local safety assumption. Allows the two-frame queue to drain before decay begins on the fourth consecutive rejected frame. |
| `controller.recovery.decay_per_rejected_frame` | Absent | 0.05 | Local safety assumption. Decays the requested shape by 5% on each subsequent rejected frame. |
| Fallback reconstruction / gain schedule | Absent | Disabled | No relaxed validity criterion or alternate low-coverage reconstruction. |

These are not published Robo-AO-2 operating settings or a fitted optimum.
The literature's NGS simulation uses regularized zonal least squares; v2
remains the project's TSVD approximation. All other missing-data assumptions
in [PARAMETERS.md](PARAMETERS.md) and [parameter-ledger.json](parameter-ledger.json)
continue to apply. The original draft, old results and original 2 m baseline
are retained for comparison. No global reconstruction/controller default is
changed.

## Validation protocol

Use one 1500-frame v2 realization, requiring all 1500 atmosphere frames to
match saved v1 bytes and all calibration arrays to match exactly. Keep the
same 0.2–1.0 s primary window against saved 2 m data and 0.2–2.0 s window
against v1. Save invalid frames, commands, boundary occupancy, recovery
activation counts and per-gate rejection counts. A dormant recovery policy
would distinguish preventive regularization from recovery-driven success.
No original 2 m or 42 m trajectory is rerun. Three focused local checks of
TSVD behavior and rejection decay passed.

The frozen plan, diagnostic arrays and final validation evidence are in the
development archive (`outputs/robo_ao2_ngs/20261024-loss-of-lock-repair/`,
not part of this repository). A successful two-second,
single-seed run is evidence for this repair on this input, not long-duration
stability or hardware validation.

## Observed validation result

The v2 validation completed all 1500 frames with zero unusable reconstructions,
zero newly clipped commands and zero applied boundary occupancy. Neither
rejection decay nor fallback activated. All 1500 atmospheric maps were
bitwise identical to v1; calibration arrays were identical. The first 92
applied-command frames were also identical. Thus the improvement in this
realization comes from the preventive TSVD cutoff, not an activated recovery
policy. The minimum usable-row fraction over the run was 89.30%.

Over [0.2, 2.0) s, H Strehl mean/SD changes from 0.381474/0.316777 in v1
to 0.750226/0.069065 in v2. Over [0.2, 1.0) s, v2 gives 0.737504/0.077765
versus 0.575890/0.081746 in the saved original 2 m baseline. These remain
different physical scenarios; the latter comparison is not a stroke-only
experiment. Full frame-level data and saturation definitions are in the repair report
of that archive.

## Primary sources and applicability

- [Zhang et al. (2024), §3.1](https://arxiv.org/html/2407.14677v1): published
  Robo-AO-2 simulation settings and regularized zonal least squares for NGS.
  It does not supply the local TSVD cutoff or rejection-decay parameters.
- [Booth, Calibration and Closed-Loop Control, equations 12–14](https://aomicroscopy.org/calibration-and-closed-loop-control-of-deformable-mirrors-using-direct-sensing):
  inverse singular values amplify weak modes; mode rejection limits excessive
  control signals. Applicable to the numerical mechanism, not instrument
  validation or a recommended universal cutoff.
- [Bitenc et al. (2015), §4.1](https://academic.oup.com/mnras/article/448/2/1199/1048477):
  demonstrates that instability and saturation can depend on reconstructor,
  partial illumination and coupling; leak stabilizes their CuReD example.
  Their reconstructor differs from this one, so that paper does not prove
  a waffle-mode diagnosis here or prescribe our recovery settings.

Research questions were whether the published NGS inverse was regularized,
whether a changing row mask can amplify poorly sensed modes, and whether
holding a rejected correction constitutes recovery. Relevant source sections
above were read and checked against saved-array SVD, queue behavior and
deterministic fixed-state counterfactuals. The algorithmic distinction is
resolved; long-duration and multi-seed robustness remain untested.

Searches included `adaptive optics Shack Hartmann truncated singular values
weakly sensed modes closed loop instability actuator waffle modes` and
`Robo AO 2 natural guide star 750 Hz gain 0.4 wavefront sensor 16 16`.
The modal analysis did not establish a waffle-mode-specific diagnosis, so
the finding is stated in terms of the measured masked singular spectrum.
