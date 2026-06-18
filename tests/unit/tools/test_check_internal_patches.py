"""Characterization tests for tools/check_internal_patches.py.

These pin the guard's observable behavior — which sites are flagged, at which
line numbers, with which symbol, and which annotations exempt them — so the
detection internals can be reworked without changing what the guard reports.
"""

import textwrap
from pathlib import Path

import pytest
from check_internal_patches import IN_SCOPE_FILES, check_file


def run(tmp_path: Path, content: str) -> list[tuple[int, str]]:
    """Write content to a temp file and return the guard's violations."""
    target = tmp_path / "sample_test.py"
    target.write_text(textwrap.dedent(content))
    return check_file(target)


# Each case: (id, source, expected violations as [(lineno, symbol), ...]).
CASES: list[tuple[str, str, list[tuple[int, str]]]] = [
    (
        "direct_assign_flagged",
        "state_proxy.load_cache = AsyncMock()\n",
        [(1, "load_cache")],
    ),
    (
        "direct_assign_exempt_same_line",
        "state_proxy.load_cache = AsyncMock()  # boundary-exempt: collaborator of x\n",
        [],
    ),
    (
        "annotated_assign_flagged",
        "state_proxy.load_cache: AsyncMock = AsyncMock()\n",
        [(1, "load_cache")],
    ),
    (
        "non_service_receiver_not_flagged",
        "app1.mark_ready = Mock()\n",
        [],
    ),
    (
        "patch_object_flagged",
        'patch.object(state_proxy, "load_cache")\n',
        [(1, "load_cache")],
    ),
    (
        "monkeypatch_setattr_flagged",
        'monkeypatch.setattr(ws, "dispatch")\n',
        [(1, "dispatch")],
    ),
    (
        "monkeypatch_setattr_keyword_flagged",
        'monkeypatch.setattr(ws, name="dispatch")\n',
        [(1, "dispatch")],
    ),
    (
        "patch_object_keyword_flagged",
        'patch.object(state_proxy, attribute="load_cache")\n',
        [(1, "load_cache")],
    ),
    (
        "patch_string_form_flagged",
        'patch("hassette.core.websocket_service.WebsocketService.dispatch")\n',
        [(1, "dispatch")],
    ),
    (
        "patch_string_partial_segment_not_flagged",
        'patch("hassette.core.connect_ws_helper")\n',
        [],
    ),
    (
        "multiline_patch_object_flagged_at_opener",
        """\
        with patch.object(
            websocket_service,
            "dispatch",
        ):
            pass
        """,
        [(1, "dispatch")],
    ),
    (
        "multiline_patch_object_exempt_continuation",
        """\
        with patch.object(
            websocket_service,
            "dispatch",  # boundary-exempt: collaborator of x
        ):
            pass
        """,
        [],
    ),
    (
        "preceding_comment_exempt",
        """\
        # boundary-exempt: collaborator of load_cache
        state_proxy.load_cache = AsyncMock()
        """,
        [],
    ),
    (
        "comparison_not_flagged",
        "assert state_proxy.mark_ready == something\n",
        [],
    ),
    (
        "excluded_symbol_spawn_not_flagged",
        "task_bucket.spawn = Mock()\n",
        [],
    ),
    (
        "plain_attribute_call_not_flagged",
        "result = websocket_service.dispatch()\n",
        [],
    ),
]


@pytest.mark.parametrize(("source", "expected"), [(c[1], c[2]) for c in CASES], ids=[c[0] for c in CASES])
def test_guard_behavior(tmp_path: Path, source: str, expected: list[tuple[int, str]]) -> None:
    assert run(tmp_path, source) == expected


@pytest.mark.parametrize("path", IN_SCOPE_FILES, ids=lambda p: p.name)
def test_real_in_scope_files_pass(path: Path) -> None:
    """The guard must stay green on the actual repo files it polices."""
    assert check_file(path) == []
