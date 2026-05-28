# Design: Automated Doc Screenshot Capture

**Date:** 2026-05-27
**Status:** approved
**Scope-mode:** hold
**Research:** design/research/2026-05-21-automated-doc-screenshots/research.md

## Problem

Documentation screenshots go stale after UI changes. The current workflow is fully manual: start the demo environment, navigate to each page, capture via interactive Playwright MCP, crop detail elements by hand, and commit the results. With 16 screenshots across 8 doc pages, a single UI layout change means 20+ minutes of repetitive capture work.

The screenshots are currently stale and have been through multiple releases. The friction of manual recapture means nobody updates them when the UI changes, so the docs silently drift from the real UI. Every release that touches the frontend widens the gap between what the docs show and what users actually see.

## Goals

- One command regenerates all documentation screenshots from a clean state
- The command produces all 16 `docs/_static/web_ui_*.png` files matching the current UI
- Adding a new screenshot means adding a manifest entry and a doc reference — no scripting
- Detail screenshots (element-level crops) use stable selectors that survive refactors
- Animations and transitions are disabled during capture for consistent output

## User Scenarios

### Developer: framework maintainer or AI coding agent
- **Goal:** Update all doc screenshots after a UI change
- **Context:** Working in a feature branch, just modified frontend code

#### Regenerate screenshots after UI change

1. **Run the capture script**
   - Sees: A single command to execute (`uv run python scripts/capture_screenshots.py`)
   - Decides: N/A — the command is deterministic
   - Then: Demo environment starts (HA container + hassette + Vite), readiness is confirmed, screenshots are captured, demo tears down

2. **Review and commit**
   - Sees: Updated PNG files in `docs/_static/`
   - Decides: Whether the screenshots look correct (git diff or visual inspection)
   - Then: Commits the updated PNGs alongside the UI change

### Developer: adding a new doc screenshot

1. **Add manifest entry**
   - Sees: Existing entries in the YAML manifest as examples
   - Decides: URL path, output filename, viewport size, optional selector for element crop
   - Then: Adds the entry to the manifest

2. **Reference in docs**
   - Sees: The output path from the manifest entry
   - Decides: Where in the doc page to insert the image
   - Then: Adds a Markdown image reference

3. **Run capture and commit**
   - Same as regeneration flow above

## Functional Requirements

- **FR#1** A wrapper script starts the demo environment, waits for readiness, captures all screenshots defined in a manifest, and tears down the demo
- **FR#2** A YAML manifest defines each screenshot with URL path, output file path, viewport dimensions, and optional element selector
- **FR#3** Full-page screenshots capture at 1400px viewport width to match existing screenshot dimensions
- **FR#4** Element-level screenshots use `data-testid` CSS selectors to crop specific UI components
- **FR#5** CSS animations and transitions are disabled during capture via injected stylesheet
- **FR#6** The wrapper script exits with a non-zero code if any screenshot fails to capture
- **FR#7** The wrapper script can run from any working directory within the repository

## Edge Cases

- **Demo fails to start** — wrapper script reports the error from `hassette_demo.py` output (DEMO_ERROR lines) and exits non-zero without leaving orphaned processes
- **Demo hangs silently** — wrapper enforces a 180-second wall-clock deadline on stdout reading. On timeout, kills the demo subprocess, prints a diagnostic (check Docker status, port conflicts), and exits non-zero
- **Element selector not found** — shot-scraper reports which selector failed; wrapper exits non-zero
- **Port conflicts** — handled by the demo script's `find_free_port()` — no additional work needed
- **Font loading delays** — `wait` parameter in manifest entries gives fonts time to load; if headless environments hang on fonts, `PW_TEST_SCREENSHOT_NO_FONTS_ENVIRONMENT=1` can be set
- **Demo stimulator hasn't generated data yet** — the demo stimulator's `failing_job` default interval is reduced from 60s to 5s in `examples/demo_stimulator.py` so errors appear quickly after startup. After `DEMO_READY`, the wrapper polls `GET /api/apps/{app_key}` until error data exists (90-second timeout, 2-second poll interval) before proceeding to shot-scraper. This ensures error-state screenshots always have content.

## Acceptance Criteria

