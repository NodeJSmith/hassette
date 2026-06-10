# Mental Model

This page maps the design differences between AppDaemon and Hassette so you can write idiomatic Hassette code instead of translating patterns one-for-one.

## App Structure

=== "AppDaemon"

    ```python
    --8<-- "pages/migration/snippets/concepts_appdaemon_app.py"
    ```

=== "Hassette"

    ```python
    --8<-- "pages/migration/snippets/concepts_hassette_app.py"
    ```

Three things change:

- **Base class**: `Hass` becomes `App[Config]`. The generic parameter is optional. [App][hassette.app.app.App] with no type argument works fine.
- **Lifecycle hook**: `initialize()` becomes `on_initialize()`.
- **Async keyword**: Hassette's hook is `async def`. The body uses `await`.

## Access Model

AppDaemon puts everything on `self`. `self.listen_state(...)`, `self.call_service(...)`, `self.run_in(...)` all live on one flat surface.

Hassette uses composition. Each subsystem is a separate attribute:

| Attribute | What it does |
|---|---|
| `self.bus` | Subscribe to state changes, service calls, and custom events |
| `self.scheduler` | Schedule jobs by delay, interval, time, or cron expression |
| `self.api` | Call Home Assistant REST and WebSocket APIs |
| `self.states` | Read local state cache, automatically kept current |
| `self.cache` | Persistent disk-backed key-value store |
| `self.logger` | Standard Python logger scoped to the app |

The upside is discoverability. Typing `self.bus.` in your editor gives you the full event API. Typing `self.scheduler.` gives you the scheduler. Nothing is buried.

## Async vs Sync

AppDaemon is multi-threaded. Each app runs in its own thread, so synchronous code works fine.

Hassette runs all apps in a single asyncio event loop. Two things follow:

1. API calls and bus registrations require `await` — the practical rule: put `await` in front of any call to `self.api`, `self.bus`, or `self.scheduler`, and declare the surrounding method `async def`. Reads from `self.states` are synchronous.
2. Blocking the event loop (a long `time.sleep`, a slow synchronous database call) blocks all apps, not just yours.

```python
--8<-- "pages/migration/snippets/concepts_sync_async.py"
```

The example's `self.task_bucket.run_in_thread(...)` is a helper on every `App` instance that runs blocking code in a thread without stalling other apps. If most of your code is blocking and you cannot convert it, use [`AppSync`][hassette.app.app.AppSync] ([described below](#synchronous-api-appsync)).

## Typed vs Untyped

AppDaemon returns raw strings and dicts. `self.get_state("light.kitchen")` returns `"on"` or `"off"`. Attribute access returns `Any`. Configuration lives in `self.args`, a plain dict.

Hassette uses typed models throughout — objects with named, validated fields instead of raw dicts (powered by Pydantic).

**Entity states** are typed objects. `self.states.get("light.kitchen")` returns a [`LightState`][hassette.models.states.light.LightState] with typed fields. Your IDE knows the shape, and a type checker like Pyright catches typos at development time, not at 2am.

**App configuration** is a validated Pydantic model. You declare fields with types and defaults; Hassette loads and validates them at startup. A missing required field raises an error before any handler fires.

**API responses** return structured models instead of raw dicts. You work with attributes, not string keys.

## Callback Signatures

AppDaemon requires a fixed signature. State change callbacks must be:

```python
def my_callback(self, entity, attribute, old, new, **kwargs): ...
```

You always receive all five arguments, whether you need them or not.

Hassette handlers can have almost any signature. Three styles work:

**Full event object.** Receive the raw event and extract what you need:

```python
async def on_light_change(self, event: RawStateChangeEvent): ...
```

**Dependency injection.** Annotate parameters with `D.*` types and Hassette fills them in:

```python
async def on_light_change(self, new_state: D.StateNew[states.LightState]): ...
```

**No arguments.** Use when you only care that the event fired:

```python
async def on_motion(self): ...
```

Hassette inspects your handler's type annotations at subscription time and injects the right data automatically. See [Dependency Injection](../core-concepts/bus/dependency-injection.md) for the full reference.

## Synchronous API (AppSync)

If you have a large synchronous codebase and don't want to convert everything at once, `AppSync` is an intermediate step. It runs lifecycle hooks in a managed thread, letting you write synchronous code as before.

```python
--8<-- "pages/migration/snippets/concepts_appsync.py"
```

Because the bus, scheduler, and API are async internally, `AppSync` exposes synchronous wrappers: `self.bus.sync`, `self.scheduler.sync`, `self.api.sync`. Each one waits for the async operation to finish and returns the result to your synchronous code.

`AppSync` keeps your existing code working while you migrate. As you convert methods to async, you can move them to `App` incrementally.

## See Also

- [`Bus` & Events](bus.md): migrating `listen_state` and `listen_event`
- [API Calls](api.md): migrating `get_state`, `call_service`, and `set_state`
- [Dependency Injection](../core-concepts/bus/dependency-injection.md): full DI reference
