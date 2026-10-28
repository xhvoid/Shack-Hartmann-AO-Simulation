# Interaction Matrix Notes

The repository-level calibration owner is
`shwfs_ao.calibration.calibrate_interaction_matrix`. It accepts either a
unit-pupil-RMS `ModalProbeBasis` or a canonical-DM
`DmActuatorProbeBasis`, plus any WFS implementing the shared measurement
protocol. Central difference is the default:

```text
(measurement(+a) - measurement(-a)) / (2a)
```

Columns describe response to positive residual-aberration OPD. A positive DM
correction influence is therefore presented as a positive synthetic residual;
the physical loop later subtracts correction from atmosphere exactly once.
Canonical detector-DM calibration uses:

```text
coordinate unit: m_opd_equivalent
matrix unit: pixel / m_opd_equivalent
phase wavelength: calibration.geometry.wfs_wavelength_m
row orientation: increasing detector column / row
```

The `InteractionMatrix` retains every ordered sensor row. A row that fails any
required probe/sign/repeat is stored as all-NaN and marked false; it is never
compressed or silently replaced with zero. SVD, rank, condition proxy, and
all-zero-column validation use only calibration-valid rows. The result also
records the exact sensor, geometry, detector, DM, row-layout, coordinate, and
calibration hashes. Every sensor call uses an explicit named random-stream
view beneath the `calibration` scope, so calibration draws do not advance
runtime detector or atmosphere generators.

Noisy calibration requires at least two repeats. It records the mean of the
per-repeat derivative matrices and their sample standard error with the same
units and row mask. Deterministic calibration uses one repeat and has no
uncertainty array.

## Reconstruction from the calibrated matrix

Inverse policy is separate from matrix construction. The canonical
`LeastSquaresReconstructor`, `TsvdReconstructor`, and
`TikhonovReconstructor` consume an `InteractionMatrix` and return the shared
`ReconstructionEstimate`.

Runtime measurements must have the exact calibrated row IDs, order, and unit.
The usable rows are the intersection of calibration validity, runtime
validity, and finite runtime values. The solve never turns an invalid centroid
into a zero-valued valid measurement. Reconstructed and residual signals keep
the full canonical row layout with NaN in unusable rows, while coordinates
retain their modal or actuator IDs and units. Every estimate records the
matrix hash.

Recurring runtime masks reuse solve factors from a deterministic bounded LRU
cache keyed by the matrix, inverse settings, and packed usable-row mask. Thus a
stable detector mask does not trigger an SVD on each loop frame. The canonical
layer also owns kept-mode counting, the TSVD noise-amplification proxy,
matrix-specific cutoff selection, and rcond scans. Tikhonov at `alpha=0` has
the least-squares limit.

## Installed compatibility result

The installed top-level `interaction_matrix` module retains the historical
`PokeMtxResult`, TSVD/Tikhonov result formats, scan result, and nanometre-facing
output. Poke construction and inverse policy delegate to the canonical
calibration package. At the calibration boundary only, it converts:

```text
canonical pixel/metre → legacy detector_px/nm_OPD_equivalent
canonical detector-row-positive y → legacy mathematical y-up
full canonical rows → complete historically valid x/y lenslet pairs
```

Its required compatibility fields remain:

```text
poke_matrix
singular_values
kept_modes
rcond
source_class
```

Additional metadata records controlled actuator indices, valid lenslet rows,
calibration amplitude, numerical rank, a condition proxy, and the frozen
legacy `config_hash` derived from geometry, detector, DM, and calibration
settings.

The selected TSVD `rcond` is chosen from a fresh interaction-matrix scan grid
for the current detector-level matrix. It is not copied from notebook 09. The
helper keeps a configurable fraction of the numerically nonzero singular modes
and stores the grid summary in `PokeMtxResult.rcond_scan_summary`; each scan
candidate calls the canonical reconstructor rather than constructing a second
pseudoinverse.

For the current fast demonstrator, the poke matrix is deliberately small and well conditioned. The SVD plot should be described as a compact detector-level DM/WFS response sanity check, not as a realistic high-order detector-level reconstructor-conditioning study. In this configuration all controlled modes remain well above the selected TSVD cutoff.

The command-line diagnostic is:

```bash
python3 examples/run_interaction_matrix_demo.py
```

It writes:

```text
figures/detector_level_SCAO/poke_matrix_singular_values.png
figures/detector_level_SCAO/poke_matrix_singular_values.csv
```

These outputs are synthetic calibration diagnostics, not measured observatory
interaction matrices. The complete canonical contract and migration boundary
are documented in
[`refactor/AO_REF_007_INTERACTION_MATRIX.md`](refactor/AO_REF_007_INTERACTION_MATRIX.md).
The runtime mask, inverse, and cache contract is documented in
[`refactor/AO_REF_008_RECONSTRUCTORS.md`](refactor/AO_REF_008_RECONSTRUCTORS.md).
