# Saved NGS control timeline

Only existing v1/v2 telemetry and scalar PSF metrics are read. No atmosphere,
sensor, reconstructor, controller, PSF propagation or AO runtime is executed.
All 1500 samples per trajectory are retained; 0.920–1.040 s is the default
inspection window and 0–2 s remains available. The marker at 0.981333333 s
is the first rejected reconstruction, not an independent lock classifier.

Rows, reconstructed increment and Strehl belong to frame k. The DM shape
held during that exposure comes from the update at k-1. Boundary occupancy
is shifted accordingly; it is distinct from newly clipped requests after
update k, whose unshifted fraction is also provided in the readout/CSV.
Frame 0 starts with a flat DM. Unlike the original comparison table, which
counts post-update applied states, this timeline aligns held states with PSFs.

A rejected reconstruction has no valid increment estimate. Its archived
zero sentinel is exported as null (empty CSV), shown as a gap, never as a
successful zero-error estimate. The increment is an actuator-vector L2 norm,
not a single actuator stroke and not a wavefront RMS. V1's delayed commands
continue through update 737; exposure 738 starts the persistent eight-actuator
boundary state. V2 has neither rejection nor boundary occupancy in this run.

This is descriptive telemetry from one paired realization. The existing
diagnosis provides selected modal checks; the timeline alone does not isolate
a unique initiating noise event or establish robust hardware performance.
The original bundles, draft and all assumptions are retained unchanged.
