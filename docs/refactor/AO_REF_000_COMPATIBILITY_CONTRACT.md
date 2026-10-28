# AO-REF-000 Compatibility and Regression Contract

Status: implementation freeze, locally green and independently reviewable; exact constrained Python 3.10/3.14 CI evidence is pending, and AO-REF-001 remains gated.

## Scope and authority

This contract freezes the exact current working-tree behavior observed on 2026-07-14 before any file move. It does **not** declare the dirty scientific baselines, CI workflow, constraints, or untracked packaging files accepted. HEAD is `9c4816c094249b49d4f9a1fd182e39ea264252e5`; the pre-ticket tree had 73 status entries and tracked binary diff SHA-256 `20bb3521bed2fbdf4e04e9960638661d5897c84bd8fd9167fbe6ad052ebeb36d`. HEAD has 17 modules and one unconstrained Python 3.11 job; the 19-module/resource and constrained 3.10/3.14 contract described here exists in the current dirty worktree.

The authoritative machine-readable inventory is `data/reference_metrics/refactor_contract_manifest.json`. Array hashes in the component fixture are informational across NumPy/FFT/BLAS versions; portable scalar assertions carry explicit tolerances.

## Evidence summary

| Surface | Observed result |
|---|---|
| Pre-ticket source checkout | CPython 3.14.3; `166 passed` in 233.08 s |
| AO-REF-000 complete suite | `184 passed` in 232.48 s, including 18 new contract/component tests |
| Editable install outside CWD | 19/19 modules imported; resource package resolved to checkout `data/` |
| Pre-ticket non-editable wheel | 19/19 modules imported outside checkout; all 20 package-data resources read; 46 wheel members; licenses present |
| Wheel rebuilt from sdist | Payloads matched direct wheel; isolated suite 165 passed with only the expected `.git` portability failure |
| Local caveats | local dependencies are not the pinned Linux 3.14 set; no local Python 3.10; `python` alias absent; set `MPLCONFIGDIR` under `/tmp` |

## Installed module and AO-REF-001 disposition map

No module defines `__all__`. Therefore the strict current star-import contract is every non-underscore global, including imported helpers. The repository has no star-import consumers, but external consumers are unknown.

| Import | Source | Runtime names | Owned names | Internal dependencies | AO-REF-001 implementation / shim |
|---|---|---:|---:|---|---|
| `ao_closed_loop` | `src/ao_closed_loop.py` | 45 | 20 | config_hashing, data_sources, dm_model, interaction_matrix, phase_screen, psf_tools, reconstruction, shwfs_detector, synthetic_instrument_data | `src/shwfs_ao/legacy/ao_closed_loop.py` / `src/ao_closed_loop.py` |
| `ao_conditions` | `src/ao_conditions.py` | 16 | 10 | data_sources | `src/shwfs_ao/legacy/ao_conditions.py` / `src/ao_conditions.py` |
| `ao_diagnostics` | `src/ao_diagnostics.py` | 33 | 19 | data_sources, dm_model, psf_tools | `src/shwfs_ao/legacy/ao_diagnostics.py` / `src/ao_diagnostics.py` |
| `ao_error_budget` | `src/ao_error_budget.py` | 46 | 18 | ao_closed_loop, ao_diagnostics, config_hashing, data_sources, dm_model, interaction_matrix, synthetic_instrument_data | `src/shwfs_ao/legacy/ao_error_budget.py` / `src/ao_error_budget.py` |
| `ao_integration` | `src/ao_integration.py` | 65 | 18 | ao_closed_loop, ao_diagnostics, ao_error_budget, ao_validation, data_sources, dm_model, interaction_matrix, runtime_resources, synthetic_instrument_data | `src/shwfs_ao/legacy/ao_integration.py` / `src/ao_integration.py` |
| `ao_validation` | `src/ao_validation.py` | 31 | 12 | ao_closed_loop, ao_diagnostics, ao_error_budget, data_sources, dm_model, interaction_matrix, synthetic_instrument_data | `src/shwfs_ao/legacy/ao_validation.py` / `src/ao_validation.py` |
| `atmosphere_profiles` | `src/atmosphere_profiles.py` | 34 | 23 | data_sources, phase_screen | `src/shwfs_ao/legacy/atmosphere_profiles.py` / `src/atmosphere_profiles.py` |
| `config_hashing` | `src/config_hashing.py` | 6 | 1 | none | `src/shwfs_ao/legacy/config_hashing.py` / `src/config_hashing.py` |
| `data_sources` | `src/data_sources.py` | 28 | 20 | runtime_resources | `src/shwfs_ao/legacy/data_sources.py` / `src/data_sources.py` |
| `dm_model` | `src/dm_model.py` | 31 | 20 | data_sources, runtime_resources | `src/shwfs_ao/legacy/dm_model.py` / `src/dm_model.py` |
| `interaction_matrix` | `src/interaction_matrix.py` | 40 | 23 | config_hashing, data_sources, dm_model, synthetic_instrument_data | `src/shwfs_ao/legacy/interaction_matrix.py` / `src/interaction_matrix.py` |
| `phase_screen` | `src/phase_screen.py` | 12 | 10 | none | `src/shwfs_ao/legacy/phase_screen.py` / `src/phase_screen.py` |
| `psf_tools` | `src/psf_tools.py` | 7 | 5 | none | `src/shwfs_ao/legacy/psf_tools.py` / `src/psf_tools.py` |
| `pwfs_forward` | `src/pwfs_forward.py` | 22 | 21 | none | `src/shwfs_ao/legacy/pwfs_forward.py` / `src/pwfs_forward.py` |
| `reconstruction` | `src/reconstruction.py` | 15 | 13 | none | `src/shwfs_ao/legacy/reconstruction.py` / `src/reconstruction.py` |
| `runtime_resources` | `src/runtime_resources.py` | 11 | 5 | none | `src/shwfs_ao/legacy/runtime_resources.py` / `src/runtime_resources.py` |
| `shwfs_detector` | `src/shwfs_detector.py` | 13 | 10 | reconstruction | `src/shwfs_ao/legacy/shwfs_detector.py` / `src/shwfs_detector.py` |
| `synthetic_instrument_data` | `src/synthetic_instrument_data.py` | 35 | 24 | data_sources, reconstruction, shwfs_detector | `src/shwfs_ao/legacy/synthetic_instrument_data.py` / `src/synthetic_instrument_data.py` |
| `zernike` | `src/zernike.py` | 14 | 11 | none | `src/shwfs_ao/legacy/zernike.py` / `src/zernike.py` |

### Exhaustive current exported namespaces

#### `ao_closed_loop`

Frozen non-underscore names (45):

```text
ALLOWED_SOURCE_CLASSES, Any, ClosedLoopError, DEFAULT_CENTROID_VALIDITY, DEFAULT_LOOP_SOURCE_CLASS, DEFAULT_LOOP_SOURCE_NOTE, DMModel, DetectorLoopConfig, DetectorShwfsCalibration, LoopHistory, NM_PER_M, PHASE_TWO_PI, PokeMtxResult, actuator_centers_on_pupil, annotations, build_detector_dm_poke_matrix_from_calibration, build_dm_detector_response_matrix, build_dm_wfs_response_matrix, dataclass, expand_controlled_commands, frozen_flow_shift, frozen_flow_shift_physical, gain_scan, gaussian_influence_functions, hashlib, json, loop_history_summary, math, measure_centroid_shifts, measure_detector_shwfs, measure_slopes, np, reconstruct_dm_delta, reference_centroids, rms, run_closed_loop_ao, run_closed_loop_ao_detector, run_detector_integrator_loop, shifted_atmosphere, stable_array_descriptor, strehl_ratio, synthesize_dm_phase, synthesize_dm_phase_rad, tsvd_reconstruct_commands, vectorize_detector_measurement
```

Module-owned declarations:

- `ClosedLoopError` — class, source line 47
- `DEFAULT_LOOP_SOURCE_CLASS` — constant_or_alias, source line 38
- `DEFAULT_LOOP_SOURCE_NOTE` — constant_or_alias, source line 39
- `DetectorLoopConfig(n_steps: 'int' = 50, gain: 'float' = 0.35, leak: 'float' = 0.0, latency_frames: 'int' = 0, frame_rate_hz: 'float' = 500.0, include_detector_noise: 'bool' = False, seed: 'int' = 1, source_class: 'str' = 'synthetic_assumed', source_note: 'str' = 'Synthetic detector-level integrator loop settings for the 2 m SCAO demonstrator; not measured RTC telemetry.') -> None` — class, source line 52
- `LoopHistory(residual_opd_rms: 'np.ndarray', command_rms_nm: 'np.ndarray', command_l2_norm_nm: 'np.ndarray', valid_centroid_frac: 'np.ndarray', config_hash: 'str', open_loop_opd_rms: 'np.ndarray', pre_update_residual_opd_rms: 'np.ndarray', command_history_nm: 'np.ndarray', delta_command_norm_nm: 'np.ndarray', applied_delta_norm_nm: 'np.ndarray', saturation_fraction: 'np.ndarray', residual_phase_rms_rad: 'np.ndarray', latency_frames: 'int', latency_ms: 'float', gain: 'float', leak: 'float', source_class: 'str', units: 'dict[str, str]') -> None` — class, source line 113
- `NM_PER_M` — constant_or_alias, source line 44
- `PHASE_TWO_PI` — constant_or_alias, source line 43
- `actuator_centers_on_pupil(diameter: 'float' = 1.0, n_actuators: 'int' = 8, include_edge: 'bool' = True) -> 'tuple[np.ndarray, float]'` — function, source line 184
- `build_detector_dm_poke_matrix_from_calibration(*args, **kwargs)` — function, source line 405
- `build_dm_detector_response_matrix(influence_functions: 'np.ndarray', pupil_mask: 'np.ndarray', X: 'np.ndarray', Y: 'np.ndarray', n_lenslets: 'int' = 12, min_fill: 'float' = 0.5, pad_factor: 'int' = 8, threshold_fraction: 'float' = 0.0, subtract_minimum: 'bool' = False, detector_window_size: 'int | None' = None, calibration_amplitude: 'float' = 0.001) -> 'tuple[np.ndarray, np.ndarray, list[np.ndarray], np.ndarray]'` — function, source line 296
- `build_dm_wfs_response_matrix(influence_functions: 'np.ndarray', pupil_mask: 'np.ndarray', X: 'np.ndarray', Y: 'np.ndarray', n_lenslets: 'int' = 12, min_fill: 'float' = 0.5) -> 'tuple[np.ndarray, np.ndarray]'` — function, source line 265
- `gain_scan(gains: 'list[float]', phase0: 'np.ndarray', pupil_mask: 'np.ndarray', X: 'np.ndarray', Y: 'np.ndarray', influence_functions: 'np.ndarray', dm_response_matrix: 'np.ndarray', n_steps: 'int' = 40, wind_shift_per_step: 'tuple[int, int]' = (1, 0), n_lenslets: 'int' = 12, min_fill: 'float' = 0.5, slope_noise_std: 'float' = 0.0, rcond: 'float' = 0.001, command_leak: 'float' = 0.0, seed: 'int' = 1) -> 'dict[float, dict[str, float]]'` — function, source line 799
- `gaussian_influence_functions(X: 'np.ndarray', Y: 'np.ndarray', pupil_mask: 'np.ndarray', centers: 'np.ndarray', pitch: 'float', coupling: 'float' = 0.35, normalize_peak: 'bool' = True) -> 'np.ndarray'` — function, source line 213
- `loop_history_summary(history: 'LoopHistory') -> 'dict[str, Any]'` — function, source line 566
- `reconstruct_dm_delta(slopes: 'np.ndarray', dm_response_matrix: 'np.ndarray', rcond: 'float' = 0.001) -> 'tuple[np.ndarray, np.ndarray, int, np.ndarray]'` — function, source line 380
- `run_closed_loop_ao(phase0: 'np.ndarray', pupil_mask: 'np.ndarray', X: 'np.ndarray', Y: 'np.ndarray', influence_functions: 'np.ndarray', dm_response_matrix: 'np.ndarray', n_steps: 'int' = 40, wind_shift_per_step: 'tuple[int, int]' = (1, 0), gain: 'float' = 0.4, n_lenslets: 'int' = 12, min_fill: 'float' = 0.5, slope_noise_std: 'float' = 0.0, rcond: 'float' = 0.001, command_leak: 'float' = 0.0, compute_strehl: 'bool' = True, pad_factor: 'int' = 4, seed: 'int' = 1) -> 'dict[str, np.ndarray]'` — function, source line 609
- `run_closed_loop_ao_detector(phase0: 'np.ndarray', pupil_mask: 'np.ndarray', X: 'np.ndarray', Y: 'np.ndarray', influence_functions: 'np.ndarray', dm_detector_response_matrix: 'np.ndarray', detector_reference: 'np.ndarray', detector_masks: 'list[np.ndarray]', detector_centers: 'np.ndarray', n_steps: 'int' = 40, vx: 'float' = 10.0, vy: 'float' = 0.0, dt: 'float' = 0.002, delta: 'float' = 0.02, gain: 'float' = 0.3, n_lenslets: 'int' = 12, min_fill: 'float' = 0.5, pad_factor: 'int' = 8, photons: 'float | None' = 10000.0, read_noise_e: 'float' = 1.0, background_e: 'float' = 0.0, threshold_fraction: 'float' = 0.0, subtract_minimum: 'bool' = False, detector_window_size: 'int | None' = None, rcond: 'float' = 0.001, command_leak: 'float' = 0.0, seed: 'int' = 1, compute_strehl: 'bool' = True) -> 'dict[str, np.ndarray]'` — function, source line 691
- `run_detector_integrator_loop(phase_sequence_rad: 'np.ndarray', calibration: 'DetectorShwfsCalibration', dm_model: 'DMModel', poke_result: 'PokeMtxResult', config: 'DetectorLoopConfig | None' = None) -> 'LoopHistory'` — function, source line 417
- `shifted_atmosphere(phase0: 'np.ndarray', pupil_mask: 'np.ndarray', shift_x_pix: 'int' = 0, shift_y_pix: 'int' = 0) -> 'np.ndarray'` — function, source line 592
- `synthesize_dm_phase(commands: 'np.ndarray', influence_functions: 'np.ndarray', pupil_mask: 'np.ndarray', remove_mean: 'bool' = True) -> 'np.ndarray'` — function, source line 242

