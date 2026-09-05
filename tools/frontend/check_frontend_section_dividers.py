#!/usr/bin/env python3
"""CI guard: detect decorated section-divider comments in .ts/.tsx files.

house-lint's HSL001 flags decorated section dividers (``# --------``,
``# --- Helpers ---``) in Python via ``tokenize``, but it never scans
``frontend/src/`` at all — there's no TS-aware parser wired in. This is the
frontend-only counterpart: a scan for the same divider shape in the three
comment forms TS/TSX actually uses:

- ``// --------`` / ``// --- Helpers ---`` — line comments, inherently single-line.
- ``{/* -------- */}`` / ``{/* --- Helpers --- */}`` — JSX expression comments.
- ``/* -------- */`` / ``/* --- Helpers --- */`` — ordinary block comments, used
  outside JSX (plain ``.ts`` files, or ``.tsx`` code outside a JSX expression).

The JSX and block forms can also span multiple physical lines (the standard JSDoc-style
layout, ``/*`` then a ``* --- Helpers ---`` line then a closing ``*/`` line) — those are
matched as a whole comment span across the full file text, normalized to the single-line
form the same regexes already check, rather than line-by-line like the ``//`` scan. The same
normalization strips a JSDoc opener's extra leading ``*`` (``/** -------- */``), so that form
is recognized too, whether it's one line or several.

Decorated-form parity with HSL001 only — unlike ``tools/check_section_dividers.py``, this
checker has no *undecorated* one-line label rule (``// Helpers`` with no dashes). Extending
this checker to that shape needs a decision the Python structural/shape heuristic doesn't
answer for free: whether it's confidently distinguishable from an ordinary short comment given
how differently TS/TSX code is structured.

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
BLOCK_COMMENT_RULE = re.compile(r"^/\*\s*[-=#*~_]{4,}\s*\*/$")
BLOCK_COMMENT_WRAPPED = re.compile(r"^/\*\s*[-=#*~_]{3,}\s+\S(?:.*\S)?\s+[-=#*~_]{3,}\s*\*/$")

#: Whole-file spans for the JSX and block comment forms, found across line boundaries so a
#: multiline ``/*\n * --- Helpers ---\n */`` layout is caught, not just the single-line shape.
#: The block-comment span excludes anything immediately preceded by ``{`` (a negative
#: lookbehind) so a ``{/* ... */}`` JSX comment's inner ``/* ... */`` is never matched twice —
#: once as JSX, once as a plain block comment.
JSX_COMMENT_SPAN_RE = re.compile(r"\{/\*.*?\*/\}", re.DOTALL)
BLOCK_COMMENT_SPAN_RE = re.compile(r"(?<!\{)/\*.*?\*/", re.DOTALL)


def _normalize_comment_span(span: str, *, jsx: bool) -> str:
    """Collapse a (possibly multiline) comment span into the single-line form
    ``JSX_COMMENT_RULE``/``BLOCK_COMMENT_RULE`` and their wrapped variants expect: strip the
    delimiters, drop each continuation line's leading ``*`` bullet (the standard JSDoc-style
    layout), and join what's left with a single space.
    """
    inner = span[3:-3] if jsx else span[2:-2]
    parts = []
    for raw_line in inner.splitlines():
        stripped = raw_line.strip()
        if stripped.startswith("*"):
            stripped = stripped[1:].strip()
        if stripped:
            parts.append(stripped)
    body = " ".join(parts)
    return f"{{/* {body} */}}" if jsx else f"/* {body} */"


def check_file(path: Path) -> list[tuple[int, str]]:
    """Return sorted (1-based line number, message) decorated-divider violations in ``path``."""
    try:
        text = path.read_text(encoding="utf-8")
    except (UnicodeDecodeError, OSError):
        return []

    violations: list[tuple[int, str]] = []

    for lineno, line in enumerate(text.splitlines(), start=1):
        stripped = line.strip()
        if LINE_COMMENT_RULE.fullmatch(stripped) or LINE_COMMENT_WRAPPED.fullmatch(stripped):
            violations.append((lineno, f"section-divider comment - {stripped!r}"))

    for span_re, rule, wrapped, jsx in (
        (JSX_COMMENT_SPAN_RE, JSX_COMMENT_RULE, JSX_COMMENT_WRAPPED, True),
        (BLOCK_COMMENT_SPAN_RE, BLOCK_COMMENT_RULE, BLOCK_COMMENT_WRAPPED, False),
    ):
        for match in span_re.finditer(text):
            normalized = _normalize_comment_span(match.group(), jsx=jsx)
            if rule.fullmatch(normalized) or wrapped.fullmatch(normalized):
                lineno = text.count("\n", 0, match.start()) + 1
                violations.append((lineno, f"section-divider comment - {normalized!r}"))

    violations.sort()
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
