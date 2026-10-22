# Known Issues

Real issues found while building this feature and intentionally left unfixed.

## KI-001: A new client against a pre-schema-3 server gets unfiltered log lines

Status: open
Recorded: 2026-10-22 (3096)
Source: ship-challenge
Reason not fixed now: accepted-limitation
Affected files:
- client/src/hassette_client/client.py

Issue:
`get_recent_logs` and `get_execution_logs` send `author` when the caller sets it. A v0.59 server (API schema 2) ignores it, so `author="framework"` returns every line. When `author` is unset, which is the default call, that server returns everything instead of the default view. The response can't say which semantics applied.

Why deferred:
The schema-floor contract in `client/src/hassette_client/version.py` already declares that every parameter the client sends needs a schema-3 server, and `check_server_version` enforces it for callers that opt in. The failure returns extra lines, not fewer.

Recommended follow-up:
If integrators hit this, either have the client call `check_server_version` once before its first request, or list per-method schema requirements on the python-client docs page.

Acceptance criteria:
- A client talking to a schema-2 server can't silently get a different log view than it asked for.

## KI-002: The framework-lines toggle doesn't sync across browser tabs

Status: open
Recorded: 2026-10-22 (3096)
Source: ship-challenge
Reason not fixed now: accepted-limitation
Affected files:
- frontend/src/state/store.ts

Issue:
`showAllFrameworkLogs` is read from localStorage once, when the store initializes. Turning it on in one tab changes every log view in that tab, but other open tabs keep the old value until they reload.

Why deferred:
Every persisted UI preference (`theme`, `sidebarCollapsed`, `timePreset`) loads the same way, and none listens for `storage` events. Syncing only this one would be the inconsistent choice.

Recommended follow-up:
If cross-tab sync is wanted, add one `storage` event listener in the store that refreshes all persisted preferences together.

Acceptance criteria:
- Changing any persisted preference in one tab updates other open tabs without a reload.

## KI-003: The default log view's ERROR floor matches level names, not numeric levels

Status: open
Recorded: 2026-10-22 (3096)
Source: ship-challenge
Reason not fixed now: accepted-limitation
Affected files:
- src/hassette/core/telemetry/helpers.py
- src/hassette/types/types.py

Issue:
The default view keeps framework lines whose stored `level` is in `ERROR_AND_ABOVE_LEVEL_NAMES`. A framework-authored line at a custom level name above ERROR (via `logging.addLevelName`) is hidden by the default view.

Why deferred:
Hassette never logs at a non-standard level, and third-party loggers fall outside the `hassette` namespace, so they're authored `app` and the floor doesn't apply to them. A numeric floor would need `log_records` to store `levelno`.

Recommended follow-up:
If custom levels on Hassette's loggers become a real use, store `levelno` on `log_records` and compare numerically.

Acceptance criteria:
- A framework line at any level numerically at or above ERROR shows in the default view.
