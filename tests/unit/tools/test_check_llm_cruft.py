"""Characterization tests for tools/check_llm_cruft.py.

Pin which AI-writing tells the guard reports (section dividers, filler phrases)
and which ordinary prose it leaves alone.
"""

import textwrap
from pathlib import Path

import pytest
from check_llm_cruft import check_file, iter_paths


def run(tmp_path: Path, content: str) -> list[tuple[int, str]]:
    """Write content to a temp file and return the guard's findings."""
    target = tmp_path / "sample.py"
    target.write_text(textwrap.dedent(content))
    return check_file(target)


def codes(tmp_path: Path, content: str) -> list[str]:
    """Return just the short kind of each finding ('divider' or 'filler')."""
    return ["divider" if "divider" in f else "filler" for _, f in run(tmp_path, content)]


def test_pure_rule_divider_flagged(tmp_path: Path) -> None:
    assert codes(tmp_path, "# ----------------------------\nx = 1\n") == ["divider"]


def test_wrapped_label_divider_flagged(tmp_path: Path) -> None:
    assert codes(tmp_path, "# ----- Error details -----\nx = 1\n") == ["divider"]


def test_hash_and_equals_dividers_flagged(tmp_path: Path) -> None:
    assert codes(tmp_path, "# ======\n# ######\nx = 1\n") == ["divider", "divider"]


def test_short_dash_run_not_flagged(tmp_path: Path) -> None:
    # 3 dashes is below the {4,} rule threshold; an em-dash comment is normal prose.
    assert run(tmp_path, "x = 1  # foo - bar baz\n") == []


def test_bare_three_dash_rule_not_flagged(tmp_path: Path) -> None:
    # A bare '# ---' (3 chars) is below the rule floor — a writer's light separator.
    assert run(tmp_path, "# ---\nx = 1\n") == []


def test_three_dash_wrapped_label_flagged(tmp_path: Path) -> None:
    # But a 3-char fence AROUND a label is unambiguously a section header.
    assert codes(tmp_path, "# --- Helpers ---\nx = 1\n") == ["divider"]


def test_ordinary_comment_not_flagged(tmp_path: Path) -> None:
    assert run(tmp_path, "# resolve the owner app from the confirmed app_key\nx = 1\n") == []


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
def test_filler_phrase_flagged_in_comment(tmp_path: Path, phrase: str) -> None:
    assert codes(tmp_path, f"# {phrase}\nx = 1\n") == ["filler"]


def test_filler_flagged_in_docstring(tmp_path: Path) -> None:
    assert codes(tmp_path, '"""We leverage the pool in order to batch."""\n') == ["filler", "filler"]


def test_filler_case_insensitive(tmp_path: Path) -> None:
    assert codes(tmp_path, "# In Order To do the thing\nx = 1\n") == ["filler"]


def test_filler_not_in_data_string(tmp_path: Path) -> None:
    # String literals are data, not prose — not scanned.
    assert run(tmp_path, 'label = "in order to proceed"\n') == []


@pytest.mark.parametrize("path", iter_paths(), ids=lambda p: str(p))
def test_real_src_files_pass(path: Path) -> None:
    """The guard must stay green on the actual repo files it polices."""
    assert check_file(path) == []
