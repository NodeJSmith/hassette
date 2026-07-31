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
Observed in: T03; narrowed during clean-code pass at commit 84d45330
Affected files:
- src/hassette/core/app_lifecycle_service.py

Issue:
The "detect changes → reconcile blocked apps → compute `to_start` → rebuild `ChangeSet` → bail if
no changes → `apply_changes`" sequence was copy-pasted near-verbatim between `handle_change_event`
and `_replay_pre_release_reconciliation_if_needed`. The clean-code pass at commit 84d45330 extracted
the "reconcile blocked apps → compute `to_start` → rebuild `ChangeSet`" portion into a shared
`_fold_unblocked_apps_into_changes(changes)` helper, now called
identically from both methods. What remains duplicated is thinner: both methods independently call
`self.change_detector.detect_changes(original_apps_config, curr_apps_config, changed_file_paths,
only_apps=self.registry.only_apps)` (same 3-line call) and, on success, `await
self.apply_changes(changes)`. Only `handle_change_event` additionally does the pre-release
defer/merge bookkeeping, the bootstrap-release check, and the `APP_LOAD_COMPLETED` event send.

Why deferred:
The remaining duplication is small (one shared call plus one shared call), but the two methods
differ in exactly what happens immediately before and after — `handle_change_event` merges queued
pre-release state and defers when unreleased; the replay method has already taken and validated
that state and has no defer branch. Extracting `detect_changes` + `apply_changes` into one shared
method requires deciding how much of that surrounding branching should move inside a shared helper
versus stay in each caller. That's a small design call, not a mechanical fix.

Recommended follow-up:
Decide the extraction boundary for a `_detect_and_apply_changes(original, curr, changed_file_paths)
-> bool` helper (returns whether anything changed) that both methods call, keeping only
`handle_change_event`'s defer/merge/event-send logic and `_replay_pre_release_reconciliation_if_needed`'s
take/no-op-if-empty logic in their respective callers.

Acceptance criteria:
- The `detect_changes` call and the `apply_changes` call each exist in exactly one place.
- `handle_change_event` and `_replay_pre_release_reconciliation_if_needed` both call the shared
  helper and retain only their distinct bookkeeping (pre-release defer/merge, event-send, take
  semantics).
- Existing tests covering both call sites (`tests/unit/core/test_app_lifecycle_service.py`) still
  pass unmodified in behavior.

## KI-003: `StateProxy` has grown into a 630+ line file embedding a full synchronization state machine

Status: open
Source: clean-code (mine-clean-code, this run)
Reason not fixed now: out-of-scope
Observed in: commit 84d45330
Affected files:
- src/hassette/core/state_proxy.py

Issue:
`state_proxy.py` grew from 367 to ~630 lines in the #1484 lifecycle redesign. The file now owns
nine private coordination methods (`_run_synchronization`, `_begin_synchronization`,
`_build_candidate_states`, `_commit_candidate_states`, `_handle_synchronization_failure`,
`_detach_active_sync_task`, `_finish_synchronization`, `_schedule_retry`,
`_run_retry_after_delay`) plus three dataclasses/enums (`_JournalOperation`,
`_ActiveSynchronization`, `_ConnectedSyncCause`, `StateSynchronizationStatus`,
`StateCacheFreshness`), all inside the `StateProxy` `Resource` class. This exceeds the 400-line
"typical" ceiling in `CLAUDE.md` (coding-style.md) by a wide margin.

