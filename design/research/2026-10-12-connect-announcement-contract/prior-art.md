---
topic: "Connected/disconnected event contract when the connection dies during the connect announcement"
date: 2026-10-12
status: Draft
---

# Prior Art: Connect-Announcement Contract

## The Problem

A long-lived client announces "connected" in several steps: internal observers (resync), then public events. The connection can die partway through. The client then has to decide what its connected/disconnected events promise. Pairing means no disconnected without a prior connected. Freshness means never announcing a connection that is already dead. It also has to decide what happens to connect-time handlers still running when the drop lands.

The trigger was a Codex review finding on PR #2743. `WebsocketService.mark_connected` awaits `connected_observers.notify()`, which includes StateProxy's initial sync. It then emits `websocket_connected` and any held `homeassistant_started` without rechecking the recv task. Two earlier ship-time challenge findings (12 and 13 in `design/specs/131-ha-restart-reconnect/`) patched other windows in the same sequence. That raised the question of whether the sequence needs a different contract rather than another recheck.

## How We Do It Today

`mark_connected` (`src/hassette/core/websocket_service.py`) rechecks `recv_task.done()` at entry and after `report_connection_status`. It then sets `_connected_signal_active` and awaits the connected observers before emitting the bus events. `_handle_recv_task_done` invalidates the generation and connection state the moment the recv task dies. `run_connection` awaits `mark_connected` and then the recv task in the same coroutine, so `handle_connection_failure` runs after the announcement finishes. It notifies the disconnected observers and sends `websocket_disconnected`, gated on `_connected_signal_active`. State-change events carry a generation stamp.

## Patterns Found

### Pattern 1: Serialization gives ordering

**Used by**: paho-mqtt (network-loop thread), AppDaemon (one coroutine), Phoenix JS, socket.io-client, home-assistant-js-websocket (synchronous listeners).
**How it works**: The connect callback and the close handling run on the same thread or coroutine, so the close is processed only after the connect callback returns. "Connected, then disconnected" ordering comes for free. Async handlers break this unless the sequential loop awaits them, which AppDaemon does.
**Strengths**: Exact ordering with no flags.
**Weaknesses**: No freshness. Connected can be announced for a dead connection and followed immediately by disconnected.
**Example**: https://github.com/eclipse/paho.mqtt.python/blob/master/src/paho/mqtt/client.py

### Pattern 2: Flag-guarded, idempotent disconnect

**Used by**: HA core MQTT (`if not self.connected: return`), AppDaemon (`notify_plugin_stopped` only `if self.is_ready`), nats.py (early return if closed or reconnecting).
**How it works**: The disconnect path checks whether connected was announced and returns if not. That guarantees no disconnected without connected and dedupes close storms.
**Strengths**: Simple and robust.
**Weaknesses**: Only guards one direction, and the flag can drift from the event it stands for if they are set in different places.
**Example**: https://github.com/home-assistant/core/blob/dev/homeassistant/components/mqtt/client.py

### Pattern 3: Cancel in-flight connect-time work on drop

**Used by**: AppDaemon (`finally` cancels maintenance tasks and result futures), nats.py (a new reconnect task cancels the old one, including a running `reconnected_cb`; incidental, inferred from code).
**How it works**: The connection owns its connect-time work as tasks, and the drop cancels them before disconnected is delivered.
**Strengths**: No handler keeps working against a dead connection.
**Weaknesses**: Handlers must be cancel-safe, and cancellation can leave setup half done. Only two libraries do it, and nats.py's behavior looks accidental.
**Example**: https://github.com/AppDaemon/appdaemon/blob/dev/appdaemon/plugins/hass/hassplugin.py

### Pattern 4: Advisory events, with state as the source of truth

**Used by**: gRPC (level-triggered state, explicit staleness contract), SignalR C# (fire-and-forget handlers), socket.io-client.
**How it works**: Events say that something changed, and consumers re-read state to learn the current answer. gRPC: "state changes can be rapid and race with any such notification ... the notification should just inform the user that some state change has happened, leaving it to the user to poll the channel for the current state."
**Strengths**: An honest contract that never blocks the connection on a slow handler.
**Weaknesses**: Every handler author has to deal with the race.
**Example**: https://github.com/grpc/grpc/blob/master/doc/connectivity-semantics-and-api.md

### Pattern 5: Generation token rejects stale events

**Used by**: Phoenix JS (`connectClock`, `stillUses(connection)`), proposed in TencentCloud/Octop#1534.
**How it works**: Callbacks capture a connection identity and ignore events from an older one.
**Strengths**: Stops a stale connection's callbacks from overwriting newer state.
**Weaknesses**: Gives neither pairing nor freshness on its own.
**Example**: https://github.com/phoenixframework/phoenix/blob/main/assets/js/phoenix/socket.js

## Anti-Patterns

