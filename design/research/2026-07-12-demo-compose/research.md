---
proposal: "Rewrite hassette_demo.py and capture_screenshots.py to use Docker Compose for all three demo services instead of manual subprocess management"
date: 2026-07-12
status: Draft
flexibility: Leaning
motivation: "Both reliability (orphaned containers, leaked resources) and maintainability (script is too complex for what it does, hard to modify/debug)"
constraints: "None stated beyond removing boilerplate and making it reliable"
non-goals: "None stated"
depth: normal
---

# Research Brief: Docker Compose for Demo Scripts

**Initiated by**: Rewrite `scripts/hassette_demo.py` (~392 lines) and `scripts/capture_screenshots.py` (~301 lines) to use Docker Compose for all three demo services (HA, hassette, vite) instead of manual subprocess management.

## Context

### What prompted this

The demo orchestrator (`hassette_demo.py`) is ~392 lines of stdlib-only process management: dynamic port allocation, subprocess lifecycle, signal handling with process-group teardown, readiness polling, and cascading cleanup. The screenshot capture script (`capture_screenshots.py`, ~301 lines) adds another layer by spawning the demo orchestrator as a child process and managing its lifecycle via a stdout IPC protocol. Both scripts have orphan risk on unclean shutdown (the parent's `atexit`/signal handlers must fire for cleanup to happen), and modifying either script requires understanding the full subprocess lifecycle.

### Current state

**Three services, one containerized.** The demo stack runs:

1. **Home Assistant** -- via `docker compose -f scripts/docker/ha-demo.yml up -d`, the only containerized service. Uses a pre-seeded JWT token, a fixture config directory copied to a tmpdir each run, and a Compose healthcheck polling `/api/` with Bearer auth. Dynamic port via env var `HA_PORT`, project name scoped to the port (`hassette-demo-{ha_port}`) for concurrency isolation.

2. **Hassette** -- bare host subprocess via `uv run python -m hassette --config-file examples/hassette.toml run`, with env vars for `HASSETTE__BASE_URL`, `HASSETTE__TOKEN`, `HASSETTE__WEB_API__PORT`, `HASSETTE__APPS__DIRECTORY=examples`, `HASSETTE__DATA_DIR=.demo-data`. Stdout/stderr redirected to a log file in the tmpdir.

3. **Vite dev server** -- bare host subprocess via `npm run dev --prefix frontend -- --port {vite_port}`, with `VITE_PROXY_TARGET` pointing to the hassette port. Optional `DEMO_VITE_HOST` env var passes `--host` for remote browser / SSH tunnel access.

**The orchestrator's lifecycle flow:**
1. Resolve repo root, reject Windows
2. Allocate 3 free ports (bind-to-0-then-close, documented TOCTOU race)
3. Copy HA fixture config (`tests/fixtures/demo-ha-config`) to tmpdir with an ignore list (kept in sync with `tests/system/conftest.py`)
4. Check docker compose and uv availability
5. Start HA, poll `/api/` for 3 consecutive 200s (60s timeout)
6. Start hassette, poll `/api/health` (30s timeout)
7. Conditionally `npm ci` if `node_modules` missing
8. Start Vite, poll root path for 200 (15s timeout)
9. Print `KEY=value` lines (`DEMO_HA_URL`, `DEMO_HASSETTE_URL`, `DEMO_FRONTEND_URL`, `DEMO_READY=true`)
10. `signal.pause()` -- block until signal

**Teardown** (idempotent, reverse order): SIGTERM Vite process group, SIGTERM hassette process group (fallback SIGKILL after 5s each), close log handles, `docker compose down`, `shutil.rmtree(tmpdir)`. Registered via both `atexit` and SIGINT/SIGTERM handlers.

**`capture_screenshots.py` protocol:** Spawns the demo orchestrator in its own process group, drains stdout via a background thread into a queue, parses `KEY=value` lines looking for `DEMO_READY=true` (180s deadline) or `DEMO_ERROR=...` (immediate exit). After readiness, polls a hassette telemetry endpoint waiting for `demo_stimulator` to accumulate error data (90s, soft timeout). Then resolves `{port}` placeholders in `docs/screenshots.yml`, prepends animation-disabling CSS injection JS to every entry, writes a temp manifest, and runs `uv run shot-scraper multi <manifest>`.

**`.demo-data/`** is a persistent repo-root directory (gitignored) for hassette's SQLite database across demo runs. `capture_screenshots.py` deletes the DB files at start for deterministic content but preserves the directory.

### Key constraints

**Stdout IPC contract is consumed by three independent callers:**
- `scripts/capture_screenshots.py` -- parses `DEMO_*` vars from stdout, exits on `DEMO_ERROR`
- `.mise/tasks/demo-verify` -- parses into bash associative array, polls hassette REST API for app count
- Agent-facing skill docs (`.claude/skills/ui-qa/`) -- instruct agents to start the demo and use the URLs

**Dynamic port allocation is load-bearing**, not just convenience. Compose project name derives from the HA port (`hassette-demo-{ha_port}`), and the entire stack avoids port and naming collisions across concurrent runs (developer + screenshot capture, or two sequential runs where teardown hasn't fully released ports yet).

**Vite runs for live reload.** CLAUDE.md explicitly documents the demo stack as the preferred tool for visual QA because "CSS/TSX edits apply live" -- the production Dockerfile builds a static SPA, so using the production image loses the HMR property.

**HA token is duplicated in three places** that must stay in sync: `hassette_demo.py` (constant), `scripts/docker/ha-demo.yml` (healthcheck), `tests/fixtures/demo-ha-config/.storage/auth`.

**Neither script runs in CI.** Screenshot regeneration and demo verification are local/agent workflows. The blast radius on CI of a rewrite is zero.

## Feasibility Analysis

### What would need to change

| Area | Files affected | Effort | Risk |
|------|---------------|--------|------|
| Demo compose file | `scripts/docker/ha-demo.yml` (extend) | Low | Low -- existing compose patterns to follow |
| Demo orchestrator | `scripts/hassette_demo.py` (rewrite) | Med | Med -- stdout contract must be preserved |
| Screenshot capture | `scripts/capture_screenshots.py` (modify) | Low | Low -- only if demo protocol changes |
| Dev Dockerfiles | 2 new files (hassette-dev, vite-dev) | Med | Med -- no existing dev images |
| Mise tasks | `.mise/tasks/demo`, `.mise/tasks/demo-verify` | Low | Low -- if stdout contract preserved |
| Agent docs | `.claude/skills/ui-qa/` references | Low | Low -- URL format unchanged |
| CLAUDE.md | Demo Stack section | Low | Low -- documentation only |

### What already supports this

- **HA is already in Compose.** The `ha-demo.yml` file already uses Compose health checks and env-var-driven port mapping -- extending it with more services is natural.
- **A production Dockerfile exists** at repo root. It has a multi-stage build (frontend, uv, builder, runtime) and an entrypoint script (`scripts/docker_start.sh`). While this builds a static SPA (no Vite dev server), it provides a reference for what a hassette container needs.
- **Hassette exposes health endpoints.** `/api/health`, `/api/health/live`, `/api/health/ready` are all available. The production docker-compose example (`docs/pages/getting-started/docker/snippets/docker-compose.yml`) uses `/api/health/live` for its healthcheck (explicitly avoids `/api/health/ready` because "using ready here causes a restart loop whenever HA restarts").
- **The existing compose file already uses dynamic port mapping** via `${HA_PORT:-8123}:8123`, so the pattern for parameterized ports is established.

### What works against this

1. **Vite in a container loses fast HMR.** The Vite dev server watches the filesystem for changes. Inside a Docker container on Linux (bind mount), inotify events work but add latency. On macOS/WSL2, filesystem watching over bind mounts is notoriously unreliable or falls back to polling. The demo stack's value proposition is "CSS/TSX edits apply live" -- degrading HMR undermines the primary use case.

2. **No dev Dockerfiles exist.** The production Dockerfile builds a static SPA and installs a locked set of dependencies. A dev image for hassette would need `uv` + source volume mount (for live code changes), and a dev image for Vite would need Node + source volume mount + exposed HMR port. These are new artifacts to create and maintain.

3. **Dynamic ports are awkward in Compose.** Compose can allocate dynamic host ports (`"127.0.0.1::8123"`), but discovering them requires running `docker compose port <service> <container-port>` after start. The orchestrator script still needs to resolve these ports and surface them via the stdout contract -- so the "just run `docker compose up`" simplification doesn't fully materialize.

4. **Inter-service networking adds complexity.** If hassette runs in a container, it needs to reach HA at the Docker network address (not `localhost`). Vite on the host needs to proxy to hassette in a container (requiring the mapped host port). The current setup avoids this entirely because all three services share `localhost`.

5. **Source volume mounts for hassette are complex.** Hassette needs `pyproject.toml`, `uv.lock`, `src/`, `examples/`, and potentially `codegen/` mounted. The production image copies these at build time. A dev image needs them bind-mounted for live changes, but hassette's `examples/hassette.toml` references relative paths (`apps.directory = "examples"`) that would need to resolve inside the container's volume mount structure.

## Options Evaluated

### Option A: Full Docker Compose (all three services containerized)

**How it works**: Extend `ha-demo.yml` with `hassette` and `vite` services. Create two dev Dockerfiles: one for hassette (Python + uv, source bind-mounted), one for Vite (Node, frontend source bind-mounted). Replace the Python orchestrator with a thin wrapper that runs `docker compose up -d`, polls `docker compose port` to discover dynamic ports, and prints the stdout IPC contract. Teardown becomes `docker compose down`. Health checks for all three services are declared in the compose file.

The hassette dev image would use the same Python base as the production Dockerfile but skip the multi-stage build -- instead bind-mounting `src/` and `examples/` and running `uv run python -m hassette run`. The Vite dev image would use the same Node base as the frontend build stage but run `npm run dev` instead of `npm run build`, with the frontend source bind-mounted.

Compose networking would use a shared bridge network. Hassette reaches HA at `homeassistant:8123` (Docker DNS). Vite's `VITE_PROXY_TARGET` would point to `hassette:<port>` if Vite is also containerized, or to `host.docker.internal:<mapped-port>` if Vite stays on the host.

**Pros**:
- `docker compose down` is more reliable cleanup than process-group signal cascades -- no orphaned processes if the parent dies, only potentially stopped containers that `docker compose down` (or Docker's own restart policy) handles
- Health checks are declarative in the compose file, not imperative Python polling loops
- All resources (containers, networks, volumes) are scoped to the compose project, making cleanup deterministic
- Reduces `hassette_demo.py` from ~392 lines to potentially ~100 lines (port discovery + stdout contract + compose lifecycle)

**Cons**:
- **Vite HMR degrades in a container.** Filesystem watching over bind mounts on WSL2 (the primary dev machine per CLAUDE.md) is unreliable. This directly undermines the demo stack's stated purpose of live CSS/TSX editing.
- Two new Dockerfiles to create and maintain, with no other consumers (not used by CI, production, or tests)
- Dynamic port discovery via `docker compose port` adds a new failure mode (service healthy but port not yet mapped, or port parsing errors)
- Hassette's relative path config (`examples/hassette.toml` referencing `apps.directory = "examples"`) needs careful volume mount alignment inside the container
- `DEMO_VITE_HOST` remote-browser support becomes more complex -- the Vite container needs to bind to `0.0.0.0` inside the container and map the port externally, and the hassette container's port also needs external exposure for the proxy chain to work
- Source volume mounts for hassette are complex: `src/`, `examples/`, `pyproject.toml`, `uv.lock` all need mounting at the right paths, and `.demo-data/` needs to be a shared volume or host bind mount for persistence

**Effort estimate**: Medium -- new Dockerfiles, compose file extension, networking, volume mount debugging, and HMR testing across platforms.

**Dependencies**: None new. Docker Compose is already a requirement.

### Option B: Keep Vite on host, simplify the orchestrator

**How it works**: Instead of containerizing everything, refactor `hassette_demo.py` to reduce boilerplate while keeping the same architecture (HA in Compose, hassette and Vite as host subprocesses). The refactoring targets three areas:

1. **Extract a `ProcessGroup` abstraction** (~40 lines) that wraps `subprocess.Popen` with `start_new_session=True`, log-file redirection, readiness polling, and SIGTERM/SIGKILL teardown. The three services become three `ProcessGroup` (or `ComposeService`) instances with declarative config, replacing the current spread-out subprocess management.

2. **Consolidate teardown into a single `DemoStack` context manager** that holds all three service handles and cleans up in `__exit__`. Replace the module-level globals (`_ha_compose_file`, `_ha_project_name`, `_hassette_proc`, `_vite_proc`, `_torn_down`) with instance state. Signal handlers delegate to `stack.teardown()`.

3. **Share `_poll_http()` and `find_free_port()` between the demo and system test infrastructure** (`tests/system/conftest.py` has near-identical readiness polling logic). Extract to a shared module under `scripts/` or `src/hassette/test_utils/`.

`capture_screenshots.py` stays largely unchanged -- it already delegates to `hassette_demo.py` and its interaction is through the stdout contract, which doesn't change.

**Pros**:
- Preserves fast Vite HMR -- no container filesystem watching overhead
- No new Dockerfiles to create or maintain
- No Docker networking complexity -- everything stays on localhost
- Dynamic ports work naturally via the existing `find_free_port()`
- `DEMO_VITE_HOST` remote-browser support stays simple (just a `--host` flag to Vite)
- Smaller diff, lower risk -- restructuring existing code rather than replacing the architecture
- Reduces `hassette_demo.py` to ~200-250 lines (estimated) -- cuts in half without changing behavior
- De-duplicates the readiness polling between `hassette_demo.py` and `tests/system/conftest.py`

**Cons**:
- Does not eliminate subprocess management -- just organizes it better
- Orphan risk on unclean shutdown remains (though `DemoStack` context manager + atexit + signal handlers already cover the realistic cases)
- Still ~200+ lines of Python process orchestration, just better structured
- The fundamental complexity of "start three things in order, poll for readiness, tear down in reverse order" is inherent to the problem, not to the solution

**Effort estimate**: Small -- refactoring within existing files, no new infrastructure.

**Dependencies**: None.

## Concerns

### Technical risks

- **Vite HMR in Docker on WSL2.** The primary development machine runs WSL2 (CLAUDE.md, memory notes). Docker bind mounts on WSL2 use 9p/virtio-fs, which has known latency issues with inotify events. Vite's `usePolling` fallback works but adds CPU overhead and delay. This is the single largest risk with Option A -- it could make the demo stack slower for its primary use case (live UI iteration) than the current approach.

- **Port discovery race in Compose.** When using Compose's dynamic port assignment, there is a window between `docker compose up -d` returning and the ports being queryable via `docker compose port`. The current TOCTOU race with `find_free_port()` is narrow (~milliseconds); the Compose port discovery race could be wider if a service is slow to start.

- **HA fixture config copying.** The current script copies `tests/fixtures/demo-ha-config` to a tmpdir with a specific ignore list that must stay in sync with `tests/system/conftest.py`. This logic needs to survive any rewrite. In a full Compose approach, the tmpdir creation and copy would still need to happen before `docker compose up`, so this complexity doesn't go away.

### Complexity risks

- **Two dev Dockerfiles with no other consumers.** Creating dev-specific Dockerfiles just for the demo stack means two more build artifacts to maintain, test, and keep in sync with the production Dockerfile's base images and dependency versions. If the production Dockerfile's Python version or Node version changes, the dev Dockerfiles need to follow.

- **Mixed container/host networking.** If only HA and hassette are containerized (not Vite), Vite on the host needs to proxy to hassette in a container. This requires knowing the mapped host port for hassette's container, and the proxy chain becomes `browser -> Vite (host) -> hassette (container, mapped port) -> HA (container, Docker DNS)`. This is strictly more complex than the current `browser -> Vite (host) -> hassette (host) -> HA (container, mapped port)`.

### Maintenance risks

- **Stdout contract durability.** Three independent consumers rely on the `KEY=value` stdout protocol. Any change to the output format or timing breaks `capture_screenshots.py`, `.mise/tasks/demo-verify`, and agent skill docs. Both options preserve this contract, but it is worth noting that the contract itself is the real interface -- not the implementation behind it.

## Open Questions

- [ ] **How bad is Vite HMR latency in Docker on WSL2?** The claim that bind-mount filesystem watching is unreliable on WSL2 is well-documented generically, but the actual impact on Vite's dev server in this specific setup is unknown. A quick experiment (run `npm run dev` inside a Docker container with the frontend source bind-mounted, edit a CSS file, measure reload time) would settle this empirically. **Unknown-tier:** no direct evidence in the codebase; general WSL2/Docker knowledge from training data.

- [ ] **Is concurrency actually needed?** The dynamic port allocation exists to support concurrent demo runs, but it is unclear how often that actually happens. If the answer is "never in practice," fixed ports would simplify both options. **Unknown-tier:** searched `hassette_demo.py` comments and CLAUDE.md for concurrent-use documentation; found the mechanism but no record of whether concurrent runs actually occur.

- [ ] **Should `capture_screenshots.py` import the demo orchestrator instead of spawning it?** The current two-process architecture (capture spawns demo as a subprocess and communicates via stdout) exists partly because `hassette_demo.py` is stdlib-only (works pre-`uv sync`). If both scripts require `uv` anyway (capture uses `uv run shot-scraper`), the stdlib constraint may be vestigial, and capture could directly call a `DemoStack` Python API. **Inferred:** the stdlib-only design (docstring line 12-13: "uses only stdlib modules so it works before uv sync") appears to be the original motivation for the subprocess architecture, but `capture_screenshots.py` already requires `uv run`, undermining the isolation argument.

- [ ] **What is the actual orphan frequency?** The motivation cites "orphaned containers, leaked resources" as a reliability concern. How often does this actually happen? If it is rare (only on `kill -9` or hard system crash), the current signal-handler-based cleanup may be sufficient and the reliability argument weakens. If it is frequent (e.g., Ctrl-C during startup sometimes fails to clean up), the argument strengthens. **Unknown-tier:** no telemetry or incident records found in the codebase.

## Recommendation

**Option B (refactor, don't rewrite)** is the stronger choice.

The core argument for Docker Compose is "replace subprocess management with `docker compose up/down`." But two of the three services (hassette and Vite) are not natural containers for a dev workflow. Hassette needs source access for live iteration. Vite needs native filesystem watching for fast HMR -- the demo stack's stated purpose per CLAUDE.md. Containerizing them introduces new complexity (dev Dockerfiles, volume mounts, Docker networking, HMR degradation on WSL2) that offsets the subprocess management it removes.

The current script's real problem is not "subprocess management exists" but "subprocess management is spread across ~390 lines of module-level globals and imperative lifecycle code." A `DemoStack` context manager with a `ProcessGroup` abstraction would cut the script roughly in half, eliminate the module-level mutable state, and make each service's lifecycle declarative -- without introducing container-related complexity for services that don't benefit from being containerized.

One area where confidence is lower: if the orphan problem is genuinely frequent (not just a theoretical concern on hard kills), the argument for Compose strengthens because `docker compose down` is more robust than process-group SIGTERM cascades. An empirical check -- "how often do orphaned `hassette-demo-*` containers appear after normal Ctrl-C usage?" -- would inform this. **Inferred:** the presence of reaper systemd services on the dev machine (per CLAUDE.md memory notes) suggests orphaned processes are a real operational concern in this environment, which lends some weight to the compose approach. But the reapers target pytest processes and dev servers, not specifically demo containers.

### Suggested next steps

1. **Decide whether Vite HMR in Docker on WSL2 is acceptable** -- if it is (quick experiment), Option A becomes viable. If not, Option B is the clear winner.
2. **Refactor `hassette_demo.py`** with a `DemoStack` context manager and `ProcessGroup` abstraction (Option B). This is independently valuable regardless of the Compose question -- it makes the code half the size and testable.
3. **Extract shared readiness-polling logic** between `hassette_demo.py` and `tests/system/conftest.py` to eliminate the documented "keep in sync" coupling.
4. **Consider whether `capture_screenshots.py` should import `DemoStack` directly** instead of spawning the orchestrator as a subprocess -- this would eliminate the stdout IPC layer for the screenshot use case while preserving it for mise tasks and agent docs.
