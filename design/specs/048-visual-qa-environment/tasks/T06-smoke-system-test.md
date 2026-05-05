---
task_id: "T06"
title: "Add smoke system test for demo environment"
status: "planned"
depends_on: ["T04"]
implements: ["FR#9", "AC#3", "AC#5"]
---

## Summary
Create a system test that starts the demo environment, waits for readiness, queries the hassette API to confirm all 7 app instances are running, and tears down. This validates the full stack end-to-end in CI. The test uses the `system` marker so it runs as part of `nox -s system`.

## Prompt
Create `tests/system/test_demo_smoke.py`:

1. **Import the orchestrator logic.** The test needs to start the demo environment the same way the orchestrator script does. Import or subprocess-invoke `scripts/hassette_demo.py`. The simplest approach: run the orchestrator as a subprocess, capture its stdout, parse the `DEMO_*` env-style lines to get URLs, then hit the hassette API.

2. **Test structure:**
   ```python
   @pytest.mark.system
   class TestDemoSmoke:
       def test_all_apps_running(self):
           """Start demo env, verify all 7 app instances reach RUNNING."""
   ```

3. **Test implementation:**
   - Start `uv run python scripts/hassette_demo.py` as a `subprocess.Popen` with `stdout=PIPE`
   - Read stdout lines until `DEMO_READY=true` is found (timeout: 120 seconds total — 60s HA + 30s hassette + 15s Vite + buffer)
   - Extract `DEMO_HASSETTE_URL` from the output
   - `GET {hassette_url}/api/apps` and parse the response
   - Assert the response contains exactly 7 app entries
   - Assert all 7 have `status == "RUNNING"` (or the equivalent status field — check the `AppStatusResponse` model)
   - Send `SIGTERM` to the subprocess in a `finally` block and wait for exit

4. **Mark with `pytest.mark.system`** so it runs as part of `nox -s system` (non-destructive tier). The existing system session runs `pytest -m "system and not system_destructive"` which will pick this up.

## Focus
- The `GET /api/apps` endpoint is at `src/hassette/web/routes/apps.py` and returns an `AppStatusResponse`. Check the response model to know the exact field names for app status.
- The 7 expected instances are: motion_lights/backyard_kitchen, motion_lights/backyard_ceiling, climate_controller, cover_scheduler, presence_tracker/paulus, presence_tracker/home_boy, security_monitor.
- The test must be tolerant of startup timing — apps may take a few seconds after `DEMO_READY=true` to fully initialize. Add a brief polling loop for the apps endpoint if needed (poll until all 7 are RUNNING, timeout 30s).
- Use `subprocess.Popen` with `start_new_session=True` so `os.killpg` can cleanly terminate the orchestrator and its children in the finally block.
- The test should clean up even if assertions fail — use try/finally, not just teardown.
- Check `pyproject.toml` for existing pytest markers — `system` is already registered.

## Verify
- [ ] FR#9: `tests/system/test_demo_smoke.py` exists, is marked with `pytest.mark.system`, starts the demo environment, and asserts all 7 app instances reach RUNNING status
- [ ] AC#3: The test queries `GET /api/apps` and verifies the response includes active app instances with listeners, scheduled jobs, and event/invocation activity (note: this validates the API data backing the dashboard; visual rendering is validated manually)
- [ ] AC#5: The test can be run via `uv run nox -s system` and passes when Docker is available
