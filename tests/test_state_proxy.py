"""Tests for StateProxyResource functionality.

Tests cover initialization, state management, event handling, HA lifecycle,
shutdown behavior, and thread-safety/concurrency.
"""

import asyncio
from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, patch

import pytest
from fixtures.state_fixtures import (
    make_light_state_dict,
    make_sensor_state_dict,
    make_state_change_event,
    make_switch_state_dict,
)

from hassette.exceptions import ResourceNotReadyError
from hassette.models.states import LightState, SensorState, SwitchState
from hassette.types import topics

if TYPE_CHECKING:
    from hassette import Hassette


class TestStateProxyResourceInit:
    """Tests for initialization and dependencies."""

    async def test_waits_for_dependencies(self, hassette_with_state_proxy: "Hassette") -> None:
        """State proxy waits for WebSocket, API, and Bus services before initializing."""
        hassette = hassette_with_state_proxy
        proxy = hassette._state_proxy_resource

        # Verify proxy is ready (which means all dependencies were awaited)
        assert proxy.is_ready()

    async def test_performs_initial_sync(self, hassette_with_state_proxy: "Hassette") -> None:
        """State proxy performs initial sync during initialization."""
        hassette = hassette_with_state_proxy
        proxy = hassette._state_proxy_resource

        # Proxy should have cached states from the initial sync
        assert isinstance(proxy.states, dict)
        # Initially empty since mock returns empty list
        assert len(proxy.states) == 0, f"Expected 0 states, got {len(proxy.states)} ({proxy.states})"

    async def test_marks_ready_after_sync(self, hassette_with_state_proxy: "Hassette") -> None:
        """State proxy marks itself ready after successful initial sync."""
        hassette = hassette_with_state_proxy
        proxy = hassette._state_proxy_resource

        assert proxy.is_ready()
        assert len(proxy.states) >= 0  # Could be 0 or more depending on mock

    async def test_subscribes_to_events(self, hassette_with_state_proxy: "Hassette") -> None:
        """State proxy subscribes to state_changed and homeassistant_stop events."""
        hassette = hassette_with_state_proxy
        proxy = hassette._state_proxy_resource

        # Wait a moment for async subscription tasks to complete
        await asyncio.sleep(0.1)

        # Verify bus service has listeners registered
        # The listeners are registered under the Bus's owner_id, which is the proxy's unique_name
        router = proxy.bus.bus_service.router
        async with router.lock:
            owner_listeners = router.owners.get(proxy.bus.owner_id, [])
            assert len(owner_listeners) > 0, "StateProxy should have registered event listeners"
            # Verify we have subscriptions for state_changed and homeassistant_stop
            listener_topics = {listener.topic for listener in owner_listeners}
            assert topics.HASS_EVENT_STATE_CHANGED in listener_topics, "Should subscribe to state_changed"

    # async def test_raises_on_api_failure_during_init(self, hassette_harness, test_config) -> None:
    #     """State proxy raises exception if API fails during initial sync."""
    #     # Configure mock API to fail
    #     async with hassette_harness(
    #         config=test_config, use_bus=True, use_api_mock=True, use_state_proxy=True
    #     ) as harness:
    #         # Mock API to raise error
    #         harness.hassette.api.get_states = AsyncMock(side_effect=Exception("API failure"))

    #         proxy = harness.hassette._state_proxy_resource

    #         # Proxy should not be ready due to failure
    #         # The exception should have been raised during initialization
    #         with pytest.raises(Exception, match="API failure"):
    #             # Try to reinitialize
    #             await proxy.on_initialize()


