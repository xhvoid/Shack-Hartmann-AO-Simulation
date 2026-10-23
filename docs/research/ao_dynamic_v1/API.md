# Computation service API v1 (`ao-dynamic.api.v1`)

The single definition of the contract is `scripts/ao_dynamic/contract.py`
(standard library only); the browser mirrors its rules in
`web/ao-explorer/code-<build>/generate-contract.js`. A client must check
semantics, not only digests: an unsupported schema, API version, unit,
wavelength, residual field, window, layout or scene is refused.

## Endpoints

| Method and path | Result |
| --- | --- |
| `GET /api/v1/info` | `ao-dynamic.info.v1`: schemas, service instance and code digests, producer and core identities, environment, fixed scope, parameter table with bounds and notes, comparison rules, horizon constants, limits, display tables (256-entry RdBu_r and inferno lookup tables), frame/final block layouts |
| `POST /api/v1/check` | validation and complete-horizon admission only (`ao-dynamic.check.v1`); nothing is queued |
| `POST /api/v1/runs` | 202 with a status, 422 `invalid_request` or `not_admitted` (with every reason and the admission record), 429 `busy` |
| `GET /api/v1/runs` | recent runs of this service instance |
| `GET /api/v1/runs/<run-id>` | `ao-dynamic.status.v1`; asking renews the job's lease |
| `POST /api/v1/runs/<run-id>/cancel` | optional body `{"reason": "visitor" \| "superseded"}`; returns the final status |
| `GET /api/v1/runs/<run-id>/files/<name>` | `run.json`, `frames.bin`, `final.bin`, `metrics.csv`, `evidence.npz` of a completed run (409 if not completed, 410 if evicted) |

Errors use `ao-dynamic.error.v1` (`error`, `message`, optional `reasons`,
`admission`). Requests must be `application/json`, at most 64 KiB, without
NaN/Infinity. Cross-origin access is granted only to origins listed with
`--allow-origin`; credentials are never used.

## Request (`ao-dynamic.request.v1`)

```json
{
  "schema": "ao-dynamic.request.v1",
  "api": "ao-dynamic.api.v1",
  "seed_policy": "specified",
  "parameters": {
    "seed": 1, "r0_m": 0.1263371938263465, "r0_reference_wavelength_m": 5e-07,
    "wind_speed_m_per_s": 10.0, "wind_direction_deg": 0, "guide_ab_magnitude": 7.0,
    "controller_gain": 0.2, "queued_latency_frames": 2,
    "n_frames": 180, "burn_in": 40, "display_stride": 1
  }
}
```

`seed_policy: "allocate"` with `"seed": null` asks the service for a new seed
(never 1 or 2, never one it already used); the status and the run record name
it with `seed_source: "allocated_by_service"`. Every parameter is required;
unknown fields are refused. `client_token` (≤ 80 characters) is optional.

## Status (`ao-dynamic.status.v1`)

`run_id`, `state` (`queued`, `running`, `completed`, `cancelled`, `failed`),
the effective parameters (with the derived `wind_m_per_s`), `seed`,
`seed_source`, `physical_identity`, `queue_position`, `progress`
(`frames_done`, `n_frames`, `physical_time_s`, `fraction`, `stage`),
`computation_wall_s`, an admission summary and its digest, `reason` for
cancelled/failed jobs, `worker` (process id, thread limits, cleanup record:
signals sent, return code, whether the process group outlived it, whether
partial outputs were removed) and `files` (size and SHA-256 of each run file)
once completed.

Progress counts computed frames and the physical time reached. It is
unrelated to the page's replay speed.

## Run record (`ao-dynamic.run.v1`, `run.json`)

| Section | Content |
| --- | --- |
| `effective` | parameters (with `wind_m_per_s`), fixed scope, `physical_identity` (SHA-256 of API, profile and physical parameters; display stride excluded), `system_config_hash`, the profile's effective parameters |
| `identities` | API and schema, worker and reused explorer-module digests, producer Git state, core package digest and Git state, environment and lock verification, host, atmosphere (component/config hash, model configuration, root seed, realization index and stream id, evolution rule), calibration (interaction matrix, WFS and reconstructor hashes; dependence rule), all component hashes, loop-history digest, propagator hash, scene id, numerical parents and renderer |
| `admission` | the complete-horizon admission record and its digest |
| `time` | frame rate, period, `time_s` of every frame (k / 1000 s), grid digest, sampling and evolution statement |
| `analysis_window` | `[burn_in, n)`, equal weights, samples used (= every eligible frame) |
| `conventions` | OPD in metres, residual field and timing, uncorrected field, held-correction rule, phase rule and wrapping, phase-display wavelengths, axis layout and directions, PSF normalization, Strehl kinds, queued vs WFS-visible delay, saturation timing, spatial-invariance and science-camera limits |
| `grids` | pupil (shape, spacing, mask digest), PSF (156 x 156, axis digests, step, zero index, 64 x 64 crop and its angular extent), observation (convolution policy, full 311 x 311 shape, native crop) |
| `scene` | the binary scene record (`ao-explorer.scene.v1`) |
| `display` | OPD colour limit and rule, per-replay-frame piston removed and clipped fractions for the three maps, intensity mapping and ideal peak cell flux |
| `per_frame` | every frame: index, time, atmosphere/residual RMS (m), instantaneous peak Strehl (both arms), running averaged-intensity Strehl (null before burn-in), valid fractions, reconstruction usability, saturation of the issued and of the held command, atmosphere and residual SHA-256 |
| `transported` | replay frame indices and times, running sample counts and windows, instantaneous and running observation flux records |
| `summary`, `final_average` | completed-window statistics and observation flux bookkeeping, accumulator records |
| `arrays` | sizes, digests and block layouts of the binary files |
| `checks` | independent reductions, direct-DFT PSF/Strehl/phase oracles, streaming and linearity checks, flux, horizon; `all_passed` |
| `resources`, `limitations` | build/loop/export wall times, peak RSS, thread limits; stated limits |

## Binary files

`frames.bin`: little-endian float32, per replay frame in order, blocks
`atmosphere_opd_m`, `held_correction_opd_m`, `pre_update_residual_opd_m`
(52 x 52, metres, NaN outside the pupil), `psf_uncorrected`, `psf_corrected`,
`observation_uncorrected`, `observation_corrected`,
`running_observation_uncorrected`, `running_observation_corrected` (64 x 64
crops about exact zero angle; running blocks are NaN before burn-in).
Rows increase with +y, columns with +x. `final.bin`: the completed-window
mean PSFs, final observations and the scene, as 64 x 64 float32 crops.
`evidence.npz`: full-precision axes, pupil mask, ideal PSF, mean PSFs, final
observations on the full native grid, scene, replay indices and loop history.

## Compatibility

A client must refuse an `info` or run record whose `api`/`schema` differ, or
whose fixed scope, parameter names, layouts or conventions differ from the
version it implements. Incompatible changes require a new API version and
a new page build.
