#!/usr/bin/env python3
"""Scan recent CI runs for recurring test failures (flaky tests).

Usage:
    uv run python scripts/ci_flake_scan.py
    uv run python scripts/ci_flake_scan.py --days 14
    uv run python scripts/ci_flake_scan.py --workflow Tests --workflow "E2E Tests"

Pulls failed GitHub Actions runs for the given workflow(s) over the lookback
window, downloads each failed job's log, and extracts pytest FAILED lines.
Failures are grouped by test id; anything appearing 2+ times across
independent runs is flagged as recurring and worth a look. Already-tracked
flakes are read from scripts/known_flakes.yaml so they're reported as known
instead of resurfacing every scan.

Job failures with no pytest FAILED line in their log (network hiccups,
artifact-permission errors, and other GitHub Actions infra noise) are
reported separately, not mixed into the test-failure table.

Requires the `gh` CLI, authenticated for this repo.
"""

import json
import re
import subprocess
import sys
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any, NamedTuple

import cyclopts
import yaml
from whenever import Instant

app = cyclopts.App(help=__doc__)

REPO_ROOT = Path(__file__).resolve().parent.parent
KNOWN_FLAKES_PATH = REPO_ROOT / "scripts" / "known_flakes.yaml"

# Documented, continue-on-error baseline failures on main (see CLAUDE.md,
# "Known-failing lint checks") -- not test flakiness, skip entirely.
SKIP_JOB_NAMES = frozenset({"file-sizes", "duplicate-code"})

# Matches pytest's short test summary lines, e.g.:
#   FAILED tests/unit/test_foo.py::test_bar - AssertionError: boom
#   ERROR tests/unit/test_foo.py::test_bar - fixture 'db' not found
# ERROR lines come from collection/fixture/teardown failures, not assertion
# failures -- still a test-level signal, not infra noise, so they're matched
# alongside FAILED rather than falling through to GH_ERROR_RE below.
# `gh run view --log-failed` prefixes every line with "<job>\t<step>\t<timestamp> ",
# so this intentionally does not anchor to the start of the line.
#
# Deliberately only applied to the "short test summary info" section (see
# PYTEST_SUMMARY_BANNER below) rather than the whole log -- an unscoped
# search for "ERROR <token> - <message>" would also match ordinary
# "LEVEL name - message"-shaped log output from application or third-party
# code captured in the same job log, misclassifying it as a test failure.
# Pytest's summary section is the one place this shape is guaranteed to mean
# an actual test outcome.
PYTEST_FAILURE_RE = re.compile(r"(?:FAILED|ERROR) (\S+) - (.+)$", re.MULTILINE)

# Marks the start of pytest's summary section; everything after it is exactly
# one line per failed/errored test, nothing else.
PYTEST_SUMMARY_BANNER = "short test summary info"

# Matches a GitHub Actions error annotation, e.g.:
#   ##[error]The operation was aborted due to timeout
# Used as the fallback summary for a failed job whose log has no pytest FAILED
# line -- infra noise (network hiccups, artifact errors) rather than a test failure.
GH_ERROR_RE = re.compile(r"##\[error\](.+)$", re.MULTILINE)

RECURRING_THRESHOLD = 2

# `gh` can hang on a slow API response; fail loudly rather than let one bad
# call stall the whole scan.
GH_TIMEOUT_SECONDS = 30

# Comfortably above this repo's actual weekly failed-run volume (tens, not
# hundreds) -- see `gh run list --help` for the underlying API page cap.
GH_RUN_LIST_LIMIT = 500

# Truncation lengths for the "latest error" line in the report. Test failures
# carry pytest's assertion detail (more useful, worth more room); infra
# failures are usually a single short GitHub Actions annotation.
TEST_ERROR_TRUNCATE_LEN = 160
INFRA_ERROR_TRUNCATE_LEN = 120


@dataclass
class Occurrence:
    run_id: str
    branch: str
    created_at: str
    error: str


class KnownFlake(NamedTuple):
    pattern: re.Pattern[str]
    issue: int
    note: str


