"""Characterization tests for tools/check_exception_names.py.

These pin the guard's observable behavior — which bound exception names are
flagged and at which line numbers — so the detection internals can be reworked
without changing what the guard reports.
"""

from collections.abc import Callable
from pathlib import Path

import pytest
from check_exception_names import check_file

# Each case: (id, source, expected violations as [(lineno, handler_text), ...]).
CASES: list[tuple[str, str, list[tuple[int, str]]]] = [
    (
        "except_no_binding_not_flagged",
        """\
        try:
            pass
        except ValueError:
            pass
        """,
        [],
    ),
    (
        "except_as_exc_not_flagged",
        """\
        try:
            pass
        except ValueError as exc:
            pass
        """,
        [],
    ),
    (
        "except_as_retry_exc_not_flagged",
        """\
        try:
            pass
        except ValueError as retry_exc:
            pass
        """,
        [],
    ),
    (
        "except_as_e_flagged",
        """\
        try:
            pass
        except ValueError as e:
            pass
        """,
        [(3, "except ValueError as e:")],
    ),
    (
        "except_as_ex_flagged",
        """\
        try:
            pass
        except ValueError as ex:
            pass
        """,
        [(3, "except ValueError as ex:")],
    ),
    (
        "except_as_err_flagged",
        """\
        try:
            pass
        except ValueError as err:
            pass
        """,
        [(3, "except ValueError as err:")],
    ),
    (
        "except_as_error_flagged",
        """\
        try:
            pass
        except ValueError as error:
            pass
        """,
        [(3, "except ValueError as error:")],
    ),
    (
        "bare_except_as_e_flagged",
        """\
        try:
            pass
        except Exception as e:
            pass
        """,
        [(3, "except Exception as e:")],
    ),
    (
        "multiple_handlers",
        """\
        try:
            pass
        except ValueError as exc:
            pass
        except TypeError as e:
            pass
        """,
        [(5, "except TypeError as e:")],
    ),
    (
        "nested_try_flagged",
        """\
        def f():
            try:
                pass
            except ValueError as e:
                pass
        """,
        [(4, "except ValueError as e:")],
    ),
    (
        "docstring_example_not_flagged",
        '''\
        def f():
            """Do a thing.

            Example: except X as e: is what NOT to do.
            """
        ''',
        [],
    ),
]


@pytest.mark.parametrize(("source", "expected"), [(c[1], c[2]) for c in CASES], ids=[c[0] for c in CASES])
def test_guard_behavior(write_sample: Callable[[str], Path], source: str, expected: list[tuple[int, str]]) -> None:
    assert check_file(write_sample(source)) == expected
