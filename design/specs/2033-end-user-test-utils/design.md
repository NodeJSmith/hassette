# Design: End-User Test Utilities

**Date:** 2026-04-07
**Status:** archived
**Research:** design/research/2026-04-07-test-utils-end-users/research.md

## Problem

Hassette ships a `test_utils` package with 48 exported symbols, but the module docstring explicitly says "not meant to be used by external users." The canonical `hassette-examples` repo has zero tests. End users who want to test their apps must understand Resource parent/child relationships, AppManifest creation, HassetteConfig TOML parsing, and the internal initialization lifecycle — all undocumented for external consumption.

The most common test pattern for a hassette app is: "when entity X changes to Y, my handler should call service Z." This requires wiring an App instance into a test Bus, Scheduler, StateManager, and Api — something that currently takes 50+ lines of boilerplate copied from hassette's own `tests/conftest.py`.

## Non-Goals

- **Rewriting hassette's internal test infrastructure.** The existing `HassetteHarness`, event factories, and `SimpleTestServer` stay as-is. We layer on top.
- **General-purpose HA testing framework.** This is for testing hassette apps, not arbitrary HA integrations.
- **Supporting tests that require a real HA instance.** All testing is offline against mocks/stubs.
- **`AppSync` support.** `AppSync.run_in_thread` requires a live executor not validated for the test harness's thread model. End users testing `AppSync` subclasses should use `HassetteHarness` directly for now.
- **Typed dependency injection helpers.** Constructing events that satisfy `D.StateNew[SensorState]` or `A.get_attr_new("temperature")` is not addressed by the harness. Users can construct typed events manually using the existing factories; a DI test helper may follow in a future iteration.
- **Debounce/throttle testing.** Debounced and throttled bus handlers (e.g., `on_state_change(..., debounce=60)`) require time advancement and drain coordination beyond what `simulate_state_change` provides. These are testable by combining `freeze_time` + `advance_time` + `trigger_due_jobs` manually; a higher-level helper may follow.

## Architecture

### New module: `hassette.test_utils.app_harness`

A thin wrapper around `HassetteHarness` that adds app-wiring. The central API is an async context manager:

```python
from hassette.test_utils import AppTestHarness

async with AppTestHarness(MotionLights, config={"motion_entity": "binary_sensor.test"}) as harness:
    # harness.app — the fully wired MotionLights instance
    # harness.bus — the test Bus (same as harness.app.bus)
    # harness.scheduler — the test Scheduler
    # harness.api_recorder — RecordingApi (for asserting app-initiated calls)
    # harness.states — StateManager with seeding helpers
    await harness.simulate_state_change("binary_sensor.test", old_value="off", new_value="on")
    harness.api_recorder.assert_called("turn_on", entity_id="light.kitchen")
```

**Two APIs in tests**: `harness.api_recorder` is the `RecordingApi` wrapping `app.api` — it records calls the app makes (e.g., `turn_on`, `call_service`). The internal `hassette.api` (an `AsyncMock` used by `StateProxy` for cache loading) is a separate object not intended for assertion. This split is an architectural reality of the harness — `StateProxy`'s internal API calls are not user-visible behavior.

**Concurrency constraint**: `AppTestHarness` mutates class-level attributes (`app_manifest`, `_api_factory`) with save/restore on teardown. This is safe for sequential tests and for parallel tests across separate processes (pytest-xdist workers). It is **not safe** for concurrent use within the same process for the same App class. Tests using the same App class must run in separate xdist workers (`--dist loadfile`) or sequentially.

#### What `AppTestHarness.__init__` does

1. Stores the App class, config dict, and optional `tmp_path` parameter. **No resource allocation happens here** — no `AsyncExitStack`, no `HassetteHarness`, no ContextVar mutation. All setup is deferred to `__aenter__`.

#### What `__aenter__` does

Creates an `AsyncExitStack` and uses it to sequence setup steps. Each teardown callback is registered immediately after the corresponding setup step succeeds. If any step raises, the exit stack unwinds everything already started. Callbacks are registered in the inverse of desired teardown order because `AsyncExitStack` unwinds LIFO.

