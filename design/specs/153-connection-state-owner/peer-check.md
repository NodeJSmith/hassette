# Peer check: connection-state observers

Sources were read directly from each project's default branch on 2026-11-13 (raw GitHub via `curl`/`gh api`), so no web search was needed. Short names used below:

- **grpc-py**: `grpc/grpc` `src/python/grpcio/grpc/_channel.py`, `grpc/__init__.py`, `grpc/aio/_base_channel.py`, `doc/connectivity-semantics-and-api.md`, plus `grpc/proposal` `A17-client-side-health-checking.md`
- **grpc-java**: `grpc/grpc-java` `api/.../ManagedChannel.java`, `core/.../internal/ConnectivityStateManager.java`
- **grpc-go**: `grpc/grpc-go` `clientconn.go`, `balancer/subconn.go`, `balancer/pickfirst/pickfirst.go`, `internal/grpcsync/pubsub.go`, `internal/channelz/trace.go`
- **HA**: `home-assistant/core@dev` `homeassistant/config_entries.py`, `core.py`, `helpers/start.py`, `helpers/dispatcher.py`
- **hajs**: `home-assistant/home-assistant-js-websocket` `lib/connection.ts`, `lib/config.ts`, `lib/collection.ts`
- **NetDaemon**: `net-daemon/netdaemon@main` `src/Client/NetDaemon.HassClient/Internal/HomeAssistantRunner.cs`, `Internal/HomeAssistantClient.cs`, `Common/DisconnectReason.cs`, `src/Runtime/NetDaemon.Runtime/Internal/NetDaemonRuntime.cs`
- **AppDaemon**: `AppDaemon/appdaemon@dev` `appdaemon/plugins/hass/hassplugin.py`, `appdaemon/plugin_management.py`
- **transitions**: `pytransitions/transitions` `transitions/core.py`, `extensions/asyncio.py`, `README.md`
- **psm** (python-statemachine): `fgmacedo/python-statemachine@main` `docs/actions.md`, `docs/async.md`, `docs/listeners.md`, `docs/states.md`, `docs/transitions.md`

## 1. Are observers called synchronously or awaited?

- **grpc-py**: Synchronous. `_spawn_delivery` starts a daemon `ForkManagedThread` that calls `callback(connectivity)` in a loop and logs any exception (`_channel.py` `_deliver`/`_spawn_delivery`). The aio channel has no callbacks. Callers poll `get_state()` or `await wait_for_state_change(last_observed_state)` instead (`aio/_base_channel.py`).
- **grpc-java**: Synchronous. The callback is a `Runnable` that `executor.execute(callback)` runs on "the same executor that runs Call listeners" (`ManagedChannel.notifyWhenStateChanged` javadoc, `ConnectivityStateManager.Listener.runInExecutor`). The work is handed off by running it on an executor.
- **grpc-go**: Synchronous. `PubSub.Publish` queues `sub.OnMessage(msg)` onto a `CallbackSerializer`, and the interface says "Implementations must not block in this method" (`internal/grpcsync/pubsub.go`). The public API is the blocking `WaitForStateChange(ctx, source)` (`clientconn.go`).
- **HA ConfigEntry**: Synchronous. `_async_process_on_state_change` calls each `func()` inline and wraps it in try/except with `logger.exception` (`config_entries.py`). The `SIGNAL_CONFIG_ENTRY_CHANGED` dispatcher runs `@callback` targets inline and gives coroutine targets to `hass.async_run_hass_job`, which schedules them as tasks (`helpers/dispatcher.py` `async_dispatcher_send_internal`, `core.py` `async_run_hass_job`). Async work is handed off by scheduling a task.
- **HA CoreState**: `hass.set_state()` is a plain setter with no observers (`core.py` `set_state`). Each call site then fires a bus event, e.g. `set_state(CoreState.running)` followed by `EVENT_CORE_CONFIG_UPDATE` and `EVENT_HOMEASSISTANT_STARTED` (`core.py` `async_start`). Bus listeners use the same callback-or-task dispatch as above.
- **hajs**: Synchronous. `fireEvent` does `forEach(callback => callback(this, eventData))` with no try/catch (`connection.ts`).
- **NetDaemon**: Synchronous. Rx `Subject.OnNext` (`HomeAssistantRunner.cs`). The runtime hands off with `.Select(async c => await OnHomeAssistantClientConnected(...)).Subscribe()`, a fire-and-forget task per emission (`NetDaemonRuntime.cs`).
- **AppDaemon**: Awaited inline. `await self.notify_plugin_started(...)` / `await self.AD.plugins.notify_plugin_stopped(...)` (`hassplugin.py` `__post_auth__`/`get_updates`), which `await self.AD.events.process_event(...)` (`plugin_management.py`).
- **transitions**: `Machine` is synchronous ("Blocking callbacks will halt the execution order", README). `AsyncMachine` awaits every callback stage (`extensions/asyncio.py` `await event_data.machine.callbacks(...)`), and sync and async callbacks can be mixed (README).
- **psm**: Automatic. "If the state machine has at least one `async` callback, the engine switches to AsyncEngine automatically", and callbacks are then awaited (`docs/async.md`).

