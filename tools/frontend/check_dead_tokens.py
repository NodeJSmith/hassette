#!/usr/bin/env python3
"""CI guard: detect unused CSS custom properties in frontend/src/global.css.

Extracts source-token custom property definitions (--name: value) from the
`:root` and `[data-theme="dark"]` blocks in global.css and checks each against
all .css, .ts, and .tsx files under frontend/src/. Exported alias tokens are
excluded because they are a public styling surface, not dead implementation
detail. Reports source properties that are never referenced. Exits non-zero if
any unreferenced tokens are found.

Usage:
    python tools/frontend/check_dead_tokens.py
"""

import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
GLOBAL_CSS = REPO_ROOT / "frontend" / "src" / "global.css"
FRONTEND_SRC = REPO_ROOT / "frontend" / "src"

SOURCE_TOKEN_STOP_MARKERS = {
    ":root": "--background",
    '[data-theme="dark"]': "--primary",
}


def extract_block(css_text: str, selector: str) -> str:
    """Extract the body of the first top-level CSS block for `selector`."""
    start = css_text.find(f"{selector} {{")
    if start == -1:
        return ""

    body_start = start + len(f"{selector} {{")
    depth = 1
    index = body_start
    while index < len(css_text) and depth > 0:
        char = css_text[index]
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
        index += 1

    if depth != 0:
        return ""

    return css_text[body_start : index - 1]


def extract_token_definitions(css_text: str) -> list[str]:
    """Extract all unique source-token custom property names from theme root blocks."""
    pattern = re.compile(r"^\s*(--[\w-]+)\s*:", re.MULTILINE)
    tokens: list[str] = []
    for selector, stop_marker in SOURCE_TOKEN_STOP_MARKERS.items():
        block = extract_block(css_text, selector)
        source_block = block.split(f"  {stop_marker}:", maxsplit=1)[0]
        tokens.extend(pattern.findall(source_block))
    return list(dict.fromkeys(tokens))


def find_frontend_files() -> list[Path]:
    """Return all .css/.ts/.tsx files under frontend/src/ (excluding .d.ts)."""
    files: list[Path] = []
    for pattern in ("*.css", "*.ts*"):
        files.extend(FRONTEND_SRC.rglob(pattern))
    return [f for f in files if not f.name.endswith(".d.ts")]


def build_corpus(files: list[Path]) -> str:
    """Concatenate all file contents for substring search."""
    parts = []
    for f in files:
        try:
            parts.append(f.read_text())
        except OSError:
            continue
    return "\n".join(parts)


def is_referenced(token: str, corpus: str) -> bool:
    """Return True if `token` appears outside its own definition line(s) as a complete token.

    Uses a word-boundary match to avoid prefix collisions: ``--accent`` must not
    be counted as referenced just because ``--accent-hover`` appears in the corpus.
    A token name is delimited by any non-identifier character (whitespace, comma,
    closing paren, colon, semicolon) or end-of-string.
    """
    definition_line = re.compile(rf"^\s*{re.escape(token)}\s*:.*$", re.MULTILINE)
    remainder = definition_line.sub("", corpus)
    reference_re = re.compile(rf"{re.escape(token)}(?![\w-])")
    return bool(reference_re.search(remainder))


def main() -> int:
    if not GLOBAL_CSS.exists():
        print(f"ERROR: global CSS file not found: {GLOBAL_CSS}", file=sys.stderr)
        return 1

    css_text = GLOBAL_CSS.read_text()
    all_tokens = extract_token_definitions(css_text)

    source_files = find_frontend_files()
    if not source_files:
        print("WARNING: No .css/.ts/.tsx files found under frontend/src/", file=sys.stderr)
        return 0

    corpus = build_corpus(source_files)

    unreferenced = [token for token in all_tokens if not is_referenced(token, corpus)]

    if unreferenced:
        print(f"ERROR: {len(unreferenced)} unreferenced token(s) found in global.css:")
        for token in sorted(unreferenced):
            print(f"  {token}")
        print()
        print("These tokens are not referenced in any .css/.ts/.tsx file under frontend/src/.")
        print("Remove them from global.css if they are truly unused.")
    else:
        print(f"OK: all {len(all_tokens)} tokens in global.css appear to be referenced.")

    return 1 if unreferenced else 0


if __name__ == "__main__":
    sys.exit(main())
