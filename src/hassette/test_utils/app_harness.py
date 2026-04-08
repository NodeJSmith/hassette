"""AppTestHarness — async context manager for end-user app testing.

Wires a user's App class into the Hassette test infrastructure with a minimal,
hermetically-validated config. Provides the app instance, bus, scheduler,
api_recorder, and states as attributes after entry.

Typical usage::

    async with AppTestHarness(MotionLights, config={"motion_entity": "binary_sensor.test"}) as harness:
        await harness.simulate_state_change(
            "binary_sensor.test", old_value="off", new_value="on"
        )
        harness.api_recorder.assert_called("turn_on", entity_id="light.kitchen")

See design/specs/2033-end-user-test-utils/design.md for architecture details.
"""

import contextlib
import inspect
import logging
import tempfile
from contextlib import AsyncExitStack
from pathlib import Path
from typing import TYPE_CHECKING, Any, ClassVar, cast
from unittest.mock import AsyncMock

if TYPE_CHECKING:
    from hassette import Hassette
    from hassette.events import HassStateDict

import pydantic
from pydantic_settings.sources import InitSettingsSource

from hassette import context
from hassette.app.app import App
from hassette.app.app_config import AppConfig
from hassette.app.utils import _get_app_config_class
from hassette.bus import Bus
from hassette.config.classes import AppManifest
from hassette.config.config import HassetteConfig
from hassette.scheduler import Scheduler
from hassette.state_manager import StateManager
from hassette.test_utils.harness import HassetteHarness, wait_for
from hassette.test_utils.helpers import create_call_service_event, create_state_change_event, make_state_dict
from hassette.test_utils.recording_api import RecordingApi
from hassette.types.enums import ResourceStatus

LOGGER = logging.getLogger(__name__)


class AppConfigurationError(Exception):
    """Raised when the config dict fails validation against the app's AppConfig subclass.

    Attributes:
        app_cls: The App class whose config failed validation.
        original_error: The underlying pydantic ValidationError.
    """

    app_cls: type[App]
    original_error: pydantic.ValidationError

    def __init__(self, app_cls: type[App], original_error: pydantic.ValidationError) -> None:
        self.app_cls = app_cls
        self.original_error = original_error
        count = original_error.error_count()
        errors = original_error.errors()
        # Build a compact summary of the first error
        first = errors[0] if errors else {}
        field = ".".join(str(loc) for loc in first.get("loc", ())) or "<unknown>"
        msg_detail = first.get("msg", "")
        summary = f"{count} validation error{'s' if count != 1 else ''} — field '{field}': {msg_detail}"
        super().__init__(f"AppConfigurationError for {app_cls.__name__}: {summary}")


def _make_hermetic_config(
    app_cls: type[App], app_config_cls: type[AppConfig], config_dict: dict[str, Any]
) -> AppConfig:
    """Validate config_dict against app_config_cls using only InitSettingsSource.

    Creates a transient subclass that suppresses env var, .env file, and all other
    settings sources, leaving only the provided dict. Runs full Pydantic validation.

    Args:
        app_cls: The App class (used in error messages).
        app_config_cls: The AppConfig subclass to validate against.
        config_dict: Dict of config key/value pairs to validate.

    Returns:
        A validated AppConfig instance.

    Raises:
        AppConfigurationError: If validation fails.
    """

    class _HermeticSettings(app_config_cls):  # pyright: ignore[reportGeneralTypeIssues]
        @classmethod
        def settings_customise_sources(cls, settings_cls, **_kwargs):  # pyright: ignore[reportIncompatibleMethodOverride]
            return (InitSettingsSource(settings_cls, init_kwargs=config_dict),)

    try:
        return _HermeticSettings()
    except pydantic.ValidationError as e:
        raise AppConfigurationError(app_cls, e) from e


