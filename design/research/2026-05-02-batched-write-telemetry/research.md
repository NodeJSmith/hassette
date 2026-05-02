---
topic: "batched write and command queue patterns for telemetry"
date: 2026-05-02
status: Draft
---

# Prior Art: Batched Write and Command Queue Patterns for Telemetry

## The Problem

High-frequency telemetry (handler invocations, job executions) must be persisted to a database without blocking the instrumented application. The write path must handle sustained load (hundreds of events/second), transient database failures (locked, I/O stalls), and resource exhaustion — all without stalling event dispatch or losing data silently. The design space spans: queue sizing, overflow policies (drop vs. block vs. sample), batch sizing, retry strategies, and how to make data loss observable.

## How We Do It Today

Hassette's `CommandExecutor` uses a bounded `asyncio.Queue(maxsize=1000)` with non-blocking enqueue (`put_nowait()`). A background `serve()` loop drains up to 100 items per batch. On `OperationalError`, batches are re-enqueued up to 3 times before being dropped (incrementing `_dropped_exhausted`). Queue-full drops increment `_dropped_overflow`. A 75% capacity warning logs at a rate-limited 30s interval. FK violations get row-by-row fallback with nullable FK fields.

Key design choice: **never block producers**. Event dispatch proceeds regardless of queue state. Data loss is tracked via counters but not propagated as backpressure.

## Patterns Found

### Pattern 1: Bounded In-Memory Queue with Silent Drop

**Used by**: OpenTelemetry BatchSpanProcessor, Datadog agents, New Relic agents

**How it works**: A bounded in-memory queue (OTel default: 2048 items) accepts telemetry records via non-blocking enqueue. When full, new records are silently dropped. A background thread/task exports batches on either a count threshold (OTel: 512 spans) or a time interval (OTel: 5000ms), whichever triggers first. A preemptive flush at 50% capacity prevents burst-induced drops.

The queue uses `collections.deque` with maxlen or explicit size checks. Drop policy is always "drop newest" (the incoming record) — existing queued records are preserved because they represent earlier, potentially more valuable context.

**Strengths**: Never blocks the application. Predictable memory usage. Simple implementation. Drop behavior is deterministic and bounded.

**Weaknesses**: Silent data loss under sustained overload. No feedback to producers. Lost spans/metrics are irrecoverable. Quality of dropped data is random (newest may be the most relevant for debugging).

**Example**: https://opentelemetry.io/docs/specs/otel/trace/sdk/

### Pattern 2: Dual-Trigger Flush (Count OR Time)

**Used by**: OpenTelemetry, Elastic APM, Datadog, virtually all batched telemetry systems

**How it works**: The batch exporter flushes when EITHER the batch reaches a size threshold OR a timer expires — whichever comes first. Under high load, size-based flushes dominate (maximizing throughput). Under low load, time-based flushes ensure records don't wait too long (bounded latency).

OTel defaults: max batch size 512 spans, scheduled delay 5000ms. These are configurable per deployment. The timer resets after each flush regardless of trigger source.

**Strengths**: Adapts automatically to load without configuration. High throughput under load (large batches amortize I/O). Bounded latency under low load (timer forces flush). Universal pattern — proven across dozens of implementations.

**Weaknesses**: Choosing defaults requires understanding typical load patterns. Too-large batches can cause memory pressure. Timer-based flushes under low load mean records sit in memory until the interval.

**Example**: https://opentelemetry-python.readthedocs.io/en/latest/sdk/trace.export.html

### Pattern 3: Export Retry with Exponential Backoff

**Used by**: OpenTelemetry, Elastic APM, all telemetry exporters

**How it works**: Failed exports are retried with exponential backoff and jitter. Maximum retry count is bounded (typically 3-5 attempts). Non-retryable errors (4xx status, data format errors) are dropped immediately. Retryable errors (5xx, timeouts, connection refused) trigger the retry sequence. Between retries, new records continue accumulating in the queue.

The key distinction: **transient** errors (locked database, network blip) vs. **permanent** errors (schema mismatch, constraint violation). Only transient errors get retries.

**Strengths**: Recovers from transient failures without manual intervention. Bounded attempts prevent infinite resource consumption. Jitter prevents thundering herd on recovery. Clear error classification enables appropriate responses.

**Weaknesses**: During retry backoff, queue fills faster (no drain). Requeued batches compete with fresh records for queue space. Multiple retry attempts for the same batch consume CPU/IO budget.

**Example**: https://opentelemetry.io/docs/collector/resiliency/

### Pattern 4: Graduated Backpressure (Reduce Before Dropping)

