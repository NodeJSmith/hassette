# REVIEW.md — testing/

## Public Export Completeness
Is every symbol in `__all__` in `src/hassette/testing/__init__.py` still
importable from the package? A rename in a private module that isn't reflected in
the re-export breaks end-user test code silently — the import fails at test
collection time, not at a type-check boundary.

## RecordingApi Parity
Does `RecordingApi` in `src/hassette/testing/recording_api.py` implement every
method that `Api` in `src/hassette/api/api.py` exposes? A new `Api` method
without a `RecordingApi` counterpart raises `NotImplementedError` in harness
tests, which surfaces as a confusing test failure far from the root cause.

## Factory Visibility
If a new factory is added to `src/hassette/testing/_factories.py`, is it listed
in `__all__` in `src/hassette/testing/__init__.py`? An unlisted factory is
importable from the private module but invisible from the public
`hassette.testing` namespace, causing inconsistent discovery.
