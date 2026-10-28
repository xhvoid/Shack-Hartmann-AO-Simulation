# AO-REF-016A — HCIPy lenslet axes on their detector windows

Date: 2026-10-15. Working tree on `public-clean-main` (base `2e96d86`),
uncommitted. The fix is opt-in. No published profile, pinned hash, governed
baseline or cache moves. `high_order_10m_hcipy@4` is a draft and is **not
published**. The closed-loop confirmation at the published scale is
**NOT_RUN_RESOURCE_POLICY** (§6).

Evidence: `eso_scao_evidence/published_profile_window_bias.md` §1 and §6.

## 1. The defect

`HcipyShackHartmannOptics` measures each lenslet on its own
`W = N/n`-pixel block and centroids it about the block centre
`((W − 1)/2, (W − 1)/2)`. HCIPy focuses each block through a parabolic lens
whose vertex is the spot axis. In `high_order_10m_hcipy@1–3` that vertex is
the geometry's continuous cell centre. The cell edges are
`linspace(min x, max x, n + 1)` (`wfs/shack_hartmann/geometry.py:525`), and
the pupil grid is `linspace(−D/2, D/2, N)` (`core/geometry.py:125`). The cells
therefore run from the first to the last pixel **centre**: they are
`(N − 1)/n` pixels wide on `N/n`-pixel blocks. In column `c` the axis sits at

    (W − 1)/2 + δ_c,   δ_c = 1/2 − (c + 1/2)/n   (pixels)

The same holds in y. For 384 px and 48 lenslets, δ runs from +0.49 to −0.49 px.
The pixel blocks themselves are right: the geometry's lenslet masks coincide
with them, and the construction checks this.

The zero-phase reference calibration absorbs the offset only for a **flat**
spot. A window that is asymmetric about its spot truncates a broadened spot
unevenly. The centre-of-gravity shift then depends on the spot width, so it
is not the calibrated constant. The asymmetry has opposite signs on opposite
sides of the pupil. The mean (tilt) bias cancels, and a slope pattern
`s_x ∝ +x, s_y ∝ +y` remains. A closed loop holds the static defocus that
cancels it. The scaled analogue in the evidence note predicts −8 to −30 nm
rms of Noll Z4 for the published loop.

## 2. Options

| Option | Effect on the bias | Cost and risk | Verdict |
|---|---|---|---|
| A. Reference pixel at the true axis (per lenslet) | None. A slope is `c(φ) − c(0)` measured in one per-lenslet frame, so moving that frame's origin by δ cancels exactly. The window stays asymmetric about the spot. A window symmetric about a fractional axis would need resampling of the focal plane, which changes the detector model. | Small | Rejected: it relabels the centroid and does not fix it |
| B. Cell edges on pixel edges in the shared geometry (`linspace(min x − dx/2, max x + dx/2, n + 1)`) | Removed. Each cell centre is then its block centre. | `ShackHartmannGeometry` validates masks and centres against the hard-coded edges, and its hash covers the centres. It needs a geometry convention threaded through every backend and the geometry hash schema. The native optics never read the centres: their spot axis is the FFT canvas centre. | Rejected: shared risk for no native gain |
| **C. HCIPy lens vertices at the pixel-block centres** | Removed. The vertices are option B's cell centres: the mean of each block's sample coordinates. Every window is symmetric about its axis. | HCIPy adapter only. The shared geometry is not touched, so no geometry hash moves, including the @4 draft's. | **Chosen** |

Trade-off of C: `geometry.subaperture_centers_m` remains the partition label
from the continuous cells. For an opted-in HCIPy sensor it differs from the
optical axis by less than half a pupil pixel. No canonical code reads those
centres except the HCIPy adapter. The legacy facades read them, but they build
native geometries. The adapter checks that bound for every retained lenslet
and exposes the real vertices as `lenslet_vertices_xy_m`.

## 3. Implementation (opt-in; published behaviour is the default)

- **`backends/hcipy/shwfs.py`.**
  - New argument `HcipyShackHartmannOptics(..., lenslet_axis=)`:
    `"geometry_cell_center"` (default, @1–3) or `"pixel_block_center"`.
  - For the default, the optics config-hash payload is byte for byte the
    historical one.
  - The block-centred convention hashes its own vertices and adds a
    `"lenslet_axis"` key. This is the same pattern
    `calibration.py` uses for `clip_negative_pixels`.
  - HCIPy's closest-centre lenslet assignment still has to reproduce the
    block partition. That holds trivially with block-centred vertices.
  - New properties: `lenslet_axis` and `lenslet_vertices_xy_m`.
- **`backends/hcipy/factory.py`.** `build_wfs(..., lenslet_axis=)` forwards
  the value to the optics.
- **`experiments/scao.py`.** Passes `lenslet_axis` only for a profile that
  opts in, like `lenslet_batch_size`. The native factory and every factory
  written earlier therefore never see it.
