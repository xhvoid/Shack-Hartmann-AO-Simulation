# 2.2 m natural-guide-star model: original draft and repair

This bundle publishes existing results. No AO simulation was run to publish it.
The browser displays saved statistics and images, and checks asset hashes.

`results.json` contains the primary [0.2, 1.0) s comparison with the saved
2 m baseline and the separate [0.2, 2.0) s v1/v2 comparison. H-band Strehl is
the instantaneous, flux-normalized peak of each pre-update residual PSF,
relative to its own ideal pupil/grid. SD is population temporal SD, not an
error bar on the mean. Invalid frames are included. The 2 m baseline ends
at one second and is not paired with the different 2.2 m atmosphere.

The original 2.2 m run rejects reconstruction from frame 736 (0.981333 s).
Weak modes of the changing masked inverse amplify command increments;
more spots fail quality gates, and the usable fraction drops below 75%.
After its delayed queue drains, the zero-leak controller holds a saturated
shape. `diagnosis.json` retains the fixed-state and modal checks.

v2 changes the TSVD cutoff from 0.001 to 0.05 and adds rejection decay.
Its atmosphere and calibration arrays match v1 exactly. All 1500 frames
reconstruct, no actuator clips or remains at its boundary, and the recovery
policy never activates. This supports the preventive cutoff repair on this
realization. It is not a proof of long-term stability or measured Robo-AO-2
hardware performance. All other physical values, including stroke, are unchanged.

New clipping means a requested command exceeds the effective limit;
boundary occupancy also includes commands held exactly at that limit.
Fractions in the CSVs are per actuator, not percentages of frames. Summary
tables count frames where any actuator meets the respective criterion.

The four `draft/` files are byte-identical preparation artifacts. They retain
all 131 field annotations and original assumptions. Statements that the
draft was not registered or run refer to that historical checkpoint;
original relative local-file references in the Markdown are also preserved.
Use `baseline-2m-config.json`, `effective-config-v1.json`, and
`effective-config-v2.json` for the executed configurations.
`revision-assumptions.json` explicitly overlays the two local engineering
choices; no published hardware value is claimed for either.

`publication.json` records original source hashes and the distinction between
byte copies and selected scalar exports. Full raw OPD stacks remain local.
The unchanged PNG/PDF are scientific figures generated during the completed
analysis. `validation.json` records prior checks; it is not evidence that
tests or simulations were repeated during publication.
