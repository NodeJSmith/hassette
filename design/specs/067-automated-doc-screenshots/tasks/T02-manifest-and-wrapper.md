---
task_id: "T02"
title: "Create YAML manifest and wrapper capture script"
status: "done"
depends_on: ["T01"]
implements: ["FR#1", "FR#2", "FR#3", "FR#5", "FR#6", "FR#7", "AC#1", "AC#2", "AC#4", "AC#5"]
---

## Summary
Create the YAML screenshot manifest and the wrapper script that orchestrates the full capture flow. The manifest defines all 16 screenshots with URL paths, output files, viewport dimensions, selectors, and pre-capture JavaScript. The wrapper starts the demo environment, waits for readiness and error data, resolves port placeholders, injects animation-disabling CSS into each entry, runs shot-scraper, and tears down.

This is the core deliverable — after this task, `uv run python scripts/capture_screenshots.py` produces all 16 doc screenshots.

## Prompt
Create two new files:

### 1. `docs/screenshots.yml` — YAML manifest

Define all 16 screenshot entries per the inventory in the design doc's "Screenshot inventory mapped to manifest entries" section. Each entry has these shot-scraper fields:
- `url`: URL path with `{port}` placeholder (e.g., `http://localhost:{port}/apps`)
- `output`: output file path relative to repo root (e.g., `docs/_static/web_ui_apps.png`)
- `width`: viewport width (1400 for all entries)
- `height`: viewport height (varies — see design doc inventory for tall pages like config at 1656, overview at 1508)
- `selector`: CSS selector for element-level crops (omit for full-page)
- `javascript`: pre-capture JS when needed (command palette keyboard dispatch, column picker click, log row click, handler error row selection)
- `wait`: milliseconds to wait after page load (2000 default)
- `wait_for`: CSS selector to wait for before capture (command palette needs this)

Include a header comment block explaining the manifest format, the `{port}` placeholder convention, and how to add a new screenshot.

**Full-page entries (8):** `/apps`, `/handlers`, `/logs`, `/config`, `/apps/motion_lights/overview`, `/apps/motion_lights/handlers`, `/apps/motion_lights/code`, `/apps/motion_lights/config`. Use `height: 900` for standard pages; `height: 1656` for config; `height: 1508` for overview.

**Element-level entries (8):** Each entry's exact selector, URL, and pre-capture JS:
- Sidebar: selector `[data-testid='sidebar']` on `/apps` — no JS needed
- Status bar: selector `[data-testid='status-bar']` on `/apps` — no JS needed
- Command palette: selector `[data-testid='cmd-palette']` on `/apps` — JS: `document.dispatchEvent(new KeyboardEvent('keydown', {key: 'k', ctrlKey: true, bubbles: true}))` plus `wait_for: "[data-testid='cmd-palette']"`
- Column picker popover: selector `[data-testid='column-picker-popover']` on `/logs` — JS: `document.querySelector('[data-testid="column-picker"]')?.click()` plus `wait_for: "[data-testid='column-picker-popover']"`
- Error spotlight: selector `[data-testid='overview-error-spotlight']` on `/apps/demo_stimulator/overview` — no JS needed
- Handler error row: selector `[data-screenshot-target='true']` on `/apps/demo_stimulator/handlers` — JS: `const row = document.querySelector('[data-testid="handler-failed-count"]')?.closest('[data-testid^="unified-row-"]'); if (row) { row.dataset.screenshotTarget = 'true'; row.scrollIntoView(); }`
- Instance switcher: selector `[data-testid='instance-switcher']` on `/apps/motion_lights/overview` — no JS needed
- Log drawer: selector `[data-testid='log-detail-drawer']` on `/logs` — JS: `document.querySelector('tbody tr')?.click()` plus `wait_for: "[data-testid='log-detail-drawer']"`

### 2. `scripts/capture_screenshots.py` — wrapper script

Follow the orchestration pattern from `scripts/hassette_demo.py` (see context.md Convention Examples). The script:

1. Register `atexit` + `SIGINT`/`SIGTERM` handlers immediately. Derive repo root from `Path(__file__).resolve().parent.parent`.
2. Parse `docs/screenshots.yml` with `yaml.safe_load()` (PyYAML is a transitive dependency of shot-scraper).
3. Delete `.demo-data/hassette.db` if it exists.
4. Start `scripts/hassette_demo.py` as a subprocess with `stdout=PIPE`, `start_new_session=True`. Store the process for cleanup.
5. Read stdout line by line. Parse `KEY=value` lines. Extract `DEMO_FRONTEND_URL` and watch for `DEMO_READY=true`. Enforce a **180-second wall-clock deadline** — if exceeded, kill the demo process, print a diagnostic message listing things to check (Docker running? Port conflicts? Check demo logs), and exit 1. Also watch for `DEMO_ERROR=` lines and exit immediately if seen.
6. Extract the port from `DEMO_FRONTEND_URL` (e.g., `http://localhost:54321` → `54321`). Also extract `DEMO_HASSETTE_URL` for API polling.
7. Poll `GET {DEMO_HASSETTE_URL}/api/telemetry/app/demo_stimulator/jobs` until the response JSON contains at least one job with `failed > 0` (the `sensor_health_check` job). Use a **90-second timeout** with 2-second poll interval. `urllib.request` is fine (script is stdlib-only except for yaml). The `/api/telemetry/app/{app_key}/jobs` endpoint returns `list[JobSummary]` which includes a `failed: int` field per job.
8. For each manifest entry: replace `{port}` in the `url` field. Prepend animation-disabling CSS injection to the `javascript` field:
   ```javascript
   const s=document.createElement('style');s.textContent='*,*::before,*::after{animation-duration:0s!important;transition-duration:0s!important;}';document.head.appendChild(s);
   ```
   If the entry already has a `javascript` field, append the existing JS after the injection (separated by semicolons).
9. Write the resolved manifest to a temp file (`tempfile.NamedTemporaryFile` with `.yml` suffix, `delete=False`).
10. Run `shot-scraper multi <temp-file>` as a subprocess. Capture its exit code.
11. Clean up: delete the temp manifest, send SIGTERM to the demo process, wait for exit.
12. Exit with shot-scraper's exit code.

The script should use only stdlib modules plus `yaml` (from PyYAML). Include `argparse` with `--help` text documenting usage, requirements (Docker, Playwright/Chromium, shot-scraper), and how to add new screenshots.

**stdout=PIPE is critical** — without it, the demo's stdout goes to the terminal and the wrapper can't parse KEY=value lines. But do NOT read until EOF — the demo blocks on `signal.pause()` with the pipe open. Break the read loop on `DEMO_READY=true`.

## Focus
- The demo script outputs `DEMO_READY=true` only after all three services (HA, hassette, Vite) are confirmed healthy. The wrapper does NOT need to re-verify service health.
- The demo script's `find_free_port()` handles port allocation. The wrapper doesn't need to worry about port conflicts.
- `signal.pause()` in the demo keeps the process alive — the wrapper must SIGTERM it to trigger teardown. The demo's own `_signal_handler` calls `teardown()` which stops Docker, kills processes, and cleans up temp dirs.
- Use `os.killpg(proc.pid, signal.SIGTERM)` to kill the demo's process group (it uses `start_new_session=True`), matching the pattern in `hassette_demo.py:133-139`.
- The animation-disabling JS must run before any entry-specific JS (like opening the command palette). Prepend it, don't append.
- shot-scraper's `multi` command processes entries sequentially — one page load per entry. Entries sharing the same URL still load the page separately.

## Verify
- [ ] FR#1: Running `uv run python scripts/capture_screenshots.py` starts the demo, captures screenshots, and tears down
- [ ] FR#2: `docs/screenshots.yml` exists with 16 entries, each having `url`, `output`, `width`; element entries have `selector`
- [ ] FR#3: Full-page manifest entries specify `width: 1400`
- [ ] FR#5: Every manifest entry's resolved `javascript` field begins with the animation-disabling CSS injection
- [ ] FR#6: If the demo fails to start (DEMO_ERROR output), the script exits non-zero. If shot-scraper fails, the script exits with shot-scraper's non-zero code.
- [ ] FR#7: The script resolves repo root from its own path (`Path(__file__).resolve().parent.parent`), not from `os.getcwd()`
- [ ] AC#1: All 16 `docs/_static/web_ui_*.png` files are produced after a successful run
- [ ] AC#2: Full-page screenshots are captured at 1400px viewport width
- [ ] AC#4: Animation-disabling CSS is injected into every manifest entry
- [ ] AC#5: Demo failure produces non-zero exit and descriptive error; no orphaned Docker containers or processes remain
