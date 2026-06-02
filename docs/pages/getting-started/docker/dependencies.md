# Managing Dependencies

## Overview

Hassette's Docker startup script installs your project dependencies before launching. Two methods are available: a project-based install using `pyproject.toml` and `uv.lock`, and a simpler opt-in discovery of `requirements.txt` files. You can use one or both.

### How Constraints Work

The Docker image includes a constraints file at `/app/constraints.txt`. It records compatible version ranges for all framework dependencies. Every `uv pip install` the startup script runs passes `-c /app/constraints.txt`. A conflicting package produces a clear error rather than silently downgrading a hassette dependency.

If you see a conflict error on startup, your `uv.lock` was likely generated against a different hassette version than the image. Run `uv lock` locally and commit the result. See [Dependency Conflicts](troubleshooting.md#dependency-conflicts) for more.

## How the Startup Script Works

```mermaid
--8<-- "pages/getting-started/docker/snippets/deps-startup-flow.mmd"
```

Set `HASSETTE__INSTALL_DEPS=1` to activate dependency installation. Without it, the startup script skips all requirements discovery.

With it set, the script runs these steps in order:

1. Check `HASSETTE__PROJECT_DIR` for a `pyproject.toml` and `uv.lock`
2. If both are present, export the lock file to a temporary requirements list and install through the constraints file
3. Scan `/config` and `/apps` for files named exactly `requirements.txt` (up to 5 directory levels deep) and install each one through the constraints file
4. Start Hassette

### Key Behaviors

- When a `uv.lock` exists, the script exports resolved dependencies to a flat requirements list before installing. This routes every package through the constraints file.
- `requirements.txt` files are only discovered when `HASSETTE__INSTALL_DEPS=1` is set.
- Only files named exactly `requirements.txt` are discovered. Variants like `requirements-dev.txt` or `requirements_test.txt` are ignored. This prevents dev and test dependencies from entering the production container.
- Every `uv pip install` call passes `-c /app/constraints.txt`. Conflicts produce a clear error before the container exits.
- A failing install exits the container immediately. With `restart: unless-stopped`, Docker retries automatically. Transient network errors resolve on their own.
- All network calls are wrapped with `timeout`: 300 s for project export and install, 120 s per requirements file.
- After installation, stale uv cache entries are pruned by default. Disable with `HASSETTE__PRUNE_UV_CACHE=0` to manage cache size manually.

## Understanding APP_DIR vs PROJECT_DIR

`HASSETTE__APPS__DIRECTORY` and `HASSETTE__PROJECT_DIR` serve different purposes:

| Variable | Purpose | Used by |
|---|---|---|
| `HASSETTE__APPS__DIRECTORY` | Where Hassette looks for `.py` files containing `App` and `AppSync` classes | Hassette runtime |
| `HASSETTE__PROJECT_DIR` | Where the startup script looks for `pyproject.toml` and `uv.lock` | Startup script |

These can point to the same directory or different ones depending on your project layout. `HASSETTE__APP_DIR` is a legacy alias for `HASSETTE__APPS__DIRECTORY` and still works, but prefer the canonical name.

## Project Structures

### Simple Flat Structure

```
--8<-- "pages/getting-started/docker/snippets/deps-flat-dir-structure.txt"
```

```yaml
--8<-- "pages/getting-started/docker/snippets/deps-flat-compose.yml"
```

Both `HASSETTE__APPS__DIRECTORY` and `HASSETTE__PROJECT_DIR` default to `/apps`, so no extra environment variables are needed. A `requirements.txt` in `/apps` is not installed automatically. Set `HASSETTE__INSTALL_DEPS=1` to enable discovery.

### Traditional src/ Layout

```
--8<-- "pages/getting-started/docker/snippets/deps-src-dir-structure.txt"
```

```yaml
--8<-- "pages/getting-started/docker/snippets/deps-src-compose.yml"
```

The project root containing `pyproject.toml` mounts to `/apps`. `HASSETTE__PROJECT_DIR=/apps` tells the startup script where to find the lock file. `HASSETTE__APPS__DIRECTORY=/apps/src/my_apps` tells Hassette where to find your app classes. Your apps can import from the `my_apps` package normally.

## Using pyproject.toml

```toml
--8<-- "pages/getting-started/docker/snippets/pyproject-example.toml"
```

### With a Lock File (Required)

```bash
--8<-- "pages/getting-started/docker/snippets/uv-lock.sh"
```

Commit the `uv.lock` file alongside your `pyproject.toml`. The startup script detects both files and exports resolved dependencies through the constraints file.

If `pyproject.toml` is present but no `uv.lock` exists, the startup script logs a message and skips the project install. If you cannot run `uv` locally, use `requirements.txt` with `HASSETTE__INSTALL_DEPS=1` instead.

## Using requirements.txt

```
--8<-- "pages/getting-started/docker/snippets/deps-requirements-dir-structure.txt"
```

```
--8<-- "pages/getting-started/docker/snippets/requirements-example.txt"
```

```yaml
--8<-- "pages/getting-started/docker/snippets/deps-install-deps-env.yml"
```

The startup script uses `fd` to find files named exactly `requirements.txt` in both `/config` and `/apps`. It installs them in sorted path order with constraints applied.

## Startup Performance

### Using uv.lock for Faster Starts

```yaml
--8<-- "pages/getting-started/docker/snippets/uv-cache-volume.yml"
```

The `uv_cache` Docker volume caches downloaded packages between container restarts. Combined with `uv.lock`, subsequent starts skip re-downloading cached packages.

### Known Limitations

#### Local Path Dependencies

Projects with local path dependencies (for example, `foo = { path = "../shared-lib" }` in `pyproject.toml`) fail during the export step. `uv export` emits `file:///absolute/path` references that do not resolve inside the container. If your project uses monorepo-style local deps, build a custom image with those packages copied in at build time:

```dockerfile
--8<-- "pages/getting-started/docker/snippets/custom-image.dockerfile"
```

```yaml
--8<-- "pages/getting-started/docker/snippets/custom-image-compose.yml"
```

!!! note "CLI tooling for custom images is planned"
    A `hassette docker build` command to streamline this workflow is on the roadmap.

## Complete Examples

### Example 1: Simple Flat Structure

```yaml
--8<-- "pages/getting-started/docker/snippets/deps-example1-compose.yml"
```

```
--8<-- "pages/getting-started/docker/snippets/deps-example1-requirements.txt"
```

### Example 2: src/ Layout with Lock File

```yaml
--8<-- "pages/getting-started/docker/snippets/deps-example2-compose.yml"
```

```toml
--8<-- "pages/getting-started/docker/snippets/deps-example2-pyproject.toml"
```

## See Also

- [Docker Setup](index.md) — Getting started with Docker
- [Image Tags](image-tags.md) — Choosing the right image version
- [Troubleshooting](troubleshooting.md) — Dependency conflicts and common errors
