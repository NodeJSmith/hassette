"""Unit tests for WebApiService uvicorn configuration, startup guards, and shutdown."""

import asyncio
import ipaddress
import socket
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any, cast
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import uvicorn
from httpx2 import ASGITransport, AsyncClient

from hassette.config.models import WebApiConfig
from hassette.core.core import Hassette
from hassette.core.scheduler_service import SchedulerService
from hassette.core.web_api_service import WebApiService
from hassette.exceptions import FatalError
from hassette.web.auth.tokens import TOKEN_FILENAME
from hassette.web.auth.trusted_proxies import EMPTY_TRUSTED_PROXY_SET
from tests.conftest import TestConfig as HassetteTestConfig  # aliased so pytest does not collect it
from tests.support.helpers import make_addrinfo, patch_loop_getaddrinfo


def _make_web_api_service(
    unused_tcp_port_factory, tmp_path, *, logging: dict[str, Any] | None = None, **web_api_overrides: Any
) -> WebApiService:
    web_api_config = WebApiConfig(port=unused_tcp_port_factory(), **web_api_overrides)
    logging_kwargs: dict[str, Any] = {} if logging is None else {"logging": logging}
    config = HassetteTestConfig(web_api=web_api_config, data_dir=tmp_path, **logging_kwargs)
    hassette = Hassette(config)

    # WebApiService.__init__ creates its Scheduler child (self.add_child(Scheduler)), which
    # needs hassette.scheduler_service — only wired by the full wire_services() sequence, not
    # by Hassette(config) alone. Patch Scheduler for the duration of construction so
    # on_initialize() doesn't need a fully-wired SchedulerService either; this isolates
    # WebApiService's own wiring logic from Scheduler's internals, which are covered by
    # dedicated scheduler test suites elsewhere.
    with patch("hassette.core.web_api_service.Scheduler") as mock_scheduler_cls:
        mock_scheduler_cls.return_value.run_every = AsyncMock()
        return WebApiService(hassette)


@pytest.fixture
def web_api_service(unused_tcp_port_factory, tmp_path) -> WebApiService:
    return _make_web_api_service(unused_tcp_port_factory, tmp_path)


@contextmanager
def patch_uvicorn_serve() -> Iterator[tuple[MagicMock, MagicMock]]:
    """Patch hassette.core.web_api_service.uvicorn so serve() runs against a fake Server
    instance, without binding a real socket. Yields (mock_uvicorn, mock_server).
    """
    mock_server = MagicMock()
    mock_server.serve = AsyncMock()
    with (
        patch("hassette.core.web_api_service.uvicorn") as mock_uvicorn,
        patch("hassette.core.web_api_service._ShieldedStartupServer", return_value=mock_server),
    ):
        yield mock_uvicorn, mock_server


