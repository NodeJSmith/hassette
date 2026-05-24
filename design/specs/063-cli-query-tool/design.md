# Design: CLI Query Tool

**Date:** 2026-05-22
**Status:** approved
**Scope-mode:** hold
**Research:** design/research/2026-05-22-cli-tool-prior-art/research.md, design/research/2026-05-22-cli-subcommand-structure/research.md, design/research/2026-05-22-cli-output-formatting/research.md

## Problem

There is no terminal-native way to query a running hassette instance. Checking system status, viewing app health, inspecting listeners, tailing logs, or reviewing scheduler jobs requires the browser UI or raw HTTP requests. Users who work primarily in the terminal must context-switch to a browser or compose curl commands with endpoint paths and query parameters from memory.

## Goals

- Query all read-only API endpoints from the terminal with typed, well-formatted output
- Provide human-readable output by default and structured output for scripting
- Share response models with the server to avoid type duplication across codebases
- Replace argparse and pydantic-settings CLI parsing with a single CLI framework that handles both server startup flags and query subcommands
- Support filtering by app, time window, and result limits across relevant commands

## Non-Goals

- Mutations (start/stop/reload apps) — deferred to v2
- WebSocket streaming (live log tailing, event watching) — deferred to v2
- `hassette execution <uuid>` showing invocation/job metadata alongside logs — v1 shows logs only; a server-side execution-detail endpoint and richer composite view are deferred
- Interactive features (prompts, selection menus)
- Configuration file management
- Multi-instance profiles (named server configs)
- Documentation site pages for CLI usage (deferred)

## User Scenarios

### Framework operator: Developer running hassette automations

- **Goal:** Quickly check system and app health from the terminal
- **Context:** Working in a terminal session, hassette running locally or on a remote server

#### Quick health check

1. **Run the status command**
   - Sees: system status, uptime, entity count, app count, WebSocket connection state, version, any boot issues
   - Decides: whether the system is healthy or needs investigation
   - Then: if healthy, done; if degraded, drills into specific app or service

#### Investigate a failing app

1. **List all apps**
   - Sees: app key, status, display name, instance count, recent invocations
   - Decides: which app to investigate based on status or error indicators
   - Then: queries that app's health

2. **Check app health**
   - Sees: error rate, average handler/job duration, last activity, health status
   - Decides: whether the issue is handler errors, job failures, or general unresponsiveness
   - Then: lists listeners or jobs filtered to that app

3. **List listeners filtered to the app**
   - Sees: listener ID, topic, handler method, invocation counts (total/ok/fail), avg duration
   - Decides: which listener is problematic based on failure count or duration
   - Then: views invocation history for that listener

4. **View listener invocation history**
   - Sees: individual invocations with status, duration, error details, timestamps
   - Decides: whether the failure pattern is transient or systematic
   - Then: checks logs for that execution context

#### Scripted monitoring

1. **Query status in JSON mode**
   - Sees: full system status as structured data on stdout
   - Decides: nothing — a script parses the JSON and takes automated action
   - Then: script evaluates health fields and alerts if degraded

#### Server unreachable

1. **Run a query command against a stopped instance**
   - Sees: error message on stderr naming the address that was attempted and suggesting the server may not be running
   - Decides: whether to start the server or check the configured address
   - Then: starts the server or adjusts configuration

## Functional Requirements

- **FR#1** The tool queries a running hassette instance's REST API and displays results in the terminal
- **FR#2** Each readable API resource is accessible as a noun-based subcommand
- **FR#3** The default output format is a human-readable table for collections and a key-value panel for single objects
- **FR#4** A flag switches output to structured data containing the complete response model
- **FR#5** When the structured output flag is active, stdout contains exactly one valid document — no other output may appear on stdout
- **FR#6** Commands that return collections support filtering by app key, time window, and result count limit via flags
- **FR#7** The tool discovers the server address from the same configuration sources used by the server itself
- **FR#8** Running the binary with no subcommand starts the server, preserving backward compatibility
- **FR#9** Commands return structured data objects; a single rendering layer handles all output formatting
- **FR#10** The tool supports shell tab completion for commands and subcommands

