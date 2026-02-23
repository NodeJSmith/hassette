# Integration Test Design Audit

**Date:** 2026-02-23
**Scope:** Multi-component integration test infrastructure, triggered by difficulty writing ServiceWatcher shutdown tests
**Branch:** fix-broken-state-shutdown

## Context

Writing the test for "ServiceWatcher shuts down Hassette when max restart attempts exceeded" took several minutes of iteration to get working. This audit investigates whether the difficulty stems from service design, test infrastructure, or both.

## Finding 1: No Event Injection Utility for Service-Level Tests (Critical)

**Impact:** Every integration test involving event-driven service behavior must choose between two extremes — neither is ideal.

### The Two Strategies Today

| Strategy | Pros | Cons |
|----------|------|------|
| Direct method call (`restart_service()`) | Fast, focused, no bus wiring | Bypasses event routing; doesn't test real flow |
| Full bus cascade (fire event, wait for processing) | Tests real event flow end-to-end | Requires 7+ infrastructure concerns per test |

### What's Missing: The Middle Layer

Hot-reload tests have purpose-built injection helpers:
- `emit_file_change_event()` — injects a synthetic event into the bus
- `wire_up_app_running_listener()` — sets up an event listener to observe outcomes

ServiceWatcher tests have no equivalent. The bus-driven test (`test_service_watcher.py:299-346`) must manually:

1. Use module-scoped `hassette_with_bus` fixture
2. Create `ServiceWatcher.create()` with manual wiring
3. Inject a dummy service into `hassette.children`
4. Stub `hassette.shutdown()` to prevent coroutine cancellation
5. Call `on_initialize()` + `get_listeners()` to synchronize bus wiring
6. Use `wait_for()` polling for async cascade completion
7. Set zero backoff config (patching `asyncio.sleep` globally would starve the event loop)

That's 7 infrastructure concerns for a test asserting one thing: "after N failures, shut down."

### Suggested Remedy

Add to `src/hassette/test_utils/helpers.py`:

```python
async def emit_service_event(hassette, event: HassetteServiceEvent) -> None:
    """Inject a service event into the bus as if it were real."""
    await hassette.send_event(event.topic, event)

async def wait_for_shutdown(hassette, *, timeout: float = 3.0) -> None:
    """Wait for hassette.shutdown_event to be set."""
    await wait_for(lambda: hassette.shutdown_event.is_set(), timeout=timeout,
                   desc="hassette shutdown triggered")
```

More importantly, a dedicated fixture or utility that:
- Creates a ServiceWatcher wired to the bus
- Handles initialization synchronization
- Stubs `hassette.shutdown()` automatically
- Provides a `wait_for_shutdown()` assertion helper

---

## Finding 2: Module-Scoped Fixture Reset Is Manual and Fragile (Concerning)

**Impact:** Tests that touch shutdown state must manually reset 4 properties. Missing any one causes "works alone, fails in suite" bugs.

### Current State

`reset.py` provides standardized reset functions for:
- `reset_state_proxy()` — clears state cache, re-initializes listeners
- `reset_bus()` — removes all listeners
- `reset_scheduler()` — removes all jobs
- `reset_mock_api()` — clears server expectations

Missing: **`reset_hassette_lifecycle()`** — no standardized way to reset shutdown state.

### Manual Reset in ServiceWatcher Tests

```python
# test_service_watcher.py:22-26 — manual cleanup
hassette_with_bus.children[:] = original_children
hassette_with_bus.shutdown_event = asyncio.Event()
hassette_with_bus._shutting_down = False
hassette_with_bus.ready_event.set()
```

4 other test files also manually reset shutdown state. This is duplicated logic that should be in `reset.py`.

### Suggested Remedy

Add to `src/hassette/test_utils/reset.py`:

```python
async def reset_hassette_lifecycle(hassette: "Hassette", *, original_children: list | None = None) -> None:
    """Reset Hassette lifecycle state for module-scoped fixture reuse."""
    hassette.shutdown_event = asyncio.Event()
    hassette._shutting_down = False
    hassette.ready_event.set()
    if original_children is not None:
        hassette.children[:] = original_children
```

Optionally, add an autouse cleanup fixture in `tests/integration/conftest.py` alongside the existing bus/scheduler/state_proxy cleanups.

---

## Finding 3: Test Utility Churn Signals Ongoing Friction (Concerning)

**Impact:** Developers writing tests hit infrastructure gaps and must patch the infra, creating a moving target.

### Evidence

Last 3 months of git churn:
- `harness.py` — **22 changes** (most-churned non-config source file)
- `fixtures.py` — **17 changes**
- `tests/conftest.py` — **26 changes**

For comparison, the actual service code (`service_watcher.py`, `bus_service.py`, etc.) changed far less frequently.

### Interpretation

The test infrastructure is stabilizing but hasn't plateaued. Each new integration test scenario (like the ServiceWatcher shutdown cascade) reveals gaps that require infrastructure patches. This is normal for a maturing framework, but it means:
- Writing new integration tests often involves modifying test utils first
- Tests written against the current infra may need updates as the infra evolves

### Suggested Remedy

No immediate action needed — the churn is trending downward. But each new gap (like the event injection utility) should be addressed generically rather than with per-test workarounds.

---

## Finding 4: Service Layer Design Is Sound (Positive)

**Impact:** The test difficulty does **not** stem from poor service coupling.

### Evidence

- Services communicate through the event bus (loose coupling)
- `wait_for_ready()` provides clean dependency coordination
- Resource lifecycle hooks (`on_initialize`, `on_shutdown`) are consistent
- No circular dependencies between services
- ServiceWatcher observes via bus subscription, doesn't directly call other services

### Minor Observation

Services reference Hassette's private attributes in `wait_for_ready()`:
```python
await self.hassette.wait_for_ready([
    self.hassette._websocket_service,  # private attribute
    self.hassette._api_service,        # private attribute
])
```

This is a naming/encapsulation issue, not a design issue. The dependency direction is correct — it just leaks implementation details through attribute names. Not worth changing unless doing a broader refactor.

---

## Summary

| Finding | Severity | Action |
|---------|----------|--------|
| No event injection utility for service tests | Critical | Create issue |
| Missing `reset_hassette_lifecycle()` | Concerning | Create issue |
| Test util churn (stabilizing) | Concerning | Monitor |
| Service design is sound | Positive | None |

The root cause of the ServiceWatcher test difficulty is a **missing middle layer in the test infrastructure**, not service coupling or test configuration. The hot-reload tests already demonstrate the pattern (synthetic event injection + outcome observation) — it just hasn't been generalized.
