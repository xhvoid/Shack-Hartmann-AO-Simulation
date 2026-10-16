"""Generate the packaged detector-level SCAO profiles (schema v7).

Every profile is derived from a packaged base profile by an explicit list of
replacements, so it differs from its base only where the detector-level
model says it must.  Every value is traced in
``benchmarks/detector_level.assumptions.v1.json`` (rows B01-B14) and the
detector source ledger.  ``--check`` verifies that the packaged files equal
what this script would write.

Families (new names, never new versions of existing profiles):

``det_ccd_2m_synthetic@1``, ``det_emccd_2m_synthetic@1``, ``det_cmos_2m_synthetic@1``
    Milestone A: ``fast_2m_detector@4`` with a synthetic physical camera,
    photometric AB source and sky, estimated calibration products and
    detector noise on.  Monochromatic, frozen FFT point sampling (pad 3).
``det_emccd_2m_plane_synthetic@1``
    Milestone B at 2 m: MFT pixel integration (k = 4), charge diffusion,
    electronic coupling and a three-node R3 band.
``det_emccd_12m_medium_derived@1``
    Milestone B on ``eso_scao_medium_12m_derived@2`` (scalable path).
``det_ccd_42m_r3band_derived@1``
    ``eso_drm_42m_scao_derived@2`` with the R3 band (0.6-0.9 um) and 3 e-
    read noise, and R4's 1e5 photoelectrons per frame per subaperture.
"""

from __future__ import annotations

import argparse
from dataclasses import replace
import json
from pathlib import Path
import sys

from shwfs_ao.core.provenance import Provenance
from shwfs_ao.detector.physical_config import (
    BandpassConfig,
    DetectorPlaneSamplingConfig,
    SourceBudgetConfig,
)
from shwfs_ao.detector.processing import PixelProcessingConfig
from shwfs_ao.io.configs import (
    DetectorPhysicsConfig,
    ProfileProvenance,
    SystemConfig,
    load_system_profile,
    system_config_to_mapping,
)


OUTPUT_DIR = Path(__file__).resolve().parents[1] / "src/shwfs_ao/resources/synthetic_presets"
LEDGERS = (
    "benchmarks/detector_source_ledger.v1.json",
    "benchmarks/detector_level.assumptions.v1.json",
)
R3_BAND_M = (6.0e-7, 9.0e-7)
MONO_BAND_M = (5.5e-7, 8.5e-7)
SKY_AB_MAG_ARCSEC2 = 20.5
THROUGHPUT_EXCLUDING_QE = 0.4
# Controller gains selected by the predeclared DET-09 scan (status file).
GAINS: dict[str, float] = {
    # docs/refactor/detector_level_evidence/det09_gain_scan.json: at 2 m every
    # gain lies within the 2 % tie band (fitting-error-limited residual), so
    # the rule picks the lowest; on the ci geometry 0.3 wins outright.
    "det_ccd_2m_synthetic": 0.2,
    "det_emccd_2m_synthetic": 0.2,
    "det_cmos_2m_synthetic": 0.2,
    "det_emccd_2m_plane_synthetic": 0.2,
    "det_emccd_12m_medium_derived": 0.3,
    "det_ccd_42m_r3band_derived": 0.3,
}


def _processing(n_frames: int, hot_threshold_e: float) -> PixelProcessingConfig:
    return PixelProcessingConfig(
        mode="estimated",
        n_bias_frames=n_frames,
        n_dark_frames=n_frames,
        n_sky_frames=n_frames,
        n_flat_frames=n_frames,
        flat_level_e=1000.0,
        hot_pixel_threshold_e=hot_threshold_e,
        flat_low_threshold=0.5,
        flat_high_threshold=1.5,
        bad_pixel_policy="zero_weight",
        gain_treatment="known_per_pixel",
        clip_negative=False,
    )


def _ab_source(magnitude: float) -> SourceBudgetConfig:
    return SourceBudgetConfig(
        kind="ab_flat_fnu",
        ab_magnitude=magnitude,
        throughput_excluding_qe=THROUGHPUT_EXCLUDING_QE,
        sky_ab_mag_per_arcsec2=SKY_AB_MAG_ARCSEC2,
    )


