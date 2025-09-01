from collections import defaultdict, deque
from collections.abc import Iterable
from dataclasses import astuple, dataclass
from typing import Any

from aiohttp import web
from whenever import PlainDateTime

# Key = tuple[str, str, str]  # (METHOD, PATH, QUERYSTRING)


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
    """
    Minimal HTTP double for Home Assistant.

    Usage:
      mock.expect("GET", "/api/states/light.kitchen", "", json={...})
      app.router.add_route("*", "/{tail:.*}", mock.handle_request)
    """

    def __init__(self) -> None:
        self._expectations: dict[Key, deque[Expected]] = defaultdict(deque)
        self._unexpected: list[Key] = []

    # ----- registering expectations -----

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

    # Nice helper for history endpoints (keeps query ordering stable)
    @staticmethod
    def make_history_path(
        entity_ids: Iterable[str],
        start: PlainDateTime,
        end: PlainDateTime,
        *,
        minimal: bool = False,
    ):
        ids = ",".join(entity_ids)
        path = f"/api/history/period/{start.format_common_iso()}"
        qs = f"filter_entity_id={ids}&end_time={end.format_common_iso()}"
        if minimal:
            qs += "&minimal_response=true"
        # Caller still needs to provide METHOD, so this returns (PATH, QUERY)
        return path, qs  # (path, query)

    # ----- request handler -----

    async def handle_request(self, request: web.Request) -> web.StreamResponse:
        key = Key(request.method, request.path, request.query_string or "")
        bucket = self._expectations.get(key)

        if not bucket:
            # record so teardown can fail loudly with details
            self._unexpected.append(key)
            return web.Response(status=599, text=f"Unexpected request: {key}")

        exp = bucket.popleft()
        if exp.json is None:
            return web.Response(status=exp.status)
        return web.json_response(exp.json, status=exp.status)

    # ----- teardown assertions -----

    def _leftovers(self) -> list[tuple[Key, int]]:
        return [(k, len(v)) for k, v in self._expectations.items() if v]

    def assert_clean(self) -> None:
        leftovers = self._leftovers()

        errors = []
        if self._unexpected:
            errors.append(f"Unexpected requests: {self._unexpected}")

        if leftovers:
            errors.append(f"Expected requests not seen: {leftovers}")

        assert not errors, f"MockHaApi assertions failed: {errors}"

    def dump_all(self):
        expectations = {astuple(k): [astuple(e) for e in v] for k, v in self._expectations.items()}
        expectations = {str(k): v for k, v in expectations.items() if v}

        # expectations = {str(k): v for k, v in self._expectations.items() if v}
        unexpected = [str(k) for k in self._unexpected]

        return {"expectations": expectations, "unexpected": unexpected}