def gh_json(*args: str) -> Any | None:
    """Run a `gh` CLI command and parse its JSON output.

    Returns None if `gh` exits non-zero (auth hiccup, rate limit, transient
    network error) instead of raising -- mirrors job_log()'s handling so one
    bad call doesn't crash the whole scan and discard every run's signal
    already gathered. A hung call still raises subprocess.TimeoutExpired
    (see GH_TIMEOUT_SECONDS) -- that failure mode is deliberately not caught.
    """
    try:
        result = subprocess.run(["gh", *args], capture_output=True, text=True, check=True, timeout=GH_TIMEOUT_SECONDS)
    except subprocess.CalledProcessError as exc:
        print(f"warning: gh {' '.join(args)} failed: {exc.stderr.strip()}", file=sys.stderr)
        return None
    return json.loads(result.stdout)


def load_known_flakes() -> list[KnownFlake]:
    if not KNOWN_FLAKES_PATH.exists():
        return []
    data = yaml.safe_load(KNOWN_FLAKES_PATH.read_text()) or {}
    return [
        KnownFlake(re.compile(entry["pattern"]), entry["issue"], entry.get("note", "").strip())
        for entry in data.get("flakes", [])
    ]


def list_failed_runs(workflow: str, since_date: str) -> list[dict]:
    runs = gh_json(
        "run",
        "list",
        "--workflow",
        workflow,
        "--status",
        "failure",
        "--created",
        f">={since_date}",
        "--limit",
        str(GH_RUN_LIST_LIMIT),
        "--json",
        "databaseId,headBranch,createdAt",
    )
    if runs is None:
        print(f"warning: could not list failed runs for workflow {workflow!r}, skipping it", file=sys.stderr)
        return []
    if len(runs) == GH_RUN_LIST_LIMIT:
        print(
            f"warning: hit the {GH_RUN_LIST_LIMIT}-run cap for workflow {workflow!r} -- "
            "results for this lookback window may be truncated",
            file=sys.stderr,
        )
    return runs


def failed_jobs(run_id: str) -> list[dict]:
    data = gh_json("run", "view", run_id, "--json", "jobs")
    if data is None:
        print(f"warning: could not fetch jobs for run {run_id}, skipping it", file=sys.stderr)
        return []
    jobs = data["jobs"]
    return [j for j in jobs if j["conclusion"] == "failure" and j["name"] not in SKIP_JOB_NAMES]


def job_log(job_id: str) -> str | None:
    """Return a failed job's log text, or None if the `gh` call itself failed.

    Kept distinct from "log fetched but had no FAILED/##[error] line" -- a
    failed `gh` call (auth hiccup, expired log retention, rate limit) must not
    be silently treated as "this job's failure has no signal."
    """
    result = subprocess.run(
        ["gh", "run", "view", "--job", job_id, "--log-failed"],
        capture_output=True,
        text=True,
        timeout=GH_TIMEOUT_SECONDS,
    )
    if result.returncode != 0:
        return None
    return result.stdout


def scan_run(run: dict) -> tuple[dict[str, list[Occurrence]], dict[str, list[Occurrence]]]:
    """Scan one run's failed jobs and return (test_failures, infra_failures) for it.

    Returns fresh dicts rather than mutating caller-owned state -- the caller
    merges them into its running totals.
    """
    test_failures: dict[str, list[Occurrence]] = defaultdict(list)
    infra_failures: dict[str, list[Occurrence]] = defaultdict(list)

    run_id = str(run["databaseId"])
    for job in failed_jobs(run_id):
        occurrence_base = {"run_id": run_id, "branch": run["headBranch"], "created_at": run["createdAt"]}

        log = job_log(str(job["databaseId"]))
        if log is None:
            infra_failures[job["name"]].append(
                Occurrence(error="(gh CLI call failed fetching this job's log)", **occurrence_base)
            )
            continue

        summary_start = log.find(PYTEST_SUMMARY_BANNER)
        pytest_summary = log[summary_start:] if summary_start != -1 else ""
        test_matches = PYTEST_FAILURE_RE.findall(pytest_summary)
        if test_matches:
            for test_id, error in test_matches:
                test_failures[test_id].append(Occurrence(error=error.strip(), **occurrence_base))
            continue

        error_matches = GH_ERROR_RE.findall(log)
        summary = error_matches[0].strip() if error_matches else "(no FAILED line or ##[error] found in log)"
        infra_failures[job["name"]].append(Occurrence(error=summary, **occurrence_base))

    return test_failures, infra_failures


