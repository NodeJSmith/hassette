---
topic: "WS push vs REST fetch for enriched log metadata"
date: 2026-09-25
status: Draft
---

# Prior Art: WS Push vs REST Fetch for Enriched Log Metadata

## The Problem

Real-time dashboards need two things that pull in opposite directions: immediacy (logs appear the instant they're emitted) and completeness (each log row carries enriched metadata from DB joins — execution context, listener/job IDs, correlation data). Assembling the full enriched shape at push time forces the streaming path to duplicate the same join logic the REST query already owns, creating maintenance drift and bugs when fields are added to one path but not the other.

## How We Do It Today

Hassette runs two independent log-assembly paths. The WS path (`LogCaptureHandler.emit()`) builds a `LogEntry` dataclass from the logging record plus context-var correlation fields stamped by `CorrelationFilter` — no DB access, pure in-process. The REST path (`get_log_records`) queries SQLite with a LEFT JOIN on the `executions` table to pull `execution_kind`, `listener_id`, and `job_id`. Both paths produce shape-compatible payloads (`LogEntry.to_dict()` vs `LogEntryResponse`), but they're maintained independently — a Python dataclass, a Pydantic model, and a SQL projection. Nothing enforces sync. This already caused a bug where linking fields were present on REST but missing on WS.

## Patterns Found

### Pattern 1: Notify-and-Fetch (thin WS hint + REST fetch)

**Used by**: Stripe (thin webhook events), WebSocket.org (named "signalling" pattern), CQRS/event-sourcing systems (Fenergo/AWS), Grafana Live (signal-then-query for dashboards)

**How it works**: WS carries a minimal envelope — event ID or cursor, event type, enough correlation to let the client decide what to do — but not the enriched joined fields. On receipt, the client fetches the full record via REST using that ID/cursor. This decouples "when did something happen" (cheap, append-only, ideal for WS) from "what is the full current state" (join-heavy, better served by an existing cacheable REST endpoint). Stripe's explicit rationale: fetched data reflects current DB state, not emit-time state, avoiding staleness.

**Strengths**: Minimizes WS payload and broadcast cost; reuses existing REST/DB query infrastructure; avoids staleness; scales better with many subscribers since enrichment is on-demand.

**Weaknesses**: Two round trips per update; naive 1:1 notify→fetch creates fetch storms under high event rates — must batch/coalesce via cursor-range fetching.

**Example**: [Stripe webhooks](https://docs.stripe.com/webhooks), [Fenergo CQRS+WS](https://resources.fenergo.com/engineering-at-fenergo/working-with-event-sourcing-cqrs-and-web-sockets-on-aws)

### Pattern 2: Full Enriched Payload Over WS

**Used by**: Rails Turbo Streams + ActionCable, Phoenix LiveView

**How it works**: The broadcasting process performs the join/enrichment at emit time and pushes the fully resolved shape over the socket. No separate fetch step.

**Strengths**: Single round trip, lowest latency, simpler client logic.

**Weaknesses**: Couples broadcast code to join logic (the exact duplication hassette already suffers from); every subscriber pays the join cost at broadcast time; payload grows with enrichment complexity; works best when broadcaster and query layer are the same monolith — awkward with a separate SPA + REST API.

**Example**: [Rails ActionCable Turbo Streams](https://www.stanza.dev/courses/rails-action-cable/broadcasting-patterns/rails-action-cable-turbo-streams), [Phoenix LiveView](https://hexdocs.pm/phoenix_live_view/Phoenix.LiveView.html)

### Pattern 3: Cursor/ID-Based Incremental Fetch

**Used by**: GetStream (real-time feeds), Zendesk (incremental export), dlt (incremental loading)

**How it works**: Regardless of trigger (WS push, long-poll, reconnect), data retrieval uses a resumable cursor: "give me everything after ID X." Cursor advances only on confirmed processing. Transport-agnostic — WS can fail over to polling without changing fetch semantics.

**Strengths**: Correct under reconnect gaps, dropped messages, client restarts; supports backfill/catch-up after offline periods.

**Weaknesses**: Requires the DB to support ordered resumable pagination (stable increasing ID or sequence number); adds client-side cursor bookkeeping.

**Example**: [GetStream blog](https://getstream.io/blog/long-polling-vs-websockets/), [dlt cursor loading](https://dlthub.com/docs/general-usage/incremental/cursor)

### Pattern 4: Periodic Polling (baseline)

**Used by**: Simpler dashboards, GetStream's "good enough" recommendation for low-frequency feeds

**How it works**: Client polls REST on a fixed interval, always fetching from the same enriched query.

**Strengths**: Simplest to implement; naturally reuses the exact REST/DB query path.

**Weaknesses**: Wastes requests when nothing changed, or adds latency with longer intervals.

## Anti-Patterns

- **Fat-state broadcasts on every tick** — a cited case saw 3,200x bandwidth overhead from broadcasting full state every 10s when only ~10 bytes changed. ([Hookdeck](https://hookdeck.com/outpost/guides/webhook-payload-best-practices))
- **Trusting push payload for security-sensitive reads** — Stripe recommends re-fetching rather than acting on embedded data, because pushed data can be stale or spoofed. ([Hookdeck/Stripe](https://hookdeck.com/webhooks/platforms/stripe-thin-events-best-practices))
- **Un-coalesced fetch-per-event under bursty rates** — naive 1:1 notify→fetch degenerates into a request storm; cursor-range batch fetching (Pattern 3) is the documented mitigation. ([WebSocket.org](https://websocket.org/guides/use-cases/notifications/))

## Relevance to Us

Hassette's situation maps directly to Pattern 1 + Pattern 3 combined:

- **Pattern 2 is what we have today** (full enriched payload over WS) and it's the source of the bug that motivated #1373 — the WS path duplicates join logic the REST path already owns, with no structural guarantee they stay in sync.
- **Pattern 1 (notify-and-fetch)** eliminates the duplication by making WS carry only display fields and letting REST be the single source of truth for the enriched shape.
- **Pattern 3 (cursor-based incremental fetch)** solves the "how does the frontend know what to fetch" question — the WS hint carries a starting `seq` (hassette's log records already have a monotonically increasing `seq` field), and the frontend fetches `get_log_records(since_seq=X)` to get the enriched batch.

The combination avoids the anti-patterns: no fat broadcasts, no duplicated join logic, no fetch-per-event storms (cursor-range batching is natural), and reconnect/backfill correctness comes free from the cursor.

Hassette's existing constraint — `LogCaptureHandler.emit()` runs synchronously in a logging handler with no DB access — makes Pattern 2 structurally awkward anyway. The emit path *can't* cheaply do the JOIN; it has to thread correlation fields through context vars, which is the fragile part. Dropping that threading and switching to notify-and-fetch aligns with the architectural grain rather than fighting it.

The frontend already deduplicates WS and REST log entries by `rowKey()` (timestamp + logger_name + lineno), so the merge infrastructure exists. The `seq` field is already present on both paths — it's a natural cursor.

## Recommendation

**Notify-and-fetch with cursor-based batching** (Pattern 1 + 3) is well-supported by prior art and directly addresses hassette's dual-path maintenance problem. The candidate pattern the user described — WS sends a lightweight "new logs available" hint with a starting seq/ID, frontend fetches the enriched batch from REST — matches the documented best practice from Stripe, WebSocket.org, and CQRS literature.

Key design decisions to lock in:
1. **WS hint payload**: `{"type": "log_hint", "since_seq": N}` — minimal, carries the cursor
2. **Coalescing**: under bursty log rates, batch multiple hints into one fetch (debounce on the frontend, fetch the cursor range)
3. **Reconnect**: on WS reconnect, frontend fetches from its last-seen seq — cursor makes this correct without special reconnect logic

## Sources

### Reference implementations
- https://docs.stripe.com/webhooks — Stripe thin events model
- https://hexdocs.pm/phoenix_live_view/Phoenix.LiveView.html — Phoenix LiveView (counter-pattern)

### Blog posts & writeups
- https://hookdeck.com/webhooks/platforms/stripe-thin-events-best-practices — Stripe thin events best practices
- https://hookdeck.com/outpost/guides/webhook-payload-best-practices — Webhook payload design (thin vs thick)
- https://resources.fenergo.com/engineering-at-fenergo/working-with-event-sourcing-cqrs-and-web-sockets-on-aws — CQRS + WS notify-then-query
- https://getstream.io/blog/long-polling-vs-websockets/ — Cursor-based resume pattern
- https://oneuptime.com/blog/post/2026-01-23-push-notifications-websockets-nodejs/view — Notify-and-fetch implementation walkthrough

### Documentation & standards
- https://websocket.org/guides/use-cases/notifications/ — WS notify-and-fetch pattern (named "signalling")
- https://websocket.org/comparisons/rest/ — WS vs REST complementary use
- https://grafana.com/docs/grafana/latest/setup-grafana/set-up-grafana-live/ — Grafana Live signal-then-query model
- https://www.svix.com/resources/webhook-university/implementation/designing-webhook-payloads/ — Webhook payload design guidance
- https://www.stanza.dev/courses/rails-action-cable/broadcasting-patterns/rails-action-cable-turbo-streams — Rails ActionCable Turbo Streams (counter-pattern)
- https://dlthub.com/docs/general-usage/incremental/cursor — Cursor-based incremental loading
