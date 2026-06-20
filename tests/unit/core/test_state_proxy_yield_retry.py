"""Regression test for the inert @retry on StateProxy.yield_domain_states.

yield_domain_states is decorated with @retry(ResourceNotReadyError), but it was
written as a generator that raised inside its body — so @retry wrapped the call
(which only returns a generator object) and the readiness check never ran at call
time. Retries never fired on cold start. The check must run eagerly so @retry
can wrap it; this pins the eager-raise behavior.
"""

import pytest

from hassette.core.state_proxy import StateProxy
from hassette.exceptions import ResourceNotReadyError
from hassette.resources.base import Resource
from hassette.test_utils import make_mock_hassette


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
    obj._ready_reason = "test cold start"
    return obj


def test_yield_domain_states_raises_eagerly_when_not_ready() -> None:
    """The readiness check runs at call time so @retry can wrap it (not deferred to iteration)."""
    proxy = stub_state_proxy()

    # Calling must raise here — not only once iteration begins. With the old
    # generator form this returned a generator without raising, so @retry was inert.
    with pytest.raises(ResourceNotReadyError):
        proxy.yield_domain_states("light")
