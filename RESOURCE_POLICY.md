# Execution resource policy

Memory/pressure enforcement is disabled by default. This applies to future
checkouts and installed packages. Run ordinary checks directly; a warning
pressure signal or estimated memory budget does not block them automatically.

`AO_RESOURCE_GUARD=1` explicitly opts back into memory-budget, scratch-buffer
and pressure enforcement. `0`, `off`, or an unset variable keeps it disabled.
The preflight and supervisor records include `enforcement_enabled`. When off,
preflight reasons are advisory, and the supervisor does not run memory/pressure
probes or stop a job because of those signals. Reported policy budgets remain
estimates; they must not be described as enforced or measured caps.

Timeouts, owned-process cleanup and native-thread limits remain independent
execution controls. Large-run enablement and scientific study scope also remain
explicit: turning off the memory guard does not request new trajectories,
calibration, large-aperture studies or expanded ensembles. Preserve cumulative
wall-time/evidence accounting and historical producer identities.

This is the current policy. Older archived plans and historical supervisor
records describe the settings used for those studies and are retained as such.
The static explorer's accepted numerical evidence is unchanged by this setting.
