"""Read a pull request's labels live from GitHub, for CI gates that a label can turn into a pass.

Labels are fetched at run time with the GitHub CLI rather than taken from the workflow's event
payload: a job re-run reuses the original payload, so its label list is stale.
"""

import json
import os
import subprocess
import sys

GH_TIMEOUT_SECONDS = 30


class LabelLookupError(RuntimeError):
    """Raised when a PR's labels can't be read."""


def fetch_pr_labels(pr: str) -> list[str]:
    """Return the label names currently on ``pr`` via ``gh pr view``."""
    try:
        result = subprocess.run(
            ["gh", "pr", "view", pr, "--json", "labels"],
            capture_output=True,
            text=True,
            check=True,
            timeout=GH_TIMEOUT_SECONDS,
        )
    except FileNotFoundError as exc:
        raise LabelLookupError("the GitHub CLI ('gh') is not installed or not on PATH") from exc
    except subprocess.TimeoutExpired as exc:
        raise LabelLookupError(f"'gh pr view {pr}' timed out after {GH_TIMEOUT_SECONDS}s") from exc
    except subprocess.CalledProcessError as exc:
        raise LabelLookupError(f"'gh pr view {pr}' failed: {(exc.stderr or '').strip()}") from exc
    try:
        data = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise LabelLookupError(f"'gh pr view {pr}' did not produce valid JSON: {result.stdout[:200]!r}") from exc
    return [label["name"] for label in data.get("labels", [])]


def apply_label_override(exit_code: int, label: str, pr: str | None = None) -> int:
    """Return 0 instead of a failing ``exit_code`` when the PR carries ``label``.

    ``pr`` defaults to ``$PR_NUMBER``; with no PR number (e.g. a local run) the exit code is
    returned unchanged and no lookup happens. Labels are only fetched when the gate failed. A
    failed lookup keeps the failure.
    """
    if exit_code == 0:
        return exit_code
    pr = pr if pr is not None else os.environ.get("PR_NUMBER")
    if not pr:
        return exit_code
    try:
        labels = fetch_pr_labels(pr)
    except LabelLookupError as exc:
        print(f"ERROR: could not read labels for PR #{pr}: {exc}", file=sys.stderr)
        return exit_code
    if label not in labels:
        return exit_code
    print()
    print(f"ALLOWED: the regression above was allowed by the '{label}' label on PR #{pr}.")
    return 0
