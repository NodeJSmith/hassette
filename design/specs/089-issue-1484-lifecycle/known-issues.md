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

## KI-002: Duplicated change-detection/apply logic between `handle_change_event` and `_replay_pre_release_reconciliation_if_needed`

Status: open
Source: T03
Reason not fixed now: needs-decision
Observed in: T03
Affected files:
- src/hassette/core/app_lifecycle_service.py

Issue:
The "detect changes → reconcile blocked apps → compute `to_start` → rebuild `ChangeSet` → bail if
no changes → `apply_changes`" sequence (`app_lifecycle_service.py:570-601` in `handle_change_event`
vs. `625-653` in `_replay_pre_release_reconciliation_if_needed`) is copy-pasted near-verbatim
between the two methods. Only `handle_change_event` additionally does the pre-release
defer/merge bookkeeping and the `APP_LOAD_COMPLETED` event send.

Why deferred:
The duplication is real and does carry drift risk — it's exactly what nearly caused the
stale-replay bug this task already fixed once during review. But extracting a shared helper
(code review suggested `_detect_and_apply_changes(original, curr, changed_file_paths) -> bool`)
requires deciding the exact boundary: what stays in each caller (defer/merge bookkeeping,
event-send, take/no-op-if-empty logic) vs. what moves into the shared method. That's a small
design call, not a mechanical fix, and this task's fix budget is exhausted.

Recommended follow-up:
Extract a shared `_detect_and_apply_changes(original, curr, changed_file_paths) -> bool` (returns
whether anything changed) that both `handle_change_event` and
`_replay_pre_release_reconciliation_if_needed` call, keeping only the defer/merge/event-send logic
in `handle_change_event` and the take/no-op-if-empty logic in the replay method.

Acceptance criteria:
- The "detect → reconcile blocked → compute to_start → rebuild ChangeSet → bail-if-empty →
  apply_changes" sequence exists in exactly one place.
- `handle_change_event` and `_replay_pre_release_reconciliation_if_needed` both call the shared
  helper and retain only their distinct bookkeeping (pre-release defer/merge, event-send, take
  semantics).
- Existing tests covering both call sites (`tests/unit/core/test_app_lifecycle_service.py`) still
  pass unmodified in behavior.
