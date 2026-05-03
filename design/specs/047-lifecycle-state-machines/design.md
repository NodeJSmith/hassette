# Design: Lifecycle State Machines and Startup Validation

**Date:** 2026-05-03
**Status:** approved
**Issues:** #675, #668, #666
<!-- Gap check 2026-05-03: 4 gaps included — app_lifecycle_service.py:158,168 direct status assignment → WP02 subtask 5, core.py:586 direct status assignment → WP02 subtask 5, harness.py:710 test utility bypass → WP02 subtask 5, web_mocks.py:102 test utility bypass → WP02 subtask 5 -->
**Research:** design/research/2026-05-01-app-loading-reloading/research.md, design/research/2026-05-01-websocket-client-mgmt/research.md, design/research/2026-05-01-type-state-registries/research.md

## Problem

Three subsystems rely on implicit state — boolean flags, null-checks, and idempotency guards — instead of formal state machines:

1. **Resource/App lifecycle** (`resources/base.py`, `mixins.py`): The lifecycle has ~8 statuses (`ResourceStatus` enum) but no enforcement of valid transitions. `handle_running()` can be called from any state. Invalid transitions (e.g., `STOPPED → RUNNING` without going through `STARTING`) are silently accepted because each `handle_*` method only checks "am I already in this state?" not "is this transition valid from my current state?" Debugging lifecycle bugs requires reconstructing the transition history from logs.

2. **WebSocket connection** (`websocket_service.py`): Connection state is derived from `self._ws is not None and not self._ws.closed` (the `connected` property), `is_ready()`, and `_connected_at`. There's no formal distinction between DISCONNECTED, CONNECTING, CONNECTED, and RECONNECTING — these states exist implicitly across multiple flags. The monitoring UI can't show "reconnecting" because no single observable represents that state.

3. **Type/State registries** (`conversion/`): Registration happens at import time via `__init_subclass__` and module-level `register_*` calls. Invalid entries (converters with wrong signatures, state models with missing domain annotations) only fail at first use. Missing imports mean missing registrations with no error.

## Goals

- Invalid lifecycle transitions raise or log at the point of violation, not downstream
- WebSocket connection state is a single observable enum, suitable for API/UI exposure
- Registry entries are validated at startup; configuration errors surface before the first event is processed
- All changes are additive — existing behavior is preserved when transitions follow the current happy path

## Functional Requirements

### Lifecycle Transition Guards (#675)

1. Every `ResourceStatus` transition through the `status` setter SHALL be validated against a static transition table
2. In strict mode (`strict_lifecycle = True`), an invalid transition SHALL raise `InvalidLifecycleTransitionError` with the attempted transition pair and the resource's `unique_name`
3. In non-strict mode, an invalid transition SHALL log a warning at WARNING level with the attempted transition pair, `unique_name`, and a 1-2 frame stack trace
4. Every valid transition SHALL be logged at DEBUG level as `"{unique_name}: {old} → {new}"`
5. `_force_terminal()` SHALL bypass transition validation entirely via direct attribute assignment (`self._status = ...`)
6. The transition table SHALL be a module-level constant, not computed at runtime

### WebSocket Connection State Machine (#668)

7. `WebsocketService` SHALL expose a `connection_state` read-only property returning a `ConnectionState` enum value
8. `ConnectionState` transitions SHALL be validated against a static transition table with the same strict/non-strict behavior as lifecycle guards
9. The existing `connected` property SHALL return `True` if and only if `connection_state == ConnectionState.CONNECTED`
10. Connection state SHALL transition to CONNECTING before any WebSocket handshake attempt, to CONNECTED after successful authentication and subscription, and to DISCONNECTED on non-retryable failure, max retries exhausted, or clean shutdown
11. `_partial_cleanup()` SHALL NOT change connection state — it is resource cleanup, not a state transition

### Resource Lifecycle Fixes

20. `Resource.shutdown()` and `Service.shutdown()` SHALL set `self.status = ResourceStatus.STOPPING` at entry, after re-entry guards, before hooks run
21. `ServiceWatcher` SHALL set the service instance's `.status` to `EXHAUSTED_COOLING` or `EXHAUSTED_DEAD` when transitioning to those states, not just emit events with those statuses in the payload
22. `_force_terminal()` SHALL use direct attribute assignment (`self._status = ...`) instead of the property setter to bypass transition validation

