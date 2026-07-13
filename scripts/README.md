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
  `DemoStack`, runs shot-scraper, tears down. See CLAUDE.md → "Demo Stack & Doc
  Screenshots".
- **`hassette_demo.py`** — thin wrapper around `DemoStack` for interactive visual
  QA: starts the compose stack, prints URLs, blocks until signaled; also
  `mise run demo`. See CLAUDE.md → "Demo Stack & Doc Screenshots".
- **`docker_start.sh`** — Docker container entrypoint.
- **`docker/`** — Docker Compose configs for demo/test environments
  (`ha-demo.yml` defines the HA + hassette + Vite demo stack;
  `Dockerfile.hassette-dev` and `Dockerfile.vite-dev` are the dev-mode images).
