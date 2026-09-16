---
topic: "embedded telemetry retention strategies"
date: 2026-09-16
status: Draft
---

# Prior Art: Embedded Telemetry Retention for Automation Frameworks

## The Problem

When an automation framework persists execution telemetry to a local SQLite database, high-frequency internal signals (framework plumbing like state-change proxying) can crowd out the data that actually matters for troubleshooting (app-tier executions and logs). A single global size cap with delete-oldest-first can't distinguish valuable from noisy data, so the most useful records get wiped while the noisiest table grows back within hours.

This is a well-documented class of problem. Home Assistant's own recorder component, Prometheus/Thanos, OpenTelemetry, and edge/IoT observability systems have all converged on similar solutions — the patterns are mature and the anti-patterns are well-catalogued.

## How We Do It Today

Hassette stores all telemetry (executions, log_records, blocking_events, sessions) in one SQLite database with a single `source_tier` column (`app`/`framework`) used only for read-side filtering. Retention is uniform per table (7 days executions, 3 days logs). A size failsafe (500MB cap) deletes oldest rows by table priority — log_records first, then executions — but can't distinguish framework from app rows within a table. No sampling or aggregation exists; every execution is persisted 1:1. The result: 537k framework executions (90% of rows) from one internal listener fill the DB, the failsafe wipes logs down to 4 minutes of coverage, and the cycle repeats hourly.

## Patterns Found

### Pattern 1: Write-Path Filtering (Home Assistant Recorder)

**Used by**: Home Assistant `recorder` integration
**How it works**: Rather than recording everything and pruning later, HA lets the operator declare `include`/`exclude` rules (by domain, entity_id, or glob) evaluated at write time. Noisy, low-value entities never get a row written. This is configuration-driven and takes effect on reload.
**Strengths**: Zero storage cost for excluded data. Simple mental model. Immediately effective — prevents the row from ever existing rather than deleting it after the fact.
**Weaknesses**: Requires knowing in advance which sources are noisy (reactive, not automatic). Becomes an unmaintainable list as source count grows — HA's community repeatedly asks for the inverse "keep-list" model. Provides no record at all for excluded sources, which is a problem if that data is occasionally useful for debugging.
**Example**: https://www.home-assistant.io/integrations/recorder/

### Pattern 2: Tiered Retention with Aggregation/Downsampling (HA Long-Term Statistics, Prometheus + Thanos)

**Used by**: Home Assistant (recorder → long-term statistics), Prometheus + Thanos/Cortex/Mimir
**How it works**: Raw high-resolution data is kept for a short window (HA: 10 days default; Prometheus: 15 days). A decoupled background process periodically aggregates raw data into coarser summaries (HA: hourly statistics in a separate table set; Thanos: 5-min/1-hour resolution blocks) retained far longer at a fraction of the storage cost. The aggregation job runs asynchronously — ingestion is never blocked by compaction work.
**Strengths**: Preserves long-term trend visibility (counts, rates, latency percentiles) without raw row storage cost. Decouples retention policy per data class. Write throughput unaffected by compaction.
**Weaknesses**: Aggregation is lossy — individual anomalous events beyond the raw window are no longer inspectable. Requires a second schema (aggregate tables) and a scheduled job, which is nontrivial engineering compared to just deleting old rows.
**Example**: https://www.home-assistant.io/integrations/recorder/, https://thanos.io/tip/components/compact.md/

### Pattern 3: Anomaly-Prioritized Sampling (OpenTelemetry)

**Used by**: OpenTelemetry Collector (tail sampling processor), Grafana Labs (head sampling at extreme volume)
**How it works**: Sampling decisions based on whether a record is "interesting." Head-based sampling decides at operation start (cheap, blind to outcome) — used at extreme volumes where full tail buffering isn't tractable. Tail-based sampling waits until the operation completes, then applies policies: "keep 100% of errors, 100% of slow traces, X% of routine successes" — concentrating storage on records most likely to matter for debugging.
**Strengths**: Concentrates storage budget on failures and outliers rather than treating all records equally. Tail-based can dramatically cut volume while improving debuggability.
**Weaknesses**: Tail-based requires buffering all in-flight records until the decision window closes (memory cost proportional to concurrency). Head-based can drop the failure you needed. Both require the source to know what's "interesting" at write time.
**Example**: https://opentelemetry.io/blog/2022/tail-sampling/

