#!/usr/bin/env python3
"""Find external contributors between two git tags.

Usage:
    uv run python scripts/release_contributors.py v0.50.0 v0.51.0
    uv run python scripts/release_contributors.py v0.50.0 HEAD
    uv run python scripts/release_contributors.py              # auto: second-latest tag..latest tag

Scans git log for authors who are not the repo owner or bots, and prints
each contributor with their associated PRs.
"""

import argparse
import re
import subprocess
import sys

OWNER_EMAILS = frozenset(
    {
        "8505845+NodeJSmith@users.noreply.github.com",
    }
)

OWNER_NAMES = frozenset(
    {
        "Jessica Smith",
    }
)

BOT_PATTERNS = re.compile(r"\[bot\]|dependabot|renovate", re.IGNORECASE)


def git(*args: str) -> str:
    result = subprocess.run(
        ["git", *args],
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout.strip()


def get_latest_tags(count: int = 2) -> list[str]:
    output = git("tag", "--sort=-v:refname", "--list", "v*")
    return output.splitlines()[:count]


def get_commits(from_ref: str, to_ref: str) -> list[dict[str, str]]:
    sep = "§§"
    log_format = f"%an{sep}%ae{sep}%s"
    output = git("log", f"--format={log_format}", f"{from_ref}..{to_ref}")
    if not output:
        return []

    commits = []
    for line in output.splitlines():
        parts = line.split(sep, 2)
        if len(parts) != 3:
            continue
        commits.append({"name": parts[0], "email": parts[1], "subject": parts[2]})
    return commits


def is_external(name: str, email: str) -> bool:
    if name in OWNER_NAMES or email in OWNER_EMAILS:
        return False
    if BOT_PATTERNS.search(name) or BOT_PATTERNS.search(email):
        return False
    return True


def parse_github_username(email: str) -> str | None:
    m = re.match(r"(?:\d+\+)?(.+)@users\.noreply\.github\.com", email)
    return m.group(1) if m else None


def find_external_contributors(from_ref: str, to_ref: str) -> dict[str, list[dict[str, str]]]:
    commits = get_commits(from_ref, to_ref)
    contributors: dict[str, list[dict[str, str]]] = {}

    for commit in commits:
        if not is_external(commit["name"], commit["email"]):
            continue

        name = commit["name"]
        entry = {"subject": commit["subject"], "email": commit["email"]}

        if name not in contributors:
            contributors[name] = []
        contributors[name].append(entry)

    return contributors


def print_contributors(
    contributors: dict[str, list[dict[str, str]]],
    from_ref: str,
    to_ref: str,
) -> None:
    if not contributors:
        print(f"No external contributors found in {from_ref}..{to_ref}")
        return

    print(f"External contributors in {from_ref}..{to_ref}:\n")
    for name, entries in sorted(contributors.items()):
        username = None
        for entry in entries:
            username = parse_github_username(entry["email"])
            if username:
                break

        display = f"@{username}" if username else name
        print(f"  {display}")
        for entry in entries:
            print(f"    - {entry['subject']}")
        print()


def main() -> int:
    parser = argparse.ArgumentParser(description="Find external contributors between git tags.")
    parser.add_argument("from_ref", nargs="?", help="Start ref (default: second-latest tag)")
    parser.add_argument("to_ref", nargs="?", default="HEAD", help="End ref (default: HEAD)")
    args = parser.parse_args()

    if args.from_ref is None:
        tags = get_latest_tags(2)
        if len(tags) < 1:
            print("No tags found. Provide explicit refs.", file=sys.stderr)
            return 1
        if len(tags) < 2:
            args.from_ref = tags[0]
            print(f"Only one tag found, scanning {args.from_ref}..HEAD\n")
        else:
            args.from_ref = tags[1]
            args.to_ref = tags[0]
            print(f"Auto-detected range: {args.from_ref}..{args.to_ref}\n")

    contributors = find_external_contributors(args.from_ref, args.to_ref)
    print_contributors(contributors, args.from_ref, args.to_ref)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
