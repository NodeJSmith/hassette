"""How ``load_app_class`` imports, caches, and re-imports app modules (spec 161)."""

import logging
import os
import py_compile
import sys
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from unittest.mock import patch

import pytest

from hassette.testing import make_test_config
from hassette.utils import app_utils
from hassette.utils.app_utils import cached_class, cached_load_error, load_app_class
from tests.support.app_staging_helpers import clear_loaded_class_caches, new_unique_app_dir
from tests.support.helpers import write_app

TWO_APPS_SOURCE = """
from pathlib import Path

from hassette import App

with Path({runs!r}).open("a") as f:
    f.write("x")

VALUE = {value}


class FirstApp(App):
    pass


class SecondApp(App):
    pass
"""

FAILING_SOURCE = """
from pathlib import Path

with Path({runs!r}).open("a") as f:
    f.write("x")

raise RuntimeError("module-level failure")
"""

NOT_A_CLASS_SOURCE = """
def not_an_app():
    return None
"""


@dataclass
class AppSandbox:
    """A unique apps package in a temp dir, with a file each test module's top-level code appends to."""

    app_dir: Path
    pkg_name: str
    runs_file: Path
    config: object

    def write(self, filename: str, source: str, **fields: object) -> Path:
        return write_app(self.app_dir, filename, source.format(runs=str(self.runs_file), **fields))

    def load(self, module_path: Path, class_name: str, *, force_reload: bool = False):
        return load_app_class(
            self.app_dir,
            module_path,
            class_name,
            config=self.config,  # pyright: ignore[reportArgumentType]
            force_reload=force_reload,
        )

    def runs(self) -> int:
        """How many times a module's top-level code ran: each run appends one ``x`` to the runs file."""
        return len(self.runs_file.read_text()) if self.runs_file.exists() else 0


@pytest.fixture
def sandbox(tmp_path: Path) -> Iterator[AppSandbox]:
    pkg_name, app_dir = new_unique_app_dir(tmp_path)
    config = make_test_config(data_dir=tmp_path, apps={"directory": app_dir})
    yield AppSandbox(app_dir=app_dir, pkg_name=pkg_name, runs_file=tmp_path / "runs.txt", config=config)
    clear_loaded_class_caches(under=app_dir)
    sys.modules.pop(pkg_name, None)


def test_class_name_naming_a_function_raises_not_a_subclass_and_caches_the_failure(sandbox: AppSandbox) -> None:
    module_path = sandbox.write("function_app.py", NOT_A_CLASS_SOURCE)

    with pytest.raises(TypeError, match="not a subclass of App or AppSync") as first:
        sandbox.load(module_path, "not_an_app")
    with pytest.raises(TypeError) as second:
        sandbox.load(module_path, "not_an_app")

    assert second.value is first.value
    assert cached_load_error(module_path, "not_an_app") is first.value


def test_plain_load_runs_a_module_once_for_every_class_in_it(sandbox: AppSandbox) -> None:
    module_path = sandbox.write("two.py", TWO_APPS_SOURCE, value=1)

    first = sandbox.load(module_path, "FirstApp")
    second = sandbox.load(module_path, "SecondApp")

    assert sandbox.runs() == 1
    assert sys.modules[first.__module__] is sys.modules[second.__module__]
    assert cached_class(module_path, "SecondApp") is second


def test_module_imported_by_another_app_module_is_not_run_again(sandbox: AppSandbox) -> None:
    helper_path = sandbox.write("helper.py", TWO_APPS_SOURCE, value=1)
    main_path = sandbox.write("main.py", f"from {sandbox.pkg_name}.helper import FirstApp as MainApp\n")

    sandbox.load(main_path, "MainApp")
    helper_class = sandbox.load(helper_path, "FirstApp")

    assert sandbox.runs() == 1
    assert sandbox.load(main_path, "MainApp") is helper_class
    # The loader adopted a module it didn't import, so it has no hash and a forced load re-imports it.
    assert app_utils.APP_MODULES[helper_path].content_hash is None
    sandbox.load(helper_path, "FirstApp", force_reload=True)
    assert sandbox.runs() == 2


