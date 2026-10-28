# AO Code Review

Read [the common contract](common_contract.md) for preservation,
outputs, execution policy, and authorization. When reviewing the original AO
Simulation repository, consult [project integration](project_integration.md)
for actual paths and contracts. For an isolated supplied fixture or another
project, use its own scope and instructions; original-repository access is not
required. Do not assume a particular revision.

## Establish review scope

- Identify the reviewed source/dirty state and requested scope: a diff plus
  necessary dependencies, selected components, or the whole repository.
- A diff review does not establish whole-repository coverage. For an audit,
  inventory unchanged implementations, supported modes, adapters, experiments,
  notebooks, and validation boundaries as well as recently changed code.
- Trace inputs through models, calibration, reconstruction, control, and science.
  Record each boundary's units, axes, IDs, support masks, state, and failure policy.
- Read governing tests and documentation as claims to verify, not an infallible
  oracle. Identify optional dependencies before selecting an executable check.
- Review by default: create only audit-owned reproductions and evidence. A
  finding does not authorize a repair, new dependency, baseline update, or refactor.

## Inspect array and state correctness

- Check named axis meanings and shapes before broadcasting or reduction: rows/y,
  columns/x, lenslets, wavelengths, time samples, and actuator coordinates.
  Singleton dimensions and square fixtures can conceal swapped axes.
- Inspect integer division, index ordering, boolean indexing copies, views,
  mutability, dtype promotion, complex-to-real conversion, and accumulated precision.
- Verify finite support separately from numeric values. Preserve NaNs plus
  validity masks, and intersect calibration, runtime-valid, and finite rows.
  Zero-filling invalid slopes or masking nonfinite illuminated pixels changes
  the measurement. Distinguish an optical zero-flux exception from dropout.
- Check lifecycle: persistent maps/masters, temporal draws, RNG scopes/keys,
  reset/replay, cached responses, controller queues, and applied-command feedback.
- Review conditioning, cancellation, overflow/underflow, and scale-aware error
  bounds. A numerically small residual in raw units may still be scientifically large.

## Review Fourier and optical conventions

- Verify FFT sign, normalization, transformed axes, shift order, centering, and
  odd/even-grid reference pixels against direct small transforms or tilt oracles.
- Check Parseval and flux conservation using the implemented sample-area and
  angular-area factors. Unit-sum normalization can hide a lost throughput factor.
- Keep OPD-to-phase wavelength conversion and DM surface/OPD factors explicit.
- Check angular grids, field extent, aliasing limits, crop denominators, and
  per-wavelength sampling. Same array indices do not guarantee a common angle.
- Exposure integration averages intensities; a mean phase/OPD or coherent field
  sum is a different model. Separate peak and on-axis image metrics.

## Review sparse calibration and solvers

- Look for hidden large densification through conversions, broadcasting, probe
  stacks, full-pupil masks, factorization caches, or hashing/copying intermediates.
  A tiny dense independent oracle is useful; a full dense reference need not fit.
- Estimate CSR bytes from values, index dtype, and row pointers: approximately
  `value_bytes*nnz + index_bytes*nnz + index_bytes*(n_rows+1)`; include simultaneous
  work arrays and copies. A byte estimate is not measured process RSS.
- Verify operator dimensions, row/actuator identities, adjoints, null modes,
  rank/coverage gates, and grouped calibration's locality/noiseless prerequisites.
- Compare mathematical objectives and damping units before comparing parameters.
  Absolute dense Tikhonov and relative sparse damping are not interchangeable.
- Recompute small solver residuals/objectives independently; inspect scaling,
  conditioning, tolerances, stopping codes, and nonconvergence handling.
  A successful solver exit alone does not establish a useful scientific estimate.

## Confirm findings and report

- Follow the common contract's active-research loop for substantive findings:
  search and read the relevant algorithm papers or official library documentation,
  then verify whether they support the diagnosis in this implementation.
- Build the smallest adversarial reproduction that reaches a supported failure:
  use unequal axes, partial masks, boundary values, heterogeneous maps, or a tiny
  ill-conditioned system as appropriate. Do not merely repeat the suspect formula.
- Execute requested feasible confirmations under the common contract; use a
  bounded pilot and serialized two-thread numerical jobs. Do not infer permission
  for scale runs from review scope. Save exact commands, inputs, imports, and output.
- For each actionable finding provide priority, current file/line/function,
  trigger, expected/actual behavior, independent evidence, affected scientific
  claim, and the smallest proposed correction/check. Distinguish introduced
  regressions, pre-existing defects, documentation errors, and evidence gaps.
- A missing capability, accurately disclosed approximation, or failed scientific
  hypothesis is not by itself a code bug. Passing regression tests is not hardware
  validation. Do not invent findings or hide a supported defect as future work.
- A clean review is valid: state no actionable findings and give inspected,
  executed, unavailable, and unreviewed coverage. Keep proposals separate from
  changes actually made; stop at the review handoff unless repair was authorized.
