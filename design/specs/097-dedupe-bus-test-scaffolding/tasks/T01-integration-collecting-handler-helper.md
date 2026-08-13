---
task_id: "T01"
title: "Add shared collecting-handler helper to integration/bus/helpers.py and adopt in test_bus_duration.py + test_bus_immediate.py"
status: "done"
depends_on: []
implements: ["FR#1", "FR#2", "FR#3", "AC#2", "AC#3"]
---

## Target Files

- modify: `tests/integration/bus/helpers.py`
- modify: `tests/integration/bus/test_bus_duration.py`
- modify: `tests/integration/bus/test_bus_immediate.py`

## Prompt

`tests/integration/bus/helpers.py` currently exposes `seed`, `send_state_change`, `pump_event_loop`,
`fire`, `ENTITY`, `EVENT_LOOP_YIELDS` (read the file first — this is the established shared home for
bus integration test helpers, documented in `tests/integration/bus/CLAUDE.md`).

`test_bus_duration.py` and `test_bus_immediate.py` both repeat this pattern many times (read both
files in full first — this exact shape recurs roughly 6 and 13 times respectively):

```python
received: list[RawStateChangeEvent] = []
fired = asyncio.Event()

async def handler(event: RawStateChangeEvent) -> None:
    received.append(event)
    hassette.task_bucket.post_to_loop(fired.set)

await bus.on_state_change(..., handler=handler, ..., name="...")
...
await asyncio.wait_for(fired.wait(), timeout=...)
assert len(received) == 1
```

Some call sites capture the raw `event`, others need `event.payload.data`; some tests never call
`asyncio.wait_for` on the fired event at all (negative-fire tests, which just assert `received == []`
after some other wait condition). Read every occurrence in both files before designing the helper so
it covers the real call-site variety without forcing an awkward fit.

Add one function to `helpers.py` — pick a name like `make_collector` or `collecting_handler` — that
builds and returns the `(handler, received_list, fired_event)` triple (or two thin variants if a
single shape can't cleanly serve both the "want the event" and "want event.payload.data" cases;
prefer one shape if it works). It needs access to `hassette.task_bucket` — decide whether to take
`hassette` as a parameter or `task_bucket` directly, matching whatever the call sites in both files
already have in scope (check: `test_bus_duration.py`'s `bus_harness` fixture unpacks
`(harness, hassette, bus)` — `hassette` is already there).

Also widen `seed()` in `helpers.py`: it currently only accepts `(harness, entity_id, state_value)`
and calls `make_state_dict(entity_id, state_value)` with no other kwargs. `test_bus_immediate.py`
has ~13 call sites doing `await harness.seed_state(entity_id, make_state_dict(entity_id, value, attributes=..., last_changed=...))`
directly instead of using `seed()` — because `seed()` can't pass those extra kwargs through. Add
`**kwargs` (or explicit `attributes`/`last_changed` params) to `seed()` that forward to
`make_state_dict`, then replace those direct `harness.seed_state(...)` call sites in
`test_bus_immediate.py` with `seed(harness, entity_id, value, ...)`.

Update both files to use the new collecting-handler helper wherever the pattern above appears.
Preserve every test's actual assertions and timeout values exactly — this is a pure structural
refactor, not a test-behavior change.

## Verify

- [ ] FR#1: `tests/integration/bus/helpers.py` has a new collecting-handler helper function.
- [ ] FR#2: `test_bus_duration.py` and `test_bus_immediate.py` no longer contain the inline
      `list + asyncio.Event + async def handler(...)` block anywhere the new helper can serve —
      confirm by grepping both files for `asyncio.Event()` and checking each remaining occurrence
      is one the helper genuinely can't cover (document why in a comment if any remain).
- [ ] FR#3: `seed()` accepts and forwards `attributes`/`last_changed` (or equivalent kwargs), and
      `test_bus_immediate.py`'s direct `harness.seed_state(entity_id, make_state_dict(...))` call
      sites that only need those fields now call `seed(...)` instead.
- [ ] AC#2 (partial, target ≤23 by T05): run `uv run python tools/check_duplicate_code.py 2>&1 | grep -A5 "test_bus_duration.py\|test_bus_immediate.py"` and confirm the clusters that were purely internal to these two files are gone (cross-file clusters may persist until T02 lands).
- [ ] AC#3: `uv run pytest tests/integration/bus/test_bus_duration.py tests/integration/bus/test_bus_immediate.py -n 4` passes with zero failures.
