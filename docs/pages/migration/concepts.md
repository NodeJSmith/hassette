# Mental Model

This page covers how AppDaemon and Hassette differ at the design level — not just syntax, but philosophy. Understanding these differences helps you write idiomatic Hassette code instead of translating AppDaemon patterns one-for-one.

## Execution Model

**AppDaemon** runs each app in a separate thread. This means you can write synchronous code without worrying about blocking the event loop — long-running operations work fine because they run in their own thread.

**Hassette** runs all apps in a single asyncio event loop. You write `async`/`await` code. If you have blocking or IO-bound operations, you either use `AppSync` (which runs in a thread automatically) or offload work to a thread using `self.task_bucket.run_in_thread()`.

```python
--8<-- "pages/migration/snippets/concepts_sync_async.py"
```

## Access Model

**AppDaemon** exposes everything via methods on `self` (the app instance): `self.listen_state(...)`, `self.call_service(...)`, `self.run_in(...)`. All features live on one flat surface.

**Hassette** uses composition: each subsystem is a separate attribute on the app:

| Attribute | What it does |
|-----------|--------------|
| `self.bus` | Event subscriptions (state changes, service calls, custom events) |
| `self.scheduler` | Scheduled jobs |
| `self.api` | Home Assistant REST/WebSocket API calls |
| `self.states` | Local state cache (automatically updated) |
| `self.cache` | Persistent disk-backed cache |
| `self.logger` | Standard Python logger |

## Inheritance vs. Composition

**AppDaemon** apps inherit from `Hass` (or `ADAPI`) and call inherited methods directly.

**Hassette** apps inherit from `App` (or `AppSync`), but features are accessed via composition (the subsystem attributes above). The base class provides the lifecycle hooks and wires everything together at startup.

=== "AppDaemon"

    ```python
    --8<-- "pages/migration/snippets/concepts_appdaemon_app.py"
    ```

=== "Hassette"

    ```python
    --8<-- "pages/migration/snippets/concepts_hassette_app.py"
    ```

**Key differences when updating your class definition:**

- Change `Hass` to `App` or `AppSync`
- Rename `initialize()` to `on_initialize()` (and add `async` for `App`)
- Use `await` for API calls and other async operations

## Typed vs. Untyped

**AppDaemon** returns raw strings or dicts from API calls. State values are strings; attribute access returns `Any`. Configuration arguments come in as a plain dictionary (`self.args["args"]["key"]`).

**Hassette** uses Pydantic models throughout:

- Entity states are typed objects (e.g., `LightState`, `BinarySensorState`) with typed attributes
- App configuration is a validated Pydantic model — missing fields raise an error at startup, not at runtime
- API responses return structured models instead of raw dicts

## Callback Signatures

**AppDaemon** requires specific callback signatures. State change callbacks must be `def my_callback(self, entity, attribute, old, new, **kwargs)`. Event callbacks must be `def my_callback(self, event_name, event_data, **kwargs)`. Extra keyword arguments you passed when subscribing arrive in `**kwargs`.

**Hassette** handlers can have almost any signature. You can:

1. Accept the full event object: `async def handler(self, event: CallServiceEvent)`
2. Use dependency injection to extract only the fields you need: `async def handler(self, domain: D.Domain, entity_id: D.EntityId)`
3. Accept no arguments at all: `async def handler(self)`

Hassette inspects your handler's type annotations at subscription time and injects the right data automatically. See [Bus & Events](bus.md) for the full DI reference.

## Synchronous API

If you have existing synchronous code and don't want to add `async`/`await` everywhere, use `AppSync`:

```python
from hassette import AppSync


class MyApp(AppSync):
    def on_initialize_sync(self):
        # Everything here is synchronous
        self.api.sync.call_service("light", "turn_on", target={"entity_id": "light.kitchen"})
```

`AppSync` runs in a managed thread and provides `self.api.sync` for blocking API access. It is a good intermediate step when migrating apps with heavy synchronous logic.

## See Also

- [Bus & Events](bus.md) — migrating `listen_state` and `listen_event` to `bus.on_state_change` and `bus.on_call_service`
- [API Calls](api.md) — migrating `get_state`, `call_service`, and `set_state`
- [Dependency Injection](../advanced/dependency-injection.md) — the full dependency injection reference
