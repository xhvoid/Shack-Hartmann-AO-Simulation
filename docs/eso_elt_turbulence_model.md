# ESO E-ELT ten-layer turbulence model

This page documents the multi-layer atmosphere taken from ESO's E-ELT Design
Reference Mission, how the repository represents it, and how it was checked.

## Source

ESO's technical-data page
[AO performance and PSFs](https://www.eso.org/sci/facilities/eelt/science/drm/tech_data/ao/)
lists the atmosphere used in its OCTOPUS end-to-end AO simulations for the
E-ELT DRM PSF database (Le Louarn et al. 2004, Proc. SPIE 5490, 705; the 2005
simulation note linked from the page). Accessed 2026-10-14.

| Parameter | ESO value |
| --- | --- |
| Fried parameter r0 | 0.13 m at 0.5 µm |
| Seeing | 0.8 arcsec at 0.5 µm |
| Power spectrum | von Kármán |
| Outer scale L0 | 25 m |
| Inner scale | pixel size |
| Turbulent layers | 10 |

| Altitude | Fractional Cn² | Wind speed |
| --- | --- | --- |
| 0 m | 0.335 | 12.1 m/s |
| 600 m | 0.223 | 8.6 m/s |
| 1 200 m | 0.112 | 18.6 m/s |
| 2 500 m | 0.090 | 12.4 m/s |
| 5 000 m | 0.080 | 8.0 m/s |
| 9 000 m | 0.052 | 33.7 m/s |
| 11 500 m | 0.045 | 23.2 m/s |
| 12 800 m | 0.034 | 22.2 m/s |
| 14 500 m | 0.019 | 8.0 m/s |
| 18 500 m | 0.011 | 10.0 m/s |

The table is packaged verbatim, with structured `literature_derived`
provenance, as
[`literature_profiles/eso_elt_drm_ten_layer.json`](../src/shwfs_ao/resources/literature_profiles/eso_elt_drm_ten_layer.json).

Decisions the page leaves open, and how the repository resolves them:

- **Fractions sum to 1.001.** The printed fractions are rounded. The loader
  divides them by their printed sum, so the layers carry exactly the stated
  r0; `TurbulenceProfile.published_cn2_fraction_sum` keeps 1.001.
- **Seeing 0.8″ versus r0 = 0.13 m.** `0.98 λ/r0` gives 0.777″, which ESO
  rounds to 0.8″. The model uses r0. With L0 = 25 m the long-exposure FWHM
  is about 0.63″ (Tokovinin 2002).
- **Wind directions are not published.** Every layer moves toward +x by
  default, matching the single-layer profiles. Use
  `with_wind_directions(...)` to choose others. On-axis SCAO statistics depend
  on the speeds, not the azimuths.
- **Zenith angle is not stated.** The table is treated as a zenith profile.
  `at_zenith_angle(z)` scales r0 by `cos(z)^(3/5)` and layer ranges by `sec z`.
- **Inner scale = pixel size.** The screens carry no power above the pupil
  grid's Nyquist frequency, the same convention.

Derived quantities (the `TurbulenceProfile` properties, standard formulae):

| Quantity | Value |
| --- | --- |
| Kolmogorov seeing `0.98 λ/r0` | 0.777″ |
| Turbulence-weighted wind `(Σ fᵢ vᵢ^(5/3))^(3/5)` | 14.5 m/s |
| Coherence time `τ0 = 0.314 r0 / v̄` | 2.81 ms |
| Turbulence-weighted altitude `(Σ fᵢ hᵢ^(5/3))^(3/5)` | 4.42 km |
| Isoplanatic angle `θ0 = 0.314 r0 / h̄` | 1.90″ |
| Greenwood frequency `0.4265 v̄ / r0` | 47.6 Hz |
| Layer Fried parameters `r0 fᵢ^(-3/5)` | 0.25 m (ground) to 1.95 m (18.5 km) |

## Model: `native_layered`

`shwfs_ao.backends.native.layered_atmosphere.LayeredFrozenFlowAtmosphere`
implements the canonical `AtmosphereModel` protocol. Each layer is an
independent, absolutely normalized von Kármán phase screen with Fried
parameter `r0 fᵢ^(-3/5)`. Each layer moves with its own wind, and the pupil
sees the sum of all layers (on axis, geometric optics). The variances add,
so the summed phase carries exactly the integrated r0. No RMS rescaling is
applied.

The existing `native_frozen_flow_v2` screen cannot simply be stacked ten
times. Its subharmonics make a finite screen non-periodic, so a layer may
travel only `(screen − pupil)/2` pixels before the wrap seam reaches the pupil,
and every translated frame replays 16 FFTs. ESO's 33.7 m/s layer would use up
a 10 m pupil's travel budget in 0.3 s. The layered model splits the spectrum
instead:

- **Periodic band.** All FFT frequencies of a screen twice the pupil array,
  except the inner 9×9 block of cells. The band is exactly periodic, so any
  real translation is an exact Fourier phase ramp with no travel limit. All
  layers are summed in the Fourier domain and transformed together, one
  inverse FFT per frame.
- **Analytic low frequencies.** The inner cells, resolved into 4×4
  midpoint-quadrature nodes, plus three 3×3 subharmonic levels below the FFT
  band. These modes are evaluated directly at the translated coordinates, so
  they are exact at any time.

The periodic band repeats after a layer has travelled one screen period
(4 m for the 2 m profiles, 20 m for 10 m). `periodic_band_repeated` reports
when that has happened. Repetition makes long-exposure statistics less
independent but introduces no discontinuity.

Cost per frame with all ten ESO layers is 3.1 ms on a 72 px pupil and 36 ms
on a 384 px pupil. A single `native_frozen_flow_v2` layer, with its exact
spectral replay, costs 26 ms and 810 ms on the same grids.

## Validation

`tests/backends/native/test_layered_atmosphere.py` checks:

- **Discrete spectrum against the continuum.** The exact expected pupil
  variance of the discretization, with no Monte Carlo noise. The ESO model is
  within 0.5% of the von Kármán integral for piston-removed variance and
  within 1% for tip/tilt-removed variance, on 2 m/72 px and 10 m/384 px pupils.
- **Realizations against the spectrum.** 160 seeded realizations reproduce
  the expected tilt-removed variance.
- **Frozen flow.** Integer and half-pixel translations agree with the shifted
  initial screen to 1e-12 rad. A sub-pixel step changes the frame rather than
  rounding it away.
- **Unbounded travel.** Frames remain valid beyond one screen period.
- **Contracts.** Piston-free OPD in metres with NaN outside the pupil,
  deterministic replay, independent per-layer random streams, and identity
  hashes.

The demo additionally compares the phase structure function averaged over
256 independent ESO screens with the von Kármán `D(r)`. The two agree within
2.5% for 2 px ≤ r ≤ 1 m: the ratio runs from 0.981 at 2 px to 1.025 at 1 m.
At 1 m, 256 screens of a 2 m pupil give a standard error of about 5%; the
discrete model's exact expectation there is 0.996. A one-pixel separation is
8% low; that is the pixel-scale cutoff.

### Cross-check against HCIPy

`atmosphere_model = "hcipy_layered"` (with `backend = "hcipy"`) builds the
same ten layers with HCIPy: one `InfiniteAtmosphericLayer` per profile layer,
with Fried parameter `r0 fᵢ^(-3/5)` and the layer's wind and altitude. HCIPy
shares no code or random numbers with the native model. It extrudes each
layer row by row from the exact von Kármán covariance (Assémat et al. 2006)
rather than synthesizing a spectrum, so it is an independent check of the
native layer split, normalization and frozen flow.

`tests/backends/hcipy/test_hcipy_layered_atmosphere.py` compares ensemble
statistics on the ESO profile's 2 m / 72 px pupil, with phase in radians at
500 nm. HCIPy frames are taken every 0.25 s from 0.5 s on, after every layer
has crossed the pupil grid and its initial screen has been replaced by
extruded rows. Native frames are independent t = 0 realizations, which the
stationary, exactly translating model permits. Standard errors treat each
HCIPy realization's mean as one independent sample. The slow tier, 512 HCIPy
frames from 32 realizations against 1024 native realizations, measured:

| Statistic | HCIPy / native | Gate |
| --- | --- | --- |
| Piston-removed pupil variance | 0.93 ± 0.04 | ±20% |
| Piston- and tip/tilt-removed pupil variance | 1.03 ± 0.03 | ±10% |
| `D(r)`, r = 2 px (5.6 cm) | 1.010 ± 0.010 | ±4% |
| `D(r)`, r = 4 px | 0.993 ± 0.013 | ±5% |
| `D(r)`, r = 8 px | 0.983 ± 0.017 | ±7% |
| `D(r)`, r = 16 px (0.44 m) | 0.969 ± 0.024 | ±10% |
| Temporal structure function, τ = 3 ms | 1.035 ± 0.007 | ±6% |
| Temporal structure function, τ = 10 ms | 1.008 ± 0.012 | ±6% |
| Temporal structure function, τ = 30 ms | 1.015 ± 0.022 | ±10% |
| Co-moving, τ = 10 ms, 5 px along the flow | 0.92 ± 0.04 | ±20% |
| Counter-moving, τ = 10 ms, 5 px against the flow | 1.006 ± 0.017 | ±8% |

The temporal structure function is the pupil mean of
`(φ(t + τ) − φ(t))²`. The co-moving and counter-moving statistics shift the
later frame by the turbulence-weighted wind's 5 px (14.5 m/s × 10 ms) along
and against +x before differencing. They depend on how far each layer's own
speed is from that common shift, and so on which wind belongs to which
layer. Every gate is at least three standard errors. A comparison passes
only if its ratio lies inside the gate. The co-moving gate also allows for
the sub-2 px difference described below, because that statistic is
dominated by layers moving close to 5 px. The non-slow tier, which runs in
CI, uses 120 HCIPy frames and 256 native realizations with gates about twice
as wide.

Two controls show the comparison resolves the winds:

- **Flow direction.** In both backends the counter-moving statistic is about
  six times the co-moving one (5.8 native, 6.3 HCIPy), so every layer moves
  toward +x.
- **Wind-to-layer assignment.** The native model is rerun from the same
  seeds with the ten winds reversed, so every speed is kept but the ground
  layer gets 10 m/s and the 18.5 km layer 12.1 m/s. Its co-moving statistic
  rises by 62% and its 3 ms temporal structure function by 10%, so the
  reversed atmosphere fails the gates the correctly mapped HCIPy layers
  pass.

The backends differ, by construction, in three places that the gates
exclude. These measurements are not test-gated:

- **Below 2 px and 3 ms.** Extruded HCIPy screens have `D(1 px)` 5% above
  native, and the 1 ms temporal structure function is 7% above. HCIPy
  keeps the exact pixel-scale covariance: its `D(1 px)` is within 1% of the
  von Kármán value. The native band carries no power above the grid's
  Nyquist frequency, so its `D(1 px)` is 7% low (see inner scale above).
  HCIPy also interpolates sub-pixel positions bilinearly.
- **HCIPy's initial screens.** Until a layer has moved one grid width (2 m,
  0.06–0.25 s for these winds), HCIPy shows the layer's initial screen,
  drawn by a separate finite spectral layer. For a single layer over 400
  realizations, that screen's `D(r)` is 4% below the von Kármán value at
  2–8 px and 10% below at 1 px. A 150-frame `hcipy_layered` run at 1 kHz
  therefore mostly sees initial screens. Over 400 ESO realizations, native
  `D(r)` is within 1% of the analytic value at 2–32 px.
