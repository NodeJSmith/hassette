# Design: Smaller Design-Audit Follow-Ups (#1096)

**Date:** 2026-06-21
**Status:** approved
**Scope-mode:** hold
**Research:** design/audits/2026-06-19-design-audit-bus-scheduler-execution-web/audit.md

## Problem

The 2026-06-19 design audit (`bus`, `scheduler`, execution, web, `api`, `state_manager`,
app-lifecycle, telemetry) split its findings into a *ship-now* slice and a *backlog* tier. The
ship-now slice and several large refactors have since landed (#1088, #1102–#1106). What remains —
issue #1096 — is six small, separable follow-ups that each fix a localized inefficiency or
inconsistency in core infrastructure:

1. **Hot-path registry traversal (audit T9).** `CommandExecutor.bind_execution_context` calls
   `hassette.app_handler.get(...)` on *every* handler/job execution solely to resolve
   `instance_name` for logging. The command already carries `app_key`/`instance_index`; the name
   could be resolved once at registration.
2. **Leaky exception type (audit N3 / bug #4).** Domain-typed subscript access
   (`self.states.light["x"]`) leaks a raw Pydantic `ValidationError` when a state fails to convert,
   instead of the framework's domain `UnableToConvertStateError`.
3. **Iteration defeats the cache (audit N3).** `StateManager.__iter__`/`items()`/`values()` build a
   fresh `DomainStates` per call (empty per-entity validation cache), bypassing the
   `_domain_states_cache` that attribute access populates.
4. **One fact in two mutable places (audit N2).** The `only_app` filter lives in both
   `AppRegistry._only_app` and `AppChangeDetector.only_app_filter`, kept equal by a sync method with
   no test pin and two public setters — future drift risk.
5. **Redundant round-trips on attribute writes (audit "verify-then-fix").** `Api._set_state` does a
   client-side attribute merge (GET-then-POST), opening a TOCTOU window. A reviewer claims HA's
   `POST /api/states/{id}` merges natively. This must be *verified against a live instance* before
   any code change.
6. **Dead Resource child (audit N2).** `AppLifecycleService` owns a `Bus` child it never uses; the
   live file-watcher subscription is on `AppHandler.bus`.

None of these is a correctness bug today (except the latent TOCTOU in #5). They are boundary gaps
worth closing while the audit context is fresh, before they re-accrete.

## Goals

- Resolve `instance_name` once at registration; remove the per-execution `app_handler.get()` call
  from the executor hot path, with identical logging/telemetry output.
- Normalize the domain-typed state-access failure to raise `UnableToConvertStateError`, while keeping
  the intentional raise-vs-return split between `DomainStates[...]` access and `StateManager.get()`.
- Make iteration reuse the same per-entity validation cache as attribute access, without changing
  `StateManager.__getitem__`'s documented no-cache contract.
- Make `AppChangeDetector` stateless (filter passed as a parameter), with a test pinning the
  registry↔detection agreement.
- Determine empirically whether HA merges attributes natively on `POST /api/states/{id}`; simplify
  `Api._set_state` *only if* the live test confirms it, preserving the documented merge contract.
- Delete the unused `Bus` child from `AppLifecycleService`.

## Non-Goals

- The large refactors the audit deferred to a *different* track are **out of scope** and several are
  already shipped: T1 dispatch bridge (#1102), bus→core→bus import-cycle break (#1103), T4/T5 web
  mapper + health-math (#1106), N4/N5 telemetry SQL collapse and package move. Do not pull these in.
- No change to `StateManager.__getitem__`'s no-cache semantics.
- No change to the *observable* `set_state` merge contract ("keys not mentioned are preserved"),
  regardless of whether the implementation changes.
- No change to the raise-vs-return divergence between domain-typed access and `StateManager.get()`.

## User Scenarios

These are framework-internal changes; the "actors" are app authors and operators who observe the
framework's behavior indirectly.

### App author: writes automations against the states API
- **Goal:** access entity state with predictable, catchable errors
- **Context:** inside a handler, reading `self.states.light["kitchen"]`

#### Conversion failure surfaces a domain error
1. **App author accesses a malformed entity via domain-typed access** (`self.states.light["kitchen"]`
   or `self.states.light.get("kitchen")`)
   - Sees: a `hassette.exceptions.UnableToConvertStateError` naming the entity and target class —
     both subscript and `DomainStates.get` raise it on a failed conversion
   - Decides: catch the framework error rather than `pydantic.ValidationError`; or use
     `self.states.get("light.kitchen")` (generic) which returns `None` instead of raising
   - Then: error type and the raise-vs-return distinction are documented on the states concept page

### Operator: runs Hassette and reads logs/telemetry
- **Goal:** unchanged log/telemetry output, slightly less per-execution overhead
- **Context:** an app fires thousands of handler/job executions

#### Logging context is unchanged after the hot-path fix
1. **A handler executes**
   - Sees: the same `app_key` / `instance_name` / `instance_index` bound to structlog context and the
     `ExecutionMarker` as before
   - Then: no `app_handler.get()` call occurs during the execution

## Functional Requirements

- **FR#1** `ListenerIdentity` and `ScheduledJob` carry a precomputed `instance_name` value, resolved
  at registration time when the owning app instance is known.
- **FR#2** `CommandExecutor.bind_execution_context` resolves `instance_name` from the command's
  precomputed value and performs no `app_handler` registry lookup during execution.
- **FR#3** The structlog context vars and `ExecutionMarker` produced per execution contain the same
  `app_key`, `instance_name`, and `instance_index` values as before the change.
- **FR#4** Domain-typed state access (`DomainStates.__getitem__` and `DomainStates.get`) raises
  `UnableToConvertStateError` (naming the entity id and target state class) when a state dict fails to
  convert, instead of leaking a raw `pydantic.ValidationError`.
- **FR#5** The raise-vs-return divergence is preserved across the three access styles on a conversion
  failure: `self.states.light["x"]` (`DomainStates.__getitem__`) raises; `self.states.light.get("x")`
  (`DomainStates.get`) **also raises** (it returns `None` only for a *missing* entity, never for a
  failed conversion); `self.states.get("light.x")` (`StateManager.get`) returns `None`. The fix changes
  only the exception *type* on the two raising paths, not which paths raise.
- **FR#6** `DomainStates.__iter__` continues to skip un-convertible entities (log and continue) rather
  than aborting iteration.
- **FR#7** `StateManager.__iter__`, `items()`, and `values()` return `DomainStates` instances drawn
  from `_domain_states_cache`, sharing the per-entity validation cache with attribute access.
- **FR#8** `StateManager.__getitem__(model)` continues to return a fresh, uncached `DomainStates`
  instance (no-cache contract unchanged).
- **FR#9** `AppChangeDetector.detect_changes` accepts the `only_app` filter as a call parameter and
  holds no `only_app_filter` instance state.
- **FR#10** `AppRegistry` is the single owner of the `only_app` value; `AppLifecycleService` reads it
  from the registry and passes it to `detect_changes`, with no second stored copy.
- **FR#11** A live-instance probe determines whether HA's `POST /api/states/{entity_id}` merges
  submitted attributes with existing ones. The result is recorded as evidence in the task trail.
- **FR#12** If and only if the probe confirms native merge, `Api._set_state` drops the client-side
  GET-and-merge step while preserving the observable contract that attributes not named in the call
  are retained.
- **FR#13** `AppLifecycleService` no longer constructs or owns a `Bus` child Resource.

## Edge Cases

- **Listener/job with no owning app** (`app_key == ""`): `instance_name` resolves to `None`, exactly
  as the current execution-time path returns when `app_handler.get` misses. Logging output unchanged.
- **App instance not yet registered at listener-registration time:** if `instance_name` cannot be
  resolved at registration, the field is `None` and the executor binds `None` — same as today's miss.
  Confirm whether any registration path runs before the app instance exists.
- **Iteration over a domain with an un-convertible entity:** must still log once and continue (FR#6);
  the new `UnableToConvertStateError` is an `Exception` subclass, so the existing broad `except` in
  `DomainStates.__iter__` still catches it.
- **Collision-guard:** `StateManager.items`/`values`/`keys` are *methods*; `__getattr__` must not
  shadow them with `DomainStates`. The existing
  `test_domain_named_items_does_not_collide_with_items_method` must stay green (FR#7 touches
  `__iter__`/`values`, not `__getattr__`).
- **`set_state` on a non-existent entity:** today it skips the GET-merge and POSTs directly. The
  verify-then-fix must keep new-entity creation working whether or not the merge step is removed.
- **`set_state` probe inconclusive or HA replaces attributes:** leave `Api._set_state` unchanged;
  record the negative result. FR#12 is conditional.

## Acceptance Criteria

- **AC#1** A test asserts that after a handler/job executes, the bound structlog context and
  `ExecutionMarker` carry the expected `instance_name`, and that `app_handler.get` is **not** called
  during `bind_execution_context` (verifies FR#1–FR#3).
- **AC#2** A test asserts `self.states.light["<bad>"]` raises `UnableToConvertStateError` (not
  `pydantic.ValidationError`) when conversion fails, and the error names the entity and class
  (FR#4).
- **AC#3** Tests assert the full divergence on the same malformed state (FR#5): `light.get("<bad>")`
  (`DomainStates.get`) raises `UnableToConvertStateError`; `StateManager.get("<bad>")` returns `None`.
  Together with AC#2 this pins all three access styles.
- **AC#4** A test asserts iteration over a domain containing one un-convertible entity yields the
  good entities and skips the bad one without raising (FR#6).
- **AC#5** A test asserts that iterating `StateManager.values()` and then accessing the same domain
  via attribute returns `DomainStates` instances that share validation-cache state (or are the same
  cached object), and that `StateManager[model]` still returns a fresh instance (FR#7, FR#8). The
  collision-guard test still passes.
- **AC#6** A test asserts `AppChangeDetector.detect_changes(..., only_app=...)` filters correctly with
  no instance state, and a test pins that after `resolve_only_app`, the registry's `only_app` equals
  the value passed to the next `detect_changes` (FR#9, FR#10).
- **AC#7** The live-instance probe result for HA attribute-merge behavior is recorded; if confirmed,
  a system test asserts `set_state` preserves un-named attributes after the implementation change; if
  not confirmed, `Api._set_state` is unchanged and the negative result is documented (FR#11, FR#12).
- **AC#8** `AppLifecycleService` no longer references a `Bus` child; the file-watcher subscription on
  `AppHandler.bus` still fires (existing reload/file-watch behavior unaffected) (FR#13).
- **AC#9** Unit + integration suites pass; because `core/` infrastructure changed, `nox -s system`
  and `nox -s e2e` pass locally before push (per CLAUDE.md).

## Key Constraints

- **Preserve the raise-vs-return divergence** (item 2). `DomainStates[...]` raises on conversion
  failure; `StateManager.get()` swallows and returns `None`. Only the exception *type* on the raising
  side changes.
- **Do not change `StateManager.__getitem__` caching** (item 3). The no-cache direct-access contract
  is documented; only `__iter__`/`values()` route through the cache.
- **Do not duplicate conversion semantics or logging** (item 2). Fix at the existing `model_validate`
  call site with a local exception translation; do not re-route DomainStates through the registry's
  `conversion_with_error_handling` (different conversion function + its own logging would double-log
  during iteration).
- **Verify before fixing `set_state`** (item 5). No code change to `_set_state` without a live-HA
  probe confirming native merge. The observable merge contract is fixed regardless.
- **Stay within the backlog items.** Do not pull in the deferred large refactors (see Non-Goals).
- **Core-service changes require system + e2e tests locally** before push.

## Dependencies and Assumptions

- A live Home Assistant instance is reachable for the item-5 probe. The `tests/system/` suite already
  spins up an HA container (`ha_container` fixture), and the project's demo stack
  (HA Docker + hassette) is available on the dev machine — either can host the probe.
- `UnableToConvertStateError(entity_id, state_class)` already exists (`exceptions.py:256`) and
  subclasses `StateRegistryError` (an `Exception`).
- The registry already has `conversion_with_error_handling` (`conversion/state_registry.py:152`) as
  prior art for the error type — referenced for naming/messaging consistency, not reused wholesale.
- `instance_name` is currently resolved from `app_inst.app_config.instance_name`
  (`command_executor.py:495-499`); the same source is available at registration time.

## Architecture

Six independent changes. Each is small and touches a distinct subsystem; they share no write target,
so they can land as separate commits in any order (suggested order below sequences the
lowest-risk/highest-clarity first).

### 1. Precompute `instance_name` (T9 — hot path)
Add an `instance_name: str | None = None` field to `ListenerIdentity` (`bus/listeners.py:44`) and
`ScheduledJob` (`scheduler/classes.py`). Populate it at registration time from the owning app
instance's `app_config.instance_name` (the same value `bind_execution_context` resolves today).
`CommandExecutor.bind_execution_context` (`core/command_executor.py:491-524`) currently has the
signature `(self, app_key: str | None, instance_index: int)` — it receives *scalars*, not the
listener/job object, and resolves `instance_name` via `self.hassette.app_handler.get(app_key,
instance_index)` (`:497`). The fix threads the precomputed `instance_name` to this method instead:
either add an `instance_name: str | None` parameter that the callers (`execute_handler`/`execute_job`,
which *do* have the listener/job in scope) read off the command's precomputed field and pass in, or
have the callers resolve and bind it. The `app_handler.get(...)` call is removed; the structlog binding
and `ExecutionMarker` construction are otherwise unchanged. Trace the registration sites that build
`ListenerIdentity`/`ScheduledJob` to find where the app instance is in scope and populate
`instance_name` there — the app-registration paths at `bus/bus.py:593` and `scheduler/scheduler.py:452`.
The `ListenerIdentity(...)` at `bus/listeners.py:614` is inside `create_cancel_listener`, a
`source_tier="framework"` factory with no app instance in scope — `instance_name` is `None` there by
definition (the field default), not a population target. Exact call-site shape (extra param vs.
identity object) is settled during planning.

### 2. Normalize conversion exception type (N3)
In `DomainStates._validate_or_return_from_cache` (`state_manager/state_manager.py:72-88`), wrap the
`self._model.model_validate(state)` call (line 86) in `try/except` and re-raise a
`pydantic.ValidationError` as `UnableToConvertStateError(entity_id, self._model) from e`. This single
site is reached by all three domain-level paths: `DomainStates.get` (`:90-108`, no try/except — it
propagates), `DomainStates.__getitem__` (`:175-190`, via `get`), and `DomainStates.__iter__`
(`:152-161`). Effect after the wrap:

- `DomainStates.__getitem__` and `DomainStates.get` both raise `UnableToConvertStateError` on a failed
  conversion (today both leak raw `ValidationError`). `DomainStates.get` still returns `None` only for a
  *missing* entity — that path (`:105-106`) is unchanged.
- `DomainStates.__iter__`'s existing broad `except Exception` (`:157`) still catches it, so iteration
  logs once and continues — `UnableToConvertStateError` is an `Exception` subclass.
- `StateManager.get` (`:312-352`) is a *different* method on a *different* object; it already catches
  `Exception` and returns `None`, and is untouched.

This is the minimal, behavior-preserving change: it alters only the exception *type* on the two
domain-typed raising paths, never which paths raise. Update the `DomainStates.get`/`__getitem__`
docstrings to name `UnableToConvertStateError` in their `Raises:` blocks.

### 3. Route iteration through the cache (N3)
`StateManager.__iter__` (`:358-361`) and `values()` (`:367-374`) currently call `self[state_class]`
(`__getitem__`, fresh uncached instance). `items()` (`:363-365`) delegates to `iter(self)`, so it
fixes automatically once `__iter__` changes — only `__iter__` and `values()` are edited directly.

Extract a small private cache-get-or-create helper keyed by `state_class` — the same
`_domain_states_cache` (`:221`) that `__getattr__` populates (`:282-293`). On a miss the helper calls
`self[state_class]` (i.e. `__getitem__`) to mint the instance, then stores and returns it:

```python
def _domain_states_for(self, state_class: type[StateT]) -> DomainStates[StateT]:
    cached = self._domain_states_cache.get(state_class)
    if cached is None:
        cached = self[state_class]            # __getitem__ — fresh, uncached instance
        self._domain_states_cache[state_class] = cached
    return cached
```

Call it from `__getattr__`, `__iter__`, and `values()` (the get-or-create logic now appears in three
places — extraction matches the project's existing private-helper convention, e.g.
`_validate_or_return_from_cache`). In `__getattr__`, only the get-or-create *tail* moves into the
helper — the recursion guard, the `RegistryNotReadyError` handling, and the
`if state_class is None: raise AttributeError(...)` unregistered-domain guard (`:285-289`) all stay in
`__getattr__` (the helper must never receive a `None` `state_class`). Leave `__getitem__` (`:295-310`)
returning a fresh instance — its documented no-cache contract is unchanged; the helper, not
`__getitem__`, owns the caching. Verify
against the collision-guard test (`__getattr__` still doesn't shadow the `items`/`values`/`keys`
methods).

### 4. Stateless `AppChangeDetector` (N2)
Remove the `only_app_filter` field and `set_only_app_filter` method from `AppChangeDetector`
(`core/app_change_detector.py:47-48,108-110`); read it from a new `only_app` parameter on
`detect_changes` (`:78-79` becomes a local read). `AppRegistry` keeps `_only_app` and its
`set_only_app`/`only_app` accessors as the single source. In `AppLifecycleService`, drop
`update_only_app_filter`'s detector-sync line (`:486-489`) — it now only sets the registry — and at the
`detect_changes` call site (`:395`) pass `only_app=self.registry.only_app`. Add a test pinning that
the registry filter and the value passed to the next `detect_changes` agree.

### 5. Verify-then-fix `Api._set_state` (verify-then-fix)
**Step 5a (verify):** Write a probe against a live HA instance: set an entity with two attributes via
`POST /api/states/{id}` carrying only one attribute, then GET it back and observe whether the other
attribute survived. Record the result in the task trail. **Step 5b (conditional fix):** only if HA
merges natively, remove the GET-and-merge block in `Api._set_state` (`api/api.py:901-923`,
specifically the `entity_exists`+`get_state_raw`+`curr | new` merge) and POST the submitted attributes
directly. Keep new-entity creation working. The docs already state the merge contract
(`docs/pages/core-concepts/api/methods.md:388-408`) — that prose stays true either way; touch it only
if the implementation note needs updating. If the probe is negative/inconclusive, leave the code as-is
and document why.

### 6. Delete unused `Bus` child (N2)
Remove the `bus: Bus` annotation (`core/app_lifecycle_service.py:69`), the
`self.bus = self.add_child(Bus)` line (`:86`), the docstring mention (`:54`), and the now-unused `Bus`
import if nothing else in the file uses it. The real file-watcher subscription on `AppHandler.bus`
(`core/app_handler.py:100-104`) is untouched. No external references to `lifecycle.bus` exist.

## Replacement Targets

- `CommandExecutor.bind_execution_context`'s `app_handler.get(...)` lookup (item 1) is replaced by a
  read of the precomputed command field — remove the lookup, don't keep both paths.
- `AppChangeDetector.only_app_filter` field + `set_only_app_filter` method and the detector-sync line
  in `update_only_app_filter` (item 4) are replaced by parameter passing — remove them.
- The `AppLifecycleService` `Bus` child (item 6) is removed outright.
- Client-side merge block in `Api._set_state` (item 5) is removed **only if** the probe confirms
  native merge; otherwise retained.

## Convention Examples

### Domain exception with structured fields

**Source:** `src/hassette/exceptions.py`

```python
class UnableToConvertStateError(StateRegistryError):
    """Raised when a state dictionary cannot be converted to a specific state class."""

    def __init__(self, entity_id: str, state_class: type["BaseState"]) -> None:
        super().__init__(f"Unable to convert state for entity_id '{entity_id}' to class {state_class.__name__}.")
        self.entity_id = entity_id
        self.state_class = state_class
```

### Existing wrap-and-reraise prior art (reference, not reused wholesale)

**Source:** `src/hassette/conversion/state_registry.py`

```python
def conversion_with_error_handling(self, state_class, data, entity_id, domain) -> "BaseState":
    """Convert state data, logging and re-raising as UnableToConvertStateError on failure."""
    try:
        return convert_state_dict_to_model(data, state_class)
    except Exception as e:
        LOGGER.error(CONVERSION_FAIL_TEMPLATE, entity_id, domain, class_name, truncated_data, e, tb)
        raise UnableToConvertStateError(entity_id, state_class) from e
```

### Current attribute-path caching (the source item 3 extracts into a helper)

**Source:** `src/hassette/state_manager/state_manager.py` (`__getattr__`) — this is the *existing* code
that already caches; item 3 lifts this get-or-create into `_domain_states_for` (see Architecture item
3 for the target helper body) so `__iter__`/`values()` reuse it instead of bypassing the cache.

```python
if state_class in self._domain_states_cache:
    return self._domain_states_cache[state_class]
# ...
self._domain_states_cache[state_class] = self[state_class]
return self._domain_states_cache[state_class]
```

### Slotted identity dataclass (where item 1 adds a field)

**Source:** `src/hassette/bus/listeners.py`

```python
@dataclass(slots=True)
class ListenerIdentity:
    owner_id: str
    handler_name: str
    handler_short_name: str
    app_key: str = ""
    instance_index: int = 0
    # ...
```

## Alternatives Considered

- **Item 2 — reuse `registry.conversion_with_error_handling` inside `DomainStates`.** Rejected: it
  calls a *different* conversion function (`convert_state_dict_to_model`, not `model_validate`),
  changing conversion semantics, and it logs — which would double-log against `DomainStates.__iter__`'s
  existing error log. A local `try/except ValidationError` translation is the minimal,
  no-smuggled-behavior fix.
- **Item 2 — make `DomainStates.get` swallow conversion errors and return `None`.** Rejected: that
  would erase the raise-vs-return divergence the audit says is intentional. Domain-typed access keeps
  raising; only `StateManager.get` swallows.
- **Item 3 — route iteration through `getattr(self, domain_name)`.** Rejected: requires reverse-mapping
  `state_class → domain string` and re-resolving through the registry, and raises `AttributeError` for
  custom/unregistered domains. Direct `_domain_states_cache` lookup keyed by `state_class` is simpler
  and matches what `__getattr__` stores.
- **Item 4 — keep the sync, just add a test pin.** Rejected as the primary fix: it leaves two mutable
  copies and two public setters. Deriving (parameter passing) removes the drift surface entirely; the
  test pin comes along for free.
- **Item 5 — just remove the round-trips now (the reviewer is probably right).** Rejected: the audit
  explicitly flags this as verify-then-fix because a wrong assumption would silently drop attributes on
  every write. A 5-minute live probe settles it; "probably" is not evidence.
- **Do nothing.** Rejected: these are cheap, the audit context is fresh, and leaving them re-accretes
  the boundary gaps the audit identified.

## Test Strategy

### Existing Tests to Adapt
- `tests/unit/test_state_manager.py` — `test_domain_named_items_does_not_collide_with_items_method`
  (lines ~81-84) must stay green after item 3; verify it still passes unchanged. Any existing test
  asserting `light["x"]` raises `ValidationError` on bad conversion must change to expect
  `UnableToConvertStateError` (grep for `ValidationError` in state tests).
- `tests/unit/core/test_app_change_detector.py` — tests calling `set_only_app_filter` /
  constructing the detector with `only_app_filter` (lines ~223-236) must move to passing `only_app`
  to `detect_changes`.
- `tests/system/test_api.py::test_set_state_roundtrip` — extend (or add a sibling) to assert
  attribute preservation, gated on the item-5 probe result.

### New Test Coverage
- FR#1–FR#3: unit test that `bind_execution_context` binds the expected `instance_name` and does not
  call `app_handler.get` (assert via spy/mock on `app_handler`).
- FR#4: unit test that domain-typed subscript raises `UnableToConvertStateError` on a malformed state.
- FR#5: unit test that `StateManager.get` returns `None` on the same malformed state.
- FR#6: unit test that `DomainStates.__iter__` skips the bad entity and yields good ones.
- FR#7/FR#8: unit test that iteration and attribute access share cache state, and `StateManager[model]`
  returns a fresh instance.
- FR#9/FR#10: unit test for stateless `detect_changes(only_app=...)` filtering, plus the registry↔
  detection agreement pin.
- FR#11/FR#12: live-HA probe (system test) for native merge; conditional `set_state` attribute-
  preservation system test.
- FR#13: confirm file-watcher reload still fires after the `Bus` child removal (existing reload
  integration coverage should suffice — verify, add if thin).

### Tests to Remove
- Any test that exists solely to assert the `AppChangeDetector.only_app_filter` field or
  `set_only_app_filter` setter (superseded by the parameter). Confirm none assert behavior still
  needed before deleting.

## Documentation Updates

- `docs/pages/core-concepts/states/index.md` — document that domain-typed access
  (`self.states.light["x"]`) raises `UnableToConvertStateError` on conversion failure, and contrast
  with `self.states.get(...)` returning `None` (item 2; required by design-completeness.md as a
  user-facing API-contract touch).
- Docstrings: `DomainStates.get` and `DomainStates.__getitem__` `Raises:` blocks name
  `UnableToConvertStateError` (item 2).
- `docs/pages/core-concepts/api/methods.md` (lines ~388-408) — only if item 5's fix lands; the
  observable merge contract prose stays true, so this is likely a no-op or a minor implementation
  note. Do not edit unless the probe confirms and the fix ships.
- `CHANGELOG.md` — not edited manually (release-please). Commit types: `perf` (item 1), `fix` (item 2
  exception type; item 5 if it ships), `refactor` (items 3, 4, 6).

## Impact

### Changed Files
- `src/hassette/state_manager/state_manager.py` — modify: wrap `model_validate` (item 2); route
  iteration through cache + add cache helper (item 3). **Highest-traffic file; two items touch it.**
- `src/hassette/core/command_executor.py` — modify: read precomputed `instance_name`, drop
  `app_handler.get` (item 1).
- `src/hassette/bus/listeners.py` — modify: add `instance_name` to `ListenerIdentity`; populate at
  registration (item 1).
- `src/hassette/scheduler/classes.py` — modify: add `instance_name` to `ScheduledJob` (item 1).
- Listener/job registration sites (in `bus/` and `scheduler/`) — modify: resolve and pass
  `instance_name` (item 1). Exact sites to be enumerated during planning.
- `src/hassette/core/app_change_detector.py` — modify: remove field/setter, add parameter (item 4).
- `src/hassette/core/app_registry.py` — read-only reference: remains single owner of `only_app`
  (item 4).
- `src/hassette/core/app_lifecycle_service.py` — modify: pass `only_app` param, drop detector sync
  (item 4); remove `Bus` child (item 6).
- `src/hassette/api/api.py` — modify (conditional): simplify `_set_state` if probe confirms (item 5).
- `docs/pages/core-concepts/states/index.md` — modify: document `UnableToConvertStateError` (item 2).
- Tests under `tests/unit/`, `tests/unit/core/`, `tests/system/` — create/modify per Test Strategy.

### Behavioral Invariants
- Per-execution structlog context and `ExecutionMarker` values are byte-for-byte the same after item 1.
- `DomainStates.__iter__` keeps logging-and-continuing on un-convertible entities.
- `StateManager.__getitem__` keeps returning fresh, uncached instances.
- `only_app` filtering produces the same change-set decisions as before item 4.
- The observable `set_state` merge contract ("un-named attributes preserved") holds regardless of
  item 5's outcome.
- The file-watcher reload path on `AppHandler.bus` is unaffected by item 6.

### Blast Radius
- Items 1, 2, 3 sit on app-facing hot paths (execution logging; state access). Behavior is held
  constant by the invariants above; the risk is a subtle output/caching difference, which the new
  tests pin.
- Item 4 touches app-reload/lifecycle decision-making — covered by lifecycle tests + the new pin.
- Item 5 touches every attribute write — gated behind a live probe precisely because the blast radius
  is high.
- Item 6 is pure subtraction with zero external references.

## Open Questions

None. (Item 5's empirical question is resolved *during* implementation by the probe, not before
planning — its conditional outcome is captured in FR#11/FR#12 and AC#7.)