#### `ao_conditions`

Frozen non-underscore names (16):

```text
ALLOWED_SOURCE_CLASSES, AOConditionError, ARCSEC_PER_RAD, EsoAsmSnapshot, ObservingConditionConfig, REFERENCE_PHASE_AMPLITUDE_NM, REFERENCE_SEEING_ARCSEC, Sequence, annotations, condition_rows, dataclass, default_observing_conditions, math, phase_amplitude_from_seeing, r0_from_seeing_arcsec, theta0_rad_from_arcsec
```

Module-owned declarations:

- `AOConditionError` — class, source line 20
- `ARCSEC_PER_RAD` — constant_or_alias, source line 15
- `ObservingConditionConfig(condition_name: 'str', atmosphere_source: 'str', seeing_arcsec: 'float', r0_500_m: 'float', tau0_s: 'float', theta0_rad: 'float', turbulence_speed_m_s: 'float', photons_per_subap_frame: 'float', photon_source: 'str', read_noise_e: 'float', latency_frames: 'int', stroke_limit_nm: 'float', ncpa_rms_nm: 'float', misregistration_shift_px: 'tuple[float, float]' = (0.0, 0.0), misregistration_rotation_deg: 'float' = 0.0, misregistration_magnification: 'float' = 1.0, misregistration_shear: 'float' = 0.0, exposure_latency_s: 'float' = 0.0, readout_latency_s: 'float' = 0.0, compute_latency_s: 'float' = 0.0, dm_settling_latency_s: 'float' = 0.0, source_class: 'str' = 'synthetic_assumed', source_note: 'str' = 'Synthetic observing-condition preset for Notebook 11.') -> None` — class, source line 25
- `REFERENCE_PHASE_AMPLITUDE_NM` — constant_or_alias, source line 17
- `REFERENCE_SEEING_ARCSEC` — constant_or_alias, source line 16
- `condition_rows(conditions: 'Sequence[ObservingConditionConfig]') -> 'list[dict[str, object]]'` — function, source line 270
- `default_observing_conditions(asm_snapshot: 'EsoAsmSnapshot', catalog_photons_per_subap_frame: 'float', photon_source: 'str') -> 'tuple[ObservingConditionConfig, ...]'` — function, source line 137
- `phase_amplitude_from_seeing(seeing_arcsec: 'float', reference_seeing_arcsec: 'float' = 0.8, reference_phase_amplitude_nm: 'float' = 260.0) -> 'float'` — function, source line 111
- `r0_from_seeing_arcsec(seeing_arcsec: 'float', wavelength_m: 'float' = 5e-07) -> 'float'` — function, source line 124
- `theta0_rad_from_arcsec(theta0_arcsec: 'float') -> 'float'` — function, source line 132

#### `ao_diagnostics`

Frozen non-underscore names (33):

```text
ALLOWED_SOURCE_CLASSES, AODiagnosticsError, ARCSEC_PER_RAD, Any, DEFAULT_DIAGNOSTIC_SOURCE_CLASS, DEFAULT_DIAGNOSTIC_SOURCE_NOTE, DMModel, FilterCurve, Mapping, NM_PER_M, NM_TO_M, PHASE_TWO_PI, ScienceBandpass, SciencePsfMetrics, Sequence, annotations, band_averaged_psf_metrics_from_opd, bandpass_from_filter_curve, compute_psf_from_phase, dataclass, marechal_strehl, math, monochromatic_bandpass, np, phase_for_science_wavelength, phase_rad_to_opd_nm, remove_piston_opd_nm, residual_opd_nm_from_command, science_case_metrics_table, science_metrics_as_dicts, science_psf_metrics_from_opd, synthesize_dm_phase_rad, top_hat_bandpass
```

Module-owned declarations:

- `AODiagnosticsError` — class, source line 35
- `ARCSEC_PER_RAD` — constant_or_alias, source line 32
- `DEFAULT_DIAGNOSTIC_SOURCE_CLASS` — constant_or_alias, source line 24
- `DEFAULT_DIAGNOSTIC_SOURCE_NOTE` — constant_or_alias, source line 25
- `NM_PER_M` — constant_or_alias, source line 31
- `NM_TO_M` — constant_or_alias, source line 30
- `PHASE_TWO_PI` — constant_or_alias, source line 29
- `ScienceBandpass(name: 'str', wavelength_m: 'np.ndarray', transmission: 'np.ndarray', source_class: 'str' = 'synthetic_assumed', source_note: 'str' = 'Synthetic science diagnostic settings for the 2 m AO demonstrator; bandpass fallback is not an on-sky calibration.', filter_id: 'str | None' = None) -> None` — class, source line 40
- `SciencePsfMetrics(case_name: 'str', band_name: 'str', effective_wavelength_m: 'float', opd_rms_nm: 'float', strehl_peak: 'float', strehl_marechal: 'float', marechal_abs_error: 'float', fwhm_px: 'float', fwhm_lambda_over_d: 'float', fwhm_arcsec: 'float', ee50_px: 'float', ee50_lambda_over_d: 'float', ee50_arcsec: 'float', ee80_px: 'float', ee80_lambda_over_d: 'float', ee80_arcsec: 'float', halo_fraction: 'float', halo_inner_lambda_over_d: 'float', source_class: 'str', source_note: 'str') -> None` — class, source line 121
- `band_averaged_psf_metrics_from_opd(opd_nm: 'np.ndarray', pupil_mask: 'np.ndarray', bandpass: 'ScienceBandpass', telescope_diameter_m: 'float', case_name: 'str' = 'case', pad_factor: 'int' = 4, halo_inner_lambda_over_d: 'float' = 3.0) -> 'SciencePsfMetrics'` — function, source line 385
- `bandpass_from_filter_curve(curve: 'FilterCurve', name: 'str | None' = None) -> 'ScienceBandpass'` — function, source line 216
- `monochromatic_bandpass(name: 'str', wavelength_m: 'float', source_class: 'str' = 'synthetic_assumed', source_note: 'str' = 'Synthetic science diagnostic settings for the 2 m AO demonstrator; bandpass fallback is not an on-sky calibration.') -> 'ScienceBandpass'` — function, source line 170
- `phase_rad_to_opd_nm(phase_rad: 'np.ndarray', reference_wavelength_m: 'float', pupil_mask: 'np.ndarray | None' = None, remove_piston: 'bool' = True) -> 'np.ndarray'` — function, source line 229
- `remove_piston_opd_nm(opd_nm: 'np.ndarray', pupil_mask: 'np.ndarray') -> 'np.ndarray'` — function, source line 253
- `residual_opd_nm_from_command(atmosphere_phase_rad: 'np.ndarray', command_nm: 'Sequence[float]', dm_model: 'DMModel', reference_wavelength_m: 'float') -> 'np.ndarray'` — function, source line 268
- `science_case_metrics_table(cases_opd_nm: 'Mapping[str, np.ndarray]', pupil_mask: 'np.ndarray', bandpasses: 'Sequence[ScienceBandpass]', telescope_diameter_m: 'float', pad_factor: 'int' = 4, halo_inner_lambda_over_d: 'float' = 3.0) -> 'tuple[SciencePsfMetrics, ...]'` — function, source line 424
- `science_metrics_as_dicts(metrics: 'Sequence[SciencePsfMetrics]') -> 'tuple[dict[str, float | str], ...]'` — function, source line 457
- `science_psf_metrics_from_opd(opd_nm: 'np.ndarray', pupil_mask: 'np.ndarray', wavelength_m: 'float', telescope_diameter_m: 'float', case_name: 'str' = 'case', band_name: 'str' = 'monochromatic', pad_factor: 'int' = 4, halo_inner_lambda_over_d: 'float' = 3.0, source_class: 'str' = 'synthetic_assumed', source_note: 'str' = 'Synthetic science diagnostic settings for the 2 m AO demonstrator; bandpass fallback is not an on-sky calibration.') -> 'SciencePsfMetrics'` — function, source line 286
- `top_hat_bandpass(name: 'str', wavelength_min_m: 'float', wavelength_max_m: 'float', n_samples: 'int' = 9, source_class: 'str' = 'synthetic_assumed', source_note: 'str' = 'Synthetic science diagnostic settings for the 2 m AO demonstrator; bandpass fallback is not an on-sky calibration.') -> 'ScienceBandpass'` — function, source line 189

#### `ao_error_budget`

Frozen non-underscore names (46):

```text
ALLOWED_SOURCE_CLASSES, AOErrorBudgetError, Any, DEFAULT_H_BAND, DEFAULT_J_BAND, DEFAULT_K_BAND, DEFAULT_SCENARIO_SOURCE_CLASS, DEFAULT_SCENARIO_SOURCE_NOTE, DMConfig, DMModel, DetectorLoopConfig, DetectorShwfsCalibration, LoopHistory, Mapping, NM_PER_M, PHASE_TWO_PI, PokeMtxResult, REQUIRED_SCENARIO_NAMES, ScenarioConfig, ScenarioResult, ScienceBandpass, Sequence, annotations, band_averaged_psf_metrics_from_opd, build_control_space_phase_sequence, dataclass, default_error_budget_scenarios, default_jhk_bandpasses, expand_controlled_commands, hashlib, json, math, ndimage, np, phase_rad_to_opd_nm, remove_piston_opd_nm, replace, residual_opd_nm_from_command, run_detector_integrator_loop, run_error_budget_scenario, run_error_budget_scenarios, scenario_results_as_dicts, stable_array_descriptor, summarize_scenario, synthesize_dm_phase_rad, top_hat_bandpass
```

Module-owned declarations:

- `AOErrorBudgetError` — class, source line 59
- `DEFAULT_H_BAND` — constant_or_alias, source line 53
- `DEFAULT_J_BAND` — constant_or_alias, source line 52
- `DEFAULT_K_BAND` — constant_or_alias, source line 54
- `DEFAULT_SCENARIO_SOURCE_CLASS` — constant_or_alias, source line 37
- `DEFAULT_SCENARIO_SOURCE_NOTE` — constant_or_alias, source line 38
- `NM_PER_M` — constant_or_alias, source line 55
- `PHASE_TWO_PI` — constant_or_alias, source line 56
- `REQUIRED_SCENARIO_NAMES` — constant_or_alias, source line 42
- `ScenarioConfig(scenario_name: 'str', enabled_effects: 'tuple[str, ...]', n_steps: 'int' = 24, dynamic_phase: 'bool' = True, phase_amplitude_nm: 'float' = 400.0, gain: 'float' = 0.32, leak: 'float' = 0.02, latency_frames: 'int' = 0, frame_rate_hz: 'float' = 500.0, include_detector_noise: 'bool' = False, stroke_limit_nm: 'float | None' = None, misregistration_shift_px: 'tuple[float, float]' = (0.0, 0.0), misregistration_rotation_deg: 'float' = 0.0, misregistration_magnification: 'float' = 1.0, misregistration_shear: 'float' = 0.0, ncpa_rms_nm: 'float' = 0.0, tau0_s: 'float' = 0.004, turbulence_speed_m_s: 'float' = 10.0, seed: 'int' = 1, phase_seed: 'int | None' = None, detector_noise_seed: 'int | None' = None, ncpa_seed: 'int | None' = None, source_class: 'str' = 'synthetic_assumed', source_note: 'str' = 'Synthetic fast-mode error-budget scenario; uses local detector, DM, controller, and science-metric proxies rather than measured AO telemetry.') -> None` — class, source line 64
- `ScenarioResult(scenario_name: 'str', enabled_effects: 'tuple[str, ...]', open_rms_nm: 'float', closed_rms_nm: 'float', strehl_J: 'float', strehl_H: 'float', strehl_K: 'float', ee50_J: 'float', ee50_H: 'float', ee50_K: 'float', source_class: 'str', ee80_J: 'float', ee80_H: 'float', ee80_K: 'float', command_rms_nm: 'float', command_peak_nm: 'float', saturated_actuator_frac: 'float', valid_centroid_frac: 'float', open_strehl_H: 'float', closed_over_open_rms: 'float', config_hash: 'str', source_note: 'str' = 'Synthetic fast-mode error-budget scenario; uses local detector, DM, controller, and science-metric proxies rather than measured AO telemetry.') -> None` — class, source line 195
- `build_control_space_phase_sequence(calibration: 'DetectorShwfsCalibration', dm_model: 'DMModel', poke_result: 'PokeMtxResult', scenario: 'ScenarioConfig') -> 'np.ndarray'` — function, source line 460
- `default_error_budget_scenarios(n_steps: 'int' = 24, phase_amplitude_nm: 'float' = 400.0) -> 'tuple[ScenarioConfig, ...]'` — function, source line 286
- `default_jhk_bandpasses() -> 'tuple[ScienceBandpass, ScienceBandpass, ScienceBandpass]'` — function, source line 369
- `run_error_budget_scenario(calibration: 'DetectorShwfsCalibration', dm_model: 'DMModel', poke_result: 'PokeMtxResult', scenario: 'ScenarioConfig', bandpasses: 'Sequence[ScienceBandpass]', telescope_diameter_m: 'float' = 2.0, pad_factor: 'int' = 4) -> 'ScenarioResult'` — function, source line 421
- `run_error_budget_scenarios(calibration: 'DetectorShwfsCalibration', dm_model: 'DMModel', poke_result: 'PokeMtxResult', scenarios: 'Sequence[ScenarioConfig] | None' = None, bandpasses: 'Sequence[ScienceBandpass] | None' = None, telescope_diameter_m: 'float' = 2.0, pad_factor: 'int' = 4) -> 'tuple[ScenarioResult, ...]'` — function, source line 379
- `scenario_results_as_dicts(results: 'Sequence[ScenarioResult]') -> 'tuple[dict[str, float | str], ...]'` — function, source line 634
- `summarize_scenario(phase_sequence_rad: 'np.ndarray', history: 'LoopHistory', calibration: 'DetectorShwfsCalibration', dm_model: 'DMModel', scenario: 'ScenarioConfig', bandpasses: 'Sequence[ScienceBandpass]', telescope_diameter_m: 'float' = 2.0, pad_factor: 'int' = 4) -> 'ScenarioResult'` — function, source line 520

