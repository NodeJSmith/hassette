#!/usr/bin/env python3
"""CI guard: detect unused class selectors in frontend/src/global.css.

Extracts all class selectors from global.css and checks each against all .ts
and .tsx files under frontend/src/. Reports selectors that are not referenced
in any source file. Exits non-zero if any unreferenced selectors are found.

Maintains an annotated exemption list for:
  - Dynamically-assembled class families (e.g. ht-badge--${variant})
  - Third-party injected classes (shiki syntax highlighting)
  - Parser false positives (e.g. woff2 from @font-face src)

Usage:
    python tools/frontend/check_dead_global_css.py
"""

import contextlib
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
GLOBAL_CSS = REPO_ROOT / "frontend" / "src" / "global.css"
STYLES_DIR = REPO_ROOT / "frontend" / "src" / "styles"
FRONTEND_SRC = REPO_ROOT / "frontend" / "src"

# Exemption list: class name prefixes that are assembled dynamically at runtime
# or injected by third-party libraries. These cannot be detected by static grep.
# Format: (prefix_or_exact, reason)
EXEMPTIONS: list[tuple[str, str]] = [
    # Third-party injected classes from shiki syntax highlighter
    ("shiki", "third-party: injected by shiki syntax highlighter"),
    ("line--", "third-party: injected by shiki (line token classes)"),
]

# Exact class names that are known-exempt (not prefix-based)
EXACT_EXEMPTIONS: set[str] = {
    "line",  # shiki injects class="line" on code lines
    "woff2",  # false positive: appears in @font-face src: url(...) format('woff2')
}


def is_exempt(class_name: str) -> bool:
    """Return True if this class is on the exemption list."""
    if class_name in EXACT_EXEMPTIONS:
        return True
    return any(class_name.startswith(prefix) for prefix, _reason in EXEMPTIONS)


def extract_class_selectors(css_text: str) -> list[str]:
    """Extract all unique class names from CSS selector rules."""
    # Match .classname at start of selector or after combinators/pseudo-classes
    pattern = re.compile(r"\.([a-zA-Z_][a-zA-Z0-9_-]*)")
    return list(dict.fromkeys(pattern.findall(css_text)))


def find_frontend_source_files() -> list[Path]:
    """Return all .ts/.tsx source files under frontend/src/ (excluding .d.ts)."""
    return [f for f in FRONTEND_SRC.rglob("*.ts*") if not f.name.endswith(".d.ts")]


def build_tsx_corpus(tsx_files: list[Path]) -> str:
    """Concatenate all source for substring search. Short class names (e.g. "page") may match
    inside comments or identifiers — accepted trade-off for a grep-style linter.
    """
    parts = []
    for f in tsx_files:
        with contextlib.suppress(OSError):
            parts.append(f.read_text())
    return "\n".join(parts)


def _read_all_style_files() -> str | None:
    """Read all shared CSS files: global.css (which may just be @imports) + styles/*.css.

    Duplicated in check_global_css_allowlist.py — kept inline for script self-containment.
    """
    parts: list[str] = []
    if GLOBAL_CSS.exists():
        parts.append(GLOBAL_CSS.read_text())
    if STYLES_DIR.is_dir():
        parts.extend(css_file.read_text() for css_file in sorted(STYLES_DIR.glob("*.css")))
    if not parts:
        return None
    return "\n".join(parts)


def main() -> int:
    css_text = _read_all_style_files()
    if css_text is None:
        print("ERROR: no global CSS files found (checked global.css and styles/)", file=sys.stderr)
        return 1

    all_classes = extract_class_selectors(css_text)

    source_files = find_frontend_source_files()
    if not source_files:
        print("WARNING: No .ts/.tsx files found under frontend/src/", file=sys.stderr)
        return 0

    tsx_corpus = build_tsx_corpus(source_files)

    unreferenced: list[str] = []
    exempted: list[str] = []

    for class_name in all_classes:
        if is_exempt(class_name):
            exempted.append(class_name)
            continue
        # Check if the class name appears in any .tsx file
        if class_name not in tsx_corpus:
            unreferenced.append(class_name)

    if unreferenced:
        print(f"ERROR: {len(unreferenced)} unreferenced class(es) found in global CSS:")
        for cls in sorted(unreferenced):
            print(f"  .{cls}")
        print()
        print(f"({len(exempted)} class(es) skipped — on exemption list)")
        print()
        print("These classes are not referenced in any .ts/.tsx file.")
        print("Either remove them from the style files, or add to EXEMPTIONS in")
        print("tools/frontend/check_dead_global_css.py if the class is dynamically assembled.")
    else:
        print(f"OK: all {len(all_classes)} class selectors in global CSS appear to be referenced.")
        print(f"({len(exempted)} class(es) skipped — on exemption list)")

    return 1 if unreferenced else 0


if __name__ == "__main__":
    sys.exit(main())
