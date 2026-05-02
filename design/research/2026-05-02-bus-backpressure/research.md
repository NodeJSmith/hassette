---
topic: "system-level backpressure for event bus pub/sub"
date: 2026-05-02
status: Draft
---

# Prior Art: System-Level Backpressure for Event Bus Pub/Sub

## The Problem

An in-process event bus dispatching to async handlers faces a fundamental tension: events arrive from external sources (HA WebSocket) at rates the framework cannot control, but handlers have bounded processing capacity. Without system-level backpressure, an event flood spawns unbounded concurrent tasks — consuming memory, starving the event loop, and potentially crashing the process. Per-listener throttle/debounce helps individual handlers but doesn't protect the system as a whole.

The design space: where do you put the bound (channel, dispatch, per-handler), what overflow policy do you use (block, drop, sample), and how do you make the tradeoff between event completeness and system stability?

## How We Do It Today

Hassette's event flow has one backpressure point and one unbounded fan-out:

**Bounded channel** (EventStreamService): anyio `MemoryObjectSendStream` with configurable buffer (default 1000 events). When full, **senders block** — this is the only system-level backpressure mechanism. The WebSocket reader can't push faster than the bus can drain.

**Unbounded dispatch fan-out** (BusService): When an event arrives, `dispatch()` spawns one task per matched listener via `task_bucket.spawn()`. No limit on concurrent dispatch tasks. Under a flood with many listeners, task count grows without bound.

**Per-listener rate limiting** (RateLimiter): Throttle and debounce are per-listener, limiting how often a specific handler fires. But the dispatch task is already spawned before the rate limiter runs — so system resources are consumed even for throttled events.

**No event dropping**: The system never drops events — it blocks producers (the WebSocket reader) when the channel is full. This means HA event delivery stalls, which could cause missed events at the HA side if the WS buffer fills.

## Patterns Found

### Pattern 1: Consumer-Driven Demand (Pull-Based / Reactive Streams)

**Used by**: Reactive Streams (JVM), RxJava, Project Reactor, Kafka consumer groups

**How it works**: The consumer signals how many items it can handle via `request(n)`. The publisher never sends more than requested. If the consumer is slow, the publisher naturally pauses. Demand accumulates — a `request(5)` followed by `request(3)` means 8 items can be sent.

Kafka implements this at partition level: `pause(partitions)` stops fetching while maintaining group membership. `resume(partitions)` when the consumer's queue drops below threshold. Heartbeating continues during pause — no rebalance.

**Strengths**: Lossless (no drops). Producer naturally pauses when consumer can't keep up. Demand signals are composable (intermediate operators propagate demand). No buffer overflow possible.

