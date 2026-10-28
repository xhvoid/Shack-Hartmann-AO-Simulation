---
name: ao-numerical-verification
description: Verify adaptive-optics numerical implementations with independent oracles, convergence studies, and statistical checks. Use for requested numerical testing or verification; distinguish implementation accuracy from physical or hardware validation.
argument-hint: "[implementation or numerical claim to verify]"
---

# AO Numerical Verification

Read [the common contract](../../references/common-contract.md) before execution.
When working in the original AO Simulation repository, use
[project integration](../../references/project-integration.md) to locate its
environment, tests, selectors, and resource controls. An isolated fixture or
another project uses its own supplied scope and instructions; original-project
access is not required.

## Establish and execute the check

- Identify the claim, supported configuration, units, array layouts, estimator,
  and expected limiting behavior before choosing an oracle.
- Plan and execute the requested feasible checks; a test plan alone does not
  satisfy a request to verify. Honor an explicit planning-only request.
- Put new oracles, reproductions, logs, and figures in caller-owned audit output.
  Do not modify existing source, tests, configurations, or accepted resources as
  part of verification. Record proposed repairs separately.
- Record source/dirty identity, import origin, environment, seeds, commands,
  parameters, tolerance rationale, exit status, and observed results.
- Pilot an unfamiliar workload at a bounded size before scaling. Apply the
  common contract's serial, two-thread policy and live resource authorization;
  a small pilot does not authorize a telescope-scale run.

## Choose independent evidence

- Prefer analytic limits and direct small calculations: zero/piston/tilt fields,
  diffraction scales, Parseval flux, known linear DM sums, finite differences,
  and independently evaluated reconstruction objectives.
- Use property and metamorphic checks only inside their assumptions. Piston
  invariance, axis exchange, flux rescaling, or wavelength rescaling may fail
  legitimately with clipping, asymmetric pupils, fixed detector scales, noise,
  or different choices of fixed OPD versus fixed phase.
- Check supported boundary cases: partial illumination, invalid rows, zero flux,
  ADC on/off, fixed detector maps, saturation, and rejected reconstruction.
- Separate an independent oracle from dense/batched agreement, backend agreement,
  and fixed-seed regression. Shared code or assumptions can share an error.
- Choose tolerances from units, conditioning, discretization, and sampling error;
  default absolute tolerances can hide large errors in metre-valued OPD.

## Isolate numerical convergence

Vary one discretization at a time and record what remains physically fixed.
Use several resolutions and an independent limit or justified finer reference;
agreement between two nearby grids is not sufficient evidence of convergence.

| Axis | Control the comparison |
| --- | --- |
| Pupil | Hold aperture and physical parameters fixed; track raster masks, local sampling, represented spatial band, and low-frequency coverage. |
| Focal grid | Separate padding/angular sampling from field extent; compare on compatible angular coordinates and preserve the flux denominator. |
| Window | Measure capture and truncation effects separately from pixel resolution; changing a synthetic layout need not be a crop of fixed hardware. |
| Detector pixels | Separate angular pixel scale, area quadrature, and diffusion; distinguish expectation integration from point sampling. |
| Spectrum | Refine wavelength quadrature with consistent source/QE/throughput weights; match detected photometry when isolating chromatic optics. |
| Time | Refine exposure subsamples with a held DM and intensity averaging; state sample times, latency convention, and residual metric time. |

Report coupled changes explicitly when isolation is impossible. Convergence
need not be monotonic, and a converged discrete model can retain physical bias.

## Design stochastic checks before drawing samples

- Declare the estimand and population: temporal noise conditional on fixed maps
  and masters differs from an ensemble regenerating those persistent products.
- Predeclare primary endpoints, acceptable error/effect size, confidence level,
  sample count or precision/power-based stopping rule, and an upper cost bound.
- Account for temporal correlation with justified block/cluster methods or an
  effective sample size. Seed scatter is not automatically a standard error;
  correlated frames are not independent realizations.
- Define the family of comparisons and the simultaneous-coverage or multiplicity
  treatment appropriate to the claim. Separate exploratory findings from
  confirmatory tests; do not select favorable seeds or retune thresholds.
- Use paired realizations for effects where shared atmosphere/maps are intended;
  verify the pairing and estimator. Differences of total residual mean squares
  can contain a large cross term; residual-map differences answer another question.
- Check Monte Carlo against the oracle's declared regime. A failed pure photon
  law with read noise, CIC, gates, or nonlinear feedback is not automatically a
  software defect; preserve and investigate the observed departure.

## Deliver the verification result

For unexplained failures or discrepancies, proactively research the relevant
method, estimator, and validity assumptions under the common contract. Return
to the oracle/test design with what was actually learned; do not silently retune
thresholds or stop at a suggestion to search later.

Report passed, failed, unsupported, and not-run checks with evidence paths,
uncertainty, convergence limits, and exact affected claims. Distinguish a
reproduced implementation bug, a model limitation, and a validation gap. Keep
governed work concrete and deferred when authorization or resources are absent.