### Pattern 4: Per-Table / Per-Source Row Caps — Ring Buffer Pattern

**Used by**: IoT telemetry systems on SQLite, edge observability architectures
**How it works**: Instead of a single global database-size cap, each table or logical data class gets its own fixed row-count or time-based cap, enforced independently. A periodic job runs per-table retention rather than global delete-oldest. Celery's `result_expires` TTL is the time-based cousin: results expire on their own schedule independent of other backend data.
**Strengths**: A noisy source can't crowd out a quiet-but-valuable source's budget. Directly solves the "537k framework rows evict 4-minutes-of-logs" failure mode by construction — logs and app executions keep their own guaranteed floor.
**Weaknesses**: Requires deciding budgets per table/tier up front. If budgets are set poorly, one tier can still fill up silently.
**Example**: https://www.sqliteforum.com/p/storing-iot-telemetry-streams-with

### Pattern 5: Single Dedicated Writer + Explicit Checkpointing (SQLite WAL Discipline)

**Used by**: General SQLite high-write guidance (phiresky's widely-cited tuning writeup), edge/IoT architectures
**How it works**: SQLite WAL can grow without bound if checkpoints can't keep pace with write rate. Fix: funnel all writes through a single dedicated writer task/queue, and explicitly force periodic checkpointing rather than relying on defaults.
**Strengths**: Prevents WAL bloat from compounding the row-count/size problem independently. Single writer simplifies write ordering and avoids lock contention.
**Weaknesses**: Requires architectural discipline; checkpoint tuning is per-deployment, not set-and-forget.
**Example**: https://phiresky.github.io/blog/2020/sqlite-performance-tuning/

## Anti-Patterns

- **Global size-cap with delete-oldest, no per-source distinction.** HA's own community routinely reports the DB filling from "one or two noisy entities" — the standard advice is always to exclude/tier at the source, never to purge harder globally. This is exactly hassette's current failsafe design.
- **Purging without repacking.** HA's docs note that purging rows does not shrink the on-disk file — a separate VACUUM/repack step is required, or the size cap keeps tripping. Hassette does run incremental vacuum during the size failsafe, but only 100 pages per iteration — likely insufficient for 500MB databases.
- **Retention inline with the write path.** Thanos runs its Compactor as a separate process so compaction never blocks ingestion. Doing retention enforcement synchronously during writes risks the indiscriminate emergency deletion hassette is seeing.
- **Treating all telemetry as equally durable.** Celery explicitly treats task results as a disposable cache with per-type TTL, not an audit log. A system that retains every framework-internal listener execution identically to user-triggered app executions has mismatched its durability stance with its data value.

## Relevance to Us

Hassette's current design hits **three of the four documented anti-patterns**: global size-cap with no per-source distinction, treating all telemetry as equally durable, and insufficient vacuum during the failsafe cycle. The fourth (retention inline with writes) is partially avoided — retention runs hourly in the serve loop, not per-write — but the size failsafe is still a reactive emergency mechanism rather than a preventive one.

The good news: hassette already has the `source_tier` column and the `RetentionTarget` priority system. The infrastructure for per-tier retention exists — it just isn't wired up. The `source_tier` field already threads through every telemetry model; it needs to become a retention discriminator, not just a read-side filter.

**Pattern alignment:**
- **Pattern 1 (write-path filtering)** maps directly to "don't record framework-tier state_proxy executions at all, or record only anomalies." Hassette already knows at write time whether an execution is `app` or `framework`. The simplest immediate fix.
- **Pattern 3 (anomaly-prioritized sampling)** is the sophisticated version of Pattern 1 — instead of blanket-excluding framework executions, keep errors and slow executions, sample the rest at a low rate. Hassette already has `status` and `duration_ms` at write time, so tail-sampling is feasible without buffering.
- **Pattern 4 (per-source row caps)** is the structural fix for the failsafe — replace the single 500MB cap with per-tier budgets so logs and app executions have guaranteed floors. Can coexist with the global cap as a last resort.
- **Pattern 2 (tiered retention with aggregation)** is the long-term play — roll up framework execution counts into hourly summaries for trend visibility, delete the raw rows. Higher engineering cost, but preserves the ability to answer "how many state changes per hour" without keeping 537k rows.

**What we don't need:**
- Pattern 5 (dedicated writer + checkpointing) — hassette already funnels writes through a single async writer queue via `CommandExecutor`. The WAL checkpoint could be tuned, but it's not the primary problem.

## Recommendation

**Immediate (fixes the acute problem):** Combine Pattern 1 + Pattern 4.
1. Add per-source-tier retention days to `DatabaseConfig` — e.g., `framework_retention_days: 1` vs the existing `retention_days: 7` for app-tier. Wire `RetentionTarget` to use tier-aware cutoffs.
2. For the `state_proxy.on_state_change` listener specifically, apply Pattern 3 at write time: persist only errors/slow executions, drop (or sample at ~1%) successful fast executions. This single listener is 90% of volume.
3. Give `log_records` a guaranteed retention floor independent of the size failsafe — either exempt it from the failsafe entirely (it's tiny) or give it a per-table row cap that the failsafe respects.

**Medium-term (prevents recurrence):** Add a nightly aggregation job (Pattern 2) that rolls framework execution counts into an hourly summary table before deleting the raw rows. This preserves trend data ("state changes per hour over the last 30 days") at ~0.1% of the storage cost.

**Not recommended now:** Write-path exclude lists (Pattern 1's HA-style config). The problem is structural (framework telemetry shouldn't be stored at raw granularity), not operational (the user forgot to add an exclude rule). Solve it in the framework, not in config.

## Sources

### Reference implementations
- https://www.home-assistant.io/integrations/recorder/ — HA recorder: include/exclude filters, purge_keep_days, long-term statistics
- https://thanos.io/tip/components/compact.md/ — Thanos Compactor: decoupled background retention/downsampling
- https://github.com/celery/celery/issues/6295 — Celery backend_cleanup: per-type TTL enforcement
- https://docs.celeryq.dev/en/stable/userguide/configuration.html — Celery result_expires configuration

### Blog posts & writeups
- https://www.vanwerkhoven.org/blog/2024/reduce-home-assistant-database-size/ — Diagnosing noisy HA entities
- https://szimnau.dk/en/blog/ha-recorder-database-optimization/ — HA recorder optimization methodology
- https://edvoncken.net/2025/01/reduce-homeassistant-database/ — HA database engine migration path
- https://phiresky.github.io/blog/2020/sqlite-performance-tuning/ — SQLite WAL/performance tuning
- https://www.gouthamve.dev/sampling-at-scale-with-opentelemetry/ — Grafana's head-sampling at scale
- https://advt3.com/posts/edge_computing_observability/ — Edge-native observability budgeting
- https://www.sqliteforum.com/p/storing-iot-telemetry-streams-with — SQLite ring-buffer pattern for IoT

### Documentation & standards
- https://opentelemetry.io/blog/2022/tail-sampling/ — OpenTelemetry tail sampling
- https://uptrace.dev/opentelemetry/sampling — OpenTelemetry sampling overview
- https://signoz.io/guides/edge-observability/ — Edge observability patterns
- https://last9.io/blog/prometheus-vs-thanos/ — Prometheus vs Thanos retention tiers

### Community discussions
- https://community.home-assistant.io/t/recorder-entity-purge-for-all-entities-with-exemptions/834826 — HA community: default-deny retention model
- https://community.home-assistant.io/t/how-to-keep-your-recorder-database-size-under-control/295795 — HA community: recorder size control guide
