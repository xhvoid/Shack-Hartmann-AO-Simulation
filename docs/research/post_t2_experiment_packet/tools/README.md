# Caller-owned launchers and analysis tools named by the pilot requests

These scripts are part of the packet for review. None of them is runtime
code: they live outside `src/`, `scripts/`, `examples/` and `tests/`, import
the installed package's public functions and the two study drivers (by path,
registered in `sys.modules` before execution so that the drivers' dataclasses
resolve their annotations; `_packet_common.py`), and change no profile,
baseline or record. Every tool refuses to overwrite an existing output,
requires `--enabled-by-user` for a governed configuration exactly as the
drivers do, and writes one JSON record. Their records are timing, admission
and implementation evidence; they carry no scientific claim and are never
placed in a study's `runs/` directory or beside a series' record.

| Script | Purpose | Used by | Validated (ungoverned, review round 1) |
| --- | --- | --- | --- |
| `authorized_supervise.py` | run one command under `shwfs_ao.runtime.resource_guard` with a human-authorized budget above the desktop policy, mirroring the ESO runner's `_authorized_decision` (non-empty note, margined estimate within the authorized budget, largest buffer under the 64 MiB scratch ceiling, memory pressure `normal`, available memory at least the raw estimate plus 1 GiB); the policy preflight runs first and is recorded; a refusal for any reason other than the budget is never overridden | S4-A1, P2, P2b, P3, E3 | syntax and `--help`; no governed run |
| `timing_pilot_fixed_physics.py` | run exactly one planned setting of `scripts/detector_level_convergence_study.py` through `experiments.convergence_study.fixed_physics_paired_run` with the driver's own plan, execution options and row composition (`_run_child` plus `run_protocol`), validate the row with the driver's `check_run` against the planned protocol, and record the validated row, an `acceptance_evidence` block (arms, digests, atmosphere and exposure metadata, geometry, detector budget, saturation, usable fractions, recovery, science metrics, Fourier reference status, paired `DeltaV` summary), wall time and peak RSS | P1a-P1c, P3 | ci scale under the guard: `check_run` passed; every scalar and digest bit-identical to the T2 ci self-check row of the same key (`records/cloud_checks/round1/p1_ci/`) |
| `timing_pilot_traced_run.py` | run one traced paired run (`paired_noise_run_traced`) of a profile or of the ci geometry at one magnitude and seed; record the seven recorded quantities and their comparison with a historical record (`--historical`), per-arm telemetry summaries (saturation, rejected reconstructions, recovery), mask disagreement, the `DeltaV` series summary, the E0 summary, the trace size; optionally write the trace once in the series' sidecar layout under the pilot schema (`--trace-sidecar`) for the model below | P2 | 2 m m5 seed 61: seven quantities within 8.3e-10 relative of the committed desktop record; ci geometry m7 and m9 (`records/cloud_checks/round1/`) |
| `linear_loop_noise_model.py` | the exact linear closed-loop detector-noise model of `PROTOCOL.md` 1.6 with the reconstructed spatial feedback `L = R M`: feedback spectrum, transient (finite-window) and stationary covariance of the command difference, prediction of `DeltaV`, the scalar unit-feedback reduction beside it, the noise covariance from a traced sidecar's realized residuals under two support rules (`available`, primary: lenslets usable in at least 90 % of the analysed frames with the covariance over their own valid frames; `strict`: lenslets usable in every frame, the E0 rule) or from the flat-wavefront model, identity check of the sidecar's configuration hash, pilot-level comparison with the measured `DeltaV`; `--self-test` checks the solver against `kappa` | P2b; S4 A1 analysis | self-test; 2 m (33 sidecars: exact equals the scalar factor, `L = I`); ci geometry with the ci damping and with the 12 m damping (`--alpha 0.1`, diagnostic) |
| `quarantine_leftovers.py` | list and, with `--apply`, move aside the leftovers of an interrupted invocation that both drivers refuse (temporary `*.tmp-*` publication files, orphan sidecars, a stale twin disk record) into `leftovers/<UTC>/` with a manifest; nothing is deleted or rewritten; planned run files, referenced sidecars and the record are never candidates | every stage's resume procedure (`README.md` 2.4) | synthetic interrupted study and series directories (`records/cloud_checks/round1/quarantine_demo/`) |
| `_packet_common.py` | shared helpers: driver import by path, configuration selection (`--profile`/`--ci-geometry`, `--magnitude`, diagnostic `--alpha`), the run configuration a paired run hashes, record writing | the tools above | through them |

`--alpha` is a diagnostic reconstructor-damping override for tool validation
only: it changes the configuration hash, is recorded in every output, and is
never part of a governed series (the 12 m series uses the profile's damping).