def _make_minimal_hassette_config(data_dir: Path) -> HassetteConfig:
    """Create a minimal HassetteConfig suitable for unit testing.

    Suppresses env vars, .env file, TOML file, and CLI args. Uses only init_kwargs.
    State proxy polling is disabled to prevent _load_cache() from overwriting seeded state.

    Args:
        data_dir: Directory for Hassette data (caches, etc.).

    Returns:
        A minimal HassetteConfig instance.
    """

    class _HermeticHassetteConfig(HassetteConfig):
        model_config = HassetteConfig.model_config.copy() | {
            "cli_parse_args": False,
            "toml_file": None,
            "env_file": None,
        }

        @classmethod
        def settings_customise_sources(cls, settings_cls, **_kwargs):  # pyright: ignore[reportIncompatibleMethodOverride]
            return (
                InitSettingsSource(
                    settings_cls,
                    init_kwargs={
                        "token": "test-token",
                        "base_url": "http://test.invalid:8123",
                        "data_dir": data_dir,
                        "disable_state_proxy_polling": True,
                        "autodetect_apps": False,
                        "run_web_api": False,
                        "run_app_precheck": False,
                    },
                ),
            )

    return _HermeticHassetteConfig()


def _synthesize_manifest(app_cls: type[App]) -> AppManifest:
    """Build a minimal AppManifest for app_cls without requiring a real file or TOML config.

    Derives app_key from the class name (snake_case), filename from the source file's parent
    directory, and class_name from __name__. Falls back to Path.cwd() with a warning if
    inspect.getfile() raises TypeError (namespace packages or C extensions).

    Args:
        app_cls: The App subclass to synthesize a manifest for.

    Returns:
        A synthesized AppManifest.
    """
    class_name = app_cls.__name__
    # Convert CamelCase to snake_case for app_key
    import re

    app_key = re.sub(r"(?<!^)(?=[A-Z])", "_", class_name).lower()

    try:
        source_file = Path(inspect.getfile(app_cls))
        app_dir = source_file.parent
        filename = source_file.name
    except TypeError:
        LOGGER.warning(
            "Could not determine source file for %s (namespace package or C extension). Using cwd() as app_dir.",
            class_name,
        )
        app_dir = Path.cwd()
        filename = f"{app_key}.py"

    full_path = app_dir / filename

    return AppManifest(
        app_key=app_key,
        filename=filename,
        class_name=class_name,
        app_dir=app_dir,
        full_path=full_path,
        app_config=[{"instance_name": f"{class_name}.0"}],
    )


