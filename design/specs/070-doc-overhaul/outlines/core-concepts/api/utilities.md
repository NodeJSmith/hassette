# API — Utilities

**Status:** Rewrite from blank
**Voice mode:** Concept — system-as-subject, no "you"
**Page type:** Concept (reference-leaning)
**Reader's job:** Find the right API method for a less common task — rendering a template, fetching history, firing an event, writing a synthetic state, or querying calendars.

## What was cut (and where it goes)

- **Discovery methods** (`get_config`, `get_services`, `get_panels`) — cut from the outline. These are rarely used in automations and are better served by the API reference (mkdocstrings). Mentioning them in a "Discovery" collapsible adds clutter for a page where most readers want templates or history.
- **"Other Endpoints" grab-bag heading** — dissolved. Each method now has a short, descriptive heading that tells the reader what it does, not where it lives in the API surface.

## Outline

### H2: (Opening — no heading)
One sentence: beyond states and services, the API exposes templates, history, calendars, and event-firing. This page covers the less frequent but still useful methods.

### H2: Templates
`render_template(template, variables=None)` evaluates a Jinja2 template on the HA server. Useful when HA already knows how to compute something (averaging sensors, complex conditionals) and pulling all raw data into Python would be wasteful.

Snippet: template rendering with variables.

### H2: History
`get_history(entity_id, start_time, end_time)` retrieves recorded state changes for one entity. Useful for trend analysis, energy reporting, or automations that depend on past sensor readings.

`get_histories(entity_ids, start_time, end_time)` for batch retrieval. Passing a comma-separated string to `get_history` raises `ValueError`.

Optional flags: `significant_changes_only`, `minimal_response`, `no_attributes`.

Snippet: history retrieval.

### H2: Logbook
`get_logbook(entity_id, start_time, end_time)` retrieves human-readable log entries. Both `start_time` and `end_time` are required (unlike `get_history` where `end_time` is optional).

Snippet: logbook query.

### H2: Firing Events
`fire_event(event_type, **data)` sends an event to HA's event bus. Any HA automation or integration subscribed to that event type receives it.

Note callout: for in-process broadcast between Hassette apps, use `self.bus.emit()` instead — it stays local, is faster, and keeps data typed.

Snippet: fire_event.

### H2: Writing Synthetic State
`set_state(entity_id, state, attributes=None)` writes a state entry to HA's state machine. Does not control a real device — use it for virtual sensors, exposing computed values to the HA dashboard, or sharing state between apps via HA.

Existing attributes are merged: only pass keys to change.

Note callout: synthetic states are not persisted across HA restarts. Restore them in `on_initialize` if needed.

Snippet: set_state.

### H2: Calendars
`get_calendars()` lists all calendar entities. `get_calendar_events(calendar_id, start_time, end_time)` fetches events within a time window.

Snippet: calendar query.

## Snippet Inventory

| Snippet | Decision | Notes |
|---|---|---|
| `api_template.py` | Keep | Template rendering |
| `api_history.py` | Keep | History retrieval |
| `api_logbook.py` | Keep | Logbook query |
| `api_utilities.py` | Keep | fire_event, set_state, calendars (section markers) |

## Cross-Links

- **Links to:** API overview, Bus (emit for in-process events), Apps overview (on_initialize for restoring set_state), Cache (for persisting data across restarts)
- **Linked from:** API overview
