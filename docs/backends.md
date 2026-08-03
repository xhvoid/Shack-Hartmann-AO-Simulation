# Backends and public contracts

The framework has a transparent NumPy reference backend and an optional HCIPy
optical backend. Both communicate with detector, calibration, controller, and
science code through repository-owned protocols and immutable result records.
An HCIPy object is never a public pipeline value, even inside result metadata.

Install the optional dependency with
`python -m pip install "shack-hartmann-ao-simulation[hcipy]"`. Importing
`shwfs_ao`, `shwfs_ao.core`, native modules, or
`shwfs_ao.backends.hcipy` itself remains lazy and works without HCIPy. Calling
an HCIPy-backed constructor without the extra raises `OptionalDependencyError`
with that install hint.

## Responsibility boundary

| Concern | Repository/shared owner | Native implementation | HCIPy implementation |
| --- | --- | --- | --- |
| pupil and stable IDs | `core.geometry`, `wfs.shack_hartmann.geometry` | consumes repository geometry | conversion validates exact grid order and mask |
| atmosphere output | `AtmosphereModel`: piston-removed OPD m | static OPD or periodic Fourier screen with integer-pixel frozen flow | finite/infinite von Kármán layers with sub-pixel flow; summed near-field OPD |
| SH-WFS optics | `ShackHartmannOpticsBackend`: normalized spots and throughput | local extraction, piston removal, padded FFT | microlens array plus Fresnel propagation |
| detector/electrons | `detector.effects` and one `DetectorRealization` | shared | shared; HCIPy does not replace it |
| centroid and validity | `detector.centroid`, `detector.validity` | shared | shared; HCIPy estimator is diagnostics-only |
| DM policy | `dm.DeformableMirror`: IDs, stroke, faults, requested/applied telemetry | shared wrapper | shared wrapper |
| DM spatial synthesis | `dm.DmBackend`: memoryless raw correction OPD | Gaussian, compact-Gaussian, and pyramid-like influences | matched Gaussian basis through `hcipy.DeformableMirror` |
| calibration/reconstruction | `calibration` | shared | shared |
| gain/leak/latency | `control.Controller` and `control.loop` | shared | shared; no backend queue |
| science PSF | `SciencePropagator` → `PsfResult` | centered padded NumPy FFT | HCIPy Fraunhofer propagation on an explicit angular grid |
| scalar metrics | `science.metrics` | shared | shared |
| artifacts | `io.artifacts` | shared | shared |

The built-in profile-level `ScaoBackendComponentFactory` registrations are
`native` and `hcipy`. The HCIPy factory
(`shwfs_ao.backends.hcipy.factory.HCIPY_SCAO_COMPONENT_FACTORY`) builds the
detector-level lenslet SH-WFS on fixed block windows, the single-layer von
Kármán frozen-flow atmosphere, the matched Gaussian DM, and the Fraunhofer
science propagator; `high_order_10m_hcipy@2` is its current packaged profile,
alongside the superseded `high_order_10m_hcipy@1` that remains loadable. The
serialized fields keep one meaning across backends: `wfs.pad_factor` is the
spot sampling in detector pixels per lambda/d — realized natively by FFT
zero-padding and by the equivalent lenslet f-number under HCIPy — and
`wfs.detector_window_px` must equal `pupil_pixels // lenslets_across`, the
block window the HCIPy lenslet model actually measures on. Profiles the HCIPy
backend cannot represent (geometric WFS, `static` or `native_frozen_flow`
atmospheres, RMS-normalized seeing) fail closed with a factory error rather
than silently substituting native components, and resolving the registration
never imports HCIPy: building without the optional dependency raises the
canonical `OptionalDependencyError` with its install hint.

### Known backend scope

- Native frozen flow preserves the historical nearest-integer periodic shift.
  HCIPy atmosphere supports finite/infinite layers and sub-pixel motion. The
  adapter sums pupil-plane phase/OPD; layer altitude is metadata and there is
  no scintillation, anisoplanatic tomography, or laser-guide-star propagation.
