#!/usr/bin/env python3
"""Execute the README command blocks owned by a clean-wheel smoke lane.

Only direct Python commands are accepted.  Shell pipelines, redirections,
continuations, and compound commands are deliberately unsupported so the
Markdown remains portable and CI never has to evaluate README text through a
shell.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import importlib.metadata
import importlib.util
import json
import os
from pathlib import Path
import re
import shlex
import subprocess
import sys


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
README_PATH = REPOSITORY_ROOT / "README.md"
_OWNER_RE = re.compile(r"^<!-- readme-smoke: (native|hcipy) -->$")
_BASH_FENCE_RE = re.compile(r"^```[ \t]*bash[ \t]*$")
_CLOSE_FENCE_RE = re.compile(r"^```[ \t]*$")
_INLINE_SHELL_COMMAND_RE = re.compile(
    r"`(?:\$\s+)?(?:[A-Za-z_][A-Za-z0-9_]*=[^`\s]+\s+)*"
    r"(?:python(?:3(?:\.\d+)*)?|pip|pytest|git)(?:\s+[^`]*)?`"
)
_ENVIRONMENT_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=.*$", re.DOTALL)
_FORBIDDEN_ENVIRONMENT = frozenset({"PYTHONHOME", "PYTHONPATH"})
_SHELL_PUNCTUATION = frozenset({";", "&", "|", "<", ">"})


class ReadmeSmokeError(ValueError):
    """Raised when an executable README block is missing or unsafe."""


@dataclass(frozen=True)
class ReadmeCommand:
    """One direct command extracted from an owned README block."""

    owner: str
    line_number: int
    source: str


def parse_readme_commands(
    readme_path: Path = README_PATH,
) -> dict[str, list[ReadmeCommand]]:
    """Return validated commands grouped by their native or HCIPy owner."""

    try:
        lines = readme_path.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        raise ReadmeSmokeError(f"Cannot read {readme_path}: {exc}") from exc

    for line_number, line in enumerate(lines, start=1):
        if _INLINE_SHELL_COMMAND_RE.search(line):
            raise ReadmeSmokeError(
                f"README line {line_number}: shell commands must appear in an "
                "owned fenced bash block, not inline code."
            )

    commands: dict[str, list[ReadmeCommand]] = {"native": [], "hcipy": []}
    index = 0
    while index < len(lines):
        line = lines[index]
        owner_match = _OWNER_RE.fullmatch(line)
        if owner_match:
            if index + 1 >= len(lines) or not _BASH_FENCE_RE.fullmatch(
                lines[index + 1]
            ):
                raise ReadmeSmokeError(
                    f"README line {index + 1}: a readme-smoke owner must be "
                    "followed immediately by a bash fence."
                )
            index += 1
            continue

        if not _BASH_FENCE_RE.fullmatch(line):
            index += 1
            continue

        if index == 0 or (owner_match := _OWNER_RE.fullmatch(lines[index - 1])) is None:
            raise ReadmeSmokeError(
                f"README line {index + 1}: every bash fence needs an immediate "
                "'<!-- readme-smoke: native -->' or "
                "'<!-- readme-smoke: hcipy -->' owner."
            )
        owner = owner_match.group(1)
        block_start = index + 1
        index += 1
        block_count = 0
        while index < len(lines) and not _CLOSE_FENCE_RE.fullmatch(lines[index]):
            source = lines[index].strip()
            if source:
                if source.endswith("\\"):
                    raise ReadmeSmokeError(
                        f"README line {index + 1}: multiline shell commands are "
                        "not supported."
                    )
                _command_argv(source, line_number=index + 1)
                commands[owner].append(
                    ReadmeCommand(
                        owner=owner,
                        line_number=index + 1,
                        source=source,
                    )
                )
                block_count += 1
            index += 1
        if index >= len(lines):
            raise ReadmeSmokeError(
                f"README line {block_start}: unclosed bash command block."
            )
        if block_count == 0:
            raise ReadmeSmokeError(
                f"README line {block_start}: executable bash blocks cannot be empty."
            )
        index += 1

    if not any(commands.values()):
        raise ReadmeSmokeError("README contains no owned executable commands.")
    return commands


def _command_argv(source: str, *, line_number: int) -> tuple[dict[str, str], list[str]]:
    """Parse one safe, direct Python command without invoking a shell."""

    if "`" in source or "$(" in source:
        raise ReadmeSmokeError(
            f"README line {line_number}: command substitution is not supported."
        )
    lexer = shlex.shlex(source, posix=True, punctuation_chars=";&|<>")
    lexer.whitespace_split = True
    lexer.commenters = ""
    try:
        tokens = list(lexer)
    except ValueError as exc:
        raise ReadmeSmokeError(
            f"README line {line_number}: cannot parse command: {exc}"
        ) from exc
    if not tokens:
        raise ReadmeSmokeError(f"README line {line_number}: empty command.")
    if any(token and set(token) <= _SHELL_PUNCTUATION for token in tokens):
        raise ReadmeSmokeError(
            f"README line {line_number}: shell operators and redirections are "
            "not supported."
        )

    environment: dict[str, str] = {}
    while tokens and _ENVIRONMENT_RE.fullmatch(tokens[0]):
        name, value = tokens.pop(0).split("=", 1)
        if name in _FORBIDDEN_ENVIRONMENT:
            raise ReadmeSmokeError(
                f"README line {line_number}: {name} is controlled by the smoke "
                "runner and cannot be overridden."
            )
        environment[name] = value
    if not tokens or tokens[0] not in {"python", "python3"}:
        raise ReadmeSmokeError(
            f"README line {line_number}: executable commands must invoke "
            "'python' or 'python3' directly."
        )
    tokens[0] = sys.executable
    return environment, tokens


def _assert_clean_wheel_bundle(root: Path) -> None:
    """Prove that imports cannot fall back to a source checkout."""

    forbidden = [path for path in (root / "src", root / ".git") if path.exists()]
    if forbidden:
        names = ", ".join(path.name for path in forbidden)
        raise ReadmeSmokeError(
            f"Wheel-smoke root {root} contains forbidden checkout paths: {names}."
        )
    spec = importlib.util.find_spec("shwfs_ao")
    if spec is None or spec.origin is None:
        raise ReadmeSmokeError("The installed shwfs_ao wheel cannot be resolved.")
    origin = Path(spec.origin).resolve()
    if origin.is_relative_to(root.resolve()):
        raise ReadmeSmokeError(
            f"shwfs_ao resolves inside the smoke bundle ({origin}), not from the "
            "installed wheel."
        )
    try:
        distribution = importlib.metadata.distribution("shack-hartmann-ao-simulation")
    except importlib.metadata.PackageNotFoundError as exc:
        raise ReadmeSmokeError(
            "The shack-hartmann-ao-simulation distribution is not installed."
        ) from exc
    direct_url = distribution.read_text("direct_url.json")
    if direct_url is not None:
        try:
            direct_url_record = json.loads(direct_url)
        except json.JSONDecodeError as exc:
            raise ReadmeSmokeError(
                "The installed distribution has an invalid direct_url.json."
            ) from exc
        if direct_url_record.get("dir_info", {}).get("editable") is True:
            raise ReadmeSmokeError(
                "The installed shwfs_ao distribution is editable; the "
                "documentation smoke requires a built, non-editable wheel."
            )


def run_commands(commands: list[ReadmeCommand], *, root: Path) -> None:
    """Execute validated commands in order against the current interpreter."""

    base_environment = os.environ.copy()
    base_environment.update(
        {
            "MPLBACKEND": "Agg",
            "PYTHONDONTWRITEBYTECODE": "1",
            "PYTHONNOUSERSITE": "1",
            "PYTHONPATH": "",
        }
    )
    for command in commands:
        command_environment, argv = _command_argv(
            command.source,
            line_number=command.line_number,
        )
        environment = base_environment | command_environment
        print(
            f"[readme-smoke:{command.owner}:{command.line_number}] {command.source}",
            flush=True,
        )
        subprocess.run(argv, cwd=root, env=environment, check=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--section",
        choices=("native", "hcipy", "all"),
        default="all",
        help="owned README section to execute (default: all)",
    )
    parser.add_argument(
        "--require-wheel-bundle",
        action="store_true",
        help="reject a source checkout and require shwfs_ao to resolve externally",
    )
    arguments = parser.parse_args(argv)

    try:
        grouped = parse_readme_commands()
        selected = (
            grouped["native"] + grouped["hcipy"]
            if arguments.section == "all"
            else grouped[arguments.section]
        )
        if not selected:
            raise ReadmeSmokeError(
                f"README has no commands owned by {arguments.section!r}."
            )
        if arguments.require_wheel_bundle:
            _assert_clean_wheel_bundle(REPOSITORY_ROOT)
        run_commands(selected, root=REPOSITORY_ROOT)
    except ReadmeSmokeError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    except subprocess.CalledProcessError as exc:
        return exc.returncode or 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
