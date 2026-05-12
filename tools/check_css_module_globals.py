#!/usr/bin/env python3
"""CI guard: detect bare state modifier patterns in CSS module files.

Greps all .module.css files under frontend/src/ for bare state modifier
class combinations without :global() escaping:
  .someClass.is-active    <- WRONG: is-active will be scoped to a hashed name
  .someClass.is-blocked   <- WRONG
  .someClass.is-expanded  <- WRONG
  .someClass.is-open      <- WRONG

The correct pattern is:
  .someClass:global(.is-active)   <- OK: is-active is treated as a global name

Exits non-zero if any match is found.

Usage:
    python tools/check_css_module_globals.py
"""

import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
FRONTEND_SRC = REPO_ROOT / "frontend" / "src"

# State modifier class names that are applied as string literals at runtime
# and must NOT be scoped by the CSS Modules compiler.
# Note: status-bar.module.css also uses runtime classes ("connecting", "disconnected",
# "degraded") but those are component-specific, not a shared convention — not guarded here.
STATE_MODIFIERS = [
    "is-active",
    "is-blocked",
    "is-expandable",
    "is-expanded",
    "is-open",
]


# Pattern: .anyClassName.is-modifier (without :global preceding the modifier)
# Matches things like:
#   .appItem.is-active
#   .row.is-expanded
# Does NOT match:
#   .appItem:global(.is-active)   <- correct pattern, skip
#   /* .appItem.is-active */      <- comment, skip
def build_pattern(modifier: str) -> re.Pattern[str]:
    """Build regex that matches bare .className.modifier (not :global()).

    Only detects the is-* state modifier classes listed in STATE_MODIFIERS.
    Does not detect module-scoped classes used inside :global() ancestor chains.
    """
    escaped = re.escape(modifier)
    # Match .word-chars followed immediately by .modifier (no :global( in between)
    # Negative lookbehind for :global( to skip correct usages
    return re.compile(
        r"(?<!:global\()"  # not preceded by :global(
        r"\.[a-zA-Z][\w-]*"  # .className
        r"\." + escaped,  # .is-modifier (bare, not inside :global)
        re.MULTILINE,
    )


PATTERNS: list[tuple[str, re.Pattern[str]]] = [(modifier, build_pattern(modifier)) for modifier in STATE_MODIFIERS]


def find_module_css_files() -> list[Path]:
    """Return all .module.css files under frontend/src/."""
    return list(FRONTEND_SRC.rglob("*.module.css"))


def check_file(path: Path) -> list[tuple[int, str, str]]:
    """Return list of (line_number, modifier, line_text) for violations."""
    violations: list[tuple[int, str, str]] = []
    try:
        text = path.read_text()
    except OSError:
        return violations

    lines = text.splitlines()
    in_block_comment = False
    for lineno, line in enumerate(lines, start=1):
        stripped = line.strip()
        if in_block_comment:
            if "*/" in stripped:
                in_block_comment = False
            continue
        if stripped.startswith("/*") and "*/" not in stripped:
            in_block_comment = True
            continue
        line_no_comments = re.sub(r"/\*.*?\*/", "", line)
        if not line_no_comments.strip():
            continue
        for modifier, pattern in PATTERNS:
            if pattern.search(line_no_comments):
                violations.append((lineno, modifier, line.rstrip()))

    return violations


def main() -> int:
    module_files = find_module_css_files()

    if not module_files:
        print("No .module.css files found — nothing to check.")
        return 0

    all_violations: list[tuple[Path, int, str, str]] = []

    for path in sorted(module_files):
        file_violations = check_file(path)
        for lineno, modifier, line_text in file_violations:
            all_violations.append((path, lineno, modifier, line_text))

    if all_violations:
        print(f"ERROR: {len(all_violations)} bare state modifier pattern(s) found in .module.css files.")
        print()
        modifier_list = ", ".join(STATE_MODIFIERS)
        print(f"State modifier classes ({modifier_list}) are applied")
        print("as string literals at runtime. Without :global(), the CSS Modules compiler will")
        print("scope them to a hashed name that never matches the applied class.")
        print()
        print("Replace bare patterns with :global() syntax:")
        print("  WRONG:  .appItem.is-active { ... }")
        print("  RIGHT:  .appItem:global(.is-active) { ... }")
        print()

        current_file = None
        for file_path, lineno, _modifier, line_text in all_violations:
            rel = file_path.relative_to(REPO_ROOT)
            if file_path != current_file:
                print(f"  {rel}:")
                current_file = file_path
            print(f"    line {lineno}: {line_text.strip()}")
        return 1

    print(f"OK: no bare state modifier patterns found in {len(module_files)} .module.css file(s).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
