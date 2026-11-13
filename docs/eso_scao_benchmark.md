# Comparing the 5 m, 12 m and 42 m loops with TIPTOP/P3

I used the same ten-layer atmospheric profile in the native Shack–Hartmann loop and the Fourier model in TIPTOP 1.5.1 / P3 1.6.2. The three systems use 0.5 m subapertures, a Fried length of 0.13 m at 500 nm, and an on-axis guide star at zenith. Each loop runs at 500 Hz with gain 0.4. A native two-frame latency corresponds to three delay steps in P3.

## What the filter changes

The alternating pattern of neighbouring mirror actuators is called *waffle*. Several patterns close to it produce very little spot motion. The filter removes those patterns from each command increment. I switched it on and off at a fixed Tikhonov factor of 0.001, with detector noise off.

| Aperture | Native RMS, filter off (nm) | Native RMS, cutoff 0.35 (nm) | P3 RMS (nm) | Filtered native / P3 Strehl at 2.2 µm |
| --- | ---: | ---: | ---: | ---: |
| 5 m | 192.0 ± 1.4 | 173.5 ± 0.9 | 154.1 | 0.784 / 0.813 |
| 12 m | 183.2 ± 2.0 | 172.1 ± 1.5 | 155.9 | 0.787 / 0.816 |
| 42 m | 174.18 ± 0.66 | 168.06 ± 0.65 | 156.45 | 0.795 / 0.818 |

The 5 m and 12 m means each cover five realizations and the 42 m means three. At 42 m the filter lowered total variance by 2,092 ± 78 nm², and by at least 1,943 nm² on each atmosphere. The 5 m averages use 1,800 settled frames per realization, the others 900. RMS is the square root of the mean piston-removed pupil variance. The ± values are standard errors across realizations.

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

I then repeated that scan with 1 electron of read noise, on four atmospheres of 400 settled frames. The entries are the total variance minus its value at 0.03, in nm².

| Tikhonov factor | Noise off | 1,000 photons | 500 photons |
| ---: | ---: | ---: | ---: |
| 0.001 | +234 ± 20 | +252 ± 18 | +131 ± 56 |
| 0.01 | +166 ± 15 | +172 ± 16 | +91 ± 56 |
| 0.02 | +57 ± 6 | +96 ± 22 | +21 ± 70 |
| 0.05 | +47 ± 12 | +66 ± 42 | +52 ± 42 |

A factor of 0.03 kept the lowest mean in all three columns. At 500 photons I could not separate it from 0.02 or 0.05.

Version 4 of the 12 m profile uses a cutoff of 0.6 and keeps the damping at 0.03. The 5 m and 42 m profiles stay at version 3.

## The filter cutoff at 42 m

The 42 m reconstructor could not build a cutoff of 0.6. The filter first collects every mirror pattern whose response is below 1.5 times the cutoff. The sparse solver handles at most a quarter of the 5,328 commanded actuators in that set, and the dense fallback would need more memory than the code allows. The largest cutoff that passes is 0.513.

I ran 0.4, 0.45 and 0.5 on the three atmospheres already used at 0.35, and ran the same three with the filter off. The Tikhonov factor was 0.001 and detector noise was off.

| Filter cutoff | Patterns removed | RMS (nm) | Total variance minus its value at 0.35 (nm²) |
| ---: | ---: | ---: | ---: |
| off | 0 | 174.18 ± 0.66 | +2,092 ± 78 |
| 0.35 | 96 | 168.06 ± 0.65 | — |
| 0.4 | 130 | 167.78 ± 0.64 | −96 ± 7 |
| 0.45 | 165 | 167.54 ± 0.64 | −177 ± 6 |
| 0.5 | 206 | 167.40 ± 0.65 | −223 ± 6 |

Each step up in cutoff lowered the residual on each of the three atmospheres. The steps shrank, from 96 nm² between 0.35 and 0.4 to 81 nm² and then 46 nm². The residual was still falling at the largest cutoff I could build. Against P3 at 156.45 nm, the native residual went from 7.4% above it at 0.35 to 7.0% at 0.5.

I also tried a Tikhonov factor of 0.03 at 0.45 and at 0.5. Relative to 0.001 it changed total variance by +48 ± 42 nm² and +49 ± 42 nm². At 0.35 the same change was +44 ± 42 nm², so the damping is unresolved at all three cutoffs.