def classify_verdict(
    test_id: str, occurrences: list[Occurrence], known: list[KnownFlake]
) -> tuple[str, KnownFlake | None]:
    """Decide whether a test's failures look known, suite-wide flaky, or one PR's own bug.

    Every `push`-triggered run on `main` is a separate, already-merged commit --
    unlike a feature branch, "main" is never "one PR's diff." So a test recurring
    on main (even under one branch name), or recurring across 2+ different
    non-main branches, is the real flakiness signature: independent commits
    hitting the same nondeterminism. A test recurring only within one feature
    branch is more likely that branch's own unfixed bug, not a suite-wide flake.
    """
    match = next((k for k in known if k.pattern.search(test_id)), None)
    if match:
        return f"known (#{match.issue})", match

    # A single run fans a test out across multiple job-level occurrences (one
    # per Python version in the test matrix) while still being one commit's
    # worth of signal -- count distinct runs, not raw occurrences, so matrix
    # fanout within one run doesn't look like recurrence across commits.
    distinct_runs = {o.run_id for o in occurrences}
    if len(distinct_runs) < RECURRING_THRESHOLD:
        return "single run", None

    branches = {o.branch for o in occurrences}
    non_main_branches = branches - {"main"}
    if "main" in branches or len(non_main_branches) >= 2:
        return "NEW -- recurring across independent commits, consider filing", None
    return "recurring on one branch -- likely a real bug in that PR, not a suite flake", None


def render_report(
    days: int,
    workflows: list[str],
    test_failures: dict[str, list[Occurrence]],
    infra_failures: dict[str, list[Occurrence]],
    known: list[KnownFlake],
) -> None:
    print(f"CI flake scan -- last {days} day(s), workflows: {', '.join(workflows)}\n")

    if not test_failures:
        print("No pytest failures found.")
    else:
        for test_id, occurrences in sorted(test_failures.items(), key=lambda kv: -len(kv[1])):
            verdict, match = classify_verdict(test_id, occurrences, known)
            branches = sorted({o.branch for o in occurrences})
            print(f"{test_id}")
            print(f"  {len(occurrences)}x -- {verdict}")
            print(f"  branches: {', '.join(branches)}")
            print(f"  latest error: {occurrences[-1].error[:TEST_ERROR_TRUNCATE_LEN]}")
            if match and match.note:
                print(f"  note: {match.note}")
            print()

    if infra_failures:
        print("Non-test (infra) job failures -- not test flakiness, shown for awareness:")
        for job_name, occurrences in sorted(infra_failures.items(), key=lambda kv: -len(kv[1])):
            print(f"  {job_name}: {len(occurrences)}x -- {occurrences[-1].error[:INFRA_ERROR_TRUNCATE_LEN]}")


@app.default
def main(*, days: int = 7, workflow: list[str] | None = None) -> None:
    """Scan recent CI runs for recurring test failures.

    Args:
        days: Lookback window in days.
        workflow: Workflow name(s) to scan. Repeat the flag for multiple.
            Defaults to "Tests" and "E2E Tests".
    """
    workflows = workflow if workflow else ["Tests", "E2E Tests"]
    lookback_start = Instant.now().subtract(hours=24 * days)
    since_date = lookback_start.to_stdlib().date().isoformat()
    known = load_known_flakes()

    test_failures: dict[str, list[Occurrence]] = defaultdict(list)
    infra_failures: dict[str, list[Occurrence]] = defaultdict(list)

    for wf in workflows:
        for run in list_failed_runs(wf, since_date):
            run_test_failures, run_infra_failures = scan_run(run)
            for test_id, occurrences in run_test_failures.items():
                test_failures[test_id].extend(occurrences)
            for job_name, occurrences in run_infra_failures.items():
                infra_failures[job_name].extend(occurrences)

    render_report(days, workflows, test_failures, infra_failures, known)


if __name__ == "__main__":
    app()
