"""Unit tests for AppFactory."""

from typing import cast
from unittest.mock import Mock, patch

import pytest
from pydantic import AliasChoices, AliasPath, Field
from pydantic.alias_generators import to_camel
from pydantic_settings import SettingsConfigDict

from hassette import AppConfig
from hassette.core.app_factory import AppFactory, accepted_config_keys
from hassette.core.app_registry import AppRegistry


def make_app_class(config_cls: type[AppConfig] = AppConfig, **kwargs) -> Mock:
    """A mock App class with a real config class, so config validation runs for real."""
    return Mock(app_config_cls=config_cls, **kwargs)


@pytest.fixture
def mock_hassette():
    """Create a mock Hassette instance."""
    return Mock()


@pytest.fixture
def mock_registry():
    """Create a mock AppRegistry instance."""
    registry = Mock()
    registry.register_app = Mock()
    registry.record_failure = Mock()
    registry.get = Mock(return_value=None)
    registry.get_running_apps = Mock(return_value={})
    return cast("AppRegistry", registry)


@pytest.fixture
def mock_manifest():
    """Create a mock AppManifest instance."""
    manifest = Mock()
    manifest.full_path = "/path/to/app.py"
    manifest.class_name = "TestApp"
    manifest.display_name = "test_app"
    manifest.app_config = {"instance_name": "test_instance"}
    return manifest


@pytest.fixture
def factory(mock_hassette, mock_registry):
    """Create an AppFactory instance with mocked dependencies."""
    return AppFactory(mock_hassette, mock_registry)


class TestAppFactoryInit:
    def test_init_stores_hassette_and_registry(self, mock_hassette, mock_registry):
        """Verify constructor stores references correctly."""
        factory = AppFactory(mock_hassette, mock_registry)

        assert factory.hassette is mock_hassette
        assert factory.registry is mock_registry


