# Shack-Hartmann AO Simulation

A Python model of a Shack–Hartmann adaptive optics loop, written so I could
follow a measurement all the way from the detector pixels to the science
image. The sensor sees where each lenslet spot lands, the reconstructor turns
those displacements into mirror commands, and whatever wavefront is left over
decides what the star looks like in the final image.

[Open AO Explorer](https://xhvoid.github.io/Shack-Hartmann-AO-Simulation/) · [Design decisions](docs/design-decisions.md) · [Run an example](#run-an-example)

## What came out of it

Most of what I learned is in the figures below, but a few results stuck with me:

- The 2.2 m loop lost lock just under a second in, when spots started dropping
  out and the small singular values of the reconstructor blew up the commands.
  Raising the TSVD cutoff from 0.001 to 0.05 and replaying the same atmosphere
  got it through the full two seconds without the mirror reaching its stroke
  limit.
- Moving the science target away from the guide star costs Strehl steadily.
  At 20 arcsec the long-exposure peak is about three quarters of the on-axis
  value, with the same mirror commands for both.
- With two frames of delay, pushing the gain up to 1.0 made the loop worse than
  no correction at all. The gain–delay figure shows where that turns over.
- Spot centroids improve with photon count very close to the square-root
  scaling you would expect from photon noise. At 500 photons per subaperture,
  though, the quality cuts throw every spot away before the noise statistics
  even come into it.
- In the 8 m MCAO model, tomography is the single largest term in the error
  budget, about half the residual variance, and roughly two thirds of the
  on-axis H-band light lands within 50 milliarcseconds.

I also ran the same 2 m geometry through TIPTOP. The two codes disagree by a
factor of about two in residual RMS, and most of that gap is tilt that this
small loop leaves behind: [Compare the 2 m loop with TIPTOP](docs/scao-comparison/README.md).

## Results

### Closed-loop correction

![Open-loop and corrected wavefront RMS over 12 frames](figures/canonical_closed_loop_control.png)

This 1 m example runs at 500 Hz with gain 0.5 and detector noise switched
off. Over the last six frames of the sequence, correction brought the mean
wavefront RMS down from 148.6 to 84.4 nm.
[Recorded control experiment](https://github.com/xhvoid/Shack-Hartmann-AO-Simulation/blob/14611da9a92c6c4de59ee60de8fb2d23f2bbc7c3/notebooks/tutorials/04_closed_loop_control.ipynb)

### Science targets away from the guide star

In the 2.2 m model a single natural guide star sets the mirror correction, and
I then look at four targets at increasing separation from it. Light from a
target farther out crosses the high-altitude layers at a different place than
the guide-star light did, so the correction fits it less and less well.

![Long-exposure PSFs at 0, 5, 10, and 20 arcsec, on a common logarithmic scale](https://raw.githubusercontent.com/xhvoid/Shack-Hartmann-AO-Simulation/7aca875e5e34265c3f9ead97ae99da55663bcce7/docs/research/scao_off_axis_v1/evidence/demo_22m/reproduction/psf_comparison.png)

Each panel is the same 1.8-second exposure (1,350 frames), centred on a
different target. In this macOS run at 1.65 µm the interpolated peak Strehl
drops from 0.448 on axis to 0.436, 0.398 and 0.338 at 5, 10 and 20 arcsec.

![Long-exposure and mean instantaneous Strehl against guide-star separation](https://raw.githubusercontent.com/xhvoid/Shack-Hartmann-AO-Simulation/7aca875e5e34265c3f9ead97ae99da55663bcce7/docs/research/scao_off_axis_v1/evidence/demo_22m/reproduction/strehl_vs_separation.png)

The second figure separates two ways of quoting Strehl from the same exposure.
If I take the brightest pixel of every individual frame and average those, the
on-axis value is 0.750. If I average the frames first and then read the peak,
it is 0.448. The core wanders between frames, so the accumulated image spreads
its light over several pixels. Which number you want depends on whether you
care about a single frame or a real exposure.
[Linux reference values and measurement details](https://github.com/xhvoid/Shack-Hartmann-AO-Simulation/blob/7aca875e5e34265c3f9ead97ae99da55663bcce7/docs/scao_off_axis_science.md#reading-the-figures) · [Off-axis implementation (PR #10)](https://github.com/xhvoid/Shack-Hartmann-AO-Simulation/pull/10)

### Sensor calibration and photon noise

![Measured centroid displacement for independent x and y tilt inputs](figures/canonical_sensor_calibration.png)

A 2 µrad tilt moves the spot centroids by 2.701 pixels along the driven axis.
The purely geometric prediction from the pixel scale is 2.902 pixels, so the
measured gain comes out about 7% low; the tutorial puts that down to the finite
centroid window and spot sampling. The response on the perpendicular axis is
negligible in this symmetric 8 × 8 lenslet model.
[Calibration experiment](https://github.com/xhvoid/Shack-Hartmann-AO-Simulation/blob/14611da9a92c6c4de59ee60de8fb2d23f2bbc7c3/notebooks/tutorials/01_geometric_shwfs.ipynb)

![Centroid RMS error and the fraction of accepted measurements against photon count](figures/canonical_detector_centroiding.png)

Over 12 realizations, the RMS error of the accepted centroid components falls
from 0.199 pixels at 1,000 photons per subaperture per frame to 0.0194 at
100,000, which is almost exactly the square-root scaling of photon noise. At
500 photons there is no point on the curve at all, because every measurement
failed the quality cuts.
[Detector experiment](https://github.com/xhvoid/Shack-Hartmann-AO-Simulation/blob/14611da9a92c6c4de59ee60de8fb2d23f2bbc7c3/notebooks/tutorials/02_detector_centroiding.ipynb)

### Reconstruction and control

![Singular spectrum of the interaction matrix and command reconstruction error](figures/canonical_tsvd_regularization.png)

The reconstructor is a truncated singular-value decomposition of the measured
interaction matrix, so the main knob is how many modes to keep. In this noisy
example, going from 12 to 29 retained modes cut the command RMS error from
62.94 to 8.58 nm.
[Reconstruction experiment](https://github.com/xhvoid/Shack-Hartmann-AO-Simulation/blob/14611da9a92c6c4de59ee60de8fb2d23f2bbc7c3/notebooks/tutorials/03_tsvd_regularization.ipynb)

![Closed-loop to open-loop wavefront RMS ratio for five gains and three delays](figures/canonical_gain_latency.png)

With a two-frame delay, raising the gain from 0.2 to 1.0 took the
corrected-to-open RMS ratio from 0.723 to 1.746. At the higher gains the
delayed loop amplifies the disturbance instead of removing it.
[Gain and delay experiment](https://github.com/xhvoid/Shack-Hartmann-AO-Simulation/blob/14611da9a92c6c4de59ee60de8fb2d23f2bbc7c3/notebooks/studies/noise_latency_gain.ipynb)

![Residual wavefront error and estimated H-band Strehl for three mirror grids](figures/canonical_correction_order.png)

With the same atmosphere and sensor, mirrors with 13, 29 and 49 active
actuators left residuals of 246.7, 229.6 and 227.5 nm RMS. Going from 29 to
49 actuators barely helps, which suggests fitting error is not what limits
this loop. The plotted H-band Strehl is just the Maréchal conversion of those
RMS values.
[Mirror-grid comparison](https://github.com/xhvoid/Shack-Hartmann-AO-Simulation/blob/14611da9a92c6c4de59ee60de8fb2d23f2bbc7c3/notebooks/studies/high_order_scao.ipynb)

### H-band PSFs and the MCAO error budget

The multi-conjugate model is a different kind of calculation from the rest of
this repository. It is an 8 m-class telescope with eight laser guide stars and
three deformable mirrors, and instead of running a time-domain loop it takes
the TIPTOP/P3 residual spectrum, adds a high-frequency fitting term, and lets
MASTSEL compute the PSF.
[Model and numerical checks](https://github.com/xhvoid/Shack-Hartmann-AO-Simulation/blob/14611da9a92c6c4de59ee60de8fb2d23f2bbc7c3/docs/notebook12_tiptop_portfolio_notes.md)

![H-band PSF core, halo, and encircled energy on axis and 30 arcsec off axis](figures/tiptop_baseline_psf.png)

In the 1.65 µm baseline the on-axis peak Strehl is 0.781 and 63.5% of the
energy falls within a 50 milliarcsecond radius. The energy fraction is taken
relative to the flux of the whole computational field.

![Residual variance by source and total wavefront error before and after including the fitting tail](figures/tiptop_error_budget.png)

Tomography and fitting account for 50.9% and 29.3% of the baseline residual
variance. Swapping the finite-grid fitting term for its continuous
high-frequency integral raises the total from 120.8 to 131.7 nm RMS, so the
finite grid was missing about 9% of the total. I check that the budget terms
add up against the same residual spectrum that goes into the PSF, so the two
views of the error are never computed from different inputs.

![Peak Strehl, 50 milliarcsecond aperture energy, and core width over a seeing sweep](figures/tiptop_seeing_sensitivity.png)

As seeing worsens from 0.5 to 1.2 arcsec, the energy inside 50 milliarcseconds
drops by 27.1% relative to the good-seeing case, while the sampled full width
at half maximum hardly moves, from 43.19 to 43.45 milliarcseconds. The core
stays the same size; it just holds less of the light.

### Layered atmospheric turbulence

![ESO ten-layer profile, phase screen, structure function, and residual wavefront RMS](figures/eso_elt_turbulence/eso_elt_turbulence_demo.png)

I ran the same 2 m loop under two atmospheres. With the ten layers of the ESO
E-ELT design reference, correction took the wavefront RMS from 444 to 325 nm;
with a single frozen-flow layer it went from 462 to 294 nm. Both numbers use
frames 50–149 from eight realizations. The layered atmosphere is harder to
correct even though it starts from a slightly lower uncorrected RMS.
[Layer parameters and experiment](https://github.com/xhvoid/Shack-Hartmann-AO-Simulation/blob/14611da9a92c6c4de59ee60de8fb2d23f2bbc7c3/docs/eso_elt_turbulence_model.md)

<details>
<summary>Earlier detector, calibration, and near-infrared imaging studies (14 figures)</summary>

The detector experiments feed public seeing and photometry measurements into a synthetic AO loop. [Data sources and acknowledgements](DATA_LICENSES.md)

![Public data overview](figures/detector_level_SCAO/public_data_overview.png)

Seeing conditions come from ESO Paranal measurements and the photometric inputs from the 2MASS and Pan-STARRS catalogues.

![SVO JHK filter curves](figures/detector_level_SCAO/public_filter_curves_jhk.png)

The SVO 2MASS J, H and Ks transmission curves provide the wavelength weights for the science bands.

![Public-data WFS photon budget](figures/detector_level_SCAO/public_data_photon_budget.png)

The guide-star photon budget at 700 nm is estimated from Pan-STARRS photometry and an assumed throughput.

![Public-data-informed AO photon scan](figures/detector_level_SCAO/public_data_informed_ao_photon_scan.png)

This scan varies the guide-star flux in the simulated detector loop, while the measured seeing sets the amplitude of the synthetic phase sequence.

![Public-data-informed AO scenarios](figures/detector_level_SCAO/public_data_informed_error_budget.png)

Five scenarios vary the observing conditions and the instrumental terms: read noise, mirror stroke and misregistration.

![High-order SCAO J/H/K PSF diagnostic](figures/high_order_ao_jhk_psf.png)

Diffraction-limited, uncorrected and AO-corrected PSFs side by side, showing how the residual wavefront redistributes light in J, H and K.

![High-order AO residual RMS history](figures/high_order_ao_rms_history.png)

The orange curve drops sharply in the first few milliseconds. The blue points are the residual for an ideal mirror fit to the same wavefront.

![High-order AO phase maps](figures/high_order_ao_phase_maps.png)

Maps of the atmospheric wavefront, the applied mirror correction and the residual, showing which spatial features survive the correction.

![Noise, latency, and gain stability scan](figures/noise_latency_gain_stability.png)

An operating-point scan over photon flux, detector read noise, loop gain and delay. Hatched cells are the unstable or command-limited cases.

![Fast detector-level error-budget scenarios](figures/detector_level_SCAO/fast_error_budget.png)

The synthetic 2 m scenario comparison builds its disturbance directly in the mirror's command space, which is why the ideal case reaches an unrealistically high Strehl.

![Exploratory PWFS detector images](figures/PWFS_detector_images.png)

The pyramid sensor produces four pupil images. From left to right: a flat wavefront, atmospheric aberration, and the same aberration with detector noise.

![Sampling versus correction order](figures/sampling_vs_correction_order.png)

Wavefront-sensor sampling and the number of controlled modes are varied together to see how each affects the reconstruction.

![Detector-level reconstruction](figures/detector_level_reconstruction.png)

The input wavefront, its reconstruction from the lenslet spot centroids, and their difference. The residual panel uses a finer colour scale.

![Poke-amplitude scan](figures/detector_level_SCAO/poke_amplitude_scan.png)

The calibration varies the amplitude of the positive and negative actuator pokes used to measure the interaction matrix.

</details>

## Install

You need Python 3.10 or later. From the repository root:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install .
```

On Windows PowerShell the activation step is `.\.venv\Scripts\Activate.ps1`.
If you plan to edit the package, install it with `python -m pip install -e .`
instead. The default backend only needs NumPy and SciPy; for the HCIPy
backend, install with `python -m pip install '.[hcipy]'`.

## Run an example

The detector example runs a synthetic 2 m closed loop and writes the detector
and wavefront measurements to `detector_level_demo_output/detector_level_demo.json`:

```bash
python examples/run_detector_level_demo.py
```

Two shorter examples pick out individual parts of the loop. The first plots
how a prescribed wavefront shifts the lenslet spots; the second scales a phase
map and reports its propagated peak Strehl next to the Maréchal estimate from
the RMS.

```bash
python examples/run_shwfs_centroid_demo.py
python examples/run_psf_strehl_demo.py
```

Both write their plots under `outputs/examples/detector_level_SCAO/`. Set
`AO_DEMO_OUTPUT_DIR` if you want them somewhere else.

To look at the 2 m residual wavefront from Python, load the same profile and
read the history after each mirror update:

```python
from shwfs_ao.io.configs import load_system_profile
from shwfs_ao.experiments.scao import run_closed_loop

config = load_system_profile("det_emccd_2m_synthetic", 1)
history = run_closed_loop(config)
print("Residual after each update (nm):", history.post_update_residual_opd_rms_m * 1e9)
```

Everything inside the package is in metres, OPD and wavelength alike; the
example multiplies by 1e9 for display. One thing to keep in mind when comparing
with the Explorer: its images are made from the wavefront *before* the next
mirror update, whereas the history above is read *after* it. Each recording
on the site lists its own settings and exposure window.

## Limitations

The pupils, mirror influence functions and detector responses are idealised
models, and none of this has been calibrated against a real instrument. The
2.2 m repair has only been tested on the one two-second trajectory it was
built for, and the recovery rule I added alongside it never had to act in that
run, so I cannot say much about how it behaves. The 42 m pupil follows the
historical E-ELT design rather than the current 39 m ELT. Segment phasing and
calibration against on-sky telemetry are instrument problems I have not
touched.

- [Model conventions and sources](docs/methods.md)
- [Component checks, numerical repairs and remaining limits](docs/verification-summary.md)
- [Reproducing examples and checking saved results](docs/reproducing.md)
- [Selected studies and their evidence](https://xhvoid.github.io/Shack-Hartmann-AO-Simulation/#studies)

The simulation code and versioned profiles are in [src/shwfs_ao](src/shwfs_ao/).
The [examples](examples/) directory holds the scripts above and [tests](tests/)
the component checks. The Explorer's source and recordings live on the
[website branch](https://github.com/xhvoid/Shack-Hartmann-AO-Simulation/tree/website).

The code is under the [MIT licence](LICENSE). The [data licences](DATA_LICENSES.md)
list the sources and terms for the third-party data.
