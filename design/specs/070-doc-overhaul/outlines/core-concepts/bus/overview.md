# Bus

**Status:** Rewrite from blank
**Voice mode:** Concept — system-as-subject, no "you"
**Page type:** Concept (landing page)
**Reader's job:** Understand what the bus does and learn the basic patterns for subscribing to events.

## What was cut (and where it goes)

- Synchronous usage (`BusSyncFacade`) was listed in the previous outline but never written. It belongs as a callout or collapsible section on this page, not a full H2 — most readers use async and don't need it until they hit `AppSync` hooks. One paragraph with a link to the Apps page suffices.

## Outline

### H2: Subscribing to Events
The core job: register a handler, receive typed data. One code example showing `on_state_change` with DI. Then the four-method table (`on_state_change`, `on_attribute_change`, `on_call_service`, `on`). Mention `name=` is required. Link to Handlers for the full event type catalog.

### H2: Matching Multiple Entities
Glob patterns for entity IDs, domains, and services. Short snippet showing `"light.*"` and `"sensor.bedroom_*"`. One warning: globs match identifiers only, not attribute names or data values — link to Filtering for those.

### H2: Rate Control
Three parameters that limit handler invocation frequency, each with a one-sentence explanation and a minimal snippet:
- `debounce` — wait until quiet for N seconds
- `throttle` — at most once per N seconds
- `once=True` — fire once then auto-cancel

Warning: mutually exclusive.

### H2: Synchronous Usage
One paragraph: `self.bus.sync` (`BusSyncFacade`) mirrors all subscription methods as blocking calls for `AppSync` hooks. Link to Apps page.

### H2: Next Steps
Links to: Handlers, Filtering, Dependency Injection.

## Snippet Inventory

| Snippet | Decision | Notes |
|---|---|---|
| `bus_basic_subscribe.py` | Keep | DI-first subscription example |
| `bus_glob_patterns.py` | Keep | Glob pattern matching |
| `bus_rate_control.py` | Keep | Three section markers (debounce, throttle, once) |

No new snippets needed.

## Cross-Links

- **Links to:** Handlers, DI, Filtering, States/Subscribing, Scheduler overview
- **Linked from:** Architecture, Apps overview, First Automation
