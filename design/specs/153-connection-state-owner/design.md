# Design: One owner for the websocket connection state

**Date:** 2026-11-13
**Status:** built
**Mode:** sketch
**Issues:** #4091
**Prior art:** `design/specs/153-connection-state-owner/peer-check.md` (observer mechanics); `design/research/2026-11-13-framework-timeline/structural-gaps.md` Gap 2 (state model; on branch `3678`, read with `git show 3678:<path>`)

## Summary

Two places track the websocket connection's state today, and neither has the full picture. `ConnectionState` (`src/hassette/types/enums.py`), owned by `WebsocketService.set_connection_state` (`src/hassette/core/websocket_service.py`), has no state for "socket up, Home Assistant core still starting". The RUNNING gate (`wait_for_core_running`) holds the connection in CONNECTING, and the wait shows up only as a ready-reason string. `OutageLog` (`src/hassette/core/websocket_reconnect.py`) keeps a parallel gap and episode model for log pacing (spec 131 D11). Explicit serve-loop calls feed it (D1). Anything that wants connection history, such as the lifecycle-history writers (#3678, spec 152 on branch `3678`), would have to rebuild a third "last state" from the two.

This change:

- adds `ConnectionState.WAITING_FOR_CORE`, entered by the RUNNING gate when Home Assistant's core isn't RUNNING (D6)
- makes `set_connection_state(new)` the only place under `src/` that connection state changes after `WebsocketService.__init__` sets the initial DISCONNECTED, including the test harness's "mark connected" helper (D9)
- leaves `OutageLog` on its explicit serve-loop calls (D1), with `WebsocketService` the only owner of "connected since" and "ever connected"

It does not add transition observers. The observer seam, its payload and its first consumer are designed together in the #3678 re-sketch (D10), and D2–D5 are carried there as input.

Homes for the new pieces:

- **Single-writer harness path (D9):** `mark_websocket_service_connected` in `src/hassette/testing/_ws_mocks.py` calls the setter instead of writing the state.
- **The new state:** `ConnectionState` in `types/enums.py`. Its edges go in `WS_VALID_TRANSITIONS` in `websocket_service.py`. It's set in `wait_for_core_running`, beside its ready reason and the per-recheck `record_core_wait` call.