**Common pattern:** state-owner libraries (gRPC, HA, hajs, NetDaemon) call plain synchronous callbacks and hand async work off to a task, executor or serializer. Only the generic FSM libraries and AppDaemon await observers.

## 2. What payload does an observer get?

- **grpc-py**: The new state only (`callback(connectivity)`, `__init__.py` `subscribe` docstring).
- **grpc-java**: Nothing. The `Runnable` takes no arguments, and the callback calls `getState()` itself. The javadoc warns that the API "is only reliable in tracking the *current* state".
- **grpc-go**: The channel pubsub publishes the bare `connectivity.State` (`clientconn.go` `updateState`). The LB-facing `SubConnState{ConnectivityState, ConnectionError error}` carries a detail that is "set if the ConnectivityState is TransientFailure … Otherwise, it is nil" (`balancer/subconn.go`). That detail is typed (`error`) and bound to one state by convention, not by the type system.
- **HA ConfigEntry**: `async_on_state_change` callbacks get no arguments (`func()`) and read `entry.state` / `entry.reason`. The dispatcher signal gets `(ConfigEntryChange.UPDATED, entry)`. The detail is `reason: str | None` plus `error_reason_translation_key/placeholders/domain`: one untyped field set on every transition, with no old state passed (`config_entries.py` `_async_set_state`).
- **HA CoreState**: The start/started events take `NoEventData` (`helpers/start.py` type hints). The state is read from `hass.state`.
- **hajs**: `(conn, eventData?: any)`. Only `reconnect-error` passes data (`ERR_INVALID_AUTH`), so the detail is untyped `any` (`connection.ts` `ConnectionEventListener`).
- **NetDaemon**: Two streams with different payloads. `OnConnect` emits the `IHomeAssistantConnection`. `OnDisconnect` emits a closed enum `DisconnectReason {Client, Remote, NotReady, Unauthorized, Error}` (`DisconnectReason.cs`). Neither carries an old/new pair.
- **AppDaemon**: `plugin_started` / `plugin_stopped` events with `{"name": ...}` (`plugin_management.py`).
- **transitions**: With `send_event=True`, an `EventData` with `state`, `event`, `machine`, `model`, `transition` (source/dest), `args`, `kwargs` and `error` (`core.py` `EventData.__init__`). The detail is whatever untyped `*args/**kwargs` were passed to the trigger.
- **psm**: Dependency-injected `source`, `target`, `event`, `event_data`, `state`, `model`, `transition`, and `error` only in error callbacks (`docs/actions.md` "Available parameters"). Extra trigger args are passed through untyped.

**Common pattern:** the state owners pass the new state at most, with no old/new pair, and any detail is a single untyped or loosely typed field (str, any, error). Only the FSM libraries pass source and target. Only NetDaemon's reason enum and grpc-go's TF-only `ConnectionError` tie a detail to a state.

## 3. Detail changes while the state stays the same, and periodic "still waiting" output

