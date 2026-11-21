"""Characterization tests for tools/check_wire_compat.py.

Runs the real ``oasdiff`` binary against minimal fixture pairs: OpenAPI documents under
``tests/unit/tools/fixtures/wire_compat/`` for the HTTP contract, and Pydantic-generated WS message
schemas under ``tests/unit/tools/fixtures/ws_compat/`` for the WS contract. The exact per-check filtering and the
reversed/forward argument order are the thing under test, and mocking ``oasdiff``'s output would
just re-assert whatever the mock was told to return. Skipped when ``oasdiff`` isn't on PATH
(installed from the ``mise.toml`` pin, locally and in CI via ``.github/actions/setup-oasdiff``).
"""

import json
import shutil
import subprocess
from pathlib import Path

import pytest
from check_wire_compat import (
    DEFAULT_IGNORE_FILE,
    HTTP_CONTRACT,
    WS_CONTRACT,
    WS_MESSAGES_PATH,
    check_contract,
    format_ignore_line,
    list_release_tags,
    main,
    resolve_latest_release_tag,
    select_forward_blocking_findings,
    select_reversed_blocking_findings,
    wrap_ws_schema,
)

pytestmark = pytest.mark.skipif(shutil.which("oasdiff") is None, reason="oasdiff not found on PATH")

FIXTURES = Path(__file__).parent / "fixtures" / "wire_compat"
WS_FIXTURES = Path(__file__).parent / "fixtures" / "ws_compat"
COMMITTED_WS_SCHEMA = Path(__file__).resolve().parents[3] / "frontend" / "ws-schema.json"


def _run(name: str, ignore_file: Path = DEFAULT_IGNORE_FILE) -> int:
    d = FIXTURES / name
    return check_contract(HTTP_CONTRACT, d / "head.json", d / "release.json", ignore_file, tag=name)


def _run_ws(name: str, ignore_file: Path = DEFAULT_IGNORE_FILE) -> int:
    d = WS_FIXTURES / name
    return check_contract(WS_CONTRACT, d / "head.json", d / "release.json", ignore_file, tag=name)


def _oasdiff_findings(base: Path, revision: Path) -> list[dict]:
    """Run ``oasdiff breaking base revision`` with no ignore file and return its JSON findings."""
    result = subprocess.run(
        ["oasdiff", "breaking", str(base), str(revision), "--format", "json"],
        capture_output=True,
        text=True,
        timeout=30,
    )
    return json.loads(result.stdout)


def _init_throwaway_repo(repo_dir: Path) -> Path:
    """Create a throwaway git repo at ``repo_dir`` with a committed ``frontend/openapi.json``.

    Returns the ``frontend`` directory so callers can overwrite ``openapi.json`` for later commits.
    """
    frontend_dir = repo_dir / "frontend"
    frontend_dir.mkdir()
    (frontend_dir / "openapi.json").write_text("{}")
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=repo_dir, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=repo_dir, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=repo_dir, check=True, capture_output=True)
    subprocess.run(["git", "add", "-A"], cwd=repo_dir, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "initial"], cwd=repo_dir, check=True, capture_output=True)
    return frontend_dir


def test_new_required_response_property_fails() -> None:
    """A response property that didn't exist in the release and is required at HEAD is blocked."""
    assert _run("new_required_property") != 0


def test_optional_response_property_became_required_fails() -> None:
    """A response property that was optional in the release and is required at HEAD is blocked."""
    assert _run("optional_became_required") != 0


def test_removed_response_property_fails() -> None:
    """A required response property present in the release and removed at HEAD is blocked."""
    assert _run("removed_response_property") != 0


def test_removed_endpoint_fails() -> None:
    """An endpoint present in the release and removed at HEAD is blocked."""
    assert _run("removed_endpoint") != 0


def test_removed_webhook_fails() -> None:
    """A webhook present in the release and removed at HEAD is blocked.

    This is a components-scoped finding (``webhook-removed``, ``section: "components"``) — oasdiff
    reports no ``operation``/``path`` for it at all, unlike every other fixture here. It exists to
    prove the check doesn't crash on a finding shaped like this.
    """
    assert _run("removed_webhook") != 0


def test_new_optional_response_property_passes() -> None:
    """A new, non-required response property at HEAD is not blocked."""
    assert _run("new_optional_property") == 0


def test_new_endpoint_passes() -> None:
    """A brand-new endpoint at HEAD is not blocked."""
    assert _run("new_endpoint") == 0


