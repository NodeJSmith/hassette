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
# JSX tags can span multiple lines when attributes are wrapped. 5 lines covers
# the longest realistic <a ... > opening tag in this codebase.
MAX_TAG_LINES = 5

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

    for i, line in enumerate(lines):
        if not ANCHOR_TAG.search(line):
            continue

        line_num = i + 1
        tag_buf = line
        for j in range(i + 1, min(i + MAX_TAG_LINES, len(lines))):
            # Stop once the opening tag is closed (first > after the <a)
            after_tag = tag_buf.split("<a", 1)[-1]
            if ">" in after_tag:
                break
            tag_buf += " " + lines[j]

        finding = _check_tag(tag_buf, tsx_path, line_num)
        if finding:
            findings.append(finding)

    return findings


def _check_tag(tag: str, path: Path, line_num: int) -> tuple[Path, int, str] | None:
    lit = LITERAL_HREF.search(tag)
    if lit:
        href_val = lit.group(1)
        if href_val.startswith("/") and not any(href_val.startswith(p) for p in EXTERNAL_PREFIXES):
            return (path, line_num, f'"{href_val}"')
        return None

    expr = EXPR_HREF.search(tag)
    if expr:
        expr_text = expr.group(1).strip()
        # Flag all dynamic hrefs unless the expression is clearly an external URL.
        # This is intentionally broad: a false positive is a CI failure with an
        # actionable EXEMPTIONS entry, while a false negative is a silent full-page
        # reload on an internal route.
        if not (expr_text.startswith("`http") or expr_text.startswith('"http')):
            return (path, line_num, f"{{{expr_text}}}")

    return None


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
