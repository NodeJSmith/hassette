---
topic: "How HA automation frameworks represent an immediate/initial state-listener fire"
date: 2026-11-05
status: Draft
---

# Prior Art: Immediate-Fire Synthetic Events

## The Problem

A state listener with an "immediate" option fires once at registration with the entity's current state, and duration holds re-check state when the hold elapses. Frameworks have to hand the callback *something* for that fire. Hassette builds a fake `state_changed` event with a random uuid4 context id, origin `LOCAL`, and a topic shape real events never carry; the only synthetic marker is a flag on the internal command. Telemetry code holding only the event then records the fabricated context as if Home Assistant issued it (raised by the sketch-time challenge of `design/specs/147-execution-trigger-detail/design.md`).

## How We Do It Today

`make_synthetic_state_event` in `src/hassette/core/bus_service.py` builds `RawStateChangeEvent(topic="hass.event.state_changed.<entity_id>", old_state=None, new_state=<cached state>, origin="LOCAL", context=HassContext(id=uuid4(), ...))`. `InvokeHandler.is_synthetic` is the marker; its one reader, `build_execution_record`, nulls the context id and records origin `HASSETTE_SYNTHETIC`. The cached `HassStateDict` already carries the real `context` (`Required` in `src/hassette/events/hass/raw.py`), unused here.

## Patterns Found

### Pattern 1: Synthetic event reuses the real current State object (no fabricated context)
**Used by**: NetDaemon (WithCurrent), Node-RED HA websocket (outputInitially), AppDaemon (new_state = current stored state), HA core (for: hold)
**How it works**: The initial or recheck fire is built from the stored State, which already holds the `context` of the change that last set it. Nothing generates a new id.
**Strengths**: No wrong provenance for telemetry; zero new machinery. Matches your option 3.
**Weaknesses**: The context is that of a past change, not the fire itself, so a recorder can't tell "this ran now" from "this context belongs to the change that ran earlier" unless it also has a marker.
**Example**: NetDaemon `Prepend(new StateChange(entity, null, entity.EntityState))`; Node-RED `old_state: entities[id], new_state: entities[id]`.
**Read**: netdaemon EntityExtensions.cs L126-130; nrhaws EventsStateController.ts L228-245.

### Pattern 2: Hold/duration fire re-uses the original triggering event's context
**Used by**: HA core (`for:`), pyscript (`state_hold`)
**How it works**: When the hold starts, the original event (or its func_args) is captured. When the timer elapses, the action runs with `event.context` (HA core) or the saved func_args (pyscript) after a recheck predicate passes.
**Strengths**: Authoritative: trigger variables and context describe the event that began the hold; the recheck only gates.
**Weaknesses**: Context is from hold start, not from the moment the condition last held.
**Example**: `hass.async_run_hass_job(job, {"trigger": {... "from_state": from_s, "to_state": to_s, "for": ...}}, event.context)`
**Read**: core state.py L175-260; pyscript trigger.py L1180-1260.

### Pattern 3: Marker only by absence or by call-side flag; none on the payload
**Used by**: AppDaemon (old=None), pyscript (no var_name/value keys in initial func_args), NetDaemon (Old==null), Node-RED (internal `runAll` param)
**How it works**: Consumers infer synthetic-ness from the shape (old is None / missing keys); at most an internal flag skips timers/filters. No peer adds an explicit "synthetic"/"initial" field to the event.
**Strengths**: Simple; nothing to maintain.
**Weaknesses**: Shape inference only works inside the callback; downstream recorders can't distinguish. Node-RED's old==new shape is ambiguous with real attribute-less changes.
**Read**: appdaemon state.py L328-380 and scheduler.py L369-395; pyscript trigger.py L1090-1140; nrhaws L102-200.

### Pattern 4: Fresh Context only when none is incoming (pyscript run context)
**Used by**: pyscript
**How it works**: The function-run context is `Context(parent_id=incoming.id)` if there is one; otherwise a new bare `Context()`. The fabricated Context is the run's own (it fires `pyscript_running` with it), not presented as an HA-issued event context. Parent link records provenance.
**Strengths**: Fabricated ids are explicitly new contexts for the run, with parent_id linking back where known.
**Weaknesses**: Only relevant if the framework itself issues service calls and needs a context; not an event field.
**Read**: pyscript trigger.py L1359-1362.

## Anti-Patterns
- Fabricating an event-level context id and presenting it as HA-issued: no peer does this. (Hassette's uuid4-as-event-context has no precedent in the six surveyed projects.)

## Gaps
- No peer's traces/history record initial fires distinctly: HA automation traces mark nothing for initial (no initial fire in HA core triggers; `for:` traces simply show the trigger with `for`/original context). I did not open homeassistant/components/automation trace code or the HA frontend; not searched for beyond core trigger. Home Assistant frontend (subscribeEntities initial-state delivery) not read; [no source found] for a synthetic marker there.
- pyscript's `state_check_now` docs and any issue discussion on context not read; AppDaemon issue tracker and NetDaemon issues not searched. HA core `async_track_template_result` initial runs (helpers/event.py) not read.
- First pyscript clone from a wrong org failed (auth prompt); retried with custom-components/pyscript, success. exa-search not used; no web sources needed beyond source reading.

## Relevance to Us

No peer fabricates an event context. The two closest peers (NetDaemon `WithCurrent`, Node-RED "output on connect") build the initial event from the real current state object, so it carries the real context of the change that last set the state. Home Assistant's own `for:` holds fire with the original triggering event's context. None marks the payload as synthetic; they rely on `old_state` being absent or on a call-side flag. Hassette's random uuid4 is the outlier, and threading a flag or adding a payload marker would be more machinery than any peer carries.

## Recommendation

Build the synthetic event from the cached state's real `context` and the base `hass.event.state_changed` topic, matching NetDaemon and Node-RED. That removes the fabricated id at its source, so consumers holding only the event record honest data without a marker. Whether to keep a call-side "synthetic" label (today's `HASSETTE_SYNTHETIC` origin on normal rows) is a local choice; peers either keep a call-side flag (Node-RED, pyscript) or rely on `old_state is None` (AppDaemon, NetDaemon). Coverage gap: HA automation trace code and the HA frontend weren't read.

## Sources

### Reference implementations
- https://github.com/AppDaemon/appdaemon/blob/dev/appdaemon/state.py (add_state_callback ~L248-400); dispatch in appdaemon/scheduler.py exec_schedule ~L369-395
- https://github.com/custom-components/pyscript/blob/master/custom_components/pyscript/trigger.py (L1087-1140 initial check; L1180-1260 hold; L1359-1362 context)
- https://github.com/home-assistant/core/blob/dev/homeassistant/components/homeassistant/triggers/state.py (L175-260)
- https://github.com/zachowj/node-red-contrib-home-assistant-websocket/blob/main/src/nodes/events-state/EventsStateController.ts (onStatesLoaded L228-245; onHaEventsStateChanged L102-200)
- https://github.com/net-daemon/netdaemon/blob/main/src/HassModel/NetDaemon.HassModel/Entities/EntityExtensions.cs (L58-135); StateChange.cs L29
