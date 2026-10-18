# Repository Optimization Ticket

Last updated: 2026-07-10

## Objective

Resolve the confirmed review findings in small, independently verifiable changes while preserving the repository's documented educational/synthetic scope. This file is the durable checkpoint for work performed across multiple Codex turns.

## Baseline

- Reviewed revision: `9c4816c` (`origin/main` at review time).
- Working tree at start: clean on local branch `public-clean-main`.
- Python used for the initial full run: 3.14.3.
- Initial test result: `102 passed, 1 failed in 237.05s`.
- Initial failure: generated parameter-source inventory differs from the committed Markdown by one terminal newline.
- Wheel build succeeds, but the wheel does not contain runtime data resources.

## Execution rules

1. Execute tickets serially in ticket-number order unless a dependency is documented.
2. Keep only one ticket `IN PROGRESS` at a time.
3. Add an independent regression test for every correctness fix. A test must not obtain its expected value from the same implementation under test.
4. Run focused tests after every ticket. Run the full suite after T03, after the scientific/numerical phase, and at final completion.
5. Do not weaken assertions, broaden tolerances without justification, or accept regenerated baselines blindly.
6. Preserve unrelated user changes. Do not commit, push, change branch, tag, release, or open a PR.
7. Regenerate tracked CSV/JSON/PNG artifacts only when corrected behavior requires it; record every regenerated artifact in the execution log.
8. Prefer physically explicit failures over silently replacing invalid pupil data with zero.

## Status legend

- `PENDING`: not started.
- `IN PROGRESS`: currently being implemented.
- `DONE`: implementation and focused verification complete.
- `BLOCKED`: requires user input or external state; record the reason.

## Ticket queue

### T01 — Restore inventory consistency and green CI

- Priority: P1
- Status: DONE
- Scope: `scripts/build_parameter_source_inventory_pdf.py`, committed inventory Markdown, and the inventory consistency test.
- Problem: the generator emits two terminal LF characters while the committed document has one.
- Acceptance:
  - establish exactly one canonical terminal newline;
  - retain the meaningful exact-content drift check;
  - `tests/test_inventory_consistency.py` passes.

### T02 — Correct gradients on a masked pupil

- Priority: P1
- Status: DONE
- Scope: `src/reconstruction.py` and reconstruction tests.
- Problem: pupil-exterior NaNs are converted to zero before differentiation, creating false edge slopes.
- Acceptance:
  - analytic `W=x` gives `sx≈1`, `sy≈0` in all retained subapertures;
  - analytic `W=y`, piston, and quadratic cases pass independent checks;
  - modal reconstruction tests remain compatible.

### T03 — Shift full finite phase screens before pupil masking

- Priority: P1
- Status: DONE
- Scope: `src/phase_screen.py`, legacy loop helpers in `src/ao_closed_loop.py`, notebooks 07/10 call paths, and tests.
- Problem: rolling a masked NaN-outside screen after filling NaNs with zero injects a false crescent and lowers atmospheric RMS.
- Acceptance:
  - frozen flow requires or preserves a complete finite screen;
  - masking and piston removal occur after translation;
  - piston, RMS-preservation, wraparound, and physical/pixel-shift equivalence tests pass.

### T04 — Use a fixed lenslet aperture and detector-pixel scale

- Priority: P2
- Status: DONE
- Scope: `src/shwfs_detector.py`, detector calibration/measurement helpers, and centroid tests.
- Problem: the FFT size follows each illuminated bounding box, so partially illuminated edge lenslets have a different focal-plane pixel scale.
- Acceptance:
  - every lenslet uses the same nominal cell sampling and detector scale;
  - a uniform phase tilt produces consistent centroid displacement across lenslets;
  - detector window and clipping semantics remain explicit.

### T05 — Add a physical atmosphere time axis and isolate scenario effects

- Priority: P2
- Status: DONE
- Scope: `src/ao_error_budget.py`, `src/atmosphere_profiles.py`, `src/ao_conditions.py`, and the public-data-informed demo.
- Problem: dynamic phases ignore frame rate/tau0/wind, and one seed controls both phase truth and detector noise; default effect rows use different truth realizations.
- Acceptance:
  - `dt=1/frame_rate_hz` affects evolution;
  - seeing/r0, wind, and documented temporal parameters affect the generated truth or are clearly marked metadata-only;
  - phase, detector-noise, and NCPA seeds are separate;
  - effect-isolation scenarios share the same atmospheric truth cube.

### T06 — Correct DM fitting and command statistics