## Edge Cases

- **Server not running**: Connection refused — display a clear error message with the address that was attempted, exit non-zero
- **Server returns degraded status**: Some endpoints return partial data during database issues — display the partial data with a warning
- **No config available**: If the server address can't be determined from any configuration source, fall back to the default address
- **Token not set**: The server access token is optional for query commands (they don't need it). Server startup validates the token is present before connecting to the automation platform
- **Wide tables**: Listener and job tables have many columns — handle terminal width overflow with column truncation and ellipsis
- **Empty results**: When a query returns an empty collection — display a clean "no results" message in human mode, empty collection in structured mode
- **Invalid app key**: The user passes a nonexistent app key filter — display the empty result or error from the server accordingly
- **Timeout**: Server is reachable but slow — all requests have an explicit timeout; display a timeout error if exceeded

## Acceptance Criteria

- **AC#1** All GET endpoints in the REST API are queryable via CLI subcommands (FR#1, FR#2)
- **AC#2** Human-readable output fits within an 80-column terminal without horizontal scrolling for the default column set (FR#3)
- **AC#3** Structured output mode produces valid parseable output on stdout with no other content on stdout (FR#4, FR#5)
- **AC#4** `hassette listener --app my-app` returns only listeners belonging to `my-app` (FR#6)
- **AC#5** `hassette log --since 1h --limit 20` returns at most 20 log entries from the last hour (FR#6)
- **AC#6** Running `hassette` with no arguments starts the framework server as before (FR#8)
- **AC#7** Adding a new output format requires changes only to the rendering layer, not to individual commands (FR#9)
- **AC#8** When the server is unreachable, the tool exits with a non-zero code and a human-readable error message on stderr
- **AC#9** When a configuration file or environment variable specifies a non-default server address, the tool queries that address instead of the default (FR#7)
- **AC#10** Tab completion for command and subcommand names works after running the shell-specific installation command (FR#10)

## Key Constraints

- Commands must never print directly to stdout — all output goes through the rendering layer. This is the "return data, not strings" constraint from the output formatting research; violating it creates the two-rendering-paths maintenance trap.
- The `--json` flag must guarantee stdout cleanliness from day one. Diagnostics, warnings, and progress output go to stderr only. This is a correctness constraint, not a style preference — fixing it after release is a breaking change (Salesforce CLI, .NET SDK both required breaking changes to fix this).
- The `token` field change in HassetteConfig must be validated at server startup, not at config instantiation. CLI commands must work without a token set.

## Dependencies and Assumptions

- **cyclopts** (v4.x, pinned) — CLI framework replacing argparse and pydantic-settings CLI parsing for subcommand routing, help text, tab completion
- **rich** (transitive via cyclopts) — terminal formatting, tables, auto-detection of TTY vs pipe
- **httpx** — synchronous HTTP client for API queries
- All three are core dependencies, not optional extras
- Assumes the hassette web API is running and accessible over HTTP
- Assumes the API endpoint paths and response models are stable (they are part of the frontend contract)

**Prerequisite: Web API model hardening (resolved)** — PR #837 (issue #832) hardened the API response models. Status, health, and classification fields now use constrained `Literal` types (`ManifestStatus`, `ErrorRateClass`, `HealthStatus`, `SystemHealthStatus`, `ListenerKind`) and `StrEnum` types (`InvocationStatus`, `ResourceStatus`). Events now return typed `EventEntry` models. The execution endpoint moved to `GET /api/executions/{execution_id}`. Per-app telemetry endpoints document their `instance_index` behavior.

The telemetry models (`HandlerInvocation`, `JobExecution`, `JobSummary`, `ActivityFeedEntry`) remain in `core/telemetry_models.py` and are returned directly by routes — no projection wrappers. This is intentional: the telemetry models are already Pydantic models serving as the shared contract between the query service and web layer, and no fields need hiding from API consumers. The CLI imports from both `web/models` and `core/telemetry_models`.

Two endpoints remain untyped: `/api/services` returns `dict[str, Any]` (proxied HA data with unpredictable schema) and the CLI renders it as-is.

PR #835 migrated the frontend data layer to TanStack Query. This has no impact on the CLI — the REST API endpoints and response models are unchanged. Noted here because it landed in the same rebase window.

## Architecture

### Trade-offs

This architecture optimizes for **zero-duplication and low per-command maintenance** — commands are pure data producers, the rendering layer is shared, and response models are imported directly from the server. The sacrifice is **coupling to the server's model schema** — if a response model changes shape, the CLI's column definitions may need updating. This is acceptable because the models are already a contract with the frontend, so changes are versioned and deliberate.

Synchronous httpx is chosen over async for simplicity — CLI commands are request-response with no concurrency needs in v1. The trade-off is that switching to async later (for WebSocket streaming in v2) will require changing the HTTP client layer, though command functions themselves won't change since they return models, not manage connections.

### Package structure

New `src/hassette/cli/` package containing all CLI-specific code:

```
src/hassette/cli/
├── __init__.py          # cyclopts App setup, root command, subcommand registration
├── client.py            # HTTP client wrapper (httpx sync, typed responses)
├── output.py            # Rendering layer (Column definitions, Rich tables, JSON output)
└── commands/
    ├── __init__.py
    ├── status.py         # status, telemetry, dashboard (system-level)
    ├── app.py            # app list, health, activity, config, source
    ├── listener.py       # listener list, invocation history
    ├── job.py            # job list, execution history
    ├── log.py            # recent logs, logs by execution
    └── misc.py           # event, config, service (simple single-endpoint commands)
```

### Entry point refactor

`src/hassette/__main__.py` delegates entirely to the cyclopts App defined in `hassette.cli`. cyclopts handles all argument parsing — both subcommands (query tools) and the default command (start the framework). argparse is removed completely.

The cyclopts App's default command (no subcommand) exposes HassetteConfig's top-level fields as CLI flags (`--token`, `--base-url`, `--verify-ssl`, `--config-file`, `--env-file`, `--dev-mode`, etc.) and passes them as init values to `HassetteConfig()`. This replaces both argparse and pydantic-settings CLI parsing with a single cyclopts-based parser. The exact set of exposed fields should match HassetteConfig's top-level fields — verify during implementation.

`HassetteConfig.model_config` changes `cli_parse_args` from `True` to `False` — pydantic-settings no longer parses `sys.argv`. All CLI argument parsing goes through cyclopts exclusively. HassetteConfig continues to load from env vars, .env files, and TOML as before; cyclopts-parsed values are passed as init kwargs (highest priority in the pydantic-settings source chain).

### Command mapping (noun-verb with bare-noun-as-list)

| Command | API Endpoint | Response Model |
|---------|-------------|----------------|
| `hassette status` | `GET /api/health` | `SystemStatusResponse` |
| `hassette app` | `GET /api/apps/manifests` | `AppManifestListResponse` |
| `hassette app health <key>` | `GET /api/telemetry/app/{key}/health` | `AppHealthResponse` |
| `hassette app activity <key>` | `GET /api/telemetry/app/{key}/activity` | `list[ActivityFeedEntry]` |
| `hassette app config <key>` | `GET /api/apps/{key}/config` | `AppConfigResponse` |
| `hassette app source <key>` | `GET /api/apps/{key}/source` | `AppSourceResponse` |
| `hassette listener` | `GET /api/bus/listeners` | `list[ListenerWithSummary]` |
| `hassette listener <id>` | `GET /api/telemetry/handler/{id}/invocations` | `list[HandlerInvocation]` |
| `hassette job` | `GET /api/scheduler/jobs` | `list[JobSummary]` |
| `hassette job <id>` | `GET /api/telemetry/job/{id}/executions` | `list[JobExecution]` |
| `hassette log` | `GET /api/logs/recent` | `list[LogEntryResponse]` |
| `hassette execution <uuid>` | `GET /api/executions/{execution_id}` | `LogsByExecutionResponse` |
| `hassette event` | `GET /api/events/recent` | `list[EventEntry]` |
| `hassette config` | `GET /api/config` | `ConfigResponse` |
| `hassette service` | `GET /api/services` | `dict[str, Any]` |
| `hassette telemetry` | `GET /api/telemetry/status` | `TelemetryStatusResponse` |
| `hassette dashboard` | `GET /api/telemetry/dashboard/app-grid` | `DashboardAppGridResponse` |

### Shared flags (flag-based scoping, not structural nesting)

Several commands share filtering parameters. These are implemented as shared annotated types used across command signatures:

- `--app` — filter by app_key (used by: listener, job, log, event)
- `--since` — time window filter (used by: listener, job, log, app activity). Accepts relative durations (`Nd`, `Nh`, `Nm` — e.g., `1h`, `7d`, `30m`) and absolute ISO 8601 timestamps (`2026-05-22T10:00`). The CLI converts to a Unix epoch float before forwarding to the API. Invalid formats exit non-zero with a usage error on stderr. Implemented via a cyclopts custom type converter
- `--limit` — max results (used by: log, event, app activity, listener invocations, job executions)
- `--source-tier` — telemetry source tier (used by: listener, job, log)
- `--json` — output as JSON (used by: all commands)

The API endpoint selection is transparent to the user. For example, `hassette listener --app my-app` uses the per-app telemetry endpoint internally (`/api/telemetry/app/{key}/listeners`) while `hassette listener` uses the global endpoint (`/api/bus/listeners`). Same command, different API route chosen based on whether `--app` is provided.

### Rendering layer (`output.py`)

Commands return Pydantic response models (or lists of models). A single rendering layer handles all formatting:

- **JSON mode**: `model.model_dump_json(indent=2)` written to stdout. For lists: serialize the list. The Pydantic model IS the complete data — JSON is a superset of human output.
- **Human mode (list)**: Rich `Table` with per-command column definitions. Each command declares a list of `Column(field, header, max_width?, overflow?)` objects that map model fields to table columns.
- **Human mode (detail)**: Rich key-value panel for single-object responses (e.g., `hassette status`, `hassette app config <key>`).
- **Pipe detection**: Rich auto-detects TTY and strips ANSI when piped. Truncation disabled in non-TTY mode. Respects `NO_COLOR`.
- **stderr contract**: All diagnostics (errors, warnings, connection issues) go to stderr. stdout is reserved for data output only.

### HTTP client (`client.py`)

Thin wrapper around `httpx.Client` (synchronous) that:
- Takes base URL from HassetteConfig's `web_api.host` and `web_api.port`, substituting `0.0.0.0` → `127.0.0.1` (the server's bind-all address is not a routable connect address on macOS or Docker)
- Sets explicit timeout on every request (10s default)
- Deserializes responses directly into Pydantic response models via `model.model_validate(response.json())`
- Provides clear error messages for connection refused, timeout, and non-2xx responses:
  - **Human mode**: print the server's `detail` field to stderr, exit non-zero
  - **JSON mode**: emit `{"error": true, "status": <http_status>, "detail": "..."}` to stdout (maintaining the stdout-only JSON contract), exit non-zero
  - **Exit codes**: 1 for server errors (4xx/5xx), 2 for network errors (connection refused, timeout)

