---
task_id: "T04"
title: "Create demo orchestrator script with dynamic ports"
status: "done"
depends_on: ["T01", "T02", "T03"]
implements: ["FR#1", "FR#2", "FR#6", "FR#7", "FR#8", "FR#11", "AC#1", "AC#2", "AC#4"]
---

## Summary
Create the main orchestrator script at `scripts/hassette_demo.py` that allocates three dynamic ports, starts HA + hassette + Vite in sequence, prints machine-parseable URLs when ready, blocks until signaled, and tears down cleanly in reverse order. This is the core of the one-command visual QA environment.

## Prompt
Create `scripts/hassette_demo.py` — a standalone Python script (no external dependencies beyond stdlib + `urllib`). It implements the following 10-step startup sequence:

**Step 1: Resolve repo root.** Use `Path(__file__).resolve().parent.parent` to get the repo root. All subsequent paths are derived from this — no hardcoded absolute paths.

**Step 2: Allocate three free ports.** Write a `find_free_port()` function using `socket.socket(AF_INET, SOCK_STREAM)`, `bind(('', 0))`, `getsockname()[1]`, then close. Call it three times for HA, hassette, and Vite ports.

**Step 3: Copy demo HA fixture to temp directory.** Use `shutil.copytree` with the same ignore patterns as system test conftest.py:
```python
_ignore = shutil.ignore_patterns(
    ".HA_VERSION", "home-assistant.log*", "known_devices.yaml",
    "blueprints", "core.area_registry", "core.device_registry",
    "core.entity_registry", "core.restore_state",
    "homeassistant.exposed_entities", "http", "http.auth",
    "person", "repairs.issue_registry", "trace.saved_traces",
)
```
Source: `{repo_root}/tests/fixtures/demo-ha-config/`. Dest: `tempfile.mkdtemp(prefix="hassette-demo-")`.

**Step 4: Start HA container.** Run `docker compose -f {repo_root}/scripts/docker/ha-demo.yml up -d` with environment variables `HA_PORT={ha_port}` and `HA_CONFIG_PATH={tmp_dir}`. Check for Docker availability first — if `docker compose version` fails, print `DEMO_ERROR=Docker is not running or not installed` and exit 1. Use `subprocess.run` for this step (not Popen) since we wait for it to complete.

**Step 5: Poll HA readiness.** Poll `GET http://localhost:{ha_port}/api/` with `Authorization: Bearer {HA_TOKEN}` header. Timeout: 60 seconds, poll interval: 2 seconds. Require 3 consecutive successful responses (matching the system test pattern). On timeout: print `DEMO_ERROR=HA failed to start within 60s`, tear down, exit 1. The JWT token is the same as in the system test conftest: `eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiIwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMyIsImlhdCI6MTczNTY4OTYwMCwiZXhwIjoyMDUxMDQ5NjAwfQ.q-p85dOe-MMnKQhSNh_LEWnWJGK-GA3xdmqb4LKvkU0`

**Step 6: Start hassette subprocess.** Use `subprocess.Popen` with `os.setsid()` (via `start_new_session=True`):
```
uv run python -m hassette --config-file {repo_root}/examples/hassette.toml
```
Environment variables (added to current env):
- `HASSETTE__BASE_URL=http://localhost:{ha_port}`
- `HASSETTE__TOKEN={HA_TOKEN}`
- `HASSETTE__WEB_API_PORT={hassette_port}`
- `HASSETTE__APP_DIR={repo_root}/examples`
- `HASSETTE__DATA_DIR={repo_root}/.demo-data`

**Step 7: Poll hassette readiness.** Poll `GET http://localhost:{hassette_port}/api/health`. Timeout: 30 seconds, poll interval: 2 seconds. On timeout: print `DEMO_ERROR=Hassette failed to start within 30s`, tear down, exit 1.

**Step 8: Check node_modules.** If `{repo_root}/frontend/node_modules/` does not exist, run `npm ci --prefix {repo_root}/frontend` and wait for completion. This handles the "clean worktree" edge case.

**Step 9: Start Vite dev server.** Use `subprocess.Popen` with `start_new_session=True`:
```
npm run dev --prefix {repo_root}/frontend -- --port {vite_port}
```
Environment variable: `VITE_PROXY_TARGET=http://localhost:{hassette_port}`
Poll `http://localhost:{vite_port}` for up to 15 seconds to confirm Vite started.

**Step 10: Print structured ready message and block.**
```
DEMO_HA_URL=http://localhost:{ha_port}
DEMO_HASSETTE_URL=http://localhost:{hassette_port}
DEMO_FRONTEND_URL=http://localhost:{vite_port}
DEMO_READY=true
```
Then block on `signal.pause()`.

**Teardown:** Register signal handlers for SIGINT and SIGTERM that call a `teardown()` function. Also register `atexit.register(teardown)`. The teardown function:
1. Terminates Vite process group (`os.killpg`) if started
2. Terminates hassette process group if started
3. Runs `docker compose -f ha-demo.yml down` with the same env vars
4. Removes the temp directory via `shutil.rmtree`
5. Each step is guarded — if a process wasn't started yet, skip it

The teardown function must be idempotent (safe to call multiple times) since both signal handler and atexit may fire.

**Add `.demo-data/` to `.gitignore`.**

## Focus
- `start_new_session=True` on Popen creates a new process group, allowing `os.killpg(proc.pid, signal.SIGTERM)` to kill the process and all its children.
- The hassette subprocess runs via `uv run` which itself spawns a child Python process — the process group kill handles this.
- `signal.pause()` blocks until a signal is received. On Linux/WSL this is the cleanest way to wait indefinitely.
- The `find_free_port()` approach has a TOCTOU window between closing the socket and the service binding. For this use case, the window is tiny and acceptable — the design doc notes this explicitly.
- All `subprocess.run` and `Popen` calls should use `cwd=repo_root` to ensure paths resolve correctly.
- The orchestrator imports only stdlib modules — no hassette imports, no third-party deps. This is critical so it works before `uv sync` runs.

## Verify
- [ ] FR#1: Running `uv run python scripts/hassette_demo.py` with no arguments starts all three services
- [ ] FR#2: The script allocates three distinct free ports via `socket.bind(('', 0))` and passes them to each service
- [ ] FR#6: The script prints `DEMO_HA_URL=`, `DEMO_HASSETTE_URL=`, `DEMO_FRONTEND_URL=`, and `DEMO_READY=true` lines to stdout after all services are ready
- [ ] FR#7: On SIGTERM or SIGINT, the script terminates Vite, then hassette, then runs `docker compose down`, then removes the temp directory
- [ ] FR#8: All file paths in the script are derived from `Path(__file__).resolve().parent.parent` — no hardcoded absolute paths
- [ ] FR#11: The HA container name includes the port number for uniqueness, and all three services use dynamically allocated ports
- [ ] AC#1: After the script prints `DEMO_READY=true`, all three URLs respond (HA returns 200 with auth header, hassette /api/health returns 200, Vite returns HTML)
- [ ] AC#2: Starting the script twice from different directories results in two independent sets of services on different ports
- [ ] AC#4: After sending SIGTERM to the script, `docker ps` shows no container with name matching `hassette-demo-ha-*`, and the hassette and Vite processes are no longer running
