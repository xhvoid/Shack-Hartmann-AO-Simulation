# Traced noise-isolation analysis note

Record `/tmp/claude-0/-home-user-Shack-Hartmann-AO-Simulation/f1f3bff0-5382-5b19-9652-6c00a445942e/scratchpad/checks/ni2m_traced/det09_noise_isolation_2m_traced.json` (SHA-256 `0fe189f685237dad…`), 32 analysed runs, 0 refused. NumPy-only analysis `shwfs_ao.noise_isolation_trace_analysis.v1`; no verdict is asserted here.

## Per magnitude (seeds are the units; Student t intervals)

| label | N_e | ΔV mean ± SE (nm²) | t half-width | median | gate-quiet seeds | excursions | E0 ratio equal-weight | E0 ratio weighted | ΔV/propagated | bias 4/SNR_T² |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| m5 | 13001 | 4.27 ± 0.08 | 0.19 | 4.24 | 8/8 | — | 0.994 ± 0.008 | 0.996 ± 0.011 | 0.145 ± 0.004 | 0.0007 |
| m6 | 5176 | 10.40 ± 0.32 | 0.75 | 10.11 | 8/8 | — | 1.005 ± 0.005 | 1.004 ± 0.008 | 0.138 ± 0.005 | 0.0018 |
| m7 | 2061 | 25.81 ± 0.44 | 1.04 | 25.41 | 8/8 | — | 1.008 ± 0.004 | 1.010 ± 0.006 | 0.133 ± 0.003 | 0.0045 |
| m8 | 820 | 200.67 ± 105.01 | 248.32 | 94.17 | 0/8 | [65, 68] | 1.011 ± 0.008 | 1.019 ± 0.009 | 0.916 ± 0.503 | 0.0110 |

## Across magnitudes

### Domain `all`: ['m5', 'm6', 'm7', 'm8']

- Historical weighted fit of seed means, log ΔV vs log N_e: slope -0.9782 ± 0.0136 (unscaled), ± 0.0213 (scaled), χ²/dof 2.458, 1.61 unscaled SE from −1.
- Per-seed paired slopes, log ΔV vs log N_e: mean -1.1956 ± 0.0976 (t half-width 0.2308, n = 8); -2.00 SE from −1.
- Per-seed paired slopes, log ΔV vs log Σ w S² (loop linearity): mean 1.3558 ± 0.1015 (n = 8); 3.50 SE from +1.
- F-06 bootstrap (descriptive): slope -1.3527, SD 0.1628 over 2000 resamples.
- Floor-share fit ΔV·N_e = α + β/N_e: β/α = -93.1 e⁻ (χ²/dof 1.052).
- m5 → m6: paired change of ΔV/Σ w S² -4.22 % ± 3.82 % (n = 8).
- m6 → m7: paired change of ΔV/Σ w S² -3.20 % ± 2.74 % (n = 8).
- m7 → m8: paired change of ΔV/Σ w S² 605.04 % ± 390.40 % (n = 8).

### Domain `gate_quiet_data_driven`: ['m5', 'm6', 'm7']

- Historical weighted fit of seed means, log ΔV vs log N_e: slope -0.9768 ± 0.0136 (unscaled), ± 0.0038 (scaled), χ²/dof 0.077, 1.71 unscaled SE from −1.
- Per-seed paired slopes, log ΔV vs log N_e: mean -0.9768 ± 0.0149 (t half-width 0.0352, n = 8); 1.56 SE from −1.
- Per-seed paired slopes, log ΔV vs log Σ w S² (loop linearity): mean 0.9550 ± 0.0140 (n = 8); -3.21 SE from +1.
- F-06 bootstrap (descriptive): slope -0.9767, SD 0.0139 over 2000 resamples.
- Floor-share fit ΔV·N_e = α + β/N_e: β/α = -95.8 e⁻ (χ²/dof 0.311).
- m5 → m6: paired change of ΔV/Σ w S² -4.22 % ± 3.82 % (n = 8).
- m6 → m7: paired change of ΔV/Σ w S² -3.20 % ± 2.74 % (n = 8).

