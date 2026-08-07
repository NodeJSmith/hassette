---
task_id: "T07"
title: "Add the four narrowed sensor accessors to StateManager"
status: "planned"
depends_on: ["T06"]
implements: ["FR#5", "AC#17"]
---

## Summary

Expose the four value shapes as accessors — `self.states.numeric_sensor`, `.enum_sensor`,
`.timestamp_sensor`, `.date_sensor` — each returning a `DomainStates` parameterized to its class and
filtered by its shape. This is the path an app author meets first in autocomplete, and the only one
where the declared type and the runtime type agree exactly with no cast. Four hand-written entries in
`state_manager.pyi` are what make the narrowing visible to pyright. This task also adds the
accessor-naming text deferred from PR 1.

## Target Files

- modify: `src/hassette/state_manager/state_manager.py`
- modify: `src/hassette/state_manager/state_manager.pyi`
- modify: `src/hassette/models/states/sensor_shapes.py`
- modify: `src/hassette/models/states/base.py`
- modify: `src/hassette/exceptions.py`
- create: `tests/integration/test_sensor_shape_accessors.py`
- read: `src/hassette/state_manager/state_manager.py`
- read: `tests/integration/test_states.py`

## Prompt

Read `context.md` first, then the design doc's `## Architecture → The accessors` section and the
`## Edge Cases` entry for `self.states[NumericSensorState]`.

**Part 1 — four real properties (FR#5).**

Add four `@property` declarations on `StateManager`, **not** `__getattr__` routing. `__getattr__`
(`state_manager.py:216-264`) fires only when normal attribute lookup fails, so a real property
shadows it cleanly and avoids teaching `__getattr__` to parse accessor names into shapes. Each
returns a `DomainStates` built with `domain="sensor"`, the matching class from T04, and the matching
shape predicate from T06.

Reuse the existing per-class cache. `_domain_states_for` (`:208-214`) is keyed by state class, so
the four classes are four distinct keys and each accessor caches independently — the existing
`sensor` accessor is untouched. Today `_domain_states_for` delegates to `self[state_class]`
(`__getitem__`, `:266-285`), which passes neither a domain nor a predicate; it needs to learn to
construct with both. Do **not** change `StateManager.__getitem__` itself — `self.states[CustomClass]`
must keep working exactly as documented for custom state classes.

**Part 2 — four stub entries.**

Add four matching property declarations to `src/hassette/state_manager/state_manager.pyi` beside the
existing `sensor` property (`:127-128`), each typed `DomainStates[<ShapeClass>]`. The stub is
hand-written with no generator and no freshness check — nothing ties a stub accessor to a real HA
domain, which is exactly why these four work. This file is what makes `s.value` narrow to
`float | None` for pyright.

**Part 3 — the accessor-naming text (deferred from PR 1).**

Now that the accessors exist, add the pointers that PR 1 deliberately omitted:

- An optional accessor-hint ClassVar on each of the four classes in `sensor_shapes.py`, naming its
  accessor (e.g. `"numeric_sensor"`).
- In `models/states/base.py`, have `get_domain()`'s raise path read that hint (when present) so
  `NoDomainAnnotationError` can say "use `self.states.numeric_sensor`" instead of only the generic
  message. Update `NoDomainAnnotationError.__init__` in `exceptions.py` to accept and render the
  hint. Both must stay optional — every other state class has no hint and must keep the current
  message unchanged.
- A sentence in each class docstring stating that `self.states[<class>]` is unsupported and naming
  the accessor instead.

This is the "encode the lesson in the error, not just the docs" requirement: users will try
`self.states[NumericSensorState]`, and the failure should explain itself.

**Part 4 — integration tests.**

Create `tests/integration/test_sensor_shape_accessors.py`. These are integration tests because the
accessors reach through `StateManager` to a state proxy — the seam where the domain-passing and
caching changes could regress. Use the harness pattern from `tests/integration/test_states.py`.

## Focus

**Depends on T06** for the `DomainStates` domain and predicate parameters, and transitively on T04
for the classes and classifier.

**`self.states[NumericSensorState]` still raises, and that is intended.** Generic indexing
constructs a `DomainStates` without an explicit domain, and the four classes deliberately do not
re-declare `domain`, so `get_domain()` raises `NoDomainAnnotationError`. Do not "fix" this by
re-declaring `domain` (it clobbers `SensorState` process-wide) or by adding an MRO walk to
`get_domain()`. The four accessors exist for exactly this access; Part 3 makes the error say so.

**Caching interacts with membership.** `_domain_states_for` caches the `DomainStates` *container*
per class; the container's own `_cache` holds per-entity validated models keyed by `last_updated` +
frozen content. Membership is recomputed per access and never cached across a device-class change,
so a runtime device-class flip correctly moves an entity out of the view on the next access. Verify
this rather than assuming it — it is the `device_class` changes at runtime edge case.

**Do not add `.of(device_class)` or per-device-class stub overloads.** Filtering to a specific
device class is a data query, not a typing feature. The type axis has four members and the four
accessors cover it completely — which is also why a new HA device class requires no stub change.

**Check the existing `isinstance` assertions.** `tests/integration/test_states.py` and
`tests/integration/test_app_test_harness.py` carry `isinstance` assertions on state classes. Verify
none assumes `SensorState` is the *only* sensor class; since the four subclass it, they should pass
either way, but confirm rather than assume.

**AC#17 carries the accessor-level `uptime` assertion.** AC#6 (in T04) covers the classifier-level
half; this task proves an `uptime` entity actually surfaces in `self.states.timestamp_sensor`.

## Verify

- [ ] FR#5: `StateManager` exposes `numeric_sensor`, `enum_sensor`, `timestamp_sensor`, and
      `date_sensor` as real properties, each returning a `DomainStates` parameterized to the
      matching class, with matching entries in `state_manager.pyi`.
- [ ] AC#17: `uv run pytest tests/integration/test_sensor_shape_accessors.py -n 4` passes, asserting
      each accessor returns a `DomainStates` of the right class, that membership is exactly the
      sensors whose shape matches and whose state converts (fixture spanning all four shapes, an
      unknown-shape sensor, and an unconvertible numeric-metadata sensor), and that an `uptime`
      sensor appears in `self.states.timestamp_sensor`.
