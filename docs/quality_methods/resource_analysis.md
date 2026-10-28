# Memory and runtime analysis

Read the [shared contract](common_contract.md). Determine
whether the user wants an analytic estimate, a bounded measurement, or a study
plan. Do not launch an expensive run merely to answer an estimate question.

## Define a matched scenario

Record revision, hardware/OS, dependency/native libraries, backend, threads,
profile, pupil/focal grids, lenslets, active actuators, sparse nnz, wavelengths,
quadrature, layers/bands, frames/burn-in, telemetry, histories, calibration reuse,
and science options. Compare like observables and timing boundaries.

## Account for allocations

- Use actual shapes/dtypes and ownership. A float64 plane costs `8*Nx*Ny`
  bytes and a complex128 plane `16*Nx*Ny`; real/complex temporary buffers and
  FFT workspaces can change the peak.
- Dense float64 interaction storage costs `8*R*A` bytes before copies,
  factorization, and workspaces. CSR storage is value bytes plus index bytes
  plus row-pointer bytes; use actual integer widths and nnz. Inspect hidden
  densification rather than inferring sparse memory from the public type.
- Account separately for materialized atmospheric layers/bands versus
  regeneration, batched lenslet/pixel/wavelength buffers, caches, calibration
  state, and science images. Derive formulas from actual lifetimes.
- One retained float64 command history costs `8*F*A`; count each actual history.
  Streaming a PSF does not make the whole simulation constant-memory in frames.
- Include simultaneous paired systems, retained residual samples, output
  aggregation, Python references, and transient old/new system overlap.
- Separate process RSS, virtual memory, Python heap, native arrays/workspaces,
  caches, OS pressure, and whole-machine headroom. Do not equate tracemalloc
  alone with process memory or one historical peak with minimum machine RAM.

## Measure only when requested and authorized

Choose bounded representative fixtures. Use fresh processes for per-run peak
RSS where feasible; report units/platform semantics. Predeclare warmup, cache
state, repeats, and useful spread; short measurements usually warrant at least
three repeats unless cost justifies fewer.

Make timing boundaries mutually exclusive. If construction includes calibration,
do not add calibration again. If loop time includes science, do not add science
again. Separate wall time, CPU time, build, calibration, loop, and reporting.
Investigate repeatable material regressions using the repository's objectives;
do not tune physics or accept noisy timing as a unit-test oracle.

For ensembles distinguish serial reuse, fresh-process serial execution, and
concurrent workers. Conditional estimates may use `Tbuild + F*Tframe` and
worker-memory sums with shared overhead/headroom, while explaining cache,
bandwidth, threading, and oversubscription limits. No untested linear speedup.

## Deliver

Use a scenario table and allocation formulas, labeling `MEASURED_CURRENT`,
`MEASURED_HISTORICAL`, `ANALYTIC_ESTIMATE`, `EXTRAPOLATED`, or `NOT_MEASURED`.
Explain whether memory or compute appears limiting and what evidence supports
that assessment. Recommend bounded follow-up measurements with concrete costs.
Use [report fields](evidence_and_reporting.md) and, where
applicable, [project integration](project_integration.md).
