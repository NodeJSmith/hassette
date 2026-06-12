# App Configuration

This page covers the **Python side** of app configuration: defining `AppConfig` subclasses, typed fields, defaults, and environment variable injection. For how to register apps and supply config values in `hassette.toml`, see [Application Configuration](../configuration/applications.md).

## Defining Config Models

Inherit from [`AppConfig`][hassette.app.app_config.AppConfig] to define your configuration schema. `AppConfig` extends Pydantic's [`BaseSettings`](https://pydantic.dev/docs/validation/latest/concepts/pydantic_settings/) (from the `pydantic-settings` package), which adds environment variable injection on top of standard Pydantic validation. If you've used Pydantic's `BaseModel`, the syntax is the same — `BaseSettings` just adds env var support.

```python
--8<-- "pages/core-concepts/apps/snippets/app_config_definition.py"
```

The `App` generic parameter (`App[MyAppConfig]`) tells Hassette which config class to instantiate. Inside your app, `self.app_config` is typed as `MyAppConfig`, giving you full IDE completion and type checking.

## Base Fields

The base `AppConfig` includes standard fields available to all apps:

- `instance_name: str = ""` - Used for logging and identification.
- `log_level: LOG_LEVEL_TYPE` - Log-level override for this app instance; defaults to `INFO` or the global `log_level` setting.

## Secrets & Environment Variables

`AppConfig` inherits from Pydantic's `BaseSettings`, so it supports environment variable injection out of the box. Define a custom `env_prefix` on your config class to control which environment variables it reads:

```python
--8<-- "pages/core-concepts/apps/snippets/app_config_env_prefix.py"
```

Now you can set `MYAPP_API_KEY` in your environment or `.env` file. TOML values and environment variables are merged; environment variables take precedence.

## Developer Settings {#developer-settings}

`AppConfig` includes one developer-facing field:

- **`forgotten_await_behavior`** (`"IGNORE"` / `"WARN"` / `"ERROR"` or `None`): Per-app override for what happens when a protected method is called without `await`. `None` (the default) falls back to the global `forgotten_await_behavior` setting in `hassette.toml`.

    ```python
    --8<-- "pages/core-concepts/apps/snippets/app_config_forgotten_await.py"
    ```

    Import `ForgottenAwaitBehavior` from `hassette.types.enums`:

    ```python
    from hassette.types.enums import ForgottenAwaitBehavior
    ```

    Use `ERROR` for apps under active development to catch forgotten `await` calls at runtime. Use `WARN` (or `None` to inherit the global default) for production apps. See [Global Settings](../configuration/global.md#developer-settings) for the global default.

## Sync Apps (`AppSync`)

`AppSync` subclasses `App` and provides synchronous lifecycle hooks (`on_initialize_sync`, `on_shutdown_sync`). The sync facades (`self.bus.sync`, `self.scheduler.sync`, `self.api.sync`) call each registration method synchronously — there is no forgotten-await risk on the sync path, because the sync facade drives the coroutine to completion before returning.

## See Also

- [Application Configuration](../configuration/applications.md) - Registering apps and supplying config values in `hassette.toml`