1. Creates a minimal `HassetteConfig` from defaults — no TOML file, no env file. If `tmp_path` was provided, sets `data_dir=tmp_path`. If `tmp_path` is `None`, auto-creates a temporary directory via `tempfile.mkdtemp()` and registers cleanup in the exit stack (zero-config cache isolation). Sets `ha_host="test.invalid"` (unreachable by design). Disables state proxy polling to prevent `_load_cache()` from wiping seeded state.
2. Validates the `config` dict against the App's `AppConfig` subclass using a hermetic settings approach: creates a transient subclass of `app_cls.app_config_cls` that overrides `settings_customise_sources` to return only `InitSettingsSource(settings_cls, init_kwargs=config_dict)`. This runs full Pydantic validation (type coercion, `@field_validator`, required-field checks) while suppressing all env var and `.env` file sources. On validation failure, catches `pydantic.ValidationError` and re-raises as `AppConfigurationError(app_cls, original_error)` with a message identifying the app class and the missing/invalid fields.
3. Creates a `HassetteHarness` internally with `with_bus()`, `with_scheduler()`, `with_state_proxy()`, and `with_state_registry()`. Configures `hassette.api.get_states_raw = AsyncMock(return_value=[])` so `StateProxy._load_cache()` initializes to an empty dict.
4. Starts the inner `HassetteHarness`. Registers `harness.stop()` as an exit stack callback (registered early so it unwinds late — after app shutdown).
5. Calls `set_global_hassette()` (moved from `HassetteHarness.__init__` to here), stores the returned `Token`, and registers `ContextVar.reset(token)` in the exit stack. This requires modifying `set_global_hassette()` to return the token from `ContextVar.set()`.
6. Calls `state_proxy.mark_ready()` once, explicitly, so `StateProxy` is ready for seeding without requiring a successful `_load_cache()` cycle.
7. Synthesizes an `AppManifest` from the App class (derives `app_key` from class name, `filename` from `Path(inspect.getfile(app_cls)).parent` — falls back to `Path.cwd()` with a warning if `inspect.getfile` raises `TypeError` for namespace packages/C extensions, `class_name` from `__name__`). Sets the manifest on the App class (`app_cls.app_manifest = manifest`) with save/restore of the original value via the exit stack.
8. Sets `app_cls._api_factory = RecordingApi` with save/restore of the original value via the exit stack (alongside manifest restore). See `_api_factory` section below for the injection mechanism.
9. Instantiates the user's App class, passing the harness's mock Hassette, the validated AppConfig, and `index=0`. During `App.__init__`, the `_api_factory` ClassVar directs `add_child()` to create a `RecordingApi` instead of a real `Api`.
10. Adds the App as a child of the mock Hassette.
11. Calls `app.start()` to run the lifecycle hooks (`before_initialize` → `on_initialize` → `after_initialize`).
12. Waits for the app to reach RUNNING status.

#### What `__aexit__` does

Delegates to the `AsyncExitStack`, which unwinds LIFO. Because callbacks were registered in inverse order, teardown runs as:
1. Calls `app.shutdown()` (while harness is still live — bus and scheduler available for `on_shutdown` hooks).
2. Calls `HassetteHarness.stop()`.
3. Restores `app_cls._api_factory`.
4. Restores `app_cls.app_manifest`.
5. Resets the `ContextVar` token.
6. Cleans up auto-created tmpdir (if applicable).

### `_api_factory` injection point

A new `ClassVar` on `App`:

```python
class App(Generic[AppConfigT], Resource, metaclass=FinalMeta):
    _api_factory: ClassVar[type[Resource] | None] = None
    """Internal: factory for the Api resource. When set, App.__init__ uses
    this instead of Api. Used by AppTestHarness to inject RecordingApi.
    Not a user-facing API."""

    def __init__(self, hassette, *, app_config, index, parent=None):
        # ...existing setup...
        factory = type(self)._api_factory or Api
        self.api = self.add_child(factory)
        # ...rest of init...
```

The harness sets and restores `_api_factory` via the exit stack, alongside `app_manifest`. Both follow the same save/restore pattern from `preserve_config()`.