### Config changes

`HassetteConfig.token` changes from `default=...` (required) to `default=None` (optional). Three locations need updates:

1. **`auth_headers` property** (`config.py:225`): Add `if self.token is None: return {}` guard — returns empty headers instead of `"Bearer None"`
2. **`truncated_token` property** (`config.py:235`): Add `if self.token is None: return "<not set>"` guard — avoids `TypeError` from `len(None)`
3. **Server startup** (`core.py`, before `wire_services`): Validate that `config.token is not None` and raise `FatalError` if missing — prevents the server from starting without HA credentials

The property guards make `HassetteConfig` safe to use with `token=None` from any call site (CLI commands, tests). The startup check enforces the server-side requirement early.

### Packaging

`pyproject.toml` changes:
- Add `cyclopts>=4.0,<5.0` and `httpx>=0.28.0` to `[project.dependencies]` (core deps, not optional). Rich is a transitive dep of cyclopts.
- Entry point remains: `hassette = "hassette.__main__:entrypoint"`
- No `[cli]` optional extra — all CLI functionality is always available after `pip install hassette`

## Replacement Targets

The argparse-based CLI in `src/hassette/__main__.py` (lines 18-38, `get_parser()`) is replaced entirely by cyclopts App subcommand routing. The 3 argparse flags (`--config-file`, `--env-file`, `--version`) plus HassetteConfig's top-level fields become parameters on the cyclopts default command. No fallback path — cyclopts is a core dependency.

