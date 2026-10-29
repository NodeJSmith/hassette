from hassette.resources import ShutdownOutcome, ShutdownResult

# A clean teardown attempt: result DONE, nothing running.
clean = ShutdownOutcome()
assert clean.is_restart_safe is True

# A hook timed out and was cancelled. It has ended, so nothing runs.
hook_timed_out = ShutdownOutcome(
    ShutdownResult.TIMED_OUT,
    reason="MyService: shutdown hook on_shutdown timed out after 10s",
)
assert hook_timed_out.is_restart_safe is True

# A task ignored cancellation and is still pending.
task_pending = ShutdownOutcome(still_running=("MyService.poll",))
assert task_pending.is_restart_safe is False
