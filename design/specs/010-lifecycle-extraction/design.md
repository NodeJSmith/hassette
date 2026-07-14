# Design: Extract Framework-Internal Names from App's Public Surface

**Date:** 2026-07-13
**Status:** archived
**Scope-mode:** hold
**Research:** design/research/2026-07-13-lifecycle-extraction/research.md

## Problem

App inherits ~54 public names from Resource and LifecycleMixin. Only ~20 are app-author API; the remaining ~34 are framework plumbing — lifecycle state machines, child-resource wiring, readiness signaling, task bucket registration. These names appear in IDE autocomplete, create a false impression of stable API surface, and risk app authors calling sequence-unsafe methods that corrupt lifecycle state. Before the 1.0 API freeze, the public surface must reflect only what app authors should use.

## Goals

- Remove 16 non-polymorphic framework-internal methods from the Resource/LifecycleMixin class hierarchy entirely, replacing them with module-level functions.
- Add a `__dir__` override on App that exposes only the app-author API, hiding the remaining ~18 framework-internal names that cannot be structurally removed (polymorphic methods, properties, attributes, `add_child`).
- Maintain full test suite green — no silent breakage from spy-pattern changes.
- Add a `__dir__` allowlist test that catches future regressions where a new Resource name leaks into App's surface.

## Non-Goals

