"""Repository portability checks for files that can enter a commit."""

from pathlib import Path
import re
import subprocess


ROOT = Path(__file__).resolve().parents[1]
WINDOWS_INVALID_CHARS = frozenset('<>:"\\|?*')
WINDOWS_RESERVED_STEMS = {
    "CON",
    "PRN",
    "AUX",
    "NUL",
    *(f"COM{number}" for number in range(1, 10)),
    *(f"LPT{number}" for number in range(1, 10)),
}


def _candidate_repository_paths() -> list[str]:
    completed = subprocess.run(
        ["git", "ls-files", "-z", "--cached", "--others", "--exclude-standard"],
        cwd=ROOT,
        check=True,
        capture_output=True,
    )
    paths = completed.stdout.decode("utf-8").split("\0")
    # Ignore index entries deleted by a pending rename; include their new
    # untracked destination so this test also works before changes are staged.
    return sorted(path for path in paths if path and (ROOT / path).exists())


def _windows_path_problem(path: str) -> str | None:
    for component in Path(path).parts:
        if any(character in WINDOWS_INVALID_CHARS for character in component):
            return f"contains a Windows-forbidden character in {component!r}"
        if any(ord(character) < 32 for character in component):
            return f"contains a control character in {component!r}"
        if component.endswith((" ", ".")):
            return f"has a trailing space or period in {component!r}"
        stem = re.split(r"\.", component, maxsplit=1)[0].upper()
        if stem in WINDOWS_RESERVED_STEMS:
            return f"uses reserved Windows device name {component!r}"
    return None


def test_repository_filenames_are_windows_portable():
    problems = {
        path: problem
        for path in _candidate_repository_paths()
        if (problem := _windows_path_problem(path)) is not None
    }

    assert problems == {}
    assert (ROOT / "figures" / "PWFS_Sx_Sy.png").is_file()
