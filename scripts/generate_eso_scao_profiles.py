"""Generate the packaged ESO-derived SCAO benchmark profiles (schema v5).

The records are written from one table of declared values so that the tiers
differ only where the benchmark says they do.  Every value is traced in the
assumption ledger of its version (``benchmarks/eso_drm_42m_scao_derived.assumptions.v<N>.json``,
IDs A01-A12) and the source ledger.  ``--check`` verifies that the packaged
files equal what this script would write.

Versions
--------
``@1`` used the whole 24-pixel Nyquist canvas as the detector window.  That
window has one more row and column on the negative side of the optical-axis
pixel, so a centre of gravity reads a negative slope for symmetric but broad
spots, and the closed loop settles on a compensating static tilt of about
+2.6e-8 rad (5 mas; one 0.5 lambda/D pixel at 2.2 um on 42 m).  ``@1`` stays
frozen as the configuration the first runs used.  ``@2`` changes only
``wfs.detector_window_px`` to 23, a window symmetric about the axis pixel
(evidence: ``docs/refactor/eso_scao_evidence/centroid_window_bias_diagnostic.txt``).

Tiers
-----
``eso_scao_smoke_5m_software@1``
    Software smoke label.  5 m aperture, 10x10 SH, 11x11 DM, 120 samples:
    the full tier's 0.5 m pitch and 12 samples per lenslet at a desktop-safe
    size.  A distinct physical experiment, not a scaled benchmark result.
``eso_scao_medium_12m_derived@1``
    Medium scaling tier: 12 m, 24x24 SH, 25x25 DM, 288 samples, 200 frames.
``eso_scao_medium_12m_weak_gate@1``
    The medium tier under a predeclared weak atmosphere (r0 = 0.40 m at
    500 nm) for the control gate, 120 frames.
``eso_drm_42m_scao_derived@1``
    Full nominal spatial scale: 42 m, 84x84 SH, 85x85 DM, 1008 samples,
    2000 frames (the R1 reference length).
"""

from __future__ import annotations

import argparse
from dataclasses import replace
import json
import math
from pathlib import Path
import sys

from shwfs_ao.core.provenance import Provenance
from shwfs_ao.io.configs import (
    CalibrationConfig,
    CommandProjectorConfig,
    ControllerConfig,
    DetectorSystemConfig,
    DmSystemConfig,
    ProfileProvenance,
    RandomSeedConfig,
    ReconstructorConfig,
    ScalablePathConfig,
    ScienceConfig,
    SystemConfig,
    WfsConfig,
    system_config_to_mapping,
)
from shwfs_ao.io.turbulence_profiles import eso_elt_turbulence_profile


PRESETS = Path(__file__).resolve().parents[1] / "src" / "shwfs_ao" / "resources" / "synthetic_presets"
R1_URL = "https://www.eso.org/sci/facilities/eelt/science/drm/tech_data/ao/"
VERSIONS = (1, 2)
DETECTOR_WINDOW_PX = {1: 24, 2: 23}


def _ledgers(version: int) -> tuple[str, ...]:
    return (
        "benchmarks/eso_scao_source_ledger.v1.json",
        f"benchmarks/eso_drm_42m_scao_derived.assumptions.v{version}.json",
        "docs/eso_scao_benchmark.md",
    )


TIERS = {
    "eso_scao_smoke_5m_software": dict(
        diameter=5.0, pupil=120, lenslets=10, actuators=11, steps=32,
        science=(1.65e-6, 2.2e-6), r0=0.13,
        label="software smoke tier (5 m, 10x10 SH, 11x11 DM, 120 samples, 32 frames)",
    ),
    "eso_scao_medium_12m_derived": dict(
        diameter=12.0, pupil=288, lenslets=24, actuators=25, steps=200,
        science=(2.2e-6,), r0=0.13,
        label="medium scaling tier (12 m, 24x24 SH, 25x25 DM, 288 samples, 200 frames)",
    ),
    "eso_scao_medium_12m_weak_gate": dict(
        diameter=12.0, pupil=288, lenslets=24, actuators=25, steps=120,
        science=(2.2e-6,), r0=0.40,
        label=(
            "medium control-gate tier under a predeclared weak atmosphere "
            "(r0 = 0.40 m at 500 nm; 12 m, 24x24 SH, 25x25 DM, 288 samples, 120 frames)"
        ),
    ),
    "eso_drm_42m_scao_derived": dict(
        diameter=42.0, pupil=1008, lenslets=84, actuators=85, steps=2000,
        science=(2.2e-6,), r0=0.13,
        label=(
            "full nominal spatial scale (42 m, 84x84 SH, 85x85 DM, 1008 samples, "
            "2000 frames = 4 s at 500 Hz)"
        ),
    ),
}


