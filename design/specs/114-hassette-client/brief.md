# Brief: hassette-wire and hassette-client, One Contract and One Client

**Date:** 2026-09-25
**Status:** explored and challenged (2026-09-25; findings resolved in this revision). Every
decision here is provisional until `/mine-define`.
**Epic:** HACS companion integration (`design/specs/113-hacs-companion-integration/brief.md`).
This brief replaces unit B of that epic.

## Idea

Hassette's HTTP API will soon have three Python consumers: the CLI, the HA integration
(`hass-hassette`), and any remote CLI a user runs from another machine. Today the only Python
client is `HassetteCLIClient` (`src/hassette/cli/client.py`, 704 lines). It is synchronous
(`httpx2`), exits the process on errors, and imports hassette's config and models, so nothing
else can reuse it.

The earlier plan for unit B added a second client: an async `hassette-client` package covering
five endpoints, with hand-mirrored response models, a contract test to catch drift, and its own
release train. That leaves two clients and two copies of the models. This brief replaces it with
one package for the wire contract, one client every consumer uses, and a CLI that is only
presentation.

**Governing value:** the best end-state software. Hassette has two known users, so breaking
changes are acceptable when they buy a better design.

## Key Decisions Made

### Packages

- **Three packages in one uv workspace:**

  | Package | Import | Holds | Depends on |
  |---|---|---|---|
  | `hassette-wire` | `hassette_wire` | The wire contract: request/response models, WS messages, wire enums | pydantic |
  | `hassette-client` | `hassette_client` | The async transport; the CLI behind a `[cli]` extra | `hassette-wire`, aiohttp (`[cli]`: cyclopts, rich) |
  | `hassette` | `hassette` | The framework and server | `hassette-wire`, `hassette-client[cli]` |

  Every dependency edge means one thing: the framework depends on the contract, and depends on
  the client only for the `hassette` command. Nothing in hassette imports `hassette_client`.
  This is the layout Music Assistant uses (`music-assistant-models`, `-client`, server), in the
  same Open Home Foundation ecosystem.
  - The earlier revision put the models inside `hassette-client`, with the server importing
    them. No surveyed project does that, and the package name invites client-side assumptions
    about the authoritative contract. It was rejected.
  - Other names were rejected because they collide with existing hassette modules:
    `hassette-models` (`hassette.models` holds the HA entity state models), `hassette-api`
    (`hassette.api` is the HA API client), and `hassette-schemas` (`hassette.schemas`).
  - The cost is a third published artifact (a PyPI trusted publisher, `extra-files`, Dockerfile
    metadata lines, nox and CI wiring) and a publish order. Both are one-time.
- **One release train, lockstep versions.** All three packages release from hassette's existing
  release-please train at the same version, and each pins the others exactly. The HA integration
  still requires `hassette-client` as a range, never an exact pin (epic brief). There's no second
  release PR, no tag-prefix routing, no GitHub "Latest" badge workaround, no split drift checks,
  and no separate release-verify job.
  - Mechanism: `release-please-config.json` keeps its single `"."` component and writes the
    version into `wire/pyproject.toml` and `client/pyproject.toml` via `extra-files`. There's one
    release PR and one tag.
  - The publish job uploads `hassette-wire`, then `hassette-client`, then `hassette`. A
    half-finished publish only ever leaves a newer package that nothing depends on yet.
- **Neither `hassette-wire` nor `hassette-client` may depend on `hassette`.** HA installs
  integration requirements under its own constraints, and hassette's dependency tree (FastAPI,
  aiosqlite, structlog and more) doesn't belong there. Floors sit at or below what HA pins.
- **The frontend is unchanged.** It keeps generating TypeScript types from `openapi.json`.

### The wire contract

