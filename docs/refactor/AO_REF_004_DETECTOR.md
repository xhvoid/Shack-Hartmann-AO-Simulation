# AO-REF-004 Canonical Detector Layer

AO-REF-004 moves detector configuration, realized pixel state, frame effects,
centroiding, and centroid-validity policy into `shwfs_ao.detector`. The
canonical modules depend on `shwfs_ao.core`, NumPy, and each other; they do not
import the legacy SH-WFS optics, interaction matrices, or AO control code.

## Configuration and realized state

`DetectorConfig` retains its eleven historical fields in their original order.
Two trailing fields make new behavior explicit:

- `prnu_mode="per_frame_legacy"` preserves the frozen per-call PRNU model and
  remains the compatibility default;
- `prnu_mode="persistent"` selects a fixed pixel-response map;
- `bad_pixel_fraction` requests a persistent generated defect map. An explicit
  `bad_pixel_mask` remains supported and is defensively copied.

The selected PRNU mode is included in both the configuration hash and the
configuration provenance references. Existing detector presets still produce
`per_frame_legacy` configurations unless a caller deliberately constructs a
persistent configuration.

`DetectorRealization` separates configuration from instrument state. It owns
immutable PRNU and bad-pixel arrays, the root seed, the realization stream ID
when a draw was required, and stable configuration/realization hashes. It
draws only from `detector.realization`. A keyed realization index replays the
same maps without depending on temporal detector draws.

The realization key covers only settings that physically determine those maps
(PRNU mode/RMS and fixed/generated defects). Changing photon budget, read
noise, exposure, saturation, quantum efficiency, or provenance reuses the same
realized detector under the same root seed and index.

## Frame effects and random domains

`apply_detector_effects` implements this order:

```text
normalized optical intensity
→ source-electron expectation and dark/background expectation
→ pixel-response multiplication
→ Poisson shot noise
→ Gaussian read noise
→ full-well clipping
→ bad-pixel response
→ optional negative clipping
```

The result is the immutable core `DetectorFrame`, including source,
background, pre-Poisson, PRNU, saturation, defect, negative-clipping, and
random-stream diagnostics. Background diagnostics contain dark plus
sky/electronic background and never include source signal.

`apply_legacy_detector_effects` preserves the one distinct branch of the
installed low-level `shwfs_detector.add_detector_noise` API: when `photons` is
`None`, the normalized input remains the source signal, per-pixel background
is added directly, seeded read noise is applied, and no Poisson draw occurs.
The older configured-detector helper also continues to accept `None` photon
budgets; in default compatibility mode that branch ignores
photon/background/PRNU stages but retains read noise, saturation, bad pixels,
and negative clipping. Explicit persistent mode instead applies its fixed PRNU
and background expectation deterministically, omits shot noise, and retains
named-stream read noise. Both compatibility rules are implemented in the
canonical layer rather than in legacy adapters.

Persistent operation uses separate `detector.shot_noise` and
`detector.read_noise` streams. Callers can pass a scoped provider per frame for
order-independent keyed replay. The compatibility mode uses one
`numpy.default_rng(seed)` and preserves the frozen PRNU → Poisson → read-noise
draw order exactly. Adding a draw in a persistent temporal domain cannot alter
the realized PRNU or defect maps.

## Centroid and validity contracts

Canonical centroid estimators return `CentroidEstimate` in absolute array
coordinates: `x` increases with column and `y` increases with row. The initial
implementations are center of gravity and thresholded center of gravity, both
with optional minimum subtraction. `CentroidConfig` is the reusable,
hash-ready selection record. Canonical estimators reject non-2-D and
non-finite images; zero or negative processed flux returns an explicit invalid
estimate with NaN coordinates.

`centroid_quality` retains the existing expected-signal CCD SNR,
intensity-weighted uncertainty, and detector-window clipping equations.
`evaluate_centroid_validity` applies the independent flux, peak-SNR,
uncertainty, and clipping thresholds and returns every flag plus the aggregate
`CentroidValidity` decision.

## Compatibility boundary

The installed `shwfs_detector` and `synthetic_instrument_data` APIs keep their
AO-REF-000 names and signatures. Their detector calls now delegate to the
canonical layer. The legacy centroid adapter converts absolute `(column, row)`
coordinates back to centered, upward-positive coordinates and retains the old
NaN-ignoring behavior only at that compatibility boundary. Existing profiles
stay in `per_frame_legacy`; persistent PRNU is not enabled silently.
