#!/usr/bin/env python3
"""CI guard: detect unreferenced snippet files under docs/pages/*/snippets/.

Finds all files in snippet directories and checks each against --8<-- include
references in .md files. Reports files not referenced by any page. Exits
non-zero if orphans are found.

Handles both full-file includes and fragment includes (section markers):
  --8<-- "pages/core-concepts/bus/snippets/file.py"
  --8<-- "pages/core-concepts/bus/snippets/file.py:marker"

Usage:
    python tools/check_snippet_orphans.py
"""

import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DOCS_DIR = REPO_ROOT / "docs"

INCLUDE_RE = re.compile(r'--8<--\s+"([^"]+)"')


def find_snippet_files() -> set[Path]:
    results: set[Path] = set()
    for path in DOCS_DIR.rglob("snippets/**/*"):
        if path.is_file():
            results.add(path)
    return results


def find_referenced_paths() -> set[Path]:
    referenced: set[Path] = set()
    for md_file in DOCS_DIR.rglob("*.md"):
        for match in INCLUDE_RE.finditer(md_file.read_text(encoding="utf-8")):
            raw = match.group(1)
            file_part = raw.split(":")[0]
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