class AppTestHarness:
    """Async context manager that wires an App class into Hassette test infrastructure.

    Provides a fully initialized app instance with access to its bus, scheduler,
    api_recorder, and states. Handles teardown in the correct LIFO order via
    AsyncExitStack.

    Usage::

        async with AppTestHarness(MyApp, config={"my_setting": "value"}) as harness:
            harness.app      # MyApp instance
            harness.bus      # test Bus
            harness.scheduler  # test Scheduler
            harness.api_recorder  # RecordingApi — records calls your app makes
            harness.states   # StateManager

    Note:
        Mutates class-level attributes (app_manifest, _api_factory) with save/restore.
        Safe for sequential tests and xdist workers. NOT safe for concurrent use within
        the same process for the same App class.
    """

    # Class-level sentinel for "not set" — distinguishes None from "attribute absent"
    _UNSET: ClassVar[object] = object()

    def __init__(
        self,
        app_cls: type[App],
        config: dict[str, Any],
        *,
        tmp_path: Path | None = None,
    ) -> None:
        """Store args. No resource allocation.

        Args:
            app_cls: The App subclass to instantiate and test.
            config: Dict of config values to validate against app_cls.app_config_cls.
            tmp_path: Optional directory for Hassette data. Auto-created and cleaned
                up if not provided.
        """
        self._app_cls = app_cls
        self._config_dict = config
        self._tmp_path = tmp_path

        # Set during __aenter__
        self._exit_stack: AsyncExitStack | None = None
        self._harness: HassetteHarness | None = None
        self._app: App | None = None
        self._token = None  # Token from context.set_global_hassette()

    async def __aenter__(self) -> "AppTestHarness":
        """Set up the full harness in 12 steps with LIFO teardown via AsyncExitStack."""
        exit_stack = AsyncExitStack()
        self._exit_stack = exit_stack

        try:
            await self._setup(exit_stack)
        except Exception:
            await exit_stack.aclose()
            self._exit_stack = None
            raise

        return self

    async def _setup(self, exit_stack: AsyncExitStack) -> None:
        """Execute all setup steps, registering teardown callbacks as we go."""

        # Step 1: Resolve data directory
        if self._tmp_path is not None:
            data_dir = self._tmp_path
        else:
            data_dir = Path(tempfile.mkdtemp(prefix="hassette_test_"))
            exit_stack.callback(self._cleanup_tmpdir, data_dir)

        # Step 2: Create minimal HassetteConfig
        hassette_config = _make_minimal_hassette_config(data_dir)

        # Step 3: Validate user config hermetically.
        # Use _get_app_config_class to resolve the generic type argument (App[MyConfig])
        # even when app_config_cls is not set as a class attribute (e.g. inline test classes).
        app_config_cls = _get_app_config_class(self._app_cls)
        validated_config = _make_hermetic_config(self._app_cls, app_config_cls, self._config_dict)

        # Step 4: Create HassetteHarness (skip_global_set=True — we handle ContextVar below)
        harness = (
            HassetteHarness(
                hassette_config,
                skip_global_set=True,
            )
            .with_bus()
            .with_scheduler()
            .with_state_proxy()
            .with_state_registry()
        )
        self._harness = harness

        # Step 5: Pre-configure hassette.api mock before state proxy starts.
        # HassetteHarness.start() checks "if not self.hassette.api" before setting it,
        # so we set it here first with get_states_raw returning [] to prevent
        # StateProxy._load_cache() from failing when on_initialize() runs.
        api_mock = AsyncMock()
        api_mock.sync = AsyncMock()
        api_mock.get_states_raw = AsyncMock(return_value=[])
        harness.hassette.api = api_mock

        # Step 6: Start harness — registers stop() as teardown (early registration = late unwind)
        await harness.start()
        exit_stack.push_async_callback(harness.stop)

        # Step 7: Set global hassette ContextVar — store token for reset on teardown
        token = context.set_global_hassette(cast("Hassette", harness.hassette))  # pyright: ignore[reportArgumentType]
        if token is not None:
            exit_stack.callback(context.HASSETTE_INSTANCE.reset, token)

        # Step 8: Mark state proxy ready
        state_proxy = harness.hassette._state_proxy
        if state_proxy is None:
            raise RuntimeError("StateProxy was not started — ensure with_state_proxy() is called")
        state_proxy.mark_ready(reason="AppTestHarness: mark ready for test")

        # Step 9: Synthesize AppManifest and set on class with save/restore
        manifest = _synthesize_manifest(self._app_cls)
        original_manifest = getattr(self._app_cls, "app_manifest", self._UNSET)
        self._app_cls.app_manifest = manifest
        exit_stack.callback(self._restore_manifest, original_manifest)

        # Step 10: Set _api_factory on class with save/restore
        original_api_factory = getattr(self._app_cls, "_api_factory", self._UNSET)
        self._app_cls._api_factory = RecordingApi  # pyright: ignore[reportAttributeAccessIssue]
        exit_stack.callback(self._restore_api_factory, original_api_factory)

        # Step 11: Instantiate the app
        app = self._app_cls(
            hassette=harness.hassette,  # pyright: ignore[reportArgumentType]
            app_config=validated_config,
            index=0,
        )

        # Add app as child of hassette mock
        harness.hassette.children.append(app)
        app.parent = harness.hassette  # pyright: ignore[reportAttributeAccessIssue]

        self._app = app

        # Step 12: Register app shutdown first (late registration = early unwind)
        # This ensures app shuts down before harness.stop() runs
        exit_stack.push_async_callback(app.shutdown)

        # Start the app lifecycle
        app.start()
        await wait_for(
            lambda: app.status == ResourceStatus.RUNNING,
            desc=f"{app.class_name} RUNNING",
            timeout=5.0,
        )

    def _cleanup_tmpdir(self, data_dir: Path) -> None:
        """Remove auto-created tmpdir on teardown."""
        import shutil

        try:
            shutil.rmtree(data_dir, ignore_errors=True)
        except Exception as e:
            LOGGER.warning("Failed to clean up tmpdir %s: %s", data_dir, e)

    def _restore_manifest(self, original: Any) -> None:
        """Restore app_cls.app_manifest to its original value."""
        if original is self._UNSET:
            if hasattr(self._app_cls, "app_manifest"):
                with contextlib.suppress(AttributeError):
                    del self._app_cls.app_manifest
        else:
            self._app_cls.app_manifest = original

    def _restore_api_factory(self, original: Any) -> None:
        """Restore app_cls._api_factory to its original value."""
        if original is self._UNSET:
            self._app_cls._api_factory = None  # pyright: ignore[reportAttributeAccessIssue]
        else:
            self._app_cls._api_factory = original  # pyright: ignore[reportAttributeAccessIssue]

    async def __aexit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        """Delegate teardown to the AsyncExitStack (LIFO order)."""
        if self._exit_stack is not None:
            await self._exit_stack.__aexit__(exc_type, exc, tb)
            self._exit_stack = None

    # ------------------------------------------------------------------
    # Convenience properties
    # ------------------------------------------------------------------

    @property
    def app(self) -> App:
        """The fully initialized App instance."""
        if self._app is None:
            raise RuntimeError("AppTestHarness is not active — use 'async with AppTestHarness(...) as harness'")
        return self._app

    @property
    def bus(self) -> Bus:
        """The test Bus owned by the app."""
        return self.app.bus

    @property
    def scheduler(self) -> Scheduler:
        """The test Scheduler owned by the app."""
        return self.app.scheduler

    @property
    def api_recorder(self) -> RecordingApi:
        """The RecordingApi injected into the app (records calls the app makes)."""
        api = self.app.api
        if not isinstance(api, RecordingApi):
            raise RuntimeError(
                f"Expected app.api to be a RecordingApi but got {type(api).__name__}. "
                "Ensure _api_factory was set before app instantiation."
            )
        return api

    @property
    def states(self) -> StateManager:
        """The StateManager owned by the app."""
        return self.app.states

    # ------------------------------------------------------------------
    # State seeding helpers
    # ------------------------------------------------------------------

    async def set_state(self, entity_id: str, state: str, **attributes: Any) -> None:
        """Seed an entity's state in the StateProxy.

        Uses make_state_dict() internally with a past sentinel timestamp
        (1970-01-01T00:00:00Z) so that any subsequent simulate_state_change()
        with a current or future timestamp always supersedes the seeded value.

        This is for pre-test setup only and does NOT fire bus events.

        Args:
            entity_id: The entity ID to seed (e.g., "light.kitchen").
            state: The state value (e.g., "on", "off", "25.5").
            **attributes: Entity attribute key/value pairs.
        """
        harness = self._harness
        if harness is None:
            raise RuntimeError("AppTestHarness is not active")
        state_proxy = harness.hassette._state_proxy
        if state_proxy is None:
            raise RuntimeError("StateProxy is not available — ensure with_state_proxy() was called")
        state_dict = cast(
            "HassStateDict",
            make_state_dict(
                entity_id,
                state,
                dict(attributes),
                "1970-01-01T00:00:00+00:00",
                "1970-01-01T00:00:00+00:00",
            ),
        )
        await state_proxy._test_seed_state(entity_id, state_dict)

    async def set_states(self, states: dict[str, str | tuple[str, dict]]) -> None:
        """Seed multiple entities at once.

        Example::

            harness.set_states({
                "light.kitchen": "on",
                "sensor.temp": ("25.5", {"unit_of_measurement": "°C"}),
            })

        Args:
            states: Dict mapping entity_id to state string or (state, attrs) tuple.
        """
        for entity_id, value in states.items():
            if isinstance(value, tuple):
                state, attrs = value
                await self.set_state(entity_id, state, **attrs)
            else:
                await self.set_state(entity_id, value)

    # ------------------------------------------------------------------
    # Event simulation helpers
    # ------------------------------------------------------------------

    async def simulate_state_change(
        self,
        entity_id: str,
        *,
        old_value: Any,
        new_value: Any,
        old_attrs: dict | None = None,
        new_attrs: dict | None = None,
        timeout: float = 2.0,
    ) -> None:
        """Create a state change event and send it through the bus.

        Waits for all triggered handlers to complete by polling the task bucket
        until empty, with a configurable timeout.

        Args:
            entity_id: The entity ID that changed.
            old_value: Previous state value.
            new_value: New state value.
            old_attrs: Previous attributes dict (optional).
            new_attrs: New attributes dict (optional).
            timeout: Maximum seconds to wait for handlers to complete.
        """
        harness = self._harness
        if harness is None:
            raise RuntimeError("AppTestHarness is not active")

        event = create_state_change_event(
            entity_id=entity_id,
            old_value=old_value,
            new_value=new_value,
            old_attrs=old_attrs,
            new_attrs=new_attrs,
        )
        await harness.hassette.send_event(event.topic, event)
        await self._drain_task_bucket(timeout=timeout)

    async def simulate_attribute_change(
        self,
        entity_id: str,
        attribute: str,
        *,
        old_value: Any,
        new_value: Any,
        timeout: float = 2.0,
    ) -> None:
        """Create an attribute change event and send it through the bus.

        Args:
            entity_id: The entity ID whose attribute changed.
            attribute: The attribute name.
            old_value: Previous attribute value.
            new_value: New attribute value.
            timeout: Maximum seconds to wait for handlers to complete.
        """
        old_attrs = {attribute: old_value}
        new_attrs = {attribute: new_value}
        await self.simulate_state_change(
            entity_id,
            old_value="unknown",
            new_value="unknown",
            old_attrs=old_attrs,
            new_attrs=new_attrs,
            timeout=timeout,
        )

    async def simulate_call_service(
        self,
        domain: str,
        service: str,
        timeout: float = 2.0,
        **data: Any,
    ) -> None:
        """Create a call_service event and send it through the bus.

        Args:
            domain: Service domain (e.g., "light").
            service: Service name (e.g., "turn_on").
            timeout: Maximum seconds to wait for handlers to complete.
            **data: Service call data.
        """
        harness = self._harness
        if harness is None:
            raise RuntimeError("AppTestHarness is not active")

        event = create_call_service_event(domain=domain, service=service, service_data=data)
        await harness.hassette.send_event(event.topic, event)  # pyright: ignore[reportAttributeAccessIssue]
        await self._drain_task_bucket(timeout=timeout)

    async def _drain_task_bucket(self, *, timeout: float = 2.0) -> None:
        """Wait until all bus-dispatched handler tasks have completed.

        Yields control to the event loop (allowing BusService's serve() to process
        the event and call dispatch, which spawns _dispatch tasks). Then waits until
        only the BusService's long-running serve() task remains in the bucket
        (all handler dispatch tasks have finished).

        The BusService task bucket always contains at least 1 long-running task (serve()),
        so we wait for the count to drop back to ≤1, not 0.

        Args:
            timeout: Maximum seconds to wait.
        """
        import asyncio

        harness = self._harness
        if harness is None:
            raise RuntimeError("AppTestHarness is not active")

        # Yield to let BusService.serve() pick up the queued event and run dispatch().
        # dispatch() spawns _dispatch tasks and returns. Multiple yields are needed to
        # let the anyio memory channel route the event through EventStreamService to
        # BusService, then for BusService to call dispatch, then for dispatch tasks to run.
        for _ in range(10):
            await asyncio.sleep(0)

        # Wait for dispatch tasks to complete. BusService.task_bucket always has the
        # serve() task running (count=1), so we wait for count to reach ≤1.
        bus_service = harness.hassette._bus_service
        if bus_service is not None:
            await wait_for(
                lambda: len(bus_service.task_bucket) <= 1,
                timeout=timeout,
                desc="bus dispatch tasks drained",
            )

        # Extra yields to let any tasks spawned by handlers complete (e.g., app.api.turn_on).
        for _ in range(5):
            await asyncio.sleep(0)
