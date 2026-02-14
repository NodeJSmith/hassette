#!/usr/bin/env python3
"""Check Jinja2 templates for banned patterns.

Checks:
  1. Inline <script> tags in partials/components (only allowed in pages via {% block scripts %} and base.html)
  2. Inline event handlers (onclick=, onchange=, oninput=, etc.)
"""

import re
import sys
from pathlib import Path

TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "src" / "hassette" / "web" / "templates"

# Directories where inline <script> is NOT allowed
SCRIPT_BANNED_DIRS = {"partials", "components", "macros"}

# Inline event handler pattern
INLINE_HANDLER_RE = re.compile(
    r"\b(onclick|onchange|oninput|onsubmit|onblur|onfocus|onmouseover|onmouseout|onkeydown|onkeyup|onkeypress)\s*=",
    re.IGNORECASE,
)

# Inline <script> tag (not a src= reference)
INLINE_SCRIPT_RE = re.compile(r"<script(?:\s[^>]*)?>", re.IGNORECASE)
SCRIPT_SRC_RE = re.compile(r"<script\s[^>]*\bsrc\s*=", re.IGNORECASE)


def check_file(path: Path, rel: str) -> list[str]:
    """Return list of error messages for a single template file."""
    errors: list[str] = []
    content = path.read_text(encoding="utf-8")
    lines = content.splitlines()

    # Determine which directory this file is in
    parts = Path(rel).parts
    in_banned_dir = len(parts) > 1 and parts[0] in SCRIPT_BANNED_DIRS

    for i, line in enumerate(lines, start=1):
        # Check inline event handlers everywhere
        match = INLINE_HANDLER_RE.search(line)
        if match:
            errors.append(f"{rel}:{i}: inline event handler '{match.group(1)}=' — use Alpine.js directives instead")

        # Check inline <script> in banned directories
        if in_banned_dir and INLINE_SCRIPT_RE.search(line) and not SCRIPT_SRC_RE.search(line):
            errors.append(f"{rel}:{i}: inline <script> in {parts[0]}/ — move to page-level {{% block scripts %}}")

    return errors


def main() -> int:
    if not TEMPLATES_DIR.is_dir():
        print(f"Templates directory not found: {TEMPLATES_DIR}", file=sys.stderr)
        return 1

    all_errors: list[str] = []
    for path in sorted(TEMPLATES_DIR.rglob("*.html")):
        rel = str(path.relative_to(TEMPLATES_DIR))
        all_errors.extend(check_file(path, rel))

    if all_errors:
        print(f"Found {len(all_errors)} template pattern violation(s):\n")
        for err in all_errors:
            print(f"  {err}")
        return 1

    print("All template pattern checks passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
