# Prereq 03 — Ingress Source Guard (`web_api.allowed_client_ips`)

**Repo:** hassette
**Depends on:** nothing
**Size:** small

## Problem

The add-on spec requires ingress add-ons to accept connections only from the ingress gateway
(`172.30.32.2`) and deny all other clients. Hassette's web server binds `0.0.0.0:8126`
(`WebApiConfig.host`, `src/hassette/config/models.py:319`) with no client filtering — the only
middleware is CORS (`src/hassette/web/app.py:53-59`). Since the web API is unauthenticated,
the guard is what makes "ingress-only" actually mean supervisor-authenticated-only inside the
add-on's docker network.

## Design (T5 in the research brief)

New config field `web_api.allowed_client_ips: tuple[str, ...] | None = None`:

- `None` (default) — allow all clients; today's behavior for every existing deployment.
- Set — an ASGI middleware rejects (403) any connection whose peer address is not in the
  list. Entries are IPs or CIDR networks (`ipaddress` stdlib parsing at config load). Applies
  to HTTP and WebSocket alike (pure ASGI middleware, not FastAPI HTTP-only middleware, so the
  `/api/ws` upgrade is covered).

The add-on's `run.sh` sets `HASSETTE__WEB_API__ALLOWED_CLIENT_IPS='["172.30.32.2","127.0.0.1"]'`
when the optional host port is unmapped (queried from `http://supervisor/addons/self/info`
via `hassio_api: true`), and leaves the field unset when the user maps the port. Loopback stays
allowed so in-container CLI use (`docker exec ... hassette status`) keeps working.

Non-goals: this is not authentication and must not be described as such — it is a network
allowlist that narrows the unauthenticated surface to the supervisor gateway. The real auth
layer remains the audit gap's follow-up
(`design/audits/2026-03-25-comprehensive-audit/web-frontend.md:178` — "without any rate
limiting, authentication, or CSRF protection").

## Files

- Modify `src/hassette/config/models.py` — `allowed_client_ips` field on `WebApiConfig` +
  parse/validate to `ipaddress` networks
- Create `src/hassette/web/middleware.py` — ASGI client-IP allowlist middleware (first
  middleware module; CORS stays where it is)
- Modify `src/hassette/web/app.py` — install the middleware when the field is set
- Modify `tests/integration/test_api.py` (or a sibling) — allowed IP passes, disallowed IP
  gets 403 on HTTP and on WS upgrade, `None` allows all
- Modify `docs/pages/` (web API configuration docs) — document the field and its add-on use
- Regenerate `hassette.schema.json` if applicable

## Acceptance criteria

- [ ] Default config: behavior unchanged (no middleware installed, zero overhead)
- [ ] With an allowlist: non-listed peers get 403 on REST and on the WS upgrade; listed peers
      are unaffected
- [ ] CIDR entries work (`172.30.32.0/23`)
- [ ] Invalid entries fail at config load with a clear message, not at request time
