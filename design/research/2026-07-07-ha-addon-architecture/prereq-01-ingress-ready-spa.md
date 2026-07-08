# Prereq 01 — Ingress-Ready SPA (Base-Path Support)

**Repo:** hassette
**Depends on:** nothing
**Size:** large (the epic's biggest single work item)
**Also benefits:** reverse-proxy deployments (`location /hassette/ { proxy_pass ... }`), which
have the same served-under-a-prefix shape as ingress.

## Problem

Under ingress the browser loads the SPA at `/api/hassio_ingress/<token>/`, but every URL the
frontend emits assumes it lives at `/`:

| Absolute-path assumption | Location |
|---|---|
| Vite `base` defaults to `/` → `/assets/...`, `/fonts/...` refs in built HTML/JS | `frontend/vite.config.ts` (no `base` set) |
| `BASE_URL = "/api"` | `frontend/src/api/client.ts:3` |
| `WS_PATH = "/api/ws"` + `location.host` | `frontend/src/api/endpoints.ts:29`, `frontend/src/hooks/use-websocket.ts:42-43` |
| `wouter` history routing, absolute routes (`/apps`, `/handlers`, ...) | `frontend/src/app.tsx:115-151` |
| Absolute icon/script refs | `frontend/index.html:7,11` |

Backend routes do **not** change: the supervisor strips the ingress prefix before forwarding,
so hassette keeps serving `/api/...`, `/assets/...`, `/fonts/...` exactly as today. The
external prefix arrives per-request in the `X-Ingress-Path` header and is only needed for URL
*generation*.

## Design (T3 in the research brief)

1. **Backend — `<base href>` injection.** `src/hassette/web/app.py` currently returns
   `index.html` as a static file from the catch-all route. Change: read `index.html` once at
   startup, and on each SPA-serving response inject
   `<base href="{x_ingress_path}/">` into `<head>` (empty header → `<base href="/">`).
   This is string substitution against a placeholder comment in `index.html`, not a template
   engine.
2. **Vite — relative asset refs.** Set `base: "./"` in `frontend/vite.config.ts` so built
   asset URLs are relative and resolve against the injected `<base>` (not against the current
   SPA route — that is exactly what `<base>` exists for). Make `index.html` refs relative to
   match.
3. **Frontend — derive from `document.baseURI`.** One tiny module (e.g.
   `frontend/src/api/base.ts`) exports the resolved base path. Consumers:
   - `client.ts`: `BASE_URL = new URL("api", document.baseURI)`-style construction
   - `use-websocket.ts`: build the WS URL from `document.baseURI` with the `http(s) → ws(s)`
     protocol swap, replacing the `location.host + WS_PATH` construction
   - `app.tsx`: `<Router base={basePath}>` (wouter supports a base prop; internal `<Link>`s
     and routes stay as written)
4. **Direct-port path unchanged.** No header → base `/` → behavior identical to today. The
   Vite dev server (which serves its own `index.html` without the injection) needs the
   placeholder handled — dev falls back to `/` naturally since Vite serves at root with the
   existing `/api` proxy.

## Files

- Modify `frontend/vite.config.ts` — `base: "./"`
- Modify `frontend/index.html` — relative refs + base-injection placeholder
- Create `frontend/src/api/base.ts` — base-path resolution from `document.baseURI`
- Modify `frontend/src/api/client.ts` — derive `BASE_URL`
- Modify `frontend/src/api/endpoints.ts` — `WS_PATH` becomes relative or moves into `base.ts`
- Modify `frontend/src/hooks/use-websocket.ts` — WS URL from base
- Modify `frontend/src/app.tsx` — `<Router base=...>`
- Modify `src/hassette/web/app.py` — index.html base injection in the SPA catch-all
- Modify `tests/` — integration test: request `/` with and without `X-Ingress-Path`, assert
  the injected `<base href>`; frontend unit tests for `base.ts` resolution
- Modify `tests/e2e/` — one e2e that serves the app under a path prefix (reverse-proxy
  fixture) and verifies navigation + API + WS connect (stretch; the integration test is the
  floor)

## Acceptance criteria

- [ ] Built SPA works served at `/` (today's deployments — zero visual/behavioral change)
- [ ] Built SPA works served under an arbitrary prefix when `X-Ingress-Path` is present:
      assets load, client-side routes navigate and deep-link, REST calls and the WS connect
      through the prefix
- [ ] Vite dev server (`npm run dev`) still works with the `/api` proxy
- [ ] No hardcoded `"/api"` or `"/assets"` URL construction remains in `frontend/src`
