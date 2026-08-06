# Design: CLI Support for Targeting a Remote API URL

**Date:** 2026-08-05
**Status:** archived
**Scope-mode:** hold
**Research:** `design/research/2026-08-05-cli-remote-url/research.md`

## Problem

The `hassette` CLI cannot reach a Hassette instance that is not plain HTTP on a bind address. `HassetteCLIClient.__init__` (`src/hassette/cli/client.py:98-100`) builds its connect target from the server's own *bind* settings:

```python
host = _format_host(config.web_api.host)
port = config.web_api.port
self.base_url = f"http://{host}:{port}"
```

`WebApiConfig.host` and `.port` are documented as "Host to bind the web API server to" / "Port to run the web API server on" (`src/hassette/config/models.py:342-346`). Reusing a bind address as a connect target is the root defect. It works for loopback, coincidentally works for a plain-HTTP LAN host, and breaks for everything else — the `http://` scheme is a hardcoded f-string literal with no override.

The existing `HASSETTE__WEB_API__HOST` / `__PORT` levers cannot express an HTTPS deployment. Verified:

```
HASSETTE__WEB_API__HOST=hassette.example.com
HASSETTE__WEB_API__PORT=443
  →  base_url = http://hassette.example.com:443
```

This blocks the workflow that PR #1521 (`feat!: require authentication for the web API by default`, merged as `02ae0098`) opened up: an operator can now put Hassette behind a reverse proxy with TLS and a login, but the CLI they administer it with cannot follow it there.

A second, quieter defect rides along. `_resolve_cli_auth_token` (`client.py:48-84`) resolves a credential from `config.web_api.auth_token` and then `<data_dir>/.web_api_token`, and attaches whichever it finds to whatever target the CLI resolves. Both of those describe the *local* instance: the file is what the local service generated for itself, and `web_api.auth_token` is what it validates incoming headers against. Today the documented way to query a remote instance is `HASSETTE__WEB_API__HOST=192.168.1.100 hassette status` (`docs/pages/cli/configuration.md:18-30`), which transmits one of those local credentials to that host.

Both are correctly scoped to the local instance; the CLI reads them as though they were global defaults. On one machine with one instance those coincide. Add a remote target and they diverge, and the credential becomes both a leak and useless — it is not what the remote instance validates against.

## Goals

- The CLI can target any reachable Hassette instance by full URL, including scheme, host, port, and optional path prefix.
- TLS verification is on by default and can be turned off for a self-signed deployment.
- A credential can be supplied per-target, independent of the local instance's own credentials.
- No local-instance credential — neither the generated token file nor a configured `web_api.auth_token` — is ever transmitted to a non-loopback target.
- The zero-config local path is byte-identical to today: `hassette status` against a local instance keeps working with no configuration.
- An operator can read the docs and know what to change on their reverse proxy to let CLI traffic through.

## Non-Goals

- **Server-side path-prefix support.** `create_fastapi_app()` (`src/hassette/web/app.py:48`) passes no `root_path`; routers mount at fixed `/api` prefixes and static mounts are root-relative. The CLI can *send* a prefixed URL; the server can only *receive* a stripped one. Making Hassette itself mountable under a prefix is out of scope.
- **Reconsidering web API token auto-generation.** See Alternatives — considered and rejected.
- **A CLI WebSocket/follow transport.** The CLI has no WebSocket client today (zero matches for `websocket`/`follow`/`tail` under `src/hassette/cli/`), so there is no `ws://`→`wss://` work here.
- **Named multi-instance profiles within a single config file.** `CliConfig` is a flat single-target shape, and `--config-file` per instance is the answer today. If profile support is added later it lands as a new `[hassette.cli.profiles.<name>]` table *alongside* the flat fields, not replacing them — so deferring it now is additive, not a future breaking change.
- **Changing #1117's reverse-proxy guidance.** That work is merged; this design links to it.

## User Scenarios

### Operator: administers a self-hosted Hassette behind a reverse proxy

- **Goal:** query and manage a remote Hassette instance from a laptop
- **Context:** Hassette runs on a VPS behind TLS termination and a forward-auth gateway; the operator's laptop has the CLI installed but no local Hassette instance

#### One-off remote query

1. **Runs `hassette --server-url https://hassette.example.com status`**
   - Sees: the same status output they would see locally, or a clear error
   - Decides: nothing — this is the common path
   - Then: the CLI resolves the flag as its base URL, verifies TLS, and attaches whichever credential resolution finds

2. **Hits a 401 because the forward-auth gateway rejected the request**
   - Sees: an error naming the three ways to supply a credential (`--token-file`, `HASSETTE__CLI__AUTH_TOKEN`, `trusted_proxies`) and stating that the local instance's own credentials were deliberately withheld
   - Decides: whether the fix is a credential or a proxy-config change
   - Then: consults the reverse-proxy section of the CLI docs

#### Persistent remote profile

1. **Writes `[hassette.cli]` settings into a profile TOML**
   - Sees: `server_url` and `token_file` under one config group, separate from the server's `web_api` bind settings
   - Decides: whether to keep the profile per-instance or use the env var
   - Then: `hassette --config-file ~/.config/hassette/homelab.toml status` targets that instance with no other flags

### Operator: runs Hassette locally

- **Goal:** keep using the CLI exactly as before
- **Context:** single machine, Hassette bound to `0.0.0.0:8126`, token file on disk

#### Unchanged local query

1. **Runs `hassette status` with no flags and no `[hassette.cli]` config**
   - Sees: identical output to the pre-change behavior
   - Decides: nothing
   - Then: the CLI derives `http://127.0.0.1:8126` from `web_api.host`/`port`, reads `<data_dir>/.web_api_token`, and attaches it

## Functional Requirements

