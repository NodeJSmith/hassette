---
proposal: "Give the hassette CLI a first-class way to target a remote web API (scheme + host + port + optional path prefix), independent of the server's own bind settings, plus safe auth-token handling for non-loopback targets."
date: 2026-08-05
status: Draft
flexibility: Exploring
motivation: "The user runs a real homelab Hassette instance behind Traefik with auth enabled, and cannot point the hassette CLI at it — the CLI can only build http://{host}:{port}."
constraints: "Must not regress local/loopback UX. Must not silently transmit the local .web_api_token to a remote host. #1117 (merged) reverse-proxy docs are out of scope to change; only reference them."
non-goals: "Re-investigating or modifying #1117's reverse-proxy guidance. Server-side path-prefix (root_path) support. CLI websocket/follow transport."
depth: normal
---

# Research Brief: CLI Support for Targeting a Remote Hassette API URL

**Initiated by**: GitHub issue #1522 — "Add CLI support for targeting a remote API URL". Direct follow-up to #1117 / PR #1521 (`feat!: require authentication for the web API by default`, merged as `02ae0098`), which shipped reverse-proxy + auth guidance for the browser UI but left the CLI unable to reach such a deployment.

## Context

### What prompted this

The user deploys Hassette from `main` on their VPS behind Traefik with authentication enabled, and wants `hassette status` / `hassette app` / etc. to work against it instead of only `localhost`. Issue #1522 states the project owner will not release the #1117 auth work until this is also completed (`priority:high`).

**This is a real, currently-blocked workflow.** I verified it end to end against the live deployment (details below), and the block is worse than the issue describes — see the Concerns section.

### Current state

`HassetteCLIClient.__init__` builds the connect target from the server's own **bind** settings:

```python
# src/hassette/cli/client.py:98-100
host = _format_host(config.web_api.host)
port = config.web_api.port
self.base_url = f"http://{host}:{port}"
```

`WebApiConfig.host` (default `"0.0.0.0"`) and `.port` (default `8126`) are declared at `src/hassette/config/models.py:342-346` with docstrings "Host to bind the web API server to" / "Port to run the web API server on". **Reusing a bind address as a connect target is the root category error** — it happens to work for loopback and coincidentally for a plain-HTTP LAN host, and breaks for anything else.

Confirmed empirically that the existing `HASSETTE__WEB_API__HOST` / `__PORT` levers cannot express the user's deployment:

```
HASSETTE__WEB_API__HOST=hassette.smithfamily.dev
HASSETTE__WEB_API__PORT=443
  →  base_url = http://hassette.smithfamily.dev:443
```

The scheme is unreachable — it is a hardcoded f-string literal.

Other relevant current state, all read directly:

- **Global CLI flags** are only `--config-file/-c`, `--env-file/-e/--env`, `--json`, `--debug`, declared on the cyclopts meta launcher (`src/hassette/cli/__init__.py:118-129`). `CLIContext` (`context.py`) carries only `json_mode` and `debug_mode` — no target information.
- **Config precedence** is `init kwargs > env > .env > file secrets > TOML` (`settings_customise_sources`, `src/hassette/config/config.py:64-80`). Env naming is `HASSETTE__` + `__` nesting (`HASSETTE__WEB_API__PORT`).
- **Token resolution** (`_resolve_cli_auth_token`, `client.py:48-84`) tries `config.web_api.auth_token` (blank-stripped), then falls back to reading `<data_dir>/.web_api_token` off the **local** filesystem. It never generates.
- **13 CLI commands across 6 files** make HTTP requests, all funneling through the single `make_client(ctx)` → `HassetteCLIClient.get()` path. There is exactly one URL construction site.
- **The CLI has no websocket client at all** (zero matches for `websocket`/`follow`/`tail` under `src/hassette/cli/`), so there is no `ws://`→`wss://` work in scope.

### Key constraints

