"""Characterization tests for tools/check_section_dividers.py.

Pins which isolated one-line comments (blank line above and below) the guard flags as
undecorated section dividers — the structural rule (introduces a def/class/decorator) and
the shape rule (1-4 word body) — and which it leaves alone: decorated dividers (HSL001's own
job), pragma-shaped comments, prose ending in sentence punctuation, and trailing remarks with
nothing left in the file to separate from.
"""

from collections.abc import Callable
from pathlib import Path

import pytest
from check_section_dividers import check_file

# Each case: (id, source, expected violations as [(lineno, message), ...]).
CASES: list[tuple[str, str, list[tuple[int, str]]]] = [
    (
        "short_label_before_def_flagged_as_structural",
        """\
        x = 1

        # Helpers

        def foo():
            pass
        """,
        [(3, "undecorated section divider (introduces definition) - '# Helpers'")],
    ),
    (
        "short_label_not_before_def_flagged_as_shape",
        """\
        x = 1

        # some label

        y = 2
        """,
        [(3, "undecorated section divider (short label) - '# some label'")],
    ),
    (
        "longer_label_before_class_flagged_as_structural",
        """\
        x = 1

        # Tier 2 event structure for persistence

        class Foo:
            pass
        """,
        [(3, "undecorated section divider (introduces definition) - '# Tier 2 event structure for persistence'")],
    ),
    (
        "decorator_counts_as_definition",
        """\
        x = 1

        # Route handlers

        @app.get("/x")
        def foo():
            pass
        """,
        [(3, "undecorated section divider (introduces definition) - '# Route handlers'")],
    ),
    (
        "decorated_divider_not_flagged",
        """\
        x = 1

        # --------

        def foo():
            pass
        """,
        [],
    ),
    (
        "decorated_wrapped_divider_not_flagged",
        """\
        x = 1

        # --- Helpers ---

        def foo():
            pass
        """,
        [],
    ),
    (
        "decorated_wrapped_single_char_label_not_flagged",
        """\
        x = 1

        # --- A ---

        def foo():
            pass
        """,
        [],
    ),
    (
        "pragma_todo_not_flagged",
        """\
        x = 1

        # TODO

        def foo():
            pass
        """,
        [],
    ),
    (
        "pragma_fixme_not_flagged",
        """\
        x = 1

        # FIXME

        def foo():
            pass
        """,
        [],
    ),
    (
        "pragma_note_not_flagged",
        """\
        x = 1

        # NOTE

        def foo():
            pass
        """,
        [],
    ),
    (
        "pragma_coverage_directive_not_flagged",
        """\
        x = 1

        # pragma: no cover

        def foo():
            pass
        """,
        [],
    ),
    (
        "pragma_spdx_license_identifier_not_flagged",
        """\
        x = 1

        # SPDX-License-Identifier: MIT

        def foo():
            pass
        """,
        [],
    ),
    (
        "pragma_copyright_notice_not_flagged",
        """\
        x = 1

        # Copyright 2026 Jessica Smith

        def foo():
            pass
        """,
        [],
    ),
    (
        "shebang_not_flagged_even_when_isolated",
        """\
        #!/usr/bin/env python3

        def foo():
            pass
        """,
        [],
    ),
    (
        "encoding_cookie_not_flagged_even_when_isolated",
        """\
        # coding: utf-8

        def foo():
            pass
        """,
        [],
    ),
    (
        "pragma_noqa_not_flagged",
        """\
        x = 1

        # noqa

        def foo():
            pass
        """,
        [],
    ),
    (
        "pragma_dup_ignore_not_flagged",
        """\
        x = 1

        # dup-ignore-marker

        def foo():
            pass
        """,
        [],
    ),
    (
        "pragma_snippet_marker_not_flagged",
        """\
        x = 1

        # --8<-- [end:foo]

        def foo():
            pass
        """,
        [],
    ),
    (
        "sentence_ending_in_period_not_flagged",
        """\
        x = 1

        # This explains something the reader could not infer otherwise.

        class Foo:
            pass
        """,
        [],
    ),
    (
        "long_body_not_flagged_by_structural_rule",
        """\
        x = 1

        # This is a much longer comment that reads like real prose rather than a label

        class Foo:
            pass
        """,
        [],
    ),
    (
        "trailing_comment_on_code_line_not_flagged",
        """\
        x = 1  # Helpers

        def foo():
            pass
        """,
        [],
    ),
    (
        "comment_without_blank_above_not_flagged",
        """\
        x = 1
        # Helpers

        def foo():
            pass
        """,
        [],
    ),
    (
        "comment_without_blank_below_not_flagged",
        """\
        x = 1

        # Helpers
        def foo():
            pass
        """,
        [],
    ),
    (
        "trailing_comment_at_end_of_file_not_flagged",
        """\
        x = 1

        # nothing left to divide from
        """,
        [],
    ),
]


@pytest.mark.parametrize(("_id", "source", "expected"), CASES, ids=[c[0] for c in CASES])
def test_check_file(
    _id: str, source: str, expected: list[tuple[int, str]], write_sample: Callable[[str], Path]
) -> None:
    path = write_sample(source)
    assert check_file(path) == expected
