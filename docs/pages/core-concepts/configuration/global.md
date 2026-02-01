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

## Basic Example

```toml
--8<-- "pages/core-concepts/configuration/snippets/basic_config.toml"
```
