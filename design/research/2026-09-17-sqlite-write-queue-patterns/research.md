---
topic: "embedded SQLite async write queue patterns"
date: 2026-09-17
status: Draft
---

# Prior Art: Embedded SQLite Async Write Queue Patterns

## The Problem

When an async Python application uses SQLite for persistent telemetry, the single-writer constraint creates a bottleneck that needs careful queue design. The key decisions: one queue or multiple (with priority), blocking submit vs fire-and-forget, how many connections, and when/how to checkpoint. These are well-trodden choices with mature prior art — HA Recorder, aiosqlite, Datasette, and SkyPilot have all converged on similar patterns.

## How We Do It Today

Hassette uses a single bounded `asyncio.Queue` (maxsize 2000) drained by one worker task. Two calling conventions: `submit()` (blocking, returns a Future) for operations needing results (registrations, session bookkeeping) and `enqueue()` (fire-and-forget, `put_nowait`) for telemetry. A dual-connection model separates reads (`_read_db`, `query_only=ON`) from writes (`_db`). PRAGMAs are appropriate (WAL, `synchronous=NORMAL`, `busy_timeout=5000`, `foreign_keys=ON`). `wal_autocheckpoint=1000` handles checkpointing automatically; the size failsafe also runs manual `wal_checkpoint(TRUNCATE)`.

## Patterns Found

### Pattern 1: Single background writer thread/task draining a queue, batched commits (Recorder pattern)

**Used by**: Home Assistant Recorder, aiosqlite (per-connection worker thread)
**How it works**: One dedicated thread/task owns the database connection and drains a queue. Other code pushes work items onto the queue instead of touching the connection. The writer batches items and commits at intervals rather than per-item.
**Strengths**: Removes DB I/O from hot paths; batching cuts fsync overhead; sidesteps `SQLITE_BUSY` by construction.
**Weaknesses**: The queue becomes the bottleneck under sustained high write volume — HA's community reports this at scale. Crash before flush loses unbatched writes.
**Example**: https://www.home-assistant.io/integrations/recorder/

### Pattern 2: Blocking submit via Future (caller awaits result)

**Used by**: aiosqlite (every public async call)
**How it works**: Caller pushes `(closure, future)` onto the worker queue and awaits the Future. Worker resolves it with result or exception. Looks like an ordinary `await` but work happens serialized on a separate thread.
**Strengths**: Real error propagation — constraint violations surface at the call site. Serialization is free.
**Weaknesses**: Slow writes directly increase caller latency — poor fit for telemetry paths. No built-in timeout in most implementations.
**Example**: https://github.com/omnilib/aiosqlite/blob/main/aiosqlite/core.py

### Pattern 3: Fire-and-forget with dual-trigger batching (telemetry/logs)

**Used by**: General telemetry pipeline guidance (OneUptime), HA Recorder's non-blocking `SimpleQueue.put()`
**How it works**: Producer pushes to a bounded queue and returns immediately. Consumer batches by size AND time (dual-trigger: flush every N items or every T seconds, whichever first). Priority records may flush immediately; shutdown handler flushes remaining.
**Strengths**: Producers never block on disk I/O. Batching amortizes commit cost.
**Weaknesses**: Silent data loss on crash. Bare `asyncio.create_task()` without retained reference can lose the task entirely. Requires explicit backpressure (bounded queue + drop policy).
**Example**: https://oneuptime.com/blog/post/2026-01-30-log-batching/view

### Pattern 4: Dual-connection model — write + read(s) under WAL

**Used by**: Datasette (3 readers + 1 writer), SkyPilot
**How it works**: One connection for writes (routed through a serialization point), one or more for reads. WAL allows concurrent readers alongside a single writer.
**Strengths**: Read latency decoupled from write load. "One writer" invariant enforced by object ownership, not convention.
**Weaknesses**: Reads can serve slightly stale data. Must ensure only the write connection issues writes.
**Example**: https://blog.skypilot.co/abusing-sqlite-to-handle-concurrency/

### Pattern 5: Checkpoint strategy tuned to write pattern

**Used by**: SQLite default (automatic), batch-ingest systems (manual/scheduled)
**How it works**: Default: automatic PASSIVE checkpoint at `wal_autocheckpoint=1000` pages — simple but ties checkpoint I/O to whichever commit crosses the threshold. Alternative: disable autocheckpoint, run manual `wal_checkpoint(TRUNCATE)` on a schedule or after a batch.
**Strengths**: Automatic is zero-config. Manual removes latency spikes from the write path.
**Weaknesses**: Automatic can spike latency unpredictably. Manual requires reliable scheduling.
**Example**: https://www.sqliteforum.com/p/checkpoint-algorithms-and-wal-performance