- **Unconditional close notification**: SignalR JS fires `onclose` even when `start()` never completed, so consumers see closed without connected (https://github.com/aspnet/SignalR/blob/master/clients/ts/signalr/src/HubConnection.ts).
- **Disconnect handling bound inside an async connect path**: if the drop happens first, the handler never registers (https://github.com/socketio/socket.io/issues/3134).
- **Unserialized state check racing the close path**: https://github.com/pusher/pusher-websocket-java/pull/378.

## Relevance to Us

- **Freshness:** no surveyed client rechecks liveness before announcing connected. The norm is that connected may be followed immediately by disconnected. gRPC is the only one that documents this, and it does so explicitly.
- **Ordering:** we already have Pattern 1. `run_connection` awaits `mark_connected` and then the recv task in one coroutine, so `websocket_disconnected` always follows `websocket_connected` even when the socket died mid-announcement. AppDaemon, the closest HA-websocket analogue, has the same shape.
- **Pairing:** we already have Pattern 2 (`_connected_signal_active`, as in AppDaemon's `is_ready`). It only becomes unpaired if code raises out of `mark_connected` *after* the flag is set but *before* the bus event goes out. Codex's proposed recheck after `notify()` would create exactly that case. A bus-send failure in `send_connection_established_event` already does, though that is rare and logged.
- **Generation stamp:** we already have Pattern 5 on state-change events.
- **Cancelling handlers (Pattern 3):** only AppDaemon and nats.py do it, and it would require StateProxy's sync to be cancel-safe. There's no evidence we need it.

## Recommendation

**Adopt Pattern 4's contract on top of the Pattern 1 and 2 machinery we already have.** `websocket_connected` means "a connection was established and announced", not "it is still up". Apps get a paired `websocket_disconnected` right after it if the connection already dropped, and `is_connected`/the generation is the source of truth.

- **No recheck after `notify()`:** don't add one. No surveyed client does, and adding a raise there is the only thing that would break pairing.
- **Pin the contract with a test:** socket dies during a slow observer → the bus gets connected, then disconnected, in that order.
- **Document the contract:** put it where the events are documented.
- **Split the flag:** keep `_connected_signal_active` from going true before the bus event has actually been sent. That means splitting the observer flag from the bus flag. Review later found a realistic path that makes this necessary: shutdown landing while a connected observer runs, e.g. Ctrl-C during StateProxy's initial sync, would otherwise emit `websocket_disconnected` with no `websocket_connected`. PR #2743 adopted the split (`_observers_announced` / `_bus_announced`).

**Coverage:** good for MQTT, NATS, SignalR, socket.io, Phoenix, gRPC and both HA websocket clients. aiomqtt, websockets, librdkafka, aio-pika and kombu were not read. No mainstream issue was found that reports literally "disconnected without connected".

## Sources

URLs were not live-verified.

### Reference implementations
- https://github.com/home-assistant/home-assistant-js-websocket/blob/master/lib/connection.ts — `ready` fires last in `_setSocket`; no recheck
- https://github.com/AppDaemon/appdaemon/blob/dev/appdaemon/plugins/hass/hassplugin.py — `is_ready`-guarded stopped notification; `finally` cancels connect-time work
- https://github.com/eclipse/paho.mqtt.python/blob/master/src/paho/mqtt/client.py — single-thread serialization; `on_disconnect` without a CONNACK check
- https://github.com/home-assistant/core/blob/dev/homeassistant/components/mqtt/client.py — flag-guarded, re-entrant disconnect
- https://github.com/nats-io/nats.py/blob/main/nats/src/nats/aio/client.py — status machine; reconnect-task replacement cancels the callback
- https://github.com/phoenixframework/phoenix/blob/main/assets/js/phoenix/socket.js — connection identity, cleanup before close callbacks
- https://github.com/socketio/socket.io/blob/main/packages/socket.io-client/lib/socket.ts — connect/disconnect with no recheck
- https://github.com/dotnet/aspnetcore/blob/main/src/SignalR/clients/csharp/Client.Core/src/HubConnection.cs — fire-and-forget Reconnected/Closed
- https://github.com/aspnet/SignalR/blob/master/clients/ts/signalr/src/HubConnection.ts — unconditional `onclose`

### Issues
- https://github.com/socketio/socket.io/issues/3134 — disconnect missed when the drop precedes the middleware
- https://github.com/TencentCloud/Octop/issues/1534 — stale close callback overwrote newer state
- https://github.com/pusher/pusher-websocket-java/pull/378 — reconnect timer racing disconnect
- https://github.com/redis/redis-py/issues/3640 — PubSub reconnect during resubscribe

### Documentation & standards
- https://github.com/grpc/grpc/blob/master/doc/connectivity-semantics-and-api.md — notifications may be stale; poll state
- https://www.erlang.org/doc/system/ref_man_processes.html — late monitor gets an immediate `noproc` DOWN
- https://learn.microsoft.com/aspnet/core/signalr/dotnet-client — Reconnected/Closed semantics
- https://docs.nats.io/using-nats/developer/connecting/events — NATS connection events
