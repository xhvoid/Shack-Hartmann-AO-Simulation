<!-- Canonical synthetic-DM ownership, command units, faults, and backend boundary. -->

# DM Model Notes

The synthetic DM has one repository-level policy owner in
`shwfs_ao.dm.DeformableMirror`. The transparent NumPy spatial implementation
lives in `shwfs_ao.backends.native.dm`. The installed top-level `dm_model`
module remains a compatibility facade for the historical API; it is not a
second physical implementation.

Canonical commands are full-layout `DmCommandVector` values in
`m_opd_equivalent`. They are correction optical-path-difference amplitudes,
not actuator volts or reflective surface displacement. Positive commands
produce positive correction OPD and the loop convention is

```python
residual_opd_m = atmosphere_opd_m - dm_correction_opd_m
```

The repository wrapper owns stable physical actuator IDs/order, symmetric
stroke clipping, dead/stuck rules, requested/applied diagnostics, actuator
metadata, configuration hashing, and provenance. The fault order is clip,
dead-to-zero, then stuck-to-its-clipped configured value; saturation describes
requested commands beyond stroke before fault replacement. Historical fields
such as `stroke_limit_nm` and `stuck_command_nm` remain
`nm_OPD_equivalent` for compatibility and are converted once to metres.

The native backend owns square-grid placement, `gaussian`,
`compact_gaussian`, and `pyramid_like` influence sampling, plus the memoryless
linear command-to-OPD sum. Its output is a finite raw OPD array in metres. It
does not remove piston and contains no gain, leak, latency, command queue, or
fault policy. Compatibility adapters alone restore historical piston removal
and NaN-outside-pupil representations where requested.

A future reflective backend must convert the requested OPD-equivalent command
to half as much physical mirror-surface displacement. Reflection creates OPD
equal to twice the surface displacement, so that conversion happens exactly
once: a 10 nm OPD-equivalent command means 5 nm of surface motion and 10 nm of
returned correction OPD.

Validation summary:

```text
Zero commands yield zero raw correction OPD; positive commands retain their
positive correction sign; influence peaks, linearity, stroke/fault behavior,
stable ordering, the reflective factor of two, and static fitting trends are
covered by focused tests.
```

Current synthetic preset:

```text
data/synthetic_presets/dm_2m_fast_gaussian.json
```

This preset is `synthetic_literature_inspired`; it is not measured DM calibration data.
