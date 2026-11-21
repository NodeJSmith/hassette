#!/usr/bin/env -S uv run
"""Pre-push / CI check: enforce wire compatibility against the latest release.

Checks two contracts against the same files as they existed at the latest ``v*`` git tag reachable
from HEAD: the HTTP API (``frontend/openapi.json``) and the WebSocket messages the server pushes
(``frontend/ws-schema.json``). Each runs ``oasdiff breaking`` twice, once per version-skew direction.
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
  hazard hassette-client's lenient parsing owns, not this check. A *removed* response enum value is
  raised to ERR (``SEVERITY_OVERRIDES``), so an enum rename blocks here.

The WS schema is JSON Schema, not OpenAPI, so ``wrap_ws_schema`` turns each copy into an OpenAPI
document with one fake operation (``WS_MESSAGES_PATH``) that responds with the message union. The WS
policy is the HTTP one plus a rule for message types: adding one passes and removing one blocks (see
``WS_BASE_LACKS_MESSAGE_TYPE_CHECK_ID``).

All runs take ``--err-ignore tools/wire_compat_ignore.txt`` for deliberate, reviewed breaks (see
that file's header for the override format). A failing run prints, for each blocking finding, the
exact line to paste into that file.

See ``design/research/2026-09-29-wire-compat-enforcement/research.md``,
``design/research/2026-11-21-ws-schema-compat/prior-art.md`` and
``design/specs/116-wire-models-to-hassette-wire/design.md`` ("Wire-compatibility check") for the
full rationale.
"""

import json
import shutil
import subprocess
import sys
import tempfile
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from packaging.version import InvalidVersion, Version

REPO_ROOT = Path(__file__).resolve().parent.parent
TOOLS_DIR = REPO_ROOT / "tools"
DEFAULT_IGNORE_FILE = TOOLS_DIR / "wire_compat_ignore.txt"
OPENAPI_RELATIVE_PATH = "frontend/openapi.json"
WS_SCHEMA_RELATIVE_PATH = "frontend/ws-schema.json"
WS_MESSAGES_PATH = "/__ws__/server-messages"

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

# oasdiff ``--severity-levels`` overrides, applied to both runs. A removed response enum value is INFO by
# default, so a rename (one value added, one removed) passed: the added half is allowed above. But a caller
# comparing against the removed value silently stops matching, so in the forward run removal blocks. The
# reversed run reports HEAD's additions under this id and ignores it (not in REVERSED_BLOCKING_CHECK_IDS).
SEVERITY_OVERRIDES = {
    "response-property-enum-value-removed": "ERR",
}

# oasdiff reports a union branch the base lacks as "added". In the forward run (base = release) that's a
# message type HEAD added, allowed because a WS client ignores types it doesn't recognize (the rule lives in
# the ``hassette_wire`` package docstring). In the reversed run (base = HEAD) it's a type HEAD dropped, which
# blocks.
WS_BASE_LACKS_MESSAGE_TYPE_CHECK_ID = "response-body-one-of-added"


@dataclass(frozen=True)
class Contract:
    """One wire contract: the committed schema file and the policy that decides which findings block."""

    name: str
    relative_path: str
    reversed_blocking_check_ids: frozenset[str]
    forward_allowed_err_check_ids: frozenset[str]
    to_openapi: Callable[[dict[str, Any]], dict[str, Any]] | None = None
    """Converts the committed file to an OpenAPI document; None when it already is one."""


def wrap_ws_schema(schema: dict[str, Any]) -> dict[str, Any]:
    """Return an OpenAPI 3.1 document whose one operation responds with the WS message union.

    ``schema`` is ``frontend/ws-schema.json``: a root ``oneOf`` over the message models, with the models
    under ``$defs``. They move to ``components.schemas`` (refs rewritten to match) and the root becomes
    ``components.schemas.WsServerMessage``, referenced from a fake ``GET`` response: oasdiff never diffs a
    component no operation reaches, and a response is the direction WS messages flow.
    """
    union = rewrite_defs_references(schema)
    schemas = union.pop("$defs", {})
    schemas["WsServerMessage"] = union
    media = {"application/json": {"schema": {"$ref": "#/components/schemas/WsServerMessage"}}}
    return {
        "openapi": "3.1.0",
        "info": {"title": "hassette WebSocket server messages", "version": "1"},
        "paths": {WS_MESSAGES_PATH: {"get": {"responses": {"200": {"description": "A WS message", "content": media}}}}},
        "components": {"schemas": schemas},
    }


