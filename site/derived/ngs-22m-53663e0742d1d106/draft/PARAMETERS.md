# Robo-AO-2 / UH 2.2 m / natural-guide-star configuration draft

Prepared 2026-10-24. **Parameter preparation only: no atmosphere generated, calibration built, AO trajectory run, CI run, or default profile changed.**

The new [configuration bundle](candidate-config.json) describes an on-axis, 16×16 NGS scenario with the internal MEMS mirror. Its scope follows the NGS mode documented for mid-2025 through the July-2026 publication [S3]. The adaptive secondary and hybrid laser/stellar operation belong to different configurations.

The bundle combines documented hardware with published simulation inputs and explicit local assumptions. It is **an unregistered configuration draft**, with a schema-v7 system profile and a separate camera record. The existing loader resolves only packaged camera presets; this new camera is deliberately local to the bundle. Later execution needs explicit bundle loading or preset registration. This task adds neither a runtime loader nor a packaged preset.

The original 2 m profile and all saved trajectories remain in place. The comparison below uses [the archived 2 m A configuration](../../../outputs/ao_dm_stroke_comparison/20261024-2m-stroke-ab/config-A.json) with 1000 frames. The packaged `det_emccd_2m_synthetic@1` has a 60-frame default; that distinction is preserved in the integrity record.

## Parameter comparison

Evidence labels: **H** = published hardware/operating mode; **L** = published simulation input; **D** = derived, conditional on stated assumptions; **A** = local assumption or approximation; **N** = numerical choice. “L” does not establish an on-sky operating value. The [complete field ledger](parameter-ledger.json) records every serialized config value, including inherited settings.

| Parameter | Original 2 m A | New 2.2 m draft | Evidence and qualification |
|---|---|---|---|
| Telescope diameter | 2.0 m | 2.2 m | H, [S1] |
| Sensing mode | Synthetic on-axis SH-WFS | NGS-only, on-axis | H/A; no finite-distance beacon |
| Lenslets across pupil | 5 | 16 | H, [S3] §3 |
| DM hardware target | No commercial model | BMC DM492-3.5 | H, [S1] §2.3 |
| Model actuator grid | 5 across; 13 centres | 17 across; 197 centres | H for 17 across; A for local circular mask. Not a measured channel map |
| Device actuator count | — | 492 total; 24 across full device | H, [S4]; do not equate full device count with illuminated/model count |
| Projected actuator pitch | 0.5 m | 0.1375 m | D: diameter / (actuators across − 1) |
| Command half-limit | ±1 µm OPD | **±3.5 µm OPD** | D/A; centred nominal-stroke approximation, explained below |
| Influence width σ/pitch | 0.4 | 0.495047 | D/A: Gaussian fit to nominal 13% neighbour coupling [S4] |
| Pupil grid | 52×52 | 256×256 | N; convergence not checked |
| Obscuration / spiders | Both zero | Both zero, explicit omissions | A; real pupil mask still missing |
| WFS reference wavelength | 700 nm | 750 nm | L, [S2] Table 5 |
| WFS spectral model | 550–850 nm budget; one wavelength | 640–900 nm top-hat; three nodes | L/A/N; endpoints from [S2] §2.1, not a measured filter curve |
| WFS camera | `synthetic_emccd@1` | HNü128/CCD60 target with a separate noise proxy | H for identity [S1] §2.6; mixed L/A for response |
| Scalar QE | 0.90 | 0.67 | L, [S2] Table 5; not a measured QE spectrum |
| Input-referred read noise | 0.20 e⁻ | 0.39 e⁻ | L; output-referred config conversion below |
| Nominal dark current | 0.002 e⁻/pixel/s | 0.01 e⁻/pixel/s | L, [S2] Table 5 |
| EM gain | 300 | 300 | A, retained synthetic high-gain setting |
| Model multiplication noise | High-gain EMCCD | Same model; ENF ≈ √2 | N; compatible with rounded 1.41 in [S2], not a new camera measurement |
| Guide-star brightness | AB 7, flat fν | AB 7, flat fν | A; not an identified star or the paper's magnitude convention |
| Throughput excluding QE | 0.40 | 0.30 | L, [S2] Table 5; no extra beamsplitter factor |
| Sky brightness | AB 20.5 mag/arcsec² | AB 18.5 proxy | A; uses [S2]'s number but assumes an AB convention |
| Window and angular sampling | 23 pixels; FFT spacing | 7 pixels; 0.714286 arcsec/pixel | A; 5 arcsec / 7; native schema requires odd windows. Operating NGS binning remains unverified |
| WFS focal stop | No physical stop propagation | 5 arcsec hardware target [S1]; detector-field proxy | H for stop; A for its representation. Different optical planes |
| Update rate | 1000 Hz | 750 Hz | L/A; NGS study setting [S2] Table 7, not verified present-day telemetry |
| Exposure | 1 ms | 1.333333 ms | D/A: one full frame, no dead time |
| Loop gain / leak | 0.2 / 0.02 | 0.4 / 0 | L for gain [S2]; A for zero leak and controller interpretation |
| Command latency setting | 2 frames | 2 frames | A; 2.667 ms queue at 750 Hz, not measured total latency |
| Separate tip-tilt mirror | Absent | Absent from model | Model gap: real architecture has a separate mirror [S1] |
| Reconstructor | TSVD, cutoff 10⁻⁸ | TSVD, cutoff 10⁻³ | N; zonal regularized-LS surrogate. Cutoff uncalibrated |
| Integrated r₀ at 500 nm | 0.126337 m | 0.113 m | L, [S2] §3.1 |
| Turbulence / wind | Single 10 m/s layer | Eleven frozen-flow layers including dome component | L/D, [S2] Table 6; complete vectors in bundle |
| Outer scale | 25 m | 25 m | A retained; not an established site value in the selected source |
| RMS rescaling | Off | Off | N; amplitude remains tied to r₀ |
| Science wavelengths | 1.25, 1.65, 2.2 µm | 0.620, 1.25, 1.65 µm | A: monochromatic r/J/H diagnostics; actual NIR channel blocks wavelengths beyond 1.8 µm [S1] |
| Planned length | Saved 1000 frames / 1 s | 1500 frames / 2 s, not run | N; proposed 0.2 s discard, not a stability/convergence demonstration |
| Random seed | 1 | 1 | N; changed model/geometry prevents claiming paired atmospheric realizations |

