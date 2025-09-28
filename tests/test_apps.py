import asyncio
import typing
from copy import deepcopy
from unittest.mock import patch

from hassette.core.apps.app_handler import _AppHandler, load_app_class

if typing.TYPE_CHECKING:
    from data.my_app import MyApp


async def test_apps_are_working(hassette_app_handler: _AppHandler) -> None:
    """Test actual WebSocket calls against running HA instance."""

    await asyncio.sleep(0.3)
    app_handler = hassette_app_handler
    assert app_handler.apps, "There should be at least one app group"
    assert "my_app" in app_handler.apps, "my_app should be one of the app groups"
    assert "my_app_sync" in app_handler.apps, "my_app_sync should be one of the app groups"
    assert "disabled_app" not in app_handler.apps, "disabled_app should remain disabled"

    # test that an app that only has config values but no class_name/filename is ignored
    assert "myfakeapp" not in app_handler.apps, "myfakeapp should not be one of the app groups"


def test_get_app_instance(hassette_app_handler: _AppHandler) -> None:
    """Test getting a specific app instance."""
    app = hassette_app_handler.get("my_app", 0)
    assert app is not None, "App instance should be found"

    my_app_class = load_app_class(app.app_manifest)

    assert isinstance(app, my_app_class), "App instance should be of type MyApp"


def test_all_apps(hassette_app_handler: _AppHandler) -> None:
    """Test getting all running app instances."""
    all_apps = hassette_app_handler.all()
    assert isinstance(all_apps, list), "All apps should return a list"
    assert len(all_apps) == 2, "There should be at least two running app instances"
    class_names = [app.class_name for app in all_apps]
    assert "MyApp" in class_names, "MyApp should be in the list of running apps"
    assert "MyAppSync" in class_names, "MyAppSync should be in the list of running apps"


async def test_handle_changes_disables_app(hassette_app_handler: _AppHandler) -> None:
    """Verify that editing hassette.toml to disable an app stops the running instance."""

    app_handler = hassette_app_handler
    assert "my_app" in app_handler.apps, "Precondition: my_app starts enabled"
    assert app_handler.apps_config["my_app"].enabled is True, "Precondition: my_app config shows enabled"

    with patch.object(app_handler, "_calculate_app_changes") as mock_calc_changes:
        mock_calc_changes.return_value = (
            {"my_app"},  # orphans
            set(),  # new_apps
            set(),  # reimport_apps
            set(),  # reload_apps
        )

        await app_handler.handle_changes()
        await asyncio.sleep(0)  # let async shutdowns complete

        assert "my_app" not in app_handler.apps, "my_app should stop after being disabled"
        assert "my_app_sync" in app_handler.apps, "Other enabled apps should continue running"


async def test_handle_changes_enables_app(hassette_app_handler: _AppHandler) -> None:
    """Verify that editing hassette.toml to enable a disabled app starts the instance."""

    app_handler = hassette_app_handler
    assert "disabled_app" not in app_handler.apps, "Precondition: disabled_app starts disabled"
    assert app_handler.apps_config["disabled_app"].enabled is False, "Precondition: disabled_app config shows disabled"

    new_app_config = deepcopy(app_handler.apps_config)
    new_app_config["disabled_app"].enabled = True

    with (
        patch.object(app_handler, "_calculate_app_changes") as mock_calc_changes,
        patch.object(app_handler, "refresh_config") as mock_refresh_config,
    ):
        app_handler.apps_config = new_app_config
        mock_refresh_config.return_value = (app_handler.apps_config, new_app_config)
        mock_calc_changes.return_value = (
            set(),  # orphans
            {"disabled_app"},  # new_apps
            set(),  # reimport_apps
            set(),  # reload_apps
        )

        await app_handler.handle_changes()
        await asyncio.sleep(0.3)  # let async startups complete

        assert "disabled_app" in app_handler.apps, "disabled_app should start after being enabled"
        assert "my_app" in app_handler.apps, "Other enabled apps should continue running"


async def test_config_changes_are_reflected_after_reload(hassette_app_handler: _AppHandler) -> None:
    """Verify that editing hassette.toml to change an app's config reloads the instance."""

    app_handler = hassette_app_handler
    assert "my_app" in app_handler.apps, "Precondition: my_app starts enabled"

    my_app_instance = typing.cast("MyApp", app_handler.get("my_app", 0))
    assert my_app_instance is not None, "Precondition: my_app instance should exist"

    assert my_app_instance.app_config.test_entity == "input_button.test", (
        "Precondition: my_app config has initial value"
    )

    app_handler.apps_config["my_app"].app_config = {"test_entity": "light.office"}

    await app_handler._reload_apps_due_to_config({"my_app"})
    await asyncio.sleep(0.3)  # let async startups complete

    assert "my_app" in app_handler.apps, "my_app should still be running after reload"
    my_app_instance = typing.cast("MyApp", app_handler.get("my_app", 0))
    assert my_app_instance is not None, "my_app instance should still exist after reload"
    assert my_app_instance.app_config.test_entity == "light.office", "my_app config should be updated after reload"


async def test_app_with_instance_name(hassette_app_handler: _AppHandler) -> None:
    """Test that an app with a specific instance_name in config starts correctly."""
    app_handler = hassette_app_handler
    assert "my_app" in app_handler.apps, "Precondition: my_app starts enabled"

    my_app_instance = app_handler.get("my_app", 0)
    assert my_app_instance is not None, "my_app instance should exist"
    assert my_app_instance.app_config.instance_name == "unique_instance_name", (
        "my_app instance should have the specified instance_name"
    )


async def test_app_without_instance_name(hassette_app_handler: _AppHandler) -> None:
    """Test that an app without a specific instance_name in config starts with default naming."""
    app_handler = hassette_app_handler
    assert "my_app_sync" in app_handler.apps, "Precondition: my_app_sync starts enabled"

    my_app_sync_instance = app_handler.get("my_app_sync", 0)
    assert my_app_sync_instance is not None, "my_app_sync instance should exist"
    assert my_app_sync_instance.app_config.instance_name == "MyAppSync.0", (
        "my_app_sync instance should have the default instance_name,"
        f" found {my_app_sync_instance.app_config.instance_name}"
    )


async def test_app_logger_is_instance_attribute(hassette_app_handler: _AppHandler) -> None:
    """Test that an app has its own logger attribute."""
    app_handler = hassette_app_handler
    assert "my_app" in app_handler.apps, "Precondition: my_app starts enabled"

    my_app_instance = app_handler.get("my_app", 0)
    assert my_app_instance is not None, "my_app instance should exist"
    assert hasattr(my_app_instance, "logger"), "my_app instance should have a logger attribute"
    assert type(my_app_instance).logger != my_app_instance.logger, (
        "logger should be an instance attribute, not class attribute"
    )
    assert my_app_instance.logger.name == "hassette.MyApp.unique_instance_name", (
        f"my_app logger name should be 'hassette.MyApp.unique_instance_name', found {my_app_instance.logger.name}"
    )
