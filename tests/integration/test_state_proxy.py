"""Tests for StateProxy functionality.

Tests cover initialization, state management, event handling, HA lifecycle,
shutdown behavior, and thread-safety/concurrency.
"""

import asyncio
from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, Mock, patch

import pytest

from hassette.core.core import Hassette
from hassette.core.state_proxy import StateProxy
from hassette.events import RawStateChangeEvent
from hassette.exceptions import ResourceNotReadyError
from hassette.test_utils import (
    make_full_state_change_event,
    make_light_state_dict,
    make_sensor_state_dict,
    make_switch_state_dict,
    wait_for,
)
from hassette.types import Topic

if TYPE_CHECKING:
    from hassette import Hassette


class TestStateProxyInit:
    proxy: "StateProxy"

    def setup_hassette(self, hassette: "Hassette") -> None:
        """Set up Hassette instance and extract StateProxy.

        Args:
            hassette: The Hassette instance from fixture
        """
        self.hassette = hassette
        self.api = hassette.api
        self.bus = hassette._bus
        self.proxy = hassette._state_proxy

    async def send_state_event(
        self,
        entity_id: str,
        old_state_dict: dict | None,
        new_state_dict: dict | None,
    ) -> None:
        """Helper to send a state change event.

        Args:
            entity_id: Entity ID for the state change
            old_state_dict: Old state dictionary (or None)
            new_state_dict: New state dictionary (or None)
        """
        from hassette.test_utils import make_full_state_change_event
        from hassette.types import Topic

        event = make_full_state_change_event(entity_id, old_state_dict, new_state_dict)
        await self.hassette.send_event(Topic.HASS_EVENT_STATE_CHANGED, event)
        await wait_for(
            lambda: self.hassette._state_proxy.get_state(entity_id) is not None,
            desc=f"{entity_id} state arrived",
        )

    async def test_waits_for_dependencies(self, hassette_with_state_proxy: "Hassette") -> None:
        """State proxy waits for WebSocket, API, and Bus services before initializing."""
        self.setup_hassette(hassette_with_state_proxy)

        # Verify proxy is ready (which means all dependencies were awaited)
        assert self.proxy.is_ready()

    async def test_performs_initial_sync(self, hassette_with_state_proxy: "Hassette") -> None:
        """State proxy performs initial sync during initialization."""
        self.setup_hassette(hassette_with_state_proxy)

        # Proxy should have cached states from the initial sync
        assert isinstance(self.proxy.states, dict)
        # Initially empty since mock returns empty list
        assert len(self.proxy.states) == 0, f"Expected 0 states, got {len(self.proxy.states)} ({self.proxy.states})"

    async def test_marks_ready_after_sync(self, hassette_with_state_proxy: "Hassette") -> None:
        """State proxy marks itself ready after successful initial sync."""
        self.setup_hassette(hassette_with_state_proxy)

        assert self.proxy.is_ready()
        assert len(self.proxy.states) >= 0  # Could be 0 or more depending on mock

    async def test_subscribes_to_events(self, hassette_with_state_proxy: "Hassette") -> None:
        """State proxy subscribes to state_changed and homeassistant_stop events."""
        self.setup_hassette(hassette_with_state_proxy)

        listeners = await self.proxy.bus.get_listeners()
        assert len(listeners) > 0, "Should have listeners after initialization"
        topic_set = {listener.topic for listener in listeners}
        assert Topic.HASS_EVENT_STATE_CHANGED in topic_set, "Should subscribe to state_changed"

    async def test_raises_on_api_failure_during_init(self, hassette_with_state_proxy: "Hassette") -> None:
        """State proxy raises exception if API fails during initial sync."""

        hassette = hassette_with_state_proxy

        with patch.object(hassette.api, "get_states_raw", new_callable=AsyncMock) as mock_get_states:
            mock_get_states.side_effect = Exception("API failure during init")

            proxy = hassette._state_proxy

            with pytest.raises(Exception, match="API failure during init"):
                await proxy.on_initialize()

        await proxy.on_initialize()  # Ensure it can be used in later tests