Out of scope: transition observers and the row writer (#3678), exposing the state in the wire format or the UI, and any change to log pacing.

## Posture

- **Failure handling:** no new retries or guards.
- **Compatibility:** break freely. The new `ConnectionState` member is additive. The wire format exposes only `is_connected` (`wire/src/hassette_wire/health.py`), and the frontend never reads the enum.
- **Scope:** minimal: the issue's acceptance criteria as revised by D1 and D10. The observer and `detail` criteria move to #3678, and "`OutageLog` is driven by transitions" becomes "`OutageLog`'s pacing is unchanged". Log pacing (spec 131 D11) stays exactly as it is: the same lines, at the same levels and the same cadence. In production, the setter's per-transition DEBUG line is the only new log output.
- **Rollout:** ships directly.
- **Hardening:** project defaults.
- **Altitude:** build. One session builds it.
- **Docs:** `.claude/rules/core-startup.md` and docstrings. The docs pages mention only `AUTH_FAILED`, and `design-completeness.md` exempts internal plumbing.

## Decisions

### D1: What feeds `OutageLog`?

**Situation:** Failed attempts deliberately produce no transition. They stay in CONNECTING (`websocket_service.py`, the comment above `WS_VALID_TRANSITIONS`), and the issue keeps that. Core-wait rechecks also stay in one state, every `CORE_RUNNING_RECHECK_SECONDS` (5 s). But `OutageLog` needs a call on each attempt, to count it, dedupe its traceback and log it at the right level, and on each recheck, to pace the 300 s "still waiting" summary. So transitions alone can't drive all of `OutageLog`. The issue's "its serve-loop call sites go" holds only if observers also get same-state events. Today `record_failure` also takes `connected_for` and `has_ever_connected`, which `WebsocketService` computes. Those are facts about transitions.

**Deciding factor:** `OutageLog` has one driver in today's order, log pacing is exactly unchanged, and `WebsocketService` is the only owner of "connected since" and "ever connected".

| | A: transitions for state facts, explicit per-attempt calls stay | B: every call notifies, same-state included | C: leave `OutageLog` on its explicit calls |
|---|---|---|---|
| What `OutageLog` takes from transitions | Leaving CONNECTED: works out `connected_for` from its own `at`, runs the flap and stable-episode logic, opens the gap. Entering CONNECTED: the recovery line, closes the gap, latches "has ever connected". Entering WAITING_FOR_CORE: opens an episode if none is open | Everything, including each failed attempt (CONNECTING → CONNECTING carrying the exception and plan) and each recheck | Nothing |
| Serve-loop calls left | `record_failure` per attempt and `record_core_wait` per recheck. `record_connected` and the `connected_for`/`has_ever_connected` arguments go | None | All three, unchanged |
| What observers see | Real changes only; `old != new` always | State changes mixed with same-state "events"; #3678's writer has to skip `old == new` | Real changes only |
| Payload | `detail` stays small (D3) | `detail` has to carry an `Exception` and a `RetryPlan`, so it must be a typed union | Small |
| Meets acceptance criterion "`OutageLog` is driven by transitions" | Its state facts, yes. Its per-attempt pacing, no, and that's called out | Yes, literally | No; reworded to "`OutageLog`'s pacing is unchanged" |
| Drivers of `OutageLog`'s episode and gap fields | Two (a transition handler and `record_failure`), in an order that differs by path; on recv death the handler runs first | One per call, but every call becomes a notification | One, in today's order |
| Owners of "connected since" / "ever connected" | `WebsocketService` and a shadow copy in `OutageLog` | Same as A | `WebsocketService` only |
| What peers do | gRPC drops same-state updates. gRPC and NetDaemon keep backoff and pacing in a helper separate from the state owner | HA `ConfigEntry` and NetDaemon re-notify on every retry attempt (SETUP_RETRY → SETUP_IN_PROGRESS → SETUP_RETRY) | AppDaemon-like: no state owner feeding history |

**Recommendation:** C. It keeps `OutageLog` on one driver and one owner, and log pacing stays exactly as the Posture promises. (The first pass recommended A; see the Challenge revision below.)
**Peer divergence:** from the issue's wording ("`OutageLog` is driven by transitions"), which is reworded. C matches peers: gRPC and NetDaemon pace from the retry loop, and no surveyed peer feeds a log helper from state transitions (Gap 2; peer-check §3).
**Pick A instead if** `OutageLog` must keep facts a transition consumer reads, and you accept a written handler/`record_failure` protocol with per-path tests. **Pick B instead if** you want `OutageLog` to have exactly one entry point and accept observers filtering non-transitions.
**Reversibility:** easy (internal)
**Challenge revision (2026-11-13):** both critics found that A splits `OutageLog`'s episode and gap fields across two drivers in an unwritten order. On the recv-death path, which is how an HA restart usually ends, the transition fires in the done-callback before `record_failure`. A handler that opened an episode would demote the "Lost connection" WARNING to DEBUG, and the "Reconnected after X" duration would shift, contrary to the Posture. A also gave `OutageLog` shadow copies of `_connected_at` and `_ever_connected`, which `WebsocketService` must keep for `ReconnectPolicy` and the first-connect line. Peers drive pacing from the retry loop, and none feeds a log helper from state transitions (Gap 2; peer-check §3). C removes the split instead of documenting it.
**Ratified:** Chose leaving `OutageLog` on its explicit `record_failure`/`record_core_wait`/`record_connected` calls (C) over feeding its state facts from transitions (A) or same-state notifications (B), so `OutageLog` has one driver in today's order, `WebsocketService` stays the only owner of "connected since" and "ever connected", and log pacing is exactly unchanged, as peers pace from the retry loop, accepting that the issue's criterion "`OutageLog` is driven by transitions" is reworded to "`OutageLog`'s pacing is unchanged". (Revised at the sketch challenge, overriding the first ratification of A.)

### D2: Are transition observers synchronous or awaited?

**Situation:** `set_connection_state` is synchronous. One caller, `_handle_recv_task_done`, is an `asyncio` done-callback and can't await. The existing `ObserverList.notify` is `async`. `OutageLog` is synchronous. #3678's writer would enqueue a database write.

**Deciding factor:** state and observers update together, at the moment of the transition, from every call site including the done-callback.

| | A: sync callbacks, called inline | B: async, awaited | C: sync setter, observers spawned as tasks |
|---|---|---|---|
| `set_connection_state` | Stays sync; every call site unchanged | Becomes `async`. About six call sites change, and the done-callback has to spawn a task to transition | Stays sync |
| Ordering | Observers run before the setter returns, in transition order | In order, but the recv-death transition runs late in a spawned task, so `is_connected` lags | Not guaranteed; `OutageLog` lines can land out of order or after shutdown |
| Observer limits | Must not block; async work gets handed off (a queue or a spawned task) | Any | Any |
| New code | A small sync observer list beside `ObserverList` in `observer_list.py`, with the same log-and-skip behavior | None for the list | Task spawning and lifetime |
| What peers do | gRPC (py, java, go), HA (`ConfigEntry.async_on_state_change`, `@callback`), home-assistant-js-websocket and NetDaemon all use sync callbacks and hand async work off elsewhere | AppDaemon; `transitions`' `AsyncMachine`; python-statemachine | grpc-java runs callbacks on an executor |

**Recommendation:** A, because it is the only option where the done-callback's transition and its observers happen together. It is also the peer norm.
**Peer divergence:** none.
**Pick B instead if** an observer must await I/O before the next transition. **Pick C instead if** observers may be slow and their order doesn't matter.
**Reversibility:** easy (no external observers yet)
**Ratified:** Deferred by D10: not built here. The table and recommendation above are input to the #3678 re-sketch, which designs the observer seam with its consumer (D10 lists what the challenge found it must settle).

### D3: What does an observer receive?

**Note:** this analysis assumed `OutageLog` takes transitions (D1 option A). Under the ratified D1 (C) it takes none, so its `OutageLog` rationale here is stale input for #3678.

**Situation:** the issue proposes `(old, new, detail, at)`. Details that exist today:

- the core state while waiting (`NOT_RUNNING`, `STARTING`), which is HA's own vocabulary
- the failure cause when `handle_connection_failure` moves to CONNECTING: `RetryPlan.cause`, a human-readable string from `describe_failure`. Each plan also carries a closed `Disposition` (FAST, SLOW, AUTH_RETRY, PARK) in `websocket_reconnect.py`
- the rejection when `park()` moves to AUTH_FAILED

The recv-death done-callback has no cause, only a close code. Two questions are in play: the payload's shape (a dataclass or positional args), and whether the detail is free text or a closed enum. Much of what a peer reason enum encodes is already a state in hassette. NetDaemon's `NotReady` is WAITING_FOR_CORE, and its `Unauthorized` is AUTH_FAILED. So `new` already answers "which kind of not-connected" for those cases.

**Deciding factor:** one small, stable payload, with no closed vocabulary that just restates `new`.

| | A: frozen `ConnectionTransition(old, new, detail: str \| None, at)` | B: A plus `disposition: Disposition \| None` | C: dataclass with typed per-state detail (`CoreWait(core_state)`, `Failure(cause, disposition)`) | D: positional args `(old, new, detail, at)` |
|---|---|---|---|---|
| Adding a field later | Additive | Additive | Additive | Breaks every observer's signature |
| Groupable cause (fast vs slow vs auth) | Only by parsing text | Yes, from an enum that already exists, so no new vocabulary | Yes | Only by parsing text |
| Redundancy with `new` | None | `PARK` duplicates AUTH_FAILED | Its classes mirror states | None |
| Consumer code | Reads a string | Reads a string; can `match` the enum | `match` on type | Reads a string |
| Today's consumers | `OutageLog` reads no detail from transitions (D1 keeps the plan on `record_failure`). #3678 only displays the cause and doesn't filter on it (spec 152 D5) | Same; nobody groups yet | Same | Same |
| What peers do, detail kind | HA `ConfigEntry.reason: str \| None`; home-assistant-js-websocket `any`; `transitions`/python-statemachine untyped args | NetDaemon `DisconnectReason {Client, Remote, NotReady, Unauthorized, Error}`, a closed enum | grpc-go `ConnectionError` bound to TransientFailure by convention | n/a: positional args are a shape, not a detail kind |
| What peers do, old/new | Peers pass the new state only | Same | Same | Same |

**Recommendation:** A. No consumer branches on the cause, and the cases a peer enum distinguishes are already states here. A string matches HA, the closest peer. If grouping ever matters, B can be added without breaking anything, using the existing `Disposition` rather than a new enum.
**Peer divergence:**
- **String vs enum:** A matches HA, home-assistant-js-websocket and the FSM libraries. It diverges from NetDaemon's reason enum, because hassette's richer state set already carries most of what that enum distinguishes.
- **Passing `old`:** peers pass only the new state. Hassette passes `old` because `OutageLog` (D1) reacts to *leaving* CONNECTED. Without `old` it would keep a shadow copy of the state, which is the thing this change removes. #3678 doesn't need `old`: its rows are one per change and in order, so a row's from-state is the previous row. Peers (Gatus, Uptime Kuma, Kubernetes conditions, HA's recorder via `old_state_id`) store only the new state. The #3678 re-sketch should reconsider storing a from-state for connection rows.
**Pick B instead if** you want history or logs grouped by cause class now. **Pick C instead if** observers will branch on the detail's kind, not just show it.
**Reversibility:** easy (B is additive on top of A)
**Ratified:** Deferred by D10: not built here. The table and recommendation above are input to the #3678 re-sketch, which designs the observer seam with its consumer (D10 lists what the challenge found it must settle).

### D4: Which clock is `at`?

**Situation:** `OutageLog` measures gaps and episodes on `time.monotonic()`. Its unit tests pass `now` explicitly, so pacing is testable without patching clocks. #3678's rows want wall-clock times. Observers run inline (D2), at the moment of the transition.

**Deciding factor:** `OutageLog` keeps injectable, monotonic pacing; a wall-clock consumer gets an accurate time.

| | A: `at` is a `time.monotonic()` float | B: `at` is a wall-clock `whenever.Instant` | C: both | D: no `at`; observers read their own clock |
|---|---|---|---|---|
| `OutageLog` durations | Safe against clock jumps | Shift with a wall-clock jump | Safe | Safe |
| Testing `OutageLog` | Pass any `at` | Pass any instant, but durations are wall-clock | Pass both | Needs clock patching |
| Wall-clock consumers (#3678) | Stamp `Instant.now()` themselves; exact, since observers run inline | Free | Free | Stamp it themselves |
| What peers do | None passes a timestamp. AppDaemon uses monotonic for durations only | HA `Event.time_fired`, grpc-go channelz: wall-clock where recorded | n/a: no surveyed peer passes any timestamp | Every surveyed peer |

**Recommendation:** A, because it keeps `OutageLog`'s pacing tests as they are, and inline observers make a self-stamped wall time exact.
**Peer divergence:** passing a timestamp at all, which no peer does. It's for testability: `OutageLog` is already built around an injected `now`.
**Pick B instead if** history rows are the main consumer and `OutageLog` can move to wall-clock time. **Pick D instead if** you'd rather match peers and patch the clock in `OutageLog`'s tests.
**Reversibility:** easy
**Ratified:** Deferred by D10: not built here. The table and recommendation above are input to the #3678 re-sketch, which designs the observer seam with its consumer (D10 lists what the challenge found it must settle).

### D5: Does a new observer learn the current state when it registers?

**Note:** this analysis assumed `OutageLog` takes transitions (D1 option A). Under the ratified D1 (C) it takes none, so its `OutageLog` rationale here is stale input for #3678.

**Situation:** the issue proposes `old=None` on the first call. But the initial DISCONNECTED is set directly in `WebsocketService.__init__`, before any observer can register. `OutageLog` registers in `__init__`. `serve()` runs once per process, and its first transition is DISCONNECTED → CONNECTING. #3678's history writer doesn't exist yet, so where it registers, and whether that's before `serve()` starts, is unknown. It wants a row with the session's starting connection state.

**Deciding factor:** an observer is correct however late it registers, without having to know to read the current state first.

| | A: no initial notification; `old` is always a `ConnectionState` | B: replay the current state on registration, with `old=None` | C: route the initial set through `set_connection_state` with `old=None` |
|---|---|---|---|
| Who sees a starting state | Only observers registered before `serve()`, as DISCONNECTED → CONNECTING | Every observer, whenever it registers | Nobody: no observer exists in `__init__` |
| A late observer | Misses earlier transitions; must read `connection_state` itself before subscribing, or it has no starting point | Gets the current state immediately | Misses it |
| Work | None | A registration method on `WebsocketService` that adds the observer, then calls it once with `ConnectionTransition(old=None, new=<current>, detail=None, at=now)`, with the same log-and-skip behavior. About 5 lines plus a test. The sync list itself doesn't know the state, so the replay lives on `WebsocketService` | A one-line change in `__init__` |
| Cost to every observer | None | `old` is `ConnectionState \| None`, so each observer handles `None`. `OutageLog` ignores it: it acts only on leaving or entering CONNECTED and on entering WAITING_FOR_CORE, and none of those has `old=None` | Same type cost, no benefit |
| Race between reading state and subscribing | Not a real race (observers are sync on one loop), but two steps a consumer can forget | None: one call | n/a |
| What peers do | Silent until the first real change: grpc-java, HA `ConfigEntry.async_on_state_change` | grpc-py `subscribe`, grpc-go pubsub, home-assistant-js-websocket collections, and HA's `async_at_started` all replay the current state to a new subscriber | none found |

**Recommendation:** B. It makes every observer order-independent for about five lines. #3678's writer, the next consumer, gets its session-start row wherever it registers. The price is `None` in `old`'s type, which `OutageLog` ignores without trying.
**Peer divergence:** none. It matches the replay-on-subscribe peers (gRPC Python and Go, home-assistant-js-websocket, HA `async_at_started`). It realizes the issue's `old=None` as a replay rather than as the initial set, which would reach nobody.
**Pick A instead if** you'd rather keep `old` non-optional and require observers to register before `serve()`.
**Reversibility:** easy
**Ratified:** Deferred by D10: not built here. The table and recommendation above are input to the #3678 re-sketch, which designs the observer seam with its consumer (D10 lists what the challenge found it must settle).

### D6: When is WAITING_FOR_CORE entered, and how is it left?

**Situation:** the RUNNING gate reads `get_config`. On RUNNING it returns at once. On STOPPING, FINAL_WRITE or STOPPED it raises `CoreShuttingDownError` (a failure). Otherwise it waits for `homeassistant_started`, rechecking every 5 s. The core state can change during the wait, from `NOT_RUNNING` to `STARTING`. Exits:

- RUNNING → CONNECTED
- a failure on that socket → `handle_connection_failure` → CONNECTING
- recv-task death → the done-callback → DISCONNECTED
- shutdown → `cleanup` → DISCONNECTED

Auth happens before the gate, so a token rejection can't happen while waiting.

**Deciding factor:** the state appears only when Hassette actually waits, with no unreachable edges.

| | A: enter only when a `get_config` read is not RUNNING; edges to CONNECTED, CONNECTING and DISCONNECTED | B: enter on every connection before the first `get_config` | C: A, plus a WAITING_FOR_CORE → AUTH_FAILED edge |
|---|---|---|---|
| Healthy connect | CONNECTING → CONNECTED, as today | CONNECTING → WAITING_FOR_CORE → CONNECTED, an extra transition (and an extra #3678 row) per connect | Same as A |
| HA restart | CONNECTED → DISCONNECTED (recv death) → CONNECTING → WAITING_FOR_CORE → CONNECTED; a send failure goes CONNECTED → CONNECTING directly. A drop during the wait goes via DISCONNECTED on recv death, or straight to CONNECTING on other failures | Same, plus a pass through every connect | Same as A |
| Core state changes mid-wait | No transition; the per-recheck `report_connection_status` (D8) and `record_core_wait` (D1) calls carry the new core state | Same | Same |
| Unreachable edges | None | None | One |
| What peers do | HA `SETUP_RETRY` and gRPC A17's unhealthy TRANSIENT_FAILURE are entered only when not ready. AppDaemon keeps the socket and waits; NetDaemon drops it | none found | Auth failure comes only from a fresh handshake in every peer |

**Recommendation:** A. A healthy connect stays two states, and every edge is reachable from a code path.
**Peer divergence:** none for entry and exit. Staying on the socket while waiting matches AppDaemon and gRPC A17, not NetDaemon's drop-and-reconnect, which is spec 131 D12's existing choice.
**Pick B instead if** you want every connect's history to show the gate.
**Reversibility:** easy
**Ratified:** Chose entering WAITING_FOR_CORE only when a `get_config` read reports a core state other than RUNNING (and not shutting down), with edges to CONNECTED, CONNECTING and DISCONNECTED, over entering on every connection or adding an AUTH_FAILED edge, so a healthy connect stays CONNECTING → CONNECTED and every edge is reachable, accepting that a core-state change mid-wait is no transition and reaches only the explicit per-recheck calls (`report_connection_status`, D8, and `record_core_wait`, D1).
**Edges this adds to `WS_VALID_TRANSITIONS`:** CONNECTING → WAITING_FOR_CORE (entry), and WAITING_FOR_CORE → CONNECTED, CONNECTING and DISCONNECTED (exits). WAITING_FOR_CORE is set on each non-RUNNING read. After the first one it's a same-state call, which `set_connection_state` already ignores, so no guard is needed. A first read that reports a shutting-down state raises before the set, so the state stays CONNECTING. The comment above `WS_VALID_TRANSITIONS` (CONNECTING → DISCONNECTED stays, reworded to recv death or shutdown before the first non-RUNNING read; a WAITING_FOR_CORE line is added) and the `wait_for_core_running` docstring ("Hold the connection in CONNECTING…") are updated to match.

### D7: Do the existing connected/disconnected observer lists fold into transition observers?

**Note:** this analysis assumed the sync transition observers that D10 defers. Its outcome is "no change" either way. The question returns in #3678.

**Situation:** `connected_observers` are async and are awaited from `mark_connected` with the connection generation. `StateProxy`'s initial sync runs there. `disconnected_observers` are async and are awaited from `handle_connection_failure`, firing only if the connected ones did (`_observers_announced`). Both lists announce a *usable connection*. Transition observers (D2) are synchronous bookkeeping inside `set_connection_state`.

**Deciding factor:** keep heavy async announcement work off the synchronous transition path.

| | A: keep them separate | B: fold them into transition observers |
|---|---|---|
| `StateProxy`'s initial sync | Stays awaited, as today | Must become a handed-off task, since the sync list can't await |
| Connected/disconnected pairing | Unchanged (`_observers_announced`) | Each observer re-derives from transitions whether a disconnect is owed |
| Mechanisms | Two: sync bookkeeping and async announcements | One |
| What peers do | NetDaemon's OnConnect/OnDisconnect observables are announcements like these, separate from any state stream | none found |

**Recommendation:** A. Folding them in would undo D2 for the heaviest consumer and lose the pairing. The proper tidy-up is a follow-up: the single ordered async announcer tracked as #4101, which would absorb these lists, the ready reason and the bus events together.
**Peer divergence:** none found.
**Pick B instead if** you want one observer mechanism now and accept handing `StateProxy`'s sync off to a task.
**Reversibility:** easy
**Ratified:** Chose keeping the async connected/disconnected announcement lists as they are, over folding them into transition observers, so `StateProxy`'s initial sync stays awaited and the announced/owed pairing is unchanged. With D10 deferring transition observers, this change adds no second mechanism. The question returns in #3678.

### D8: Does the ready reason come from transitions?

**Note:** this analysis assumed the sync transition observers that D10 defers. Its outcome is "no change" either way. The question returns in #3678.

**Situation:** four sites call `report_connection_status(reason)`: `handle_connection_failure`, `park`, `wait_for_core_running` and `mark_connected`. It is `async`, and it emits a readiness event only when the reason changes, a rule the acceptance criteria keep. Shutdown's reason wins. The reasons don't map one-to-one onto states. CONNECTING after a failure is `NOT_CONNECTED_REASON`. The core wait is `CORE_NOT_RUNNING_REASON` formatted with the core state, which `test_websocket_readiness_events.py` asserts. That reason changes when the core state changes mid-wait, which per D6 is not a transition.

**Deciding factor:** don't put async work behind synchronous observers, and keep the reason tracking the core state.

| | A: keep the explicit calls | B: a transition observer derives the reason |
|---|---|---|
| Async emit | Awaited where it happens today | The sync observer (D2) has to spawn a task per emit, so emits can land out of order |
| Core state changes mid-wait | Each recheck reports the new core state, as today | No transition fires, so the reason goes stale unless the recheck still calls it explicitly, leaving two paths |
| Call sites | Four, unchanged; the WAITING_FOR_CORE transition sits next to its reason in `wait_for_core_running` | Fewer, but the recheck call stays |
| What peers do | none found | none found |

**Recommendation:** A. Deriving the reason can't track the core state mid-wait without keeping an explicit call anyway, and it adds a task spawn behind a sync observer. The async-announcer follow-up (#4101) is where deriving it belongs.
**Peer divergence:** none found.
**Pick B instead if** you accept a spawned task per readiness emit plus a remaining explicit call for core-state changes.
**Reversibility:** easy
**Ratified:** Chose keeping the four explicit, awaited `report_connection_status` calls over deriving the reason in a transition observer, so the reason keeps tracking the core state on each recheck and no task is spawned behind a sync observer, accepting that each transition's reason is set beside it by hand until the async-announcer follow-up (#4101, parked behind #3678).

### D9: Does the test helper's "mark connected" go through `set_connection_state`?

**Situation:** `mark_websocket_service_connected` in `src/hassette/testing/_ws_mocks.py` (a private module of the testing package) writes `_connection_state = CONNECTED` and `_ever_connected = True` directly. Its only callers are hassette's own tests (the websocket integration tests and `tests/unit/core/test_websocket_service_coverage.py`). Apart from the initial DISCONNECTED in `WebsocketService.__init__`, it's the one direct state write in `src/` outside the setter, so it bypasses the setter's ever-connected latch and its transition validation and logging. Unit tests that assign `_connection_state` to set up a scenario are fixture setup, not product behavior.

**Deciding factor:** "`set_connection_state` is the only place connection state changes after initialization" holds for everything under `src/`.

| | A: route it through `set_connection_state` | B: leave the direct write |
|---|---|---|
| The acceptance criterion's "only place" | Holds for `src/` | One exception in `src/`, documented on the helper |
| Ever-connected latch | Set by the setter, as in production | Set by hand |
| `OutageLog` | Not called: the helper calls no `record_*` method today and still won't (D1) | Not called |
| Starting state | From DISCONNECTED it steps through CONNECTING to CONNECTED, so no invalid-transition warning. From CONNECTING it goes straight to CONNECTED | Any |
| Side effect | The first-ever CONNECTED logs the INFO "Connected to Home Assistant at …" line in those tests | None |
| Work | About 3 lines | None |

**Recommendation:** A. It's a few lines, and it makes the single-writer rule true without an asterisk. Test-setup writes in `tests/` stay as they are.
**Peer divergence:** none found.
**Pick B instead if** harness connections shouldn't emit the first-connect log line or go through transition validation.
**Reversibility:** easy
**Ratified:** Chose routing `mark_websocket_service_connected` through `set_connection_state` (stepping via CONNECTING from DISCONNECTED) over keeping its direct write, so the single-writer rule holds for all of `src/` and harness connections set the ever-connected latch through the setter as in production, accepting the first-connect INFO line in those tests.
**Order and scope:** the setter calls come before `_configure_websocket_external_readiness_primitives`, because leaving any state for CONNECTING clears `_connected_event` and `_connected_generation`. The helper is called only on a fresh service, in DISCONNECTED or CONNECTING; any other starting state is a test bug. Only AUTH_FAILED makes the setter warn; WAITING_FOR_CORE → CONNECTED is a valid edge and CONNECTED is a same-state no-op, so neither reports the misuse.

### D10: Are transition observers built here, or with their first consumer?

**Situation:** with `OutageLog` on its explicit calls (D1), the transition observer list would have no production observer in this change. Its only planned consumer is #3678's history writer. That spec is paused and gets re-sketched after this lands (`git show 3678:design/specs/152-lifecycle-history-writers/pause-note.md`). The challenge found the ratified payload doesn't fit that writer. It lacks a flap flag and an outage length. Recv death emits two transitions for one loss, with the cause on the second. And the replay serves a session-start row spec 152 doesn't write. What #3678 depends on from this issue is a single writer and WAITING_FOR_CORE as a real state.

**Deciding factor:** design the seam with the consumer that uses it, so the payload fits the first time.

| | A: defer the list and payload to #3678 | B: build now, reshaped against spec 152's rows | C: build as ratified (D2–D5) |
|---|---|---|---|
| This change | The new state (D6) and the single-writer rule (D9) | A plus the list and payload, reshaped for flap, outage length and the recv-death sequence | A plus the list, payload and replay |
| Code with no consumer here | None | List and payload (tests only) | List, payload and replay |
| Payload fit | Designed in the #3678 re-sketch with the writer | Guessed against a paused ledger about to be revised | Known not to fit |
| Issue criterion "notifies registered observers" | Moves to #3678; this issue is reworded | Met | Met |
| What peers do | gRPC, HA and NetDaemon have state callbacks; when to add one isn't a peer question | Same: not a peer question | Same: not a peer question |

**Recommendation:** A. It drops about four decisions' worth of code nothing uses yet, and lets #3678 settle the payload and the recv-death sequence with the real consumer in hand.
**Pick B instead if** this issue must deliver the observer seam as written. **Pick C instead if** you'd ship the seam now and let #3678 extend it additively.
**Reversibility:** easy
**Ratified:** Chose deferring the transition observer list, `ConnectionTransition` payload, `detail` argument and replay to the #3678 re-sketch (D2–D5 carried as input) over building them now reshaped or as ratified, so the seam is designed with its consumer and nothing here lacks one, accepting that `set_connection_state` keeps its `(new)` signature and issue #4091's observer and detail criteria move to #3678. (Added at the sketch challenge.)

## Assumed

- `serve()` runs once per process: "Nothing restarts a service in-process" (`src/hassette/resources/service.py`, the `Service` docstring). So `serve()`'s first transition is always DISCONNECTED → CONNECTING. Evidence: `websocket_service.py`, `serve()`.
- A failed attempt that never reads a non-RUNNING core stays in CONNECTING with no per-attempt transition (apart from DISCONNECTED on recv death), and `is_connected` stays `== CONNECTED`. Evidence: issue #4091 body; spec 131 D10 (`tests/unit/core/test_ws_connection_state.py`, `ALLOWED_TRANSITIONS` docstring).
- `dispatch_hass_event` gates on `!= CONNECTED` (`src/hassette/core/websocket_io.py`), so WAITING_FOR_CORE keeps holding and dropping events exactly as CONNECTING does during the gate.
- `ReconnectPolicy.on_connection_ended(connected_for)` still needs `connected_for` in `handle_connection_failure`, so `WebsocketService._connected_at` stays for the policy. `is_stable_connection` remains the one stability test both use. Evidence: `websocket_reconnect.py`, `is_stable_connection` docstring.
- The first-ever CONNECTED INFO line ("Connected to Home Assistant at …") stays in `set_connection_state`; reconnect lines stay in `OutageLog`. Evidence: `set_connection_state` docstring.
- The unit-test transition table (`ALLOWED_TRANSITIONS` in `tests/unit/core/test_ws_connection_state.py`, spec 131 D10) gains the D6 edges; log pacing stays as Posture states.
- `ConnectionState` is exported from `hassette.types`. A new member is additive. Evidence: `src/hassette/types/__init__.py`.
- Nothing outside `websocket_service.py`, `websocket_io.py` and the testing mocks reads or writes the connection state. Evidence: grep for `ConnectionState`/`connection_state` across `src/`, `wire/`, `client/`.

## Build

- [x] Implementation and tests committed
- [x] Docs (`.claude/rules/core-startup.md`, the `ConnectionState`/`wait_for_core_running`/harness docstrings and the `WS_VALID_TRANSITIONS` comment; no docs pages, per Posture)
- [x] Ship-time challenge

**Calls made during the build:**
- `wait_for_core_running` sets WAITING_FOR_CORE before awaiting `report_connection_status`: the state is synchronous bookkeeping, so it reads correctly to anything the readiness event wakes.
- For the #3678 re-sketch: an attempt that waits for the core and then fails transitions out of WAITING_FOR_CORE each time (WAITING_FOR_CORE → CONNECTING, or WAITING_FOR_CORE → DISCONNECTED → CONNECTING on recv death), as gRPC, HA `ConfigEntry` and NetDaemon also do per retry (peer-check §3). A row writer sees these per attempt. The core state being waited on (NOT_RUNNING vs STARTING) lives only in the ready reason and `OutageLog.record_core_wait` (D6, D8); the re-sketch should give it a typed source rather than parse the reason text.
- `test_dispatch_drops_events_before_connected` gains WAITING_FOR_CORE: it pins the Assumed claim that the dispatch gate holds events in the new state as it does in CONNECTING.
