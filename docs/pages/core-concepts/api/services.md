# Calling Services

The API provides methods to invoke Home Assistant services.

## Basic Service Calls

Use `call_service` for generic service invocations.

```python
--8<-- "pages/core-concepts/api/snippets/api_call_service.py"
```

## Convenience Helpers

Common operations like turning entities on/off have dedicated helpers.

```python
--8<-- "pages/core-concepts/api/snippets/api_helpers.py"
```

These methods forward arguments to `call_service` while providing a cleaner syntax.

## Service Responses

Service calls return a response dictionary (if the service provides one).

```python
--8<-- "pages/core-concepts/api/snippets/api_response.py"
```
