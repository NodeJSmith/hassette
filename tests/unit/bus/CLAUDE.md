# Tests: unit/bus

## Available fixtures (this directory's conftest.py)

- `hassette_with_bus` — function-scoped `Hassette` with a live `Bus`; overrides the module-scoped `test_utils` version because these tests mutate listener state per-test
- `bus` — the `Bus` resource off `hassette_with_bus`, with `parent` set via `make_mock_parent`

## Shared helpers

- `from hassette.test_utils.factories import make_mock_parent` — owning-App stand-in, used to set `bus.parent`
- `mock_add_listener(bus)` (local contextmanager) — swaps `bus.bus_service.add_listener` for an `AsyncMock`, restores on exit

## Key conventions

- `hassette_with_bus` is intentionally function-scoped, not module-scoped — see the fixture docstring before "fixing" the scope mismatch with other harness fixtures.
