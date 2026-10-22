#!/usr/bin/env python3
"""Rewrite the hassette version in a release-branch checkout, for cutting a patch release off an old line.

release-please only bumps `main`, so a patch release on an older line needs its version set by hand in every
file that carries it. This script doesn't exist on old tags, so run it from a main checkout against a
release-branch worktree:

    uv run python tools/release/bump_version.py 0.58.1 --root ../hassette-0.58

It edits, under `--root`:

- the `version = "..."` line in `pyproject.toml`, `wire/pyproject.toml` and `client/pyproject.toml`
- the exact `hassette-wire==` / `hassette-client[...]==` pins, keeping each line's `# x-release-please-version`
  marker
- the `"."` entry in `.release-please-manifest.json`

then runs `uv lock` in the root. Any of those locations missing from an old line (the workspace members predate
some lines) is skipped and reported, not treated as an error; a missing root `pyproject.toml` means `--root` is
wrong and fails.

Stdlib-only, like bump_addon.py.
"""

import argparse
import json
import re
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path

VERSION_ARG = re.compile(r"^\d+\.\d+\.\d+$")
VERSION_LINE = re.compile(r'^(version\s*=\s*")[^"]*(")', re.MULTILINE)
EXACT_PIN = re.compile(r'("hassette-(?:wire|client)(?:\[[^\]]*\])?==)[^"]*(")')
PYPROJECTS = ("pyproject.toml", "wire/pyproject.toml", "client/pyproject.toml")
MANIFEST = ".release-please-manifest.json"

LockRunner = Callable[[Path], None]


class BumpError(Exception):
    """The bump can't proceed; the message says why."""


def validate_version(version: str) -> str:
    """Return `version` when it's a plain X.Y.Z, else raise BumpError."""
    if not VERSION_ARG.match(version):
        raise BumpError(f"version must be a plain X.Y.Z release, got {version!r}")
    return version


def bump_pyproject(text: str, version: str) -> str:
    """Rewrite the top-level `version` line and every exact hassette-wire/hassette-client pin."""
    text = VERSION_LINE.sub(rf"\g<1>{version}\g<2>", text, count=1)
    return EXACT_PIN.sub(rf"\g<1>{version}\g<2>", text)


def bump_manifest(text: str, version: str) -> str:
    manifest = json.loads(text)
    manifest["."] = version
    return json.dumps(manifest, indent="\t") + "\n"


def run_uv_lock(root: Path) -> None:
    subprocess.run(["uv", "lock"], cwd=root, check=True, timeout=600)


def run(version: str, root: Path, lock: LockRunner = run_uv_lock) -> tuple[list[str], list[str]]:
    """Bump every version location under `root` and relock. Returns (edited, skipped) relative paths."""
    validate_version(version)
    if not (root / "pyproject.toml").is_file():
        raise BumpError(f"{root} has no pyproject.toml; --root must point at a hassette checkout")

    edited: list[str] = []
    skipped: list[str] = []
    for rel_path in PYPROJECTS:
        path = root / rel_path
        if not path.is_file():
            skipped.append(rel_path)
            continue
        text = path.read_text(encoding="utf-8")
        if VERSION_LINE.search(text) is None:
            raise BumpError(f'{rel_path} has no top-level `version = "..."` line')
        path.write_text(bump_pyproject(text, version), encoding="utf-8")
        edited.append(rel_path)

    manifest_path = root / MANIFEST
    if manifest_path.is_file():
        manifest_path.write_text(bump_manifest(manifest_path.read_text(encoding="utf-8"), version), encoding="utf-8")
        edited.append(MANIFEST)
    else:
        skipped.append(MANIFEST)

    lock(root)
    return edited, skipped


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="Set the hassette version in a release-branch checkout.")
    parser.add_argument("version", help="Target version, e.g. 0.58.1")
    parser.add_argument("--root", required=True, type=Path, help="Root of the checkout to edit")
    args = parser.parse_args(argv)

    try:
        edited, skipped = run(args.version, args.root)
    except BumpError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    except subprocess.CalledProcessError as exc:
        print(f"error: `uv lock` failed with exit code {exc.returncode}", file=sys.stderr)
        return 1

    for rel_path in edited:
        print(f"set {args.version} in {rel_path}")
    for rel_path in skipped:
        print(f"skipped {rel_path} (not present on this line)")
    print("ran uv lock")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