#### `ao_integration`

Frozen non-underscore names (65):

```text
ALLOWED_SOURCE_CLASSES, AOIntegrationError, Any, DEFAULT_INTEGRATION_SOURCE_CLASS, DEFAULT_INTEGRATION_SOURCE_NOTE, DEFAULT_OUTPUT_DIR, DEFAULT_REFERENCE_METRICS_PATH, DMConfig, DMModel, DetectorConfig, DetectorLoopConfig, DetectorShwfsCalibration, IntegrationConfig, IntegrationRunResult, Path, PokeMatrixConfig, PokeMtxResult, REFERENCE_TOLERANCES, REPO_ROOT, REQUIRED_REFERENCE_FIELDS, REQUIRED_SCENARIO_NAMES, ScenarioConfig, ScenarioResult, Sequence, ShwfsGeometryConfig, VALID_INTEGRATION_MODES, ValidationCheckResult, ValidationScanResult, annotations, asdict, bandpass_from_filter_curve, build_control_space_phase_sequence, build_detector_dm_poke_matrix, build_detector_shwfs_calibration, build_dm_model, build_integration_system, build_jhk_bandpasses, build_reference_metrics, build_validation_results, check_centroid_noise_photon_monotonicity, check_diffraction_scale, check_dm_fitting_trend, check_latency_residual_monotonicity, check_marechal_consistency, check_scenario_reproducibility, csv, dataclass, default_error_budget_scenarios, hashlib, json, load_reference_metrics, load_svo_filter_curve, math, np, open_text_resource, replace, resource_exists, run_error_budget_scenario, run_error_budget_scenarios, run_fast_integration, run_integration, scenario_results_as_dicts, time, top_hat_bandpass, validation_results_as_dicts
```

Module-owned declarations:

- `AOIntegrationError` — class, source line 80
- `DEFAULT_INTEGRATION_SOURCE_CLASS` — constant_or_alias, source line 57
- `DEFAULT_INTEGRATION_SOURCE_NOTE` — constant_or_alias, source line 58
- `DEFAULT_OUTPUT_DIR` — constant_or_alias, source line 56
- `DEFAULT_REFERENCE_METRICS_PATH` — constant_or_alias, source line 55
- `IntegrationConfig(mode: 'str' = 'fast', telescope_diameter_m: 'float' = 2.0, n_pupil_pixels: 'int' = 52, n_lenslets: 'int' = 5, detector_window_px: 'int' = 18, pad_factor: 'int' = 3, photons_per_subap_frame: 'float' = 8000.0, read_noise_e: 'float' = 1.0, qe: 'float' = 1.0, n_actuators_across: 'int' = 5, coupling_width_pitch: 'float' = 0.4, stroke_limit_nm: 'float' = 1000.0, calibration_amplitude_nm: 'float' = 10.0, target_kept_mode_fraction: 'float' = 1.0, n_steps: 'int' = 12, phase_amplitude_nm: 'float' = 260.0, frame_rate_hz: 'float' = 1000.0, output_dir: 'Path | str' = PosixPath('figures/detector_level_SCAO'), reference_metrics_path: 'Path | str' = PosixPath('data/reference_metrics/fast_reference_metrics.json'), source_class: 'str' = 'synthetic_assumed', source_note: 'str' = 'Fast end-to-end detector-level 2 m SCAO integration using local synthetic/literature-inspired fixtures; not calibrated observatory AO telemetry.') -> None` — class, source line 85
- `IntegrationRunResult(mode: 'str', scenario_results: 'tuple[ScenarioResult, ...]', validation_results: 'tuple[ValidationCheckResult | ValidationScanResult, ...]', reference_metrics: 'dict[str, Any]', written_files: 'tuple[Path, ...]', runtime_s: 'float', source_class: 'str', config_hash: 'str') -> None` — class, source line 194
- `REFERENCE_TOLERANCES` — constant_or_alias, source line 62
- `REPO_ROOT` — constant_or_alias, source line 53
- `REQUIRED_REFERENCE_FIELDS` — constant_or_alias, source line 70
- `VALID_INTEGRATION_MODES` — constant_or_alias, source line 54
- `build_integration_system(config: 'IntegrationConfig') -> '_IntegrationSystem'` — function, source line 294
- `build_jhk_bandpasses()` — function, source line 492
- `build_reference_metrics(config: 'IntegrationConfig', poke_result: 'PokeMtxResult', scenario_results: 'Sequence[ScenarioResult]', validation_results: 'Sequence[ValidationCheckResult | ValidationScanResult]', runtime_s: 'float', config_hash: 'str') -> 'dict[str, Any]'` — function, source line 450
- `build_validation_results(config: 'IntegrationConfig', system: '_IntegrationSystem') -> 'tuple[ValidationCheckResult | ValidationScanResult, ...]'` — function, source line 346
- `load_reference_metrics(path: 'str | Path' = PosixPath('data/reference_metrics/fast_reference_metrics.json')) -> 'dict[str, Any]'` — function, source line 498
- `run_fast_integration(config: 'IntegrationConfig | None' = None, write_outputs: 'bool' = True) -> 'IntegrationRunResult'` — function, source line 214
- `run_integration(config: 'IntegrationConfig | None' = None, write_outputs: 'bool' = True) -> 'IntegrationRunResult'` — function, source line 236

#### `ao_validation`

Frozen non-underscore names (31):

```text
ALLOWED_SOURCE_CLASSES, AOValidationError, Any, DEFAULT_VALIDATION_SOURCE_CLASS, DEFAULT_VALIDATION_SOURCE_NOTE, DMConfig, DetectorConfig, DetectorLoopConfig, DetectorShwfsCalibration, PokeMtxResult, ScenarioResult, Sequence, ValidationCheckResult, ValidationScanResult, annotations, build_dm_model, check_centroid_noise_photon_monotonicity, check_diffraction_scale, check_dm_fitting_trend, check_latency_residual_monotonicity, check_marechal_consistency, check_scenario_reproducibility, dataclass, fit_static_opd_with_dm, math, np, replace, run_detector_integrator_loop, sample_centroid_noise, science_psf_metrics_from_opd, validation_results_as_dicts
```

Module-owned declarations:

- `AOValidationError` — class, source line 34
- `DEFAULT_VALIDATION_SOURCE_CLASS` — constant_or_alias, source line 27
- `DEFAULT_VALIDATION_SOURCE_NOTE` — constant_or_alias, source line 28
- `ValidationCheckResult(check_name: 'str', passed: 'bool', metric_value: 'float', tolerance: 'float', message: 'str', source_class: 'str' = 'synthetic_assumed', source_note: 'str' = 'Synthetic validation check for the 2 m detector-level AO demonstrator; not a measured observatory validation.', details: 'dict[str, float | int | str | bool] | None' = None) -> None` — class, source line 39
- `ValidationScanResult(check_name: 'str', x_values: 'np.ndarray', metric_values: 'np.ndarray', passed: 'bool', x_unit: 'str', metric_unit: 'str', tolerance: 'float', message: 'str', source_class: 'str' = 'synthetic_assumed', source_note: 'str' = 'Synthetic validation check for the 2 m detector-level AO demonstrator; not a measured observatory validation.') -> None` — class, source line 76
- `check_centroid_noise_photon_monotonicity(normalized_spot: 'np.ndarray', photon_counts: 'Sequence[float]', detector_template: 'DetectorConfig | None' = None, n_trials: 'int' = 192, seed: 'int' = 1, relative_tolerance: 'float' = 0.05) -> 'ValidationScanResult'` — function, source line 204
- `check_diffraction_scale(pupil_mask: 'np.ndarray', wavelength_m: 'float', telescope_diameter_m: 'float', pad_factor: 'int' = 6, fwhm_lambda_over_d_range: 'tuple[float, float]' = (0.75, 1.15)) -> 'ValidationCheckResult'` — function, source line 162
- `check_dm_fitting_trend(target_opd_nm: 'np.ndarray', x_m: 'np.ndarray', y_m: 'np.ndarray', pupil_mask: 'np.ndarray', actuator_counts: 'Sequence[int]', dm_config_template: 'DMConfig | None' = None, relative_tolerance: 'float' = 0.03) -> 'ValidationScanResult'` — function, source line 349
- `check_latency_residual_monotonicity(phase_sequence_rad: 'np.ndarray', calibration: 'DetectorShwfsCalibration', dm_model, poke_result: 'PokeMtxResult', latency_frames: 'Sequence[int]', base_loop_config: 'DetectorLoopConfig', relative_tolerance: 'float' = 0.05) -> 'ValidationScanResult'` — function, source line 253
- `check_marechal_consistency(opd_nm: 'np.ndarray', pupil_mask: 'np.ndarray', wavelength_m: 'float', telescope_diameter_m: 'float', tolerance_abs: 'float' = 0.03, min_marechal_strehl: 'float' = 0.8, pad_factor: 'int' = 5) -> 'ValidationCheckResult'` — function, source line 122
- `check_scenario_reproducibility(first_results: 'Sequence[ScenarioResult]', second_results: 'Sequence[ScenarioResult]', field_names: 'Sequence[str]' = ('open_rms_nm', 'closed_rms_nm', 'strehl_H', 'command_rms_nm', 'valid_centroid_frac'), atol: 'float' = 1e-12, rtol: 'float' = 1e-12) -> 'ValidationCheckResult'` — function, source line 299
- `validation_results_as_dicts(results: 'Sequence[ValidationCheckResult | ValidationScanResult]') -> 'tuple[dict[str, float | int | str | bool], ...]'` — function, source line 397

#### `atmosphere_profiles`

Frozen non-underscore names (34):

```text
ALLOWED_SOURCE_CLASSES, ARCSEC_PER_RAD, AtmosphereConfig, AtmosphereLayerConfig, AtmospherePhaseCube, AtmosphereProfileError, EsoAsmSnapshot, FRIED_SEEING_COEFFICIENT, FULL_SCREEN_COVER_FACTOR, LAYER_WEIGHT_ABS_TOL, LiteratureAtmosphereProfile, PHASE_RMS_COEFFICIENT, PHASE_RMS_REL_TOL, R0_REFERENCE_WAVELENGTH_M, R0_STRENGTH_EXPONENT, R0_WAVELENGTH_EXPONENT, Sequence, annotations, atmosphere_config_from_eso_asm_snapshot, atmosphere_config_from_literature_profile, circular_mask_from_grid, dataclass, equivalent_r0_500_m, expected_phase_rms_rad, fourier_phase_screen, generate_multilayer_phase_cube, math, normalize_layers, np, r0_at_wavelength_m, rms, seeing_to_r0_m, shift_full_phase_pixels, wind_components_ms
```

Module-owned declarations:

- `ARCSEC_PER_RAD` — constant_or_alias, source line 23
- `AtmosphereConfig(layers: 'tuple[AtmosphereLayerConfig, ...]', r0_500_m: 'float', seeing_arcsec: 'float', tau0_s: 'float', theta0_rad: 'float', seed: 'int', source_class: 'str', source_note: 'str') -> None` — class, source line 82
- `AtmosphereLayerConfig(height_m: 'float', cn2_weight: 'float', wind_ms: 'float', wind_dir_deg: 'float') -> None` — class, source line 39
- `AtmospherePhaseCube(cube_rad: 'np.ndarray', x_m: 'np.ndarray', y_m: 'np.ndarray', mask: 'np.ndarray', time_s: 'np.ndarray', rms_rad: 'np.ndarray', expected_rms_rad: 'float', r0_at_wavelength_m: 'float', wavelength_m: 'float', config: 'AtmosphereConfig') -> None` — class, source line 138
- `AtmosphereProfileError` — class, source line 34
- `FRIED_SEEING_COEFFICIENT` — constant_or_alias, source line 25
- `FULL_SCREEN_COVER_FACTOR` — constant_or_alias, source line 31
- `LAYER_WEIGHT_ABS_TOL` — constant_or_alias, source line 29
- `PHASE_RMS_COEFFICIENT` — constant_or_alias, source line 26
- `PHASE_RMS_REL_TOL` — constant_or_alias, source line 30
- `R0_REFERENCE_WAVELENGTH_M` — constant_or_alias, source line 24
- `R0_STRENGTH_EXPONENT` — constant_or_alias, source line 28
- `R0_WAVELENGTH_EXPONENT` — constant_or_alias, source line 27
- `atmosphere_config_from_eso_asm_snapshot(snapshot: 'EsoAsmSnapshot', seed: 'int' = 1, wind_dir_deg: 'float' = 0.0) -> 'AtmosphereConfig'` — function, source line 374
- `atmosphere_config_from_literature_profile(profile: 'LiteratureAtmosphereProfile', seed: 'int' = 1) -> 'AtmosphereConfig'` — function, source line 323
- `equivalent_r0_500_m(config: 'AtmosphereConfig') -> 'float'` — function, source line 299
- `expected_phase_rms_rad(diameter_m: 'float', r0_m: 'float') -> 'float'` — function, source line 238
- `generate_multilayer_phase_cube(config: 'AtmosphereConfig', n_grid: 'int', diameter_m: 'float', n_steps: 'int', dt_s: 'float', wavelength_m: 'float' = 5e-07, outer_scale_L0_m: 'float | None' = 25.0, field_angle_x_arcsec: 'float' = 0.0, field_angle_y_arcsec: 'float' = 0.0, normalize_total: 'bool' = True) -> 'AtmospherePhaseCube'` — function, source line 487
- `normalize_layers(layers: 'Sequence[AtmosphereLayerConfig]') -> 'tuple[AtmosphereLayerConfig, ...]'` — function, source line 263
- `r0_at_wavelength_m(r0_500_m: 'float', wavelength_m: 'float', reference_wavelength_m: 'float' = 5e-07) -> 'float'` — function, source line 207
- `seeing_to_r0_m(seeing_arcsec: 'float', wavelength_m: 'float' = 5e-07) -> 'float'` — function, source line 179
- `shift_full_phase_pixels(phase_rad: 'np.ndarray', shift_x_pix: 'int', shift_y_pix: 'int') -> 'np.ndarray'` — function, source line 453
- `wind_components_ms(layer: 'AtmosphereLayerConfig') -> 'tuple[float, float]'` — function, source line 429

