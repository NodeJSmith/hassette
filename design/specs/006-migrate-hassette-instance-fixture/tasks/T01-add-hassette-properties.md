---
task_id: "T01"
title: "Add 3 public properties and stream cleanup helper"
status: "planned"
depends_on: []
implements: ["FR#1", "FR#2", "FR#3", "FR#7"]
---

## Summary
Add 3 new public property accessors to the `Hassette` class (`session_manager`, `event_stream_service`, `bus`) following the existing property pattern. Add a test-only `cleanup_hassette_streams()` helper function in `tests/integration/conftest.py` that replaces the inline stream teardown logic in the `hassette_instance` fixture. Update the fixture to use the helper.

## Target Files
- modify: `src/hassette/core/core.py`
- modify: `tests/integration/conftest.py`

## Prompt
Add 3 public property accessors to `src/hassette/core/core.py` in the existing property block. Each follows the exact pattern of `database_service` (line 349-354):

1. `session_manager` — returns `SessionManager`, raises `_service_not_wired_error("SessionManager")` if None. Docstring: `"""SessionManager instance for session lifecycle management."""`
2. `event_stream_service` — returns `EventStreamService`, raises `_service_not_wired_error("EventStreamService")` if None. Docstring: `"""EventStreamService instance for internal event stream lifecycle."""`
3. `bus` — returns `Bus`, raises `_service_not_wired_error("Bus")` if None. Docstring: `"""Bus instance for internal event pub/sub."""`

Place them logically near related services in the property block. The import types (`SessionManager`, `EventStreamService`, `Bus`) are already imported in `core.py` — verify before adding.

Then in `tests/integration/conftest.py`:

1. Add a `cleanup_hassette_streams()` async helper function above the `hassette_instance` fixture:

```python
async def cleanup_hassette_streams(instance: Hassette) -> None:
    """Close event streams and the bus service's cloned receive stream.

    Both underlying close operations are idempotent, so no pre-check is needed —
    suppress(Exception) alone handles the not-yet-wired and already-closed cases.
    """
    with suppress(Exception):
        await instance._event_stream_service.close_streams()
    with suppress(Exception):
        await instance._bus_service.stream.aclose()
```

2. Replace the `hassette_instance` fixture's `finally:` block (lines 32-38) to use the helper:

```python
    finally:
        await cleanup_hassette_streams(instance)
```

## Focus
- `core.py` already has `_service_not_wired_error()` at line 55 and 12+ property accessors using it. Match the pattern exactly.
- The `_bus` slot is declared at `core.py:117` and set at `core.py:211`. Note: `core.py:210-215` has a comment "# internal instances" for `_bus`/`_scheduler` vs "# public instances" for `_states`/`_api`. The `bus` property is being added intentionally despite this comment — the comment describes the original intent, not a binding constraint. Do not modify the comment.
- `suppress` is already imported in `tests/integration/conftest.py` (line 6).
- The cleanup helper deliberately keeps private-attr access (`instance._event_stream_service`, `instance._bus_service`) because this is test infrastructure, not production code. The helper consolidates the access into one function.

## Verify
- [ ] FR#1: `Hassette().session_manager` raises `RuntimeError` before `wire_services()`; returns `SessionManager` after
- [ ] FR#2: `Hassette().event_stream_service` raises `RuntimeError` before `wire_services()`; returns `EventStreamService` after
- [ ] FR#3: `Hassette().bus` raises `RuntimeError` before `wire_services()`; returns `Bus` after
- [ ] FR#7: `hassette_instance` fixture teardown calls `cleanup_hassette_streams()` — no inline private-attr access in the fixture's `finally:` block
