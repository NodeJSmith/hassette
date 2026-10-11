# Design: Serve the web UI under a URL prefix

**Date:** 2026-10-11
**Status:** built
**Mode:** sketch

## Summary

Issue #2664. Home Assistant ingress serves the add-on UI at `/api/hassio_ingress/<token>/` (spec 129, D1).
The SPA assumes it lives at `/`, so under any prefix its API calls, WebSocket, login redirect, client-side
routes and asset URLs all miss. This change makes the backend emit a `<base href>` per request and makes every
frontend URL resolve against it.

Trust and validation start from spec 129 D1's `X-Ingress-Path` rule (trusted peer, ingress pattern, trailing `/`
appended, HTML-escaped). This ledger extends it with a second header and a precedence rule (D1) and amends its
fallback so a present-but-rejected header gets a diagnostic page instead of a `/` shell (D6).

Backend: `spa_catch_all` in `src/hassette/web/app.py` (today a `FileResponse` of `index.html`; it also serves
D6's diagnostic page), with the
base-href resolution beside the existing trusted-peer-then-header pattern (`should_set_secure_cookie_flag` in
`src/hassette/web/auth/session.py`, `is_trusted_peer` in `src/hassette/web/auth/trusted_proxies.py`).
Frontend: `frontend/src/api/client.ts` (`BASE_URL`, `postSession`), `frontend/src/api/endpoints.ts` (`WS_PATH`),
`frontend/src/hooks/use-websocket.ts` (`location.host` URL), `frontend/src/lib/query-client.ts`
(`window.location.assign(LOGIN_PATH)`), wouter routing in `frontend/src/app.tsx` (no `<Router>` today),
`frontend/vite.config.ts` (default `base`), `frontend/index.html`, and the skip link in `app.tsx` (D10). Prior
art for every decision: `design/research/2026-10-11-spa-sub-path-base/prior-art.md`. Tests: unit tests for the trust rule, a
frontend unit test per URL site, and an e2e test under a prefix. Docs: `docs/pages/web-ui/index.md`.

Out of scope: the FastAPI `/api/docs` page under a prefix (its `openapi_url` is absolute; nothing in the UI links
to it), and proxies that forward the prefix instead of stripping it.

## Decisions

### D1: Which request signals may set the base, beyond HA ingress?

**Deciding factor:** sub-path reverse proxies work (the benefit D1 in spec 129 claimed, and the issue's docs
criterion promises) without widening what an untrusted client can influence.

`X-Ingress-Path`'s pattern only admits `/api/hassio_ingress/<token>`, so a Traefik or nginx user serving hassette
at `/hassette/` gets base `/` and a broken UI. `X-Forwarded-Prefix` is the de-facto header for a stripped prefix
(RFC 7239 has none): Traefik's `StripPrefix` reportedly sets it, nginx sends it with one `proxy_set_header`
line, and ASP.NET, Spring and Werkzeug read it, off by default and gated. ESPHome device-builder, the closest HA
add-on to this design, reads `X-Ingress-Path` then `X-Forwarded-Prefix`, as do Etherpad and docker-wyze-bridge.
zwave-js-ui's `X-External-Path` is project-specific and only drives a redirect
(`design/research/2026-10-11-spa-sub-path-base/prior-art.md`). A `trusted_proxies` peer already bypasses
hassette auth (`resolve_auth_outcome`, `src/hassette/web/middleware.py`), so the proxies this would trust are the
same ones already trusted for more.

| | A: `X-Ingress-Path` only (spec 129 D1 as written) | B: A, plus `X-Forwarded-Prefix` from the same trusted peers | C: A, plus a static `web_api.base_path` setting |
|---|---|---|---|
| Sub-path reverse proxy | Not supported; docs say so | Works for a trusted proxy (the forward-auth setup `trusted_proxies` exists for) | Works for any proxy, including an untrusted one with token login |
| Convention | — | ESPHome device-builder, Etherpad, wyze-bridge; ASP.NET/Spring/Werkzeug | Grafana `root_url`, Sonarr `UrlBase`, Z2M `base_url` (non-add-on apps) |
| New public surface | None | One header, documented | A config field users must keep in sync with the proxy |
| Trust model | Unchanged | Unchanged: same peer gate, header ignored from anyone else (stricter than device-builder, which doesn't gate its browser site) | A static value, no header trust needed |
| Under HA ingress | — | `X-Ingress-Path` is always set by HA core (`~/source/core/homeassistant/components/hassio/ingress.py:275`) and wins, so a client-sent `X-Forwarded-Prefix` passed through by core can't override it | Unused by the add-on |
| Validation | Ratified pattern | Allow-list in Etherpad's shape: one or more `/<segment>`, segment `[A-Za-z0-9_-][A-Za-z0-9._~-]*` (so no empty segment, no leading `//`, no `.` or `..` segment), a trailing `/` stripped before matching and one appended after | Validated at config load |

The first D1 header present decides: a present-but-invalid `X-Ingress-Path` is rejected (D6) and
`X-Forwarded-Prefix` is not consulted. A header whose value is empty, whitespace-only or `/` counts as absent:
it is skipped without logging and precedence moves to the next header, so a proxy that clears the header by
blanking it, or sends `/` for "no prefix", gets base `/`. Unit tests pin both cases. This is device-builder's strict precedence
("the first source that yields a non-empty value wins"); Etherpad instead falls through to the next header when
a value fails sanitization. Falling through here would, under ingress, hand the base to a client-supplied
`X-Forwarded-Prefix` (core passes it through) whenever HA changed its `X-Ingress-Path` format, where rejecting
surfaces the change on D6's diagnostic page.

**Recommendation:** B. It is the precedence the closest HA add-on uses, delivers the sub-path promise with the
trust machinery that already exists, adds no config field, and keeps the ingress precedence airtight.
**Pick A instead if** you want v0.1 strictly to the ingress need, accepting that the docs say sub-path proxies
aren't supported yet.
**Pick C instead if** sub-path users behind an untrusted proxy with token login matter more than avoiding a
setting that can drift from the proxy's config.
**Reversibility:** easy (adding a header source later is additive; removing one is a documented break)
**Ratified:** Chose `X-Ingress-Path` first, then `X-Forwarded-Prefix`, both honored only from `trusted_proxies` peers and allow-list validated, with the first header present deciding (a present-but-invalid `X-Ingress-Path` is rejected and `X-Forwarded-Prefix` is not consulted; an empty, whitespace-only or `/` value counts as absent), over ingress-only, a static `base_path` setting, or Etherpad-style fall-through, so sub-path reverse proxies work with the existing trust machinery and ESPHome device-builder's strict precedence, accepting that a sub-path proxy must be a trusted (auth-bypassing) proxy.

### D2: How does the frontend learn its base?

**Deciding factor:** one source of truth for the base, read in one place.

| | A: Read `document.baseURI` (set by `<base href>`) once at load, through one module that every site imports | B: Backend also injects `window.__HASSETTE_BASE__` in an inline script | C: Derive from the entry script's URL (`import.meta.url` / `document.currentScript`) | D: No base at all: hash router, URLs from `location.pathname` |
|---|---|---|---|---|
| Convention | Grafana (base from `<base href>`) | Frigate, Double-take (both escape it wrongly) | ESPHome device-builder | zwave-js-ui, Z2M windfront, Music Assistant |
| Sources of truth | One (`<base href>`) | Two that must agree | One, but tied to asset layout | None needed |
| Deep-link reload (`<prefix>/apps/foo`) | Works: the base is absolute | Works | Works, given `<base href>` for the assets | Trivial: the server only serves `/` |
| UI URLs | Unchanged (`/apps/foo`) | Unchanged | Unchanged | Become `/#/apps/foo`; every existing bookmark and docs link changes |
| Inline script / CSP | None | Adds an inline script | None | None |
| Testability | Set `<base>` in jsdom, assert URLs | Set a global | Hard to fake in jsdom | Easy |

Under A, one module (e.g. `frontend/src/lib/base-path.ts`) exposes the router base (the base's pathname without
its trailing `/`, empty at `/`) and a resolver from an app-relative path to an absolute URL. `client.ts`'s REST
and `postSession` calls, the WebSocket URL (resolved, then `http`→`ws` / `https`→`wss`), and the 401 login
redirect all go through it. `app.tsx` wraps its routes in wouter's `<Router base>` so routes, `<Link>`s,
`navigate` and `useLocation` stay base-relative and `HOME_PATH` / `LOGIN_PATH` keep their current values. `document.baseURI` equals the page URL when no
`<base>` exists; that state is unreachable because D4 never serves a shell without the marker, so the module
adds no fallback.

**Recommendation:** A. `<base href>` is already required for relative assets on a deep-link reload, so reading
it back avoids a second, drift-prone channel; it gives the same answer as device-builder's script-URL
derivation with less machinery.
**Pick B instead if** some consumer runs before `<base>` is parsed (none does today: the entry script follows
it in `<head>`).
**Pick C instead if** the backend could never inject `<base>`, which D1 of spec 129 already rules out.
**Pick D instead if** you'd rather match the HA-ecosystem majority and drop header trust from the UI entirely,
accepting hash URLs for every page.
**Reversibility:** easy (internal to the frontend)
**Ratified:** Chose reading `document.baseURI` once at load through one base-path module (router base + URL resolver for REST, `postSession`, WebSocket and the login redirect, with `app.tsx` under wouter's `<Router base>`) over an injected global, entry-script derivation or a hash router, so `<base href>` stays the single source of truth and UI URLs stay unchanged, accepting that the frontend depends on the backend's `<base>` being correct.

### D3: What `base` does the Vite build use?

**Deciding factor:** the built output contains no absolute same-origin paths, with the fewest source edits.

A probe build with `--base ./` (2026-10-11) emitted `./assets/index-*.js`, `./assets/index-*.css`,
`./hassette-logo.png` in `index.html`, and rewrote all five `url("/fonts/…")` in `fonts.css` to
`url(../fonts/…)` relative to the emitted stylesheet. The only absolute paths left in the bundle, vendor chunks
included, were the source constants `BASE_URL = "/api"` (`frontend/src/api/client.ts`) and
`WS_PATH = "/api/ws"` (`frontend/src/api/endpoints.ts`); this change makes both app-relative (`"api"`,
`"api/ws"`) inputs to D2's resolver, so the shipped bundle has none.

| | A: `base: "./"` | A2: A, plus the five fonts move from `frontend/public/fonts/` into Vite's asset pipeline (`fonts.css` references them by relative path) | B: A placeholder base string the backend rewrites in every served file | C: Keep `base: "/"`, move fonts into `src/` and hand-fix each path |
|---|---|---|---|---|
| Source edits for icon + fonts | None (Vite rewrites public-dir URLs) | Fonts move, five `url()`s become relative; icon untouched | None | Fonts move, CSS and icon edited |
| Backend work | `index.html` only | `index.html`, and the `/fonts` `StaticFiles` mount in `src/hassette/web/app.py` is deleted (fonts ship under `assets/`) | Rewrite JS and CSS on every request, breaking static caching | `index.html` only |
| Hashed, cacheable assets | Yes, except fonts (unhashed under `fonts/`, as today) | Yes, fonts included | No | Yes |
| Absolute paths left in source | `/fonts/…` and the icon's `/`, rewritten at build | Only the icon's `/`, rewritten at build | Same as A | None |
| Dev server (`npm run dev`) | Unchanged: Vite serves a relative base at `/` in dev | Unchanged | Unchanged | Unchanged |

**Recommendation:** A2. The probe shows Vite already does the asset half of the work; moving the fonts also
hashes them and deletes a backend mount. The icon stays in `public/`: a favicon there is conventional and gains
nothing from hashing.
**Pick A instead if** you'd rather not touch the fonts at all.
**Reversibility:** easy (one config line, five files moved)
**Ratified:** Chose `base: "./"` with the fonts moved into Vite's asset pipeline (relative `url()`s in `fonts.css`, `/fonts` mount removed from `app.py`) and the icon left in `public/`, over a plain relative base, a placeholder rewrite, or an absolute base, so the bundle has no absolute same-origin paths and fonts become hashed assets, accepting five moved files.

### D4: How does `index.html` get its `<base href>`, and when is the file read?

**Deciding factor:** a missing injection point fails loudly, not as a blank page under ingress.

| | A: Source `index.html` carries a literal `<base href="/" />` as the first `<head>` child after the charset; the backend reads the built file once at app creation, requires that exact tag (startup error if `run_ui` and absent), and substitutes it per request | A2: As A, but a missing marker (or missing `index.html`) logs ERROR naming the file and "rebuild the SPA", mounts no SPA routes, and keeps the API up | B: As A, but read per request; a missing tag logs an error and serves the file unmodified | C: Insert a `<base>` after `<head>` with a regex, no marker |
|---|---|---|---|---|
| Stale or foreign build | Startup error inside `WebApiService.serve()`: REST, WebSocket and telemetry restart-loop; in the add-on, Supervisor's watchdog on port 8126 restarts the container | ERROR at startup; UI routes 404; API, WebSocket and telemetry stay up | Silent at `/`, blank page under a prefix, one log line per request | Works on any HTML, but a second `<base>` (if one ever appears) is undefined behavior |
| Matches today's no-SPA-dir behavior (degrade to no UI) | No | Yes | Yes | Yes |
| Dev server parity | `<base href="/">` is correct at `/` | Same | Same | Dev has no `<base>` |
| Rebuilding the SPA while hassette runs | Needs a restart to pick up the new `index.html` | Same | Picks it up | Picks it up |
| Request cost | String substitution on a cached string | Same | File read + substitution | File read + regex |

Every path that serves `index.html` goes through the substitution, including a direct `GET /index.html`, which
today hits the root-level static-file branch of `spa_catch_all` and would bypass it. One helper is the only code
that renders the shell; the root-level static-file branch excludes `index.html` by name and defers to it, and a
unit test asserts `GET /index.html` from a trusted peer returns the substituted base. Under A2 the three
build states are: SPA directory missing (no UI, as today, no log change), directory present but `index.html`
missing or marker absent (ERROR, no SPA routes), marker present (served). `hassette run --check` does not fail
on the marker: `scripts/docker_start.sh` halts the start on a failed check, which would stop the automation
runtime over a UI asset.

**Recommendation:** A2. It keeps the failure loud while confining it to the UI, the component that is actually
broken. ESPHome device-builder uses the same substitute-a-marker shape (a `__ESPHOME_BASE_HREF__` token,
memoized per base); a literal `/` as the marker keeps the dev server correct without substitution.
**Pick A instead if** you treat a marker-less SPA as a packaging bug that must never reach a user, accepting that
stale dev builds lose the API until rebuilt.
**Pick B instead if** you rebuild the SPA against a running backend often enough that a restart hurts.
**Reversibility:** easy
**Ratified:** Chose a literal `<base href="/" />` marker in source `index.html`, the built file read once at app creation, a missing `index.html` or marker logging ERROR (file named, "rebuild the SPA") and mounting no SPA routes while the API stays up, `hassette run --check` not failing on it, and one helper as the only code that renders the shell (the static-file branch excludes `index.html` by name, and `GET /index.html` is pinned by a test), over a startup error, per-request reads or a regex insert, so a stale or foreign build is loud without taking down the API or the add-on and no path serves an unsubstituted shell, accepting a restart after rebuilding the SPA under a running server.

### D5: What caching headers does `index.html` get?

**Deciding factor:** a browser or proxy never reuses one request's base for another.

The body now varies by peer and headers, so `FileResponse`'s file-derived `ETag` / `Last-Modified` would
validate a cached copy built for a different base.

| | A: `Cache-Control: no-cache`, no `ETag` / `Last-Modified`, `Vary: X-Ingress-Path, X-Forwarded-Prefix` | B: `Cache-Control: no-store` | C: Keep `FileResponse` validators |
|---|---|---|---|
| Wrong-base reuse | Prevented (no validator to match) | Prevented | Possible |
| Shared-cache correctness | `Vary` names the inputs | Nothing stored | Wrong |
| Cost | One small HTML fetch per load, as today in practice | Same | — |

`Vary` lists only the headers D1 admits (drop `X-Forwarded-Prefix` if D1 is A or C). The body also varies by
peer address, which `Vary` cannot express, and browsers never send `X-Forwarded-Prefix`; the guard against
wrong-base reuse is `no-cache` with no validators. `Vary` only keeps a shared cache from storing one
header-keyed copy for all requests. Practice varies:
device-builder sends `Vary` only, Music Assistant `no-cache`, Z2M `no-store`; Etherpad adds `Vary` after a
cache-poisoning advisory.

**Recommendation:** A. It's the minimal correct set; `no-store` adds nothing once there is no validator.
**Pick B instead if** a proxy in the path is known to ignore `Vary`.
**Reversibility:** easy
**Ratified:** Chose `Cache-Control: no-cache` with no `ETag`/`Last-Modified` and `Vary: X-Ingress-Path, X-Forwarded-Prefix` on every `index.html` response, over `no-store` or keeping `FileResponse` validators, so no cache reuses a shell rendered for another base, accepting one small HTML fetch per page load.

### D6: What happens when a base header is present but rejected, and what gets logged?

**Deciding factor:** a misconfiguration is diagnosable where the user is looking (a blank ingress panel has no
other symptom), without letting anonymous traffic control log volume.

A rejected header falls into one of three reasons: **untrusted peer** (header from a peer outside
`trusted_proxies`), **malformed value** (fails D1's pattern for that header), or **trust inactive**
(`auth_enabled=false`, so `trusted_proxies` is never resolved; `src/hassette/core/web_api_service.py`,
`on_initialize`). A request carrying neither D1 header is the normal direct-port case: base `/`, nothing logged.
When more than one reason applies, they are checked in the order trust inactive, untrusted peer, malformed
value, and the first match decides both the page text and the WARNING key, so an untrusted header's value is
never parsed. (Evaluating malformed first was considered and rejected: it parses untrusted input and can blame
the value when the fix is trust configuration.) No surveyed project does more than a DEBUG line or silence (prior-art brief, Pattern 3).

**What the browser gets.** Under a stripped prefix, a shell with base `/` can never load (its assets resolve at
the proxy's origin root), so serving it hides the cause.

| | A: A self-contained diagnostic page (inline CSS, no external assets, `no-cache`) naming the reason and the setting to fix, for either D1 header | B: Diagnostic page for `X-Ingress-Path` only; a rejected `X-Forwarded-Prefix` falls back to base `/` | C: Base `/` for every rejection |
|---|---|---|---|
| Blank ingress panel | Replaced by the cause | Replaced by the cause | Blank |
| Untrusted sub-path proxy | Shows the cause | Broken page | Broken page |
| Direct-port client sending a stray header | Sees the diagnostic page | Works for a stray `X-Forwarded-Prefix` | Works |
| Spec 129 D1 ("every other request gets `/`") | Amended | Amended for ingress only | Unchanged |

The page contains no request-supplied value (no peer address, no header value), only the reason and the remedy:
add the proxy to `web_api.trusted_proxies`, fix the proxy's prefix header, or set `auth_enabled=true`.
It is returned with status 403 for every reason, the same page for any method and `Accept` value, with D5's
caching headers, rendered by the same helper as the shell (D4). A 403 tells curl and monitors the request failed;
the browser renders the page regardless, including inside the ingress iframe. Supervisor's watchdog requests port
8126 directly with no base header, so it never receives this page. A per-reason status (400 for a malformed
value) and a 200 were considered: the first adds a mapping to maintain, the second makes a misconfiguration look
like success.

**How often the WARNING fires.**

| | A: WARNING the first time each reason occurs in the process (with the peer address, never the header value), DEBUG after | B: WARNING per (peer, reason) in a time window with a suppressed count | C: WARNING every request | D: WARNING the first time each (reason, peer) pair occurs, capped at 16 pairs, DEBUG after |
|---|---|---|---|---|
| Flood resistance | Bounded: at most three lines per process | Bounded per peer; a scanner sweep still logs one line per peer | None | Bounded: at most 16 lines per `SpaShell` |
| New state | A set of at most three reasons | A time-windowed map that grows with peers | None | A set of at most 16 pairs |
| Misconfiguration visible after the first line | On the diagnostic page, every time | Periodically in the log | Every request | On the diagnostic page, every time |
| Address the untrusted-peer remedy needs | Lost if another peer was rejected first | Logged per window | Every request | Logged once per peer, up to the cap |

**Whether a successful resolution is logged.**

| | A: DEBUG on every successful resolution: the header used and the resulting base (both validated) | B: Nothing | C: DEBUG once per distinct (peer, base) |
|---|---|---|---|
| Diagnosing a wrong-but-valid prefix | Turn on debug logging | Browser only | Turn on debug logging |
| New state | None | None | A set that grows |

**Recommendation:** A, A, A. The diagnostic page puts the cause in front of the user, which frees the log from
carrying the whole diagnosis; the three-reason set bounds the log with trivial state; success at DEBUG is
stateless and silent by default.
**Pick B (response) instead if** you expect direct-port clients to send stray `X-Forwarded-Prefix` headers.
**Pick C (response) instead if** spec 129 D1 must stay untouched.
**Pick B (log) instead if** you want each misconfigured peer named in the log.
**Reversibility:** easy
**Ratified:** Chose reasons checked in the order trust inactive, untrusted peer, malformed value (first match decides page and log key), a self-contained diagnostic page (status 403 for every reason, no request-supplied values, `no-cache`) for any present-but-rejected D1 header, a WARNING the first time each (reason, peer) pair occurs (log option D, capped at 16 pairs per `SpaShell`, chosen at the ship-time challenge over the reason-only set so the address the untrusted-peer remedy asks for always reaches the log) with DEBUG after, and DEBUG on every successful resolution, over base `/` with a per-request WARNING, so the user sees the cause in the panel and anonymous traffic can't flood the log, accepting an amendment to spec 129 D1 and a stray-header direct-port client seeing the error page.

### D7: How is "no absolute same-origin paths" enforced?

**Deciding factor:** the check covers what ships, runs everywhere the SPA is built, and needs no allowlist.

| | A: A Vite plugin in `vite.config.ts` that fails `vite build` when any emitted JS, CSS or HTML chunk, vendor chunks included, contains an `/api`, `/fonts` or `/assets` path opening a single-quoted, double-quoted or backtick string, or a `url(` | B: A source-grep prek hook (`tools/frontend/check_absolute_paths.py`, beside `check_dead_tokens.py`) | C: An ESLint `no-restricted-syntax` rule |
|---|---|---|---|
| What it checks | Built output, after Vite's rewrites | Source | TS/TSX string literals only |
| Covers CSS and `index.html` | Yes | Yes | No |
| False positives | None once `BASE_URL`/`WS_PATH` are app-relative (D3); the probe build's only hits were those two | `generated-types.ts` path keys, doc comments, and `index.html`'s icon (which Vite rewrites) all need allowlisting | Generated types |
| Runs in | Every build: local, CI, release, and local e2e whenever D12 rebuilds a stale SPA | Commit hook and the lint job | Lint |
| Enforcement rung | Build failure | Pre-commit | Pre-commit |

**Recommendation:** A. With D3's relative base, the source legitimately keeps the icon's `/` (rewritten at build);
checking the bundle is the only form without an allowlist, and it can't be skipped. A vendor chunk that ever
contains such a path fails the build too: it would break under a prefix whatever its source.
**Pick B instead if** you want the failure at commit time rather than build time.
**Reversibility:** easy
**Ratified:** Chose a Vite build plugin in `vite.config.ts` that fails `vite build` when emitted JS, CSS or HTML chunk (vendor included) contains an `/api`, `/fonts` or `/assets` path opening a quoted or backtick string or a `url(`, with `BASE_URL`/`WS_PATH` made app-relative, over a source-grep hook or an ESLint rule, so the check covers what ships with no allowlist on every build, accepting that the failure surfaces at build rather than commit time.

### D8: What fronts the app in the prefix e2e test, and what does the test assert?

**Deciding factor:** the test fails on any URL that escapes the prefix, through real HTTP and WebSocket
proxying shaped like production ingress, without new infrastructure.

HA ingress is HA core's aiohttp proxy (`~/source/core/homeassistant/components/hassio/ingress.py`) in front of
Supervisor: it strips the prefix, sets `X-Ingress-Path`, and connects from a trusted peer, so hassette auth is
bypassed (spec 129 D7) and no login page appears. A trusted D1 sub-path proxy behaves the same with a different
header; the frontend only sees the resulting `<base>`, so one e2e path covers both and unit tests cover each
header's resolution. No surveyed project runs e2e under ingress or a proxy.

| | A: In-process ASGI layer that rewrites the scope | B: nginx container in front of uvicorn | C: A real reverse proxy in Python `aiohttp` (already a dependency), modeled on HA core's ingress view, on its own socket in front of uvicorn |
|---|---|---|---|
| Real HTTP / WebSocket upgrade through a proxy | No (scope rewritten in-process) | Yes | Yes |
| Resembles production ingress | Behaviorally | A generic proxy, not what HA runs | Same stack and header logic as HA core |
| Setup | ~30 lines | Docker in the e2e job, a config file, trusting the Docker bridge address (differs WSL vs CI) | ~80-100 lines, no Docker; peer is loopback |
| Flakiness | None | Image pull, readiness wait, network differences | Low (same start-and-wait pattern as `tests/support/uvicorn.py`) |
| Catches an escaped URL | Yes | Yes | Yes |

Under every option the proxy strips `/api/hassio_ingress/<token>` for HTTP and WebSocket, sets
`X-Ingress-Path: /api/hassio_ingress/<token>`, and returns 404 for any path outside the prefix. The app runs with
auth on and `trusted_proxies` matching the proxy's peer. The test asserts: the UI loads at the prefix with no
login view; client-side navigation and a deep-link reload stay under the prefix with styles and fonts applied;
the live WebSocket connects. Invariant: a prefix is only ever honored for a trusted, auth-bypassing peer (D1), so
hassette's own login and session cookie never operate under a prefix; login under a prefix is unreachable, and
frontend unit tests pin the 401 handling instead (D11).

Beyond the e2e happy path, integration tests pin each D6 rejection branch (untrusted peer, malformed value,
trust inactive with auth off), a trusted peer with no header (base `/`), the D1 precedence case, and each D4 build
state (marker missing, `index.html` missing), asserting the response and base rather than log text.

**Recommendation:** C. It runs real HTTP and WebSocket traffic through a proxy built like HA's own, which
answers the risk of an in-process imitation letting bugs through, at no Docker cost.
**Pick B instead if** you want a third-party proxy implementation in the loop and accept Docker in e2e.
**Pick A instead if** the cheapest test matters more than exercising real proxying.
**Reversibility:** easy
**Ratified:** Chose a real aiohttp reverse proxy modeled on HA core's ingress view (strips the prefix, sets `X-Ingress-Path`, forwards HTTP and WebSocket, 404s outside the prefix) in front of an auth-on app trusting loopback, asserting a login-free load, in-prefix navigation and deep-link reload, and a live WebSocket, over an in-process scope rewrite or an nginx container, so real proxying is exercised without Docker, accepting ~100 lines of test proxy to maintain.

### D9: Where do the docs go?

**Deciding factor:** users looking for reverse-proxy setup find it where trusted proxies are already explained.

**Recommendation:** a "Serving under a sub-path" section on `docs/pages/web-ui/index.md`, next to its trusted
proxies material (`docs/pages/web-ui/snippets/trusted-proxies.toml`): that the proxy must strip the prefix, be a
`trusted_proxies` entry with `auth_enabled=true` (D6's "trust inactive" reason), and send `X-Forwarded-Prefix`
(per D1) on every request, setting or clearing it unconditionally so a client-sent copy never passes through
(Spring's edge-strips rule: "a proxy at the edge of trust must remove forwarded headers"), with Traefik and
nginx snippets that do so; ingress needs no setup.
**Pick instead** a page under `docs/pages/operating/` if the section outgrows the web UI page.
**Reversibility:** easy
**Ratified:** Chose a "Serving under a sub-path" section on `docs/pages/web-ui/index.md` beside the trusted-proxies material (strip the prefix, trust the proxy with auth on, always set or clear `X-Forwarded-Prefix`; Traefik and nginx snippets; ingress needs no setup) over a standalone operating page, so users find it where proxy trust is already explained, accepting a longer web UI page.

### D10: How do in-page `#` links behave once a `<base href>` is present?

**Deciding factor:** the skip link keeps working on every route, at base `/` as well as under a prefix.

Under `<base>`, `<a href="#x">` resolves to `<base>#x` and navigates off the current route (MDN; prior-art
brief, Anti-Patterns). This applies at base `/` too: on `/apps/foo`, the skip link
(`href={`#${MAIN_CONTENT_ID}`}` in `frontend/src/app.tsx`) would load `/#main-content`. It is the only in-page
anchor in `frontend/src`, and there are no inline SVG `url(#id)` references.

| | A: Skip link handles activation itself: focuses `#main-content` and scrolls to it without navigating, keeping a `#main-content` href for semantics | B: `href` built from the current path (`location.pathname + location.search + "#main-content"`) | C: Leave it |
|---|---|---|---|
| Works on every route | Yes | Yes, but it pushes a history entry and the router sees a hash change | No: navigates to the base |
| Keyboard and screen-reader behavior | Same as today (focus lands on `<main>`) | Same, plus a URL change | Broken |
| Future anchors | A small shared component or handler new anchors reuse | Each anchor rebuilds the path | Each one breaks |

**Recommendation:** A, because focus is what the skip link exists to move, and it involves no URL at all.
**Pick B instead if** you want the browser's native anchor behavior, accepting the history entry.
**Reversibility:** easy
**Ratified:** Chose having the skip link move focus to (and scroll to) `#main-content` itself without navigating, keeping its `#main-content` href for semantics, over a path-qualified href or leaving it, so it works on every route under any `<base>`, accepting a small handler new in-page anchors must reuse.

### D11: What does the UI do on a 401 it didn't cause?

**Deciding factor:** the UI responds to the 401 that actually happened, from evidence in the response rather than
a guess from the base.

Under ingress, Supervisor itself returns 401 when the HA ingress session expires
(`~/source/supervisor/supervisor/api/ingress.py`, `validate_session`), on REST, WebSocket and HTML requests alike.
Today both 401 sites send the user to hassette's login view: `frontend/src/lib/query-client.ts`
(`window.location.assign(LOGIN_PATH)`, a full reload that lands on Supervisor's raw 401) and
`frontend/src/hooks/use-websocket.ts` (`navigate(LOGIN_PATH)` after a rejected handshake). Login can't succeed
there: its POST gets Supervisor's 401 too. Hassette's own 401 is a problem response carrying
`ProblemCode.NOT_AUTHENTICATED` (`src/hassette/web/middleware.py`).

| | A: Redirect to login only on hassette's own 401 (problem code `NOT_AUTHENTICATED`); any other 401 shows a "session expired, reload from Home Assistant" state | B: Under a non-root base, never redirect; always show the reload state | C: Keep the redirect on every 401 | D: A, with the view's copy proxy-neutral and a secondary "Log in to Hassette" action at root base |
|---|---|---|---|---|
| Expired ingress session | Correct message | Correct message | Broken login view or raw 401 | Correct message |
| Basis of the decision | Response body (evidence) | Base path (a heuristic about who sent it) | Status code alone | Response body; the base only adds an affordance |
| Direct-port login | Unchanged | Unchanged | Unchanged | Unchanged |
| Root base, Hassette 401 whose body a proxy mangled | Dead end (Reload repeats it) | Login | Login | Login reachable from the view |
| Forward-auth proxy (non-HA) 401 | Copy names Home Assistant | Copy names Home Assistant | Login form that can't succeed | Neutral copy; Reload reaches the proxy's sign-in |
| Size | A check at the two 401 sites | Smaller | None | A, plus a copy tweak and one conditional action |

The "session expired" state is a full-page view that replaces the app, the way the login view already
bypasses the shell in `frontend/src/app.tsx`, driven by a store flag both sites set. `ApiError`
(`frontend/src/api/client.ts`) gains the response's problem code so the query-client site can branch on it; the
WebSocket site decides from the existing `confirmAuthRejection` REST probe, since a handshake carries no body.
A banner over the current view was considered and rejected: after an expired session every control fails.
Frontend tests pin both branches at both sites.

**Recommendation:** A. An expired ingress session is ordinary (any HA tab left open long enough), and A uses data
already in the response.
**Pick B instead if** you'd rather not couple the frontend to the problem-code body.
**Pick C instead if** expired ingress sessions are rare enough for a follow-up.
**Reversibility:** easy
**Ratified:** Chose redirecting to login only on hassette's own 401 (problem code `NOT_AUTHENTICATED`) and showing a full-page "session expired" view (option D, amended at the ship-time challenge: proxy-neutral copy, and a secondary "Log in to Hassette" action when served at root base, so a Hassette 401 whose body a proxy mangled isn't a dead end) (store flag; `ApiError` gains the problem code; the WebSocket site uses the `confirmAuthRejection` REST probe) for any other 401, at both the query-client and WebSocket sites with frontend tests for each branch, over a base-path heuristic or redirecting on every 401, so an expired ingress session gets an actionable message instead of a dead login form, accepting a frontend dependency on the problem-code body.

### D12: When does local e2e rebuild the SPA?

**Deciding factor:** local e2e runs against the current frontend, so D7's plugin and this change's frontend
behavior are actually exercised before push.

Both `ensure_spa_built` (`tests/e2e/conftest.py`) and the `e2e` nox session (`noxfile.py`) build only when the
built `index.html` is missing, so a build from before this change keeps being reused locally.

| | A: One shared staleness check, used by both callers: rebuild when the built `index.html` is missing or older than the newest file under `frontend/src/`, `frontend/public/`, or `frontend/index.html`, `vite.config.ts`, `package.json`, `package-lock.json`; `npm ci` only when `node_modules` is missing or the lockfile is newer | B: Leave the fixtures as they are; D7's "Runs in" says a stale local build skips the plugin |
|---|---|---|
| Stale local bundle | Rebuilt | Reused until deleted by hand |
| Wrong-direction risk | A spurious rebuild after a checkout bumps mtimes (safe); a missed rebuild only under clock skew | Silent staleness |
| Size | ~20-line helper, a unit test, two call sites | None |
| Concurrency | None needed: the `e2e` nox session runs without xdist | — |

**Recommendation:** B (from the challenge synthesis): CI builds fresh and the mtime check is a fixture guessing at
build state.
**Pick A instead if** local e2e is a main feedback loop for frontend changes.
**Reversibility:** easy
**Ratified:** Chose one shared mtime staleness check used by both `ensure_spa_built` and the `e2e` nox session (rebuild when the built `index.html` is missing or older than any frontend source, public, `index.html`, Vite config or package file; `npm ci` only when `node_modules` is missing or the lockfile is newer), over leaving stale builds in place, so local e2e exercises the current frontend and D7's plugin, accepting occasional spurious rebuilds after checkouts.

## Assumed

- HA core sets `X-Ingress-Path: /api/hassio_ingress/<token>` (no trailing slash) on every ingress request,
  overwriting any client value. Evidence: `~/source/core/homeassistant/components/hassio/ingress.py:275`.
- Supervisor strips the prefix: it proxies to `http://<addon_ip>:<ingress_port>/<path-after-token>`. Evidence:
  `~/source/supervisor/supervisor/api/ingress.py:94-96`.
- Core forwards other client request headers to the add-on unchanged (only a fixed filter list is dropped).
  Evidence: `~/source/core/homeassistant/components/hassio/ingress.py:266-272`.
- The add-on pins `auth_enabled` and `trusted_proxies = ["172.30.32.2"]`. `trusted_proxies` is only resolved when
  `auth_enabled` is true, so with auth off no base header is ever honored (D6 covers the response). Evidence: spec 129 D7;
  `src/hassette/core/web_api_service.py` (`on_initialize`).
- A trusted-peer request bypasses auth entirely. Evidence: `resolve_auth_outcome` in `src/hassette/web/middleware.py`.
- With `base: "./"`, Vite rewrites public-dir absolute URLs in HTML and CSS to relative ones, and the bundle's only
  remaining absolute paths are `BASE_URL` and `WS_PATH`. Evidence: probe build, 2026-10-11 (see D3).
- wouter 3's `<Router base>` makes `useLocation`, `<Route>`, `<Link>` and `navigate` base-relative. Evidence:
  `frontend/package.json` (`wouter ^3.10.0`); wouter README, "Base path".
- `tests/integration/web_api/conftest.py` (`stub_spa`) and `tests/integration/test_packaging.py` write stub
  `index.html` files without a `<base>` tag; under D4 they need one, or the SPA routes are not mounted.
- Today e2e's `ensure_spa_built` and the `e2e` nox session each build only when
  `src/hassette/web/static/spa/index.html` is missing (D12 changes this); CI builds fresh. The `e2e` nox session
  runs pytest without xdist. Evidence: `tests/e2e/conftest.py` (`ensure_spa_built`), `noxfile.py` (`e2e`).

## Build

- [x] Implementation and tests committed
- [x] Docs
- [x] Ship-time challenge

**Calls made during the build:**

- One trailing `/` is stripped from either header before matching, so `/hassette//` is malformed: D1 left the
  trailing `//` case open; an empty last segment is what the allow-list already rejects.
- A request whose transport reports no peer address counts as an untrusted peer: nothing to match against
  `trusted_proxies`.
- A missing or marker-less `index.html` skips the `/assets` mount too, not just the catch-all: D4 says "no
  SPA routes", and assets without a shell serve nothing useful.
- `tests/integration/test_packaging.py`'s stub stays marker-less: it builds a wheel and never constructs an
  app, so the Assumed note about it doesn't apply.
- Backend lives in a new `src/hassette/web/spa.py` (`resolve_base`, `SpaShell`, `load_spa_shell`);
  `app.py` only wires it. Each `BaseRejection` member carries its log label and the page's cause and remedy.
- The diagnostic page names which header was rejected (a fixed header name, not a request-supplied value).
- The WARNING-once set lives on the app's `SpaShell`, so it lasts one `WebApiService.serve()` lifetime: a web
  service restart rebuilds the app and resets it, the same restart that re-reads `index.html` (D4).
- `App` is a `<Router base={ROUTER_BASE}>` around the former body (now `AppShell`), because `App` itself calls
  `useLocation`.
- `resolveAppUrl` treats a leading `/` as the app root, so route constants like `LOGIN_PATH` resolve without a
  second helper; the bundle still holds only `"api"`/`"api/ws"`.
- The session-expired view (`frontend/src/pages/session-expired.tsx`) has a Reload button that reloads the top
  frame, so HA starts a fresh ingress session; it falls back to this window when the top is cross-origin.
- D7's plugin is `frontend/no-absolute-paths.ts` (imported by `vite.config.ts`), so its matcher has a unit test.
- D12: `tools/frontend/spa_build.py` holds the check; `npm ci` keys on `node_modules/.package-lock.json`
  (npm rewrites it on every install; the directory's mtime doesn't track installs). The nox session runs the
  file as a script, because nox loads `noxfile.py` without the repo root on `sys.path`.
- The Traefik snippet clears any client-sent `X-Forwarded-Prefix` with a headers middleware before
  `stripPrefix`, so it never depends on whether `stripPrefix` adds or replaces the header (D9's set-or-clear
  rule).
- Spec 129's D1 amendment is an addendum entry there, not a body edit, since that ledger is ratified for its own
  build.
- A deciding header sent more than once is a malformed value, checked after the trust checks: an append-style
  proxy would otherwise let the client's copy come first and pick the base.
- `load_spa_shell` also serves no UI (ERROR logged) when `assets/` is missing or `index.html` can't be read
  or decoded, so every bad-build state D4 names degrades to no UI rather than a startup crash.
- D7's plugin checks in a post-enforced `generateBundle`, before anything is written, so a failing build leaves
  no `index.html` for D12's freshness check to reuse (verified by builds with a planted absolute JS path, CSS
  `url()` and rewritten marker). The same plugin fails the build when the emitted `index.html` lacks the exact
  `BASE_MARKER` tag.
- The error body is read through a type keyed by the generated `ProblemDetail`, so a backend rename of `code`
  fails tsc; `ApiError.code` stays `string`, since a newer backend may send a code the generated union lacks.
- The skip-link handler is `focusInPageTarget` in `frontend/src/lib/in-page-anchor.ts`; a test fails on any
  component with a `#` href that doesn't use it (D10's "new in-page anchors must reuse").
- The session-expired view's `offerLogin` prop defaults to `ROUTER_BASE === ""`, so tests set it directly.
- No `BREAKING CHANGE:` footer for the 403 on a base header from a non-trusted peer: deployments that sent one
  and worked were mostly direct-port clients with a stray header, and stripping proxies were already broken
  by the old absolute asset paths; the docs page describes the error page.

## Addendum
