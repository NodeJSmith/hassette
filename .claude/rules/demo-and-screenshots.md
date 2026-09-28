---
paths:
  - "frontend/src/**"
  - "docs/screenshots.yml"
  - "docs/_static/**"
  - "docs/pages/**"
  - "scripts/capture_screenshots.py"
  - "scripts/demo_stack.py"
  - "scripts/hassette_demo.py"
  - "examples/**"
---

# Demo Stack and Screenshots

## Live demo stack (visual QA)

For visual/UI work, run the demo stack — **not** the e2e mock server. It starts a real HA container + Hassette (with the example apps) + a Vite dev server with hot reload.

```bash
mise run demo            # or: uv run python scripts/hassette_demo.py  (~60-90s to come up)
mise run demo-verify     # non-interactive health check (apps running, listeners registered)
```

`hassette_demo.py` wraps `scripts/demo_stack.py`'s `DemoStack` context manager (`docker compose up -d --wait`). Ports: HA `18123`, hassette `18126`, Vite `15173`; override with `DEMO_HA_PORT`, `DEMO_HASSETTE_PORT`, `DEMO_VITE_PORT`. Ctrl-C/SIGTERM tears it down via `docker compose down --remove-orphans`. If the wrapper died any other way (e.g. `pkill`), the containers are still running: `docker compose -p hassette-demo down --remove-orphans` (project name: `COMPOSE_PROJECT_NAME` in `scripts/demo_stack.py`).

Gotchas:
- **Stale app code:** reloading a *failed* app via the REST API reuses the stale module — after editing app code, restart the whole stack.
- **Stale telemetry:** `.demo-data/` persists between runs. If the dashboard shows old errors or inflated counts, stop the stack, `rm -rf .demo-data`, and restart.

## Screenshots (docs and PR evidence)

The docs site embeds `docs/_static/web_ui_*.png`, generated from the manifest `docs/screenshots.yml`. Always capture screenshots — for docs or PR visual evidence — via `scripts/capture_screenshots.py`, never via raw Playwright MCP/browser automation. The script owns auth (session cookie minting), animation-disabling, viewport sizing, and demo-stack lifecycle. Needs Docker + Playwright + shot-scraper (`uv sync --group dev`).

```bash
uv run python scripts/capture_screenshots.py                                   # all
uv run python scripts/capture_screenshots.py --only web_ui_apps,web_ui_config  # substring match on output filename
```

New screenshot:
1. Add an entry to `docs/screenshots.yml` (URL path, output filename, optional `selector` crop and `wait_for` gate). Crop via `data-testid`, not class names.
2. Embed `![alt](../../_static/web_ui_<name>.png)` in the relevant `docs/pages/` page.
3. Run the capture tool scoped with `--only`.

If a UI state isn't config-driven (e.g. it needs a crashed instance), add a demo fixture (see `examples/degraded_demo.py` and its `autostart = false` entry in `examples/hassette.toml`) rather than faking the state.

After a UI change that alters a view documented with a screenshot, regenerate the affected `web_ui_*.png`. PRs touching rendered frontend files need visual evidence — see `.claude/rules/design-completeness.md`.
