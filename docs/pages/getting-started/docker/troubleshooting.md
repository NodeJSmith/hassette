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
2. Check network configuration
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

### Dependency Conflicts

**Symptom:** Container exits at startup with a `DEPENDENCY CONFLICT` banner followed by a uv resolver error like:

```
─────────────────────────────────────────────────────────
  DEPENDENCY CONFLICT

  Your project's dependencies conflict with this version
  of Hassette. This usually means your uv.lock was generated
  against a different Hassette version than this image.

  To fix: run 'uv lock' locally, commit uv.lock, and restart.
─────────────────────────────────────────────────────────
Because you require yarl==1.20.0 and yarl==1.22.0, we can conclude that
your requirements are unsatisfiable.
```

**Why it happens:** Your project's `uv.lock` was resolved against a different version of Hassette than the Docker image you're running. When the startup script installs your dependencies through Hassette's constraints file, it detects the version mismatch and exits rather than silently downgrading a framework package.

**How to fix it:**

For project-based installs (`pyproject.toml` + `uv.lock`):

```bash
# Re-resolve against the current hassette version
uv lock

# Commit the updated lockfile
git add uv.lock
git commit -m "update uv.lock for hassette upgrade"
```

Then restart the container.

For `requirements.txt`-based installs: relax any pinned versions that conflict, or check which version range hassette requires:

```bash
docker compose exec hassette cat /app/constraints.txt | grep <package>
```

**How to prevent it:** Pin hassette in your project dependencies to match the image tag you're deploying. For example, if you're using the `0.24.0-py3.13` image:

```toml
# pyproject.toml
dependencies = [
    "hassette==0.24.0",
    # ... your other deps
]
```

Re-run `uv lock` after changing the pin, then commit both files.

### pyproject.toml Not Found

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

### Project Has pyproject.toml But Dependencies Don't Install

**Symptom:** You have a `pyproject.toml` but no `uv.lock`, and the startup log says "run 'uv lock' to generate a lockfile"

**Solution:** Generate a lockfile locally and commit it:

```bash
uv lock
git add uv.lock
git commit -m "add uv.lock"
```

If you cannot run `uv` locally, use the `requirements.txt` approach with `HASSETTE__INSTALL_DEPS=1` instead.

### requirements.txt Not Found

**Symptom:** `requirements.txt` files are not being installed

**Solution:** Check these in order:

1. **Confirm `HASSETTE__INSTALL_DEPS=1` is set** — requirements discovery is disabled by default. Without this variable, no requirements files are scanned.

   ```yaml
   environment:
     - HASSETTE__INSTALL_DEPS=1
   ```

2. **Verify the filename is exactly `requirements.txt`** — the startup script only discovers files named exactly `requirements.txt`. Files named `requirements-dev.txt`, `requirements_test.txt`, or any other variant are ignored.

3. **Verify the file is under `/config` or `/apps`** and is not empty.

Check what the container sees:

```bash
docker compose exec hassette fdfind -t f -a '^requirements\.txt$' /apps /config
```

### Version Conflicts

**Symptom:** Package version conflicts during installation

**Solutions:**

1. Use `uv.lock` for consistent, reproducible resolution
2. For `requirements.txt`, relax overly tight version pins
3. Check the constraints file to see what versions hassette requires:

   ```bash
   docker compose exec hassette cat /app/constraints.txt
   ```

### Import Errors at Runtime

If apps fail to import installed packages:

1. Verify the package is listed in your dependencies
2. Check logs for installation errors at startup
3. Ensure `HASSETTE__APP_DIR` points to the correct location

## Health Check Failing

The health check queries `http://127.0.0.1:8126/api/health`.

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
   docker compose exec hassette curl http://127.0.0.1:8126/api/health
   ```

3. **Check for port conflicts:**

   Ensure no other service uses port 8126 inside the container.

4. **Increase start period:**

   If the container installs dependencies at startup, it may take more than a few seconds before Hassette is ready to respond to health checks. Increase `start_period` to give it time:

   ```yaml
   healthcheck:
     test: ["CMD", "curl", "-f", "http://127.0.0.1:8126/api/health"]
     interval: 30s
     timeout: 5s
     retries: 3
     start_period: 60s
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

**Solution:** This usually means the virtual environment isn't activated or the Docker image is corrupt. Check the startup logs — the script validates that hassette is importable before doing anything else, and prints a clear error if that import fails. If you see `"ERROR: Failed to import hassette — the Docker image may be corrupt"`, try pulling the image again:

```bash
docker compose pull
docker compose up -d
```

## Performance Issues

### Slow Container Startup

**Causes:**

- Installing many dependencies on each start
- No package cache

**Solutions:**

1. Use `uv.lock` for faster resolution (packages are already pinned, no resolution needed)
2. Mount a persistent cache volume:

   ```yaml
   volumes:
     - uv_cache:/uv_cache
   ```

3. Pre-build a custom image with dependencies — see [Pre-building a Custom Image](dependencies.md#pre-building-a-custom-image)

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

   # File structure - example uses fdfind to automatically exclude pycache/pyc/etc.
   docker compose exec hassette fdfind . /apps /config -t f
   ```

3. **Open a new issue** with the diagnostic information

## See Also

- [Docker Overview](index.md) - Quick start guide
- [Managing Dependencies](dependencies.md) - Dependency installation details
