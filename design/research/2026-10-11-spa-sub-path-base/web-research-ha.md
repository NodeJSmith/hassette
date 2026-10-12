# Prior art: app-side ingress base path for SPA add-ons (HA ingress + generic sub-path proxies)

All source read from default branches via `gh api repos/<o>/<r>/contents/<path>` on 2026-10-11. Line numbers are against those heads and may drift. Not examined: legacy `esphome/dashboard` (superseded by device-builder), `nurikk/zigbee2mqtt-frontend` (old Z2M frontend; no matching files found).

## Sources Found

### ESPHome Device Builder backend (closest match to the target design)
- **URL**: https://github.com/esphome/device-builder/blob/main/esphome_device_builder/device_builder.py (also `helpers/auth.py`, `constants.py`)
- **Type**: reference implementation
- **Key takeaway**: `index.html` carries a literal `<base href="__ESPHOME_BASE_HREF__">` placeholder (`_BASE_HREF_PLACEHOLDER`, ~L128). `_resolve_base_href` (~L142-193) picks `X-Ingress-Path`, else `X-Forwarded-Prefix`, else the request path minus the matched SPA tail, then `strip("/")` and re-wraps as `/{x}/` so `//evil.com` collapses to an on-origin path. The result is `html.escape(..., quote=True)`-ed (~L1197), rendered through an `lru_cache(maxsize=8)` keyed by base (~L1187), and sent with `Vary: X-Ingress-Path, X-Forwarded-Prefix` (~L1210).
- **Relevance**: Nearly the exact mechanic we want. It is a runtime `<base>` injection, so it needs no build-time prefix.

### ESPHome Device Builder frontend
- **URL**: https://github.com/esphome/device-builder-frontend (`src/util/base-path.ts`, `public/index.html`, `build-scripts/rspack.cjs`, `src/api/esphome-api.ts`, `src/components/app-shell/router.ts`)
- **Type**: reference implementation
- **Key takeaway**: `base-path.ts` L15-34 computes `BASE_PATH` once at module load from `document.currentScript.src`'s directory (falling back to `location.pathname`). It is deliberately captured before any `pushState`, so deep-link reload works. `withBase()`/`stripBase()` (L41-58) prefix and strip it. rspack uses `publicPath: "auto"` (rspack.cjs ~L226). The WebSocket URL is `${proto}//${location.host}${BASE_PATH}ws` (`esphome-api.ts` ~L282). Routes are declared as `withBase("/secrets")` etc. on the History API, not a hash router.
- **Relevance**: Shows the browser half of the `<base>` pattern. The backend's `<base>` makes the entry script URL resolve to the deployment root, and the frontend derives everything else from that script URL.

### Home Assistant core ingress proxy
- **URL**: https://github.com/home-assistant/core/blob/dev/homeassistant/components/hassio/ingress.py (`_init_header`, ~L266-275); docs https://developers.home-assistant.io/docs/add-ons/presentation/#ingress
- **Type**: reference implementation / documentation
- **Key takeaway**: Core copies the request headers into a `CIMultiDict`, then assigns `headers["X-Ingress-Path"] = f"/api/hassio_ingress/{token}"`. That assignment replaces any client-supplied value, so on the ingress path the header is always server-minted. Forgery only matters if the app's port is reachable another way (LAN/direct).
- **Relevance**: Justifies the peer guard. The header is trustworthy only when the TCP peer is the Supervisor (172.30.32.2).

### zwave-js-ui
- **URL**: https://github.com/zwave-js/zwave-js-ui (`api/app.ts` L621-642, `api/config/app.ts` L87, `src/router/index.js` L1/L40-41, `src/App.vue` L1371-1377, `src/apis/ConfigApis.js` L9, `vite.config.mjs` L50, `docs/usage/reverse-proxy.md`)
- **Type**: reference implementation
- **Key takeaway**: Almost purely relative. Vite `base: './'`, `createWebHashHistory()` with a comment "DON'T use lazy loading here, it would break application running behind a proxy" (router L3), axios `baseURL = './api'`, and `io('/', {path: location.pathname + 'socket.io'})`. The server reads `X-External-Path` in exactly one place: a legacy redirect from old history-mode paths to `${path}/#${originalUrl}` (`app.ts` L634), with no validation. `express.static` serves `dist/` with defaults, no explicit Cache-Control.
- **Relevance**: The "relative-only plus hash router" extreme. The server needs no base knowledge for the UI to work; the header is only an optional convenience.

