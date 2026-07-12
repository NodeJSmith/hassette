"""Characterization tests for tools/check_registration_signatures.py.

These pin the guard's observable behavior — which method signatures are flagged for a
misdeclared ``name`` parameter — so the detection internals can be reworked without
changing what the guard reports.
"""

from collections.abc import Callable
from pathlib import Path

import pytest
from check_registration_signatures import TARGET_FILES, check_file

# Each case: (id, source, expected violations as [(lineno, message), ...]).
CASES: list[tuple[str, str, list[tuple[int, str]]]] = [
    (
        "keyword_only_no_default_not_flagged",
        """\
        class Bus:
            def on_state_change(self, entity_id: str, *, handler, name: str) -> None:
                pass
        """,
        [],
    ),
    (
        "generic_on_method_keyword_only_not_flagged",
        """\
        class Bus:
            def on(self, *, topic: str, handler, name: str) -> None:
                pass
        """,
        [],
    ),
    (
        "name_before_star_flagged",
        """\
        class Bus:
            def on_state_change(self, entity_id: str, name: str, *, handler) -> None:
                pass
        """,
        [(2, "Bus.on_state_change: 'name' parameter must be keyword-only (add '*' before it)")],
    ),
    (
        "name_with_default_flagged",
        """\
        class Scheduler:
            def schedule(self, func, trigger, *, name: str = "job") -> None:
                pass
        """,
        [(2, "Scheduler.schedule: 'name' parameter must not have a default value")],
    ),
    (
        "name_with_none_default_flagged",
        """\
        class Scheduler:
            def schedule(self, func, trigger, *, name: str | None = None) -> None:
                pass
        """,
        [(2, "Scheduler.schedule: 'name' parameter must not have a default value")],
    ),
    (
        "no_name_parameter_not_flagged",
        """\
        class Bus:
            def on_error(self, handler) -> None:
                pass
        """,
        [],
    ),
    (
        "private_method_not_flagged",
        """\
        class Bus:
            def _on_listener_removed(self, listener) -> None:
                pass

            def _private_with_bad_name(self, name: str = "x") -> None:
                pass
        """,
        [],
    ),
    (
        "async_method_checked",
        """\
        class Scheduler:
            async def run_in(self, func, delay, name: str, *, group=None) -> None:
                pass
        """,
        [(2, "Scheduler.run_in: 'name' parameter must be keyword-only (add '*' before it)")],
    ),
]


@pytest.mark.parametrize(("source", "expected"), [(c[1], c[2]) for c in CASES], ids=[c[0] for c in CASES])
def test_guard_behavior(write_sample: Callable[[str], Path], source: str, expected: list[tuple[int, str]]) -> None:
    assert check_file(write_sample(source)) == expected


@pytest.mark.parametrize("path", TARGET_FILES, ids=lambda p: str(p))
def test_real_repo_files_pass(path: Path) -> None:
    """The guard must stay green on the actual Bus/Scheduler source it polices."""
    assert check_file(path) == []
