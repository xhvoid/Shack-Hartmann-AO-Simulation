# Validation, regression, and limitations

The repository validates interfaces, numerical invariants, physical trends,
seeded regression behavior, and agreement between two independently
implemented optical backends. It has **not** been validated against observatory
telemetry or a calibrated instrument. “Pass” means the declared model satisfies
its own governed contract; it does not mean the model predicts on-sky
performance.

## Validation ladder

| Level | What is checked | Interpretation |
| --- | --- | --- |
| contract/unit | shapes, immutable IDs, registered units, finite values, hashes, normalization and sign | catches interface and convention errors exactly |
| component physics | analytic conversions, piston/RMS behavior, diffraction scale, detector trends, DM linearity/fitting, controller frame semantics | sanity checks for one implementation |
| seeded native regression | frozen fast-integration metrics and semantic CSV rows | guards unintended movement during structural changes |
| native-versus-HCIPy | exact identity plus tight numerical and physical-tolerance metrics | cross-checks independent optical implementations without demanding pixel equality |
| scenario/provenance | finite outputs, source classification, public-cache use, runtime reporting | checks experiment bookkeeping, not absolute AO accuracy |

## Internal physical and trend checks

The canonical helpers in `shwfs_ao.validation.physical`, focused component
tests, and the retained compatibility validation adapter cover:

| Check | Required behavior |
| --- | --- |
| OPD/phase conversion | `phase = 2*pi*OPD/lambda`, explicit positive wavelength, round-trip within numerical precision |
| piston and masked RMS | piston removed only inside a non-empty pupil; interior NaN/Inf fails |
| Maréchal consistency | for the small-aberration regime, measured peak Strehl follows `exp[-(2*pi*sigma_opd/lambda)^2]` and falls as RMS grows |
| diffraction scale | ideal circular-pupil core/first-minimum scale is consistent with `lambda/D` on physical angular axes |
| detector statistics | photon noise and centroid uncertainty improve with photon count; read noise degrades quality; full-well/bad-pixel/PRNU policies are explicit |
| centroid validity | flux, SNR, uncertainty, and window-clipping gates trigger independently; faint noise is not reported as a valid centroid |
| SH-WFS sign/order | physical subaperture IDs and `S:x`, `S:y` rows are stable; positive x/y OPD tilt moves columns/rows positively |
| DM sign/factor | positive command makes positive correction OPD; the reflective factor of two occurs exactly once |
| fitting trend | a denser matched actuator basis does not worsen the declared static fitting case |
| reconstruction masks | usable rows are calibration-valid ∩ runtime-valid ∩ finite; unusable full-layout values remain NaN, never zero-filled |
| latency/controller | delay `d` makes a frame-`k` increment available at frame `k+d`; `None` advances the queue and leak; applied commands are acknowledged |
| science grids | PSF flux sums to one, angular axes are increasing and dimensionally consistent, EE/FWHM use physical coordinates |
| replay | resetting seed/realization/component state replays the declared run within the frozen environment |

The fast integration's six compatibility validation rows are Maréchal
consistency, diffraction scale, photon-count/centroid trend, latency residual
trend, DM fitting trend, and scenario reproducibility. Read-noise centroid
validity is tested separately; it is not one of those six rows.

### Faint or unusable measurements

An all-invalid detector frame produces no reconstruction. Canonically the
reconstructor returns `None`; the controller enqueues a zero increment,
advances its latency queue, may release an older increment, and applies
configured leak. It does not reinterpret invalid rows as zeros and does not
freeze simulation time. In a run that starts and remains all-invalid with no
queued command, the applied command naturally remains zero and the residual
tracks open loop.

Low valid-centroid fraction is therefore a diagnostic, not automatically a
provenance failure. A deliberately faint scenario can pass “inputs present and
outputs finite” checks while demonstrating that the loop did not obtain enough
usable measurements.

## Seeded native regression

The schema-v2 fast baseline freezes:

- open- and closed-loop OPD RMS;
- H-band Strehl;
- valid-centroid fraction;
- kept TSVD modes;
- scenario names/count/order and validation names/count/order;
- configuration/source fields and declared tolerances; and
- an informational, non-portable runtime reference.

