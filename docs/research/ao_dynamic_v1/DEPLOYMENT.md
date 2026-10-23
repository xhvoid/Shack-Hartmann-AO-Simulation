# Generated-experiment mode: setup, preview and backend connection

The published GitHub Pages site is static. It shows the **Generate an
experiment** section as *not connected* until a visitor connects a computation
service; the precomputed explorer and the Research Results never need one.
No public computation service exists for this site yet (see the last section).

## Install

Use a separate environment from a fresh clone (Linux x86-64, Python 3.14):

```bash
python3.14 -m venv .venv
. .venv/bin/activate
python -m pip install -c constraints/py314.txt -e '.[test]'
```

The service and its worker use only the package dependencies (NumPy, SciPy,
Matplotlib for the display tables) and the standard library (`http.server`).

## Local preview

Same origin (the service also serves the site):

```bash
python scripts/ao_dynamic/service.py --port 8765 --web-dir web
# open http://127.0.0.1:8765/ao-explorer/?backend=/ and press Connect
```

Separate origins (as with a published page):

```bash
python3 -m http.server 8000 --bind 127.0.0.1 --directory web
python scripts/ao_dynamic/service.py --port 8765 --allow-origin http://127.0.0.1:8000
# open http://127.0.0.1:8000/ao-explorer/?backend=http://127.0.0.1:8765 and press Connect
```

`?backend=` only fills in the *Service address* field; the page contacts a
service only after *Connect* is pressed. The service answers only Host names
of its bound address, `localhost`/`127.0.0.1` and names given with
`--allowed-host`, refuses POSTs that carry an unlisted origin, and requires
JSON bodies with a decimal `Content-Length` of at most 64 KiB. Options: `--storage-dir` (default
`outputs/ao_dynamic_service`; each service start uses its own
`<storage-dir>/<instance-id>/` namespace), `--job-timeout-s` (240),
`--abandon-after-s` (300), `--max-queue` (3 waiting jobs besides the running
one), `--max-runs-kept` (8 completed runs; older ones are evicted). Workers run
with two native threads; memory enforcement follows
[RESOURCE_POLICY.md](../../../RESOURCE_POLICY.md) (off unless
`AO_RESOURCE_GUARD=1`). Each service instance appends every job outcome and its
wall time to `service-ledger.jsonl` in its namespace.

In a cloud development container the same commands work; a browser outside
the container needs the port forwarded, which a cloud task session may not
provide. This feature was exercised there with headless Chromium (below).

## Checks

```bash
python -m pytest -q tests/ao_dynamic          # contract, admission, worker, service, page contract (Node), browser e2e
python -m pytest -q tests/ao_explorer         # the precomputed explorer is unchanged
python scripts/ao_explorer/site_build.py --web-dir web/ao-explorer
python scripts/ao_explorer/validate.py --web-dir web/ao-explorer
```

The page-contract test needs Node.js; the browser test needs Node.js with
Playwright and a Chromium build (`AO_E2E_NODE_PATH`, `AO_E2E_CHROMIUM`). Without
them those tests are skipped, never passed. Follow [AGENTS.md](../../../AGENTS.md)
before running checks or CI. The bounded feature validation is reproducible with
`scripts/ao_dynamic/feature_validation.py` (see [VALIDATION.md](VALIDATION.md));
do not repeat its successful runs.

## Remaining steps for public generation (not done in this assignment)

1. **Host.** Provision a Linux host or container you control (2 vCPU, ≥ 1 GiB
   RAM: the measured worker peak was 127 MiB for 64 frames and 179 MiB for
   180 frames with every frame kept for replay; 400-frame runs were not
   measured; disk for `--max-runs-kept` × about 26 MB). Install as above from
   the merged commit.
2. **Run the service** as an unprivileged, supervised process bound to
   localhost, with persistent storage and the published origin:
   ```bash
   python scripts/ao_dynamic/service.py --host 127.0.0.1 --port 8765 \
     --storage-dir /var/lib/ao-dynamic --allow-origin https://xhvoid.github.io \
     --allowed-host <public host name>
   ```
   The origin is `https://xhvoid.github.io` (no path); `--allowed-host` is the
   name the proxy forwards in the `Host` header. Never pass
   `--enable-test-faults` in production.
3. **TLS reverse proxy.** The page is served over HTTPS, so browsers block an
   `http://` service (mixed content). Terminate HTTPS at a proxy for a host name
   you own, forward to `127.0.0.1:8765`, preserve the `Origin` header, cap
   request bodies (64 KiB), and add per-client rate limits for `POST
   /api/v1/runs`. The service has no authentication: a public endpoint offers
   compute to anyone, so add an access control at the proxy if that is not
   intended.
4. **Verify the backend**: `GET https://<host>/api/v1/info` returns
   `ao-dynamic.api.v1` with `allowed_origins` containing the site's origin; run
   one small job (`n_frames` 16) and fetch its files.
5. **Connect the site.** After this branch is merged and the Pages workflow
   has published it, open
   `https://xhvoid.github.io/Shack-Hartmann-AO-Simulation/?backend=https://<host>`
   (or enter the address in the page), press Connect and perform a browser check: connect,
   run, replay, compare, cancel, downloads, 375 px. Configuring a default
   service in the page would change static-mode requests and needs a separate
   decision and page build.
6. **Operate.** Watch `service-ledger.jsonl` and the worker logs; keep the
   bounded queue and timeouts; plan storage clean-up of old instance
   namespaces. Only after steps 1–5 succeed may the site be described as able
   to generate new runs publicly.
