---
task_id: "T02"
title: "Normalize state-conversion error type and route iteration through cache"
status: "done"
depends_on: []
implements: ["FR#4", "FR#5", "FR#6", "FR#7", "FR#8", "AC#2", "AC#3", "AC#4", "AC#5", "AC#9"]
---

## Summary
Two related fixes inside `state_manager.py`. First, domain-typed state access
(`self.states.light["x"]`) currently leaks a raw Pydantic `ValidationError` when a state fails to
convert; wrap the single shared `model_validate` call so it raises the framework's
`UnableToConvertStateError` instead — while preserving the intentional raise-vs-return divergence
across the three access styles. Second, `StateManager.__iter__`/`values()` build a fresh `DomainStates`
per call, bypassing the `_domain_states_cache` that attribute access populates; route iteration through
a shared get-or-create helper so it reuses the same per-entity validation cache, without changing
`__getitem__`'s no-cache contract. Both items live in the same file, so they ship together. The states
docs page must be updated for the new exception (user-facing API-contract touch).

## Target Files
- modify: `src/hassette/state_manager/state_manager.py` — wrap `model_validate` in `DomainStates._validate_or_return_from_cache` (`:86`); add `_domain_states_for` helper and route `StateManager.__getattr__`/`__iter__`/`values()` through it; update `DomainStates.get`/`__getitem__` docstrings
- modify: `docs/pages/core-concepts/states/index.md` — document that domain-typed access raises `UnableToConvertStateError` on conversion failure and contrast with `self.states.get(...)` returning `None`
- modify: `tests/unit/test_state_manager.py` — keep the collision-guard test green; add coverage per Verify (migrate any assertion expecting `ValidationError` on domain subscript to `UnableToConvertStateError`)
- read: `src/hassette/exceptions.py` — `UnableToConvertStateError(entity_id, state_class)` (`:256`)
- read: `src/hassette/conversion/state_registry.py` — `conversion_with_error_handling` (`:152`), reference only
- read: `design/specs/081-design-audit-followups-1096/design.md` — Architecture items 2 & 3
- read: `design/specs/081-design-audit-followups-1096/tasks/context.md`

## Prompt
Implement items 2 and 3 from the design (`## Architecture` → "2. Normalize conversion exception type"
and "3. Route iteration through the cache").

