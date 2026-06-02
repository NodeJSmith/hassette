# Docker Setup

## Prerequisites

- [Docker](https://docs.docker.com/get-docker/) and [Docker Compose](https://docs.docker.com/compose/install/) installed
- A running Home Assistant instance
- A long-lived access token from your HA profile. See [Creating a Home Assistant token](../ha_token.md)

## Quick Start

### 1. Create your project directory

```bash
--8<-- "pages/getting-started/docker/snippets/mkdir-project.sh"
```

### 2. Create the Compose file

```yaml
--8<-- "pages/getting-started/docker/snippets/docker-compose.yml"
```

Save this as `docker-compose.yml` in `project_dir`.

### 3. Create your `.env` file

```bash
--8<-- "pages/getting-started/docker/snippets/env-file.sh"
```

Save this as `config/.env`. Replace `your_long_lived_access_token_here` with the token you generated. Add `config/.env` to your `.gitignore` to keep it out of version control.

### 4. Create `hassette.toml`

```toml
--8<-- "pages/getting-started/docker/snippets/hassette.toml"
```

Save this as `config/hassette.toml`. Set `base_url` to your Home Assistant URL. If HA runs on the same machine, `http://homeassistant:8123` works when both containers share a Docker network. Use your HA's IP or hostname otherwise.

### 5. Write your first app

```python
--8<-- "pages/getting-started/docker/snippets/my_app.py"
```

Save this as `apps/my_app.py`. `App` lets you subscribe to HA events and control devices. `AppConfig` defines typed settings your app reads from `hassette.toml`. `on_initialize` runs once when Hassette loads the app.

### 6. Start Hassette

```bash
--8<-- "pages/getting-started/docker/snippets/docker-compose-up.sh"
```

Check that it connected:

```bash
--8<-- "pages/getting-started/docker/snippets/docker-compose-logs-hassette.sh"
```

You should see `Connected to Home Assistant` in the output.

!!! warning "Web UI security"
    The Compose file exposes port `8126` with no authentication. Anyone on your network can view, start, stop, and reload your automations. For remote servers, bind to `127.0.0.1` via `host` under `[hassette.web_api]`. You can also place Hassette behind a reverse proxy. See [Web UI](../../web-ui/index.md) for details.

## Directory Structure

After the quick start, your project looks like this:

```
--8<-- "pages/getting-started/docker/snippets/dir-structure.txt"
```

The Docker image mounts four paths:

| Mount | Purpose |
|---|---|
| `/config` | Configuration files: `hassette.toml`, `.env` |
| `/apps` | Your app Python files |
| `/data` | Persistent data storage: telemetry database |
| `/uv_cache` | Python package cache for faster restarts |

For projects with external Python dependencies, see [Managing Dependencies](dependencies.md).

## Configuration

### Home Assistant Token

Hassette reads the token from `HASSETTE__TOKEN` in your `.env` file. The [Creating a Home Assistant token](../ha_token.md) page shows how to generate one.

### Environment Variables Reference

Any setting from `hassette.toml` can be overridden with a `HASSETTE__` environment variable. Set these in `docker-compose.yml` under `environment`, or add them to `config/.env`.

| Variable | Description |
|---|---|
| `HASSETTE__TOKEN` | Home Assistant long-lived access token |
| `HASSETTE__BASE_URL` | Home Assistant URL, e.g. `http://homeassistant:8123` |
| `HASSETTE__APPS__DIRECTORY` | Directory containing your app files |
| `HASSETTE__PROJECT_DIR` | Directory containing `pyproject.toml` and `uv.lock` for dependency installation |
| `HASSETTE__CONFIG_DIR` | Directory containing configuration files |
| `HASSETTE__LOG_LEVEL` | Log level: `debug`, `info`, `warning`, or `error` |
| `HASSETTE__INSTALL_DEPS` | Set to `1` to discover and install `requirements.txt` at startup |
| `HASSETTE__PRUNE_UV_CACHE` | Set to `0` to skip `uv cache prune` at startup (default: `1`) |
| `TZ` | System timezone, e.g. `America/New_York` |

For a full configuration reference, see [Configuration](../../core-concepts/configuration/index.md).

## Production Deployment

### Hot Reloading in Production

```toml
--8<-- "pages/getting-started/docker/snippets/prod-reload.toml"
```

Hassette watches for file changes in `./apps/`, but reloads require an explicit opt-in outside dev mode. Add the snippet above to `config/hassette.toml`.

With `allow_reload_in_prod = true`, saving a file in `./apps/` restarts only the affected app. File watching adds overhead. Only enable it if your workflow requires in-place updates to a running container.

### Graceful Shutdown

`docker stop` and `docker compose down` send `SIGTERM`. Hassette catches it, finalizes the active session, and drains pending database writes. All connections close before the process exits.

The Compose file sets `stop_grace_period: 45s`. Docker's default of 10 seconds is too short. The process gets force-killed before shutdown completes, leaving sessions marked as `unknown` on next startup.

If you override `total_shutdown_timeout_seconds` in your config, set `stop_grace_period` to at least 15 seconds more.

## Viewing Logs

### Docker Compose Logs

```bash
--8<-- "pages/getting-started/docker/snippets/docker-compose-logs.sh"
```

### Web UI

The web UI at `http://<host>:8126/ui/` shows live app status, handler details, log streaming, and system configuration. It starts with the container. See [Web UI](../../web-ui/index.md) for a full tour.

## Next Steps

- [Managing Dependencies](dependencies.md) — Install Python packages for your apps
- [Image Tags](image-tags.md) — Pick a versioned or Python-specific image tag
- [Write Your First Automation](../first-automation.md) — Subscribe to HA events and control devices
- [Troubleshooting](troubleshooting.md) — Common issues and solutions
