# C1 static noise assessment: public summary

`summary.json` holds selected scalars of the completed C1 assessment (stage N15 of the S6 investigation into the
42 m profile's regularization). C1 is a static calculation, separate from the 42 m replay: it predicts the
stationary detector-noise component of the reconstructed pupil wavefront at the production photon budget
(10^5 detected electrons per fully illuminated subaperture per frame) for the production damping (alpha 0.001) and
one selected comparator (alpha 0.0025). It generated no images, PSFs or closed-loop frames.

Result: `QUALIFIED_BELOW_C1_TRIGGER`. Under the frozen static covariance and stationary linear-loop model at that
budget, the selected admissible comparator does not meet the C1 material-benefit trigger (at least 1.0 nm and at
least 10 % variance reduction). The predicted component is 1.1113 nm RMS at alpha 0.001 and 1.1071 nm at alpha
0.0025. The 0.0042 nm difference of these two component predictions is not a change in total closed-loop residual,
not the RMS of a paired difference and not an estimate of what a closed-loop comparison would measure. No
closed-loop damping experiment was triggered; the production damping stays 0.001. Total closed-loop response and
other operating conditions remain unmeasured.

The recorded 2.0e-13 is an empirical numerical consistency indicator, not a certified error bound and not a
statistical interval. Model conditions: the detector covariance at a flat wavefront with fixed camera maps,
inter-lenslet independence, persistent calibration bias excluded; a stationary linear loop (gain 0.3, latency 2,
leak 0) with temporally white modal noise; one configuration, seed 1, realization 0. This is an exploratory
simulation result, not a hardware measurement.

`summary.json` names the source records by SHA-256; they stay in the project's private evidence archive.
