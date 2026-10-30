"""Tests for scripts/ci_flake_scan.py: flaky-issue matching and scanning of earlier run attempts."""

import json
import subprocess
from dataclasses import dataclass, field

import ci_flake_scan
import pytest
from ci_flake_scan import classify_verdict, fetch_tracked_flakes, main

TEST_FILE = "tests/unit/test_foo.py"
FLAKY_TEST = f"{TEST_FILE}::test_flaky"
OTHER_TEST = f"{TEST_FILE}::test_other"
SINGLE_COMMIT = "single commit"
RECURRING = "NEW -- recurring across independent commits"
# What `gh run view --job <id> --log-failed` prints for a job from an earlier attempt:
# the latest attempt's log, which says nothing about the job that was asked for.
LATEST_ATTEMPT_LOG = "test (3.14)\tRun tests\t2026-10-30T13:25:58Z ##[group]Run uv run nox\n"


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


def summary_log(*lines: str) -> str:
    """A `--log-failed` job log whose pytest summary section holds `lines`, with gh's per-line prefix."""
    prefix = "test (3.14)\tRun tests\t2026-10-30T13:15:30Z "
    return "".join(f"{prefix}{line}\n" for line in ("=== short test summary info ===", *lines))


def gh_run(run_id: int, attempt: int, conclusion: str, *, sha: str = "sha-a", branch: str = "feature") -> dict:
    return {
        "databaseId": run_id,
        "attempt": attempt,
        "conclusion": conclusion,
        "headSha": sha,
        "headBranch": branch,
        "createdAt": "2026-10-30T13:08:47Z",
    }


def failed_job(job_id: int, name: str = "test (3.14)") -> dict:
    return {"databaseId": job_id, "name": name, "conclusion": "failure"}


@dataclass
class FakeGh:
    """Stands in for the `gh` CLI at the subprocess boundary, as observed against real reruns.

    `--status failure` filters on a run's latest conclusion, jobs default to the latest
    attempt, and a job log fetched without `--attempt` resolves to the latest attempt.
    """

    runs: list[dict]
    jobs: dict[tuple[int, int], list[dict]] = field(default_factory=dict)
    logs: dict[int, str] = field(default_factory=dict)
    calls: list[list[str]] = field(default_factory=list)

    def latest_attempt(self, run_id: int) -> int:
        return next(r["attempt"] for r in self.runs if r["databaseId"] == run_id)

    def job_location(self, job_id: int) -> tuple[int, int]:
        return next(key for key, jobs in self.jobs.items() if any(j["databaseId"] == job_id for j in jobs))

    def job_log_stdout(self, args: list[str]) -> str:
        job_id = int(flag_value(args, "--job") or 0)
        run_id, attempt = self.job_location(job_id)
        requested = flag_value(args, "--attempt")
        if requested is None and attempt != self.latest_attempt(run_id):
            return LATEST_ATTEMPT_LOG
        return self.logs[job_id]

    def run_list_stdout(self, args: list[str]) -> str:
        if flag_value(args, "--status") == "failure":
            return json.dumps([r for r in self.runs if r["conclusion"] == "failure"])
        return json.dumps(self.runs)

    def run(self, args: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        self.calls.append(args)
        if args[1:3] == ["issue", "list"]:
            stdout = "[]"
        elif args[1:3] == ["run", "list"]:
            stdout = self.run_list_stdout(args)
        elif "--log-failed" in args:
            stdout = self.job_log_stdout(args)
        else:
            run_id = int(args[3])
            attempt = int(flag_value(args, "--attempt") or self.latest_attempt(run_id))
            stdout = json.dumps({"jobs": self.jobs.get((run_id, attempt), [])})
        return subprocess.CompletedProcess(args, 0, stdout=stdout, stderr="")


def flag_value(args: list[str], flag: str) -> str | None:
    return args[args.index(flag) + 1] if flag in args else None


def scan_report(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], gh: FakeGh) -> str:
    """Run the whole scan against `gh` and return the printed report."""
    monkeypatch.setattr(ci_flake_scan.subprocess, "run", gh.run)
    main(days=0, workflow=["Tests"])
    return capsys.readouterr().out