class TestAppFactoryCreateInstances:
    @patch("hassette.core.app_factory.load_app_class_from_manifest")
    def test_create_instances_success_single_config(
        self,
        mock_load_class,
        factory: AppFactory,
        mock_registry: AppRegistry,
        mock_manifest,
    ):
        """Successfully creates single app instance from dict config."""
        mock_load_class.return_value = mock_app_class = make_app_class()

        factory.create_instances("test_app", mock_manifest)

        mock_app_class.assert_called_once()
        mock_registry.register_app.assert_called_once_with("test_app", 0, mock_app_class.return_value)

    @patch("hassette.core.app_factory.load_app_class_from_manifest")
    def test_create_instances_success_multiple_configs(
        self, mock_load_class, factory: AppFactory, mock_registry: AppRegistry, mock_manifest
    ):
        """Creates multiple instances from list of configs."""
        mock_load_class.return_value = mock_app_class = make_app_class()
        mock_manifest.app_config = [
            {"instance_name": "instance_0"},
            {"instance_name": "instance_1"},
        ]

        factory.create_instances("test_app", mock_manifest)

        assert mock_app_class.call_count == 2
        assert mock_registry.register_app.call_count == 2
        mock_registry.register_app.assert_any_call("test_app", 0, mock_app_class.return_value)
        mock_registry.register_app.assert_any_call("test_app", 1, mock_app_class.return_value)

    @patch("hassette.core.app_factory.load_app_class_from_manifest")
    def test_create_instances_empty_config(
        self, mock_load_class, factory: AppFactory, mock_registry: AppRegistry, mock_manifest
    ):
        """Handles empty/None app_config gracefully."""
        mock_manifest.app_config = None
        mock_load_class.return_value = mock_app_class = make_app_class()

        factory.create_instances("test_app", mock_manifest)

        mock_app_class.assert_not_called()
        mock_registry.register_app.assert_not_called()

    @patch("hassette.core.app_factory.class_failed_to_load", return_value=True)
    @patch("hassette.core.app_factory.get_class_load_error")
    def test_create_instances_class_load_failure(
        self, mock_get_error, mock_failed, factory: AppFactory, mock_registry: AppRegistry, mock_manifest
    ):
        """Records failure at index 0 when class loading fails."""
        cached_error = ValueError("Failed to load")
        mock_get_error.return_value = cached_error

        factory.create_instances("test_app", mock_manifest)

        mock_registry.record_failure.assert_called_once_with("test_app", 0, cached_error)
        mock_registry.register_app.assert_not_called()

    @patch("hassette.core.app_factory.class_failed_to_load", return_value=True)
    @patch("hassette.core.app_factory.get_class_load_error")
    def test_create_instances_class_load_failure_reports_unoccupied_sibling(
        self, mock_get_error, mock_failed, factory: AppFactory, mock_registry: AppRegistry, mock_manifest
    ):
        """When index 0 is already running (preserved) and class loading fails for a
        multi-instance app, the failure must be recorded against the first unstarted sibling
        index instead of being swallowed entirely — otherwise a genuinely-failed index 1 would
        report no FAILED status at all and look like an ordinary stopped index (Codex P2 finding
        on #2245).
        """
        cached_error = ValueError("Failed to load")
        mock_get_error.return_value = cached_error
        mock_manifest.app_config = [
            {"instance_name": "instance_0"},
            {"instance_name": "instance_1"},
        ]
        existing_app = Mock()
        mock_registry.get = Mock(side_effect=lambda _key, idx: existing_app if idx == 0 else None)

        factory.create_instances("test_app", mock_manifest)

        mock_registry.record_failure.assert_called_once_with("test_app", 1, cached_error)
        mock_registry.register_app.assert_not_called()

    @patch("hassette.core.app_factory.class_failed_to_load", return_value=True)
    @patch("hassette.core.app_factory.get_class_load_error")
    def test_create_instances_class_load_failure_all_indices_occupied(
        self, mock_get_error, mock_failed, factory: AppFactory, mock_registry: AppRegistry, mock_manifest
    ):
        """When every configured index already has a live entry, there is no unstarted index
        to report the failure against -- skip recording entirely rather than overwriting a
        running instance's registry entry.
        """
        cached_error = ValueError("Failed to load")
        mock_get_error.return_value = cached_error
        mock_manifest.app_config = [{"instance_name": "instance_0"}]
        mock_registry.get = Mock(return_value=Mock())

        factory.create_instances("test_app", mock_manifest)

        mock_registry.record_failure.assert_not_called()
        mock_registry.register_app.assert_not_called()

    @patch("hassette.core.app_factory.load_app_class_from_manifest")
    def test_create_instances_missing_instance_name(
        self, mock_load_class, factory: AppFactory, mock_registry: AppRegistry, mock_manifest
    ):
        """Records failure for config missing instance_name, continues with others."""
        mock_manifest.app_config = [
            {"other_field": "value"},  # Missing instance_name
            {"instance_name": "valid_instance"},
        ]
        mock_load_class.return_value = mock_app_class = make_app_class()

        factory.create_instances("test_app", mock_manifest)

        # First config should fail
        assert mock_registry.record_failure.call_count == 1
        call_args = mock_registry.record_failure.call_args
        assert call_args[0][0] == "test_app"
        assert call_args[0][1] == 0
        assert isinstance(call_args[0][2], ValueError)

        # Second config should succeed
        mock_registry.register_app.assert_called_once_with("test_app", 1, mock_app_class.return_value)

    @patch("hassette.core.app_factory.load_app_class_from_manifest")
    def test_create_instances_non_string_instance_name(
        self, mock_load_class, factory: AppFactory, mock_registry: AppRegistry, mock_manifest
    ):
        """A non-string but truthy instance_name (e.g. an int) is rejected the same way a
        missing one is -- is_valid_instance_name() requires a str, not just a truthy value.
        """
        mock_manifest.app_config = [{"instance_name": 123}]
        mock_load_class.return_value = make_app_class()

        factory.create_instances("test_app", mock_manifest)

        mock_registry.record_failure.assert_called_once()
        call_args = mock_registry.record_failure.call_args
        assert call_args[0][0] == "test_app"
        assert call_args[0][1] == 0
        assert isinstance(call_args[0][2], ValueError)
        mock_registry.register_app.assert_not_called()

    @patch("hassette.core.app_factory.load_app_class_from_manifest")
    def test_create_instances_validation_failure(
        self, mock_load_class, factory: AppFactory, mock_registry: AppRegistry, mock_manifest
    ):
        """Records failure when Pydantic validation fails."""
        mock_app_class = Mock(__name__="TestApp")

        validation_error = ValueError("Validation failed")
        mock_app_class.app_config_cls.model_validate.side_effect = validation_error
        mock_load_class.return_value = mock_app_class

        factory.create_instances("test_app", mock_manifest)

        mock_registry.record_failure.assert_called_once_with("test_app", 0, validation_error)
        mock_registry.register_app.assert_not_called()

    @patch("hassette.core.app_factory.load_app_class_from_manifest")
    def test_create_instances_app_create_failure(
        self, mock_load_class, factory: AppFactory, mock_registry: AppRegistry, mock_manifest
    ):
        """Records failure when App() constructor raises exception."""
        create_error = RuntimeError("Create failed")
        mock_app_class = make_app_class(__name__="TestApp")

        mock_app_class.side_effect = create_error
        mock_load_class.return_value = mock_app_class
        factory.create_instances("test_app", mock_manifest)

        mock_registry.record_failure.assert_called_once_with("test_app", 0, create_error)
        mock_registry.register_app.assert_not_called()

    @patch("hassette.core.app_factory.load_app_class_from_manifest")
    def test_create_instances_passes_manifest_to_constructor(self, mock_load_class, factory: AppFactory, mock_manifest):
        """Passes the section's manifest to the App constructor per instance (regression #1062)."""
        mock_load_class.return_value = mock_app_class = make_app_class()
        mock_manifest.app_config = [{"instance_name": "instance_0"}]

        factory.create_instances("test_app", mock_manifest)

        assert mock_app_class.call_args.kwargs["app_manifest"] is mock_manifest

    @patch("hassette.core.app_factory.load_app_class_from_manifest")
    def test_create_instances_passes_app_key_to_constructor(
        self, mock_load_class, factory: AppFactory, mock_manifest
    ) -> None:
        """Passes the app_key loop value to the App constructor (regression #1060)."""
        mock_load_class.return_value = mock_app_class = make_app_class()
        mock_manifest.app_config = [{"instance_name": "instance_0"}]

        factory.create_instances("kitchen_lights", mock_manifest)

        assert mock_app_class.call_args.kwargs["app_key"] == "kitchen_lights"

    @patch("hassette.core.app_factory.load_app_class_from_manifest")
    def test_create_instances_registers_each_app(
        self, mock_load_class, factory: AppFactory, mock_registry: AppRegistry, mock_manifest
    ):
        """Verifies registry.register_app() called for each successful instance."""
        mock_manifest.app_config = [
            {"instance_name": "instance_0"},
            {"instance_name": "instance_1"},
            {"instance_name": "instance_2"},
        ]
        mock_load_class.return_value = make_app_class()

        factory.create_instances("test_app", mock_manifest)

        assert mock_registry.register_app.call_count == 3

    @patch("hassette.core.app_factory.load_app_class_from_manifest")
    @patch("hassette.core.app_factory.class_already_loaded", return_value=True)
    def test_create_instances_force_reload(self, mock_loaded, mock_load_class, factory: AppFactory, mock_manifest):
        """Passes force_reload=True through to load_class()."""
        mock_load_class.return_value = make_app_class()

        factory.create_instances("test_app", mock_manifest, force_reload=True)

        # When force_reload=True, should call load_app_class_from_manifest even if already loaded
        mock_load_class.assert_called_once_with(mock_manifest, config=factory.hassette.config, force_reload=True)

    @patch("hassette.core.app_factory.load_app_class_from_manifest")
    def test_create_instances_force_reload_ignored_when_instance_already_running(
        self, mock_load_class, factory: AppFactory, mock_registry: AppRegistry, mock_manifest
    ):
        """force_reload=True must not reload the shared class while any instance of this
        app_key is already running -- doing so would leave the preserved instance bound to
        the pre-reload class while a newly-created sibling gets the post-reload one, two class
        versions serving one app_key at once (Codex P2 finding on #2245). Use reload_app() to
        stop-then-recreate with a fresh class instead.
        """
        mock_manifest.app_config = [
            {"instance_name": "instance_0"},
            {"instance_name": "instance_1"},
        ]
        # Index 0 is already running; index 1 is not.
        existing_app = Mock()
        mock_registry.get = Mock(side_effect=lambda _key, idx: existing_app if idx == 0 else None)
        mock_registry.get_running_apps = Mock(return_value={0: existing_app})
        mock_load_class.return_value = make_app_class()

        factory.create_instances("test_app", mock_manifest, force_reload=True)

        # load_class() must be called with force_reload downgraded to False.
        mock_load_class.assert_called_once_with(mock_manifest, config=factory.hassette.config, force_reload=False)

    @patch("hassette.core.app_factory.load_app_class_from_manifest")
    def test_create_instances_force_reload_ignored_when_all_indices_occupied(
        self, mock_load_class, factory: AppFactory, mock_registry: AppRegistry, mock_manifest
    ):
        """When every configured index is already live, force_reload=True must not reload the
        class at all -- there is no instance left to apply a fresh class to, so reloading would
        only mutate the module/class cache for nothing.
        """
        mock_manifest.app_config = [{"instance_name": "instance_0"}]
        existing_app = Mock()
        mock_registry.get = Mock(return_value=existing_app)
        mock_registry.get_running_apps = Mock(return_value={0: existing_app})
        mock_load_class.return_value = make_app_class()

        created = factory.create_instances("test_app", mock_manifest, force_reload=True)

        mock_load_class.assert_called_once_with(mock_manifest, config=factory.hassette.config, force_reload=False)
        assert created == set()

    @patch("hassette.core.app_factory.load_app_class_from_manifest")
    def test_create_instances_force_reload_ignored_for_out_of_range_running_orphan(
        self, mock_load_class, factory: AppFactory, mock_registry: AppRegistry, mock_manifest
    ):
        """force_reload=True must also be downgraded when the only running instance of this
        app_key sits at an index the *current* config no longer covers (e.g. the config shrank
        from 2 instances to 1, leaving index 1 running as an orphan -- prune_stale_failed_indices()
        only prunes stale failed entries, never running ones). The in-range live_indices set alone
        would miss this and let the reload proceed, splitting the orphan and any newly-created
        in-range instance across two class versions (Codex P2 finding on #2245, round 2).
        """
        mock_manifest.app_config = [{"instance_name": "instance_0"}]  # config shrank to 1 instance
        orphan = Mock()
        mock_registry.get = Mock(return_value=None)  # index 0 (the only configured index) is not live
        mock_registry.get_running_apps = Mock(return_value={1: orphan})  # index 1 is an out-of-range orphan
        mock_load_class.return_value = make_app_class()

        factory.create_instances("test_app", mock_manifest, force_reload=True)

        mock_load_class.assert_called_once_with(mock_manifest, config=factory.hassette.config, force_reload=False)

    @patch("hassette.core.app_factory.load_app_class_from_manifest")
    def test_create_instances_skips_already_running_indices(
        self, mock_load_class, factory: AppFactory, mock_registry: AppRegistry, mock_manifest
    ):
        """create_instances skips indices that already have a live registry entry, rather
        than overwriting them via register_app() and orphaning the originals' listeners,
        scheduler jobs, and tasks (#1688). Only indices without a live entry are created.
        """
        mock_load_class.return_value = mock_app_class = make_app_class()
        mock_manifest.app_config = [
            {"instance_name": "instance_0"},
            {"instance_name": "instance_1"},
            {"instance_name": "instance_2"},
        ]
        # Index 1 is already running; indices 0 and 2 are not.
        existing_app = Mock()
        mock_registry.get = Mock(side_effect=lambda _key, idx: existing_app if idx == 1 else None)

        created = factory.create_instances("test_app", mock_manifest)

        # Only indices 0 and 2 should be created (2 calls, not 3).
        assert created == {0, 2}
        assert mock_app_class.call_count == 2
        assert mock_registry.register_app.call_count == 2
        mock_registry.register_app.assert_any_call("test_app", 0, mock_app_class.return_value)
        mock_registry.register_app.assert_any_call("test_app", 2, mock_app_class.return_value)


