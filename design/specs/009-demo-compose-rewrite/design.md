# Design: Compose-Native Demo Stack

**Date:** 2026-07-12
**Status:** approved
**Scope-mode:** hold
**Research:** design/research/2026-07-12-demo-compose/research.md

## Problem

The demo orchestrator (`scripts/hassette_demo.py`, ~392 lines) and screenshot capture tool (`scripts/capture_screenshots.py`, ~301 lines) manage three services through manual subprocess orchestration: dynamic port allocation, process-group lifecycle, signal handling with cascading teardown, readiness polling, and a stdout IPC protocol. This architecture leaks Docker containers when interrupted (#1158), is difficult to modify or debug, and represents ~700 lines of fragile infrastructure for what should be "start three things, block, clean up."

Only HA runs in Docker today. Hassette and Vite run as bare host subprocesses, requiring the orchestrator to manage their full lifecycle. `capture_screenshots.py` adds another layer by spawning the orchestrator as a child process and parsing its stdout for port discovery — a design motivated by a stdlib-only constraint that no longer applies (both scripts require `uv`).

## Goals

- All three demo services (HA, hassette, vite) start and stop via `docker compose up/down`
- Teardown is reliable under all exit conditions (Ctrl-C, SIGTERM, crash, timeout)
- Combined script line count drops from ~700 to under 250
- No module-level mutable state or process-group signal cascades
- Ports are fixed and deterministic — no dynamic discovery protocol
- SSH tunnel access works for remote development
- Vite HMR works for live CSS/TSX editing
- `capture_screenshots.py` runs shot-scraper without spawning a subprocess

## Non-Goals

- Consolidating the HA JWT token to a single source (currently duplicated in 3 places)
- Rewriting `demo-verify` from scratch (minimal adaptation only)
- Changes to the production Dockerfile or deployment workflow
- Changes to the screenshot manifest format (`docs/screenshots.yml`) or shot-scraper integration
- Supporting concurrent demo runs (confirmed unnecessary — never happens in practice)

## User Scenarios

### Developer: Visual QA iteration

- **Goal:** Run the demo stack to iterate on frontend CSS/TSX with live reload
- **Context:** SSHed into dev machine from laptop, editing in a remote session

#### Start demo and iterate

1. **Run `uv run python scripts/hassette_demo.py`**
   - Sees: compose building/pulling images, service health progress
   - Then: human-readable URLs printed when all services healthy
2. **Open `http://localhost:15173` via SSH tunnel**
   - Sees: live dashboard with example apps running
3. **Edit CSS/TSX files**
   - Sees: changes hot-reload in the browser via Vite HMR
4. **Ctrl-C the script**
   - Then: `docker compose down --remove-orphans` cleans up everything

### CI agent: Screenshot capture

- **Goal:** Regenerate doc screenshots deterministically
- **Context:** Automated workflow, no human interaction

#### Capture screenshots

1. **Run `uv run python scripts/capture_screenshots.py`**
   - Then: demo stack starts via compose, waits for health
2. **Script polls for demo_stimulator error data**
   - Then: runs shot-scraper against fixed-port URLs
3. **Script exits**
   - Then: compose down cleans up all containers and networks

## Functional Requirements

- **FR#1** `docker compose up` starts all three services (HA, hassette, vite) from a single compose file
- **FR#2** `docker compose down --remove-orphans` removes all containers and networks created by the demo stack
- **FR#3** Each service uses a fixed default port on the host, overridable via environment variable (`DEMO_HA_PORT`, `DEMO_HASSETTE_PORT`, `DEMO_VITE_PORT`)
- **FR#4** Each service declares a health check in the compose file; `docker compose up --wait` blocks until all are healthy
- **FR#5** The orchestrator copies HA fixture config to a temp directory before starting compose, using the same ignore list as `tests/system/conftest.py`
- **FR#6** Hassette's `.demo-data/` directory persists between demo runs via host bind mount
- **FR#7** Vite serves the frontend with working HMR over Docker port mapping
- **FR#8** All demo ports are accessible via SSH tunnel (bound to `127.0.0.1` on the host)
- **FR#9** `capture_screenshots.py` starts and stops the demo stack by importing the shared `DemoStack` module directly, rather than spawning `hassette_demo.py` as a child process and parsing its stdout
- **FR#10** `hassette_demo.py` prints human-readable URLs after startup, blocks until signaled, then tears down via compose

## Edge Cases

- **Ctrl-C during `compose up --wait`**: compose handles SIGINT natively — tears down any partially-started services
- **Ctrl-C while blocked on `signal.pause()`**: `DemoStack`'s signal handler runs `compose down`; the context manager's `__exit__` is the fallback via atexit
- **Second Ctrl-C during teardown**: `compose down` is already running; a second SIGINT is either ignored (if teardown is in progress) or forces an immediate exit — compose still removes containers on its next run via `--remove-orphans`
- **Port already in use**: compose fails with a clear error; no special handling needed beyond letting the error propagate
- **Docker not running**: detected before compose up; script exits with an actionable error message
- **Previous demo not cleaned up**: `--remove-orphans` on compose down handles stale containers from prior runs; the fixed project name ensures compose sees them
- **`.demo-data/` contains stale data**: `capture_screenshots.py` deletes DB files before starting (existing behavior, preserved)
- **Container build failure**: compose reports the build error; script exits non-zero

## Acceptance Criteria

- **AC#1** Running `uv run python scripts/hassette_demo.py` starts all three services and prints URLs within 120s (FR#1, FR#4, FR#10)
- **AC#2** Ctrl-C during any phase (startup, running, teardown) leaves no orphaned containers (`docker ps` shows none with the demo project name) (FR#2)
- **AC#3** `uv run python scripts/capture_screenshots.py` produces the same screenshot set as the current script against the same demo state (FR#9)
- **AC#4** Editing a `.tsx` file while the demo is running triggers a hot reload in the browser without requiring a full page reload (FR#7)
- **AC#5** All three demo ports are reachable via SSH tunnel from a different machine (FR#8)
- **AC#6** `DEMO_HA_PORT=29123 DEMO_HASSETTE_PORT=29126 DEMO_VITE_PORT=29173 uv run python scripts/hassette_demo.py` starts the stack on the overridden ports (FR#3)
- **AC#7** Combined line count of `hassette_demo.py` + `capture_screenshots.py` + `demo_stack.py` is under 250 lines (goals)

## Key Constraints

- The HA fixture ignore list in `demo_stack.py` must match the one in `tests/system/conftest.py`. A comment cross-references the location. (Existing constraint, preserved from the current script.)
- Vite must run with `--host 0.0.0.0` inside the container for Docker port mapping to work. This is set in the Dockerfile CMD, not in `vite.config.ts`, to avoid affecting non-Docker development.

## Dependencies and Assumptions

- Docker Compose v2.17+ (for `up --wait`; `condition: service_healthy` is older but `--wait` shipped around v2.17)
- Docker engine running natively inside WSL2 (not Docker Desktop) — bind mounts use the native Linux filesystem, so inotify works correctly for Vite HMR. This was the research brief's primary concern with the compose approach; the grill phase resolved it by confirming the Docker setup is WSL2-native (no 9p/virtio-fs translation layer)
- `uv` and `npm` available on the host (for building dev images)
- Python and UV versions match the production Dockerfile (`python:3.14`, `uv:0.11.26`)

## Architecture

### Compose file extension

Extend `scripts/docker/ha-demo.yml` with `hassette` and `vite` services. Each service declares a health check and uses `depends_on` with `condition: service_healthy` for startup ordering: HA → hassette → vite.

Port mapping uses fixed defaults with env-var overrides:
- HA: `${DEMO_HA_PORT:-18123}:8123`
- Hassette: `${DEMO_HASSETTE_PORT:-18126}:8126`
- Vite: `${DEMO_VITE_PORT:-15173}:5173`

All ports bind to `127.0.0.1` on the host (SSH-tunnel friendly, not exposed to LAN).

Inter-service networking uses Docker DNS:
- Hassette reaches HA at `http://homeassistant:8123`
- Vite proxies to hassette at `http://hassette:8126`

### Dev Dockerfiles

Two minimal Dockerfiles in `scripts/docker/`:

**`Dockerfile.hassette-dev`** (~6 lines): `python:3.14-slim` base, copies `uv` from the astral image, sets WORKDIR to `/app`, sets `UV_PROJECT_ENVIRONMENT=/opt/venv` so `uv sync` writes the venv outside the bind-mounted source tree (without this, `uv sync` as root would overwrite the host's `.venv`, breaking local pyright/pytest). CMD runs `uv sync --locked` then `exec uv run python -m hassette --config-file examples/hassette.toml run`.

**`Dockerfile.vite-dev`** (~5 lines): `node:24-slim` base, sets WORKDIR to `/app/frontend`. CMD runs `npm install` then `exec npm run dev -- --host 0.0.0.0 --port 5173`. Source comes from a bind mount; `node_modules` uses an anonymous volume to avoid platform-specific native module issues.

### Shared lifecycle module

New `scripts/demo_stack.py` module (~80 lines) providing a `DemoStack` context manager:

```python
with DemoStack() as demo:
    # All services healthy, ports available
    print(f"Frontend: http://localhost:{demo.vite_port}")
    signal.pause()
# compose down runs automatically in __exit__
```

Responsibilities:
- Copy HA fixture config to tmpdir (with the synced ignore list)
- Set compose env vars (ports, config path, token)
- Run `docker compose up -d --wait`
- Expose port values as properties
- Run `docker compose down --remove-orphans` and clean up tmpdir in `__exit__`
- Register atexit + signal handlers for reliability

### Simplified scripts

**`hassette_demo.py`** (~30 lines): Imports `DemoStack`, enters the context manager, prints human-readable URLs, calls `signal.pause()`.

**`capture_screenshots.py`** (~120 lines): Imports `DemoStack`, enters the context manager, deletes stale demo DB files, polls the hassette API for `demo_stimulator` error data (existing logic), resolves the screenshot manifest with fixed ports, runs shot-scraper. No subprocess spawning, no stdout parsing, no process-group teardown.

### Volume mounts

| Service | Bind mount | Purpose |
|---------|-----------|---------|
| HA | `${HA_CONFIG_PATH}:/config` | Pre-seeded fixture config (tmpdir, set by script) |
| Hassette | `<repo_root>:/app` | Live source for development iteration (`UV_PROJECT_ENVIRONMENT=/opt/venv` keeps the venv outside the mount) |
| Hassette | `<repo_root>/.demo-data:/app/.demo-data` | Persistent telemetry DB |
| Vite | `<repo_root>/frontend:/app/frontend` | Live source for HMR |
| Vite | anonymous at `/app/frontend/node_modules` | Container-local deps |

## Implementation Preferences

- Compose project name: `hassette-demo` (fixed, no port suffix)
- Use `docker compose up -d --wait` instead of manual Python readiness polling
- Dev Dockerfiles reference the same Python/UV/Node versions as the production Dockerfile for consistency
- No `.env` file — the Python script passes env vars to compose via `subprocess.run(env=...)`

## Replacement Targets

| Old code | Replaced by | Action |
|----------|------------|--------|
| `hassette_demo.py` subprocess lifecycle (~300 lines) | `DemoStack` context manager + compose | Remove — full rewrite |
| `hassette_demo.py` `_poll_http()` readiness polling | Compose health checks + `--wait` | Remove |
| `hassette_demo.py` `find_free_port()` dynamic allocation | Fixed ports with env-var overrides | Remove |
| `hassette_demo.py` `_terminate_process_group()` teardown | `docker compose down` | Remove |
| `capture_screenshots.py` subprocess spawn + stdout IPC | Direct `DemoStack` import | Remove |
| `capture_screenshots.py` `line_queue` threaded reader | No longer needed (no stdout parsing) | Remove |
| `DEMO_*=` stdout key-value protocol | Human-readable print statements + fixed ports | Remove |
| `DEMO_VITE_HOST` env var for remote browser access | Compose port mapping on `127.0.0.1` + SSH tunnel | Remove (FR#8 replaces it) |

## Test Strategy

### Existing Tests to Adapt

No existing tests cover these scripts. They are validated by running them (`mise run demo-verify` is the closest thing to a test).

### New Test Coverage

No unit tests for the scripts themselves — the compose file's health checks and `demo-verify` serve as the integration test. Verify AC#1 through AC#7 manually during implementation.

### Tests to Remove

No tests to remove.

## Documentation Updates

- **CLAUDE.md** — Update the "Demo Stack & Doc Screenshots" section: remove references to `DEMO_*=` protocol and dynamic ports, document fixed default ports, update the `hassette_demo.py` description, note compose requirement
- **`.claude/skills/ui-qa/references/harness.md`** — Rewrite: remove `DEMO_*=` protocol parsing instructions, replace with fixed URLs (`http://localhost:15173`, `http://localhost:18126`), update startup command, simplify teardown instructions
- **`design/specs/048-visual-qa-environment/design.md`** — Update if it references the demo protocol (read and verify during implementation)

## Impact

### Changed Files

- modify: `scripts/docker/ha-demo.yml` — extend with hassette and vite services, health checks, volume mounts, networking
- create: `scripts/docker/Dockerfile.hassette-dev` — minimal Python+uv dev image (~5 lines)
- create: `scripts/docker/Dockerfile.vite-dev` — minimal Node dev image (~5 lines)
- create: `scripts/demo_stack.py` — shared DemoStack context manager (~80 lines)
- modify (rewrite): `scripts/hassette_demo.py` — thin wrapper around DemoStack (~30 lines)
- modify (rewrite): `scripts/capture_screenshots.py` — import DemoStack, remove subprocess/IPC code
- modify: `.mise/tasks/demo-verify` — adapt to fixed ports, remove DEMO_*= parsing
- modify: `CLAUDE.md` — update Demo Stack section
- modify: `.claude/skills/ui-qa/references/harness.md` — update to fixed URLs

### Behavioral Invariants

- `capture_screenshots.py` must produce the same screenshot set for the same manifest and demo state
- `mise run demo-verify` must still validate that all apps reach running status
- `mise run demo` must still start the demo stack for interactive use
- `.demo-data/` must persist between runs (for iterative visual QA)

### Blast Radius

- **Agents using ui-qa skill**: will read updated harness.md with fixed URLs — simpler for them
- **`docs/screenshots.yml`**: unchanged — manifest format is preserved
- **CI workflows**: not affected — neither script runs in CI

## Open Questions

None — all questions resolved during discovery and investigation.
