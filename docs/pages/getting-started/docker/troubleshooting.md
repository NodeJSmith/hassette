# Troubleshooting

This guide covers common issues when running Hassette in Docker and how to resolve them.

## Container Won't Start

### Check the Logs

Always start by checking the logs:

```bash
--8<-- "pages/getting-started/docker/snippets/ts-check-logs.sh"
```

For more detail:

```bash
--8<-- "pages/getting-started/docker/snippets/ts-check-logs-tail.sh"
```

### Common Startup Issues

#### Token Not Set

**Symptom:** Error about missing or invalid token

**Solution:** Ensure `HASSETTE__TOKEN` is set in `config/.env`:

```bash
--8<-- "pages/getting-started/docker/snippets/ts-token-env.sh"
```

#### Can't Reach Home Assistant

**Symptom:** Connection refused or timeout errors

**Solutions:**

1. Verify `base_url` in `hassette.toml` is correct
2. Check network configuration
3. Test connectivity from the container:

```bash
--8<-- "pages/getting-started/docker/snippets/ts-curl-ha.sh"
```

#### Permission Errors

**Symptom:** Permission denied when reading files

**Solution:** The container runs as user `hassette`. Ensure mounted files are readable:

```bash
--8<-- "pages/getting-started/docker/snippets/ts-chmod.sh"
```

## Apps Not Loading

### 1. Check App Discovery

Verify Hassette can see your app files:

```bash
--8<-- "pages/getting-started/docker/snippets/ts-ls-apps.sh"
```

### 2. Verify APP_DIR Configuration

Ensure `app_dir` in `hassette.toml` matches the container path:

```toml
--8<-- "pages/getting-started/docker/snippets/ts-app-dir-toml.toml"
```

If using `src/` layout:

```yaml
--8<-- "pages/getting-started/docker/snippets/ts-app-dir-src-env.yml"
```

### 3. Check for Python Errors

Look for syntax or import errors in the logs:

```bash
--8<-- "pages/getting-started/docker/snippets/ts-grep-errors.sh"
```

### 4. Verify App Configuration

Ensure your app is configured in `hassette.toml`:

```toml
--8<-- "pages/getting-started/docker/snippets/ts-app-config.toml"
```

## Dependency Installation Fails

### Check Installation Output

Look for installation errors in the logs:

```bash
--8<-- "pages/getting-started/docker/snippets/ts-dep-install-logs.sh"
```

### Dependency Conflicts

**Symptom:** Container exits at startup with a `DEPENDENCY CONFLICT` banner followed by a uv resolver error like:

```
--8<-- "pages/getting-started/docker/snippets/ts-dep-conflict.txt"
```

**Why it happens:** Your project's `uv.lock` was resolved against a different version of Hassette than the Docker image you're running. When the startup script installs your dependencies through Hassette's constraints file, it detects the version mismatch and exits rather than silently downgrading a framework package.

**How to fix it:**

For project-based installs (`pyproject.toml` + `uv.lock`):

```bash
--8<-- "pages/getting-started/docker/snippets/ts-uv-relock.sh"
```

Then restart the container.

For `requirements.txt`-based installs: relax any pinned versions that conflict, or check which version range hassette requires:

```bash
--8<-- "pages/getting-started/docker/snippets/ts-check-constraints.sh"
```

**How to prevent it:** Pin hassette in your project dependencies to match the image tag you're deploying. For example, if you're using the `0.24.0-py3.13` image:

```toml
--8<-- "pages/getting-started/docker/snippets/ts-pin-hassette-pyproject.toml"
```

Re-run `uv lock` after changing the pin, then commit both files.

### pyproject.toml Not Found

**Symptom:** "No pyproject.toml found" or dependencies not installing

**Solution:** Check `HASSETTE__PROJECT_DIR` points to the right location:

```yaml
--8<-- "pages/getting-started/docker/snippets/ts-project-dir-env.yml"
```

Verify the file exists:

```bash
--8<-- "pages/getting-started/docker/snippets/ts-cat-pyproject.sh"
```

### Project Has pyproject.toml But Dependencies Don't Install

**Symptom:** You have a `pyproject.toml` but no `uv.lock`, and the startup log says "run 'uv lock' to generate a lockfile"

**Solution:** Generate a lockfile locally and commit it:

