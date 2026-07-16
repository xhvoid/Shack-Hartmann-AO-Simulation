# AO-REF-003 Core Provenance and Public-Data Boundary

AO-REF-003 makes provenance a shared domain record rather than a taxonomy
owned by a data loader. Canonical code imports `Provenance`, `SourceClass`, and
`ALLOWED_SOURCE_CLASSES` from `shwfs_ao.core.provenance`. Physical components
do not depend on the public-data I/O layer to validate source metadata.

## Canonical record

`Provenance` is an immutable record with these fields, in constructor order:

1. `source_class`;
2. `source_note`;
3. `source_id`;
4. `url`;
5. `access_time`;
6. `fallback_used`;
7. `references`.

The first six positions preserve the historical constructor. `note` is a
readable property alias for `source_note`; it is not a second stored value.
Validation retains the five-class taxonomy and requires a non-empty note.
Optional source identity, URL, access time, fallback state, and references stay
as separate structured fields.

## Versioned serialization

The canonical structured form is named `shwfs_ao.provenance` and currently has
schema version 2. Its ordered keys are:

```text
schema_name, schema_version, source_class, note, source_id, url,
access_time, fallback_used, references
```

`from_record()` accepts that schema explicitly and rejects a missing, malformed,
or unsupported schema name/version. `to_record()` emits JSON-compatible
references as a list and does not invent an alternate representation for an
unknown requested version.

The compatibility form remains flat and unversioned:

```text
source_class, source_note, source_id, url, access_time, fallback_used
```

`from_legacy_fields()` extracts only those provenance fields, so a surrounding
fixture's own `schema_version` is never mistaken for the provenance schema.
`to_legacy_fields()` preserves their historical names and order. Existing JSON
and CSV artifact owners continue to write these flat fields until their own
schemas are deliberately migrated; this ticket neither removes nor reorders a
column.

## Public-data I/O and compatibility

Public-data records and offline loaders now live in
`shwfs_ao.io.public_data`. Every loader constructs the core `Provenance` type.
The installed top-level `data_sources` import and
`shwfs_ao.legacy.data_sources` remain silent compatibility facades with their
AO-REF-000 names and loader signatures intact. Existing public caches, sample
fixtures, and literature profiles remain byte-identical package resources.

Configuration types that still expose positional `source_class` and
`source_note` fields provide a canonical `provenance` view where practical.
This keeps existing call sites and flat artifact output stable while removing
the physical modules' dependency on the I/O taxonomy.
