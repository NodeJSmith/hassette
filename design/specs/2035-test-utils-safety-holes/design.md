# Design: Close Three Safety Holes in hassette.test_utils

**Status:** draft
**Spec:** 2035-test-utils-safety-holes
**Date:** 2026-04-09
**Revision:** 3 (applies findings from two rounds of challenge review)

## Problem

Challenge review of `docs/pages/testing/index.md` surfaced three safety holes in the public `hassette.test_utils` API that produce silent false-green tests or make common code paths untestable. Two rounds of challenge review on this design refined the scope to what's reflected below.

**Release context**: none of the affected `hassette.test_utils` functionality is released yet — we are between v0.24.0 (shipped) and the unreleased v0.25.0. No CHANGELOG update is needed manually; release-please handles CHANGELOG generation automatically from commit messages.

### F2 — `RecordingApi.sync` is a bare `Mock()` (HIGH)

`RecordingApi.__init__` sets `self.sync = Mock()`. Any `api.sync.*` call silently returns another Mock and records nothing — tests for sync code paths pass without actually testing anything.

**Source**: `src/hassette/test_utils/recording_api.py:132`

### F4 — `turn_on`/`turn_off`/`toggle_service` recorded as `call_service` (HIGH)

`RecordingApi.turn_on()` delegates to `call_service()` internally, matching the real `Api` class. All three convenience methods record as `ApiCall(method="call_service", ...)`. A user who writes the natural assertion `assert_called("turn_on", ...)` gets a silent `AssertionError` with no diagnostic path.

**Source**: `src/hassette/test_utils/recording_api.py:155-166`

### F10 — `_drain_task_bucket` doesn't drain the task bucket (CRITICAL)

`AppTestHarness._drain_task_bucket` delegates only to `BusService.await_dispatch_idle`, which waits on bus dispatch tasks only. Handlers that spawn fire-and-forget work via `self.task_bucket.spawn(...)` are not tracked; `RateLimiter._debounced_call` already exercises depth-2 chains (handler→spawned debounce task), so false-idle returns are routine, not edge cases.

**Source**: `src/hassette/test_utils/app_harness.py:718-735`, `src/hassette/core/bus_service.py:413-463`, `src/hassette/bus/rate_limiter.py:113-131`

## Scope

### In Scope

1. **F2 — Hand-written `_RecordingSyncFacade`** with a CI drift-detection test. The facade is a plain class that appends to the parent `RecordingApi`'s `calls` list for write methods and delegates to the state proxy for read methods. A new test asserts that the public write-method name sets of `ApiSyncFacade` and `_RecordingSyncFacade` match — catching drift when `Api` gains a new convenience method.
2. **F4 — Direct-record convenience methods**. `turn_on`/`turn_off`/`toggle_service` append directly to `self.calls` under their own method names, with uniform `str | StrEnum` coercion across all three.
3. **F10 — Iterative drain** with deadline guard, exception surfacing, stability-window delegation, and public `TaskBucket.pending_tasks()` / `BusService.is_dispatch_idle` properties.
4. **Diagnostic improvements**: `DrainError` aggregates handler exceptions surfaced during drain; `TimeoutError` message includes pending task names with debounce hint.
5. **Inline docstring + test updates**: Update `recording_api.py` module/class docstrings, `app_harness.py` module docstring, affected tests, and `docs/pages/testing/index.md`.
6. **File follow-up issue**: Open a GitHub issue tracking the deferred `_RecordingSyncFacade` code-generation work — document the scope (AST body-copy + `self`→`self._parent` rewrite), the reason for deferral (new generator infrastructure), and the drift-detection test as the interim safety net.

### Out of Scope

- **Code generation of `_RecordingSyncFacade`** (F4 Option C from the first re-challenge) — deferred to a follow-up issue (filed in scope item 6 above). The existing `generate_sync_facade.py` only produces signature-level wrappers; body-copy + AST rewriting would be new infrastructure. The CI drift test provides the protective value without the implementation risk.
- Manual CHANGELOG updates — release-please generates the CHANGELOG from commit messages automatically.
- Archived design specs (2033, 2034) — historical artifacts.
- `_RecordingSyncFacade` Resource lifecycle subclassing — it's a plain class; Resource property access raises the default `AttributeError` via Python lookup rules.
- Refactoring `get_entity_or_none` / `get_state_or_none` — they remain `async def` with internal `await`; no generator invariant requires this now.

## Architecture

### F4: Direct-record convenience methods

