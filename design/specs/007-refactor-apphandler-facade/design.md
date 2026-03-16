# Design: Refactor AppHandler into Coordinator Facade

**Date:** 2026-03-16
**Status:** approved
**Spec:** design/specs/007-refactor-apphandler-facade/spec.md

## Problem

AppHandler (369 lines, `src/hassette/core/app_handler.py`) mixes coordination logic (~51 lines) with implementation details (~165 lines). Methods like `start_app`, `bootstrap_apps`, `handle_change_event`, and `_resolve_only_app` directly orchestrate factory creation, lifecycle initialization, event emission, and config reloading — making it impossible to test lifecycle behavior without wiring up the full AppHandler composition.

This is Phase 3 of ADR-0002. Phases 1-2 successfully extracted SessionManager and EventStreamService from Hassette using a proven pattern (Resource child, `mark_ready()`, property forwarding). Phase 3 applies the same principle to AppHandler's internals.

Additionally, the identity model incident (issues #335-337) demonstrated that app_key/instance_index/owner_id semantics are fragile during restructuring. This refactor must preserve those semantics exactly.

## Non-Goals

- Changing AppHandler's external behavior (identical before/after)
- Adding new features (UI app toggle without dev mode tracked separately)
- Modifying AppRegistry (365 lines, already well-structured)
- Modifying AppChangeDetector (110 lines, already focused)
- Promoting AppFactory to a Service (no lifecycle needs)
- Changing web route endpoints or dependency injection
- Optimizing fixture scoping or test performance

## Architecture

### Overview

Create `AppLifecycleService(Resource)` as a child of AppHandler. It absorbs:
1. All methods from the current `AppLifecycleManager` class (folded in, not preserved as internal class)
2. Implementation methods from AppHandler: `bootstrap_apps`, `start_app`, `stop_app`, `reload_app`, `start_apps`, `apply_changes`, `handle_change_event`, `refresh_config`, `_resolve_only_app`, `_update_only_app_filter`, `_reconcile_blocked_apps`
3. The Bus child (for file watcher subscription)
4. A reference to AppFactory (plain utility, not a child)

AppHandler becomes a thin coordinator (~120-150 lines) that:
- Owns AppRegistry (plain class) and AppLifecycleService (Resource child)
- Exposes public API via delegation (`.get()`, `.all()`, `.apps`, `.get_status_snapshot()`)
- Delegates start/stop/reload to AppLifecycleService
- Handles lifecycle coordination: waits for Hassette deps in `on_initialize`, spawns bootstrap in `after_initialize`, delegates shutdown

### AppHandler (after refactor)

```
class AppHandler(Resource):
    registry: AppRegistry          # plain class (unchanged)
    lifecycle: AppLifecycleService  # new Resource child

    __init__:
        - Create AppRegistry
        - Add AppLifecycleService as child (receives registry, change_detector refs)
        - Set log levels from config

    # --- Public API (thin delegation) ---
    apps → registry.apps
    get(app_key, index) → registry.get(app_key, index)
    all() → registry.all_apps()
    get_status_snapshot() → registry.get_snapshot()
    set_apps_configs(apps_config) → registry.set_manifests(...)

    # --- Lifecycle hooks ---
    on_initialize:
        - Wait for Hassette services (websocket, api, bus, scheduler, state_proxy)
        - mark_ready()
    after_initialize:
        - Spawn lifecycle.bootstrap_apps() via task_bucket
    on_shutdown:
        - Await lifecycle.shutdown_all()

    # --- Delegated operations ---
    start_app(app_key, force_reload) → lifecycle.start_app(...)
    stop_app(app_key) → lifecycle.stop_app(...)
    reload_app(app_key, force_reload) → lifecycle.reload_app(...)
```

### AppLifecycleService (new)

Location: `src/hassette/core/app_lifecycle_service.py`

```
class AppLifecycleService(Resource):
    registry: AppRegistry          # shared ref from AppHandler
    factory: AppFactory            # plain utility (created internally)
    change_detector: AppChangeDetector  # plain utility (created internally)
    bus: Bus                       # child Resource for file watcher events

    __init__(hassette, *, parent, registry):
        - Store registry reference
        - Create AppFactory (plain class)
        - Create AppChangeDetector (plain class)
        - Add Bus as child
        - Subscribe bus to file watcher events → handle_change_event

    on_initialize:
        - mark_ready()

    # --- From AppLifecycleManager (folded in) ---
    initialize_instances(app_key, instances, manifest):
        - Wrap each instance init in anyio.fail_after(startup_timeout)
        - Set status = RUNNING on success
        - Record failures to registry + emit state events
    shutdown_instance(app):
        - Wrap in anyio.fail_after(shutdown_timeout)
        - Emit state events
    shutdown_instances(instances):
        - Set status = STOPPING, call shutdown_instance for each
    shutdown_all():
        - Shutdown all registered apps, clear registry
    startup_timeout / shutdown_timeout:
        - Read from hassette.config

    # --- From AppHandler (moved) ---
    bootstrap_apps():
        - Load config via refresh_config()
        - Resolve only_app filter
        - Reconcile blocked apps
        - Start all active apps
        - Emit APP_LOAD_COMPLETED
    start_app(app_key, force_reload):
        - Get manifest from registry
        - Emit NOT_STARTED for each instance
        - Create instances via factory
        - Initialize via initialize_instances
    stop_app(app_key):
        - Unregister from registry
        - Shutdown instances
    reload_app(app_key, force_reload):
        - stop_app + start_app
    start_apps(apps):
        - Parallel initialization of multiple apps
    apply_changes(changes: ChangeSet):
        - Stop orphans, reimport changed, reload config changes, start new
    handle_change_event(changed_file_paths):  # Bus handler with DI annotations preserved
        - Call refresh_config
        - Call change_detector.detect_changes
        - Call apply_changes
    refresh_config():
        - Reload hassette config
        - Update registry manifests
    _resolve_only_app(changed_file_paths):
        - Check @only_app decorator via factory
        - Update registry filter
    _update_only_app_filter(app_key):
        - Set registry.only_app and change_detector filter
    _reconcile_blocked_apps():
        - Unblock/block apps based on only_app state
```

### Dependency Flow

```
Hassette
  └─ AppHandler (Resource child)
       ├─ AppRegistry (plain class, shared reference)
       └─ AppLifecycleService (Resource child)
            ├─ AppFactory (plain class, internal)
            ├─ AppChangeDetector (plain class, internal)
            └─ Bus (Resource child, file watcher events)
```

AppLifecycleService receives `registry` as a constructor parameter from AppHandler. It creates AppFactory and AppChangeDetector internally (they don't need to be shared).

### Event Emission

All app state events consolidate in AppLifecycleService:
- `NOT_STARTED` — emitted in `start_app()` before initialization (currently split: AppHandler line 326)
- `RUNNING` / `FAILED` — emitted in `initialize_instances()` (currently in AppLifecycleManager)
- `STOPPING` / `STOPPED` — emitted in `shutdown_instances()` (currently in AppLifecycleManager)
- `APP_LOAD_COMPLETED` — emitted in `bootstrap_apps()` (currently in AppHandler)

All events use `self.hassette.send_event()` (accessible via Resource base class).

### Task Bucket Ownership

Task spawning moves from AppHandler to AppLifecycleService:
- `bootstrap_apps` is still spawned by AppHandler via `self.task_bucket.spawn(self.lifecycle.bootstrap_apps())` in `after_initialize`
- `initialize_instances` uses AppLifecycleService's own `task_bucket` for parallel app init
- During shutdown, AppLifecycleService's task_bucket is cancelled before AppHandler's (child shuts down before parent) — correct ordering

### Identity Model Preservation

The refactored code preserves identity semantics from the #335-337 fixes:
- `app_key` flows from `AppManifest` → `AppFactory.create_instances()` → `App.__init__()` → unchanged
- `instance_index` is assigned by AppFactory during multi-instance creation → unchanged
- `owner_id` is set by App during Bus/Scheduler registration → unchanged
- AppLifecycleService never creates or modifies these values; it passes them through

### Files Unchanged

- `src/hassette/core/app_registry.py` — no changes
- `src/hassette/core/app_change_detector.py` — no changes (moved to AppLifecycleService ownership)
- `src/hassette/core/app_factory.py` — no changes (moved to AppLifecycleService ownership)
- `src/hassette/core/core.py` — no changes (AppHandler is already a child)
- `src/hassette/web/routes/apps.py` — no changes (calls `hassette.app_handler.start_app()` etc.)
- `src/hassette/core/runtime_query_service.py` — no changes (accesses `hassette.app_handler.registry`)

### Test Strategy

**Unit tests:**
- Delete `tests/unit/test_app_lifecycle.py` (tests AppLifecycleManager which no longer exists)
- Create `tests/unit/core/test_app_lifecycle_service.py` — test AppLifecycleService with mock Hassette, real AppRegistry, mock AppFactory
- Cover: init success/timeout/failure, shutdown success/timeout, event emission, only_app resolution, change handling
- `tests/unit/test_app_factory.py` — unchanged
- `tests/unit/core/test_app_registry.py` — unchanged
- `tests/unit/core/test_app_change_detector.py` — unchanged

**Integration tests:**
- `tests/integration/test_apps.py` — may need minor setup updates if it accesses AppHandler internals
- `tests/integration/test_app_factory_lifecycle.py` — update to construct AppLifecycleService instead of separate AppFactory + AppLifecycleManager
- `tests/integration/test_hot_reload.py` — update patches from `app_handler.change_detector` to `app_handler.lifecycle.change_detector`

**Test fixtures:**
- Add a `create_app_lifecycle_service(registry, hassette)` helper in conftest or fixtures
- `HassetteHarness` — AppLifecycleService is auto-created as AppHandler child, minimal changes expected

## Alternatives Considered

### Option B: Two-service split (AppLifecycleService + AppConfigService)

Split into lifecycle management and config management services. Rejected because:
- Config reload and lifecycle are deeply intertwined (`handle_change_event` calls both)
- `_resolve_only_app` needs access to both AppFactory (lifecycle) and AppRegistry (config) — awkward split
- Over-engineering for current complexity
- ADR-0002 specifies AppChangeDetector as unchanged; a config service would be scope expansion

### Option C: Minimal refactor (move only core lifecycle methods)

Move only `start_app`/`stop_app`/`reload_app`/`bootstrap_apps` to AppLifecycleService, leave change handling in AppHandler. Rejected because:
- AppHandler would still be ~220-250 lines (doesn't meet the ~150-180 target)
- Change handling methods directly call lifecycle methods, creating bidirectional dependency
- Doesn't fully achieve ADR-0002 Phase 3 goals

### Preserve AppLifecycleManager as internal class

Keep AppLifecycleManager inside AppLifecycleService rather than folding its methods in. Rejected because:
- AppLifecycleManager is only 163 lines — not worth the indirection
- Methods integrate naturally with the moved AppHandler methods
- Folding in produces a cleaner single-class design
- Unit tests should be rewritten for the new service interface anyway

## Open Questions

None — all resolved during planning interrogation.

## Impact

### Files modified

| File | Change | Risk |
|------|--------|------|
| `src/hassette/core/app_handler.py` | Major refactor: 369 → ~120-150 lines | Medium — must preserve all public API |
| `src/hassette/core/app_lifecycle.py` | Deleted (replaced by app_lifecycle_service.py) | Low — clean replacement |
| `tests/unit/test_app_lifecycle.py` | Deleted (replaced by new test file) | Low — clean replacement |
| `tests/integration/test_app_factory_lifecycle.py` | Update construction to use AppLifecycleService | Medium — 506 lines, significant test file |
| `tests/integration/test_hot_reload.py` | Update patches for new structure | Low-Medium — patch paths change |

### Files created

| File | Purpose |
|------|---------|
| `src/hassette/core/app_lifecycle_service.py` | New AppLifecycleService (~250-280 lines) |
| `tests/unit/core/test_app_lifecycle_service.py` | Unit tests for AppLifecycleService |

### Files unchanged

- `src/hassette/core/app_registry.py`
- `src/hassette/core/app_change_detector.py`
- `src/hassette/core/app_factory.py`
- `src/hassette/core/core.py`
- `src/hassette/web/routes/apps.py`
- `src/hassette/core/runtime_query_service.py`
- `tests/unit/test_app_factory.py`
- `tests/unit/core/test_app_registry.py`
- `tests/unit/core/test_app_change_detector.py`

### Blast radius

- 2 source files modified/deleted, 1 created
- 2-3 test files modified/deleted, 1 created
- 0 web route changes
- 0 Hassette core changes
- Public API unchanged
