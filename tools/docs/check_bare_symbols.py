#!/usr/bin/env python3
"""CI guard: detect public API symbols mentioned without backtick formatting.

Finds class/type names from hassette's public API that appear as bare text
in documentation pages (not wrapped in backticks or markdown links). These
should be code-formatted for consistency and to distinguish them from prose.

Usage:
    python tools/docs/check_bare_symbols.py          # report only
    python tools/docs/check_bare_symbols.py --fix    # fix in place
"""

import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
DOCS_DIR = REPO_ROOT / "docs" / "pages"

SYMBOLS = {
    "AppConfig",
    "AppSync",
    "BaseState",
    "BinarySensorState",
    "Bus",
    "CallServiceEvent",
    "DomainStates",
    "LightState",
    "RawStateChangeEvent",
    "ScheduledJob",
    "Scheduler",
    "SensorState",
    "StateManager",
    "StateProxy",
    "Subscription",
    "TaskBucket",
    "TypeRegistry",
    "StateRegistry",
}


def check_page(path: Path, fix: bool = False) -> list[str]:
    text = path.read_text()
    lines = text.split("\n")
    in_code = False
    findings: list[str] = []
    new_lines = []

    for i, line in enumerate(lines, 1):
        if line.strip().startswith("```"):
            in_code = not in_code
            new_lines.append(line)
            continue
        # Skip code fences (handled above), table rows, and headings. Symbols in
        # headings are titles by convention and are not code-formatted.
        # NOTE: tools/docs/check_xref_coverage.py applies the same three skips — keep in sync.
        stripped = line.strip()
        if in_code or stripped.startswith("|") or stripped.startswith("#"):
            new_lines.append(line)
            continue

        for sym in SYMBOLS:
            for m in re.finditer(rf"(?<!`)\b{sym}\b(?!`|_)", line):
                before = line[: m.start()]
                if before.count("[") > before.count("]"):
                    continue
                rel = path.relative_to(DOCS_DIR)
                findings.append(f"{rel}:{i}: `{sym}` missing backticks")

        if fix:
            for sym in SYMBOLS:
                line = re.sub(
                    rf"(?<!`)(\b{sym}\b)(?!`|_)",
                    lambda m: f"`{m.group(1)}`",
                    line,
                )
        new_lines.append(line)

    if fix and findings:
        path.write_text("\n".join(new_lines))

    return findings


def main() -> int:
    fix = "--fix" in sys.argv
    all_findings: list[str] = []

    for md in sorted(DOCS_DIR.rglob("*.md")):
        if "snippets" in str(md):
            continue
        all_findings.extend(check_page(md, fix=fix))

    if not all_findings:
        print("OK: no bare public symbols found in docs")
        return 0

    if fix:
        print(f"Fixed {len(all_findings)} bare symbol(s)")
        return 0

    print(f"FAIL: {len(all_findings)} bare public symbol(s) found:\n")
    for f in all_findings:
        print(f"  {f}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
