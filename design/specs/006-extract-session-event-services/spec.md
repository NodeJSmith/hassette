---
feature_number: "006"
feature_slug: "extract-session-event-services"
status: "approved"
created: "2026-03-16T16:51:59Z"
---

# Spec: Extract SessionManager and EventStreamService from Hassette Core

## Problem Statement

The Hassette coordinator class currently owns responsibilities well beyond its role as a top-level orchestrator: it directly manages database session lifecycle (creating, finalising, crash-recording, and orphan-cleaning sessions) and owns the internal event stream infrastructure (memory channel creation, event dispatch, and stream teardown). This concentration of unrelated concerns makes Hassette hard to test in isolation, hides the true ownership of each subsystem, and means that changes to session or stream behaviour require navigating a large, mixed-purpose class. Two GitHub issues (#326, #327) and ADR-0002 identify these as phases 1 and 2 of a planned decomposition.

## Goals

- Session lifecycle is owned by a dedicated, independently testable service; Hassette delegates to it.
- Event stream infrastructure is owned by a dedicated service; all producers and consumers receive it via explicit dependency rather than accessing it through the top-level coordinator.
- The event stream buffer size is configurable rather than hardcoded, closing issue #321.
- Hassette is measurably smaller and has fewer direct responsibilities after the change.
- All existing behaviour is preserved — no user-visible changes.

## Non-Goals

- Refactoring AppHandler (ADR-0002 phase 3, tracked separately as #328).
- Extracting SessionManager or EventStreamService further into sub-components.
- Changes to the session data model or schema.
- Any new user-facing features or API additions beyond configurable buffer size.
- Performance improvements beyond what configurable buffer size enables.

## User Scenarios

**Scenario 1 — Hassette starts normally**
A developer runs their automation. Hassette initialises SessionManager as a child service; SessionManager creates a session row and marks any orphaned sessions from prior runs. EventStreamService initialises the memory channel with the configured buffer size. All producer services receive EventStreamService at construction and send events through it. Behaviour is identical to before.

**Scenario 2 — A service crashes mid-run**
One of the child services crashes. SessionManager receives the crash event and records failure details to the session row. Hassette does not need to know how session crash recording works — it delegates entirely to SessionManager.

**Scenario 3 — DatabaseService restarts transiently**
A transient DatabaseService restart occurs. Because session ownership has moved to Hassette (via SessionManager), no new session row is created — the session represents the Hassette process lifetime, not the DatabaseService lifetime.

**Scenario 4 — Developer writes an integration test for session behaviour**
A developer creates a test for session crash recording. They instantiate SessionManager directly with a test DatabaseService, fire a crash event, and assert on the session row — without needing a full Hassette instance.

**Scenario 5 — Developer configures a larger event buffer**
A developer sets `hassette_event_buffer_size = 5000` in their configuration. EventStreamService reads this value at startup and creates the memory channel with the specified capacity.

## Functional Requirements

1. A `SessionManager` service exists as a child of Hassette and is responsible for: creating the session row on startup, marking orphaned sessions, recording crash details when a service fails, and finalising the session on shutdown.
2. `Hassette.session_id` is a delegating property — it returns the session ID from `SessionManager`, not a value stored directly on `Hassette`.
3. `Hassette` is reduced in size by the session methods extracted to `SessionManager` (approximately 235 lines).
4. `SessionManager` depends on `DatabaseService` for all database access; it does not manage its own connection.
5. An `EventStreamService` service exists as a child of Hassette and owns: memory channel creation, the `send_event()` method, the `event_streams_closed` property, and stream teardown on shutdown.
6. The memory channel buffer size used by `EventStreamService` is read from the Hassette configuration field `hassette_event_buffer_size`, replacing the current hardcoded value. If unset, a default of 1000 is used.
7. `BusService` receives `EventStreamService` (or its receive-stream interface) via constructor injection rather than cloning from Hassette directly.
8. All five producer services (`AppHandler`, `WebsocketService`, `FileWatcherService`, `ServiceWatcher`, `AppLifecycleManager`) receive `EventStreamService` via constructor injection and call `send_event()` on it rather than on `Hassette`.
9. `Hassette.send_event()` is preserved as a delegating method for any callers that reference it through the coordinator.
10. `HassetteHarness` is updated to reflect the new service graph — both new services are available as optional components in test harness construction.
11. A test fixture `create_session_manager(db_service)` exists for integration tests.
12. A test fixture `create_event_stream_service(buffer_size)` exists for integration tests.
13. Session lifecycle tests are co-located with `SessionManager` rather than mixed into general Hassette lifecycle tests.
14. All existing tests pass without modification to their intent (test infrastructure updates are expected, but no tests are deleted or have assertions weakened).

## Edge Cases

- **Concurrent crash + shutdown**: `SessionManager` must coordinate crash recording and session finalisation safely when both occur close together (the existing lock mechanism is preserved or equivalent).
- **Session ID accessed before initialisation**: If `Hassette.session_id` is called before `SessionManager` has created a session, the existing `RuntimeError` behaviour is preserved.
- **Producers calling send_event before EventStreamService is ready**: Ordering guarantees of the Resource initialisation hierarchy are relied upon; no new handling is introduced.
- **Buffer exhaustion**: A fully exhausted event buffer results in backpressure to the caller, consistent with current anyio memory channel semantics.
- **Zero or missing buffer size config**: If `hassette_event_buffer_size` is not set, the default of 1000 is used silently.

## Dependencies and Assumptions

- ADR-0002 defines the decomposition strategy; this spec implements phases 1 and 2 only.
- The existing `Resource` base class provides lifecycle hooks and child service registration — both new services use this pattern.
- `DatabaseService` is assumed to be available as a sibling service when `SessionManager` initialises (existing service ordering is preserved).
- Issue #321 (`hassette_event_buffer_size` configuration field) is being incorporated into this feature rather than implemented separately.
- The anyio memory channel API is stable for the project's supported dependency range.

## Acceptance Criteria

- `src/hassette/core/session_manager.py` exists and contains all session lifecycle logic.
- `src/hassette/core/event_stream_service.py` exists and owns all stream and dispatch logic.
- `core.py` no longer contains session CRUD methods or stream management logic directly.
- `Hassette.session_id` and `Hassette.send_event()` are delegating properties/methods.
- `EventStreamService` reads buffer size from configuration; the value `1000` does not appear hardcoded in stream creation.
- All 5 producer services receive `EventStreamService` via constructor, not via `self.hassette`.
- `BusService` receives its stream via constructor, not by cloning from `Hassette`.
- `tests/integration/test_session_manager.py` exists with session lifecycle coverage.
- `tests/integration/test_event_stream_service.py` exists with stream and dispatch coverage.
- `HassetteHarness` can be constructed with or without the new services for test flexibility.
- Full test suite passes (`uv run pytest -n auto`).
- Type checking passes (`uv run pyright`).