#### `config_hashing`

Frozen non-underscore names (6):

```text
Any, annotations, hashlib, json, np, stable_array_descriptor
```

Module-owned declarations:

- `stable_array_descriptor(values: 'Any') -> 'dict[str, Any]'` — function, source line 12

#### `data_sources`

Frozen non-underscore names (28):

```text
ALLOWED_SOURCE_CLASSES, ARCSEC_PER_RADIAN, ATMOSPHERE_LAYER_UNITS, Any, AtmosphereLayer, CSV_COMMENT_PREFIX, CSV_METADATA_SEPARATOR, DataSourceError, ESO_MEASUREMENT_UNITS, EsoAsmSnapshot, FilterCurve, LITERATURE_SUMMARY_UNITS, LiteratureAtmosphereProfile, NORMALIZED_WEIGHT_ABS_TOL, Path, Provenance, REQUIRED_CSV_METADATA, TargetPhotometry, annotations, csv, dataclass, json, load_eso_asm_snapshot, load_literature_atmosphere_profile, load_svo_filter_curve, load_target_photometry, math, open_text_resource
```

Module-owned declarations:

- `ALLOWED_SOURCE_CLASSES` — constant_or_alias, source line 22
- `ARCSEC_PER_RADIAN` — constant_or_alias, source line 36
- `ATMOSPHERE_LAYER_UNITS` — constant_or_alias, source line 60
- `AtmosphereLayer(height_m: 'float', cn2_weight: 'float', wind_ms: 'float', wind_dir_deg: 'float') -> None` — class, source line 229
- `CSV_COMMENT_PREFIX` — constant_or_alias, source line 32
- `CSV_METADATA_SEPARATOR` — constant_or_alias, source line 33
- `DataSourceError` — class, source line 149
- `ESO_MEASUREMENT_UNITS` — constant_or_alias, source line 41
- `EsoAsmSnapshot(measurements: 'dict[str, float]', units: 'dict[str, str]', provenance: 'Provenance') -> None` — class, source line 198
- `FilterCurve(filter_id: 'str', wavelength_m: 'tuple[float, ...]', transmission: 'tuple[float, ...]', units: 'dict[str, str]', provenance: 'Provenance') -> None` — class, source line 300
- `LITERATURE_SUMMARY_UNITS` — constant_or_alias, source line 53
- `LiteratureAtmosphereProfile(name: 'str', summary: 'dict[str, float]', layers: 'tuple[AtmosphereLayer, ...]', units: 'dict[str, str]', provenance: 'Provenance') -> None` — class, source line 265
- `NORMALIZED_WEIGHT_ABS_TOL` — constant_or_alias, source line 35
- `Provenance(source_class: 'str', source_note: 'str', source_id: 'str | None' = None, url: 'str | None' = None, access_time: 'str | None' = None, fallback_used: 'bool' = False) -> None` — class, source line 154
- `REQUIRED_CSV_METADATA` — constant_or_alias, source line 34
- `TargetPhotometry(target_id: 'str', ra_deg: 'float', dec_deg: 'float', magnitudes: 'dict[str, float]', units: 'dict[str, str]', provenance: 'Provenance') -> None` — class, source line 335
- `load_eso_asm_snapshot(path: 'str | Path') -> 'EsoAsmSnapshot'` — function, source line 369
- `load_literature_atmosphere_profile(path: 'str | Path') -> 'LiteratureAtmosphereProfile'` — function, source line 409
- `load_svo_filter_curve(path: 'str | Path') -> 'FilterCurve'` — function, source line 482
- `load_target_photometry(path: 'str | Path', target_id: 'str | None' = None) -> 'TargetPhotometry'` — function, source line 543

#### `dm_model`

Frozen non-underscore names (31):

```text
ALLOWED_SOURCE_CLASSES, Any, DEFAULT_ACTUATOR_MARGIN_FRACTION, DEFAULT_DM_SOURCE_CLASS, DEFAULT_DM_SOURCE_NOTE, DMConfig, DMFitResult, DMModel, DMModelError, DMSynthesisResult, MIN_ACTUATORS_ACROSS, NM_TO_M, PHASE_TWO_PI, Path, Sequence, VALID_INFLUENCE_MODELS, actuator_centers_on_pupil, actuator_metadata, annotations, build_dm_model, clip_commands_nm, dataclass, fit_static_opd_with_dm, json, load_dm_config_from_json, math, np, open_text_resource, optimize, synthesize_dm_opd_nm, synthesize_dm_phase_rad
```

Module-owned declarations:

- `DEFAULT_ACTUATOR_MARGIN_FRACTION` — constant_or_alias, source line 33
- `DEFAULT_DM_SOURCE_CLASS` — constant_or_alias, source line 25
- `DEFAULT_DM_SOURCE_NOTE` — constant_or_alias, source line 26
- `DMConfig(telescope_diameter_m: 'float' = 2.0, n_actuators_across: 'int' = 11, influence_model: 'str' = 'gaussian', coupling_width_pitch: 'float' = 0.35, stroke_limit_nm: 'float' = 800.0, include_edge_actuators: 'bool' = True, actuator_margin_fraction: 'float' = 0.0, dead_actuator_indices: 'tuple[int, ...]' = (), stuck_actuator_indices: 'tuple[int, ...]' = (), stuck_command_nm: 'float' = 0.0, source_class: 'str' = 'synthetic_literature_inspired', source_note: 'str' = 'Synthetic Gaussian DM influence model motivated by published influence-function modelling examples such as Berdeu arXiv:2306.10803; not measured calibration data.') -> None` — class, source line 42
- `DMFitResult(target_opd_nm: 'np.ndarray', fitted_opd_nm: 'np.ndarray', residual_opd_nm: 'np.ndarray', commands_nm: 'np.ndarray', residual_rms_nm: 'float', command_rms_nm: 'float', rank: 'int', singular_values: 'np.ndarray') -> None` — class, source line 186
- `DMModel(config: 'DMConfig', x_m: 'np.ndarray', y_m: 'np.ndarray', pupil_mask: 'np.ndarray', actuator_centers_m: 'np.ndarray', actuator_pitch_m: 'float', influence_functions: 'np.ndarray', dead_actuator_mask: 'np.ndarray', stuck_actuator_mask: 'np.ndarray') -> None` — class, source line 110
- `DMModelError` — class, source line 37
- `DMSynthesisResult(opd_nm: 'np.ndarray', clipped_commands_nm: 'np.ndarray', saturated_mask: 'np.ndarray', saturation_fraction: 'float', dead_actuator_mask: 'np.ndarray', stuck_actuator_mask: 'np.ndarray') -> None` — class, source line 152
- `MIN_ACTUATORS_ACROSS` — constant_or_alias, source line 34
- `NM_TO_M` — constant_or_alias, source line 31
- `PHASE_TWO_PI` — constant_or_alias, source line 32
- `VALID_INFLUENCE_MODELS` — constant_or_alias, source line 30
- `actuator_centers_on_pupil(config: 'DMConfig') -> 'tuple[np.ndarray, float]'` — function, source line 333
- `actuator_metadata(model: 'DMModel') -> 'dict[str, Any]'` — function, source line 565
- `build_dm_model(x_m: 'np.ndarray', y_m: 'np.ndarray', pupil_mask: 'np.ndarray', config: 'DMConfig | None' = None) -> 'DMModel'` — function, source line 262
- `clip_commands_nm(commands_nm: 'Sequence[float]', model: 'DMModel') -> 'tuple[np.ndarray, np.ndarray]'` — function, source line 373
- `fit_static_opd_with_dm(target_opd_nm: 'np.ndarray', model: 'DMModel', rcond: 'float' = 0.0001) -> 'DMFitResult'` — function, source line 479
- `load_dm_config_from_json(path: 'str | Path') -> 'DMConfig'` — function, source line 220
- `synthesize_dm_opd_nm(commands_nm: 'Sequence[float]', model: 'DMModel', remove_piston: 'bool' = True) -> 'DMSynthesisResult'` — function, source line 402
- `synthesize_dm_phase_rad(commands_nm: 'Sequence[float]', model: 'DMModel', wavelength_m: 'float', remove_piston: 'bool' = True) -> 'tuple[np.ndarray, DMSynthesisResult]'` — function, source line 445

#### `interaction_matrix`

Frozen non-underscore names (40):

```text
ALLOWED_SOURCE_CLASSES, Any, DEFAULT_CENTROID_VALIDITY, DEFAULT_NUMERIC_RANK_RTOL, DEFAULT_POKE_AMPLITUDE_GRID_NM, DEFAULT_POKE_SOURCE_CLASS, DEFAULT_POKE_SOURCE_NOTE, DEFAULT_RCOND_SCAN_GRID, DEFAULT_TARGET_KEPT_FRACTION, DMModel, DetectorMeasurement, DetectorShwfsCalibration, InteractionMatrixError, PokeMatrixConfig, PokeMtxResult, RcondScanResult, Sequence, TSVDReconstructionResult, TikhonovReconstructionResult, annotations, build_detector_dm_poke_matrix, choose_rcond_from_singular_values, dataclass, expand_controlled_commands, hashlib, json, kept_modes_for_rcond, math, measure_detector_shwfs, noise_amplification_proxy, np, poke_amplitude_scan, poke_matrix_summary, replace, scan_tsvd_rcond, stable_array_descriptor, synthesize_dm_phase_rad, tikhonov_reconstruct_commands, tsvd_reconstruct_commands, vectorize_detector_measurement
```

Module-owned declarations:

- `DEFAULT_NUMERIC_RANK_RTOL` — constant_or_alias, source line 43
- `DEFAULT_POKE_AMPLITUDE_GRID_NM` — constant_or_alias, source line 41
- `DEFAULT_POKE_SOURCE_CLASS` — constant_or_alias, source line 33
- `DEFAULT_POKE_SOURCE_NOTE` — constant_or_alias, source line 34
- `DEFAULT_RCOND_SCAN_GRID` — constant_or_alias, source line 38
- `DEFAULT_TARGET_KEPT_FRACTION` — constant_or_alias, source line 42
- `InteractionMatrixError` — class, source line 46
- `PokeMatrixConfig(calibration_amplitude_nm: 'float' = 10.0, rcond_scan_grid: 'tuple[float, ...]' = (1e-06, 3e-06, 1e-05, 3e-05, 0.0001, 0.0003, 0.001, 0.003, 0.01), target_kept_mode_fraction: 'float' = 0.9, minimum_kept_modes: 'int' = 1, controlled_actuator_indices: 'tuple[int, ...] | None' = None, source_class: 'str' = 'synthetic_assumed', source_note: 'str' = 'Synthetic detector-level DM poke calibration constructed by central difference from the local detector model and synthetic DM model.') -> None` — class, source line 51
- `PokeMtxResult(poke_matrix: 'np.ndarray', singular_values: 'np.ndarray', kept_modes: 'int', rcond: 'float', source_class: 'str', rank: 'int', calibration_amplitude_nm: 'float', controlled_actuator_indices: 'np.ndarray', valid_subaperture_mask: 'np.ndarray', row_valid: 'np.ndarray', condition_proxy: 'float', config_hash: 'str', calibration_settings: 'dict[str, Any]', rcond_grid: 'tuple[float, ...]', rcond_scan_summary: 'tuple[dict[str, float | int], ...]', source_note: 'str' = 'Synthetic detector-level DM poke calibration constructed by central difference from the local detector model and synthetic DM model.') -> None` — class, source line 111
- `RcondScanResult(rcond_values: 'np.ndarray', kept_modes: 'np.ndarray', command_norms_nm: 'np.ndarray', residual_norms_px: 'np.ndarray', source_class: 'str') -> None` — class, source line 207
- `TSVDReconstructionResult(commands_nm: 'np.ndarray', reconstructed_signal_px: 'np.ndarray', residual_px: 'np.ndarray', kept_modes: 'int', rcond: 'float', singular_values: 'np.ndarray', command_norm_nm: 'float', residual_norm_px: 'float', source_class: 'str') -> None` — class, source line 179
- `TikhonovReconstructionResult(commands_nm: 'np.ndarray', reconstructed_signal_px: 'np.ndarray', residual_px: 'np.ndarray', alpha: 'float', command_norm_nm: 'float', residual_norm_px: 'float', source_class: 'str') -> None` — class, source line 194
- `build_detector_dm_poke_matrix(calibration: 'DetectorShwfsCalibration', dm_model: 'DMModel', config: 'PokeMatrixConfig | None' = None) -> 'PokeMtxResult'` — function, source line 217
- `choose_rcond_from_singular_values(singular_values: 'Sequence[float]', rcond_grid: 'Sequence[float]', target_kept_mode_fraction: 'float' = 0.9, minimum_kept_modes: 'int' = 1) -> 'float'` — function, source line 383
- `expand_controlled_commands(commands_nm: 'Sequence[float]', poke_result: 'PokeMtxResult', dm_model: 'DMModel') -> 'np.ndarray'` — function, source line 643
- `kept_modes_for_rcond(singular_values: 'Sequence[float]', rcond: 'float') -> 'int'` — function, source line 345
- `noise_amplification_proxy(singular_values: 'Sequence[float]', rcond: 'float') -> 'float'` — function, source line 355
- `poke_amplitude_scan(calibration: 'DetectorShwfsCalibration', dm_model: 'DMModel', amplitudes_nm: 'Sequence[float]' = (2.0, 5.0, 10.0, 20.0, 50.0), base_config: 'PokeMatrixConfig | None' = None) -> 'list[dict[str, Any]]'` — function, source line 562
- `poke_matrix_summary(poke_result: 'PokeMtxResult') -> 'dict[str, Any]'` — function, source line 619
- `scan_tsvd_rcond(measurement_vector_px: 'Sequence[float]', poke_result: 'PokeMtxResult', rcond_values: 'Sequence[float] | None' = None) -> 'RcondScanResult'` — function, source line 530
- `tikhonov_reconstruct_commands(measurement_vector_px: 'Sequence[float]', poke_result: 'PokeMtxResult', alpha: 'float') -> 'TikhonovReconstructionResult'` — function, source line 488
- `tsvd_reconstruct_commands(measurement_vector_px: 'Sequence[float]', poke_result: 'PokeMtxResult', rcond: 'float | None' = None) -> 'TSVDReconstructionResult'` — function, source line 449
- `vectorize_detector_measurement(measurement: 'DetectorMeasurement', poke_result: 'PokeMtxResult') -> 'np.ndarray'` — function, source line 429

