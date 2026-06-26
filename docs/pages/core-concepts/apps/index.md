# Apps Overview

An app is a Python class that reacts to Home Assistant events and controls devices. Each app has its own config, state, and a set of typed accessors — `self.bus`, `self.scheduler`, `self.api`, `self.states`, `self.cache`, and `self.task_bucket` — for interacting with HA.

## Defining an App

Every app is a Python class that inherits from [`App`][hassette.app.app.App]. `App` manages handlers, scheduling, and the connection to Home Assistant. The `on_initialize` lifecycle hook runs at startup, before any events arrive.

```python
--8<-- "pages/core-concepts/apps/snippets/example_app.py"
```

!!! info "What's `D.StateNew[states.LightState]`?"
    That annotation is [dependency injection](../bus/dependency-injection.md). The handler declares what data it needs, and Hassette extracts and types it from the event automatically. The [Writing Handlers](../bus/handlers.md) page covers how it works. For now, just notice the pattern.

Two more things to notice in the example. Every method is `async def`, and the registration call is awaited — that pattern holds for all bus, scheduler, and API calls, and a missing `await` silently does nothing (see [Call Services](#call-services) below) — [Async Basics](../../migration/async-basics.md) explains why. The `name=` parameter is required on every subscription; it labels the listener in logs and the [web UI](../../web-ui/index.md).

## Configuration

[`AppConfig`][hassette.app.app_config.AppConfig] loads and validates an app's settings from `hassette.toml` and environment variables. A subclass declares typed fields; Hassette populates them at startup.

```python
--8<-- "pages/core-concepts/apps/snippets/app_config_definition.py"
```

`self.app_config` on the app instance is typed as the declared subclass, so the IDE and Pyright know the exact shape.

### Environment Variables

`SettingsConfigDict(env_prefix="...")` scopes environment variable injection to a prefix, preventing collisions between multiple apps running in the same process.

```python
--8<-- "pages/core-concepts/apps/snippets/app_config_env_prefix.py"
```

With `env_prefix="MYAPP_"`, the field `api_key` reads from `MYAPP_API_KEY`. Fields without a matching environment variable fall back to their declared defaults. Required fields (no default) raise a validation error at startup if absent.

### Base Fields

Every `AppConfig` includes three built-in fields:

- `instance_name`: a string that uniquely identifies one running instance of the app. Defaults to an empty string; Hassette derives a display name from the class name when it is not set.
- `log_level`: controls the logging verbosity for this app's logger. Inherits the process-level default when not set.
- `app_key`: the app's key from `hassette.toml`, set by the framework. Don't set it directly; framework-reserved values are rejected with a validation error. Read it at runtime via `self.app_key` — useful for logging or cross-app messaging.

`AppConfig` allows arbitrary extra fields by default. A subclass can tighten this by setting `extra="forbid"` in its own `model_config`.

### Secret Fields

A field declared [`SecretStr`][pydantic.SecretStr] is masked wherever Hassette surfaces the config — the dashboard Config tab shows a masked placeholder, never the value. Masking follows the type, not the name: a `str` named `api_key` renders in full, while a `SecretStr` named anything renders masked.

```python
--8<-- "pages/core-concepts/apps/snippets/app_config_secret.py"
```

App code reads the real value with `get_secret_value()`. The plaintext stays server-side and never reaches the browser.

!!! warning "Name-based masking is gone"
    Earlier versions masked fields whose name matched `token`, `password`, `secret`, and similar. That heuristic is removed — it missed names like `pat` or `connection_string` and gave false confidence. Type a field `SecretStr` to mask it.

### Presentation Metadata

Each field sets optional presentation hints under a `ui` namespace through `json_schema_extra`. The dashboard reads them when rendering the Config tab; every hint falls back to a schema-derived default when absent, so annotating is opt-in.

```python
--8<-- "pages/core-concepts/apps/snippets/app_config_ui_metadata.py"
```

| Key | Effect | Default when unset |
|---|---|---|
| `label` | field display name | humanized field name |
| `group_label` | section title, set on a nested-group field | humanized group name |
| `order` | sort order within a section | declaration order |
| `widget` | force a value format, e.g. `"path"` | format derived from the field type |

!!! note "`tier` is reserved"
    The `ui` namespace also defines a `tier` key (`"common"` / `"advanced"`) for a future show-advanced view. It has no effect yet — don't repurpose the key before that lands.

### TOML Registration

The `hassette.toml` file registers each app and supplies its config values. See [App Configuration](configuration.md) for the full reference.

```toml
--8<-- "pages/core-concepts/apps/snippets/app_config.toml"
```

## Dates and Times

`self.now()` returns the current time as a `ZonedDateTime` from the [`whenever`](https://whenever.readthedocs.io/en/latest/) library, which ships with Hassette — no separate install needed. All scheduler parameters, persistent storage examples, and custom state definitions use `whenever` types.

```python
--8<-- "pages/core-concepts/apps/snippets/apps_whenever_dates.py:imports"
```

```python
--8<-- "pages/core-concepts/apps/snippets/apps_whenever_dates.py:usage"
```

`whenever` is always timezone-aware and immutable. Mixing naive and aware times is a type error that Pyright catches before the code runs. Python's stdlib `datetime` permits that class of mistake; `whenever` does not.

## What an App Can Do

### React to Events

[`self.bus`](../bus/index.md) subscribes to Home Assistant state changes, attribute changes, and service calls. The bus delivers each matching event to every registered handler.

```python
--8<-- "pages/core-concepts/apps/snippets/apps_subscribe_state_change.py:subscribe_state_change"
```

See the [`Bus`](../bus/index.md) page for filtering, predicates, debounce, and throttle options.

### Schedule Jobs

[`self.scheduler`](../scheduler/index.md) runs functions on a schedule.

```python
--8<-- "pages/core-concepts/apps/snippets/apps_run_hourly.py:run_hourly"
```

See the [`Scheduler`](../scheduler/index.md) page for triggers, job groups, and jitter.

### Read Entity States

[`self.states`](../states/index.md) provides instant access to the current state of any entity, without an API call.

```python
--8<-- "pages/core-concepts/apps/snippets/apps_check_state.py:check_state"
```

See the [States](../states/index.md) page for typed domain access and custom state models.

### Call Services

[`self.api`](../api/index.md) calls Home Assistant REST and WebSocket services.

```python
--8<-- "pages/core-concepts/apps/snippets/apps_call_service.py:call_service"
```

!!! warning "Forgetting `await` on API calls"
    Every `self.api.*` method is a coroutine. It must be awaited. Writing `self.api.call_service(...)` without `await` returns a coroutine object and silently does nothing: no error is raised, no service is called, and no log message appears. If an API call seems to have no effect, check that `await` is present.

See the [API](../api/index.md) page for state access, entity management, and more.

### Persist Data

[`self.cache`](../cache/index.md) stores values that survive app restarts. Reads and writes go through a disk-backed store scoped to the app instance.

```python
--8<-- "pages/core-concepts/apps/snippets/apps_cache_counter.py:cache_counter"
```

See the [Cache](../cache/index.md) page for typed access, TTL, and cache invalidation.

### Run Background Work

[`self.task_bucket`](task-bucket.md) spawns fire-and-forget coroutines and offloads blocking calls to a thread pool. All tracked tasks cancel automatically on shutdown.

```python
--8<-- "pages/core-concepts/apps/snippets/apps_task_bucket.py:spawn"
```

See the [Task Bucket](task-bucket.md) page for `run_in_thread`, `make_async_adapter`, and cross-thread communication.

## Restricting to a Single App

The [`@only_app`][hassette.app.app.only_app] decorator prevents all other apps from loading while the decorated class is present. It is intended for development isolation: one app runs while the rest are silenced, without editing `hassette.toml`.

```python
--8<-- "pages/core-concepts/apps/snippets/apps_only_app.py"
```

Only one class in the project may carry `@only_app` at a time. Hassette raises an error at startup if more than one is found.

In production mode, the decorator is ignored by default. `allow_only_app_in_prod = true` in `hassette.toml` overrides this behavior.

## Broadcasting Between Apps

[`self.bus.emit()`](../bus/index.md) broadcasts an in-process event to all apps subscribed to a given topic. The event never reaches Home Assistant and is not persisted across restarts.

`self.bus.on(topic=...)` subscribes to a named topic. [`D.EventData[T]`](../bus/dependency-injection.md) follows the same dependency injection pattern as `D.StateNew` — replace `T` with the payload class, so `D.EventData[LightsSyncedData]` delivers the payload as a `LightsSyncedData` object.

```python
--8<-- "pages/core-concepts/apps/snippets/apps_bus_emit.py:sender"
```

```python
--8<-- "pages/core-concepts/apps/snippets/apps_bus_emit.py:receiver"
```

!!! note "Self-delivery"
    An app that both emits and subscribes on the same topic receives its own events. To filter self-emitted events, include a `source` field on the emitted dataclass (as `LightsSyncedData` does above) and guard in the handler: `if data.source == self.instance_name: return`.

## Synchronous Apps

[`AppSync`][hassette.app.app.AppSync] runs automations written without `async`/`await`. Hassette executes the app's lifecycle hooks in a thread pool so blocking code does not stall the event loop. The bus, scheduler, and API expose synchronous facades via `.sync` (`self.bus.sync`, `self.scheduler.sync`, `self.api.sync`), so registrations and calls work without `await`. Entity objects from `self.api.sync.get_entity(...)` expose the same pattern. `entity.sync` returns a typed domain facade — a `CoverEntitySyncFacade`, `ClimateEntitySyncFacade`, and so on. The facade makes every domain action callable without `await`: `cover.sync.set_cover_position(position=60)`, `climate.sync.set_temperature(temperature=21.0)`. See [API Methods](../api/methods.md#entity-sync-facades-appsync-only) for the full facade reference.

`AppSync` fits apps built on blocking libraries and migrations from synchronous frameworks. Prefer async `App` for new code. See [Lifecycle](lifecycle.md#synchronous-lifecycle) for the sync hook details and a full example.

## Next Steps

- **[Lifecycle](lifecycle.md)**: `on_initialize`, `on_shutdown`, and automatic resource cleanup.
- **[Task Bucket](task-bucket.md)**: background tasks, thread offloading, and cross-thread communication.
