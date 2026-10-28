# DM stroke limits in the recorded 2 m and 42 m demonstrations

This is a read-only analysis of the existing one-second recordings. No atmosphere, calibration, control loop, or optical propagation was rerun. The analysis imports NumPy and Matplotlib, but does not import the AO package. No simulation configuration was changed. This public copy accompanies the website discussion.

## Findings

The 100-fold difference is an intentional difference between synthetic profile assumptions, not a hardware scaling law with telescope diameter. The 2 m run actually clips commands. The 42 m run never clips commands and uses less than 7% of its configured limit. Stroke is therefore a material confounding variable in a comparison of these demonstrations. These records do not isolate how much of the difference in Strehl variability is caused by stroke.

The 2 m Strehl also varies strongly during sustained intervals without clipping. It is not justified to explain all its variability by saturation, or to identify saturation as the dominant cause from these trajectories alone. The earlier aperture-scale interpretation needs this additional qualification: the controller and DM constraints are not matched.

| Quantity | 2 m | 42 m |
|---|---:|---:|
| Configured symmetric actuator-command bound, OPD | ±1 µm | ±100 µm |
| Recorded actuator-vector length | 13 | 5873 |
| Frame rate | 1000 Hz | 500 Hz |
| All recorded command updates | 1000 | 500 |
| Updates with at least one clipped actuator, entire recording | 306 / 1000 = 30.6% | 0 / 500 |
| Largest absolute requested command, entire recording | 1.127744 µm OPD | 6.918306 µm OPD |
| Updates in the analysis interval [0.2, 1.0) s | 800 | 400 |
| Updates with clipping in that interval | 174 / 800 = 21.75% | 0 / 400 |
| Mean clipped actuator fraction in that interval | 2.0096% | 0% |
| Largest number simultaneously clipped | 2 / 13 | 0 / 5873 |
| Largest absolute requested command in that interval | 1.096294 µm OPD | 6.818864 µm OPD |
| Largest single-command clipping loss in that interval | 96.294 nm OPD-equivalent | 0 |
| Recorded instantaneous peak Strehl, mean ± population SD | 0.575890 ± 0.081746 | 0.753544 ± 0.006409 |
| Pre-update residual RMS, mean ± population SD | 266.208 ± 60.438 nm OPD | 186.727 ± 2.856 nm OPD |
| Science wavelength | 1.65 µm | 2.20 µm |

An average of 2.01% of actuator-time entries being clipped is compatible with 21.75% of frames containing clipping: these are different denominators. Fractions use every actuator in the recorded vector, as the implementation does. For 42 m, 5328 of the 5873 command channels are nonzero at some point in this recording; zero command channels remain in the saturation denominator.

The common 2 ms sampling sensitivity check uses 400 samples from each recording over 0.200–0.998 s. It gives 85/400 clipped issued-command samples for 2 m and zero for 42 m. The 2 m Strehl mean/SD is 0.576048/0.081585, close to the native-sampling result. Native sampling remains the primary statistic because decimation can miss brief clipping events.

## Why the limits differ

The effective 2 m profile is `det_emccd_2m_synthetic@1`, derived from `fast_2m_detector@4`. The 1e-6 m OPD bound is already present in versions 1–4 of the fast 2 m profile. Its provenance is `synthetic_assumed`; no measured hardware stroke is established by that profile. The detector profile changes camera/calibration parameters and controller gain, retaining the base stroke.

The effective 42 m profile is `det_ccd_42m_r3band_derived@1`, derived from `eso_drm_42m_scao_derived@2`. Assumption A08 in `src/shwfs_ao/resources/benchmarks/eso_drm_42m_scao_derived.assumptions.v2.json` explicitly calls 100 µm OPD a finite engineering limit standing in for an unbounded DM. Its authority-source list is empty. A08 requires measured saturation to be exactly zero for this approximation to hold; the existing 42 m recording meets that condition.

The bound is implemented as `abs(requested) > limit`, followed by independent symmetric command clipping. It is not a loop gain or a slew-rate limit. Unused headroom above the requested command does not itself improve the correction in this model.

