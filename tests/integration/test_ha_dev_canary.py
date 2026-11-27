"""Verify tools/release/ha_dev_canary.py, which keeps ha-dev-canary.yml's single tracking issue in sync.

Runs the script as a subprocess against a stub `gh` placed first on PATH. The stub answers the
lookups from environment variables and appends every mutating call (create, edit, comment, close),
with its stdin, to a JSON-lines log the tests read back.
"""

import json
import os
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from xml.sax.saxutils import quoteattr

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = PROJECT_ROOT / "tools" / "release" / "ha_dev_canary.py"
SYSTEM_CONFTEST = PROJECT_ROOT / "tests" / "system" / "conftest.py"
SUBPROCESS_TIMEOUT_SECONDS = 30
RUN_URL = "https://github.com/o/r/actions/runs/1"
STUB_GH = """#!/usr/bin/env python3
import json, os, sys

args = sys.argv[1:]
cmd = " ".join(args[:2])
if cmd == "label create":
    sys.exit(0)
if cmd == "issue list":
    print(os.environ.get("STUB_EXISTING_ISSUE", ""))
    sys.exit(0)
if cmd == "issue view":
    print(json.dumps({"body": os.environ.get("STUB_EXISTING_BODY", "")}))
    sys.exit(0)
if cmd in ("issue create", "issue edit", "issue comment", "issue close"):
    stdin = sys.stdin.read() if "-" in args else ""
    with open(os.environ["STUB_GH_LOG"], "a") as f:
        f.write(json.dumps({"args": args, "stdin": stdin}) + "\\n")
    sys.exit(0)
print(f"stub gh: unhandled args: {args}", file=sys.stderr)
sys.exit(1)
"""


@dataclass(frozen=True)
class GhCall:
    args: list[str]
    stdin: str

    @property
    def command(self) -> str:
        return " ".join(self.args[:2])


@dataclass(frozen=True)
class CanaryResult:
    returncode: int
    stdout: str
    stderr: str
    calls: list[GhCall]


def junit(*cases: tuple[str, str | None], element: str = "error") -> str:
    """Build a JUnit report from (test name, problem message or None) pairs.

    ``element`` picks how a problem is recorded: ``error`` (setup/teardown) or ``failure`` (the test body).
    """
    body = ""
    for name, message in cases:
        inner = f"<{element} message={quoteattr(message)}>trace</{element}>" if message else ""
        body += f'<testcase classname="tests.system.test_api" name="{name}">{inner}</testcase>'
    return f'<?xml version="1.0"?><testsuites><testsuite name="pytest">{body}</testsuite></testsuites>'


def run_canary(
    tmp_path: Path,
    *,
    report: str | None,
    outcome: str,
    existing_issue: str = "",
    existing_body: str = "",
) -> CanaryResult:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(exist_ok=True)
    gh = bin_dir / "gh"
    gh.write_text(STUB_GH)
    gh.chmod(0o755)
    log = tmp_path / "gh.log"
    log.write_text("")
    junit_path = tmp_path / "report.xml"
    if report is not None:
        junit_path.write_text(report)

    env = dict(os.environ)
    env["PATH"] = f"{bin_dir}:{env['PATH']}"
    env["STUB_EXISTING_ISSUE"] = existing_issue
    env["STUB_EXISTING_BODY"] = existing_body
    env["STUB_GH_LOG"] = str(log)

    result = subprocess.run(
        [
            "python3",
            str(SCRIPT),
            "--junit",
            str(junit_path),
            "--outcome",
            outcome,
            "--ha-version",
            "2026.12.0.dev0",
            "--image-tag",
            "dev",
            "--run-url",
            RUN_URL,
        ],
        cwd=str(PROJECT_ROOT),
        capture_output=True,
        text=True,
        timeout=SUBPROCESS_TIMEOUT_SECONDS,
        env=env,
    )
    calls = [GhCall(**json.loads(line)) for line in log.read_text().splitlines()]
    return CanaryResult(returncode=result.returncode, stdout=result.stdout, stderr=result.stderr, calls=calls)


def body_for(failing: list[str]) -> str:
    return f"<!-- ha-dev-canary-failing: {json.dumps(failing)} -->\nold body"


@pytest.mark.integration
def test_green_run_without_issue_does_nothing(tmp_path: Path) -> None:
    result = run_canary(tmp_path, report=junit(("test_a", None)), outcome="success")

    assert result.returncode == 0, result.stderr
    assert result.calls == []


