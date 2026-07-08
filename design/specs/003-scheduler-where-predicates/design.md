# Design: Scheduler `where=` Predicate Support

**Date:** 2026-07-06
**Status:** archived
**Scope-mode:** hold
**Research:** /tmp/claude-mine-define-research-VR3Z3i/brief.md

## Problem

Scheduler jobs execute unconditionally when their trigger fires. Developers who want conditional execution — "run this daily check only if the alarm is armed," "skip this polling job when the house is empty" — must write guard clauses at the top of every job callback:

```python
async def my_daily_check(self):
    if not self.states.get("binary_sensor.motion").is_on:
        return  # manual guard — invisible to telemetry
    # actual logic
```

This has three costs: the guard logic is invisible to telemetry (a silently-returning handler looks like a successful execution), every job that needs conditional execution repeats the same boilerplate pattern, and the conditional intent is buried inside the handler rather than declared at the registration site.

The bus already has `where=` on every subscription method, with normalization, summarization, and telemetry. The scheduler has no equivalent.

## Goals

- `where=` parameter on `Scheduler.schedule()` and all convenience methods (`run_in`, `run_once`, `run_every`, `run_daily`, `run_cron`, `run_minutely`, `run_hourly`)
- Predicate evaluated at dispatch time, before the handler runs
- Skipped executions recorded in telemetry with `'skipped'` status and visible in the web UI
- Predicate description stored in the `scheduled_jobs` table and displayed in the job detail UI
- Consistent API surface with bus `where=` (same parameter name, scheduler-specific normalization for sequences)

## User Scenarios

### App developer: automation author

- **Goal:** register a recurring job that only runs under certain conditions
- **Context:** writing an `on_initialize` method, scheduling jobs that should be conditional on HA state

#### Conditional daily job

1. **Registers a daily job with `where=`**
   - Sees: `self.scheduler.run_daily(self.morning_routine, at="07:00", where=self.is_home)`
   - Decides: which predicate to use for the condition
   - Then: job is registered with predicate stored and described in telemetry

2. **Job fires at 07:00, predicate returns True**
   - Sees: handler executes normally, telemetry shows `success` status
   - Then: job is rescheduled for tomorrow

3. **Job fires at 07:00, predicate returns False**
   - Sees: handler does not execute, telemetry shows `skipped` status with duration 0ms
   - Then: job is rescheduled for tomorrow

#### One-shot conditional job

1. **Registers a delayed job with `where=`**
   - Sees: `self.scheduler.run_in(self.delayed_action, 300, where=lambda: self.states.get("alarm.armed").state == "armed")`
   - Then: job is scheduled to fire in 5 minutes

2. **Job fires, predicate returns False**
   - Sees: handler does not execute, telemetry shows `skipped` status
   - Then: job is consumed (removed from scheduler) — one-shots do not retry on skip

### Operator: monitoring the dashboard

- **Goal:** understand why a job didn't execute at its scheduled time
- **Context:** checking the web UI job detail page

#### Viewing skipped executions

1. **Opens job detail page**
   - Sees: execution history showing `skipped` entries alongside `success`/`error`/etc., skipped count in stats grid, predicate description in job metadata
   - Decides: whether the skip was expected based on the predicate description
   - Then: no action needed if the predicate correctly gated execution

## Functional Requirements

