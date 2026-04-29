# Design: Service Supervision Redesign

**Date:** 2026-04-28
**Status:** approved
**Research:** design/research/2026-04-28-service-supervision/research.md

## Problem

The service supervision system applies a single global restart policy to all services regardless of their criticality, failure modes, or recovery characteristics. This causes three concrete problems:

1. **Budget depletion across failure epochs.** The restart counter is monotonic and only resets when a service reaches RUNNING and signals readiness within a fixed timeout. Services with legitimate multi-layer retry logic (where recovery can take minutes) never get their counter reset because the readiness timeout expires first. Over time, past transient failures consume the budget for future genuine recovery attempts.

2. **No criticality distinction.** An optional dev-only file watcher exhausting its restart budget triggers the same system shutdown as the core event bus failing. Every service failure is treated as equally catastrophic.

3. **Services cannot declare their own restart behavior.** The service has the most context about which errors are recoverable, how long startup takes, and how aggressively to retry — but the framework doesn't ask. Services that need different policies must implement their own internal retry logic, creating two independent, uncoordinated retry layers.

## Goals

- Services declare their own restart characteristics (criticality, retryable errors, backoff, startup expectations) as part of their class definition
- Past transient failures are automatically forgiven over time without requiring an explicit readiness signal
- Optional services can fail and exhaust their restart budget without affecting the rest of the system
- Critical services still trigger system shutdown when they cannot recover
- Services with long initialization (multi-layer connection retry) are not penalized by a fixed readiness timeout
- All service status transitions — including new states like degraded or exhausted — are visible in the UI and emitted as events

## Non-Goals

- **Liveness heartbeat / watchdog**: No periodic "are you still alive" probing. The watcher reacts to failure events, not polling. Worth revisiting if stuck-process detection becomes a problem.
- **Hot-reload of restart policies**: RestartSpec is a class attribute read at startup. Changing restart behavior requires a code change and process restart.
- **Coordination between internal and external retry layers**: The watcher does not know about a service's internal retry logic. The two layers are independent by design.
- **Circuit breaker state machine**: No HALF_OPEN probing state. Long-cooldown retry for transient services achieves a similar effect with less complexity.
- **Manual service recovery**: No API, UI action, or CLI command to manually restart an exhausted service. Exhausted TEMPORARY services require a full process restart. A one-shot restart endpoint is a natural follow-up but out of scope for this redesign.

## User Scenarios

### Operator: Hassette instance owner

- **Goal:** Run a stable hassette instance where transient failures self-heal and critical failures are surfaced clearly
- **Context:** Long-running deployment on a VPS with occasional Home Assistant connectivity issues

#### Wobbly WebSocket connection

1. **Home Assistant becomes temporarily unreachable**
   - Sees: WebsocketService enters its internal retry loop (early-drop detection, connection retries)
   - Decides: Nothing — the system handles this automatically
   - Then: WebsocketService's internal retries eventually fail, service exits serve() with an error

2. **ServiceWatcher observes the failure**
   - Sees: WebsocketService entered FAILED state
   - Decides: Check the service's restart spec — it's TRANSIENT with a budget of 5 restarts in 300 seconds
   - Then: Apply backoff from the spec, restart the service

3. **WebsocketService recovers on restart**
   - Sees: Service reaches RUNNING, then signals readiness after completing subscription setup
   - Decides: Nothing — readiness is observed but does not participate in budget tracking
   - Then: The restart timestamp stays in the sliding window and will naturally expire after 300 seconds

4. **WebsocketService cannot recover (HA down for extended period)**
   - Sees: Service exhausts its sliding-window budget (5 restarts in 300 seconds)
   - Decides: Service is TRANSIENT, so enter long-cooldown retry instead of shutdown
   - Then: After a longer cooldown period, reset the window and try again. System continues running without WebSocket.

#### Optional service crashes in production

1. **FileWatcherService crashes**
   - Sees: Service entered FAILED state
   - Decides: Check restart spec — it's TEMPORARY with a budget of 3 restarts in 60 seconds
   - Then: Restart with backoff

2. **FileWatcherService exhausts budget**
   - Sees: 3 restarts in 60 seconds, budget exceeded
   - Decides: Service is TEMPORARY — mark as dead, do not retry further
   - Then: Service stays dead. System continues running. UI shows the service as permanently failed.

#### Critical service fails