@pytest.mark.integration
def test_green_run_closes_open_issue(tmp_path: Path) -> None:
    result = run_canary(tmp_path, report=junit(("test_a", None)), outcome="success", existing_issue="12")

    assert result.returncode == 0, result.stderr
    assert [c.command for c in result.calls] == ["issue close"]
    assert result.calls[0].args[2] == "12"


@pytest.mark.integration
def test_first_failure_opens_issue_with_ids_version_and_run(tmp_path: Path) -> None:
    report = junit(("test_a", None), ("test_b", "boom"), ("test_c", "bang"))
    result = run_canary(tmp_path, report=report, outcome="failure")

    assert result.returncode == 0, result.stderr
    assert [c.command for c in result.calls] == ["issue create"]
    create = result.calls[0]
    assert create.args[create.args.index("--label") + 1] == "ha-dev-canary"
    body = create.stdin
    assert '<!-- ha-dev-canary-failing: ["tests.system.test_api::test_b", "tests.system.test_api::test_c"] -->' in body
    assert "`tests.system.test_api::test_b`" in body
    assert "`tests.system.test_api::test_a`" not in body
    assert "2026.12.0.dev0" in body
    assert RUN_URL in body


@pytest.mark.integration
def test_failure_elements_count_as_failing(tmp_path: Path) -> None:
    result = run_canary(tmp_path, report=junit(("test_b", "assert 1 == 2"), element="failure"), outcome="failure")

    assert result.returncode == 0, result.stderr
    assert '["tests.system.test_api::test_b"]' in result.calls[0].stdin


@pytest.mark.integration
def test_body_without_marker_is_rewritten_and_commented(tmp_path: Path) -> None:
    result = run_canary(
        tmp_path, report=junit(("test_b", "boom")), outcome="failure", existing_issue="12", existing_body="edited"
    )

    assert result.returncode == 0, result.stderr
    assert [c.command for c in result.calls] == ["issue edit", "issue comment"]
    assert "Now failing:\n- `tests.system.test_api::test_b`" in result.calls[1].stdin


@pytest.mark.integration
def test_unchanged_failing_set_leaves_issue_alone(tmp_path: Path) -> None:
    result = run_canary(
        tmp_path,
        report=junit(("test_b", "boom")),
        outcome="failure",
        existing_issue="12",
        existing_body=body_for(["tests.system.test_api::test_b"]),
    )

    assert result.returncode == 0, result.stderr
    assert result.calls == []


@pytest.mark.integration
def test_changed_failing_set_rewrites_body_and_comments(tmp_path: Path) -> None:
    result = run_canary(
        tmp_path,
        report=junit(("test_b", None), ("test_c", "bang")),
        outcome="failure",
        existing_issue="12",
        existing_body=body_for(["tests.system.test_api::test_b"]),
    )

    assert result.returncode == 0, result.stderr
    assert [c.command for c in result.calls] == ["issue edit", "issue comment"]
    assert '["tests.system.test_api::test_c"]' in result.calls[0].stdin
    comment = result.calls[1].stdin
    assert "Now failing:\n- `tests.system.test_api::test_c`" in comment
    assert "No longer failing:\n- `tests.system.test_api::test_b`" in comment


@pytest.mark.integration
def test_container_that_never_started_is_one_startup_failure(tmp_path: Path) -> None:
    message = 'failed on setup with "Failed: HA container failed to start: HA did not become ready within 60s"'
    result = run_canary(tmp_path, report=junit(("test_a", message), ("test_b", message)), outcome="failure")

    assert result.returncode == 0, result.stderr
    assert '<!-- ha-dev-canary-failing: ["<startup>"] -->' in result.calls[0].stdin


@pytest.mark.integration
@pytest.mark.parametrize("report", [None, junit(("test_a", None))], ids=["missing-report", "no-failing-test"])
def test_failed_step_without_failing_test_is_job_failed(tmp_path: Path, report: str | None) -> None:
    result = run_canary(tmp_path, report=report, outcome="failure")

    assert result.returncode == 0, result.stderr
    assert '<!-- ha-dev-canary-failing: ["<job-failed>"] -->' in result.calls[0].stdin


@pytest.mark.integration
def test_startup_prefix_matches_system_fixture() -> None:
    """The script collapses startup failures by the fixture's message prefix, so the two must agree."""
    pattern = re.compile(r'^HA_STARTUP_FAILURE = "(.+)"$', re.MULTILINE)
    script_match = pattern.search(SCRIPT.read_text())
    conftest_match = pattern.search(SYSTEM_CONFTEST.read_text())

    assert script_match is not None
    assert conftest_match is not None
    assert script_match.group(1) == conftest_match.group(1)
