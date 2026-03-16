---
feature_number: "007"
feature_slug: "refactor-apphandler-facade"
status: "approved"
created: "2026-03-16T21:09:50Z"
---

# Spec: Refactor AppHandler into Coordinator Facade

## Problem Statement

AppHandler (369 lines) mixes coordination logic with implementation details. It directly manages instance creation, lifecycle timeouts, event emission, and status transitions alongside its orchestration of start/stop/reload/apply operations. This entanglement makes it difficult to test individual concerns in isolation — lifecycle timeout behavior can't be verified without setting up the full AppHandler composition, and factory logic can't be exercised without the lifecycle manager wired in.

This is Phase 3 of the Hassette god-object decomposition (ADR-0002). Phases 1-2 successfully extracted SessionManager and EventStreamService from Hassette. Phase 3 applies the same principle to AppHandler's internal composition.

A secondary concern: the recent identity model incident (issues #335-337) revealed that app_key, instance_index, and owner_id semantics are fragile when code is restructured. Any refactor touching app management must preserve these semantics exactly.

## Goals

1. Reduce AppHandler to a thin coordinator that delegates implementation details to focused services
2. Make each app management concern independently testable with focused fixtures (no full AppHandler wiring needed)
3. Preserve all public APIs — no breaking changes for web routes, Hassette core, or RuntimeQueryService
4. Preserve correct identity model semantics (app_key, instance_index, owner_id) throughout the refactored services
5. Maintain or improve existing test coverage

## Non-Goals

- Changing what AppHandler does (behavior must be identical before and after)
- Adding new features (e.g., UI app toggle without dev mode — tracked separately)
- Modifying AppRegistry's internal structure (already well-organized at 365 lines)
- Modifying AppChangeDetector's internal structure (already focused at 110 lines)
- Promoting AppFactory to a Service (it has no lifecycle needs)
- Changing web route endpoints or dependency injection patterns

## User Scenarios

### Scenario 1: Developer writes a test for app initialization timeout

Before: Developer must wire up AppHandler with AppRegistry, AppFactory, AppLifecycleManager, AppChangeDetector, a mock Hassette, and a Bus instance to test that initialization times out correctly after N seconds.

After: Developer creates an AppLifecycleService with a mock registry and factory, then verifies timeout behavior directly. No AppHandler, no Hassette mock, no Bus setup needed.

### Scenario 2: Developer investigates a startup failure

Before: Debugging requires tracing through AppHandler's start_app, which calls factory.create_instances (which registers to registry and records failures), then lifecycle.initialize_instances (which emits events and records failures). The flow crosses four objects.

After: AppLifecycleService owns the full create-init-register flow. The developer reads one service to understand what happens during startup, with clear delegation to AppFactory for class loading.

### Scenario 3: CI verifies app management behavior

Before: Integration tests set up HassetteHarness to test app start/stop/reload because AppHandler can't run without its parent.

After: Integration tests can exercise AppLifecycleService directly with a real AppRegistry and mock database, covering the same behavior with simpler setup. Full HassetteHarness tests remain for end-to-end verification.

## Functional Requirements

### FR-1: AppLifecycleService

The system must provide an AppLifecycleService that owns instance creation, initialization, shutdown, and status event emission.

**Acceptance criteria:**
- AppLifecycleService extends the Service base class with proper lifecycle hooks
- It uses AppFactory internally for class loading, config validation, and instance creation
- It manages initialization with configurable timeout (currently from hassette.config)
- It manages shutdown with configurable timeout
- It emits app state change events on status transitions
- It records failures to AppRegistry when initialization or shutdown fails
- It is testable without AppHandler — a focused test fixture can create one with a mock registry and factory

### FR-2: AppHandler as Coordinator

AppHandler must retain coordination logic (start/stop/reload/apply/bootstrap) while delegating implementation details to services.

**Acceptance criteria:**
- AppHandler orchestrates start_app by calling AppLifecycleService (which handles create + init)
- AppHandler orchestrates stop_app by calling AppLifecycleService (which handles shutdown + unregister)
- AppHandler orchestrates reload_app as stop + start via AppLifecycleService
- AppHandler orchestrates apply_changes using AppChangeDetector results and AppLifecycleService operations
- AppHandler orchestrates bootstrap_apps as config load + only_app resolution + parallel start
- AppHandler handles file watcher events by calling AppChangeDetector then apply_changes
- AppHandler size is reduced from 369 lines to approximately 150-180 lines

### FR-3: Preserved Public APIs

All existing public interfaces must continue to work identically.

**Acceptance criteria:**
- `app_handler.get(app_key, index)` returns the correct app instance
- `app_handler.all()` returns all running instances
- `app_handler.get_status_snapshot()` returns an immutable AppStatusSnapshot
- `app_handler.start_app(app_key)`, `stop_app(app_key)`, `reload_app(app_key)` work identically
- `hassette.apps`, `hassette.get_app()` continue to delegate correctly
- Web routes (`/apps`, `/apps/{app_key}/start`, etc.) work without modification
- RuntimeQueryService queries return identical results

### FR-4: Identity Model Preservation

The refactored code must preserve correct app_key, instance_index, and owner_id semantics.

**Acceptance criteria:**
- app_key used in AppRegistry, AppLifecycleService, and AppFactory matches the config key (not unique_name)
- instance_index correctly identifies individual instances within multi-instance app configurations
- owner_id in Bus listeners and Scheduler jobs matches the app_key from the parent App
- No new hardcoded instance_index=0 assumptions introduced
- Existing identity model tests continue to pass

### FR-5: Independent Test Fixtures

Each refactored service must have focused test fixtures.

**Acceptance criteria:**
- A test helper or fixture can create an AppLifecycleService with mock dependencies (registry, factory, event stream)
- Existing AppRegistry tests continue to pass without modification
- Existing AppChangeDetector tests continue to pass without modification
- Existing AppFactory tests continue to pass without modification
- New AppLifecycleService tests cover: initialization success, initialization timeout, initialization failure recording, shutdown success, shutdown timeout, event emission on state transitions
- HassetteHarness updated to reflect the new composition

## Edge Cases

1. **Concurrent start/stop during bootstrap** — If a user triggers stop_app while bootstrap_apps is still initializing, the coordinator must handle the race correctly (current behavior preserved).
2. **Factory returns no instances** — If AppFactory fails to load a class or all configs are invalid, AppLifecycleService must handle the empty-instances case gracefully and record appropriate failures.
3. **Shutdown during initialization** — If Hassette shuts down while AppLifecycleService is initializing an app, the cancellation must propagate correctly through anyio timeout scopes.
4. **only_app filter with blocked apps** — The reconciliation of blocked apps when only_app changes must work correctly through the coordinator (current behavior preserved).

## Dependencies and Assumptions

**Dependencies:**
- Resource/Service base classes — AppLifecycleService extends Service
- AppFactory — used internally by AppLifecycleService (not promoted to Service)
- EventStreamService (from Phase 2) — AppLifecycleService uses it for event emission
- anyio — for timeout handling in lifecycle operations

**Assumptions:**
- The Resource/Service lifecycle hooks (on_initialize, on_shutdown, mark_ready) are stable and well-tested
- AppRegistry's public API is stable and doesn't need changes for this refactor
- AppChangeDetector's interface is stable and doesn't need changes
- The identity model fixes from issues #335-337 are already merged and correct
- Existing test infrastructure (HassetteHarness, conftest fixtures) can be extended incrementally

## Acceptance Criteria

1. AppHandler is reduced from 369 lines to approximately 150-180 lines
2. AppLifecycleService exists as an independently testable Service
3. All existing tests pass without modification to test assertions (test setup may change)
4. Web routes work identically (verified by existing e2e tests)
5. AppRegistry and AppChangeDetector code is unchanged
6. No new identity model bugs introduced (app_key, instance_index, owner_id all correct)
7. Each service has focused test fixtures that don't require full Hassette wiring
8. Type checking passes (pyright)
9. Linting passes (ruff)
10. HassetteHarness is updated to reflect the new AppHandler composition
