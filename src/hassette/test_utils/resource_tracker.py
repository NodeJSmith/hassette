"""Pytest plugin: track closeable resource lifecycle.

Monkeypatches resource constructors and close/shutdown methods to record which
test created each resource and whether it was properly cleaned up. Reports
unclosed resources at session end with creation context (test name + stack).

Tracked resource types:
- EventStreamService (anyio memory streams)
- MemoryObjectReceiveStream.clone() (cloned streams passed to BusService)
- aiosqlite.Connection (database connections)
- aiohttp.ClientSession (HTTP sessions for REST API and WebSocket)
- ThreadPoolExecutor (sync executor thread pools)

Quiet on clean runs — only prints when leaks are detected.

xdist-aware: each worker writes its results to a JSON file; the controller
aggregates all workers in pytest_sessionfinish.

Disable by setting HASSETTE_DISABLE_RESOURCE_TRACKER=1.
"""

import contextlib
import json
import os
import traceback
import typing
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import aiohttp
import aiosqlite
import pytest
from anyio.streams.memory import MemoryObjectReceiveStream

from hassette.core.event_stream_service import EventStreamService

if typing.TYPE_CHECKING:
    from collections.abc import Iterator

# Frames of caller context to capture in creation stacks.
_STACK_CONTEXT_FRAMES = 6


class _TrackedResource:
    __slots__ = ("closed", "creation_stack", "kind", "obj", "obj_id", "test_name")

    def __init__(self, kind: str, obj_id: int, test_name: str, creation_stack: str, obj: object) -> None:
        self.kind = kind
        self.obj_id = obj_id
        self.test_name = test_name
        self.creation_stack = creation_stack
        self.closed = False
        # Strong ref prevents id() reuse while the resource is tracked as open.
        self.obj: object | None = obj

    def to_dict(self) -> dict[str, typing.Any]:
        return {
            "kind": self.kind,
            "test_name": self.test_name,
            "creation_stack": self.creation_stack,
            "closed": self.closed,
        }


