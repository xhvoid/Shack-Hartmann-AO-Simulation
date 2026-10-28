"""Content-addressed code directory of the explorer site.

The page's scripts and style live in ``web/ao-explorer/code-<build>/``, where
``<build>`` is the first 16 hex digits of the SHA-256 of a canonical listing
of ``index.html`` (its build references normalized) and every file of that
directory.  ``index.html`` names the directory, and the modules import each
other relative to it, so a page always runs the code of its own build: a
changed file is a new URL, never a cached older one (external review ER-F05).  The
dataset entry ``data/current.json`` records the build it was published with,
and the code refuses an entry of another build -- a cached older page that
meets a newer entry -- instead of mixing versions.

Usage::

    python scripts/ao_explorer/site_build.py --web-dir web/ao-explorer           # check
    python scripts/ao_explorer/site_build.py --web-dir web/ao-explorer --write   # rename and restamp

``--write`` renames the single code directory to its build, rewrites the
references in ``index.html`` and records the build in ``data/current.json``.
Exit status 0 means the site is consistent.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import sys
from typing import Any, Dict, List, Optional


CODE_FILES = ("app.js", "charts.js", "galaxy.js", "integrity.js", "playback.js", "ngs-replay.js", "replay42.js", "c1-noise.js",
              "dm-stroke.js", "aperture.js", "results.js", "styles.css")
BUILD_DIGITS = 16
_DIR = re.compile(rf"^code-([0-9a-f]{{{BUILD_DIGITS}}})$")
_REF = re.compile(rf"code-([0-9a-f]{{{BUILD_DIGITS}}})/")
PLACEHOLDER = "code-{build}/"


class SiteBuildError(RuntimeError):
    pass


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def code_dirs(web_dir: Path) -> List[Path]:
    return sorted(path for path in Path(web_dir).iterdir() if path.is_dir() and path.name.startswith("code-"))


def normalized_index(text: str) -> str:
    return _REF.sub(PLACEHOLDER, text)


def listing(web_dir: Path, code_dir: Path) -> Dict[str, str]:
    present = sorted(path.name for path in code_dir.iterdir())
    if present != sorted(CODE_FILES):
        raise SiteBuildError(f"{code_dir.name} holds {present}, expected exactly {sorted(CODE_FILES)}")
    index = (Path(web_dir) / "index.html").read_text(encoding="utf-8")
    files = {"index.html": _sha(normalized_index(index).encode("utf-8"))}
    files.update({name: _sha((code_dir / name).read_bytes()) for name in CODE_FILES})
    return files


def build_id(files: Dict[str, str]) -> str:
    canonical = json.dumps(files, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return _sha(canonical)[:BUILD_DIGITS]


def check(web_dir: Path, *, entry: bool = True) -> Dict[str, Any]:
    """The site's build and every inconsistency found (an empty list means consistent)."""

    web_dir = Path(web_dir)
    problems: List[str] = []
    dirs = code_dirs(web_dir)
    if len(dirs) != 1:
        return {"build": None, "files": {}, "problems": [f"expected exactly one code directory, found {[path.name for path in dirs]}"]}
    code_dir = dirs[0]
    try:
        files = listing(web_dir, code_dir)
    except SiteBuildError as exc:
        return {"build": None, "files": {}, "problems": [str(exc)]}
    build = build_id(files)
    if code_dir.name != f"code-{build}":
        problems.append(f"{code_dir.name} does not carry its content build code-{build}")
    index = (web_dir / "index.html").read_text(encoding="utf-8")
    references = set(_REF.findall(index))
    if references != {code_dir.name[len("code-"):]}:
        problems.append(f"index.html references code builds {sorted(references)}, not {code_dir.name}")
    for needed in (f'href="{code_dir.name}/styles.css"', f'src="{code_dir.name}/app.js"'):
        if needed not in index:
            problems.append(f"index.html lacks {needed}")
    if entry:
        entry_path = web_dir / "data" / "current.json"
        recorded = json.loads(entry_path.read_text(encoding="utf-8")).get("code_build") if entry_path.is_file() else None
        if recorded != build:
            problems.append(f"data/current.json records code build {recorded}, not {build}")
    return {"build": build, "code_dir": code_dir.name, "files": files, "problems": problems}


def write(web_dir: Path) -> Dict[str, Any]:
    web_dir = Path(web_dir)
    dirs = code_dirs(web_dir)
    if len(dirs) != 1 or not _DIR.match(dirs[0].name):
        raise SiteBuildError(f"expected exactly one code-<{BUILD_DIGITS} hex> directory, found {[path.name for path in dirs]}")
    build = build_id(listing(web_dir, dirs[0]))
    target = web_dir / f"code-{build}"
    if dirs[0] != target:
        dirs[0].rename(target)
    index_path = web_dir / "index.html"
    index = index_path.read_text(encoding="utf-8")
    index_path.write_text(_REF.sub(f"code-{build}/", index), encoding="utf-8")
    entry_path = web_dir / "data" / "current.json"
    if entry_path.is_file():
        entry_value = json.loads(entry_path.read_text(encoding="utf-8"))
        entry_value["code_build"] = build
        entry_path.write_text(json.dumps(entry_value, indent=1) + "\n", encoding="utf-8")
    report = check(web_dir, entry=entry_path.is_file())
    if report["problems"]:
        raise SiteBuildError("; ".join(report["problems"]))
    return report


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--web-dir", type=Path, required=True)
    parser.add_argument("--write", action="store_true")
    arguments = parser.parse_args(argv)
    try:
        report = write(arguments.web_dir) if arguments.write else check(arguments.web_dir)
    except SiteBuildError as exc:
        print(json.dumps({"consistent": False, "error": str(exc)}))
        return 2
    print(json.dumps({"build": report["build"], "code_dir": report.get("code_dir"), "consistent": not report["problems"], "problems": report["problems"]}, indent=1))
    return 0 if not report["problems"] else 1


if __name__ == "__main__":
    sys.exit(main())
