"""Tests for tools/pr_labels.py: live PR label lookup and the label override for failing gates.

`gh` is an external CLI, so its subprocess call is mocked at that boundary.
"""

import json
import subprocess
from unittest.mock import MagicMock, patch

import pytest
from pr_labels import LabelLookupError, apply_label_override, fetch_pr_labels

LABEL = "lint:example-allowed"


def _gh_result(labels: list[str]) -> MagicMock:
    return MagicMock(stdout=json.dumps({"labels": [{"name": name} for name in labels]}))


def test_fetch_pr_labels_returns_names() -> None:
    with patch("pr_labels.subprocess.run", return_value=_gh_result(["a", "b"])) as run:
        assert fetch_pr_labels("12") == ["a", "b"]
    assert run.call_args.args[0] == ["gh", "pr", "view", "12", "--json", "labels"]


@pytest.mark.parametrize(
    "error",
    [
        FileNotFoundError(),
        subprocess.TimeoutExpired(cmd="gh", timeout=30),
        subprocess.CalledProcessError(1, "gh", stderr="no pull requests found"),
    ],
)
def test_fetch_pr_labels_wraps_gh_failures(error: Exception) -> None:
    with patch("pr_labels.subprocess.run", side_effect=error), pytest.raises(LabelLookupError):
        fetch_pr_labels("12")


def test_fetch_pr_labels_rejects_invalid_json() -> None:
    with patch("pr_labels.subprocess.run", return_value=MagicMock(stdout="not json")), pytest.raises(LabelLookupError):
        fetch_pr_labels("12")


def test_override_passes_failure_when_label_present(capsys: pytest.CaptureFixture[str]) -> None:
    with patch("pr_labels.subprocess.run", return_value=_gh_result(["other", LABEL])):
        assert apply_label_override(1, LABEL, "12") == 0
    assert f"allowed by the '{LABEL}' label on PR #12" in capsys.readouterr().out


def test_override_keeps_failure_without_label() -> None:
    with patch("pr_labels.subprocess.run", return_value=_gh_result(["other"])):
        assert apply_label_override(1, LABEL, "12") == 1


def test_override_skips_lookup_when_gate_passed() -> None:
    with patch("pr_labels.subprocess.run") as run:
        assert apply_label_override(0, LABEL, "12") == 0
    run.assert_not_called()


def test_override_skips_lookup_without_pr_number(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("PR_NUMBER", raising=False)
    with patch("pr_labels.subprocess.run") as run:
        assert apply_label_override(1, LABEL) == 1
    run.assert_not_called()


def test_override_reads_pr_number_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PR_NUMBER", "34")
    with patch("pr_labels.subprocess.run", return_value=_gh_result([LABEL])) as run:
        assert apply_label_override(1, LABEL) == 0
    assert "34" in run.call_args.args[0]


def test_override_keeps_failure_when_lookup_fails(capsys: pytest.CaptureFixture[str]) -> None:
    with patch("pr_labels.subprocess.run", side_effect=FileNotFoundError()):
        assert apply_label_override(1, LABEL, "12") == 1
    assert "could not read labels for PR #12" in capsys.readouterr().err
