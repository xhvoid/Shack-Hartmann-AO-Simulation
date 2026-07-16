# AO-REF-007: canonical interaction-matrix calibration

AO-REF-007 replaces the repository's response/poke finite-difference loops
with one unit-explicit calibration engine in
`shwfs_ao.calibration.interaction`. The five installed legacy builders keep
their frozen signatures and result formats, but now adapt their mode or DM
inputs to this owner.

## Canonical API

```python
from shwfs_ao.calibration import (
    DmActuatorProbeBasis,
    ModalProbeBasis,
    calibrate_interaction_matrix,
)

matrix = calibrate_interaction_matrix(
    probe_basis,
    sensor,
    amplitude_m,
    random_streams=random_streams,
    method="central",
    include_noise=False,
    repeats=1,
)
```

`ModalProbeBasis` removes sampled piston and normalizes every mode once to
unit pupil RMS. Its coordinate unit is `m_opd_rms`. Canonical real Zernike
generation and this single normalization implementation live in
`shwfs_ao.backends.native.modes`; legacy Zernike functions restore their
historical NaN-outside arrays and continuous normalization.

`DmActuatorProbeBasis` uses the canonical DM's ordered
`controllable_actuator_ids`, excluding dead and stuck actuators. Its
coordinate unit is `m_opd_equivalent`, and every amplitude is checked against
the DM stroke before the sensor is called.

## Sign, units, and layout

Every column is the WFS derivative for a **positive residual-aberration OPD**
basis:

```text
central: (measurement(+a) - measurement(-a)) / (2a)
forward: (measurement(+a) - noise-free measurement(0)) / a
```

A positive DM correction influence is presented to the WFS as a positive
synthetic residual. The physical loop later forms `atmosphere - correction`;
calibration does not insert an extra negative sign.

`InteractionMatrix.matrix` has the complete canonical row layout:

```text
(len(row_ids), len(coordinate_ids))
```

Rows are never compressed. A row is valid only if every required
probe/sign/repeat sample has the exact sensor row identity and measurement
unit and is finite and valid. An invalid row is marked false and contains NaN
across the entire matrix (and uncertainty matrix). Singular values, rank,
condition proxy, and zero-column checks use only valid rows.

The matrix unit string is `"<measurement_unit> / <coordinate_unit>"`, for
example `"pixel / m_opd_equivalent"`. The result records sensor, geometry,
detector, DM, row-layout, coordinate-layout, and complete calibration content
through immutable hashes and provenance. `to_record()` / `from_record()`
revalidate the same layout, diagnostics, units, and content hash.

## Randomness and noisy calibration

An explicit named random-stream provider is required even for deterministic
calibration. Every probe/sign/repeat receives a view derived as:

```python
random_streams.scoped("calibration", key=(...))
```

Detector requests beneath that view do not advance the caller's top-level
runtime detector or atmosphere generators. Deterministic calibration requires
one repeat and stores no uncertainty. Noisy calibration requires at least two
repeats; it stores the mean of per-repeat derivative matrices and the sample
standard error (`ddof=1 / sqrt(repeats)`) with the same row mask and units.

## Compatibility boundary

The following installed APIs now delegate calibration to the canonical
engine while preserving their historical scaling, row orientation, and
return types:

- `reconstruction.build_response_matrix`
- `shwfs_detector.build_detector_response_matrix`
- `ao_closed_loop.build_dm_wfs_response_matrix`
- `ao_closed_loop.build_dm_detector_response_matrix`
- `interaction_matrix.build_detector_dm_poke_matrix`

The older detector APIs use mathematical y-up rows, so their adapters flip
canonical detector-row-positive y exactly once. The detector-DM poke adapter
also converts canonical pixel/metre derivatives to its frozen pixel/nanometre
format and compresses complete x/y lenslet pairs only at the compatibility
boundary. AO-REF-008 now routes reconstruction policy and rcond scans through
the independent mask-aware canonical reconstructors while preserving the
installed legacy result formats; see
[`AO_REF_008_RECONSTRUCTORS.md`](AO_REF_008_RECONSTRUCTORS.md).

No import-time deprecation warning is emitted. New code should import the
canonical calibration package directly.

The exploratory `shwfs_ao.experimental.pwfs` phase-domain demonstrator is not
one of these five SH-WFS calibration paths: it has no explicit wavelength/OPD
contract and does not implement `WavefrontSensor`. Its frozen experimental
phase-radian calibration remains separate until a typed PWFS sensor boundary
exists; relabeling radians as metres here would be a unit error.
