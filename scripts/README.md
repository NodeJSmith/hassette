# scripts/

Operational scripts for building, running, and demoing hassette.

- **`export_schemas.py`** — generate OpenAPI, WebSocket, and hassette.toml config JSON schemas for frontend type generation and IDE autocomplete
- **`generate-ws-types.cjs`** — generate TypeScript types from WebSocket schema
- **`generate_constraints.py`** — generate pip constraints file for Docker builds
- **`demo_stack.py`** — shared `DemoStack` context manager: copies the HA fixture
  config to a tmpdir, runs `docker compose up -d --wait` / `down --remove-orphans`
  for the HA + hassette + Vite stack, and handles signal/atexit teardown. Imported
  by `hassette_demo.py` and `capture_screenshots.py`; not run directly.
- **`capture_screenshots.py`** — regenerate `docs/_static/web_ui_*.png` from
  `docs/screenshots.yml` (`--only <name>` to scope). Starts the demo stack via
  `DemoStack`, runs shot-scraper, tears down. See `.claude/rules/demo-and-screenshots.md`.
- **`hassette_demo.py`** — thin wrapper around `DemoStack` for interactive visual
  QA: starts the compose stack, prints URLs, blocks until signaled; also
  `mise run demo`. See `.claude/rules/demo-and-screenshots.md`.
- **`release_contributors.py`** — find external contributors between two git
  tags. Filters bots and repo owner, resolves GitHub usernames from noreply
  emails. Used by the `changelog-review` command during release prep.
- **`ci_flake_scan.py`** — scan recent GitHub Actions runs (`Tests`, `E2E Tests`
  by default) for recurring pytest failures, separating real flaky tests from
  GitHub Actions infra noise (network hiccups, artifact-permission errors).
  Earlier attempts count too, so a failure a rerun cleared still shows up.
  Cross-references open `topic:flaky-test` issues (titled `Fix flaky <test name>`)
  so already-tracked flakes are reported as known rather than resurfacing every scan. `--days N` to change the
  lookback window, `--workflow` (repeatable) to scope to specific workflows.
- **`demo_apps/`** — demo and screenshot fixture apps (`demo_stimulator`,
  `degraded_demo`, `blocking_demo`, ...) that put the web UI into specific states.
  Not user templates; those live in `examples/`. Its `hassette.toml` is the demo
  stack's config and loads both sets.
- **`docker_start.sh`** — Docker container entrypoint.
- **`docker/`** — Docker Compose configs for demo/test environments
  (`ha-demo.yml` defines the HA + hassette + Vite demo stack;
  `Dockerfile.hassette-dev` and `Dockerfile.vite-dev` are the dev-mode images).