- **FR#1** The CLI resolves its connect target from, in precedence order: the `--server-url` global flag, `cli.server_url` from config, then the derived `http://{substituted_host}:{port}` from `web_api.host`/`web_api.port`.
- **FR#2** An explicitly supplied server URL preserves its scheme, host, port, and path prefix in every request the CLI issues.
- **FR#3** A server URL without a scheme is rejected with an error naming the required form.
- **FR#4** A server URL whose path ends in `/api` is rejected with an error explaining that command paths already start with `/api` and naming the corrected URL.
- **FR#5** A trailing slash on a server URL is normalized away before use.
- **FR#6** TLS certificate verification is enabled by default for HTTPS targets and can be disabled via `cli.verify_ssl` config or the `--no-verify-ssl` flag.
- **FR#7** The CLI resolves its bearer credential from, in precedence order: the `--token-file` global flag, `cli.token_file` from config, `cli.auth_token` from config, `web_api.auth_token` from config, then `<data_dir>/.web_api_token`.
- **FR#8** Each credential source declares a scope of `cli` or `server`. Sources declaring `server` scope — `web_api.auth_token` and `<data_dir>/.web_api_token` — are used only when the resolved target is loopback; for any non-loopback target the resolver skips every `server`-scoped source without naming individual sources. Sources declaring `cli` scope apply to every target.
- **FR#9** Loopback classification parses the host as an IP literal and reports whether it is a loopback address, falling back to a fixed hostname set (`localhost`) when it does not parse. It performs no DNS resolution. This covers all of `127.0.0.0/8`, `::1`, and the IPv4-mapped form `::ffff:127.0.0.1`. An IPv6 host is classified in its unbracketed form, so `::1` and `[::1]` classify identically. The CLI and the server share one implementation of this check.
- **FR#10** When a non-loopback target resolves no credential, the CLI issues the request anyway rather than failing before the network call.
- **FR#11** A 401 response where no credential was attached and a server-scoped source was suppressed produces an error that separates remedies by where they are applied: attaching a credential locally (`--token-file`, `cli.token_file`, `HASSETTE__CLI__AUTH_TOKEN`) versus configuring `trusted_proxies` on the *remote instance*, which needs access to that host and a restart. The message must mark the second as remote-side, not present all remedies as one flat list.
- **FR#12** A 3xx response produces an error identifying it as a redirect, naming a forward-auth login redirect as the likely cause, and pointing at the reverse-proxy section of the CLI docs. Diagnosis alone is not enough — "forward auth" is a term the affected reader may be meeting for the first time.
- **FR#13** `hassette run` accepts the Home Assistant base URL as `--ha-url` or `-u`. The former names `--base-url` and `--url` are removed.
- **FR#14** Network and HTTP error messages report the resolved base URL, including scheme and any path prefix.
- **FR#15** A resolved credential that is not header-safe — non-ASCII, or containing control characters — is rejected as a usage error naming its source, before it reaches an HTTP header.
- **FR#16** When the resolved target is non-loopback, the CLI surfaces it once per invocation on both the success and failure paths: a `Target: <base_url>` line on stderr in human mode, a `"target"` key in the JSON envelope in JSON mode. On HTTP-error responses this does not require `--debug`, which today gates the only URL echo `_handle_http_error` performs.
- **FR#17** When `verify_ssl` is false and the value came from persisted config rather than the `--no-verify-ssl` flag, the CLI emits a warning naming the unverified target: a stderr line in human mode, a `"tls_verified": false` key in JSON mode.

## Edge Cases

- **`--server-url` with an IPv6 literal** — `http://[::1]:8126` must round-trip. `_build_ha_url` rejects IPv6 outright (`url_utils.py:30-31`); that rejection must not be inherited here, since the existing CLI already supports `::1` via `_format_host`.
- **`--server-url` pointing at loopback** — the token file fallback still applies. Suppression keys off the resolved target, not off which source supplied it.
- **`web_api.host` set to a LAN address with no `cli.server_url`** — the derived target is non-loopback, so the token file is suppressed. This is a deliberate behavior change from today (see Impact → Behavioral Invariants).
- **`--token-file` pointing at a missing or unreadable path** — a usage error naming the path, not a silent fall-through to the next credential source. A file named on the command just typed is an operator mistake, fresh and attributable, and failing loudly is the fastest way to say so.
- **`cli.token_file` pointing at a missing or unreadable path** — falls through to the next credential source, matching today's file-read behavior (`client.py:80-84`). This deliberately differs from the flag. A config path is durable and reused unattended, so it goes stale in ways the operator is not present to see: a rotated token, an unmounted volume, a profile copied to another machine. Hard-stopping every future invocation of that profile — with no fallback to a lower-precedence credential the operator may also have configured — is the worse failure. The two forms share a precedence tier but not a failure mode; FR#7 orders them, this decides what "unreadable" means for each.
- **`--token-file` pointing at an empty or whitespace-only file** — treated as no credential, matching the existing empty-token-file handling in `_resolve_cli_auth_token`.
- **A token file whose contents are not header-safe** — a smart quote or accented character from a copy-paste, a UTF-8 BOM, or simply the wrong file. Per FR#15 this is a usage error naming the path. Without it the value reaches `httpx.Client(headers=...)` inside `__init__` and raises `UnicodeEncodeError` before any of the CLI's error handling runs, producing a bare traceback.
- **`cli.auth_token` set to a blank or whitespace-only value** — treated as unset, falling through to the next source. Mirrors the existing blank-token handling for `web_api.auth_token`.
- **`cli.auth_token` and `cli.token_file` both set** — `token_file` wins, per FR#7's order. The reason is the same one that rules out an `--auth-token` flag: prefer the form that does not leave a secret sitting in environment output. It is not an assumption about which was configured more recently.
- **Server URL with a query string or fragment** — stripped during normalization; neither is meaningful for a base URL.
- **Both `--server-url` and `HASSETTE__WEB_API__HOST` set** — the flag wins; the bind-derived path is never consulted when an explicit target exists.
- **`cli.server_url` set to an empty or whitespace-only string** — treated as unset, falling through to the derived target. Mirrors the blank-token handling already in `_resolve_cli_auth_token`.
- **`--no-verify-ssl` against an `http://` target** — accepted and inert; no warning. Verification is meaningless without TLS.

## Acceptance Criteria

