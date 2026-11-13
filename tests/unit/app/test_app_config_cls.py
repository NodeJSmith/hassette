"""`App.app_config_cls` is resolved when the subclass is defined, not only by the app loader (issue #4040)."""

from hassette.app import App, AppConfig, AppSync


class _GreetingConfig(AppConfig):
    greeting: str = "hi"


class _GreetingApp(App[_GreetingConfig]):
    pass


class _GreetingSubApp(_GreetingApp):
    pass


class _SyncGreetingApp(AppSync[_GreetingConfig]):
    pass


class _UnparameterizedApp(App):
    pass


def test_generic_parameter_sets_app_config_cls() -> None:
    """An app imported directly, without the loader, exposes the config class from its generic parameter."""
    assert _GreetingApp.app_config_cls is _GreetingConfig


def test_app_sync_generic_parameter_sets_app_config_cls() -> None:
    assert _SyncGreetingApp.app_config_cls is _GreetingConfig


def test_subclass_inherits_parent_config_cls() -> None:
    assert _GreetingSubApp.app_config_cls is _GreetingConfig


def test_unparameterized_app_falls_back_to_app_config() -> None:
    assert _UnparameterizedApp.app_config_cls is AppConfig
