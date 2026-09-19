#!/usr/bin/env python3
"""CI gate: fail if a PR made an already-oversized file bigger, or added a brand-new oversized one.

Complements house-lint's HSL102 check, which is informational in CI (`continue-on-error: true`,
tracks the full backlog of ~20 files already over the 800-line threshold). This script is the
"new code" counterpart -- see check_duplicate_code.py's --gate-new-code mode for the same idea
applied to copy-pasted code instead of file size. Only files this PR's own commits actually
touched are in scope; an untouched file that happens to still be over threshold is pre-existing
debt and never blocks here.

A touched, currently-over-threshold file fails this gate only if it is now bigger than it was at
the PR's merge-base (a brand-new file counts as growing from 0 -- "born oversized" still counts
as growing). Shrinking, or leaving an oversized file's size unchanged, always passes: this gate
ratchets in one direction only. It never requires fixing existing debt, just not adding to it.

Renames are resolved via git's own rename detection, so splitting or renaming a large file isn't
mistaken for creating a new one from nothing.

Usage:
    python tools/check_file_size_regressions.py <base-ref> <head-ref>

<base-ref>/<head-ref> are the PR's own base and head refs (e.g. a GitHub Actions pull_request
event's base.sha/head.sha) -- this script resolves their merge-base itself and diffs against
that, not against <base-ref> directly (see git_merge_base's docstring in lint_helpers.py for
why). Both refs must already be fetched in the current checkout -- see
.github/workflows/lint.yml for how CI does that before calling this.
"""

import json
import re
import subprocess
import sys
from pathlib import Path

from lint_helpers import REPO_ROOT, git_changed_line_ranges, git_file_line_count_at, git_merge_base, git_renamed_from

HSL102_MESSAGE_RE = re.compile(r"^(\d+) lines \(threshold: (\d+)\)$")


class HouseLintError(RuntimeError):
    """Raised when house-lint can't be run or its output can't be parsed -- must fail loudly."""


def current_oversized_files(repo_root: Path) -> dict[Path, int]:
    """Return ``{repo-relative path: current line count}`` for every live HSL102 finding."""
    try:
        result = subprocess.run(
            ["house-lint", "check", "--format", "json", "--select", "HSL102"],
            cwd=repo_root,
            capture_output=True,
            text=True,
        )
    except FileNotFoundError as exc:
        raise HouseLintError("house-lint is not on PATH -- run `uv sync` first") from exc

    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise HouseLintError(f"house-lint did not produce valid JSON: {result.stdout[:500]!r}") from exc

    # house-lint exits 0 (clean) or 1 (findings, no errors) for an ordinary scan; exit 3 (config/
    # scan errors) or 4 (internal error) means some file wasn't actually scanned, so `findings`
    # below is a partial result -- silently trusting it as complete would let genuinely oversized
    # files that failed to scan slip past this gate unflagged.
    if result.returncode not in (0, 1) or payload.get("errors"):
        raise HouseLintError(f"house-lint reported scan errors (exit {result.returncode}): {payload.get('errors')}")

    oversized: dict[Path, int] = {}
    for finding in payload.get("findings", []):
        if finding.get("rule_id") != "HSL102":
            continue
        message = finding.get("message", "")
        match = HSL102_MESSAGE_RE.match(message)
        if not match:
            raise HouseLintError(f"unrecognized HSL102 message format: {message!r}")
        oversized[Path(finding["path"])] = int(match.group(1))
    return oversized


def regressions(
    repo_root: Path, oversized: dict[Path, int], base_ref: str, head_ref: str
) -> list[tuple[Path, int, int]]:
    """Return ``(path, old_line_count, new_line_count)`` for every oversized file this PR grew.

    ``base_ref``/``head_ref`` are the PR's raw base and head refs (e.g. a GitHub Actions PR
    event's ``base.sha``/``head.sha``) — the merge-base between them, not ``base_ref`` itself,
    is resolved here and used as the actual comparison point. See ``git_merge_base``'s docstring
    for why the live base tip is the wrong reference.
    """
    merge_base = git_merge_base(repo_root, base_ref, head_ref)
    changed_files = git_changed_line_ranges(repo_root, merge_base, head_ref)
    renames = git_renamed_from(repo_root, merge_base, head_ref)

    found: list[tuple[Path, int, int]] = []
    for path, new_count in oversized.items():
        if path not in changed_files:
            continue
        old_path = renames.get(path, path)
        old_count = git_file_line_count_at(repo_root, merge_base, old_path)
        if new_count > old_count:
            found.append((path, old_count, new_count))
    return found


def main() -> int:
    if len(sys.argv) != 3:
        print("Usage: check_file_size_regressions.py <base-ref> <head-ref>", file=sys.stderr)
        return 2
    base_ref, head_ref = sys.argv[1], sys.argv[2]

    try:
        oversized = current_oversized_files(REPO_ROOT)
        found = regressions(REPO_ROOT, oversized, base_ref, head_ref)
    except HouseLintError as exc:
        print(f"ERROR: {exc}")
        return 1

    if found:
        print(f"ERROR: {len(found)} file(s) grew past the size threshold in this PR:")
        print()
        for path, old_count, new_count in sorted(found):
            print(f"    {path}: {old_count} -> {new_count} lines")
        print()
        print(
            "Each of these was already over house-lint's HSL102 threshold, and this PR made it\n"
            "bigger. Move the new lines into a new module, or shrink something else in the same\n"
            "file so the net change isn't positive. Pre-existing oversized files this PR didn't\n"
            "touch aren't blocked here -- see the informational 'file-sizes' job for the full\n"
            "backlog."
        )
        return 1

    print("OK: no file grew past the size threshold in this PR.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
