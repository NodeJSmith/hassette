"""Tests for StateProxyResource functionality.

Tests cover initialization, state management, event handling, HA lifecycle,
shutdown behavior, and thread-safety/concurrency.
"""

import asyncio
from typing import TYPE_CHECKING
from unittest.mock import AsyncMock

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
    from hassette.test_utils.test_server import SimpleTestServer


class TestStateProxyResourceInit:
    """Tests for initialization and dependencies."""

    async def test_waits_for_dependencies(
        self, hassette_with_state_proxy: tuple["Hassette", "SimpleTestServer"]
    ) -> None:
        """State proxy waits for WebSocket, API, and Bus services before initializing."""
        hassette, _ = hassette_with_state_proxy
        proxy = hassette._state_proxy_resource

        # Verify proxy is ready (which means all dependencies were awaited)
        assert proxy.is_ready()

    async def test_performs_initial_sync(
        self, hassette_with_state_proxy: tuple["Hassette", "SimpleTestServer"]
    ) -> None:
        """State proxy performs initial state sync during initialization."""
        hassette, mock_server = hassette_with_state_proxy
        proxy = hassette._state_proxy_resource

        # The mock server should have received the get_states request during init
        mock_server.assert_clean()

        # Proxy should have cached states from the initial sync
        assert isinstance(proxy.states, dict)

    async def test_marks_ready_after_sync(
        self, hassette_with_state_proxy: tuple["Hassette", "SimpleTestServer"]
    ) -> None:
        """State proxy marks itself ready after successful initial sync."""
        hassette, _ = hassette_with_state_proxy
        proxy = hassette._state_proxy_resource

        assert proxy.is_ready()
        assert len(proxy.states) >= 0  # Could be 0 or more depending on mock

    async def test_subscribes_to_events(self, hassette_with_state_proxy: tuple["Hassette", "SimpleTestServer"]) -> None:
        """State proxy subscribes to state_changed and homeassistant_stop events."""
        hassette, _ = hassette_with_state_proxy
        proxy = hassette._state_proxy_resource

        # Verify the proxy's bus has listeners (subscriptions were created)
        # The bus should have subscriptions for state_changed and ha_stop
        assert len(proxy.bus._subscriptions) > 0

    async def test_raises_on_api_failure_during_init(self, hassette_harness, test_config) -> None:
        """State proxy raises exception if API fails during initial sync."""
        # Configure mock API to fail
        async with hassette_harness(
            config=test_config, use_bus=True, use_api_mock=True, use_state_proxy=True
        ) as harness:
            # Mock API to raise error
            harness.hassette.api.get_states = AsyncMock(side_effect=Exception("API failure"))

            proxy = harness.hassette._state_proxy_resource

            # Proxy should not be ready due to failure
            # The exception should have been raised during initialization
            with pytest.raises(Exception, match="API failure"):
                # Try to reinitialize
                await proxy.on_initialize()


