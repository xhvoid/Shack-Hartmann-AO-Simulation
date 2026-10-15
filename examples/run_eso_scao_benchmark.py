"""ESO-derived SCAO benchmark: supervised tier runner (command-line example).

Runs one tier of the ESO-derived 42 m SCAO benchmark through the canonical
``build_scao_system`` / ``run_closed_loop`` API with streamed long-exposure
science images.  The default ``ci`` tier (5 m software smoke, 10x10 SH,
11x11 DM, 32 frames) is desktop safe and takes a few seconds.  ``medium``,
``medium-gate``, ``full`` and ``reference`` refuse to run without
``--enable-large-run``, which a human should pass only after reviewing
``--dry-run`` output (configuration, estimated peak memory, threads, timeout,
output path).

The numerical work runs in a child process with native-library thread limits,
an aggregate-RSS budget, a wall-clock limit and a memory-pressure stop.
Outputs go to ``$AO_DEMO_OUTPUT_DIR/eso_scao_<tier>`` or, when that variable
is unset, ``./eso_scao_benchmark_output/eso_scao_<tier>``; nothing is written
into tracked figures or packaged resources.

Examples::

    python examples/run_eso_scao_benchmark.py
    python examples/run_eso_scao_benchmark.py --tier full --dry-run
"""

from __future__ import annotations

import os
import sys

# Native-library thread limits must exist before NumPy is first imported, in
# this supervising process as well as in the child it launches.  Existing
# lower limits are kept.
for _name in (
    "OMP_NUM_THREADS",
    "OPENBLAS_NUM_THREADS",
    "MKL_NUM_THREADS",
    "VECLIB_MAXIMUM_THREADS",
    "NUMEXPR_NUM_THREADS",
):
    _value = os.environ.get(_name, "")
    if not (_value.isdigit() and 0 < int(_value) <= 2):
        os.environ[_name] = "2"

from shwfs_ao.experiments.eso_scao_benchmark import main


if __name__ == "__main__":
    sys.exit(main())
