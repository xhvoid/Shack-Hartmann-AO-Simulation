"""Closed-loop check of the HCIPy lenslet-axis fix (AO-REF-016A).

Pairs ``high_order_10m_hcipy@3`` (published, cell-centred lenslet axes) with
the unpublished ``@4`` draft beside this file (block-centred axes) on the same
atmosphere realizations.  It reports the Noll Z2-Z4 content of the pre-update
residual OPD after burn-in, for each realization and paired by realization.
The two profiles differ only in ``wfs.lenslet_axis``, so the paired Z4
difference is the static focus that the cell-centred axes make the loop hold.

Scales:

``--scale analogue`` (default)
    A desktop-safe analogue at the fixture limits of
    ``docs/refactor/ESO_SCAO_DEVELOPMENT_PROMPT.md`` section 2.3: 80 pupil
    pixels, 10x10 SH, 11x11 DM, 32 frames, one science wavelength (2.2 um)
    and science pad 3.  It keeps the published lenslet pitch, spot sampling,
    8-pixel windows, sensing wavelength, r0, L0, wind, gain and latency.  It
    indicates the mechanism; it is not the confirmation.
``--scale published``
    The full published system: 384 pixels, 48x48 SH, 49x49 dense HCIPy DM,
    300 frames.  It needs about 6.5 GiB raw (13 GiB with the 2x margin), so it
    is refused unless ``--enable-large-host`` is given.  It must not run on the
    16 GiB authoring desktop.

Without ``--run`` the script prints the plan and memory estimate and builds
nothing.  Run every job through ``shwfs_ao.runtime.resource_guard``.
"""

from __future__ import annotations

import argparse
from dataclasses import replace
import json
import math
from pathlib import Path
import sys
import time


DRAFT_PATH = Path(__file__).resolve().with_name("high_order_10m_hcipy.v4.json")
ANALOGUE = {
    "pupil_pixels": 80,
    "lenslets_across": 10,
    "actuators_across": 11,
    "n_steps": 32,
    "burn_in": 12,
    "science_wavelengths_m": (2.2e-6,),
    "psf_pad_factor": 3,
}
PUBLISHED_BURN_IN = 100
# Raw peak estimates before the guard's 2x margin, in MiB.
ESTIMATE_MIB = {
    "analogue": 300,
    # 2401 x 384^2 x 8 B dense DM influence stack (2.83 GB) and one copy,
    # 1850 x 384^2 B lenslet masks and a validation copy, the interaction
    # matrix (2401 x 3700 x 8 B), PSF and propagation grids, interpreter.
    "published": 6600,
}


def _profiles(scale: str):
    from shwfs_ao.io.configs import (
        ScienceConfig,
        load_system_profile,
        system_config_from_mapping,
    )

    published = load_system_profile("high_order_10m_hcipy", 3)
    draft = system_config_from_mapping(json.loads(DRAFT_PATH.read_text(encoding="utf-8")))
    if scale == "published":
        return published, draft, PUBLISHED_BURN_IN

    pitch_m = published.telescope_diameter_m / published.lenslets_across

    def analogue(config):
        return replace(
            config,
            pupil_pixels=ANALOGUE["pupil_pixels"],
            lenslets_across=ANALOGUE["lenslets_across"],
            actuators_across=ANALOGUE["actuators_across"],
            telescope_diameter_m=pitch_m * ANALOGUE["lenslets_across"],
            science_wavelengths_m=ANALOGUE["science_wavelengths_m"],
            science=ScienceConfig(psf_pad_factor=ANALOGUE["psf_pad_factor"]),
            controller=replace(config.controller, n_steps=ANALOGUE["n_steps"]),
        )

    return analogue(published), analogue(draft), ANALOGUE["burn_in"]


