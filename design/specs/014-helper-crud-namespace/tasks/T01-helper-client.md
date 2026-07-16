---
task_id: "T01"
title: "Create HelperClient with dispatch registries and overloads"
status: "done"
depends_on: []
implements: ["FR#1", "FR#2", "FR#3", "FR#4", "FR#5", "FR#6", "FR#10", "AC#1", "AC#2", "AC#4", "AC#7"]
---

## Summary

Create `src/hassette/api/helpers.py` containing the `HelperClient(Resource)` class with 4 generic CRUD methods (list, create, update, delete), 3 counter shortcuts (increment, decrement, reset), dispatch registries, and `@overload` declarations for full type safety. Wire it into `Api.__init__` and remove the 35 flat helper methods from `api.py`. This is the foundational task — all other tasks depend on it.

## Target Files

- create: `src/hassette/api/helpers.py`
- modify: `src/hassette/api/api.py`
- modify: `src/hassette/api/__init__.py`
- read: `src/hassette/models/helpers/__init__.py`
- read: `src/hassette/models/helpers/input_boolean.py`
- read: `src/hassette/models/helpers/counter.py`
- read: `src/hassette/models/helpers/input_datetime.py`
- read: `src/hassette/resources/base.py`

## Prompt

Create a new file `src/hassette/api/helpers.py` containing the `HelperClient` class. Read the design doc's `## Architecture` section for the full class design.

**HelperClient structure:**

1. Define `HelperDomain` as a `Literal` union of all 8 domain strings.

2. Define 4 dispatch registries:
   - `CREATE_DISPATCH`: maps `Create*Params` type → `(domain_string, Record_type, id_key_name)` — 8 entries
   - `UPDATE_DISPATCH`: maps `Update*Params` type → same tuple — 8 entries
   - `DOMAIN_DISPATCH`: maps domain string → Record type — 8 entries (for `list()`)
   - `ID_KEYS`: maps domain string → WS id key name (uniform `{domain}_id` pattern) — 8 entries

3. `HelperClient(Resource)` class:
   - `__init__` takes `hassette` and `api` keyword arg, stores `self._api`
   - `on_initialize` calls `mark_ready(self, reason="Helper client initialized")`
   - `config_log_level` property returns `self.hassette.config.logging.api`
   - 4 async CRUD methods with 8 `@overload` declarations each (hand-maintained)
   - 3 counter shortcuts (`increment`, `decrement`, `reset`) using `self._api.call_service()`

4. Import `_ws_helper_call`, `_expect_list`, `_expect_dict` from `hassette.api.api` — these stay in `api.py`.

**api.py changes:**

5. Remove all 35 helper methods (lines 989-1477 — the block starting with `async def list_input_booleans` through `async def reset_counter`). Also remove the comment block at lines 985-988.

6. Add to `Api.__init__`: `self.helpers = self.add_child(HelperClient, api=self)` — following the `self.sync = self.add_child(ApiSyncFacade, api=self)` convention at line 281.

7. Add `from hassette.api.helpers import HelperClient` import.

8. Remove helper model imports that are no longer used in `api.py` (all `Create*Params`, `Update*Params`, and `*Record` types from `hassette.models.helpers`). These imports move to `helpers.py`.

9. Update `src/hassette/api/__init__.py` to export `HelperClient` if appropriate (check current exports pattern).

**Overloads:** See the design doc's Architecture section for the full signature pattern. Each CRUD method has 8 overloads. The implementation method uses `BaseModel` as the param/return type. `list()` and `delete()` dispatch on a `HelperDomain` literal string; `create()` and `update()` dispatch on `type(params)`.

**Counter shortcuts:** Move `increment_counter`, `decrement_counter`, `reset_counter` from `Api` to `HelperClient` as `increment`, `decrement`, `reset`. They delegate to `self._api.call_service()` with `return_response=True`.

## Focus

- `_ws_helper_call` is defined at `api.py:238` — import it into `helpers.py`, do not duplicate it
- `_expect_list` and `_expect_dict` are at `api.py:220-235` — same, import them
- The `input_boolean_id` / `counter_id` / `timer_id` naming is verified uniform across all 8 domains
- `mark_ready` is imported from `hassette.resources.lifecycle`, not a method on `Resource`
- `Resource.__init__` signature: `(self, hassette, task_bucket=None, parent=None)` — `api` is a keyword-only custom param
- Check if `api.py` has `per-file-ignores` in `ruff.toml` (it does: `S101`) — add `helpers.py` to the same ignore if assertions are used
- The overloads must satisfy pyright strict mode — run `prek pyright -a --stage pre-push` to verify

## Verify

- [ ] FR#1: `Api` has a `helpers` attribute set in `__init__` via `self.helpers = self.add_child(HelperClient, api=self)`
- [ ] FR#2: `HelperClient.list()` has 8 `@overload` declarations with `Literal` domain strings returning domain-specific `list[Record]` types
- [ ] FR#3: `HelperClient.create()` has 8 `@overload` declarations dispatching on `Create*Params` types
- [ ] FR#4: `HelperClient.update()` has 8 `@overload` declarations dispatching on `Update*Params` types
- [ ] FR#5: `HelperClient.delete()` has 8 `@overload` declarations with `Literal` domain strings
- [ ] FR#6: `HelperClient` has `increment()`, `decrement()`, and `reset()` methods wrapping `call_service()`
- [ ] FR#10: `prek pyright -a --stage pre-push` exits 0
- [ ] AC#1: `grep -c` for old flat method names in `api.py` returns 0
- [ ] AC#2: `grep -c 'self\.helpers = self\.add_child(HelperClient' src/hassette/api/api.py` returns 1
- [ ] AC#4: `prek pyright -a --stage pre-push` exits 0
- [ ] AC#7: `prek -a` exits 0
