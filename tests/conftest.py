"""Repository-wide pytest policy for resource-gated tests.

Tests marked ``elt_scale`` build or calibrate systems at or near the full
84x84 / 85x85 ESO-derived SCAO scale, run medium-scale benchmark tiers, or
build a sensor at a published profile's full scale beyond the desktop-safe
default (the 384-pixel HCIPy lenslet-axis check).
They never run by default: a broad ``pytest`` invocation, a ``-m elt_scale``
marker expression, or a ``-m "not slow"`` selection all skip them unless the
caller also passes the explicit ``--enable-elt-scale`` option.  The option is
the human authorization required by section 2.3 of
``docs/refactor/eso_scao_development_plan.md``; the marker alone is only a
label.  Collection and fixtures of those tests must not allocate the large
system, so the guard below runs before any fixture is set up.
"""

from __future__ import annotations

import pytest


# ``pytester`` lets the guard below be tested on a throwaway test file.
pytest_plugins = ("pytester",)

ELT_SCALE_OPTION = "--enable-elt-scale"
ELT_SCALE_SKIP_REASON = (
    "elt_scale test refused: medium/full-scale runs need the explicit "
    f"{ELT_SCALE_OPTION} option after a human has reviewed the run's "
    "configuration, estimated peak memory, thread count, timeout, and output "
    "path (docs/refactor/eso_scao_development_plan.md section 2.3)."
)


def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addoption(
        ELT_SCALE_OPTION,
        action="store_true",
        default=False,
        help=(
            "explicitly authorize tests marked elt_scale (medium/full-scale "
            "ESO SCAO construction or calibration); never implied by -m."
        ),
    )


def pytest_runtest_setup(item: pytest.Item) -> None:
    if item.get_closest_marker("elt_scale") is None:
        return
    if not item.config.getoption(ELT_SCALE_OPTION):
        pytest.skip(ELT_SCALE_SKIP_REASON)
