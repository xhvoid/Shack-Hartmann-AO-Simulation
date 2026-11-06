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

## Branches and evidence dates

`main` contains the package and the latest component repairs. `website`
contains the files used for the published static Explorer. A commit to either
branch does not deploy the site; publication uses the manual workflow below.

`feature/dynamic-phase` and `feature/dynamic-explorer` are an experimental
service and its companion interface. The service has not incorporated the
latest component repairs, and its October checks describe the producers
named in those records. They are not a validation of the current package or
a public computation service.

The Explorer keeps older results as dated records. Current interpretation
notes are separate from the frozen values. Two download copies omit a local
machine path or a temporary branch label; each is labelled as an edited
public copy and gives the original SHA-256 and source link. The originals
and their hashes remain available. These copies are for reading, not exact
byte-for-byte reproduction of the original files.

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
browser. Plots, tables and CSV share their named saved results; source identities and
full-precision values remain in the downloads.

## Maintenance

Ordinary documentation, presentation and small maintenance changes skip general
CI. Add the `skip-checks: true` trailer to routine commits. Run only checks affected by the change
unless broader validation is explicitly requested or the change is unusually
substantial. The manual Explorer Pages workflow is required for publication.
Do not rewrite historical commits or replace frozen results to simplify a page.
