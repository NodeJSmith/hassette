# Design: Migrate hassette_instance fixture to public API

**Date:** 2026-07-10
**Status:** approved
**Scope-mode:** hold

## Problem

34 integration tests across three files (`test_core.py`, `test_fatal_shutdown.py`, `test_resource_deps.py`) access Hassette services through private attributes like `hassette_instance._database_service` and `hassette_instance._session_manager`. When `Hassette.wire_services()` changes — adding a service, renaming an attribute, changing constructor args — these tests silently drift from the real API. The fixture teardown also reaches into private stream state (`_event_stream_service.event_streams_closed`, `_bus_service.stream._closed`), creating a second fragile surface.

Hassette already exposes public property accessors for 12+ services (`database_service`, `bus_service`, `scheduler_service`, etc.). The tests use private attributes for all services, including those with existing public properties.

## Goals

- Eliminate private-attribute access for service lookups in all three test files
- Add public properties to `Hassette` for the 3 services with behavioral test usage (`session_manager`, `event_stream_service`, `bus`); rewrite the constructor-registration test to use `children` for the remaining 5
- Refactor structural invariant tests (`_init_waves`, `_init_order`) to test pure functions directly
- Consolidate the fixture teardown into a test-only helper function
- Annotate the ~30 remaining private-access sites (state machine internals and SessionManager internal fields) as intentional

## User Scenarios

### Test author: Developer writing or maintaining integration tests

- **Goal:** Access Hassette services without coupling to private attribute names
- **Context:** Writing tests for coordinator behavior (startup, shutdown, dependency ordering)

#### Access a wired service

1. **Create a Hassette instance via the fixture**
   - Sees: A fully-wired, un-started Hassette instance
   - Then: Access services via public properties like `hassette_instance.session_manager`

#### Validate structural invariants

1. **Test dependency ordering**
   - Sees: The public `children` list on the Hassette instance
   - Decides: Which invariant to validate (coverage, uniqueness, ordering)
   - Then: Call `topological_levels()` or `topological_sort()` with the child type list directly

## Functional Requirements

- **FR#1** `Hassette` exposes a public `session_manager` property that returns the wired `SessionManager` or raises when not wired. Justification: 35 test accesses for session lifecycle mocking (`mark_orphaned_sessions`, `create_session`, `finalize_session`); no existing narrow accessor covers this use case (`session_id`/`try_session_id` expose computed facts, not the object).
- **FR#2** `Hassette` exposes a public `event_stream_service` property that returns the wired `EventStreamService` or raises when not wired. Justification: behavioral test usage for stream lifecycle (`close_streams()`) and event delivery (`receive_stream.receive()`); `event_streams_closed` is a narrow proxy but tests need the object for these operations.
- **FR#3** `Hassette` exposes a public `bus` property that returns the wired `Bus` instance or raises when not wired. Justification: 4 behavioral test accesses in `before_shutdown` tests to mock `remove_all_listeners`; `bus_service` exposes the service wrapper, not the Bus instance itself.
- **FR#4** `test_constructor_registers_background_services` is rewritten to assert type-membership via `hassette_instance.children` (matching the FR#6 pattern), eliminating the need for properties on `service_watcher`, `file_watcher`, `web_api_service`, `web_ui_watcher`, and `scheduler` — these had zero behavioral test usage outside that one type-assertion test.
- **FR#5** All integration tests in `test_core.py`, `test_fatal_shutdown.py`, and `test_resource_deps.py` that read service instances use public properties instead of private attributes
- **FR#6** Structural invariant tests (`_init_waves`, `_init_order`) call `topological_levels()` and `topological_sort()` directly with `[type(c) for c in hassette.children]` instead of reading private attributes
- **FR#7** The `hassette_instance` fixture teardown delegates stream cleanup to a test-only helper function in `tests/integration/conftest.py` rather than reaching into private stream state inline
- **FR#8** Private-attribute access sites that test state machine internals are annotated with `# coordinator-internal` comments AND enforced by a CI lint (extending `tools/check_internal_patches.py` or a sibling script in the same pattern). This covers four categories: (a) `_fatal_shutdown_reason` reset to `None` (~1 site; the other 3 writes migrate to `record_fatal_reason()`), (b) `_loop`/`_loop_watchdog` access (~4 sites — `_loop_thread_id` has a public property and migrates normally), (c) `SessionManager` internal fields accessed after obtaining it via the public property — `sm._session_id`, `sm._session_error`, `sm._database_service`, `sm._session_lock` (~20 sites in `test_core.py:324-350` and `test_fatal_shutdown.py:159-200`). The lint fails when a private-attribute access in the affected test files lacks the annotation, preventing unannotated drift.

