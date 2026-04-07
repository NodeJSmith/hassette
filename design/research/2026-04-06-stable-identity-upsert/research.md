---
topic: "Stable identity keys and upsert patterns for preserving FK references across restarts"
date: 2026-04-06
status: Draft
---

# Prior Art: Stable Identity Keys and Upsert Patterns for FK Preservation

## The Problem

When an application restarts and re-registers its listeners/jobs, it needs to match new registrations to existing database rows so that foreign key references from historical execution records remain valid. This requires two things: (1) a stable identity key that survives process restarts, and (2) an upsert mechanism that updates existing rows rather than deleting and re-inserting them.

The identity key problem is particularly tricky when registrations include callable references (predicates, filters) whose default `repr()` includes memory addresses that change every restart.

## How We Do It Today

Hassette uses a destructive clear-and-reinsert pattern: `clear_registrations(app_key)` DELETEs all listener/job rows, then re-INSERTs them. `ON DELETE SET NULL` preserves execution history rows but nullifies their parent FK references. A prior upsert attempt (migration 001) used UNIQUE constraints on `(app_key, instance_index, handler_method, topic)` but was dead code — the DELETE ran before INSERT, so ON CONFLICT never fired. Migration 004 removed the dead upsert columns and UNIQUE constraints.

## Patterns Found

### Pattern 1: Module + Qualified Name (Callable Identity)

**Used by**: Celery (task names), APScheduler (job persistence via `callable_to_ref`), pytest (node IDs)

**How it works**: Construct a stable string reference from `f"{func.__module__}:{func.__qualname__}"`. This produces a human-readable, importable path like `myapp.tasks:send_email`. APScheduler's `callable_to_ref()` is the most complete implementation — it explicitly REJECTS lambdas (`<lambda>` in qualname), closures (`<locals>` in qualname), `functools.partial`, and unbound instance methods. The rejection is intentional: these callables have no importable path and cannot be stably identified.

**Strengths**: Deterministic, human-readable, survives restarts, works through `@functools.wraps` decorator chains.

**Weaknesses**: Cannot handle lambdas, closures, `functools.partial`, or dynamically generated functions.

