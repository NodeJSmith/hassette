# Prior art: runtime sub-path support for a SPA served by a Python/Go/Node backend behind a reverse proxy

Research date 2026-10-11. Line numbers come from the raw files as fetched (WebFetch reported them; treat as +/-2). Items I could not verify are marked [no source found] or [unverified].

## Sources Found

### FastAPI "Behind a Proxy"
- **URL**: https://fastapi.tiangolo.com/advanced/behind-a-proxy/
- **Type**: Official docs
- **Key takeaway**: Server ignores forwarded headers unless told to trust them (`--forwarded-allow-ips`). `root_path` is set via `--root-path` or `FastAPI(root_path=...)`; "the server (Uvicorn) won't use that `root_path` for anything else than passing it to the app". The page only lists X-Forwarded-For/Proto/Host, never X-Forwarded-Prefix, and has no per-request root_path middleware example. It reads `request.scope.get("root_path")`.
- **Relevance**: Confirms per-request root_path from a header is NOT a documented FastAPI pattern. Static root_path is the documented path.

### uvicorn ProxyHeadersMiddleware
- **URL**: https://raw.githubusercontent.com/encode/uvicorn/master/uvicorn/middleware/proxy_headers.py
- **Type**: Source
- **Key takeaway**: Reads only `x-forwarded-proto` (lines ~39-40, 47-51) and `x-forwarded-for` (~41-42, 53-61). Does not read a prefix header and does not touch `root_path`. All processing gated by `if client_host in self.trusted_hosts` (line ~35); XFF walked right-to-left returning the first untrusted hop (~178-181).
- **Relevance**: Prefix handling must be our own middleware; we can copy its trust-gate shape (peer IP in trusted set before reading the header).

### Starlette routing / `get_route_path`
- **URL**: https://raw.githubusercontent.com/encode/starlette/master/starlette/_utils.py and https://raw.githubusercontent.com/encode/starlette/master/starlette/routing.py
- **Type**: Source
- **Key takeaway**: `get_route_path` strips `root_path` from `scope["path"]` only if the path starts with it at a segment boundary; otherwise returns path unchanged. `Mount.matches` (routing.py ~394-425) reads `scope.get("root_path")` and builds child `root_path = root_path + matched_path`. Plain `Route.matches` does not read root_path (it uses the route path).
- **Relevance**: With a stripping proxy, setting `scope["root_path"]` per request does not break routing (path lacks the prefix so nothing is stripped) and makes `url_for`/redirects prefix-aware. If the proxy does NOT strip, setting root_path makes Starlette strip it for you. Per-request middleware is mechanically sound, but is [no source found] as a documented idiom.

### Traefik StripPrefix
- **URL**: https://doc.traefik.io/traefik/middlewares/http/stripprefix/
- **Type**: Official docs (page fetch only returned a redirect stub; claim below is from general knowledge and the Spring/ASP.NET docs describing the de-facto header)
- **Key takeaway**: Traefik StripPrefix sets `X-Forwarded-Prefix` with the removed prefix [unverified against the live page in this session].
- **Relevance**: Main real-world producer of the header.

### Spring `ForwardedHeaderFilter`
- **URL**: https://docs.spring.io/spring-framework/reference/web/webmvc/filters.html
- **Type**: Official docs
- **Key takeaway**: "While not standard, `X-Forwarded-Prefix: <prefix>` is a de-facto standard header that is used to communicate the original URL path prefix to a downstream server." Trust: "Forwarded headers are intended to be set by trusted proxies and never allowed in from the outside. A proxy at the edge of trust must remove forwarded headers". Offers `removeOnly` mode and a separate toggle for the prefix header. Spring does not gate by peer IP; it relies on the edge proxy stripping inbound copies.
- **Relevance**: Establishes the header as de-facto standard and the two trust models (peer-IP gate vs edge-strips).

### ASP.NET Core forwarded headers / `UsePathBase`
- **URL**: https://learn.microsoft.com/en-us/aspnet/core/host-and-deploy/proxy-load-balancer
- **Type**: Official docs
- **Key takeaway**: Table lists `X-Forwarded-Prefix` ("original base path requested by the client"); middleware sets `HttpContext.Request.PathBase` from it and persists the old value in `X-Original-Prefix`. Default off (`ForwardedHeaders.None`). Trust is peer-IP gated: "The request's original remote IP must match an entry in the KnownProxies or KnownNetworks lists before forwarded headers are processed"; defaults are loopback only. Configurable header name via `ForwardedPrefixHeaderName`. `UsePathBase("/foo")` is the static-config alternative for proxies that pass the full path.
- **Relevance**: Closest analogue to our plan: header-driven PathBase, peer-IP gated, off by default. Does not document value validation.

