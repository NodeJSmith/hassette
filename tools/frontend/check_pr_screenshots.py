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

Path (a) rejects any ``raw.githubusercontent.com/<owner>/<repo>/<ref>/`` link, whatever
the file, whose ref is not a full commit SHA: merging deletes the PR branch, so a
branch-scoped link 404s afterward. Matching the prefix only means the check never has
to find where a URL ends. Paths (b) and (c) don't depend on body links.

The rejection catches accidental branch links, from the autofix PR-body generator or a pasted
URL, in the forms that actually occur: ``https://`` links, protocol-relative links, and explicit
ports, in Markdown or ``<img>``. It is not a defense against deliberate evasion, so rarer URL
syntax (userinfo, percent-encoded hosts, redirects, and the like) is out of scope. Don't grow
the pattern for it.

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
# A raw URL's prefix through its ref segment (group 1). A SHA never contains a slash, so ``autofix/x`` and
# ``refs/heads/main`` fail the SHA check on their first segment. Browsers resolve a protocol-relative
# ``//raw.githubusercontent.com/...`` link to the same URL, so that form counts too, but only where the ``//`` starts a
# URL (start of text, or after whitespace, a quote, ``(``, ``<`` or ``=``), not inside another URL's path. An explicit
# port such as ``:443`` names the same host.
RAW_URL_PREFIX_RE = re.compile(
    r"""(?:https?://|(?<![^\s"'(<=])//)raw\.githubusercontent\.com(?::\d+)?/[\w.-]+/[\w.-]+/([^/\s]+)/""",
    re.IGNORECASE,
)
COMMIT_SHA_RE = re.compile(r"[0-9a-f]{40}", re.IGNORECASE)
NO_VISUAL_CHANGE_LABEL = "no-visual-change"


def is_rendering_file(path: str) -> bool:
    """Return True if a changed path is a rendered frontend file (not a test or stub)."""
    if not RENDERING_RE.match(path):
        return False
    return not (path.endswith(".test.tsx") or path.endswith(".d.ts"))


def branch_scoped_raw_prefixes(body: str) -> list[str]:
    """Return distinct raw URL prefixes (through the ref segment) in the body whose ref is not a commit SHA."""
    prefixes = (m.group(0) for m in RAW_URL_PREFIX_RE.finditer(body) if not COMMIT_SHA_RE.fullmatch(m.group(1)))
    return list(dict.fromkeys(prefixes))


def has_visual_evidence(body: str, changed_files: list[str], labels: list[str]) -> bool:
    """Return True if the PR satisfies any of the three visual-evidence paths.

    Path (a) fails outright when the body links any branch-scoped raw URL, even if it also has a
    Screenshots heading or a SHA-pinned image.
    """
    if NO_VISUAL_CHANGE_LABEL in labels:
        return True
    if any(DOCS_IMAGE_RE.match(f) for f in changed_files):
        return True
    if branch_scoped_raw_prefixes(body):
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

    unpinned = branch_scoped_raw_prefixes(body)
    if unpinned:
        print(
            "ERROR: the PR description links raw files by branch, which 404s once the branch is deleted on merge:",
            file=sys.stderr,
        )
        for prefix in unpinned:
            print(f"  {prefix}...", file=sys.stderr)
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
    print("      (pin raw.githubusercontent.com links to a commit SHA, not the branch),", file=sys.stderr)
    print("  (b) include an updated screenshot under docs/ (a *.png) in the diff, or", file=sys.stderr)
    print(f"  (c) add the '{NO_VISUAL_CHANGE_LABEL}' label if the change is genuinely not visible.", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