@pytest.fixture
def state_proxy():
    mock_hassette = Mock()
    mock_hassette.config.state_proxy_log_level = "DEBUG"
    mock_hassette.config.task_bucket_log_level = "DEBUG"
    mock_hassette.config.log_level = "DEBUG"
    mock_hassette.config.bus_service_log_level = "DEBUG"

    proxy = StateProxy.create(mock_hassette, mock_hassette)
    proxy.mark_ready(reason="Test setup")
    return proxy


class TestStateProxyGetState:
    """Tests for get_state method."""

    async def test_returns_state_when_ready_and_exists(self, state_proxy: "StateProxy") -> None:
        """get_state returns state when proxy is ready and entity exists."""

        # Add a state to the cache manually
        light_dict = make_light_state_dict("light.test", "on", brightness=200)
        state_proxy.states["light.test"] = light_dict

        # Retrieve it
        result = state_proxy.get_state("light.test")
        assert result is not None
        assert result["entity_id"] == "light.test"
        assert isinstance(result, dict)

    async def test_returns_none_for_missing_entity(self, state_proxy: "StateProxy") -> None:
        """get_state returns None when entity does not exist in cache."""
        result = state_proxy.get_state("light.nonexistent")
        assert result is None

    async def test_raises_when_not_ready(self, state_proxy: "StateProxy") -> None:
        """get_state raises ResourceNotReadyError when proxy is not ready."""

        # Mark proxy as not ready
        state_proxy.mark_not_ready(reason="Test")

        with pytest.raises(ResourceNotReadyError, match="StateProxy is not ready"):
            state_proxy._get_state_once("light.test")
        state_proxy.mark_ready(reason="Test complete")  # Restore ready state for other tests

    async def test_lockfree_read_access(self, state_proxy: "StateProxy") -> None:
        """get_state does not acquire lock (lock-free read)."""

        # Add state
        light_dict = make_light_state_dict("light.test", "on")
        state_proxy.states["light.test"] = light_dict

        # Lock should not be acquired during read
        # We can't directly test that lock is not acquired, but we can verify
        # that multiple reads can happen simultaneously without blocking
        results = await asyncio.gather(
            *[asyncio.create_task(asyncio.to_thread(lambda: state_proxy.get_state("light.test"))) for _ in range(10)]
        )

        assert all(r is not None for r in results)


