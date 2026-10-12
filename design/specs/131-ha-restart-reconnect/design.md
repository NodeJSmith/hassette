# Design: Stay up and reconnect through Home Assistant restarts

**Date:** 2026-10-12
**Status:** built
**Mode:** sketch
**Issues:** #2701

## Summary

Today an HA restart kills Hassette. A long-lived WebSocket drops, `ServiceWatcher` restarts `WebsocketService`, and the tenacity layer in `make_connection` (`src/hassette/core/websocket_service.py`) gets five connection refusals. It then raises `CouldNotFindHomeAssistantError`, a `FatalError` (`src/hassette/exceptions.py:159`). `_serve_wrapper` routes that to `handle_crash` (`src/hassette/resources/service.py:196-199`) and the process exits. The add-on path also hits this while the Supervisor restarts, and it loops through full service restarts while Core answers HTTP 502.

The change replaces the three stacked retry layers (tenacity in `make_connection`, the early-drop loop in `serve()` plus `src/hassette/core/early_drop_policy.py`, and ServiceWatcher restarts) with one reconnect loop inside `WebsocketService.serve()` (D1), which classifies failures per D9. Apps keep running against a STALE cache through an outage.

**In scope** (files: `src/hassette/core/websocket_service.py`, `src/hassette/core/state_proxy.py`, `src/hassette/exceptions.py`, `src/hassette/types/enums.py`, `src/hassette/config/models.py`, `src/hassette/testing/config.py`, `src/hassette/testing/_ws_mocks.py`, `hassette.schema.json`, `ruff.toml`):
- The reconnect loop and its failure classification (D1, D2, D8, D9, D11).
- Auth-rejected handling and `ConnectionState.AUTH_FAILED` (D3, D10).
- The RUNNING gate, including deleting `wait_initial_connection` / `_first_connection_attempt_done_event` (D4, D12).
- `max_msg_size` and 1009 handling (D13).
- StateProxy sync-retry timing (D14).
- Failing pending response futures (`PendingResponses.fail_all`) the moment the recv task ends, not only in `partial_cleanup`/`cleanup` (see the Assumed bullet on pending futures).
- Deletions: the websocket retry/early-drop config fields listed in Assumed, `early_drop_policy.py` (and its `ruff.toml` S311 ignore), the `hassette.testing` `TEST_EARLY_DROP_*` constants (`src/hassette/testing/config.py`), and `CouldNotFindHomeAssistantError` (D7). The PR carries one `BREAKING CHANGE:` footer covering all of them, plus regenerated `hassette.schema.json`.
- Docs: `docs/pages/operating/index.md`, `docs/pages/troubleshooting.md`, `docs/pages/core-concepts/internals/service-details.md`, `docs/pages/core-concepts/internals/lifecycle.md`, `docs/pages/configuration/index.md`, `docs/pages/web-ui/health-endpoints.md`. They include a migration note for apps that relied on the process restart after an HA reboot (see Assumed) and the stale-cache consequence below.
- Tests, including a system test where an HA restart ends a connection that had been CONNECTED longer than D8's reset window and Hassette recovers in the same process, without ServiceWatcher restarts.

**Out of scope:**
- #1676, a framework "HA restarted" signal for apps. It ships separately: HA emits no restart signal that is reachable on both the direct and the Supervisor-proxy paths.
- Replaying events missed during the gap.
- REST (`ApiResource`) auth handling.
- Coalescing persisted app telemetry for connection-closed API failures during a long outage. Apps keep running on a STALE cache and their failing HA calls each persist an error row; the docs migration note states this alongside the #1676 pointer (sketch challenge, Finding 13).

Prior work: `design/research/2026-10-12-ha-restart-reconnect/research.md`. Its F-numbers (F1-F21) are cited below.

## Decisions

### D1: Reconnect architecture

**Deciding factor:** stop routing HA outages through ServiceWatcher teardown, and match prior art.

| | A: single in-loop reconnect in `serve()` | B: reclassify `CouldNotFindHomeAssistantError` as non-fatal only |
|---|---|---|
| Ends process exit on HA restart | yes | yes |
| Outages avoid ServiceWatcher teardown / #1716 escalation | yes | no; a full teardown about every 19 s |
| Retry layers left | 1 | 3 |
| Size | medium-large (loop, fake WS server, tests, docs) | small |

**Recommendation:** A, because every surveyed HA client reconnects in place and B keeps the #1716 exposure.
**Pick B instead if** the add-on milestone could not wait for A's test infrastructure.
**Reversibility:** hard (rewrites the connection core)
**Ratified:** Chose A over B, to take outages out of ServiceWatcher and delete two retry layers, accepting a rewrite of `serve()` and its test suite. (Ratified during research, 2026-10-12.)

### D2: Backoff cap

**Deciding factor:** recovery within a few seconds of HA returning.