#### `phase_screen`

Frozen non-underscore names (12):

```text
annotations, circular_mask_from_grid, fourier_phase_screen, frozen_flow_shift, frozen_flow_shift_physical, np, opd_to_phase, phase_to_opd, r0_from_seeing, remove_piston, rms, scale_r0_with_wavelength
```

Module-owned declarations:

- `circular_mask_from_grid(X: 'np.ndarray', Y: 'np.ndarray', diameter: 'float') -> 'np.ndarray'` — function, source line 18
- `fourier_phase_screen(N: 'int' = 256, delta: 'float' = 0.01, r0: 'float' = 0.15, L0: 'float | None' = 25.0, diameter: 'float' = 1.0, wavelength: 'float' = 5e-07, seed: 'int | None' = 1, target_rms_rad: 'float | None' = None, normalize_rms: 'bool' = True, mask_output: 'bool' = True) -> 'tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]'` — function, source line 82
- `frozen_flow_shift(screen: 'np.ndarray', shift_x_pix: 'int' = 0, shift_y_pix: 'int' = 0, mask: 'np.ndarray | None' = None, remove_mean: 'bool' = True) -> 'np.ndarray'` — function, source line 220
- `frozen_flow_shift_physical(screen: 'np.ndarray', vx: 'float', vy: 'float', dt: 'float', delta: 'float', mask: 'np.ndarray | None' = None, remove_mean: 'bool' = True) -> 'np.ndarray'` — function, source line 262
- `opd_to_phase(opd_m: 'np.ndarray', wavelength: 'float') -> 'np.ndarray'` — function, source line 213
- `phase_to_opd(phase_rad: 'np.ndarray', wavelength: 'float') -> 'np.ndarray'` — function, source line 206
- `r0_from_seeing(seeing_arcsec: 'float', wavelength: 'float' = 5e-07) -> 'float'` — function, source line 44
- `remove_piston(screen: 'np.ndarray', mask: 'np.ndarray') -> 'np.ndarray'` — function, source line 24
- `rms(screen: 'np.ndarray', mask: 'np.ndarray') -> 'float'` — function, source line 34
- `scale_r0_with_wavelength(r0_ref: 'float', wavelength: 'float', wavelength_ref: 'float' = 5e-07) -> 'float'` — function, source line 64

#### `psf_tools`

Frozen non-underscore names (7):

```text
annotations, compute_psf_from_phase, marechal_strehl, np, phase_for_science_wavelength, radial_profile, strehl_ratio
```

Module-owned declarations:

- `compute_psf_from_phase(phase_rad: 'np.ndarray', mask: 'np.ndarray', pad_factor: 'int' = 4) -> 'np.ndarray'` — function, source line 8
- `marechal_strehl(phase_rad: 'np.ndarray', mask: 'np.ndarray') -> 'float'` — function, source line 94
- `phase_for_science_wavelength(opd_m: 'np.ndarray', wavelength_sci: 'float') -> 'np.ndarray'` — function, source line 111
- `radial_profile(psf: 'np.ndarray', center: 'tuple[float, float] | None' = None) -> 'tuple[np.ndarray, np.ndarray]'` — function, source line 71
- `strehl_ratio(phase_rad: 'np.ndarray', mask: 'np.ndarray', pad_factor: 'int' = 4) -> 'float'` — function, source line 57

#### `pwfs_forward`

Frozen non-underscore names (22):

```text
add_detector_noise, add_tilt_phase, aligned_pupil_images, calibrate_pwfs_interaction_matrix, check_pwfs_geometry, extract_cutout, fft2c, ifft2c, make_aligned_pupil_mask, make_modulation_points, make_pwfs_grid, np, pupil_image_centers, pwfs_detector_measurement_from_phase, pwfs_detector_signal_from_phase, pwfs_intensity, pwfs_measurement_from_phase, pwfs_reference_signal, pwfs_signal_from_intensity, pwfs_signal_from_phase, pwfs_signal_maps_from_intensity, pyramid_phase_mask
```

Module-owned declarations:

- `add_detector_noise(intensity, n_photons=1000000.0, read_noise_e=0.0, seed=None)` — function, source line 534
- `add_tilt_phase(x, y, tx, ty)` — function, source line 133
- `aligned_pupil_images(intensity, n_pupil=128, separation=96)` — function, source line 322
- `calibrate_pwfs_interaction_matrix(modes, pupil, x, y, calibration_amplitude=0.001, n_pupil=128, separation=96, central_obscuration=0.0, pyramid_mask=None, modulation_radius=0.0, n_modulation_points=12, differential=True)` — function, source line 696
- `check_pwfs_geometry(n_fft, n_pupil, separation)` — function, source line 826
- `extract_cutout(image, center_xy, size=128)` — function, source line 290
- `fft2c(a)` — function, source line 18
- `ifft2c(a)` — function, source line 25
- `make_aligned_pupil_mask(n_pupil=128, central_obscuration=0.0)` — function, source line 80
- `make_modulation_points(modulation_radius=0.0, n_modulation_points=12)` — function, source line 142
- `make_pwfs_grid(n_fft=384, n_pupil=128, central_obscuration=0.0)` — function, source line 32
- `pupil_image_centers(n_fft=384, separation=96)` — function, source line 269
- `pwfs_detector_measurement_from_phase(phase, pupil, x, y, reference_signal=None, n_photons=1000000.0, read_noise_e=0.0, seed=None, n_pupil=128, separation=96, central_obscuration=0.0, pyramid_mask=None, modulation_radius=0.0, n_modulation_points=12)` — function, source line 641
- `pwfs_detector_signal_from_phase(phase, pupil, x, y, n_photons=1000000.0, read_noise_e=0.0, seed=None, n_pupil=128, separation=96, central_obscuration=0.0, pyramid_mask=None, modulation_radius=0.0, n_modulation_points=12)` — function, source line 595
- `pwfs_intensity(phase, pupil, x, y, pyramid_mask=None, separation=96, modulation_radius=0.0, n_modulation_points=12)` — function, source line 170
- `pwfs_measurement_from_phase(phase, pupil, x, y, reference_signal=None, n_pupil=128, separation=96, central_obscuration=0.0, pyramid_mask=None, modulation_radius=0.0, n_modulation_points=12)` — function, source line 489
- `pwfs_reference_signal(pupil, x, y, n_pupil=128, separation=96, central_obscuration=0.0, pyramid_mask=None, modulation_radius=0.0, n_modulation_points=12)` — function, source line 459
- `pwfs_signal_from_intensity(intensity, n_pupil=128, separation=96, central_obscuration=0.0)` — function, source line 401
- `pwfs_signal_from_phase(phase, pupil, x, y, n_pupil=128, separation=96, central_obscuration=0.0, pyramid_mask=None, modulation_radius=0.0, n_modulation_points=12)` — function, source line 425
- `pwfs_signal_maps_from_intensity(intensity, n_pupil=128, separation=96, central_obscuration=0.0, eps=1e-12)` — function, source line 354
- `pyramid_phase_mask(n_fft=384, separation=96)` — function, source line 107

#### `reconstruction`

Frozen non-underscore names (15):

```text
annotations, build_response_matrix, measure_geometric_slopes, measure_slopes, np, numerical_gradient, reconstruct_modal_coefficients, reconstruct_tikhonov, reconstruct_tsvd, reconstruct_wavefront, remove_piston, residual_wavefront, rms, subaperture_masks, synthesize_from_coefficients
```

Module-owned declarations:

- `build_response_matrix(modes: 'dict[str, np.ndarray]', pupil_mask: 'np.ndarray', X: 'np.ndarray', Y: 'np.ndarray', n_lenslets: 'int' = 12, min_fill: 'float' = 0.5) -> 'tuple[np.ndarray, list[str], np.ndarray]'` — function, source line 213
- `measure_geometric_slopes(*args, **kwargs)` — function, source line 208
- `measure_slopes(W: 'np.ndarray', pupil_mask: 'np.ndarray', X: 'np.ndarray', Y: 'np.ndarray', n_lenslets: 'int' = 12, min_fill: 'float' = 0.5, noise_std: 'float' = 0.0, seed: 'int | None' = 1) -> 'tuple[np.ndarray, np.ndarray]'` — function, source line 160
- `numerical_gradient(W: 'np.ndarray', dx: 'float', mask: 'np.ndarray | None' = None) -> 'tuple[np.ndarray, np.ndarray]'` — function, source line 8
- `reconstruct_modal_coefficients(slopes: 'np.ndarray', response_matrix: 'np.ndarray', rcond: 'float' = 0.0001) -> 'tuple[np.ndarray, np.ndarray, int, np.ndarray]'` — function, source line 265
- `reconstruct_tikhonov(signal: 'np.ndarray', response_matrix: 'np.ndarray', alpha: 'float') -> 'np.ndarray'` — function, source line 362
- `reconstruct_tsvd(signal: 'np.ndarray', response_matrix: 'np.ndarray', k: 'int') -> 'tuple[np.ndarray, np.ndarray]'` — function, source line 341
- `reconstruct_wavefront(slopes: 'np.ndarray', response_matrix: 'np.ndarray', modes: 'dict[str, np.ndarray]', names: 'list[str]', pupil_mask: 'np.ndarray', rcond: 'float' = 0.0001) -> 'tuple[np.ndarray, np.ndarray, np.ndarray, int, np.ndarray]'` — function, source line 307
- `remove_piston(W: 'np.ndarray', mask: 'np.ndarray') -> 'np.ndarray'` — function, source line 276
- `residual_wavefront(W_true: 'np.ndarray', W_rec: 'np.ndarray', mask: 'np.ndarray') -> 'np.ndarray'` — function, source line 335
- `rms(W: 'np.ndarray', mask: 'np.ndarray') -> 'float'` — function, source line 325
- `subaperture_masks(X: 'np.ndarray', Y: 'np.ndarray', pupil_mask: 'np.ndarray', n_lenslets: 'int' = 12, min_fill: 'float' = 0.5) -> 'tuple[np.ndarray, list[np.ndarray]]'` — function, source line 110
- `synthesize_from_coefficients(coeffs: 'np.ndarray', modes: 'dict[str, np.ndarray]', names: 'list[str]', pupil_mask: 'np.ndarray', remove_mean: 'bool' = True) -> 'np.ndarray'` — function, source line 286

#### `runtime_resources`

Frozen non-underscore names (11):

```text
Iterator, Path, RESOURCE_PACKAGE, SOURCE_REPOSITORY_ROOT, TextIO, annotations, contextmanager, normalized_resource_name, open_text_resource, resource_exists, resources
```

Module-owned declarations:

- `RESOURCE_PACKAGE` — constant_or_alias, source line 11
- `SOURCE_REPOSITORY_ROOT` — constant_or_alias, source line 12
- `normalized_resource_name(path: 'str | Path') -> 'str'` — function, source line 15
- `open_text_resource(path: 'str | Path', *, encoding: 'str' = 'utf-8', newline: 'str | None' = None) -> 'Iterator[TextIO]'` — function, source line 45
- `resource_exists(path: 'str | Path') -> 'bool'` — function, source line 27

#### `shwfs_detector`

Frozen non-underscore names (13):

```text
add_detector_noise, annotations, build_detector_response_matrix, centroid, centroid_noise_scan, crop_center, lenslet_spot_from_phase, measure_centroid_shifts, nominal_lenslet_sampling_shape, np, reconstruct_from_centroid_shifts, reference_centroids, subaperture_masks
```

Module-owned declarations:

