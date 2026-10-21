"""The startup scan for app classes no app entry configures, and the warnings it produces."""

import tomllib
from pathlib import Path

import pytest

from hassette import context
from hassette.config.config import HassetteConfig
from hassette.testing import make_test_config
from hassette.utils.app_utils import (
    app_startup_warnings,
    find_unconfigured_app_classes,
    load_app_class_from_manifest,
    unconfigured_app_warning,
)
from tests.support.helpers import write_app

APP_SOURCE = """
from hassette import App, AppConfig

class LightsApp(App[AppConfig]): ...
"""


@pytest.fixture
def app_dir(tmp_path: Path) -> Path:
    path = tmp_path / "apps"
    path.mkdir()
    return path.resolve()


def make_config(tmp_path: Path, app_dir: Path, **apps: object) -> HassetteConfig:
    """A config reading `app_dir`, manifests validated; `apps` go into ``[hassette.apps]`` as written."""
    config = make_test_config(data_dir=tmp_path, apps={"directory": app_dir, **apps})
    with context.use_hassette_config(config):
        config.set_validated_app_manifests()
    return config


def startup_warnings(config: HassetteConfig) -> list[str]:
    return app_startup_warnings(config.apps, config_files=[], cwd=config.apps.directory)


class TestFindUnconfiguredAppClasses:
    @pytest.mark.parametrize(
        "base",
        ["App", "AppSync", "App[AppConfig]", "AppSync[AppConfig]", "hassette.App", "hassette.AppSync[AppConfig]"],
    )
    def test_finds_each_direct_base_spelling(self, app_dir: Path, base: str) -> None:
        path = write_app(
            app_dir,
            "my_app.py",
            f"import hassette\nfrom hassette import App, AppSync, AppConfig\n\nclass MyApp({base}): ...\n",
        )

        assert find_unconfigured_app_classes(app_dir, set()) == [(path, "MyApp")]

    def test_skips_classes_it_cannot_see_as_direct_subclasses(self, app_dir: Path) -> None:
        """Aliases, indirect subclasses, nested classes, and TYPE_CHECKING blocks are not resolved."""
        write_app(
            app_dir,
            "my_app.py",
            """
            from typing import TYPE_CHECKING
            from hassette import App as Base, App

            class Aliased(Base): ...

            class Shared(App): ...

            class Indirect(Shared): ...

            def factory():
                class Nested(App): ...
                return Nested

            if TYPE_CHECKING:
                class Guarded(App): ...

            class Plain: ...
            """,
        )

        assert [name for _, name in find_unconfigured_app_classes(app_dir, set())] == ["Shared"]

    def test_never_imports_the_file(self, app_dir: Path) -> None:
        write_app(app_dir, "my_app.py", f"raise RuntimeError('imported')\n{APP_SOURCE}")

        assert [name for _, name in find_unconfigured_app_classes(app_dir, set())] == ["LightsApp"]

    def test_configured_pair_is_skipped_but_a_second_class_in_the_file_is_not(self, app_dir: Path) -> None:
        path = write_app(app_dir, "my_app.py", f"{APP_SOURCE}\nclass OtherApp(App): ...\n")

        assert find_unconfigured_app_classes(app_dir, {(path, "LightsApp")}) == [(path, "OtherApp")]

    def test_skips_unparseable_and_unreadable_files(self, app_dir: Path) -> None:
        write_app(app_dir, "broken.py", "class (:\n")
        (app_dir / "binary.py").write_bytes(b"\xff\xfe\x00")
        good = write_app(app_dir, "good.py", APP_SOURCE)

        assert find_unconfigured_app_classes(app_dir, set()) == [(good, "LightsApp")]

    def test_walks_subdirectories_in_sorted_order_and_skips_built_in_exclusions(self, app_dir: Path) -> None:
        second = write_app(app_dir / "b", "two.py", APP_SOURCE)
        first = write_app(app_dir / "a", "one.py", APP_SOURCE)
        write_app(app_dir / ".venv" / "lib", "vendored.py", APP_SOURCE)
        write_app(app_dir / "__pycache__", "cached.py", APP_SOURCE)

        assert [path for path, _ in find_unconfigured_app_classes(app_dir, set())] == [first, second]

    def test_apps_dir_under_an_excluded_name_is_not_scanned(self, tmp_path: Path) -> None:
        app_dir = tmp_path / "venv" / "apps"
        write_app(app_dir, "my_app.py", APP_SOURCE)

        assert find_unconfigured_app_classes(app_dir, set()) == []

    def test_missing_directory_finds_nothing(self, tmp_path: Path) -> None:
        assert find_unconfigured_app_classes(tmp_path / "missing", set()) == []


