"""Runtime wrapper that detects forgotten ``await`` on protected registration methods.

``RegistrationHandle[T]`` wraps a real coroutine and emits a
``HassetteForgottenAwaitWarning`` in ``__del__`` when it is garbage-collected
without ever being awaited, sent to, thrown into, or closed.

``guard_await(coro, *, owner, source_location, method_name)`` is the single
call-site helper used by every converted public method (Bus, Scheduler, Api).
It resolves the per-app-then-global behavior and constructs the handle.

Architecture reference: design/specs/071-forgotten-await-detection/design.md
"""

import contextlib
import warnings
from collections.abc import Coroutine, Generator
from typing import Any, TypeVar

from hassette.exceptions import HassetteForgottenAwaitWarning
from hassette.types.enums import ForgottenAwaitBehavior

T = TypeVar("T")

# Hardcoded fallback when neither per-app nor global config has a value set.
DEFAULT_FORGOTTEN_AWAIT_BEHAVIOR = ForgottenAwaitBehavior.WARN


class RegistrationHandle(Coroutine[Any, Any, T]):
    """A coroutine wrapper that warns when never awaited.

    Subclasses ``collections.abc.Coroutine`` so ``asyncio.iscoroutine(handle)``
    returns ``True`` — the sync-facade ``run_sync`` path depends on this.

    The annotation on every protected method stays ``-> Coroutine[Any, Any, T]``
    (the supertype, on purpose): Pyright's ``reportUnusedCoroutine`` fires only
    for the ``Coroutine`` ABC; narrowing to ``RegistrationHandle`` or ``Awaitable``
    would silently kill the static layer.  AC#8 guards that constraint.
    """

    __slots__ = ("__name__", "_awaited", "_behavior", "_coro", "_display_name", "_owner_identity", "_source_location")

    def __init__(
        self,
        coro: Coroutine[Any, Any, T],
        *,
        owner_identity: str,
        behavior: ForgottenAwaitBehavior,
        source_location: str,
        method_name: str | None = None,
    ) -> None:
        self._coro = coro
        self._awaited = False
        self._behavior = behavior
        self._owner_identity = owner_identity
        self._source_location = source_location
        # Expose the inner coroutine's name so run_sync error paths can log fn.__name__.
        self.__name__: str = getattr(coro, "__name__", "<unknown>")
        # Public method name for the warning message — users search for what they
        # called (e.g. 'on_state_change'), not the inner private coroutine name.
        self._display_name = method_name or self.__name__

    # Coroutine protocol — all four entry points set _awaited = True before
    # delegating.  Omitting any one causes a false-positive warning on
    # cancellation, threadsafe scheduling, or the sync error path.

    def send(self, value: Any) -> Any:
        """Drive the coroutine one step; marks the handle awaited."""
        self._awaited = True
        return self._coro.send(value)

    def throw(self, *args: Any, **kwargs: Any) -> Any:
        """Inject an exception; marks the handle awaited.

        Forwards the full ``Coroutine.throw`` protocol — both the single-arg
        ``throw(exc)`` form and the legacy ``throw(type, value, tb)`` form — so
        callers using either signature reach the wrapped coroutine unchanged.
        """
        self._awaited = True
        return self._coro.throw(*args, **kwargs)

    def close(self) -> None:
        """Close the inner coroutine; marks the handle awaited so ``__del__`` stays silent."""
        self._awaited = True
        self._coro.close()

    def __await__(self) -> Generator[Any, None, T]:
        """Delegate ``await``; marks the handle awaited."""
        self._awaited = True
        return self._coro.__await__()

    def __del__(self) -> None:
        """Emit a warning and close the inner coroutine when never awaited."""
        if self._awaited:
            return

        # Always close the inner coroutine FIRST — this suppresses CPython's native
        # "coroutine '...' was never awaited" RuntimeWarning (FR#4) even during
        # interpreter shutdown, when the warnings module below may already be gone.
        # Plain try/except, not contextlib: module globals can be None'd at shutdown.
        try:  # noqa: SIM105 — contextlib itself may be torn down when __del__ runs at shutdown
            self._coro.close()
        except Exception:  # noqa: S110 — __del__ must never raise; nothing to log at teardown
            pass

        # Guard against interpreter shutdown where warnings module may be None.
        if warnings is None:
            return

        try:
            # WARN and ERROR both emit here; ERROR escalates only via the user's
            # filterwarnings("error") configuration (see ForgottenAwaitBehavior.ERROR).
            if self._behavior is not ForgottenAwaitBehavior.IGNORE:
                msg = (
                    f"Coroutine from '{self._display_name}' was never awaited "
                    f"(app: {self._owner_identity}, call site: {self._source_location}). "
                    f"Did you forget 'await'?"
                )
                # stacklevel=1 because the real call site is captured in source_location —
                # the frame that would be indicated by stacklevel is __del__ (useless).
                warnings.warn(msg, HassetteForgottenAwaitWarning, stacklevel=1)
        except HassetteForgottenAwaitWarning:
            # filterwarnings("error") escalated the warning — let it propagate so
            # Python's unraisable hook prints the loud, visible traceback the ERROR
            # level promises. Raising from __del__ never crashes the process.
            raise
        except Exception:  # noqa: S110 — __del__ must never raise accidentally at shutdown
            # Accidental failures of partially-torn-down machinery stay silent.
            pass


