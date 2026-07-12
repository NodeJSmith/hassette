---
task_id: "T02"
title: "Create DemoStack context manager in scripts/demo_stack.py"
status: "done"
depends_on: ["T01"]
implements: ["FR#2", "FR#5"]
---

## Summary

Create the shared `DemoStack` context manager that handles the compose lifecycle: HA fixture config copy, compose up/down, signal handling, and cleanup. This module is imported by both `hassette_demo.py` and `capture_screenshots.py`, eliminating duplicated subprocess management.

## Target Files

- create: `scripts/demo_stack.py`
- read: `scripts/hassette_demo.py` (current fixture copy logic, lines 208-227)
- read: `tests/system/conftest.py` (fixture ignore list to keep in sync)
- read: `scripts/docker/ha-demo.yml` (compose file path)

## Prompt

Create `scripts/demo_stack.py` (~80 lines) with a `DemoStack` class that implements the context manager protocol (`__enter__`/`__exit__`).

**Constructor** accepts optional port overrides via env vars:
- `DEMO_HA_PORT` (default 18123)
- `DEMO_HASSETTE_PORT` (default 18126)
- `DEMO_VITE_PORT` (default 15173)

Expose ports as properties: `ha_port`, `hassette_port`, `vite_port`.

**`__enter__`**:
1. Check Docker availability: `subprocess.run(["docker", "compose", "version"], capture_output=True)` — raise a clear error if not running.
2. Copy HA fixture config from `tests/fixtures/demo-ha-config` to a `tempfile.mkdtemp()`. Use the same `shutil.copytree` with `shutil.ignore_patterns` as the current `hassette_demo.py` lines 210-227. Add a comment cross-referencing `tests/system/conftest.py` for the ignore list.
3. Build the compose env dict: `HA_CONFIG_PATH` (tmpdir), `DEMO_HA_PORT`, `DEMO_HASSETTE_PORT`, `DEMO_VITE_PORT`, plus `os.environ`.
4. Run `docker compose -f <compose_file> -p hassette-demo up -d --wait` with the env dict. If it fails, clean up the tmpdir and re-raise.
5. Return `self`.

**`__exit__`**:
1. Run `docker compose -f <compose_file> -p hassette-demo down --remove-orphans` with a timeout (30s).
2. Clean up the tmpdir via `shutil.rmtree(ignore_errors=True)`.
3. Make idempotent (track `_torn_down` flag).

**Signal handling**: Register `atexit` and SIGINT/SIGTERM handlers in `__enter__` that call the teardown. The signal handler should call teardown then `sys.exit(0)`.

**Resolve paths**: Derive `repo_root` from `Path(__file__).resolve().parent.parent`. The compose file is at `repo_root / "scripts" / "docker" / "ha-demo.yml"`.

## Focus

- The current fixture ignore list (hassette_demo.py lines 210-227): `.HA_VERSION`, `home-assistant.log*`, `known_devices.yaml`, `blueprints`, `core.area_registry`, `core.device_registry`, `core.entity_registry`, `core.restore_state`, `homeassistant.exposed_entities`, `http`, `http.auth`, `person`, `repairs.issue_registry`, `trace.saved_traces`. Cross-reference `tests/system/conftest.py` to confirm the lists match.
- The compose project name must be `hassette-demo` (fixed). Pass `-p hassette-demo` on every compose command.
- `--remove-orphans` on compose down handles stale containers from prior runs.
- `__exit__` must suppress exceptions during teardown (use `contextlib.suppress`) — don't let cleanup failures mask the original error.
- No Windows platform check needed — all target machines run WSL2/Linux. Drop the `sys.platform == "win32"` guard from the old script.

## Verify

- [ ] FR#2: After `DemoStack.__exit__`, `docker ps --filter "label=com.docker.compose.project=hassette-demo"` returns no containers
- [ ] FR#5: HA fixture config is copied to a fresh tmpdir on each start (verify tmpdir path exists during `__enter__`, is cleaned up after `__exit__`)
