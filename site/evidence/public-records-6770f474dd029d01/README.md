# Public reading copies

These files are edited copies, not the original evidence files.

- `42m-noise-on-record.public.json`: only `/argv/0` is shortened.
- `detector-noise-law.public.json`: `/source_identity/branch` and
  `/package_checks/package_file` are replaced, and the 48 missing
  estimates that the original writes as the non-standard constant `NaN`
  (`msd_nm2` and `msd_se_nm2` of the attempt-1 runs, which have no separate
  mean-square-difference value) are written as `null`. The copy lists them.
- `research-results.public.json`: the research catalog bound by the 2 m
  dataset, with its two downloads of those records pointed at the copies here
  and every relative link rebased to this folder. The bound catalog itself is
  served unchanged; its two links to the originals no longer resolve.

Each copy adds a `_public_copy` block that states its edits. All scientific
values and the remaining original fields are unchanged. `sources.json`
records each original's SHA-256, size and immutable source link; the unedited
records remain in Git history there. Use those originals when checking an
original producer hash. The manifest binds these copies to their own hashes.
The directory is named after the first 16 hexadecimal digits of the SHA-256 of
the manifest's `files` object, serialized as compact JSON with sorted keys.
