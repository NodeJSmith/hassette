---
topic: "Serving an SPA under HA ingress and sub-path reverse proxies, with the base handled by the app"
date: 2026-10-11
status: Draft
---

# Prior Art: SPA base path under HA ingress and sub-path proxies

## The Problem

HA ingress serves an add-on at `/api/hassio_ingress/<token>/`, strips that prefix before proxying, and tells
the app the prefix in `X-Ingress-Path`. A generic reverse proxy can do the same at `/hassette/`. An SPA that
assumes `/` breaks on every absolute URL: API calls, the WebSocket, router paths, assets. The earlier survey
(`design/research/2026-10-10-ha-addon-conventions/`) settled that the app should handle this itself, behind a
peer guard. This one surveys the mechanics: which signal sets the base, how the browser learns it, how the
WebSocket and router derive from it, and what caching and logging go with it.

Raw findings, with file and line citations: `web-research-ha.md` (HA add-on apps, read from source) and
`web-research-generic.md` (header conventions, frameworks, `<base href>` pitfalls).

## How We Do It Today

The SPA hard-codes `/api`, `/api/ws`, and wouter's absolute routes; Vite builds with `base: "/"`; the backend's
`spa_catch_all` (`src/hassette/web/app.py`) serves `index.html` as a static file. Spec 130's draft ledger
(`design/specs/130-ingress-base-path/design.md`) proposes a per-request `<base href>` from a trusted header.

## Patterns Found

### Pattern 1: Server-rendered `<base href>` from the request header

**Used by**: ESPHome device-builder (backend and frontend). Grafana does the same from static config
(`<base href="[[.AppSubUrl]]/" />`).
**How it works**: `index.html` ships a `<base href>` placeholder. The SPA catch-all resolves the prefix
(`X-Ingress-Path`, then `X-Forwarded-Prefix`, then the request path minus the SPA tail), normalizes it to `/x/`
(collapsing `//evil.com`), `html.escape`s it, substitutes it, memoizes per distinct base, and sends
`Vary: X-Ingress-Path, X-Forwarded-Prefix`. The build uses a relative public path, so the entry script resolves
against `<base>` even on a deep route. The frontend computes `BASE_PATH` once at module load (from the entry
script URL) and builds router paths, fetch URLs and `${host}${BASE_PATH}ws` from it on a History-API router.
**Strengths**: no build-time prefix; one image serves any prefix; deep-link reload works; URLs stay readable.
**Weaknesses**: `#hash` links and SVG `url(#id)` resolve against `<base>`; the shell must not be cached across
prefixes; asset-extension paths must 404 rather than fall back to HTML. Device-builder sets `no-cache` on the
shell only in dev mode.
**Example**: `esphome/device-builder` `device_builder.py` (~L124-211); `esphome/device-builder-frontend`
`src/util/base-path.ts` (L15-58).

### Pattern 2: Fully relative build plus a hash router

**Used by**: zwave-js-ui, Zigbee2MQTT windfront, Music Assistant frontend; Node-RED (relative, no router).
**How it works**: Vite `base: "./"` (or `""`), a hash router so the server only ever serves `/`, and the API and
WebSocket URLs derived from `location.pathname`. The server 301s the mount point to a trailing slash (Z2M,
Node-RED) so relative URLs resolve. The app needs no header at all; Music Assistant never reads `X-Ingress-Path`.
**Strengths**: zero header trust and zero injection surface; reload is trivially correct.
**Weaknesses**: URLs become `/#/apps/foo`; lazy-loaded chunks and libraries with absolute asset paths break
(zwave-js-ui disables router lazy loading for this reason); needs the trailing-slash redirect.
**Example**: `Nerivec/zigbee2mqtt-windfront` `src/store.ts` L124-128; `zwave-js/zwave-js-ui` `src/App.vue` L1371-1377.

### Pattern 3: Trust-gated, allow-listed prefix header

**Used by**: Etherpad (`sanitizeProxyPath`), ASP.NET Core ForwardedHeaders (`KnownProxies`), Werkzeug
`ProxyFix(x_prefix=)` (hop count), Tailscale (honors the header only when running as an HA add-on).
**How it works**: the header is read only when a trusted proxy is known to be in front; the value is reduced
to an allow-listed charset (Etherpad: `[A-Za-z0-9\-_/.]`), leading `//` collapsed, `..` rejected, empty on
failure. Etherpad sets `Vary` on exactly the headers it consulted (cache-poisoning advisory GHSA-fjgc-3mj7-8rg8).
**Strengths**: one rule removes header injection and open redirect together.
**Weaknesses**: every surveyed project falls back silently; none logs a rejected header above DEBUG.
**Example**: `ether/etherpad` `src/node/utils/sanitizeProxyPath.ts` L37-63.

### Pattern 4: Base as a JS global (contrast)

**Used by**: Frigate (`window.baseUrl` via nginx `sub_filter`, built with `--base=/BASE_PATH/`), Double-take.
**How it works**: a script tag sets the global; `BrowserRouter basename` and the WebSocket read it.
**Weaknesses**: needs JS-in-HTML escaping both projects get wrong; Frigate's placeholder build and response
rewriting are the brittle approach the earlier survey already ruled out.

## Anti-Patterns