class ResourceTracker:
    def __init__(self) -> None:
        self.resources: dict[int, _TrackedResource] = {}
        self._original_ess_init: typing.Any = None
        self._original_ess_close: typing.Any = None
        self._original_recv_clone: typing.Any = None
        self._original_recv_aclose: typing.Any = None
        self._original_aiosqlite_connect: typing.Any = None
        self._original_aiosqlite_close: typing.Any = None
        self._original_aiohttp_init: typing.Any = None
        self._original_aiohttp_close: typing.Any = None
        self._original_executor_init: typing.Any = None
        self._original_executor_shutdown: typing.Any = None

    def _current_test(self) -> str:
        return os.environ.get("PYTEST_CURRENT_TEST", "<unknown>")

    def _stack(self) -> str:
        frames = traceback.extract_stack()
        # Drop the 3 innermost frames (this method, record_creation, and the monkeypatch wrapper).
        relevant = frames[:-3][-_STACK_CONTEXT_FRAMES:]
        return "".join(traceback.format_list(relevant))

    def record_creation(self, kind: str, obj: object) -> None:
        obj_id = id(obj)
        self.resources[obj_id] = _TrackedResource(
            kind=kind,
            obj_id=obj_id,
            test_name=self._current_test(),
            creation_stack=self._stack(),
            obj=obj,
        )

    def record_close(self, kind: str, obj: object) -> None:
        obj_id = id(obj)
        if obj_id in self.resources:
            self.resources[obj_id].closed = True
            self.resources[obj_id].obj = None

    def install_patches(self) -> None:
        self._patch_event_stream_service()
        self._patch_recv_stream_clone()
        self._patch_aiosqlite()
        self._patch_aiohttp()
        self._patch_thread_pool_executor()

    def remove_patches(self) -> None:
        self._unpatch_event_stream_service()
        self._unpatch_recv_stream_clone()
        self._unpatch_aiosqlite()
        self._unpatch_aiohttp()
        self._unpatch_thread_pool_executor()

    def _patch_event_stream_service(self) -> None:
        self._original_ess_init = EventStreamService.__init__
        self._original_ess_close = EventStreamService.close_streams

        original_init = self._original_ess_init
        original_close = self._original_ess_close

        def patched_init(self_ess: typing.Any, *args: typing.Any, **kwargs: typing.Any) -> None:
            original_init(self_ess, *args, **kwargs)
            self.record_creation("EventStreamService", self_ess)

        async def patched_close(self_ess: typing.Any) -> None:
            await original_close(self_ess)
            self.record_close("EventStreamService", self_ess)

        EventStreamService.__init__ = patched_init  # pyright: ignore[reportAttributeAccessIssue]
        EventStreamService.close_streams = patched_close  # pyright: ignore[reportAttributeAccessIssue]

    def _unpatch_event_stream_service(self) -> None:
        if self._original_ess_init is not None:
            EventStreamService.__init__ = self._original_ess_init  # pyright: ignore[reportAttributeAccessIssue]
        if self._original_ess_close is not None:
            EventStreamService.close_streams = self._original_ess_close  # pyright: ignore[reportAttributeAccessIssue]

    def _patch_recv_stream_clone(self) -> None:
        self._original_recv_clone = MemoryObjectReceiveStream.clone
        self._original_recv_aclose = MemoryObjectReceiveStream.aclose

        original_clone = self._original_recv_clone
        original_aclose = self._original_recv_aclose

        def patched_clone(self_stream: typing.Any) -> MemoryObjectReceiveStream:  # pyright: ignore[reportReturnType]
            cloned = original_clone(self_stream)
            self.record_creation("MemoryObjectReceiveStream.clone", cloned)
            return cloned

        async def patched_aclose(self_stream: typing.Any) -> None:
            await original_aclose(self_stream)
            self.record_close("MemoryObjectReceiveStream.clone", self_stream)

        MemoryObjectReceiveStream.clone = patched_clone  # pyright: ignore[reportAttributeAccessIssue]
        MemoryObjectReceiveStream.aclose = patched_aclose  # pyright: ignore[reportAttributeAccessIssue]

    def _unpatch_recv_stream_clone(self) -> None:
        if self._original_recv_clone is not None:
            MemoryObjectReceiveStream.clone = self._original_recv_clone  # pyright: ignore[reportAttributeAccessIssue]
        if self._original_recv_aclose is not None:
            MemoryObjectReceiveStream.aclose = self._original_recv_aclose  # pyright: ignore[reportAttributeAccessIssue]

    def _patch_aiosqlite(self) -> None:
        self._original_aiosqlite_connect = aiosqlite.connect
        self._original_aiosqlite_close = aiosqlite.Connection.close

        original_connect = self._original_aiosqlite_connect
        original_close = self._original_aiosqlite_close

        def patched_connect(database: typing.Any, **kwargs: typing.Any) -> aiosqlite.Connection:
            conn = original_connect(database, **kwargs)
            self.record_creation("aiosqlite.Connection", conn)
            return conn

        async def patched_close(self_conn: typing.Any) -> None:
            await original_close(self_conn)
            self.record_close("aiosqlite.Connection", self_conn)

        aiosqlite.connect = patched_connect  # pyright: ignore[reportAttributeAccessIssue]
        aiosqlite.Connection.close = patched_close  # pyright: ignore[reportAttributeAccessIssue]

    def _unpatch_aiosqlite(self) -> None:
        if self._original_aiosqlite_connect is not None:
            aiosqlite.connect = self._original_aiosqlite_connect  # pyright: ignore[reportAttributeAccessIssue]
        if self._original_aiosqlite_close is not None:
            aiosqlite.Connection.close = self._original_aiosqlite_close  # pyright: ignore[reportAttributeAccessIssue]

    def _patch_aiohttp(self) -> None:
        self._original_aiohttp_init = aiohttp.ClientSession.__init__
        self._original_aiohttp_close = aiohttp.ClientSession.close

        original_init = self._original_aiohttp_init
        original_close = self._original_aiohttp_close

        def patched_init(self_session: typing.Any, *args: typing.Any, **kwargs: typing.Any) -> None:
            original_init(self_session, *args, **kwargs)
            self.record_creation("aiohttp.ClientSession", self_session)

        async def patched_close(self_session: typing.Any) -> None:
            await original_close(self_session)
            self.record_close("aiohttp.ClientSession", self_session)

        aiohttp.ClientSession.__init__ = patched_init  # pyright: ignore[reportAttributeAccessIssue]
        aiohttp.ClientSession.close = patched_close  # pyright: ignore[reportAttributeAccessIssue]

    def _unpatch_aiohttp(self) -> None:
        if self._original_aiohttp_init is not None:
            aiohttp.ClientSession.__init__ = self._original_aiohttp_init  # pyright: ignore[reportAttributeAccessIssue]
        if self._original_aiohttp_close is not None:
            aiohttp.ClientSession.close = self._original_aiohttp_close  # pyright: ignore[reportAttributeAccessIssue]

    def _patch_thread_pool_executor(self) -> None:
        self._original_executor_init = ThreadPoolExecutor.__init__
        self._original_executor_shutdown = ThreadPoolExecutor.shutdown

        original_init = self._original_executor_init
        original_shutdown = self._original_executor_shutdown

        def patched_init(self_executor: typing.Any, *args: typing.Any, **kwargs: typing.Any) -> None:
            original_init(self_executor, *args, **kwargs)
            self.record_creation("ThreadPoolExecutor", self_executor)

        def patched_shutdown(self_executor: typing.Any, *args: typing.Any, **kwargs: typing.Any) -> None:
            original_shutdown(self_executor, *args, **kwargs)
            self.record_close("ThreadPoolExecutor", self_executor)

        ThreadPoolExecutor.__init__ = patched_init  # pyright: ignore[reportAttributeAccessIssue]
        ThreadPoolExecutor.shutdown = patched_shutdown  # pyright: ignore[reportAttributeAccessIssue]

    def _unpatch_thread_pool_executor(self) -> None:
        if self._original_executor_init is not None:
            ThreadPoolExecutor.__init__ = self._original_executor_init  # pyright: ignore[reportAttributeAccessIssue]
        if self._original_executor_shutdown is not None:
            ThreadPoolExecutor.shutdown = self._original_executor_shutdown  # pyright: ignore[reportAttributeAccessIssue]

    def unclosed(self) -> list[_TrackedResource]:
        return [r for r in self.resources.values() if not r.closed]

    def save_results(self, path: str) -> None:
        unclosed = self.unclosed()
        data = {
            "total": len(self.resources),
            "closed": len(self.resources) - len(unclosed),
            "unclosed": [r.to_dict() for r in unclosed],
        }
        with open(path, "w") as f:
            json.dump(data, f, indent=2)


