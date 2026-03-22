# Research Brief: Home Assistant Add-on for Hassette

**Date**: 2026-03-21
**Status**: Ready for Decision
**Proposal**: Package hassette as a Home Assistant add-on with ingress-based web UI
**Initiated by**: User wants implementation details for creating an HA add-on

## Executive Summary

Hassette is well-positioned for add-on packaging. The existing Docker infrastructure (multi-stage Dockerfile, startup script, environment-variable-based config) already solves 60-70% of the container story. The main work falls into three areas: (1) creating the HA add-on metadata and adapting the Dockerfile to use HA base images, (2) bridging HA's add-on config schema to hassette's TOML/env-var config system, and (3) making the Preact SPA work behind HA's ingress proxy.

The ingress integration is the hardest part. Hassette's frontend uses absolute paths for API calls (`/api/*`) and WebSocket connections (`/api/ws`), and its router (wouter) uses root-relative paths (`/`, `/apps`, `/logs`). All of these break behind ingress, which serves the app under a dynamic base path like `/api/hassio_ingress/<token>/`. This requires changes to both the Vite build (dynamic `base` config) and the frontend's API client and router to use the `X-Ingress-Path` header.

The HA API connection is straightforward -- inside an add-on container, HA Core is reachable at `http://supervisor/core/api` using the `SUPERVISOR_TOKEN` environment variable, which maps cleanly to hassette's existing `base_url` and `token` config fields.

## Current Hassette Architecture

### Entry Points

The application has a single entry point defined in `pyproject.toml`:

```
hassette = "hassette.__main__:entrypoint"
```

`entrypoint()` in `src/hassette/__main__.py` enables logging, then calls `asyncio.run(main())`. The `main()` function parses CLI args (`--config-file`, `--env-file`), creates a `HassetteConfig`, instantiates `Hassette(config)`, and calls `core.run_forever()`.

The Docker container uses `scripts/docker_start.sh` as its entrypoint (via tini). This script activates the venv, installs user project deps if a `uv.lock` or `pyproject.toml` exists in the apps dir, finds and installs any `requirements.txt` files, then calls `exec hassette "$@"`.

### Configuration System

`HassetteConfig` (`src/hassette/config/config.py`) extends Pydantic `BaseSettings` with multiple config sources in priority order:

1. **Init kwargs** (constructor)
2. **Environment variables** (prefix `HASSETTE__`, nested delimiter `__`)
3. **Dotenv files** (searched at `/config/.env`, `.env`, `./config/.env`)
4. **File secrets**
5. **TOML files** (searched at `/config/hassette.toml`, `hassette.toml`, `./config/hassette.toml`)

Key config fields relevant to add-on packaging:
- `base_url` (str, default `http://127.0.0.1:8123`) -- HA instance URL
- `token` (str, required) -- HA long-lived access token
- `verify_ssl` (bool, default `True`)
- `config_dir` (Path, defaults to `HASSETTE__CONFIG_DIR` or `/config`)
- `data_dir` (Path, defaults to `HASSETTE__DATA_DIR` or `/data`)
- `app_dir` (Path, defaults to `HASSETTE__APP_DIR` or `/apps`)
- `web_api_host` (str, default `0.0.0.0`)
- `web_api_port` (int, default `8126`)
- `log_level` (str, default `INFO`)
- `db_path` (Path, defaults to `data_dir / "hassette.db"`)

The config system already has Docker-aware defaults: `default_config_dir()`, `default_data_dir()`, and `default_app_dir()` in `src/hassette/config/helpers.py` all check for `/config`, `/data`, and `/apps` respectively before falling back to platform-specific paths.

### Web Server

The web API runs on FastAPI + uvicorn (`src/hassette/core/web_api_service.py`). The FastAPI app is created in `src/hassette/web/app.py`:
- API routes at `/api/*` (health, apps, services, events, logs, scheduler, bus, config, ws, telemetry)
- Preact SPA served from `src/hassette/web/static/spa/` with catch-all route for client-side routing
- WebSocket endpoint at `/api/ws`
- CORS middleware configured via `web_api_cors_origins`

### Frontend (Preact SPA)

