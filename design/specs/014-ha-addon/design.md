# Design: Home Assistant Add-on for Hassette

**Date:** 2026-03-21
**Status:** draft
**Research:** `design/research/2026-03-21-ha-addon/research.md`

## Problem

Hassette currently requires users to set up their own Docker deployment. Users who run Home Assistant need to pull the GHCR image, write a docker-compose file, configure networking, and manage the container lifecycle manually. An HA add-on would let users install and manage hassette from the HA UI with zero Docker knowledge.

## Non-Goals

- **Ingress support** — The web UI will use an exposed port (like AppDaemon), not HA's ingress proxy. Ingress is a follow-up. This eliminates the entire frontend path-rewriting effort identified as the highest-risk item.
- **Distribution via HACS or official add-on store** — This design covers the technical add-on, not store listing or review process.
- **armv7 support** — Target amd64 and aarch64 only.
- **Full config through HA UI** — Following AppDaemon's pattern, only environment-level options (log level, packages) go in the add-on options. Users edit `hassette.toml` directly for framework config.

## Architecture

### Overview

A separate `hassette-addon` directory (or repository) containing the HA add-on metadata and a dedicated Dockerfile. The Dockerfile uses HA's Alpine-based Python base images with s6-overlay. Hassette is built from source (not pip installed), preserving the same build process as the standalone image. The two Dockerfiles share no code but build the same application.

### Add-on Repository Structure

```
hassette-addon/
  config.yaml          # Add-on metadata, options schema, permissions
  build.yaml           # Per-arch base images
  Dockerfile           # HA-specific, Alpine-based, s6-overlay
  DOCS.md              # User-facing documentation
  CHANGELOG.md
  icon.png             # 128x128
  logo.png             # 256x256
  translations/
    en.yaml            # Option descriptions
  rootfs/
    etc/s6-overlay/s6-rc.d/
      init-hassette/   # oneshot: config patching, user dep install
        type           # "oneshot"
        up             # path to run script
        run            # bash init script
      hassette/        # longrun: the main process
        type           # "longrun"
        run            # exec hassette
        finish         # halt container on crash
        dependencies.d/
          init-hassette
      user/contents.d/
        init-hassette
        hassette
```

### config.yaml

```yaml
name: Hassette
description: Async-first Python framework for Home Assistant automations
version: 0.23.0
slug: hassette
url: https://github.com/nodejsmith/hassette
arch:
  - amd64
  - aarch64
homeassistant_api: true
init: false
ports:
  8126/tcp: 8126
ports_description:
  8126/tcp: Hassette Web UI
webui: http://[HOST]:[PORT:8126]
map:
  - addon_config:rw
watchdog: http://[HOST]:[PORT:8126]/api/health
backup: hot
options:
  log_level: info
  python_packages: []
  init_commands: []
schema:
  log_level: list(debug|info|warning|error|critical)
  python_packages:
    - str
  init_commands:
    - str
```

Key decisions:
- `homeassistant_api: true` — Supervisor injects `SUPERVISOR_TOKEN` for HA API access
- `init: false` — The Dockerfile uses s6-overlay from the HA base image, not Docker's `--init`
- `ports: 8126/tcp` — Exposed port for the web UI (no ingress)
- `webui` — HA shows an "Open Web UI" button linking to port 8126
- `watchdog` — Uses hassette's existing `/api/health` endpoint for auto-restart on crash
- `map: addon_config:rw` — User config (`hassette.toml`, apps) lives in `/addon_config/` on the host
- Options are minimal (AppDaemon pattern): log level, Python packages, init commands. No hassette-specific config exposed — users edit `hassette.toml`.

### Dockerfile

Multi-stage build on HA Alpine base images:

```dockerfile
ARG BUILD_FROM
FROM node:22-slim AS frontend
WORKDIR /app/frontend
COPY frontend/package*.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

FROM ghcr.io/astral-sh/uv:0.9.8 AS uv

FROM ${BUILD_FROM}

# Build deps for C extensions (orjson, aiohttp, watchfiles)
RUN apk add --no-cache --virtual .build-deps \
        build-base python3-dev rust cargo \
    && apk add --no-cache \
        python3 py3-pip fd

COPY --from=uv /uv /bin/uv

WORKDIR /app
COPY pyproject.toml uv.lock README.md ./
COPY src/ ./src/
COPY --from=frontend /app/src/hassette/web/static/spa/ ./src/hassette/web/static/spa/
COPY scripts/ ./scripts/

ENV UV_LINK_MODE=copy
RUN uv sync --locked --no-editable --active --no-default-groups \
    && apk del --no-cache --purge .build-deps

ENV PATH="/app/.venv/bin:$PATH" \
    HASSETTE__CONFIG_DIR=/addon_config \
    HASSETTE__DATA_DIR=/data \
    HASSETTE__APP_DIR=/addon_config/apps \
    PYTHONUNBUFFERED=1

COPY rootfs/ /
```

