"""A harness whose startup fails partway must restore the process-global state it already changed (#4259).

``HassetteHarness.start()`` swaps the loop's task factory, configures the ``date_utils`` timezone and
(for a bare harness) sets ``HASSETTE_INSTANCE`` before ``start_children_and_wait`` can time out. When
that raises, both ``AppTestHarness`` and a bare ``async with HassetteHarness(...)`` must still undo it,
or the leak breaks later tests on the same worker.
"""

import asyncio
from pathlib import Path
from unittest.mock import patch

import pytest

import hassette.utils.date_utils as date_utils
from hassette import context
from hassette.app import App
from hassette.testing import AppTestHarness, HassetteHarness, make_test_config


class _PartialStartApp(App):
    """App whose harness never gets far enough to instantiate it."""


async def _fail_start(*_args: object, **_kwargs: object) -> None:
    raise TimeoutError("children never became ready")


def _global_state() -> tuple[object, object, object]:
    return (
        asyncio.get_running_loop().get_task_factory(),
        date_utils._configured_tz,
        context.HASSETTE_INSTANCE.get(None),
    )


async def test_app_harness_restores_globals_when_start_fails(tmp_path: Path) -> None:
    before = _global_state()

    with (
        patch("hassette.testing._harness.start_children_and_wait", _fail_start),
        pytest.raises(TimeoutError, match="never became ready"),
    ):
        async with AppTestHarness(_PartialStartApp, config={}, tmp_path=tmp_path):
            pytest.fail("harness should not have started")

    assert _global_state() == before


async def test_bare_harness_restores_globals_when_start_fails(tmp_path: Path) -> None:
    before = _global_state()
    harness = HassetteHarness(make_test_config(data_dir=tmp_path, timezone="Pacific/Chatham")).with_bus()

    with (
        patch("hassette.testing._harness.start_children_and_wait", _fail_start),
        pytest.raises(TimeoutError, match="never became ready"),
    ):
        async with harness:
            pytest.fail("harness should not have started")

    assert _global_state() == before
