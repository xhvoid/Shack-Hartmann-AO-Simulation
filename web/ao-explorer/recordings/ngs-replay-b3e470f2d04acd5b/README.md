# Synchronized 2.2 m NGS replay

Existing v1/v2 archives only. No AO trajectory is rerun. The same saved input
atmosphere accompanies both pre-update residuals. All 1500 scalar values
remain in data.json; display snapshots use their original frame-start times.
Frame 736 (0.981333333 s) is v1's first rejected reconstruction; it is not a
new estimate of when the optical quality first began to deteriorate.

PSFs are offline Fourier propagation of saved raw residuals at 1.65 um,
verified against all 15 previously archived v1/v2 snapshots and the saved
Strehl values of every displayed frame. The raw wavefront is not altered
before propagation. Only the displayed wavefront maps have piston removed;
tilt stays in all quantities. Common wavefront and PSF scales never rescale
with the frame. PSF crop flux fractions are recorded separately and cropping
never enters Strehl. No image interpolation between times is performed.

The original draft, all assumptions and repair evidence remain in the separate
NGS publication bundle referenced in provenance.json. Full raw wavefront
stacks remain local. Checks establish correspondence to that saved experiment,
not additional physical validation, a new noise realization or long-run stability.
