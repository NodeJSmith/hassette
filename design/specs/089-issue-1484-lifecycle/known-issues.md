# Known Issues

Durable issues discovered during orchestration that were intentionally not fixed in this run.

## KI-001: Websocket generation metadata currently lives on the shared Event base type

Status: open
Source: T02
Reason not fixed now: needs-decision
Observed in: T02
Affected files:
- src/hassette/events/base.py
- src/hassette/events/metadata.py
- src/hassette/core/websocket_service.py

Issue:
`websocket_generation` is currently stored on the shared `Event` base dataclass so StateProxy can reject stale state-change events by generation. The remaining integration-review objection is architectural: this exposes transport-coordination metadata on every event instance instead of confining it to the Home Assistant state-change path.

Why deferred:
The current implementation is functionally correct and covered by focused tests, but there are two reasonable designs left: keep the shared field as the smallest declared-storage fix, or move generation metadata to a narrower Home Assistant-specific type/sidecar. Choosing between those options is design cleanup, not a blocker for T02 behavior.

Recommended follow-up:
If we want stricter layering later, move websocket-generation storage off the root `Event` type and onto a narrower Home Assistant/state-change-only metadata container while preserving the stale-generation protections added in T02.

Acceptance criteria:
- StateProxy still rejects stale-generation state-change events.
- Websocket generation metadata is no longer visible on unrelated event types.
- Public websocket bus listener APIs and payloads remain source-compatible for app authors.
