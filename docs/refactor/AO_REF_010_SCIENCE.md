# AO-REF-010: science propagation, bandpasses, and physical-grid metrics

`shwfs_ao.science` is the canonical owner of science-band spectral sampling,
the backend-independent propagation construction contract, and scalar
image-quality metrics. `shwfs_ao.backends.native.propagation` is the one owner
of the native NumPy science FFT. Detector, controller, WFS, and reconstruction
modules do not own a second science FFT or metric implementation.

## Physical input and result contract

Science propagation consumes residual optical path difference in metres, not
WFS phase:

```python
from shwfs_ao.science import PsfSampling, monochromatic_psf

psf = monochromatic_psf(
    residual_opd_m,
    pupil_geometry,
    wavelength_m,
    backend="native",
    sampling=PsfSampling(pad_factor=4),
)
```

The pupil is an immutable `PupilGeometry` whose array axis 0 is physical y and
axis 1 is physical x. `PsfSampling` belongs to the backend-independent science
contract. `monochromatic_psf` validates that contract, resolves the requested
backend, and delegates; it does not contain an FFT. For `backend="native"`, the
pupil and sampling are bound by
`shwfs_ao.backends.native.propagation.NativeSciencePropagator`, so only
residual OPD and wavelength vary per call. The native backend preserves the
repository's centered, zero-padded NumPy FFT and unit-total-flux normalization.
HCIPy propagation is deferred to AO-REF-017.

Every `PsfResult` contains finite, non-negative discrete pixel flux whose sum
is one. Its strictly increasing `x_angle_rad` and `y_angle_rad` axes match the
intensity columns and rows. Sampling metadata records the pupil geometry,
physical pixel spacing, FFT padding and output shapes, focal angular scale,
axis layout, FFT convention, cropping, interpolation, and normalization.
Malformed or dimensionally inconsistent axes are rejected at the result or
metric boundary.

## Bandpasses

`ScienceBandpass` stores a strictly increasing wavelength axis in metres and
non-negative transmission samples. Arrays and normalized trapezoid-quadrature
weights are copied into immutable storage, and the configuration hash covers
the samples and provenance. `monochromatic_bandpass` and
`top_hat_bandpass` provide documented synthetic fallbacks;
`bandpass_from_filter_curve` accepts a structural SVO-style record only after
its wavelength and transmission units and canonical provenance are validated.

The weights authorize wavelength integration of scalar metric rows only. They
do not authorize stacking wavelength-dependent PSF pixels by array index.

## Scalar metric semantics

`shwfs_ao.science.metrics` distinguishes two data meanings explicitly:

- peak Strehl receives discrete pixel flux but compares peaks only after
  conversion to angular surface brightness using the physical cell areas;
- encircled energy and halo fraction integrate discrete pixel flux;
- FWHM consumes angular surface brightness per steradian.

Encircled-energy radii, FWHM, and halo apertures are measured on those physical
axes rather than inferred from pixel indices. Results report radians,
arcseconds, and lambda/D where applicable. Marechal Strehl removes piston from
the supplied residual OPD in metres and applies the science wavelength
explicitly; passing WFS phase at a different wavelength would violate the
contract.

`band_average_scalar_metrics` normalizes the supplied weights and averages
already-computed monochromatic scalar fields. It does not accept PSF arrays and
does not produce a broadband image. A future broadband image API must require
one explicit common angular detector grid, flux-conserving resampling,
interpolation provenance, and coaddition only after resampling.

## Compatibility boundary

The installed `psf_tools` and `ao_diagnostics` modules retain their frozen
AO-REF-000 signatures, nanometre/phase-facing inputs, dataclass identities,
field order, return shapes, and numerical conventions. Their bandpass and
scalar-metric work delegates to `shwfs_ao.science`; their FFT work delegates to
the single kernel in `shwfs_ao.backends.native.propagation`. New code should
use `shwfs_ao.science` and SI inputs directly; backend implementers use the
corresponding backend namespace. `shwfs_ao.legacy` remains internal.

Notebook 09 and Notebook 11 migration remains assigned to AO-REF-019. Their
existing output tables and figures remain compatibility surfaces rather than a
new broadband detector-image API.
