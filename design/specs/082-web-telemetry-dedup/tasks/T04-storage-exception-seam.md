---
task_id: "T04"
title: "Translate storage errors to TelemetryUnavailableError (#1114)"
status: "planned"
depends_on: ["T03"]
implements: ["FR#7", "FR#8", "FR#9", "FR#10", "AC#6", "AC#7"]
---

## Summary
Fix the architectural root beneath #1108: stop the HTTP layer from catching raw storage
exceptions. Add a `TelemetryUnavailableError` domain exception, translate storage errors into it at
every `TelemetryQueryService` read path, narrow `db_degrades_to` (and the category-C/D inline
catches) to that one type, and delete `DB_ERRORS` from the HTTP layer. This is one atomic task —
the translation and the catch-type swap must land together, or handlers stop catching the errors
the service now raises. It carries the cluster's one intended behavior change: a non-DB
`ValueError` in a handler body now surfaces as a 500 instead of a swallowed 503.

## Target Files
- modify: `src/hassette/exceptions.py` (add `TelemetryUnavailableError`)
- modify: `src/hassette/core/telemetry/query_service.py` (translate in `execute()`)
- modify: `src/hassette/core/telemetry/summary_queries.py` (cover the `get_all_app_summaries`
  direct-`_db.execute` transaction, ~lines 215-228)
- modify: `src/hassette/web/dependencies.py` (`db_degrades_to` catches `TelemetryUnavailableError`;
  remove `DB_ERRORS`)
- modify: category-C/D inline catches: `src/hassette/web/routes/apps.py`,
  `src/hassette/web/routes/telemetry.py` (`dashboard_app_grid`), `src/hassette/web/routes/executions.py`
- read: `design/specs/082-web-telemetry-dedup/design.md` (`## Architecture → #1108b (#1114)`)
- read: all three query mixins under `src/hassette/core/telemetry/` for the read-path audit
- create/modify: tests for the seam (translation, footgun-fixed, dashboard_app_grid degradation)

## Prompt
Implement the storage→domain exception seam from the design's `## Architecture → #1108b (#1114)`:

1. **Define the exception.** Add `class TelemetryUnavailableError(HassetteError)` to
   `src/hassette/exceptions.py` (base `HassetteError` is at line 33). One-line docstring.

2. **Translate at `execute()`.** In `TelemetryQueryService.execute()`
   (`core/telemetry/query_service.py`, the `@asynccontextmanager` around `asyncio.timeout` +
   `self._db.execute`), wrap the body in `try/except (sqlite3.Error, OSError, ValueError,
   TimeoutError) as exc: raise TelemetryUnavailableError(str(exc)) from exc`. Catching the broad
   tuple is safe here because `execute()` does nothing but DB I/O.

3. **Read-path audit + cover bypasses.** Grep the three mixins (`registration_queries.py`,
   `summary_queries.py`, `execution_queries.py`) for `self._db.execute` used **outside** the
   `execute()` helper. The known bypass is `get_all_app_summaries` (`summary_queries.py:215-228`),
   which runs a manual `BEGIN DEFERRED`/`ROLLBACK` transaction directly on `self._db`. Wrap that
   transaction so the same storage tuple is translated to `TelemetryUnavailableError` (preserve the
   existing `ROLLBACK` on failure, then re-raise as the domain error). Confirm no other read path
   is left untranslated.

4. **Narrow the HTTP catch.** Change `db_degrades_to` (in `dependencies.py`) to
   `except TelemetryUnavailableError`. Change the category-C/D inline catches
   (`apps.py:get_app_manifests`, the three `dashboard_app_grid` sub-queries, and the two
   `executions.py` sites including the `check_retention_expired_uuid4` helper) from
   `except DB_ERRORS` to `except TelemetryUnavailableError`. Then **delete the `DB_ERRORS` tuple**
   from `dependencies.py` and remove its imports across `web/` — the storage tuple is now named
   only inside `execute()` (and the `get_all_app_summaries` wrapper).

5. **Tests.** Add: (a) a storage error raised inside a read surfaces to the handler as
   `TelemetryUnavailableError` and the route still returns its prior 503/200; (b) **footgun-fixed**:
   a non-DB `ValueError` raised in a handler body now propagates as a 500, not a swallowed 503;
   (c) a forced storage error in `get_all_app_summaries` still degrades `dashboard_app_grid` to
   200-partial, not 500.

## Focus
- This MUST be one commit — adding the translation without swapping the catches leaves handlers
  catching `DB_ERRORS` while the service raises `TelemetryUnavailableError`, breaking every
  degradation path. Do steps 2-4 together.
- `get_all_app_summaries` is the single highest-risk spot: it is the one read that bypasses
  `execute()` AND it backs a category-C (200-partial) site. If its translation is missed, a storage
  error there becomes a 500 instead of the current 200-partial — a regression the
  `dashboard_app_grid` test (5c) is designed to catch.
- `HassetteError` precedent for multi-inheritance exists (`EntityNotFoundError(ValueError,
  HassetteError)`), but `TelemetryUnavailableError` should subclass `HassetteError` only — it is not
  a `ValueError`.
- After this task, grep `web/` for `DB_ERRORS` — it must return nothing.
- Run `uv run pyright`; at this unit boundary run `uv run nox -s system` and `uv run nox -s e2e`;
  confirm zero `scripts/export_schemas.py --types` diff.

## Verify
- [ ] FR#7: `TelemetryUnavailableError(HassetteError)` defined in `exceptions.py`.
- [ ] FR#8: every read path (including the `get_all_app_summaries` bypass) translates the storage
      tuple to `TelemetryUnavailableError`; a `self._db.execute`-outside-`execute()` audit shows no
      uncovered read path.
- [ ] FR#9: `db_degrades_to` and the category-C/D catches catch `TelemetryUnavailableError`;
      `DB_ERRORS` no longer appears anywhere in `web/`.
- [ ] FR#10: a non-DB `ValueError` in a handler body returns HTTP 500 (test asserts this).
- [ ] AC#6: forced storage error in `get_all_app_summaries` degrades `dashboard_app_grid` to
      200-partial, not 500.
- [ ] AC#7: HTTP layer catches only `TelemetryUnavailableError`; the footgun-fixed test passes.
