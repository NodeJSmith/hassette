"""Event bus functionality for handling Home Assistant events.

This module provides clean access to the event bus system for registering handlers,
managing subscriptions, and working with event listeners and predicates.
"""

from .core.resources.bus.bus import Bus
from .core.resources.bus.listeners import Listener, Subscription
from .core.resources.bus.predicates import accessors, conditions, predicates

__all__ = [
    "Bus",
    "Listener",
    "Subscription",
    "accessors",
    "conditions",
    "predicates",
]
