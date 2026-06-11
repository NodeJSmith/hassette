# Design: `if_exists` for bus handler registration

**Date:** 2026-06-11
**Status:** approved
**Scope-mode:** hold

## Problem

The scheduler lets an app conditionally register or hot-swap a named job through
`if_exists="error" | "skip" | "replace"`. `error` (default) raises on a name clash,
`skip` returns the already-registered job when its config matches, and `replace`
cancels the existing job and registers a new one in its place. This makes two common
patterns trivial: idempotent registration (re-running `on_initialize` without
double-registering) and hot-swapping a handler under a stable name.

The bus has no equivalent. A name clash always raises `DuplicateListenerError`, so an
app that wants to replace or idempotently re-register a listener must manually find and
cancel the old subscription first. The `name=` parameter only disambiguates the natural
key; it does not unlock skip/replace semantics the way it does in the scheduler. Two
peer subsystems that solve the same registration problem expose different APIs for it,
which is the asymmetry this change removes.

A second problem surfaces from the same area, with two halves. once-listeners
(`once=True`) are exempt from in-memory collision tracking (`register_and_check_collision`
returns early for them), so two once-listeners with the same name and topic coexist in
memory and never raise. Separately, the listener table has no durable cancellation marker:
cancelling a listener writes nothing to the database, unlike the scheduler, whose
`cancel_job` records `cancelled_at`. So the bus cannot record a replaced or cancelled
listener's removal at all. Both halves are closed here.

## Goals

- The bus exposes `if_exists="error" | "skip" | "replace"` on every public registration
  method (including `add_listener`), with `"error"` as the default (preserving current
  behavior).
- `skip` and `replace` behave as the scheduler's do, including drift detection on `skip`
  and the same row-preserving telemetry semantics on `replace`.
- once-listeners participate in collision tracking like every other listener, with their
  in-memory key released and their cancellation recorded in the database when they fire.
- Cancelling a listener (via `Subscription.cancel`, `replace`, or a once-listener firing)
  records `cancelled_at` durably, mirroring the scheduler's `cancel_job`; re-registration
  under the same natural key clears it.
- The bus and scheduler `if_exists` APIs read as deliberately symmetric: same parameter
  name, same literal values, same semantics — with the two structural differences documented,
  not hidden: (1) the bus keys per `(name, topic)` while the scheduler keys per `name`; (2) on
  the `if_exists="error"` clash the bus raises its existing `DuplicateListenerError` (with
  `.name`/`.topic`/handler attributes) while the scheduler raises a plain `ValueError`. The
  skip-drift error is `ValueError` in both.

## Non-Goals

- `replace` does not produce a new `db_id`. The natural-key row is the stable identity
  (it persists across restarts for FK preservation); `replace` updates it in place, exactly
  as the scheduler does. A fresh id is neither offered by the scheduler nor wanted here.
- No change to the natural key itself `(app_key, instance_index, name, topic)` or to the
  scheduler.

## User Scenarios

### App author: building a Hassette automation
- **Goal:** register bus listeners without manual cancel-then-register bookkeeping
- **Context:** writing an app's `on_initialize`, or reacting to a config change that
  rebuilds handlers

#### Idempotent registration (`skip`)

1. **Re-run `on_initialize` (e.g. after a reload) and re-register the same listener**
   - Sees: registration succeeds and returns a subscription, with no
     `DuplicateListenerError`
   - Decides: nothing — the call is safe to repeat
   - Then: the existing listener is returned unchanged; no second listener is created

2. **Re-register under the same name but with a changed filter or handler**
   - Sees: a `ValueError` naming which configuration fields differ
   - Decides: whether the drift is intentional (switch to `replace`) or a bug
   - Then: registration is rejected so the divergence cannot pass silently

#### Hot-swap a handler (`replace`)

1. **Register a new handler under a name already in use, with `if_exists="replace"`**
   - Sees: a subscription for the new listener
   - Decides: nothing
   - Then: the previous listener is cancelled and removed from routing (its removal recorded
     via `cancelled_at`); the new listener occupies the same natural-key row, with
     `cancelled_at` cleared

### App author: registering a one-shot listener
- **Goal:** register a `once=True` listener and trust name uniqueness
- **Context:** a fire-once reaction to the next matching event

#### One-shot name collision