class TestAppFactoryCreateSingleInstance:
    def test_create_single_instance_success(self, factory: AppFactory, mock_registry: AppRegistry, mock_manifest):
        """Registers the instance at the given index on success."""
        mock_app_class = make_app_class()
        config = {"instance_name": "test_instance"}

        factory.create_single_instance("test_app", mock_manifest, 3, config, mock_app_class)

        mock_app_class.assert_called_once()
        mock_registry.register_app.assert_called_once_with("test_app", 3, mock_app_class.return_value)
        mock_registry.record_failure.assert_not_called()

    def test_create_single_instance_missing_instance_name(
        self, factory: AppFactory, mock_registry: AppRegistry, mock_manifest
    ):
        """Records failure at the given index when instance_name is missing."""
        mock_app_class = make_app_class()
        config = {"other_field": "value"}

        factory.create_single_instance("test_app", mock_manifest, 2, config, mock_app_class)

        mock_registry.record_failure.assert_called_once()
        call_args = mock_registry.record_failure.call_args
        assert call_args[0][0] == "test_app"
        assert call_args[0][1] == 2
        assert isinstance(call_args[0][2], ValueError)
        mock_registry.register_app.assert_not_called()
        mock_app_class.assert_not_called()

    def test_create_single_instance_validation_failure_records_correct_index(
        self, factory: AppFactory, mock_registry: AppRegistry, mock_manifest
    ):
        """Records failure at the real index (not hardcoded 0) when Pydantic validation fails."""
        mock_app_class = Mock(__name__="TestApp")
        validation_error = ValueError("Validation failed")
        mock_app_class.app_config_cls.model_validate.side_effect = validation_error
        config = {"instance_name": "test_instance"}

        factory.create_single_instance("test_app", mock_manifest, 5, config, mock_app_class)

        mock_registry.record_failure.assert_called_once_with("test_app", 5, validation_error)
        mock_registry.register_app.assert_not_called()

    def test_create_single_instance_app_create_failure_records_correct_index(
        self, factory: AppFactory, mock_registry: AppRegistry, mock_manifest
    ):
        """Records failure at the real index when App() constructor raises."""
        create_error = RuntimeError("Create failed")
        mock_app_class = make_app_class(__name__="TestApp")
        mock_app_class.side_effect = create_error
        config = {"instance_name": "test_instance"}

        factory.create_single_instance("test_app", mock_manifest, 7, config, mock_app_class)

        mock_registry.record_failure.assert_called_once_with("test_app", 7, create_error)
        mock_registry.register_app.assert_not_called()