```python
async def turn_on(self, entity_id: str | StrEnum, domain: str = "homeassistant", **data) -> None:
    entity_id = str(entity_id)
    self.calls.append(
        ApiCall(
            method="turn_on",
            args=(entity_id,),
            kwargs={"entity_id": entity_id, "domain": domain, **data},
        )
    )

async def turn_off(self, entity_id: str | StrEnum, domain: str = "homeassistant") -> None:
    entity_id = str(entity_id)
    self.calls.append(
        ApiCall(
            method="turn_off",
            args=(entity_id,),
            kwargs={"entity_id": entity_id, "domain": domain},
        )
    )

async def toggle_service(self, entity_id: str | StrEnum, domain: str = "homeassistant") -> None:
    entity_id = str(entity_id)
    self.calls.append(
        ApiCall(
            method="toggle_service",
            args=(entity_id,),
            kwargs={"entity_id": entity_id, "domain": domain},
        )
    )
```

All three methods broaden their type annotation to `str | StrEnum` and coerce uniformly.

### Canonical kwargs shape table (F2, F4)

Both async `RecordingApi` and sync `_RecordingSyncFacade` produce identical shapes. Implementors must use this table as the contract.

| Method | `ApiCall.method` | `ApiCall.args` | `ApiCall.kwargs` |
|--------|------------------|----------------|------------------|
| `turn_on(entity_id, domain="homeassistant", **data)` | `"turn_on"` | `(entity_id,)` | `{"entity_id": entity_id, "domain": domain, **data}` |
| `turn_off(entity_id, domain="homeassistant")` | `"turn_off"` | `(entity_id,)` | `{"entity_id": entity_id, "domain": domain}` |
| `toggle_service(entity_id, domain="homeassistant")` | `"toggle_service"` | `(entity_id,)` | `{"entity_id": entity_id, "domain": domain}` |
| `call_service(domain, service, target=None, return_response=False, **data)` | `"call_service"` | `(domain, service)` | `{"domain": domain, "service": service, "target": target, "return_response": return_response, **data}` |
| `set_state(entity_id, state, attributes=None)` | `"set_state"` | `(entity_id, state)` | `{"entity_id": entity_id, "state": state, "attributes": attributes}` |
| `fire_event(event_type, event_data=None)` | `"fire_event"` | `(event_type,)` | `{"event_type": event_type, "event_data": event_data}` |

**Return values** (must match between async and sync paths):

| Method | Return |
|--------|--------|
| `turn_on` / `turn_off` / `toggle_service` | `None` |
| `call_service(return_response=False)` | `None` |
| `call_service(return_response=True)` | `ServiceResponse(context=Context(id=None, parent_id=None, user_id=None))` |
| `set_state` | `{}` (empty dict) |
| `fire_event` | `{}` (empty dict) |

`entity_id` is always stored as a plain `str` in `kwargs` — all three convenience methods coerce via `str(entity_id)` before recording.

### F2: Hand-written `_RecordingSyncFacade`

New file: `src/hassette/test_utils/sync_facade.py`. Plain class (not a `Resource` subclass).

