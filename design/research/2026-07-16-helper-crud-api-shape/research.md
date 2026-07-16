# Research Brief: Helper CRUD API Shape (Issue #1233)

## Context

35 flat CRUD methods on `Api` (8 domains × 4 ops + 3 counter shortcuts, lines 989-1477 in `api.py`) need restructuring before the v1.0 API freeze. The question is not whether to restructure, but what shape to restructure into.

## Finding 1: The methods are perfectly mechanical

All 32 CRUD methods follow an identical template:

```python
# list: no params → list[{Domain}Record]
async def list_input_booleans(self) -> list[InputBooleanRecord]:
    val = await _ws_helper_call(self, "input_boolean", "list")
    items = _expect_list(val, "input_boolean/list")
    return [InputBooleanRecord.model_validate(item) for item in items]

# create: params → Record
async def create_input_boolean(self, params: CreateInputBooleanParams) -> InputBooleanRecord:
    val = await _ws_helper_call(self, "input_boolean", "create", **params.model_dump(exclude_unset=True))
    record = InputBooleanRecord.model_validate(_expect_dict(val, "input_boolean/create"))
    return record

# update: id + params → Record
async def update_input_boolean(self, helper_id: str, params: UpdateInputBooleanParams) -> InputBooleanRecord:
    val = await _ws_helper_call(self, "input_boolean", "update", input_boolean_id=helper_id, ...)
    record = InputBooleanRecord.model_validate(_expect_dict(val, "input_boolean/update"))
    return record

# delete: id → None
async def delete_input_boolean(self, helper_id: str) -> None:
    await _ws_helper_call(self, "input_boolean", "delete", input_boolean_id=helper_id)
```

The only variations:
- The ID key name (`input_boolean_id`, `counter_id`, `timer_id`) — uniform per domain
- `input_datetime` has a `model_validator` on `CreateInputDatetimeParams` (has_date or has_time)
- `input_number` has `min`/`max` required fields; `counter` uses `minimum`/`maximum` (HA asymmetry)
- The 3 counter shortcuts use `call_service()` instead of `_ws_helper_call()`

The `RecordingApi` already recognizes this: it has generic `_list_helper`, `_create_helper`, `_update_helper`, `_delete_helper` methods with a `RECORD_TYPE_TO_DOMAIN` dispatch table. The 32 per-domain methods are thin typed wrappers over those generics.

## Finding 2: The original design doc explicitly rejected `Api.helpers`

`design/specs/031-helper-crud-api/design.md` considered and rejected the sub-namespace for three reasons:

1. **Generator constraint**: the sync-facade codegen walks a single `ast.ClassDef` — sub-namespace classes would need generator changes
2. **Caller ergonomics**: `api.create_input_boolean(...)` is more discoverable than `api.helpers.create_input_boolean(...)`
3. **Consistency**: `Api` is the monolith entry point; a second layer creates naming asymmetry

Issue **#422** ("Split `api.py` into focused submodules") already tracks the proper fix for the file-size cap violation. The design doc called it "likely a mixin or composition pattern."

## Finding 3: The codegen pipeline is brittle to shape changes

The sync facade generator (`codegen/src/hassette_codegen/sync_facade/generic.py`) does:
1. `ast.parse` the source file
2. Find the class by exact name match in `module.body`
3. Walk `target_class.body` for wrappable/delegatable methods
4. Emit wrappers with `self.task_bucket.run_sync(self._api.name(call))`

**It has no support for nested classes, mixins, or multi-file definitions.** The header imports (all 24 helper model types) are hand-maintained string literals — not derived from the source.

The recording facade generator (`recording.py`) correlates `Api.foo` and `RecordingApi.foo` by identical method name string — no other registry.

Any shape change that moves methods off the `Api` class body or renames them requires generator changes.

## Finding 4: Integration surface

- **35 methods** on `Api`, mirrored on `ApiSyncFacade` (generated), `RecordingApi` (hand-written protocol + impl), `RecordingSyncFacade` (generated)
- **~91 test functions** across 6 files
- **0 example app usages** — no example apps use helper CRUD
- **2 doc pages** + 5 type-checked snippet files (CI-enforced via pyright)
- **2 hardcoded name lists** in tests (`DOCUMENTED_EXCLUSIONS[Api]` and `KNOWN_READ_METHODS`)

## Finding 5: Helper models are genuinely distinct