class MotionLightConfig(AppConfig):
    off_delay: int = 30


class AliasedDelayConfig(AppConfig):
    off_delay: int = Field(default=30, alias="delay")


class ByNameDelayConfig(AliasedDelayConfig):
    model_config = SettingsConfigDict(validate_by_name=True)


class CamelCaseConfig(AppConfig):
    model_config = SettingsConfigDict(alias_generator=to_camel)

    off_delay: int = 30


class AliasChoicesConfig(AppConfig):
    off_delay: int = Field(default=30, validation_alias=AliasChoices("delay", AliasPath("timing", 0)))


@pytest.mark.parametrize(
    ("config_cls", "expected", "absent"),
    [
        (MotionLightConfig, {"off_delay"}, set()),
        (AliasedDelayConfig, {"delay"}, {"off_delay"}),
        (ByNameDelayConfig, {"delay", "off_delay"}, set()),
        (AliasChoicesConfig, {"delay", "timing"}, {"off_delay"}),
    ],
)
def test_accepted_config_keys_follow_pydantic_lookup(
    config_cls: type[AppConfig], expected: set[str], absent: set[str]
) -> None:
    """Suggestion candidates are the keys pydantic actually reads, not always the attribute names."""
    keys = set(accepted_config_keys(config_cls))

    assert expected <= keys
    assert not (absent & keys)


