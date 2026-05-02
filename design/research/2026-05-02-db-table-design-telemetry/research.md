---
topic: "database table design for automation framework telemetry"
date: 2026-05-02
status: Draft
---

# Prior Art: Database Table Design for Automation Framework Telemetry

## The Problem

Automation frameworks need to persist execution history for observability and debugging — but the design of those tables has lasting consequences. Too few columns and you can't diagnose failures; too many and you're carrying dead weight on every write. The structure determines what questions you can answer later: "why did this fail?" vs. "what failed?" vs. "how often does this fail?" Each requires different data.

The tension is between operational queries (fast filtering by status, time, handler) and debugging queries (full context of what happened and why). Most frameworks evolve their schemas over time as they discover which questions they actually need to answer.

## How We Do It Today

Hassette uses SQLite with six core tables: `sessions`, `listeners`, `scheduled_jobs`, `handler_invocations`, `job_executions`, and views. The design follows a **registration table + execution table** pattern — listeners and jobs store their configuration and metadata, while invocations/executions store per-run outcomes. Notable features: `source_tier` (app vs. framework) on every table, soft deletes via `retired_at`, nullable FK with ON DELETE SET NULL for orphan preservation, `is_di_failure` flag, and pre-computed `duration_ms`. The schema is at migration 006.

## Patterns Found

### Pattern 1: Event-Sourced History (Append-Only Event Log)

**Used by**: Temporal, Dapr Workflow

**How it works**: Every state transition is recorded as a typed, immutable event appended to a history log. Events contain: sequence number, typed event enum (WORKFLOW_EXECUTION_STARTED, ACTIVITY_TASK_SCHEDULED, TIMER_FIRED), timestamp, and event-specific attributes serialized as structured data. Current state is reconstructed by replaying the full event history.

Temporal stores these in `history_node` and `history_tree` tables, using a branched tree structure that supports workflow reset (replay to a prior point and diverge). Each node carries a shard_id for horizontal partitioning.

**Strengths**: Complete audit trail. Enables replay/debugging of any historical state. No information ever lost. Supports temporal queries ("what was the state at time T?").

**Weaknesses**: Unbounded growth without explicit compaction (Temporal recommends <50K events per execution). History size directly impacts replay performance. Complex to query for aggregates without secondary projections. Overkill for systems that don't need replay capability.

**Example**: https://docs.temporal.io/workflow-execution/event

### Pattern 2: Flat Relational Task Table (Single Row Per Execution)

**Used by**: Apache Airflow, Celery

**How it works**: Each execution is a single mutable row. State is updated in-place as execution progresses (QUEUED → RUNNING → SUCCESS/FAILED), timestamps filled in progressively, duration computed at completion. Retries either increment `try_number` on the same row or create new rows keyed by attempt.

Airflow's `task_instance` key columns: task_id, dag_id, run_id, execution_date, start_date, end_date, duration, state, try_number, max_tries, hostname, queued_by_job_id, executor, map_index. Indexes on (dag_id, state) and (pool, state, priority_weight) for operational queries.

Celery's basic model is leaner still: task_id, status, result, date_done, traceback.

**Strengths**: Simple to query (WHERE state = 'failed'). Fixed row count per execution — no unbounded growth per task. Good index support for common dashboard queries. Familiar relational model.

**Weaknesses**: Loses intermediate state transitions. No replay capability. Limited debugging context unless supplemented with logs. Concurrent updates require careful locking.

**Example**: https://deepwiki.com/apache/airflow/5.1-database-schema-and-erd

### Pattern 3: Run Table + Separate State Transition Table

**Used by**: Prefect

**How it works**: A `flow_run` / `task_run` table stores the "current snapshot" — id, name, timestamps, current state_type, total_run_time, infrastructure_pid. A separate `flow_run_state` / `task_run_state` table records each state transition with its own timestamp, creating lightweight event history without full event sourcing.

`total_run_time` is incremented in the run table whenever a RUNNING state exits, avoiding expensive aggregation at read time. The run table serves operational queries; the state table serves debugging.

**Strengths**: Fast point queries on current state (run table) plus transition history for debugging (state table). Pre-computed aggregates avoid expensive joins. Independent retention policies per table possible (keep run rows longer than transition detail).

**Weaknesses**: Two writes per state transition. Slightly more complex schema. State table still grows per execution (though much slower than full event sourcing).

**Example**: https://docs.prefect.io/v3/api-ref/python/prefect-server-database-orm_models

### Pattern 4: Blob Storage for Execution Data (Structured Metadata + Unstructured Payload)

**Used by**: n8n, Temporal (for large payloads)

**How it works**: The execution table stores structured metadata in indexed columns (id, status, startedAt, stoppedAt, mode, workflowId) alongside a large text/blob column containing full execution data. n8n stores two blobs: `data` (full node I/O) and `workflowData` (workflow definition at execution time for reproducibility).

The blob is opaque to the database — only deserialized by the application layer. This separates "what can I filter on?" (columns) from "what can I inspect?" (blob).