Other differences remain: gain 0.2 versus 0.3; leak 0.02 versus 0; Gaussian versus linear-spline influence functions; TSVD versus sparse LSMR/Tikhonov reconstruction; different actuator layouts, detector conditions, atmosphere structure, wavelengths, and sampling rates. Both use two queued latency frames, but their frame durations differ. “Comparable control efficiency” is an assumption, not a demonstrated property of this pair.

## Time alignment and relation to Strehl

The history stores the command requested and applied at the end of update k. The recorded pre-update optical metrics at frame k instead use the correction held from update k−1. Accordingly, the held clipping indicator is zero at frame 0 and equals the previous update's clipping indicator thereafter. This explains why the analysis window contains 174 clipped issued updates but only 173 observations holding a clipped command: the final update is beyond the last recorded exposure.

In the 2 m analysis interval:

| Held command classification | Frames | Mean Strehl | Strehl population SD | Mean residual RMS |
|---|---:|---:|---:|---:|
| At least one clipped actuator | 173 | 0.600548 | 0.078500 | 280.022 nm |
| No clipped actuator | 627 | 0.569087 | 0.081314 | 262.396 nm |

These groups are not matched atmospheric conditions. Their raw averages do not estimate the effect of clipping; in particular, the higher mean Strehl in the clipped group does not imply clipping is beneficial. The descriptive correlation of held clipped fraction with Strehl is +0.177, and with residual RMS is +0.071. No independent-sample significance claim is made for these autocorrelated series.

From t=0.200 through 0.518 s, all 319 recorded observations hold commands that were not clipped, yet Strehl ranges from 0.379867 to 0.722391. Another long unsaturated interval, 0.690–0.886 s, ranges from 0.488390 to 0.643445. Thus substantial variability exists without contemporaneous saturation. These intervals do not erase earlier closed-loop history, so they also cannot prove a zero historical contribution from clipping.

The largest 2 m clipping episodes in the analysis interval occur in issued updates around 0.518–0.619 s and 0.886–0.933 s, with interruptions detailed in `results.json`. The central actuator accounts for 146 clipped updates in that interval. A command loss measured in nm OPD-equivalent is an actuator coefficient loss, not automatically a pupil RMS wavefront error.

The controller uses the actually applied command as its next integrator state. Hence the saved requested commands already depend on earlier clipping. Merely removing the clipping from this saved sequence cannot reconstruct the closed-loop trajectory of a larger-stroke 2 m system. Likewise, clipping the recorded 42 m sequence at a smaller threshold would not produce a valid alternative closed-loop Strehl history.

For scale only, 46.7314% of 42 m actuator-time requests exceed 1 µm in the analysis interval, and every frame has at least one such request. At 5 µm, 0.1917% exceed the threshold; at 10 µm, none do. These are threshold counts on the original trajectory, not counterfactual performance results.

## Hardware units: when 100 µm can match ±100 µm OPD

At normal incidence, reflective mirror displacement h corresponds to optical path change 2h. For displacement along the surface normal at incidence angle θ, the geometrical relation is 2h cos θ. Our command coefficient is already OPD-equivalent and must not receive another factor of two.

If a manufacturer's 100 µm specification means total mechanical travel, a centered usable range is ±50 µm mechanical. At normal incidence that corresponds to ±100 µm OPD, exactly the numerical bound in this model. It would therefore be incorrect to claim these values necessarily disagree. Conversely, a 100 µm total optical travel specification would correspond to only ±50 µm OPD, and a ±100 µm mechanical bound would correspond to ±200 µm OPD at normal incidence.

The issue is the missing definition and calibration link, not an inevitable numerical mismatch. The ESO passage cited below says the M4 actuators have 100 µm stroke without specifying all these conventions in that passage. It does not by itself establish the operational centered OPD range for each independent actuator coefficient. Bias position, flattening/static offsets, incidence angle, spatial coupling, and offloading to other mirrors affect usable capability. The repository explicitly uses an unbounded-stroke surrogate rather than claiming a hardware-calibrated M4 model.

Actual hardware examples:

