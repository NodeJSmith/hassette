# Design: Complete Event Simulation for AppTestHarness

**Date:** 2026-04-17
**Status:** approved
**Spec:** design/specs/034-harness-event-simulation/spec.md
**Research:** /tmp/claude-mine-design-research-KFepfV/brief.md

## Problem

The `AppTestHarness` provides simulation methods for only 3 of 17 bus subscription methods. The existing methods produce incomplete event payloads that break typed DI-annotated handlers (`D.StateNew[BinarySensorState]`, `D.Domain`, etc.), forcing users to avoid the framework's recommended patterns or construct events manually. All required building blocks already exist in the codebase — this is a wiring and coverage problem, not an infrastructure gap.

## Architecture

### File decomposition

`app_harness.py` is 1082 lines and will grow to ~1400+ with 14 new simulate methods. The file has clear responsibility clusters that should be extracted into focused modules before adding new code:

| Module | Responsibility | Approximate lines |
|--------|---------------|-------------------|
| `app_harness.py` | Setup/teardown, `__aenter__`/`__aexit__`, config validation, property accessors, state seeding | ~450 |
| `simulation.py` | All `simulate_*` methods + `_drain_task_bucket` | ~500 (after new methods) |
| `time_control.py` | `freeze_time`, `advance_time`, `trigger_due_jobs`, `_FrozenClock` | ~200 |

`AppTestHarness` inherits from `SimulationMixin` and `TimeControlMixin` (both defined in the new modules), keeping the public API surface identical.

A `_SimulationHost` Protocol (defined in `simulation.py` under `TYPE_CHECKING`) declares the attributes both mixins depend on: `_harness`, `_app`, `bus`, and `_drain_task_bucket`. `AppTestHarness` satisfies this Protocol at the class declaration site — Pyright enforces the contract statically. The existing inline guard pattern (`if harness is None: raise RuntimeError(...)`, repeated at 5+ call sites) is extracted into a shared `_require_harness()` method on the Protocol, eliminating duplication.

This decomposition keeps every file under 600 lines and makes each concern independently navigable.

### Fix existing event factories

**`create_state_change_event` (helpers.py:25-48)**: Replace inline sub-dicts with `make_state_dict` calls. Handle `None` values for entity creation/removal by producing `None` (not a dict with `None` fields):

```python
"old_state": make_state_dict(entity_id, str(old_value), attributes=old_attrs) if old_value is not None else None,
"new_state": make_state_dict(entity_id, str(new_value), attributes=new_attrs) if new_value is not None else None,
```

`make_state_dict` (helpers.py:63-92) already produces dicts with `entity_id`, `state`, `attributes`, `last_changed`, `last_updated`, and `context`. No changes to `make_state_dict` are needed.

**`create_call_service_event` (helpers.py:51-60)**: Replace the `SimpleNamespace` cast with proper event construction via `create_event_from_hass`. Build a `HassEventEnvelopeDict` with `event_type: "call_service"` containing `{"domain": domain, "service": service, "service_data": service_data or {}}` as the data dict. Return a real `CallServiceEvent`.

This is a **breaking change** with three specific impacts beyond the return type:
1. **`event.topic` type change**: From plain string `"hass.event.call_service"` to `Topic.HASS_EVENT_CALL_SERVICE` (a `str` enum — `Topic` inherits `str`, so `==` comparisons still work, but `is` checks and `type()` checks change).
2. **`isinstance` behavior flip**: `isinstance(event, CallServiceEvent)` changes from `False` (SimpleNamespace) to `True`. Grep for `isinstance(.*CallServiceEvent)` in the test suite before implementing.
3. **New attributes appear**: `event.payload.context`, `event.payload.time_fired`, `event.payload.origin` now exist where they previously raised `AttributeError`. Code using `hasattr` guards changes behavior.

The attribute data paths (`event.payload.data.domain`, `event.payload.data.service`) remain identical.

### New simulate methods

All new methods follow the established pattern:

```python
async def simulate_xxx(self: _SimulationHost, ..., timeout: float = 2.0) -> None:
    harness = self._require_harness()  # extracted shared guard; raises RuntimeError if not active
    event = <construct via factory>
    await harness.hassette.send_event(event.topic, event)
    await self._drain_task_bucket(timeout=timeout)
```

Three event construction patterns are used, matching production:

**Pattern 1 — HA events via `create_event_from_hass()`** (component_loaded, service_registered):
Build a `HassEventEnvelopeDict` with the appropriate `event_type` and data fields. Pass through `create_event_from_hass()` to produce the typed event. This is the same path used by `simulate_state_change` and the fixed `simulate_call_service`.

**Pattern 2 — Hassette events via `from_data()` factories** (service_status, app_state_changed):
- `simulate_hassette_service_status`: calls `HassetteServiceEvent.from_data(resource_name, role, status, ...)`. Role defaults to `ResourceRole.SERVICE`.
- `simulate_app_state_changed`: calls `HassetteAppStateEvent.from_data(self._app, status, ...)`. The harness owns the app instance — callers provide only `status`, `previous_status`, and `exception`. **Limitation**: this always emits an event for the harness's own app. To simulate a foreign app's state change (for cross-app coordination tests), users must construct `HassetteAppStateEvent` manually and call `harness._harness.hassette.send_event(...)` directly.

**Pattern 3 — Simple events via `create_event()`** (websocket connected/disconnected):
Calls `HassetteSimpleEvent.create_event(topic=Topic.HASSETTE_EVENT_WEBSOCKET_CONNECTED)`. No parameters — matches the production emission path in `websocket_service.py:431-437`.

**Convenience delegations** (7 methods):
Mirror the Bus delegation pattern exactly. All convenience wrappers must explicitly thread `timeout=timeout` to their delegate call:
- `simulate_homeassistant_restart/start/stop` → `simulate_call_service("homeassistant", "restart/start/stop", timeout=timeout)`
- `simulate_hassette_service_failed/crashed/started` → `simulate_hassette_service_status(status=FAILED/CRASHED/RUNNING, ..., timeout=timeout)`
- `simulate_app_running/stopping` → `simulate_app_state_changed(status=RUNNING/STOPPING, timeout=timeout)`

### Helper factory for HA events

A private `_create_hass_event` helper in `helpers.py` can reduce boilerplate across `create_state_change_event`, the fixed `create_call_service_event`, and the new `create_component_loaded_event` / `create_service_registered_event` factories. It builds the common envelope structure (`id`, `type`, `event.origin`, `event.time_fired`, `event.context`) and delegates to `create_event_from_hass`:

```python
def _create_hass_event(event_type: str, data: dict[str, Any]) -> Any:
    envelope: HassEventEnvelopeDict = {
        "id": 1,  # Discarded by create_event_from_hass; present only to satisfy HassEventEnvelopeDict shape
        "type": "event",
        "event": {
            "event_type": event_type,
            "data": data,
            "origin": "LOCAL",
            "time_fired": ZonedDateTime.now_in_system_tz().format_iso(),
            "context": {"id": str(uuid4()), "parent_id": None, "user_id": None},
        },
    }
    return create_event_from_hass(envelope)
```

This eliminates ~15 lines of boilerplate per HA event factory.

Each factory that calls `_create_hass_event` must assert the return type immediately (following the `make_full_state_change_event` precedent at helpers.py:207):
```python
event = _create_hass_event("component_loaded", {"component": component})
assert isinstance(event, ComponentLoadedEvent)
return event
```

New factory functions are **Tier 2 (private)**: named `_create_component_loaded_event` and `_create_service_registered_event` with leading underscores. Users interact via `simulate_*` methods, not factories directly.

Lifecycle simulate methods (`simulate_websocket_connected/disconnected`, `simulate_hassette_service_status`, `simulate_app_state_changed`) should include a `Note:` in their docstring referencing the `_drain_task_bucket` limitation — it only drains `app.task_bucket`, not `bus.task_bucket`. These methods are most likely to have bus-level subscribers (e.g., `wire_up_app_state_listener`).

### Structural drift regression test

A test that introspects `Bus` and `AppTestHarness` to assert 1:1 `on_*` / `simulate_*` coverage:

```python
def test_all_bus_subscriptions_have_simulate_counterparts():
    resource_methods = {name for name in Resource.__dict__ if name.startswith("on_")}
    bus_methods = {name.removeprefix("on_") for name in Bus.__dict__ if name.startswith("on_") and name not in resource_methods}
    harness_methods = {name.removeprefix("simulate_") for name in dir(AppTestHarness) if name.startswith("simulate_")}
    missing = bus_methods - harness_methods
    assert not missing, f"Bus subscription methods without simulate counterparts: {missing}"
```

Placed in `tests/unit/test_harness_coverage.py` (not integration — no async setup needed).

### Test strategy

**DI-annotated handler tests** (5 methods per spec FR16): `simulate_state_change`, `simulate_attribute_change`, `simulate_call_service`, `simulate_hassette_service_status`, `simulate_app_state_changed`. Each test creates a harness app with a typed DI handler and asserts the handler receives the correct typed model/value.

**Raw handler tests** (all methods): Each simulate method gets at least one test verifying the handler fires and receives the event.

**Edge case tests**: `old_value=None`, `new_value=None`, non-string state values.

All integration tests go in `tests/integration/test_app_test_harness.py`. The structural drift test goes in `tests/unit/test_harness_coverage.py`.

## Alternatives Considered

### Keep everything in `app_harness.py` without decomposition

The simplest approach — just add 14 methods to the existing file. Rejected because the file is already over the 800-line convention and would grow to ~1400 lines. The responsibility clusters are clear and independently testable, making decomposition low-risk and high-value.

### Generic `simulate(topic, event)` method instead of per-type methods

A single generic method that accepts any event and topic. This provides ultimate flexibility but loses discoverability and type safety — users would need to construct events manually, defeating the purpose of the harness. Rejected in favor of typed convenience methods that mirror the Bus subscription API.

### Add URL/error parameters to websocket simulate methods

Would provide richer simulation capability but mismatches production — `websocket_service.py` emits `HassetteSimpleEvent` with empty payloads. The `WebsocketConnectedEventPayload` and `WebsocketDisconnectedEventPayload` classes exist but are dead code. Rejected per spec challenge finding F1 (4/4 critic agreement).

## Test Strategy

**Unit tests**: Structural drift regression test (new file `tests/unit/test_harness_coverage.py`).

**Integration tests**: All simulate method tests in `tests/integration/test_app_test_harness.py`:
- 17 raw handler tests (one per simulate method, including existing methods)
- 5 DI-annotated handler tests (per FR16)
- 3 edge case tests (None old/new values, non-string values)

No E2E tests needed — this is test infrastructure, not user-facing UI.

## Open Questions

_None — all questions resolved during specification and research._

## Impact

### Files modified

| File | Change |
|------|--------|
| `src/hassette/test_utils/helpers.py` | Fix `create_state_change_event`, fix `create_call_service_event`, add `_create_hass_event` helper, add `_create_component_loaded_event`, `_create_service_registered_event` factories (Tier 2 private) |
| `src/hassette/test_utils/app_harness.py` | Extract simulation and time control methods to mixins; keep setup/teardown/accessors/state-seeding |
| `src/hassette/test_utils/simulation.py` | **New** — `SimulationMixin` with all `simulate_*` methods + `_drain_task_bucket` |
| `src/hassette/test_utils/time_control.py` | **New** — `TimeControlMixin` with `freeze_time`, `advance_time`, `trigger_due_jobs`, `_FrozenClock` |
| `tests/integration/test_app_test_harness.py` | ~25 new tests |
| `tests/unit/test_harness_coverage.py` | **New** — structural drift regression test |
| `docs/pages/testing/index.md` | Representative examples of typed DI testing |

### Blast radius

- **Public API**: `create_state_change_event` and `create_call_service_event` return types change (breaking, acknowledged in spec)
- **Internal**: `AppTestHarness` gains 14 new public methods (7 base + 7 convenience delegations); existing 3 simulate methods unchanged in behavior
- **No impact on**: Bus, Scheduler, Api, StateManager, or any production code paths
