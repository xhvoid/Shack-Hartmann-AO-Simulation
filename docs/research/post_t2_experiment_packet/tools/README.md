# Caller-owned launchers named by the pilot requests (proposed, unexecuted)

These three scripts are part of the packet for review. None of them is
runtime code: they live outside `src/`, `scripts/`, `examples/` and `tests/`,
import only public functions of the installed package and of the two study
drivers, and change no profile, baseline or record. They were syntax-checked
and their `--help` was exercised in this session; none was run on a
governed configuration.

| Script | Purpose | Used by |
| --- | --- | --- |
| `authorized_supervise.py` | run one command under `shwfs_ao.runtime.resource_guard` with a human-authorized budget above the desktop policy, mirroring the ESO runner's `_authorized_decision` (non-empty note, margined estimate within the authorized budget, largest buffer under the 64 MiB scratch ceiling, memory pressure `normal`, available memory at least the raw estimate plus 1 GiB); the policy preflight runs first and is recorded; a refusal for any reason other than the budget is never overridden | S4-A1, P2, P3, E3 |
| `timing_pilot_fixed_physics.py` | run exactly one planned setting of `scripts/detector_level_convergence_study.py` (same `SystemConfig`, atmosphere options, exposure override, execution options, frames, burn-in, seed, realization) through `experiments.convergence_study.fixed_physics_paired_run` and record wall time, the process's own peak RSS and the planned protocol it mirrors; a timing pilot, not a study run | P1, P3 |
| `timing_pilot_traced_run.py` | run exactly one traced paired run of the S4 A1 configuration (`paired_noise_run_traced` at one magnitude and seed, maps retained on request) and record wall time, peak RSS, the recorded scalars and the uncompressed size of what a sidecar would hold | P2 |

Each launcher refuses to overwrite an existing output file, requires
`--enabled-by-user` for governed configurations exactly as the drivers do,
and writes one JSON record. Their records are timing and admission evidence
(`MEASURED_CURRENT` once run); they carry no scientific claim and are never
placed in a study's `runs/` directory.
