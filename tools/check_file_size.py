#!/usr/bin/env python3
"""CI guard: flag .py files that have grown past the house size convention.

CLAUDE.md's coding-style guidance caps files at 800 lines (200-400 typical). This
guard exits non-zero when any file exceeds the threshold. It runs in CI as a
``continue-on-error`` step so violations surface as a visible yellow warning on
the PR without blocking the merge.

The ``# file-size-exempt:`` annotation opts a file out entirely. It requires a
non-empty reason after the colon so an empty annotation does not exempt. One
annotation anywhere in the file exempts the whole file.

Usage:
    python tools/check_file_size.py [FILE ...]

With no arguments, scans every file under src/, tests/, scripts/, tools/, codegen/,
docs/, and examples/. Given file paths, scans only those.
"""

import re
import sys
from pathlib import Path

from lint_helpers import DEFAULT_SCAN_DIRS, REPO_ROOT, iter_python_files

THRESHOLD = 800

ANNOTATION_RE = re.compile(r"#\s*file-size-exempt:\s*\S")


def check_file(path: Path) -> list[tuple[int, str]]:
    """Return [(1, message)] if the file exceeds THRESHOLD lines and isn't exempt, else []."""
    source = path.read_text()
    lines = source.splitlines()
    line_count = len(lines)

    if line_count <= THRESHOLD:
        return []

    if any(ANNOTATION_RE.search(line) for line in lines):
        return []

    return [(1, f"{line_count} lines (threshold: {THRESHOLD})")]


def iter_paths() -> list[Path]:
    """Return every .py file under the scanned directories, sorted for stable output."""
    return iter_python_files([])


def main() -> int:
    paths = iter_python_files(sys.argv[1:])
    violations: list[tuple[Path, int, str]] = []
    for path in paths:
        rel = path.relative_to(REPO_ROOT)
        for lineno, message in check_file(path):
            violations.append((rel, lineno, message))

    if violations:
        print(f"WARNING: {len(violations)} file(s) exceed {THRESHOLD} lines:")
        print()
        for rel, _lineno, message in violations:
            print(f"  {rel} — {message}")
        print()
        print("Consider decomposing. Exempt with '# file-size-exempt: <reason>'.")
    else:
        print(f"OK: no un-exempt files exceed {THRESHOLD} lines under {', '.join(DEFAULT_SCAN_DIRS)}/.")

    return 1 if violations else 0


if __name__ == "__main__":
    sys.exit(main())
