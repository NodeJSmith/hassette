# API Methods

[`Api`][hassette.api.Api] methods organized by task. Every method is `async` and requires `await`. See the [API overview](index.md) for when-to-use guidance and error handling.

---

## Reading State

### Which method to use

| Need | Method |
|---|---|
| Just the raw state string | `get_state_value` |
| Typed value without a full state object | `get_state_value_typed` |
| Typed value, attributes, and timestamps | `get_state` |
| Domain action methods (`turn_on`, `turn_off`, `toggle`) | `get_entity` |
| Check whether an entity exists | `get_state_or_none` or `entity_exists` |
| Raw HA payload dict | `get_state_raw` |
| Single attribute by name | `get_attribute` |
| All entities at once | `get_states` |

### `get_state_value(entity_id)`

Returns the raw state string for an entity. This is the value Home Assistant stores in its
state machine: `"on"`, `"23.5"`, `"above_horizon"`. No attributes, no timestamps, no type
conversion.

```python
--8<-- "pages/core-concepts/api/snippets/api_get_state_value.py"
```

This is the cheapest state call when the value string is all the code needs.

### `get_state(entity_id)`

Returns a typed [`BaseState`][hassette.models.states.base.BaseState] subclass matched to the entity's
domain. The `.value` field is coerced to the domain's Python type: `bool` for lights and switches,
`float` for numeric sensors, `str` for most others. The object includes `.attributes`,
`.last_changed`, `.last_updated`, and `.context`.

```python
--8<-- "pages/core-concepts/api/snippets/api_get_state.py"
```

Raises `EntityNotFoundError` when the entity does not exist.

### `get_state_or_none(entity_id)` / `entity_exists(entity_id)`

`get_state_or_none` returns `None` instead of raising when the entity is absent.
`entity_exists` returns a plain `bool`.

```python
--8<-- "pages/core-concepts/api/snippets/api_check_existence.py"
```

### `get_state_raw(entity_id)`

Returns the untyped `HassStateDict` from the REST response. Use this when working outside the type
registry or inspecting the raw HA payload for debugging.

```python
--8<-- "pages/core-concepts/api/snippets/api_get_state_raw.py"
```

### `get_state_value_typed(entity_id)`

Returns the state value converted to the domain's Python type — like `get_state`, but without
fetching attributes or timestamps.

```python
--8<-- "pages/core-concepts/api/snippets/api_get_state_value_typed.py"
```

!!! note "`SensorState` value type is always `str`"
    Sensors are `str` even when the sensor represents a number, because Hassette cannot determine the
    numeric type without additional context. Convert manually with `float(value)` or `int(value)`.
    `binary_sensor` returns `bool`. `light` and `switch` return `bool`.

### `get_attribute(entity_id, attribute)`

Returns a single attribute value. `attribute` supports dot-path notation for nested fields
(`"color_modes.0"`). Returns the `MISSING_VALUE` sentinel when the attribute is absent rather than
raising.

| Parameter | Type | Default | Description |
|---|---|---|---|
| `entity_id` | `str` | — | Entity ID. |
| `attribute` | `str` | — | Attribute name, or dot-separated path for nested access. |

```python
--8<-- "pages/core-concepts/api/snippets/api_get_attribute.py"
```

The return value should be compared against `MISSING_VALUE` before use. A truthiness check
alone is unreliable because some valid attribute values are falsy (`0`, `False`, `""`).

### `get_entity(entity_id, model)` / `get_entity_or_none(entity_id, model)`

Wraps a state in a [`BaseEntity`][hassette.models.entities.base.BaseEntity] subclass. An entity
adds domain-specific action methods to the state snapshot: `turn_on()`, `turn_off()`, `toggle()`,
and `refresh()`. The `model` argument specifies which entity class to use.

| Parameter | Type | Default | Description |
|---|---|---|---|
| `entity_id` | `str` | — | Entity ID. |
| `model` | `type[EntityT]` | — | A `BaseEntity` subclass (e.g., `entities.LightEntity`). |

```python
--8<-- "pages/core-concepts/api/snippets/api_get_entity.py"
```

`entity.refresh()` re-fetches the entity's state from Home Assistant and replaces `.state`
with the new snapshot. The updated state is also returned.

`get_entity_or_none` returns `None` when the entity is not found, following the same pattern as
`get_state_or_none`.

### `get_states()` / `get_states_raw()`

`get_states()` retrieves all entities in a single call and returns them as a list of typed
`BaseState` objects. States that fail to convert are skipped and logged as errors.
`get_states_raw()` returns the untyped list instead.

```python
--8<-- "pages/core-concepts/api/snippets/api_get_states.py"
```

Neither method accepts filtering parameters. Filtering happens in Python after the call.

---

## Calling Services

### `call_service(domain, service, ...)`

The generic service call method. Service data passes as keyword arguments — they become
`service_data` on the wire.

