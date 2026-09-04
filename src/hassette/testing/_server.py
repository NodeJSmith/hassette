from collections import defaultdict, deque
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

from aiohttp import web
from whenever import PlainDateTime

from hassette.utils.request_utils import orjson_dump

UNEXPECTED_REQUEST_STATUS = 599


@dataclass(eq=True, frozen=True)
class Key:
    method: str
    path: str
    query: str


@dataclass
class Expected:
    status: int
    json: Any


class SimpleTestServer:
    """Minimal HTTP double for Home Assistant.

    Usage:
      mock.expect("GET", "/api/states/light.kitchen", "", json={...})
      app.router.add_route("*", "/{tail:.*}", mock.handle_request)
    """

    def __init__(self) -> None:
        self._expectations: dict[Key, deque[Expected]] = defaultdict(deque)
        self._unexpected: list[Key] = []

    # registering expectations

    def expect(
        self,
        method: str,
        path: str,
        query: str = "",
        *,
        json: Any = None,
        status: int = 200,
        repeat: int = 1,
    ) -> None:
        key = Key(method.upper(), path, query or "")
        for _ in range(repeat):
            self._expectations[key].append(Expected(status=status, json=json))

    @staticmethod
    def make_history_path(
        entity_ids: Iterable[str],
        start: PlainDateTime,
        end: PlainDateTime,
        *,
        minimal: bool = False,
    ) -> tuple[str, str]:
        ids = ",".join(entity_ids)
        path = f"/api/history/period/{start.format_iso()}"
        qs = f"filter_entity_id={ids}&end_time={end.format_iso()}"
        if minimal:
            qs += "&minimal_response=true"
        return path, qs

    # request handler

    async def handle_request(self, request: web.Request) -> web.StreamResponse:
        key = Key(request.method, request.path, request.query_string or "")
        bucket = self._expectations.get(key)

        if not bucket:
            # record so teardown can fail loudly with details
            self._unexpected.append(key)
            return web.Response(status=UNEXPECTED_REQUEST_STATUS, text=f"Unexpected request: {key}")

        exp = bucket.popleft()
        if exp.json is None:
            return web.Response(status=exp.status)
        return web.json_response(exp.json, status=exp.status, dumps=orjson_dump)

    # teardown assertions

    def leftovers(self) -> list[tuple[Key, int]]:
        return [(k, len(v)) for k, v in self._expectations.items() if v]

    def assert_clean(self) -> None:
        leftovers = self.leftovers()

        errors = []
        if self._unexpected:
            errors.append(f"Unexpected requests: {self._unexpected}")

        if leftovers:
            errors.append(f"Expected requests not seen: {leftovers}")

        assert not errors, f"MockHaApi assertions failed: {errors}"

    def reset(self) -> None:
        """Clear queued expectations and the unexpected-request log.

        Call between tests to reuse the same server instance without state pollution.
        """
        self._expectations.clear()
        self._unexpected.clear()
