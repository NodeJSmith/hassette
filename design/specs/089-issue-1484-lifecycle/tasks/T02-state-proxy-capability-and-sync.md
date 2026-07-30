---
task_id: "T02"
title: "Rebuild state proxy capability and sync"
status: "done"
depends_on: ["T01"]
implements: ["FR#12", "FR#13", "FR#14", "FR#15", "FR#16", "FR#17", "FR#18", "FR#19", "FR#20", "FR#21", "FR#22", "FR#23", "FR#24", "FR#25", "FR#31", "FR#34", "AC#5", "AC#9", "AC#10", "AC#11", "AC#12", "AC#13", "AC#14", "AC#15", "AC#16", "AC#17", "AC#22", "AC#26"]
---

## Summary
Replace `StateProxy`'s startup/reconnect booleans and listener churn with one generation-aware synchronization coordinator. The new model must separate synchronization status, freshness, cache presence, and maintained generation while preserving stale reads after post-bootstrap disconnects. This task also updates the harness and helper infrastructure that currently forces StateProxy ready by toggling old readiness assumptions.

## Target Files
- modify: `src/hassette/core/state_proxy.py`
- modify: `src/hassette/types/enums.py`
- modify: `src/hassette/test_utils/app_harness.py`
- modify: `src/hassette/test_utils/factories.py`
- modify: `src/hassette/test_utils/harness.py`
- modify: `src/hassette/test_utils/reset.py`
- modify: `src/hassette/test_utils/web_mocks.py`
- modify: `tests/unit/core/test_state_proxy_yield_retry.py`
- modify: `tests/integration/test_state_proxy.py`
- modify: `tests/system/test_state_proxy.py`
- read: `src/hassette/core/websocket_service.py`
- read: `src/hassette/test_utils/helpers.py`

## Prompt
Implement the `## Architecture -> State Capability Model`, `## Architecture -> State Synchronization Coordinator`, `## Architecture -> Snapshot and Event Ordering`, and `## Architecture -> Failure Semantics` sections from the design doc.

In `src/hassette/core/state_proxy.py`, remove `_initialized`, `_reconnect_lock`, and reconnect-time listener recreation. Add explicit internal facts for synchronization status, freshness, cache presence, maintained generation, and initial-capability completion. Install one resource-lifetime state-change listener, open a synchronization-local journal for snapshot work, and commit snapshot + journal under the existing cache-write lock with request-id and generation fencing. Poll requests must skip during active synchronization; reconnect during a poll must queue exactly one reconnect; obsolete generation work must not publish freshness or initial capability. Empty successful snapshots are success, failed initial snapshots keep bootstrap blocked, reconnect failures keep the listener installed, and recoverable failures must retry via the next poll or one coalesced generation-scoped timer when polling is unavailable.

Only promote enums into `src/hassette/types/enums.py` if they are useful outside local implementation; keep purely local coordination enums inside `state_proxy.py`. Preserve lock-free read APIs, stale reads with populated cache, and `ResourceNotReadyError` for cold-cache reads. Update harness/reset/test helpers so they model state capability explicitly instead of just forcing `is_ready()`.

## Focus
- `src/hassette/core/state_proxy.py` currently conflates lifecycle readiness with state capability and directly clears/recreates `state_change_sub`; all of that is replacement-target work, not an additive path.
- The websocket generation API from `T01` is a dependency here; do not invent a second stale-work rejection mechanism based only on locks.
- Reverse-dependency gaps to include here: `src/hassette/test_utils/harness.py`, `src/hassette/test_utils/reset.py`, `src/hassette/test_utils/app_harness.py`, `src/hassette/test_utils/web_mocks.py`, and `src/hassette/test_utils/factories.py` each assume `StateProxy.is_ready()` or mocked empty caches are enough to simulate usable state.
- `tests/integration/test_state_proxy.py` currently asserts `_initialized`, `_reconnect_lock`, reconnect-time resubscription, and ready-after-failed-init behavior; those assertions must be replaced, not preserved alongside the new coordinator.
- `tests/system/test_state_proxy.py` is a reverse dependency because real-system expectations around populated cache, stale reads, and typed state access must still hold after the internal rewrite.

## Verify
- [ ] FR#12: `StateProxy` exposes separately testable synchronization status, freshness, and cache-presence facts instead of one overloaded readiness bit.
- [ ] FR#13: A successful zero-entity snapshot counts as fresh state capability.
- [ ] FR#14: Failed or never-completed initial synchronization never satisfies initial state capability.
- [ ] FR#15: Duplicate startup/connected signals cannot skip or duplicate initial synchronization.
- [ ] FR#16: Concurrent reconnect requests for one active generation coalesce into one reconnect synchronization.
- [ ] FR#17: Poll refresh never overlaps another synchronization.
- [ ] FR#18: A poll request arriving during active synchronization is skipped.
- [ ] FR#19: A reconnect request arriving during a poll produces exactly one reconnect synchronization after the poll finishes.
- [ ] FR#20: Obsolete-generation synchronization cannot mark the cache fresh or complete initial capability.
- [ ] FR#21: Journaled newer state-change operations win over older snapshot values in commit order.
- [ ] FR#22: Disconnect after successful initialization retains populated cached state for stale reads.
- [ ] FR#23: Cold-cache reads before capability exists raise `ResourceNotReadyError`.
- [ ] FR#24: The lifetime state-change listener stays installed across reconnect snapshot failures.
- [ ] FR#25: Runtime disconnect changes StateProxy freshness to stale without clearing populated cached states or affecting app lifecycle.
- [ ] FR#31: Journaled removal tombstones prevent deleted entities from being resurrected by an in-flight snapshot.
- [ ] FR#34: Every recoverable synchronization failure schedules one bounded future retry for the current generation and cancels superseded retries.
- [ ] AC#5: An empty but successfully maintained snapshot is treated as bootstrap-releasing state capability.
- [ ] AC#9: Synchronization status, freshness, and cache presence are independently observable in tests.
- [ ] AC#10: Duplicate initial connected signals do not trigger a second initial snapshot or duplicate listener install.
- [ ] AC#11: Reconnect coalescing uses the existing lifetime listener rather than creating a new one.
- [ ] AC#12: Poll-skip and reconnect-after-poll behavior matches the explicit request policy.
- [ ] AC#13: Obsolete generation completion cannot mark fresh or release bootstrap.
- [ ] AC#14: Newer state events observed during synchronization survive snapshot merge.
- [ ] AC#15: Populated-cache disconnects permit stale reads, while empty cold-cache reads raise.
- [ ] AC#16: Reconnect snapshot failure leaves the lifetime listener installed without publishing freshness.
- [ ] AC#17: A post-bootstrap disconnect produces stale state capability while preserving the cache consumed by running apps.
- [ ] AC#22: Delete events received during synchronization remain authoritative over the returned snapshot.
- [ ] AC#26: Retry behavior converges through poll-or-timer with generation-scoped coalescing and cancellation.
