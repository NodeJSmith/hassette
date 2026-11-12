---
topic: "Flush lifecycle of batched, best-effort telemetry recorders"
date: 2026-11-12
status: Draft
---

# Prior Art: Flush Lifecycle of Batched, Best-Effort Telemetry Recorders

## The Problem

Hassette's listener near-miss recorder (spec 151) aggregates per-listener drop counts in memory and writes them to SQLite every 30 s, plus once at shutdown. Each review round on PR #4013 has patched how the batch is handed off: swap ordering, cancellation counting, merge-back retry, shutdown ordering, lifecycle tests, loss docs. The latest round still finds three problems. A periodic flush that is in flight during shutdown, combined with merge-back retry, can lose a batch without counting it. Retries make the documented "visible within 30 s, a crash loses at most 30 s" bound false. And the lifecycle tests can't observe the periodic and final flushes overlapping.

The question is whether comparable recorders guard against these failure modes, and with how much machinery.

## How We Do It Today

- **Recording.** `ListenerMissRecorder.record` mutates `self.entries` without awaiting. `flush` swaps the map out atomically (`listener_miss_recorder.py:167`), so after the swap only the flush's local variable holds the batch.
- **Two callers.** `run_flush_loop` (spawned in `BusService.on_initialize`, `bus_service.py:697`) flushes every 30 s. `BusService.on_shutdown` separately calls `flush(final=True)` after dispatch drains, and nothing stops or awaits the loop first. The two flushes can overlap, and they share an unguarded `retries` counter.
- **Failure.** A retryable failure (`TimeoutError`/`OperationalError`) merges the batch back into `self.entries`. After 3 consecutive failures, or on the final flush, the batch is counted as lost under `LISTENER_MISS_FLUSH_FAILED`. Cancellation mid-write counts it lost too.
- **The in-repo contrast.** The execution-telemetry flusher (`CommandExecutor.serve`, `command_executor.py:195-254`) is a single loop that runs `flush_queue` itself on shutdown, so its periodic and final flushes cannot overlap. Its retries are per batch inside that one owner (`RetryableBatch`, `execution_pipeline.py:312-362`).

## Patterns Found

### Pattern 1: One owner for flushes; shutdown signals it and joins

**Used by**: OpenTelemetry `BatchProcessor` and `PeriodicExportingMetricReader`, stdlib `QueueListener`, Home Assistant recorder, Sentry `BackgroundWorker`

**How it works**: A stop event, or a sentinel or `StopTask` in the same queue, wakes the single worker. The worker leaves its periodic loop and runs the final flush itself; the closer then joins it, with a timeout where the flush does I/O. The final flush is the same code path as the periodic one, so two flushes never run at once. HA's periodic commit doesn't even run on a timer: the timer enqueues a `COMMIT_TASK` onto the recorder thread's queue.

**Strengths**: No overlap race by construction, and a single place for the swap and the error handling.

**Weaknesses**: The join needs a timeout, or a hung write blocks shutdown (OTel sets `_shutdown_timeout_exceeded` and abandons the rest). If the worker has died, nothing drains.

**Example**: OTel `_ticker`: `while not shutdown_event.wait(interval): collect()`, then one last `collect()`. `shutdown()`: `event.set(); thread.join(timeout)`.

**Read**: OTel `sdk/metrics/_internal/export/__init__.py` L597-646 and `sdk/_shared_internal/__init__.py` (worker, shutdown); stdlib `QueueListener.stop`; HA `recorder/core.py` L478-484, L811-830; Sentry `worker.py` L102-160.

### Pattern 2: Serialize the rare extra flusher with a lock, and re-check after acquiring

**Used by**: OTel `BatchProcessor._export` / `force_flush`, `PeriodicExportingMetricReader._receive_metrics`

**How it works**: When a second caller can legitimately flush (`force_flush`), both callers go through `with self._export_lock:`, and whichever arrives second re-checks whether anything is left to export. The second caller waits rather than skipping.

