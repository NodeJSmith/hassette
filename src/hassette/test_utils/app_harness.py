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
import weakref
from contextlib import AsyncExitStack
from pathlib import Path
from typing import TYPE_CHECKING, Any, ClassVar, cast
from unittest.mock import AsyncMock

if TYPE_CHECKING:
    from hassette import Hassette
    from hassette.events import HassStateDict

import pydantic
from pydantic import BaseModel
from pydantic_settings.sources import InitSettingsSource

from hassette import context
from hassette.app.app import App
from hassette.app.app_config import AppConfig
from hassette.app.utils import _get_app_config_class
from hassette.bus import Bus
from hassette.config.classes import AppManifest
from hassette.scheduler import Scheduler
from hassette.state_manager import StateManager
from hassette.test_utils.config import make_test_config
from hassette.test_utils.harness import TIMEOUTS, HassetteHarness, wait_for
from hassette.test_utils.helpers import make_state_dict
from hassette.test_utils.recording_api import _RECORD_TYPE_TO_DOMAIN, RecordingApi
from hassette.test_utils.simulation import SimulationMixin
from hassette.test_utils.time_control import TimeControlMixin
from hassette.types.enums import ResourceStatus

LOGGER = logging.getLogger(__name__)

# Per-class asyncio.Lock used as a narrow critical section around the
# _CLASS_MANIFEST_STATE read-modify-write and config validation. Held only
# during synchronous operations — not during app startup, test body, or teardown.
_CLASS_LOCKS: weakref.WeakKeyDictionary[type, asyncio.Lock] = weakref.WeakKeyDictionary()

# Per-class reference-counted manifest state. When concurrent harnesses share
# an App class, the first to enter saves the original manifest and subsequent
# ones increment the count. Only the last to exit (count drops to 0) restores.
_CLASS_MANIFEST_STATE: weakref.WeakKeyDictionary[type, tuple[int, Any]] = weakref.WeakKeyDictionary()


def _get_class_lock(cls: type) -> asyncio.Lock:
    """Return the per-class asyncio.Lock, creating one if needed.

    Uses setdefault to avoid the TOCTOU race where two concurrent callers
    both see None and create separate Lock instances.
    """
    return _CLASS_LOCKS.setdefault(cls, asyncio.Lock())


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


# Cache of (hermetic_subclass, init_kwargs_ref) pairs keyed by app_config_cls — avoids
# creating a new subclass per _make_hermetic_config call, which would accumulate
# permanently in __subclasses__() and Pydantic's internal model cache.
# Same closure-ref pattern as _get_hermetic_hassette_config_cls in config.py (singleton variant).
_HERMETIC_CONFIG_CACHE: dict[type[AppConfig], tuple[type[AppConfig], list[dict[str, Any]]]] = {}


def _get_hermetic_subclass(app_config_cls: type[AppConfig]) -> tuple[type[AppConfig], list[dict[str, Any]]]:
    """Return a cached hermetic subclass of app_config_cls and its config cell.

    The subclass reads init_kwargs from a mutable single-element list (the
    "cell") captured by the ``settings_customise_sources`` closure. The caller
    updates ``cell[0]`` before instantiation — race-free because the cell is
    private to the returned pair and asyncio's cooperative multitasking means
    no ``await`` occurs between the update and the instantiation.

    Returns:
        A ``(hermetic_subclass, cell)`` tuple. ``cell`` is a list whose only
        element is the current ``config_dict``. Set ``cell[0] = new_dict``
        before calling ``hermetic_subclass()`` to control what is validated.
    """
    cached = _HERMETIC_CONFIG_CACHE.get(app_config_cls)
    if cached is not None:
        return cached

    # Mutable single-element container that the closure reads from.
    cell: list[dict[str, Any]] = [{}]

    class _HermeticSettings(app_config_cls):  # pyright: ignore[reportGeneralTypeIssues]
        @classmethod
        def settings_customise_sources(cls, settings_cls, **_kwargs):  # pyright: ignore[reportIncompatibleMethodOverride]
            return (InitSettingsSource(settings_cls, init_kwargs=cell[0]),)

    result = (_HermeticSettings, cell)
    _HERMETIC_CONFIG_CACHE[app_config_cls] = result
    return result


def _make_hermetic_config(
    app_cls: type[App], app_config_cls: type[AppConfig], config_dict: dict[str, Any]
) -> AppConfig:
    """Validate config_dict against app_config_cls using only InitSettingsSource.

    Uses a cached hermetic subclass per app_config_cls to avoid accumulating
    subclass entries in __subclasses__() across repeated calls. The config_dict
    is injected via a closure cell rather than a ClassVar — no shared mutable
    state is visible outside this call.

    Args:
        app_cls: The App class (used in error messages).
        app_config_cls: The AppConfig subclass to validate against.
        config_dict: Dict of config key/value pairs to validate.

    Returns:
        A validated AppConfig instance.

    Raises:
        AppConfigurationError: If validation fails.
    """
    hermetic_cls, cell = _get_hermetic_subclass(app_config_cls)
    # Update the cell before instantiation; no await between here and hermetic_cls()
    # so asyncio cooperative multitasking cannot interleave a concurrent caller.
    cell[0] = config_dict

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


