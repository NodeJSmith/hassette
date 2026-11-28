"""What counts as app code, eviction, the syntax precheck and the watcher's reload-all rule (spec 162 D2-D4)."""

import importlib.util
import os
import sys
from collections.abc import Iterator
from pathlib import Path
from types import ModuleType

import pytest

from hassette.utils.app_modules import (
    app_code_modules,
    describe_syntax_error,
    evict_apps_package,
    imported_module_names,
    is_app_code,
    needs_reload_all,
    precheck_apps_package,
)
from hassette.utils.app_utils import APP_MODULES, AppModuleRecord
from hassette.utils.stack_frames import HASSETTE_PACKAGE_DIR


@pytest.fixture
def root(tmp_path: Path) -> Path:
    path = tmp_path / "apps"
    path.mkdir()
    return path.resolve()


@pytest.fixture
def prefix() -> str:
    """A unique module-name prefix, so modules loaded by one test never collide with another's."""
    return f"t{os.urandom(4).hex()}"


@pytest.fixture(autouse=True)
def restore_modules() -> Iterator[None]:
    """Drop every module and app record a test added."""
    before_modules = set(sys.modules)
    before_records = set(APP_MODULES)
    yield
    for name in set(sys.modules) - before_modules:
        sys.modules.pop(name, None)
    for path in set(APP_MODULES) - before_records:
        APP_MODULES.pop(path, None)


def write(path: Path, source: str = "") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(source)
    return path