### Werkzeug ProxyFix
- **URL**: https://werkzeug.palletsprojects.com/en/stable/middleware/proxy_fix/
- **Type**: Official docs
- **Key takeaway**: `x_prefix` (default 0 = ignored) sets how many `X-Forwarded-Prefix` values to trust; trusted value becomes `SCRIPT_NAME`. "It is a security issue to trust values that came from the client rather than a proxy." Trust is by proxy hop count, not peer IP.
- **Relevance**: Third trust model (hop count). Off by default.

### Django FORCE_SCRIPT_NAME
- **URL**: https://docs.djangoproject.com/en/stable/ref/settings/#force-script-name
- **Type**: Official docs
- **Key takeaway**: Static setting that overrides server-provided `SCRIPT_NAME`; also used outside request cycle for URL generation. No header.
- **Relevance**: Static-config end of the spectrum (also what Paperless-ngx exposes as `PAPERLESS_FORCE_SCRIPT_NAME`; Paperless docs page returned 403 so that mapping is [unverified] in this session).

### RFC 7239 Forwarded
- **URL**: https://www.rfc-editor.org/rfc/rfc7239#section-5
- **Type**: Standard
- **Key takeaway**: Defines only `by`, `for`, `host`, `proto` (Section 5; IANA table has the same four). Section 5.5 permits extension parameters, but none for a path prefix. Confirmed: no prefix parameter exists.
- **Relevance**: Prefix header is necessarily non-standard; X-Forwarded-Prefix is the convention.

### Grafana `index.html` template and docs
- **URL**: https://raw.githubusercontent.com/grafana/grafana/main/public/views/index.html (also `pkg/services/frontend/index.html`); https://grafana.com/docs/grafana/latest/setup-grafana/configure-grafana/
- **Type**: Source + docs
- **Key takeaway**: Line 15: `<base href="[[.AppSubUrl]]/" />`, placed immediately after `<title>` and before the icon `<link>`s (lines 17-18). `AppSubUrl` comes from static `root_url` when `serve_from_sub_path = true` ("If accessed without sub-path Grafana redirects the request to the sub-path"). No header involved.
- **Relevance**: Direct precedent for server-templated `<base href>` in index.html. Static config, not header.

### Sonarr/Radarr `UrlBase`
- **URL**: https://raw.githubusercontent.com/Sonarr/Sonarr/develop/src/Sonarr.Http/Frontend/Mappers/HtmlMapperBase.cs ; Startup.cs (`app.UsePathBase(new PathString(configFileProvider.UrlBase))` ~line 245, `UrlBaseMiddleware` ~259)
- **Type**: Source
- **Key takeaway**: Static config `UrlBase`. index.html is post-processed: regex rewrites `href|src` for css/js/png/ico/svg/json assets to prefix `_urlBase` (lines ~56-70) and replaces literal `__URL_BASE__` placeholder (line ~72). Generated HTML cached in memory in production (`_generatedContent`). I did not find a `<base href>` or cache headers in these files. `window.Sonarr.urlBase` claim is [unverified]; placeholder substitution is verified.
- **Relevance**: "Placeholder in built index.html, replaced at serve time" is the Go/.NET-world analogue; build artifact stays base-agnostic.

### zwave-js-ui `X-External-Path`
- **URL**: https://raw.githubusercontent.com/zwave-js/zwave-js-ui/master/api/app.ts
- **Type**: Source
- **Key takeaway**: `req.header('X-External-Path')?.replace(/\/$/, '') ?? ''` used only to build a redirect (`${path}/#${req.originalUrl}`) for legacy history-mode URLs. The app uses hash routing. Header is unvalidated and not peer-gated: a value like `//evil.example` yields a protocol-relative redirect (open redirect when header is attacker-controlled).
- **Relevance**: Cautionary example for validation; also shows hash-routing as the sub-path escape hatch.

### Home Assistant add-on Ingress
- **URL**: https://developers.home-assistant.io/docs/add-ons/presentation/#ingress
- **Type**: Official docs
- **Key takeaway**: Ingress adds request header `X-Ingress-Path` ("may be filtered to obtain the base URL"). Trust is peer-IP gated and mandatory: "Only connections from `172.30.32.2` must be allowed" / deny all others. Docs don't say how apps should generate asset URLs.
- **Relevance**: Real-world per-request header base, with the strictest trust model (single known peer IP, app denies everything else).

