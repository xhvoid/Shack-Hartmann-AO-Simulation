# Reading the older results alongside the component checks

Updated 2 November 2026. This is an interpretation note, based on existing records.
The original values, source revisions and failed checks remain unchanged.
The appendix labels R1–R8 identify groups of historical records, not eight
stages of a current validation programme.

## Shared reconstruction in backend comparisons

The native and HCIPy comparison used different optical components but shared
the dense reconstructor. Agreement checks the differing optical components.
The 52 criteria-bearing metrics describe one small fixture at its original revision.

The later precision repair applies to least squares, TSVD and Tikhonov in
the common dense kernel. The tutorial TSVD example has a low retained
condition number (about 3.2), which suggests low numerical risk, but its
trajectory was not rerun with the repaired kernel. See the
[component verification summary](https://github.com/xhvoid/Shack-Hartmann-AO-Simulation/blob/c42fe87a88f8f2dc97cedfacec791f5624950a3a/docs/verification-summary.md)
for the repair, numerical bounds and remaining limits. The traced 42 m
producers use a different path; that statement is specific to those sources.

## Which sampling studies are complete?

The appendix's statement that detector-level convergence studies were
prepared but not run describes its earlier source record. Later 42 m
studies did run:

| Recorded comparison | Result within that study |
| --- | --- |
| Detector sampling and spectral nodes (E2a) | The finest changes in residual RMS, Strehl and both EE50 definitions converged under the stated tolerances, with three realization pairs. |
| Exposure quadrature (E2b) | The finest midpoint comparison converged for all four metrics, with three realization pairs. |
| Science-image padding (E2b, including its extension) | With six realization pairs, residual RMS, Strehl and Fourier-reference EE50 converged. Production EE50 remained **unconverged**, final for that stage. |

For production EE50 at padding 3 → 4, the recorded shift was −1.1275 mas,
with a 95% interval [−1.4037, −0.8512] mas, outside the ±0.6326 mas band.
Stability of the Fourier reference does not turn the production estimator
into a converged one. These are 42 m results from their frozen configurations;
they do not complete the separate 12 m detector-level study or validate
hardware. The full run logs remain in the research archive, not this page.

## What later checks did not resolve

- The earlier command-space failures T1c/T4 remain failures. The historical
  outcome I remains unresolved; later pupil-space bounds have narrower scope.
- The static detector-noise calculation (C1) selected damping 0.0025 against
  0.001. Its approximately 0.0042 nm predicted benefit is one noise component,
  not a measured closed-loop improvement. It did not trigger the proposed
  closed-loop damping comparison (C3).
- The R1 x covariance comparison remains inconclusive. Low correlation or
  an interval containing zero is not a demonstration of independence or
  equivalence.
- Component checks cover the fixtures, equations and recorded versions
  described in their reports. No telescope data or hardware calibration was
  added by this documentation update.

## How to read the downloads

Most downloads are unchanged historical files. Two are explicitly marked
public copies: one omits a workstation directory from the command path; the
other omits a temporary branch label. Each names its original SHA-256,
historical source and edited field. Scientific values and other provenance
fields are unchanged. The originals remain available; an edited copy is
not presented as having the original hash.

The gain-study methods also have a [current reading copy](gain-study-notes.md)
and [wording corrections](gain-study-corrections.md). The original methods
inside the frozen study bundle retain their bytes and hashes.