class _NollRecorder:
    """Least-squares Noll Z2, Z3, Z4 (rms-normalized, metres) of each residual."""

    requested_fields = frozenset({"pre_update_residual_opd_m"})

    def __init__(self, geometry, np):
        self._np = np
        self._mask = np.asarray(geometry.pupil_mask, dtype=bool)
        radius_m = 0.5 * float(geometry.telescope_diameter_m)
        x = geometry.x_m[self._mask] / radius_m
        y = geometry.y_m[self._mask] / radius_m
        self._basis = np.column_stack(
            (
                np.ones_like(x),
                2.0 * x,
                2.0 * y,
                math.sqrt(3.0) * (2.0 * (x * x + y * y) - 1.0),
            )
        )
        self.coefficients_m: list[list[float]] = []

    def observe(self, event) -> None:
        values = event.pre_update_residual_opd_m[self._mask]
        coefficients, *_ = self._np.linalg.lstsq(self._basis, values, rcond=None)
        self.coefficients_m.append([float(value) for value in coefficients[1:]])


def _plan(args) -> dict[str, object]:
    return {
        "scale": args.scale,
        "realizations": list(range(args.first_realization, args.first_realization + args.realizations)),
        "profiles": ["high_order_10m_hcipy@3", f"high_order_10m_hcipy@4 draft ({DRAFT_PATH.name})"],
        "audited_peak_estimate_mib": ESTIMATE_MIB[args.scale],
        "required_with_2x_margin_mib": 2 * ESTIMATE_MIB[args.scale],
        "threads": 2,
        "output": str(args.out),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--scale", choices=("analogue", "published"), default="analogue")
    parser.add_argument("--realizations", type=int, default=4)
    parser.add_argument("--first-realization", type=int, default=0)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--run", action="store_true", help="build and run; without it only the plan is printed")
    parser.add_argument(
        "--enable-large-host",
        action="store_true",
        help="authorize --scale published after a human reviewed the plan on a suitable host",
    )
    args = parser.parse_args(argv)
    plan = _plan(args)
    print(json.dumps(plan, indent=1), flush=True)
    if not args.run:
        return 0
    if args.scale == "published" and not args.enable_large_host:
        print(
            "NOT_RUN_RESOURCE_POLICY: --scale published needs --enable-large-host "
            "on a host that fits the estimate above.",
            file=sys.stderr,
        )
        return 2

    import numpy as np

    from shwfs_ao.experiments.scao import build_scao_system, run_closed_loop

    published, draft, burn_in = _profiles(args.scale)
    result: dict[str, object] = {"plan": plan, "burn_in": burn_in, "runs": {}}
    for label, config in (("cell_center@3", published), ("block_center@4", draft)):
        started = time.perf_counter()
        system = build_scao_system(config)
        runs = []
        for realization in plan["realizations"]:
            recorder = _NollRecorder(system.wfs.geometry, np)
            history = run_closed_loop(
                config,
                system=system,
                realization_index=realization,
                observers=(recorder,),
            )
            held = np.asarray(recorder.coefficients_m)[burn_in:]
            runs.append(
                {
                    "realization_index": realization,
                    "mean_z2_z3_z4_nm": [float(value) * 1e9 for value in held.mean(axis=0)],
                    "std_z4_nm": float(held[:, 2].std() * 1e9),
                    "residual_rms_after_burn_in_nm": float(
                        np.mean(history.pre_update_residual_opd_rms_m[burn_in:]) * 1e9
                    ),
                }
            )
            print(label, runs[-1], flush=True)
        result["runs"][label] = {
            "lenslet_axis": config.wfs.lenslet_axis,
            "build_and_run_s": time.perf_counter() - started,
            "realizations": runs,
        }
    cell = result["runs"]["cell_center@3"]["realizations"]
    block = result["runs"]["block_center@4"]["realizations"]
    paired = [a["mean_z2_z3_z4_nm"][2] - b["mean_z2_z3_z4_nm"][2] for a, b in zip(cell, block)]
    result["paired_z4_cell_minus_block_nm"] = {
        "values": paired,
        "mean": float(np.mean(paired)),
        "standard_error": float(np.std(paired, ddof=1) / math.sqrt(len(paired))) if len(paired) > 1 else None,
    }
    print(json.dumps(result["paired_z4_cell_minus_block_nm"]), flush=True)
    args.out.write_text(json.dumps(result, indent=1) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
