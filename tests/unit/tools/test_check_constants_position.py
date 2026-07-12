"""Characterization tests for tools/check_constants_position.py.

These pin the guard's observable behavior — which UPPER_CASE module constants are
flagged as misplaced after the first class/function, which are auto-exempted because
they reference an earlier-defined name, and which are exempted via the
``# constant-after-def:`` annotation — so the detection internals can be reworked
without changing what the guard reports.
"""

from collections.abc import Callable
from pathlib import Path

import pytest
from check_constants_position import check_file

# Each case: (id, source, expected violations as [(lineno, statement text), ...]).
CASES: list[tuple[str, str, list[tuple[int, str]]]] = [
    (
        "no_defs_not_flagged",
        """\
        FOO = 1
        BAR = 2
        """,
        [],
    ),
    (
        "constant_before_def_not_flagged",
        """\
        FOO = 1


        class C:
            pass
        """,
        [],
    ),
    (
        "constant_after_def_flagged",
        """\
        class C:
            pass


        FOO = 1
        """,
        [(5, "FOO = 1")],
    ),
    (
        "constant_referencing_earlier_class_exempt",
        """\
        class MyEnum:
            VALUE = "value"


        DEFAULT = MyEnum.VALUE
        """,
        [],
    ),
    (
        "constant_referencing_earlier_function_exempt",
        """\
        def compute():
            return 1


        RESULT = compute()
        """,
        [],
    ),
    (
        "constant_with_annotation_exempt",
        """\
        class C:
            pass


        FOO = 1  # constant-after-def: legacy placement
        """,
        [],
    ),
    (
        "empty_annotation_not_exempt",
        """\
        class C:
            pass


        FOO = 1  # constant-after-def:
        """,
        [(5, "FOO = 1  # constant-after-def:")],
    ),
    (
        "dunder_not_flagged",
        """\
        class C:
            pass


        __all__ = ["C"]
        """,
        [],
    ),
    (
        "lowercase_not_flagged",
        """\
        class C:
            pass


        my_var = 1
        """,
        [],
    ),
    (
        "single_char_not_flagged",
        """\
        class C:
            pass


        X = 1
        """,
        [],
    ),
    (
        "annotated_assign_flagged",
        """\
        class C:
            pass


        FOO: int = 1
        """,
        [(5, "FOO: int = 1")],
    ),
    (
        "frozenset_wrapping_earlier_enum_exempt",
        """\
        class Status:
            DONE = 1


        TERMINAL = frozenset({Status.DONE})
        """,
        [],
    ),
    (
        "annotation_referencing_earlier_class_exempt",
        """\
        class Handle:
            pass


        HANDLE_VAR: dict[str, Handle] = {}
        """,
        [],
    ),
    (
        "constant_referencing_earlier_constant_exempt",
        """\
        def build():
            return (1, 2)


        _COLUMNS = build()
        _INSERT_SQL = f"INSERT ({_COLUMNS})"
        """,
        [],
    ),
]


@pytest.mark.parametrize(("source", "expected"), [(c[1], c[2]) for c in CASES], ids=[c[0] for c in CASES])
def test_guard_behavior(write_sample: Callable[[str], Path], source: str, expected: list[tuple[int, str]]) -> None:
    assert check_file(write_sample(source)) == expected