- **AC#1** `uv run pytest tests/unit/cli/test_client.py` passes, with the four existing `TestBaseUrl` tests unmodified. (FR#1)
- **AC#2** A unit test resolves `https://example.com/hassette` through `resolve_server_target` and asserts the resulting `base_url`, joined with `/api/health` by `httpx2`, produces `https://example.com/hassette/api/health`. The assertion sits at the resolver layer because that is where the composition is decided; no HTTP client is needed to prove it. (FR#2)
- **AC#3** Unit tests assert that a scheme-less URL and a URL ending in `/api` each raise a usage error whose message names the corrected form. (FR#3, FR#4)
- **AC#4** A unit test asserts `https://example.com/hassette/` and `https://example.com/hassette` produce identical base URLs. (FR#5)
- **AC#5** A unit test asserts `httpx.Client` receives `verify=False` when `cli.verify_ssl` is false and `verify=True` by default. (FR#6)
- **AC#6** Unit tests cover each step of the credential precedence chain, including `--token-file` overriding `cli.auth_token` and `cli.auth_token` overriding `web_api.auth_token`. (FR#7)
- **AC#7** Unit tests assert no `authorization` header is sent when the target is non-loopback and the only available credential is `<data_dir>/.web_api_token`, and separately when it is `web_api.auth_token`. A third asserts `cli.auth_token` *is* sent to a non-loopback target. A fourth iterates `CREDENTIAL_SOURCES` and asserts every entry declares a `scope` of `cli` or `server`, so a source added later cannot omit the classification. (FR#8)
- **AC#8** Unit tests assert `localhost`, `LOCALHOST`, `127.0.0.1`, `127.0.0.53`, `::1`, `[::1]`, and `::ffff:127.0.0.1` classify as loopback while `192.168.1.5`, `example.com`, and `0.0.0.0` do not, with no DNS lookup performed. Non-divergence between the CLI and the server is guaranteed structurally rather than by a duplicated table: `grep -rn "_is_loopback_host" src/hassette/core/` returns no match, proving one definition remains and `WebApiService` calls the shared helper. (FR#9)
- **AC#9** A unit test asserts a request is issued (transport receives it) for a non-loopback target with no credential. (FR#10)
- **AC#10** A unit test asserts the 401 message for a suppressed-credential remote target names `--token-file`, `cli.token_file`, `HASSETTE__CLI__AUTH_TOKEN`, and `trusted_proxies`, and that the `trusted_proxies` mention is qualified as applying to the remote instance — asserted on the qualifying phrase, not on substring presence alone. (FR#11)
- **AC#11** A unit test asserts a 302 response produces an error mentioning a redirect, forward auth, and a pointer to the reverse-proxy docs section. (FR#12)
- **AC#12** `hassette run --help` lists `--ha-url` and does not list `--base-url` or `--url`; `uv run pytest tests/unit/cli/` passes. (FR#13)
- **AC#13** `uv run python scripts/export_schemas.py` produces no diff in `hassette.schema.json` after the `CliConfig` group is added and the schema is regenerated — i.e. `uv run python tools/check_schemas_fresh.py` exits 0.
- **AC#14** `prek -a && prek pyright -a --stage pre-push` exits 0.
- **AC#15** `uv run mkdocs build --strict` exits 0 with the rewritten CLI configuration page and the new reverse-proxy section in place.
- **AC#16** A unit test asserts a token file containing a non-ASCII character produces a usage error naming the file path, not an unhandled `UnicodeEncodeError`. (FR#15)
- **AC#17** Unit tests assert the resolved target appears in stderr output for a successful non-loopback request and is absent for a successful loopback request. A further test asserts it also appears for a 401 against a non-loopback target **without** `--debug`, so an implementation covering only the success path fails. (FR#16)
- **AC#18** A unit test asserts a config-sourced `verify_ssl=false` emits the warning while the `--no-verify-ssl` flag does not. (FR#17)
- **AC#19** `grep -n 'base-url\|--url' docs/pages/cli/commands.md` returns no match for the removed `hassette run` flag spellings. (FR#13)
- **AC#20** Unit tests assert a connection error and an HTTP error against `https://example.com/hassette` each report that full base URL — scheme and path prefix included — not a host-only or scheme-stripped form. (FR#14)

## Key Constraints

- **Do not reuse `_build_ha_url` or `_parse_and_normalize_url`** (`src/hassette/utils/url_utils.py:13-51`). Both discard the path component via `URL.build(..., path="/api/")`, which would silently destroy path-prefix support, and `_parse_and_normalize_url` rejects IPv6 outright, which would regress the CLI's existing `::1` handling. Reuse the *field shape* (`str` URL + `verify_ssl`) and the `yarl`-based lazy-parse style, not these functions.
- **Do not add a third copy of the bind-all substitution map.** `_BIND_ALL_SUBSTITUTIONS` already exists in `src/hassette/cli/client.py:26-30` and again in `src/hassette/web/auth.py:63-73` (the latter deliberately not importing to avoid a cycle). New resolution code routes through the existing `cli/client.py` copy.
- **Do not write a second loopback classifier.** `_is_loopback_host` (`src/hassette/core/web_api_service.py:45-58`) already does exactly what FR#9 needs — `ipaddress.ip_address(host).is_loopback` with a `localhost` fallback and no DNS. The reason not to import it directly is layering, not semantics: it sits in a `Service`-layer module the CLI should stay below. Move the function to `src/hassette/utils/net_utils.py` and have both callers import it from there. Writing a parallel CLI-side check instead would let the two silently disagree about `::ffff:127.0.0.1` — both classifiers feed the same trust decision, so a divergence is a security bug, not a style nit.
- **Do not resolve DNS to classify a target as loopback.** A DNS answer can change between the classification and the request, and resolving adds latency to every invocation. Literal matching fails safe — it withholds a credential from a host that might have been local, rather than sending one to a host that might not be.
- **Do not accept a bare token value as a CLI argument.** `design/specs/091-web-api-auth/design.md` establishes this: a secret passed as `--token <value>` is visible in shell history and `ps` output for the process lifetime. `--token-file` takes a path, never a value.
- **Do not add deprecation aliases for the renamed `hassette run` flags.** This ships as a breaking change with a `BREAKING CHANGE:` footer, not a soft deprecation.
- **Do not let `follow_redirects` default to `True`.** Verified `False` today. A forward-auth gateway issuing a login redirect must surface as a clear error, not silently follow to an HTML login page that then fails JSON parsing.

## Dependencies and Assumptions

- `yarl` is already available (transitive via `aiohttp`, pinned `1.22.0`, already imported in `url_utils.py`, `exceptions.py`, `harness.py`). No new dependency.
- Any new config field automatically gets `HASSETTE__CLI__*` env, `.env`, and TOML resolution via pydantic-settings' existing `settings_customise_sources` chain (`src/hassette/config/config.py:64-80`). No plumbing needed.
- `nested_model_default_partial_update=True` (`config/config.py:61`) means a partial `[hassette.cli]` TOML table does not wipe unset group defaults.
- **Validating against the author's live homelab requires a proxy-side change first.** Research proved (four requests, documented in the brief) that `tinyauth` returns 401 to a valid Hassette bearer token before the request reaches Hassette — it is browser-OIDC forward auth (`OAUTH_AUTO_REDIRECT=pocketid`) with no bypass configured. A correct implementation of this design still returns 401 there. Reaching that instance additionally requires one of: a second Traefik router for `/api` without the `tinyauth@docker` middleware, a tinyauth bypass rule for `/api/*`, or an SSH tunnel to `127.0.0.1:8126`. That change lives in the operator's own infrastructure config, not in this repo — it is a prerequisite for end-to-end validation, not a follow-up task.
- **Path-prefix behavior is unverified against a live stripping proxy.** `httpx2` joining is verified locally (see Architecture) and the server's lack of `root_path` is verified by reading `web/app.py` and `core/web_api_service.py`, but no end-to-end "proxy strips `/hassette`, Hassette sees `/api/...`" request has been observed. Verify with a temporary `PathPrefix(/hassette)` + `stripPrefix` router before relying on it.

