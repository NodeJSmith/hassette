#!/usr/bin/env python3
"""CI guard: prevent component-specific selectors from entering global.css.

Extracts all .ht-* class selectors from frontend/src/global.css and compares
them against an allowlist of shared class prefixes. Exits non-zero if any
unknown selector is found.

Usage:
    python tools/check_global_css_allowlist.py              # check full file
    python tools/check_global_css_allowlist.py --diff-only  # check only git diff
"""

import argparse
import re
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
GLOBAL_CSS = REPO_ROOT / "frontend" / "src" / "global.css"

# Shared class prefixes that are allowed to remain in global.css.
# BEM modifiers are matched by prefix: ht-btn--sm matches ht-btn.
# Entries that end in - or _ must be matched as prefixes (e.g. ht-text-, ht-mb-).
ALLOWLIST: list[str] = [
    # Layout primitives
    "ht-layout",
    "ht-main",
    "ht-page",
    "ht-section",
    "ht-page-header",
    "ht-level",
    # Surface components
    "ht-card",
    "ht-table",
    "ht-badge",
    "ht-btn",
    "ht-btn-group",
    "ht-chip",
    "ht-pill",
    "ht-search",
    "ht-alert",
    # Navigation & wayfinding
    "ht-breadcrumb",
    "ht-hamburger",
    "ht-drawer",
    "ht-skip-link",
    # Typography & display
    "ht-display",
    "ht-heading-4",
    "ht-icon",
    "ht-icon-svg",
    "ht-traceback",
    "ht-log-level-badge",
    "ht-detail-label",
    "ht-section-label",
    # Table infrastructure
    "ht-table-toolbar",
    "ht-table-card-scroll",
    "ht-error-card",
    # Utilities (text)
    "ht-text-",
    # Utilities (spacing — only values with live selectors)
    "ht-mb-",
    "ht-ml-",
    # Accessibility
    "ht-visually-hidden",
    # Level layout sub-elements
    "ht-level-start",
    "ht-level-end",
    "ht-level-item",
    # Mobile-responsive drawer overlay
    "ht-drawer-backdrop",
    # Table column width helpers (set on <th>/<td> alongside ht-table)
    "ht-col-",
]


def is_allowed(class_name: str) -> bool:
    """Return True if class_name matches any allowlist prefix."""
    for prefix in ALLOWLIST:
        if prefix.endswith("-") or prefix.endswith("_"):
            # Prefix-only match: ht-text- matches ht-text-muted but not ht-text
            if class_name.startswith(prefix):
                return True
        else:
            # Exact, BEM modifier (--), or BEM element (__) match
            if class_name == prefix or class_name.startswith(prefix + "--") or class_name.startswith(prefix + "__"):
                return True
    return False


def extract_ht_selectors(css_text: str) -> list[str]:
    """Extract all unique .ht-* class names from CSS text."""
    # Match .ht-word characters; stop at pseudo-classes, spaces, brackets, etc.
    pattern = re.compile(r"\.(ht-[\w-]+)")
    return list(dict.fromkeys(pattern.findall(css_text)))


def get_diff_text(base_ref: str) -> str:
    """Return added lines from diff against a base ref for global.css."""
    result = subprocess.run(
        ["git", "-C", str(REPO_ROOT), "diff", base_ref, "--", "frontend/src/global.css"],
        capture_output=True,
        text=True,
    )
    added = [line[1:] for line in result.stdout.splitlines() if line.startswith("+") and not line.startswith("+++")]
    return "\n".join(added)


def run_smoke_test() -> bool:
    """Built-in smoke test: verify allowed and disallowed selectors are detected."""
    allowed_sample = ".ht-btn { } .ht-btn--sm { } .ht-card { } .ht-text-muted { }"
    disallowed_sample = ".ht-new-widget__header { } .ht-sidebar__app-link { }"
    combined = allowed_sample + "\n" + disallowed_sample

    selectors = extract_ht_selectors(combined)
    unknown = [s for s in selectors if not is_allowed(s)]

    expected_unknown = {"ht-new-widget__header", "ht-sidebar__app-link"}
    if set(unknown) != expected_unknown:
        print(f"SMOKE TEST FAILED: expected unknown={expected_unknown}, got={set(unknown)}")
        return False

    # Verify allowed selectors pass
    allowed_selectors = extract_ht_selectors(allowed_sample)
    bad_allowed = [s for s in allowed_selectors if not is_allowed(s)]
    if bad_allowed:
        print(f"SMOKE TEST FAILED: these should be allowed: {bad_allowed}")
        return False

    print("Smoke test passed.")
    return True


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument(
        "--diff-only",
        action="store_true",
        help="Check only lines added in git diff (migration mode). Use with --diff-base.",
    )
    parser.add_argument(
        "--diff-base",
        type=str,
        default=None,
        help="Base ref for diff comparison (e.g., origin/main). Implies --diff-only.",
    )
    parser.add_argument(
        "--smoke-test",
        action="store_true",
        help="Run built-in smoke test and exit",
    )
    args = parser.parse_args()

    if args.smoke_test:
        return 0 if run_smoke_test() else 1

    if args.diff_base:
        args.diff_only = True

    if args.diff_only:
        base_ref = args.diff_base or "HEAD"
        css_text = get_diff_text(base_ref)
        source_label = f"git diff {base_ref} -- frontend/src/global.css"
    else:
        if not GLOBAL_CSS.exists():
            print(f"ERROR: {GLOBAL_CSS} not found", file=sys.stderr)
            return 1
        css_text = GLOBAL_CSS.read_text()
        source_label = str(GLOBAL_CSS.relative_to(REPO_ROOT))

    selectors = extract_ht_selectors(css_text)
    unknown = [s for s in selectors if not is_allowed(s)]

    if unknown:
        print(f"ERROR: Unknown selectors found in {source_label}:")
        for sel in sorted(unknown):
            print(f"  .{sel}")
        print()
        print("These selectors are not on the global.css allowlist.")
        print("Move component-specific styles to a co-located .module.css file,")
        print("or add the prefix to ALLOWLIST in tools/check_global_css_allowlist.py")
        print("if the class is genuinely shared (used across 3+ component files).")
        return 1

    print(f"OK: all .ht-* selectors in {source_label} are on the allowlist ({len(selectors)} checked).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
