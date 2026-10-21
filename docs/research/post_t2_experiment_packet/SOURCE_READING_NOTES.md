# Source-reading notes

Everything below was read in this session on the exact tree `5514285`
(`INSPECTED_CURRENT` unless marked otherwise). Line numbers are those of the
tree; "status record" means `docs/refactor/DETECTOR_LEVEL_DEVELOPMENT_STATUS.md`,
"cleanup record" means `docs/refactor/CLEANUP_REFACTOR_STATUS.md`.

## 1. Documents

| Source | What was taken from it |
| --- | --- |
| `docs/technical_reference.md` 5.1 (atmosphere, pairing paragraph), 5.4 (sampling and exposure rules), 5.10 (science metrics, Fourier EE reference), 5.11 (experiment approaches), 6.2-6.3 (representative runs, identity versus execution options), 7.5 (recorded negative results), 9.2-9.7 (measured costs, memory inventory, scenarios, guidance) | the identity rules of the pairing options, the midpoint scheme and its metadata, the EE reference's error budgets, the labels of every cost figure, the 42 m memory inventory, the two-thread serial policy |
| `docs/roadmap.md` (cost categories, S3, S4, G2, G4, G6) | the governed-run categories; the T1 and T2 status lines; G4 (process-lifetime peak), G6 (desktop environment is not the lock) |
| `docs/current_limitations.md` LIM-05, LIM-07, LIM-08, LIM-11, LIM-17, LIM-18 | the standing boundaries the protocols must preserve; the exact recorded 12 m and 2 m slopes and their qualifications |
| `docs/validation.md`, `docs/provenance.md`, `docs/reproducibility.md` | the validation ladder; the named random domains and the host-independent noise-stream identity (roundoff, not bitwise, agreement across hosts); the replay checklist |
| `docs/eso_scao_benchmark.md` (resource policy section, via the technical reference and the runner) | the authorized-budget semantics |
| status record 85-104 (policy in force), 907-928 (gated-run estimates), 2279-2348 (isolated-noise protocol and amendments), 2406-2442 (2 m results), 2510-2560 (12 m results, the 1.11 GiB peak) | the predeclared noise protocol, the per-magnitude `DeltaV` and model columns, the recorded outlier at m11 seed 72 |
| cleanup record 94-111 (execution policy), 847-884 (S1-S3 runs), 1018-1070 (T1 and T2 sections) | the T1 C0 replay facts, the T2 self-check facts, the guard refusals on pressure and the user's instruction that is not inherited |
| `constraints/README.md`, the four lock files, `.github/workflows/{ci,scheduled,relock}.yml` | which lanes run which lock; the verification step in every lane |
| `scripts/README.md`, `tests/conftest.py` | the `elt_scale` authorization option; markers |

## 2. Code

