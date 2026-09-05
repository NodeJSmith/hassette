#!/usr/bin/env python3
"""CI guard: detect decorated section-divider comments in .ts/.tsx files.

house-lint's HSL001 flags decorated section dividers (``# --------``,
``# --- Helpers ---``) in Python via ``tokenize``, but it never scans
``frontend/src/`` at all — there's no TS-aware parser wired in. This is the
frontend-only counterpart: a line-based scan for the same divider shape in the
two comment forms TS/TSX actually uses:

- ``// --------`` / ``// --- Helpers ---`` — line comments.
- ``{/* -------- */}`` / ``{/* --- Helpers --- */}`` — JSX expression comments.

Usage:
    python tools/frontend/check_frontend_section_dividers.py
"""

import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
FRONTEND_SRC = REPO_ROOT / "frontend" / "src"

#: The label portion accepts a single non-whitespace character (``\S(?:.*\S)?``) so a
#: one-character label like ``// --- A ---`` is recognized as decorated.
LINE_COMMENT_RULE = re.compile(r"^//\s*[-=#*~_]{4,}$")
LINE_COMMENT_WRAPPED = re.compile(r"^//\s*[-=#*~_]{3,}\s+\S(?:.*\S)?\s+[-=#*~_]{3,}$")
JSX_COMMENT_RULE = re.compile(r"^\{/\*\s*[-=#*~_]{4,}\s*\*/\}$")
JSX_COMMENT_WRAPPED = re.compile(r"^\{/\*\s*[-=#*~_]{3,}\s+\S(?:.*\S)?\s+[-=#*~_]{3,}\s*\*/\}$")


def check_file(path: Path) -> list[tuple[int, str]]:
    """Return sorted (1-based line number, message) decorated-divider violations in ``path``."""
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except (UnicodeDecodeError, OSError):
        return []

    violations: list[tuple[int, str]] = []
    for lineno, line in enumerate(lines, start=1):
        stripped = line.strip()
        if (
            LINE_COMMENT_RULE.fullmatch(stripped)
            or LINE_COMMENT_WRAPPED.fullmatch(stripped)
            or JSX_COMMENT_RULE.fullmatch(stripped)
            or JSX_COMMENT_WRAPPED.fullmatch(stripped)
        ):
            violations.append((lineno, f"section-divider comment - {stripped!r}"))

    return violations


def find_frontend_files() -> list[Path]:
    """Return every .ts/.tsx file under frontend/src/, sorted, excluding generated .d.ts files."""
    return sorted(
        path for pattern in ("*.ts", "*.tsx") for path in FRONTEND_SRC.rglob(pattern) if not path.name.endswith(".d.ts")
    )


def main() -> int:
    violations: list[tuple[str, int, str]] = []
    for path in find_frontend_files():
        rel = str(path.relative_to(REPO_ROOT))
        for lineno, message in check_file(path):
            violations.append((rel, lineno, message))

    if violations:
        print(f"ERROR: {len(violations)} section-divider comment(s) found:")
        print()
        for rel, lineno, message in violations:
            print(f"  {rel}:{lineno} — {message}")
        print()
        print("A decorated section-divider comment is an AI-writing tell — delete it. If it")
        print("carries a label (// --- Helpers ---), keep the label as a plain comment (// Helpers).")
        return 1

    print("OK: no section-divider comments found.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
