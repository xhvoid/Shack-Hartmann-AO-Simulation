# Notebook 12 — TIPTOP performance modelling: portfolio notes

Supporting material for
[`12_TIPTOP_performance_modelling.ipynb`](../notebooks/studies/12_TIPTOP_performance_modelling.ipynb).
Numerical claims below come from its final executed outputs and
[`tiptop_validation.json`](../notebooks/studies/tiptop_validation.json).
The reported model combines P3's sampled correction-band residual with a
continuous von Kármán fitting tail, propagated with MASTSEL. It is an explicitly
attributed adapter result, rather than an unmodified TIPTOP prediction.

## 1. Suggested README description

Short form:

> `12_TIPTOP_performance_modelling.ipynb` studies a representative 8 m-class,
> eight-LGS, three-DM MCAO system using TIPTOP/P3 and MASTSEL. It compares seeing,
> outer scale, turbulence altitude distribution and guide-star geometry across
> a 0–30″ H-band science field. An explicit fitting-tail completion, error-budget
> closure and separate image-sampling checks accompany the performance results.

Longer form:

> A system-level AO sensitivity study built on
> [TIPTOP](https://github.com/astro-tiptop/TIPTOP),
> [P3](https://github.com/astro-tiptop/P3) and MASTSEL. The configuration is adapted
> from the distributed `MavisMCAO.ini` example and uses representative parameters;
> it does not claim to reproduce an official instrument design or on-sky data.
>
> The study exposes an important numerical dependency: the original finite-grid
> P3 fitting term is 47.895 nm, rises to 64.920 nm when the native image field is
> doubled, and becomes 71.300 nm when the same atmospheric PSD is integrated
> above the circular correction cutoff to infinity. The completed baseline has
> 131.688 nm total on-axis residual, peak Strehl 0.780916 and 0.635403 of the
> computational-field flux inside a 50 mas radius. Tomography contributes 50.9%
> of that completed variance, while fitting contributes 29.3%.
>
> At fixed seeing, redistributing turbulence in altitude changes on-axis Strehl
> by 0.07766. Across a 0.5″–1.2″ seeing sweep, energy inside 50 mas falls by 27.1%
> relative to its good-seeing value. The measured core FWHM changes weakly,
> from 43.194 to 43.449 mas at 5 mas pixels. Separate focal-sampling tests expose
> the estimator's remaining absolute width bias, so a nearly stable core is
> not presented as proof that the whole PSF is insensitive to seeing.
>
> The final run records 15 model evaluations and 105 completed science-direction
> PSFs, including a repeated baseline. Their timed model-plus-completion calls
> sum to 84.1 s on the recorded machine; this is not a portable runtime promise
> or the whole notebook's wall-clock time. Analytical sensitivity modelling
> complements explicit time-domain studies of controller behavior, transients
> and nonlinear sensing.

### Optional dependency and supported scope

The repository already declares a `tiptop` extra. On Python 3.11 or newer:

```bash
pip install -e ".[tiptop]"
```

The validated upstream versions are pinned in `pyproject.toml`:

```toml
tiptop = [
    "astro-tiptop==1.5.1",
    "astro-p3==1.6.2",
    "mastsel==1.5.2",
]
```

The notebook checks these versions before running. The adapter is deliberately
limited to the tested CPU, single-wavelength, HO-only branch with a generated
annular pupil and circular correction cutoff. File-loaded pupils/apodizers,
static aberrations, separate low-order/NGS branches and additional unvalidated
error terms are rejected. Extending that scope requires new validation.

## 2. CV / portfolio bullets

- Built a representative 8 m-class MCAO sensitivity study using **TIPTOP/P3 and
  MASTSEL**, with 15 recorded model evaluations, 105 science-direction PSFs and
  a residual-PSD error-budget comparison across atmospheric and guide-star
  configurations.
- Identified finite-frequency coverage in a fitting-error estimate and added
  an explicitly attributed **continuous von Kármán fitting-tail completion**:
  47.895 nm on the original grid versus 71.300 nm with the infinite tail.
  Checked error-budget closure and independence from the native output field.
- Demonstrated the importance of turbulence altitude at fixed integrated
  seeing: the tested profiles change the isoplanatic angle by a factor of
  1.91 and on-axis completed Strehl by 0.07766 while preserving `r0` and fitting
  error.
- Compared **Strehl, fixed-aperture energy and interpolated core FWHM** rather
  than treating one metric as a complete PSF specification. Quantified focal
  sampling separately from computational-grid and quadrature convergence.
- Used analytical AO modelling for sensitivity studies alongside an explicit
  Shack–Hartmann closed-loop simulator for time-dependent behavior, while
  keeping the validation limits of the two models separate.

## 3. Interview explanation (60–90 seconds)

> I had an explicit closed-loop Shack–Hartmann simulator and wanted to explore
> system-level sensitivities with a complementary analytical model. I used
> TIPTOP/P3 for a representative eight-metre system with eight laser guide
> stars and three deformable mirrors, then varied seeing, outer scale,
> turbulence altitude and guide-star geometry.
>
> The most useful finding was numerical. The original fitting-error term was
> about 48 nanometres, but it changed when I increased the model's frequency
> coverage. I integrated the missing atmospheric tail explicitly and obtained
> 71.3 nanometres. I kept the raw P3 result visible, checked the combined error
> budget, and validated the PSF calculation at several sampling settings.
>
> The physical comparisons then became easier to interpret. Moving turbulence
> in altitude at fixed seeing changed on-axis Strehl by about 0.078. Worsening
> seeing reduced energy inside a 50-milliarcsecond aperture by 27%, while the
> measured core width moved only about a quarter of a milliarcsecond. That
> width was not exactly constant, and its absolute sampling bias needed a
> separate check.
>
> The main lesson was to distinguish a reproducible calculation from a
> validated performance prediction. The analytical model is useful for
> sensitivity studies, but these results do not demonstrate on-sky accuracy or
> establish controller stability. That needs a matched time-domain study or
> measurements of the actual system.

## 4. Verified implementation facts and numerical limits

| Item | Evidence and interpretation |
| --- | --- |
| Model access | `baseSimulation` exposes the PSF results and P3 model; the notebook requests `getHoErrorBreakDown=True`. |
| Budget decomposition | P3's `wfeST` contains servo-lag and tomography; adding `wfeST`, `wfeS` and `wfeTomo` together would double-count. The completed budget uses disjoint terms. |
| Raw versus completed budget | Baseline raw total/fitting are 120.763/47.895 nm; completed total/fitting are 131.688/71.300 nm. On-axis tomography is 93.982 nm, or 50.9% of completed variance. |
| PSD units and frequency increment | The adapter reverses P3's stored nanometre/cell scaling, uses the actual PSD grid increment for the retained correction-band variance, and replaces only the finite fitting term. |
| Seeing and wavelength | Input seeing is at zenith and 500 nm. The executed check gives line-of-sight `r0 = 0.115418 m` at 500 nm and `0.483604 m` at H band. |
| Pupil coordinates | P3 generates the annulus with inclusive `linspace(-D/2, D/2, N)` coordinates. The adapter uses **D/(N−1)** for the pupil autocorrelation spacing. |
| OTF support | The complete interpolated autocorrelation is retained. A hard circular crop at radius D removes interpolation-edge values and creates negative diffraction rings; propagated PSFs instead retain a material-negativity check. |
| Flux normalization | Each PSF is normalized once on the full computational field before cropping. The baseline science crop contains about 95.18% of that flux and is never renormalized. EE therefore retains its full-field denominator. |
| Native output-field check | Changing the native field from 400 to 800 pixels changes the raw fitting term to 64.920 nm. Completed PSFs agree exactly for this check, and completed fitting remains 71.300 nm. |
| Error-budget closure | The maximum difference between the completed OTF variance budget and the quadrature sum of its terms is `5.97e-13 nm`. |
| Determinism | A fresh repeated baseline has maximum PSF difference zero in the pinned environment. This is a reproducibility check, not an accuracy guarantee. |

### Three different convergence questions

1. **Computational OTF grid, fixed 5 mas pixels.** Increasing 1024 to 2048
   changes peak Strehl by at most `1.10e-6`, EE(50 mas) by `8.88e-6`, and contour
   FWHM by `7.33e-5 mas` across all seven directions. Crop energy changes by up
   to `0.001807`, so the finite computational field still affects the remote
   halo. These checks do not establish focal-pixel accuracy.
2. **Fitting-tail quadrature.** Increasing the quadrature from 256 to 512 nodes
   changes the tested metrics by at most `9.89e-13` relative. This tests the
   tail integration for these configurations, not the whole physical model.
3. **Focal pixel scale.** A separate P3 calculation at 2.5 mas pixels changes
   the seven baseline FWHMs by up to **0.371%** compared with 5 mas pixels;
   on-axis width changes from 43.2805 to 43.4410 mas. Peak Strehl changes by at
   most `1.13e-5` and EE(50 mas) by `5.03e-5`. For an independent analytic
   annular-aperture reference, the continuous FWHM is 43.3031 mas, while the
   sampled contour estimator gives 43.0881 mas at 5 mas pixels and 43.2497 mas
   at 2.5 mas pixels: biases of **−0.497%** and **−0.123%**, respectively.

The seeing-sweep FWHM change of 0.256 mas is an observed differential change at
fixed sampling. It should not be quoted as an absolute width accurate to the
very small computational-grid convergence difference. The focal refinement
covers the baseline's seven directions; it is not a full refinement of every
seeing, profile and asterism operating point.

These results retain P3's analytical control and independence assumptions,
finite correction-band sampling and a finite pupil raster. They do not show
that the chosen MCAO controller is stable in a matched time-domain model,
validate an actual instrument, or establish universal guide-star geometry
optima. The notebook and its machine-readable evidence should accompany any
portfolio excerpt that quotes the numbers.