- `add_detector_noise(normalized_spot: 'np.ndarray', photons: 'float | None' = None, read_noise_e: 'float' = 0.0, background_e: 'float' = 0.0, seed: 'int | None' = None, clip_negative: 'bool' = True) -> 'np.ndarray'` — function, source line 159
- `build_detector_response_matrix(modes: 'dict[str, np.ndarray]', pupil_mask: 'np.ndarray', X: 'np.ndarray', Y: 'np.ndarray', n_lenslets: 'int' = 12, min_fill: 'float' = 0.5, pad_factor: 'int' = 8, threshold_fraction: 'float' = 0.0, subtract_minimum: 'bool' = False, detector_window_size: 'int | None' = None, calibration_amplitude: 'float' = 0.001, differential: 'bool' = True) -> 'tuple[np.ndarray, list[str], np.ndarray, list[np.ndarray], np.ndarray]'` — function, source line 404
- `centroid(image: 'np.ndarray', threshold_fraction: 'float' = 0.0, subtract_minimum: 'bool' = False) -> 'tuple[float, float]'` — function, source line 196
- `centroid_noise_scan(phase_rad: 'np.ndarray', response_matrix: 'np.ndarray', modes: 'dict[str, np.ndarray]', names: 'list[str]', pupil_mask: 'np.ndarray', X: 'np.ndarray', Y: 'np.ndarray', photon_levels: 'list[float]', n_lenslets: 'int' = 12, min_fill: 'float' = 0.5, pad_factor: 'int' = 8, read_noise_e: 'float' = 0.0, background_e: 'float' = 0.0, threshold_fraction: 'float' = 0.0, subtract_minimum: 'bool' = False, detector_window_size: 'int | None' = None, n_trials: 'int' = 10, seed: 'int' = 1, rcond: 'float' = 0.0001) -> 'dict[float, dict[str, float]]'` — function, source line 539
- `crop_center(image: 'np.ndarray', window_size: 'int | None' = None) -> 'np.ndarray'` — function, source line 126
- `lenslet_spot_from_phase(phase_rad: 'np.ndarray', lenslet_mask: 'np.ndarray', pad_factor: 'int' = 8, remove_local_piston: 'bool' = True, sampling_shape: 'tuple[int, int] | None' = None) -> 'np.ndarray'` — function, source line 63
- `measure_centroid_shifts(phase_rad: 'np.ndarray', pupil_mask: 'np.ndarray', X: 'np.ndarray', Y: 'np.ndarray', n_lenslets: 'int' = 12, min_fill: 'float' = 0.5, pad_factor: 'int' = 8, photons: 'float | None' = None, read_noise_e: 'float' = 0.0, background_e: 'float' = 0.0, threshold_fraction: 'float' = 0.0, subtract_minimum: 'bool' = False, detector_window_size: 'int | None' = None, seed: 'int | None' = 1, reference: 'np.ndarray | None' = None, masks: 'list[np.ndarray] | None' = None, centers: 'np.ndarray | None' = None, return_spots: 'bool' = False, return_diagnostics: 'bool' = False)` — function, source line 284
- `nominal_lenslet_sampling_shape(image_shape: 'tuple[int, int]', n_lenslets: 'int') -> 'tuple[int, int]'` — function, source line 45
- `reconstruct_from_centroid_shifts(shifts: 'np.ndarray', response_matrix: 'np.ndarray', rcond: 'float' = 0.0001) -> 'tuple[np.ndarray, np.ndarray, int, np.ndarray]'` — function, source line 515
- `reference_centroids(pupil_mask: 'np.ndarray', X: 'np.ndarray', Y: 'np.ndarray', n_lenslets: 'int' = 12, min_fill: 'float' = 0.5, pad_factor: 'int' = 8, threshold_fraction: 'float' = 0.0, detector_window_size: 'int | None' = None, subtract_minimum: 'bool' = False) -> 'tuple[np.ndarray, list[np.ndarray], np.ndarray]'` — function, source line 236

#### `synthetic_instrument_data`

Frozen non-underscore names (35):

```text
ALLOWED_SOURCE_CLASSES, CentroidValidityConfig, DEFAULT_CENTROID_VALIDITY, DEFAULT_SOURCE_CLASS, DEFAULT_WFS_WAVELENGTH_M, DETECTOR_PRESETS, DetectorConfig, DetectorMeasurement, DetectorPreset, DetectorResponseMatrix, DetectorShwfsCalibration, MIN_VALID_CENTROID_FRACTION, Sequence, ShwfsGeometryConfig, SyntheticInstrumentError, add_configured_detector_noise, annotations, build_detector_shwfs_calibration, build_tilt_response_matrix, centroid, centroid_quality, crop_center, dataclass, detector_preset, lenslet_spot_from_phase, make_bad_pixel_mask, make_pupil_grid_and_mask, math, measure_detector_shwfs, nominal_lenslet_sampling_shape, np, phase_tilt_map_rad, sample_centroid_noise, subaperture_masks, zero_phase_centroid_rms_px
```

Module-owned declarations:

- `CentroidValidityConfig(min_flux_e: 'float' = 30.0, min_peak_snr: 'float' = 3.0, max_centroid_sigma_px: 'float' = 0.5, max_window_clipping_fraction: 'float' = 0.15) -> None` — class, source line 39
- `DEFAULT_CENTROID_VALIDITY` — constant_or_alias, source line 76
- `DEFAULT_SOURCE_CLASS` — constant_or_alias, source line 30
- `DEFAULT_WFS_WAVELENGTH_M` — constant_or_alias, source line 29
- `DETECTOR_PRESETS` — constant_or_alias, source line 1128
- `DetectorConfig(photons_per_subap_frame: 'float | None' = None, read_noise_e: 'float' = 0.0, dark_e_per_s: 'float' = 0.0, background_e_per_pixel_frame: 'float' = 0.0, full_well_e: 'float | None' = None, qe: 'float' = 1.0, bad_pixel_mask: 'np.ndarray | None' = None, prnu_rms: 'float' = 0.0, exposure_s: 'float' = 0.001, source_class: 'str' = 'synthetic_assumed', source_note: 'str' = 'Synthetic detector settings for unit tests and fast-mode demos.') -> None` — class, source line 80
- `DetectorMeasurement(shifts_px: 'np.ndarray', centroids_px: 'np.ndarray', fluxes_e: 'np.ndarray', valid: 'np.ndarray', valid_centroid_frac: 'float', total_flux_e: 'np.ndarray | None' = None, background_e: 'np.ndarray | None' = None, peak_snr: 'np.ndarray | None' = None, total_snr: 'np.ndarray | None' = None, centroid_sigma_px: 'np.ndarray | None' = None, window_clipping_fraction: 'np.ndarray | None' = None, valid_by_flux: 'np.ndarray | None' = None, valid_by_snr: 'np.ndarray | None' = None, valid_by_uncertainty: 'np.ndarray | None' = None, valid_by_clipping: 'np.ndarray | None' = None, spots: 'tuple[np.ndarray, ...] | None' = None) -> None` — class, source line 420
- `DetectorPreset(preset_name: 'str', read_noise_e: 'float', dark_e_per_s: 'float', background_e_per_pixel_frame: 'float', full_well_e: 'float | None', prnu_rms: 'float', bad_pixel_fraction: 'float', exposure_s: 'float' = 0.001, source_class: 'str' = 'synthetic_assumed', source_note: 'str' = 'Synthetic visible SH-WFS detector-quality preset; not a measured detector calibration.') -> None` — class, source line 165
- `DetectorResponseMatrix(matrix_px_per_unit: 'np.ndarray', column_names: 'tuple[str, ...]', row_valid: 'np.ndarray', calibration_amplitude_rad_per_m: 'float') -> None` — class, source line 463
- `DetectorShwfsCalibration(geometry: 'ShwfsGeometryConfig', detector: 'DetectorConfig', x_m: 'np.ndarray', y_m: 'np.ndarray', pupil_mask: 'np.ndarray', centers_m: 'np.ndarray', subaperture_masks: 'tuple[np.ndarray, ...]', reference_centroids_px: 'np.ndarray', valid_subaperture_fraction: 'float') -> None` — class, source line 374
- `MIN_VALID_CENTROID_FRACTION` — constant_or_alias, source line 31
- `ShwfsGeometryConfig(telescope_diameter_m: 'float' = 2.0, n_pupil_pixels: 'int' = 128, n_lenslets: 'int' = 10, min_fill_fraction: 'float' = 0.35, pad_factor: 'int' = 3, detector_window_px: 'int | None' = 24, threshold_fraction: 'float' = 0.0, subtract_minimum: 'bool' = False, central_obstruction_ratio: 'float' = 0.0, spider_width_m: 'float' = 0.0, wfs_wavelength_m: 'float' = 7e-07, source_class: 'str' = 'synthetic_assumed', source_note: 'str' = 'Synthetic 2 m SH-WFS geometry for unit tests and fast-mode demos.') -> None` — class, source line 298
- `SyntheticInstrumentError` — class, source line 34
- `add_configured_detector_noise(normalized_spot: 'np.ndarray', detector: 'DetectorConfig', seed: 'int | None' = None, clip_negative: 'bool' = True) -> 'np.ndarray'` — function, source line 638
- `build_detector_shwfs_calibration(geometry: 'ShwfsGeometryConfig | None' = None, detector: 'DetectorConfig | None' = None) -> 'DetectorShwfsCalibration'` — function, source line 533
- `build_tilt_response_matrix(calibration: 'DetectorShwfsCalibration', calibration_amplitude_rad_per_m: 'float' = 0.05) -> 'DetectorResponseMatrix'` — function, source line 970
- `centroid_quality(cropped_spot_norm: 'np.ndarray', full_spot_norm: 'np.ndarray', detector: 'DetectorConfig') -> 'dict[str, float]'` — function, source line 721
- `detector_preset(name: 'str') -> 'DetectorPreset'` — function, source line 1172
- `make_bad_pixel_mask(window_px: 'int', bad_pixel_fraction: 'float', *, seed: 'int') -> 'np.ndarray'` — function, source line 267
- `make_pupil_grid_and_mask(config: 'ShwfsGeometryConfig') -> 'tuple[np.ndarray, np.ndarray, np.ndarray, float]'` — function, source line 492
- `measure_detector_shwfs(phase_rad: 'np.ndarray', calibration: 'DetectorShwfsCalibration', include_noise: 'bool' = True, seed: 'int | None' = 1, return_spots: 'bool' = False, validity: 'CentroidValidityConfig | None' = None) -> 'DetectorMeasurement'` — function, source line 797
- `phase_tilt_map_rad(calibration: 'DetectorShwfsCalibration', tilt_x_rad_per_m: 'float' = 0.0, tilt_y_rad_per_m: 'float' = 0.0) -> 'np.ndarray'` — function, source line 606
- `sample_centroid_noise(normalized_spot: 'np.ndarray', detector: 'DetectorConfig', n_trials: 'int' = 64, seed: 'int' = 1, threshold_fraction: 'float' = 0.0) -> 'dict[str, float]'` — function, source line 1019
- `zero_phase_centroid_rms_px(calibration: 'DetectorShwfsCalibration') -> 'float'` — function, source line 944

#### `zernike`

Frozen non-underscore names (14):

```text
annotations, eval_jacobi, generate_zernike_modes, make_pupil_grid, np, number_of_zernike_modes, remove_piston, rms, synthesize_wavefront, zernike_gram_matrix, zernike_inner_product, zernike_named_modes, zernike_nm, zernike_radial
```

Module-owned declarations:

- `generate_zernike_modes(rho: 'np.ndarray', theta: 'np.ndarray', mask: 'np.ndarray', max_radial_order: 'int' = 6, include_piston: 'bool' = False, normalization: 'bool' = True) -> 'dict[str, np.ndarray]'` — function, source line 186
- `make_pupil_grid(N: 'int' = 256, diameter: 'float' = 1.0)` — function, source line 9
- `number_of_zernike_modes(max_radial_order: 'int', include_piston: 'bool' = False) -> 'int'` — function, source line 218
- `remove_piston(W: 'np.ndarray', mask: 'np.ndarray') -> 'np.ndarray'` — function, source line 28
- `rms(W: 'np.ndarray', mask: 'np.ndarray') -> 'float'` — function, source line 38
- `synthesize_wavefront(modes: 'dict[str, np.ndarray]', coeffs: 'dict[str, float]', mask: 'np.ndarray', remove_mean: 'bool' = True) -> 'np.ndarray'` — function, source line 103
- `zernike_gram_matrix(modes: 'dict[str, np.ndarray]', mask: 'np.ndarray') -> 'tuple[np.ndarray, list[str]]'` — function, source line 237
- `zernike_inner_product(Z1: 'np.ndarray', Z2: 'np.ndarray', mask: 'np.ndarray') -> 'float'` — function, source line 228
- `zernike_named_modes(rho: 'np.ndarray', theta: 'np.ndarray', mask: 'np.ndarray', include_piston: 'bool' = False, normalized: 'bool' = True) -> 'dict[str, np.ndarray]'` — function, source line 48
- `zernike_nm(n: 'int', m: 'int', rho: 'np.ndarray', theta: 'np.ndarray', mask: 'np.ndarray', normalization: 'bool' = True) -> 'np.ndarray'` — function, source line 151
- `zernike_radial(n: 'int', m: 'int', rho: 'np.ndarray') -> 'np.ndarray'` — function, source line 124

## Internal import and provenance edges

