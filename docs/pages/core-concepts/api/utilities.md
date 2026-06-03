# Utilities

Beyond states and services, the API exposes templates, history, logbook entries, event firing, synthetic state writing, and calendar access. These methods handle the less frequent tasks that don't fit the core state-and-service model.

## Templates

`render_template` evaluates a Jinja2 template string on the Home Assistant server and returns the result as a string. Template evaluation runs server-side, so the full HA template environment is available: `states`, `is_state`, sensor aggregations, and every other built-in helper.

```python
--8<-- "pages/core-concepts/api/snippets/api_template.py"
```

The optional `variables` parameter injects a dict of values into the template context. The same template string stays reusable across calls with different inputs.

Template evaluation is most useful when HA already knows how to compute something complex (averaging across a device class, evaluating multi-sensor conditionals) and pulling all the raw data into Python would be wasteful.

## History

`get_history` retrieves recorded state changes for a single entity over a time window. The `start_time` parameter is required. The `end_time` parameter is optional; omitting it returns changes from `start_time` to the present.

```python
--8<-- "pages/core-concepts/api/snippets/api_history.py"
```

`get_histories` fetches multiple entities in a single request. It accepts a `list[str]` and returns a `dict` mapping each entity ID to its history entries. Passing a comma-separated string to `get_history` raises a `ValueError`.

Both methods accept three optional flags for reducing payload size:

- `significant_changes_only` — skips minor attribute-only updates, returning only state-string transitions
- `minimal_response` — omits attributes from all but the last entry in each entity's list
- `no_attributes` — strips attributes entirely from every entry

## Logbook

`get_logbook` retrieves the human-readable log entries that Home Assistant records for an entity. Logbook entries capture state changes and automation triggers in the format HA displays in its UI. They are useful for building activity summaries or audit trails.

```python
--8<-- "pages/core-concepts/api/snippets/api_logbook.py"
```

Both `start_time` and `end_time` are required. This differs from `get_history`, where `end_time` is optional.

## Firing Events

`fire_event` sends an event to Home Assistant's event bus. Any HA automation, integration, or component subscribed to that event type receives it.

```python
--8<-- "pages/core-concepts/api/snippets/api_utilities.py:fire_event"
```

The `event_data` parameter is optional. When omitted, the event fires with no payload.

!!! note "In-process broadcast between apps"
    `fire_event` leaves the framework. The event travels to Home Assistant and back. For broadcasting between Hassette apps in the same process, [`self.bus.emit()`](../bus/index.md) stays local, fires faster, and keeps the data typed end-to-end.

## Writing Synthetic State

`set_state` writes a state entry to Home Assistant's in-memory state machine. The entry appears in the HA dashboard and REST API like any other entity state, but it does not control a real device. HA integrations do not react to it the way they react to `call_service`.

```python
--8<-- "pages/core-concepts/api/snippets/api_utilities.py:set_state"
```

Attributes are merged: `set_state` reads the entity's current attributes and overlays only the keys passed in `attributes`. Existing keys not mentioned in the call are preserved.

Typical uses include virtual sensors that expose computed values to the dashboard, and sharing derived state between apps via HA's state machine.

!!! note "Synthetic states do not survive HA restarts"
    States written with `set_state` live in HA's in-memory state machine. They are lost when HA restarts. Apps that need persistence across restarts can re-create them in `on_initialize`.

## Calendars

`get_calendars` returns all calendar entities registered in Home Assistant. `get_calendar_events` fetches events from a specific calendar within a time window. Both `start_time` and `end_time` are required for `get_calendar_events`.

```python
--8<-- "pages/core-concepts/api/snippets/api_utilities.py:get_calendars"
```

```python
--8<-- "pages/core-concepts/api/snippets/api_utilities.py:get_calendar_events"
```

## See Also

- [API Overview](index.md) — the full `self.api` surface
- [Retrieving Entities & States](entities.md) — reading current state without history
- [Calling Services](services.md) — controlling real devices
- [`Bus`](../bus/index.md) — in-process event broadcast between apps
- [App Cache](../cache/index.md) — persisting data across HA restarts