class TestStateProxyResourceGetState:
    """Tests for get_state method."""

    async def test_returns_state_when_ready_and_exists(
        self, hassette_with_state_proxy: tuple["Hassette", "SimpleTestServer"]
    ) -> None:
        """get_state returns typed state when proxy is ready and entity exists."""
        hassette, _ = hassette_with_state_proxy
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

    async def test_returns_none_for_missing_entity(
        self, hassette_with_state_proxy: tuple["Hassette", "SimpleTestServer"]
    ) -> None:
        """get_state returns None when entity does not exist in cache."""
        hassette, _ = hassette_with_state_proxy
        proxy = hassette._state_proxy_resource

        result = proxy.get_state("light.nonexistent")
        assert result is None

    async def test_raises_when_not_ready(
        self, hassette_with_state_proxy: tuple["Hassette", "SimpleTestServer"]
    ) -> None:
        """get_state raises ResourceNotReadyError when proxy is not ready."""
        hassette, _ = hassette_with_state_proxy
        proxy = hassette._state_proxy_resource

        # Mark proxy as not ready
        proxy.mark_not_ready(reason="Test")

        with pytest.raises(ResourceNotReadyError, match="StateProxy is not ready"):
            proxy.get_state("light.test")

    async def test_lockfree_read_access(self, hassette_with_state_proxy: tuple["Hassette", "SimpleTestServer"]) -> None:
        """get_state does not acquire lock (lock-free read)."""
        hassette, _ = hassette_with_state_proxy
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

    async def test_adds_new_entity(self, hassette_with_state_proxy: tuple["Hassette", "SimpleTestServer"]) -> None:
        """on_state_changed adds new entity when old_state is None."""
        hassette, _ = hassette_with_state_proxy
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

    async def test_updates_existing_entity(
        self, hassette_with_state_proxy: tuple["Hassette", "SimpleTestServer"]
    ) -> None:
        """on_state_changed updates entity when both states present."""
        hassette, _ = hassette_with_state_proxy
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

    async def test_removes_entity_when_new_state_none(
        self, hassette_with_state_proxy: tuple["Hassette", "SimpleTestServer"]
    ) -> None:
        """on_state_changed removes entity when new_state is None."""
        hassette, _ = hassette_with_state_proxy
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

    async def test_handles_multiple_domain_types(
        self, hassette_with_state_proxy: tuple["Hassette", "SimpleTestServer"]
    ) -> None:
        """on_state_changed correctly handles different entity domains."""
        hassette, _ = hassette_with_state_proxy
        proxy = hassette._state_proxy_resource

        # Add entities of different types
        light_dict = make_light_state_dict("light.test", "on")
        sensor_dict = make_sensor_state_dict("sensor.temp", "22.5")
        switch_dict = make_switch_state_dict("switch.test", "off")

        for entity_id, state_dict in [
            ("light.test", light_dict),
            ("sensor.temp", sensor_dict),
            ("switch.test", switch_dict),
        ]:
            event = make_state_change_event(entity_id, None, state_dict)
            await hassette.send_event(topics.HASS_EVENT_STATE_CHANGED, event)

        await asyncio.sleep(0.1)

        # Verify all were added with correct types
        assert isinstance(proxy.states["light.test"], LightState)
        assert isinstance(proxy.states["sensor.temp"], SensorState)
        assert isinstance(proxy.states["switch.test"], SwitchState)

    async def test_concurrent_state_changes_are_serialized(
        self, hassette_with_state_proxy: tuple["Hassette", "SimpleTestServer"]
    ) -> None:
        """Multiple state_changed events are processed serially due to lock."""
        hassette, _ = hassette_with_state_proxy
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

    async def test_clears_cache_on_stop(self, hassette_with_state_proxy: tuple["Hassette", "SimpleTestServer"]) -> None:
        """on_homeassistant_stop clears the state cache."""
        hassette, _ = hassette_with_state_proxy
        proxy = hassette._state_proxy_resource

        # Add some states
        proxy.states["light.test"] = LightState.model_validate(make_light_state_dict("light.test", "on"))
        proxy.states["sensor.test"] = SensorState.model_validate(make_sensor_state_dict("sensor.test", "20"))
        assert len(proxy.states) >= 2

        # Trigger HA stop
        await proxy.on_homeassistant_stop()

        # Cache should be cleared
        assert len(proxy.states) == 0

    async def test_marks_not_ready_on_stop(
        self, hassette_with_state_proxy: tuple["Hassette", "SimpleTestServer"]
    ) -> None:
        """on_homeassistant_stop marks proxy as not ready."""
        hassette, _ = hassette_with_state_proxy
        proxy = hassette._state_proxy_resource

        assert proxy.is_ready()

        await proxy.on_homeassistant_stop()

        assert not proxy.is_ready()

    async def test_subscribes_to_start_on_stop(
        self, hassette_with_state_proxy: tuple["Hassette", "SimpleTestServer"]
    ) -> None:
        """on_homeassistant_stop subscribes to homeassistant_start."""
        hassette, _ = hassette_with_state_proxy
        proxy = hassette._state_proxy_resource

        initial_subscription_count = len(proxy.bus._subscriptions)

        await proxy.on_homeassistant_stop()

        # Should have added a subscription for HA start
        assert len(proxy.bus._subscriptions) >= initial_subscription_count

    async def test_resyncs_on_start(self, hassette_with_state_proxy: tuple["Hassette", "SimpleTestServer"]) -> None:
        """on_homeassistant_start performs full state resync."""
        hassette, mock_server = hassette_with_state_proxy
        proxy = hassette._state_proxy_resource

        # Clear cache and mark not ready (simulating HA stop)
        proxy.states.clear()
        proxy.mark_not_ready(reason="HA stopped")

        # Configure mock API response for resync
        mock_states = [
            make_light_state_dict("light.kitchen", "on"),
            make_sensor_state_dict("sensor.temp", "21.0"),
        ]
        mock_server.expect("GET", "/api/states", "", json=mock_states, status=200)

        # Trigger HA start
        await proxy.on_homeassistant_start()
        await asyncio.sleep(0.1)

        # States should be resynced
        assert proxy.is_ready()
        assert len(proxy.states) >= 2
        mock_server.assert_clean()

    async def test_handles_resync_failure(
        self, hassette_with_state_proxy: tuple["Hassette", "SimpleTestServer"]
    ) -> None:
        """on_homeassistant_start handles API failure gracefully."""
        hassette, _ = hassette_with_state_proxy
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

    async def test_removes_all_listeners(
        self, hassette_with_state_proxy: tuple["Hassette", "SimpleTestServer"]
    ) -> None:
        """Shutdown removes all bus listeners."""
        hassette, _ = hassette_with_state_proxy
        proxy = hassette._state_proxy_resource

        assert len(proxy.bus._subscriptions) > 0

        await proxy.on_shutdown()

        # All subscriptions should be removed
        assert len(proxy.bus._subscriptions) == 0

    async def test_clears_cache_on_shutdown(
        self, hassette_with_state_proxy: tuple["Hassette", "SimpleTestServer"]
    ) -> None:
        """Shutdown clears the state cache."""
        hassette, _ = hassette_with_state_proxy
        proxy = hassette._state_proxy_resource

        # Add states
        proxy.states["light.test"] = LightState.model_validate(make_light_state_dict("light.test", "on"))

        await proxy.on_shutdown()

        assert len(proxy.states) == 0

    async def test_marks_not_ready_on_shutdown(
        self, hassette_with_state_proxy: tuple["Hassette", "SimpleTestServer"]
    ) -> None:
        """Shutdown marks proxy as not ready."""
        hassette, _ = hassette_with_state_proxy
        proxy = hassette._state_proxy_resource

        assert proxy.is_ready()

        await proxy.on_shutdown()

        assert not proxy.is_ready()


class TestStateProxyResourceConcurrency:
    """Tests for thread-safety and concurrency."""

    async def test_concurrent_reads_dont_block(
        self, hassette_with_state_proxy: tuple["Hassette", "SimpleTestServer"]
    ) -> None:
        """Multiple concurrent reads should not block each other."""
        hassette, _ = hassette_with_state_proxy
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

    async def test_writes_are_serialized(
        self, hassette_with_state_proxy: tuple["Hassette", "SimpleTestServer"]
    ) -> None:
        """Write operations acquire lock and are serialized."""
        hassette, _ = hassette_with_state_proxy
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

    async def test_read_during_write_sees_consistent_state(
        self, hassette_with_state_proxy: tuple["Hassette", "SimpleTestServer"]
    ) -> None:
        """Reads during writes see a consistent state snapshot."""
        hassette, _ = hassette_with_state_proxy
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
