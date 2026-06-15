# Execution Modes

The `mode` parameter controls what happens when a trigger fires while a prior
invocation of the same handler is still running. Four modes are available,
matching Home Assistant's automation mode names.

```python
--8<-- "pages/core-concepts/bus/snippets/execution_modes.py:mode_parameter_basic"
```

All four bus registration methods — `on_state_change`, `on_attribute_change`,
`on_call_service`, and `on()` — accept `mode=`.

## The Four Modes

### `single` — drop while running (app default)

`single` is the default for app handlers. When a trigger fires while the prior
invocation is still running, the bus drops the re-fire. The running invocation
continues uninterrupted.

```python
--8<-- "pages/core-concepts/bus/snippets/execution_modes.py:single_implicit"
```

`D.StateNew[...]` is dependency injection — Hassette extracts and converts the
new state into the handler parameter automatically. See
[Writing Handlers](handlers.md) for the full annotation reference.

The re-fire is logged at DEBUG. No WARNING is emitted — this is expected
behavior, not an error. The running handler sees no interruption.

`single` is the right choice for handlers that mutate shared state, call a slow
service, or hold a resource. One invocation at a time prevents state corruption
and duplicate side effects.

### `restart` — cancel and replace

`restart` cancels the running invocation when a new trigger arrives, then
starts a fresh one with the new event.

```python
--8<-- "pages/core-concepts/bus/snippets/execution_modes.py:restart"
```

The cancelled invocation receives `CancelledError` at its next `await`. Making
handlers cancellation-safe is the author's responsibility — the framework cancels
the task, but cleanup logic inside the handler must be idiomatic Python
(`try/finally` or `contextlib.suppress`).

`restart` is the right choice for "latest wins" patterns: a search-as-you-type
handler, a preview renderer, or any scenario where only the most recent trigger
matters.

!!! warning "Cancelled invocations have side effects"
    A handler cancelled mid-run may have already mutated state or called a
    service. The framework provides no automatic rollback. Handlers that mutate
    state mid-run need cancellation handling (`try/finally` or
    `contextlib.suppress`). `single` or `queued` avoid partial execution
    entirely.

### `queued` — serialize in arrival order

`queued` runs every trigger, one at a time, in the order they arrived. Triggers
that arrive while an invocation is running are held and dispatched sequentially
after the current invocation completes.

```python
--8<-- "pages/core-concepts/bus/snippets/execution_modes.py:queued"
```

The queue holds at most 10 pending triggers. When the queue is full, the newest
trigger is dropped and logged at DEBUG. Already-queued triggers are unaffected.
This cap prevents unbounded memory growth on high-frequency triggers feeding a
slow handler.

`queued` is the right choice when every event must be processed and the order
matters: audit logging, sequential command dispatch, or anything where skipping
an event would leave the system in an incorrect state.

### `parallel` — concurrent (framework default)

`parallel` imposes no overlap guard. Multiple invocations of the same listener
run concurrently. This is the behavior that all handlers had before execution
modes were introduced, and it is what framework-internal listeners default to.

```python
--8<-- "pages/core-concepts/bus/snippets/execution_modes.py:parallel"
```

`parallel` is the right choice for stateless, idempotent handlers, or handlers
where each invocation manages its own isolated resources.

## Default Mode: Tier-Aware

The default mode depends on the *tier* — who registered the listener. App
handlers and framework-internal listeners get different defaults.

Framework-internal listeners are the bus subscriptions Hassette registers for
itself — not through `self.bus.*` in an app — to run its own services.

| Registration tier | Default mode | Why |
|---|---|---|
| App handler (`self.bus.*`) | `single` | Prevents a handler from running twice at once in user automations |
| Framework-internal listener | `parallel` | Preserves concurrent behavior required by the framework |

An explicit `mode=` always overrides the tier default.

Framework-internal listeners — the service supervisor, the state cache, the
runtime query service — depend on concurrent dispatch. The tier split mirrors
Home Assistant, where automation modes apply to user automations only.

??? note "Migrating from pre-1.0 concurrent behavior"
    Before execution modes were introduced, all handlers ran concurrently. An
    app handler that relied on that behavior can restore it explicitly:

    ```python
    --8<-- "pages/core-concepts/bus/snippets/execution_modes.py:migrating_parallel"
    ```

## Observability

### Suppressed and dropped counts

Each listener with a non-`parallel` mode tracks two live counters:

- **Suppressed** — triggers dropped by `single` while the handler was running.
- **Dropped** — triggers discarded by `queued` when the queue was at its cap.

These counts appear in the monitoring UI's Handlers tab when non-zero. They are
live-only diagnostics — held in memory, reset to zero when the process restarts,
never persisted to the database.

A non-zero suppressed count on a `single` handler indicates re-fires are
arriving faster than the handler completes. If that represents lost work,
consider `queued`. If it represents expected deduplication, `single` is correct.

### Stall detection

A handler that holds a `single` or `queued` guard (the lock that enforces
one-at-a-time execution) longer than 60 seconds without completing emits a
WARNING. This is the only WARNING the execution mode feature generates.
Suppressed and dropped events always log at DEBUG.

The per-listener `timeout` still applies and ultimately releases the guard when
it fires. The stall WARNING is an early signal, independent of the timeout.

### Mode in the monitoring UI

The mode is persisted for each listener and displayed as a chip in the app
detail Handlers tab. The mode chip is visible alongside invocation counts and
last-seen timestamps.

## Composition

### With `debounce` and `throttle`

Rate limiting (`debounce`, `throttle`) and `mode` operate at different points
in the dispatch pipeline.

- Rate limiting governs **whether an invocation starts** — debounce delays
  start until quiet, throttle limits start frequency.
- `mode` governs **what happens when a started invocation overlaps** with the
  next trigger.

Both can be active at the same time and do not conflict:

```python
--8<-- "pages/core-concepts/bus/snippets/execution_modes.py:debounce_single"
```

A debounced trigger that finally fires starts an invocation. If the handler
is still running when the next debounced trigger fires, `single` drops it.
`restart` would cancel and replace. The two mechanisms compose naturally.

### With `once=True`

A `once=True` listener fires at most once. The once-guard short-circuits in
the dispatch path before the mode guard runs — a concurrent re-fire hits the
once-check and returns immediately, never reaching the mode logic. `mode` has
no behavioral effect when combined with `once=True`.

```python
--8<-- "pages/core-concepts/bus/snippets/execution_modes.py:once_mode"
```

### With `duration`

Duration listeners fire their handler only after the state has held for the
configured period. The mode guard applies at that delayed dispatch point — when
the hold elapses and the handler is called — not when the trigger first arrives.

```python
--8<-- "pages/core-concepts/bus/snippets/execution_modes.py:duration_single"
```

A second motion event arriving while the first hold timer is running resets
the timer. If two hold timers expire close together and the handler is still
running from the first, `single` drops the second dispatch.

## See Also

- [Subscription Methods](methods.md): full parameter reference, including
  `debounce`, `throttle`, `once`, `timeout`, `duration`, and `if_exists`
- [Writing Handlers](handlers.md): handler patterns and dependency injection
- [Filtering & Predicates](filtering.md): `where=` predicates and conditions