### Home Assistant frontend (no sub-path)
- **URL**: https://shop.zimaspace.com/blogs/support-tips/can-home-assistant-work-behind-reverse-proxy-subpath (secondary); no official HA statement found
- **Type**: Secondary blog / community anecdotes
- **Key takeaway**: Frontend requests root-relative assets, WebSockets and views hard-code `/`; community says developers decline sub-path support. Official rationale [no source found]; treat as anecdotal.
- **Relevance**: Shows what happens if the frontend assumes root; not a data point on mechanism.

### Uptime Kuma sub-path issue
- **URL**: https://github.com/louislam/uptime-kuma/issues/147
- **Type**: Issue thread
- **Key takeaway**: No native support; maintainer (Aug 2021): "it is much harder than I thought, because express.js itself is not so friendly with subdirectory", could not find a clean fix without hardcoding. Closed as not planned June 2026. Workarounds: nginx `sub_filter`, entrypoint script patching built JS/HTML; socket.io path stays fixed at root.
- **Relevance**: Cost of retrofitting; WebSocket/socket.io path is the typical leak.

### code-server
- **URL**: https://coder.com/docs/code-server/guide
- **Type**: Official docs
- **Key takeaway**: "HTTP servers should use relative URLs to avoid the need to be coupled to the absolute path at which they are served." Default strips `/proxy/<port>`; `--abs-proxy-base-path` for the absolute variant; "Omitting the trailing slashes couples you to the base path, since you cannot use relative redirects correctly anymore." No X-Forwarded-Prefix mention.
- **Relevance**: Relative-only strategy; trailing-slash redirect requirement.

### Jupyter server `base_url`
- **URL**: https://jupyter-server.readthedocs.io/en/latest/operators/public-server.html
- **Type**: Official docs
- **Key takeaway**: Static config `c.ServerApp.base_url = "/ipython/"`. No header.
- **Relevance**: Static-config strategy.

### Vaultwarden `DOMAIN`
- **URL**: https://github.com/dani-garcia/vaultwarden/wiki/Configuration-overview
- **Type**: Wiki
- **Key takeaway**: Sub-path supported via `DOMAIN` containing a path (example `https://host.example.com/bitwarden/`); wiki says avoid URL-rewriting tricks. Static config.
- **Relevance**: Static-config strategy.

### Mealie, AdGuard Home, Portainer
- **Type**: Not verified
- **Key takeaway**: [no source found] in this session. Mealie docs redirected and were not re-fetched; Portainer nginx docs show only a dedicated hostname; AdGuard not checked. Do not cite them.

### MDN `<base>`
- **URL**: https://developer.mozilla.org/en-US/docs/Web/HTML/Reference/Elements/base
- **Type**: Reference
- **Key takeaway**: "Links pointing to a fragment in the document — e.g., `<a href="#some-id">` — are resolved with the `<base>`, triggering an HTTP request to the base URL with the fragment attached." Only the first `<base>` is obeyed; it "must come before other elements with attribute values that are URLs"; `data:`/`javascript:` hrefs disallowed; Open Graph tags ignore `<base>`.
- **Relevance**: Defines the pitfalls we must handle (hash links, ordering).

### SVG `url(#id)` under `<base>`
- **URL**: https://bugs.webkit.org/show_bug.cgi?id=189499 ; https://bug635044.bugzilla.mozilla.org/show_bug.cgi?id=652991 ; https://www.syncfusion.com/forums/124323/base-tag-breaks-diagrams-gridlines
- **Type**: Browser bug trackers / forum
- **Key takeaway**: WebKit 189499 (Safari did not render a gradient fill with `<base href="/">`; retitled so fragment-only `url(#frag)` resolves against the current document; marked RESOLVED FIXED, shipping version not stated). Mozilla 652991: CSS `url()` resolved against base URI then compared to document URL. Workaround in Syncfusion thread: `url(${location.pathname}${location.search}#id)`. Current-browser behaviour not re-tested here.
- **Relevance**: Inline SVG paint-server/clip-path/mask references can break under `<base>` in some engines; test in Safari/Firefox.

### Vite build options
- **URL**: https://vite.dev/guide/build.html#relative-base
- **Type**: Official docs
- **Key takeaway**: "If you don't know the base path in advance, you may set a relative base path with `base: './'` or `base: ''`." Requires `import.meta` support; old browsers need the legacy plugin. `import.meta.env.BASE_URL` is statically replaced at build time. Experimental `experimental.renderBuiltUrl` can emit runtime expressions (`{ runtime: ... }`) for JS-referenced assets.
- **Relevance**: The three build-time-agnostic routes: relative base, `renderBuiltUrl` runtime, or server-side rewrite. The docs do not discuss `<base href>` interplay.

