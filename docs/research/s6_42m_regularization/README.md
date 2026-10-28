# S6: is the 42 m profile under-regularized? Current status

Status as of **2026-10-26**, after the static C1 noise step and its review. Roadmap item
[S6](../../roadmap.md#s6-status-after-c1-2026-10-26); limitation [LIM-17](../../current_limitations.md).

The evidence for this page is private: it lives on the `s6/*` evidence branches of the transfer repository
`ao-p3-transfer`, produced on the frozen producer `98e10278f957c630cf44942b9d02b7a8c66e2988` (not a commit of this
repository; `src/` and `configs/` are identical to `main` at `3ce386f`). Numbers below are copied from those records;
the full claims ledger, with source hashes and record pointers, is part of the same private export.

## Current answer

> Under the frozen static covariance and stationary linear-loop model at 10⁵ detected electrons per fully illuminated
> subaperture per frame, the selected admissible comparator does not meet the C1 material-benefit trigger. C3 is
> therefore not triggered by this evaluation. Total closed-loop response and other operating conditions remain
> unmeasured.

- Production damping remains **α 0.001** for `det_ccd_42m_r3band_derived@1`; no profile version is proposed.
- Broader S6 adequacy remains **open**.

## What was done

| Step | Result | Kind |
| --- | --- | --- |
| N11 (12 m @2 anchor, 12 m-derived geometry with 42 m sensor physics) | outcome I; original T1c (full-command solver accuracy) fails | static diagnostic |
| N12 (k4, 5 m geometry, trend) | combined I; T4 fails (α 0.1 halves tip/tilt one-shot gain at 12 m); original progression gate not passed | static diagnostic |
| N13 (42 m, attempt-01) | `UNQUALIFIED` (mis-normalized fill check) | static diagnostic |
| N14 (42 m, attempt-02) | `QUALIFIED_PASS` under a separately declared prospective pupil-space protocol; weaker normalized sensing tail; seven modes flagged by the static screen; original command-space criterion fails 12 of 42 | static diagnostic |
| C1 / N15 (42 m) | `QUALIFIED_BELOW_C1_TRIGGER` | static noise prediction |

C1, in numbers (static stationary-loop predictions with the full cross-modal covariance):

| | α 0.001 (production) | α 0.0025 (selected comparator) |
| --- | --- | --- |
| Stationary detector-noise component, variance | 1.2351 nm² | 1.2257 nm² |
| Stationary detector-noise component, RMS | 1.1113 nm | 1.1071 nm |
| Tip / tilt / defocus nominal one-shot gain | 0.99866 / 0.99866 / 0.99984 | 0.99171 / 0.99171 / 0.99897 |

- The 0.0042 nm difference of the two component predictions (0.76 % in variance) is far below the frozen triggers
  (≥ 1.0 nm and ≥ 10 %, guards 0.001 nm and 0.001). It is not a change in total closed-loop residual, not the RMS
  of a paired difference and not an estimate of what a closed-loop comparison (C3) would measure.
- α 0.0025 is the largest grid value whose tip, tilt and defocus gains stay within [0.99, 1.01]; the admissible set
  was {0.0015, 0.002, 0.0025}, and only α 0.0025 received full noise propagation.
- The comparator's production solver qualified against two independent references under the prospective
  pupil-space criteria (A 26/26, B 16/16). The original command-space criterion fails 3 of 42 at the comparator.
- The seven flagged modes carry about 36 % of the component variance; 61 % of the small variance difference lies
  within them. This attribution is non-additive and never replaces the complete totals.
- The 42 saved inputs are 25 probes, 1 screen and 16 unit-noise vectors (the frozen protocol's "26 probes" is
  corrected by an erratum; criterion A covers the 25 probes and the screen).

## Limits

- **Model-conditional.** `detector_covariance_v2` at a flat wavefront with fixed camera maps and calibration
  products; inter-lenslet independence; persistent calibration bias excluded; stationary linear loop (gain 0.3,
  latency 2, leak 0) with temporally white modal noise; no atmosphere dynamics, nonlinearity or mask changes.
- **Numerical, not statistical.** Independent numerical paths agree to about 1e-13 (an empirical consistency
  indicator, not a certified error bound). The calculation is deterministic for one configuration (seed 1,
  realization 0, k2) and supplies no statistical interval.
- **Unmeasured.** Closed-loop behaviour under noise; other photon budgets, realizations, detector settings and
  masks; α 0.0015 and 0.002; dampings outside the grid.

## Unchanged historical conclusions

The original T1c and T4 failures; N11 outcome I and N12 combined I; the original progression gate not passed; N13
attempt-01 `UNQUALIFIED`; N14 attempt-02 `QUALIFIED_PASS` under its own prospective protocol; the three original
command-space failures at the C1 comparator. C1 does not revise any of them.
