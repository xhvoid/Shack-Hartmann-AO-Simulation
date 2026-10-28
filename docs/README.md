<!-- Public technical-documentation index for the adaptive-optics simulation. -->

# Technical documentation

This directory documents the installed `shwfs_ao` framework. The
[repository README](../README.md) is the primary entry point for installation,
wheel-verified quick-start commands, scope, results, and limitations.

## Overview and reproducibility

- [Getting started](getting_started.md) — installation, notebook entry points and optional dependencies.
- [Current numerical verification](numerical_accuracy_fixes.md) — corrected atmospheric, PSF and notebook results.
- [TIPTOP sensitivity study](notebook12_tiptop_portfolio_notes.md) — method, convergence checks and recorded results.

- [Architecture](architecture.md) — package dependencies plus runtime,
  backend, calibration, and artifact-flow diagrams.
- [Backends and public contracts](backends.md) — native/HCIPy responsibilities,
  protocols, result fields, units, and sign conventions.
- [Validation](validation.md) — internal checks, regression governance,
  native/HCIPy tolerances, and explicit non-validation scope.
- [Provenance](provenance.md) — source taxonomy, canonical records, packaged
  public caches, and synthetic-model boundary.
- [Reproducibility](reproducibility.md) — named random domains, reset/replay,
  hashes, dependency evidence, and known limits.
- [Artifact schemas](artifact_schemas.md) — schema-v2 compatibility, additive
  schema 3, sidecars/manifests, upgrades, and baseline acceptance.
- [Migration](migration.md) — deprecated import/resource replacements,
  release clock, and serialized compatibility paths.
- [Parameter-source inventory (Markdown)](ao_realistic_demo_parameter_source_inventory.md) — tracked public caches, derived quantities, synthetic parameters, and result provenance.
- [Parameter-source inventory (PDF)](ao_realistic_demo_parameter_source_inventory.pdf) — formatted version of the source inventory.

## Canonical API contracts

- [AO-REF-007 interaction-matrix calibration](refactor/AO_REF_007_INTERACTION_MATRIX.md)
- [AO-REF-008 mask-aware reconstructors](refactor/AO_REF_008_RECONSTRUCTORS.md)
- [AO-REF-009 backend-independent control loop](refactor/AO_REF_009_CONTROL_LOOP.md)
- [AO-REF-010 science propagation and physical-grid metrics](refactor/AO_REF_010_SCIENCE.md)
- [AO-REF-011 shared SCAO construction and profiles](refactor/AO_REF_011_SCAO.md)
- [AO-REF-012 artifact and packaged-resource boundary](refactor/AO_REF_012_ARTIFACTS.md)
- [AO-REF-013 optional HCIPy dependency and conversion layer](refactor/AO_REF_013_HCIPY.md)
- [AO-REF-014 HCIPy atmosphere](refactor/AO_REF_014_HCIPY_ATMOSPHERE.md)
- [AO-REF-015 HCIPy DM](refactor/AO_REF_015_HCIPY_DM.md)
- [AO-REF-016 HCIPy Shack-Hartmann optics](refactor/AO_REF_016_HCIPY_SHWFS.md)
- [AO-REF-017 HCIPy science propagation](refactor/AO_REF_017_HCIPY_SCIENCE.md)

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

The component notes preserve detailed implementation history. Current
architecture is defined by the package-level pages above and current notebooks
under `notebooks/tutorials`, `notebooks/studies`, and
`notebooks/experimental`; archived numbered notebooks are migration evidence,
not the primary design description.