class TestUnconfiguredAppWarning:
    def test_snippet_names_the_path_relative_to_the_apps_directory(self, app_dir: Path) -> None:
        path = write_app(app_dir / "lights", "porch.py", APP_SOURCE)

        assert unconfigured_app_warning(app_dir, path, "LightsApp") == (
            f"App class LightsApp in {path} is not configured, so it won't run. To run it, add to your config:\n\n"
            "[hassette.apps.lights_app]\n"
            'filename = "lights/porch.py"\n'
            'class_name = "LightsApp"\n\n'
            "Set warn_unconfigured = false under [hassette.apps] to turn this warning off."
        )

    def test_pasted_snippet_loads_the_app(self, tmp_path: Path, app_dir: Path) -> None:
        """The snippet for an app in a subdirectory, pasted as config, configures and loads that app."""
        path = write_app(app_dir / "lights", "porch.py", APP_SOURCE)
        warning = startup_warnings(make_config(tmp_path, app_dir))[0]
        snippet = tomllib.loads(warning.split("\n\n")[1])["hassette"]["apps"]

        config = make_config(tmp_path, app_dir, **snippet)

        manifest = config.apps.manifests["lights_app"]
        assert manifest.full_path == path
        assert load_app_class_from_manifest(manifest, config=config).__name__ == "LightsApp"
        assert startup_warnings(config) == []


class TestAppStartupWarnings:
    def test_one_warning_per_unconfigured_class_replaces_no_apps_found(self, tmp_path: Path, app_dir: Path) -> None:
        one = write_app(app_dir, "one.py", APP_SOURCE)
        two = write_app(app_dir, "two.py", APP_SOURCE)

        assert startup_warnings(make_config(tmp_path, app_dir)) == [
            unconfigured_app_warning(app_dir, one, "LightsApp"),
            unconfigured_app_warning(app_dir, two, "LightsApp"),
        ]

    def test_no_app_classes_still_warns_no_apps_found(self, tmp_path: Path, app_dir: Path) -> None:
        assert startup_warnings(make_config(tmp_path, app_dir)) == [
            f"No apps found or configured in apps directory {app_dir}"
        ]

    def test_switched_off_skips_the_scan_and_warns_as_if_no_classes(self, tmp_path: Path, app_dir: Path) -> None:
        write_app(app_dir, "one.py", APP_SOURCE)

        assert startup_warnings(make_config(tmp_path, app_dir, warn_unconfigured=False)) == [
            f"No apps found or configured in apps directory {app_dir}"
        ]

    def test_disabled_entry_counts_as_configured(self, tmp_path: Path, app_dir: Path) -> None:
        write_app(app_dir, "one.py", APP_SOURCE)
        config = make_config(
            tmp_path, app_dir, apps={"lights": {"filename": "one.py", "class_name": "LightsApp", "enabled": False}}
        )

        assert startup_warnings(config) == []

    def test_entry_missing_required_keys_does_not_count(self, tmp_path: Path, app_dir: Path) -> None:
        path = write_app(app_dir, "one.py", APP_SOURCE)
        config = make_config(tmp_path, app_dir, apps={"lights": {"filename": "one.py"}})

        assert startup_warnings(config) == [unconfigured_app_warning(app_dir, path, "LightsApp")]
