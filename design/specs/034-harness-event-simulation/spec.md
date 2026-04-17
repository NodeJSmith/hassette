---
feature_number: "034"
feature_slug: "harness-event-simulation"
status: "approved"
created: "2026-04-17T16:30:00-04:00"
---

# Spec: Complete Event Simulation for AppTestHarness

## Problem Statement

The test harness provides simulation methods for only 3 of the 17 subscription methods (across 13 underlying event topics) that users can subscribe to through the Bus. Even the existing simulation methods produce incomplete event payloads that break when handlers use typed dependency injection annotations (e.g., `D.StateNew[BinarySensorState]`). This forces users to either avoid the framework's recommended DI patterns in their tests or manually construct event objects — defeating the purpose of the test harness.

The result: users cannot reliably test their own automations using the tools the framework provides.

## Goals

1. Every Bus subscription method (`on_*`) has a corresponding simulation method (`simulate_*`) on AppTestHarness that produces events identical in structure to what the real system produces.
2. All simulation methods work with both raw event handlers and typed DI-annotated handlers.
3. Documentation includes representative examples showing how to test automations using the simulation methods.

## User Scenarios

### Automation developer: Testing state-change handlers with typed DI

- **Goal:** Verify that a handler using `D.StateNew[BinarySensorState]` receives a correctly typed state model.
- **Context:** Writing integration tests for a motion-triggered automation.

#### Testing typed state change handler

1. **Registers handler with typed DI annotation**
   - Sees: Handler accepts `new_state: D.StateNew[BinarySensorState]`
   - Then: Bus wires up the handler with the DI conversion pipeline

2. **Simulates a state change via the harness**
   - Sees: `await harness.simulate_state_change("binary_sensor.motion", old_value="off", new_value="on")`
   - Then: Handler receives a fully hydrated `BinarySensorState` with `entity_id`, `domain`, timestamps, and `value=True`

3. **Asserts on the typed state**
   - Sees: `assert received.value is True` and `assert received.entity_id == "binary_sensor.motion"`

### Automation developer: Testing service and lifecycle event handlers

- **Goal:** Verify that handlers for service calls, component loads, and internal events fire correctly.
- **Context:** Writing tests for an automation that reacts to Home Assistant restarts or hassette service failures.

#### Testing hassette service failure handler

1. **Registers handler for service failure**
   - Sees: `self.bus.on_hassette_service_failed(handler=self.on_failure)`
   - Then: Bus wires up the handler

2. **Simulates the failure via the harness**
   - Sees: `await harness.simulate_hassette_service_failed(resource_name="DatabaseService", exception=RuntimeError("disk full"))`
   - Then: Handler receives a `HassetteServiceEvent` with status=FAILED and the exception details

## Functional Requirements

1. **Fix `create_state_change_event` to produce complete state dicts**: Build `old_state`/`new_state` sub-dicts via the existing `make_state_dict` helper rather than inline dicts — this adds the required `entity_id`, `context`, `last_changed`, and `last_updated` fields. `make_full_state_change_event` remains the correct path for callers who already have pre-built `HassStateDict` objects. Acceptance: A handler using `D.StateNew[BinarySensorState]` receives a valid `BinarySensorState` instance when triggered via `simulate_state_change`.

1b. **Fix `create_call_service_event` to produce real `CallServiceEvent` objects**: The current implementation uses `SimpleNamespace` casts which break DI-annotated handlers (`D.Domain`, `D.EntityId`). Replace with proper event construction via `create_event_from_hass` using a call_service event dict. Acceptance: A handler using `D.Domain` receives the correct domain string when triggered via `simulate_call_service`.

2. **Add `simulate_component_loaded` method**: Accepts a `component` name (e.g., `"light"`). Produces a `ComponentLoadedEvent` and drains. Acceptance: A handler registered via `on_component_loaded("light", ...)` fires and a `D.Domain`-annotated handler receives the component name.

3. **Add `simulate_service_registered` method**: Accepts `domain` and `service` (e.g., `"light"`, `"turn_on"`). Produces a `ServiceRegisteredEvent` and drains. Acceptance: A handler registered via `on_service_registered("light", "turn_on", ...)` fires and a `D.Domain`-annotated handler receives `"light"`.

4. **Add `simulate_homeassistant_restart` convenience method**: Delegates to `simulate_call_service("homeassistant", "restart")` — mirrors the delegation pattern of `on_homeassistant_restart` to `on_call_service`. Acceptance: A handler registered via `on_homeassistant_restart(...)` fires.

5. **Add `simulate_homeassistant_start` convenience method**: Delegates to `simulate_call_service("homeassistant", "start")`. Acceptance: A handler registered via `on_homeassistant_start(...)` fires.

6. **Add `simulate_homeassistant_stop` convenience method**: Delegates to `simulate_call_service("homeassistant", "stop")`. Acceptance: A handler registered via `on_homeassistant_stop(...)` fires.

7. **Add `simulate_hassette_service_status` method**: Accepts `resource_name`, `status`, and optional `role` (defaults to `ResourceRole.SERVICE`), `previous_status`, and `exception`. Produces a `HassetteServiceEvent` and drains. Acceptance: A handler registered via `on_hassette_service_status(...)` fires and receives an event with `payload.data.status` and `payload.data.resource_name` matching the provided values.