| | A: ~5 s | B: 10 s | C: 30 s |
|---|---|---|---|
| Worst-case added delay after HA returns | ~5 s | ~10 s | ~30 s |
| Prior art | js-websocket, node-red, AppDaemon | HA MQTT, remote_homeassistant | none of the surveyed HA clients |
| Load on HA / Supervisor proxy | one attempt per 5 s, trivial | lower | lowest |

**Recommendation:** A, because it matches HA's own frontend client.
**Pick B instead if** attempt volume during long outages mattered. **Pick C instead if** you wanted it to be quiet above all else.
**Reversibility:** easy (a constant)
**Ratified:** Chose a ~5 s cap over 10 s and 30 s, to recover within seconds of HA returning, accepting one connection attempt every ~5 s during long outages. (Ratified during research.)

### D3: Behavior on `auth_invalid`

**Deciding factor:** never exit, never generate repeated failed-login side effects in HA (F20), and don't strand a previously working token on a false rejection.

| | A: stay up, stop retrying | B: retry every 5-10 min | C: 3 retries 60 s apart for every rejected token, then park | D: park immediately if never connected; if a connection has ever succeeded, 3 retries 60 s apart, then park |
|---|---|---|---|---|
| Process exits | no | no | no | no |
| HA "Login attempt failed" notifications / ban count | 1 | 1 per interval, unbounded | up to 4 | 1 (never connected) or up to 4 (after a prior success) |
| Recovers from a token rotated in HA without a Hassette restart | no | yes | no | no |
| Recovers from a false rejection (HA host clock behind the token's `iat` at boot) | no | yes | yes, if it clears within ~3 min, including when Hassette restarted with the host | only if Hassette outlived the reboot; a co-hosted cold boot starts never-connected and parks |
| Prior art | js-ws, node-red, HA MQTT, config entries | ESPHome-style pinned backoff | none | ESPHome-like (retries auth at 60 s before HA stops it) |
| Added state | none | a timer | a counter | a counter keyed on `has_ever_connected` |
| Time to the CRITICAL "fix the token" line for a mistyped token | immediate | never (retries forever) | ~3 min | immediate |

**Recommendation:** D. A token that never worked is a config error and keeps A's profile. A token that worked before and is rejected during an HA reboot can be a clock-skew false rejection (see Assumed), and gets a few spaced attempts.
**Pick A instead if** clock skew on an HA host is too rare to design for. **Pick B instead if** tokens were rotated in HA without touching Hassette's config. **Pick C instead if** you want bounded retries even for a never-working token.
**Reversibility:** easy
**Ratified:** Chose C (3 retries 60 s apart for every rejected token, then park) over D's immediate park for a never-connected process, to recover from clock-skew false rejections when Hassette reboots with the HA host, accepting up to 4 failed-login notifications and a ~3 min wait for the CRITICAL line on a mistyped token. (Originally A during research; D in the sketch challenge, Finding 2; C in the ship-time challenge, Finding 3: `has_ever_connected` is always false after a co-hosted reboot, the very case D's retries were for.) How the parked state is represented is D10.

### D4: Core-state (`RUNNING`) awareness scope

**Deciding factor:** apps never initialize, and the cache never settles, against a half-loaded HA (F8).

| | A: resync at RUNNING and gate first bootstrap on RUNNING | B: resync at RUNNING only | C: defer |
|---|---|---|---|
| Cold start against a booting HA | apps wait for RUNNING | apps may init on a partial snapshot | same as B |
| Reconnect during HA boot | cache converges at RUNNING | same as A | stays partial until entities change |
| Prior art | AppDaemon #2226, node-red | js-ws frontend partial | none |

**Recommendation:** A, because it covers both halves of the scope (cold start and reconnect).
**Pick B instead if** app startup latency on a slow-booting HA mattered more than snapshot completeness. **Pick C instead if** the loop needed to ship alone.
**Reversibility:** easy
**Ratified:** Chose RUNNING-gated resync plus RUNNING-gated first bootstrap over resync-only or deferring, to keep apps off a half-loaded HA, accepting later app startup while HA boots. (Ratified during research.) The mechanism is D12.

### D5: Configurability of reconnect timing

**Deciding factor:** smallest config surface.

**Recommendation:** module constants only, matching js-ws and node-red.
**Pick configurable fields instead if** a user reports a network where the 5 s cap is wrong.
**Reversibility:** easy (a field can be added later)
**Ratified:** Chose module constants over 2-3 config fields, to keep the surface small, accepting no per-install tuning. (Ratified during research.)

### D6: Opt-in "exit if HA unreachable for N seconds"

**Deciding factor:** no prior art, and spec 018 already rejected the equivalent `require_ha_connection`.

**Recommendation:** don't add it. A degraded `/api/health` already lets an external supervisor decide to restart.
**Pick adding it instead if** a deployment can only express recovery as a process restart.
**Reversibility:** easy
**Ratified:** Chose not to add an exit setting, to keep Hassette alive through any outage, accepting that supervisor-driven restarts must use the health endpoints. (Ratified during research.)

### D7: Fate of `CouldNotFindHomeAssistantError`

