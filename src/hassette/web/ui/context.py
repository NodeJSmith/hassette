"""Template context helpers for the Hassette Web UI."""

from hassette.config.helpers import VERSION


def base_context(current_page: str) -> dict:
    """Build the common template context shared by all pages."""
    return {
        "current_page": current_page,
        "hassette_version": str(VERSION),
    }
