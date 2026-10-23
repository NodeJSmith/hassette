"""Per-app lifecycle lock that also reports queued waiters as busy."""

import asyncio


class AppKeyLock(asyncio.Lock):
    """An ``asyncio.Lock`` whose :attr:`busy` counts tasks holding *or waiting for* it.

    ``locked()`` alone goes false for one loop iteration on every handoff: ``release()`` clears
    the flag and wakes the next waiter, which only re-takes the lock when it next runs. A
    fail-fast caller checking ``locked()`` in that gap would see the lock as free, then queue
    behind the woken waiter. ``busy`` stays true across the handoff because the waiter's claim
    is counted from the moment it starts acquiring.
    """

    def __init__(self) -> None:
        super().__init__()
        self.claims = 0

    @property
    def busy(self) -> bool:
        """Whether any task holds the lock or is waiting to acquire it."""
        return self.claims > 0

    async def acquire(self) -> bool:
        """Acquire the lock, counting this task as a claim from the moment it starts waiting.

        The claim is withdrawn if acquisition is cancelled or fails.

        Returns:
            ``True`` once the lock is held.
        """
        self.claims += 1
        try:
            return await super().acquire()
        except BaseException:
            self.claims -= 1
            raise

    def release(self) -> None:
        """Release the lock and withdraw the holder's claim."""
        super().release()
        self.claims -= 1