```python
"""Sync recording facade for RecordingApi.

Provides synchronous versions of RecordingApi's write and read methods. Write
methods append to the parent RecordingApi's `calls` list; read methods delegate
to the state proxy synchronously. Unimplemented methods raise NotImplementedError
with tailored guidance.
"""

from enum import StrEnum
from typing import TYPE_CHECKING, Any, ClassVar, cast
from unittest.mock import Mock  # for isinstance removal context in tests

from hassette.exceptions import EntityNotFoundError
from hassette.models.entities.base import BaseEntity
from hassette.models.services import ServiceResponse
from hassette.models.states.base import BaseState, Context
from hassette.test_utils.recording_api import ApiCall

if TYPE_CHECKING:
    from hassette.test_utils.recording_api import RecordingApi


class _RecordingSyncFacade:
    """Synchronous recording facade for RecordingApi.

    Instances are created by RecordingApi.__init__ and share the parent's
    `calls` list via the `_parent` reference. Users access it via `harness.api_recorder.sync`
    (which is `RecordingApi.sync`).
    """

    _parent: "RecordingApi"

    # Methods whose tailored error message should redirect users to get_state()
    _STATE_CONVERSION_METHODS: ClassVar[frozenset[str]] = frozenset({
        "get_state_value",
        "get_state_value_typed",
        "get_attribute",
    })

    def __init__(self, parent: "RecordingApi") -> None:
        self._parent = parent

    # Write methods — append ApiCall synchronously
    def turn_on(self, entity_id: str | StrEnum, domain: str = "homeassistant", **data) -> None:
        entity_id = str(entity_id)
        self._parent.calls.append(
            ApiCall(
                method="turn_on",
                args=(entity_id,),
                kwargs={"entity_id": entity_id, "domain": domain, **data},
            )
        )

    def turn_off(self, entity_id: str | StrEnum, domain: str = "homeassistant") -> None:
        entity_id = str(entity_id)
        self._parent.calls.append(
            ApiCall(
                method="turn_off",
                args=(entity_id,),
                kwargs={"entity_id": entity_id, "domain": domain},
            )
        )

    def toggle_service(self, entity_id: str | StrEnum, domain: str = "homeassistant") -> None:
        entity_id = str(entity_id)
        self._parent.calls.append(
            ApiCall(
                method="toggle_service",
                args=(entity_id,),
                kwargs={"entity_id": entity_id, "domain": domain},
            )
        )

    def call_service(
        self,
        domain: str,
        service: str,
        target: dict | None = None,
        return_response: bool | None = False,
        **data,
    ) -> ServiceResponse | None:
        self._parent.calls.append(
            ApiCall(
                method="call_service",
                args=(domain, service),
                kwargs={
                    "domain": domain,
                    "service": service,
                    "target": target,
                    "return_response": return_response,
                    **data,
                },
            )
        )
        if return_response:
            return ServiceResponse(context=Context(id=None, parent_id=None, user_id=None))
        return None

    def set_state(
        self,
        entity_id: str | StrEnum,
        state: Any,
        attributes: dict[str, Any] | None = None,
    ) -> dict:
        entity_id = str(entity_id)
        self._parent.calls.append(
            ApiCall(
                method="set_state",
                args=(entity_id, state),
                kwargs={"entity_id": entity_id, "state": state, "attributes": attributes},
            )
        )
        return {}

    def fire_event(self, event_type: str, event_data: dict[str, Any] | None = None) -> dict[str, Any]:
        self._parent.calls.append(
            ApiCall(
                method="fire_event",
                args=(event_type,),
                kwargs={"event_type": event_type, "event_data": event_data},
            )
        )
        return {}

    # Read methods — delegate to parent's state-proxy helpers synchronously
    def get_state(self, entity_id: str) -> BaseState:
        raw = self._parent._get_raw_state(entity_id)
        return self._parent._convert_state(raw, entity_id)

    def get_states(self) -> list[BaseState]:
        items = list(self._parent._state_proxy.states.items())
        return [self._parent._convert_state(raw, eid) for eid, raw in items]

    def get_entity(self, entity_id: str, model: type[Any] = BaseState) -> BaseState:
        raw = self._parent._get_raw_state(entity_id)
        if model is not BaseState and issubclass(model, BaseEntity):
            return cast("BaseState", model.model_validate({"state": raw}))
        return self._parent._convert_state(raw, entity_id)

    def get_entity_or_none(self, entity_id: str, model: type[Any] = BaseState) -> BaseState | None:
        try:
            return self.get_entity(entity_id, model)
        except EntityNotFoundError:
            return None

    def entity_exists(self, entity_id: str) -> bool:
        return entity_id in self._parent._state_proxy.states

    def get_state_or_none(self, entity_id: str) -> BaseState | None:
        try:
            return self.get_state(entity_id)
        except EntityNotFoundError:
            return None

    # Fallback for uncovered methods — tailored messages for state-conversion methods
    def __getattr__(self, name: str) -> Any:
        if name.startswith("_"):
            raise AttributeError(name)

        if name in self._STATE_CONVERSION_METHODS:
            raise NotImplementedError(
                f"RecordingApi.sync.{name} is not implemented on the test facade. "
                f"Call `harness.api_recorder.sync.get_state(entity_id)` and read the returned state directly."
            )

        raise NotImplementedError(
            f"RecordingApi.sync.{name} is not implemented. "
            "Seed state via AppTestHarness.set_state() for read methods, "
            "or use a full integration test for methods requiring a live HA connection."
        )
```

**`RecordingApi.__init__` changes** — module-level import (no lazy imports):

```python
# At top of recording_api.py (after existing imports)
from hassette.test_utils.sync_facade import _RecordingSyncFacade  # noqa: E402 — ordered for forward declaration

# In __init__
self.sync: _RecordingSyncFacade = _RecordingSyncFacade(self)
```