def test_module_level_failure_is_raised_for_every_class_without_importing_again(sandbox: AppSandbox) -> None:
    module_path = sandbox.write("broken.py", FAILING_SOURCE)

    with pytest.raises(RuntimeError, match="module-level failure") as first:
        sandbox.load(module_path, "FirstApp")
    with pytest.raises(RuntimeError) as second:
        sandbox.load(module_path, "SecondApp")

    assert second.value is first.value
    assert sandbox.runs() == 1
    assert app_utils.APP_MODULES[module_path].name not in sys.modules


def test_forced_load_of_an_unchanged_file_reuses_the_module(
    sandbox: AppSandbox, caplog: pytest.LogCaptureFixture
) -> None:
    module_path = sandbox.write("two.py", TWO_APPS_SOURCE, value=1)
    original = sandbox.load(module_path, "FirstApp")

    with caplog.at_level(logging.INFO, logger=app_utils.LOGGER.name):
        reloaded = sandbox.load(module_path, "FirstApp", force_reload=True)

    assert reloaded is original
    assert sandbox.runs() == 1
    assert "file unchanged" in caplog.text


def test_forced_load_of_a_changed_file_runs_it_once_for_sibling_classes(
    sandbox: AppSandbox, caplog: pytest.LogCaptureFixture
) -> None:
    """Two app keys from one file in one reload batch both land on the one new import (D2)."""
    module_path = sandbox.write("two.py", TWO_APPS_SOURCE, value=1)
    old_first = sandbox.load(module_path, "FirstApp")
    sandbox.load(module_path, "SecondApp")
    sandbox.write("two.py", TWO_APPS_SOURCE, value=22)

    with caplog.at_level(logging.INFO, logger=app_utils.LOGGER.name):
        new_first = sandbox.load(module_path, "FirstApp", force_reload=True)
        new_second = sandbox.load(module_path, "SecondApp", force_reload=True)

    assert new_first is not old_first
    assert sandbox.runs() == 2
    module = sys.modules[new_first.__module__]
    assert module.VALUE == 22
    assert new_second is module.SecondApp
    assert "re-importing" in caplog.text


def test_a_save_racing_a_forced_import_is_picked_up_by_the_next_reload(sandbox: AppSandbox) -> None:
    """The hash is read before the import, so a save landing in between is never recorded as already loaded."""
    module_path = sandbox.write("racy.py", TWO_APPS_SOURCE, value=1)
    sandbox.load(module_path, "FirstApp")
    sandbox.write("racy.py", TWO_APPS_SOURCE, value=5)
    real_hash = app_utils.file_content_hash

    def hash_then_save(path: Path) -> str:
        digest = real_hash(path)
        sandbox.write("racy.py", TWO_APPS_SOURCE, value=66)  # the save lands between the hash read and the import
        return digest

    with patch.object(app_utils, "file_content_hash", side_effect=hash_then_save):
        sandbox.load(module_path, "FirstApp", force_reload=True)
    assert sandbox.runs() == 2

    reloaded = sandbox.load(module_path, "FirstApp", force_reload=True)

    assert sandbox.runs() == 3
    assert sys.modules[reloaded.__module__].VALUE == 66


def test_forced_load_retries_a_failed_import_after_the_file_is_fixed(sandbox: AppSandbox) -> None:
    module_path = sandbox.write("fixable.py", FAILING_SOURCE)
    with pytest.raises(RuntimeError):
        sandbox.load(module_path, "FirstApp")
    sandbox.write("fixable.py", TWO_APPS_SOURCE, value=1)

    with pytest.raises(RuntimeError):
        sandbox.load(module_path, "FirstApp")  # a plain load keeps the cached failure

    app_class = sandbox.load(module_path, "FirstApp", force_reload=True)

    assert app_class.__name__ == "FirstApp"
    assert cached_load_error(module_path, "FirstApp") is None