```bash
--8<-- "pages/getting-started/docker/snippets/ts-uv-lock-add.sh"
```

If you cannot run `uv` locally, use the `requirements.txt` approach with `HASSETTE__INSTALL_DEPS=1` instead.

### requirements.txt Not Found

**Symptom:** `requirements.txt` files are not being installed

**Solution:** Check these in order:

1. **Confirm `HASSETTE__INSTALL_DEPS=1` is set** — requirements discovery is disabled by default. Without this variable, no requirements files are scanned.

```yaml
--8<-- "pages/getting-started/docker/snippets/ts-install-deps-env.yml"
```

2. **Verify the filename is exactly `requirements.txt`** — the startup script only discovers files named exactly `requirements.txt`. Files named `requirements-dev.txt`, `requirements_test.txt`, or any other variant are ignored.

3. **Verify the file is under `/config` or `/apps`** and is not empty.

Check what the container sees:

```bash
--8<-- "pages/getting-started/docker/snippets/ts-find-requirements.sh"
```

### Version Conflicts

**Symptom:** Package version conflicts during installation

**Solutions:**

1. Use `uv.lock` for consistent, reproducible resolution
2. For `requirements.txt`, relax overly tight version pins
3. Check the constraints file to see what versions hassette requires:

```bash
--8<-- "pages/getting-started/docker/snippets/ts-check-constraints.sh"
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
--8<-- "pages/getting-started/docker/snippets/ts-check-logs.sh"
```

2. **Verify the health service is running:**

The health service is enabled by default. Check if it's accessible:

```bash
--8<-- "pages/getting-started/docker/snippets/ts-health-check.sh"
```

3. **Check for port conflicts:**

Ensure no other service uses port 8126 inside the container.

4. **Increase start period:**

If the container installs dependencies at startup, it may take more than a few seconds before Hassette is ready to respond to health checks. Increase `start_period` to give it time:

```yaml
--8<-- "pages/getting-started/docker/snippets/ts-healthcheck-long-start.yml"
```

## Hot Reload Not Working

### Requirements

For hot reload to work:

1. `watch_files = true` in `hassette.toml`
2. Files are mounted as volumes (not copied into image)
3. If not in dev mode: `allow_reload_in_prod = true`

### Configuration

```toml
--8<-- "pages/getting-started/docker/snippets/ts-hot-reload.toml"
```

### Verify Volume Mounts

Ensure files are mounted, not copied:

```yaml
--8<-- "pages/getting-started/docker/snippets/ts-vol-mount.yml"
```

## Import Errors

### Package Not Found

**Symptom:** `ModuleNotFoundError: No module named 'xyz'`

**Solutions:**

1. Verify the package is in your dependencies:

```toml
--8<-- "pages/getting-started/docker/snippets/ts-pyproject-dep.toml"
```

2. Check installation logs for errors

3. Verify the correct Python environment is active

### Hassette Module Not Found

**Symptom:** `ModuleNotFoundError: No module named 'hassette'`

**Solution:** This usually means the virtual environment isn't activated or the Docker image is corrupt. Check the startup logs — the script validates that hassette is importable before doing anything else, and prints a clear error if that import fails. If you see `"ERROR: Failed to import hassette — the Docker image may be corrupt"`, try pulling the image again:

```bash
--8<-- "pages/getting-started/docker/snippets/ts-docker-pull.sh"
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
--8<-- "pages/getting-started/docker/snippets/ts-uv-cache-vol.yml"
```

3. Pre-build a custom image with dependencies — see [Pre-building a Custom Image](dependencies.md#pre-building-a-custom-image)

### High Memory Usage

**Solutions:**

1. Check for memory leaks in your apps
2. Limit container memory:

```yaml
--8<-- "pages/getting-started/docker/snippets/ts-memory-limit.yml"
```

## Getting Help

If you can't resolve an issue:

1. **Search existing issues:** [GitHub Issues](https://github.com/NodeJSmith/hassette/issues)

2. **Collect diagnostic information:**

```bash
--8<-- "pages/getting-started/docker/snippets/ts-diagnostics.sh"
```

3. **Open a new issue** with the diagnostic information

## See Also

- [Docker Overview](index.md) — Quick start guide
- [Managing Dependencies](dependencies.md) — Dependency installation details
