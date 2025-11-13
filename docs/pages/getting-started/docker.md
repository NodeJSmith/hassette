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
mkdir hassette-deploy && cd hassette-deploy
mkdir -p config apps

# Create docker-compose.yml
cat > docker-compose.yml << 'EOF'
services:
  hassette:
    image: ghcr.io/nodejsmith/hassette:latest
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
hassette-deploy/
├── docker-compose.yml
├── config/
│   ├── hassette.toml      # Hassette configuration
│   └── .env               # Secrets (HA token, etc.)
└── apps/
    ├── my_app.py          # Your app files
    └── another_app.py
```

The Docker image creates four volumes:

- `/config` - Configuration files (mounted from `./config`)
- `/apps` - Your application code (mounted from `./apps`)
- `/data` - Persistent data storage (Docker volume)
- `/uv_cache` - Python package cache for faster restarts (Docker volume)

!!! note "Package Structure"
    For simple setups, just put `.py` files in `./apps`. For more complex projects with dependencies, see [Apps with Dependencies](#apps-with-dependencies).

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

## Networking

### Connecting to Home Assistant

Hassette needs to reach Home Assistant's API. There are three common setups:

#### Same Docker Network (Recommended)

If Home Assistant is also running in Docker, use Docker networking:

```yaml
services:
  hassette:
    image: ghcr.io/nodejsmith/hassette:latest
    # ... other config ...
    networks:
      - homeassistant

networks:
  homeassistant:
    external: true
    name: homeassistant_network  # Use your HA network name
```

Then in `config/hassette.toml`:

```toml
[hassette]
base_url = "http://homeassistant:8123"  # container name as hostname
```

#### Host Network

Use the host network if Home Assistant runs directly on the host:

```yaml
services:
  hassette:
    image: ghcr.io/nodejsmith/hassette:latest
    network_mode: host
    # ... other config ...
```

```toml
[hassette]
base_url = "http://127.0.0.1:8123"
```

#### External URL

Connect to a remote Home Assistant instance:

```toml
[hassette]
base_url = "https://home.example.com"
```

## Apps with Dependencies

If your apps need additional Python packages, create a package structure in your `apps` directory:

### Using pyproject.toml

```bash
cd apps
uv init --lib  # or manually create the structure
```

Your `apps` directory should look like:

```
apps/
├── pyproject.toml
├── uv.lock (optional but recommended)
└── src/
    └── my_apps/
        ├── __init__.py
        ├── app_one.py
        └── app_two.py
```

Example `apps/pyproject.toml`:

```toml
[project]
name = "my-hassette-apps"
version = "0.1.0"
requires-python = ">=3.11"
dependencies = [
    "requests>=2.31.0",
    "aiohttp>=3.9.0",
    # your other dependencies
]
```

Update `config/hassette.toml`:

```toml
[hassette]
app_dir = "/apps/src/my_apps"  # point to your package

[apps.app_one]
filename = "app_one.py"
class_name = "AppOne"
```

The Docker startup script automatically detects and installs packages defined in `pyproject.toml`.

### Using requirements.txt

Alternatively, place `requirements.txt` files in `/config` or `/apps`:

```bash
# apps/requirements.txt
requests>=2.31.0
aiohttp>=3.9.0
```

Hassette will automatically discover and install these on container startup.

!!! note "Startup Time"
    Installing dependencies happens at container startup. Use `uv.lock` to speed up subsequent starts, or pre-build a custom image with your dependencies.

## Production Deployment

### Complete docker-compose.yml Example

Here's a production-ready setup with all the bells and whistles:

```yaml
services:
  hassette:
    image: ghcr.io/nodejsmith/hassette:latest
    container_name: hassette
    restart: unless-stopped

    volumes:
      - ./config:/config:ro  # Read-only configuration
      - ./apps:/apps:ro      # Read-only apps
      - data:/data
      - uv_cache:/uv_cache

    environment:
      - LOG_LEVEL=info
      - TZ=America/New_York
      # Optional: override config file location
      # - HASSETTE__CONFIG_FILE=/config/hassette.toml

    networks:
      - homeassistant

    healthcheck:
      test: ["CMD", "curl", "-f", "http://127.0.0.1:8126/healthz"]
      interval: 30s
      timeout: 5s
      retries: 3
      start_period: 40s

    # Resource limits (optional but recommended)
    deploy:
      resources:
        limits:
          memory: 512M
        reservations:
          memory: 256M

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
docker build -t my-hassette:latest .

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

## Troubleshooting

### Container Won't Start

Check the logs:

```bash
docker compose logs hassette
```

Common issues:

- **Token not set**: Ensure `HASSETTE__TOKEN` is in `config/.env`
- **Can't reach Home Assistant**: Check your `base_url` and network configuration
- **Permission errors**: The container runs as user `hassette` (UID 1000). Ensure mounted files are readable.

### Apps Not Loading

1. Check app discovery:
   ```bash
   docker compose exec hassette ls -la /apps
   ```

2. Verify `app_dir` in `hassette.toml` matches the container path (`/apps`)

3. Check for Python syntax errors in your apps

### Dependency Installation Fails

If dependencies fail to install:

1. Check `apps/pyproject.toml` or `requirements.txt` syntax
2. Look for conflicting versions
3. Try pinning exact versions instead of using `>=`

### Health Check Failing

The health check queries `http://127.0.0.1:8126/healthz`. If it fails:

1. Ensure Hassette is starting successfully (check logs)
2. Verify the health service is enabled (it is by default)
3. Check if another service is using port 8126

### Hot Reload Not Working

Ensure:

1. `watch_files = true` in `hassette.toml`
2. Files are mounted as volumes (not copied into image)
3. You're running with `allow_reload_in_prod = true` if not in dev mode

## Environment Variables Reference

Override any configuration via environment variables using the `HASSETTE__` prefix:

```yaml
environment:
  - HASSETTE__TOKEN=your_token
  - HASSETTE__BASE_URL=http://homeassistant:8123
  - HASSETTE__APP_DIR=/apps/src/my_apps
  - HASSETTE__LOG_LEVEL=debug
  - TZ=America/New_York  # System timezone
```

Nested config uses double underscores:

```bash
HASSETTE__APPS__MY_APP__CONFIG__SETTING=value
```

## Next Steps

Now that you have Hassette running in Docker:

- **Build automations**: See [Core Concepts](../core-concepts/index.md) for event handling, scheduling, and API usage
- **Monitor your apps**: Use the health endpoint or add application monitoring
- **Add tests**: See the testing guide (coming soon) for testing your apps
- **Deploy updates**: Run `docker compose pull && docker compose up -d` to update Hassette

## See Also

- [Getting Started](index.md) - Local development setup
- [Configuration](../core-concepts/configuration/index.md) - Complete configuration reference
- [Apps](../core-concepts/apps/index.md) - Writing and structuring apps
- [Examples](https://github.com/NodeJSmith/hassette/tree/main/examples) - Example apps and configurations