- The HCIPy SH-WFS block-window adapter requires each pupil dimension to be an
  integer multiple of `n_lenslets_across`. Other samplings use the native
  optics backend.
- The matched HCIPy DM builder supports the Gaussian influence family. Native
  compact-Gaussian and pyramid-like influence families have no HCIPy adapter.
- `focal_sampling_from_psf_sampling()` can make the native FFT and HCIPy focal
  lattices identical only for square sampled pupils. Rectangular pupils must
  use `HcipyFocalSampling` explicitly.
- `PsfResult` is monochromatic. The scalar bandpass helper averages scalar
  metrics; it does not authorize same-index coaddition of wavelength-dependent
  PSF arrays.

## Command and residual convention

Repository DM commands are `m_opd_equivalent`: optical-path correction
amplitudes, not volts and not physical mirror surface. The shared equations are

```python
residual_opd_m = atmosphere_opd_m - dm_correction_opd_m
requested_commands_opd_m = (
    (1.0 - leak) * last_applied_commands_opd_m
    + gain * released_delta_opd_m
)
```

`released_delta_opd_m` is the increment released by the sole controller delay
queue on this frame; it may be older than the increment just reconstructed.

A positive command produces a positive correction map, which is subtracted
from atmospheric OPD. HCIPy's reflective DM accepts physical surface
displacement, so its adapter sends half the OPD-equivalent command and returns
HCIPy's reflected `2 * surface` OPD unchanged. That is the only factor-of-two
conversion. The repository `DeformableMirror` still owns clipping, dead/stuck
actuators, saturation diagnostics, and applied-command acknowledgement.

## Public component protocols

The nine backend-neutral protocols in `shwfs_ao.core.protocols` are the
normative pipeline interfaces. Structural conformance is sufficient; runtime
inheritance is not required.

| Protocol | Required public members | Contract |
| --- | --- | --- |
| `RandomStreams` | `root_seed`, `derivation_scheme_id`, `registered_domains`, `reset()`, `generator(domain)`, `keyed_generator(domain, key=...)`, `stream_id(domain, key=())`, `scoped(scope, key=())` | stable registered RNG domains (`registered_domains` lists them in registration order); keyed/scoped children do not advance unrelated persistent generators |
| `AtmosphereModel` | `backend_name`, `config_hash`, `metadata`, `reset(realization_index=0)`, `opd_at(time_s)` | non-decreasing absolute time; piston-removed OPD m; same realization index replays within a backend |
| `ShackHartmannOpticsBackend` | `backend_name`, `config_hash`, `spot_intensities(residual_opd_m)` | returns `SpotIntensityResult`; owns no detector or validity behavior |
| `WavefrontSensor` | `config_hash`, `row_ids`, `measure(residual_opd_m, random_streams=..., include_noise=...)` | returns `WfsMeasurement` in the immutable row layout |
| `DeformableMirrorModel` | `config_hash`, `n_actuators`, `actuator_ids`, `controllable_actuator_ids`, `opd_from_commands(DmCommandVector)` | validates full ordered IDs and returns correction OPD plus requested/applied diagnostics |
| `Reconstructor` | `matrix_hash`, `reconstruct(MeasurementVector)` | returns `ReconstructionEstimate` or `None` when coverage/rank policy fails |
| `CommandProjector` | `config_hash`, `input_coordinate_ids`, `input_coordinate_kind`, `input_coordinate_unit`, `output_actuator_ids`, `project(estimate)` | checks coordinate identity/kind/unit and returns a full-layout `DmCommandVector` |
| `Controller` | `config_hash`, `actuator_ids`, `reset()`, `update(delta_or_none)`, `accept_applied_commands(commands)` | sole gain/leak/latency owner; `None` advances the queue; applied DM command becomes next state |
| `SciencePropagator` | `backend_name`, `config_hash`, `psf_from_opd(opd_m, wavelength_m)` | explicit wavelength; returns physical-axis `PsfResult` |

Exported extension protocols narrow implementation seams:

| Protocol | Required public members | Owner |
| --- | --- | --- |
| `CentroidEstimator` | `estimate(image_e) -> CentroidEstimate` | `shwfs_ao.detector.centroid` |
| `DmBackend` | `influence_functions()`, `opd_from_commands(commands_opd_m)` | `shwfs_ao.dm.model`; raw array-only, memoryless synthesis |
| `ProbeBasis` | `size`, `coordinate_ids`, `coordinate_kind`, `coordinate_unit`, `max_abs_amplitude_m`, `opd_m_for_coordinate(index, amplitude_m)` | `shwfs_ao.calibration.interaction` |
| `ScaoBackendComponentFactory` | `backend_name`, `build_geometry(**kwargs)`, `build_atmosphere(**kwargs)`, `build_wfs(**kwargs)`, `build_dm(**kwargs)`, `build_science_propagator(**kwargs)` | `shwfs_ao.experiments.scao` |

`io.artifacts.IntegrationArtifactResult` is a public structural input annotation
for the writer rather than an exported package protocol:

| Member | Unit/contract |
| --- | --- |
| `mode` | non-empty experiment-mode string |
| `scenario_results` | ordered scenario-result sequence |
| `validation_results` | ordered validation-result sequence |
| `reference_metrics` | finite JSON-compatible metric mapping |
| `runtime_s` | elapsed seconds |
| `source_class` | registered provenance class |
| `config_hash` | stable experiment configuration identity |

Likewise, `science.bandpass.FilterCurve` is a structural conversion input (not
an `__all__` export):

| Member | Unit/contract |
| --- | --- |
| `filter_id` | stable filter identifier |
| `wavelength_m` | increasing 1-D wavelengths in metres |
| `transmission` | matching finite non-negative dimensionless weights |
| `units` | mapping that confirms wavelength/transmission source units |
| `provenance` | canonical `Provenance` record |

## Canonical shared result fields

The ten records in `shwfs_ao.core.types` are the canonical result contracts
exchanged across backend/protocol boundaries. Layer-specific public records
follow in the next section. Arrays are copied and stored read-only. IDs are
non-empty, unique, and ordered. Infinities are forbidden. NaN is permitted
only where the owning record gives it a meaning: outside a pupil, in an
explicitly invalid full-layout row, or in a detector diagnostic such as
ideal-path flux/SNR that is explicitly not applicable. The per-field rules
below are authoritative.

### `MeasurementVector`

| Field | Unit/shape | Meaning |
| --- | --- | --- |
| `values` | `(n_rows,)`; unit named by `measurement_unit` | full-layout measurement payload; an invalid row may be NaN |
| `valid_rows` | `(n_rows,)` bool | runtime validity mask |
| `row_ids` | `tuple[str, ...]` | immutable calibration/runtime row identity |
| `measurement_unit` | `"pixel"` or `"rad_wavefront_slope"` | detector shift or dimensionless/radian small-angle wavefront slope |

### `DetectorPlaneSampling`

| Field | Unit/shape | Meaning |
| --- | --- | --- |
| `window_shape_px` | `(rows, columns)` px | full lenslet detector window |
| `pixel_scale_rad` | `(x, y)` rad/px | angular sampling by columns and rows |
| `reference_pixel_xy` | `(x, y)` px | reference pixel in column/row coordinates |
| `sampling_hash` | stable string | hash of shape, scale, and reference pixel |

### `DetectorFrame`

| Field | Unit/shape | Meaning |
| --- | --- | --- |
| `image_e` | 2-D electrons | final detector image after configured effects |
| `expected_source_e` | same shape, electrons | source-electron expectation |
| `expected_background_e` | same shape, electrons | dark plus background expectation, excluding source |
| `expected_pre_poisson_e` | same shape, electrons | total expectation after pixel response and before Poisson draw |
| `prnu_response` | same shape, dimensionless | realized multiplicative pixel response |
| `saturated_mask` | same shape, bool | full-well-clipped pixels |
| `bad_pixel_mask` | same shape, bool | persistent configured defect map |
| `negative_clipped_mask` | same shape, bool | pixels clipped by the non-negative output policy |
| `random_stream_ids` | mapping `str -> str` | identities of streams actually used, never generator state |

### `DetectorTelemetry`

