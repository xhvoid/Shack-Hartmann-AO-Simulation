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

## Choosing the 12 m filter cutoff

The v3 profiles took the cutoff of 0.35 from the 42 m detector-level profile. I scanned it at 5 m and 12 m with the Tikhonov factor at 0.03, on five noiseless atmospheres per aperture. The table gives the number of mirror patterns the filter removes and the square root of the mean total residual variance, in nm.

| Filter cutoff | 5 m, patterns removed | 5 m RMS | 12 m, patterns removed | 12 m RMS |
| ---: | ---: | ---: | ---: | ---: |
| off | 0 | 186.37 | 0 | 179.38 |
| 0.1 | 1 | 172.68 | 1 | 173.85 |
| 0.2 | — | — | 5 | 171.46 |
| 0.3 | — | — | 8 | 170.95 |
| 0.35 | 3 | 172.66 | 11 | 170.82 |
| 0.45 | — | — | 16 | 169.99 |
| 0.5 | 5 | 173.31 | 18 | 169.79 |
| 0.6 | — | — | 20 | 169.59 |
| 0.7 | 5 | 173.88 | 32 | 169.69 |
| 0.8 | — | — | 45 | 170.11 |
| 0.9 | 10 | 175.53 | 64 | 171.32 |
| 1.0 | 12 | 176.06 | 80 | 172.63 |

The 5 m runs keep 1,800 settled frames and the 12 m runs 900. The 12 m entry at 0.35 comes from these five runs, so it differs from the twelve-realization value in the damping table. For the pattern counts I built each system once, at a cutoff of 0.35, and applied a dense form of the filter's selection rule to that calibrated response at every cutoff in the table. Its count matched the reconstructor's own at 0.35 for both apertures. Building version 4 of the 12 m profile gives 20 at 0.6.

Raising the damping did not replace the filter. With the filter off, total variance was 4,924 ± 346 nm² higher at 5 m and 2,998 ± 212 nm² higher at 12 m than at 0.35. At 5 m, 0.35 gave the lowest mean. A cutoff of 0.1 came out 9 ± 31 nm² higher, and 0.5 came out 226 ± 45 nm² higher. At 12 m the lowest mean was at 0.6, 419 ± 42 nm² below 0.35. On the same five atmospheres, 0.5 was 68 ± 10 nm² above 0.6 and 0.7 was 36 ± 9 nm² above it.

I ran two checks at 12 m before changing the profile. With the cutoff at 0.5 and again at 0.7, I repeated the runs at Tikhonov factors of 0.001, 0.01, 0.05 and 0.1. In both cases 0.03 kept the lowest mean of the five factors. Then I added 1 electron of read noise on four atmospheres of 400 settled frames. Relative to 0.35, a cutoff of 0.6 reduced total variance by 406 ± 79 nm² at 1,000 photons per fully illuminated subaperture per frame and by 355 ± 60 nm² at 500 photons. With noise I could not separate 0.6 from 0.7. The paired difference, 0.6 minus 0.7, was −23 ± 40 nm² at 1,000 photons and +74 ± 55 nm² at 500.

After preparing version 4, I scanned the damping at its own cutoff of 0.6 on the same five noiseless atmospheres.

| Tikhonov factor | 12 m RMS at cutoff 0.6 (nm) | Total variance minus its value at 0.03 (nm²) |
| ---: | ---: | ---: |
| 0.001 | 170.36 | +263 ± 13 |
| 0.01 | 170.13 | +184 ± 8 |
| 0.02 | 169.76 | +58 ± 3 |
| 0.03 | 169.59 | — |
| 0.05 | 169.85 | +90 ± 20 |
| 0.10 | 173.50 | +1,343 ± 183 |

A factor of 0.03 gave the lowest mean of the six. Each of the other five came out higher on every atmosphere.

Version 4 of the 12 m profile uses a cutoff of 0.6 and keeps the damping at 0.03. The 5 m and 42 m profiles stay at version 3. I did not scan the damping at 0.6 with read noise, and I did not scan the cutoff at 42 m.

## The weak-turbulence 12 m profile

`eso_scao_medium_12m_weak_gate` is the same 12 m system under a Fried length of 0.40 m. I ran its version 2 with the filter off, at 0.35 and at 0.6, each at a Tikhonov factor of 0.001 and 0.03, on five noiseless atmospheres of 900 settled frames.

| Filter cutoff | Tikhonov factor | RMS (nm) | Total variance minus version 2 (nm²) |
| ---: | ---: | ---: | ---: |
| off | 0.001 | 71.21 | — |
| off | 0.03 | 69.81 | −198 ± 9 |
| 0.35 | 0.001 | 67.02 | −580 ± 34 |
| 0.35 | 0.03 | 66.53 | −645 ± 37 |
| 0.6 | 0.001 | 66.34 | −670 ± 42 |
| 0.6 | 0.03 | 66.05 | −709 ± 44 |

The order matched the nominal profile, with the lowest mean at 0.6 and 0.03. I do not count this as independent evidence. These atmospheres are the nominal screens scaled to the larger Fried length, and each total variance came out as the nominal one divided by 6.59 to 6.62. The two Fried lengths alone give 6.51. A noiseless scan repeats the nominal one at a smaller amplitude.

Detector noise does not shrink with the turbulence. Finding out whether this profile needs its own settings takes a scan with noise, which I have not run. The profile stays at version 2.

## Using the profiles and measurements

Pass version 4 to the profile loader for the 12 m profile and version 3 for the other two. The three names are `eso_scao_smoke_5m_software`, `eso_scao_medium_12m_derived` and `eso_drm_42m_scao_derived`. Version 3 of the 12 m profile still loads with its cutoff of 0.35. The 42 m pupil follows the historical E-ELT design. The profile records give the source of each parameter. [ESO design sources](../src/shwfs_ao/resources/benchmarks/eso_scao_source_ledger.v1.json) · [v3 assumptions](../src/shwfs_ao/resources/benchmarks/eso_drm_42m_scao_derived.assumptions.v3.json) · [v4 assumptions](../src/shwfs_ao/resources/benchmarks/eso_drm_42m_scao_derived.assumptions.v4.json)

```python
from shwfs_ao.io.configs import load_system_profile

config = load_system_profile("eso_scao_medium_12m_derived", 4)
print(config.reconstructor.alpha, config.reconstructor.waffle_filter_cutoff)
```

The native CSV has one row per realization and setting. The `aperture` series supplies the filter comparison, the 5 m and 42 m damping scans, and the noiseless cutoff scans with their 12 m damping checks. The `sensor` series supplies the 12 m variance budget and noiseless damping scan. The `spot_sampling` series gives the 24-sample image and geometric measurements. The `detector_noise` series pairs each noisy 12 m run with its noiseless control. The `weak_turbulence` series holds the runs of the weak-turbulence 12 m profile. For a paired damping or cutoff change, subtract the two variances for the same realization, series, sensor and noise setting, then average the differences. Empty cells mark quantities that the run did not measure or settings that were switched off.

These scans applied the specified settings to version 2 of each profile. The configuration hashes identify those runs, including their frame counts. The source SHA-256 identifies the original numerical record for each row. [Native measurements](scao-comparison/layered/native.csv)
