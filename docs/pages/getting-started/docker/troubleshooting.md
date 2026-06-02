# Troubleshooting

## Container Won't Start

### Check the Logs

The logs tell you why the container stopped:

```bash
--8<-- "pages/getting-started/docker/snippets/ts-check-logs.sh"
```

If the output is truncated, get more:

```bash
--8<-- "pages/getting-started/docker/snippets/ts-check-logs-tail.sh"
```

### Token Not Set

**Symptom:** The logs show an error about a missing or invalid token.

`HASSETTE__TOKEN` is required. Set it in `config/.env` and restart:

```bash
HASSETTE__TOKEN=your_long_lived_token_here
```

See [Docker Setup](index.md) for how to generate a long-lived token in Home Assistant.

### Can't Reach Home Assistant

**Symptom:** The logs show `Connection refused` or a timeout when connecting to Home Assistant.

Confirm `base_url` in `hassette.toml` matches your Home Assistant address. Then test connectivity from inside the container:

```bash
--8<-- "pages/getting-started/docker/snippets/ts-curl-ha.sh"
```

If this command times out or returns a connection error, the container cannot reach Home Assistant. Check your Docker network configuration. Hassette and Home Assistant must be on the same network, or you must use a routable hostname.

### Permission Errors

**Symptom:** The logs show `Permission denied` when reading config or app files.

The container runs as user `hassette`. Your mounted files must be readable by that user:

```bash
--8<-- "pages/getting-started/docker/snippets/ts-chmod.sh"
```

Restart the container after fixing permissions.

## Apps Not Loading

### Check App Discovery

Verify Hassette can see your app files:

```bash
--8<-- "pages/getting-started/docker/snippets/ts-ls-apps.sh"
```

If your files aren't listed, the volume mount is wrong or the files don't exist at the expected path.

### Verify App Directory Configuration

`apps.directory` in `hassette.toml` must match the container path where your apps are mounted:

```toml
--8<-- "pages/getting-started/docker/snippets/ts-app-dir-toml.toml"
```

If your project uses a `src/` layout, override the directory with an environment variable instead:

```yaml
--8<-- "pages/getting-started/docker/snippets/ts-app-dir-src-env.yml"
```

### Check for Python Errors

**Symptom:** The app directory exists and the files are there, but apps still don't load.

Look for syntax errors or failed imports in the logs:

```bash
--8<-- "pages/getting-started/docker/snippets/ts-grep-errors.sh"
```

A `SyntaxError` or `ImportError` in your app file prevents it from loading. Fix the error in your app code and restart.

### Verify App Configuration

Each app needs a corresponding entry in `hassette.toml`. Without one, Hassette ignores the file:

```toml
--8<-- "pages/getting-started/docker/snippets/ts-app-config.toml"
```

Check that `filename` matches your actual filename and `class_name` matches the class inside it.

## Dependency Installation Fails

### Check Installation Output

Look for errors in the startup logs:

```bash
--8<-- "pages/getting-started/docker/snippets/ts-dep-install-logs.sh"
```

### Dependency Conflicts

**Symptom:** The container exits at startup with a `DEPENDENCY CONFLICT` banner:

```
--8<-- "pages/getting-started/docker/snippets/ts-dep-conflict.txt"
```

Your `uv.lock` was resolved against a different Hassette version than the image provides. The startup script detects the mismatch and exits rather than silently downgrading a framework package.

Re-resolve locally against the current image version, then commit:

```bash
--8<-- "pages/getting-started/docker/snippets/ts-uv-relock.sh"
```

For `requirements.txt`-based installs, relax any pinned versions that conflict. Check which version range Hassette requires:

```bash
--8<-- "pages/getting-started/docker/snippets/ts-check-constraints.sh"
```

To prevent this, pin Hassette in your project to match the image tag you deploy. If you're using the `0.24.0-py3.13` image:

```toml
--8<-- "pages/getting-started/docker/snippets/ts-pin-hassette-pyproject.toml"
```

Run `uv lock` after updating the pin, then commit both files.

### pyproject.toml Not Found

**Symptom:** The logs say "No pyproject.toml found" or your project dependencies aren't installing.

Check that `HASSETTE__PROJECT_DIR` points to the directory containing your `pyproject.toml`:

```yaml
--8<-- "pages/getting-started/docker/snippets/ts-project-dir-env.yml"
```

Confirm the file is there:

```bash
--8<-- "pages/getting-started/docker/snippets/ts-cat-pyproject.sh"
```

### Project Has pyproject.toml But Dependencies Don't Install

**Symptom:** You have a `pyproject.toml` but no `uv.lock`, and the startup log says "run 'uv lock' to generate a lockfile".

Hassette requires a lockfile to install project dependencies. Generate one locally and commit it:

```bash
uv lock
git add uv.lock
git commit -m "add lockfile"
```

If you can't run `uv` locally, use the `requirements.txt` approach with `HASSETTE__INSTALL_DEPS=1` instead. See [Managing Dependencies](dependencies.md).

### requirements.txt Not Found

**Symptom:** Your `requirements.txt` exists but dependencies aren't installing.

Check these in order:

1. **`HASSETTE__INSTALL_DEPS=1` must be set.** Requirements discovery is off by default. Without this variable, the startup script skips all `requirements.txt` scanning.

2. **The filename must be exactly `requirements.txt`.** Files named `requirements-dev.txt`, `requirements_test.txt`, or any other variant are ignored.

3. **The file must be under `/config` or `/apps`** and must not be empty.

Check what the container sees:

```bash
--8<-- "pages/getting-started/docker/snippets/ts-find-requirements.sh"
```

