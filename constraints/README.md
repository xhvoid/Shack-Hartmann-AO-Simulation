# Reproducible Test Environments

`py310.txt` and `py314.txt` pin the complete runtime, pytest, and wheel-build
dependency graphs used by CI. The package metadata deliberately keeps
compatible lower bounds so downstream applications can resolve their own
environments.

Install the profile matching the interpreter:

```bash
python -m pip install -c constraints/py310.txt -e ".[test]"  # Python 3.10
python -m pip install -c constraints/py314.txt -e ".[test]"  # Python 3.14
```

To refresh a profile, resolve `.[test]` in the corresponding CPython version
and operating-system family, pin every transitive dependency, then run the full
test suite and wheel smoke test before replacing the checked-in file. Review
dependency release notes and the resulting diff; do not mechanically copy a
Python 3.14 resolution into the Python 3.10 profile because supported package
versions differ.
