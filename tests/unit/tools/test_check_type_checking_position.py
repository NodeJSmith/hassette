"""Characterization tests for tools/check_type_checking_position.py.

These pin the guard's observable behavior — which ``if TYPE_CHECKING:`` blocks
are flagged, at which line numbers, and which positions are considered
correct — so the detection internals can be reworked without changing what
the guard reports.
"""

from collections.abc import Callable
from pathlib import Path

import pytest
from check_type_checking_position import check_file

# Each case: (id, source, expected violations as [(lineno, message), ...]).
CASES: list[tuple[str, str, list[tuple[int, str]]]] = [
    (
        "no_type_checking_block",
        """\
        import os
        from pathlib import Path
        """,
        [],
    ),
    (
        "type_checking_at_end",
        """\
        import os
        from typing import TYPE_CHECKING

        if TYPE_CHECKING:
            from pathlib import Path


        class C:
            pass
        """,
        [],
    ),
    (
        "type_checking_between_imports",
        """\
        import os
        from typing import TYPE_CHECKING

        if TYPE_CHECKING:
            from pathlib import Path

        import sys
        """,
        [(4, "if TYPE_CHECKING: block at line 4 followed by imports at line 7")],
    ),
    (
        "typing_dot_type_checking",
        """\
        import os
        import typing

        if typing.TYPE_CHECKING:
            from pathlib import Path

        import sys
        """,
        [(4, "if TYPE_CHECKING: block at line 4 followed by imports at line 7")],
    ),
    (
        "type_checking_followed_by_class_not_flagged",
        """\
        from typing import TYPE_CHECKING

        if TYPE_CHECKING:
            from pathlib import Path


        class C:
            pass
        """,
        [],
    ),
    (
        "multiple_type_checking_blocks",
        """\
        import os
        from typing import TYPE_CHECKING

        if TYPE_CHECKING:
            from pathlib import Path

        import sys

        if TYPE_CHECKING:
            from collections.abc import Iterator


        class C:
            pass
        """,
        [(4, "if TYPE_CHECKING: block at line 4 followed by imports at line 7")],
    ),
]


@pytest.mark.parametrize(("source", "expected"), [(c[1], c[2]) for c in CASES], ids=[c[0] for c in CASES])
def test_guard_behavior(write_sample: Callable[[str], Path], source: str, expected: list[tuple[int, str]]) -> None:
    assert check_file(write_sample(source)) == expected
