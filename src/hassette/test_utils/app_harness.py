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

import asyncio
import contextlib
import inspect
import logging
import re
import shutil
import tempfile
import threading
import weakref
from contextlib import AsyncExitStack
from pathlib import Path
from typing import TYPE_CHECKING, Any, ClassVar, cast
from unittest.mock import AsyncMock, patch

if TYPE_CHECKING:
    from hassette import Hassette
    from hassette.core.bus_service import BusService
    from hassette.events import HassStateDict

import pydantic
from pydantic import BaseModel
from pydantic_settings.sources import InitSettingsSource
from whenever import Instant, ZonedDateTime

from hassette import context
from hassette.app.app import App
from hassette.app.app_config import AppConfig
from hassette.app.utils import _get_app_config_class
from hassette.bus import Bus
from hassette.config.classes import AppManifest
from hassette.scheduler import Scheduler
from hassette.state_manager import StateManager
from hassette.test_utils.config import make_test_config
from hassette.test_utils.exceptions import DrainError, DrainTimeout
from hassette.test_utils.harness import HassetteHarness, wait_for
from hassette.test_utils.helpers import create_call_service_event, create_state_change_event, make_state_dict
from hassette.test_utils.recording_api import _RECORD_TYPE_TO_DOMAIN, RecordingApi
from hassette.types.enums import ResourceStatus

LOGGER = logging.getLogger(__name__)

# Process-local lock for freeze_time within this Python interpreter. Guards
# against overlapping freeze_time calls from multiple threads, and also from
# multiple asyncio coroutines running in the same process/event loop thread,
# because acquisition happens synchronously before patching time.
#
# Limitations: this lock does not coordinate across separate processes, is not
# re-entrant, and is not awaitable. Callers use a non-blocking acquire in
# synchronous code, so concurrent attempts fail immediately rather than waiting
# for the active freeze_time scope to finish.
_FREEZE_TIME_LOCK = threading.Lock()

# Per-class asyncio.Lock to prevent concurrent harnesses for the same App class
# from corrupting class-level _api_factory / app_manifest (Finding 2).
_CLASS_LOCKS: weakref.WeakKeyDictionary[type, asyncio.Lock] = weakref.WeakKeyDictionary()


def _get_class_lock(cls: type) -> asyncio.Lock:
    """Return the per-class asyncio.Lock, creating one if needed.

    Uses setdefault to avoid the TOCTOU race where two concurrent callers
    both see None and create separate Lock instances.
    """
    return _CLASS_LOCKS.setdefault(cls, asyncio.Lock())


class _TestClock:
    """Mutable test clock for controlling time in tests.

    Patches ``hassette.utils.date_utils.now`` to return a controlled time.
    Used internally by :meth:`AppTestHarness.freeze_time`.

    Not part of the public API — subject to change without notice.
    """

    _current: ZonedDateTime

    def __init__(self, instant: Instant | ZonedDateTime) -> None:
        """Initialize the clock at the given time.

        Args:
            instant: Starting time as an Instant or ZonedDateTime.
        """
        self._current = self._to_zoned(instant)

    @staticmethod
    def _to_zoned(instant: Instant | ZonedDateTime) -> ZonedDateTime:
        """Convert an Instant or ZonedDateTime to system-tz ZonedDateTime."""
        if isinstance(instant, ZonedDateTime):
            return instant
        return instant.to_system_tz()

    def current(self) -> ZonedDateTime:
        """Return the current frozen time.

        Returns:
            The current ZonedDateTime.
        """
        return self._current

    def set(self, instant: Instant | ZonedDateTime) -> None:
        """Set the clock to a new time.

        Args:
            instant: New time as an Instant or ZonedDateTime.
        """
        self._current = self._to_zoned(instant)

    def advance(self, *, seconds: float = 0, minutes: float = 0, hours: float = 0) -> None:
        """Advance the clock by the given delta.

        Args:
            seconds: Seconds to advance.
            minutes: Minutes to advance.
            hours: Hours to advance.
        """
        self._current = self._current.add(seconds=seconds, minutes=minutes, hours=hours)


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