| Parameter | Type | Default | Description |
|---|---|---|---|
| `domain` | `str` | — | Service domain (e.g., `"light"`). |
| `service` | `str` | — | Service name (e.g., `"turn_on"`). |
| `target` | `dict \| None` | `None` | Target entity IDs, areas, or devices. |
| `return_response` | `bool` | `False` | When `True`, returns the service response payload. |
| `**data` | `Any` | — | Service data fields passed as keyword arguments. |

```python
--8<-- "pages/core-concepts/api/snippets/api_call_service.py"
```

### `turn_on(entity_id, domain, **data)` / `turn_off(...)` / `toggle_service(...)`

Shorthands for the most common service calls. Each accepts an entity ID and dispatches the
corresponding service.

| Parameter | Type | Default | Description |
|---|---|---|---|
| `entity_id` | `str \| StrEnum` | — | Entity to target. |
| `domain` | `str` | `"homeassistant"` | Service domain to route the call to. |

`turn_on` also accepts `**data` keyword arguments, so light-specific fields like
`brightness` and `color_name` pass through to the service call. `turn_off` and
`toggle_service` do not accept extra data.

```python
--8<-- "pages/core-concepts/api/snippets/api_helpers.py"
```

!!! warning "HA 2024.x deprecated `homeassistant.*` generic services"
    The default `domain="homeassistant"` routes to `homeassistant.turn_on`, which Home Assistant
    deprecated in 2024.x. Pass `domain="light"`, `domain="switch"`, or the appropriate domain to
    route to the domain-specific service instead.

### Getting a response

Some services return data. `weather.get_forecasts` returns forecast arrays; `conversation.process`
returns a reply. Set `return_response=True` to include the response payload. Without it,
`call_service` returns `None`.

```python
--8<-- "pages/core-concepts/api/snippets/api_response.py"
```

---

## History & Logbook

### `get_history(entity_id, start_time, end_time=None, ...)`

Returns recorded state changes for a single entity over a time window. `start_time` is required.
Omitting `end_time` returns changes from `start_time` to the present.

| Parameter | Type | Default | Description |
|---|---|---|---|
| `entity_id` | `str` | — | Single entity ID. Comma-separated strings raise `ValueError`. |
| `start_time` | `PlainDateTime \| ZonedDateTime \| Date \| str` | — | Start of the time window. |
| `end_time` | `PlainDateTime \| ZonedDateTime \| Date \| str \| None` | `None` | End of the time window. `None` means now. |
| `significant_changes_only` | `bool` | `False` | Skips attribute-only updates; returns state-string transitions only. |
| `minimal_response` | `bool` | `False` | Omits attributes from all but the last entry per entity. |
| `no_attributes` | `bool` | `False` | Strips attributes entirely from every entry. |

```python
--8<-- "pages/core-concepts/api/snippets/api_history.py"
```

The three payload flags (`significant_changes_only`, `minimal_response`, `no_attributes`) reduce
response size for long time windows or large attribute sets.

### `get_histories(entity_ids, start_time, end_time=None, ...)`

Fetches multiple entities in a single request. `entity_ids` is `list[str]`. Returns a `dict`
mapping each entity ID to its list of history entries. Accepts the same payload-reduction flags
as `get_history`.

`entity_ids` must be a list — passing a comma-separated string to `get_history` raises `ValueError`.

### `get_logbook(entity_id, start_time, end_time)`

Returns human-readable log entries that Home Assistant records for an entity. Logbook entries
capture state changes and automation triggers in the format the HA UI displays.

| Parameter | Type | Default | Description |
|---|---|---|---|
| `entity_id` | `str` | — | Entity ID. |
| `start_time` | `PlainDateTime \| ZonedDateTime \| Date \| str` | — | Start of the time window. |
| `end_time` | `PlainDateTime \| ZonedDateTime \| Date \| str` | — | End of the time window. Required (unlike `get_history`). |

```python
--8<-- "pages/core-concepts/api/snippets/api_logbook.py"
```

Both `start_time` and `end_time` are required. `get_history` makes `end_time` optional;
`get_logbook` does not.

---

## Templates

### `render_template(template, variables=None)`

Evaluates a Jinja2 template string on the Home Assistant server and returns the result as a string.
Template evaluation runs server-side, so the full HA template environment is available: `states`,
`is_state`, sensor aggregations, and every other built-in helper.

| Parameter | Type | Default | Description |
|---|---|---|---|
| `template` | `str` | — | Jinja2 template string. |
| `variables` | `dict \| None` | `None` | Values injected into the template context. |

```python
--8<-- "pages/core-concepts/api/snippets/api_template.py"
```

The `variables` parameter keeps the template string reusable across calls with different inputs.
`render_template` is most useful when HA already knows how to compute something complex
(averaging across a device class, evaluating multi-sensor conditionals). Pulling all the
raw data into Python would be wasteful.

---

## Events & Synthetic State