1. **BusService crashes**
   - Sees: Service entered FAILED state
   - Decides: Check restart spec — it's PERMANENT with a budget of 2 restarts in 30 seconds
   - Then: Restart immediately with minimal backoff

2. **BusService cannot recover**
   - Sees: Budget exhausted
   - Decides: Service is PERMANENT — system cannot function without it
   - Then: Trigger system shutdown

### Framework developer: Adding a new service

- **Goal:** Define a new Service subclass with appropriate restart behavior
- **Context:** Implementing a new background service for hassette

#### Declaring restart behavior

1. **Define the service class**
   - Sees: Service base class with a `restart_spec` class attribute
   - Decides: Which restart type fits (permanent, transient, temporary), what errors are non-retryable, how aggressive the backoff should be
   - Then: Override `restart_spec` with a RestartSpec configured for the service's failure profile

2. **Service is automatically supervised**
   - Sees: ServiceWatcher picks up the restart spec from the class attribute
   - Decides: Nothing — the watcher reads the spec and applies it
   - Then: Service gets per-service supervision matching its declared behavior

## Functional Requirements

1. Each service must declare a restart specification as a class attribute that describes its restart type, error classification, backoff parameters, startup expectations, and restart budget
2. The restart specification must support three restart types:
   - **Permanent**: restart on any failure; system shutdown when budget is exhausted
   - **Transient**: restart on failure; long-cooldown retry cycle when budget is exhausted
   - **Temporary**: restart on failure; stay dead when budget is exhausted
3. The restart budget must use a sliding time window where restart timestamps older than the window period are automatically discarded — no explicit reset required
4. Services must be able to declare specific error class names as non-retryable; failures whose exception type name matches a declared non-retryable name must skip the restart loop entirely and follow the budget-exhaustion path for that restart type. Matching is by exact class name string (not isinstance), since the watcher receives exception type as a serialized string via bus events. `FatalError` subclasses are already non-retryable via the existing CRASHED path and must not appear in `non_retryable_error_names`
5. The readiness timeout must not count against the restart budget; a service that reaches RUNNING but takes longer than expected to signal readiness must not be penalized with a budget increment
6. Services must be able to declare a startup timeout that overrides the default readiness wait period, allowing services with known long initialization to take the time they need
7. When a transient service exhausts its budget, the system must enter a long-cooldown retry cycle: after a configurable cooldown period, reset the sliding window and attempt restart again
8. The restart specification must provide defaults so that services without explicit overrides behave as transient with a budget of 5 restarts in 300 seconds, 2-second base backoff with 2x multiplier capped at 60 seconds, 30-second startup timeout, and 300-second long-cooldown period
9. All existing global restart configuration fields must be removed in favor of per-service defaults built into the restart specification
10. All status transitions — including budget exhaustion, long-cooldown entry, and permanent failure — must emit events and be visible in the monitoring UI
11. The service watcher must remain independent from services' internal retry logic; it must only observe failures that escape the service's `serve()` method

## Edge Cases

1. **Concurrent service failures**: Multiple services fail simultaneously. The watcher must handle each independently according to its own restart spec, without one service's restart blocking another's.
2. **Shutdown signal during restart**: A shutdown signal arrives while a service is mid-restart (between shutdown and initialize). The restart must be abandoned cleanly without leaving the service in an intermediate state.
3. **Rapid mark-ready-then-fail**: A service signals readiness, then immediately fails again. The sliding window naturally handles this — each restart adds a timestamp, and rapid cycling fills the window quickly.
4. **Non-retryable error from a permanent service**: A permanent service raises a non-retryable error. The service should skip the restart loop and go directly to system shutdown (the error will never resolve by retrying).
5. **Wobbly WebSocket connection**: Home Assistant connectivity is intermittent, causing WebsocketService to cycle through its internal retries and occasionally escape to the watcher. The sliding window must tolerate occasional restarts spread over long periods without exhausting the budget.
6. **Service fails during startup (before first mark_ready)**: A service crashes during initialization before ever signaling readiness. This should count as a restart attempt in the sliding window, using the startup timeout (not the default readiness timeout) to determine how long to wait.
7. **Long-cooldown retry succeeds**: A transient service exhausts its budget, enters long cooldown, then successfully restarts after cooldown. The sliding window should be reset so the service gets a fresh budget.
9. **restart() raises an exception**: If `service.restart()` throws (e.g., during `shutdown()` or `on_initialize()`), the budget entry is already recorded (pre-record semantics: entries represent attempts initiated, not completed). The watcher catches the exception, logs it, and leaves the service in FAILED state. The watcher does NOT record an additional budget entry — it waits for the next FAILED event from the service to re-enter the restart cycle. The in-restart guard is cleared so the next FAILED event is not dropped.
8. **Budget window expires with no new failures**: A service fails and restarts twice, then runs stably for longer than the window period. Both restart timestamps expire from the window — the budget is fully restored without any explicit action.