def port_is_bound(port: int) -> bool:
    """Return whether anything holds 127.0.0.1:port, probing with a bind so no connection is accepted."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        try:
            probe.bind(("127.0.0.1", port))
        except OSError:
            return True
    return False


class TestUvicornConfig:
    async def test_uses_websockets_sansio_protocol(self, web_api_service: WebApiService) -> None:
        with patch_uvicorn_serve() as (mock_uvicorn, _mock_server):
            await web_api_service.serve()

        config_call = mock_uvicorn.Config.call_args
        assert config_call.kwargs["ws"] == "websockets-sansio"

    async def test_disables_uvicorn_proxy_headers(self, web_api_service: WebApiService) -> None:
        """proxy_headers=False so uvicorn's own ProxyHeadersMiddleware never rewrites
        scope["client"] before trusted_proxies' peer check sees the real peer.
        """
        with patch_uvicorn_serve() as (mock_uvicorn, _mock_server):
            await web_api_service.serve()

        config_call = mock_uvicorn.Config.call_args
        assert config_call.kwargs["proxy_headers"] is False

    @pytest.mark.parametrize(("level", "expected"), [("INFO", False), ("DEBUG", True)])
    async def test_access_log_enabled_only_at_debug(
        self, unused_tcp_port_factory, tmp_path, level: str, expected: bool
    ) -> None:
        service = _make_web_api_service(unused_tcp_port_factory, tmp_path, logging={"web_api": level})
        with patch_uvicorn_serve() as (mock_uvicorn, _mock_server):
            await service.serve()

        config_call = mock_uvicorn.Config.call_args
        assert config_call.kwargs["access_log"] is expected

    async def test_serve_passes_resolved_credentials_to_app_factory(self, unused_tcp_port_factory, tmp_path) -> None:
        service = _make_web_api_service(unused_tcp_port_factory, tmp_path, host="127.0.0.1")

        await service.on_initialize()

        with (
            patch("hassette.core.web_api_service.create_fastapi_app") as mock_create_app,
            patch_uvicorn_serve(),
        ):
            await service.serve()

        mock_create_app.assert_called_once_with(
            service.hassette,
            auth_token=service._resolved_auth_token,
            trusted_proxies=service._trusted_proxies,
        )


class TestShutdownSocketCleanup:
    async def test_cancellation_calls_server_shutdown(self, web_api_service: WebApiService) -> None:
        with patch_uvicorn_serve() as (_mock_uvicorn, mock_server):
            mock_server.serve = AsyncMock(side_effect=asyncio.CancelledError)
            mock_server.shutdown = AsyncMock()

            with pytest.raises(asyncio.CancelledError):
                await web_api_service.serve()

            mock_server.shutdown.assert_awaited_once()


class TestCancelDuringStartup:
    async def test_cancel_during_create_server_final_tick_releases_port(
        self, unused_tcp_port_factory, tmp_path
    ) -> None:
        """A cancel landing on the tick where create_server is listening but hasn't returned closes the listener.

        Steps the loop one tick at a time: create_server yields once right after it starts
        listening, so a polling helper that sleeps would step past that window.
        """
        service = _make_web_api_service(unused_tcp_port_factory, tmp_path, host="127.0.0.1")

        serve_task = asyncio.create_task(service.serve())
        for _ in range(100):  # a numeric host needs no resolver thread, so this takes a handful of ticks
            if port_is_bound(service.port):
                break
            await asyncio.sleep(0)
        else:
            pytest.fail("serve() never started listening")
        serve_task.cancel()

        with pytest.raises(asyncio.CancelledError):
            await serve_task

        assert not port_is_bound(service.port)

    async def test_repeated_cancel_during_startup_waits_for_startup_and_releases_port(
        self, unused_tcp_port_factory, tmp_path
    ) -> None:
        """A second cancel must not end serve() while startup can still bind with nobody left to close it."""
        service = _make_web_api_service(unused_tcp_port_factory, tmp_path, host="127.0.0.1")
        real_startup = uvicorn.Server.startup
        startup_entered = asyncio.Event()
        release_startup = asyncio.Event()

        async def gated_startup(server: uvicorn.Server, sockets: list[socket.socket] | None = None) -> None:
            startup_entered.set()
            await release_startup.wait()
            await real_startup(server, sockets=sockets)

        with patch.object(uvicorn.Server, "startup", gated_startup):
            serve_task = asyncio.create_task(service.serve())
            await startup_entered.wait()

            serve_task.cancel()
            await asyncio.sleep(0)
            serve_task.cancel()
            await asyncio.sleep(0)
            assert not serve_task.done(), "serve() ended while startup was still in progress"

            release_startup.set()
            with pytest.raises(asyncio.CancelledError):
                await serve_task

        assert not port_is_bound(service.port)


class TestBindFailure:
    async def test_port_in_use_raises_fatal_error_naming_the_port(self, unused_tcp_port_factory, tmp_path) -> None:
        """Uvicorn's sys.exit(1) on a bind failure must surface as a FatalError, not a SystemExit."""
        service = _make_web_api_service(unused_tcp_port_factory, tmp_path, host="127.0.0.1")
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as holder:
            holder.bind(("127.0.0.1", service.port))
            holder.listen()

            with pytest.raises(FatalError, match=f"127.0.0.1:{service.port}"):
                await service.serve()


async def collect_log_messages(service: WebApiService) -> dict[str, list[str]]:
    """Run on_initialize() with service.logger patched and return the text of every
    info- and warning-level log call, keyed by level name.
    """
    with patch.object(service, "logger") as mock_logger:
        await service.on_initialize()

    return {
        "info": [call.args[0] for call in mock_logger.info.call_args_list],
        "warning": [call.args[0] for call in mock_logger.warning.call_args_list],
    }


class TestStartupGuards:
    """Hard-block guard (auth disabled + non-loopback host) and the informational TLS note (no
    trusted_proxies + non-loopback host).
    """

    async def test_auth_disabled_non_loopback_host_raises(self, unused_tcp_port_factory, tmp_path) -> None:
        service = _make_web_api_service(unused_tcp_port_factory, tmp_path, auth_enabled=False, host="0.0.0.0")

        with pytest.raises(FatalError) as exc_info:
            await service.on_initialize()

        message = str(exc_info.value)
        assert "auth_enabled" in message
        assert "host" in message

    @pytest.mark.parametrize("host", ["127.0.0.1", "localhost", "::1"])
    async def test_auth_disabled_loopback_host_does_not_raise(
        self, unused_tcp_port_factory, tmp_path, host: str
    ) -> None:
        service = _make_web_api_service(unused_tcp_port_factory, tmp_path, auth_enabled=False, host=host)

        await service.on_initialize()  # must not raise

    async def test_default_bind_logs_tls_note_at_info_without_warning(self, unused_tcp_port_factory, tmp_path) -> None:
        service = _make_web_api_service(unused_tcp_port_factory, tmp_path, host="0.0.0.0", trusted_proxies=())

        messages = await collect_log_messages(service)

        assert any("TLS" in msg for msg in messages["info"])
        assert messages["warning"] == []

    async def test_no_tls_note_when_trusted_proxies_configured(self, unused_tcp_port_factory, tmp_path) -> None:
        service = _make_web_api_service(
            unused_tcp_port_factory, tmp_path, host="0.0.0.0", trusted_proxies=("10.0.0.5",)
        )

        messages = await collect_log_messages(service)

        assert not any("TLS" in msg for msg in messages["info"] + messages["warning"])

    async def test_no_tls_note_when_host_is_loopback(self, unused_tcp_port_factory, tmp_path) -> None:
        service = _make_web_api_service(unused_tcp_port_factory, tmp_path, host="localhost", trusted_proxies=())

        messages = await collect_log_messages(service)

        assert not any("TLS" in msg for msg in messages["info"] + messages["warning"])


