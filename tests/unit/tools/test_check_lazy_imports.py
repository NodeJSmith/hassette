"""Characterization tests for tools/check_lazy_imports.py.

These pin the guard's observable behavior — which imports are flagged, at which
line numbers, and which annotations exempt them — so the detection internals can
be reworked without changing what the guard reports.
"""

import textwrap
from pathlib import Path

import pytest
from check_lazy_imports import check_file, iter_paths


def run(tmp_path: Path, content: str) -> list[tuple[int, str]]:
    """Write content to a temp file and return the guard's violations."""
    target = tmp_path / "sample.py"
    target.write_text(textwrap.dedent(content))
    return check_file(target)


# Each case: (id, source, expected violations as [(lineno, import_text), ...]).
CASES: list[tuple[str, str, list[tuple[int, str]]]] = [
    (
        "module_level_not_flagged",
        "import os\nfrom pathlib import Path\n",
        [],
    ),
    (
        "function_body_import_flagged",
        """\
        def f():
            import os
            return os
        """,
        [(2, "import os")],
    ),
    (
        "function_body_from_import_flagged",
        """\
        def f():
            from pathlib import Path
            return Path
        """,
        [(2, "from pathlib import Path")],
    ),
    (
        "async_function_body_flagged",
        """\
        async def f():
            import json
            return json
        """,
        [(2, "import json")],
    ),
    (
        "method_body_flagged",
        """\
        class C:
            def m(self):
                import os
                return os
        """,
        [(3, "import os")],
    ),
    (
        "nested_function_flagged",
        """\
        def outer():
            def inner():
                import os
                return os
            return inner
        """,
        [(3, "import os")],
    ),
    (
        "exempt_same_line",
        """\
        def f():
            import os  # lazy-import: break circular import with thing
            return os
        """,
        [],
    ),
    (
        "exempt_preceding_comment",
        """\
        def f():
            # lazy-import: break circular import with thing
            import os
            return os
        """,
        [],
    ),
    (
        "empty_annotation_does_not_exempt",
        """\
        def f():
            import os  # lazy-import:
            return os
        """,
        [(2, "import os  # lazy-import:")],
    ),
    (
        "module_level_type_checking_not_flagged",
        """\
        from typing import TYPE_CHECKING

        if TYPE_CHECKING:
            from collections.abc import Iterator
        """,
        [],
    ),
    (
        "multiline_import_exempt_on_continuation",
        """\
        def f():
            from pathlib import (
                Path,  # lazy-import: break circular import with thing
            )
            return Path
        """,
        [],
    ),
]


@pytest.mark.parametrize(("source", "expected"), [(c[1], c[2]) for c in CASES], ids=[c[0] for c in CASES])
def test_guard_behavior(tmp_path: Path, source: str, expected: list[tuple[int, str]]) -> None:
    assert run(tmp_path, source) == expected


@pytest.mark.parametrize("path", iter_paths(), ids=lambda p: str(p))
def test_real_src_files_pass(path: Path) -> None:
    """The guard must stay green on the actual repo files it polices."""
    assert check_file(path) == []
