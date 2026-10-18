"""Characterization tests pinning the wired shape of ``create_hassette_stub()``.

Web/API tests exercise most of this stub indirectly; these pin the wiring that a
silent regression would turn back into MagicMock's auto-truthy defaults.
"""

from unittest.mock import AsyncMock

from hassette_wire import ResourceStatus

from hassette.config.models import DEFAULT_WEB_API_PORT
from hassette.schemas.app_snapshots import AppStatusSnapshot
from tests.support.web_mocks import create_hassette_stub


class TestPublicPrivateAliases:
    def test_public_service_attributes_alias_private_ones(self):
        h = create_hassette_stub()
        assert h.state_proxy is h._state_proxy
        assert h.websocket_service is h._websocket_service
        assert h.app_handler is h._app_handler
        assert h.app_bootstrap_coordinator is h._app_bootstrap_coordinator
        assert h.bus_service is h._bus_service
        assert h.scheduler_service is h._scheduler_service
        assert h.runtime_query_service is h._runtime_query_service
        assert h.database_service is h._database_service
        assert h.telemetry_query_service is h._telemetry_query_service


class TestRootFields:
    def test_root_fields_are_concrete(self):
        h = create_hassette_stub()
        assert h._fatal_shutdown_reason is None
        assert h.fatal_shutdown_reason is None
        assert isinstance(h.loop_thread_id, int)
        assert h.children == []
        assert h.get_drop_counters() == (0, 0, 0)
        assert h.get_log_queue_drops() == 0
        assert h.get_db_write_queue_drops() == 0
        assert h.is_log_persistence_active() is True


class TestConfig:
    def test_config_attributes_follow_arguments(self):
        h = create_hassette_stub(
            run_web_api=False,
            run_web_ui=False,
            cors_origins=("http://a",),
            auth_enabled=True,
            log_level="DEBUG",
            dev_mode=False,
            allow_reload_in_prod=True,
        )
        cfg = h.config
        assert cfg.dev_mode is False
        assert cfg.allow_reload_in_prod is True
        assert cfg.web_api.run is False
        assert cfg.web_api.run_ui is False
        assert cfg.web_api.port == DEFAULT_WEB_API_PORT
        assert cfg.web_api.cors_origins == ("http://a",)
        assert cfg.web_api.auth_enabled is True
        assert cfg.logging.log_level == "DEBUG"
        assert cfg.logging.web_api == "DEBUG"

    def test_model_dump_mirrors_attributes(self):
        h = create_hassette_stub(cors_origins=("http://a",), auth_enabled=True, log_level="DEBUG")
        dump = h.config.model_dump(mode="json")
        cfg = h.config
        assert dump["dev_mode"] == cfg.dev_mode
        assert dump["base_url"] == cfg.base_url
        assert dump["data_dir"] == cfg.data_dir
        assert dump["config_dir"] == cfg.config_dir
        assert dump["token"] is None
        assert dump["web_api"]["cors_origins"] == ["http://a"]
        assert dump["web_api"]["auth_enabled"] is True
        assert dump["web_api"]["port"] == cfg.web_api.port
        assert dump["logging"] == {"log_level": "DEBUG", "web_api": "DEBUG"}
        assert dump["lifecycle"]["startup_timeout_seconds"] == cfg.lifecycle.startup_timeout_seconds
        assert dump["apps"] == {"autodetect": cfg.apps.autodetect, "directory": cfg.apps.directory}
        assert dump["scheduler"]["behind_schedule_threshold_seconds"] == cfg.scheduler.behind_schedule_threshold_seconds
        assert dump["file_watcher"]["debounce_milliseconds"] == cfg.file_watcher.debounce_milliseconds
        assert set(dump) >= {"database", "websocket", "blocking_io"}


class TestStateProxy:
    def test_get_state_and_domain_states_read_the_states_dict(self):
        states = {"light.a": {"state": "on"}, "switch.b": {"state": "off"}}
        h = create_hassette_stub(states=states)
        assert h.state_proxy.get_state("light.a") == {"state": "on"}
        assert h.state_proxy.get_state("light.missing") is None
        assert h.state_proxy.get_domain_states("light") == {"light.a": {"state": "on"}}

    def test_readiness_flags(self):
        h = create_hassette_stub(is_ready=False, has_state_capability=False)
        assert h.state_proxy.is_ready() is False
        assert h.state_proxy.has_initial_state_capability() is False


class TestWebsocketAndBootstrap:
    def test_connected_websocket(self):
        h = create_hassette_stub()
        assert h.websocket_service._status == ResourceStatus.RUNNING
        assert h.websocket_service.is_connected is True

    async def test_disconnected_websocket(self):
        h = create_hassette_stub(websocket_connected=False)
        ws = h.websocket_service
        assert ws._status == ResourceStatus.RUNNING
        assert ws.is_connected is False
        assert ws.has_ever_connected is False
        assert ws.get_connected_generation() is None
        assert await ws.wait_connected() is False
        assert await ws.wait_connected_generation() is None
        assert not ws._connected_event.is_set()
        assert not ws._send_ready_event.is_set()

    async def test_bootstrap_defaults_to_state_capability(self):
        h = create_hassette_stub(has_state_capability=False)
        assert h.app_bootstrap_coordinator.is_released() is False
        assert await h.app_bootstrap_coordinator.wait_released() is False

    async def test_bootstrap_explicit_override(self):
        h = create_hassette_stub(has_state_capability=False, bootstrap_released=True)
        assert h.app_bootstrap_coordinator.is_released() is True
        assert await h.app_bootstrap_coordinator.wait_released() is True


class TestAppHandler:
    def test_registry_containers_are_real_and_empty(self):
        h = create_hassette_stub()
        registry = h.app_handler.registry
        assert registry.manifests == {}
        assert registry.only_apps == frozenset()
        assert registry.get_failed_instance_infos() == {}
        assert h.app_handler.is_action_in_progress() is False
        assert registry.get_full_snapshot() is not None

    def test_status_snapshot_default_and_override(self):
        assert isinstance(create_hassette_stub().app_handler.get_status_snapshot(), AppStatusSnapshot)
        snap = AppStatusSnapshot()
        assert create_hassette_stub(old_snapshot=snap).app_handler.get_status_snapshot() is snap

    def test_app_action_mocks(self):
        h = create_hassette_stub(app_action_mocks=True)
        for name in ("start_app", "stop_app", "reload_app", "start_instance", "stop_instance", "reload_instance"):
            assert isinstance(getattr(h.app_handler, name), AsyncMock)


class TestBusSchedulerDatabase:
    def test_bus_stub_defaults(self):
        h = create_hassette_stub()
        assert h.bus_service.live_execution_counts() == {}
        assert h.bus_service.pending_wait_for_count == 0

    async def test_scheduler_jobs_override(self):
        jobs = [object()]
        assert await create_hassette_stub(scheduler_jobs=jobs).scheduler_service.get_all_jobs() == jobs

    async def test_database_submit_returns_empty(self):
        assert await create_hassette_stub().database_service.submit() == []

    async def test_scheduler_jobs_default_empty(self):
        assert await create_hassette_stub().scheduler_service.get_all_jobs() == []