### Zigbee2MQTT backend and windfront frontend
- **URL**: https://github.com/Koenkk/zigbee2mqtt/blob/master/lib/extension/frontend.ts ; https://github.com/Nerivec/zigbee2mqtt-windfront (`vite.config.mts`, `src/Main.tsx`, `src/store.ts` L124-128, `src/websocket/WebSocketManager.ts` L242-253); add-on https://github.com/zigbee2mqtt/hassio-zigbee2mqtt
- **Type**: reference implementation
- **Key takeaway**: Backend base is static config `frontend.base_url` (`frontend.ts` L41): it serves files under `posix.relative(baseUrl, url)`, 404s anything outside it (L74-81), 301-redirects the bare base to its trailing-slash form (L83-90) so relative assets resolve, and mounts the WS at `posix.join(baseUrl, "api")` (L48/L123). `util/staticFileServer.ts` L46-49 sets `Cache-Control: no-store` on `text/html`. Windfront uses `vite base: ""`, `<HashRouter>`, and the WS URL `host + location.pathname (+"/") + "api"`. The add-on (`ingress: true`) points Supervisor straight at the frontend port with no `base_url`, relying purely on relative paths.
- **Relevance**: Confirms relative assets + hash router + pathname-derived WS URL, and that the trailing-slash redirect is load-bearing.

### Music Assistant (server + frontend)
- **URL**: https://github.com/music-assistant/server (`controllers/webserver/controller.py`, `helpers/webserver.py` L153-164/L221, `helpers/auth_middleware.py` L504-548); https://github.com/music-assistant/frontend (`vite.config.ts` L13, `src/plugins/router.ts` L705-708, `src/helpers/ingress.ts`, `src/views/Login.vue` ~L540)
- **Type**: reference implementation
- **Key takeaway**: Never reads `X-Ingress-Path` for the UI. Vite `base: "./"`, `createWebHashHistory()` (a custom HA-panel history only when framed by `ha-panel-app`). It detects ingress client-side via `location.pathname.includes("/hassio_ingress/")`. API base is `location.origin + location.pathname.replace(/\/$/, "")` and the WS is that plus `/ws` (`plugins/api/index.ts` ~L222-230). Server side, a second `web.TCPSite` bound only to the 172.30.32.x:8094 address is the ingress listener. `is_request_from_ingress` checks the socket's own `sockname == ingress_site`, and `is_request_from_ingress_proxy` additionally requires `peername[0] == HASSIO_SUPERVISOR_IP`. `serve_static` sends `Cache-Control: no-cache` for all frontend files including index.
- **Relevance**: Best reference for trust-gating: bind-address check plus peer check, in addition to header trust. Also hash routing, so deep-link reload needs no server fallback.

### Node-RED editor
- **URL**: https://github.com/node-red/node-red (`editor-client/src/js/comms.js` L38-71, `settings.js` L110-112, `editor-api/lib/editor/ui.js` L45-48)
- **Type**: reference implementation
- **Key takeaway**: All editor URLs are relative. The WS is `ws(s)://host:port + document.location.pathname + (trailing "/") + "comms"` (comms.js L49-56). The server 301-redirects `/admin` to `/admin/` (ui.js L45-48). `apiRootUrl` is an optional override. No header involved; no HA-specific handling.
- **Relevance**: Same relative + pathname-derived WS model, with the trailing-slash 301 as a prerequisite.

