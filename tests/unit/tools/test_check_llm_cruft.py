"""Characterization tests for tools/check_llm_cruft.py.

Pin which AI-writing tells the guard reports (section dividers, filler phrases)
and which ordinary prose it leaves alone.
"""

from collections.abc import Callable
from pathlib import Path

import pytest
from check_llm_cruft import check_file, iter_paths


def kinds(findings: list[tuple[int, str]]) -> list[str]:
    """Return just the short kind of each finding ('divider' or 'filler')."""
    kinds_out: list[str] = []
    for _, finding in findings:
        if "divider" in finding:
            kinds_out.append("divider")
            continue
        if "filler" in finding:
            kinds_out.append("filler")
            continue
        raise AssertionError(f"Unexpected finding format: {finding!r}")
    return kinds_out


def test_pure_rule_divider_flagged(write_sample: Callable[[str], Path]) -> None:
    assert kinds(check_file(write_sample("# ----------------------------\nx = 1\n"))) == ["divider"]


def test_wrapped_label_divider_flagged(write_sample: Callable[[str], Path]) -> None:
    assert kinds(check_file(write_sample("# ----- Error details -----\nx = 1\n"))) == ["divider"]


def test_hash_and_equals_dividers_flagged(write_sample: Callable[[str], Path]) -> None:
    assert kinds(check_file(write_sample("# ======\n# ######\nx = 1\n"))) == ["divider", "divider"]


def test_short_dash_run_not_flagged(write_sample: Callable[[str], Path]) -> None:
    # 3 dashes is below the {4,} rule threshold; an em-dash comment is normal prose.
    assert check_file(write_sample("x = 1  # foo - bar baz\n")) == []


def test_bare_three_dash_rule_not_flagged(write_sample: Callable[[str], Path]) -> None:
    # A bare '# ---' (3 chars) is below the rule floor — a writer's light separator.
    assert check_file(write_sample("# ---\nx = 1\n")) == []


def test_three_dash_wrapped_label_flagged(write_sample: Callable[[str], Path]) -> None:
    # But a 3-char fence AROUND a label is unambiguously a section header.
    assert kinds(check_file(write_sample("# --- Helpers ---\nx = 1\n"))) == ["divider"]


def test_ordinary_comment_not_flagged(write_sample: Callable[[str], Path]) -> None:
    assert check_file(write_sample("# resolve the owner app from the confirmed app_key\nx = 1\n")) == []


@pytest.mark.parametrize(
    "phrase",
    [
        "in order to",
        "it is important to note",
        "due to the fact that",
        "we leverage the bus",
        "utilize the cache",
        "to facilitate lookups",
    ],
)
def test_filler_phrase_flagged_in_comment(write_sample: Callable[[str], Path], phrase: str) -> None:
    assert kinds(check_file(write_sample(f"# {phrase}\nx = 1\n"))) == ["filler"]


def test_filler_flagged_in_docstring(write_sample: Callable[[str], Path]) -> None:
    assert kinds(check_file(write_sample('"""We leverage the pool in order to batch."""\n'))) == ["filler", "filler"]


def test_filler_case_insensitive(write_sample: Callable[[str], Path]) -> None:
    assert kinds(check_file(write_sample("# In Order To do the thing\nx = 1\n"))) == ["filler"]


def test_filler_not_in_data_string(write_sample: Callable[[str], Path]) -> None:
    # String literals are data, not prose — not scanned.
    assert check_file(write_sample('label = "in order to proceed"\n')) == []


@pytest.mark.parametrize("path", iter_paths(), ids=lambda p: str(p))
def test_real_repo_files_pass(path: Path) -> None:
    """The guard must stay green on the actual repo files it polices."""
    assert check_file(path) == []
