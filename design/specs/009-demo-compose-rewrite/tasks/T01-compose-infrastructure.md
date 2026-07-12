---
task_id: "T01"
title: "Add compose services and dev Dockerfiles for hassette and vite"
status: "planned"
depends_on: []
implements: ["FR#1", "FR#3", "FR#4", "FR#6", "FR#7", "FR#8"]
---

## Summary

Create the Docker infrastructure that runs all three demo services via a single compose file. Extend the existing `ha-demo.yml` with hassette and vite services, each with health checks and `depends_on` ordering. Create two minimal dev Dockerfiles. This is the foundation all other tasks build on.

## Target Files

- modify: `scripts/docker/ha-demo.yml`
- create: `scripts/docker/Dockerfile.hassette-dev`
- create: `scripts/docker/Dockerfile.vite-dev`
- read: `Dockerfile` (production Dockerfile — reference for Python/UV/Node versions)
- read: `frontend/vite.config.ts` (proxy target env var)
- read: `src/hassette/cli/__init__.py` (CLI subcommand structure)

## Prompt

Extend `scripts/docker/ha-demo.yml` to add `hassette` and `vite` services alongside the existing `homeassistant` service.

**Compose file changes:**

Keep the existing `homeassistant` service. Change its `container_name` from `"hassette-demo-ha-${HA_PORT:-8123}"` to omit the port (fixed project name handles naming). Change its port mapping to `"127.0.0.1:${DEMO_HA_PORT:-18123}:8123"`.

Add a `hassette` service:
- Build from `scripts/docker/Dockerfile.hassette-dev` (set `context: ../..` for repo root access during build)
- Port: `"127.0.0.1:${DEMO_HASSETTE_PORT:-18126}:8126"`
- Volumes: bind-mount repo root at `/app`, bind-mount `../../.demo-data:/app/.demo-data`
- Environment: `HASSETTE__BASE_URL=http://homeassistant:8123`, `HASSETTE__TOKEN=<the JWT from the existing HA_TOKEN constant>`, `HASSETTE__WEB_API__PORT=8126`, `HASSETTE__APPS__DIRECTORY=/app/examples`, `HASSETTE__DATA_DIR=/app/.demo-data`
- `depends_on: homeassistant: condition: service_healthy`
- Health check: `curl -sf http://localhost:8126/api/health` (interval 5s, timeout 5s, retries 6, start_period 10s)
- `restart: "no"`

Add a `vite` service:
- Build from `scripts/docker/Dockerfile.vite-dev` (set `context: ../..`)
- Port: `"127.0.0.1:${DEMO_VITE_PORT:-15173}:5173"`
- Volumes: bind-mount `../../frontend:/app/frontend`, anonymous volume at `/app/frontend/node_modules`
- Environment: `VITE_PROXY_TARGET=http://hassette:8126`
- `depends_on: hassette: condition: service_healthy`
- Health check: `curl -sf http://localhost:5173` (interval 3s, timeout 3s, retries 5, start_period 10s)
- `restart: "no"`

**Dockerfile.hassette-dev** (~6 lines):
```
FROM python:3.14-slim
COPY --from=ghcr.io/astral-sh/uv:0.11.26 /uv /bin/uv
ENV UV_PROJECT_ENVIRONMENT=/opt/venv
WORKDIR /app
CMD ["sh", "-c", "uv sync --locked && exec uv run python -m hassette --config-file examples/hassette.toml run"]
```

**Dockerfile.vite-dev** (~5 lines):
```
FROM node:24-slim
RUN apt-get update && apt-get install -y --no-install-recommends curl && rm -rf /var/lib/apt/lists/*
WORKDIR /app/frontend
CMD ["sh", "-c", "npm install && exec npm run dev -- --host 0.0.0.0 --port 5173"]
```

Note: the vite Dockerfile needs `curl` for the health check. The hassette base image (`python:3.14-slim`) should already have curl, but verify — if not, add the same apt-get install.

Check that the existing HA JWT token in `ha-demo.yml`'s healthcheck matches the `HA_TOKEN` constant in the current `scripts/hassette_demo.py` (lines 33-38). Use the same token in the hassette service's `HASSETTE__TOKEN` environment variable.

## Focus

- The current `ha-demo.yml` is 16 lines with only the HA service. The extension adds ~40 lines for the two new services.
- `vite.config.ts` (line 5) reads `VITE_PROXY_TARGET` — the compose environment sets this to `http://hassette:8126` (Docker DNS resolution).
- The production `Dockerfile` uses `ARG PYTHON_VERSION=3.14.6` and `ARG UV_VERSION=0.11.26` — match these versions in `Dockerfile.hassette-dev`.
- The production `Dockerfile` uses `node:24-slim` for the frontend stage — match this in `Dockerfile.vite-dev`.
- `python:3.14-slim` may not have `curl` — check and add if needed for the health check.
- The anonymous volume at `/app/frontend/node_modules` prevents platform-specific native module issues by keeping deps container-local.

## Verify

- [ ] FR#1: `docker compose -f scripts/docker/ha-demo.yml up -d --wait` starts all three services and exits 0 (requires setting `HA_CONFIG_PATH` to a valid HA config dir first)
- [ ] FR#3: `DEMO_HA_PORT=29123 DEMO_HASSETTE_PORT=29126 DEMO_VITE_PORT=29173 docker compose ... up -d --wait` starts on the overridden ports
- [ ] FR#4: `docker compose -f scripts/docker/ha-demo.yml ps` shows all three services as healthy
- [ ] FR#7: With the stack running, editing a `.tsx` file triggers HMR reload in the browser
- [ ] FR#6: `.demo-data/` bind mount is declared in the compose file for the hassette service
- [ ] FR#8: All three ports are bound to `127.0.0.1` (verify with `docker compose port` or `ss -tlnp`)