Why deferred:
Splitting the synchronization coordinator (dataclasses, enums, and orchestration methods) into a
dedicated module that `StateProxy` composes is a structural refactor touching the most
correctness-critical file in this design (generation fencing, journal commits, freshness
barriers — FR#12-#21). It needs a deliberate refactor pass with its own pinned-behavior tests
(see `refactoring-discipline.md`), not a clean-code-pass edit. Out of scope for this run.

Recommended follow-up:
Extract `_JournalOperation`, `_ActiveSynchronization`, `_ConnectedSyncCause`,
`StateSynchronizationStatus`, `StateCacheFreshness`, and the synchronization orchestration methods
(`_run_synchronization` through `_run_retry_after_delay`) into a dedicated
`state_proxy_sync.py` module that `StateProxy` composes (owns an instance of) rather than
implements directly. Keep the public `StateProxy` surface (`get_state`, `synchronization_status`,
`cache_freshness`, `wait_initial_state_capability`, etc.) unchanged.

Acceptance criteria:
- `state_proxy.py` drops back under (or close to) the 400-line typical ceiling.
- All existing `tests/integration/test_state_proxy.py`, `tests/system/test_state_proxy.py`, and
  `tests/unit/core/test_state_proxy_yield_retry.py` tests pass unmodified in behavior.
- Generation fencing, journal-commit ordering, and freshness semantics (FR#12-#21) are unchanged.

## KI-004: Two test files crossed the 800-line hard cap during this branch

Status: open
Source: clean-code (mine-clean-code, this run)
Reason not fixed now: out-of-scope
Observed in: commit 84d45330
Affected files:
- tests/integration/test_websocket_service.py (991 → 1177 lines)
- tests/unit/core/test_app_lifecycle_service.py (728 → 808 lines)

Issue:
Both files exceed the 800-line hard maximum in `CLAUDE.md` (coding-style.md) after this branch's
additions. `test_websocket_service.py` gained new readiness/generation and retry-subscription
tests; `test_app_lifecycle_service.py` gained the new `TestBootstrapAppsAdmission` class covering
`AppAdmissionMode`.

Why deferred:
Splitting a test file is mechanical (no production behavior at risk) but requires deciding the
split boundary — which test classes/fixtures move to a sibling file, and whether shared fixtures
need to move to a local `conftest.py`. That's a file-organization decision better made deliberately
than folded into a mixed clean-code pass touching many other files.

Recommended follow-up:
- Split `test_websocket_service.py`: move `TestSubscribeEventsRetry` and the new
  readiness/generation tests into a sibling file (e.g. `test_websocket_service_generations.py`).
- Split `test_app_lifecycle_service.py`: move the new `TestBootstrapAppsAdmission` class into its
  own file (e.g. `test_app_lifecycle_service_admission.py`).

Acceptance criteria:
- Both files drop under 800 lines.
- All tests continue to pass, unmodified in behavior, after the split.
- Directory-level `CLAUDE.md` fixture pointers (if any) are updated to reflect new file locations.

## KI-005: Pre-release reconciliation merge/record logic has deep nesting around correctness-sensitive bookkeeping

Status: open
Source: clean-code (mine-clean-code, this run)
Reason not fixed now: behavior-change
Observed in: commit 84d45330
Affected files:
- src/hassette/core/app_lifecycle_service.py

Issue:
Two related readability findings in the pre-release reconciliation path:
1. `handle_change_event`'s queued-pre-release-merge block reaches 4 levels of nesting
   (`async with lock:` → `if is_released() and pending:` → `if pending_original is not None:` →
   `if pending_paths is None or changed_file_paths is None:` / `else:`).
2. `_record_pre_release_reconciliation`'s `changed_file_paths` handling is a four-branch
   `if/elif/elif/else` chain where two branches (`elif not had_pending_reconciliation` and
   `elif self._pending_pre_release_changed_paths is None`) both just set `None`, making the
   non-overlapping-ness of the branches hard to confirm at a glance.

Why deferred:
Both blocks implement the exact merge/dedup semantics that a prior integration review already
caught one subtle bug in (see the inline comment referencing "stale pre-release replay" at
`handle_change_event`). Restructuring control flow here — even without intending a behavior
change — risks silently altering which `changed_file_paths`/`original_apps_config` combination
survives a merge, since the four branches encode specific, previously-debugged edge cases. This
needs a pinned-behavior test pass (see `refactoring-discipline.md`) before restructuring, not a
clean-code-pass edit.

Recommended follow-up:
Add characterization tests enumerating all four `changed_file_paths`/`had_pending_reconciliation`
combinations in `_record_pre_release_reconciliation`, then refactor both blocks (extract a
named helper for the merge in `handle_change_event`; collapse the two `None`-setting branches in
`_record_pre_release_reconciliation`) against that pin.

Acceptance criteria:
- Characterization tests cover all four branches of `_record_pre_release_reconciliation`'s
  `changed_file_paths` handling before refactoring.
- Nesting in `handle_change_event`'s merge block drops to 3 levels or fewer.
- `_record_pre_release_reconciliation`'s branch count is reduced without changing which value each
  input combination produces.
- All existing tests in `tests/unit/core/test_app_lifecycle_service*.py` pass unmodified in
  behavior.