**Strengths**: Captures everything needed for debugging/reproduction. Structured columns enable efficient filtering. Blob avoids schema changes when execution data evolves. Workflow-at-execution-time enables exact reproduction even after edits.

**Weaknesses**: Blobs cannot be queried or indexed. Large payloads dominate storage. Selective retrieval impossible (load all or nothing). Schema evolution of blob format requires app-level migration.

**Example**: https://docs.n8n.io/hosting/scaling/execution-data/

### Pattern 5: Two-Tier Result Storage (Minimal + Extended)

**Used by**: Celery

**How it works**: Two models at different detail levels. The basic `Task` model: task_id, status, result, date_done, traceback — minimum for outcome retrieval. The extended `TaskExtended` model adds: name, args, kwargs, worker, queue, retries — debugging and operational context.

Operators choose which model based on observability needs. The choice is per-deployment.

**Strengths**: Explicit storage/observability tradeoff. Minimal model is extremely lightweight. Extended model adds debugging without changing core protocol. Clear separation of concerns (result retrieval vs. operational debugging).

**Weaknesses**: If you start minimal and later need debugging data, historical executions lack it. Choice is per-deployment not per-task. Two models to maintain and keep in sync.

**Example**: https://docs.celeryq.dev/en/stable/internals/reference/celery.backends.database.models.html

### Pattern 6: Configurable Retention with Selective Persistence

**Used by**: n8n, Airflow (log pruning)

**How it works**: Rather than storing unconditionally, the framework lets users configure what to persist. n8n offers per-workflow settings: save all executions, only failed ones, only manual runs, or nothing. A background pruner runs with configurable max age and max count, using two-stage deletion (soft-delete, then hard-delete after a safety buffer period). User-annotated executions are exempt from automatic pruning.

**Strengths**: Prevents unbounded growth automatically. Users control the tradeoff for their use case. Safety buffer prevents losing data during active debugging. Annotation exemption preserves intentionally-saved executions.

**Weaknesses**: Aggressive pruning can delete data needed for delayed investigations. Configuration complexity. Per-workflow settings create inconsistent retention. Soft-delete adds storage overhead during buffer period.

**Example**: https://docs.n8n.io/hosting/scaling/execution-data/

### Pattern 7: Sharding by Execution Identity

**Used by**: Temporal

**How it works**: All execution-related tables include a `shard_id` in their primary key. Shard assignment is deterministic based on namespace_id + workflow_id, ensuring all data for a single execution lives on the same shard. Related tables (executions, buffered_events, history_node, activity_info_maps) share the same sharding key for co-located operations.

**Strengths**: Enables horizontal scaling to millions of concurrent executions. Co-location avoids distributed transactions. Deterministic routing without lookup tables.

**Weaknesses**: Cross-shard queries require scatter-gather. Adding shards requires rebalancing. Every primary key becomes more complex. Irrelevant for single-node SQLite deployments.

**Example**: https://planetscale.com/blog/temporal-workflows-at-scale-sharding-in-production

## Anti-Patterns

- **Property Sourcing (Events Without Business Context)**: Recording "FieldXChanged" without capturing WHY. Produces audit trails answering "what happened" but not "why," making debugging difficult. Events should capture intent ("ListenerRegistered" not "StateChangedToActive"). Source: https://event-driven.io/en/property-sourcing/

- **Full Payload Blobs Without Selective Retrieval**: n8n's `data` column stores complete I/O of every node as a single text blob. For high-volume workflows, this creates massive rows that must be fully loaded even when you only need metadata. Source: https://docs.n8n.io/hosting/scaling/execution-data/

- **Unbounded History Without Compaction**: Temporal documents that histories >50K events degrade replay performance. Without explicit compaction or bounded lifetimes, long-running automations accumulate history that slows every state recovery. The fix is architectural (bounded execution lifetimes), not operational (bigger database). Source: https://docs.temporal.io/encyclopedia/event-history

- **Over-Indexing Write-Heavy Tables**: Every index on a telemetry table adds overhead to every INSERT. Airflow strategically indexes only query patterns that matter operationally. Speculative indexes ("might query by X someday") silently erode write performance. Source: https://deepwiki.com/apache/airflow/5.1-database-schema-and-erd

## Emerging Trends

- **Dual-Write Separation (Hot State + Cold History)**: Mutable "current state" (fast reads/writes during execution) separated from immutable "history" (debugging/compliance). Enables different retention, indexing, and storage strategies per tier.

- **Configurable Observability Depth**: Per-workflow/per-handler configuration of what to persist. Critical automations get full traces; high-frequency polling automations only store errors.

- **Pre-Computed Aggregates**: Prefect's `total_run_time` updated incrementally on state transitions rather than computed from events. Avoids expensive aggregation at read time — critical for dashboard/UI latency.

- **Two-Stage Deletion with Safety Buffers**: Soft-delete then hard-delete with configurable buffer. Acknowledges that the window after execution is when most debugging occurs.

## Relevance to Us

Hassette's current schema is closest to **Pattern 2 (Flat Relational)** with elements of **Pattern 3 (Run + State Table)** — the registration tables (listeners, scheduled_jobs) serve as the "run table" with current state, while the invocation/execution tables serve as execution records. Key comparisons:

**What we do well:**
- `source_tier` separation (app vs. framework) — not seen in any surveyed framework. This is a differentiator for frameworks that run internal infrastructure alongside user code.
- `is_di_failure` flag — fine-grained error classification that Airflow and Celery lack (they only have status + traceback).
- Soft deletes via `retired_at` — matches best practice. n8n does similar.
- Nullable FKs with SET NULL for orphan preservation — protects invocation history from parent deletion.
- Pre-computed `duration_ms` — matches Prefect's `total_run_time` pattern (emerging trend).
- `registration_source` and `source_location` — enables "where was this registered?" debugging that most frameworks don't offer.

**Potential gaps to consider:**
1. **No state transition history** (intentional) — unlike Prefect, we only store the final outcome of an invocation (success/error/cancelled/timed_out). We can't answer "how long was it queued before running?" This is by design — hassette handlers are fast-fire (not long-running workflows), so intermediate states have minimal debugging value. Only worth revisiting if long-running handlers or explicit queuing are added.
2. **No trigger context on invocations** — `handler_invocations` has `listener_id` but doesn't capture *which event* triggered the invocation (entity_id, old_state, new_state). Debugging "why did this fire?" requires correlating with event logs externally. Airflow stores dag_run_id linking back to the triggering event.
3. **No retry tracking** — Airflow stores `try_number` and `max_tries`. Hassette's invocation records don't track whether this was a retry or which attempt number it is. If retries are added later, the schema would need to accommodate this.
4. **No execution arguments** — Celery's extended model stores `args_json` and `kwargs_json` on executions. Hassette stores these on `scheduled_jobs` (the registration) but not on individual executions. If args change between runs (dynamic scheduling), the invocation won't capture what arguments were used for that specific execution.
5. ~~No retention/pruning story~~ — **already addressed**. `database_service.py` implements hourly retention cleanup (deletes invocations/executions older than `db_retention_days` config) plus a size failsafe that triggers emergency cleanup when DB exceeds `db_max_size_mb`. Both run in the serve loop.
6. **No "mode" column** — n8n tracks how an execution was triggered (manual, trigger, webhook, retry). Hassette doesn't distinguish between "user triggered via UI" vs. "event-driven" vs. "scheduled" invocations.

**What doesn't apply:**
- Sharding (Pattern 7) — irrelevant for single-node SQLite
- Full event sourcing (Pattern 1) — overkill for hassette's use case (short-lived event handlers, not long-running workflows)
- Full blob storage (Pattern 4) — hassette's handlers don't produce large I/O payloads worth storing

## Recommendation

Hassette's current schema is well-designed for its scope. The **source_tier**, **is_di_failure**, and **registration_source** columns show thoughtful framework-specific decisions that go beyond what most workflow engines store. The schema is closest to Airflow's flat-relational model but with better metadata.

The most impactful improvements to consider, in priority order:

1. **Trigger context on invocations** — even a nullable `trigger_entity_id` or `trigger_summary` column would dramatically improve "why did this fire?" debugging. This is the #1 gap compared to Prefect and Airflow, which link every execution to its triggering event/run.

2. **Retention/pruning** — a background task that prunes invocations older than N days (configurable, with soft-delete buffer) would prevent unbounded growth. n8n's two-stage approach is simple and proven. Consider also a "pin" mechanism for user-annotated executions.

3. **Execution mode/trigger type** — a `trigger_mode` column (event, schedule, manual, retry) on invocations/executions would enable filtering by how something was triggered, useful for both debugging and analytics.

4. **State transition table** — only worth adding if hassette later supports long-running handlers or needs queuing analytics. For now, the fast-fire event handler model means transitions are basically instant (queued → running → done in milliseconds), making a transition table low-value.

## Sources

### Reference implementations
- https://docs.temporal.io/workflow-execution/event — Temporal event history documentation
- https://deepwiki.com/apache/airflow/5.1-database-schema-and-erd — Airflow database schema ERD
- https://docs.prefect.io/v3/api-ref/python/prefect-server-database-orm_models — Prefect ORM models
- https://docs.celeryq.dev/en/stable/internals/reference/celery.backends.database.models.html — Celery database backend models

### Blog posts & writeups
- https://planetscale.com/blog/temporal-workflows-at-scale-sharding-in-production — PlanetScale on Temporal sharding
- https://medium.com/data-science-collective/system-design-series-a-step-by-step-breakdown-of-temporals-internal-architecture-52340cc36f30 — Temporal architecture breakdown
- https://event-driven.io/en/property-sourcing/ — Property sourcing anti-pattern

### Documentation & standards
- https://www.astronomer.io/docs/learn/airflow-database — Airflow metadata database guide
- https://docs.n8n.io/hosting/scaling/execution-data/ — n8n execution data management
- https://deepwiki.com/n8n-io/n8n-docs/3.7-execution-data-management-and-pruning — n8n pruning documentation
- https://learn.microsoft.com/en-us/azure/architecture/patterns/event-sourcing — Microsoft event sourcing pattern