### RecordingApi

An explicit stub that implements the `Api` interface via an `ApiProtocol`. Located at `hassette/test_utils/recording_api.py`. Must be a `Resource` subclass to participate in the app's resource tree.

```python
class ApiProtocol(Protocol):
    """Protocol defining the Api interface for type-checking conformance."""
    async def turn_on(self, entity_id: str, **kwargs) -> None: ...
    async def turn_off(self, entity_id: str, **kwargs) -> None: ...
    async def call_service(self, domain: str, service: str,
                           target: dict | None = None,
                           return_response: bool | None = False,
                           **data) -> ServiceResponse | None: ...
    async def set_state(self, entity_id: str | StrEnum, state: Any,
                        attributes: dict[str, Any] | None = None) -> dict: ...
    async def fire_event(self, event_type: str,
                         event_data: dict | None = None) -> dict: ...
    async def get_state(self, entity_id: str) -> BaseState: ...
    async def get_states(self) -> list[BaseState]: ...
    async def get_entity(self, entity_id: str) -> BaseState: ...
    async def get_entity_or_none(self, entity_id: str) -> BaseState | None: ...
    async def entity_exists(self, entity_id: str) -> bool: ...
    async def toggle_service(self, entity_id: str, **kwargs) -> None: ...
    # ... remaining Api methods


class RecordingApi(Resource):
    """Records API calls for test assertions.

    Write methods are no-ops that record the call. Read methods delegate
    to StateProxy so tests see seeded state values. get_state() raises
    EntityNotFoundError for unseeded entities (matching real Api behavior).

    on_initialize() calls self.mark_ready() (required for Resource lifecycle).
    sync attribute is a Mock() — sync-call recording is not supported;
    apps using self.api.sync.* must use use_api_server=True for those paths.
    """
    calls: list[ApiCall]
    _state_proxy: StateProxy
    sync: Mock  # facade for AppSync compatibility (limited)

    # Write methods — record and no-op (signatures match Api exactly)
    async def turn_on(self, entity_id: str, **kwargs) -> None: ...
    async def turn_off(self, entity_id: str, **kwargs) -> None: ...
    async def call_service(self, domain: str, service: str,
                           target: dict | None = None,
                           return_response: bool | None = False,
                           **data) -> ServiceResponse | None: ...
    async def set_state(self, entity_id: str | StrEnum, state: Any,
                        attributes: dict[str, Any] | None = None) -> dict: ...
    async def fire_event(self, event_type: str,
                         event_data: dict | None = None) -> dict: ...
    async def toggle_service(self, entity_id: str, **kwargs) -> None: ...

    # Read methods — delegate to StateProxy, convert via state registry
    async def get_state(self, entity_id: str) -> BaseState: ...  # raises EntityNotFoundError
    async def get_states(self) -> list[BaseState]: ...
    async def get_entity(self, entity_id: str) -> BaseState: ...
    async def get_entity_or_none(self, entity_id: str) -> BaseState | None: ...
    async def entity_exists(self, entity_id: str) -> bool: ...

    # Assertion helpers
    def assert_called(self, method: str, **kwargs) -> None: ...
    def assert_not_called(self, method: str) -> None: ...
    def assert_call_count(self, method: str, count: int) -> None: ...
    def get_calls(self, method: str | None = None) -> list[ApiCall]: ...
    def reset(self) -> None: ...

    # Lifecycle
    async def on_initialize(self) -> None:
        self.mark_ready(reason="RecordingApi initialized")
```

A static conformance assertion in `recording_api.py` verifies `RecordingApi` satisfies `ApiProtocol` at import time.

Methods not yet stubbed raise `NotImplementedError(f"RecordingApi does not implement {method_name}. Use use_api_server=True for full Api coverage.")`.

The `RecordingApi` is the default. Users who want HTTP-level fidelity can opt into `SimpleTestServer` via `AppTestHarness(MyApp, config={...}, use_api_server=True)`.

### Event simulation helpers

Methods on `AppTestHarness` that combine event factory + bus emission + reliable drain:

```python
async def simulate_state_change(
    self, entity_id: str, *, old_value: str, new_value: str,
    old_attrs: dict | None = None, new_attrs: dict | None = None,
) -> None:
    """Create a state change event and send it through the bus.

    Waits for all triggered handlers to complete by polling the
    appropriate task bucket until empty, with a configurable timeout
    (default 2.0s). The exact drain target (app.bus.task_bucket vs
    hassette.task_bucket) must be verified during implementation by
    tracing the task ownership path for bus-dispatched handlers.
    """

async def simulate_attribute_change(
    self, entity_id: str, attribute: str, *, old_value: Any, new_value: Any,
) -> None:
    """Create an attribute change event and send it through the bus."""

async def simulate_call_service(
    self, domain: str, service: str, **data: Any,
) -> None:
    """Create a call_service event and send it through the bus."""
```

Parameter names use `old_value`/`new_value` to match the underlying `create_state_change_event()` factory — one naming convention throughout the Tier 1 API.

These use the existing `create_state_change_event()`, `create_call_service_event()`, and `make_state_dict()` factories from `hassette.test_utils.helpers`, then call `hassette.send_event()` and drain by polling the task bucket empty using the existing `wait_for` utility with a timeout (default 2.0s).

### State seeding

Methods on `AppTestHarness` that seed the `StateProxy` with initial entity state via a new `StateProxy._test_seed_state()` method:

```python
def set_state(self, entity_id: str, state: str, **attributes: Any) -> None:
    """Seed an entity's state in the StateProxy.

    Uses make_state_dict() internally with a past sentinel timestamp
    (1970-01-01T00:00:00Z) so that any subsequent simulate_state_change()
    with a current or future timestamp always supersedes the seeded value.
    Users must not call freeze_time() at the sentinel timestamp.

    This is for pre-test setup only and does NOT fire bus events.
    """

def set_states(self, states: dict[str, str | tuple[str, dict]]) -> None:
    """Seed multiple entities at once.

    Example:
        harness.set_states({
            "light.kitchen": "on",
            "sensor.temp": ("25.5", {"unit_of_measurement": "°C"}),
        })
    """
```

These call `StateProxy._test_seed_state(entity_id, state_dict)` — a new method on `StateProxy` (prefixed with `_test_` to signal it is for test harnesses only, not production use) that acquires the write lock and writes to `self._states`. It does **not** call `mark_ready()` — the harness calls `mark_ready()` once during its own setup sequence (step 6 of `__aenter__`), separating lifecycle management from data seeding.

### Time control via `_TestClock`

The scheduler uses `hassette.utils.date_utils.now()` which calls `ZonedDateTime.now_in_system_tz()`. We use a custom `_TestClock` that patches `now` directly:

```python
class _TestClock:
    """Mutable test clock for controlling time in tests."""
    _current: ZonedDateTime

    def current(self) -> ZonedDateTime:
        return self._current

    def set(self, instant: Instant | ZonedDateTime) -> None:
        self._current = ...  # convert to ZonedDateTime if needed

    def advance(self, *, seconds: float = 0, minutes: float = 0, hours: float = 0) -> None:
        self._current = self._current.add(seconds=seconds, minutes=minutes, hours=hours)
```

`freeze_time()` creates a `_TestClock`, patches `hassette.utils.date_utils.now` via `unittest.mock.patch` to call `_test_clock.current()`, and stores the clock on the harness. If a patcher is already active (idempotent re-freeze), the existing patcher is stopped before the new one is started. The patcher's `stop` callback is registered with the exit stack for cleanup on teardown.

```python
def freeze_time(self, instant: Instant | ZonedDateTime) -> None:
    """Freeze time at the given instant.

    Idempotent — calling again replaces the frozen time (stops old patcher first).
    All calls to hassette's now() will return this time.
    Time control is process-global — not safe for concurrent test
    execution within the same process.
    """

def advance_time(self, *, seconds: float = 0, minutes: float = 0, hours: float = 0) -> None:
    """Advance frozen time by the given delta.

    Raises RuntimeError if freeze_time() has not been called.
    Does NOT automatically trigger scheduled jobs — call trigger_due_jobs()
    explicitly after advancing time.
    """
```

