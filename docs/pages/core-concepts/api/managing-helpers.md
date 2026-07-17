# Managing Helpers

Home Assistant helpers (`input_boolean`, `input_number`, `input_text`, `input_select`,
`input_datetime`, `input_button`, `counter`, `timer`) are persistent entities stored in
HA's `.storage/` directory. They survive restarts and appear in the HA UI.
`self.api.helpers` is a [`HelperClient`][hassette.api.helpers.HelperClient] with 4 generic
CRUD methods (`list`, `create`, `update`, `delete`) covering all 8 domains, plus 3 counter
shortcuts (`increment`, `decrement`, `reset`). Each CRUD method dispatches to the right
domain from its argument — a domain string for `list`/`delete`, a typed params model for
`create`/`update` — and returns the domain-specific record type.

## Creating a Helper on Startup

The most common pattern provisions a helper once during [`on_initialize`](../apps/lifecycle.md) (the app startup hook), then holds the
returned record — a Pydantic model with the helper's `id`, `name`, and configuration — for the app's lifetime. Because helpers persist across restarts, the
idempotent approach checks for an existing record before creating:

```python
--8<-- "pages/core-concepts/api/snippets/managing-helpers/crud_operations.py:bootstrap"
```

`helpers.list("input_boolean")` fetches all `input_boolean` records from Home Assistant. The loop exits early if a matching id is found, so `helpers.create(...)` only runs on first startup.

!!! warning "Concurrent provisioning"
    When two apps run the same list-then-create sequence simultaneously, both may pass
    the gap between list and create. HA does not raise an error. It silently appends `_2`
    to the second helper's id. No error code signals the collision. The correct mitigation
    is naming discipline: each helper's name should carry a prefix unique to its owning app
    (for example, `motionapp_cycles` rather than `cycles`), and only one app should ever
    provision a given helper.

## Common Pitfalls

**HA auto-suffixes on name collision.** When `helpers.create(...)` receives a `name` that
slugifies to an `id` already in storage, HA does not raise an error. It silently
appends `_2`, `_3`, and so on until it finds a free slot. Two concurrent creators of
the same-named helper both succeed, leaving two semantically-duplicate records. There
is no `name_in_use` error code to catch. Each helper's name should carry a prefix
unique to its owning app, and only one app should provision it.

**`CreateInputDatetimeParams` requires `has_date=True` or `has_time=True`.** Both
fields `False` raises `ValidationError` at construction time, before any network call.
`UpdateInputDatetimeParams` does not enforce this constraint on partial updates, because
the counterpart field retains its stored value.

**`exclude_unset=True` vs explicit `None`.** All CRUD methods serialize params with
`model_dump(exclude_unset=True)`. A field omitted from the constructor is not sent to
HA; HA keeps its stored value. A field passed as `None` is sent as `null`, which may
clear the value on the HA side. Omitting `icon` and passing `icon=None` produce
different wire payloads.

**`CounterRecord` and [`CounterState`][hassette.models.states.counter.CounterState] are two different models.** `CounterRecord`
represents stored configuration, returned by `helpers.list("counter")`, `helpers.create(...)`, and
`helpers.update(...)`. `CounterState` represents the live runtime value, returned by
`get_state("counter.mycounter")`. Changes to stored config (for example, updating
`initial`) take effect after an HA restart. `helpers.increment`, `helpers.decrement`,
and `helpers.reset` are immediate but do not modify stored config.