The pydantic-settings `cli_parse_args=True` setting in `HassetteConfig.model_config` (config.py:60) is changed to `cli_parse_args=False`. The `cli_prog_name`, `cli_kebab_case`, and `cli_ignore_unknown_args` settings and CLI shortcut aliases (config.py:58-68) can also be removed since cyclopts handles all CLI parsing.

Note: `HassetteConfig` instantiation creates `config_dir` and `data_dir` directories on disk via the `resolve_paths` validator (config.py:258-266). CLI query commands that instantiate `HassetteConfig` for server address discovery will trigger this side effect. The implementation should determine whether this is acceptable (the directories are harmless) or whether a lightweight config read path is needed to avoid creating directories from a read-only query tool.

## Convention Examples

### Route handler pattern

**Source:** `src/hassette/web/routes/health.py`

```python
@router.get(
    "/health",
    response_model=SystemStatusResponse,
    responses={503: {"model": SystemStatusResponse}},
)
async def get_health(runtime: RuntimeDep, response: Response) -> SystemStatusResponse:
    status_data = runtime.get_system_status()
    if status_data.status != "ok":
        response.status_code = 503
    return system_status_response_from(status_data)
```

### Response model pattern

**Source:** `src/hassette/web/models.py`

```python
class SystemStatusResponse(BaseModel):
    status: SystemHealthStatus
    websocket_connected: bool
    uptime_seconds: float
    entity_count: int
    app_count: int
    services_running: list[str]
    services: list[ServiceInfoResponse] = Field(default_factory=list)
    version: str = ""
    boot_issues: list[BootIssueResponse] = Field(default_factory=list)
    log_records_dropped: int = 0
```