- **Low orders.** The piston-removed variance is dominated by tip/tilt and
  varies by about 80% between realizations. With a different seed, the
  tip/tilt-removed ratio was 0.94 ± 0.03; together the two seeds give about
  0.985. HCIPy documents that its extrusion loses low orders at large outer
  scales. A loss of a few percent can be neither confirmed nor excluded at
  this sample size.

## Use in the SCAO simulation

Profile schema 4 adds `atmosphere.layers` to the serialized SCAO profile, and
`atmosphere_model = "native_layered"` selects the model. Single-layer blocks
hash exactly as before, so no published profile identity moved.

The packaged profile `eso_turbulence_2m_detector@1` is
`portfolio_2m_detector@4` (2 m, 7×7 detector-level Shack-Hartmann, 1 kHz,
two-frame latency, 150 frames) with only the atmosphere replaced by ESO's ten
layers:

```python
from shwfs_ao.experiments import run_closed_loop
from shwfs_ao.io import load_system_profile

config = load_system_profile("eso_turbulence_2m_detector", 1)
history = run_closed_loop(config)
```

The same atmosphere runs through the HCIPy backend as `hcipy_layered`. The
HCIPy lenslet model needs whole block windows, which 72 px over 7 lenslets
are not, so an all-HCIPy run states a 70 px pupil and 10 px windows:

