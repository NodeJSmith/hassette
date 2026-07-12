"""Characterization tests for tools/check_file_size.py.

These pin the guard's observable behavior — which files are flagged, at which
line count, and which annotations exempt them — so the detection internals can
be reworked without changing what the guard reports.
"""

from collections.abc import Callable
from pathlib import Path

import pytest
from check_file_size import check_file

# Each case: (id, source, expected violations as [(lineno, message), ...]).
CASES: list[tuple[str, str, list[tuple[int, str]]]] = [
    (
        "short_file_not_flagged",
        "x = 1\n" * 10,
        [],
    ),
    (
        "exactly_800_not_flagged",
        "x = 1\n" * 800,
        [],
    ),
    (
        "over_800_flagged",
        "x = 1\n" * 801,
        [(1, "801 lines (threshold: 800)")],
    ),
    (
        "exempt_file_not_flagged",
        "# file-size-exempt: tracking in #123\n" + "x = 1\n" * 900,
        [],
    ),
    (
        "empty_annotation_not_exempt",
        "# file-size-exempt:\n" + "x = 1\n" * 900,
        [(1, "901 lines (threshold: 800)")],
    ),
]


@pytest.mark.parametrize(("source", "expected"), [(c[1], c[2]) for c in CASES], ids=[c[0] for c in CASES])
def test_guard_behavior(write_sample: Callable[[str], Path], source: str, expected: list[tuple[int, str]]) -> None:
    target = write_sample(source)
    assert check_file(target) == expected
