# Experimental service: version and validation scope

Updated 2 November 2026.

This branch contains the optional 2 m computation service. Its companion
interface is on `feature/dynamic-explorer`; the published static site is
maintained separately on `website`. [PR #8](https://github.com/xhvoid/Shack-Hartmann-AO-Simulation/pull/8) was closed without
merging. The branch is retained for development, not as a released service.

## Component repairs are not integrated here

The [component verification summary](https://github.com/xhvoid/Shack-Hartmann-AO-Simulation/blob/c42fe87a88f8f2dc97cedfacec791f5624950a3a/docs/verification-summary.md)
describes repairs on `main`. This service still has the earlier versions of
the following seven modules:

- `src/shwfs_ao/dm/config.py`
- `src/shwfs_ao/core/geometry.py`
- `src/shwfs_ao/wfs/shack_hartmann/geometry.py`
- `src/shwfs_ao/wfs/shack_hartmann/compact_geometry.py`
- `src/shwfs_ao/detector/physical_config.py`
- `src/shwfs_ao/detector/processing.py`
- `src/shwfs_ao/calibration/reconstructors.py`

These include boundary handling and dense reconstruction precision. Their
effect depends on the configuration; a difference in source does not by
itself establish that a saved trajectory is wrong. Conversely, the later
checks on `main` cannot be claimed for this service.

## What the saved checks establish

[Validation](VALIDATION.md) and the [technical review](ACCEPTANCE.md) describe
the October producers identified in those records. They cover a bounded
2 m example, replay and software behaviour. They do not establish ensemble
statistics, hardware accuracy, or validation of a newly combined version.
Independent calculations are identified by their method, such as direct
DFT checks. A separate code review is not external scientific peer review.

The 2 November changes clarify documentation only. No service code was
upgraded and no trajectory was rerun. Integrating the component repairs would
require a separate source and compatibility review before new use.
