---
task_id: "T02"
title: "Add Listener.config_matches and diff_fields"
status: "done"
depends_on: []
implements: ["FR#8"]
---

## Summary
Add logical-configuration comparison to `Listener`, mirroring `ScheduledJob.matches` /
`diff_fields`. These power `skip` drift detection (T03): `config_matches` returns whether two
listeners represent the same logical registration; `diff_fields` lists the differing field
names for the drift error message.

## Prompt
In `src/hassette/bus/listeners.py`, add two methods to the `Listener` dataclass:

- `config_matches(self, other: "Listener") -> bool`
- `diff_fields(self, other: "Listener") -> list[str]`

Model them field-for-field on `ScheduledJob.matches` (scheduler/classes.py:268) and
`diff_fields` (scheduler/classes.py:295). Compare the logical configuration:
- handler callable: `self.invoker.orig_handler == other.invoker.orig_handler`
- filter predicate: `self.predicate == other.predicate` (built-in predicates are
  `@dataclass(frozen=True)` and compare by value)
- timing options: `once`, `debounce`, `throttle`, `timeout`, `timeout_disabled` (from
  `self.options`)
- handler kwargs: `self.invoker.kwargs == other.invoker.kwargs`
- per-registration error handler: `self.invoker.error_handler is other.invoker.error_handler`
  (by identity, mirroring the scheduler's `error_handler is other.error_handler`)
- duration configuration: compare `duration_config` scalars (`entity_id`, `duration`,
  `immediate`, `is_attribute_listener`, `hold_predicate`); treat both-None as equal.

Exclude all runtime state from the comparison: `listener_id`, `db_id`, `_cancelled`, and the
attached `DurationTimer` (`duration_config._timer`). `diff_fields` returns the list of field
names (e.g. `"handler"`, `"predicate"`, `"once"`, `"debounce"`, ...) that differ, in a stable
order, matching what `config_matches` checks.

**Critical naming:** the method MUST be `config_matches`, not `matches`. `Listener.matches`
already exists (listeners.py:360) as the event-predicate dispatch method called on every
routing pass — do not shadow it.

Add unit tests in `tests/unit/bus/test_listeners.py` mirroring
`tests/unit/test_scheduler_job_names.py`: a same-config pair matches; each individually-changed
field is detected by `diff_fields`; runtime-state differences (different `listener_id`/`db_id`)
do not affect `config_matches`.

## Focus
- `Listener` is a `@dataclass(slots=True)` (listeners.py:291). The sub-structs are
  `identity` (`ListenerIdentity`), `invoker` (`HandlerInvoker`), `options` (`ListenerOptions`),
  and `duration_config` (`DurationConfig | None`).
- `HandlerInvoker.orig_handler` (listeners.py:109) holds the original user handler;
  `kwargs` (listeners.py:118) and `error_handler` (listeners.py:121) are also on the invoker.
- `DurationConfig` (listeners.py:224) has `entity_id`, `duration`, `immediate`,
  `is_attribute_listener`, `hold_predicate`, and a private `_timer` (exclude `_timer`).
- Lambda/closure predicates and callable `changed_to`/`hold_predicate` conditions compare by
  identity, so two registrations using fresh lambdas will report drift. That is the accepted,
  documented limitation (same as the scheduler) — do not try to work around it.
- This task adds methods only; it does not wire them into the bus. T03 calls them.

## Verify
- [ ] FR#8: `Listener.config_matches` returns True for two listeners with identical logical
      configuration and False when any compared field (handler, predicate, once, debounce,
      throttle, timeout, timeout_disabled, kwargs, error_handler, duration config) differs;
      `diff_fields` lists exactly the differing field names; runtime state (`listener_id`,
      `db_id`, `_cancelled`, timer) is excluded. Unit tests in `test_listeners.py` cover the
      match case, each per-field drift case, and runtime-state exclusion. The method is named
      `config_matches` (not `matches`).
