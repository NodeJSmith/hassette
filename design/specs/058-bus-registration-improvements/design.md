# Design: Bus Registration Improvements

**Date:** 2026-05-17
**Status:** draft
**Scope-mode:** hold
**Issues:** #438, #554, #529, #779

## Problem

App developers writing hassette automations face two categories of friction when registering event handlers on the bus:

**Development ergonomics:** The handler registration API has accumulated options over time without consolidating them. Adding a new behavioral option (e.g., a timeout override) requires changes across five layers: the Listener dataclass, the factory method, the Bus registration method, the options type definition, and every convenience method that forwards options. Monitoring multi-entity patterns (e.g., presence detection across three people) requires a loop that produces N independent subscriptions with no unified cancel. The registration task (confirming DB persistence) is discarded internally and inaccessible to callers who need deterministic ordering.

**Runtime behavior gaps:** When an app reloads or a config change triggers re-registration, the bus has no mechanism to skip or replace an existing handler by name. The only option is the manual four-line pattern: look up the old subscription, cancel it, re-register with new parameters, store the new subscription. The scheduler already offers `if_exists="error"|"skip"|"replace"` for this exact scenario — the bus lacks parity.

The cost is concrete: every app that dynamically updates handler configuration must carry 4 lines of boilerplate per handler, and developers who forget the manual pattern get a `ValueError` on reload with no recovery path other than restarting. The scheduler solved this with `if_exists` — the bus should too.

## Goals

- Reduce the layer count for adding new listener options from five to two
- Allow callers to await handler registration completion via the subscription object
- Enable single-call multi-entity subscriptions with unified lifecycle management
- Provide idempotent handler registration with skip and replace semantics, mirroring the scheduler

## User Scenarios

### Alex: Automation Developer

- **Goal:** Register event handlers with minimal boilerplate and reliable lifecycle management
- **Context:** Writing and iterating on hassette apps that respond to Home Assistant state changes

#### Registering a multi-entity presence handler

1. **Calls `on_state_change` with a list of person entity IDs**
   - Sees: A single `Subscription` object returned
   - Decides: Whether to await registration completion
   - Then: Handler fires when any listed entity changes state

2. **Cancels the subscription**
   - Sees: Single `.cancel()` call
   - Then: All underlying listeners are removed

#### Replacing a handler after config change

1. **Registers a named handler with `if_exists="replace"`**
   - Sees: The old handler is cancelled and the new one takes its place
   - Decides: Nothing — the replacement is automatic
   - Then: New handler fires with updated predicate/debounce/etc.

#### Skipping duplicate registration on reload

1. **Registers a named handler with `if_exists="skip"`**
   - Sees: The existing subscription returned unchanged
   - Decides: Nothing — no error raised, no duplicate created
   - Then: Existing handler continues operating

#### Encountering a skip mismatch (error path)

1. **Registers a named handler with `if_exists="skip"`, but an existing handler with the same name has a different topic or callable**
   - Sees: A validation error identifying the mismatched fields (e.g., "handler 'on_motion' exists but topic changed from 'sensor.a' to 'sensor.b'")
   - Decides: Whether the name collision is accidental (fix the name) or intentional (use `if_exists="replace"` instead)
   - Then: No state changes — the existing handler remains intact

## Functional Requirements

- **FR#1** A consolidated options object groups the behavioral parameters (once, debounce, throttle, timeout, timeout disabled, priority) into a single construct, reducing the number of places that must change when adding a new option
- **FR#2** The subscription object exposes an awaitable registration task that resolves when the handler's database persistence is complete
- **FR#3** The state change and attribute change registration methods accept either a single entity identifier or a list of entity identifiers
- **FR#4** When a list of entity identifiers is provided, a single subscription is returned whose cancel operation removes all underlying listeners
- **FR#5** When a list is provided and a name is specified, each underlying listener receives an auto-suffixed name derived from the entity identifier to prevent internal collisions
- **FR#6** Registration methods accept an existence policy parameter with three modes: error on duplicate (default, preserving current behavior), skip if already registered, or replace the existing handler
- **FR#7** When skip mode encounters a matching name with different handler configuration, a validation error is raised (mirroring the scheduler's mismatch detection)
- **FR#8** When replace mode is used, the existing listener is cancelled and its subscription is removed before the new listener is registered
- **FR#9** The existence policy is only meaningful when a stable name is provided; without a name, the natural key (handler name, topic, predicate summary) continues to serve as the implicit identity

