# Reproducible Test Environments

`py310.txt` and `py314.txt` pin the complete runtime, pytest, and wheel-build
dependency graphs used by native CI. `hcipy-py311.txt` pins the optional
HCIPy backend lane: the `.[test,hcipy]` extras plus the `build` frontend on
CPython 3.11. `hcipy-py314.txt` pins the HCIPy maintainer environment on
CPython 3.14 that generates the packaged cross-backend baseline; the
candidate-generation script verifies the running interpreter against the
profile named for its Python version before recording it in a baseline's
environment block. The package metadata deliberately keeps compatible lower
bounds so downstream applications can resolve their own environments.

Install the profile matching the interpreter:

```bash
python -m pip install -c constraints/py310.txt -e ".[test]"          # Python 3.10
python -m pip install -c constraints/py314.txt -e ".[test]"          # Python 3.14
python -m pip install -c constraints/hcipy-py311.txt -e ".[test,hcipy]"  # Python 3.11 + HCIPy
python -m pip install -c constraints/hcipy-py314.txt -e ".[test,hcipy]"  # Python 3.14 + HCIPy maintainer lane
```

To refresh a profile, resolve `.[test]` in the corresponding CPython version
and operating-system family, pin every transitive dependency, then run the full
test suite and wheel smoke test before replacing the checked-in file. Review
dependency release notes and the resulting diff; do not mechanically copy a
Python 3.14 resolution into the Python 3.10 profile because supported package
versions differ.
