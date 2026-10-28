# AO-REF-002 Wavefront Core and Unit Boundaries

AO-REF-002 centralizes wavefront masking, statistics, piston removal, and
phase/OPD conversion in `shwfs_ao.core.wavefront`. The canonical layer is
wavelength-explicit and uses optical path difference in metres. It contains no
implicit wavelength and no nanometre conversion.

## Canonical API

`shwfs_ao.core` re-exports exactly these wavefront operations:

- `remove_piston(values, mask)`;
- `masked_mean(values, mask)`;
- `masked_rms(values, mask, remove_mean=True)`;
- `phase_to_opd(phase_rad, wavelength_m)`;
- `opd_to_phase(opd_m, wavelength_m)`;
- `mask_outside(values, mask, fill=np.nan)`;
- `validate_masked_finite(values, mask, label)`.

Masked operations require matching shapes, a non-empty pupil, and finite values
at every illuminated sample. Conversion functions require a finite, positive,
explicit wavelength in metres. Returned arrays are deterministic floating-point
copies, so callers do not mutate their inputs through the result.

## Strict core and legacy compatibility

The core deliberately rejects any NaN or infinity where the mask is true. This
is the contract for all new code.

The pre-refactor public helpers in `zernike`, `phase_screen`, and
`reconstruction` historically selected only finite illuminated samples. Their
temporary compatibility adapters retain that leniency and delegate the actual
mean, RMS, and piston arithmetic to the strict core using the resulting finite
submask. The static DM fitting helper follows the same compatibility policy for
partially observed fitting targets. Existing diagnostics exception types and
messages are also retained at their public boundary. These policies live only
in legacy adapters; `masked_rms` itself never hides an invalid pupil value.

This distinction is covered by tests: canonical operations reject interior
NaN/Inf, while characterization tests freeze the legacy finite-submask result.

## Canonical physical-unit ledger

Shared runtime boundaries use OPD metres. Legacy units are converted exactly at
their adapter edge:

| Pipeline boundary | Canonical unit | Temporary legacy edge |
|---|---|---|
| Atmosphere output | m OPD | phase radians converted with the WFS wavelength |
| Residual input | m OPD | none after atmosphere/DM adaptation |
| WFS input | m OPD | converted to phase radians immediately before the legacy WFS |
| DM commands/output | m OPD-equivalent / m OPD | legacy command and output arrays use nm |
| Reconstructor output | m OPD-equivalent | legacy reconstructor returns nm |
| Controller history | m OPD-equivalent | legacy `LoopHistory` records nm |
| Science propagation input | m OPD | converted to phase using the science wavelength |

`tests/core/test_wavefront_unit_audit.py` exercises all seven named boundaries
with an exact miniature atmosphere/reconstructor/controller/DM/WFS/science
pipeline. It verifies that phase radians and nanometres do not cross a
canonical boundary and that the WFS and science wavelengths are independently
explicit.

## Migration scope

The following legacy implementations now delegate their duplicated operations
to the core while retaining their AO-REF-000 public surfaces:

- `shwfs_ao.legacy.zernike`;
- `shwfs_ao.legacy.phase_screen`;
- `shwfs_ao.legacy.reconstruction`;
- `shwfs_ao.legacy.ao_closed_loop`;
- `shwfs_ao.legacy.ao_diagnostics`;
- `shwfs_ao.legacy.dm_model`;
- the adjacent science conversion helpers in `shwfs_ao.legacy.psf_tools`.

The installed wheel and sdist contract includes the new `shwfs_ao.core`
package. Top-level legacy imports remain silent compatibility shims during this
ticket and retain their frozen call signatures and exported names.
