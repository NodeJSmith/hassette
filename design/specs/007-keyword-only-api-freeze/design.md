# Design: Lock down Bus and Scheduler registration signatures for v1.0

**Date:** 2026-07-11
**Status:** archived
**Scope-mode:** hold

## Problem

Bus and Scheduler registration methods have loose signatures that create three categories of API fragility before the v1.0 freeze:

1. **Positional parameters that should be keyword-only.** Scheduler methods place `name`, `group`, `jitter`, `timeout`, `timeout_disabled` before the `*` separator — any future parameter insertion or reorder silently breaks callers using positional args. Three Bus `on_homeassistant_*` methods have no `*` at all.

2. **Required parameter typed as optional.** Bus enforces `name` at runtime (`ListenerNameRequiredError`) but types it as `str | None = None` — Pyright cannot catch omission. Scheduler defaults `name` to `""` and auto-derives a name from the callable, creating a divergent philosophy from Bus that has to be explained forever.

3. **Incomplete delegate method surfaces.** Ten Bus delegate methods (`on_homeassistant_*`, `on_websocket_*`, `on_app_*`, `on_hassette_service_failed/crashed/started`) omit `on_error`, forcing users to drop down to the underlying primary method to get per-listener error handling.

Secondary: `App.cleanup`, `Resource.cleanup`, and `DatabaseService.cleanup` use `timeout: int | None` when every other timeout in the codebase is `float | None`.

## Goals

