---
topic: "user-facing vs internal telemetry separation in automation frameworks"
date: 2026-04-07
status: Draft
---

# Prior Art: User-Facing vs Internal Telemetry Separation

## The Problem

Automation frameworks run two categories of work: user-defined automations (the primary value) and internal framework operations (scheduling, health checks, reconnection, session management). Both can fail. Users need to see their automation errors on a dashboard; operators need to see framework errors somewhere. The question is how to store, separate, and surface these two categories without one polluting the other, and what to do with execution records when their parent registration is deleted.

## How We Do It Today

Hassette uses a binary split controlled by `db_id`: if a listener/job has a `db_id` (DB registration succeeded), its executions are persisted to SQLite and appear on the dashboard. If `db_id is None` (internal framework actor or registration not yet complete), executions are log-only with no DB record. Orphaned records from deleted `once=True` listeners are preserved via `ON DELETE SET NULL` but are invisible to dashboard queries due to INNER JOINs — they exist in the DB but never surface.

## Patterns Found

### Pattern 1: Metadata Tag on Every Record (Source Annotation)

**Used by**: Temporal (`TemporalNamespaceDivision`), OpenTelemetry (instrumentation scope), Apache Airflow (`run_type` enum, DAG tags)

**How it works**: Every execution record is created with a metadata field identifying its source tier. The UI/API layer auto-injects a filter excluding framework records unless explicitly requested. In Temporal, scheduler workflows are tagged with `TemporalNamespaceDivision = "TemporalScheduler"` at creation; all list queries append `AND TemporalNamespaceDivision IS NULL` by default. In OpenTelemetry, every span carries an instrumentation scope (`otel.library.name`) that backends like Jaeger use for filtering.

The key insight is that the annotation is set at creation time and is immutable — no retroactive classification. Temporal explicitly chose this over post-fetch filtering because naive filtering breaks pagination (fetching 20 records, filtering 8 framework records, returning only 12 to the user).

**Strengths**: Self-describing records; no separate storage; records remain queryable by operators; scales to multiple tiers; pagination-correct.

**Weaknesses**: Requires discipline at every record creation site; tag values must be stable (renaming requires migration); adds a field to every record.

**Example**: https://temporal.io/blog/how-we-build-it-building-scheduled-workflows-in-temporal

### Pattern 2: Separate Storage Surfaces by Tier

**Used by**: Home Assistant (Logbook / System Log / automation traces), Dagster (daemon log vs run records)

**How it works**: Framework events and user execution records go to entirely separate stores with separate UI pages. In Home Assistant, the Logbook shows user events, automation traces show per-automation execution detail (capped at 5), and the System Log shows framework errors — none bleed into each other. In Dagster, the daemon's scheduling/sensor activity appears only in daemon logs; only launched runs appear in the user runs table.

**Strengths**: Complete isolation — framework bugs can't pollute user dashboards; simpler query logic (no filter clauses needed); UI can be designed independently per tier.

**Weaknesses**: Cross-tier correlation requires manual effort; duplicate schema if stores are similar; harder to evolve if a record type needs to move between tiers.

**Example**: https://www.home-assistant.io/docs/automation/troubleshooting/

### Pattern 3: Cascade Delete for Orphan Prevention

**Used by**: n8n, Prefect (parent-child flow run linkage)

**How it works**: Execution records are owned by their registration. Deleting a workflow in n8n deletes all its execution history in the same operation. n8n's automated pruning uses a two-stage soft-delete/hard-delete pipeline with configurable retention. The system never allows execution records to exist without a valid parent.

**Strengths**: No orphan accumulation; storage bounded by active registrations; dashboards stay accurate.

**Weaknesses**: Destructive — history is permanently lost on deletion; forensic analysis of past runs impossible; surprising if users expect only the definition to disappear.

**Example**: https://docs.n8n.io/workflows/executions/all-executions/

### Pattern 4: Framework Internals Produce No User-Space Records

**Used by**: Dagster (daemon scheduling), Airflow (scheduler heartbeats), Home Assistant (internal event bus)

**How it works**: Framework bookkeeping (scheduler ticks, health checks, dependency resolution) simply doesn't create records in the user-facing store. Activity goes to framework logs only. The user store is strictly user-initiated or schedule-initiated executions. In Airflow, the scheduler loop produces no `DagRun` records — only actual DAG executions do.

**Strengths**: Simplest UX — dashboard is unambiguously about user work; no filtering needed; framework can evolve without user-visible side effects.

**Weaknesses**: Debugging framework problems requires separate log access; when a framework error causes a user job to not run, the user sees absence (no record) rather than an error record explaining why.

**Example**: https://docs.dagster.io/deployment/execution/dagster-daemon

## Anti-Patterns

