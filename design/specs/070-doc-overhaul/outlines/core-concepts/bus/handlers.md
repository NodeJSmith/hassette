# Bus — Writing Handlers

**Status:** Exists (192 lines), needs restructuring to remove DI overlap
**Voice mode:** Concept — system-as-subject, no "you"

## Outline

### H2: Event Model
What events look like: `RawStateChangeEvent`, `CallServiceEvent`, `Event`. The event dict structure.

### H2: Raw Event Handlers
Handlers that receive the raw event dict. When to use: rare cases where DI doesn't cover the need, or when processing bulk events. Show the pattern.

### H2: Non-State Event Types
Cover event types beyond state changes:
- `on_call_service` — reacting to service calls
- `on_service_registered` — reacting to new HA service registrations
- `on` — subscribing to raw HA event types (e.g., `event_triggered`, `automation_triggered`)
- `on_component_loaded` — HA component load events
- HA startup/shutdown events (`on_homeassistant_start`, `on_homeassistant_stop` — wrappers around `on_call_service` for `homeassistant` domain)
- Hassette internal events — typed helpers: `on_hassette_service_status`, `on_hassette_service_failed`, `on_hassette_service_crashed`, `on_hassette_service_started`, `on_websocket_connected`, `on_websocket_disconnected`, `on_app_state_changed`, `on_app_running`, `on_app_stopping`
- `Bus.emit()` for broadcasting Hassette-internal events between apps

### H2: Error Handling
#### H3: App-Level Error Handler
`Bus.on_error()` registration method.
#### H3: Per-Registration Error Handler
`on_error=` parameter on subscription methods.
#### H3: What `BusErrorContext` Contains
Fields: `topic`, `listener_name`, `event`, plus inherited fields from `ErrorContext` (`exception`, `traceback`).

### H2: Timeout Configuration
`timeout=` and `timeout_disabled=` options on subscription methods.

### H2: Subscription Mechanics
#### H3: The `name=` Parameter (Required)
Why it's required, what it's used for (telemetry, logging, idempotent registration).
#### H3: Registration Is Complete When the Awaited Call Returns
`db_id` is immediately valid. No background registration task.
#### H3: Sequential Operations Are Deterministic
Registration order guarantees.

## Snippet Inventory

| Snippet | Status | Notes |
|---|---|---|
| `handlers_no_data.py` | Keep | Raw handler example |
| `handlers_extract_data.py` | Review | May overlap with DI page — reassign if so |
| `handlers_multiple_dependencies.py` | Review | Likely belongs on DI page now |
| `handlers_custom_args.py` | Review | May belong on DI page (custom kwargs) |
| `bus_error_handler_app.py` | Keep | App-level error handler |
| `bus_error_handler_per_reg.py` | Keep | Per-registration error handler |
| `bus_subscription_patterns.py` | Keep | Subscription mechanics |
| `bus_registration_identity.py` | Keep | name= parameter, identity |
| `bus_timeouts.py` | Keep | Timeout configuration |
| `first_automation_step3_raw.py` (from getting-started) | New claim | Raw handler example from getting-started, now lives here |

**New snippets needed:**
- Non-state event handler examples (on_call_service, on("event_triggered"), internal events, HA lifecycle events)

## Cross-Links

- **Links to:** DI page (for typed annotations), Filtering (for predicates), States/Subscribing (for state-specific patterns)
- **Linked from:** Bus overview, Apps overview
