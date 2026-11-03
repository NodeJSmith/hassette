# Known Issues

Real issues found while building this feature and intentionally left unfixed.

## KI-001: A stale `instance_index` query parameter answers for the whole app

Status: open
Recorded: 2026-11-02 (3100)
Source: ship-challenge
Reason not fixed now: accepted-limitation
Affected files:
- src/hassette/web/dependencies.py

Issue:
A script or a released 0.61 client that still sends `instance_index` gets app-wide numbers with a 200, because FastAPI ignores unknown query parameters. No test pins this.

Why deferred:
D1 ratified it and the upgrading note states it. A 422 would be migration-only detection code, which this project skips before v1, and the hazard is a one-time upgrade with recoverable wrong numbers.

Recommended follow-up:
None unless a stale caller reports being misled. Then answer 422 on the seven routes that take an instance filter.

Acceptance criteria:
- A leftover `instance_index` answers 422, if this is ever picked up.

## KI-002: A link to a just-added instance can land on the parent page

Status: open
Recorded: 2026-11-02 (3100)
Source: ship-challenge
Reason not fixed now: accepted-limitation
Affected files:
- frontend/src/pages/app-detail.tsx

Issue:
`isAddressableInstance` checks the cached manifest. A valid `?instance=` for a name added seconds ago, before the `APP_LOAD_COMPLETED` refetch lands, is dropped from the URL with no notice.

Why deferred:
The window is seconds long, the parent page lists the instances one click away, the race predates this change, and skipping the correction during a fetch narrows the window without closing it.

Recommended follow-up:
None unless someone hits it. Then skip the correction while the manifest query is fetching.

Acceptance criteria:
- A fresh link opened during a manifest refetch keeps its `?instance=`, if this is ever picked up.

## KI-003: Rows stored with no name can't be told apart by instance

Status: open
Recorded: 2026-11-02 (3100)
Source: ship-challenge
Reason not fixed now: accepted-limitation
Affected files:
- src/hassette/migrations_sql/020.sql

Issue:
On `log_records` and `blocking_events` rows with a NULL `instance_name`, the dropped index was the only value distinguishing instances. D7 covers blocking rows; this also applies to log rows.

Why deferred:
The value lost is a positional integer the UI never showed, on a minority of rows that age out with retention. Backfilling would put placeholder names in front of users, and the ledger leaves backfilling out of scope.

Recommended follow-up:
None. The rows expire by themselves.

Acceptance criteria:
- No NULL-name rows remain after one retention window.
