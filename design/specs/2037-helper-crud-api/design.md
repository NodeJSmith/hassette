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

Without this wrapper, a failed `create_input_boolean(name="vacation_mode")` produces a log line like `"FailedMessageError: Name is already in use"` with no hint about which domain, name, or operation was involved. With the wrapper, the log line reads `"input_boolean/create failed for {'name': 'vacation_mode'}: Name is already in use"`, AND the caller can still do `except FailedMessageError as e: if e.code == "name_in_use": ...` because the structured fields are preserved through the chain.

Call sites pass `self` as the first argument: `await _ws_helper_call(self, "input_boolean", "create", **params.model_dump(exclude_unset=True))`.

**Example programmatic error handling** (not required, but now possible):

```python
try:
    await self.api.create_input_boolean(
        CreateInputBooleanParams(name="vacation_mode", initial=False)
    )
except FailedMessageError as e:
    if e.code == "name_in_use":
        # Recover gracefully — helper already exists, update instead
        for record in await self.api.list_input_booleans():
            if record.id == "vacation_mode":
                await self.api.update_input_boolean(
                    record.id,
                    UpdateInputBooleanParams(initial=False),
                )
                break
    else:
        # Includes transport timeouts, disconnects, and other failures where
        # HA never returned an error envelope — `e.code is None` for those
        # cases. They are not recoverable via helper CRUD retry and fall
        # through to `raise`.
        raise
```

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
- **`create_{domain}(params)`** — records an `ApiCall`, constructs `{Domain}Record(id=_slugify_helper_name(params.name), **params.model_dump(exclude_unset=True))` where `_slugify_helper_name` is a **module-level function defined in `src/hassette/test_utils/recording_api.py`** (NOT in `api.py` — it is harness-only logic; the real `Api.create_*` methods never slugify because HA assigns the id server-side). The function normalizes the display name to HA's ID format. A caller who does `create_input_boolean(CreateInputBooleanParams(name="Vacation Mode"))` then `update_input_boolean("vacation_mode", ...)` sees consistent behavior between harness and real HA. WP01 verifies HA's exact slug rule — if hassette already has a slugify utility, reuse it; otherwise a small local implementation in `recording_api.py` is fine (`name.lower().replace(" ", "_")` handles the common cases; edge cases like punctuation need the WP01 rule).
- **`update_{domain}(helper_id, params)`** — records an `ApiCall`, constructs a new record via `existing.model_copy(update=params.model_dump(exclude_unset=True))` (immutability), replaces `helper_definitions[domain][helper_id]`, returns the new record. **Raises `KeyError` with a diagnostic message** if `helper_id` is not in the seed dict — tests that expect an update on nonexistent state fail fast with a clear message rather than silently succeeding.
- **`delete_{domain}(helper_id)`** — records an `ApiCall`, removes from `helper_definitions[domain]`. **Raises `KeyError` with a diagnostic message** on missing `helper_id`, consistent with `update_*`. The earlier draft proposed silent ignore "matching HA behavior," but real HA's `DictStorageCollectionWebsocket` delete-of-nonexistent behavior is not actually silent — it returns an error response. WP01 verifies the exact HA behavior; the default is strict (raise) because strict-in-harness catches bugs that lax-in-harness would hide. Internal consistency with `update_*` is a secondary but important reason.
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
7. **HA's delete-of-nonexistent behavior**: does `{domain}/delete` with an unknown ID return an error response, or silently succeed? This validates (or refutes) the design's choice to have `RecordingApi.delete_*` raise `KeyError` strictly.

Results land in a `## HA WebSocket Commands` section of this design doc (added during WP01) and drive:
- An `_ID_KEYS_BY_DOMAIN: dict[str, str]` lookup table in `api.py` if HA is not consistent across domains. If HA IS consistent, we can use plain string interpolation; but the verification must happen either way.
- A module-level `_slugify_helper_name(name: str) -> str` function in **`src/hassette/test_utils/recording_api.py`** (harness-only; real `Api.create_*` methods never slugify because HA assigns the id server-side). Verify via `grep -r slugify src/hassette/` whether hassette already has a slugify utility; if so, reuse it, otherwise a small local implementation is fine.

If possible, add at least one `@pytest.mark.requires_ha` integration smoke test that exercises `create`/`update`/`delete` against a real HA instance for at least one domain — to catch ID key mismatches that mocked tests cannot.

## Alternatives Considered

### A. Keep `ensure_helper` and fix its individual flaws

**Rejected.** Challenge review produced seven distinct findings against `ensure_helper`: TOCTOU race under concurrent app startup, matching by mutable `name` instead of stable `id`, `dict[str, Any]` return erasing type information, untestable via `RecordingApi`, round-trip breakage through `Update*Params` after HA upgrades, unbounded `list_*` calls scaling O(apps × domains), and first-run create→subscribe ordering gotchas. Each individually has a fix (asyncio.Lock, match on id, typed overloads, harness seed surface, `extra="ignore"`, session cache, docstring note). Collectively they reveal that the abstraction is wrong:

- The "convenience" the method provided was hiding a 4-line loop, not meaningful complexity
- Every "fix" layered another invariant on users (must not race, must match on id not name, must understand that the returned dict isn't round-trip-safe)
- The method's type return was strictly worse than the methods it wrapped
- It couldn't be unit-tested without a separate seed surface that was itself being deferred

Users who need the pattern write it themselves. Two variants:

**Simple version (default)** — fine for the vast majority of apps. ~5 lines:

```python
async def _ensure_vacation_mode(self) -> InputBooleanRecord:
    for record in await self.api.list_input_booleans():
        if record.id == "vacation_mode":
            return record
    return await self.api.create_input_boolean(
        CreateInputBooleanParams(name="vacation_mode", initial=False)
    )
```

**Race-safe variant (advanced pattern, concurrent provisioning only)** — use when two or more apps in the same deployment might self-provision the **same** helper concurrently (e.g., both apps launched via `asyncio.gather` in `on_initialize` and both call `_ensure_vacation_mode`). This narrow case is rare but when it hits, the simple version produces a `FailedMessageError` with `code == "name_in_use"` on the losing caller. The safe variant catches exactly that code and re-fetches:

```python
async def _ensure_vacation_mode(self) -> InputBooleanRecord:
    # First pass: check for an existing record
    for record in await self.api.list_input_booleans():
        if record.id == "vacation_mode":
            return record
    try:
        return await self.api.create_input_boolean(
            CreateInputBooleanParams(name="vacation_mode", initial=False)
        )
    except FailedMessageError as e:
        if e.code != "name_in_use":
            # Transport failure, permission error, validation error — not a race.
            # Surface it to the caller; don't mask real errors as "another app won."
            raise
        # Race: another caller won. Re-fetch and return their record.
        for record in await self.api.list_input_booleans():
            if record.id == "vacation_mode":
                return record
        # Re-fetch missed after a successful concurrent create — indicates
        # WS read-after-write eventual consistency. Re-raise so the caller
        # gets a clear error rather than a silent wrong result.
        raise
```

**Critical**: the safe variant uses `if e.code != "name_in_use": raise`, NOT a bare `except FailedMessageError:`. A bare except would swallow timeouts, permission errors, and malformed payloads as if they were races — exactly the debugging hell the improved `FailedMessageError.code` was added to prevent.

The **simple version is the default pattern** promoted in the narrative guide. Most hassette deployments have many apps but only one app provisions any given helper — the race only occurs when two apps happen to bootstrap the same named helper, which is a code smell on the user's side (you probably want one shared app or a coordinator). The race-safe variant is documented but labeled as "only needed if you are certain two apps will provision the same helper concurrently."

Neither version is "as convenient" as `ensure_helper("input_boolean", "vacation_mode")`, but both are **honest code** — the caller can see what's happening, decide whether they need to guard against concurrency, and choose matching semantics. Apps that need many helpers can factor their own private helper in their base class. The framework does not ship an `ensure_helper` because getting concurrency, id-matching, and type safety correct inside a framework-level abstraction is a larger scope than this PR, and doing any of them partially would be worse than not shipping the abstraction at all.

**WP01 verification item**: the race-safe variant's "re-fetch after a successful concurrent create" path assumes HA's WebSocket API provides read-after-write consistency on the same WS connection. If two separate Hassette instances on separate WS connections race, the losing instance's re-fetch may not yet see the winning instance's record. WP01 should document HA's actual behavior here; if read-after-write is not guaranteed across connections, the race-safe pattern needs a retry loop with timeout, not a single re-fetch.

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
- `update_*` on unseeded `helper_id` raises `KeyError` with a diagnostic message
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

None. No new third-party libraries. All code uses existing `pydantic`, `whenever`, and stdlib.

### Documentation

- `docs/` (readthedocs) has API reference pages auto-generated from `Api` docstrings — the new methods will appear automatically
- One narrative guide: `docs/guides/managing-helpers.md` — includes the **simple 5-line bootstrap pattern as the default** worked example for self-provisioning apps, plus an "Advanced: concurrent provisioning" section with the race-safe 13-line variant for the narrow case where multiple apps might bootstrap the same helper simultaneously. The advanced section explicitly notes the `if e.code != "name_in_use": raise` narrowing requirement, so readers don't introduce a bare `except` that masks real transport errors. This is in scope for the PR (not deferred) so users who discover the feature also discover the recommended pattern and the concurrency caveat together.

### Rollout

No migration, no config flags, no deprecations. Ship behind a single PR. Users on older HA versions may see `ValidationError` if HA's response schema drifts — the `extra="allow"` config on Record models protects against added fields, but a removed field would surface as a `ValidationError` at parse time. This is acceptable: HA releases do not typically remove helper fields, and if they do we want to know.
