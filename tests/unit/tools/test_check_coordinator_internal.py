"""Characterization tests for tools/check_coordinator_internal.py.

These pin the guard's observable behavior — which private-attribute accesses on
``hassette_instance`` (and its ``session_manager`` aliases) are flagged, at which line
numbers, and which ``# coordinator-internal`` placements exempt them — so the detection
internals can be reworked without changing what the guard reports.
"""

from collections.abc import Callable
from pathlib import Path

import pytest
from check_coordinator_internal import check_file, discover_files

# Each case: (id, source, expected violations as [(lineno, attr), ...]).
CASES: list[tuple[str, str, list[tuple[int, str]]]] = [
    (
        "direct_assign_flagged",
        "hassette_instance._loop = running_loop\n",
        [(1, "_loop")],
    ),
    (
        "direct_assign_exempt_same_line",
        "hassette_instance._loop = running_loop  # coordinator-internal\n",
        [],
    ),
    (
        "preceding_comment_exempt",
        """\
        # coordinator-internal: no public accessor for the watchdog slot
        assert hassette_instance._loop_watchdog is None
        """,
        [],
    ),
    (
        "session_manager_alias_flagged",
        """\
        sm = hassette_instance.session_manager
        sm._session_id = 42
        """,
        [(2, "_session_id")],
    ),
    (
        "session_manager_alias_exempt",
        """\
        sm = hassette_instance.session_manager
        sm._session_id = 42  # coordinator-internal
        """,
        [],
    ),
    (
        "nested_attribute_chain_flags_only_private_segment",
        """\
        sm = hassette_instance.session_manager
        sm._database_service.db.execute.assert_awaited_once()
        """,
        [(2, "_database_service")],
    ),
    (
        "unrelated_receiver_not_flagged",
        "app1._private_thing = Mock()\n",
        [],
    ),
    (
        "public_attribute_not_flagged",
        "hassette_instance.session_manager.mark_orphaned_sessions.assert_awaited_once()\n",
        [],
    ),
    (
        "string_literal_containing_annotation_not_exempt",
        'assert hassette_instance._loop is None, "hassette_instance._loop # coordinator-internal not real"\n',
        [(1, "_loop")],
    ),
    (
        "fstring_expression_flagged_and_exempt_via_preceding_comment",
        """\
        # coordinator-internal: _loop is set by run_forever() itself
        assert hassette_instance._loop is running_loop, f"mismatch {hassette_instance._loop}"
        """,
        [],
    ),
    (
        "with_statement_flagged",
        """\
        sm = hassette_instance.session_manager
        async def f():
            async with sm._session_lock:
                pass
        """,
        [(3, "_session_lock")],
    ),
]


@pytest.mark.parametrize(("source", "expected"), [(c[1], c[2]) for c in CASES], ids=[c[0] for c in CASES])
def test_guard_behavior(write_sample: Callable[[str], Path], source: str, expected: list[tuple[int, str]]) -> None:
    assert check_file(write_sample(source)) == expected


@pytest.mark.parametrize("path", discover_files(), ids=lambda p: p.name)
def test_real_in_scope_files_pass(path: Path) -> None:
    """The guard must stay green on the actual repo files it polices."""
    assert check_file(path) == []
