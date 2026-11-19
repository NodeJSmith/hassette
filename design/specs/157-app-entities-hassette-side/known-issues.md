# Known Issues

Real issues found while building this feature and intentionally left unfixed.

## KI-001: A press during process exit can be reported dispatched without running

Status: open
Recorded: 2026-11-19 (4218)
Source: ship-challenge
Reason not fixed now: accepted-limitation
Affected files:
- src/hassette/core/app_lifecycle_instances.py
- src/hassette/core/integration_service.py

Issue:
Process exit takes no app-key lock. If it lands while an instance's integration commit is being written, the commit
still lands and `initialize_instance` then writes a late RUNNING. Until `clear_all` discards it,
`IntegrationService.dispatch_command` reads that RUNNING, so a press arriving in those milliseconds returns
`DISPATCHED` and is published to a bus that is being torn down.

Why deferred:
Only process exit reaches it, #4219's web API is shutting down at the same time, and `DISPATCHED` is documented as
not proof that the handler ran. A fourth admission check would also need a new outcome reason, since "stopped before
init" would be wrong for an instance whose commit landed. `shutdown_all`'s docstring names the limitation.

Recommended follow-up:
Re-check admission after the commit, with its own outcome reason, if #4219's dispatch route turns out to outlive
`AppHandler`'s stop stage.

Acceptance criteria:
- A press landing between a late RUNNING and `clear_all` returns `NOT_RUNNING`.

## KI-002: Two ledger invariants hold only outside narrow windows

Status: open
Recorded: 2026-11-19 (4218)
Source: ship-challenge
Reason not fixed now: accepted-limitation
Affected files:
- src/hassette/integration/integration.py

Issue:
`declare_with_handler` records the declaration and then awaits its listener's registration. A commit snapshot taken
in that gap, only possible from a declaring task that outlives `on_initialize`, commits the declaration without its
listener. Separately, while the commit is being written a handle reads its restored state or default, not the value
set during initialization, which shows once the commit lands.

Why deferred:
Both need an unusual interleaving (a leaked declaring task, or a read from another task during a write that takes
milliseconds), and neither loses stored data. Closing them means holding the commit snapshot on `Integration` and
reordering declaration after registration.

Recommended follow-up:
Close them if apps turn out to read handle state from listeners that fire while the commit is in flight.

Acceptance criteria:
- A read during the commit write returns the value set during initialization.
- No committed declaration lacks its listener.

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