class TestStateProxyStateChanged:
    """Tests for on_state_changed handler."""

    async def test_adds_new_entity(self, hassette_with_state_proxy: "Hassette") -> None:
        """on_state_changed adds new entity when old_state is None."""
        hassette = hassette_with_state_proxy
        proxy = hassette._state_proxy

        # Create and send a state change event for a new entity
        light_dict = make_light_state_dict("light.new_light", "on", brightness=100)
        event = make_full_state_change_event("light.new_light", None, light_dict)

        await hassette.send_event(Topic.HASS_EVENT_STATE_CHANGED, event)
        await wait_for(
            lambda: "light.new_light" in proxy.states,
            desc="light.new_light state arrived",
        )

        # Verify entity was added
        assert "light.new_light" in proxy.states
        state = proxy.states["light.new_light"]
        assert isinstance(state, dict)
        assert state["entity_id"] == "light.new_light"

    async def test_updates_existing_entity(self, hassette_with_state_proxy: "Hassette") -> None:
        """on_state_changed updates entity when both states present."""
        proxy = hassette_with_state_proxy._state_proxy

        wait_for = asyncio.Event()

        proxy.bus.on_state_change(entity_id="light.*", handler=lambda: wait_for.set(), changed=False)

        # Add initial state
        old_dict = make_light_state_dict("light.test", "on", brightness=100)
        proxy.states["light.test"] = old_dict

        # make and send update event
        event = make_full_state_change_event(
            "light.test",
            old_dict,
            make_light_state_dict("light.test", "on", brightness=200),
        )

        await hassette_with_state_proxy.send_event(Topic.HASS_EVENT_STATE_CHANGED, event)
        await asyncio.wait_for(wait_for.wait(), timeout=1.0)

        # Verify entity was updated
        state = proxy.states["light.test"]
        assert state["attributes"]["brightness"] == 200

    async def test_removes_entity_when_new_state_none(self, hassette_with_state_proxy: "Hassette") -> None:
        """on_state_changed removes entity when new_state is None."""
        hassette = hassette_with_state_proxy
        proxy = hassette._state_proxy

        wait_for = asyncio.Event()

        proxy.bus.on_state_change(entity_id="light.*", handler=lambda: wait_for.set(), changed=False)

        # Add initial state
        old_dict = make_light_state_dict("light.test", "on")
        proxy.states["light.test"] = old_dict
        assert "light.test" in proxy.states

        # Send removal event (new_state=None)
        event = make_full_state_change_event("light.test", old_dict, None)

        await hassette.send_event(Topic.HASS_EVENT_STATE_CHANGED, event)
        await asyncio.wait_for(wait_for.wait(), timeout=1.0)

        # Verify entity was removed
        assert "light.test" not in proxy.states

    async def test_handles_multiple_domain_types(self, hassette_with_state_proxy: "Hassette") -> None:
        """on_state_changed stores all entities as BaseState"""
        hassette = hassette_with_state_proxy
        proxy = hassette._state_proxy

        wait_for = asyncio.Event()

        proxy.bus.on_state_change(entity_id="*", handler=lambda: wait_for.set(), changed=False, debounce=0.1)

        # Add entities of different types
        light_dict = make_light_state_dict("light.test", "on")
        sensor_dict = make_sensor_state_dict("sensor.temperature", "22.5")
        switch_dict = make_switch_state_dict("switch.test", "off")

        for entity_id, state_dict in [
            ("light.test", light_dict),
            ("sensor.temperature", sensor_dict),
            ("switch.test", switch_dict),
        ]:
            event = make_full_state_change_event(entity_id, None, state_dict)
            await hassette.send_event(Topic.HASS_EVENT_STATE_CHANGED, event)

        await asyncio.wait_for(wait_for.wait(), timeout=1.0)

        # Verify all were added with correct types
        assert isinstance(proxy.states["light.test"], dict)
        assert isinstance(proxy.states["sensor.temperature"], dict)
        assert isinstance(proxy.states["switch.test"], dict)

    async def test_concurrent_state_changes_are_serialized(self, hassette_with_state_proxy: "Hassette") -> None:
        """Multiple state_changed events are processed serially due to lock."""
        hassette = hassette_with_state_proxy
        proxy = hassette._state_proxy

        wait_for = asyncio.Event()

        # debounce to avoid firing until all events sent
        proxy.bus.on_state_change(entity_id="light.*", handler=lambda: wait_for.set(), changed=False, debounce=0.1)

        # Send multiple events rapidly
        events = []
        for i in range(10):
            light_dict = make_light_state_dict(f"light.test_{i}", "on", brightness=i * 10)
            event = make_full_state_change_event(f"light.test_{i}", None, light_dict)
            events.append((Topic.HASS_EVENT_STATE_CHANGED, event))

        # Send all events
        await asyncio.gather(*[hassette.send_event(topic, event) for topic, event in events])
        await asyncio.wait_for(wait_for.wait(), timeout=1.0)

        # All should be processed correctly
        for i in range(10):
            assert f"light.test_{i}" in proxy.states