class TestTrustedProxyRefreshScheduling:
    """trusted_proxies hostname entries resolve at startup and periodically thereafter."""

    async def test_schedules_periodic_refresh_job(self, unused_tcp_port_factory, tmp_path) -> None:
        service = _make_web_api_service(unused_tcp_port_factory, tmp_path, host="127.0.0.1")

        await service.on_initialize()

        mock_scheduler = cast("MagicMock", service.scheduler)
        mock_scheduler.run_every.assert_awaited_once()
        call = mock_scheduler.run_every.call_args
        assert call.args[0] == service._refresh_trusted_proxies
        assert call.kwargs["name"] == "web_api_trusted_proxy_refresh"
        assert call.kwargs["if_exists"] == "skip"
        assert call.kwargs["mode"] == "single"

    async def test_resolves_trusted_proxies_at_startup(self, unused_tcp_port_factory, tmp_path) -> None:
        service = _make_web_api_service(
            unused_tcp_port_factory, tmp_path, host="127.0.0.1", trusted_proxies=("10.0.0.5",)
        )

        await service.on_initialize()

        assert service._trusted_proxies is not EMPTY_TRUSTED_PROXY_SET
        addr = ipaddress.ip_address("10.0.0.5")
        assert any(addr in network for network in service._trusted_proxies.all_networks())

    async def test_unresolvable_hostname_still_initializes_and_schedules_refresh(
        self, unused_tcp_port_factory, tmp_path
    ) -> None:
        service = _make_web_api_service(unused_tcp_port_factory, tmp_path, host="127.0.0.1", trusted_proxies=("caddy",))

        with patch_loop_getaddrinfo(side_effect=socket.gaierror("Name or service not known")):
            await service.on_initialize()

        assert service.is_ready()
        assert service._trusted_proxies.hostname_entries["caddy"] == frozenset()
        cast("MagicMock", service.scheduler).run_every.assert_awaited_once()

    async def test_reinitialize_during_dns_outage_keeps_previous_resolution(
        self, unused_tcp_port_factory, tmp_path
    ) -> None:
        """A second on_initialize() must not discard the last-known-good resolution."""
        service = _make_web_api_service(unused_tcp_port_factory, tmp_path, host="127.0.0.1", trusted_proxies=("caddy",))
        with patch_loop_getaddrinfo(return_value=[make_addrinfo("172.30.32.2")]):
            await service.on_initialize()

        with patch_loop_getaddrinfo(side_effect=socket.gaierror("temporary failure")):
            await service.on_initialize()

        assert ipaddress.ip_network("172.30.32.2/32") in service._trusted_proxies.all_networks()

    async def test_refresh_job_calls_refresh_trusted_proxies(self, unused_tcp_port_factory, tmp_path) -> None:
        service = _make_web_api_service(unused_tcp_port_factory, tmp_path, host="127.0.0.1")

        await service.on_initialize()

        previous = service._trusted_proxies
        with patch("hassette.core.web_api_service.refresh_trusted_proxies") as mock_refresh:
            mock_refresh.return_value = "sentinel-refreshed"
            await service._refresh_trusted_proxies()

        mock_refresh.assert_called_once_with(previous)
        assert service._trusted_proxies == "sentinel-refreshed"


