# Using the State Cache

The state cache (`self.states`) provides synchronous access to all entity states.

## Domain Access

The easiest way to access states is via domain properties.

```python
--8<-- "pages/core-concepts/states/snippets/states_domain_access.py"
```

## Generic Access

For domains that don't have a dedicated helper, or for dynamic access, use `.get`:

```python
--8<-- "pages/core-concepts/states/snippets/states_generic_access.py"
```

## Iteration

You can iterate over domains to find entities.

```python
--8<-- "pages/core-concepts/states/snippets/states_iteration.py"
```

## All States

Access the entire cache as a dictionary.

```python
--8<-- "pages/core-concepts/states/snippets/states_all.py"
```
