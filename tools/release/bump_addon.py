#!/usr/bin/env python3
"""Bump the Home Assistant add-on in a `hassette-addon` checkout to a hassette release.

Called by release-please.yml's `bump-addon` job (design/specs/129-ha-addon-v01/design.md, D12). It edits the
checkout in place and reports what it did; the job owns the image check, the commit, and the push.

- A pre-release or dev tag is skipped: the add-on tracks stable hassette releases only.
- A version lower than the add-on's current one is refused, because `workflow_dispatch` accepts any tag and an
  old tag must not downgrade add-on users.
- An equal version is a successful no-op, so re-running a release whose bump already landed passes.
- Otherwise `version` in `hassette/config.yaml` is rewritten and a CHANGELOG entry linking the release notes is
  added above the newest one.

Usage:
    python3 ./tools/release/bump_addon.py --tag "$TAG_NAME" --addon-dir addon --release-repo "$GITHUB_REPOSITORY"

Writes to $GITHUB_OUTPUT (or stdout, for local runs): action (bump, noop, or skip), version, image (the add-on's
`image:` from config.yaml, which the job checks before committing), and current (the add-on's version before
the bump).

"Stable" here is a bare X.Y.Z, stricter than check_tag_version.py's packaging-based test, which also counts
post-releases as stable. The add-on only ever needs release-please's X.Y.Z tags, and staying stdlib-only lets
the job run this with the runner's python3, as drift_check.py does.
"""

import argparse
import os
import re
import sys
import uuid
from pathlib import Path

STABLE_VERSION = re.compile(r"^(\d+)\.(\d+)\.(\d+)$")
VERSION_LINE = re.compile(r'^version:[ \t]*"?([^"\s]+)"?[ \t]*$', re.MULTILINE)
IMAGE_LINE = re.compile(r'^image:[ \t]*"?([^"\s]+)"?[ \t]*$', re.MULTILINE)
CHANGELOG_HEADING = re.compile(r"^## ", re.MULTILINE)
BUMP = "bump"
NOOP = "noop"
SKIP = "skip"


class BumpError(Exception):
    """The bump can't proceed; the message says why."""


def parse_stable_version(text: str) -> tuple[int, int, int] | None:
    """Return the version as an int tuple when it's a plain X.Y.Z release, else None."""
    match = STABLE_VERSION.match(text)
    if match is None:
        return None
    major, minor, patch = (int(part) for part in match.groups())
    return major, minor, patch


def read_field(pattern: re.Pattern[str], config_text: str, field: str) -> str:
    matches = pattern.findall(config_text)
    if len(matches) != 1:
        raise BumpError(f"config.yaml must have exactly one top-level `{field}:` line, found {len(matches)}")
    return matches[0]


def bump_action(version: str, current: str) -> str:
    """Return SKIP, NOOP, or BUMP for releasing `version` over the add-on's `current` version."""
    new = parse_stable_version(version)
    if new is None:
        return SKIP
    old = parse_stable_version(current)
    if old is None:
        raise BumpError(f"the add-on's current version {current!r} isn't a plain X.Y.Z version")
    if new < old:
        raise BumpError(f"refusing to downgrade the add-on from {current} to {version}")
    return NOOP if new == old else BUMP


def set_version(config_text: str, version: str) -> str:
    return VERSION_LINE.sub(f'version: "{version}"', config_text, count=1)


def add_changelog_entry(changelog_text: str, version: str, release_url: str) -> str:
    """Insert the entry above the newest `## ` heading, or append it when there's none yet."""
    entry = f"## {version}\n\n- [hassette {version} release notes]({release_url})\n"
    match = CHANGELOG_HEADING.search(changelog_text)
    if match is None:
        return changelog_text.rstrip("\n") + "\n\n" + entry
    return changelog_text[: match.start()] + entry + "\n" + changelog_text[match.start() :]


def write_outputs(outputs: dict[str, str]) -> None:
    """Write outputs to $GITHUB_OUTPUT with a random heredoc delimiter, so a value can never end its own field
    early, or print `key=value` lines when it's unset, for local runs.
    """
    output_path = os.getenv("GITHUB_OUTPUT")
    if not output_path:
        for key, value in outputs.items():
            print(f"{key}={value}")
        return

    with open(output_path, "a", encoding="utf-8") as f:
        for key, value in outputs.items():
            delimiter = uuid.uuid4().hex
            f.write(f"{key}<<{delimiter}\n{value}\n{delimiter}\n")


def describe(action: str, version: str, current: str) -> str:
    if action == SKIP:
        return f"{version} is not a stable release; the add-on stays at {current}"
    if action == NOOP:
        return f"the add-on is already at {version}; nothing to commit"
    return f"bumped the add-on from {current} to {version}"


def run(tag: str, addon_dir: Path, release_repo: str) -> dict[str, str]:
    version = tag.removeprefix("v")
    config_path = addon_dir / "hassette" / "config.yaml"
    changelog_path = addon_dir / "hassette" / "CHANGELOG.md"

    config_text = config_path.read_text(encoding="utf-8")
    current = read_field(VERSION_LINE, config_text, "version")
    image = read_field(IMAGE_LINE, config_text, "image")

    action = bump_action(version, current)
    if action == BUMP:
        release_url = f"https://github.com/{release_repo}/releases/tag/{tag}"
        config_path.write_text(set_version(config_text, version), encoding="utf-8")
        changelog_text = changelog_path.read_text(encoding="utf-8")
        changelog_path.write_text(add_changelog_entry(changelog_text, version, release_url), encoding="utf-8")

    return {"action": action, "version": version, "image": image, "current": current}


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="Bump the hassette add-on to a hassette release.")
    parser.add_argument("--tag", required=True, help="Release tag, e.g. v0.58.0")
    parser.add_argument("--addon-dir", required=True, type=Path, help="Checkout of NodeJSmith/hassette-addon")
    parser.add_argument("--release-repo", required=True, help="owner/repo whose GitHub release notes the entry links")
    args = parser.parse_args(argv)

    try:
        outputs = run(args.tag, args.addon_dir, args.release_repo)
    except BumpError as exc:
        print(f"::error::{exc}", file=sys.stderr)
        return 1

    print(describe(outputs["action"], outputs["version"], outputs["current"]))
    write_outputs(outputs)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
