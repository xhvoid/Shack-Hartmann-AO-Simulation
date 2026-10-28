"""Run fast notebook-11 integration and write CSV, PNG, and reference JSON artifacts."""

from __future__ import annotations

import json
import os
from pathlib import Path

from ao_integration import IntegrationConfig, run_fast_integration
from shwfs_ao.io.artifacts import ArtifactConfig, write_integration_artifacts


ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    output_dir = Path(
        os.environ.get("AO_DEMO_OUTPUT_DIR", ROOT / "figures" / "detector_level_SCAO")
    )
    reference_metrics_path = Path(
        os.environ.get(
            "AO_DEMO_REFERENCE_METRICS",
            output_dir / "fast_reference_metrics.json",
        )
    )
    config = IntegrationConfig.from_mode(
        "fast",
        output_dir=output_dir,
        reference_metrics_path=reference_metrics_path,
    )
    result = run_fast_integration(config=config, write_outputs=False)
    written_files = write_integration_artifacts(
        result,
        ArtifactConfig(
            output_dir=output_dir,
            reference_metrics_path=reference_metrics_path,
            prefix="fast",
            schema_version=2,
        ),
    )

    print("Fast integration complete")
    print(json.dumps(result.reference_metrics, indent=2, sort_keys=True))
    for path in written_files:
        print(f"Wrote {path}")


if __name__ == "__main__":
    main()
