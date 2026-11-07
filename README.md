# AO Explorer

This branch holds the static [AO Explorer](https://xhvoid.github.io/Shack-Hartmann-AO-Simulation/)
site. It has four views, Overview, Explore the loop, Selected studies, and
Methods & evidence, built around three cases: the 2 m demonstration, the
2.2 m loss-of-lock investigation and the 42 m gain–delay comparison.

Nothing is simulated in the browser. The page replays values that were saved
when the experiments ran. The Python package and the runnable examples live
on `main`.

## Preview

```bash
python3 -m http.server 8000 --bind 127.0.0.1 --directory site
```

Then open `http://127.0.0.1:8000/`. There is nothing to install; the site has
no JavaScript dependencies.

## Rebuild and publish

After editing the HTML, scripts or styles, run

```bash
python3 tools/site_build.py --web-dir site --write
python3 tools/check_bindings.py --web-dir site
```

The build names the code directory after its content hash and rewrites the
HTML and the data entry to match, so don't rename a hashed bundle by hand.
Commits to `website` carry a `skip-checks: true` trailer.

To publish, open **Actions → Explorer Pages → Run workflow**, select `main`,
and run it once. The workflow checks out `website`, verifies the bundle
bindings and publishes `site/`. It does not run any simulation or the test
suite.

## Layout

- `site/index.html`: the view structure and all public text. Older section
  anchors still open the right view.
- `site/code-<hash>/`: browser modules and styles, including the hash
  navigation.
- `site/data/`, `site/derived/`, `site/recordings/`: the compact saved datasets.
- `site/evidence/`: a summary of the numerical checks and the numeric records
  they refer to, kept as they were produced.
- `tools/`: publication checks and the exporters for the retained studies.
- `tests/`: checks for the saved-data exporters.

## Saved data

Each dataset keeps the sizes, SHA-256 values and source references it was
recorded with, and editing the presentation never regenerates images, metrics
or failed frames. The 2 m, 2.2 m and 42 m experiments run on their own clocks.
The 2.2 m replay moves its telemetry cursor to the saved image times, and the
telemetry can also be inspected between snapshots.

The earlier Orion and NGC 602 illustrations and the old 180-frame demo are no
longer in the tree; they remain in Git history. The Westerlund 2 example keeps
the JWST source PSF and noise, so what it shows is extra simulated blur on top
of a real image, not a prediction of an actual observation.

## Recompute the saved-data summaries

The 42 m exporters work from compact evidence packages; they do not rebuild an
AO model. The method is described in the [gain-study notes](tools/gain42_notes/README.md)
and the [dated corrections](tools/gain42_notes/CORRECTIONS.md).

```bash
python tools/export_gain42.py --validate-bundle site/derived/gain42-2a47efeb7c51bd13
```

To export again from the original evidence archives, see `--help` on
`tools/export_gain42.py` or `tools/export_42m_studies.py`. NumPy is required,
and every input has to match its recorded hash. Image metrics come from the
pinned analysis; scalar summaries and paired intervals are recomputed. The
full-precision PSFs and the original run archives are not in this branch.

The Westerlund 2 renderer, `tools/westerlund_scene.py`, likewise needs the
original OPD archive and the calibrated cutout, and `tools/westerlund_mp4.py`
encodes its saved frames. Neither is needed to serve or rebuild the page.

The exporter tests live in `tests/`, for example
`python -m pytest tests/test_gain42.py`.