**Used by**: Elastic APM agents, some Datadog implementations

**How it works**: Rather than binary full/not-full, the system degrades gracefully through multiple thresholds. At 50% capacity: preemptive flush. At 75%: reduce sampling rate (collect every Nth event). At 90%: drop all but errors/failures. At 100%: drop everything. This preserves the highest-value telemetry (errors, slow operations) even under extreme load.

Elastic APM agents receive explicit "queue is full" signals from the server (503 responses) and reduce their recording rate in response, independent of local queue state.

**Strengths**: Preserves high-value data under overload. Degradation is visible and proportional. Better debugging experience than random drops. Error telemetry survives longest.

**Weaknesses**: More complex implementation. Sampling decisions must be made at enqueue time (before the record reaches the queue). Requires priority classification of telemetry records.

**Example**: https://github.com/elastic/apm-agent-java/issues/798

### Pattern 5: Ring Buffer / Drop Oldest

**Used by**: OTel tail sampling, Linux kernel trace buffers (ftrace), some metrics systems

**How it works**: A fixed-size circular buffer overwrites the oldest records when full. The most recent N records are always available. No blocking, no explicit drop decisions — the write pointer simply advances, overwriting old data.

This inverts the "drop newest" policy: under sustained overload, you always have the most recent data (useful for "what just happened?") but lose historical context.

**Strengths**: Constant memory. Most recent data always preserved. Zero decision overhead at write time. No explicit overflow handling needed.

**Weaknesses**: Historical data silently evicted. Cannot guarantee retention of any specific record. Bad for debugging rare events that happened in the past. Counter-intuitive when users expect "all errors are preserved."

**Example**: [no source found — kernel pattern, not commonly in Python telemetry]

### Pattern 6: Meta-Telemetry (Instrument the Telemetry System)

**Used by**: Datadog (bytes_dropped, datagrams_dropped metrics), OpenTelemetry (otel.sdk.dropped_spans), Vector

**How it works**: The telemetry write path itself emits metrics about its own health: queue fill percentage, records dropped (by reason), batch export latency, retry count, export failures. These meta-metrics use a separate, lightweight channel that bypasses the main pipeline.

Datadog's DogStatsD client tracks `bytes_dropped` and `datagrams_dropped` as histograms. Vector exposes `component_discarded_events_total` with labels for component and reason.

**Strengths**: Data loss becomes observable and alertable. Operators can tune queue sizes based on actual fill rates. Differentiates overflow drops from error drops from shutdown drops. Enables capacity planning.

**Weaknesses**: Meta-telemetry itself needs a reliable path (can't use the same pipeline it's monitoring). Adds complexity. Must not contribute to the overload it's monitoring.

**Example**: https://docs.datadoghq.com/developers/dogstatsd/high_throughput/

### Pattern 7: Persistent Queue (File-Backed Storage)

**Used by**: OpenTelemetry Collector, Vector, Fluentd

**How it works**: The in-memory queue is replaced by or backed by persistent storage (bbolt, LevelDB, WAL file). Records survive process restarts. Queue size is measured in batches rather than individual records. The persistent queue acts as both buffer and WAL — if the process crashes, unexported records are recovered on restart.

OTel Collector's persistent queue uses bbolt (embedded key-value store) with configurable queue_size (default: 1000 batches). This replaces the in-memory `chan` entirely rather than augmenting it.

**Strengths**: Crash durability. No data loss on restart. Can buffer far more than memory allows. Enables offline/disconnected operation.

**Weaknesses**: Write latency increases (disk I/O on every enqueue). More complex failure modes (corrupted WAL, disk full). Recovery on startup adds delay. Overkill for embedded databases where the write target is already on disk.

**Example**: https://opentelemetry.io/docs/collector/resiliency/

## Anti-Patterns

- **Multi-Stage Unsynchronized Buffers**: Multiple independent buffers in a pipeline (one per component) create uncoordinated backpressure — the second buffer fills while the first has spare capacity, causing unnecessary drops. The OTel community is consolidating toward single-queue architectures. Source: https://www.dash0.com/blog/why-the-opentelemetry-batch-processor-is-going-away-eventually

- **Silent Drops Without Observability**: Dropping records without tracking or exposing the drop count makes data loss invisible. Operators cannot tune configuration or diagnose missing telemetry. Every drop must increment a counter. Source: https://docs.datadoghq.com/developers/dogstatsd/high_throughput/

- **Blocking the Producer Under Any Circumstance**: Telemetry should never block the instrumented application. A full telemetry queue causing production latency is worse than lost telemetry. The principle: degrade observability before degrading availability. Source: https://www.observability.how/p/scaling-observability-designing-a-high-volume-telemetry-pipeline-part-3