**Strengths**: An extra flush can neither be a silent no-op nor run at the same time as the worker's.

**Weaknesses**: The caller blocks for as long as the in-flight export takes.

**Read**: OTel `_shared_internal/__init__.py` `_export` (comment: "We could see concurrent export calls from worker and force_flush").

### Pattern 3: Swap, then write; the writer owns the batch and never restores it

**Used by**: OTel (pops the batch before `export`), Sentry client-report counters, datadog `ThreadStats` aggregators

**How it works**: Take the pending data, replace it with an empty structure, and write the taken data outside any lock so producers never wait on I/O.

**Strengths**: Each datum is in exactly one place at any time.

**Weaknesses**: Between the swap and the end of the write, only a local variable holds the data, so loss accounting belongs on the write's failure path. Hassette already does this.

**Read**: Sentry `transport.py` L433-460; datadog `threadstats/base.py` L419-457; OTel `_export`.

### Pattern 4: On failure, drop the batch and (sometimes) count it; don't merge it back

**Used by**: OTel (logs; counts queue overflow via `drop_items`), Sentry (logs, plus a `network_error`/`send_error` client report), datadog `ThreadStats` (logs only), stdlib logging (`handleError`)

**How it works**: The flush boundary catches the write's exception, logs it, and discards the batch. Sentry also increments a per-(category, reason) loss counter, and its spec says that counter is itself best-effort.

**Strengths**: The loss bound stays true: a datum is written in the interval it was swapped, or lost in that interval. Nothing grows without bound while the backend is down, and nothing gets double-counted.

**Weaknesses**: A transient failure loses a whole interval.

**Example**: OTel spec: "The default SDK's Span Processors SHOULD NOT implement retry logic." Sentry spec: the party that drops an item "MUST record and report it"; client reports "do not expect 100 percent correct numbers".

**Read**: OTel trace SDK spec; OTel `_export` except block; Sentry `transport.py` `_handle_request_error`; Sentry client-reports spec.

### Pattern 5: Retry only inside the single owner, on the same data, with a cap

**Used by**: HA recorder (`_commit_event_session_or_retry`, 10 tries at 3 s), datadog dogstatsd background sender (backoff, stale-drop, 60 s shutdown grace)

**How it works**: The retry happens inside the one owner, below the flush boundary, and blocks that owner. HA's pending rows stay in the open SQLAlchemy session. When retries run out, it rolls back and reopens the session, which drops the batch and logs it.

**Strengths**: No state crosses flushes, so shutdown can't race a retry.

**Weaknesses**: Visibility and crash loss become the interval plus the retry budget, and shutdown can wait out a full retry budget unless that wait is capped.

**Read**: HA `recorder/core.py` L1248-1269, L1317-1323; datadog `dogstatsd/base.py` L185-200, L518-530 (constants and docstrings only).

### Pattern 6: Document the interval, not a hard loss bound

**Used by**: HA (`commit_interval`, with advice on the I/O trade-off), OTel (`scheduledDelayMillis` only), Sentry ("best-effort", "acceptable to lose"), stdlib (the `stop()` docstring warns that unflushed records are lost)

**How it works**: None of these docs promise "visible within N s" once failures are in play.

## Anti-Patterns

- **A skip-if-in-flight flag plus a separate shutdown flush** (datadogpy `ThreadStats`, `threadstats/base.py` L366-417). An `atexit` flush that arrives during a periodic flush is silently skipped, the flag is an unlocked bool, and `stop()` neither joins the thread nor does a final flush. This is the same shape as hassette's race.
- **Merge-back retry across flushes while a second flusher exists.** No peer does this. The two that retry (HA, dogstatsd) retry inside a single owner. Merging back requires the shutdown path to know about batches that are neither pending nor written, which is exactly the window for uncounted loss. [no source found for a peer that merges a failed batch back into a live aggregator]

## Gaps