class AppTestHarness(SimulationMixin, TimeControlMixin):
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
        Mutates class-level attributes (app_manifest) with save/restore under a
        narrow per-class asyncio.Lock. Safe for sequential tests, xdist workers,
        and concurrent use via asyncio.gather for the same App class.
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
        self._test_clock = None
        self._time_patcher: list[object] | None = None
        self._time_patcher_registered: bool = False

    async def __aenter__(self) -> "AppTestHarness":
        """Set up the full harness in 11 steps with LIFO teardown via AsyncExitStack."""
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

        # Step 3: Resolve app config class (read-only, safe outside lock).
        app_config_cls = _get_app_config_class(self._app_cls)

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
        harness.hassette._api = api_mock

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
        harness.state_proxy.mark_ready(reason="AppTestHarness: mark ready for test")

        # Step 9: Synthesize manifest under narrow per-class lock.
        # The lock serializes both hermetic config validation and the
        # _CLASS_MANIFEST_STATE read-modify-write so concurrent harnesses for
        # the same class share one manifest lifecycle — only the last to exit
        # restores the original.
        async with _get_class_lock(self._app_cls):
            validated_config = _make_hermetic_config(self._app_cls, app_config_cls, self._config_dict)
            state = _CLASS_MANIFEST_STATE.get(self._app_cls)
            if state is None:
                original_manifest = getattr(self._app_cls, "app_manifest", self._UNSET)
                manifest = _synthesize_manifest(self._app_cls)
                self._app_cls.app_manifest = manifest
                _CLASS_MANIFEST_STATE[self._app_cls] = (1, original_manifest)
            else:
                count, original_manifest = state
                _CLASS_MANIFEST_STATE[self._app_cls] = (count + 1, original_manifest)

        exit_stack.push_async_callback(self._restore_manifest)

        # Step 10: Instantiate the app with RecordingApi injected via constructor
        app = self._app_cls(
            hassette=harness.hassette,  # pyright: ignore[reportArgumentType]
            app_config=validated_config,
            index=0,
            api_factory=RecordingApi,
        )

        # Add app as child of hassette mock
        harness.hassette.children.append(app)
        app.parent = harness.hassette  # pyright: ignore[reportAttributeAccessIssue]

        self._app = app

        # Step 11: Register app shutdown first (late registration = early unwind)
        # This ensures app shuts down before harness.stop() runs.
        # Wrapped to prevent shutdown exceptions from masking the original test failure.
        exit_stack.push_async_callback(self._safe_app_shutdown, app)

        # Start the app lifecycle
        app.start()
        await wait_for(
            lambda: app.status == ResourceStatus.RUNNING,
            desc=f"{app.class_name} RUNNING",
            timeout=TIMEOUTS.WAIT_FOR_READY,
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

    async def _restore_manifest(self) -> None:
        """Decrement the manifest reference count; restore original when count reaches 0."""
        async with _get_class_lock(self._app_cls):
            state = _CLASS_MANIFEST_STATE.get(self._app_cls)
            if state is None:
                LOGGER.warning(
                    "_restore_manifest: _CLASS_MANIFEST_STATE entry missing for %s",
                    self._app_cls.__name__,
                )
                return
            count, original = state
            if count > 1:
                _CLASS_MANIFEST_STATE[self._app_cls] = (count - 1, original)
                return
            del _CLASS_MANIFEST_STATE[self._app_cls]
            if original is self._UNSET:
                with contextlib.suppress(AttributeError):
                    del self._app_cls.app_manifest
                if "app_manifest" in self._app_cls.__dict__:
                    LOGGER.warning(
                        "_restore_manifest: could not delete app_manifest from %s.__dict__",
                        self._app_cls.__name__,
                    )
            else:
                self._app_cls.app_manifest = original

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
                "Ensure api_factory=RecordingApi was passed at app construction."
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
        ``harness.seed_state()``), so the epoch timestamp does not play a protective
        ordering role — it simply marks seeded state as obviously synthetic.

        Call ``set_state`` **before** ``simulate_state_change`` for the same entity.
        Calling it afterward will overwrite the simulated state with the seeded value.

        This is for pre-test setup only and does NOT fire bus events.

        Args:
            entity_id: The entity ID to seed (e.g., "light.kitchen").
            state: The state value (e.g., "on", "off", "25.5").
            **attributes: Entity attribute key/value pairs.
        """
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
        await self._require_harness().seed_state(entity_id, state_dict)

    def seed_helper(self, record: BaseModel) -> None:
        """Seed a stored helper config for tests that read helper CRUD.

        Domain is derived from the record class. Passing a record of a type
        not registered in _RECORD_TYPE_TO_DOMAIN raises ValueError immediately.

        The record is deep-copied before storage, so later mutations of the
        caller's `record` object will not leak into harness state — matching
        the isolation guarantees of ``list_*`` / ``create_*`` / ``update_*``.

        Args:
            record: A helper Record model instance (e.g., InputBooleanRecord).

        Raises:
            ValueError: If the record's type is not a known helper record type,
                or if a record with the same id is already seeded.
        """
        try:
            domain, _deep_copy = _RECORD_TYPE_TO_DOMAIN[type(record)]
        except KeyError as e:
            raise ValueError(
                f"Unknown helper record type: {type(record).__name__}. "
                f"Expected one of: {sorted(t.__name__ for t in _RECORD_TYPE_TO_DOMAIN)}"
            ) from e
        if record.id in self.api_recorder.helper_definitions[domain]:  # pyright: ignore[reportAttributeAccessIssue]
            raise ValueError(
                f"A {type(record).__name__} with id={record.id!r} is already seeded. "  # pyright: ignore[reportAttributeAccessIssue]
                f"Use a unique id or call harness.api_recorder.reset() first."
            )
        # Deep-copy to isolate the harness store from later caller-side mutations.
        # Shallow copy is insufficient for InputSelectRecord because of options: list[str].
        self.api_recorder.helper_definitions[domain][record.id] = record.model_copy(deep=True)  # pyright: ignore[reportAttributeAccessIssue]

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
