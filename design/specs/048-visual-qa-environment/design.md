# Design: One-Command Visual QA Environment

**Date:** 2026-05-05
**Status:** archived
**Scope-mode:** hold
**Research:** design/research/2026-05-05-example-apps-demo-env/research.md

## Problem

Testing UI changes against a live automation backend requires manually assembling multiple disconnected services: the external automation platform, the framework backend, and the frontend dev server. Each piece has its own startup sequence, configuration, and port assumptions. Getting them wired together correctly is error-prone, and when the wrong backend is used (e.g., a production instance instead of an isolated test instance), debugging time is wasted on phantom issues that don't actually exist.

The current workaround — reusing a live production instance — interrupts real automation workflows every time a test run happens. There is no isolated, reproducible environment purpose-built for visual QA and UI development.

Additionally, the project's example apps live in a separate repository that has drifted from the framework's current API. Keeping examples separate creates a synchronization burden and means CI cannot validate that examples work against the current framework version.

## Goals

- A single command starts an isolated, fully-wired environment with real data flowing through the system (binary: it starts or it doesn't)
- No manual configuration, onboarding, or token generation required (binary: zero interactive steps)
- Multiple instances can run simultaneously from different working directories without port conflicts (binary: two instances coexist or they don't)
- The environment outputs machine-parseable `KEY=value` lines that a programmatic consumer can extract without parsing prose (binary: lines parse or they don't)
- All 5 demo apps (7 instances) load successfully and reach running state, exercising the framework's core feature surface
- Example apps are co-located in the main repository and validated by CI
- A smoke test verifies the full stack starts and all app instances reach running state

## User Scenarios

### Developer Agent: AI coding assistant
- **Goal:** Validate UI changes against a live backend with real automation data
- **Context:** Working in a feature branch worktree, needs visual QA before committing

#### Start demo environment for visual QA

1. **Start the demo environment**
   - Sees: A command to run that requires no arguments or configuration
   - Decides: N/A — the command is deterministic
   - Then: Services start sequentially; machine-parseable output reports allocated ports and readiness

2. **Wait for readiness**
   - Sees: Structured output indicating each service's status and the final URLs
   - Decides: N/A — proceeds when all services report ready
   - Then: The environment is stable and accepting requests

3. **Perform visual QA**
   - Sees: Dashboard at the reported URL showing running apps, listeners, scheduled jobs, and event activity
   - Decides: Which pages to screenshot, what to verify
   - Then: Screenshots captured via browser automation

4. **Tear down**
   - Sees: N/A — sends termination signal to the foreground process
   - Decides: N/A
   - Then: All services stop cleanly, containers are removed, no orphaned processes

### Developer: Framework maintainer
- **Goal:** Manually inspect the UI during development
- **Context:** Working on frontend changes, wants live preview with real data

#### Manual UI development session

1. **Start the demo environment**
   - Sees: URLs printed to terminal
   - Decides: N/A
   - Then: Opens browser to the frontend URL

2. **Develop with hot reload**
   - Sees: Frontend updates automatically on file save; backend serves real automation data
   - Decides: What to change in the frontend code
   - Then: Changes appear immediately in the browser

3. **Stop when done**
   - Sees: N/A — presses Ctrl+C in the terminal
   - Decides: N/A
   - Then: All services stop cleanly

## Functional Requirements

- **FR#1** A single command starts all required services without arguments or manual configuration
- **FR#2** Each service instance allocates its own ports dynamically, avoiding conflicts with other instances or existing services on the host
- **FR#3** The environment uses pre-configured credentials and bypass mechanisms so no interactive setup steps are needed
- **FR#4** The environment loads automation apps that exercise a broad range of framework features (event handling, scheduling, state management, service interception, synchronous and asynchronous patterns)
- **FR#5** The frontend dev server proxies API and WebSocket traffic to the backend at the dynamically allocated port
- **FR#6** The command blocks in the foreground and outputs structured, machine-parseable status messages including allocated URLs when all services are ready
- **FR#7** On termination signal, all services shut down cleanly in reverse startup order with no orphaned processes or containers
- **FR#8** The environment works correctly when invoked from any working directory or worktree of the repository
- **FR#9** A smoke test validates that the full stack starts successfully and all automation app instances reach a running state
- **FR#10** Example apps are co-located in the main repository and replace the existing legacy example apps
- **FR#11** The environment can run simultaneously with other instances started from different worktrees

## Edge Cases

- Readiness polling timeouts: HA readiness polls for up to 60 seconds, hassette for up to 30 seconds, Vite for up to 15 seconds. On timeout, the orchestrator reports which service failed and tears down any services that did start
- Port allocation race: two instances starting simultaneously could both claim the same port before either binds — mitigated by binding immediately after allocation
- Docker not running: the command should fail fast with a clear error rather than hanging on a readiness poll
- HA container startup failure (image pull fails, config invalid): detect non-zero exit or unhealthy status and report before attempting to start dependent services
- Frontend `node_modules` not installed in worktree: detect and either auto-install or fail with a clear message
- Termination during startup (before all services are running): must still clean up any services that did start
- Stale container from a previous crashed run: detect and remove or error clearly

## Acceptance Criteria

- **AC#1** Running the single command from a clean worktree (including worktrees at non-standard paths) results in all three services running and a dashboard visible at the reported frontend URL (validates FR#1, FR#3, FR#6, FR#8)
- **AC#2** Two simultaneous instances started from different worktrees both run without port conflicts (validates FR#2, FR#11)
- **AC#3** The dashboard shows active automation app instances with listeners, scheduled jobs, and event activity (validates FR#4)
- **AC#4** Sending SIGTERM or pressing Ctrl+C results in all processes exiting and no containers remaining in `docker ps` (validates FR#7)
- **AC#5** The smoke system test passes in CI, confirming all app instances reach running state (validates FR#9)
- **AC#6** The legacy `examples/apps/` directory is removed and replaced by the consolidated example apps (validates FR#10)
- **AC#7** Frontend hot reload works — saving a frontend source file updates the browser without restarting the environment (validates FR#5)

## Key Constraints

No feature-specific constraints identified during discovery beyond those already captured in the project's general conventions.

## Dependencies and Assumptions

- Docker must be available on the host (required for the automation platform container)
- Node.js and npm must be available (required for the frontend dev server)
- The `hassette-examples` repository at `/home/jessica/source/hassette-examples/` is the source for the demo apps being brought in-repo
- The pre-seeded JWT token and onboarding bypass from the system test fixtures are reusable for the demo environment
- The framework's config system supports environment variable overrides for all relevant settings (confirmed: `HASSETTE__BASE_URL`, `HASSETTE__TOKEN`, `HASSETTE__APP_DIR`, `HASSETTE__WEB_API_PORT`)

## Architecture

### Bringing examples in-repo

Remove the existing `examples/apps/` directory (7 older apps) and its config. Copy the 5 demo apps from `hassette-examples/src/hassette_examples/` into `examples/`. Bring the `hassette.toml` app registry (7 instances across 5 apps) adapted for the new location. These apps import directly from `hassette` — no separate package needed since the nox session runs via `uv run` against the local project.

The existing `examples/docker-compose.yml` is also removed — the demo orchestrator replaces its purpose.

### Demo HA fixture

Create `tests/fixtures/demo-ha-config/` by copying the system test's `tests/fixtures/ha-config/` and modifying `configuration.yaml` to include the `demo:` integration. This provides synthetic entities (lights, sensors, device trackers, covers, climate, locks, binary sensors) that the demo apps are designed to interact with. The pre-seeded JWT, onboarding bypass, and auth storage files are reused unchanged.

A separate docker-compose file at `scripts/docker/ha-demo.yml` defines the HA container for the demo environment. It uses environment variable substitution for the host port (`${HA_PORT}:8123`) and config path (`${HA_CONFIG_PATH}:/config`). The container name includes a unique suffix to avoid collisions (e.g., derived from the allocated port or a random ID).

### Dynamic port allocation

The orchestrator script allocates three free ports at startup using `socket.bind(('', 0))`. To avoid TOCTOU races, ports are bound immediately and released just before the service that needs them starts. The three ports are:

1. **HA port** — passed to docker-compose via `HA_PORT` env var
2. **Hassette backend port** — passed via `HASSETTE__WEB_API_PORT` env var
3. **Vite dev server port** — passed via `--port` CLI flag

### Vite proxy override

`frontend/vite.config.ts` currently hardcodes the proxy target to `http://localhost:8126`. Add support for reading from `process.env.VITE_PROXY_TARGET` with the existing value as the default. This is a backward-compatible change — existing development workflows are unaffected.

### Orchestrator script

A Python script at `scripts/hassette_demo.py` is the main entry point. Startup sequence:

1. Resolve repo root from the script's own path (works from any worktree)
2. Allocate three free ports
3. Copy demo HA fixture to a temp directory (same pattern as system test conftest: `shutil.copytree` with ignore patterns for runtime artifacts)
4. Start HA container via `docker compose up -d` with the demo compose file, passing `HA_PORT` and `HA_CONFIG_PATH` as env vars
5. Poll HA readiness (REST API + JWT auth check, similar to system test's `wait_for_ha_ready`)
6. Start hassette subprocess via `uv run python -m hassette --config-file examples/hassette.toml` with env var overrides for `HASSETTE__BASE_URL`, `HASSETTE__TOKEN`, `HASSETTE__WEB_API_PORT`, `HASSETTE__APP_DIR`, `HASSETTE__DATA_DIR`
7. Poll hassette readiness (`GET /api/health`)
8. Start Vite dev server via `npm run dev --prefix frontend -- --port {vite_port}` with `VITE_PROXY_TARGET` env var
9. Print structured ready message with all three URLs
10. Block on `signal.pause()`

Teardown on SIGINT/SIGTERM: terminate Vite → terminate hassette → `docker compose down` → remove temp directory. Each subprocess is started with `os.setsid()` so the process group can be killed cleanly. An `atexit` handler covers normal Python exit.

Structured output format for machine parsing:
```
DEMO_HA_URL=http://localhost:{ha_port}
DEMO_HASSETTE_URL=http://localhost:{hassette_port}
DEMO_FRONTEND_URL=http://localhost:{vite_port}
DEMO_READY=true
```

### Nox session and mise task

A `python=False` nox session named `demo` wraps the orchestrator script, following the established pattern from the `frontend` and `dev` sessions. A corresponding mise task provides `mise run demo` as an alias.

### Smoke system test

A new test file in `tests/system/` that:
1. Starts the demo environment using the same orchestrator logic (or by invoking the script as a subprocess)
2. Waits for the `DEMO_READY=true` signal
3. Queries `GET /api/apps` on the hassette backend and asserts all 7 app instances have status `RUNNING`
4. Tears down the environment

This test runs as part of `nox -s system` with a dedicated marker so it can be run in isolation.

### .gitignore

Add `.demo-data/` to the root `.gitignore` — this is the data directory used by the hassette demo process.

## Alternatives Considered

### Extract a reusable `HaLauncher` class

Refactoring the system test's HA Docker lifecycle into a shared `HaLauncher` class would eliminate duplication between the demo orchestrator and system test conftest. Rejected for this PR because it increases blast radius — refactoring the system test fixture introduces regression risk for no immediate benefit. The duplication is small (copy fixture to tmpdir, compose up, poll, compose down) and can be extracted later if a third consumer appears.

### Daemonize instead of foreground blocking

The orchestrator could daemonize (fork to background, write a PID file, return immediately). This would avoid tying up a terminal or background process. Rejected because it adds complexity (PID tracking, stale PID detection, a separate `stop` command) without clear benefit — the foreground model works well for both Claude (run in background, capture output) and humans (Ctrl+C to stop).

### Use fixed ports with configurable overrides

Instead of dynamic allocation, use fixed default ports (e.g., 28123, 28126, 25173) with CLI flags to override. Simpler to implement but doesn't solve the multi-worktree simultaneous use case. Rejected because dynamic ports are the whole point — the user explicitly needs multiple concurrent instances.

## Test Strategy

- **Smoke system test** (new): Validates the full stack starts and all 7 app instances reach RUNNING status. Runs as part of `nox -s system`.
- **Existing system tests**: Must continue to pass unchanged — the demo environment uses separate fixtures, container names, and ports.
- **Existing e2e tests**: Unaffected — they use their own mock data, not the demo environment.
- **Manual verification**: Start the demo, confirm dashboard shows live data, Ctrl+C tears down cleanly. Verify two simultaneous instances from different worktrees don't conflict.

## Documentation Updates

- `examples/README.md` — New file describing the demo apps, what patterns they demonstrate, and how to run the demo environment
- Nox session docstring — Clear one-line description of what `nox -s demo` does

## Impact

**Files added:**
- `examples/` — 5 app files + `__init__.py` + `hassette.toml` (replacing existing `examples/apps/`)
- `scripts/hassette_demo.py` — orchestrator
- `scripts/docker/ha-demo.yml` — demo docker-compose
- `tests/fixtures/demo-ha-config/` — HA fixture with demo integration
- `tests/system/test_demo_smoke.py` — smoke test
- `examples/README.md`

**Files modified:**
- `frontend/vite.config.ts` — env var for proxy target
- `noxfile.py` — `demo` session
- `mise.toml` — `demo` task
- `.gitignore` — `.demo-data/`

**Files removed:**
- `examples/apps/` — 7 legacy example app files
- `examples/config/` — legacy example config
- `examples/docker-compose.yml` — legacy example compose

<!-- Gap check 2026-05-05: 1 gap included — README.md:53-59 (links to removed examples/apps/) → T01 Focus item 4 -->

**Blast radius:** Low. No changes to framework source code, system test conftest, or existing test suites. The `vite.config.ts` change is backward-compatible (env var with existing value as default).

## Open Questions

None — all decisions resolved during discovery.
