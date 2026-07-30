# Event Priority

Every listener carries a priority tier: `"critical"`, `"high"`, `"normal"`, or
`"low"`. The tier decides two things when the bus runs out of dispatch capacity —
which listeners get a slot first, and which ones lose their event instead of
waiting for one.

Hassette assigns the tier from the listener's topic, so most apps never set it.

```python
--8<-- "pages/core-concepts/bus/snippets/event_priority.py:derived_default"
```

Below saturation the tier changes nothing. Every listener runs, in tier order.

## The Default Tiers

Hassette classifies a listener's topic at registration time.

| Topic | Tier |
|---|---|
| Service status, WebSocket connected/disconnected, app state changed | `critical` |
| Service calls, automation triggered, script started, file watcher, app load completed | `high` |
| `sensor.*` state changes, handler execution telemetry | `low` |
| Everything else, including all other state changes | `normal` |

`sensor` is the only entity domain classified as `low`. It is the highest-volume
domain in a typical Home Assistant install, and its readings are cumulative — the
next reading supersedes a shed one. `binary_sensor` stays at `normal`: motion and
door contacts are edge-triggered, so a shed event is information that never
comes back.

A topic Hassette does not recognize — including any topic passed to `Bus.emit` —
classifies as `normal`. Unknown topics are never shed.

## What Each Tier Does Under Saturation

The bus is saturated when `lifecycle.max_concurrent_dispatches` handlers (default
50) are already in flight. At that point each tier resolves differently against
the listener's [`backpressure`](backpressure.md) policy.

| Tier | Under saturation |
|---|---|
| `critical` | Waits for a slot. Overrides `backpressure="drop_newest"`. |
| `high` | Defers to `backpressure`. |
| `normal` | Defers to `backpressure`. |
| `low` | Sheds the event. Overrides `backpressure="block"`. |

The two extremes override the policy; the middle two leave it alone. A `high` or
`normal` listener behaves exactly as it did before tiers existed.

## Overriding the Tier

Passing `event_priority=` at registration wins over the topic-derived default.
All four registration methods accept it — `on_state_change`,
`on_attribute_change`, `on_call_service`, and `on()`.

The override matters most for a `sensor` listener that cannot afford to lose
events:

```python
--8<-- "pages/core-concepts/bus/snippets/event_priority.py:opt_out_of_shedding"
```

`event_priority="normal"` puts the listener back under its `backpressure` policy,
so the default `block` makes it lossless again.

The override runs the other way too. `critical` guarantees a listener runs even
when it declared `drop_newest`:

```python
--8<-- "pages/core-concepts/bus/snippets/event_priority.py:critical_never_sheds"
```

An invalid tier raises `ValueError` at registration, listing the valid values.

## Ordering

Within one event's fan-out, the bus hands out dispatch slots in tier order:
`critical`, then `high`, then `normal`, then `low`. Listeners in the same tier
keep the existing order — most specific route first, then by the bus's
registration priority.

Ordering matters under saturation, where the last free slot goes to the highest
tier that wants it. Below saturation it only affects the order handler tasks
start in; they run concurrently either way.

## Observability

A shed event increments the same counter as a `drop_newest` drop. The monitoring
UI's Handlers tab shows it as **Backpressure Dropped**, and the web API exposes
it as `backpressure_dropped_count`. Both are live-only — the count resets on app
reload and process restart.

The resolved tier is persisted to the `listeners` table and shown as a `tier`
chip on the listener detail panel for anything other than `normal`.

A rising drop count on a `low` listener means the bus reached saturation while
that listener's events were arriving. Raising
`lifecycle.max_concurrent_dispatches`, speeding up slow handlers, or cutting
event volume addresses the cause; raising the listener's tier only moves the loss
somewhere else.

## Composition

`event_priority` and [`backpressure`](backpressure.md) both act at the dispatch
acquire gate, and the table above is the whole interaction between them.

`mode`, `debounce`, and `throttle` act inside the handler invoker, downstream of
that gate. An event shed by tier never reaches them.

## See Also

- [Backpressure Policy](backpressure.md): `backpressure=` — block or drop under saturation
- [Execution Modes](execution-modes.md): `mode=` — handler overlap behavior
- [Subscription Methods](methods.md): full parameter reference