| Field | Unit/shape | Meaning |
| --- | --- | --- |
| `subaperture_ids` | `n_subapertures` IDs | stable lenslet order |
| `centroids_xy_px` | `(n_subapertures, 2)` px | measured `(x column, y row)` centroids; invalid entries may be NaN |
| `reference_centroids_xy_px` | same shape, px | finite zero-phase references |
| `fluxes_e` | `(n_subapertures,)` electrons | detector-window flux |
| `valid_subapertures` | bool vector | aggregate validity; both x/y rows follow it |
| `valid_by_flux` | bool vector | minimum-flux criterion |
| `valid_by_snr` | bool vector | configured SNR criterion |
| `valid_by_uncertainty` | bool vector | centroid-uncertainty criterion |
| `valid_by_clipping` | bool vector | detector-window clipping criterion |
| `peak_snr` | vector, dimensionless | peak-pixel SNR or NaN when not applicable |
| `total_snr` | vector, dimensionless | integrated SNR or NaN when not applicable |
| `centroid_sigma_px` | vector, px | estimated centroid uncertainty |
| `clipping_fraction` | vector in `[0, 1]` | estimated flux outside the finite window |
| `detector_frames` | tuple of `DetectorFrame` or `None` | optional per-lenslet detector details |
| `optical_spots` | `SpotIntensityResult` or `None` | optional noiseless backend spots |

### `WfsMeasurement`

| Field | Unit/shape | Meaning |
| --- | --- | --- |
| `vector` | `MeasurementVector` | minimal reconstruction input |
| `valid_subapertures` | bool vector or `None` | optional lenslet-level validity; absent for sensors without that concept |
| `metadata` | immutable JSON mapping | repository-owned component and convention metadata |
| `detector_telemetry` | `DetectorTelemetry` or `None` | optional detector details; geometric sensors do not invent electrons |

### `SpotIntensityResult`

| Field | Unit/shape | Meaning |
| --- | --- | --- |
| `unit_sum_spots` | tuple of 2-D windows | one finite, non-negative, unit-sum spot per retained lenslet |
| `subaperture_ids` | ordered ID tuple | must match repository geometry exactly |
| `relative_throughput` | vector, dimensionless | captured lenslet throughput kept separate from normalization |
| `x_px` | tuple of increasing 1-D axes | detector-column coordinate for each window |
| `y_px` | tuple of increasing 1-D axes | detector-row coordinate for each window |
| `sampling` | `DetectorPlaneSampling` | common detector window identity |
| `normalization` | `"unit_sum_per_subaperture"` | fixed normalization discriminator |

### `PsfResult`

| Field | Unit/shape | Meaning |
| --- | --- | --- |
| `intensity` | 2-D discrete flux | finite, non-negative, validated as unit total flux with `rel_tol=1e-9`, `abs_tol=1e-12`; input is not silently renormalized |
| `x_angle_rad` | increasing axis matching columns | physical focal angle in radians |
| `y_angle_rad` | increasing axis matching rows | physical focal angle in radians |
| `wavelength_m` | metres | wavelength used for OPD-to-phase conversion |
| `normalization` | `"unit_total_flux"` | fixed normalization discriminator |
| `backend_name` | string | implementation identity such as `native` or `hcipy` |
| `sampling_metadata` | immutable JSON mapping | pupil/focal grid, padding/cropping/interpolation and convention identity |

### `DmCommandVector`

| Field | Unit/shape | Meaning |
| --- | --- | --- |
| `values_opd_m` | `(n_actuators,)` m OPD-equivalent | full-layout correction amplitudes |
| `actuator_ids` | ordered ID tuple | exact physical command layout |
| `command_unit` | `"m_opd_equivalent"` | fixed command discriminator |

### `DmSynthesisResult`

