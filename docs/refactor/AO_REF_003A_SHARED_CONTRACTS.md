# AO-REF-003A Shared Contracts and Native Atmosphere

AO-REF-003A establishes the backend-neutral boundary used by later component
tickets. The canonical interfaces live in `shwfs_ao.core`; they import NumPy
but no detector, I/O, experiment, legacy, or optional-backend implementation.

## Result and component contracts

`shwfs_ao.core.types` contains the Section 4 measurement, detector, optical,
DM-command, synthesis, and reconstruction records. Constructors validate
ordered identities, units, dimensions, normalization, and finite samples under
their validity masks. Array inputs are defensively copied onto immutable byte
buffers, so callers cannot re-enable writes. Metadata is recursively checked
for JSON-safe repository values and stored through immutable mapping proxies.

`shwfs_ao.core.protocols` contains runtime-checkable structural protocols for
random streams, atmosphere, Shack-Hartmann optics, WFS measurement, DM
synthesis, reconstruction, command projection, control, and science
propagation. Implementations do not inherit repository base classes or expose
backend-library objects.

## Stable identity and randomness

Canonical component identities use `shwfs_ao.canonical_sha256.v1`. Supported
values are encoded through a typed, deterministic JSON representation;
mappings are key-sorted, arrays use normalized little-endian content
descriptors, and arbitrary object `repr`/`__dict__` state is rejected. Geometry,
calibration-row layouts, command coordinates, and component configs use
separate semantic namespaces. Detector-plane sampling records verify a hash of
their shape, angular pixel scale, and reference pixel, and their spot axes use
that reference convention. Dataclass encodings include an explicit schema/type
identity as well as declared fields. The historical `config_hashing` array
descriptor is now a compatibility facade over the canonical implementation.

`NamedRandomStreams` uses scheme
`shwfs_ao.random.sha256-json-pcg64-v1`. A SHA-256 digest of the immutable root
seed, registered domain, typed key, and scope path seeds explicit NumPy PCG64.
Persistent, keyed, and scoped streams cannot perturb other domains; resetting
the provider clears retained scoped generators and exactly replays their draws.
The required domains are:

```text
detector.realization
detector.shot_noise
detector.read_noise
calibration
atmosphere
ncpa
```

## Native atmosphere

`StaticOpdAtmosphere` and `FrozenFlowAtmosphere` implement the shared
`AtmosphereModel`. They return piston-removed OPD metres with NaN outside the
configured pupil, enforce nondecreasing absolute time, and expose immutable,
JSON-safe configuration metadata. Static user maps record realization
invariance explicitly.

The frozen-flow model preserves the existing Fourier draw order and periodic
nearest-integer `numpy.roll` discretization. Realization zero uses the root seed
directly and is bitwise compatible with the AO-REF-000 phase-screen and shifted
time samples. Indexed stochastic realizations use the named atmosphere stream;
resetting the same index and replaying the same times is exact.