### wouter `Router base`
- **URL**: https://github.com/molefrog/wouter#base-path
- **Type**: README
- **Key takeaway**: `base` prop: "All application routes will be relative to that path"; `useLocation()` returns a path scoped to the base; bases nest; `~` prefix escapes to absolute. Nothing on `document.baseURI` or whether `base` must be absolute.
- **Relevance**: Router base must be derived by us from `document.baseURI` (strip origin, trailing slash). That derivation is [no source found] as an established recipe; it is our glue.

### Caching of index.html
- **URL**: https://web.dev/articles/codelab-http-cache (and search results summarized by blazingcdn / MS Q&A)
- **Type**: Guides
- **Key takeaway**: Standard recipe is `no-cache` (revalidate) on HTML, long `immutable` on fingerprinted assets; ETag/Last-Modified make revalidation cheap. Nothing found specifically on `Vary` for a header-varied index.html; RFC 9110 section 12.5.5 (Vary) fetch was truncated before the definition. Point below on `Vary` is reasoning, not sourced.
- **Relevance**: See Pattern 5.

## Patterns Found

### Pattern 1: Static config prefix, server templates index.html
**Used by**: Grafana (`root_url` + `serve_from_sub_path`, `<base href="[[.AppSubUrl]]/" />`), Sonarr/Radarr (`UrlBase`, `__URL_BASE__` placeholder + asset regex), Jupyter (`base_url`), Vaultwarden (`DOMAIN`), Django (`FORCE_SCRIPT_NAME`), ASP.NET (`UsePathBase`).
**How it works**: Operator sets the prefix once; the backend mounts routes under it (or the proxy strips it) and rewrites index.html on startup/serve.
**Strengths**: No header trust problem; deterministic; cacheable; the most common approach by far.
**Weaknesses**: One prefix per instance; a mismatch with the proxy silently breaks; operator must configure both sides.
**Example**: Grafana `index.html` line 15.

### Pattern 2: Per-request prefix from a trusted-proxy header
**Used by**: ASP.NET Core (`X-Forwarded-Prefix` to `PathBase`, KnownProxies/KnownNetworks gated, off by default), Spring (`X-Forwarded-Prefix`, edge strips untrusted copies, can be toggled), Werkzeug `ProxyFix(x_prefix=n)` (hop-count trust), HA add-ons (`X-Ingress-Path`, single trusted peer 172.30.32.2), zwave-js-ui (`X-External-Path`, no trust gate, redirect only).
**How it works**: A proxy that strips the prefix advertises it; a middleware sets root_path/PathBase/SCRIPT_NAME from it for that request; templating uses it.
**Strengths**: Same image serves any prefix or several; no app config; matches Traefik StripPrefix out of the box.
**Weaknesses**: Needs trust gating and value validation; every deployment must add the header (nginx/Caddy do not set it automatically); response varies per request (caching).
**Example**: ASP.NET docs table row for `X-Forwarded-Prefix` -> `Request.PathBase`.

### Pattern 3: Server-injected `<base href>` plus relative asset URLs
**Used by**: Grafana (injects base; assets are relative to it), our plan.
**How it works**: Built bundle uses relative URLs (`base: './'` or `''`); server writes `<base href="{prefix}/">` as the first URL-bearing element in `<head>`; JS derives router base and WebSocket URL from `document.baseURI`.
**Strengths**: Deep-link reloads work (a relative base on `/app/a/b/` would otherwise resolve `./assets/x.js` against `/app/a/b/`); one build for all prefixes.
**Weaknesses**: See Anti-Patterns (hash links, SVG refs, JS-built URLs that use `/`).
**Example**: Grafana line 15 comes before icon links at 17-18, satisfying MDN's ordering rule.

### Pattern 4: Relative-only, no base, no config
**Used by**: code-server (per its guide: use relative URLs, preserve trailing slashes).
**How it works**: Every URL is relative; proxy keeps trailing slash; no prefix knowledge needed.
**Strengths**: Zero config, zero trust surface.
**Weaknesses**: Breaks on history-mode deep links (no slash-depth guarantee), needs trailing-slash redirects; hard for an SPA with client-side routes.
**Example**: code-server's `/proxy/<port>/` vs `/absproxy/`.