**Deciding factor:** pre-v1 with no compatibility shims.

**Recommendation:** delete it from `exceptions.py` and `__all__`. Nothing raises it once refused connections stay in the loop. Use a `BREAKING CHANGE:` footer.
**Pick keeping it as a non-fatal `HassetteError` instead if** a caller needed to catch it, but nothing would raise it.
**Reversibility:** easy
**Ratified:** Chose deletion over a non-fatal rebase, to leave no dead public type, accepting a breaking change for any user code that catches it. (Ratified during research.)

### D8: Backoff curve and reset rule

**Deciding factor:** reach the 5 s cap fast, and never hot-loop when the Supervisor proxy accepts then drops (F1, node-red #76).

| | A: exponential 1, 2, 4, then 5 s, ±20% jitter; reset after 2 min CONNECTED | B: linear 0, 1, 2, 3, 4, then 5 s, no jitter (js-ws); reset after 2 min CONNECTED | C: fixed 5 s; no reset needed |
|---|---|---|---|
| Time to first retry after a drop | ~1 s | 0 s (immediate) | 5 s |
| Hot-loop risk on accept-then-drop or a flapping link | none (the reset needs 2 min CONNECTED) | none (same reset rule) | none |
| Wasted attempts during a typical 20-60 s HA restart | ~4 + one per 5 s | ~5 + one per 5 s | one per 5 s |
| Prior art | AWS / general guidance | HA frontend | node-red, AppDaemon |
| Behavior a test pins | attempts 1-4 delays inside the jitter bands, then ≤5 s; reset only after 2 min CONNECTED | exact sequence | constant |

**Recommendation:** A, because a 1 s first retry handles network blips quickly without an immediate retry while the server is still closing. Jitter costs nothing.
**Pick B instead if** you want exact parity with HA's frontend client. **Pick C instead if** you want the simplest possible loop and accept a 5 s delay on every blip.
**Reversibility:** easy (constants)
**Ratified:** Chose exponential 1/2/4/5 s with ±20% jitter and a reset after 2 min CONNECTED over linear or fixed backoff, to recover from blips in ~1 s without hot-looping on accept-then-drop or a flapping link, accepting a few extra attempts early in an outage. (The reset window was 30 s at first ratification; the sketch challenge raised it to 2 min.)

**Amended by the sketch challenge (Findings 7 and 8; recommended options taken as clear-cut):**
- Jitter is applied before the cap, so no Fast delay exceeds 5 s (D2).
- The reset clock measures time in CONNECTED (D12), not time since the socket opened.
- The reset window is 2 min, not 30 s: a drop that ends a connection shorter than 2 min continues the curve where it was. This bounds a flapping upstream's reconnects, and with them the resyncs, bus events and log lines each success triggers. Flaps are counted in D11's periodic summary.
- This curve is the Fast disposition's pace (D9); the Slow and Park dispositions don't use it.

### D9: How the loop classifies failures

**Deciding factor:** no HA-side condition can stop the process or tear the service down; a failure that recurs identically and can't heal on its own is retried slowly and reported loudly; strict-mode lifecycle bugs still fail tests. (Re-evaluated in the sketch challenge, Finding 1, which converged Findings 2-6.)

Four dispositions. A failure is classified by what failed, not only by how often, because the commonest failures during an HA restart (refused, Docker's embedded DNS returning NXDOMAIN for a stopped `homeassistant` container, see Assumed) can last 20+ minutes during a DB migration and must still recover within seconds.

| Disposition | What lands there | Pace | Logging (D11) |
|---|---|---|---|
| **Propagate** (re-raised, never caught by the loop) | cancellation (`BaseException`); `InvalidLifecycleTransitionError` (strict lifecycle mode, forced on by the test harness, `src/hassette/testing/_harness.py:314`); `MemoryError` | n/a: `_serve_wrapper` / ServiceWatcher / the failing test | normal |
| **Fast** (default: everything not named elsewhere) | refused; DNS failures; connect/handshake/auth timeouts; handshake 5xx (Supervisor proxy 502); close right after `auth_ok`; peer close or heartbeat loss of an established socket; a 1009 that isn't the 3rd in a row; HA reporting STOPPING/FINAL_WRITE during the RUNNING wait (D12); any unexpected exception, including proxy oddities (`RuntimeError("Unexpected authentication response")`, the `auth_required` assertion) | D8 curve, 1/2/4/5 s | D11 Fast cadence |
| **Slow** (recurring, won't heal without an upstream fix) | handshake 401, 403, 429; a certificate the client rejects; 1009 on 3 consecutive attempts | fixed 5 min; a 429 waits its `Retry-After` when present, capped at 30 min | ERROR naming the cause on every attempt (~12/h) |
| **Park** (stop retrying until restart) | `auth_invalid` per D3: after 3 retries 60 s apart | none: `ConnectionState.AUTH_FAILED` (D10), `serve()` waits until shutdown | CRITICAL once |

Any connection that reaches CONNECTED returns the loop to the Fast disposition. The consecutive-1009 counter clears only when a connection stays CONNECTED for D8's 2-min reset window, or when a failure other than 1009 breaks the streak (amended at build time: an oversized `get_states` is only ever sent after CONNECTED, so clearing at CONNECTED would keep the counter at 1 forever).

| | A: four dispositions (above) | B: two buckets (catch-all Fast; Park for `auth_invalid`) | C: allowlist; unknowns propagate to ServiceWatcher |
|---|---|---|---|
| Requests to a WAF / reverse-proxy ban list per day on a 401/403 | ~288 (stays under fail2ban's default 5 failures in 10 min) | ~17,000 | ~17,000 |
| Deterministic oversized `get_states` (F6) | ~12 full serializations/h | ~600/h | ~600/h |
| Strict-mode lifecycle bug in tests | fails the test | retried every 5 s; test hangs | fails via ServiceWatcher |
| Proxy oddities | retried in place | retried in place | ServiceWatcher teardown, #1716-exposed |
| Recovery after an upstream fix (proxy, cert) | ≤5 min | ≤5 s | ≤5 s |
| Prior art | Fast + Park are convention (js-ws, node-red, MQTT, config entries); a slower pin for won't-heal causes has precedent in aioesphomeapi (60 s); the 5 min interval is Hassette's own, chosen for fail2ban defaults | convention | none |

**Recommendation:** A. It keeps the conventional Fast and Park behavior and adds one slow pace for causes that a retry can't fix.
**Pick B instead if** reverse-proxy-with-auth deployments and very large installs are out of audience. **Pick C instead if** you'd rather unknown bugs surface as service restarts.
**Reversibility:** easy
**Ratified:** Chose four dispositions (Propagate / Fast / Slow at a fixed 5 min / Park) over the two-bucket catch-all, to stop hammering ban lists and oversized fetches while keeping refused and DNS recovery fast and strict-mode bugs loud, accepting up to 5 min to notice an upstream fix for 401/403/429, certificate and 1009 failures. (Originally a two-bucket catch-all; revised in the sketch challenge, Finding 1, with the user choosing the 5 min interval over 60 s and no slow tier. The ship-time challenge, Findings 4 and 5, moved a handshake 404 and non-certificate TLS errors to Fast: a reverse proxy answers 404 while the HA container behind it restarts, and an EOF or reset mid-handshake is a TLS listener restarting.)

### D10: How the auth-rejected state is represented

**Deciding factor:** the user can see why Hassette is idle without reading logs, and a later UI (#1926) can tell "retrying on its own" from "needs action" without string-matching.

| | A: new `ConnectionState.AUTH_FAILED` plus a ready reason "Home Assistant rejected the access token" | B: `DISCONNECTED` plus the same ready reason | C: B plus a new health `status` value `"auth_failed"` |
|---|---|---|---|
| Visible in `/api/health` / UI now | via `ServiceInfo.ready_phase` (rendered by `frontend/src/components/diagnostics/service-row.tsx`) | same | as the top-level status |
| Typed signal for #1926's connection banner | yes: #1926 surfaces the state on the wire | no: #1926 must string-match the reason or add the state itself | yes, but decided here instead of in #1926 |
| Public surface change | one member on the public `hassette.types.ConnectionState`, which is not breaking; two new `WS_VALID_TRANSITIONS` edges (full table below) (F19). No consumer outside `websocket_service.py` branches on `ConnectionState` (other consumers use `is_connected`, which is false here); `src/hassette/testing/_ws_mocks.py:101` sets it directly and is a touch point. No wire, schema, frontend or client change | none | `SystemStatusResponse.status` literal, which needs frontend, API schema and `client_compat` changes |
| `serve()` after rejection | parks until shutdown | parks until shutdown | parks until shutdown |
| Health top-level status | `starting` (never connected) or `degraded` (had connected) | same | `auth_failed` |
| Log | CRITICAL with the remediation, once | same | same |

**Recommendation:** A, because it gives #1926 a typed state at the cost of one enum member and two transitions, with no wire or frontend change now. The ready reason covers today's Diagnostics view.
**Pick B instead if** no consumer will ever branch on auth failure. **Pick C instead if** auth failure must be on the dashboard header in this PR.
**Reversibility:** A is hard to remove once public (adding is easy); B is easy; C is hard
**Ratified:** Chose a new `ConnectionState.AUTH_FAILED` plus a ready reason over plain `DISCONNECTED` or a new health status, to give #1926 a typed "needs action" signal, accepting one new public enum member and two state transitions. The ready reason carries every connection status, while lifecycle readiness stays set from `on_initialize` to shutdown (ship-time challenge, Finding 2): clearing readiness to change a displayed string put the startup wave at risk and needed a private-field write. A typed connection state on the wire belongs to #1926 (scope noted there); the ship-time challenge, Finding 7, kept `/api/health`'s `starting` for a parked never-connected process until then.

Post-change `WS_VALID_TRANSITIONS` (sketch challenge, Finding 12), with the code path that writes each edge once `handle_early_drop`, `handle_genuine_failure` and the tenacity layer are gone:

| From → To | Trigger / writer |
|---|---|
| DISCONNECTED → CONNECTING | `serve()` starts its first attempt; the loop starts the next attempt after a recv-task death (`_handle_recv_task_done` may already have set DISCONNECTED) |
| CONNECTING → CONNECTED | the D12 RUNNING gate passes (`get_config` RUNNING or `homeassistant_started`) |
| CONNECTING → AUTH_FAILED | the D3 park condition is met |
| CONNECTING → DISCONNECTED | the recv task dies during the D12 RUNNING wait (`_handle_recv_task_done`); shutdown `cleanup()` |
| CONNECTED → CONNECTING | the loop handles a drop of an established connection |
| CONNECTED → DISCONNECTED | `_handle_recv_task_done` (recv task died); shutdown `cleanup()` |
| AUTH_FAILED → DISCONNECTED | shutdown `cleanup()` |

Failed attempts and their backoffs (connect, handshake or auth failures, D3's spaced auth retries, a non-RUNNING close per D12) stay in CONNECTING with no transition, so a long outage produces no per-attempt state changes or readiness events (D11). AUTH_FAILED has no edge back to CONNECTING: leaving it takes a process restart. A test pins every (from, to) pair against this table.


### D11: Logging and readiness-event cadence during an outage

**Deciding factor:** a multi-hour outage must not flood the persisted log DB or the bus, yet must stay visible (F7, F16).

| | A: WARNING on the first failure; DEBUG per attempt; WARNING "still unreachable after N min" every 5 min; INFO on recovery with the outage duration; readiness events only on state transitions | B: WARNING every attempt; readiness event every attempt | C: WARNING on the first failure, INFO on recovery, nothing in between |
|---|---|---|---|
| Log rows over a 1 h Fast-disposition outage (a Slow-disposition outage adds an ERROR per attempt, ~12/h, per D9) | ~13 | ~720 | 2 |
| Visible that it's still down | yes, periodic | yes, noisy | only via health |
| Unexpected-exception tracebacks (D9 Fast) | the first occurrence of each (exception type, innermost frame file:line) gets a traceback; repeats go into the periodic summary | every attempt | first only |
| First-startup hint ("check `base_url`") | while no connection has ever succeeded, the first failure and every 5-min summary are ERROR and repeat the hint | every attempt | first only |

**Recommendation:** A, matching aioesphomeapi's pattern. It bounds rows to a constant per hour while keeping the outage visible.
**Pick C instead if** you consider health and UI sufficient and want minimal logs. **Pick B instead if** you were debugging the loop itself (DEBUG level already gives you that).
**Reversibility:** easy
**Ratified:** Chose first-failure WARNING, a 5-minute "still unreachable" WARNING, INFO on recovery, DEBUG per attempt and transition-only readiness events over per-attempt or first/last-only logging, to keep a long outage visible at ~13 rows/hour, accepting up to 5 minutes between visible log updates. (Ship-time challenge: a flap's recovery logs at DEBUG and only the summaries count flaps, Finding 8, because the D8 reset window alone left a flapping link at hundreds of INFO rows an hour; the summary is ERROR while an unexpected error keeps recurring, Finding 6; and a status event fires whenever the ready reason changes, Finding 2.)

**Amended by the sketch challenge (Findings 1, 5, 6, 7, 8):**
- While `has_ever_connected` is false, the first failure and each 5-min summary log at ERROR with the `base_url` hint, replacing the fail-fast exit a mistyped `base_url` used to get (Finding 6, folded into the Finding 1 re-evaluation).
- Traceback dedupe is keyed on (exception type, innermost frame file:line), not type alone (Finding 5).
- The Slow disposition (D9) logs an ERROR naming the cause on every attempt; Park logs CRITICAL once.
- The 5-min summary includes the flap count (connections that ended before the D8 2-min reset window) (Finding 7).
- During the D12 RUNNING wait the summary says "Home Assistant is reachable; core state is X, waiting for RUNNING", not "still unreachable" (Finding 8).

### D12: Where the RUNNING gate lives

**Deciding factor:** one clear meaning of "connected", and no partial snapshot ever committed as authoritative (F8, F11).

| | A: connection-level: after subscribe, `WebsocketService` calls `get_config`; if not RUNNING it stays CONNECTING with the recv loop running, and becomes CONNECTED (observers, StateProxy resync, bootstrap release) only on `homeassistant_started` or a re-checked `get_config` showing RUNNING | B: StateProxy-level: CONNECTED immediately; StateProxy commits a provisional snapshot, does not open the initial-capability latch, and resyncs again on `homeassistant_started` or a poll-tick `get_config` RUNNING |
|---|---|---|
| Concepts added | one wait step inside the connect sequence | a "provisional" sync cause plus a second trigger in StateProxy |
| App API calls during HA STARTING | refused by `Api`'s `is_connected` check (`src/hassette/api/api.py:346-353`), the same as during an outage | allowed; services may be missing |
| Events received during HA boot (the `unavailable` storm, F10) | not dispatched to apps until RUNNING (dropped, like node-red) | dispatched |
| Health during HA boot | `starting` / `degraded` | `degraded` (connected, but bootstrap not released until RUNNING) |
| Add-on path (proxy returns 502 until RUNNING) | the check always passes immediately | same |
| Missed-`homeassistant_started` fallback | re-check `get_config` on a fixed interval while waiting | StateProxy poll tick (lost if polling is disabled) |

**Recommendation:** A. "Connected" then means "HA is usable", which every consumer (StateProxy, bootstrap gate, health, apps' API calls) already assumes. It needs no second resync concept and doesn't depend on polling being enabled.
**Pick B instead if** apps must be able to call services while HA is still STARTING.
**Reversibility:** easy
**Ratified:** Chose a connection-level gate (CONNECTED only once `get_config` reports RUNNING or `homeassistant_started` arrives, re-checking `get_config` every 5 s while waiting) over a StateProxy provisional-snapshot model, so that "connected" means "HA is usable" for every consumer, accepting that HA-boot events are not dispatched and app API calls wait until RUNNING. A `homeassistant_started` the gate catches is held and dispatched to the bus right after CONNECTED, so direct-path apps can still react to a real HA restart (ship-time challenge, Finding 14).

**Behavior the build must hold (sketch challenge, Findings 8-11):**
- **The wait's `get_config` calls** go through `WebsocketService.send_and_wait` on the auth-level send gate (`_send_ready_event`), not through `Api.get_config`. `Api.get_config` refuses whenever the state isn't CONNECTED (Finding 11).
- **Where events are dropped:** `dispatch_hass_event`, while `connection_state != CONNECTED`. `homeassistant_started` received during the wait is consumed by the gate to trigger CONNECTED. `result` messages take the separate `dispatch` branch and are unaffected. Dropped events are never stamped, so no event with a `None` generation reaches StateProxy (Finding 9).
- **Visibility:** the wait sets the ready reason "Home Assistant core state is X, waiting for RUNNING" and is reported per D11 (Finding 8).
- **Non-starting states:** a `get_config` state of STOPPING or FINAL_WRITE during the wait counts as a failed attempt: close the socket and back off per D9 Fast (Finding 8).
- **No deadline.** HA bounds STARTING at 15 s (see Assumed), so a wait that never ends means HA itself is wedged; it stays visible rather than proceeding against a half-loaded HA (Finding 8).
- **Removed primitive:** `_first_connection_attempt_done_event` and `wait_initial_connection` are deleted, including the `hassette.testing` mock (`src/hassette/testing/_ws_mocks.py:89`). With no retry budget to exhaust, they only produced a false WARNING on slow boots. `StateProxy._bootstrap_initial_sync` checks `get_connected_generation()` after registering its connected observer, and the observer covers every later connection (Finding 10).

### D13: Message size limit and close code 1009

Close code 1009 is the WebSocket "Message Too Big" code (RFC 6455): aiohttp closes with it when an incoming message exceeds `max_msg_size`, which defaults to 4 MiB. Hassette sets no override today.

**Deciding factor:** a large install must not loop forever on an oversized `get_states` (F6, AppDaemon #2676).

| | A: `max_msg_size` 16 MiB constant; 1009 is transient, with an ERROR naming the limit | B: 16 MiB; 1009 is terminal like auth (D10), so Hassette stays up and stops | C: no limit (`max_msg_size=0`); 1009 cannot occur |
|---|---|---|---|
| Entities before it trips (~469 B/state) | ~35,000 | ~35,000 | none |
| A one-off oversized event (huge attribute) | reconnect, recover | connection dead until restart | fine |
| A deterministic oversized `get_states` | 3 attempts at the Fast pace, then D9's Slow disposition (5 min, ERROR each attempt) | stops cleanly | fine |
| Prior art | python-hass-client, remote_homeassistant (16 MiB) | none | none of the surveyed clients |
| Memory guard against a misbehaving server | yes | yes | none (HA is trusted) |

**Recommendation:** A, following prior art. 16 MiB puts the deterministic case at roughly 35k entities, and the loud ERROR makes it diagnosable.
**Pick C instead if** you consider HA fully trusted and want the failure class gone. **Pick B instead if** you think a deterministic oversize is likelier than a one-off one.
**Reversibility:** easy
**Ratified:** Chose a 16 MiB `max_msg_size` constant with 1009 treated as transient plus an ERROR naming the limit over no limit or a terminal stop, to follow prior art and let a one-off oversized message recover, accepting that an install beyond ~35k entities retries every 5 min with a diagnosable ERROR (see the amendment below).

**Amended by the sketch challenge (Finding 4, via the Finding 1 re-evaluation):** a 1009 on 3 consecutive attempts moves the loop to D9's Slow disposition (5 min, ERROR naming the limit on every attempt), bounding a deterministic oversize to ~12 full serializations an hour instead of ~600. The counter clears when a connection stays CONNECTED for D8's 2-min reset window, or when a different failure breaks the streak.

**Amended at build time (user-ratified):** Chose clearing the 1009 counter after 2 min CONNECTED (or on a non-1009 failure) over clearing it at CONNECTED, so that a deterministic oversized `get_states`, which is always sent after CONNECTED, still reaches the Slow disposition, accepting no new concepts (it reuses D8's stability rule).

### D14: StateProxy sync-retry timing after the config fields go

**Deciding factor:** one backoff vocabulary, given that `state_proxy.py:829-830` reads the `connect_retry_*` fields being deleted.

| | A: share D8's reconnect backoff (1/2/4/5 s, jitter) | B: StateProxy's own constants equal to today's defaults (1.0 s initial, 32.0 s max) |
|---|---|---|
| Backoff definitions in the codebase | one | two |
| Behavior change | StateProxy's retry cap drops from 32 s to 5 s | none |
| When it matters | only when `disable_state_proxy_polling` is set; otherwise the poll tick converges instead (`_handle_synchronization_failure`) | same |
| Cost of a repeatedly failing sync | a full `get_states` up to every ~5 s | backs off to 32 s |

**Recommendation:** A, because B's only advantage is avoiding a behavior change in a non-default configuration.
**Pick B instead if** repeated full `get_states` fetches under disabled polling were a measured load problem.
**Reversibility:** easy
**Ratified:** Chose sharing D8's reconnect backoff over StateProxy-specific constants, to keep one backoff definition, accepting faster (≤5 s) full-sync retries when polling is disabled.

## Assumed

- A refused connection on the direct path is fatal today; 502, DNS and timeouts loop through ServiceWatcher. Evidence: `websocket_service.py:434-441` (refused → `CouldNotFindHomeAssistantError`); research brief, "Needs investigation" item 4.
- The WS ServiceWatcher restart budget resets on every restart, so cooldown and exhaustion never fire for WS. Evidence: `websocket_service.py:168-177` (`mark_ready` in `on_initialize`); `core/service_watcher.py:644-670`; `tests/integration/test_service_watcher.py:429`.
- When the recv task dies, pending response futures are not failed, so the next `subscribe_events` / `get_states` waits the full `response_timeout_seconds` (fixed in scope, see Summary). Evidence: `_handle_recv_task_done` (`websocket_service.py:476-499`) only flips state; `fail_all` runs only in `partial_cleanup`/`cleanup`; probes `p1`/`p1b` in the research.
- The Supervisor proxy returns HTTP 502 while Core is not RUNNING, sends `auth_ok` before connecting upstream, and closes with 1001 then refuses while the Supervisor restarts. Evidence: `supervisor/api/proxy.py:326-327, 371, 390-393`; `supervisor/core.py:390`; research item 2.
- `auth_invalid` is rarely transient during an HA restart: the auth store loads before the HTTP listener serves. The exception is clock skew (below), which D3 covers. Evidence: `homeassistant/core_config.py:377`, `components/http/__init__.py:206`.
- HA always reaches RUNNING: STARTING waits at most `TIMEOUT_EVENT_START` (15 s) for start tasks before `set_state(CoreState.running)`. Evidence: `~/source/core/homeassistant/core.py:158, 513-560`.
- `homeassistant_started` arrives over the existing blanket `subscribe_events` subscription. Evidence: `start_recv_and_subscribe` (`websocket_service.py:446-474`).
- `get_config` returns HA's `state` field (NOT_RUNNING / STARTING / RUNNING / ...). Evidence: `homeassistant/core_config.py:685-721`; `Api.get_config` (`src/hassette/api/api.py:454-461`).
- Removing config fields hard-fails startup for users who set them (`check_unknown_keys` raises `ConfigError`). The websocket fields being removed are `connect_retry_max_attempts`, `connect_retry_initial_wait_seconds`, `connect_retry_max_wait_seconds`, `early_drop_stable_window_seconds`, `early_drop_max_retries`, `early_drop_backoff_initial_seconds`, `early_drop_backoff_max_seconds` and `max_recovery_seconds`. Evidence: `src/hassette/config/checks.py:79`, `config.py:444`; research item 6.
- Apps that relied on the process restart after an HA reboot to re-run `on_initialize` (e.g. re-creating `set_state` entities) lose that; #1676 tracks a framework signal for it. Evidence: research brief F9; hautomate `car_status.py:161`, `monarch/*`.
- After a reconnect, the resync replaces the cache with a full `get_states` rather than merging. Evidence: research brief F11, StateProxy `_commit_candidate_states`.
- `/api/health/live` is HA-independent, and the add-on Watchdog (129 D14) points at it. Evidence: `design/specs/070-health-liveness-readiness/design.md`, `design/specs/129-ha-addon-v01/design.md`.
- Health top-level status is already derived as `ok` / `degraded` / `starting` from `is_connected`, bootstrap release and `has_ever_connected`. Evidence: `src/hassette/core/runtime_query_service.py:341-351`.
- Service shutdown cancels the serve task, and `_serve_wrapper` treats `CancelledError` as cooperative shutdown, so cancellation reaching the loop is a shutdown, never a failure to classify (D9 Propagate). Evidence: `src/hassette/resources/service.py:85-87, 137-138, 182-186`; research F18.
- `/api/health`'s "An HA outage does not trigger a restart" (`docs/pages/web-ui/health-endpoints.md:79`) becomes true with this change.
- With Docker Compose and `base_url` naming the HA container (e.g. `http://homeassistant:8123`), Docker's embedded DNS returns NXDOMAIN while that container is stopped, so a DNS failure is a normal HA-restart signal, not a config error. Evidence: Docker embedded DNS only resolves running containers on the network (https://docs.docker.com/engine/network/#dns-services).
- HA verifies access-token time claims, and PyJWT rejects a token whose `iat` is ahead of the host clock, so an HA host booting with its clock behind (no RTC, before NTP sync) rejects a valid token. Evidence: `~/source/core/homeassistant/auth/__init__.py:673-677`; PyJWT `_validate_iat` (read from a locally installed copy, not HA's pinned version).
- fail2ban's default jail bans after 5 failures within 10 min (`maxretry = 5`, `findtime = 10m` in `jail.conf`), the typical setup in front of an nginx/Caddy reverse proxy with auth. Evidence: https://github.com/fail2ban/fail2ban/blob/master/config/jail.conf.

## Build

- [x] Implementation and tests committed
- [x] Docs
- [x] Ship-time challenge

**Calls made during the build:**

- The reconnect policy (classification, pacing, outage logging) lives in a new `src/hassette/core/websocket_reconnect.py`, replacing `early_drop_policy.py`: `websocket_service.py` was already over the 800-line limit, and the file-size gate forbids it growing.
- `WebsocketService.report_connection_status` sets the ready reason through the new `lifecycle.set_ready_reason` and emits a status event only when the reason changes; it does nothing once shutdown has started, so shutdown's reason wins. Every non-park failure resets the reason to "Not connected to Home Assistant", including a first-start outage.
- D3's auth-rejection count resets only when a connection reaches CONNECTED; other failures between rejections don't reset it.
- A 429's `Retry-After` is honored only in its delta-seconds form, floored at the 5 s Fast cap (a `Retry-After: 0` must not hot-loop); the HTTP-date form falls back to the 5 min Slow pace.
- Any failure other than a 1009, auth rejections included, breaks the 1009 streak.
- Slow and auth-retry failures don't advance the D8 Fast curve.
- D11 episodes: an episode lasts until a connection survives the 2-min D8 window, so a flapping link gets one first-failure WARNING plus flap counts in the 5-min summaries. A flap is a connection that dropped inside an open episode (`OutageLog.is_flap`); its recovery line is DEBUG.
- `set_connection_state` no longer logs "Disconnected from Home Assistant" at INFO: OutageLog's first-failure WARNING reports a real drop, and a flap's drop belongs in the summary.
- `mark_connected` re-checks the recv task after its status-event await and raises instead of announcing a connection that died meanwhile; observers get the generation captured before the await. Cleanup detaches the recv task before cancelling it, so the done-callback treats any other end of an attached task, cancellation included, as a lost connection (ship-time challenge, Findings 12 and 13).
- `InvalidAuthError` subclasses `HassetteError`, not `FatalError`: nothing treats it as fatal any more, by D7's no-dead-public-semantics reasoning (ship-time challenge, Finding 15).
- The "Reconnected to Home Assistant" INFO moved from `set_connection_state` to `OutageLog.record_connected` so it can carry the outage duration; the first-connect "Connected to Home Assistant" line stays where the quickstart expects it.
- `authenticate()` no longer logs CRITICAL on `auth_invalid`; `OutageLog` logs at the level D3's retry-or-park decision calls for, so a retried rejection isn't reported as CRITICAL.
- "Unexpected" exceptions (D11 traceback dedupe) are anything outside `aiohttp.ClientError`, `OSError`, `TimeoutError` and `HassetteError`.
- `STOPPED` counts as a shutting-down core state for D12, alongside STOPPING and FINAL_WRITE.
- The Fast curve's exponent is capped, so a days-long outage can't overflow the float conversion.
- The system acceptance test shrinks D8's reset window to 5 s with `monkeypatch` instead of holding a connection for 2 min.
- The ledger's `docs/pages/configuration/index.md` doesn't exist; the `[hassette.websocket]` table it meant is in `docs/pages/core-concepts/configuration/index.md`.
- `hassette.testing._ws_mocks`: `run_start_recv_and_subscribe` became `run_connect_sequence` (start_recv_and_subscribe, then mark_connected), and `make_clean_connection_task`/`make_dropped_connection_task` were deleted, since they only stubbed the removed `make_connection`.

## Addendum