The frontend lives in `frontend/` and is a Preact SPA using:
- **wouter** for client-side routing (root-relative paths: `/`, `/apps`, `/apps/:key`, `/logs`)
- **@preact/signals** for state management
- **Vite** for bundling (outputs to `../src/hassette/web/static/spa/`)
- API client (`frontend/src/api/client.ts`) with hardcoded `BASE_URL = "/api"`
- WebSocket connects to `${proto}//${location.host}/api/ws`
- Google Fonts loaded from external CDN

### WebSocket Connection to HA

`WebsocketService` (`src/hassette/core/websocket_service.py`) connects to HA via aiohttp WebSocket. URL is built by `build_ws_url()` in `src/hassette/utils/url_utils.py` from `config.base_url` -- converts `http://host:port` to `ws://host:port/api/websocket`. Authentication uses `config.token` as a bearer token.

### Docker Infrastructure

The existing `Dockerfile` is a multi-stage build:
1. **Frontend stage**: Node 22, `npm ci && npm run build`
2. **uv stage**: Copies uv binary
3. **Builder stage**: Python 3.13-slim, installs deps via `uv sync`
4. **Final stage**: Python 3.13-slim, installs runtime packages (ca-certificates, curl, tini, tzdata, fd-find, git), creates non-root user, volumes at `/config`, `/data`, `/apps`, `/uv_cache`

Already builds multi-arch (`linux/amd64,linux/arm64`) and publishes to GHCR.

### Dependencies

Python 3.11+ required (tested on 3.11, 3.12, 3.13). Key runtime dependencies: aiohttp, fastapi, uvicorn, pydantic-settings, aiosqlite, alembic, watchfiles, croniter. Total of ~25 direct dependencies.

## HA Add-on Requirements

### Add-on Structure

A minimal HA add-on repository requires:

```
hassette-addon/
  config.yaml          # Add-on metadata + config schema
  Dockerfile           # Must use ARG BUILD_FROM / FROM $BUILD_FROM
  build.yaml           # Architecture-specific base images
  icon.png             # 128x128 icon
  logo.png             # 256x256 logo
  DOCS.md              # User-facing documentation
  CHANGELOG.md
  translations/
    en.yaml            # Localized config option descriptions
```

This can live in a standalone repo or as a subdirectory in a multi-addon repository. For hassette, a standalone repo (e.g., `hassette-addon` or `hassette-ha-addon`) makes sense since it's the only add-on.

### Dockerfile & Base Images

HA add-ons must use the `ARG BUILD_FROM` / `FROM $BUILD_FROM` pattern. The Supervisor builder substitutes the correct arch-specific base image. HA provides Python base images:

```
ghcr.io/home-assistant/{arch}-base-python:3.13-alpine3.22-{date}
```

Where `{arch}` is `amd64`, `aarch64`, `armv7`, etc.

**Key difference from current Dockerfile**: HA base images are Alpine-based, not Debian-based. This affects package installation (`apk add` vs `apt-get`), available system libraries, and potentially some Python packages with C extensions that might not have Alpine wheels.

The `build.yaml` specifies per-architecture base images:

```yaml
build_from:
  amd64: ghcr.io/home-assistant/amd64-base-python:3.13-alpine3.22
  aarch64: ghcr.io/home-assistant/aarch64-base-python:3.13-alpine3.22
  armv7: ghcr.io/home-assistant/armv7-base-python:3.13-alpine3.22
```

Alternatively, you can set `init: false` in config.yaml and use any base image (including the existing python-slim images), but then you lose s6-overlay integration and the HA builder won't auto-select arch-specific images.

### Configuration Schema

HA add-ons expose config to users via the `options` and `schema` fields in `config.yaml`:

```yaml
options:
  log_level: info
  app_dir: /config/hassette/apps
schema:
  log_level: list(debug|info|warning|error|critical)
  app_dir: str
  token: password?
```

These options are available inside the container as a JSON file (via bashio) or can be read directly from `/data/options.json`. The add-on's run script typically reads these and passes them as environment variables to the actual application.

**Mapping to hassette's config**: Since hassette already reads environment variables with the `HASSETTE__` prefix, the cleanest approach is a thin startup script that reads `/data/options.json` and exports the values as `HASSETTE__*` environment variables before launching hassette.

### Ingress (Web UI)

Ingress configuration in `config.yaml`:

```yaml
ingress: true
ingress_port: 8126    # match hassette's web_api_port
ingress_entry: /
```

**How ingress works**:
1. User clicks the add-on panel in HA sidebar
2. HA creates a session token and opens an iframe/panel to `/api/hassio_ingress/<token>/`
3. The Supervisor reverse-proxies all requests under that path to the add-on container on `ingress_port`
4. The `X-Ingress-Path` header is injected into proxied requests, containing the ingress base path (e.g., `/api/hassio_ingress/abc123/`)

**Security requirement**: Only accept connections from `172.30.32.2` (the Supervisor's internal IP). All other IPs must be rejected.

**What breaks with the current frontend**:
- `BASE_URL = "/api"` in `client.ts` -- needs to become relative to the ingress path
- `new WebSocket(\`\${proto}//\${location.host}/api/ws\`)` -- needs ingress-aware URL
- wouter routes (`/`, `/apps`, `/logs`) -- need a base path prefix
- `<link rel="icon" href="/hassette-logo.png">` and font URLs -- need relative paths or ingress-aware URLs
- Vite's `base` config in production build -- needs to be set to the ingress path or `.` for relative

**Ingress supports**: HTTP/1.x, streaming, WebSockets. This covers all of hassette's needs.

### HA API Communication

Inside an add-on container:
- **Supervisor API**: Available at `http://supervisor/` with `SUPERVISOR_TOKEN` env var (auto-injected)
- **HA Core API**: Available at `http://supervisor/core/api` (proxied through Supervisor)
- **Direct HA Core**: Also reachable at `http://homeassistant:8123/api` on the internal network

For hassette, the connection needs:
- `base_url` = `http://supervisor/core` (or `http://homeassistant:8123`)
- `token` = value of `SUPERVISOR_TOKEN` env var

This requires declaring `homeassistant_api: true` in `config.yaml`, which grants the add-on permission to access HA's API via the Supervisor proxy.

**WebSocket URL construction**: `build_ws_url()` currently converts `http://` to `ws://`. For the Supervisor proxy (`http://supervisor/core`), the WebSocket URL would be `ws://supervisor/core/api/websocket`. This should work with the existing URL utility, but needs testing -- the path component `/core/api/websocket` is different from the standard `/api/websocket`.

### Lifecycle & Logging

**Container lifecycle**: The Supervisor manages start/stop/restart. The container process should handle SIGTERM gracefully -- hassette already does this (catches `KeyboardInterrupt` and `CancelledError`).

**Watchdog**: Can be configured for health monitoring:
```yaml
watchdog: http://[HOST]:[PORT:8126]/api/health
```
This maps directly to hassette's existing health endpoint.

**Logging**: stdout/stderr from the container process are captured and shown in the HA logs panel. Hassette uses Python's `logging` module with `coloredlogs` -- this should work, though ANSI color codes may not render well in HA's log viewer. May want to disable `coloredlogs` when running as an add-on.

**Backup**: The `/data` directory is automatically backed up by HA. Set `backup: hot` (default) to allow backups while running. Hassette's SQLite database should be in `/data` (already the default via `HASSETTE__DATA_DIR=/data`).

### Storage & Backups

**Automatic mounts available to add-ons**:
- `/data` -- persistent, add-on-specific, backed up automatically (hassette's `data_dir`)
- `/config` -- HA config directory (available if `map` includes it)
- `/share` -- shared between add-ons
- `/addon_config` -- add-on-specific config area

**For hassette**:
```yaml
map:
  - addon_config:rw    # /addon_config for hassette.toml and user config
  - share:rw           # /share for user apps that need shared data (optional)
```

The user's hassette apps directory should probably live under `/addon_config/hassette/apps/` or `/config/hassette/apps/` (the latter puts it in the main HA backup).

**Backup integration**: `/data` is automatically included in HA backups. This covers the SQLite database and any cached data. User apps (if stored under `/addon_config`) are also backed up. The `backup_exclude` option can exclude large/regeneratable files.

### Permissions

Required permissions for the add-on:

```yaml
homeassistant_api: true    # Access HA Core API (required)
ingress: true              # Web UI via ingress (required)
```

Optional but recommended:
```yaml
hassio_api: false          # Not needed unless hassette needs Supervisor features
auth_api: false            # Not needed; ingress handles auth
host_network: false        # Internal networking is sufficient
```

### S6-Overlay / Process Supervision

HA's base images include s6-overlay for process supervision. For hassette:

**Option A: Use s6-overlay** -- Set `init: true` (default). Create a service directory for hassette under `/etc/services.d/hassette/run`. S6 handles process supervision, restart on crash, and signal forwarding.

**Option B: Skip s6-overlay** -- Set `init: false` in config.yaml. Use `CMD` or `ENTRYPOINT` directly. Hassette already uses `tini` as PID 1 in its current Dockerfile. However, you lose s6's process supervision (auto-restart on crash).

**Recommendation**: Option A (use s6-overlay). It's the standard pattern for HA add-ons, provides auto-restart, and the Supervisor expects it. The run script would be:

```bash
#!/usr/bin/with-contenv bashio
# Read add-on options and export as env vars
export HASSETTE__TOKEN="$(bashio::config 'token')"
export HASSETTE__BASE_URL="http://supervisor/core"
export HASSETTE__LOG_LEVEL="$(bashio::config 'log_level')"
export HASSETTE__WEB_API_PORT=8126
exec hassette
```

## Gap Analysis

### What needs to change

| Area | Files affected | Effort | Risk |
|------|---------------|--------|------|
| Add-on metadata (new repo/dir) | 6-8 new files | Low | Low -- boilerplate |
| Dockerfile adaptation | 1 file (new, based on existing) | Medium | Medium -- Alpine vs Debian, build deps |
| Config bridge script | 1 new file | Low | Low -- env var mapping |
| Frontend base path / ingress | 4-6 files | High | High -- URL rewriting, SPA routing |
| HA API URL construction | 1-2 files | Low | Low -- already flexible |
| Logging (coloredlogs disable) | 1 file | Low | Low |
| Google Fonts (offline) | 2-3 files | Low | Low -- bundle fonts or use system |

### What already supports this

1. **Config system is Docker-ready**: `default_config_dir()`, `default_data_dir()`, `default_app_dir()` already check for `/config`, `/data`, `/apps` before platform defaults
2. **Environment variable config**: `HASSETTE__*` prefix with nested delimiter already works for all config fields
3. **TOML file search paths**: Already searches `/config/hassette.toml`
4. **Web server binds 0.0.0.0**: Default `web_api_host` is already `0.0.0.0`
5. **Multi-arch Docker builds**: Already builds `linux/amd64` and `linux/arm64`
6. **Health endpoint exists**: `/api/health` is already implemented for watchdog
7. **Graceful shutdown**: Signal handling is already implemented
8. **SQLite in /data**: `data_dir` defaults to `/data` in Docker, database goes there

### What works against this

1. **Frontend hardcoded paths**: `BASE_URL = "/api"`, absolute WebSocket URL, root-relative routes -- all need ingress awareness
2. **Google Fonts from CDN**: External network requests from within an add-on may be blocked or add latency; fonts should be bundled
3. **Alpine compatibility**: Current Dockerfile uses Debian-slim; some dependencies (especially those with C extensions like `orjson`, `aiohttp`) may need Alpine-specific build steps
4. **No ingress awareness anywhere**: Zero existing code handles `X-Ingress-Path` or dynamic base paths
5. **WebSocket URL construction**: `build_ws_url()` assumes standard HA URL format; Supervisor proxy URL (`http://supervisor/core`) has a different path structure
6. **User app installation**: `docker_start.sh` installs user deps via `uv sync`/`uv pip install`, which needs to work with Alpine and whatever Python the HA base image provides

## Options Evaluated

### Option A: Dedicated Add-on Dockerfile with HA Base Images

**How it works**: Create a new `hassette-addon` repository (or directory) with HA-specific Dockerfile using `ARG BUILD_FROM` / `FROM $BUILD_FROM`. Use HA's Alpine-based Python base images. Include s6-overlay service definitions. Build and publish via HA's builder or custom CI.

The Dockerfile would install uv, copy the hassette source and frontend build, install Python deps, and set up the s6 service. A run script reads `/data/options.json` (add-on config from HA UI), exports values as `HASSETTE__*` env vars, and launches hassette.

**Pros**:
- Standard HA add-on pattern; works with Supervisor builder and HACS
- S6-overlay provides process supervision and auto-restart
- Alpine images are smaller
- Users install via HA UI with zero Docker knowledge

**Cons**:
- Must maintain a separate Dockerfile for the add-on (different from the standalone Docker image)
- Alpine compatibility may require changes for C extension packages
- Loses the existing tini + non-root user setup (s6 runs as root, drops privileges)
- Frontend build still needs Node.js in the build stage

**Effort estimate**: Medium -- the Dockerfile work and config bridge are straightforward; the ingress frontend changes are the bulk of the effort regardless of option.

**Dependencies**: None new for the backend. Frontend may need a small utility to detect ingress mode.

### Option B: Reuse Existing Docker Image with `init: false`

**How it works**: Set `init: false` in config.yaml and use hassette's existing GHCR Docker image directly via the `image` field in config.yaml. No custom Dockerfile -- the existing image is pulled and run by the Supervisor. A wrapper script handles the config bridge.

```yaml
image: ghcr.io/nodejsmith/hassette:{version}-py3.13
init: false
```

**Pros**:
- Single Dockerfile to maintain (not two)
- No Alpine compatibility concerns (stays on Debian-slim)
- Existing CI pipeline publishes the image
- Faster iteration -- changes to hassette automatically work in the add-on

**Cons**:
- Loses s6-overlay process supervision (but tini provides signal forwarding and zombie reaping)
- Image is larger (Debian-slim vs Alpine)
- Less "standard" for HA add-ons -- some users/reviewers may raise eyebrows
- Need to ensure the entrypoint script can read `/data/options.json` (currently expects `docker_start.sh`)
- armv7 support may be needed (current images are amd64+arm64 only)

**Effort estimate**: Small for backend, but same Medium-High effort for ingress/frontend.

**Dependencies**: None new.

### Option C: Hybrid -- HA Base Image Wrapping Existing Package

**How it works**: Use HA's base image in the Dockerfile but install hassette from PyPI (or the GHCR image as a build stage). This avoids maintaining a full separate build but uses HA's standard patterns.

```dockerfile
ARG BUILD_FROM
FROM $BUILD_FROM

RUN apk add --no-cache python3 py3-pip
RUN pip install hassette==${VERSION}

COPY rootfs/ /
```

**Pros**:
- Standard HA base image pattern
- S6-overlay available
- Hassette installed as a package (clean separation)
- Smaller maintenance surface than Option A

**Cons**:
- Requires hassette to be published to PyPI (it's already set up for this)
- Alpine pip installation may need build dependencies for C extensions
- Frontend SPA assets need to be included in the PyPI package (they already are -- built into `src/hassette/web/static/spa/`)
- Version pinning adds a release step

**Effort estimate**: Medium -- similar to Option A but with cleaner separation.

**Dependencies**: PyPI publishing must be reliable.

## Concerns

### Technical risks

1. **Ingress + SPA is the hard part**: Every HA add-on with a web UI has to deal with ingress path rewriting. For SPAs, this is especially tricky because the router, API client, and static asset paths all need the base path. Wouter supports a `base` prop on its `Router` component, but the base path is dynamic (changes per session token) and must be determined at runtime.

2. **WebSocket through ingress**: HA ingress supports WebSocket proxying, but hassette's frontend constructs the WS URL from `location.host` with an absolute path. This needs to use the same ingress-aware base path. Any reconnection logic must also handle the ingress path.

3. **Alpine C extension compatibility**: `orjson`, `aiohttp`, and `watchfiles` all have C/Rust extensions. They should have Alpine wheels, but this needs verification. If wheels aren't available, the Dockerfile needs build-time dependencies (`gcc`, `musl-dev`, `rust`, etc.) which bloats the image.

4. **Supervisor proxy WebSocket URL**: The path to HA's WebSocket API through the Supervisor proxy is `ws://supervisor/core/api/websocket`, not the standard `ws://host:8123/api/websocket`. The `build_ws_url()` function needs to handle this correctly.

### Complexity risks

1. **Two Dockerfiles**: If using Option A, there are now two Dockerfiles to maintain (standalone + add-on). They serve different purposes but share the same application code.

2. **Ingress detection mode**: The frontend needs to detect whether it's running standalone or behind ingress, and configure its base path accordingly. This could be done via a meta tag injected by the backend, an API endpoint, or by detecting the `X-Ingress-Path` header presence.

3. **Config schema duplication**: The add-on's `schema` in config.yaml partially duplicates hassette's own Pydantic validation. Changes to config fields need to be reflected in both places.

### Maintenance risks

1. **HA base image updates**: Alpine version bumps, s6-overlay version changes, and Python version availability in HA base images are outside hassette's control.

2. **Ingress API stability**: The ingress proxy behavior and headers could change in future HA versions, though it's been stable since 2019.

3. **HACS review requirements**: If distributed via HACS, there are additional review criteria and maintenance expectations.

## Open Questions

- [ ] **Which option for Dockerfile strategy?** Option A (dedicated HA Dockerfile), B (reuse existing image), or C (hybrid with PyPI install). Each has trade-offs around maintenance burden vs. standardness.

- [ ] **Where should user apps live?** Options: `/addon_config/hassette/apps/`, `/config/hassette/apps/`, or `/share/hassette/apps/`. This affects backup behavior and whether other add-ons can access the apps.

- [ ] **How should the frontend detect ingress mode?** Options: (a) backend injects a `<meta>` tag with the base path, (b) frontend reads `X-Ingress-Path` from an initial API response header, (c) backend exposes a `/api/config` endpoint that includes the ingress path, (d) build-time environment variable.

- [ ] **Should hassette also support the `SUPERVISOR_TOKEN` directly?** Currently `token` requires a long-lived access token. The Supervisor token is different -- it authenticates to the Supervisor API, not directly to HA Core. When using `http://supervisor/core/api`, the Supervisor token works as a proxy auth. Should hassette detect this automatically?

- [ ] **armv7 support?** Current images build amd64+arm64. Some HA installations run on armv7 (Raspberry Pi 2/3 in 32-bit mode). Is this a target?

- [ ] **Should this be a HACS add-on or official HA add-on?** HACS has lower barriers to entry but official add-ons get more visibility. HACS is the likely starting point.

- [ ] **Google Fonts bundling**: The frontend loads DM Sans, JetBrains Mono, and Space Grotesk from Google's CDN. Inside an add-on container, external network access may be restricted. Should these be self-hosted / bundled?

## Recommendation

Start with **Option B** (reuse existing Docker image with `init: false`) for the initial add-on release, then migrate to **Option A** (dedicated HA Dockerfile) once the ingress integration is proven and stable.

**Rationale**: The ingress/frontend work is the highest-risk item and is identical across all options. Using the existing Docker image eliminates the Alpine compatibility variable, letting you focus entirely on the ingress integration. Once that's working, switching to HA base images is a well-understood Dockerfile change.

### Suggested next steps

1. **Write a design doc** (`/mine.design`) covering the ingress integration specifically -- how the frontend will detect and use the base path, the API client changes, and the WebSocket URL construction.

2. **Prototype ingress support in the frontend** -- Add a `getBasePath()` utility that reads `X-Ingress-Path` from a backend endpoint, and wire it into the API client, WebSocket hook, and wouter Router. Test with a manual nginx reverse proxy that simulates ingress behavior.

3. **Create the add-on repository skeleton** -- `config.yaml`, `build.yaml`, `DOCS.md`, run script. Use `image:` pointing to the existing GHCR image. Get the basic add-on installable in HA (without ingress) first.

4. **Bundle Google Fonts** -- Download the font files and serve them from the SPA's static assets. This is a prerequisite for reliable add-on operation.

5. **Test Supervisor token and WebSocket** -- Verify that `SUPERVISOR_TOKEN` works with `http://supervisor/core` as `base_url`, and that `build_ws_url()` produces a correct WebSocket URL for this base.

## AppDaemon Precedent Study

AppDaemon is the closest analog — an async Python HA automation framework with a web dashboard, packaged as an HA add-on. The add-on repo is [`hassio-addons/addon-appdaemon`](https://github.com/hassio-addons/addon-appdaemon), maintained separately from the [AppDaemon core](https://github.com/AppDaemon/appdaemon). Key findings:

### Dockerfile & Base Images

Uses the community hassio-addons Alpine base image (`ghcr.io/hassio-addons/base:20.0.1`), not official HA base images. C extensions are handled with a virtual package pattern — install `build-base`/`python3-dev`, run pip, then `apk del`. All versions are pinned. AppDaemon is installed from PyPI (`appdaemon==4.5.13`) as the sole direct requirement.

### Config Bridge — Minimal by Design

**AppDaemon does NOT expose its full config through HA's add-on options UI.** The `options.json` schema only controls the container environment:
- `system_packages` — Alpine packages to install on startup
- `python_packages` — pip packages to install on startup
- `init_commands` — arbitrary shell commands before AppDaemon starts
- `log_level` — mapped to AppDaemon's `-D` flag

Users edit `appdaemon.yaml` directly for all AppDaemon-specific config. The init script uses `yq` (Go-based YAML processor) to surgically patch exactly two values: the `SUPERVISOR_TOKEN` and the HTTP URL. Everything else is the user's responsibility.

**Lesson for hassette:** Don't try to represent hassette's full config in `options.json`. Keep the add-on options minimal (token, log level, packages). Let users edit `hassette.toml` directly.

### Web UI / Ingress — Exposed Port, No Ingress

**AppDaemon does NOT use ingress.** It exposes port 5050 directly:

```yaml
webui: http://[HOST]:[PORT:5050]
ports:
  5050/tcp: 5050
```

The "Open Web UI" button opens a new browser tab to `http://<host>:5050`. This is AppDaemon's biggest UX weakness — no SSL termination through HA, no HA authentication for dashboard access, users must handle port exposure/firewalling themselves.

**Lesson for hassette:** This is where hassette can differentiate. If the ingress complexity is solvable, it provides meaningfully better UX. If it proves too costly, the exposed-port approach is a proven fallback. Node-RED's add-on may be a better reference for ingress with a web UI.

### HA API Connection

AppDaemon core defaults to `http://supervisor/core` with `SUPERVISOR_TOKEN` from the environment:

```python
class HASSConfig(PluginConfig, extra="forbid"):
    ha_url: URL = Field(default="http://supervisor/core", validate_default=True)
    token: SecretStr = Field(default_factory=lambda: SecretStr(os.environ.get("SUPERVISOR_TOKEN")))
```

Combined with `homeassistant_api: true` in the add-on config, this means zero manual auth setup.

**Lesson for hassette:** `build_ws_url()` must preserve the `/core` path prefix from `base_url`. AppDaemon handles this correctly because it doesn't strip the base URL path.

### User App Dependencies

Installed on every container startup via bash loops in the init script:

```bash
for package in $(bashio::config 'python_packages'); do
    pip3 install "$package"
done
```

No venv — everything installs into system Python. Packages are listed in the add-on options UI, not a `requirements.txt`. `init_commands` provides an escape hatch for complex setups.

**Lesson for hassette:** The startup-install pattern is accepted in the HA add-on ecosystem (AppDaemon has done it for years). The UX cost is real but tolerated. Using `uv` instead of `pip` would be significantly faster. Venv isolation for user deps would prevent conflicts with hassette's own dependencies.

### Process Supervision — s6-overlay v3

Two-phase s6-rc startup:
1. **`init-appdaemon`** (oneshot) — config migration, YAML patching, package installation
2. **`appdaemon`** (longrun) — `exec appdaemon -c /config -D "${log_level}"`

The finish script halts the container on non-zero exit, making crashes visible to the Supervisor for automatic restart. Note: `init: false` in the config means "don't inject Docker's `--init`", not "don't use s6" — the base image ships s6-overlay regardless.

**Lesson for hassette:** Use the same two-phase pattern. Separating init (config patching, dep install) from the main process is clean and well-tested.

### Storage

No SQLite. All state is in YAML files under `/config/` (via `addon_config:rw`). This is the newer HA convention — user-editable config goes in `/addon_config/<slug>/` on the host. `/data/` is for private add-on state.

**Lesson for hassette:** Put SQLite in `/data/` (private, backed up automatically). Put `hassette.toml` and user apps in `/addon_config/` (user-editable, also backed up).

### Logging

stdout/stderr by default. HA Supervisor captures it for the Logs tab. Log level mapped from HA's enum to AppDaemon's via the run script. No special handling needed.

## Critique Findings

Three independent critics (Senior Engineer, Systems Architect, Adversarial Reviewer) reviewed this research brief. Key findings by confidence:

### CRITICAL (all 3 critics agreed)
1. **`build_ws_url()` silently drops base path** — `_parse_and_normalize_url()` returns `(scheme, host, port)` and discards the path. `http://supervisor/core` produces `ws://supervisor/api/websocket` instead of `ws://supervisor/core/api/websocket`. Must be fixed before any add-on work.
2. **Frontend has five independent hardcoded root paths** — API client, WebSocket, router, Vite build, FastAPI mounts all assume `/` as root. Behind ingress, the entire UI is non-functional.
3. **Option B→A is a rewrite, not a migration** — different OS, init system, user model, package manager, and entrypoint.

### HIGH (2+ critics)
4. **Bash config bridge loses types** — use a native Pydantic settings source for `/data/options.json` instead (Senior + Adversarial)
5. **`docker_start.sh` installs packages on every startup** — network dependency, startup latency, writable layer assumption (Senior + Adversarial)

### HIGH (single critic, strong evidence)
6. **SQLite WAL + hot backup = silent data corruption** — filesystem-level copy of `/data` while WAL is active produces corrupt restores (Senior)

### TENSION
7. **Is an add-on the right abstraction?** — Adversarial reviewer argues `panel_iframe` + HACS integration delivers better HA integration with far less work. Senior and Architect accept the add-on as given. Worth evaluating before committing.

Full critic reports available (session-scoped):
- Senior: `/tmp/claude-mine-challenge-NUYRV9/senior.md`
- Architect: `/tmp/claude-mine-challenge-NUYRV9/architect.md`
- Adversarial: `/tmp/claude-mine-challenge-NUYRV9/adversarial.md`

## References

- [HA App/Add-on Configuration Schema](https://developers.home-assistant.io/docs/apps/configuration/)
- [HA App Presentation (Ingress)](https://developers.home-assistant.io/docs/apps/presentation/)
- [Introducing Hass.io Ingress](https://www.home-assistant.io/blog/2019/04/15/hassio-ingress/)
- [How to use X-Ingress-Path in an add-on](https://community.home-assistant.io/t/how-to-use-x-ingress-path-in-an-add-on/276905)
- [HA Supervisor Proxy and Ingress (DeepWiki)](https://deepwiki.com/home-assistant/supervisor/6.3-proxy-and-ingress)
- [HA Docker Base Images](https://github.com/home-assistant/docker-base)
- [S6-Overlay for HA Docker Containers](https://developers.home-assistant.io/blog/2020/04/12/s6-overlay/)
- [SUPERVISOR_TOKEN issue discussion](https://github.com/home-assistant/supervisor/issues/5028)
- [Community add-on structure guide](https://blog.michal.pawlik.dev/posts/smarthome/home-assistant-addons/)
- [Can't get Ingress to work](https://community.home-assistant.io/t/cant-get-ha-add-on-ingress-to-work-what-am-i-doing-wrong/766070)
- [hassio-addons/addon-appdaemon](https://github.com/hassio-addons/addon-appdaemon) — AppDaemon add-on (Dockerfile, config, s6 services)
- [AppDaemon/appdaemon](https://github.com/AppDaemon/appdaemon) — AppDaemon core (HASSConfig defaults)
- [Trouble with static assets under ingress](https://community.home-assistant.io/t/trouble-with-static-assets-in-custom-addon-with-ingress/712298)

### Key Hassette Source Files

- Entry point: `src/hassette/__main__.py`
- Config system: `src/hassette/config/config.py`, `src/hassette/config/helpers.py`, `src/hassette/config/defaults.py`
- Web API service: `src/hassette/core/web_api_service.py`
- FastAPI app factory: `src/hassette/web/app.py`
- WebSocket service: `src/hassette/core/websocket_service.py`
- URL utilities: `src/hassette/utils/url_utils.py`
- Frontend API client: `frontend/src/api/client.ts`
- Frontend WebSocket hook: `frontend/src/hooks/use-websocket.ts`
- Frontend app/router: `frontend/src/app.tsx`
- Vite config: `frontend/vite.config.ts`
- Existing Dockerfile: `Dockerfile`
- Docker startup script: `scripts/docker_start.sh`
- TOML defaults: `src/hassette/config/hassette.prod.toml`
