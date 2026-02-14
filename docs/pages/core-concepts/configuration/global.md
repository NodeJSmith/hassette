# Global Settings

Global settings control how Hassette runs and connects to Home Assistant. These are defined under the `[hassette]` table in `hassette.toml`.

## Connection Settings

- **`base_url`** (string): Home Assistant URL.
    - Default: `http://127.0.0.1:8123`
    - Must include the scheme (`http://` or `https://`) and port.

- **`verify_ssl`** (boolean): Whether to verify SSL certificates when connecting to Home Assistant.
    - Default: `true`
    - Set to `false` if using self-signed certificates.

- **`import_dot_env_files`** (boolean): Whether to load `.env` file contents into `os.environ`.
    - This is useful to allow apps to access these values without needing to import the file.
    - Default: `true`

## Runtime Settings

- **`app_dir`** (string): Directory containing your app modules.
    - Default: `.` (current directory)
    - Example: `src/apps`

- **`dev_mode`** (boolean): Enable development features.
    - **Heuristics**: If not explicitly set, Hassette detects dev mode by checking for:
        - `debugpy` or `pydevd` in `sys.modules`
        - `sys.gettrace()` being set
        - `sys.flags.dev_mode` being enabled
    - **Features Enabled**:
        - Automatic file watching and hot reloading.
        - Extended timeouts for tasks and connections.
        - Skipping some strict startup pre-checks.

## Storage Settings

- **`data_dir`** (string): Directory where Hassette stores persistent data.
    - Default: `~/.hassette`
    - Used for [persistent cache](../persistent-storage.md) storage and other data files.
    - Each resource class gets its own subdirectory: `{data_dir}/{ClassName}/cache/`

- **`default_cache_size`** (integer): Maximum size in bytes for each resource's disk cache.
    - Default: `104857600` (100 MiB)
    - When the limit is reached, least recently used items are automatically evicted.
    - See [Persistent Storage](../persistent-storage.md) for usage details.

**Example:**

```toml
[hassette]
data_dir = "/var/lib/hassette"
default_cache_size = 209715200  # 200 MiB
```

## Web UI Settings

These settings control the built-in [web UI](../../web-ui/index.md) and the underlying web API service.

- **`run_web_api`** (boolean): Whether to run the web API service (REST API, healthcheck, and UI backend).
    - Default: `true`

- **`run_web_ui`** (boolean): Whether to serve the browser dashboard. Only used when `run_web_api` is `true`.
    - Default: `true`

- **`web_api_host`** (string): Host to bind the web API server to.
    - Default: `0.0.0.0`

- **`web_api_port`** (integer): Port to run the web API server on.
    - Default: `8126`
    - The UI is accessible at `http://<host>:<port>/ui/`

- **`web_api_cors_origins`** (tuple): Allowed CORS origins for the web API.
    - Default: `("http://localhost:3000", "http://localhost:5173")`

- **`web_api_event_buffer_size`** (integer): Maximum number of recent events to keep in the ring buffer.
    - Default: `500`

- **`web_api_log_buffer_size`** (integer): Maximum number of log entries to keep in the ring buffer.
    - Default: `2000`

**Example:**

```toml
[hassette]
run_web_ui = true
web_api_port = 8126
```

## Basic Example

```toml
--8<-- "pages/core-concepts/configuration/snippets/basic_config.toml"
```

## See Also

- [Authentication](auth.md) - Tokens and secrets
- [Applications](applications.md) - App registration and configuration
- [Persistent Storage](../persistent-storage.md) - Using the disk cache