def rewrite_defs_references(node: Any) -> Any:
    """Copy ``node``, pointing every ``#/$defs/X`` reference at ``#/components/schemas/X``.

    Matches string values rather than ``$ref`` keys, because the discriminator's ``mapping`` values are
    references too.
    """
    if isinstance(node, dict):
        return {key: rewrite_defs_references(value) for key, value in node.items()}
    if isinstance(node, list):
        return [rewrite_defs_references(item) for item in node]
    if isinstance(node, str) and node.startswith("#/$defs/"):
        return "#/components/schemas/" + node.removeprefix("#/$defs/")
    return node


HTTP_CONTRACT = Contract(
    name="HTTP",
    relative_path=OPENAPI_RELATIVE_PATH,
    reversed_blocking_check_ids=REVERSED_BLOCKING_CHECK_IDS,
    forward_allowed_err_check_ids=FORWARD_ALLOWED_ERR_CHECK_IDS,
)
WS_CONTRACT = Contract(
    name="WS",
    relative_path=WS_SCHEMA_RELATIVE_PATH,
    reversed_blocking_check_ids=REVERSED_BLOCKING_CHECK_IDS | {WS_BASE_LACKS_MESSAGE_TYPE_CHECK_ID},
    forward_allowed_err_check_ids=FORWARD_ALLOWED_ERR_CHECK_IDS | {WS_BASE_LACKS_MESSAGE_TYPE_CHECK_ID},
    to_openapi=wrap_ws_schema,
)
CONTRACTS = (HTTP_CONTRACT, WS_CONTRACT)


