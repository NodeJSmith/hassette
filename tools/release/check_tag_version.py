#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = [
#     "packaging>=25.0",
# ]
# ///

import argparse
import os
import subprocess
import sys
from dataclasses import dataclass

from packaging.version import InvalidVersion, Version


@dataclass(frozen=True)
class Classification:
    version: Version
    is_stable_release: bool

    @property
    def is_stable_str(self) -> str:
        return "true" if self.is_stable_release else "false"


def _run(cmd: list[str]) -> str | None:
    try:
        out = subprocess.check_output(cmd, stderr=subprocess.DEVNULL, text=True).strip()
    except Exception:
        return None
    return out or None


def resolve_ref_name(cli_ref: str | None) -> str:
    if cli_ref:
        return cli_ref

    gh_ref = os.getenv("GITHUB_REF_NAME")
    if gh_ref:
        return gh_ref

    # Local convenience: if HEAD is exactly at a tag, use that tag.
    tag = _run(["git", "describe", "--tags", "--exact-match"])
    if tag:
        return tag

    raise SystemExit(
        "Could not determine ref name.\n"
        "Provide one of:\n"
        "  - --ref-name vX.Y.Z[...]\n"
        "  - set GITHUB_REF_NAME\n"
        "  - run from a git checkout where HEAD is exactly at a tag\n"
    )


def list_version_tags() -> list[str]:
    """Return every `v*` tag in the checkout; needs full history fetched (`fetch-depth: 0`) in CI."""
    out = subprocess.check_output(["git", "tag", "--list", "v*"], text=True)
    return out.split()


def is_stable(ver: Version) -> bool:
    return not (ver.is_prerelease or ver.is_devrelease)


def highest_stable_version(tags: list[str]) -> Version | None:
    """Highest stable version among `tags`, skipping tags that aren't valid versions."""
    versions = []
    for tag in tags:
        try:
            versions.append(Version(tag.removeprefix("v")))
        except InvalidVersion:
            continue
    stable = [v for v in versions if is_stable(v)]
    return max(stable, default=None)


def classify(ref_name: str, existing_tags: list[str]) -> Classification:
    """Classify `ref_name`; a stable tag counts as a stable release only if no higher stable tag exists.

    `IS_STABLE_RELEASE` gates the Docker `latest` tag, so a late patch for an older line
    (e.g. v0.55.2 after v0.56.0) must not move `latest` backwards.
    """
    ver = Version(ref_name.removeprefix("v"))
    if not is_stable(ver):
        return Classification(version=ver, is_stable_release=False)
    highest = highest_stable_version(existing_tags)
    return Classification(version=ver, is_stable_release=highest is None or ver >= highest)


def write_github_env(c: Classification) -> bool:
    env_path = os.getenv("GITHUB_ENV")
    if not env_path:
        return False

    with open(env_path, "a", encoding="utf-8") as f:
        f.write(f"VERSION={c.version}\n")
        f.write(f"IS_STABLE_RELEASE={c.is_stable_str}\n")
    return True


def main(argv: list[str]) -> int:
    p = argparse.ArgumentParser(
        description="Classify a git tag as the highest stable release vs an older-line or prerelease/dev tag."
    )
    p.add_argument(
        "--ref-name",
        help="Tag/ref name (e.g. v0.18.0, v0.18.0.dev1). If omitted, uses GITHUB_REF_NAME or git describe.",
    )
    p.add_argument(
        "--project-version",
        help="Project version from pyproject.toml (e.g. 0.18.0). If provided, validates that ref name matches.",
    )
    args = p.parse_args(argv)

    ref_name = resolve_ref_name(args.ref_name)
    c = classify(ref_name, list_version_tags())

    # Validate that ref name matches project version if provided
    if args.project_version:
        ref_version_str = ref_name[1:] if ref_name.startswith("v") else ref_name
        if ref_version_str != args.project_version:
            print(
                f"ERROR: Tag {ref_name!r} does not match project version {args.project_version!r} in pyproject.toml",
                file=sys.stderr,
            )
            return 1

    wrote = write_github_env(c)

    # Always print something useful for local testing/logs
    print(f"REF_NAME={ref_name}")
    print(f"VERSION={c.version}")
    print(f"IS_STABLE_RELEASE={c.is_stable_str}")
    if wrote:
        print("Wrote VERSION and IS_STABLE_RELEASE to GITHUB_ENV", file=sys.stderr)

    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