- **FR#1** `Scheduler.schedule()` accepts a `where` parameter of type `SchedulerPredicate | Sequence[SchedulerPredicate] | None` (defaulting to `None`), where `SchedulerPredicate` is a new type alias (`Callable[..., bool]`) — distinct from the bus `Predicate[EventT]` protocol which requires exactly one event argument
- **FR#2** All convenience methods (`run_in`, `run_once`, `run_every`, `run_daily`, `run_cron`, `run_minutely`, `run_hourly`) accept and forward the `where` parameter to `schedule()`
- **FR#3** The predicate is normalized at registration time (single callable stored directly; sequences collapsed into an `_AllPredicates` combinator) and stored on the `ScheduledJob` dataclass alongside a pre-built DI invoker
- **FR#4** At dispatch time, the predicate is evaluated before the handler runs; if it returns `False`, the handler is not invoked
- **FR#5** A skipped execution produces an `ExecutionRecord` with `status='skipped'` and `duration_ms=0.0`
- **FR#6** For recurring jobs, a skipped execution does not affect the schedule — the next occurrence is computed and enqueued regardless of predicate outcome
- **FR#7** For one-shot jobs, a skipped execution consumes the job (removes it from the scheduler)
- **FR#8** Predicate exceptions are caught and logged with traceback; the handler does not run. An `ExecutionRecord` with `status='error'` is enqueued and the job's `on_error` handler (or app-level fallback) is invoked — the same routing a raising handler gets. (Revised during PR review: originally specified as fail-open.)
- **FR#9** Predicate arity is annotation-based: a parameter annotated as `ScheduledJob` receives the job via DI; unannotated predicates (including lambdas) dispatch as zero-arg
- **FR#10** Predicate signatures are inspected once at registration time via the shared DI layer (`hassette.di`: `build_injection_plan` → `CallableInvoker`); dispatch resolves kwargs through the stored invoker without re-inspecting
- **FR#11** The `scheduled_jobs` database table stores `predicate_description` (Python repr) and `human_description` (from `callable_stable_name()` with `hasattr` fallback to `summarize()`)
- **FR#12** The `executions` table `status` CHECK constraint allows `'skipped'` as a valid value
- **FR#13** The `JobSummary` telemetry model includes a `skipped` count field
- **FR#14** `skipped` executions count toward `total_executions` (preserving the invariant: `successful + failed + cancelled + timed_out + skipped == total_executions`)
- **FR#15** The `ScheduledJob.matches()` and `diff_fields()` methods include the predicate in collision detection (equality comparison, with identity semantics for lambdas/closures)
- **FR#16** Predicates are synchronous only — async callables raise `TypeError` at registration time

## Edge Cases

