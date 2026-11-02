"""Unit tests for AppFactory."""

from unittest.mock import Mock, patch

from hassette.core.app_factory import AppFactory
from hassette.core.app_lifecycle_common import ActionOutcomes
from hassette.schemas.app_outcomes import OutcomeResult
from tests.support.outcomes import AnyNameOutcomes

from .conftest import as_app_class, flag_names, make_app_class


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
        mock_registry: Mock,
        mock_manifest,
    ):
        """Successfully creates single app instance from dict config."""
        mock_load_class.return_value = mock_app_class = make_app_class()

        factory.create_instances("test_app", mock_manifest, outcomes=AnyNameOutcomes())

        mock_app_class.assert_called_once()
        mock_registry.register_app.assert_called_once_with("test_app", "test_instance", mock_app_class.return_value)

    @patch("hassette.core.app_factory.load_app_class_from_manifest")
    def test_create_instances_success_multiple_configs(
        self, mock_load_class, factory: AppFactory, mock_registry: Mock, mock_manifest
    ):
        """Creates multiple instances from list of configs."""
        mock_load_class.return_value = mock_app_class = make_app_class()
        mock_manifest.app_config = [
            {"instance_name": "instance_0"},
            {"instance_name": "instance_1"},
        ]

        factory.create_instances("test_app", mock_manifest, outcomes=AnyNameOutcomes())

        assert mock_app_class.call_count == 2
        assert mock_registry.register_app.call_count == 2
        mock_registry.register_app.assert_any_call("test_app", "instance_0", mock_app_class.return_value)
        mock_registry.register_app.assert_any_call("test_app", "instance_1", mock_app_class.return_value)

    @patch("hassette.core.app_factory.load_app_class_from_manifest")
    def test_create_instances_empty_config(
        self, mock_load_class, factory: AppFactory, mock_registry: Mock, mock_manifest
    ):
        """Handles empty/None app_config gracefully."""
        mock_manifest.app_config = None
        mock_load_class.return_value = mock_app_class = make_app_class()

        factory.create_instances("test_app", mock_manifest, outcomes=AnyNameOutcomes())

        mock_app_class.assert_not_called()
        mock_registry.register_app.assert_not_called()

    @patch("hassette.core.app_factory.class_failed_to_load", return_value=True)
    @patch("hassette.core.app_factory.get_class_load_error")
    def test_create_instances_class_load_failure(
        self, mock_get_error, mock_failed, factory: AppFactory, mock_registry: Mock, mock_manifest
    ):
        """Records failure against the first configured name when class loading fails."""
        cached_error = ValueError("Failed to load")
        mock_get_error.return_value = cached_error

        factory.create_instances("test_app", mock_manifest, outcomes=AnyNameOutcomes())

        mock_registry.record_failure.assert_called_once_with("test_app", "test_instance", cached_error)
        mock_registry.register_app.assert_not_called()

    @patch("hassette.core.app_factory.class_failed_to_load", return_value=True)
    @patch("hassette.core.app_factory.get_class_load_error")
    def test_create_instances_class_load_failure_reports_unoccupied_sibling(
        self, mock_get_error, mock_failed, factory: AppFactory, mock_registry: Mock, mock_manifest
    ):
        """When the first instance is already running (preserved) and class loading fails for a
        multi-instance app, the failure must be recorded against the first unstarted sibling
        instead of being swallowed entirely — otherwise a genuinely-failed second instance would
        report no FAILED status at all and look like an ordinary stopped instance (Codex P2 finding
        on #2245).
        """
        cached_error = ValueError("Failed to load")
        mock_get_error.return_value = cached_error
        mock_manifest.app_config = [
            {"instance_name": "instance_0"},
            {"instance_name": "instance_1"},
        ]
        existing_app = Mock()
        mock_registry.get = Mock(side_effect=lambda _key, name: existing_app if name == "instance_0" else None)

        factory.create_instances("test_app", mock_manifest, outcomes=AnyNameOutcomes())

        mock_registry.record_failure.assert_called_once_with("test_app", "instance_1", cached_error)
        mock_registry.register_app.assert_not_called()

    @patch("hassette.core.app_factory.class_failed_to_load", return_value=True)
    @patch("hassette.core.app_factory.get_class_load_error")
    def test_create_instances_class_load_failure_all_instances_occupied(
        self, mock_get_error, mock_failed, factory: AppFactory, mock_registry: Mock, mock_manifest
    ):
        """When every configured name already has a live entry, there is no unstarted instance
        to report the failure against -- skip recording entirely rather than overwriting a
        running instance's registry entry.
        """
        cached_error = ValueError("Failed to load")
        mock_get_error.return_value = cached_error
        mock_manifest.app_config = [{"instance_name": "instance_0"}]
        mock_registry.get = Mock(return_value=Mock())

        factory.create_instances("test_app", mock_manifest, outcomes=AnyNameOutcomes())

        mock_registry.record_failure.assert_not_called()
        mock_registry.register_app.assert_not_called()

    @patch("hassette.core.app_factory.load_app_class_from_manifest")
    def test_create_instances_validation_failure(
        self, mock_load_class, factory: AppFactory, mock_registry: Mock, mock_manifest
    ):
        """Records failure when Pydantic validation fails."""
        mock_app_class = Mock(__name__="TestApp")

        validation_error = ValueError("Validation failed")
        mock_app_class.app_config_cls.model_validate.side_effect = validation_error
        mock_load_class.return_value = mock_app_class

        factory.create_instances("test_app", mock_manifest, outcomes=AnyNameOutcomes())

        mock_registry.record_failure.assert_called_once_with("test_app", "test_instance", validation_error)
        mock_registry.register_app.assert_not_called()

    @patch("hassette.core.app_factory.load_app_class_from_manifest")
    def test_create_instances_app_create_failure(
        self, mock_load_class, factory: AppFactory, mock_registry: Mock, mock_manifest
    ):
        """Records failure when App() constructor raises exception."""
        create_error = RuntimeError("Create failed")
        mock_app_class = make_app_class(__name__="TestApp")

        mock_app_class.side_effect = create_error
        mock_load_class.return_value = mock_app_class
        factory.create_instances("test_app", mock_manifest, outcomes=AnyNameOutcomes())

        mock_registry.record_failure.assert_called_once_with("test_app", "test_instance", create_error)
        mock_registry.register_app.assert_not_called()

    @patch("hassette.core.app_factory.load_app_class_from_manifest")
    def test_create_instances_passes_manifest_to_constructor(self, mock_load_class, factory: AppFactory, mock_manifest):
        """Passes the section's manifest to the App constructor per instance (regression #1062)."""
        mock_load_class.return_value = mock_app_class = make_app_class()
        mock_manifest.app_config = [{"instance_name": "instance_0"}]

        factory.create_instances("test_app", mock_manifest, outcomes=AnyNameOutcomes())

        assert mock_app_class.call_args.kwargs["app_manifest"] is mock_manifest

    @patch("hassette.core.app_factory.load_app_class_from_manifest")
    def test_create_instances_passes_app_key_to_constructor(
        self, mock_load_class, factory: AppFactory, mock_manifest
    ) -> None:
        """Passes the app_key loop value to the App constructor (regression #1060)."""
        mock_load_class.return_value = mock_app_class = make_app_class()
        mock_manifest.app_config = [{"instance_name": "instance_0"}]

        factory.create_instances("kitchen_lights", mock_manifest, outcomes=AnyNameOutcomes())

        assert mock_app_class.call_args.kwargs["app_key"] == "kitchen_lights"

    @patch("hassette.core.app_factory.load_app_class_from_manifest")
    def test_create_instances_registers_each_app(
        self, mock_load_class, factory: AppFactory, mock_registry: Mock, mock_manifest
    ):
        """Verifies registry.register_app() called for each successful instance."""
        mock_manifest.app_config = [
            {"instance_name": "instance_0"},
            {"instance_name": "instance_1"},
            {"instance_name": "instance_2"},
        ]
        mock_load_class.return_value = make_app_class()

        factory.create_instances("test_app", mock_manifest, outcomes=AnyNameOutcomes())

        assert mock_registry.register_app.call_count == 3

    @patch("hassette.core.app_factory.load_app_class_from_manifest")
    @patch("hassette.core.app_factory.class_already_loaded", return_value=True)
    def test_create_instances_force_reload(self, mock_loaded, mock_load_class, factory: AppFactory, mock_manifest):
        """Passes force_reload=True through to load_class()."""
        mock_load_class.return_value = make_app_class()

        factory.create_instances("test_app", mock_manifest, force_reload=True, outcomes=AnyNameOutcomes())

        # When force_reload=True, should call load_app_class_from_manifest even if already loaded
        mock_load_class.assert_called_once_with(mock_manifest, config=factory.hassette.config, force_reload=True)

    @patch("hassette.core.app_factory.load_app_class_from_manifest")
    def test_create_instances_force_reload_ignored_when_instance_already_running(
        self, mock_load_class, factory: AppFactory, mock_registry: Mock, mock_manifest
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
        # "instance_0" is already running; "instance_1" is not.
        existing_app = Mock()
        mock_registry.get = Mock(side_effect=lambda _key, name: existing_app if name == "instance_0" else None)
        mock_registry.get_running_apps = Mock(return_value={"instance_0": existing_app})
        mock_load_class.return_value = make_app_class()

        factory.create_instances("test_app", mock_manifest, force_reload=True, outcomes=AnyNameOutcomes())

        # load_class() must be called with force_reload downgraded to False.
        mock_load_class.assert_called_once_with(mock_manifest, config=factory.hassette.config, force_reload=False)

    @patch("hassette.core.app_factory.load_app_class_from_manifest")
    def test_create_instances_force_reload_ignored_when_all_instances_occupied(
        self, mock_load_class, factory: AppFactory, mock_registry: Mock, mock_manifest
    ):
        """When every configured instance is already live, force_reload=True must not reload the
        class at all -- there is no instance left to apply a fresh class to, so reloading would
        only mutate the module/class cache for nothing.
        """
        mock_manifest.app_config = [{"instance_name": "instance_0"}]
        existing_app = Mock()
        mock_registry.get = Mock(return_value=existing_app)
        mock_registry.get_running_apps = Mock(return_value={"instance_0": existing_app})
        mock_load_class.return_value = make_app_class()

        created = factory.create_instances("test_app", mock_manifest, force_reload=True, outcomes=AnyNameOutcomes())

        mock_load_class.assert_not_called()
        assert created == set()

    @patch("hassette.core.app_factory.load_app_class_from_manifest")
    def test_create_instances_force_reload_ignored_for_unconfigured_running_orphan(
        self, mock_load_class, factory: AppFactory, mock_registry: Mock, mock_manifest
    ):
        """force_reload=True must also be downgraded when the only running instance of this
        app_key is under a name the *current* config no longer has (e.g. the config shrank
        from 2 instances to 1, leaving "instance_1" running as an orphan -- prune_stale_failed()
        only prunes stale failed entries, never running ones). The configured-name check alone
        would miss this and let the reload proceed, splitting the orphan and any newly-created
        configured instance across two class versions (Codex P2 finding on #2245, round 2).
        """
        mock_manifest.app_config = [{"instance_name": "instance_0"}]  # config shrank to 1 instance
        orphan = Mock()
        mock_registry.get = Mock(return_value=None)  # "instance_0" (the only configured name) is not live
        mock_registry.get_running_apps = Mock(return_value={"instance_1": orphan})  # not configured: an orphan
        mock_load_class.return_value = make_app_class()

        factory.create_instances("test_app", mock_manifest, force_reload=True, outcomes=AnyNameOutcomes())

        mock_load_class.assert_called_once_with(mock_manifest, config=factory.hassette.config, force_reload=False)

    @patch("hassette.core.app_factory.load_app_class_from_manifest")
    def test_create_instances_skips_already_running_instances(
        self, mock_load_class, factory: AppFactory, mock_registry: Mock, mock_manifest
    ):
        """create_instances skips names that already have a live registry entry, rather
        than overwriting them via register_app() and orphaning the originals' listeners,
        scheduler jobs, and tasks (#1688). Only names without a live entry are created.
        """
        mock_load_class.return_value = mock_app_class = make_app_class()
        mock_manifest.app_config = [
            {"instance_name": "instance_0"},
            {"instance_name": "instance_1"},
            {"instance_name": "instance_2"},
        ]
        # "instance_1" is already running; "instance_0" and "instance_2" are not.
        existing_app = Mock()
        mock_registry.get = Mock(side_effect=lambda _key, name: existing_app if name == "instance_1" else None)

        created = factory.create_instances("test_app", mock_manifest, outcomes=AnyNameOutcomes())

        # Only "instance_0" and "instance_2" should be created (2 calls, not 3).
        assert created == {"instance_0", "instance_2"}
        assert mock_app_class.call_count == 2
        assert mock_registry.register_app.call_count == 2
        mock_registry.register_app.assert_any_call("test_app", "instance_0", mock_app_class.return_value)
        mock_registry.register_app.assert_any_call("test_app", "instance_2", mock_app_class.return_value)


class TestAppFactoryNeedsRestartGate:
    THREE_INSTANCES = (
        {"instance_name": "instance_0"},
        {"instance_name": "instance_1"},
        {"instance_name": "instance_2"},
    )

    @patch("hassette.core.app_factory.load_app_class_from_manifest")
    def test_flagged_instance_is_skipped_and_siblings_are_created(
        self, mock_load_class, factory: AppFactory, mock_registry: Mock, mock_manifest, caplog
    ):
        """A flagged instance gets no replacement and a refused outcome, logged by nobody here; siblings are created."""
        mock_load_class.return_value = make_app_class()
        mock_manifest.app_config = list(self.THREE_INSTANCES)
        flag_names(mock_registry, "instance_1")
        outcomes = ActionOutcomes({"instance_0": 0, "instance_1": 1, "instance_2": 2})

        created = factory.create_instances("test_app", mock_manifest, outcomes=outcomes)

        assert created == {"instance_0", "instance_2"}
        assert sorted(c.args[1] for c in mock_registry.register_app.call_args_list) == ["instance_0", "instance_2"]
        assert [(o.instance_index, o.result, o.needs_restart, o.reason) for o in outcomes.snapshot()] == [
            (1, OutcomeResult.REFUSED, True, "refused instance_1")
        ]
        assert not [r for r in caplog.records if r.levelname == "ERROR"]

    @patch("hassette.core.app_factory.load_app_class_from_manifest")
    def test_every_instance_flagged_refuses_before_loading_the_class(
        self, mock_load_class, factory: AppFactory, mock_registry: Mock, mock_manifest, caplog
    ):
        """With every configured instance flagged there is nothing to create: the class isn't loaded (not even
        on a forced reload) and no class-load failure is recorded over a flag.
        """
        mock_manifest.app_config = list(self.THREE_INSTANCES[:2])
        flag_names(mock_registry, "instance_0", "instance_1")

        outcomes = AnyNameOutcomes()

        created = factory.create_instances("test_app", mock_manifest, force_reload=True, outcomes=outcomes)

        assert created == set()
        mock_load_class.assert_not_called()
        mock_registry.record_failure.assert_not_called()
        assert [o.result for o in outcomes.snapshot()] == [OutcomeResult.REFUSED, OutcomeResult.REFUSED]
        assert not [r for r in caplog.records if r.levelname == "ERROR"]

    @patch("hassette.core.app_factory.load_app_class_from_manifest")
    def test_flagged_and_live_instances_with_nothing_to_create_refuse_before_loading_the_class(
        self, mock_load_class, factory: AppFactory, mock_registry: Mock, mock_manifest, caplog
    ):
        """A live instance plus a flagged one leaves nothing to create: no class load (not even forced), no
        class-load failure recorded, and one refusal for the flagged instance.
        """
        mock_manifest.app_config = list(self.THREE_INSTANCES[:2])
        existing_app = Mock()
        mock_registry.get = Mock(side_effect=lambda _key, name: existing_app if name == "instance_0" else None)
        mock_registry.get_running_apps = Mock(return_value={"instance_0": existing_app})
        flag_names(mock_registry, "instance_1")

        outcomes = AnyNameOutcomes()

        created = factory.create_instances("test_app", mock_manifest, force_reload=True, outcomes=outcomes)

        assert created == set()
        mock_load_class.assert_not_called()
        mock_registry.record_failure.assert_not_called()
        assert [(o.result, o.reason) for o in outcomes.snapshot()] == [
            (OutcomeResult.SUCCEEDED, "already running"),
            (OutcomeResult.REFUSED, "refused instance_1"),
        ]
        assert not [r for r in caplog.records if r.levelname == "ERROR"]

    @patch("hassette.core.app_factory.class_failed_to_load", return_value=True)
    @patch("hassette.core.app_factory.get_class_load_error")
    def test_class_load_failure_skips_flagged_instance_when_choosing_where_to_record(
        self, mock_get_error, mock_failed, factory: AppFactory, mock_registry: Mock, mock_manifest
    ):
        """A class-load failure is recorded against the first instance that is neither running nor flagged."""
        mock_get_error.return_value = cached_error = ValueError("Failed to load")
        mock_manifest.app_config = list(self.THREE_INSTANCES)
        existing_app = Mock()
        mock_registry.get = Mock(side_effect=lambda _key, name: existing_app if name == "instance_1" else None)
        flag_names(mock_registry, "instance_0")

        factory.create_instances("test_app", mock_manifest, outcomes=AnyNameOutcomes())

        mock_registry.record_failure.assert_called_once_with("test_app", "instance_2", cached_error)

    @patch("hassette.core.app_factory.class_failed_to_load", return_value=True)
    @patch("hassette.core.app_factory.get_class_load_error")
    def test_class_load_failure_fails_every_instance_left_to_create(
        self, mock_get_error, mock_failed, factory: AppFactory, mock_registry: Mock, mock_manifest
    ):
        """One shared class serves every instance, so its load failure fails each instance left to create."""
        mock_get_error.return_value = ValueError("Failed to load")
        mock_manifest.app_config = list(self.THREE_INSTANCES)
        flag_names(mock_registry, "instance_0")
        outcomes = AnyNameOutcomes()

        factory.create_instances("test_app", mock_manifest, outcomes=outcomes)

        assert [(o.instance_index, o.result, o.reason) for o in outcomes.snapshot()] == [
            (0, OutcomeResult.REFUSED, "refused instance_0"),
            (1, OutcomeResult.FAILED, "the app class failed to load: Failed to load"),
            (2, OutcomeResult.FAILED, "the app class failed to load: Failed to load"),
        ]


class TestAppFactoryCreateSingleInstance:
    def test_create_single_instance_success(self, factory: AppFactory, mock_registry: Mock, mock_manifest):
        """Registers the instance under the given name on success."""
        mock_app_class = make_app_class()
        mock_manifest.app_config = [{"instance_name": "first"}, {"instance_name": "second"}]

        factory.create_single_instance(
            "test_app", mock_manifest, "second", as_app_class(mock_app_class), outcomes=AnyNameOutcomes()
        )

        mock_app_class.assert_called_once()
        assert mock_app_class.call_args.kwargs["index"] == 1
        mock_registry.register_app.assert_called_once_with("test_app", "second", mock_app_class.return_value)
        mock_registry.record_failure.assert_not_called()

    def test_create_single_instance_validation_failure_records_the_name(
        self, factory: AppFactory, mock_registry: Mock, mock_manifest
    ):
        """Records the failure under the instance's name when Pydantic validation fails."""
        mock_app_class = Mock(__name__="TestApp")
        validation_error = ValueError("Validation failed")
        mock_app_class.app_config_cls.model_validate.side_effect = validation_error
        mock_manifest.app_config = [{"instance_name": "first"}, {"instance_name": "second"}]

        factory.create_single_instance(
            "test_app", mock_manifest, "second", as_app_class(mock_app_class), outcomes=AnyNameOutcomes()
        )

        mock_registry.record_failure.assert_called_once_with("test_app", "second", validation_error)
        mock_registry.register_app.assert_not_called()

    def test_create_single_instance_app_create_failure_records_the_name(
        self, factory: AppFactory, mock_registry: Mock, mock_manifest
    ):
        """Records the failure under the instance's name when the App() constructor raises."""
        create_error = RuntimeError("Create failed")
        mock_app_class = make_app_class(__name__="TestApp")
        mock_app_class.side_effect = create_error
        mock_manifest.app_config = [{"instance_name": "first"}, {"instance_name": "second"}]

        factory.create_single_instance(
            "test_app", mock_manifest, "second", as_app_class(mock_app_class), outcomes=AnyNameOutcomes()
        )

        mock_registry.record_failure.assert_called_once_with("test_app", "second", create_error)
        mock_registry.register_app.assert_not_called()


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
