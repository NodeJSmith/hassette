# Prereq 2: Stable Listener Identity Scheme

**Status**: Not started

**Parent**: [SQLite + Command Executor research](./research.md)

## Dependencies

- **None** — can start immediately

## Dependents

- [Prereq 1: HandlerInvocationRecord](./prereq-01-handler-invocation-record.md) — uses `stable_key` as an identity field
- [Prereq 5: Schema design](./prereq-05-schema-design.md) — stable key is a column + index candidate

## Problem

`listener_id` is an auto-incrementing `int` from a module-level `itertools.count(1)` (`bus/listeners.py:25`) that resets every time the process restarts. Persistent DB records need a key that:

1. Survives restarts — same handler re-registered after restart gets the same key
2. Is unique within a running instance — no two listeners share a key
3. Is human-readable — useful in queries and debugging

## Current identity fields on `Listener`

From `bus/listeners.py:32-91`:

| Field          | Type             | Stable?                    | Example                           |
| -------------- | ---------------- | -------------------------- | --------------------------------- |
| `listener_id`  | `int`            | No (resets on restart)     | `7`                               |
| `owner`        | `str`            | Yes (resource unique_name) | `"Hassette.AppHandler.MyApp.Bus"` |
| `topic`        | `str`            | Yes (registration-time)    | `"state_changed.light.kitchen"`   |
| `handler_name` | `str` (property) | Yes (callable_name)        | `"my_app.MyApp.on_light_change"`  |

## Proposed scheme

```python
@property
def stable_key(self) -> str:
    return f"{self.owner}:{self.handler_name}:{self.topic}"
```

Example: `"Hassette.AppHandler.MyApp.Bus:my_app.MyApp.on_light_change:state_changed.light.kitchen"`

### Why this works

- **Survives restarts**: All three components are deterministic from the app code — same app registering the same handler on the same topic always produces the same key.
- **Unique within instance**: An app can register the same handler on different topics (different key), or different handlers on the same topic (different key). The only collision would be registering the exact same handler on the exact same topic twice from the same owner — which is already a user error.
- **Human-readable**: You can see at a glance which app, handler, and topic a record belongs to.

### Edge cases

- **Lambda handlers**: `callable_name()` returns `"module.<lambda>"` — multiple lambdas in the same module would collide. This is already a problem for `handler_name` display in the dashboard. Not a new issue, and lambdas are discouraged for named handlers.
- **Dynamic topics** (glob patterns): `"state_changed.*"` is a valid topic. The stable key includes the pattern as-is — queries match on the pattern string, not on what it expands to. This is correct behavior (you want history for "the handler listening on `state_changed.*`").
- **Key length**: Could be long (~100-150 chars). Fine for SQLite TEXT columns and indexing.

## Scope

1. Add a `stable_key` property to the `Listener` dataclass in `bus/listeners.py`
2. Keep `listener_id` for in-process use (fast dict lookups in `BusService._listener_metrics`)
3. Use `stable_key` in `ListenerMetrics` as an additional field (for DB correlation)
4. Update tests that construct `Listener` instances (if any assert on field counts)

## Deliverable

Small PR: add `stable_key` property to `Listener`, add `stable_key` field to `ListenerMetrics`. No behavioral changes — the property is available but not yet consumed by anything until the executor is built.