| Source | Published quantity | Interpretation |
|---|---|---|
| BMC Multi-C-1.5, Multi-3.5, Multi-C-5.5 | Physical stroke 1.5, 3.5, 5.5 µm; wavefront stroke 3, 7, 11 µm | A few µm of mechanical travel; the manufacturer's table explicitly separates physical and optical quantities |
| ESO ELT M4, Chiozzi et al. (2022) | Actuator stroke 100 µm | Large telescope-integrated adaptive mirrors can have a very different stroke scale; the quoted passage alone does not fully define a symmetric OPD bound |

BMC describes flat maps typically at 50% deflection. Under the ideal centered, normal-incidence conversion, its 3.5 µm total mechanical stroke corresponds to ±3.5 µm OPD, before operational reservations and coupling. This is a conversion example, not a specification for our synthetic DM. See the [BMC specification table](https://bostonmicromachines.com/products/deformable-mirrors/standard-deformable-mirrors/) and [BMC FAQ, flat-map and deflection sections](https://bostonmicromachines.com/products/deformable-mirrors/deformable-mirror-faq/).

The [ESO 2022 paper](https://www.eso.org/~gchiozzi/MyDocs/SPIE2022/12189-48-The_ELT_high_level_coordination_and_control.pdf), PDF pages 2–3, describes the 100 µm actuator stroke and redistributing slowly accumulating modes to other mirrors. It supports the importance of stroke management, not the exact parameterization of this repository.

## Focused literature check and applicability

Research question: can actuator clipping and integral-state handling affect AO performance, and does the existence of saturation establish the cause of the observed variability difference?

Searches covered AO actuator saturation/anti-windup, stroke-limited ELT simulations, BMC physical versus wavefront stroke, and ESO M4 stroke conventions. Material actually read:

- [Nagashima, Kim and Agrawal, *Comparison of the Performance of Modal Control Schemes for an Adaptive Optics System and Analysis of the Effect of Actuator Limitations*](https://faculty.nps.edu/agrawal/docs/DEPS_BC_12-BC-011%20paper.pdf), introduction and anti-windup discussion, PDF pages 2, 13–14, and experimental discussion on pages 18–22. Saturation and the controller state both matter; their anti-windup algorithm is not the algorithm implemented here. Our controller explicitly acknowledges applied commands, so uncontrolled integrator windup is not established by observing clipping.
- [Basden et al. (2013), *Monte Carlo simulation of ELT-scale multi-object adaptive optics deformable mirror requirements and tolerances*](https://academic.oup.com/mnras/article/435/2/992/1033081), sections 2.3 and 3.3. It models finite stroke by clipping and compares performance across limits. Its MOAO/global-DM architecture and mechanical stroke conventions differ from these SCAO demonstrations. It supports the need for a controlled stroke comparison, not importing its numerical performance penalties into this case.
- BMC primary product documentation and the ESO 2022 paper, as cited above, for the hardware-unit question. ALPAO pages appeared in search but full-page/PDF retrieval failed; they are not used for quantitative conclusions here.

Resolved: the limit's meaning and provenance, actual clipping counts, headroom, and time alignment. Unresolved: the causal contribution of stroke to Strehl variance, and a full operational M4-to-model hardware mapping. A future causal check would hold all 2 m inputs fixed and vary only stroke, with matched seeds and explicit optical metrics. That would require a new run and was not performed.

## Evidence and publication

`results.json`, the two CSV histories and the PNG/PDF figure are byte-identical
to the completed local audit. `publication.json` retains the raw-history hashes,
configuration and producer identities, original analysis/report hashes and
checks. Source paths use scientific archive labels without workstation details.
The original analysis verified every inspected input before and after; none
changed. The public statistics preserve the original values and definitions.

Commands are in OPD-equivalent metres. RMS removes piston and retains tilt.
Strehl comes from each recorded propagated PSF at its own science wavelength;
it is not recomputed from the Marechal approximation. Population standard
deviations describe this one record and are not uncertainty estimates.
No CI, calibration, atmosphere, control-loop or optical-propagation run was
performed for this addition. The 42 m stroke surrogate is an intentional
approximation; the causal contribution of stroke to Strehl variability remains
unresolved.