class TestAppFactoryUnrecognizedConfigKeyWarning:
    def test_bare_app_config_does_not_warn_on_extras(
        self, factory: AppFactory, mock_registry: AppRegistry, mock_manifest
    ):
        """A bare AppConfig takes arbitrary keys as intended extras, so none of them warn."""
        config = {"instance_name": "test_instance", "anything": 1, "off_dealy": 5}

        factory.create_single_instance("test_app", mock_manifest, 0, config, make_app_class())

        mock_registry.register_app.assert_called_once()
        mock_registry.record_failure.assert_not_called()

    def test_typed_config_typo_warns_with_suggestion(
        self, factory: AppFactory, mock_registry: AppRegistry, mock_manifest
    ):
        """A typo'd key on a typed subclass warns once, names the key, and suggests the field."""
        mock_app_class = make_app_class(MotionLightConfig)
        config = {"instance_name": "test_instance", "off_dealy": 5}

        with pytest.warns(UserWarning, match="Unrecognized configuration key") as record:
            factory.create_single_instance("test_app", mock_manifest, 0, config, mock_app_class)

        assert len(record) == 1
        msg = str(record[0].message)
        assert "'off_dealy' (did you mean 'off_delay'?)" in msg
        assert "test_app" in msg
        assert "test_instance" in msg
        mock_registry.register_app.assert_called_once()
        validated = mock_app_class.call_args.kwargs["app_config"]
        assert validated.off_delay == 30

    def test_typed_config_unrelated_key_warns_without_suggestion(
        self, factory: AppFactory, mock_registry: AppRegistry, mock_manifest
    ):
        """An unrecognized key with no close field match warns without a suggestion."""
        config = {"instance_name": "test_instance", "zzz": 5}

        with pytest.warns(UserWarning, match="'zzz'") as record:
            factory.create_single_instance("test_app", mock_manifest, 0, config, make_app_class(MotionLightConfig))

        assert "did you mean" not in str(record[0].message)
        mock_registry.register_app.assert_called_once()

    def test_typed_config_suggests_alias_not_field_name(
        self, factory: AppFactory, mock_registry: AppRegistry, mock_manifest
    ):
        """An aliased field is populated by its alias, so the suggestion names the alias, not the attribute."""
        config = {"instance_name": "test_instance", "off_delay": 5}

        with pytest.warns(UserWarning, match="Unrecognized configuration key") as record:
            factory.create_single_instance("test_app", mock_manifest, 0, config, make_app_class(AliasedDelayConfig))

        assert "'off_delay' (did you mean 'delay'?)" in str(record[0].message)

    def test_typed_config_incomplete_alias_path_does_not_suggest_itself(
        self, factory: AppFactory, mock_registry: AppRegistry, mock_manifest
    ):
        """A correctly spelled alias-path head whose nested value is missing warns without suggesting itself."""
        config = {"instance_name": "test_instance", "timing": []}

        with pytest.warns(UserWarning, match="'timing'") as record:
            factory.create_single_instance("test_app", mock_manifest, 0, config, make_app_class(AliasChoicesConfig))

        msg = str(record[0].message)
        assert "did you mean" not in msg
        assert "value went unused" in msg
        mock_registry.register_app.assert_called_once()

    def test_typed_config_aliased_instance_name_does_not_warn(
        self, factory: AppFactory, mock_registry: AppRegistry, mock_manifest
    ):
        """The framework requires the literal instance_name key, so it never warns, even under an alias generator."""
        config = {"instance_name": "test_instance", "offDelay": 5}

        factory.create_single_instance("test_app", mock_manifest, 0, config, make_app_class(CamelCaseConfig))

        mock_registry.register_app.assert_called_once()
        mock_registry.record_failure.assert_not_called()

    def test_typed_config_all_keys_recognized_does_not_warn(
        self, factory: AppFactory, mock_registry: AppRegistry, mock_manifest
    ):
        """No warning when every key maps to a declared field (pytest escalates warnings to errors)."""
        config = {"instance_name": "test_instance", "off_delay": 5}

        factory.create_single_instance("test_app", mock_manifest, 0, config, make_app_class(MotionLightConfig))

        mock_registry.register_app.assert_called_once()
        mock_registry.record_failure.assert_not_called()

    def test_typed_config_ignores_dotenv_extras(
        self, factory: AppFactory, mock_registry: AppRegistry, mock_manifest, tmp_path, monkeypatch
    ):
        """Unrelated .env entries folded into model_extra by pydantic-settings never warn."""
        (tmp_path / ".env").write_text("SOME_OTHER_SECRET=1\n")
        monkeypatch.chdir(tmp_path)
        config = {"instance_name": "test_instance", "off_delay": 5}

        mock_app_class = make_app_class(MotionLightConfig)

        factory.create_single_instance("test_app", mock_manifest, 0, config, mock_app_class)

        assert "some_other_secret" in mock_app_class.call_args.kwargs["app_config"].model_extra
        mock_registry.register_app.assert_called_once()
        mock_registry.record_failure.assert_not_called()


