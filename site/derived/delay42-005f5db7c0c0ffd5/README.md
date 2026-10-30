# 42 m controller-delay comparison, realizations 0-2, 500 frames

Nine saved closed-loop records of the synthetic 42 m SCAO profile
(det_ccd_42m_r3band_derived@1) at 100000 detected electrons per fully
illuminated subaperture per frame, gain 0.3, leak 0, damping 0.001, 500 Hz.
Only the configured controller delay changes: 1, 2 or 3 frames, each in the
same three atmospheric realizations (r0, r1, r2; root seed 1).  The six delay-1
and delay-3 trajectories are new; the three delay-2 records are the reused
photon-budget baselines.  The delay-3/r2 record is the accepted second attempt;
the first attempt was lost to a container restart and has no history.  This
bundle only re-expresses saved values; nothing was simulated to make it.

Timing: an increment reconstructed at frame k is released at frame k+L and
first sensed in the pre-update residual at frame k+L+1.  L is a queue length
in the simulation, not a measured end-to-end instrument latency.

Files: data.json (per-frame pre-update residual RMS in nm and valid fraction
for all nine records, the open-loop RMS of each realization, per-delay
summaries, paired differences against delay 2 with exploratory intervals,
the Strehl asymmetry and the post-hoc r2 description), frames.csv,
psf_panels.png (the accepted analysis figure, copied unchanged),
provenance.json and exporter.py.

Main window [100,500): 400 frames, 0.8 s per record.  Paired intervals are
exploratory 95 % t intervals with df = 2 over three conditional realizations;
the 400 correlated frames are not replicates.  The 3-2 residual interval,
[-4.48, +44.20] nm, includes zero; all three differences are positive and r2
is the largest.  The about 2.3 ratio is the sample-mean peak-Strehl loss from
delay 2 to 3 divided by the gain from 2 to 1, at gain 0.3, in these three
realizations; it is not a general cost multiplier.  The results establish no
stability boundary, optimal gain, hardware requirement or behaviour after
frame 499.

Wording corrections (latency review of 2026-10-29), applied here and on the
page while the frozen study reports and their hashes stay unchanged:
LAT-R01 the r2 excursion is described observationally, without a proven
atmospheric cause; LAT-R02 the similar whole-window mean-image Strehl of r2
does not measure the excursion's effect on the image; LAT-R03 202.761403 nm
is frame 338 (339: 208.842077, 344: 255.093974), frames 446->447 rise from
248.795052 to 273.001961 nm without a simultaneous validity drop (0.993153365
-> 0.993740219), validity recovers only partly (mean 0.991961987 over
[345,500) versus 0.999310446 over [100,300)), 137 window frames are below
0.995; LAT-R04 the ratio is tied to Strehl, the sample and gain 0.3.
