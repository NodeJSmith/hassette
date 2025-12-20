# Filtering & Advanced Subscriptions

Hassette provides powerful tools for filtering events, ensuring your handlers only run when necessary.

## Common State Filtering

For `on_state_change`, the most common way to filter is using the `changed_to`, `changed_from`, or `changed` parameters. These allow you to filter based on the new state value, old state value, or general criteria.

### Simple Value Matching

Pass concrete values to match exact states:

```python
--8<-- "pages/core-concepts/bus/snippets/filtering_simple_start.py"
--8<-- "pages/core-concepts/bus/snippets/filtering_simple_stop.py"
```

### Predicate Matching

For more logic, you can pass **Predicates** or callables directly to these parameters. This is the recommended way to handle most state change logic.

```python
--8<-- "pages/core-concepts/bus/snippets/filtering_predicate_isin.py"
--8<-- "pages/core-concepts/bus/snippets/filtering_predicate_lambda.py"
```

## Advanced Filtering with `where`

If `changed_to/from` aren't enough, or if you are filtering other event types (like service calls), use the `where` parameter.

`where` accepts a list of predicates (logical AND) or a customized predicate structure.

### Combining Predicates

Multiple predicates in a list are treated as logical **AND**.
Use `P.AnyOf` for logical **OR**.

```python
--8<-- "pages/core-concepts/bus/snippets/filtering_combined_and.py"
--8<-- "pages/core-concepts/bus/snippets/filtering_combined_or.py"
```

## Filtering Service Calls

`on_call_service` supports both specific dictionary matching and predicate-based filtering using `where`.

### Dictionary Filtering

A simple dict passed to `where` matches keys and values in the service data.

```python
--8<-- "pages/core-concepts/bus/snippets/filtering_service_literal.py"
--8<-- "pages/core-concepts/bus/snippets/filtering_service_presence.py"
--8<-- "pages/core-concepts/bus/snippets/filtering_service_callable.py"
```

### Predicate Filtering

Use `P.ServiceDataWhere` for structured access to service data fields:

```python
--8<-- "pages/core-concepts/bus/snippets/filtering_service_predicates.py"
```

## Advanced Topic Subscriptions

For scenarios not covered by helper methods, you can subscribe loosely to any event topic using `on`. This method always uses `where` for filtering.

```python
--8<-- "pages/core-concepts/bus/snippets/filtering_advanced_topics.py"
```

See [`predicates`][hassette.event_handling.predicates] for the full list of built-in predicates.
