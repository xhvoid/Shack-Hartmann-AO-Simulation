# Comparing the 2 m Shack–Hartmann loop with TIPTOP

I ran the same on-axis 2 m telescope geometry in the time-domain model and in TIPTOP. Both used a single atmospheric layer moving at 10 m/s, a 5 × 5 lenslet grid, a 0.5 m actuator pitch and a 1 kHz loop. I turned off detector noise and removed the stroke constraint in the time-domain model so that neither would set the result.

![Residual wavefront RMS and long-exposure H-band peak Strehl in three time-domain exposures and the TIPTOP estimate](comparison.png)

| At 1.65 µm | Time domain, three atmospheres | TIPTOP |
|---|---:|---:|
| Residual RMS over the pupil | 257–391 nm | 154 nm |
| Peak Strehl of the mean image | 0.257–0.419 | 0.710 |

For each time-domain run I averaged 800 point-source images over 0.8 s, keeping their positions fixed. TIPTOP calculates the long-exposure image from the residual power spectrum instead. The time-domain loop came out with a larger residual and a lower image peak in all three exposures, by a factor of about two in RMS.

To see where the difference sits, I fitted a plane to the residual wavefront of the first exposure. Tilt alone accounted for 69% of its variance (325 nm out of 391 nm total RMS). That makes sense for how this loop works: the detector measures spot positions, the calibrated mirror fits those measurements, and whatever tilt that fit leaves behind goes straight into the stellar image. TIPTOP applies a spatial-frequency correction filter and averages over atmospheric statistics; it never sees this loop's actual mirror fit. The [model notes](../methods.md#reading-the-selected-cases) record the same weak tilt correction from this sensor, reconstructor and DM combination, so I read most of the gap as a property of this small loop rather than of the atmosphere. Field sampling is not the cause either: doubling the TIPTOP image field changed its residual by 0.4 nm and its Strehl by 0.005.

## Experiment settings

The pupil was circular and unobstructed. I used a Fried length of 0.12634 m at 500 nm, an outer scale of 25 m, a 700 nm sensing wavelength and a loop gain of 0.2. The science grid sampled λ/D with three pixels. In the time-domain code a command calculated at frame *k* first enters the measured wavefront at *k* + 3, and the TIPTOP transfer function uses the matching delay of three frame periods. The time-domain reconstructor uses the calibrated actuator responses, whereas TIPTOP represents the DM correction band analytically.

The first 0.2 s of each one-second time series was excluded. The RMS is the square root of the mean piston-removed pupil variance, and Strehl is the peak of the accumulated image relative to the ideal pupil. The table gives the range across the three exposures and the 384-pixel TIPTOP result.

[Inputs](matched.ini) · [Numerical results](results.json) · [Comparison script](compare.py) · [TIPTOP documentation](https://tiptop.readthedocs.io/)

To rerun it, install the package and the three versions listed in the results file, then from the repository root:

```sh
PYTHONPATH=src python docs/scao-comparison/compare.py
```

The script writes the table data and the figure next to the input file.