## Edge Cases

- **Property access before `wire_services()`**: Each new property raises `RuntimeError` via `_service_not_wired_error()` when the backing slot is `None`, matching the existing pattern.
- **`fatal_shutdown_reason` reads vs writes**: The public read-only property already exists. Tests that READ the value migrate to `hassette_instance.fatal_shutdown_reason`. For writes: `Hassette.record_fatal_reason(reason)` (`core.py:664`) is a public method with "first reason wins" semantics. 3 of 4 write sites (lines 41, 136, 162 in `test_fatal_shutdown.py`) set a reason when it's `None` — matching `record_fatal_reason()` exactly; these migrate to the public method. Only the reset site (line 187, `= None`) has no public equivalent and keeps private access with annotation.
- **HassetteHarness unchanged**: `HassetteHarness` reads and writes Hassette private slots directly as part of its lifecycle control. This is intentional — the harness owns the construction of those slots and the coupling is inherent. It is not changed in this migration.

## Acceptance Criteria

- **AC#1** Zero `hassette_instance._<service>` access patterns remain for the 15 services that have public properties (FR#1-FR#3 for new properties, FR#4 for constructor-test rewrite, FR#5 for migration)
- **AC#2** `test_init_waves_cover_all_children`, `test_init_waves_have_no_duplicates`, `test_init_waves_respect_dependency_ordering`, and `test_init_order_contains_all_children` call `topological_levels()` / `topological_sort()` directly — no `_init_waves` or `_init_order` access (FR#6)
- **AC#3** The `hassette_instance` fixture teardown contains no inline private-attribute access (FR#7)
- **AC#4** All remaining private-attribute access sites have a `# coordinator-internal` annotation, enforced by CI lint (FR#8)
- **AC#5** All tests pass with no behavior change (`uv run nox -s dev`)
- **AC#6** `prek -a` passes (lint + type check)
- **AC#7** HassetteHarness is unchanged — no delegation update (see Architecture section for rationale)

## Key Constraints

No feature-specific constraints identified during discovery.

## Dependencies and Assumptions

No external dependencies. Assumes `wire_services()` continues to populate the private slots that the new properties read from — this is the existing pattern for all 12+ current properties.

## Architecture

### New properties on Hassette

Add 3 properties to `src/hassette/core/core.py` following the exact pattern of existing properties like `database_service` (lines 349-354):

```python
@property
def session_manager(self) -> SessionManager:
    """SessionManager instance for session lifecycle management."""
    if self._session_manager is None:
        raise _service_not_wired_error("SessionManager")
    return self._session_manager
```

Each property: guards against `None`, raises `_service_not_wired_error()`, returns the typed instance. Place them in the existing property block, grouped logically with related services.

### Stream cleanup helper

Add a `cleanup_hassette_streams()` async helper function in `tests/integration/conftest.py` (not on the production `Hassette` class — this teardown logic has a live-instance hazard and belongs in test infrastructure):

```python
async def cleanup_hassette_streams(instance: Hassette) -> None:
    """Close event streams and the bus service's cloned receive stream.

    Both underlying close operations are idempotent, so no pre-check is needed —
    suppress(Exception) alone handles the not-yet-wired and already-closed cases.
    """
    with suppress(Exception):
        await instance._event_stream_service.close_streams()
    with suppress(Exception):
        await instance._bus_service.stream.aclose()
```

