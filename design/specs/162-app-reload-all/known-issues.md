# Known Issues

Real issues found while building this feature and intentionally left unfixed.

## KI-001: A watcher reload-all refused for a syntax error isn't re-queued

Status: open
Recorded: 2026-11-28 (4498)
Source: ship-challenge
Reason not fixed now: accepted-limitation
Affected files:
- src/hassette/core/app_lifecycle_reconcile.py

Issue:
When a watcher event needs a reload-all and the syntax precheck fails, only the reload-all part is dropped (D12 step 4). Nothing remembers it, so the reload-all runs again only on the next file event that needs one, or a manual Reload all. Fixing the file normally sends that event; an edit the watcher doesn't report (an atomic save it misses) leaves the apps on the old helper until one arrives.

Why deferred:
It is D12's ratified behavior, fixing the file normally heals it, and re-queuing would add state carried across watcher events.

Recommended follow-up:
If users report a fixed helper not reaching their apps until they touch another file, remember a refused watcher reload-all and run it on the next event.

Acceptance criteria:
- A watcher reload-all refused for a syntax error runs once the file compiles, even when the next event's paths alone wouldn't trigger one.

## KI-002: A reload-all that restarts no app doesn't say what it re-read

Status: open
Recorded: 2026-11-28 (4498)
Source: ship-challenge
Reason not fixed now: accepted-limitation
Affected files:
- wire/src/hassette_wire/apps.py

Issue:
With every app stopped, a manual reload-all still re-reads the config and evicts the app-code modules, but answers 200 with `apps: []` and zero counts. The caller can't tell that from a no-op.

Why deferred:
The case is rare, D1's behavior (stopped apps stay stopped) is correct, and an optional response field can be added later without breaking the released client.

Recommended follow-up:
If a deploy script needs to confirm the code was evicted with no app running, add an evicted-module count (or a config-reread flag) to `ReloadAllResponse` and the CLI summary.

Acceptance criteria:
- A reload-all with no tracked apps reports that it re-read the config and how many modules it evicted.
