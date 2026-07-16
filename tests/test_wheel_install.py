"""Installed-artifact checks for the namespaced refactor foundation."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tarfile
import textwrap
import zipfile


ROOT = Path(__file__).resolve().parents[1]
DIST_NAME = "shack-hartmann-ao-simulation"
SHIM_MODULES = (
    "ao_closed_loop",
    "ao_conditions",
    "ao_diagnostics",
    "ao_error_budget",
    "ao_integration",
    "ao_validation",
    "atmosphere_profiles",
    "config_hashing",
    "data_sources",
    "dm_model",
    "interaction_matrix",
    "phase_screen",
    "psf_tools",
    "pwfs_forward",
    "reconstruction",
    "runtime_resources",
    "shwfs_detector",
    "synthetic_instrument_data",
    "zernike",
)
WAVEFRONT_EXPORTS = (
    "remove_piston",
    "masked_mean",
    "masked_rms",
    "phase_to_opd",
    "opd_to_phase",
    "mask_outside",
    "validate_masked_finite",
)
GEOMETRY_EXPORTS = (
    "GeometryError",
    "PupilGeometry",
    "build_pupil_geometry",
)
PROVENANCE_EXPORTS = (
    "SourceClass",
    "ALLOWED_SOURCE_CLASSES",
    "Provenance",
)
TYPE_EXPORTS = (
    "MeasurementUnit",
    "MeasurementVector",
    "DetectorPlaneSampling",
    "DetectorFrame",
    "DetectorTelemetry",
    "WfsMeasurement",
    "SpotIntensityResult",
    "PsfResult",
    "DmCommandVector",
    "DmSynthesisResult",
    "ReconstructionEstimate",
)
PROTOCOL_EXPORTS = (
    "RandomStreams",
    "AtmosphereModel",
    "ShackHartmannOpticsBackend",
    "WavefrontSensor",
    "DeformableMirrorModel",
    "Reconstructor",
    "CommandProjector",
    "Controller",
    "SciencePropagator",
)
RANDOM_EXPORTS = (
    "DEFAULT_RANDOM_DOMAINS",
    "DERIVATION_SCHEME_ID",
    "NamedRandomStreams",
    "RandomStreamError",
)
HASHING_EXPORTS = (
    "HASH_SCHEMA_ID",
    "HashingError",
    "stable_array_descriptor",
    "canonicalize_for_hash",
    "canonical_json_bytes",
    "stable_hash",
    "geometry_hash",
    "detector_plane_sampling_hash",
    "calibration_rows_hash",
    "command_coordinates_hash",
    "component_config_hash",
    "hash_geometry",
    "hash_calibration_rows",
    "hash_command_coordinates",
    "hash_component_config",
)
NATIVE_ATMOSPHERE_EXPORTS = (
    "NativeAtmosphereError",
    "StaticOpdAtmosphere",
    "FrozenFlowAtmosphereConfig",
    "FrozenFlowAtmosphere",
)
NATIVE_PROPAGATION_EXPORTS = ("NativeSciencePropagator",)
NATIVE_SHWFS_EXPORTS = (
    "NativeShackHartmannError",
    "NativeShackHartmannOptics",
    "NativeShackHartmannOpticsBackend",
    "nominal_lenslet_sampling_shape",
    "lenslet_spot_from_phase",
    "lenslet_spot_from_opd",
    "crop_center",
)
NATIVE_DM_EXPORTS = (
    "NativeDmError",
    "NativeDmBackend",
    "VALID_INFLUENCE_MODELS",
    "square_grid_actuator_layout",
    "square_grid_actuator_centers",
    "actuator_centers_on_pupil",
    "gaussian_influence_functions",
    "build_influence_functions",
    "synthesize_opd",
)
NATIVE_MODES_EXPORTS = (
    "NativeModesError",
    "polar_pupil_coordinates",
    "normalize_mode_to_unit_pupil_rms",
    "zernike_named_modes",
    "zernike_radial",
    "zernike_nm",
    "generate_zernike_modes",
    "number_of_zernike_modes",
    "synthesize_modes",
    "mode_inner_product",
    "mode_gram_matrix",
)
NATIVE_EXPORTS = (
    *NATIVE_ATMOSPHERE_EXPORTS,
    *NATIVE_PROPAGATION_EXPORTS,
    *NATIVE_SHWFS_EXPORTS,
    *NATIVE_DM_EXPORTS,
    *NATIVE_MODES_EXPORTS,
)
CALIBRATION_DIAGNOSTICS_EXPORTS = (
    "DEFAULT_NUMERIC_RANK_RTOL",
    "InteractionDiagnosticsError",
    "InteractionDiagnostics",
    "calibration_valid_matrix",
    "all_zero_columns",
    "interaction_diagnostics",
)
CALIBRATION_INTERACTION_EXPORTS = (
    "CoordinateKind",
    "CoordinateUnit",
    "CalibrationMethod",
    "INTERACTION_SIGN_CONVENTION",
    "INTERACTION_MATRIX_SCHEMA_ID",
    "InteractionMatrixError",
    "InteractionCalibrationError",
    "ProbeBasis",
    "ModalProbeBasis",
    "DmActuatorProbeBasis",
    "InteractionMatrix",
    "calibrate_interaction_matrix",
    "interaction_matrix_hash",
)
CALIBRATION_RECONSTRUCTOR_EXPORTS = (
    "ReconstructionError",
    "ReconstructorCacheInfo",
    "LeastSquaresReconstructor",
    "TsvdReconstructor",
    "TikhonovReconstructor",
    "kept_modes_for_rcond",
    "noise_amplification_proxy",
    "choose_rcond_from_singular_values",
    "scan_tsvd_rcond",
)
CALIBRATION_EXPORTS = (
    *CALIBRATION_DIAGNOSTICS_EXPORTS,
    *CALIBRATION_INTERACTION_EXPORTS,
    *CALIBRATION_RECONSTRUCTOR_EXPORTS,
)
CONTROL_CONFIG_EXPORTS = (
    "LoopConfigError",
    "LoopConfig",
)
CONTROL_COMMAND_MAPPING_EXPORTS = (
    "CommandMappingError",
    "IdentityCommandProjector",
    "ControlledSubsetCommandProjector",
    "ModalToActuatorCommandProjector",
)
CONTROL_CONTROLLER_EXPORTS = (
    "ControllerError",
    "LeakyIntegratorController",
)
CONTROL_HISTORY_EXPORTS = (
    "LoopHistoryError",
    "LoopHistory",
)
CONTROL_LOOP_EXPORTS = (
    "ControlLoopError",
    "validate_closed_loop_components",
    "run_closed_loop",
)
CONTROL_SWEEP_EXPORTS = (
    "ControlSweepError",
    "gain_scan",
    "latency_scan",
    "photon_scan",
    "read_noise_scan",
    "gain_delay_stability_map",
)
CONTROL_EXPORTS = (
    *CONTROL_CONFIG_EXPORTS,
    *CONTROL_COMMAND_MAPPING_EXPORTS,
    *CONTROL_CONTROLLER_EXPORTS,
    *CONTROL_HISTORY_EXPORTS,
    *CONTROL_LOOP_EXPORTS,
    *CONTROL_SWEEP_EXPORTS,
)
SCIENCE_BANDPASS_EXPORTS = (
    "BandpassError",
    "ScienceBandpass",
    "monochromatic_bandpass",
    "top_hat_bandpass",
    "bandpass_from_filter_curve",
)
SCIENCE_PROPAGATION_EXPORTS = (
    "SciencePropagationError",
    "PsfSampling",
    "monochromatic_psf",
)
SCIENCE_METRICS_EXPORTS = (
    "ScienceMetricsError",
    "PsfScalarMetrics",
    "discrete_flux_to_angular_surface_brightness",
    "peak_strehl_from_discrete_flux",
    "marechal_strehl_from_opd",
    "fwhm_diameter_from_angular_surface_brightness",
    "encircled_energy_radius_from_discrete_flux",
    "halo_fraction_from_discrete_flux",
    "psf_scalar_metrics",
    "band_average_scalar_metrics",
    "lambda_over_d_rad",
    "radians_to_lambda_over_d",
    "radians_to_arcsec",
)
SCIENCE_EXPORTS = (
    *SCIENCE_BANDPASS_EXPORTS,
    *SCIENCE_PROPAGATION_EXPORTS,
    *SCIENCE_METRICS_EXPORTS,
)
DM_CONFIG_EXPORTS = (
    "DEFAULT_ACTUATOR_MARGIN_FRACTION",
    "DEFAULT_DM_SOURCE_CLASS",
    "DEFAULT_DM_SOURCE_NOTE",
    "MIN_ACTUATORS_ACROSS",
    "NM_TO_M",
    "VALID_INFLUENCE_MODELS",
    "DMModelError",
    "DMConfigError",
    "DMConfig",
    "DmConfig",
    "actuator_id",
    "actuator_ids_from_grid_indices",
)
DM_MODEL_EXPORTS = (
    "COMMAND_UNIT",
    "DmBackend",
    "DeformableMirrorError",
    "DeformableMirror",
    "build_native_deformable_mirror",
    "build_deformable_mirror",
)
DM_EXPORTS = (*DM_CONFIG_EXPORTS, *DM_MODEL_EXPORTS)
SHWFS_GEOMETRY_EXPORTS = (
    "DEFAULT_WFS_WAVELENGTH_M",
    "ShwfsGeometryConfig",
    "ShackHartmannGeometryError",
    "ShackHartmannGeometry",
    "build_shack_hartmann_geometry",
    "partition_pupil_geometry",
    "subaperture_id",
    "lenslet_indices_from_id",
)
SHWFS_OPTICS_EXPORTS = (
    "ShackHartmannOpticsError",
    "make_detector_plane_sampling",
    "validate_spot_intensity_result",
    "validate_optics_backend_result",
)
SHWFS_CALIBRATION_EXPORTS = (
    "ShackHartmannCalibrationError",
    "ShackHartmannCalibration",
    "row_ids_for_subapertures",
    "calibrate_zero_phase_reference",
    "shack_hartmann_calibration_hash",
    "legacy_calibration_seeds",
)
SHWFS_MEASUREMENT_EXPORTS = (
    "ShackHartmannMeasurementError",
    "DetectorShackHartmannSensor",
    "DetectorLevelShackHartmannSensor",
    "build_detector_shack_hartmann_sensor",
)
SHWFS_GEOMETRIC_EXPORTS = (
    "GeometricShackHartmannError",
    "GeometricShackHartmannCalibration",
    "NativeGeometricShackHartmannSensor",
    "GeometricShackHartmannSensor",
    "numerical_gradient",
    "mean_subaperture_slopes",
)
SHACK_HARTMANN_EXPORTS = (
    *SHWFS_GEOMETRY_EXPORTS,
    *SHWFS_OPTICS_EXPORTS,
    *SHWFS_CALIBRATION_EXPORTS,
    *SHWFS_MEASUREMENT_EXPORTS,
    *SHWFS_GEOMETRIC_EXPORTS,
)
PWFS_EXPORTS = (
    "add_detector_noise",
    "add_tilt_phase",
    "aligned_pupil_images",
    "calibrate_pwfs_interaction_matrix",
    "check_pwfs_geometry",
    "extract_cutout",
    "fft2c",
    "ifft2c",
    "make_aligned_pupil_mask",
    "make_modulation_points",
    "make_pwfs_grid",
    "pupil_image_centers",
    "pwfs_detector_measurement_from_phase",
    "pwfs_detector_signal_from_phase",
    "pwfs_intensity",
    "pwfs_measurement_from_phase",
    "pwfs_reference_signal",
    "pwfs_signal_from_intensity",
    "pwfs_signal_from_phase",
    "pwfs_signal_maps_from_intensity",
    "pyramid_phase_mask",
)
DETECTOR_CONFIG_EXPORTS = (
    "DEFAULT_SOURCE_CLASS",
    "PrnuMode",
    "SyntheticInstrumentError",
    "DetectorConfigError",
    "DetectorConfig",
    "DetectorPreset",
    "DETECTOR_PRESETS",
    "detector_preset",
    "make_bad_pixel_mask",
)
DETECTOR_RANDOM_EXPORTS = (
    "DetectorRealizationError",
    "DetectorRealization",
)
DETECTOR_EFFECTS_EXPORTS = (
    "DetectorEffectsError",
    "apply_detector_effects",
    "apply_legacy_detector_effects",
)
DETECTOR_CENTROID_EXPORTS = (
    "CentroidMethod",
    "CentroidConfig",
    "CentroidEstimate",
    "CentroidEstimator",
    "CenterOfGravityEstimator",
    "ThresholdedCenterOfGravityEstimator",
    "make_centroid_estimator",
    "estimate_centroid",
)
DETECTOR_VALIDITY_EXPORTS = (
    "CentroidValidityConfig",
    "CentroidQuality",
    "CentroidValidity",
    "DEFAULT_CENTROID_VALIDITY",
    "UNDEFINED_CENTROID_SIGMA_PX",
    "centroid_quality",
    "evaluate_centroid_validity",
)
DETECTOR_EXPORTS = (
    "DEFAULT_SOURCE_CLASS",
    "DETECTOR_PRESETS",
    "PrnuMode",
    "SyntheticInstrumentError",
    "DetectorConfigError",
    "DetectorConfig",
    "DetectorPreset",
    "detector_preset",
    "make_bad_pixel_mask",
    *DETECTOR_RANDOM_EXPORTS,
    *DETECTOR_EFFECTS_EXPORTS,
    *DETECTOR_CENTROID_EXPORTS,
    *DETECTOR_VALIDITY_EXPORTS,
)
CONFIG_EXPORTS = (
    "PROFILE_SCHEMA_NAME",
    "PROFILE_SCHEMA_VERSION",
    "SystemConfigError",
    "ProfileProvenance",
    "AtmosphereConfig",
    "DetectorSystemConfig",
    "WfsConfig",
    "DmSystemConfig",
    "CalibrationConfig",
    "ReconstructorConfig",
    "CommandProjectorConfig",
    "ControllerConfig",
    "ScienceConfig",
    "RandomSeedConfig",
    "SystemConfig",
    "available_system_profiles",
    "load_system_profile",
    "system_config_from_mapping",
    "system_config_to_mapping",
)
PUBLIC_DATA_EXPORTS = (
    "ALLOWED_SOURCE_CLASSES",
    "AtmosphereLayer",
    "DataSourceError",
    "EsoAsmSnapshot",
    "FilterCurve",
    "LiteratureAtmosphereProfile",
    "Provenance",
    "TargetPhotometry",
    "load_eso_asm_snapshot",
    "load_literature_atmosphere_profile",
    "load_svo_filter_curve",
    "load_target_photometry",
)
IO_EXPORTS = (*CONFIG_EXPORTS, *PUBLIC_DATA_EXPORTS)
NATIVE_FACTORY_EXPORTS = (
    "NativeScaoFactoryError",
    "NativeScaoComponentFactory",
    "NATIVE_SCAO_COMPONENT_FACTORY",
)
ERROR_BUDGET_EXPORTS = (
    "DEFAULT_SCENARIO_SOURCE_CLASS",
    "DEFAULT_SCENARIO_SOURCE_NOTE",
    "REQUIRED_SCENARIO_NAMES",
    "DEFAULT_J_BAND",
    "DEFAULT_H_BAND",
    "DEFAULT_K_BAND",
    "NM_PER_M",
    "PHASE_TWO_PI",
    "AOErrorBudgetError",
    "ScenarioConfig",
    "ScenarioResult",
    "default_error_budget_scenarios",
    "default_jhk_bandpasses",
    "run_error_budget_scenarios",
    "run_error_budget_scenario",
    "build_control_space_phase_sequence",
    "summarize_scenario",
    "scenario_results_as_dicts",
)
PUBLIC_DATA_CONDITIONED_EXPORTS = (
    "AOConditionError",
    "ARCSEC_PER_RAD",
    "ObservingConditionConfig",
    "REFERENCE_PHASE_AMPLITUDE_NM",
    "REFERENCE_SEEING_ARCSEC",
    "condition_rows",
    "default_observing_conditions",
    "phase_amplitude_from_seeing",
    "r0_from_seeing_arcsec",
    "theta0_rad_from_arcsec",
)
SCAO_EXPORTS = (
    "ScaoConstructionError",
    "ScaoBackendComponentFactory",
    "ScaoSystem",
    "register_scao_backend_factory",
    "build_scao_system",
    "run_closed_loop",
)
EXPERIMENT_EXPORTS = (
    *ERROR_BUDGET_EXPORTS,
    *PUBLIC_DATA_CONDITIONED_EXPORTS,
    *SCAO_EXPORTS,
)
CORE_EXPORTS = (
    *PROVENANCE_EXPORTS,
    *GEOMETRY_EXPORTS,
    *WAVEFRONT_EXPORTS,
    *TYPE_EXPORTS,
    *PROTOCOL_EXPORTS,
    *RANDOM_EXPORTS,
    *HASHING_EXPORTS,
)
AO_REF_011_PROFILE_RESOURCES = (
    "synthetic_presets/fast_2m_detector.v1.json",
    "synthetic_presets/portfolio_2m_detector.v1.json",
    "synthetic_presets/research_2m_detector.v1.json",
    "synthetic_presets/high_order_10m_geometric.v1.json",
)
AO_REF_011_SYSTEM_PROFILES = (
    ("fast_2m_detector", 1),
    ("portfolio_2m_detector", 1),
    ("research_2m_detector", 1),
    ("high_order_10m_geometric", 1),
)
CONTRACT_MANIFEST = (
    ROOT
    / "src"
    / "shwfs_ao"
    / "resources"
    / "reference_metrics"
    / "refactor_contract_manifest.json"
)
CANONICAL_RESOURCE_ROOT = ROOT / "src" / "shwfs_ao" / "resources"
RESOURCE_MANIFEST = CANONICAL_RESOURCE_ROOT / "resource_manifest.json"


def _run(*args: str, cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, *args],
        cwd=cwd,
        check=True,
        capture_output=True,
        text=True,
    )


def _build_direct_wheel(output_dir: Path) -> Path:
    output_dir.mkdir()
    _run(
        "-m",
        "pip",
        "wheel",
        ".",
        "--no-deps",
        "--no-build-isolation",
        "--no-cache-dir",
        "--wheel-dir",
        str(output_dir),
        cwd=ROOT,
    )
    return next(output_dir.glob("*.whl"))


def _build_sdist_and_wheel(sdist_dir: Path, wheel_dir: Path) -> tuple[Path, Path]:
    sdist_dir.mkdir()
    wheel_dir.mkdir()
    # Calling the configured setuptools backend directly keeps this test
    # offline and avoids adding a second frontend solely for an sdist smoke.
    _run(
        "-c",
        (
            "import sys; "
            "from setuptools.build_meta import build_sdist; "
            "print(build_sdist(sys.argv[1]))"
        ),
        str(sdist_dir),
        cwd=ROOT,
    )
    sdist = next(sdist_dir.glob("*.tar.gz"))
    _run(
        "-m",
        "pip",
        "wheel",
        str(sdist),
        "--no-deps",
        "--no-build-isolation",
        "--no-cache-dir",
        "--wheel-dir",
        str(wheel_dir),
        cwd=sdist_dir,
    )
    return sdist, next(wheel_dir.glob("*.whl"))


def _wheel_payloads(wheel: Path, prefix: str) -> dict[str, bytes]:
    with zipfile.ZipFile(wheel) as archive:
        return {
            name: archive.read(name)
            for name in archive.namelist()
            if name.startswith(prefix) and not name.endswith("/")
        }


def _wheel_members(wheel: Path) -> set[str]:
    with zipfile.ZipFile(wheel) as archive:
        return {name for name in archive.namelist() if not name.endswith("/")}


def _sdist_members(sdist: Path) -> set[str]:
    with tarfile.open(sdist, mode="r:gz") as archive:
        members = {member.name for member in archive.getmembers() if member.isfile()}
    # PEP 517 sdists have one generated top-level directory.  Compare the
    # meaningful source-relative paths rather than its versioned name.
    return {name.split("/", 1)[1] for name in members if "/" in name}


def _resource_contract() -> tuple[dict, list[str], dict[str, str]]:
    historical_manifest = json.loads(CONTRACT_MANIFEST.read_text(encoding="utf-8"))
    checked_manifest = json.loads(RESOURCE_MANIFEST.read_text(encoding="utf-8"))
    assert checked_manifest["schema_name"] == "shwfs_ao.resource_manifest"
    assert checked_manifest["schema_version"] == 1
    records = checked_manifest["resources"]
    names = [record["logical_name"] for record in records]
    assert names == sorted(names)
    expected_hashes: dict[str, str] = {}
    for record in records:
        source = CANONICAL_RESOURCE_ROOT / record["logical_name"]
        actual = hashlib.sha256(source.read_bytes()).hexdigest()
        assert actual == record["sha256"]
        expected_hashes[f"ao_simulation_data/{record['logical_name']}"] = actual
    expected_hashes[f"ao_simulation_data/{RESOURCE_MANIFEST.name}"] = hashlib.sha256(
        RESOURCE_MANIFEST.read_bytes()
    ).hexdigest()
    logical_names = [name for name in names if name != "__init__.py"]
    logical_names.append(RESOURCE_MANIFEST.name)
    return historical_manifest, logical_names, expected_hashes


def _assert_wheel_layout(
    wheel: Path,
    *,
    logical_resources: list[str],
    expected_resource_hashes: dict[str, str],
) -> dict[str, bytes]:
    members = _wheel_members(wheel)
    expected_resources = set(expected_resource_hashes)
    expected_canonical_resources = {
        name.replace("ao_simulation_data/", "shwfs_ao/resources/", 1)
        for name in expected_resources
    }
    expected_package_code = {
        "shwfs_ao/__init__.py",
        "shwfs_ao/backends/__init__.py",
        "shwfs_ao/backends/native/__init__.py",
        "shwfs_ao/backends/native/atmosphere.py",
        "shwfs_ao/backends/native/dm.py",
        "shwfs_ao/backends/native/factory.py",
        "shwfs_ao/backends/native/modes.py",
        "shwfs_ao/backends/native/propagation.py",
        "shwfs_ao/backends/native/shwfs.py",
        "shwfs_ao/calibration/__init__.py",
        "shwfs_ao/calibration/diagnostics.py",
        "shwfs_ao/calibration/interaction.py",
        "shwfs_ao/calibration/reconstructors.py",
        "shwfs_ao/control/__init__.py",
        "shwfs_ao/control/command_mapping.py",
        "shwfs_ao/control/config.py",
        "shwfs_ao/control/controller.py",
        "shwfs_ao/control/history.py",
        "shwfs_ao/control/loop.py",
        "shwfs_ao/control/sweeps.py",
        "shwfs_ao/core/__init__.py",
        "shwfs_ao/core/geometry.py",
        "shwfs_ao/core/hashing.py",
        "shwfs_ao/core/protocols.py",
        "shwfs_ao/core/provenance.py",
        "shwfs_ao/core/random.py",
        "shwfs_ao/core/types.py",
        "shwfs_ao/core/wavefront.py",
        "shwfs_ao/detector/__init__.py",
        "shwfs_ao/detector/centroid.py",
        "shwfs_ao/detector/config.py",
        "shwfs_ao/detector/effects.py",
        "shwfs_ao/detector/random.py",
        "shwfs_ao/detector/validity.py",
        "shwfs_ao/dm/__init__.py",
        "shwfs_ao/dm/config.py",
        "shwfs_ao/dm/model.py",
        "shwfs_ao/experimental/__init__.py",
        "shwfs_ao/experimental/pwfs.py",
        "shwfs_ao/experiments/__init__.py",
        "shwfs_ao/experiments/error_budget.py",
        "shwfs_ao/experiments/public_data_conditioned.py",
        "shwfs_ao/experiments/scao.py",
        "shwfs_ao/io/__init__.py",
        "shwfs_ao/io/artifacts.py",
        "shwfs_ao/io/configs.py",
        "shwfs_ao/io/public_data.py",
        "shwfs_ao/io/resources.py",
        "shwfs_ao/legacy/__init__.py",
        "shwfs_ao/legacy/_control_adapters.py",
        "shwfs_ao/legacy/_interaction_adapters.py",
        "shwfs_ao/legacy/_reconstruction_adapters.py",
        *(f"shwfs_ao/legacy/{name}.py" for name in SHIM_MODULES),
        "shwfs_ao/science/__init__.py",
        "shwfs_ao/science/bandpass.py",
        "shwfs_ao/science/metrics.py",
        "shwfs_ao/science/propagation.py",
        "shwfs_ao/wfs/__init__.py",
        "shwfs_ao/wfs/shack_hartmann/__init__.py",
        "shwfs_ao/wfs/shack_hartmann/calibration.py",
        "shwfs_ao/wfs/shack_hartmann/geometric.py",
        "shwfs_ao/wfs/shack_hartmann/geometry.py",
        "shwfs_ao/wfs/shack_hartmann/measurement.py",
        "shwfs_ao/wfs/shack_hartmann/optics.py",
        *expected_canonical_resources,
    }
    expected_shims = {f"{name}.py" for name in SHIM_MODULES}

    assert {name for name in members if name.startswith("ao_simulation_data/")} == expected_resources
    assert {name for name in members if name.startswith("shwfs_ao/")} == expected_package_code
    assert expected_shims <= members
    assert any(name.endswith(".dist-info/licenses/LICENSE") for name in members)
    assert any(name.endswith(".dist-info/licenses/DATA_LICENSES.md") for name in members)

    payloads = _wheel_payloads(wheel, "ao_simulation_data/")
    canonical_payloads = _wheel_payloads(wheel, "shwfs_ao/resources/")
    for name, expected_hash in expected_resource_hashes.items():
        assert hashlib.sha256(payloads[name]).hexdigest() == expected_hash
        canonical_name = name.replace(
            "ao_simulation_data/", "shwfs_ao/resources/", 1
        )
        assert canonical_payloads[canonical_name] == payloads[name]
    return {**payloads, **canonical_payloads}


def _install_and_smoke(
    wheel: Path,
    *,
    site_dir: Path,
    expected_path: Path,
    work_dir: Path,
) -> str:
    site_dir.mkdir()
    _run(
        "-m",
        "pip",
        "install",
        "--no-deps",
        "--no-compile",
        "--target",
        str(site_dir),
        str(wheel),
        cwd=work_dir,
    )

    smoke_code = textwrap.dedent(
        """
        import contextlib
        import hashlib
        import importlib
        import importlib.metadata as metadata
        import importlib.resources as resources
        import json
        import numpy as np
        import pathlib
        import sys
        import warnings

        site = pathlib.Path(sys.argv[1]).resolve()
        expected = json.loads(pathlib.Path(sys.argv[2]).read_text(encoding="utf-8"))
        sys.path.insert(0, str(site))

        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            package = importlib.import_module("shwfs_ao")
            backends_package = importlib.import_module("shwfs_ao.backends")
            native_package = importlib.import_module("shwfs_ao.backends.native")
            native_component_modules = {
                "shwfs_ao.backends.native.atmosphere",
                "shwfs_ao.backends.native.dm",
                "shwfs_ao.backends.native.factory",
                "shwfs_ao.backends.native.modes",
                "shwfs_ao.backends.native.propagation",
                "shwfs_ao.backends.native.shwfs",
            }
            assert native_component_modules.isdisjoint(sys.modules)
            assert "NativeSciencePropagator" not in vars(native_package)
            native_atmosphere = importlib.import_module(
                "shwfs_ao.backends.native.atmosphere"
            )
            native_propagation = importlib.import_module(
                "shwfs_ao.backends.native.propagation"
            )
            native_dm = importlib.import_module("shwfs_ao.backends.native.dm")
            native_factory = importlib.import_module(
                "shwfs_ao.backends.native.factory"
            )
            native_modes = importlib.import_module("shwfs_ao.backends.native.modes")
            native_shwfs = importlib.import_module("shwfs_ao.backends.native.shwfs")
            calibration_package = importlib.import_module("shwfs_ao.calibration")
            calibration_diagnostics = importlib.import_module(
                "shwfs_ao.calibration.diagnostics"
            )
            calibration_interaction = importlib.import_module(
                "shwfs_ao.calibration.interaction"
            )
            calibration_reconstructors = importlib.import_module(
                "shwfs_ao.calibration.reconstructors"
            )
            control_package = importlib.import_module("shwfs_ao.control")
            control_command_mapping = importlib.import_module(
                "shwfs_ao.control.command_mapping"
            )
            control_config = importlib.import_module("shwfs_ao.control.config")
            control_controller = importlib.import_module(
                "shwfs_ao.control.controller"
            )
            control_history = importlib.import_module("shwfs_ao.control.history")
            control_loop = importlib.import_module("shwfs_ao.control.loop")
            control_sweeps = importlib.import_module("shwfs_ao.control.sweeps")
            core_package = importlib.import_module("shwfs_ao.core")
            core_geometry = importlib.import_module("shwfs_ao.core.geometry")
            hashing = importlib.import_module("shwfs_ao.core.hashing")
            protocols = importlib.import_module("shwfs_ao.core.protocols")
            provenance = importlib.import_module("shwfs_ao.core.provenance")
            random_streams = importlib.import_module("shwfs_ao.core.random")
            result_types = importlib.import_module("shwfs_ao.core.types")
            wavefront = importlib.import_module("shwfs_ao.core.wavefront")
            detector_package = importlib.import_module("shwfs_ao.detector")
            detector_centroid = importlib.import_module("shwfs_ao.detector.centroid")
            detector_config = importlib.import_module("shwfs_ao.detector.config")
            detector_effects = importlib.import_module("shwfs_ao.detector.effects")
            detector_random = importlib.import_module("shwfs_ao.detector.random")
            detector_validity = importlib.import_module("shwfs_ao.detector.validity")
            dm_package = importlib.import_module("shwfs_ao.dm")
            dm_config = importlib.import_module("shwfs_ao.dm.config")
            dm_model = importlib.import_module("shwfs_ao.dm.model")
            experimental_package = importlib.import_module("shwfs_ao.experimental")
            experimental_pwfs = importlib.import_module("shwfs_ao.experimental.pwfs")
            experiments_package = importlib.import_module("shwfs_ao.experiments")
            experiments_error_budget = importlib.import_module(
                "shwfs_ao.experiments.error_budget"
            )
            experiments_public_data = importlib.import_module(
                "shwfs_ao.experiments.public_data_conditioned"
            )
            experiments_scao = importlib.import_module("shwfs_ao.experiments.scao")
            io_package = importlib.import_module("shwfs_ao.io")
            configs = importlib.import_module("shwfs_ao.io.configs")
            public_data = importlib.import_module("shwfs_ao.io.public_data")
            legacy_package = importlib.import_module("shwfs_ao.legacy")
            science_package = importlib.import_module("shwfs_ao.science")
            science_bandpass = importlib.import_module("shwfs_ao.science.bandpass")
            science_propagation = importlib.import_module(
                "shwfs_ao.science.propagation"
            )
            science_metrics = importlib.import_module("shwfs_ao.science.metrics")
            wfs_package = importlib.import_module("shwfs_ao.wfs")
            shack_hartmann = importlib.import_module("shwfs_ao.wfs.shack_hartmann")
            shwfs_geometry = importlib.import_module(
                "shwfs_ao.wfs.shack_hartmann.geometry"
            )
            shwfs_optics = importlib.import_module(
                "shwfs_ao.wfs.shack_hartmann.optics"
            )
            shwfs_calibration = importlib.import_module(
                "shwfs_ao.wfs.shack_hartmann.calibration"
            )
            shwfs_measurement = importlib.import_module(
                "shwfs_ao.wfs.shack_hartmann.measurement"
            )
            shwfs_geometric = importlib.import_module(
                "shwfs_ao.wfs.shack_hartmann.geometric"
            )
            shims = [importlib.import_module(name) for name in expected["modules"]]
            implementations = [
                importlib.import_module(f"shwfs_ao.legacy.{name}")
                for name in expected["modules"]
            ]
        assert caught == [], [(str(item.message), item.category.__name__) for item in caught]

        installed_modules = [
            package,
            backends_package,
            native_package,
            native_atmosphere,
            native_propagation,
            native_dm,
            native_factory,
            native_modes,
            native_shwfs,
            calibration_package,
            calibration_diagnostics,
            calibration_interaction,
            calibration_reconstructors,
            control_package,
            control_command_mapping,
            control_config,
            control_controller,
            control_history,
            control_loop,
            control_sweeps,
            core_package,
            core_geometry,
            hashing,
            protocols,
            provenance,
            random_streams,
            result_types,
            wavefront,
            detector_package,
            detector_centroid,
            detector_config,
            detector_effects,
            detector_random,
            detector_validity,
            dm_package,
            dm_config,
            dm_model,
            experimental_package,
            experimental_pwfs,
            experiments_package,
            experiments_error_budget,
            experiments_public_data,
            experiments_scao,
            io_package,
            configs,
            public_data,
            legacy_package,
            science_package,
            science_bandpass,
            science_propagation,
            science_metrics,
            wfs_package,
            shack_hartmann,
            shwfs_geometry,
            shwfs_optics,
            shwfs_calibration,
            shwfs_measurement,
            shwfs_geometric,
            *shims,
            *implementations,
        ]
        assert all(
            pathlib.Path(module.__file__).resolve().is_relative_to(site)
            for module in installed_modules
        )
        assert package.__version__ == metadata.version(expected["distribution"])
        assert package.__all__ == ("__version__",)
        assert core_package.__all__ == tuple(expected["core_exports"])
        assert core_geometry.__all__ == tuple(expected["geometry_exports"])
        assert hashing.__all__ == tuple(expected["hashing_exports"])
        assert protocols.__all__ == tuple(expected["protocol_exports"])
        assert provenance.__all__ == tuple(expected["provenance_exports"])
        assert random_streams.__all__ == tuple(expected["random_exports"])
        assert result_types.__all__ == tuple(expected["type_exports"])
        assert wavefront.__all__ == tuple(expected["wavefront_exports"])
        assert backends_package.__all__ == ("native",)
        assert native_package.__all__ == tuple(expected["native_exports"])
        assert native_atmosphere.__all__ == tuple(
            expected["native_atmosphere_exports"]
        )
        assert native_propagation.__all__ == tuple(
            expected["native_propagation_exports"]
        )
        assert native_dm.__all__ == tuple(expected["native_dm_exports"])
        assert native_factory.__all__ == tuple(expected["native_factory_exports"])
        assert native_modes.__all__ == tuple(expected["native_modes_exports"])
        assert native_shwfs.__all__ == tuple(expected["native_shwfs_exports"])
        assert calibration_package.__all__ == tuple(expected["calibration_exports"])
        assert calibration_diagnostics.__all__ == tuple(
            expected["calibration_diagnostics_exports"]
        )
        assert calibration_interaction.__all__ == tuple(
            expected["calibration_interaction_exports"]
        )
        assert calibration_reconstructors.__all__ == tuple(
            expected["calibration_reconstructor_exports"]
        )
        assert control_package.__all__ == tuple(expected["control_exports"])
        assert control_command_mapping.__all__ == tuple(
            expected["control_command_mapping_exports"]
        )
        assert control_config.__all__ == tuple(expected["control_config_exports"])
        assert control_controller.__all__ == tuple(
            expected["control_controller_exports"]
        )
        assert control_history.__all__ == tuple(
            expected["control_history_exports"]
        )
        assert control_loop.__all__ == tuple(expected["control_loop_exports"])
        assert control_sweeps.__all__ == tuple(expected["control_sweep_exports"])
        assert science_package.__all__ == tuple(expected["science_exports"])
        assert science_bandpass.__all__ == tuple(
            expected["science_bandpass_exports"]
        )
        assert science_propagation.__all__ == tuple(
            expected["science_propagation_exports"]
        )
        assert science_metrics.__all__ == tuple(
            expected["science_metrics_exports"]
        )
        assert dm_package.__all__ == tuple(expected["dm_exports"])
        assert dm_config.__all__ == tuple(expected["dm_config_exports"])
        assert dm_model.__all__ == tuple(expected["dm_model_exports"])
        assert detector_package.__all__ == tuple(expected["detector_exports"])
        assert detector_config.__all__ == tuple(expected["detector_config_exports"])
        assert detector_random.__all__ == tuple(expected["detector_random_exports"])
        assert detector_effects.__all__ == tuple(expected["detector_effects_exports"])
        assert detector_centroid.__all__ == tuple(expected["detector_centroid_exports"])
        assert detector_validity.__all__ == tuple(expected["detector_validity_exports"])
        assert experimental_package.__all__ == ()
        assert experimental_pwfs.__all__ == tuple(expected["pwfs_exports"])
        assert experiments_package.__all__ == tuple(expected["experiment_exports"])
        assert experiments_error_budget.__all__ == tuple(
            expected["error_budget_exports"]
        )
        assert experiments_public_data.__all__ == tuple(
            expected["public_data_conditioned_exports"]
        )
        assert experiments_scao.__all__ == tuple(expected["scao_exports"])
        assert configs.__all__ == tuple(expected["config_exports"])
        assert public_data.__all__ == tuple(expected["public_data_exports"])
        assert io_package.__all__ == tuple(expected["io_exports"])
        assert wfs_package.__all__ == tuple(expected["shack_hartmann_exports"])
        assert shack_hartmann.__all__ == tuple(expected["shack_hartmann_exports"])
        assert shwfs_geometry.__all__ == tuple(expected["shwfs_geometry_exports"])
        assert shwfs_optics.__all__ == tuple(expected["shwfs_optics_exports"])
        assert shwfs_calibration.__all__ == tuple(
            expected["shwfs_calibration_exports"]
        )
        assert shwfs_measurement.__all__ == tuple(
            expected["shwfs_measurement_exports"]
        )
        assert shwfs_geometric.__all__ == tuple(expected["shwfs_geometric_exports"])
        assert all(
            getattr(core_package, name) is getattr(wavefront, name)
            for name in expected["wavefront_exports"]
        )
        assert all(
            getattr(core_package, name) is getattr(provenance, name)
            for name in expected["provenance_exports"]
        )
        assert all(
            getattr(core_package, name) is getattr(core_geometry, name)
            for name in expected["geometry_exports"]
        )
        for module, export_key in (
            (result_types, "type_exports"),
            (protocols, "protocol_exports"),
            (random_streams, "random_exports"),
            (hashing, "hashing_exports"),
        ):
            assert all(
                getattr(core_package, name) is getattr(module, name)
                for name in expected[export_key]
            )
        assert all(
            getattr(native_package, name) is getattr(native_atmosphere, name)
            for name in expected["native_atmosphere_exports"]
        )
        assert all(
            getattr(native_package, name) is getattr(native_propagation, name)
            for name in expected["native_propagation_exports"]
        )
        assert all(
            getattr(native_package, name) is getattr(native_shwfs, name)
            for name in expected["native_shwfs_exports"]
        )
        assert all(
            getattr(native_package, name) is getattr(native_dm, name)
            for name in expected["native_dm_exports"]
        )
        assert all(
            getattr(native_package, name) is getattr(native_modes, name)
            for name in expected["native_modes_exports"]
        )
        assert all(
            getattr(calibration_package, name) is getattr(calibration_diagnostics, name)
            for name in expected["calibration_diagnostics_exports"]
        )
        assert all(
            getattr(calibration_package, name) is getattr(calibration_interaction, name)
            for name in expected["calibration_interaction_exports"]
        )
        assert all(
            getattr(calibration_package, name)
            is getattr(calibration_reconstructors, name)
            for name in expected["calibration_reconstructor_exports"]
        )
        for module, export_key in (
            (control_config, "control_config_exports"),
            (control_command_mapping, "control_command_mapping_exports"),
            (control_controller, "control_controller_exports"),
            (control_history, "control_history_exports"),
            (control_loop, "control_loop_exports"),
            (control_sweeps, "control_sweep_exports"),
        ):
            assert all(
                getattr(control_package, name) is getattr(module, name)
                for name in expected[export_key]
            )
        for module, export_key in (
            (science_bandpass, "science_bandpass_exports"),
            (science_propagation, "science_propagation_exports"),
            (science_metrics, "science_metrics_exports"),
        ):
            assert all(
                getattr(science_package, name) is getattr(module, name)
                for name in expected[export_key]
            )
        assert all(
            getattr(dm_package, name) is getattr(dm_config, name)
            for name in expected["dm_config_exports"]
        )
        assert all(
            getattr(dm_package, name) is getattr(dm_model, name)
            for name in expected["dm_model_exports"]
        )
        assert dm_package.DmConfig is dm_package.DMConfig
        assert dm_package.build_deformable_mirror is dm_package.build_native_deformable_mirror
        assert dm_model.DmCommandVector is result_types.DmCommandVector
        assert dm_model.DmSynthesisResult is result_types.DmSynthesisResult
        assert all(
            getattr(wfs_package, name) is getattr(shack_hartmann, name)
            for name in expected["shack_hartmann_exports"]
        )
        for module, export_key in (
            (shwfs_geometry, "shwfs_geometry_exports"),
            (shwfs_optics, "shwfs_optics_exports"),
            (shwfs_calibration, "shwfs_calibration_exports"),
            (shwfs_measurement, "shwfs_measurement_exports"),
            (shwfs_geometric, "shwfs_geometric_exports"),
        ):
            assert all(
                getattr(shack_hartmann, name) is getattr(module, name)
                for name in expected[export_key]
            )
        for module, export_key in (
            (detector_config, "detector_config_exports"),
            (detector_random, "detector_random_exports"),
            (detector_effects, "detector_effects_exports"),
            (detector_centroid, "detector_centroid_exports"),
            (detector_validity, "detector_validity_exports"),
        ):
            assert all(
                getattr(detector_package, name) is getattr(module, name)
                for name in expected[export_key]
                if name in expected["detector_exports"]
            )
        assert detector_effects.DetectorFrame is result_types.DetectorFrame
        assert detector_validity.DetectorConfig is detector_config.DetectorConfig
        assert public_data.Provenance is provenance.Provenance
        assert public_data.ALLOWED_SOURCE_CLASSES is provenance.ALLOWED_SOURCE_CLASSES
        assert all(
            getattr(io_package, name) is getattr(configs, name)
            for name in expected["config_exports"]
        )
        assert all(
            getattr(io_package, name) is getattr(public_data, name)
            for name in expected["public_data_exports"]
        )
        for module, export_key in (
            (experiments_error_budget, "error_budget_exports"),
            (experiments_public_data, "public_data_conditioned_exports"),
            (experiments_scao, "scao_exports"),
        ):
            assert all(
                getattr(experiments_package, name) is getattr(module, name)
                for name in expected[export_key]
            )

        pupil = core_geometry.build_pupil_geometry(
            telescope_diameter_m=2.0,
            pupil_shape=(12, 12),
        )
        residual_opd_m = np.where(pupil.pupil_mask, 0.0, np.nan)
        native_psf = science_propagation.monochromatic_psf(
            residual_opd_m,
            pupil,
            1.65e-6,
            backend="native",
            sampling=science_propagation.PsfSampling(pad_factor=2),
        )
        assert isinstance(native_psf, result_types.PsfResult)
        assert native_psf.backend_name == "native"
        assert native_psf.intensity.shape == (24, 24)
        assert np.isclose(np.sum(native_psf.intensity), 1.0)
        assert np.all(np.diff(native_psf.x_angle_rad) > 0.0)
        assert np.all(np.diff(native_psf.y_angle_rad) > 0.0)
        assert (
            science_metrics.peak_strehl_from_discrete_flux(
                native_psf,
                native_psf,
            )
            == 1.0
        )
        assert (
            science_metrics.marechal_strehl_from_opd(
                residual_opd_m,
                pupil.pupil_mask,
                native_psf.wavelength_m,
            )
            == 1.0
        )

        for shim, implementation, record in zip(
            shims, implementations, expected["public_api"]
        ):
            # The AO-REF-000 inventory was recorded on Python 3.14.  The future
            # feature named ``annotations`` is public there but absent on some
            # older supported interpreters, so availability is determined from
            # the relocated implementation on the interpreter under test.
            names = tuple(
                name
                for name in record["runtime_public_names"]
                if hasattr(implementation, name)
            )
            assert isinstance(shim.__all__, tuple)
            assert len(shim.__all__) == len(set(shim.__all__))
            assert set(shim.__all__) == set(names)
            assert {
                name for name in vars(shim) if not name.startswith("_")
            } == set(names)
            assert all(
                getattr(shim, name) is getattr(implementation, name)
                for name in names
            )
            star_namespace = {}
            exec(f"from {record['name']} import *", star_namespace)
            assert {
                name for name in star_namespace if not name.startswith("_")
            } == set(names)

        data_index = expected["modules"].index("data_sources")
        assert shims[data_index].Provenance is provenance.Provenance
        assert implementations[data_index].Provenance is provenance.Provenance
        assert (
            implementations[data_index].ALLOWED_SOURCE_CLASSES
            is provenance.ALLOWED_SOURCE_CLASSES
        )
        hashing_index = expected["modules"].index("config_hashing")
        assert (
            implementations[hashing_index].stable_array_descriptor
            is hashing.stable_array_descriptor
        )
        snapshot = public_data.load_eso_asm_snapshot(
            "samples/eso_asm_snapshot_sample.json"
        )
        assert isinstance(snapshot.provenance, provenance.Provenance)

        profile_keys = tuple(
            (str(name), int(version))
            for name, version in expected["system_profiles"]
        )
        assert configs.available_system_profiles() == profile_keys
        profile_configs = tuple(
            configs.load_system_profile(name, version)
            for name, version in profile_keys
        )
        for key, config in zip(profile_keys, profile_configs):
            assert (config.profile.profile_name, config.profile.profile_version) == key
            record = configs.system_config_to_mapping(config)
            restored = configs.system_config_from_mapping(record)
            assert restored == config
            assert restored.config_hash == config.config_hash
            assert dict(restored.component_config_hashes) == dict(
                config.component_config_hashes
            )
            assert len(config.config_hash) == 64
            assert all(
                len(value) == 64
                for value in config.component_config_hashes.values()
            )
        two_m_profiles = profile_configs[:3]
        assert len({config.config_hash for config in two_m_profiles}) == 3
        assert len(
            {config.observing_conditions_hash for config in two_m_profiles}
        ) == 1
        high_order = profile_configs[3]
        assert high_order.telescope_diameter_m == 10.0
        assert high_order.pupil_pixels == 384
        assert high_order.lenslets_across == 48
        assert high_order.actuators_across == 49
        assert high_order.wfs_model == "geometric"

        assert native_factory.NATIVE_SCAO_COMPONENT_FACTORY.backend_name == "native"
        installed_system = experiments_scao.build_scao_system(profile_configs[0])
        assert installed_system.config_hash == profile_configs[0].config_hash
        assert all(len(value) == 64 for value in installed_system.component_hashes.values())

        data_package = importlib.import_module("ao_simulation_data")
        assert pathlib.Path(data_package.__file__).resolve().is_relative_to(site)
        data_schemas = importlib.import_module("ao_simulation_data.schemas")
        assert pathlib.Path(data_schemas.__file__).resolve().is_relative_to(site)
        canonical_package = importlib.import_module("shwfs_ao.resources")
        assert pathlib.Path(canonical_package.__file__).resolve().is_relative_to(site)
        canonical_schemas = importlib.import_module("shwfs_ao.resources.schemas")
        assert pathlib.Path(canonical_schemas.__file__).resolve().is_relative_to(site)
        root = resources.files("ao_simulation_data")
        canonical_root = resources.files("shwfs_ao.resources")
        for name, expected_hash in expected["resource_hashes"].items():
            logical_name = name.removeprefix("ao_simulation_data/")
            payload = root.joinpath(*logical_name.split("/")).read_bytes()
            assert hashlib.sha256(payload).hexdigest() == expected_hash
            assert canonical_root.joinpath(*logical_name.split("/")).read_bytes() == payload

        adapter = importlib.import_module("runtime_resources")
        with contextlib.ExitStack() as stack:
            for logical_name in expected["logical_resources"]:
                expected_hash = expected["resource_hashes"][
                    "ao_simulation_data/" + logical_name
                ]
                for alias in (logical_name, "data/" + logical_name):
                    handle = stack.enter_context(
                        adapter.open_text_resource(alias, encoding="utf-8", newline="")
                    )
                    assert hashlib.sha256(
                        handle.read().encode("utf-8")
                    ).hexdigest() == expected_hash

        print(
            f"installed-package-smoke-ok:{len(shims)}:"
            f"{len(expected['logical_resources'])}"
        )
        """
    )
    env = os.environ.copy()
    env.pop("PYTHONPATH", None)
    env["MPLCONFIGDIR"] = str(work_dir / "mpl")
    result = subprocess.run(
        [sys.executable, "-I", "-c", smoke_code, str(site_dir), str(expected_path)],
        cwd=work_dir,
        env=env,
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def test_direct_wheel_and_sdist_wheel_have_identical_installed_contract(tmp_path):
    manifest, logical_resources, expected_resource_hashes = _resource_contract()
    assert [record["name"] for record in manifest["public_api"]["modules"]] == list(
        SHIM_MODULES
    )

    direct_wheel = _build_direct_wheel(tmp_path / "direct-wheel")
    sdist, sdist_wheel = _build_sdist_and_wheel(
        tmp_path / "sdist", tmp_path / "sdist-wheel"
    )

    direct_resources = _assert_wheel_layout(
        direct_wheel,
        logical_resources=logical_resources,
        expected_resource_hashes=expected_resource_hashes,
    )
    sdist_resources = _assert_wheel_layout(
        sdist_wheel,
        logical_resources=logical_resources,
        expected_resource_hashes=expected_resource_hashes,
    )
    assert direct_resources == sdist_resources

    sdist_members = _sdist_members(sdist)
    expected_sdist_members = {
        "MANIFEST.in",
        "pyproject.toml",
        "README.md",
        "LICENSE",
        "DATA_LICENSES.md",
        "build_support/__init__.py",
        "build_support/resource_alias.py",
        *(
            "src/shwfs_ao/resources/"
            + name.removeprefix("ao_simulation_data/")
            for name in expected_resource_hashes
        ),
        "src/shwfs_ao/__init__.py",
        "src/shwfs_ao/backends/__init__.py",
        "src/shwfs_ao/backends/native/__init__.py",
        "src/shwfs_ao/backends/native/atmosphere.py",
        "src/shwfs_ao/backends/native/dm.py",
        "src/shwfs_ao/backends/native/factory.py",
        "src/shwfs_ao/backends/native/modes.py",
        "src/shwfs_ao/backends/native/propagation.py",
        "src/shwfs_ao/backends/native/shwfs.py",
        "src/shwfs_ao/calibration/__init__.py",
        "src/shwfs_ao/calibration/diagnostics.py",
        "src/shwfs_ao/calibration/interaction.py",
        "src/shwfs_ao/calibration/reconstructors.py",
        "src/shwfs_ao/control/__init__.py",
        "src/shwfs_ao/control/command_mapping.py",
        "src/shwfs_ao/control/config.py",
        "src/shwfs_ao/control/controller.py",
        "src/shwfs_ao/control/history.py",
        "src/shwfs_ao/control/loop.py",
        "src/shwfs_ao/control/sweeps.py",
        "src/shwfs_ao/core/__init__.py",
        "src/shwfs_ao/core/geometry.py",
        "src/shwfs_ao/core/hashing.py",
        "src/shwfs_ao/core/protocols.py",
        "src/shwfs_ao/core/provenance.py",
        "src/shwfs_ao/core/random.py",
        "src/shwfs_ao/core/types.py",
        "src/shwfs_ao/core/wavefront.py",
        "src/shwfs_ao/detector/__init__.py",
        "src/shwfs_ao/detector/centroid.py",
        "src/shwfs_ao/detector/config.py",
        "src/shwfs_ao/detector/effects.py",
        "src/shwfs_ao/detector/random.py",
        "src/shwfs_ao/detector/validity.py",
        "src/shwfs_ao/dm/__init__.py",
        "src/shwfs_ao/dm/config.py",
        "src/shwfs_ao/dm/model.py",
        "src/shwfs_ao/experimental/__init__.py",
        "src/shwfs_ao/experimental/pwfs.py",
        "src/shwfs_ao/experiments/__init__.py",
        "src/shwfs_ao/experiments/error_budget.py",
        "src/shwfs_ao/experiments/public_data_conditioned.py",
        "src/shwfs_ao/experiments/scao.py",
        "src/shwfs_ao/io/__init__.py",
        "src/shwfs_ao/io/artifacts.py",
        "src/shwfs_ao/io/configs.py",
        "src/shwfs_ao/io/public_data.py",
        "src/shwfs_ao/io/resources.py",
        "src/shwfs_ao/legacy/__init__.py",
        "src/shwfs_ao/legacy/_control_adapters.py",
        "src/shwfs_ao/legacy/_interaction_adapters.py",
        "src/shwfs_ao/legacy/_reconstruction_adapters.py",
        *(f"src/shwfs_ao/legacy/{name}.py" for name in SHIM_MODULES),
        "src/shwfs_ao/science/__init__.py",
        "src/shwfs_ao/science/bandpass.py",
        "src/shwfs_ao/science/metrics.py",
        "src/shwfs_ao/science/propagation.py",
        "src/shwfs_ao/wfs/__init__.py",
        "src/shwfs_ao/wfs/shack_hartmann/__init__.py",
        "src/shwfs_ao/wfs/shack_hartmann/calibration.py",
        "src/shwfs_ao/wfs/shack_hartmann/geometric.py",
        "src/shwfs_ao/wfs/shack_hartmann/geometry.py",
        "src/shwfs_ao/wfs/shack_hartmann/measurement.py",
        "src/shwfs_ao/wfs/shack_hartmann/optics.py",
        *(f"src/{name}.py" for name in SHIM_MODULES),
    }
    assert expected_sdist_members <= sdist_members
    assert not any(name.startswith("data/") for name in sdist_members)
    assert not any(name.startswith("src/ao_simulation_data/") for name in sdist_members)

    expected_path = tmp_path / "expected.json"
    expected_path.write_text(
        json.dumps(
            {
                "distribution": DIST_NAME,
                "core_exports": list(CORE_EXPORTS),
                "geometry_exports": list(GEOMETRY_EXPORTS),
                "hashing_exports": list(HASHING_EXPORTS),
                "protocol_exports": list(PROTOCOL_EXPORTS),
                "provenance_exports": list(PROVENANCE_EXPORTS),
                "random_exports": list(RANDOM_EXPORTS),
                "type_exports": list(TYPE_EXPORTS),
                "wavefront_exports": list(WAVEFRONT_EXPORTS),
                "native_atmosphere_exports": list(NATIVE_ATMOSPHERE_EXPORTS),
                "native_propagation_exports": list(NATIVE_PROPAGATION_EXPORTS),
                "native_dm_exports": list(NATIVE_DM_EXPORTS),
                "native_factory_exports": list(NATIVE_FACTORY_EXPORTS),
                "native_modes_exports": list(NATIVE_MODES_EXPORTS),
                "native_shwfs_exports": list(NATIVE_SHWFS_EXPORTS),
                "native_exports": list(NATIVE_EXPORTS),
                "calibration_diagnostics_exports": list(
                    CALIBRATION_DIAGNOSTICS_EXPORTS
                ),
                "calibration_interaction_exports": list(
                    CALIBRATION_INTERACTION_EXPORTS
                ),
                "calibration_reconstructor_exports": list(
                    CALIBRATION_RECONSTRUCTOR_EXPORTS
                ),
                "calibration_exports": list(CALIBRATION_EXPORTS),
                "control_config_exports": list(CONTROL_CONFIG_EXPORTS),
                "control_command_mapping_exports": list(
                    CONTROL_COMMAND_MAPPING_EXPORTS
                ),
                "control_controller_exports": list(CONTROL_CONTROLLER_EXPORTS),
                "control_history_exports": list(CONTROL_HISTORY_EXPORTS),
                "control_loop_exports": list(CONTROL_LOOP_EXPORTS),
                "control_sweep_exports": list(CONTROL_SWEEP_EXPORTS),
                "control_exports": list(CONTROL_EXPORTS),
                "science_bandpass_exports": list(SCIENCE_BANDPASS_EXPORTS),
                "science_propagation_exports": list(
                    SCIENCE_PROPAGATION_EXPORTS
                ),
                "science_metrics_exports": list(SCIENCE_METRICS_EXPORTS),
                "science_exports": list(SCIENCE_EXPORTS),
                "dm_exports": list(DM_EXPORTS),
                "dm_config_exports": list(DM_CONFIG_EXPORTS),
                "dm_model_exports": list(DM_MODEL_EXPORTS),
                "shwfs_geometry_exports": list(SHWFS_GEOMETRY_EXPORTS),
                "shwfs_optics_exports": list(SHWFS_OPTICS_EXPORTS),
                "shwfs_calibration_exports": list(SHWFS_CALIBRATION_EXPORTS),
                "shwfs_measurement_exports": list(SHWFS_MEASUREMENT_EXPORTS),
                "shwfs_geometric_exports": list(SHWFS_GEOMETRIC_EXPORTS),
                "shack_hartmann_exports": list(SHACK_HARTMANN_EXPORTS),
                "pwfs_exports": list(PWFS_EXPORTS),
                "detector_exports": list(DETECTOR_EXPORTS),
                "detector_config_exports": list(DETECTOR_CONFIG_EXPORTS),
                "detector_random_exports": list(DETECTOR_RANDOM_EXPORTS),
                "detector_effects_exports": list(DETECTOR_EFFECTS_EXPORTS),
                "detector_centroid_exports": list(DETECTOR_CENTROID_EXPORTS),
                "detector_validity_exports": list(DETECTOR_VALIDITY_EXPORTS),
                "config_exports": list(CONFIG_EXPORTS),
                "public_data_exports": list(PUBLIC_DATA_EXPORTS),
                "io_exports": list(IO_EXPORTS),
                "error_budget_exports": list(ERROR_BUDGET_EXPORTS),
                "public_data_conditioned_exports": list(
                    PUBLIC_DATA_CONDITIONED_EXPORTS
                ),
                "scao_exports": list(SCAO_EXPORTS),
                "experiment_exports": list(EXPERIMENT_EXPORTS),
                "system_profiles": AO_REF_011_SYSTEM_PROFILES,
                "logical_resources": logical_resources,
                "modules": list(SHIM_MODULES),
                "public_api": manifest["public_api"]["modules"],
                "resource_hashes": expected_resource_hashes,
            }
        ),
        encoding="utf-8",
    )
    expected_stdout = f"installed-package-smoke-ok:{len(SHIM_MODULES)}:{len(logical_resources)}"
    assert _install_and_smoke(
        direct_wheel,
        site_dir=tmp_path / "direct-site",
        expected_path=expected_path,
        work_dir=tmp_path,
    ) == expected_stdout
    assert _install_and_smoke(
        sdist_wheel,
        site_dir=tmp_path / "sdist-site",
        expected_path=expected_path,
        work_dir=tmp_path,
    ) == expected_stdout


def test_pep660_editable_install_generates_resource_alias_only_in_environment(
    tmp_path: Path,
) -> None:
    source_alias = ROOT / "src" / "ao_simulation_data"
    assert not source_alias.exists()

    environment = tmp_path / "editable-environment"
    subprocess.run(
        [sys.executable, "-m", "venv", "--system-site-packages", str(environment)],
        cwd=tmp_path,
        check=True,
        capture_output=True,
        text=True,
    )
    if os.name == "nt":
        python = environment / "Scripts" / "python.exe"
    else:
        python = environment / "bin" / "python"
    subprocess.run(
        [
            str(python),
            "-m",
            "pip",
            "install",
            "-e",
            str(ROOT),
            "--no-deps",
            "--no-build-isolation",
            "--no-cache-dir",
        ],
        cwd=tmp_path,
        check=True,
        capture_output=True,
        text=True,
    )

    smoke = textwrap.dedent(
        """
        import hashlib
        import importlib
        import importlib.resources as resources
        import json
        import pathlib
        import sys

        source_root = pathlib.Path(sys.argv[1]).resolve()
        alias = importlib.import_module("ao_simulation_data")
        alias_schemas = importlib.import_module("ao_simulation_data.schemas")
        canonical = importlib.import_module("shwfs_ao.resources")
        schemas = importlib.import_module("shwfs_ao.resources.schemas")
        assert not pathlib.Path(alias.__file__).resolve().is_relative_to(source_root)
        assert not pathlib.Path(alias_schemas.__file__).resolve().is_relative_to(source_root)
        assert pathlib.Path(canonical.__file__).resolve().is_relative_to(source_root)
        assert pathlib.Path(schemas.__file__).resolve().is_relative_to(source_root)

        alias_root = resources.files("ao_simulation_data")
        canonical_root = resources.files("shwfs_ao.resources")
        manifest_payload = alias_root.joinpath("resource_manifest.json").read_bytes()
        assert canonical_root.joinpath("resource_manifest.json").read_bytes() == manifest_payload
        manifest = json.loads(manifest_payload)
        for record in manifest["resources"]:
            parts = record["logical_name"].split("/")
            alias_payload = alias_root.joinpath(*parts).read_bytes()
            canonical_payload = canonical_root.joinpath(*parts).read_bytes()
            assert alias_payload == canonical_payload
            assert hashlib.sha256(alias_payload).hexdigest() == record["sha256"]
        print(f"editable-resource-alias-ok:{len(manifest['resources'])}")
        """
    )
    result = subprocess.run(
        [str(python), "-I", "-c", smoke, str(ROOT)],
        cwd=tmp_path,
        check=True,
        capture_output=True,
        text=True,
    )
    assert result.stdout.strip() == "editable-resource-alias-ok:34"
    assert not source_alias.exists()
