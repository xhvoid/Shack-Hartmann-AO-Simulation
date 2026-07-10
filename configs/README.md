<!-- Config skeletons for the fast, portfolio, research, and 10 m reference AO demo presets, with units and source_class provenance tags. -->

# AO demo configuration presets

These YAML files define the starting configuration skeleton for the realistic 2 m SCAO demo sequence. They are intentionally still presets, not calibrated instrument files.

```text
ao_demo_2m_fast.yaml                  small CI-style smoke preset
ao_demo_2m_portfolio.yaml             default notebook-figure preset
ao_demo_2m_research.yaml              optional slower local-quality preset
ao_demo_10m_high_order_reference.yaml narrative reference for notebook 09
```

Allowed `source_class` values (see `docs/validation.md` for provenance):

```text
direct_public_data
literature_derived
synthetic_literature_inspired
synthetic_assumed
package_reference
```

When a value is not tied to a named public dataset, package reference, or cited paper, it remains `synthetic_assumed` until stronger provenance is available.