| Source | Target | Imported names / locations |
|---|---|---|
| `ao_closed_loop` | `config_hashing` | stable_array_descriptor; line 23 (module) |
| `ao_closed_loop` | `data_sources` | ALLOWED_SOURCE_CLASSES; line 22 (module) |
| `ao_closed_loop` | `dm_model` | DMModel, synthesize_dm_phase_rad; line 24 (module) |
| `ao_closed_loop` | `interaction_matrix` | PokeMtxResult, build_detector_dm_poke_matrix, expand_controlled_commands, tsvd_reconstruct_commands, vectorize_detector_measurement; line 25 (module); line 412 (module/function:build_detector_dm_poke_matrix_from_calibration) |
| `ao_closed_loop` | `phase_screen` | frozen_flow_shift, frozen_flow_shift_physical; line 33 (module) |
| `ao_closed_loop` | `psf_tools` | strehl_ratio; line 32 (module) |
| `ao_closed_loop` | `reconstruction` | measure_slopes, rms; line 31 (module) |
| `ao_closed_loop` | `shwfs_detector` | measure_centroid_shifts, reference_centroids; line 34 (module) |
| `ao_closed_loop` | `synthetic_instrument_data` | DEFAULT_CENTROID_VALIDITY, DetectorShwfsCalibration, measure_detector_shwfs; line 35 (module) |
| `ao_conditions` | `data_sources` | ALLOWED_SOURCE_CLASSES, EsoAsmSnapshot; line 12 (module) |
| `ao_diagnostics` | `data_sources` | ALLOWED_SOURCE_CLASSES, FilterCurve; line 19 (module) |
| `ao_diagnostics` | `dm_model` | DMModel, synthesize_dm_phase_rad; line 20 (module) |
| `ao_diagnostics` | `psf_tools` | compute_psf_from_phase, marechal_strehl, phase_for_science_wavelength; line 21 (module) |
| `ao_error_budget` | `ao_closed_loop` | DetectorLoopConfig, LoopHistory, run_detector_integrator_loop; line 21 (module) |
| `ao_error_budget` | `ao_diagnostics` | ScienceBandpass, band_averaged_psf_metrics_from_opd, phase_rad_to_opd_nm, remove_piston_opd_nm, residual_opd_nm_from_command, top_hat_bandpass; line 22 (module) |
| `ao_error_budget` | `config_hashing` | stable_array_descriptor; line 30 (module) |
| `ao_error_budget` | `data_sources` | ALLOWED_SOURCE_CLASSES; line 31 (module) |
| `ao_error_budget` | `dm_model` | DMConfig, DMModel, synthesize_dm_phase_rad; line 32 (module) |
| `ao_error_budget` | `interaction_matrix` | PokeMtxResult, expand_controlled_commands; line 33 (module) |
| `ao_error_budget` | `synthetic_instrument_data` | DetectorShwfsCalibration; line 34 (module) |
| `ao_integration` | `ao_closed_loop` | DetectorLoopConfig; line 23 (module) |
| `ao_integration` | `ao_diagnostics` | bandpass_from_filter_curve, top_hat_bandpass; line 24 (module) |
| `ao_integration` | `ao_error_budget` | REQUIRED_SCENARIO_NAMES, ScenarioConfig, ScenarioResult, build_control_space_phase_sequence, default_error_budget_scenarios, run_error_budget_scenario, run_error_budget_scenarios, scenario_results_as_dicts; line 25 (module) |
| `ao_integration` | `ao_validation` | ValidationCheckResult, ValidationScanResult, check_centroid_noise_photon_monotonicity, check_diffraction_scale, check_dm_fitting_trend, check_latency_residual_monotonicity, check_marechal_consistency, check_scenario_reproducibility, validation_results_as_dicts; line 35 (module) |
| `ao_integration` | `data_sources` | ALLOWED_SOURCE_CLASSES, load_svo_filter_curve; line 46 (module) |
| `ao_integration` | `dm_model` | DMConfig, DMModel, build_dm_model; line 47 (module) |
| `ao_integration` | `interaction_matrix` | PokeMatrixConfig, PokeMtxResult, build_detector_dm_poke_matrix; line 48 (module) |
| `ao_integration` | `runtime_resources` | open_text_resource, resource_exists; line 49 (module) |
| `ao_integration` | `synthetic_instrument_data` | DetectorConfig, DetectorShwfsCalibration, ShwfsGeometryConfig, build_detector_shwfs_calibration; line 50 (module) |
| `ao_validation` | `ao_closed_loop` | DetectorLoopConfig, run_detector_integrator_loop; line 18 (module) |
| `ao_validation` | `ao_diagnostics` | science_psf_metrics_from_opd; line 19 (module) |
| `ao_validation` | `ao_error_budget` | ScenarioResult; line 20 (module) |
| `ao_validation` | `data_sources` | ALLOWED_SOURCE_CLASSES; line 21 (module) |
| `ao_validation` | `dm_model` | DMConfig, build_dm_model, fit_static_opd_with_dm; line 22 (module) |
| `ao_validation` | `interaction_matrix` | PokeMtxResult; line 23 (module) |
| `ao_validation` | `synthetic_instrument_data` | DetectorConfig, DetectorShwfsCalibration, sample_centroid_noise; line 24 (module) |
| `atmosphere_profiles` | `data_sources` | ALLOWED_SOURCE_CLASSES, EsoAsmSnapshot, LiteratureAtmosphereProfile; line 19 (module) |
| `atmosphere_profiles` | `phase_screen` | circular_mask_from_grid, fourier_phase_screen, rms; line 20 (module) |
| `data_sources` | `runtime_resources` | open_text_resource; line 19 (module) |
| `dm_model` | `data_sources` | ALLOWED_SOURCE_CLASSES; line 21 (module) |
| `dm_model` | `runtime_resources` | open_text_resource; line 22 (module) |
| `interaction_matrix` | `config_hashing` | stable_array_descriptor; line 23 (module) |
| `interaction_matrix` | `data_sources` | ALLOWED_SOURCE_CLASSES; line 22 (module) |
| `interaction_matrix` | `dm_model` | DMModel, synthesize_dm_phase_rad; line 24 (module) |
| `interaction_matrix` | `synthetic_instrument_data` | DEFAULT_CENTROID_VALIDITY, DetectorMeasurement, DetectorShwfsCalibration, measure_detector_shwfs; line 25 (module) |
| `shwfs_detector` | `reconstruction` | residual_wavefront, rms, subaperture_masks, synthesize_from_coefficients; line 24 (module); line 561 (module/function:centroid_noise_scan) |
| `synthetic_instrument_data` | `data_sources` | ALLOWED_SOURCE_CLASSES; line 19 (module) |
| `synthetic_instrument_data` | `reconstruction` | subaperture_masks; line 20 (module) |
| `synthetic_instrument_data` | `shwfs_detector` | centroid, crop_center, lenslet_spot_from_phase, nominal_lenslet_sampling_shape; line 21 (module) |

Direct `data_sources` provenance-taxonomy consumers (10): `ao_closed_loop`, `ao_conditions`, `ao_diagnostics`, `ao_error_budget`, `ao_integration`, `ao_validation`, `atmosphere_profiles`, `dm_model`, `interaction_matrix`, `synthetic_instrument_data`. `data_sources` then depends on `runtime_resources.open_text_resource`.

## Packaged resources

The pre-ticket wheel contains `ao_simulation_data/__init__.py` plus the 20 package-data resources below. AO-REF-000 adds this JSON manifest as a twenty-first package-data resource; its own hash is intentionally not embedded in itself.

| Logical name | Wheel path | SHA-256 | Bytes |
|---|---|---|---:|
| `README.md` | `ao_simulation_data/README.md` | `480ce9795c02014d8b883d8bc8543b663d246c965ed26e8d3ab2308a35258ca9` | 5444 |
| `literature_profiles/paranal_three_layer_literature_inspired.json` | `ao_simulation_data/literature_profiles/paranal_three_layer_literature_inspired.json` | `19af2a4b1eddfa86f942f34817332658ced114b952e9478f0dc98b4bbeecd233` | 1316 |
| `public/README.md` | `ao_simulation_data/public/README.md` | `5a390bdbf75b8bb327171ae1c2c1057d1200daa098e3074d582be70b1d84f466` | 2351 |
| `public/eso_asm_paranal_20240729_0300_0800_snapshot.json` | `ao_simulation_data/public/eso_asm_paranal_20240729_0300_0800_snapshot.json` | `113eb3d07f0423087caaf76fb481d9ace5bdbdd51f3955c64283caeb54fc737f` | 1832 |
| `public/eso_asm_paranal_20240729_0300_0800_timeseries.csv` | `ao_simulation_data/public/eso_asm_paranal_20240729_0300_0800_timeseries.csv` | `38d18aa98399547875cee7966bac9be7e318159e8336f4746bb5774d1e0adbbe` | 7754 |
| `public/eso_asm_paranal_20240729_0900_1000_snapshot.json` | `ao_simulation_data/public/eso_asm_paranal_20240729_0900_1000_snapshot.json` | `6f15a6968690f3f57306303ebab54dc07655aec6a779eb541e98d76e183295d3` | 1286 |
| `public/eso_asm_paranal_20240729_0900_1000_timeseries.csv` | `ao_simulation_data/public/eso_asm_paranal_20240729_0900_1000_timeseries.csv` | `26f2d191798375b0541fe2fd8463cee61a9946d6a91de1af96ca70be1be7bf68` | 2644 |
| `public/svo_2mass_h_direct.csv` | `ao_simulation_data/public/svo_2mass_h_direct.csv` | `f63aa3c5f4b1e63654d71dd89babf52db2f577dbdd61680823e1e2ab8fd0badb` | 2130 |
| `public/svo_2mass_j_direct.csv` | `ao_simulation_data/public/svo_2mass_j_direct.csv` | `692bd9a9e6bc23e6316220be5f37e5d550c49ac0e74d0e8adbeb30baa791c64c` | 3228 |
| `public/svo_2mass_ks_direct.csv` | `ao_simulation_data/public/svo_2mass_ks_direct.csv` | `8c7ac30d7ff1c540319011049549e95f691e34227250426dccdedcd8f745ca05` | 2524 |
| `public/target_photometry_2mass_psc_demo_ngs_bright.csv` | `ao_simulation_data/public/target_photometry_2mass_psc_demo_ngs_bright.csv` | `709979f20e914cd04d7dde1c860472b62abd59468ed6e2d79a5269e756e4c687` | 1180 |
| `public/target_photometry_panstarrs_dr2_demo_ngs_bright.csv` | `ao_simulation_data/public/target_photometry_panstarrs_dr2_demo_ngs_bright.csv` | `ea8e41fa741066e7fd771340a5d940a83f0b508333a398e5178d6c36e062bc95` | 2238 |
| `reference_metrics/fast_error_budget_regression_baseline.csv` | `ao_simulation_data/reference_metrics/fast_error_budget_regression_baseline.csv` | `2ab79f6af3e6724014651c17f27342a3c877681d5e50781956b1811e75592bd1` | 4203 |
| `reference_metrics/fast_reference_metrics.json` | `ao_simulation_data/reference_metrics/fast_reference_metrics.json` | `c404f8ec8d059de8f353c35071497bc11cbfaf6a220be3a4910e32abd8b391a9` | 1312 |
| `reference_metrics/fast_reference_metrics_regression_baseline.json` | `ao_simulation_data/reference_metrics/fast_reference_metrics_regression_baseline.json` | `c404f8ec8d059de8f353c35071497bc11cbfaf6a220be3a4910e32abd8b391a9` | 1312 |
| `reference_metrics/fast_validation_regression_baseline.csv` | `ao_simulation_data/reference_metrics/fast_validation_regression_baseline.csv` | `e59403688e6cf625dc8ce9234ed8ba0dbf020a632d309ef72fe445f1cad25b24` | 3870 |
| `samples/eso_asm_snapshot_sample.json` | `ao_simulation_data/samples/eso_asm_snapshot_sample.json` | `944f2e7086b003205fdfa0b6e0d8f1b744fe06b10d402747357fea159d73aaa5` | 850 |
| `samples/svo_2mass_h_sample.csv` | `ao_simulation_data/samples/svo_2mass_h_sample.csv` | `1fdc18b0b9806685c46bab3c111f7dabd0e2ba38f62e543ca5c0fc5df1d0ee80` | 595 |
| `samples/target_photometry_sample.csv` | `ao_simulation_data/samples/target_photometry_sample.csv` | `050d184729cdd17d1d08cafd1f46e8008991032c87915b67233b0f7fd4dc9692` | 643 |
| `synthetic_presets/dm_2m_fast_gaussian.json` | `ao_simulation_data/synthetic_presets/dm_2m_fast_gaussian.json` | `4753566272ea121449f2e3d12d00bdd0a4e5cfce22df42a6302603384ac3e57c` | 1087 |
| `reference_metrics/refactor_contract_manifest.json` | `ao_simulation_data/reference_metrics/refactor_contract_manifest.json` | self-reference excluded | generated |

Resource lookup currently tries absolute paths, CWD-relative paths, repository-root-relative paths, then package resources. That precedence is observable and must survive AO-REF-001. In a raw checkout, nested resources are reliably found as `data/<logical-name>`; an unprefixed nested name can fail when `ao_simulation_data` is not installed. The installed wheel accepts both forms. `cache/`, `external/`, and `.gitkeep` files are not installed.

For AO-REF-001, every table row maps one-for-one from `data/<logical-name>` to `src/ao_simulation_data/<logical-name>`; `data/__init__.py` maps to `src/ao_simulation_data/__init__.py`, and this manifest maps to `src/ao_simulation_data/reference_metrics/refactor_contract_manifest.json`. The complete explicit source map is `resources.ao_ref_001_explicit_resource_map` in the manifest. No move is performed by AO-REF-000.

## Baseline and artifact contract

All four files differ from HEAD. This manifest characterizes both identities and does not accept either candidate on the user's behalf.

| Artifact | Format/schema | Working-tree SHA-256 | HEAD SHA-256 |
|---|---|---|---|
| `data/reference_metrics/fast_reference_metrics.json` | schema 2 JSON | `c404f8ec8d059de8f353c35071497bc11cbfaf6a220be3a4910e32abd8b391a9` | `e68823f683334f0f9d043c0d9c8c66350131348c8f7722a761a23c70978abf72` |
| `data/reference_metrics/fast_reference_metrics_regression_baseline.json` | schema 2 JSON | `c404f8ec8d059de8f353c35071497bc11cbfaf6a220be3a4910e32abd8b391a9` | `806bb9c432bfde5f8bd55db37377349154aab700244a70757ae1bf0bd7390857` |
| `data/reference_metrics/fast_error_budget_regression_baseline.csv` | semantic CSV, 8 rows | `2ab79f6af3e6724014651c17f27342a3c877681d5e50781956b1811e75592bd1` | `82055c0a30146591bb46f00462e7a55558a319fdfb326f654f9ad811634d120e` |
| `data/reference_metrics/fast_validation_regression_baseline.csv` | semantic CSV, 13 rows | `e59403688e6cf625dc8ce9234ed8ba0dbf020a632d309ef72fe445f1cad25b24` | `a7a8a835ea535e5c1eb213fa50834965719a3e2e1df13bb5b0bd8a1c544cce72` |

