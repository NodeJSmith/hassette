#!/usr/bin/env python3
"""CI guard: detect drift between JS breakpoint constants and CSS media queries.

Responsive breakpoints live in two places the browser cannot keep in sync:
  - JS/TS constants in frontend/src/hooks/use-media-query.ts (BREAKPOINT_* exports)
  - CSS `@media (max-width: Npx)` queries across frontend/src/**/*.css

CSS custom properties can't be used inside `@media` queries, so the pixel values
are duplicated literally and can silently drift apart. This script parses both
sources and fails when a CSS `@media (max-width:)` breakpoint has no matching JS
constant — the drift direction that bites: CSS introduces a breakpoint the JS
layer (and anyone reading the constants file) knows nothing about.

JS constants without a matching CSS query are allowed: a breakpoint may be
declared for programmatic use via `useMediaQuery(BREAKPOINT_X)` before any CSS
rule needs it. The reverse — a CSS breakpoint with no constant — is the bug.

Usage:
    python tools/check_breakpoint_drift.py
    python tools/check_breakpoint_drift.py --smoke-test
"""

import argparse
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
FRONTEND_SRC = REPO_ROOT / "frontend" / "src"
MEDIA_QUERY_TS = FRONTEND_SRC / "hooks" / "use-media-query.ts"

# Matches: export const BREAKPOINT_MOBILE = 768;
JS_CONST_PATTERN = re.compile(r"export\s+const\s+(BREAKPOINT_[A-Z_]+)\s*=\s*(\d+)\s*;")

# Matches the max-width inside an @media query, e.g. `@media screen and (max-width: 768px)`.
# Anchored on `@media` (DOTALL) so component-level `min-width`/`max-width` declarations
# used for sizing — not responsive breakpoints — are ignored.
# NOTE: this regex assumes single-line @media queries (the current CSS satisfies this).
MEDIA_BREAKPOINT_PATTERN = re.compile(r"@media[^{]*?max-width:\s*(\d+)px", re.DOTALL)

# Stripped before matching so commented-out @media rules don't produce false positives.
CSS_BLOCK_COMMENT = re.compile(r"/\*.*?\*/", re.DOTALL)


def extract_js_breakpoints() -> dict[int, str]:
    """Return {pixel_value: constant_name} for every BREAKPOINT_* export in the TS file."""
    if not MEDIA_QUERY_TS.exists():
        return {}
    text = MEDIA_QUERY_TS.read_text()
    return {int(value): name for name, value in JS_CONST_PATTERN.findall(text)}


def extract_css_breakpoints() -> dict[int, list[Path]]:
    """Return {pixel_value: [css files using it]} for every @media max-width across the frontend."""
    found: dict[int, list[Path]] = {}
    for css_file in sorted(FRONTEND_SRC.rglob("*.css")):
        text = CSS_BLOCK_COMMENT.sub("", css_file.read_text())
        for match in MEDIA_BREAKPOINT_PATTERN.finditer(text):
            value = int(match.group(1))
            files = found.setdefault(value, [])
            if css_file not in files:
                files.append(css_file)
    return found


def find_missing_constants(js: dict[int, str], css: dict[int, list[Path]]) -> set[int]:
    """Return CSS breakpoint values that have no matching JS constant."""
    return set(css) - set(js)


def run_smoke_test() -> bool:
    """Built-in smoke test: confirm covered breakpoints pass and uncovered ones are caught."""
    js = {768: "BREAKPOINT_MOBILE", 900: "BREAKPOINT_SIDEBAR", 1024: "BREAKPOINT_TABLET"}

    covered_css = {768: [Path("a.css")], 900: [Path("b.css")]}
    missing = find_missing_constants(js, covered_css)
    if missing:
        print(f"SMOKE TEST FAILED: covered CSS should not report missing constants, got {missing}")
        return False

    drifted_css = {768: [Path("a.css")], 600: [Path("c.css")]}
    missing = find_missing_constants(js, drifted_css)
    if missing != {600}:
        print(f"SMOKE TEST FAILED: expected missing={{600}}, got {missing}")
        return False

    print("Smoke test passed.")
    return True


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--smoke-test", action="store_true", help="Run built-in smoke test and exit")
    args = parser.parse_args()

    if args.smoke_test:
        return 0 if run_smoke_test() else 1

    js = extract_js_breakpoints()
    if not js:
        print(f"ERROR: no BREAKPOINT_* constants found in {MEDIA_QUERY_TS.relative_to(REPO_ROOT)}", file=sys.stderr)
        return 1

    css = extract_css_breakpoints()
    if not css:
        print("ERROR: no @media (max-width: Npx) queries found in frontend/src/**/*.css", file=sys.stderr)
        return 1

    missing = find_missing_constants(js, css)

    if missing:
        print("ERROR: CSS media-query breakpoints with no matching JS constant:")
        print()
        for value in sorted(missing):
            files = ", ".join(str(p.relative_to(REPO_ROOT)) for p in css[value])
            print(f"  {value}px — used in: {files}")
        print()
        print(f"Add a constant to {MEDIA_QUERY_TS.relative_to(REPO_ROOT)}, e.g.:")
        print("    /** Must match CSS `@media (max-width: <value>px)` breakpoints */")
        print("    export const BREAKPOINT_<NAME> = <value>;")
        print()
        print("Every responsive breakpoint used in CSS must have a named JS constant so the")
        print("two sources stay in sync and the breakpoint is discoverable from code.")
        return 1

    js_only = sorted(set(js) - set(css))
    covered = ", ".join(f"{v}px ({js[v]})" for v in sorted(css))
    print(f"OK: all {len(css)} CSS media-query breakpoint(s) have a matching JS constant: {covered}")
    if js_only:
        extras = ", ".join(f"{v}px ({js[v]})" for v in js_only)
        print(f"(JS-only constants, declared for programmatic use, no CSS query yet: {extras})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
