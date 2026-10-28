# AO Simulation Explorer

A static, buildless site with four sections:

- **Explore 2 m** — a precomputed native 2 m Shack-Hartmann SCAO experiment
  (`det_emccd_2m_synthetic@1`, seed 1) in eight recorded cases. The active
  dataset has 1000 frames at 1 kHz (the physical interval [0.000, 1.000) s)
  on a 624 × 624 `native_frozen_flow_v2` screen, a predeclared 200-frame
  startup exclusion and equal-weight means over frames 200–999 (800
  frames). The page shows synchronized wavefront maps, instantaneous and
  analysis-window-average PSFs, per-frame metrics of all 1000 frames,
  100 ms block summaries, a synthetic binary observation and an
  observed-galaxy view: the central region of NGC 1705 from the LEGUS
  HST/WFC3 F814W mosaic, at its real angular scale, seen through the
  recorded PSFs. Playback replays a deterministic subset of 126 actual
  frames (every 8th frame and frame 999) at their recorded timestamps, with
  one pass over the 1.000 s taking 20, 25 or 30 s; the main viewer and the
  galaxy panel share one playback state and clock, so both always show the
  same case and recorded frame. All 1000 PSF pairs and
  their galaxy observations are kept at full precision outside the site.
  The earlier 180-frame dataset and its galaxy derivative are preserved
  unchanged and are not combined with it.
- **Behind the simulation** — three short topic panels: the ten-layer
  atmosphere, the large-system architecture, and checks and limits. The layer
  profile and structure-function plot come from the unchanged saved records.
- **Explore 42 m** — one fixed exploratory ten-layer trajectory: 500 frames
  at 500 Hz, 126 recorded replay snapshots, 2.2 µm PSFs and a real HST binary
  template convolved with those PSFs. OPD maps, per-frame RMS, Strehl and images
  share a timeline independent of the 2 m controls. Means use all 400 frames
  in the predeclared 100–499 analysis window. This is a historical 42 m
  DRM-derived configuration, not a current 39 m ELT instrument prediction.
- **Appendix** — collapsed records for the 12 m detector studies, analytical
  MCAO, historical 42 m runs and other experiments. All eight original groups
  (R1–R8), evidence downloads and deep links are retained. Full methods and
  observable definitions are also collapsed here.

The browser only selects and replays validated recorded data. It does not
simulate, interpolate between cases, draw noise or compute metrics from
images.

## Local preview

The page loads its data with `fetch`, so it needs HTTP; opening `index.html`
from the file system is not supported. From the repository root:

```bash
python3 -m http.server 8000 --bind 127.0.0.1 --directory web
```

