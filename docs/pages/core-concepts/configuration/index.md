# Configuration

This guide walks through the most common Hassette configuration options. It isn’t exhaustive, but covers everything you need for a smooth first run.

!!! info "First time here?"
    Start with the [Getting Started guide](../../getting-started/index.md) if you haven’t already created your first app.

!!! note "Full reference"
    See the [HassetteConfig][hassette.config.config.HassetteConfig] docs for a complete list of configuration options and environment variables.

Hassette really only needs two things: your Home Assistant URL and an access token. Provide the URL via TOML or environment variables; keep the token out of source control by using env vars or CLI flags.

## Specifying file locations

Hassette searches for `hassette.toml` and `.env` in this order:

1. `/config` — what is typically used in Docker setups.
2. `./` — current working directory.
3. `./config` — `config` subdirectory of the current working directory.

Override either path with `--config-file / -c` and `--env-file / -e`:

```bash
# override both config and env file locations
uv run hassette -c ./config/hassette.dev.toml -e ./config/.dev.env
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

### Global configuration

Non-app configuration can either be set in the `[hassette]` block or at the top level (not under any heading). There are too many configuration
options to enumerate here, but the most important are:

- `base_url` – Home Assistant URL (defaults to `http://127.0.0.1:8123`).
  - This needs to be the full URL including scheme (`http://` or `https://`) and port (if non-standard, including `:8123`).
  - Use `verify_ssl` to disable SSL verification for self-signed certificates.
- `app_dir` – Directory containing your app modules (e.g., `src/apps`).
- `dev_mode` – Enable dev mode features like auto-reloading
  - By default this will use heuristics to determine if dev mode should be enabled
    - Will check if `debugpy` is in `sys.modules`
    - Will check if `sys.gettrace()` is set
    - Will check if `sys.flags.dev_mode` is set
  - If `dev_mode` is enabled Hassette will
    - watch for file changes and auto-reload apps
    - extend timeouts for task completion and connections
    - allow Hassette to continue startup if apps fail the pre-check
- `import_dot_env_files` - Whether to call `load_dotenv()` on the `.env` file(s) found by Hassette
  - This is useful if you want the variables in your `.env` file(s) to be available via `os.environ` for other libraries that read from environment variables directly.

!!! note
    In Docker, mount your apps at `/apps` and your config at `/config` for the default paths to work without overrides.

### App configuration

App configuration lives under the `[apps.<name>]` heading, where `<name>` is a unique identifier for the app. Each app *requires* the following fields:

- `filename` – Module inside `app_dir` that contains the app class.
  - Can also be provided as `file_name` for people like me who never remember which way to spell it.
  - Should include the extension (e.g., `my_app.py`), but Hassette will attempt to add it if missing.
  - Should be a relative path inside `app_dir` - if you have subdirectories, include them (e.g., `subdir/my_app.py`).
- `class_name` – Class to import from that module.
  - Can also be provided as `class`, `module`, or `module_name` for flexibility.
  - If you have multiple classes in the module, Hassette will only import the one you specify here.

Other optional fields include:

- `enabled` – Optional; defaults to `true`. Disable an app without removing its block.
- `display_name` – Optional friendly label; defaults to the class name.
- `config` – Configuration to provide to the app instance(s).
  - While you can use an inline table (e.g., `config = { some_option = true }`), it may be simpler to default to using a list of tables (`[[apps.<name>.config]]`), even for a single instance.
  - Each `config` entry will be validated against your app’s `AppConfig` subclass, so you can declare multiple instances of the same app with different settings.
  - Configuration can also be provided via environment variables (or .env files, etc.), which Hassette will merge with any TOML-provided config (env vars take precedence).
    - For example, for an app named `my_app`, you could set `HASSETTE__APPS__MY_APP__CONFIG__SOME_OPTION=true` to override the `some_option` field in the config.

!!! warning
    If configuration values are provided but the required app fields (`filename` and `class_name`) are missing, Hassette will log a warning and skip loading that app.

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

## Configuration sources (precedence)

Hassette will apply configuration from multiple sources, in the below order of precedence (highest to lowest):

1. CLI flags (`-c`, `--config`, `--token`, `--app-dir`, etc.).
2. Environment variables (e.g., `HASSETTE__TOKEN`, `HASSETTE__BASE_URL`).
3. `.env` files (`/config/.env`, `.env`, `./config/.env` are checked in that order) - `--env-file` or `-e` overrides.
4. File-based secrets (if configured).
5. TOML file (`/config/hassette.toml`, `hassette.toml`, `./config/hassette.toml` are checked in that order) - `--config-file` or `-c` overrides.

Best practice: keep secrets in env vars or `.env`, and leave TOML for non-secret configuration.

!!! note
    CLI flags can be provided at runtime or in Docker Compose files to override defaults without changing config files. These are
    kebab-case versions of the corresponding config keys (e.g., `--app-dir`, `--base-url`).

## See also

- [Core Concepts](../index.md) — back to the core concepts overview
- [Apps](../apps/index.md) — more on app anatomy, lifecycle, and capabilities
- [Scheduler](../scheduler/index.md) — more on scheduling jobs and intervals
- [Bus](../bus/index.md) — more on subscribing to and handling events
- [API](../api/index.md) — more on interacting with Home Assistant's APIs
