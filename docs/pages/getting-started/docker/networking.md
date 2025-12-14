# Networking

This guide covers how to configure networking between Hassette and Home Assistant when running in Docker.

## Overview

Hassette needs to reach Home Assistant's API over HTTP/HTTPS. The best approach depends on how Home Assistant is deployed.

## Connection Methods

### Same Docker Network (Recommended)

If Home Assistant is also running in Docker, use Docker networking for reliable container-to-container communication:

```yaml
services:
  hassette:
    image: ghcr.io/nodejsmith/hassette:latest-py3.13
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

!!! tip "Finding the Network Name"
    Run `docker network ls` to see available networks. If Home Assistant uses Docker Compose, the network is typically named `<project>_default` (e.g., `homeassistant_default`).

### Host Network

Use the host network if Home Assistant runs directly on the host machine (not in Docker):

```yaml
services:
  hassette:
    image: ghcr.io/nodejsmith/hassette:latest-py3.13
    network_mode: host
    # ... other config ...
```

```toml
[hassette]
base_url = "http://127.0.0.1:8123"
```

!!! note "Host Networking Trade-offs"
    Host networking gives the container full access to the host's network stack. This is simpler but provides less isolation.

### Bridge Network with Host Access

To access services on the host while using bridge networking:

```yaml
services:
  hassette:
    image: ghcr.io/nodejsmith/hassette:latest-py3.13
    extra_hosts:
      - "host.docker.internal:host-gateway"
    # ... other config ...
```

```toml
[hassette]
base_url = "http://host.docker.internal:8123"
```

### External URL

Connect to a remote Home Assistant instance over the network or internet:

```toml
[hassette]
base_url = "https://home.example.com"
```

!!! warning "Security"
    When connecting over the internet, always use HTTPS and ensure your Home Assistant instance is properly secured.

## Complete Network Examples

### Example 1: Home Assistant in Docker

Both containers on the same network:

```yaml
# docker-compose.yml
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
      - TZ=America/New_York
    networks:
      - ha_network

volumes:
  data:
  uv_cache:

networks:
  ha_network:
    external: true
    name: homeassistant_default
```

```toml
# config/hassette.toml
[hassette]
base_url = "http://homeassistant:8123"
```

### Example 2: Home Assistant on Host

Hassette container connecting to HA on the host:

```yaml
# docker-compose.yml
services:
  hassette:
    image: ghcr.io/nodejsmith/hassette:latest-py3.13
    container_name: hassette
    restart: unless-stopped
    network_mode: host
    volumes:
      - ./config:/config
      - ./apps:/apps
      - data:/data
      - uv_cache:/uv_cache
    environment:
      - TZ=America/New_York

volumes:
  data:
  uv_cache:
```

```toml
# config/hassette.toml
[hassette]
base_url = "http://127.0.0.1:8123"
```

### Example 3: Remote Home Assistant

Connecting to an external Home Assistant instance:

```yaml
# docker-compose.yml
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
      - TZ=America/New_York

volumes:
  data:
  uv_cache:
```

```toml
# config/hassette.toml
[hassette]
base_url = "https://home.example.com"
```

## Troubleshooting Connectivity

### Can't Connect to Home Assistant

1. **Verify the URL is reachable from the container:**

   ```bash
   docker compose exec hassette curl -I http://homeassistant:8123
   ```

2. **Check if containers are on the same network:**

   ```bash
   docker network inspect homeassistant_default
   ```

3. **Verify Home Assistant container name:**

   ```bash
   docker ps --format "{{.Names}}"
   ```

### Connection Refused

- Ensure Home Assistant is running and accessible
- Check that the port is correct (default: 8123)
- Verify no firewall rules are blocking the connection

### SSL/TLS Errors

When using HTTPS:

- Ensure the certificate is valid
- Check that the hostname matches the certificate
- For self-signed certificates, you may need to configure trust

## See Also

- [Docker Overview](index.md) - Quick start guide
- [Troubleshooting](troubleshooting.md) - Common issues and solutions