class TestStateProxyWebsocketListeners:
    """Tests for websocket events that trigger clear/sync states."""

    async def test_clears_cache_on_stop(self, state_proxy: "StateProxy") -> None:
        """on_disconnect clears the state cache."""

        # Add some states
        state_proxy.states["light.test"] = make_light_state_dict("light.test", "on")
        state_proxy.states["sensor.test"] = make_sensor_state_dict("sensor.test", "20")
        assert len(state_proxy.states) >= 2

        # Trigger HA stop
        with patch.object(state_proxy, "mark_not_ready") as mock_mark_not_ready:
            await state_proxy.on_disconnect()

        # Cache should be cleared
        assert len(state_proxy.states) == 0
        mock_mark_not_ready.assert_called_once()

    async def test_marks_not_ready_on_stop(self, state_proxy: "StateProxy") -> None:
        """on_disconnect marks proxy as not ready."""

        orig_state = state_proxy.is_ready()

        if not orig_state:
            state_proxy.mark_ready(reason="Test setup")

        with patch.object(state_proxy, "mark_not_ready") as mock_mark_not_ready:
            await state_proxy.on_disconnect()

        mock_mark_not_ready.assert_called_once()

        if orig_state:
            state_proxy.mark_ready(reason="Test complete")  # Restore ready state for other tests

    async def test_subscribes_to_start_on_stop(self, hassette_with_state_proxy: "Hassette") -> None:
        """on_disconnect clears cache but does not add new subscriptions (they're already registered)."""

        proxy = hassette_with_state_proxy._state_proxy

        listeners = await proxy.bus.get_listeners()

        initial_subscription_count = len(listeners)
        expected_sub_count = initial_subscription_count - 1  # because state_change_listener removes itself

        with patch.object(proxy, "mark_not_ready") as mock_mark_not_ready:
            await proxy.on_disconnect()

        mock_mark_not_ready.assert_called_once()

        # Subscriptions should remain the same (all registered in on_initialize)
        listeners_after = await proxy.bus.get_listeners()
        assert len(listeners_after) == expected_sub_count

    async def test_resyncs_on_start(self, state_proxy: "StateProxy") -> None:
        """on_reconnect performs full state resync."""
        # Clear cache and mark not ready (simulating HA stop)
        state_proxy.states.clear()
        state_proxy.mark_not_ready(reason="HA stopped")

        # Configure mock API response for resync
        mock_states = [
            make_light_state_dict("light.kitchen", "on"),
            make_sensor_state_dict("sensor.temp", "21.0"),
        ]
        # okay to set this one directly since it's on the "state_proxy" fixture, which isn't shared
        state_proxy.hassette.api.get_states_raw = AsyncMock(return_value=[mock_states[0], mock_states[1]])

        # Trigger HA start
        await state_proxy.on_reconnect()
        await wait_for(
            lambda: state_proxy.is_ready() and len(state_proxy.states) >= 2,
            desc="state proxy resynced",
        )

        # States should be resynced
        assert state_proxy.is_ready()
        assert len(state_proxy.states) >= 2

    async def test_handles_resync_failure(self, hassette_with_state_proxy: "Hassette") -> None:
        """on_reconnect handles API failure gracefully."""
        proxy = hassette_with_state_proxy._state_proxy

        with patch.object(hassette_with_state_proxy.api, "get_states_raw", new_callable=AsyncMock) as mock_get_states:
            mock_get_states.side_effect = Exception("API error during resync")
            # Clear cache
            proxy.states.clear()
            proxy.mark_not_ready(reason="HA stopped")

            # Trigger HA start - should not crash
            await proxy.on_reconnect()

            # Should remain not ready
            assert not proxy.is_ready()

        await proxy.on_initialize()  # Ensure it can be used in later tests


