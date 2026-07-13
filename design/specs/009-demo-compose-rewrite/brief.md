# Brief: Compose-Native Demo Stack

**Date:** 2026-07-12
**Status:** explored

## Idea

Rewrite `scripts/hassette_demo.py` (~392 lines) and `scripts/capture_screenshots.py` (~301 lines) to run all three demo services (HA, hassette, vite) in Docker Compose instead of managing hassette and vite as host subprocesses. The current script is fragile process orchestration that leaks containers on interrupt (#1158), is hard to maintain, and uses ~700 combined lines for what should be "start three things, block, clean up."

## Key Decisions Made

- **Full compose, not refactor-only.** The research brief recommended refactoring (DemoStack/ProcessGroup) over compose, primarily because "Vite HMR degrades in Docker on WSL2." That concern is invalid — Docker runs natively inside WSL2 (not Docker Desktop), so bind mounts use the native Linux filesystem and inotify works perfectly. With the HMR concern debunked, compose delivers an actual architecture change rather than reorganizing the same subprocess management.
- **Fixed ports with conflict detection, not dynamic allocation.** Concurrent demo runs have never happened in practice across several months of use. Dynamic port allocation adds complexity (port discovery, TOCTOU races). Fixed defaults with a "port in use" error message are simpler and compose-native. The compose file can use env-var overrides for the edge case.
- **hassette_demo.py stays as a thin wrapper.** Even with compose, the script serves a purpose: copy HA fixture config to tmpdir, set env vars, `docker compose up -d`, wait for health, print `DEMO_*=` key-value lines, block, `docker compose down --remove-orphans`. Roughly 50-80 lines. Consumers (capture_screenshots.py, demo-verify, agents) keep using the stdout contract.
- **Dev Dockerfiles are acceptable.** Two ~10-line Dockerfiles with no other consumers is not a real maintenance burden.
- **capture_screenshots.py keeps consuming hassette_demo.py**, not talking to compose directly. Avoids duplicating fixture-copy and port logic.

## Open Questions

- **Vite container config details.** How exactly does the Vite dev server's `VITE_PROXY_TARGET` work when hassette is also in a container? Likely `http://hassette:<port>` via Docker DNS, but needs confirmation during design.
- **hassette config path resolution.** `examples/hassette.toml` references `apps.directory = "examples"` as a relative path. Inside a container with bind-mounted source, this needs to resolve correctly. May need an absolute path override via env var.
- **`.demo-data/` persistence.** Currently a host directory for hassette's SQLite DB across runs. Needs to be a bind mount or named volume in compose.
- **`DEMO_VITE_HOST` for remote access.** Currently passes `--host` to Vite. In compose, Vite already binds inside the container — remote access means exposing the port on `0.0.0.0` in the compose port mapping, which is a different mechanism.
- **HA token duplication.** The JWT is duplicated in three places (hassette_demo.py, ha-demo.yml healthcheck, fixture .storage/auth). Could consolidate to one source during the rewrite, but may be out of scope.
- **demo-verify mise task.** Not wired into CI or other tasks. Could be simplified or removed during the rewrite.

## Scope Boundaries

**In scope:**
- Extend `scripts/docker/ha-demo.yml` with hassette and vite services
- Two new dev Dockerfiles (hassette-dev, vite-dev) in `scripts/docker/`
- Rewrite `scripts/hassette_demo.py` as thin compose wrapper (~50-80 lines)
- Simplify `scripts/capture_screenshots.py` teardown (compose down replaces process-group signals)
- Fix #1158 (orphaned containers) as a natural consequence

**Out of scope:**
- Consolidating HA token to a single source
- Rewriting demo-verify (can adapt to new interface with minimal changes)
- Changes to the screenshot manifest format or shot-scraper integration
- Production Dockerfile changes

**Deferred:**
- Removing demo-verify if it proves unused

## Risks and Concerns

- **Inter-container networking.** All three services currently share localhost. In compose, they communicate via Docker DNS (service names). The proxy chain becomes `browser -> Vite (container) -> hassette (container, Docker DNS) -> HA (container, Docker DNS)`. This is standard compose networking but is a change from the current model.
- **Source volume mounts for hassette.** Needs `src/`, `examples/`, `pyproject.toml`, `uv.lock` mounted. The production Dockerfile copies these at build time; the dev setup bind-mounts them. Path alignment matters.
- **Port exposure for the browser.** Vite's container port needs to be mapped to the host so the browser (and capture_screenshots.py's shot-scraper) can reach it. Fixed port mapping in compose handles this.

## Codebase Context

- `scripts/docker/ha-demo.yml` — 16 lines, HA-only compose file with env-var port mapping and healthcheck. Extension point for new services.
- `Dockerfile` (repo root) — 109-line production multi-stage build. Provides reference for Python/uv setup but is not directly reusable for dev (builds static SPA, copies source instead of mounting).
- `.mise/tasks/demo-verify` — 89-line bash script, another stdout-contract consumer with its own teardown. Not wired into CI.
- `tests/system/conftest.py` — has near-identical HA readiness polling and fixture-copy logic. The compose healthcheck would replace the Python polling, but the fixture-copy logic still needs to exist somewhere.
- `examples/hassette.toml` — demo config with relative paths. Needs path resolution inside container.
- Research brief: `design/research/2026-07-12-demo-compose/research.md` — full investigation of both options. Option A (compose) is now preferred after the HMR concern was debunked.
