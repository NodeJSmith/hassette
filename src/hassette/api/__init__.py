"""API functionality for interacting with Home Assistant.

This module provides clean access to the API classes for making HTTP requests,
managing WebSocket connections, and handling entity states.
"""

from .api import Api
from .sync import ApiSyncFacade

__all__ = ["Api", "ApiSyncFacade"]