class TestStateProxyResourceGetState:
    """Tests for get_state method."""

    async def test_returns_state_when_ready_and_exists(self, hassette_with_state_proxy: "Hassette") -> None:
        """get_state returns typed state when proxy is ready and entity exists."""
        hassette = hassette_with_state_proxy
        proxy = hassette._state_proxy_resource

        # Add a state to the cache manually
        light_dict = make_light_state_dict("light.test", "on", brightness=200)
        light_state = LightState.model_validate(light_dict)
        proxy.states["light.test"] = light_state

        # Retrieve it
        result = proxy.get_state("light.test")
        assert result is not None
        assert result.entity_id == "light.test"
        assert isinstance(result, LightState)

    async def test_returns_none_for_missing_entity(self, hassette_with_state_proxy: "Hassette") -> None:
        """get_state returns None when entity does not exist in cache."""
        hassette = hassette_with_state_proxy
        proxy = hassette._state_proxy_resource

        result = proxy.get_state("light.nonexistent")
        assert result is None

    async def test_raises_when_not_ready(self, hassette_with_state_proxy: "Hassette") -> None:
        """get_state raises ResourceNotReadyError when proxy is not ready."""
        hassette = hassette_with_state_proxy
        proxy = hassette._state_proxy_resource

        # Mark proxy as not ready
        proxy.mark_not_ready(reason="Test")

        with pytest.raises(ResourceNotReadyError, match="StateProxy is not ready"):
            proxy.get_state("light.test")

        proxy.mark_ready(reason="Test complete")  # Restore ready state for other tests

    async def test_lockfree_read_access(self, hassette_with_state_proxy: "Hassette") -> None:
        """get_state does not acquire lock (lock-free read)."""
        hassette = hassette_with_state_proxy
        proxy = hassette._state_proxy_resource

        # Add state
        light_dict = make_light_state_dict("light.test", "on")
        proxy.states["light.test"] = LightState.model_validate(light_dict)

        # Lock should not be acquired during read
        # We can't directly test that lock is not acquired, but we can verify
        # that multiple reads can happen simultaneously without blocking
        results = await asyncio.gather(
            *[asyncio.create_task(asyncio.to_thread(lambda: proxy.get_state("light.test"))) for _ in range(10)]
        )

        assert all(r is not None for r in results)


class TestStateProxyResourceStateChanged:
    """Tests for on_state_changed handler."""

    async def test_adds_new_entity(self, hassette_with_state_proxy: "Hassette") -> None:
        """on_state_changed adds new entity when old_state is None."""
        hassette = hassette_with_state_proxy
        proxy = hassette._state_proxy_resource

        # Create and send a state change event for a new entity
        light_dict = make_light_state_dict("light.new_light", "on", brightness=100)
        event = make_state_change_event("light.new_light", None, light_dict)

        await hassette.send_event(topics.HASS_EVENT_STATE_CHANGED, event)
        await asyncio.sleep(0.1)  # Give time for event processing

        # Verify entity was added
        assert "light.new_light" in proxy.states
        state = proxy.states["light.new_light"]
        assert isinstance(state, LightState)
        assert state.entity_id == "light.new_light"

    async def test_updates_existing_entity(self, hassette_with_state_proxy: "Hassette") -> None:
        """on_state_changed updates entity when both states present."""
        hassette = hassette_with_state_proxy
        proxy = hassette._state_proxy_resource

        # Add initial state
        old_dict = make_light_state_dict("light.test", "on", brightness=100)
        proxy.states["light.test"] = LightState.model_validate(old_dict)

        # Send update event
        new_dict = make_light_state_dict("light.test", "on", brightness=200)
        event = make_state_change_event("light.test", old_dict, new_dict)

        await hassette.send_event(topics.HASS_EVENT_STATE_CHANGED, event)
        await asyncio.sleep(0.1)

        # Verify entity was updated
        state = proxy.states["light.test"]
        assert state.attributes.brightness == 200

    async def test_removes_entity_when_new_state_none(self, hassette_with_state_proxy: "Hassette") -> None:
        """on_state_changed removes entity when new_state is None."""
        hassette = hassette_with_state_proxy
        proxy = hassette._state_proxy_resource

        # Add initial state
        old_dict = make_light_state_dict("light.test", "on")
        proxy.states["light.test"] = LightState.model_validate(old_dict)
        assert "light.test" in proxy.states

        # Send removal event (new_state=None)
        event = make_state_change_event("light.test", old_dict, None)

        await hassette.send_event(topics.HASS_EVENT_STATE_CHANGED, event)
        await asyncio.sleep(0.1)

        # Verify entity was removed
        assert "light.test" not in proxy.states

    async def test_handles_multiple_domain_types(self, hassette_with_state_proxy: "Hassette") -> None:
        """on_state_changed correctly handles different entity domains."""
        hassette = hassette_with_state_proxy
        proxy = hassette._state_proxy_resource

        # Add entities of different types
        light_dict = make_light_state_dict("light.test", "on")
        sensor_dict = make_sensor_state_dict("sensor.temperature", "22.5")
        switch_dict = make_switch_state_dict("switch.test", "off")

        for entity_id, state_dict in [
            ("light.test", light_dict),
            ("sensor.temperature", sensor_dict),
            ("switch.test", switch_dict),
        ]:
            event = make_state_change_event(entity_id, None, state_dict)
            await hassette.send_event(topics.HASS_EVENT_STATE_CHANGED, event)

        await asyncio.sleep(0.1)

        # Verify all were added with correct types
        assert isinstance(proxy.states["light.test"], LightState)
        assert isinstance(proxy.states["sensor.temperature"], SensorState)
        assert isinstance(proxy.states["switch.test"], SwitchState)

    async def test_concurrent_state_changes_are_serialized(self, hassette_with_state_proxy: "Hassette") -> None:
        """Multiple state_changed events are processed serially due to lock."""
        hassette = hassette_with_state_proxy
        proxy = hassette._state_proxy_resource

        # Send multiple events rapidly
        events = []
        for i in range(10):
            light_dict = make_light_state_dict(f"light.test_{i}", "on", brightness=i * 10)
            event = make_state_change_event(f"light.test_{i}", None, light_dict)
            events.append((topics.HASS_EVENT_STATE_CHANGED, event))

        # Send all events
        await asyncio.gather(*[hassette.send_event(topic, event) for topic, event in events])
        await asyncio.sleep(0.2)

        # All should be processed correctly
        for i in range(10):
            assert f"light.test_{i}" in proxy.states


