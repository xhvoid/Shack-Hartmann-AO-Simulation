# Review round 1: ungoverned checks of the repaired tools (2026-10-22)

Producer: commit `da44227` (the packet's first revision on top of `5514285`;
the imported package digest is unchanged), the `constraints/hcipy-py311.txt`
environment of the first session (Python 3.11.17, NumPy 2.4.6, SciPy 1.17.1,
x86_64), serial, two native threads, every numerical job under
`shwfs_ao.runtime.resource_guard` with the policy budget (2011.6 MiB). Nothing
here is a governed run, a 12 m or 42 m system build, or a scientific result;
the labels are `EXECUTED_CURRENT` for the checks and `MEASURED_CURRENT` for
their timings. Chronology: `run_validations.log`, `run_validations2.log`,
`run_validations3.log` (the model outputs were regenerated twice as the tool
gained the finite-window prediction and the support rules; only the final
outputs are kept here). Trace archives (`*.npz`) stay outside the
repository; their digests are in `pilot_sidecars.sha256`.

## CHK-1a: fixed-physics timing pilot at ci scale (finding 1 and 2)

`tools/timing_pilot_fixed_physics.py --scale ci --key ci_baseline_plain_r0`
under the guard CLI (`p1_ci/`, and `p1_ci_alone/` rerun with nothing else
on the host):

| Quantity | first run | rerun alone | T2 ci self-check child of the same key (2026-10-21) |
| --- | --- | --- | --- |
| driver import and plan | the driver loads by path with the module registered first; `plan("ci")` and `planned_protocol` as the driver's | same | - |
| `check_run` against the planned protocol | passed | passed | passed (the driver's own) |
| scalars, open-loop digests, `DeltaV` series, science metrics | bit-identical to the self-check row | bit-identical | reference |
| protocol hash | differs from the self-check row in `code/git_head` only (`da44227` against `5514285`; same package digest) | same | - |
| wall (launcher / result timing) | 27.2 s / 27.2 s | 26.7 s / 26.7 s | 17.6 s |
| per-frame twin / noise-on | 0.130 / 0.132 s | 0.130 / 0.123 s | 0.102 / 0.078 s |
| `ru_maxrss` / group peak | 159 / 149 MiB | 160 / 131 MiB | 178 MiB child |

The computation is the study child's to the bit; the host was about 1.5x
slower than on 2026-10-21 for the identical work (build and loop alike), so
cloud timing anchors carry at least that session-to-session spread.

## CHK-1b: traced timing pilot on the 2 m profile (finding 2)

`tools/timing_pilot_traced_run.py --profile det_emccd_2m_synthetic
--profile-version 1 --magnitude 5 --root-seed 61 --frames 200 --burn-in 50
--historical docs/refactor/detector_level_evidence/det09_noise_isolation_2m.json
--trace-sidecar ...` under the guard (`ni2m_m5s61/`): wall 39.9 s,
`ru_maxrss` 104 MiB, group peak 93 MiB; the seven recorded quantities agree
with the committed desktop record within 8.3e-10 relative (configuration
hash equal); `DeltaV` 4.17 +/- 0.51 nm^2 (25-frame block SE, 150 frames);
gate-quiet, no mask disagreement, no rejected reconstruction; E0 weighted
ratio 1.027; both arms clip up to 31 % of the actuators in a frame (mean
15 %, stroke 1 um); trace 1.0 MB uncompressed, sidecar 0.78 MB.

## CHK-1c: the exact linear loop model on the 2 m sidecars (finding 3)

`tools/linear_loop_noise_model.py --self-test`: the Lyapunov variance equals
`kappa` to 1e-15 for (g, l, d) = (0.3, 0, 2), (0.2, 0.02, 2), (0.4, 0, 2),
(0.5, 0, 0), (0.3, 0, 1); decoupled modes keep their own variances; the
structured `F P F^T` equals the dense product to 3e-17; the 400-frame window
mean of a unit-feedback loop equals `kappa` to 7e-15 (`model_self_test.json`).

On the 33 two-metre sidecars (the pilot's and the 32 of the first session's
series replay), configuration hashes equal to the built configuration's,
13 controlled actuators, 42 rows, 2032 pupil samples, TSVD: `max |L - I|`
3.6e-15, spectral radius 0.7226, Lyapunov residual at most 3.4e-14, window
equal to the stationary value (`L = I`, time constant about 5 frames), exact
over scalar within 0.4 % (the x/y correlation term). Measured `DeltaV` over
the prediction from each run's realized covariance (`ni2m_models/summary.json`):

| m_AB | seeds | measured / predicted, available rule (t, 7 dof) | strict rule | saturation (mean after burn-in) | strict support | within 2 block SE |
| --- | --- | --- | --- | --- | --- | --- |
| 5 | 8 | 0.936 +/- 0.060 | 0.939 +/- 0.058 | 0.015-0.153 | 0.95-1.00 | 5/8 |
| 6 | 8 | 0.892 +/- 0.076 | 0.896 +/- 0.075 | 0.016-0.154 | 0.95-1.00 | 5/8 |
| 7 | 8 | 0.860 +/- 0.050 | 0.862 +/- 0.048 | 0.016-0.153 | 0.95-1.00 | 3/8 |
| 8 | 8 | 3.6 +/- 5.0 (gate-active, not fitted) | 5.9 +/- 7.7 | 0.021-0.152 | 0.38-0.86 | 5/8 |

The 2 m outcome of the first session therefore stands for the whole linear
model (not only for the scalar factor): the deficit under actuator clipping
is unchanged, and the model is not verified at 2 m. The flat-wavefront
covariance predicts 2.07 nm^2 at m5 seed 61 against 4.7 nm^2 from the
realized covariance: the a-priori sigma is not usable for closure.

## CHK-1d: traced pilots and the model on the ci geometry (findings 2 and 3)

The convergence driver's ci derivation (12 m `@3` detector physics on the
5 m smoke geometry: 96 controlled actuators, 144 rows, 10,224 pupil samples,
gain 0.4, latency 2, stroke 100 um), seed 71, 400 frames, burn-in 100, each
under the guard (wall 120-131 s, `ru_maxrss` 238 MiB, group peak 198-223
MiB, trace 7.0 MB, sidecar 5.1 MB, no clipping, no rejected reconstruction):