- **One definition of the API.** The server serves the `hassette_wire` models, the client parses
  them, and OpenAPI (and so the frontend's types) is generated from them. Hassette and the client
  version it pins can't drift. This was chosen over hand-mirrored copies plus a contract test,
  which the earlier plan used, and over Python models generated from `openapi.json`, which still
  leaves two model sets, and generated models read worse than hand-written ones.
- **A type lives in `hassette-wire` if and only if it goes over the wire.** There are two
  categories:
  - **Wire models move.** Every `*Response` and WS message in `web/models.py`, `SystemStatus`
    and the WS event payloads in `schemas/domain_models.py`, and the telemetry models
    (`Execution`, `JobSummary`, `ListenerSummary`, `ActivityFeedEntry`, and the rest). The
    read-side query modules build the telemetry ones directly from DB rows
    (`Execution.model_validate(row_to_dict(row))` in `core/telemetry/*_queries.py`) and routes
    return them unchanged. Producing API data is those modules' whole job, so the DB-to-wire
    mapping lives in their SQL aliases, with no separate mapping layer.
  - **Internal models stay in hassette.** The `schemas/app_snapshots.py` dataclasses
    (`AppInstanceInfo`, `AppManifestInfo`, and so on) carry live runtime state, including
    `error: Exception`. The web layer already maps them into `*Response` models, and that
    mapping stays.

  Two definitions are only a problem when they describe the same thing. A server wire model and a
  client wire model are the same thing, and the shared package removes that duplication. An
  internal domain object and its wire DTO are different things that overlap. Mapping between
  them is the boundary doing its job, and pyright checks it. The reverse is the real smell:
  putting internal or persistence types on the wire, so that every refactor or column rename
  breaks the API. Accepted trade-off: the telemetry wire models tie the DB query shape to the
  API, so a column rename needs a SQL alias to keep the wire stable. That's how it works today.
- **Enforced by a check, not convention.** `tools/check_module_boundaries.py` gets two rules:
  - Only the modules that construct or return wire models may import `hassette_wire`: `web/`,
    the read-side query modules (`core/telemetry/`, `runtime_query_service`), and the WS
    broadcasters.
  - Nothing in `hassette` imports `hassette_client`. The CLI plugin reaches the client's CLI
    through the entry point's `register(app)` argument, not an import.

  Today the checker can't express the first rule: `layer_of()` returns only the top-level
  package (`tools/check_module_boundaries.py:202-205`), so `core/telemetry/` and the rest of
  `core/` look identical to it. Issue 0 adds first-class nested-module scoping. If that hasn't
  landed by 3b, a path-prefix allowlist (modeled on `PRIVATE_ATTR_ALLOWLIST`) stands in, and
  issue 0 removes it.
- **Wire enums are separate from hassette's internal enums.** The same domain-vs-wire rule
  applies to enums. `hassette.types.enums` stays internal: 51 modules across every layer of `src/hassette` import it,
  and `ExecutionMode` is public app-author API (`hassette/__init__.py:23,48`). `hassette_wire`
  gets its own `StrEnum`s with the same string values. Telemetry models fill from DB strings, so
  they use the wire enums directly with no mapping. Only the domain-to-wire path
  (`app_snapshots` → `*Response`) maps, and it already does. Exhaustive `match` with
  `assert_never` makes pyright flag a new internal member that the mapping doesn't handle.

### Version skew

- **Lenient parsing is a client-side validation mode.** The HA integration must survive a newer
  server: unknown fields are ignored, and an unknown enum value parses as `UNKNOWN`. The wire
  enums support that through a pydantic validation context, which only `hassette_client` sets.
  The server validates strictly and never emits `UNKNOWN`, so HA's closed option lists (such as
  the six `ManifestStatus` values) stay closed server-side. This matches the prior-art norm: one
  model class, with strictness chosen where it's validated (pydantic strict mode, Stripe's open
  enums, protobuf's open enums).
- **Lenient parsing covers additive changes only. Anything else fails loudly.** A renamed or
  retyped field, or a missing required one, raises a distinct response-validation error, never
  a silent misparse. C maps it to `UpdateFailed`. Version skew gets a floor and a warning, not a
  ceiling: C's setup check already rejects servers below `MIN_HASSETTE_VERSION` (epic brief), and
  the client also exposes whether the server's version is newer than its own, which C logs as a
  warning without blocking.
- **Wire fields added after the first release are optional with a default.** The HA
  integration's client can be newer than the user's server, as long as the server is above
  `MIN_HASSETTE_VERSION`. A required field the older server doesn't send would fail every call.
  Music Assistant's mobile app hit exactly this (music-assistant/mobile-app#1012). Adding a
  required wire field means bumping `MIN_HASSETTE_VERSION`.
- **CI catches cross-version breaks before release.** A PR-triggered job, run when
  `hassette_wire` changes, installs the latest released `hassette-client` and `hassette-wire` in
  an isolated environment and runs the client against the HEAD server's endpoints. An
  intentional break then fails loudly before release, which prompts the changelog entry and the
  integration's range bump instead of leaving them to be found in the field. The
  optional-new-fields rule covers the other direction (a newer client against an older server).

### The client

