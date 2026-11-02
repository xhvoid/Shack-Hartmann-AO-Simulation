# Gain-study wording corrections

Corrections recorded 30 October; wording revised 2 November 2026.

These notes accompany the original gain–latency execution reports without changing
those reports, archives, manifests or hashes.

**GL-R01 — concurrency timing.** Concurrent run durations were within the
observed serial range on this host; no matched serial/concurrent benchmark or
whole-session peak measurement was performed. The three concurrent durations
were approximately 5,074–5,076 seconds; the two serial durations were
4,784–5,089 seconds. These were different trajectories, not a controlled
performance benchmark.

**GL-R02 — preservation exception.** The earlier statement that every file was preserved needs one correction:
with the project maintainer's agreement, cleanup removed 111 verified, re-fetchable export
intermediates, totaling 3,475,187,254 bytes, from earlier photon-budget and
latency workspaces. Retained scientific records and durable remote evidence
are distinct from these intermediates. The cleanup did not remove those retained scientific or remote records.

Resource figures, if cited: aggregate supervised duration 30,163.495 seconds
(including overlapping runs); largest fresh-child peak 1,345.160 MiB
(approximately 1.314 GiB); sum of peaks of concurrent children 3–5,
3,989.137 MiB; new run payload 1,083,901,568 bytes. The sum of child peaks
excludes parents, analysis and session overhead. It is not a measured
whole-session peak.
