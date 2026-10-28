# Reproducibility and evidence

Read the [shared contract](common_contract.md). Investigate the
requested claim or workflow; do not require an entire audit for one replay bug.

## Establish the actual experiment

Identify source and dirty inputs, dependency/native-library versions, imported
package, backend, dtype, threads, profile/schema versions, seeds, initialization,
burn-in, retained observables, and environment. Bind records to actual producers.
Distinguish an inspected historical result from a newly executed check.

## Check identity and randomness

- Map root seed to domain/key derivation, generator, draws, scopes, reset/replay,
  and object lifetimes. Check that changing one noise domain does not perturb
  unrelated domains when independence is part of the contract.
- Distinguish atmosphere realization, frame noise, pixel maps, calibration
  masters, and deterministic calibration. Verify intended pairing in comparisons.
- Separate exact same-environment replay, tolerance-based numerical agreement,
  distributional equivalence, and cross-platform reproducibility. Do not promise
  all four from one fixed-seed comparison.
- Inspect config canonicalization, nested hashes, resource/profile versions,
  public class/schema identities, calibration response/layout/row identities,
  cache attestation, and stale-state rejection where relevant.
- Exercise resume with compatible, incompatible, disjoint, overlapping, and
  no-new-work records using small stand-ins. Verify every retained run matches
  shared protocol/code identity, not merely the overlapping labels.
- Preserve observation definitions, finite-row masks, failure/refusal outcomes,
  frame counts, and accepted baseline authority. Similar summary statistics
  cannot justify merging incompatible runs.

## Audit evidence quality

Trace scientific, parameter, and instrument claims through source/assumption
ledgers to their actual authority. Separate public design values, derived
quantities, synthetic presets, and measured calibration. Record inaccessible
sources rather than upgrading their status.

Check test collection, node IDs, exit codes, skips/xfails, CI lanes, environment,
and producing source. A saved green total or another reviewer's summary is not
fresh evidence. Missing optional environments remain separate coverage rows.

Use small independent replay/protocol checks when execution is requested.
For comparison studies, verify matched inputs and uncertainty design before
interpreting a difference. Historical failure can be resolved in current code;
permit a clean review and retain the chronology.

## Deliver

Produce the requested English evidence note or audit appendix, using
[report fields](evidence_and_reporting.md). Explain what can be
reproduced, what identity is verified, what remains uncertain, and the next
bounded check. In a full audit include source-integrity and coverage records.
For the original repository, consult
[project integration](project_integration.md) as needed.
