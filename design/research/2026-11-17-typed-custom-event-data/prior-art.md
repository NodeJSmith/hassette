---
topic: "Typed data from custom Home Assistant events in automation frameworks"
date: 2026-11-17
status: Draft
---

# Prior Art: Typed Data From Custom HA Events

## The Problem

A custom Home Assistant event (here hass-hassette's `hassette_action`, data `{"name": str, "data": {...}}`) arrives as JSON. An app wants the inner data as a typed, validated object, wants to match on a field inside it (`name`), and wants to fire one in tests. Issue #4152.

## How We Do It Today

`D.EventData[T]` extracts `payload.data` with no converter, so the default `AnnotationConverter` falls through to `TYPE_REGISTRY` → `Model(dict)`, which fails for pydantic models and dataclasses and skips the handler. It works for `Bus.emit` because there the payload already is the object. Unknown HA event types become a generic `Event` on `hass.event.<type>` with the raw dict. Every typed HA event hassette knows about has a `Topic`, an event class in `HASS_EVENT_TYPES`, an `on_*` bus method with a field filter (e.g. `on_component_loaded(component=...)` → `P.ValueIs` on `payload.data.component`), and a `simulate_*` harness helper. hautomate works around the gap with a converter-slot alias using `TypeAdapter` (`hautomate/ha_messages.py`).

## Patterns Found
### Pattern 1: Generic typed wrapper over any event (type param + event-type string)
**Used by**: NetDaemon (`Events.Filter<T>("my_event")`, built-ins like `call_service` reuse it).
**How it works**: One generic conversion (JsonElement -> T via the serializer) is applied to any event. The user declares T; event type is a string argument. Built-in events are the same mechanism with a named wrapper (`HassServiceEventData<T>`), not bespoke converters. Matching on data fields is ordinary code on the typed `Data` (Rx `.Where`).
**Strengths**: no per-event code in the framework; works for custom events; one place for conversion rules.
**Weaknesses**: conversion errors surface late (lazy `Data` throws in the subscriber); missing fields silently default unless T marks them required; events lacking data are dropped silently.
**Example**: https://github.com/net-daemon/netdaemon/blob/main/src/HassModel/NetDaemon.HassModel/HaContextExtensions.cs
**Read**: HaContextExtensions.cs, Event.cs, AppScopedHaContextProviderTest.cs, IntegrationHaContextExtensions.cs (grep lines).

### Pattern 2: Raw dict + declarative equality/subset filter
**Used by**: Home Assistant core event trigger, AppDaemon (kwargs), Node-RED (isMatch JSON), pyscript (kwargs variant).
**How it works**: Subscribe by event type with an optional dict of expected field values; framework compares as subset/partial match; handler gets the raw mapping. HA core uses `items() >=` fast path and a schema for nested dicts; AppDaemon compares each kwarg to `data[key]`, allowing a callable predicate per field; Node-RED uses lodash `isMatch`.
**Strengths**: simple, no model needed, cheap.
**Weaknesses**: no validation or typing; AppDaemon's absent-key-passes behavior can fire the callback on the wrong events; AppDaemon filters collide with callback kwargs.
**Example**: https://github.com/AppDaemon/appdaemon/blob/dev/appdaemon/events.py
**Read**: AppDaemon events.py, HA core event.py, Node-RED EventsAllController.ts.

### Pattern 3: Expression-string predicate
**Used by**: pyscript `@event_trigger("evt", "arg1 == 20 and arg2 == 30")`.
**How it works**: second arg is parsed once at decoration, evaluated per event with data keys as locals. Errors (NameError for missing key) propagate as exceptions.
**Strengths**: expressive.
**Weaknesses**: stringly typed, errors at runtime; unusable for typed code.
**Example**: https://github.com/custom-components/pyscript/blob/master/docs/reference.rst
**Read**: reference.rst, trigger.py lines 327-343 and 546-556.

### Pattern 4: Test harness = push a raw event into the same stream
**Used by**: NetDaemon (`HaContextMock.EventsSubject.OnNext`), pyscript tests (`hass.bus.async_fire(type, data)`), appdaemontestframework (call callback directly; assert registration only).
**How it works**: no purpose-built "simulate custom event" sugar found in any of them; the harness exposes the raw event stream or the real HA bus.
**Strengths/Weaknesses**: trivial to implement; tests must hand-build the full event envelope (NetDaemon) or bypass the subscription path entirely (appdaemontestframework).
**Read**: as listed above.

## Anti-Patterns
- AppDaemon filter semantics: a filter kwarg whose key is missing in the event data lets the event through (events.py ~360-370). Missing data should not read as a match.
- NetDaemon lazy deserialize: bad data throws inside the user's subscriber at first `.Data` access, far from the subscription, with no structured log.

## Gaps
- AppDaemon: no GitHub issue found (one `gh search issues` attempt returned nothing useful) asking for typed event data; its documented behavior is simply a raw dict. Closest evidence is the `EventCallback` Protocol typing data as `dict[str, Any]`. Won't-fix issues: not found.
- NetDaemon: could not locate the published NetDaemon test package (NetDaemon.Extensions/TestHelpers) in the cloned repo; its event-simulation helper, if any, is [no source found]. Did not confirm what a failed `Deserialize<T>` logs (it is an unhandled JsonException in the observer chain; Rx routes it to OnError, not verified by test).
- nickw444/appdaemon-testing: only README read via search; source not inspected.
- Home Assistant core: no model-conversion layer exists for event data (only the trigger schema above); nothing to cite for typed access. Did not inspect HA core's test helpers beyond the pyscript use of `hass.bus.async_fire`.

## Relevance to Us

- Only NetDaemon types custom event data, and it does so with **one generic mechanism** (`Filter<T>(eventType)`, lazy deserialize) that its built-in typed events also sit on. That argues for fixing `D.EventData[Model]` generically (dict → model via `TypeAdapter`) rather than a one-event extractor, since a generic fix also serves every other custom HA event users fire.
- Field matching everywhere is a filter on the raw data (kwargs, subset dict, predicate). None of the peers offer a per-custom-event subscribe method; hassette's own convention, though, gives every HA event it types an `on_*` method with a field filter, so `on_hassette_action(name=...)` matches the house pattern rather than peers.
- Failure handling: peers mostly skip silently (HA core, Node-RED) or throw late (NetDaemon). hassette's existing behavior (skip the handler, log a `DependencyResolutionError` that names the converter error) is already louder than any peer; pydantic's `ValidationError` text names the field.
- Testing: peers push a raw event into the stream; none offer a named helper. hassette's harness already has `simulate_event` plus named `simulate_*` helpers per typed event, so a `simulate_hassette_action` follows the house pattern.

## Recommendation

Make the conversion generic (Pattern 1): validate a Mapping into a pydantic model / dataclass annotation in the conversion layer, so `D.EventData[Model]` works for any custom HA event. Then layer the hass-hassette specifics (topic, `on_hassette_action(name=...)`, an extractor for the inner `data`, `simulate_hassette_action`) as thin wrappers, mirroring how hassette already treats the HA events it knows. Peers don't carry the dedicated subscribe method or test helper, so those earn their place only via hassette's own convention, not ecosystem demand.

Gaps: NetDaemon's logging on a failed deserialize wasn't confirmed; no AppDaemon issue asking for typed events was found.

## Sources

### Reference implementations
- https://github.com/AppDaemon/appdaemon/blob/dev/appdaemon/events.py
- https://github.com/HelloThisIsFlo/Appdaemon-Test-Framework
- https://github.com/custom-components/pyscript/blob/master/docs/reference.rst
- https://github.com/home-assistant/core/blob/dev/homeassistant/components/homeassistant/triggers/event.py
- https://github.com/net-daemon/netdaemon/blob/main/src/HassModel/NetDaemon.HassModel.Integration/IntegrationHaContextExtensions.cs
- https://github.com/net-daemon/netdaemon/blob/main/src/HassModel/NetDaemon.HassModel.Tests/Internal/AppScopedHaContextProviderTest.cs
- https://github.com/net-daemon/netdaemon/blob/main/src/HassModel/NetDaemon.HassModel.Tests/TestHelpers/HassClient/HaContextMock.cs
- https://github.com/net-daemon/netdaemon/blob/main/src/HassModel/NetDaemon.HassModel/Event.cs
- https://github.com/net-daemon/netdaemon/blob/main/src/HassModel/NetDaemon.HassModel/HaContextExtensions.cs
- https://github.com/nickw444/appdaemon-testing
- https://github.com/zachowj/node-red-contrib-home-assistant-websocket
- https://github.com/zachowj/node-red-contrib-home-assistant-websocket/discussions/788