- **grpc-py**: Same-state updates are ignored. `_deliveries` only calls callbacks whose last-delivered connectivity `is not state.connectivity` (`_channel.py`). The separate polling thread wakes every 0.2 s (`watch_connectivity_state(connectivity, time.time() + 0.2)`), but it only delivers on change.
- **grpc-java**: Ignored. `gotoState` returns unless `state != newState` (`ConnectivityStateManager.java`). The semantics doc notes that recoverable failures still produce CONNECTING→TF→CONNECTING churn "that appear[s] spurious" (`connectivity-semantics-and-api.md`).
- **grpc-go**: The channel ignores it (`updateState`: `if csm.state == state { return }`), and so does the SubConn (`updateConnectivityState`: `if ac.state == s { return }`). The detail travels a separate channel: pick_first re-sends `UpdateState(TransientFailure, picker{err})` with the new error, with the comment "In case of TransientFailures allow the picker to be updated to update the connectivity error, in all other cases don't send duplicate state updates" (`pickfirst.go` `updateBalancerState`). It does this once per full pass over addresses (`numTF % len == 0`), so the retry loop drives it.
- **HA ConfigEntry**: Every call notifies. `_async_set_state` has no old==new check. Each retry goes SETUP_RETRY → SETUP_IN_PROGRESS (reason cleared to `None`) → SETUP_RETRY (new reason), so observers fire twice per retry and the retry loop drives it. Retry timing is the `2**tries * 5` backoff capped at 600 s, logged once per attempt as "not ready yet; Retrying in N seconds" (`config_entries.py` ConfigEntryNotReady branch). No separate timer-driven summary was found.
- **HA CoreState**: `EVENT_CORE_CONFIG_UPDATE` is a shared "something about core changed" channel. It fires on every `set_state(starting|running)` and on config changes (`core.py` `async_start`), so listeners re-fetch everything instead of reading a diff.
- **hajs**: The connection fires no event per failed retry. It only fires `disconnected` once, and `reconnect-error` on auth failure (`connection.ts` `_handleClose`). Core readiness travels a separate channel: the `subscribeConfig` collection re-fetches `get_config` on every `core_config_updated` event and exposes `state: "NOT_RUNNING"|"STARTING"|"RUNNING"|…` (`config.ts`, `types.ts`). No periodic summary was found.
- **NetDaemon**: The retry loop drives it. Each attempt that finds HA not RUNNING disposes the connection and emits `OnDisconnect(NotReady)` again, logging "Home Assistant is not ready yet!" and then "Client connection failed, retrying in {Seconds} seconds..." (`HomeAssistantRunner.cs`). Same-reason emissions are not deduplicated.
- **AppDaemon**: It logs "Waiting for Home Assistant to start" once and then `await self.ready_event.wait()`. A `looped_coro(get_hass_config, config_sleep_time)` poll sets `ready_event` once `state == "RUNNING"`, as does the `homeassistant_started` event (`hassplugin.py`). The poll produces no periodic "still waiting" log. Not found.
- **transitions**: Staying in a state requires an explicit reflexive (`dest='='`, which runs exit/enter) or internal (`dest=None`, which runs only before/after) transition (README "Reflexive transitions" and "Internal transitions", `core.py` `if self.dest is not None`).
- **psm**: Same as transitions. `s.to.itself()` runs exit/enter, while `internal=True` runs only the `on` callback (`docs/transitions.md` "Self-transitions and internal transitions").

**Common pattern:** owners that deduplicate (all of gRPC) send detail changes over a separate channel, and owners that don't (HA ConfigEntry, NetDaemon) re-notify from the retry loop. No peer runs a timer-driven "still down" summary. Repeated output comes from the retry loop's own per-attempt log.

## 4. First notification: old=None, or the current state on subscribe?

- **grpc-py**: The current state is sent on subscribe ("invoked immediately upon subscription", `__init__.py`; `_subscribe` spawns a delivery with the current connectivity).
- **grpc-java**: The caller passes the assumed `source`. "If the states are already different, the callback will be called immediately" (`notifyWhenStateChanged` javadoc).
- **grpc-go**: Internal `PubSub.Subscribe` replays the last published message asynchronously to a new subscriber (`pubsub.go`). `WaitForStateChange` returns at once if the state already differs from `source`.
- **HA ConfigEntry**: There is no initial call. `async_on_state_change` only appends the callback (`config_entries.py`). For core state, `async_at_start` / `async_at_started` run the job immediately if HA is already in the wanted state and otherwise `async_listen_once` the event (`helpers/start.py` `_async_at_core_state`).
- **hajs**: Connection events are not replayed. Collections replay: `if (store.state !== undefined) setTimeout(() => subscriber(store.state), 0)` ("so that caller has time to initialize", `collection.ts`).
- **NetDaemon**: Not replayed. It uses a plain `Subject`, not a `BehaviorSubject`, and exposes a pollable `CurrentConnection` property instead (`HomeAssistantRunner.cs`, `IHomeAssistantRunner.cs`). The runtime subscribes before calling `RunAsync` (`NetDaemonRuntime.cs`).
- **AppDaemon**: There are no observers. `ready_event.wait()` returns immediately if the event is already set (`plugin_management.py` `is_ready`).
- **transitions**: "`on_enter_«state name»` callback will _not_ fire when a Machine is first initialized" (README).
- **psm**: Initial-state enter actions run when the machine starts (`docs/states.md`), and async machines need `await sm.activate_initial_state()` (`docs/async.md`). The listener example records only `['s1 -> s2']` after one transition, so `after_transition` does not fire for the initial activation (`docs/listeners.md`).