| Field | Unit/shape | Meaning |
| --- | --- | --- |
| `correction_opd_m` | 2-D metres | finite raw correction map returned by the backend |
| `requested_commands_opd_m` | actuator vector, metres | pre-stroke/fault requested command |
| `applied_commands_opd_m` | actuator vector, metres | post-clipping/dead/stuck command sent to the backend |
| `actuator_ids` | ordered ID tuple | full physical layout |
| `saturated_mask` | actuator bool vector | requested commands outside the symmetric stroke |
| `saturation_fraction` | `[0, 1]` | saturated actuator fraction |
| `command_unit` | `"m_opd_equivalent"` | fixed command discriminator |
| `config_hash` | stable string | canonical DM wrapper identity |

### `ReconstructionEstimate`

| Field | Unit/shape | Meaning |
| --- | --- | --- |
| `delta_coordinates_opd_m` | coordinate vector, metres | reconstructed increments in the declared coordinate convention |
| `coordinate_ids` | ordered ID tuple | modal or controllable-DM coordinate identity |
| `coordinate_kind` | `"modal_opd"` or `"dm_command_opd"` | coordinate semantic type |
| `coordinate_unit` | `"m_opd_rms"` or `"m_opd_equivalent"` | modal pupil-RMS or DM command amplitude |
| `measurement_unit` | registered measurement unit | unit of the calibrated forward operator |
| `usable_rows` | full row-layout bool vector | calibration-valid ∩ runtime-valid ∩ finite |
| `reconstructed_signal` | full row-layout vector | fitted measurement signal; NaN in unusable rows |
| `residual_signal` | full row-layout vector | measurement minus fitted signal; NaN in unusable rows |
| `coordinate_norm_m` | metres | Euclidean coordinate norm |
| `residual_norm` | measurement unit | Euclidean norm over usable residual rows |
| `kept_modes` | count or `None` | retained inverse modes when the solver has that concept |
| `singular_values` | 1-D operator values | singular spectrum of the usable-row solve |
| `matrix_hash` | stable string | interaction-matrix identity |

## Other public pipeline records

These records do not replace the ten core types; they preserve the identity
needed by one pipeline layer. Configuration-only records are documented by
their owning module/profile schema; every exported canonical measurement,
calibration, diagnostic, science, and experiment-result record is listed here.

### `calibration.InteractionDiagnostics`

| Field | Unit/shape | Meaning |
| --- | --- | --- |
| `singular_values` | descending 1-D operator spectrum | finite non-negative singular values from calibration-valid rows |
| `rank` | count | numerical rank under the declared tolerance |
| `condition_proxy` | dimensionless | largest/smallest retained singular-value ratio, or positive infinity when rank is zero |

### `calibration.ReconstructorCacheInfo`

| Field | Unit | Meaning |
| --- | --- | --- |
| `hits` | count | masked-operator cache hits |
| `misses` | count | cache misses |
| `svd_computations` | count | decompositions actually performed |
| `current_size` | count | retained mask/operator entries; exposed as `size` too |
| `max_size` | count | configured bound; exposed as `max_cached_masks` too |

### `calibration.InteractionMatrix`

| Fields | Meaning |
| --- | --- |
| `matrix`, `row_valid`, `row_ids`, `coordinate_ids` | full `(rows, coordinates)` forward operator, full validity layout, and stable identities |
| `coordinate_kind`, `calibration_amplitude_m`, `measurement_unit`, `coordinate_unit`, `matrix_unit` | explicit coordinate, probe, measurement, and derivative units |
| `singular_values`, `rank`, `condition_proxy` | diagnostics computed from calibration-valid rows |
| `method`, `include_noise`, `repeat_count`, `matrix_standard_error` | forward/central method and repeated/noisy calibration uncertainty |
| `sensor_config_hash`, `geometry_hash`, `detector_hash`, `dm_hash`, `calibration_hash` | component and complete calibration identity |
| `provenance` | source classification and references |

### SH-WFS calibration records