**Item 2 — exception type.** In `DomainStates._validate_or_return_from_cache`
(`src/hassette/state_manager/state_manager.py:72-88`), wrap the `self._model.model_validate(state)` call
(`:86`) in a `try/except pydantic.ValidationError` and re-raise as
`UnableToConvertStateError(entity_id, self._model) from e`. Import `UnableToConvertStateError` from
`hassette.exceptions` and `ValidationError` from `pydantic` at the top of the file. Do **not** reuse
`registry.conversion_with_error_handling` — it uses a different conversion function and logs (would
double-log against `DomainStates.__iter__`'s existing error log). This single site is reached by
`DomainStates.get` (`:90-108`, no try/except — propagates), `DomainStates.__getitem__` (`:175-190`, via
`get`), and `DomainStates.__iter__` (`:152-161`, which catches `Exception` broadly and continues).

Preserve the three-way divergence exactly (it must hold after the change):
- `self.states.light["x"]` (`DomainStates.__getitem__`) → raises `UnableToConvertStateError` on bad
  conversion (and `KeyError` on missing entity — unchanged).
- `self.states.light.get("x")` (`DomainStates.get`) → **also raises** `UnableToConvertStateError` on bad
  conversion; returns `None` ONLY for a missing entity (the `:105-106` path — unchanged).
- `self.states.get("light.x")` (`StateManager.get`, `:312-352`) → returns `None` on bad conversion
  (already has its own `except Exception`) — leave untouched.

Update the `Raises:` blocks of `DomainStates.get` and `DomainStates.__getitem__` docstrings to name
`UnableToConvertStateError`. While editing the `__getitem__` docstring, also fix a pre-existing error:
it currently claims `Raises: EntityNotFoundError` (`:181-183`) but the code raises `KeyError` on a
missing entity (`:189`) — correct the docstring to `KeyError`.

**Item 3 — iteration cache.** Add a private helper to `StateManager`:
```python
def _domain_states_for(self, state_class: type[StateT]) -> DomainStates[StateT]:
    cached = self._domain_states_cache.get(state_class)
    if cached is None:
        cached = self[state_class]            # __getitem__ — fresh, uncached instance
        self._domain_states_cache[state_class] = cached
    return cached
```
Call it from three places:
- `StateManager.__getattr__` (`:270-293`): **preserve the existing guards** — the internal-attr
  recursion guard (`:270-272`), the `RegistryNotReadyError → AttributeError` handling (`:274-280`), and
  critically the `if state_class is None: raise AttributeError(...)` unregistered-domain guard
  (`:285-289`) all stay in `__getattr__`. Only the get-or-create **tail** (the cache lookup at
  `:282-283` and the create-and-store at `:291-293`) moves into `_domain_states_for`. The refactored
  method resolves `state_class`, runs the `None` guard, then `return self._domain_states_for(state_class)`.
  Do NOT pass a `None` `state_class` into the helper (it would call `self[None]` and fail) — the guard
  prevents that.
- `StateManager.__iter__` (`:358-361`): replace `self[state_class]` with `self._domain_states_for(state_class)`.
- `StateManager.values()` (`:367-374`): replace `self[state_class]` with `self._domain_states_for(state_class)`.

`items()` (`:363-365`) delegates to `iter(self)` — no direct edit. Leave `StateManager.__getitem__`
(`:295-310`) returning a fresh, uncached instance — its no-cache contract is unchanged; the helper owns
the caching.

**Docs.** Update `docs/pages/core-concepts/states/index.md` to document the `UnableToConvertStateError`
behavior and the raise-vs-return distinction. Follow the project voice-guide (`.claude/rules/voice-
guide.md`): system-as-subject on this concept page, no "you". The states snippets are Pyright-checked;
if you touch a code block, ensure any snippet file stays type-correct.

**Tests.** See Verify. Grep the test suite for assertions expecting a raw `ValidationError` from domain
subscript access (`self.states.<domain>[...]`) and migrate them to `UnableToConvertStateError`. The
collision-guard test (`test_domain_named_items_does_not_collide_with_items_method`,
`tests/unit/test_state_manager.py:~81`) must stay green unchanged.

## Focus
- `_validate_or_return_from_cache` is the ONE shared site — wrapping it fixes `get`, `__getitem__`, and
  `__iter__` together. Because `__iter__` catches `Exception` and logs-then-continues, and
  `UnableToConvertStateError` subclasses `StateRegistryError` (an `Exception`), iteration still skips
  bad entities and continues — verify this in a test (AC#4).
- Do NOT make `DomainStates.get` swallow the conversion error and return `None` — that would erase the
  divergence. Domain-typed access keeps raising; only the type changes.
- `_domain_states_cache` is keyed by `type[BaseState]` (`:221`); `__getattr__` resolves a domain string
  to a `state_class` via the registry before the cache lookup — keep that resolution; only the
  get-or-create tail moves into the helper.
- The minor "DomainStates also has its own `items()/values()`" (`:110-150`) are different methods on a
  different class — this task only touches `StateManager`'s iteration, not `DomainStates`'s.
- Blast radius: app-facing state access + iteration hot paths. The behavioral invariants (divergence,
  no-cache `__getitem__`, iteration-skips-bad) are pinned by the new tests.

## Verify
- [ ] FR#4: `self.states.light["<bad>"]` raises `UnableToConvertStateError` (naming entity + class), not raw `pydantic.ValidationError`.
- [ ] FR#5: `self.states.light.get("<bad>")` raises `UnableToConvertStateError`; `self.states.get("light.<bad>")` returns `None` — divergence preserved.
- [ ] FR#6: Iterating a domain containing one un-convertible entity yields the good entities and skips the bad one without raising.
- [ ] FR#7: `StateManager.__iter__`/`items()`/`values()` return `DomainStates` from `_domain_states_cache`, sharing validation-cache state with attribute access.
- [ ] FR#8: `StateManager[model]` (`__getitem__`) still returns a fresh, uncached `DomainStates` instance.
- [ ] AC#2: Test asserts subscript access raises `UnableToConvertStateError` (not `ValidationError`) on a malformed state.
- [ ] AC#3: Tests assert `DomainStates.get("<bad>")` raises while `StateManager.get("<bad>")` returns `None`.
- [ ] AC#4: Test asserts iteration over a domain with one un-convertible entity skips it and continues.
- [ ] AC#5: Test asserts iteration + attribute access share cache state and `StateManager[model]` returns a fresh instance; collision-guard test still passes.
- [ ] AC#9: The affected unit/integration suites pass for this task; core change — the branch-level `nox -s system`/`nox -s e2e` gate is green before push.