### Frigate (contrast)
- **URL**: https://github.com/blakeblackshear/frigate (`web/package.json` L9, `docker/main/rootfs/usr/local/nginx/conf/nginx.conf` ~L361-378, `web/src/api/baseUrl.ts`, `web/src/App.tsx` L47, `docker/main/Dockerfile` L366-369)
- **Type**: reference implementation (the pattern to avoid)
- **Key takeaway**: Built with `vite build --base=/BASE_PATH/`, then nginx `sub_filter` rewrites `/BASE_PATH/` to `$http_x_ingress_path/` across HTML/JS/CSS/JSON and injects `<script>window.baseUrl="$http_x_ingress_path/";</script>`. Router is `BrowserRouter basename={window.baseUrl}`; the WS is `baseUrl` with `http` replaced by `ws`, plus `ws`. The header is spliced into responses unvalidated.
- **Relevance**: Confirms the already-decided "app-side beats sub_filter": it needs a placeholder build, a minified-JS match string (`return\`/BASE_PATH/\``), and unescaped header interpolation.

### Etherpad `sanitizeProxyPath`
- **URL**: https://github.com/ether/etherpad/blob/develop/src/node/utils/sanitizeProxyPath.ts ; call sites `src/node/hooks/express/specialpages.ts` L34-41, L190
- **Type**: reference implementation
- **Key takeaway**: Priority `x-proxy-path` (always honored), then `x-forwarded-prefix` and `x-ingress-path`, which are honored only when `settings.trustProxy === true`. The cleaner strips everything outside `[A-Za-z0-9\-_/.]`, collapses a leading `//+` to `/`, prepends `/`, and returns `""` on any `..` segment. Responses set `Vary` on exactly the headers consulted, to prevent cache poisoning (references GHSA-fjgc-3mj7-8rg8).
- **Relevance**: The most thorough validation and trust-gating of any app that reads `X-Ingress-Path`. Good model for a regex and rejection rule.

### Other `X-Ingress-Path` readers
- **URL**: https://github.com/tailscale/tailscale/blob/main/client/web/web.go L915-919 ; https://github.com/jakowenko/double-take/blob/master/api/src/app.js L21-39 ; https://github.com/mrlt8/docker-wyze-bridge/blob/main/app/wyzebridge/web_ui.py L38-44 ; https://github.com/Akkudoktor-EOS/EOS/blob/main/src/akkudoktoreos/server/dash/context.py L29-98 ; https://github.com/babybuddy/babybuddy/blob/master/docs/configuration/homeassistant.md ; https://github.com/OpenCCU/OpenCCU/blob/master/home-assistant-addon-proxy/ha-proxy.js.gtpl L42-45, L74
- **Type**: reference implementations / documentation
- **Key takeaway**:
  - Tailscale: trusts the header only when `hostinfo.GetEnvType() == HomeAssistantAddOn` and no static prefix is set. The value goes into the `/api/data` JSON as `URLPrefix`, not into HTML.
  - Double-take: injects `window.ingressUrl = JSON.stringify(header)` into `</head>`.
  - Wyze-bridge: `url_for` wrapper prepends `X-Ingress-Path or X-Forwarded-Prefix`, `rstrip("/")`.
  - EOS: stores the header into a module-global `ROOT_PATH` and the ASGI `root_path`, unvalidated.
  - Babybuddy: an explicit opt-in setting, and the docs warn that attackers can forge `X-Ingress-Path` if it is enabled outside HA.
  - OpenCCU: uses it only as a cookie `Path=` after a `startsWith('/')` check.
- **Relevance**: Spread of trust-gating (env detection, opt-in flag, none) and sinks (JSON, inline script, cookie, ASGI root_path).

## Per-project matrix