def guard_await(
    coro: Coroutine[Any, Any, T],
    *,
    owner: Any,
    source_location: str,
    method_name: str | None = None,
) -> "RegistrationHandle[T]":
    """Wrap *coro* in a ``RegistrationHandle`` with eager behavior resolution.

    Resolves ``ForgottenAwaitBehavior`` at call time (user frame still live) so
    ``__del__`` never touches the owning app's config — safe to call at shutdown.

    Resolution order:
    1. ``owner.app_config.forgotten_await_behavior`` (per-app, when not ``None``)
    2. ``owner.hassette.config.forgotten_await_behavior`` (global, when not ``None``)
    3. ``WARN`` (hardcoded default — FR#7)

    The owner identity string is also captured eagerly for the same reason.

    Args:
        coro: The inner coroutine to wrap (from a private ``async def _x(...)``).
        owner: The owning App resource.  Duck-typed: needs ``unique_name``,
            ``app_config.forgotten_await_behavior``, and
            ``hassette.config.forgotten_await_behavior``.
        source_location: Pre-captured ``"<file>:<lineno>"`` string from the
            public ``def`` call site (user frame live at that point).
        method_name: The public method name shown in the warning message
            (e.g. ``"on_state_change"``).  Falls back to the inner coroutine's
            ``__name__`` when omitted.

    Returns:
        A ``RegistrationHandle`` that is a ``collections.abc.Coroutine`` subclass
        and satisfies ``asyncio.iscoroutine(handle) is True``.
    """
    # Resolve behavior — eagerly, before the user frame is gone.
    # Config fields are Pydantic-validated at load time, so per_app/global_val are
    # already valid enum members or None here; the narrow suppress only guards the
    # enum constructor (ValueError/TypeError) and defensive attribute access.
    behavior: ForgottenAwaitBehavior = DEFAULT_FORGOTTEN_AWAIT_BEHAVIOR
    with contextlib.suppress(AttributeError, ValueError, TypeError):
        per_app = getattr(getattr(owner, "app_config", None), "forgotten_await_behavior", None)
        if per_app is not None:
            behavior = ForgottenAwaitBehavior(per_app)
        else:
            hassette_cfg = getattr(getattr(owner, "hassette", None), "config", None)
            global_val = getattr(hassette_cfg, "forgotten_await_behavior", None)
            if global_val is not None:
                behavior = ForgottenAwaitBehavior(global_val)

    # Resolve identity string — eagerly. This value is a cosmetic display string, so a
    # missing or non-stringable unique_name falls back to "<unknown>" rather than breaking
    # the registration call. Narrowed to the same surface as the behavior block above — a
    # genuinely broken accessor surfaces instead of being silently masked.
    owner_identity: str = "<unknown>"
    with contextlib.suppress(AttributeError, TypeError, ValueError):
        owner_identity = str(getattr(owner, "unique_name", "<unknown>"))

    return RegistrationHandle(
        coro=coro,
        owner_identity=owner_identity,
        behavior=behavior,
        source_location=source_location,
        method_name=method_name,
    )