- **Unbounded Retry Without Backoff or Budget**: Retrying failed exports without exponential backoff creates thundering herd on recovery. Retrying without a maximum attempt count consumes resources indefinitely. Both bounds are required.

## Emerging Trends

- **Single Durable Queue Over Multi-Buffer Pipelines**: OTel is moving batching into exporters backed by persistent storage, collapsing multiple unsynchronized buffers into a single write path. Simpler architecture, coordinated backpressure, crash durability in one mechanism.

- **Configurable Per-Sink Overflow Policy**: Vector and similar tools let operators choose `when_full: drop_newest | block` per sink. The "right" policy depends on the downstream — some sinks can handle blocking (local file), others cannot (real-time dashboards).

## Relevance to Us

Hassette's CommandExecutor is a solid implementation of **Pattern 1 (Bounded Queue + Silent Drop)** with elements of **Pattern 3 (Retry with bounded attempts)**. Comparing against industry standards:

**What we do well:**
- Non-blocking enqueue (critical — never stalls event dispatch)
- Bounded queue (1000 records)
- Bounded retries (3 attempts for OperationalError)
- Error classification (retryable OperationalError vs. non-retryable IntegrityError vs. DataError)
- Drop counters per category (overflow, exhausted, no_session)
- FK violation fallback (row-by-row with nullable FK)

**Gaps compared to best practice:**

1. **No dual-trigger flush** — we drain on-demand (blocking `queue.get()`) rather than using size OR time triggers. Under low load this is fine (drain happens immediately when a record arrives). But there's no time-based guarantee that records flush within N seconds of enqueue.

2. **No graduated backpressure** (Pattern 4) — we go from "accept everything" to "drop" at 100% capacity. The 75% warning log is passive. Consider: at 75%, stop persisting framework-tier invocations (keep only app-tier). At 90%, stop persisting successful invocations (keep only errors).

3. **Meta-telemetry not exposed via API** — drop counters exist (`_dropped_overflow`, `_dropped_exhausted`, `_dropped_no_session`) but are only visible in session records at shutdown. They should be queryable in real-time for the dashboard and alertable.

4. **No backoff between retries** — requeued batches are immediately eligible for the next drain cycle. Under sustained DB pressure, this means rapid retry → fail → retry without letting the DB recover. A brief sleep or priority reduction after requeue would help.

5. **Batch size is items-from-queue, not records** — a RetryableBatch counts as 1 item but may contain a full prior batch. Under retry pressure, a single drain cycle could process 1 fresh record + 99 retry batches (each containing 100 records), creating a burst of 9,900+ record writes in one transaction.

## Recommendation

The CommandExecutor is well-designed for hassette's typical load (home automation telemetry is low-to-moderate frequency). The most impactful improvements:

1. **Expose drop counters via the web API and dashboard** — meta-telemetry is the highest-value addition. Users should see "12 records dropped in the last hour due to queue overflow" on the dashboard, not discover it in logs after the fact.

2. **Add graduated priority dropping** — at 80% capacity, stop persisting successful framework-tier invocations. At 90%, stop persisting successful app-tier invocations. Always persist errors regardless of queue state. This preserves debugging data under load.

3. **Add retry backoff** — after requeuing a failed batch, mark it with a `not_before` timestamp (e.g., current_time + 1 second × retry_count). Skip it in the drain loop until that time passes.

4. **Consider dual-trigger flush** — lower priority since the current `queue.get()` blocking approach means immediate processing anyway. Only matters if batch writes are consolidated in the future.

## Sources

### Standards & specifications
- https://opentelemetry.io/docs/specs/otel/trace/sdk/ — OTel BatchSpanProcessor specification
- https://opentelemetry-python.readthedocs.io/en/latest/sdk/trace.export.html — OTel Python SDK batch processor
- https://opentelemetry.io/docs/collector/resiliency/ — OTel Collector persistent queue

### Blog posts & design guides
- https://www.dash0.com/blog/why-the-opentelemetry-batch-processor-is-going-away-eventually — OTel batch processor consolidation
- https://www.observability.how/p/scaling-observability-designing-a-high-volume-telemetry-pipeline-part-3 — High-volume telemetry pipeline design
- https://docs.datadoghq.com/developers/dogstatsd/high_throughput/ — Datadog meta-telemetry and overflow

### Reference implementations
- https://github.com/elastic/apm-agent-java/issues/798 — Elastic APM graduated backpressure
- https://github.com/elastic/apm-server/issues/13403 — Elastic APM server-side circuit breaking