## Anti-Patterns

- **`busy_timeout` alone doesn't solve contention** — lock-upgrade sequences can still fail immediately. WAL + `busy_timeout` + short transactions (or `BEGIN IMMEDIATE`) needed together.
- **Bare `asyncio.create_task()` for fire-and-forget** — event loop holds only a weak reference; task can be GC'd mid-flight, silently losing exceptions.
- **Write transaction held open across external I/O** — common cause of avoidable lock contention.
- **Single queue as silent throughput ceiling** — HA Recorder is the real-world case study: past a certain volume, the fix is migrating off SQLite, not tuning the queue.

## Relevance to Us

Hassette's architecture already follows the consensus pattern family (Patterns 1, 2, 4). The submit/enqueue split maps cleanly to Patterns 2 and 3. The dual-connection model matches Pattern 4 exactly. The gaps are in the *refinements* each pattern expects:

1. **`submit()` needs a timeout** — Pattern 2 implementations (aiosqlite) don't have one either, but hassette's `update_heartbeat` already adds one manually (30s), acknowledging the need. Most other `submit()` callers have none.
2. **No priority between write kinds** — Pattern 3 recommends immediate flush for priority records and explicit backpressure. Hassette's single FIFO conflates "worker is busy processing legitimate work" with "worker is wedged," and heartbeat timeout can't tell the difference.
3. **Checkpoint strategy is mixed** — automatic `wal_autocheckpoint=1000` (Pattern 5 automatic) plus manual `wal_checkpoint(TRUNCATE)` in the size failsafe (Pattern 5 manual). These aren't in conflict, but the manual checkpoint runs inline on the write worker for up to 30 iterations, blocking all other writes.
4. **Batching is partial** — `_insert_log_records` batches (Pattern 3), but retention/failsafe cleanup is per-row with inline vacuum, not batched.

## Recommendation

The prior art validates hassette's core architecture (single writer, submit/enqueue split, dual connections, WAL+NORMAL PRAGMAs). The actionable gaps are refinements, not redesigns:

1. **Add a default timeout to `submit()`** — every implementation of Pattern 2 expects one; hassette has it for heartbeat but nowhere else.
2. **Wire the orphaned config fields** — six `DatabaseConfig` knobs that users can set but that silently do nothing. This is the cheapest fix with the clearest user-facing impact.
3. **Consider separating the size-failsafe's checkpoint work** from the main write queue to avoid blocking other writes during emergency cleanup.

None of the prior art suggests hassette needs multiple queues or a fundamentally different architecture. The single-writer queue is the right shape for a single-user embedded telemetry database.

## Sources

### Reference implementations
- https://www.home-assistant.io/integrations/recorder/ — HA Recorder (single-writer thread + queue + batched commits)
- https://github.com/omnilib/aiosqlite/blob/main/aiosqlite/core.py — aiosqlite (Future-based blocking submit)
- https://github.com/simonw/datasette/issues/2942 — Datasette connection architecture (3 readers + 1 writer)

### Blog posts & writeups
- https://phiresky.github.io/blog/2020/sqlite-performance-tuning/ — Canonical SQLite WAL/PRAGMA tuning reference
- https://blog.skypilot.co/abusing-sqlite-to-handle-concurrency/ — Dual-connection pattern for SQLite
- https://berthub.eu/articles/posts/a-brief-post-on-sqlite3-database-locked-despite-timeout/ — `busy_timeout` limitations
- https://tenthousandmeters.com/blog/sqlite-concurrent-writes-and-database-is-locked-errors/ — WAL + single writer rationale
- https://tekmusings.com/fire-but-dont-forget.html — asyncio fire-and-forget pitfalls
- https://oneuptime.com/blog/post/2026-01-30-log-batching/view — Dual-trigger log batching
- https://www.xda-developers.com/replaced-home-assistants-built-in-database-postgresql-smart-home-snappy/ — HA queue backlog at scale

### Documentation & standards
- https://www.sqlite.org/wal.html — SQLite WAL mode reference
- https://www.sqliteforum.com/p/checkpoint-algorithms-and-wal-performance — WAL checkpoint strategies
