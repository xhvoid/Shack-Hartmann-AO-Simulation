# Numerical checks behind the 2 m interpretation

Summary of existing checks, 30 October 2026. These concern the archived
`det_emccd_2m_synthetic@1` configuration, its 13-actuator Gaussian DM and
associated sensor/calibration. They are not a verification of every current
package profile, the 2.2 m case, or the 42 m model.

## What was compared

| Question | Comparison | Result and scope |
| --- | --- | --- |
| Is the weak tilt correction a sign or unit error? | Signed tilts through the assembled sensor, calibration and Gaussian DM | At 200 nm/m, the command keeps about 0.34 of the input plane coefficient. Representable modes round-trip consistently. This does not establish an ideal sensor response. |
| Is the sensor response exactly linear? | Tilt amplitudes from 25 to 400 nm/m | The one-pass coefficient changes by about 2.1%. The frozen 0.1% linearity bound failed. |
| Does an independent sensor calculation agree? | Independent lenslet propagation and detector-product calculations | It reproduces the discrete sensor chain. Refined optical quadrature gives a tilt coefficient about 0.347 with recalibration, versus 0.341 for the discrete model; weak correction remains. The detector window and products are held fixed. |
| Is the DM basis alone responsible? | WFS least-squares commands versus a pupil-optimal fit using the same basis | A static tilt has residual RMS about 0.681 of input under the WFS objective, versus 0.373 for the pupil-optimal fit. This compares spatial objectives with unconstrained commands; it is not a closed-loop error budget. |
| Is the archived trajectory reproducible? | Actuator-space recurrence with the archived gain, leak, delay, sensor and matched noise streams | The assembled spatial-and-temporal model reproduces the saved baseline. Timing remains part of that model; this comparison does not isolate its contribution. |

The fitted tilt result depends on this low-order basis and measurement
objective. It should not be generalized to Shack–Hartmann sensors as a class.

A DM-layout review also found a boundary-membership defect on some actuator
counts. The 2 m configuration with 13 actuators was unaffected. The ongoing
local correction is separate from this presentation update; no simulation
algorithm or archived recording was changed here.

## What remains open

The checks above do not establish the physical accuracy of PSF, Strehl or EE
outputs, the correctness of every photometric/calibration product, or hardware
performance. Those are separate investigations. Static fitting results omit
stroke constraints, measurement noise and closed-loop temporal effects.

The 42 m case has different evidence. Its earlier command-space solver criteria
failed; later pupil-space checks have narrower conclusions. See the
[42 m qualifications](../index.html#studies42-history) and the gain study's
methods and corrections. A better two-second 2.2 m trajectory or a smaller
42 m excursion is not a general stability claim.

## Saved numerical records

The following files copy the existing numeric records without changing their
values or internal scientific identifiers. `records.json` maps their public
filenames to the source records and SHA-256 values. These are recorded evidence,
not newly executed tests. The full oracle implementations, raw arrays and
execution histories remain in the local research archive.

- [Static tilt and command choice](static-tilt.json)
- [Independent discrete sensor](sensor-checks.json)
- [Optical quadrature refinement](spot-refinement.json)
- [DM fitting](dm-fitting.json)
- [Archived trajectory replay](archive-replay.json)
- [Record identities](records.json)
