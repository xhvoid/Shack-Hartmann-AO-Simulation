"""Run fast notebook-11 integration and write CSV, PNG, and reference JSON artifacts."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from ao_integration import IntegrationConfig, run_fast_integration


def main() -> None:
    config = IntegrationConfig.from_mode("fast")
    result = run_fast_integration(config=config, write_outputs=True)

    print("Fast integration complete")
    print(json.dumps(result.reference_metrics, indent=2, sort_keys=True))
    for path in result.written_files:
        print(f"Wrote {path.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
