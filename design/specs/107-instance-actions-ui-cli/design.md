# Design: Per-Instance Actions in Frontend and CLI

**Date:** 2026-09-02
**Status:** archived
**Scope-mode:** hold

## Problem

PR #1687 added backend API routes for per-instance app control (`start`, `stop`, `reload`), but neither the web dashboard nor the CLI exposes them. Operators must call the REST API directly to control individual instances. The frontend renders `ActionButtons` at both the app level and per-instance rows, but every button fires the app-level endpoint regardless of context. The CLI has no action subcommands at all — only read-only queries (`health`, `activity`, `config`, `source`).

## Goals

- An operator can start, stop, or reload a single app instance from the web dashboard without affecting other instances of the same app.
- An operator can start, stop, or reload a single app instance from the CLI using `hassette app start|stop|reload <key> --instance <selector>`.
- Without `--instance`, CLI action commands operate at the app level (all instances), matching existing app-level routes.
- Both surfaces use the same backend routes and produce consistent terminology.

## Non-Goals

- Instance-level actions on the collapsed app-level row in the apps table (the parent row, not the expanded instance sub-rows).
- A separate "restart" operation — `reload` already stops and recreates the instance.
- Bulk-select-and-act UI (select multiple instances and act on them together).

## User Scenarios

### Operator: homelab developer

- **Goal:** reload a single misbehaving instance without disrupting other instances
- **Context:** monitoring the dashboard or using the CLI during development

#### Reload a specific instance from the dashboard

1. **Navigate to the app detail page**
   - Sees: app-level status, instance switcher tabs (for multi-instance apps)
   - Decides: which instance to inspect
   - Then: clicks the instance tab

2. **View instance detail**
   - Sees: instance-specific status badge, action buttons (Start / Reload / Stop), handlers, jobs
   - Decides: this instance needs reloading
   - Then: clicks Reload

3. **Confirm and observe**
   - Sees: toast confirming "Instance 'office' reloaded"
   - Then: WebSocket pushes the status change; instance status updates live

#### Reload a specific instance from the CLI

1. **Run the reload command**
   - Runs: `hassette app reload my_app --instance office`
   - Sees: success message confirming the instance was reloaded

#### Stop all instances of an app from the CLI

1. **Run stop without --instance**
   - Runs: `hassette app stop my_app`
   - Sees: success message confirming the app was stopped (all instances)

## Functional Requirements

- **FR#1** When `ActionButtons` receives an `instance` prop, clicking Start calls `POST /apps/{app_key}/instances/{index}/start` instead of `POST /apps/{app_key}/start`.
- **FR#2** When `ActionButtons` receives an `instance` prop, clicking Stop calls the instance-level stop route.
- **FR#3** When `ActionButtons` receives an `instance` prop, clicking Reload calls the instance-level reload route.
- **FR#4** When `ActionButtons` has no `instance` prop (or it is undefined), buttons continue to call app-level routes (existing behavior unchanged).
- **FR#5** The stop-confirmation dialog displays the instance name in both title and description (e.g., title "Stop instance 'office'?", description "Stop instance 'office' of 'my_app'?") when an instance-level stop is triggered, and the app name alone when app-level.
- **FR#6** When `instance` is present, `data-testid` on action buttons includes the instance index (e.g., `btn-start-{appKey}-{index}`) and `aria-label` includes the instance name (e.g., "Start instance 'office'"). Without `instance`, existing `data-testid` and `aria-label` values are unchanged.
- **FR#7** When `instance` is present, `performAction`'s success and error toast text includes the instance name (e.g., "Instance 'office' of 'my_app' reloaded"). Without `instance`, toast text uses app-level wording (existing behavior).
- **FR#8** `app-detail-header.tsx` passes the `instance` prop to `ActionButtons` when the user is viewing a single instance of a multi-instance app (not the parent overview).
- **FR#9** `apps-table-row.tsx` passes the `instance` prop to `ActionButtons` in instance sub-rows, and passes `confirmStop` on both app-level and instance sub-rows.
- **FR#10** CLI command `hassette app start <key>` calls `POST /api/apps/{key}/start`.
- **FR#11** CLI command `hassette app start <key> --instance <selector>` resolves the selector to an index and calls `POST /api/apps/{key}/instances/{index}/start`.
- **FR#12** CLI commands `stop` and `reload` follow the same pattern as FR#10–FR#11 for their respective routes.
- **FR#13** CLI action commands construct a human-readable success message on 202 and an error message on 4xx/5xx. When `--instance` is provided, the message includes the instance's canonical name resolved from the manifest (e.g., "Instance 'office' of 'my_app' reloaded"), regardless of whether the operator selected the instance by name or by numeric index — a bare index falls back to displaying the raw selector only if the manifest has no matching entry (e.g. a stale/out-of-range index). Without `--instance`, the message uses app-level text (e.g., "App 'my_app' reloaded"). `ActionResponse.instance_index` echoes the server-confirmed instance the action actually ran against; if it disagrees with the requested index, the CLI prints a warning to stderr and the frontend logs a console warning — a cheap check against a silent routing bug.
- **FR#14** CLI `stop` and `reload` commands prompt for interactive confirmation before executing (e.g., "Stop app 'my_app'? [y/N]" or "Reload instance 'office' of 'my_app'? [y/N]") at both app-level and instance-level. A `--yes` flag bypasses the prompt for scripted use. `start` does not require confirmation.