### `fire_event(event_type, event_data=None)`

Sends an event to Home Assistant's event bus. Any HA automation, integration, or component
subscribed to that event type receives it.

| Parameter | Type | Default | Description |
|---|---|---|---|
| `event_type` | `str` | — | Event type string (e.g., `"my_custom_event"`). |
| `event_data` | `dict \| None` | `None` | Payload attached to the event. |

```python
--8<-- "pages/core-concepts/api/snippets/api_utilities.py:fire_event"
```

!!! note "Broadcasting between Hassette apps"
    `fire_event` leaves the framework. The event travels to Home Assistant and back. For
    broadcasting between apps in the same Hassette process,
    [`self.bus.emit()`](../bus/handlers.md#cross-app-communication) stays local, fires
    faster, and keeps the data typed end-to-end.

### `set_state(entity_id, state, attributes=None)`

Writes a state entry to Home Assistant's in-memory state machine. The entry appears in the HA
dashboard and REST API like any other entity state, but it does not control a real device.

| Parameter | Type | Default | Description |
|---|---|---|---|
| `entity_id` | `str \| StrEnum` | — | Entity ID to write. |
| `state` | `Any` | — | New state value. |
| `attributes` | `dict \| None` | `None` | Attributes to overlay on the current attribute set. |

```python
--8<-- "pages/core-concepts/api/snippets/api_utilities.py:set_state"
```

Attributes are merged: the method reads the entity's current attributes and overlays only the
keys passed in `attributes`. Keys not mentioned in the call are preserved.

!!! note "Synthetic states do not survive HA restarts"
    States written with `set_state` live in HA's in-memory state machine. They are lost when HA
    restarts. Apps that need persistence can re-create them in `on_initialize`.

---

## Calendars & Camera

### `get_calendars()`

Returns all calendar entities registered in Home Assistant as a list of dicts.

```python
--8<-- "pages/core-concepts/api/snippets/api_utilities.py:get_calendars"
```

### `get_calendar_events(calendar_id, start_time, end_time)`

Returns events from a specific calendar within a time window. Both `start_time` and `end_time`
are required.

| Parameter | Type | Default | Description |
|---|---|---|---|
| `calendar_id` | `str` | — | Calendar entity ID (e.g., `"calendar.work"`). |
| `start_time` | `PlainDateTime \| ZonedDateTime \| Date \| str` | — | Start of the window. |
| `end_time` | `PlainDateTime \| ZonedDateTime \| Date \| str` | — | End of the window. Required. |

```python
--8<-- "pages/core-concepts/api/snippets/api_utilities.py:get_calendar_events"
```

### `get_camera_image(entity_id, timestamp=None)`

Returns the camera image as `bytes`. Omitting `timestamp` returns the latest image. A
`timestamp` argument retrieves a historical snapshot.

| Parameter | Type | Default | Description |
|---|---|---|---|
| `entity_id` | `str` | — | Camera entity ID (e.g., `"camera.front_door"`). |
| `timestamp` | `PlainDateTime \| ZonedDateTime \| Date \| str \| None` | `None` | Snapshot time. `None` returns the latest image. |

```python
--8<-- "pages/core-concepts/api/snippets/api_get_camera_image.py"
```

---

## System

### `get_config()` / `get_services()` / `get_panels()`

Three methods for reading Home Assistant system information.

| Method | Returns |
|---|---|
| `get_config()` | HA configuration dict: version, location, unit system, time zone, installed components. |
| `get_services()` | All registered services, keyed by domain then service name. |
| `get_panels()` | All registered frontend panels, keyed by panel URL path. |

```python
--8<-- "pages/core-concepts/api/snippets/api_system.py:get_config"
```

```python
--8<-- "pages/core-concepts/api/snippets/api_system.py:get_services"
```

### `delete_entity(entity_id)`

Removes an entity from the Home Assistant state machine. Raises `RuntimeError` when deletion fails.

```python
--8<-- "pages/core-concepts/api/snippets/api_system.py:delete_entity"
```

`delete_entity` removes the entity from the HA REST state machine. It does not remove a
device or integration-backed entity from the HA entity registry. The HA UI or the registry
WebSocket API handles that.

---

## Synchronous Usage

`self.api.sync` provides blocking versions of every `Api` method. These are only safe to call from
[`AppSync`][hassette.app.app.AppSync] lifecycle hooks, which run in a dedicated worker thread
outside the event loop. Calling `self.api.sync` from an `async` context deadlocks.

```python
--8<-- "pages/core-concepts/api/snippets/api_sync_usage.py"
```

---

## See Also

- [API Overview](index.md) — when to use `self.api` vs `self.states`, error handling
- [Managing Helpers](managing-helpers.md) — create and update HA helpers via the API
- [States](../states/index.md) — synchronous state cache for instant lookups without a network call
- [Bus](../bus/index.md) — subscribing to state changes and service call events
