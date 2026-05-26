# Context: Decompose bus_service.py

## Problem & Motivation
BusService has grown to 946 lines (project ceiling: 800), mixing five concerns: duration hold lifecycle, dispatch pipeline, event filtering, registration persistence, and idle tracking. This makes PRs touching any single concern require reviewers to understand all five, and unit-testing individual behaviors requires constructing a full BusService with mocked everything. The decomposition extracts three focused modules to enable isolated reasoning and testing.

## Visual Artifacts
None.

## Key Decisions
1. Extract duration hold lifecycle into `src/hassette/bus/duration_hold.py` (~220 lines) as a `DurationHoldManager` class
2. Extract invocation builder into `src/hassette/bus/invocation.py` (~100 lines) as a module-level `build_tracked_invoke_fn` function
3. Extract event filtering into `src/hassette/core/event_filter.py` (~80 lines) as an `EventFilter` class
4. DurationHoldManager receives `executor` and `config_resolver` directly (not a callback indirection) and imports `build_tracked_invoke_fn` from the sibling module
5. Callbacks used only for cross-module operations: `state_reader` (absorbs ResourceNotReadyError), `remove_listener` (verified idempotent)
6. `_should_log_event` stays on BusService — it reads both a `@cached_property` (`config_log_all_events`) and live config fields, depending on BusService's config access patterns
7. Dispatch tracking (`_dispatch_pending`/`_dispatch_idle_event`) stays entirely in BusService — duration timer fires are explicitly excluded from `await_dispatch_idle`
8. `read_current_state` does NOT move — absorbed into the `state_reader` callback

## Constraints & Anti-Patterns
- Do NOT introduce Protocol/ABC for BusService — over-engineering for one consumer
- Do NOT rename any public method or attribute on BusService
- Do NOT call dispatch tracking callbacks from duration timer fires (they're excluded from `await_dispatch_idle` per bus_service.py:767-770)
- Do NOT pass `config_resolver` as a captured value — it MUST be a `Callable[[], float | None]` for hot-reload correctness
- The non-duration dispatch path must remain in BusService (4-line code path, not worth fragmenting)
- EventFilter snapshots config at construction — does not observe changes after init

## Test Rewrites Required
Two existing test files call `BusService._make_tracked_invoke_fn()` directly and must be fully rewritten (not just import-updated) to call `build_tracked_invoke_fn()` with explicit `executor` and `config_resolver` arguments:
- `tests/unit/core/test_bus_service_timeout.py`
- `tests/unit/core/test_bus_service_error_handler.py`

## Design Doc References
- `## Architecture` — detailed module specs, constructor params, method lists
- `## Key Constraints` — prohibited approaches
- `## Convention Examples` — DurationTimer callback injection, RegistrationTracker standalone utility, BusService test fixture
- `## Test Strategy` — existing tests to adapt (rewrites needed for timeout/error_handler tests), new coverage needed
- `## Impact > Behavioral Invariants` — what must not change

## Convention Examples

### Callback injection pattern (DurationTimer)

**Source:** `src/hassette/bus/duration_timer.py:50-75`

```python
def __init__(
    self,
    task_bucket: "TaskBucket",
    duration: float,
    predicates: "Predicate | None",
    entity_id: str,
    owner_id: str,
    create_cancel_sub: "Callable[[], Subscription]",
    on_cancel: "Callable[[], None] | None" = None,
) -> None:
    self.task_bucket = task_bucket
    self.duration = duration
    self.predicates = predicates
    self.entity_id = entity_id
    self.owner_id = owner_id
    self._create_cancel_sub = create_cancel_sub
    self._on_cancel = on_cancel
```

### Standalone utility (RegistrationTracker)

**Source:** `src/hassette/core/registration_tracker.py:1-7`

```python
"""Standalone tracker for pending DB registration tasks.

Encapsulates the prune-and-track, await-with-timeout, and drain patterns
that were previously duplicated in BusService and SchedulerService.

This class has NO dependency on Resource or Service — it is a plain utility.
"""
```

### BusService test fixture (mock construction)

**Source:** `tests/unit/core/test_bus_service_public_accessors.py:27-33`

```python
@pytest.fixture
def bus_service() -> BusService:
    """Construct a BusService backed by mocks, ready for accessor tests."""
    hassette = make_mock_hassette()
    stream = MagicMock()
    executor = MagicMock()
    executor.execute = AsyncMock()
    return BusService(hassette, stream=stream, executor=executor)
```
