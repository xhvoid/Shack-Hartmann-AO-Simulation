# Development and releases

`main` is the integration and publication branch. The explorer serves only
committed, precomputed data; no Python service is needed in production.
The [release requirements](docs/research/ao_2m_interactive_v1/RELEASE_REQUIREMENTS.md)
and [acceptance record](docs/research/ao_2m_interactive_v1/ACCEPTANCE_REPORT.md)
define the scientific and browser contracts.

## One branch and environment per task

Start each task with a clean, isolated checkout. Record the synchronized base
commit in the task and PR. Never switch or clean another task's checkout.

```bash
git fetch origin main
git rev-parse origin/main
git worktree add -b codex/topic ../ao-topic origin/main
cd ../ao-topic
```

Use `codex/<topic>` for local branches. A cloud service may require its own
branch prefix; use its distinct task branch. Give one writer responsibility
for each working branch. Local and cloud tasks must not push to the same
branch concurrently. Transfer ownership explicitly before resuming a branch.
Synchronize with the accepted `main` before starting the next task. Do not
force-push, rewrite shared history, or replace scientific baselines.

## Setup from a fresh clone

A static preview needs only Python's standard library:

```bash
python3 -m http.server 8000 --bind 127.0.0.1 --directory web/ao-explorer
```

Open `http://127.0.0.1:8000/`. For a project subpath, serve `web` instead and
open `/ao-explorer/`. Use HTTP locally and HTTPS publicly; `file://` is not
supported. There is no JavaScript package installation or frontend build.

For validation, create a separate environment. On Linux x86-64 with Python
3.14, the complete CI profile is:

```bash
python3.14 -m venv .venv
. .venv/bin/activate
export PIP_CONSTRAINT="$PWD/constraints/py314.txt"
python -m pip install -e '.[test,notebook-test,lint]' build
python -m pip check
python scripts/verify_environment_lock.py --constraints constraints/py314.txt
```

On Linux x86-64 Python 3.10 use `constraints/py310.txt` and
`'.[test,notebook-test]'` plus `build` instead. These complete profiles support
exact lock verification. A smaller `.[test]` installation constrained by the
same file supports focused explorer checks but is not the complete verified
lock. Platform locks are not interchangeable; consult
[constraints/README.md](constraints/README.md) for macOS arm64 and HCIPy.
Do not alter locks or regenerate accepted resources for a website edit.

## Checks available with committed assets

```bash
python scripts/ao_explorer/site_build.py --web-dir web/ao-explorer
python scripts/ao_explorer/validate.py --web-dir web/ao-explorer
python -m pytest -q -rs tests/ao_explorer
python -m ruff check scripts/ao_explorer tests/ao_explorer
```

The suite includes tiny deterministic contract fixtures. It does not regenerate
the production trajectories. Eight retained-evidence derive checks skip in a
fresh clone; record them as skipped, never passed. Keep full Git history for
historical source-digest tests (`git fetch --unshallow` if needed). The existing
CI also checks Python 3.10/3.14, wheels, notebooks and static types.

Memory/pressure enforcement is **disabled by default**, including future local
and cloud checkouts. Normal checks can run directly as above. Timeouts,
process cleanup and two native threads remain available independently. Records
state whether memory enforcement was enabled; an unenforced estimate is not a
measured or enforced memory cap. Set `AO_RESOURCE_GUARD=1` only when deliberately
opting back in. See [RESOURCE_POLICY.md](RESOURCE_POLICY.md).

No new production data, calibration, ensemble or large-aperture study is
implied by this setting. Scientific scope and cumulative evidence limits remain
separate from the optional memory guard.

## Checks requiring retained local evidence

Raw evidence is intentionally ignored and is not transmitted by Git. A cloud
checkout has no local paths, environments or credentials. A maintainer with
the retained `series-2m180-b3e1c66` evidence can additionally run:

```bash
python scripts/ao_explorer/validate.py --web-dir web/ao-explorer \
  --series-dir /path/to/retained/series-2m180-b3e1c66
```

The derive-refusal tests currently discover evidence at
`outputs/ao_explorer_v1/series-2m180-b3e1c66`; a fresh clone skips those eight
checks. Use a separate local verification checkout with an explicitly supplied
copy or read-only link at that path. Do not commit raw evidence or silently
rerun successful science. Rendering/derive/export work must use the exporter
CLI and cumulative ledger: 1200 s numerical/processing wall time and
512 MiB raw evidence. The retained series already records 153.409918 s and
177,694,247 B before publication; preserve that history and add new consumption.

## Cloud work and local scientific integration

Configure the cloud environment to clone this repository, select `main`, use
the applicable setup above, and read this document and the release requirements.
Supply the exact base SHA and bounded task scope explicitly. Allow package
registry access during setup if needed; runtime website assets are all local.
Keep credentials in the service's supported connection, never the repository.

Review the cloud PR and its test logs. Bring it back into a new local checkout:

```bash
git fetch origin main pull/NUMBER/head:review/pr-NUMBER
git worktree add --detach ../ao-pr-NUMBER review/pr-NUMBER
```

Verify the fetched head SHA against the PR. Check the delta against its stated
base, run committed-asset checks, then run any applicable retained-evidence
checks locally before integration. Changes to scientific semantics, producer
identities or exported data need scientific review. A cloud green check cannot
substitute for missing raw-evidence verification. Merge the reviewed PR only
after the appropriate CI succeeds. Preserve unrelated work.

## Publication and rollback

`.github/workflows/pages.yml` validates both supported Python versions and
uploads only `web/ao-explorer`. PRs validate without deploying. Only a push to
`main`, or a manual workflow run explicitly on `main`, can publish. GitHub
Settings > Pages must use **GitHub Actions** as its source. Development
branches cannot replace the public site through this workflow.

After each release, record the merged commit, workflow run, public URL,
dataset ID, manifest SHA-256 and code build. Inspect the real public site:
case controls, playback, average PSFs, static binary observations, all research
groups, source links, nonempty downloads, missing assets, console errors and
375 px layout. A successful workflow alone is not browser acceptance.

To roll back, identify the last checked release SHA, create a new branch from
current `main`, and use ordinary revert commits for the release delta (a merge
revert needs the correct mainline parent). Review that PR and run the same
checks before merging. Do not reset `main`, force-push or hand-edit hashes.
Restore the complete matching page/code/data/validation set. A stale page must
continue to refuse an incompatible entry with a readable reload message.
