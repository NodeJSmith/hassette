# Context: CLI Query Tool

## Problem & Motivation

There is no terminal-native way to query a running hassette instance. Checking system status, viewing app health, inspecting listeners, tailing logs, or reviewing scheduler jobs requires the browser UI or raw HTTP requests. Users who work primarily in the terminal must context-switch to a browser or compose curl commands with endpoint paths and query parameters from memory. This feature adds a CLI interface that queries the existing REST API and presents results in human-readable tables or structured JSON for scripting.

## Visual Artifacts

None — this feature adds CLI commands with text output only; no UI surfaces or mockups.

## Key Decisions

1. **cyclopts replaces argparse and pydantic-settings CLI parsing.** cyclopts handles subcommand routing, help text, and tab completion. pydantic-settings continues to load env vars, .env, and TOML — only its CLI argument source (`cli_parse_args`) is disabled. The short aliases from `cli_shortcuts` must be re-implemented as cyclopts parameter aliases.

2. **Synchronous httpx for HTTP client.** CLI commands are request-response with no concurrency. Async would add complexity for no benefit in v1. The trade-off is that WebSocket streaming (v2) will require changing the client layer.

3. **Commands return Pydantic models; a shared rendering layer formats them.** Commands are pure data producers. A single `output.py` handles Rich tables, key-value panels, and JSON serialization. This prevents the two-rendering-paths maintenance trap.

4. **Response models imported directly from server.** The CLI imports from `web/models.py` and `core/telemetry_models.py` — no wrappers or duplication. Couples CLI to server schema, but the schema is already a frontend contract, so changes are versioned.

5. **`HassetteConfig.token` becomes optional (`str | None`).** CLI commands don't need HA credentials. Server startup validates token is not None before connecting. Property guards prevent `Bearer None` headers and `len(None)` errors.

6. **`--instance` accepts int or string.** Integer values pass through as `instance_index`. String values resolve to an index by fetching the app manifest and matching `instance_name`. One extra HTTP call for name resolution.

7. **`--app` transparently routes to per-app telemetry endpoints.** `hassette listener` hits `/api/bus/listeners`; `hassette listener --app my-app` routes to `/api/telemetry/app/{key}/listeners`. Same command, different API route.

## Constraints & Anti-Patterns

- Commands must NEVER print directly to stdout — all output goes through the rendering layer.
- `--json` must guarantee stdout cleanliness from day one. All diagnostics, warnings, and progress go to stderr.
- Exit codes: 0 success, 1 server errors (4xx/5xx), 2 network errors (connection refused, timeout).
- JSON error output format: `{"error": true, "status": <int|null>, "detail": "..."}` on stdout.
- The default command (no subcommand) MUST start the framework server — backward compatibility constraint.
- `--config-file` and `--env-file` flags must continue to work for server startup.
- Do NOT implement mutations (start/stop/reload), WebSocket streaming, interactive features, or config management — these are explicit non-goals.
- Token validation happens at server startup, not at config instantiation.

## Design Doc References

- `## Architecture` — package structure, entry point refactor, command mapping, shared flags, rendering layer, HTTP client, config changes, packaging
- `## Convention Examples` — route handler pattern, response model pattern, config token pattern, entry point pattern
- `## Replacement Targets` — argparse removal, pydantic-settings cli_* removal, alias re-implementation
- `## Test Strategy` — existing test adaptations, new test coverage, CLI smoke tests
- `## Impact` — changed files, new files, behavioral invariants, blast radius

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

### Config token pattern (being changed)

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

The exception handling structure should be preserved in the cyclopts default command.
