#!/usr/bin/env python3
"""CI guard: detect drift between JS breakpoint constants and CSS breakpoints.

Responsive breakpoints live in two places the browser cannot keep in sync:
  - JS/TS constants in frontend/src/hooks/use-media-query.ts (BREAKPOINT_* exports)
  - Tailwind `@theme inline` breakpoint registrations in frontend/src/global.css
  - CSS `@media (max-width: Npx)` queries across frontend/src/**/*.css
  - Tailwind responsive utility prefixes across frontend/src/**/*.ts(x)

CSS custom properties can't be used inside `@media` queries, so the pixel values
are duplicated literally and can silently drift apart. This script parses all
three sources and fails when either a Tailwind screen registration or a CSS
`@media (max-width:)` breakpoint or Tailwind responsive utility has no matching
JS constant — the drift direction that bites: styling introduces a breakpoint
the JS layer (and anyone reading the constants file) knows nothing about.

JS constants without a matching CSS query are allowed: a breakpoint may be
declared for programmatic use via `useMediaQuery(BREAKPOINT_X)` before any CSS
rule needs it. The reverse — a CSS breakpoint with no constant — is the bug.

Usage:
    python tools/frontend/check_breakpoint_drift.py
    python tools/frontend/check_breakpoint_drift.py --smoke-test
"""

import argparse
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
FRONTEND_SRC = REPO_ROOT / "frontend" / "src"
MEDIA_QUERY_TS = FRONTEND_SRC / "hooks" / "use-media-query.ts"
GLOBAL_CSS = FRONTEND_SRC / "global.css"

# Matches: export const BREAKPOINT_MOBILE = 768;
JS_CONST_PATTERN = re.compile(r"export\s+const\s+(BREAKPOINT_[A-Z_]+)\s*=\s*(\d+)\s*;")

# Matches the max-width inside an @media query, e.g. `@media screen and (max-width: 768px)`.
# Anchored on `@media` (DOTALL) so component-level `min-width`/`max-width` declarations
# used for sizing — not responsive breakpoints — are ignored.
# NOTE: this regex assumes single-line @media queries (the current CSS satisfies this).
MEDIA_BREAKPOINT_PATTERN = re.compile(r"@media[^{]*?max-width:\s*(\d+)px", re.DOTALL)
THEME_BREAKPOINT_PATTERN = re.compile(r"--breakpoint-([\w-]+):\s*(\d+)px\s*;")
TAILWIND_MAX_SCREEN_PATTERN = re.compile(r"(?<![\w-])max-(?!width\b)([a-z][\w-]*):")
TAILWIND_ARBITRARY_PX_PATTERN = re.compile(r"(?<![\w-])(max|min)-\[(\d+)px\]:")

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


def extract_theme_breakpoints() -> dict[str, int]:
    """Return {screen_name: pixel_value} for every Tailwind theme breakpoint."""
    if not GLOBAL_CSS.exists():
        return {}

    found: dict[str, int] = {}
    text = CSS_BLOCK_COMMENT.sub("", GLOBAL_CSS.read_text())
    for name, value in THEME_BREAKPOINT_PATTERN.findall(text):
        found[name] = int(value)
    return found


def theme_breakpoints_by_value(theme: dict[str, int]) -> dict[int, list[Path]]:
    """Return {pixel_value: [global.css]} for Tailwind theme registrations."""
    found: dict[int, list[Path]] = {}
    for value in theme.values():
        found.setdefault(value, []).append(GLOBAL_CSS)
    return found


def find_frontend_source_files() -> list[Path]:
    """Return frontend TS/TSX source files that may contain Tailwind class strings."""
    return [
        path for pattern in ("*.ts", "*.tsx") for path in FRONTEND_SRC.rglob(pattern) if not path.name.endswith(".d.ts")
    ]


def extract_tailwind_utility_breakpoints(
    theme: dict[str, int], js: dict[int, str]
) -> tuple[dict[int, list[Path]], dict[str, list[Path]]]:
    """Return pixel breakpoints and unknown named screens used in Tailwind utility prefixes."""
    found: dict[int, list[Path]] = {}
    unknown_screens: dict[str, list[Path]] = {}
    registered_screen_patterns = {screen: re.compile(rf"(?<![\w-]){re.escape(screen)}:") for screen in theme}
    for source_file in sorted(find_frontend_source_files()):
        text = source_file.read_text()
        for screen, pattern in registered_screen_patterns.items():
            if pattern.search(text):
                found.setdefault(theme[screen], []).append(source_file)
        for screen in TAILWIND_MAX_SCREEN_PATTERN.findall(text):
            if screen in theme:
                found.setdefault(theme[screen], []).append(source_file)
            else:
                unknown_screens.setdefault(screen, []).append(source_file)
        for match in TAILWIND_ARBITRARY_PX_PATTERN.finditer(text):
            kind = match.group(1)
            value = int(match.group(2))
            if kind == "min" and value not in js and value - 1 in js:
                value -= 1
            found.setdefault(value, []).append(source_file)
    return found, unknown_screens