**Helper creation persists across HA restarts.** HA stores helpers in `.storage/`.
A helper created during `on_initialize` is still present on the next run. The
idempotent bootstrap pattern in [Creating a Helper on Startup](#creating-a-helper-on-startup)
exists for this reason.

**[`RetryableConnectionClosedError`][hassette.exceptions.RetryableConnectionClosedError] is a second exception class callers may receive.**
A WebSocket disconnect mid-CRUD propagates as `RetryableConnectionClosedError`, not
[`FailedMessageError`][hassette.exceptions.FailedMessageError]. Exception handlers that target only `FailedMessageError` miss
this case. A broader `except` clause covering both exception types handles it
correctly.

## CRUD Operations

The create, list, update, and delete pattern is identical across all 8 domains. The
examples below use `input_boolean`; the same `helpers.*` methods apply to every domain in
the [reference table](#all-supported-domains) — only the domain string or params model
type changes.

### Create

```python
--8<-- "pages/core-concepts/api/snippets/managing-helpers/create_helper.py"
```

The returned `InputBooleanRecord` carries the `id` HA assigned, typically the slugified
form of the `name` passed in, for example `"vacation_mode"`. Storing or logging the `id`
is useful, as `helpers.list("input_boolean")` is the only retrieval path if the id is not cached.

### List

```python
--8<-- "pages/core-concepts/api/snippets/managing-helpers/crud_operations.py:list"
```

`helpers.list(domain)` returns all records for the domain, regardless of which app created them.

### Update

```python
--8<-- "pages/core-concepts/api/snippets/managing-helpers/crud_operations.py:update"
```

`helpers.update(helper_id, params)` accepts a `helper_id` string (the stored `id` field, not the
display name) and a partial params object. Only fields present in the params object are
sent to HA; absent fields retain their stored values. A `helper_id` that does not exist
raises `FailedMessageError(code="not_found")`.

### Delete

```python
--8<-- "pages/core-concepts/api/snippets/managing-helpers/crud_operations.py:delete"
```

`helpers.delete(domain, helper_id)` returns `None`. It raises `FailedMessageError(code="not_found")` if the id
is absent from storage.

### All Supported Domains

`HelperClient` exposes 7 methods. `list` and `delete` dispatch on a domain string; `create`
and `update` dispatch on the params model's type — passing `CreateCounterParams` routes the
call to the `counter` domain and returns a `CounterRecord`, no domain argument needed.

| Method | Signature | Dispatches on |
|---|---|---|
| `helpers.list` | `list(domain: HelperDomain) -> list[Record]` | `domain` string |
| `helpers.create` | `create(params: Create*Params) -> Record` | `type(params)` |
| `helpers.update` | `update(helper_id: str, params: Update*Params) -> Record` | `type(params)` |
| `helpers.delete` | `delete(domain: HelperDomain, helper_id: str) -> None` | `domain` string |
| `helpers.increment` | `increment(entity_id: str) -> None` | n/a (counter only) |
| `helpers.decrement` | `decrement(entity_id: str) -> None` | n/a (counter only) |
| `helpers.reset` | `reset(entity_id: str) -> None` | n/a (counter only) |

`HelperDomain` is the literal union of the 8 supported domain strings: `input_boolean`,
`input_number`, `input_text`, `input_select`, `input_datetime`, `input_button`, `counter`,
`timer`. Passing an unsupported string is a type error under Pyright, since `HelperDomain`
rejects it at the call site before the code ever runs.

`@overload` declarations on each method narrow the return type per domain — `helpers.list("counter")`
returns `list[CounterRecord]`, not a generic `list[BaseModel]`. The params models for
`create` and `update` live in `hassette.models.helpers` (for example
`CreateInputBooleanParams`, `UpdateCounterParams`) and need an explicit import at each call
site — see the collapsible reference table below for the full list.

## Counter Shortcuts

`helpers.increment`, `helpers.decrement`, and `helpers.reset` operate on the live entity
state, not stored configuration. They call HA's `counter` service domain and take effect
immediately:

```python
--8<-- "pages/core-concepts/api/snippets/managing-helpers/counter_shortcuts.py"
```

Timer actions (`timer.start`, `timer.pause`, `timer.cancel`) are not wrapped as
shortcuts. They go through `call_service` directly:

```python
--8<-- "pages/core-concepts/api/snippets/managing-helpers/timer_call_service.py:timer"
```

Counter shortcuts are high-frequency operations. The shorter call site makes a difference
when a handler runs on every motion event. Timer actions are typically one-off; the full
`call_service` signature makes the intent explicit at those call sites.

## Testing

`AppTestHarness` exposes a `seed_helper(record)` method that pre-populates the harness's
helper store. The harness derives the domain from the record's class, so no `domain`
parameter is needed. The typed record is sufficient:

```python
--8<-- "pages/core-concepts/api/snippets/managing-helpers/testing_harness.py"
```

Seeded records are stored as deep copies. Later mutations to the record passed into
`seed_helper` do not affect harness state.

??? note "Typed model reference"

    Each domain exposes three Pydantic model classes in `hassette.models.helpers`:

    | Model | Purpose | `extra` policy |
    |---|---|---|
    | `{Domain}Record` | Stored configuration returned by `helpers.list`, `helpers.create`, and `helpers.update` | `"allow"`: unknown HA fields pass through |
    | `Create{Domain}Params` | Required and optional fields for a create call | `"forbid"`: typos raise `ValidationError` at construction |
    | `Update{Domain}Params` | Partial update payload with all fields optional | `"ignore"`: extra fields from round-tripped records are silently dropped |

    The two CRUD methods that accept a params object (`helpers.create` and `helpers.update`) serialize it with
    `model_dump(exclude_unset=True)`, not `exclude_none`. Omitting a field and explicitly
    setting it to `None` produce different wire payloads.

## See Also

- [API Overview](index.md): when to use `self.api` vs `self.states`
- [API Methods](methods.md): `call_service` for timer actions and other service calls
- [Testing Apps](../../testing/index.md): full harness documentation
- [Apps](../apps/index.md): lifecycle hooks including `on_initialize`