1. **Register two `once=True` listeners with the same name and topic**
   - Sees: the second registration raises `DuplicateListenerError` (or is resolved by
     `if_exists`, identical to durable listeners)
   - Decides: pick a distinct name, or choose explicit `if_exists` behavior
   - Then: in-memory and DB state agree — one live listener per `(name, topic)`

## Functional Requirements

- **FR#1** Every public bus registration method — `on()`, `on_state_change`,
  `on_attribute_change`, the `**opts` event-specific methods, and `add_listener` — accepts
  `if_exists` with values `"error"`, `"skip"`, `"replace"`, defaulting to `"error"`.
- **FR#2** `if_exists="error"` preserves current behavior: a same-session clash on the
  natural key raises `DuplicateListenerError`.
- **FR#3** `if_exists="skip"` returns a subscription to the existing listener when the
  new registration's logical configuration matches the existing one, and does not
  register a second listener.
- **FR#4** `if_exists="skip"` raises `ValueError` when a listener with the same natural
  key exists but its logical configuration differs; the error names the differing fields.
- **FR#5** `if_exists="replace"` cancels the existing listener (recording its removal via
  `cancelled_at`) and registers the new listener on the same natural-key row, returning a
  subscription to the new listener. The row's `db_id` is preserved; the re-registration
  upsert clears `cancelled_at`.
- **FR#6** once-listeners participate in collision tracking identically to durable
  listeners: a same-session natural-key clash is detected, and `if_exists` resolves it
  with the same semantics.
- **FR#7** When a once-listener fires and is auto-removed, its natural key is released
  from in-memory collision tracking and its `cancelled_at` is recorded in the database, so
  a later registration under the same key is a fresh registration and does not spuriously
  clash.
- **FR#8** Two listeners count as a logical-configuration match when they share handler
  callable, filter predicate, timing options (`once`, `debounce`, `throttle`, `timeout`,
  `timeout_disabled`), handler kwargs, per-registration error handler, and duration
  configuration; runtime state (`listener_id`, `db_id`, cancellation flag, attached
  timer) is excluded from the comparison.
- **FR#9** Cancelling a listener through any path (`Subscription.cancel` →
  `Bus.remove_listener`, `replace`'s cancel-old step, or a once-listener firing) writes
  `cancelled_at` to its database row. Re-registration under the same natural key clears it.
- **FR#10** `add_listener` returns a `Subscription`. With `if_exists="skip"` and a matching
  existing listener, it returns a subscription to the existing listener rather than `None`.
- **FR#11** The generated synchronous facade (`bus/sync.py`) exposes `if_exists` on the
  same methods with identical defaults and semantics, and passes the codegen drift check.

## Edge Cases

- **Listener using a custom callable filter or lambda condition under `skip`.** Lambdas
  and closures compare by identity, so re-registering "the same" listener built from a
  fresh lambda reports a drift and raises under `skip`. This matches the scheduler's own
  limitation (it compares `job` and `error_handler` by identity). The same applies to a
  callable `hold_predicate` on a duration listener. Documented as a known constraint; the
  path forward is `replace`, or a non-lambda predicate.
- **Non-atomic `replace`.** `replace` cancels the old listener (route removal +
  `cancelled_at` write) before registering the new one, because the unique natural key
  forbids two live listeners under one key. If the new registration's DB write fails after
  the old listener is gone, the app is left with no listener under that name and matching
  events drop. This window is structural and identical to the scheduler's `replace`
  (`cancel_job` then `await add_job`). It is logged at the cancel and register steps so an
  operator can see the gap; a future improvement could stage the new registration before
  retiring the old, but that is out of scope.
- **Concurrent `skip` during a once-listener's dispatch.** While a once-listener's async
  handler runs, its in-memory key is still present (cleanup runs in the dispatch `finally`).
  A concurrent `skip` could match and return a subscription to a listener that is about to
  be auto-removed. The returned subscription then refers to a cancelled listener. Documented;
  the consequence is a no-op subscription, not corruption.
- **`replace` when no existing listener is present.** Behaves as a normal registration —
  there is nothing to cancel.
- **`skip` returning a subscription whose `cancel()` removes the existing listener.** The
  returned subscription wraps the existing listener; cancelling it removes that listener,
  consistent with the subscription the original registration returned. `Bus.remove_listener`
  and the once-fire cleanup are idempotent, so a redundant removal is a harmless no-op.