The 8 domains have different field sets (42-70 lines each):
- `input_boolean`: name, icon, initial (bool)
- `input_number`: name, min, max, initial (float), step, unit_of_measurement, mode (box/slider)
- `input_text`: name, min, max, initial, pattern, mode (text/password)
- `input_select`: name, options (list[str]), icon, initial
- `input_datetime`: name, has_date, has_time, icon, initial + model_validator
- `input_button`: name, icon (minimal)
- `counter`: name, icon, initial (int), minimum, maximum, step, restore
- `timer`: name, icon, duration, restore

This means a fully generic `create(domain, **kwargs)` approach loses type safety — the valid kwargs differ per domain.

---

## Competing Shapes

### Option A: Per-domain facade classes (the issue's proposal)

```python
# Usage: api.helpers.input_boolean.create(CreateInputBooleanParams(...))
class HelperNamespace:
    input_boolean: InputBooleanHelper
    input_number: InputNumberHelper
    # ... 8 small classes
```

| Dimension | Assessment |
|-----------|-----------|
| Public methods on Api | 1 (`helpers` property) |
| Type safety | Full — each class has typed create/update/delete |
| Autocomplete | Good — `api.helpers.` shows 8 domains, then `.create()` shows domain params |
| Codegen impact | **Large** — generator must learn to walk sub-objects or generate 8 facade classes |
| Test impact | **Large** — all 91 test functions change call sites |
| Complexity | 8 new classes + 1 namespace class + generator overhaul |
| Developer experience | `api.helpers.input_boolean.create(params)` — 4 segments, verbose |

### Option B: Single generic method (string domain)

```python
# Usage: api.helpers.create("input_boolean", name="foo")
class HelperClient:
    async def list(self, domain: str) -> list[BaseModel]: ...
    async def create(self, domain: str, **kwargs) -> BaseModel: ...
    async def update(self, domain: str, helper_id: str, **kwargs) -> BaseModel: ...
    async def delete(self, domain: str, helper_id: str) -> None: ...
```

| Dimension | Assessment |
|-----------|-----------|
| Public methods on Api | 1 (`helpers` property) → 4 methods on client |
| Type safety | **None** — returns `BaseModel`, kwargs untyped |
| Autocomplete | Poor — no per-domain parameter hints |
| Codegen impact | Small — only 4 methods to wrap |
| Test impact | Medium — call sites change but fewer methods |
| Complexity | Low code volume |
| Developer experience | `api.helpers.create("input_boolean", name="foo")` — no type errors caught at write time |

### Option C: Generic with typed model dispatch

```python
# Usage: api.helpers.create(CreateInputBooleanParams(name="foo"))
class HelperClient:
    async def list(self, domain: HelperDomain) -> list[BaseModel]: ...
    async def create[P: CreateParams, R: Record](self, params: P) -> R: ...
    async def update[P: UpdateParams, R: Record](self, helper_id: str, params: P) -> R: ...
    async def delete(self, domain: HelperDomain, helper_id: str) -> None: ...
```

| Dimension | Assessment |
|-----------|-----------|
| Public methods on Api | 1 (`helpers` property) → 4 methods |
| Type safety | **Partial** — input is typed (params model), but return type requires overloads or loses specificity |
| Autocomplete | Good on input (params model), poor on output without overloads |
| Codegen impact | Small — only 4 methods, but overloads for return types get complex |
| Test impact | Medium — call sites change |
| Complexity | Moderate — needs a registry mapping params→domain→record |
| Developer experience | `api.helpers.create(CreateInputBooleanParams(name="foo"))` — type safe input, 3 segments |

### Option D: File split without API change (the "do less" option)

```python
# api.py stays flat, but methods move to a mixin or submodule
# Usage unchanged: api.create_input_boolean(params)
class HelperMixin:
    async def list_input_booleans(self) -> list[InputBooleanRecord]: ...
    async def create_input_boolean(self, params: ...) -> ...: ...
    # ... all 35 methods

class Api(HelperMixin, ...):
    # helper methods inherited, api.py shrinks
```

| Dimension | Assessment |
|-----------|-----------|
| Public methods on Api | **35** (unchanged) |
| Type safety | Full (unchanged) |
| Autocomplete | Same as today |
| Codegen impact | **None if mixin is in same class** — generator walks `Api` body including inherited |
| Test impact | **Zero** — no call site changes |
| Complexity | Low — it's a file reorganization |
| Developer experience | Identical to today |

