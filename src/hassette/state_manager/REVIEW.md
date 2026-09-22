# REVIEW.md — state_manager/

## STATE_REGISTRY Resolution
Does `StateManager.__getattr__` in `src/hassette/state_manager/state_manager.py`
resolve domain lookups through `STATE_REGISTRY` in
`src/hassette/conversion/__init__.py`? If a new state model is added to the
registry but the registration call is missing, does the error message guide the
user to the right fix?

## Sensor-Shape Accessor Parity
The four sensor-shape accessors (`numeric_sensor`, `enum_sensor`, etc.) in
`src/hassette/state_manager/state_manager.py` each pass a `predicate` and
explicit `domain="sensor"` to `_domain_states_for()`. If a new sensor-shape
accessor is added, does it follow the same two-arg pattern, or does it omit one?

## DomainStates Error Path Consistency
`DomainStates.__getitem__` in `src/hassette/state_manager/state_manager.py`
handles predicate and no-predicate paths with different exceptions
(`EntityNotInViewError` vs `UnableToConvertStateError`). Could a change to
`_validate_or_return_from_cache` break one path while fixing the other?
