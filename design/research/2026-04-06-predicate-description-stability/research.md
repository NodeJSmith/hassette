---
proposal: "Investigate predicate_description stability and natural key options for listener upsert (issue #466)"
date: 2026-04-06
status: Draft
flexibility: Decided
motivation: "Preserve listener/job registrations across sessions to keep historical invocations visible"
constraints: "Must handle predicate collision case; must handle removed handlers; upsert was previously rejected as too complex"
non-goals: "N/A"
depth: quick
---

# Research Brief: predicate_description Stability and Natural Key Options

**Initiated by**: Investigating how `predicate_description` is generated, whether it is stable across restarts, and what natural key options exist for the upsert design in issue #466.

## Question 1: How is `predicate_description` generated?

### Full trace

1. **User registers a listener** via `Bus.on_state_change()`, `Bus.on_attribute_change()`, `Bus.on_call_service()`, or `Bus.on()` (`src/hassette/bus/bus.py`).

2. **Predicates are composed** in helper methods (e.g., `on_state_change` at line 303 builds `[EntityMatches(entity_id), StateDidChange()]` plus optional `StateFrom`, `StateTo`, and user `where` predicates). These are passed through `_subscribe()` (line 219) which calls `Bus.on()` (line 163).

3. **`Bus.on()` calls `Listener.create()`** (`src/hassette/bus/listeners.py:194`), passing `where=preds`. Inside `Listener.create()` at line 213, `normalize_where(where)` is called, which wraps the list into an `AllOf` predicate (via `AllOf.ensure_iterable()`). The resulting `AllOf` instance is stored as `listener.predicate`.

4. **`BusService._register_then_add_route()`** (`src/hassette/core/bus_service.py:87`) constructs the `ListenerRegistration`. The key line is **line 110**:

   ```python
   predicate_description=repr(listener.predicate) if listener.predicate else None,
   ```

   So `predicate_description` is **`repr()` of the predicate object**.

5. **`TelemetryRepository.register_listener()`** (`src/hassette/core/telemetry_repository.py:27`) inserts the registration into SQLite with a plain `INSERT`.

### Summary

`predicate_description` = `repr(listener.predicate)`. Since the predicate is almost always an `AllOf` wrapping inner predicates, the repr is the **dataclass auto-generated `__repr__`** of `AllOf`, which recursively calls `repr()` on each inner predicate.

---

## Question 2: What predicate types exist and are their reprs stable?

All predicate classes are in `src/hassette/event_handling/predicates.py`. All are `@dataclass(frozen=True)`.

### Classes WITH custom `__repr__`

| Class | `__repr__` | Stable? |
|-------|-----------|---------|
| `DomainMatches` (line 367) | `DomainMatches(domain='light')` | Yes -- string literal |
| `EntityMatches` (line 384) | `EntityMatches(entity_id='light.kitchen')` | Yes -- string literal |
| `ServiceMatches` (line 401) | `ServiceMatches(service='light.turn_on')` | Yes -- string literal |

### Classes WITHOUT custom `__repr__` (use dataclass auto-repr)

| Class | Fields | Stable across restarts? |
|-------|--------|------------------------|
| `Guard` | `fn: Predicate[EventT]` | **NO** -- `fn` is a callable; repr includes `<function ... at 0x...>` memory address |
| `AllOf` | `predicates: tuple[Predicate, ...]` | Depends on inner predicates -- unstable if any inner is unstable |
| `AnyOf` | `predicates: tuple[Predicate, ...]` | Same as AllOf |
| `Not` | `predicate: Predicate` | Same as inner |
| `ValueIs` | `source: Callable, condition: ChangeType` | **NO** -- `source` is a function (e.g., `get_entity_id`); repr includes `<function get_entity_id at 0x...>` |
| `DidChange` | `source: Callable` | **NO** -- same reason |
| `IsPresent` | `source: Callable` | **NO** |
| `IsMissing` | `source: Callable` | **NO** |
| `StateFrom` | `condition: ChangeType` | Yes if condition is a literal; **NO** if condition is a callable |
| `StateTo` | `condition: ChangeType` | Yes if condition is a literal; **NO** if condition is a callable |
| `StateComparison` | `condition: ComparisonCondition` | Yes (condition is a dataclass like `Increased()`) |
| `AttrFrom` | `attr_name: str, condition: ChangeType` | Yes if condition is a literal |
| `AttrTo` | `attr_name: str, condition: ChangeType` | Yes if condition is a literal |
| `AttrComparison` | `attr_name: str, condition: ComparisonCondition` | Yes |
| `StateDidChange` | (no fields) | Yes -- `StateDidChange()` |
| `AttrDidChange` | `attr_name: str` | Yes -- `AttrDidChange(attr_name='brightness')` |
| `ServiceDataWhere` | `spec: Mapping, auto_glob: bool` | Partial -- spec values may be callables |

