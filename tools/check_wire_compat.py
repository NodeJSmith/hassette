#!/usr/bin/env -S uv run
"""Pre-push / CI check: enforce wire compatibility against the latest release.

Runs ``oasdiff breaking`` twice against HEAD's ``frontend/openapi.json`` and the same file as it
existed at the latest ``v*`` git tag reachable from HEAD, in both version-skew directions.
Severity is decided in Python from oasdiff's JSON findings (``id`` + ``level``), not from an
``oasdiff --severity-levels`` file — a per-check-id allowlist here means a newer oasdiff that adds
checks can't produce spurious failures in the reversed run just by existing.

- **Reversed (new client, old server):** ``oasdiff breaking <HEAD> <last-release>``. oasdiff
  judges the *old-client/new-server* direction by default, which scores a newly required response
  field as ``info`` (non-breaking). Swapping the argument order flips that same change to
  ``response-required-property-removed`` / ``response-property-became-optional``, both ``error``
  — a client written against the last release cannot handle a response the new server now
  requires. Only findings whose ``id`` is in ``REVERSED_BLOCKING_CHECK_IDS`` block this run; every
  other finding (a reversed run also flags legitimate additions, like a new endpoint, as "removed")
  is ignored.
- **Forward (old client, new server):** ``oasdiff breaking <last-release> <HEAD>``. Every
  ERR-level finding blocks except ``FORWARD_ALLOWED_ERR_CHECK_IDS``
  (``response-property-enum-value-added``) — enum/Literal value growth is the old-client/new-server
  hazard hassette-client's lenient parsing owns, not this check.

Both runs take ``--err-ignore tools/wire_compat_ignore.txt`` for deliberate, reviewed breaks (see
that file's header for the override format). A failing run prints, for each blocking finding, the
exact line to paste into that file.

See ``design/research/2026-09-29-wire-compat-enforcement/research.md`` and
``design/specs/116-wire-models-to-hassette-wire/design.md`` ("Wire-compatibility check") for the
full rationale.
"""

import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
TOOLS_DIR = REPO_ROOT / "tools"
DEFAULT_IGNORE_FILE = TOOLS_DIR / "wire_compat_ignore.txt"
OPENAPI_RELATIVE_PATH = "frontend/openapi.json"

GIT_TIMEOUT_SECONDS = 30
OASDIFF_TIMEOUT_SECONDS = 60

# oasdiff's checker.Level: ERR=3, WARN=2, INFO=1, NONE=0 (checker/rules package, pinned 1.32.1).
ERR_LEVEL = 3

# Reversed run (new client, old server): only these check ids block, regardless of how many other
# checks a future oasdiff version adds. Both are always ERR by default.
REVERSED_BLOCKING_CHECK_IDS = frozenset(
    {
        "response-property-became-optional",
        "response-required-property-removed",
    }
)

# Forward run (old client, new server): every ERR-level finding blocks except these.
FORWARD_ALLOWED_ERR_CHECK_IDS = frozenset(
    {
        "response-property-enum-value-added",
    }
)

_NO_EXEMPT_IDS: frozenset[str] = frozenset()


def resolve_latest_release_tag(repo_root: Path) -> str | None:
    """Return the latest ``v*`` git tag reachable from HEAD, or None if there is none.

    Uses ``git describe`` rather than a repo-wide ``git tag --list`` + version sort, so a branch
    forked before a release doesn't get compared against a tag it can't see yet.
    """
    result = subprocess.run(
        ["git", "describe", "--tags", "--abbrev=0", "--match", "v*"],
        cwd=repo_root,
        capture_output=True,
        text=True,
        timeout=GIT_TIMEOUT_SECONDS,
    )
    if result.returncode == 0:
        return result.stdout.strip()

    stderr = result.stderr.strip()
    # git describe's two "nothing to describe" messages: no v* tag exists anywhere in the repo, or
    # none of the existing v* tags are reachable from HEAD.
    if "no names found" in stderr.lower() or "no tags can describe" in stderr.lower():
        return None
    raise RuntimeError(f"git describe failed: {stderr}")


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


def run_oasdiff(base: Path, revision: Path, ignore_file: Path, label: str) -> list[dict[str, Any]]:
    """Run ``oasdiff breaking base revision`` and return the parsed JSON findings.

    ``--err-ignore`` is applied by oasdiff itself, so an ignored finding never appears in the
    returned list. Any non-zero exit code is a genuine tool error (bad args, unreadable spec,
    malformed output) — severity is decided entirely in Python from the returned findings, so
    oasdiff itself is never asked to fail the run via ``--fail-on``.
    """
    print(f"--- oasdiff breaking ({label}): {base} -> {revision} ---")
    result = subprocess.run(
        [
            "oasdiff",
            "breaking",
            str(base),
            str(revision),
            "--format",
            "json",
            "--err-ignore",
            str(ignore_file),
        ],
        capture_output=True,
        text=True,
        timeout=OASDIFF_TIMEOUT_SECONDS,
    )
    if result.stderr:
        print(result.stderr, file=sys.stderr, end="")
    if result.returncode != 0:
        raise RuntimeError(f"oasdiff exited with unexpected code {result.returncode} ({label} run)")

    findings: list[dict[str, Any]] = json.loads(result.stdout) if result.stdout.strip() else []
    for finding in findings:
        print(f"  [{finding['id']}] {finding['operation']} {finding['path']}: {finding['text']}")
    return findings


