"""Characterization tests for tools/check_spec_tokens.py.

These pin which leaked spec-artifact tokens the guard reports — and, just as
importantly, which look-alike tokens it leaves alone (clock times, single-digit
type-var-ish tokens, and tokens that live in data string literals rather than
comments or docstrings).
"""

from collections.abc import Callable
from pathlib import Path

import pytest
from check_spec_tokens import check_file, check_filename, iter_paths

# Each case: (id, source, expected violations as [(lineno, token), ...]).
CASES: list[tuple[str, str, list[tuple[int, str]]]] = [
    (
        "comment_task_id_flagged",
        "x = 1  # T05 persistence invariant\n",
        [(1, "T05")],
    ),
    (
        "comment_ac_fr_nfr_wp_flagged",
        "# see AC1, FR2, NFR3 and WP04\n",
        [(1, "AC1"), (1, "FR2"), (1, "NFR3"), (1, "WP04")],
    ),
    (
        "comment_hash_form_flagged",
        "# see FR#6, AC#10 and NFR#3\n",
        [(1, "AC#10"), (1, "FR#6"), (1, "NFR#3")],
    ),
    (
        "docstring_hash_form_flagged",
        '"""Enablement logic (FR#6, AC#10)."""\n',
        [(1, "AC#10"), (1, "FR#6")],
    ),
    (
        "module_docstring_flagged",
        '"""Module structured for T05 persistence."""\n',
        [(1, "T05")],
    ),
    (
        "function_docstring_flagged",
        """\
        def f():
            \"\"\"Consumed by T06 at the timeout site.\"\"\"
            return 1
        """,
        [(2, "T06")],
    ),
    (
        "iso_time_in_comment_not_flagged",
        "# parse value + T00:00:00 boundary\n",
        [],
    ),
    (
        "iso_time_in_string_literal_not_flagged",
        'ts = value + "T00:00:00"\n',
        [],
    ),
    (
        "task_id_in_data_string_not_flagged",
        'label = "process T05 now"\n',
        [],
    ),
    (
        "single_digit_t_not_flagged",
        "# generic over T1 and T2\n",
        [],
    ),
    (
        "lowercase_words_not_flagged",
        "# the frame factor for the actor\n",
        [],
    ),
    (
        "embedded_token_not_flagged",
        "# the BAT05 register and ATC1 pin\n",
        [],
    ),
]


@pytest.mark.parametrize(("source", "expected"), [(c[1], c[2]) for c in CASES], ids=[c[0] for c in CASES])
def test_guard_behavior(write_sample: Callable[[str], Path], source: str, expected: list[tuple[int, str]]) -> None:
    assert check_file(write_sample(source)) == expected


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("normal_module.py", []),
        ("T05_notes.py", ["T05"]),
        ("design_AC1.md", ["AC1"]),
        ("test_t1_helpers.py", []),  # single digit — T\d{2,} requires 2+ digits
        ("test_t03_x.py", ["t03"]),  # lowercase 2-digit task-ID segment must be flagged
    ],
)
def test_filename_check(tmp_path: Path, name: str, expected: list[str]) -> None:
    assert check_filename(tmp_path / name) == expected


@pytest.mark.parametrize("path", iter_paths(), ids=lambda p: str(p))
def test_real_repo_files_pass(path: Path) -> None:
    """The guard must stay green on the actual repo files it polices."""
    assert check_file(path) == []
    assert check_filename(path) == []


def test_task_label_colon_flagged(write_sample: Callable[[str], Path]) -> None:
    """A task ID followed by a planning-label colon (not a clock digit) must be caught."""
    assert check_file(write_sample("# T05: Saturation handling\n")) == [(1, "T05")]


def test_sub_criterion_letter_flagged(write_sample: Callable[[str], Path]) -> None:
    """A criterion token with a trailing lowercase letter must be caught."""
    assert check_file(write_sample("# see AC#6a for details\n")) == [(1, "AC#6a")]


def test_clock_time_in_data_string_not_flagged(write_sample: Callable[[str], Path]) -> None:
    """A real HH:MM:SS timestamp in a string literal must not be flagged."""
    assert check_file(write_sample('value = "2020-01-01T05:30:00"\n')) == []


def test_clock_time_in_comment_not_flagged_tightened(write_sample: Callable[[str], Path]) -> None:
    """A real clock time (colon+digit) in a comment must not be flagged."""
    assert check_file(write_sample("# parse value + T05:30 boundary\n")) == []