| Project | (1) Signal / trust | (2) Browser learns base; deep-link reload | (3) Build-time asset base | (4) WS URL / router base | (5) index.html caching; rejection logging |
|---|---|---|---|---|---|
| ESPHome device-builder | `X-Ingress-Path` > `X-Forwarded-Prefix` > request path minus SPA tail. Header not peer-gated on the browser site, but the ingress site is peer-guarded (loopback/172.30.32.2 allowlist, binds 127.0.0.1 + 172.30.32.1 only). Normalized to `/x/`, `html.escape`d. | Server-injected `<base href>`; JS also derives `BASE_PATH` from entry-script URL. Deep link works: SPA fallback renders shell with `<base>`; asset-extension paths 404 instead of falling back to HTML. | Relative entry script, rspack `publicPath: "auto"`. Placeholder substituted at serve time, not build. | WS `host + BASE_PATH + "ws"`. History-API router, routes via `withBase()`. | Shell: `Vary: X-Ingress-Path, X-Forwarded-Prefix`; `no-cache` only in dev_mode, none in prod (code at `shell_headers`). Hashed bundles immutable. Peer-guard rejections logged at DEBUG; header never rejected, only normalized. |
| zwave-js-ui | `X-External-Path` (redirect only), `BASE_PATH` env/config `base`. No trust gate or validation. | Relative-only; hash router; reload hits `/` so no fallback needed. | Vite `base: './'` | WS `io('/', {path: location.pathname + 'socket.io'})`; `createWebHashHistory()`; axios `./api` | `express.static` defaults, no explicit header; no logging. |
| Zigbee2MQTT + windfront | Static `frontend.base_url`. HA add-on uses none. | Relative; trailing-slash 301 from backend; hash router. | Vite `base: ""` | WS `host + pathname + "api"`; HashRouter | `Cache-Control: no-store` on all `text/html`; unmatched URLs 404 via `sendNotFound`. |
| Music Assistant | None for UI. Ingress identified by bind socket + peer 172.30.32.2 (separate listener on 172.30.32.x:8094). | Relative; hash router; client checks `pathname.includes("/hassio_ingress/")`. | Vite `base: "./"` | WS `origin + pathname(rstrip /) + "/ws"`; hash router | `Cache-Control: no-cache` via `serve_static`. |
| Node-RED | None; all-relative. | Relative; server 301s to trailing slash. | n/a (static relative) | WS `host + document.location.pathname + "comms"` | `express.static` defaults. |
| Frigate | `X-Ingress-Path` set by Frigate's own nginx for its `base_path`, or HA's, interpolated by `sub_filter` raw. | Injected `window.baseUrl` via sub_filter; nginx `try_files ... /index.html` | Vite `--base=/BASE_PATH/` placeholder | WS from `window.baseUrl`; `BrowserRouter basename={window.baseUrl}` | nginx-level; no validation to log. |
| Etherpad | `x-proxy-path` always; `x-forwarded-prefix`/`x-ingress-path` only with `trustProxy`. Sanitized by whitelist regex; `..` rejected. | Server-rendered into templates | n/a (templated) | n/a | `res.vary(...)` on consulted headers. Silent drop on invalid. |
| Tailscale | `X-Ingress-Path` only if env type == HA add-on. | JSON field `URLPrefix` from `/api/data` | n/a | App uses prefix for navigation | n/a |

## Patterns Found

### Pattern 1: Server-rendered `<base href>` from the request header (placeholder in index.html)
**Used by**: ESPHome device-builder (+ frontend).
**How it works**: `index.html` ships `<base href="__PLACEHOLDER__">`. A catch-all handler resolves a prefix from headers (or request path minus matched tail), normalizes to `/x/`, escapes it, substitutes it, and memoizes per distinct value. The frontend's entry script is relative, so under `<base>` it resolves to the deployment root even when the browser URL is a deep route. The JS also derives `BASE_PATH` from the entry script URL once at load for router, WS, and fetch.
**Strengths**: No build-time prefix, one source of truth (the server), works under HA ingress and arbitrary sub-path proxies, deep-link reload works, small cache keyed by base.
**Weaknesses**: Needs `Vary` on the consulted headers and a no-cache policy on the shell (device-builder only sets no-cache in dev mode). Static assets requested as `/device/app.js` must 404 rather than fall back to HTML. Header trust is a separate concern.
**Example**: `device_builder.py` L124-139, L142-193, L1187-1211; `base-path.ts` L15-58; `public/index.html` L107-131.

