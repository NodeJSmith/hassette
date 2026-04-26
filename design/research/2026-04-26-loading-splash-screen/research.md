---
topic: "loading splash screen during slow startup"
date: 2026-04-26
status: Draft
---

# Prior Art: Loading Splash Screen During Slow Startup

## The Problem

Self-hosted web applications with multi-service architectures often take several seconds (or more) to fully initialize — connecting to external systems, loading plugins, running migrations, warming caches. During this period, users who navigate to the UI see either a browser connection error, a blank page, or a broken interface with failing API calls. This creates a poor first impression and makes it impossible to distinguish "still loading" from "crashed."

The challenge is serving a useful response as early as possible — ideally from the moment the container starts — while the real application initializes in the background.

## How We Do It Today

We don't have a splash screen. The current startup sequence initializes all services (database, event bus, scheduler, HA WebSocket, app handler) before WebApiService starts uvicorn on port 8126. During this time, the port is not listening — browsers get "connection refused." Once uvicorn starts, the SPA renders immediately but API calls may fail or return incomplete data while late-initializing services finish. The health endpoint (`GET /api/health`) returns 503 when not fully ready, but there's no user-facing indication of startup progress.

## Patterns Found

### Pattern 1: Inline HTML Splash Screen (Client-Side)

**Used by**: Home Assistant, Grafana, Portainer, most modern SPAs
**How it works**: A full-viewport splash screen (logo, spinner, loading message) is embedded directly in the server-rendered HTML using only inline HTML and CSS — no JavaScript required to display. The splash sits outside (or above) the SPA root element. When the SPA bundle loads, mounts, and establishes its backend connection, it removes or fades the splash.

Home Assistant's implementation is the canonical ecosystem example: `#ha-launch-screen` is a fixed-position div with flexbox centering, dark mode support via `@media (prefers-color-scheme: dark)`, and CSS `view-transition-name` for animated removal. Visible within milliseconds of the browser receiving HTML.

**Strengths**: Instant display, no network round-trips beyond initial HTML. Works offline. No server-side state needed. Users see branded content immediately.
**Weaknesses**: Only covers the frontend-boot gap, not the backend-readiness gap. If the backend is slow, the splash may hang indefinitely unless paired with a readiness check. Does nothing when the port isn't even listening yet.
**Example**: https://github.com/home-assistant/frontend/blob/dev/src/html/index.html.template

### Pattern 2: Readiness Middleware with Flag (Fast Lifespan + Background Init)

**Used by**: Kubernetes-deployed FastAPI/Flask apps, microservices architectures
**How it works**: The ASGI lifespan completes quickly — it only sets up a readiness flag (`app.state.ready = False`) and spawns a background `asyncio.Task` that performs the slow initialization. A middleware checks the flag on every request: if not ready, it serves an HTML splash page (for browsers) or a JSON 503 (for API/health clients). Once the background task completes, it flips the flag and the middleware passes requests through.

The splash page served by the middleware includes an inline script that polls `/api/health` on an interval (e.g., every 2s with exponential backoff). When the endpoint returns 200, the page auto-reloads to show the real app.

**Strengths**: Single-process, no external dependencies. Works with any proxy/Docker setup. Health endpoint serves double duty for Docker HEALTHCHECK and browser polling. Can serve partial readiness ("connecting to HA..." → "loading apps...").
**Weaknesses**: Requires restructuring initialization into a background task (lifespan must be fast). Every request pays middleware overhead (negligible — boolean check). Splash page must include its own polling logic.
**Example**: Community pattern from FastAPI discussions — https://github.com/fastapi/fastapi/discussions/7242 (conceptual; no canonical implementation)

### Pattern 3: Two-Phase Server Startup (Router Swap)

**Used by**: Gitea
**How it works**: The application starts with a minimal, fast-initializing HTTP server serving only splash + health routes. Heavy initialization runs concurrently. Once complete, the server swaps to the full route table. Gitea's implementation uses separate router modules (`routers/install/` vs `routers/web/`) with a clean architectural boundary.

For ASGI, this means starting uvicorn with a minimal Starlette app, running heavy init in a background task, then swapping the ASGI app or mounted routes when ready. Starlette's `Router` and route mounting could support this.

**Strengths**: Server responds to HTTP immediately. Health checks work from the start. Clean separation of pre-ready and post-ready routes.
**Weaknesses**: Requires careful app-swapping logic. Starlette doesn't natively support hot-swapping. Race conditions possible during the swap. More complex than a middleware flag.
**Example**: https://github.com/go-gitea/gitea/pull/13195

### Pattern 4: Reverse Proxy Error Page

**Used by**: Production deployments behind nginx, Caddy, Traefik
**How it works**: The reverse proxy serves a custom HTML splash page when the backend returns 502 (connection refused) or 503 (not ready). The backend starts normally. The splash page includes JavaScript that polls the backend and auto-redirects when ready.

**Strengths**: Zero application code changes. Works with any backend. Battle-tested.
**Weaknesses**: Requires a reverse proxy (not always present in HA add-on or simple Docker setups). Configuration is environment-specific. Users running Hassette directly don't benefit.
**Example**: https://www.tekovic.com/blog/nginx-maintenance-page-with-503-http-status-code/

### Pattern 5: SPA Polling with Progressive Status

**Used by**: GitLab (migration progress), Discourse (rebuild progress), modern dashboards
**How it works**: The SPA's initial HTML includes a splash screen (Pattern 1). Bootstrap code immediately polls a status endpoint returning structured data (`{"status": "starting", "phase": "connecting_to_ha", "progress": 0.3}`). The splash updates its message and progress indicator. When status returns "ready," the splash transitions to the full app.

