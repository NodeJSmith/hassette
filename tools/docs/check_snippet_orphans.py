#!/usr/bin/env python3
"""CI guard: detect unreferenced snippet files under docs/pages/*/snippets/.

Finds all files in snippet directories and checks each against --8<-- include
references in .md files. Reports files not referenced by any page. Exits
non-zero if orphans are found.

Handles both full-file includes and fragment includes (section markers), in
pymdownx's single-line form and its multi-line block form:
  --8<-- "pages/core-concepts/bus/snippets/file.py"
  --8<-- "pages/core-concepts/bus/snippets/file.py:marker"

  --8<--
  pages/core-concepts/bus/snippets/file.py:imports
  pages/core-concepts/bus/snippets/file.py:usage
  --8<--

Usage:
    python tools/docs/check_snippet_orphans.py
"""

import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
DOCS_DIR = REPO_ROOT / "docs"

INCLUDE_RE = re.compile(r'--8<--\s+"([^"]+)"')
# A bare `--8<--` line opens a block of one include per line, closed by the next bare `--8<--` line.
BLOCK_RE = re.compile(r"^[ \t]*--8<--[ \t]*\n(.*?)^[ \t]*--8<--[ \t]*$", re.MULTILINE | re.DOTALL)


def included_files(markdown: str) -> set[str]:
    """Return the snippet paths a page includes, with any ``:marker`` section suffix dropped.

    Lines starting with ``;`` inside a block are pymdownx's way of commenting an include out.
    """
    includes = [match.group(1) for match in INCLUDE_RE.finditer(markdown)]
    for block in BLOCK_RE.finditer(markdown):
        lines = (line.strip() for line in block.group(1).splitlines())
        includes.extend(line for line in lines if line and not line.startswith(";"))
    return {include.split(":")[0] for include in includes}


def find_snippet_files() -> set[Path]:
    results: set[Path] = set()
    for path in DOCS_DIR.rglob("snippets/**/*"):
        if path.is_file():
            results.add(path)
    return results


def find_referenced_paths() -> set[Path]:
    referenced: set[Path] = set()
    for md_file in DOCS_DIR.rglob("*.md"):
        for file_part in included_files(md_file.read_text(encoding="utf-8")):
            referenced.add((DOCS_DIR / file_part).resolve())
    return referenced


def main() -> int:
    snippet_files = find_snippet_files()
    referenced = find_referenced_paths()

    orphans = sorted(f.relative_to(DOCS_DIR) for f in snippet_files if f.resolve() not in referenced)

    if not orphans:
        print(f"OK: all {len(snippet_files)} snippet files are referenced")
        return 0

    print(f"FAIL: {len(orphans)} orphaned snippet file(s) (not referenced by any --8<-- include):\n")
    for orphan in orphans:
        print(f"  {orphan}")

    print(f"\n{len(snippet_files) - len(orphans)} referenced, {len(orphans)} orphaned")
    return 1


if __name__ == "__main__":
    sys.exit(main())
