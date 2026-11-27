#!/usr/bin/env python3
"""Turn one ha-dev-canary.yml run into the state of its single tracking issue.

Reads the JUnit report of the `system_canary` nox session and keeps at most one open issue
labeled `ha-dev-canary`:

- failing run, no open issue: open one listing the failing test IDs, the HA version and the run.
- failing run, open issue, different failing set: rewrite the issue body to the new set and comment
  with what was added and removed, so watchers get notified.
- failing run, same failing set: leave the issue alone.
- green run: close the open issue, if any.

The issue body carries the failing set in a hidden HTML comment (`STATE_MARKER`), so the next run
compares against what the issue says, not against an earlier run's artifacts.

Two failures have no real test ID, so they get a synthetic one:

- `<startup>`: the HA container never started (a broken dev build or a failed pull). Every test
  that needs HA errors with the same fixture message, so they collapse into one ID instead of
  listing the whole suite.
- `<job-failed>`: the test step failed but the report names no failing test (collection crash,
  nox error, missing report).

Usage:
    python3 ./tools/release/ha_dev_canary.py --junit test-results/ha-dev-canary.xml \
        --outcome failure --ha-version 2026.12.0.dev202611270234 --image-tag dev --run-url URL
"""

import argparse
import json
import re
import subprocess
import sys
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path

from drift_check import ensure_label, find_existing_issue

LABEL = "ha-dev-canary"
LABEL_DESCRIPTION = "System suite fails against Home Assistant's dev image (at most one open issue)"
LABEL_COLOR = "d93f0b"
ISSUE_LABELS = (LABEL, "type:CICD", "area:testing", "size:medium")
# Start of every startup failure the ha_container fixture in tests/system/conftest.py raises. JUnit wraps
# it (`failed on setup with "Failed: ..."`), so it is matched as a substring. tools/ can't import the
# conftest, so the value is copied; test_ha_dev_canary.py checks the two copies agree.
HA_STARTUP_FAILURE = "HA container failed to start"
STARTUP_ID = "<startup>"
JOB_FAILED_ID = "<job-failed>"
STATE_MARKER = "ha-dev-canary-failing"
STATE_RE = re.compile(rf"<!-- {STATE_MARKER}: (.*?) -->")
GH_TIMEOUT_SECONDS = 30


@dataclass(frozen=True)
class RunContext:
    ha_version: str
    image_tag: str
    run_url: str


def failing_set(junit: Path, *, outcome: str) -> list[str]:
    """Return the sorted failing test IDs for this run, or [] for a green run.

    Args:
        junit: Path to the JUnit XML report. May be missing when pytest never ran.
        outcome: The test step's outcome (`success` or `failure`).

    Returns:
        Sorted `classname::name` IDs of failed or errored test cases, `[STARTUP_ID]` when HA never
        started, or `[JOB_FAILED_ID]` when the step failed without a failing test in the report.
    """
    ids: set[str] = set()
    startup = False
    if junit.exists():
        # The report is written by this job's own pytest run, not fetched from anywhere.
        root = ET.parse(junit).getroot()  # noqa: S314
        for case in root.iter("testcase"):
            problems = [*case.findall("failure"), *case.findall("error")]
            if not problems:
                continue
            ids.add(f"{case.get('classname', '')}::{case.get('name', '')}")
            if any(HA_STARTUP_FAILURE in (p.get("message", "") + (p.text or "")) for p in problems):
                startup = True
    # ha_container is session-scoped, so when HA never starts every test that needs it errors with
    # this message; listing them all would bury the one cause.
    if startup:
        return [STARTUP_ID]
    if not ids and outcome != "success":
        return [JOB_FAILED_ID]
    return sorted(ids)


def recorded_set(body: str) -> list[str] | None:
    """Return the failing set stored in an issue body, or None if the body has no marker."""
    match = STATE_RE.search(body)
    if match is None:
        return None
    return sorted(json.loads(match.group(1)))