## Edge Cases

- **List + glob interaction:** Each item in an entity ID list may itself be a glob pattern. Both single globs and lists of globs are valid.
- **List + immediate/duration:** `immediate=True` or `duration=` with a glob item in the list raises `ValueError` per the existing glob restriction — checked per-item, not on the list as a whole.
- **Skip with exact match:** `if_exists="skip"` with identical config returns the existing subscription without re-registering.
- **Replace with no existing:** `if_exists="replace"` when no matching name exists behaves identically to a fresh registration — no error.
- **once=True listeners:** Continue to be excluded from collision detection (the existing partial unique index allows unlimited once=True inserts for the same natural key).
- **Empty list:** `on_state_change([], handler=h)` raises `ValueError` — an empty list is always a bug.
- **Single-item list:** `on_state_change(["sensor.a"], handler=h)` behaves identically to `on_state_change("sensor.a", handler=h)` — returns a regular `Subscription`, not a `MultiSubscription`.
- **Large list:** No artificial limit on list size. Each item creates one listener. Performance degrades linearly with count, which is acceptable — lists of 50+ entities would be unusual and better served by glob patterns.
- **MultiSubscription registration_task:** Uses `asyncio.gather` to wrap all inner tasks into a single awaitable.
- **bus_service.py Subscription construction:** The framework's internal cancel-listener `Subscription` at `bus_service.py:204` gets an already-resolved dummy future as `registration_task` since cancel listeners skip DB registration.
- **Concurrent replace safety:** `Bus.on()` is synchronous between the key check and the key insertion (no `await` between check-and-set). Since all Bus operations run on the event loop thread, two concurrent `if_exists="replace"` calls for the same name cannot interleave. Names are scoped by `(app_key, instance_index)`, so cross-app collisions are impossible.
- **Replace followed by add_listener failure:** If `if_exists="replace"` cancels the old listener but the subsequent `bus_service.add_listener()` task fails (e.g., DB error), the old listener is gone and the new one isn't routed. The `_registered_keys` set will contain the new key (added synchronously), but the listener won't be in the router. The developer would need to re-register. This is an acceptable trade-off — DB failures during registration are rare and the app's next reload would recover.

## Acceptance Criteria

- **AC#1** Adding a new behavioral option to the listener requires changes in exactly two places: the options dataclass and the implementation that reads from it (FR#1)
- **AC#2** `await subscription.registration_task` resolves after the listener's database registration attempt is complete; the task propagates DB errors rather than silently succeeding (FR#2)
- **AC#3** `on_state_change(["person.a", "person.b"], handler=h)` registers two listeners and `sub.cancel()` removes both (FR#3, FR#4)
- **AC#4** `on_state_change(["a", "b"], name="presence", ...)` produces listeners named `presence.a` and `presence.b` (FR#5)
- **AC#5** `bus.on(..., name="x", if_exists="skip")` returns the existing subscription when name "x" is already registered with matching config (FR#6)
- **AC#6** `bus.on(..., name="x", if_exists="skip")` raises `ValueError` when name "x" exists with different handler or topic (FR#7)
- **AC#7** `bus.on(..., name="x", if_exists="replace")` cancels the old listener and returns a new subscription (FR#6, FR#8)
- **AC#8** `bus.on(..., if_exists="skip")` without `name=` falls through to existing collision detection: if the 5-tuple natural key matches an existing registration, raises `ValueError` (same as `if_exists="error"`). Skip-and-return-existing requires `name=` (FR#9)
- **AC#9** All existing bus unit tests pass without modification after the ListenerOptions refactor
- **AC#10** Documentation is updated for list entity IDs, if_exists, and registration_task

## Key Constraints