## Edge Cases

- **Single-instance app:** `ActionButtons` should not receive `instance` — the app-level route is correct. The CLI `--instance` flag is accepted but unusual for a single-instance app; it works as expected (index 0).
- **Instance index out of range:** The backend returns 404; the frontend toast and CLI error message surface this clearly.
- **App not found:** The backend returns 404; both surfaces surface the error.
- **Action on a stopped instance:** Starting a stopped instance is valid. Stopping or reloading an already-stopped instance returns an appropriate error from the backend; both surfaces display it.
- **Instance name resolution failure in CLI:** `resolve_instance()`/`resolve_instance_with_name()` already exits with a clear error listing available instance names when a `--instance` *name* doesn't match. A numeric `--instance` selector that doesn't match any current manifest entry does not error client-side — it's passed through to the server, which is the authoritative source for range validation (`_require_valid_instance_index`); the CLI message falls back to the raw selector in that case since no name is known.

## Acceptance Criteria

- **AC#1** Frontend component tests confirm `ActionButtons` with `instance={{ index: 1, name: "office" }}` calls `startInstance`/`stopInstance`/`reloadInstance` for the correct index (not app-level endpoints) — verifies FR#1–FR#3.
- **AC#2** Frontend component tests confirm `ActionButtons` without `instance` calls `startApp("app_key")` — verifies FR#4.
- **AC#3** Frontend component test confirms stop-confirmation dialog title and description both include the instance name when `instance` is provided — verifies FR#5.
- **AC#4** Frontend component test confirms `data-testid` includes instance index and `aria-label` includes instance name when `instance` is provided — verifies FR#6.
- **AC#5** Frontend component test confirms toast text includes instance name when `instance` is provided — verifies FR#7.
- **AC#6** CLI unit tests confirm `hassette app start my_app` sends `POST /api/apps/my_app/start` — verifies FR#10.
- **AC#7** CLI unit tests confirm `hassette app start my_app --instance 1` sends `POST /api/apps/my_app/instances/1/start` — verifies FR#11.
- **AC#8** CLI unit tests confirm `stop` and `reload` subcommands follow the same routing — verifies FR#12.
- **AC#9** CLI unit tests confirm `stop` and `reload` prompt for confirmation and `--yes` bypasses it — verifies FR#14.
- **AC#10** CLI unit tests confirm success message includes instance name when `--instance` is provided — verifies FR#13.
- **AC#11** Frontend component test confirms `apps-table-row` passes `confirmStop` on both app-level and instance sub-rows — verifies FR#9.
- **AC#12** E2E test navigates to a multi-instance app's instance view and verifies the action buttons fire instance-level routes — verifies FR#8.
- **AC#13** `prek -a` passes (lint + type check).
- **AC#14** `cd frontend && npm run build` succeeds with regenerated types.

## Key Constraints

- Do not change any backend *routes* — the endpoint surface is fixed. `ActionResponse` gained one additive field (`instance_index: int | None`) during implementation to let callers confirm the server acted on the intended instance rather than trusting client-side request data alone — this is additive and does not change any route's contract.
- Do not introduce a separate "restart" action — `reload` is the restart operation.
- The `ActionButtons` component must remain backward-compatible: callers that don't pass `instance` must see no behavior change.