- **AC#1** Running `uv run python scripts/capture_screenshots.py` from the repo root produces all 16 `docs/_static/web_ui_*.png` files (FR#1, FR#2)
- **AC#2** Full-page screenshots are 1400px wide (FR#3)
- **AC#3** Detail screenshots (sidebar, status bar, error spotlight, etc.) capture only the target element, not the full page (FR#4)
- **AC#4** No CSS animations or transitions are visible in captured screenshots (FR#5)
- **AC#5** If the demo environment fails to start, the script exits non-zero with a descriptive error and no orphaned processes (FR#6)
- **AC#6** Adding a new screenshot requires only a YAML manifest entry and a Markdown image reference — no script changes (FR#2)

## Key Constraints

- **Do not conflate with visual regression testing.** Screenshots should update when the UI changes, not fail. This is doc generation, not pixel-diff testing.
- **Do not write per-screenshot Playwright scripts.** The YAML manifest pattern exists to avoid the anti-pattern of 14+ bespoke scripts that each handle different interactions (documented in research brief).
- **Do not modify `scripts/hassette_demo.py`.** The wrapper script is a consumer of the demo environment, not a modifier. If the demo script needs changes, that is a separate issue.

## Dependencies and Assumptions

- **shot-scraper** — Python CLI built on Playwright for YAML-manifest-driven screenshot capture. Already evaluated in the research brief; pip/uv installable.
- **Playwright + Chromium** — already in dev deps for e2e tests. shot-scraper uses Playwright under the hood.
- **Demo environment** (`scripts/hassette_demo.py`) — provides HA + hassette + Vite with deterministic data via the demo stimulator app.
- **Demo stimulator** (`examples/demo_stimulator.py`) — generates error/activity data needed for error-state screenshots.
- **Assumption:** Docker is available (required by the demo environment for the HA container).
- **Assumption:** `data-testid` attributes on target components remain stable. If a `data-testid` is removed during a refactor, the corresponding manifest entry breaks visibly (shot-scraper reports the missing selector).

## Architecture

### shot-scraper as dev dependency

Add `shot-scraper` to the `[project.optional-dependencies]` dev group in `pyproject.toml`. shot-scraper installs Playwright as a dependency, but the project already has Playwright installed for e2e tests — no additional browser install needed.

### YAML manifest: `docs/screenshots.yml`

A single YAML file defines all screenshots. Each entry maps to one output file:

```yaml
# Full-page screenshots (1400px viewport, full-page capture)
- url: http://localhost:{port}/apps
  output: docs/_static/web_ui_apps.png
  width: 1400
  height: 900
  wait: 2000

# Element-level crops (selector-based)
- url: http://localhost:{port}/apps
  output: docs/_static/web_ui_detail_sidebar.png
  selector: "[data-testid='sidebar']"
  width: 1400
  height: 900
  wait: 2000
```

The `{port}` placeholder will be resolved by the wrapper script before passing to shot-scraper. Alternatively, the wrapper can write a resolved copy of the manifest to a temp file.

### Screenshot inventory mapped to manifest entries

**Full-page (8):**

| Output file | URL path | Notes |
|---|---|---|
| `web_ui_apps.png` | `/apps` | Landing page |
| `web_ui_handlers.png` | `/handlers` | Handlers list |
| `web_ui_logs.png` | `/logs` | Logs page |
| `web_ui_config.png` | `/config` | Config page (tall — needs `height: 1656`) |
| `web_ui_app_detail_overview.png` | `/apps/motion_lights/overview` | App detail overview (tall — `height: 1508`). `motion_lights` chosen: has two instances (exercises instance switcher) and receives error injection from demo stimulator. |
| `web_ui_app_detail_handlers.png` | `/apps/motion_lights/handlers` | App detail handlers |
| `web_ui_app_detail_code.png` | `/apps/motion_lights/code` | App detail code |
| `web_ui_app_detail_config.png` | `/apps/motion_lights/config` | App detail config |

**Element-level (8):**