The fixture teardown becomes `await cleanup_hassette_streams(instance)`. This keeps the teardown consolidation benefit (single function, not inline private-attr access) without adding a hazardous method to the production API surface.

### Structural test refactoring

The 4 structural invariant tests in `test_resource_deps.py` and `test_core.py` change from:

```python
# Before: reads private attr
wave_types = {t for wave in hassette_instance._init_waves for t in wave}
```

To:

```python
# After: calls the pure function with public data
from hassette.utils.service_utils import topological_levels
child_types = list(dict.fromkeys(type(c) for c in hassette_instance.children))
waves = topological_levels(child_types)
wave_types = {t for wave in waves for t in wave}
```

### HassetteHarness — no changes

`HassetteHarness` is not changed in this migration. Its properties already read `self.hassette._bus`, `self.hassette._scheduler_service`, etc. directly — the same private slots it writes to in its `_start_*` methods. Making reads indirect while writes stay direct would be asymmetric and remove no real coupling. The harness is an internal test infrastructure class that constructs Hassette's internals from scratch; it is not the same problem as test files coupling to private attribute names they don't own.

## Implementation Preferences

No specific implementation preferences — follow codebase conventions.

## Replacement Targets

- **Private-attribute access in test files** — ~126 access sites across `test_core.py` (~72), `test_fatal_shutdown.py` (~50), `test_resource_deps.py` (~4). Of these, ~96 migrate to public properties and ~30 remain as annotated `# coordinator-internal` accesses (SessionManager internals, fatal shutdown writes, loop state). Old service-access patterns removed outright; no migration period.
- **Fixture teardown stream cleanup** — the manual `_event_stream_service.event_streams_closed` / `_bus_service.stream._closed` checks in `tests/integration/conftest.py:32-38` replaced by a single `cleanup_streams()` call.
- **HassetteHarness** — unchanged. Its properties read/write Hassette private slots as part of lifecycle control; this coupling is inherent to the harness's purpose and is not the same problem as test-file coupling to attribute names.

## Convention Examples

### Hassette service property pattern

**Source:** `src/hassette/core/core.py:349-354`

```python
@property
def database_service(self) -> DatabaseService:
    """DatabaseService instance for SQLite telemetry storage."""
    if self._database_service is None:
        raise _service_not_wired_error("DatabaseService")
    return self._database_service
```

### HassetteHarness property delegation

**Source:** `src/hassette/test_utils/harness.py:359-365`

```python
@property
def bus_service(self) -> "BusService":
    """The BusService instance managed by this harness."""
    bs = self.hassette._bus_service
    if bs is None:
        raise RuntimeError("BusService is not available — ensure with_bus() was called")
    return bs
```

This pattern is unchanged by this migration — the harness's direct private-slot access is intentional (see Architecture → HassetteHarness section).

### Pure function test (existing pattern)

**Source:** `tests/integration/test_core.py:407-424`

```python
def test_graph_validation_catches_missing_type() -> None:
    class _GhostDep(Resource):
        """A resource type absent from the registered child list."""

    class _StubService(DatabaseService):
        restart_spec = RestartSpec()
        depends_on: ClassVar[list[type[Resource]]] = [_GhostDep]

    with pytest.raises(ValueError, match="_GhostDep"):
        validate_dependency_graph([_StubService])
```

Tests the function directly with synthetic input — no Hassette instance needed for the invariant under test.

## Alternatives Considered

**A. `get_child(Type)` generic lookup on Resource** — Add a single typed lookup method instead of individual properties. Rejected: less discoverable than named properties, inconsistent with the 12+ existing property pattern, and the IDE autocompletion story is worse.

**B. HassetteHarness coordinator mode** — Add a `for_coordinator_tests()` classmethod that creates a real (not `_TestableHassette`), fully-wired, un-started instance. Rejected: only one consumer (this fixture), over-engineering for a 15-line fixture. The fixture's real problem is private-attr access, not the fixture itself.

