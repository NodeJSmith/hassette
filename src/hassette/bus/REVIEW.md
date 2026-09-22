# REVIEW.md — bus/

## Natural Key Consistency
The natural key `(app_key, instance_index, name, topic)` is defined in
`_listener_natural_key()` in `src/hassette/bus/bus.py`, matches the SQL unique
index in `src/hassette/migrations_sql/001.sql`, and is replicated in the
`INSERT ... ON CONFLICT` upsert in `src/hassette/core/telemetry/repository.py`.
When any of these three definitions changes, do the other two still match?

## Removal Path Parity
`Bus.remove_listener()` and the `_on_listener_removed()` callback in
`src/hassette/bus/bus.py` share the `mark_listener_cancelled` DB spawn, guarded
by `was_present` to avoid double-writes. Does a concurrent once-fire during
shutdown still produce exactly one `removed_at`/`retired_at` write per listener,
or can the timing window allow both paths to write?

## Guard Release on Sealed Bucket
`Listener.cancel()` spawns `release_guard()` via `task_bucket.spawn()` in
`src/hassette/bus/listeners.py`. The sealed-bucket path during force-terminal
teardown intentionally leaves the guard unreleased (documented as an accepted
gap). Does any change make the sealed path reachable *outside* force-terminal
teardown, or regress the normal unsealed drain of `_dispatch_pending` futures?

## Backpressure vs Execution Mode Telemetry
`backpressure` gates at the dispatch semaphore in
`src/hassette/core/bus_service.py`, while `mode` gates inside
`HandlerInvoker.dispatch()` in `src/hassette/bus/listeners.py`. A `DROP_NEWEST`
listener in `queued` mode has two independent drop paths. Do `backpressure_dropped`
and `guard.dropped` counters both appear in `src/hassette/web/models.py`'s
`ListenerWithSummary`, or does one path lose its telemetry?

## Duration Hold Predicate Consistency
`DurationConfig.hold_predicate` in `src/hassette/bus/listeners.py` is built from
`hold_preds` by including `changed_to` predicates but excluding transition
predicates (`StateFrom`, `StateDidChange`). Does
`src/hassette/bus/duration_timer.py`'s cancel-event evaluation use this same
predicate set, or does it re-evaluate with a different subset?