### Verdict on `predicate_description` stability

**`predicate_description` (repr) is NOT stable across restarts.** The most common predicate (`AllOf`) wraps `ValueIs` instances whose `source` field is a function reference. The dataclass auto-repr renders function objects with memory addresses, e.g.:

```
AllOf(predicates=(EntityMatches(entity_id='light.kitchen'), ValueIs(source=<function get_state_value_old at 0x7f1234567890>, condition='on')))
```

The `0x7f...` address changes every process invocation. This makes `predicate_description` **unsuitable as part of a natural key**.

---

## Question 3: Does `summarize()` exist? Is it stable?

**Yes, `summarize()` exists** on all predicate dataclasses. It is the source for `human_description`, not `predicate_description`.

### How `human_description` is generated

`src/hassette/core/bus_service.py:98-100`:
```python
human_description: str | None = None
if listener.predicate is not None and hasattr(listener.predicate, "summarize"):
    human_description = listener.predicate.summarize()
```

### `summarize()` outputs by class

| Class | `summarize()` output | Stable? |
|-------|---------------------|---------|
| `Guard` | `"custom condition"` | Yes (but not distinctive) |
| `AllOf` | Joins inner summaries with `" and "` | Yes if inner summaries are stable |
| `AnyOf` | Joins inner summaries with `" or "` | Yes if inner summaries are stable |
| `Not` | `"not " + inner.summarize()` | Yes if inner is stable |
| `ValueIs` | `"custom condition"` | Yes (but not distinctive) |
| `DidChange` | `"changed"` | Yes |
| `IsPresent` | `"is present"` | Yes |
| `IsMissing` | `"is missing"` | Yes |
| `StateFrom` | `"from {condition}"` | Yes -- uses the condition value |
| `StateTo` | `"-> {condition}"` | Yes |
| `StateComparison` | `"state {condition!r}"` | Yes |
| `AttrFrom` | `"attr {name} from {condition}"` | Yes |
| `AttrTo` | `"attr {name} -> {condition}"` | Yes |
| `AttrComparison` | `"attr {name} {condition!r}"` | Yes |
| `StateDidChange` | `"state changed"` | Yes |
| `AttrDidChange` | `"attr {name} changed"` | Yes |
| `DomainMatches` | `"domain {domain}"` | Yes |
| `EntityMatches` | `"entity {entity_id}"` | Yes |
| `ServiceMatches` | `"service {service}"` | Yes |
| `ServiceDataWhere` | `"service data where k = v, ..."` | Yes |

### Example `human_description` for a typical registration

`bus.on_state_change("light.kitchen", handler=handler, changed_to="on")` produces:
- Predicate: `AllOf(predicates=(EntityMatches("light.kitchen"), StateDidChange(), StateTo("on")))`
- `human_description`: `"entity light.kitchen and state changed and -> on"`

### Verdict on `human_description` stability

**`human_description` (via `summarize()`) IS stable across restarts.** It contains no memory addresses or function references. However, it is **not always unique** -- `ValueIs` and `Guard` both return the generic `"custom condition"` string, so two different `ValueIs` predicates with different `source` functions but the same `condition` would have identical summaries.

---

## Question 4: Do any apps register two listeners on the same handler+topic with different predicates?

### Exhaustive search results

**No examples found** in the codebase where the same handler method is registered on the same topic more than once with different predicates.

