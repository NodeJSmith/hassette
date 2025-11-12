# Apps

Apps are the heart of Hassette—the Python you write to respond to events and manipulate resources. Each app encapsulates its own behavior, configuration, and internal state while interacting with Home Assistant through typed helpers.

Apps can be **async** or **sync**. Async is preferred because it plugs directly into Hassette’s event loop. Sync apps are supported for compatibility; they run inside `asyncio.to_thread()` so they never block the loop.

## App structure

```mermaid
graph LR
    App -- uses --> Api
    App -- subscribes_to --> Bus
    App -- schedules --> Scheduler
```

## Defining an app

Create a class that inherits from `hassette.app.app.App` (async) or `hassette.app.app.AppSync` (sync). Optional Pydantic config models inherit from `hassette.app.app_config.AppConfig`.

```python
--8<-- "pages/core-concepts/apps/example_app.py"
```

That’s enough to get a fully functioning Hassette app.

## Core capabilities

Every app automatically receives helpers:

- `self.api` — typed async wrapper over Home Assistant’s REST/WebSocket APIs (see [API](../api/index.md)).
- `self.bus` — subscribe to and handle events (see [Bus](../bus/index.md)).
- `self.scheduler` — schedule or manage jobs (see [Scheduler](../scheduler/index.md)).
- `self.logger` — standard `logging.Logger` scoped to your app.
- `self.app_config` — typed config instance specific to the current app instance.

Extra metadata like `self.instance_name` and `self.index` help with logging and diagnostics.

## Lifecycle

Apps follow a predictable lifecycle with startup and shutdown hooks. Hassette waits until all core services are ready before invoking your hooks and automatically cleans up resources afterwards.

**Initialization order**

1. `before_initialize`
2. `on_initialize`
3. `after_initialize`

**Shutdown order**

1. `before_shutdown`
2. `on_shutdown`
3. `after_shutdown`

After shutdown hooks, Hassette calls `cleanup` to cancel subscriptions, jobs, and pending tasks. Use the hooks to set up or tear down anything app-specific.

!!! warning
    Don’t override `initialize`, `shutdown`, or `cleanup` directly. Use the provided hooks; overriding the core methods raises `hassette.exceptions.CannotOverrideFinalError`.

## App configuration

Subclass `AppConfig` to declare typed configuration for your app. Because `App` is generic on the config type, `self.app_config` is fully typed and validated at startup.

```python
--8<-- "pages/core-concepts/apps/typed_config_example.py"
```

```toml
--8<-- "pages/core-concepts/apps/typed_config_toml.toml"
```

The base `AppConfig` already includes optional `instance_name` and `log_level` fields. You can add anything else you need—defaults, validators, `Field` metadata, etc. Since `AppConfig` extends `pydantic_settings.BaseSettings`, environment variables and `.env` files are supported automatically.

## App secrets

Environment variables map to config fields via Hassette’s nested naming convention:

```
HASSETTE__APPS__MY_APP__CONFIG__FIELD_NAME
```

Prefer to type less? Set `env_prefix` inside `AppConfig` so you can use shorter names:

```python
from hassette import AppConfig
from pydantic_settings import SettingsConfigDict


class MyAppConfig(AppConfig):
    model_config = SettingsConfigDict(env_prefix="MYAPP_")
    required_secret: str
```

```bash
export MYAPP_REQUIRED_SECRET="s3cr3t"
```

## See also

- [Core concepts](../index.md)
- [Scheduler](../scheduler/index.md)
- [Bus](../bus/index.md)
- [API](../api/index.md)
- [Configuration](../configuration/index.md)
