# Reproducible Test Environments

Every profile in this directory is a **complete resolved environment lock**:
it pins, at exact versions, every distribution the lanes that name it
install — the extras they request, the full transitive closures of those
extras (including the Jupyter execution stack behind `notebook-test`), and
the `build` wheel frontend. `scripts/verify_environment_lock.py` runs in
every CI lane after installation and fails if any installed distribution is
missing from the profile or drifts from its pin, so identical profile hashes
describe identical environments. The `PIP_CONSTRAINT` job environment
additionally applies each profile inside pip's build isolation, so
build-backend resolution is locked too. Only `pip` itself (the resolver)
and this project (the subject under test) are outside a lock's scope. The
package metadata deliberately keeps compatible lower bounds so downstream
applications can resolve their own environments.

| profile | platform | scope |
| --- | --- | --- |
| `py310.txt` | Linux CPython 3.10 | `.[test,notebook-test]` + `build` (native CI lanes) |
| `py314.txt` | Linux CPython 3.14 | `.[test,notebook-test,lint]` + `build` (native CI + lint lanes) |
| `hcipy-py311.txt` | Linux CPython 3.11 | `.[test,hcipy,notebook-test]` + `build` (HCIPy lanes) |
| `hcipy-py314.txt` | macOS-arm64 CPython 3.14 | maintainer environment that generates and accepts the packaged cross-backend baseline; verified by `scripts/generate_cross_backend_candidate.py` |

Install the profile matching the interpreter:

```bash
python -m pip install -c constraints/py310.txt -e ".[test]"          # Python 3.10
python -m pip install -c constraints/py314.txt -e ".[test]"          # Python 3.14
python -m pip install -c constraints/hcipy-py311.txt -e ".[test,hcipy]"  # Python 3.11 + HCIPy
python -m pip install -c constraints/hcipy-py314.txt -e ".[test,hcipy]"  # Python 3.14 + HCIPy maintainer lane
```

To verify that an environment still matches its profile exactly:

```bash
python scripts/verify_environment_lock.py --constraints constraints/py314.txt
```

## Relocking a profile

Locks are regenerated **on the platform that runs them**, never by copying
versions between Python versions or operating systems (supported package
versions and marker-conditional dependencies differ; for example Python
3.10 needs `tomli` and `exceptiongroup` where 3.11+ does not).

For the three Linux profiles, run the manual `relock` workflow
(`.github/workflows/relock.yml`): each job resolves its profile's extras
fresh on the CI platform, emits the complete freeze with
`scripts/verify_environment_lock.py --emit`, prints the diff against the
committed profile, and uploads the freeze as an artifact. Review the diff
and dependency release notes, replace the profile body with the freeze,
keep the profile's header comment, and update the recorded profile hashes
in the AO-REF-000 contract manifest
(`src/shwfs_ao/resources/reference_metrics/refactor_contract_manifest.json`)
plus the resource manifest in the same commit — the contract tests fail on
any silent divergence. Run the full suite and the wheel smoke before
replacing a checked-in file.

The macOS maintainer profile is regenerated in place by running `--emit` in
the maintainer environment; changing it also changes the
`dependency_constraint_sha256` the packaged cross-backend baseline records,
so a maintainer-profile refresh requires regenerating and re-accepting the
baseline through `scripts/generate_cross_backend_candidate.py`.