## Acceptance Criteria

- [ ] Each of the 8 existing services declares a restart specification matching its criticality and failure profile
- [ ] A permanent service that exhausts its sliding-window budget triggers system shutdown
- [ ] A transient service that exhausts its budget enters a long-cooldown retry cycle instead of triggering shutdown
- [ ] A temporary service that exhausts its budget stays dead; the system continues running
- [ ] Restart timestamps older than the budget window period are automatically discarded from the budget calculation
- [ ] A service raising an error whose class name matches a declared non-retryable name skips the restart loop entirely
- [ ] A service that reaches RUNNING but has not yet signaled readiness does not have a restart counted against its budget
- [ ] Services with declared startup timeouts are given that duration (not the default) to signal readiness
- [ ] The global restart configuration fields are removed; default behavior comes from the restart specification
- [ ] Budget exhaustion, long-cooldown entry/exit, and permanent failure emit events visible in the UI
- [ ] Multiple simultaneous service failures are handled independently per their individual restart specs
- [ ] A transient service that recovers after long-cooldown retry gets a fresh sliding window
- [ ] DatabaseService raises a typed `SchemaVersionError` (extracted from current RuntimeError) from `_handle_schema_version()`, listed in `fatal_error_names`
- [ ] A service that does not override the restart specification gets transient behavior with a budget of 5 restarts in 300 seconds
- [ ] A service's internal retry logic (e.g., WebsocketService early-drop retries) does not interact with the watcher's restart budget — the watcher only observes failures that exit serve()

## Dependencies and Assumptions

- The bus event system must remain functional for status event emission (circular dependency: if BusService itself fails, its failure event is emitted before it shuts down — this is already the case today)
- The web UI must be updated to display new service states (long-cooldown, permanently failed, budget status)
- The existing `Service.restart()` method signature must not change (called by app code)
- The `mark_ready()` / `wait_ready()` contract remains unchanged; only the watcher's response to readiness timing changes
- **Known limitation: BusService restart blind window.** The watcher subscribes to service status events via BusService. During a BusService restart, other services' FAILED events may be dropped. After BusService recovery (RUNNING+ready), the watcher must perform a reconciliation scan: query all service statuses directly and check for any services in FAILED state that have no corresponding budget entry. If found, treat them as if a FAILED event had been received (enter the normal restart flow). This is an inherent architectural limitation of event-bus-based supervision, not introduced by this redesign.

## Architecture

### RestartSpec dataclass

A new dataclass in `src/hassette/resources/base.py` (co-located with Service):

```python
@dataclass(frozen=True)
class RestartSpec:
    restart_type: RestartType = RestartType.TRANSIENT
    non_retryable_error_names: tuple[str, ...] = ()  # skip restart, follow budget-exhaustion path
    fatal_error_names: tuple[str, ...] = ()  # always trigger immediate shutdown regardless of restart_type
    backoff_base_seconds: float = 2.0
    backoff_multiplier: float = 2.0
    backoff_max_seconds: float = 60.0
    budget_intensity: int = 5          # max restarts within window
    budget_period_seconds: float = 300.0  # sliding window size
    startup_timeout_seconds: float = 30.0  # how long to wait for mark_ready
    cooldown_seconds: float = 300.0    # long-cooldown for transient budget exhaustion
    max_cooldown_cycles: int = 0       # 0 = infinite; after N cycles, transition to EXHAUSTED_DEAD
```

`RestartType` is an enum: `PERMANENT`, `TRANSIENT`, `TEMPORARY`.

The Service base class gets a class attribute:
```python
class Service(Resource):
    restart_spec: ClassVar[RestartSpec] = RestartSpec()
```

A `__init_subclass__` hook on `Service` emits `warnings.warn()` when a concrete Service subclass is created without declaring its own `restart_spec`. This prevents silent inheritance of a parent service's production profile by test doubles or future subclasses. Matches the existing `__init_subclass__` pattern in `Resource` for `depends_on`.

### Per-service declarations

Each service overrides the class attribute:

- **BusService**: `RestartSpec(restart_type=PERMANENT, budget_intensity=2, budget_period_seconds=30)`
- **SchedulerService**: `RestartSpec(restart_type=PERMANENT, budget_intensity=2, budget_period_seconds=30)`
- **WebsocketService**: `RestartSpec(restart_type=TRANSIENT, budget_intensity=5, budget_period_seconds=300, startup_timeout_seconds=60)` (note: `InvalidAuthError` is a `FatalError` subclass and already routes to CRASHED, not FAILED — it does not need to appear in `non_retryable_error_names`)
- **DatabaseService**: `RestartSpec(restart_type=TRANSIENT, budget_intensity=3, budget_period_seconds=120, fatal_error_names=("SchemaVersionError",))` (SchemaVersionError to be extracted from current RuntimeError usage; fatal because schema mismatches cannot self-heal)
- **WebApiService**: `RestartSpec(restart_type=TRANSIENT, budget_intensity=3, budget_period_seconds=60)`
- **CommandExecutor**: `RestartSpec(restart_type=TRANSIENT, budget_intensity=3, budget_period_seconds=120)`
- **FileWatcherService**: `RestartSpec(restart_type=TEMPORARY, budget_intensity=3, budget_period_seconds=60)`
- **WebUiWatcherService**: `RestartSpec(restart_type=TEMPORARY, budget_intensity=3, budget_period_seconds=60)`

### Sliding-window budget tracker

A new class `RestartBudget` in `src/hassette/core/service_watcher.py`:

```python
class RestartBudget:
    def __init__(self, intensity: int, period_seconds: float):
        self._timestamps: list[float] = []
        self._intensity = intensity
        self._period = period_seconds

    def record_restart(self) -> None:
        self._timestamps.append(time.monotonic())

    def is_exhausted(self) -> bool:
        self._evict_expired()
        return len(self._timestamps) >= self._intensity

    def reset(self) -> None:
        self._timestamps.clear()

    def _evict_expired(self) -> None:
        cutoff = time.monotonic() - self._period
        self._timestamps = [t for t in self._timestamps if t > cutoff]
```

The watcher maintains a `dict[str, RestartBudget]` keyed by service identity (name:role), created lazily from each service's `restart_spec`.

### In-restart guard

The watcher maintains `_restarting: set[str]` (keyed by service identity). When `restart_service()` fires:

1. If the service key is already in `_restarting`, drop the event and return (a restart is already in progress; the duplicate FAILED event is from the in-progress restart's own failure).
2. Add the service key to `_restarting` before `record_restart()`.
3. Clear the service key from `_restarting` when the service emits RUNNING (restart succeeded) or when a new FAILED event arrives after the restart completes (restart failed, new cycle begins).

This prevents double budget depletion from fail-during-restart and concurrent FAILED events racing the watcher.

### ServiceWatcher changes

The `restart_service()` handler is restructured:

1. **Check fatal errors**: If the failure event's `exception_type` string matches any name in `spec.fatal_error_names`, emit CRASHED and trigger immediate system shutdown regardless of restart type.
2. **Check non-retryable errors**: If the failure event's `exception_type` string matches any name in `spec.non_retryable_error_names`, skip restart and go to exhaustion handling.
3. **Check budget**: If `budget.is_exhausted()`, go to exhaustion handling.
4. **Record restart**: `budget.record_restart()`.
5. **Apply backoff**: Use the service's spec values instead of global config. Sleep using shutdown-safe pattern.
6. **Restart the service**: Call `service.restart()` as today.

Exhaustion handling depends on restart type:
- **PERMANENT**: Emit CRASHED event, call `hassette.shutdown()`.
- **TRANSIENT**: Emit `EXHAUSTED_COOLING` status (with `retry_at` timestamp), schedule a long-cooldown task. After cooldown, reset the budget and attempt restart. If `max_cooldown_cycles` is non-zero and exceeded, transition to `EXHAUSTED_DEAD` instead. Errors that can never self-heal should be classified in `fatal_error_names` or `non_retryable_error_names` so they never reach cooldown — `max_cooldown_cycles` is insurance against unknown unknowns where an error is indistinguishable from a recoverable one.
- **TEMPORARY**: Emit `EXHAUSTED_DEAD` status. No further action.

### Error routing policy

Three layers of non-retry behavior, each with a distinct domain:

1. **`FatalError` subclasses** (existing): raised in `serve()`, caught by `_serve_wrapper`, routes to `handle_crash()` → CRASHED status → `shutdown_if_crashed()`. These never reach `restart_service()`. Use for errors where the service itself knows at raise-time that recovery is impossible (e.g., `InvalidAuthError`).

2. **`fatal_error_names`** (new): checked by the watcher on FAILED events. Triggers immediate system shutdown regardless of restart type. Use for errors that cannot self-heal but are not `FatalError` subclasses — typically configuration errors discovered during `on_initialize()` (e.g., `SchemaVersionError`).

3. **`non_retryable_error_names`** (new): checked by the watcher on FAILED events. Skips restart and follows the budget-exhaustion path for the service's restart type. Use for errors that shouldn't be retried immediately but where the exhaustion behavior (cooldown for TRANSIENT, dead for TEMPORARY) is appropriate.

Constraint: `FatalError` subclass names must not appear in `fatal_error_names` or `non_retryable_error_names` — they are already handled by layer 1 and would be dead code in the FAILED path.

### Shutdown-safe sleeping

All sleeps in restart paths (backoff delays and long-cooldown waits) must use `asyncio.wait_for(hassette.shutdown_event.wait(), timeout=duration)` instead of `asyncio.sleep(duration)`. An early wake (shutdown event fires before timeout) is treated as an abort signal — the restart or cooldown is abandoned. The long-cooldown task must be spawned in `ServiceWatcher.task_bucket` (so watcher shutdown cancels it), must check `hassette.shutdown_event.is_set()` before executing the restart, and must be keyed per-service so a second budget exhaustion for the same service cancels the first cooldown task before starting a new one.

### Readiness and budget reset

The `_on_service_running()` handler changes:
- Still waits for `mark_ready()` using the service's `startup_timeout_seconds`.
- Readiness timeout is logged as a warning but does NOT increment the restart budget (decoupled from budget tracking).
- When a service reaches RUNNING and signals readiness, `budget.reset()` is called — a fully recovered service gets its full budget back. Two independent failures with full recovery between them are treated as separate incidents, not accumulated.
- The sliding window provides automatic forgiveness for services that recover but don't explicitly signal readiness. The explicit reset on RUNNING+ready provides immediate forgiveness for services that do.

### Config removal

Remove from `HassConfig`:
- `service_restart_max_attempts`
- `service_restart_backoff_seconds`
- `service_restart_backoff_multiplier`
- `service_restart_max_backoff_seconds`
- `service_restart_readiness_timeout_seconds`

Keep `service_watcher_log_level` (orthogonal to restart policy).

### Trade-offs

This architecture optimizes for **per-service correctness** (each service gets appropriate supervision) and **automatic forgiveness** (sliding window). It sacrifices:

- **Simplicity**: 8 services now each declare their own spec, and the watcher has three exhaustion paths instead of one. More code, more test surface.
- **Global override**: Operators cannot tune restart behavior without code changes. The rejected "global config as fallback" alternative would have allowed this.
- **Stuck-process detection**: Without a liveness heartbeat, a service that hangs (not crashed, not exited) is invisible to the watcher.

### Event and UI changes

Two new service statuses:
- `EXHAUSTED_DEAD` — budget exceeded, no further restarts (TEMPORARY services, or TRANSIENT services that exhaust `max_cooldown_cycles`)
- `EXHAUSTED_COOLING` — budget exceeded, long-cooldown in progress (TRANSIENT services during cooldown)

The `ServiceStatusPayload` event already includes `resource_name`, `role`, `status`, `previous_status`, `exception`, `traceback`. Add `retry_at: float | None = None` (Unix timestamp) — populated with `time.time() + cooldown_seconds` when emitting `EXHAUSTED_COOLING`, `None` for `EXHAUSTED_DEAD` and PERMANENT exhaustion (which triggers CRASHED + shutdown). The web UI renders both states distinctly: `EXHAUSTED_DEAD` as a permanent failure indicator, `EXHAUSTED_COOLING` with a countdown timer using `retry_at`.

## Alternatives Considered

### Global config with per-service overrides

Keep the global config fields as defaults, allow per-service overrides via config (e.g., `service_restart_websocket_max_attempts`). Rejected because: it pushes service-specific knowledge into deployment configuration rather than the service class where it belongs. The service author knows what errors are non-retryable and how long startup takes — the deployer shouldn't have to.

### Method-based restart spec

`def restart_spec(self) -> RestartSpec` instead of a class attribute. More flexible (can vary based on runtime state) but adds indirection, is harder to inspect at import time, and none of the 8 services need runtime-varying specs today. Class attribute is simpler and can be upgraded to a method later if needed.

### Coordinated internal/external retry layers

Have the watcher coordinate with services' internal retry logic (e.g., WebsocketService signals "I'm retrying internally, don't count this"). Rejected because: it creates coupling between the watcher and service internals, muddles the budget's meaning, and the sliding window already handles the practical problem (occasional watcher-level restarts spaced over long periods naturally stay within budget).

### Circuit breaker pattern

Add HALF_OPEN probing state for services recovering from budget exhaustion. Rejected as over-engineering for the current scale — the long-cooldown retry for transient services achieves a similar effect (try again after cooldown) without the state machine complexity. Worth revisiting if hassette grows to manage many more services.

## Test Strategy

### Unit tests

- `RestartSpec` dataclass: default values, frozen immutability, non-retryable error matching
- `RestartBudget`: sliding window eviction, exhaustion detection, reset behavior, edge cases (empty window, exactly-at-boundary timestamps)
- Backoff calculation with per-service spec values

### Integration tests

- ServiceWatcher with PERMANENT service: failure → restart → budget exhaustion → shutdown
- ServiceWatcher with TRANSIENT service: failure → restart → budget exhaustion → long cooldown → restart → recovery
- ServiceWatcher with TEMPORARY service: failure → restart → budget exhaustion → stays dead
- Non-retryable error: service raises non-retryable → immediate exhaustion path (no restart attempt)
- Readiness decoupling: service reaches RUNNING, readiness times out → no budget impact
- Concurrent failures: two services fail simultaneously → each handled by its own spec
- Sliding window forgiveness: restart, wait longer than window, restart again → budget is 1, not 2
- Long-cooldown recovery: transient exhaustion → cooldown → successful restart → fresh window
- Dependent-service concurrent failure: DatabaseService + CommandExecutor fail simultaneously → verify restart ordering respects depends_on and no double budget penalty
- DatabaseService cooldown telemetry loss: when DatabaseService enters EXHAUSTED_COOLING, track aggregate count of dropped writes during cooldown and emit summary on resume

### Existing test migration

The existing `test_service_watcher.py` tests need updating:
- Remove global config references
- Update fixtures to use RestartSpec
- Verify that existing behavioral guarantees (restart works, max attempts enforced, backoff calculated) still hold under the new model

## Documentation Updates

- `docs/` site: Update the service lifecycle page to document RestartSpec, restart types, and budget behavior
- `CLAUDE.md`: Update the "Resource Hierarchy" section to mention RestartSpec
- Docstrings on RestartSpec, RestartType, RestartBudget, and updated ServiceWatcher methods
- Migration note: document removal of global config fields for anyone tracking hassette's configuration surface

## Impact

### Files modified

- `src/hassette/resources/base.py` — Add RestartSpec, RestartType, class attribute on Service
- `src/hassette/core/service_watcher.py` — RestartBudget, restructured restart/exhaustion logic, readiness decoupling
- `src/hassette/config/config.py` — Remove 5 global config fields
- `src/hassette/core/websocket_service.py` — Declare RestartSpec
- `src/hassette/core/web_api_service.py` — Declare RestartSpec
- `src/hassette/core/database_service.py` — Declare RestartSpec, extract SchemaVersionError
- `src/hassette/core/bus_service.py` — Declare RestartSpec
- `src/hassette/core/command_executor.py` — Declare RestartSpec
- `src/hassette/core/scheduler_service.py` — Declare RestartSpec
- `src/hassette/core/file_watcher.py` — Declare RestartSpec
- `src/hassette/core/web_ui_watcher.py` — Declare RestartSpec
- `src/hassette/core/domain_models.py` — Add EXHAUSTED to service status enum
- `src/hassette/events/hassette.py` — Ensure EXHAUSTED status flows through existing event types
- `tests/integration/test_service_watcher.py` — Rewrite for per-service specs, sliding window, exhaustion paths
- Web UI components — Render EXHAUSTED state, optional cooldown timer display
- `src/hassette/web/models.py` — Update response models if needed for new status
- OpenAPI spec + frontend types — Regenerate

### Blast radius

Medium-high. The Service base class change touches all 8 services, but each change is a one-line class attribute declaration. The ServiceWatcher rewrite is contained to one file but changes core supervision behavior. Config removal is a breaking change for anyone who set those values (documented as migration).

## Open Questions

None — all design decisions resolved during discovery.