def build(name: str, version: int = 2) -> SystemConfig:
    tier = TIERS[name]
    window = DETECTOR_WINDOW_PX[version]
    atmosphere = eso_elt_turbulence_profile().to_atmosphere_config()
    if tier["r0"] != atmosphere.r0_m:
        atmosphere = replace(atmosphere, r0_m=tier["r0"])
    actuators = int(tier["actuators"])
    # A06: retain every nominal actuator whose one-pitch support square can
    # reach the pupil disk: centre radius <= R + sqrt(2) p = R (1 + 2 sqrt(2)/(N-1)).
    margin = 2.0 * math.sqrt(2.0) / (actuators - 1)
    rationale = (
        f"ESO-derived SCAO benchmark, {tier['label']}. Normative scales from the "
        "ESO E-ELT DRM AO technical-data page (R1) and telescope page (R2): "
        "obstruction ratio 0.28, ten-layer von Karman atmosphere (r0 and L0 "
        "from R1, fractions renormalized from their printed 1.001, every layer "
        "toward +x), linear-spline ground DM in Fried geometry, 500 Hz, a "
        "three-interval command delay (latency_frames=2), deterministic "
        "noiseless image-based SH sensing at 700 nm. Every executable value "
        "not fixed by R1/R2 is an explicit engineering assumption in the "
        "packaged assumption ledger. Not an ESO instrument model and not a "
        "reproduction of the R3/R4 SCAO studies."
    )
    if version >= 2:
        rationale += (
            " Version 2 changes only the detector window, from the whole "
            "24-pixel canvas to 23 pixels symmetric about the optical-axis "
            "pixel, removing a centre-of-gravity bias that left a static "
            "+2.6e-8 rad tilt in the corrected wavefront of version 1."
        )
    return SystemConfig(
        backend="native",
        wfs_model="detector_level",
        atmosphere_model="native_layered",
        telescope_diameter_m=float(tier["diameter"]),
        pupil_pixels=int(tier["pupil"]),
        lenslets_across=int(tier["lenslets"]),
        actuators_across=actuators,
        wfs_wavelength_m=7.0e-7,
        science_wavelengths_m=tuple(tier["science"]),
        atmosphere=atmosphere,
        detector=DetectorSystemConfig(
            enabled=True,
            photons_per_subap_frame=1.0e5,
            read_noise_e=0.0,
            dark_e_per_s=0.0,
            background_e_per_pixel_frame=0.0,
            full_well_e=None,
            qe=1.0,
            prnu_rms=0.0,
            exposure_s=0.002,
            prnu_mode="persistent",
            bad_pixel_fraction=0.0,
        ),
        wfs=WfsConfig(
            min_fill_fraction=0.5,
            pad_factor=2,
            detector_window_px=window,
            centroid_estimator="center_of_gravity",
            threshold_fraction=0.0,
            subtract_minimum=False,
            min_flux_e=100.0,
            min_peak_snr=3.0,
            max_centroid_sigma_px=0.5,
            max_window_clipping_fraction=0.15,
            central_obstruction_ratio=0.28,
            spider_width_m=0.0,
            photon_allocation="throughput_scaled",
            clip_negative_pixels=True,
        ),
        dm=DmSystemConfig(
            influence_model="linear_spline",
            coupling_width_pitch=1.0,
            stroke_limit_opd_m=1.0e-4,
            include_edge_actuators=True,
            actuator_margin_fraction=margin,
            dead_actuator_indices=(),
            stuck_actuator_indices=(),
            stuck_command_opd_m=0.0,
        ),
        calibration=CalibrationConfig(
            source="build",
            method="central",
            probe_kind="dm_actuator",
            amplitude_m=2.0e-8,
            include_noise=False,
            repeats=1,
            resource_name=None,
        ),
        reconstructor=ReconstructorConfig(
            kind="sparse_lsmr_tikhonov",
            rcond=None,
            alpha=1.0e-3,
            min_valid_fraction=0.5,
            min_rank=1,
            max_cached_masks=0,
        ),
        command_projector=CommandProjectorConfig(
            kind="controlled_subset", mapping_resource=None
        ),
        controller=ControllerConfig(
            n_steps=int(tier["steps"]),
            gain=0.4,
            leak=0.0,
            latency_frames=2,
            frame_rate_hz=500.0,
            include_noise=False,
        ),
        science=ScienceConfig(psf_pad_factor=2),
        random=RandomSeedConfig(root_seed=1),
        profile=ProfileProvenance(
            profile_name=name,
            profile_version=version,
            baseline_rationale=rationale,
            provenance=Provenance(
                source_class="synthetic_assumed",
                source_note=(
                    "ESO-derived synthetic engineering SCAO configuration: R1/R2 "
                    "scales and the literature_derived ESO DRM atmosphere, with "
                    "every other value an explicit engineering assumption "
                    "(assumption ledger A01-A12). Not observatory telemetry."
                ),
                source_id=f"shwfs_ao.system_profile.{name}.v{version}",
                url=R1_URL,
                access_time="2026-10-14",
                fallback_used=False,
                references=(
                    "R1: ESO E-ELT DRM, AO performance and PSFs (updated 2011-05-25)",
                    "R2: ESO E-ELT DRM, telescope technical data (2013-03-20)",
                )
                + _ledgers(version),
            ),
        ),
        record_schema_version=5,
        scalable=ScalablePathConfig(
            dm_operator="linear_spline_local_sparse",
            wfs_geometry="compact_cells",
            calibration_strategy="grouped_local_noiseless",
            solver="lsmr",
            solver_atol=1.0e-8,
            solver_btol=1.0e-8,
            solver_max_iterations=5000,
            nonconverged_policy="reject",
        ),
    )


def render(name: str, version: int = 2) -> str:
    return json.dumps(system_config_to_mapping(build(name, version)), indent=2) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--check", action="store_true")
    arguments = parser.parse_args()
    status = 0
    for name, version in ((name, version) for name in TIERS for version in VERSIONS):
        path = PRESETS / f"{name}.v{version}.json"
        text = render(name, version)
        if arguments.check:
            if not path.is_file() or path.read_text() != text:
                print(f"STALE {path}")
                status = 1
        else:
            path.write_text(text)
            print(f"wrote {path}")
    return status


if __name__ == "__main__":
    sys.exit(main())
