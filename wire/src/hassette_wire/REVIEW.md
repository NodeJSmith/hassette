# REVIEW.md — hassette_wire/

## Version Skew on New Fields
Is every field added to a served model optional with a default, so a newer
client can still parse an older server's response? `tools/check_wire_compat.py`
enforces this for HTTP models through `frontend/openapi.json` only — for a model
in `ws.py`, nothing checks it, so read the diff.

## Package Isolation
Does any module import something other than the standard library, `pydantic`,
or `hassette_wire` itself? `wire/pyproject.toml` declares `pydantic` alone, and
the isolation test only catches `hassette` imports. Does a newly used pydantic
feature need a higher lower bound than the one declared there?

## Schema-Emitted Text
Class docstrings, `Field(description=...)`, and attribute docstrings on models
that set `use_attribute_docstrings=True` are emitted into
`frontend/openapi.json`. Does changed text describe the value to a contract
consumer, or does it point at server functions, files, or tables that do not
exist in this package? Were the generated artifacts regenerated with it?

## Shared Vocabulary Is Published
A member added to an enum in `enums.py` or a value added to a Literal in
`literals.py` reaches every client immediately. Is the new value something a
client should see, or a server-internal state that needs its own enum in
`src/hassette/types/enums.py`? Do the SQL `CHECK` constraints under
`src/hassette/migrations_sql/` that list these values (`status`, `mode`,
`source_tier`) still match?

## Duplicated Defaults
This package cannot import `hassette`, so `JobSummary.mode`,
`ListenerWithSummary.mode`, and `ListenerWithSummary.backpressure` spell their
defaults out. Do they still equal `DEFAULT_OVERLAP_MODE` and
`DEFAULT_BACKPRESSURE_POLICY` in `src/hassette/types/enums.py`?