class TestStateProxyShutdown:
    """Tests for shutdown behavior."""

    async def test_removes_all_listeners(self, hassette_with_state_proxy: "Hassette") -> None:
        """Shutdown removes all bus listeners."""
        proxy = hassette_with_state_proxy._state_proxy

        listeners = await proxy.bus.get_listeners()
        assert len(listeners) > 0, "Should have listeners before shutdown"

        with patch.object(proxy, "mark_not_ready"):
            await proxy.on_shutdown()

        # All subscriptions should be removed
        listeners_after = await proxy.bus.get_listeners()
        assert len(listeners_after) == 0, "All listeners should be removed on shutdown"

    async def test_clears_cache_on_shutdown(self, state_proxy: "StateProxy") -> None:
        """Shutdown clears the state cache."""

        # Add states
        state_proxy.states["light.test"] = make_light_state_dict("light.test", "on")

        await state_proxy.on_shutdown()

        assert len(state_proxy.states) == 0

    async def test_marks_not_ready_on_shutdown(self, state_proxy: "StateProxy") -> None:
        """Shutdown marks proxy as not ready."""

        orig_state = state_proxy.is_ready()
        if not orig_state:
            state_proxy.mark_ready(reason="Test setup")

        with patch.object(state_proxy, "mark_not_ready") as mock_mark_not_ready:
            await state_proxy.on_shutdown()

        mock_mark_not_ready.assert_called_once()

        if orig_state:
            state_proxy.mark_ready(reason="Test complete")  # Restore ready state for other tests


class TestStateProxyConcurrency:
    """Tests for thread-safety and concurrency."""

    async def test_concurrent_reads_dont_block(self, state_proxy: "StateProxy") -> None:
        """Multiple concurrent reads should not block each other."""
        # Add test state
        state_proxy.states["light.test"] = make_light_state_dict("light.test", "on")

        # Perform many concurrent reads
        async def read_state():
            return state_proxy.get_state("light.test")

        results = await asyncio.gather(*[read_state() for _ in range(100)])

        # All should succeed
        assert all(r is not None for r in results)
        assert all(r["entity_id"] == "light.test" for r in results)

    async def test_writes_are_serialized(self, hassette_with_state_proxy: "Hassette") -> None:
        """Write operations acquire lock and are serialized."""
        hassette = hassette_with_state_proxy
        proxy = hassette._state_proxy
        max_brightness = 0

        # def handler(new_brightness: D.AttrNew("brightness")):
        def handler(event: RawStateChangeEvent):
            new_brightness = event.payload.data.new_state["attributes"]["brightness"]
            if new_brightness == max_brightness:
                wait_for.set()

        wait_for = asyncio.Event()
        proxy.bus.on_state_change(entity_id="light.*", handler=handler, changed=False)
        # Send many concurrent state change events
        events = []
        for i in range(20):
            if i > max_brightness:
                max_brightness = i
            light_dict = make_light_state_dict("light.test", "on", brightness=i)
            event = make_full_state_change_event("light.test", light_dict, light_dict)
            events.append((Topic.HASS_EVENT_STATE_CHANGED, event))

        await asyncio.gather(*[hassette.send_event(topic, event) for topic, event in events])
        await asyncio.wait_for(wait_for.wait(), timeout=1.0)

        # Final state should be consistent (last update wins)
        state = proxy.states.get("light.test")
        assert state is not None
        assert isinstance(state, dict)
        assert state["attributes"]["brightness"] == max_brightness

    async def test_read_during_write_sees_consistent_state(self, hassette_with_state_proxy: "Hassette") -> None:
        """Reads during writes see a consistent state snapshot."""
        hassette = hassette_with_state_proxy
        proxy = hassette._state_proxy

        # Add initial state
        proxy.states["light.test"] = make_light_state_dict("light.test", "on", brightness=100)

        # Start continuous reads
        read_results = []

        async def continuous_read():
            for _ in range(50):
                state = proxy.get_state("light.test")
                if state:
                    read_results.append(state["attributes"]["brightness"])
                await asyncio.sleep(0.001)

        # Start continuous writes
        async def continuous_write():
            for i in range(10):
                light_dict = make_light_state_dict("light.test", "on", brightness=100 + i * 10)
                event = make_full_state_change_event("light.test", None, light_dict)
                await hassette.send_event(Topic.HASS_EVENT_STATE_CHANGED, event)
                await asyncio.sleep(0.01)

        # Run reads and writes concurrently
        await asyncio.gather(continuous_read(), continuous_write())

        # All reads should return valid brightness values
        assert all(isinstance(b, (int, float)) for b in read_results)
        assert len(read_results) > 0
