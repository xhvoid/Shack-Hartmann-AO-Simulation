"""Packaged runtime data for the Shack-Hartmann AO simulation.

Access these files through :mod:`shwfs_ao.io.resources`.  Built distributions
also install a byte-identical copy of this package as the deprecated
``ao_simulation_data`` compatibility alias (see
``build_support/resource_alias.py``); importing the copy under that historical
name emits the AO-REF-021 DeprecationWarning below, while the canonical
``shwfs_ao.resources`` import stays silent.
"""

if __name__ == "ao_simulation_data":  # pragma: no cover - alias import path only
    import warnings as _warnings

    import shwfs_ao._deprecation as _deprecation

    _warnings.warn(
        _deprecation.resource_alias_deprecation_message(),
        DeprecationWarning,
        stacklevel=2,
    )