- **Raw header into HTML or JS.** Frigate interpolates `$http_x_ingress_path` unvalidated; Double-take's
  `JSON.stringify` in an inline script doesn't escape `</script>`. A forged `<base>` redirects every relative
  `<script src>`, so it is script injection.
- **Header in process-global state.** EOS writes the request's prefix into a module-global `ROOT_PATH`, leaking
  one request's prefix into the next.
- **Ungated header.** zwave-js-ui's `X-External-Path` redirect has no gate or validation; Babybuddy's docs warn
  `X-Ingress-Path` is forgeable when honored outside HA.
- **`#hash` links under `<base>`.** `<a href="#x">` resolves to `<base>#x` and navigates off the current route
  (MDN). This applies at base `/` too, on any non-root route.
- **File-derived validators on a rendered shell.** An `ETag`/`Last-Modified` from the file on disk lets a cache
  revalidate a shell rendered for another prefix.

## Relevance to Us

- **Spec 130 D1 (signals):** `X-Ingress-Path` first, then `X-Forwarded-Prefix`, is the device-builder order, and
  Etherpad and wyze-bridge read the same pair. `X-Forwarded-Prefix` is a de-facto convention (RFC 7239 has no
  prefix parameter), read by ASP.NET, Spring and Werkzeug, all off by default and gated. `X-External-Path` is
  zwave-js-ui-only and used for a redirect, so it isn't a convention to adopt. Our peer gate is stricter than
  device-builder's (which doesn't gate its browser site). The validation should follow Etherpad's shape.
- **D2 (frontend base):** device-builder derives the base from the entry script URL; with `<base href>` present,
  `document.baseURI` gives the same answer more directly. Both capture it once at load. The HA ecosystem's
  common alternative is a hash router (Pattern 2), which would change every UI URL.
- **D3 (Vite base):** `"./"` matches zwave-js-ui, windfront and Music Assistant, and our probe build.
- **D4 (injection):** device-builder uses a placeholder token in `<base href>`; a literal `<base href="/">`
  is the same mechanism with dev-server parity.
- **D5 (caching):** practice varies (device-builder: `Vary` only; Music Assistant: `no-cache`; Z2M: `no-store`);
  `no-cache` with `Vary` and no file-derived validator covers both failure modes.
- **D6 (logging):** no surveyed project logs a rejected base header above DEBUG. A WARNING would diverge from
  practice; the argument for it is that a rejected `X-Ingress-Path` means a blank ingress panel.
- **New:** our skip link (`href="#main-content"` in `frontend/src/app.tsx`) is exactly the `#hash` pitfall. No
  inline SVG `url(#id)` references exist in `frontend/src`.

## Recommendation

Pattern 1 with Pattern 3's gate and validation: server-rendered `<base href>` from `X-Ingress-Path`, then
`X-Forwarded-Prefix`, honored only from `trusted_proxies` peers and allow-list validated; frontend reads the base
once and builds router, fetch and WebSocket URLs from it; Vite `base: "./"`; `no-cache` + `Vary` on the shell;
fix in-page anchors. Pattern 2 (hash router) is the HA-ecosystem majority but trades away readable, shareable
URLs to avoid trust work we already have.

Coverage gaps: Traefik's StripPrefix setting `X-Forwarded-Prefix` is reported but wasn't verified against the
live docs; Mealie, AdGuard Home, Portainer and Paperless-ngx weren't confirmed; GitHub code search hit its rate
limit, so the list of `X-Ingress-Path` readers is a sample.

## Sources

URLs were not live-verified beyond the source reads noted in the raw files.

### Reference implementations
- https://github.com/esphome/device-builder — `<base href>` placeholder, header precedence, `Vary`
- https://github.com/esphome/device-builder-frontend — `base-path.ts`, WS URL from base
- https://github.com/zwave-js/zwave-js-ui — relative build, hash router, `X-External-Path` redirect
- https://github.com/Koenkk/zigbee2mqtt — `frontend.base_url`, trailing-slash 301, `no-store` on HTML
- https://github.com/Nerivec/zigbee2mqtt-windfront — `base: ""`, HashRouter, pathname-derived WS
- https://github.com/music-assistant/server and https://github.com/music-assistant/frontend — separate ingress listener, relative build
- https://github.com/node-red/node-red — relative editor, pathname-derived WS
- https://github.com/blakeblackshear/frigate — placeholder build + `sub_filter` (contrast)
- https://github.com/ether/etherpad — `sanitizeProxyPath`
- https://github.com/home-assistant/core/blob/dev/homeassistant/components/hassio/ingress.py — `X-Ingress-Path` minted by core
- https://github.com/grafana/grafana — `<base href="[[.AppSubUrl]]/" />`
- Tailscale, Double-take, docker-wyze-bridge, EOS, Babybuddy, OpenCCU — see `web-research-ha.md`

### Documentation & standards
- https://developers.home-assistant.io/docs/add-ons/presentation/#ingress
- RFC 7239 (`Forwarded`: `by`, `for`, `host`, `proto` only)
- ASP.NET Core ForwardedHeaders, Spring ForwardedHeaderFilter, Werkzeug ProxyFix, FastAPI "Behind a Proxy" — see `web-research-generic.md`
- MDN `<base>` (placement, `#hash` resolution)