# Cache of hermetic subclasses keyed by app_config_cls — avoids creating a new
# subclass per _make_hermetic_config call, which would accumulate permanently in
# __subclasses__() and Pydantic's internal model cache.
_HERMETIC_CONFIG_CACHE: dict[type[AppConfig], type[AppConfig]] = {}


def _get_hermetic_subclass(app_config_cls: type[AppConfig]) -> type[AppConfig]:
    """Return a cached hermetic subclass of app_config_cls.

    The subclass reads init_kwargs from a class variable ``_hermetic_init_kwargs``
    set by the caller before instantiation. This avoids creating a new class per
    call while still supporting per-call config dicts.
    """
    cached = _HERMETIC_CONFIG_CACHE.get(app_config_cls)
    if cached is not None:
        return cached

    class _HermeticSettings(app_config_cls):  # pyright: ignore[reportGeneralTypeIssues]
        _hermetic_init_kwargs: ClassVar[dict[str, Any]] = {}

        @classmethod
        def settings_customise_sources(cls, settings_cls, **_kwargs):  # pyright: ignore[reportIncompatibleMethodOverride]
            return (InitSettingsSource(settings_cls, init_kwargs=cls._hermetic_init_kwargs),)

    _HERMETIC_CONFIG_CACHE[app_config_cls] = _HermeticSettings
    return _HermeticSettings