### Domain `gate_quiet_predeclared`: ['m5', 'm6', 'm7']

- Historical weighted fit of seed means, log ΔV vs log N_e: slope -0.9768 ± 0.0136 (unscaled), ± 0.0038 (scaled), χ²/dof 0.077, 1.71 unscaled SE from −1.
- Per-seed paired slopes, log ΔV vs log N_e: mean -0.9768 ± 0.0149 (t half-width 0.0352, n = 8); 1.56 SE from −1.
- Per-seed paired slopes, log ΔV vs log Σ w S² (loop linearity): mean 0.9550 ± 0.0140 (n = 8); -3.21 SE from +1.
- F-06 bootstrap (descriptive): slope -0.9767, SD 0.0139 over 2000 resamples.
- Floor-share fit ΔV·N_e = α + β/N_e: β/α = -95.8 e⁻ (χ²/dof 0.311).
- m5 → m6: paired change of ΔV/Σ w S² -4.22 % ± 3.82 % (n = 8).
- m6 → m7: paired change of ΔV/Σ w S² -3.20 % ± 2.74 % (n = 8).

## Within-run errors, correlation times and excursions

| run | frames | SE(25) nm² | plateau | τ_int | τ status | excursion | mask disagreement | cross term mean/SE |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| m5/61 | 150 | 0.51 | L=5 SE=0.36 | 6.3 | unreliable: fewer than 50 tau frames | no | 0.00000 | -1.00 |
| m5/62 | 150 | 0.47 | not identified (lower bound 0.47) | 4.0 | unreliable: fewer than 50 tau frames | no | 0.00000 | 0.76 |
| m5/63 | 150 | 0.23 | L=10 SE=0.29 | 2.3 | ok | no | 0.00000 | -0.34 |
| m5/64 | 150 | 0.26 | L=10 SE=0.25 | 2.3 | ok | no | 0.00000 | 0.38 |
| m5/65 | 150 | 0.38 | L=5 SE=0.39 | 5.1 | unreliable: fewer than 50 tau frames | no | 0.00000 | -0.49 |
| m5/66 | 150 | 0.12 | L=5 SE=0.26 | 1.3 | ok | no | 0.00000 | -3.77 |
| m5/67 | 150 | 0.20 | L=5 SE=0.20 | 1.5 | ok | no | 0.00000 | 0.38 |
| m5/68 | 150 | 0.20 | L=5 SE=0.27 | 1.9 | ok | no | 0.00000 | -2.26 |
| m6/61 | 150 | 0.91 | L=5 SE=0.83 | 2.3 | ok | no | 0.00000 | 0.17 |
| m6/62 | 150 | 0.72 | not identified (lower bound 0.72) | 3.6 | unreliable: fewer than 50 tau frames | no | 0.00000 | 0.45 |
| m6/63 | 150 | 0.65 | L=5 SE=0.70 | 2.0 | ok | no | 0.00000 | -1.99 |
| m6/64 | 150 | 1.09 | not identified (lower bound 1.09) | 4.0 | unreliable: fewer than 50 tau frames | no | 0.00000 | 0.01 |
| m6/65 | 150 | 0.64 | L=5 SE=0.62 | 1.8 | ok | no | 0.00000 | 0.36 |
| m6/66 | 150 | 0.33 | L=5 SE=0.66 | 1.8 | ok | no | 0.00000 | -1.23 |
| m6/67 | 150 | 0.74 | L=5 SE=0.59 | 2.6 | ok | no | 0.00000 | -1.57 |
| m6/68 | 150 | 1.58 | not identified (lower bound 1.58) | 4.1 | unreliable: fewer than 50 tau frames | no | 0.00000 | -0.83 |
| m7/61 | 150 | 1.35 | L=10 SE=1.97 | 3.4 | unreliable: fewer than 50 tau frames | no | 0.00000 | 2.06 |
| m7/62 | 150 | 0.95 | L=5 SE=1.61 | 2.1 | ok | no | 0.00000 | -0.35 |
| m7/63 | 150 | 1.99 | L=10 SE=1.95 | 3.8 | unreliable: fewer than 50 tau frames | no | 0.00000 | 0.84 |
| m7/64 | 150 | 1.11 | L=10 SE=2.03 | 1.6 | ok | no | 0.00000 | -0.89 |
| m7/65 | 150 | 2.28 | not identified (lower bound 2.28) | 9.1 | unreliable: fewer than 50 tau frames | no | 0.00000 | 0.06 |
| m7/66 | 150 | 1.60 | L=5 SE=1.86 | 2.3 | ok | no | 0.00000 | -0.55 |
| m7/67 | 150 | 3.36 | not identified (lower bound 3.36) | 3.3 | unreliable: fewer than 50 tau frames | no | 0.00000 | 0.22 |
| m7/68 | 150 | 2.07 | L=5 SE=1.80 | 5.1 | unreliable: fewer than 50 tau frames | no | 0.00000 | 0.66 |
| m8/61 | 150 | 11.13 | L=10 SE=16.36 | 4.3 | unreliable: fewer than 50 tau frames | no | 0.00381 | 1.71 |
| m8/62 | 150 | 7.77 | L=10 SE=10.82 | 2.4 | ok | no | 0.00127 | -0.81 |
| m8/63 | 150 | 9.72 | L=5 SE=6.47 | 5.6 | unreliable: fewer than 50 tau frames | no | 0.00317 | -0.40 |
| m8/64 | 150 | 8.80 | not identified (lower bound 8.80) | 3.3 | unreliable: fewer than 50 tau frames | no | 0.00159 | 1.41 |
| m8/65 | 150 | 52.45 | L=5 SE=38.09 | 6.6 | unreliable: fewer than 50 tau frames | yes [5] | 0.00349 | 1.78 |
| m8/66 | 150 | 22.68 | L=5 SE=17.21 | 5.0 | unreliable: fewer than 50 tau frames | no | 0.00381 | -2.12 |
| m8/67 | 150 | 4.40 | L=5 SE=4.25 | 2.4 | ok | no | 0.00159 | 0.66 |
| m8/68 | 150 | 807.20 | not identified (lower bound 807.20) | 4.8 | unreliable: fewer than 50 tau frames | yes [4] | 0.01270 | -1.02 |

