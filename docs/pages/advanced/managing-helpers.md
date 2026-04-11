# Managing Helpers

Home Assistant **helpers** (`input_boolean`, `input_number`, `input_text`, `input_select`,
`input_datetime`, `input_button`, `counter`, `timer`) are persistent entities stored in
HA's `.storage/` directory — they survive restarts and are visible in the HA UI. Apps that
want to self-provision their own helpers (a vacation-mode toggle, a motion-event cycle
counter, a user-facing mode selector) can create and manage them directly through typed
`Api` methods. The full surface is 32 CRUD methods covering 8 domains, plus 3 counter
service-call shortcuts.

## Typed Models

Each helper domain exposes three Pydantic model classes in `hassette.models.helpers`:

| Model | Purpose | `extra` policy |
|---|---|---|
| `{Domain}Record` | Stored configuration returned by `list_*`, `create_*`, and `update_*` | `"allow"` — unknown HA fields pass through |
| `Create{Domain}Params` | Required and optional fields for a create call | `"forbid"` — typos raise `ValidationError` at construction |
| `Update{Domain}Params` | Partial update payload (all fields optional) | `"ignore"` — extra fields from round-tripped records are silently dropped |

All three CRUD methods that accept a params object serialize it with
`model_dump(exclude_unset=True)`, not `exclude_none`. This means omitting a field and
explicitly setting it to `None` produce different wire payloads — see
[Gotchas](#gotchas) for the full implications.

## Creating a Helper

```python
from hassette import App, AppConfig
from hassette.models.helpers import CreateInputBooleanParams, InputBooleanRecord


class VacationModeApp(App[AppConfig]):
    async def on_initialize(self) -> None:
        record: InputBooleanRecord = await self.api.create_input_boolean(
            CreateInputBooleanParams(name="vacation_mode", initial=False)
        )
        self.logger.info("Provisioned vacation_mode helper: %s", record.id)
```

The returned `InputBooleanRecord` carries the `id` HA assigned (usually the slugified
form of the `name` you passed, e.g. `"vacation_mode"`). Store or log it if you need it
later — `list_input_booleans()` is the way to retrieve it again.

## Listing Helpers

```python
records: list[InputBooleanRecord] = await self.api.list_input_booleans()
for record in records:
    self.logger.debug("Found input_boolean: id=%s name=%s", record.id, record.name)
```

## Updating a Helper

`update_*` accepts a `helper_id` (the stored `id` field, not the display name) and a
partial params object. Only the fields you pass are sent to HA:

```python
from hassette.models.helpers import UpdateInputBooleanParams

await self.api.update_input_boolean(
    "vacation_mode",
    UpdateInputBooleanParams(icon="mdi:palm-tree"),
)
```

Passing `helper_id` that does not exist raises `FailedMessageError(code="not_found")`.

## Deleting a Helper

```python
await self.api.delete_input_boolean("vacation_mode")
```

Returns `None`. Raises `FailedMessageError(code="not_found")` if the id is absent.

## Idempotent Bootstrap (the Simple Pattern)

Your app might not know whether it has been run before and whether its helper already
exists. The correct pattern is a short list-then-create loop:

```python
from hassette.models.helpers import CreateInputBooleanParams, InputBooleanRecord


async def _ensure_vacation_mode(self) -> InputBooleanRecord:
    for record in await self.api.list_input_booleans():
        if record.id == "vacation_mode":
            return record
    return await self.api.create_input_boolean(
        CreateInputBooleanParams(name="vacation_mode", initial=False)
    )
```

This pattern is correct when **one app in the deployment owns provisioning** for this
helper — which is the recommended topology. Call it from `on_initialize` and keep the
returned record for the rest of the app's lifetime.

!!! warning "Concurrent provisioning"
    If two apps can run `_ensure_vacation_mode` simultaneously, both may pass the
    list-then-create gap and both will succeed — but HA will silently auto-suffix the
    second helper's id to `vacation_mode_2`. There is no error code to catch; see
    [Gotchas](#gotchas) for the full explanation and the recommended mitigation (naming
    discipline, not retry logic).

## Counter Service-Call Shortcuts

`increment_counter`, `decrement_counter`, and `reset_counter` operate on the **live
entity state**, not stored configuration. They call HA's `counter` service domain and
take effect immediately:

```python
from hassette.models.helpers import CreateCounterParams, CounterRecord


class MotionCycleApp(App[AppConfig]):
    _cycle_counter_id: str = "motionapp_cycles"

    async def on_initialize(self) -> None:
        await self._ensure_cycle_counter()
        self.bus.on_state_change(
            "binary_sensor.motion",
            handler=self.on_motion,
        )

    async def on_motion(self) -> None:
        await self.api.increment_counter(f"counter.{self._cycle_counter_id}")

    async def _ensure_cycle_counter(self) -> None:
        for record in await self.api.list_counters():
            if record.id == self._cycle_counter_id:
                return
        await self.api.create_counter(
            CreateCounterParams(name="motionapp_cycles", initial=0)
        )
```

`timer` actions (`timer.start`, `timer.pause`, `timer.cancel`) are **not** wrapped as
shortcuts. Call them through `api.call_service` directly:

```python
await self.api.call_service("timer", "start", target={"entity_id": "timer.away_mode"})
```

The asymmetry is intentional. Counter increment/decrement/reset are high-frequency
operations that benefit from short, readable call sites. Timer actions are typically
one-off and the full `call_service` signature makes the intent explicit.

## Testing with the Harness

`AppTestHarness` exposes a `seed_helper(record)` method that pre-populates the harness's
helper store. The harness derives the helper domain from the record's class, so there is
no `domain` parameter — just pass the typed record.

```python
from hassette.models.helpers import InputBooleanRecord
from hassette.test_utils import AppTestHarness

from myapp import VacationModeApp


async def test_vacation_mode_creates_helper_on_first_run():
    async with AppTestHarness(VacationModeApp, config={}) as harness:
        # No helper was seeded, so the app's idempotent-bootstrap check
        # falls through to create_input_boolean.
        harness.api_recorder.assert_call_count("create_input_boolean", 1)


async def test_list_returns_seeded_helper():
    async with AppTestHarness(VacationModeApp, config={}) as harness:
        harness.seed_helper(
            InputBooleanRecord(id="vacation_mode", name="Vacation Mode", initial=False)
        )
        records = await harness.api_recorder.list_input_booleans()
        assert len(records) == 1
        assert records[0].name == "Vacation Mode"
```

Seeded records are stored as deep copies, so later mutations to the record you passed
in won't leak into harness state.

## Gotchas

- **HA auto-suffixes on name collision.** When you call `create_input_boolean` (or any
  `create_*`) with a `name` that slugifies to an `id` already in storage, HA does **not**
  raise an error. Home Assistant's collection storage silently appends `_2`, `_3`, and so
  on until it finds a free slot. Two concurrent creators of the same-named helper will
  both succeed, leaving two semantically-duplicate records in storage. There is no
  `name_in_use` error code to catch. The correct mitigation is **naming discipline**:
  prefix every helper with an identifier unique to its owning app (e.g., `motionapp_cycles`
  rather than `cycles`) so collisions cannot happen in the first place, and ensure only
  one app ever provisions any given helper.

- **`CreateInputDatetimeParams` requires `has_date=True` or `has_time=True`.** Both
  `False` raises `ValidationError` at construction time — before any network call is
  made. `UpdateInputDatetimeParams` does **not** enforce this constraint on partial
  updates because the counterpart field stays at its stored value.

- **`exclude_unset=True` vs explicit `None`.** All CRUD methods serialize params with
  `model_dump(exclude_unset=True)`. A field you omit entirely is not sent to HA (HA keeps
  its stored value). A field you pass as `None` is sent as `null`, which may clear the
  value. These produce different behavior: if you want to leave `icon` unchanged, omit it
  from the constructor; if you want to clear it, pass `icon=None`.

- **`CounterRecord` and `CounterState` are two different models.** Reading the current
  counter value at runtime uses `await self.api.get_state("counter.mycounter")`, which
  returns a `CounterState`. Changing the counter's configured `initial` value uses
  `await self.api.update_counter("mycounter", UpdateCounterParams(initial=0))`, which
  returns a `CounterRecord`. Changes to stored config take effect on the next HA restart;
  `increment_counter` / `decrement_counter` / `reset_counter` are immediate but do not
  change stored config.

- **Helper creation persists across HA restarts.** HA stores helpers in `.storage/`,
  unlike volatile entity state. A helper you create in `on_initialize` today will still
  be there next week. The idempotent-bootstrap pattern above exists precisely because of
  this: on the second run your helper is already there.

- **`RetryableConnectionClosedError` is a second exception class callers may receive.**
  A WebSocket disconnect mid-CRUD propagates as `RetryableConnectionClosedError`, not
  `FailedMessageError`. Callers whose `except FailedMessageError` block contains cleanup
  logic should add a separate `except (FailedMessageError, RetryableConnectionClosedError):`
  or wrap in a broader `except Exception:` where appropriate.

## Not Included / Out of Scope

- **Subscribe commands.** Hassette does not currently expose a typed wrapper for HA's
  helper config-change subscribe commands. Apps that need to react to stored-config
  changes in real time should subscribe to entity state changes instead, or fall back to
  raw `ws_send_and_wait()`.

## See Also

- [API Reference — `hassette.api.Api`][hassette.api.Api] — full method signatures for all
  32 CRUD methods and 3 counter shortcuts
- [Testing Your Apps](../testing/index.md) — general harness documentation
