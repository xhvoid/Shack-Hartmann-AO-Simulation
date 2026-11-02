# AO Explorer: experimental generation interface

This branch is an experimental interface for the optional 2 m computation
service. It is not the version deployed to the public site. The published
[AO Explorer](https://xhvoid.github.io/Shack-Hartmann-AO-Simulation/) is built
from `website`; the current Python package and component repairs are on `main`.

The companion `feature/dynamic-phase` service still uses earlier component
implementations. Its October checks describe the recorded producers, not
the latest package. See its [version and validation scope](https://github.com/xhvoid/Shack-Hartmann-AO-Simulation/blob/feature/dynamic-phase/docs/research/ao_dynamic_v1/STATUS.md).

## Preview

```bash
python3 -m http.server 8000 --bind 127.0.0.1 --directory site
```

Open `http://127.0.0.1:8000/`. No JavaScript dependencies or Python simulation
are needed to serve the site.

## Update this experimental interface

After editing the page or scripts, update the code identifier:

```bash
python3 tools/site_build.py --web-dir site --write
```

Keep changes on this experimental branch and add the `skip-checks: true` trailer to routine
commits. The manual Pages workflow publishes `website`, not this branch.
Integration and deployment are separate decisions.

The recorded datasets include size and SHA-256 references. Preserve each
complete dataset and its references when updating the site. Source links
in the research panels point to the commits that produced those records.

## Generate a run

The generation panel connects to the optional computation service discussed
in [PR #8](https://github.com/xhvoid/Shack-Hartmann-AO-Simulation/pull/8), which
was closed without merging.
It contacts the address you enter only after you press **Connect**. No public
service is configured.

For a local preview, check out the service branch separately, install it,
then run this from that checkout:

```bash
python scripts/ao_dynamic/service.py --port 8765 --web-dir /path/to/website-checkout/site
```

Open `http://127.0.0.1:8765/?backend=/#generate`. The recorded experiments
and their data do not need the service.
