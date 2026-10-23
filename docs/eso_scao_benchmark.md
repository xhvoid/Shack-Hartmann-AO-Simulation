# ESO-derived SCAO benchmark

This page documents the ESO-derived, single-NGS, Shack–Hartmann SCAO
benchmark: what it is derived from, what is assumed, how it runs at the full
84×84 / 85×85 spatial scale without dense arrays, how its long-exposure
science images are formed, and what has and has not been verified.

It is an **ESO-derived SCAO benchmark**: an auditable numerical experiment
built from the historical E-ELT Design Reference Mission (DRM) parameters. It
is not an ELT instrument model, it is not validated against ESO SCAO data (the
DRM PSF database has no SCAO case), and no parameter was tuned to reproduce a
published Strehl ratio.

## Sources

The source ledger
[`benchmarks/eso_scao_source_ledger.v1.json`](../src/shwfs_ao/resources/benchmarks/eso_scao_source_ledger.v1.json)
records each source's URL, locator, role, supported claims and limitations.

| ID | Source | Role |
| --- | --- | --- |
| R1 | ESO E-ELT DRM, [AO performance and PSFs](https://www.eso.org/sci/facilities/eelt/science/drm/tech_data/ao/) (2011-05-25) | normative: atmosphere, 84×84 SH and 85×85 DM scales, linear-spline family, 500 Hz, 2000 iterations, three-iteration delay, idealized noise |
| R2 | ESO E-ELT DRM, [telescope technical data](https://www.eso.org/sci/facilities/eelt/science/drm/tech_data/telescope/) (2013-03-20) | normative: 42 m, obstruction ratio 0.28 |
| R3 | Gladysz & Rebolo 2010, DRM S3 report, Table 1 p. 17 | contextual reference case (PAOLA SCAO study); not merged |
| R4 | Bechet & Tallon 2012, FRiM/OCTOPUS slides 7, 15–16 | contextual reference case (nine-layer SCAO run); not reproduced |

R3 and R4 stay separate, documented-not-runnable reference cases. Their
noise, lag, atmosphere and filtering differ from R1, and the ledger lists the
contradictions (C1–C4) and how each is resolved.

## Assumptions

Every executable value of every benchmark profile is closed by a row of
[`benchmarks/eso_drm_42m_scao_derived.assumptions.v2.json`](../src/shwfs_ao/resources/benchmarks/eso_drm_42m_scao_derived.assumptions.v2.json)
(the version-1 profiles keep their own v1 ledger). Each row gives its value
and SI unit, a normative source or an explicit rationale, the transformation
applied, its limitation, and the tests that consume it.
`shwfs_ao.io.benchmark_ledgers.validate_benchmark_profiles` checks that every
profile value is covered and equals the row's stated value. It also rejects
engineering assumptions that cite a source as authority, and a frame clock
that disagrees with the detector exposure field.

| ID | Assumption | Value |
| --- | --- | --- |
| A01 | guide star | one on-axis NGS at infinity; layer altitudes unused |
| A02 | wind azimuths | every layer toward +x (R1 gives speeds only) |
| A03 | WFS wavelength | 700 nm, monochromatic |
| A04 | science wavelengths | 2.2 µm (smoke tier: 1.65 and 2.2 µm) |
| A05 | sampling | 12 pupil samples per lenslet (1008 at full scale), Nyquist SH sampling (pad 2, 24-pixel canvas), 23-pixel COG window symmetric about the optical-axis pixel, fill cut 0.5 |
| A06 | DM basis | separable bilinear tent `L((x−xi)/p)·L((y−yi)/p)`, `L(t)=max(0,1−|t|)`, one-pitch support, unit continuous centre (partition of unity); actuators on lenslet corners; layout margin `2√2/(N−1)`; zero-support actuators kept in the layout but excluded |
| A07 | control and reconstruction | gain 0.4, leak 0; Tikhonov least squares, damping 1e-3 of the RMS response column norm; 20 nm central-difference probes |
| A08 | stroke | finite 100 µm OPD limit standing in for unbounded; measured saturation must be 0 |
| A09 | electron scale | 1e5 e⁻/subaperture/frame, numerical only; slopes are scale invariant |
| A10 | timing | one instantaneous atmosphere sample per 2 ms frame; `latency_frames = 2` gives R1's three-interval delay; `exposure_s` recorded, not integrated |
| A11 | science | per-tier burn-in, stride 1, equal weights, pre-update residual, full uncropped grid |
| A12 | numerics | LSMR atol = btol = 1e-8, ≤ 5000 iterations, non-converged solves rejected; float64 |

## Tiers

All four profiles are schema-v5 records in `synthetic_presets/` with their
own identities. Every published profile's identity is unchanged. Each tier
has a version 1 and a version 2; the tiers run version 2 (see
[the detector window revision](#detector-window-revision)).

| Tier | Profile | Size | Frames | Runs |
| --- | --- | --- | --- | --- |
| `ci` | `eso_scao_smoke_5m_software@2` | 5 m, 10×10 SH, 11×11 DM, 120 px | 32 | always (software smoke) |
| `medium` | `eso_scao_medium_12m_derived@2` | 12 m, 24×24 SH, 25×25 DM, 288 px | 200 | `--enable-large-run` |
| `medium-gate` | `eso_scao_medium_12m_weak_gate@2` | as `medium`, r0 = 0.40 m at 500 nm | 120 | `--enable-large-run` |
| `full` | `eso_drm_42m_scao_derived@2`, 20-frame override | 42 m, 84×84 SH, 85×85 DM, 1008 px | 20 | `--enable-large-run` |
| `reference` | `eso_drm_42m_scao_derived@2` | as `full` | 2000 | `--enable-large-run` |

The smaller tiers keep the full tier's 0.5 m pitch and 12 samples per lenslet.
They are distinct, lower-order experiments, not rescaled ESO results.

## Detector window revision

Version 1 of every tier used the whole 24-pixel Nyquist canvas as the
centre-of-gravity window. With an even window, the optical-axis pixel has
12 pixels on its negative side and 11 on its positive side. A spot that is
symmetric about the axis but broad enough to reach the edge then reads a
small negative slope: −0.005 px for a 400 nm local defocus, against exactly
0 for a 23-pixel window
([diagnostic](refactor/eso_scao_evidence/centroid_window_bias_diagnostic.txt)).
The closed loop cancels that false slope with a real one. On the smoke tier
the corrected wavefront held a static tilt of +2.6e-8 rad in x and
+1.8e-8 rad in y with 24 pixels, and +0.06e-8 and −0.66e-8 rad with 23
(realization scatter about 1.7e-8 and 1.2e-8 rad).

At 42 m and 2.2 µm, 2.6e-8 rad is 0.5 λ/D, one science pixel. The
version-1 reference run therefore put its long-exposure core half a λ/D off
axis in both directions: peak Strehl 0.78, on-axis Strehl 0.20
([offset record](refactor/eso_scao_evidence/v1_long_exposure_peak_offset.txt)).
Version 2 changes only `wfs.detector_window_px` to 23. The v2 ledger
records the change under `revisions` (row A05c), and version 1 stays
loadable as the configuration of the first runs. No other value was
changed, and the change was made to remove a measured sensing bias, not to
reach a target Strehl.

## High-order execution path

A schema-v5 profile with a `scalable` block builds through the same
`build_scao_system` factory, preflight, identity attestation and
`run_closed_loop` as every other profile. Nothing on this path allocates an
actuator-by-pupil or lenslet-by-pupil array.

- **DM** — `backends.native.dm_operator.LinearSplineDmOperator` stores each
  actuator's influence only on its support, as a sparse pixel-by-actuator
  matrix. It provides forward synthesis, the adjoint and local influence
  access, and classifies zero illuminated support. `DeformableMirror`
  learns count, shape and identity from the operator. The dense cube exists
  only through a size-guarded compatibility method (64 MiB).
- **SH geometry and optics** —
  `wfs.shack_hartmann.compact_geometry.CompactShackHartmannGeometry` stores
  per-lenslet cell bounds and local masks. It uses the dense geometry's exact
  partition rule, and nondivisible pupils are never rounded.
  `backends.native.shwfs_batched.BatchedNativeShackHartmannOptics` reproduces
  the dense optics lenslet by lenslet in bounded FFT batches; batch size is
  outside every identity.
- **Calibration** — `calibration.sparse.calibrate_sparse_interaction_matrix`
  colors the eligible actuators into groups that share no lenslet. It then
  measures one zero reference and a ±a pair per group. For local, noiseless
  sensing the result equals the per-actuator central differences, column by
  column. Noise-on scalable calibration is refused before any measurement.
- **Response and solver** — `SparseInteractionMatrix` stores the nonzeros
  with the full row layout, units, identities and exclusions. It provides a
  tested forward/adjoint pair. `SparseLsmrReconstructor` solves the damped
  least-squares objective with LSMR, records iteration telemetry, and
  rejects non-converged solves.
- **Reuse** — an explicit `SparseCalibrationCache` reuses a calibration only
  after re-deriving its content hash and matching every identity field.
  Anything else fails closed.
- **Atmosphere memory** — the ten-layer atmosphere can redraw its band
  coefficients each frame from the same keyed generators
  (`ScaoExecutionOptions(atmosphere_band_storage="regenerate")`). Frames are
  bit-identical, and the full scale holds about 600 MiB less.

## Long-exposure science

`science.long_exposure.StreamingLongExposure` is a passive frame observer.
For every selected frame it propagates the residual OPD separately at each
wavelength through the system's science propagator and adds the
instantaneous unit-flux intensity to a running sum. The long exposure is
`Σ a_k I_k / Σ a_k`. It never propagates a mean OPD, never adds fields
coherently and never recentres frames. Its retained state is one sum image
per wavelength, independent of the frame count.

- Selection is `frame ≥ burn-in`, every `stride` frames, up to `max_samples`.
  The result records the first and last frame, the timestamps, `N·stride·dt`
  quadrature exposure and `(N−1)·stride·dt` sample-centre span.
- The default residual is the pre-update residual the WFS measured. The
  post-update residual is labelled a same-sample diagnostic.
- Flux denominator: every image has unit flux over the full uncropped FFT
  grid. Strehl is the final image's peak surface brightness over the peak of
  a zero-OPD ideal image from the same propagator. FWHM, EE50/EE80 and the
  radial profile are centred on the final-image peak, and on-axis Strehl is
  also reported. At the default science sampling (pad 2) EE50 is
  pixel-limited: 7.3 % (12 m) and 3.6 % (42 m) above its pad-4 value (see
  below), so it is an upper estimate. Strehl does not depend on it.
- The benchmark uses the native propagator, whose grid is the complete FFT
  grid. An HCIPy propagator returns a unit-sum image over a finite focal
  window. With it the same accumulator gives in-window (conditional)
  fractions, not absolute-source encircled energy; its `captured_flux_fraction`
  diagnostic would be needed to recover the denominator. That path is not
  part of the benchmark.
- The native ten-layer atmosphere's periodic band repeats once a layer has
  travelled one screen period (2× the pupil, 84 m at full scale). In the
  4 s reference run, the 33.7, 23.2 and 22.2 m/s layers (13 % of Cn²) pass
  that point. Their band content then repeats, which makes long-exposure
  statistics less independent without introducing a discontinuity. Each
  manifest reports `periodic_band_repeated` and the maximum travel.

## Running

```bash
python examples/run_eso_scao_benchmark.py
```

```bash
python examples/run_eso_scao_benchmark.py --tier full --dry-run
```

The first command runs the CI tier in a supervised child process: two native
threads, an aggregate-RSS budget, a wall-clock limit, and a stop on
warning/critical memory pressure. The second prints the configuration and an
analytic peak-memory estimate without building anything. Large tiers refuse
to run without `--enable-large-run`. On a desktop whose policy budget is too
small they also need `--authorized-budget-mib` with an `--authorization-note`
naming the human authorization. Outputs go to
`$AO_DEMO_OUTPUT_DIR/eso_scao_<tier>` (or `./eso_scao_benchmark_output/`):
`manifest.json`, `telemetry.npz` and `science_<λ>.npz`.

## Measured results

Version-2 profiles, realization 0, noiseless, on the 16 GiB development
desktop. Open-loop and residual values are means of the wavefront RMS
over the frames after burn-in (the residual is the pre-update one).
Strehl is from the long-exposure image at 2.2 µm over the frames after
burn-in; in every run below the image peak is on axis.

| Tier | Frames (burn-in) | Open loop → residual | Strehl | Wall time, peak memory |
| --- | --- | --- | --- | --- |
| `ci` | 32 (8) | 1439 → 233 nm | 0.65 | 2.6 s, 130 MiB |
| `medium` | 200 (50) | 1300 → 175 nm | 0.78 | 47 s, 301 MiB |
| `medium-gate` | 120 (30) | 449 → 71 nm | 0.96 | 16 s, 299 MiB |
| `full` | 20 (5) | 1624 → 372 nm | 0.43 | 110 s, 1.41 GiB |
| `reference` | 2000 (200) | 1683 → 173 nm | 0.78 | 62 min, 1.64 GiB |

The `full` tier is capability evidence: 20 frames do not settle the loop.
The `reference` run reused the `full` tier's calibration from the verified
cache; its residual stays within 172–174 nm from frame 20 to 2000.
None of these numbers is a comparison with an ESO result; R3 and R4 differ
in noise, delay, atmosphere and filtering.

## Sampling convergence

`scripts/eso_scao_paired_convergence_study.py` (roadmap S3, run 2026-10-18
on `2312502`, recorded 2026-10-19) refines one sampling at a time from the tier's baseline, with
the WFS field of view held at 11.5–11.75 λ/d and paired atmospheric draws
(every setting's screen is a sub-band of one draw on the finest grid). Three
realizations of 200 frames per setting, 50-frame burn-in, long exposure at
2.2 µm; criterion, declared beforehand: the two finest settings agree within
2 % in Strehl and EE50.

| Tier | Scan | Strehl | EE50 | Verdict |
| --- | --- | --- | --- | --- |
| `medium` (12 m) | pupil, 12 → 16 → 20 samples per lenslet | 0.7618 → 0.7603 → 0.7584 (finest two 0.25 %) | 32.56 → 32.72 → 32.89 mas (0.55 %) | converged |
| `medium` | WFS pad 2 → 3 → 4 | 0.00 % | 0.00 % | converged |
| `medium` | science pad 2 → 3 → 4 | identical | 32.56 → 31.65 → 30.35 mas (4.3 %) | EE50 not converged |
| `full` (42 m) | pupil, 12 → 16 samples per lenslet | 0.7832 → 0.7832 (0.01 %) | 8.684 → 8.685 mas (0.01 %) | converged |
| `full` | WFS pad 2 → 3 → 4 | 0.7832 → 0.7822 → 0.7819 (0.04 %) | +0.12 % | converged |
| `full` | science pad 2 → 3 → 4 | identical | 8.684 → 8.473 → 8.384 mas (1.05 %) | converged; pad 2 reads 3.6 % high |

Records: [`paired_convergence_medium.json`](refactor/eso_scao_evidence/paired_convergence_medium.json),
[`paired_convergence_full.json`](refactor/eso_scao_evidence/paired_convergence_full.json).
The earlier smoke-tier scan in the development record did not pair its
screens and let the WFS field of view grow with the sampling; this study
supersedes its sampling conclusion for the two larger tiers.

## Verification status

See [`refactor/ESO_SCAO_DEVELOPMENT_STATUS.md`](refactor/ESO_SCAO_DEVELOPMENT_STATUS.md)
for the commands run, their measured results, the convergence study, and the
gates still pending.
