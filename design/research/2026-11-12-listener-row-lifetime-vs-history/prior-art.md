---
topic: "Listener-row lifetime versus its child history (persisted and buffered)"
date: 2026-11-12
status: Draft
---

# Prior Art: Listener-Row Lifetime Versus Its Child History

## The Problem

Hassette's telemetry DB has one `listeners` row per registered listener, with child history in `executions` and `listener_misses`. At startup and app reload, reconciliation deletes non-live listener rows that have no history and retires the ones that do. Near-misses are aggregated in memory and written every 30 s.

Every review round on PR #4013 (spec 151) has found another way a removed listener's row and its near-misses come apart. First the sketch had to pick a delete policy for the new foreign key, and chose cascade. Next the ship challenge documented drops for removed listeners as an uncounted loss. Then reconciliation deleted a never-run listener and cascaded its misses away, which was patched by counting miss rows as history. Now Codex finds that this check only sees persisted misses. A never-run listener removed or renamed before its first flush is deleted, and its buffered misses are dropped silently by the upsert. Each fix has added another condition to when a listener row may be deleted. The question is whether comparable systems guard against this at all, and how.

## How We Do It Today

- **Reconciliation** (`reconcile_sql.py:82-160`, called from `app_lifecycle_registrations.py`, one transaction) deletes non-live `once = 0` rows when `history_exists_sql` is false, and retires them (`retired_at = now`) when it's true. History means an `executions` row or a `listener_misses` row (`LISTENER_MISS_HISTORY_SQL`). The `once=True` cleanup (`repository.py:~434-470`) deletes once-listeners with no current-session execution and no misses, and retires ones with misses.
- **FK policies.** `listener_misses.listener_id` is `ON DELETE CASCADE` (`025.sql:10`). `executions.listener_id` is `ON DELETE SET NULL`, but a CHECK requires exactly one of `listener_id`/`job_id`, so deleting a listener that has executions would fail.
- **Retention** (`database_retention.py:351-370`) deletes a retired listener only after `retired_at` is past the cutoff and no execution or miss is newer than the cutoff. It already waits for children to age out.
- **Buffers aren't coordinated with reconciliation.** The miss recorder flushes on a 30 s loop tied to `BusService`, not to app reload. `_LISTENER_MISS_UPSERT_SQL` is `INSERT … SELECT … WHERE EXISTS (listener)`, so a miss for a deleted listener is a silent no-op, with no error, count or log. Execution writes queued in `CommandExecutor` hit the same race, but louder: the FK error goes through `handle_fk_violation`, fails the CHECK, and is counted and logged as a drop.

## Patterns Found

### Pattern 1: Never delete the parent when the entity disappears; delete it only once its children are gone

**Used by**: Home Assistant recorder (`states_meta`, `event_types`, `statistics_meta`), Prometheus TSDB head

**How it works**: Removing the real-world entity does nothing to its metadata row. HA deletes `states_meta` rows only in `_purge_old_entity_ids`, at the end of a purge cycle, selecting ids that "no longer exist in the States table" (`find_entity_ids_to_purge`). Prometheus drops a head series only when GC has removed all its chunks. It even keeps the series record through WAL checkpointing while samples in the log still reference it, so replay doesn't lose them. The parent lives as long as its newest child, so neither persisted nor buffered children can dangle.

**Strengths**: There's no race with buffers. A late write always finds its parent.

**Weaknesses**: Parent rows build up when the entity never returns. HA's orphaned `statistics_meta` rows are a long-standing complaint, cleared by hand from Developer Tools.

**Example**: https://github.com/home-assistant/core/blob/dev/homeassistant/components/recorder/purge.py

