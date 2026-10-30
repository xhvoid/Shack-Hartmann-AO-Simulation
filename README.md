# AO Explorer

The static [AO Explorer](https://xhvoid.github.io/Shack-Hartmann-AO-Simulation/)
contains four main views: Overview, Explore the loop, Selected studies, and
Methods & evidence. The core examples are the 2 m demonstration, the 2.2 m
loss-of-lock investigation and the 42 m gain–delay comparison.

The browser selects and replays saved values. It runs no optical simulation.
The Python package and small runnable examples are on `main`.

## Preview and publish

```bash
python3 -m http.server 8000 --bind 127.0.0.1 --directory site
```

Open `http://127.0.0.1:8000/`. There is no JavaScript dependency installation.
After editing the HTML, scripts or styles:

```bash
python3 tools/site_build.py --web-dir site --write
python3 tools/check_bindings.py --web-dir site
```

The build tool renames the code directory from its content hash and updates
the HTML and data entry together. Do not rename a hashed bundle by hand.
Commit to `website` with `[skip ci]`. Then open **Actions → Explorer Pages →
Run workflow**, select `main`, and run it once. The manual workflow checks
out `website`, verifies bundle bindings and publishes `site/`; it runs no
simulation or general test suite.

## Files and scientific records

- `site/index.html`: view structure and public text; earlier section anchors
  still open the corresponding view.
- `site/code-<hash>/`: browser modules and styles, including hash navigation.
- `site/data/`, `site/derived/`, `site/recordings/`: compact saved datasets.
- `site/evidence/`: a scoped numerical-check summary and unchanged numeric records.
- `tools/`: publication checks and exporters needed for the retained studies.
- `tests/`: focused saved-data exporter checks.

Every active bundle retains its original scientific identity, member sizes,
SHA-256 values and source references. Images, metrics and failed frames are
not regenerated during presentation edits. The 2 m, 2.2 m and 42 m experiments
have separate clocks. The 2.2 m replay updates its native telemetry cursor at
exact saved image times; telemetry can also be inspected between snapshots.

Superseded Orion/NGC 602 illustrations and the old 180-frame demo are no longer
in the current tree. Their complete bytes were preserved locally before
removal and remain in Git history. The selected Westerlund 2 example retains
the JWST source PSF and noise: it shows additional simulated blur, not a
prediction of an actual observation.

## Recompute saved-data summaries

The 42 m exporters read compact evidence packages; they do not create an AO
model. See [gain-study methods](tools/gain42_notes/README.md) and the
[dated corrections](tools/gain42_notes/CORRECTIONS.md).

```bash
python tools/export_gain42.py --validate-bundle site/derived/gain42-2a47efeb7c51bd13
```

To export again from the original evidence archives, use
`tools/export_gain42.py --help` or `tools/export_42m_studies.py --help`.
NumPy is required. Every input must match its recorded identity; image metrics
come from the pinned analysis, while scalar summaries and paired intervals
are recomputed. Full-precision PSFs and original run archives are not bundled.

The Westerlund 2 renderer (`tools/westerlund_scene.py`) similarly requires the
original OPD archive and retained calibrated cutout. `tools/westerlund_mp4.py`
encodes its saved frames. Serving or rebuilding the page requires neither.

Run only checks affected by an exporter change, for example
`python -m pytest tests/test_gain42.py`. No routine edit calls for full
scientific simulations or general CI.