Then open `http://127.0.0.1:8000/ao-explorer/`. The site also works from the
root of a server (`--directory web/ao-explorer`, then `http://127.0.0.1:8000/`)
or any deeper project subpath: every member is resolved relative to the JSON
that names it. It makes no external network requests. `crypto.subtle` (used
to verify every member's SHA-256) is available on `localhost`/`127.0.0.1`
and on HTTPS origins.

## Layout

```text
index.html                      page (system fonts, no framework)
code-<build>/styles.css         layout
code-<build>/app.js             2 m experiment controller
code-<build>/galaxy.js          observed-template galaxy view
code-<build>/playback.js        the one playback state and clock both panels operate
code-<build>/results.js         topic evidence and lazy appendix rendering
code-<build>/replay42.js        fixed 42 m recording and independent timeline
code-<build>/charts.js          canvas charts of recorded values
code-<build>/integrity.js       size + SHA-256 verification, relative resolution
data/current.json               entry: dataset id, manifest size/SHA-256, code build,
                                and the galaxy derivative it is paired with
data/<dataset-id>/manifest.json every member with size and SHA-256
data/<dataset-id>/cases/<id>/   case, metrics (JSON/CSV), config, provenance,
                                display atlases, average PSFs, observations
data/<dataset-id>/scene/        the shared binary scene and its reference image
data/<dataset-id>/research/     results.json, byte-identical figures and evidence,
                                source-bound extracts of saved notebook outputs
validation/                     external export and manifest-validation records of the
                                earlier 180-frame dataset (they do not cover the active one)
derived/<derived-id>/manifest.json  galaxy derivative: every member with size and SHA-256,
                                bound by the `galaxy` block of data/current.json
derived/<derived-id>/scene/     the observed template's preparation record and display image
derived/<derived-id>/cases/<id>/ galaxy record, sampled atlases and mean images per case
derived/rms-<...>/manifest.json RMS diagnostics: residual RMS after tip/tilt removal of every saved
                                residual map, bound by the `diagnostics` block of data/current.json
derived/rms-<...>/cases/<id>/   rms.json per case (1000 values, window means, source digests)
recordings/42m-500-<hash>/      immutable 42 m data, atlases, scientific source and run evidence
```

A galaxy derivative has its own identities and manifest and names the dataset
and manifest digest it was derived from. The active one is written by
`scripts/ao_explorer/long_export.py` together with the 1000-frame dataset,
from the archived per-frame PSFs and mean PSFs of each case and the prepared
full-precision NGC 1705 template (reused, not rebuilt from the FITS
products); see `docs/research/ao_2m_interactive_v1/ONE_SECOND_DATASET.md`.
Its active records are a metadata revision written by
`scripts/ao_explorer/long_metadata_revision.py` (a corrected flux-file
reference). The revision directory holds only the revised JSON; its image and
scene references resolve to the exported directory's original files in place.
The earlier derivative of the 180-frame dataset was written by
`scripts/ao_explorer/galaxy_export.py`; see
`docs/research/ao_2m_interactive_v1/GALAXY_OBSERVATION.md`. Both keep their
full-precision arrays outside the site.

The RMS diagnostics are a separate scalar derivative written by
`scripts/ao_explorer/rms_diagnostics.py` (and by `long_export.py` for a new
export) from the archived residual maps; the dataset and its images are
unchanged by it.

Images that are byte-identical between cases (the atmosphere maps,
uncorrected PSFs and uncorrected observations of the six cases that share the
baseline atmosphere) are stored once and referenced by every case that uses
them; each reference still carries the member's size and SHA-256.

The dataset directory name changes with every export, so a browser cache can
never mix two exports. The manifest is bound by `data/current.json` and by the
validation record; it never hashes itself.

The code is content-addressed too: `<build>` is the first 16 hex digits of the
SHA-256 of `index.html` (build references normalized) and every file of the
code directory, `index.html` names that directory, and the modules import each
other relative to it. A changed script is therefore a new URL that no browser
cache can answer with older bytes. `data/current.json` records the build it was
published with (it is always fetched with `cache: "no-store"`), and the page
refuses an entry of another build -- for example a heuristically cached older
`index.html` meeting a newer entry -- with a request to reload, instead of
running older code on newer data. After changing any code file, run

```bash
python scripts/ao_explorer/site_build.py --web-dir web/ao-explorer --write
```

which renames the code directory to its new build and restamps `index.html`
and the entry; without `--write` it only checks. A future hosting step may
still serve `index.html` and `data/current.json` with `Cache-Control: no-cache`
so that visitors see a new version without the reload prompt.

## Producing and validating

The active 1000-frame dataset comes from `scripts/ao_explorer/long_series.py`
(plan, serial production, archives) and `scripts/ao_explorer/long_export.py`
(block summaries, observations, browser bundle, entry switch); its raw
numerical evidence stays in `outputs/ao_explorer_1s/<series-id>/`,
`outputs/ao_explorer_1s_derived/<dataset-id>/` and
`outputs/ao_explorer_galaxy/<derived-id>/`.

The earlier 180-frame dataset's producer, exporter and validator also live in
`scripts/ao_explorer/` (see the docstring of `export.py`). Its raw numerical
evidence — full-precision maps, numeric mean PSFs, loop histories and the
series plan — stays in the caller-owned `outputs/ao_explorer_v1/<series-id>/`
directory and is not part of this site.

```bash
python scripts/ao_explorer/validate.py --web-dir web/ao-explorer
```

checks the bundle's structure and semantics; add
`--series-dir outputs/ao_explorer_v1/<series-id>` to also bind it to the raw
evidence. Its rules were written for the 180-frame schemas (`*.v1`); it has
not been extended to, or run on, the 1000-frame dataset (`*.v2`) or its galaxy
derivative.

## The fixed 42 m recording

The `replay42` entry in `data/current.json` binds a separate manifest by size
and SHA-256. Its directory name is derived from the canonical member listing.
The browser verifies each data or image member before displaying it, loads
this section on demand, and retains a bounded atlas cache. A failed check
stops playback and identifies any remaining image as the last verified frame.

The real binary template is the MAST HST/ACS HRC F775W product
`j6kt02020_drz.fits` (program 9451, 2MASS J0746425+200032 AB).
It retains the original HST PSF and noise; convolution with a simulated
2.2 µm PSF demonstrates additional blur, not intrinsic K-band morphology or
the resolving power of a real 42 m telescope. All three panels retain one
angular scale and brightness mapping. Provenance and linear arrays are
available through verified downloads.

See `docs/research/ao_42m_replay/README.md` for production, packaging and the
independent publication checker `scripts/ao_explorer/portfolio_validate.py`.
It verifies this integration against the completed local recording and the
pre-integration site, without running the simulation or CI. The 17.1 GB raw
archive remains local; only the 66.5 MB browser recording is published.
