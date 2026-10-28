# AO-REF-008: mask-aware cached reconstructors

AO-REF-008 separates inverse reconstruction policy from interaction-matrix
calibration. The calibrated forward operator remains an immutable
`shwfs_ao.calibration.InteractionMatrix`; least-squares, truncated-SVD, and
Tikhonov inverse policies now live in
`shwfs_ao.calibration.reconstructors`.

## Canonical API

```python
from shwfs_ao.calibration import TsvdReconstructor

reconstructor = TsvdReconstructor(
    interaction_matrix,
    rcond=1.0e-4,
    min_valid_fraction=0.5,
    min_rank=1,
    max_cached_masks=32,
)

estimate = reconstructor.reconstruct(measurement.vector)
```

All three reconstructors consume a canonical `MeasurementVector` and return
the shared `shwfs_ao.core.ReconstructionEstimate`; there is no
calibration-local command-result type. The estimate preserves the matrix's
coordinate IDs, coordinate kind, coordinate unit, measurement unit, and
calibration hash. Modal coordinates therefore remain `m_opd_rms`, while DM
coordinates remain `m_opd_equivalent`; reconstruction does not relabel either
one as a full DM command vector.

## Runtime row policy

Runtime measurements must have exactly the interaction matrix's `row_ids`, in
the same order, and the same measurement unit. Missing, extra, or reordered
rows and unit mismatches raise `ReconstructionError`; they are not repaired by
position.

Usable rows are selected as:

```text
interaction_matrix.row_valid
and measurement.valid_rows
and finite(measurement.values)
```

The valid-fraction denominator is the number of calibration-valid rows, not
the number of nominal rows. A structurally valid measurement returns `None`
only when usable coverage or the masked operator's numerical rank is below the
configured policy. Invalid measurements are never filled with zero before a
solve.

`reconstructed_signal` and `residual_signal` retain the full canonical row
layout. Unusable rows are NaN and are marked false in `usable_rows`; the
residual on usable rows is `measurement - reconstructed`. Norms and singular
diagnostics are computed from the usable system only.

## Inverse policies and diagnostics

- `LeastSquaresReconstructor` applies a minimum-norm pseudoinverse while the
  configured rank gate uses the canonical numerical-rank policy.
- `TsvdReconstructor` retains singular directions selected by its finite,
  positive relative `rcond`.
- `TikhonovReconstructor` applies a non-negative regularization parameter;
  `alpha=0` has the least-squares limit.

The same module owns kept-mode counting, the TSVD noise-amplification proxy,
matrix-specific `rcond` selection, and `rcond` scans. A scan constructs and
calls reconstructor objects; it does not carry a second pseudoinverse
implementation.

## Masked-operator cache

Each reconstructor caches masked operators and solve factors by matrix hash,
reconstructor settings, and the packed usable-row mask. Repeated production
masks therefore reuse their SVD instead of recomputing it on every loop frame.
The cache is a deterministic bounded LRU; `max_cached_masks=0` disables it,
and eviction changes performance only. `ReconstructorCacheInfo` exposes cache
hits, misses, factorization count, current size, and configured capacity for
diagnostics and tests.

The matrix hash is recorded on every `ReconstructionEstimate`, preventing a
result from being detached silently from the calibration that produced its
inverse operator.

## Sparse LSMR Tikhonov reconstructor

Scalable profiles (a `scalable` block, `sparse_lsmr_tikhonov`) use
`shwfs_ao.calibration.sparse.SparseLsmrReconstructor`. It follows the same
runtime row policy without forming a dense inverse:
- it solves the Tikhonov least-squares objective with LSMR from `x0 = 0`
  on the usable rows;
- its damping is relative: `damp = alpha * rms(column norms)` over the
  calibration-valid rows;
- a solve that hits the iteration or conditioning limit returns `None`,
  unless `nonconverged_policy="accept"`.

### Subset solve

`reconstruct_subset(measurement, min_valid_fraction=...,
min_actuator_coverage=None)` is the same solve with a lower coverage
threshold in place of the reconstructor's own. It is the fallback of the
opt-in loop recovery policy (AO-REF-009, recovery supervisor).
- With `min_actuator_coverage` (the rank guard), it solves only for
  actuators whose usable rows keep at least that fraction of their
  calibrated response energy, the squared column norm. The other actuators
  receive an exactly zero increment.
- It returns `None` when too few rows are usable, no actuator qualifies,
  or the solve is rejected.
- The reconstructor's identity and `reconstruct()` are unchanged.
- On the 12 m detector-level profile this fallback did not recover a
  latched loop. A partial solve corrects the seen actuators while the
  unseen ones hold the bad shape.

### Choosing the damping

The relative damping must be compared with the *weakest sensed modes*, not
with the column norm.
- A mode with singular value `s` keeps the fraction `s² / (s² + damp²)` of
  its gain. Its noise is amplified by `s / (s² + damp²)` instead of `1 / s`.
- On a Fried-geometry SH with a linear-spline DM, the weakest non-null
  mode is global waffle. The interaction matrix of the 12 m
  detector-level tier (832 rows × 476 actuators) puts it at 0.0265 of the
  RMS column norm, about 40 times below the median mode.
- `alpha = 0.001` (damping 4 % of the waffle singular value) therefore
  leaves waffle unregularized. Centroid noise then drives it as a random
  walk, and at m_AB = 11 it broadened and clipped enough spots to collapse
  the loop.

Measured on that tier at m_AB = 11, root seeds 11 and 12 with the reset
policy:

| `alpha` | Waffle gain kept | Modes keeping < 0.9 of their gain | Residual |
| --- | --- | --- | --- |
| 0.001 | 1.00 | 0 | 332 / 296 nm, 6–8 resets |
| 0.03 | 0.44 | 1 | 197 nm (seed 11), no reset |
| 0.1 | 0.066 | 25 of 475 (median mode 0.99) | 189 / 181 nm, no reset |
| 0.3 | 0.008 | 185 | 269 nm (seed 11): over-damped |

- `alpha = 0.1` was evaluated, predeclared, on independent seeds and
  adopted in `det_emccd_12m_medium_derived@3`. There m_AB = 11 holds
  195 nm, and m_AB 8–10 improve by about 8–9 nm.
- The value is specific to that geometry and noise level. Another profile
  should check where its weakest modes sit before reusing it.
- `det_ccd_42m_r3band_derived@1` still uses 0.001 and is untested.

Evidence: the [detector-level status record](DETECTOR_LEVEL_DEVELOPMENT_STATUS.md),
section "Excursion trigger at m_AB = 11".

## Compatibility boundary

The installed `reconstruction`, `shwfs_detector`, `ao_closed_loop`, and
`interaction_matrix` APIs retain their frozen signatures, result dataclasses,
row orientation, and historical nanometre/pixel scaling. Their reconstruction
helpers now adapt those arrays to the canonical layer. Legacy frame loops
construct a reconstructor once and reuse it, while `scan_tsvd_rcond` delegates
each candidate to the same reconstructor policy.

The top-level compatibility modules remain silent imports. New code should use
`shwfs_ao.calibration` directly. Controller state, gain, leak, command
projection, and latency are owned by `shwfs_ao.control`; see the
[AO-REF-009 control-loop contract](AO_REF_009_CONTROL_LOOP.md).