def render_body(failing: list[str], ctx: RunContext) -> str:
    """Render the issue body for the current failing set."""
    lines = "\n".join(f"- `{test_id}`" for test_id in failing)
    return f"""<!-- {STATE_MARKER}: {json.dumps(failing)} -->
## System suite fails against Home Assistant `{ctx.image_tag}`

The daily canary (`.github/workflows/ha-dev-canary.yml`) runs the non-destructive system suite \
against `homeassistant/home-assistant:{ctx.image_tag}`. It is failing.

- **HA version:** `{ctx.ha_version}`
- **Run:** {ctx.run_url}

### Failing tests

{lines}

`{STARTUP_ID}` means the HA container never started; `{JOB_FAILED_ID}` means the run failed \
without a failing test in its report. Both point at the run log.

### What to do

Check whether the failure is a real wire change in HA (a payload or API shape hassette must follow) \
or unrelated breakage in the dev build. A wire change gets its own issue to adapt hassette before \
the next HA release; unrelated breakage can wait for the next dev build.

This body always shows the current failing set. A comment is added whenever the set changes, and \
the issue closes itself on the next green run.
"""


def gh(*args: str, body: str | None = None) -> str:
    """Run a `gh` command against the current repo, passing `body` on stdin if given."""
    result = subprocess.run(
        ["gh", *args],
        input=body,
        capture_output=True,
        text=True,
        check=False,
        timeout=GH_TIMEOUT_SECONDS,
    )
    if result.returncode != 0:
        print(f"::error::gh {' '.join(args[:2])} failed: {result.stderr}", file=sys.stderr)
        raise subprocess.CalledProcessError(result.returncode, result.args, result.stdout, result.stderr)
    return result.stdout


def change_comment(old: list[str], new: list[str], ctx: RunContext) -> str:
    """Describe how the failing set changed since the issue last recorded it."""
    added = [t for t in new if t not in old]
    removed = [t for t in old if t not in new]
    parts = [f"Failing set changed on HA `{ctx.ha_version}` ({ctx.run_url})."]
    if added:
        parts.append("Now failing:\n" + "\n".join(f"- `{t}`" for t in added))
    if removed:
        parts.append("No longer failing:\n" + "\n".join(f"- `{t}`" for t in removed))
    return "\n\n".join(parts)


def sync_issue(failing: list[str], ctx: RunContext) -> str:
    """Bring the tracking issue in line with `failing`; return a one-line summary of the action."""
    ensure_label(LABEL, LABEL_DESCRIPTION, LABEL_COLOR)
    existing = find_existing_issue(LABEL)

    if not failing:
        if not existing:
            return "green, no open issue"
        gh("issue", "close", existing, "--comment", f"Green again on HA `{ctx.ha_version}` ({ctx.run_url}).")
        return f"green, closed #{existing}"

    body = render_body(failing, ctx)
    if not existing:
        labels = [arg for label in ISSUE_LABELS for arg in ("--label", label)]
        title = f"System suite fails against Home Assistant {ctx.image_tag}"
        gh("issue", "create", "--title", title, *labels, "--body-file", "-", body=body)
        return "failing, opened a new issue"

    current_body = json.loads(gh("issue", "view", existing, "--json", "body"))["body"]
    # A body without the marker (edited by hand) counts as an empty set: rewrite it and comment.
    recorded = recorded_set(current_body)
    if recorded == failing:
        return f"failing, set unchanged on #{existing}"
    gh("issue", "edit", existing, "--body-file", "-", body=body)
    gh("issue", "comment", existing, "--body-file", "-", body=change_comment(recorded or [], failing, ctx))
    return f"failing, set changed on #{existing}"


def main(argv: list[str]) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--junit", type=Path, required=True, help="JUnit XML report of the canary run.")
    p.add_argument(
        "--outcome",
        required=True,
        choices=["success", "failure"],
        help="The test step's outcome (steps.<id>.outcome); the workflow skips this script otherwise.",
    )
    p.add_argument("--ha-version", required=True, help="HA version of the image, or 'unknown'.")
    p.add_argument("--image-tag", required=True, help="The HA image tag the run used.")
    p.add_argument("--run-url", required=True, help="Link to this workflow run.")
    args = p.parse_args(argv)

    failing = failing_set(args.junit, outcome=args.outcome)
    ctx = RunContext(ha_version=args.ha_version, image_tag=args.image_tag, run_url=args.run_url)
    print(f"Failing set: {failing or 'none'}")
    print(sync_issue(failing, ctx))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
