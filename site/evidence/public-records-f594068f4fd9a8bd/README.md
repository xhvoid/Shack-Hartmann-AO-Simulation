# Public reading copies

These two JSON files are edited copies, not the original evidence files.
Only `/argv/0` in the 42 m record, and `/source_identity/branch` and
`/package_checks/package_file` in the noise-law record, have been shortened or
replaced. Each copy also adds a `_public_copy` block explaining that change.
All scientific values and the remaining original provenance fields are
unchanged.

`sources.json` records the original SHA-256, size and immutable source link.
The unedited records are no longer served with the site; they remain in Git
history at that link. Use those originals when checking an original producer
hash. The manifest here binds the new copies to their own hashes; it does not
reuse the original hashes. The directory is named after the first 16
hexadecimal digits of the SHA-256 of the manifest's `files` object, serialized
as compact JSON with sorted keys. This set replaces `public-records-46a80a01d47afca4`,
whose noise-law copy still carried an absolute package path.
