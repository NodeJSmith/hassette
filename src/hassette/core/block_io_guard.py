"""Blocking-I/O detection for the shared event loop.

This module is the canonical location for the shared behavior-resolution logic used
by both Tier 1 (loop-responsiveness watchdog) and Tier 2 (call-site interception).

Architecture reference: design/specs/074-blocking-io-detection/design.md
"""

import contextlib

from hassette.types.enums import BlockingIOBehavior

# Hardcoded fallback when neither per-app nor global config has a value set.
DEFAULT_BLOCKING_IO_BEHAVIOR = BlockingIOBehavior.WARN


def resolve_blocking_io_behavior(owner: object) -> BlockingIOBehavior:
    """Resolve the effective ``BlockingIOBehavior`` for the given app owner.

    Resolution order:
    1. ``owner.app_config.blocking_io_behavior`` (per-app, when not ``None``)
    2. ``owner.hassette.config.blocking_io.behavior`` (global, when not ``None``)
    3. ``WARN`` (hardcoded default — FR#7)

    Duck-typed: ``owner`` needs ``app_config.blocking_io_behavior`` and
    ``hassette.config.blocking_io.behavior``. Missing or broken accessors are
    suppressed so detection never crashes a handler.

    Note: the global path is two levels deep (``blocking_io.behavior``, a nested
    config model) — unlike the flat ``forgotten_await_behavior`` that
    ``await_guard.guard_await`` reads. The blocking-IO settings are grouped under
    one nested model, so the global default lives on that model rather than at the
    config root.

    Tier note: this resolves *lazily*, at the moment detection fires — correct for
    Tier 1 (the watchdog has no registration moment) and for Tier 2 (the call site
    is intercepted while the owning app is still alive). It must NOT be deferred to
    a teardown path (e.g. ``__del__``) where the owner's config may be gone; resolve
    while the owner is live, exactly as ``guard_await`` does eagerly.

    Args:
        owner: The owning App resource, or any object with the duck-typed interface above.

    Returns:
        The resolved ``BlockingIOBehavior`` for this app.
    """
    behavior: BlockingIOBehavior = DEFAULT_BLOCKING_IO_BEHAVIOR
    with contextlib.suppress(AttributeError, ValueError, TypeError):
        per_app = getattr(getattr(owner, "app_config", None), "blocking_io_behavior", None)
        if per_app is not None:
            behavior = BlockingIOBehavior(per_app)
        else:
            hassette_cfg = getattr(getattr(owner, "hassette", None), "config", None)
            global_val = getattr(getattr(hassette_cfg, "blocking_io", None), "behavior", None)
            if global_val is not None:
                behavior = BlockingIOBehavior(global_val)
    return behavior
