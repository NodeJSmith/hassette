---
task_id: "T04"
title: "Rewrite capture_screenshots.py to use DemoStack directly"
status: "planned"
depends_on: ["T02"]
implements: ["FR#9", "AC#3"]
---

## Summary

Rewrite `scripts/capture_screenshots.py` to import `DemoStack` directly instead of spawning `hassette_demo.py` as a child process and parsing its stdout. This eliminates the threaded line reader, stdout queue, subprocess teardown, and the `PROC_WAIT_TIMEOUT_SECONDS` that caused #1158. The shot-scraper integration and screenshot manifest handling stay unchanged.

## Target Files

- modify: `scripts/capture_screenshots.py`
- read: `scripts/demo_stack.py` (DemoStack API)
- read: `docs/screenshots.yml` (manifest format — unchanged)

## Prompt

Rewrite `scripts/capture_screenshots.py`. The new script (~120 lines) should:

1. **Parse args** — keep the existing `--only` argument for filtering manifest entries.

2. **Enter DemoStack context** — `with DemoStack() as demo:` replaces the subprocess spawn, stdout reader thread, line queue, and `DEMO_READY` polling.

3. **Clean stale demo DB** — preserve the existing logic (lines 133-141) that deletes `.demo-data/hassette.db`, `-shm`, and `-wal` before starting. Do this before entering the DemoStack context.

4. **Wait for demo_stimulator error data** — preserve the existing polling logic (lines 230-256) that polls `http://localhost:{demo.hassette_port}/api/telemetry/app/demo_stimulator/jobs` until a job with `failed > 0` appears. Use the fixed hassette port from `demo.hassette_port`. Keep the 90s timeout and 2s poll interval. Keep the soft warning (not a hard failure) if timeout elapses.

5. **Resolve manifest** — preserve the existing logic (lines 258-279) that reads `docs/screenshots.yml`, filters by `--only`, replaces `{port}` with the vite port (`str(demo.vite_port)`), and prepends animation-disabling JS.

6. **Run shot-scraper** — preserve the existing `subprocess.run(["uv", "run", "shot-scraper", "multi", _tmp_manifest])` call.

7. **Exit** — the `with` block exits, DemoStack tears down via compose. Exit with shot-scraper's return code.

**Remove all of the following:**
- Module-level globals: `_demo_proc`, `_tmp_manifest`, `_torn_down`
- The `teardown()` function and `_signal_handler()`
- The `atexit.register(teardown)` and signal registrations
- The subprocess spawn of `hassette_demo.py` (lines 144-151)
- The threaded `reader()` function and `line_queue` (lines 162-168)
- The `DEMO_READY` polling loop (lines 170-215)
- `DEMO_READY_TIMEOUT_SECONDS`, `PROC_WAIT_TIMEOUT_SECONDS` constants
- The `demo_output` dict and URL/port extraction (lines 217-228)

**Keep:**
- `ANIMATION_DISABLE_JS` constant
- `ERROR_DATA_TIMEOUT_SECONDS`, `ERROR_DATA_POLL_INTERVAL_SECONDS`, `HTTP_SOCKET_TIMEOUT_SECONDS` constants
- The `--only` argument parsing
- The manifest resolution logic (read YAML, filter, replace port, inject JS)
- The temp manifest file handling (write resolved manifest, clean up)
- The shot-scraper subprocess call

## Focus

- The import `from demo_stack import DemoStack` works because `scripts/` is the CWD — same as T03.
- The `{port}` placeholder in `docs/screenshots.yml` entries is replaced with `str(demo.vite_port)`, which defaults to `15173`.
- The temp manifest file (`_tmp_manifest`) cleanup should use a `try/finally` or `atexit` — DemoStack handles compose cleanup, but the temp YAML file is this script's responsibility.
- The error data polling uses `urllib.request` (stdlib) — no change needed.
- `repo_root` derivation stays the same: `Path(__file__).resolve().parent.parent`.

## Verify

- [ ] FR#9: `capture_screenshots.py` starts and stops the demo stack by importing DemoStack directly — no `hassette_demo.py` subprocess is spawned
- [ ] AC#3: `uv run python scripts/capture_screenshots.py` produces the same screenshot files as the current script for the same manifest and demo state