## Architecture

### Where the target lives

A new `CliConfig` group in `src/hassette/config/models.py`, following the nine existing `ExcludeExtrasMixin, BaseModel` groups:

```python
class CliConfig(ExcludeExtrasMixin, BaseModel):
    """CLI client connect target, TLS, and credential settings."""

    model_config = ConfigDict(json_schema_extra={"ui": {"group_label": "CLI"}})

    server_url: str | None = Field(default=None, json_schema_extra={"ui": {"label": "Server URL"}})
    verify_ssl: bool = Field(default=True, json_schema_extra={"ui": {"label": "Verify SSL"}})
    token_file: Path | None = Field(default=None, json_schema_extra={"ui": {"label": "Token File"}})
    auth_token: SecretStr | None = Field(default=None, json_schema_extra={"ui": {"label": "Auth Token"}})
```

`auth_token` is `SecretStr` for the same reason `web_api.auth_token` is: the value is masked in logs, reprs, and the `GET /api/config` response, and is unwrapped only at the point of use. `token_file` is a path, not a secret, so it stays a plain `Path`.

Wired onto `HassetteConfig` alongside the existing groups (`config/config.py:82-106`):

```python
cli: CliConfig = Field(default_factory=CliConfig)
```

The group label goes on the model's own `model_config`, not on the `Field(json_schema_extra=)` in `HassetteConfig` — a nested-model field is emitted as a `$ref`, and the server-side deref (`jsonref.replace_refs`) drops `$ref` sibling keys, silently losing a `ui` block placed there. `WebApiConfig` carries a comment explaining this; follow it.

Separating `cli` from `web_api` is the point of the change, not incidental. `web_api.host`/`port` answer "where does the server bind?"; `cli.server_url` answers "where does the client connect?" Putting the second on `WebApiConfig` as a `client_url` field would leave one model holding both, with a relationship ("the second overrides the first two, but only for the CLI, and only when set") that is genuinely hard to write a docstring for.

### Global flags

Three new flags on the cyclopts meta launcher (`src/hassette/cli/__init__.py:117-141`), which today declares only `--config-file/-c`, `--env-file/-e/--env`, `--json`, and `--debug`:

| Flag | Short | Maps to |
|---|---|---|
| `--server-url` | `-s` | `CLIContext.server_url` |
| `--token-file` | — | `CLIContext.token_file` |
| `--no-verify-ssl` | — | `CLIContext.verify_ssl` (as `False`) |

`-s` is free — the only short flags in use are `-c`, `-e`, `-v` (meta) and `-a`, `-t`, `-u` (subcommands). `--token-file` takes no short flag because `-t` is `hassette run --token`.

There is deliberately **no** `--auth-token` flag. `cli.auth_token` is reachable by config and `HASSETTE__CLI__AUTH_TOKEN` only — a flag taking a literal secret would leave it in shell history and `ps` output, which Key Constraints prohibits.

`--server-url` rather than `--url` is forced by a real collision, not style. `src/hassette/cli/commands/run.py:25-27` declares:

```python
base_url: Annotated[
    str | None, Parameter(name=["--base-url", "-u", "--url"], help="Base URL of the Home Assistant instance.")
] = None
```

Meta-launcher flags and subcommand flags share a parse scope, so a global `--url` would sit next to `hassette run --url` meaning the opposite remote. `--server-url`/`-s` also matches `hass-cli`'s `--server`/`HASS_SERVER`, which this project's Home Assistant audience already knows.

Per FR#13 that subcommand flag collapses to a single name, `--ha-url` / `-u`. `--base-url` goes too, not just `--url`: three names for one flag was the underlying confusion, and leaving `--base-url` alive keeps two. The `base_url` *config field* is unchanged — inside `HassetteConfig` it is unambiguous, since the CLI's target now lives under a different group.

Flags flow into `CLIContext` (`src/hassette/cli/context.py`), which grows from two fields to five. Unlike `--config-file`/`--env-file`, which mutate class-level `model_config` in the launcher, these are per-invocation values with no reason to touch global state.

### Resolution

A new module, `src/hassette/cli/target.py`, owns target and credential resolution. Keeping it out of `client.py` matters: that file already mixes transport, error rendering, and app-routing concerns, and resolution is independently testable without an HTTP client.

It exposes a frozen dataclass and two functions:

```python
@dataclass(frozen=True)
class ServerTarget:
    base_url: str
    is_loopback: bool
    verify_ssl: bool
```

```python
def resolve_server_target(
    config: HassetteConfig, *, server_url_flag: str | None = None, verify_ssl_flag: bool | None = None
) -> ServerTarget: ...

def resolve_cli_auth_token(
    config: HassetteConfig, target: ServerTarget, *, token_file_flag: Path | None = None
) -> str | None: ...
```

`resolve_server_target` applies FR#1's precedence, normalizing an explicit URL through `yarl.URL` and deriving the fallback through the existing `_format_host`. `resolve_cli_auth_token` walks `CREDENTIAL_SOURCES` in order, skipping `server`-scoped entries when `target.is_loopback` is false.

Neither takes `CLIContext`. It is a frozen dataclass built solely by the cyclopts meta launcher out of parsed flags (`src/hassette/cli/context.py:9-19`) — passing it here would make "independently testable" mean "testable once you hand-build a cyclopts carrier type," and would force any future non-CLI caller (a Python client library, or the `api_url`/`ws_url` overrides ADR-0005 already anticipates) to fabricate one purely as an argument vehicle. `make_client(ctx)` is the single place that unpacks `ctx.server_url` / `ctx.token_file` / `ctx.verify_ssl` into these keyword arguments, keeping the flag-parsing layer at the edge where it belongs.

