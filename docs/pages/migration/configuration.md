# Configuration

This page covers how to migrate AppDaemon configuration files to Hassette's `hassette.toml` and typed `AppConfig` models.

## Overview

AppDaemon uses two YAML files:

- `appdaemon.yaml` — global settings (timezone, HA connection details)
- `apps.yaml` — per-app settings (module, class, arguments)

Hassette uses a single `hassette.toml` for everything. App arguments are defined as typed Pydantic models instead of raw dictionaries.

## Global Configuration

### AppDaemon (`appdaemon.yaml`)

```yaml
--8<-- "pages/migration/snippets/config_appdaemon_yaml.yaml"
```

### Hassette (`hassette.toml`)

```toml
--8<-- "pages/migration/snippets/config_migration_toml.toml"
```

The Home Assistant token is read from the `HASSETTE__TOKEN` environment variable or from a `.env` file — it is not stored in `hassette.toml`.

## Per-App Configuration

### AppDaemon (`apps.yaml`)

```yaml
--8<-- "pages/migration/snippets/config_apps_yaml.yaml"
```

Arguments are accessible in the app via `self.args["args"]["entity"]` — a nested dictionary with no type information.

```python
--8<-- "pages/migration/snippets/config_appdaemon_access.py"
```

### Hassette (`hassette.toml` + `AppConfig`)

```toml
--8<-- "pages/migration/snippets/config_hassette_toml.toml"
```

In Hassette, you define a subclass of `AppConfig` to declare the expected parameters with types and defaults. You access configuration via the typed `self.app_config` attribute:

```python
--8<-- "pages/migration/snippets/config_hassette_appconfig.py"
```

## Migration Steps

Convert your `appdaemon.yaml` and `apps.yaml` to a single `hassette.toml`:

=== "Before (AppDaemon)"

    ```yaml
    # appdaemon.yaml
    appdaemon:
      plugins:
        HASS:
          type: hass
          ha_url: http://192.168.1.179:8123
          token: !env_var HOME_ASSISTANT_TOKEN

    # apps.yaml
    my_app:
      module: my_app
      class: MyApp
      args:
        entity: light.kitchen
        brightness: 200
    ```

=== "After (Hassette)"

    ```toml
    --8<-- "pages/migration/snippets/config_migration_toml.toml"
    ```

Then replace dictionary access with typed config access:

=== "Before (AppDaemon)"

    ```python
    def initialize(self):
        entity = self.args["args"]["entity"]
        brightness = self.args["args"]["brightness"]
    ```

=== "After (Hassette)"

    ```python
    from pydantic import Field
    from hassette import AppConfig

    class MyAppConfig(AppConfig):
        entity: str = Field(..., description="The entity to monitor")
        brightness: int = Field(100, ge=0, le=255)

    class MyApp(App[MyAppConfig]):
        async def on_initialize(self):
            entity = self.app_config.entity
            brightness = self.app_config.brightness
    ```

## Benefits of Typed Configuration

- **Validation at startup** — missing required fields raise a clear error before your app runs, not at runtime when a handler fires
- **IDE autocomplete** — `self.app_config.entity` gets type hints and autocomplete in any IDE with type-checking support
- **Default values** — use `Field(default_value)` to declare defaults; Hassette applies them if the toml omits the key
- **Constraints** — Pydantic validators like `ge=0, le=255` catch invalid values before your app starts

## Further Reading

- [App Configuration](../core-concepts/apps/configuration.md) — full reference for defining `AppConfig` models
- [Configuration Overview](../core-concepts/configuration/index.md) — `hassette.toml` structure
- [Global Settings](../core-concepts/configuration/global.md) — all global Hassette settings
- [Applications](../core-concepts/configuration/applications.md) — app registration and toml syntax
