# AO-REF-005 Canonical Shack-Hartmann Domain

AO-REF-005 separates Shack-Hartmann geometry, noiseless optics, deterministic
reference calibration, detector-level measurement, and geometric measurement.
The stable API is available from `shwfs_ao.wfs.shack_hartmann` and is re-exported
with object identity from `shwfs_ao.wfs`.

## Geometry and identity

`shwfs_ao.core.geometry.PupilGeometry` owns the immutable Cartesian pupil
sampling in metres. `ShackHartmannGeometry` adds the retained lenslet masks,
centers, and ordered physical lenslet IDs. Array axis 0 is physical y/increasing
row and array axis 1 is physical x/increasing column. The retained tuple keeps
the repository's frozen column-outer, row-inner traversal, while IDs encode the
physical row and column and do not depend on backend enumeration.

All geometry arrays and masks are defensively copied into read-only storage.
Geometry content and ordering contribute to stable hashes used by calibration.

## Optical backend boundary

The shared `ShackHartmannOpticsBackend` consumes residual OPD in metres and
returns `SpotIntensityResult`. A result contains exactly one full detector
window for each ordered geometry ID. Each spot is non-negative and independently
normalized to unit sum. Detector-window capture throughput is reported
separately and must not be multiplied into the normalized spot twice. Boundary
validation rejects missing, unexpected, duplicated, and reordered IDs as well
as incompatible detector-plane sampling.

`shwfs_ao.backends.native.shwfs` is the transparent NumPy implementation. It
performs local lenslet-field extraction, local piston removal, fixed zero
padding, centered FFT propagation, detector-window cropping, and normalization.
It neither applies detector effects nor evaluates centroid validity. Its phase
convention is:

```text
phase_rad = 2π * residual_opd_m / wfs_wavelength_m
```

Positive physical x tilt moves a spot toward increasing detector columns;
positive physical y tilt moves it toward increasing detector rows. Padding,
FFT centering, sampling, and reference-pixel choices are explicit configuration
content rather than optional backend defaults.

## Reference calibration and detector state

`ShackHartmannCalibration` records geometry, zero-phase reference centroids,
WFS wavelength, ordered subaperture and `S:x`/`S:y` row IDs, pixel measurement
unit, detector-plane sampling, detector and centroid configurations, detector
realization hash, provenance, and the complete calibration hash.

A detector-level sensor owns one immutable `DetectorRealization`. Calibration
and runtime both verify the recorded realization and configuration hashes.
Reference centroids run through the same optics, detector expectation,
detector-window, fixed response, and centroid estimator used at runtime, with
temporal shot and read draws disabled. Persistent PRNU and bad-pixel maps are
therefore identical in reference and measurement frames.

The historical `per_frame_legacy` PRNU response is isolated to explicitly
keyed/scoped child generators in the `calibration` random domain. The scope,
key, derived stream identity, and seed are recorded in provenance and covered
by the calibration hash. These draws cannot advance runtime
`detector.shot_noise` or `detector.read_noise` streams.

## Measurement contract

The detector-level pipeline is:

```text
residual OPD (m)
→ phase at the WFS wavelength
→ backend unit-sum lenslet spots
→ detector effects
→ centroid estimator
→ zero-phase reference subtraction
→ centroid-validity policy
→ WfsMeasurement
```

The canonical `MeasurementVector` stores flattened x/y centroid shifts in
pixels with immutable row IDs. For each subaperture, x precedes y; if either
coordinate is unusable, both rows are invalid. Optional detector telemetry owns
centroids, flux and quality diagnostics, per-criterion flags, optical spots,
and detector frames without changing the reconstruction-vector schema.

`include_noise=False` disables temporal shot/read draws but still applies the
fixed detector response, or the explicitly replayed legacy calibration
response. Runtime randomness is supplied by the caller as `RandomStreams`; the
sensor does not create a hidden provider or reuse calibration generators.

## Detector-free geometric path

`NativeGeometricShackHartmannSensor` averages local OPD gradients over the same
retained subapertures and returns the same ordered `S:x`, `S:y` rows with
`measurement_unit="rad_wavefront_slope"`. It has an explicit reference-slope
calibration, no detector telemetry, and no detector imports. It preserves the
positive x/y convention and supplies the stable sensor contract needed by
later interaction-matrix and SCAO tickets. AO-REF-007 owns the actual
interaction-matrix rebuild.

## Compatibility and experimental PWFS

Existing `shwfs_detector` and `synthetic_instrument_data` imports remain silent
compatibility paths that delegate affected physical operations to canonical
owners while retaining their frozen signatures, coordinates, exceptions, and
seeded results at the legacy boundary.

The pre-existing PWFS implementation now has one installed owner at
`shwfs_ao.experimental.pwfs`; `shwfs_ao.legacy.pwfs_forward` and the top-level
`pwfs_forward` import delegate to it. Its focused seeded outputs remain frozen,
but it does not implement the stable Shack-Hartmann protocols and is not
presented as a validated PWFS SCAO backend.
