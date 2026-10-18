"""Registration-time WARNING for literal entity IDs that match no cached entity (#2891)."""

import typing
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from hassette.bus.listeners import Subscription
from tests.support.factories import make_mock_parent

from .conftest import mock_add_listener

if typing.TYPE_CHECKING:
    from hassette.bus.bus import Bus

KNOWN_ENTITY = "binary_sensor.motion_backyard"
TYPO_ENTITY = "binary_sensor.motion_backyrd"


async def handler(event) -> None:
    pass


def stub_state_proxy(states: dict[str, typing.Any]) -> SimpleNamespace:
    return SimpleNamespace(states=states, has_cache_entries=bool(states))


async def register(bus: "Bus", method: str, entity_id: str) -> Subscription:
    if method == "on_state_change":
        return await bus.on_state_change(entity_id, handler=handler, name="door_when_empty")
    return await bus.on_attribute_change(entity_id, "battery", handler=handler, name="door_when_empty")


@pytest.fixture
def warning_logger(bus: "Bus") -> typing.Iterator[MagicMock]:
    with patch.object(bus, "logger") as logger:
        yield logger


def use_cache(bus: "Bus", states: dict[str, typing.Any]) -> None:
    bus.hassette.try_state_proxy = lambda: stub_state_proxy(states)  # pyright: ignore[reportAttributeAccessIssue]


@pytest.mark.parametrize("method", ["on_state_change", "on_attribute_change"])
async def test_unknown_literal_entity_warns_once_with_suggestion(
    bus: "Bus", warning_logger: MagicMock, method: str
) -> None:
    use_cache(bus, {KNOWN_ENTITY: {}, "light.kitchen": {}})

    with mock_add_listener(bus):
        sub = await register(bus, method, TYPO_ENTITY)

    assert isinstance(sub, Subscription)
    assert warning_logger.warning.call_count == 1
    args, kwargs = warning_logger.warning.call_args
    rendered = args[0] % args[1:]
    assert TYPO_ENTITY in rendered
    assert f"did you mean {KNOWN_ENTITY!r}" in rendered
    assert "door_when_empty" in rendered
    assert kwargs["extra"] == {"app": "test_app", "listener": "door_when_empty", "entity_id": TYPO_ENTITY}


async def test_unknown_entity_without_close_match_omits_suggestion(bus: "Bus", warning_logger: MagicMock) -> None:
    use_cache(bus, {"light.kitchen": {}})

    with mock_add_listener(bus):
        await register(bus, "on_state_change", "switch.zzz_unrelated_thing")

    args, _ = warning_logger.warning.call_args
    assert "did you mean" not in args[0] % args[1:]


@pytest.mark.parametrize(
    ("entity_id", "states", "source_tier"),
    [
        pytest.param(KNOWN_ENTITY, {KNOWN_ENTITY: {}}, "app", id="known-entity"),
        pytest.param("binary_sensor.motion_*", {KNOWN_ENTITY: {}}, "app", id="glob"),
        pytest.param(TYPO_ENTITY, {}, "app", id="empty-cache"),
        pytest.param(TYPO_ENTITY, {KNOWN_ENTITY: {}}, "framework", id="framework-owner"),
    ],
)
async def test_no_warning(
    bus: "Bus", warning_logger: MagicMock, entity_id: str, states: dict[str, typing.Any], source_tier: str
) -> None:
    bus.parent = make_mock_parent(app_key="test_app", index=0, source_tier=source_tier)  # pyright: ignore[reportArgumentType]
    use_cache(bus, states)

    with mock_add_listener(bus):
        await register(bus, "on_state_change", entity_id)

    warning_logger.warning.assert_not_called()


async def test_no_warning_when_state_proxy_not_wired(bus: "Bus", warning_logger: MagicMock) -> None:
    bus.hassette.try_state_proxy = lambda: None  # pyright: ignore[reportAttributeAccessIssue]

    with mock_add_listener(bus):
        await register(bus, "on_state_change", TYPO_ENTITY)

    warning_logger.warning.assert_not_called()
