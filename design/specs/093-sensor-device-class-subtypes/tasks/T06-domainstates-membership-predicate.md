---
task_id: "T06"
title: "Add membership filtering to DomainStates"
status: "planned"
depends_on: ["T01", "T02", "T03", "T04", "T05"]
implements: ["FR#6", "FR#7", "FR#12", "FR#13", "AC#4", "AC#8", "AC#9"]
---

## Summary

`DomainStates` is a `Mapping` whose four access methods disagree the moment filtering is introduced:
`__iter__` filters as a side effect of catching conversion failures, while `__len__` and
`__contains__` consult the state proxy directly. A five-sensor probe measured `len() == 5` against
`list()` yielding 2. Give `DomainStates` an explicit membership predicate and thread it through all
four methods so they agree exactly, add the `EntityNotInViewError` that non-member lookup raises, and
drop the per-entity skip log from `error` to `debug`. This is the highest-risk file in the change —
it is on every typed state read, for every domain.

## Target Files

- modify: `src/hassette/state_manager/state_manager.py`
- modify: `src/hassette/exceptions.py`
- create: `tests/unit/state_manager/test_domain_states_membership.py`
- read: `src/hassette/models/states/sensor_shapes.py`
- read: `src/hassette/core/state_proxy.py`
- read: `src/hassette/types/types.py`
- read: `tests/unit/state_manager/test_domain_states_statereader.py`
- read: `tests/unit/test_state_manager.py`
- read: `src/hassette/state_manager/state_manager.pyi`

## Prompt

Read `context.md` first, then the design doc's `## Architecture → Filtering in DomainStates` section
and the `## Edge Cases` entry for "A numeric sensor whose state does not parse as a number."

**Part 1 — two new optional constructor parameters.**

`DomainStates.__init__(self, state_proxy, model)` (`state_manager.py:69-76`) gains:

- an explicit `domain`, defaulting to `model.get_domain()` — needed because `get_domain()` reads a
  class's *own* annotations only (`base.py:197-218`), so the four shape classes (which deliberately
  do not re-declare `domain`) raise `NoDomainAnnotationError`. Passing the domain explicitly is a
  smaller change than an MRO walk and keeps registration behavior intact.
