# Off-axis targets and zenith angle

The wavefront sensor follows one natural guide star. For each science target the native loop samples the same moving layers at the target's angle, subtracts the mirror shape in place during that measurement, and adds the resulting image to the exposure. All targets share the guide-star commands. Each image stays on a grid centred on the target's nominal position, so image motion during the exposure broadens the core.

## Run the 2.2 m example

```bash
python examples/run_off_axis_science_demo.py --output outputs/off_axis_science/22m
```

This uses the second version of the 2.2 m profile, realization 0 and a wavelength of 1.65 µm. It averages frames 150–1499 of a 750 Hz loop at 0, 5, 10 and 20 arcsec from the guide star. The four interpolated long-exposure Strehl values were 0.448, 0.436, 0.398 and 0.338 on macOS and 0.444, 0.433, 0.396 and 0.337 on Linux. The two runs first diverged at the first mirror update. [Recorded measurements and platform comparison](https://github.com/xhvoid/Shack-Hartmann-AO-Simulation/blob/7aca875e5e34265c3f9ead97ae99da55663bcce7/docs/scao_off_axis_science.md#reading-the-figures)

The example writes the two figures, the Strehl table, the exposure settings and the underlying PSFs and guide-star history. For a short run with two directions, use the smaller 2 m model.

```bash
python examples/run_off_axis_science_demo.py --profile eso_turbulence_2m_detector --version 1 --offsets "0,0;10,0" --burn-in 30 --n-steps 60 --block-frames 10 --output outputs/off_axis_science/2m
```

## Pointing away from zenith

The zenith angle sets the line of sight of the whole telescope. The science offset sets the angular separation of a target from the guide star. At zenith angle `z`, the native layered atmosphere uses airmass `X = 1 / cos(z)`. The Fried length along the line of sight is the zenith value times `X^(-3/5)`. A layer at vertical height `h` is sampled at a distance `h * X`, so a small target offset of `theta` radians shifts its footprint by `h * X * theta`. Winds are specified in the layer plane. This thin-layer calculation covers angles from 0 up to, but excluding, 90 degrees and omits differential refraction.

```python
from dataclasses import replace
from shwfs_ao.experiments import run_off_axis_science
from shwfs_ao.io.configs import load_system_profile

config = load_system_profile("eso_scao_smoke_5m_software", 3)
tilted = replace(config, record_schema_version=9,
                 atmosphere=replace(config.atmosphere, zenith_angle_deg=30.0))
run = run_off_axis_science(tilted, offsets_arcsec=[(0, 0), (10, 0)],
                           wavelengths_m=(2.2e-6,), burn_in_frames=8)
for row in run.science.table_rows():
    print(row["radial_arcsec"], row["long_exposure_interpolated_peak_strehl"])
```