## Replay comparison: traced versus historical record

Other record `docs/refactor/detector_level_evidence/det09_noise_isolation_2m.json` (SHA-256 `655528b64e087b3f…`): 0 of 32 compared runs bit-identical in the seven recorded quantities.
- m5/61: first differing quantity `noise_variance_m2` (4.165567128001401e-18 vs 4.165567126994347e-18, relative 0.000000).
- m5/62: first differing quantity `noise_variance_m2` (4.41100973607037e-18 vs 4.411009736266952e-18, relative -0.000000).
- m5/63: first differing quantity `noise_variance_m2` (4.125326672740725e-18 vs 4.125326672653721e-18, relative 0.000000).
- m5/64: first differing quantity `noise_variance_m2` (3.955015042784026e-18 vs 3.955015042463618e-18, relative 0.000000).
- m5/65: first differing quantity `noise_variance_m2` (4.6260147338859714e-18 vs 4.626014733635329e-18, relative 0.000000).
- m5/66: first differing quantity `noise_variance_m2` (4.467318164388953e-18 vs 4.467318165167275e-18, relative -0.000000).
- m5/67: first differing quantity `noise_variance_m2` (4.3052459445608284e-18 vs 4.30524594431163e-18, relative 0.000000).
- m5/68: first differing quantity `noise_variance_m2` (4.104733956327183e-18 vs 4.10473395632752e-18, relative -0.000000).
- m6/61: first differing quantity `noise_variance_m2` (9.820321924078011e-18 vs 9.820321925187714e-18, relative -0.000000).
- m6/62: first differing quantity `noise_variance_m2` (1.0396420129503273e-17 vs 1.0396420128989977e-17, relative 0.000000).
- m6/63: first differing quantity `noise_variance_m2` (9.486263306337156e-18 vs 9.4862633063397e-18, relative -0.000000).
- m6/64: first differing quantity `noise_variance_m2` (1.1457500498524933e-17 vs 1.1457500498528657e-17, relative -0.000000).
- m6/65: first differing quantity `noise_variance_m2` (1.1557398632923284e-17 vs 1.1557398633051755e-17, relative -0.000000).
- m6/66: first differing quantity `noise_variance_m2` (9.79614766245263e-18 vs 9.796147663294259e-18, relative -0.000000).
- m6/67: first differing quantity `noise_variance_m2` (9.453751546247089e-18 vs 9.453751545019156e-18, relative 0.000000).
- m6/68: first differing quantity `noise_variance_m2` (1.1248893817634022e-17 vs 1.1248893817909267e-17, relative -0.000000).
- m7/61: first differing quantity `noise_variance_m2` (2.4671833298988097e-17 vs 2.467183329918503e-17, relative -0.000000).
- m7/62: first differing quantity `noise_variance_m2` (2.511997465181283e-17 vs 2.5119974651638806e-17, relative 0.000000).
- m7/63: first differing quantity `noise_variance_m2` (2.5209925637874526e-17 vs 2.5209925637486887e-17, relative 0.000000).
- m7/64: first differing quantity `noise_variance_m2` (2.803490363948417e-17 vs 2.803490363897124e-17, relative 0.000000).
- m7/65: first differing quantity `noise_variance_m2` (2.6956440988900434e-17 vs 2.6956440988878577e-17, relative 0.000000).
- m7/66: first differing quantity `noise_variance_m2` (2.4421758172545018e-17 vs 2.442175817220137e-17, relative 0.000000).
- m7/67: first differing quantity `noise_variance_m2` (2.6433988206826454e-17 vs 2.643398820547067e-17, relative 0.000000).
- m7/68: first differing quantity `noise_variance_m2` (2.5617850440187198e-17 vs 2.5617850439564392e-17, relative 0.000000).
- m8/61: first differing quantity `noise_variance_m2` (9.321021843801228e-17 vs 9.321021844022373e-17, relative -0.000000).
- m8/62: first differing quantity `noise_variance_m2` (9.513838495493405e-17 vs 9.513838495514177e-17, relative -0.000000).
- m8/63: first differing quantity `noise_variance_m2` (7.873770894990578e-17 vs 7.873770894925852e-17, relative 0.000000).
- m8/64: first differing quantity `noise_variance_m2` (7.168528202924042e-17 vs 7.168528202932482e-17, relative -0.000000).
- m8/65: first differing quantity `noise_variance_m2` (1.4804470837574735e-16 vs 1.4804470837698816e-16, relative -0.000000).
- m8/66: first differing quantity `noise_variance_m2` (1.1980704803748994e-16 vs 1.198070480410619e-16, relative -0.000000).
- m8/67: first differing quantity `noise_variance_m2` (6.601792707153513e-17 vs 6.601792706489811e-17, relative 0.000000).
- m8/68: first differing quantity `noise_variance_m2` (9.327491024254974e-16 vs 9.327491024279433e-16, relative -0.000000).

## Limitations stated by this analysis

- Block standard errors from fewer than about ten blocks carry a relative uncertainty of 1/sqrt(2(k-1)) or more; plateau identification at 150 analysed frames is indicative, not a guarantee of a 5 % error.
- The integrated autocorrelation time is reported as unreliable whenever the series is shorter than 50 tau or the automatic window does not close; such runs give lower bounds only.
- E0 uses the expected-frame centroid as the first-order mean of the noisy centroid; the reported second moment and centred variance differ by the squared mean residual, and the model's first-order bias (about 4/SNR_T^2) is reported, not corrected.
- The propagation weights are the fixed reconstructor's pupil response per row (linear, every row valid); they are one justified weighting, reported beside equal weights, not the only one.
- Bootstrap resamples are descriptive; seeds remain the only independent units.
- Nothing here closes AR-006 or LIM-18, retunes the noise model or treats the proposed first-order bias band as an established acceptance criterion.
- No blocking plateau identified for 8 of 32 runs (m5/62, m6/62, m6/64, m6/68, m7/65, m7/67, m8/64, m8/68): their within-run errors are lower bounds.
