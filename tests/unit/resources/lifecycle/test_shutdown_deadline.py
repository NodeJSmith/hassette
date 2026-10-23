"""Tests for the shutdown-deadline helpers in ``hassette.resources.shutdown_deadline``."""

import pytest

from hassette.resources.shutdown_deadline import (
    clamp_to_shutdown_deadline,
    deadline_in,
    shutdown_deadline_remaining,
    shutdown_hook_bound,
    tighten_shutdown_deadline,
)
from tests.support.mock_hassette import make_mock_hassette

from .conftest import SimpleParent


@pytest.fixture
def resource() -> SimpleParent:
    hassette = make_mock_hassette(sealed=False)
    hassette.config.lifecycle.shutdown_timeout_seconds = 10.0
    return SimpleParent(hassette)


async def test_no_deadline_reads_as_none(resource: SimpleParent) -> None:
    assert shutdown_deadline_remaining(resource) is None


async def test_passed_deadline_reads_as_zero(resource: SimpleParent) -> None:
    resource._shutdown_deadline = deadline_in(-5.0)

    assert shutdown_deadline_remaining(resource) == 0.0


async def test_clamp_keeps_the_cap_without_a_deadline(resource: SimpleParent) -> None:
    assert clamp_to_shutdown_deadline(resource, 3.0) == 3.0
    assert clamp_to_shutdown_deadline(resource, None) is None


async def test_clamp_shortens_the_cap_to_what_is_left(resource: SimpleParent) -> None:
    resource._shutdown_deadline = deadline_in(1.0)

    bound = clamp_to_shutdown_deadline(resource, 3.0)

    assert 0.0 < bound <= 1.0


async def test_hook_bound_is_the_per_hook_timeout_clamped_to_the_deadline(resource: SimpleParent) -> None:
    assert shutdown_hook_bound(resource) == 10.0

    resource._shutdown_deadline = deadline_in(2.0)

    bound = shutdown_hook_bound(resource)
    assert bound is not None
    assert 0.0 < bound <= 2.0


async def test_hook_bound_ignores_the_per_hook_timeout_when_it_does_not_apply(
    resource: SimpleParent, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A foundation service's hooks are bounded by the stage's deadline alone."""
    monkeypatch.setattr(SimpleParent, "shutdown_hook_timeout_applies", False)

    assert shutdown_hook_bound(resource) is None

    resource._shutdown_deadline = deadline_in(30.0)

    bound = shutdown_hook_bound(resource)
    assert bound is not None
    assert bound > 10.0


async def test_tighten_sets_a_deadline_when_none_exists(resource: SimpleParent) -> None:
    tighten_shutdown_deadline(resource, 123.0)

    assert resource._shutdown_deadline == 123.0


async def test_tighten_only_shortens_an_existing_deadline(resource: SimpleParent) -> None:
    """A caller joining an attempt already in flight can tighten its deadline but never extend it."""
    resource._shutdown_deadline = 100.0

    tighten_shutdown_deadline(resource, 200.0)
    assert resource._shutdown_deadline == 100.0

    tighten_shutdown_deadline(resource, 50.0)
    assert resource._shutdown_deadline == 50.0

    tighten_shutdown_deadline(resource, None)
    assert resource._shutdown_deadline == 50.0