Key differences from standalone Dockerfile:
- `FROM ${BUILD_FROM}` — HA builder substitutes the correct arch base image
- Alpine packages (`apk`) instead of Debian (`apt-get`)
- Build deps installed as virtual package and removed after build (AppDaemon pattern)
- No tini (s6-overlay is PID 1)
- No non-root user creation (s6-overlay handles privileges)
- `HASSETTE__CONFIG_DIR=/addon_config` (not `/config`, which is HA's own config dir)
- `HASSETTE__APP_DIR=/addon_config/apps` (user apps alongside config)
- rootfs overlay for s6 service definitions

### build.yaml

```yaml
build_from:
  amd64: ghcr.io/home-assistant/amd64-base-python:3.13
  aarch64: ghcr.io/home-assistant/aarch64-base-python:3.13
```

### C Extension Compatibility (Alpine)

The following hassette dependencies have C/Rust extensions that need build-time tools on Alpine:

| Package | Extension type | Alpine build deps |
|---------|---------------|-------------------|
| `orjson` | Rust | `rust`, `cargo` |
| `aiohttp` | C | `build-base`, `python3-dev` |
| `watchfiles` | Rust (via pyo3) | `rust`, `cargo` |
| `uvloop` (via uvicorn[standard]) | C | `build-base`, `python3-dev` |

These are installed as `.build-deps` and removed after `uv sync` to keep the image small. If pre-built Alpine wheels are available on PyPI (increasingly common for these packages), the build deps aren't needed and the install is fast.

**Risk mitigation:** Verify Alpine wheel availability before implementation. Run `uv pip install --dry-run hassette` on an Alpine 3.22 + Python 3.13 container to check.

### s6-overlay Services

**Phase 1: init-hassette (oneshot)**

```bash
#!/command/with-contenv bashio

# Set HA connection defaults for add-on mode
export HASSETTE__BASE_URL="http://supervisor/core"
export HASSETTE__TOKEN="${SUPERVISOR_TOKEN}"

# Map log level from HA's enum
case "$(bashio::string.lower "$(bashio::config 'log_level')")" in
    debug)   export HASSETTE__LOG_LEVEL="DEBUG" ;;
    info)    export HASSETTE__LOG_LEVEL="INFO" ;;
    warning) export HASSETTE__LOG_LEVEL="WARNING" ;;
    error)   export HASSETTE__LOG_LEVEL="ERROR" ;;
    critical) export HASSETTE__LOG_LEVEL="CRITICAL" ;;
esac

# Install user Python packages (from add-on options)
if bashio::config.has_value 'python_packages'; then
    for package in $(bashio::config 'python_packages'); do
        uv pip install "$package"
    done
fi

# Run user init commands
if bashio::config.has_value 'init_commands'; then
    while read -r cmd; do
        eval "${cmd}"
    done <<< "$(bashio::config 'init_commands')"
fi

# Seed default config if none exists
if [ ! -f /addon_config/hassette.toml ]; then
    cp /app/scripts/hassette.addon.toml /addon_config/hassette.toml
fi
```

**Phase 2: hassette (longrun)**

```bash
#!/command/with-contenv bashio
export HASSETTE__BASE_URL="http://supervisor/core"
export HASSETTE__TOKEN="${SUPERVISOR_TOKEN}"
exec hassette
```

**Finish script:**

```bash
#!/command/with-contenv bashio
declare exit_code_service=${1}
if [[ "${exit_code_service}" -ne 0 ]]; then
    echo "${exit_code_service}" > /run/s6-linux-init-container-results/exitcode
    exec /run/s6/basedir/bin/halt
fi
```

### Config Strategy

Following the AppDaemon pattern, the add-on options are deliberately minimal. The config bridge is env vars set in the s6 run scripts, not a bash-to-JSON translation layer:

| Config source | What it provides | Priority |
|---|---|---|
| s6 run script env vars | `HASSETTE__BASE_URL`, `HASSETTE__TOKEN`, `HASSETTE__LOG_LEVEL` | Highest (env vars) |
| `/addon_config/hassette.toml` | All other hassette config (apps, timeouts, filters, etc.) | Normal (TOML source) |
| Built-in defaults | Docker-aware defaults (`/data`, `/addon_config`) | Lowest |

This avoids the type-lossy config bridge the critics flagged. Only three values come from the add-on options; everything else is native hassette config.

### HA API Connection — build_ws_url() Fix

**This is a prerequisite.** `_parse_and_normalize_url()` in `src/hassette/utils/url_utils.py:43` discards the path from `base_url`. With `base_url = "http://supervisor/core"`, it produces `ws://supervisor/api/websocket` instead of `ws://supervisor/core/api/websocket`.

Fix: return `(scheme, host, port, base_path)` and prepend `base_path` to the API paths.

```python
# Before
def _parse_and_normalize_url(config) -> tuple[str, str, int | None]:
    ...
    return yurl.scheme, yurl.host, yurl.explicit_port

# After
def _parse_and_normalize_url(config) -> tuple[str, str, int | None, str]:
    ...
    base_path = yurl.path.rstrip("/") if yurl.path and yurl.path != "/" else ""
    return yurl.scheme, yurl.host, yurl.explicit_port, base_path

def build_ws_url(config) -> str:
    scheme, hostname, port, base_path = _parse_and_normalize_url(config)
    ws_scheme = "wss" if scheme == "https" else "ws"
    yurl = URL.build(scheme=ws_scheme, host=hostname, port=port,
                     path=f"{base_path}/api/websocket")
    return str(yurl)
```

This fix benefits all deployments behind reverse proxies, not just the add-on.

### SQLite Backup Safety

The critic flagged that SQLite in WAL mode can corrupt during HA's hot backup of `/data`. Mitigation: add a periodic checkpoint to the database service that runs `PRAGMA wal_checkpoint(TRUNCATE)` on a schedule (e.g., every 5 minutes). This minimizes the WAL file and reduces the corruption window. For full safety, a future enhancement could use SQLite's backup API to create consistent snapshots.

### Logging

Disable `coloredlogs` when running as an add-on (ANSI codes don't render in HA's log viewer). Detection: check for `SUPERVISOR_TOKEN` in the environment at startup. If present, configure plain text logging.

### User App Directory

User apps live at `/addon_config/apps/` (mapped to `addon_configs/<slug>/apps/` on the host). Users can edit these files directly through the HA file editor add-on or via Samba/SSH. The `hassette.toml` file lives at `/addon_config/hassette.toml`.

A default `hassette.toml` template is seeded on first run with sensible add-on defaults (no `base_url` or `token` since those come from env vars).

### User Dependency Installation

User Python packages are specified in the add-on options UI (like AppDaemon) and installed during the s6 init phase using `uv pip install`. This happens on every container start. Using `uv` instead of `pip` gives ~10x faster installs.

Additionally, if the user has a `requirements.txt` in their apps directory, it will be installed. The `fd` command (Alpine: `fd-find` → `fd`) replaces `fdfind` from the Debian image.

## Alternatives Considered

### Option B: Reuse existing GHCR Docker image with `init: false`

Rejected because: UID 1000 mismatch with root-owned Supervisor paths, no s6-overlay for process supervision, Debian-slim is non-standard for HA add-ons, and the critics unanimously flagged B→A migration as a rewrite rather than a step.

### Option C: HA base image + `pip install hassette`

Rejected because: the PyPI package doesn't include the SPA frontend assets (the build output is gitignored and only produced by the Docker image's Node stage). Would require either adding a frontend build step to PyPI publishing or building the frontend in the add-on Dockerfile — the latter is what Option A does anyway.