- Priority: P2
- Status: DONE
- Scope: `src/dm_model.py`, `src/ao_error_budget.py`, loop diagnostics, tests, and affected tables/docs.
- Problems:
  - the fitter solves an unprojected influence matrix against a piston-removed target;
  - dead/stuck actuator constraints are applied after fitting;
  - `command_rms_nm` currently stores an L2 vector norm.
- Acceptance:
  - solve the piston-projected usable-actuator system;
  - same-basis round trips reach numerical precision without active limits;
  - dead, stuck, and stroke-limited cases are tested;
  - command RMS is `sqrt(mean(command**2))`; retain L2 norm only under an accurate name.

### T07 — Correct science-band and PSF metrics

- Priority: P2
- Status: DONE
- Scope: `src/ao_diagnostics.py`, `src/psf_tools.py`, and metric tests.
- Problems:
  - filter weights omit wavelength quadrature spacing;
  - even FFT outputs are measured around a half-pixel-offset center;
  - non-finite pupil phase can be interpreted as an ideal zero phase.
- Acceptance:
  - wavelength-aware quadrature is invariant to benign filter resampling;
  - PSF centering is consistent across Strehl/FWHM/EE/halo and documented for tip/tilt;
  - NaN/Inf inside the pupil raises, while NaN outside remains supported;
  - ideal Airy and known-aberration checks pass.

### T08 — Stabilize reconstruction and Zernike numerics

- Priority: P2
- Status: DONE
- Scope: both Tikhonov implementations, `src/zernike.py`, singular-mode selection, and tests.
- Problems:
  - normal equations fail for rank-deficient matrices at zero or small alpha;
  - factorial Zernike summation is unstable at high order;
  - impossible `minimum_kept_modes` requests silently violate the configured lower bound.
- Acceptance:
  - alpha zero uses least squares/pseudoinverse;
  - positive-alpha solves are stable via SVD or an augmented system;
  - high-order Zernike endpoint/orthogonality tests pass or a justified supported-order limit is enforced;
  - impossible minimum-mode requests raise clearly.

### T09 — Make calibration/config hashes complete

- Priority: P2
- Status: DONE
- Scope: interaction-matrix and downstream loop/config hashes.
- Problem: response-changing geometry, centroid, detector, coordinate, pupil, and valid-row state is omitted.
- Acceptance:
  - all response-relevant scalars are included;
  - array-valued state uses stable content digests;
  - identical builds hash identically;
  - changing any response-relevant setting changes the hash.

### T10 — Enforce detector, PWFS, and latency input contracts

- Priority: P2
- Status: DONE
- Scope: `src/synthetic_instrument_data.py`, `src/pwfs_forward.py`, latency configuration/queue logic, and tests.
- Problems:
  - `photons=None` is documented as deterministic but can still receive read noise;
  - PWFS allows exterior NaNs to poison the FFT and has no dedicated tests;
  - odd cutout sizes return `N-1` pixels;
  - duplicate PWFS helpers exist;
  - fractional latency is accepted, applied, reported, and truncated inconsistently.
- Acceptance:
  - deterministic detector semantics are enforced or incompatible configurations are rejected;
  - PWFS supports NaN only outside the pupil and rejects interior invalid values;
  - even/odd geometry and modulation are tested;
  - latency is an actual integer and applied/reported consistently.

### T11 — Package runtime resources in a normal wheel

- Priority: P2
- Status: DONE
- Scope: `pyproject.toml`, package/resource layout, integration resource loading, and install smoke tests.
- Problem: wheel installs omit `data/`, rely on a source-repository root, fail to load reference metrics, and silently downgrade SVO bandpasses.
- Acceptance:
  - use standard package resources rather than source-tree-relative paths;
  - a non-editable fresh installation outside the repo imports modules, loads default references/SVO curves, and runs an installed-package smoke path;
  - direct-data fallback is explicit in provenance.

### T12 — Enforce real baselines, generated-artifact consistency, and Notebook 11 paths

- Priority: P2
- Status: DONE
- Scope: integration tests, tracked regression baselines, CI generation paths, and Notebook 11.
- Problems:
  - current tests validate only outputs created by the same run;
  - tolerances and committed baselines are unused;
  - CI regenerates tracked outputs without checking drift;
  - Notebook 11 mixes `figures/generated` with `figures/detector_level_SCAO`.
- Acceptance:
  - normal tests read immutable committed baselines and apply documented tolerances;
  - baseline updates require an explicit maintainer command;
  - generators use temporary outputs or verify semantic drift;
  - Notebook 11 uses one configured output path and asserts that public-data tables are actually loaded.

### T13 — Validate units, portability, and third-party data notices

- Priority: P2/P3
- Status: DONE
- Scope: data loaders, tracked filenames/references, and public-data documentation.
- Problems:
  - unit strings are checked only for presence while consumers assume canonical units;
  - `figures/PWFS_Sx:Sy.png` is not Windows-portable;
  - redistributed public data lack a per-source terms/acknowledgement notice.
