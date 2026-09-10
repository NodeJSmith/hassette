"""Not-ready read behavior for StateProxy's sync read path.

Two invariants are pinned here. `yield_domain_states` must run its readiness check
eagerly at call time rather than deferring it to the first `next()`, so a caller that
builds the generator without iterating it still sees an unavailable cache. And the read
path must raise on the first failed check — it holds the event loop thread, so any retry
loop with a blocking wait between attempts would stall the very code that transitions
cache freshness.
"""

import asyncio
from collections.abc import Callable

import pytest

from hassette.core.state_proxy import StateCacheFreshness, StateProxy
from hassette.exceptions import ResourceNotReadyError
from hassette.resources.base import Resource
from tests.support.mock_hassette import make_mock_hassette


def stub_state_proxy() -> StateProxy:
    hassette = make_mock_hassette(
        sealed=False,
        logging={"state_proxy": "INFO"},
        lifecycle={"resource_shutdown_timeout_seconds": 5, "task_cancellation_timeout_seconds": 5},
    )
    obj = StateProxy.__new__(StateProxy)
    Resource.__init__(obj, hassette, parent=hassette)
    # Freshly-constructed Resource: ready_event is unset, so is_ready() is naturally
    # False — no need to patch the method. Empty states + not-ready is the cold-start path.
    obj.states = {}
    obj._cache_freshness = StateCacheFreshness.UNAVAILABLE
    obj._ready_reason = "test cold start"
    # has_initial_state_capability() reads this event; a real StateProxy.__init__ always
    # creates it unset, matching the cold-start "capability not reached" state under test.
    obj._initial_state_capability_event = asyncio.Event()
    return obj


def test_yield_domain_states_raises_eagerly_when_not_ready() -> None:
    """The readiness check runs at call time, not deferred to the first iteration step."""
    proxy = stub_state_proxy()

    # Calling must raise here — not only once iteration begins. A plain generator function
    # would return a generator object without ever running the check.
    with pytest.raises(ResourceNotReadyError):
        proxy.yield_domain_states("light")


@pytest.mark.parametrize(
    "read",
    [
        pytest.param(lambda proxy: proxy.get_state("light.kitchen"), id="get_state"),
        pytest.param(lambda proxy: proxy.get_state_once("light.kitchen"), id="get_state_once"),
        pytest.param(lambda proxy: proxy.yield_domain_states("light"), id="yield_domain_states"),
        pytest.param(lambda proxy: proxy.get_domain_states("light"), id="get_domain_states"),
    ],
)
def test_not_ready_read_checks_once_and_raises(read: Callable[[StateProxy], object]) -> None:
    """An unavailable cache raises on the first check — no retry loop on the read path.

    Counting the checks (rather than timing the call) is what makes this deterministic: a
    retry would re-run the check, and it could only ever observe the same frozen freshness
    because these reads run on the event loop thread that would have to change it.
    """
    proxy = stub_state_proxy()
    checks = 0
    real_check = proxy._check_ready

    def counting_check() -> None:
        nonlocal checks
        checks += 1
        real_check()

    proxy._check_ready = counting_check  # pyright: ignore[reportAttributeAccessIssue]

    with pytest.raises(ResourceNotReadyError):
        read(proxy)

    assert checks == 1
