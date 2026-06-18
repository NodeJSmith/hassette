#!/usr/bin/env python3
"""CI guard: detect deterministic AI-writing tells in src/ comments and docstrings.

This is the mechanizable subset of a clean-code review — the textual tells that a
regex can catch with high precision, not the structural judgment a human (or LLM)
reviewer makes. It catches two things:

    * Section-divider comments — a comment line that is a rule of decoration
      (``# -----``) or a label wrapped in decoration (``# --- Helpers ---``).
      A class or module that needs drawn dividers to be navigable needs fewer
      sections, not prettier separators. Delete the rule; keep any label as a
      plain comment.

    * Filler phrases — hedges and inflated Latinate verbs that add words without
      meaning. The full list, each paired with a plainer replacement, is in
      ``FILLER_PATTERNS`` below.

Scope is human-readable text only: comments (via ``tokenize``) and docstrings (via
AST line spans). Arbitrary string literals are not scanned. There is no escape
hatch — these are always cruft. If a pattern misfires, tighten the pattern.

Usage:
    python tools/check_llm_cruft.py
"""

import ast
import io
import re
import sys
import tokenize
from pathlib import Path

from lint_helpers import docstring_spans, iter_py_files

REPO_ROOT = Path(__file__).resolve().parent.parent

# Directories scanned, relative to the repo root.
SCAN_DIRS: list[str] = ["src"]

# A comment whose content (after the leading '#') is a bare rule of decoration. The
# 4+ floor avoids flagging a stray '# ---' a writer might use as a light separator.
DIVIDER_RULE = re.compile(r"^[-=#*~_]{4,}$")
# A label fenced by decoration: '--- Helpers ---'. A 3-char fence is enough here —
# unlike a bare rule, fencing a label is unambiguously a section header.
DIVIDER_WRAPPED = re.compile(r"^[-=#*~_]{3,}\s+\S.*\S\s+[-=#*~_]{3,}$")

# Filler phrases and inflated verbs, each paired with a suggested fix. Case-insensitive.
FILLER_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"\bit is important to note\b", re.IGNORECASE), "drop it; state the fact directly"),
    (re.compile(r"\bit should be noted\b", re.IGNORECASE), "drop it; state the fact directly"),
    (re.compile(r"\bit is worth noting\b", re.IGNORECASE), "drop it; state the fact directly"),
    (re.compile(r"\bplease note that\b", re.IGNORECASE), "drop 'please note that'"),
    (re.compile(r"\bneedless to say\b", re.IGNORECASE), "drop it"),
    (re.compile(r"\bdue to the fact that\b", re.IGNORECASE), "use 'because'"),
    (re.compile(r"\bin order to\b", re.IGNORECASE), "use 'to'"),
    (re.compile(r"\bas mentioned (?:above|previously|earlier)\b", re.IGNORECASE), "name the thing directly"),
    (re.compile(r"\b(?:leverage|leverages|leveraging)\b", re.IGNORECASE), "use 'use'"),
    (re.compile(r"\b(?:utilize|utilizes|utilizing)\b", re.IGNORECASE), "use 'use'"),
    (re.compile(r"\b(?:facilitate|facilitates|facilitating)\b", re.IGNORECASE), "use 'help' or be specific"),
]


def comment_body(text: str) -> str:
    """Return a comment's text with the leading '#' and surrounding whitespace removed."""
    return text.lstrip("#").strip()


def filler_hits(text: str) -> list[str]:
    """Return suggestions for every filler pattern that matches the text."""
    return [suggestion for pattern, suggestion in FILLER_PATTERNS if pattern.search(text)]


def check_file(path: Path) -> list[tuple[int, str]]:
    """Return a sorted, de-duplicated list of (1-based line number, finding) for cruft."""
    source = path.read_text()
    lines = source.splitlines()
    hits: set[tuple[int, str]] = set()

    # Comments: section dividers + filler phrases.
    try:
        for tok in tokenize.generate_tokens(io.StringIO(source).readline):
            if tok.type != tokenize.COMMENT:
                continue
            body = comment_body(tok.string)
            if DIVIDER_RULE.match(body) or DIVIDER_WRAPPED.match(body):
                hits.add((tok.start[0], "section-divider comment — delete the rule, keep any label as a plain comment"))
            for suggestion in filler_hits(tok.string):
                hits.add((tok.start[0], f"filler — {suggestion}"))
    except (tokenize.TokenError, IndentationError):
        pass

    # Docstrings: filler phrases only (dividers in docstrings are reST, not cruft).
    for start, end in docstring_spans(ast.parse(source)):
        for lineno in range(start, end + 1):
            for suggestion in filler_hits(lines[lineno - 1]):
                hits.add((lineno, f"filler — {suggestion}"))

    return sorted(hits)


def iter_paths() -> list[Path]:
    """Return every .py file under the scanned directories, sorted for stable output."""
    return iter_py_files(REPO_ROOT, SCAN_DIRS)


def main() -> int:
    violations: list[tuple[Path, int, str]] = []
    for path in iter_paths():
        rel = path.relative_to(REPO_ROOT)
        for lineno, finding in check_file(path):
            violations.append((rel, lineno, finding))

    if violations:
        print(f"ERROR: {len(violations)} AI-writing tell(s) found in src/:")
        print()
        for rel, lineno, finding in violations:
            print(f"  {rel}:{lineno} — {finding}")
        return 1

    print(f"OK: no AI-writing tells found under {', '.join(SCAN_DIRS)}/.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
