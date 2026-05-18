# Context: Listener Decomposition

## Problem & Motivation
The `Listener` dataclass in `src/hassette/bus/listeners.py` has grown to 26 fields serving four distinct consumers: Router (topic matching), dispatch engine (handler invocation), DB layer (registration telemetry), and user code (subscription lifecycle). Adding a new behavioral option threads through five layers. Duration-hold behavior is scattered across four files with implicit invariants — the timer is constructed in BusService and attached via private field mutation. The double-guard in dispatch (`duration is not None and _duration_timer is not None`) reveals untrusted invariants. Each new bus feature adds to the sprawl.

## Visual Artifacts
None.

## Key Decisions
1. **Four sub-structs, not three**: ListenerIdentity (ownership/telemetry), ListenerOptions (behavioral timing), HandlerInvoker (handler execution/dispatch), DurationConfig (duration-hold + timer). Identity was included to make ListenerRegistration parity testable.
2. **Listener remains the composed object**: 10 fields, thin composition layer. Not replaced; just decomposed.
3. **Backward-compatible Listener.create()**: Accepts both kwargs (58 existing test call sites) and sub-struct parameters. Constructs sub-structs internally when kwargs are provided.
4. **DurationConfig.attach_timer() instead of __init__**: Timer construction requires BusService dependencies (task_bucket, cancel-sub factory). attach_timer() is the explicit wiring step; BusService calls it during registration. Counter ownership stays in BusService.
5. **Bus.on() / _on_internal() split**: Public on() drops internal params (is_attribute_listener, hold_preds, entity_id, immediate, duration, priority). Private _on_internal() carries the full set.
6. **registration_task is a completion signal, not a success signal**: Resolves with None regardless of DB outcome. Callers check db_id for persistence status. Matches existing error-swallowing behavior.
7. **Listener.create_cancel_listener() dedicated factory**: Replaces direct Listener.create() call in BusService._create_cancel_listener(). Framework source tier, no Bus instance needed.
8. **priority stays Bus-level**: Not exposed as per-registration param. Sourced from self.priority internally.

## Constraints & Anti-Patterns
- Do NOT implement if_exists (#779) or list entity IDs (#529) — those build on top of this
- Do NOT modify the database schema or migrations
- Do NOT change the event dispatch model or routing architecture
- Do NOT add backpressure/saturation fixes (separate work)
- ListenerOptions groups behavioral parameters ONLY — not error_handler, not structural params
- error_handler and _app_error_handler_resolver live on HandlerInvoker, not ListenerOptions
- The Options TypedDict in bus.py remains separate from ListenerOptions dataclass (TypedDict for kwargs, dataclass for structured passing)
- Cross-concern validation (duration + debounce) lives in Listener.create(), not any single sub-struct
- _duration_timers_active counter is exclusively managed by BusService — not by DurationConfig.attach_timer()

## Design Doc References
- ## Architecture — sub-struct definitions, composed Listener, consumer updates, fixes
- ## Edge Cases — backward compat, duration config without timer, cancel-listener identity, concurrent registration
- ## Key Constraints — if_exists excluded, Options TypedDict vs ListenerOptions, error_handler placement
- ## Convention Examples — AnnotationDetails pattern, scheduler collision detection, current Listener (anti-pattern)
- ## Test Strategy — sub-struct unit tests, regression, parity test, Router extraction test

## Convention Examples
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

DO: Simple composition with one method.