| Record/fields | Unit/shape | Meaning |
| --- | --- | --- |
| `ShackHartmannCalibration.geometry` | `ShackHartmannGeometry` | exact detector-level pupil/lenslet layout |
| `reference_centroids_px` | `(n_subapertures, 2)` px | finite zero-OPD `(x column, y row)` references |
| `wfs_wavelength_m` | metres | calibration wavelength |
| `subaperture_ids`, `row_ids` | ordered tuples | exact physical IDs and interleaved `S:x`, `S:y` row layout |
| `measurement_unit` | `"pixel"` | fixed detector-level calibration unit |
| `detector_sampling`, `detector_config`, `centroid_config` | typed records | exact sampling and algorithm/electron assumptions |
| `detector_realization_hash`, `config_hash` | stable strings | persistent detector state and full calibration identity |
| `provenance` | `Provenance` | source classification and references |
| `photon_allocation` | `"throughput_scaled"` or `"unit_sum"` | explicit photon-budget interpretation shared by reference and runtime frames; the frozen throughput-scaled default hashes identically, while `"unit_sum"` changes the calibration hash |
| `GeometricShackHartmannCalibration.geometry` | `ShackHartmannGeometry` | exact geometric-sensor layout |
| `reference_slopes_rad` | `(n_subapertures, 2)` rad wavefront slope | finite local-slope references |
| `subaperture_ids`, `row_ids` | ordered tuples | physical IDs and interleaved row identity |
| `config_hash`, `provenance` | stable string and `Provenance` | complete geometric calibration identity and source |

### `control.LoopHistory`

| Fields | Meaning |
| --- | --- |
| `time_s` | absolute sample time |
| `open_loop_opd_rms_m`, `pre_update_residual_opd_rms_m`, `post_update_residual_opd_rms_m` | frame-aligned SI wavefront telemetry |
| `command_norm_m`, `delta_command_norm_m`, `released_delta_norm_m` | requested/increment/released command norms |
| `requested_command_history_opd_m`, `applied_command_history_opd_m` | full actuator histories |
| `saturation_fraction` | per-frame DM saturation |
| `valid_measurement_fraction`, `valid_subaperture_fraction`, `reconstruction_usable`, `measurement_row_masks` | validity and reconstruction coverage without zero-filling |
| `config_hash`, `metadata` | loop/component/convention/hash and RNG identity |

### `science.PsfScalarMetrics`

| Fields | Unit | Meaning |
| --- | --- | --- |
| `wavelength_m`, `telescope_diameter_m`, `opd_rms_m` | metres | monochromatic/effective wavelength, aperture diameter, and pupil OPD RMS |
| `peak_strehl`, `marechal_strehl`, `marechal_abs_difference` | dimensionless | sampled peak ratio, Maréchal estimate, and their absolute difference |
| `fwhm_rad`, `fwhm_lambda_over_d`, `fwhm_arcsec` | rad, `lambda/D`, arcsec | the same surface-brightness FWHM diameter in three declared units |
| `ee50_rad`, `ee50_lambda_over_d`, `ee50_arcsec` | rad, `lambda/D`, arcsec | 50-percent encircled-energy radius |
| `ee80_rad`, `ee80_lambda_over_d`, `ee80_arcsec` | rad, `lambda/D`, arcsec | 80-percent encircled-energy radius |
| `halo_fraction` | `[0, 1]` | discrete flux outside the declared halo boundary |
| `halo_inner_radius_rad`, `halo_inner_lambda_over_d` | rad, `lambda/D` | the same halo boundary in physical and diffraction units |
| `flux_semantics` | `"discrete_pixel_flux"` | declares that PSF samples sum as discrete flux |
| `fwhm_semantics` | `"angular_surface_brightness_per_sr"` | declares the quantity used for FWHM |
| `aggregation` | `"monochromatic"` or `"weighted_scalar_average"` | distinguishes one wavelength from scalar-only band averaging |

### `experiments.ScenarioResult`

This is the retained fast error-budget row shape. It is canonical at the
experiment API even though its implementation deliberately adapts historical
loop/result types.

