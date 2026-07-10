<!-- Public technical-documentation index for the adaptive-optics simulation. -->

# Technical documentation

This directory provides supporting technical notes for the detector-level adaptive-optics demonstrator. The [repository README](../README.md) is the primary entry point for installation, quick-start commands, scope, results, and limitations.

## Overview and reproducibility

- [Architecture](architecture.md) — module pipeline and simulation input boundary.
- [Validation](validation.md) — numerical checks and explicit non-validation scope.
- [Parameter-source inventory (Markdown)](ao_realistic_demo_parameter_source_inventory.md) — tracked public caches, derived quantities, synthetic parameters, and result provenance.
- [Parameter-source inventory (PDF)](ao_realistic_demo_parameter_source_inventory.pdf) — formatted version of the source inventory.

## Simulation components

- [Data-source interface](ao_realistic_demo_data_interface.md)
- [Atmosphere profiles](ao_realistic_demo_atmosphere_profile_builder.md)
- [Detector-level Shack-Hartmann WFS](ao_realistic_demo_detector_shwfs.md)
- [Synthetic deformable-mirror model](ao_realistic_demo_dm_model.md)
- [Interaction matrix](ao_realistic_demo_interaction_matrix.md)
- [Closed-loop controller](ao_realistic_demo_closed_loop_controller.md)
- [Science metrics](ao_realistic_demo_science_metrics.md)
- [Error-budget scenarios](ao_realistic_demo_error_budget.md)
- [Validation details](ao_realistic_demo_validation.md)
- [Fast integration run](ao_realistic_demo_integration.md)

These notes document assumptions, provenance classes, validation criteria, and the intended interpretation of notebook `11_full_detector_level_2m_scao_demo.ipynb` without presenting the demonstrator as a calibrated observatory system.
