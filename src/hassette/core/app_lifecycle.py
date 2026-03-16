"""Backward-compatibility shim — will be removed in WP04.

AppLifecycleManager is replaced by AppLifecycleService. This module only
exists so that tests importing AppLifecycleManager continue to resolve until
those tests are updated in WP04.
"""

from typing import TYPE_CHECKING

from hassette.core.app_lifecycle_service import AppLifecycleService

if TYPE_CHECKING:
    from hassette import Hassette
    from hassette.core.app_registry import AppRegistry
    from hassette.resources.base import Resource


class AppLifecycleManager(AppLifecycleService):
    """Deprecated compatibility wrapper — use AppLifecycleService directly.

    Accepts the old positional ``(hassette, registry)`` constructor signature
    and forwards to ``AppLifecycleService.__init__`` with keyword args.
    """

    def __init__(
        self,
        hassette: "Hassette",
        registry: "AppRegistry",
        *,
        parent: "Resource | None" = None,
    ) -> None:
        super().__init__(hassette, parent=parent, registry=registry)
