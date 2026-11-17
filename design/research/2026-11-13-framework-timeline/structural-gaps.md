# Research Brief: Structural gaps under the lifecycle-history writers (#3678)

**Date:** 2026-11-13
**For:** `design/specs/152-lifecycle-history-writers/pause-note.md` (gaps 1–3)

**Bottom line:** Gaps 1 and 2 have small, peer-aligned fixes, so no temporary workaround is needed. Each fix deletes a workaround the #3678 ledger was building: D2's dedupe map, D4's inferred last state and D6's callable. Gap 3 is real but doesn't block #3678 once gap 1 lands. File it on its own. Order: gap 2, then gap 1, then re-sketch #3678's D1, D2 and D4. Gap 3 can land any time.

No open duplicate issues for any of the three. #1446 (the status projector) is open and related to gap 1. The gap 1 fix is its input contract, about 15–20% of it.

## Gap 1: app status has no single owner

**Today**
- `AppRegistry` (`core/app_registry.py:79-120`) stores only RUNNING or FAILED. Its methods don't know the previous status and send no events.
- The fine-grained status (STARTING, STOPPING, and so on) lives on the `App` resource. Its setter (`resources/mixins.py:224-235`) already logs `old → new`, but it sends nothing for apps.
- Six sites rebuild `HassetteAppStateEvent` by hand:
  - Four send no `previous_status`.
  - The `previous_status=STARTING` passed at `app_lifecycle_instances.py:129/263/280` is a literal. No STARTING event is ever sent.
  - `shutdown_all` → `clear_all()` and the needs-restart flag change status silently.
- The only production consumer is `RuntimeQueryService.on_app_state_changed` (`runtime_query_service.py:212-231`), which overwrites the UI's cached status.
- Site 198 exists only to push create-time failures into that cache. A snapshot push would do the same job.

**Peers**
- **Prefect:** `set_flow_run_state` reads the from-state from its own store, then validates, commits and runs `after_transition(initial, validated)` hooks. Callers never supply the from-state.
- **HA `ConfigEntry`:** `_async_set_state` (`config_entries.py:1245-1278`) is the one setter, and it dispatches the change signal.
- **HA state machine:** "changed" and "re-send anyway" (`force_update`) are separate paths. An identical state sends no event.
- **Airflow:** listeners receive `previous_state`. Airflow's per-site calls were missed twice (PRs 61932, 59639).
- Not checked: AppDaemon, NetDaemon.

**Proper fix (recommended; no temporary fix needed)**
- Add `AppRegistry.set_status(app_key, instance, to, *, error=None) -> StatusChange | None`:
  - It reads the from-state from the entry, or uses NOT_STARTED when there's no entry.
  - It returns `None` when the status and details are unchanged.
  - It updates the entry and returns a frozen `StatusChange`.
- Make `register_app`, `record_failure` and `unregister_app` internal to the registry. Widen `InstanceEntry.status` to the full `ResourceStatus`.
- A thin `AppLifecycle.transition()` builds the event from the returned change. The registry gains no bus dependency.
- Delete site 198. The UI re-sync becomes a snapshot push from `get_full_snapshot` (`app_registry.py:441`), following HA's split between "changed" and `force_update`.
- Size: about 8–12 files and 300–400 lines, mostly mechanical. It is the input contract for #1446's projector, not the projector.
- What this removes from #3678:
  - D2's dedupe map: no-change returns `None`.
  - The three meanings of `from_status`: the registry supplies it.
  - Most of D1's structural test: status changes only through `set_status`.

**Divergences from peers**
- **No transition table** (Prefect validates every pair). Not adopted because a table is overbuilt for a solo, pre-V1 project. The from == to guard plus a DEBUG log on odd sequences covers the cases we've seen. **Possible mistake:** an illegal sequence such as STOPPED → RUNNING passes silently.
- **The from-state is included in the event.** This goes beyond HA, whose signal has no from-state, and matches Airflow's `previous_state`.
- **Status still has two holders, the `App` resource setter and the registry.** Having the setter call into the registry would close that, but it's a bigger change. Flagged as debt to file alongside.

## Gap 2: connection state has two incomplete owners

