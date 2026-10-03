"""Regression test for #2500 — isolated from test_file_watcher.py's module-scoped harness.

Builds its own function-scoped HassetteHarness rather than reusing the shared
``hassette_with_file_watcher`` fixture: only one live ``Hassette()`` instance is
supported per process at a time (see ``.claude/rules/core-startup.md``), and that
fixture's harness stays alive for the whole module.
"""

import typing

if typing.TYPE_CHECKING:
    from collections.abc import Callable

    from hassette import HassetteConfig
    from hassette.testing import HassetteHarness


async def test_harness_starts_with_file_watcher_disabled(
    hassette_harness: "Callable[[HassetteConfig], HassetteHarness]",
    test_config_class: "type[HassetteConfig]",
    unused_tcp_port_factory,
) -> None:
    """A disabled FileWatcherService marks ready from on_initialize() and keeps serve() parked.

    Startup must not wait on serve() for readiness, and serve() must not return while the
    service is supposed to stay up.
    """
    config = test_config_class(
        web_api={"port": unused_tcp_port_factory()},
        file_watcher={"watch_files": False},
    )

    async with hassette_harness(config).with_bus().with_file_watcher().with_api_mock() as harness:
        assert harness.file_watcher.is_ready()
        assert harness.file_watcher.is_running()