**Common pattern:** no peer sends `old=None`. They either replay the current state to the new subscriber (grpc-py, grpc-go pubsub, hajs collections, HA `async_at_*`) or send nothing until the first real change and let the caller read the current state.

## 5. Transitions out of a "connected, but the remote isn't ready" state

- **gRPC**: There is no distinct state for this. Under A17 client-side health checking, the subchannel "will stay in state CONNECTING until it receives the first health-check response". If the backend reports unhealthy, it goes to TRANSIENT_FAILURE while the connection stays open, and recovery is TF → READY directly, "with no stop at CONNECTING in between", which A17 describes as "a new transition that was not previously supported" (`A17-client-side-health-checking.md`). In the base transition table, READY → CONNECTING is not allowed: READY may go only to TF, IDLE or SHUTDOWN, and TF may go only to CONNECTING or SHUTDOWN (`connectivity-semantics-and-api.md`). A17 also notes that LB policies "will not be able to tell whether the subchannel has become disconnected or whether the backend has reported that it is unhealthy."
- **HA ConfigEntry** (SETUP_RETRY): Each retry goes to SETUP_IN_PROGRESS, which then ends in LOADED, SETUP_RETRY again, or SETUP_ERROR. Auth failure (`ConfigEntryAuthFailed`) is reached only through a retry: SETUP_IN_PROGRESS → SETUP_ERROR, which also starts reauth (`config_entries.py`). While core isn't running, the retry waits on `EVENT_HOMEASSISTANT_STARTED` instead of the backoff timer (`if hass.state is CoreState.running: async_call_later … else: hass.bus.async_listen(EVENT_HOMEASSISTANT_STARTED, …)`).
- **NetDaemon**: Not-ready is handled as a disconnect. `CheckIfRunning` runs after auth, calls `get_config` and checks `config.State == "RUNNING"`. If HA isn't running, the client disposes the connection and throws `NotReady` (`HomeAssistantClient.cs`). The runner emits `OnDisconnect(NotReady)`, resets the progressive backoff "We have an connection but waiting for Home Assistant to be ready" and reconnects (`HomeAssistantRunner.cs`). So the path is always through disconnected. `Unauthorized` comes only from the auth handshake, which happens before the running check, and it stops the loop.
- **AppDaemon**: Stays connected while waiting (`await self.ready_event.wait()` inside `__post_auth__`). If the socket drops, the `get_updates` loop catches it, runs `ready_event.clear()`, sleeps `retry_secs` and reconnects (`hassplugin.py`). `auth_invalid` is only handled during the handshake: the plugin logs and closes the websocket (`process_websocket_json`). It appears to then fall into the same reconnect loop. That is inferred from `get_updates`; no explicit stop on auth failure was found.
- **hajs**: Has no such state. `ready` fires once the socket is set, and core readiness lives in the config collection (Q3). Auth failure during reconnect fires `reconnect-error` and stops retrying (`connection.ts`).
- **transitions / psm**: Not applicable (generic libraries).

**Common pattern:** peers split. NetDaemon drops the socket and goes back through disconnected. AppDaemon and gRPC A17 keep the connection open and recover directly to ready. In every peer, auth failure comes only from a fresh handshake, never directly from the waiting state.

## 6. Timestamps passed to observers

- **grpc-py / grpc-java / grpc-go**: No timestamp in callbacks (signatures above). grpc-go's channelz trace events record `Timestamp: time.Now()`, which is wall-clock (`internal/channelz/trace.go`), but that is a diagnostics surface, not the observer payload.
- **HA ConfigEntry**: Not passed (no-arg callbacks).
- **HA bus events** (`homeassistant_started`, `core_config_updated`): `time_fired_timestamp = time.time()`, which is wall-clock (`core.py` `Event.__init__`).
- **hajs**: Not passed.
- **NetDaemon**: Not passed. Backoff is a `TimeSpan` duration, not a timestamp (`HomeAssistantRunner.cs`).
- **AppDaemon**: Not passed to observers. Internally it uses `perf_counter()`, which is monotonic, for "fully started after X" durations (`hassplugin.py` `self.start = perf_counter()`), and `AD.sched.get_now()`, which is wall-clock, for `last_plugin_state` (`plugin_management.py` `refresh_update_time`).
- **transitions / psm**: Not passed (EventData and the injected params have no time field).

**Common pattern:** no peer passes a timestamp to state observers. Where one is recorded, it is wall-clock for events and logs, and AppDaemon is the one peer that uses a monotonic clock, for measuring durations.