- **`io/configs.py`, profile schema v6.**
  - New field `wfs.lenslet_axis`. A v6 record must state it; v1–v5 records
    must omit it.
  - A frozen `_WfsConfigSchemaV3` payload keeps the published nested WFS
    hashes of the v3–v5 records. Those are `eso_turbulence_2m_detector@1` and
    the eight ESO SCAO tiers.
  - A non-default value is refused under schema < 6, and for any sensor other
    than the HCIPy detector-level one.
- **`AO_REF_016_HCIPY_SHWFS.md`.** Corrected its claim that calibration
  absorbs the offset.

## 4. Analogue test

`tests/backends/hcipy/test_hcipy_lenslet_axis.py` is a WFS-only analogue of
`@3`:

- 80 px, 10 lenslets at the published 0.2083 m pitch, so cells are 7.9 px and
  δ runs ±0.45 px
- pad 4, 8-px windows, 750 nm, built through the registered factory
- no atmosphere model, DM or loop

Each check is parametrized over both conventions. The published one is a
strict `xfail(raises=AssertionError)`, so the check demonstrably detects the
defect, and @1–3 stay as published.

Results: **not run yet.** Memory pressure was at warn when this was
committed, so the supervisor refused every test job.

## 5. Draft `high_order_10m_hcipy@4`

`docs/refactor/drafts/high_order_10m_hcipy.v4.json` is a schema-v6 record.
It is `@3` with:

- `wfs.lenslet_axis = "pixel_block_center"`
- the keys that later schemas require, all at @3's values:
  `atmosphere.layers = []`, `wfs.clip_negative_pixels = true` (@3 clips) and
  `scalable = null`
- a new rationale, provenance note, `source_id` and references

`tests/io/test_configs.py::test_draft_high_order_10m_hcipy_v4_is_v3_with_only_block_centred_axes`
checks that it round-trips exactly. It also checks that it equals @3 in every
physical component except the WFS, keeps @3's observing conditions, and
differs from @3 only in the `profile`, `wfs` and (schema-v6-only) `scalable`
identities. `load_system_profile("high_order_10m_hcipy", 4)` still refuses.

To publish the draft, after the confirmation in §6:

1. Move the file to `src/shwfs_ao/resources/synthetic_presets/`.
2. Register it in `_PROFILE_RESOURCES` and `resource_manifest.json`.
3. Add it to `EXPECTED_PROFILES` and the wheel-install profile lists.
4. Pin its `config_hash` and nested WFS hash in `tests/io/test_configs.py`.
5. Remove the "no latest alias" @4 probe in that file.

## 6. Verification status

**NOT RUN YET: the analogue test, the factory and configuration tests, and
mypy.** They were written but not executed: memory pressure stayed at warn,
so the supervisor refused every job. Ruff passes.

**NOT_RUN_RESOURCE_POLICY: closed-loop confirmation at the published scale.**

- **Why it cannot run here.**
  - The dense HCIPy DM stack is 2401 × 384² × 8 B ≈ 2.8 GB, plus a copy.
  - The per-lenslet masks are ≈ 270 MB, plus a validation copy.
  - The audited raw peak is ≈ 6.5 GiB, or ≈ 13 GiB required with the 2×
    margin. That is above the 2 GiB ceiling of the desktop-safe budget on any
    host.
  - The dense DM is also one ≈ 2.8 GB buffer, far above the policy's 64 MiB
    ceiling for a single scratch buffer.
  - It needs a suitable host and an explicitly authorized, revised budget.
    `shwfs_ao.runtime.resource_guard` cannot provide that: its budget is
    `min(2 GiB, 12.5 % physical, 25 % available)` on every host and can only
    be lowered. It would refuse this job anywhere. The run needs a
    host-specific supervisor and a budget the user authorizes for that host.
- **Plan first** (prints the configuration and estimate, and builds nothing):

  ```bash
  .venv/bin/python docs/refactor/drafts/hcipy_lenslet_axis_closed_loop.py --scale published --realizations 4 --out out/hcipy-axis-published.json
  ```

- **The job itself**, under that host's authorized supervisor, 2 threads,
  about a 2 h wall limit:

  ```bash
  .venv/bin/python docs/refactor/drafts/hcipy_lenslet_axis_closed_loop.py --scale published --realizations 4 --run --enable-large-host --out out/hcipy-axis-published.json
  ```

- **Acceptance before publishing @4.**
  - The paired `Z4(@3) − Z4(@4)` is negative and outside 2 standard errors.
  - Its size is consistent with the −8 to −30 nm rms prediction.
  - `@4`'s mean Z4 is within its realization scatter of zero.
  - `@4`'s residual RMS after burn-in is no worse than `@3`'s.
- The full-size WFS-only probe (≈ 1.7 GiB required, for the dense per-lenslet
  masks) is NOT_RUN_RESOURCE_POLICY for the same reason.