8. **Add `simulate_hassette_service_failed` convenience method**: Delegates to `simulate_hassette_service_status` with `status=FAILED`. Acceptance: A handler registered via `on_hassette_service_failed(...)` fires and receives an event with `payload.data.status == ResourceStatus.FAILED`.

9. **Add `simulate_hassette_service_crashed` convenience method**: Delegates with `status=CRASHED`. Acceptance: Same pattern — `payload.data.status == ResourceStatus.CRASHED`.

10. **Add `simulate_hassette_service_started` convenience method**: Delegates with `status=RUNNING`. Acceptance: Same pattern — `payload.data.status == ResourceStatus.RUNNING`.

11. **Add `simulate_websocket_connected` method**: No parameters. Produces a `HassetteSimpleEvent` with the websocket-connected topic and drains — matching the production emission path. Acceptance: A handler registered via `on_websocket_connected(...)` fires.

12. **Add `simulate_websocket_disconnected` method**: No parameters. Produces a `HassetteSimpleEvent` with the websocket-disconnected topic and drains — matching the production emission path. Acceptance: A handler registered via `on_websocket_disconnected(...)` fires.

13. **Add `simulate_app_state_changed` method**: Accepts `status` and optional `previous_status`/`exception`. Delegates to `HassetteAppStateEvent.from_data(self._app, ...)` — the harness owns the app instance and fills in `app_key`, `index`, `class_name`, and `instance_name` automatically. Produces a `HassetteAppStateEvent` and drains. Acceptance: A handler registered via `on_app_state_changed(...)` fires and receives an event with `payload.data.app_key` matching the harness app's key.

14. **Add `simulate_app_running` convenience method**: Delegates to `simulate_app_state_changed` with `status=RUNNING`. Acceptance: Same pattern.

15. **Add `simulate_app_stopping` convenience method**: Delegates with `status=STOPPING`. Acceptance: Same pattern.

16. **Each simulation method has integration tests**: Tests cover both raw event handlers and, where applicable, typed DI handlers. This includes the pre-existing `simulate_attribute_change` method, which inherits the DI fix from FR1 but must have its own DI test to confirm the delegation path works. Methods requiring explicit typed-DI tests: `simulate_state_change`, `simulate_attribute_change`, `simulate_call_service`, `simulate_hassette_service_status`, and `simulate_app_state_changed`. Acceptance: Test file includes at least one test per simulation method, with DI-annotated handler tests for the methods listed above.

17. **Documentation updated with representative examples**: Testing docs include examples for the most commonly used simulate methods (state change with typed DI, service call, hassette service events). Not exhaustive — avoids repeating the same pattern for every method. Acceptance: Docs build cleanly and include at least 3 distinct simulate examples.

## Edge Cases

1. **`old_value=None` for first-time state set**: `simulate_state_change` with `old_value=None` should produce a `None` old_state in the event, and `D.MaybeStateOld` should return `None`. `D.StateOld` should raise.
2. **`new_value=None` for state removal**: When `new_value=None`, the `new_state` sub-dict in the event payload is `None` (not `{"state": None, ...}`), representing entity removal. `D.MaybeStateNew[BinarySensorState]` returns `None`; `D.StateNew[BinarySensorState]` raises `DependencyResolutionError`.
3. **Convenience methods share the same drain/timeout contract**: `simulate_homeassistant_restart` must drain handlers and surface `DrainError`/`DrainTimeout` the same way as `simulate_state_change`.
4. **Existing tests remain unbroken**: The state dict fix adds fields to events that existing raw-handler tests receive. These extra fields must be harmless — no existing test should assert on the absence of `entity_id` in sub-state dicts.
5. **Non-string state values**: `simulate_state_change` accepts `Any` for values. The updated path must handle non-string values (booleans, ints) without crashing — same contract as today.

## Dependencies and Assumptions

- The DI annotation conversion pipeline (`AnnotationConverter`, `ParameterInjector`) is already fully implemented and tested in isolation. This work only needs to ensure the harness produces events that pass through it successfully.
- Event model classes (`HassetteServiceEvent`, `HassetteAppStateEvent`, `HassetteSimpleEvent`) already have `from_data` or `create_event` factory methods that can be reused by the new simulation methods.
- The existing `_drain_task_bucket` pattern on AppTestHarness applies uniformly to all new simulate methods.
- All simulate methods — new and existing — do not update harness state after firing. Post-event state queries read what was last seeded via `_test_seed_state`.
- Fixing `create_state_change_event` and `create_call_service_event` changes the public shape of their returned events. The `HassStateDict` TypedDict has always declared these fields as `Required`; the prior incomplete shape was a bug, not a feature. Note as a breaking change in the changelog. Downstream user code asserting on the prior incomplete event structure will need to be updated.

## Acceptance Criteria

1. A handler using `D.StateNew[BinarySensorState]` receives a valid typed model when triggered via `simulate_state_change` — the original bug reported in issue #510.
2. Every `on_*` Bus subscription method has a corresponding `simulate_*` method on AppTestHarness.
3. All new simulate methods drain handlers and surface errors via `DrainError`/`DrainTimeout`.
4. All existing tests continue to pass unchanged.
5. The full test suite (`uv run nox -s dev`) passes with the new tests included.
6. Testing documentation includes representative examples of typed DI testing.
7. A structural regression test enumerates all `Bus.on_*` methods and asserts a corresponding `simulate_*` method exists on `AppTestHarness` — preventing the coverage drift that caused issue #510 from recurring.

## Open Questions

_None — all questions resolved during specification._
