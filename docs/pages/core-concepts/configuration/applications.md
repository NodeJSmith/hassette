# Application Configuration

This page covers the **TOML side** of app configuration: registering apps in `hassette.toml`, supplying config values, and running multiple instances. For how to define typed `AppConfig` models in Python, see [App Configuration](../apps/configuration.md).

Apps are registered and configured in the `hassette.toml` file under `[apps.<name>]`.

## App Registration

Each app block requires:

- **`filename`** (or `file_name`): Path to the python file relative to `app_dir`.
    - Should include the extension (e.g., `.py`), though Hassette will attempt to guess if missing.
    - Supports subdirectories (e.g., `subdir/my_app.py`).

- **`class_name`** (or `class`, `module`, `module_name`): Name of the `App` subclass to load.
    - If multiple classes exist in the file, this field disambiguates which one to load.

!!! tip
    Prefer `class_name` and `filename` in docs and new configs; the alternative keys exist for compatibility.

**Optional fields:**

- **`enabled`**: Set to `false` to disable the app without removing the config block.
- **`display_name`**: Friendly name for logs; defaults to the class name.

### Single Instance

```toml
--8<-- "pages/core-concepts/configuration/snippets/single_instance.toml"
```

## App Configuration Parameters

You can pass configuration parameters to your apps using the `config` field.

- **Single instance**: `config = { key = "value" }` or `[apps.name.config]`
- **Multiple instances**: `[[apps.name.config]]` (recommended)

!!! note "Paths"
    `app_dir` is resolved to an absolute path at startup. Relative paths are resolved relative to the current working directory.

!!! note "Filename extension"
    If `filename` has no extension, Hassette assumes `.py`.

**Environment Variable Overrides:**

You can override nested config values using environment variables. This merges with any TOML configuration (env vars take precedence).

- Pattern: `HASSETTE__APPS__<APP_NAME>__CONFIG__<KEY>`
- Example: `HASSETTE__APPS__MY_APP__CONFIG__SOME_OPTION=true` overrides `some_option` for `my_app`.

### Multiple Instances

To run the same app multiple times with different configurations, use `[[apps.<name>.config]]` blocks.

```toml
--8<-- "pages/core-concepts/configuration/snippets/multiple_instances.toml"
```

## Typed Configuration

The `config` values supplied in TOML are validated against an `AppConfig` subclass that you define in Python. Hassette raises a configuration error at startup if any required field is missing or has the wrong type. For how to define that model, see [App Configuration](../apps/configuration.md).

## See Also

- [App Configuration](../apps/configuration.md) - Defining typed `AppConfig` models in Python
- [Global Settings](global.md) - Runtime and connection settings
- [Authentication](auth.md) - Tokens and secrets
