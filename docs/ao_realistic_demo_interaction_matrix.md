<!-- Interaction-matrix note for detector-level DM pokes, singular spectrum, kept modes, TSVD cutoff, calibration amplitude, and provenance. -->

# Interaction Matrix Notes

The interaction-matrix layer adds `src/interaction_matrix.py`, which connects the detector-level SH-WFS calibration to the synthetic DM model. The matrix is constructed from central-difference DM pokes:

```text
command unit: nm_OPD_equivalent
matrix unit: detector_px / nm_OPD_equivalent
phase wavelength: calibration.geometry.wfs_wavelength_m
```

Validation summary:

```text
The poke-matrix shape is correct and the SVD singular values are finite and plotted.
```

The shared result object is `PokeMtxResult`. Its required fields are:

```text
poke_matrix
singular_values
kept_modes
rcond
source_class
```

Additional metadata records controlled actuator indices, valid lenslet rows, calibration amplitude, numerical rank, a condition proxy, and a `config_hash` derived from geometry, detector, DM, and calibration settings.

The selected TSVD `rcond` is chosen from a fresh interaction-matrix scan grid for the current detector-level matrix. It is not copied from notebook 09. The helper keeps a configurable fraction of the numerically nonzero singular modes and stores the grid summary in `PokeMtxResult.rcond_scan_summary`.

For the current fast demonstrator, the poke matrix is deliberately small and well conditioned. The SVD plot should be described as a compact detector-level DM/WFS response sanity check, not as a realistic high-order detector-level reconstructor-conditioning study. In this configuration all controlled modes remain well above the selected TSVD cutoff.

The command-line diagnostic is:

```bash
python3 examples/run_interaction_matrix_demo.py
```

It writes:

```text
figures/detector_level_SCAO/poke_matrix_singular_values.png
figures/detector_level_SCAO/poke_matrix_singular_values.csv
```

These outputs are synthetic calibration diagnostics, not measured observatory interaction matrices.
