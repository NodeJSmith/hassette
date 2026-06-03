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

`config/` holds your token and settings. `apps/` holds your automation code.

### Step 2: Create docker-compose.yml

```yaml
--8<-- "pages/getting-started/docker/snippets/docker-compose.yml"
```

The volumes break down like this:

- `./config` and `./apps` mount your local directories into the container.
- `data` and `uv_cache` are named volumes for persistent data and the package cache.

Port `8126` exposes the web UI. It is unauthenticated, so keep it off public networks. Set `TZ` to your local timezone so scheduled automations fire at the right times.

### Step 3: Create config/.env

```bash
--8<-- "pages/getting-started/docker/snippets/env-file.sh"
```

Replace `your_long_lived_access_token_here` with your token. Set `HASSETTE__BASE_URL` to your Home Assistant's address, like `http://192.168.1.100:8123`. If HA runs in Docker on the same network, use the container name instead.

Hassette reads `/config/.env` automatically on startup. You do not need an `env_file:` directive in the compose file.

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
INFO hassette ... ─ Connected to Home Assistant
```

Hassette is running.

## Write Your First App

Create `apps/my_app.py`:

```python
--8<-- "pages/getting-started/docker/snippets/my_app.py"
```

[`App`](../../core-concepts/apps/index.md) runs your automation logic and gives you access to the bus, scheduler, and API. [`AppConfig`](../../core-concepts/configuration/applications.md) loads and validates your app's settings from the environment. `on_initialize` runs once when the app starts.

Restart the container to pick up the new file:

```bash
docker compose restart hassette
```

Check the logs again. You see `Hello from Docker!` from your app:

```
INFO hassette.MyApp.0 ... ─ Hello from Docker!
```

!!! tip "Having trouble?"
    If Hassette fails to connect, check `HASSETTE__BASE_URL` and your token in `config/.env`. See [Troubleshooting](troubleshooting.md) for common issues.

From here, see [First Automation](../first-automation.md) to subscribe to Home Assistant events and control devices.

## Next Steps

- [First Automation](../first-automation.md) — subscribe to events, control devices
- [Managing Dependencies](dependencies.md) — add Python packages to your setup
- [Image Tags](image-tags.md) — pick a stable tag for production
- [Troubleshooting](troubleshooting.md) — diagnose connection and startup problems