| run | damping | gate-quiet | mask frames (row-frames) | strict / available support | measured `DeltaV` (nm^2, block SE) | window prediction, available / strict (nm^2) | scalar `kappa` reduction | stationary | measured / predicted (available; strict) |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| m7 | 0.1 (12 m, diagnostic) | yes | 0 | 1.000 / 1.000 | 92.9 +/- 2.8 | 94.1 / 94.1 | 97.7 | 94.2 | 0.987; 0.987 |
| m9 | 0.1 (12 m, diagnostic) | yes | 1 (0.005 %) | 0.958 / 1.000 | 614.6 +/- 15.9 | 607.9 / 583.4 | 627.7 | 608.0 | 1.011; 1.053 |
| m7 | 0.001 (ci's own) | yes | 15 (0.079 %) | 0.875 / 1.000 | 223.4 +/- 26.0 | 212.6 / 174.2 | 212.3 | 424.1 | 1.051; 1.282 |
| m9 | 0.001 (ci's own) | **no** | 71 (0.583 %) | 0.639 / 1.000 | 1771.8 +/- 189.7 | 1388.4 / 784.9 | 1382.3 | 2883.8 | 1.276; 2.257 |

Feedback spectrum of `L = R M`: with the 12 m damping 7.3 % of the
eigenvalues are below 0.9 and 2.1 % below 0.5 (10th percentile 0.937,
smallest 6e-11); with the ci damping all but one are within 1e-5 of unity
and one is 4.6e-7 (an almost unsensed mode: with no leak it accumulates
noise through the run, so the stationary limit is about twice the 400-frame
window value, which is why the finite-window prediction is the primary
quantity). With the 12 m damping the exact prediction is 3.2-3.7 % below the
scalar reduction and the two gate-quiet runs agree with it within one block
standard error (0.987, 1.011). With the ci damping the gate-quiet m7 run
agrees under the available rule (1.051) and not under the strict rule
(1.282): 12.5 % of the lenslets flicker in 15 of 300 frames, and the strict
rule drops their noise entirely. The gate-active m9 run (71 frames, 36 % of
the lenslets flickering) exceeds the fixed-mask prediction by 28 % under
the available rule and by a factor 2.3 under the strict rule: the fixed-mask
linear picture does not describe gate-active runs, which is what P4 of the
protocol measures against it. E0 weighted ratios of the four runs:
0.992-1.008.

The `--alpha 0.1` runs are diagnostic configurations (the configuration hash
changes and is recorded); they are not profiles and enter no series.

## CHK-1e: leftover quarantine on synthetic directories (finding 8)

`tools/quarantine_leftovers.py` on a study directory holding a planned run
file, a `runs/*.json.tmp-4242-9f3a1c2b` leftover and a `scratch/twin_pupil_samples_*.npy`,
and on a record directory holding the record, its referenced sidecar, an
orphan sidecar and a `*.npz.tmp-777-0badf00d` leftover: the listing names
exactly the leftovers with sizes and SHA-256; `--apply` moves them into
`leftovers/<UTC>/` with a manifest and leaves the planned run, the record
and the referenced sidecar in place; a second pass finds nothing
(`quarantine_demo/*/leftovers/*/manifest.json`). Both drivers' refusal paths
for such files were read, not exercised (no governed directory exists).

## Not executed

Every pilot and stage of `pilot_requests.json` (P1a-P1c, P2, P2b, P3, the
stages), any 12 m or 42 m run or system build, any slow or HCIPy test.
