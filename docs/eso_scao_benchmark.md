# Comparing the 5 m, 12 m and 42 m loops with TIPTOP/P3

I used the same ten-layer atmospheric profile in the native Shack–Hartmann loop and the Fourier model in TIPTOP 1.5.1 / P3 1.6.2. The three systems use 0.5 m subapertures, a Fried length of 0.13 m at 500 nm, and an on-axis guide star at zenith. Each loop runs at 500 Hz with gain 0.4. A native two-frame latency corresponds to three delay steps in P3.

## What the filter changes

The alternating pattern of neighbouring mirror actuators is called *waffle*. Several patterns close to it produce very little spot motion. The filter removes those patterns from each command increment. I switched it on and off at a fixed Tikhonov factor of 0.001, with detector noise off.

| Aperture | Native RMS, filter off (nm) | Native RMS, cutoff 0.35 (nm) | P3 RMS (nm) | Filtered native / P3 Strehl at 2.2 µm |
| --- | ---: | ---: | ---: | ---: |
| 5 m | 192.0 ± 1.4 | 173.5 ± 0.9 | 154.1 | 0.784 / 0.813 |
| 12 m | 183.2 ± 2.0 | 172.1 ± 1.5 | 155.9 | 0.787 / 0.816 |
| 42 m | 173.6 | 168.06 ± 0.65 | 156.45 | 0.795 / 0.818 |

The 5 m and 12 m means each cover five realizations. At 42 m I have three filtered realizations and one unfiltered run. On the one atmosphere common to both, the filter took the residual from 173.65 to 167.17 nm. The 5 m averages use 1,800 settled frames per realization, the others 900. RMS is the square root of the mean piston-removed pupil variance. The ± values are standard errors across realizations.

For P3 I integrated fitting power over the same spatial band as the native screens and excluded chromatism. The P3 Strehl values use the 1,024-pixel image and approximate exponential corrections for those two changes. The native Strehl comes from the accumulated image. [P3 results](scao-comparison/layered/p3.csv) · [5 m input](scao-comparison/layered/5m.ini) · [12 m input](scao-comparison/layered/12m.ini) · [42 m input](scao-comparison/layered/42m.ini)

## Where the 12 m residual comes from

I used twelve noiseless realizations with 500 settled frames each to look inside the 12 m result. At a filter cutoff of 0.35 and damping of 0.001 the image loop left 29,692 nm² of residual variance. P3 gave 24,311 nm². I fitted the native mirror's tent-shaped influence functions with a free piston, then repeated each trajectory using a separately calibrated sensor that reads the wavefront gradient across each subaperture.

| Contribution to the 5,381 nm² difference | Variance (nm²) | Share |
| --- | ---: | ---: |
| Native mirror fit above P3's fitting floor | 2,387 ± 94 | 44% |
| Image sensor and its reconstructor above the geometric sensor and its reconstructor | 2,032 ± 73 | 38% |
| Geometric loop above P3 within the mirror's controllable space | 962 ± 251 | 18% |

I also tried forming each spot from 24 wavefront samples across a subaperture instead of 12. Against a geometric sensor that kept the coarse gradient stencil on fully illuminated subapertures, the image-sensor excess fell by 510 ± 84 nm². Changing grids gave different atmospheric realizations. On the finer grid I could widen the centroid window from 23 to 47 pixels on the very same wavefronts. That removed another 614 ± 20 nm², leaving 908 ± 26 nm² above the geometric loop.

## Choosing the v3 damping

All three v3 profiles use the 0.35 filter. I scanned the Tikhonov factor on paired atmospheres with equal weights for the slope measurements. The table gives the square root of the mean total residual variance, in nm.

| Tikhonov factor | 5 m, five realizations | 12 m, twelve realizations | 42 m, three realizations |
| ---: | ---: | ---: | ---: |
| 0.001 | 173.53 | 172.31 | 168.06 |
| 0.003 | 173.51 | 172.28 | — |
| 0.01 | 173.34 | 171.96 | — |
| 0.02 | 172.97 | 171.39 | — |
| 0.03 | 172.66 | 171.06 | 168.19 |
| 0.05 | 172.37 | 171.18 | — |
| 0.07 | 172.36 | — | — |
| 0.10 | 172.68 | — | — |
| 0.15 | 174.23 | — | — |

I chose 0.03 for both the 5 m and 12 m profiles. At 12 m it gave the lowest mean I measured. At 5 m the lowest mean was at 0.07, just 0.01 nm below the mean at 0.05. Using the common setting cost 103 ± 19 nm² relative to 0.07 in the five paired runs. At 42 m I kept 0.001. Raising it to 0.03 changed total variance by +44 ± 42 nm². One 42 m realization also ran at 0.01 and gave 167.06 nm.

I repeated the 12 m scan with four realizations of 400 settled frames, this time adding 1 electron of read noise. Raising the factor from 0.001 to 0.03 reduced total variance by 348 ± 43 nm² at 1,000 photons per fully illuminated subaperture per frame and by 356 ± 78 nm² at 500 photons. At 500 photons the lowest mean was at 0.02, with 0.03 only 16 ± 51 nm² higher.

## Using the profiles and measurements

Pass version 3 to the profile loader. The three names are `eso_scao_smoke_5m_software`, `eso_scao_medium_12m_derived` and `eso_drm_42m_scao_derived`. The 42 m pupil follows the historical E-ELT design. The profile records give the source of each parameter. [ESO design sources](../src/shwfs_ao/resources/benchmarks/eso_scao_source_ledger.v1.json) · [v3 assumptions](../src/shwfs_ao/resources/benchmarks/eso_drm_42m_scao_derived.assumptions.v3.json)

```python
from shwfs_ao.io.configs import load_system_profile

config = load_system_profile("eso_scao_medium_12m_derived", 3)
print(config.reconstructor.alpha, config.reconstructor.waffle_filter_cutoff)
```

The native CSV has one row per realization and setting. The `aperture` series supplies the filter comparison and the 5 m and 42 m damping scans. The `sensor` series supplies the 12 m variance budget and noiseless damping scan. The `spot_sampling` series gives the 24-sample image and geometric measurements. The `detector_noise` series pairs each noisy 12 m run with its noiseless control. For a paired damping change, subtract the two variances for the same realization, series, sensor and noise setting, then average the differences. Empty cells mark quantities that the run did not measure or settings that were switched off.

These scans applied the specified settings to version 2 of each profile. The configuration hashes identify those runs, including their frame counts. The source SHA-256 identifies the original numerical record for each row. [Native measurements](scao-comparison/layered/native.csv)