def test_forced_load_ignores_bytecode_for_a_same_size_edit_in_the_same_second(sandbox: AppSandbox) -> None:
    """The source loader trusts a .pyc whose recorded mtime and size match; a forced load deletes it first (D4)."""
    module_path = sandbox.write("same_size.py", TWO_APPS_SOURCE, value=1)
    stat = module_path.stat()
    sandbox.load(module_path, "FirstApp")

    # Plant a .pyc compiled from VALUE = 2 whose recorded mtime and size match the VALUE = 3 source saved
    # next: the state a same-size edit within the same second leaves behind.
    sandbox.write("same_size.py", TWO_APPS_SOURCE, value=2)
    os.utime(module_path, ns=(stat.st_atime_ns, stat.st_mtime_ns))
    py_compile.compile(str(module_path), doraise=True)
    sandbox.write("same_size.py", TWO_APPS_SOURCE, value=3)
    os.utime(module_path, ns=(stat.st_atime_ns, stat.st_mtime_ns))

    app_class = sandbox.load(module_path, "FirstApp", force_reload=True)

    assert sys.modules[app_class.__module__].VALUE == 3


def test_unremovable_bytecode_logs_a_warning_and_still_imports(
    sandbox: AppSandbox, caplog: pytest.LogCaptureFixture
) -> None:
    module_path = sandbox.write("readonly.py", TWO_APPS_SOURCE, value=1)
    sandbox.load(module_path, "FirstApp")
    sandbox.write("readonly.py", TWO_APPS_SOURCE, value=22)  # a different size, so the stale .pyc is detected

    with (
        patch.object(Path, "unlink", side_effect=PermissionError("read-only")),
        caplog.at_level(logging.WARNING, logger=app_utils.LOGGER.name),
    ):
        app_class = sandbox.load(module_path, "FirstApp", force_reload=True)

    assert sys.modules[app_class.__module__].VALUE == 22
    assert "Could not remove cached bytecode" in caplog.text


def test_record_is_stale_once_sys_modules_holds_another_module(sandbox: AppSandbox) -> None:
    module_path = sandbox.write("two.py", TWO_APPS_SOURCE, value=1)
    original = sandbox.load(module_path, "FirstApp")
    sys.modules.pop(original.__module__)

    assert cached_class(module_path, "FirstApp") is None
    reloaded = sandbox.load(module_path, "FirstApp")

    assert reloaded is not original
    assert sandbox.runs() == 2


def test_forced_load_that_cannot_read_the_file_drops_the_old_module(sandbox: AppSandbox) -> None:
    """A forced load that fails before re-importing records its error instead of leaving the old module."""
    module_path = sandbox.write("unreadable.py", TWO_APPS_SOURCE, value=1)
    original = sandbox.load(module_path, "FirstApp")

    with (
        patch.object(app_utils, "file_content_hash", side_effect=PermissionError("denied")),
        pytest.raises(PermissionError),
    ):
        sandbox.load(module_path, "FirstApp", force_reload=True)

    assert original.__module__ not in sys.modules
    assert isinstance(cached_load_error(module_path, "FirstApp"), PermissionError)


def test_forced_load_of_a_deleted_file_drops_the_old_module(sandbox: AppSandbox) -> None:
    module_path = sandbox.write("deleted.py", TWO_APPS_SOURCE, value=1)
    original = sandbox.load(module_path, "FirstApp")
    module_path.unlink()

    with pytest.raises(FileNotFoundError):
        sandbox.load(module_path, "FirstApp", force_reload=True)

    assert original.__module__ not in sys.modules


def test_failure_before_the_module_name_resolves_stays_cached_until_a_forced_load(sandbox: AppSandbox) -> None:
    module_path = sandbox.app_dir / "missing.py"

    with pytest.raises(FileNotFoundError) as first:
        sandbox.load(module_path, "FirstApp")
    sandbox.write("missing.py", TWO_APPS_SOURCE, value=1)

    assert cached_load_error(module_path, "FirstApp") is first.value
    assert sandbox.load(module_path, "FirstApp", force_reload=True).__name__ == "FirstApp"


def test_clear_app_module_removes_the_module_and_its_record_together(sandbox: AppSandbox) -> None:
    module_path = sandbox.write("two.py", TWO_APPS_SOURCE, value=1)
    app_class = sandbox.load(module_path, "FirstApp")

    app_utils.clear_app_module(module_path, app_class.__module__)

    assert app_class.__module__ not in sys.modules
    assert module_path not in app_utils.APP_MODULES
