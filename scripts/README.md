# scripts/

Operational scripts for building, running, and demoing hassette.

- **`export_schemas.py`** — generate OpenAPI and WebSocket JSON schemas for frontend type generation
- **`generate-ws-types.cjs`** — generate TypeScript types from WebSocket schema
- **`generate_constraints.py`** — generate pip constraints file for Docker builds
- **`capture_screenshots.py`** — regenerate `docs/_static/web_ui_*.png` from the `docs/screenshots.yml` manifest (`--only <name>` to scope). See CLAUDE.md → "Demo Stack & Doc Screenshots".
- **`hassette_demo.py`** — demo orchestrator (HA + hassette + Vite) for visual QA; also `mise run demo`. See CLAUDE.md → "Demo Stack & Doc Screenshots".
- **`docker_start.sh`** — Docker container entrypoint
- **`docker/`** — Docker Compose configs for demo/test environments
