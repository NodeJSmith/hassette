# Docker Deployment

This guide walks through deploying Hassette with Docker Compose, the recommended way to run Hassette in production.

!!! tip "Why Docker?"
    Docker provides isolation, easy updates, consistent environments across machines, and automatic restarts.

## Prerequisites

- Docker and Docker Compose installed
- A running Home Assistant instance
- A long-lived access token from your Home Assistant profile

!!! note

    If you don't have a token yet, you can follow the steps in the [Creating a Home Assistant token](../ha_token.md) guide.

## Quick Start

The fastest way to get started is to use the pre-built image from GitHub Container Registry:

1. **Create project directory**

```bash
# Create directory structure
mkdir project_dir && cd project_dir
mkdir -p config apps
```

2. **Create Docker Compose file**

Create `docker-compose.yml` in `project_dir`:

```yaml
--8<-- "pages/getting-started/docker/snippets/docker-compose.yml"
```

1. **Start Hassette**

```bash
docker compose up -d
```

Now configure Hassette by creating `config/hassette.toml` and `config/.env` - see [Configuration](#configuration) below.

## Directory Structure

Hassette expects the following directory structure when running in Docker:

```
project_dir/
├── docker-compose.yml
├── config/
│   ├── hassette.toml      # Hassette configuration
│   └── .env               # Secrets (HA token, etc.)
└── apps/
    ├── my_app.py          # Your app files
    └── another_app.py
```

The Docker image uses four volumes:

| Mount Point | Description                                              |
| ----------- | -------------------------------------------------------- |
| `/config`   | Configuration files (mounted from `./config`)            |
| `/apps`     | Your application code (mounted from `./apps`)            |
| `/data`     | Persistent data storage (Docker volume)                  |
| `/uv_cache` | Python package cache for faster restarts (Docker volume) |

!!! note "Package Structure"
    For simple setups, just put `.py` files in `./apps`. For more complex projects with dependencies, see [Managing Dependencies](dependencies.md).

## Configuration

### Home Assistant Token

Create `config/.env` with your Home Assistant token:

```bash
# config/.env
HASSETTE__TOKEN=your_long_lived_access_token_here
```

!!! note
    If you do not yet have a token, follow the steps in the [Creating a Home Assistant token](../ha_token.md) guide.

!!! warning "Security"
    Never commit `.env` files to version control. Add `config/.env` to your `.gitignore`.

### Hassette Configuration

Create `config/hassette.toml`:

```toml
--8<-- "pages/getting-started/docker/snippets/hassette.toml"
```

### Create Your First App

Create `apps/my_app.py`:

```python
--8<-- "pages/getting-started/docker/snippets/my_app.py"
```

### Start Hassette

```bash
docker compose up -d
```

Check the logs:

```bash
docker compose logs -f hassette
```

You should see Hassette connect to Home Assistant and load your apps.

## Production Deployment

### Hot Reloading in Production

Hassette supports hot reloading, but it's disabled by default in production. To enable:

```toml
[hassette]
dev_mode = false  # Keep production mode
allow_reload_in_prod = true  # But allow file watching
watch_files = true
```

Now Hassette will automatically restart apps when you change files in `./apps/`.

!!! warning "Performance"
    File watching adds overhead. Only enable if you need it.

## Viewing Logs

### Docker Compose Logs

```bash
# Follow all logs
docker compose logs -f

# Just Hassette
docker compose logs -f hassette

# Last 100 lines
docker compose logs --tail=100 hassette
```

### Using Dozzle (Optional)

Hassette does not yet have a UI, but you can enhance your logging experience with [Dozzle](https://dozzle.dev/), a lightweight log viewer for Docker containers.

```yaml
--8<-- "pages/getting-started/docker/snippets/dozzle-service.yml"
```

Access Dozzle at `http://localhost:8080` for a web-based log viewer with filtering, search, and multi-container support.

## Environment Variables Reference

Override any configuration via environment variables using the `HASSETTE__` prefix:

| Variable                           | Description                                                                 |
| ---------------------------------- | --------------------------------------------------------------------------- |
| `HASSETTE__TOKEN`                  | Home Assistant long-lived access token                                      |
| `HASSETTE__BASE_URL`               | Home Assistant URL (e.g., `http://homeassistant:8123`)                      |
| `HASSETTE__APP_DIR`                | Directory containing your app Python files                                  |
| `HASSETTE__PROJECT_DIR`            | Directory containing `pyproject.toml`/`uv.lock` for dependency installation |
| `HASSETTE__CONFIG_DIR`             | Directory containing configuration files                                    |
| `HASSETTE__LOG_LEVEL`              | Logging level (`debug`, `info`, `warning`, `error`)                         |
| `HASSETTE__ALLOW_UNLOCKED_PROJECT` | Set to `1` to allow installing from `pyproject.toml` without a lockfile     |
| `TZ`                               | System timezone (e.g., `America/New_York`)                                  |

See [Managing Dependencies](dependencies.md) for details on `HASSETTE__APP_DIR` and `HASSETTE__PROJECT_DIR`.

## Next Steps

- [Managing Dependencies](dependencies.md) - Install Python packages for your apps
- [Networking](networking.md) - Connect to Home Assistant
- [Image Tags](image-tags.md) - Choose the right Docker image
- [Troubleshooting](troubleshooting.md) - Common issues and solutions

## See Also

- [Getting Started](../index.md) - Local development setup
- [Configuration](../../core-concepts/configuration/index.md) - Complete configuration reference
- [Apps](../../core-concepts/apps/index.md) - Writing and structuring apps
- [Examples](https://github.com/NodeJSmith/hassette/tree/main/examples) - Example apps and configurations
