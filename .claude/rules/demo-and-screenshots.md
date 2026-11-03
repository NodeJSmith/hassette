---
paths:
  - "frontend/src/**"
  - "docs/screenshots.yml"
  - "docs/_static/**"
  - "docs/pages/**"
  - "scripts/capture_screenshots.py"
  - "tools/frontend/attach_pr_screenshots.py"
  - "tools/frontend/check_pr_screenshots.py"
  - "scripts/demo_stack.py"
  - "scripts/hassette_demo.py"
  - "examples/**"
  - "scripts/demo_apps/**"
---

# Demo Stack and Screenshots

## Live demo stack (visual QA)

For visual/UI work, run the demo stack — **not** the e2e mock server. It starts a real HA container + Hassette (the `examples/` templates plus the demo fixtures in `scripts/demo_apps/`, loaded by `scripts/demo_apps/hassette.toml`) + a Vite dev server with hot reload.

```bash
mise run demo            # or: uv run python scripts/hassette_demo.py  (~60-90s to come up)
mise run demo-verify     # non-interactive health check (apps running, listeners registered, HA integration loaded)
```

`hassette_demo.py` wraps `scripts/demo_stack.py`'s `DemoStack` context manager (`docker compose up -d --wait`). Ports: HA `18123`, hassette `18126`, Vite `15173`; override with `DEMO_HA_PORT`, `DEMO_HASSETTE_PORT`, `DEMO_VITE_PORT`. Ctrl-C/SIGTERM tears it down via `docker compose down --remove-orphans`. If the wrapper died in a way that bypasses those handlers (e.g. `kill -9`/SIGKILL, an OOM kill, or a WSL restart), the containers are still running: `docker compose -p hassette-demo down --remove-orphans` (project name: `COMPOSE_PROJECT_NAME` in `scripts/demo_stack.py`).

The demo HA installs the pinned hass-hassette integration and ships a pre-seeded config entry for it (`tests/fixtures/demo-ha-config/.storage/core.config_entries`, pointing at `http://hassette:8126` with no token; the demo hassette lists the `homeassistant` service in `web_api.trusted_proxies`), so every hassette app shows up as an HA device without clicking through the config flow. `demo-verify` fails if that entry doesn't load. The file is hand-authored: its `minor_version` must be the `core.config_entries` storage version of the pinned HA release, or HA migrates it on load.

Gotchas:
- **Stale app code:** reloading a *failed* app via the REST API reuses the stale module — after editing app code, restart the whole stack.
- **Stale telemetry:** `.demo-data/` persists between runs. If the dashboard shows old errors or inflated counts, stop the stack, `rm -rf .demo-data`, and restart.

## Screenshots (docs and PR evidence)

The docs site embeds `docs/_static/web_ui_*.png` and `docs/_static/ha-*.png`, generated from the manifest `docs/screenshots.yml`. Always capture screenshots — for docs or PR visual evidence — via `scripts/capture_screenshots.py`, never via raw Playwright MCP/browser automation (PR-specific steps: "PR screenshots" below). The script owns auth (session cookie minting, Home Assistant login), animation-disabling, viewport sizing, and demo-stack lifecycle. Needs Playwright + shot-scraper (`uv sync --group dev`), plus Docker for the demo stack.

```bash
uv run python scripts/capture_screenshots.py                                   # all
uv run python scripts/capture_screenshots.py --only web_ui_apps,web_ui_config  # substring match on output filename
uv run python scripts/capture_screenshots.py --only ha-                        # the Home Assistant token walkthrough
```

New screenshot:
1. Add an entry to `docs/screenshots.yml` (URL path, output filename, optional `selector` crop and `wait_for` gate). Crop via `data-testid`, not class names.
2. Embed `![alt](../../_static/web_ui_<name>.png)` in the relevant `docs/pages/` page.
3. Run the capture tool scoped with `--only`.

Home Assistant pages render in shadow DOM, which `selector` and `wait_for` can't reach. Their entries use `{ha_port}` and the `window.docShot` helpers in `scripts/screenshot_page_helpers.js` to wait for targets, drive the UI, and draw the green circle. HA's own UI text and layout change between releases, so rerun `--only ha-` when an HA bump changes the token flow.

If a UI state isn't config-driven (e.g. it needs a crashed instance), add a demo fixture in `scripts/demo_apps/` (see `degraded_demo.py` and its entry in `scripts/demo_apps/hassette.toml`) rather than faking the state. Never add one to `examples/`: that directory holds only apps users copy as templates.

After a UI change that alters a view documented with a screenshot, regenerate the affected `web_ui_*.png`. PRs touching rendered frontend files need visual evidence — see `.claude/rules/design-completeness.md`.

## PR screenshots

### States the demo stack can't produce

The demo stack starts from an empty DB, so it can't show history, a large or adversarial dataset, or an app that left the config but still has an `app_manifests` row. For those, run your own hassette against a seeded DB and point `capture_screenshots.py --against` at it. Don't seed rows into the demo stack's DB by hand.

1. Seed a DB (scenarios are in `scripts/seed_scenarios/`): `uv run python scripts/seed_db.py --scenario healthy --output <dir>/data/hassette.db`
2. Write `<dir>/hassette.toml` with `data_dir = "<dir>/data"`, an unreachable `base_url` (e.g. `http://127.0.0.1:1`) and any `token`, a spare `[hassette.web_api] port`, and `[hassette.apps] directory = "<dir>/apps"`. Every configured app needs a stub file in that directory and `config = { instance_name = "..." }`, or config validation fails. To show removed apps, configure only some of the seed's apps: the rest keep their DB rows but leave the config.
3. Build the SPA so hassette serves the UI: `cd frontend && npm run build`
4. `uv run hassette run -c <dir>/hassette.toml`
5. `uv run python scripts/capture_screenshots.py --against <port> --token-file <dir>/data/.web_api_token --url /apps --url /apps/<app_key> --out <shots-dir>`. Viewport and wait flags are on `--help`. Keep `<shots-dir>` outside `docs/`.

### Attaching screenshots to a PR

Don't commit PR screenshots into the tree: they'd merge into `main` and grow every clone. With the PR branch pushed, run:

```bash
uv run python tools/frontend/attach_pr_screenshots.py <shots-dir>/*.png
```

It pushes two commits to the branch, one adding the images and one removing them, and prints a `### Screenshots` block linking each image at the add commit's SHA. Paste that block into the PR body yourself; the tool never edits it. The squash merge drops both commits, and the links keep working after the branch is deleted because GitHub keeps PR commits under `refs/pull/<N>/head`. Rerun it after retaking screenshots and replace the block.
