"""Guard that the committed parameter-source inventory matches current outputs.

The inventory Markdown is generated from the tracked public caches and result
CSV/JSON files. If a result table is regenerated (for example when the centroid-
validity change freezes faint scenarios) but the inventory is not, the two
deliverables drift apart. This test regenerates the inventory in-memory and
compares it to the committed Markdown so that drift fails CI instead of shipping.
"""

import importlib.util
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BUILDER = ROOT / "scripts" / "build_parameter_source_inventory_pdf.py"
INVENTORY_MD = ROOT / "docs" / "ao_realistic_demo_parameter_source_inventory.md"


def _load_builder():
    spec = importlib.util.spec_from_file_location("inventory_builder", BUILDER)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _strip_timestamp(text: str) -> str:
    return re.sub(r"Prepared: .*", "Prepared: <timestamp>", text)


def test_committed_inventory_matches_current_result_tables():
    builder = _load_builder()
    inventory = builder.build_inventory()
    regenerated = builder.markdown_inventory(inventory)
    committed = INVENTORY_MD.read_text(encoding="utf-8")

    assert regenerated.endswith("\n")
    assert not regenerated.endswith("\n\n"), "Generated Markdown must use exactly one terminal newline."
    assert _strip_timestamp(regenerated) == _strip_timestamp(committed), (
        "docs/ao_realistic_demo_parameter_source_inventory.md is out of sync with the "
        "generated result tables. Regenerate it with "
        "`python scripts/build_parameter_source_inventory_pdf.py`."
    )