- **The client covers the whole API.** `hassette_client` is async `aiohttp` with a caller-owned
  session (HA's `inject-websession` rule), a typed exception hierarchy mapped from status codes,
  explicit per-request timeouts, and typed methods for every endpoint the CLI uses today (19
  endpoint patterns, 23 routes once the action variants are expanded; see Codebase Context).
  Being 0.x and moving in lockstep with the server, typed methods don't freeze anything. The
  `code` discriminator applies only to the app action routes (issue 1). Other endpoints'
  400/404/409 responses stay `detail`-string only until #2369 extends problem details repo-wide.
- **Client requirements the HA integration (epic unit C) relies on:**
  - The token is optional. Without one, the client sends no `Authorization` header at all, so a
    hassette server that lists HA's address in `web_api.trusted_proxies` admits it by peer
    trust. Today's CLI client already behaves this way (`cli/client.py:126`).
  - A 503 raises its own exception type, whatever the body. `GET /api/apps/manifests` answers
    503 when its DB read fails (`web/routes/apps.py:180-186`), and C must treat that as "update
    failed", never as "every app was removed".
  - A 409 is split by problem-details `code` (issue 1) into "bootstrap not released" and "app
    blocked", instead of by matching `detail` prose.
  - A 401, a 404, a 500 action failure, a connection error, and a timeout each raise a distinct
    type. C maps them to `ConfigEntryAuthFailed`, `ServiceValidationError` or
    `HomeAssistantError` as the epic brief lists. A 400 (`invalid_app_key`) and
    `instance_not_found` still get typed errors, but C never hits them in v0.1: app keys come
    from the manifest list, never from user input, and v0.1 is app-level only.
  - `get_health()` exposes the server `version`, which C's setup check compares against its
    `MIN_HASSETTE_VERSION`.

### The CLI

- **The CLI moves into `hassette-client`, behind a `[cli]` extra.** `pip install
  hassette-client[cli]` adds cyclopts and rich plus the `hassette` command with every query and
  action command. The motivating case is real: controlling a hassette server on a VPS or desktop
  from a laptop without installing the whole framework. Hassette depends on
  `hassette-client[cli]`, so a full install still gets the same command.
- **Server-only CLI parts plug in through an entry point.** `hassette run` and local target
  discovery (which reads `HassetteConfig` and the token file) cannot move to the client. There is
  exactly one `hassette` console script, declared only by `hassette-client[cli]`.
  - Contract: hassette registers one entry point in the `hassette.cli` group, whose target is a
    callable `register(app)`. It adds `run` and local target discovery to the cyclopts app. On
    a client-only install the group is empty: no `run`, and targets come from flags, environment
    variables, or the client config file. If loading the plugin fails, the CLI prints a warning
    naming it and carries on without it.
  - Why an entry point rather than a conditional `import hassette...`: the client doesn't
    hard-code a hassette-internal module path, and a real import error inside hassette isn't
    swallowed as "not installed". It's the standard way for an optional package to add commands
    to another package's CLI (pytest, datasette and llm plugins all use it).
- **Named remote targets are first-class.** A client-only install has no local config to
  discover, so the CLI gains a small config file of named targets (working shape:
  `~/.config/hassette/cli.toml`, `[targets.<name>]` with URL, token or token file, and
  `verify_ssl`, plus a top-level `default`) and a `--target <name>` flag. Shell aliases over the
  existing flags were considered and rejected: a client-only install has no `HassetteConfig`, so
  there would be no persistent defaults at all, and aliases put tokens in shell rc files where a
  config entry can point at a `token_file`. The motivating setup is several machines (work
  laptops, a desktop) controlling one server.

## Proposed Work Split

These land as issues under the HACS epic, most independently, then a slimmer spec covers
whatever the HA integration still needs.

| # | Issue | Depends on | Notes |
|---|---|---|---|
| 0 | Teach `check_module_boundaries.py` to scope rules by nested module path | — | Rules can target `core/telemetry/` separately from the rest of `core/`, not just top-level layers. Should land before 3b. |
| 1 | Return RFC 9457 problem details from the app action routes | — | Stable `code` values (`invalid_app_key`, `app_not_found`, `instance_not_found`, `bootstrap_not_released`, `app_blocked`, `action_failed`). These are wire codes; C maps them to its own translation keys (`bootstrap_not_released` → `not_bootstrapped`, `app_blocked` → `blocked_by_filter`, `app_not_found` → `not_found`, `action_failed` → `action_failed`). First slice of #2369. Independent of #2368 (epic unit A): either can land first, and A's 500 goes out as `action_failed` once both have. |
| 2 | Re-anchor the stale zizmor `artipacked` ignore | — | `.github/zizmor.yml:13` points at `release-please.yml:49`, which is now `timeout-minutes`. |
| 3a | Convert the repo to a uv workspace with empty `hassette-wire` and `hassette-client` packages, released in lockstep | — | Packaging only: workspace members, Dockerfile metadata lines (like `codegen`'s, for `uv lock --check`), CI path filters, nox sessions, release-please `extra-files`, and the wire → client → hassette publish order. Done when the Docker build is green and a release-please dry-run shows one PR bumping all three versions. |
| 3b | Move the wire models and wire enums into `hassette-wire` | 3a (and 0, or its stopgap) | Behavior-preserving, pinned by the OpenAPI schema and the existing route tests. Domain objects (`app_snapshots`) and `hassette.types.enums` stay in hassette. `SystemStatus.version` becomes server-set. Adds both boundary rules to `check_module_boundaries.py`. |
| 4 | Add the async transport, error mapping, and typed methods for every endpoint to `hassette-client` | 1, 3b | The HA requirements live here: injected session, lenient validation context, loud non-additive failures, the newer-server warning. Also adds the cross-version CI job. |
| 5 | Move the CLI into `hassette-client[cli]`, with the entry-point plugin for `run` and local discovery | 4 | Ports every command onto the async client and deletes `HassetteCLIClient`. |
| 6 | Add named remote targets to the CLI | 5 | The client config file, `default`, and `--target`. |

## Open Questions

- **Server-only defaults in the moving models.** `SystemStatus.version` uses
  `hassette.utils.get_version` as its `default_factory` (`schemas/domain_models.py:30,88`), which
  reads the installed `hassette` package's version. Moved as-is, it would either import hassette
  or report `"unknown"`, so the server has to pass the value explicitly. Are there other defaults
  or validators like this in the models that move?
- **`Literal` wire types.** Some wire fields are `Literal[...]` aliases rather than enums
  (`ErrorRateClass`, `HealthStatus`, `ListenerKind`, `SystemHealthStatus` in `web/models.py`).
  Lenient parsing has to cover them too: convert them to wire enums, or give them their own
  open-union handling.
- **Sync CLI over an async client.** The CLI would wrap each command in `asyncio.run`. Is that
  fine for every command, including paginated or streaming ones?
- **`httpx2` in hassette.** Starlette uses it, so it stays a dependency. Only the CLI's direct
  use goes away.

## Scope Boundaries

- **In:** the issues above.
- **Out:** WebSocket push and subscriptions (the epic's v0.2), per-client or scoped tokens,
  problem details beyond the app action routes (#2369), min/max schema-version negotiation (the
  zwave-js-server-python pattern; revisit if the floor-plus-warning approach proves
  insufficient), and any change to the frontend's API layer.

## Risks and Concerns

- **A large mechanical move.** Relocating the models touches the web layer, core, and the CLI
  at once, and changes import paths for anything using `hassette.web.models`. The OpenAPI schema
  and the existing route tests pin its behavior, and 3a proves the packaging first.
- **Lockstep coupling.** Every hassette release publishes new `hassette-wire` and
  `hassette-client` versions, even when they're unchanged. Their version numbers track
  hassette's (0.5x), not 0.1.
- **HA's constrained environment.** The floors of `hassette-wire` and `hassette-client` must sit
  at or below the pins of the integration's minimum HA version. HA 2026.9.2 (hassette's codegen
  target in `codegen/ha-version.txt`) pins `aiohttp==3.14.3` and `pydantic==2.13.4`, and its
  `package_constraints.txt` also constrains `packaging>=23.1`.

## Codebase Context

- **Today's client:** `src/hassette/cli/client.py` (`HassetteCLIClient`, sync `httpx2`,
  `NoReturn` error handlers); target and credential resolution in `src/hassette/cli/target.py`
  (`--server-url` flag → `config.cli.server_url` → derived from the server config). Tokens
  resolve through `CREDENTIAL_SOURCES` (`target.py:334`) in order: the `--token-file` flag,
  `cli.token_file`, `cli.auth_token` (`HASSETTE__CLI__AUTH_TOKEN`), `web_api.auth_token`
  (`HASSETTE__WEB_API__AUTH_TOKEN`), then the data-dir token file.
- **CLI commands:** `run`, `status`, `app` (`health`, `activity`, `config`, `source`, `start`,
  `stop`, `reload`), `listener`, `job`, `log`, `execution`, `config`, `telemetry`, `dashboard`
  (`src/hassette/cli/__init__.py`).
- **Endpoints the CLI calls:** `/api/health`, `/api/config`, `/api/apps/manifests`,
  `/api/apps/{key}/{config,source}`, `/api/apps/{key}/{action}`,
  `/api/apps/{key}/instances/{index}/{action}`, `/api/bus/listeners`, `/api/scheduler/jobs`,
  `/api/logs/recent`, `/api/executions/{uuid}`, `/api/telemetry/status`,
  `/api/telemetry/dashboard/app-grid`, `/api/telemetry/app/{key}/{jobs,listeners,activity,health}`,
  `/api/telemetry/{job,listener}/{id}/executions`.
- **Wire models today:** `src/hassette/web/models.py` and `src/hassette/schemas/`.
- **Existing workspace-like member:** `codegen/` (a path dependency with Dockerfile metadata
  lines for `uv lock --check`).
- **Single console script today:** `hassette = "hassette.__main__:entrypoint"` (`pyproject.toml:124`).
- **Related issues:** #2368 (start/reload failures return 500; epic unit A), #2369 (problem
  details repo-wide), #45 (epic tracker).
