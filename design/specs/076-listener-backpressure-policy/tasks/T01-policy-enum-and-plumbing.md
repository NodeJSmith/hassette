---
task_id: "T01"
title: "Add BackpressurePolicy enum and thread it through subscription plumbing"
status: "planned"
depends_on: []
implements: ["FR#1", "FR#2", "FR#9", "FR#10", "AC#6", "AC#7"]
---

## Summary
Create the `BackpressurePolicy` StrEnum (`BLOCK`, `DROP_NEWEST`) and thread it from the public
subscription API down to the `ListenerOptions` struct. This is the foundational plumbing: the enum, a
default constant, the `Options` TypedDict key for the typed `on_*` methods, an explicit parameter on
both `Bus.on()` and `_on_internal`, the `ListenerOptions.backpressure` field with string coercion, and
config-equality (`config_matches`/`diff_fields`) so re-registration drift is detected. No dispatch
enforcement yet — that is T02. Default resolves to `BLOCK` so existing apps are unaffected.

## Target Files
- modify: `src/hassette/types/enums.py`
- modify: `src/hassette/bus/options.py`
- modify: `src/hassette/bus/listeners.py`
- modify: `src/hassette/bus/bus.py`
- modify: `tests/unit/bus/test_listeners.py`
- read: `design/specs/076-listener-backpressure-policy/design.md`
- read: `design/specs/076-listener-backpressure-policy/tasks/context.md`

## Prompt
Implement the policy enum and its plumbing per the design doc's `## Architecture` §1, §2, §3.

1. **Enum** (`src/hassette/types/enums.py`): add `class BackpressurePolicy(StrEnum)` with members
   `BLOCK = auto()` and `DROP_NEWEST = auto()`, each with a one-line docstring (mirror `ExecutionMode`
   at `enums.py:58`). Add a module constant `DEFAULT_BACKPRESSURE_POLICY: str =
   BackpressurePolicy.BLOCK.value` alongside the existing `DEFAULT_OVERLAP_MODE`. Do NOT add
   `KEEP_LATEST`.

2. **Options TypedDict** (`src/hassette/bus/options.py`): add a `backpressure: BackpressurePolicy | str`
   key with a docstring matching the `mode` entry's style. This covers `on_state_change`,
   `on_attribute_change`, and `on_call_service` (they take `**opts: Unpack[Options]`).

3. **ListenerOptions** (`src/hassette/bus/listeners.py`): add
   `backpressure: BackpressurePolicy = BackpressurePolicy.BLOCK` to the `ListenerOptions` dataclass
   (it is `@dataclass(slots=True)` and NOT frozen — match it). Extend `__post_init__` (around
   `listeners.py:114`) to coerce a raw string into the enum and raise a clear `ValueError` listing the
   valid values, mirroring the `mode` coercion at lines 117-122.

4. **config equality** (`src/hassette/bus/listeners.py`): add a `backpressure` comparison to
   `diff_fields` (around line 560, alongside the `mode` check) and the matching `config_matches`, so an
   `if_exists="skip"` re-registration with a changed policy reports `backpressure` as drift.

5. **bus.py — explicit param on BOTH methods.** `_on_internal` (`bus.py:521-540`) and `Bus.on()`
   (`bus.py:429-445`) have fully explicit named params — there is NO `**opts` catch-all. Mirror how
   `mode` is threaded:
   - Add `backpressure: BackpressurePolicy | str | None = None` to `_on_internal`'s signature (next to
     `mode` at line 533) and pass `backpressure=backpressure` into the `ListenerOptions(...)`
     construction (`bus.py:600`). Resolve an omitted value to `BLOCK` (the `ListenerOptions` field
     default handles this if you pass `BackpressurePolicy.BLOCK` when `None`).
   - Add the same explicit param to `Bus.on()` (next to `mode` at line 441) and forward it explicitly
     in `on()`'s `_on_internal(...)` call (`bus.py:497-515`, next to `mode=mode` at line 508).

6. **Tests** (`tests/unit/bus/test_listeners.py`): add tests covering: invalid `backpressure` string
   raises `ValueError` naming valid values; `if_exists="skip"` re-registration with a changed policy
   reports `backpressure` in the drift list; omitted policy defaults to `BLOCK`.

Follow `tasks/context.md` Convention Examples for enum and coercion style.

## Focus
- `ExecutionMode` (`enums.py:58`) is the exact template for the enum, the default constant, and the
  string coercion. Read it first.
- `Bus.on()` is the ONE public method not backed by `Options` — if you only edit the TypedDict,
  `self.bus.on(topic=..., backpressure="drop_newest")` raises `TypeError`. Both edits (5) are required.
- `_on_internal` forwards into `ListenerOptions(...)` at `bus.py:600` — verify the exact construction
  call and add the kwarg there.
- The tier-aware default logic at `bus.py:567-580` is for `mode` only; `backpressure` has a flat
  `BLOCK` default — do NOT add a tier-resolution block for it.
- `ListenerOptions.__post_init__` already rejects `debounce`+`throttle` and `once`+`debounce`; do NOT
  add forbidden-combination rules for `backpressure` (DROP_NEWEST composes fine with debounce/throttle/
  mode — they act at different points).

## Verify
- [ ] FR#1: `Bus.on()` accepts an explicit `backpressure` kwarg, and `on_state_change`/
  `on_attribute_change`/`on_call_service` accept it via `Options`; all reach `ListenerOptions`.
- [ ] FR#2: An omitted `backpressure` results in `ListenerOptions.backpressure == BackpressurePolicy.BLOCK`.
- [ ] FR#9: A subscription with `backpressure="bogus"` raises `ValueError` naming the valid policies.
- [ ] FR#10: `diff_fields`/`config_matches` treat `backpressure` as a config field; a skip-re-register
  with a changed policy reports `backpressure` as drift.
- [ ] AC#6: Test asserts the `ValueError` on an invalid policy string.
- [ ] AC#7: Test asserts `if_exists="skip"` drift on a changed `backpressure` value.
