# Troubleshooting

This guide covers common issues when running Hassette in Docker and how to resolve them.

## Container Won't Start

### Check the Logs

Always start by checking the logs:

```bash
docker compose logs hassette
```

For more detail:

```bash
docker compose logs --tail=200 hassette
```

### Common Startup Issues

#### Token Not Set

**Symptom:** Error about missing or invalid token

**Solution:** Ensure `HASSETTE__TOKEN` is set in `config/.env`:

```bash
# config/.env
HASSETTE__TOKEN=your_long_lived_access_token_here
```

#### Can't Reach Home Assistant

**Symptom:** Connection refused or timeout errors

**Solutions:**

1. Verify `base_url` in `hassette.toml` is correct
2. Check network configuration - see [Networking](networking.md)
3. Test connectivity from the container:

   ```bash
   docker compose exec hassette curl -I http://homeassistant:8123
   ```

#### Permission Errors

**Symptom:** Permission denied when reading files

**Solution:** The container runs as user `hassette`. Ensure mounted files are readable:

```bash
chmod -R a+r ./config ./apps
```

## Apps Not Loading

### 1. Check App Discovery

Verify Hassette can see your app files:

```bash
docker compose exec hassette ls -la /apps
```

### 2. Verify APP_DIR Configuration

Ensure `app_dir` in `hassette.toml` matches the container path:

```toml
[hassette]
app_dir = "/apps"  # Must match volume mount
```

If using `src/` layout:

```yaml
environment:
  - HASSETTE__APP_DIR=/apps/src/my_apps
```

### 3. Check for Python Errors

Look for syntax or import errors in the logs:

```bash
docker compose logs hassette | grep -i "error\|exception\|traceback"
```

### 4. Verify App Configuration

Ensure your app is configured in `hassette.toml`:

```toml
[apps.my_app]
filename = "my_app.py"
class_name = "MyApp"
enabled = true
```

## Dependency Installation Fails

### Check Installation Output

Look for installation errors in the logs:

```bash
docker compose logs hassette | grep -i "installing\|error\|failed"
```

### Common Dependency Issues

#### pyproject.toml Not Found

**Symptom:** "No pyproject.toml found" or dependencies not installing

**Solution:** Check `HASSETTE__PROJECT_DIR` points to the right location:

```yaml
environment:
  - HASSETTE__PROJECT_DIR=/apps  # Must contain pyproject.toml
```

Verify the file exists:

```bash
docker compose exec hassette cat /apps/pyproject.toml
```

#### Unlocked Project Not Installing

**Symptom:** Has `pyproject.toml` but no `uv.lock`, dependencies not installing

**Solution:** Either create a lock file or enable unlocked projects:

```bash
# Create lock file (recommended)
uv lock
```

Or enable unlocked projects:

```yaml
environment:
  - HASSETTE__ALLOW_UNLOCKED_PROJECT=1
```

#### Version Conflicts

**Symptom:** Package version conflicts during installation

**Solutions:**

1. Pin exact versions in your dependencies
2. Use `uv.lock` for consistent resolution
3. Check for conflicts with hassette's requirements

#### requirements.txt Not Found

**Symptom:** requirements.txt files not being installed

**Solution:** The startup script looks in `/config` and `/apps`. Ensure files are:

1. Named `requirements*.txt` (e.g., `requirements.txt`, `requirements-dev.txt`)
2. Located somewhere under `/config` or `/apps`
3. Not empty

Check what the container sees:

```bash
docker compose exec hassette find /apps /config -name "requirements*.txt" 2>/dev/null
```

## Health Check Failing

The health check queries `http://127.0.0.1:8126/healthz`.

### Symptoms

- Container marked as unhealthy
- Container keeps restarting

### Solutions

1. **Check if Hassette is starting successfully:**

   ```bash
   docker compose logs hassette
   ```

2. **Verify the health service is running:**

   The health service is enabled by default. Check if it's accessible:

   ```bash
   docker compose exec hassette curl http://127.0.0.1:8126/healthz
   ```

3. **Check for port conflicts:**

   Ensure no other service uses port 8126 inside the container.

4. **Increase start period:**

   If the app takes time to start, increase `start_period`:

   ```yaml
   healthcheck:
     test: ["CMD", "curl", "-f", "http://127.0.0.1:8126/healthz"]
     interval: 30s
     timeout: 5s
     retries: 3
     start_period: 60s  # Increase this
   ```

## Hot Reload Not Working

### Requirements

For hot reload to work:

1. `watch_files = true` in `hassette.toml`
2. Files are mounted as volumes (not copied into image)
3. If not in dev mode: `allow_reload_in_prod = true`

### Configuration

```toml
[hassette]
watch_files = true
allow_reload_in_prod = true  # Only if dev_mode = false
```

### Verify Volume Mounts

Ensure files are mounted, not copied:

```yaml
volumes:
  - ./apps:/apps  # ✓ Mounted - changes reflected
```

Not:

```dockerfile
COPY ./apps /apps  # ✗ Copied - changes not reflected
```

## Import Errors

### Package Not Found

**Symptom:** `ModuleNotFoundError: No module named 'xyz'`

**Solutions:**

1. Verify the package is in your dependencies:

   ```toml
   # pyproject.toml
   dependencies = ["xyz>=1.0.0"]
   ```

2. Check installation logs for errors

3. Verify the correct Python environment is active

### Hassette Module Not Found

**Symptom:** `ModuleNotFoundError: No module named 'hassette'`

**Solution:** This usually means the virtual environment isn't activated or hassette was uninstalled. Check the startup logs - the script reinstalls hassette after user dependencies.

## Performance Issues

### Slow Container Startup

**Causes:**

- Installing many dependencies on each start
- No package cache

**Solutions:**

1. Use `uv.lock` for faster resolution
2. Mount a persistent cache volume:

   ```yaml
   volumes:
     - uv_cache:/uv_cache
   ```

3. Pre-build a custom image with dependencies

### High Memory Usage

**Solutions:**

1. Check for memory leaks in your apps
2. Limit container memory:

   ```yaml
   services:
     hassette:
       # ... other config ...
       deploy:
         resources:
           limits:
             memory: 512M
   ```

## Getting Help

If you can't resolve an issue:

1. **Search existing issues:** [GitHub Issues](https://github.com/NodeJSmith/hassette/issues)

2. **Collect diagnostic information:**

   ```bash
   # Container status
   docker compose ps

   # Full logs
   docker compose logs hassette > hassette.log

   # Environment
   docker compose exec hassette env | grep HASSETTE

   # File structure
   docker compose exec hassette find /apps /config -type f
   ```

3. **Open a new issue** with the diagnostic information

## See Also

- [Docker Overview](index.md) - Quick start guide
- [Managing Dependencies](dependencies.md) - Dependency installation details
- [Networking](networking.md) - Network configuration