def _results_dir(config: pytest.Config) -> Path:
    base = config.rootpath / ".resource-tracker"
    base.mkdir(exist_ok=True)
    return base


def _worker_id() -> str:
    return os.environ.get("PYTEST_XDIST_WORKER", "main")


def format_report(results: list[dict[str, typing.Any]]) -> str:
    total = sum(r["total"] for r in results)
    closed = sum(r["closed"] for r in results)
    all_unclosed: list[dict[str, typing.Any]] = []
    for r in results:
        all_unclosed.extend(r["unclosed"])

    if not all_unclosed:
        return ""

    by_test: dict[str, list[dict[str, typing.Any]]] = {}
    for u in all_unclosed:
        by_test.setdefault(u["test_name"], []).append(u)

    lines = [
        "",
        "=" * 80,
        "RESOURCE LEAK REPORT",
        "=" * 80,
        f"Total tracked: {total}  |  Closed: {closed}  |  UNCLOSED: {len(all_unclosed)}",
        "",
        "-" * 80,
    ]

    for test_name, resources in sorted(by_test.items()):
        lines.append(f"\n  {test_name}")
        for r in resources:
            lines.append(f"    [{r['kind']}]")
            lines.extend(f"      {stack_line}" for stack_line in r["creation_stack"].strip().splitlines())

    lines.extend(["", "=" * 80, ""])
    return "\n".join(lines)


@pytest.fixture(autouse=True, scope="session")
def _resource_tracker(request: pytest.FixtureRequest) -> "Iterator[None]":  # pyright: ignore[reportUnusedFunction]
    if os.environ.get("HASSETTE_DISABLE_RESOURCE_TRACKER"):
        yield
        return

    tracker = ResourceTracker()
    tracker.install_patches()
    yield
    tracker.remove_patches()

    results_dir = _results_dir(request.config)
    worker = _worker_id()
    tracker.save_results(str(results_dir / f"{worker}.json"))


def pytest_sessionfinish(session: pytest.Session, exitstatus: int) -> None:  # noqa: ARG001
    if os.environ.get("HASSETTE_DISABLE_RESOURCE_TRACKER"):
        return
    if _worker_id() != "main":
        return

    results_dir = _results_dir(session.config)
    results: list[dict[str, typing.Any]] = []

    for child in sorted(results_dir.iterdir()):
        if child.suffix != ".json":
            continue
        with child.open() as fh:
            results.append(json.load(fh))
        child.unlink()

    with contextlib.suppress(OSError):
        results_dir.rmdir()

    if not results:
        return

    report = format_report(results)
    if report:
        print(report)
