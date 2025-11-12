# Api

Async-first API for REST and WebSocket interactions. The service wraps
Home Assistant's HTTP and WebSocket endpoints with typed models so your
apps can query and mutate data without hand-building requests. All calls
run on Hassette's asyncio loop and share the same authentication/session
that the framework manages for you.

## Key capabilities

- Retrieve states and entities as rich Pydantic models (with raw
  variants available when needed) using
  `hassette.api.api.Api.get_states`, `hassette.api.api.Api.get_state`,
  `hassette.api.api.Api.get_entity`, and more.
- Call services with convenience helpers for on/off/toggle as well as
  the generic `hassette.api.api.Api.call_service` method.
- Fire custom events, fetch history/logbook records, interact with
  calendars, render templates, and download camera stills.
- Drop down to low-level `hassette.api.api.Api.rest_request` or
  `hassette.api.api.Api.ws_send_and_wait` helpers when you need direct
  API access.

!!! caution "States vs entities"
    Hassette intentionally uses slightly different terminology than Home Assistant/AppDaemon.

    - A `hassette.models.states.base.BaseState` (returned by `get_state`) represents the full entity state, including attributes and metadata.
    - A `hassette.models.states.base.StateValueT` (returned by `get_state_value`) is the raw value, e.g., `"on"`, `"off"`, `23.5`.
    - A `hassette.models.entities.base.BaseEntity` (returned by `get_entity`) wraps a state plus helper methods, so you can act on it directly.

!!! note
    Most API methods return typed models. For example, `get_state` expects an entity ID and a state model class, then returns an instance of that model.

    ```python
    --8<-- "pages/core-concepts/api/typed_state_example.py"
    ```

    Every typed helper has a `raw` sibling that yields plain dictionaries if you prefer them:

    ```python
    --8<-- "pages/core-concepts/api/raw_state_example.py"
    ```

    `get_state_value` is the exception: it always returns Home Assistant’s raw string. Use `get_state_value_typed` if you need the typed version.

## States

`get_states` and `get_state` convert raw dictionaries into the
appropriate `hassette.models.states.base.BaseState` subclasses. Pass
the state model you expect to `get_state` so you receive the fully typed
object. If you just need the primary value, `get_state_value` returns
the raw Home Assistant string, while `get_state_value_typed` will coerce
into your Pydantic model's `state` field.

```python
--8<-- "pages/core-concepts/api/states_example.py"
```

## Entities

Entities (`hassette.models.entities`) wrap a state plus helper methods.
`get_entity` performs a runtime check to be sure you requested the right
entity model and returns `None` if you use `get_entity_or_none` and the
entity is missing.

```python
--8<-- "pages/core-concepts/api/entities_example.py"
```

!!! note
    Entity helpers are still evolving—right now only `BaseEntity` and `LightEntity` exist.

## Service helpers

`hassette.api.api.Api.call_service` is the lowest-level abstraction for
invoking Home Assistant services. Pass `domain`/`service` along with a
`target` dict or additional service data. Convenience wrappers
turn_on/turn_off/toggle simply forward to `call_service` and request a
response context so you can inspect the HA `HassContext`.

```python
--8<-- "pages/core-concepts/api/service_helpers_example.py"
```

!!! note
    Typed service wrappers are on the roadmap. For now, detailed services (e.g., `light.turn_on`) will eventually land on entity classes rather than adding hundreds of overloads to `Api`.

## History and logbook

History endpoints accept Whenever date objects or plain strings.
`get_history` returns normalized `hassette.models.history.HistoryEntry`
instances; `get_histories` returns a mapping of entity IDs to entry
lists when you need to fetch multiple entities at once.

```python
--8<-- "pages/core-concepts/api/history_example.py"
```

## Templates, calendars, and other REST endpoints

Use the provided helpers instead of building raw URLs:

- `hassette.api.api.Api.render_template` renders Jinja templates.
- `hassette.api.api.Api.get_camera_image` streams the latest still (or
  a specific timestamp).
- `hassette.api.api.Api.set_state` writes synthetic states (handy for
  helpers or sensors you manage).
- `hassette.api.api.Api.get_calendars` /
  `hassette.api.api.Api.get_calendar_events` expose HA calendar data.

Each helper handles serialization and retries for you.

## Low-level access

If you need an endpoint Hassette does not wrap yet, `rest_request` and
`ws_send_and_wait` provide direct access to the authenticated `aiohttp`
session and WebSocket connection. They include retry logic and raise
Hassette-specific exceptions like
`hassette.exceptions.EntityNotFoundError` and
`hassette.exceptions.InvalidAuthError` so you can handle failures
consistently.

```python
--8<-- "pages/core-concepts/api/low_level_example.py"
```

## Sync facade

`self.api.sync` mirrors the async API with blocking calls for
synchronous code. Do not call from within an event loop - it's intended
for `AppSync` subclasses or transitional code paths (for example,
libraries that expect synchronous hooks).

```python
--8<-- "pages/core-concepts/api/sync_facade_example.py"
```

## Typing status

- Many models and read operations are strongly typed.
- Service calls are not fully typed yet; finishing this is a high
  priority. For now, `call_service` accepts `**data` and performs string
  normalization for REST parameters.

## See also

- [Core concepts](../index.md)
- [Apps](../apps/index.md)
- [Scheduler](../scheduler/index.md)
- [Bus](../bus/index.md)
- [Configuration](../configuration/index.md)
