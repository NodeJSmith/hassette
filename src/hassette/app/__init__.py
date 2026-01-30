"""App base classes and configuration for building Home Assistant automations.

This module provides clean access to the app framework for creating both async and sync
applications with typed configuration.
"""

from .app import App, AppSync, only_app
from .app_config import AppConfig

__all__ = [
    "App",
    "AppConfig",
    "AppSync",
    "only_app",
]