def find_missing_constants(js: dict[int, str], css: dict[int, list[Path]]) -> set[int]:
    """Return CSS breakpoint values that have no matching JS constant."""
    return set(css) - set(js)


def run_smoke_test() -> bool:
    """Built-in smoke test: confirm covered breakpoints pass and uncovered ones are caught."""
    js = {
        480: "BREAKPOINT_SMALL_MOBILE",
        768: "BREAKPOINT_MOBILE",
        900: "BREAKPOINT_SIDEBAR",
        1024: "BREAKPOINT_TABLET",
    }

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

    theme_breakpoints = {480: [Path("global.css")], 768: [Path("global.css")]}
    missing = find_missing_constants(js, theme_breakpoints)
    if missing:
        print(f"SMOKE TEST FAILED: theme breakpoints should not report missing constants, got {missing}")
        return False

    tw_breakpoints, unknown_screens = extract_tailwind_utility_breakpoints(
        {"small-mobile": 480, "mobile": 768, "sidebar": 900, "tablet": 1024}, js
    )
    if unknown_screens:
        print(f"SMOKE TEST FAILED: current source should not report unknown screens, got {unknown_screens}")
        return False
    missing = find_missing_constants(js, tw_breakpoints)
    if missing:
        print(f"SMOKE TEST FAILED: current Tailwind utility breakpoints should have JS constants, got {missing}")
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

    theme = extract_theme_breakpoints()
    if not theme:
        print(
            f"ERROR: no Tailwind @theme breakpoint registrations found in {GLOBAL_CSS.relative_to(REPO_ROOT)}",
            file=sys.stderr,
        )
        return 1

    theme_by_value = theme_breakpoints_by_value(theme)
    css = extract_css_breakpoints()
    if not css:
        print("ERROR: no @media (max-width: Npx) queries found in frontend/src/**/*.css", file=sys.stderr)
        return 1
    tailwind_utilities, unknown_screens = extract_tailwind_utility_breakpoints(theme, js)
    if unknown_screens:
        print("ERROR: Tailwind responsive utility prefixes with no matching @theme screen:")
        print()
        for screen, files in sorted(unknown_screens.items()):
            locations = ", ".join(str(p.relative_to(REPO_ROOT)) for p in sorted(set(files)))
            print(f"  {screen}: — used in: {locations}")
        print()
        print("Register the screen in frontend/src/global.css or fix the utility prefix.")
        return 1

    missing_theme = find_missing_constants(js, theme_by_value)
    missing_css = find_missing_constants(js, css)
    missing_tailwind = find_missing_constants(js, tailwind_utilities)
    missing = missing_theme | missing_css | missing_tailwind

    if missing:
        print("ERROR: CSS breakpoints with no matching JS constant:")
        print()
        for value in sorted(missing_theme):
            files = ", ".join(str(p.relative_to(REPO_ROOT)) for p in theme_by_value[value])
            print(f"  {value}px — Tailwind @theme registration in: {files}")
        for value in sorted(missing_css):
            files = ", ".join(str(p.relative_to(REPO_ROOT)) for p in css[value])
            print(f"  {value}px — CSS @media usage in: {files}")
        for value in sorted(missing_tailwind):
            files = ", ".join(str(p.relative_to(REPO_ROOT)) for p in sorted(set(tailwind_utilities[value])))
            print(f"  {value}px — Tailwind utility usage in: {files}")
        print()
        print(f"Add a constant to {MEDIA_QUERY_TS.relative_to(REPO_ROOT)}, e.g.:")
        print("    /** Must match CSS/Tailwind `<value>px` breakpoints */")
        print("    export const BREAKPOINT_<NAME> = <value>;")
        print()
        print("Every responsive breakpoint used in CSS or Tailwind theme config must have")
        print("a named JS constant so the sources stay in sync and the breakpoint is")
        print("discoverable from code.")
        return 1

    covered = sorted(set(theme_by_value) | set(css) | set(tailwind_utilities))
    js_only = sorted(set(js) - set(covered))
    covered_display = ", ".join(f"{v}px ({js[v]})" for v in covered)
    print(f"OK: all {len(covered)} CSS/Tailwind breakpoint(s) have a matching JS constant: {covered_display}")
    if js_only:
        extras = ", ".join(f"{v}px ({js[v]})" for v in js_only)
        print(f"(JS-only constants, declared for programmatic use, no CSS query yet: {extras})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
