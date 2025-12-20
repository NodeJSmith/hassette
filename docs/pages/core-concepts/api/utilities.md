# Utilities & History

Beyond basic states and services, the API exposes advanced Home Assistant features.

## Templates

Render Jinja2 templates on the server.

```python
--8<-- "pages/core-concepts/api/snippets/api_template.py"
```

## History

Fetch historical state data.

```python
--8<-- "pages/core-concepts/api/snippets/api_history.py"
```

## Logbook

Retrieve logbook entries.

```python
--8<-- "pages/core-concepts/api/snippets/api_logbook.py"
```

## Other Endpoints

- **`fire_event`**: Fire a custom event on the HA bus.
- **`get_calendars`**: List available calendars.
- **`get_calendar_events`**: Fetch events from a calendar.
- **`set_state`**: Set a synthetic state (useful for testing or virtual sensors).
