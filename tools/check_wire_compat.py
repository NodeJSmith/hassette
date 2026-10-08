#!/usr/bin/env -S uv run
"""Pre-push / CI check: enforce wire compatibility against the latest release.

Runs ``oasdiff breaking`` twice against HEAD's ``frontend/openapi.json`` and the same file as it
existed at the latest ``v*`` git tag reachable from HEAD, in both version-skew directions.
Blocking is decided in Python from oasdiff's JSON findings (``id`` + ``level``):

- **Reversed (new client, old server):** ``oasdiff breaking <HEAD> <last-release>``. oasdiff
  judges the *old-client/new-server* direction by default, which scores a newly required response
  field as ``info`` (non-breaking). Swapping the argument order flips that same change to
  ``response-required-property-removed`` / ``response-property-became-optional``, both ``error``
  — a client written against the last release cannot handle a response the new server now
  requires. Only findings whose ``id`` is in ``REVERSED_BLOCKING_CHECK_IDS`` block this run — a
  named allowlist, so a newer oasdiff that adds checks can't fail it just by existing, and a
  reversed run also flags legitimate additions (like a new endpoint) as "removed", which must not
  block.
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

LABEL_REVERSED = "reversed: new client, old server"
LABEL_FORWARD = "forward: old client, new server"

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


def list_release_tags(repo_root: Path) -> list[str]:
    """Return the ``v*`` git tags reachable from HEAD, highest version first.

    ``git tag --list --merged HEAD`` limits candidates to tags whose commit is an ancestor of
    HEAD, so a branch forked before a release isn't compared against a tag it can't see yet.
    Empty stdout with exit 0 means no reachable tag; any non-zero exit is a real git failure.
    """
    result = subprocess.run(
        ["git", "tag", "--list", "v*", "--merged", "HEAD", "--sort=-v:refname"],
        cwd=repo_root,
        capture_output=True,
        text=True,
        timeout=GIT_TIMEOUT_SECONDS,
    )
    if result.returncode != 0:
        raise RuntimeError(f"git tag --list failed: {result.stderr.strip()}")
    return [line.strip() for line in result.stdout.splitlines() if line.strip()]


def resolve_latest_release_tag(repo_root: Path) -> str | None:
    """Return the highest ``v*`` git tag reachable from HEAD, or None if there is none."""
    tags = list_release_tags(repo_root)
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


def run_oasdiff(base: Path, revision: Path, ignore_file: Path | None, label: str) -> list[dict[str, Any]]:
    """Run ``oasdiff breaking base revision`` and return the parsed JSON findings.

    ``--err-ignore`` is applied by oasdiff itself, so an ignored finding never appears in the
    returned list; ``ignore_file=None`` ignores nothing. Any non-zero exit code is a genuine tool
    error (bad args, unreadable spec, malformed output).
    """
    print(f"--- oasdiff breaking ({label}): {base} -> {revision} ---")
    ignore_args = ["--err-ignore", str(ignore_file)] if ignore_file is not None else []
    result = subprocess.run(
        ["oasdiff", "breaking", str(base), str(revision), "--format", "json", *ignore_args],
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
        print(f"  [{finding['id']}] {describe_finding_location(finding)}: {finding['text']}")
    return findings


def describe_finding_location(finding: dict[str, Any]) -> str:
    """Return a finding's location prefix: ``METHOD /path`` for a paths-scoped finding, or
    ``components`` for one that isn't (security, schema, webhook, and other non-path checks report
    no ``operation``/``path`` at all).

    ``section`` is the reliable discriminator: verified empirically for oasdiff 1.32.1 that a
    components-scoped finding (e.g. ``webhook-removed``) omits the ``operation``/``path`` keys
    entirely rather than leaving them empty, so checking their truthiness would raise ``KeyError``
    on the ones that omit them.
    """
    if finding["section"] == "paths":
        return f"{finding['operation']} {finding['path']}"
    return "components"


def select_reversed_blocking_findings(findings: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Findings that block the reversed run: only ``REVERSED_BLOCKING_CHECK_IDS`` at ERR level."""
    return [
        finding
        for finding in findings
        if finding["id"] in REVERSED_BLOCKING_CHECK_IDS and finding["level"] == ERR_LEVEL
    ]


def select_forward_blocking_findings(findings: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Findings that block the forward run: every ERR-level finding except ``FORWARD_ALLOWED_ERR_CHECK_IDS``."""
    return [
        finding
        for finding in findings
        if finding["level"] == ERR_LEVEL and finding["id"] not in FORWARD_ALLOWED_ERR_CHECK_IDS
    ]


def format_ignore_line(finding: dict[str, Any]) -> str:
    """Format a finding as the line to paste into ``tools/wire_compat_ignore.txt``.

    Matches oasdiff's own ``--err-ignore`` line format: ``METHOD /path <description>`` for a
    path-scoped finding, ``components <description>`` for a components-scoped one.
    """
    return f"{describe_finding_location(finding)} {finding['text']}"


def print_blocking_findings(findings: list[dict[str, Any]], label: str) -> None:
    print(f"Wire compatibility check FAILED ({label}). Paste each line below into tools/wire_compat_ignore.txt:")
    for finding in findings:
        print(format_ignore_line(finding))


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
        label=LABEL_REVERSED,
    )
    reversed_blocking = select_reversed_blocking_findings(reversed_findings)

    forward_findings = run_oasdiff(
        release_openapi_path,
        head_openapi_path,
        ignore_file,
        label=LABEL_FORWARD,
    )
    forward_blocking = select_forward_blocking_findings(forward_findings)

    if not reversed_blocking and not forward_blocking:
        print(f"Wire compatibility check passed against {label}.")
        return 0

    if reversed_blocking:
        print_blocking_findings(reversed_blocking, label=LABEL_REVERSED)
    if forward_blocking:
        print_blocking_findings(forward_blocking, label=LABEL_FORWARD)
    return 1


if __name__ == "__main__":
    sys.exit(main())