class TestAppFactoryLoadClass:
    @patch("hassette.core.app_factory.load_app_class_from_manifest")
    def test_load_class_fresh_load_success(self, mock_load_class, factory: AppFactory, mock_manifest):
        """Loads class when not cached."""
        mock_load_class.return_value = mock_app_class = Mock()

        result = factory.load_class("test_app", mock_manifest, force_reload=False)

        assert result is mock_app_class
        mock_load_class.assert_called_once()

    @patch("hassette.core.app_factory.get_loaded_class")
    @patch("hassette.core.app_factory.class_already_loaded", return_value=True)
    def test_load_class_returns_cached(self, mock_loaded, mock_get_loaded, factory: AppFactory, mock_manifest):
        """Returns cached class when already loaded."""
        mock_get_loaded.return_value = mock_app_class = Mock()

        result = factory.load_class("test_app", mock_manifest, force_reload=False)

        assert result is mock_app_class
        mock_get_loaded.assert_called_once_with(mock_manifest.full_path, mock_manifest.class_name)

    @patch("hassette.core.app_factory.class_failed_to_load", return_value=True)
    def test_load_class_returns_none_when_previously_failed(self, mock_failed, factory: AppFactory, mock_manifest):
        """Returns None for previously failed classes."""
        result = factory.load_class("test_app", mock_manifest, force_reload=False)

        assert result is None

    @patch("hassette.core.app_factory.load_app_class_from_manifest")
    @patch("hassette.core.app_factory.class_already_loaded", return_value=True)
    def test_load_class_force_reload_clears_cache(
        self, mock_loaded, mock_load_class, factory: AppFactory, mock_manifest
    ):
        """Force reload attempts fresh load even if cached."""
        mock_load_class.return_value = mock_app_class = Mock()

        result = factory.load_class("test_app", mock_manifest, force_reload=True)

        assert result is mock_app_class
        mock_load_class.assert_called_once_with(mock_manifest, config=factory.hassette.config, force_reload=True)

    @patch("hassette.core.app_factory.load_app_class_from_manifest")
    def test_load_class_logs_error_on_failure(self, mock_load_class, factory: AppFactory, mock_manifest):
        """Returns None on load failure."""
        mock_load_class.side_effect = ImportError("Module not found")

        result = factory.load_class("test_app", mock_manifest, force_reload=False)

        assert result is None