def test_failure_cleared_by_a_rerun_is_reported(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    gh = FakeGh(
        runs=[gh_run(1, attempt=2, conclusion="success")],
        jobs={(1, 1): [failed_job(10)], (1, 2): []},
        logs={10: summary_log(f"ERROR {FLAKY_TEST} - pytest.PytestUnraisableExceptionWarning")},
    )

    report = scan_report(monkeypatch, capsys, gh)

    assert FLAKY_TEST in report
    assert SINGLE_COMMIT in report
    assert "PytestUnraisableExceptionWarning" in report


def test_infra_failure_cleared_by_a_rerun_is_reported(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    gh = FakeGh(
        runs=[gh_run(1, attempt=2, conclusion="success")],
        jobs={(1, 1): [failed_job(10, name="system (3.12)")], (1, 2): []},
        logs={10: "system (3.12)\tBuild\t2026-10-30T13:15:30Z ##[error]The operation was aborted\n"},
    )

    report = scan_report(monkeypatch, capsys, gh)

    assert "system (3.12): 1x -- The operation was aborted" in report
    assert "No pytest failures found." in report


def test_attempts_failing_differently_are_both_reported(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    gh = FakeGh(
        runs=[gh_run(1, attempt=2, conclusion="failure")],
        jobs={(1, 1): [failed_job(10)], (1, 2): [failed_job(20)]},
        logs={10: summary_log(f"FAILED {FLAKY_TEST} - boom"), 20: summary_log(f"FAILED {OTHER_TEST} - bang")},
    )

    report = scan_report(monkeypatch, capsys, gh)

    assert FLAKY_TEST in report
    assert OTHER_TEST in report


def test_same_failure_in_two_attempts_counts_as_one_commit(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    gh = FakeGh(
        runs=[gh_run(1, attempt=2, conclusion="failure", branch="main")],
        jobs={(1, 1): [failed_job(10)], (1, 2): [failed_job(20)]},
        logs={10: summary_log(f"FAILED {FLAKY_TEST} - boom"), 20: summary_log(f"FAILED {FLAKY_TEST} - boom")},
    )

    report = scan_report(monkeypatch, capsys, gh)

    assert f"2x -- {SINGLE_COMMIT}" in report
    assert RECURRING not in report


def test_rerun_cleared_failures_on_two_commits_are_recurring(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    gh = FakeGh(
        runs=[
            gh_run(1, attempt=2, conclusion="success", sha="sha-a", branch="feature-a"),
            gh_run(2, attempt=2, conclusion="success", sha="sha-b", branch="feature-b"),
        ],
        jobs={(1, 1): [failed_job(10)], (2, 1): [failed_job(20)]},
        logs={10: summary_log(f"FAILED {FLAKY_TEST} - boom"), 20: summary_log(f"FAILED {FLAKY_TEST} - boom")},
    )

    report = scan_report(monkeypatch, capsys, gh)

    assert f"2x -- {RECURRING}" in report


def test_rerun_cleared_failure_joins_the_commit_it_ran_on(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    gh = FakeGh(
        runs=[
            gh_run(1, attempt=2, conclusion="success", sha="sha-a"),
            gh_run(2, attempt=1, conclusion="failure", sha="sha-a"),
        ],
        jobs={(1, 1): [failed_job(10)], (2, 1): [failed_job(20)]},
        logs={10: summary_log(f"FAILED {FLAKY_TEST} - boom"), 20: summary_log(f"FAILED {FLAKY_TEST} - boom")},
    )

    report = scan_report(monkeypatch, capsys, gh)

    assert f"2x -- {SINGLE_COMMIT}" in report


def test_run_listed_twice_is_scanned_once(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    run = gh_run(1, attempt=1, conclusion="failure")
    gh = FakeGh(
        runs=[run, run],
        jobs={(1, 1): [failed_job(10)]},
        logs={10: summary_log(f"FAILED {FLAKY_TEST} - boom")},
    )

    report = scan_report(monkeypatch, capsys, gh)

    assert f"1x -- {SINGLE_COMMIT}" in report
