# AO Simulation Explorer

A static, buildless site with three sections:

- **Explore 2 m** — a precomputed native 2 m Shack-Hartmann SCAO experiment
  (`det_emccd_2m_synthetic@1`, 180 frames at 1 kHz, burn-in 40, seed 1) in
  eight recorded cases, with synchronized wavefront maps, instantaneous and
  post-burn-in-average PSFs, per-frame metrics and a synthetic binary
  observation.
- **Research Results** — the project's eight main result groups (R1–R8),
  shown from saved records, notebook outputs and figures of the repository.
- **Methods & Limits** — model families, observable definitions, evidence
  status, numerical limits and identities.

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
code-<build>/results.js         Research Results rendering
code-<build>/charts.js          canvas charts of recorded values
code-<build>/integrity.js       size + SHA-256 verification, relative resolution
data/current.json               entry: dataset id, manifest size/SHA-256, code build
data/<dataset-id>/manifest.json every member with size and SHA-256
data/<dataset-id>/cases/<id>/   case, metrics (JSON/CSV), config, provenance,
                                display atlases, average PSFs, observations
data/<dataset-id>/scene/        the shared binary scene and its reference image
data/<dataset-id>/research/     results.json, byte-identical figures and evidence,
                                source-bound extracts of saved notebook outputs
validation/                     external export and manifest-validation records
```

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

The producer, exporter and validator live in `scripts/ao_explorer/`
(see the docstring of `export.py`). Raw numerical evidence — full-precision
maps, numeric mean PSFs, loop histories and the series plan — stays in the
caller-owned `outputs/ao_explorer_v1/<series-id>/` directory and is not part
of this site.

```bash
python scripts/ao_explorer/validate.py --web-dir web/ao-explorer
```

checks the bundle's structure and semantics; add
`--series-dir outputs/ao_explorer_v1/<series-id>` to also bind it to the raw
evidence.