def load(name: str, path: Path) -> ModuleType:
    """Import ``path`` as module ``name`` and register it in ``sys.modules``, as the app loader does."""
    is_package = path.name == "__init__.py"
    spec = importlib.util.spec_from_file_location(
        name, path, submodule_search_locations=[str(path.parent)] if is_package else None
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def loaded_with_source(root: Path, name: str, source: str) -> ModuleType:
    """A module loaded from an empty file that now holds ``source``: the import reader parses the file on disk."""
    path = write(root / "m.py")
    module = load(name, path)
    write(path, source)
    return module


class TestIsAppCode:
    def test_a_file_under_a_root_is_app_code(self, root: Path) -> None:
        assert is_app_code(root / "helpers" / "notify.py", [root])

    def test_a_file_outside_every_root_is_not(self, root: Path, tmp_path: Path) -> None:
        assert not is_app_code(tmp_path / "elsewhere.py", [root])

    @pytest.mark.parametrize("skipped", [".venv", "venv", "site-packages", "__pycache__", "node_modules"])
    def test_a_skipped_directory_under_a_root_is_not(self, root: Path, skipped: str) -> None:
        """An apps directory holding a virtualenv never counts its installed packages as app code."""
        assert not is_app_code(root / skipped / "lib" / "requests" / "__init__.py", [root])

    def test_a_skipped_name_above_the_root_does_not_exclude_it(self, tmp_path: Path) -> None:
        """Only the part of the path below the root is matched against the skipped names."""
        root = (tmp_path / "venv" / "apps").resolve()
        assert is_app_code(root / "notify.py", [root])

    def test_the_interpreter_prefix_is_not_app_code(self) -> None:
        """A root containing the interpreter (``directory = "/"``, say) still excludes installed packages."""
        prefix = Path(sys.prefix).resolve()
        assert not is_app_code(prefix / "lib" / "something.py", [Path(prefix.anchor)])

    def test_hassette_itself_is_not_app_code(self) -> None:
        package = Path(HASSETTE_PACKAGE_DIR).resolve()
        assert not is_app_code(package / "app" / "app.py", [package.parent])

    def test_a_symlinked_path_resolves_into_the_root(self, root: Path, tmp_path: Path) -> None:
        target = write(root / "notify.py")
        link = tmp_path / "link.py"
        link.symlink_to(target)
        assert is_app_code(link, [root])


class TestAppCodeModules:
    def test_finds_modules_by_file_whatever_their_name(self, root: Path, prefix: str) -> None:
        """A helper imported under a bare name and under the package name is found both times."""
        helper = write(root / "notify.py", "VALUE = 1\n")
        bare = load(f"{prefix}notify", helper)
        packaged = load(f"{prefix}pkg.notify", helper)

        found = app_code_modules([root])

        assert found == {f"{prefix}notify": (bare, helper), f"{prefix}pkg.notify": (packaged, helper)}

    def test_skips_modules_outside_the_roots(self, root: Path, tmp_path: Path, prefix: str) -> None:
        load(f"{prefix}outside", write(tmp_path / "outside.py"))
        assert app_code_modules([root]) == {}


class TestEvictAppsPackage:
    def test_removes_every_app_module_and_its_parent_attribute(self, root: Path, prefix: str) -> None:
        """The synthesized namespace package stays; the submodule it holds as an attribute goes."""
        package = ModuleType(prefix)
        package.__path__ = [str(root)]
        sys.modules[prefix] = package
        package.notify = load(f"{prefix}.notify", write(root / "notify.py", "VALUE = 1\n"))  # pyright: ignore[reportAttributeAccessIssue]
        load(f"{prefix}_bare", write(root / "bare.py"))

        evicted = evict_apps_package([root])

        assert evicted == [f"{prefix}.notify", f"{prefix}_bare"]
        assert sys.modules[prefix] is package
        assert f"{prefix}.notify" not in sys.modules
        assert f"{prefix}_bare" not in sys.modules
        assert not hasattr(package, "notify")

    def test_a_reimport_after_eviction_reads_the_edited_file(self, root: Path, prefix: str) -> None:
        helper = write(root / "notify.py", "VALUE = 1\n")
        load(f"{prefix}notify", helper)
        write(helper, "VALUE = 2\n")

        evict_apps_package([root])

        assert load(f"{prefix}notify", helper).VALUE == 2

    def test_removes_cached_bytecode(self, root: Path, prefix: str) -> None:
        helper = write(root / "notify.py", "VALUE = 1\n")
        pyc = Path(importlib.util.cache_from_source(str(helper)))
        write(pyc, "stale")
        load(f"{prefix}notify", helper)

        evict_apps_package([root])

        assert not pyc.exists()

    def test_drops_app_records_with_no_module_left(self, root: Path, prefix: str) -> None:
        """A failed import leaves a record with no module; it must go, or the app reuses the old failure."""
        app_file = write(root / "broken_app.py")
        APP_MODULES[app_file] = AppModuleRecord(name=f"{prefix}broken_app", module=None)

        evict_apps_package([root])

        assert app_file not in APP_MODULES

    def test_leaves_modules_outside_the_roots(self, root: Path, tmp_path: Path, prefix: str) -> None:
        outside = load(f"{prefix}outside", write(tmp_path / "outside.py"))
        load(f"{prefix}inside", write(root / "inside.py"))

        evict_apps_package([root])

        assert sys.modules[f"{prefix}outside"] is outside


class TestPrecheckAppsPackage:
    def test_returns_none_when_everything_compiles(self, root: Path, prefix: str) -> None:
        load(f"{prefix}notify", write(root / "notify.py", "VALUE = 1\n"))
        assert precheck_apps_package([root], []) is None

    def test_reports_a_loaded_helper_with_a_syntax_error(self, root: Path, prefix: str) -> None:
        helper = write(root / "notify.py", "VALUE = 1\n")
        load(f"{prefix}notify", helper)
        write(helper, "VALUE = 1\ndef broken(:\n")

        error = precheck_apps_package([root], [])

        assert error is not None
        assert error.filename == str(helper)
        assert error.lineno == 2

    def test_checks_enabled_app_files_that_were_never_loaded(self, root: Path) -> None:
        app_file = write(root / "new_app.py", "class (:\n")
        error = precheck_apps_package([root], [app_file])
        assert error is not None
        assert error.filename == str(app_file)

    def test_ignores_a_broken_file_nothing_imports(self, root: Path) -> None:
        write(root / "scratch.py", "def (:\n")
        assert precheck_apps_package([root], []) is None

    def test_skips_a_loaded_module_whose_file_was_deleted(self, root: Path, prefix: str) -> None:
        """Deleting a helper never refuses the reload; its importers fail at import instead."""
        helper = write(root / "notify.py", "VALUE = 1\n")
        load(f"{prefix}notify", helper)
        helper.unlink()

        assert precheck_apps_package([root], []) is None


class TestDescribeSyntaxError:
    def test_the_path_is_relative_to_the_containing_root(self, root: Path) -> None:
        error = SyntaxError("invalid syntax")
        error.filename = str(root / "helpers" / "notify.py")
        error.lineno = 12

        assert describe_syntax_error(error, [root]) == "helpers/notify.py:12: invalid syntax"

    def test_the_innermost_root_wins(self, root: Path) -> None:
        inner = root / "garage"
        error = SyntaxError("invalid syntax")
        error.filename = str(inner / "door.py")
        error.lineno = 3

        assert describe_syntax_error(error, [root, inner]) == "door.py:3: invalid syntax"


class TestNeedsReloadAll:
    def test_a_changed_helper_needs_a_reload_all(self, root: Path) -> None:
        app_file = root / "door.py"
        assert needs_reload_all([root / "notify.py"], [app_file], [root])

    def test_a_lone_app_file_edit_does_not(self, root: Path, prefix: str) -> None:
        app_file = write(root / "door.py", "VALUE = 1\n")
        load(f"{prefix}door", app_file)
        assert not needs_reload_all([app_file], [app_file], [root])

    def test_a_non_python_or_outside_path_does_not(self, root: Path, tmp_path: Path) -> None:
        assert not needs_reload_all([root / "hassette.toml", tmp_path / "other.py"], [], [root])

    def test_a_helper_under_a_skipped_directory_does_not(self, root: Path) -> None:
        assert not needs_reload_all([root / ".venv" / "lib" / "mod.py"], [], [root])

    @pytest.mark.parametrize(
        "import_line",
        [
            "import {name}",
            "from {name} import THRESHOLD",
            "from {name} import *",
        ],
    )
    def test_an_app_file_another_app_module_imports_needs_one(self, root: Path, prefix: str, import_line: str) -> None:
        """``vacuum_health`` importing ``str`` constants from ``vacuum_alert`` keeps both on one generation."""
        imported = write(root / "vacuum_alert.py", "THRESHOLD = 'low'\n")
        importer = write(root / "vacuum_health.py", import_line.format(name=f"{prefix}vacuum_alert") + "\n")
        load(f"{prefix}vacuum_alert", imported)
        load(f"{prefix}vacuum_health", importer)

        assert needs_reload_all([imported], [imported, importer], [root])

    def test_a_relative_import_counts(self, root: Path, prefix: str) -> None:
        load(prefix, write(root / "__init__.py"))
        imported = write(root / "thermoscura.py", "VALUE = 1\n")
        importer = write(root / "car_climate.py", "from .thermoscura import VALUE\n")
        load(f"{prefix}.thermoscura", imported)
        load(f"{prefix}.car_climate", importer)

        assert needs_reload_all([imported], [imported, importer], [root])

    def test_an_app_that_imports_only_itself_changed_does_not(self, root: Path, prefix: str) -> None:
        """Two changed app files importing each other are both reimported anyway."""
        first = write(root / "first.py", f"import {prefix}second\n")
        second = write(root / "second.py", "VALUE = 1\n")
        load(f"{prefix}second", second)
        load(f"{prefix}first", first)

        assert not needs_reload_all([first, second], [first, second], [root])


class TestImportedModuleNames:
    def test_names_each_package_above_an_imported_module(self, root: Path, prefix: str) -> None:
        module = loaded_with_source(root, f"{prefix}m", "import a.b.c\n")
        assert imported_module_names(f"{prefix}m", module) == {"a", "a.b", "a.b.c"}

    def test_from_import_names_the_module_and_each_name_as_a_submodule(self, root: Path, prefix: str) -> None:
        module = loaded_with_source(root, f"{prefix}m", "from pkg import thing\n")
        assert imported_module_names(f"{prefix}m", module) == {"pkg", "pkg.thing"}

    def test_reads_imports_inside_functions(self, root: Path, prefix: str) -> None:
        module = loaded_with_source(root, f"{prefix}m", "def f():\n    import later\n")
        assert "later" in imported_module_names(f"{prefix}m", module)

    def test_a_relative_import_from_a_top_level_module_names_nothing(self, root: Path, prefix: str) -> None:
        """``from . import x`` in a module with no package is an error, so it names nothing."""
        module = loaded_with_source(root, f"{prefix}m", "from . import x\n")
        assert imported_module_names(f"{prefix}m", module) == set()

    def test_a_relative_import_one_level_past_the_package_names_nothing(self, root: Path, prefix: str) -> None:
        """In ``pkg.m``, ``from .. import x`` climbs past ``pkg``, which Python refuses."""
        module = loaded_with_source(root, f"{prefix}.m", "from .. import x\n")
        assert imported_module_names(f"{prefix}.m", module) == set()

    def test_a_relative_import_inside_the_package_resolves(self, root: Path, prefix: str) -> None:
        module = loaded_with_source(root, f"{prefix}.m", "from . import sibling\n")
        assert imported_module_names(f"{prefix}.m", module) == {prefix, f"{prefix}.sibling"}

    def test_a_relative_import_past_the_top_names_nothing(self, root: Path, prefix: str) -> None:
        module = loaded_with_source(root, f"{prefix}m", "from ... import x\n")
        assert imported_module_names(f"{prefix}m", module) == set()

    def test_an_unparseable_file_names_nothing(self, root: Path, prefix: str) -> None:
        module = loaded_with_source(root, f"{prefix}m", "def (:\n")
        assert imported_module_names(f"{prefix}m", module) == set()
