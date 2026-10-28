# Release Checklist

The source metadata currently use version `0.1.0`, but repository optimization
does not itself create a tag or publish a release. Treat a version as released
only after a maintainer intentionally completes the checklist below.

## Prepare

1. Choose the release version and summarize user-visible changes.
2. Set the same version in `pyproject.toml` and `CITATION.cff`. Add
   `date-released` to `CITATION.cff` only for the commit that will actually be
   tagged and published.
3. Review `LICENSE`, `DATA_LICENSES.md`, package URLs, author metadata, and all
   third-party data provenance. Do not describe unresolved redistribution
   rights as granted.
4. Refresh `constraints/py310.txt` and `constraints/py314.txt` in their matching
   Python environments, review the dependency diff, and keep package runtime
   requirements as compatible ranges rather than exact pins.

## Verify

Run from a clean checkout with network-independent simulation inputs:

```bash
python -m pip install -c constraints/py314.txt -e ".[test]"
python -m pytest -q tests/test_wheel_install.py
python -m pytest -q tests/test_integration_fast.py
python -m pytest -q
python -m pip check
python -m pip wheel --no-deps --wheel-dir /tmp/ao-wheelhouse .
git diff --check
git diff --exit-code -- src/shwfs_ao/resources/reference_metrics \
  src/shwfs_ao/resources/resource_manifest.json figures/detector_level_SCAO
git status --short
```

The CI matrix must also pass on Python 3.10 and 3.14. Inspect the wheel from a
fresh, non-editable installation and confirm that reference metrics, SVO
curves, presets, `LICENSE`, and `DATA_LICENSES.md` are present and readable.

## Publish intentionally

After verification, commit the synchronized metadata, create an annotated
`vX.Y.Z` tag on that exact commit, push it, and create matching release notes.
Those operations are explicit maintainer actions and are intentionally not
performed by tests or repository-optimization tickets.

## AO-REF-021 deprecation clock

`src/shwfs_ao/resources/deprecation_clock.json` records the deprecation
release/tag, publication UTC date, planned removal release, and earliest
removal UTC date for the compatibility shims and the `ao_simulation_data`
alias. It is committed in the planned/unpublished state.

- When the deprecation release (the one that first ships the import warnings,
  currently `0.2.0`) is actually tagged, in that same commit set the clock's
  `publication_status` to `published`, set `publication_utc_date` to the tag's
  UTC date, and update `earliest_removal_utc_date` to the later of that date
  plus `minimum_window_days` and any published subsequent-minor date.
- When the required subsequent minor release (`0.3.0`) is tagged, set its
  `subsequent_minor_release.publication_status`/`publication_utc_date` and
  re-derive `earliest_removal_utc_date`.
- `shwfs_ao._deprecation.earliest_removal_utc_date` and
  `removal_boundaries_satisfied` recompute these boundaries;
  `tests/compat/test_phase_a_isolation.py` fails if the recorded date drifts
  from the recomputed one. Regenerate `resource_manifest.json` after any clock
  edit (the manifest hashes the packaged resource). Phase B (deletion) may open
  only once `removal_boundaries_satisfied` holds. See
  [migration.md](migration.md).