### Ingress instead of exposed port

Deferred to a follow-up. The frontend has five independent hardcoded root paths that all need ingress awareness. This is the highest-effort, highest-risk item and is not required for a functional add-on. The exposed port approach (AppDaemon's model) works today with zero frontend changes.

### panel_iframe via HACS integration

The adversarial reviewer suggested a HACS custom integration with `panel_iframe` instead of an add-on. This achieves sidebar integration without ingress but doesn't solve the deployment problem — users still need to run the Docker container themselves. The add-on handles both deployment and basic UI access.

## Open Questions

- [ ] **Alpine wheel availability** — Do `orjson`, `aiohttp`, `watchfiles`, and `uvloop` have pre-built wheels for Alpine 3.22 + Python 3.13? If not, Rust/C build deps are needed in the Dockerfile and the build will be slower.
- [ ] **Add-on repo location** — Separate `hassette-addon` repo, or a subdirectory in the main hassette repo? Separate is cleaner for HACS; subdirectory keeps everything together.
- [ ] **SUPERVISOR_TOKEN as bearer token** — Verify that `SUPERVISOR_TOKEN` works as a bearer token for WebSocket authentication through the Supervisor proxy at `http://supervisor/core`. AppDaemon does this, so it should work, but needs testing.
- [ ] **Existing docker_start.sh callers** — The standalone Dockerfile still uses `docker_start.sh`. The add-on has its own s6 scripts. No shared code between the two startup paths.

## Impact

### Files changed in hassette core (prerequisites)

| File | Change |
|---|---|
| `src/hassette/utils/url_utils.py` | Preserve base path in `_parse_and_normalize_url()` |
| `src/hassette/__main__.py` or logging setup | Detect `SUPERVISOR_TOKEN` and disable coloredlogs |
| `src/hassette/core/database_service.py` | Add periodic WAL checkpoint |

### New files (add-on repository/directory)

| File | Purpose |
|---|---|
| `config.yaml` | Add-on metadata and options schema |
| `build.yaml` | Per-arch base images |
| `Dockerfile` | HA-specific Alpine build |
| `DOCS.md` | User documentation |
| `CHANGELOG.md` | Version history |
| `icon.png`, `logo.png` | Branding |
| `translations/en.yaml` | Option descriptions |
| `rootfs/etc/s6-overlay/s6-rc.d/...` | s6 service definitions |
| `scripts/hassette.addon.toml` | Default config template for first run |

### Dependencies affected

None. The add-on uses hassette's existing dependencies. The Dockerfile installs build-time deps (build-base, python3-dev, rust) temporarily for C extension compilation.
