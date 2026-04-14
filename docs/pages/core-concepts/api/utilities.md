# Utilities & History

Beyond basic states and services, the API exposes advanced Home Assistant features.

## Templates

Render Jinja2 templates on the server. Use this when you need to evaluate expressions that HA already knows how to compute — such as averaging across all sensors of a certain class, or evaluating a complex conditional — without pulling all the raw data into Python first.

```python
--8<-- "pages/core-concepts/api/snippets/api_template.py"
```

You can pass a `variables` dict as the second argument to inject values into the template context, keeping the template string reusable across calls.

## History

Fetch the recorded state changes for an entity over a time window. This is useful for trend analysis, energy reporting, or building automations that depend on what a sensor was doing hours ago, not just its current value.

```python
--8<-- "pages/core-concepts/api/snippets/api_history.py"
```

Use `get_histories` (plural) to fetch multiple entities in one request. Passing a comma-separated string to `get_history` raises a `ValueError`. Both methods accept optional flags: `significant_changes_only` (skip minor attribute-only updates), `minimal_response` (omit attributes from all but the last entry), and `no_attributes` (strip attributes entirely for smaller payloads).

## Logbook

Retrieve logbook entries for an entity — the human-readable log HA shows in the UI. This captures state changes and automation triggers in a format suited for displaying activity summaries to users.

```python
--8<-- "pages/core-concepts/api/snippets/api_logbook.py"
```

Unlike `get_history`, both `start_time` and `end_time` are required.

## Other Endpoints

### `fire_event`

Fire a custom event onto the Home Assistant event bus. Any automation or integration listening for that event type will respond to it. Use this to trigger HA automations from Hassette, or to communicate between apps via HA's native event system.

```python
await self.api.fire_event("custom_event", {"source": "my_app", "value": 42})

# event_data is optional
await self.api.fire_event("hassette_ready")
```

### `set_state`

Write a synthetic state to HA's state machine. This creates or updates a state entry in HA's UI and REST API, but it does not control a real device — HA integrations do not react to it the way they react to `call_service`. Use it for virtual sensors, exposing computed values to the HA dashboard, or sharing state between apps via HA's state machine.

```python
await self.api.set_state("sensor.custom_score", "87", {"unit_of_measurement": "%"})
```

Existing attributes are merged: any attributes you pass are overlaid on top of the current ones, so you only need to provide the keys you want to change.

!!! note "Synthetic states are not persisted across HA restarts"
    States written with `set_state` live in HA's in-memory state machine. They are lost when HA restarts unless you restore them in `on_initialize`.

### `get_calendars`

List all calendar entities registered in Home Assistant.

```python
calendars = await self.api.get_calendars()
for cal in calendars:
    print(cal["entity_id"], cal.get("name"))
```

### `get_calendar_events`

Fetch events from a specific calendar within a time window.

```python
start = self.now()
end = self.now().add(days=7)
events = await self.api.get_calendar_events("calendar.work", start, end)
for event in events:
    print(event["summary"], event["start"])
```

## See Also

- [Retrieving Entities & States](entities.md) - Get entity and state data
- [Calling Services](services.md) - Invoke Home Assistant services
- [App Cache](../cache/index.md) - Cache data locally across restarts
