# Context: Smaller Design-Audit Follow-Ups (#1096)

## Problem & Motivation
The 2026-06-19 design audit split its findings into a ship-now slice (landed in #1088, #1102–#1106)
and a backlog tier. Issue #1096 is that backlog tier: six small, separable fixes to core
infrastructure. Each closes a localized inefficiency or inconsistency — a hot-path registry traversal,
a leaky exception type, iteration that bypasses a cache, one fact stored in two mutable places,
redundant HTTP round-trips on attribute writes, and a dead Resource child. None is a correctness bug
today (except a latent TOCTOU in the `set_state` item), but they re-accrete if left, and the audit
context is fresh. All six were re-verified against current code before this plan — the codebase moved
substantially since the audit, so the design carries freshly-verified `file:line` references.

## Visual Artifacts
None.

## Key Decisions
1. **Item 1 (hot path):** Precompute `instance_name` on `ListenerIdentity` and `ScheduledJob` at
   registration time (from the owning app instance's `app_config.instance_name` — the same source the
   executor reads today), and thread it into `CommandExecutor.bind_execution_context` so it stops
   calling `hassette.app_handler.get(...)` on every execution. Logging/telemetry output is unchanged;
   only the resolution point moves.
2. **Item 2 (exception type):** Wrap the single shared `model_validate` call in
   `DomainStates._validate_or_return_from_cache` (`state_manager.py:86`) so a `pydantic.ValidationError`
   becomes `UnableToConvertStateError`. This is the minimal, behavior-preserving fix — it changes only
   the exception *type* on the two domain-typed raising paths, never which paths raise. Do **not** reuse
   the registry's `conversion_with_error_handling` (different conversion fn + its own logging → would
   double-log during iteration).
3. **Item 2 — three-way divergence (must hold):** `self.states.light["x"]` raises;
   `self.states.light.get("x")` **also raises** (returns `None` only for a *missing* entity, never for
   a failed conversion); `self.states.get("light.x")` returns `None`. Preserve this exactly.
4. **Item 3 (iteration cache):** Extract a private `_domain_states_for(state_class)` get-or-create
   helper that mints via `self[state_class]` (`__getitem__`, uncached) on a miss and stores in
   `_domain_states_cache`. Call it from `__getattr__`, `__iter__`, and `values()`. `items()` auto-fixes
   via `iter(self)`. Leave `__getitem__`'s no-cache contract untouched.
5. **Item 4 (stateless detector):** Make `only_app` a parameter of `AppChangeDetector.detect_changes`;
   remove the `only_app_filter` field and `set_only_app_filter`. `AppRegistry` is the sole owner; the
   lifecycle service reads `registry.only_app` and passes it in. Add a test pinning the registry↔
   detection agreement.
6. **Item 5 (verify-then-fix):** Probe a live HA instance for native attribute-merge on
   `POST /api/states/{id}` **before** any code change. Simplify `Api._set_state` only if confirmed; the
   observable merge contract ("un-named attributes preserved") holds either way.
7. **Item 6 (dead Bus child):** Delete the unused `Bus` child from `AppLifecycleService`. Pure
   subtraction — the real file-watcher subscription is on `AppHandler.bus`, untouched.

## Constraints & Anti-Patterns
- **Do NOT pull in the deferred large refactors** (already shipped or on a separate track): T1 dispatch
  bridge (#1102), bus→core→bus import cycle (#1103), T4/T5 web mapper + health math (#1106), N4/N5
  telemetry SQL collapse and package move. Stay within the six backlog items.
- **Preserve the raise-vs-return divergence** (Key Decision 3). Only the exception type changes.
- **Do NOT change `StateManager.__getitem__` caching** — its no-cache direct-access contract is
  documented; only `__iter__`/`values()` route through the cache.
- **Preserve the observable `set_state` merge contract** regardless of item 5's outcome.
- **No `from __future__ import annotations`; no `Optional[X]` (use `X | None`); no lazy imports** — repo
  conventions (see CLAUDE.md). Private `_`-prefixed helpers ARE the project convention here
  (`_validate_or_return_from_cache`, `_domain_states_cache`) — follow it.
- **Core-service changes require local verification:** `nox -s system` and `nox -s e2e` must pass
  locally before push (per CLAUDE.md "Pre-Ship Verification for Core Changes"), in addition to unit +
  integration. Do NOT run unbounded `pytest -n auto` — use an explicit `-n N`.
- **Item 2 is a user-facing API-contract touch** → the states docs page must be updated (design-
  completeness.md).

## Design Doc References
- `## Problem` — the six backlog items and why they matter now.
- `## Architecture` — per-item fix recipe with freshly-verified file:line references (the ground truth
  for implementation).
- `## Key Constraints` — feature-specific prohibitions (divergence, no-cache contract, verify-first).
- `## Test Strategy` — existing tests to adapt, new coverage mapped to FRs, tests to remove.
- `## Impact` — Changed Files, Behavioral Invariants, Blast Radius.
- `## Alternatives Considered` — why the minimal fixes were chosen over the tempting shortcuts.

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

### Existing wrap-and-reraise prior art (reference for messaging, NOT reused wholesale)
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

### Cache-get-or-create keyed by state class (the source item 3 extracts into a helper)
**Source:** `src/hassette/state_manager/state_manager.py` (`__getattr__` — existing code that caches)
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
