# Packaged data

These small files let examples run without an archive connection.

- `synthetic_presets/`: versioned detector, DM and system configurations.
- `literature_profiles/`: atmosphere profiles with their source classifications.
- `benchmarks/`: parameter ledgers, assumptions and camera presets.
- `public/`: cached filter curves, catalogue photometry and an ESO atmospheric-monitor snapshot.
- `samples/`: small synthetic fallback fixtures.
- `reference_metrics/`: saved numerical comparisons and regression values.
- `schemas/`: JSON schemas for configurations and saved records.

The atmosphere-monitor data condition synthetic scenarios; they are not AO
control telemetry. A published parameter source does not calibrate the full
instrument model. Versioned profiles and scientific source records retain
their original identifiers and content hashes.

`resource_manifest.json` lists the packaged files and their SHA-256 values.
The two deprecation records support older import paths. Raw downloads,
large simulation arrays and local working records are not installed.

See [data licences](../DATA_LICENSES.md) for attribution and source terms.
