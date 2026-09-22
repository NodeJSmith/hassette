# REVIEW.md — app/

## Public API Allowlist
Is `_APP_PUBLIC_API` in `src/hassette/app/app.py` updated when a new user-facing
method or property is added to `App`? `App.__dir__` returns only these names — a
missing entry makes a real method invisible to app authors' autocomplete and
introspection.

## Cache Key Agreement
Does `App.cache_key` in `src/hassette/app/app.py` still produce the same
`{app_key}/{index}` format as `resolve_cache_keys()` in
`src/hassette/config/config.py`? A drift between them causes silent
cache-directory mismatch.

## Lifecycle Hook Contract
If a new lifecycle hook is added to `AppSync` in `src/hassette/app/app.py`, is it
included in `_APPSYNC_HOOKS` and decorated with `@final`? A missing `@final` lets
subclasses override the async-to-sync bridge, breaking the sync contract.
