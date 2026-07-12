# Context: Compose-Native Demo Stack

## Problem & Motivation

The demo orchestrator (`scripts/hassette_demo.py`, ~392 lines) and screenshot capture tool (`scripts/capture_screenshots.py`, ~301 lines) manage three services through manual subprocess orchestration: dynamic port allocation, process-group lifecycle, signal handling with cascading teardown, readiness polling, and a stdout IPC protocol. This architecture leaks Docker containers when interrupted (#1158), is difficult to modify, and represents ~700 lines of infrastructure for what should be "start three things, block, clean up." Only HA runs in Docker today; hassette and vite run as bare host subprocesses.

## Visual Artifacts

None.

## Key Decisions

1. **Full Docker Compose for all three services.** HA, hassette, and vite all run as compose services. HMR concern debunked — Docker runs natively inside WSL2, bind mounts use the native Linux filesystem.
2. **Fixed ports with env-var overrides.** Default ports: HA=18123, hassette=18126, vite=15173. Overridable via `DEMO_HA_PORT`, `DEMO_HASSETTE_PORT`, `DEMO_VITE_PORT`. Concurrent demo runs never happen in practice.
3. **Shared DemoStack context manager.** New `scripts/demo_stack.py` (~80 lines) handles fixture copy, compose up/down, signal handlers, and cleanup. Both `hassette_demo.py` and `capture_screenshots.py` import it.
4. **No stdout IPC protocol.** The `DEMO_*=` key-value protocol is eliminated. With fixed ports, consumers know the URLs without discovery. Scripts print human-readable messages only.
5. **`docker compose up -d --wait` replaces Python readiness polling.** Compose health checks are declarative in the YAML; `--wait` blocks until all pass.
6. **`UV_PROJECT_ENVIRONMENT=/opt/venv`** inside the hassette container to prevent `uv sync` from corrupting the host's `.venv` via bind mount.

## Constraints & Anti-Patterns

- The HA fixture ignore list in `demo_stack.py` must match `tests/system/conftest.py`. Cross-reference in a comment.
- Vite must run with `--host 0.0.0.0` inside the container for Docker port mapping. Set in the Dockerfile CMD, not in `vite.config.ts`.
- Do NOT change the `docs/screenshots.yml` manifest format or shot-scraper integration.
- Do NOT modify the production `Dockerfile` at the repo root.
- Do NOT implement support for concurrent demo runs.
- Do NOT consolidate the HA JWT token to a single source.
- Compose project name is `hassette-demo` (fixed, no port suffix).
- All ports bind to `127.0.0.1` on the host (SSH-tunnel friendly, not exposed to LAN).

## Design Doc References

- `## Problem` — what's broken and why it matters
- `## Architecture` — compose file extension, dev Dockerfiles, DemoStack module, volume mounts table
- `## Replacement Targets` — old code/patterns being removed
- `## Edge Cases` — interrupt scenarios, port conflicts, stale data
- `## Documentation Updates` — CLAUDE.md, harness.md, spec 048

## Convention Examples

None — no convention examples captured during discovery.
