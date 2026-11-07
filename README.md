# AO Explorer: experimental generation interface

This branch is an experiment: a version of the Explorer with a panel that can
ask a local computation service for new 2 m runs. It is not what is deployed.
The public [AO Explorer](https://xhvoid.github.io/Shack-Hartmann-AO-Simulation/)
is built from `website`, and the current Python package, with its component
repairs, is on `main`.

The service it talks to lives on `feature/dynamic-phase`, which still uses
older versions of the simulation components. The checks recorded there in
October 2026 describe those older versions, not the current package; see its
[version and validation scope](https://github.com/xhvoid/Shack-Hartmann-AO-Simulation/blob/feature/dynamic-phase/docs/research/ao_dynamic_v1/STATUS.md).

## Preview

```bash
python3 -m http.server 8000 --bind 127.0.0.1 --directory site
```

Then open `http://127.0.0.1:8000/`. There is nothing to install, and no Python
simulation runs when serving the site.

## Editing

After editing the page or scripts, refresh the code identifier:

```bash
python3 tools/site_build.py --web-dir site --write
```

Routine commits on this branch carry a `skip-checks: true` trailer. The Pages
workflow publishes `website`, so nothing here goes live on its own.

The recorded datasets carry their sizes and SHA-256 references. Keep each
dataset whole when editing the site; the source links in the research panels
point at the commits that produced those records.

## Generate a run

The generation panel connects to the computation service from
[PR #8](https://github.com/xhvoid/Shack-Hartmann-AO-Simulation/pull/8), which
was closed without merging. It only contacts the address you type in, and only
after you press **Connect**. No public service exists.

To try it locally, check out `feature/dynamic-phase` separately, install it,
and from that checkout run

```bash
python scripts/ao_dynamic/service.py --port 8765 --web-dir /path/to/website-checkout/site
```

then open `http://127.0.0.1:8765/?backend=/#generate`. The recorded
experiments and their data work without the service.