### Pattern 5: Cache an index.html that varies per request
**Used by**: general SPA practice; Sonarr caches the generated HTML in memory per process (base is static there).
**How it works**: Send `Cache-Control: no-cache` (revalidate) on index.html; compute ETag over the rendered bytes (so a different base gives a different ETag); if any shared cache could sit between client and app, add `Vary` on the header that drives the base, or `Cache-Control: private`.
**Strengths**: Cheap 304s; correct per prefix.
**Weaknesses**: A strong ETag computed from the unrendered file would produce wrong 304s across prefixes; `Vary` on a custom request header is only honored by compliant caches. Vary specifics [no source found] beyond reasoning.
**Example**: web.dev codelab for `no-cache` on HTML.

### Pattern 6: Hash routing to dodge the problem
**Used by**: zwave-js-ui (redirects legacy history URLs to `/#...`).
**How it works**: Routes live after `#`, so the server path is always the entry document.
**Strengths**: Deep-link reload needs no server fallback and no base knowledge for routing.
**Weaknesses**: Ugly URLs; conflicts with wouter history routing; assets still need a base.

## Anti-Patterns

1. **Trusting the prefix header from any peer.** zwave-js-ui reads `X-External-Path` without a gate or validation (`//evil.example` becomes a protocol-relative redirect target). Gate on the peer IP (ASP.NET KnownProxies model, HA's single-IP model) AND validate the value. ASP.NET/Spring/Werkzeug docs all default the header to off.
2. **Writing the raw header into HTML.** The value lands in an attribute (`<base href="...">`), so it needs strict validation (allow-list regex like `^/[A-Za-z0-9._~/-]*$`, reject `//`, scheme, backslash, `..`, quotes) plus HTML-attribute escaping. MDN: a `<base>` can redirect every relative URL on the page, including `<script src>`. A forged base is script injection. [validation regex is my recommendation; no surveyed project documents one]
3. **`<base>` after other URL-bearing elements.** Per MDN it "must come before other elements with attribute values that are URLs"; the first `<base>` wins and later ones are ignored, so don't also leave a static `<base>` in the Vite template.
4. **`#hash` links.** Under `<base href="/sub/">`, `<a href="#x">` resolves to `/sub/#x` and navigates away from the current route (MDN). In an SPA with a history router and a non-root route, clicking a skip-link or in-page anchor triggers a full navigation to the base URL. Fix with `href={location.pathname + '#x'}` or JS handling.
5. **SVG `fill="url(#id)"` / `clip-path` / `mask` / `filter` references.** Historical breakage in WebKit (bug 189499, fixed per tracker) and Firefox (652991), and fragment references in CSS `url()`. Test inline SVG gradients and clip-paths in Safari/Firefox; workaround is `url(${location.pathname}${location.search}#id)`.
6. **Hardcoded root-absolute URLs in JS** (`fetch('/api')`, `new WebSocket('/ws')`, `history.pushState('/x')`, `import.meta.env.BASE_URL` which Vite replaces statically). Uptime Kuma's socket.io path and HA's hard-coded paths are the cautionary tales. Use `new URL('api/x', document.baseURI)` and `new URL('ws', document.baseURI)` with `protocol` swapped to `ws:`/`wss:`. [Recipe from standard URL semantics; no framework doc found that prescribes it.]
7. **Vite `base: './'` without testing deep links.** Docs require `import.meta` support; CSS `url()` is rewritten relative to the CSS file and dynamic imports resolve relative to the module, which works; but any asset referenced from `index.html` with a relative URL resolves against `<base>` (fine) or against the document URL if `<base>` is missing (breaks on `/app/a/b/`). That is why `<base href>` is needed with a relative build. Workers and `new URL('./x', import.meta.url)` are the usual edge cases; specifics for our build are [no source found], verify by building and loading a nested route.
8. **Missing trailing slash on the mount root.** `/app` must redirect to `/app/` or relative URLs resolve to `/`. code-server's guide calls this out; with a stripping proxy this redirect must be done by the proxy or by the app using the prefix header.
9. **Static root_path plus stripped path assumption mismatch.** In Starlette, `get_route_path` strips `root_path` only when present; if the proxy both strips and the app is also given `root_path`, behavior is fine for plain routes, but a `Mount` would build child root_path from it. Test `StaticFiles` mounts and `url_for`.
10. **Caching one rendering for all prefixes.** An ETag/`Last-Modified` computed from the file on disk rather than from the rendered bytes lets a browser or shared cache revalidate to a 304 against the wrong prefix.
11. **Retrofitting by response rewriting at the proxy** (nginx `sub_filter`, patching built JS). Uptime Kuma workarounds and HA's rewrite attempts show it breaks with each new frontend build.