### Config with HassetteConfig (the token field being changed)

**Source:** `src/hassette/config/config.py:132-135`

```python
token: str = Field(
    default=...,
    validation_alias=AliasChoices("token", "hassette__token", "ha_token", "home_assistant_token"),
)
```

DO: Change `default=...` to `default=None` and type to `str | None`. Validate at server startup.
DON'T: Add a separate config class for the CLI — future CLI commands will need more of HassetteConfig.

### Entry point pattern (being replaced)

**Source:** `src/hassette/__main__.py:65-81`

```python
def entrypoint() -> None:
    enable_logging(get_log_level(), log_format="auto")
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        LOGGER.info("Keyboard interrupt received, shutting down")
    except AppPrecheckFailedError as e:
        LOGGER.error("App precheck failed: %s", e)
        LOGGER.error("Hassette is shutting down due to app precheck failure")
    except FatalError as e:
        LOGGER.error("Fatal error occurred: %s", e)
        LOGGER.error("Hassette is shutting down due to a fatal error")
    except Exception as e:
        LOGGER.exception("Unexpected error in Hassette: %s", e)
        raise
```

The exception handling structure should be preserved in the cyclopts default command that starts the framework.

## Alternatives Considered

### pydantic-settings CLI

pydantic-settings has built-in CLI support via `CliApp` and `CliSubCommand`. Since hassette already uses pydantic-settings, this would add zero new dependencies. However, pydantic-settings CLI is designed for configuration parsing, not for building CLIs with rich help text, tab completion, and complex subcommands. It lacks Rich-based help formatting, multi-shell completion, and config source integration. Rejected because the CLI will grow beyond simple queries, and migrating away from pydantic-settings CLI later would be costly.

### tyro