- **Predicate raises an exception:** caught and logged as an error (with traceback via `logger.exception`); the handler does not run. The fire is recorded with `status='error'` (including error type, message, and traceback), the `on_error` handler is invoked, and one-shot jobs are still removed.
- **Predicate on a one-shot that returns False:** job is consumed. The developer chose to gate it — the skip is deliberate.
- **Lambda identity in `matches()`/`diff_fields()`:** two lambdas with identical source compare by identity (`is`), so `if_exists="skip"` treats them as different jobs. This matches `Listener`'s existing behavior and is documented in the bus.
- **Zero-arg lambda summarization:** `summarize_top_level()` falls back to `callable_stable_name()`, returning the function name or `"<callable>"` for lambdas. Named functions and predicate dataclasses with `summarize()` produce better descriptions.
- **One-arg predicate sees post-advance state:** Because the predicate runs after step 1 (compute next occurrence), `job.next_run` and `job.fire_at` reflect the *next* occurrence, not the time currently firing. `job.args` and `job.kwargs` are unaffected. This is acceptable — predicates that need timing info should use `date_utils.now()` rather than inspecting the job's schedule fields.
- **`where=` with `if_exists="skip"`:** if an existing job matches on all fields including predicate, the new registration is skipped. If the predicate differs, `matches()` returns `False` and `_add_job()` raises `ValueError` naming the changed fields (same as any other config mismatch — the new job does not silently register alongside the old one).
- **Predicate takes >1 positional parameter:** accepted. Parameters without a `ScheduledJob` annotation are not injected (per FR#9's annotation-based rule), so a predicate whose extra parameters all have defaults dispatches fine; one whose extra parameters lack defaults fails at call time like any Python callable.
- **Manual trigger ("Run Now") bypasses predicates:** The `POST /api/scheduler/jobs/{job_id}/trigger` endpoint calls `run_job_with_guard()` directly, not `dispatch_and_log()`. Since the predicate check lives inside `dispatch_and_log()`, manually-triggered executions skip the predicate entirely. This is intentional — "Run Now" is an explicit operator action that should always fire, regardless of conditional gating. The resulting execution records have `trigger_mode="manual"` and no `'skipped'` status.

## Acceptance Criteria

- **AC#1** A job registered with `where=lambda: False` never executes its handler but produces `'skipped'` execution records on every trigger fire (FR#4, FR#5)
- **AC#2** A recurring job with a `where=` predicate that returns `False` is rescheduled for its next occurrence (FR#6)
- **AC#3** A one-shot job (`run_in`) with a `where=` predicate that returns `False` is consumed after skip (FR#7)
- **AC#4** A predicate that raises an exception logs an error (with traceback), records a `status='error'` execution, invokes `on_error`, and does not run the handler (FR#8)
- **AC#5** A predicate with a `ScheduledJob`-annotated positional parameter receives the job instance; a predicate without such annotation is called with zero arguments (FR#9, FR#10)
- **AC#6** An async predicate raises `TypeError` at registration time (FR#16)
- **AC#7** The job detail page in the web UI displays the `skipped` count and predicate description (FR#11, FR#13)
- **AC#8** `total_executions` in `JobSummary` equals `successful + failed + cancelled + timed_out + skipped` (FR#14)
- **AC#9** The `ScheduledJob.matches()` method includes predicate in comparison (FR#15)
- **AC#10** `Scheduler.schedule()` accepts `where=` directly, and all seven convenience methods forward it (FR#1, FR#2)

## Key Constraints

- Predicate evaluation must happen after the next occurrence is computed and enqueued (so recurring schedules continue) but before the handler is invoked. The interception point is inside `dispatch_and_log()`, between step 1 (compute next / enqueue) and step 2 (run through guard).
- The `executions.status` CHECK constraint modification requires SQLite table recreation (CREATE → INSERT...SELECT → DROP → RENAME) because SQLite does not support `ALTER CONSTRAINT`. This migration must preserve all indexes and the foreign key `CHECK` constraint.
- Predicate evaluation must not go through the `CommandExecutor._execute()` path — `track_execution()` wraps actual invocation timing and is meaningless for a skip. The skip path builds an `ExecutionRecord` directly and enqueues it via `enqueue_record()`.

## Dependencies and Assumptions

- The bus's `AllOf`, `normalize_where()`, `summarize_top_level()`, and `_summarize_predicate()` are all typed for `Predicate[EventT]` (one-arg) and cannot accept zero-arg scheduler predicates. The scheduler uses its own normalization (`_AllPredicates` combinator for sequences) and summarization (`callable_stable_name()` directly, with `hasattr` fallback to `summarize()`).
- `inspect.signature` from stdlib is sufficient for predicate arity inspection (no new dependencies).
- The `ExecutionStatus` StrEnum in `types/types.py` is the authoritative source for valid status values; the SQL CHECK constraint is defense-in-depth.

## Architecture

### Predicate storage

Define a new `SchedulerPredicate` type alias in `src/hassette/types/types.py`:

```python
SchedulerPredicate = Callable[..., bool]
```

This is distinct from the bus `Predicate[EventT]` protocol (which requires exactly one event argument). The scheduler predicate supports zero-arg (common case) or one-arg (receives `ScheduledJob`).

Add a `predicate` field to `ScheduledJob`:

```python
predicate: "SchedulerPredicate | None" = field(default=None, compare=False)
```

The predicate is normalized at registration time inside `Scheduler.schedule()` via `_normalize_where()`. For a single callable, store it directly alongside its DI invoker. For a sequence, collapse into a frozen `_AllPredicates` dataclass that holds `(predicate, invoker)` pairs and ANDs the results.

`_AllPredicates` is a combinator class (the design originally specified a bare closure; a lambda was replaced during PR review because closures compare by identity, which broke `if_exists=` collision detection — two independently-built sequences of the same predicate functions must compare equal). The bus's `AllOf` is typed for one-arg `Predicate[EventT]` and cannot be reused for scheduler predicates. This does not constrain the future design — when composable predicate classes (e.g., `IsHome("jessica") & StateIs("light.office", "on")`) are built later, they'll implement `__and__`/`__or__` returning their own combinator, and the scheduler's `where=` parameter accepts them without changes (any callable works).

Sequence members keep the single-predicate contract: each member carries its own DI invoker, so a `ScheduledJob`-annotated member receives the job and unannotated members are called with zero arguments.

### Predicate summarization

The bus's `summarize_top_level()` and `_summarize_predicate()` are typed for `Predicate[EventT]` and reject zero-arg callables at the type level. The scheduler calls `callable_stable_name()` directly for `human_description` generation, and delegates to a predicate's `summarize()` method when present (via `hasattr` check). For `predicate_description`, `repr(predicate)` is used (same as the bus). `_AllPredicates.summarize()` joins member names with `" and "`, mirroring the bus's `AllOf.summarize()`; lambdas still render as `"<callable>"` — users who want informative telemetry descriptions use named functions or (in the future) predicate dataclasses with `summarize()`.

### Predicate arity detection

At registration time in `Scheduler.schedule()`, `_build_predicate_invoker()` inspects the predicate's signature via the shared DI layer (`hassette.di`): `get_typed_signature()` → `build_injection_plan(sig, (TypeMatcher(ScheduledJob),))` → `CallableInvoker`. The invoker is stored on `ScheduledJob.predicate_invoker` (passed to the constructor alongside `predicate`). At dispatch time, `predicate_invoker.invoke({ScheduledJob: job})` resolves kwargs without re-inspecting, and the predicate is called with `predicate(**kwargs)`. (The design originally specified a `_predicate_wants_job: bool` flag with positional dispatch; the DI-layer rewrite replaced it after `hassette.di` shipped.)

Detection rules:
- If the predicate is async (detected via `inspect.iscoroutinefunction()`) → `TypeError`
- If a parameter is annotated as `ScheduledJob` (or a union containing it, e.g. `ScheduledJob | None`) → the injection plan injects the job for that parameter. Dispatch passes kwargs, so keyword-only parameters resolve the same as positional ones.
- If the signature has `*args` or positional-only parameters → `DependencyInjectionError` (shared DI validation)
- If the signature cannot be inspected at all (some builtins/C callables) → empty invoker, zero-arg dispatch
- Otherwise (no `ScheduledJob` annotation found, including lambdas and unannotated functions) → empty injection plan, zero-arg dispatch

### Predicate evaluation

In `SchedulerService.dispatch_and_log()`, insert a predicate check between step 1 (compute next occurrence) and step 2 (run through guard):

```python
# After step 1 (next occurrence computed, enqueued if recurring)
if job.predicate is not None:
    predicate_start = time.time()
    try:
        kwargs = job.predicate_invoker.invoke({ScheduledJob: job}) if job.predicate_invoker else {}
        should_run = job.predicate(**kwargs)
    except Exception as exc:
        self.logger.exception("Predicate raised for job %s — recording failure; the job does not run", job)
        self._record_predicate_failure(job, exc, predicate_start)
        if remove_after_fire:
            await self._try_remove_job(job, "predicate-error")
        return

    if not should_run:
        self.logger.debug("Predicate returned False for job %s — skipping", job)
        self._record_skipped(job)
        if remove_after_fire:
            await self._try_remove_job(job, "skipped")
        return
```

The `_record_skipped()` method builds an `ExecutionRecord` with `status='skipped'`, `duration_ms=0.0`, and enqueues it via `self._executor.enqueue_record()`. `_record_predicate_failure()` builds a `status='error'` record (with error type, message, traceback, and the real predicate-evaluation duration) and routes the exception to the job's `on_error` handler via `CommandExecutor.invoke_error_handler()`. Both bypass `_execute()` / `track_execution()` entirely.

### API surface

Add `where: "SchedulerPredicate | Sequence[SchedulerPredicate] | None" = None` to `Scheduler.schedule()` and forward from all convenience methods. The parameter position is after the existing keyword arguments, consistent with the bus methods.

### Registration telemetry

Add `predicate_description: str | None` and `human_description: str | None` to `ScheduledJobRegistration`. Populated in `SchedulerService.add_job()` using `repr(job.predicate)` for `predicate_description` and the scheduler's own summarization (see Predicate summarization section above) for `human_description`.

### Database migration (009.sql)

Three changes in a single migration:

1. **Add columns to `scheduled_jobs`:** `predicate_description TEXT` and `human_description TEXT` (nullable, no CHECK needed).
2. **Modify `executions.status` CHECK:** Requires SQLite table recreation. CREATE `executions_new` with the updated CHECK (`status IN ('success', 'error', 'cancelled', 'timed_out', 'skipped')`), INSERT...SELECT from `executions`, DROP `executions`, ALTER TABLE RENAME `executions_new` → `executions`. Recreate all indexes.
3. **Add `SKIPPED` to `ExecutionStatus` StrEnum** in `types/types.py`.

### SQL query updates

The `get_job_summary()` query in `registration_queries.py` needs two changes:

1. **Add `skipped` aggregation bucket:**
```sql
SUM(CASE WHEN e.status = 'skipped' THEN 1 ELSE 0 END) AS skipped,
```

2. **Add new `scheduled_jobs` columns to the SELECT list** (the query selects columns by name, not `SELECT *`):
```sql
sj.predicate_description,
sj.human_description,
```

These mirror `get_listener_summary()`'s existing `l.predicate_description, l.human_description` at lines 80-81.

The `total_executions` (from `COUNT(e.rowid)`) already includes all rows regardless of status, so the invariant holds automatically.

The global summary queries in `summary_queries.py` need one change: `get_app_health_aggregates()` computes `AVG(CASE WHEN e.kind = 'job' THEN e.duration_ms END) AS job_avg_duration_ms`. Since skipped executions have `duration_ms=0.0` (FR#5), they would silently dilute the average. Exclude them:

```sql
AVG(CASE WHEN e.kind = 'job' AND e.status != 'skipped' THEN e.duration_ms END) AS job_avg_duration_ms
```

The same exclusion applies to any other `AVG`/`MIN`/`MAX` duration aggregation that would be distorted by zero-duration skip records. Error/timeout counts and `total_executions` correctly handle `'skipped'` without edits.

### Collision detection

Add `predicate` to `ScheduledJob.matches()` and `diff_fields()`:

```python
# In matches():
and self.predicate == other.predicate

# In diff_fields():
if self.predicate != other.predicate:
    changed.append("predicate")
```

This uses equality comparison. Lambda/closure predicates compare by identity (same as `Listener`), which is documented behavior.

### Frontend changes

1. **`ExecutionStatus` type** — regenerated from OpenAPI spec, will include `'skipped'`
2. **`executionStatusKind()`** in `utils/status.ts` — map `'skipped'` to `StatusKind` `"mute"` (renders as a ring shape, neutral visual weight)
3. **`job-detail.tsx`** — add `Skipped` cell to the stats grid in `buildJobStatsCells()`
4. **`JobSummary` response model** — add `skipped: int = 0` field, exposed to frontend via OpenAPI
5. **`scheduled_jobs` table columns** — `predicate_description` and `human_description` exposed through `JobSummary` for display in job metadata

## Implementation Preferences

No specific implementation preferences — follow codebase conventions.

## Replacement Targets

No existing code is being replaced. This is purely additive — the manual guard-clause pattern continues to work; `where=` provides a declarative alternative.

## Migration

### Schema changes

- `scheduled_jobs` table: add `predicate_description TEXT` and `human_description TEXT` columns (nullable)
- `executions` table: modify `status` CHECK constraint to include `'skipped'` (requires table recreation in SQLite)

### Data impact

- Existing `scheduled_jobs` rows get `NULL` for both new columns (correct — no predicate was registered)
- Existing `executions` rows are unchanged (no existing row has `'skipped'` status)
- The table recreation preserves all existing data via INSERT...SELECT
- Migration is forward-only (no rollback support, consistent with existing migrations)

## Convention Examples

### Predicate normalization and storage in `Listener.create()`

**Source:** `src/hassette/bus/listeners.py:592-601`

```python
pred = normalize_where(where)
return cls(
    logger=logger,
    topic=topic,
    predicate=pred,
    identity=identity,
    invoker=invoker,
    options=options,
    duration_config=duration_config,
)
```

The scheduler cannot reuse `normalize_where()` or `AllOf` directly (both are typed for the bus `Predicate[EventT]` protocol), but follows the same single-entry-point pattern: normalize once at registration, store the result, never re-normalize at dispatch. Sequences collapse into the `_AllPredicates` combinator, the scheduler's analog of the bus's `AllOf`.

### Predicate evaluation in `Listener.matches()`

**Source:** `src/hassette/bus/listeners.py:557-565`

```python
def matches(self, ev: "Event[Any]") -> bool:
    if self.predicate is None:
        return True
    matched = self.predicate(ev)
    verdict = "matched" if matched else "did not match"
    self.logger.debug("Listener %s %s predicate for event: %s", self, verdict, ev)
    return matched
```

### Collision detection pattern in `ScheduledJob`

**Source:** `src/hassette/scheduler/classes.py:306-332`

```python
def matches(self, other: "ScheduledJob") -> bool:
    if self.trigger is not None and other.trigger is not None:
        triggers_match = self.trigger.trigger_id() == other.trigger.trigger_id()
    else:
        triggers_match = self.trigger is other.trigger
    return (
        self.job == other.job
        and triggers_match
        and self.group == other.group
        and self.jitter == other.jitter
        and self.timeout == other.timeout
        and self.timeout_disabled == other.timeout_disabled
        and self.args == other.args
        and self.kwargs == other.kwargs
        and self.error_handler is other.error_handler
        and self.mode is other.mode
    )
```

### Registration telemetry construction in `BusService`

**Source:** `src/hassette/core/bus_service.py` (build_registration pattern)

```python
human_description: str | None = None
if listener.predicate is not None:
    human_description = summarize_top_level(listener.predicate)
return ListenerRegistration(
    ...,
    predicate_description=repr(listener.predicate) if listener.predicate else None,
    human_description=human_description,
    ...,
)
```

### Dispatch interception point in `dispatch_and_log()`

**Source:** `src/hassette/core/scheduler_service.py:296-377`

The predicate check inserts between the existing step 1 (compute next occurrence, lines 316-359) and step 2 (run through guard, lines 362-369). This ensures recurring jobs continue their schedule even when skipped.

## Alternatives Considered

### Zero-arg only (no ScheduledJob parameter)

Simpler — predicates are always `() -> bool`. Users who need job context access it via closure over `self`. Rejected because passing the `ScheduledJob` is a low-cost addition that avoids forcing users to capture job references in closures when they want to branch on `args`/`kwargs`.

### Pass `*args, **kwargs` directly to predicate

The predicate receives the same positional and keyword arguments as the job handler. More ergonomic for the args/kwargs case but requires full DI-style argument matching (partial kwargs, missing args). Rejected because the complexity of flexible argument matching outweighs the benefit — users who need `args`/`kwargs` can access them via the `ScheduledJob` parameter (`job.args`, `job.kwargs`).

### Reuse bus `Predicate[EventT]` with synthetic event

Pass a synthetic event object to the predicate to maintain type compatibility with bus predicates. Rejected because scheduler jobs have no meaningful event — the synthetic object would be an empty shell that exists only to satisfy the type signature, adding confusion without value.

### Don't record skipped executions in telemetry

Skip silently (no execution record). Simpler — no CHECK constraint migration, no frontend changes, no query updates. Rejected because the primary motivation is making conditional execution visible — silent skips defeat the purpose.

## Test Strategy

### Existing Tests to Adapt

- `tests/unit/scheduler/test_scheduled_job_lifecycle.py` — extend `ScheduledJob` construction tests to include the `predicate` field
- `tests/unit/scheduler/test_scheduled_job_mark_registered.py` — verify `predicate` doesn't interfere with registration flow
- `tests/integration/test_scheduler.py` — baseline tests that confirm existing behavior is unchanged
- `tests/unit/core/test_scheduler_service_reschedule.py` — verify rescheduling is unaffected by predicate presence
- `tests/unit/test_model_types.py` — update `TestExecutionStatus` expected values to include `'skipped'`

### New Test Coverage

- **Unit: predicate arity detection** — zero-arg, annotated ScheduledJob, unannotated one-arg, wrong annotation, union annotation, `*args` (DependencyInjectionError), async (TypeError), lambda (FR#9, FR#10, FR#16)
- **Unit: `ScheduledJob.matches()` with predicate** — same predicate matches, different predicate doesn't, None vs predicate doesn't (FR#15)
- **Unit: `ScheduledJob.diff_fields()` with predicate** — predicate listed in diffs when changed (FR#15)
- **Integration: recurring job skip** — register with `where=lambda: False`, trigger, verify `'skipped'` record and rescheduling (FR#4, FR#5, FR#6)
- **Integration: one-shot job skip** — register `run_in` with `where=lambda: False`, trigger, verify `'skipped'` record and job removal (FR#7)
- **Integration: predicate exception** — register with a raising predicate, dispatch, verify the job does not run, a `status='error'` record is enqueued, `on_error` is invoked, and the one-shot is removed (FR#8)
- **Integration: predicate receives ScheduledJob** — register with `where=` using a named function with `job: ScheduledJob` annotation, verify correct invocation (FR#9)
- **Integration: `where=` parameter forwarding** — verify `run_in`, `run_every`, `run_daily`, `run_cron` all forward `where=` to `schedule()` (FR#2)
- **Unit: telemetry — `'skipped'` in aggregation queries** — verify `skipped` count in `JobSummary` (FR#13, FR#14)
- **Unit: registration — predicate description persistence** — verify `predicate_description` and `human_description` stored (FR#11)

### Tests to Remove

No tests to remove.

## Documentation Updates

- `docs/pages/core-concepts/scheduler/methods.md` — add `where=` parameter documentation to all method signatures, with usage examples
- `docs/pages/core-concepts/scheduler/index.md` — add a "Conditional Execution" section explaining `where=` with a basic example
- `docs/pages/core-concepts/scheduler/snippets/` — add snippet files for `where=` examples (zero-arg state check, one-arg job inspection)
- Docstrings on `Scheduler.schedule()` and all convenience methods — add `where` parameter description
- Schema regeneration: `uv run python scripts/export_schemas.py --types` after modifying `JobSummary` and `ExecutionStatus` — regenerates `openapi.json`, `ws-schema.json`, `generated-types.ts`, and `ws-types.ts`

## Impact

### Changed Files
<!-- Gap check 2026-07-06: 5 gaps included — repository.py:register_job SQL (T03 Focus), factories.py:make_job_registration (T01 Focus), test_telemetry_models.py + core/test_telemetry_models.py (T04 tests), status.test.ts (T05 tests), web_helpers.py:make_real_job (T03 Focus) -->

- **create** `src/hassette/migrations_sql/009.sql` — add `skipped` to `executions.status` CHECK, add `predicate_description`/`human_description` to `scheduled_jobs`
- **modify** `src/hassette/scheduler/classes.py` — add `predicate` and `_predicate_wants_job` fields, extend `matches()`/`diff_fields()`
- **modify** `src/hassette/scheduler/scheduler.py` — add `where=` parameter to `schedule()` and all convenience methods, predicate normalization and arity inspection
- **modify** `src/hassette/core/scheduler_service.py` — predicate evaluation in `dispatch_and_log()`, `_record_skipped()` helper, predicate description in `add_job()`
- **modify** `src/hassette/core/registration.py` — add `predicate_description`/`human_description` to `ScheduledJobRegistration`
- **modify** `src/hassette/types/types.py` — add `SKIPPED` to `ExecutionStatus` StrEnum, add `SchedulerPredicate` type alias
- **modify** `src/hassette/core/telemetry/registration_queries.py` — add `skipped` bucket to job summary query
- **modify** `src/hassette/core/telemetry/summary_queries.py` — exclude `status = 'skipped'` from `AVG`/`MIN`/`MAX` duration aggregations to prevent zero-duration skip records from diluting metrics
- **modify** `src/hassette/schemas/telemetry_models.py` — add `skipped` field to `JobSummary`, `predicate_description`/`human_description` fields
- **read** `src/hassette/web/routes/scheduler.py` — verify routes use `JobSummary` directly as `response_model` (no separate web model to update)
- **modify** `frontend/src/utils/status.ts` — map `'skipped'` to `StatusKind` `"mute"`
- **modify** `frontend/src/components/app-detail/job-detail.tsx` — add `Skipped` cell to stats grid, display predicate description
- **modify** `docs/pages/core-concepts/scheduler/methods.md` — add `where=` parameter docs
- **modify** `docs/pages/core-concepts/scheduler/index.md` — add "Conditional Execution" section
- **create** `docs/pages/core-concepts/scheduler/snippets/scheduler_where_*.py` — snippet files for `where=` examples

### Behavioral Invariants

- All existing scheduler tests must continue to pass unchanged (no `where=` means no predicate, which means unconditional execution — the default)
- The existing `total_executions = successful + failed + cancelled + timed_out` invariant extends to include `+ skipped`
- `if_exists="skip"` collision detection must remain correct with the additional `predicate` comparison field
- Bus `where=` behavior is unchanged

### Blast Radius

- **Telemetry pipeline:** every status-aggregation query must account for `'skipped'` — missing one silently miscounts
- **Frontend:** the `ExecutionStatus` TypeScript type is auto-regenerated; components that switch on status values (beyond `executionStatusKind()`) must handle the new value
- **Migration:** the `executions` table recreation touches every row in potentially the largest table; tested with realistic data volumes

## Open Questions

(None — all design decisions resolved during discovery.)
