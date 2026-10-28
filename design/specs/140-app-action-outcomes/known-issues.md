# Known Issues

Real issues found while building this feature and intentionally left unfixed.

## KI-001: An action on an app with zero configured instances answers 200 with an empty `outcomes` list

Status: open
Recorded: 2026-10-28 (3111)
Source: ship-challenge
Reason not fixed now: accepted-limitation
Affected files:
- src/hassette/web/routes/apps.py
- src/hassette/core/app_lifecycle_start_stop.py

Issue:
A manifest whose `app_config` normalizes to no instances gives a start or stop no targets. `finish()` returns `()`, `_problem_code_for(())` is `None`, and the route answers 200 with `outcomes: []`, though D1 says a request never gets a 200 with no outcomes.

Why deferred:
Accepted at the ship-time challenge (Finding 5) as rare: nothing was targeted, so the response isn't false, and nothing is lost.

Recommended follow-up:
If it starts happening, have `_run_app_action` answer `app_not_found` when the operation returns no outcomes.

Acceptance criteria:
- A start, stop or reload of an app with zero configured instances answers 404 `app_not_found`.

## KI-002: A whole-app start or reload that raises mid-initialization leaves registered, never-initialized instances

Status: open
Recorded: 2026-10-28 (3111)
Source: ship-challenge
Reason not fixed now: accepted-limitation
Affected files:
- src/hassette/core/app_lifecycle_start_stop.py

Issue:
The whole-app catch in `start_app`/`reload_app` only fails the undecided slots. Instances `create_instances` registered stay registered, so a later start reports them `succeeded`, "already running", without their having initialized. The per-instance path shuts such a phantom down. `main` had the same gap.

Why deferred:
Accepted at the ship-time challenge (Finding 6): only a hassette bug reaches it, and a stop or reload recovers it.

Recommended follow-up:
Shut down any instance this request registered that never initialized, the way `_create_instance_unlocked` does.

Acceptance criteria:
- After a whole-app start that raised partway, the registry holds no instance that never initialized.

## KI-003: A reload of a blocked app hides its stop half's failure from `detail`

Status: open
Recorded: 2026-10-28 (3111)
Source: ship-challenge
Reason not fixed now: accepted-limitation
Affected files:
- src/hassette/web/routes/apps.py

Issue:
A reload of an `--app`-blocked app answers 409 `app_blocked` with a fixed `detail`, even when its stop half failed or flagged an instance. D3 says the `detail` names every instance that didn't succeed. The failure is still in `problem.outcomes`, the apps-page badge and the server log.

Why deferred:
Accepted at the ship-time challenge (Finding 7): it needs a blocked app that is still running and a failing stop at once.

Recommended follow-up:
When `AppBlockedError` or `AppRemovedError` carries a non-succeeded outcome, append the `action_detail` text to the fixed detail.

Acceptance criteria:
- A blocked reload whose stop half failed names that instance and its failure in `detail`.

## KI-004: An unexpected raise early in a reload's create half turns a flagged index's `refused` into a plain `failed`

Status: open
Recorded: 2026-10-28 (3111)
Source: ship-challenge
Reason not fixed now: accepted-limitation
Affected files:
- src/hassette/core/app_lifecycle_common.py

Issue:
`begin_create_half` clears the flagged index from the decided set. If hassette raises before the create-half gate re-records the refusal, `fail_undecided` writes `failed` with `needs_restart: false` over the stop half's `refused`, so that one response says 500 instead of 409 for an instance the registry still flags.

Why deferred:
Accepted at the ship-time challenge (Finding 8): the window is narrow, only a hassette bug reaches it, and the registry flag stays correct.

Recommended follow-up:
Have `_write` keep a slot with `needs_restart` true against a later plain failure.

Acceptance criteria:
- A reload that raises between `begin_create_half` and the gate still reports a flagged index `refused` with `needs_restart: true`.

## KI-005: `stop_app` and `stop_instance` don't catch unexpected exceptions around their bookkeeping

Status: open
Recorded: 2026-10-28 (3111)
Source: ship-challenge
Reason not fixed now: accepted-limitation
Affected files:
- src/hassette/core/app_lifecycle_start_stop.py

Issue:
`start_app`, `reload_app`, `start_instance` and `reload_instance` wrap their locked bodies. The two stops wrap only the teardown, so a bug in target naming, the refusal step or `finish` would reach the route as a 500 `internal_error` without outcomes, after the stop ran.

Why deferred:
Accepted at the ship-time challenge (Finding 9): nothing there can raise today, and a 500 for a hassette bug is honest.

Recommended follow-up:
Wrap the locked bodies of `stop_app` and `stop_instance` the way `start_app` is wrapped.

Acceptance criteria:
- A raise in a stop's bookkeeping returns one `failed` outcome per target instead of an `internal_error`.

## KI-006: The `needs_restart` docstrings don't say the app's other instances were acted on

Status: open
Recorded: 2026-10-28 (3111)
Source: ship-challenge
Reason not fixed now: accepted-limitation
Affected files:
- wire/src/hassette_wire/problems.py
- client/src/hassette_client/errors.py

Issue:
A whole-app action on an app with one flagged instance answers 409 `needs_restart` though its siblings were stopped, started or reloaded. The `NEEDS_RESTART` and `NeedsRestartError` docstrings describe only the flagged instance; `python-client.md` documents the sibling effect.

Why deferred:
Accepted at the ship-time challenge (Finding 12): the docs page and the "Not retryable" docstring already cover it.

Recommended follow-up:
Add one sentence to those docstrings and `client.action()`'s Raises section: the other instances were acted on, so don't resend a reload blindly.

Acceptance criteria:
- An IDE reader of `NeedsRestartError` learns the siblings were acted on.