def test_new_enum_value_passes() -> None:
    """A new allowed enum value on an existing response property at HEAD is not blocked.

    Enum/Literal value growth is the old-client/new-server hazard hassette-client's lenient
    parsing owns, not this check — see ``FORWARD_ALLOWED_ERR_CHECK_IDS``.
    """
    assert _run("new_enum_value") == 0


def test_removed_enum_value_fails() -> None:
    """An enum value present in the release and removed at HEAD is blocked, so an enum rename is too.

    oasdiff rates this INFO by default; ``SEVERITY_OVERRIDES`` raises it, since a caller comparing
    against the removed value silently stops matching.
    """
    assert _run("removed_enum_value") != 0


def test_removed_response_property_passes_when_listed_in_ignore_file(tmp_path: Path) -> None:
    """A deliberate break passes once its exact oasdiff finding is listed in the ignore file.

    The ignore line is generated by ``format_ignore_line`` — the same function the failing check
    prints for a developer to paste — so the test proves that line actually matches what
    ``--err-ignore`` expects, not just that the format doc claims it does.
    """
    d = FIXTURES / "ignored_removed_property"
    # This same fixture pair fails without an ignore entry — the forward run is where the
    # removed-property finding surfaces (see test_removed_response_property_fails).
    assert _run("ignored_removed_property") != 0

    findings = _oasdiff_findings(d / "release.json", d / "head.json")
    blocking = select_forward_blocking_findings(findings, HTTP_CONTRACT)
    assert blocking, f"expected a blocking finding in:\n{findings}"

    ignore_file = tmp_path / "wire_compat_ignore.txt"
    ignore_file.write_text(format_ignore_line(blocking[0]) + "\n")

    assert _run("ignored_removed_property", ignore_file=ignore_file) == 0


def test_removed_webhook_passes_when_listed_in_ignore_file(tmp_path: Path) -> None:
    """A components-scoped deliberate break (no operation/path) also passes once ignored.

    Proves ``format_ignore_line``'s ``components <description>`` form — used when a finding has no
    operation/path — actually suppresses the finding via ``--err-ignore``, not just the
    ``METHOD /path <description>`` form the other ignore test covers.
    """
    d = FIXTURES / "removed_webhook"
    findings = _oasdiff_findings(d / "release.json", d / "head.json")
    blocking = select_forward_blocking_findings(findings, HTTP_CONTRACT)
    assert blocking, f"expected a blocking finding in:\n{findings}"
    assert format_ignore_line(blocking[0]).startswith("components "), blocking[0]

    ignore_file = tmp_path / "wire_compat_ignore.txt"
    ignore_file.write_text(format_ignore_line(blocking[0]) + "\n")

    assert _run("removed_webhook", ignore_file=ignore_file) == 0


