"""Exception types for hassette.test_utils.

Contains exceptions raised by the AppTestHarness drain mechanism.

The drain exception hierarchy is rooted at ``DrainFailure`` so callers can
catch any drain-related failure uniformly::

    try:
        await harness.simulate_state_change(...)
    except DrainFailure:
        ...  # catches both DrainError and DrainTimeout

Subclasses:

* :class:`DrainError` — handler task(s) raised non-cancellation exceptions.
* :class:`DrainTimeout` — drain did not reach quiescence within the deadline.

``DrainTimeout`` deliberately does **not** inherit from :class:`TimeoutError`.
The drain mechanism is a test-harness concern; raising a generic
``TimeoutError`` leaked that implementation detail to callers and prevented
them from writing a single ``except DrainFailure:`` clause.
"""


class DrainFailure(Exception):  # noqa: N818  # base class; concrete subclasses use the Error/Timeout suffix
    """Base class for all AppTestHarness drain failures.

    Lets callers catch both handler exceptions and drain deadline timeouts
    uniformly with ``except DrainFailure:``. Do not raise this class directly —
    raise one of its subclasses (:class:`DrainError` or :class:`DrainTimeout`).

    Note:
        The ``Failure`` suffix is intentional and deviates from the project's
        ``*Error``-suffix convention for exceptions. It signals that this
        class is a hierarchy root, not something to raise directly. The two
        concrete subclasses below use the conventional ``Error`` / ``Timeout``
        suffixes.
    """


class DrainError(DrainFailure):
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


class DrainTimeout(DrainFailure):
    """Raised when AppTestHarness drain does not reach quiescence within its deadline.

    Carries a diagnostic message built by ``_raise_drain_timeout`` that
    includes pending task counts, pending task names, and — when applicable —
    a hint about debounce windows.

    Does NOT inherit from :class:`TimeoutError`. Callers that previously
    caught ``TimeoutError`` around drain calls should catch ``DrainTimeout``
    (or the broader ``DrainFailure``) instead.
    """
