"""Every example app in ``examples/`` must initialize against the current framework.

The examples are user-facing documentation, and nothing else imports them, so a framework API change
(e.g. a newly required ``name=`` on a registration) would otherwise break them silently. Each
``examples/*.py`` file is discovered at collection time, so a new example is covered with no test change.
"""

import importlib.util
import inspect
import sys
from pathlib import Path
from types import ModuleType

import pytest

from hassette import App
from hassette.testing import AppTestHarness

EXAMPLES_DIR = Path(__file__).resolve().parents[2] / "examples"
EXAMPLE_FILES = sorted(EXAMPLES_DIR.glob("*.py"))


def load_example_module(path: Path, monkeypatch: pytest.MonkeyPatch) -> ModuleType:
    """Import an example file under a private module name, registered in ``sys.modules`` for the test only."""
    module_name = f"hassette_examples.{path.stem}"
    spec = importlib.util.spec_from_file_location(module_name, path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    # Registered before exec so source inspection (used for config/annotation resolution) can find it.
    monkeypatch.setitem(sys.modules, module_name, module)
    spec.loader.exec_module(module)
    return module


def app_classes_in(module: ModuleType) -> list[type[App]]:
    return [
        cls
        for _, cls in inspect.getmembers(module, inspect.isclass)
        if issubclass(cls, App) and cls.__module__ == module.__name__
    ]


def capturing_initialize_errors(app_cls: type[App], errors: list[BaseException]) -> type[App]:
    """Subclass ``app_cls`` so an exception raised by ``on_initialize`` is recorded before it propagates.

    The harness reports an initialization failure only as a timeout waiting for RUNNING; the recorded
    exception is what names the registration that failed.
    """

    class Capturing(app_cls):  # pyright: ignore[reportGeneralTypeIssues, reportUntypedBaseClass]
        async def on_initialize(self) -> None:
            try:
                await super().on_initialize()
            except Exception as exc:
                errors.append(exc)
                raise

    Capturing.__name__ = app_cls.__name__
    Capturing.__qualname__ = app_cls.__qualname__
    return Capturing


def test_examples_discovered() -> None:
    assert EXAMPLE_FILES, f"no example apps found in {EXAMPLES_DIR}"


@pytest.mark.parametrize("example_path", EXAMPLE_FILES, ids=[path.name for path in EXAMPLE_FILES])
async def test_example_app_initializes(example_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    module = load_example_module(example_path, monkeypatch)
    app_classes = app_classes_in(module)
    assert app_classes, f"examples/{example_path.name} defines no App subclass"

    for app_cls in app_classes:
        errors: list[BaseException] = []
        try:
            async with AppTestHarness(capturing_initialize_errors(app_cls, errors)):
                pass
        except Exception as exc:
            cause = errors[0] if errors else exc
            raise AssertionError(
                f"examples/{example_path.name}: {app_cls.__name__} failed to initialize: "
                f"{type(cause).__name__}: {cause}"
            ) from cause