**Example**: [APScheduler callable_to_ref](https://github.com/agronholm/apscheduler/blob/master/src/apscheduler/_marshalling.py)

### Pattern 2: Explicit User-Provided Key (dispatch_uid)

**Used by**: Django signals (`dispatch_uid`), APScheduler (job `id`), Home Assistant (automation `id`), pytest (`ids=`)

**How it works**: The caller provides a stable string identifier at registration time. The framework uses this as the lookup key instead of deriving one. This is the universal escape hatch when automatic identification fails.

**Strengths**: Works for ANY callable. User controls the identity. Simple to implement.

**Weaknesses**: Requires user discipline. Adds boilerplate. No automatic deduplication.

**Example**: [Django dispatch_uid](https://github.com/django/django/blob/main/django/dispatch/dispatcher.py)

### Pattern 3: Hybrid Auto-Derive + Fallback

**Used by**: APScheduler (callable_to_ref + explicit `id`), Celery (auto name + `name=` override)

**How it works**: Attempt `module:qualname` first. If the callable cannot be auto-identified, either raise a clear error (APScheduler) or require an explicit name parameter (Celery). This is the pragmatic synthesis — zero-friction for the common case, clean escape hatch for edge cases.

**Strengths**: Best of both worlds. Most registrations need no explicit key.

**Weaknesses**: Users of lambdas/closures must understand why they need an explicit key.

**Example**: [APScheduler docs](https://apscheduler.readthedocs.io/en/3.x/faq.html)

### Pattern 4: Upsert by Stable ID (Replace-Existing)

**Used by**: APScheduler (`replace_existing=True`), django-celery-beat (`get_or_create` + update), Airflow (`sync_to_db` with `session.merge()`)

**How it works**: Each registration gets a stable identifier. On startup, upsert each registration: update mutable fields if the row exists, insert if not. APScheduler's docs explicitly warn: "you MUST define an explicit ID for the job and use `replace_existing=True` or you will get a new copy of the job every time your application restarts."

**Strengths**: Simplest mental model. No `WHERE active = true` predicates needed. FK integrity is automatic. Well-proven by APScheduler and Airflow at scale.

**Weaknesses**: Requires a stable identifier. Reconciliation step needed for removed registrations. Update-in-place loses historical config snapshots.

**Example**: [APScheduler SQLAlchemyJobStore](https://apscheduler.readthedocs.io/en/3.x/userguide.html), [Airflow DagModel.sync_to_db](https://airflow.apache.org/docs/apache-airflow/1.10.4/_modules/airflow/models/dag.html)

### Pattern 5: Soft Delete with Active Flag

**Used by**: Many enterprise ORMs. Widely discussed but increasingly criticized.

**How it works**: Mark rows inactive instead of deleting. Filter `WHERE active = 1` in all queries. Widely criticized by Brandur Leach, Cultured Systems, and Richard Dingwall as creating more problems than it solves — every query must remember the filter, unique constraints become complex, storage grows unboundedly.

**Strengths**: Preserves FK references. Allows querying historical registrations.

**Weaknesses**: Query complexity tax on every consumer. Forgotten filters produce incorrect results. Storage bloat. Multiple authoritative sources argue against this pattern.

**Example**: [Brandur on soft deletion](https://brandur.org/soft-deletion), [Cultured Systems](https://www.cultured.systems/2024/04/24/Soft-delete/)

## Anti-Patterns

- **Using `repr()` as an identity key**: Memory addresses for callables, format not stable across Python versions. [death and gravity](https://death.andgravity.com/stable-hashing) explicitly calls this out.
- **Delete-and-reinsert on every restart**: The current hassette approach. APScheduler docs explicitly warn against this.
- **Blanket soft delete**: Multiple sources document this as a common mistake that creates maintenance tax on every query.
- **Ignoring stale registration accumulation**: [django-celery-beat #654](https://github.com/celery/django-celery-beat/issues/654) shows upsert without reconciliation causes unbounded growth.

## Relevance to Us

### Predicate Identity (the repr problem)

Hassette's `predicate_description` uses `repr(listener.predicate)`, which includes memory addresses for `ValueIs`, `Guard`, `DidChange`, `IsPresent`, `IsMissing` predicates. This is the exact anti-pattern documented above.

However, hassette already has `human_description` via `predicate.summarize()`, which IS stable across restarts. It produces deterministic strings from data fields only. The one weakness: `ValueIs` and `Guard` with callable conditions both collapse to `"custom condition"`, losing distinctiveness.

**Codebase finding**: No apps in the codebase currently register two listeners on the same handler+topic with different predicates. The API supports it, but it's not exercised.

### Upsert Mechanism

The plan's proposed soft-delete-with-active-flag approach is the pattern most criticized in the prior art. The industry consensus (APScheduler, Airflow, django-celery-beat) favors **upsert by stable ID** — which is what the plan is trying to do, but using soft-delete as the implementation mechanism adds unnecessary query complexity.

A cleaner approach: use `ON CONFLICT DO UPDATE` with a UNIQUE constraint on the natural key, updating mutable fields in place. No active flag needed — rows are never deleted, just updated. Stale registrations (handlers removed from code) get a reconciliation pass after all current registrations are upserted.

## Recommendation

**For identity**: Use `(app_key, instance_index, handler_method, topic, human_description)` as the natural key. `human_description` is stable and distinctive enough for the predicate collision case. Accept that callable predicates with identical summaries ("custom condition") would collide — document that this edge case requires distinct handler method names, or add an optional `name=` parameter (Pattern 2) as a future escape hatch.

**For upsert mechanism**: Consider whether the `active` flag approach is necessary at all. The prior art strongly favors direct upsert via `ON CONFLICT DO UPDATE` with a UNIQUE constraint, which avoids the query-filter tax that soft delete imposes. Stale registrations (removed handlers) can be reconciled after the upsert pass — delete rows not seen in the current startup cycle if they have no execution history, or mark them inactive if they do.

## Sources

### Reference implementations
- [APScheduler callable_to_ref](https://github.com/agronholm/apscheduler/blob/master/src/apscheduler/_marshalling.py)
- [APScheduler SQLAlchemyJobStore](https://apscheduler.readthedocs.io/en/3.x/userguide.html)
- [Django dispatch_uid](https://github.com/django/django/blob/main/django/dispatch/dispatcher.py)
- [Airflow DagModel.sync_to_db](https://airflow.apache.org/docs/apache-airflow/1.10.4/_modules/airflow/models/dag.html)
- [Blinker hashable_identity](https://github.com/pallets-eco/blinker)
- [Celery gen_task_name](https://github.com/celery/celery/pull/2078/files)

### Blog posts & writeups
- [Brandur: Soft Deletion Probably Isn't Worth It](https://brandur.org/soft-deletion)
- [Brandur: deleted_record_insert](https://brandur.org/fragments/deleted-record-insert)
- [Cultured Systems: Avoiding the Soft Delete Anti-Pattern](https://www.cultured.systems/2024/04/24/Soft-delete/)
- [Richard Dingwall: The Trouble with Soft Delete](https://richarddingwall.name/2009/11/20/the-trouble-with-soft-delete/)
- [death and gravity: Deterministic hashing](https://death.andgravity.com/stable-hashing)
- [Halim Samy: Soft Delete and Unique Constraint](https://halimsamy.com/sql-soft-deleting-and-unique-constraint)

### Documentation & standards
- [Celery Task Names](https://docs.celeryq.dev/en/stable/userguide/tasks.html)
- [APScheduler FAQ](https://apscheduler.readthedocs.io/en/3.x/faq.html)
- [Django Signals dispatch_uid](https://docs.djangoproject.com/en/5.2/topics/signals/)
- [Airflow Best Practices](https://airflow.apache.org/docs/apache-airflow/stable/best-practices.html)
- [Home Assistant Entity Unique ID](https://developers.home-assistant.io/docs/core/integration-quality-scale/rules/entity-unique-id/)
- [Microsoft Event Sourcing Pattern](https://learn.microsoft.com/en-us/azure/architecture/patterns/event-sourcing)
- [Python __qualname__](https://runebook.dev/en/docs/python/reference/datamodel/function.__qualname__)
