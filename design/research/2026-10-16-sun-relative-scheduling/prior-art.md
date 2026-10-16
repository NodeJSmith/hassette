---
topic: "Scheduling relative to sunrise/sunset, offsets after the event"
date: 2026-10-16
status: Draft
---

# Prior Art: Sun-Relative Scheduling

## The Problem

A job scheduled "30 minutes after sunset" has to survive the moment of sunset itself. Any design that reads "the next sunset" and adds the offset breaks there: at sunset the next sunset becomes tomorrow's, before tonight's sunset + 30 min has arrived. That is the bug PR #2957 surfaced in Hassette's `EntityTime("sun.sun", attribute="next_setting", offset=...)` documentation example.

The question is whether this is a fixable mistake in `EntityTime` or a sign that sun scheduling needs its own trigger.

## How We Do It Today

There is no sun trigger. Users are pointed at `EntityTime`, which reads a datetime from an entity's state or attribute, adds `offset`, and fires once at that absolute time (`src/hassette/scheduler/triggers.py`, `EntityTime`). A state-change listener on the entity moves the job whenever the entity changes (`Scheduler._reschedule_entity_time_job`), and `next_run_time` re-reads the entity after each fire.

Two defects follow:

1. **A positive offset is lost when the entity rolls to its next occurrence.** At sunset `sun.sun` flips state and `next_setting` moves to tomorrow. The listener replaces tonight's pending sunset + 30 min with tomorrow's. This is not sun-specific: a phone next-alarm sensor with "alarm + 10 min" fails the same way.
2. **The listener only sees main-state changes** (`on_state_change`'s default `changed=True`), so an `attribute=` value that changes without a state change never moves the job. It happens not to matter for `next_setting`/`next_rising`, which move exactly when the state flips.

`Api.get_config()` already returns HA's configured location. No solar library is a dependency.

## Patterns Found

### Pattern 1: Compute the event per day, add the offset, pick the first result in the future

**Used by**: Home Assistant core (`trigger: sun`, `async_track_sunset`), node-red-contrib-sun-position, pyscript (date-probe variant), AppDaemon's current `run_at_sunset`.

**How it works**: The scheduler never asks "when is the next sunset?". It asks "for local date D, is sunset(D) + offset after now?", walking D from yesterday forward. HA core's `get_observer_astral_event_next` adds the offset inside the loop before the future check, so a positive offset can't be skipped by the event passing, and starting at yesterday catches offsets that cross midnight. The result is armed as a one-shot timer. After it fires, the same function runs again with the new `now` and resolves to tomorrow. HA re-arms before running the action, and also re-arms when the location config changes.

Drift is handled for free, since every date's solar time is computed fresh. Days with no sunset (polar latitudes) raise `ValueError` in astral; HA skips them and scans up to 367 days.

**Strengths**: A pure function of (now, location, offset), so it is restart-safe with nothing to remember. Correct for both offset signs and midnight crossings. Registration and reschedule share one code path.

**Weaknesses**: Needs a solar library (astral) and a location. A local result can differ from `sun.sun`'s by seconds if elevation or refraction settings differ.

**Example**: https://raw.githubusercontent.com/home-assistant/core/dev/homeassistant/helpers/sun.py (`get_observer_astral_event_next`)

### Pattern 2: Store base time and offset separately; anchor the reschedule on the event that just fired

**Used by**: AppDaemon (`basetime` + `offset` in the schedule entry, `restart_timer`).

**How it works**: Registration takes today's event if today's event + offset is still in the future, otherwise the next one. After a fire, `restart_timer` decides whether to skip a day from the offset's sign: a negative offset fired before the event, so the next event is still today's and it skips ahead. A positive offset fired after it, so the next event is already tomorrow's.

**Strengths**: Cheap; supports random offsets.

**Weaknesses**: A history of exactly our bug. AppDaemon #2188 is a restart between sunset and sunset + offset scheduling the run for the next day. #2440 is the day-2 reschedule dropping the offset, because the reschedule path diverged from registration. The sign special case is something Pattern 1 doesn't need.

**Example**: https://raw.githubusercontent.com/AppDaemon/appdaemon/dev/appdaemon/scheduler.py (`restart_timer`)

### Pattern 3: Poll on a short tick and compare time-of-day windows

**Used by**: node-red-contrib-bigtimer.

**How it works**: Every minute it recomputes that day's solar times, adds minute offsets, and tests whether now is inside the on window. Nothing is scheduled, so nothing can be skipped.

**Strengths**: Self-healing across restarts.

**Weaknesses**: Minute resolution. It answers "should this be on now", not "fire once at T", so it doesn't fit a one-shot job scheduler.

**Example**: https://raw.githubusercontent.com/scargill/node-red-contrib-bigtimer/master/bigtimer.js

### Pattern 4 (Hassette's current shape): Read `sun.sun`'s `next_*` attribute, add the offset, reschedule on state change

**Used by**: no project found. The Node-RED HA-websocket cookbook reacts to `sun.sun` state changes with no offsets, and points elsewhere for offset timers. HA core never derives an offset trigger from `sun.sun`; `SunEntity` publishes the next event strictly after now, with no offset.

**Strengths**: Agrees with what HA displays; no solar math; uses HA's location.

**Weaknesses**: The base jumps to tomorrow at the event instant, which replaces any pending offset run (Pattern 5). Even keeping that run couldn't survive a restart inside the gap: the entity no longer says when tonight's sunset was.

### Pattern 5: Entity time + offset, replaced on every change (the generic case)

**Used by**: Home Assistant core (`trigger: time` with `at: {entity_id, offset}`), Node-RED's HA-websocket `time` node. AppDaemon and pyscript document no trigger bound to an entity's time (from their docs and the trigger sources read for Pattern 1; not re-checked for this pattern); users combine a state listener with `run_at` by hand.

**How it works**: Every state change cancels the pending timer and arms a new one at the new value + offset, if that is still in the future (HA: `update_entity_trigger` in `homeassistant/components/homeassistant/triggers/time.py`; Node-RED: `#processEvent` in `src/nodes/time/TimeController.ts`). A time-only value repeats daily, like `EntityTime(daily=True)`.

**Strengths**: No state beyond the one timer. A change always wins, so edits and `unavailable` behave predictably.

**Weaknesses**: A one-off positive offset on an entity that rolls to its next time when the current one arrives never fires; the rollover replaces it. (A daily time-of-day run survives when the rolled value keeps the same time of day.) Neither project tries to keep it.

Hassette tried keeping the pending run across a rollover (PR #2978). The job stores one whole-second run, so the rule had to recover the run's occurrence as `run - offset` and decide "already dispatched" from the wall clock. Three review rounds found holes in that reconstruction: sub-second rounding in both directions, an overdue run dropped before dispatch, and an offset longer than the entity's interval skipping occurrences. The rule was dropped in favour of Pattern 5 plus a documented limit. Offsets after a rolling event belong to a trigger that computes each occurrence itself (Pattern 1).

## Anti-Patterns

- **"Next event + offset" as the only computation**: AppDaemon #2188. HA avoids it by construction.
- **Reusing today's time of day on another date**: pyscript #18. Solar times move minutes per day.
- **A reschedule path separate from registration**: AppDaemon #2440 dropped the offset on day 2.

## Emerging Trends

HA core now routes every sun-like trigger (sunrise/sunset, dawn/dusk, golden and blue hour) through one `get_observer_astral_event_next(observer, event, now, offset, depression)` function. `get_location_astral_event_next` is deprecated, so anything modeled on HA should call astral with an `Observer` directly rather than lean on HA helper internals (pyscript #203 broke on a core helper signature change).

## Relevance to Us

Losing a positive offset on rollover is not sun-specific, but it is also not something the generic case fixes elsewhere: HA and Node-RED replace the pending run on every change (Pattern 5). Keeping it means reconstructing which occurrence a run belongs to from one rounded timestamp, which proved leaky (see Pattern 5). The attribute-only watcher gap is a separate small, general bug.

`sun.sun` is not a sound base for offsets after the event either way. Even a kept run is lost on a restart between sunset and sunset + offset, the same class as AppDaemon #2188, because only computing tonight's sunset can recover it.

Pattern 1 is not "AppDaemon's own logic" in the problematic sense. HA itself computes sun triggers this way, with astral and `hass.config`'s latitude, longitude and elevation. Hassette can read the same location through `Api.get_config()` and get the same answers HA's own automations get, with no Hassette-side location config to drift.

## Recommendation

1. **Keep `EntityTime` on Pattern 5 and document its limit.** Watch the attribute, not only the main state, when `attribute=` is set. Document that a change replaces the pending run, so a positive offset needs an entity that keeps its time. (A keep-pending rule was built and dropped; see Pattern 5.)
2. **Add a dedicated sun trigger if sun offsets should be first-class.** It would implement Pattern 1 (per-date astral, offset inside the loop, start at yesterday, skip polar days) using HA's location from `get_config`, re-reading it on HA's core config update event. That makes it restart-safe for both offset signs, which `EntityTime` on `sun.sun` can't be. It costs an `astral` dependency, and handling for an HA instance with no location set.
3. **Until then**, document `EntityTime` on `sun.sun` for offsets before the event only, and point dusk/dawn light-level automations at a sun elevation condition. HA's own docs recommend elevation over offsets because twilight length varies by season.

Coverage was good on mechanics (source code read for every project except node-red eztimer and sun-position's scheduler node), and thin on DST and polar edge cases.

## Sources

Note: these URLs were not live-verified after the research pass.

### Reference implementations
- https://raw.githubusercontent.com/home-assistant/core/dev/homeassistant/helpers/sun.py — `get_observer_astral_event_next`, the per-date + offset loop
- https://raw.githubusercontent.com/home-assistant/core/dev/homeassistant/components/sun/trigger.py — `trigger: sun`, re-arm before running the action, re-arm on config update
- https://raw.githubusercontent.com/home-assistant/core/dev/homeassistant/helpers/event.py — `async_track_sunrise`/`async_track_sunset`
- https://raw.githubusercontent.com/home-assistant/core/dev/homeassistant/components/sun/entity.py — `sun.sun` publishes the next event with no offset
- https://raw.githubusercontent.com/AppDaemon/appdaemon/dev/appdaemon/adapi.py — `run_at_sunset`
- https://raw.githubusercontent.com/AppDaemon/appdaemon/dev/appdaemon/scheduler.py — `restart_timer`, sign-dependent day skip
- https://raw.githubusercontent.com/custom-components/pyscript/master/custom_components/pyscript/trigger.py — `once(sunset + 30min)` via HA's astral helper
- https://raw.githubusercontent.com/rdmtc/node-red-contrib-sun-position/master/nodes/10-position-config.js — SunCalc, offset per day then loop forward
- https://raw.githubusercontent.com/scargill/node-red-contrib-bigtimer/master/bigtimer.js — 1-minute polling windows

- https://raw.githubusercontent.com/home-assistant/core/dev/homeassistant/components/homeassistant/triggers/time.py — `trigger: time` entity + offset, replaced on every state change
- https://raw.githubusercontent.com/zachowj/node-red-contrib-home-assistant-websocket/main/src/nodes/time/TimeController.ts — Node-RED `time` node, cron rebuilt on every entity event

### Bug reports
- https://github.com/AppDaemon/appdaemon/issues/2188 — restart between sunset and sunset + offset schedules for the next day
- https://github.com/AppDaemon/appdaemon/issues/2440 — offset dropped on the day-2 reschedule
- https://github.com/custom-components/pyscript/issues/18 — today's time of day reused on a later date
- https://github.com/custom-components/pyscript/issues/203 — broke on an HA helper signature change

### Documentation
- https://zachowj.github.io/node-red-contrib-home-assistant-websocket/cookbook/sun-events.html — HA-websocket Node-RED has no offset-aware sun scheduler
- https://www.home-assistant.io/docs/automation/trigger/#sun-elevation-trigger — HA recommends elevation over offsets for dusk and dawn