- a membership predicate over the raw state dict, defaulting to `None` (meaning "everything in the
  domain is a member", i.e. today's behavior).

Both must be optional and appended so the ~15 existing positional `DomainStates(proxy, Model)` call
sites in `tests/unit/test_state_manager.py` and
`tests/unit/state_manager/test_domain_states_statereader.py` keep passing unchanged. That every
existing caller is unaffected is a Behavioral Invariant of this design.

**Part 2 — membership is predicate AND convertibility, in all four methods.**

`__iter__` (`:112-125`), `__len__` (`:127-129`), `__contains__` (`:131-139`), and `__getitem__`
(`:141-158`) must all agree. An entity is a member when the predicate accepts it **and** its current
state converts to the model. The predicate is the cheap first gate (three dict-key reads); the
conversion attempt is the second, amortized by the existing `_validate_or_return_from_cache` cache
(`:78-98`), so repeated `len()` calls only re-validate entities whose state actually changed.

This is deliberate: a sensor whose metadata says numeric but whose value is garbage is out of the
view *everywhere at once*, which keeps `len(m) == len(list(m))` unconditionally true and stops one
flaky sensor from aborting an `items()` loop mid-iteration. The accepted tradeoff is that `len()`
and `in` become value-dependent for that one edge — bounded to misbehaving integrations, since
`unknown` and `unavailable` normalize to `None` and stay members.

**Part 3 — `EntityNotInViewError` (FR#12).**

Add an exception to `src/hassette/exceptions.py` that subclasses **both `KeyError` and the existing
state-error hierarchy** (`StateRegistryError`). Its message names the entity, its actual device
class, and the view's expected shape.

Subclassing `KeyError` is the load-bearing part: `Mapping.get()` is implemented by catching
`KeyError`, so `.get()` returns `None` for non-members — consistent with `__contains__` returning
`False`, and preserving the standard "might not be there" idiom on a view where non-membership is
common and expected. `[]` still fails loudly with the legible message.

Raise it from `__getitem__` when an entity exists in the domain but is not a member of this view.
Keep the existing plain `KeyError` for an entity that is not in the domain at all.

**Part 4 — log level (FR#13).**

`__iter__`'s skip path currently calls `LOGGER.error` per entity (`:118-125`). Drop it to `debug`.
At `error`, a 200-sensor install iterating a numeric-only view would emit roughly 150 error lines
per iteration; for a deliberately filtered view a non-match is expected, not exceptional.

**Part 5 — tests.**

Create `tests/unit/state_manager/test_domain_states_membership.py`. The fixture proxy must span all
four shapes, an unmatched (wrong-shape) sensor, **and a numeric-metadata sensor whose value fails
conversion** — that last one is the case a naive implementation gets wrong.

## Focus

**Depends on T04** for the classifier that the predicate wraps. This task does not create the
accessors (T07 does) — it makes `DomainStates` capable of filtering, and tests it by constructing
`DomainStates` directly with an explicit domain and predicate.

**This task opens PR 2, which is why `depends_on` lists all of T01–T05 rather than just T04.** No
files collide between them, so the extra entries are not about write conflicts — they enforce the
`## Delivery Sequencing` boundary. The whole point of the two-PR split is that this file
(`state_manager.py`, on every typed state read for every domain) gets modified only once PR 1's
purely additive half is green underneath it. Starting this task early would give away that
guarantee.

**The `Mapping` invariant is the pin.** A test asserting `len(ds) == len(list(ds))` is what proves
this task correct — the naive implementation fails it (measured: `len() -> 5`, `list()` yields 2).
Write that test first and watch it fail before wiring the predicate through.

**Blast radius: every domain, not just sensor.** `DomainStates` is on every typed state read. The
containment is that both new parameters default to today's behavior — verify by running the full
existing state-manager suite unchanged, not just the new tests.

**`__contains__` currently short-circuits on `make_entity_id`.** It catches `ValueError` and returns
`False` (`:133-139`). Preserve that; add membership on top rather than restructuring it.

**`__getitem__` calls `make_entity_id` then `_state_proxy.get_state`** and raises a plain `KeyError`
when the state is missing (`:154-157`). That path (entity not in the domain) keeps its plain
`KeyError`; the new `EntityNotInViewError` covers the different case of an entity that is present
but not a member.

**Do not add filtering to `StateManager.__getitem__`.** `self.states[SomeClass]` constructs a
`DomainStates` with neither domain nor predicate (`:285`) and must keep working exactly as it does
today for custom state classes — that is a documented contract and a Behavioral Invariant.

**Exception naming lint.** `tools/check_exception_names.py` enforces binding caught exceptions to
`exc` or a `*_exc` name. The existing `except Exception as exc` in `__iter__` already complies.

## Verify

- [ ] FR#6: A `DomainStates` built with a shape predicate contains exactly the entities whose shape
      matches **and** whose state converts; an entity failing either check is not a member.
- [ ] FR#7: `len(ds) == len(list(ds))` holds over a fixture containing matched, wrong-shape, and
      unconvertible entities, and `__contains__` agrees with both.
- [ ] FR#12: `ds[non_member]` raises `EntityNotInViewError`; the error is a `KeyError` subclass;
      `ds.get(non_member)` returns `None`; iteration omits the entity.
- [ ] FR#13: Iterating a filtered view emits no `ERROR` records for skipped entities.
- [ ] AC#4: A test builds a `DomainStates` over a fixture proxy containing all four shapes, an
      unmatched sensor, and a numeric-metadata sensor whose value fails conversion, and asserts
      `len(ds) == len(list(ds))` and that `__contains__` agrees.
- [ ] AC#8: A test asserts direct lookup of a non-member raises `EntityNotInViewError`, that it is a
      `KeyError` subclass, that `.get()` returns `None`, and that iteration omits it.
- [ ] AC#9: A `caplog`-based test asserts no record at `ERROR` is emitted while iterating a narrowed
      view containing non-matching entities.