- **`replace`/`skip` across different topics sharing a name.** The natural key includes
  `topic`, so `if_exists` resolves per `(name, topic)`. The same name on a different topic
  is a different listener and does not collide — unlike the scheduler, which keys on name
  alone. This difference is documented (see Documentation Updates).

## Acceptance Criteria

- **AC#1** Calling any registration method with `if_exists="skip"` twice with identical
  arguments returns a subscription both times and leaves exactly one listener registered.
  (FR#1, FR#3)
- **AC#2** Calling with `if_exists="skip"` after registering under the same name+topic
  but with a different handler or filter raises `ValueError` whose message lists the
  changed fields. (FR#4, FR#8)
- **AC#3** Calling with `if_exists="replace"` under an existing name+topic leaves exactly
  one live listener — the new one — routed; the old listener is no longer routed; and the
  natural-key row's `db_id` is unchanged (preserved, not regenerated) with `cancelled_at`
  cleared after the re-registration. (FR#5, FR#9)
- **AC#4** Calling with `if_exists="error"` (or omitting it) under an existing name+topic
  raises `DuplicateListenerError`, unchanged from today. (FR#2)
- **AC#5** Registering two `once=True` listeners with the same name+topic and default
  `if_exists` raises `DuplicateListenerError`. (FR#6)
- **AC#6** After a `once=True` listener fires, registering a new listener under the same
  name+topic succeeds without raising. (FR#7)
- **AC#7** Cancelling a listener via `Subscription.cancel()` without re-registering sets
  `cancelled_at` on its database row. (FR#9)
- **AC#8** When a `once=True` listener fires, its database row has `cancelled_at` set.
  (FR#7, FR#9)
- **AC#9** `add_listener` returns a `Subscription`; with `if_exists="skip"` and a matching
  existing listener it returns a subscription to the existing listener. (FR#10)
- **AC#10** The regenerated `bus/sync.py` passes the sync-facade drift check
  (`hassette-codegen sync-facade --check`) and exposes `if_exists` on the same methods.
  (FR#11)

## Key Constraints

- **Do not pursue scheduler→bus symmetry by removing one-shot tracking from the
  scheduler.** That would regress `run_in(..., if_exists="replace")` — the pending-timeout
  replace idiom the motion-light recipe relies on. Parity is achieved by bringing the bus
  up to the scheduler, never by reducing the scheduler.
- **Do not hand-edit `bus/sync.py`.** It is generated from `Bus` by
  `codegen/src/hassette_codegen/sync_facade/`. Changes to the async `Bus` signatures flow
  to the facade through regeneration.
- **Keep the collision-resolution method private (`_`-prefixed).** The sync-facade codegen
  skips methods beginning with `_` (`sync_facade/ast_utils.py`). Reshaping
  `register_and_check_collision` must keep it underscore-prefixed so the generator does not
  expose it on the facade.
- **`skip` must not silently no-op on drift.** A configuration mismatch raises; it never
  returns the stale listener while discarding the new arguments.
- **`replace` must preserve the natural-key row id.** No fresh `db_id`, no DELETE+INSERT —
  the upsert's `DO UPDATE` path is the parity behavior; `cancelled_at` is a marker, not a
  trigger to recreate the row.
- **Do not introduce a separate `if_exists` value or branch for once-listeners.** Once
  they are tracked (Direction A), they flow through the identical resolution path.

## Dependencies and Assumptions

- Assumes the natural key `(app_key, instance_index, name, topic)` remains the collision
  and DB upsert key (unchanged by this work).
- Assumes `BusService` is the component that auto-removes a once-listener after it fires
  (`bus_service.py:350`, dispatch `finally`) and is the natural place to invoke a fire-time
  removal callback and the `cancelled_at` write.
- Assumes the telemetry DB is disposable across schema bumps: `database_service.py:451`
  deletes and recreates a DB whose version is below head, so a column-adding migration needs
  no in-place data migration.
- Depends on the `hassette-codegen sync-facade` tooling, already wired into the repo and CI
  drift checks.

## Architecture

### Threading `if_exists` through the registration surface

`if_exists` is added to the `Options` TypedDict (`bus/options.py`). Every event-specific
method (`on_state_change`, `on_attribute_change`, `on_call_service`, `on_component_loaded`,
`on_service_registered`, the `on_homeassistant_*`, `on_hassette_service_*`,
`on_websocket_*`, `on_app_*` shorthands) accepts `**opts: Unpack[Options]` and forwards
`**opts` through `_subscribe` into `_on_internal`, so the single TypedDict key gives them
all `if_exists` with full type safety and no per-method signature churn.

`on()` has an explicit signature (no `**opts`), so it gains an explicit `if_exists`
parameter forwarded to `_on_internal`. `_on_internal` gains an explicit `if_exists`
parameter — it is the funnel where the collision decision is made. `add_listener` (the
external pre-built-`Listener` entry point, the bus analogue of `Scheduler.add_job`) gains
an explicit `if_exists` parameter and is changed to return a `Subscription` (FR#10), for
parity with `add_job` returning the job.

### Collision resolution

Today `register_and_check_collision` (bus.py:198) is error-only and exempts
once-listeners. It is reshaped into the single decision point — kept private and
`_`-prefixed (e.g. `_resolve_collision`) so the codegen ignores it — that both
`_on_internal` and `add_listener` call, modeled on the collision block inside
`Scheduler.add_job` (the `if existing is not None:` branch at scheduler.py:201–218; `add_job`
itself begins at scheduler.py:169):

- Compute the natural key. Look up the existing listener.
- No existing listener → register the key and proceed.
- Existing + `if_exists="error"` → raise `DuplicateListenerError` (unchanged).
- Existing + `if_exists="replace"` → cancel/remove the existing listener (route removal +
  `cancelled_at` write), then register the new one in its place.
- Existing + `if_exists="skip"` and configs match → short-circuit: the caller returns a
  subscription to the existing listener without registering the new one.
- Existing + `if_exists="skip"` and configs differ → raise `ValueError` listing changed
  fields.

The helper returns the existing listener (skip short-circuit) or `None` (proceed). Both
`_on_internal` and `add_listener` shape the skip return as a `Subscription` wrapping the
existing listener. The new listener's key is registered only on the proceed path (and after
the old one is cancelled, on `replace`).

### Storing the listener, not just its name

`_registered_handler_names: dict[tuple[str, int, str, str], str]` (bus.py:142) currently
stores the handler-name string — enough for the `error`-only duplicate message, but `skip`
(return the existing subscription) and `replace` (cancel the existing listener) need the
`Listener` object itself. The map's value type changes from `str` to `Listener`, and it
is renamed `_registered_listeners`. (The key tuple `(app_key, instance_index, name, topic)`
has no named alias today; introducing a `NaturalKey` alias is optional and not required by
this change.) The duplicate-error message derives the handler name from
`listener.identity.handler_name`, so no information is lost.

### Logical-configuration comparison

`Listener` gains `config_matches(other) -> bool` and `diff_fields(other) -> list[str]`,
modeled field-for-field on `ScheduledJob.matches`/`diff_fields` (classes.py:268 and :295).
The bus method is named `config_matches`, **not** `matches`, because `Listener.matches`
already exists (bus/listeners.py:360) — it is the event-predicate dispatch method called on
every routing pass and must not be shadowed. They compare
the logical configuration — handler callable (`invoker.orig_handler`), filter
(`predicate`, value-comparable because built-in predicates are frozen dataclasses), timing
options (`once`, `debounce`, `throttle`, `timeout`, `timeout_disabled`), handler
(`invoker.kwargs`), per-registration error handler (`invoker.error_handler`, by identity),
and duration configuration (`entity_id`, `duration`, `immediate`, `is_attribute_listener`,
`hold_predicate`). Runtime state (`listener_id`, `db_id`, `_cancelled`, the attached
`DurationTimer`) is excluded, exactly as the scheduler excludes its runtime fields.

### Durable cancellation marker (`cancelled_at`)

To record a replaced or cancelled listener's removal (FR#9), the bus mirrors the
scheduler's `cancelled_at` mechanism exactly:

- A new migration `002.sql` adds a nullable `cancelled_at REAL` column to `listeners`,
  matching `scheduled_jobs` (001.sql:72). Because `database_service.py` recreates any DB
  below head version, no in-place data migration is needed (see Migration).
- The listener upsert (`telemetry_repository.register_listener`, telemetry_repository.py:300)
  gains `cancelled_at = NULL` in its `DO UPDATE` clause, mirroring the job upsert
  (telemetry_repository.py:376) — re-registration clears cancellation and preserves the row
  id.
- A new `mark_listener_cancelled(db_id)` on `TelemetryRepository` mirrors `mark_job_cancelled`
  (telemetry_repository.py:403), threaded through `CommandExecutor` and exposed on
  `BusService` the same way `SchedulerService.mark_job_cancelled` (scheduler_service.py:462)
  delegates to the executor.
- The bus cancel path spawns `mark_listener_cancelled` for a listener with a `db_id`,
  mirroring how `Scheduler.cancel_job` (scheduler.py:257–264) spawns `mark_job_cancelled` on
  the service's task bucket so the write survives resource shutdown. This covers all three
  cancel sources: `Subscription.cancel` → `Bus.remove_listener`, `replace`'s cancel-old, and
  the once-fire removal.

### Tracking once-listeners and fire-time cleanup (Direction A)

The `if listener.options.once: return` exemption in the collision check is removed, so
once-listeners register their natural key like any other listener. This requires that the
key be released — and `cancelled_at` written — when a once-listener fires and is
auto-removed; otherwise a stale key would block future registration.

`BusService.remove_listener` (bus_service.py:187), invoked from the dispatch `finally`
block when a once-listener fires (bus_service.py:350), tears the listener out of routing
but does not touch the per-owner `Bus._registered_listeners`. A fire-time removal-callback
registry is added to `BusService`, mirroring the scheduler's
`register_removal_callback`/`_on_job_removed`/`deregister_removal_callback`
(scheduler.py:119–141, scheduler_service.py): `Bus` registers a callback keyed by `owner_id`
in its constructor and **deregisters it in `Bus.on_shutdown`** (bus.py:152, which today lacks
this — see Impact); when `BusService` removes a listener it invokes the owner's callback,
which pops the natural key from `_registered_listeners` and spawns the `cancelled_at` write.
The registry guards a missing/replaced callback the way the scheduler's does (it tolerates
re-registration during hot-reload), so a stale once-fire after the owning `Bus` is gone is a
no-op, not a crash. `Bus.remove_listener` already pops the key directly, so the callback
closes only the once-fire path; a redundant pop is a harmless no-op.

### Sync facade

After the async `Bus` signatures change, `bus/sync.py` is regenerated with
`uv run hassette-codegen sync-facade`. The CI drift gate
(`hassette-codegen sync-facade --check`) verifies it is current.

## Replacement Targets

- **`Bus._registered_handler_names: dict[NaturalKey, str]` → `_registered_listeners:
  dict[NaturalKey, Listener]`** (bus.py:142). The string value cannot support `skip`/
  `replace`; it is superseded by storing the `Listener`. The old field name is removed,
  not aliased.
- **The `if listener.options.once: return` exemption in the collision check** (bus.py:204).
  Removed outright — once-listeners are tracked under Direction A. Replaced by the
  fire-time removal callback; not kept alongside it.
- **`Bus.add_listener` return type `None`** (bus.py:181) → `Subscription`. The void return
  cannot support `skip`'s return-the-existing contract. Callers that ignore the return are
  unaffected (widening `None` → `Subscription` is non-breaking); the implementer confirms no
  caller is typed as expecting `None`.
- **`bus/sync.py`** is regenerated, not edited. Its current content is superseded by the
  generator output.

## Migration

The schema is versioned with SQLite's native `PRAGMA user_version` (this replaced Alembic;
see `migration_runner.py` — "PRAGMA user_version migration runner. Replaces Alembic"). It is
not an ORM/incremental-state migration system. The mechanics:

- Numbered `.sql` files in `src/hassette/migrations_sql/` (today only `001.sql`). The head
  version is the highest numeric filename stem (`_get_expected_head_version`,
  database_service.py:431).
- The runner (`run_migrations`, migration_runner.py:20) applies each file whose version is
  `> PRAGMA user_version`, in order, each inside `BEGIN IMMEDIATE ... PRAGMA user_version = N
  ... COMMIT` (crash-safe atomic).
- On startup, `_handle_schema_version` (database_service.py:446) compares the DB's
  `user_version` to head: below head → **delete the DB file** and recreate (telemetry is
  disposable, no data to preserve); above head → refuse and raise `SchemaVersionError`.

This change adds **`src/hassette/migrations_sql/002.sql`**:

```sql
ALTER TABLE listeners ADD COLUMN cancelled_at REAL;
```

Adding a new numbered file is the **only** way to bump the head version — editing `001.sql`
in place would leave head at 1, so an existing v1 DB would never be flagged stale and would
never gain the column. With `002.sql` present, head becomes 2. The runner never alters a
populated table in place: a v1 DB is *deleted* first, then rebuilt by running `001.sql`
(creates the `listeners` table without the column) followed by `002.sql` (the `ADD COLUMN`
runs against that just-created, empty table). A fresh install does the same. So the `ALTER` is
a one-line delta applied to a freshly created table every time — there is no data to migrate.
Adding the column directly to `001.sql`'s `CREATE TABLE` would also work but would not bump
the version on its own; the separate `002.sql` is what makes existing DBs recreate.

**Reversibility:** rolling back the code lowers head to 1; a DB at version 2 is then *ahead*
of head and raises `SchemaVersionError` (database_service.py:489) — the existing
newer-DB-on-older-binary behavior, recovered by manual DB removal. Consistent with every
prior schema change in this repo.

If the active-listener views or restart reconciliation must exclude cancelled rows, mirror
whatever `scheduled_jobs` does for `cancelled_at` (the existing active views filter only
`retired_at IS NULL`, 001.sql:145; reconciliation handles `cancelled_at` in code). The
implementer confirms parity against the scheduler's reconciliation path.

## Convention Examples

### Scheduler `if_exists` resolution — the canonical error/skip/replace shape

**Source:** `src/hassette/scheduler/scheduler.py`

```python
existing = self._jobs_by_name.get(job.name)
if existing is not None:
    if if_exists == "replace":
        self.logger.debug("Replacing existing job '%s' (cancelling old, registering new)", job.name)
        self.cancel_job(existing)
    elif if_exists == "skip" and existing.matches(job):
        return existing
    elif if_exists == "skip":
        changed_fields = existing.diff_fields(job)
        raise ValueError(
            f"A job named '{job.name}' already exists but its configuration has changed "
            f"(changed fields: {', '.join(changed_fields)})"
        )
    else:
        raise ValueError(
            f"A job named '{job.name}' already exists in scheduler for '{self.owner_id}'. "
            "Job names must be unique per scheduler instance."
        )
```

### `ScheduledJob.matches` / `diff_fields` — the logical-config comparison to mirror

**Source:** `src/hassette/scheduler/classes.py`

```python
def matches(self, other: "ScheduledJob") -> bool:
    """Check whether two jobs represent the same logical configuration.

    Compares callable, trigger (by trigger_id()), group, jitter, timeout,
    timeout_disabled, args, kwargs, and error_handler (by identity).
    Does not compare runtime state (db_id, next_run, sort_index, _scheduler, ...).
    """
    ...
    return (
        self.job == other.job
        and triggers_match
        and self.group == other.group
        # ... one field per comparison ...
        and self.error_handler is other.error_handler
    )
```

### Durable cancellation — `cancelled_at` write + upsert clear (the mechanism to mirror)

**Source:** `src/hassette/core/telemetry_repository.py`

```python
# register_job upsert clears cancellation on re-registration (mirror for listeners):
ON CONFLICT(app_key, instance_index, job_name)
DO UPDATE SET
    ...
    retired_at = NULL,
    cancelled_at = NULL  -- re-registration clears cancellation
RETURNING id

# mark_job_cancelled writes the marker (mirror as mark_listener_cancelled):
async def mark_job_cancelled(self, db_id: int) -> None:
    await db.execute(
        "UPDATE scheduled_jobs SET cancelled_at = :cancelled_at WHERE id = :id",
        {"cancelled_at": time.time(), "id": db_id},
    )
    await db.commit()
```

### Scheduler fire-time removal callback — the cleanup pattern for once-listeners

**Source:** `src/hassette/scheduler/scheduler.py`

```python
# In __init__: register a removal callback keyed by owner
self.scheduler_service.register_removal_callback(self.owner_id, self._on_job_removed)

def _on_job_removed(self, job: "ScheduledJob") -> None:
    """Keep _jobs_by_name/_jobs_by_group in sync when the service removes a job."""
    self._jobs_by_name.pop(job.name, None)
    ...

# In on_shutdown:
self.scheduler_service.deregister_removal_callback(self.owner_id)
```

## Alternatives Considered

- **Keep once-listeners exempt; raise on `once=True` + non-default `if_exists`
  (Direction B).** Smaller change, no fire-time cleanup hook, no behavior change for
  existing once-listener users. Rejected because it preserves the exact asymmetry this
  issue targets and leaves the in-memory/DB inconsistency intact.
- **Make the scheduler stop tracking one-shot jobs (Direction C).** Achieves symmetry by
  reducing the scheduler to the bus's leniency. Rejected: it regresses
  `run_in(..., if_exists="replace")`, the pending-timeout replace idiom the motion-light
  recipe depends on, on a released subsystem.
- **Reframe `replace`/once around the existing model without adding `cancelled_at`** (no
  removal-write mechanism). `replace` would update the row in place with no cancellation
  record, and a cancelled listener would leave no durable trace. Rejected in favor of true
  telemetry parity: cancelling a job records `cancelled_at`, and the bus should match so a
  replaced/cancelled listener is observable in telemetry rather than vanishing silently.
- **Give `replace` a fresh `db_id` (DELETE+INSERT or partial unique index).** Rejected: the
  scheduler preserves the row id across replace for FK preservation
  (telemetry_repository.py:264); a fresh id would diverge from the scheduler and orphan
  `executions` rows that reference the listener.
- **Restrict `if_exists` to the three methods named in the issue.** Rejected: the `Options`
  TypedDict path gives uniform coverage for free, and the scheduler exposes `if_exists` on
  every scheduling method.

## Test Strategy

### Existing Tests to Adapt

- `tests/unit/bus/test_t03_registration_errors.py` — tests and asserts the old
  once-listener exempt behavior (test_t03_registration_errors.py:125). Update to assert the
  new once-listener collision behavior (FR#6); keep the default-`error` cases green.
- `src/hassette/test_utils/helpers.py` — `wire_up_app_state_listener` (def at
  test_utils/helpers.py:415; `once=True` at :430) registers a once-listener with a
  deterministic name. `tests/.../test_hot_reload.py` calls the `wire_up_app_running_listener`
  shorthand twice with the same `app_key`+`RUNNING` (and same topic/name) in **at least four**
  test methods (lines 123/141, 159/177, 259/275, 299/316). Under Direction A every second call
  raises `DuplicateListenerError` — today they pass only by dispatch ordering. Adapt the
  helper to register with `if_exists="replace"` (or make the name unique per call) so all four
  keep passing for the right reason.
- `tests/unit/bus/test_bus.py`, `tests/unit/bus/test_registration_parity.py` — verify
  nothing relies on the once-exemption; extend parity coverage for `if_exists`.
- `tests/integration/test_sync_facades.py`, `tests/unit/test_recording_sync_facade*.py`,
  `tests/unit/tools/test_generate_sync_facade.py` — regenerate and confirm green.
- `tests/unit/bus/test_listeners.py` — home for the new `Listener.config_matches`/`diff_fields`
  unit tests.

### New Test Coverage

- `if_exists="skip"` idempotent re-registration returns a subscription, one listener (FR#3,
  AC#1).
- `if_exists="skip"` with drift raises `ValueError` naming changed fields (FR#4, AC#2).
- `if_exists="replace"` leaves one routed listener with the same `db_id`, old unrouted,
  `cancelled_at` cleared (FR#5, AC#3).
- `if_exists="error"`/default still raises `DuplicateListenerError` (FR#2, AC#4).
- once-listener name+topic collision raises (FR#6, AC#5); key released and `cancelled_at`
  set after fire, re-registration succeeds (FR#7, AC#6, AC#8).
- `Subscription.cancel()` writes `cancelled_at` (FR#9, AC#7).
- `Listener.config_matches`/`diff_fields`: same-config match, per-field drift, runtime fields
  ignored (FR#8) — mirror `tests/unit/test_scheduler_job_names.py`.
- `add_listener` returns a `Subscription`, including the skip-returns-existing case (FR#10,
  AC#9).
- `if_exists` reaches representative `**opts` methods (`on_call_service`) and `on()` (FR#1).
- Regenerated sync facade passes the drift check and exposes `if_exists` (FR#11, AC#10).
- Non-atomic `replace` failure path: a forced DB-registration failure after cancel leaves no
  listener and is logged (Edge Cases).

### Tests to Remove

No tests to remove. Tests asserting the old once-exempt behavior are adapted, not deleted.

## Documentation Updates

- `docs/pages/core-concepts/bus/methods.md` — add `if_exists` to the "Shared Parameters"
  table and the "Registration" section, mirroring the scheduler's `methods.md`. Explicitly
  contrast the key shapes: the scheduler resolves `if_exists` per **name**, the bus per
  **(name, topic)** — the same name on a different topic does not collide.
- A new tested snippet under `docs/pages/core-concepts/bus/snippets/` showing idempotent
  registration and replace, mirroring
  `scheduler/snippets/scheduler_idempotent_registration.py`.
- Docstrings on `on()`, `_on_internal`, `add_listener`, and the `Options` key documenting
  `if_exists`, matching the scheduler's `add_job`/`schedule` docstrings.
- `docs/pages/migration/bus.md` — document the once-listener collision behavior change
  (same name+topic once-listeners now raise) as a migration item.
- `cancelled_at` is an internal telemetry column — no user-facing doc beyond the migration
  note that the telemetry DB is recreated on the schema bump (consistent with prior bumps).
- **CHANGELOG / PR:** this is `feat!` with a `BREAKING CHANGE:` footer. The once-collision
  change breaks a documented, tested contract (test_t03_registration_errors.py:125) and the
  framework's own test utility (test_utils/helpers.py:430), so the breaking flag is required,
  not optional. The footer states: same name+topic `once=True` listeners now raise
  `DuplicateListenerError` (previously silent); use distinct names or `if_exists`.

## Impact

### Changed Files

- `src/hassette/migrations_sql/002.sql` — **new**; adds `cancelled_at` to `listeners`
  (highest-risk: schema bump that recreates existing telemetry DBs).
- `src/hassette/core/telemetry_repository.py` — `register_listener` upsert gains
  `cancelled_at = NULL`; new `mark_listener_cancelled`.
- `src/hassette/core/command_executor.py` — `mark_listener_cancelled` passthrough (mirror
  the job path).
- `src/hassette/core/bus_service.py` — removal-callback registry; invoke it on listener
  removal (the once-fire path); expose `mark_listener_cancelled`.
- `src/hassette/bus/options.py` — add `if_exists` to the `Options` TypedDict (shared by
  `bus.py` and generated `sync.py`).
- `src/hassette/bus/bus.py` — `if_exists` on `on()`, `_on_internal`, `add_listener`
  (now returns `Subscription`); reshape the collision check into the `_`-prefixed
  resolution point; `_registered_handler_names` → `_registered_listeners` (value `Listener`);
  register the removal callback in `__init__` and **deregister it in `on_shutdown`** (bus.py:152);
  spawn `mark_listener_cancelled` on the cancel path.
- `src/hassette/bus/listeners.py` — add `Listener.config_matches`/`diff_fields`.
- `src/hassette/bus/sync.py` — regenerated (not hand-edited).
- `docs/pages/core-concepts/bus/methods.md`, `docs/pages/migration/bus.md`, new bus
  snippet — documentation.
- `src/hassette/test_utils/helpers.py`, `tests/unit/bus/*`,
  `tests/integration/test_sync_facades.py` — test infrastructure and coverage.

### Behavioral Invariants

- `if_exists="error"` (the default) is byte-for-byte the current behavior — existing apps
  see no change unless they opt in.
- The natural key `(app_key, instance_index, name, topic)`, the DB upsert target, and the
  preserved-row-id semantics are unchanged.
- `replace` preserves the listener's `db_id` (FK preservation for `executions.listener_id`).
- Non-once listener registration, routing, dispatch, and cancellation are unchanged except
  for the added `cancelled_at` write on cancel.
- The one intentional behavior change: two once-listeners with the same name+topic now
  collide (previously silent). This is the FR#6 soundness fix, surfaced as a breaking change.

### Blast Radius

- The framework's own `wire_up_app_state_listener` test utility and hot-reload tests must be
  adapted (Test Strategy) — proof the once-collision change has real reach.
- App authors registering duplicate once-listeners under the same name+topic now hit
  `DuplicateListenerError`. Surfaced in the migration doc and breaking-change footer.
- The schema bump recreates existing telemetry DBs on first run after upgrade (disposable
  data; consistent with prior bumps).
- The fire-time removal callback adds a `BusService` → `Bus` notification path; a missed
  invocation would leave a stale key (the failure class the scheduler already manages).
  Covered by FR#7 tests.
- The sync facade and its drift check are touched; regeneration is mandatory before pushing
  (CI gates on it).

## Open Questions

None.