def _legacy_pixel_scale_rad(base: SystemConfig) -> float:
    """lambda / (pad * n_s * dx): the base profile's FFT pixel scale."""

    samples_per_lenslet = -(-base.pupil_pixels // base.lenslets_across)
    # Pupil samples span the diameter edge to edge: D / (N - 1).
    dx = base.telescope_diameter_m / (base.pupil_pixels - 1)
    assert base.wfs.pad_factor is not None
    return base.wfs_wavelength_m / (base.wfs.pad_factor * samples_per_lenslet * dx)


SPECS: dict[str, dict[str, object]] = {
    "det_ccd_2m_synthetic": {
        "base": ("fast_2m_detector", 4),
        "camera": ("synthetic_ccd", 1),
        "magnitude": 5.0,
        "hot_threshold_e": 5.0,
        "milestone": "A",
    },
    "det_emccd_2m_synthetic": {
        "base": ("fast_2m_detector", 4),
        "camera": ("synthetic_emccd", 1),
        "magnitude": 7.0,
        "hot_threshold_e": 0.5,
        "milestone": "A",
    },
    "det_cmos_2m_synthetic": {
        "base": ("fast_2m_detector", 4),
        "camera": ("synthetic_cmos", 1),
        "magnitude": 5.0,
        "hot_threshold_e": 3.0,
        "milestone": "A",
    },
    "det_emccd_2m_plane_synthetic": {
        "base": ("fast_2m_detector", 4),
        "camera": ("synthetic_emccd_coupled", 1),
        "magnitude": 7.0,
        "hot_threshold_e": 0.5,
        "milestone": "B",
    },
    "det_emccd_12m_medium_derived": {
        "base": ("eso_scao_medium_12m_derived", 2),
        "camera": ("synthetic_emccd_coupled", 1),
        # m_AB = 6 drives the brightest pixels past 90 % of the EM register
        # capacity at G = 300; m_AB = 8 (~2500 e- per subaperture) does not.
        "magnitude": 8.0,
        "hot_threshold_e": 0.5,
        "milestone": "B",
    },
    "det_ccd_42m_r3band_derived": {
        "base": ("eso_drm_42m_scao_derived", 2),
        "camera": ("synthetic_ccd", 1),
        "magnitude": None,
        "hot_threshold_e": 5.0,
        "milestone": "B",
    },
}


def build(name: str) -> SystemConfig:
    spec = SPECS[name]
    base_name, base_version = spec["base"]  # type: ignore[misc]
    base = load_system_profile(base_name, base_version)
    camera_name, camera_version = spec["camera"]  # type: ignore[misc]
    milestone = spec["milestone"]
    legacy_scale = _legacy_pixel_scale_rad(base)
    if name in ("det_ccd_2m_synthetic", "det_emccd_2m_synthetic", "det_cmos_2m_synthetic"):
        window, guard, pad = 23, 0, base.wfs.pad_factor
        sampling = DetectorPlaneSamplingConfig(kind="legacy_fft")
        bandpass = BandpassConfig(kind="monochromatic", band_min_m=MONO_BAND_M[0], band_max_m=MONO_BAND_M[1])
        n_frames = 32
    elif name == "det_emccd_2m_plane_synthetic":
        window, guard, pad = 21, 1, None
        sampling = DetectorPlaneSamplingConfig(
            kind="mft_pixel_integrated", pixel_scale_rad=legacy_scale, oversampling=4, diffusion_sigma_px=0.25
        )
        bandpass = BandpassConfig(kind="gauss_legendre", band_min_m=R3_BAND_M[0], band_max_m=R3_BAND_M[1], n_samples=3)
        n_frames = 32
    else:
        window, guard, pad = 15, 1, None
        oversampling = 4 if name == "det_emccd_12m_medium_derived" else 2
        sampling = DetectorPlaneSamplingConfig(
            kind="mft_pixel_integrated", pixel_scale_rad=legacy_scale, oversampling=oversampling, diffusion_sigma_px=0.2
        )
        bandpass = BandpassConfig(kind="gauss_legendre", band_min_m=R3_BAND_M[0], band_max_m=R3_BAND_M[1], n_samples=3)
        n_frames = 32 if name == "det_emccd_12m_medium_derived" else 16
    if spec["magnitude"] is None:
        source = SourceBudgetConfig(kind="detected_electrons", detected_e_per_full_subap_frame=1.0e5)
    else:
        source = _ab_source(float(spec["magnitude"]))  # type: ignore[arg-type]
    physics = DetectorPhysicsConfig(
        camera_preset_name=camera_name,
        camera_preset_version=camera_version,
        layout_scheme="isolated_lenslet_blocks.v1",
        guard_px=guard,
        source=source,
        bandpass=bandpass,
        sampling=sampling,
        processing=_processing(n_frames, float(spec["hot_threshold_e"])),  # type: ignore[arg-type]
        exposure_subsamples=1,
    )
    detector = replace(
        base.detector,
        enabled=True,
        photons_per_subap_frame=None,
        read_noise_e=0.0,
        dark_e_per_s=0.0,
        background_e_per_pixel_frame=0.0,
        full_well_e=None,
        qe=1.0,
        prnu_rms=0.0,
        prnu_mode="persistent",
        bad_pixel_fraction=0.0,
    )
    wfs = replace(
        base.wfs,
        pad_factor=pad,
        detector_window_px=window,
        clip_negative_pixels=False,
    )
    reconstructor = base.reconstructor
    if reconstructor.min_valid_fraction > 0.75:
        reconstructor = replace(reconstructor, min_valid_fraction=0.75)
    controller = replace(base.controller, include_noise=True, gain=GAINS[name])
    rationale = (
        f"Detector-level noise-on profile (milestone {milestone}) derived from "
        f"{base_name}@{base_version}: physical camera {camera_name}@{camera_version} "
        "(shwfs_ao.detector.physical_camera.v1), declared detector-pixel layout, "
        "photometric budget, estimated calibration products and RTC pixel processing, "
        f"centroid window {window} px (odd, symmetric about the optical-axis pixel), "
        f"controller gain {GAINS[name]} from the predeclared DET-09 scan, detector "
        "noise on.  Every other value is the base profile's."
    )
    provenance = Provenance(
        source_class="synthetic_assumed",
        source_note=(
            "Synthetic detector-level SCAO profile.  Camera presets are synthetic "
            "engineering values without a datasheet; derived ESO tiers keep their "
            "ledgered geometry and atmosphere.  Not measured observatory or camera data."
        ),
        source_id=f"shwfs_ao.system_profile.{name}.v1",
        references=(
            "docs/refactor/DETECTOR_LEVEL_DEVELOPMENT_PROMPT.md",
            "docs/refactor/DETECTOR_LEVEL_DEVELOPMENT_STATUS.md",
            "docs/detector_model.md",
            *LEDGERS,
            f"base profile {base_name}@{base_version}",
        ),
    )
    return replace(
        base,
        detector=detector,
        wfs=wfs,
        reconstructor=reconstructor,
        controller=controller,
        profile=ProfileProvenance(
            profile_name=name,
            profile_version=1,
            baseline_rationale=rationale,
            provenance=provenance,
        ),
        record_schema_version=7,
        detector_physics=physics,
    )


# Version 2 of the 12 m profile (post-hoc, recorded reason): E3 on @1 showed
# that the inherited peak-pixel SNR gate (min_peak_snr = 3) rejects lenslets
# whose total SNR is adequate from m_AB ~ 9.5, and that calibrating on the
# operating-flux reference path makes the system uncalibratable from m_AB = 11
# (docs/refactor/DETECTOR_LEVEL_DEVELOPMENT_STATUS.md, E3).  @2 calibrates with
# a bright internal source and gates on the validated detector_covariance_v1
# domain (SNR_T >= 7, sigma <= 0.5 px) instead of peak-pixel SNR.
CALIBRATION_SOURCE_E = 2.5e3
VERSION_2 = ("det_emccd_12m_medium_derived",)


def build_version(name: str, version: int) -> SystemConfig:
    config = build(name)
    if version == 1:
        return config
    if version != 2 or name not in VERSION_2:
        raise KeyError((name, version))
    assert config.detector_physics is not None
    rationale = (
        f"{name}@1 with two changes made after its predeclared E3 magnitude scan: "
        "a bright internal calibration source of 2500 detected e- per full "
        "subaperture for the reference and interaction calibration (the @1 "
        "calibration on the operating flux refused to build from m_AB = 11), and "
        "wfs.min_peak_snr = 0 so validity rests on the validated "
        "detector_covariance_v1 domain (SNR_T >= 7) and max_centroid_sigma_px "
        "(the inherited peak-pixel gate removed lenslets with adequate total SNR "
        "from m_AB ~ 9.5).  Gain 0.3 is the @1 scan selection: the scan ran at "
        "m_AB = 8, where neither change binds."
    )
    provenance = Provenance(
        source_class="synthetic_assumed",
        source_note=config.profile.provenance.source_note,
        source_id=f"shwfs_ao.system_profile.{name}.v2",
        references=config.profile.provenance.references,
    )
    return replace(
        config,
        wfs=replace(config.wfs, min_peak_snr=0.0),
        detector_physics=replace(
            config.detector_physics,
            calibration_source_detected_e_per_full_subap_frame=CALIBRATION_SOURCE_E,
        ),
        profile=ProfileProvenance(
            profile_name=name,
            profile_version=2,
            baseline_rationale=rationale,
            provenance=provenance,
        ),
    )


def _all_versions() -> list[tuple[str, int]]:
    return [(name, 1) for name in SPECS] + [(name, 2) for name in VERSION_2]


def render(name: str, version: int = 1) -> str:
    return json.dumps(system_config_to_mapping(build_version(name, version)), indent=2) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="verify packaged files")
    arguments = parser.parse_args()
    status = 0
    for name, version in _all_versions():
        path = OUTPUT_DIR / f"{name}.v{version}.json"
        text = render(name, version)
        if arguments.check:
            if not path.exists() or path.read_text() != text:
                print(f"DIFFERS: {path}")
                status = 1
        else:
            path.write_text(text)
            print(f"wrote {path}")
    status |= write_ledger(arguments.check)
    status |= write_resource_manifest(arguments.check)
    return status