| Fields | Unit | Meaning |
| --- | --- | --- |
| `scenario_name`, `enabled_effects` | strings | stable row identity and explicit enabled-effect labels |
| `open_rms_nm`, `closed_rms_nm` | nm OPD RMS | median open- and closed-loop tail-window residuals |
| `strehl_J`, `strehl_H`, `strehl_K`, `open_strehl_H` | dimensionless | band-specific closed-loop peak ratios and open-loop H-band ratio |
| `ee50_J`, `ee50_H`, `ee50_K` | `lambda/D` | band-specific 50-percent encircled-energy radii |
| `ee80_J`, `ee80_H`, `ee80_K` | `lambda/D` | band-specific 80-percent encircled-energy radii |
| `command_rms_nm`, `command_peak_nm` | nm OPD-equivalent | applied-command RMS and maximum absolute command in the compatibility loop |
| `saturated_actuator_frac`, `valid_centroid_frac` | `[0, 1]` | median actuator saturation and usable-centroid fractions |
| `closed_over_open_rms` | dimensionless | closed/open OPD-RMS ratio |
| `config_hash` | SHA-256 hex | complete scenario/result identity |
| `source_class`, `source_note` | provenance strings | source taxonomy and non-empty interpretation note |

### `experiments.ScaoSystem`

| Fields | Meaning |
| --- | --- |
| `random_streams`, `atmosphere`, `wfs`, `dm` | constructed truth, sensor, and correction components |
| `interaction_matrix`, `reconstructor`, `command_projector`, `controller` | calibrated inverse and real-time-control chain |
| `science_propagator` | configured physical-axis PSF backend |
| `component_hashes`, `config_hash`, `source_config` | immutable component map, serialized profile identity, and the `SystemConfig` the system was built from (`config_hash` equals `source_config.config_hash`) |

The detector layer also returns detector-state and detector-local records;
`DetectorTelemetry` is their backend-neutral aggregate.

### `detector.DetectorRealization`

| Field | Unit/shape | Meaning |
| --- | --- | --- |
| `prnu_response` | detector-shaped, dimensionless | persistent multiplicative pixel response |
| `bad_pixel_mask` | detector-shaped bool | persistent defect map |
| `root_seed` | non-negative integer | immutable root seed used to derive the realization |
| `stream_id` | string | `detector.realization` stream identity, not generator state |
| `config_hash`, `realization_hash` | stable strings | detector configuration and realized-map identity |

### `detector.CentroidEstimate`

| Field | Unit | Meaning |
| --- | --- | --- |
| `x_px` | pixel columns | centroid x coordinate |
| `y_px` | pixel rows | centroid y coordinate |
| `total_flux_e` | electrons | summed finite image signal after the estimator's configured preprocessing |
| `finite` | bool | whether the coordinate and flux result is finite and usable by the next validity stage |

### `detector.CentroidQuality`

| Field | Unit | Meaning |
| --- | --- | --- |
| `total_flux_e` | electrons or NaN | expected source signal; NaN on an ideal detector path where electrons are not applicable |
| `background_e` | electrons | finite non-negative background expectation |
| `peak_snr`, `total_snr` | dimensionless or NaN | peak and integrated SNR; NaN when the diagnostic is not applicable |
| `centroid_sigma_px` | px | finite non-negative centroid-uncertainty estimate |
| `clipping_fraction` | `[0, 1]` | estimated flux outside the finite detector window |

### `detector.CentroidValidity`

| Field | Unit | Meaning |
| --- | --- | --- |
| `valid` | bool | aggregate of all enabled criteria |
| `valid_by_flux` | bool | minimum-flux decision |
| `valid_by_snr` | bool | configured SNR decision |
| `valid_by_uncertainty` | bool | centroid-uncertainty decision |
| `valid_by_clipping` | bool | detector-window clipping decision |
| `peak_snr` | dimensionless | peak-pixel SNR, or NaN when not applicable |
| `total_snr` | dimensionless | integrated SNR, or NaN when not applicable |
| `centroid_sigma_px` | px | estimated centroid uncertainty |
| `clipping_fraction` | `[0, 1]` | estimated flux outside the detector window |

## Comparison policy

Native and HCIPy are not required to be pixel-identical. Shape, IDs, units,
normalization discriminators, hashes, and simple conversions are exact.
Small-signal signs and normalized integrals use tight numerical checks.
Atmosphere statistics, spot width, singular spectra, Strehl, and closed-loop
trends use metric-specific physical tolerances with units and rationale.
Independently generated atmospheric screens are never compared pointwise.
See [Validation](validation.md).
