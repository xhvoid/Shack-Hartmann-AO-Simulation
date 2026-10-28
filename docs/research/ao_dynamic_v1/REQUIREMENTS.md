# Generated-experiment mode: requirements (API v1)

This contract governs the **Generate an experiment** mode added to the AO
Simulation Explorer after its precomputed release. It is separate from, and
does not amend, the [precomputed release requirements](../ao_2m_interactive_v1/RELEASE_REQUIREMENTS.md):
the published frozen explorer, its dataset `series-2m180-b3e1c66-e0d60cbaccc6b`
and the Research Results remain governed by that record. The earlier release
did not support live generation; this mode was authorized later as a bounded
extension and is implemented in `scripts/ao_dynamic/` and the
`generate*.js` modules of the content-addressed site build.

## Scope

- Canonical native profile `det_emccd_2m_synthetic@1`: 2 m, 52 pupil samples,
  5 x 5 lenslets/actuators, 700 nm WFS with the synthetic EMCCD (noise on),
  `native_frozen_flow_v2` atmosphere (subharmonic von Karman spectrum, exact
  Fourier sub-pixel translation), 1 kHz, leak 0.02, legacy left-point WFS
  exposure (one atmosphere sample per frame), science at 1.65 µm.
- Only these parameters may change; every request must state all of them:

| Parameter | Supported values | Basis |
| --- | --- | --- |
| `seed` | integer 1 – 2 147 483 647 | root of the named random streams; 1 is the frozen explorer's realization |
| `r0_m` at `r0_reference_wavelength_m` | 0.06 – 0.30 m at exactly 500 nm | lower bound keeps the 39.2 mm pupil sampling below half of r0 at the 700 nm WFS wavelength; upper bound limits the initial range |
| `wind_speed_m_per_s`, `wind_direction_deg` | 0 – 30 m/s; integer 0 – 359° (counter-clockwise from +x, the flow direction) | admitted per run against the finite screen (below) |
| `guide_ab_magnitude` | 4.0 – 9.0 AB mag | the noise-free calibration found no valid rows at AB 3, 10 and 11 (measured probe) |
| `controller_gain` | 0 – 1 | unstable combinations are allowed and labelled with the largest pole modulus |
| `queued_latency_frames` | integer 0 – 6 | delay L; first WFS-visible at k + L + 1 |
| `n_frames` | integer 16 – 400 | measured cost 52 ms/frame (2 threads) keeps 400 frames well inside the 240 s job limit; the screen admits fewer frames at higher wind |
| `burn_in` | integer 0 – n_frames − 8 | at least 8 analysis samples |
| `display_stride` | integer 1 – 10, at most 200 replay frames | display sampling only; never changes histories or averages |

- Aperture, sampling, atmosphere model, outer scale and wavelengths are fixed.
  Requests are validated on the service; nothing is clamped, rounded or
  defaulted, and a refusal lists every reason.

## Randomness, time and admission

- One seeded realization per run, generated once at t = 0 and translated by
  frozen flow; frames are never redrawn. A new realization has a new seed and
  identity. Replays are labelled as replays, including loop replay.
- Before a job is queued, and again in the worker, the frozen explorer's
  complete-horizon admission (`scripts/ao_explorer/admission.py`) evaluates
  every atmosphere request time against the factory's actual screen
  (156 samples, 52 px travel budget, endpoint-inclusive spacing 2/51 m):
  frame starts, left-point multisample, midpoint n = 1 and n > 1 branches, no
  slack. At 10 m/s, 204 frames are admitted and 205 refused. The rule is
  mandatory regardless of the optional memory guard. Screens are never
  wrapped, reset, blended, enlarged or slowed; a finite run ends normally.
- Changing gain, guide magnitude or queued delay keeps the atmosphere of the
  same seed. A comparison is labelled paired only when the time grids and
  every per-frame atmosphere SHA-256 match. Changing r0 or wind changes the
  physical atmosphere (same random draws, different screen); a new seed is a
  new realization.