**C. Declarative wiring** — Make `wire_services()` iterate over a data structure instead of imperative `add_child()` calls. Rejected: higher effort, limited benefit — the wiring has ordering constraints and per-service constructor args that make a flat declaration awkward. Would be worthwhile if wire_services() needed to be tested in isolation, but it doesn't.

## Test Strategy

### Existing Tests to Adapt

All 34 tests across the three affected files need adaptation:

- `tests/integration/test_core.py` — 22 tests: migrate ~72 private-attr accesses to public properties. `test_init_order_contains_all_children` refactored to use `topological_sort()` directly. `test_init_order_has_no_cycles` already calls `topological_sort()` directly today — no change needed. `test_concurrent_crash_and_finalize_are_serialized` and `test_finalize_*` tests access `SessionManager` internals (`_session_id`, `_session_error`, `_database_service`, `_session_lock`) — these remain with `# coordinator-internal` annotations.
- `tests/integration/test_fatal_shutdown.py` — 7 tests: migrate ~50 private-attr accesses. ~4 `_fatal_shutdown_reason` writes and ~20 `SessionManager` internal field accesses remain with annotation.
- `tests/integration/test_resource_deps.py` — 5 tests: 3 `_init_waves` tests refactored to use `topological_levels()` directly, 2 use public `children`/`add_child` (already public).

### New Test Coverage

No new test files. The new properties are exercised by the migrated tests themselves.

Note: the structural invariant test refactor (FR#6) is not a pure 1:1 transform — it changes *what* is verified, not just how. Today's tests read the actual `_init_waves`/`_init_order` values that `wire_services()` computed and stored. After refactoring, tests recompute `topological_levels()` from `children` and assert on the recomputed value, never touching the stored attribute. If `wire_services()` regresses in how it builds those attributes, these tests won't catch it directly — coverage on those code paths becomes indirect, via startup/shutdown tests that consume `_init_waves` for real dispatch. This mirrors the existing precedent set by `test_init_order_has_no_cycles` (which already calls `topological_sort()` directly), and the indirect coverage is adequate, but the trade-off should be understood rather than treated as risk-free.

### Tests to Remove

No tests to remove.

## Documentation Updates

- **modify** `src/hassette/core/core.py` — Each new property needs a one-line docstring matching the existing convention (e.g., `"""SessionManager instance for session lifecycle management."""`). The `Hassette` class is in the `PUBLIC_MODULES` allowlist (`tools/docs/gen_ref_pages.py`) and renders via mkdocstrings with no member filter, so all public properties — including the 3 new ones — appear on the auto-generated API reference page. No manual docs-site page edits are needed; the docstrings ARE the documentation.

## Impact

### Changed Files

- **modify** `src/hassette/core/core.py` — add 3 public properties (`session_manager`, `event_stream_service`, `bus`)
- **read** `src/hassette/test_utils/harness.py` — unchanged; referenced for convention examples only
- **modify** `tests/integration/conftest.py` — simplify `hassette_instance` fixture teardown to use `cleanup_streams()`
- **modify** `tests/integration/test_core.py` — migrate private-attr access to public properties, refactor structural tests
- **modify** `tests/integration/test_fatal_shutdown.py` — migrate private-attr access to public properties, annotate state machine accesses
- **modify** `tests/integration/test_resource_deps.py` — refactor `_init_waves` tests to use `topological_levels()` directly

### Behavioral Invariants

- All 34 tests must continue to pass with identical assertions and identical behavior
- `HassetteHarness`-based tests (bus, scheduler, state proxy fixtures) must continue working — the harness delegation update is a passthrough change
- The `cleanup_harness` autouse fixture and `_HARNESS_FIXTURES` set in `tests/integration/conftest.py` are unaffected

### Blast Radius

Contained to the integration test layer and `Hassette` class. No runtime behavior changes. No API contract changes for app authors. The new properties make more of Hassette's surface public, but they follow the existing "raise if not wired" pattern that prevents misuse.

## Open Questions

None.
