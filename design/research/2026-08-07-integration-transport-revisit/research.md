---
proposal: "Re-open ADR-0004 (companion integration transport). Re-test the rejection of T3 — hassette hosts a server, the integration connects to it — against facts that changed after 2026-07-07: web API auth, CLI remote-URL targeting, an existing hassette WebSocket server, and a new motivation to publish a thin standalone client package."
date: 2026-08-07
status: Draft
flexibility: Exploring
motivation: "Three of the ADR's premises may have decayed, and a new packaging goal (a stdlib-light `hassette` CLI installable without the framework) might be better served by a single client library shared between the CLI and the integration."
constraints: "Do not write or modify an ADR. Do not touch design/adrs/0004-*. Do not modify source code. Solo-dev, self-hosted, personal-scale calibration — no enterprise patterns."
non-goals: "Re-litigating T2 (plain HA services) or MQTT Discovery (D2). Designing the entity protocol itself. Implementing anything."
depth: deep
---

# Research Brief: Revisiting ADR-0004 — Companion Integration Transport

**Initiated by**: A request to re-test ADR-0004's rejection of **T3** ("hassette hosts a server; the
integration connects to it") now that three of its premises have changed, plus a new packaging
motivation the ADR never weighed.

## Context

### What prompted this

ADR-0004 (Accepted 2026-07-07) chose **T1**: the HACS companion integration registers custom
`hassette/*` WebSocket commands inside HA via `websocket_api.async_register_command`, and hassette
calls them over the WS connection it already maintains. It rejected **T3** on exactly three grounds:

> adds network reachability configuration, a pairing secret, and a second reconnect state machine,
> with no capability the chosen design lacks.
> — `design/adrs/0004-companion-integration-transport.md:40-42`

Since then:

1. **Web API auth shipped.** PR #1521 (`feat!: require authentication for the web API by default`),
   merged as `02ae0098` — verified via `git log --oneline -1 02ae0098`. `src/hassette/web/auth.py`
   is 778 lines implementing token resolution, bearer/cookie/trusted-peer precedence, and a shared
   `authorize_ws()`.
2. **CLI remote targeting shipped.** `src/hassette/cli/target.py` (290 lines) implements
   `--server-url`, per-target credentials, TLS verify, and refusal to leak local credentials to
   non-loopback targets.
3. **A new motivation.** Publish a thin client package so `hassette` (the CLI) can be installed
   standalone to administer a remote instance — and possibly serve the integration too, collapsing
   `hassette-protocol` (`prereq-03`) into it.

Point 3 is the genuinely new input. Points 1 and 2 are cheap to re-check; point 3 was never weighed.

### Current state

**Nothing from the integration epic is implemented.** Verified:

- `gh issue view 45/46/71` → all three **OPEN**. #45 and #46 carry `epic:hacs`; #71 carries
  `epic:ha-addon`. `gh issue list --label epic:hacs --state all` returns exactly those two, both open.
- `grep -rIl -e 'hassette-protocol' -e 'async_register_command' -e 'config_flow' -e 'custom_components' .`
  matches **only** files under `design/` — the ADR and the four prereq/research docs. Zero source hits.
- `git log --all --grep='hacs|companion integration|entity registry|hassette-protocol' -i` returns one
  commit: `77f42cae chore: architecture designs for epic:hacs and epic:ha-addon (#1240)`.
- `grep -rn "instance_id" src/` returns nothing — even `prereq-01` (instance identity) is unbuilt.

**The claim that switching now costs design time, not code, is confirmed.**

Three pieces of shipped infrastructure are directly relevant:

**The outbound HA client** (`src/hassette/core/websocket_service.py`, 927 lines). `send_and_wait`
(`:714-753`) provides id-correlated request/response over `send_and_await_response` (`:594-623`),
with tenacity retry. The reconnect machinery spans roughly `:344-588` (~245 lines): `serve()`
(`:408-443`), early-drop classification (`:365-373`), exponential backoff capped at 60s
(`:552-563`), and connect retry capped at 32s over 5 attempts (`:565-588`). `dispatch` (`:886-896`)
is a three-arm `match` that routes **every** `type: "event"` frame to `dispatch_hass_event` with no
subscription-id branch — exactly as ADR-0004 states at `:47-49`. No subscription-id routing exists
anywhere in `src/`; the single permanent `subscribe_events` id is tracked (`:113,137,481,524,548`)
only for cleanup.

**The inbound web server** (`src/hassette/web/routes/ws.py`, 113 lines, mounted at `/api/ws` via
`src/hassette/web/app.py:96`). This is the piece the revisit premise leans hardest on, and it is
much thinner than "hassette already runs a WebSocket server" suggests:

- Client→server accepts exactly two message types (`ws.py:41-59`): `{"type":"ping"}` → `pong`, and
  `{"type":"subscribe","data":{"logs":bool,"min_log_level":str}}`, which toggles a per-connection
  log filter. **There is no request id, no correlation, no command dispatch, no topic namespace.**
- Server→client is an unconditional broadcast fan-out. `RuntimeQueryService` holds
  `_ws_clients: set[asyncio.Queue]` (`src/hassette/core/runtime_query_service.py:60,74`);
  `broadcast()` (`:409-438`) `put_nowait`s to every queue and **drops on `QueueFull`** (maxsize 256)
  rather than applying backpressure. Every connected client receives every event except logs.
- `frontend/ws-schema.json` and `frontend/src/api/ws-types.ts` describe a `WsServerMessage`
  discriminated union only — six server→client shapes. There is no client→server schema.

So hassette's WS server is a **dashboard telemetry firehose**, not a reusable command channel.

**Auth** (`src/hassette/web/auth.py`). `resolve_auth_token()` (`:115-176`) resolves config value →
`<data_dir>/.web_api_token` (`TOKEN_FILENAME`, `:48`) → freshly generated `secrets.token_urlsafe(32)`
written atomically at mode `0600`. `resolve_auth_outcome()` (`:673-732`) is the single precedence
function shared by `DefaultDenyMiddleware` (`src/hassette/web/middleware.py:234-296`, gating the
`/api/` prefix) and `authorize_ws()` (`:735-778`, called pre-`accept()` from `ws.py:88`). Auth is
enforced identically on HTTP and WS via handshake headers/cookies. Default bind is `0.0.0.0:8126`
(`src/hassette/config/models.py:342-345`).

### Key constraints

- Solo dev, self-hosted, personal scale. One hassette instance is the norm; N is rare.
- Nothing implemented → design-only migration cost.
- ADR-0004 and ADR-0005 must not be edited by this brief.
- `design/specs/091` and `092` are shipped and archived; their behavioral invariants are live.

---

## 1. T1 and T3 restated with today's facts

### T1 as designed

Hassette opens one WS to HA (it already does, for events). After auth it sends
`hassette/handshake`, then `hassette/subscribe`, then batched `hassette/entity/register` /
`entity/update` / `entity/remove` / `sync` commands. The integration stores its subscription
cleanup in `connection.subscriptions[msg_id]`; HA invokes it on disconnect. HA→hassette pushes
(entity commands, later service calls and webhooks) ride back as `event_message` frames on that
subscription. Config flow has zero fields; instances self-identify at handshake (D5).

### T3 as it would actually be built today

Not "hassette hosts a server" in the abstract — concretely:

- Hassette grows an entity-bridge surface on its existing FastAPI app: REST routes for
  register/update/remove/sync (trivial — ten routers already registered at `web/app.py:89-98`),
  **plus** topic-scoped WS subscriptions so entity-command pushes reach the integration without
  also flooding the dashboard, and so dashboard telemetry doesn't flood the integration. The
  existing `subscribe` handler (`ws.py:49-54`) is a one-topic prototype of this, not the thing itself.