- `if_exists` is a Bus-level registration policy, not a Listener property — it must not be stored on the Listener dataclass or on ListenerOptions. It is consumed entirely by the Bus during registration and discarded.
- The `name=` identity key collapse (from 5-tuple to 3-tuple `(app_key, instance_index, name)`) only activates when `name` is provided. Without `name`, the existing natural key behavior is preserved exactly.
- `ListenerOptions` groups behavioral parameters only — structural parameters (owner_id, topic, handler, app_key, etc.) remain individual `Listener.create()` parameters.

## Dependencies and Assumptions

- Scheduler `if_exists="replace"` (PR #780) has already merged and provides the pattern to follow.
- No database schema changes required — `if_exists` is resolved at the Bus layer before any DB interaction.
- The `bus_service.py` framework listener construction at line 184 is the only non-Bus call site for `Listener.create()` in `src/`. Approximately 12 test files also call `Listener.create()` directly and will need signature updates.

## Architecture

### ListenerOptions Dataclass (#438)

New `@dataclass(slots=True)` in `listeners.py` grouping `once`, `debounce`, `throttle`, `timeout`, `timeout_disabled`, `priority`. `Listener.create()` accepts `options: ListenerOptions | None = None` (defaults to `ListenerOptions()` when None). The existing `_validate_options()` method is called with fields from the options object. `Bus.on()` constructs `ListenerOptions` from its keyword arguments and passes it through.

The `Options` TypedDict in `bus.py` remains as the user-facing kwargs spec for `_subscribe()` — it continues to hold `once`, `debounce`, `throttle`, `timeout`, `timeout_disabled`, `name`, `on_error`. `ListenerOptions` is internal plumbing; `Options` TypedDict is the public API surface.

### Registration Task on Subscription (#554)

Add `registration_task: asyncio.Future[None]` field to `Subscription` (typed as `Future` rather than `Task` because `MultiSubscription` assigns `asyncio.gather()` which returns a `Future`; single-listener `Task` satisfies `Future`). In `Bus.on()`, capture the return value from `self.add_listener(listener)` and pass it to `Subscription(listener, unsubscribe, registration_task=task)`.

The `bus_service.py` DB registration path must re-raise after logging DB failures so the task faithfully reports persistence status. For the framework's internal cancel-listener `Subscription` at `bus_service.py:204`, use an already-resolved dummy future (`loop.create_future()` resolved with `None`) since cancel listeners skip DB registration entirely. Document that `registration_task` confirms DB persistence state, not routing readiness — for non-once listeners, the route is in the router before `registration_task` completes.

### List Entity IDs (#529)

`on_state_change` and `on_attribute_change` accept `entity_id: str | list[str]`. When a list is received:

1. Iterate each entity ID through the existing single-entity predicate-building path
2. Call `self._subscribe(...)` for each, collecting inner `Subscription`s
3. Return a `MultiSubscription` wrapping all inner subscriptions

`MultiSubscription` is a subclass of `Subscription` in `listeners.py`. Its `cancel()` calls `cancel()` on all inner subscriptions (catch-and-log on individual failures). Its `registration_task` is an `asyncio.gather` wrapping all inner tasks. It overrides `listener` as a property that raises `AttributeError` with a helpful message (`"MultiSubscription has multiple listeners — use .listeners or iterate"`). The canonical access path is `listeners: tuple[Subscription, ...]`. To handle the `@dataclass(slots=True)` inheritance, `MultiSubscription` declares `__slots__ = ('_subscriptions',)` and uses `__init_subclass__` or a custom `__init__` to avoid the slot conflict with the parent's `listener` field.

When `name=` is provided with a list, each inner subscription gets `name=f"{name}.{entity_id}"` (using the entity ID, not an index). This means `name="presence"` with `["person.a", "person.b"]` produces listeners named `presence.person.a` and `presence.person.b`.

Glob validation (`immediate` and `duration` restrictions) is checked per-item in the list.

**`name=` as explicit parameter:** `name` is promoted from `**opts` to an explicit keyword parameter on `on_state_change()` and `on_attribute_change()` (alongside the existing `immediate` and `duration` parameters). This makes per-entity suffixing type-safe — the list loop passes `name=f"{name}.{entity_id}"` to each `_subscribe()` call without destructuring `**opts`. The `name` field is removed from the `Options` TypedDict since it's now an explicit parameter on the convenience methods and on `Bus.on()` directly (where it already is).

### if_exists Behavior (#779)

Add `if_exists: Literal["error", "skip", "replace"]` to the `Options` TypedDict (default `"error"`). The collision handling lives in `Bus.on()`, not in `add_listener()`:

1. If `name` is provided, check `_subscriptions_by_key` for the collapsed key `(app_key, instance_index, name, "", "")`
2. If found and `if_exists="skip"`: validate config match, return existing subscription
3. If found and `if_exists="replace"`: cancel old subscription via `remove_listener()`, then fall through to register new
4. If found and `if_exists="error"`: raise `ValueError` (current behavior)
5. If not found: register normally

New tracking dict: `_subscriptions_by_key: dict[tuple[str, int, str, str, str], Subscription]` alongside `_registered_keys`. Populated in `Bus.on()` after constructing the Subscription. Cleared in `on_initialize()` and `remove_all_listeners()`.

**Key capture in closure:** The natural key is computed once in `Bus.on()` and captured in the `unsubscribe` closure. The closure performs both `self._registered_keys.discard(key)` and `self._subscriptions_by_key.pop(key, None)` atomically, rather than recomputing the key at remove-time via `_listener_natural_key()`. This eliminates the risk of key-recomputation mismatches and ensures stale entries are cleaned up on every cancel path — including `Subscription.cancel()`, `remove_listener()`, and harness resets. `_subscriptions_by_key` excludes `once=True` listeners (mirroring `_registered_keys`).

**Identity key change when `name=` is provided:** When `name` is not None, `_listener_natural_key()` returns `(app_key, instance_index, name, "", "")` — the handler_name and topic fields are blanked, making `name` the sole identity. This enables replacing a handler with a completely different callable or topic. The key-collapse is implemented entirely inside `_listener_natural_key()`. Since `add_listener()` (line 200) and `remove_listener()` (line 226) both call this function, updating the function body is sufficient — no separate remove-path change is needed. `_subscriptions_by_key` must use the same collapsed key (it calls the same function).

**Mismatch detection for skip:** When `if_exists="skip"` and a matching key is found, compare the existing listener's `handler_name` and `topic` against the new registration. If they differ, raise `ValueError` with a message identifying the changed fields. This mirrors the scheduler's `diff_fields()` approach.

**Skip-path `registration_task` semantics:** The `registration_task` on a skip-path return is an already-completed task from the prior registration. Awaiting it is safe but does not confirm anything about the current `Bus.on()` call. Callers who need to detect skip vs. fresh registration should compare the returned subscription's identity against their stored reference.

## Convention Examples

### Options TypedDict pattern

**Source:** `src/hassette/bus/bus.py:111-134`

```python
class Options(TypedDict, total=False):
    once: bool
    debounce: float | None
    throttle: float | None
    timeout: float | None
    timeout_disabled: bool
    name: str | None
    on_error: "BusErrorHandlerType | None"
```

### Listener.create() factory

**Source:** `src/hassette/bus/listeners.py:286-375`

```python
@classmethod
def create(
    cls,
    task_bucket: "TaskBucket",
    owner_id: str,
    topic: str,
    handler: "HandlerType",
    where: "Predicate | Sequence[Predicate] | None" = None,
    # ... 18 more params
) -> "Listener":
    cls._validate_options(once=once, debounce=debounce, ...)
    # ... construction logic
    return listener
```

### Scheduler add_job collision handling

**Source:** `src/hassette/scheduler/scheduler.py:164-200`

```python
def add_job(self, job: "ScheduledJob", *, if_exists: Literal["error", "skip"] = "error") -> "ScheduledJob":
    existing = self._jobs_by_name.get(job.name)
    if existing is not None:
        if if_exists == "skip" and existing.matches(job):
            return existing
        if if_exists == "skip":
            changed_fields = existing.diff_fields(job)
            raise ValueError(
                f"A job named '{job.name}' already exists but its configuration has changed "
                f"(changed fields: {', '.join(changed_fields)})"
            )
        raise ValueError(f"A job named '{job.name}' already exists ...")
    self._jobs_by_name[job.name] = job
```

### Bus._subscribe() delegation

**Source:** `src/hassette/bus/bus.py:326-376`

```python
def _subscribe(
    self,
    *,
    method_name: str,
    topic: str,
    handler: "HandlerType",
    preds: list["Predicate"],
    where: "Predicate | Sequence[Predicate] | None" = None,
    kwargs: Mapping[str, Any] | None = None,
    # ... additional params
    **opts: Unpack[Options],
) -> Subscription:
    # normalize where, build preds, delegate to self.on()
    return self.on(topic=topic, handler=handler, where=preds, **opts)
```

### Subscription dataclass

**Source:** `src/hassette/bus/listeners.py:378-395`

```python
@dataclass(slots=True)
class Subscription:
    listener: Listener
    unsubscribe: "Callable[[], None]"

    def cancel(self) -> None:
        self.unsubscribe()
```

## Alternatives Considered

**if_exists on Listener instead of Bus:** Rejected because `if_exists` is a registration-time policy consumed by the Bus. Storing it on the Listener would conflate registration behavior with listener behavior and leak a Bus concern into the Listener dataclass.

**Separate MultiSubscription class vs. extending Subscription:** We use a `MultiSubscription(Subscription)` subclass rather than making Subscription handle both cases. This keeps the single-listener path clean and avoids a confusing `listener` field that points to only one of N inner listeners.

**Skip without mismatch detection:** Rejected. Silent skip when the handler or topic differs would mask bugs where two unrelated registrations accidentally share a name. Raising ValueError on mismatch is consistent with the scheduler and catches accidental name collisions.

**name= + list raises ValueError:** Rejected in favor of auto-suffixing. Blocking name+list would prevent the common pattern of wanting if_exists semantics on multi-entity registrations. Auto-suffixing (`presence.person.a`, `presence.person.b`) gives each inner listener a unique, deterministic name.

## Test Strategy

- **Phase 1 (ListenerOptions):** Run all existing `tests/unit/bus/` tests to confirm zero behavior change. Update ~12 test call sites that use `Listener.create()` directly with the new `options=` parameter.
- **Phase 2 (registration_task):** Test that `Subscription.registration_task` is an `asyncio.Task`, is awaitable, and that `sub.cancel()` works independently of task completion.
- **Phase 3 (list entity IDs):** Test list of two exact entity IDs, list with glob items, cancel removes all, immediate+glob in list raises ValueError, single-string regression check.
- **Phase 4 (if_exists):** Test all three modes (error/skip/replace), skip with matching config, skip with mismatched config raises ValueError, replace cancels old and registers new, replace with no existing is a fresh registration, if_exists without name uses natural key.

## Documentation Updates

- `docs/pages/core-concepts/bus/index.md` — Add sections for multi-entity subscriptions and idempotent registration (if_exists)
- `docs/pages/core-concepts/bus/handlers.md` — Add `registration_task` to subscription reference, add `if_exists` to options table
- Doc snippets for list entity_id and if_exists usage examples

## Impact

**Files modified:**
- `src/hassette/bus/listeners.py` — ListenerOptions dataclass, Subscription.registration_task, MultiSubscription subclass
- `src/hassette/bus/bus.py` — Options TypedDict (add if_exists), Bus.on() (collision handling, task capture), on_state_change/on_attribute_change (str | list[str])
- `src/hassette/bus/__init__.py` — Export ListenerOptions, MultiSubscription
- `src/hassette/core/bus_service.py` — Subscription construction at line 204 (add registration_task)
- ~12 test files calling `Listener.create()` directly
- 2-3 doc pages

**Blast radius:** Moderate. All changes are within the bus module. The `Listener.create()` signature change affects test call sites but the public API (`Bus.on()`, `on_state_change()`, etc.) is additive-only — existing user code is unaffected.

## Open Questions

None — all design decisions resolved during discovery.
