---
task_id: "T03"
title: "Remove the catalog's unused device_class dimension"
status: "done"
depends_on: []
implements: ["FR#18", "AC#16"]
---

## Summary

The state catalog carries a `device_class` dimension on its key that has never been populated or
consumed. It was added in passing by PR #197 (2025-12-13) — that PR's body is about deferring
conversion and never mentions it — and has survived eight months and four refactors with no caller.
This design deliberately does not use it, so leaving it in place would be permanently misleading
speculative generality. Remove the field, the fallback chain it enables, and the parameter on both
public writers. `StateKey` itself stays, as a one-field frozen dataclass.

## Target Files

- modify: `src/hassette/models/states/catalog.py`
- modify: `src/hassette/conversion/state_registry.py`
- read: `src/hassette/conversion/validation.py`
- read: `src/hassette/models/states/base.py`
- read: `src/hassette/state_manager/state_manager.py`
- read: `src/hassette/state_manager/state_manager.pyi`
- modify: `tests/unit/conversion/test_registry_validation.py`
- read: `tests/unit/models/test_state_catalog.py`
- read: `docs/pages/core-concepts/states/conversion.md`

## Prompt

Read `context.md` first, then the design doc's `## Replacement Targets` section (the second bullet)
and `## Functional Requirements → FR#18`.

Remove the `device_class` dimension in three places:

1. **`src/hassette/models/states/catalog.py`** — drop the `device_class` field from `StateKey`
   (lines 25-26), drop the `device_class` parameter from `register_state_converter` (line 30) and
   its docstring entry, and simplify `resolve()` (lines 43-60): with only one dimension there is no
   exact→domain-only fallback, so the two-candidate `candidates` list collapses to a single dict
   lookup. Update the module docstring if it describes the two-dimensional key.

2. **`src/hassette/conversion/state_registry.py`** — drop the `device_class` parameter from
   `StateRegistry.register` (lines 114-129) and `StateRegistry.resolve` (lines 131-134), including
   their docstring entries, and update the `register_state_converter(...)` / `resolve(...)`
   delegating calls.

3. **Tests** — `tests/unit/conversion/test_registry_validation.py:88` and `:151` construct
   `StateKey(domain=..., device_class=...)` directly. Rewrite both against the domain-only key while
   preserving what each test is actually checking (duplicate-domain detection at `:87-88`, and the
   warning path at `:150-151`). Read the surrounding test bodies before editing — if a test's entire
   premise was the two-dimensional key, it may no longer be meaningful; say so in your report rather
   than forcing it into a shape that asserts nothing.

**Keep `StateKey`.** Do not collapse it to a plain `str` key. It is exported from both
`src/hassette/models/states/__init__.py` (`__all__`) and `src/hassette/conversion/__init__.py`
(`__all__`), it is the yield type of `DomainStatesMapping.__iter__` / `items()` / `keys()`
(`state_manager.py:403-417`, mirrored in `state_manager.pyi:161-164`), and it is `isinstance`-checked
at `conversion/validation.py:118`. Collapsing it would change the user-visible iteration key type —
a third breaking change for no functional gain. After this task it is a frozen dataclass with one
field, `domain`.

This is a public-signature change on `StateRegistry.register` and `register_state_converter`, so it
joins the PR's `BREAKING CHANGE:` footer.

## Focus

**Verified caller inventory — this is the complete set.** `register_state_converter` is called from
exactly one production site, `src/hassette/models/states/base.py:158`, which already passes `domain`
only. `StateRegistry.register` has one test caller,
`tests/unit/test_state_registry.py:56`, which passes no `device_class`. All four production
`resolve()` call sites pass `domain` only. Nothing in `src/` depends on the dimension.

**`conversion/validation.py:118` reads `key.domain`, not `key.device_class`** — it does
`if not isinstance(key, StateKey) or key.domain is None`. It keeps working unchanged as long as
`StateKey` survives with its `domain` field. Do not "simplify" this check as part of this task.

**The documented override pattern must keep working.**
`docs/pages/core-concepts/states/conversion.md:70-92` teaches users to override a built-in by
subclassing with the same `Literal` domain — the resulting same-key overwrite is the *intended*
mechanism, not a bug. This task must not add an overwrite guard, and the pattern must still work
afterward. `conversion.md:88` also references `register_state_converter` via a mkdocstrings
autolink, so its rendered signature updates automatically once the parameter is gone; check the
surrounding prose does not describe the device-class argument in text.

**Tests snapshot the catalog.** `tests/conftest.py:225-227` snapshots and restores `_STATE_CATALOG`
around each test via `snapshot_catalog()` / `restore_catalog()`, so catalog mutations in tests do
not leak. You can register throwaway classes freely.

**`domain: Hashable | None = None` keeps its default.** Do not make `domain` required as a
drive-by cleanup — that is a separate behavior change and `validation.py:118` explicitly handles the
`domain is None` case as a detectable error condition.

## Verify

- [ ] FR#18: `StateKey` has only a `domain` field; `register_state_converter`,
      `StateRegistry.register`, and `resolve()` (both the catalog function and the classmethod) no
      longer accept `device_class`; `resolve()` performs a single lookup with no fallback chain.
- [ ] AC#16: `grep -rn "device_class" src/hassette/models/states/catalog.py` returns nothing; a test
      asserts `inspect.signature(StateRegistry.register)` has no `device_class` parameter;
      `uv run pytest tests/unit/conversion/ tests/unit/models/test_state_catalog.py tests/unit/test_state_registry.py -n 4`
      passes; and a test confirms the documented domain-override pattern (subclass with the same
      `Literal` domain replaces the built-in) still works.
