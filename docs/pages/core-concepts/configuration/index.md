# Configuration

This guide walks through the most common Hassette configuration options. It isn’t exhaustive, but covers everything you need for a smooth first run.

!!! info "First time here?"
    Start with the [Getting Started guide](../getting-started/index.md) if you haven’t already created your first app.

Hassette really only needs two things: your Home Assistant URL and an access token. Provide the URL via TOML or environment variables; keep the token out of source control by using env vars or CLI flags.

## Specifying file locations

Hassette searches for `hassette.toml` (and `.env`) in this order:

1. `/config/hassette.toml` — handy for Docker.
2. `./hassette.toml` — current working directory.
3. `./config/hassette.toml` — `config` subdirectory.

Override either path with `--config-file / -c` and `--env-file / -e`:

```bash
uvx hassette -c ./config/hassette.toml -e ./config/.env
```

## Home Assistant token

Create a long-lived access token from your Home Assistant profile and supply it via:

- Environment variables: `HASSETTE__TOKEN`, `HOME_ASSISTANT_TOKEN`, or `HA_TOKEN`.
- CLI flags: `--token` / `-t`.

## `hassette.toml`

The TOML file sets global defaults and declares your apps.

```toml
--8<-- "pages/core-concepts/configuration/basic_config.toml"
```

### `[hassette]`

- `base_url` – Home Assistant URL (defaults to `http://127.0.0.1:8123`). If you include a port it’s used for REST and WebSocket calls.
- `app_dir` – Directory containing your app modules (e.g., `src/apps`). A file `my_app.py` inside becomes importable as `apps.my_app`.

!!! note
    In Docker, mount your apps at `/apps` and your config at `/config` for the default paths to work without overrides.

### `[apps.<name>]`

- `enabled` – Optional; defaults to `true`. Disable an app without removing its block.
- `filename` – Module inside `app_dir` that contains the app class.
- `class_name` – Class to import from that module.
- `display_name` – Optional friendly label; defaults to the class name.
- `config` – Inline table for a single instance or repeated tables (`[[apps.<name>.config]]`) for multiple instances.

!!! note
    See the [Apps guide](../apps/index.md) for more on app anatomy, `App` vs `AppSync`, and helpers like `self.api`, `self.bus`, and `self.scheduler`.

Single instance:

```toml
--8<-- "pages/core-concepts/configuration/single_instance.toml"
```

Multiple instances:

```toml
--8<-- "pages/core-concepts/configuration/multiple_instances.toml"
```

!!! note
    The `AppManifest` validator ensures `[apps.<name>]` blocks are well-formed (one per name). Each `config` entry is validated by your custom `AppConfig` subclass, and you can declare as many instances as you need with `[[apps.<name>.config]]`.

## Typed app configuration

Apps inherit from `App`, which is generic on a config type. Subclass `AppConfig` to define fields, defaults, validators, and environment variable handling. Because `AppConfig` extends `pydantic.BaseSettings`, you get all the usual niceties (env vars, `.env`, type coercion).

```python
--8<-- "pages/core-concepts/apps/typed_config_example.py"
```

```toml
--8<-- "pages/core-concepts/apps/typed_config_toml.toml"
```

```bash
export MYAPP_REQUIRED_SECRET="s3cr3t"
# or
export HASSETTE__APPS__MY_APP__CONFIG__REQUIRED_SECRET="s3cr3t"
```

## Common pitfalls

- WebSocket auth fails → set `HASSETTE__TOKEN` or `HOME_ASSISTANT_TOKEN`.
- Import errors → ensure `app_dir` matches your mounted path (keep package names consistent).
- Multiple instances not starting → use `[[apps.<name>.config]]` (list of tables).
- Token checked into TOML → move it to env vars or a `.env` file.

## Configuration sources (precedence)

Hassette merges configuration in “first writer wins” order:

1. CLI flags (`-c`, `--config`, `--token`, `--app-dir`, etc.).
2. Environment variables (prefer the `HASSETTE__*` namespace).
3. `.env` files (checked in the same three default locations as TOML unless `--env-file` is provided).
4. File-based secrets (if configured).
5. TOML files (same default search order; overridden when `-c/--config-file` is supplied).

Best practice: keep secrets in env vars or `.env`, and leave TOML for non-secret configuration.

## See also

- [Core concepts](../index.md)
- [Apps](../apps/index.md)
- [Scheduler](../scheduler/index.md)
- [Bus](../bus/index.md)
- [API](../api/index.md)