## Dependencies and Assumptions

- Backend instance-level routes exist and are tested (`POST /apps/{app_key}/instances/{index}/{start|stop|reload}`).
- The `app_status_changed` WebSocket message already carries per-instance `index` and `status`, so no WebSocket changes are needed for the frontend to update after an instance action.
- The CLI client currently has no `post()` method — one must be added (modeled after the existing `get()` method).

## Architecture

### Frontend

**Endpoint functions** (`frontend/src/api/endpoints.ts`): Add three functions following the existing pattern:

```typescript
export const startInstance = (appKey: string, index: number) =>
  apiPost<ActionResponse>(`/apps/${encodeURIComponent(appKey)}/instances/${index}/start`);
```

Same shape for `stopInstance` and `reloadInstance`.

**ActionButtons** (`frontend/src/components/shared/action-buttons.tsx`): Add an optional `instance?: { index: number; name: string }` prop to `Props` (a single paired object, not two independent optional fields, so mismatch is structurally impossible). The `ACTIONS` map stays as-is (app-level). The `performAction` function gains an `instance` parameter: when present, it calls the instance endpoint and includes the instance name in toast text (e.g., "Instance 'office' of 'my_app' reloaded"); when absent, it calls the app endpoint with app-level wording. `buildButtonSpecs` gains `instance` so it can produce instance-aware `ariaLabel` values (e.g., "Start instance 'office'" vs. "Start app"); visibility logic is unchanged. When `instance` is present, `ActionButton` renders `data-testid={`btn-${action}-${appKey}-${instance.index}`}` and the instance-aware `aria-label`.

**Wiring in app-detail-header** (`frontend/src/components/app-detail/app-detail-header.tsx`): When `manifest.instance_count > 1`, `!showParentOverview`, and `currentInstance` actually resolved (an unresolved lookup — e.g. a sparse `instances` array or an out-of-range URL query param — falls back to app-level action semantics instead of emitting a blank instance name), pass `instance={getStableInstanceRef(currentInstance.index, currentInstance.instance_name)}` to `ActionButtons`. When showing the parent overview, a single-instance app, or an unresolved instance, no `instance` is passed (existing behavior).

**Wiring in apps-table-row** (`frontend/src/pages/apps-table-row.tsx`): The instance sub-row already has access to `inst.index` and `inst.instance_name`. Pass `instance={getStableInstanceRef(inst.index, inst.instance_name)}`. Pass `confirmStop` on both app-level rows and instance sub-rows.

