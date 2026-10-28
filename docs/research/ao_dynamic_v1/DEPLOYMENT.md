# Run the computation service

The service computes seeded 2 m AO runs for the Explorer generation panel.
The page and the Python package now live on separate branches. No public
backend is deployed; the service has no authentication.

## Install

Use the `feature/dynamic-phase` checkout for the service. The worker uses
Unix process groups, so use Linux or macOS. The original numerical evidence
was collected with Python 3.14 on Linux.

```bash
python3.14 -m venv .venv
. .venv/bin/activate
python -m pip install -c constraints/py314.txt -e .
```

The retained constraint file records the environment used for that evidence.
Each run records the installed versions and any differences from the lock.
Installing on another environment does not reproduce the historical checks.

## Preview the page and service together

Check out `feature/dynamic-explorer` into a separate directory. From the
service checkout, pass its `site/` directory:

```bash
python scripts/ao_dynamic/service.py --port 8765 --web-dir /path/to/website-checkout/site
```

Open `http://127.0.0.1:8765/?backend=/#generate` and press **Connect**.
The query parameter only fills in the address; it does not start a request.
The generated default is the original 180-frame setup, separate from the
current one-second recording and its larger atmosphere screen.

For separate local origins, serve the website checkout with
`python3 -m http.server 8000 --bind 127.0.0.1 --directory site`, and run:

```bash
python scripts/ao_dynamic/service.py --port 8765 --allow-origin http://127.0.0.1:8000
```

Open `http://127.0.0.1:8000/?backend=http://127.0.0.1:8765#generate`.

## Service limits

One worker runs at a time with two native threads. Defaults are a 240-second
job timeout, 300-second abandonment lease, three waiting jobs and eight
retained completed runs. Cancellation stops the worker process group and
removes partial results. Every service start uses its own namespace under
`outputs/ao_dynamic_service`; outcomes are recorded in `service-ledger.jsonl`.

Memory enforcement is off by default; `AO_RESOURCE_GUARD=1` enables it.
Use `--storage-dir`, `--job-timeout-s`, `--abandon-after-s`, `--max-queue`
and `--max-runs-kept` to change the corresponding limits. Run the service
with `--help` for all options.

## Existing checks and evidence

The [validation record](VALIDATION.md), [review record](ACCEPTANCE.md) and
files in `evidence/` describe the original feature commits. They are retained
as historical evidence, not results for the revised branch.

When a maintainer explicitly requests these checks:

```bash
python -m pip install -c constraints/py314.txt pytest
export AO_EXPLORER_SITE=/path/to/website-checkout/site
python -m pytest -q tests/ao_dynamic
```

Without `AO_EXPLORER_SITE`, the page-specific tests skip when no legacy site
directory is present. Browser checks also require Node, Playwright and
Chromium (`AO_E2E_NODE_PATH` and `AO_E2E_CHROMIUM`). A skip is not a pass.
The feature-validation evaluator uses the retained `series-2m180-b3e1c66-e0d60cbaccc6b`
dataset in that site, rather than whichever dataset is currently selected.
Do not repeat numerical runs or start CI for routine maintenance.

## Public hosting remains separate

A public deployment needs a supervised worker on a Linux host, persistent
storage and an HTTPS reverse proxy. Bind the service to localhost, pass the
page origin with `--allow-origin`, and pass the forwarded host with
`--allowed-host`. The published page origin is `https://xhvoid.github.io`.

The proxy must bound request bodies to 64 KiB, limit run submissions and add
authentication if access should be restricted. Preserve `Origin` and
forward the expected `Host`; if the proxy rewrites `Host`, allow the page's
origin explicitly. An HTTPS page cannot connect to an HTTP backend.
Never enable test faults in production. Verify connect, run, replay,
comparison, cancellation and downloads before advertising a public service.
