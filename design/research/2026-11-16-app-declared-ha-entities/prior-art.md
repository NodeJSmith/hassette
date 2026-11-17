---
topic: "How external automation runtimes let user code declare Home Assistant entities they own"
date: 2026-11-16
status: Draft
---

# Prior Art: App-Declared Home Assistant Entities

## The Problem

An external automation runtime wants its user code to own real Home Assistant entities: buttons whose
presses run a handler, switches whose state the app controls, sensors the app publishes. Each one needs
a registry entry and stable unique_id, a push path for state, a path for commands back to the runtime,
and lifecycle answers: availability when the runtime is down, what a switch reads after a restart, and
how an entity is removed once the code stops declaring it. Getting these wrong produces the standing
issue classes peers carry: entities "unknown" after restart, switches "stuck unavailable" after a
disconnect, and orphans nobody sweeps.

## How We Do It Today

hassette has no app-declared entities (#3993). hass-hassette (v0.7) connects OUT to hassette's web API
with `hassette-client`: a `DataUpdateCoordinator` polls `/api/health` then `/api/apps` every 30 s, and
gives each app a device with framework entities (start/stop switch, reload button, status sensor) keyed
`{app_key}-{key}`. Commands go HA → hassette over HTTP (`client.action`), followed by a debounced
refresh so a toggled switch updates within about a second. Device removal and entity availability are
gated on `app_list_trusted` (good poll + bootstrap released). `hassette-client` has no WebSocket
support; hassette's `/ws` route streams UI events (`app_status_changed`, `apps_changed`, …) whose
compatibility is only freshness-checked (#2439). Separately, hassette holds its own WS into HA, and the
`hassette.send` action reaches apps as an HA event (`hassette_action`) over that connection. App users
today hand-create `input_button`/`input_boolean` helpers for hassette to listen to.

## Patterns Found

### Pattern 1: Runtime pushes declarations over HA's WebSocket to a companion integration (connection-scoped ownership)
**Used by**: hass-node-red + node-red-contrib-home-assistant-websocket
**How it works**: The runtime already holds a WS connection into HA and sends custom admin-only commands. `nodered/discovery` carries component type, `server_id` + `node_id`, config, state, device_info, `remove`. The integration creates a platform entity on first sight (keyed by `already_discovered` set) and updates it on later messages. The command is a `subscribe`-style WS message, so the HA entity keeps the `ActiveConnection` and message id. `button.press`/`switch.turn_on` send an `event_message` back down that subscription. When the connection closes, the subscription cleanup callback runs `handle_lost_connection`, which sets `_attr_available = False`. On reconnect the runtime re-registers everything (`Integration.#onHaIntegration` -> `register()`), which flips available back to True and rebinds the new connection.
State push is `nodered/entity` (`state`, `attributes`, `available`), no HA-side polling. Switch truth is the runtime: its on/off is persisted in Node-RED storage and sent at registration; a HA toggle goes to the runtime, which sets it and echoes `nodered/entity` state, so HA state only changes on the echo (confirmed). `unique_id` = `nodered-<server_id>-<node_id>` (node ids are Node-RED's random flow ids, so renaming is free but copy/paste of a flow makes new entities). No RestoreEntity anywhere in the component. Orphan removal: the runtime sends `remove: true` only when a node is deleted while connected (`onEntityConfigNodeClose(removed)`); the HA side drops the registry entry (mirrors MQTT). Nothing sweeps entities whose node was deleted while HA/Node-RED were disconnected, so such entries persist as unavailable until the user deletes them [inferred from the code; no sweep logic exists in `discovery.py`].
**Strengths**: One connection, no polling, push both directions, availability follows the link exactly, no broker dependency, command latency is one WS hop.
**Weaknesses**: Entities exist only while the runtime has registered them since HA start; "unknown after restart" and "stuck unavailable after disconnect" are standing issue classes (#358, #2015). The runtime must resend everything on every reconnect, and the integration has to detect the missing-resend case. No declarative orphan sweep.
**Example**: https://github.com/zachowj/hass-node-red/blob/main/custom_components/nodered/websocket.py (`websocket_discovery`), `entity.py` (`handle_lost_connection`, `handle_discovery_update`)
**Read**: hass-node-red @dd447fa `websocket.py`, `discovery.py`, `entity.py`, `switch.py`, `button.py`; contrib @561790c `Integration.ts`, `UnidirectionalEntityIntegration.ts`, `BidirectionalEntityIntegration.ts`, `State.ts`.

### Pattern 2: Integration connects OUT; device declares full entity list on connect and pushes state (ESPHome)
**Used by**: ESPHome native API (HA core)
**How it works**: HA is the client. On connect it calls `device_info_and_list_entities()`; the declared list is authoritative for that session. The platform diffs the new list against stored infos: new entries become entities, entries missing from the list are removed from the entity registry, renamed keys migrate `unique_id`. The list is persisted in a Store, so entities appear (unavailable) at HA startup before the device connects. Availability is `entry_data.available`, False on disconnect (deep-sleep devices excepted). States are pushed by the device on a subscription; HA does not poll. Commands (`switch_command`, `button_command`) go straight out over the same connection. Switch truth is the device; `assumed_state` is a device-declared flag, otherwise the switch changes only when the device pushes state. `unique_id` = MAC + entity key/object id.
**Strengths**: Declaration is a complete snapshot each connect, so orphan removal is a pure diff with no tombstone messages; works with the runtime down at HA start.
**Weaknesses**: Requires HA to know where the device is and to reconnect (config entry with host). That is the direction hass-hassette uses today (HA -> hassette). Needs a custom protocol (protobuf) or equivalent.
**Example**: https://github.com/home-assistant/core/blob/dev/homeassistant/components/esphome/entity.py (the `current_infos` diff near `async_remove_entities`), `entry_data.py` (`async_remove_entities`, `async_on_disconnect`)
**Read**: core @fb3bf83 `esphome/entry_data.py`, `entity.py`, `switch.py`; aioesphomeapi `model.py` `build_device_unique_id` (via `gh api`).

### Pattern 3: MQTT discovery with retained config, availability/LWT, and empty-payload removal
**Used by**: HA MQTT; NetDaemon `MqttEntityManager` (recommended by NetDaemon); Zigbee2MQTT and AppDaemon users (AppDaemon only via community advice)
**How it works**: The runtime talks to a broker, not to HA. Declaration = a retained JSON config at `<prefix>/<component>/<id>/config` with required `unique_id`, `state_topic`, `command_topic`, optional `availability_topic`. Because it is retained, entities survive HA and runtime restarts; HA re-reads it on startup. Availability: HA marks entities unavailable when the broker connection is down; with availability topics it follows them, typically `online` retained plus an LWT `offline` so a crashed runtime flips entities unavailable without cooperating. Removal: publish an empty retained payload; HA removes the entity and registry entry. If the user deletes the entity in HA, HA clears the retained topic itself. Switch semantics: with a `state_topic` the switch is confirmed (state changes only on the state message); without one it is optimistic and uses RestoreEntity. NetDaemon's wrapper exposes imperative `CreateAsync/SetStateAsync/SetAvailabilityAsync/RemoveAsync` and a command `IObservable<string>`. Availability is opt-in in NetDaemon, and `RemoveAsync` is not retained.
**Strengths**: Documented HA standard; no custom integration code; orphan removal and availability have first-class mechanics; entities survive either side restarting.
**Weaknesses**: Needs a broker; retained garbage accumulates if the runtime never publishes removals (nothing sweeps declarations that disappeared from user code unless the runtime tracks them itself); discovery-config drift (e.g. `object_id` -> `default_entity_id`, NetDaemon PR #1351) is the runtime's problem.
**Example**: https://netdaemon.xyz/docs/user/extensions/extensions_mqttentitymanager/
**Read**: core @fb3bf83 `mqtt/discovery.py`, `entity.py`, `switch.py`; netdaemon @4696609 `MqttEntityManager.cs`; docs page (opened).

### Pattern 4: Service-call entity CRUD with HA-side persistence (NetDaemon integration)
**Used by**: net-daemon/integration (deprecated in favor of Pattern 3)
**How it works**: The runtime calls `netdaemon.entity_create|update|remove` (`entity_id`, `state`, `attributes`, `icon`, `unit`, `options`) through its HA WS. The integration saves a dict in HA `.storage/netdaemon` and renders entities from it via a coordinator. `entity_create` reloads the whole config entry, so each create tears down all platforms. HA owns persistence, so entities and switch state survive restarts of both sides (state is whatever was last written). A switch `turn_on` writes the store and HA state with no round trip; the runtime is expected to observe the state change. Removal is explicit (`entity_remove`, which also removes the registry entry); nothing sweeps on declaration drop. No link-based availability. `unique_id` = `netdaemon_<entity name part>`. Buttons are not supported.
**Strengths**: Trivially simple transport (service calls only, no persistent subscription from the integration).
**Weaknesses**: Stale entities remain forever if the app stops declaring them; HA and runtime state can diverge (optimistic writes); reload-per-create; the project itself deprecated this API in favor of MQTT.
**Example**: https://github.com/net-daemon/integration/blob/main/custom_components/netdaemon/client.py
**Read**: integration @2781bf1 `__init__.py`, `client.py`, `entity.py`, `switch.py`, `const.py`, `services.yaml`; netdaemon @4696609 `IntegrationHaContextExtensions.cs`.

### Pattern 5: Accept the limitation: `set_state` ghost entities, no real entities
**Used by**: AppDaemon (`set_state`/`Entity.add` for HA namespace), pyscript (`state.set`, `pyscript.` domain only for `state.persist`)
**How it works**: The runtime writes into HA's state machine through the REST/WS `set_state` equivalent. The result has no registry entry, so no `unique_id`, no rename, no UI customization, no area, and it disappears on HA restart unless the runtime re-sets it. Nothing routes HA commands back, so there are no buttons or switches that call the runtime. AppDaemon's community answer: create only sensor/binary_sensor this way, use MQTT discovery for anything with an id. pyscript offers `state.persist(entity_id)` for `pyscript.*` only, via a RestoreState hack that its own source comments flag as undesirable.
**Strengths**: Zero HA-side code; works everywhere.
**Weaknesses**: Documented as rogue by contributors; collisions overwrite real entities; no command path; users keep asking for unique_id (HA community thread, pyscript #47).
**Example**: https://github.com/custom-components/pyscript/issues/47
**Read**: pyscript @11a8312 `docs/reference.rst`, `state.py` (`register_persist`, `persist`); community thread and issue #47 (opened). AppDaemon source not cloned; basis is its API reference + community thread.

## Anti-Patterns

- **Opt-in availability.** NetDaemon's MQTT availability topic exists only if the app sets payloads; the default entity never goes unavailable when the runtime dies. HA's `entity-unavailable` rule says the opposite. Source: NetDaemon docs page, HA quality scale rule.
- **State written by HA on the user's click without the runtime's confirmation** (NetDaemon integration switch). It diverges from the runtime whenever the runtime ignores or fails the command. MQTT/ESPHome/Node-RED only change on a pushed state, except MQTT's explicit optimistic mode (`assumed_state=True`).
- **Reload the whole config entry to add one entity** (`entity_create` -> `async_reload_entry`). Contradicts HA's `dynamic-devices` rule.
- **No unique_id** (AppDaemon/pyscript set_state). HA FAQ and registry docs: user can't manage the entity.
- **Unique IDs from mutable inputs.** HA docs forbid names, URLs, IP. Node-RED's `node_id` avoids this at the cost of flow-copy duplicates; NetDaemon's name-based id breaks on rename.
- **Orphan cleanup only on runtime-observed deletion** (Node-RED `removed` flag; NetDaemon explicit `entity_remove`). Deletions done while disconnected leave unavailable entities forever. ESPHome's diff-on-connect and MQTT's user-delete hook are the two sweeps that exist.
- **Reconnect without re-register** produces "stuck unavailable" switches (contrib #2015, #1724) and "unknown after restart" sensors (hass-node-red #358, #310).

## Emerging Trends

- NetDaemon moved from a bespoke integration to MQTT discovery; HA deprecations in discovery payloads (`object_id` -> `default_entity_id`, HA 2026.4) now propagate to every runtime that wraps MQTT.
- HA's quality scale now has explicit Gold rules for stale/dynamic devices; any new integration is expected to diff a full list rather than rely on tombstones.
- HA is deprecating device-link attachments for entities without a unique id/config entry (registry doc: warning now, stops working in HA 2027.8), which further penalizes non-registry entities.

## Gaps

- No maintainer-closed "won't fix" issue found for AppDaemon/pyscript real-entity support; limitation evidence is documentation and a contributor comment in pyscript #47 only. AppDaemon's repo was not cloned.
- NetDaemon's stated reason for deprecating the integration path was not found in code, release notes, or docs I read.
- Not read: Hubitat/Homebridge bridges, `remote_homeassistant`, hass-variables (not directly relevant). Zigbee2MQTT source not opened; the MQTT claims come from HA core and docs.
- Node-RED: unverified whether HA restart without Node-RED restart re-registers entities automatically. Code shows registration is triggered by `ClientEvent.Integration` Loaded, which suggests yes, but I did not trace the integration-loaded event on the HA side.
- Runtime behavior (not read, no test run): none of these claims were exercised against a live HA; all are from source and docs.

## Comparison table

| Project | who connects to whom | state push | command path | availability when runtime down | switch state after restart (source of truth) | orphan removal | unique_id scheme |
|---|---|---|---|---|---|---|---|
| hass-node-red | runtime -> HA WS (custom `nodered/*` admin commands) | `nodered/entity` WS message | HA entity sends `event_message` down the runtime's own WS subscription; runtime echoes state | unavailable when WS connection closes (subscription cleanup); stays so until runtime re-registers | runtime (Node-RED node storage `isEnabled`); no RestoreEntity; resent at register | `remove: true` only on node delete while connected; nothing else sweeps | `nodered-<server_id>-<node_id>` |
| NetDaemon integration (deprecated) | runtime -> HA WS service calls `netdaemon.entity_*` | service `entity_update` into HA `.storage/netdaemon` | none direct; HA writes state on toggle and runtime observes state_changed | none link-based; entity available if present in store | HA store (last written state, optimistic) | explicit `entity_remove` only | `netdaemon_<name>` |
| NetDaemon MqttEntityManager | runtime -> broker <- HA | retained state/attributes topics | MQTT command topic `.../set` -> `IObservable<string>`; app sets state | only if app opted into availability payloads (no LWT by default) | retained state topic (runtime/broker); HA optimistic only if no state topic | `RemoveAsync` (empty payload) | config topic path with `/`->`_`, overridable |
| ESPHome | HA -> device (native API) | device pushes subscribed state | direct `switch_command` / `button_command` on same connection | unavailable on disconnect (deep-sleep exception); entity list persisted so entities exist at HA start | device | diff of `list_entities` each connect -> `er.async_remove` | MAC + entity key/object id (v3) |
| HA MQTT discovery | runtime -> broker <- HA | retained state topic | command topic | HA broker-link + availability topics/LWT | state topic if present (confirmed); else optimistic + RestoreEntity | empty retained config; HA clears retained topic on UI delete | required `unique_id` in payload |
| AppDaemon / pyscript | runtime -> HA (REST/WS set_state) | state-machine write | none | none (ghost state stays until restart) | none (lost at restart; pyscript `state.persist` only for `pyscript.*`) | none | none |

## Relevance to Us

- **Our transport direction matches ESPHome, not Node-RED.** hass-hassette already connects out to
  hassette, as HA connects out to an ESPHome device. ESPHome's lifecycle (full list on every connect,
  diff-based orphan removal, entities persisted so they exist unavailable while the device is away,
  commands on the same link, the device as switch truth) maps onto what hass-hassette already does for
  app devices: `/api/apps` is a full list, removal is gated on a trusted list. The Node-RED shape
  (runtime pushes over HA's WS) is the ADR-0004 T1 direction the transport revisit moved away from;
  adopting it for entities would bring back a second transport.
- **The runtime is the switch's source of truth everywhere that isn't deprecated.** Node-RED, ESPHome
  and MQTT-with-state-topic change a switch only when the runtime reports the new state; only MQTT's
  explicit optimistic mode and NetDaemon's abandoned integration let HA write it. None of them use
  RestoreEntity when the runtime reports state. That makes "switch state survives a hassette restart"
  a hassette-side persistence question (hassette has a DB), not a RestoreEntity question.
- **Push latency is the one thing polling doesn't give.** Commands and confirmed switch state already
  work over HTTP + an immediate refresh. App-pushed sensor state is the case that needs a push channel;
  no peer polls for it. A push channel means WS support in `hassette-client`, which is exactly what
  #2439 guards.
- **Orphan removal by tombstone is the documented failure.** Node-RED and NetDaemon only remove what
  they saw deleted while connected. The diff against a trusted full list (ESPHome, HA's stale-devices
  rule) is what we already do for app devices.
- **Unique_id**: our `{app_key}-{key}` scheme already follows HA's "device id + entity key" rule, but
  framework keys (`switch`, `reload`, `status`) and user keys share the namespace, so app-declared keys
  need their own segment.

## Recommendation

Model app entities on ESPHome's lifecycle over the transport hass-hassette already has: hassette
exposes each app's declared entities as part of a full list the integration reads, the integration
diffs against it (removal gated on the existing trusted-list check), commands go back over HTTP like
app actions, and the app is the switch's source of truth (persisted on hassette's side if it must
survive a hassette restart). Treat the push channel for sensor state as the one new transport piece:
either accept poll latency for a first cut or add WS to `hassette-client`, with #2439 landing first.
Don't adopt the Node-RED or NetDaemon-integration shapes, and don't use RestoreEntity for switches the
app reports. MQTT discovery is the route NetDaemon took; it would skip hass-hassette entirely but needs
a broker, and NetDaemon's reason for the switch wasn't found.

Coverage: source for hass-node-red, NetDaemon, ESPHome and MQTT was read at the commits cited; AppDaemon
source and Zigbee2MQTT were not; nothing was run against a live HA.

## Sources

### Reference implementations
- https://github.com/zachowj/hass-node-red — `nodered/*` WS commands, connection-scoped entities
- https://github.com/zachowj/node-red-contrib-home-assistant-websocket — runtime side, switch truth in node storage
- https://github.com/net-daemon/integration — service-call entity CRUD (deprecated)
- https://github.com/net-daemon/netdaemon/blob/main/src/Extensions/NetDaemon.Extensions.MqttEntityManager/MqttEntityManager.cs — MQTT entity manager
- https://github.com/home-assistant/core/tree/dev/homeassistant/components/esphome — list-on-connect, diff removal
- https://github.com/home-assistant/core/tree/dev/homeassistant/components/mqtt — discovery, availability, optimistic switch
- https://github.com/home-assistant/core/blob/dev/homeassistant/helpers/restore_state.py — restore dump interval and expiry

### Issues & community
- https://github.com/zachowj/hass-node-red/issues/358 , /310 — unknown after restart
- https://github.com/zachowj/node-red-contrib-home-assistant-websocket/issues/2015 , /1724 , /1323 — stuck unavailable
- https://github.com/custom-components/pyscript/issues/47 — why set_state entities are "rogue"
- https://community.home-assistant.io/t/can-you-give-an-entity-created-by-set-state-in-appdaemon-an-unique-id/485513

### Documentation & standards
- https://netdaemon.xyz/docs/user/extensions/extensions_mqttentitymanager/
- https://www.home-assistant.io/integrations/mqtt/
- https://developers.home-assistant.io/docs/core/integration-quality-scale/rules/stale-devices
- https://developers.home-assistant.io/docs/core/integration-quality-scale/rules/dynamic-devices
- https://developers.home-assistant.io/docs/core/integration-quality-scale/rules/entity-unavailable
- https://www.home-assistant.io/faq/unique_id/
