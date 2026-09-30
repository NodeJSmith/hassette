# REVIEW.md — codegen/src/hassette_codegen/sync_facade/

## Hand-Maintained Header Import Validity
`HEADER`, `BUS_HEADER`, `SCHEDULER_HEADER`, `HELPERS_HEADER` in `generic.py` are
string-literal import blocks a human edits by hand. `atomic_write()` in
`codegen/src/hassette_codegen/output.py` validates with `py_compile.compile()`
before writing — does that actually catch a header importing a symbol that moved
or was renamed elsewhere in the repo, or does `py_compile` only validate syntax,
leaving a stale import to fail later at real import time? Does `--check` mode
(`_check_drift` in `cli.py`, via `format_via_ruff`) run the generated code at all,
or only ruff-normalize and text-diff against the committed file?

## Freshness Hook Coverage for the `helpers` Target
`cli.py`'s `--target` choices include `helpers` (`generate_sync_helpers`).
`prek.toml`'s pre-push hooks (`generate_sync_facade`, `generate_recording_sync_facade`,
`generate_bus_sync_facade`, `generate_scheduler_sync_facade`) each match a file
pattern and one `--target`. Is there a pre-push hook that runs `--target helpers`
when `src/hassette/api/helpers.py` changes, or does only
`.github/workflows/lint.yml`'s `--target all --check` catch drift in
`HelperClientSyncFacade` — after push instead of before?

## Docstring Desync Parity Between Generators
`gen_wrapper()` in `generic.py` calls `desync_docstring()` (`ast_utils.py`) to
strip "must be awaited" phrasing before emitting a docstring. `gen_recording_method()`
in `recording_transform.py` copies `ast.get_docstring(func)` straight through with
no call to `desync_docstring()`. Does the generated `RecordingSyncFacade` end up
with docstrings still describing methods as needing `await`?

## `INTERNAL_METHODS` Filtering Asymmetry
`is_delegatable()` in `ast_utils.py` excludes names in `INTERNAL_METHODS`
(`{"get_job_db_ids"}`). `is_wrappable()` — used for both the generic async path
and the recording generator's method selection — checks `LIFECYCLE_METHODS`,
`is_overload()`, and the underscore prefix, but never `INTERNAL_METHODS`. If a
method in `INTERNAL_METHODS` became `async def` (or the de-asynced
`-> Coroutine[...]` form), would `is_wrappable()` still expose it on the public
facade despite the constant's stated purpose?
