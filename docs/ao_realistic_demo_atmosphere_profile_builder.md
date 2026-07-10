<!-- Atmosphere-builder note for seeing/r0 conversion, Cn2 layer normalization, and finite frozen-flow phase cubes. -->

# Atmosphere Profile Builder Notes

The atmosphere builder adds `src/atmosphere_profiles.py`, which consumes the literature-profile object and produces an `AtmosphereConfig` shared across the simulation modules:

```text
layers: height_m, cn2_weight, wind_ms, wind_dir_deg
r0_500_m
seeing_arcsec
tau0_s
theta0_rad
seed
```

The phase cube generator returns phase in radians at an explicit `wavelength_m`; it does not return OPD or science-wavelength Strehl quantities. Layer Cn2 weights are normalized to sum to one, layer RMS values scale as `sqrt(cn2_weight)`, and each simulated frame is checked against the r0-derived expected phase RMS.

Validation summary:

```text
The phase RMS matches the r0-derived expectation within 10%.
```
