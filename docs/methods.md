# Model conventions

The native loop combines frozen-flow atmosphere screens, a deformable-mirror
model, Shack–Hartmann measurements and a reconstructed command. Small models
use dense matrices; the large-aperture path uses local lenslet propagation,
sparse response matrices and iterative reconstruction. The package also
contains optional HCIPy components and older compatibility interfaces.

## Quantities and timing

- Optical path difference (OPD), wavelengths and DM commands use metres in the
  canonical APIs. A reflective surface displacement is not the same quantity
  as an OPD-equivalent command.
- Phase is `2π × OPD / wavelength`. Array rows follow y and columns follow x.
  Optical backends explicitly state their coordinate and FFT conventions.
- A frame measures the residual with the held DM command. The controller
  computes an increment and releases it according to its queue delay. For
  the 42 m study's convention, an increment from frame k with queue delay L
  first affects the measured residual at k + L + 1.
- Pupil RMS removes piston; tilt is retained unless the label says otherwise.
  Mean instantaneous RMS and the root of mean variance are different averages.
- Mean images average propagated intensities. They do not propagate a mean
  wavefront. Peak Strehl of a mean image differs from mean instantaneous peak
  Strehl. The Explorer recordings retain tilt and do not recenter images.
- EE50 is the radius enclosing half the energy. The 42 m gain study uses its
  Fourier-reference estimate in units of wavelength/aperture; the production
  estimator has a documented sampling sensitivity.

## Reading the selected cases

The 2 m demonstration is deliberately small: five lenslets across and a
13-actuator Gaussian basis. Later numerical checks find weak tilt correction
from the spatial sensor/reconstructor/DM combination. That residual should
not be attributed to latency alone.

The 2.2 m investigation compares two runs through the same atmospheric
sequence. A stronger TSVD cutoff suppresses weak inverse modes. The revised
trajectory remains usable for the recorded two seconds; this does not establish
a general stability boundary. The recovery safeguard never activates in that run.

The 42 m study compares gains 0.2 and 0.3, queue delays 2 and 3, and three
paired atmospheric realizations. It reports both whole-window image metrics
and a late excursion in one realization. Its small conditional sample does
not establish an optimum gain or an instrument latency requirement.

## Sources

Parameter-by-parameter references, source classifications and uncertainties
are retained in `src/shwfs_ao/resources/benchmarks/` and the versioned profiles.
Key entry points are:

- [ESO historical E-ELT telescope reference](https://www.eso.org/sci/facilities/eelt/science/drm/tech_data/telescope/)
- [Current ELT](https://elt.eso.org/about/)
- [Robo-AO-2 NGS modelling paper](https://arxiv.org/html/2407.14677v1)
- [HCIPy](https://github.com/ehpor/hcipy), the optional optical backend
- [MAST data-use guidance](https://archive.stsci.edu/publishing/data-use), for
  the observed image templates and their retained telescope resolution/noise

The [website evidence view](https://xhvoid.github.io/Shack-Hartmann-AO-Simulation/#methods-home)
links numerical-check summaries, individual study methods and frozen source
records. The versioned ledgers remain authoritative for each recording's
parameters; literature-derived inputs do not amount to calibration of the full model.
