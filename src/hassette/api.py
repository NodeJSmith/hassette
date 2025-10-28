"""API functionality for interacting with Home Assistant.

This module provides clean access to the API classes for making HTTP requests,
managing WebSocket connections, and handling entity states.
"""

from .core.resources.api.api import Api
from .core.resources.api.sync import ApiSyncFacade

__all__ = ["Api", "ApiSyncFacade"]
