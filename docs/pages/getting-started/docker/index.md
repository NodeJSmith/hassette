# Docker Setup

Run Hassette in a container with Docker Compose.

## Prerequisites

- **Docker and Docker Compose** installed on the host machine.
- **A running Home Assistant instance** with a long-lived access token. See [Creating a Home Assistant Token](../ha_token.md) for how to generate one.

## Quick Start

### Step 1: Create the project

```bash
--8<-- "pages/getting-started/docker/snippets/mkdir-project.sh"
```

`project_dir` is a placeholder — name the directory whatever you like. `config/` holds your token and settings. `apps/` holds your automation code.

### Step 2: Create docker-compose.yml

```yaml
--8<-- "pages/getting-started/docker/snippets/docker-compose.yml"
```

The `image:` line pulls Hassette from GitHub Container Registry (`ghcr.io`) — Docker downloads it automatically on first run. The volumes break down like this:

- `./config` and `./apps` mount your local directories into the container.
- `data` and `uv_cache` are named volumes for persistent data and the package cache. Docker Compose creates them automatically — no action needed.

Port `8126` exposes the web UI. It is unauthenticated, so keep it off public networks. Set `TZ` to your local timezone so scheduled automations fire at the right times.

### Step 3: Create config/.env

```bash
--8<-- "pages/getting-started/docker/snippets/env-file.sh"
```

Replace `your_long_lived_access_token_here` with your token. Set `HASSETTE__BASE_URL` to your Home Assistant's address, like `http://192.168.1.100:8123` — when in doubt, use the IP address. The container-name form (`http://homeassistant:8123`) only works when HA also runs in Docker on the same Docker network.

The `__` double underscore is how Hassette maps environment variables to nested settings — `HASSETTE__TOKEN` sets `token`. Hassette reads `/config/.env` automatically on startup; you do not need an `env_file:` directive in the compose file.

### Step 4: Start it

```bash
--8<-- "pages/getting-started/docker/snippets/docker-compose-up.sh"
```

Check the logs:

```bash
--8<-- "pages/getting-started/docker/snippets/docker-compose-logs-hassette.sh"
```

You see output like:

```
INFO hassette ... ─ Hassette is running.
```

Hassette is running, and the web UI is available at `http://localhost:8126`. If you see an error instead of this line, head to [Troubleshooting](troubleshooting.md).

## Write Your First App

Create `apps/my_app.py`:

```python
--8<-- "pages/getting-started/docker/snippets/my_app.py"
```

[`App`](../../core-concepts/apps/index.md) runs your automation logic and gives you access to the bus (subscribes to HA events), the scheduler (runs code on a timer), and the API (calls HA services). [`AppConfig`](../../core-concepts/apps/configuration.md) loads and validates your app's settings from the environment, including `config/.env`. `on_initialize` runs once when the app starts.

Two pieces of syntax worth knowing: `App[MyAppConfig]` pairs your app with its config class — that's how `self.app_config` knows its type. And lifecycle hooks like `on_initialize` are `async def` — Hassette runs the event loop for you, so you can follow the pattern without prior async experience.

Restart the container to pick up the new file:

```bash
docker compose restart hassette
```

Check the logs again. You see `Hello from Docker!` from your app:

```
INFO hassette.MyApp.0 ... ─ Hello from Docker!
```

!!! tip "Having trouble?"
    If Hassette fails to connect, check `HASSETTE__BASE_URL` and your token in `config/.env`. If your app doesn't show up in the logs, see [Troubleshooting](troubleshooting.md) for app-loading and other common issues.

From here, see [First Automation](../first-automation.md) to subscribe to Home Assistant events and control devices.

## Next Steps

- [First Automation](../first-automation.md): subscribe to events, control devices
- [Managing Dependencies](dependencies.md): add Python packages to your setup
- [Image Tags](image-tags.md): pick a stable tag for production
- [Troubleshooting](troubleshooting.md): diagnose connection and startup problems