### Pattern 2: Fully relative assets + hash router (no server base knowledge)
**Used by**: zwave-js-ui, Zigbee2MQTT windfront, Music Assistant, Node-RED (relative, not hash).
**How it works**: Vite `base: './'` or `""`, hash-based router so the server only ever serves `/`, and the WS URL / API base derived from `location.pathname`. Server guarantees a trailing slash on the mount point by 301.
**Strengths**: Zero header trust, zero injection surface; deep-link "reload" is trivially correct because the path never changes.
**Weaknesses**: Needs the trailing slash redirect (Z2M L83-90, Node-RED ui.js L45-48) or relative URLs resolve against the parent. Lazy-loaded chunks and absolute-path asset references are fragile (zwave-js-ui disables lazy loading in its router; ZwaveGraph.vue inlines a data URI because vis-network ignored the prefix, issue zwave-js-ui#3492). History-mode URLs for users and docs are lost.
**Example**: `zwave-js-ui/src/App.vue` L1371-1377; `zigbee2mqtt-windfront/src/store.ts` L124-128.

### Pattern 3: Trust-gated, whitelist-sanitized prefix header
**Used by**: Etherpad (`sanitizeProxyPath`), Tailscale (env gate), Music Assistant (bind + peer gate), device-builder (peer guard on the ingress site), Babybuddy (opt-in flag).
**How it works**: Only read the header when the deployment is known to put a trusted proxy in front (setting, env detection, or a dedicated listener plus peer-IP allowlist); then strip to `[A-Za-z0-9\-_/.]`, collapse leading `//`, reject `..`, and return empty on failure so the caller falls back to the request path.
**Strengths**: Header is woven into HTML/JS/Location, so a whitelist removes injection and open-redirect classes together.
**Weaknesses**: Silent fallback hides misconfiguration. Only Etherpad (silent) and device-builder (DEBUG for peer rejections) do anything observable; nobody logs a malformed-but-present base header at WARNING [no source found for any project that does].
**Example**: `sanitizeProxyPath.ts` L37-44, L58-63.

### Pattern 4: Separate ingress listener bound to the Supervisor network
**Used by**: Music Assistant (172.30.32.x:8094), ESPHome device-builder (127.0.0.1 + 172.30.32.1, default port 8099).
**How it works**: A second site is bound only on the hassio bridge address; handlers check the socket's own `sockname` and/or the TCP `peername` against 172.30.32.2 before honoring `X-Remote-User-*` or skipping auth.
**Strengths**: Structural, not header-based; a LAN client cannot reach the no-auth site.
**Weaknesses**: Host-network add-ons must pick the bind address carefully (device-builder documents why it hardcodes the gateway).
**Example**: `auth_middleware.py` L504-548; `helpers/auth.py` L444-479.

### Pattern 5: Inject a JS global for the base
**Used by**: Frigate (`window.baseUrl`), Double-take (`window.ingressUrl`).
**How it works**: Server or nginx adds `<script>window.X = "<header>"</script>`; router `basename` and WS URL read it.
**Strengths**: Simple; works with `BrowserRouter` basename.
**Weaknesses**: Needs correct JS-in-HTML escaping; the shell must not be shared-cached across prefixes.

## Anti-Patterns

- **Raw header into HTML/JS**: Frigate's `sub_filter '<body>' '<body><script>window.baseUrl="$http_x_ingress_path/";</script>'` interpolates the header unvalidated. Double-take's `JSON.stringify(header)` in an inline `<script>` is not safe either, since `JSON.stringify` does not escape `</script>` or `<!--`. Escape `<` as `<` or whitelist the value.
- **Header stored in a module-global**: EOS `IngressMiddleware` writes `ROOT_PATH = ingress_path` from the request, which leaks one request's prefix into the next and is unvalidated.
- **Header trusted with no gate**: zwave-js-ui's `X-External-Path` redirect (`app.ts` L634) and Z2M-style direct exposure. Babybuddy's docs call out that `X-Ingress-Path` can be forged if honored off-HA.
- **SPA fallback for asset-extension paths**: returning `index.html` for `/device/app.<hash>.js` causes "Unexpected token '<'". device-builder 404s `_ASSET_EXTENSIONS` instead.
- **Computing the base from `location.pathname` after the router has started**: the pathname no longer reflects the mount point; device-builder captures it at module load from the script URL.