class TestTokenResolution:
    async def test_resolves_and_stores_auth_token(self, unused_tcp_port_factory, tmp_path) -> None:
        service = _make_web_api_service(unused_tcp_port_factory, tmp_path, host="127.0.0.1")

        await service.on_initialize()

        assert service._resolved_auth_token
        assert isinstance(service._resolved_auth_token, str)
        assert (tmp_path / TOKEN_FILENAME).exists()

    async def test_auth_disabled_skips_token_and_trusted_proxy_resolution(
        self, unused_tcp_port_factory, tmp_path
    ) -> None:
        """Neither DefaultDenyMiddleware nor authorize_ws consult the resolved token or
        trusted_proxies when auth_enabled=False (both bypass entirely) — resolving/writing them
        would be pure overhead for a run that never uses them.
        """
        service = _make_web_api_service(
            unused_tcp_port_factory, tmp_path, host="127.0.0.1", auth_enabled=False, trusted_proxies=("10.0.0.5",)
        )

        await service.on_initialize()

        assert service._resolved_auth_token is None
        assert not (tmp_path / TOKEN_FILENAME).exists()
        assert service._trusted_proxies is EMPTY_TRUSTED_PROXY_SET
        cast("MagicMock", service.scheduler).run_every.assert_not_awaited()


class TestSchedulerServiceDependency:
    def test_depends_on_includes_scheduler_service(self) -> None:
        assert SchedulerService in WebApiService.depends_on


class TestSchedulerChildLifecycle:
    """Regression coverage for the Scheduler child being created exactly once, in __init__,
    rather than on every on_initialize() call.

    A same-instance shutdown() + initialize() runs on_initialize() again without re-construction.
    Resource children are only ever reset in __init__ — nothing evicts an entry on shutdown — so if
    add_child(Scheduler) ran inside on_initialize() instead, each re-initialization would append a new
    Scheduler child without removing the stale, already-shut-down one.
    """

    def test_scheduler_child_created_once_in_init(self, unused_tcp_port_factory, tmp_path) -> None:
        service = _make_web_api_service(unused_tcp_port_factory, tmp_path, host="127.0.0.1")

        assert service.scheduler in service.children
        assert sum(1 for child in service.children if child is service.scheduler) == 1

    async def test_second_initialize_does_not_accumulate_scheduler_children(
        self, unused_tcp_port_factory, tmp_path
    ) -> None:
        service = _make_web_api_service(unused_tcp_port_factory, tmp_path, host="127.0.0.1")
        first_scheduler = service.scheduler
        children_after_construction = list(service.children)

        await service.on_initialize()
        await service.on_initialize()  # simulate a second initialize() on the same instance

        assert service.scheduler is first_scheduler
        assert service.children == children_after_construction


class TestLiveAppTrustedProxyRefresh:
    """Regression coverage for a periodic refresh tick reaching the *already-serving* FastAPI
    app, not just ``WebApiService``'s own ``_trusted_proxies`` attribute.

    ``serve()`` builds the FastAPI app exactly once via ``create_fastapi_app()``, which copies
    the resolved trusted-proxy set onto ``app.state.trusted_proxies`` as a single reference.
    Before this fix, ``_refresh_trusted_proxies()`` only rebound the service's own attribute —
    nothing downstream re-read it, so the periodic ``Scheduler.run_every()`` job silently updated
    a value the live, already-serving app never saw again. A unit test of
    ``refresh_trusted_proxies()`` alone (or one that builds a brand-new ``create_fastapi_app()``
    with the refreshed value) can't catch this — it has to exercise a live app that was already
    built by ``serve()`` before the refresh tick fires.
    """

    async def test_refresh_after_serve_updates_live_app_trusted_proxies(
        self, unused_tcp_port_factory, tmp_path
    ) -> None:
        service = _make_web_api_service(
            unused_tcp_port_factory, tmp_path, host="127.0.0.1", trusted_proxies=("proxy.internal",)
        )

        with patch_loop_getaddrinfo(return_value=[make_addrinfo("172.30.32.2")]):
            await service.on_initialize()

        # Simulate serve() building the live FastAPI app, without actually binding a socket.
        with patch_uvicorn_serve():
            await service.serve()

        assert service._app is not None
        live_app = service._app

        # Before the refresh tick: the original resolved address is trusted.
        transport = ASGITransport(app=live_app, client=("172.30.32.2", 12345))
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/api/config")
        assert resp.status_code == 200

        # Periodic refresh tick: the sibling proxy container was recreated with a new IP (same
        # hostname) -- exactly as Scheduler.run_every() would observe on its next run.
        with patch_loop_getaddrinfo(return_value=[make_addrinfo("172.30.32.9")]):
            await service._refresh_trusted_proxies()

        # The refresh must be visible on the SAME already-serving app instance -- no rebuild.
        assert service._app is live_app

        new_transport = ASGITransport(app=live_app, client=("172.30.32.9", 12345))
        async with AsyncClient(transport=new_transport, base_url="http://test") as client:
            new_resp = await client.get("/api/config")
        assert new_resp.status_code == 200

        old_transport = ASGITransport(app=live_app, client=("172.30.32.2", 12345))
        async with AsyncClient(transport=old_transport, base_url="http://test") as client:
            old_resp = await client.get("/api/config")
        assert old_resp.status_code == 401
