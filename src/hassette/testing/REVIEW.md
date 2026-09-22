# REVIEW.md — testing/

## Public Export Completeness
Is every symbol in `__all__` in `src/hassette/testing/__init__.py` still
importable from the package? A rename in a private module that isn't reflected in
the re-export breaks end-user test code silently — the import fails at test
collection time, not at a type-check boundary.

## RecordingApi Coverage
`RecordingApi` in `src/hassette/testing/recording_api.py` inherits `Resource`
(not `Api`) and has a `__getattr__` fallback that raises `NotImplementedError`
for any unknown public attribute. When a new `Api` method is added in
`src/hassette/api/api.py`, is it either deliberately implemented in
`RecordingApi`, explicitly stubbed, or correctly handled by the generic
`__getattr__` fallback? A method that needs harness-specific behavior (e.g.
recording calls, returning seed data) but relies on the generic fallback will
raise at runtime instead of providing useful test behavior.

## Factory Visibility
If a new factory is added to `src/hassette/testing/_factories.py`, is it listed
in `__all__` in `src/hassette/testing/__init__.py`? An unlisted factory is
importable from the private module but invisible from the public
`hassette.testing` namespace, causing inconsistent discovery.
