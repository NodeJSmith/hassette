---
task_id: "T01"
title: "Define ListenerIdentity, ListenerOptions, HandlerInvoker, DurationConfig"
status: "planned"
depends_on: []
implements: ["FR#1", "FR#2", "FR#3", "FR#4", "FR#5", "AC#1", "AC#2", "AC#4", "AC#5"]
---

## Summary
Create the four new sub-struct dataclasses in `src/hassette/bus/listeners.py` and refactor the existing `Listener` class to compose them. Move `dispatch()`, `invoke()`, and `mark_fired()` methods from `Listener` to `HandlerInvoker`. Update `Listener.create()` to construct sub-structs internally while preserving backward compatibility for existing kwargs callers. Add `create_cancel_listener()` dedicated factory. Update `Listener.cancel()` to also call `self.invoker.mark_fired()`. Write unit tests for each sub-struct independently.

## Prompt
Read the design doc at `design/specs/059-listener-decomposition/design.md`, sections "Sub-struct definitions" and "Composed Listener".

**Step 1: Create sub-structs** in `src/hassette/bus/listeners.py` (add above the existing `Listener` class):

- `ListenerIdentity` — `@dataclass(slots=True)` with 9 fields: `owner_id`, `app_key` (default ""), `instance_index` (default 0), `name` (default None), `source_tier` (default "app"), `handler_name`, `handler_short_name`, `source_location` (default ""), `registration_source` (default ""). No factory needed.

- `ListenerOptions` — `@dataclass(slots=True)` with 6 fields: `once` (default False), `debounce` (default None), `throttle` (default None), `timeout` (default None), `timeout_disabled` (default False), `priority` (default 0). Add `__post_init__` validation: mutual exclusivity of debounce/throttle, non-negative values. Move the relevant validation from `Listener._validate_options()`.

- `HandlerInvoker` — `@dataclass(slots=True)` with 8 fields: `orig_handler`, `_async_handler`, `_injector`, `kwargs`, `error_handler`, `_app_error_handler_resolver`, `_rate_limiter`, `_fired` (default False, init=False). Move `dispatch()`, `invoke()`, `mark_fired()` methods from Listener. Add `HandlerInvoker.create(task_bucket, handler, kwargs, options, ...)` classmethod that constructs async wrapper, injector, and rate limiter.

- `DurationConfig` — `@dataclass(slots=True)` with 6 fields: `duration`, `immediate` (default False), `entity_id`, `is_attribute_listener` (default False), `hold_predicate` (default None), `_timer` (default None, init=False). Add `__post_init__` validation: duration > 0, entity_id non-empty. Add `attach_timer(task_bucket, create_cancel_sub, on_cancel)` method. Add `@property timer` that asserts `_timer is not None`.

**Step 2: Refactor Listener** to compose the four sub-structs. The new Listener has 10 fields: `listener_id`, `topic`, `predicate`, `identity`, `invoker`, `options`, `duration_config`, `_cancelled`, `db_id`, `logger`. Remove all flat fields that moved to sub-structs. Keep `matches()`, `cancel()`, `mark_registered()`, `is_cancelled`. Update `cancel()` to call `self.invoker.mark_fired()` in addition to existing cleanup.

**Step 3: Update Listener.create()** to accept both individual kwargs and sub-struct parameters. When kwargs are provided, construct sub-structs internally. Cross-concern validation (duration + debounce) stays here. Source location is captured before construction and passed to ListenerIdentity. The factory must still work with all 58 existing test call sites unchanged.

**Step 4: Add Listener.create_cancel_listener()** — dedicated factory for framework cancel-listeners. Accepts task_bucket, owner_id, topic, handler, entity_id, predicate. Constructs identity with source_tier="framework". No rate limiter, no error handler, no duration config.

**Step 5: Update exports** in `src/hassette/bus/__init__.py` — add ListenerIdentity, ListenerOptions, HandlerInvoker, DurationConfig to `__all__`.

**Step 6: Write unit tests** for each sub-struct:
- `tests/unit/bus/test_listener_identity.py` — construction, defaults
- `tests/unit/bus/test_listener_options.py` — construction, validation (debounce/throttle exclusivity, non-negative)
- `tests/unit/bus/test_handler_invoker.py` — construction via create(), dispatch() with once-guard, invoke() with injection, mark_fired()
- `tests/unit/bus/test_duration_config.py` — construction, validation (duration > 0, entity_id required), attach_timer(), timer property assertion
- Update `tests/unit/bus/test_listeners.py` if Listener-level tests need path adjustments

## Focus
- `listeners.py` is currently 410 lines. The sub-structs add ~200 lines but the field removal from Listener offsets some of it.
- `_validate_options()` must be split: debounce/throttle/once validation moves to ListenerOptions.__post_init__; duration+debounce cross-validation stays in Listener.create().
- The `_rate_limiter` is constructed in Listener.create() today (lines 368-373). After refactor it's constructed in HandlerInvoker.create() from the options.
- `_duration_timer` is currently `field(default=None, init=False)` with a comment about external wiring. DurationConfig._timer follows the same pattern but with the explicit attach_timer() method.
- The logger field stays on Listener (not on sub-structs). HandlerInvoker methods that need logging should accept a logger parameter or use module-level logging.
- `Listener.create()` backward compat: detect whether sub-structs were passed by checking `identity is not None`. If None, construct from kwargs.

## Verify
- [ ] FR#1: ListenerIdentity groups all 9 identity/telemetry fields into a single `@dataclass(slots=True)`
- [ ] FR#2: ListenerOptions groups all 6 behavioral fields with __post_init__ validation for mutual exclusivity and non-negative values
- [ ] FR#3: HandlerInvoker groups handler callable, async wrapper, injector, kwargs, error handler, rate limiter, and once-guard; owns dispatch(), invoke(), mark_fired()
- [ ] FR#4: DurationConfig groups 5 duration-hold fields plus _timer; attach_timer() constructs and stores DurationTimer; timer property asserts non-None
- [ ] FR#5: Listener has 10 or fewer direct fields composing four sub-structs
- [ ] AC#1: Adding a mock new option to ListenerOptions requires changes only in ListenerOptions and the dispatch/test that reads it
- [ ] AC#2: Listener field count is 10 or fewer (count the fields in the dataclass definition)
- [ ] AC#4: HandlerInvoker.create() can be called with a MagicMock task_bucket and produces a functional invoker
- [ ] AC#5: DurationConfig(duration=-1, entity_id="x") raises ValueError; DurationConfig(duration=5, entity_id="") raises ValueError
