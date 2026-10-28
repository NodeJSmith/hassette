from hassette.resources.teardown import TeardownCause, TeardownReport

# A clean teardown attempt: no causes recorded, is_restart_safe is derived as True.
clean_report = TeardownReport()
assert clean_report.is_restart_safe is True

# A shutdown hook timed out and was cancelled: the cause is recorded, but nothing is still running.
hook_timed_out = TeardownReport(causes=(TeardownCause.SHUTDOWN_HOOK_TIMED_OUT,))
assert hook_timed_out.is_restart_safe is True

# A task ignored cancellation and is still pending: work may still be running.
task_pending = TeardownReport(causes=(TeardownCause.TASKS_PENDING,), pending_tasks=("MyService.poll",))
assert task_pending.is_restart_safe is False
