# Filtering & Predicates

Three filtering layers narrow which events reach a handler. Built-in parameters (`changed_to`, `changed_from`, `changed`) cover the common cases directly on `on_state_change` and `on_attribute_change`. Conditions (`C`) express value-level tests: set membership, numeric comparisons, string patterns. Predicates (`P`) handle anything more complex, composing with `where=` on any subscription method.

All three are importable from `hassette`.

```python
from hassette import P, C, A
```

`P` contains predicates for filtering events. `C` contains conditions for matching values. `A` contains accessors for extracting specific fields from events — covered at the [end of this page](#custom-accessors).

## Filtering State Changes

Filters and predicates compare against **raw Home Assistant state strings**, not typed state models. HA reports state values as strings: `"on"`, `"off"`, `"unavailable"`, `"72.5"`. Filtering runs before type conversion for performance. Hassette avoids deserializing every event into a Pydantic model when most events will be filtered out. Bool and number literals are the exception. Hassette coerces the raw string to the literal's type before comparing. So `changed_to=True` matches a light turning `"on"`, and `changed_to=20` matches `"20.0"`. String literals like `changed_to="on"` compare exactly, as before. Wrap a literal in `C.Exact` to skip coercion. See [Literal coercion](predicate-reference.md#literal-coercion) for the full rules.

`on_state_change` accepts three built-in parameters that handle the majority of state-change filtering without predicates.

### `changed_to`

`changed_to` restricts the handler to events where the new state matches a value.

```python
--8<-- "pages/core-concepts/bus/snippets/filtering_simple_start.py"
```

The handler fires only when `binary_sensor.front_door` transitions to `"on"`. Transitions from `"on"` to anything else are ignored.

### `changed_from`

`changed_from` restricts the handler to events where the previous state matches a value.

```python
--8<-- "pages/core-concepts/bus/snippets/filtering_simple_stop.py"
```

The handler fires only when the sensor leaves `"on"`, meaning when motion stops.

### `changed=False`

By default, `on_state_change` fires only when the main state value changes. `changed=False` removes that restriction, allowing the handler to fire on attribute-only changes too.

```python
--8<-- "pages/core-concepts/bus/snippets/filtering/changed_false.py:changed_false"
```

A light remaining `"on"` while its brightness shifts from 128 to 255 would normally produce no event. With `changed=False`, that attribute update reaches the handler.

## Conditions

Conditions are value-level matchers. They work as arguments to `changed_to` and `changed_from`, or as the `condition` argument inside predicates. `changed=` takes a two-argument comparison condition instead, such as `C.Increased`, `C.Decreased`, `C.CrossedAbove`, or `C.CrossedBelow`, covered below.

### Set membership: `C.IsIn`

`C.IsIn` fires when the value appears in a collection.

```python
--8<-- "pages/core-concepts/bus/snippets/filtering_predicate_isin.py"
```

The handler runs only when `app_name` becomes `"Home Assistant Lovelace"` or `"Netflix"`.

`A.get_attr_old("app_name")` and `A.get_attr_new("app_name")` are accessors, imported from `hassette` like `C`. Inside `Annotated[...]`, each one passes the attribute's old or new value as that handler parameter. They work the same way as `D.*` annotations. [Custom Extractors](custom-extractors.md) covers accessors in full.

### Numeric comparison: `C.Comparison`

`C.Comparison` tests a value against a threshold using an operator string.

```python
--8<-- "pages/core-concepts/bus/snippets/filtering_predicate_lambda.py"
```

Supported operators: `">"`, `"<"`, `">="`, `"<="`, `"=="`, `"!="`, and their named forms (`"gt"`, `"lt"`, `"ge"`, `"le"`, `"eq"`, `"ne"`). The raw state string is coerced to the threshold's type, the same way bare literals are. So `C.Comparison(">", 20)` compares `"21.5"` as a number. A state that can't be coerced, such as `"unavailable"`, never matches.

### Numeric direction: `C.Increased` and `C.Decreased`

`C.Increased` and `C.Decreased` fire when a numeric value moves in a particular direction between events. Both work as arguments to `changed=` on `on_state_change` or `on_attribute_change`, and inside `P.StateComparison` / `P.AttrComparison`.

`P.StateComparison` calls a two-argument condition with the old and new state values. `P.AttrComparison` takes an attribute name first, then calls the condition with that attribute's old and new values. Both go in `where=`, and their entries are in the [Predicate Reference](predicate-reference.md#state-change-predicates).

```python
--8<-- "pages/core-concepts/bus/snippets/filtering_increased_decreased.py"
```

### Threshold crossing: `C.CrossedAbove` and `C.CrossedBelow`

`C.CrossedAbove` and `C.CrossedBelow` fire once when a numeric value crosses a threshold. Updates that stay past the threshold don't fire again. Both go in `changed=`, like `C.Increased`.

```python
--8<-- "pages/core-concepts/bus/snippets/filtering/threshold_crossing.py:threshold_crossing"
```

A reading of 24.8, then 25.1, then 25.3 fires the handler once, on the move to 25.1. A non-numeric old or new state, such as `"unavailable"`, never counts as a crossing. So `"unavailable"` → `26` doesn't fire. `C.Comparison` in `changed_to=` matches readings that are already past the threshold.

The full conditions table, including string matching, collection membership, and null checks, is on the [Predicate Reference](predicate-reference.md) page.

## Predicates and the `where` Parameter

When built-in parameters are not enough, `where=` accepts a predicate or a list of predicates. A list is treated as logical AND, so all predicates must match. `hassette.types.WhereClause` is the type of `where=`, for helpers that accept and forward it.

### `P.StateFrom` and `P.StateTo`

`P.StateFrom` tests the previous state. `P.StateTo` tests the new state. Both accept any value, callable, or condition object. They take the same types as `changed_from` and `changed_to`, but exist as predicate objects so they can be nested inside `P.AnyOf`, `P.AllOf`, or `P.Not` — something the bare `changed_from`/`changed_to` parameters cannot do.

```python
--8<-- "pages/core-concepts/bus/snippets/filtering_state_from_to.py"
```

The handler fires only when the light moves from an off-like state into `"on"`. Both predicates must match.

### Logical AND

`P.AttrTo` tests that a specific attribute's new value matches a condition — the attribute equivalent of `P.StateTo`. A list passed to `where=` applies all predicates as logical AND.

```python
--8<-- "pages/core-concepts/bus/snippets/filtering_combined_and.py"
```

Both `P.AttrTo` predicates must match. The `changed=False` parameter is also required here, since only attributes change, not the main state value.

### Logical OR: `P.AnyOf`

`P.AnyOf` fires when at least one contained predicate matches.

```python
--8<-- "pages/core-concepts/bus/snippets/filtering_combined_or.py"
```

`P.AllOf` is an explicit AND combinator — it does the same thing as passing a list to `where=`, but can be nested inside `P.AnyOf` or `P.Not` where a plain list is not accepted. `P.Not` negates any predicate: `P.Not(P.StateTo("on"))` fires when the new state is anything except `"on"`. All three compose freely.

### Operator Shorthand: `&`, `|`, `~`

Built-in `P.*` predicate objects overload Python's bitwise operators as shorthand for the three combinators. `a & b` is `P.AllOf((a, b))`, `a | b` is `P.AnyOf((a, b))`, and `~a` is `P.Not(a)`.

```python
--8<-- "pages/core-concepts/bus/snippets/filtering_operators.py"
```

The handler fires when a light turns on or goes unavailable, except for `light.office`. Python gives `&` higher precedence than `|`, so the OR branch needs parentheses.

Chains flatten instead of nesting: `a & b & c` builds `P.AllOf((a, b, c))`, so the summary shown by `hassette listener` reads the same as the explicit form. The result is an ordinary predicate, so operators and explicit combinators mix freely. Wrap a custom callable in [`P.Guard`](predicate-reference.md#logic-combinators) to use it in operator chains, as in `P.Guard(is_weekend) & P.StateTo("on")`.

Conditions (`C.*`) do not support these operators. They test extracted values, not events, so they compose through predicates instead.

### Ignoring Restart Replays: `P.EventEntityFresh`

Home Assistant `event.*` entities, such as Zigbee buttons and remotes, store the time of their last event as their state value. `input_button.*` helpers store their last press the same way. When Home Assistant restarts, it restores that state and broadcasts it as a new `state_changed` event. Without a guard, every button automation runs once on each restart, as if someone pressed the button.

The event's own `time_fired` doesn't help here, since a replayed event gets a fresh one. `P.EventEntityFresh` instead compares the timestamp in the entity's new state with that state's `last_changed`, and drops the event when `last_changed` is more than `max_age` seconds after that timestamp.

```python
--8<-- "pages/core-concepts/bus/snippets/filtering_event_entity_fresh.py"
```

A real press writes its timestamp and `last_changed` at the same moment, so it passes. A restart replay pairs the last real press's timestamp, often hours old, with a `last_changed` from the restart, so it is dropped. Both values come from Home Assistant, so the Hassette host's clock doesn't matter, and a listener with `duration=` still fires when its hold timer expires.

The guard fails open: a state that isn't a timestamp, such as `unknown` or `unavailable`, passes. A `max_age` of a few seconds is plenty.

A handler that acts without checking anything else also runs on those states during a restart, and when the entity is removed, since a removal has no new state to check. An `event.*` handler usually returns early on its empty `event_type`, but an `input_button` handler has no such check. Composing the guard with `P.IsPresent` and `P.StateTo` drops those events too:

```python
--8<-- "pages/core-concepts/bus/snippets/filtering/input_button_fresh.py"
```

`P.IsPresent` is false when its accessor finds no value, as on a removal. `A.get_state_value_new` goes in without parentheses because `P.IsPresent` calls it with each event.

The handler now skips placeholder states, removals, and replays of older presses. A restart that finishes within `max_age` of the last press still looks like a real press and runs the handler. If running twice for one press would be a problem, make the handler idempotent, or save the last timestamp it handled and skip a repeat.

### Presence Checks

`where=` accepts any callable that takes the event and returns a bool. That includes a lambda calling the [presence helpers](../states/index.md#presence) on `self.states`, which read the local state cache without an `await`.

```python
--8<-- "pages/core-concepts/bus/snippets/filtering/presence_where.py"
```

The handler fires when the front door opens and no tracked person is home. The lambda ignores the event, so `_` names its unused parameter. The check runs when each event is dispatched, so it reads presence at that moment, not at registration.

With no tracked `person` or `device_tracker` entities, `nobody_home()` returns `True` and the handler fires. An empty-house check needs at least one tracked entity to mean anything.

## Filtering Service Calls

`on_call_service` accepts `domain=` and `service=` for coarse filtering, and `where=` for fine-grained control. `where=` on `on_call_service` also accepts a plain dict, which matches against the service data payload.

### Dict filtering

A dict passed to `where=` matches keys and values in the service data.

**Literal match.** Every key-value pair must match. A bool or number literal coerces a string value first. See [Literal coercion](predicate-reference.md#literal-coercion). A string containing glob syntax matches as a glob.

```python
--8<-- "pages/core-concepts/bus/snippets/filtering_service_literal.py"
```

**Key presence.** The key must exist, but value does not matter (`ANY_VALUE`).

```python
--8<-- "pages/core-concepts/bus/snippets/filtering_service_presence.py"
```

**Callable per key.** A function receives the value and returns a bool.

```python
--8<-- "pages/core-concepts/bus/snippets/filtering_service_callable.py"
```

### `P.ServiceDataWhere`

`P.ServiceDataWhere` provides structured access to service data fields. Each field takes a literal, a glob string, a callable, or a condition. Pass the fields as a dict (`P.ServiceDataWhere({"entity_id": "scene.evening"})`) or, when every key is a valid Python identifier, as keyword arguments with `P.ServiceDataWhere.from_kwargs(entity_id="scene.evening")`. The two forms behave identically.

```python
--8<-- "pages/core-concepts/bus/snippets/filtering_service_predicates.py"
```

The handler fires when `message` contains `"urgent"` and `title` doesn't start with `"DEBUG"`.

`C.StartsWith` tests whether a string value begins with a prefix. `P.Not` calls whatever it wraps and inverts the result, so wrapping a condition in `P.Not` negates a field value. The wrapped form counts as a callable.

This negated field also matches a call that omits `title`, because `C.StartsWith` returns `False` for a missing value. A callable that checks `isinstance(value, str)` before testing the value rejects a missing field.

### `P.ServiceMatches`

`P.ServiceMatches` filters on the bare service name (e.g., `"turn_on"`); the domain is a separate field, matched by `P.DomainMatches`. `on_call_service` has `domain=` and `service=` built in. When subscribing via `on(topic=Topic.HASS_EVENT_CALL_SERVICE)` instead — for raw event-level access — those parameters are not available, so `P.DomainMatches` and `P.ServiceMatches` fill that role.

```python
--8<-- "pages/core-concepts/bus/snippets/filtering_service_matches.py"
```

## Raw Topic Subscriptions

`on()` subscribes to any event topic by string. It accepts `where=` predicates but has no built-in `changed_to` / `changed_from` parameters. All filtering goes through predicates.

```python
--8<-- "pages/core-concepts/bus/snippets/filtering_advanced_topics.py"
```

`on()` covers event types that the typed helper methods do not expose, including custom internal events, raw Home Assistant events, and any future topic the framework adds.

## Custom Accessors

[`A`](custom-extractors.md) (accessors) point predicates at fields not directly exposed by the helper methods. `P.ValueIs` extracts a value with an accessor, then tests it against a condition.

```python
--8<-- "pages/core-concepts/bus/snippets/filtering/custom_accessors.py"
```

`A.get_service_data_key` extracts a specific key from service data. `A.get_path` follows a dot-separated path through the event.

`A.get_path` needs the full event to walk, so it only works with `where=`. `changed_to` and `changed_from` narrow the event to a single value first, leaving nothing to traverse. The example also passes `changed=False`. `geolocation.locality` is an attribute, not the main state value `changed` gates by default. Most filtering needs are met by `changed_to`, `changed_from`, and the typed predicates. `A` handles the cases they do not reach. The full accessor guide is at [Custom Extractors](custom-extractors.md).

## Near-Misses { #near-misses }

When a filter drops an event, Hassette counts it so `hassette listener <id> --misses` can show why the handler didn't run. `<id>` is the `ID` column of `hassette listener --app <key>`. Each row of the output counts one reason's drops in one hour, with the last dropped event's values; [Why Didn't My Listener Run?](../../cli/workflows.md#why-didnt-my-listener-run) walks through reading it, and [Database & Telemetry](../database-telemetry.md#what-is-collected) lists every reason. Only app listeners record, and only these filters count:

- Each `where=` predicate, as its own filter. A list or `P.AllOf` counts each item separately, so the row names the one that said no.
- `changed_from`, `changed_to`, and `changed` when passed explicitly.

What a subscription method adds to pick its events doesn't count: the entity ID or glob, the topic, and the default change check that applies when `changed` is omitted. Those drops record nothing, so a listener on `light.*` doesn't log every other light's events.

A row names its filter by the filter's summary, such as `→ open` or `from on`. A lambda has no useful name, so two lambdas in one `where=` share a row. A named function shows its own name in the row:

```python
--8<-- "pages/core-concepts/bus/snippets/filtering/named_where.py:named_where"
```

When motion is detected in a bright hall, the row reads `is_dark` rather than `<callable>`.

A `where=` predicate that raises records an error run, not a miss. A `duration=` listener also records a miss when its hold ends early (`hold_cancelled`) or when the state no longer matches as the hold runs out (`hold_recheck_failed`), or when the entity is gone from Hassette's state cache as it runs out (`hold_entity_missing`). The second happens when the state changed without an event Hassette saw.

A `duration=` listener's `changed_to` is still a filter, so each event that leaves the matching state records a `filter` row. When that event also ends an active hold, it records a `hold_cancelled` row too: one event, two rows, each true.

## Full Reference

The complete `P`, `C`, and `A` lookup tables live on [Predicate Reference](predicate-reference.md).

## See Also

- [Writing Handlers](handlers.md). Handler signature patterns and dependency injection.
- [Subscription Methods](methods.md). Method reference, parameters, and registration.
- [Dependency Injection](dependency-injection.md). How `D.*` annotations work alongside predicates.
- [Predicate Reference](predicate-reference.md). Complete `P`, `C`, and `A` tables.
- [Custom Extractors](custom-extractors.md). Accessors for non-standard fields.