- The integration is a WS client (see §2.4). Its config flow takes URL + token + verify-SSL, or
  gets them free via Supervisor discovery in the add-on topology.
- Auth is the existing bearer token — the same one the CLI uses.

### The three rejection grounds, re-assessed

| Ground | Verdict | One-line reason |
|---|---|---|
| "network reachability configuration" | **Weakened, topology-dependent — still fully holds for one shape** | Moot for the add-on (Supervisor discovery), near-moot same-host, fully live for remote-host/VPS |
| "a pairing secret" | **Moot** | The token exists, is auto-generated, and a URL+token+verify_ssl config flow is a shipped, platinum-tier HA pattern |
| "a second reconnect state machine" | **Weakened as written; the underlying concern is stronger than the ADR articulated** | The integration writes ~40 lines, not a subsystem — but hassette's WS server is *not* reusable, and the real cost is a second failure domain, not a state machine |

#### Ground 1 — network reachability configuration

**Add-on topology (ADR-0005): moot.** Supervisor's discovery API makes this zero-config, including
the token. Verified end to end:

- An add-on declares `discovery: [<service>]` in `config.yaml` and POSTs
  `{"service": ..., "config": {...}}` to Supervisor `/discovery`. The only access check is that the
  add-on listed the service itself — there is no whitelist of known service names
  ([`supervisor/api/discovery.py`, `set_discovery`](https://github.com/home-assistant/supervisor/blob/main/supervisor/api/discovery.py)).
- HA Core's `hassio` integration then calls
  `discovery_flow.async_create_flow(hass, data.service, context={"source": SOURCE_HASSIO}, data=HassioServiceInfo(config=data.config, ...))`
  ([`homeassistant/components/hassio/discovery.py`, `async_process_new`](https://github.com/home-assistant/core/blob/dev/homeassistant/components/hassio/discovery.py)).
  **`service` is used directly as the target integration's domain**, and `config` is handed to
  `async_step_hassio` verbatim — so host, port, *and token* arrive with no user input.
- This is exactly how Z-Wave JS works: `zwave_js/config.yaml` declares `discovery: [zwave_js]`, and
  `zwave_js/config_flow.py:457` builds `self.ws_address = f"ws://{discovery_info.host}:{discovery_info.port}"`.
- Add-ons are reachable from HA Core by container name on the shared `hassio` bridge **without any
  `ports:` host mapping** — the add-on communication docs state the internal network "is allowed to
  communicate with every app, including to/from Home Assistant, by using its name or alias."

**Same-host Docker: near-moot.** This repo's own demo stack already proves bidirectional
reachability: `scripts/docker/ha-demo.yml` sets `HASSETTE__BASE_URL: "http://homeassistant:8123"`,
i.e. hassette reaches HA by Compose service name. The reverse (`http://hassette:8126`) works by the
same mechanism. Config cost: one URL the user types once. **Caveat:** HA's own documented
container install uses `--network=host`, and Compose service-name DNS does not work for a
host-networked container — such a user must supply a host IP instead.

**Remote host / VPS: this ground fully holds, and it is worse than "type a URL."** Spec 092's own
research documented the concrete failure against Jessica's live deployment: `tinyauth` returns 401
to a valid hassette bearer token before the request reaches hassette, because it is browser-OIDC
forward auth with no bypass configured (`design/specs/092-cli-remote-url/design.md:163`). Making
the integration reachable there requires a proxy-side change — a second router for `/api` without
the auth middleware, a bypass rule, or a tunnel — *in the operator's own infrastructure*. That is
not "a URL and a token." Under T1, nothing ever needs to reach hassette, so this class of problem
does not exist.

**Assessment (Supported):** the ground is narrower than the ADR implies but not dead. It is moot for
the topology ADR-0005 targets and live for the topology Jessica personally runs.

#### Ground 2 — a pairing secret

Moot on both halves.

**Hassette side.** The token already exists, is generated on first start with zero configuration
(`web/auth.py:115-176`), and is already consumed by a non-browser client:
`cli/target.py:252-260` declares five credential sources with `cli`/`server` scopes, and `:285-286`
skips server-scoped sources for non-loopback targets. Handing that token to a config flow is not
new machinery.

**HA side.** "Integration takes a URL + API token + verify-SSL" is a first-class, blessed pattern.
`paperless_ngx` is **platinum** quality scale with exactly that three-field flow
(`CONF_URL` + `CONF_API_KEY` + `CONF_VERIFY_SSL`, all imported from `homeassistant.const`) plus a
reauth step. `mealie` does the same with `CONF_HOST`/`CONF_API_TOKEN`/`CONF_VERIFY_SSL`. At least
eleven core integrations match the shape (`zwave_js`, `music_assistant`, `octoprint`, `unifi`,
`jellyfin`, `mealie`, `paperless_ngx`, `proxmoxve`, `nut`, `wyoming`, `esphome`).

One wrinkle worth naming: `CONF_VERIFY_SSL` exists in `homeassistant/const.py` and is used by at
least five integrations, but a code search of the developer-docs repo for `verify_ssl` returns zero
hits. It is convention-by-precedent, not written standard. That does not weaken the pattern; it
just means there is no doc to point at.

**Assessment (Direct):** this ground no longer holds.

#### Ground 3 — a second reconnect state machine

This one needs to be split, because the ADR's sentence and the ADR's actual concern are different
things.

**As written, it is weakened — but not for the reason the revisit premise supposes.**

The premise says hassette already runs a WS server, so the state machine partly exists. That is
**wrong in the direction that matters**. Hassette's server (`ws.py`, 113 lines) has no request
correlation, no command dispatch, and no topics beyond a logs on/off flag. `frontend/ws-schema.json`
has no client→server half. An integration could not speak to it today; the reusable part is the
transport plumbing (accept, task group, disconnect classification at `ws.py:27-38`, queue drain),
not the protocol. The frontend's reconnect logic (`frontend/src/hooks/use-websocket.ts`, ~40 of 233
lines) is TypeScript in a browser and reusable by nothing.

What *does* weaken the ground is the HA side, and the evidence is strong. Neither `zwave_js` nor
`music_assistant` — nor either of their client libraries — implements a retry/backoff loop. They
detect "socket closed" and ask HA to reload the config entry:

```python
# homeassistant/components/zwave_js/__init__.py — client_listen(), ~37 lines total
if entry.state.recoverable:
    LOGGER.debug("Disconnected from server. Reloading integration")
    hass.config_entries.async_schedule_reload(entry.entry_id)
```

HA core then owns the backoff. Verified in `homeassistant/config_entries.py`:
`SETUP_RETRY_MAX_WAIT = 600` (`:141`) and
`wait_time = min(2**self._tries * 5, SETUP_RETRY_MAX_WAIT) + jitter` (`:843`) — 5s, 10s, 20s, 40s …
capped at 10 minutes. So the integration-side cost is roughly **25-40 lines**, not a subsystem.

**But the ADR's underlying concern is stronger than its wording, and survives intact.** Restated
correctly, T3 introduces a **second independent failure domain**:

- Under T1 there is one connection. If it is down, hassette is non-functional anyway — it cannot
  read state or call services. Entity availability and framework availability are the same fact.
- Under T3 there are two: hassette→HA (events, state, service calls) and HA→hassette (entities).
  They fail independently. Reachable new states include "hassette is running fine and driving the
  house, but all its HA entities show unavailable because a proxy rule changed" and the converse.
  Neither is reachable under T1.

There is also a modest, concrete availability cost. Under T1, recovery is bounded by hassette's own
reconnect: early-drop backoff caps at 60s (`websocket_service.py:552-563`), connect retry at 32s
over 5 attempts (`:565-588`). Under T3, recovery after a longer hassette outage is bounded by HA's
config-entry backoff, which grows to 10 minutes. For a 5-minute hassette deploy, entities can stay
unavailable for several minutes after hassette is back.

**Assessment (Supported):** the literal claim is weakened; the concern it was pointing at is real,
and the ADR undersold it by framing an architectural property as an implementation cost.

---

## 2. Capability parity

### 2.1 The four in-process capabilities are transport-independent — confirmed

Registry entities, native services, device registry entries, and webhook registration all require
Python running inside HA's process (`design/research/2026-07-07-companion-integration-architecture/research.md:9-22`).
That is a statement about *where code runs*, not about *how the two processes talk*. Under both T1
and T3 the integration exists and does the same `async_add_entities` / `services.async_register` /
`DeviceInfo` / `webhook.async_register` work. **The transport choice is genuinely independent of all
four.** Nothing in either direction changes this.

Corollary worth stating plainly: `prereq-04` (the `EntityRegistry` core service and the per-app
`self.entities` resource) and `prereq-06` (the six HA entity platforms) are **substantially
transport-agnostic**. They are also the bulk of the epic's work. Only the client shim inside
`prereq-04` and the command-ingress half of `prereq-05` change.

### 2.2 Availability / liveness — the ADR's strongest argument, honestly graded

The mechanism is real and I verified it first-hand rather than trusting the ADR.
`homeassistant/components/websocket_api/connection.py`:

```python
self.subscriptions: dict[Hashable, Callable[[], Any]] = {}     # :81

@callback
def async_handle_close(self) -> None:                           # :256-270
    for unsub in self.subscriptions.values():
        try:
            unsub()
        except Exception:
            self.logger.exception("Error unsubscribing from subscription: %s", unsub)
    self.subscriptions.clear()
    self.send_message = self._connect_closed_error
```

Three properties hold: every stored callable fires on close; one raising unsub does not abort the
rest; and post-close sends get a clean error rather than a crash. `hass-node-red` uses exactly this
(`custom_components/nodered/websocket.py:331,413`), as does HACS itself.

**But the ADR overstates the comparison.** Under T3 with a persistent integration→hassette WS, the
integration *owns* the socket and observes its close directly — the same signal, in the same
process, at the same latency. `zwave_js`'s `client_listen()` is precisely that pattern.

So the honest grading is:

| | T1 | T3 (integration as WS client) |
|---|---|---|
| Disconnect signal exists | Yes | Yes |
| Signal quality / latency | TCP + aiohttp heartbeat (30s, `websocket_service.py:457-459`) | TCP + whatever the client sets |
| Who writes it | **HA's framework, free** | The integration (~40 lines) |
| Recovery bound | hassette's own loop, ≤60s | HA config-entry backoff, ≤600s |
| Failure domains | **One** | **Two** |

**T1's liveness advantage is that it is free and that it collapses two failure domains into one —
not that the signal is better.** The ADR's "strongest single argument" framing is directionally
right but rests on the wrong clause. Treating it seriously means keeping it and fixing its
justification.

### 2.3 Multi-instance

- **T1:** N hassette instances each open their own WS. Each handshakes with its own `instance_id`;
  one zero-field config entry, N hub devices appearing dynamically (D5). Marginal user config per
  instance: **zero**.
- **T3:** HA must reach each instance. The natural shape is N config entries — one per instance,
  each with URL + token + verify-SSL. HA supports multiple entries per domain trivially, and
  `entry_id` gives stable identity for free (arguably making `prereq-01`'s `instance_id` optional).
  Marginal user config per instance: **one config flow, three fields, plus whatever proxy work that
  instance's topology needs.**

For a solo dev running one instance this is a difference between "nothing" and "a two-minute
one-time setup." It is not decisive on its own. It becomes decisive only if the add-on ships and
Jessica wants installation to be genuinely click-and-done — and even there, Supervisor discovery
closes the gap for the add-on specifically.

### 2.4 Under T3, who initiates?

Three shapes; only one is viable.

- **Polling REST.** Rejected on its own terms. No liveness signal (stale entities stay available —
  the exact defect T2 was rejected for at `research.md:61-64`), latency on every entity update, and
  no callback path for entity commands without long-polling.
- **Integration holds a persistent WS to hassette.** The only sane option, and the one all the prior
  art uses. Entity registration and entity-command results flow client→server; state pushes flow
  server→client. Liveness falls out of socket close.
- **Both.** Registration/commands over REST, state pushes over WS. Workable and arguably tidier
  (REST gets you FastAPI validation and OpenAPI for free), but it means two channels whose health
  can disagree.

So T3 = "integration is a WS client, possibly with REST for the request/response half." Note the
direction inversion this forces on hassette: hassette *wants* to push registrations, but under T3 it
is the server, so registrations become something the integration pulls or something hassette pushes
down a socket it did not open. That is fine mechanically; it just means the protocol is not a
mirror image of T1's.

### 2.5 Capabilities T3 has that T1 lacks

The ADR claims "no capability the chosen design lacks." Checking the reverse direction, as asked:

**T3 removes the admin-token requirement.** This is real and the ADR does not mention it as a T3
advantage — it appears only as a T1 *risk*. Under T1 every `hassette/*` command is `@require_admin`
(`research.md:227-228`), with the stated consequence: *"hassette's long-lived token must belong to an
admin user. Document prominently."* `require_admin` raises `Unauthorized` unless
`connection.user.is_admin` (`websocket_api/decorators.py:54-69`). Under T3 the integration runs
inside HA with full in-process access and authenticates *to hassette* with hassette's own bearer
token; hassette's HA token then only needs whatever its normal read/call-service work needs. Users
who deliberately run hassette on a non-admin HA token keep working.

Weight: real, narrow. It is listed as the first Risk in the original brief (`research.md:234-235`)
with the mitigation "likely already true for most users."

**T3 keeps working if hassette's HA WS is unhealthy but hassette is up.** Marginal-to-worthless — if
hassette cannot reach HA, entity state has nothing behind it.

**Nothing else.** T3 gains no capability regarding registry entities, services, devices, or webhooks.

### 2.6 Capabilities T1 has that T3 lacks

- **Zero inbound exposure.** Nothing ever needs to reach hassette (`research.md:56`). This is a real
  asymmetry, quantified in §3.
- **Zero user configuration in every topology**, not just the discoverable ones.
- **One failure domain** (§1, ground 3).
- **Free liveness plumbing** (§2.2).
- **Faster recovery bound** (60s vs 600s).

---

## 3. Topology matrix

"Can HA reach hassette's web API" and "what must the user configure" — under T3. Under T1 the
answer is uniformly **N/A / nothing**, which is the asymmetry to quantify.

| # | Deployment shape | HA → hassette reachable? | User must configure (T3) | User must configure (T1) |
|---|---|---|---|---|
| a | **HA add-on** (ADR-0005: derived image, ingress) | **Yes.** Add-ons and HA Core share the Supervisor `hassio` bridge; container ports are reachable by name (`{repo}_{slug}`, `_`→`-`) with **no** `ports:` mapping. | **Nothing** — the add-on's `run.sh` POSTs `{"service":"hassette","config":{host,port,token}}` to Supervisor `/discovery`; `async_step_hassio` completes the flow. Cost: one `discovery:` key in `config.yaml` + ~15 lines in `run.sh`. | Nothing |
| b | **hassette in Docker on the same host as HA** | **Usually.** Shared Compose network → service-name DNS (this repo's demo stack already relies on it in the other direction, `ha-demo.yml`). **Not** if HA runs `--network=host` (HA's own documented container install) or they are on different networks. | One URL + one token, typed once. Host-networked HA needs a host IP instead of a service name. | Nothing |
| c | **hassette on a different host / VPS** | **Only if the operator makes it so.** | URL + token + TLS decision, **plus** any proxy work. Concretely on Jessica's own deployment: tinyauth 401s a valid bearer token before hassette sees it (`092-cli-remote-url/design.md:163`), so this needs a second Traefik router for `/api`, a bypass rule, or a tunnel. Also: hassette now needs a reachable inbound port from HA's network — a firewall/exposure decision that does not exist today. | Nothing |
| d | **HAOS, hassette elsewhere on the LAN** | **Yes by IP.** Not reliably by `.local` — HA Core's Alpine base lacks nss-mdns, and Supervisor's DNS plugin only forwards `.local` to the host's resolver, which is flaky in practice (multiple open supervisor/OS issues). | URL (**use an IP or a real DNS name, not `.local`**) + token + TLS decision. A DHCP lease change silently breaks it. | Nothing |

**Quantifying the asymmetry.** For (a) it costs nothing. For (b) it costs one field. For (d) it
costs one field plus a standing "don't let the IP change" obligation. For (c) it costs a
credential, an inbound exposure decision, and — in the one deployment we have concrete evidence
about — a change to infrastructure that lives outside this repo.

So the honest summary is not "T3 costs configuration everywhere." It is: **T3 is free in the add-on
topology, cheap in the two LAN topologies, and genuinely expensive in the remote topology — which
happens to be the one Jessica runs.**

---

## 4. HA-side constraints for an outbound-connecting integration

### 4.1 Is "connect out to a user-configured URL + token" a normal HA pattern?

**Yes, unambiguously.** Eleven core integrations verified. Two are near-exact analogues:

**`paperless_ngx` — the config-flow template.** `quality_scale: platinum`. Its
`STEP_USER_DATA_SCHEMA` is three voluptuous fields: `CONF_URL`, `CONF_API_KEY`, `CONF_VERIFY_SSL`
(default `True`), with `cannot_connect` error mapping and a reauth step. This is the entire "URL +
token + TLS" problem, solved at HA's highest quality tier.

**`zwave_js` — the transport analogue.** Outbound WebSocket to a user-supplied `ws://` URL, with a
companion PyPI client library. Its manual schema is one field:

```python
def get_manual_schema(user_input: dict[str, Any]) -> vol.Schema:      # config_flow.py:135-138
    default_url = user_input.get(CONF_URL, DEFAULT_URL)               # DEFAULT_URL = "ws://localhost:3000"
    return vol.Schema({vol.Required(CONF_URL, default=default_url): str})
```

with validation that connects before creating the entry (`:147-157`, raising
`InvalidInput("cannot_connect")`). The file is 1741 lines, but the vast majority is Supervisor
add-on lifecycle management — install/start/configure the Z-Wave JS add-on. The manual path is tiny.
Note `zwave_js` has **no** auth and **no** TLS option (grep for `verify_ssl` across its config flow
and `__init__` returns nothing); take the transport shape from it and the credential shape from
`paperless_ngx`.

`music_assistant` (bronze) adds a third data point: a browser-redirect auth flow with a manual
token-paste fallback, and a granular setup error taxonomy worth copying —
`ConfigEntryNotReady` for timeouts/version mismatch, `ConfigEntryAuthFailed` for credential failure.

`CONF_VERIFY_SSL` is defined at `homeassistant/const.py:257` and used by `octoprint`, `unifi`,
`mealie`, `paperless_ngx`, `proxmoxve` — but is **undocumented** on developers.home-assistant.io.

### 4.2 Remote service down at HA startup

The required pattern is `ConfigEntryNotReady`, raised from the integration's `async_setup_entry`
(raising it from a *platform's* setup is documented as too late). HA then retries on a fixed
schedule — verified in `homeassistant/config_entries.py`:

```python
SETUP_RETRY_MAX_WAIT = 600  # 10 minutes                                      # :141
wait_time = min(2**self._tries * 5, SETUP_RETRY_MAX_WAIT) + jitter            # :843
```

5s → 10s → 20s → 40s → 80s → 160s → 320s → 600s cap, plus 0.05–0.5s jitter. `_tries` resets when
the entry leaves `SETUP_RETRY`. Two behaviors worth knowing: if HA is still booting it listens for
`EVENT_HOMEASSISTANT_STARTED` instead of setting a timer; and a discovery flow matching the same
unique ID short-circuits the wait and reloads immediately. The entry shows as **"Failed setup, will
retry"** in the UI. `ConfigEntryAuthFailed` triggers reauth instead; `ConfigEntryError` is terminal
(`SETUP_ERROR`, never retried).

For a **push** integration holding a persistent socket, no coordinator is required —
`integration_fetching_data` says a coordinator is usable "if you want," via
`coordinator.async_set_updated_data(data)`, and the entity pattern is `should_poll = False` +
`async_write_ha_state()` + subscribe in `async_added_to_hass`.

### 4.3 Quality scale

**It does not apply to custom/HACS integrations at all.** HA's quality-scale docs are explicit that
the project does not review, audit, maintain, or support third-party custom integrations, and
neither HACS docs page mentions a tier. HACS's own bar is much lower than the epic's `prereq-05`
assumes:

| | Core | HACS custom repo |
|---|---|---|
| Quality-scale tier | Bronze minimum, mandatory | **None** |
| hassfest | Required | **Not run** — HACS ships its own `hacs/action` checking `archived`/`brands`/`description`/`hacsjson`/`images`/`information`/`issues`/`topics`. hassfest is an optional tip |
| `==` pinning of requirements | Enforced (`hassfest/requirements.py`, gated on `integration.core`) | **Not enforced** — HACS's own manifest ships `aiogithubapi>=22.10.1` |
| `version` in manifest | Must be omitted | **Required** |
| brands repo submission | Required | **No longer required** since HA 2026.3 — a local `brand/` directory inside the integration takes precedence |

Bronze/Silver rules remain the right *target* because they encode real reliability behavior
(`test-before-setup`, `test-before-configure`, `runtime-data`, `config-entry-unloading`,
`entity-unavailable`, `reauthentication-flow`, `log-when-unavailable`, `parallel-updates`,
`docs-installation-parameters`) — but none of it is a gate. `prereq-05`'s hassfest CI step is
optional hygiene, not a requirement.

### 4.4 Dependencies — the decisive finding

**How `manifest.json` `requirements` works.** HA installs them **at runtime**, on first load of the
domain, into the config dir's `deps/` (or the venv). Verified in `homeassistant/requirements.py`:

```python
CONSTRAINT_FILE = "package_constraints.txt"                                   # :25

def pip_kwargs(config_dir):                                                   # :95-104
    kwargs = {"constraints": os.path.join(os.path.dirname(__file__), CONSTRAINT_FILE), ...}
```

Every integration requirement is resolved **under HA's central constraints file**, by `uv`, which
uses PubGrub resolution and will not pick a different version. Conflict → non-zero exit →
`install_package()` returns `False` → `RequirementsNotFound` → setup fails. No silent downgrade.

**Does HA ship pydantic?** **Yes: `pydantic==2.13.4`**, verified by fetching
`homeassistant/package_constraints.txt` directly. The file's own comment reads *"ensure pydantic
version does not float since it might have breaking changes."* It is **not** in
`homeassistant/requirements.txt` — it is purely transitive, pulled in by several integrations'
client libraries. HA is **pydantic v2 only**; the v1 mypy shim was removed 2026-01-30
(core PR #161901). The historical v1/v2 conflict problem is resolved and has been for ~18 months.

**Is a pydantic-based client library acceptable inside HA? Yes — and this is proven by a shipped
core integration.** `zwave_js`'s client library is the closest possible precedent:

```
zwave-js-server-python==0.73.0   requires_dist: ['aiohttp>3', 'pydantic>=2.0.0']
```

A widely-deployed, first-party HA integration installs a **pydantic-based, aiohttp-based WebSocket
client library** inside HA. Others doing the same: `notion`, `unifiprotect`, `mcp_server`,
`amberelectric`.

**What voluptuous actually requires.** Voluptuous is a **boundary** requirement, not a house style.
It is mandatory at exactly four places: YAML config schemas (and only for integrations that define
`setup`/`async_setup` at all — a config-entry-only integration is exempt), service-call schemas,
WebSocket command schemas, and config-flow `data_schema`. None of hassfest's ~32 plugins inspects
what schema library an integration uses internally. **Your wire models are unconstrained.**

**The one hard rule.** Express pydantic as a **range**, never a pin. Real failure, HA issue #173019
(2026-06-04):

```
Unable to install package smartbox>=2.5.1,<2.6.0: × No solution found ...
╰─▶ Because smartbox==2.5.1 depends on pydantic==2.13.2 and pydantic==2.13.4, we can conclude that
    smartbox==2.5.1 cannot be used.
```

An exact pin **two patch versions** off HA's was a hard install failure. HA's own
`hassfest/requirements.py` has a `PACKAGE_CHECK_VERSION_RANGE` list — including `pydantic`,
`aiohttp`, `yarl`, `zeroconf` — that flags over-tight constraints, but it is enforced for core
integrations only, so a custom integration gets no warning and just breaks at install time.

Other dependency notes for a would-be shared client:

- `aiohttp==3.14.3` is already in HA core requirements, and hassette requires `aiohttp>=3.14.3`
  (`pyproject.toml:36`). Compatible today; an exact-match coincidence worth not relying on.
- `httpx==0.28.1` is in HA core, but hassette's CLI uses **`httpx2`** (`pyproject.toml:39`) — a
  different distribution. Shipping it into HA is a genuinely new install, and HA docs advise custom
  integrations to avoid duplicating packages core already provides.
- `whenever` (`pyproject.toml:64`) is a Rust-extension package. HA containers are Alpine/musl.
  **Unverified** whether musl wheels exist for all HA-supported architectures; a client library
  should avoid it regardless.

---

## 5. Consequences for the packaging question

The premise under test: *"Under T3, potentially one client package serving both the CLI and the
integration."* I checked whether that survives §4's findings. **It survives the dependency test and
fails the reasoning test.**

### 5.1 Does HA force a stdlib-only client anyway?

**No.** §4.4 is unambiguous: `zwave-js-server-python` requires `pydantic>=2.0.0` and `aiohttp>3` and
ships inside a core integration. So T3's packaging advantage does *not* evaporate on dependency
grounds — a pydantic + aiohttp client is installable inside HA today.

**But this cuts against the ADR's premise, not for T3.** D4 says
(`design/research/2026-07-07-companion-integration-architecture/research.md:31`, `:178-180`):

> **Constraints:** pure Python, zero runtime dependencies, Python ≥3.11. No pydantic — HA pins its
> own pydantic and custom integrations must not import a conflicting one.

The premise is half-right and the conclusion does not follow. HA does pin pydantic (`==2.13.4`), and
a *conflicting* pin is fatal (#173019). But a client declaring `pydantic>=2,<3` resolves cleanly and
is exactly what a shipped core integration does. **D4's stdlib-only constraint is not required by
HA. It should be revised regardless of which transport wins.**

### 5.2 Does the repo count actually differ?

**No — and this is verifiable in-tree.** This repo already ships a second distribution: `codegen/`
has its own `pyproject.toml` (`name = "hassette-codegen"`, setuptools backend, its own `uv.lock`),
wired via `[tool.uv.sources] hassette-codegen = { path = "codegen", editable = true }`
(`pyproject.toml:118-119`). The multi-distribution-from-one-repo pattern is established here.

So under **T1**, `hassette-protocol` can live at `protocol/` in this repo rather than in its own
repo — collapsing the "three-repo coordination" risk (`research.md:243-244`) to two without changing
the transport at all. Under **T3**, a shared client would live the same way. The repo count is a
build-configuration choice, not a transport consequence. `prereq-03`'s "its own repo, so releases
version independently" is a preference, and a defensible one (independent versioning genuinely helps
when two consumers pin), but it is not forced.

### 5.3 Is the thin-CLI-package goal even coupled to the transport?

**No. This is the load-bearing finding of §5.**

The thin-CLI goal is: install `hassette` to administer a remote instance without fastapi, uvicorn,
aiohttp, or the framework. The blocker is entirely internal to this repo and has nothing to do with
HA. Verified by import tracing: importing `hassette.cli` today pulls in `fastapi` (39 submodules),
`uvicorn` (18), `starlette` (22), and `aiohttp` (40), on **every** CLI invocation regardless of
subcommand. Two independent chains cause it:

- `src/hassette/cli/__init__.py:15` unconditionally imports `cmd_run` → `cli/commands/run.py:12`
  imports `hassette.server` → `hassette/__init__.py:15` imports `core.core.Hassette` → the whole
  resource graph including `WebApiService`.
- Separately, `cli/target.py:30` imports `TOKEN_FILENAME` from `hassette.web.auth`, which imports
  `starlette.datastructures`/`requests`/`websockets` (`web/auth.py:38-40`).

There is one flat dependency list and exactly one extra: `test` (`pyproject.toml:68-69`). No
`cli`/`web`/`core` split exists.

Fixing that means: move the shared constants out of `web/auth.py`, make `cmd_run` a lazy entry
point (or move the server import behind the subcommand), and split `[project.optional-dependencies]`.
**That work is byte-identical under T1 and T3.** The transport decision does not touch it.

### 5.4 Package tables

**Under T1:**

| Package | Deps | Consumers |
|---|---|---|
| `hassette-protocol` — constants, `TypedDict` shapes, coercion fns, JSON fixtures | Currently specced stdlib-only; **could use pydantic** per §5.1 | `hass-hassette`, `hassette` |
| `hassette-client` (new, orthogonal) — web-API client for the CLI | httpx2 + pydantic | CLI |

Two distributions — but both can ship from this repo (§5.2), and the second one is needed under T3
too.

**Under T3:**

| Package | Deps | Consumers |
|---|---|---|
| `hassette-client` — web-API client, including the entity-bridge surface | httpx2/aiohttp + pydantic | CLI, `hass-hassette` |

One distribution. Genuinely one fewer thing to version. Two costs the premise does not mention:

1. **It conflates two APIs.** Hassette's web API is an *operator/admin* surface: start/stop/reload
   apps, trigger jobs, read app **source** (`/api/apps/{key}/source`), read config, change log
   levels. The entity bridge is a *runtime data* surface. Merging them means the HA-side integration
   holds a credential granting full admin over hassette. Both processes already fully trust each
   other, so the marginal risk is small — but it makes every future web-API change a potential
   integration-compat event, and vice versa.
2. **The client would need to be careful about deps inside HA.** `httpx2` is not in HA core;
   `whenever` is a Rust extension on an Alpine/musl base (unverified wheel coverage). A client
   written for the CLI would want both. A client written for HA would want neither. That pressure
   pushes toward *two client profiles anyway* — or an aiohttp-based client that is worse for the CLI.

**Net: the packaging saving under T3 is one small distribution, not a repo, not a dependency
category. It is real but small, and it is partly offset by a surface-area conflation.**

---

## Feasibility Analysis

### What would need to change

**If T1 is reaffirmed** (the status quo — listed for comparison):

| Area | Files affected | Effort | Risk |
|---|---|---|---|
| `dispatch` subscription routing (prereq-02) | `core/websocket_service.py` + tests | Low | Touches the hottest path in the framework; `dispatch` is 11 lines today |
| `instance_id` (prereq-01) | config, core, CLI, web config view | Low | Slug validation, "pick once" doc obligation |
| `hassette-protocol` (prereq-03) | new distribution | Low | Revise D4's stdlib-only constraint (§5.1) |
| Entity registry service + `self.entities` (prereq-04) | new `core/entity_registry_service.py`, `entities/`, `app/app.py`, `core/core.py` | **High** | The bulk of the epic; transport-agnostic |
| Integration skeleton + platforms (prereq-05/06) | new `hass-hassette` repo | **High** | Transport-agnostic except `websocket.py` |

**If T3 is adopted**, the delta from the above:

| Area | Change | Effort | Risk |
|---|---|---|---|
| prereq-02 | **Deleted** — no subscription routing needed | −Low | — |
| prereq-01 | Likely optional — `entry_id` gives identity | −Low | Some `unique_id` design rework |
| prereq-03 | Reshaped into a client library | Neutral | Must use dependency **ranges** (§4.4) |
| prereq-04 | Client shim swaps; core service unchanged | Neutral | — |
| prereq-05 | `websocket.py` becomes a client, not command registrations; config flow gains 3 fields + `async_step_hassio` | Neutral | — |
| **NEW: hassette entity-bridge API** | Topic-scoped WS subscriptions in `web/routes/ws.py` + `runtime_query_service.broadcast`; new REST routes; entity-command ingress | **Medium** | `src/hassette/web/` is flagged high-churn (89 commits at 091's research time); broadcast currently **drops** on `QueueFull` — unacceptable for entity commands, needs real backpressure |
| **NEW: add-on discovery publish** | `discovery:` key + `run.sh` POST in `hassette-addon` | Low | Only benefits topology (a) |
| Docs | Reachability, TLS, and proxy-bypass guidance per topology | Medium | The (c) case has no clean answer |

Plus the design churn: a new ADR superseding 0004, ~1/3 of `research.md` (transport analysis,
lifecycle matrix, protocol design), and rewrites of prereq-01/02/03/05.

### What already supports this

- Nothing is implemented, so switching costs no code (verified — §Current state).
- Auth is shipped, shared between HTTP and WS through one `resolve_auth_outcome()`
  (`web/auth.py:673-732`), and already consumed by a non-browser client (`cli/target.py`).
- The FastAPI app has ten routers registered (`web/app.py:89-98`); an eleventh is trivial.
- The repo already ships a second distribution (`codegen/`), so extra packages need no extra repos.
- HA's side is well-trodden: `paperless_ngx` (platinum) for the config flow, `zwave_js` for the
  transport, HACS's own integration for custom WS commands.
- HACS's bar is far lower than `prereq-05` assumes — no quality scale, no hassfest, no pinning, no
  brands submission post-2026.3.

### What works against this

- **Hassette's WS server is not the reusable asset the premise assumes.** 113 lines, broadcast-only,
  two client→server message types, no correlation, no topics, `QueueFull` → drop
  (`runtime_query_service.py:409-438`).
- **`src/hassette/web/` is high-churn.** Adding a protocol surface there means rebase pressure and
  couples entity-bridge stability to dashboard work.
- **Topology (c) has a real, documented block** on Jessica's own deployment
  (`092-cli-remote-url/design.md:163`).
- **Two failure domains** is a permanent architectural cost, not a one-time build cost.
- **The strongest stated motivation for revisiting (packaging) does not depend on the transport**
  (§5.3).

---

## Options Evaluated

### Option A: Reaffirm T1, correct the record, and decouple the packaging work

Keep custom `hassette/*` WS commands over hassette's existing HA connection. Separately:

1. Revise **D4** — drop "no pydantic" as a *constraint*. HA pins `pydantic==2.13.4` and a
   `>=2,<3` range resolves cleanly (`zwave-js-server-python` precedent). Keep stdlib-only if it is
   wanted for other reasons (it is a genuinely nice property for a wire-contract package), but stop
   justifying it with a claim that is not true.
2. Consider moving `hassette-protocol` into this repo as a second distribution alongside `codegen/`,
   cutting the "three-repo coordination" risk to two.
3. File the **thin CLI client** as its own issue, unblocked by any of this: break the
   `cli/__init__.py` → `commands/run.py` → `hassette.server` chain, move `TOKEN_FILENAME` out of
   `web/auth.py`, and add `[project.optional-dependencies]` groups.
4. Amend the ADR's third rejection ground when a superseding record is next written: the cost is a
   **second failure domain**, not a second reconnect state machine.

**Pros**
- Zero user configuration in all four topologies — including (c), the one Jessica runs and the one
  where T3 has a documented, unsolved block.
- One failure domain. Entity availability and framework availability stay the same fact.
- Faster recovery bound (hassette's ≤60s vs HA's ≤600s).
- Liveness plumbing is free and verified working in production integrations.
- Nothing new lands in the high-churn `web/` layer.
- The packaging goal is achieved anyway, on its own schedule.

**Cons**
- Keeps the admin-token requirement — a real, documented friction (`research.md:234-235`).
- `prereq-02` (dispatch subscription routing) stays on the critical path.
- Two distributions rather than one, though both can ship from this repo.
- Leaves the add-on topology's zero-config discovery path unused, which is a genuinely elegant
  mechanism.

**Effort estimate**: Small (design edits only; the epic's estimate is unchanged).

**Dependencies**: none new.

### Option B: Switch to T3 — integration connects to hassette's web API

Add an entity-bridge surface to hassette's FastAPI/WS app; the integration is a WS client with a
URL + token + verify-SSL config flow, auto-populated via Supervisor discovery in the add-on case.

**Pros**
- Drops the admin-token requirement on hassette's HA token.
- One client library plausibly serves both the CLI and the integration.
- Reuses shipped auth and the CLI's target/credential-scoping model.
- Zero-config in the add-on topology via Supervisor discovery — genuinely as clean as T1 there.
- The integration side is small and well-precedented (~40 lines of connection lifecycle; HA owns
  backoff).

**Cons**
- **Two independent failure domains**, permanently. New reachable states like "hassette healthy,
  entities all unavailable."
- **Topology (c) is unsolved.** The one deployment we have hard evidence about currently 401s
  bearer tokens at the proxy, and fixing it means changing infrastructure outside this repo.
- Hassette's WS server needs real work: topic-scoped subscriptions, and the current
  `QueueFull` → **drop** behavior is disqualifying for entity commands.
- New surface lands in a high-churn directory.
- Conflates an operator/admin API with a runtime data API behind one credential.
- Recovery bound grows to 10 minutes after a longer hassette outage.
- Requires inbound network exposure of hassette from HA — a decision that does not exist today.

**Effort estimate**: Medium design + Medium extra implementation vs Option A. The epic's dominant
cost (prereq-04, prereq-06) is unchanged either way.

**Dependencies**: none new beyond the client library's own.

### Option C (do less): Reaffirm T1 and change nothing but the two factual corrections

Fix D4's pydantic claim and the ground-3 wording. Do not move `hassette-protocol` into this repo, do
not file the CLI packaging issue yet. Revisit after `prereq-04` lands, when the entity protocol is
concrete rather than sketched.

**Pros**
- Smallest possible diff to a decision that, on this evidence, was correct.
- Avoids committing to a packaging shape before the protocol exists.

**Cons**
- Leaves a known-false constraint in the design record longer than necessary.
- The CLI packaging goal is real and currently untracked (no matching open issue — verified against
  the full open-issue list).

**Effort estimate**: Trivial.

---

## Concerns

### Technical risks

- **`runtime_query_service.broadcast()` drops on `QueueFull`** (`:409-438`, maxsize 256). Fine for
  dashboard telemetry, disqualifying for entity commands under T3. Any T3 path must add real
  backpressure or a separate delivery channel — this is not a detail.
- **Two-failure-domain states are hard to debug and hard to surface.** The web UI has no place to
  say "entities are unavailable in HA but hassette is fine." T1 avoids inventing that vocabulary.
- **Pinned dependencies inside HA are a live failure mode** (#173019: an exact pin two patch
  versions off HA's `pydantic==2.13.4` was a hard install failure). This applies to whatever
  package ships into HA, under either transport.
- **`whenever` is a Rust extension and HA runs Alpine/musl.** Unverified wheel coverage across HA's
  architectures. Any HA-side package must avoid it.

### Complexity risks

- Under T3, hassette's web layer acquires a second consumer with different semantics from the
  dashboard (must-deliver vs best-effort, per-topic vs firehose). That is a genuine second concept
  in a module that currently has one.
- Under T3, "which side is the client" inverts relative to how the protocol reads: hassette wants to
  *push* registrations but is the server. Workable, mildly confusing.

### Maintenance risks

- **Under T3**, every web-API change becomes a potential integration-compatibility event, because
  both ride one client and one token.
- **Under T1**, `dispatch` gains a routing table on the framework's hottest path. Small, but it is
  the path every HA event traverses.
- Either way, the protocol contract spans two consumers and needs contract tests. That obligation is
  identical.

---

## Open Questions

- [ ] Does topology (c) have an acceptable answer at all under T3? The concrete evidence
  (`092-cli-remote-url/design.md:163`) says reaching Jessica's own instance needs a proxy change.
  If the answer is "document the proxy bypass," is that acceptable as an *install prerequisite* for
  the integration, when T1 needs nothing?
- [ ] Is the admin-token requirement (T1's cost) actually biting anyone? The original brief assumed
  "likely already true for most users" without evidence. Worth a quick check of how hassette's docs
  currently describe token creation, since it is the one real capability T3 buys.
- [ ] Does `whenever` publish musl wheels for `aarch64` and `x86_64`? **Not verified** — I did not
  check PyPI wheel tags. Matters only if a hassette-derived package ever ships into HA.
- [ ] Can `uv_build` publish a second distribution from a subdirectory of this repo as cleanly as
  `codegen/` does with setuptools? `codegen/` proves the *pattern*; it uses a different backend.
  **Not verified.**
- [ ] Does HACS's `hacs/action` still enforce a `brands` check after HA 2026.3 allowed local
  `brand/` directories? The developer-docs side is unambiguous; the HACS-action side is
  **unconfirmed**.
- [ ] Is Supervisor's ingress `172.30.32.2`-only restriction network-enforced or convention?
  Docs frame it as add-on-author guidance ("you should deny"). **Could not verify** whether
  Supervisor firewalls it. Affects whether an add-on could serve ingress *and* a direct integration
  connection on the same port.

---

## Recommendation

**Reaffirm T1. Take Option A.**

Being direct, as asked: **this revisit did not overturn the decision, and on the transport question
specifically it was close to a waste of time.** Two of the three rejection grounds decayed exactly
as the premise supposed — the pairing secret is now trivial, and reachability is solved for the
add-on topology. But the third ground, restated correctly, is decisive on its own, and the decisive
detail is one the premise got backwards: *hassette's existing WebSocket server is not a reusable
command channel.* It is 113 lines of broadcast fan-out with two client→server message types, no
request correlation, no topics, and a `QueueFull` → drop policy. Adopting T3 does not reuse a second
reconnect state machine; it requires building a protocol surface that does not exist, in the
repo's highest-churn directory, to buy a permanent second failure domain.

Weighing the rest:

- **Capability parity holds in T1's favor, with one correction.** T3 does have a capability T1
  lacks — it drops the admin-token requirement — and the ADR's "no capability the chosen design
  lacks" claim should be narrowed to acknowledge it. That is one narrow item against T1's
  zero-config-everywhere, one-failure-domain, faster-recovery set.
- **The liveness argument is right but oversold.** T3 with a persistent integration→hassette socket
  gets an equally good disconnect signal — `zwave_js` proves it. T1's advantage is that the signal
  is *free* (HA's `connection.async_handle_close`, verified at `connection.py:256-270`) and that
  there is only one connection to lose. Keep the argument; fix the justification.
- **Topology decides it.** T3 is free in the add-on shape, cheap on a LAN, and genuinely expensive
  for a remote instance behind forward auth — which is the shape Jessica actually runs, and where
  spec 092's research already documented a concrete block. T1 needs nothing, anywhere.
- **The packaging motivation does not survive as an argument for T3.** It was the strongest new
  input and it dissolves under inspection: the thin-CLI blocker is entirely internal to this repo
  (`cli/__init__.py:15` → `commands/run.py:12` → `hassette.server`, plus `cli/target.py:30` →
  `web/auth.py`), the repo already ships a second distribution (`codegen/`), and HA's constraints
  do not force stdlib-only. T3's actual packaging saving is one small distribution, partly offset by
  merging an operator/admin API with a runtime data API behind one credential.

The revisit was **not** entirely wasted, though — it produced two corrections worth banking, both
independent of the transport:

1. **D4's stdlib-only rationale is factually wrong.** HA pins `pydantic==2.13.4` but installs
   integration requirements under that constraint, and `zwave-js-server-python==0.73.0` —
   `pydantic>=2.0.0`, `aiohttp>3` — ships inside a first-party core integration. Voluptuous is a
   boundary requirement at four places, not a house style. Keep stdlib-only if it is wanted on its
   merits; stop attributing it to an HA constraint that does not exist. The rule that *does* matter
   is: express shared deps as **ranges**, never pins (#173019).
2. **`prereq-05`'s CI scope is heavier than HACS requires.** The quality scale does not apply to
   custom integrations, HACS does not run hassfest, `==` pinning is unenforced, and brands-repo
   submission stopped being required in HA 2026.3. Bronze/Silver rules remain a good target; none of
   it is a gate.

**What would have to be true for this recommendation to be wrong:**

- If the HA add-on (#71) became the *only* topology that mattered — Supervisor discovery makes T3
  zero-config there, and the failure-domain argument weakens when both processes are supervised on
  one host by the same watchdog.
- If the admin-token requirement turned out to block real users, rather than being the "likely
  already true" assumption the original brief made.
- If the entity protocol turned out to need request/response semantics rich enough that HA's
  `websocket_api` command surface became the constraint rather than the gift.
- If hassette's WS server independently grew topic-scoped subscriptions and real backpressure for
  dashboard reasons, making the T3 delta genuinely small.

None of those is true today.

### Suggested next steps

1. **Record the reaffirmation** — a short superseding note or an amendment when ADR-0004 is next
   touched, correcting ground 3 to "a second failure domain" and narrowing "no capability the
   chosen design lacks" to acknowledge the admin-token difference. *(Not done here by instruction.)*
2. **Fix D4 in `design/research/2026-07-07-companion-integration-architecture/research.md`**
   (lines 31, 178-179) — replace the "HA pins its own pydantic" rationale with the verified facts,
   and state the range-not-pin rule. Do this before `prereq-03` starts.
3. **File the thin-CLI-client issue** (`type:enhancement`, `area:cli`, `size:medium`). No matching
   open issue exists. Scope: break the `cli/__init__.py` → `hassette.server` import chain, move
   `TOKEN_FILENAME` out of `web/auth.py`, add `[project.optional-dependencies]`. Explicitly note it
   is independent of the transport decision.
4. **Trim `prereq-05`'s CI scope** to what HACS actually requires, keeping Bronze/Silver rules as
   targets rather than gates.
5. **Decide `hassette-protocol`'s home** — `protocol/` in this repo (cheaper coordination, follows
   `codegen/`) vs its own repo (independent versioning, as specced). Either is defensible; make it
   an explicit choice rather than an inherited one.
6. **If the add-on ships first and zero-config install becomes the priority**, revisit *only that
   topology* — but note that a second transport for one deployment shape doubles the protocol
   surface, and T1 already works there unchanged (ADR-0005 says so explicitly at `:64-66`).

---

## Sources

**Home Assistant core** (all `dev` branch, fetched 2026-08-07):

- `homeassistant/components/websocket_api/connection.py` — `subscriptions` dict (`:81`),
  `async_handle_close` (`:256-270`) — https://github.com/home-assistant/core/blob/dev/homeassistant/components/websocket_api/connection.py
- `homeassistant/components/websocket_api/__init__.py` — `async_register_command` (`:48`) — https://github.com/home-assistant/core/blob/dev/homeassistant/components/websocket_api/__init__.py
- `homeassistant/components/websocket_api/decorators.py` — `require_admin` (`:54`),
  `websocket_command` (`:131`) — https://github.com/home-assistant/core/blob/dev/homeassistant/components/websocket_api/decorators.py
- `homeassistant/config_entries.py` — `SETUP_RETRY_MAX_WAIT = 600` (`:141`), backoff (`:843`) — https://github.com/home-assistant/core/blob/dev/homeassistant/config_entries.py
- `homeassistant/requirements.py` — `CONSTRAINT_FILE` (`:25`), `pip_kwargs` (`:95-104`) — https://github.com/home-assistant/core/blob/dev/homeassistant/requirements.py
- `homeassistant/package_constraints.txt` — `pydantic==2.13.4`, `aiohttp==3.14.3`, `httpx==0.28.1`,
  `voluptuous==0.15.2` — https://raw.githubusercontent.com/home-assistant/core/dev/homeassistant/package_constraints.txt
- `homeassistant/requirements.txt` — pydantic absent; aiohttp/httpx/yarl present — https://raw.githubusercontent.com/home-assistant/core/dev/requirements.txt
- `homeassistant/components/hassio/discovery.py` — `async_process_new` → `discovery_flow.async_create_flow(hass, data.service, ...)` — https://github.com/home-assistant/core/blob/dev/homeassistant/components/hassio/discovery.py
- `homeassistant/components/zwave_js/config_flow.py` — `get_manual_schema` (`:135-138`),
  `validate_input` (`:147-157`), discovery URL build (`:457`) — https://github.com/home-assistant/core/blob/dev/homeassistant/components/zwave_js/config_flow.py
- `homeassistant/components/zwave_js/__init__.py` — `client_listen` reload-on-close (`:1117-1153`) — https://github.com/home-assistant/core/blob/dev/homeassistant/components/zwave_js/__init__.py
- `homeassistant/components/zwave_js/manifest.json` — `zwave-js-server-python==0.73.0` — https://github.com/home-assistant/core/blob/dev/homeassistant/components/zwave_js/manifest.json
- `homeassistant/components/paperless_ngx/config_flow.py` + `manifest.json` (`quality_scale: platinum`) — https://github.com/home-assistant/core/blob/dev/homeassistant/components/paperless_ngx/config_flow.py
- `homeassistant/components/mealie/config_flow.py` — `CONF_HOST`/`CONF_API_TOKEN`/`CONF_VERIFY_SSL` — https://github.com/home-assistant/core/blob/dev/homeassistant/components/mealie/config_flow.py
- `homeassistant/components/music_assistant/{config_flow,__init__}.py` + `manifest.json` — https://github.com/home-assistant/core/blob/dev/homeassistant/components/music_assistant/config_flow.py
- `homeassistant/const.py` — `CONF_VERIFY_SSL` (`:257`) — https://github.com/home-assistant/core/blob/dev/homeassistant/const.py
- `script/hassfest/requirements.py` — `==` pinning gated on `integration.core`; `PACKAGE_CHECK_VERSION_RANGE` — https://github.com/home-assistant/core/blob/dev/script/hassfest/requirements.py

**Home Assistant Supervisor / add-ons:**

- `supervisor/api/discovery.py` — `set_discovery`, access check against the add-on's own `discovery:` list — https://github.com/home-assistant/supervisor/blob/main/supervisor/api/discovery.py
- App communication (internal `hassio` network, `{REPO}_{SLUG}` hostnames) — https://developers.home-assistant.io/docs/apps/communication/
- App presentation / ingress (`172.30.32.2`, `ingress_port`) — https://developers.home-assistant.io/docs/apps/presentation
- Supervisor API endpoints (`/discovery`, `/addons/<addon>/info`) — https://developers.home-assistant.io/docs/api/supervisor/endpoints/
- `home-assistant/addons` — `zwave_js/config.yaml` (`discovery: [zwave_js]`), `mosquitto/config.yaml` (`discovery: [mqtt]`) — https://github.com/home-assistant/addons/blob/master/zwave_js/config.yaml

**Home Assistant developer docs:**

- Integration setup failures / `ConfigEntryNotReady` — https://developers.home-assistant.io/docs/integration_setup_failures/
- Integration quality scale (does not apply to custom integrations) — https://developers.home-assistant.io/docs/core/integration-quality-scale/
- Fetching data (coordinator optional for push) — https://developers.home-assistant.io/docs/integration_fetching_data/
- Integration manifest / `requirements` — https://developers.home-assistant.io/docs/creating_integration_manifest/#requirements
- Extending the WebSocket API — https://developers.home-assistant.io/docs/frontend/extending/websocket-api/
- Brand images (local `brand/` dir from HA 2026.3) — https://developers.home-assistant.io/docs/core/integration/brand_images
- Config flow (`hassio` discovery step) — https://developers.home-assistant.io/docs/core/integration/config_flow/

**HACS:**

- Publishing an integration (layout, `hacs.json`, manifest keys, releases optional) — https://www.hacs.xyz/docs/publish/integration/
- HACS action checks — https://www.hacs.xyz/docs/publish/action/
- `hacs/integration` — custom integration registering WS commands with `connection.subscriptions` — https://github.com/hacs/integration/blob/main/custom_components/hacs/websocket/__init__.py

**PyPI:**

- `zwave-js-server-python` 0.73.0 — `requires_dist: ['aiohttp>3', 'pydantic>=2.0.0']` — https://pypi.org/pypi/zwave-js-server-python/json
- `music-assistant-client` 1.4.3 — `requires_dist: ['aiohttp>=3.8.6', 'music_assistant_models==1.1.152', 'orjson>=3.9']` — https://pypi.org/pypi/music-assistant-client/json

**Other:**

- `hass-node-red` — `async_register_command` (`:98-107`), `connection.subscriptions[msg_id]`
  (`:331`, `:413`) — https://github.com/zachowj/hass-node-red/blob/main/custom_components/nodered/websocket.py
- HA core issue #173019 — pydantic exact-pin install failure — https://github.com/home-assistant/core/issues/173019
- HA core PR #161901 — pydantic v1 mypy plugin removed (2026-01-30) — https://github.com/home-assistant/core/pull/161901
- Docker Compose networking (service-name DNS; `network_mode: host` caveat) — https://docs.docker.com/compose/how-tos/networking/
- HA container install uses `--network=host` — https://www.home-assistant.io/installation/linux
</content>
</invoke>