| File and lines | Established |
| --- | --- |
| `scripts/detector_level_convergence_study.py` 1-67 (docstring), 91-137 (constants, `SCALES`, `REFINEMENT`), 210-286 (`plan`), 288-320 (`planned_protocol`), 321-400 (producer identity), 414-660 (`check_run`), 663-700 (`_publish`, atomic), 746-955 (`analyze`), 955-980 (`cost_estimate`), 984-1047 (child launch and child work), 1074-1083 (unplanned files), 1086-1196 (`main`) | plan sizes (ci 11, medium 54, full 5), axes and readings, the baseline's exclusion from the pupil family, the once-written summary, the governed refusals, the child environment (two threads, no bytecode), the per-child `ru_maxrss` semantics, the cost model and its anchor |
| `src/shwfs_ao/experiments/convergence_study.py` 1-40 (docstring), 85-150 (`scan_configuration`), 155-240 (disk recorder and streaming `DeltaV`), 243-260 (block mean and error), 254-325 (geometry and budget records), 328-395 (`planned_physics_record`), 412-445 (science record with Fourier reference), 456-640 (`fixed_physics_paired_run`, `block_frames=10`) | what each run records; the twin-first order; the disk-backed twin record; the `metric_time_convention` field; the refusals that become rows |
| `scripts/run_detector_level_evidence.py` 1-100 (docstring), 130-200 (header, record path, write), 240-316 (code identity and environment), 320-470 (series protocol 4, self-consistency), 650-890 (`_gated_series`), 897-900 (summary execution), 1095-1160 (`NOISE_ISOLATION_*`, `e5`), 1180-1420 (traced family: settings, diagnostic protocol, sidecar arrays, atomic publication), 1640-1740 (`traced_run_factory`), 1877-1947 (`main`) | the A1 command and its constants; the arm order; map-retention seeds; the sidecar schema; the resume and refusal rules; that one process runs the series; that per-run peaks are not recorded by the paired core |
| `src/shwfs_ao/experiments/detector_level.py` 420-435 (`with_magnitude`), 476-561 (`science_run`, lifetime peak), 601-607 (arm orders and schemas), 649-732 (recorders), 1021-1055 (`_run_paired_arm`), 1057-1133 (`_trace_payload`), 1273-1355 (`_paired_noise_core`), 1358-1443 (`paired_noise_run`, `_traced`), 1446-1480 (`_mask_locked` docstring) | the memory model of a paired run (float32 samples for every analysed frame, telemetry arrays, payload copies), realization index 0 under each root seed, the E0 summary |
| `scripts/analyze_noise_isolation_traces.py` 1-50 (rules), 1074-1084 (CLI) | the predeclared statistics (blocking plateau, Sokal window, gate-quiet domain, excursions, E0, Student t, descriptive bootstrap) and the `--historical` comparison |
| `scripts/noise_isolation_offline_bounds.py` 1-60 | the propagated-variance definition `V(R) = sum_r sigma_r^2 w_r` and its independence assumption |
| `src/shwfs_ao/validation/richardson.py` (whole) | the model, the admissibility rules, the `NOT_ESTIMATED` reasons, the assumed-order labelling, the Celik et al. 2008 attribution, the minimum log refinement ratio |
| `src/shwfs_ao/validation/atmosphere_pairing.py` 91-118, 121-160 | the dilation report, the exact-pairing flag, band-power fractions |
| `src/shwfs_ao/validation/encircled_energy.py` 1-75 (docstring) | pad independence of the interpolant for pad >= 2; whole-field flux denominator; what the reference does not remove |
| `src/shwfs_ao/runtime/resource_guard.py` 1-30, 79-100 (defaults), 363-401 (snapshot and budget), 404-437 (thread environment), 523-592 (preflight), 763-800 (`run_supervised` signature), 914-970 (CLI) | the budget formula, the 2x margin, the pressure stop, the CLI's inability to raise the budget, the aggregate-RSS supervision |
| `src/shwfs_ao/experiments/eso_scao_benchmark.py` 220-270 (dry run), 760-800 (`_authorized_decision`), 826-900 (budget and launch) | the authorized-budget semantics mirrored by `tools/authorized_supervise.py` |
| `scripts/verify_environment_lock.py` | installed is a subset of pinned at exact versions; `pip` and the project ignored |
| `tests/experiments/test_detector_level_convergence.py` (names and markers) | the real self-check is `slow`; `--plan` is tested for governed scales without enablement |
| profiles `det_emccd_12m_medium_derived.v3.json`, `det_ccd_42m_r3band_derived.v1.json`, `det_emccd_2m_synthetic.v1.json` | the fixed quantities of PROTOCOL.md 1.3 and 3.1; the 2 m controller (gain 0.2, leak 0.02, latency 2) for the `kappa` check |
| records `det09_noise_isolation_12m_v3.json`, `det09_noise_isolation_2m.json`, `paired_convergence_medium.json`, `paired_convergence_full.json` (headers) | producers of the historical records (series protocol 2, dirty `663df16`; S3 at `2312502` clean), run counts, wall times |

## 3. Derivation used by the alternative closure model (repository-style derivation, checked numerically)

