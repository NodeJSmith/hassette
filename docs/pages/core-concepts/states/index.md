# States

Hassette maintains a local, real-time cache of all Home Assistant states. This is available as `self.states` in your apps.

## Why use `self.states`?

| Feature       | `self.states`            | `self.api.get_state()` |
| ------------- | ------------------------ | ---------------------- |
| **Speed**     | Instant (Local Memory)   | Slow (Network Request) |
| **IO**        | Synchronous              | Asynchronous (await)   |
| **Freshness** | Real-time (Event driven) | Real-time (On demand)  |

**Recommendation**: Use `self.states` for reading data (conditions, logic). Use `self.api` only when you need to write data (services) or explicitly confirm state with the server.

## Using the Cache

The state cache (`self.states`) provides synchronous access to all entity states.

### Domain Access

The easiest way to access states is via domain properties.

```python
--8<-- "pages/core-concepts/states/snippets/states_domain_access.py"
```

### Generic Access

For domains that don't have a dedicated helper, or for dynamic access, provide the state class to the `self.states` dictionary-like interface:

```python
--8<-- "pages/core-concepts/states/snippets/states_generic_access.py"
```

### Iteration

You can iterate over domains to find entities.

```python
--8<-- "pages/core-concepts/states/snippets/states_iteration.py"
```

### All States

Access the entire cache as a dictionary.

```python
--8<-- "pages/core-concepts/states/snippets/states_all.py"
```