**Read**: HA `purge.py`, `queries.py`, `statistics.py`, `db_schema.py`; Prometheus `tsdb/head.go` `gc()` (all opened). The orphan complaints are secondary (search highlights of core#117046 and a forum thread).

### Pattern 2: Flush the write buffer before any destructive step (single-writer ordering)

**Used by**: Home Assistant recorder; OpenTelemetry (`Shutdown` must include `ForceFlush`); Node-RED context store (flush on close)

**How it works**: HA's recorder runs everything on one thread from one queue. Every non-event `RecorderTask` defaults to `commit_before = True`, so the session is committed before a purge, rename migration or statistics clear runs. OTel and Node-RED apply the same rule at shutdown.

**Strengths**: It's only an ordering rule, so there's little machinery, and buffered data is kept exactly.

**Weaknesses**: It needs a single writer, or a lock shared by the flusher and the destructive step. HA gets that for free from its architecture; hassette has two writers here, the recorder's flush owner and reconciliation. It also doesn't help a write that arrives after the parent is gone.

**Example**: https://github.com/home-assistant/core/blob/dev/homeassistant/components/recorder/core.py (`_process_one_task_or_event_or_recover`)

**Read**: HA `core.py`, `tasks.py` (opened). OTel: spec `sdk.md` Shutdown sections only. Node-RED: `localfilesystem.js`, grep only.

### Pattern 3: History decoupled from the definition, expired by TTL (no FK, no cascade)

**Used by**: APScheduler 4 (`job_results`), Celery result backend

**How it works**: Result rows are keyed by job id, have no FK to the task or schedule, and expire on their own `expires_at`. Removing a schedule or task deletes only the definition, and orphaned history ages out.

**Strengths**: Removing the parent can never lose history.

**Weaknesses**: Each history row must carry enough identity to be readable once the definition is gone. That works against a schema normalized through FK cascade.

**Example**: https://github.com/agronholm/apscheduler/blob/master/src/apscheduler/datastores/sqlalchemy.py

**Read**: APScheduler `sqlalchemy.py` (opened). Celery: `configuration.rst` `result_expires` (opened); backend code not read.

### Pattern 4: Create the parent lazily on the write path

**Used by**: Home Assistant recorder (`StatesMetaManager.add_pending`)

**How it works**: The writer gets or creates the parent row in the same transaction as the first child, and holds pending parents in a dict until commit.

**Strengths**: A child can never reference a parent that doesn't exist.

**Weaknesses**: The writer needs the parent's full identity at write time. HA's parent is just a name; a hassette listener row carries registration data that reconciliation owns.

**Read**: HA `core.py`, `table_managers/states_meta.py` (opened).

### Pattern 5: Accept the loss and say so

**Used by**: HA recorder. It doesn't record a removal event for an entity with no `metadata_id`. A rename onto an id that's already taken logs "Cannot migrate history … because the new entity_id is already in use" and leaves the history behind. AppDaemon, NetDaemon and pyscript keep no per-callback history, so the case never comes up.

**How it works**: Narrow edge cases get a comment or a warning log, not machinery.

**Weaknesses**: HA at least logs. Hassette's upsert drops silently.

**Read**: HA `core.py`, `entity_registry.py`; AppDaemon `callbacks.py` (opened). NetDaemon and pyscript: grep only.

## Anti-Patterns

- **Treating "not live right now" as grounds to delete history.** The Spook maintainer closed an auto-purge PR because "a disabled entity, an integration that failed to start this boot … a fresh restart all look exactly like that." That is the same condition reconciliation uses. (frenck/spook#1313, search highlight only.)
- **Dropping a child write silently when its parent is missing.** HA's analogous edge case logs a warning. No project read drops without a log.

## Gaps

- None of the projects read has exactly this case: a buffered aggregate whose parent is hard-deleted by a startup reconcile. HA's pending-metadata and `commit_before` handling are the closest.
- HA core#117046, the HA forum thread and Spook #1313 were read only as search highlights. Sentry, Prometheus staleness markers and OTel SDK internals weren't read.

## Relevance to Us

Hassette already has Pattern 1's second half: retention deletes a retired listener only once its executions and misses are older than the cutoff. What it lacks is the first half. Reconciliation still hard-deletes non-live rows it judges to have no history, and "no history" is a guess made against the database while the evidence may still sit in a buffer. Every fix this PR has made, and the one Codex proposes, refines that guess. HA and Prometheus never make it: disappearing never deletes a parent, only children aging out does.

Of the candidate fixes:

- **Always retire and let retention delete** (Pattern 1). This removes the race for both buffers: misses (silent today) and executions (counted drops today). It also makes `LISTENER_MISS_HISTORY_SQL` and the history branch of the delete query unnecessary in reconciliation, so it's mostly a deletion. Rename is covered too, because the old row is retired rather than deleted, so its late misses still land. The cost is that never-run listeners from dev churn sit retired until retention's window passes.
- **Flush before reconciling** (Pattern 2). This works in HA because it has a single writer. Here it would need reconciliation to call into the recorder's flush owner, which brings back a second flush caller that the flush-lifecycle brief (`2026-11-12-telemetry-flush-lifecycle`) just removed. It also leaves the execution queue exposed.
- **Have reconciliation consult the pending entries.** No project does this, and it couples reconciliation to an in-memory structure on another service.

Separately from the choice, the silent `WHERE EXISTS` skip in the upsert runs against the one anti-pattern every source agreed on. Wherever a write can still miss its parent (for example, retention deleting a row while a miss for it is buffered), that skip should at least be counted.

## Recommendation

Adopt Pattern 1: reconciliation retires non-live app listener rows and never hard-deletes them, and retention, which already waits for children to age out, does all deletion. That's what HA and Prometheus do, and it closes this PR's converging findings by removing a rule instead of adding a fourth condition to it.

Before committing, decide whether the `once=True` path keeps its delete. Its deletion of once-listeners that already ran is deliberate, and those rows can't have pending misses after their only run. Also check that retired never-run rows don't clutter any UI or CLI listing during the retention window.

Coverage was good on HA and Prometheus (code read), thinner elsewhere. No peer had the exact failure.

## Sources

### Reference implementations
- https://github.com/home-assistant/core/blob/dev/homeassistant/components/recorder/purge.py — metadata purged only when no child rows remain
- https://github.com/home-assistant/core/blob/dev/homeassistant/components/recorder/core.py — single writer, `commit_before`, lazy parent creation
- https://github.com/home-assistant/core/blob/dev/homeassistant/components/recorder/entity_registry.py — rename updates metadata in place; collision logs a warning
- https://github.com/home-assistant/core/blob/dev/homeassistant/components/recorder/statistics.py — statistics metadata kept after entity removal; manual clear
- https://github.com/prometheus/prometheus/blob/main/tsdb/head.go — series GC driven by chunk age; series records kept through WAL checkpointing
- https://github.com/agronholm/apscheduler/blob/master/src/apscheduler/datastores/sqlalchemy.py — `job_results` with no FK, TTL cleanup
- https://github.com/AppDaemon/appdaemon/blob/dev/appdaemon/callbacks.py — callbacks in memory only
- https://github.com/node-red/node-red/blob/master/packages/node_modules/@node-red/runtime/lib/nodes/context/localfilesystem.js — 30 s flush, flush on close

### Issues & discussions
- https://github.com/home-assistant/core/issues/117046 — orphaned statistics complaints (not opened)
- https://community.home-assistant.io/t/remove-statistics-of-disabled-not-deleted-entities-from-recorder/462599 — warning against auto-removing statistics (not opened)
- https://github.com/frenck/spook/pull/1313 — auto-purge of non-live entities rejected (not opened)

### Documentation & standards
- https://github.com/open-telemetry/opentelemetry-specification/blob/main/specification/metrics/sdk.md — Shutdown includes ForceFlush
- https://raw.githubusercontent.com/celery/celery/main/docs/userguide/configuration.rst — `result_expires`