# -- assumption ledger ---------------------------------------------------------------

LEDGER_PATH = OUTPUT_DIR.parent / "benchmarks/detector_level.assumptions.v1.json"
_TESTS = {
    "camera": [
        "tests/detector/test_physical_camera.py::test_poisson_through_register_has_excess_factor_two",
        "tests/io/test_detector_level_profiles.py::test_packaged_camera_presets_are_versioned_and_synthetic",
    ],
    "sampling": [
        "tests/backends/native/test_shwfs_mft.py::test_k1_mft_reproduces_the_frozen_fft_spots",
        "tests/backends/native/test_shwfs_mft.py::test_pixel_integration_matches_erf_integrals_and_converges",
    ],
    "diffusion": [
        "tests/backends/native/test_shwfs_mft.py::test_diffusion_adds_its_variance_to_the_spot",
        "tests/detector/test_noise_model.py::test_coupled_readout_covariance_is_k_diag_mu_k_transpose_plus_read",
    ],
    "bandpass": [
        "tests/backends/native/test_shwfs_mft.py::test_quadrature_convergence_of_slopes_and_centroid_gain",
        "tests/detector/test_photometry.py::test_wavelength_dependent_qe_matches_an_independent_integral",
    ],
    "source": [
        "tests/detector/test_photometry.py::test_flat_fnu_top_hat_matches_the_analytic_integral",
        "tests/wfs/test_physical_sensor.py::test_half_qe_gives_half_the_source_electrons_not_a_quarter",
    ],
    "sky": ["tests/detector/test_photometry.py::test_sky_electrons_scale_with_pixel_solid_angle_and_match_a_hand_calculation"],
    "products": [
        "tests/wfs/test_physical_sensor.py::test_master_variance_scales_as_one_over_n_with_shared_frame_covariance",
        "tests/detector/test_noise_model.py::test_calibration_ensemble_matches_the_model",
    ],
    "bad": ["tests/wfs/test_physical_sensor.py::test_bad_pixels_mask_without_losing_a_usable_centroid_and_invalid_when_all_masked"],
    "exposure": ["tests/control/test_exposure_subsamples.py::test_one_subsample_is_bit_identical_with_one_atmosphere_call_per_frame"],
    "gain": ["tests/control/test_profile_stability.py", "tests/io/test_detector_level_ledgers.py::test_profile_gains_are_the_recorded_scan_selections"],
    "layout": ["tests/detector/test_physical_camera.py::test_maps_follow_physical_pixels_not_order_batch_or_subset"],
    "processing": ["tests/wfs/test_physical_sensor.py::test_noiseless_linear_fixture_recovers_the_input_electron_signal"],
    "model": ["tests/detector/test_noise_model.py::test_temporal_scatter_matches_the_model_within_ten_percent"],
    "schema": ["tests/io/test_detector_level_profiles.py::test_malformed_or_unsupported_records_are_rejected_while_parsing"],
}