def select_blocking_findings(
    findings: list[dict[str, Any]],
    *,
    only_ids: frozenset[str] | None = None,
    exempt_ids: frozenset[str] = _NO_EXEMPT_IDS,
) -> list[dict[str, Any]]:
    """Return the findings that should fail the run.

    ``only_ids`` (reversed run): keep only findings whose id is in the set — an allowlist of what
    blocks. ``exempt_ids`` (forward run): keep every ERR-level finding except those ids — a
    denylist of exceptions. A run passes ``only_ids`` XOR ``exempt_ids``, never both.
    """
    return [
        finding
        for finding in findings
        if finding.get("level") == ERR_LEVEL
        and (only_ids is None or finding["id"] in only_ids)
        and finding["id"] not in exempt_ids
    ]


def format_ignore_line(finding: dict[str, Any]) -> str:
    """Format a finding as the line to paste into ``tools/wire_compat_ignore.txt``.

    Matches oasdiff's own ``--err-ignore`` line format: ``METHOD /path <description>`` for a
    path-scoped finding, ``components <description>`` for one with no operation/path (e.g. a
    removed shared schema).
    """
    operation = finding.get("operation")
    path = finding.get("path")
    if operation and path:
        return f"{operation} {path} {finding['text']}"
    return f"components {finding['text']}"


def print_blocking_findings(findings: list[dict[str, Any]], label: str) -> None:
    print(f"Wire compatibility check FAILED ({label}). Paste one line per finding below into")
    print("tools/wire_compat_ignore.txt to accept it as a deliberate, reviewed break:")
    for finding in findings:
        print(f"  [{finding['id']}] {format_ignore_line(finding)}")


def main(
    repo_root: Path = REPO_ROOT,
    head_openapi_path: Path | None = None,
    release_openapi_path: Path | None = None,
    ignore_file: Path = DEFAULT_IGNORE_FILE,
) -> int:
    """Run both directions of the wire-compat check.

    ``head_openapi_path`` overrides HEAD's ``frontend/openapi.json`` path. ``release_openapi_path``
    overrides the "last release" spec directly, bypassing git-tag resolution and ``git show``
    entirely. Tests supply both to drive this with fixture pairs without a real git history. In
    the normal invocation both are None: HEAD's committed ``frontend/openapi.json`` is used, and
    the "last release" spec is extracted from the latest ``v*`` tag reachable from HEAD via git.
    """
    if shutil.which("oasdiff") is None:
        print("oasdiff not found on PATH. Install via `mise install` (see mise.toml).", file=sys.stderr)
        return 1

    resolved_head_path = head_openapi_path if head_openapi_path is not None else repo_root / OPENAPI_RELATIVE_PATH
    if not resolved_head_path.exists():
        print(f"HEAD OpenAPI spec not found: {resolved_head_path}", file=sys.stderr)
        return 1

    if release_openapi_path is not None:
        return _run_both_directions(
            resolved_head_path, release_openapi_path, ignore_file, label=str(release_openapi_path)
        )

    tag = resolve_latest_release_tag(repo_root)
    if tag is None:
        print(
            "No 'v*' release tag reachable from HEAD. The wire-compat check needs at least one "
            "'v*' tag to compare HEAD against — it never skips silently.",
            file=sys.stderr,
        )
        return 1

    with tempfile.TemporaryDirectory() as tmp:
        release_openapi_path = extract_tagged_openapi(repo_root, tag, Path(tmp))
        return _run_both_directions(resolved_head_path, release_openapi_path, ignore_file, label=tag)


def _run_both_directions(head_openapi_path: Path, release_openapi_path: Path, ignore_file: Path, label: str) -> int:
    """Run the reversed and forward oasdiff checks and report the combined result."""
    reversed_findings = run_oasdiff(
        head_openapi_path,
        release_openapi_path,
        ignore_file,
        label="reversed: new client, old server",
    )
    reversed_blocking = select_blocking_findings(reversed_findings, only_ids=REVERSED_BLOCKING_CHECK_IDS)

    forward_findings = run_oasdiff(
        release_openapi_path,
        head_openapi_path,
        ignore_file,
        label="forward: old client, new server",
    )
    forward_blocking = select_blocking_findings(forward_findings, exempt_ids=FORWARD_ALLOWED_ERR_CHECK_IDS)

    if not reversed_blocking and not forward_blocking:
        print(f"Wire compatibility check passed against {label}.")
        return 0

    if reversed_blocking:
        print_blocking_findings(reversed_blocking, label="reversed: new client, old server")
    if forward_blocking:
        print_blocking_findings(forward_blocking, label="forward: old client, new server")
    return 1


if __name__ == "__main__":
    sys.exit(main())
