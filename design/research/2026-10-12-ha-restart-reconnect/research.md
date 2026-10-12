# Research Brief: Stay up and reconnect when Home Assistant restarts (#2701)

| | |
|---|---|
| **Proposal** | Take HA-unreachable off the fatal path, and replace the stacked retry layers with one unbounded, in-loop reconnect inside `WebsocketService.serve()` (capped exponential backoff plus jitter). Apps keep running on a STALE cache, and StateProxy resyncs on reconnect. |
| **Date** | 2026-10-12 |
| **Status** | Draft |
| **Flexibility** | Leaning (prefers the issue's direction; wants prior art to confirm or correct it) |
| **Motivation** | Hassette exits fatally ~20 s after HA starts a restart. The user wants to follow convention and learn which footguns others have hit. |
| **Scope** | Post-bootstrap HA restarts **and** HA unreachable at first startup |
| **Constraints** | Pre-v1, no compat shims. HA-facing design follows HA/HACS convention. One live `Hassette` per process. |
| **Depth** | deep |

## Summary

**Prior art backs the proposal's core.** No long-lived HA client I surveyed exits because HA is unreachable: AppDaemon, home-assistant-js-websocket, node-red-contrib-home-assistant-websocket, Music Assistant, remote_homeassistant, and HA's own MQTT, ESPHome and config-entry retry. All of them retry forever. Kubernetes and the HA Supervisor follow the same rule: a dependency outage is not a reason to die. Under Supervisor, the add-on Watchdog is **off by default** (`supervisor/apps/validate.py:624`), so an exiting add-on stays dead.

Prior art would change five things in the proposal:

1. **The 30 s backoff cap is slower than the ecosystem and slower than the issue's own "reconnects within a few seconds".** HA's clients cap at 5 s (js-websocket, node-red, AppDaemon) or 10 s (MQTT, remote_homeassistant). With a single client on a LAN, thundering-herd jitter matters little.
2. **Socket-open and `auth_ok` do not mean HA is ready.** HA's HTTP listener starts as soon as `frontend` is set up, before the recorder, stage 1/2 integrations, `STARTING` or `RUNNING` (`homeassistant/components/http/__init__.py:206`). A direct-URL client can therefore authenticate and fetch a partial `get_states`. AppDaemon (#2226) and node-red both added a `get_config.state == "RUNNING"` gate after users hit exactly this.
3. **`auth_invalid` is not transient.** The auth store loads before the listener exists (`homeassistant/core_config.py:377`), and validation is synchronous and in-memory. Every rejected attempt also costs HA something: a WARNING log, a "Login attempt failed" persistent notification, and an IP-ban count if the user has configured a threshold (`homeassistant/components/http/ban.py:111-170`). Convention (js-ws, node-red, HA MQTT, HA config entries) is to stop retrying, stay up, and escalate. AppDaemon retries forever, and nothing else does.
4. **The add-on path doesn't fail the way the issue says.** Through `ws://supervisor/core/api/websocket`, Supervisor answers **HTTP 502** for as long as Core is not RUNNING (`supervisor/api/proxy.py:326-327`). Hassette sees that as `WSServerHandshakeError`, not connection-refused, so today the add-on does not take the fatal path. Instead it restarts `WebsocketService` through ServiceWatcher indefinitely. The fix is still needed, but the acceptance tests should cover 502 explicitly.
5. **HA lifecycle events are not a reliable restart signal.** Via the proxy, `homeassistant_start` and `homeassistant_started` have always fired before an add-on can connect. On the direct path, whether they are seen depends on backoff timing. Apps that today rely on the process restart to re-create `set_state` entities lose that once Hassette stays up (hautomate's `monarch/*` apps; see #1676).

**Recommendation:** Option A, adjusted for the five points above: a lower cap, auth-reject as a terminal stay-up state, 502 and accept-then-drop treated as transient, and core-state awareness for the resync. The early-drop concept, the tenacity connect layer and `max_recovery_seconds` should be deleted rather than renamed.

## Context

### What prompted this
Issue #2701 (observed in production on jessica-desktop). After a long-lived connection drops, `ServiceWatcher` restarts `WebsocketService`. The tenacity connect layer then gets 5 connection refusals, raises `CouldNotFindHomeAssistantError`, which is a `FatalError` (`src/hassette/exceptions.py:159`), and `_serve_wrapper` routes it to `handle_crash` (`src/hassette/resources/service.py:196-199`), so the process exits. The issue is in the *HA Add-on v0.1* milestone, whose Done-when requires the add-on to "survive a reboot".

### Key constraints
- Pre-v1 with no shims: config fields, `early_drop_policy.py` and the public `hassette.testing` `TEST_EARLY_DROP_*` constants can be deleted. A removed public export needs a `BREAKING CHANGE:` footer.
- Hassette is a framework, so in-repo usage measures blast radius, not demand.
- Designs 018, 043 and 070 already state the target behavior: stay up and retry. `docs/pages/web-ui/health-endpoints.md:79` already tells users "An HA outage does not trigger a restart", which is false today.

## Prior Art

### AppDaemon 4.5.14: retry forever, stop and re-init apps
Source read: [`hassplugin.py`](https://github.com/AppDaemon/appdaemon/blob/b8b06ba/appdaemon/plugins/hass/hassplugin.py#L555-L595), [`plugin_management.py`](https://github.com/AppDaemon/appdaemon/blob/b8b06ba/appdaemon/plugin_management.py#L440-L449).
- **Reconnect:** `while not AD.stopping`, with a **fixed** `retry_secs=5` (connect timeout 1 s). No jitter and no give-up. First connect and reconnect share the loop.
- **Auth:** `auth_invalid` closes the socket, and the loop **retries every 5 s forever**. AppDaemon is the outlier here.
- **Readiness:** after `auth_ok`, AppDaemon subscribes, then waits for `homeassistant_started` **or** `get_config` reporting `state == "RUNNING"`, then `get_states`, then starts apps. The `get_config` half exists because a brief WS blip never produces a new `homeassistant_started`.
- **Apps:** on disconnect, every app in the namespace is **terminated**. On reconnect they are re-initialized (`PLUGIN_RESTART`). API calls while disconnected warn and return `None` (`@hass_check`).
- **Footguns:**
  - [#2226](https://github.com/AppDaemon/appdaemon/issues/2226) (4.5.0): apps initialized before HA finished loading, so entities were missing. The RUNNING gate above was the fix. Side effect: apps can no longer `listen_event("homeassistant_started")`, because it has already fired.
  - [#1256](https://github.com/AppDaemon/appdaemon/issues/1256): services were missing after an HA restart.
  - [#2540](https://github.com/AppDaemon/appdaemon/issues/2540): **502 from the Supervisor proxy** during restart (handled by plain retry).
  - [#1614](https://github.com/AppDaemon/appdaemon/issues/1614): "Client exceeded max pending messages" at HA restart with a blanket `subscribe_events`.
  - [#2676](https://github.com/AppDaemon/appdaemon/issues/2676) (open): `get_states` exceeds aiohttp's 4 MiB `max_msg_size`, so the client **loops reconnecting forever**. A permanent error is indistinguishable from a transient one.
  - [#2011](https://github.com/AppDaemon/appdaemon/issues/2011): apps stuck `terminated` after a restart, which shows that stop-all/restart-all is fragile.

### home-assistant-js-websocket (HA frontend's client)
Source read: [`connection.ts`](https://github.com/home-assistant/home-assistant-js-websocket/blob/4c5674c/lib/connection.ts#L441-L505), [`socket.ts`](https://github.com/home-assistant/home-assistant-js-websocket/blob/4c5674c/lib/socket.ts#L93-L107), frontend [`connection-mixin.ts`](https://github.com/home-assistant/frontend/blob/dev/src/state/connection-mixin.ts#L262-L410).
- **Reconnect:** `Math.min(tries, 5) * 1000`, i.e. 0, 1, 2, 3, 4, then 5 s capped. No jitter and no give-up. Initial-connect retry is opt-in (`setupRetry`). `connectTimeout=10s` was added in 2026-09 ([#760](https://github.com/home-assistant/home-assistant-js-websocket/issues/760)), because a socket stuck in CONNECTING never fired `close`.
- **Auth:** `ERR_INVALID_AUTH` makes it **stop retrying** and emit `reconnect-error`. The frontend reloads the page.
- **Resubscription:** automatic, from a subscription map. Message IDs reset per socket, and in-flight commands reject with `ERR_CONNECTION_LOST`.
- **Readiness:** the library's `ready` means only "authed and resubscribed". The frontend re-fetches `get_config` on `ready` because "we might miss an update while disconnected". The frontend also runs its own ping (30 s interval, 15 s timeout, then `reconnect(true)`); the library has no dead-socket detection ([#256](https://github.com/home-assistant/home-assistant-js-websocket/issues/256)).
- **Footguns:**
  - [#130](https://github.com/home-assistant/home-assistant-js-websocket/issues/130) and [#272](https://github.com/home-assistant/home-assistant-js-websocket/issues/272): the WS accepts connections **before integrations load**, so early resubscribes or refetches fail.
  - [#555](https://github.com/home-assistant/home-assistant-js-websocket/issues/555) (open): `subscribe_trigger` made before RUNNING silently never delivers.
  - [#769](https://github.com/home-assistant/home-assistant-js-websocket/issues/769): a snapshot **merged** on reconnect left deleted entities behind forever. Resync must replace, not merge.

### node-red-contrib-home-assistant-websocket
Source read: [`createSocket.ts`](https://github.com/zachowj/node-red-contrib-home-assistant-websocket/blob/main/src/homeAssistant/createSocket.ts#L24-L175), [`Websocket.ts:529`](https://github.com/zachowj/node-red-contrib-home-assistant-websocket/blob/main/src/homeAssistant/Websocket.ts#L529).
- **Reconnect:** fixed 5 s, forever, plus an initial 5 s delay "so it doesn't spam the hass.io proxy". Handshake timeout 15 s and auth timeout 45 s were added in 2026-07.
- **Auth:** reject puts the client in an Error state, and it **does not retry**.
- **Readiness:** an explicit `isHomeAssistantRunning` flag set from `subscribeConfig` reporting `state === 'RUNNING'`. `Ready` requires that flag **and** services loaded. Event nodes drop `state_changed` until running.
- **Footguns:**
  - [#76](https://github.com/zachowj/node-red-contrib-home-assistant-websocket/issues/76): the **Supervisor proxy accepted then dropped** the socket while HA was offline. The client counted that as a success, which gave a 0-delay hot loop and a CPU spike. This is the evidence for resetting backoff only after the connection has stayed up for N seconds.
  - [#1908](https://github.com/zachowj/node-red-contrib-home-assistant-websocket/issues/1908): the maintainer says it "reconnects fairly early … before all integrations are fully loaded", so cached state stays wrong until the entity next changes.
  - [#2027](https://github.com/zachowj/node-red-contrib-home-assistant-websocket/issues/2027): a wedged HA still accepted TCP, and the client sat "connecting" for 15 h until handshake and auth timeouts were added.
  - [#2015](https://github.com/zachowj/node-red-contrib-home-assistant-websocket/issues/2015): integration entities stayed unavailable after reconnect (a re-registration gap).

### Python clients: hass-client / Music Assistant, remote_homeassistant
- **[python-hass-client](https://github.com/music-assistant/python-hass-client/blob/3e68c91/hass_client/client.py#L330):** has no reconnect loop; reconnecting is the consumer's job. Footgun [#275](https://github.com/music-assistant/python-hass-client/issues/275): an ERROR frame had no `.code`, so the reader raised `AttributeError` and bypassed the consumer's reconnect. **The reader loop must catch everything.**
- **[Music Assistant](https://github.com/music-assistant/server/blob/1611ea1/music_assistant/mass.py#L134-L135):** full provider reload with stepped delays of 10/30/60/120 s ±3 s, **unbounded**. It is the only surveyed HA client with jitter.
- **[remote_homeassistant](https://github.com/custom-components/remote_homeassistant/blob/bd554c4/custom_components/remote_homeassistant/__init__.py#L403-L552):** fixed 10 s forever. On `auth_invalid` it stays loaded and stops retrying. App-level ping is every 20 s with a 5 s timeout. It subscribes **before** `get_states`, which closes the gap. It removes mirrored entities while disconnected.
  - Footguns: [#394](https://github.com/custom-components/remote_homeassistant/issues/394) (reconnect stuck indefinitely with no attempt timeout), [#211](https://github.com/custom-components/remote_homeassistant/issues/211)/[#215](https://github.com/custom-components/remote_homeassistant/issues/215) (shows "connected" but no data: a zombie subscription), [#170](https://github.com/custom-components/remote_homeassistant/issues/170) (reconnect logic blocked host startup).
- **pyscript** runs in-process with no WS client, so it is not relevant here.

### HA core itself (server side; read at `home-assistant/core@abe1fdd7`, 2026-10-10)
- **Startup order:**
  1. The auth store loads in core config (`core_config.py:377`).
  2. The HTTP server binds, but serves only once `frontend` is set up (`components/http/__init__.py:206`). That is stage 0, **before the recorder (DB migration) and stage 1/2**.
  3. `CoreState` stays `NOT_RUNNING` through bootstrap. `async_start` then goes to `STARTING`, fires `homeassistant_start`, then `RUNNING`, and fires `homeassistant_started` (`core.py:523-562`).
  4. At `homeassistant_start`, every registered entity not yet loaded gets an **`unavailable` state with `restored: true`** (`helpers/entity_registry.py:2827-2837`).
  5. A reconnecting client therefore sees a storm of `unavailable → real` `state_changed` events as integrations finish.
- **Shutdown:** `homeassistant_stop` stops the listener and cancels every WS handler. The client gets a plain close with no "stopping" message, then ECONNREFUSED.
- **Auth:** `async_validate_access_token` is a synchronous JWT check against the in-memory store (`auth/__init__.py:654`). Rejection calls `process_wrong_login`, which always logs and creates a persistent notification. It bans only if `login_attempts_threshold ≥ 1`; the default is `-1` (`http/const.py:51`).
- **Readiness signals:** `get_config` returns `state` (NOT_RUNNING / STARTING / RUNNING / STOPPING / FINAL_WRITE / STOPPED) plus `recovery_mode` and `safe_mode`. There is no subscribe-to-core-state command. The conventional pattern is: subscribe, then `get_config`, and if not RUNNING, wait for `homeassistant_started`.
- **HA's own long-lived-client conventions:**
  - Config entries: `ConfigEntryNotReady` retries at `min(2**tries * 5, 600)` s forever, while `ConfigEntryAuthFailed` stops and starts a reauth flow (`config_entries.py:805-815`).
  - MQTT: reconnects every fixed 10 s forever. On bad-auth CONNACK it stops and starts reauth (`components/mqtt/client.py:1221-1233`).
  - [aioesphomeapi](https://github.com/esphome/aioesphomeapi/blob/main/aioesphomeapi/reconnect_logic.py): backoff `min(1.8**tries, 60)` with no jitter. Auth errors pin backoff at 60 s, and the HA integration then stops it and starts reauth.
  - **The rule across all three: connection errors retry forever with a capped backoff, and credential errors stop and ask a human.**

### HA Supervisor / add-on conventions (read at `home-assistant/supervisor@f2a8d3df`)
- **WS proxy** (`/core/api/websocket` and `/core/websocket`, `api/__init__.py:706-707`):
  - **HTTP 502** when Core is not `RUNNING` (or is mid offline DB migration) (`api/proxy.py:326-327`, `homeassistant/api.py:476-480`). So an add-on never sees a STARTING Core, and it never sees `homeassistant_start` or `homeassistant_started` after a Core restart.
  - The proxy sends **`auth_ok` before it connects upstream** (`proxy.py:371` vs `:390-393`). If Core vanishes in between, the add-on gets `auth_ok` and then an immediate close.
  - `auth_invalid` comes only for an unknown `SUPERVISOR_TOKEN` or a missing `homeassistant_api` permission.
- **Watchdog:** default **off** (`apps/validate.py:624`). It triggers on container exit or unhealthy, or on two failed `watchdog:` URL polls 120 s apart.
- **Restarts and startup ordering:** a Core restart neither restarts nor notifies add-ons. `startup: application` add-ons start after Core is RUNNING on a full host boot, but see the whole outage on a Core-only restart or update.
- **How long an outage can last:** Supervisor itself waits 10 min for Core's API, then 15 min for RUNNING, and extends during DB migration (`homeassistant/core.py:62-70, 648-697`). Outages of tens of minutes are a design-accepted case, so any fixed give-up timer is wrong.
- The developer docs ([communication](https://developers.home-assistant.io/docs/add-ons/communication/), [configuration](https://developers.home-assistant.io/docs/add-ons/configuration/)) say nothing about how an add-on should behave while Core is down.

### General conventions
- **Backoff:** capped exponential with jitter is the standard for remote clients ([AWS: Exponential Backoff and Jitter](https://aws.amazon.com/blogs/architecture/exponential-backoff-and-jitter/)). Reset only after the connection has been stable: the Kubernetes kubelet resets crash backoff after 10 min of healthy running ([pod lifecycle](https://kubernetes.io/docs/concepts/workloads/pods/pod-lifecycle/)). Jitter guards against many clients synchronizing. Hassette is one client per HA, so jitter is cheap insurance, not load-bearing.
- **Exit vs stay up:** Kubernetes warns that liveness probes "must be configured carefully to ensure that they truly indicate unrecoverable application failure" and that incorrect ones "can lead to cascading failures". Dependency checks belong in readiness ([probes](https://kubernetes.io/docs/concepts/configuration/liveness-readiness-startup-probes/); [srcco.de](https://srcco.de/posts/kubernetes-liveness-probes-are-dangerous.html)). Process exit on a dependency outage is the same mistake one level up. Hassette's 070 split (live = process, ready = HA) already encodes this.
- **Auth failures:** non-retriable by class in Kafka ([`AuthenticationException`](https://kafka.apache.org/42/javadoc/org/apache/kafka/common/errors/AuthenticationException.html)), and treated the same way by HA MQTT and ESPHome (above).

### Cross-project synthesis

| | Backoff | Gives up? | `auth_invalid` | Ready gate | Resync | Apps during outage |
|---|---|---|---|---|---|---|
| AppDaemon | fixed 5 s | never | retry forever (5 s) | `homeassistant_started` or `get_config` RUNNING | full `get_states`, replace | **stopped**, re-init on reconnect |
| js-websocket | 0→5 s cap | never (after first connect) | **stop**, emit error | none in lib; frontend refetches `get_config` | auto-resubscribe; snapshot | keep running |
| node-red | fixed 5 s | never | **stop** | `config.state == RUNNING` + services | full refetch | keep running, events dropped until RUNNING |
| remote_homeassistant | fixed 10 s | never | **stop**, stay loaded | none | subscribe, then `get_states` | mirrored entities removed |
| Music Assistant | 10/30/60/120 s ±3 | never | probably retries (unverified) | none | full provider reload | provider unavailable |
| HA MQTT / ESPHome / config entries | 10 s / ≤60 s / ≤600 s | never | **stop + reauth** | n/a | n/a | n/a |
| **Hassette today** | tenacity 1→32 s ×5, then ServiceWatcher | **exits** on refused | **exits** (FatalError) | none | `get_states` on connect, replace | keep running (STALE) |

## Current Codebase State

### Today's failure paths (Direct, from code; `src/hassette/core/websocket_service.py`)
Three retry layers stack:
1. Tenacity in `make_connection` (`:529-552`): 5 attempts, about 17 s.
2. The early-drop loop in `serve()` (`:399-421`, `early_drop_policy.py`): only for drops within 30 s of connecting.
3. ServiceWatcher restarts (TRANSIENT, `:91-97`).

| Failure | What happens today |
|---|---|
| Long-lived connection drops (the usual HA restart) | Not an early drop, because `elapsed > 30 s`. `handle_genuine_failure` → `handle_failed` → ServiceWatcher restart → tenacity ×5 against refused → `CouldNotFindHomeAssistantError` → `handle_crash` → **process exit**. |
| Direct URL, connection refused | `connect_ws` converts it to `CouldNotFindHomeAssistantError` (`:438-440`), which is fatal after tenacity. |
| `EHOSTUNREACH`, DNS, connect timeout | Plain `ClientConnectorError` or timeout → `handle_failed` → restart, forever (non-fatal). |
| **Add-on proxy, Core down** (HTTP 502) | `WSServerHandshakeError`, never converted → `handle_failed` → **restart loop, not an exit**. Inferred from code plus the Supervisor source; not observed. |
| `auth_invalid` | `InvalidAuthError` (FatalError) → exit (`:404-408`, `:817-823`). |
| Socket closes right after `auth_ok` (proxy race) | `subscribe_events` waits on a response future that the recv-task death doesn't fail. That inference comes from `_handle_recv_task_done` (`:476-499`) only flipping state. Each attempt may wait up to `response_timeout_seconds` (15 s) before retrying. **Needs investigation.** |

**Two claims in the issue look wrong, and neither changes the direction:**
- **"After 5 restarts in 300 s the service enters a 300 s cooldown."** `WebsocketService.on_initialize` marks ready unconditionally (`:168-177`). `ServiceWatcher.await_service_readiness` resets the restart budget as soon as the restarted service is ready (`core/service_watcher.py:644-670`). So the WS budget resets on every restart and cooldown is unreachable for WS. **Supported** (two code sites agree; not observed at runtime). The real secondary cost is therefore an endless sequence of full `WebsocketService` teardowns, each exposed to #1716's refusal-to-fatal escalation, not a 5-minute latency.
- **"The add-on with Watchdog off stays stopped after every HA update."** Through the proxy the error is a 502, not refused, so the exit path doesn't fire (Inferred, see table). It would fire if the add-on hit refused, e.g. while `supervisor` itself restarts. What the client sees then is unverified.

### What already supports the change
- `handle_early_drop` (`:351-373`) is already the in-loop reconnect sequence: set CONNECTING, clear the send gate, notify observers once, send the lost event, `mark_not_ready`, `partial_cleanup`, then back off. The fix mostly generalizes it.
- The pieces a reconnect relies on are in place:
  - Reconnect re-subscribes (`start_recv_and_subscribe`, `:446-474`).
  - Connection generations fence StateProxy commits.
  - The disconnect event and observers fire once per connected episode, gated on `_connected_signal_active`.
  - StateProxy marks STALE once initial capability is latched, and a reconnect resync replaces the cache with a full `get_states`. StateProxy coalesces resync requests through `_pending_reconnect_generation` (no double-resync path found).
- Startup already tolerates HA being down:
  - Lifecycle waves never wait on HA.
  - `AppBootstrapCoordinator` waits for initial state capability with `timeout=None`.
  - `/api/health/live` is HA-independent, and add-on design 129 D14 points the Watchdog at `/live`.
- Cancellation is clean. `CancelledError` is a `BaseException`, so `except Exception` in `serve()` doesn't swallow it, and `asyncio.sleep` is cancellable.

### What works against it
- `serve()` treats in-loop retry as the exception and propagation as the default. The proposal inverts that, so every non-auth failure has to stay in the loop.
- The early-drop counters (`early_drop_attempts`, `recovery_started_at`) are never reset after a stable connection (`:393-415`), even though the field docstring says they are.
- `state_proxy.py:829-830` reads `connect_retry_initial_wait_seconds`/`connect_retry_max_wait_seconds` for its own sync-retry backoff. Deleting the fields breaks this hidden consumer.
- `aiohttp` `ws_connect` uses the default 4 MiB `max_msg_size` (no override in `src/`), and StateProxy fetches `get_states` over WS (`api/api.py:429`). A large install could exceed it. Under an unbounded loop that becomes AppDaemon #2676's infinite reconnect. This is a current-code exposure that I haven't reproduced.
- `WEBSOCKET_CONNECTED` fires only after StateProxy's resync finishes, because observers are awaited serially (`:471-473`).

### Change surface

| Area | Files | Effort | Risk |
|---|---|---|---|
| Reconnect loop | `core/websocket_service.py` (high fan-in, ~900 lines, 25+ test files); delete `core/early_drop_policy.py` (+ `ruff.toml:158` S311 ignore) | Med | Core connection path; cancellation and state-transition correctness |
| Exceptions | `exceptions.py:159` (`CouldNotFindHomeAssistantError` is public in `__all__`), `:248` `InvalidAuthError` | Low | Public API change, so it needs a `BREAKING CHANGE:` footer if removed or rebased |
| Config | `config/models.py:174-195` (8 fields), `hassette.schema.json` (regen hook), `testing/config.py:65-68` (public `TEST_EARLY_DROP_*`), `state_proxy.py:829-830` | Low | Hidden StateProxy consumer |
| StateProxy core-state awareness (if adopted) | `core/state_proxy.py`, `core/app_bootstrap_coordinator.py` | Med | Interacts with generation fencing and #2699 poll |
| Tests | `tests/integration/websocket/test_reconnect.py` (rewrite early-drop suite), `test_connection.py:144-153`, `tests/unit/core/test_websocket_service_coverage.py:149-190`, `test_ws_connection_state.py:334-363`, `test_websocket_readiness_events.py:29`, `tests/unit/test_config*.py`, `tests/support/mock_hassette.py:219-223` (high fan-in), `tests/system/test_reconnection.py`, `test_startup_without_ha.py`; **new** in-process fake WS server | Med-High | No fake WS server exists today (`build_fake_ws()` is an AsyncMock stub) |
| Docs | `docs/pages/operating/index.md:9-61` (rewrite "three-layer retry model"), `troubleshooting.md:219,283`, `core-concepts/internals/service-details.md:278`, `internals/lifecycle.md:31,225` (anchor), `configuration/index.md:82` | Med | Voice pass + doc-persona/accuracy reviews required |
| Untouched by design | `resources/service.py`, `core/service_watcher.py`, `resources/lifecycle.py` | — | The point is to stop routing outages through them |

hautomate has no `[websocket]` config and no `WEBSOCKET_*` event usage, so config removal costs it nothing. **Behavior** does change for it. `monarch/*` and `car_status.py` create entities with `set_state` / `helpers.create` in `on_initialize`. Today the process restart after an HA reboot re-creates them by accident. After the fix they won't be re-created (`car_status.py:161` already compensates via `on_homeassistant_start`, but see footgun F9).

## Options

### Option A: Single in-loop reconnect, with prior-art corrections (recommended)

**How it works.** `serve()` becomes one loop that returns only on shutdown. Every attempt is a single try: connect, authenticate, subscribe, then run the recv loop. The tenacity wrapper in `make_connection` and the early-drop classifier are deleted. The loop sorts outcomes into three classes:
- **Transient**, covering anything the network or HA can recover from: refused, timeout, `EHOSTUNREACH`, DNS, `WSServerHandshakeError` 5xx (proxy 502), close after `auth_ok`, peer close of an established socket, and heartbeat timeout. Each one goes through the existing `handle_early_drop` sequence (renamed), then a capped exponential backoff with full jitter.
- **Auth-rejected**, meaning `auth_invalid`. The loop enters a terminal-but-alive state: a new `ConnectionState` (e.g. `AUTH_FAILED`) or a ready-reason, an ERROR log with the remediation, and health `starting` or `degraded`. It then stops retrying, or retries on a long interval (see Open Questions).
- **Bug**, meaning anything unexpected inside hassette's own code. That still propagates to `handle_failed`/ServiceWatcher, so `RestartType.TRANSIENT` keeps its meaning: "`serve()` itself is broken".

`CouldNotFindHomeAssistantError` stops being a `FatalError`. The simplest version deletes it and keeps the "check `base_url`" text as the log hint on a refused or DNS failure before the first connect. Backoff resets only after a connection has stayed up for N seconds (node-red #76 is the evidence for that rule).

**Core-state awareness (the readiness correction).** After subscribing, the loop calls `get_config`. If the state isn't `RUNNING`, the connection is still CONNECTED, but StateProxy treats the snapshot as provisional and schedules a second full resync when `homeassistant_started` arrives on the existing blanket subscription. Because the event can be missed, a `get_config` re-check on the poll tick covers that case. That gives AppDaemon's and node-red's behavior without delaying the reconnect itself. A further choice is whether initial app **bootstrap** should also wait for RUNNING. AppDaemon #2226 says yes, and it would close the cold-start partial-snapshot hole.

**Config.** The 8 fields collapse into 0-3. The candidates are a cap and a stable-reset window. Prior art mostly hard-codes these values, which argues for module constants.

**Pros:**
- Every surveyed HA client and HA's own conventions behave this way.
- Removes one exception classification, two retry layers, and `max_recovery_seconds` with its misleading log line.
- Takes HA outages out of ServiceWatcher teardown and #1716's blast radius.
- Makes `health-endpoints.md:79` and 070's scenario true.
- The proxy 502 and refused paths behave identically.
- Subtraction-first: `early_drop_policy.py` goes away.

**Cons:**
- Rewrites the most fan-in-heavy connection code and its test suite.
- Needs a new in-process fake WS server.
- Core-state awareness adds a concept, a second resync trigger, to StateProxy.
- A typo'd `base_url` idles instead of exiting. This was already accepted in 018, and #1926 is the UI half.

**Effort:** Medium-Large. The loop itself is Medium. The test infrastructure (fake server, injectable sleep, new system test) and the docs rewrite make up the rest. Core-state awareness can ship as a separable unit after the loop.

**Dependencies:** none new. Tenacity stays in use elsewhere, for `send_and_wait`, `subscribe_events` and REST.

### Option B: Do less, reclassify only

**How it works.** `CouldNotFindHomeAssistantError` subclasses `HassetteError` instead of `FatalError`, or `connect_ws` stops converting. Also fix the budget log line and the troubleshooting docs. Every outage then takes the path that `EHOSTUNREACH` and proxy-502 already take: tenacity ×5, `handle_failed`, ServiceWatcher restart, repeated forever, because the WS budget resets on every restart (see above).

**Pros:**
- A few lines plus docs, and no test rewrite beyond `test_connection.py:144-153` and docstrings.
- Ends the process exit, which is the bug in the title.
- Reuses a path production already exercises for other error classes.

**Cons:**
- Every outage still runs full `WebsocketService` teardown/restart cycles about every 19 s. Each one is exposed to #1716 (a teardown that overruns its budget → `RestartRefusedError` → fatal), so the process can still die, just by a rarer route.
- Recovery latency after HA returns is up to ~32 s of tenacity wait plus 2 s of restart backoff.
- Keeps three retry layers and the early-drop concept that the user wants subtracted.
- Fails the issue's acceptance criterion "without passing through ServiceWatcher restart/cooldown".
- Leaves the readiness, auth and proxy footguns untouched.

**Effort:** Small. **Dependencies:** none.

Option B is a reasonable **hotfix** if the add-on milestone needs the exit gone before Option A's test infrastructure exists. It isn't a substitute for Option A: it keeps the code shape that prior art and 043's own "conceptual complexity" warning argue against.

## Concerns / Footguns Checklist

Each item names its evidence. Tier: **D** = direct (code/doc), **S** = supported, **I** = inferred.

**Reconnect loop**
- [ ] **F1. Backoff reset point.** Reset only after the connection has stayed up N seconds, never on socket-open or `auth_ok`. The proxy accepts, sends `auth_ok`, then drops, which produces a hot loop (node-red #76; `supervisor/api/proxy.py:371,390-393`). **D**
- [ ] **F2. Every non-auth failure stays in the loop.** That includes a drop of a stable connection, which is what a real HA restart is. Today only early drops loop (`websocket_service.py:409-421`), and the system test passes only because the test restarts HA inside the 30 s window. **D**
- [ ] **F3. Classify 502/503 and close-after-`auth_ok` as transient.** These are the add-on path's normal restart signals (AppDaemon #2540; Supervisor source). **D**
- [ ] **F4. Bound every phase with a timeout.** Connect, handshake, auth and the subscribe response all need one. A wedged HA that accepts TCP hangs clients forever otherwise (node-red #2027, js-ws #760, remote_homeassistant #394). Hassette already has connect (5 s), total (30 s) and auth (10 s) timeouts. Verify they cover the proxy-race case and that a dead recv task fails pending futures. **I**
- [ ] **F5. The recv loop must survive any exception shape** (hass-client #275). `dispatch` catches already; `raw_recv` frame handling is the place to check. **I**
- [ ] **F6. A permanent error can loop forever** (AppDaemon #2676, a 4 MiB `get_states`). Hassette uses aiohttp's default `max_msg_size=4194304` and fetches `get_states` over WS. Either raise the limit or classify close code 1009 as a distinct, loudly logged failure. **S**
- [ ] **F7. Log volume across long outages.** Hassette persists logs to its DB. Per-attempt logs should be DEBUG, with WARNING on the first failure, a periodic "still unreachable after N min", and INFO on recovery (aioesphomeapi's pattern). Apps' own failing HA calls also log every tick for the whole outage (#967). **I**

**Readiness and state**
- [ ] **F8. `auth_ok` ≠ ready on the direct path.** HA serves WS from the moment `frontend` is up, before the recorder and integrations (`components/http/__init__.py:206`). The resync can capture a partial snapshot, and because it replaces state, entities can vanish from the cache until their integration loads (AppDaemon #2226, node-red #1908, js-ws #130/#272). **D**
- [ ] **F9. HA-lifecycle events are an unreliable restart signal.** Through the proxy, `homeassistant_start`/`started` always fire before the add-on can connect. On the direct path, whether they're seen depends on backoff timing. Apps using `bus.on_homeassistant_start` to republish `set_state` entities (hautomate `car_status.py:161`) will silently miss it under the add-on. AppDaemon hit the same thing (#2226 side effect). This bears directly on #1676: the framework needs its own "HA restarted" signal. **S**
- [ ] **F10. A restart storm reaches apps.** At `homeassistant_start`, HA writes `unavailable` + `restored: true` for every unloaded registry entity, then real states as integrations load (`helpers/entity_registry.py:2827-2837`). Today some of this lands while hassette is dead and restarting. With a fast reconnect, every `on_state_change` handler will see `unavailable → on` transitions. That's HA's behavior and doesn't need fixing, but it should be documented. **D** (HA side) / **I** (app impact)
- [ ] **F11. Resync must replace, not merge** (js-ws #769). Hassette's full `get_states` commit already replaces (per the StateProxy reading). Keep it that way in any core-state second pass. **S**
- [ ] **F12. Events in the gap are lost.** No client replays them. Non-state events (`call_service`, custom events) fired during the outage are gone, and only states are recovered. Document it. **D** (consensus)
- [ ] **F13. Keep the state-proxy poll** (#2699 comment). It is the catch-all for missed state and the natural place for a `get_config` RUNNING re-check. **D**
- [ ] **F14. Blanket `subscribe_events` during the startup storm.** HA's per-client pending-message cap is 4096 (AppDaemon #1614). If bus dispatch backpressures `recv_loop`, HA may drop the client mid-storm, which looks like another outage. **Speculative.** Check whether `dispatch_hass_event`'s `await send_event` can block.

**Lifecycle and health**
- [ ] **F15. `serve()` never finishing means ServiceWatcher never sees the outage.** Status comes only from `mark_not_ready` reasons and `ConnectionState`. `/api/health` shows `starting` (never connected) or `degraded` (connected before), and `/ready` returns 503. 129 D14's Watchdog uses `/live`, so it is unaffected. **D**
- [ ] **F16. Rate-limit or dedupe `_emit_readiness_event`** per failed attempt. Otherwise a long outage spams status events into the bus, telemetry and UI. **I**
- [ ] **F17. `_first_connection_attempt_done_event` stays set forever after the first failure.** StateProxy's 30 s bootstrap wait (`state_proxy.py:243-262`) relies on this. Keep the semantics, or update the docstring. **D**
- [ ] **F18. Don't swallow cancellation.** Keep `except Exception` and not `BaseException` around the backoff sleep. Check that `anyio.fail_after` in `authenticate` doesn't convert a shutdown cancel into a retry. **I**
- [ ] **F19. `WS_VALID_TRANSITIONS` comments** (`:63-73`) describe "max retries exhausted". An auth-failed terminal state needs a transition entry, and strict-lifecycle mode raises on unlisted transitions. **D**

**Auth**
- [ ] **F20. Retrying `auth_invalid` has side effects inside HA.** Each attempt writes a WARNING, a "Login attempt failed" persistent notification, and a ban count if a threshold is configured. A ban makes later handshakes 403 (`http/ban.py:81-170`). Fast or unbounded auth retry is the one place "retry forever" is wrong. **D**

**Tests**
- [ ] **F21. The existing `system_destructive` reconnect tests mask the production path.** They restart HA within 30 s of connecting (early-drop window), and the test container's refusal window is under 17 s. A new test must connect, wait past the stable window, `docker stop`, hold longer than the old budget (e.g. 30-40 s, which fits the 120 s pytest timeout in `noxfile.py`), `docker start`, and assert the same instance reconnects with ServiceWatcher's `_budgets` untouched. **D**

## Open Questions

### Needs user decision
- [x] **Backoff cap.** → **Decided: ~5 s cap** (matches js-ws/node-red/AppDaemon).
   The issue proposes 1 s → 30 s, but its own Expected Behavior says "reconnects within a few seconds". HA-ecosystem clients cap at 5-10 s. Pick roughly 5-10 s (fast recovery, trivial load on a LAN HA or the Supervisor proxy), or keep 30 s (quieter during long outages)?
- [x] **`auth_invalid` policy.** → **Decided: (a) stay up, stop retrying.**
   Stay up in all cases (no exit). Then choose:
  - (a) Stop retrying until the process restarts or config changes, as js-ws, node-red, MQTT and config entries do.
  - (b) Retry on a long fixed interval (e.g. 5-10 min) in case the token was rotated. ESPHome pins its backoff at 60 s in a similar way.
  - (c) A handful of retries, then (a), as a hedge against the clock-skew edge case.
  - Every retry adds a "Login attempt failed" notification in HA.
- [x] **Core-state gating scope.** → **Decided: (ii) resync at RUNNING and gate first app bootstrap on RUNNING.**
   Pick one:
  - (i) Resync again on `homeassistant_started` / RUNNING only.
  - (ii) Also hold first app bootstrap until RUNNING (AppDaemon #2226).
  - (iii) Ship the loop first and do core-state awareness as a follow-up.
- [x] **Config surface.** → **Decided: module constants only.**
   Module constants only (matches most prior art and the laziness rule), or keep 2-3 fields (e.g. `reconnect_max_delay_seconds`, `reconnect_stable_seconds`)?
- [x] **Decided: drop it.** **Opt-in exit (`exit_if_ha_unreachable_seconds`).** Found no prior art for it. 018 rejected the equivalent `require_ha_connection` flag. Drop it?
- [x] **Fate of `CouldNotFindHomeAssistantError`.** → **Decided: delete (BREAKING footer); pre-v1 no-shims policy.**
   Delete it, since it is public in `__all__` (that needs a BREAKING footer), or keep it as a non-fatal type used only for diagnostics?
- [x] **Hotfix sequencing.** → **Decided: straight to Option A, no Option B hotfix.**
   Ship Option B first to unblock the add-on milestone, then Option A, or go straight to A?
- [x] **Corpus behavior change.** → **Decided: land #1676 in the same PR *if* HA emits a reliable restart signal reachable on both direct and Supervisor-proxy paths; otherwise ship #1676 separately with a migration note.** (Investigation result: no reliable signal on both paths, so **#1676 ships separately**; this PR carries a migration note.)
   Apps that relied on the post-restart re-init (hautomate `monarch/*`) lose it. Does #1676 (or a framework "HA restarted" signal, see F9) need to land in the same release, or is a changelog/migration note enough?

### Needs investigation
- [x] **Resolved (probe):** yes. `subscribe_events` (and the post-reconnect `get_states` observer) waits the full `response_timeout_seconds`, because recv-task death never calls `PendingResponses.fail_all` (`_handle_recv_task_done` only flips state). Then `ClientConnectionResetError`, which isn't in `EARLY_DROP_RETRYABLE`. **Fix required:** fail pending futures when the recv task ends. Original question: Does the proxy race (`auth_ok`, then immediate close) make `subscribe_events` wait the full `response_timeout_seconds` per attempt? That depends on whether recv-task death fails pending futures (`websocket_service.py:476-499`, `:615-642`). Reproduce with a fake server.
- [x] **Resolved (source + probe; Docker ARP inferred):** no DNS failure (`supervisor` is a static ExtraHosts entry -> 172.30.32.2). Supervisor stopping -> close 1001, then ECONNREFUSED while the listener is down; container gone -> connect timeout/EHOSTUNREACH; Supervisor starting -> ECONNREFUSED until the API binds, then 502 until Core RUNNING. **Refused is still fatal today, so the add-on can hit the fatal path during Supervisor restarts.** Original question: What does a client see on `ws://supervisor/...` while **Supervisor itself** restarts (DNS failure on `supervisor`, refused, or something else)? Unverified in the Supervisor source. Today that could still hit the fatal path.
- [x] **Resolved (probe + evidence):** plausible on very large installs (~469 B/state on a 1175-entity HA, so 4 MiB is about 8,900 entities; AppDaemon #2676 saw 6.1 MB). aiohttp surfaces `WSMsgType.ERROR` + close 1009; the pending `get_states` then hangs to timeout. hassette sets no `max_msg_size`. **Recommend 16 MiB** (python-hass-client, remote_homeassistant) and classify 1009 as a distinct loud failure. Original question: Is a large install's `get_states` actually over 4 MiB in practice, and what does aiohttp surface (close 1009 / `WSMsgType.ERROR`)? Decide whether to raise `max_msg_size`.
- [x] **Resolved (source + prod log; not run end-to-end):** the budget resets every restart (`mark_ready` in `on_initialize` -> RUNNING -> `await_service_readiness` -> `budget.reset()`; covered by `tests/integration/test_service_watcher.py:429`). Cooldown/exhaustion are unreachable for WS. Direct refused -> fatal on the first restart cycle; 502/DNS/timeout -> endless FAILED/restart cycles. Original question: Confirm at runtime that the WS restart budget resets on every restart (`service_watcher.py:644-670` + unconditional `mark_ready`). This matters for how Option B behaves and for correcting the issue text.
- [x] **Resolved (source; triggering inferred):** yes structurally. recv_loop awaits a send into a 1000-buffer stream; bus dispatch blocks on a 50-slot semaphore. The realistic HA trigger is `PENDING_MSG_PEAK=1024` sustained for 10 s, not 4096. Also an inferred livelock risk (handlers awaiting HA responses the blocked reader can't deliver). Low probability; note in design, not a blocker. Original question: Can `dispatch_hass_event` backpressure `recv_loop` enough to hit HA's 4096 pending-message cap during the restart storm (F14)?
- [x] **Resolved (probe):** rejected. `check_unknown_keys` raises `ConfigError` at startup for unknown TOML/env keys, so deleting the websocket retry fields hard-fails users who set them. Needs a BREAKING footer, a changelog/docs list of removed keys, and a schema regen. Original question: How do removed config keys in a user's `hassette.toml` behave under `ExcludeExtrasMixin`: rejected, warned, or silently dropped? Relevant to "no shims" messaging.
- [x] **Resolved (source + live):** no dedicated signal. `get_config`, `auth_ok` and Supervisor `/core/info` carry no Core start time; `sensor.uptime` is opt-in. Retroactive heuristic: `logbook/get_events` from the last-connected time shows `homeassistant` started/stopped entries (needs recorder + logbook). Hassette-local: "Core not RUNNING at reconnect" is detectable; a fast restart fully inside the gap is not. **Verdict for #1676: HA does not emit a restart signal reliably reachable on both paths (the proxy path connects after start/started fire), so #1676 ships separately per the user's condition.** Original question: Is there any HA-side signal that distinguishes "HA restarted" from "network blip" on reconnect (needed for F9/#1676)? Not found in `get_config`. Candidates to check: comparing `homeassistant_started` time_fired, or the `system_health`/`hassio` info endpoints.

## Recommendation

Go with **Option A**. The evidence for the core direction is strong (**Supported**): every surveyed long-lived HA client, HA's own MQTT, ESPHome and config-entry conventions, Supervisor's tolerance of 10-15+ minute Core startups, and Kubernetes probe guidance all say to stay up and retry indefinitely on connection errors. No surveyed project exits on HA unreachability, at first start or after. Hassette's own specs 018, 043 and 070, and its health docs, already promise this.

Refine the issue's proposal in five places, each grounded above:
1. **Cap the backoff near 5-10 s, not 30 s.** This is an inference from prior-art clustering and the issue's own expectation. It's the user's call (Open Questions).
2. **Reset backoff only after a stable window.** Treat proxy 502 and close-after-`auth_ok` as transient (Direct: Supervisor source, node-red #76).
3. **Make `auth_invalid` a stay-up terminal state, not an exit and not a fast retry** (Direct for the HA-side cost; Supported for "never transient", about 85-90% confidence). Whether to add a slow retry is the user's call.
4. **Add core-state awareness to the resync**, at minimum a second resync at RUNNING (Supported: AppDaemon #2226, node-red #1908, js-ws #130). Consider gating first app bootstrap on RUNNING, which also covers the cold-start half of the scope.
5. **Delete, don't rename.** That covers `early_drop_policy.py`, the tenacity connect layer, `max_recovery_seconds` and the misleading budget log. Give StateProxy's sync retry its own constants.

Correct the issue text: the 300 s cooldown is likely unreachable for WS, and the add-on path sees 502, not refused. Neither correction changes the decision. Both change which acceptance tests prove the fix.

If the add-on milestone can't wait for the fake-WS-server test infrastructure, Option B is an acceptable stopgap. Ship it explicitly as such, with Option A queued behind it.

### Suggested next steps
1. Settle the Open Questions marked "needs user" via `/mine-sketch`: backoff cap, auth policy, core-state scope, config surface, hotfix or not.
2. Write the RED system test first (F21). It needs a connection held past the stable window, `docker stop` for longer than 17 s, then `docker start`, and must assert the same instance survives. Add a cold-start variant where HA appears later.
3. Build an in-process aiohttp fake WS server for integration tests. Script it for: refuse-then-accept, 502 on upgrade, `auth_ok`-then-close, `auth_invalid`, accept-then-drop (for backoff reset), and handshake hang. Add an injectable sleep for unit tests.
4. Land the loop (subtraction first: delete early-drop and tenacity, then reshape `serve()`), then core-state awareness as its own verifiable unit, then the docs rewrite (`operating/index.md`, `troubleshooting.md`) with the voice and doc-review passes.
5. Comment on #1676 with F9: `homeassistant_start` can't be the app-facing restart signal under the add-on.

## Sources

- AppDaemon: [hassplugin.py](https://github.com/AppDaemon/appdaemon/blob/b8b06ba/appdaemon/plugins/hass/hassplugin.py#L555-L595), [plugin_management.py](https://github.com/AppDaemon/appdaemon/blob/b8b06ba/appdaemon/plugin_management.py#L440-L449), issues [#2226](https://github.com/AppDaemon/appdaemon/issues/2226), [#1256](https://github.com/AppDaemon/appdaemon/issues/1256), [#2540](https://github.com/AppDaemon/appdaemon/issues/2540), [#1614](https://github.com/AppDaemon/appdaemon/issues/1614), [#2676](https://github.com/AppDaemon/appdaemon/issues/2676), [#2011](https://github.com/AppDaemon/appdaemon/issues/2011)
- home-assistant-js-websocket: [connection.ts](https://github.com/home-assistant/home-assistant-js-websocket/blob/4c5674c/lib/connection.ts#L441-L505), [socket.ts](https://github.com/home-assistant/home-assistant-js-websocket/blob/4c5674c/lib/socket.ts#L93-L107), issues [#130](https://github.com/home-assistant/home-assistant-js-websocket/issues/130), [#256](https://github.com/home-assistant/home-assistant-js-websocket/issues/256), [#272](https://github.com/home-assistant/home-assistant-js-websocket/issues/272), [#555](https://github.com/home-assistant/home-assistant-js-websocket/issues/555), [#760](https://github.com/home-assistant/home-assistant-js-websocket/issues/760), [#769](https://github.com/home-assistant/home-assistant-js-websocket/issues/769); frontend [connection-mixin.ts](https://github.com/home-assistant/frontend/blob/dev/src/state/connection-mixin.ts)
- node-red-contrib-home-assistant-websocket: [createSocket.ts](https://github.com/zachowj/node-red-contrib-home-assistant-websocket/blob/main/src/homeAssistant/createSocket.ts), [Websocket.ts](https://github.com/zachowj/node-red-contrib-home-assistant-websocket/blob/main/src/homeAssistant/Websocket.ts#L529), issues [#76](https://github.com/zachowj/node-red-contrib-home-assistant-websocket/issues/76), [#1908](https://github.com/zachowj/node-red-contrib-home-assistant-websocket/issues/1908), [#2015](https://github.com/zachowj/node-red-contrib-home-assistant-websocket/issues/2015), [#2027](https://github.com/zachowj/node-red-contrib-home-assistant-websocket/issues/2027)
- Python clients: [python-hass-client](https://github.com/music-assistant/python-hass-client/blob/3e68c91/hass_client/client.py#L330) / [#275](https://github.com/music-assistant/python-hass-client/issues/275), [Music Assistant mass.py](https://github.com/music-assistant/server/blob/1611ea1/music_assistant/mass.py#L134-L135), [remote_homeassistant](https://github.com/custom-components/remote_homeassistant/blob/bd554c4/custom_components/remote_homeassistant/__init__.py#L403-L552) / [#170](https://github.com/custom-components/remote_homeassistant/issues/170), [#211](https://github.com/custom-components/remote_homeassistant/issues/211), [#394](https://github.com/custom-components/remote_homeassistant/issues/394)
- HA core and Supervisor: local checkouts `home-assistant/core@abe1fdd7` and `home-assistant/supervisor@f2a8d3df` (paths cited inline); [aioesphomeapi reconnect_logic.py](https://github.com/esphome/aioesphomeapi/blob/main/aioesphomeapi/reconnect_logic.py); [add-on communication](https://developers.home-assistant.io/docs/add-ons/communication/), [add-on configuration](https://developers.home-assistant.io/docs/add-ons/configuration/)
- Conventions: [AWS Exponential Backoff and Jitter](https://aws.amazon.com/blogs/architecture/exponential-backoff-and-jitter/), [Kubernetes probes](https://kubernetes.io/docs/concepts/configuration/liveness-readiness-startup-probes/), [Kubernetes pod lifecycle](https://kubernetes.io/docs/concepts/workloads/pods/pod-lifecycle/), [Liveness Probes are Dangerous](https://srcco.de/posts/kubernetes-liveness-probes-are-dangerous.html), [systemd.service](https://man7.org/linux/man-pages/man5/systemd.service.5.html), [Kafka AuthenticationException](https://kafka.apache.org/42/javadoc/org/apache/kafka/common/errors/AuthenticationException.html)
- Hassette internal: issue #2701; specs `design/specs/018-dashboard-without-ha`, `043-websocket-service-resilience`, `070-health-liveness-readiness`, `129-ha-addon-v01` (D4, D14); research `design/research/2026-05-01-websocket-client-mgmt`, `2026-04-28-service-supervision`, `2026-10-10-ha-addon-conventions`

### Additions from open-question investigation (2026-10-12)

Option A stands, with four additions:
1. **Fail pending futures when the recv task dies.** Confirmed bug; otherwise the proxy-race and 1009 paths each cost a full response timeout per attempt.
2. **Raise `max_msg_size` to 16 MiB and surface close 1009 distinctly.**
3. **Config-key removal story.** Removed websocket keys hard-fail startup: BREAKING footer, changelog/docs list, schema regen.
4. **Supervisor-restart refused windows are real.** Add refuse-then-accept to the add-on-path acceptance tests.