Loop of technical reference 4.2 with gain `g`, leak `l`, queue latency `d`
and measurement noise `n_k` on the reconstructed increment: the command
difference between the noisy and the twin arm obeys
`dc_k = (1-l) dc_{k-1} + g (dr_{k-d} + n_{k-d})` with `dr_k = -dc_{k-1}`, so
`dC(z) (1 - (1-l) z^{-1} + g z^{-(d+1)}) = g z^{-d} N(z)`, i.e.
`H(z) = g z / (z^{d+1} - (1-l) z^d + g)`; the residual transfer `-g / (...)` has
the same modulus on the unit circle. For white noise the mean-square gain is
`kappa = (1/2 pi) integral_0^{2 pi} |H(e^{i w})|^2 dw`. Checks: at `d = 0`,
`l = 0` the closed form `g/(2-g)` is reproduced to five digits (0.17647 for
g = 0.3); the denominator is the stability polynomial `z^{d+1} - z^d + g`
of the reference (largest pole modulus 0.813 at g = 0.3, d = 2, stable).
Values on a 2^16-point grid: g = 0.3, l = 0, d = 2: **0.35005**; g = 0.2,
l = 0.02, d = 2 (the 2 m profile): **0.15455** (0.16959 without the leak).
This is a derivation of this packet, not a literature result; the
literature status of the method is in section 4.

## 4. Literature and official documentation

The environment's network policy denied every primary host (HTTP 403 from
the proxy for `asme.org`, `ntrs.nasa.gov`, `arxiv.org`, `doi.org`,
`adsabs.harvard.edu`, `sto.nato.int`, `ox.ac.uk`). The user then supplied
copies of four papers (Celik et al. 2008, Gendron and Léna 1994, Agapito et
al. 2019, Trefethen 2008), which were read in this session; the two paywalled
papers (Flyvbjerg and Petersen; Madras and Sokal) stay at listing status.
The supplied copies are not part of the repository.

