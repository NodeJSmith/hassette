# REVIEW.md — task_bucket/

## PROTECT_TASK Context Var
Does `make_task_factory` in `src/hassette/task_bucket/task_bucket.py` correctly
handle the `PROTECT_TASK` context var? A task marked protected should not be
tracked by any bucket's `cancel_all()` — does the factory skip tracking when
`ctx.PROTECT_TASK.get()` is True and no explicit bucket is set?

## Sealed Bucket Coroutine Cleanup
When `spawn()` in `src/hassette/task_bucket/task_bucket.py` is called from a
non-loop thread and the bucket is sealed, does the rejection path close the
coroutine? A sealed bucket that doesn't close on the cross-thread path produces a
"coroutine was never awaited" warning.

## Seal/Reopen Idempotency
Does `seal()` / `reopen()` in `src/hassette/task_bucket/task_bucket.py` remain
idempotent? A double-seal that logs twice or a reopen that clears state beyond
the sealed flag would be a regression — Codex has flagged `contextlib.suppress`
breadth in the rejection callback for this reason.
