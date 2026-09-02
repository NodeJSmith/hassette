# Context: Per-Instance Actions in Frontend and CLI

## Problem & Motivation

PR #1687 added backend API routes for per-instance app control (start, stop, reload), but neither the web dashboard nor the CLI exposes them. Operators must call the REST API directly to control individual instances. The frontend renders ActionButtons at both app level and per-instance rows, but every button fires the app-level endpoint regardless of context. The CLI has no action subcommands at all — only read-only queries.

## Visual Artifacts

None.

## Key Decisions

1. **Single paired `instance` prop** — ActionButtons receives `instance?: { index: number; name: string }` instead of two independent optional props, making mismatch structurally impossible.
2. **No backend changes** — all three instance routes already exist; this work is purely frontend + CLI.
3. **Instance-aware messaging** — both toast text and CLI success messages include the instance name when acting at instance scope, built from client-side data.
4. **`confirmStop` on all table rows** — stop confirmation dialog added to both app-level and instance sub-rows in the apps table (previously only on app-detail header).
5. **CLI `--yes` flag** — `stop` and `reload` prompt for confirmation; `--yes` bypasses it. `start` does not prompt.
6. **Instance-scoped testid/aria-label** — when `instance` is present, `data-testid` includes the index and `aria-label` includes the instance name for both testing and accessibility.

## Constraints & Anti-Patterns

- Do NOT change any backend routes or models.
- Do NOT introduce a separate "restart" action — `reload` is the restart.
- ActionButtons backward compatibility: callers not passing `instance` must see identical routing behavior.
- Instance-level actions on the collapsed app-level row in the apps table are out of scope.
- No bulk-select-and-act UI.

## Design Doc References

- `## Architecture → Frontend` — endpoint functions, ActionButtons prop design, wiring in app-detail-header and apps-table-row, stop confirmation dialog
- `## Architecture → CLI` — client post method, action commands with --instance and --yes, command registration
- `## Test Strategy` — required test types, existing tests to adapt, new test coverage
- `## Convention Examples` — endpoint function pattern, CLI command pattern, CLI registration pattern

## Convention Examples

### Frontend endpoint function

**Source:** `frontend/src/api/endpoints.ts`

```typescript
export const reloadApp = (appKey: string) =>
  apiPost<ActionResponse>(`/apps/${encodeURIComponent(appKey)}/reload`);
```

### CLI command with instance support

**Source:** `src/hassette/cli/commands/app.py`

```python
def cmd_app_health(
    key: str,
    instance: InstanceArg = None,
    since: SinceArg = None,
    source_tier: SourceTierArg = None,
    *,
    ctx: CLIContextParam = DEFAULT_CLI_CONTEXT,
) -> None:
    """Show health metrics for an app instance (GET /api/telemetry/app/{key}/health)."""
    client = make_client(ctx)
    params = query_params(
        instance_index=client.resolve_instance_or_none(key, instance),
        since=since,
        source_tier=source_tier,
    )
    result = client.get(f"/api/telemetry/app/{key}/health", AppHealthResponse, params=params)
    render_detail(result, json_mode=ctx.json_mode)
```

### CLI command registration

**Source:** `src/hassette/cli/__init__.py`

```python
apps_app.command(cmd_app_health, name="health")
apps_app.command(cmd_app_activity, name="activity")
apps_app.command(cmd_app_config, name="config")
apps_app.command(cmd_app_source, name="source")
```
