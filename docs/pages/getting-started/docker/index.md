# Docker Deployment

This guide walks through deploying Hassette with Docker Compose, the recommended way to run Hassette in production.

!!! tip "Why Docker?"
    Docker provides isolation, easy updates, consistent environments across machines, and automatic restarts. If you're already running Home Assistant in Docker, adding Hassette is straightforward.

## Prerequisites

- Docker and Docker Compose installed
- A running Home Assistant instance
- A long-lived access token from your Home Assistant profile

## Quick Start

The fastest way to get started is to use the pre-built image from GitHub Container Registry:

```bash
# Create directory structure
mkdir project_dir && cd project_dir
mkdir -p config apps

# Create docker-compose.yml
cat > docker-compose.yml << 'EOF'
services:
  hassette:
    image: ghcr.io/nodejsmith/hassette:latest-py3.13
    container_name: hassette
    restart: unless-stopped
    volumes:
      - ./config:/config
      - ./apps:/apps
      - data:/data
      - uv_cache:/uv_cache
    environment:
      - LOG_LEVEL=info
      - TZ=America/New_York  # Set your timezone
    healthcheck:
      test: ["CMD", "curl", "-f", "http://127.0.0.1:8126/healthz"]
      interval: 10s
      timeout: 5s
      retries: 3

volumes:
  uv_cache:
  data:
EOF

# Start the container
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

!!! warning "Security"
    Never commit `.env` files to version control. Add `config/.env` to your `.gitignore`.

### Hassette Configuration

Create `config/hassette.toml`:

```toml
[hassette]
base_url = "http://homeassistant:8123"  # or your HA URL
app_dir = "/apps"  # absolute path inside container

[apps.my_app]
filename = "my_app.py"
class_name = "MyApp"
enabled = true

[[apps.my_app.config]]
# Your app-specific configuration
instance_name = "my_app"
```

### Create Your First App

Create `apps/my_app.py`:

```python
from hassette import App, AppConfig


class MyAppConfig(AppConfig):
    greeting: str = "Hello from Docker!"


class MyApp(App[MyAppConfig]):
    async def on_initialize(self):
        self.logger.info(self.app_config.greeting)
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

### Complete docker-compose.yml Example

Here's a production-ready setup:

```yaml
services:
  hassette:
    image: ghcr.io/nodejsmith/hassette:latest-py3.13
    container_name: hassette
    restart: unless-stopped

    volumes:
      - ./config:/config
      - ./apps:/apps
      - data:/data
      - uv_cache:/uv_cache

    environment:
      - LOG_LEVEL=info
      - TZ=America/New_York

    networks:
      - homeassistant

    healthcheck:
      test: ["CMD", "curl", "-f", "http://127.0.0.1:8126/healthz"]
      interval: 30s
      timeout: 5s
      retries: 3
      start_period: 40s

volumes:
  uv_cache:
  data:

networks:
  homeassistant:
    external: true
    name: homeassistant_default
```

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

For a better logging experience, add [Dozzle](https://dozzle.dev/) to your stack:

```yaml
services:
  dozzle:
    container_name: dozzle
    image: amir20/dozzle:latest
    volumes:
      - /var/run/docker.sock:/var/run/docker.sock
    ports:
      - 8080:8080
    environment:
      - DOZZLE_ENABLE_ACTIONS=true

  hassette:
    # ... your hassette config ...
```

Access Dozzle at `http://localhost:8080` for a web-based log viewer with filtering, search, and multi-container support.

## Building Your Own Image

For custom requirements or private registries, build your own image:

```bash
# Clone the repository
git clone https://github.com/NodeJSmith/hassette.git
cd hassette

# Build
docker build -t my-hassette:latest-py3.13 .

# Use in docker-compose.yml
```

```yaml
services:
  hassette:
    build:
      context: /path/to/hassette
      dockerfile: Dockerfile
    # ... rest of config ...
```

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
