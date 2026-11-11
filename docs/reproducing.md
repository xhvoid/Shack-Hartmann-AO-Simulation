# Reproducing the examples

Each example uses the packaged profiles and data. Run it from the repository root after installation.

| Material | What you can reproduce |
| --- | --- |
| Detector, centroid and Strehl examples | Run the [three short scripts](../README.md#run-an-example) and inspect their measurements. |
| 2.2 m guide-star loop | Run either version of the profile. The [off-axis example](scao_off_axis_science.md) uses version 2 for all four science targets. |
| ESO-derived 5 m, 12 m and 42 m loops | Load version 3 for the published damping and filter settings. The [comparison tables](eso_scao_benchmark.md) include the frame counts and individual measurements from the longer scans. |
| 2 m Explorer | Replay the eight configurations and inspect their per-frame metrics on the website. |
| 42 m gain study | Recompute scalar summaries and paired contrasts from the twelve compact records on the website. |

The Explorer bundles identify the producer revision and configuration hash for each recording.

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