For triggering scheduled jobs after time advancement, `AppTestHarness` provides:

```python
async def trigger_due_jobs(self) -> int:
    """Fire all jobs that are due at the current (possibly frozen) time.

    Lives on AppTestHarness (not on SchedulerService) to avoid leaking
    test concerns into production code. Accesses the scheduler's job queue
    via the inner harness's _scheduler_service reference.

    Implementation: snapshots due jobs via a single pop_due_and_peek_next(now())
    call, then awaits each _dispatch_and_log(job) inline (not via task_bucket.spawn).
    Jobs re-enqueued during dispatch (repeating jobs) are not included in this
    invocation — only the initial snapshot is processed, preventing infinite loops
    when the clock is frozen.

    Returns the number of jobs completed (not scheduled).
    """
```

```python
harness.freeze_time(Instant.from_utc(2026, 4, 7, 6, 0))
# App registered run_daily(my_task, start=(7, 0))
harness.advance_time(hours=1)
count = await harness.trigger_due_jobs()  # fires the 7:00 job
assert count == 1
harness.api_recorder.assert_called("turn_on", entity_id="cover.blinds")
```

### Minimal config helper

`AppTestHarness` handles config internally, but we also expose a standalone factory for users who want to use `HassetteHarness` directly:

```python
def make_test_config(**overrides: Any) -> HassetteConfig:
    """Create a minimal HassetteConfig for testing.

    No TOML file needed. Suppresses env var and .env file sources.
    Defaults:
    - ha_host: "test.invalid" (unreachable by design)
    - ha_port: 8123
    - ha_token: "test-token"
    - data_dir: tempfile.mkdtemp() (auto-cleaned if used via AppTestHarness)

    Overrides are applied via the hermetic settings pattern
    (InitSettingsSource only, no env pollution).
    """
```

This lives in `hassette/test_utils/config.py`.

### Test dependency group

Add to `pyproject.toml`:

```toml
[project.optional-dependencies]
test = ["pytest>=8.0", "pytest-asyncio>=0.23"]
```

This lets end users `pip install hassette[test]` to get the minimum test dependencies. The version floor aligns with hassette's own pinned version.

**Note**: End-user test suites must set `asyncio_mode = "auto"` in `[tool.pytest.ini_options]`.

### Public API surface

The `test_utils/__init__.py` will be restructured with physical namespace separation:

**Tier 1** (`hassette.test_utils`) — end-user API, stable, documented:
```python
from .app_harness import AppTestHarness
from .recording_api import RecordingApi, ApiCall
from .config import make_test_config
from .helpers import (
    create_state_change_event,
    create_call_service_event,
    make_state_dict,
    make_light_state_dict,
    make_sensor_state_dict,
    make_switch_state_dict,
)
```

**Tier 2** (`hassette.test_utils._internal`) — advanced/internal, available but not in `__all__`:
```python
# Re-exported from hassette.test_utils for backward compatibility
# with hassette's own 200+ internal tests, but not in __all__
from ._internal import HassetteHarness, wait_for, preserve_config
from ._internal import SimpleTestServer
# ... rest of current exports
```

`__all__` in `test_utils/__init__.py` contains only Tier 1 symbols. IDE autocomplete and `from hassette.test_utils import *` surface only the supported names. Existing internal tests that import `from hassette.test_utils import HassetteHarness` continue to work via the re-export.

Since `hassette.test_utils` was previously documented as internal/unsupported (the module docstring explicitly says "not meant to be used by external users"), the `__all__` restructure is not a semver breaking change.

The module docstring will be updated to reflect that Tier 1 APIs are supported for end users.

## Alternatives Considered

### B) Unified harness — extend `HassetteHarness` directly

Add `with_app(MyApp, config={...})` to `HassetteHarness`. This would be a single API to learn, but it conflates internal testing concerns (component-level harness) with end-user concerns (app-level testing). The thin wrapper approach keeps responsibilities clear and avoids risking regressions in hassette's own 200+ tests that use `HassetteHarness`.

### C) Standalone harness — no dependency on `HassetteHarness`

