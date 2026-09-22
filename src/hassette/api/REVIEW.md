# REVIEW.md — api/

## Sync Wrapper Parameter Forwarding
Does each sync wrapper in `src/hassette/api/sync.py` forward every parameter
from the corresponding async method in `src/hassette/api/api.py`? A wrapper that
omits or renames a newly-added parameter silently drops that feature for sync
handlers. Codex has caught double-timeout and missing-parameter bugs in this
layer.

## Mode Interaction
When two API options can be combined (e.g., `return_response` + `wait_for_ack`,
retry logic + acknowledged calls in `src/hassette/api/api.py`), is the
interaction explicitly handled? An unhandled combination can silently re-apply
side effects or produce an error the caller doesn't expect.

## Helper Client Domain Coverage
`src/hassette/api/helpers.py`'s `HelperClient` has `@overload` declarations per
supported HA helper domain. When `list`/`create`/`update`/`delete` are called
with a domain not covered by an overload, does the call succeed with `Any` typing
(hiding a possible runtime error), or does the type checker catch it?