**But**: this does NOT achieve the stated goal (reduce public API surface). It only fixes the file-size violation (#422).

### Option E: Generic + overloads (recommended)

```python
# Usage: api.helpers.create(CreateInputBooleanParams(name="foo"))
# Returns: InputBooleanRecord (not BaseModel — overloads narrow it)
class HelperClient:
    @overload
    async def create(self, params: CreateInputBooleanParams) -> InputBooleanRecord: ...
    @overload
    async def create(self, params: CreateCounterParams) -> CounterRecord: ...
    # ... 8 overloads total
    async def create(self, params: CreateParams) -> Record:
        domain, record_type = PARAMS_TO_DOMAIN[type(params)]
        val = await _ws_helper_call(self._api, domain, "create", **params.model_dump(exclude_unset=True))
        return record_type.model_validate(_expect_dict(val, f"{domain}/create"))

    # list needs a domain argument (no params to dispatch on)
    @overload
    async def list(self, domain: Literal["input_boolean"]) -> list[InputBooleanRecord]: ...
    @overload
    async def list(self, domain: Literal["counter"]) -> list[CounterRecord]: ...
    async def list(self, domain: HelperDomain) -> list[Record]: ...

    # update/delete similarly overloaded
```

| Dimension | Assessment |
|-----------|-----------|
| Public methods on Api | 1 (`helpers` property) → 4 methods + ~8 overloads each |
| Type safety | **Full** — overloads give exact return types per domain |
| Autocomplete | Good — params model gives input hints, overloads give output type |
| Codegen impact | Medium — generator wraps 4 methods + overloads (overloads are just signatures) |
| Test impact | Medium — call sites change but uniformly |
| Complexity | Moderate — overload declarations are boilerplate but mechanical |
| Developer experience | `api.helpers.create(CreateInputBooleanParams(name="foo"))` — 3 segments, fully typed |
| Counter shortcuts | `api.helpers.increment(entity_id)` / `decrement` / `reset` — or keep on Api |

---

## Comparison Summary

| | A: Per-domain | B: Generic | C: Model dispatch | D: File split | E: Generic+overloads |
|---|---|---|---|---|---|
| Api surface reduction | ✅ 35→1 | ✅ 35→1 | ✅ 35→1 | ❌ stays 35 | ✅ 35→1 |
| Type safety | ✅ full | ❌ none | ⚠️ partial | ✅ full | ✅ full |
| Codegen change | 🔴 large | 🟢 small | 🟡 medium | 🟢 none | 🟡 medium |
| Test migration | 🔴 large (91 fns) | 🟡 medium | 🟡 medium | 🟢 none | 🟡 medium |
| Code volume added | 🔴 ~8 classes | 🟢 ~1 class | 🟢 ~1 class | 🟢 ~0 | 🟡 1 class + overloads |
| DX improvement | ⚠️ verbose | ❌ worse | 🟢 clean | — | 🟢 clean |

## Recommendation

**Option E (Generic + overloads)** gives the best tradeoff:
- Achieves the API surface reduction goal (35→4 visible methods + 1 property)
- Preserves full type safety via overloads
- Single `HelperClient` class is much less code than 8 per-domain classes
- Overloads are mechanical and can be generated alongside the methods
- The `PARAMS_TO_DOMAIN` / `RECORD_TYPE_TO_DOMAIN` registries already exist in `RecordingApi`

**Combine with Option D** (file split) to also close #422: move `HelperClient` into `src/hassette/api/helpers.py`, making `api.py` smaller regardless of the namespace question.

The counter shortcuts (`increment_counter`, `decrement_counter`, `reset_counter`) can either move to `api.helpers.increment(entity_id)` etc., or stay flat on `Api` since they use `call_service()` not the helper CRUD pattern. I'd lean toward moving them — they're conceptually helper operations.

## Open Questions

1. **Overload generation**: Should the overloads be hand-maintained or generated? Given the 8-domain × 4-op pattern, codegen is attractive but adds generator complexity. Hand-maintaining 32 overload signatures (~2 lines each) may be simpler.

2. **`list()` dispatch**: Unlike create/update/delete, `list()` has no params object to dispatch on. It needs an explicit domain argument — either a `Literal` union (`HelperDomain`) or individual `list_input_booleans()` style. The overload approach works with `domain: Literal["input_boolean"]` etc.

3. **Should `HelperClient` be a `Resource`?** The sync facade pattern needs it to be a `Resource` child of `Api`. If it's just a thin wrapper holding a reference to `Api`, it might not need full Resource lifecycle.

4. **How does `StateManager.__getattr__` compare?** `self.states.light` uses `__getattr__` + `.pyi` stubs for per-domain typing. A similar `self.helpers.input_boolean` approach could combine Option A's discoverability with Option E's implementation, but the `.pyi` stub maintenance and the fact that these are methods (not mapping access) makes it less natural.

5. **Counter shortcuts**: Keep on `Api` or move to `HelperClient`? They're `call_service()` wrappers, not WS CRUD — conceptually different but user-associated.