Pure model-first CLI framework — Union types become subcommands, no decorators. Elegant and minimal (4 deps). However, tyro is CLI-only with no settings layering, no Rich help formatting, and basic tab completion. More importantly, it lacks config file integration and async command support. Rejected because hassette's CLI will need richer features as it grows.

### Separate binary (hass-cli pattern)

Home Assistant uses a separate package (`homeassistant-cli`) for CLI queries. This cleanly separates client from server but creates a version compatibility problem and doubles the maintenance surface. Rejected because hassette's CLI shares response models with the server — keeping them in one package eliminates type duplication.

## Test Strategy

### Existing Tests to Adapt

- `tests/system/test_web_api.py` — no changes needed; these test the API endpoints directly and are not affected by CLI additions
- Grep for `HassetteConfig(` *without* a `token=` argument — these will now receive `token=None` at instantiation instead of raising `ValidationError`. Verify they still exercise the intended behavior or add an explicit `token=None` to make the intent clear

### New Test Coverage

- **Rendering layer unit tests** (FR#3, FR#4, FR#5, FR#9): Mock Pydantic models → verify Rich table output has correct columns and values; verify JSON output is valid and contains all model fields; verify no output leaks to stdout in JSON mode besides the JSON document
- **HTTP client unit tests** (FR#1, FR#7): Mock httpx responses → verify typed model deserialization; verify connection refused error handling; verify timeout handling
- **Command integration tests** (FR#2, FR#6): Mock HTTP client → invoke each command function with various flag combinations; verify correct API endpoint is called with correct query params; verify correct response model is passed to the renderer
- **Entry point tests** (FR#8): Test subcommand routing; test default command starts the framework with correct HassetteConfig init values from CLI flags
- **Token validation test** (edge case): Verify HassetteConfig instantiates with token=None; verify server startup rejects None token

### Tests to Remove

No tests to remove.

## Documentation Updates

- **`CLAUDE.md`** — add CLI commands to the "Common Commands" section (e.g., `hassette status`, `hassette app`, `hassette log --app <key> --since 1h`)
- **`README.md`** — add a "CLI" section showing basic usage examples (`hassette status`, `hassette app`, `hassette log --app <key> --since 1h`)
- **No CHANGELOG update** — release-please generates this from conventional commit messages

## Impact

### Changed Files

- `pyproject.toml` — add `cyclopts` and `httpx` to core dependencies
- `src/hassette/config/config.py` — change `token` field from required to optional (`str | None`, `default=None`); remove `cli_parse_args`, `cli_prog_name`, `cli_kebab_case`, `cli_ignore_unknown_args`, `cli_shortcuts`
- `src/hassette/__main__.py` — replace argparse with cyclopts App delegation
- `src/hassette/core/core.py` (or wherever server startup validates config) — add token-not-None check before HA connection

### New Files

- `src/hassette/cli/__init__.py` — cyclopts App setup, root command, subcommand registration
- `src/hassette/cli/client.py` — HTTP client wrapper (httpx sync, typed responses)
- `src/hassette/cli/output.py` — rendering layer (column definitions, Rich tables, JSON output)
- `src/hassette/cli/commands/` — command modules (status, app, listener, job, log, misc)

### Behavioral Invariants

- `hassette` with no arguments must continue to start the framework server — this is the primary backward compatibility constraint
- `--config-file` and `--env-file` flags must continue to work for server startup
- All existing REST API endpoints must continue to return the same response models — the CLI depends on these as a contract
- `HassetteConfig` environment variable loading (`HASSETTE__TOKEN`, `HA_TOKEN`, etc.) must continue to work

### Blast Radius

- **Server startup**: The token change affects how HassetteConfig validates — any code that catches `ValidationError` during config instantiation for token-missing scenarios will behave differently
- **Test infrastructure**: Tests using `HassetteConfig()` without a token will no longer raise ValidationError at instantiation — they'll get `token=None` instead, which may cause failures later in the test if the code path tries to use the token
- **Frontend**: No impact — the CLI queries the same API the frontend uses
- **Documentation**: README and CLAUDE.md need updates to mention the CLI

## Open Questions

None — all questions resolved during discovery.