- Loopback/default UX must not regress — `hassette status` with no configuration must keep working.
- The local token file must not be silently shipped to a remote host (#1522 acceptance criterion).
- #1117's docs content is fixed; #1522 should link to it, not rewrite it.
- Adding any config field requires regenerating `hassette.schema.json` via `uv run python scripts/export_schemas.py`, enforced by the `tools/check_schemas_fresh.py` pre-push hook.

## Live Deployment Ground Truth

I reached the user's real deployment via `ssh smithfamily` and validated the topology directly. This materially changes the design.

**Actual Traefik routing** (`docker inspect hassette --format '{{json .Config.Labels}}'`):

```
traefik.http.routers.hassette.rule:        Host(`hassette.smithfamily.dev`)
traefik.http.routers.hassette.entrypoints: websecure
traefik.http.routers.hassette.tls:         true
traefik.http.routers.hassette.tls.certresolver: cf
traefik.http.routers.hassette.middlewares: tinyauth@docker
traefik.http.services.hassette.loadbalancer.server.port: 8126
```

Four findings, all **Direct** (read from live config / observed responses):

1. **The deployment uses subdomain routing, not a path prefix.** There is no `PathPrefix` rule and no `stripprefix` middleware anywhere. The user's actual blocker is *scheme* (`https`) + hostname — not path prefixes. Path-prefix support in #1522 is generic hardening, not the thing unblocking this user.

2. **TLS terminates at Cloudflare and again at Traefik.** Responses carry `server: cloudflare`, `cf-ray`, HTTP/2. Certificates are publicly valid, so default TLS verification works — no self-signed opt-out is needed for this user.

3. **A valid Hassette bearer token is rejected by the proxy.** This is the critical finding:

   | Test | Request | Result |
   |---|---|---|
   | A | `https://hassette.smithfamily.dev/api/health`, no token | `401 {"message":"Unauthorized","status":401}` |
   | B | `https://hassette.smithfamily.dev/api/health`, **valid** Hassette bearer token | `401 {"message":"Unauthorized","status":401}` |
   | C | `http://127.0.0.1:8126/api/health` inside the container, same token | **`200`** — full valid JSON (`"status":"ok"`, `entity_count:864`, `app_count:15`) |
   | D | `http://tinyauth:3000/api/auth/traefik` forward-auth probe, same token | `401 {"message":"Unauthorized","status":401}` — byte-identical body to A and B |

   Test D's response body is byte-identical to A and B, which identifies tinyauth — not Hassette — as the source of the 401. Test C proves Hassette's own bearer auth works correctly. **tinyauth is an OIDC/browser SSO forward-auth middleware** (`OAUTH_AUTO_REDIRECT=pocketid`, `PROVIDERS_POCKETID_*`, `APP_URL=https://auth.smithfamily.dev`) with no bypass configured. Root `/` and `/api/ws` also return 401.

4. **The user's Hassette config deliberately trusts Traefik instead of using a token.** `~/homelab/hautomate/config/hassette.toml` sets `trusted_proxies = ["traefik"]`, with a comment explaining the intent: *"Rather than manage a bearer token, trust the one peer that can reach us through an authenticated path."* This matches the `trusted_proxies` docstring at `config/models.py:385-394`, which describes exactly this forward-auth-gateway pattern.

**Token path claim — CONFIRMED.** The coordinator relayed an unverified claim that the token lives at `/data/.web_api_token` on the `hautomate_data` volume. Verified:

```
docker volume inspect hautomate_data  →  /var/lib/docker/volumes/hautomate_data/_data
docker inspect hassette (Mounts)      →  volume hautomate_data -> /data
docker exec hassette ls -la /data/.web_api_token
                                      →  -rw------- 1 hassette hassette 43 Aug  5 12:59
```

43 bytes matches `secrets.token_urlsafe(32)`, and the token authenticated successfully in test C. The claim is accurate. The token was used only inside SSH sessions on `smithfamily` and was never written to disk in this worktree.

## Feasibility Analysis

### What would need to change

| Area | Files affected | Effort | Risk |
|------|---------------|--------|------|
| URL construction | `cli/client.py` (1 site, lines 98-100) | Low | Low — single choke point, 13 commands inherit it |
| Config field | `config/models.py` or `config/config.py`; regenerate `hassette.schema.json` | Low | Low — well-trodden pattern |
| Global flag | `cli/__init__.py` (meta launcher), `cli/context.py` | Low–Med | **Med** — name collision, see below |
| Token-fallback guard | `cli/client.py:48-84` + a loopback predicate | Med | **Med** — must classify hostnames, not just IPs |
| TLS verify option | `cli/client.py:107` (`httpx.Client(...)` takes no `verify=` today) | Low | Low |
| Tests | `tests/unit/cli/test_client.py` (`TestBaseUrl` 4 tests, `TestCredentialAttachment` 12 tests, factories at :55 and :489); `tests/system/test_cli_smoke.py` (hardcoded `http://127.0.0.1:{port}`) | Med | Low |
| Docs | `docs/pages/cli/configuration.md` (rewrite "Remote instances", lines 18-30; "Discovery Order" lines 5-16; "Common Errors" lines 135-149) | Med | Low |

### What already supports this

- **One URL construction site.** All 13 HTTP commands go through `make_client(ctx)` → `HassetteCLIClient`. Fixing `base_url` fixes everything.

- **Path prefixes work for free.** Issue #1522 asserts path-prefix support "touches every call site in `client.py`". **That is incorrect.** The CLI uses `httpx2`, whose `base_url` merging preserves the base path. Verified directly:

  ```
  'http://h:8126'                      + "/api/health" -> http://h:8126/api/health
  'https://x.example.com/hassette'      + "/api/health" -> https://x.example.com/hassette/api/health
  'https://x.example.com/hassette/'     + "/api/health" -> https://x.example.com/hassette/api/health
  'https://x.example.com/hassette/api'  + "/api/health" -> https://x.example.com/hassette/api/api/health   ← doubled
  ```

  Every command's path already starts with `/api/...`, so a prefix supplied *without* a trailing `/api` composes correctly with zero call-site changes. This meaningfully shrinks the scope. The one hazard is the last row: a user copying the issue's own example (`https://hassette.example.com/hassette/api`) gets `/hassette/api/api/health`. That needs a validator or a clear docs warning, not code changes at 13 sites.

- **A strong in-repo precedent for exactly this shape.** `HassetteConfig.base_url: str = "http://127.0.0.1:8123"` plus `verify_ssl: bool = True` (`config/config.py:130-133`) is how Hassette already solves "connect to a remote HTTPS service." It is a plain `str` (not `AnyUrl`/`HttpUrl`), parsed lazily at point of use by `src/hassette/utils/url_utils.py` with `yarl.URL` and dedicated `FatalError` subclasses per failure mode (`BaseUrlRequiredError`, `IPV6NotSupportedError`, `SchemeRequiredInBaseUrlError`).

- **`yarl` is already available** (transitive via `aiohttp`, pinned `1.22.0`, already imported in `url_utils.py`, `exceptions.py`, `harness.py`).

- **Env var support is free.** Any new config field automatically gets `HASSETTE__...` env + `.env` + TOML resolution via pydantic-settings. No plumbing needed.

- **Nested config group precedent** is well established (`design/specs/060-nested-config-models/design.md`), including `nested_model_default_partial_update=True` so partial overrides don't wipe group defaults.

- **`--config-file` already lets a user keep a separate remote profile** today, which is a viable interim workaround and a natural composition partner for whatever ships.

### What works against this

- **Flag name collision (concrete, not hypothetical).** `hassette run` already defines:

  ```python
  # src/hassette/cli/commands/run.py:25-27
  base_url: Annotated[str | None, Parameter(name=["--base-url", "-u", "--url"],
      help="Base URL of the Home Assistant instance.")] = None
  ```

  `--url` and `-u` are taken, and they mean **the Home Assistant instance**, a completely different remote. A global `--url` meta flag would sit in the same parse scope as `hassette run --url` and mean the opposite thing. Any option that adds a flag must pick a non-colliding name.

- **`_build_ha_url` discards the path — do not reuse it.** `url_utils.py:51` does `URL.build(scheme=..., host=..., port=..., path="/api/")`, dropping any path component from the user's URL. It also flatly rejects IPv6 (`if "::" in config.base_url: raise`). Reuse the *field shape* (`str` URL + `verify_ssl`), not this function — copying it would break the path-prefix requirement and the IPv6 loopback case the CLI currently supports.

- **Three duplicated copies of the bind-all substitution map.** `_BIND_ALL_SUBSTITUTIONS` (`0.0.0.0`→`127.0.0.1`, `::`→`::1`) exists in `cli/client.py:26-30` and again in `web/auth.py:63-73`, the latter deliberately not importing to avoid a cycle. This logic is meaningful only for a locally-bound server; it needs to be scoped so it does not run for an explicitly-supplied remote target.

- **The server cannot be mounted under a path prefix.** `create_fastapi_app()` (`web/app.py:48`) passes no `root_path`; routers mount at fixed `/api` prefixes; static mounts (`/assets`, `/fonts`) and the SPA catch-all are root-relative. `uvicorn.Config` in `core/web_api_service.py` passes `proxy_headers=False` deliberately (uvicorn's `ProxyHeadersMiddleware` would trust `X-Forwarded-For` before Hassette's own `trusted_proxies` peer check). So a prefixed deployment **requires the proxy to strip the prefix**, and flipping `proxy_headers=True` is not a safe shortcut. The CLI can send prefixed URLs; the server can only receive stripped ones. Docs must say this plainly.

- **`httpx2.Client` is constructed with `follow_redirects=False`** (verified default) and no `verify=` argument (`client.py:107`). A proxy issuing an `http`→`https` or login redirect surfaces as a raw 3xx and a confusing error.

- **The user's actual deployment will still not work after this feature ships.** See Concerns.

## Options Evaluated

Flexibility is *Exploring*, so three options with a genuine "do less" at the end.

### Option A: New `[hassette.cli]` config group + a `--server` global flag

**How it works.** Add a `CliConfig(ExcludeExtrasMixin, BaseModel)` group to `config/models.py` alongside the existing nine groups, wired into `HassetteConfig` as `cli: CliConfig = Field(default_factory=CliConfig)`. Two fields to start: `url: str | None = None` and `verify_ssl: bool = True`. This gives `HASSETTE__CLI__URL` / `HASSETTE__CLI__VERIFY_SSL` env vars and a `[hassette.cli]` TOML table for free.

Add one global flag to the cyclopts meta launcher named **`--server`** (with `-s`), matching the `hass-cli` convention that Hassette's Home Assistant audience already knows (`HASS_SERVER`) and sidestepping the `--url`/`-u` collision on `hassette run` entirely. The launcher already mutates class-level state for `--config-file`; `--server` instead flows cleanly into `CLIContext` as a new `server_url: str | None` field, which `make_client()` reads.

Resolution in `HassetteCLIClient.__init__` becomes a small ordered function: `ctx.server_url` → `config.cli.url` (which pydantic-settings has already resolved across env → `.env` → TOML) → derive `http://{_format_host(web_api.host)}:{web_api.port}` as today. The derived branch keeps every existing loopback behavior byte-identical, so `TestBaseUrl`'s four pinned tests stay green unchanged. Parse the explicit URL with `yarl.URL` following `url_utils.py`'s style — require a scheme, reject a path ending in `/api` (the doubling hazard), strip a trailing slash — but do **not** call `_build_ha_url`.

For auth, add a loopback predicate and suppress the `<data_dir>/.web_api_token` fallback whenever the resolved target is non-loopback, replacing it with an actionable error naming `HASSETTE__WEB_API__AUTH_TOKEN`. Keep the config/env token path working for remote targets — that is the intended remote credential.

**Pros**
- Cleanly separates "where the server binds" (`web_api`) from "where the CLI connects" (`cli`), fixing the root category error rather than papering over it.
- A `[hassette.cli]` group is the natural home for the follow-on CLI settings this will attract (`token_file`, default `--json`, timeout), so it does not need re-litigating later.
- `--server`/`HASSETTE__CLI__URL` mirrors `hass-cli`'s `--server`/`HASS_SERVER`, which this project's users already have muscle memory for.
- Path prefixes work with no call-site changes (verified above).
- Existing loopback tests remain untouched, so the risk surface is the new branch only.

**Cons**
- Adds a tenth config group for what is currently two fields — the heaviest option for the immediate need.
- `[hassette.cli]` in `hassette.toml` is mildly odd on the *server's* config file, which is otherwise entirely server settings. The CLI and server share one config file today, and this makes that sharing visible.
- Requires `hassette.schema.json` regeneration and touches `CLIContext`, which is currently a tidy two-field dataclass.

**Effort estimate**: Medium. One new config group, one flag, one resolution function, one loopback predicate, ~8-10 new tests, one docs page rewrite. No cascade beyond `client.py` because of the single choke point.

**Dependencies**: None new. `yarl` already available transitively.

### Option B: Single `web_api.client_url` field + `--server` flag

**How it works.** Identical to Option A except the field lands on the existing `WebApiConfig` as `client_url: str | None = None` (plus `client_verify_ssl: bool = True`), giving `HASSETTE__WEB_API__CLIENT_URL`. No new config group.

**Pros**
- Smallest structural diff; no new group, no new TOML table.
- Keeps everything web-API-related in one place, which is arguably easier to find in the config docs table at `docs/pages/web-ui/index.md:63-80`.
- Same free path-prefix behavior and same test-preserving fallback structure as A.

**Cons**
- Perpetuates the exact confusion this issue exists to fix: `WebApiConfig` would then hold both bind settings (`host`, `port`) and a connect setting (`client_url`) whose relationship is "the second overrides the first two, but only for the CLI, and only when set." That is a genuinely hard sentence to write in a docstring.
- The `client_` prefix on two fields in a server-settings model is a naming smell that signals the field is in the wrong place.
- Leaves no obvious home for follow-on CLI settings, so a `cli` group likely gets added later anyway — paying the migration cost twice.

**Effort estimate**: Small–Medium. Meaningfully less than A, mostly by skipping the group scaffolding.

**Dependencies**: None new.

### Option C (do less): Config/env only — no new flag, no new group

**How it works.** Change only `client.py`'s URL construction to honor a scheme and optional prefix, sourced from a single new field, and ship the token-fallback guard. No global CLI flag at all — users select a target with the **already existing** `--config-file` flag, or by exporting the env var. Document a `hassette-remote.toml` profile pattern:

```bash
hassette --config-file ~/.config/hassette/homelab.toml status
```

**Pros**
- Ships the actual unblock (a reachable `https://` target) with the smallest possible diff and no flag-collision decision to make.
- `--config-file` already exists and is already the idiomatic way to switch environments in this CLI; a profile file scales better to multi-instance use than a single flag anyway.
- Defers the `cli`-group-vs-`web_api`-field question until there is a second CLI setting to justify it — consistent with subtract-before-you-add.
- Least test churn.

**Cons**
- `hassette --server https://... status` is a materially nicer one-off than exporting an env var or maintaining a profile file, and one-off queries are the common CLI case.
- Every comparable tool (`hass-cli`, `kubectl`, `docker`) offers a flag; its absence will read as an omission and probably generate a follow-up issue.
- Does not resolve the bind-vs-connect naming confusion, so the "which field do I set?" support burden persists.

**Effort estimate**: Small.

**Dependencies**: None new.

## Concerns

### Technical risks

- **The headline risk: this feature does not unblock the user's stated workflow.** Proven above (tests A–D) — tinyauth 401s a valid Hassette bearer token before the request reaches Hassette. A perfect `--server https://hassette.smithfamily.dev` implementation still returns 401 against the user's live deployment. Unblocking them additionally requires an infrastructure change on their side, one of:
  1. A Traefik router for `/api` on the same host **without** the `tinyauth@docker` middleware, relying on Hassette's own bearer token (note their config currently has `auth_token` unset, so the generated `/data/.web_api_token` value would become the CLI credential);
  2. A tinyauth bypass rule for `/api/*` (tinyauth's configured env shows OIDC-only with no bypass today);
  3. An SSH tunnel to `127.0.0.1:8126`, which needs no code change at all.

  This should be stated in the design doc and in the docs page. It is also a strong argument for shipping the docs half of #1522 with real weight rather than treating it as an afterthought — and worth checking with the user whether they want a follow-up issue for the Traefik-side change, since the code change alone will not visibly fix anything for them.

- **Loopback classification is subtler than an IP check.** The guard must decide "is this target local?" for inputs like `localhost`, `127.0.0.1`, `::1`, `[::1]`, `0.0.0.0`, a LAN IP, and a hostname that resolves to loopback. Resolving DNS to decide whether to attach a credential is itself a risk (slow, and a DNS answer can change). A conservative literal-match allowlist (`localhost`, `127.0.0.0/8`, `::1`) with no DNS resolution is the safer call, accepting that a loopback-resolving hostname loses the file fallback. Worth an explicit decision in the design doc rather than falling out of the implementation.

- **The `/api` doubling hazard.** `https://host/hassette/api` + `/api/health` → `/hassette/api/api/health` (verified). The issue text and the acceptance criteria both use `https://hassette.example.com/hassette/api` as the example URL, so the canonical example in the issue is itself the broken form. A validator rejecting a path ending in `/api` with a message naming the correct form would prevent a confusing 404.

- **No redirect following and no `verify` argument** on the current `httpx2.Client` call. Both are one-line additions but need deliberate defaults: verify on by default; redirects probably still off, with the error message improved to name a 3xx explicitly (a login redirect from a forward-auth proxy is now a likely failure mode).

### Complexity risks

- Introducing a second, overlapping way to say "where is the server" means the docs must explain when `web_api.host/port` applies versus the new field. Option A's separate group makes that explanation easy ("one is bind, one is connect"); Option B makes it hard.
- The token guard adds a new conditional failure mode ("token found on disk but deliberately not sent") whose error message is load-bearing. A silent no-credential 401 here would be worse than the status quo.

### Maintenance risks

- Whatever ships becomes the shape a future CLI websocket/follow transport must reuse. There is no CLI websocket today, so this is cheap now and expensive to retrofit later. Storing a parsed target rather than a formatted string keeps the `https`→`wss` derivation available later, mirroring `build_ws_url`.
- A fourth copy of the bind-all substitution logic would be a real regression; there are already three. Any new resolution code should route through the existing `cli/client.py` copy rather than adding one.

## Open Questions

- [ ] Does the user want the CLI-side change alone, or also a follow-up issue for the Traefik-side bypass/second-router change that would actually make their homelab reachable? The code change does not unblock them by itself.
- [ ] Which flag name — `--server`/`-s` (hass-cli precedent, no collision) or something else? `--url`/`-u` are taken by `hassette run` and mean the Home Assistant instance.
- [ ] Should the loopback predicate resolve DNS, or match literals only? Recommend literals only; needs an explicit decision.
- [ ] Should a `--token-file` flag ship alongside? `design/specs/091-web-api-auth/design.md` and the 2026-08-03 research brief both establish "never a secret as a bare CLI argument" but explicitly float `--token-file <path>` as acceptable. Out of scope for #1522 as written, but it is the natural companion to a remote target.
- [ ] **Verification gap — path prefixes are untested against a real proxy.** The user's deployment uses subdomain routing with no prefix, so I could not observe a live stripped-prefix request. `httpx2`'s joining behavior is verified locally, and the server's lack of `root_path` is verified by reading `web/app.py` and `core/web_api_service.py` — but the end-to-end "Traefik strips `/hassette`, Hassette sees `/api/...`" path has not been exercised. Before relying on it, run one targeted check: add a temporary Traefik router with `PathPrefix(/hassette)` + a `stripPrefix` middleware pointing at the same container, then `curl -H "Authorization: Bearer <token>" https://<host>/hassette/api/health`. If that returns 200, prefix support is real.
- [ ] Should the demo/QA scripts (`scripts/capture_screenshots.py`, `tools/frontend/ui_qa_capture.py`) that hardcode `http://localhost:...` adopt the new mechanism? They do not use the CLI client today. Recommend no — out of scope.

## Recommendation

**Ship Option A, but decouple it from the user's unblock and set expectations accordingly.**

Option A is the right target state. The bind-vs-connect conflation is the actual defect, and a `[hassette.cli]` group names that distinction in the config surface instead of hiding it behind a `client_` prefix. The cost gap versus Option B is small — one `BaseModel` subclass and a `Field(default_factory=...)` line — and Option B's naming smell is the kind of thing that gets re-litigated in six months. That said, if the reviewer weighs "tenth config group for two fields" heavily, Option B is a defensible call that ships the same user-visible capability; the difference is structural hygiene, not function.

Three things should shape the design doc, in order of how much they change the plan:

1. **The user's deployment will still 401 after this ships.** This is Direct evidence (tests A–D above), not a guess. The design doc should say so, the docs page should cover the forward-auth interaction concretely, and the user should decide whether they want a companion issue for the Traefik-side change. Shipping this and reporting "remote CLI access works now" would be wrong.

2. **Path prefix support is much cheaper than #1522 assumes.** The issue's claim that it "touches every call site in `client.py`" is incorrect — `httpx2` base-URL joining handles it, verified. Budget for a validator and docs, not a refactor. Correspondingly, the *scheme* is the whole substance of the change for the user's real topology.

3. **Preserve the derived-from-`web_api` fallback exactly.** It keeps `TestBaseUrl`'s four pinned tests green unchanged and keeps the zero-config local path untouched, confining the risk to the new explicit-target branch.

One note on confidence: the live findings (routing rules, the 401 provenance, the token path and volume, `httpx2` joining, the flag collision) are all Direct — read from live config or observed in command output. The judgment that a `cli` config group beats a `web_api` field is Inferred from the codebase's existing grouping conventions and the docstring-clarity problem; it is a design preference, not a finding, and the user may reasonably prefer the smaller diff.

### Suggested next steps

1. Confirm the flag name (`--server` recommended) and the Option A/B/C choice with the user — these are the two decisions that gate a design doc.
2. Run `/mine-define` to produce the design doc, folding in the four live-deployment findings and the three open decisions (loopback predicate, `/api` doubling validator, redirect/verify defaults).
3. Run the one targeted prefix check named in Open Questions before committing to path-prefix support in the acceptance criteria.
4. Decide whether to file a companion issue for the Traefik/tinyauth bypass so the user's homelab is actually reachable — the code change alone will not do it.

## Sources

- [home-assistant-cli (hass-cli) — `--server` / `HASS_SERVER` convention](https://github.com/home-assistant-ecosystem/home-assistant-cli)
- [home-assistant-cli installation and setup](https://deepwiki.com/home-assistant-ecosystem/home-assistant-cli/3-installation-and-setup)
- [CLI configuration precedence patterns (flags > env > config file)](https://hackernoon.com/how-to-design-a-cli-tool-that-developers-actually-love-using)

Web research was deliberately light — the in-repo precedent (`HassetteConfig.base_url` + `verify_ssl` + `yarl`-based lazy parsing) is stronger and more binding evidence than general CLI convention, and the `hass-cli` precedent was the only external input that changed a recommendation (the flag name).