- `tests/data/apps/my_app.py` registers `handle_event_sync` on `"input_button.test"` (once) and `handle_color_change` on `"light.office"` (once) -- different handlers, different topics.
- `tests/data/apps/my_app_sync.py` registers `handle_event` on `"input_button.*"` (once).
- Test files register handlers on various entities but never the same handler on the same topic twice.

**However**, the API fully supports this pattern. A user could write:

```python
self.bus.on_state_change("light.kitchen", handler=self.on_light, changed_to="on")
self.bus.on_state_change("light.kitchen", handler=self.on_light, changed_to="off")
```

This would create two listeners with the same `(app_key, instance_index, handler_method, topic)` but different predicates (`StateTo("on")` vs `StateTo("off")`). The issue description explicitly calls out this case as a constraint.

---

## Question 5: `human_description` vs `predicate_description`

| Field | Source | Stable? | Unique? |
|-------|--------|---------|---------|
| `predicate_description` | `repr(listener.predicate)` | **No** -- contains memory addresses from function reprs | High -- includes full structural detail |
| `human_description` | `predicate.summarize()` | **Yes** -- pure string composition from data fields | Medium -- `ValueIs`/`Guard` collapse to `"custom condition"` |

They are generated at the same point in `BusService._register_then_add_route()` (lines 98-111) but serve different purposes:
- `predicate_description` was a debugging aid (full structural repr)
- `human_description` was added in migration 002 as a stable, readable summary

---

## Question 6: How `BusService` builds the registration

`src/hassette/core/bus_service.py:87-121` -- `_register_then_add_route()`:

1. Reads `listener.source_location` (captured at registration time via stack introspection)
2. Reads `listener.registration_source` (source code snippet of the call site)
3. Calls `listener.predicate.summarize()` if available -> `human_description`
4. Calls `repr(listener.predicate)` -> `predicate_description`
5. Constructs `ListenerRegistration` with all 12 fields
6. Passes to `self._executor.register_listener(reg)` which calls `TelemetryRepository.register_listener()` -> plain `INSERT` returning the new row ID
7. Sets `listener.db_id` via `listener.mark_registered(db_id)`

---

## Recommendation: Natural Key for Upsert

### `(app_key, instance_index, handler_method, topic)` -- almost sufficient

This 4-tuple is unique for every registration found in the codebase today. However, the issue explicitly requires handling the predicate collision case (same handler+topic, different predicates).

### Adding `human_description` as the 5th key component

`human_description` is **stable across restarts** and **distinctive enough** for the predicate collision case:

- `on_state_change("light.kitchen", handler=h, changed_to="on")` -> `"entity light.kitchen and state changed and -> on"`
- `on_state_change("light.kitchen", handler=h, changed_to="off")` -> `"entity light.kitchen and state changed and -> off"`

These differ, so the 5-tuple `(app_key, instance_index, handler_method, topic, human_description)` would correctly identify them as distinct registrations.

### Edge case: `ValueIs` with custom callables

If a user writes:
```python
self.bus.on_state_change("light.kitchen", handler=h, changed_to=lambda v: v > 50)
self.bus.on_state_change("light.kitchen", handler=h, changed_to=lambda v: v < 20)
```

Both would produce `human_description = "entity light.kitchen and state changed and custom condition"` -- **identical summaries for different predicates**. This is the `ValueIs.summarize()` returning `"custom condition"` problem.

### Mitigation options for the edge case

1. **Accept the limitation** -- callable predicates on the same handler+topic is an unusual edge case. Document that this pattern requires distinct handler method names.
2. **Improve `ValueIs.summarize()`** -- for literal conditions, include the value; for callables, include the function name (`condition.__qualname__`). This would produce `"-> <lambda>"` which is still not unique but at least flags the ambiguity.
3. **Use `registration_source` as a tiebreaker** -- the captured source code snippet from the call site includes the actual arguments. Two different `changed_to=` calls would have different `registration_source` values. This is stable across restarts (it's source code, not runtime state).

### Suggested natural key

**Primary**: `(app_key, instance_index, handler_method, topic, human_description)`

**With tiebreaker for the callable edge case**: Add `registration_source` as a 6th column in the upsert key, or use it as a fallback when `human_description` contains `"custom condition"`.

**Do NOT use `predicate_description`** in the natural key -- it contains memory addresses and is unstable across restarts.