### Version Conflicts

**Symptom:** Installation fails with a package version conflict.

Use `uv.lock` for consistent resolution. Packages are already pinned, so there's nothing to conflict. For `requirements.txt`, relax any overly tight version pins.

Check the Hassette constraints file to see which version ranges the image requires:

```bash
--8<-- "pages/getting-started/docker/snippets/ts-check-constraints.sh"
```

### Import Errors at Runtime

**Symptom:** Dependencies installed at startup but fail to import when your app runs.

Check three things:

1. The package is listed in your `pyproject.toml` or `requirements.txt`
2. The startup logs show the package installing without errors
3. `HASSETTE__APPS__DIRECTORY` points to the correct location

## Hassette Restarts Whenever Home Assistant Goes Down

**Symptom:** Hassette keeps restarting in a loop whenever Home Assistant restarts or goes offline, even though Hassette itself is healthy.

**Cause:** A Docker healthcheck or an autoheal tool (e.g. `willfarrell/autoheal`) is pointed at `/api/health/ready`. That endpoint returns HTTP 503 when Hassette cannot reach Home Assistant, which looks unhealthy to Docker and triggers a restart. The container is marked unhealthy during every HA outage — including routine HA restarts — so autoheal keeps killing and restarting Hassette unnecessarily.

**Fix:** Point your healthcheck at `/api/health/live` instead. The liveness endpoint returns 200 whenever the Hassette event loop can respond, regardless of Home Assistant connectivity. Only a true process failure (wedged event loop, container crash, non-zero exit) makes a liveness probe fail.

```yaml
--8<-- "pages/getting-started/docker/snippets/ts-healthcheck-live.yml"
```

If you need a separate traffic-routing signal, use `/api/health/ready` — but keep it out of any healthcheck that triggers restarts. See [Health Endpoints](../../web-ui/health-endpoints.md) for the full reference.

## Health Check Failing

The liveness check queries `http://127.0.0.1:8126/api/health/live`. This endpoint returns 200 whenever the Hassette process is up and the event loop can respond. It does not check Home Assistant connectivity — HA being down never makes the liveness probe return a non-200 response.

**Symptom:** The container is marked unhealthy, or keeps restarting.

First, check whether Hassette started at all:

```bash
--8<-- "pages/getting-started/docker/snippets/ts-check-logs.sh"
```

If Hassette started but the health check still fails, test the endpoint directly:

```bash
--8<-- "pages/getting-started/docker/snippets/ts-health-check.sh"
```

If port 8126 is in use by another process inside the container, the health service won't bind. Check your configuration for port conflicts.

If the container installs dependencies at startup, it may not respond before the first health check fires. Increase `start_period` to give it more time:

```yaml
--8<-- "pages/getting-started/docker/snippets/ts-health-check-long-start.yml"
```

## Hot Reload Not Working

**Symptom:** You edit an app file but Hassette doesn't reload.

Hot reload requires three things to be true at once:

1. `watch_files = true` is set in `hassette.toml`
2. Your app files are mounted as volumes, not copied into the image
3. If `dev_mode = false`: `allow_reload_in_prod = true` is also set

Add both settings to `hassette.toml`:

```toml
--8<-- "pages/getting-started/docker/snippets/ts-hot-reload.toml"
```

Confirm your `docker-compose.yml` mounts the files rather than baking them in:

```yaml
--8<-- "pages/getting-started/docker/snippets/ts-vol-mount.yml"
```

Files copied into the image at build time won't reflect host edits. Use volume mounts for any files you want hot reload to track.

## Import Errors

### Package Not Found

**Symptom:** `ModuleNotFoundError: No module named 'xyz'` when your app starts.

Add the package to your project dependencies:

```toml
--8<-- "pages/getting-started/docker/snippets/ts-pyproject-dep.toml"
```

Then check the startup logs to confirm it installed:

```bash
--8<-- "pages/getting-started/docker/snippets/ts-dep-install-logs.sh"
```

### Hassette Module Not Found

**Symptom:** `ModuleNotFoundError: No module named 'hassette'`

The startup script validates that Hassette is importable before doing anything else. If you see `ERROR: Failed to import hassette — the Docker image may be corrupt`, pull a fresh copy of the image:

```bash
docker compose pull hassette
docker compose up -d
```

## Performance Issues

### Slow Container Startup

**Cause:** Installing many dependencies at each startup with no cached packages.

Mount a persistent `uv` cache volume so packages don't re-download on every start:

```yaml
--8<-- "pages/getting-started/docker/snippets/ts-uv-cache-vol.yml"
```

`uv.lock` also speeds up resolution. Packages are already pinned, so `uv` skips the resolver entirely.

For the fastest startup, pre-build a custom image with your dependencies installed. See [Known Limitations](dependencies.md#known-limitations) in the dependencies guide.

### High Memory Usage

Set a memory limit in `docker-compose.yml` to prevent unbounded host memory consumption:

```yaml
--8<-- "pages/getting-started/docker/snippets/ts-memory-limit.yml"
```

If the container hits the limit and restarts repeatedly, check your apps for memory leaks. Common causes are accumulating state in module-level variables or unbounded queues.

## Getting Help

If you're still stuck, collect diagnostic information first:

```bash
--8<-- "pages/getting-started/docker/snippets/ts-diagnostics.sh"
```

Then search [existing issues](https://github.com/NodeJSmith/hassette/issues). Someone else may have hit the same problem. If not, open a new issue and include the diagnostic output.

## See Also

- [Docker Setup](index.md)
- [Managing Dependencies](dependencies.md)
- [Image Tags](image-tags.md)