- **Flat record store without source tagging (Celery/Flower)**: All tasks in a single undifferentiated stream. Teams resort to naming conventions (`_internal_` prefix) and queue routing, which breaks silently when new internal tasks are added without the convention.
- **Post-fetch filtering without pagination correction**: Filtering framework records after querying breaks pagination — pages return fewer results than requested. Temporal explicitly rejected this pattern.
- **Infrastructure events surfaced without context (Prefect)**: Forwarding Kubernetes pod events into user flow timelines creates noise for non-infrastructure-aware users.
- **Silent orphan accumulation**: Execution records from deleted registrations accumulate indefinitely, creating false dashboard signal and storage bloat.

## Emerging Trends

OpenTelemetry instrumentation scope is converging as the standard mechanism for framework-vs-user attribution. Prefect (PR #16010) and Temporal both support OTel, meaning the distinction is available for free to any OTel-compatible backend. Separately, retention policy is becoming a first-class user-configurable concern rather than a hidden framework default.

## Relevance to Us

Hassette currently uses **Pattern 4** (framework internals produce no user-space records) combined with **partial Pattern 2** (internal errors go to logs only, not the dashboard). However, the implementation has gaps:

1. **The `db_id is None` sentinel conflates "internal" with "pending registration"** — Pattern 1's explicit source tag would eliminate this ambiguity. Temporal's `TemporalNamespaceDivision` is the closest analogue to what an `is_internal` flag or `source_tier` column would provide.

2. **Orphaned records are preserved but invisible** — Hassette uses `ON DELETE SET NULL` (preserving history) but then INNER JOINs in queries (hiding it). This is neither Pattern 3 (cascade delete — clean but destructive) nor Pattern 1 (tag and filter — visible when queried). It's an accidental anti-pattern: records exist but are unreachable. The fix is either LEFT JOIN (expose orphans with a "deleted handler" label) or explicit cascade (accept history loss).

3. **No framework health surface exists** — Pattern 2 (HA's System Log) and Pattern 4 (Dagster's daemon log) both provide *some* surface for framework errors. Hassette provides none beyond raw log output. The challenge's Finding 6 (in-memory error counter on `/health`) is the minimal version of Pattern 4's separate surface.

4. **The UNION ALL fix for `get_recent_errors`** aligns with Pattern 1's principle: filtering and ordering should happen in the query layer, not post-fetch in Python. Temporal's pagination argument applies directly.

## Recommendation

**Pattern 1 (source tag) is the right long-term direction**, matching both the challenge's Finding 1 (`is_internal` flag) and the industry consensus (Temporal, OTel). For the immediate issue 484 fix, the minimum viable changes are:

1. LEFT JOIN in `get_recent_errors` (expose orphaned records — aligns with "records should be reachable")
2. UNION ALL query (fix limit semantics — aligns with Pattern 1's query-level filtering principle)
3. In-memory framework error counter on `/health` (minimal Pattern 4 surface)

The `source_tier` column (challenge Finding 20) is worth deferring unless there's a concrete requirement for framework telemetry in the dashboard — the challenge's TENSION finding is correct that this may be over-engineering without demand.

**Hassette's `ON DELETE SET NULL` approach is defensible** and aligns more with an archival philosophy than n8n's cascade-delete. The gap is that the query layer doesn't honor it. Fixing the JOINs is sufficient — no need to switch to cascade delete.

## Sources

### Reference implementations
- https://temporal.io/blog/how-we-build-it-building-scheduled-workflows-in-temporal — Temporal's NamespaceDivision pattern for hiding system workflows
- https://docs.temporal.io/search-attribute — Temporal search attributes including system attributes
- https://docs.temporal.io/visibility — Temporal's visibility system architecture
- https://docs.n8n.io/workflows/executions/all-executions/ — n8n execution history and cascade delete
- https://github.com/PrefectHQ/prefect/pull/16010 — Prefect OTel instrumentation addition

### Documentation & standards
- https://opentelemetry.io/docs/concepts/instrumentation-scope/ — OTel instrumentation scope concept
- https://github.com/open-telemetry/opentelemetry-specification/issues/4330 — OTel spec discussion on scope semantics
- https://airflow.apache.org/docs/apache-airflow/stable/core-concepts/dag-run.html — Airflow DAG run types
- https://airflow.apache.org/docs/apache-airflow/3.0.0/_api/airflow/models/dagrun/index.html — Airflow DagRun model
- https://docs.dagster.io/deployment/execution/dagster-daemon — Dagster daemon separation
- https://www.home-assistant.io/docs/automation/troubleshooting/ — HA's three-tier telemetry model

### Blog posts & writeups
- https://oneuptime.com/blog/post/2026-02-06-otel-instrumentation-scope-correlate-signals/view — OTel scope for correlating signals
- https://n8n.io/workflows/6833-automated-execution-cleanup-system-with-n8n-api-and-custom-retention-rules/ — n8n retention rules
- https://docs.celeryq.dev/en/main/userguide/monitoring.html — Celery monitoring (anti-pattern: flat store)