- NetDaemon and AppDaemon weren't opened; neither is known to have a comparable batched recorder.
- The HA docs have no explicit crash-loss sentence, and the HA shutdown join had no visible timeout in the lines read.
- datadog's `_sender_main_loop` and the OTLP exporters' retry code weren't read end to end.
- The Sentry offline-caching spec was seen only as a search snippet.

## Relevance to Us

Hassette's recorder combines the two shapes no peer uses: separate periodic and final flushers (the datadogpy anti-pattern, minus the skip flag), and a merge-back retry that crosses flushes. Every open finding in this convergence comes from that combination.

Hassette's own `CommandExecutor.serve` already follows Pattern 1 (one loop that does its own final flush) with Pattern 5 retry inside it. The recorder is the outlier in its own codebase. The fixes applied in earlier rounds (cancel counting, merge-back, a shared retry counter) add machinery that peers avoid by having one owner.

## Recommendation

Restructure the recorder around Pattern 1 combined with Pattern 4:

- **One flush owner.** `run_flush_loop` waits on a stop event with a 30 s timeout. When the event is set, it leaves the loop and runs the final flush itself. `BusService.on_shutdown` sets the event (after dispatch drains) and awaits the loop task with a timeout. That removes the overlap race, the shared `retries` state, and the need for a lifecycle test that can observe overlap.
- **Drop and count on failure; no merge-back.** This is near-miss telemetry, best-effort by design. OTel's spec says its batching layer shouldn't retry, and Sentry accepts approximate loss counts. Dropping makes the documented bound true again.
- **Docs: state the interval and that a failed write drops that interval's counts**, which `LISTENER_MISS_FLUSH_FAILED` counts. Don't promise a hard bound beyond that.

If you want to keep retry, put it inside the single owner as Pattern 5, with a cap: a retry on the same local batch within the same flush call, or a per-batch retry the way `CommandExecutor` does it. The docs' bound then becomes the interval plus the retry budget. Either way, merge-back into shared pending state should go.

## Sources

### Reference implementations
- https://github.com/home-assistant/core/blob/dev/homeassistant/components/recorder/core.py — HA recorder: a single thread, commit as a queued task, StopTask plus join, capped commit retry
- https://github.com/open-telemetry/opentelemetry-python/blob/main/opentelemetry-sdk/src/opentelemetry/sdk/_shared_internal/__init__.py — OTel BatchProcessor: the worker does the final export, `_export_lock`, drops on failure
- https://github.com/open-telemetry/opentelemetry-python/blob/main/opentelemetry-sdk/src/opentelemetry/sdk/metrics/_internal/export/__init__.py — OTel PeriodicExportingMetricReader: "one last collection" in the ticker
- https://github.com/getsentry/sentry-python/blob/master/sentry_sdk/worker.py — Sentry BackgroundWorker: flush waits for the single worker to drain
- https://github.com/DataDog/datadogpy/blob/master/datadog/threadstats/base.py — datadog ThreadStats: the skip-if-in-flight anti-pattern
- https://github.com/DataDog/datadogpy/blob/master/datadog/dogstatsd/base.py — dogstatsd sender: bounded retry with a shutdown grace period

### Documentation & standards
- https://opentelemetry.io/docs/specs/otel/trace/sdk/ — OTel trace SDK spec: processors SHOULD NOT retry; exports are serialized
- https://develop.sentry.dev/sdk/telemetry/client-reports/ — Sentry client reports: drop-and-count, best-effort counts
- https://develop.sentry.dev/sdk/foundations/transport/offline-caching/ — Sentry offline caching: opt-in, capped retry (not opened)
- https://docs.python.org/3/library/logging.handlers.html — stdlib QueueListener `stop()` semantics
- https://www.home-assistant.io/integrations/recorder/ — HA `commit_interval` docs
- https://github.com/home-assistant/core/pull/86115 — HA's default commit interval raised to 5 s (not opened)
