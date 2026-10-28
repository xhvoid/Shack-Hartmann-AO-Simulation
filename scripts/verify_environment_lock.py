#!/usr/bin/env python3
"""Verify the running environment against a resolved constraint profile.

A constraint profile under ``constraints/`` is a complete environment lock:
after a lane installs its dependencies with ``-c`` against the profile,
every installed distribution must appear in the profile at exactly the
installed version.  Anything else means the profile stopped being a lock —
an unpinned transitive dependency floated in, or an install drifted from a
pin — and identical profile hashes would no longer describe identical
environments.

Usage::

    python scripts/verify_environment_lock.py --constraints constraints/py314.txt
    python scripts/verify_environment_lock.py --emit > freeze.txt

``--constraints`` verifies installed ⊆ pinned (at exact versions) and fails
listing every violation.  ``--emit`` prints the complete normalized freeze of
the running environment — the relock procedure runs it on the target
platform to regenerate a profile.  The verifier and the emitter both ignore
``pip`` (the resolver is not part of the resolved environment) and the
project under test itself.
"""

from __future__ import annotations

import argparse
from importlib import metadata
from pathlib import Path
import sys

IGNORED_DISTRIBUTIONS = frozenset({"pip", "shack-hartmann-ao-simulation"})


def _normalize(name: str) -> str:
    return name.strip().lower().replace("_", "-")


def parse_constraint_pins(text: str) -> dict[str, str]:
    """``name==version`` pins from a constraint file, comments stripped."""

    pins: dict[str, str] = {}
    for raw_line in text.splitlines():
        line = raw_line.split("#", 1)[0].split(";", 1)[0].strip()
        if line and "==" in line and not line.startswith("-"):
            name, _, version = line.partition("==")
            pins[_normalize(name)] = version.strip()
    return pins


def installed_distributions() -> dict[str, str]:
    """Normalized name → version for every non-ignored installed dist."""

    installed: dict[str, str] = {}
    for distribution in metadata.distributions():
        name = distribution.metadata["Name"]
        if name is None:
            continue
        normalized = _normalize(name)
        if normalized in IGNORED_DISTRIBUTIONS:
            continue
        installed[normalized] = distribution.version
    return installed


def verify(pins: dict[str, str], installed: dict[str, str]) -> list[str]:
    """Every violation of installed ⊆ pinned-at-exact-version."""

    violations: list[str] = []
    for name in sorted(installed):
        if name not in pins:
            violations.append(
                f"{name}=={installed[name]} is installed but the profile "
                "does not pin it"
            )
        elif pins[name] != installed[name]:
            violations.append(
                f"{name} is installed at {installed[name]} but the profile "
                f"pins {pins[name]}"
            )
    return violations


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    operation = parser.add_mutually_exclusive_group(required=True)
    operation.add_argument(
        "--constraints",
        type=Path,
        help="Constraint profile to verify the running environment against.",
    )
    operation.add_argument(
        "--emit",
        action="store_true",
        help="Print the complete normalized freeze of the running environment.",
    )
    arguments = parser.parse_args(argv)

    installed = installed_distributions()
    if arguments.emit:
        for name in sorted(installed):
            print(f"{name}=={installed[name]}")
        return 0

    profile: Path = arguments.constraints
    if not profile.is_file():
        print(f"error: constraint profile not found: {profile}", file=sys.stderr)
        return 2
    pins = parse_constraint_pins(profile.read_text(encoding="utf-8"))
    violations = verify(pins, installed)
    if violations:
        print(
            f"{profile} is not a complete lock of this environment:",
            file=sys.stderr,
        )
        for violation in violations:
            print(f"  {violation}", file=sys.stderr)
        return 1
    print(
        f"{profile.name}: {len(installed)} installed distributions all "
        f"pinned exactly ({len(pins)} pins cover this and other lanes)."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
