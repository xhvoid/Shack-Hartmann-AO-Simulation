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

## Calibrated F164N image presentation

The Orion F164N panel is post-processing of the archived 2.2 m OPDs, not a new
AO trajectory. The renderer needs NumPy, SciPy, Astropy, Pillow and Matplotlib;
serving the website still needs none of them. Use two native numerical threads.

1. `python tools/fetch_science_source.py --output-dir /path/to/source`
2. Copy the active science bundle's `README.md` to `/path/to/source/METHODS.md`.
3. `python tools/science_scene.py --archive-root /path/to/archived-simulation-checkout --source-dir /path/to/source --web-dir site`
4. `python tools/science_mp4.py --ffmpeg /path/to/ffmpeg`
5. Restamp the site and publish as above.

The archive root must retain the two recorded trajectories named by the parent
replay's provenance. Original OPD hashes are verified before post-processing.
The download and render stages are separate; neither runs an AO controller.
Previous NGC 602 bundles remain available at their original immutable URLs.