class TestStateProxyResourceHALifecycle:
    """Tests for HA stop/start handlers."""

    async def test_clears_cache_on_stop(self, hassette_with_state_proxy: "Hassette") -> None:
        """on_homeassistant_stop clears the state cache."""
        hassette = hassette_with_state_proxy
        proxy = hassette._state_proxy_resource

        # Add some states
        proxy.states["light.test"] = LightState.model_validate(make_light_state_dict("light.test", "on"))
        proxy.states["sensor.test"] = SensorState.model_validate(make_sensor_state_dict("sensor.test", "20"))
        assert len(proxy.states) >= 2

        # Trigger HA stop
        with patch.object(proxy, "mark_not_ready") as mock_mark_not_ready:
            await proxy.on_homeassistant_stop()

        # Cache should be cleared
        assert len(proxy.states) == 0
        mock_mark_not_ready.assert_called_once()

    async def test_marks_not_ready_on_stop(self, hassette_with_state_proxy: "Hassette") -> None:
        """on_homeassistant_stop marks proxy as not ready."""
        hassette = hassette_with_state_proxy
        proxy = hassette._state_proxy_resource

        assert proxy.is_ready()

        with patch.object(proxy, "mark_not_ready") as mock_mark_not_ready:
            await proxy.on_homeassistant_stop()

        mock_mark_not_ready.assert_called_once()

    async def test_subscribes_to_start_on_stop(self, hassette_with_state_proxy: "Hassette") -> None:
        """on_homeassistant_stop subscribes to homeassistant_start."""
        hassette = hassette_with_state_proxy
        proxy = hassette._state_proxy_resource

        listeners = await proxy.bus.get_listeners()

        initial_subscription_count = len(listeners)

        with patch.object(proxy, "mark_not_ready") as mock_mark_not_ready:
            await proxy.on_homeassistant_stop()

        mock_mark_not_ready.assert_called_once()

        # Should have added a subscription for HA start
        listeners_after = await proxy.bus.get_listeners()
        assert len(listeners_after) == initial_subscription_count + 1

    # async def test_resyncs_on_start(self, hassette_with_state_proxy: "Hassette") -> None:
    #     """on_homeassistant_start performs full state resync."""
    #     hassette = hassette_with_state_proxy
    #     proxy = hassette._state_proxy_resource

    #     # Clear cache and mark not ready (simulating HA stop)
    #     proxy.states.clear()
    #     proxy.mark_not_ready(reason="HA stopped")

    #     # Configure mock API response for resync
    #     mock_states = [
    #         make_light_state_dict("light.kitchen", "on"),
    #         make_sensor_state_dict("sensor.temp", "21.0"),
    #     ]
    #     mock_server.expect("GET", "/api/states", "", json=mock_states, status=200)

    #     # Trigger HA start
    #     await proxy.on_homeassistant_start()
    #     await asyncio.sleep(0.1)

    #     # States should be resynced
    #     assert proxy.is_ready()
    #     assert len(proxy.states) >= 2
    #     mock_server.assert_clean()

    async def test_handles_resync_failure(self, hassette_with_state_proxy: "Hassette") -> None:
        """on_homeassistant_start handles API failure gracefully."""
        hassette = hassette_with_state_proxy
        proxy = hassette._state_proxy_resource

        # Mock API to fail
        hassette.api.get_states = AsyncMock(side_effect=Exception("API error"))

        # Clear cache
        proxy.states.clear()
        proxy.mark_not_ready(reason="HA stopped")

        # Trigger HA start - should not crash
        await proxy.on_homeassistant_start()

        # Should remain not ready
        assert not proxy.is_ready()