Structural changes compare these values under the existing metric-specific
tolerances and retain focused exact/near-exact array tests for units, ordering,
sign, and seeded component outputs. Runtime is not a correctness gate. A green
test does not authorize rewriting the accepted resource.

Before numerical values are compared, configuration, component, row-layout,
actuator-layout, resource, and constraint hashes establish that the same
experiment is being evaluated. Schema-v2 remains readable; schema 3 adds
structured provenance/reproducibility and authority. See
[Artifact schemas](artifact_schemas.md).

## Two disturbance sources, two baseline sets

The seeded fast baseline above records the **control-space proxy**: a
disturbance synthesized by driving the deformable mirror and reading back its
own surface. It lies entirely inside the mirror's controllable span, so a
budget built on it contains *no fitting error at all* — the DM reproduces the
input to machine precision (measured residual ~1e-13 nm). There is no `r0` and
no outer scale on that path; the amplitude is the free parameter
`phase_amplitude_nm`.

That makes it a legitimate instrument for isolating temporal, noise, stroke,
misregistration, and NCPA terms *from* fitting error. It does not make it an
atmosphere, and a Strehl read off it is not an AO performance prediction.

The **physical workflow** (`shwfs_ao.experiments.physical_integration`) runs
the same instrument, the same validation row set, and the same artifact
contract against a calibrated von Kármán screen with a two-frame command
latency. Its disturbance amplitude follows `r0` and the outer scale, and it
carries real fitting error, real servo lag, and real aliasing.

| | proxy (`fast_*`) | physical (`physical_*`) |
| --- | --- | --- |
| disturbance | DM surface | von Kármán screen, `subharmonic_von_karman_v2` |
| amplitude set by | `phase_amplitude_nm` | `r0_m`, `outer_scale_m` |
| fitting error | none, by construction | present (~43 % of the screen at 5×5 actuators) |
| latency | 0 frames | 2 frames |
| `workflow` label | `fast_integration` | `physical_integration` |

Both baseline sets are packaged and governed the same way, by separate tools
so that neither can move the other:

```
scripts/update_fast_regression_baselines.py       # fast_*      (frozen engine)
scripts/update_physical_regression_baselines.py   # physical_*  (atmosphere)
```

Each tool separates candidate generation from acceptance, refuses to write
into the packaged resource directory during generation, refuses to accept
while pytest is running, requires a written reason and a review reference, and
records the accepted file hashes. The physical tool additionally refuses any
candidate whose `workflow` label is not `physical_integration`, so a proxy
artifact can never be accepted as a physical baseline.

The physical regression tests that rerun the experiment carry the `slow`
marker and run in the scheduled lane. The reason is cost and it is not the
atmosphere's: `summarize_scenario` evaluates PSF metrics once per frame, per
band, per wavelength sample — 5784 evaluations and 23136 array sorts per
scenario at the packaged 24-frame length — so a scenario costs about 75 s
whichever disturbance drives it (measured: 74.8 s physical, 72.0 s proxy).
Generating the phase screen itself costs 0.1 s. Tests that only read the
packaged artifacts stay in the fast lane.

## Native-versus-HCIPy suite

`shwfs_ao.validation.cross_backend.run_cross_backend_report()` and the accepted
version-1 comparison baseline cover thirteen comparison groups:

1. pupil-mask conversion and throughput;
2. Zernike RMS/alignment and relative sign;
3. atmosphere RMS and structure-function statistics;
4. pure tip/tilt SH-WFS sign, cross-axis leakage, and gain;
5. lenslet spot EE50 width and centroid displacement;
6. Gaussian DM actuator identity and single-influence agreement;
7. static DM fitting residual;
8. interaction-matrix shape, row/coordinate IDs, and rank;
9. normalized singular-spectrum shape;
10. PSF unit-flux normalization;
11. Strehl ratio;
12. short closed-loop correction/residual trend; and
13. runtime and peak traced memory.

This inventory is enforced, not aspirational: the document validator in
`shwfs_ao.validation.regression` rejects any report or baseline whose
comparison list does not cover exactly these thirteen kinds in this order,
and rejects degenerate gating criteria (non-finite expectations, negative
absolute tolerances, inverted ranges, non-finite recorded baseline values).
A regenerated baseline therefore cannot silently drop a comparison or widen
a tolerance into an always-passing gate.

