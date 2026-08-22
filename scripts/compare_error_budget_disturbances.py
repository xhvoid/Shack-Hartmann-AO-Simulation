#!/usr/bin/env python3
"""Print the 2 m error budget twice: proxy disturbance, then real atmosphere.

The packaged ``fast`` error budget is built on a disturbance synthesized from
the deformable mirror itself, so it contains no fitting error and reports a
nearly perfect system.  This script runs the same eight scenarios against a
calibrated von Karman screen with a two-frame command latency, and prints both
tables side by side so the difference is visible rather than asserted.

Run:
    python scripts/compare_error_budget_disturbances.py
"""

from __future__ import annotations

import argparse

from shwfs_ao.experiments.atmospheric_disturbance import (
    physical_error_budget_scenarios,
)
from shwfs_ao.experiments.error_budget import (
    default_error_budget_scenarios,
    default_jhk_bandpasses,
    run_error_budget_scenarios,
)
from shwfs_ao.legacy.dm_model import DMConfig, build_dm_model
from shwfs_ao.legacy.interaction_matrix import (
    PokeMatrixConfig,
    build_detector_dm_poke_matrix,
)
from shwfs_ao.legacy.synthetic_instrument_data import (
    DetectorConfig,
    ShwfsGeometryConfig,
    build_detector_shwfs_calibration,
    make_pupil_grid_and_mask,
)


SOURCE_CLASS = "synthetic_literature_inspired"
NOTE = "Physical-versus-proxy error-budget demonstration."


def build_instrument():
    """Assemble the shipped fast 2 m detector-level instrument."""

    geometry = ShwfsGeometryConfig(
        telescope_diameter_m=2.0,
        n_pupil_pixels=52,
        n_lenslets=5,
        detector_window_px=18,
        pad_factor=3,
        source_note=NOTE,
    )
    x_m, y_m, mask, _ = make_pupil_grid_and_mask(geometry)
    dm_model = build_dm_model(
        x_m,
        y_m,
        mask,
        DMConfig(
            telescope_diameter_m=2.0,
            n_actuators_across=5,
            influence_model="gaussian",
            coupling_width_pitch=0.40,
            stroke_limit_nm=1000.0,
            source_class=SOURCE_CLASS,
            source_note=NOTE,
        ),
    )
    calibration = build_detector_shwfs_calibration(
        geometry,
        DetectorConfig(
            read_noise_e=1.0,
            qe=1.0,
            source_class=SOURCE_CLASS,
            source_note=NOTE,
        ),
    )
    poke = build_detector_dm_poke_matrix(
        calibration,
        dm_model,
        PokeMatrixConfig(
            calibration_amplitude_nm=10.0,
            target_kept_mode_fraction=1.0,
            source_class=SOURCE_CLASS,
            source_note=NOTE,
        ),
    )
    return calibration, dm_model, poke


def print_table(title: str, results) -> None:
    print(f"\n{title}")
    print(
        f"  {'scenario':26s} {'open nm':>9s} {'closed nm':>10s} "
        f"{'ratio':>7s} {'Strehl J':>9s} {'Strehl H':>9s} {'Strehl K':>9s}"
    )
    for row in results:
        print(
            f"  {row.scenario_name:26s} {row.open_rms_nm:9.1f} "
            f"{row.closed_rms_nm:10.1f} {row.closed_over_open_rms:7.3f} "
            f"{row.strehl_J:9.4f} {row.strehl_H:9.4f} {row.strehl_K:9.4f}"
        )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--n-steps",
        type=int,
        default=24,
        help="Loop frames per scenario (default: 24, enough for a quick look).",
    )
    args = parser.parse_args()

    calibration, dm_model, poke = build_instrument()
    bandpasses = default_jhk_bandpasses()

    proxy = run_error_budget_scenarios(
        calibration,
        dm_model,
        poke,
        default_error_budget_scenarios(n_steps=args.n_steps),
        bandpasses,
        telescope_diameter_m=2.0,
    )
    physical = run_error_budget_scenarios(
        calibration,
        dm_model,
        poke,
        physical_error_budget_scenarios(n_steps=args.n_steps),
        bandpasses,
        telescope_diameter_m=2.0,
    )

    print_table(
        "control_space_proxy — disturbance synthesized from the DM "
        "(no fitting error, zero latency)",
        proxy,
    )
    print_table(
        "atmospheric_screen — von Karman screen, r0-driven amplitude, "
        "two-frame latency",
        physical,
    )
    print(
        "\nThe gap is fitting error plus servo lag: a 5x5 actuator grid cannot "
        "correct\na von Karman screen on a 2 m pupil, and the proxy "
        "disturbance is built so that it can."
    )


if __name__ == "__main__":
    main()
