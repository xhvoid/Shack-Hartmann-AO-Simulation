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
