"""App base classes and configuration for building Home Assistant automations.

This module provides clean access to the app framework for creating both async and sync
applications with typed configuration.
"""

from .app import App, AppSync, only_app
from .app_config import AppConfig, AppConfigT

__all__ = [
    "App",
    "AppConfig",
    "AppConfigT",
    "AppSync",
    "only_app",
]