Build `AppTestHarness` from scratch using only public APIs. This would be the cleanest separation but would duplicate significant infrastructure (bus startup, scheduler startup, mock executor wiring) that `HassetteHarness` already handles well. The duplication would be a maintenance burden.

## Test Strategy

**Unit tests** for:
- `RecordingApi` — call recording, assertion helpers, reset, read delegation to StateProxy, `NotImplementedError` for unstubbed methods, `EntityNotFoundError` for unseeded entities, `mark_ready()` in `on_initialize`, `ApiProtocol` conformance
- `make_test_config()` — default values, override application, env var hermiticity
- `StateProxy._test_seed_state()` — verify cache population, write lock acquisition
- `_TestClock` — set, advance, `advance_time()` without `freeze_time()` raises `RuntimeError`, idempotent freeze (stops old patcher)

**Integration tests** for:
- `AppTestHarness` lifecycle — create, start, initialize app, shutdown, cleanup on `__aenter__` failure (verify exit stack unwinds correctly)
- `AppConfigurationError` — bad config produces helpful message, cleanup still runs
- Event simulation — `simulate_state_change` triggers registered handlers, reliable drain
- Time control — `freeze_time` + `advance_time` + `trigger_due_jobs` fires scheduled jobs (including repeating jobs — verify snapshot-based dispatch prevents infinite loops)
- Full end-to-end: instantiate an example app (e.g., MotionLights-like test app), simulate events, assert API calls
- Manifest and `_api_factory` save/restore — sequential tests don't corrupt class-level state
- Auto-tmpdir cleanup — verify temp directories are removed on exit

**Validation** — add tests to `hassette-examples` for at least 2 example apps (MotionLights and CoverScheduler) using the new API. This validates that the API actually works for real end-user apps. **Risk acknowledgment**: deferring the example-app validation to post-implementation means the API design is not proven ergonomic against a real app before implementation begins. If the implementation surfaces ergonomic issues, a design revision may be needed.

## Open Questions

- The exact drain target for `simulate_state_change` (which task bucket to poll) must be verified during implementation by tracing the actual task ownership path for bus-dispatched handlers through `BusService._stub_execute` → `InvokeHandler` → `listener.invoke(event)`.
- `set_state()` does NOT trigger state change events on the bus — it silently populates the cache for pre-test setup. Use `simulate_state_change()` to test event-driven behavior. The sentinel timestamp (1970-01-01) ensures subsequent `simulate_state_change()` always supersedes seeded values. Users must not call `freeze_time()` at the sentinel timestamp.

## Impact

**New files:**
- `src/hassette/test_utils/app_harness.py` — `AppTestHarness` class
- `src/hassette/test_utils/recording_api.py` — `RecordingApi` class (Resource subclass), `ApiProtocol`, `ApiCall` dataclass
- `src/hassette/test_utils/config.py` — `make_test_config()` factory
- `src/hassette/test_utils/_internal/__init__.py` — Tier 2 re-exports (move existing internal symbols here)

**Modified files:**
- `src/hassette/test_utils/__init__.py` — restructure exports with `__all__` for Tier 1 only, update docstring
- `src/hassette/core/state_proxy.py` — add `_test_seed_state(entity_id, state_dict)` method (test-only, acquires write lock)
- `src/hassette/core/context.py` — modify `set_global_hassette()` to return the `Token` from `ContextVar.set()`
- `src/hassette/app/app.py` — add `_api_factory: ClassVar[type[Resource] | None] = None` and use it in `__init__` (`factory = type(self)._api_factory or Api; self.api = self.add_child(factory)`)
- `pyproject.toml` — add `[project.optional-dependencies] test`

**Blast radius:** Low-to-moderate. Core changes are minimal and targeted:
- `StateProxy._test_seed_state()` — new test-only method, no existing behavior changed
- `context.set_global_hassette()` — returns token instead of None (backward compatible — callers that ignore the return value are unaffected)
- `App._api_factory` — new ClassVar with `None` default, preserving existing behavior when not set
- `SchedulerService` — no changes (trigger_due_jobs lives on AppTestHarness, accesses internals via the harness)
- Existing internal tests are unaffected (Tier 2 symbols remain importable via re-export)
