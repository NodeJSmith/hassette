---
topic: "Grouping stack-carrying events into findings at read time"
date: 2026-10-02
status: Draft
---

# Prior Art: Grouping stack-carrying events into findings

## The Problem

Blocking-IO events are stored one row per event, each carrying its stack. The UI needs one finding per call site, with counts that are exact. Deciding which frame is "app code" depends on server state (configured app dirs, interpreter prefixes) that can change between restarts.

## How We Do It Today

`blocking_queries.py` fetches the newest 1000 rows. `blocking_findings.group_findings` decodes and classifies each row in Python on the event loop. A chronic call site fills the cap, so older call sites disappear and counts are wrong. Grouping measured about 540 ms per capped read.

## Patterns Found

### Pattern 1: Fingerprint at ingest, store it, version the rules
**Used by**: Sentry.
**How it works**: Each event gets a fingerprint when it is ingested, and in-app classification is one of its inputs. Rule changes ship as dated grouping configs that apply only to new events. Old groups are fixed manually with merge/unmerge.
**Strengths**: The read path is a plain GROUP BY on an indexed column. Counts are exact.
**Weaknesses**: Old events stay in old groups after a rule change. It needs a rule-version column.
**Example**: https://docs.sentry.io/concepts/data-management/event-grouping/

### Pattern 2: Aggregate distinct stacks, interpret at read time
**Used by**: Folded-stack tools (py-spy output, inferno), Datadog profiler, Pyroscope.
**How it works**: Samples collapse into exact `{stack -> count}` pairs first. Interpretation is a pass over the distinct stacks only.
**Strengths**: Rules can change freely. Cost scales with distinct stacks, not events. Counts are lossless.
**Weaknesses**: Cost still grows with stack cardinality. These tools interpret symbols, not mutable in-app rules.
**Example**: https://docs.rs/inferno/0.6.0 ; https://datadoghq.com/blog/engineering/dotnet-continuous-profiler

### Pattern 3: Threads for blocking I/O; processes for CPU-bound work
**Used by**: Starlette/FastAPI (`run_in_threadpool`), the asyncio `run_in_executor` idiom.
**How it works**: The thread pool exists for blocking I/O and for C code that releases the GIL. Pure-Python CPU work holds the GIL, so a thread hides the cost rather than removing it. The loop still gets turns at the ~5 ms switch interval.
**Strengths**: One line. Acceptable for short, bounded bursts.
**Weaknesses**: Total CPU is unchanged, and it adds GIL contention.
**Example**: https://dev.to/r9v/one-blocking-call-freezes-every-request-fastapis-def-vs-async-def-52lh

## Anti-Patterns

- **Capping rows before grouping.** None of the surveyed tools do this. They aggregate over everything and cap the number of groups. [inferred; no source states it outright]
- **Treating a thread as a CPU-cost fix.** It hides the work instead of removing it.

## Relevance to Us

Option A is Pattern 2 with read-time in-app classification layered on. That keeps D2 (classify at read time, so config changes apply retroactively), which Sentry gives up. No source names this exact combination, but each half is well established. SQLite can GROUP BY the `frames` text directly, so a stored stack digest (the hybrid) isn't needed at this scale.

## Recommendation

Use A (SQL aggregate per distinct stack, cap the groups) plus B (memoize filename classification per request). Together they remove the miscounts and most of the CPU work. Treat C as a separate question. A thread doesn't cut the CPU work, but it does bound how long the loop is held: the loop gets a turn about every 5 ms instead of waiting out the whole computation. Decide on C by measuring the A+B cost against the watchdog's 100 ms threshold. Don't move to Pattern 1: it gives up retroactive reclassification, which D2 chose deliberately.

## Sources

### Reference implementations
- https://docs.rs/inferno/0.6.0 — folded-stack aggregation

### Blog posts & writeups
- https://datadoghq.com/blog/engineering/dotnet-continuous-profiler — identical stacks summed into one sample
- https://dev.to/r9v/one-blocking-call-freezes-every-request-fastapis-def-vs-async-def-52lh — threads vs processes for CPU work
- https://rushter.com/blog/python-gil-thread-scheduling/ — GIL switch interval

### Documentation & standards
- https://docs.sentry.io/concepts/data-management/event-grouping/ — ingest-time fingerprinting
- https://docs.sentry.io/concepts/data-management/event-grouping/merging-issues/ — merge/unmerge after rule changes