- Acceptance:
  - supported units are converted to canonical units and unsupported units are rejected;
  - tracked filenames pass a Windows-portability check;
  - `DATA_LICENSES.md` or `NOTICE` records source terms links, redistribution status, acknowledgements, and unresolved items without unsupported legal claims.

### T14 — Improve CI and release reproducibility

- Priority: P3
- Status: DONE
- Scope: GitHub Actions, dependency constraints, ignores, and release metadata guidance.
- Acceptance:
  - test the declared minimum Python and a current stable Python;
  - provide a reproducible constraints/lock path while keeping sensible package metadata;
  - use explicit minimal workflow permissions and immutable action versions where practical;
  - ignore build/test artifacts;
  - align package/CITATION/release instructions without creating a tag or release.

## Phase gates

- Gate A after T03: full test suite and local CI-equivalent commands pass.
- Gate B after T10: all scientific/numerical regression tests pass; record before/after reference values.
- Gate C after T14: fresh-wheel install, offline integration, Notebook 11 smoke, full suite, `git diff --check`, and final status review pass. **DONE**

## Execution log

| Ticket | Status | Verification | Notes |
| --- | --- | --- | --- |
| T01 | DONE | `1 passed in 0.04s` | Generator now emits exactly one terminal newline; exact drift check retained. |
| T02 | DONE | `7 passed in 0.07s` | Added masked central/one-sided derivatives plus independent linear, piston, and quadratic checks. |
| T03 | DONE | `111 passed in 243.28s` (Gate A) | Full finite-screen contract added; Notebook 10 no-correction tail RMS changed from artificial `3.623` to `4.073` rad for a `4.000` rad initial screen. |
| T04 | DONE | `32 passed in 1.00s` | Uniform-tilt max/min response improved from about `1.47` to `1.077`; all detector spot arrays now share one shape. |
| T05 | DONE | `26 passed in 12.60s` | Dynamic truth now uses seconds, tau0, and wind; phase/detector/NCPA seeds are isolated; all default dynamic effect rows share one truth cube. |
| T06 | DONE | `21 passed in 11.11s` | Fitting now projects target/influences together, solves usable/fixed actuators with stroke bounds, and separates actuator RMS from L2 norm. |
| T07 | DONE | `24 passed in 12.31s` | Added trapezoidal wavelength weights, peak-centered shape metrics, tip/tilt invariance, and strict interior finite checks. |
| T08 | DONE | `29 passed in 1.22s` | Both Tikhonov paths use rank-aware SVD filters; Zernike uses stable Jacobi evaluation; impossible mode lower bounds raise. |
| T09 | DONE | `28 passed in 12.29s` | Hash schema now includes canonical array digests for calibration/DM/response/truth state and full science-band settings. |
| T10 | DONE | `58 passed in 12.08s`; Gate B: `157 passed in 239.47s` | Deterministic detector, PWFS finite/odd-even geometry, single-helper ownership, and exact integer latency contracts are enforced. |
| T11 | DONE | wheel smoke: `1 passed in 1.93s`; resource paths: `33 passed in 221.87s` | Wheel includes standard `ao_simulation_data` resources; fresh non-editable install loads references, direct SVO J/H/K, and DM preset outside the repo. |
| T12 | DONE | `6 passed in 221.26s` | Tests consume immutable JSON/CSV baselines; updates require an acknowledgement flag; CI writes to temp; Notebook 11 uses one artifact directory and requires public rows. |
| T13 | DONE | `16 passed in 0.13s` | Loaders convert supported atmosphere, filter, coordinate, and magnitude units to canonical contracts and reject unsupported units; tracked paths are Windows-portable; per-source data notices record terms links and unresolved redistribution questions. |
| T14 | DONE | focused Gate-C subset: `17 passed in 2.00s`; metadata parse and `pip check` pass | CI tests Python 3.10/3.14 with exact constraints; workflow actions use verified tag SHAs and read-only permissions; build/test artifacts are ignored; package/CFF/release guidance is aligned without tagging or publishing. |
| Gate C | DONE | canonical environment: `166 passed in 239.42s`; pinned Python 3.14: 165 non-wheel tests passed, corrected wheel smoke `1 passed in 1.55s`; both `pip check` runs, metadata parse, and `git diff --check` pass | Fresh non-editable wheel includes runtime resources and license notices; offline integration and Notebook 11 smoke pass; the 7-page regenerated inventory PDF was rendered and visually checked; final worktree contains only intentional ticket changes and no commit/tag/release/push. |