| Output file | URL path | Selector | Notes |
|---|---|---|---|
| `web_ui_detail_sidebar.png` | `/apps` | `[data-testid='sidebar']` | Sidebar nav |
| `web_ui_detail_status_bar.png` | `/apps` | `[data-testid='status-bar']` | Top status bar |
| `web_ui_detail_command_palette.png` | `/apps` | `[data-testid='cmd-palette']` | JS opens palette: `document.dispatchEvent(new KeyboardEvent('keydown', {key: 'k', ctrlKey: true}))`. Must use `wait_for: "[data-testid='cmd-palette']"` because Preact state update is async — without it, shot-scraper captures before the DOM updates. |
| `web_ui_detail_column_picker.png` | `/logs` | `[data-testid='column-picker-popover']` | **Requires adding `data-testid="column-picker-popover"` to `ColumnFilterPopover`'s root `<div>` in `column-filter-popover/index.tsx`.** JS clicks the trigger button first: `document.querySelector('[data-testid="column-picker"]')?.click()` |
| `web_ui_detail_error_spotlight.png` | `/apps/demo_stimulator/overview` | `[data-testid='overview-error-spotlight']` | Error spotlight section. Targets `demo_stimulator` because it runs the intentionally-failing `sensor_health_check` job that populates error data. |
| `web_ui_detail_handler_error.png` | `/apps/demo_stimulator/handlers` | `[data-testid^='unified-row-']` (first row with failed > 0) | Targets `demo_stimulator` for error data. **Requires adding `data-testid="handler-failed-count"` to the `<span class={styles.statsErr}>` in `unified-handler-row.tsx`.** JS finds the target: `document.querySelector('[data-testid="handler-failed-count"]')?.closest('[data-testid^="unified-row-"]')` — note: cannot use `.statsErr` directly because CSS modules hash class names at build time. |
| `web_ui_detail_instance_switcher.png` | `/apps/motion_lights/overview` | `[data-testid='instance-switcher']` | Instance tab bar |
| `web_ui_detail_log_drawer.png` | `/logs` | `[data-testid='log-detail-drawer']` | **Requires adding `data-testid="log-detail-drawer"` to `LogDetailDrawer`'s root `<aside>` in `log-detail-drawer.tsx:120`.** JS clicks the first log table row to open the drawer: `document.querySelector('tbody tr')?.click()` |

Some detail screenshots require pre-capture JavaScript to open UI elements (command palette, column picker dropdown, log drawer). shot-scraper's `javascript` field handles this.

### Wrapper script: `scripts/capture_screenshots.py`

A Python script that orchestrates the full flow:

1. Parse `docs/screenshots.yml`
2. Delete `.demo-data/hassette.db` if it exists (ensures deterministic screenshot content across runs)
3. Start the demo environment as a subprocess (`scripts/hassette_demo.py`)
4. Read `DEMO_READY=true` and `DEMO_FRONTEND_URL=...` from stdout (with 180-second wall-clock deadline)
5. Poll hassette API until error data exists (90-second timeout)
6. Resolve port placeholders in manifest entries
7. Write resolved manifest to a temp file
8. Run `shot-scraper multi <temp-manifest>` as a subprocess
9. Tear down the demo (send SIGTERM to the demo subprocess)
10. Exit with shot-scraper's exit code

The wrapper follows the same signal-handling and cleanup patterns as `hassette_demo.py`: register `atexit` + `SIGINT`/`SIGTERM` handlers to ensure the demo process is always terminated.

### Animation disabling

Inject a CSS override via shot-scraper's `javascript` field on every manifest entry (or a shared pre-capture script):

```javascript
const style = document.createElement('style');
style.textContent = '*, *::before, *::after { animation-duration: 0s !important; transition-duration: 0s !important; }';
document.head.appendChild(style);
```

This can be factored into a shared JS snippet loaded by the wrapper and prepended to each entry's `javascript` field before writing the resolved manifest.

### Nox session (optional convenience)

Add a `screenshots` nox session that runs the wrapper script, matching the project's pattern for dev tooling:

```python
@nox.session(python=False)
def screenshots(session):
    session.run("uv", "run", "python", "scripts/capture_screenshots.py", external=True)
```

## Replacement Targets

No existing code is being replaced. This is purely additive tooling.

## Convention Examples

### Multi-service orchestration script

**Source:** `scripts/hassette_demo.py:187-210`

```python
def main() -> None:
    global _ha_compose_file, _ha_project_name, _ha_env, ...

    atexit.register(teardown)
    signal.signal(signal.SIGINT, _signal_handler)
    signal.signal(signal.SIGTERM, _signal_handler)

    repo_root = Path(__file__).resolve().parent.parent
    # ... sequential startup with readiness polling
```

The wrapper script should follow this same pattern: atexit + signal handlers registered early, repo root derived from script location, teardown idempotent.

### Readiness polling via KEY=value output

**Source:** `scripts/hassette_demo.py:388-396`

