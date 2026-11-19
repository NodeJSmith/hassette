# Known Issues

Real issues found while building this feature and intentionally left unfixed.

## KI-003: An unparseable stored row of an instance that never commits again warns at every start

Status: open
Recorded: 2026-11-19 (4218)
Source: ship-challenge
Reason not fixed now: accepted-limitation
Affected files:
- src/hassette/core/integration_store.py

Issue:
A stored row whose declaration doesn't parse is skipped at load with a WARNING, and the instance's next commit
rewrites it. An instance that is configured but never commits (disabled, or declaring nothing so its commit is
skipped) keeps the row, and the WARNING repeats at every start.

Why deferred:
The row is already broken, the repeat is loud and harmless, and deleting it would destroy the only copy someone could
repair by hand.

Recommended follow-up:
Delete unparseable rows in the prune transaction if corrupt rows turn out to happen without manual database edits.

Acceptance criteria:
- An unparseable row warns once, then is gone.

## KI-004: A failed rollback of the integration commit leaves the writer connection's transaction state unknown

Status: open
Recorded: 2026-11-19 (4218)
Source: ship-challenge
Reason not fixed now: accepted-limitation
Affected files:
- src/hassette/core/integration_store.py
- src/hassette/core/database_sql.py

Issue:
`replace_instance_set` rolls back through `safe_rollback`, which logs and absorbs a storage error from the rollback
itself. The connection's transaction state is then unknown, so the next `BEGIN` from any writer can fail.

Why deferred:
It needs two storage failures in a row, and it is the documented behavior of every `safe_rollback` caller. A change
is a writer-wide policy, which belongs in the shared helper rather than in one caller.

Recommended follow-up:
If it ever happens, change `safe_rollback`'s policy for every writer in its own change.

Acceptance criteria:
- A failed rollback can't leave a later write running inside a stale transaction.