def ledger_record() -> dict[str, object]:
    from shwfs_ao.io.benchmark_ledgers import profile_value_paths

    configs = {f"{name}@{version}": build_version(name, version) for name, version in _all_versions()}
    ids = list(configs)
    paths = {pid: profile_value_paths(config) for pid, config in configs.items()}

    def by_profile(*keys: str) -> dict[str, dict[str, object]]:
        return {pid: {key: paths[pid][key] for key in keys if key in paths[pid]} for pid in ids}

    physics = "detector_physics"
    rows: list[dict[str, object]] = []

    def row(identifier, title, classification, values_by_profile, *, unit, rationale, limitation, tests, context=(), transformation="none", implicit=False):
        record: dict[str, object] = {
            "id": identifier, "title": title, "classification": classification, "applies_to": "all",
            "unit": unit, "authority_sources": [], "locator": "",
            "rationale": rationale, "transformation": transformation, "limitation": limitation,
            "consuming_tests": tests,
        }
        if values_by_profile:
            record["values_by_profile"] = values_by_profile
        if context:
            record["context_sources"] = list(context)
        if implicit:
            record["implicit_model_property"] = True
        rows.append(record)

    row("B01", "Camera response model, preset and supported EM-gain regime", "engineering_assumption",
        by_profile(f"{physics}.camera.preset_name", f"{physics}.camera.preset_version"), unit="preset key",
        rationale="CCD (read 3 e-, the R3 contextual value), EMCCD (G = 300 in the Gamma high-gain regime, pre-register CIC 0.005 e-/px/read) and CMOS (per-pixel offset, gain and lognormal read-noise maps) synthetic presets; coupled EMCCD for milestone B",
        limitation="synthetic_assumed engineering presets without a datasheet (no D6); CIC is pre-register only; intermediate EM gains are rejected",
        tests=_TESTS["camera"], context=("D1", "D2", "D3", "D7", "R3"))
    row("B02", "Pixel scale and centroid-window field of view", "engineering_assumption",
        by_profile("wfs.detector_window_px", "wfs.pad_factor", f"{physics}.sampling.pixel_scale_rad"), unit="px; rad",
        rationale="2 m: the base profile's FFT scale (pad 3) with an odd 23 px window (21 px for the MFT profile); 12/42 m: lambda/(2 d) at 700 nm with a 15 px window so the field stays inside one far-field period at 600 nm",
        limitation="the 15 px window spans 7.5 lambda/d at 700 nm; broadened spots clip earlier than in the 23 px ESO tiers",
        tests=_TESTS["sampling"], transformation="pixel scale = lambda/(pad n_s dx) of the base profile, dx = D/(N-1)")
    row("B03", "Detector-plane sampling and optical oversampling", "engineering_assumption",
        by_profile(f"{physics}.sampling.kind", f"{physics}.sampling.oversampling"), unit="nodes per pixel and axis",
        rationale="legacy FFT point sampling for milestone A; Gauss-Legendre pixel quadrature with k = 4 (2 at 42 m for cost) for milestone B, where the erf oracle meets 1e-6 at k = 4",
        limitation="k = 2 at 42 m trades pixel-integration accuracy (~1e-4 relative) for run time", tests=_TESTS["sampling"])
    row("B04", "Charge diffusion, electronic coupling, placement and boundary", "engineering_assumption",
        by_profile(f"{physics}.sampling.diffusion_sigma_px", f"{physics}.layout.guard_px"), unit="px",
        rationale="diffusion sigma 0.25 px (2 m) and 0.2 px (12/42 m, keeps the margin to one pixel), truncated at 5 sigma; coupling only in the coupled EMCCD preset (1 % nearest, 0.2 % diagonal) after saturation and before read noise, zero boundary at the block edge with a one-pixel guard ring",
        limitation="synthetic values; light of neighbouring lenslets is not modelled in a block; the coupling placement is a model assumption (D8 describes CMOS IPC)",
        tests=_TESTS["diffusion"], context=("D8",))
    row("B05", "WFS bandpass, wavelength quadrature and spectral weights", "declared_experiment_choice",
        by_profile(f"{physics}.bandpass.kind", f"{physics}.bandpass.band_min_m", f"{physics}.bandpass.band_max_m", f"{physics}.bandpass.n_samples", "wfs_wavelength_m"), unit="m; nodes",
        rationale="milestone A: monochromatic 700 nm carrying a 550-850 nm bandwidth for photometry; milestone B: the R3 contextual sensing band 0.6-0.9 um with 3 Gauss-Legendre nodes weighted by detected electrons (flat in photon number per wavelength for direct budgets)",
        limitation="3 nodes; quadrature convergence verified to 2e-3 px between 5 and 7 nodes on the 2 m fixture",
        tests=_TESTS["bandpass"], context=("R3",))
    row("B06", "Source budget, magnitude system, area, throughput and QE accounting", "declared_experiment_choice",
        by_profile(f"{physics}.source.kind", f"{physics}.source.ab_magnitude", f"{physics}.source.throughput_excluding_qe",
                   f"{physics}.source.incident_photons_per_full_subap_frame", f"{physics}.source.detected_e_per_full_subap_frame"),
        unit="AB mag; dimensionless; e-",
        rationale="AB magnitudes (Oke & Gunn zero point) with throughput 0.4 excluding QE and the camera's QE applied once; bright-star settings m = 5 (CCD, CMOS) and 7 (EMCCD) at 2 m, m = 8 for the 12 m EMCCD (register capacity), R4's 1e5 per frame per subaperture read as detected photoelectrons at 42 m; per-subaperture budgets scale with illuminated area",
        limitation="R4 states photons, not electrons; reading it as detected electrons keeps the 42 m tier comparable with eso_drm_42m_scao_derived@2",
        tests=_TESTS["source"], context=("D5", "R4"))
    row("B07", "Sky surface brightness", "engineering_assumption", by_profile(f"{physics}.source.sky_ab_mag_per_arcsec2"),
        unit="AB mag arcsec^-2", rationale="20.5 mag/arcsec^2, a dark-sky visible value, constant in f_nu across the band; null for the direct 42 m budget",
        limitation="not site data; negligible at these pixel scales and exposures", tests=_TESTS["sky"])
    row("B08", "Calibration-frame protocol and product definitions", "engineering_assumption",
        by_profile(f"{physics}.processing.mode", f"{physics}.processing.n_bias_frames", f"{physics}.processing.n_dark_frames",
                   f"{physics}.processing.n_sky_frames", f"{physics}.processing.n_flat_frames", f"{physics}.processing.flat_level_e"),
        unit="frames; e-",
        rationale="estimated products from 32 frames each (16 at 42 m for cost), flat at 1000 input e- per pixel; B = bias mean, D = dark mean - B, S = sky mean - B - D, flat = (flat mean - B - D) normalized over valid pixels",
        limitation="no shared input frames between products; products fixed per run and regenerated only with a new calibration realization",
        tests=_TESTS["products"], context=("D9",))
    row("B09", "Bad-pixel detection thresholds and policy", "engineering_assumption",
        by_profile(f"{physics}.processing.hot_pixel_threshold_e", f"{physics}.processing.flat_low_threshold",
                   f"{physics}.processing.flat_high_threshold", f"{physics}.processing.bad_pixel_policy"),
        unit="input e- per frame; normalized flat",
        rationale="hot threshold about six times the dark-master noise of each camera; flat outside [0.5, 1.5] is bad; zero weight",
        limitation="interpolation is available but not used by the profiles", tests=_TESTS["bad"])
    row("B10", "Finite-exposure sub-sample count", "engineering_assumption", by_profile(f"{physics}.exposure_subsamples"),
        unit="samples", rationale="1: the DET-08 study is opt-in and measured separately", limitation="the time quadrature study at 12 m needs enablement",
        tests=_TESTS["exposure"])
    row("B11", "Controller gain selection for noise-on profiles", "declared_experiment_choice",
        by_profile("controller.gain", "controller.include_noise"), unit="dimensionless",
        rationale="predeclared scan over {0.2, 0.3, 0.4, 0.5} with max |pole| <= 0.98; the lowest second-half residual wins, ties within 2 % go to the lower gain (det09_gain_scan.json)",
        limitation="selected on 3 atmosphere realizations; 12/42 m gains scanned on the ci geometry", tests=_TESTS["gain"])
    row("B12", "Detector-pixel layout and immutable pixel IDs", "software_policy", by_profile(f"{physics}.layout.scheme"),
        unit="scheme", rationale="isolated lenslet blocks keyed by stable subaperture IDs; maps drawn per physical block",
        limitation="synthetic non-overlapping layout, not a real detector geometry", tests=_TESTS["layout"])
    row("B13", "Gain knowledge, EM/input-electron conversion and clipping", "software_policy",
        by_profile(f"{physics}.processing.gain_treatment", f"{physics}.processing.clip_negative", "wfs.clip_negative_pixels"),
        unit="policy", rationale="conversion and EM gain are known engineering inputs applied once (per-pixel CMOS gain applied as known conversion gain, the flat then carries PRNU only); no negative clipping, so the centre of gravity stays first-order",
        limitation="no gain estimation; gain errors are outside the model", tests=_TESTS["processing"])
    row("B14", "Uncertainty-model validity domain; temporal versus persistent calibration error", "software_policy", {},
        unit="n/a", rationale="detector_covariance_v1 is supported for a plain centre of gravity without clipping, saturation, non-linearity or coarse quantization and with SNR_T >= 7; temporal sigma conditional on fixed masters gates validity, calibration-ensemble sigma is reported separately",
        limitation="outside the domain the model reports an undefined sigma and the lenslet is invalid", tests=_TESTS["model"], implicit=True)
    neutral = ["detector.enabled", "detector.photons_per_subap_frame", "detector.read_noise_e", "detector.dark_e_per_s",
               "detector.background_e_per_pixel_frame", "detector.full_well_e", "detector.qe", "detector.prnu_rms",
               "detector.prnu_mode", "detector.bad_pixel_fraction", "detector.exposure_s"]
    row("B15", "Neutral compatibility detector block and exposure clock", "software_policy", by_profile(*neutral), unit="various",
        rationale="the camera preset owns noise and QE and the source block owns the budget, so the legacy detector block is neutral and only carries the exposure, equal to the frame period",
        limitation="none", tests=_TESTS["schema"])
    v2_only = [pid for pid in ids if pid.endswith("@2")]

    def v2_values(*keys: str) -> dict[str, dict[str, object]]:
        return {pid: {key: paths[pid][key] for key in keys if key in paths[pid]} for pid in v2_only}

    row("B18", "Validity gating on the detector_covariance_v1 domain (version 2, post-hoc)", "engineering_assumption",
        v2_values("wfs.min_peak_snr"), unit="dimensionless",
        rationale="E3 on @1 showed the inherited peak-pixel SNR gate (3) rejects lenslets with total SNR ~20 from m_AB ~ 9.5 and collapses the loop at m_AB = 10; @2 sets it to 0 and relies on SNR_T >= 7 (validated domain) and sigma <= 0.5 px; recorded reason, the affected experiments are rerun on @2",
        limitation="changed after inspecting E3; @1 keeps the predeclared gate and its results stand", tests=_TESTS["model"])
    row("B19", "Bright internal calibration source (version 2)", "engineering_assumption",
        v2_values(f"{physics}.calibration_source_detected_e_per_full_subap_frame"), unit="detected e- per full subaperture per frame",
        rationale="2500 e- (an m_AB = 8 equivalent at 12 m for the EMCCD) for reference centroids and interaction probes, without sky; @1 calibrated at the operating flux and refused to build from m_AB = 11",
        limitation="the internal source has the operating spectral weights; its sky-free reference differs from the operating sky pedestal only by the sky master (about 1e-4 e- per pixel)",
        tests=["tests/wfs/test_physical_sensor.py::test_a_calibration_source_decouples_calibration_from_the_operating_flux"])
    row("B16", "Noise-on reconstruction validity floor", "engineering_assumption", by_profile("reconstructor.min_valid_fraction"),
        unit="fraction", rationale="0.75 (the 2 m base profiles required 1.0, which freezes the DM on the first noise-invalidated lenslet); the ESO tiers keep 0.5",
        limitation="none", tests=_TESTS["gain"])
    def covered_for(pid: str) -> set[str]:
        return {
            path
            for record in rows
            for path in record.get("values_by_profile", {}).get(pid, {})
        }

    inherited = {}
    for pid, config in configs.items():
        base_name, base_version = SPECS[pid.split("@")[0]]["base"]  # type: ignore[misc]
        if pid.endswith("@2"):
            base_name, base_version = pid.split("@")[0], 1
        covered = covered_for(pid)
        inherited[pid] = {
            path: f"derived:{base_name}@{base_version}"
            for path in paths[pid]
            if path not in covered
        }
    row("B17", "Values inherited unchanged from the base profile", "software_policy", inherited, unit="various",
        rationale="geometry, atmosphere, DM, calibration, reconstructor kind, command projector, loop timing and science settings are the base profile's; ESO-derived tiers are traced by eso_drm_42m_scao_derived.assumptions.v2.json",
        limitation="the 2 m base (fast_2m_detector@4) is a synthetic engineering profile without its own ledger",
        tests=_TESTS["schema"], transformation="none (copied from the base profile)")
    return {
        "schema_name": "shwfs_ao.assumption_ledger",
        "schema_version": 1,
        "ledger_id": "detector_level.assumptions",
        "benchmark": "Detector-level SCAO profiles (docs/refactor/DETECTOR_LEVEL_DEVELOPMENT_PROMPT.md)",
        "source_ledger": "benchmarks/detector_source_ledger.v1.json",
        "profiles": ids,
        "frozen": "2026-10-15",
        "classifications": {
            "source_derived": "value taken from a normative source with its locator",
            "source_scale_adapted": "normative value adapted to this repository's topology; the adaptation is stated",
            "engineering_assumption": "value no source supplies, chosen for a stated engineering reason",
            "declared_experiment_choice": "a choice that defines the experiment, declared before running",
            "software_policy": "a software convention with no physical content",
        },
        "rows": rows,
    }


def write_ledger(check: bool) -> int:
    text = json.dumps(ledger_record(), indent=2) + "\n"
    if check:
        if not LEDGER_PATH.exists() or LEDGER_PATH.read_text() != text:
            print(f"DIFFERS: {LEDGER_PATH}")
            return 1
        return 0
    LEDGER_PATH.write_text(text)
    print(f"wrote {LEDGER_PATH}")
    return 0


def write_resource_manifest(check: bool) -> int:
    """Keep the packaged resource manifest in step with the written files."""

    from shwfs_ao.io.resources import render_resource_manifest

    root = OUTPUT_DIR.parent
    path = root / "resource_manifest.json"
    text = render_resource_manifest(root)
    if check:
        if path.read_text(encoding="utf-8") != text:
            print(f"DIFFERS: {path}")
            return 1
        return 0
    path.write_text(text, encoding="utf-8")
    print(f"wrote {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
