#!/usr/bin/env python3
"""CI guard: detect undecorated section-divider comments in Python files.

house-lint's HSL001 flags *decorated* section dividers (``# --------``,
``# --- Helpers ---``) but not the undecorated form: an isolated one-line label
comment — blank line above, blank line below — that visually separates code the
same way a decorated divider does (``# Helpers``, ``# Root App``). This checker
covers exactly that gap; it never re-flags a decorated divider, which stays
HSL001's job.

Two independent rules, either one flags a line, both chosen for a 0% false-positive
rate on this codebase:

- **Structural** (high precision): the comment sits alone between blank lines, and
  the next non-blank line after it opens a ``def``/``async def``/``class``, or a
  decorator (``@...``) — the comment is literally introducing that definition.
- **Shape** (medium precision): the comment sits alone between blank lines and its
  body is 1-4 words — short enough to be a label, not a sentence explaining
  something.

Pragma-shaped comments (``# type: ...``, ``# pyright: ...``, ``# noqa``,
``# fmt: ...``, ``# ruff: ...``, ``# TODO``, ``# FIXME``, ``# NOTE``, ``# HACK``,
``# XXX``) are never flagged — they carry tooling directives or follow-up markers,
not section labels, even though they're often short and isolated.

Usage:
    ./tools/check_section_dividers.py            # scan the same dirs as house-lint
    ./tools/check_section_dividers.py <file> ...  # scan specific files (pre-commit)
"""

import re
import sys
from pathlib import Path

from lint_helpers import REPO_ROOT, extract_comments, iter_python_files, run_check

#: Already HSL001's job — never re-flag a comment that's a decorated divider. The label portion
#: accepts a single non-whitespace character (``\S(?:.*\S)?``) so a one-character label like
#: ``# --- A ---`` is recognized as decorated instead of falling through to the shape rule below.
DECORATED_RULE = re.compile(r"^[-=#*~_]{4,}$")
DECORATED_WRAPPED = re.compile(r"^[-=#*~_]{3,}\s+\S(?:.*\S)?\s+[-=#*~_]{3,}$")

#: Tooling directives and follow-up markers, never section labels. ``pragma:`` covers directives
#: like ``# pragma: no cover``; ``dup-ignore*`` is ``check_duplicate_code.py``'s suppression
#: syntax; ``--8<--`` is the mkdocs snippet-extraction marker used throughout
#: ``docs/pages/*/snippets/``. All are isolated, short lines that would otherwise match the shape
#: rule below, but none is prose a reader wrote to label a section.
PRAGMA_RE = re.compile(
    r"^(type:|pyright:|noqa\b|fmt:|ruff:|pragma:|TODO\b|FIXME\b|NOTE\b|HACK\b|XXX\b|dup-ignore|--8<--)",
    re.IGNORECASE,
)

#: Shebang and PEP 263 encoding-cookie lines are tokenized as comments by ``tokenize`` but are
#: source directives, never section labels — exempt them even if isolated by blank lines above
#: and below (e.g. a shebang followed by a blank line before the module docstring). Per PEP 263,
#: both are only meaningful on line 1 or 2, so the check is line-scoped to avoid exempting an
#: unrelated isolated comment that merely contains the substring "coding" further down the file.
SHEBANG_RE = re.compile(r"^#!")
CODING_COOKIE_RE = re.compile(r"^#.*coding[:=]\s*[-\w.]+")

#: What a comment "introduces" for the structural rule: a definition or a decorator above one.
DEFINITION_RE = re.compile(r"^(async\s+def\s|def\s|class\s|@)")

#: A body ending in sentence punctuation is prose explaining something, not a label — e.g. "These
#: represent the structure of the data as it comes from Home Assistant's websocket API, prior to
#: any processing." reads as real documentation despite sitting directly above a class.
SENTENCE_END_RE = re.compile(r"[.!?]$")

#: Above this word count, a comment reads as an explanation rather than a short label, even
#: without terminal punctuation (e.g. "TLS-verification warning: config-sourced only, not the
#: explicit flag" is 9 words and still a label; a 15-word body is a sentence in practice).
MAX_STRUCTURAL_WORDS = 10

FOOTER = (
    "An isolated one-line label comment (blank line above and below) that only restates the\n"
    "def/class name below it, or reads as a short section label, is the same AI-writing tell as\n"
    "a decorated divider (# --- Helpers ---) — delete it rather than converting it to plain text."
)


def check_file(path: Path) -> list[tuple[int, str]]:
    """Return sorted (1-based line number, message) undecorated-divider violations in ``path``."""
    try:
        source = path.read_text(encoding="utf-8")
    except (UnicodeDecodeError, OSError):
        return []

    lines = source.splitlines()
    comments = extract_comments(source)
    violations: list[tuple[int, str]] = []

    for lineno, comment in comments.items():
        line = lines[lineno - 1]
        if line.strip() != comment.strip():
            continue  # trailing comment on a code line, not a standalone one

        above_blank = lineno == 1 or lines[lineno - 2].strip() == ""
        below_blank = lineno == len(lines) or lines[lineno].strip() == ""
        if not (above_blank and below_blank):
            continue

        if lineno <= 2 and (SHEBANG_RE.match(comment) or CODING_COOKIE_RE.match(comment)):
            continue

        body = comment.lstrip("#").strip()
        if not body or DECORATED_RULE.fullmatch(body) or DECORATED_WRAPPED.fullmatch(body):
            continue
        if PRAGMA_RE.match(body):
            continue

        # A divider separates the comment from something that follows it — nothing left in
        # the file to separate from means this is a trailing remark, not a divider candidate.
        next_line = _next_non_blank(lines, lineno)
        if next_line is None:
            continue

        word_count = len(body.split())
        is_prose = SENTENCE_END_RE.search(body) is not None

        introduces_definition = (
            not is_prose and word_count <= MAX_STRUCTURAL_WORDS and DEFINITION_RE.match(next_line.strip()) is not None
        )
        is_short_label = not is_prose and 1 <= word_count <= 4

        if introduces_definition:
            violations.append((lineno, f"undecorated section divider (introduces definition) - {comment.strip()!r}"))
        elif is_short_label:
            violations.append((lineno, f"undecorated section divider (short label) - {comment.strip()!r}"))

    return violations


def _next_non_blank(lines: list[str], lineno: int) -> str | None:
    """Return the first non-blank line after the blank line following 1-based ``lineno``, or None."""
    for line in lines[lineno:]:
        if line.strip():
            return line
    return None


def main() -> int:
    return run_check(
        iter_python_files(sys.argv[1:]),
        REPO_ROOT,
        check_file,
        summary="undecorated section divider comment(s) found",
        ok="no undecorated section divider comments found.",
        footer=FOOTER,
    )


if __name__ == "__main__":
    sys.exit(main())
