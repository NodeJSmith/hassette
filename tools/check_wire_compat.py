#!/usr/bin/env -S uv run
"""Pre-push / CI check: enforce wire compatibility against the latest release.

Runs ``oasdiff breaking`` twice against HEAD's ``frontend/openapi.json`` and the
same file as it existed at the latest ``v*`` git tag, in both version-skew
directions:

- **Reversed (new client, old server):** ``oasdiff breaking <HEAD> <last-release>``.
  oasdiff judges the *old-client/new-server* direction by default, which scores a
  newly required response field as ``info`` (non-breaking). Swapping the argument
  order flips that same change to ``response-required-property-removed`` /
  ``response-property-became-optional``, both ``error`` — a client written against
  the last release cannot handle a response the new server now requires.
  ``tools/wire_compat_levels_reversed.txt`` silences every other check in this
  direction (a reversed run also flags legitimate additions, like a new endpoint,
  as breaking).
- **Forward (old client, new server):** ``oasdiff breaking <last-release> <HEAD>``
  with oasdiff's default severities, catching removed response fields, type
  changes, removed endpoints, and new required request parameters.
  ``tools/wire_compat_levels_forward.txt`` lowers only
  ``response-property-enum-value-added`` to ``info`` — enum/Literal value growth
  is the old-client/new-server hazard that hassette-client's lenient parsing owns,
  not this check.

Both runs take ``--err-ignore tools/wire_compat_ignore.txt`` for deliberate,
reviewed breaks (see that file's header for the override format).

See ``design/research/2026-09-29-wire-compat-enforcement/research.md`` and
``design/specs/116-wire-models-to-hassette-wire/design.md`` ("Wire-compatibility
check") for the full rationale.
"""

import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
TOOLS_DIR = REPO_ROOT / "tools"
LEVELS_REVERSED = TOOLS_DIR / "wire_compat_levels_reversed.txt"
LEVELS_FORWARD = TOOLS_DIR / "wire_compat_levels_forward.txt"
DEFAULT_IGNORE_FILE = TOOLS_DIR / "wire_compat_ignore.txt"
OPENAPI_RELATIVE_PATH = "frontend/openapi.json"

GIT_TIMEOUT_SECONDS = 30
OASDIFF_TIMEOUT_SECONDS = 60


def resolve_latest_release_tag(repo_root: Path) -> str | None:
    """Return the latest ``v*`` git tag (by version sort), or None if there are none."""
    result = subprocess.run(
        ["git", "tag", "--list", "v*", "--sort=-v:refname"],
        cwd=repo_root,
        capture_output=True,
        text=True,
        timeout=GIT_TIMEOUT_SECONDS,
    )
    if result.returncode != 0:
        raise RuntimeError(f"git tag --list failed: {result.stderr.strip()}")
    tags = [line.strip() for line in result.stdout.splitlines() if line.strip()]
    return tags[0] if tags else None


def extract_tagged_openapi(repo_root: Path, tag: str, dest_dir: Path) -> Path:
    """Extract ``frontend/openapi.json`` as it existed at ``tag`` into ``dest_dir``."""
    result = subprocess.run(
        ["git", "show", f"{tag}:{OPENAPI_RELATIVE_PATH}"],
        cwd=repo_root,
        capture_output=True,
        text=True,
        timeout=GIT_TIMEOUT_SECONDS,
    )
    if result.returncode != 0:
        raise RuntimeError(f"git show {tag}:{OPENAPI_RELATIVE_PATH} failed: {result.stderr.strip()}")
    dest_path = dest_dir / "openapi-release.json"
    dest_path.write_text(result.stdout)
    return dest_path


def run_oasdiff(base: Path, revision: Path, levels_file: Path, ignore_file: Path, label: str) -> bool:
    """Run ``oasdiff breaking base revision`` with the given severity levels and ignore file.

    Prints the run's output and returns True if it passed (exit code 0), False on a
    breaking-change failure (exit code 1). Any other exit code is treated as a tool
    error and raises.
    """
    print(f"--- oasdiff breaking ({label}): {base} -> {revision} ---")
    result = subprocess.run(
        [
            "oasdiff",
            "breaking",
            str(base),
            str(revision),
            "--fail-on",
            "ERR",
            "--severity-levels",
            str(levels_file),
            "--err-ignore",
            str(ignore_file),
        ],
        capture_output=True,
        text=True,
        timeout=OASDIFF_TIMEOUT_SECONDS,
    )
    print(result.stdout, end="")
    if result.stderr:
        print(result.stderr, file=sys.stderr, end="")

    if result.returncode == 0:
        return True
    if result.returncode == 1:
        return False
    raise RuntimeError(f"oasdiff exited with unexpected code {result.returncode} ({label} run)")


def main(
    repo_root: Path = REPO_ROOT,
    base_openapi_path: Path | None = None,
    revision_openapi_path: Path | None = None,
    ignore_file: Path = DEFAULT_IGNORE_FILE,
) -> int:
    """Run both directions of the wire-compat check.

    ``base_openapi_path`` overrides HEAD's ``frontend/openapi.json`` path.
    ``revision_openapi_path`` overrides the "last release" spec directly, bypassing
    git-tag resolution and ``git show`` entirely. Tests supply both to drive this
    with fixture pairs without a real git history. In the normal invocation both are
    None: HEAD's committed ``frontend/openapi.json`` is used, and the "last release"
    spec is extracted from the latest ``v*`` tag via git.
    """
    if shutil.which("oasdiff") is None:
        print("oasdiff not found on PATH. Install via `mise install` (see mise.toml).", file=sys.stderr)
        return 1

    head_openapi_path = base_openapi_path if base_openapi_path is not None else repo_root / OPENAPI_RELATIVE_PATH
    if not head_openapi_path.exists():
        print(f"HEAD OpenAPI spec not found: {head_openapi_path}", file=sys.stderr)
        return 1

    if revision_openapi_path is not None:
        return _run_both_directions(
            head_openapi_path, revision_openapi_path, ignore_file, label=str(revision_openapi_path)
        )

    tag = resolve_latest_release_tag(repo_root)
    if tag is None:
        print(
            "No 'v*' release tag found in this repository. The wire-compat check needs at "
            "least one 'v*' tag to compare HEAD against — it never skips silently.",
            file=sys.stderr,
        )
        return 1

    with tempfile.TemporaryDirectory() as tmp:
        release_openapi_path = extract_tagged_openapi(repo_root, tag, Path(tmp))
        return _run_both_directions(head_openapi_path, release_openapi_path, ignore_file, label=tag)


def _run_both_directions(head_openapi_path: Path, release_openapi_path: Path, ignore_file: Path, label: str) -> int:
    """Run the reversed and forward oasdiff checks and report the combined result."""
    reversed_ok = run_oasdiff(
        head_openapi_path,
        release_openapi_path,
        LEVELS_REVERSED,
        ignore_file,
        label="reversed: new client, old server",
    )
    forward_ok = run_oasdiff(
        release_openapi_path,
        head_openapi_path,
        LEVELS_FORWARD,
        ignore_file,
        label="forward: old client, new server",
    )

    if reversed_ok and forward_ok:
        print(f"Wire compatibility check passed against {label}.")
        return 0

    print(
        f"Wire compatibility check FAILED against {label}. "
        "A deliberate break must be listed in tools/wire_compat_ignore.txt in its `!` PR.",
        file=sys.stderr,
    )
    return 1


if __name__ == "__main__":
    sys.exit(main())
