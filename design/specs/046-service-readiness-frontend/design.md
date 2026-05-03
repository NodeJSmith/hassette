# Design: Surface Service Readiness in the Frontend

**Date:** 2026-05-02
**Status:** archived
**Research:** design/research/2026-04-26-resource-service-lifecycle/research.md, design/research/2026-04-26-loading-splash-screen/research.md, design/research/2026-04-28-service-supervision/research.md

## Problem

The dashboard shows services as either healthy (hidden) or failed (visible), with nothing in between. When a service like WebSocket is actively reconnecting — which can take 18+ seconds — the UI shows it as healthy because its status is RUNNING. The user has no indication that the system is degraded until something visibly breaks.

This happens because status (RUNNING = task loop is executing) and readiness (RUNNING + actually functional) are conflated at the event layer. The backend already tracks readiness internally via `mark_ready()` / `mark_not_ready()`, but this state is never included in the events broadcast to the frontend.

A separate but related need: the loading splash screen (issue #615) requires structured readiness data to show startup progress ("Connecting to HA...", "Syncing states..."). Solving the readiness visibility problem at the event layer serves both the dashboard and the future splash screen.

## Goals

- Users can see when a service is running but not yet functional (e.g., reconnecting, syncing)
- Users can see *what* a service is doing during its non-ready phase (a human-readable phase description, not just a binary indicator)
- Per-service readiness is surfaced via the WS event pipeline. The health endpoint continues to compute aggregate readiness via direct `is_ready()` calls. Unifying these paths is deferred to the REST snapshot work planned for #615
- No information is lost — services that don't provide a phase string still show a generic "Starting" indicator

## User Scenarios

### Operator: Home automation developer

- **Goal:** Understand system health at a glance during startup, reconnection, or degraded operation
- **Context:** Pulls up the dashboard after a restart or when automations aren't firing

#### Service initializing after startup

1. **Opens the dashboard during startup**
   - Sees: Service Status panel showing WebSocket as "Starting — Connecting to HA..." with an amber indicator
   - Decides: Whether to wait or investigate
   - Then: Phase text updates to "Authenticating..." then "Subscribing to events...", then the row disappears (service is ready and healthy)

#### Service loses connection mid-operation

1. **Dashboard is open when Home Assistant restarts**
   - Sees: WebSocket row appears in the Service Status panel as "Starting — Reconnecting" with an amber indicator
   - Decides: Whether this is expected (HA update) or unexpected (crash)
   - Then: Row disappears when WebSocket reconnects and re-authenticates

#### Service with no phase detail

1. **A simpler service (e.g., FileWatcher) transitions through not-ready briefly**
   - Sees: Row appears as "Starting" with no detail text (the service didn't provide a phase string)
   - Then: Row disappears quickly as the service becomes ready

## Functional Requirements

1. Every service status event broadcast to the frontend SHALL include a readiness indicator (boolean) and an optional phase description (text, nullable)
2. The readiness indicator SHALL be `true` only after the service has explicitly signaled functional readiness, and `false` at all other times (including during RUNNING before readiness, and after readiness is revoked)
3. The phase description SHALL be the human-readable reason string provided by the service when it signals readiness or lack thereof (e.g., "Connecting to HA...", "Initial state sync complete")
4. When a service revokes its readiness without changing status (e.g., WebSocket disconnects while the reconnection loop keeps running), a new status event SHALL be emitted immediately so the frontend learns about the transition without waiting for a status change
5. When a service signals readiness without changing status (e.g., WebSocket successfully reconnects), a new status event SHALL be emitted immediately
6. Readiness events SHALL NOT be emitted when the service is not in a running state — during stop, fail, and crash transitions, the status change event itself carries `ready=false` and no separate readiness event is needed
7. The dashboard SHALL display services that are running but not ready as a distinct visual state: amber indicator with "Starting" label, plus the phase description if available
8. Services that are running and ready SHALL be treated as healthy and hidden from the Service Status panel (current behavior for RUNNING)
9. The phase description SHALL be displayed as secondary detail text alongside the status label when present
10. The readiness and phase fields SHALL have safe defaults (not ready, no phase) so that services which predate this change or don't opt in behave correctly

## Edge Cases

1. **Service revokes readiness then immediately re-signals it** — Two events fire in rapid succession from the service's async `serve()` context. The frontend must handle both; the final state wins. No deduplication or debouncing at the event layer.
2. **Service calls mark_not_ready() during shutdown/crash path** — `mark_not_ready()` is side-effect-free; it only clears the readiness flag. The subsequent `handle_stop()`/`handle_failed()`/`handle_crash()` event carries `ready=false`. No duplicate event because the service does not call `_emit_readiness_event()` during shutdown — only the lifecycle transition emits.
3. **`request_shutdown()` calls mark_not_ready() while still RUNNING** — Since `mark_not_ready()` does not emit events, no readiness-change event fires. The subsequent `handle_stop()` event carries `ready=false, ready_phase="shutdown requested"`. A brief window exists where the backend state is not-ready but no event has been sent — this is acceptable because the STOPPED event follows immediately.
4. **Buffered events from before the schema change replayed on WS reconnect** — Old events lack readiness fields. The domain model's defaults (`ready=false`, `ready_phase=null`) serialize cleanly; the frontend uses `?? false` / `?? null` guards.
5. **Service calls mark_ready() before handle_running()** — `mark_ready()` does not emit events, so no premature emission occurs. When `handle_running()` fires, it includes `ready=self.is_ready()` which is now `true`.
6. **Phase string is long or contains special characters** — Frontend truncates or wraps gracefully. No length validation at the event layer — phase strings are internal, not user-supplied.
7. **Frontend reconnects after service recovered during disconnected window** — `serviceStatus` state is cleared on WS reconnect (alongside existing `logs.clear()`). A brief flash of empty state occurs until fresh events arrive. The REST snapshot endpoint planned for #615 will eliminate this gap.

## Acceptance Criteria

1. When WebSocketService is RUNNING but still connecting, the dashboard shows it with an amber "Starting" indicator and the phase text provided by the service
2. When WebSocketService becomes fully connected, the dashboard row disappears (service is healthy)
3. When WebSocketService loses its connection while the reconnection loop keeps running, the dashboard row reappears with amber "Starting" and the current phase text within one event cycle
4. The health endpoint continues to function correctly using `is_ready()` — no behavior change
5. Services that don't provide a phase string show "Starting" with no detail text
6. All existing non-readiness status behaviors (failed, crashed, exhausted_dead, exhausted_cooling) are unaffected
7. The readiness and phase data are available on the same event payload used by the future splash screen (#615)

## Dependencies and Assumptions

- The existing `mark_ready()` / `mark_not_ready()` API on `LifecycleMixin` already accepts a `reason` string parameter — this is the source of the phase text, requiring no API change to callers
- The existing `_ready_reason` private attribute on `LifecycleMixin` already stores this string — the implementation surfaces it, not invents it
- WebSocket schema freshness is enforced by CI (`tools/check_schemas_fresh.py`) and the pre-push hook
- The TypeScript WS types are hand-authored and validated against the generated schema by a CI conformance test

## Architecture

### Data flow

The readiness data already exists internally — `LifecycleMixin._ready_reason` stores the phase string, `ready_event.is_set()` stores the boolean. The work is threading these values through the event pipeline:

```
LifecycleMixin (is_ready(), _ready_reason)
  → ServiceStatusPayload (ready: bool, ready_phase: str | None)     [events/hassette.py]
    → ServiceStatusData (ready: bool, ready_phase: str | None)      [core/domain_models.py]
      → ws-schema.json (generated)                                  [frontend/ws-schema.json]
        → WsServiceStatusPayload (ready: boolean, ready_phase)      [frontend/src/api/ws-types.ts]
          → ServiceStatusEntry (ready: boolean, ready_phase)        [frontend/src/state/create-app-state.ts]
            → ServiceStatusPanel (amber "Starting" + phase text)    [frontend/src/components/dashboard/]
```

### Backend changes

**`ServiceStatusPayload`** (`src/hassette/events/hassette.py`): Add `ready: bool = False` and `ready_phase: str | None = None` fields. Add corresponding parameters to `HassetteServiceEvent.from_data()`.

**`LifecycleMixin._create_service_status_event()`** (`src/hassette/resources/mixins.py`): Add `ready` and `ready_phase` parameters, defaulting to `False` and `None`. Thread `self.is_ready()` and `self._ready_reason` through every call site in the lifecycle transition methods (`handle_running`, `handle_stop`, `handle_failed`, `handle_starting`, `handle_crash`).

**Readiness-change event emission**: `mark_ready()` and `mark_not_ready()` remain side-effect-free synchronous state primitives — they do NOT emit events. Event emission stays in async contexts that already emit:

- **Lifecycle transitions** (`handle_running`, `handle_stop`, etc.) already emit `service_status` events. They now include `ready=self.is_ready()` and `ready_phase=self._ready_reason` in those events. No new emission points needed here.
- **Mid-operation readiness changes** (e.g., WebSocket disconnects/reconnects inside `serve()`): The service calls `mark_not_ready()` / `mark_ready()` as before, then explicitly calls `await self._emit_readiness_event()` — a new async helper on `Resource` that constructs and sends a `service_status` event with the current readiness state. This helper is called from the service's own async `serve()` context, so there is no sync/async mismatch.

This preserves `LifecycleMixin`'s contract as a side-effect-free readiness primitive and keeps all event emission in the `Resource` layer where the hassette context is available.

**`ServiceStatusData`** (`src/hassette/core/domain_models.py`): Add `ready: bool = False` and `ready_phase: str | None = None`.

**`RuntimeQueryService._on_service_status()`** (`src/hassette/core/runtime_query_service.py`): Map `data.ready` and `data.ready_phase` through to the `ServiceStatusData` constructor.

### Frontend changes

**`WsServiceStatusPayload`** (`frontend/src/api/ws-types.ts`): Add `ready: boolean` and `ready_phase: string | null`.

**`ServiceStatusEntry`** (`frontend/src/state/create-app-state.ts`): Add `ready: boolean` and `ready_phase: string | null`.

**`use-websocket.ts`** service_status handler: Map `msg.data.ready ?? false` and `msg.data.ready_phase ?? null` into the state entry. The nullish-coalescing guards ensure null-safety against buffered pre-schema events that lack these fields.

**`ServiceStatusPanel`** (`frontend/src/components/dashboard/service-status-panel.tsx`):
- Update the filter: a service is visible if its status is non-healthy OR if its status is `"running"` and `ready` is `false`.
- Add `"Starting"` to `STATUS_LABELS` for the running-but-not-ready case.
- When `ready_phase` is non-null, display it as secondary detail text: "Starting — Connecting to HA..."
- Clear `serviceStatus` state on WS reconnect (alongside the existing `logs.clear()`), accepting a brief flash of empty state while fresh events arrive.

**`readinessVariant` helper** (`frontend/src/utils/status.ts`): Add `readinessVariant(status: string, ready: boolean): Variant` that encapsulates the combined variant logic: if `status === "running" && !ready` return `"warning"`, else return `statusToVariant(status)`. `ServiceRow` and any future readiness-aware component (splash screen #615, status bar) call this helper instead of `statusToVariant` directly.

### Design token usage

- Amber indicator for "Starting" state uses `--ht-warning` for the dot and `--ht-warning-light` for any badge background, consistent with the existing EXHAUSTED_COOLING treatment
- Phase detail text uses `--ht-text-secondary` and `--ht-text-sm` (14px), matching the existing retry countdown detail text
- Font: phase text in DM Sans (body text), not monospace — it's a human-readable description, not a data value

## Alternatives Considered

### Binary `ready: bool` only (no phase string)

Simpler implementation — one field instead of two. Rejected because:
- The research briefs recommend structured status (`{"phase": "connecting_to_ha"}`) for the splash screen
- A bare "Starting" indicator gives no diagnostic value — the operator can't tell if WebSocket is connecting, authenticating, or subscribing
- The phase data already exists internally (`_ready_reason`) — not surfacing it wastes available information

### Per-service readiness phase enums

Each service defines its own enum of phases (e.g., `WebSocketPhase.CONNECTING`, `WebSocketPhase.AUTHENTICATING`). Rejected because:
- Requires each service to maintain a typed phase enum alongside its implementation
- The frontend would need to know about every service's phases to render them meaningfully
- The freeform string approach achieves the same UI result with zero coupling between services and the display layer

### Three-tier readiness enum (NOT_READY / DEGRADED / READY)

Adds a "partially functional" middle state. Rejected because:
- "Degraded" is hard to define consistently across services — what's partially functional for WebSocket (connected but some subscriptions failed) doesn't apply to FileWatcher
- Two of three tiers (NOT_READY and READY) map directly to the boolean; the third is a special case that can be modeled as a phase string if a service needs it later

## Test Strategy

**Unit tests — backend:**
- `ServiceStatusPayload` construction with `ready` and `ready_phase` fields (both default and explicit values)
- `_create_service_status_event()` passes `ready` and `ready_phase` through to the payload
- `handle_running()` includes `ready=self.is_ready()` and `ready_phase=self._ready_reason` in the emitted event
- `Resource._emit_readiness_event()` sends a `service_status` event with current readiness state
- `mark_ready()` and `mark_not_ready()` do NOT emit events (remain side-effect-free)
- `RuntimeQueryService._on_service_status()` maps `ready` and `ready_phase` through to `ServiceStatusData`
- `ServiceWatcher._emit_service_status_event()` passes `ready=False, ready_phase=None` explicitly

**Unit tests — frontend:**
- `use-websocket.ts` service_status handler maps `ready` and `ready_phase` into the `serviceStatus` state entry (verifies the explicit field mapping includes both new fields with correct defaults)
- `ServiceStatusPanel` renders nothing when all services are running and ready (current behavior preserved)
- `ServiceStatusPanel` shows an amber "Starting" row for a running service with `ready=false`
- `ServiceStatusPanel` displays `ready_phase` as detail text when present
- `ServiceStatusPanel` shows "Starting" with no detail when `ready_phase` is null
- `ServiceStatusPanel` hides a running service when `ready=true` (healthy)
- Existing exhausted/failed/crashed rendering is unaffected

**Schema conformance:** The existing CI check (`tools/check_schemas_fresh.py`) validates `ws-schema.json` matches the Pydantic models, and the TS conformance test validates `ws-types.ts` matches the schema.

## Documentation Updates

- Docstrings on `ServiceStatusPayload`, `ServiceStatusData`, and `HassetteServiceEvent.from_data()` updated to document the new fields
- Docstring on `Resource._emit_readiness_event()` documenting when services should call it (after `mark_ready()` / `mark_not_ready()` in async `serve()` contexts for mid-operation readiness changes)

## Impact

**Backend files modified:**
- `src/hassette/events/hassette.py` — `ServiceStatusPayload` and `HassetteServiceEvent.from_data()`
- `src/hassette/resources/mixins.py` — `LifecycleMixin._create_service_status_event()` (add `ready` and `ready_phase` parameters)
- `src/hassette/resources/base.py` — `Resource._emit_readiness_event()` (new async helper for mid-operation readiness changes)
- `src/hassette/core/domain_models.py` — `ServiceStatusData`
- `src/hassette/core/runtime_query_service.py` — `_on_service_status()`
- `src/hassette/core/service_watcher.py` — `_emit_service_status_event()` and synthetic event sites must pass `ready=False, ready_phase=None` explicitly (ServiceWatcher constructs `ServiceStatusPayload` directly, bypassing `from_data()`; without explicit fields, exhaustion events would rely on dataclass defaults — correct by coincidence but an undocumented invariant)
- `src/hassette/core/websocket_service.py` — call `_emit_readiness_event()` after `mark_ready()` / `mark_not_ready()` in `serve()` reconnect paths

**Frontend files modified:**
- `frontend/ws-schema.json` — regenerated
- `frontend/src/api/ws-types.ts` — `WsServiceStatusPayload`
- `frontend/src/state/create-app-state.ts` — `ServiceStatusEntry`
- `frontend/src/hooks/use-websocket.ts` — service_status message handler
- `frontend/src/components/dashboard/service-status-panel.tsx` — filter logic and rendering

<!-- Gap check 2026-05-02: 7 gaps included — test_ws_models.py ServiceStatusPayload constructions → WP01 subtask update, test_service_watcher.py direct ServiceStatusPayload → WP01 subtask update, test_session_manager.py direct ServiceStatusPayload → WP01 subtask update, service-status-panel.test.tsx makeEntry() → WP03 test strategy, status.test.ts readinessVariant → WP03 test strategy, simulation.py simulate_hassette_service_status → WP01 subtask 10, status.ts readinessVariant → WP03 subtask 5 -->
**Blast radius:** Moderate. The change is additive — new fields with safe defaults. All existing event consumers receive the new fields but are unaffected if they don't read them. The only behavioral change is in `ServiceStatusPanel`, which now shows a new "Starting" state. Existing states (failed, crashed, exhausted) are untouched.

**Known limitation:** Service readiness state requires an active WS connection. A browser loading the page mid-reconnect starts with empty `serviceStatus` and will not see readiness indicators until the next WS event. The REST snapshot endpoint planned for #615 (splash screen) will address cold-load visibility.

## Open Questions

None — all design decisions are resolved.
