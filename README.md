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
