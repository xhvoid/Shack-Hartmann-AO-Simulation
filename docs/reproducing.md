# Reproducing the examples

The three examples in the README run using packaged configurations and small
cached resources. They require no archive account. They are useful entry
points, but they do not recreate every published recording.

| Material | Available publicly | Reproduction scope |
| --- | --- | --- |
| Python package | Source, versioned configurations and example entry points on `main` | Run the documented short examples or inspect their component construction |
| 2 m Explorer | Eight configurations, metrics, display assets and provenance on `website` | Replay the recorded samples and inspect all per-frame metrics; full-precision OPD/PSF archives remain local |
| 2.2 m investigation | Paired diagnostic records, replay samples, configuration identities and source extracts | Inspect the failure, regularization change and exact recorded comparisons; no claim of a one-command full rerun from `main` |
| 2.2 m off-axis example | Profile, example, validation script, tests and evidence records on `main` | Rerun the one-command example and compare its CSV with the recorded values; regenerate the analytic checks with the validation script |
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

These checks cover phase/OPD conversion, matrix-based reconstruction
including invalid rows, the directional sampling of the layered atmosphere,
the off-axis observer and its loop contract, the subpixel peak estimator, and
the physical sensor's handling of a background-oversubtracted lenslet. They
run short closed loops of the small layered 2 m profile; they do not run a
scientific trajectory and do not validate telescope hardware or the full
optical model. They are retained from the project's development tests; only
a representative subset is public here.

## Off-axis example

```bash
python -m pip install .
python examples/run_off_axis_science_demo.py --profile robo_ao2_22m_ngs_draft --version 2 --offsets "0,0;5,0;10,0;20,0" --wavelength-um 1.65 --burn-in 150 --block-frames 75 --output outputs/off_axis_science/22m
```

The command reruns the 2.2 m closed loop from its packaged profile and seed;
it needs 6 to 25 minutes on two threads, depending on the machine. Compare
`outputs/off_axis_science/22m/off_axis_strehl.csv` with
`docs/research/scao_off_axis_v1/evidence/demo_22m/regenerated/off_axis_strehl.csv`
(the recorded run, Linux x86_64) and with
`docs/research/scao_off_axis_v1/evidence/demo_22m/reproduction/off_axis_strehl.csv`
(a repeat from a fresh clone, macOS arm64). Repeats on one machine are
bit-identical, and a repeat on Linux x86_64 reproduced the recorded values
to 4e-6; across the two platforms the interpolated long-exposure peak
Strehls differ by up to 3.1e-3, more than the 1e-4 declared before the
repeat. The [off-axis science note](scao_off_axis_science.md) documents both
runs and what is known about the difference. The analytic checks of
the [validation record](research/scao_off_axis_v1/VALIDATION.md) are
regenerated with `scripts/off_axis_validation.py`; its `closed-loop` check
needs the example's output directory and a second 1500-frame run.

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
CI. Add the `skip-checks: true` trailer to routine commits. Run only checks affected by the change
unless broader validation is explicitly requested or the change is unusually
substantial. The manual Explorer Pages workflow is required for publication.
Do not rewrite historical commits or replace frozen results to simplify a page.