Working-tree schema-2 reference values: open RMS 77.164249 nm, closed RMS 59.442573 nm, H Strehl 0.950455, valid-centroid fraction 1.0, kept modes 13, config hash `589f23902cec6de5d6f520f08b6b5920f55ade0ed246d31fd1f9e2a582c12685`. In HEAD, both JSONs record open 70.009063 nm, closed 48.348567 nm, and H Strehl 0.96641, but their configuration hashes already differ: generated `fast_reference_metrics.json` has `f49acb3e63c472a8d232151bfee01789cae0caf4f7e078b1cd75ef5f125b14e5`, while `fast_reference_metrics_regression_baseline.json` has `94d32c22e8a70620ba16f18b2e0887e92e23e2aa681b87cec8ca1bac53924176`.

JSON tolerances are `{"closed_rms_nm_abs": 15.0, "h_strehl_abs": 0.04, "kept_modes_abs": 0, "open_rms_nm_abs": 15.0, "runtime_s_reference_max": 30.0, "valid_centroid_fraction_abs": 1e-12}`. Semantic CSV comparisons use relative `2e-6` and absolute `2e-8`. Runtime is informational. Guarded update: `python3 scripts/update_fast_regression_baselines.py --accept-baseline-update [--candidate-dir PATH]`.

Schema-2 is intentionally characterized, not tightened: its loader validates only a subset of fields; CSV schemas are ordered headers rather than checked JSON Schemas. Strict schema/upgrader work belongs to later tickets.

## Examples, scripts, and installed entry points

There are no installed console or GUI entry points.

| Path | Kind | `main()` | Current CI smoke | Path mutation | Options/environment |
|---|---|---|---|---|---|
| `examples/run_error_budget_demo.py` | example | () -> None | no | `sys.path.insert(0, str(SRC))` | none |
| `examples/run_fast_integration.py` | example | () -> None | yes | `sys.path.insert(0, str(SRC))` | AO_DEMO_OUTPUT_DIR, AO_DEMO_REFERENCE_METRICS |
| `examples/run_interaction_matrix_demo.py` | example | () -> None | no | `sys.path.insert(0, str(SRC))` | none |
| `examples/run_psf_strehl_demo.py` | example | () -> None | yes | `sys.path.insert(0, str(SRC))` | none |
| `examples/run_public_data_informed_ao_demo.py` | example | () -> None | no | `sys.path.insert(0, str(SRC))` | none |
| `examples/run_public_data_overview.py` | example | () -> None | yes | `sys.path.insert(0, str(SRC))` | AO_DEMO_OUTPUT_DIR |
| `examples/run_science_metrics_demo.py` | example | () -> None | no | `sys.path.insert(0, str(SRC))` | none |
| `examples/run_shwfs_centroid_demo.py` | example | () -> None | yes | `sys.path.insert(0, str(SRC))` | none |
| `examples/run_validation_checks_demo.py` | example | () -> None | no | `sys.path.insert(0, str(SRC))` | none |
| `scripts/build_parameter_source_inventory_pdf.py` | script | () -> None | no | `none` | --markdown, --pdf, --no-pdf |
| `scripts/fetch_public_reference_data.py` | script | () -> None | no | `none` | none |
| `scripts/update_fast_regression_baselines.py` | script | () -> None | no | `sys.path.insert(0, str(SRC))` | --accept-baseline-update, --candidate-dir |

Required fast smoke set: `examples/run_fast_integration.py`, `examples/run_psf_strehl_demo.py`, `examples/run_public_data_overview.py`, `examples/run_shwfs_centroid_demo.py`.

## CI and environment gates

The current modified workflow has one Ubuntu matrix job (30-minute timeout, fail-fast disabled):

| Python | Constraints | SHA-256 | State |
|---|---|---|---|
| 3.10 | `constraints/py310.txt` | `01369eedf00eb25044e7c79956feb6c6a5cd03e75cb6af297677768b26e0a619` | untracked |
| 3.14 | `constraints/py314.txt` | `1d9b3dad980f983479cf5d1ca153827fbde7b7ad0a2d13f581a56be823de28e9` | untracked |

Each matrix entry performs the constrained editable install, `pip check`, and `pytest -q`. Python 3.14 also runs the four fast examples and then checks tracked baseline/figure diffs. Contract tests assert the matrix semantics, hashes, all legacy imports, resource inventory, and baseline schemas; wheel tests run outside the checkout with `PYTHONPATH` cleared.

The local 3.14.3 run used NumPy 2.4.3 and SciPy 1.17.1, so it is not evidence for either pinned Linux lane. Python 3.10/NumPy 2.2.6 and Python 3.14/NumPy 2.5.1 execution remain pending external CI. AO-REF-001 stays gated until both pass (or any version-specific stochastic fixture differences are explicitly captured and reviewed).

## RNG and draw-coupling contract

No single root-seed router exists. Seeds are passed independently and sometimes reused or arithmetically derived.

| Current owner | Draw order | Coupling that must be preserved | Proposed named domain | Compatibility mode |
|---|---|---|---|---|
| `phase_screen.fourier_phase_screen` | N x N real normal → N x N imaginary normal | same generator; seed=None is nondeterministic | `atmosphere_truth` | required |
| `atmosphere_profiles.generate_multilayer_phase_cube` | one phase screen per layer with seed + layer_index | inserting/reordering a layer remaps later realizations | `atmosphere_truth/layer/<stable-id>` | required |
| `ao_error_budget.build_control_space_phase_sequence` | initial actuator jitter → one innovation per dynamic frame after frame zero | draw count depends on actuator count and n_steps; default phase_seed=101 | `atmosphere_truth/control_proxy` | required |
| `synthetic_instrument_data.add_configured_detector_noise` | PRNU normal → Poisson shot → Gaussian read → full-well clip → fixed bad pixels → negative clip | PRNU is redrawn per call; enabling it perturbs shot/read draws | `detector_prnu + detector_shot + detector_read` | required |
| `synthetic_instrument_data.measure_detector_shwfs` | one child integer seed per retained subaperture → spot-local detector draws | subaperture reordering changes later spot realizations | `detector_noise/frame/lenslet-id` | required |
| `synthetic_instrument_data.make_bad_pixel_mask` | fixed mask realization | persistent only because the realized array is retained; seed can collide with temporal noise | `persistent_detector_defects/bad_pixels` | not required |
| `reconstruction.measure_slopes` | one Gaussian array matching all interleaved slopes when enabled | row count/order remaps the full draw | `wfs_noise/geometric` | required |
| `shwfs_detector.add_detector_noise` | Poisson shot/background → Gaussian read → negative clip | shot/read share one generator | `detector_noise/legacy_spot` | required |
| `shwfs_detector.measure_centroid_shifts` | one child seed per lenslet → legacy spot draws | consumes lenslet seeds even on the ideal path; order is observable | `detector_noise/legacy_frame/lenslet-id` | required |
| `shwfs_detector.centroid_noise_scan` | photon levels → trials → lenslet/spot draws | nested iteration order controls child-seed assignment | `detector_noise/legacy_scan/photon/trial` | required |
| `synthetic_instrument_data.sample_centroid_noise` | one child seed per trial → configured detector draws | trial order controls the coupled PRNU/shot/read stream | `detector_noise/centroid_trial` | required |
| `ao_closed_loop.run_closed_loop_ao` | one child seed per frame → optional slope-noise array | consumes a frame seed even when slope noise is zero | `wfs_noise/geometric/runtime/frame` | required |
| `ao_closed_loop.run_closed_loop_ao_detector` | frame child → lenslet children → spot draws | both frame and lenslet order are observable | `detector_noise/legacy_loop/frame/lenslet-id` | required |
| `ao_closed_loop.run_detector_integrator_loop` | one child integer seed per frame | later frame seeds are isolated from per-spot draw counts; default seed=1 | `detector_noise/runtime/frame` | required |
| `pwfs_forward.add_detector_noise` | Poisson shot → Gaussian read | independent default_rng entry point without PRNU; two detector wrapper functions forward the same seed unchanged | `detector_noise/pwfs` | required |
| `ao_error_budget._science_path_ncpa_nm` | none; deterministic trigonometric map from ncpa_seed | default ncpa_seed=307; replacing it with RNG draws changes the model | `ncpa` | required |
| `current noise-free calibrations` | none; legacy ideal paths may consume irrelevant child seeds | calibration does not share persistent PRNU/bad-pixel realization with runtime | `calibration` | required |

Seed-propagating wrappers are also observable: `gain_scan` deliberately replays the same seed for every gain; the photon-monotonicity validation replays the same trial seeds at every flux; and the two PWFS detector wrappers forward their seed unchanged to `pwfs_forward.add_detector_noise`.

The future router must provide at least atmosphere truth, detector shot/read noise, persistent detector defects, calibration, and NCPA domains without using Python's randomized `hash()`. Adding a draw in one domain must not perturb another. The current analytic NCPA map (seed 307) is behavior, not random state, and must not be silently replaced.

## Focused seeded component fixtures

Exact inputs, portable scalar tolerances, and informational current-environment array hashes live under `component_characterization` in the manifest.

The original capture command and `/tmp` output are retained only as ephemeral evidence. The durable replay is `MPLCONFIGDIR=/tmp/ao-ref-000-mpl python3 -m pytest -q tests/test_refactor_characterization.py`; it recomputes every gating scalar/order/sign assertion from the checked-in inputs.

| Fixture | Frozen behavior |
|---|---|
| `analytic_tsvd_round_trip` | two-mode command round trip and residual tolerances |
| `deformable_mirror` | 13-actuator command order; positive command produces positive local OPD; piston and command units |
| `detector_dm_poke_matrix` | 24x13 matrix, rank 13, controlled order, singular endpoints, selected rcond |
| `detector_draw_order_and_defects` | PRNU → Poisson → read-noise order; per-call PRNU; fixed bad-pixel bitmap |
| `latency_two_frames` | latency 2 enqueues two zero applications; first applied increment is frame index 2 |
| `phase_screen` | seeded real/imaginary draw order; pupil mask; piston removal; RMS normalization and selected samples |
| `psf` | 64x64 sampling, unit-total-flux normalization, peak and Strehl |
| `shack_hartmann` | retained center order; interleaved x/y rows; +x maps +x and +y maps to negative detector row |

## Risk register

| ID | Severity | Risk | Control |
|---|---|---|---|
| R1 | high | pytest pythonpath=src and editable installs mask source-layout and wheel omissions | contract wheel test imports all 19 modules outside checkout and reads every resource |
| R2 | high | the current 19-module/3.10+3.14/resource contract is dirty worktree state, not HEAD | record HEAD, status, diff, workflow/constraint/baseline hashes, and authority warning |
| R3 | high | none of the 19 modules defines __all__; 504 globals include accidental re-exports | freeze the exact namespace and require reviewed exceptions for shims |
| R4 | high | runtime resource resolution depends on cwd/repository roots before package resources | freeze lookup precedence and require outside-checkout wheel smoke |
| R5 | high | all four current baseline files differ from HEAD | label current values unaccepted and record both current and HEAD identities without regeneration |
| R6 | high | phase, OPD, nm-equivalent commands, slope rows, detector rows, and reflective sign/factor are easy to reinterpret | seeded sign/unit/order fixtures for atmosphere, WFS, DM, poke, reconstruction, latency, and PSF |
| R7 | high | shared RNG streams couple PRNU, shot/read noise, subaperture order, layer order, and frame order | record exact call order and require a named-domain compatibility mode before isolation |
| R8 | medium | moving files changes Path(__file__).parents[1] values and function-local imports may be missed | one-for-one move/shim map plus nested import inventory |
| R9 | medium | schema-2 validation is lenient and CSV schemas are only ordered headers | freeze exact field/header sets and hashes; defer stricter schema/upgrader work |
| R10 | medium | notebooks mutate paths, write tracked-style artifacts, duplicate engines, or have extreme defaults | one-for-one disposition manifest; no deletion before replacement/output capture |
| R11 | medium | wheel hashes vary due ZIP metadata and sdist omits non-package operational files | gate member/resource payloads and record archive hash as informational |
| R12 | medium | runtime thresholds lack a cross-platform performance budget | treat runtime/memory as informational until separately specified |

## Reproduction commands and observed results

```bash
MPLCONFIGDIR=/tmp/ao-ref-000-mpl python3 -m pytest -q
# pre-ticket observation: 166 passed in 233.08 s

MPLCONFIGDIR=/tmp/ao-ref-000-full-mpl python3 -m pytest -q
# AO-REF-000 observation: 184 passed in 232.48 s

python3 -m pip wheel . --no-deps --no-build-isolation --wheel-dir /tmp/ao-ref-000-wheel
python3 -m pip install --no-deps --target /tmp/ao-ref-000-site /tmp/ao-ref-000-wheel/*.whl
# from /tmp, use PYTHONPATH= and python3 -I; prepend only /tmp/ao-ref-000-site
# observed pre-ticket: 19/19 modules imported and 20/20 package-data resources read

python3 scripts/update_fast_regression_baselines.py
# observed/required: exits 2; --accept-baseline-update is required
```

For exact constrained commands, including Python 3.10 and 3.14 venv invocations, see `evidence.reproduction_commands` in the manifest.

## Ticket boundary

AO-REF-000 changes only contract documentation, manifest data, and characterization tests. It moves no implementation file, removes no public import, changes no numerical algorithm, and regenerates no accepted baseline. AO-REF-001 must not begin until this snapshot and its explicit dirty-state authority are independently accepted.
