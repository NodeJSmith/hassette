# App Configuration

Each app can define a Pydantic configuration model to validation its settings. This allows you to benefit from type safety and automatic parsing of configuration files.

## Defining Config Models

Inherit from [`AppConfig`][hassette.app.app_config.AppConfig] to define your configuration schema.

```python
--8<-- "pages/core-concepts/apps/snippets/app_config_definition.py"
```

## Base Fields

The base `AppConfig` includes standard fields available to all apps:

- `instance_name: str | None` - Used for logging and identification.
- `log_level: str | None` - Optional log-level override; defaults to the global setting.

## TOML Configuration

You can configure your apps in `hassette.toml`.

```toml
--8<-- "pages/core-concepts/apps/snippets/app_config.toml"
```

## Secrets & Environment Variables

`AppConfig` inherits from Pydantic's `BaseSettings`, so it supports environment variable injection out of the box.

Standard naming convention for nested config is:
`HASSETTE__APPS__<APP_NAME>__CONFIG__<FIELD_NAME>`

### Custom Prefix

You can simplify environment variable names by defining a custom `env_prefix`:

```python
--8<-- "pages/core-concepts/apps/snippets/app_config_env_prefix.py"
```

Now you can set `MYAPP_API_KEY` in your environment or `.env` file.