```python
print(f"DEMO_HA_URL=http://localhost:{ha_port}", flush=True)
print(f"DEMO_HASSETTE_URL=http://localhost:{hassette_port}", flush=True)
print(f"DEMO_FRONTEND_URL=http://localhost:{vite_port}", flush=True)
print("DEMO_READY=true", flush=True)
```

The wrapper script parses these lines from the demo subprocess stdout to extract the frontend URL.

### Viewport constants

**Source:** `tests/e2e/conftest.py:42-49`

```python
MOBILE_VIEWPORT = {"width": 375, "height": 812}
DESKTOP_VIEWPORT = {"width": 1024, "height": 768}
```

Existing screenshots use 1400px width (wider than the e2e desktop viewport). The manifest should document this choice.

### Nox session for external tooling

**Source:** `noxfile.py:67-90`

```python
@nox.session(python=["3.13"])
def e2e(session: "Session"):
    if not _SPA_INDEX.exists():
        session.run("npm", "ci", "--prefix", "frontend", external=True)
        session.run("npm", "run", "build", "--prefix", "frontend", external=True)
    session.run("uv", "run", "--active", "playwright", "install", "--with-deps", "chromium", external=True)
    session.run("uv", "run", "--active", "--reinstall-package", "hassette", "pytest", ...)
```

The screenshots nox session follows the same pattern: `python=False` or `python=["3.13"]`, external tool invocation.

## Alternatives Considered

### Bespoke Playwright scripts per screenshot

Write individual Python scripts using Playwright directly for each screenshot. Rejected: doesn't scale (documented anti-pattern in research brief), harder to review, and each script reinvents navigation and capture logic.

### Build-integrated capture (screenshots during mkdocs build)

Wire screenshot capture into `mkdocs build` so screenshots are always fresh. Rejected: requires the full demo environment (Docker, HA) to build docs, which breaks docs-only workflows and increases build time significantly.

### Heroshot instead of shot-scraper

Heroshot offers a visual picker for selector generation and built-in annotation support. Rejected for now: newer tool with less ecosystem maturity, and annotation support is out of scope. Could revisit if annotation needs arise.

## Test Strategy

### Existing Tests to Adapt
No existing tests affected — this is new tooling with no test infrastructure to modify.

### New Test Coverage
- **Unit test for manifest loading** (FR#2): Validate that the YAML manifest parses correctly and all required fields are present. Verify port placeholder resolution produces valid URLs.
- **Integration test for wrapper script** (FR#1): Run the wrapper with `--dry-run` flag (or equivalent) that validates the manifest and checks shot-scraper availability without starting the demo. This avoids requiring Docker in the test suite.

### Tests to Remove
No tests to remove.

## Documentation Updates

- **`scripts/capture_screenshots.py`** — inline `--help` text documenting usage, requirements (Docker, Playwright/Chromium), and how to add new screenshots
- **`docs/screenshots.yml`** — YAML comments at the top explaining the manifest format and how to add entries
- **Issue #801** — close when merged

## Impact

### Changed Files
- `pyproject.toml` — add `shot-scraper` to dev dependencies
- `docs/screenshots.yml` — new manifest file (16 entries)
- `scripts/capture_screenshots.py` — new wrapper script
- `noxfile.py` — add `screenshots` session
- `examples/demo_stimulator.py` — reduce `failure_interval` default from 60s to 5s
- `frontend/src/components/shared/log-table/log-detail-drawer.tsx` — add `data-testid="log-detail-drawer"` to root `<aside>`
- `frontend/src/components/shared/column-filter-popover/index.tsx` — add `data-testid="column-picker-popover"` to root `<div>`
- `frontend/src/components/app-detail/unified-handler-row.tsx` — add `data-testid="handler-failed-count"` to the `<span class={styles.statsErr}>` element

### Behavioral Invariants
- Existing `docs/_static/web_ui_*.png` files must be reproducible — running the script should produce screenshots that match the current manual captures in content (not necessarily pixel-identical, but showing the same UI state and elements)
- The demo environment (`scripts/hassette_demo.py`) must not be modified
- E2e tests and their Playwright/Chromium setup must not be affected

### Blast Radius
- **docs/ only** — the output PNGs are referenced by Markdown files in `docs/pages/web-ui/`. No other consumers.
- **Dev tooling only** — shot-scraper is a dev dependency. No production impact.

## Open Questions

None — all design decisions resolved.
