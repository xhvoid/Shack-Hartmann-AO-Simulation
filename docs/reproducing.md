# Reproducing the examples

The three examples in the README run using packaged configurations and small
cached resources. They require no archive account. They are useful entry
points, but they do not recreate every published recording.

| Material | Available publicly | Reproduction scope |
| --- | --- | --- |
| Python package | Source, versioned configurations and example entry points on `main` | Run the documented short examples or inspect their component construction |
| 2 m Explorer | Eight configurations, metrics, display assets and provenance on `website` | Replay the recorded samples and inspect all per-frame metrics; full-precision OPD/PSF archives remain local |
| 2.2 m investigation | Paired diagnostic records, replay samples, configuration identities and source extracts | Inspect the failure, regularization change and exact recorded comparisons; no claim of a one-command full rerun from `main` |
| 42 m gain study | Twelve compact records, paired statistics, methods, corrections and saved-data exporter | Recompute scalar summaries and paired contrasts from the bundled histories; full PSFs and original run archives remain local |

The current package is not a substitute for a recording's pinned producer
revision. Each bundle identifies its sources and configuration hashes. Source
revisions can differ from public `main`; use those identities when comparing
results. A missing raw archive is not silently replaced with a fresh trajectory.

## Small component checks

```bash
python -m pip install '.[test]'
python -m pytest tests
```

These checks cover phase/OPD conversion and matrix-based reconstruction,
including invalid rows. They do not run a scientific trajectory and do not
validate telescope hardware or the full optical model. They are retained from
the project's development tests; only a representative subset is public here.

## Website records

Use a separate clone for the website so package changes stay separate:

```bash
git clone --branch website --single-branch https://github.com/xhvoid/Shack-Hartmann-AO-Simulation.git ao-explorer
cd ao-explorer
python3 -m http.server 8000 --bind 127.0.0.1 --directory site
```

Open `http://127.0.0.1:8000/`. The website README describes the build stamp,
bundle checks and manual Pages deployment. No Python simulation runs in the
browser. All displayed scientific assets and downloads have explicit source
identities; full precision is retained in the data rather than rounded prose.

## Maintenance

Ordinary documentation, presentation and small maintenance changes skip general
CI. Use `[skip ci]` in ordinary commits. Run only checks affected by the change
unless broader validation is explicitly requested or the change is unusually
substantial. The manual Explorer Pages workflow is required for publication.
Do not rewrite historical commits or replace frozen results to simplify a page.