def run_git(repo_root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    """Run ``git <args>`` in ``repo_root`` with captured text output; the caller checks ``returncode``."""
    return subprocess.run(
        ["git", *args],
        cwd=repo_root,
        capture_output=True,
        text=True,
        timeout=GIT_TIMEOUT_SECONDS,
    )


def list_release_tags(repo_root: Path) -> list[str]:
    """Return the final-release ``v*`` git tags reachable from HEAD, highest version first.

    ``git tag --list --merged HEAD`` limits candidates to tags whose commit is an ancestor of
    HEAD, so a branch forked before a release isn't compared against a tag it can't see yet.
    Empty stdout with exit 0 means no reachable tag; any non-zero exit is a real git failure.

    Ordered by PEP 440 rather than git's version sort, which ranks ``v1.0.0rc1`` above ``v1.0.0``
    (and varies with ``versionsort.suffix``). Pre-release, dev-release and non-PEP 440 tags are
    dropped: none of them is a release users run.
    """
    result = run_git(repo_root, "tag", "--list", "v*", "--merged", "HEAD")
    if result.returncode != 0:
        raise RuntimeError(f"git tag --list failed: {result.stderr.strip()}")
    versions: dict[str, Version] = {}
    for tag in (line.strip() for line in result.stdout.splitlines()):
        try:
            tag_version = Version(tag.removeprefix("v"))
        except InvalidVersion:
            continue
        if not tag_version.is_prerelease:
            versions[tag] = tag_version
    return sorted(versions, key=versions.__getitem__, reverse=True)


def resolve_latest_release_tag(repo_root: Path) -> str | None:
    """Return the highest ``v*`` git tag reachable from HEAD, or None if there is none."""
    tags = list_release_tags(repo_root)
    return tags[0] if tags else None


def extract_tagged_openapi(repo_root: Path, tag: str, dest_dir: Path) -> Path:
    """Extract ``frontend/openapi.json`` as it existed at ``tag`` into ``dest_dir``."""
    return extract_tagged_file(repo_root, tag, OPENAPI_RELATIVE_PATH, dest_dir / "openapi-release.json")


def extract_tagged_file(repo_root: Path, tag: str, relative_path: str, dest_path: Path) -> Path:
    """Write ``relative_path`` as it existed at ``tag`` to ``dest_path``."""
    result = run_git(repo_root, "show", f"{tag}:{relative_path}")
    if result.returncode != 0:
        raise RuntimeError(f"git show {tag}:{relative_path} failed: {result.stderr.strip()}")
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
    with tempfile.TemporaryDirectory() as tmp:
        # oasdiff's severity file allows no comments, so the rationale lives on SEVERITY_OVERRIDES.
        severity_file = Path(tmp) / "severity-levels.txt"
        severity_file.write_text("".join(f"{check_id} {level}\n" for check_id, level in SEVERITY_OVERRIDES.items()))
        result = subprocess.run(
            [
                "oasdiff",
                "breaking",
                str(base),
                str(revision),
                "--format",
                "json",
                "--severity-levels",
                str(severity_file),
                *ignore_args,
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


def select_reversed_blocking_findings(findings: list[dict[str, Any]], contract: Contract) -> list[dict[str, Any]]:
    """Findings that block the reversed run: only the contract's reversed blocking ids, at ERR level."""
    return [
        finding
        for finding in findings
        if finding["id"] in contract.reversed_blocking_check_ids and finding["level"] == ERR_LEVEL
    ]


def select_forward_blocking_findings(findings: list[dict[str, Any]], contract: Contract) -> list[dict[str, Any]]:
    """Findings that block the forward run: every ERR-level finding except the contract's allowed ids."""
    return [
        finding
        for finding in findings
        if finding["level"] == ERR_LEVEL and finding["id"] not in contract.forward_allowed_err_check_ids
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


def main(repo_root: Path = REPO_ROOT, ignore_file: Path = DEFAULT_IGNORE_FILE) -> int:
    """Check every contract in ``CONTRACTS`` against the latest ``v*`` tag reachable from HEAD.

    Every contract runs even after one fails, so a single push reports all of its breaks.
    """
    if shutil.which("oasdiff") is None:
        print("oasdiff not found on PATH. Install via `mise install` (see mise.toml).", file=sys.stderr)
        return 1

    tag = resolve_latest_release_tag(repo_root)
    if tag is None:
        print(
            "No 'v*' release tag reachable from HEAD. The wire-compat check needs at least one "
            "'v*' tag to compare HEAD against — it never skips silently.",
            file=sys.stderr,
        )
        return 1

    exit_code = 0
    with tempfile.TemporaryDirectory() as tmp:
        for contract in CONTRACTS:
            head_path = repo_root / contract.relative_path
            if not head_path.exists():
                print(f"HEAD {contract.name} schema not found: {head_path}", file=sys.stderr)
                exit_code = 1
                continue
            try:
                release_path = extract_tagged_file(
                    repo_root, tag, contract.relative_path, Path(tmp) / f"{contract.name}-release.json"
                )
            except RuntimeError as exc:
                print(f"{contract.name} schema not readable at {tag}: {exc}", file=sys.stderr)
                exit_code = 1
                continue
            exit_code |= check_contract(contract, head_path, release_path, ignore_file, tag=tag)
    return exit_code


def check_contract(contract: Contract, head_path: Path, release_path: Path, ignore_file: Path, tag: str) -> int:
    """Run the reversed and forward oasdiff checks for one contract; return 0 if nothing blocks, else 1.

    Tests call this directly with fixture pairs, bypassing tag resolution.
    """
    with tempfile.TemporaryDirectory() as tmp:
        if (to_openapi := contract.to_openapi) is not None:
            head_path = write_openapi(to_openapi, head_path, Path(tmp) / "head.json")
            release_path = write_openapi(to_openapi, release_path, Path(tmp) / "release.json")

        reversed_label = f"{contract.name} {LABEL_REVERSED}"
        reversed_findings = run_oasdiff(head_path, release_path, ignore_file, label=reversed_label)
        reversed_blocking = select_reversed_blocking_findings(reversed_findings, contract)

        forward_label = f"{contract.name} {LABEL_FORWARD}"
        forward_findings = run_oasdiff(release_path, head_path, ignore_file, label=forward_label)
        forward_blocking = select_forward_blocking_findings(forward_findings, contract)

    if not reversed_blocking and not forward_blocking:
        print(f"{contract.name} wire compatibility check passed against {tag}.")
        return 0

    if reversed_blocking:
        print_blocking_findings(reversed_blocking, label=reversed_label)
    if forward_blocking:
        print_blocking_findings(forward_blocking, label=forward_label)
    return 1


def write_openapi(to_openapi: Callable[[dict[str, Any]], dict[str, Any]], source: Path, dest: Path) -> Path:
    """Write ``to_openapi`` applied to the JSON in ``source`` to ``dest``."""
    dest.write_text(json.dumps(to_openapi(json.loads(source.read_text()))))
    return dest


if __name__ == "__main__":
    sys.exit(main())
