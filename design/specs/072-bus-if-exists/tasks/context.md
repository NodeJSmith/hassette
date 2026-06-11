# Context: `if_exists` for bus handler registration

## Problem & Motivation

The scheduler lets an app conditionally register or hot-swap a named job via
`if_exists="error" | "skip" | "replace"`, enabling idempotent registration (safe re-runs of
`on_initialize`) and handler hot-swaps. The bus has no equivalent — a name clash always raises
`DuplicateListenerError`, forcing manual cancel-then-register. This change brings the bus to
parity with the scheduler. It also closes two gaps in the same area: once-listeners are exempt
from in-memory collision tracking (so duplicates coexist silently), and listeners have no
durable cancellation marker, so a replaced or cancelled listener leaves no telemetry trace.

## Visual Artifacts

None.

## Key Decisions

1. **`if_exists` on every registration method, via the `Options` TypedDict.** Adding one key
   to `bus/options.py` propagates `if_exists` through `**opts` to every event-specific method
   with type safety; `on()` (explicit signature) and `add_listener` get an explicit param.
   This mirrors the scheduler, which exposes `if_exists` on every scheduling method.
2. **`skip` does full drift detection.** It returns the existing listener when configs match,
   else raises `ValueError` listing changed fields — mirroring `ScheduledJob.matches` /
   `diff_fields`. Feasible because built-in predicates are `@dataclass(frozen=True)` and
   compare by value. Lambda/closure filters compare by identity (same limitation the scheduler
   has) and will report drift — documented, not fixed.
3. **`replace` preserves the row id.** The natural-key DB row is the stable identity (FK
   preservation for `executions.listener_id`); `replace` updates it in place, exactly as the
   scheduler does. There is NO fresh `db_id`.
4. **Durable cancellation via `cancelled_at`, mirroring the scheduler.** Add the column to
   `listeners`, write it on cancel (`mark_listener_cancelled`), clear it on re-registration
   (`cancelled_at = NULL` in the upsert's `DO UPDATE`). This is what makes replace/cancel/
   once-fire observable in telemetry.
5. **once-listeners are tracked (Direction A).** Remove the collision exemption; add a
   fire-time removal callback (`BusService` → `Bus`) mirroring the scheduler's
   `register_removal_callback` / `_on_job_removed`, so the in-memory key is released and
   `cancelled_at` written when a once-listener fires. This is a breaking change (same
   name+topic once-listeners now raise) — ship as `feat!` with a `BREAKING CHANGE:` footer.
6. **The new comparison method is named `config_matches`, NOT `matches`.** `Listener.matches`
   already exists (`bus/listeners.py:360`) as the event-predicate dispatch method on the
   routing hot path — it must not be shadowed.

## Constraints & Anti-Patterns

- **Do NOT regress the scheduler** to chase symmetry (no removing one-shot tracking). Parity
  is achieved by raising the bus to the scheduler.
- **Do NOT hand-edit `src/hassette/bus/sync.py`** — it is generated. Regenerate with
  `uv run hassette-codegen sync-facade`; verify with `--check`.
- **Keep the collision-resolution method `_`-prefixed** (e.g. `_resolve_collision`) so the
  sync-facade codegen (`sync_facade/ast_utils.py`) skips it — otherwise it gets exposed on the
  facade.
- **Do NOT give `replace` a fresh `db_id`** (no DELETE+INSERT, no partial unique index). The
  upsert `DO UPDATE` path preserving the row id is the parity behavior.
- **`skip` must raise on drift**, never silently return the stale listener while discarding the
  new arguments.
- **Do NOT add a separate `if_exists` branch for once-listeners** — once tracked, they flow
  through the identical resolution path.
- **Do NOT name the new comparison method `matches`** — collision with the existing routing
  method. Use `config_matches`.
- **Non-goal:** no change to the natural key `(app_key, instance_index, name, topic)` or to
  the scheduler.

## Design Doc References

- `## Architecture` — the full implementation approach: threading `if_exists`, collision
  resolution, `config_matches`, the `cancelled_at` mechanism, once-tracking + removal callback,
  sync-facade regeneration.
- `## Migration` — the `PRAGMA user_version` scheme (replaced Alembic) and why a new `002.sql`
  is required to add `cancelled_at`.
- `## Convention Examples` — verbatim scheduler code to mirror (if_exists block, matches/
  diff_fields, cancelled_at write+clear, removal callback).
- `## Replacement Targets` — `_registered_handler_names` → `_registered_listeners`; the once
  exemption; `add_listener` return type.
- `## Test Strategy` — existing tests to adapt (incl. `wire_up_app_state_listener`,
  `test_hot_reload.py`, `test_t03_registration_errors.py`), new coverage mapped to FRs.
- `## Edge Cases` — lambda drift, non-atomic replace, concurrent skip during dispatch.
- `## Impact` — Changed Files, Behavioral Invariants, Blast Radius.

## Convention Examples

### Scheduler `if_exists` resolution — the canonical error/skip/replace shape

**Source:** `src/hassette/scheduler/scheduler.py` (collision block inside `add_job`, lines 201–218)

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
        raise ValueError(...)
```

### `ScheduledJob.matches` / `diff_fields` — mirror as `Listener.config_matches` / `diff_fields`

**Source:** `src/hassette/scheduler/classes.py:268` (`matches`) and `:295` (`diff_fields`)

```python
def matches(self, other: "ScheduledJob") -> bool:
    """Same logical configuration? Compares callable, trigger, group, jitter, timeout,
    timeout_disabled, args, kwargs, error_handler (by identity). Excludes runtime state."""
    ...
    return (self.job == other.job and triggers_match and ... and self.error_handler is other.error_handler)

def diff_fields(self, other: "ScheduledJob") -> list[str]:
    changed: list[str] = []
    if self.job != other.job:
        changed.append("job")
    # ... one append per differing field ...
    return changed
```

### Durable cancellation — `cancelled_at` write + upsert clear

**Source:** `src/hassette/core/telemetry_repository.py:376` (job upsert clears it) and `:403` (`mark_job_cancelled`)

```python
# In register_job's ON CONFLICT DO UPDATE (mirror in register_listener):
    retired_at = NULL,
    cancelled_at = NULL  -- re-registration clears cancellation
RETURNING id

# mark_job_cancelled (mirror as mark_listener_cancelled):
async def mark_job_cancelled(self, db_id: int) -> None:
    await db.execute(
        "UPDATE scheduled_jobs SET cancelled_at = :cancelled_at WHERE id = :id",
        {"cancelled_at": time.time(), "id": db_id},
    )
    await db.commit()
```

`CommandExecutor.mark_job_cancelled` (command_executor.py:574) delegates to the repository via
`database_service.submit`; `SchedulerService.mark_job_cancelled` (scheduler_service.py:462)
delegates to the executor; `Scheduler.cancel_job` (scheduler.py:257–264) spawns it on the
service task bucket so the write survives resource shutdown. Mirror this chain for listeners.

### Scheduler fire-time removal callback — the once-listener cleanup pattern

**Source:** `src/hassette/scheduler/scheduler.py:119` (register), `:141` (deregister), `_on_job_removed`

```python
# __init__:  self.scheduler_service.register_removal_callback(self.owner_id, self._on_job_removed)
def _on_job_removed(self, job: "ScheduledJob") -> None:
    self._jobs_by_name.pop(job.name, None)
    ...
# on_shutdown:  self.scheduler_service.deregister_removal_callback(self.owner_id)
```
