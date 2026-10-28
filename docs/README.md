<!-- Public technical-documentation index for the adaptive-optics simulation. -->

# Technical documentation

This directory documents the installed `shwfs_ao` framework. The
[repository README](../README.md) is the primary entry point for installation,
wheel-verified quick-start commands, scope, results, and limitations.

## Start here

- [Technical reference](technical_reference.md) — the single current account of
  the implementation: scope, architecture, units, every model family and mode
  compared, compatible routes, assumptions, evidence, references and costs.
- [Roadmap](roadmap.md) — open scientific questions and engineering tasks, with
  the evidence each needs and its cost category.
- [Current simulation limitations](current_limitations.md) — living record of model boundaries, known issues, validation gaps and evidence needed to revisit them.

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
- [Research and validation methods](quality_methods/README.md) — focused guides for physical, numerical, code, literature, reproducibility and resource assessment.
- [Repository consolidation plan](refactor/repository_consolidation_plan.md) — implementation stages, preservation contracts, technical-reference requirements and resource estimates.
- [Independent consolidation review](refactor/repository_consolidation_review.md) — source, scientific-behavior, documentation, packaging and resource-cost acceptance review.
- [Cleanup execution record](refactor/CLEANUP_REFACTOR_STATUS.md) — what the consolidation changed and verified, ticket by ticket.
- [Parameter-source inventory (Markdown)](ao_realistic_demo_parameter_source_inventory.md) — tracked public caches, derived quantities, synthetic parameters, and result provenance.
- [Parameter-source inventory (PDF)](ao_realistic_demo_parameter_source_inventory.pdf) — formatted version of the source inventory.

## Component contracts (AO-REF ticket records)

These ticket records still state the component contracts; their status lines
and next steps are historical.


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

## Current model notes

- [Detector model](detector_model.md) — the compatibility and physical camera chains, units, camera presets, calibration products, the `detector_covariance_v2` uncertainty model and its supported domain ([execution record](refactor/DETECTOR_LEVEL_DEVELOPMENT_STATUS.md))
- [ESO E-ELT ten-layer turbulence model](eso_elt_turbulence_model.md) — source table, `native_layered` atmosphere, validation, the HCIPy `hcipy_layered` cross-check and the `eso_turbulence_2m_detector@1` profile
- [ESO-derived SCAO benchmark](eso_scao_benchmark.md) — 42 m, 84×84 SH / 85×85 DM benchmark tiers, source and assumption ledgers, the sparse high-order path, streamed long-exposure science, and the desktop resource policy ([execution record](refactor/ESO_SCAO_DEVELOPMENT_STATUS.md))

## Historical component notes

These notes were written for earlier stages of the repository and are kept
as implementation history.

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
architecture is defined by the [technical reference](technical_reference.md),
the package-level pages above and current notebooks under
`notebooks/tutorials`, `notebooks/studies`, and `notebooks/experimental`;
archived numbered notebooks are migration evidence, not the primary design
description. Earlier plans (`AO_REFACTOR_MASTER_TICKETS_REVISED.md`,
[`repository_optimization_plan.md`](repository_optimization_plan.md)) describe earlier repository
states; the [roadmap](roadmap.md) is the current plan.
