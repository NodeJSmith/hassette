# Design: Listener Decomposition

**Date:** 2026-05-18
**Status:** approved
**Scope-mode:** expand
**Issues:** #438, #554
**Research:** /tmp/claude-mine-define-research-vUWhrh/brief.md

## Problem

The central event listener in the bus module has grown to 35 fields serving four distinct consumers: the event router (topic matching), the dispatch engine (handler invocation), the database layer (registration telemetry), and the user (subscription lifecycle). Each new behavioral option threads through five layers: the listener data structure, its factory method, the registration facade, the options type definition, and every convenience method that forwards options.

Duration-hold behavior is scattered across four files with implicit invariants — the timer is constructed in the service layer and attached to the listener via direct private field mutation, creating a two-phase construction protocol documented only in comments. The double-guard pattern in the dispatch path (`duration is not None and _duration_timer is not None`) reveals the codebase does not trust its own invariants.

The cost of inaction is continued sprawl: each new bus feature adds fields to a flat struct that every consumer depends on simultaneously, and the duration timer wiring becomes harder to reason about as more features interact with it.

## Goals

- Reduce the listener data structure from 35 flat fields to 10 or fewer, composing four focused sub-structs
- Give each concern (identity, behavior, invocation, duration) a single owner — zero cross-struct field access for any single concern
- Make the duration timer lifecycle owned by the duration configuration rather than wired externally — eliminate the double-guard pattern in dispatch
- Ensure adding a new behavioral option requires changes in exactly two places: the options struct and the code that reads it (down from five today)
- Enable each sub-struct to be instantiated and tested independently without constructing the full listener
- Extract the event router to its own module with zero imports from the service layer, reducing the service file from 1066 to ~890 lines
- Expose the registration completion signal on the subscription object — callers can await persistence confirmation
- Fix two known invariant violations: in-place list mutation in predicate forwarding, and lazy imports in the accessor module

## Non-Goals