- Every registration parameter after the leading required args is keyword-only across Bus, Scheduler, and their sync facades
- `name` is statically required (`name: str`, no default) on all Bus and Scheduler registration methods, enforced by Pyright at development time, with runtime checks kept for dynamic callers
- All Bus delegate methods expose `on_error` and forward it to their underlying primary
- All `cleanup` timeout types are `float | None` (except `remote.py` which mirrors HA's schema)
- `name_auto` infrastructure is fully removed: field, auto-derivation, DB column, telemetry plumbing, frontend hint
- Regression prevention linters ensure these invariants hold for future code

## Non-Goals

- Changing `remote.py` `learn_command` timeout from `int` to `float` — these mirror HA's service schema
- Reworking Bus or Scheduler internal architecture — this is a signature-level change only
- Adding new Bus/Scheduler features beyond `on_error` passthrough

## User Scenarios

No user-facing task flows — this is an internal API signature tightening. The "user" is a Hassette app developer whose code either already passes `name=` (no change needed) or doesn't (gets a Pyright error and/or a runtime exception with a clear fix instruction).

## Functional Requirements

- **FR#1** Scheduler methods `schedule`, `run_in`, `run_once`, `run_every`, `run_minutely`, `run_hourly`, `run_daily`, `run_cron` accept `name`, `group`, `jitter`, `timeout`, `timeout_disabled` only as keyword arguments (after `*`). `run_once` additionally makes `if_past` keyword-only.
- **FR#2** Bus methods `on_homeassistant_restart`, `on_homeassistant_start`, `on_homeassistant_stop` accept `handler`, `where`, `kwargs`, `name` only as keyword arguments (after `*`).
- **FR#3** All Bus registration methods require `name: str` (no default, no `None`) — Pyright reports an error when `name` is omitted. A runtime check raises `ListenerNameRequiredError` if an empty string is passed.
- **FR#4** All Scheduler scheduling methods require `name: str` (no default, no `None`) — Pyright reports an error when `name` is omitted. A runtime check raises `SchedulerNameRequiredError` (new exception) if an empty string is passed. `Scheduler.add_job()` / `_add_job()` also validates `job.name` is non-empty at entry, mirroring `Bus.add_listener()`'s existing guard.
- **FR#5** Scheduler auto-name derivation is removed: `ScheduledJob.__post_init__` no longer generates a name from callable+trigger when none is provided.
- **FR#6** The `name_auto` field is removed from `ScheduledJob`, `ScheduledJobRegistration`, and `JobSummary`.
- **FR#7** A database migration drops the `name_auto` column from the `scheduled_jobs` table.
- **FR#8** The frontend `nameAutoHint` prop and its render block are removed from `handler-detail-layout.tsx` and `job-detail.tsx`.
- **FR#9** Bus delegate methods `on_homeassistant_restart`, `on_homeassistant_start`, `on_homeassistant_stop`, `on_websocket_connected`, `on_websocket_disconnected`, `on_app_running`, `on_app_stopping`, `on_hassette_service_failed`, `on_hassette_service_crashed`, `on_hassette_service_started` accept an `on_error` parameter and forward it to their underlying primary method.
- **FR#10** `App.cleanup`, `Resource.cleanup`, and `DatabaseService.cleanup` accept `timeout: float | None` instead of `timeout: int | None`.
- **FR#11** All sync facade methods (`SchedulerSyncFacade`, `BusSyncFacade`) mirror the signature changes of their async counterparts.
- **FR#12** A pre-commit linter validates that registration method definitions (any public method in `Bus`/`Scheduler` with a `name` parameter) have `*` before `name` and `name` has no default value. Does not check `on_error` passthrough (structurally prevented if #1296 lands, and no runtime enforcement gap to close in the interim).

## Edge Cases

- **Empty string passed as name:** Both Bus and Scheduler runtime checks treat empty string the same as omission — raise the appropriate `NameRequiredError`. This is a belt for dynamic callers who bypass Pyright.
- **Internal framework call sites:** `StateProxy.on_initialize` calls `self.scheduler.run_every(self.load_cache, ...)` without `name=`. This must be updated to pass an explicit name.
- **Existing DB rows with `name_auto=True`:** `handle_schema_version()` now applies migrations incrementally and preserves existing data (fixed in #1298). The column drop is safe: old jobs keep their derived name string, only the metadata flag disappears.
- **Sync facade delegation after `*` moves:** Both `BusSyncFacade` and `SchedulerSyncFacade` currently pass args positionally to their async counterparts. After moving `*`, all positional delegation calls become `TypeError`. `BusSyncFacade.on_homeassistant_*` passes `(handler, where, kwargs, name, **opts)` positionally. `SchedulerSyncFacade` passes `(func, trigger, name, group, jitter, timeout, timeout_disabled, ...)` positionally on all 8 methods. Both must switch to keyword args in their delegation calls.

## Acceptance Criteria

- **AC#1** `uv run pyright` reports an error when any Bus or Scheduler registration method is called without `name=` (FR#3, FR#4)
- **AC#2** Calling a Scheduler method with positional `name`, `group`, `jitter`, `timeout`, or `timeout_disabled` raises `TypeError` (FR#1)
- **AC#3** Calling `on_homeassistant_start` with positional `handler` raises `TypeError` (FR#2)
- **AC#4** `SchedulerNameRequiredError` is raised when `name=""` is passed to any Scheduler scheduling method (FR#4)
- **AC#5** `ListenerNameRequiredError` is raised when `name=""` is passed to any Bus registration method (FR#3). Note: this is new behavior — the current check tests `name is None` only; changing to `not name` extends rejection to empty strings.
- **AC#6** `on_error` handlers fire when passed to any of the 10 delegate methods listed in FR#9
- **AC#7** `name_auto` column does not exist in the `scheduled_jobs` table after migration 010 runs (FR#7)
- **AC#8** `nameAutoHint` does not appear anywhere in the frontend source (FR#8)
- **AC#9** `uv run nox -s dev` passes (all unit + integration tests)
- **AC#10** `prek -a` passes (ruff, pyright, all pre-commit hooks including the new linter)
- **AC#11** The regression prevention linter catches new public methods with a `name` parameter where `*` is missing before `name` or `name` has a default value (FR#12)

## Key Constraints

- The Bus runtime check (`ListenerNameRequiredError`) must fire before any async work — it is a synchronous guard at the top of the method. The new Scheduler equivalent must follow the same pattern.
- Sync facades are pure delegation wrappers. Their signatures must always match their async counterparts exactly — the only difference is the `run_sync` wrapper.
- The `name_auto` DB column is in migration 001. The new migration must DROP it, not just stop writing it.

## Dependencies and Assumptions

- No external system dependencies — this is entirely internal API surface work.
- Assumes all callers in the repo (tests, docs, examples, internal framework) are the complete set of callers that need updating. End-user apps will also need updating, but that's communicated via the `BREAKING CHANGE:` footer.

## Architecture

### Keyword-only enforcement

**Scheduler (`scheduler.py`):** Move `*` from its current position (after `timeout_disabled`, before `mode`) to before `name` on all 8 methods. This makes `name`, `group`, `jitter`, `timeout`, `timeout_disabled` keyword-only. For `run_once`, `if_past` also moves after `*`.

**Bus (`bus.py`):** Add `*` after `self` on `on_homeassistant_restart`, `on_homeassistant_start`, `on_homeassistant_stop` — making `handler`, `where`, `kwargs`, `name` keyword-only. All other Bus methods already have `*` in the correct position.

**Sync facades:** Both `sync.py` files are auto-generated by the codegen tool (`codegen/src/hassette_codegen/sync_facade/`) and regenerated by pre-push hooks. After moving `*` on the async methods, regenerate both facades — the codegen's `format_signature_and_call()` already emits keyword-style delegation for kwonly params automatically. Do not hand-edit `sync.py` files; they are overwritten on regeneration. For the `on_error` addition to delegate methods, the codegen will pick up the new parameter from the async signature.

### Required name

**Bus:** Change `name: str | None = None` to `name: str` on all registration methods in `bus.py` and `sync.py`. Keep the existing `ListenerNameRequiredError` check but change the condition from `name is None` to `not name` (catches empty string too after the type change).

**Scheduler:** Change `name: str = ""` to `name: str` on all 8 methods in `scheduler.py` and `sync.py`. Add a new `SchedulerNameRequiredError` exception in `exceptions.py` modeled on `ListenerNameRequiredError` — constructor takes `handler_method: str` and `trigger_description: str` (the scheduler analogue of `topic`). Add a runtime check at the top of `Scheduler.schedule()` (the primary — all convenience methods delegate here, so one check covers all 8). Also add a symmetric check to `Scheduler.add_job()` / `_add_job()` — this entry point takes a pre-built `ScheduledJob` and bypasses `schedule()`, so it needs its own guard (`if not job.name: raise SchedulerNameRequiredError(...)`) mirroring `Bus.add_listener()`'s existing pattern at `bus.py:256`.

### Auto-naming removal

Remove `ScheduledJob.name_auto` field from `classes.py` and the `__post_init__` auto-derivation logic (lines 297-301). Thread the removal through:
- `ScheduledJobRegistration.name_auto` in `registration.py`
- `JobSummary.name_auto` in `telemetry_models.py`
- SELECT in `registration_queries.py`
- INSERT/UPDATE/params in `repository.py`
- `ScheduledJobRegistration(name_auto=job.name_auto, ...)` construction in `scheduler_service.py:298`
- `make_job_registration` factory in `test_utils/factories.py`

### Database migration

New migration `010.sql`:
```sql
ALTER TABLE scheduled_jobs DROP COLUMN name_auto;
```

### Frontend cleanup

Remove `nameAutoHint` prop from `handler-detail-layout.tsx` (interface, destructuring, render block, CSS). Remove `nameAutoHint={job.name_auto}` from `job-detail.tsx`. Regenerate `generated-types.ts` from the updated OpenAPI spec after removing `name_auto` from `JobSummary`.

### on_error passthrough

Add `on_error: "BusErrorHandlerType | None" = None` to the 10 delegate methods in `bus.py` and pass it through to the underlying primary method call. Mirror the same addition on the corresponding `BusSyncFacade` methods in `sync.py`.

### Timeout type widening

Change `timeout: int | None = None` to `timeout: float | None = None` on `App.cleanup` (`app.py:152`), `Resource.cleanup` (`base.py:621`), and `DatabaseService.cleanup` (`database_service.py:347`).

### Regression prevention linter

New `tools/check_registration_signatures.py` — AST-based linter (same pattern as `check_lazy_imports.py`) wired into `.pre-commit-config.yaml` at pre-commit + pre-push stages. Scans `bus.py` and `scheduler.py` for any public method (not `_`-prefixed) with a parameter named `name`, then checks:
1. `*` separator appears before the `name` parameter (prevents positional-arg regression — no runtime enforcement exists for this)
2. The `name` parameter has no default value (prevents silent reintroduction of optional name — Pyright and runtime checks cover the caller side, but not the definition side)

## Implementation Preferences

No specific implementation preferences — follow codebase conventions. The exception pattern follows `ListenerNameRequiredError` exactly. The linter follows the `check_lazy_imports.py` AST pattern exactly. The migration follows existing `migrations_sql/*.sql` conventions.

## Replacement Targets

- `ScheduledJob.__post_init__` auto-name derivation (lines 297-301 in `classes.py`) — removed entirely, replaced by required `name` parameter
- `ScheduledJob.name_auto` field (line 198 in `classes.py`) — removed, no replacement
- `name_auto` column in `scheduled_jobs` table — dropped via migration 010
- Frontend `nameAutoHint` prop and render block — removed, no replacement

## Migration

New migration `010.sql` drops the `name_auto` column from `scheduled_jobs`. `handle_schema_version()` applies migrations incrementally and preserves existing data (fixed in #1298), so this migration is a safe one-way column drop with no data transformation needed.

## Convention Examples

### Exception pattern — `ListenerNameRequiredError`

**Source:** `src/hassette/exceptions.py:313-330`

```python
class ListenerNameRequiredError(HassetteError):
    """Raised at call time when ``name=`` is omitted on a DB-registered listener.

    Attributes:
        handler_method: Fully-qualified name of the handler function.
        topic: The event topic the listener was being registered for.
    """

    def __init__(self, handler_method: str, topic: str) -> None:
        self.handler_method = handler_method
        self.topic = topic
        super().__init__(
            f"Listener registration requires a name.\n\n"
            f"  handler: {handler_method}\n"
            f"  topic:   {topic}\n\n"
            f"Provide a stable name via the `name=` parameter:\n\n"
            f'  await self.bus.on_state_change({topic!r}, handler=self.handler, name="my_listener")'
        )
```

### Registration method with correct `*` placement — `Bus.on()`

**Source:** `src/hassette/bus/bus.py:432-450`

```python
def on(
    self,
    *,
    topic: str,
    handler: "HandlerType",
    where: WhereClause = None,
    kwargs: Mapping[str, Any] | None = None,
    once: bool = False,
    debounce: float | None = None,
    throttle: float | None = None,
    timeout: float | None = None,
    timeout_disabled: bool = False,
    mode: "ExecutionMode | str | None" = None,
    backpressure: "BackpressurePolicy | str | None" = None,
    name: str | None = None,
    on_error: "BusErrorHandlerType | None" = None,
    if_exists: IfExistsPolicy = "error",
) -> "Coroutine[Any, Any, Subscription]":
```

DON'T: Place `*` after behavioral parameters like the scheduler currently does — it defeats keyword-only enforcement for the params that matter most (`name`, `group`).

### Linter script pattern

**Source:** `tools/check_lazy_imports.py:1-28`

AST-based, runs on `src/` files, wired into `.pre-commit-config.yaml` with `stages: [pre-commit, pre-push]`. Uses `ast.parse` + visitor pattern. Exit code 0 on clean, 1 with specific file:line references on violations.

### Delegate method delegation — `BusSyncFacade.on_homeassistant_restart`

**Source:** `src/hassette/bus/sync.py:447-454`

```python
def on_homeassistant_restart(
    self, handler: "HandlerType", where: WhereClause = None,
    kwargs: Mapping[str, Any] | None = None, name: str | None = None,
    **opts: Unpack[Options],
) -> Subscription:
    return self.task_bucket.run_sync(
        self._bus.on_homeassistant_restart(handler, where, kwargs, name, **opts)
    )
```

DON'T: Pass args positionally to the async method when the async method uses keyword-only params. After this change, delegation must use keyword args.

## Alternatives Considered

**Runtime-only enforcement for `name` (keep `str | None = None`):** Considered following the existing Bus pattern without changing the type. Rejected because the whole point of this API freeze is to let the type checker enforce correctness — runtime-only enforcement lets bugs slip to production that Pyright could have caught.

**Leave `name_auto` as a legacy indicator:** Considered keeping the column and UI hint for historical jobs. Rejected for a clean break — the column becomes permanently false for all new jobs, the UI hint is dead code for the future, and maintaining it adds complexity for zero ongoing value.

**Per-method `*` on scheduler convenience methods:** Considered adding `*` only to the convenience methods (`run_in`, etc.) and leaving `schedule()` unchanged. Rejected because `schedule()` has the same positional-arg problem and is the most common direct entry point.

## Test Strategy

### Existing Tests to Adapt
- `tests/unit/test_scheduler_job_names.py` — `TestAutoGeneratedNamesWithTrigger` class tests auto-name derivation; rewrite to test `SchedulerNameRequiredError` instead. `TestJobNameUniqueness.test_auto_named_jobs_also_enforce_uniqueness` assumes empty-name jobs are legal; update to use explicit names.
- `tests/unit/scheduler/test_scheduled_job_lifecycle.py` — references `name_auto`; update to remove.
- `tests/unit/core/test_telemetry_repository.py` — references `name_auto`; update to remove.
- `tests/integration/database/test_database_service_migrations.py` — may reference `name_auto`; verify and update.
- ~192 test call sites across `tests/` that omit `name=` — add explicit `name=` to each.
- `tests/integration/bus/` and `tests/unit/bus/` — Bus registration calls that omit `name=` need explicit names.
- `src/hassette/test_utils/factories.py` — remove `name_auto` parameter from `make_job_registration`.
- `frontend/src/test/factories.ts` — remove `name_auto` from job factory.
- `frontend/src/components/app-detail/handlers-tab.test.tsx` — remove `name_auto` assertions.

### New Test Coverage
- **FR#4:** Test that `SchedulerNameRequiredError` is raised when `name` is omitted or empty — mirror `tests/unit/bus/test_registration_errors.py` pattern.
- **FR#1, FR#2:** Tests that positional args after `*` raise `TypeError` — a few representative tests covering scheduler and bus.
- **FR#9:** Tests that `on_error` fires when passed to delegate methods — at least one representative test per delegation chain (on_homeassistant_start → on_call_service, on_hassette_service_failed → on_hassette_service_status, on_websocket_connected → on, on_app_running → on_app_state_changed).
- **FR#12:** Test the new linter script itself — a few sample inputs (valid signatures, invalid signatures) asserting correct exit codes.

### Tests to Remove
- `TestAutoGeneratedNamesWithTrigger` class in `tests/unit/test_scheduler_job_names.py` — tests functionality being removed.
- Any assertions on `name_auto` field values across the test suite.

## Documentation Updates

- **Scheduler concept docs** (`docs/pages/core-concepts/scheduler/`): Update prose and ~18 snippet files that omit `name=` on scheduler calls. Remove any references to auto-naming behavior ("If empty, an auto-name is derived...").
- **Bus concept docs** (`docs/pages/core-concepts/bus/`): Update snippet files that omit `name=` on bus calls.
- **Getting started** (`docs/pages/getting-started/`): Update `first_automation_step4.py` and related snippets to include `name=`.
- **Recipes** (`docs/pages/recipes/`): Update `daily_notification.py` and related snippets.
- **Migration guide** (`docs/pages/migration/`): Update scheduler and bus migration snippets. Consider adding a migration note for the `name=` requirement change.
- **Operating docs** (`docs/pages/operating/`): Update `timeout_overrides.py` snippet.
- **Cache docs** (`docs/pages/core-concepts/cache/`): Update cache snippets that use scheduler.
- **Example apps** (`examples/`): Sweep for missing `name=` on scheduler calls (most already have it).
- **Docstrings** on all modified methods: Update parameter descriptions (remove "optional"/"if empty" language for `name`, add `on_error` parameter docs to delegate methods, update `timeout` type in cleanup docstrings).
- **Scheduler method docstrings**: Remove "If empty, an auto-name is derived from the callable and trigger ID" language.
- **`scheduler.py` module-level docstring** (lines 10-59): Contains ~10 usage examples that omit `name=`. These render in the auto-generated API reference via mkdocstrings. Update all examples to include `name=`.

## Impact

### Changed Files

**Shared / cross-cutting (higher risk):**
- modify `src/hassette/exceptions.py` — add `SchedulerNameRequiredError`
- create `src/hassette/migrations_sql/010.sql` — drop `name_auto` column
- modify `src/hassette/schemas/telemetry_models.py` — remove `name_auto` from `JobSummary`
- modify `src/hassette/core/registration.py` — remove `name_auto` from `ScheduledJobRegistration`
- modify `src/hassette/test_utils/factories.py` — remove `name_auto` from `make_job_registration`

**Scheduler package:**
- modify `src/hassette/scheduler/scheduler.py` — move `*` before `name`, change `name: str = ""` to `name: str`, add runtime check
- regenerate `src/hassette/scheduler/sync.py` — codegen picks up `*` position and `name` type changes automatically
- modify `src/hassette/scheduler/classes.py` — remove `name_auto` field and auto-derivation in `__post_init__`

**Bus package:**
- modify `src/hassette/bus/bus.py` — add `*` to 3 methods, change `name: str | None = None` to `name: str` on all, add `on_error` to 10 delegates
- regenerate `src/hassette/bus/sync.py` — codegen picks up `*`, `name` type, and `on_error` additions automatically

**Resource / app:**
- modify `src/hassette/app/app.py` — `cleanup` timeout `int` → `float`
- modify `src/hassette/resources/base.py` — `cleanup` timeout `int` → `float`
- modify `src/hassette/core/database_service.py` — `cleanup` timeout `int` → `float`

**Telemetry plumbing:**
- modify `src/hassette/core/scheduler_service.py` — remove `name_auto=job.name_auto` from `ScheduledJobRegistration()` construction (line 298)
- modify `src/hassette/core/telemetry/repository.py` — remove `name_auto` from INSERT/UPDATE/params
- modify `src/hassette/core/telemetry/registration_queries.py` — remove `name_auto` from SELECT

**Internal call site:**
- modify `src/hassette/core/state_proxy.py` — add explicit `name=` to `run_every` call

**Frontend:**
- modify `frontend/src/components/app-detail/handler-detail-layout.tsx` — remove `nameAutoHint` prop and render
- modify `frontend/src/components/app-detail/job-detail.tsx` — remove `nameAutoHint` prop pass
- modify `frontend/src/components/app-detail/handler-detail-layout.module.css` — remove `.nameAutoHint` class
- modify `frontend/src/test/factories.ts` — remove `name_auto`
- modify `frontend/src/components/app-detail/handlers-tab.test.tsx` — remove `name_auto` assertions
- regenerate `frontend/src/api/generated-types.ts` — reflects `JobSummary` change

**Tooling:**
- create `tools/check_registration_signatures.py` — new regression prevention linter
- modify `.pre-commit-config.yaml` — wire new linter

**Tests (bulk — mechanical `name=` addition):**
- modify ~192 test files across `tests/unit/`, `tests/integration/`, `tests/system/`
- modify/rewrite `tests/unit/test_scheduler_job_names.py`

**Docs / examples (bulk — mechanical `name=` addition):**
- modify ~18 scheduler snippet files under `docs/pages/`
- modify bus snippet files under `docs/pages/`
- modify `examples/cover_scheduler.py` and other example apps

### Behavioral Invariants
- All existing Bus event routing behavior is unchanged — only method signatures change
- All existing Scheduler job execution behavior is unchanged
- `ListenerNameRequiredError` still fires for Bus callers who pass empty name
- Existing scheduled jobs with auto-derived names continue working (the name string is preserved; only the `name_auto` metadata flag is dropped)
- `on_error` handlers on primary methods continue to work identically
- Sync facades continue to produce identical results to their async counterparts

### Blast Radius
- **End-user apps** that call Scheduler methods without `name=` will break at call time. This is the intended breaking change, communicated via `BREAKING CHANGE:` footer.
- **End-user apps** that call Bus methods without `name=` — no change in runtime behavior (already raised `ListenerNameRequiredError`), but now Pyright also catches it.
- **End-user apps** using positional args for `name`, `group`, etc. will get `TypeError`. Unlikely in practice — all test call sites already use keyword args.

## Open Questions

None — all decisions resolved during discovery.