**Today**
- `ConnectionState` (`types/enums.py:164-180`) has DISCONNECTED, CONNECTING, CONNECTED and AUTH_FAILED.
- Waiting for HA core holds the state in CONNECTING (`websocket_service.py:~425-455`). The wait shows up only as a ready-reason string (`report_connection_status`, `:381-392`) and as `OutageLog.record_core_wait`.
- `OutageLog` (`websocket_reconnect.py:236-377`) exists to pace logs (spec 131 D11). Its three entry points are called from the serve loop (`:371/451/496`), not from `set_connection_state`.
- A first start while HA is still starting calls no `record_failure`. That is why D4 needed its own inferred "last state written".
- `is_connected` checks `== CONNECTED`. The wire format exposes only a bool (`hassette_wire/health.py:42`).

**Peers**
- **gRPC connectivity:** one owner with five states, and observers subscribe to transitions.
- **HA `ConfigEntryState.SETUP_RETRY`:** "not ready yet, retry later" is a first-class state.
- **NetDaemon:** OnConnect and OnDisconnect observables, with retry pacing in a separate `ProgressiveTimeout` helper.
- **AppDaemon:** a `ready_event` boolean, the same weaker model hassette has now.
- **home-assistant-js-websocket:** no core-running state.
- The common pattern: one owner emits transitions, pacing and backoff live in a separate helper, and none couples log bookkeeping to the state.

**Proper fix (recommended; no temporary fix needed)**
- Add `WAITING_FOR_CORE` and extend `WS_VALID_TRANSITIONS`.
- `set_connection_state(new, *, detail=None)` becomes the single hook, calling observers with `(old, new, detail, now)`. The first call passes `old=None`.
- `OutageLog` becomes an observer:
  - Its pacing state stays.
  - The three serve-loop calls collapse into `on_transition`.
  - `record_failure` still needs the exception and retry plan, passed either as detail or as one explicit call.
- The ready reason could be derived from the transition, keeping today's emit-only-on-change rule.
- Size: about 150–250 source lines plus test churn in `test_ws_connection_state.py`, `test_websocket_readiness_events.py` and `test_reconnect_loop.py`.
- What this removes from #3678: D4's inferred last state, and D6's callable into `OutageLog`. The row writer becomes a second observer.

**Divergences from peers**
- **No TRANSIENT_FAILURE state** (gRPC has one). Retries stay in CONNECTING with no transition by design (`websocket_service.py:65` comment). Adding the state would add a row per retry.
- **`OutageLog` stays separate from the state machine.** This matches NetDaemon and HA. gRPC folds backoff into its states.

## Gap 3: the bus doesn't drain on shutdown

**Today**
- `Hassette.before_shutdown` calls `self._bus.remove_all_listeners()` (`core.py:757-762`) before any child stops.
- `BusService.serve` (`bus_service.py:759-773`) exits on `shutdown_event` and discards whatever is unread in the channel.
- `on_shutdown` (`:688-703`) waits only for handlers already dispatched.
- Apps stop before the bus (dependency waves), so the bus is still dispatching while apps stop. The listeners are already gone, though.
- Nothing found relies on dropping. App listeners are removed at app stop (`app_lifecycle_instances.py:161`).

**Peers**
- **HA:** `async_stop` runs staged events (STOP, FINAL_WRITE, CLOSE), each followed by `async_block_till_done` under a timeout.
  - The recorder unsubscribes and joins its queue at FINAL_WRITE, after integrations stop, and discards the remainder at CLOSE.
  - HA fixed this same problem (a recorder stopping before the events it should record) in core PR 91165.
- **asyncio `Queue.shutdown(immediate=False)` (3.13) and OTel's batch processor `shutdown`:** stop accepting, drain within a bound, then close.

**Proper fix**
1. Move the root `remove_all_listeners()` to after the stop stage, mirroring the recorder's FINAL_WRITE. This is about 10 lines.
2. On shutdown, drain buffered events with `receive_nowait`, bounded by `clamp_to_shutdown_deadline`, then call `await_dispatch_idle` and close. This is about 30 lines plus a test.
3. The dead-bus path still closes without draining.

Risk: a drained event could reach a listener whose service has already stopped. Not checked: whether framework services remove their own listeners on stop.

**Is it a prerequisite? No.** With gap 1's `set_status`, the history row is written through the `SessionManager` writer, never through the bus. Rows written during app stop land before the foundation stage drains the write queue. File gap 3 as its own issue (small or medium).

**Divergences from peers**
- **Listeners are removed at `before_shutdown`, the opposite of HA's recorder.** No documented reason was found. It was introduced in commit 18f742b9 (#312), which hasn't been read yet. **Flagged as a possible mistake.**
- **No per-stage shutdown events.** The dependency waves already order shutdown. HA-style STOP, FINAL_WRITE and CLOSE events would be a larger change for little gain.