## Conversions and assumptions that matter

**DM stroke.** The manufacturer lists 3.5 µm total surface travel and 7 µm total wavefront travel for this model [S4]. Near normal incidence, OPD = 2 × surface displacement. Assigning the model a symmetric half-limit of 3.5 µm OPD additionally assumes a midpoint flat bias and no stroke reserved for static correction. There is no second reflection factor in commands already expressed as OPD. The installed bias, incidence angle, modal/inter-actuator limits and remaining usable travel are not known here.

The Gaussian width follows `exp(−1/(2s²)) = 0.13`, giving `s = 0.495047`. This is a local shape approximation, not an influence-function measurement. The implementation normalizes peaks on the sampled pupil; edge response and the 197-centre mask therefore need separate review before interpreting coefficients as hardware actuator excursions. No additional guard ring was invented to force an actuator count.

**Camera and photons.** The camera model stores read noise after EM multiplication. The draft uses `117 / 300 = 0.39 e⁻` at the input; writing `0.39` directly into the output-noise field would suppress noise by another factor of 300. QE is applied once. The throughput value is treated as the full optical factor excluding QE; the NGS beamsplitter is not multiplied in again.

Full well (80,000 e⁻), EM-register capacity (800,000 output e⁻), conversion gain (15 output e⁻/ADU), bias (500 ADU), 16-bit digitization, CIC, pixel defects and calibration-master settings remain inherited **synthetic assumptions**. Their complete values are in the ledger. They are not validated HNü128 electronics or saturation thresholds.

The paper's old spectral discussion gives endpoints of 640–900 nm while its older table lists a different bandwidth. This draft explicitly chooses the endpoints, integrates a top-hat band, and keeps AB photometry. It does not silently import the paper's `6.9×10¹⁰` zero point into an incompatible magnitude convention. The sky number is also an explicitly assumed AB proxy.

**Atmosphere and time.** The listed layer fractions sum to one without renormalization. Wind vectors use `vx = v cos θ`, `vy = v sin θ`, with θ from model +x; sky orientation is not established. For the dome component, Table 6's 0.011 m/s is used, while the prose gives 0.0113 m/s. Altitudes are metadata for this on-axis geometric layer sum. Outer scale and frozen-flow screen generation remain this model's assumptions.

The standalone 750 Hz loop does not reproduce the original paper's 1500 Hz master clock with slower NGS integrations. Two queued frames are a software timing choice. One atmosphere sample per exposure also omits intra-exposure averaging. The slow dome layer makes a two-second scenario particularly insufficient for establishing long-term Strehl stability.

## Model gaps and limits of comparison

The largest unresolved differences are the independent tip-tilt loop, measured DM/pupil maps, NGS sampling and binning, current controller timing, camera/stellar calibration, and static aberrations. Each has a structured entry in `candidate-config.json` under `model_gaps`. The later tip-tilt upgrade is not assumed installed merely because its planned date has passed [S3].

This draft changes diameter, spatial sampling, detector response, atmosphere and control together. It is a new instrument-inspired scenario, **not a one-variable stroke experiment**. The earlier ±1 versus ±100 µm 2 m comparison remains a separate experiment. Neither its trajectory nor its interaction matrix can be reused as the result/calibration for this new configuration. No Strehl mean, fluctuation, saturation fraction, or performance improvement is claimed here.

Before any future trajectory, the highest-value preparation is to resolve pupil/DM masks and tip-tilt treatment, confirm NGS pixel sampling and camera operating point, and assess calibration conditioning, numerical convergence and resource cost. Those checks and simulations are deferred; the present deliverable is the parameter choice and evidence record.

## Files and sources

- [candidate-config.json](candidate-config.json): separate system-profile and camera draft, source atmosphere table, limitations and execution status.
- [parameter-ledger.json](parameter-ledger.json): all config values classified, with baseline values and change flags.
- [sources.json](sources.json): source versions, exact sections/tables, applicability and unresolved research questions.
- [validation.json](validation.json): structure-only checks and execution exclusions.
- [manifest.json](manifest.json): artifact hashes and scoped before/after integrity.

[S1]: https://arxiv.org/html/2407.00582v1
[S2]: https://arxiv.org/html/2407.14677v1
[S3]: https://arxiv.org/html/2607.02826v1
[S4]: https://bostonmicromachines.com/products/deformable-mirrors/standard-deformable-mirrors/

**S1:** Baranec et al. (2024), *Commissioning results from the Robo-AO-2 facility for rapid visible and near-infrared AO imaging*, §§2.3, 2.5–2.6, 5.2. [Instrument paper][S1].

**S2:** Zhang et al. (2024), *Simulation results for Robo-AO-2 using HAPA*, §3.1 and Tables 5–7; §2.1 for inherited spectral assumptions. [Simulation paper][S2].

**S3:** Baranec et al. (2026), *Robo-AO-2: entering the era of automated science operations, hybrid wavefront sensing, and adaptive secondary integration*, §§3, 5. [Operating-mode update][S3].

**S4:** Boston Micromachines, *Continuous Deformable Mirror Standard Models*, 492-3.5 row. [Manufacturer specifications][S4].
