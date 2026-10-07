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

## Class Naming
`wire/tests/test_naming.py` enforces the WS suffixes (`Data` payloads,
`WsMessage` envelopes) and the retired ones. Review decides what it can't:
is each new or renamed HTTP type a record (a bare noun wherever it appears)
or another HTTP body (`Response`/`Request`), per the rule in the package
docstring (`__init__.py`)? Does the name collide with a public `hassette`
name? A rename changes the published schema component names, so is the PR
marked breaking?

## Shared Vocabulary Is Published
A member added to an enum in `enums.py` or a value added to a Literal in
`literals.py` reaches every client immediately. Is the new value something a
client should see, or a server-internal state that needs its own enum in
`src/hassette/types/enums.py`? Do the SQL `CHECK` constraints under
`src/hassette/migrations_sql/` that list these values (`status`, `mode`,
`source_tier`, `schedule_status`, `schedule_status_reason`, and the others
mapped in `tests/unit/core/test_wire_check_parity.py`) still match? That test
fails on a mismatch, and on a new IN-list `CHECK` it doesn't classify.

## Closed Vocabularies
`SourceTier` and `LogLevel` stay strict on response models, so an older
client can't parse a value added to either. `tools/check_wire_compat.py`
allows added response enum values, so it won't flag this. Does the diff add a
value to either one? If so, it's a breaking change and needs a
`BREAKING CHANGE:` footer.

## Duplicated Defaults
This package cannot import `hassette`, so `JobSummary.mode`,
`ListenerSummary.mode`, and `ListenerSummary.backpressure` spell their
defaults out. Do they still equal `DEFAULT_OVERLAP_MODE` and
`DEFAULT_BACKPRESSURE_POLICY` in `src/hassette/types/enums.py`?
