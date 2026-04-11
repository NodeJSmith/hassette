# Design: Helper CRUD API

**Date:** 2026-04-10
**Status:** approved
**Issue:** [#440](https://github.com/hassette/hassette/issues/440)
**Spec:** none (feature created directly via `spec-helper init`; see Open Questions)
**Research:** inline — derived from planner output, code verification, and an adversarial challenge pass (5 critics, 21 findings, all resolved below)

## Problem

Hassette apps that want to programmatically manage Home Assistant **helpers** (`input_boolean`, `input_number`, `input_text`, `input_select`, `input_datetime`, `input_button`, `counter`, `timer`) currently have no typed wrappers. The only path is raw `ws_send_and_wait(type="{domain}/create", ...)` with untyped `Any` responses. This forces every caller to:

- Know the exact HA WebSocket command names for eight domains
- Hand-shape request payloads without schema validation
- Cast untyped responses before using them

Helpers created via these WS commands persist across HA restarts (they are stored in HA's `.storage/`), which makes them the correct primitive for self-provisioning apps — e.g., an automation that wants to bootstrap its own `input_boolean` for "vacation mode" on first run.

**Desired outcome**: Apps can create, list, update, and delete helpers in all eight domains through typed async methods on `Api`, fully unit-testable via the `RecordingApi` test harness, with HA response errors propagating with enough context to diagnose production issues.

The "idempotent bootstrap" pattern some apps will want is a **4-line loop** users write themselves against the typed primitives — not a wrapper method. See *Alternatives Considered* for why.

## Non-Goals

- **No `ensure_helper` / idempotent bootstrap wrapper.** An earlier draft proposed a generic `ensure_helper(domain, name, **fields)` convenience method. Adversarial review surfaced seven distinct problems with it (TOCTOU race under concurrent app startup; matching by mutable `name` instead of stable `id`; `dict[str, Any]` return erasing the type information; untestable via the harness because it couples to `list_*`; breakage when round-tripping the returned dict through `Update*Params` after an HA upgrade; unbounded `list_*` calls scaling O(apps × domains); and first-run create→subscribe ordering gotchas). Each individually is fixable; together they reveal that the convenience method papers over a 4-line loop callers can trivially write themselves. We document the pattern in a narrative guide instead of shipping a broken abstraction. See *Alternatives Considered* and *Open Questions*.
- **`{domain}/subscribe` commands.** HA also registers subscribe commands via `DictStorageCollectionWebsocket`. Those require async generators or callback registration and are deferred to a follow-up issue. Document "out of scope" in the PR description.
- **HA-version gating.** Some helper fields are version-dependent (e.g., `timer.restore` added in a later HA release). We will not gate methods on HA version at runtime. Unknown fields in HA responses are permitted via `ConfigDict(extra="allow")` on Record models.
- **Wrapping helper *state* access.** Reading the live state of a helper already works via `Api.get_state("input_boolean.vacation_mode")` and the existing state registry. This feature adds CRUD for the stored *configuration*, not state reads.
- **Registry integration.** The CRUD methods do not touch `STATE_REGISTRY` or the entity registry.

## Architecture

### Shape of the change

Three code surfaces change:

1. **Models** — one new package `src/hassette/models/helpers/` with a file per domain. Each file exposes three Pydantic models: `{Domain}Record` (HA's stored config), `Create{Domain}Params` (create payload), `Update{Domain}Params` (partial update payload). Plus one new state model: `src/hassette/models/states/counter.py::CounterState` for the `counter` domain which is currently absent from `models/states/`.
2. **API** — 35 new async methods on `Api` in `src/hassette/api/api.py`:
   - 32 CRUD methods (8 domains × 4 ops: `list_*`, `create_*`, `update_*`, `delete_*`)
   - 3 counter service-call shortcuts (`increment_counter`, `decrement_counter`, `reset_counter`) — these operate on a different HA subsystem (entity service calls, not stored config); they live in their own section of `api.py` and are documented as shortcuts, not CRUD
   - Plus a small private helper `_ws_helper_call(domain, operation, **data)` that wraps `ws_send_and_wait` with domain/operation error context
   - The matching sync facade at `src/hassette/api/sync.py` is **regenerated** by `tools/generate_sync_facade.py --target api`, not hand-edited
3. **Test double parity** — `src/hassette/test_utils/recording_api.py` grows a **helper definitions seed surface**, NOT `NotImplementedError` stubs. New methods are first-class citizens of the harness (see "RecordingApi seed surface" below). Parity test's `_KNOWN_READ_METHODS` gains the eight `list_*` method names. The generated `src/hassette/test_utils/sync_facade.py` is regenerated by `--target recording`.

### Transport and envelope handling

Verified against `src/hassette/api/api.py:212-214` and `src/hassette/core/websocket_service.py:246-293`:

```python
async def ws_send_and_wait(self, **data: Any) -> Any:
    return await self._api_service._ws_conn.send_and_wait(**data)
```

The underlying `WebsocketService.send_and_wait` already **unwraps the `{"result": ...}` envelope** — it returns `message.get("result")` which is `list | dict | None` depending on the command. Note: `send_and_wait`'s declared return type is `dict[str, Any]`, but the actual runtime type is the unwrapped value (`list | dict | None`). The existing `api.py` acknowledges this at line 291 with a `# pyright: ignore[reportAssignmentType]`. New helper methods inherit the same arrangement until someone fixes `send_and_wait`'s annotation upstream. We explicitly document the per-command response contract below so the type-vs-runtime mismatch is a known artifact, not a hidden trap.

**Per-command response contract (verified at implementation time against HA source — see "HA Source Verification" prerequisite below):**

| Command class | HA returns | Method handling |
|---|---|---|
| `{domain}/list` | a `list[dict]` of stored records | assert via `_expect_list(val, context)`, parse each into `{Domain}Record` |
| `{domain}/create` | a `dict` representing the newly created record | assert via `_expect_dict(val, context)`, parse into `{Domain}Record` |
| `{domain}/update` | a `dict` representing the updated record | assert via `_expect_dict(val, context)`, parse into `{Domain}Record` |
| `{domain}/delete` | `None` (no result body) | no assertion needed, method returns `None` |
| `counter.increment` / `decrement` / `reset` service calls | service response dict (awaited via `return_response=True`) | errors propagate as `FailedMessageError` |

### Response validation helpers (`_expect_list`, `_expect_dict`)

All CRUD methods validate response shapes via typed helpers instead of bare `assert isinstance(val, ...)`. This matters because:

1. `assert` statements are silently stripped under `python -O` / `PYTHONOPTIMIZE`, so the assertion is not a runtime guarantee.
2. `AssertionError` is not a typed, documented exception — callers cannot catch it meaningfully.
3. The current bare-assert pattern in `api.py:292, 347, 357, 367` is a known wart; these helper methods intentionally do not propagate it to 32 new call sites.

```python
def _expect_list(val: Any, context: str) -> list:
    if not isinstance(val, list):
        raise TypeError(
            f"Expected list from {context}, got {type(val).__name__}: {val!r}"
        )
    return val

def _expect_dict(val: Any, context: str) -> dict:
    if not isinstance(val, dict):
        raise TypeError(
            f"Expected dict from {context}, got {type(val).__name__}: {val!r}"
        )
    return val
```

These are module-level private helpers in `api.py`. The context string (e.g., `"input_boolean/create"`) gives operators a clear signal at 2am about which call failed.

### `api.py` file size — accepted technical debt

Before starting: `src/hassette/api/api.py` is already 883 lines, which exceeds the repo's 800-line file-size cap (set in `rules/common/coding-style.md`, inherited via `CLAUDE.md`). This PR adds ~35 methods + helpers and will push the file to ~1140 lines. **This PR does not resolve the cap violation** — it enlarges an existing one.

An open tracking issue already exists: **[#422 — Split api.py into focused submodules](https://github.com/hassette/hassette/issues/422)** (labels: `enhancement`, `area:api`, `size:large`). That issue covers the proper fix (likely a mixin or composition pattern that the sync facade generator would need to learn to walk). Extending the generator to support multi-file class definitions is non-trivial (`tools/generate_sync_facade.py:320-326` currently greps for `class Api` in a single file and walks only its direct body), and is out of scope for this PR.

**Why we ship anyway**: (1) the cap violation is pre-existing and this PR doesn't meaningfully change the shape of the fix; (2) delaying helper CRUD until #422 lands would couple this user-facing feature to a deep internal refactor that affects the tooling pipeline; (3) issue #422 will be marked as blocking for the next major api.py change after this one. The design team owns reconciling this debt in #422, not here.

### Improved `FailedMessageError` — structured error surface (prerequisite)

This PR **extends `FailedMessageError`** (`src/hassette/exceptions.py:52-62`) to store structured error metadata as instance attributes, so callers can do programmatic error handling instead of parsing strings:

```python
class FailedMessageError(HassetteError):
    """WebSocket message to Home Assistant failed."""

    def __init__(
        self,
        msg: str,
        *,
        code: str | None = None,
        original_data: dict | None = None,
    ) -> None:
        super().__init__(msg)
        self.code = code
        self.original_data = original_data

    @classmethod
    def from_error_response(
        cls,
        error: str | None = None,
        code: str | None = None,
        original_data: dict | None = None,
    ) -> "FailedMessageError":
        msg = f"WebSocket message failed with response '{error}' (data={original_data})"
        return cls(msg, code=code, original_data=original_data)
```

Changes from the current implementation:

- **Adds `__init__`** with keyword-only `code` and `original_data` parameters. Existing `FailedMessageError(msg)` positional-only callers continue to work unchanged (backward compatible).
- **Stores `code` and `original_data` as instance attributes**, making them inspectable from `except FailedMessageError as e:` blocks.
- **Adds a `code` parameter to `from_error_response`** so the WebSocket service can forward HA's error code (HA's WS error envelope has shape `{"success": false, "error": {"code": "...", "message": "..."}}` — the code is discarded today).
- **Fixes the message typo** (`"WebSocket message for failed"` → `"WebSocket message failed"`).

**Why this belongs in this PR**: the helper CRUD feature is the first caller that wants structured error inspection (see `_ws_helper_call` below). Fixing the exception here means helper CRUD ships with proper error handling from day one; deferring to a follow-up PR would require a second `exceptions.py` + `websocket_service.py` + `api.py` edit cycle.

**`websocket_service.py` update**: `src/hassette/core/websocket_service.py:293` currently calls `FailedMessageError.from_error_response(error=message.get("error", {}).get("message"), original_data=message)`. This changes to forward the code as well: `code=message.get("error", {}).get("code")`. WP01 verifies HA's error envelope structure (it may use different field names; the pattern is the same either way).

**Critical implementation note — BOTH changes must land together**: it is easy to update only the `__init__` and forget to update the `from_error_response` classmethod body. The current body is `return cls(msg)`, which does NOT pass `code` or `original_data` through to the new `__init__`. If only `__init__` is updated, `from_error_response` will silently produce instances with `code=None` and `original_data=None` forever, and every `except FailedMessageError as e: if e.code == ...:` check in user code will fall through to `raise`. The design's reference implementation above shows the corrected body (`return cls(msg, code=code, original_data=original_data)`) — it is **not optional**. A unit test in `tests/unit/test_exceptions.py` asserts that `from_error_response(error="x", code="y", original_data={"z": 1})` produces an instance where `e.code == "y"` and `e.original_data == {"z": 1}`. This test is the implementer's gate: if it passes, the body was updated correctly.

### Error context wrapper (`_ws_helper_call`)

All 32 CRUD methods delegate to a **module-level** async helper that chains `FailedMessageError` with domain and operation context while preserving the structured `code` and `original_data` from the underlying error. It lives at module scope in `api.py` (not as a method on `Api`) for two reasons: (1) `tools/generate_sync_facade.py:328-331` walks the `Api` class body and emits every `async def` as a public sync method — a method named `_ws_helper_call` would appear as `ApiSyncFacade._ws_helper_call` in the generated public facade; (2) it stays consistent with `_expect_list`/`_expect_dict` which are also module-level helpers.

```python
async def _ws_helper_call(
    api: "Api", domain: str, operation: str, **data: Any
) -> Any:
    """Call ws_send_and_wait with domain/operation context on failure.

    Preserves `code` and `original_data` from the original FailedMessageError
    so callers can inspect them via `except FailedMessageError as e: e.code`.
    Chains through `raise ... from e` so the original traceback is retained.
    """
    try:
        return await api.ws_send_and_wait(type=f"{domain}/{operation}", **data)
    except FailedMessageError as e:
        raise FailedMessageError(
            f"{domain}/{operation} failed for {data!r}: {e}",
            code=e.code,
            original_data=e.original_data,
        ) from e
```

Without this wrapper, a failed `update_input_boolean(helper_id="missing")` produces a log line like `"FailedMessageError: Unable to find input_boolean_id missing"` with no hint about which domain, id, or operation was involved. With the wrapper, the log line reads `"input_boolean/update failed for {'input_boolean_id': 'missing', ...}: Unable to find input_boolean_id missing"`, AND the caller can still inspect `e.code == "not_found"` because the structured fields are preserved through the chain.

Call sites pass `self` as the first argument: `await _ws_helper_call(self, "input_boolean", "create", **params.model_dump(exclude_unset=True))`.

**Example programmatic error handling** (not required, but now possible):

```python
try:
    await self.api.update_input_boolean(
        "vacation_mode",
        UpdateInputBooleanParams(initial=False),
    )
except FailedMessageError as e:
    if e.code == "not_found":
        # Helper doesn't exist yet — create it instead
        await self.api.create_input_boolean(
            CreateInputBooleanParams(name="vacation_mode", initial=False)
        )
    else:
        # Includes transport timeouts, disconnects, unauthorized, and other
        # failures where HA returned a different error (or no envelope at
        # all — `e.code is None` for transport-level failures). Not
        # recoverable via helper CRUD retry; fall through to `raise`.
        raise
```

The full catalogue of error codes Hassette may see on the helper CRUD path is documented in the `## HA WebSocket Commands` → "Error codes Hassette may see" section below, verified against HA's `websocket_api/const.py`. **Note:** HA does **not** emit a `name_in_use` error code for duplicate-create attempts; `IDManager.generate_id` silently auto-suffixes (`vacation_mode`, `vacation_mode_2`, ...). See the "HA does NOT reject duplicate create names" section for details and the naming-discipline recommendation.

### Method signatures (representative — `input_boolean`)

```python
# Read — list all stored input_boolean helpers
async def list_input_booleans(self) -> list[InputBooleanRecord]:
    val = await _ws_helper_call(self, "input_boolean", "list")
    items = _expect_list(val, "input_boolean/list")
    self.logger.debug("Listed %d input_boolean helpers", len(items))
    return [InputBooleanRecord.model_validate(item) for item in items]

# Create — returns the stored record
async def create_input_boolean(
    self, params: CreateInputBooleanParams
) -> InputBooleanRecord:
    val = await _ws_helper_call(
        self, "input_boolean", "create", **params.model_dump(exclude_unset=True)
    )
    record = InputBooleanRecord.model_validate(_expect_dict(val, "input_boolean/create"))
    self.logger.info("Created input_boolean helper %r", record.id)
    return record

# Update — partial update via exclude_unset; returns the updated record
async def update_input_boolean(
    self, helper_id: str, params: UpdateInputBooleanParams
) -> InputBooleanRecord:
    val = await _ws_helper_call(
        self,
        "input_boolean",
        "update",
        input_boolean_id=helper_id,
        **params.model_dump(exclude_unset=True),
    )
    record = InputBooleanRecord.model_validate(_expect_dict(val, "input_boolean/update"))
    self.logger.debug("Updated input_boolean helper %r", helper_id)
    return record

# Delete — returns None
async def delete_input_boolean(self, helper_id: str) -> None:
    await _ws_helper_call(self, "input_boolean", "delete", input_boolean_id=helper_id)
    self.logger.debug("Deleted input_boolean helper %r", helper_id)
```

**Why `exclude_unset=True` and not `exclude_none=True`:** `exclude_none` silently drops explicitly-set falsy values like `initial=False` — a user writing `CreateInputBooleanParams(name="foo", initial=False)` would have `initial` stripped from the payload and HA would create the helper with its default value, producing a silent semantic bug. `exclude_unset` only strips fields the caller never touched, preserving the distinction between "not set" and "set to a falsy value". This requires `Create*Params` / `Update*Params` optional fields to omit the `= None` default and use Pydantic's implicit unset semantics.

### Counter service-call shortcuts

`counter` is unique in that HA exposes `counter.increment`, `counter.decrement`, and `counter.reset` as **service calls**, not WebSocket commands. These are thin wrappers over `call_service` but they operate on a **different abstraction layer** from the 32 CRUD methods: CRUD reads/writes HA's stored `.storage/` config, while service calls mutate live entity runtime state. The two layers have different error modes and different HA subsystems backing them.

For clarity we place them in a separate `# Counter service-call shortcuts` section of `api.py`, with docstrings that explicitly say "operates on live entity state, not stored config." Callers who want to reset a counter's stored config (e.g., change `initial`) use `update_counter`; callers who want to reset the live value use `reset_counter`.

```python
async def increment_counter(self, entity_id: str) -> None:
    """Increment a counter entity's current value (live state, not stored config)."""
    await self.call_service(
        "counter", "increment",
        target={"entity_id": entity_id},
        return_response=True,  # surfaces HA errors instead of fire-and-forget
    )

async def decrement_counter(self, entity_id: str) -> None:
    """Decrement a counter entity's current value (live state, not stored config)."""
    await self.call_service(
        "counter", "decrement",
        target={"entity_id": entity_id},
        return_response=True,
    )

async def reset_counter(self, entity_id: str) -> None:
    """Reset a counter entity's value to its configured initial (live state)."""
    await self.call_service(
        "counter", "reset",
        target={"entity_id": entity_id},
        return_response=True,
    )
```

**Why `return_response=True`**: without it, `call_service` uses `ws_send_json` (fire-and-forget) and the transport-level error response is silently discarded. With `return_response=True`, `ws_send_and_wait` is used and **WebSocket-level failures** (e.g., malformed payloads, missing entities at the transport layer) raise `FailedMessageError`. For operations that apps rely on for automation correctness, silent transport failure is unacceptable. The extra round-trip cost is negligible.

**What this does NOT catch**: an application-level error returned *inside* a structurally successful WS response (e.g., `{"success": true, "result": {"error": "..."}}`) is not detected by `return_response=True`. `ws_send_and_wait` only raises `FailedMessageError` on `success: false`. Counter shortcut methods currently discard the `ServiceResponse` return value, so application-layer error payloads in successful responses go unlogged. A future improvement would inspect the `ServiceResponse` body for known error shapes — tracked as a follow-up, not in scope for this PR.

**Why not `timer.start`/`timer.pause`/`timer.cancel`**: asymmetry is intentional. `timer.start` is fully covered by `call_service("timer", "start", target=...)` with no added value from a wrapper. Counter actions get wrappers because apps commonly do "after every motion event, increment the motion_count counter" — a pattern that benefits from a two-word call site. Timer actions are typically one-off from scheduler callbacks where the full `call_service` is fine. This is documented in the section header comment in `api.py` so future contributors don't add timer wrappers by default.

### Record model conventions

All `{Domain}Record` models use:

```python
class InputBooleanRecord(BaseModel):
    model_config = ConfigDict(extra="allow")
    id: str
    name: str
    icon: str | None = None
    initial: bool | None = None
```

The `extra="allow"` opt-in lets unknown HA fields pass through without `ValidationError`. This is deliberate — HA adds helper fields across minor releases, and the feature would otherwise break users the moment they upgrade HA.

`Update*Params` models use `ConfigDict(extra="ignore")` (not the default `extra="forbid"`) so that callers who want to round-trip data — e.g., "fetch a record, tweak one field, send the update" — don't hit `ValidationError` for HA fields we don't know about. This is defensive posture for long-term HA compatibility.

`CreateInputDatetimeParams` carries a `model_validator(mode="after")` enforcing `has_date or has_time` — this mirrors HA's own create-time validation and catches the mistake locally with a clearer error than HA's generic failure response.

### `CounterRecord` vs `CounterState` — two representations of the same helper

This PR introduces two `counter` models that callers may confuse:

| Model | Represents | Obtained via | Fields |
|---|---|---|---|
| `CounterRecord` | Stored config in HA's `.storage/counter` | `list_counters()`, `create_counter()`, `update_counter()` | `id`, `name`, `icon`, `initial`, `minimum`, `maximum`, `step`, `restore` |
| `CounterState` | Live runtime state (current value) | `Api.get_state("counter.xxx")` | `state` (current value as str), `attributes.initial`, `attributes.minimum`, `attributes.maximum`, `attributes.step`, etc. |

The overlapping fields (`initial`, `minimum`, `maximum`, `step`) carry the same value because HA exposes them in both places. `state` is only on `CounterState` (the live value). Changes to stored config via `update_counter()` take effect on the next HA restart; changes to live value via `increment_counter()`/`reset_counter()` are immediate but not persisted to stored config. Docstrings on both models point at each other to keep this clear.

### RecordingApi seed surface

New methods are **first-class in the test harness**. No `NotImplementedError` stubs.

`RecordingApi` gains a new seed dict alongside `calls`:

```python
from typing import Any, cast

# Module-level domain constant — single source of truth for supported domains
_SUPPORTED_HELPER_DOMAINS: frozenset[str] = frozenset({
    "input_boolean", "input_number", "input_text", "input_select",
    "input_datetime", "input_button", "counter", "timer",
})

# Type→domain lookup — a hand-maintained dict literal that must stay in sync
# with the 8 Record classes above. Adding a 9th helper domain requires adding
# an entry here. A future refactor could add `domain: ClassVar[str]` to each
# Record model and auto-populate this dict, but that is out of scope for this PR.
_RECORD_TYPE_TO_DOMAIN: dict[type, str] = {
    InputBooleanRecord: "input_boolean",
    InputNumberRecord: "input_number",
    InputTextRecord: "input_text",
    InputSelectRecord: "input_select",
    InputDatetimeRecord: "input_datetime",
    InputButtonRecord: "input_button",
    CounterRecord: "counter",
    TimerRecord: "timer",
}


class RecordingApi(Resource):
    calls: list[ApiCall]
    # dict[str, dict[str, Any]] internally — per-domain typing is restored
    # at the list_* return site via cast. This keeps the storage flexible
    # while list_* methods return the precise Record type to callers.
    helper_definitions: dict[str, dict[str, Any]]

    def __init__(self, ...) -> None:
        super().__init__(...)
        self.calls = []
        self.helper_definitions = {d: {} for d in _SUPPORTED_HELPER_DOMAINS}
```

**Why `dict[str, dict[str, Any]]` and not typed per-domain**: keeping the internal storage as `Any` lets `RecordingApi` hold any Record subclass without Pyright's `dict[str, BaseModel]` inference weakening return types. Each `list_*` method does `cast(list[InputBooleanRecord], ...)` at return so callers get full type precision. An alternative would be a `@dataclass HelperDefinitions` with one `dict[str, XxxRecord]` per domain (fully structurally typed), but the cast approach is simpler and adequate for a test harness where the seed API enforces correctness at the entry point.

**Public seed API on `AppTestHarness`** — domain is **derived from the record type**, not passed separately. This closes round-1 finding F5 (silent domain/type mismatch):

```python
def seed_helper(self, record: BaseModel) -> None:
    """Seed a stored helper config for tests that read helper CRUD.

    Domain is derived from the record class. Passing a record of a type
    not registered in _RECORD_TYPE_TO_DOMAIN raises ValueError immediately.
    """
    try:
        domain = _RECORD_TYPE_TO_DOMAIN[type(record)]
    except KeyError as e:
        raise ValueError(
            f"Unknown helper record type: {type(record).__name__}. "
            f"Expected one of: {sorted(t.__name__ for t in _RECORD_TYPE_TO_DOMAIN)}"
        ) from e
    self.api_recorder.helper_definitions[domain][record.id] = record
```

Usage: `harness.seed_helper(InputBooleanRecord(id="vacation_mode", name="Vacation Mode"))`. No `domain` parameter — a typo in the record class name becomes an ImportError at module load, not a silent runtime no-op.

**Per-method behavior on `RecordingApi`:**

- **`list_{domain}`** — returns `cast(list[{Domain}Record], list(self.helper_definitions["{domain}"].values()))`. No recording (it's a read). Operates purely against the seeded state.
- **`create_{domain}(params)`** — records an `ApiCall`, computes the new id via `_generate_helper_id(set(self.helper_definitions["{domain}"].keys()), params.name)` (a module-level helper in `src/hassette/test_utils/recording_api.py` that mirrors HA's `IDManager.generate_id` — uses `_slugify_helper_name` for the base id, then auto-suffixes `_2`/`_3`/... on collision), constructs `{Domain}Record(id=generated_id, **params.model_dump(exclude_unset=True))`, inserts into `helper_definitions["{domain}"][record.id]`, returns the record. Both helpers (`_slugify_helper_name` and `_generate_helper_id`) are **harness-only**, defined in `recording_api.py`, NOT in `api.py` — the real `Api.create_*` methods never slugify or generate ids because HA assigns the id server-side. WP01 verified HA's exact slug rule (it uses `python-slugify` with `separator="_"`) and the auto-suffix collision loop; see `## HA WebSocket Commands` for the source trace.
- **`update_{domain}(helper_id, params)`** — records an `ApiCall`, constructs a new record via `existing.model_copy(update=params.model_dump(exclude_unset=True))` (immutability), replaces `helper_definitions[domain][helper_id]`, returns the new record. **Raises `FailedMessageError(code="not_found")` with a diagnostic message** if `helper_id` is not in the seed dict — matches real HA's `ItemNotFound → ERR_NOT_FOUND` behavior (verified in `## HA WebSocket Commands → HA delete-of-nonexistent behavior`). Tests that expect an update on nonexistent state can catch the same exception class they would use against real HA.
- **`delete_{domain}(helper_id)`** — records an `ApiCall`, removes from `helper_definitions[domain]`. **Raises `FailedMessageError(code="not_found")` with a diagnostic message** on missing `helper_id`, consistent with `update_*` and with real HA's behavior. Exception-class parity with real HA means test code can use `except FailedMessageError as e: if e.code == "not_found": ...` against both the harness and a live HA instance without branching on the environment.
- **Counter action methods** (`increment_counter`, `decrement_counter`, `reset_counter`) — record an `ApiCall` with method name + entity_id (same pattern as `turn_on` in `recording_api.py:167-176`). They do NOT delegate to `self.call_service(...)` because the sync facade generator's `_check_no_async_peer_calls` guard at `generate_sync_facade.py:509` aborts on any method body that calls another async peer method — that's an explicit authoring constraint documented at `recording_api.py:88-95`.

**`reset()` must clear `helper_definitions`**:

`RecordingApi.reset()` at `recording_api.py:504-512` currently clears only `self.calls`. It must be extended to reinitialize `helper_definitions` to empty-per-domain state, otherwise tests that use `reset()` for sub-scenario isolation will see stale helper records from prior `create_*` calls:

```python
def reset(self) -> None:
    self.calls.clear()
    self.helper_definitions = {d: {} for d in _SUPPORTED_HELPER_DOMAINS}
```

If a test wants seeded state to persist across resets (e.g., a session-scoped helper fixture), the test should re-seed after `reset()` or call a future `reset_calls_only()` method. We don't add `reset_calls_only()` in this PR — wait for demand.

**Write/read classification in the parity test:**

`tests/unit/test_recording_api_write_parity.py::_KNOWN_READ_METHODS` gains the eight `list_*` names. The 24 `create/update/delete` methods plus 3 counter action methods become write methods enforced by the parity test. `_KNOWN_READ_METHODS` updates **must be co-committed** with the new methods in `api.py` — in the same commit — otherwise the parity test will fail with a confusing "RecordingApi is missing write methods: {list_input_booleans, ...}" message. The files-affected table below co-locates these two entries with an explicit ordering note.

### `ApiProtocol` enforcement

Verified against `src/hassette/test_utils/recording_api.py:28-29, 516-522`: the module-level `_: ApiProtocol = cast(...)` at line 522 is explicitly documented as a Pyright no-op. The parity test only enforces `RecordingApi` method presence, not `ApiProtocol` sync with `Api`.

**New test** to close this gap: `tests/unit/test_recording_api_protocol_parity.py` compares the set of public async methods declared on `ApiProtocol` against the set declared on `Api`, using the **same `vars(cls)` + `inspect.iscoroutinefunction` pattern** as the existing write-parity test at `test_recording_api_write_parity.py:65-76`. `ApiProtocol.__annotations__` cannot be used — Protocol method declarations (`async def foo(self) -> None: ...`) do not populate `__annotations__`, so a test built on that inspection would always pass vacuously and enforce nothing.

Reference implementation:

```python
# tests/unit/test_recording_api_protocol_parity.py
import inspect
from hassette.api.api import Api
from hassette.test_utils.recording_api import ApiProtocol


def _public_async_methods(cls: type) -> set[str]:
    return {
        name for name, member in vars(cls).items()
        if not name.startswith("_") and inspect.iscoroutinefunction(member)
    }


def test_api_protocol_matches_api_methods() -> None:
    """ApiProtocol must declare every public async method that Api has.

    When Api gains a new public async method, ApiProtocol must be updated
    so the module-level `_: ApiProtocol = cast(...)` assertion in
    recording_api.py remains structurally valid.
    """
    api_methods = _public_async_methods(Api)
    protocol_methods = _public_async_methods(ApiProtocol)

    missing_from_protocol = api_methods - protocol_methods
    assert not missing_from_protocol, (
        f"ApiProtocol is missing methods present in Api: "
        f"{sorted(missing_from_protocol)}. Add them to ApiProtocol "
        f"in src/hassette/test_utils/recording_api.py."
    )
```

When `Api` gains a new public async method, this test fails until `ApiProtocol` is updated, forcing the Protocol to stay a first-class documentation-AND-type surface.

### Interaction with the sync facade generator

Verified against `tools/generate_sync_facade.py:179-192, 509-551, 559-632`: the generator

1. **Walks `api.py`'s AST** to derive imports automatically from the methods it emits (line 559-632). New imports from `hassette.models.helpers.*` flow through without any `HEADER` constant update.
2. **Enforces an authoring constraint** (line 509) that body-copied methods on `RecordingApi` must not call async peer methods — this is why counter action methods on `RecordingApi` record `ApiCall` directly instead of delegating to `self.call_service(...)`.
3. Has two targets (`--target api` and `--target recording`) with drift tests at `tests/unit/test_recording_sync_facade_generation.py::test_generator_check_mode_{api,recording}_exits_zero` that run on every local `pytest`. Forgetting to regenerate either target surfaces immediately.

### `Api` class responsibility and the monolith choice

This PR grows `Api` from ~40 methods to ~75, merging HA operational API (states, services, events, REST) with HA configuration CRUD (helper stored-config management). These have different change rates and different HA subsystems backing them — which would normally argue for structural separation (e.g., an `Api.helpers` sub-namespace).

**We deliberately choose the flat structure** for three reasons:

1. **Generator constraint**: `tools/generate_sync_facade.py` works at the `Api` class level. Sub-namespace classes would require extending the generator — a larger change than this feature warrants.
2. **Caller ergonomics**: `api.create_input_boolean(...)` is more discoverable than `api.helpers.create_input_boolean(...)`. Users are unlikely to scan for helper CRUD separately.
3. **Consistency**: `Api` is already the monolith entry point for HA interaction. Adding a second layer of namespacing for one subsystem would create a naming asymmetry that invites debate for every subsequent addition.

This is a deliberate architectural decision, not an accident of the generator. If we later need to split `Api` (e.g., when HA exposes registry CRUD via WebSocket), that's a much larger refactor and we'll handle it then.

### Files affected

| File | Action |
|---|---|
| `src/hassette/exceptions.py` | extend `FailedMessageError` with `__init__(msg, *, code, original_data)` + instance attributes; fix typo in `from_error_response` message |
| `src/hassette/core/websocket_service.py` | at line 293, forward HA error envelope `code` through `FailedMessageError.from_error_response(error=..., code=..., original_data=...)` |
| `src/hassette/models/states/counter.py` | **new** — `CounterAttributes`, `CounterState(NumericBaseState)` |
| `src/hassette/models/states/__init__.py` | add `CounterAttributes`, `CounterState` imports + `__all__` entries |
| `src/hassette/models/helpers/__init__.py` | **new** — re-exports |
| `src/hassette/models/helpers/input_boolean.py` | **new** — Record + Create + Update |
| `src/hassette/models/helpers/input_number.py` | **new** |
| `src/hassette/models/helpers/input_text.py` | **new** |
| `src/hassette/models/helpers/input_select.py` | **new** |
| `src/hassette/models/helpers/input_datetime.py` | **new** (includes `has_date or has_time` validator) |
| `src/hassette/models/helpers/input_button.py` | **new** |
| `src/hassette/models/helpers/counter.py` | **new** |
| `src/hassette/models/helpers/timer.py` | **new** |
| `src/hassette/api/api.py` | add 32 CRUD methods + 3 counter shortcuts + private `_ws_helper_call` + `_expect_list`/`_expect_dict` helpers; import helper models |
| `src/hassette/api/sync.py` | **regenerated** via `uv run tools/generate_sync_facade.py --target api` |
| `src/hassette/test_utils/recording_api.py` | extend `ApiProtocol` with 35 new method signatures; add `helper_definitions` seed dict; add 32 CRUD implementations that mutate the seed dict; add 3 counter action methods that record `ApiCall` directly |
| `src/hassette/test_utils/app_harness.py` | add public `seed_helper(record)` method (domain derived from record type via `_RECORD_TYPE_TO_DOMAIN`) |
| `src/hassette/test_utils/sync_facade.py` | **regenerated** via `uv run tools/generate_sync_facade.py --target recording` |
| `tests/unit/test_recording_api_write_parity.py` | extend `_KNOWN_READ_METHODS` with the eight `list_*` names — **must be in same commit as `api.py` changes** |
| `tests/unit/test_recording_api_protocol_parity.py` | **new** — compares `ApiProtocol` declared methods against `Api` public async methods |
| `tests/integration/test_api_helpers.py` | **new** — covers all 35 methods (transport/shape) |
| `tests/unit/test_api_helper_models.py` | **new** — Pydantic model validation (e.g., `CreateInputDatetimeParams` date/time invariant) |
| `tests/unit/test_recording_api_helpers.py` | **new** — exercises the seed surface: seed → list → create → list → update → delete → list |

## HA Source Verification (WP01 Prerequisite)

**Before implementing any CRUD method, verify the per-domain WebSocket command shapes against HA source.** This is the single highest-risk item in the design.

The design assumes HA's update/delete commands accept domain-specific ID keys (`input_boolean_id`, `counter_id`, etc.). Evidence for this is circumstantial — the codebase has a comment at `src/hassette/utils/hass_utils.py:18` noting that `object_id` is the typical HA storage key in practice. If any domain uses `object_id` or a different key name, every update/delete for that domain would ship broken — and mocked integration tests patching `ws_send_and_wait` would not catch it (the tests would verify the client-side shape, not HA's acceptance).

**WP01 task**: for each of the 8 domains, read `homeassistant/components/{domain}/websocket_api.py` (or the equivalent file in HA source) and document:

1. The exact command name (e.g., `input_boolean/update` vs `input_boolean_update`)
2. The ID key name for update/delete (e.g., `input_boolean_id` vs `object_id` vs `id`)
3. The response shape (dict vs list vs null)
4. Any unexpected per-domain asymmetries
5. **HA's slug-derivation rule** for converting a create-time `name` into a stored `id` (needed by `RecordingApi.create_*` to match real HA behavior — e.g., `"Vacation Mode"` → `"vacation_mode"`)
6. **HA's WS error envelope structure**: does HA's `{"success": false, "error": {...}}` response include a `code` field alongside `message`? This drives the `FailedMessageError.code` population pathway. If HA only sends `{"error": "message"}` without a code, the `code` attribute stays `None` in practice but the exception signature is still correct.
7. **HA's delete-of-nonexistent behavior**: does `{domain}/delete` with an unknown ID return an error response, or silently succeed? (**Resolved by WP01**: HA raises `ItemNotFound` → returns `code="not_found"`. See `## HA WebSocket Commands → HA delete-of-nonexistent behavior`. The design's choice of strict-not-silent is confirmed; the exception class was refined from `KeyError` to `FailedMessageError(code="not_found")` for parity with real HA.)

Results land in a `## HA WebSocket Commands` section of this design doc (added during WP01) and drive:
- An `_ID_KEYS_BY_DOMAIN: dict[str, str]` lookup table in `api.py` if HA is not consistent across domains. If HA IS consistent, we can use plain string interpolation; but the verification must happen either way.
- A module-level `_slugify_helper_name(name: str) -> str` function in **`src/hassette/test_utils/recording_api.py`** (harness-only; real `Api.create_*` methods never slugify because HA assigns the id server-side). Verify via `grep -r slugify src/hassette/` whether hassette already has a slugify utility; if so, reuse it, otherwise a small local implementation is fine.

If possible, add at least one `@pytest.mark.requires_ha` integration smoke test that exercises `create`/`update`/`delete` against a real HA instance for at least one domain — to catch ID key mismatches that mocked tests cannot.

**WP01 status: complete.** The verification results are documented in the `## HA WebSocket Commands` section below (added 2026-04-10 against HA tag `2026.4.1`, commit `b981ece163707338ef05cb227c3c14a2ca392b6e`). That section is the authoritative contract for WP02–WP05 implementation. Subsequent WPs should not re-read HA source for the items it covers — they should cite the section.

## HA WebSocket Commands

This section documents HA's WebSocket API for helper CRUD commands, verified against Home Assistant source at tag **`2026.4.1`** (commit SHA `b981ece163707338ef05cb227c3c14a2ca392b6e`). All subsequent WPs implement against this verified contract rather than assumptions. Raw file URLs follow the pattern:

```
https://raw.githubusercontent.com/home-assistant/core/2026.4.1/homeassistant/<path>
```

### Shared infrastructure — `DictStorageCollectionWebsocket`

All 8 helper domains register their CRUD WebSocket surface via `collection.DictStorageCollectionWebsocket` from `homeassistant/helpers/collection.py`. Each domain's `__init__.py` constructs it with the identical positional pattern:

```python
collection.DictStorageCollectionWebsocket(
    storage_collection, DOMAIN, DOMAIN, STORAGE_FIELDS, STORAGE_FIELDS
).async_setup(hass)
```

The second argument is `api_prefix` and the third is `model_name`; every domain passes `DOMAIN` for both. This has two important consequences that hold for **every** domain covered by this feature:

1. **Command prefix** — every command is named `f"{api_prefix}/<op>"`, i.e. `"{domain}/list"`, `"{domain}/create"`, `"{domain}/update"`, `"{domain}/delete"` (plus `"{domain}/subscribe"`, which is explicitly out of scope per *Non-Goals*). Registration happens in `StorageCollectionWebsocket.async_setup` at `homeassistant/helpers/collection.py:566-628`.
2. **Update/delete ID key** — the update and delete schemas require a field named `self.item_id_key`, a computed property at `homeassistant/helpers/collection.py:561-564`:

   ```python
   @property
   def item_id_key(self) -> str:
       """Return item ID key."""
       return f"{self.model_name}_id"
   ```

   Because every domain passes `model_name=DOMAIN`, the ID key is uniformly `"{domain}_id"` — `input_boolean_id`, `input_number_id`, `input_text_id`, `input_select_id`, `input_datetime_id`, `input_button_id`, `counter_id`, `timer_id`. **No per-domain `_ID_KEYS_BY_DOMAIN` lookup is required** — `Api.update_*` / `Api.delete_*` can use `f"{domain}_id"` interpolation.

The websocket handlers themselves live in the same file:

- `ws_list_item` (registration `collection.py:569-576`, handler body at `collection.py:630-635`): returns `self.storage_collection.async_items()` — a `list[dict]`.
- `ws_create_item` (registration `collection.py:578-590`, handler body at `collection.py:637-654`): strips `"id"` and `"type"` from the inbound message, forwards the rest to `async_create_item`, then `connection.send_result(msg["id"], item)` — response is the created item `dict`.
- `ws_update_item` (registration `collection.py:601-614`, handler body at `collection.py:706-731`): extracts `item_id = data.pop(self.item_id_key)`, calls `async_update_item(item_id, data)`, responds with the updated item `dict`. On `ItemNotFound` it sends `ERR_NOT_FOUND`. On `vol.Invalid` it sends `ERR_INVALID_FORMAT`.
- `ws_delete_item` (registration `collection.py:616-628`, handler body at `collection.py:733-746`): calls `self.storage_collection.async_delete_item(msg[self.item_id_key])`, then `connection.send_result(msg["id"])` — **no payload**, so HA returns `{"success": true, "result": null}` and Hassette's `send_and_wait` unwraps to `None`.

### Command summary (all 8 domains)

Every domain follows the identical shape: `{domain}/list`, `{domain}/create`, `{domain}/update`, `{domain}/delete`, with ID key `{domain}_id`, list response `list[dict]`, create/update response `dict`, delete response `None`. The 8 rows below confirm this by citing each domain's `DictStorageCollectionWebsocket(...)` call site and `DOMAIN` constant:

| Domain | Commands | Update/Delete ID key | Registration site |
|---|---|---|---|
| `input_boolean` | `input_boolean/{list,create,update,delete}` | `input_boolean_id` | `homeassistant/components/input_boolean/__init__.py:116-118` (`DOMAIN = "input_boolean"` at line 31) |
| `input_number` | `input_number/{list,create,update,delete}` | `input_number_id` | `homeassistant/components/input_number/__init__.py:132-134` (`DOMAIN = "input_number"` at line 31) |
| `input_text` | `input_text/{list,create,update,delete}` | `input_text_id` | `homeassistant/components/input_text/__init__.py:141-143` (`DOMAIN = "input_text"` at line 31) |
| `input_select` | `input_select/{list,create,update,delete}` | `input_select_id` | `homeassistant/components/input_select/__init__.py:162-164` (`DOMAIN = "input_select"` at line 39) |
| `input_datetime` | `input_datetime/{list,create,update,delete}` | `input_datetime_id` | `homeassistant/components/input_datetime/__init__.py:154-156` (`DOMAIN = "input_datetime"` at line 31) |
| `input_button` | `input_button/{list,create,update,delete}` | `input_button_id` | `homeassistant/components/input_button/__init__.py:101-103` (`DOMAIN = "input_button"` at line 26) |
| `counter` | `counter/{list,create,update,delete}` | `counter_id` | `homeassistant/components/counter/__init__.py:120-122` (`DOMAIN = "counter"` at line 39) |
| `timer` | `timer/{list,create,update,delete}` | `timer_id` | `homeassistant/components/timer/__init__.py:136-138` (`DOMAIN = "timer"` at line 33) |

All 8 domains use **identical** positional args `(storage_collection, DOMAIN, DOMAIN, STORAGE_FIELDS, STORAGE_FIELDS)` — create and update share one schema (no asymmetry). The `update` schema at the WS layer additionally accepts `self.item_id_key: str` (required) on top of the domain's `STORAGE_FIELDS`; the `delete` schema accepts only `self.item_id_key: str`. WP02 should model `Update*Params` with every field from the domain's STORAGE_FIELDS as optional (for partial updates via `exclude_unset=True`).

### Per-domain fields

Field names below use HA's `CONF_*` constant values (the strings that appear on the wire), not the Python constant names.

#### `input_boolean`
- **Create fields** (all shared with update): `name: str` (required, `vol.Length(min=1)`), `initial: bool` (optional), `icon: str` (optional, `cv.icon`).
- **Schema source:** `homeassistant/components/input_boolean/__init__.py:37-41` (`STORAGE_FIELDS`).
- **Collection class:** `InputBooleanStorageCollection(collection.DictStorageCollection)` at `homeassistant/components/input_boolean/__init__.py:64-81`.
- **Validators:** none (no cross-field invariants).
- **List response shape:** `list[dict]` where each entry has `id`, `name`, and whatever optional fields were set.

#### `input_number`
- **Create fields:** `name: str` (required), `min: float` (required, `vol.Coerce(float)`), `max: float` (required, `vol.Coerce(float)`), `initial: float` (optional), `step: float` (optional, default `1`, `vol.Range(min=1e-9)`), `icon: str` (optional), `unit_of_measurement: str` (optional), `mode: str` (optional, default `"slider"`, one of `["box", "slider"]`).
- **Schema source:** `homeassistant/components/input_number/__init__.py:66-75` (`STORAGE_FIELDS`).
- **Validators:** `_cv_input_number` at `homeassistant/components/input_number/__init__.py:52-63` enforces `max > min` and `min <= initial <= max`. Models should mirror this as a `@model_validator(mode="after")` on `Create*Params` / `Update*Params`. For partial updates where only one of `min`/`max` is set, the validator should **only** fire if the caller provides enough information to validate — this matters because HA's server-side validator runs against the merged (existing + update) data, not the update alone. Simplest correct behavior in Hassette models: skip the invariant check on `Update*Params` and let HA return the error if it's violated. Document this as an explicit tradeoff.

#### `input_text`
- **Create fields:** `name: str` (required), `min: int` (optional, default `0`, range `[0, MAX_LENGTH_STATE_STATE=255]`), `max: int` (optional, default `100`, range `[1, 255]`), `initial: str` (optional, default `""`), `icon: str` (optional), `unit_of_measurement: str` (optional), `pattern: str` (optional), `mode: str` (optional, default `"text"`, one of `["text", "password"]`).
- **Schema source:** `homeassistant/components/input_text/__init__.py:53-66` (`STORAGE_FIELDS`).
- **Validators:** `_cv_input_text` at `homeassistant/components/input_text/__init__.py:69-82` enforces `min <= max` and validates the initial value fits the `min`/`max` length bounds. Same partial-update consideration as `input_number` — WP02 should skip the invariant check on `Update*Params`.

#### `input_select`
- **Create fields:** `name: str` (required), `options: list[str]` (required, `vol.Length(min=1)`, unique, each `cv.string`), `initial: str` (optional), `icon: str` (optional).
- **Schema source:** `homeassistant/components/input_select/__init__.py:57-64` (`STORAGE_FIELDS`).
- **Validators:** `_cv_input_select` at `homeassistant/components/input_select/__init__.py:84-93` enforces `initial` must be a member of `options`, and duplicate options are removed (via the `_remove_duplicates` helper at `homeassistant/components/input_select/__init__.py:67-81`).

#### `input_datetime`
- **Create fields:** `name: str` (required), `has_date: bool` (optional, default `False`), `has_time: bool` (optional, default `False`), `icon: str` (optional), `initial: str` (optional).
- **Schema source:** `homeassistant/components/input_datetime/__init__.py:61-67` (`STORAGE_FIELDS`).
- **Validators:** `has_date_or_time` at `homeassistant/components/input_datetime/__init__.py:70-75` enforces `has_date or has_time` — the "entity needs at least a date or a time" invariant referenced in the *Architecture* section. `CreateInputDatetimeParams` in WP02 carries a matching `@model_validator(mode="after")`. Because the HA defaults are `False/False`, a user who calls `CreateInputDatetimeParams(name="foo")` would hit HA's validator — Hassette should catch this locally.

#### `input_button`
- **Create fields:** `name: str` (required), `icon: str` (optional).
- **Schema source:** `homeassistant/components/input_button/__init__.py:30-33` (`STORAGE_FIELDS`).
- **Validators:** none.
- **Note:** Buttons are "press to trigger"-style helpers — no `initial` field, no state, no value. The `press` action is a service call (`input_button.press`), not WS CRUD. This is consistent with the design's choice to leave service-call shortcuts to `counter` only.

#### `counter`
- **Create fields:** `name: str` (required), `icon: str` (optional), `initial: int` (optional, default `0`, `cv.positive_int`), `maximum: int | None` (optional, default `None`), `minimum: int | None` (optional, default `None`), `restore: bool` (optional, default `True`), `step: int` (optional, default `1`, `cv.positive_int`).
- **Schema source:** `homeassistant/components/counter/__init__.py:51-59` (`STORAGE_FIELDS`).
- **Validators:** none at the schema level — the `Counter` class applies min/max clamping in its runtime properties, but the CRUD schema does not.
- **Note:** `counter` uses `CONF_MAXIMUM`/`CONF_MINIMUM` (the full words), not `max`/`min` like `input_number`. WP02 field names must match: `maximum: int | None`, `minimum: int | None`. This is a per-domain asymmetry to watch for.

#### `timer`
- **Create fields:** `name: str` (required, `cv.string` — note: NOT `vol.Length(min=1)` like the other domains), `icon: str` (optional), `duration: timedelta` (optional, default `0`, `cv.time_period` — HA parses strings like `"00:05:00"` or integers as seconds), `restore: bool` (optional, default `False`).
- **Schema source:** `homeassistant/components/timer/__init__.py:68-73` (`STORAGE_FIELDS`).
- **Validators:** none.
- **Note 1:** `timer.name` validation is weaker than the other domains (empty string is technically accepted by `cv.string`, though `_get_suggested_id` would produce an empty slug which `slugify` normalizes to `"unknown"`). WP02 can still require a non-empty name in the Pydantic model for Hassette callers — stricter client-side validation is fine.
- **Note 2:** `duration` is a `timedelta` server-side. WP02's `CreateTimerParams.duration` field should accept `str | int | timedelta` and serialize to the HA wire format (HA's `cv.time_period` accepts strings like `"00:05:00"`, integers as seconds, or dict form). Recommendation: accept `str | int` in the Pydantic model and let HA's coercion handle both; document `"HH:MM:SS"` as the canonical string format.
- **Note 3:** `timer` service actions (`timer.start`, `timer.pause`, `timer.cancel`, `timer.change`, `timer.finish`) are registered as **entity services** via `async_register_entity_service` at `homeassistant/components/timer/__init__.py:154-166`, NOT as WebSocket commands — consistent with the design's "no timer action wrappers" decision in the *Counter service-call shortcuts* section.

### HA error envelope structure

HA's WebSocket error responses are produced by `error_message` in `homeassistant/components/websocket_api/messages.py:81-104`:

```python
def error_message(
    iden: int | None,
    code: str,
    message: str,
    translation_key: str | None = None,
    translation_domain: str | None = None,
    translation_placeholders: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Return an error result message."""
    error_payload: dict[str, Any] = {
        "code": code,
        "message": message,
    }
    # In case `translation_key` is `None` we do not set it, nor the
    # `translation`_placeholders` and `translation_domain`.
    if translation_key is not None:
        error_payload["translation_key"] = translation_key
        error_payload["translation_placeholders"] = translation_placeholders
        error_payload["translation_domain"] = translation_domain
    return {
        "id": iden,
        **BASE_ERROR_MESSAGE,
        "error": error_payload,
    }
```

(`BASE_ERROR_MESSAGE` is defined at `homeassistant/components/websocket_api/messages.py:47-50` as `{"type": const.TYPE_RESULT, "success": False}`.)

So the wire format is:

```json
{
  "id": 42,
  "type": "result",
  "success": false,
  "error": {
    "code": "not_found",
    "message": "Unable to find input_boolean_id vacation_mode"
  }
}
```

**The `code` field is always present** inside `error` for HA-issued error responses — it is not optional. Translation fields (`translation_key`, `translation_domain`, `translation_placeholders`) are sometimes added but Hassette doesn't need them.

**Impact on `FailedMessageError.code`:** the field is populated for every HA-sent error. It is `None` only when `send_and_wait` synthesizes its own `FailedMessageError` for non-envelope failures (e.g., `TimeoutError` in `websocket_service.py:270` — the timeout path wraps the exception itself without going through `from_error_response`). WP03's tests should cover both: (1) an HA-sent error envelope produces `code == "<ha-code>"`, and (2) a transport timeout produces `code is None`.

**Update to `websocket_service.py:292-293`** — currently:

```python
err = (message.get("error") or {}).get("message", "Unknown error")
fut.set_exception(FailedMessageError.from_error_response(err, original_data=message))
```

Must become:

```python
error_obj = message.get("error") or {}
err = error_obj.get("message", "Unknown error")
code = error_obj.get("code")
fut.set_exception(FailedMessageError.from_error_response(err, code=code, original_data=message))
```

### Error codes Hassette may see

From `homeassistant/components/websocket_api/const.py:37-48`, the complete set of HA error codes is:

| Constant | String value | Likely in helper CRUD path? |
|---|---|---|
| `ERR_ID_REUSE` | `"id_reuse"` | No (protocol-level message ID reuse) |
| `ERR_INVALID_FORMAT` | `"invalid_format"` | **Yes** — schema validation failures in create/update |
| `ERR_NOT_ALLOWED` | `"not_allowed"` | Possibly (service-call shortcuts) |
| `ERR_NOT_FOUND` | `"not_found"` | **Yes** — `update`/`delete` with unknown ID |
| `ERR_NOT_SUPPORTED` | `"not_supported"` | No |
| `ERR_HOME_ASSISTANT_ERROR` | `"home_assistant_error"` | Possibly (generic HA errors) |
| `ERR_SERVICE_VALIDATION_ERROR` | `"service_validation_error"` | Possibly (counter service calls) |
| `ERR_UNKNOWN_COMMAND` | `"unknown_command"` | Only if Hassette sends a malformed `type` |
| `ERR_UNKNOWN_ERROR` | `"unknown_error"` | Catch-all |
| `ERR_UNAUTHORIZED` | `"unauthorized"` | Yes — create/update/delete are `require_admin` |
| `ERR_TIMEOUT` | `"timeout"` | HA-side timeout (distinct from Hassette's transport timeout) |
| `ERR_TEMPLATE_ERROR` | `"template_error"` | No |

**Important:** HA's helper CRUD path does **not** have a `"name_in_use"` error code. See the next section for what this means.

### HA does NOT reject duplicate create names — it silently suffixes

This is the single most consequential finding from WP01. `StorageCollection.async_create_item` at `homeassistant/helpers/collection.py:311-328` delegates ID assignment to `IDManager.generate_id` at `homeassistant/helpers/collection.py:98-108`:

```python
def generate_id(self, suggestion: str) -> str:
    """Generate an ID."""
    base = slugify(suggestion)
    proposal = base
    attempt = 1

    while self.has_id(proposal):
        attempt += 1
        proposal = f"{base}_{attempt}"

    return proposal
```

When a caller creates a helper with a name that slugifies to an existing ID, HA **auto-suffixes** the ID (`vacation_mode`, `vacation_mode_2`, `vacation_mode_3`, ...) and silently succeeds. There is no exception raised, no warning logged, and no error code surfaced. The `ws_create_item` handler at `collection.py:637-654` catches only `vol.Invalid` and `ValueError`, neither of which `generate_id` raises.

**This invalidates the design's original concurrent-bootstrap pattern.** An earlier draft of this design's `## Alternatives Considered` section included a "race-safe variant" that caught `FailedMessageError` with `e.code == "name_in_use"` and re-fetched, on the assumption that two concurrent creators of the same helper would collide at the HA server. HA will never produce `code == "name_in_use"`. Instead, the "losing" concurrent creator successfully creates a **second helper** with id `vacation_mode_2`, leaving two semantically-duplicate records in HA storage. The simple loop-over-`list_*`-then-create version exhibits the same behavior under concurrency — the check-then-create is not atomic, and neither call raises. There is nothing to "retry" because nothing failed.

**Design updates applied in WP01** (all revisions live in this same design doc):

1. **`## Alternatives Considered` → "Race-safe variant"**: removed entirely. The simple 5-line loop remains documented as the canonical pattern, with prose explaining HA's auto-suffix behavior and the naming-discipline mitigation (each app uses a helper name unique within the deployment, typically prefixed with the app identifier, and only one app owns provisioning for any given helper). Users who need strict cross-app uniqueness must coordinate outside the WS layer — the framework does not attempt to paper over HA's lack of atomic upsert.
2. **`## Architecture` → "Example programmatic error handling"**: rewritten. The previous example caught `e.code == "name_in_use"` on a `create_*` call; that code is dead, so the example now demonstrates catching `e.code == "not_found"` on an `update_*` call (a real error code that HA actually emits, verified in the "Error codes Hassette may see" table above). The new example also cross-references this section for the full trace.
3. **`## Documentation` → narrative guide**: updated to ship only the simple 5-line bootstrap pattern plus a "gotchas" section that explains HA's auto-suffix behavior and the naming-discipline recommendation. The previously-planned "Advanced: concurrent provisioning" section with a race-safe variant is deleted — it would have trained users to catch an error code that never fires.
4. **WP07**: updated to match the new design narrative. The WP no longer instructs the implementer to document a race-safe variant; it adds a "gotchas" bullet explaining HA auto-suffixing and citing this section for the trace. The Blocker list now flags any `e.code == "name_in_use"` snippet as BLOCKER.

**Consequential adjustments to other WPs:**

- **WP05's `RecordingApi.create_*`**: should match HA's auto-suffixing behavior for parity. When a test seeds `{"vacation_mode": ...}` and then calls `create_input_boolean(CreateInputBooleanParams(name="Vacation Mode"))`, the harness should produce id `vacation_mode_2`, not raise. The seed helper signature and the module-level `_slugify_helper_name` function are already in the design — `RecordingApi.create_*` just needs a collision-check loop that mirrors `IDManager.generate_id`.
- **WP05's `RecordingApi.delete_*`**: the design's original choice to `raise KeyError` on delete-of-nonexistent is now reconsidered. HA returns `ERR_NOT_FOUND` (not silent success), so strict-in-harness is correct in intent. The divergence is only in exception class: HA raises `FailedMessageError(code="not_found")` via the WS error envelope, the harness raises `KeyError`. The "HA delete-of-nonexistent behavior" section below recommends switching the harness to raise `FailedMessageError(code="not_found")` instead, so app tests using `pytest.raises(FailedMessageError)` work identically against the harness and real HA.

### HA slug-derivation rule

HA uses `homeassistant.util.slugify` to convert a create-time `name` into a stored `id`. Source at `homeassistant/util/__init__.py:41-46`:

```python
def slugify(text: str | None, *, separator: str = "_") -> str:
    """Slugify a given text."""
    if text == "" or text is None:
        return ""
    slug = unicode_slug.slugify(text, separator=separator)
    return "unknown" if slug == "" else slug
```

The `unicode_slug` alias is imported at `homeassistant/util/__init__.py:15` as `import slugify as unicode_slug` — this is the [`python-slugify`](https://pypi.org/project/python-slugify/) PyPI package (not the `awesome-slugify` variant, and not HA's own implementation). `python-slugify` applies these transformations by default:

- **Lowercases** the input
- **ASCII-fies** via unidecode (e.g., `"Café"` → `"cafe"`, `"ümlaut"` → `"umlaut"`)
- **Separator**: HA passes `separator="_"`, so spaces and most punctuation become `_`
- **Collapses** consecutive separators to a single underscore
- **Strips** leading/trailing separators
- **Drops** characters that don't map to an ASCII letter, digit, or the separator
- **No max length** — HA does not pass `max_length`

Edge-case handling from `homeassistant.util.slugify` itself:

- `slugify(None)` → `""`
- `slugify("")` → `""`
- `slugify("%%")` (i.e. input that `unicode_slug.slugify` reduces to empty) → `"unknown"` (HA's fallback)

**Example transformations** (verified mentally against `python-slugify`'s rules — WP05 should add unit tests to pin these):

| Input `name` | `slugify(name)` result |
|---|---|
| `"Vacation Mode"` | `"vacation_mode"` |
| `"Guest Bedroom #1"` | `"guest_bedroom_1"` |
| `"  Leading/trailing  "` | `"leading_trailing"` |
| `"Café Lights"` | `"cafe_lights"` |
| `"ÜberHelper"` | `"uberhelper"` |
| `"%%"` | `"unknown"` |
| `""` | `""` |
| `None` | `""` |

**Impact on WP05's `_slugify_helper_name`:** the design doc currently suggests `name.lower().replace(" ", "_")` as a fallback. This is **insufficient** — it doesn't handle unicode, punctuation, or collision-suffixing. WP05 should instead:

1. Check whether Hassette already has a `slugify` utility (`grep -r slugify src/hassette/` — at the time of WP01 there is no such utility in the repo, only the Jinja `entity_id_to_slug` filter in `tools/generate_docs_helper.py` and unrelated docs).
2. Add `python-slugify` as a runtime dependency OR vendor a minimal implementation that matches HA's rules.
3. **Recommendation:** add `python-slugify>=8.0` to `pyproject.toml` dependencies and call it with `separator="_"` — exactly mirroring HA's call. This is simpler, more robust, and zero-maintenance. WP02 should include the dependency bump. The cost is one small wheel (~20 KB) and the benefit is that WP05's harness produces byte-identical ids to real HA.
4. Wrap it in a helper like:

   ```python
   # src/hassette/test_utils/recording_api.py
   from slugify import slugify as _unicode_slug

   def _slugify_helper_name(name: str | None) -> str:
       """Mirror homeassistant.util.slugify for RecordingApi parity with HA."""
       if name == "" or name is None:
           return ""
       slug = _unicode_slug(name, separator="_")
       return "unknown" if slug == "" else slug
   ```
5. Also implement HA's collision-suffixing so that seeding `{"vacation_mode": ...}` and then `create_*` with `name="Vacation Mode"` produces `vacation_mode_2`:

   ```python
   def _generate_helper_id(existing_ids: set[str], name: str) -> str:
       base = _slugify_helper_name(name)
       if not base or base not in existing_ids:
           return base
       attempt = 2
       while f"{base}_{attempt}" in existing_ids:
           attempt += 1
       return f"{base}_{attempt}"
   ```

### HA delete-of-nonexistent behavior

At `homeassistant/helpers/collection.py:358-366`, `StorageCollection.async_delete_item` is:

```python
async def async_delete_item(self, item_id: str) -> None:
    """Delete item."""
    if item_id not in self.data:
        raise ItemNotFound(item_id)

    item = self.data.pop(item_id)
    self._async_schedule_save()

    await self.notify_changes([CollectionChange(CHANGE_REMOVED, item_id, item)])
```

`ItemNotFound` is defined at `homeassistant/helpers/collection.py:74-80`:

```python
class ItemNotFound(CollectionError):
    """Raised when an item is not found."""

    def __init__(self, item_id: str) -> None:
        """Initialize item not found error."""
        super().__init__(f"Item {item_id} not found.")
        self.item_id = item_id
```

The WS delete handler at `homeassistant/helpers/collection.py:733-746` catches it:

```python
except ItemNotFound:
    connection.send_error(
        msg["id"],
        websocket_api.ERR_NOT_FOUND,
        f"Unable to find {self.item_id_key} {msg[self.item_id_key]}",
    )
```

So **HA returns an error envelope with `code == "not_found"`** for delete-of-nonexistent — it does NOT silently succeed. The design's strict-not-silent choice for `RecordingApi.delete_*` is confirmed, and WP01's verification further refined the choice to use `FailedMessageError(code="not_found")` (matching real HA's exception class) rather than `KeyError`. The final behavior alignment is:

| Layer | Missing-id behavior |
|---|---|
| HA server | raises `ItemNotFound` → WS returns `{"success": false, "error": {"code": "not_found", ...}}` |
| `Api.delete_*` | `ws_send_and_wait` raises `FailedMessageError(code="not_found")` |
| `RecordingApi.delete_*` | raises `FailedMessageError(code="not_found")` — same exception class as real `Api`, so tests can use a single `except` block against both |

**WP05 implementer note:** both `update_*` and `delete_*` on `RecordingApi` raise `FailedMessageError(code="not_found")` on missing ids. This provides byte-identical exception-class parity with the real `Api` — callers doing `try: await api.delete_input_boolean("x"); except FailedMessageError as e: if e.code == "not_found": ...` work identically against harness and live HA. The previous design draft used `KeyError` for internal consistency with `update_*`; WP01's HA source verification showed HA raises the `not_found` error for both cases, so we adopt the single-exception approach throughout.

The same analysis applies to `update_*` on missing ids — HA raises `ItemNotFound` in `async_update_item` at `collection.py:330-356` (the `if item_id not in self.data: raise ItemNotFound(item_id)` guard on line 332-333), the WS handler `ws_update_item` at `collection.py:706-731` catches it and returns `ERR_NOT_FOUND`. Harness parity: `RecordingApi.update_*` raises `FailedMessageError(code="not_found")`.

### HA same-connection read-after-write consistency

An earlier draft of this design posed the question: "does HA's WebSocket API provide read-after-write consistency on the same WS connection?" — relevant at the time because a now-removed "race-safe variant" depended on re-fetching a helper immediately after a create. The answer is still worth recording for the simple bootstrap loop:

- `StorageCollection.async_create_item` (`collection.py:311-328`) writes to `self.data[item_id]` **before** `_async_schedule_save()` — the in-memory dict is updated synchronously.
- `ws_list_item` calls `self.storage_collection.async_items()` which returns `list(self.data.values())` — reading the same in-memory dict.
- A subsequent `{domain}/list` command from the same WS client on the same connection reads the updated dict. As long as both commands are processed in order (which HA guarantees per connection), the list response includes the newly-created item.

**Verdict: same-connection read-after-write is reliable.** Cross-connection consistency (two Hassette instances on separate connections racing) is likewise reliable because the underlying `StorageCollection.data` is a shared in-memory dict on the HA process — there's no replication lag.

This section is informational only — with the race-safe variant removed, the simple loop no longer depends on this guarantee for correctness, but users who want to call `list_*` immediately after `create_*` on the same `Api` instance can rely on it.

### Impact on implementation

Consolidated list of WP02–WP05 adjustments required or recommended based on WP01:

1. **WP02 (models)**:
   - `counter` uses `minimum`/`maximum` (not `min`/`max`) — field names must match.
   - `timer.duration` is a `timedelta` server-side via `cv.time_period`; Pydantic model field accepts `str | int | timedelta` and serializes as `"HH:MM:SS"` string.
   - `CreateInputNumberParams` / `CreateInputTextParams` model-level invariants (min < max, initial in range) should fire on create but be **skipped on update** because HA validates against merged data.
   - Add `python-slugify>=8.0` to `pyproject.toml` dependencies (needed by WP05).
2. **WP03 (exception changes)**:
   - `FailedMessageError.code` is **reliably populated** for every HA-sent error — it is only `None` on transport-level failures (timeouts). Tests should cover both cases.
   - Update `websocket_service.py:292-293` to extract `code` from `message["error"]["code"]`.
3. **WP04 (Api methods)**:
   - All 8 domains use `{domain}_id` as the ID key — no `_ID_KEYS_BY_DOMAIN` lookup needed. Use `f"{domain}_id"` interpolation.
   - Command names are `f"{domain}/list|create|update|delete"` uniformly.
   - `delete_*` response is `None` (no result payload) — no `_expect_*` call needed.
4. **WP05 (RecordingApi harness)**:
   - Implement `_slugify_helper_name` via `python-slugify` with `separator="_"` to match HA exactly.
   - Implement collision-suffixing in `create_*` to mirror `IDManager.generate_id` — concurrent-name creates produce `name_2`, `name_3`, ... instead of raising.
   - **Change `update_*` and `delete_*` to raise `FailedMessageError(code="not_found")` instead of `KeyError`** — this gives test code a single exception type that works against both harness and real HA. Update the "RecordingApi seed surface" section of this design doc accordingly in a design amendment (or fold into WP05's PR).
5. **Alternatives Considered → Race-safe bootstrap variant**: removed in WP01. HA never emits `code == "name_in_use"` — the branch was dead code. The section now documents only the simple 5-line loop plus prose explaining HA's auto-suffix behavior and the naming-discipline recommendation. The `## Architecture` example and the `## Documentation` narrative-guide description were updated in the same pass, and WP07's subtasks and blocker list were rewritten to match.

## Alternatives Considered

### A. Keep `ensure_helper` and fix its individual flaws

**Rejected.** Challenge review produced seven distinct findings against `ensure_helper`: TOCTOU race under concurrent app startup, matching by mutable `name` instead of stable `id`, `dict[str, Any]` return erasing type information, untestable via `RecordingApi`, round-trip breakage through `Update*Params` after HA upgrades, unbounded `list_*` calls scaling O(apps × domains), and first-run create→subscribe ordering gotchas. Each individually has a fix (asyncio.Lock, match on id, typed overloads, harness seed surface, `extra="ignore"`, session cache, docstring note). Collectively they reveal that the abstraction is wrong:

- The "convenience" the method provided was hiding a 4-line loop, not meaningful complexity
- Every "fix" layered another invariant on users (must not race, must match on id not name, must understand that the returned dict isn't round-trip-safe)
- The method's type return was strictly worse than the methods it wrapped
- It couldn't be unit-tested without a separate seed surface that was itself being deferred

Users who need the pattern write it themselves. The canonical form is a ~5-line loop:

```python
async def _ensure_vacation_mode(self) -> InputBooleanRecord:
    for record in await self.api.list_input_booleans():
        if record.id == "vacation_mode":
            return record
    return await self.api.create_input_boolean(
        CreateInputBooleanParams(name="vacation_mode", initial=False)
    )
```

This is the **only** pattern shipped in the narrative guide. An earlier draft of this design included a second "race-safe variant" that caught `FailedMessageError` with `e.code == "name_in_use"` and re-fetched, on the assumption that two concurrent creators of the same helper name would collide at the HA server and produce that error. **WP01 verified against HA source at tag `2026.4.1` that this assumption is wrong** — HA never emits `name_in_use` for helper CRUD. See the `## HA WebSocket Commands` → "HA does NOT reject duplicate create names" section for the full trace through `StorageCollection.async_create_item` → `IDManager.generate_id`.

**What HA actually does on concurrent create:** `IDManager.generate_id` slugifies the caller's `name`, checks `has_id(proposal)`, and if the base id is taken it appends `_2`, `_3`, ... until it finds an unused slot. Both concurrent creators succeed — one gets `vacation_mode`, the other gets `vacation_mode_2`. No exception is raised, no error code is emitted, and the losing caller has no way to detect it happened via the WS response alone. There is no race to "resolve" via catch-and-retry because the WS-layer error that pattern was guarding against does not exist.

**The correct mitigation is naming discipline, not catch-and-retry.** Each app should use a helper name that is unique within the deployment (e.g., prefix with the app's identifier, `myapp_vacation_mode`), and only one app should own provisioning for any given helper. If two apps genuinely need to share a helper, the shared-provisioner role belongs to one of them — typically a small bootstrap app that runs first — and the consumers read the resulting helper id via `list_*`. This is a code-level convention, not a runtime lock; attempting to enforce uniqueness inside the framework would require either a cross-app shared lock (out of scope) or an attribute-based lookup (a larger redesign that would change every `Create*Params` model).

If, in six months, real users ask for a framework-level helper with the concurrency/id-matching/testability all designed in from the start, we add it then. We do not ship a broken convenience method now in the hope that nobody will notice the seven edge cases.

### B. Hand-generate all `sync.py` wrappers

**Rejected.** Would violate the convention established in PRs #502 and #503 (recording facade codegen). The generator already handles AST-based import derivation and drift detection — bypassing it would reintroduce the drift bugs those PRs were built to prevent.

### C. Use a single giant `HelperClient` class attached to `Api.helpers`

**Rejected.** See "`Api` class responsibility and the monolith choice" above for the full rationale — generator constraint, caller ergonomics, consistency with existing `Api` monolith.

### D. Defer `counter` state model to a follow-up

**Rejected.** The `counter` helper CRUD methods and the missing `CounterState` are both touched by this issue. Shipping CRUD for a `counter` helper without the ability to read its state through the typed state registry would be an awkward gap. The state model is small (~30 LOC) and rides along.

### E. Stub new methods as `NotImplementedError` on `RecordingApi`

**Rejected.** The recent test-infrastructure PRs (#502, #503) were built specifically to avoid "this method isn't in the harness yet, file a follow-up" patterns. New `Api` methods must be first-class in `RecordingApi` — that's the point of the parity test and the codegen'd facade. Adding a `helper_definitions` seed surface is ~30 LOC of straightforward code and unlocks full unit-testability for any app that creates or reads helpers.

## Test Strategy

### Unit tests (`tests/unit/test_api_helper_models.py`)

- `CreateInputDatetimeParams` raises `ValidationError` when `has_date=False, has_time=False`
- `InputBooleanRecord.model_validate({"id": ..., "name": ..., "unknown_future_field": 123})` succeeds (validates `extra="allow"`)
- Each `Update*Params` class accepts an empty dict (all fields optional)
- `UpdateInputBooleanParams(**{"unknown_future_field": 123})` succeeds (validates `extra="ignore"`)

### Harness seed-surface tests (`tests/unit/test_recording_api_helpers.py`)

- `seed_helper` → `list_*` returns the seeded record
- `create_*` → `list_*` includes the new record
- `update_*` → `list_*` reflects the updated fields
- `delete_*` → `list_*` no longer includes the record
- `update_*` on unseeded `helper_id` raises `FailedMessageError(code="not_found")` with a diagnostic message (matches real HA)
- `delete_*` on unseeded `helper_id` raises `FailedMessageError(code="not_found")` with a diagnostic message (matches real HA)
- `create_*` records an `ApiCall` with the correct method name and kwargs
- Counter action methods record an `ApiCall` with the correct method name and `entity_id`

### Integration tests (`tests/integration/test_api_helpers.py`)

For each of the 8 domains, 4 tests:

1. **`list_*`** — patch `api.ws_send_and_wait` with `AsyncMock(return_value=[record_dict])`, assert return type is `list[{Domain}Record]` with correctly-parsed fields
2. **`create_*`** — patch `ws_send_and_wait` with `AsyncMock(return_value=record_dict)`, call `create_*` with a `Create*Params`, assert:
   - `ws_send_and_wait` was called with `type="{domain}/create"` and correct payload
   - Return value is a `{Domain}Record` with expected fields
3. **`update_*`** — same pattern, assert correct `type`, domain-specific ID key threading, and `exclude_unset=True` partial update behavior
4. **`delete_*`** — assert correct `type` and ID parameter, return is `None`

Plus:

- **`_expect_list` / `_expect_dict` helpers**: 2 tests — raise `TypeError` with context string when the WS result is the wrong shape
- **`_ws_helper_call` wrapper**: 4 tests — (1) propagates successful responses unchanged; (2) chains `FailedMessageError` with domain/operation context on failure; (3) preserves `code` and `original_data` attributes from the original exception through the chain; (4) sets `__cause__` correctly for traceback inspection
- **`FailedMessageError` construction**: 3 tests in `tests/unit/test_exceptions.py` — `FailedMessageError(msg)` works (backward compat); `FailedMessageError(msg, code="x", original_data={"y": 1})` stores attrs; `from_error_response(error="x", code="y", original_data={})` forwards all args
- **Counter service-call shortcut tests** (4 tests): patch `api.call_service`, assert correct `domain`/`service`/`target`/`return_response=True`; one test asserts that `FailedMessageError` raised by the underlying call propagates to the caller (regression test for the design's "return_response=True surfaces WebSocket-level failures" claim)
- **`CreateInputDatetimeParams` integration**: construct via `has_date=True`, verify `model_dump(exclude_unset=True)` contains only set fields

### Parity and drift gates (reused existing tests — extended, not new)

- `tests/unit/test_recording_api_write_parity.py::test_api_write_methods_covered_by_recording_api` — must pass after `_KNOWN_READ_METHODS` update (co-committed with `api.py` changes)
- **New**: `tests/unit/test_recording_api_protocol_parity.py::test_api_protocol_matches_api_methods` — compares `ApiProtocol` declared methods against `Api` public async methods
- `tests/unit/test_recording_sync_facade_generation.py::test_generator_check_mode_{api,recording}_exits_zero` — must pass after both generator targets regenerated

### Observability / logging contract

Every new method emits at least one log line:

- `ensure_helper`-style convenience patterns: N/A (we don't ship one)
- `list_*`: DEBUG with record count
- `create_*`: INFO with record id (creation is a state-changing event operators want in their logs by default)
- `update_*`: DEBUG with helper_id
- `delete_*`: DEBUG with helper_id
- Counter action methods: DEBUG with entity_id (these are high-frequency — INFO would spam)

## Open Questions

1. **No spec.md for this feature.** The caliper v2 convention expects `spec.md` before `design.md`. We're skipping that because the issue body + planner output + challenge pass together cover the same ground a spec would. If you want a formal spec, run `/mine.specify` first and regenerate this doc.

2. **(Removed during revision.)** The earlier draft had an open question about whether `RecordingApi` should get a helper-definitions seed surface or ship as NotImplementedError stubs. That's now decided: seed surface, no stubs. See "RecordingApi seed surface" above.

3. **(Removed during revision.)** The earlier draft asked whether `Create*Params` objects or `**kwargs` should be the create method signature. `**kwargs` was attractive only because it made `ensure_helper` dispatch simpler. With `ensure_helper` removed, the typed `Create*Params` object is the unambiguous choice — it gives Pydantic the natural place to put field validation (e.g., `CreateInputDatetimeParams`'s has_date/has_time invariant) and keeps method signatures stable across HA field additions.

## Impact

### Blast radius

- **Public API surface**: +35 methods on `Api` and +35 on `ApiSyncFacade` (generated). Pure additions, no behavior change to existing methods.
- **Models**: new `src/hassette/models/helpers/` package (8 files + `__init__.py`) and new `CounterState` in `models/states/`. Pure additions.
- **Test doubles**: `RecordingApi` grows by ~35 new methods, a new `helper_definitions` seed dict, and a new `ApiProtocol` entries. `AppTestHarness` grows by one public method (`seed_helper`). Parity test exclusion list grows by 8 names.
- **Generated files**: both `api/sync.py` and `test_utils/sync_facade.py` regenerated — these are checked into git and land in the PR diff.
- **No existing tests are expected to fail** outside of the drift/parity/protocol gates, which are exactly the gates designed to catch "you added a method but forgot to regenerate or add the parity stub".

### Dependencies to update

**Add `python-slugify` as a direct runtime dependency** (`pyproject.toml`). Used by WP05's `_slugify_helper_name` helper in `recording_api.py` to match HA's exact slug-derivation rule (HA itself uses `python-slugify` via `homeassistant.util.slugify` — verified in `## HA WebSocket Commands → HA slug-derivation rule`). The package is already present in `uv.lock` as a transitive dependency, but must be declared as direct so WP05's import is supported by the dependency graph. WP02 owns the `pyproject.toml` bump.

No other new third-party libraries. All other code uses existing `pydantic`, `whenever`, and stdlib.

### Documentation

- `docs/` (readthedocs) has API reference pages auto-generated from `Api` docstrings — the new methods will appear automatically
- One narrative guide: `docs/pages/advanced/managing-helpers.md` (consistent with existing advanced docs like `state-registry.md` and `dependency-injection.md`; the repo does not use a `docs/guides/` directory) — includes the **simple 5-line bootstrap pattern** as the worked example for self-provisioning apps, followed by a "Gotchas" section that explains HA's auto-suffix behavior (`IDManager.generate_id` silently appends `_2`, `_3`, ... on name collisions — verified in the `## HA WebSocket Commands` section above) and the naming-discipline recommendation (each app uses a helper name unique within the deployment, typically prefixed with the app identifier). The guide does **not** include a "race-safe variant" that catches `name_in_use`, because HA never emits that error code — see the `## HA WebSocket Commands` → "HA does NOT reject duplicate create names" section for the trace. This is in scope for the PR (not deferred) so users who discover the feature also discover the recommended pattern and the concurrency caveat together.

### Rollout

No migration, no config flags, no deprecations. Ship behind a single PR. Users on older HA versions may see `ValidationError` if HA's response schema drifts — the `extra="allow"` config on Record models protects against added fields, but a removed field would surface as a `ValidationError` at parse time. This is acceptable: HA releases do not typically remove helper fields, and if they do we want to know.