I have not changed the 42 m profile. Three atmospheres is a small sample, and I have not added detector noise. A cutoff of 0.5 also sits 2.6% below the build limit, which leaves little margin if the calibrated response changes.

Part of this section ran on a Linux machine: the cutoff of 0.4, two of the three unfiltered atmospheres, and the 0.03 runs at 0.45. I repeated ten of the macOS runs there, and the total variances agreed to within 2 parts in 10¹⁴.

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

Detector noise does not shrink in step with the turbulence, so I repeated the six settings with 1 electron of read noise, on four atmospheres of 400 settled frames. Each entry gives the RMS in nm and the total variance minus version 2 in nm².

| Filter cutoff | Tikhonov factor | Noise off | 1,000 photons | 500 photons |
| ---: | ---: | --- | --- | --- |
| off | 0.001 | 70.11 | 76.89 | 85.57 |
| off | 0.03 | 68.76, −187 ± 18 | 74.86, −308 ± 20 | 82.88, −454 ± 44 |
| 0.35 | 0.001 | 66.50, −492 ± 33 | 72.94, −592 ± 50 | 81.08, −748 ± 68 |
| 0.35 | 0.03 | 66.06, −551 ± 36 | 72.13, −709 ± 47 | 80.00, −922 ± 71 |
| 0.6 | 0.001 | 65.87, −576 ± 39 | 72.20, −699 ± 51 | 80.34, −869 ± 75 |
| 0.6 | 0.03 | 65.60, −611 ± 41 | 71.67, −775 ± 53 | 79.39, −1,019 ± 67 |

The lowest mean stayed at 0.6 and 0.03 with noise, and every setting beat version 2 on every atmosphere. At a factor of 0.03, a cutoff of 0.6 came out below 0.35 by 61 ± 5 nm² without noise, 66 ± 12 nm² at 1,000 photons and 97 ± 5 nm² at 500. The same difference for the nominal profile, divided by 6.51, gives 61, 62 and 54 nm². At 500 photons the weak-turbulence run is no longer a scaled copy of the nominal one. At those settings and 500 photons, the noise added 1,999 nm² to this profile and 6,360 nm² to the nominal one, a ratio of 3.2.

The profile stays at version 2. These are four short runs at the two photon levels I chose for the nominal profile, and the atmospheres are still the nominal screens scaled to the larger Fried length. The runs with noise were made on Linux.

## Using the profiles and measurements

Pass version 4 to the profile loader for the 12 m profile and version 3 for the other two. The three names are `eso_scao_smoke_5m_software`, `eso_scao_medium_12m_derived` and `eso_drm_42m_scao_derived`. Version 3 of the 12 m profile still loads with its cutoff of 0.35. The 42 m pupil follows the historical E-ELT design. The profile records give the source of each parameter. [ESO design sources](../src/shwfs_ao/resources/benchmarks/eso_scao_source_ledger.v1.json) · [v3 assumptions](../src/shwfs_ao/resources/benchmarks/eso_drm_42m_scao_derived.assumptions.v3.json) · [v4 assumptions](../src/shwfs_ao/resources/benchmarks/eso_drm_42m_scao_derived.assumptions.v4.json)

```python
from shwfs_ao.io.configs import load_system_profile

config = load_system_profile("eso_scao_medium_12m_derived", 4)
print(config.reconstructor.alpha, config.reconstructor.waffle_filter_cutoff)
```

The native CSV has one row per realization and setting. The `aperture` series supplies the filter comparison, the 5 m and 42 m damping scans, and the noiseless cutoff scans at 5 m, 12 m and 42 m with the 12 m damping checks. The `sensor` series supplies the 12 m variance budget and noiseless damping scan. The `spot_sampling` series gives the 24-sample image and geometric measurements. The `detector_noise` series pairs each noisy 12 m run with its noiseless control. The `weak_turbulence` series holds the runs of the weak-turbulence 12 m profile, with and without noise. For a paired damping or cutoff change, subtract the two variances for the same realization, series, sensor, noise setting and frame count, then average the differences. Some rows come from a Linux machine and the rest from macOS. The runs made on both agreed to within 2 parts in 10¹³ in total variance, so the rows can be paired across the two. Empty cells mark quantities that the run did not measure or settings that were switched off.

These scans applied the specified settings to version 2 of each profile. The configuration hashes identify those runs, including their frame counts. The source SHA-256 identifies the original numerical record for each row. [Native measurements](scao-comparison/layered/native.csv)