def _make_hermetic_config(
    app_cls: type[App], app_config_cls: type[AppConfig], config_dict: dict[str, Any]
) -> AppConfig:
    """Validate config_dict against app_config_cls using only InitSettingsSource.

    Uses a cached hermetic subclass per app_config_cls to avoid accumulating
    subclass entries in __subclasses__() across repeated calls.

    Args:
        app_cls: The App class (used in error messages).
        app_config_cls: The AppConfig subclass to validate against.
        config_dict: Dict of config key/value pairs to validate.

    Returns:
        A validated AppConfig instance.

    Raises:
        AppConfigurationError: If validation fails.
    """
    hermetic_cls = _get_hermetic_subclass(app_config_cls)
    hermetic_cls._hermetic_init_kwargs = config_dict  # pyright: ignore[reportAttributeAccessIssue]

    try:
        return hermetic_cls()
    except pydantic.ValidationError as e:
        raise AppConfigurationError(app_cls, e) from e


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

        # Time control (set by freeze_time)
        self._test_clock: _TestClock | None = None
        self._time_patcher: list[object] | None = None  # list of unittest.mock._patch instances
        self._time_patcher_registered: bool = False

    async def __aenter__(self) -> "AppTestHarness":
        """Set up the full harness in 13 steps with LIFO teardown via AsyncExitStack."""
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
        hassette_config = make_test_config(data_dir=data_dir)

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

        # Step 4b: Mark hassette as being in test mode — enables _test_seed_state
        # and other test-only methods that have runtime guards.
        harness.hassette._test_mode = True  # pyright: ignore[reportAttributeAccessIssue]

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

        # Step 7: Set global hassette ContextVar — use context.use() so cleanup is always
        # registered unconditionally. set_global_hassette() returns None when the same
        # instance is already set (e.g., nested harnesses), which would silently skip token
        # cleanup and leave the next test with a stale ContextVar value. context.use()
        # always calls var.set() and registers var.reset(token) on exit, regardless of
        # whether the value was already present.
        exit_stack.enter_context(
            context.use(context.HASSETTE_INSTANCE, cast("Hassette", harness.hassette))  # pyright: ignore[reportArgumentType]
        )

        # Step 8: Mark state proxy ready
        state_proxy = harness.hassette._state_proxy
        if state_proxy is None:
            raise RuntimeError("StateProxy was not started — ensure with_state_proxy() is called")
        state_proxy.mark_ready(reason="AppTestHarness: mark ready for test")

        # Step 9: Acquire per-class lock to prevent concurrent harnesses for the
        # same App class from corrupting class-level attributes (Finding 2).
        class_lock = _get_class_lock(self._app_cls)
        await class_lock.acquire()
        exit_stack.callback(class_lock.release)

        # Step 10: Synthesize AppManifest and set on class with save/restore
        manifest = _synthesize_manifest(self._app_cls)
        original_manifest = getattr(self._app_cls, "app_manifest", self._UNSET)
        self._app_cls.app_manifest = manifest
        exit_stack.callback(self._restore_manifest, original_manifest)

        # Step 11: Set _api_factory on class with save/restore
        # Use __dict__ to check the class's own dict, not MRO — matches _restore_api_factory's delattr logic
        original_api_factory = self._app_cls.__dict__.get("_api_factory", self._UNSET)
        self._app_cls._api_factory = RecordingApi  # pyright: ignore[reportAttributeAccessIssue]
        exit_stack.callback(self._restore_api_factory, original_api_factory)

        # Step 12: Instantiate the app
        app = self._app_cls(
            hassette=harness.hassette,  # pyright: ignore[reportArgumentType]
            app_config=validated_config,
            index=0,
        )

        # Add app as child of hassette mock
        harness.hassette.children.append(app)
        app.parent = harness.hassette  # pyright: ignore[reportAttributeAccessIssue]

        self._app = app

        # Step 13: Register app shutdown first (late registration = early unwind)
        # This ensures app shuts down before harness.stop() runs.
        # Wrapped to prevent shutdown exceptions from masking the original test failure.
        exit_stack.push_async_callback(self._safe_app_shutdown, app)

        # Start the app lifecycle
        app.start()
        await wait_for(
            lambda: app.status == ResourceStatus.RUNNING,
            desc=f"{app.class_name} RUNNING",
            timeout=5.0,
        )

    @staticmethod
    async def _safe_app_shutdown(app: App) -> None:
        """Shut down the app, logging but not re-raising exceptions.

        Prevents a crashing ``app.shutdown()`` from masking the original test
        failure during ``AsyncExitStack`` teardown.
        """
        try:
            await app.shutdown()
        except Exception:
            LOGGER.warning("AppTestHarness: app.shutdown() raised during teardown", exc_info=True)

    def _cleanup_tmpdir(self, data_dir: Path) -> None:
        """Remove auto-created tmpdir on teardown."""
        try:
            shutil.rmtree(data_dir, ignore_errors=True)
        except Exception as e:
            LOGGER.warning("Failed to clean up tmpdir %s: %s", data_dir, e)

    def _restore_manifest(self, original: Any) -> None:
        """Restore app_cls.app_manifest to its original value."""
        if original is self._UNSET:
            with contextlib.suppress(AttributeError):
                del self._app_cls.app_manifest
            # Verify deletion succeeded — del on an inherited attribute is a no-op.
            if "app_manifest" in self._app_cls.__dict__:
                LOGGER.warning(
                    "_restore_manifest: could not delete app_manifest from %s.__dict__",
                    self._app_cls.__name__,
                )
        else:
            self._app_cls.app_manifest = original

    def _restore_api_factory(self, original: Any) -> None:
        """Restore app_cls._api_factory to its original value."""
        if original is self._UNSET:
            with contextlib.suppress(AttributeError):
                del self._app_cls._api_factory  # pyright: ignore[reportAttributeAccessIssue]
            # Verify deletion succeeded — del on an inherited attribute is a no-op.
            # Force to the declared default (None) if still present.
            if "_api_factory" in self._app_cls.__dict__:
                self._app_cls._api_factory = None  # pyright: ignore[reportAttributeAccessIssue]
                LOGGER.warning(
                    "_restore_api_factory: del failed for %s, forced _api_factory to None", self._app_cls.__name__
                )
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
        (1970-01-01T00:00:00Z). Simulated events sent via ``simulate_state_change``
        bypass ``StateProxy``'s staleness guard entirely (they use
        ``_test_seed_state``), so the epoch timestamp does not play a protective
        ordering role — it simply marks seeded state as obviously synthetic.

        Call ``set_state`` **before** ``simulate_state_change`` for the same entity.
        Calling it afterward will overwrite the simulated state with the seeded value.

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

    def seed_helper(self, record: BaseModel) -> None:
        """Seed a stored helper config for tests that read helper CRUD.

        Domain is derived from the record class. Passing a record of a type
        not registered in _RECORD_TYPE_TO_DOMAIN raises ValueError immediately.

        Args:
            record: A helper Record model instance (e.g., InputBooleanRecord).

        Raises:
            ValueError: If the record's type is not a known helper record type.
        """
        try:
            domain = _RECORD_TYPE_TO_DOMAIN[type(record)]
        except KeyError as e:
            raise ValueError(
                f"Unknown helper record type: {type(record).__name__}. "
                f"Expected one of: {sorted(t.__name__ for t in _RECORD_TYPE_TO_DOMAIN)}"
            ) from e
        self.api_recorder.helper_definitions[domain][record.id] = record  # pyright: ignore[reportAttributeAccessIssue]

    async def set_states(self, states: dict[str, str | tuple[str, dict]]) -> None:
        """Seed multiple entities at once.

        Example::

            await harness.set_states({
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

        Raises:
            DrainError: If any handler task raised a non-cancellation exception.
                When a timeout also occurs, this is the primary exception
                raised, chained from a ``DrainTimeout``.
            DrainTimeout: If the drain does not reach quiescence within
                ``timeout`` and no handler exceptions were collected.

        Both ``DrainError`` and ``DrainTimeout`` inherit from ``DrainFailure``,
        so callers can catch either outcome uniformly with
        ``except DrainFailure:``.
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
        state: str | None = None,
        timeout: float = 2.0,
    ) -> None:
        """Create an attribute change event and send it through the bus.

        Note:
            This method delegates to :meth:`simulate_state_change` under the hood,
            which means **any** ``bus.on_state_change`` **handler registered for the
            same entity will also fire** — not just attribute-change handlers. This
            matches Home Assistant's real behavior (``state_changed`` events fire even
            when only attributes change), but it affects handler call counts::

                # If your app registers both:
                self.bus.on_state_change("sensor.temp", handler=self.on_temp_state)
                self.bus.on_attribute_change("sensor.temp", "temperature", handler=self.on_temp_attr)

                # Then simulate_attribute_change fires BOTH handlers.
                # Account for this in assert_call_count() assertions.

        The state value used for the event is resolved in this order:
        1. The explicit ``state`` argument, if provided.
        2. The current cached state value for the entity in the StateProxy.
        3. ``"unknown"`` if the entity has not been seeded.

        Tip:
            Call :meth:`set_state` for the entity before
            ``simulate_attribute_change`` to avoid the ``"unknown"`` fallback.

        Args:
            entity_id: The entity ID whose attribute changed.
            attribute: The attribute name.
            old_value: Previous attribute value.
            new_value: New attribute value.
            state: Optional explicit state value to use for the event. If omitted, the
                current cached state for the entity is used (defaulting to ``"unknown"``
                if the entity is unseeded).
            timeout: Maximum seconds to wait for handlers to complete.

        Raises:
            DrainError: If any handler task raised a non-cancellation exception.
                When a timeout also occurs, this is the primary exception
                raised, chained from a ``DrainTimeout``.
            DrainTimeout: If the drain does not reach quiescence within
                ``timeout`` and no handler exceptions were collected.

        Both ``DrainError`` and ``DrainTimeout`` inherit from ``DrainFailure``,
        so callers can catch either outcome uniformly with
        ``except DrainFailure:``.
        """
        harness = self._harness
        if harness is None:
            raise RuntimeError("AppTestHarness is not active")

        if state is not None:
            current_state = state
        else:
            state_proxy = harness.hassette._state_proxy
            if state_proxy is not None:
                # Lock-free read is safe: dict.get() is atomic in CPython, consistent
                # with StateProxy.get_state()'s documented lock-free read pattern.
                raw = state_proxy.states.get(entity_id)
                current_state = raw["state"] if raw is not None else "unknown"
            else:
                current_state = "unknown"

        await self.simulate_state_change(
            entity_id,
            old_value=current_state,
            new_value=current_state,
            old_attrs={attribute: old_value},
            new_attrs={attribute: new_value},
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

        Raises:
            DrainError: If any handler task raised a non-cancellation exception.
                When a timeout also occurs, this is the primary exception
                raised, chained from a ``DrainTimeout``.
            DrainTimeout: If the drain does not reach quiescence within
                ``timeout`` and no handler exceptions were collected.

        Both ``DrainError`` and ``DrainTimeout`` inherit from ``DrainFailure``,
        so callers can catch either outcome uniformly with
        ``except DrainFailure:``.
        """
        harness = self._harness
        if harness is None:
            raise RuntimeError("AppTestHarness is not active")

        event = create_call_service_event(domain=domain, service=service, service_data=data)
        await harness.hassette.send_event(event.topic, event)  # pyright: ignore[reportAttributeAccessIssue]
        await self._drain_task_bucket(timeout=timeout)

    async def _drain_task_bucket(self, *, timeout: float = 2.0) -> None:
        """Wait until bus dispatch queue AND app task_bucket are jointly quiescent.

        Iterates: wait for bus dispatch idle, wait for task_bucket pending tasks, re-check.
        Exits only when both are quiescent after a yield cycle. Covers arbitrary-depth
        task chains (A→B→C) and surfaces any handler exceptions via DrainError.

        Exceptions are collected via an exception recorder installed on ``app.task_bucket``
        for the duration of the drain. The recorder fires from the task's done callback,
        which guarantees that fast-completing tasks (those that finish between successive
        ``pending_tasks()`` snapshots) are still captured — closing the snapshot-timing
        window that the ``asyncio.wait`` iteration pattern cannot cover.

        Args:
            timeout: Maximum seconds to wait.

        Raises:
            DrainError: If any handler task raised a non-cancellation exception.
                When a timeout also occurs, this is the primary exception
                raised, chained from a ``DrainTimeout`` so the handler crash
                is visible as the root failure.
            DrainTimeout: If the drain does not reach quiescence within
                ``timeout`` and no handler exceptions were collected.

        Both ``DrainError`` and ``DrainTimeout`` inherit from ``DrainFailure``,
        so callers can catch either outcome uniformly with
        ``except DrainFailure:``.

        Note:
            Only ``app.task_bucket`` is drained. Tasks spawned by Bus-owned callbacks
            (including debounce and throttle handlers registered directly at the Bus
            level, outside an App context) land in ``bus.task_bucket`` and are NOT
            visible to this drain. For full-fidelity draining, route listeners
            through App-level registration via ``self.bus.on_state_change`` inside
            an App.
        """
        harness = self._harness
        if harness is None:
            raise RuntimeError("AppTestHarness is not active")

        bus_service = harness.hassette._bus_service
        assert bus_service is not None, (
            "BusService unexpectedly None at drain time — harness setup may have partially failed"
        )

        app = self._app
        deadline = asyncio.get_running_loop().time() + timeout
        collected_exceptions: list[tuple[str, BaseException]] = []

        # Install an exception recorder on app.task_bucket for the duration of the drain.
        # This captures exceptions from tasks that complete at any point during the drain,
        # including fast-completing tasks that finish between pending_tasks() snapshots.
        # The seen_tasks guard prevents double-counting if a task's done callbacks fire
        # in an order that would otherwise expose the same exception twice.
        seen_tasks: set[asyncio.Task] = set()

        def _recorder(task: asyncio.Task, exc: BaseException) -> None:
            if task in seen_tasks:
                return
            seen_tasks.add(task)
            collected_exceptions.append((task.get_name(), exc))

        if app is not None:
            app.task_bucket.install_exception_recorder(_recorder)

        try:
            while True:
                # Top-of-loop deadline guard: prevents infinite spin on perpetually-spawning handlers
                if asyncio.get_running_loop().time() >= deadline:
                    self._raise_drain_timeout(timeout, bus_service, app, collected_exceptions)

                # Step 1: wait for bus dispatch queue to clear. Wrap await_dispatch_idle
                # to translate its TimeoutError into our diagnostic.
                remaining = deadline - asyncio.get_running_loop().time()
                if remaining <= 0:
                    self._raise_drain_timeout(timeout, bus_service, app, collected_exceptions)
                try:
                    await bus_service.await_dispatch_idle(timeout=remaining)
                except TimeoutError:
                    self._raise_drain_timeout(timeout, bus_service, app, collected_exceptions)

                # Step 2: wait for any pending tasks in the app's task_bucket.
                # Exceptions are collected via the recorder installed above — no per-task
                # collection needed here. We still await the tasks to pace the loop.
                if app is not None:
                    pending = app.task_bucket.pending_tasks()
                    if pending:
                        remaining = deadline - asyncio.get_running_loop().time()
                        if remaining <= 0:
                            self._raise_drain_timeout(timeout, bus_service, app, collected_exceptions)
                        _done, still_pending = await asyncio.wait(pending, timeout=remaining)
                        if still_pending:
                            self._raise_drain_timeout(timeout, bus_service, app, collected_exceptions)

                # Step 3: stability check via await_dispatch_idle, which has its own 5ms anyio
                # stability window. No-op when dispatch is already idle; re-runs the stability
                # check if new events arrived during step 2. Re-check the deadline first —
                # passing timeout=0 collapses the 5ms anyio window to nothing, defeating the
                # whole point of using await_dispatch_idle here.
                remaining = deadline - asyncio.get_running_loop().time()
                if remaining <= 0:
                    self._raise_drain_timeout(timeout, bus_service, app, collected_exceptions)
                try:
                    await bus_service.await_dispatch_idle(timeout=remaining)
                except TimeoutError:
                    self._raise_drain_timeout(timeout, bus_service, app, collected_exceptions)

                # Step 4: exit condition — both sides quiescent.
                if app is None or not app.task_bucket.pending_tasks():
                    if bus_service.is_dispatch_idle:
                        # All quiescent; surface any collected exceptions.
                        if collected_exceptions:
                            raise DrainError(collected_exceptions)
                        return
                # else: loop back for another pass
        finally:
            if app is not None:
                app.task_bucket.uninstall_exception_recorder()

    def _raise_drain_timeout(
        self,
        timeout: float,
        bus_service: "BusService",
        app: "App | None",
        collected_exceptions: "list[tuple[str, BaseException]]",
    ) -> None:
        """Build and raise a diagnostic DrainTimeout with pending task names and debounce hint.

        When exceptions have already been collected, raises ``DrainError`` chained from
        the ``DrainTimeout`` so the handler crash is visible as the primary failure.

        Args:
            timeout: The drain timeout that elapsed.
            bus_service: The BusService instance to query for dispatch state.
            app: The app whose task_bucket to query (may be None).
            collected_exceptions: Exceptions gathered by the recorder so far.

        Raises:
            DrainError: When ``collected_exceptions`` is non-empty (chained from DrainTimeout).
            DrainTimeout: When no exceptions were collected.
        """
        task_names: list[str] = []
        if app is not None:
            task_names = [t.get_name() for t in app.task_bucket.pending_tasks()]

        base = (
            f"AppTestHarness drain did not reach quiescence within {timeout}s "
            f"(bus dispatch pending: {bus_service.dispatch_pending_count}, "
            f"task_bucket pending: {len(task_names)})"
        )
        if task_names:
            base += f"; pending task names: {task_names}"
        if any("debounce" in n for n in task_names):
            base += (
                " — if tasks include 'handler:debounce', your drain timeout may be shorter "
                "than the handler's debounce window. Pass `timeout=` larger than your largest "
                "debounce delay."
            )
        if collected_exceptions:
            drain_err = DrainError(collected_exceptions)
            timeout_err = DrainTimeout(base)
            raise drain_err from timeout_err
        raise DrainTimeout(base)

    # ------------------------------------------------------------------
    # Time control helpers
    # ------------------------------------------------------------------

    # Single patch target for freeze_time. All production code accesses now() via
    # the module attribute (date_utils.now()), so patching the canonical source
    # is sufficient — no per-module patch list needed.
    _NOW_PATCH_TARGETS: ClassVar[tuple[str, ...]] = ("hassette.utils.date_utils.now",)

    def _stop_time_patchers(self) -> None:
        """Stop all active time patchers. Called by exit stack on teardown."""
        if self._time_patcher is not None:
            for p in self._time_patcher:
                try:
                    p.stop()  # pyright: ignore[reportAttributeAccessIssue]
                except Exception:
                    LOGGER.warning("freeze_time: failed to stop patcher %s", p, exc_info=True)
            self._time_patcher = None

    def _release_freeze_time(self) -> None:
        """Stop time patchers and release the process-global freeze_time lock."""
        self._stop_time_patchers()
        with contextlib.suppress(RuntimeError):
            _FREEZE_TIME_LOCK.release()

    def freeze_time(self, instant: Instant | ZonedDateTime) -> None:
        """Freeze time at the given instant.

        Patches ``hassette.utils.date_utils.now`` to return the frozen time.
        Idempotent — calling again replaces the frozen time (stops old patchers first).

        The patchers are automatically stopped when the harness exits via the exit stack.
        A process-global lock prevents concurrent harnesses from silently corrupting
        each other's frozen clock. If another harness already holds the lock, a
        ``RuntimeError`` is raised immediately.

        Must be called inside ``async with AppTestHarness(...) as harness:`` — raises
        RuntimeError if called before entering the context manager.

        Args:
            instant: The time to freeze at, as an Instant or ZonedDateTime.

        Raises:
            RuntimeError: If called outside the async with block, or if another
                harness already holds the freeze_time lock.
        """
        if self._exit_stack is None:
            raise RuntimeError("freeze_time() must be called inside 'async with AppTestHarness(...) as harness:'.")

        # Acquire the process-global lock (non-blocking). Idempotent re-freeze
        # from the same harness is allowed (we already hold the lock).
        if self._time_patcher is None and not _FREEZE_TIME_LOCK.acquire(blocking=False):
            raise RuntimeError(
                "freeze_time is already held by another harness — "
                "time-controlling tests must be isolated (e.g., separate xdist workers)."
            )

        # Register teardown BEFORE starting patchers — if p.start() raises, the
        # lock is still released on exit. Only register once; subsequent freeze_time
        # calls reuse this callback.
        if not self._time_patcher_registered:
            self._exit_stack.callback(self._release_freeze_time)
            self._time_patcher_registered = True

        # Stop existing patchers if active (idempotent re-freeze)
        self._stop_time_patchers()

        clock = _TestClock(instant)
        self._test_clock = clock

        patchers: list[object] = []
        for target in self._NOW_PATCH_TARGETS:
            try:
                p = patch(target, side_effect=clock.current)
                p.start()
                patchers.append(p)
            except AttributeError:
                # Module may not import `now` — skip gracefully
                LOGGER.debug("freeze_time: could not patch %s (module does not import now)", target)

        self._time_patcher = patchers

    def advance_time(self, *, seconds: float = 0, minutes: float = 0, hours: float = 0) -> None:
        """Advance frozen time by the given delta.

        Does NOT automatically trigger scheduled jobs — call :meth:`trigger_due_jobs`
        explicitly after advancing time.

        Args:
            seconds: Seconds to advance.
            minutes: Minutes to advance.
            hours: Hours to advance.

        Raises:
            RuntimeError: If :meth:`freeze_time` has not been called first.
        """
        if self._test_clock is None:
            raise RuntimeError(
                "advance_time() requires freeze_time() to be called first. "
                "Call harness.freeze_time(instant) before advancing time."
            )
        self._test_clock.advance(seconds=seconds, minutes=minutes, hours=hours)

    async def trigger_due_jobs(self) -> int:
        """Fire all jobs that are due at the current (possibly frozen) time.

        Delegates to :meth:`SchedulerService._test_trigger_due_jobs`, which
        snapshots due jobs and dispatches them inline. Jobs re-enqueued during
        dispatch (repeating jobs) are not included — only the initial snapshot
        is processed, preventing infinite loops when the clock is frozen.

        Note:
            This bypasses the scheduler's ``serve()`` loop — wakeup events and
            shutdown guards are not exercised. For testing the scheduler's own
            timing behavior, use the full harness with real time progression.

        Returns:
            The number of jobs that were dispatched and completed.

        Raises:
            RuntimeError: If the harness is not active.
        """
        harness = self._harness
        if harness is None:
            raise RuntimeError("AppTestHarness is not active")

        scheduler_service = harness.hassette._scheduler_service
        if scheduler_service is None:
            raise RuntimeError("SchedulerService is not available — ensure with_scheduler() was called")

        return await scheduler_service._test_trigger_due_jobs()
