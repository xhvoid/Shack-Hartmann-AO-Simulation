# Explorer implementation and provenance

Implemented and reviewed on 22–23 October 2026. This public record summarizes
the retained scientific evidence; local working logs and coordination notes
remain outside the release. See [acceptance](ACCEPTANCE_REPORT.md),
[requirements](RELEASE_REQUIREMENTS.md) and [development](../../../DEVELOPMENT.md).

## Source and environment

- Runtime source: `8053d25216ac180e327bf0b53afd93d1fc08d4ca`, tree
  `061b099af361a7c4d9b3bc5b96a7d1331dfac95d`. Exact-source CI run
  [39857542916](https://github.com/xhvoid/Shack-Hartmann-AO-Simulation/actions/runs/39857542916)
  succeeded. It descends from accepted integration `094b7b4`; runtime changes
  between those anchors were documentation and a diagnostic-path string.
- Physical producer milestone: `b3e1c663a162abb1cebeb5ccecb2640346daa50a`,
  committed before frozen generation. The six-file producer identity remains
  unchanged; derived export, binary rendering, frontend build and physical-run
  identities are separate. Exact file inventories are in bundled provenance.
- Numerical environment: CPython 3.14.3, macOS 26.5 arm64, Apple M1 Pro,
  8 logical CPUs, 16 GiB RAM; two native threads and one numerical child at a
  time. The macOS maintainer lock `constraints/hcipy-py314.txt` was verified
  against 23 installed distributions after removing an unused unpinned wheel
  distribution. NumPy 2.5.0, SciPy 1.18.0, matplotlib 3.11.0, Pillow 12.2.0.
- Accepted candidate and dataset/build/manifest identities are recorded in
  [ACCEPTANCE_REPORT.md](ACCEPTANCE_REPORT.md). The numerical environment's
  imported package came from its isolated producer checkout.

Original working-specification SHA-256 values (the originals remain local;
the tracked release requirements are an edited public contract, not byte copies):

| Input | Original SHA-256 |
| --- | --- |
| Implementation assignment | `951a1ba2af02088f98dca785f42077a24d36ae394803975f1c58d030c0496947` |
| Design plan | `57488e6d3f0829bdfbbc981534a8df9865ac7227d52d9bf566ed6cb549f568c1` |
| Research coverage | `d9693db50a1806a49c10f3f12a3c9bb060a90f558326312778b707d3e65d9cd5` |

## Protocol and numerical checks

The unchanged native profile is `det_emccd_2m_synthetic@1`. The eight
180-frame cases and their exact metric/image semantics are in the release
requirements and machine-readable case/config records. Production summaries
use `[40,180)`, 140 equal weights; the 40 movie frames do not define a metric.
The independent exact-rational horizon oracle covers legacy, left-point and
midpoint exposure branches and checks over-horizon refusal without slack.
For production the measured maximum is 45.645 px against 52 px support.

A separate 64-frame, burn-in-16 pilot used eight movie indices and 48 analysis
samples. The observer-disabled baseline checked passivity; a second seed
checked sensitivity without establishing an ensemble. Raw maps, numeric mean
PSFs, complete axes, scene/parent identities and telemetry are retained locally.
The frozen plan SHA-256 is
`5c518c11ea14cc8a0cc70b08eb186701b04d5261300a154ffba0d9ed08456f0d`.

Before production, tolerances were fixed: RMS rtol 1e-12 / atol 1e-18 m,
Strehl atol 1e-12, streamed mean atol 1e-15, unit flux atol 1e-12,
convolution atol 1e-15 and convolution-flux atol 1e-12. Independent delta,
weighted-shift, asymmetric/edge and direct-convolution checks verified binary
origin, axes, padding, crop loss and no hidden renormalization. All 16 numeric
observations were independently reproduced from retained mean PSFs.

## Distribution and research evidence

The dataset contains 167 manifest members totaling 11,532,922 B. First usable
view at final review was 1,332,997 B. The frontend uses content-addressed code,
relative JSON/member URLs, atomic case installation, at most two decoded cases
and readable refusal of incompatible cached builds. The browser performs no
AO propagation, random draws or new metric reductions from display images.

R1–R8 are reductions/extracts of retained records, notebooks and canonical
figures. Historical producers, failed tests, model boundaries, uncertainty
semantics and unknown fields remain explicit. The public evidence includes
27 byte-identical downloads and two source-bound notebook extracts. Source
links point at scientific source revisions, independently of the publication
revision. The full source inventory is in `research/results.json`.

## Resource history and preservation

The retained ledger totals 27 launches, 153.4099182104692 s and 177,694,247 B
before publication. Pilot, production, controls and subsequent derived exports
are all counted. Historical repair processing includes recorded warning-pressure
refusals and a repair-specific override; critical-pressure stops, budgets,
thread limits, timeout and cumulative accounting remained enforced. That
exception ended with the repair cycle and grants no permission for release
or future work to bypass the normal guard.

No runtime, profile, accepted baseline, historical evidence or original
scientific figure was changed for this release. The original and candidate
workspaces, local specifications, ignored raw evidence and full review archive
remain retained. Publication does not regenerate successful trajectories.