def test_missing_release_tag_fails_with_a_named_message(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """When no `v*` tag exists anywhere in the repo, the check fails loudly instead of skipping."""
    _init_throwaway_repo(tmp_path)

    exit_code = main(repo_root=tmp_path)

    assert exit_code != 0
    assert "v*" in capsys.readouterr().err


def test_unreachable_release_tag_fails_with_a_named_message(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """A `v*` tag that exists in the repo but isn't reachable from HEAD counts as no tag.

    A branch forked before a release must not be compared against a tag it can't see yet — that
    would report the release's later additions as removals. Here the tag lives on a sibling branch
    that HEAD (``main``) never merged, so it must be treated the same as no tag at all.
    """
    frontend_dir = _init_throwaway_repo(tmp_path)

    subprocess.run(["git", "checkout", "-q", "-b", "other"], cwd=tmp_path, check=True, capture_output=True)
    (frontend_dir / "openapi.json").write_text('{"changed": true}')
    subprocess.run(["git", "commit", "-a", "-m", "second"], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(["git", "tag", "v1.0.0"], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(["git", "checkout", "-q", "main"], cwd=tmp_path, check=True, capture_output=True)

    exit_code = main(repo_root=tmp_path)

    assert exit_code != 0
    assert "v*" in capsys.readouterr().err


def test_highest_reachable_tag_wins(tmp_path: Path) -> None:
    """When multiple `v*` tags are reachable from HEAD, the highest version wins, not tag-creation order."""
    _init_throwaway_repo(tmp_path)
    subprocess.run(["git", "tag", "v1.0.0"], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(["git", "tag", "v1.10.0"], cwd=tmp_path, check=True, capture_output=True)

    assert resolve_latest_release_tag(tmp_path) == "v1.10.0"


def test_pre_release_and_non_pep440_tags_are_skipped(tmp_path: Path) -> None:
    """Git's version sort ranks v1.1.0rc1 and v1.1.0.dev1 above v1.1.0; only final releases count."""
    _init_throwaway_repo(tmp_path)
    for tag in ("v1.0.0", "v1.1.0", "v1.1.0rc1", "v1.1.0.dev1", "v1.2.0-beta", "vnext"):
        subprocess.run(["git", "tag", tag], cwd=tmp_path, check=True, capture_output=True)

    assert list_release_tags(tmp_path) == ["v1.1.0", "v1.0.0"]


@pytest.mark.parametrize(
    "name",
    [
        "new_optional_field",
        "new_message_type",
        "new_enum_value",
        # An optional field has a default, so a client still parses a message without it; same as HTTP.
        "removed_optional_field",
    ],
)
def test_ws_compatible_change_passes(name: str) -> None:
    """A WS change every client version can parse is not blocked.

    A new message type passes because WS clients ignore message types they don't know.
    """
    assert _run_ws(name) == 0


@pytest.mark.parametrize(
    "name",
    [
        "new_required_field",
        "removed_required_field",
        "optional_became_required",
        "removed_message_type",
        "renamed_message_type",
        "removed_enum_value",
        "became_nullable",
    ],
)
def test_ws_breaking_change_fails(name: str) -> None:
    """A WS change that one side of a version skew can't parse is blocked."""
    assert _run_ws(name) != 0


def test_ws_removed_message_type_passes_when_listed_in_ignore_file(tmp_path: Path) -> None:
    """A deliberate WS break passes once the line the check prints is in the ignore file.

    Removing a message type surfaces only in the reversed run, so this also proves the reversed
    run's waiver line, with the fake WS operation as its location, matches ``--err-ignore``.
    """
    d = WS_FIXTURES / "removed_message_type"
    head = tmp_path / "head.json"
    release = tmp_path / "release.json"
    head.write_text(json.dumps(wrap_ws_schema(json.loads((d / "head.json").read_text()))))
    release.write_text(json.dumps(wrap_ws_schema(json.loads((d / "release.json").read_text()))))
    findings = _oasdiff_findings(head, release)
    blocking = select_reversed_blocking_findings(findings, WS_CONTRACT)
    assert blocking, f"expected a blocking finding in:\n{findings}"
    assert format_ignore_line(blocking[0]).startswith(f"GET {WS_MESSAGES_PATH} "), blocking[0]

    ignore_file = tmp_path / "wire_compat_ignore.txt"
    ignore_file.write_text("".join(format_ignore_line(f) + "\n" for f in blocking))

    assert _run_ws("removed_message_type", ignore_file=ignore_file) == 0


def test_wrapped_ws_schema_resolves_every_reference() -> None:
    """Every reference in the wrapped committed schema names an existing component.

    oasdiff fails to load a document with a dangling reference. References sit under ``$ref`` keys and
    as the discriminator's ``mapping`` values, so this collects every string that looks like one.
    """
    wrapped = wrap_ws_schema(json.loads(COMMITTED_WS_SCHEMA.read_text()))
    schemas = wrapped["components"]["schemas"]
    references = _reference_strings(wrapped)

    assert len(references) > len(schemas["WsServerMessage"]["oneOf"]), "expected nested references too"
    for reference in references:
        assert reference.startswith("#/components/schemas/"), reference
        assert reference.removeprefix("#/components/schemas/") in schemas, reference


def _reference_strings(node: object) -> list[str]:
    if isinstance(node, dict):
        return [ref for value in node.values() for ref in _reference_strings(value)]
    if isinstance(node, list):
        return [ref for item in node for ref in _reference_strings(item)]
    return [node] if isinstance(node, str) and node.startswith("#/") else []


def test_main_reports_a_schema_missing_at_the_release_tag_and_checks_the_rest(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """A release tag without ``ws-schema.json`` fails the WS contract loudly, and HTTP still gets checked.

    A maintenance branch whose newest reachable tag predates a contract's file must not crash or skip
    the other contracts.
    """
    frontend_dir = _init_throwaway_repo(tmp_path)
    (frontend_dir / "openapi.json").write_text((FIXTURES / "new_endpoint" / "release.json").read_text())
    subprocess.run(["git", "commit", "-qam", "real spec"], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(["git", "tag", "v1.0.0"], cwd=tmp_path, check=True, capture_output=True)
    (frontend_dir / "ws-schema.json").write_text(COMMITTED_WS_SCHEMA.read_text())

    exit_code = main(repo_root=tmp_path)

    captured = capsys.readouterr()
    assert exit_code != 0
    assert "WS schema not readable at v1.0.0" in captured.err
    assert "HTTP wire compatibility check passed against v1.0.0." in captured.out
