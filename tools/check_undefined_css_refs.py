#!/usr/bin/env python3
"""CI guard: detect raw ht-* class references in TSX that have no CSS definition.

Scans all .tsx files under frontend/src/ for raw ht-* class name strings and
verifies each one resolves to a selector in global.css or styles/*.css. Reports
references with no matching CSS definition. Exits non-zero if any are found.

This is the inverse of check_dead_global_css.py:
  - dead CSS check: "are all CSS classes referenced?" (CSS → TSX)
  - this check: "are all referenced CSS classes defined?" (TSX → CSS)

Usage:
    python tools/check_undefined_css_refs.py
"""

import contextlib
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
GLOBAL_CSS = REPO_ROOT / "frontend" / "src" / "global.css"
STYLES_DIR = REPO_ROOT / "frontend" / "src" / "styles"
FRONTEND_SRC = REPO_ROOT / "frontend" / "src"

HT_CLASS_PATTERN = re.compile(r"ht-[a-zA-Z][a-zA-Z0-9_-]*")

# Prefixes that appear as ht-* strings in TSX but are not CSS class references.
# Format: (prefix, reason)
EXACT_EXEMPTIONS: dict[str, str] = {
    "ht-theme": "JS-only class toggle on document.body, not a CSS selector",
    "ht-show-more": "dynamic ID prefix, not a CSS class",
}

EXEMPTIONS: list[tuple[str, str]] = [
    ("ht-confirm-dialog-", "ARIA ID prefix for dialog accessibility, not a CSS class"),
    ("ht-entry-", "dynamic data-testid / key prefix, not a CSS class"),
    ("ht-col-source", "defined in log-table.module.css via :global(), not in shared styles/"),
    ("ht-col-level", "defined in log-table.module.css via :global(), not in shared styles/"),
    ("ht-col-app", "defined in log-table.module.css via :global(), not in shared styles/"),
    ("ht-col-execution", "defined in log-table.module.css via :global(), not in shared styles/"),
]


def is_exempt(class_name: str) -> bool:
    if class_name in EXACT_EXEMPTIONS:
        return True
    return any(class_name.startswith(prefix) for prefix, _reason in EXEMPTIONS)


def extract_defined_classes() -> set[str]:
    """Extract all ht-* class selectors defined in global CSS and styles/*.css.

    CSS reading logic duplicated from check_dead_global_css.py — kept inline for script self-containment.
    """
    parts: list[str] = []
    if GLOBAL_CSS.exists():
        parts.append(GLOBAL_CSS.read_text())
    if STYLES_DIR.is_dir():
        parts.extend(css_file.read_text() for css_file in sorted(STYLES_DIR.glob("*.css")))
    if not parts:
        return set()

    css_text = "\n".join(parts)
    selector_pattern = re.compile(r"\.(ht-[a-zA-Z][a-zA-Z0-9_-]*)")
    return set(selector_pattern.findall(css_text))


def find_tsx_references() -> list[tuple[Path, int, str]]:
    """Find all raw ht-* class references in .tsx files with file and line."""
    refs: list[tuple[Path, int, str]] = []
    for tsx_file in FRONTEND_SRC.rglob("*.tsx"):
        if tsx_file.name.endswith(".test.tsx"):
            continue
        with contextlib.suppress(OSError):
            for line_num, line in enumerate(tsx_file.read_text().splitlines(), 1):
                refs.extend((tsx_file, line_num, m.group()) for m in HT_CLASS_PATTERN.finditer(line))
    return refs


def main() -> int:
    defined = extract_defined_classes()
    if not defined:
        print("WARNING: no global CSS found — nothing to check against", file=sys.stderr)
        return 0

    refs = find_tsx_references()
    if not refs:
        print("OK: no raw ht-* class references found in TSX files.")
        return 0

    undefined: list[tuple[Path, int, str]] = []
    seen_classes: set[str] = set()

    exempted = 0
    for path, line_num, class_name in refs:
        if is_exempt(class_name):
            exempted += 1
            continue
        if class_name in defined:
            continue
        # BEM parent check: ht-btn--sm is valid if ht-btn is defined
        base = class_name.split("--")[0]
        if base != class_name and base in defined:
            continue
        undefined.append((path, line_num, class_name))
        seen_classes.add(class_name)

    if undefined:
        print(
            f"ERROR: {len(seen_classes)} undefined ht-* class(es) ({len(undefined)} occurrence(s)) referenced in TSX:"
        )
        print()
        for path, line_num, class_name in undefined:
            rel = path.relative_to(REPO_ROOT)
            print(f"  {rel}:{line_num} — .{class_name}")
        print()
        print("These classes are used in TSX but have no matching CSS selector in")
        print("global.css or styles/*.css. Either:")
        print("  - Migrate to a shared component (Button, Badge, Chip, Card)")
        print("  - Add the class definition to the appropriate styles/*.css file")
        return 1

    unique_refs = len({c for _, _, c in refs})
    print(f"OK: all {unique_refs} raw ht-* class reference(s) in TSX resolve to defined CSS selectors.")
    if exempted:
        print(f"({exempted} reference(s) skipped — on exemption list)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