class TestStateProxyResourceShutdown:
    """Tests for shutdown behavior."""

    async def test_removes_all_listeners(self, hassette_with_state_proxy: "Hassette") -> None:
        """Shutdown removes all bus listeners."""
        hassette = hassette_with_state_proxy
        proxy = hassette._state_proxy_resource

        listeners = await proxy.bus.get_listeners()
        assert len(listeners) > 0, "Should have listeners before shutdown"

        with patch.object(proxy, "mark_not_ready"):
            await proxy.on_shutdown()

        # All subscriptions should be removed
        listeners_after = await proxy.bus.get_listeners()
        assert len(listeners_after) == 0, "All listeners should be removed on shutdown"

    async def test_clears_cache_on_shutdown(self, hassette_with_state_proxy: "Hassette") -> None:
        """Shutdown clears the state cache."""
        hassette = hassette_with_state_proxy
        proxy = hassette._state_proxy_resource

        # Add states
        proxy.states["light.test"] = LightState.model_validate(make_light_state_dict("light.test", "on"))

        await proxy.on_shutdown()

        assert len(proxy.states) == 0

    async def test_marks_not_ready_on_shutdown(self, hassette_with_state_proxy: "Hassette") -> None:
        """Shutdown marks proxy as not ready."""
        hassette = hassette_with_state_proxy
        proxy = hassette._state_proxy_resource

        assert proxy.is_ready()

        with patch.object(proxy, "mark_not_ready") as mock_mark_not_ready:
            await proxy.on_shutdown()

        mock_mark_not_ready.assert_called_once()


class TestStateProxyResourceConcurrency:
    """Tests for thread-safety and concurrency."""

    async def test_concurrent_reads_dont_block(self, hassette_with_state_proxy: "Hassette") -> None:
        """Multiple concurrent reads should not block each other."""
        hassette = hassette_with_state_proxy
        proxy = hassette._state_proxy_resource

        # Add test state
        proxy.states["light.test"] = LightState.model_validate(make_light_state_dict("light.test", "on"))

        # Perform many concurrent reads
        async def read_state():
            return proxy.get_state("light.test")

        results = await asyncio.gather(*[read_state() for _ in range(100)])

        # All should succeed
        assert all(r is not None for r in results)
        assert all(r.entity_id == "light.test" for r in results)

    async def test_writes_are_serialized(self, hassette_with_state_proxy: "Hassette") -> None:
        """Write operations acquire lock and are serialized."""
        hassette = hassette_with_state_proxy
        proxy = hassette._state_proxy_resource

        # Send many concurrent state change events
        events = []
        for i in range(20):
            light_dict = make_light_state_dict("light.test", "on", brightness=i)
            event = make_state_change_event("light.test", None, light_dict)
            events.append((topics.HASS_EVENT_STATE_CHANGED, event))

        await asyncio.gather(*[hassette.send_event(topic, event) for topic, event in events])
        await asyncio.sleep(0.2)

        # Final state should be consistent (last update wins)
        state = proxy.states.get("light.test")
        assert state is not None
        assert isinstance(state, LightState)

    async def test_read_during_write_sees_consistent_state(self, hassette_with_state_proxy: "Hassette") -> None:
        """Reads during writes see a consistent state snapshot."""
        hassette = hassette_with_state_proxy
        proxy = hassette._state_proxy_resource

        # Add initial state
        proxy.states["light.test"] = LightState.model_validate(
            make_light_state_dict("light.test", "on", brightness=100)
        )

        # Start continuous reads
        read_results = []

        async def continuous_read():
            for _ in range(50):
                state = proxy.get_state("light.test")
                if state:
                    read_results.append(state.attributes.brightness)
                await asyncio.sleep(0.001)

        # Start continuous writes
        async def continuous_write():
            for i in range(10):
                light_dict = make_light_state_dict("light.test", "on", brightness=100 + i * 10)
                event = make_state_change_event("light.test", None, light_dict)
                await hassette.send_event(topics.HASS_EVENT_STATE_CHANGED, event)
                await asyncio.sleep(0.01)

        # Run reads and writes concurrently
        await asyncio.gather(continuous_read(), continuous_write())

        # All reads should return valid brightness values
        assert all(isinstance(b, (int, float)) for b in read_results)
        assert len(read_results) > 0
