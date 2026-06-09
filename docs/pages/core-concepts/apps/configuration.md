# Application Configuration

Apps are registered in `hassette.toml` (at the project root — the same directory you run `hassette run` from) under `[hassette.apps.<key>]`. Each block tells Hassette which Python file and class to load, and passes configuration values to the app.

This page covers the TOML side of app configuration. [Apps](../apps/index.md) covers defining typed [`AppConfig`][hassette.app.app_config.AppConfig] models in Python — the class that declares and validates the fields your app accepts.

## Registering an App

An app block requires two fields: `filename` and `class_name`. `filename` is the path to the Python file, relative to [`apps.directory`](../configuration/index.md) (the root directory for app source files, configured in `hassette.toml`). `class_name` is the name of the [App][hassette.app.app.App] subclass to load.

```toml
--8<-- "pages/core-concepts/configuration/snippets/single_instance.toml"
```

`enabled` disables the app without removing the config block when set to `false`. `display_name` sets a friendly label for logs; it defaults to the class name.

!!! note "Alternative field names"
    `filename` also accepts `file_name`. `class_name` also accepts `class`, `module`, and `module_name`. `filename` and `class_name` are the recommended names; the alternatives exist for compatibility.

## Passing Configuration

The `config` field supplies values to the app's `AppConfig` model. Two TOML forms are equivalent for single-instance apps.

Inline form:

```toml
[hassette.apps.presence]
filename = "presence.py"
class_name = "PresenceApp"
config = { motion_sensor = "binary_sensor.hall", lights = ["light.entry"] }
```

Table form:

```toml
[hassette.apps.presence]
filename = "presence.py"
class_name = "PresenceApp"

[hassette.apps.presence.config]
motion_sensor = "binary_sensor.hall"
lights = ["light.entry"]
```

!!! note "Two TOML paths, two purposes"
    App registration fields (`filename`, `class_name`, `enabled`, `display_name`) live at `[hassette.apps.<key>]`. App configuration fields live at `[hassette.apps.<key>.config]`. Placing app config values directly under `[hassette.apps.<key>]` without the `config` sub-key generates a deprecation warning in the startup logs.

Environment variables override individual `config` values at startup. The pattern is `HASSETTE__APPS__<APP_KEY>__CONFIG__<FIELD>`. For example, `HASSETTE__APPS__PRESENCE__CONFIG__MOTION_SENSOR=binary_sensor.hall_v2` overrides `motion_sensor` for the `presence` app. Environment variable values take precedence over TOML.

## Multiple Instances

The same app class runs as separate instances by replacing `config = ...` with `[[hassette.apps.<key>.config]]` blocks (TOML's array-of-tables syntax). Each block produces one independent app instance with its own state, handlers, and scheduler.

```toml
--8<-- "pages/core-concepts/configuration/snippets/multiple_instances.toml"
```

The `name` field distinguishes instances in logs and the web UI. Without it, Hassette generates a name from the class name and index (e.g., `PresenceApp.0`).

Single-instance apps are the default. Most apps never need `[[...]]` blocks. Multiple instances let the same logic run across different rooms, devices, or entity sets without duplicating app code.

## Typed Configuration

The values supplied under `config` are validated at startup against an [`AppConfig`][hassette.app.app_config.AppConfig] subclass defined in Python. A missing required field or a type mismatch raises a Pydantic `ValidationError` before any app starts, showing the field name and expected type. [Apps](../apps/index.md) covers defining the model.

## Next Steps

- [Apps overview](index.md): defining `AppConfig` models, accessing config values, and app structure
- [Global Configuration](../configuration/index.md): `hassette.toml` settings outside the `[apps]` section
- [Lifecycle](lifecycle.md): what happens after Hassette loads and validates the app config