The suite uses the same stored/configured OPD and command fixtures for
pointwise optical comparisons. Independently seeded atmospheric screens are
compared across a declared realization count using statistical RMS and
structure-function estimators; equal root seeds across libraries are not a
claim of equal turbulence samples.

### Comparison levels

| Level | Examples | Gating rule |
| --- | --- | --- |
| `exact` | shape, IDs/order, rank in the matched fixture, unit/convention strings, deterministic metadata | equality |
| `tight_numerical` | mask round trip, matched Gaussian influence, unit-flux error, simple sign/cross-axis values | baseline-centered absolute tolerance with units |
| `physical_tolerance` | atmosphere statistics, spot width/gain, spectrum shape, Strehl, closed-loop residual | documented range or absolute tolerance with scientific rationale |
| `informational` | runtime and memory | reported, never gates ordinary correctness CI |

The evaluator first requires the exact comparison-config hash and every
component/shared-fixture hash. If an input hash differs, numerical tolerances do
not apply. Each metric record names its value, units, comparison level,
criterion, and rationale. A failure reports observed/expected values, tolerance
and units, plus the compared hashes.

Discrepancies are attributed to declared causes such as focal/window sampling,
normalization, interpolation/resampling, finite-window lenslet crosstalk, or
influence conventions. Passing the suite means both backends behave consistently
within those scoped checks; it is not a claim of complete equivalence.

## Baseline governance

Tests, examples, and notebooks only load accepted baselines. Updating one is a
two-stage maintainer operation:

1. generate into an explicit, non-packaged candidate directory;
2. inspect both machine-readable and human-readable old/new diffs;
3. explain any physical/numerical cause and all affected metrics;
4. accept the unchanged reviewed candidate with a non-empty reason and
   review/issue/PR reference.

The reviewed machine-readable diff is content-complete: it hashes the exact
candidate and current-baseline bytes and lists every structural change —
tolerances, criteria, rationale, and provenance included, not just metric
values. Acceptance recomputes that diff and refuses when anything changed
after review, so step 4's "unchanged" is enforced byte-for-byte rather than
assumed. Acceptance reasons and review references are persisted: embedded in
the cross-backend baseline, and written to a dedicated acceptance record for
the fast baselines.

The cross-backend accepted record additionally carries generator identity,
source commit, acceptance timestamp, backend/dependency environment, metric
rationales, and shared input hashes. Ordinary tests, notebook execution, or
the comparison example cannot invoke acceptance. CI hashes accepted resources
before and after commands and rejects both tracked mutation and unexpected
files. Full commands and schema authority rules are in
[Artifact schemas](artifact_schemas.md).

## How validation runs

The native source-development lanes run the full non-HCIPy, non-slow suite on
the checked Python 3.10 and 3.14 constraints. Non-editable-wheel lanes repeat
portable scientific tests outside the checkout with `PYTHONPATH` cleared and
exercise packaged resources without `.git`. The constrained Python 3.11 HCIPy
lane runs HCIPy component and cross-backend tests and refuses a zero-test
selection. Fast notebooks run offline from the installed wheel in a fresh
temporary working directory.

The README's executable native and HCIPy command blocks are separately parsed
and run from these wheel-smoke bundles; this prevents documentation commands
from drifting into source-checkout-only examples.

## Explicit limitations

These limitations are part of the validation claim, not footnotes:

- This is **not an observatory digital twin**.
- It is **not calibrated to a specific ESO instrument** and does not reproduce
  real AO telemetry or an operational real-time controller.
- DM calibration and influence functions are synthetic; no measured DM
  interaction calibration is claimed.
- Detector parameters, pixel effects, centroid thresholds, and validity
  assumptions are synthetic/internal rather than measured instrument data.
- The atmosphere is a limited single-line-of-sight frozen-flow/von Kármán
  model; layer altitude does not provide a full propagation, scintillation, or
  tomography model.
- The PWFS branch is experimental and is not a validated PWFS SCAO backend.
- There is no ELT laser-guide-star (LGS) tomography, cone effect, multi-guide-
  star reconstructor, sodium-layer model, or sky-coverage prediction.
- HCIPy usage or native-versus-HCIPy agreement alone does **not** validate
  observatory performance.

Public ESO/SVO/catalog caches condition selected synthetic inputs. They do not
remove any limitation above; see [Provenance](provenance.md).
