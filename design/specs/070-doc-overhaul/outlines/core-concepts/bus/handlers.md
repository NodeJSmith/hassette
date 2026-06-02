# Writing Event Handlers

**Status:** Rewrite from blank
**Voice mode:** Concept — system-as-subject, no "you"
**Page type:** Concept
**Reader's job:** Write a handler that receives the right data, handles errors, and registers correctly.

The existing page mixes three concerns: how to write handlers, how DI works, and how registration works. Readers come here for one of two reasons: "how do I get data into my handler?" or "how do I handle errors and register reliably?" The DI details already have a dedicated page. This page should show the handler patterns (raw through DI), then cover the operational concerns (errors, timeouts, registration mechanics).

## What was cut (and where it goes)

- **DI annotation details** (combining multiple deps, available annotations, union types, custom kwargs) — already on the DI page. This page shows the progression from raw to DI, then links there for the full reference. Snippets `handlers_extract_data.py`, `handlers_multiple_dependencies.py`, and `handlers_custom_args.py` are reviewed below for overlap.
- **Non-state event types** were listed in the previous outline but never existed in the page. This is a catalog of subscription methods, not handler-writing guidance. Move to a new section on this page that covers "what events can handlers receive?" as a brief table with links. The detailed method signatures already live in the Bus class API reference.

## Outline

### H2: Handler Patterns
The simplest-first progression. Each pattern gets a snippet and a one-sentence explanation of when to use it:
1. **No data needed** — handler takes no event params. Use for side-effect-only reactions.
2. **Raw event** — handler receives the untyped `Event` object. Use when exploring or when DI doesn't cover the event type.
3. **Typed state event** — handler receives `D.TypedStateChangeEvent[T]`. Use when both old and new states are needed together.
4. **Extracted data (recommended)** — handler receives specific fields via DI annotations (`D.StateNew[T]`, `D.EntityId`, etc.). Production default.

Link to DI page for the full annotation reference and advanced patterns.

### H2: Non-State Event Types
Brief table of subscription methods beyond `on_state_change`:
- `on_attribute_change` — attribute value changes
- `on_call_service` — HA service calls
- `on_component_loaded` — HA component loads
- `on_service_registered` — new HA service registrations
- `on_homeassistant_start` / `on_homeassistant_stop` / `on_homeassistant_restart` — HA lifecycle
- `on` — any raw HA event topic
- `emit()` — Hassette-internal broadcast between apps

Hassette-internal event helpers (one table): `on_hassette_service_status`, `on_hassette_service_failed`, `on_hassette_service_crashed`, `on_hassette_service_started`, `on_websocket_connected`, `on_websocket_disconnected`, `on_app_state_changed`, `on_app_running`, `on_app_stopping`.

### H2: Error Handling
#### H3: App-Level Error Handler
`bus.on_error(handler)` — applies to all listeners without a per-registration handler. Register as the first statement in `on_initialize()` to avoid the reload gap.
#### H3: Per-Registration Error Handler
`on_error=` parameter on subscription methods — takes precedence over app-level.
#### H3: What `BusErrorContext` Contains
Table: `topic`, `listener_name`, `event`, plus `exception` and `traceback` from `ErrorContext` base.

### H2: Timeout Configuration
`timeout=` overrides the global default per listener. `timeout_disabled=True` disables enforcement entirely. Brief snippet.

### H2: Registration Mechanics
#### H3: The `name=` Parameter
Required on all DB-registered listeners. Natural key: `(app_key, instance_index, name, topic)`. `ListenerNameRequiredError` when omitted. `DuplicateListenerError` when colliding within a session.
#### H3: Registration Completes Synchronously
`db_id` is valid immediately when the awaited call returns. No background task.
#### H3: Sequential Operations Are Deterministic
Cancel-then-resubscribe has no race conditions.

## Snippet Inventory

| Snippet | Decision | Notes |
|---|---|---|
| `handlers_no_data.py` | Keep | Pattern 1 |
| `handlers_raw_event.py` | Keep | Pattern 2 |
| `handlers_typed_event.py` | Keep | Pattern 3 |
| `handlers_extract_data.py` | Keep | Pattern 4 — brief DI example here, full details on DI page |
| `handlers_multiple_dependencies.py` | Drop from this page | Lives on DI page |
| `handlers_custom_args.py` | Drop from this page | Lives on DI page (`mixing_kwargs.py`) |
| `bus_error_handler_app.py` | Keep | Error handling |
| `bus_error_handler_per_reg.py` | Keep | Error handling |
| `bus_subscription_patterns.py` | Keep | Registration mechanics |
| `bus_registration_identity.py` | Keep | name= parameter |
| `bus_timeouts.py` | Keep | Timeout config |

**New snippets needed:**
- Non-state event handler examples (at least one `on_call_service` handler snippet, one `on("event_type")` snippet, one Hassette-internal event snippet)

## Cross-Links

- **Links to:** DI page (annotation reference), Filtering (predicates), States/Subscribing (state-specific patterns)
- **Linked from:** Bus overview, Apps overview