- Backpressure or saturation fixes (challenge findings F4, F5, F13 — separate work tracked in existing issues)
- New bus features: list entity IDs (#529) and idempotent registration (#779) build on top of this decomposition
- Changing the event dispatch model or the topic-based routing architecture
- Modifying the database schema or migration layer

## User Scenarios

### Framework Developer: Adding a New Bus Option

- **Goal:** Add a new behavioral parameter (e.g., a retry count) to the listener registration API
- **Context:** Implementing a feature request that adds a new option to event handler registration

#### Adding the option to the system

1. **Adds the field to the behavioral options struct**
   - Sees: One struct with all behavioral parameters grouped together
   - Decides: Default value and validation rules
   - Then: The struct's validation catches invalid combinations at construction time

2. **Reads the field in the dispatch engine**
   - Sees: The invocation sub-struct carries the handler; the options sub-struct carries the behavior
   - Decides: Where the new option affects execution (dispatch, rate limiting, or timeout)
   - Then: One additional read site in the dispatch path

3. **Verifies existing tests pass**
   - Sees: All existing tests pass without modification because the new field has a default
   - Then: Writes targeted tests for the new option's behavior

### App Developer: Registering an Event Handler

- **Goal:** Register a state change handler with debounce and await its registration
- **Context:** Writing a hassette automation that needs deterministic initialization ordering

#### Registering and awaiting readiness

1. **Calls the registration method with behavioral options**
   - Sees: The same public API as before — keyword arguments for topic, handler, and options
   - Then: Receives a subscription object with a registration completion signal

2. **Awaits the registration signal**
   - Sees: The subscription object exposes a completion signal that resolves when persistence is confirmed
   - Decides: Whether to wait for persistence or proceed immediately
   - Then: Continues initialization knowing the handler is fully registered

### Framework Developer: Working with Duration Listeners

- **Goal:** Modify the duration-hold behavior (e.g., add a grace period for re-entry)
- **Context:** Extending the timer feature without scattering changes across multiple files

#### Modifying duration behavior

1. **Adds configuration to the duration struct**
   - Sees: All duration-related fields in one place, including the timer lifecycle
   - Decides: New field value and validation
   - Then: The struct validates its own constraints

2. **Updates the timer logic**
   - Sees: The timer is owned by the duration struct, not wired externally
   - Decides: How the new configuration affects the timer
   - Then: Changes are localized to the duration struct and the service orchestration method

### Framework Developer: Hitting a Validation Error

- **Goal:** Understand why listener construction failed after passing conflicting sub-structs
- **Context:** Building a new convenience method that composes sub-structs incorrectly

#### Passing conflicting configuration

1. **Calls the factory method with a duration config and debounce in options**
   - Sees: A validation error identifying the conflict ("duration and debounce are mutually exclusive")
   - Decides: Whether to remove debounce from options or remove the duration config
   - Then: Adjusts the sub-struct and retries — no partial construction occurred

2. **Calls attach_timer() on a duration config that already has a timer**
   - Sees: An assertion error ("timer already attached — call cancel() before re-attaching")
   - Decides: Whether the re-attachment is intentional (cancel first) or a bug (fix the call site)
   - Then: The existing timer is not silently replaced

## Functional Requirements

- **FR#1** A listener identity struct groups ownership and telemetry fields (owner, app key, instance index, name, source tier, handler name, source location) into a single construct
- **FR#2** A behavioral options struct groups execution parameters (once, debounce, throttle, timeout, timeout disabled, priority) into a single construct with self-contained validation
- **FR#3** A handler invoker struct groups the handler callable, async wrapper, parameter injector, keyword arguments, error handler, rate limiter, and once-guard into a single construct that owns the dispatch and invocation methods
- **FR#4** A duration configuration struct groups duration-hold fields (duration, entity ID, attribute listener flag, hold predicate, immediate flag) and owns the timer lifecycle via an explicit attachment method
- **FR#5** The listener data structure composes these four sub-structs plus routing fields (topic, predicate) and minimal runtime state (cancelled flag, database ID), reducing total fields from 35 to 10
- **FR#6** The factory method accepts both individual keyword arguments (backward compatibility) and the new sub-structs, constructing sub-structs internally when individual arguments are provided
- **FR#7** The public registration method exposes only user-facing parameters; internal parameters (attribute listener flag, hold predicates, entity ID) are accessible only through a private registration method
- **FR#8** The subscription object exposes a completion signal that resolves when the handler's database persistence attempt is complete
- **FR#9** The event router is a standalone module with no dependencies on the service layer
- **FR#10** A dedicated factory method on the listener creates framework cancel-listeners with sensible defaults, replacing the direct construction in the service layer
- **FR#11** The convenience method predicate list is not modified in place; a new list is created for each registration call
- **FR#12** Top-level imports replace function-body imports in the accessor module

## Edge Cases

- **Backward-compatible construction:** Tests using the factory method with individual keyword arguments continue working without modification. The factory detects whether sub-structs or individual arguments were passed and constructs accordingly.
- **Duration config without timer:** A duration configuration struct exists with declarative fields before the timer is attached. Dispatch must assert the timer is present — the two-phase construction becomes an explicit attach step rather than a silent field mutation.
- **Cancel-listener identity:** The cancel-listener factory produces a listener with `source_tier=framework` and the main listener's owner ID. The identity struct is constructed inline with framework defaults.
- **Registration task for cancel-listeners:** Cancel-listeners skip database registration. Their subscription receives an already-resolved completion signal (a future resolved with None).
- **Rate limiter ownership:** The rate limiter is constructed from options (debounce/throttle) during factory method execution and stored on the handler invoker, not on the options struct. The options struct is declarative; the invoker is the runtime execution context.
- **Cross-concern validation:** Duration + debounce incompatibility validation spans the duration config and options structs. This validation lives in the factory method, which has access to both structs.
- **Router lock acquisition:** The router extraction does not change the locking model. The fair async reentrant lock stays as-is; optimizing lock acquisition (merging 3 calls per state_changed into 1) is a separate concern.
- **Subscription.registration_task type:** `asyncio.Future[None]` (not `Task`) because future work (multi-entity subscriptions) will use `asyncio.gather()` which returns a Future. `Task` subclasses `Future`, so single-listener paths satisfy the type.
- **Empty options:** `ListenerOptions()` with all defaults is a valid configuration — the most common case for simple listeners.
- **Concurrent registration with same name:** Two `Bus._on_internal()` calls racing with the same `name` value. `_on_internal()` is synchronous between the key check and the key insertion (no `await` between check-and-set). Since all Bus operations run on the event loop thread, two concurrent calls for the same name cannot interleave. This invariant is preserved by the refactor — `_on_internal()` follows the same synchronous check-and-set pattern as `on()` today.
- **attach_timer() raises:** If `DurationTimer` construction fails inside `attach_timer()` (e.g., event loop is closing), the exception propagates through `BusService.add_listener()` to `Bus.on()` and then to the caller (typically `on_initialize()`). No `Task` is spawned, no `Subscription` is constructed. This is the same behavior as today when DurationTimer construction fails inline — the refactor does not change the failure surface, only the location of construction. The `_duration_timers_active` counter is not incremented because it is guarded by the try/except already applied (Finding 6).
- **Cancel-subscription factory fails:** If `create_cancel_sub()` raises during `DurationTimer.start()`, the timer catches `CancelledError` but other exceptions propagate. The timer's `_cancel_sub` remains `None`, so no orphaned cancel-listener exists. The duration timer is effectively dead — subsequent state changes won't cancel it (no cancel listener), so it fires after the full duration regardless. This is acceptable degraded behavior: the handler fires late rather than silently dropping.

## Acceptance Criteria

- **AC#1** Adding a new behavioral option to the listener requires changes in exactly two places: the options struct and the implementation that reads it (FR#2)
- **AC#2** The listener data structure has 10 or fewer direct fields, composing four sub-structs for the remaining concerns (FR#5)
- **AC#3** All existing bus unit and integration tests pass after updating two categories of call sites: (a) factory construction signatures (~57 test sites + 5 production sites, backward-compatible via kwargs) and (b) field-access paths (~32 sites where `listener.field` becomes `listener.sub_struct.field`). No test *logic* changes — only field access paths are updated (FR#6)
- **AC#4** The handler invoker struct can be instantiated and tested independently of the full listener — `HandlerInvoker.create()` requires a `task_bucket` (provide `MagicMock()` for unit tests) (FR#3)
- **AC#5** The duration configuration struct validates its own constraints (duration > 0, entity_id required) at construction time without depending on external validation (FR#4)
- **AC#6** The public registration method's signature contains no parameters named `is_attribute_listener`, `hold_preds`, or `entity_id` (FR#7)
- **AC#7** `await subscription.registration_task` resolves after the listener's database registration attempt is complete; the signal resolves with `None` regardless of whether persistence succeeded or failed — it is a completion signal, not a success signal. Callers check `subscription.listener.db_id is not None` to detect persistence failures (FR#8)
- **AC#8** The router module has zero imports from the service layer or the core package (FR#9)
- **AC#9** The cancel-listener factory produces a functioning listener without requiring a Bus instance (FR#10)
- **AC#10** A parity test asserts that all fields on the database registration DTO have a corresponding source field on the listener identity struct or options struct (FR#1, FR#2)
- **AC#11** The convenience method predicate list passed to the registration method is not mutated (FR#11)
- **AC#12** The accessor module contains no function-body imports (FR#12)

## Key Constraints

- `if_exists` is NOT part of this work — it is a Bus-level registration policy that builds on top of the decomposed structure (tracked in #779)
- `ListenerOptions` groups behavioral parameters only — structural parameters (owner, topic, handler) and duration parameters remain on their respective sub-structs
- The `Options` TypedDict in `bus.py` remains as the user-facing kwargs spec for the public API; `ListenerOptions` is the internal dataclass. These are intentionally separate: TypedDict for kwargs unpacking, dataclass for structured passing
- `error_handler` and `_app_error_handler_resolver` live on `HandlerInvoker`, not on `ListenerOptions` — they are invocation concerns, not behavioral timing parameters
- Duration timer attachment stays in BusService (it needs task_bucket and the cancel-subscription factory), but the mutation target changes from `listener._duration_timer` to `listener.duration_config.attach_timer(...)`
- Cross-concern validation (duration + debounce incompatibility) lives in `Listener.create()`, not on any single sub-struct, because it spans two sub-structs

## Dependencies and Assumptions

- Python 3.11+ `@dataclass(slots=True)` composition works correctly for nested dataclasses (verified in research)
- `asyncio.Task` subclasses `asyncio.Future` (verified — both satisfy `Future[None]` type annotation)
- No circular import exists between `hassette.event_handling.accessors` and `hassette.events` (verified in research — the lazy imports are historical artifacts)
- The `FairAsyncRLock` package is an existing dependency (used by Router, no new dependencies needed)
- All 57 test call sites and 5 production call sites for `Listener.create()` are within this repository (no external consumers)
- Spec 058 issues #529 (list entity IDs) and #779 (if_exists) will be implemented as follow-on work on the decomposed structure

## Architecture

### Sub-struct definitions

All new structs live in `src/hassette/bus/listeners.py` alongside the existing `Listener` and `Subscription` classes.

**ListenerIdentity** — `@dataclass(slots=True)`:
- `owner_id: str`
- `app_key: str` (default `""`)
- `instance_index: int` (default `0`)
- `name: str | None` (default `None`)
- `source_tier: SourceTier` (default `"app"`)
- `handler_name: str`
- `handler_short_name: str`
- `source_location: str` (default `""`)
- `registration_source: str` (default `""`)

No factory method needed — direct construction. `source_location` and `registration_source` are set at construction time by `Bus.on()` (capturing the call site before constructing the struct), eliminating the post-construction mutation that exists today.

**ListenerOptions** — `@dataclass(slots=True)`:
- `once: bool` (default `False`)
- `debounce: float | None` (default `None`)
- `throttle: float | None` (default `None`)
- `timeout: float | None` (default `None`)
- `timeout_disabled: bool` (default `False`)
- `priority: int` (default `0`)

Validation in `__post_init__`: mutual exclusivity of debounce/throttle, non-negative values. Raises `ValueError` on invalid combinations. This replaces the subset of `Listener._validate_options()` that covers these fields.

**HandlerInvoker** — `@dataclass(slots=True)`:
- `orig_handler: HandlerType`
- `_async_handler: AsyncHandlerType`
- `_injector: ParameterInjector`
- `kwargs: Mapping[str, Any] | None`
- `error_handler: BusErrorHandlerType | None`
- `_app_error_handler_resolver: Callable[[], BusErrorHandlerType | None] | None`
- `_rate_limiter: RateLimiter | None`
- `once: bool` (default `False`)
- `_fired: bool` (default `False`, `init=False`)

The `once` field is copied from `ListenerOptions` at creation time. It drives the once-guard in `dispatch()` — keeping it here avoids threading a parameter through every dispatch call and makes HandlerInvoker independently testable (AC#4).

Methods moved from `Listener`:
- `dispatch(invoke_fn)` — once-guard + rate limiter delegation
- `invoke(event)` — parameter injection + async handler call
- `mark_fired()` — sets `_fired` flag
- `set_app_error_handler_resolver(resolver)` — sets the app-level error handler closure

Factory classmethod `create(task_bucket, handler, kwargs, options, ...)` constructs the async wrapper, injector, and rate limiter from the handler and options. Copies `options.once` to `self.once`. This replaces the handler-related construction logic currently in `Listener.create()`.

**DurationConfig** — `@dataclass(slots=True)`:
- `duration: float`
- `immediate: bool` (default `False`)
- `entity_id: str`
- `is_attribute_listener: bool` (default `False`)
- `hold_predicate: Predicate | None` (default `None`)
- `_timer: DurationTimer | None` (default `None`, `init=False`)

Validation in `__post_init__`: `duration > 0`, `entity_id` is non-empty. Raises `ValueError`.

`attach_timer(task_bucket, create_cancel_sub, on_cancel)` method constructs `DurationTimer` and stores it in `_timer`. This replaces the direct `listener._duration_timer = DurationTimer(...)` assignment in `BusService.add_listener()`. BusService calls `listener.duration_config.attach_timer(...)` during registration, passing the cancel-subscription factory and the on_cancel callback. Counter ownership: `_duration_timers_active` is exclusively managed by BusService — `attach_timer()` constructs and stores the timer reference only; `start()` and all counter bookkeeping remain in BusService.

`@property timer -> DurationTimer` accessor that asserts `_timer is not None` — converts the silent misconfiguration (missing timer) into an immediate assertion error with a clear message.

### Composed Listener

`Listener` — `@dataclass(slots=True)`:
- `listener_id: int` (auto-assigned via `field(default_factory=next_id, init=False)`)
- `topic: str`
- `predicate: Predicate | None`
- `identity: ListenerIdentity`
- `invoker: HandlerInvoker`
- `options: ListenerOptions`
- `duration_config: DurationConfig | None`
- `_cancelled: bool` (default `False`, `init=False`)
- `db_id: int | None` (default `None`, `init=False`)
- `logger: Logger`

Methods remaining on `Listener`:
- `matches(event)` — predicate evaluation (routing concern, stays on Listener)
- `cancel()` — sets `_cancelled`, calls `self.invoker.mark_fired()` to prevent handler invocation on any in-flight dispatch task, cancels rate limiter and duration timer
- `mark_registered(db_id)` — sets `db_id` post-persistence
- `is_cancelled` property

Methods moved to sub-structs:
- `dispatch()` → `HandlerInvoker.dispatch()`
- `invoke()` → `HandlerInvoker.invoke()`
- `mark_fired()` → `HandlerInvoker.mark_fired()`
- `set_app_error_handler_resolver()` → `HandlerInvoker.set_app_error_handler_resolver()`

`Listener.create()` — updated factory method:
- Accepts both individual kwargs (backward compat for 57 test + 5 production call sites) and sub-struct parameters (`identity: ListenerIdentity | None`, `options: ListenerOptions | None`, `invoker: HandlerInvoker | None`, `duration_config: DurationConfig | None`)
- When sub-structs are provided, uses them directly
- When individual kwargs are provided, constructs sub-structs internally
- Cross-concern validation (duration + debounce incompatibility, once + debounce) lives here since it spans sub-structs
- Source location is captured before construction and passed to `ListenerIdentity`, eliminating post-construction mutation

`Listener.create_cancel_listener()` — new dedicated factory:
- Accepts: `task_bucket`, `owner_id`, `topic`, `handler`, `entity_id`, `predicate`
- Constructs identity with `source_tier="framework"` and empty source location
- Constructs minimal invoker (no rate limiter, no error handler)
- Constructs default options (all defaults)
- No duration config
- Returns a `Listener` ready for Router insertion

### Subscription with registration_task

`Subscription` gains `registration_task: asyncio.Future[None] | None` (default `None`):
- Constructed in `Bus.on()` from the return value of `self.add_listener(listener)` (an `asyncio.Task`)
- For cancel-listener subscriptions in `bus_service.py:204`: pass an already-resolved `Future` since cancel listeners skip DB registration
- Default `None` preserves backward compatibility for any external `Subscription(listener, unsubscribe)` construction sites
- `await subscription.registration_task` resolves when the DB persistence attempt completes — it is a completion signal, not a success signal. The existing error-swallowing behavior in `_register_then_add_route()` is preserved; callers check `listener.db_id is not None` to detect persistence failures

### Bus.on() / _on_internal() split

`Bus.on()` (public) signature:
- `topic`, `handler`, `where`, `kwargs`
- `once`, `debounce`, `throttle`, `timeout`, `timeout_disabled`, `name`, `on_error`
- No `is_attribute_listener`, `hold_preds`, `entity_id`, `immediate`, `duration`, `priority`
- `priority` remains a Bus-level property (`self.priority`), sourced when constructing `ListenerOptions` internally — not exposed as a per-registration parameter

`Bus._on_internal()` (private) signature:
- All public parameters plus `duration_config: DurationConfig | None`, `entity_id: str | None`, `is_attribute_listener: bool`, `hold_preds: list[Predicate] | None`
- Called by `on_state_change()`, `on_attribute_change()`, and `on()` (which passes `duration_config=None`)

`on_state_change()` and `on_attribute_change()` build a `DurationConfig` when `duration` is provided and call `_on_internal()`.

### Router extraction

Move `Router` class from `src/hassette/core/bus_service.py:894-1066` to `src/hassette/bus/router.py`.

Dependencies (all already available):
- `FairAsyncRLock` — external package
- `Listener` type — from `hassette.bus.listeners` (under `TYPE_CHECKING` guard)
- `GLOB_CHARS` — from `hassette.utils.glob_utils`
- `fnmatch` — stdlib
- `defaultdict` — stdlib

No interface changes. `BusService` imports `from hassette.bus.router import Router`.

Router is not exported from `bus/__init__.py` — it remains internal (only BusService uses it).

### Bus consumer updates

`Bus._listener_natural_key()`:
- `listener.app_key` becomes `listener.identity.app_key`
- `listener.instance_index` becomes `listener.identity.instance_index`
- `listener.handler_name` becomes `listener.identity.handler_name`
- `listener.name` becomes `listener.identity.name`

`Bus.add_listener()` collision path:
- `listener.once` becomes `listener.options.once`
- `listener.handler_name` becomes `listener.identity.handler_name`

### BusService consumer updates

`BusService.add_listener()`:
- Duration timer wiring changes from `listener._duration_timer = DurationTimer(...)` to `listener.duration_config.attach_timer(task_bucket, make_cancel_sub, on_cancel)`
- Condition changes from `if listener.duration is not None and listener.entity_id` to `if listener.duration_config is not None`

`BusService._dispatch()`:
- Duration path check changes from `if listener.duration is not None and listener._duration_timer is not None` to `if listener.duration_config is not None` plus assertion on `duration_config.timer`
- Handler dispatch changes from `listener.dispatch(invoke_fn)` to `listener.invoker.dispatch(invoke_fn)`
- `listener.once` becomes `listener.options.once`

`BusService._immediate_fire_task()`:
- `listener.duration` becomes `listener.duration_config.duration`
- `listener.is_attribute_listener` becomes `listener.duration_config.is_attribute_listener`
- `listener.entity_id` becomes `listener.duration_config.entity_id`
- `listener._duration_timer` becomes `listener.duration_config.timer`

`BusService._register_then_add_route()`:
- `ListenerRegistration` construction reads from `listener.identity.*` for identity fields, `listener.options.*` for behavioral fields

`BusService._make_tracked_invoke_fn()`:
- `listener.timeout_disabled` becomes `listener.options.timeout_disabled`
- `listener.timeout` becomes `listener.options.timeout`
- Error handler resolution stays on `listener.invoker._app_error_handler_resolver`

`BusService._create_cancel_listener()`:
- Replaced by `Listener.create_cancel_listener()` — BusService calls the factory and adds the route

`CommandExecutor._execute_handler()`:
- `cmd.listener.app_key` becomes `cmd.listener.identity.app_key`
- `cmd.listener.instance_index` becomes `cmd.listener.identity.instance_index`
- `cmd.listener.invoke(cmd.event)` becomes `cmd.listener.invoker.invoke(cmd.event)`
- `cmd.listener.error_handler` becomes `cmd.listener.invoker.error_handler`

### Fixes included

**hold_preds mutation** (`bus.py:362-363`): Replace `hold_preds.append(normalized_where)` with `hold_preds = [*hold_preds, normalized_where]`.

**Lazy imports** (`accessors.py:221,239`): Move `from hassette.events import RawStateChangeEvent, CallServiceEvent` to module top level. No circular import exists (verified).

**Duration timer counter guard** (`bus_service.py`): Already applied — try/except around `_duration_timers_active += 1` / `start()` pairs.

### ListenerRegistration parity test

New test asserting that every field on `ListenerRegistration` has a corresponding source on `ListenerIdentity` or `ListenerOptions` (or is explicitly exempted as a computed/runtime field). Follows the pattern in `test_recording_api_protocol_parity.py`.

### Test harness updates

The harness goes through the normal `Bus.on()` → `BusService.add_listener()` path, so most changes are transparent. Specific updates:

- `Subscription` constructor gains `registration_task` — handled automatically since harness uses `Bus.on()`
- Mock executor's `_stub_execute` accesses `cmd.listener.invoker.error_handler` (was `cmd.listener.error_handler`)
- Mock executor's handler invocation uses `cmd.listener.invoker.invoke(cmd.event)` (was `cmd.listener.invoke(cmd.event)`)

## Convention Examples

### Dataclass with slots=True and factory method

**Source:** `src/hassette/bus/listeners.py:36-164` (current Listener — the refactor target)

```python
@dataclass(slots=True)
class Listener:
    """A listener for events with a specific topic and handler."""
    logger: Logger
    listener_id: int = field(default_factory=next_id, init=False)
    owner_id: str
    topic: str
    # ... 22 more fields ...

    @classmethod
    def create(cls, task_bucket, owner_id, topic, handler, ...) -> "Listener":
        cls._validate_options(once=once, debounce=debounce, ...)
        # ... construction logic
        return listener
```

DON'T: 35 flat fields with a factory that takes 22 parameters.

### Clean sub-struct pattern

**Source:** `src/hassette/event_handling/dependencies.py:85-100`

```python
@dataclass(slots=True, frozen=True)
class AnnotationDetails(Generic[T]):
    """Details about an annotation used for dependency injection."""
    extractor: Callable[[T], Any]
    converter: Callable[[Any, Any], Any] | None = None

    def __post_init__(self):
        if not callable(self.extractor):
            raise TypeError("extractor must be a callable")
```

DO: Small, immutable sub-structs with validation in `__post_init__`.

### Collision detection pattern (scheduler model)

**Source:** `src/hassette/scheduler/scheduler.py:164-208`

```python
existing = self._jobs_by_name.get(job.name)
if existing is not None:
    if if_exists == "replace":
        self.cancel_job(existing)
    elif if_exists == "skip" and existing.matches(job):
        return existing
    elif if_exists == "skip":
        changed_fields = existing.diff_fields(job)
        raise ValueError(f"A job named '{job.name}' already exists but its configuration has changed ...")
    else:
        raise ValueError(...)
```

DO: Three-way collision resolution with logical config comparison via `matches()` / `diff_fields()`. This is the model for future `if_exists` on the bus (spec 058 #779).

### Subscription dataclass (current — extending)

**Source:** `src/hassette/bus/listeners.py:378-395`

```python
@dataclass(slots=True)
class Subscription:
    listener: Listener
    unsubscribe: "Callable[[], None]"

    def cancel(self) -> None:
        self.unsubscribe()
```

DO: Simple composition with one method. We're adding `registration_task: asyncio.Future[None]` to this struct.

## Alternatives Considered

**Incremental decomposition (ListenerOptions first, rest later):** The research brief recommends this. Rejected because partial decomposition creates a mixed model (some fields in sub-structs, some flat on Listener) that is worse than either fully flat or fully composed. With the full decomposition scoped to this PR, the codebase transitions atomically to the clean state.

**Protocols for sub-struct interfaces:** Using `typing.Protocol` for HandlerInvoker and DurationConfig to enable lightweight test fakes. Rejected per project convention (`feedback_no_protocols_for_mixins.md`) — protocols are over-engineering for this use case. Direct dataclass composition is sufficient.

**Duration timer construction inside DurationConfig.__init__:** Rejected because the timer requires a cancel-subscription factory and task_bucket from BusService. Moving construction into `__init__` would require passing service-layer dependencies into a data struct. The `attach_timer()` method is the right compromise: DurationConfig owns the timer reference, BusService provides the dependencies.

**Removing Listener.create() in favor of direct sub-struct construction:** Rejected because the factory provides cross-concern validation (duration + debounce incompatibility) and captures source location. Direct construction would scatter this logic across callers.

## Test Strategy

- **Sub-struct unit tests:** Each of `ListenerOptions`, `HandlerInvoker`, `DurationConfig`, and `ListenerIdentity` gets independent unit tests verifying construction, validation, and (where applicable) methods. These are new tests that didn't exist before because the sub-structs didn't exist.
- **Listener.create() regression:** All 57 existing test call sites (plus 5 production call sites) continue working via backward-compatible keyword arguments. No test logic changes — only internal construction paths change.
- **Registration task tests:** Test that `Subscription.registration_task` is a `Future`, is awaitable, and that `sub.cancel()` works independently of task completion. Test that cancel-listener subscriptions receive an already-resolved future.
- **Router extraction:** Existing bus_service tests exercise the router implicitly. Add a small focused test that imports `from hassette.bus.router import Router` and verifies basic add/get/remove operations.
- **Parity test:** New test asserting `ListenerRegistration` fields map to `ListenerIdentity` or `ListenerOptions` fields, with explicit exemption list for computed fields.
- **Cancel-listener factory:** Test `Listener.create_cancel_listener()` produces a functioning listener with framework source tier and correct identity.
- **Harness smoke test:** Run the existing harness-based integration tests to verify no breakage in the mock executor path.

## Documentation Updates

- `docs/pages/core-concepts/bus/handlers.md` — Add `registration_task` to subscription reference
- Docstrings on all new structs (`ListenerIdentity`, `ListenerOptions`, `HandlerInvoker`, `DurationConfig`)
- Update `Bus.on()` docstring to reflect the public-only parameter set
- `CLAUDE.md` Architecture section — update Bus description to mention sub-struct composition

## Impact

**Files modified:**
- `src/hassette/bus/listeners.py` — ListenerIdentity, ListenerOptions, HandlerInvoker, DurationConfig structs; Listener decomposition; Subscription.registration_task; Listener.create_cancel_listener()
- `src/hassette/bus/bus.py` — Bus.on()/_on_internal() split; Options TypedDict update; hold_preds mutation fix
- `src/hassette/bus/router.py` — NEW: Router class extracted from bus_service.py
- `src/hassette/bus/__init__.py` — Export new structs
- `src/hassette/core/bus_service.py` — Consumer updates (duration_config, invoker, options, identity); Router import; cancel-listener factory delegation
- `src/hassette/core/command_executor.py` — Field access updates (identity.app_key, identity.instance_index, invoker.invoke, invoker.error_handler)
- `src/hassette/event_handling/accessors.py` — Lazy import fix
- `src/hassette/test_utils/harness.py` — Mock executor field access updates (invoker.error_handler, invoker.invoke)
- ~10 test files (57 call sites) — Call signature updates if opting into sub-struct parameters
- 1-2 doc pages

**Blast radius:** Moderate-to-large. All changes are within the bus module and its consumers. The public API (`Bus.on()`, `on_state_change()`, etc.) is restructured but the external contract (what users pass) is preserved via backward compatibility. The internal contract (what BusService reads from Listener) changes significantly.

## Open Questions

None — all design decisions resolved during discovery and architecture review.
