"""A Home Assistant ingress-shaped reverse proxy for e2e tests.

Modeled on HA core's ingress view (``homeassistant/components/hassio/ingress.py``): it serves
``/api/hassio_ingress/<token>/<path>``, strips the prefix, sets ``X-Ingress-Path`` the way core does, forwards
the client's other headers minus core's filter list, and proxies both HTTP and WebSocket traffic. Any path
outside the prefix gets a 404, so a frontend URL that escapes the prefix fails the request instead of
silently reaching the app at the origin root.

Runs on its own event loop in a daemon thread, beside the uvicorn server from ``tests/support/uvicorn.py``.
"""

import asyncio
import threading
from collections.abc import Iterator
from contextlib import contextmanager

import aiohttp
from aiohttp import hdrs, web

from tests.support.uvicorn import LIVE_SERVER_START_TIMEOUT_SECONDS, LIVE_SERVER_STOP_TIMEOUT_SECONDS, get_free_port

INGRESS_TOKEN = "e2e_ingress_token"
INGRESS_PATH = f"/api/hassio_ingress/{INGRESS_TOKEN}"

_REQUEST_HEADERS_FILTER = {
    hdrs.HOST,
    hdrs.CONTENT_LENGTH,
    hdrs.CONTENT_ENCODING,
    hdrs.TRANSFER_ENCODING,
    hdrs.ACCEPT_ENCODING,
    hdrs.SEC_WEBSOCKET_EXTENSIONS,
    hdrs.SEC_WEBSOCKET_PROTOCOL,
    hdrs.SEC_WEBSOCKET_VERSION,
    hdrs.SEC_WEBSOCKET_KEY,
}
_RESPONSE_HEADERS_FILTER = {hdrs.TRANSFER_ENCODING, hdrs.CONTENT_LENGTH, hdrs.CONTENT_ENCODING}


def _upstream_headers(request: web.Request) -> dict[str, str]:
    headers = {name: value for name, value in request.headers.items() if name not in _REQUEST_HEADERS_FILTER}
    headers["X-Ingress-Path"] = INGRESS_PATH
    return headers


async def _forward_ws(source: web.WebSocketResponse | aiohttp.ClientWebSocketResponse, target) -> None:
    async for msg in source:
        if msg.type is aiohttp.WSMsgType.TEXT:
            await target.send_str(msg.data)
        elif msg.type is aiohttp.WSMsgType.BINARY:
            await target.send_bytes(msg.data)
    await target.close()


def _make_app(upstream: str, session: aiohttp.ClientSession) -> web.Application:
    async def proxy(request: web.Request) -> web.StreamResponse:
        if request.match_info["token"] != INGRESS_TOKEN:
            raise web.HTTPNotFound
        url = f"{upstream}/{request.match_info['path']}"

        if request.headers.get(hdrs.UPGRADE, "").lower() == "websocket":
            server_ws = web.WebSocketResponse()
            await server_ws.prepare(request)
            async with session.ws_connect(
                url.replace("http", "ws", 1), headers=_upstream_headers(request)
            ) as client_ws:
                await asyncio.wait(
                    [
                        asyncio.create_task(_forward_ws(server_ws, client_ws)),
                        asyncio.create_task(_forward_ws(client_ws, server_ws)),
                    ],
                    return_when=asyncio.FIRST_COMPLETED,
                )
            return server_ws

        async with session.request(
            request.method,
            url,
            params=request.query,
            headers=_upstream_headers(request),
            data=await request.read() if request.can_read_body else None,
            allow_redirects=False,
        ) as upstream_resp:
            headers = {k: v for k, v in upstream_resp.headers.items() if k not in _RESPONSE_HEADERS_FILTER}
            return web.Response(status=upstream_resp.status, headers=headers, body=await upstream_resp.read())

    app = web.Application()
    app.router.add_route("*", "/api/hassio_ingress/{token}/{path:.*}", proxy)
    return app


@contextmanager
def ingress_proxy(upstream: str) -> Iterator[str]:
    """Run the proxy in front of ``upstream`` (e.g. ``http://127.0.0.1:8126``); yields its ingress URL."""
    loop = asyncio.new_event_loop()
    thread = threading.Thread(target=loop.run_forever, daemon=True)
    thread.start()
    port = get_free_port()

    async def start() -> tuple[web.AppRunner, aiohttp.ClientSession]:
        session = aiohttp.ClientSession(auto_decompress=False)
        # A short shutdown timeout: the browser's proxied WebSocket stays open until Playwright releases it.
        runner = web.AppRunner(_make_app(upstream, session), shutdown_timeout=1)
        await runner.setup()
        await web.TCPSite(runner, "127.0.0.1", port).start()
        return runner, session

    async def stop(runner: web.AppRunner, session: aiohttp.ClientSession) -> None:
        await runner.cleanup()
        await session.close()

    runner, session = asyncio.run_coroutine_threadsafe(start(), loop).result(timeout=LIVE_SERVER_START_TIMEOUT_SECONDS)
    try:
        yield f"http://127.0.0.1:{port}{INGRESS_PATH}/"
    finally:
        asyncio.run_coroutine_threadsafe(stop(runner, session), loop).result(timeout=LIVE_SERVER_STOP_TIMEOUT_SECONDS)
        loop.call_soon_threadsafe(loop.stop)
        thread.join(timeout=LIVE_SERVER_STOP_TIMEOUT_SECONDS)
        loop.close()
