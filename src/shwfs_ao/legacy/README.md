# Compatibility modules

These modules preserve older imports and example interfaces. The main APIs
live in `shwfs_ao.core`, `wfs`, `detector`, `calibration`, `control` and `science`.
Some older diagnostics still use the compatibility adapters, so this directory
remains part of the package.

The original nanometre-based helpers convert to the canonical metre-based
interfaces where appropriate. Do not interchange their units without checking
the function signature. `pwfs_forward` remains a separate experimental model.

Installed aliases and release constraints are recorded in
`../resources/deprecation_inventory.json` and `deprecation_clock.json`.
An alias is not removed merely because its planned deprecation date has passed.
