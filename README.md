# AO Explorer website

This branch contains the static [AO Explorer](https://xhvoid.github.io/Shack-Hartmann-AO-Simulation/).
The Python simulation package is on `main`.

## Preview

```bash
python3 -m http.server 8000 --bind 127.0.0.1 --directory site
```

Open `http://127.0.0.1:8000/`. No JavaScript dependencies or Python simulation
are needed to serve the site.

## Update and publish

After editing the page or scripts, update the code identifier:

```bash
python3 tools/site_build.py --web-dir site --write
```

Commit changes to `website` with `[skip ci]`. On GitHub, open **Actions →
Explorer Pages → Run workflow**, select `main`, and run it. That workflow
checks out `website`, verifies the saved data bindings and publishes `site/`.
It does not run simulations or the Python test suite.

The recorded datasets include size and SHA-256 references. Preserve each
complete dataset and its references when updating the site. Source links
in the research panels point to the commits that produced those records.

## Westerlund 2 F162M presentation

The active image replay reuses the approved 4.109 arcsec source context and
archived 2.2 m OPDs. It does not run an AO trajectory. The four science panels
share the wavefront replay's clock, 159 saved image times, all 1500 Strehl
measurements and the frame-736 first-rejection marker.

Use `tools/westerlund_scene.py --help` with the archived simulation checkout
and the approved static-preview directory, then `tools/westerlund_mp4.py
--ffmpeg /path/to/ffmpeg`. Use two native numerical threads. The renderer
verifies original input hashes and agreement with the accepted static images.
The bundle includes methods, single-band and saturation limitations, source
quality provenance, sensitivity results and the original static figures.

After changing the page, restamp and publish as described above. Previous
Orion F164N and NGC 602 bundles remain available at their immutable URLs.

## 42 m guide-flux and controller-delay records

Two later 42 m experiments are shown after the C1 panel, each from its own
bundle: `derived/flux42-r2-<id>/` (two 1000-frame r2 runs at 100000 and 1000
detected e⁻ per fully illuminated subaperture per frame) and
`derived/delay42-<id>/` (nine 500-frame records, delays 1, 2 and 3 frames in
realizations r0–r2; delay 2 reuses the photon-budget baselines and delay 3 in
r2 is the accepted second attempt). The exporter reads only the extracted
compact evidence packages and needs NumPy; it builds no AO model:

```bash
python tools/export_42m_studies.py --flux-root /path/to/bright-control/compact --delay-root /path/to/latency/compact --web-dir site --write
python tools/site_build.py --web-dir site --write
python tools/check_bindings.py --web-dir site
```

Every consumed file must match its package listing, the analysis records must
carry their accepted SHA-256 and every exported summary must match the
accepted values; otherwise nothing is written. A bundle identifier names the
generated display files; the scientific source identities are in its
`provenance.json`. Refusal tests: `python -m pytest tests/test_export_42m_studies.py`
(set `STUDIES42_FLUX_ROOT` and `STUDIES42_DELAY_ROOT` to include the
real-evidence check).

Copy decision for the delay study: the frozen study reports keep their text
and hashes. The page and bundle apply the review corrections LAT-R01 (the r2
excursion is described observationally, with no proven atmospheric cause),
LAT-R02 (r2's similar whole-window Strehl does not measure the excursion's
image effect), LAT-R03 (frame 338 → 344 span, second rise without a
simultaneous validity drop, partial validity recovery, 137 frames below 0.995)
and LAT-R04 (the ≈2.3 ratio is tied to mean-image Strehl, the three
realizations and gain 0.3).


## Integrator gain and controller delay

The gain view extends the earlier 42 m displays with six new gain-0.2 records
and six accepted gain-0.3 baselines. It preserves the existing recordings and
Westerlund 2 replay. It selects saved configurations; it does not simulate or
interpolate gains. Read [methods and limits](tools/gain42_notes/README.md) and
the dated [GL-R01 / GL-R02 corrections](tools/gain42_notes/CORRECTIONS.md).
The accepted cloud reports, archives and hashes are unchanged.

The dedicated saved-data exporter needs NumPy. With native thread limits set
to 2 and AO_RESOURCE_GUARD=0:

```bash
python tools/export_gain42.py --compact-root /path/to/accepted/compact --web-dir site --write
python tools/site_build.py --web-dir site --write
python tools/check_bindings.py --web-dir site
```

Run only the focused tests when changing this exporter or its bindings:
`GAIN42_REAL_BUNDLE=/path/to/gain42-bundle python -m pytest tests/test_gain42.py`.
Use `tools/export_gain42.py --validate-bundle /path/to/gain42-bundle` to validate
an existing bundle offline. These commands read saved records; they construct
no optical model. Image metrics are hash-bound accepted-analysis values;
residual summaries, validity statistics and paired intervals are recomputed.
Only new runs have windowed image summaries. The reused delay-3/r2 baseline is
completed attempt 2, with its interrupted first attempt retained in history.