Normalization follows `url_utils.py`'s style — parse with `yarl.URL`, raise a dedicated exception per failure mode — without calling its functions. Two new exceptions in `src/hassette/exceptions.py` alongside the existing `BaseUrlRequiredError` / `SchemeRequiredInBaseUrlError` / `IPV6NotSupportedError` (all `FatalError` subclasses, lines 48-56): one for a missing scheme, one for a path ending in `/api`. `HassetteCLIClient.__init__` catches both and routes them through the existing `error_usage()` path so they render as usage errors rather than tracebacks.

The derived branch keeps every existing loopback behavior byte-identical, so `TestBaseUrl`'s four tests stay green unmodified and the risk surface is the new explicit-target branch only.

### Path prefixes are free

The issue asserts path-prefix support "touches every call site in `client.py`." That is incorrect. The CLI uses `httpx2`, whose `base_url` merging preserves the base path. Verified directly against the installed version:

```
'http://h:8126'                       + /api/health -> http://h:8126/api/health
'https://x.example.com/hassette'      + /api/health -> https://x.example.com/hassette/api/health
'https://x.example.com/hassette/'     + /api/health -> https://x.example.com/hassette/api/health
'https://x.example.com/hassette/api'  + /api/health -> https://x.example.com/hassette/api/api/health
```

Every command path already starts with `/api/...`, so a prefix supplied without a trailing `/api` composes correctly with no change at any call site — every `client.get(...)` and `client.get_with_app_routing(...)` in `src/hassette/cli/commands/`, plus the two internal `self.get(...)` calls in `client.py`. The last row is the hazard FR#4 addresses — and the issue's own example URL (`https://hassette.example.com/hassette/api`) is that broken form, so the validator prevents users copying a 404 straight out of the issue text.

### Credential scoping

The credential sources split into two kinds, and that split — not the individual sources — is the rule:

| Source | Scope | Applies to |
|---|---|---|
| `--token-file` | CLI | any target |
| `cli.token_file` | CLI | any target |
| `cli.auth_token` | CLI | any target |
| `web_api.auth_token` | server | loopback only |
| `<data_dir>/.web_api_token` | server | loopback only |

That table is the data model, not just documentation. `cli/target.py` declares the sources as an ordered list of records, and the resolver walks it:

```python
@dataclass(frozen=True)
class CredentialSource:
    name: str
    scope: Literal["cli", "server"]
    resolve: Callable[[CredentialInputs], str | None]

CREDENTIAL_SOURCES: tuple[CredentialSource, ...] = (...)  # in FR#7 precedence order
```

`resolve_cli_auth_token` skips any entry whose `scope` is `"server"` when `target.is_loopback` is false — it never names an individual source. This matters because the alternative is a hand-written two-item skip, and that is precisely the shape of the bug already found once in this design: `web_api.auth_token` sat above the token file in precedence with no gate, because the invariant lived in prose and had to be re-derived by hand. The design itself calls `cli` "the natural home for the follow-on CLI settings this will attract," so there *will* be a sixth source. With a source list, adding one forces a `scope` value at the point of definition and the gate applies for free; with a named skip, the contributor has to know the rule exists and remember to extend it.

Both server-scoped sources describe the credential *the local service validates against*. `<data_dir>/.web_api_token` is the file that service wrote for itself (`hassette.web.auth.resolve_auth_token`); `web_api.auth_token` is the configured value it checks incoming `Authorization` headers against. Neither is a statement about what some *other* instance accepts. Attaching either to a remote target sends one instance's bearer token to a host that does not validate against it: a leak toward an arbitrary third party, and useless even when it is not.

Gating only the file would have been a half-measure — `web_api.auth_token` sits *above* it in precedence, so an operator with a token in their local `hassette.toml` would leak it to a remote target while the lower-priority file was dutifully withheld. Both are server settings being read by a client; both get the same gate.

That is also why `cli.auth_token` exists rather than leaving `HASSETTE__WEB_API__AUTH_TOKEN` as the remote credential env var. Once `web_api.auth_token` is loopback-gated, a remote target needs a CLI-scoped direct-value source, and `HASSETTE__CLI__AUTH_TOKEN` is the symmetric answer. The resulting rule states in one sentence: **`cli.*` credentials work anywhere; `web_api.*` credentials are for the local instance only.** Every existing local user keeps working unchanged, since loopback is exactly the case where the server-scoped sources still apply.

`--token-file` is preferred over `cli.auth_token` for remote use — a path in config or a flag leaves no secret in an environment variable that child processes inherit — but both are supported, and the flag outranks both config forms.

Suppression keys off the resolved target regardless of which source supplied the URL. `resolve_server_target` returns `is_loopback` rather than having the credential resolver recompute it: the classification is a property of the target, decided once where the target is built. It classifies the host in `yarl.URL.host`'s unbracketed form, so `::1` and `[::1]` are the same input by the time it runs, and it calls the shared `is_loopback_host()` from `utils/net_utils.py` — the same function `WebApiService` uses to decide whether an unauthenticated bind is acceptable. One definition, because both feed the same trust decision.

### Failing open, not fast

