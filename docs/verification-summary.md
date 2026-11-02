# Component verification summary

Updated 2 November 2026, following the checks completed on 30 October–1 November.

I checked individual parts of the simulation against exact grid rules,
independent matrix calculations and saved results. The checks found several
boundary errors and a precision problem in dense reconstruction. This update
includes their fixes and the conclusions below. It does not replace the source
revisions or data used for the existing recordings.

## Repairs and their checks

| Component | Finding and repair | Result within the checked scope |
| --- | --- | --- |
| DM actuator layout | Rounded coordinates could drop points exactly on the retention circle. Membership now uses integer offsets and rational arithmetic. | An 11-across, zero-margin layout now retains 81 actuators rather than 77. The audited declared profile layouts were unchanged. |
| Pupil mask | Floating-point boundary tests could omit rim samples or make an obstruction or spider asymmetric. The tests now use exact sample offsets; obstruction ratio and vane dimensions follow their stated decimal values. | The scanned square and rectangular grids agree with exact membership rules. The audited declared pupil masks were unchanged. |
| Lenslet partition | Dense and compact geometry could assign samples on an interior edge differently. Both now use the same integer cell bounds. | Exact interval checks pass for both final-edge conventions. The modern partition includes the last outer sample; the legacy partition still excludes it. |
| Photon budget | A direct photon budget could bypass the check for negative subaperture area. | Negative area is rejected for every source kind; zero area remains allowed. |
| Flat-field processing | A zero lower threshold could keep a zero-response pixel and later divide by its response. Nonpositive flat responses are now always excluded. | Zero-response pixels are excluded correctly. The audited declared profiles already used positive lower thresholds, so they did not take this path. |
| Dense reconstruction | Forming a full inverse operator before applying it lost precision on a nearly singular matrix. The retained SVD factors are now applied in sequence. | Saved-matrix checks meet the original residual and stationarity bounds. Cutoffs, filters, rank gates and mask-cache behaviour are unchanged. |

The combined lenslet, spider and area check finished with 20 of 20 checks
passing. The before/after comparison covered pupil and compact geometry for
36 profiles in the development snapshot, including two unpublished draft
profiles. Dense geometry was compared for the 33 profiles with at most 400
samples across; the three larger dense representations were not built.
These counts describe that snapshot, not the number of profiles shipped here.

The no-mask atmosphere fallback keeps its documented legacy, FFT-centred
convention. It was not changed to match the sampled-pupil convention.

## Dense reconstruction: what improved

The difficult saved response matrix has 31 rows and 13 columns. Ten valid-row
masks were checked. Its diagnostic rank is 11, while least squares retains 13
modes under its separate numerical cutoff.

| Quantity across the ten masks | Before | After |
| --- | --- | --- |
| Normalized stationarity | 4.3972e-5–2.3447e-4 | 1.2626e-16–3.7274e-16 |
| Relative residual | 1.4544e-4–7.1575e-4 | 4.6815e-16–1.1815e-15 |

The predeclared limit was 1e-12 for both quantities. The original failures are
retained in the development records. The repaired kernel passed all 14 tests
in its focused verification, and the static coordinate-to-command checks
passed all eight tests. These are results from the completed verification,
not new runs made for this repository update.

The change also applies to TSVD and Tikhonov, which share the dense kernel.
It does not make poorly determined mode coefficients accurate. A rank gate
only accepts or rejects an estimate; it does not remove weak modes from an
accepted estimate. Zero-damping Tikhonov remains equivalent to least squares.
Choosing a cutoff or positive damping still needs a scientific justification.
The factor cache is larger in the checked example, so this is an accuracy
repair, not a memory or speed improvement.

## What this means for existing results

The final development review considered 28 claims and claim groups: 16 were
retained, 12 needed qualifications, and none was suspended. These are claim
decisions, not counts of passing tests. No existing scientific claim was
overturned by the available evidence. That does not establish that every
recorded trajectory would reproduce its displayed digits with the repaired
solver.

- **Small dense models.** The saved 2 m baseline and tutorial TSVD example
  have low retained condition numbers, about 2.83 and 3.2. This suggests low
  numerical risk, but neither historical trajectory was rerun with the
  repaired kernel. Some other dense-path records lack saved spectra or a
  complete producer trace. Agreement between two backends using the same
  reconstructor is not an independent check of that reconstructor.
- **Traced 42 m studies.** The frozen paths for the static comparison, C1
  noise calculation, photon-budget, bright/faint, latency, gain–latency and
  replay studies do not use the repaired dense kernel. This conclusion is
  specific to those traced producers; it is not a claim about every 42 m
  result or the physical accuracy of the telescope model.
- **Image sampling.** The production EE50 estimator remains unconverged in
  the recorded padding comparison. Its Fourier-reference counterpart is
  stable there. The two results should not be combined into a general
  convergence claim.
- **Sensing uncertainty.** The R1 x covariance comparison remains
  inconclusive: ratio 1.0928, interval [0.8935, 1.2922]. It is not counted as
  an equivalence result. The family of comparisons remains 32 equivalent,
  one inconclusive and none established as non-equivalent.
- **42 m regularization.** C1 selected damping 0.0025 as its admissible
  static comparator against 0.001. The predicted detector-noise RMS benefit
  was about 0.0042 nm, below the study's 1 nm and 10% variance triggers.
  This is a predicted noise component, not a measured closed-loop
  improvement. It did not trigger the proposed C3 closed-loop comparison.
  The earlier T1c/T4 failures and the historical I conclusion remain in
  place; adequacy across closed-loop conditions is still unresolved.

The static checks of DM response, stroke and faults, interaction matrices,
probe grouping and command mapping apply to the tested fixtures. They do
not establish closed-loop stability, telescope-scale performance or hardware
accuracy. Later bounded-fit tests that also use the labels T1/T4 do not
supersede the earlier 42 m failures.

## Evidence and reproduction limits

The independent reference scripts, new development tests, raw logs and saved
arrays are archived separately. This update publishes their final summary;
it does not include the full verification suite or raw archive. The small
[public component tests](../tests/) remain available. See also
[model conventions](methods.md) and [reproduction scope](reproducing.md).

For this integration, the two existing public test files passed all 31 tests
under Python 3.14.3, NumPy 2.5.0 and SciPy 1.18.0. All seven changed modules
were imported from the separate public checkout. This is a small integration
check, not a rerun of the development verification or a CI result.

For matching this summary to the archived evidence, the reviewed dense
reconstruction module has SHA-256
`0d43708e4f451fb2afddaef26a07e19bd5d9631d4a23d2ddd36a8ab0fb36da4c`.
Its B1-14 evidence index has SHA-256
`2090a6d68ae25edb738dff6dc1277820faad94d37b279f4aff8dde9af907171b`.
The final conclusions include the two subsequent errata: TSVD shares the
repaired kernel, and C1 did select a comparator.

Historical numbers, failures and source identities remain as recorded.
There was no new scientific trajectory or hardware comparison for this
update.
