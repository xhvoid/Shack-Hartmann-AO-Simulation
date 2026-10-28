# Provenance and physical-fidelity boundary

Provenance answers “where did this input or result assumption come from?” It
does not turn a synthetic model into an external validation. The taxonomy is a
core domain concept in `shwfs_ao.core.provenance`; public-data parsing stays in
`shwfs_ao.io.public_data`, so atmosphere, detector, DM, calibration, control,
and science modules do not depend on file loaders.

## Source classes

Every canonical `Provenance` has one of five source classes and a non-empty
note.

| `source_class` | Meaning | Typical repository use |
| --- | --- | --- |
| `direct_public_data` | a value or small cache read directly from a named public service | ESO ASM cache, SVO filter curve, catalog photometry subset |
| `literature_derived` | a value calculated from cited literature or a published relationship | a parameter derived explicitly from a paper or documented formula |
| `synthetic_literature_inspired` | a synthetic model whose scale/shape was informed by literature but is not a reproduced calibration | example atmosphere profile or Gaussian DM family |
| `synthetic_assumed` | an internal engineering assumption selected for the simulation | detector parameters, controller settings, synthetic interaction calibration |
| `package_reference` | a repository-owned fixture, schema, profile, or accepted regression reference | packaged presets, schema documents, accepted baseline resources |

Do not upgrade `synthetic_assumed` to `direct_public_data` merely because a
public quantity conditioned one upstream parameter. For example, an ESO ASM
seeing value may scale a synthetic phase sequence; the phase sequence is still
synthetic and must be described as “ESO-ASM-conditioned synthetic,” never as a
measured wavefront.

## Canonical provenance record

The in-memory `Provenance` fields are:

| Field | Contract |
| --- | --- |
| `source_class` | one of the five values above |
| `source_note` | non-empty human-readable explanation; `note` is a read-only alias |
| `source_id` | stable source/query/dataset identifier or `None` |
| `url` | source URL or `None` |
| `access_time` | recorded access timestamp text or `None` |
| `fallback_used` | whether the desired source was unavailable and a declared fallback was used |
| `references` | ordered tuple of additional references |

`Provenance.to_record(schema_version=2)` serializes the named structured
record. Every field is required, including nullable values:

```json
{
  "schema_name": "shwfs_ao.provenance",
  "schema_version": 2,
  "source_class": "synthetic_assumed",
  "note": "Synthetic detector assumptions for the fast profile.",
  "source_id": null,
  "url": null,
  "access_time": null,
  "fallback_used": false,
  "references": []
}
```

`from_record()` rejects an unknown schema name/version, missing fields, extra
fields, or invalid source class. There is no “best effort” interpretation of a
future provenance schema.

Historical artifacts use the flat keys `source_class`, `source_note`,
`source_id`, `url`, `access_time`, and `fallback_used`.
`from_legacy_fields()` intentionally ignores unrelated enclosing fields such
as an artifact's `schema_version`; `to_legacy_fields()` preserves the frozen
flat names and order. Structured `references` are not invented when a legacy
record has none.

## Packaged inputs

Canonical runtime resources live under `shwfs_ao.resources` and are opened
through `shwfs_ao.io.resources`/`importlib.resources`. They work from a
non-editable wheel without a repository root or `.git` directory.

| Resource family | Provenance boundary | Scientific use |
| --- | --- | --- |
| ESO Paranal ASM snapshots/time series | `direct_public_data` cache with URL/access metadata | condition seeing/r0/tau0-style scenario inputs; not a measured phase screen |
| SVO 2MASS J/H/Ks curves | `direct_public_data` | wavelength/transmission samples for scalar science-band summaries |
| Pan-STARRS and 2MASS rows | `direct_public_data` | photometric anchors for an engineering WFS photon estimate |
| literature atmosphere profile | `synthetic_literature_inspired` | ordered layer weights/winds for synthetic atmosphere studies |
| detector/DM/system presets | normally `synthetic_assumed` or `synthetic_literature_inspired` | explicit simulation configuration, not hardware calibration |
| reference metrics and schemas | `package_reference` | regression governance and serialization contracts |

The loaders convert supported source units into canonical fields before
constructing typed objects. Examples include wavelength in metres, time in
seconds, wind in metres/second, and seeing in arcseconds. Unit conversion and
provenance classification are independent: a correctly converted value can
still be only a synthetic assumption.

The generated `ao_simulation_data` resource tree is a deprecated installed
alias during the compatibility window. It is built from the canonical resource
manifest and is never edited as a second source. Historical logical names such
as `data/public/...` still resolve through `shwfs_ao.io.resources`.

## Flow into configurations and artifacts

1. `io.public_data` loads and validates a packaged cache or caller-owned file.
2. A typed input record carries canonical units plus `Provenance`.
3. An experiment may derive a scenario value and must record both the direct
   anchor and the synthetic transformation/assumption.
4. Config/component hashes cover scientific configuration and provenance, but
   generated timestamps do not participate in scientific hashes.
5. Schema-3 artifacts embed the structured provenance record. Compatibility
   schema-v2 tables retain the frozen flat source fields.
6. Artifact manifests and accepted baselines add reproducibility and human
   acceptance evidence; provenance alone is not baseline authority.

## Included data and redistribution

The software and documentation use the repository MIT license. Cached
third-party data retain their own source terms; the repository does not grant
new rights over them. See [DATA_LICENSES.md](../DATA_LICENSES.md) for the exact
files, official terms/acknowledgement links, and unresolved redistribution
questions. Retain source URLs, query information, access times, and embedded
provenance with redistributed caches or derived products.

## Interpretation limits

- Public caches are small offline anchors, not complete site-monitor archives.
- Catalog magnitudes are not WFS telemetry; photon counts are engineering
  estimates with explicit bandwidth/throughput assumptions.
- Seeing/r0 condition synthetic atmosphere strength; they do not supply a
  measured, time-resolved aberration cube.
- SVO bandpasses improve wavelength weighting but do not model a complete
  instrument throughput or detector response.
- Synthetic DM calibration and internal detector assumptions remain synthetic
  even when a scenario also contains direct public inputs.
- No provenance class makes the repository a calibrated ESO instrument model
  or an observatory digital twin.

Artifact embedding and upgrade rules are documented in
[Artifact schemas](artifact_schemas.md); deterministic seed provenance is in
[Reproducibility](reproducibility.md).