A non-loopback target with no credential still issues the request (FR#10). Failing fast would look tidier but would break a valid topology: `trusted_proxies` (`config/models.py:385-394`) exists precisely so a forward-auth gateway's own authentication stands in for Hassette's, and a request arriving through such a proxy needs no bearer token at all. That is not hypothetical — it is the configuration the motivating homelab runs (`trusted_proxies = ["traefik"]`). Refusing to send a credential-less request would make that deployment unreachable by the CLI.

The cost of failing open is one wasted round-trip in the genuinely-missing-credential case, paid back by FR#11's error message.

Failing open does create a second risk the error message does not cover: a mistyped or stale `server_url` that happens to answer `200` with plausible JSON — a forgotten dev box, a proxy's default backend, the wrong instance — renders as ordinary successful output with nothing naming the host that answered.

Today's echoing is thinner than it looks. `_handle_network_error` does include the base URL unconditionally (`client.py:151-155`), but `_handle_http_error` only prints it when `--debug` is set, in both human and JSON modes (`client.py:266-273`). So a plain 401 or 302 against the wrong host names no host either, and a success names nothing at all. FR#16 therefore adds behavior on *both* paths: the resolved non-loopback target is surfaced on success, and on HTTP-error responses it is surfaced without requiring `--debug`. Loopback stays silent on both: it is the zero-config default and the one case where "which host answered" is never in question.

### Transport

`httpx.Client` (`client.py:107`) gains `verify=target.verify_ssl`. `follow_redirects` stays `False` (verified default), with FR#12 adding a 3xx-specific branch in `_handle_http_error` — a login redirect from a forward-auth gateway is now a likely enough failure that the generic "Error 302" message is not enough.

`verify_ssl=False` needs to stay visible, not just opt-in. The flag form is a conscious per-invocation choice; the config form is not — set once against a self-signed dev box, it silently persists in that profile and keeps applying after `cli.server_url` is later repointed at a real endpoint, with nothing binding the opt-out to the target that needed it. FR#17 warns for the config-sourced case only, following the precedent `WebApiService.on_initialize()` already sets for an insecure-posture warning (`web_api_service.py:115-121`).

## Implementation Preferences

- **cyclopts** for the new flags, matching the existing meta launcher. No argparse, no click.
- **`yarl.URL`** for parsing, matching `url_utils.py`. Not `urllib.parse`, not pydantic's `AnyUrl`/`HttpUrl` — the codebase's established precedent for a user-supplied URL is a plain `str` field parsed lazily at point of use (`HassetteConfig.base_url`, `config/config.py:130`), which keeps the error messages under our control.
- **`FatalError` subclasses** in `src/hassette/exceptions.py` for URL validation failures, matching `BaseUrlRequiredError` and siblings.
- **`Path`** for `cli.token_file`, not `str` — pydantic coerces and the type documents intent. **`SecretStr`** for `cli.auth_token`, matching `web_api.auth_token`, so it is masked in logs and `GET /api/config` and unwrapped only at the point of use.
- No `from __future__ import annotations`; `X | None` over `Optional[X]`; imports at module top.

## Replacement Targets

| Target | Replaced by | Disposition |
|---|---|---|
| `HassetteCLIClient.__init__`'s inline `f"http://{host}:{port}"` (`client.py:98-100`) | `resolve_server_target()` in `cli/target.py` | Remove outright — the derived path moves into the resolver's fallback branch |
| `_resolve_cli_auth_token` (`client.py:48-84`) | `resolve_cli_auth_token()` in `cli/target.py` | Move and extend with the loopback gate; do not leave a shim in `client.py` |
| `hassette run --base-url` / `-u` / `--url` (`commands/run.py:26`) | `--ha-url` / `-u` | Remove outright; no alias, no deprecation warning |
| `_is_loopback_host` (`core/web_api_service.py:45-58`) + `_LOOPBACK_HOSTNAMES` (`:41`) | `is_loopback_host()` in `utils/net_utils.py` | Move, don't copy — `WebApiService` imports it from the new home; no local definition remains |
| The duplicate-rather-than-cycle note in `web/auth.py:71` | A pointer to the shared `utils/net_utils.py` helper | Rewrite — that function is no longer an instance of accepted duplication, so citing it as one is now misleading |
| "Remote instances" tip (`docs/pages/cli/configuration.md:18-30`) | New remote-target section | Rewrite — the `HASSETTE__WEB_API__HOST` recipe it documents is the antipattern this change fixes |

## Convention Examples

### Nested config group

**Source:** `src/hassette/config/models.py:538-549`

```python
class FileWatcherConfig(ExcludeExtrasMixin, BaseModel):
    """File watcher debounce, step, and enable/disable settings."""

    debounce_milliseconds: int = Field(default=3000)
    """Debounce time for file watcher events in milliseconds."""

    step_milliseconds: int = Field(default=500)
    """Time to wait for additional file changes before emitting event in milliseconds."""

    watch_files: bool = Field(default=True)
    """Whether to watch files for changes and reload apps automatically."""
```

Docstrings go *below* each field as bare string literals, not in a `description=` kwarg. Every field uses `Field(default=...)` even when a bare default would do.

### Lazy URL parsing with dedicated exceptions

**Source:** `src/hassette/utils/url_utils.py:27-42`

```python
if not config.base_url:
    raise BaseUrlRequiredError(f"base_url must be set in the configuration, got: {config.base_url}")

cleaned_url = config.base_url.strip().strip("'\"")
yurl = URL(cleaned_url)

if not yurl.scheme:
    raise SchemeRequiredInBaseUrlError(f"base_url must include a scheme (http:// or https://), got: {cleaned_url}")
```

One exception type per failure mode, each message echoing the offending value. Note the `.strip("'\"")` — quoted values arrive from `.env` files and are stripped defensively. Follow the style; do not call these functions (see Key Constraints).

### Global flag declaration on the meta launcher

**Source:** `src/hassette/cli/__init__.py:117-131`

```python
@app.meta.default
def launcher(
    *tokens: Annotated[str, Parameter(show=False, allow_leading_hyphen=True)],
    config_file: Annotated[
        str | None, Parameter(name=["--config-file", "-c"], help="Path to the TOML configuration file.")
    ] = None,
    json: Annotated[bool, Parameter(name=["--json"], help="Output results as JSON.", negative=[])] = False,
) -> None:
```

Explicit `name=[...]` lists including the short form. `negative=[]` on booleans suppresses cyclopts' auto-generated `--no-*` variant — omit it on `--no-verify-ssl`, where the negative form *is* the flag.

### Credential test shape

**Source:** `tests/unit/cli/test_client.py` (`TestCredentialAttachment`)

```python
def test_falls_back_to_token_file_when_config_value_absent(self, tmp_path: Path) -> None:
    (tmp_path / TOKEN_FILENAME).write_text("file-token", encoding="utf-8")
    factory = CLIClientFactory(_make_config_for_auth(tmp_path))
    client, captured_headers = factory.build_capturing_headers()
    client.get(HEALTH_ENDPOINT, dict)
    assert captured_headers[0]["authorization"] == "Bearer file-token"
```

Credential assertions read the captured request header, never an internal attribute. Extend `CLIClientFactory` and `_make_config_for_auth` rather than writing new local builders — see `.claude/rules/test-conventions.md`.

## Alternatives Considered

**A `web_api.client_url` field instead of a `cli` group.** Smaller diff — no new group, no new TOML table. Rejected because it perpetuates the exact conflation this issue exists to fix: `WebApiConfig` would hold both bind settings and a connect setting, and the `client_` prefix on fields in a server-settings model is a naming smell signalling the field is in the wrong place. It also leaves no home for the follow-on CLI settings this will attract, so the group gets added later anyway and the migration cost is paid twice.

**Config and env only, no new flags.** Smallest possible diff; `--config-file` already exists and profile files scale better to multi-instance use than a single flag. Rejected because `hassette --server-url https://... status` is materially better for the one-off query that is the common CLI case, and every comparable tool (`hass-cli`, `kubectl`, `docker`) offers a flag — its absence reads as an omission.

**Soft-deprecating `--url`/`-u` with hidden aliases.** Rejected per the sign-off decision: aliases mean carrying two names indefinitely, and the whole point of the rename is that having three names for one flag was already confusing. The break is loud, versioned, and documented in a `BREAKING CHANGE:` footer.

**Failing fast when a remote target has no credential.** Rejected — it would break `trusted_proxies` deployments, where no bearer token is the correct configuration. See Architecture → Failing open, not fast.

**Removing web API token auto-generation entirely.** Raised during discovery as a possible root-cause fix: if Hassette did not auto-generate `<data_dir>/.web_api_token`, there would be less confusion about where a token belongs. Rejected on two grounds. First, auto-generation exists so a fresh install is secure with zero configuration (`design/specs/091-web-api-auth/design.md`); removing it means first start either fails, runs unauthenticated, or needs a separate setup command — all worse for the common local case. Second, it would not fix the remote case: an operator would still need a way to say "here is the credential for *that* instance," which is the actual gap. The token file is not wrong to exist; it is correctly scoped to the local instance and was being read as a global default. `--token-file` plus loopback scoping addresses that directly.

**Resolving DNS to classify loopback.** Would let `myhost.local` resolving to `127.0.0.1` keep the file fallback. Rejected — see Key Constraints.

## Test Strategy

### Required Test Types

**Unit** — the whole change is resolution logic behind one construction site, exercised through `httpx.MockTransport`. `tests/unit/cli/test_client.py` already covers base-URL construction and credential attachment via captured request headers, which is the correct surface for every FR here.

**System** — `tests/system/test_cli_smoke.py` runs the CLI against a real server and hardcodes `f"http://127.0.0.1:{port}"` (line 67). It must keep passing unchanged, proving the derived path did not regress.

Gap: no test exercises a real TLS or path-stripping proxy. FR#2's prefix composition is covered at the `httpx` level (verified above and asserted in AC#2), but the end-to-end proxy behavior is verified manually per Dependencies and Assumptions.

### Existing Tests to Adapt

- `tests/unit/cli/test_client.py` — `TestBaseUrl` (4 tests) must pass **unmodified**; that is the regression signal for FR#1's fallback. `TestCredentialAttachment` (12 tests) currently exercises `_make_config_for_auth(tmp_path)` with a loopback default, so it stays green, but the helper needs extending to build non-loopback targets for AC#7.
- `tests/unit/cli/conftest.py` — `CLIClientFactory` needs to accept a `CLIContext` so flag-sourced targets can be tested.
- Any test invoking `hassette run --base-url` or `--url` must move to `--ha-url` (FR#13).

### New Test Coverage

| Behavior | FR | Layer |
|---|---|---|
| Target precedence: flag > config > derived | FR#1 | unit |
| Scheme, port, and path prefix preserved through to request URL | FR#2 | unit |
| Scheme-less URL rejected with corrected form named | FR#3 | unit |
| `/api`-suffixed URL rejected with corrected form named | FR#4 | unit |
| Trailing slash normalized | FR#5 | unit |
| IPv6 literal target round-trips | FR#2 | unit |
| `verify=` passed through from config and flag | FR#6 | unit |
| Credential precedence across all five sources | FR#7 | unit |
| Token file and `web_api.auth_token` both suppressed for non-loopback target | FR#8 | unit |
| `cli.auth_token` and `cli.token_file` sent to a non-loopback target | FR#8 | unit |
| Loopback classification table incl. bracketed IPv6, no DNS | FR#9 | unit |
| Request issued despite no credential | FR#10 | unit |
| 401 message names all three remedies | FR#11 | unit |
| 3xx message names redirect and forward auth | FR#12 | unit |
| Missing `--token-file` path is a usage error | edge case | unit |
| Missing `cli.token_file` path falls through to the next source | edge case | unit |
| Non-header-safe token content is a usage error, not a traceback | FR#15 | unit |
| Error messages carry scheme and prefix | FR#14 | unit |
| Resolved non-loopback target surfaced on the success path | FR#16 | unit |
| Config-sourced `verify_ssl=false` warns; the flag does not | FR#17 | unit |

### Tests to Remove

No tests to remove. Every existing test either stays as-is or is adapted per above.

## Documentation Updates

- **`docs/pages/cli/configuration.md`** — the main rewrite.
  - "Discovery Order" (lines 5-16) now describes target resolution, with `--server-url` at the top and the bind-derived address as the last resort.
  - The "Remote instances" tip (lines 18-30) is replaced. Its `HASSETTE__WEB_API__HOST=192.168.1.100` recipe is the antipattern being fixed and must not survive as a suggestion.
  - "Web API Token" gains `--token-file`, `HASSETTE__CLI__AUTH_TOKEN`, and the CLI-scoped-vs-server-scoped table from Architecture → Credential scoping, with the reason (`web_api.*` describes what the local instance accepts, not what a remote one does). The current text presents `HASSETTE__WEB_API__AUTH_TOKEN` as *the* way to point the CLI at a token; that framing must change, since it now applies to loopback targets only.
  - "Common Errors" (lines 135-149) gains the redirect case and the suppressed-token 401 case.
  - **New section: letting CLI traffic through a reverse proxy.** One concrete worked example — a forward-auth gateway that rejects bearer tokens, and the shape of the change that lets `/api/*` through on Hassette's own token. Deliberately not a Traefik/Caddy/nginx reference; it links to the existing guidance in `docs/pages/web-ui/index.md:30-49` rather than duplicating it, matching that section's length and register.
  - **The example is written in proxy-agnostic language** — "add a route for `/api/*` that skips your gateway's login middleware, and let Hassette's own bearer token authenticate those requests instead" — with no product-specific nouns (no `middlewares`, no `handle`, no `location`). Two sources would otherwise pull it in different directions: the section it links to (`docs/pages/web-ui/index.md:38-40`) is written in Caddy, while the only concrete worked material available is the Traefik-flavored live validation in the research brief. A reader following the existing Caddy walkthrough and then landing on a Traefik section for the same deployment has to translate mid-task. Product-neutral phrasing avoids that without adding a second example or picking a proxy this project hasn't otherwise favored.
  - **The worked example covers subdomain routing only.** That is the topology verified end-to-end against a live deployment. Path prefixes are supported in code (FR#2) and mentioned in the field reference, but no worked prefix example ships until the `PathPrefix` + `stripPrefix` round-trip in Dependencies and Assumptions has actually been observed. Publishing a step-by-step recipe for a mechanism never seen working end-to-end is worse than publishing nothing: the reader following it is debugging under an outage, and the guidance itself is the unknown. Defer that example to a follow-up.
  - **New: an upgrade warning.** A `!!! warning "Upgrading from a previous version"` admonition naming the two silent behavior changes (the bind-host remote recipe and `HASSETTE__WEB_API__AUTH_TOKEN` scoping) and what a script relying on either must change. The changelog footer is not enough on its own — those two break at runtime rather than at parse time, so a script keeps running and either starts 401ing or, against a target with `auth_enabled=False` or a matching `trusted_proxies` entry, silently succeeds unauthenticated. This page is where a returning user looks.
- **`docs/pages/cli/commands.md`** — the `hassette run` flag table hand-documents `--base-url`/`-u`/`--url`. FR#13 removes them, so the table goes stale and a reader following it gets a cyclopts "unknown option" error. AC#12 only checks `--help` and the unit tests, so nothing else catches this.
- **`docs/pages/core-concepts/configuration/index.md`** — the "Configuration Sections" table lists the existing config groups and is the page a reader confused between `base_url`, `web_api.host`/`port`, and `cli.server_url` would consult. Add a `[hassette.cli]` row.
- **`docs/pages/web-ui/index.md`** — one cross-link from the existing reverse-proxy admonition to the new CLI section. No rewrite; #1117's content stands.
- **`hassette.schema.json`** — regenerated via `uv run python scripts/export_schemas.py` (AC#13).
- **CLI help text** — `--server-url`, `--token-file`, `--no-verify-ssl` help strings, and `--ha-url`'s.
- **No CHANGELOG edit.** release-please generates it. The PR title and `BREAKING CHANGE:` footer are the changelog surface — see `.claude/rules/changelog-quality.md`.

Per `.claude/rules/doc-rules.md`, run `doc-persona-review` and `doc-accuracy-review` scoped to `cli/configuration`, `cli/commands`, and `core-concepts/configuration` before opening the PR. Those reviews only look at pages in the docs diff, so a page omitted from Changed Files is a page the accuracy review never reads.

## Impact

### Changed Files

| File | Verb | Change |
|---|---|---|
| `src/hassette/config/models.py` | modify | Add `CliConfig` group |
| `src/hassette/config/config.py` | modify | Wire `cli: CliConfig` onto `HassetteConfig` |
| `src/hassette/exceptions.py` | modify | Two `FatalError` subclasses for server-URL validation |
| `src/hassette/utils/net_utils.py` | create | `is_loopback_host()` moved out of `core/web_api_service.py` so CLI and server share one classifier |
| `src/hassette/core/web_api_service.py` | modify | Import `is_loopback_host` from utils; drop the local `_is_loopback_host` and `_LOOPBACK_HOSTNAMES` |
| `src/hassette/web/auth.py` | modify | Docstring at `:71` cross-references the old location of `_is_loopback_host`; repoint it and drop the duplicate-rather-than-cycle framing |
| `src/hassette/cli/target.py` | create | `ServerTarget`, `resolve_server_target`, `resolve_cli_auth_token` |
| `src/hassette/cli/client.py` | modify | Consume the resolver; add `verify=`; 3xx and suppressed-token error branches; remove inline URL build and `_resolve_cli_auth_token` |
| `src/hassette/cli/context.py` | modify | Add `server_url`, `token_file`, `verify_ssl` to `CLIContext` |
| `src/hassette/cli/__init__.py` | modify | Three global flags on the meta launcher |
| `src/hassette/cli/commands/run.py` | modify | `--base-url`/`-u`/`--url` → `--ha-url`/`-u` |
| `hassette.schema.json` | modify | Regenerated |
| `tests/unit/cli/test_client.py` | modify | New coverage per Test Strategy |
| `tests/unit/cli/conftest.py` | modify | `CLIClientFactory` accepts a `CLIContext` |
| `docs/pages/cli/configuration.md` | modify | Rewrite target/token sections; new reverse-proxy section; upgrade warning |
| `docs/pages/cli/commands.md` | modify | `hassette run` flag table: drop `--base-url`/`--url`, document `--ha-url` |
| `docs/pages/core-concepts/configuration/index.md` | modify | Add `[hassette.cli]` row to the Configuration Sections table |
| `docs/pages/web-ui/index.md` | modify | One cross-link |

### Behavioral Invariants

Must not change:

- `hassette status` with no flags and no `[hassette.cli]` config resolves `http://127.0.0.1:8126` and attaches `<data_dir>/.web_api_token`. This is the zero-config path and the reason `TestBaseUrl` stays unmodified.
- Bind-all substitution: `0.0.0.0` → `127.0.0.1`, `::` → `[::1]`.
- Exit codes: 1 for HTTP and usage errors, 2 for network errors.
- The CLI never generates a token (`test_missing_token_never_calls_generating_resolver`).
- No secret is accepted as a bare CLI argument value.
- `tests/system/test_cli_smoke.py` passes unchanged.

**Deliberately changed** (all three belong in the `BREAKING CHANGE:` footer):

- `hassette run --base-url` / `--url` no longer exist; use `--ha-url`.
- `HASSETTE__WEB_API__HOST=<non-loopback> hassette status` no longer sends `<data_dir>/.web_api_token`. Previously documented as the way to query a remote instance; it now requires a CLI-scoped credential, or `--server-url` plus `--token-file`.
- `HASSETTE__WEB_API__AUTH_TOKEN` applies to loopback targets only. For a remote target use `--token-file`, `cli.token_file`, or `HASSETTE__CLI__AUTH_TOKEN`.

### Blast Radius

Contained. The CLI is a read-mostly client with one construction site, and no non-CLI code imports `cli/client.py`. The two breaking changes affect operator muscle memory and any scripts wrapping `hassette run --url` or relying on the bind-host remote recipe — both surfaced in the changelog.

`CliConfig` appears in `GET /api/config` and the config UI like every other group; no frontend change is required, since that view renders groups generically. `cli.auth_token` is `SecretStr` and is masked there exactly as `web_api.auth_token` already is; `cli.token_file` is a path, not a secret, so it renders as-is.

## Open Questions

None.
