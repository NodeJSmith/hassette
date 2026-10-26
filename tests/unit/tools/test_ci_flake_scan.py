"""Tests for scripts/ci_flake_scan.py's matching of failures to topic:flaky-test issues."""

import json
import subprocess

import ci_flake_scan
import pytest
from ci_flake_scan import classify_verdict, fetch_tracked_flakes

TEST_FILE = "tests/unit/test_foo.py"


def stub_gh_issue_list(monkeypatch: pytest.MonkeyPatch, issues: list[dict]) -> None:
    """Stub `gh issue list` at the subprocess boundary, returning `issues` as its JSON output."""

    def fake_run(args: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        assert args[:3] == ["gh", "issue", "list"]
        return subprocess.CompletedProcess(args, 0, stdout=json.dumps(issues), stderr="")

    monkeypatch.setattr(ci_flake_scan.subprocess, "run", fake_run)


def verdict_for(test_id: str, known: list[ci_flake_scan.KnownFlake]) -> str:
    return classify_verdict(test_id, [], known)[0]


def test_bare_name_matches_its_test_id(monkeypatch: pytest.MonkeyPatch) -> None:
    stub_gh_issue_list(monkeypatch, [{"number": 3029, "title": "Fix flaky test_foo under CI"}])
    known = fetch_tracked_flakes()

    assert verdict_for(f"{TEST_FILE}::test_foo", known) == "known (#3029)"
    assert verdict_for(f"{TEST_FILE}::TestFoo::test_foo[param-a]", known) == "known (#3029)"
    assert known[0].title == "Fix flaky test_foo under CI"


def test_class_method_name_matches_its_test_id(monkeypatch: pytest.MonkeyPatch) -> None:
    stub_gh_issue_list(monkeypatch, [{"number": 2178, "title": "Fix flaky TestGuard::test_drop race"}])
    known = fetch_tracked_flakes()

    assert verdict_for(f"{TEST_FILE}::TestGuard::test_drop", known) == "known (#2178)"
    assert verdict_for(f"{TEST_FILE}::OtherGuard::test_drop", known) != "known (#2178)"


@pytest.mark.parametrize(
    "test_id",
    [
        f"{TEST_FILE}::test_foo_bar",
        f"{TEST_FILE}::test_prefix_test_foo",
        "tests/unit/test_foo.py::test_unrelated",
    ],
)
def test_name_only_matches_at_a_name_boundary(monkeypatch: pytest.MonkeyPatch, test_id: str) -> None:
    stub_gh_issue_list(monkeypatch, [{"number": 1, "title": "Fix flaky test_foo"}])

    assert not verdict_for(test_id, fetch_tracked_flakes()).startswith("known")


def test_title_without_prefix_is_skipped_with_warning(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    stub_gh_issue_list(
        monkeypatch,
        [
            {"number": 7, "title": "test_foo is flaky"},
            {"number": 8, "title": "Fix flaky test_bar"},
        ],
    )

    known = fetch_tracked_flakes()

    assert [k.issue for k in known] == [8]
    assert "#7" in capsys.readouterr().err


def test_gh_failure_yields_no_tracked_flakes(monkeypatch: pytest.MonkeyPatch) -> None:
    def failing_run(args: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        raise subprocess.CalledProcessError(1, args, stderr="auth required")

    monkeypatch.setattr(ci_flake_scan.subprocess, "run", failing_run)

    assert fetch_tracked_flakes() == []