| Claim it supports | Source | Locator and what was read | Status |
| --- | --- | --- | --- |
| Three-grid apparent order with `q(p)` for unequal ratios, extrapolated value, approximate and extrapolated relative errors, `GCI_fine` with factor 1.25; three "significantly different" grids; `r = h_coarse/h_fine` greater than 1.3 "based on experience and not on formal derivation"; a negative `eps32/eps21` indicates oscillatory convergence; the procedure "does not work" when either difference is very close to zero | I. B. Celik, U. Ghia, P. J. Roache, C. J. Freitas, "Procedure for Estimation and Reporting of Uncertainty Due to Discretization in CFD Applications", ASME J. Fluids Eng. 130(7), 078001 (2008) | Steps 2-5, eqs (3a) `p = |ln|eps32/eps21| + q(p)| / ln r21`, (3b) `q(p) = ln((r21^p - s)/(r32^p - s))`, (3c) `s = sgn(eps32/eps21)`, (4) `phi_ext = (r21^p phi1 - phi2)/(r21^p - 1)`, (5)-(7) `GCI_fine = 1.25 e_a / (r21^p - 1)`; Celik orders grids fine to coarse (`h1 < h2 < h3`) | **relevant passage checked.** Cross-check: with the repository's coarse-to-fine ordering (`h1 > h2 > h3`, `e21 = Q2 - Q1`, `e32 = Q3 - Q2`, `r21 = h1/h2`, `r32 = h2/h3`) the power-law model gives `e21/e32 = r32^p (r21^p - 1)/(r32^p - 1)`, the equation `validation/richardson.py` solves; `Q0 = Q3 + e32/(r32^p - 1)` is eq. (4) at the finest pair and `gci = 1.25 |e32/Q3| / (r32^p - 1)` is eq. (7); the module's `NOT_ESTIMATED` reasons (flat, oscillatory, non-shrinking) correspond to Celik's "very close to zero" and oscillatory cases. The pupil ratio 16:20 = 1.25 is below Celik's recommended 1.3 (PROTOCOL.md 2.4) |
| Residual noise of a mode under an integrator with time delay: `<z'^2> = int H_cor |z|^2 df + int H_n |m|^2 df` (eq. 14) and, for white measurement noise, the noise term `p(i) sigma_n^2 int H_n(f, g) df` (eq. 15) with the propagation coefficient `p(i) = (D^t D)^-1_ii` (eq. 7); loop of Fig. 1 with `h_sys(f) = e^(-2 i pi tau f)/(2 i pi f)`, an integrator plus delay | E. Gendron, P. Léna, "Astronomical adaptive optics. I. Modal control optimization", A&A 291, 337-347 (1994) | sections 2.3.3, 3.2 and 4.2, eqs (7), (9)-(15), Fig. 3 (`H_n` for g = 0.05-0.4, 200 Hz, 3.5 ms delay) | **relevant passage checked** (scanned pages read). The structure of PROTOCOL.md 1.6, `DeltaV = kappa * sum_r sigma_r^2 w_r` with `kappa = int |h_n|^2`, is this result in discrete time with the repository's DM-space propagation weights in place of `p(i)`; the paper gives the continuous-time integrator-plus-delay form, not the closed-form `g/(2-g)`, which remains the packet's own check |
| Discrete pure integrator `y(k+1) = y(k) + g u(k+1)`, `C(z) = g/(1 - z^-1)` (eqs 4-5) and leaky integrator with forgetting factor `f`, `C(z) = g/(1 - f z^-1)` (eqs 6-7); rejection and noise transfer functions of the closed loop with a pure-delay plant | G. Agapito, E. Pinna, A. Puglisi, F. Rossi, "Elephants, goldfishes and SOUL: a dissertation on forgetfulness and control systems", Proc. SPIE (2019), arXiv:1911.05989 | section 3, eqs (4)-(7), Figs 2-3 (RTF and NTF with a 2.5 ms pure delay) | **relevant passage checked.** Fixes the filter form and the leak's place (`f = 1 - leak`) used in the derivation of section 3; the NTF with delay appears in figures, not as a printed equation |
| Gauss quadrature error for an integrand analytic in the Bernstein ellipse of parameter `rho > 1`: `|I - I_n| <= 64 M / (15 (1 - rho^-2) rho^(2n+2))` (geometric in `n`); algebraic rates only for finitely differentiable integrands (eq. 4.13) | L. N. Trefethen, "Is Gauss Quadrature Better than Clenshaw-Curtis?", SIAM Review 50(1), 67-87 (2008), DOI 10.1137/060659831 | Theorem 4.5, eqs (4.13)-(4.14); Theorem 4.1 (Bernstein) | **relevant passage checked.** Supports the spectral axis being declared non-power-law: the detected intensity varies smoothly with wavelength across the 600-900 nm band, so the node count converges geometrically and no algebraic order is fitted |
| Blocking (batch-means) error of correlated series | H. Flyvbjerg, H. G. Petersen, "Error estimates on averages of correlated data", J. Chem. Phys. 91, 461 (1989), DOI 10.1063/1.457480 | whole paper | listing only (paywalled); the plateau rule of the analysis script is the repository's own declared rule |
| Integrated autocorrelation time with the automatic window `M >= c tau(M)` | N. Madras, A. D. Sokal, "The pivot algorithm: a highly efficient Monte Carlo method for the self-avoiding walk", J. Stat. Phys. 50, 109-186 (1988), DOI 10.1007/BF01022990 | appendix on autocorrelation estimation | listing only (paywalled) |
| Servo-loop transfer functions of an AO integrator with delay | M. Demerlé, P.-Y. Madec, G. Rousset, "Servo-loop analysis for adaptive optics", in Adaptive Optics for Astronomy (NATO ASI, Cargèse 1993), Kluwer 1994, pp. 73-88 | — | listing only; superseded for this packet by the two checked sources above |
| Centroid noise terms of the centre of gravity (already cited by the repository) | S. Thomas et al., MNRAS 371, 323 (2006) | ledger D4 version 2 (full text read in the repository's G11 work, not here) | repository ledger |

Consequence for the protocols: the Richardson rules are the repository's
implemented and tested rules and now also match the cited procedure passage
by passage; the loop model of PROTOCOL.md 1.6 has its structure in Gendron
and Léna (1994) and its discrete filter form in Agapito et al. (2019), while
its numerical constants remain this packet's derivation; the blocking and
autocorrelation rules stay the repository's declared rules with
listing-status attributions.

## 5. Bounded checks of this session (what was executed)

See `README.md` section 4 and `records/cloud_checks/SUMMARY.md`. Executed:
the targeted test selection, the T2 ci self-check under the guard, the 2 m
traced replay and its analysis (including the 2 m verification step of
PROTOCOL.md 1.6, which did not confirm the loop model under actuator
clipping). Not executed: every pilot and stage of `pilot_requests.json`, any
12 m or 42 m run, any slow test, any HCIPy test.