### Startup Registry Validation (#666)

11. `validate_registries()` SHALL run during `Hassette.wire_services()` after all service children are added
12. An empty STATE_REGISTRY (zero entries) SHALL be reported as a validation error — the framework ships ~35 built-in state models; zero entries means the models package was not imported
13. An empty TYPE_REGISTRY (zero entries) SHALL be reported as a validation error — the module registers ~20 converters at import time; zero entries means the conversion module did not load
14. In strict mode, any validation issue SHALL raise `RegistryValidationError` with a summary of all issues found (not fail-fast on the first issue)
15. In non-strict mode, validation issues SHALL be logged as warnings with a single summary line at the end
16. `validate_registries()` SHALL return a list of `RegistryValidationIssue` dataclasses regardless of mode, for testability

### Strict Lifecycle Toggle

17. `HassetteConfig` SHALL accept a `strict_lifecycle: bool` field (default `False`)
18. `HassetteHarness` SHALL set `strict_lifecycle = True` by default
19. The toggle SHALL control behavior for all three subsystems uniformly

## Non-Goals

- Changing the Resource/Service initialization or shutdown flow
- Adding new lifecycle states beyond what `ResourceStatus` already defines
- Adding connection state to the REST API or frontend (future work using the new enum)
- Validating registry entries against a live HA instance (#679 tracks that separately)

## Architecture

### Strict Lifecycle Mode

All three subsystems share a `strict_lifecycle` toggle on `HassetteConfig` (default `False`):

- **`strict_lifecycle = False`** (production default): Invalid transitions and validation failures log warnings. The system continues operating. Useful for discovering violations without risking breakage.
- **`strict_lifecycle = True`** (test harness default): Invalid transitions raise `InvalidLifecycleTransitionError`. Validation failures raise `RegistryValidationError`. Every violation is a test failure, making it easy to find and fix latent issues.

The test harness (`HassetteHarness`) sets `strict_lifecycle = True` by default so all tests enforce valid transitions. Production gets warn-by-default with the option to flip the flag in `hassette.toml` for debugging.

`_force_terminal()` bypasses the setter (direct `self._status = ...` assignment) and is exempt from strict mode — it's an emergency teardown path that intentionally transitions from any state.

### 1. Resource Lifecycle Transition Guards (#675)

Add a transition table to `LifecycleMixin` that defines valid `(from_status, to_status)` pairs. The `status` setter validates against this table.

```
Valid transitions:
  NOT_STARTED       → STARTING
  STARTING          → RUNNING, FAILED, STOPPED
  RUNNING           → STOPPING, FAILED, CRASHED
  STOPPING          → STOPPED, FAILED
  STOPPED           → STARTING  (restart)
  FAILED            → STARTING (restart), STOPPED (shutdown after failure), EXHAUSTED_COOLING (budget exhausted, transient), EXHAUSTED_DEAD (budget exhausted, temporary)
  CRASHED           → STARTING (restart), STOPPED (shutdown after crash), EXHAUSTED_DEAD (fatal, permanent)
  EXHAUSTED_COOLING → STARTING (restart after cooldown), EXHAUSTED_DEAD (cooldown cycles exceeded)
  EXHAUSTED_DEAD    → (terminal, no transitions out)
```

Implementation:
- Define `VALID_TRANSITIONS: dict[ResourceStatus, frozenset[ResourceStatus]]` as a module-level constant in `mixins.py`
- The `status` setter in `LifecycleMixin` checks the transition table. In strict mode, invalid transitions raise `InvalidLifecycleTransitionError`. In non-strict mode, they log a warning with the attempted transition and a compact stack trace (1-2 frames).
- Log each valid transition at DEBUG level: `"%s: %s → %s"` with `unique_name`, old status, new status
- Expose `status` as a read-only property on `Resource` (it's already a property on `LifecycleMixin`). No new public API needed.
- `_force_terminal()` bypasses the setter via direct `self._status = ResourceStatus.STOPPED` assignment — this is intentional and documented. The current code uses `self.status = ...` (the property setter) and must be changed to `self._status = ...` to bypass validation.

#### Fix: Add STOPPING to the shutdown path

Currently `shutdown()` transitions directly from RUNNING to STOPPED — the STOPPING status exists in the enum but is never assigned. The bus already filters on STOPPING, and `AppLifecycleService` emits events with it. The fix:

- `Resource.shutdown()` sets `self.status = ResourceStatus.STOPPING` at entry, before hooks run (after the re-entry guards). This replaces the role of the `_shutting_down` boolean for external observers — code can now check `status == STOPPING` instead of relying on a private flag.
- `Service.shutdown()` gets the same treatment.
- The `_shutting_down` flag is retained for internal re-entry guarding (it serves a different purpose — preventing `shutdown()` from being called twice).

#### Fix: ServiceWatcher sets EXHAUSTED status on the resource instance

Currently `ServiceWatcher` emits events with `EXHAUSTED_COOLING` and `EXHAUSTED_DEAD` in the payload but never sets the service's actual `.status`. This means the resource's status and the broadcast events disagree — a service can be `.status == FAILED` while the event stream says `EXHAUSTED_COOLING`.

The fix: when ServiceWatcher decides to transition a service to an EXHAUSTED state, it looks up the service instance from `hassette.children` by name and sets its `.status` directly. This adds coupling between ServiceWatcher and the service instances, but the coupling is correct — ServiceWatcher is making lifecycle decisions about these services and the resource's status should reflect those decisions.

Lookup is by `class_name` match against `hassette.children`. If the service is not found (e.g., already removed), the status set is skipped and a warning is logged.

### 2. WebSocket Connection State Machine (#668)

Add a `ConnectionState` enum and transition logic to `WebsocketService`. Three states — the distinction between first-connect and reconnect is inferred from the transition (was the previous state CONNECTED?), not a separate enum value. This keeps the model simple and avoids extra transitions to validate. Adding a fourth state later is additive (one enum member, one transition).

```python
class ConnectionState(StrEnum):
    DISCONNECTED = auto()
    CONNECTING = auto()
    CONNECTED = auto()
```

```
Valid transitions:
  DISCONNECTED → CONNECTING   (serve() starts)
  CONNECTING   → CONNECTED    (handshake + auth + subscribe succeeds)
  CONNECTING   → DISCONNECTED (non-retryable failure or max retries exhausted)
  CONNECTED    → CONNECTING   (connection lost, retrying — this transition implies reconnect)
  CONNECTED    → DISCONNECTED (clean shutdown)
```

Implementation:
- Add `_connection_state: ConnectionState` to `WebsocketService.__init__`, initialized to `DISCONNECTED`
- Add `connection_state` read-only property
- Add `_set_connection_state(new: ConnectionState)` private method that validates the transition and logs at DEBUG. Includes `previous_state` in the log so reconnects are distinguishable: `"CONNECTED → CONNECTING"` (reconnect) vs `"DISCONNECTED → CONNECTING"` (first connect).
- Update `serve()`, `_make_connection()`, `_connect_ws()`, `_start_recv_and_subscribe()`, and `cleanup()` to call `_set_connection_state` at appropriate points
- `_partial_cleanup()` does NOT change connection state — it's resource cleanup, not a state transition. The state is set by the caller (serve loop sets CONNECTING before retry, cleanup() sets DISCONNECTED on shutdown).
- Replace the `connected` property's implementation to return `self._connection_state == ConnectionState.CONNECTED` (preserving the existing public API)
- Invalid transitions respect the `strict_lifecycle` toggle (raise in strict mode, warn otherwise)

Placement: `ConnectionState` enum goes in `types/enums.py` alongside the other enums. The transition table is a module-level constant in `websocket_service.py`.

### 3. Startup Registry Validation (#666)

Add a `validate_registries()` function that runs during `Hassette.wire_services()` (after all modules are imported but before the event loop starts processing).

**STATE_REGISTRY validation:**
- Every registered `BaseState` subclass has a non-None domain in its `StateKey`
- Every registered class is actually a subclass of `BaseState`
- No duplicate domain registrations (same domain, different classes) — log warning, don't raise
- Every registered class can be instantiated with a minimal valid dict (smoke test) — skip if this is too expensive; the Pydantic model_validate path already catches schema issues

**TYPE_REGISTRY validation:**
- Every `TypeConverterEntry.func` is callable
- `from_type` and `to_type` are actual types (not strings, not None)
- `error_types` is a tuple of exception subclasses
- `error_message` format fields (if any) are in `ALLOWED_FORMAT_FIELDS` (already validated at registration; re-check for safety)

Implementation:
- `validate_registries()` in a new `conversion/validation.py` module
- Called from `Hassette.wire_services()` after all service children are added (so all imports have run)
- In strict mode, any validation issue raises `RegistryValidationError` with a summary of all issues found. In non-strict mode, issues are logged as warnings with a single summary line: "Registry validation: N issues found" or "Registry validation: OK"
- Return a list of `RegistryValidationIssue` dataclasses for testability

## Edge Cases

### Lifecycle Transitions

- **Same-state transition** (e.g., `RUNNING → RUNNING`): The existing `handle_*` methods return early with a debug log when already in the target state. This is not a transition — the setter is never called. Behavior unchanged.
- **Concurrent status setter calls**: Two tasks could call `handle_running()` and `handle_failed()` near-simultaneously on the same resource. The setter is not atomic — `self._previous_status = self._status` followed by `self._status = value` could interleave. This is an existing race; the transition guard does not make it worse. Mitigation: the existing idempotency check in each `handle_*` method (`if self.status == X: return`) reduces the window. A lock is not added — the setter is called from the event loop (single-threaded asyncio), so true concurrent mutation requires `await` between the two lines, which doesn't happen.
- **Double shutdown**: `shutdown()` already guards against re-entry (`if self._shutting_down: return`). The transition guard sees `STOPPING → STOPPED` which is valid. No new behavior.
- **Restart from FAILED/CRASHED**: `FAILED → STARTING` and `CRASHED → STARTING` are valid transitions (restart path). The `ServiceWatcher` already performs these. The guard permits them.
- **STOPPING as a new intermediate state**: `shutdown()` now sets STOPPING before hooks run. Any code that previously checked `status == RUNNING` to decide whether to send work to a resource will now correctly see STOPPING and can back off. The `_shutting_down` flag is retained for internal re-entry guarding — it serves a different purpose (preventing `shutdown()` from being called recursively).
- **ServiceWatcher setting EXHAUSTED status**: The watcher looks up the service instance by `class_name` in `hassette.children`. If the service has already been removed (e.g., during a concurrent shutdown), the status set is skipped with a warning. The `.status` assignment goes through the setter and is validated — `FAILED → EXHAUSTED_COOLING` and `FAILED → EXHAUSTED_DEAD` must be in the transition table.
- **Transition table incompleteness**: If a legitimate transition is missing from the table, strict mode will raise in tests — this is the intended discovery mechanism. In production (non-strict), the warning log surfaces the gap without breaking the system. The transition table should be treated as a living document updated when new transition paths are added.

### WebSocket Connection State

- **Auth failure during CONNECTING**: Transitions to DISCONNECTED because InvalidAuthError is non-retryable.
- **Early drop during CONNECTED**: Transitions to CONNECTING (not DISCONNECTED) because the serve() loop will retry. The `CONNECTED → CONNECTING` transition itself indicates a reconnect — no separate RECONNECTING state needed.
- **Max retries exhausted during CONNECTING**: Transitions to DISCONNECTED — the exception propagates to `_serve_wrapper` which handles the failure.
- **Shutdown during CONNECTING**: Transitions to DISCONNECTED via cleanup(). CancelledError propagates normally.
- **`_partial_cleanup()` and connection state**: `_partial_cleanup()` does NOT change connection state. It cleans up resources (cancels recv task, closes socket, clears futures). The state transition is the responsibility of the caller — the serve() retry loop sets CONNECTING before the next `_make_connection()` attempt, and `cleanup()` sets DISCONNECTED on shutdown.
- **Distinguishing first connect from reconnect**: The previous state is included in the DEBUG log. `DISCONNECTED → CONNECTING` = first connect. `CONNECTED → CONNECTING` = reconnect. No separate enum value needed.

### Registry Validation

- **Empty STATE_REGISTRY**: Reported as error. Zero entries means the `hassette.models.states` package was not imported — a broken installation or import cycle.
- **Empty TYPE_REGISTRY**: Reported as error. Zero entries means `hassette.conversion.type_registry` module-level registrations did not run.
- **Duplicate domain in STATE_REGISTRY**: Two classes registered for the same `StateKey(domain="light")`. Reported as warning — the last registration wins (existing behavior). The validation surfaces it for awareness.
- **Converter with non-callable `func`**: Reported as error. This can happen if a `TypeConverterEntry` is constructed with `func=None` or a non-callable value.
- **Registry mutation after validation**: `validate_registries()` runs once at startup. Runtime mutations (auto-registered constructor fallback converters in TYPE_REGISTRY) are not re-validated. This is acceptable — runtime registrations go through the same `TypeRegistry.register()` path which has its own guards.

## Failure Modes

- **Transition table is wrong (missing a valid transition)**: In strict mode, the test suite catches it immediately — any test exercising that code path raises `InvalidLifecycleTransitionError`. In non-strict mode, production logs a warning per occurrence. Fix: update the transition table and add a test for the new path.
- **Strict mode accidentally enabled in production**: Invalid transitions that were previously silent now raise and crash the resource. Mitigation: `strict_lifecycle` defaults to `False` and is only set `True` by the test harness. Users must explicitly opt in via `hassette.toml`. The config field should be documented with a warning that it's intended for debugging, not production use.
- **Registry validation blocks startup**: In strict mode, `RegistryValidationError` prevents `wire_services()` from completing. This is intentional — a broken registry means the framework can't convert states or types correctly. In non-strict mode, startup proceeds with warnings.
- **Performance impact of transition validation**: The guard is a dict lookup (`O(1)`) in the status setter. No measurable impact.
- **ServiceWatcher can't find service instance**: If `hassette.children` doesn't contain a matching service (removed during concurrent shutdown), the status set is skipped with a warning. The event is still emitted — the watcher's event emission is best-effort and already worked without the status set. This is a degraded-but-safe path.
- **STOPPING breaks code that checks `status == RUNNING`**: Code that used `status == RUNNING` as a proxy for "this resource is alive" now sees STOPPING during the shutdown window. This is *correct* behavior — STOPPING means "don't send new work." Any code broken by this was relying on an incorrect assumption.

## Alternatives Considered

**Always raise on invalid transitions (no toggle)**: Simpler but risks breaking production if latent invalid transitions exist. The toggle gives us strict enforcement in tests (where we want every violation to be a failure) and safe logging in production (where we want visibility without breakage).

**Always warn (no toggle)**: Safer but the warnings would likely be ignored. The strict-by-default-in-tests approach means violations surface as test failures, which are much harder to ignore than log lines.

**ConnectionState on Resource base class**: Would give every resource a connection state, but only WebSocket has a meaningful connection lifecycle. Keep it scoped to `WebsocketService`.

**Validating state models by instantiation**: Running `model_validate({...minimal...})` on every registered state class at startup would catch schema issues early, but the cost of constructing ~35 minimal valid dicts (one per domain) outweighs the benefit. Pydantic validation errors at first use are already clear enough.

## Acceptance Criteria

### Lifecycle Transition Guards (#675)

- When a resource transitions `NOT_STARTED → STARTING → RUNNING → STOPPING → STOPPED` in strict mode, no error is raised and each transition is logged at DEBUG
- When a resource attempts `NOT_STARTED → RUNNING` (skipping STARTING) in strict mode, `InvalidLifecycleTransitionError` is raised naming the transition and the resource
- When a resource attempts `NOT_STARTED → RUNNING` in non-strict mode, a WARNING is logged containing the transition pair and resource name, and the transition proceeds
- When `_force_terminal()` sets status to STOPPED from any state, no validation occurs and no error is raised regardless of strict mode (uses `self._status = ...` bypass)
- `shutdown()` sets `STOPPING` before hooks run — a resource in the process of shutting down is observable via `status == STOPPING`
- ServiceWatcher sets the service instance's `.status` to `EXHAUSTED_COOLING` or `EXHAUSTED_DEAD` — the resource's status and broadcast events agree
- The `VALID_TRANSITIONS` table permits every transition exercised by the existing test suite when run with `strict_lifecycle = True`

### WebSocket Connection State Machine (#668)

- `WebsocketService.connection_state` returns `DISCONNECTED` before `serve()` is called
- After successful connection and authentication, `connection_state` returns `CONNECTED`
- After a retriable disconnection during an established connection, `connection_state` transitions to `CONNECTING` (the `CONNECTED → CONNECTING` transition distinguishes reconnect from first connect)
- After auth failure or max retries, `connection_state` returns `DISCONNECTED`
- The existing `connected` property returns `True` only when `connection_state == CONNECTED`
- `_partial_cleanup()` does not change `connection_state`
- Invalid connection state transitions raise in strict mode and warn in non-strict mode

### Startup Registry Validation (#666)

- `validate_registries()` returns an empty list when run against the real (unmodified) registries — all built-in entries are valid
- When a `TypeConverterEntry` with `func=None` is injected, `validate_registries()` returns an issue identifying the entry
- When STATE_REGISTRY is empty, `validate_registries()` returns an issue with a message indicating zero entries
- In strict mode, any validation issue causes `RegistryValidationError` to be raised with a summary of all issues (not just the first)
- In non-strict mode, issues are logged as warnings and startup proceeds

### Strict Lifecycle Toggle

- `HassetteConfig(strict_lifecycle=True)` enables raising behavior for all three subsystems
- `HassetteHarness` defaults to `strict_lifecycle = True` without explicit configuration
- Setting `strict_lifecycle = false` in `hassette.toml` results in warn-only behavior

## Test Strategy

All tests run with `strict_lifecycle = True` (harness default), so invalid transitions are test failures, not warnings.

### New tests

**Lifecycle transition guards** (`tests/unit/resources/`):
- Valid transition sequence: `NOT_STARTED → STARTING → RUNNING → STOPPING → STOPPED` — no error, each logged at DEBUG
- Invalid transition: `NOT_STARTED → RUNNING` — raises `InvalidLifecycleTransitionError` in strict mode
- Non-strict mode: same invalid transition logs WARNING instead of raising, transition still proceeds
- `_force_terminal` bypass: sets STOPPED from RUNNING (or any state) via `self._status` — no validation, no error regardless of mode
- Restart transitions: `FAILED → STARTING`, `CRASHED → STARTING` — valid, no error
- EXHAUSTED transitions: `FAILED → EXHAUSTED_COOLING`, `FAILED → EXHAUSTED_DEAD`, `EXHAUSTED_COOLING → EXHAUSTED_DEAD`, `EXHAUSTED_COOLING → STARTING` — all valid

**STOPPING state** (`tests/unit/resources/`, `tests/integration/`):
- `shutdown()` sets STOPPING before `on_shutdown` hook runs — verify by checking `self.status` inside the hook
- `shutdown()` sets STOPPED after all hooks and cleanup complete
- Double-shutdown still returns early (re-entry guard preserved)

**ServiceWatcher EXHAUSTED status** (`tests/unit/core/`):
- When budget exhausted (TRANSIENT), ServiceWatcher sets service instance's `.status` to `EXHAUSTED_COOLING`
- When budget exhausted (TEMPORARY), ServiceWatcher sets service instance's `.status` to `EXHAUSTED_DEAD`
- When cooldown cycles exceeded, ServiceWatcher transitions instance from `EXHAUSTED_COOLING` to `EXHAUSTED_DEAD`
- When service instance not found in `hassette.children`, status set is skipped with warning logged — no error raised

**Connection state machine** (`tests/unit/core/`):
- Initial state is `DISCONNECTED`
- After successful connect + auth + subscribe: `CONNECTED`
- After retriable disconnect from CONNECTED: `CONNECTING` (reconnect path)
- After non-retryable failure (auth): `DISCONNECTED`
- After max retries exhausted: `DISCONNECTED`
- `_partial_cleanup()` does not change `connection_state`
- `connected` property returns `True` only when `connection_state == CONNECTED`
- Invalid transition (e.g., `DISCONNECTED → CONNECTED` skipping CONNECTING): raises in strict, warns in non-strict
- Integration with existing WebSocket service tests (reconnection, early drop, auth failure paths)

**Registry validation** (`tests/unit/conversion/`):
- Real registries pass validation with zero issues (smoke test)
- `TypeConverterEntry` with `func=None` → issue reported
- `TypeConverterEntry` with `from_type=None` → issue reported
- Empty STATE_REGISTRY → issue reported
- Empty TYPE_REGISTRY → issue reported
- Duplicate domain registration in STATE_REGISTRY → warning-level issue reported
- Strict mode: issues raise `RegistryValidationError` with summary of all issues
- Non-strict mode: issues logged as warnings, startup proceeds

**Strict toggle** (`tests/unit/`):
- `HassetteConfig(strict_lifecycle=True)` → lifecycle violations raise
- `HassetteConfig(strict_lifecycle=False)` → lifecycle violations warn
- `HassetteHarness` defaults to `strict_lifecycle=True` without explicit config

### Existing test audit

Enabling `strict_lifecycle = True` on the harness means every existing test (~688) now enforces valid transitions. Any test that triggers a previously-silent invalid transition will fail. This is an explicit implementation step:

1. Run the full suite with `strict_lifecycle = True`
2. For each failure, determine whether:
   - **The transition table is missing a legitimate transition** — update the table and add a test for that path
   - **The test is triggering an actually-invalid transition** — fix the test or the production code
   - **The test is manipulating status directly in ways that bypass normal lifecycle** — update the test to use proper lifecycle methods, or use `self._status = ...` for deliberate test-only state setup
3. All ~688 tests must pass with `strict_lifecycle = True` before merging

This audit may be the largest single task in the bundle. Budget time accordingly — it's the mechanism by which we discover whether the transition table is correct and complete.

## Implementation Notes

These are not design decisions — they're traps the implementer should be aware of.

**1. Status setter must guard against missing `hassette` attribute.** The `status` setter checks `self.hassette.config.strict_lifecycle`, but `self.hassette` is set in `Resource.__init__()` which runs after `LifecycleMixin.__init__()`. The initial `self._status = NOT_STARTED` uses direct assignment so it's safe. The first setter call (`handle_starting()`) happens during `initialize()`, well after `__init__`, so it should work. But add a `hasattr(self, 'hassette')` guard in the setter anyway — if anything ever calls the setter before `Resource.__init__` completes, the `AttributeError` will be confusing. When the guard fails (no `hassette`), fall through without validation (not strict, not warning — the object isn't fully constructed yet).

**2. EXHAUSTED statuses now visible via REST API.** The health/status REST endpoints read `.status` directly from resource instances. Previously they always saw `FAILED` because ServiceWatcher never set EXHAUSTED on the instance. After this change, those endpoints will return `EXHAUSTED_COOLING` or `EXHAUSTED_DEAD`. The frontend event stream already handles these statuses (it received them in event payloads), but the REST snapshot path may not — verify that the frontend's status-to-badge mapping handles EXHAUSTED from REST responses, not just from WS events. If it doesn't, file a follow-up issue rather than blocking this PR.

**3. Registry validation tests must use snapshot/restore.** `StateRegistry._registry` and `TypeRegistry.conversion_map` are `ClassVar` dicts — class-level mutable state shared across all tests. Tests that inject malformed entries will pollute other tests. Both registries already have `snapshot()` and `restore()` methods. Use them in a fixture:
```python
@pytest.fixture(autouse=True)
def _isolate_registries():
    state_snap = StateRegistry.snapshot()
    type_snap = TypeRegistry.snapshot()
    yield
    StateRegistry.restore(state_snap)
    TypeRegistry.restore(type_snap)
```

**4. `create_hassette_stub()` and strict mode.** The test harness (`HassetteHarness`) defaults to `strict_lifecycle = True`, but `create_hassette_stub()` builds a MagicMock for web/API tests. The stub doesn't go through real lifecycle transitions, so it doesn't need to respect `strict_lifecycle`. However, if a web test creates a real `Resource` with a stubbed hassette, the `hasattr` guard from note #1 will fire (MagicMock returns a truthy mock for `config.strict_lifecycle`). Either ensure the mock's `config.strict_lifecycle` returns a sensible value, or rely on the `hasattr` guard to handle the pre-init case.
