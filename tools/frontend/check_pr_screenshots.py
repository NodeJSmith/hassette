#!/usr/bin/env python3
"""CI guard: require visual evidence on PRs that change rendering files.

A PR that touches rendered frontend files (``frontend/src/**/*.tsx`` or ``*.css``)
ships visible change, but nothing stops it merging with no screenshots. Text rules
covering this load only when a UI trigger fires, which is easy to miss. This guard
makes the requirement structural.

The check triggers when the PR changes a rendering file, excluding tests
(``*.test.tsx``) and generated type stubs (``*.d.ts``). When triggered, it passes
if ANY of:

    (a) the PR body has a Screenshots heading or an embedded image, and links no
        branch-scoped ``raw.githubusercontent.com`` URL (see below),
    (b) the PR diff adds or changes a screenshot under ``docs/`` (``*.png``),
    (c) the PR carries the ``no-visual-change`` label.

Path (a) rejects ``raw.githubusercontent.com/<owner>/<repo>/<ref>/...`` image links whose
ref is anything but a full commit SHA: merging deletes the PR branch, so a
branch-scoped link 404s afterward even though the image itself lands on ``main``.
Paths (b) and (c) don't depend on body links and are unaffected.

It runs only on ``pull_request`` events — it needs PR metadata — and no-ops
elsewhere. ``evaluate`` is the pure decision core; ``fetch_pr_metadata`` reads metadata via
the GitHub CLI so the logic can be tested with synthetic inputs.

Usage:
    python tools/frontend/check_pr_screenshots.py --pr 1234
"""

import argparse
import json
import os
import re
import subprocess
import sys

RENDERING_RE = re.compile(r"^frontend/src/.*\.(tsx|css)$")
DOCS_IMAGE_RE = re.compile(r"^docs/.*\.png$")
SCREENSHOT_HEADING_RE = re.compile(r"(?im)^#{1,6}\s*screenshots?\b")
EMBEDDED_IMAGE_RE = re.compile(r"!\[[^\]]*\]\([^)]+\)|<img\b", re.IGNORECASE)
# A raw.githubusercontent.com image URL whose ref segment is not a full 40-char commit SHA.
# The extension ends the match unless a path character continues it, so trailing prose
# punctuation (``x.png.``, ``x.png,``) still counts as a boundary.
BRANCH_SCOPED_RAW_URL_RE = re.compile(
    r"https?://raw\.githubusercontent\.com/[^/\s]+/[^/\s]+/(?![0-9a-f]{40}/)[^\s)\"'<>]+"
    r"\.(?:png|jpe?g|gif|webp|svg)(?![\w/%-])",
    re.IGNORECASE,
)
NO_VISUAL_CHANGE_LABEL = "no-visual-change"


def is_rendering_file(path: str) -> bool:
    """Return True if a changed path is a rendered frontend file (not a test or stub)."""
    if not RENDERING_RE.match(path):
        return False
    return not (path.endswith(".test.tsx") or path.endswith(".d.ts"))


def branch_scoped_raw_urls(body: str) -> list[str]:
    """Return raw.githubusercontent.com image URLs in the body that are not pinned to a commit SHA."""
    return BRANCH_SCOPED_RAW_URL_RE.findall(body)


def has_visual_evidence(body: str, changed_files: list[str], labels: list[str]) -> bool:
    """Return True if the PR satisfies any of the three visual-evidence paths."""
    if NO_VISUAL_CHANGE_LABEL in labels:
        return True
    if any(DOCS_IMAGE_RE.match(f) for f in changed_files):
        return True
    if branch_scoped_raw_urls(body):
        return False
    return bool(SCREENSHOT_HEADING_RE.search(body) or EMBEDDED_IMAGE_RE.search(body))


def evaluate(changed_files: list[str], body: str, labels: list[str]) -> tuple[bool, bool]:
    """Return (triggered, satisfied) for a PR's changed files, body, and labels."""
    triggered = any(is_rendering_file(f) for f in changed_files)
    return triggered, has_visual_evidence(body, changed_files, labels)


def fetch_pr_metadata(pr: str) -> tuple[list[str], str, list[str], str]:
    """Read changed files, body, label names, and head commit SHA for a PR via the GitHub CLI."""
    try:
        result = subprocess.run(
            ["gh", "pr", "view", pr, "--json", "files,body,labels,headRefOid"],
            capture_output=True,
            text=True,
            check=True,
            timeout=30,
        )
    except FileNotFoundError:
        print("ERROR: the GitHub CLI ('gh') is not installed or not on PATH.", file=sys.stderr)
        sys.exit(1)
    except subprocess.TimeoutExpired:
        print("ERROR: 'gh pr view' timed out after 30s.", file=sys.stderr)
        sys.exit(1)
    except subprocess.CalledProcessError as exc:
        stderr = (exc.stderr or "").strip()
        detail = f": {stderr}" if stderr else ""
        print(f"ERROR: 'gh pr view {pr}' failed{detail}", file=sys.stderr)
        sys.exit(1)
    data = json.loads(result.stdout)
    files = [f["path"] for f in data.get("files", [])]
    body = data.get("body") or ""
    labels = [label["name"] for label in data.get("labels", [])]
    head_sha = data.get("headRefOid") or ""
    return files, body, labels, head_sha


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pr", default=os.environ.get("PR_NUMBER"), help="PR number (defaults to $PR_NUMBER)")
    args = parser.parse_args()

    if not args.pr:
        print("Not a pull_request context (no --pr / $PR_NUMBER) — skipping.")
        return 0

    changed_files, body, labels, head_sha = fetch_pr_metadata(args.pr)
    triggered, satisfied = evaluate(changed_files, body, labels)

    if not triggered:
        print("OK: PR changes no rendering files — screenshot check not required.")
        return 0
    if satisfied:
        print("OK: rendering changes accompanied by visual evidence.")
        return 0

    unpinned = branch_scoped_raw_urls(body)
    if unpinned:
        print(
            "ERROR: the PR description links screenshots by branch, which 404s once the branch is deleted on merge:",
            file=sys.stderr,
        )
        for url in unpinned:
            print(f"  {url}", file=sys.stderr)
        sha = head_sha or "<commit-sha>"
        print("Pin each link to a full commit SHA instead of the branch name:", file=sys.stderr)
        print(f"  https://raw.githubusercontent.com/<owner>/<repo>/{sha}/<path>", file=sys.stderr)
        print(
            f"Alternatively, commit the screenshot under docs/ (a *.png) or add the '{NO_VISUAL_CHANGE_LABEL}' label.",
            file=sys.stderr,
        )
        return 1

    print("ERROR: this PR changes rendered frontend files but provides no visual evidence.", file=sys.stderr)
    print("Satisfy ONE of the following:", file=sys.stderr)
    print("  (a) add a Screenshots section or an embedded image to the PR description", file=sys.stderr)
    print("      (pin raw.githubusercontent.com image links to a commit SHA, not the branch),", file=sys.stderr)
    print("  (b) include an updated screenshot under docs/ (a *.png) in the diff, or", file=sys.stderr)
    print(f"  (c) add the '{NO_VISUAL_CHANGE_LABEL}' label if the change is genuinely not visible.", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
