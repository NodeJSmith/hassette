# Configuration Files

If you haven't run Hassette yet, follow the [First Run](first-run.md) first.

This page is a short reference for config discovery, overrides, and where to put secrets.

## File discovery

Configuration files are TOML and can define both global Hassette settings and app-specific settings.

Hassette searches for `hassette.toml` in:

1. `/config/hassette.toml`
2. `./hassette.toml` (current working directory)
3. `./config/hassette.toml`

`.env` files are searched in:

1. `/config/.env`
2. `./.env` (current working directory)
3. `./config/.env`

Override either with `--config-file / -c` or `--env-file / -e`.

```bash
hassette -c ./config/hassette.toml -e ./config/.env
```

## Secrets (token)

If you haven't already generated a token, you can follow the steps in the [Creating a Home Assistant token](ha_token.md) guide. Provide the token through one of:

- Environment variables: `HASSETTE__TOKEN` (recommended).
- CLI arguments: `--token` / `-t`.

!!! note "Compat env vars"
    Hassette also accepts `HOME_ASSISTANT_TOKEN` and `HA_TOKEN` for compatibility.

!!! warning
    Never store your token directly in `hassette.toml`, as it may be committed to version control. Use environment variables or `.env` files instead.

## Minimal example

Use the config file to set Hassette defaults and register apps:

```toml
--8<-- "pages/getting-started/snippets/hassette.toml"
```

Run Hassette with no CLI flags and it will pick up this configuration (or provide `-c` if the file lives elsewhere):

```bash
hassette
# or
hassette -c ./path/to/hassette.toml
```

!!! tip
    If your environment doesn't expose the `hassette` command, you can run `python -m hassette` instead.

You should now see the greeting defined in TOML.

![Hassette logs showing greeting from config file](../../_static/getting-started-config-logs.png)

## Next steps

- Full configuration reference: [Configuration Overview](../core-concepts/configuration/index.md)
- App registration/config: [Application Configuration](../core-concepts/configuration/applications.md)
- Typed app config models: [App Configuration](../core-concepts/apps/configuration.md)