**Weaknesses**: Requires protocol support from both sides. Not applicable when the source is external and uncontrollable (e.g., HA WebSocket — can't tell HA to slow down). Adds complexity to the event delivery protocol.

**Example**: https://github.com/reactive-streams/reactive-streams-jvm

### Pattern 2: Bounded Buffer with Configurable Overflow Strategy

**Used by**: AnyIO MemoryObjectStream, asyncio.Queue, RxJava operators, ZeroMQ high-water marks

**How it works**: A bounded buffer between producer and consumer provides multiple overflow strategies: **block** (producer waits — the default), **drop newest** (discard incoming), **drop oldest** (evict head of queue), **error** (signal failure to producer), or **keep latest** (buffer of 1, always holds most recent).

ZeroMQ's high-water mark (HWM) is configurable per-socket with default of 1000 messages. When reached, behavior depends on socket type: PUB drops, PUSH/DEALER blocks.

AnyIO's MemoryObjectStream blocks the sender when the buffer is full — this is hassette's current approach.

**Strengths**: Simple to reason about. Configurable per use case. Bounded memory. Clear semantics for each strategy.

**Weaknesses**: One policy doesn't fit all subscribers. "Block" propagates to the source (may stall the WS reader). "Drop" loses data. Choosing the right buffer size requires understanding load patterns.

**Example**: https://anyio.readthedocs.io/en/stable/streams.html

### Pattern 3: Sampling / Throttling (Lossy Rate Reduction)

**Used by**: RxJS (sample, throttle, debounce operators), Prometheus (sample rate), statsd

**How it works**: Under load, reduce the event rate by keeping only a sample: every Nth event (count-based), one per time window (time-based), or probabilistic (random with configurable rate). The reduction happens before dispatch, preventing task spawning for dropped events.

RxJS's `sample(interval)` emits only the most recent value within each interval. `throttleTime(ms)` emits the first value then ignores for the duration. These are per-stream operators, not per-subscriber.

**Strengths**: Bounds consumer cost regardless of source rate. Preserves "most recent" data for state-like streams. No buffer needed (stateless reduction). Minimal overhead.

**Weaknesses**: Lossy — events are permanently discarded. Inappropriate for events where every occurrence matters (errors, state changes). Sampling is random — may miss important events. Cannot be applied uniformly to all event types.

**Example**: https://reactivex.io/documentation/operators/backpressure.html

### Pattern 4: Slow Consumer Detection and Disconnection

**Used by**: NATS (pending limits), ZeroMQ (sequence gap detection), Kafka (consumer lag alerts)

**How it works**: The system monitors per-consumer message backlog. When a consumer exceeds configurable pending limits (NATS: 65536 messages / 64MB), the system takes action: drop messages for that consumer, disconnect it, or alert. The key insight: a slow consumer shouldn't penalize other consumers or the system.

NATS's approach: each subscription has pending message/byte limits. Exceeding them triggers message drops and an error callback. The server may disconnect persistently slow consumers entirely.

**Strengths**: Isolates slow consumers from affecting others. Prevents unbounded memory growth per subscription. Observable (the system knows who's slow). Proportional response (warn → drop → disconnect).

**Weaknesses**: Disconnection can lose important events for the slow consumer. Tuning pending limits requires understanding normal operation. Re-connection storms after mass disconnection.

**Example**: https://docs.nats.io/running-a-nats-service/nats_admin/slow_consumers

### Pattern 5: Blocking Producer (True Backpressure via Bounded Channel)

**Used by**: asyncio.Queue(maxsize), AnyIO MemoryObjectStream, Go channels, Kafka pause/resume

**How it works**: The channel between producer and consumer has a fixed capacity. When full, the producer blocks (async: awaits) until space is available. This propagates backpressure naturally: if all consumers are slow, the channel fills, and the producer pauses.

This is hassette's current primary mechanism. The WebSocket reader blocks on `send_event()` when the bus can't keep up, naturally throttling the HA event intake.

**Strengths**: Simplest correct pattern. Lossless. Natural backpressure propagation. No configuration beyond buffer size. Provably bounded memory.

**Weaknesses**: Blocking propagates all the way to the source — if the WS reader stalls, HA may time out the connection or buffer events on its side (potentially losing them). A single slow consumer blocks ALL event delivery (head-of-line blocking). No differentiation between event priorities.

**Example**: https://docs.python.org/3/library/asyncio-queue.html

### Pattern 6: Per-Subscription Policy Configuration

**Used by**: ZeroMQ (per-socket HWM), RxJava (per-subscriber backpressure strategy), NATS JetStream (per-consumer policy)

**How it works**: Different consumers get different overflow policies based on their characteristics. A critical error handler gets "never drop" (block or buffer). A metrics aggregator gets "keep latest" (always see current, OK to miss intermediate). A logger gets "drop oldest" (bounded buffer, recent data preferred).

This acknowledges that one-size-fits-all backpressure doesn't work when consumers have different priorities and tolerances.

**Strengths**: Each consumer gets appropriate treatment. Critical handlers never lose events. Non-critical handlers don't stall the system. Configurable without code changes.

**Weaknesses**: Complexity — each subscription has its own policy. Policy conflicts (what if all say "never drop"?). Must still have a system-level fallback when all per-subscription buffers are full.

**Example**: [no source found — derived from ZeroMQ and RxJava documentation]

### Pattern 7: Adaptive / Dynamic Backpressure

**Used by**: Kafka (threshold-based pause/resume with hysteresis), TCP congestion control, some APM agents

**How it works**: Rather than fixed limits, the system adjusts dynamically based on observed load. When queue utilization exceeds a high threshold (e.g., 90%), reduce intake. When it drops below a low threshold (e.g., 70%), resume normal operation. The hysteresis prevents oscillation.

Kafka consumers use `pause()` at 90% capacity and `resume()` at 70%, maintaining partition assignment and heartbeats throughout. No manual tuning needed — the system adapts to current conditions.

**Strengths**: Self-tuning. No manual capacity planning. Handles variable load gracefully. Hysteresis prevents oscillation. Works with unpredictable event sources.

**Weaknesses**: Delay between threshold hit and action (events arrive during ramp-down). Must choose appropriate metrics (queue fill? dispatch latency? task count?). Over-engineering for systems with predictable load.

**Example**: [no source found — derived from Kafka pause/resume pattern]

## Anti-Patterns

- **No backpressure at all (fire-and-forget dispatch)**: Home Assistant's own event bus uses `call_soon()` to schedule handlers with no flow control. Under HA state storms (e.g., group entity updates triggering dozens of state_changed events), this can flood the event loop. Armin Ronacher's "I'm not feeling the async pressure" post identifies this as a systemic issue in asyncio. Source: https://lucumr.pocoo.org/2020/1/1/async-pressure/

- **Head-of-line blocking from a single slow consumer**: When one slow handler blocks event delivery to all handlers (because the shared channel fills), fast handlers starve. The fix: per-handler or per-priority dispatch queues, not a single shared channel.

- **Unbounded task fan-out**: Spawning one task per matched listener per event without a concurrency limit means task count = events × listeners. Under sustained load with many listeners, this exhausts memory and event loop capacity.

## Emerging Trends

- **Per-Subscription Overflow as Configuration**: Rather than one system-wide policy, modern messaging systems let each consumer declare their tolerance. The framework respects these declarations and applies different strategies per subscription.

- **Observability-Driven Backpressure**: Using metrics (queue depth, dispatch latency, task count) to trigger graduated responses rather than hard limits. Connects backpressure to the monitoring system.

## Relevance to Us

Hassette's current approach — **bounded channel (Pattern 5) + unbounded fan-out** — is partially correct. The channel provides backpressure to the event source (good), but dispatch has no concurrency limit (the gap Issue #72 identifies).

**What we do well:**
- Bounded event channel (1000 events) with blocking send (Pattern 5)
- Per-listener throttle/debounce (rate limiting at handler level)
- Idle detection and drain mechanisms for testing
- In-flight dispatch tracking (`_dispatch_pending` counter)

**The three gaps:**

1. **No dispatch concurrency limit** — if 100 listeners match an event, 100 tasks spawn simultaneously. Under sustained event flood, total concurrent tasks = (events in flight) × (average listeners per event). A semaphore or task pool limiting concurrent dispatches would bound this.

2. **Head-of-line blocking** — one channel serves all event types. If the channel fills because handlers for `state_changed` are slow, even fast `call_service` handlers are blocked. Per-priority or per-type channels would prevent this.

3. **No event priority/classification** — all events are equal in the channel. Under load, low-value events (frequent sensor updates) consume the same capacity as high-value events (user actions, errors). Priority queuing or type-based sampling would help.

## Recommendation

A layered approach for Issue #72:

**Layer 1 (Dispatch concurrency limit):**
Add a semaphore to BusService limiting concurrent dispatch tasks (e.g., max 50 concurrent handler invocations). When the semaphore is full, new dispatches wait rather than spawning unbounded tasks. This bounds total resource consumption regardless of event rate or listener count.

```python
self._dispatch_semaphore = asyncio.Semaphore(max_concurrent_dispatches)

async def _dispatch(self, listener, event):
    async with self._dispatch_semaphore:
        await listener.invoke(event)
```

**Layer 2 (Per-listener overflow policy — future):**
Allow listeners to declare their backpressure tolerance: `BackpressurePolicy.BLOCK` (wait for capacity — default), `BackpressurePolicy.DROP_NEWEST` (skip if at capacity), `BackpressurePolicy.KEEP_LATEST` (replace pending with newest). This maps to Pattern 6 and gives users control.

**Layer 3 (Event priority — future):**
Classify events into priority tiers (error > user_action > state_change > sensor_update). Under load, low-priority events are sampled or dropped first. High-priority events always dispatch.

**What NOT to do:**
- Don't remove the blocking channel — it's the correct first-line defense against WS overflow
- Don't add per-event-type channels (over-engineering for the current scale)
- Don't implement full Reactive Streams protocol (overkill for in-process pub/sub)

## Sources

### Standards & specifications
- https://github.com/reactive-streams/reactive-streams-jvm — Reactive Streams backpressure spec
- https://www.reactive-streams.org/ — Reactive Streams overview
- https://reactivex.io/documentation/operators/backpressure.html — ReactiveX backpressure operators

### Reference implementations
- https://docs.nats.io/running-a-nats-service/nats_admin/slow_consumers — NATS slow consumer handling
- https://github.com/Reactive-Extensions/RxJS/blob/master/doc/gettingstarted/backpressure.md — RxJS backpressure

### Blog posts & design
- https://www.infoq.com/news/2019/10/reactiveconf-2019-backpressure/ — Four backpressure strategies taxonomy
- https://lucumr.pocoo.org/2020/1/1/async-pressure/ — Armin Ronacher on async pressure (referenced via NATS/ZMQ discussions)
