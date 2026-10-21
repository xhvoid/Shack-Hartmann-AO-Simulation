"""Offline H5 bound for the 2 m paired noise study (S4 contract arm C2', ticket T1).

Builds the 2 m ``det_emccd_2m_synthetic@1`` systems at two guide-star
magnitudes (default m_AB 5 and 7) for one root seed, compares their dense
reconstructors and interaction matrices directly, and propagates one fixed
per-row slope covariance through both to the pupil.  The relative change of
the propagated pupil noise variance between the two reconstructors bounds
hypothesis H5 (a magnitude-dependent reconstructor through calibration at
the operating flux) without a new closed-loop arm.  Fixed inputs, no loop,
no governed run; seconds on the desktop.

Assumptions recorded in the output: the reconstructor is linear for a fixed,
fully valid row mask (``reconstructor_matrix`` probes it row by row); the
propagated variance is ``V(R) = sum_r sigma_r^2 w_r(R)`` with ``w_r`` the
piston-removed pupil mean square of the DM response to a unit slope in row
``r`` (independent rows, the block-diagonal x/y covariance's off-diagonal
terms dropped); the fixed covariance is the flat-wavefront model of the
reference magnitude unless ``--identity-covariance`` is given.  The result
is a bound on H5 for this profile and seed, not a closure of LIM-18.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import platform
import sys
import time
from typing import Any

import numpy as np


def _propagated_variance(system: Any, sigma2_rows: np.ndarray) -> tuple[float, np.ndarray]:
    from shwfs_ao.experiments.detector_level import _propagation_weights

    weights = _propagation_weights(system)
    if not weights["available"]:
        raise SystemExit(weights["reason"])
    per_row = np.asarray(weights["weights_m2_per_px2"], dtype=float)
    return float(np.sum(sigma2_rows * per_row)), per_row


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--profile", default="det_emccd_2m_synthetic")
    parser.add_argument("--profile-version", type=int, default=1)
    parser.add_argument("--magnitudes", default="5,7")
    parser.add_argument("--root-seed", type=int, default=61)
    parser.add_argument("--identity-covariance", action="store_true", help="propagate an identity slope covariance instead of the reference magnitude's flat-wavefront model")
    arguments = parser.parse_args(argv)

    import scipy

    import shwfs_ao
    from shwfs_ao.experiments.detector_level import reconstructor_matrix, with_magnitude
    from shwfs_ao.experiments.scao import ScaoExecutionOptions, build_scao_system
    from shwfs_ao.io.configs import RandomSeedConfig, load_system_profile
    from dataclasses import replace

    magnitudes = [float(item) for item in arguments.magnitudes.split(",")]
    base = load_system_profile(arguments.profile, arguments.profile_version)
    started = time.perf_counter()
    systems = {}
    build_s = {}
    for magnitude in magnitudes:
        config = replace(with_magnitude(base, magnitude), random=RandomSeedConfig(root_seed=arguments.root_seed))
        t0 = time.perf_counter()
        systems[magnitude] = build_scao_system(config, execution=ScaoExecutionOptions(telemetry_level="summary"))
        build_s[magnitude] = time.perf_counter() - t0
    reference_magnitude = magnitudes[0]
    row_ids = tuple(systems[reference_magnitude].wfs.row_ids)
    matrices = {}
    for magnitude, system in systems.items():
        if tuple(system.wfs.row_ids) != row_ids:
            raise SystemExit("the systems differ in row layout; no comparison.")
        matrices[magnitude] = reconstructor_matrix(system.reconstructor, row_ids)
    reference_system = systems[reference_magnitude]
    quality = reference_system.wfs.noise_model(np.zeros(reference_system.wfs.geometry.pupil_shape))
    sigma2 = np.asarray(quality.centroid_sigma_xy_px, dtype=float).reshape(-1) ** 2
    supported = np.repeat(np.asarray(quality.supported, dtype=bool), 2)
    if arguments.identity_covariance:
        sigma2 = np.ones_like(sigma2)
    sigma2 = np.where(supported, sigma2, 0.0)
    propagated = {}
    weights = {}
    for magnitude, system in systems.items():
        propagated[magnitude], weights[magnitude] = _propagated_variance(system, sigma2)
    reference_matrix = matrices[reference_magnitude]
    comparisons = []
    for magnitude in magnitudes[1:]:
        difference = matrices[magnitude] - reference_matrix
        interaction_reference = np.asarray(reference_system.interaction_matrix.matrix, dtype=float)
        interaction_other = np.asarray(systems[magnitude].interaction_matrix.matrix, dtype=float)
        reference_centroids = np.asarray(reference_system.wfs.reference_centroids_px, dtype=float)
        other_centroids = np.asarray(systems[magnitude].wfs.reference_centroids_px, dtype=float)
        comparisons.append(
            {
                "magnitude": magnitude,
                "reference_magnitude": reference_magnitude,
                "reconstructor_relative_frobenius_difference": float(np.linalg.norm(difference) / np.linalg.norm(reference_matrix)),
                "reconstructor_max_abs_relative_entry_difference": float(np.max(np.abs(difference)) / np.max(np.abs(reference_matrix))),
                "interaction_matrix_relative_frobenius_difference": float(np.linalg.norm(interaction_other - interaction_reference) / np.linalg.norm(interaction_reference)),
                "reference_centroid_max_abs_difference_px": float(np.max(np.abs(other_centroids - reference_centroids))),
                "calibration_products_hash_equal": reference_system.wfs.calibration_products.content_hash == systems[magnitude].wfs.calibration_products.content_hash,
                "camera_maps_realization_hash_equal": reference_system.wfs.camera_maps.realization_hash == systems[magnitude].wfs.camera_maps.realization_hash,
                "propagated_variance_reference_m2": propagated[reference_magnitude],
                "propagated_variance_m2": propagated[magnitude],
                "propagated_variance_relative_change": propagated[magnitude] / propagated[reference_magnitude] - 1.0,
                "weights_relative_frobenius_difference": float(np.linalg.norm(weights[magnitude] - weights[reference_magnitude]) / np.linalg.norm(weights[reference_magnitude])),
                "config_hash_reference": reference_system.config_hash,
                "config_hash": systems[magnitude].config_hash,
                "reconstructor_hash_equal": reference_system.component_hashes["reconstructor"] == systems[magnitude].component_hashes["reconstructor"],
                "interaction_matrix_hash_equal": reference_system.component_hashes["interaction_matrix"] == systems[magnitude].component_hashes["interaction_matrix"],
            }
        )
    result = {
        "schema": "shwfs_ao.noise_isolation_offline_h5_bound.v1",
        "generated_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "script_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "package_file": shwfs_ao.__file__,
        "environment": {"python": sys.version, "numpy": np.__version__, "scipy": scipy.__version__, "machine": platform.machine()},
        "profile": f"{arguments.profile}@{arguments.profile_version}",
        "root_seed": arguments.root_seed,
        "magnitudes": magnitudes,
        "fixed_covariance": "identity per row" if arguments.identity_covariance else f"flat-wavefront detector_covariance_v2 of m_AB {reference_magnitude:g} (supported lenslets; unsupported rows weighted zero)",
        "supported_rows": int(np.count_nonzero(supported)),
        "rows": len(row_ids),
        "assumptions": [
            "linear reconstructor for a fixed, fully valid row mask (probed row by row)",
            "V(R) = sum_r sigma_r^2 w_r(R): independent rows; the x/y covariance's off-diagonal terms are dropped",
            "w_r is the piston-removed pupil mean square of the DM response to a unit slope in row r (probe 1e-3 px, linear DM)",
            "fixed inputs: one root seed, the same persistent maps and calibration products are expected across magnitudes (their hashes are reported)",
            "a bound on H5 for this profile and seed; not a closure of LIM-18 or AR-006",
        ],
        "build_s": build_s,
        "comparisons": comparisons,
        "wall_s": time.perf_counter() - started,
    }
    arguments.output.parent.mkdir(parents=True, exist_ok=True)
    arguments.output.write_text(json.dumps(result, indent=1, default=float) + "\n")
    for item in comparisons:
        print(f"m{item['reference_magnitude']:g} -> m{item['magnitude']:g}: reconstructor rel. Frobenius {item['reconstructor_relative_frobenius_difference']:.3e}, propagated variance rel. change {item['propagated_variance_relative_change']:+.3e}")
    print(f"wrote {arguments.output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