- Restructuring the Resource/LifecycleMixin inheritance hierarchy itself.
- Extracting polymorphic methods (`initialize`, `shutdown`, `cleanup`, `_force_terminal`, `_shutdown_children`, `_on_children_stopped`, `_finalize_shutdown`) — these require `super()` dispatch.
- Extracting properties — different construct with override semantics. `unique_name` and `instance_name` are app-author API (visible in `__dir__`); `app_key`, `config_log_level`, `status`, `owner_id`, and `task` are framework-internal (hidden via `__dir__`). None are extracted.
- Changing the `FinalMeta` metaclass or `@final` enforcement.
- Composition-based lifecycle alternative (deferred to post-1.0, issue #1237).

## User Scenarios

### App author: automation developer

- **Goal:** write and iterate on a Hassette automation
- **Context:** using IDE autocomplete on `self.` inside an App subclass

#### Clean autocomplete surface

1. **Types `self.` in `on_initialize`**
   - Sees: only app-author API names (`bus`, `scheduler`, `api`, `states`, `app_config`, lifecycle hooks, `is_ready`, `wait_ready`, `logger`, `cache`, etc.)
   - Decides: which method to call for their automation logic
   - Then: selects a method; no framework-internal names appear to confuse or mislead

### Framework contributor: hassette developer

- **Goal:** call lifecycle transitions on Resource instances from framework orchestration code
- **Context:** working in `app_lifecycle_service.py`, `service.py`, or `service_watcher.py`

#### Call lifecycle functions

1. **Imports lifecycle function**
   - Sees: `from hassette.resources.lifecycle import mark_ready`
   - Decides: which function matches the lifecycle transition needed
   - Then: calls `mark_ready(resource, reason="initialized")` with the resource as first argument

## Functional Requirements

- **FR#1** All 11 lifecycle state-transition methods (`handle_failed`, `handle_crash`, `handle_stop`, `handle_starting`, `handle_running`, `create_service_status_event`, `mark_ready`, `mark_not_ready`, `request_shutdown`, `start`, `cancel`) are module-level functions in `src/hassette/resources/lifecycle.py`, not methods on any class.
- **FR#2** Five structural-operation methods (`start_children_and_wait`, `restart`, `register_task_bucket_factory`, `run_hooks`, `ordered_children_for_shutdown`) are module-level functions in `src/hassette/resources/operations.py`, not methods on any class. The current method names `_run_hooks` and `_ordered_children_for_shutdown` drop the underscore prefix — they are no longer private methods on a class.
- **FR#8** `add_child` remains a method on Resource (used by `App.__init__` for child construction) but is excluded from `dir(app_instance)`.
- **FR#3** `dir()` on an App instance returns only the app-author API names: `logger`, `api`, `scheduler`, `bus`, `states`, `app_config`, `instance_name`, `unique_name`, `index`, `now`, `on_initialize`, `on_shutdown`, `before_initialize`, `after_initialize`, `before_shutdown`, `after_shutdown`, `task_bucket`, `cache`, `is_ready`, `wait_ready`. `dir()` on an AppSync instance returns the same 20 names plus the 6 sync hooks: `before_initialize_sync`, `on_initialize_sync`, `after_initialize_sync`, `before_shutdown_sync`, `on_shutdown_sync`, `after_shutdown_sync`.
- **FR#4** All framework call sites in `src/` that previously called `self.method()` or `instance.method()` for extracted methods now call the module-level function with the resource as the first argument.
- **FR#5** The `_LifecycleHostP` Protocol in `mixins.py` no longer requires `create_service_status_event` as a method — it is removed from the Protocol since the free function accesses the resource's attributes directly.
- **FR#6** A test asserts that `set(dir(app_instance))` matches the declared app-author API allowlist, catching future regressions.
- **FR#7** The 14 test files using spy-by-reassignment patterns (`instance.method = Mock()`) are redesigned to use `patch("hassette.resources.lifecycle.func")` or `patch("hassette.resources.operations.func")`.

## Edge Cases

- **Cross-method calls within extracted functions.** `handle_failed` calls `mark_not_ready` and `create_service_status_event`. Both are extracted, so the free function calls the other free function directly (same module import). No `self.` dispatch needed.
- **`_run_hooks` calls `handle_failed`.** Both are extracted. `_run_hooks` calls `handle_failed(resource, exc)` directly.
- **`register_task_bucket_factory` is a classmethod.** It becomes a plain module-level function that sets `Resource._default_task_bucket_factory`. Called once at module import time by `hassette.task_bucket`.
- **`mark_ready` has ~37 call sites** across `src/hassette/`. Most are `self.mark_ready(reason=...)` in service `on_initialize()` hooks and become `mark_ready(self, reason=...)`. A few are external calls (`inst.mark_ready(...)` in `app_lifecycle_service.py`, `harness.state_proxy.mark_ready(...)` in test utils) and become `mark_ready(inst, reason=...)` or `mark_ready(harness.state_proxy, ...)`.
- **`add_child` stays on Resource but is hidden.** `App.__init__` calls `self.add_child()` 4 times. It remains callable but invisible in autocomplete.

## Acceptance Criteria

- **AC#1** `dir(App(...))` returns exactly the app-author API allowlist defined in FR#3. Verified by `pytest tests/unit/app/test_app_dir.py`.
- **AC#2** `from hassette.resources.lifecycle import handle_failed, mark_ready` works — the functions exist as module-level exports. Verified by import test.
- **AC#3** `from hassette.resources.operations import start_children_and_wait, restart` works. Verified by import test.
- **AC#4** `hasattr(App(...), "handle_failed")` returns `False` — the method no longer exists on the class. Verified by test assertion.
- **AC#5** Full test suite passes: `uv run nox -s dev` exits 0.
- **AC#6** Linter and type checker pass: `prek -a && prek pyright -a --stage pre-push` exits 0.
- **AC#7** No spy-by-reassignment patterns remain for extracted methods: `grep -rn '\.handle_failed\s*=\|\.mark_ready\s*=\|\.handle_crash\s*=\|\.handle_stop\s*=\|\.handle_starting\s*=\|\.handle_running\s*=\|\.mark_not_ready\s*=\|\.request_shutdown\s*=\|\.create_service_status_event\s*=\|\.start\s*=.*Mock\|\.cancel\s*=.*Mock' tests/` returns no results for the extracted methods.

## Key Constraints

- **No compatibility shims.** Do not leave thin delegating stubs on the classes. Methods are deleted entirely; all call sites migrate in one wave.
- **Extract leaves first.** `create_service_status_event` and `mark_not_ready` must be extracted before `handle_failed` (which calls them). `mark_not_ready` before `request_shutdown` and `handle_stop`.
- **Do not modify `_LifecycleHostP` Protocol beyond removing `create_service_status_event`.** The Protocol's remaining attributes (`logger`, `hassette`, `role`, `class_name`, `unique_name`, `task_bucket`, `initialize`) stay unchanged.

## Dependencies and Assumptions

- No external hassette users (app authors) are currently calling the framework-internal methods being extracted. This is assumed based on the methods being undocumented and clearly internal.
- Issue #1234 (API stability policy docs) will consume the app-author API allowlist from FR#3 as the canonical supported surface.

## Architecture

### Module structure

Two new modules in `src/hassette/resources/`:

**`lifecycle.py`** — 11 functions for lifecycle state transitions:
- `handle_failed(resource: _LifecycleHostP, exception: BaseException) -> None`
- `handle_crash(resource: _LifecycleHostP, exception: Exception) -> None`
- `handle_stop(resource: _LifecycleHostP) -> None`
- `handle_starting(resource: _LifecycleHostP) -> None`
- `handle_running(resource: _LifecycleHostP) -> None`
- `create_service_status_event(resource: _LifecycleHostP, status, exception=None, ready=False, ready_phase=None) -> HassetteServiceEvent`
- `mark_ready(resource: _LifecycleHostP, reason: str | None = None) -> None`
- `mark_not_ready(resource: _LifecycleHostP, reason: str | None = None) -> None`
- `request_shutdown(resource: _LifecycleHostP, reason: str | None = None) -> None`
- `start(resource: _LifecycleHostP) -> None`
- `cancel(resource: _LifecycleHostP) -> None`

**`operations.py`** — 5 functions for structural operations:
- `start_children_and_wait(resource: Resource, timeout: float | None = None) -> None`
- `restart(resource: Resource) -> None`
- `register_task_bucket_factory(factory: Callable) -> None`
- `run_hooks(resource: Resource, hooks: list, *, continue_on_error: bool = False) -> None`
- `ordered_children_for_shutdown(resource: Resource) -> list[Resource]`

The `_LifecycleHostP` Protocol stays in `mixins.py` but is imported by `lifecycle.py` for type annotations. `operations.py` uses the concrete `Resource` type since its functions need full Resource access (children, hassette reference).

### `__dir__` on App

```python
_APP_PUBLIC_API: frozenset[str] = frozenset({
    "logger", "api", "scheduler", "bus", "states", "app_config",
    "instance_name", "unique_name", "index", "now",
    "on_initialize", "on_shutdown",
    "before_initialize", "after_initialize",
    "before_shutdown", "after_shutdown",
    "task_bucket", "cache",
    "is_ready", "wait_ready",
})

def __dir__(self) -> list[str]:
    return sorted(_APP_PUBLIC_API)
```

`AppSync` overrides `__dir__` to include its 6 sync hooks:

```python
_APPSYNC_HOOKS: frozenset[str] = frozenset({
    "before_initialize_sync", "on_initialize_sync", "after_initialize_sync",
    "before_shutdown_sync", "on_shutdown_sync", "after_shutdown_sync",
})

def __dir__(self) -> list[str]:
    return sorted(_APP_PUBLIC_API | _APPSYNC_HOOKS)
```

### `_LifecycleHostP` update

Remove `create_service_status_event` from the Protocol. The free function in `lifecycle.py` accesses `resource.hassette`, `resource.role`, `resource.class_name`, `resource.unique_name` directly — all are existing Protocol attributes.

### Call-site migration pattern

Framework code changes from:
```python
# Before (method on self)
await self.handle_failed(exc)

# After (module-level function)
from hassette.resources.lifecycle import handle_failed
await handle_failed(self, exc)
```

External orchestrators change from:
```python
# Before
inst.mark_ready(reason="initialized")

# After
from hassette.resources.lifecycle import mark_ready
mark_ready(inst, reason="initialized")
```

### Test spy migration pattern

```python
# Before (spy-by-reassignment — breaks with extraction)
svc.mark_ready = MagicMock()
await svc.on_initialize()
svc.mark_ready.assert_called_once()

# After (patch the module-level function)
with patch("hassette.resources.lifecycle.mark_ready") as mock_ready:
    await svc.on_initialize()
    mock_ready.assert_called_once_with(svc, reason="initialized")
```

## Implementation Preferences

No specific implementation preferences — follow codebase conventions.

## Replacement Targets

| Target | Replacement | Action |
|--------|-------------|--------|
| `LifecycleMixin.handle_failed()` and 10 other lifecycle methods | `resources/lifecycle.py` module-level functions | Delete from class, move body to module function |
| `Resource.start_children_and_wait()`, `restart()`, `_run_hooks()`, `_ordered_children_for_shutdown()` | `resources/operations.py` module-level functions | Delete from class, move body to module function |
| `Resource.register_task_bucket_factory()` classmethod | `resources/operations.py` module-level function | Delete classmethod, update import in `hassette.task_bucket` |
| `_LifecycleHostP.create_service_status_event` Protocol requirement | Removed from Protocol | Delete from Protocol definition |
| 14 spy-by-reassignment test files | `patch()` on module-level functions | Structural test redesign |

## Convention Examples

### Module-level utility operating on Resource instances

**Source:** `src/hassette/utils/service_utils.py`

```python
async def wait_for_ready(
    resources: "list[Resource] | Resource",
    timeout: float = 20,
    shutdown_event: asyncio.Event | None = None,
) -> bool:
    """Block until all dependent resources are ready or shutdown is requested."""
    resources = resources if isinstance(resources, list) else [resources]
    if not resources:
        return True
    # ...
```

### Protocol-typed self for lifecycle hosts

**Source:** `src/hassette/resources/mixins.py`

```python
class _LifecycleHostP(typing.Protocol):
    logger: logging.Logger
    hassette: "Hassette"
    role: ResourceRole
    class_name: str
    unique_name: str
    task_bucket: "TaskBucket"
    async def initialize(self, *args: Any, **kwargs: Any) -> None: ...
```

### Framework lifecycle orchestration call pattern

**Source:** `src/hassette/core/app_lifecycle_service.py`

```python
with anyio.fail_after(self.startup_timeout):
    await inst.initialize()
    inst.mark_ready(reason="initialized")
await self.emit_app_state_change(inst, status=RUNNING, previous_status=STARTING)
```

### Explicit public API via `__all__`

**Source:** `src/hassette/app/__init__.py`

```python
__all__ = [
    "App",
    "AppConfig",
    "AppSync",
    "BlockingIOBehavior",
    "ForgottenAwaitBehavior",
    "only_app",
]
```

## Alternatives Considered

### `__dir__` override only (Option B from research)

Add `__dir__` to App without extracting methods. Near-zero risk — no method signatures change, no call sites change, no tests change.

**Rejected because:** Names still technically exist on the class and are callable. `app.handle_failed(exc)` still works at runtime. The 1.0 API freeze would need to document "these methods exist but are not part of the stable API" rather than removing them outright. `hasattr(app, "handle_failed")` still returns True. Does not follow the functions-over-methods convention. Weaker guarantee.

### Underscore-prefix all framework-internal methods

Rename `handle_failed` to `_handle_failed`, etc. Convention-based hiding.

**Rejected because:** Bulk rename with high call-site churn that achieves less than extraction. `_` methods still appear in `dir()` (Python includes underscore-prefixed names). Doesn't remove the methods from the class. Worse signal than "method doesn't exist."

## Test Strategy

### Existing Tests to Adapt

14 test files use spy-by-reassignment patterns that silently break when methods become module-level functions:

| File | Pattern | Fix |
|------|---------|-----|
| `tests/unit/core/conftest.py:make_mock_app_instance` | `app.mark_ready = Mock()` | Patch `hassette.resources.lifecycle.mark_ready` |
| `tests/unit/scheduler/test_scheduler_error_handler.py` | `scheduler.mark_ready = MagicMock()` | Patch lifecycle module |
| `tests/unit/core/test_logging_service.py` | `svc.mark_ready = Mock()` | Patch lifecycle module |
| `tests/integration/test_web_ui_watcher.py` | `svc.mark_ready = MagicMock()` | Patch lifecycle module |
| `tests/integration/test_websocket_service.py` | `websocket_service.mark_ready = Mock()` | Patch lifecycle module |
| `tests/unit/core/test_web_ui_watcher.py` | `svc.mark_ready = MagicMock()` | Patch lifecycle module |
| `tests/unit/core/test_command_executor_pipeline.py` | `executor.mark_ready = MagicMock()` (3x) | Patch lifecycle module |
| `tests/unit/core/test_fatal_shutdown.py` | `resource.request_shutdown = Mock()` | Patch lifecycle module |
| `tests/unit/core/test_service_watcher_coverage.py` | `resource.request_shutdown = Mock()` | Patch lifecycle module |
| `tests/integration/test_fatal_shutdown.py` | `*.start = Mock()` (9x) | Patch `hassette.resources.lifecycle.start` |
| `tests/integration/test_core.py` | `*.start = Mock()` (5x) | Patch lifecycle module |
| `tests/unit/core/test_core_coverage.py` | `child.start = Mock()` (3x) | Patch lifecycle module |
| `tests/unit/resources/lifecycle/test_force_terminal.py` | `child.cancel = MagicMock()` | Patch `hassette.resources.lifecycle.cancel` |
| `tests/unit/core/test_app_lifecycle_service.py` | `lifecycle_service.handle_crash = AsyncMock()` | Patch `hassette.resources.lifecycle.handle_crash` |

~35 additional test files have direct method calls (`resource.handle_failed(exc)`) requiring mechanical rename to `handle_failed(resource, exc)`.

### New Test Coverage

- **`test_app_dir.py`** (FR#6) — assert `set(dir(app_instance))` matches `_APP_PUBLIC_API` allowlist.
- **Import tests** (FR#1, FR#2) — verify `lifecycle.py` and `operations.py` export the expected functions.
- **`hasattr` test** (AC#4) — verify extracted methods are truly gone from App instances.

### Tests to Remove

- Any assertions in `test_forgotten_await_completeness.py` that reference `INHERITED_LIFECYCLE_EXCLUSIONS` entries for extracted methods may need updating — the exclusion set should shrink since those methods no longer exist on the class.

## Documentation Updates

- Update `CLAUDE.md` Architecture section to note that lifecycle state transitions and structural operations are module-level functions in `resources/lifecycle.py` and `resources/operations.py`, not methods on Resource/LifecycleMixin.
- No docs-site page changes required — these are internal framework methods, not user-facing API.

## Impact

### Changed Files

**Shared / cross-cutting (higher risk):**
- `src/hassette/resources/mixins.py` — modify: delete 11 lifecycle method bodies from LifecycleMixin, update `_LifecycleHostP` Protocol
- `src/hassette/resources/base.py` — modify: delete `start_children_and_wait`, `restart`, `_run_hooks` (→ `run_hooks`), `_ordered_children_for_shutdown` (→ `ordered_children_for_shutdown`), `register_task_bucket_factory`; update remaining methods (`initialize`, `shutdown`, `cleanup`) to call module functions
- `src/hassette/resources/lifecycle.py` — create: 11 module-level lifecycle functions
- `src/hassette/resources/operations.py` — create: 5 module-level structural operations
- `src/hassette/resources/__init__.py` — modify: re-export lifecycle and operations for convenience
- `src/hassette/resources/service.py` — modify: update `initialize()`, `shutdown()`, `_serve_wrapper()` to call module functions

**Framework call-site updates (service subclasses — highest volume, `mark_ready` in `on_initialize()`):**
- `src/hassette/core/database_service.py` — modify: `self.mark_ready()` → `mark_ready(self)`
- `src/hassette/core/websocket_service.py` — modify: `self.mark_ready()` → `mark_ready(self)`
- `src/hassette/core/bus_service.py` — modify: `self.mark_ready()` → `mark_ready(self)`
- `src/hassette/core/scheduler_service.py` — modify: `self.mark_ready()` → `mark_ready(self)`
- `src/hassette/core/logging_service.py` — modify: `self.mark_ready()` → `mark_ready(self)`
- `src/hassette/core/sync_executor_service.py` — modify: `self.mark_ready()` → `mark_ready(self)`
- `src/hassette/core/web_api_service.py` — modify: `self.mark_ready()` → `mark_ready(self)`
- `src/hassette/core/web_ui_watcher.py` — modify: `self.mark_ready()` → `mark_ready(self)`
- `src/hassette/core/event_stream_service.py` — modify: `self.mark_ready()` → `mark_ready(self)`
- `src/hassette/core/runtime_query_service.py` — modify: `self.mark_ready()` → `mark_ready(self)`
- `src/hassette/core/session_manager.py` — modify: `self.mark_ready()` → `mark_ready(self)`
- `src/hassette/core/file_watcher.py` — modify: `self.mark_ready()` → `mark_ready(self)`
- `src/hassette/core/command_executor.py` — modify: `self.mark_ready()` → `mark_ready(self)`
- `src/hassette/core/telemetry/query_service.py` — modify: `self.mark_ready()` → `mark_ready(self)`

**Framework call-site updates (orchestration and per-app resources):**
- `src/hassette/core/app_lifecycle_service.py` — modify: `inst.mark_ready()` → `mark_ready(inst)`
- `src/hassette/core/core.py` — modify: update `handle_stop`, `_on_children_stopped()`, `shutdown()` call sites
- `src/hassette/core/service_watcher.py` — modify: update `restart()` call site
- `src/hassette/core/app_handler.py` — modify: update lifecycle call sites
- `src/hassette/core/api_resource.py` — modify: `self.mark_ready()` → `mark_ready(self)`
- `src/hassette/core/state_proxy.py` — modify: `self.mark_ready()` → `mark_ready(self)`
- `src/hassette/api/api.py` — modify: `self.mark_ready()` → `mark_ready(self)`
- `src/hassette/api/sync.py` — modify: update lifecycle call sites
- `src/hassette/bus/bus.py` — modify: `self.mark_ready()` → `mark_ready(self)`
- `src/hassette/bus/sync.py` — modify: update lifecycle call sites
- `src/hassette/scheduler/scheduler.py` — modify: `self.mark_ready()` → `mark_ready(self)`
- `src/hassette/scheduler/sync.py` — modify: update lifecycle call sites
- `src/hassette/state_manager/state_manager.py` — modify: `self.mark_ready()` → `mark_ready(self)`
- `src/hassette/app/app.py` — modify: add `__dir__` override, `_APP_PUBLIC_API` constant
- `src/hassette/task_bucket/task_bucket.py` — modify: update `register_task_bucket_factory` import

**Test utilities (call extracted methods on instances):**
- `src/hassette/test_utils/app_harness.py` — modify: update `mark_ready` call sites
- `src/hassette/test_utils/harness.py` — modify: update lifecycle call sites
- `src/hassette/test_utils/recording_api.py` — modify: update lifecycle call sites
- `src/hassette/test_utils/reset.py` — modify: update `mark_ready` call sites

**Test file updates (~40+ files):**
- 14 files with spy-by-reassignment patterns (structural redesign)
- ~35 files with direct method calls (mechanical rename)
- 1 new test file: `tests/unit/app/test_app_dir.py`
- `tests/unit/test_forgotten_await_completeness.py` — update exclusion set

### Behavioral Invariants

- All lifecycle state transitions (STARTING → RUNNING → STOPPED/FAILED/CRASHED) must produce the same events and status changes as before extraction.
- `mark_ready` must still set the `ready_event` and emit readiness events identically.
- `App.__init__` must still construct Bus, Scheduler, Api, and StateManager as children via `add_child`.
- `register_task_bucket_factory` must still be called at module import time by `hassette.task_bucket`.

### Blast Radius

- **Service subclasses** (DatabaseService, WebsocketService, BusService, SchedulerService, LoggingService, SyncExecutorService) — all call `self.mark_ready()` in their `on_initialize()` hooks. These are the highest-volume call sites (~37 total across all callers).
- **AppLifecycleService** — orchestrates lifecycle externally; calls `inst.mark_ready()`.
- **ServiceWatcher** — calls `restart()` on crashed services.
- **Test infrastructure** — `make_mock_app_instance()` in `conftest.py` sets up mock lifecycle methods.

## Open Questions

None — all architectural decisions resolved during discovery.
