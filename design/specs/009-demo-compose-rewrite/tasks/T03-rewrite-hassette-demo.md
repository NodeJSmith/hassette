---
task_id: "T03"
title: "Rewrite hassette_demo.py as thin DemoStack wrapper"
status: "done"
depends_on: ["T02"]
implements: ["FR#10", "AC#1", "AC#2", "AC#4", "AC#5", "AC#6"]
---

## Summary

Rewrite `scripts/hassette_demo.py` from ~392 lines to ~30 lines. The script imports `DemoStack`, enters the context manager, prints human-readable URLs, and blocks with `signal.pause()`. All subprocess management, readiness polling, and teardown code is removed.

## Target Files

- modify: `scripts/hassette_demo.py`
- read: `scripts/demo_stack.py` (DemoStack API)

## Prompt

Rewrite `scripts/hassette_demo.py` completely. The new script should be approximately 30 lines:

```python
#!/usr/bin/env python3
"""Demo orchestrator: starts HA + hassette + Vite for visual QA.

Usage:
    uv run python scripts/hassette_demo.py

Starts all services via Docker Compose, prints URLs when ready, and blocks
until signaled. On SIGINT or SIGTERM, tears down via docker compose down.

Requires Docker. Ports default to 18123 (HA), 18126 (hassette), 15173 (vite)
and are overridable via DEMO_HA_PORT, DEMO_HASSETTE_PORT, DEMO_VITE_PORT.
"""

import signal

from demo_stack import DemoStack


def main() -> None:
    with DemoStack() as demo:
        print(f"HA:       http://localhost:{demo.ha_port}", flush=True)
        print(f"Hassette: http://localhost:{demo.hassette_port}", flush=True)
        print(f"Frontend: http://localhost:{demo.vite_port}", flush=True)
        print("Demo ready.", flush=True)
        signal.pause()


if __name__ == "__main__":
    main()
```

The output is human-readable — no `KEY=value` protocol. Consumers (demo-verify, agent skills) use fixed-port URLs directly (updated in T05), not stdout parsing.

Remove all of the following from the old script:
- The `sys.platform == "win32"` check (not needed — all machines are WSL2/Linux)
- `find_free_port()`, `_poll_http()`, `_terminate_process_group()`
- All module-level globals (`_ha_compose_file`, `_ha_project_name`, `_ha_env`, `_hassette_proc`, `_vite_proc`, `_hassette_log_fh`, `_vite_log_fh`, `_tmp_dir`, `_torn_down`)
- The `teardown()` function and `_signal_handler()`
- Steps 2-9 in `main()` (port allocation, fixture copy, Docker start, subprocess starts, readiness polling, npm ci)
- The `atexit.register(teardown)` and signal registrations (DemoStack handles these)
- Constants: `HTTP_SOCKET_TIMEOUT_SECONDS`, `PROC_WAIT_TIMEOUT_SECONDS`, `HA_STARTUP_TIMEOUT_SECONDS`, `HASSETTE_STARTUP_TIMEOUT_SECONDS`, `VITE_STARTUP_TIMEOUT_SECONDS`, `DEFAULT_POLL_INTERVAL_SECONDS`, `AUTH_FAILURE_CODES`, `TRANSIENT_ERROR_CODES`
- `HA_TOKEN` (moved to compose file environment)
- `DEMO_VITE_HOST` support (replaced by compose port mapping + SSH tunnel)

## Focus

- The import `from demo_stack import DemoStack` works because `scripts/` is the CWD when running `uv run python scripts/hassette_demo.py` — Python adds the script's directory to `sys.path`.
- `signal.pause()` is Unix-only, but all target machines run WSL2/Linux — no platform check needed.
- DemoStack's `__exit__` handles compose down, so the `with` block needs no explicit cleanup.

## Verify

- [ ] FR#10: Running `uv run python scripts/hassette_demo.py` prints human-readable URLs after startup, blocks until Ctrl-C, then tears down
- [ ] AC#1: All three services start and URLs are printed within 120s
- [ ] AC#2: Ctrl-C during any phase leaves no orphaned containers (`docker ps` shows none with `hassette-demo` project)
- [ ] AC#4: Editing a `.tsx` file while the demo runs triggers HMR reload without a full page refresh
- [ ] AC#5: All three demo ports are reachable via SSH tunnel from another machine
- [ ] AC#6: `DEMO_HA_PORT=29123 DEMO_HASSETTE_PORT=29126 DEMO_VITE_PORT=29173 uv run python scripts/hassette_demo.py` starts on overridden ports
