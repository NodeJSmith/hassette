# Configuration

AppDaemon splits configuration across two YAML files: `appdaemon.yaml` for global settings and `apps.yaml` for per-app arguments. Hassette uses a single `hassette.toml` for everything, and replaces raw argument dictionaries with typed `AppConfig` models.

## Global Configuration

=== "AppDaemon"

    ```yaml
    --8<-- "pages/migration/snippets/config_appdaemon_yaml.yaml"
    ```

=== "Hassette"

    ```toml
    --8<-- "pages/migration/snippets/config_migration_toml.toml"
    ```

The Home Assistant token is read from the `HASSETTE__TOKEN` environment variable or a `.env` file. It does not go in `hassette.toml`.

## Per-App Configuration

This is the bigger change. In AppDaemon, you declare app arguments in `apps.yaml` and read them through a nested dictionary. In Hassette, arguments go in `hassette.toml` and you define an `AppConfig` subclass to describe them.

=== "AppDaemon"

    ```yaml
    --8<-- "pages/migration/snippets/config_apps_yaml.yaml"
    ```

    Arguments are accessible via `self.args["args"]["key"]`, a nested dictionary with no type information:

    ```python
    --8<-- "pages/migration/snippets/config_appdaemon_access.py"
    ```

=== "Hassette"

    ```toml
    --8<-- "pages/migration/snippets/config_hassette_toml.toml"
    ```

    You define a subclass of `AppConfig` to declare each parameter with a type and optional default. Access configuration through `self.app_config`:

    ```python
    --8<-- "pages/migration/snippets/config_hassette_appconfig.py"
    ```

Missing required fields raise a validation error at startup, before any handler runs. `self.app_config.entity` carries a type your IDE can check.

!!! note "`[[double brackets]]`: TOML array-of-tables"
    `[[apps.my_app.config]]` is a TOML array-of-tables. You can repeat the block to run the same app class with multiple independent configurations. Use `[...]` for a single instance; use `[[...]]` when you want a list.

## Multi-Instance Apps

To run the same class in multiple rooms, add another `[[apps.my_app.config]]` block:

```toml
[apps.motion_lights]
filename = "motion_lights.py"
class_name = "MotionLights"

[[apps.motion_lights.config]]
motion_sensor = "binary_sensor.living_room_motion"
light = "light.living_room"
off_delay = 300

[[apps.motion_lights.config]]
motion_sensor = "binary_sensor.bedroom_motion"
light = "light.bedroom"
off_delay = 120
```

Each block becomes a separate app instance. Both run the same `MotionLights` class with different config values. See [App Configuration](../core-concepts/apps/configuration.md) for the full reference.

## See Also

- [App Configuration](../core-concepts/apps/configuration.md) — defining `AppConfig` models
- [Configuration Overview](../core-concepts/configuration/index.md) — `hassette.toml` structure
- [Global Settings](../core-concepts/configuration/global.md) — all global Hassette settings
- [Applications](../core-concepts/configuration/applications.md) — app registration and toml syntax