Polling uses exponential backoff (500ms → 5s cap) with a maximum retry count or timeout. If the backend is unreachable, the splash shows a connection error with retry indication.

**Strengths**: Excellent UX — users see progress, not just a spinner. Handles both "starting" and "unreachable" cases. Different messages per initialization phase.
**Weaknesses**: Requires a status endpoint that works before full initialization (needs Pattern 2 or 3). More complex frontend code.
**Example**: [no source found] — composite pattern, no single canonical implementation

## Anti-Patterns

- **Infinite loading without timeout**: Portainer's splash waits forever with no error state (https://github.com/portainer/portainer/issues/12620). Users can't distinguish "loading" from "crashed." Always include a timeout, error message, and link to logs.
- **Blocking lifespan with slow initialization**: If ASGI lifespan takes 30+ seconds, uvicorn can't accept TCP connections, health checks fail, Docker restarts the container in a loop. Keep lifespan fast.
- **Fixed-duration `setTimeout` splash**: Hiding the splash after a hardcoded delay (e.g., 5 seconds) means it disappears too early or too late. Always tie removal to an actual readiness signal.
- **Separate splash server process on the same port**: Starting a `python -m http.server` then killing it and starting the real app creates a gap where no server is listening. Fragile and unnecessary when middleware can do the same thing in-process.

## Relevance to Us

**Critical constraint**: Starlette's lifespan blocks ALL TCP connections until it completes. Hassette currently does all service initialization before uvicorn starts accepting requests. This means the port isn't even listening during the slowest part of startup — browsers get "connection refused," and Docker HEALTHCHECK failures can trigger container restarts.

**What fits well**: Pattern 2 (readiness middleware) is the best architectural fit. Hassette already has a service-based startup with dependency ordering and a health endpoint. The change would be: (1) make the ASGI lifespan fast by spawning service initialization as a background task, (2) add a middleware that serves an HTML splash page until services are ready, (3) keep the existing `/api/health` endpoint but make it available immediately (returning 503 during startup). Pattern 1 (inline HTML splash) is complementary for the frontend-boot gap after the server is ready but before the SPA renders.

**What requires significant change**: The service initialization sequence currently blocks the event loop until completion (`run_forever()` → start services → start uvicorn). Refactoring to "start uvicorn first, init services in background" inverts the startup order. The `WebApiService` currently depends on `RuntimeQueryService` and `TelemetryQueryService` being ready — those dependencies would need to become eventually-consistent rather than guaranteed-at-startup.

**What doesn't fit**: Pattern 4 (reverse proxy) is environment-dependent and can't be relied on for all users. Pattern 3 (router swap) adds complexity without clear benefit over Pattern 2's simpler middleware approach.

## Recommendation

**Combine Pattern 2 (readiness middleware) + Pattern 1 (inline HTML splash) + Pattern 5 (progressive status)**:

1. **Restructure startup**: Make ASGI lifespan fast. Start uvicorn immediately. Spawn service initialization as a background `asyncio.Task`. This is the hardest part and the core architectural change.
2. **Add readiness middleware**: Intercept all requests when `app.state.ready == False`. Serve an HTML splash page for browser requests (with inline CSS + polling JS). Return 503 for API/health requests.
3. **Add a startup status endpoint**: Extend `/api/health` (or add `/api/startup-status`) to return structured progress data — which services are ready, which are pending, current phase. Available immediately since uvicorn is listening.
4. **Inline HTML splash in index.html**: Add an HA-style `#launch-screen` element with inline CSS that covers the SPA root. The Preact app removes it on mount + successful WebSocket connection. This handles the secondary gap (server ready, SPA still loading).

This combination covers the full timeline: Docker starts → uvicorn listens → splash served with progress → services ready → SPA loads → splash removed.

The HA add-on Supervisor may also benefit from the earlier health endpoint availability, since it can detect "starting" vs "crashed" sooner.

## Sources

### Reference implementations
- https://github.com/home-assistant/frontend/blob/dev/src/html/index.html.template — HA's inline launch screen
- https://github.com/go-gitea/gitea/pull/13195 — Gitea's two-phase router separation
- https://github.com/portainer/portainer/issues/12620 — Portainer's infinite-loading anti-pattern

### Blog posts & writeups
- https://medium.com/@dynamicy/fastapi-starlette-lifecycle-guide-startup-order-pitfalls-best-practices-and-a-production-ready-53e29dcb9249 — Starlette lifecycle guide
- https://medium.com/@jtc.21.am/readiness-vs-liveness-and-startup-probes-a-python-developers-guide-to-healthy-services-91fff180f258 — Readiness vs liveness probes
- https://www.tekovic.com/blog/nginx-maintenance-page-with-503-http-status-code/ — Nginx maintenance page
- https://last9.io/blog/docker-compose-health-checks/ — Docker Compose health checks
- https://dev.to/amjadmh73/splash-screen-for-your-spa-2h9k — SPA splash screen pattern

### Documentation & standards
- https://starlette.dev/lifespan/ — Starlette lifespan protocol
- https://developers.home-assistant.io/docs/frontend/architecture/ — HA frontend architecture
- https://docs.aiohttp.org/en/stable/web_advanced.html — aiohttp background tasks pattern

### Community discussions
- https://github.com/fastapi/fastapi/discussions/7242 — FastAPI health probes
- https://github.com/Kludex/starlette/discussions/2582 — Starlette lifespan improvements
