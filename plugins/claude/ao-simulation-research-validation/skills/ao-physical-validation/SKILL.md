---
name: ao-physical-validation
description: Assess the physical consistency, assumptions, and evidential support of adaptive-optics models and performance claims. Use for AO physics or model validation; use numerical verification for convergence-only questions and code review for implementation-only defects.
argument-hint: "[observable, model, or physical claim to validate]"
---

# AO Physical Validation

Determine whether the implemented physical model and its claimed application agree.
Read [the common contract](../../references/common-contract.md) first. For local
owners and available model routes, consult [project integration](../../references/project-integration.md)
only when needed, then verify against the current source.

## Establish the physical question

- Identify the observable, input conditions, model selectors, backend, units,
  wavelength, time/exposure definition, and claim being assessed.
- Separate implementation consistency, suitability of an approximation, numerical
  accuracy, and agreement with laboratory/on-sky measurements. Analytic checks
  and cross-backend agreement do not constitute measured instrument validation.
- An audit is read-only by default. Run only checks within the user's requested
  scope and resource policy; do not retune the model or fix source implicitly.

## Wavefront and image definitions

- Write the internal wavefront as OPD `W(r,t)` in metres and phase as
  `phi(r,t; lambda) = 2*pi*W(r,t)/lambda`. Do not compare phase RMS across
  wavelengths without conversion, or treat an RMS in radians as nanometres.
- Define pupil support and weights. For nonnegative weights `w`, use
  `Wbar = sum(w*W)/sum(w)` and
  `sigma_W = sqrt(sum(w*(W-Wbar)^2)/sum(w))` when piston is removed.
  State whether weights represent uniform samples, area, or illumination;
  reject invalid values inside the participating pupil rather than filling zero.
- State whether tilt is retained, removed by a weighted fit, or handled by image
  alignment. Piston removal, tilt removal, and recentering answer different questions.
- At normal incidence a reflective surface displacement `h` produces OPD `2*h`.
  Respect any declared incidence geometry and sign. Commands already expressed
  as OPD-equivalent correction must not receive a second reflective factor.
- Define Strehl from a specified aberrated PSF and matching diffraction reference
  with the same pupil, wavelength/band, angular sampling, and flux convention.
  A peak ratio, an on-axis ratio, and a ratio after alignment are distinct.
- Use `exp[-(2*pi*sigma_W/lambda)^2]` only as the Maréchal approximation in its
  small-aberration/high-Strehl domain with consistent tilt/alignment treatment.
  It is not a general substitute for propagating an aberrated PSF.
- Long-exposure images average intensities, not OPD or complex amplitudes.
  Keep instantaneous metrics and averages of scalar metrics separately labelled.

## Inspect the relevant physical chain

- Atmosphere: trace phase/OPD PSD units and Fourier-frequency conventions, the
  reference wavelength of `r0`, outer scale, layer strengths/winds, normalization,
  frozen-flow assumptions, low-frequency treatment, and finite-screen coverage.
  RMS rescaling is an amplitude-controlled experiment, not ensemble normalization.
- Sensing: check local slope versus calibrated centroid units, diffraction scale,
  pupil/lenslet illumination, wavelength-dependent angular coordinates, pixel
  integration, finite windows, capture loss, and optical contamination assumptions.
- Photometry: trace collecting area, exposure, spectral flux, throughput and QE.
  For spectral energy flux `F_lambda`, photons scale as
  `A*dt*integral(F_lambda*T*lambda/(h*c), d_lambda)`; detected electrons include
  QE once. State spectral/band assumptions; incident photons and electrons differ.
- Cameras: follow expectation and noise through source/sky/dark/CIC, photoresponse,
  multiplication, coupling, readout, gain/bias, nonlinear response and saturation.
  Check the declared EM-gain regime and persistent-map/calibration lifetimes.
- Processing and uncertainty: distinguish the mean conditional on realized masters
  from calibration-ensemble error, shared-master covariance, estimator bias and
  temporal precision. Inspect unsupported clipping, threshold, ADC and low-SNR regimes.
- Correction/science: trace DM basis and stroke assumptions, calibration response,
  reconstruction objective, temporal transfer and residual definition into PSFs.
  Do not assign a combined residual to one physical error term without isolation.

## Evidence and conclusion

Apply the common contract's active-research loop to suspected physical
inconsistencies, unsupported assumptions, and unexplained departures. Search
and read the relevant primary literature, then compare its actual conventions
and applicability with this model before finalizing the finding.

Use independent analytic limits, dimensional arguments, controlled fixtures,
statistical estimators, and primary sources appropriate to the particular claim.
Specify expected behavior and uncertainty before judging a numerical result.
Numerical refinement belongs alongside physical checks when sampling can bias the
observable; refine one cause at a time with matched physical inputs.

Report the implemented model, source-supported domain, assumptions, checks actually
performed, and affected scientific conclusion. Classify findings using the common
contract. Preserve failed hypotheses and explicitly unresolved discrepancies; a
deliberate approximation is not automatically a software defect.
