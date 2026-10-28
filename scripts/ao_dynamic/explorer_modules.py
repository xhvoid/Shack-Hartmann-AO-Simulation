"""Load the frozen explorer modules this mode reuses, without editing ``sys.path``.

The dynamic mode reuses ``scripts/ao_explorer`` (protocol, identities,
admission, observer, binary scene, producer helpers) unchanged.  Those modules
import each other by bare name, as scripts run from their own directory do.
Each is loaded here from its file, in dependency order, and registered in
``sys.modules`` under that bare name, so their own imports resolve to these
same module objects.  A module already imported (for example by the test
suite, which puts the explorer directory on the path) is left as it is.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
import sys


EXPLORER = Path(__file__).resolve().parent.parent / "ao_explorer"
# Dependency order: each module imports only the ones before it at load time.
MODULES = ("protocol", "identity", "binary_scene", "admission", "observer", "producer")


def load() -> None:
    for name in MODULES:
        if name in sys.modules:
            continue
        spec = importlib.util.spec_from_file_location(name, EXPLORER / f"{name}.py")
        if spec is None or spec.loader is None:
            raise ImportError(f"cannot load the explorer module {name} from {EXPLORER}")
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        try:
            spec.loader.exec_module(module)
        except BaseException:
            del sys.modules[name]
            raise
