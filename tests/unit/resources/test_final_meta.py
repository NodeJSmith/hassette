"""Tests for FinalMeta's @final override check."""

import importlib
import sys
from pathlib import Path

import pytest

from hassette.app.app import AppSync
from hassette.exceptions import CannotOverrideFinalError
from hassette.resources.base import Resource

LEGAL_SOURCE = """
from hassette.resources.base import Resource


class ReloadedResource(Resource):
    pass
"""

ILLEGAL_SOURCE = """
from hassette.resources.base import Resource


class ReloadedResource(Resource):
    async def initialize(self) -> None:
        pass
"""


def test_reloaded_module_with_final_override_raises(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A reloaded class gets the same check as a freshly imported one."""
    module_name = "finalmeta_reload_probe"
    module_file = tmp_path / f"{module_name}.py"
    module_file.write_text(LEGAL_SOURCE)
    monkeypatch.syspath_prepend(str(tmp_path))
    monkeypatch.setattr(sys, "dont_write_bytecode", True)

    try:
        module = importlib.import_module(module_name)
        module_file.write_text(ILLEGAL_SOURCE)
        importlib.invalidate_caches()

        with pytest.raises(CannotOverrideFinalError):
            importlib.reload(module)
    finally:
        sys.modules.pop(module_name, None)


def test_same_qualname_redefined_is_checked_each_time() -> None:
    """Redefining a class under an already-seen qualname still runs the check."""

    def define() -> None:
        class _Bad(Resource):  # pyright: ignore[reportUnusedClass]
            async def shutdown(self) -> None:  # pyright: ignore[reportIncompatibleMethodOverride]
                pass

    for _ in range(2):
        with pytest.raises(CannotOverrideFinalError):
            define()


def test_suggestion_points_to_on_hook() -> None:
    """Overriding a non-hook final method suggests its on_ hook."""
    with pytest.raises(CannotOverrideFinalError) as exc_info:

        class _BadInit(Resource):  # pyright: ignore[reportUnusedClass]
            async def initialize(self) -> None:  # pyright: ignore[reportIncompatibleMethodOverride]
                pass

    assert exc_info.value.suggestion == "Use 'on_initialize' instead."


def test_overriding_final_on_hook_offers_no_suggestion() -> None:
    """Overriding a final on_* hook doesn't suggest the same forbidden name."""
    with pytest.raises(CannotOverrideFinalError) as exc_info:

        class _BadHook(AppSync):  # pyright: ignore[reportUnusedClass]
            async def on_initialize(self) -> None:  # pyright: ignore[reportIncompatibleMethodOverride]
                pass

    assert exc_info.value.suggestion is None
