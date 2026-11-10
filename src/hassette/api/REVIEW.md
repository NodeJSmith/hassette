# REVIEW.md — api/

## Sync Wrapper Parameter Forwarding
Does each sync wrapper in `src/hassette/api/sync.py` forward every parameter
from the corresponding async method on `Api` (`src/hassette/api/api.py` and its
mixin modules `service_calls.py` and `entity_data.py`)? A wrapper that omits or renames a newly-added parameter silently drops that feature for sync
handlers. Codex has caught double-timeout and missing-parameter bugs in this
layer.

## Write Call Sites and Re-send
`ws_send_and_wait` re-sends on a response timeout unless the caller passes
`retry_on_timeout=False`. Does every new or changed call that can have a side
effect (`Api` in `src/hassette/api/api.py`, `service_calls.py`, and
`entity_data.py`; helper writes via `_ws_helper_call` in
`src/hassette/api/helpers.py`) pass `False`, or does it inherit the re-sending
default and risk applying the command twice? Does any `except` added on these
paths catch one delivery state (`CommandNotSentError`, `CommandRejectedError`,
`OutcomeUnknownError`) and re-raise it as another, erasing what the caller needs
to know about whether the command applied?

## Write Records
Every named write calls `begin_write()` (`src/hassette/api/api.py`) once before it
sends, and its record reaches exactly one outcome. Does a new or changed write
in `api.py`, `service_calls.py`, `entity_data.py`, `helpers.py`, or an entity
action call it? For a WebSocket write, is the handle passed as `record=` so the
pending-reply entry resolves it; for a REST write, does every exit (the
`except BaseException` path included) resolve it through `resolve_rest_failure()`
or `resolve()`? A write that skips the call is missing from the execution's
API writes with nothing to show it was dropped.

## Mode Interaction
When two API options can be combined (e.g., `return_response` + `wait_for_ack`
in `src/hassette/api/service_calls.py`), is each combination explicitly handled? An
unhandled combination can send the wrong payload or raise an error the caller
doesn't expect.

## Helper Client Domain Coverage
`src/hassette/api/helpers.py`'s `HelperClient` has `@overload` declarations per
supported HA helper domain. When `list`/`create`/`update`/`delete` are called
with a domain not covered by an overload, does the call succeed with `Any` typing
(hiding a possible runtime error), or does the type checker catch it?