```python
from dataclasses import replace

from shwfs_ao.io import load_system_profile

eso = load_system_profile("eso_turbulence_2m_detector", 1)
hcipy_config = replace(
    eso,
    backend="hcipy",
    atmosphere_model="hcipy_layered",
    pupil_pixels=70,
    wfs=replace(eso.wfs, detector_window_px=10),
)
```

The generator is part of the observing conditions, so this configuration has
its own `observing_conditions_hash`. `native_layered` under
`backend = "hcipy"` is refused rather than silently swapping generators.

Any other profile can be driven by the same turbulence:

```python
from dataclasses import replace

from shwfs_ao.io import eso_elt_turbulence_profile, load_system_profile

base = load_system_profile("research_2m_detector", 3)
eso = eso_elt_turbulence_profile(wind_directions_deg=[36.0 * i for i in range(10)])
config = replace(
    base,
    atmosphere_model="native_layered",
    atmosphere=eso.to_atmosphere_config(),
    record_schema_version=4,
)
```

The demo script runs the profile study and writes the figure and tables to
`figures/eso_elt_turbulence/`:

```bash
python examples/run_eso_elt_turbulence_demo.py
```

Over 8 realizations of 150 frames (frames 50 onwards), the 2 m system
corrects ESO's turbulence from 444 to 325 nm RMS. Under its single 10 m/s
layer it goes from 462 to 294 nm. ESO's faster turbulence-weighted wind
(14.5 m/s) leaves a larger temporal residual, although its open-loop
turbulence is slightly weaker. These short-exposure numbers carry a
realization scatter of tens of nanometres.

## Scope

- On-axis SCAO only. Layer altitude is recorded but unused: there is no
  anisoplanatism, cone effect, LGS, tomography or scintillation.
- The HCIPy backend builds layered profiles only as `hcipy_layered`, one
  HCIPy layer per profile layer. It refuses `native_layered` and never
  flattens layers into one. Its first frames show HCIPy's slightly weaker
  initial screens (see the cross-check above).
- ESO's system parameters (84×84 sub-apertures, 85×85 actuators, 500 Hz,
  3-frame delay, LGS asterisms) are not part of the turbulence profile, and
  the repository's 2 m system is not an ELT model.
