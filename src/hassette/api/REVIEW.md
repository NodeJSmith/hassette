# REVIEW.md — api/

## Sync Wrapper Parameter Forwarding
Does each sync wrapper in `src/hassette/api/sync.py` forward every parameter
from the corresponding async method in `src/hassette/api/api.py`? A wrapper that
omits or renames a newly-added parameter silently drops that feature for sync
handlers. Codex has caught double-timeout and missing-parameter bugs in this
layer.

## Write Call Sites and Re-send
`ws_send_and_wait` re-sends on a response timeout unless the caller passes
`retry_on_timeout=False`. Does every new or changed call that can have a side
effect (`src/hassette/api/api.py`, helper writes via `_ws_helper_call` in
`src/hassette/api/helpers.py`) pass `False`, or does it inherit the re-sending
default and risk applying the command twice? Does any `except FailedMessageError`
added on these paths rewrap `ResponseTimeoutError` and erase its type?

## Mode Interaction
When two API options can be combined (e.g., `return_response` + `wait_for_ack`
in `src/hassette/api/api.py`), is each combination explicitly handled? An
unhandled combination can send the wrong payload or raise an error the caller
doesn't expect.

## Helper Client Domain Coverage
`src/hassette/api/helpers.py`'s `HelperClient` has `@overload` declarations per
supported HA helper domain. When `list`/`create`/`update`/`delete` are called
with a domain not covered by an overload, does the call succeed with `Any` typing
(hiding a possible runtime error), or does the type checker catch it?