- Calibration is rebuilt for every run (central differences, noise-free). Its
  identity depends on the seed and the guide magnitude; gain, delay, r0 and
  wind leave it unchanged. Each run records the interaction-matrix, WFS and
  reconstructor identities.

## Images, metrics and observations

- Reuse of the canonical runner, `ExplorerObserver` and native propagator.
  Per frame: uncorrected PSF from that frame's atmosphere with zero DM,
  AO-corrected PSF from its pre-update residual, held correction = atmosphere −
  residual (OPD-equivalent). Unit total flux on the uncropped 156 x 156 grid;
  peak Strehl against the zero-OPD image of the same propagator, wavelength and
  grid; tilt kept; nothing recentred.
- Instantaneous Strehl, mean instantaneous Strehl and the Strehl of the
  averaged intensity are distinct. Averages are equal-weight means of
  intensities of every frame in `[burn_in, n)`, never of OPD or phase.
- Internal OPD is metres. Phase display: `phase_rad = 2π · OPD_m / λ` at a
  stated wavelength (1.65 µm science or 0.70 µm WFS), unwrapped; display piston
  removal, one colour limit per run for all frames and all three maps, and
  clipped fractions are recorded per replay frame.
- Synthetic observations: the fixed incoherent binary (weights 2/3 and 1/3,
  primary at exact zero angle, secondary +6 native x cells, scene total 1,
  independent of the guide magnitude) convolved by exact linear zero-extended
  convolution with the numerical PSFs, cropped to the native window by
  coordinates, with full/cropped flux bookkeeping and one shared display
  mapping. Three kinds: instantaneous; running post-burn-in average over every
  eligible frame (unavailable before burn-in, with its sample count and
  window); completed-window average. One on-axis PSF is assumed across the
  scene (illustrative); no science-camera noise, counts, SNR or detection claim.
- The observer, progress transport and display stride are passive: loop
  histories, RNG consumption, controller state and all reductions are
  unchanged by them.

## Service and frontend

- One numerical job at a time, bounded queue, owned worker process group with
  two native threads and a wall-clock limit. States: queued, running,
  completed, cancelled, failed. Cancellation stops the group and removes
  partial outputs; closing a browser does not cancel, but a job nobody asks
  about is cancelled as abandoned after a configurable lease.
- A run binds its immutable effective configuration and seed, API/schema and
  producer identities (code digests, Git state, core package, environment
  lock), atmosphere and calibration identities, time grid, units, axes,
  normalization, residual timing, analysis window and sample counts, scene,
  numerical parents, renderer, resources and checks. The service and the page
  both refuse records that break these semantics, independently of digests.
- Generated runs have their own identities and storage namespace; they never
  change the frozen dataset. The published static site needs no service and
  makes no new request unless a visitor presses Connect (a `?backend=` link
  only fills in the address). Every value from a service is treated as data
  (escaped markup, validated identifiers and file references), and each
  displayed run names the service origin that computed it.
- The service answers only its own Host names, refuses cross-origin writes
  from unlisted origins, bounds request bodies and its job history, times out
  idle connections, and its workers exit if the supervising service
  disappears.
- The page installs a run atomically after size, SHA-256 and semantic checks;
  generation tokens make A→B→A selection, cancellation, supersession, late
  responses and reconnects unable to mix runs. Downloads are the verified
  bytes of the displayed run.
- Content-addressed builds are kept: changing page bytes requires
  `python scripts/ao_explorer/site_build.py --web-dir web/ao-explorer --write`.

## Validation bounds

One 64/16 pilot and five 180/40 runs (baseline, same-seed replay with display
stride 3, a different seed, a same-atmosphere guide-magnitude change, an
observer-disabled passivity control), plus small fixtures. Ceilings: 20 min
numerical/processing wall time and 512 MiB raw evidence in a new plan and
ledger (`outputs/ao_dynamic_validation/fv1`), serial, two threads, explicit
timeouts. See [VALIDATION.md](VALIDATION.md).
