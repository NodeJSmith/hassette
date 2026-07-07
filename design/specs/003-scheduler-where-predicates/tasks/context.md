# Context: Scheduler `where=` Predicate Support

## Problem & Motivation
Scheduler jobs execute unconditionally when their trigger fires. Developers who want conditional execution must write guard clauses at the top of every job callback — a pattern that is invisible to telemetry (a silently-returning handler looks like a successful execution), repeats the same boilerplate, and buries conditional intent inside the handler rather than at the registration site. The bus already has `where=` on every subscription method with normalization, summarization, and telemetry. This feature extends the same pattern to the scheduler.

## Visual Artifacts
None.

## Key Decisions
1. **Scheduler predicates use a new `SchedulerPredicate` type alias** (`Callable[[], bool] | Callable[[ScheduledJob], bool]`), distinct from the bus's `Predicate[EventT]` protocol which requires exactly one event argument. Zero-arg is the common case (state checks); one-arg receives `ScheduledJob` for metadata access.
2. **Sequences collapse into a closure** at registration time (`lambda: all(p() for p in preds)`). No combinator class — the bus's `AllOf` is typed for `Predicate[EventT]` and cannot be reused. This leaves the door open for future composable predicate classes with `__and__`/`__or__`.
3. **Fail-open on predicate exceptions** — a broken predicate logs a warning and the job runs. Missed actions are worse than extra actions for home automation.
4. **One-shot jobs are consumed even when skipped** — the developer chose to gate it; the skip is deliberate.
5. **Predicate arity is annotation-based**, detected via the shared `get_typed_signature()` / `find_parameter_by_type()` utilities. A positional parameter annotated as `ScheduledJob` triggers one-arg dispatch; unannotated predicates dispatch as zero-arg. Result stored as `_predicate_wants_job: bool` on `ScheduledJob`.
6. **Skipped executions are recorded in telemetry** with `status='skipped'` and `duration_ms=0.0`, bypassing `_execute()`/`track_execution()` entirely. Visible in the web UI.
7. **The predicate check inserts in `dispatch_and_log()`** between step 1 (compute next occurrence) and step 2 (run through guard). This ensures recurring jobs continue their schedule even when skipped.
8. **Scheduler summarization calls `callable_stable_name()` directly** with `hasattr` fallback to `summarize()`, rather than reusing the bus's `summarize_top_level()` (which is typed for `Predicate[EventT]`).
9. **The `executions.status` CHECK constraint modification requires SQLite table recreation** — CREATE new, INSERT...SELECT, DROP old, RENAME.
10. **Manual trigger ("Run Now") intentionally bypasses predicates.** The `trigger_job()` path calls `run_job_with_guard()` directly, not `dispatch_and_log()`. Since the predicate check lives in `dispatch_and_log()`, manual triggers always fire regardless of `where=`. This is deliberate — "Run Now" is an explicit operator action.

## Constraints & Anti-Patterns
- Do NOT reuse the bus's `AllOf`, `normalize_where()`, `summarize_top_level()`, or `_summarize_predicate()` for scheduler predicates — they are all typed for `Predicate[EventT]` (one-arg) and will fail pyright with zero-arg callables.
- Do NOT go through `CommandExecutor._execute()` / `track_execution()` for skipped executions — build an `ExecutionRecord` directly and enqueue via `enqueue_record()`.
- Do NOT add `is_skipped` to `ExecutionResult` — the skip path never constructs one.
- The `executions` table recreation must preserve all indexes and the mutual-exclusivity CHECK constraint (`(listener_id IS NOT NULL) + (job_id IS NOT NULL) = 1`).
- Duration aggregation queries (`AVG`/`MIN`/`MAX`) must exclude `status = 'skipped'` to avoid zero-duration records diluting metrics.

## Design Doc References
- `## Problem` — the user-facing pain (invisible guards, boilerplate, buried intent)
- `## Architecture > Predicate storage` — `SchedulerPredicate` type alias, `ScheduledJob.predicate` field, closure normalization
- `## Architecture > Predicate arity detection` — annotation-based via shared `type_utils` utilities, `_predicate_wants_job` flag
- `## Architecture > Predicate evaluation` — `dispatch_and_log()` interception, `_record_skipped()`, fail-open exception handling
- `## Architecture > Predicate summarization` — `callable_stable_name()` directly, `hasattr` fallback to `summarize()`
- `## Architecture > Registration telemetry` — `predicate_description`/`human_description` on `ScheduledJobRegistration`
- `## Architecture > Database migration (009.sql)` — scheduled_jobs columns, executions CHECK constraint recreation
- `## Architecture > SQL query updates` — `get_job_summary()` skipped bucket + predicate columns, `get_app_health_aggregates()` duration exclusion
- `## Architecture > Collision detection` — `matches()`/`diff_fields()` predicate comparison
- `## Architecture > Frontend changes` — status mapping, stats grid, predicate display
- `## Convention Examples` — `Listener.create()`, `Listener.matches()`, `ScheduledJob.matches()`, `BusService.build_registration()`, `dispatch_and_log()` interception point

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

The scheduler cannot reuse `normalize_where()` or `AllOf` directly (both are typed for the bus `Predicate[EventT]` protocol), but follows the same single-entry-point pattern: normalize once at registration, store the result, never re-normalize at dispatch. Sequences collapse into a closure rather than using a combinator class.

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
