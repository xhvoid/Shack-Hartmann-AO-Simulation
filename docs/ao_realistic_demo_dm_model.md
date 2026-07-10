<!-- Synthetic-DM note for actuator masks, influence functions, stroke clipping, actuator faults, and OPD-to-phase synthesis. -->

# DM Model Notes

The synthetic DM layer adds `src/dm_model.py`, a synthetic deformable-mirror layer with commands in `nm_OPD_equivalent`. The model creates a square actuator grid inside the pupil, supports `gaussian`, `compact_gaussian`, and `pyramid_like` influence functions, and records actuator metadata for later cached response matrices.

Validation summary:

```text
The piston-removed zero-command DM phase is zero and the stroke limit is enforced.
```

Current synthetic preset:

```text
data/synthetic_presets/dm_2m_fast_gaussian.json
```

This preset is `synthetic_literature_inspired`; it is not measured DM calibration data.
