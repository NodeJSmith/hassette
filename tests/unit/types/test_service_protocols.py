"""Structural-conformance tests for SchedulerServiceProtocol and StateReader.

These protocols are plain (not @runtime_checkable), so isinstance() is not available.
Conformance is verified two ways:
1. Runtime hasattr checks — prove the concrete classes define every named member.
2. Pyright assignment — the typed helper functions below are the pyright-level proof;
   pyright validates them during type-checking, catching signature mismatches at CI time.
"""

from typing import TYPE_CHECKING, Any

import pytest

import hassette.types as ht
from hassette.core.scheduler_service import SchedulerService
from hassette.core.state_proxy import StateProxy

if TYPE_CHECKING:
    from hassette.types import SchedulerServiceProtocol, StateReader

# Protocol member inventories

_SCHEDULER_SERVICE_PROTOCOL_MEMBERS = [
    "task_bucket",
    "add_job",
    "dequeue_job",
    "register_removal_callback",
    "deregister_removal_callback",
    "mark_job_cancelled",
    "remove_jobs_by_owner",
]

_STATE_READER_MEMBERS = [
    "get_state",
    "num_domain_states",
    "yield_domain_states",
    "__contains__",
]


# Runtime hasattr conformance


def _all_annotations(cls: type) -> dict[str, Any]:
    """Collect __annotations__ from cls and all its bases (MRO order)."""
    result: dict[str, Any] = {}
    for base in reversed(cls.__mro__):
        result.update(getattr(base, "__annotations__", {}))
    return result


class TestSchedulerServiceProtocolConformance:
    """SchedulerService defines every member named in SchedulerServiceProtocol."""

    def test_task_bucket_annotated(self) -> None:
        """task_bucket is declared as a class-body annotation on Resource (inherited by SchedulerService)."""
        annotations = _all_annotations(SchedulerService)
        assert "task_bucket" in annotations, (
            "SchedulerService (via Resource) is missing 'task_bucket' annotation required by SchedulerServiceProtocol"
        )

    @pytest.mark.parametrize("member", [m for m in _SCHEDULER_SERVICE_PROTOCOL_MEMBERS if m != "task_bucket"])
    def test_scheduler_service_has_member(self, member: str) -> None:
        assert hasattr(SchedulerService, member), (
            f"SchedulerService is missing '{member}' required by SchedulerServiceProtocol"
        )


class TestStateReaderConformance:
    """StateProxy defines every member named in StateReader."""

    @pytest.mark.parametrize("member", _STATE_READER_MEMBERS)
    def test_state_proxy_has_member(self, member: str) -> None:
        assert hasattr(StateProxy, member), f"StateProxy is missing '{member}' required by StateReader"


# Pyright-level structural conformance helpers. These functions are never called
# at runtime; the assignment in each body is the structural proof — pyright validates
# at type-check time that the concrete class is assignable to the protocol, catching
# any signature drift in CI.


def _check_scheduler_service_protocol(svc: SchedulerService) -> None:
    """Pyright verifies SchedulerService is assignable to SchedulerServiceProtocol."""
    _: SchedulerServiceProtocol = svc


def _check_state_reader(proxy: StateProxy) -> None:
    """Pyright verifies StateProxy is assignable to StateReader."""
    _: StateReader = proxy


# Export / import surface checks


def test_both_in_all() -> None:
    """Both protocols appear in hassette.types.__all__."""
    assert "SchedulerServiceProtocol" in ht.__all__
    assert "StateReader" in ht.__all__