class TestAppFactoryGetLoadError:
    @patch("hassette.core.app_factory.get_class_load_error")
    @patch("hassette.core.app_factory.class_failed_to_load", return_value=True)
    def test_get_load_error_returns_cached_exception(
        self, mock_failed, mock_get_error, factory: AppFactory, mock_manifest
    ):
        """Returns cached exception from app_utils."""
        cached_error = ValueError("Cached error")
        mock_get_error.return_value = cached_error

        result = factory.get_load_error(mock_manifest)

        assert result is cached_error

    def test_get_load_error_returns_runtime_error_if_no_cached(self, factory: AppFactory, mock_manifest):
        """Returns RuntimeError if no cached error."""
        result = factory.get_load_error(mock_manifest)

        assert isinstance(result, RuntimeError)
        assert "Unknown error" in str(result)


class TestAppFactoryNormalizeConfigs:
    def test_normalize_configs_none(self):
        """Returns empty list for None."""
        result = AppFactory.normalize_configs(None)
        assert result == []

    def test_normalize_configs_empty_dict(self):
        """Returns empty list for empty dict."""
        result = AppFactory.normalize_configs({})
        assert result == [{}]

    def test_normalize_configs_single_dict(self):
        """Wraps single dict in list."""
        config = {"instance_name": "test"}
        result = AppFactory.normalize_configs(config)
        assert result == [config]

    def test_normalize_configs_list(self):
        """Returns list as-is."""
        configs = [{"instance_name": "test1"}, {"instance_name": "test2"}]
        result = AppFactory.normalize_configs(configs)
        assert result == configs

    def test_normalize_configs_single_dict_returns_independent_copy(self):
        """Mutating the result of a single-dict input must not mutate the original."""
        config = {"instance_name": "test"}
        result = AppFactory.normalize_configs(config)

        result[0]["instance_name"] = "mutated"

        assert config["instance_name"] == "test"

    def test_normalize_configs_list_returns_independent_copies(self):
        """Mutating the result of a list input must not mutate the original list or dicts."""
        configs = [{"instance_name": "test1"}, {"instance_name": "test2"}]
        result = AppFactory.normalize_configs(configs)

        result.append({"instance_name": "test3"})
        result[0]["instance_name"] = "mutated"

        assert len(configs) == 2
        assert configs[0]["instance_name"] == "test1"
