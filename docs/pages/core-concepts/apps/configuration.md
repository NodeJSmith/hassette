# Application Configuration

Apps are registered in `hassette.toml` (at the project root — the same directory you run `hassette run` from) under `[hassette.apps.<key>]`. Each block tells Hassette which Python file and class to load, and passes configuration values to the app.

This page covers the TOML side of app configuration. [Apps](../apps/index.md) covers defining typed [`AppConfig`][hassette.app.app_config.AppConfig] models in Python — the class that declares and validates the fields your app accepts.

## Registering an App

An app block requires `filename` and `class_name`, and its `config` must set an `instance_name` (see [Instance Names](#instance-names)). `filename` is the path to the Python file, relative to [`apps.directory`](../configuration/index.md) (the root directory for app source files, configured in `hassette.toml`). `class_name` is the name of the [App][hassette.app.app.App] subclass to load.

```toml
--8<-- "pages/core-concepts/configuration/snippets/single_instance.toml"
```

The app key (`presence` here) also names the app's [cache directory](../cache/index.md#instance-scoped-directories), so it must be a single path segment. Letters, digits, `_`, and `-` are always safe. A key containing `.` must be quoted (`[hassette.apps."my.app"]`), or TOML reads it as nested tables. Keys that are empty, contain `/` or `\`, start with a Windows drive letter like `C:`, or are exactly `.` or `..` are rejected at startup. The key `__hassette__` and keys starting with `__hassette__.` are reserved for the framework.

`enabled` disables the app without removing the config block when set to `false`. `autostart` controls whether the app starts when Hassette starts — it defaults to `true`. `display_name` sets a friendly label for logs; it defaults to the app key (`presence` in the block above).

`description` holds an optional one-line summary of what the app does, up to 200 characters. Hassette strips surrounding whitespace and rejects a description containing a line break at startup. The `/api/apps` endpoints return it as `description`, or `null` when unset.

Every configured app needs an `instance_name`, including blocks with `enabled = false` or `autostart = false`. A block without one fails at config load.

`enabled` and `autostart` are orthogonal. An app with `enabled = true` and `autostart = false` is registered and appears in the apps list, but Hassette does not start it at boot or on live config reload. It remains idle until started on demand via the UI or `POST /apps/{key}/start`. A later config reload of an unrelated app leaves it running if it was already started.

```toml
[hassette.apps.heavy_processor]
filename = "heavy_processor.py"
class_name = "HeavyProcessorApp"
autostart = false
config = { instance_name = "heavy_processor" }
```

`enabled = false` is the hard off-switch — the app never loads or starts, but it stays registered and the apps dashboard lists it as **disabled**. `autostart = false` means "registered but not started automatically." The apps dashboard shows a **no autostart** marker on rows where `autostart = false`.

## Passing Configuration

The `config` field supplies values to the app's `AppConfig` model, and it must set `instance_name`. A section with no `config` at all fails at config load, naming the app key and instance index. Two TOML forms are equivalent for single-instance apps.

Inline form:

```toml
[hassette.apps.presence]
filename = "presence.py"
class_name = "PresenceApp"
config = { instance_name = "presence", motion_sensor = "binary_sensor.hall", lights = ["light.entry"] }
```

Table form:

```toml
[hassette.apps.presence]
filename = "presence.py"
class_name = "PresenceApp"

[hassette.apps.presence.config]
instance_name = "presence"
motion_sensor = "binary_sensor.hall"
lights = ["light.entry"]
```

!!! note "Two TOML paths, two purposes"
    App registration fields (`filename`, `class_name`, `enabled`, `autostart`, `display_name`, `description`) live at `[hassette.apps.<key>]`. App configuration fields, including `instance_name`, live at `[hassette.apps.<key>.config]`. Placing app config values directly under `[hassette.apps.<key>]` without the `config` sub-key generates a warning in the startup logs.

Environment variables override individual `config` values at startup. The pattern is `HASSETTE__APPS__<APP_KEY>__CONFIG__<FIELD>`. For example, `HASSETTE__APPS__PRESENCE__CONFIG__MOTION_SENSOR=binary_sensor.hall_v2` overrides `motion_sensor` for the `presence` app. Environment variable values take precedence over TOML.

## Multiple Instances

The same app class runs as separate instances by replacing `config = ...` with `[[hassette.apps.<key>.config]]` blocks (TOML's array-of-tables syntax). Each block produces one independent app instance with its own state, handlers, and scheduler.

```toml
--8<-- "pages/core-concepts/configuration/snippets/multiple_instances.toml"
```

Each block sets its own `instance_name`, which distinguishes the instance in logs and the web UI. Names must be unique across the whole config, not only within one app key. See [Instance Names](#instance-names).

Single-instance apps are the default. Most apps never need `[[...]]` blocks. Multiple instances let the same logic run across different rooms, devices, or entity sets without duplicating app code.

A live config reload (on when `dev_mode` or `allow_reload_in_prod` is set) restarts only the instances whose `config` block actually changed. If instance `1`'s config changes but instance `0`'s stays the same, instance `1` restarts and instance `0` keeps running with its existing state — its scheduled jobs and event subscriptions never drop. Adding or removing an instance (changing the number of `[[...]]` blocks) falls back to a full restart of every instance for that app key, since the instance list itself changed. A restart stops every instance the change replaces, across all affected apps, before starting any replacement, so a name can move from one instance or app to another in a single edit. See [Start, Stop, and Reload](../../web-ui/manage-apps.md#start-stop-and-reload) for the per-instance controls in the web UI and the equivalent REST API endpoints.

## Instance Names {#instance-names}

`instance_name` is required on every configured app instance. The name identifies the instance throughout Hassette:

- `self.instance_name` returns it. `self.unique_name` returns the same value; it's the identity Hassette uses for the app's logger and for ownership of its handlers and jobs.
- The app's logger is `hassette.apps.<instance_name>`, and the app's bus, scheduler, and other per-app loggers nest under it (`hassette.apps.upstairs.Bus`).
- Log lines and telemetry carry it as `instance_name`.

Names are modelled on Home Assistant's entity object ID rule:

- The name starts with a lowercase letter.
- It contains only lowercase letters, digits, and `_`.
- It does not end with `_`.
- It is at most 128 characters long.

`upstairs` and `kitchen_lights_2` are valid. `Upstairs`, `kitchen-lights`, `PresenceApp.0`, `2nd_floor`, and `lights_` are not. An invalid name fails at config load.

Names are unique across the whole config. No two instances, under any app key and enabled or not, share a name. A duplicate fails at config load with an error that lists every instance using the name.

!!! note "Storage, routes, and the CLI still use the index"
    The name keys logging and `self.unique_name`. Persistent storage, web routes, and the CLI still address an instance by its app key and index (its zero-based position among the app's `config` blocks). The CLI's `--instance` flag resolves a name to its index.

## Typed Configuration

The values supplied under `config` are validated at startup against an [`AppConfig`][hassette.app.app_config.AppConfig] subclass defined in Python. A missing required field or a type mismatch fails that instance with a Pydantic `ValidationError`, logged with the field name and expected type. Other apps and instances still start. [Apps](../apps/index.md) covers defining the model — including [secret fields](index.md#secret-fields) (typed `SecretStr`, masked in the dashboard) and [presentation metadata](index.md#presentation-metadata) (the `ui` hints that control how each field renders).

## Developer Settings {#developer-settings}

`AppConfig` includes three developer-facing fields:

- **`framework_log_level`** (a log level name such as `"DEBUG"`, or `None`): Level for the lines Hassette writes about this instance: its lifecycle, bus, scheduler, API, state and task lines. The app's own `log_level` is unaffected. `None` (the default) leaves those lines at their `logging.*` levels. See [Per-App Log Levels](../../operating/log-levels.md#hassettes-lines-about-one-app).

- **`forgotten_await_behavior`** (`"ignore"` / `"warn"` / `"error"` or `None`): Per-app override for what happens when a protected method is called without `await`. `None` (the default) falls back to the global `forgotten_await_behavior` setting in `hassette.toml`.

    ```python
    --8<-- "pages/core-concepts/apps/snippets/app_config_forgotten_await.py"
    ```

    `ForgottenAwaitBehavior` is imported from `hassette` — the snippet above shows the full import. Use `"error"` for apps under active development to surface forgotten `await` calls at runtime. Use `"warn"` (or `None` to inherit the global default) for production apps. See [Global Settings](../configuration/index.md#developer-settings) for the global default.

- **`blocking_io_behavior`** (`"ignore"` / `"warn"` / `"error"` or `None`): Per-app override for blocking-call detection behavior. `None` (the default) falls back to the global `blocking_io.behavior` setting in `hassette.toml`, which itself defaults to `"warn"`.

    ```python
    --8<-- "pages/core-concepts/apps/snippets/app_config_blocking_io.py"
    ```

    `BlockingIOBehavior` is imported from `hassette`. Set to `"ignore"` to suppress both the warning and the `blocking_events` DB row for this app — useful when migrating legacy code that uses synchronous I/O. Set to `"error"` to escalate detections to raised exceptions (via `filterwarnings("error")`). See [Blocking-Call Detection](../blocking-io-detection.md) for context and [Global Settings](../configuration/index.md#blocking-io-detection) for the global defaults.

## Next Steps

- [Apps overview](index.md): defining `AppConfig` models, accessing config values, and app structure
- [Global Configuration](../configuration/index.md): `hassette.toml` settings outside the `[apps]` section
- [Lifecycle](lifecycle.md): what happens after Hassette loads and validates the app config
