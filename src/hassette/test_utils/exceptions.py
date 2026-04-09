"""Exception types for hassette.test_utils.

Contains exceptions raised by the AppTestHarness drain mechanism.
"""


class DrainError(Exception):
    """Raised when AppTestHarness drain surfaces handler task exceptions.

    Aggregates all non-cancellation exceptions from completed tasks during drain
    so test failures report the real cause instead of silently masking handler
    crashes with misleading assertion failures.

    Attributes:
        task_exceptions: List of ``(task_name, exception)`` tuples collected
            from completed handler tasks during the drain pass.
    """

    task_exceptions: list[tuple[str, BaseException]]

    def __init__(self, task_exceptions: list[tuple[str, BaseException]]) -> None:
        if not task_exceptions:
            raise ValueError(
                "DrainError requires at least one (task_name, exception) tuple. "
                "Callers must guard with `if collected_exceptions:` before raising."
            )
        self.task_exceptions = task_exceptions
        count = len(task_exceptions)
        first_name, first_exc = task_exceptions[0]
        parts = [
            f"{count} handler task exception{'s' if count != 1 else ''} during drain.",
            f"First: {first_name}: {type(first_exc).__name__}: {first_exc}",
        ]
        if count > 1:
            parts.append(f"({count - 1} more — see .task_exceptions)")
        super().__init__(" ".join(parts))
