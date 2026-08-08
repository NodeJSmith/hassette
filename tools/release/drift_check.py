#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# ///
r"""Shared compare/dedup logic for pypi-drift-check.yml, docker-drift-check.yml, and
ha-version-drift.yml.

Each of those workflows fetches its own "current" and "latest" values before calling this
script — the sources of truth differ too much to share (this repo's GitHub release, a PyPI/GHCR
query, another repo's release) and so does fetch-failure handling (some treat a failed query as
a soft warning, some let it fail the job). This script owns only the part that's genuinely
identical across all three: comparing the two values, making sure the dedup label exists, and
looking up an already-open tracking issue by that label. Filing, commenting on, or closing the
tracking issue itself stays in each workflow, since title/body/labels differ per check.

Usage:
    uv run ./tools/release/drift_check.py --current "$CURRENT" --latest "$LATEST" \
        --label "pypi-drift" --label-description "..." [--label-color HEXCOLOR]

Writes to $GITHUB_OUTPUT (or stdout, for local runs): current, latest, drift (true/false), and
existing-issue (the number of an already-open issue with `label`, or empty). existing-issue is
always computed, drift or not, so a workflow that wants to auto-close a stale tracking issue on
resync (see ha-version-drift.yml) doesn't need its own separate lookup.
"""

import argparse
import contextlib
import os
import subprocess
import sys
import uuid

DEFAULT_LABEL_COLOR = "d93f0b"


def ensure_label(label: str, description: str, color: str) -> None:
    """Create the dedup label if it doesn't already exist yet.

    Best-effort: a failure here (e.g. the label already exists) is ignored, since
    `gh issue create --label` will raise its own clear error if the label is somehow still
    missing. Bounded by a timeout so a hung `gh` call can't stall the job past its own
    best-effort intent.

    Args:
        label: The label name to create.
        description: The label's description, shown in the GitHub UI.
        color: The label's hex color, without a leading `#`.
    """
    with contextlib.suppress(subprocess.TimeoutExpired):
        subprocess.run(
            ["gh", "label", "create", label, "--description", description, "--color", color],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
            timeout=30,
        )


def find_existing_issue(label: str) -> str:
    """Return the number of an open issue carrying `label`, or "" if none exists.

    Unlike `ensure_label`, a failed lookup here is not best-effort: it raises. Swallowing a
    failed `gh issue list` (auth, rate limit, network) would return "" indistinguishably from
    "no existing issue," letting the caller file a duplicate tracking issue instead of
    surfacing the real failure.

    Args:
        label: The label to search open issues for.

    Returns:
        The issue number as a string, or "" if no open issue carries the label.
    """
    try:
        result = subprocess.run(
            ["gh", "issue", "list", "--label", label, "--state", "open", "--json", "number", "-q", ".[0].number"],
            capture_output=True,
            text=True,
            check=True,
            timeout=30,
        )
    except subprocess.CalledProcessError as exc:
        # check=True gives an uncaught traceback that shows only the command and exit code —
        # print gh's own stderr first so the operator sees *why* the lookup failed (auth,
        # rate limit, bad label) instead of having to reproduce it locally.
        print(f"::error::gh issue list failed: {exc.stderr}", file=sys.stderr)
        raise
    return result.stdout.strip()


def write_github_output(**fields: str) -> None:
    """Write step outputs, one per field.

    Values come from external registries (PyPI, GHCR, GitHub releases) — untrusted enough that a
    plain `key=value` line could be spoofed by an embedded newline. Use GITHUB_OUTPUT's heredoc
    form with a random delimiter instead, so a value can never terminate its own field early.

    Args:
        **fields: Output name/value pairs to write. Falls back to printing `key=value` lines to
            stdout when `$GITHUB_OUTPUT` is unset, for local runs.
    """
    output_path = os.getenv("GITHUB_OUTPUT")
    if not output_path:
        for key, value in fields.items():
            print(f"{key}={value}")
        return

    with open(output_path, "a", encoding="utf-8") as f:
        for key, value in fields.items():
            delimiter = uuid.uuid4().hex
            f.write(f"{key}<<{delimiter}\n{value}\n{delimiter}\n")


def main(argv: list[str]) -> int:
    """Compare `--current` against `--latest` and report drift plus any existing tracking issue.

    Args:
        argv: Command-line arguments, excluding the program name.

    Returns:
        Exit code — always 0; a genuine failure (e.g. the issue lookup failing) raises instead
        of returning a nonzero code.
    """
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--current", required=True, help="The resolved current/local value.")
    p.add_argument("--latest", required=True, help="The resolved latest/external value to compare against.")
    p.add_argument(
        "--label", required=True, help="Dedup label — an open issue with this label is treated as 'already tracked'."
    )
    p.add_argument("--label-description", required=True, help="Used when creating the label, if it's missing.")
    p.add_argument("--label-color", default=DEFAULT_LABEL_COLOR, help="Used when creating the label, if it's missing.")
    args = p.parse_args(argv)

    drift = args.current != args.latest
    print(f"Current: {args.current}")
    print(f"Latest:  {args.latest}")
    if drift:
        print(f"::error::Drift detected! current={args.current} latest={args.latest}")
    else:
        print("Versions match — no drift detected")

    ensure_label(args.label, args.label_description, args.label_color)
    existing_issue = find_existing_issue(args.label)

    write_github_output(
        current=args.current,
        latest=args.latest,
        drift="true" if drift else "false",
        **{"existing-issue": existing_issue},
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
