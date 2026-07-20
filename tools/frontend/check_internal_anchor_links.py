#!/usr/bin/env python3
"""CI guard: detect native <a> tags used for internal routes instead of wouter Link.

Scans all .tsx files under frontend/src/ for <a href="..."> where the href is
an internal route (starts with /) rather than an external URL, fragment, or
protocol link. Also flags <a href={expr}> with dynamic expressions, since
internal navigation should use wouter's <Link> component for SPA routing —
a native anchor forces a full page reload.

Usage:
    python tools/frontend/check_internal_anchor_links.py
"""

import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
FRONTEND_SRC = REPO_ROOT / "frontend" / "src"

# Match <a on a line (the tag may span multiple lines, but href is usually on the same line as <a or adjacent)
ANCHOR_TAG = re.compile(r"<a\b")

# Literal string href: href="/..." or href="http://..."
LITERAL_HREF = re.compile(r"""\bhref\s*=\s*"([^"]*)" """.strip())
# Expression href: href={...}
EXPR_HREF = re.compile(r"\bhref\s*=\s*\{([^}]+)\}")

# Prefixes that indicate external or non-route hrefs
EXTERNAL_PREFIXES = ("http://", "https://", "mailto:", "tel:", "#")

# file:line exemptions for cases where a native <a> is intentional
EXEMPTIONS: dict[str, str] = {
    # "frontend/src/path.tsx:42": "reason",
}


def is_exempt(rel_path: str, line_num: int) -> bool:
    return f"{rel_path}:{line_num}" in EXEMPTIONS


def scan_file(tsx_path: Path) -> list[tuple[Path, int, str]]:
    findings: list[tuple[Path, int, str]] = []
    try:
        lines = tsx_path.read_text().splitlines()
    except OSError:
        return findings

    # Build a buffer of consecutive lines for multi-line tag matching
    i = 0
    while i < len(lines):
        line = lines[i]
        line_num = i + 1

        if not ANCHOR_TAG.search(line):
            i += 1
            continue

        # Gather the full tag (up to 5 lines to handle multi-line JSX attributes)
        tag_lines = line
        end = i + 1
        while end < min(i + 5, len(lines)) and ">" not in tag_lines.split("<a", 1)[-1]:
            tag_lines += " " + lines[end]
            end += 1

        # Check for literal internal hrefs
        lit = LITERAL_HREF.search(tag_lines)
        if lit:
            href_val = lit.group(1)
            if href_val.startswith("/") and not any(href_val.startswith(p) for p in EXTERNAL_PREFIXES):
                findings.append((tsx_path, line_num, f'"{href_val}"'))
            i = end
            continue

        # Check for expression hrefs — any dynamic href on an <a> is suspect
        expr = EXPR_HREF.search(tag_lines)
        if expr:
            expr_text = expr.group(1).strip()
            # Template literals starting with / are clearly internal
            # Bare variables are also suspect — they're usually computed internal paths
            # Only skip if the expression is clearly external (starts with http literal)
            if not (expr_text.startswith("`http") or expr_text.startswith('"http')):
                findings.append((tsx_path, line_num, f"{{{expr_text}}}"))

        i = end if end > i + 1 else i + 1

    return findings


def main() -> int:
    all_findings: list[tuple[Path, int, str]] = []

    for tsx_file in sorted(FRONTEND_SRC.rglob("*.tsx")):
        if tsx_file.name.endswith(".test.tsx"):
            continue
        all_findings.extend(scan_file(tsx_file))

    violations: list[tuple[str, int, str]] = []
    exempted = 0
    for path, line_num, href in all_findings:
        rel = str(path.relative_to(REPO_ROOT))
        if is_exempt(rel, line_num):
            exempted += 1
            continue
        violations.append((rel, line_num, href))

    if violations:
        print(f"ERROR: {len(violations)} native <a> tag(s) used for internal routes:")
        print()
        for rel, line_num, href in violations:
            print(f"  {rel}:{line_num} — href={href}")
        print()
        print("Internal navigation should use wouter's <Link> component for SPA")
        print("routing. A native <a> with an internal path forces a full page reload.")
        print()
        print("To fix: import { Link } from 'wouter' and replace <a href=...> with <Link href=...>")
        print()
        print("If the native <a> is intentional, add an entry to EXEMPTIONS in this script.")
        return 1

    msg = "OK: no native <a> tags with internal routes found."
    if exempted:
        msg += f" ({exempted} exempted)"
    print(msg)
    return 0


if __name__ == "__main__":
    sys.exit(main())