**Stable instance references** (`frontend/src/components/shared/action-buttons.tsx`): `getStableInstanceRef(index, name)` interns `{index, name}` objects in a module-level `Map` keyed by `${index}:${name}`, so both wiring sites (one of which builds the prop inside a `.map()`, where `useMemo` isn't available) get a referentially-stable object per instance identity — a safeguard against silently defeating a future `React.memo` on `ActionButtons` or its parent, since nothing in the tree is memoized today.

**Stop confirmation dialog**: Parametrize both title and description — when `instance` is provided, title becomes "Stop instance '{name}'?" and description becomes "Stop instance '{name}' of '{appKey}'? It will stop processing events until restarted." Without `instance`, title stays "Stop app?" and description uses app-level text.

### CLI

**Client post methods** (`src/hassette/cli/client.py`): `post()` (modeled after `get()`, calling `self._client.post()`) deserializes the action routes' `ActionResponse`. `post_with_instance_routing(app_key, action, instance_index)` mirrors `get_with_app_routing()`'s app-level-vs-instance-scoped path selection for the POST side, given an already-resolved index (resolution can't happen inside this method the way it does for GET, since the CLI needs the resolved instance identity to build the confirmation prompt *before* the mutating POST runs). `resolve_instance_with_name(app_key, instance)` resolves a selector to `(index, instance_name | None)` — unlike `resolve_instance()`, it always fetches the manifest (even for a bare index) so a numeric selector's canonical name is available for messages; `instance_name` comes back `None` only when a digit selector has no matching manifest entry, in which case the caller falls back to the raw selector rather than erroring (range validation stays the server's job).

**Action commands** (`src/hassette/cli/commands/app.py`): Add `cmd_app_start`, `cmd_app_stop`, `cmd_app_reload`, all thin wrappers around a shared `_run_app_action(key, action, instance, yes, ctx)`. `cmd_app_stop` and `cmd_app_reload` take `yes: Annotated[bool, Parameter(name=["--yes"])] = False` to bypass the interactive confirmation prompt; `cmd_app_start` never prompts. `_run_app_action` resolves `instance` (if given) via `resolve_instance_with_name()` up front — before any prompt — so the confirmation text and the eventual success message both use the resolved name (or the raw selector as a fallback). It POSTs via `post_with_instance_routing()`, warns to stderr if the server-confirmed `instance_index` disagrees with the requested one, then constructs a success message client-side using a past-tense mapping (start→started, stop→stopped, reload→reloaded).

**Command registration** (`src/hassette/cli/__init__.py`): Register the three new commands on `apps_app`:

```python
apps_app.command(cmd_app_start, name="start")
apps_app.command(cmd_app_stop, name="stop")
apps_app.command(cmd_app_reload, name="reload")
```

### Schema regeneration

Run `uv run python scripts/export_schemas.py --types` after all changes. The backend routes already exist in the OpenAPI spec; the frontend types may already include them. Verify and regenerate regardless.

## Implementation Preferences

No specific implementation preferences — follow codebase conventions. The `ACTIONS` const pattern in `action-buttons.tsx`, the cyclopts command pattern in `commands/app.py`, and the `apiPost` pattern in `endpoints.ts` are the templates.

## Replacement Targets

No existing code is being replaced. This is purely additive — new endpoint functions, a new prop on an existing component, new CLI subcommands, and a new client method.

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

## Alternatives Considered

**Separate InstanceActionButtons component:** Instead of extending `ActionButtons` with an optional `instance` prop, create a new component for instance-level actions. Rejected because the behavior is identical (same buttons, same visibility logic, same confirmation dialog) — the only difference is which URL the POST hits. A single component with an optional prop avoids duplication.

**CLI `hassette instance` top-level command:** Instead of `hassette app start <key> --instance <name>`, a separate `hassette instance start <key> <name>` subcommand tree. Rejected because instance is a subordinate concept to app — the `--instance` flag pattern is already established in the read-only commands and reads naturally.

## Test Strategy

### Required Test Types

- **Frontend component tests** (vitest + testing-library): `ActionButtons` with and without `instance` prop, stop-confirmation dialog title/description, instance-aware toast text, instance-scoped testid/aria-label.
- **CLI unit tests** (pytest): `start`/`stop`/`reload` subcommands with and without `--instance`, verifying correct URL construction and response rendering.
- **E2E** (Playwright): one targeted test for instance detail action buttons firing instance-level routes.

### Existing Tests to Adapt

- `frontend/src/components/shared/action-buttons.test.tsx` (248 lines) — existing tests cover app-level behavior. Add new test cases for instance-level; existing cases should continue passing unchanged (backward compatibility).
- `frontend/src/pages/apps-table-row.test.tsx` — may need updates if the test renders instance sub-rows and asserts on `ActionButtons` props.

### New Test Coverage

- `ActionButtons` with `instance` calls instance endpoints (FR#1–FR#3) — component test
- `ActionButtons` without `instance` still calls app endpoints (FR#4) — component test (verify existing tests cover this)
- Stop dialog shows instance name in both title and description (FR#5) — component test
- Instance-scoped `data-testid` and `aria-label` when `instance` present (FR#6) — component test
- Instance-aware toast text when `instance` present (FR#7) — component test
- `apps-table-row` passes `confirmStop` on both app-level and instance sub-rows (FR#9) — component test
- CLI `start`/`stop`/`reload` without `--instance` (FR#10) — unit test
- CLI `start`/`stop`/`reload` with `--instance` (FR#11–FR#12) — unit test
- CLI success message includes instance name (FR#13) — unit test
- CLI `stop`/`reload` prompt for confirmation, `--yes` bypasses (FR#14) — unit test
- CLI error handling on 404 — unit test
- E2E: instance detail view action buttons fire instance routes (FR#8) — Playwright
- CLI success message resolves a numeric `--instance` selector to its canonical name, and falls back to the raw selector when unresolvable (FR#13) — unit test
- CLI/frontend both warn when the server-confirmed `instance_index` disagrees with the requested one (FR#13) — unit test / component test
- `getStableInstanceRef` returns the same object reference for the same `(index, name)` and distinct references otherwise — unit test

### Tests to Remove

No tests to remove.

## Smoke Test

**Frontend:** Start the demo stack (`mise run demo`). Navigate to a multi-instance app (e.g., the example app configured with multiple instances). Click an instance tab. Click the Reload button. Expect a toast saying the instance was reloaded and the status to update via WebSocket.

**CLI:** With a running hassette instance, run `hassette app reload <key> --instance <name>`. Expect a confirmation prompt; confirm. Expect a success message including the instance name. Run `hassette app stop <key> --yes` (no `--instance`, bypass confirmation). Expect the app-level stop to succeed with an app-level message.

## Documentation Updates

- CLI help text is auto-generated from docstrings by cyclopts — the docstrings on the new `cmd_app_start`/`cmd_app_stop`/`cmd_app_reload` functions are sufficient.
- **modify** `docs/pages/cli/commands.md` — add `start`, `stop`, `reload` to the `hassette app` Subcommands table; extend the per-command Flags table to list `--instance` (with action-appropriate wording, e.g., "Targets a specific app instance") and `--yes` (for `stop`/`reload` only: "Skip confirmation prompt") as accepted by the new action subcommands; update the Shared Flags table further down the page to include the new commands in `--instance`'s scope.

## Impact

### Changed Files

- **modify** `frontend/src/api/endpoints.ts` — add `startInstance`, `stopInstance`, `reloadInstance`
- **modify** `frontend/src/components/shared/action-buttons.tsx` — add `instance` prop (paired object), route to instance endpoints when present, instance-aware toast text/testid/aria-label/dialog title
- **modify** `frontend/src/components/shared/action-buttons.test.tsx` — add instance-level test cases
- **modify** `frontend/src/pages/apps-table-row.test.tsx` — update for `instance` prop and `confirmStop` on both row types
- **modify** `frontend/src/components/app-detail/app-detail-header.tsx` — pass `instance` prop (via `getStableInstanceRef`) to `ActionButtons`, gated on `currentInstance` actually resolving
- **modify** `frontend/src/pages/apps-table-row.tsx` — pass `instance` prop (via `getStableInstanceRef`) to `ActionButtons` in instance sub-rows; add `confirmStop` to both app-level and instance sub-rows
- **modify** `src/hassette/cli/client.py` — add `post()`, `post_with_instance_routing()`, `resolve_instance_with_name()`
- **modify** `src/hassette/cli/commands/app.py` — add `cmd_app_start`, `cmd_app_stop`, `cmd_app_reload` and shared `_run_app_action` (stop/reload include `--yes` flag and confirmation prompt; resolves instance name before prompting; warns on server-confirmed `instance_index` mismatch)
- **modify** `src/hassette/cli/__init__.py` — register the three new commands
- **modify** `src/hassette/web/models.py` — add `instance_index: int | None` to `ActionResponse`
- **modify** `src/hassette/web/routes/apps.py` — thread `instance_index` through `_run_app_action` and the three instance-scoped routes
- **modify** `docs/pages/cli/commands.md` — add new subcommands and update `--instance` flag scope
- **modify** `frontend/openapi.json`, `frontend/src/api/generated-types.ts` — regenerated
- **modify** `tests/unit/cli/test_commands_app.py` — add CLI action command tests (existing file covers `health`/`activity`/`config`/`source`)
- **modify** `tests/integration/web_api/test_endpoints.py` — assert `instance_index` on app- and instance-scoped action responses
- **create** one e2e test case (in existing test file or new)

### Behavioral Invariants

- Existing `ActionButtons` callers that don't pass `instance` must see identical routing behavior (app-level endpoints). Note: FR#9 intentionally adds `confirmStop` to the app-level table row — this is a deliberate behavior change to the existing caller, not a backward-compatibility violation of the instance routing contract.
- Existing CLI commands (`health`, `activity`, `config`, `source`) are unchanged.
- App-level routes (`/apps/{key}/start|stop|reload`) are not modified.

### Blast Radius

- Limited to the frontend dashboard and CLI. No backend changes. No configuration changes. No data model changes.
- The WebSocket event flow is unchanged — `app_status_changed` already carries instance-level data.

## Open Questions

None — all decisions resolved during discovery.
