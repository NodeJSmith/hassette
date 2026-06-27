#!/usr/bin/env python3
"""CI guard: detect leaked spec-artifact tokens in comments, docstrings, and filenames.

Design and work-package documents reference acceptance criteria, requirements,
tasks, and work packages by short codes — an ``AC``/``FR``/``NFR``/``WP`` prefix
followed by a number, or ``T`` followed by a task number. Those codes are
scaffolding for planning. They mean nothing to a reader of the shipped source and
should never survive into scanned source files.

Detection is text-based but scoped to human-readable text only:

    * Comments — extracted with the ``tokenize`` module, so the exact line of
      each ``# ...`` comment is known.
    * Docstrings — located via the AST (a string literal that is the first
      statement of a module, class, or function), then scanned over the raw
      source lines they span, so reported line numbers are exact.
    * Filenames — the name of every scanned file.

Arbitrary string literals are deliberately NOT scanned. A data string like
``value + "T00:00:00"`` is not human prose, and scanning it would flag the ISO
timestamp. The token pattern adds a second layer of safety: ``T\\d{2,}`` followed
by ``:`` and then a digit (a clock time like ``HH:MM``) never matches.

Tokens are leaked planning artifacts, not legitimate code references, so there is
no escape hatch — a match is always removed, never annotated. If the pattern
itself produces a false positive, tighten the pattern rather than adding an
exemption.

Usage:
    python tools/check_spec_tokens.py [FILE ...]

With no arguments, scans every file under src/, tests/, scripts/, tools/, codegen/,
docs/, and examples/. Given file paths (as pre-commit passes the staged files), scans
only those — out-of-scope or non-Python paths are ignored.
"""

import ast
import io
import re
import sys
import tokenize
from pathlib import Path

from lint_helpers import docstring_spans, resolve_paths

REPO_ROOT = Path(__file__).resolve().parent.parent

# Directories scanned, relative to the repo root.
SCAN_DIRS: list[str] = ["src", "tests", "scripts", "tools", "codegen", "docs", "examples"]

# Leaked spec-artifact codes:
#   Criterion prefixes (AC, FR, NFR, WP) followed by an optional '#', one or more
#   digits, and an optional lowercase letter — covering the bare, hash, and
#   sub-criterion suffix forms the docs use interchangeably.
#   Task prefix (T) followed by 2+ digits, not followed by ':' and a digit — catches
#   task IDs while skipping clock times (colon+digit, as in HH:MM:SS timestamps).
#   A colon followed by a non-digit (a planning label colon) IS caught.
#   Case-sensitive: these codes are always uppercase, so prose words like "tofu" or
#   "frame" never match.
TOKEN_RE = re.compile(r"\b(?:AC|FR|NFR|WP)#?\d+[a-z]?\b|\bT\d{2,}\b(?!:\d)")

# Filenames have no clock times and use '.', '_', '-' as separators — and '_' is a
# word character, so '\b' would miss 'T05_notes.py'. Match a whole separated segment
# instead, which also keeps embedded look-alike tokens (BAT05) from matching.
FILENAME_TOKEN_RE = re.compile(r"^(?:(?:AC|FR|NFR|WP)#?\d+|T\d{2,})$", re.IGNORECASE)


def check_file(path: Path) -> list[tuple[int, str]]:
    """Return a sorted, de-duplicated list of (1-based line number, token) for leaked tokens.

    Scans comments and docstring text. Does not scan arbitrary string literals.
    """
    source = path.read_text()
    lines = source.splitlines()
    hits: set[tuple[int, str]] = set()

    # Comments via tokenize — exact line numbers, no string literals.
    try:
        tokens = tokenize.generate_tokens(io.StringIO(source).readline)
        for tok in tokens:
            if tok.type == tokenize.COMMENT:
                for m in TOKEN_RE.finditer(tok.string):
                    hits.add((tok.start[0], m.group(0)))
    except (tokenize.TokenError, IndentationError):
        # Fall through to AST below; tokenize chokes on some valid-but-odd sources.
        pass

    # Docstrings via AST line spans — scanned over raw source lines for exact line numbers.
    for start, end in docstring_spans(ast.parse(source)):
        for lineno in range(start, end + 1):
            for m in TOKEN_RE.finditer(lines[lineno - 1]):
                hits.add((lineno, m.group(0)))

    return sorted(hits)


def iter_paths() -> list[Path]:
    """Return every .py file under the scanned directories, sorted for stable output.

    The full-scan entry point the characterization tests parametrize over; ``main`` calls
    ``resolve_paths`` directly so a pre-commit run can scan just the staged files. Both go
    through ``resolve_paths``, so the full-scan path can't drift from the per-file path.
    """
    return resolve_paths([], REPO_ROOT, SCAN_DIRS)


def check_filename(path: Path) -> list[str]:
    """Return any leaked tokens found among the file name's separated segments."""
    return [seg for seg in re.split(r"[._\-]", path.name) if FILENAME_TOKEN_RE.match(seg)]


def main() -> int:
    # This checker reports two violation kinds with different formats (content lines
    # and filenames), so it keeps its own runner rather than sharing run_check.
    content_violations: list[tuple[Path, int, str]] = []
    name_violations: list[tuple[Path, str]] = []

    for path in resolve_paths(sys.argv[1:], REPO_ROOT, SCAN_DIRS):
        rel = path.relative_to(REPO_ROOT)
        for lineno, token in check_file(path):
            content_violations.append((rel, lineno, token))
        name_violations.extend((rel, token) for token in check_filename(path))

    if content_violations or name_violations:
        total = len(content_violations) + len(name_violations)
        print(f"ERROR: {total} leaked spec-artifact token(s) found:")
        print()
        for rel, lineno, token in content_violations:
            print(f"  {rel}:{lineno} — {token}")
        for rel, token in name_violations:
            print(f"  {rel} (filename) — {token}")
        print()
        print("These are planning codes (acceptance criteria, requirements, tasks, work")
        print("packages) that leaked from design docs. Describe the thing, not its plan ID.")
        return 1

    print(f"OK: no leaked spec-artifact tokens found under {', '.join(SCAN_DIRS)}/.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