**Circular import check**: `sync_facade.py` imports `ApiCall` from `recording_api.py`. `recording_api.py` imports `_RecordingSyncFacade` from `sync_facade.py`. This is a circular import. Resolution:

- Move `ApiCall` to a dedicated file `src/hassette/test_utils/api_call.py` and import from there in both places, OR
- Import `_RecordingSyncFacade` at the bottom of `recording_api.py` after class definition (unconventional), OR
- Use `TYPE_CHECKING` guard and construct `_RecordingSyncFacade` via a lazy-but-not-function-local pattern.

**Chosen resolution**: extract `ApiCall` to `src/hassette/test_utils/api_call.py`. Both `recording_api.py` and `sync_facade.py` import from there. Clean one-way dependency graph: `api_call` ← `sync_facade` ← `recording_api` ← user code.

### F4 CI drift-detection test

New test: `tests/unit/test_recording_sync_facade_drift.py`

```python
"""CI-enforced drift detection between ApiSyncFacade and _RecordingSyncFacade.

If Api gains a new convenience method (turn_on variant, etc.), ApiSyncFacade
gets a sync wrapper automatically via the code generator. This test asserts
that _RecordingSyncFacade has a matching method so the recording contract
stays complete.
"""

import inspect

from hassette.api.sync import ApiSyncFacade
from hassette.test_utils.sync_facade import _RecordingSyncFacade


def _public_methods(cls: type) -> set[str]:
    """Return the set of public method names defined on cls (not inherited)."""
    return {
        name
        for name, member in inspect.getmembers(cls, predicate=inspect.isfunction)
        if not name.startswith("_") and name in cls.__dict__
    }


def test_recording_sync_facade_covers_api_sync_facade() -> None:
    """_RecordingSyncFacade must define a method for every public method on ApiSyncFacade.

    When Api adds a new convenience method, generate_sync_facade.py produces a
    matching method in ApiSyncFacade. This test fails if _RecordingSyncFacade
    is not updated to match, catching the drift that would otherwise silently
    recreate the RecordingApi.sync=Mock() safety hole for new methods.
    """
    sync_facade_methods = _public_methods(ApiSyncFacade)
    recording_facade_methods = _public_methods(_RecordingSyncFacade)

    missing = sync_facade_methods - recording_facade_methods
    assert not missing, (
        f"_RecordingSyncFacade is missing sync methods present in ApiSyncFacade: {sorted(missing)}. "
        f"Add them to src/hassette/test_utils/sync_facade.py."
    )
```

The test compares public method name sets only — signature compatibility is verified by the separate per-method tests for `_RecordingSyncFacade`.

### F10 + F8 + F9: Iterative drain with exception surfacing

Add public properties/methods:

```python
# src/hassette/task_bucket/task_bucket.py
def pending_tasks(self) -> list[asyncio.Task[Any]]:
    """Return a snapshot list of non-completed tasks in this bucket."""
    return [t for t in list(self._tasks) if not t.done()]

# src/hassette/core/bus_service.py
@property
def is_dispatch_idle(self) -> bool:
    """Return True when no dispatch tasks are in flight."""
    return self._dispatch_idle_event.is_set()

@property
def dispatch_pending_count(self) -> int:
    """Return the number of currently-in-flight dispatch tasks."""
    return self._dispatch_pending
```

New exception type in `src/hassette/test_utils/exceptions.py`:

```python
class DrainError(Exception):
    """Raised by AppTestHarness drain when handler tasks surface exceptions.

    Aggregates all non-cancellation exceptions from completed tasks during drain
    so test failures report the real cause instead of silently masking handler
    crashes with misleading assertion failures.
    """

    task_exceptions: list[tuple[str, BaseException]]

    def __init__(self, task_exceptions: list[tuple[str, BaseException]]) -> None:
        self.task_exceptions = task_exceptions
        count = len(task_exceptions)
        first_name, first_exc = task_exceptions[0]
        parts = [
            f"{count} handler task exception{'s' if count != 1 else ''} during drain.",
            f"First: {first_name}: {type(first_exc).__name__}: {first_exc}",
        ]
        if count > 1:
            parts.append(f"({count - 1} more — see .task_exceptions)")
        super().__init__(" ".join(parts))
```

Replace `AppTestHarness._drain_task_bucket`:

```python
async def _drain_task_bucket(self, *, timeout: float = 2.0) -> None:
    """Wait until bus dispatch queue AND app task_bucket are jointly quiescent.

    Iterates: wait for bus dispatch idle, wait for task_bucket pending tasks, re-check.
    Exits only when both are quiescent after a yield cycle. Covers arbitrary-depth
    task chains (A→B→C) and surfaces any handler exceptions via DrainError.

    Raises:
        TimeoutError: If drain does not reach quiescence within `timeout`.
        DrainError: If any handler task raised a non-cancellation exception.
    """
    harness = self._harness
    if harness is None:
        raise RuntimeError("AppTestHarness is not active")

    bus_service = harness.hassette._bus_service
    assert bus_service is not None, (
        "BusService unexpectedly None at drain time — harness setup may have partially failed"
    )

    app = self._app
    deadline = asyncio.get_running_loop().time() + timeout
    collected_exceptions: list[tuple[str, BaseException]] = []

    while True:
        # Top-of-loop deadline guard: prevents infinite spin on perpetually-spawning handlers
        if asyncio.get_running_loop().time() >= deadline:
            self._raise_drain_timeout(timeout, bus_service, app)

        # Step 1: wait for bus dispatch queue to clear. Wrap await_dispatch_idle
        # to translate its TimeoutError into our diagnostic.
        remaining = deadline - asyncio.get_running_loop().time()
        if remaining <= 0:
            self._raise_drain_timeout(timeout, bus_service, app)
        try:
            await bus_service.await_dispatch_idle(timeout=remaining)
        except TimeoutError:
            self._raise_drain_timeout(timeout, bus_service, app)

        # Step 2: wait for any pending tasks in the app's task_bucket.
        # Collect exceptions from completed tasks so they surface via DrainError.
        if app is not None:
            pending = app.task_bucket.pending_tasks()
            if pending:
                remaining = deadline - asyncio.get_running_loop().time()
                if remaining <= 0:
                    self._raise_drain_timeout(timeout, bus_service, app)
                done, still_pending = await asyncio.wait(pending, timeout=remaining)
                if still_pending:
                    self._raise_drain_timeout(timeout, bus_service, app)
                # Collect exceptions from any done tasks (except CancelledError)
                for task in done:
                    if task.cancelled():
                        continue
                    exc = task.exception()
                    if exc is not None:
                        collected_exceptions.append((task.get_name(), exc))

        # Step 3: stability check via await_dispatch_idle, which has its own 5ms anyio
        # stability window. No-op when dispatch is already idle; re-runs the stability
        # check if new events arrived during step 2.
        try:
            await bus_service.await_dispatch_idle(timeout=max(deadline - asyncio.get_running_loop().time(), 0))
        except TimeoutError:
            self._raise_drain_timeout(timeout, bus_service, app)

        # Step 4: exit condition — both sides quiescent.
        if app is None or not app.task_bucket.pending_tasks():
            if bus_service.is_dispatch_idle:
                # All quiescent; surface any collected exceptions.
                if collected_exceptions:
                    raise DrainError(collected_exceptions)
                return
        # else: loop back for another pass

def _raise_drain_timeout(
    self, timeout: float, bus_service: "BusService", app: "App | None"
) -> None:
    """Build a diagnostic TimeoutError with pending task names and debounce hint."""
    task_names: list[str] = []
    if app is not None:
        task_names = [t.get_name() for t in app.task_bucket.pending_tasks()]

    base = (
        f"AppTestHarness drain did not reach quiescence within {timeout}s "
        f"(bus dispatch pending: {bus_service.dispatch_pending_count}, "
        f"task_bucket pending: {len(task_names)})"
    )
    if task_names:
        base += f"; pending task names: {task_names}"
    if any("debounce" in n for n in task_names):
        base += (
            " — if tasks include 'handler:debounce', your drain timeout may be shorter "
            "than the handler's debounce window. Pass `timeout=` larger than your largest "
            "debounce delay."
        )
    raise TimeoutError(base)
```

**Key correctness points**:
- **Top-of-loop deadline guard** closes the spin-on-short-tasks hole.
- **Exception surfacing via `DrainError`** prevents handler crashes from being masked as misleading assertion failures.
- **Step 3 uses `await_dispatch_idle`** (not `sleep(0)`) to inherit its 5ms anyio stability window.
- **Public `is_dispatch_idle` / `dispatch_pending_count` properties** replace direct private attribute access.
- **`await_dispatch_idle` TimeoutError is wrapped** in `try/except` so the drain's rich diagnostic is always reached.

### F6: Tailored `__getattr__` messages

Already included in the `_RecordingSyncFacade` code above. The same tailored fallback is added to `RecordingApi.__getattr__` for consistency:

```python
# In RecordingApi
_STATE_CONVERSION_METHODS: ClassVar[frozenset[str]] = frozenset({
    "get_state_value",
    "get_state_value_typed",
    "get_attribute",
})

def __getattr__(self, name: str) -> Any:
    if name.startswith("_"):
        raise AttributeError(name)

    if name in self._STATE_CONVERSION_METHODS:
        raise NotImplementedError(
            f"RecordingApi.{name} is not implemented. "
            f"Call `await self.api.get_state(entity_id)` and read the returned state directly."
        )

    raise NotImplementedError(
        f"RecordingApi.{name} is not implemented. "
        "Seed state via AppTestHarness.set_state() for read methods, "
        "or use a full integration test for methods requiring a live HA connection."
    )
```

### Test and doc updates

**Source extraction**:
- New file: `src/hassette/test_utils/api_call.py` — contains `ApiCall` dataclass (extracted from `recording_api.py` to break the circular import).

**Inline source updates**:
- `src/hassette/test_utils/recording_api.py`: module docstring example, class docstring, any inline examples
- `src/hassette/test_utils/app_harness.py`: module docstring example

**Test updates** (grep-identified — update as part of the affected WPs):
- `tests/unit/test_recording_api.py` — assertions on old `call_service` shape for `turn_on`/`turn_off`/`toggle_service`; `test_sync_attribute_is_mock`
- `tests/unit/test_app_test_harness.py` — same
- New: `tests/unit/test_recording_sync_facade.py` — per-method tests for the sync facade
- New: `tests/unit/test_recording_sync_facade_drift.py` — drift-detection test
- New: `tests/unit/test_drain_iterative.py` — tests for the iterative drain: depth-2 chains, exception surfacing, debounce task surface, timeout diagnostic

**Doc updates** (`docs/pages/testing/index.md`):
- Quick Start uses `assert_called("turn_on", ...)` directly
- Remove the `turn_on` → `call_service` warning admonition
- Update `api.sync` warning: now a recording facade (not a Mock)
- Update `task_bucket` warning: drain now handles depth-N chains

**CHANGELOG**: no manual update — release-please generates the CHANGELOG from commit messages. Use Conventional Commits format (`fix:`, `feat:`, etc.) to ensure release-please categorizes the changes correctly.

## Alternatives Considered

1. **F4: Record both `turn_on` AND `call_service`** — rejected: doubles call count, makes `assert_call_count` misleading.
2. **F2: Raise `NotImplementedError` from all `api.sync.*`** — rejected: makes sync code paths untestable.
3. **F2 Code Generation (F4 Option C from first re-challenge)** — rejected after second re-challenge. The existing `generate_sync_facade.py` only produces signature-level wrappers; body-copy + AST rewriting is substantial new infrastructure with correctness risks (allowlist vs full rewrite, stringify invariants, `await` exclusion handling). The CI drift test provides the protective value at much lower implementation risk; code generation can be tackled as a focused follow-up.
4. **F10: Single-pass drain with docs-only warning** — rejected: `RateLimiter._debounced_call` already exercises depth-2 chains.
5. **F10: Track all tasks in all task_buckets** — rejected: waits on unrelated framework tasks.
6. **F10: Re-raise first handler exception instead of aggregating** — rejected in favor of `DrainError` aggregate for full visibility when multiple handlers fail.
7. **F4: Keep `turn_off`/`toggle_service` as `str` only (no StrEnum)** — rejected: uniform behavior across all three convenience methods is cleaner.

## Risks

- **Iterative drain may surface previously-hidden flaky tests**: handlers that relied on fire-and-forget work silently finishing will now either wait for it (possibly hitting the timeout) or surface exceptions via `DrainError`. These tests were already broken; this surfaces the breakage.
- **`DrainError` is new public API** — users writing `try/except TimeoutError` around `simulate_*` calls will not catch `DrainError`. The exception hierarchy is additive, not replacing `TimeoutError`, so drain-timeout tests still work.
- **`ApiCall` import move**: extracting `ApiCall` to its own file affects anyone importing it from `recording_api` directly. Update the `hassette.test_utils.__init__` re-export if needed so `from hassette.test_utils import ApiCall` continues to work.
- **Public property additions** (`is_dispatch_idle`, `dispatch_pending_count`, `pending_tasks`): these become part of the public API surface of `BusService` and `TaskBucket`. Future refactors of these classes must preserve the properties.

## Open Questions

None — all findings from both rounds of challenge have been folded in or explicitly rejected in Alternatives.
