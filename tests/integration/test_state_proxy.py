"""Tests for StateProxy functionality.

Tests cover initialization, state management, event handling, HA lifecycle,
shutdown behavior, and thread-safety/concurrency.
"""

import asyncio
import contextlib
from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, Mock, patch

import pytest

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
    from hassette.test_utils.harness import HassetteHarness


class TestStateProxyInit:
    proxy: "StateProxy"

    def setup_hassette(self, hassette: "HassetteHarness") -> None:
        """Set up Hassette instance and extract StateProxy.

        Args:
            hassette: The HassetteHarness instance from fixture
        """
        self.hassette = hassette
        self.api = hassette.api
        self.bus = hassette.bus
        self.proxy = hassette.state_proxy

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
        event = make_full_state_change_event(entity_id, old_state_dict, new_state_dict)
        await self.hassette.send_event(event)
        await wait_for(
            lambda: self.hassette.state_proxy.get_state(entity_id) is not None,
            desc=f"{entity_id} state arrived",
        )

    async def test_waits_for_dependencies(self, hassette_with_state_proxy: "HassetteHarness") -> None:
        """State proxy waits for WebSocket, API, and Bus services before initializing."""
        self.setup_hassette(hassette_with_state_proxy)

        # Verify proxy is ready (which means all dependencies were awaited)
        assert self.proxy.is_ready()

    async def test_performs_initial_sync(self, hassette_with_state_proxy: "HassetteHarness") -> None:
        """State proxy performs initial sync during initialization."""
        self.setup_hassette(hassette_with_state_proxy)

        # Proxy should have cached states from the initial sync
        assert isinstance(self.proxy.states, dict)
        # Initially empty since mock returns empty list
        assert len(self.proxy.states) == 0, f"Expected 0 states, got {len(self.proxy.states)} ({self.proxy.states})"

    async def test_marks_ready_after_sync(self, hassette_with_state_proxy: "HassetteHarness") -> None:
        """State proxy marks itself ready after successful initial sync."""
        self.setup_hassette(hassette_with_state_proxy)

        assert self.proxy.is_ready()
        assert len(self.proxy.states) >= 0  # Could be 0 or more depending on mock

    async def test_subscribes_to_events(self, hassette_with_state_proxy: "HassetteHarness") -> None:
        """State proxy subscribes to state_changed and homeassistant_stop events."""
        self.setup_hassette(hassette_with_state_proxy)

        listeners = self.proxy.bus.get_listeners()
        assert len(listeners) > 0, "Should have listeners after initialization"
        topic_set = {listener.topic for listener in listeners}
        assert Topic.HASS_EVENT_STATE_CHANGED in topic_set, "Should subscribe to state_changed"

    async def test_raises_on_api_failure_during_init(self, hassette_with_state_proxy: "HassetteHarness") -> None:
        """State proxy raises exception if API fails during initial sync."""

        hassette = hassette_with_state_proxy

        with patch.object(hassette.api, "get_states_raw", new_callable=AsyncMock) as mock_get_states:
            mock_get_states.side_effect = Exception("API failure during init")

            proxy = hassette.state_proxy

            with pytest.raises(Exception, match="API failure during init"):
                await proxy.on_initialize()

        # Clear collision-detection state so the retry doesn't raise "duplicate listener"
        proxy.bus._registered_listeners.clear()
        await proxy.on_initialize()  # Ensure it can be used in later tests


@pytest.fixture
def state_proxy():
    mock_hassette = Mock()
    mock_hassette.config.logging.state_proxy = "DEBUG"
    mock_hassette.config.logging.task_bucket = "DEBUG"
    mock_hassette.config.logging.log_level = "DEBUG"
    mock_hassette.config.logging.bus_service = "DEBUG"

    # Bus.remove_all_listeners() delegates to bus_service.remove_listeners_by_owner()
    # which is now synchronous and returns None.
    mock_hassette._bus_service.remove_listeners_by_owner.return_value = None
    # Bus registration awaits bus_service.add_listener() — must be AsyncMock.
    mock_hassette._bus_service.add_listener = AsyncMock()

    proxy = StateProxy(mock_hassette, parent=mock_hassette)
    proxy.mark_ready(reason="Test setup")
    return proxy


def simulate_disconnect(proxy: "StateProxy", *, clear_subscription: bool = False) -> None:
    """Put a state_proxy into the disconnected state for reconnect tests."""
    proxy.states.clear()
    proxy.mark_not_ready(reason="HA stopped")
    if clear_subscription:
        proxy.state_change_sub = None


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

    async def test_raises_when_not_ready_and_cache_empty(self, state_proxy: "StateProxy") -> None:
        """get_state_once raises ResourceNotReadyError when proxy is not ready and cache is empty."""
        state_proxy.states.clear()
        state_proxy.mark_not_ready(reason="Test")

        with pytest.raises(ResourceNotReadyError, match="StateProxy is not ready"):
            state_proxy.get_state_once("light.test")
        state_proxy.mark_ready(reason="Test complete")

    async def test_returns_stale_data_when_not_ready_but_cached(self, state_proxy: "StateProxy") -> None:
        """get_state returns stale cached data when proxy is not ready but cache has entries."""
        state_proxy.states["light.test"] = make_light_state_dict("light.test", "on", brightness=150)
        state_proxy.mark_not_ready(reason="Disconnected")

        result = state_proxy.get_state("light.test")
        assert result is not None
        assert result["entity_id"] == "light.test"
        assert result["attributes"]["brightness"] == 150

        missing = state_proxy.get_state("light.nonexistent")
        assert missing is None

        state_proxy.mark_ready(reason="Test complete")

    async def test_returns_stale_domain_states_when_not_ready_but_cached(self, state_proxy: "StateProxy") -> None:
        """yield_domain_states returns stale data when not ready but cache has entries."""
        state_proxy.states["light.kitchen"] = make_light_state_dict("light.kitchen", "on")
        state_proxy.states["light.bedroom"] = make_light_state_dict("light.bedroom", "off")
        state_proxy.states["sensor.temp"] = make_sensor_state_dict("sensor.temp", "22")
        state_proxy.mark_not_ready(reason="Disconnected")

        domain_states = state_proxy.get_domain_states("light")
        assert len(domain_states) == 2
        assert "light.kitchen" in domain_states
        assert "light.bedroom" in domain_states

        state_proxy.mark_ready(reason="Test complete")

    async def test_returns_stale_contains_when_not_ready_but_cached(self, state_proxy: "StateProxy") -> None:
        """__contains__ returns stale results when not ready but cache has entries."""
        state_proxy.states["light.test"] = make_light_state_dict("light.test", "on")
        state_proxy.mark_not_ready(reason="Disconnected")

        assert "light.test" in state_proxy
        assert "light.nonexistent" not in state_proxy

        state_proxy.mark_ready(reason="Test complete")

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

    async def test_adds_new_entity(self, hassette_with_state_proxy: "HassetteHarness") -> None:
        """on_state_changed adds new entity when old_state is None."""
        hassette = hassette_with_state_proxy
        proxy = hassette.state_proxy

        # Create and send a state change event for a new entity
        light_dict = make_light_state_dict("light.new_light", "on", brightness=100)
        event = make_full_state_change_event("light.new_light", None, light_dict)

        await hassette.send_event(event)
        await wait_for(
            lambda: "light.new_light" in proxy.states,
            desc="light.new_light state arrived",
        )

        # Verify entity was added
        assert "light.new_light" in proxy.states
        state = proxy.states["light.new_light"]
        assert isinstance(state, dict)
        assert state["entity_id"] == "light.new_light"

    async def test_updates_existing_entity(self, hassette_with_state_proxy: "HassetteHarness") -> None:
        """on_state_changed updates entity when both states present."""
        proxy = hassette_with_state_proxy.state_proxy

        event_gate = asyncio.Event()

        await proxy.bus.on_state_change(
            entity_id="light.*", handler=lambda: event_gate.set(), changed=False, name="test_updates_existing"
        )

        # Add initial state
        old_dict = make_light_state_dict("light.test", "on", brightness=100)
        proxy.states["light.test"] = old_dict

        # make and send update event
        event = make_full_state_change_event(
            "light.test",
            old_dict,
            make_light_state_dict("light.test", "on", brightness=200),
        )

        await hassette_with_state_proxy.send_event(event)
        await asyncio.wait_for(event_gate.wait(), timeout=1.0)

        # Verify entity was updated
        state = proxy.states["light.test"]
        assert state["attributes"]["brightness"] == 200

    async def test_removes_entity_when_new_state_none(self, hassette_with_state_proxy: "HassetteHarness") -> None:
        """on_state_changed removes entity when new_state is None."""
        hassette = hassette_with_state_proxy
        proxy = hassette.state_proxy

        event_gate = asyncio.Event()

        await proxy.bus.on_state_change(
            entity_id="light.*", handler=lambda: event_gate.set(), changed=False, name="test_removes_entity"
        )

        # Add initial state
        old_dict = make_light_state_dict("light.test", "on")
        proxy.states["light.test"] = old_dict
        assert "light.test" in proxy.states

        # Send removal event (new_state=None)
        event = make_full_state_change_event("light.test", old_dict, None)

        await hassette.send_event(event)
        await asyncio.wait_for(event_gate.wait(), timeout=1.0)

        # Verify entity was removed
        assert "light.test" not in proxy.states

    async def test_handles_multiple_domain_types(self, hassette_with_state_proxy: "HassetteHarness") -> None:
        """on_state_changed stores all entities as BaseState"""
        hassette = hassette_with_state_proxy
        proxy = hassette.state_proxy

        event_gate = asyncio.Event()

        await proxy.bus.on_state_change(
            entity_id="*", handler=lambda: event_gate.set(), changed=False, debounce=0.1, name="test_multi_domain"
        )

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
            await hassette.send_event(event)

        await asyncio.wait_for(event_gate.wait(), timeout=1.0)

        # Verify all were added with correct types
        assert isinstance(proxy.states["light.test"], dict)
        assert isinstance(proxy.states["sensor.temperature"], dict)
        assert isinstance(proxy.states["switch.test"], dict)

    async def test_concurrent_state_changes_are_serialized(self, hassette_with_state_proxy: "HassetteHarness") -> None:
        """Multiple state_changed events are processed serially due to lock."""
        hassette = hassette_with_state_proxy
        proxy = hassette.state_proxy

        event_gate = asyncio.Event()

        # debounce to avoid firing until all events sent
        await proxy.bus.on_state_change(
            entity_id="light.*",
            handler=lambda: event_gate.set(),
            changed=False,
            debounce=0.1,
            name="test_concurrent_serialized",
        )

        # Send multiple events rapidly
        events = []
        for i in range(10):
            light_dict = make_light_state_dict(f"light.test_{i}", "on", brightness=i * 10)
            event = make_full_state_change_event(f"light.test_{i}", None, light_dict)
            events.append(event)

        # Send all events
        await asyncio.gather(*[hassette.send_event(event) for event in events])
        await asyncio.wait_for(event_gate.wait(), timeout=1.0)

        # All should be processed correctly
        for i in range(10):
            assert f"light.test_{i}" in proxy.states


class TestStateProxyWebsocketListeners:
    """Tests for websocket events that trigger clear/sync states."""

    async def test_retains_cache_on_disconnect(self, state_proxy: "StateProxy") -> None:
        """on_disconnect retains the stale state cache."""

        # Add some states
        state_proxy.states["light.test"] = make_light_state_dict("light.test", "on")
        state_proxy.states["sensor.test"] = make_sensor_state_dict("sensor.test", "20")
        assert len(state_proxy.states) >= 2

        with patch.object(state_proxy, "mark_not_ready") as mock_mark_not_ready:
            await state_proxy.on_disconnect()

        # Cache retained for stale reads
        assert len(state_proxy.states) == 2
        assert state_proxy.states["light.test"]["entity_id"] == "light.test"
        mock_mark_not_ready.assert_called_once()

    async def test_marks_not_ready_on_disconnect(self, state_proxy: "StateProxy") -> None:
        """on_disconnect marks proxy as not ready."""

        orig_state = state_proxy.is_ready()

        if not orig_state:
            state_proxy.mark_ready(reason="Test setup")

        with patch.object(state_proxy, "mark_not_ready") as mock_mark_not_ready:
            await state_proxy.on_disconnect()

        mock_mark_not_ready.assert_called_once()

        if orig_state:
            state_proxy.mark_ready(reason="Test complete")  # Restore ready state for other tests

    async def test_subscription_count_stable_on_disconnect(self, hassette_with_state_proxy: "HassetteHarness") -> None:
        """on_disconnect retains cache and does not add new subscriptions (they're already registered)."""

        proxy = hassette_with_state_proxy.state_proxy

        listeners = proxy.bus.get_listeners()

        initial_subscription_count = len(listeners)
        expected_sub_count = initial_subscription_count - 1  # because state_change_listener removes itself

        with patch.object(proxy, "mark_not_ready") as mock_mark_not_ready:
            await proxy.on_disconnect()

        mock_mark_not_ready.assert_called_once()

        # Subscriptions should remain the same (all registered in on_initialize)
        listeners_after = proxy.bus.get_listeners()
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

    async def test_events_processed_after_reconnect_with_failed_cache(
        self, hassette_with_state_proxy: "HassetteHarness"
    ) -> None:
        """State events are processed via subscription even when cache load fails on reconnect (#992)."""
        hassette = hassette_with_state_proxy
        proxy = hassette.state_proxy

        with patch.object(hassette.api, "get_states_raw", new_callable=AsyncMock) as mock_get_states:
            mock_get_states.side_effect = Exception("API error during resync")
            proxy.states.clear()
            proxy.mark_not_ready(reason="HA stopped")

            await proxy.on_reconnect()

        # Proxy is not ready (cache failed), but subscription should be live
        assert not proxy.is_ready()
        assert proxy.state_change_sub is not None

        # Send a real state change event through the harness
        light_dict = make_light_state_dict("light.kitchen", "on", brightness=100)
        event = make_full_state_change_event("light.kitchen", None, light_dict)
        await hassette.send_event(event)
        await wait_for(
            lambda: "light.kitchen" in proxy.states,
            desc="state event processed after failed-cache reconnect",
        )

        assert proxy.states["light.kitchen"]["entity_id"] == "light.kitchen"

    async def test_handles_resync_failure(self, hassette_with_state_proxy: "HassetteHarness") -> None:
        """on_reconnect handles API failure gracefully."""
        proxy = hassette_with_state_proxy.state_proxy

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

    async def test_poll_job_survives_disconnect(
        self, hassette_with_state_proxy: "HassetteHarness", monkeypatch
    ) -> None:
        """on_disconnect keeps the poll job alive so the cache self-heals."""
        monkeypatch.setattr(hassette_with_state_proxy.hassette.config, "disable_state_proxy_polling", False)
        proxy = hassette_with_state_proxy.state_proxy

        # Re-initialize with polling enabled
        proxy.bus._registered_listeners.clear()
        await proxy.on_initialize()

        assert proxy.poll_job is not None
        poll_job_before = proxy.poll_job

        await proxy.on_disconnect()

        assert not proxy.is_ready()
        assert proxy.poll_job is poll_job_before

    async def test_on_disconnect_first_call_retains_cache(self, state_proxy: "StateProxy") -> None:
        """on_disconnect retains the cache on the first call when proxy is ready."""
        state_proxy.states["light.test"] = make_light_state_dict("light.test", "on")
        state_proxy.states["sensor.test"] = make_sensor_state_dict("sensor.test", "20")
        assert len(state_proxy.states) == 2
        assert state_proxy.is_ready()

        await state_proxy.on_disconnect()

        # Cache retained, proxy not ready
        assert len(state_proxy.states) == 2
        assert not state_proxy.is_ready()

    async def test_on_disconnect_idempotent(self, state_proxy: "StateProxy") -> None:
        """on_disconnect is a no-op when StateProxy is already not-ready.

        During early-drop retry cycles, StateProxy may receive multiple DISCONNECTED
        events. After the first call marks not-ready, all subsequent calls must be
        no-ops to prevent redundant work.
        """
        state_proxy.states["light.test"] = make_light_state_dict("light.test", "on")

        # First call: marks not-ready, retains cache
        await state_proxy.on_disconnect()
        assert not state_proxy.is_ready()
        assert len(state_proxy.states) == 1

        # Second call: must be a no-op
        with patch.object(state_proxy, "mark_not_ready") as mock_mark_not_ready:
            await state_proxy.on_disconnect()

        # Cache untouched, mark_not_ready not called again
        assert "light.test" in state_proxy.states
        mock_mark_not_ready.assert_not_called()

    async def test_subscribes_to_events_even_when_load_cache_fails(self, state_proxy: "StateProxy") -> None:
        """subscribe_to_events runs regardless of load_cache failure (#992)."""
        simulate_disconnect(state_proxy, clear_subscription=True)

        state_proxy.hassette.api.get_states_raw = AsyncMock(side_effect=Exception("API unavailable"))

        await state_proxy.on_reconnect()

        assert state_proxy.state_change_sub is not None

    async def test_stays_not_ready_when_load_cache_fails_but_subscribes(self, state_proxy: "StateProxy") -> None:
        """Proxy remains not-ready when cache fails, but subscription is still established (#992)."""
        simulate_disconnect(state_proxy, clear_subscription=True)

        state_proxy.hassette.api.get_states_raw = AsyncMock(side_effect=Exception("API unavailable"))

        with patch.object(state_proxy, "_emit_readiness_event", new_callable=AsyncMock) as mock_emit:
            await state_proxy.on_reconnect()

        assert not state_proxy.is_ready()
        assert state_proxy.state_change_sub is not None
        mock_emit.assert_called_once()

    async def test_not_ready_when_subscribe_to_events_fails(self, state_proxy: "StateProxy") -> None:
        """Proxy stays not-ready when cache loads but subscribe_to_events raises."""
        simulate_disconnect(state_proxy)

        state_proxy.hassette.api.get_states_raw = AsyncMock(return_value=[make_light_state_dict("light.kitchen", "on")])

        with patch.object(state_proxy, "subscribe_to_events", new_callable=AsyncMock) as mock_sub:
            mock_sub.side_effect = Exception("Bus not ready")
            await state_proxy.on_reconnect()

        assert not state_proxy.is_ready()
        assert len(state_proxy.states) > 0


class TestStateProxyReconnectConcurrency:
    """Tests for concurrent on_reconnect() serialization (#993)."""

    async def test_concurrent_reconnect_calls_are_serialized(self, state_proxy: "StateProxy") -> None:
        """Second on_reconnect waits for first; subscribe_to_events called exactly twice."""
        simulate_disconnect(state_proxy)

        gate = asyncio.Event()
        load_call_count = 0

        async def gated_load_cache():
            nonlocal load_call_count
            load_call_count += 1
            if load_call_count == 1:
                await gate.wait()
            state_proxy.states["light.kitchen"] = make_light_state_dict("light.kitchen", "on")

        state_proxy.hassette.api.get_states_raw = AsyncMock(return_value=[make_light_state_dict("light.kitchen", "on")])

        with (
            patch.object(state_proxy, "load_cache", side_effect=gated_load_cache),
            patch.object(state_proxy, "subscribe_to_events", wraps=state_proxy.subscribe_to_events) as mock_subscribe,
        ):
            task1 = asyncio.create_task(state_proxy.on_reconnect())
            task2 = asyncio.create_task(state_proxy.on_reconnect())
            await asyncio.sleep(0)

            # First call is blocked on the gate; second should be waiting on the lock
            assert not task1.done()
            assert not task2.done()

            gate.set()
            await asyncio.gather(task1, task2)

        # Both calls ran to completion sequentially
        assert load_call_count == 2
        assert mock_subscribe.call_count == 2
        assert state_proxy.state_change_sub is not None
        assert state_proxy.is_ready()

    async def test_reconnect_lock_does_not_block_state_writes(self, state_proxy: "StateProxy") -> None:
        """on_state_change completes while on_reconnect is held mid-flight."""
        simulate_disconnect(state_proxy)

        gate = asyncio.Event()

        async def gated_load_cache():
            await gate.wait()
            state_proxy.states["light.kitchen"] = make_light_state_dict("light.kitchen", "on")

        state_proxy.hassette.api.get_states_raw = AsyncMock(return_value=[make_light_state_dict("light.kitchen", "on")])

        with patch.object(state_proxy, "load_cache", side_effect=gated_load_cache):
            reconnect_task = asyncio.create_task(state_proxy.on_reconnect())
            await asyncio.sleep(0)

            # on_reconnect is blocked inside load_cache
            assert not reconnect_task.done()

            # on_state_change uses self.lock (FairAsyncRLock), not _reconnect_lock
            event = make_full_state_change_event(
                "sensor.temp",
                make_sensor_state_dict("sensor.temp", "20"),
                make_sensor_state_dict("sensor.temp", "21"),
            )
            # This must complete without deadlock
            await asyncio.wait_for(state_proxy.on_state_change(event), timeout=1.0)

            gate.set()
            await reconnect_task

        assert "sensor.temp" in state_proxy.states


class TestStateProxyReadinessEvents:
    """Tests that on_disconnect/on_reconnect emit readiness events via _emit_readiness_event()."""

    async def test_on_disconnect_emits_not_ready_event(self, state_proxy: "StateProxy") -> None:
        """on_disconnect emits a service_status event with ready=False after mark_not_ready()."""
        state_proxy.mark_ready(reason="Test setup")

        with patch.object(state_proxy, "_emit_readiness_event", new_callable=AsyncMock) as mock_emit:
            await state_proxy.on_disconnect()

        mock_emit.assert_called_once()
        assert not state_proxy.is_ready()

    async def test_on_reconnect_emits_ready_event(self, state_proxy: "StateProxy") -> None:
        """on_reconnect emits a service_status event with ready=True after mark_ready()."""
        state_proxy.states.clear()
        state_proxy.mark_not_ready(reason="HA stopped")

        mock_states = [
            make_light_state_dict("light.kitchen", "on"),
        ]
        state_proxy.hassette.api.get_states_raw = AsyncMock(return_value=mock_states)

        with patch.object(state_proxy, "_emit_readiness_event", new_callable=AsyncMock) as mock_emit:
            await state_proxy.on_reconnect()

        mock_emit.assert_called_once()
        assert state_proxy.is_ready()

    async def test_on_reconnect_failure_emits_not_ready_event(
        self, hassette_with_state_proxy: "HassetteHarness"
    ) -> None:
        """on_reconnect emits a service_status event with ready=False when resync fails."""
        proxy = hassette_with_state_proxy.state_proxy
        proxy.mark_not_ready(reason="HA stopped")

        with (
            patch.object(hassette_with_state_proxy.api, "get_states_raw", new_callable=AsyncMock) as mock_get_states,
            patch.object(proxy, "_emit_readiness_event", new_callable=AsyncMock) as mock_emit,
        ):
            mock_get_states.side_effect = Exception("API error during resync")
            await proxy.on_reconnect()

        mock_emit.assert_called_once()
        assert not proxy.is_ready()

        await proxy.on_initialize()


class TestStateProxyShutdown:
    """Tests for shutdown behavior."""

    async def test_removes_all_listeners(self, hassette_with_state_proxy: "HassetteHarness") -> None:
        """Shutdown removes all bus listeners via propagation to child Bus."""
        proxy = hassette_with_state_proxy.state_proxy

        listeners = proxy.bus.get_listeners()
        assert len(listeners) > 0, "Should have listeners before shutdown"

        await proxy.shutdown()

        # All subscriptions should be removed (Bus.on_shutdown calls remove_all_listeners)
        listeners_after = proxy.bus.get_listeners()
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


class TestStateProxyRestartRoundTrip:
    """Verify StateProxy shutdown + re-initialize restores subscriptions and state polling."""

    async def test_shutdown_stops_children(self, hassette_with_state_proxy: "HassetteHarness") -> None:
        """After StateProxy shutdown, its Bus and Scheduler children are stopped."""
        proxy = hassette_with_state_proxy.state_proxy
        assert proxy is not None

        # Verify children are ready before shutdown
        assert proxy.bus.is_ready(), "Proxy Bus should be ready"
        assert proxy.scheduler.is_ready(), "Proxy Scheduler should be ready"
        assert proxy.is_ready(), "StateProxy should be ready"

        await proxy.shutdown()

        assert not proxy.is_ready(), "StateProxy should not be ready after shutdown"
        assert not proxy.bus.is_ready(), "Proxy Bus should not be ready after shutdown"
        assert not proxy.scheduler.is_ready(), "Proxy Scheduler should not be ready after shutdown"
        assert len(proxy.states) == 0, "State cache should be cleared"

        # Re-initialize
        await proxy.initialize()

        assert proxy.is_ready(), "StateProxy should be ready after re-initialize"
        assert proxy.bus.is_ready(), "Proxy Bus should be ready after re-initialize"
        assert proxy.scheduler.is_ready(), "Proxy Scheduler should be ready after re-initialize"

    async def test_subscriptions_restored_after_restart(self, hassette_with_state_proxy: "HassetteHarness") -> None:
        """After shutdown + re-initialize, state change subscriptions work."""
        hassette = hassette_with_state_proxy
        proxy = hassette.state_proxy
        assert proxy is not None

        # Shutdown clears everything
        await proxy.shutdown()
        assert len(proxy.states) == 0

        # Re-initialize restores subscriptions
        await proxy.initialize()

        # Verify subscriptions are re-established by checking listeners
        listeners = proxy.bus.get_listeners()
        assert len(listeners) > 0, "Should have listeners after re-initialize"
        topic_set = {listener.topic for listener in listeners}
        assert Topic.HASS_EVENT_STATE_CHANGED in topic_set, "Should subscribe to state_changed after re-initialize"

    async def test_state_events_processed_after_restart(self, hassette_with_state_proxy: "HassetteHarness") -> None:
        """After restart, the proxy processes new state change events."""
        hassette = hassette_with_state_proxy
        proxy = hassette.state_proxy
        assert proxy is not None

        # Full restart cycle
        await proxy.shutdown()
        await proxy.initialize()

        # Send a state change event and verify it's processed
        light_dict = make_light_state_dict("light.restart_test", "on", brightness=150)
        event = make_full_state_change_event("light.restart_test", None, light_dict)

        await hassette.send_event(event)
        await wait_for(
            lambda: "light.restart_test" in proxy.states,
            desc="light.restart_test state arrived after restart",
        )

        assert "light.restart_test" in proxy.states
        state = proxy.states["light.restart_test"]
        assert state["entity_id"] == "light.restart_test"
        assert state["attributes"]["brightness"] == 150


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

    async def test_writes_are_serialized(self, hassette_with_state_proxy: "HassetteHarness") -> None:
        """Write operations acquire lock and are serialized."""
        hassette = hassette_with_state_proxy
        proxy = hassette.state_proxy
        max_brightness = 0

        # def handler(new_brightness: D.AttrNew("brightness")):
        def handler(event: RawStateChangeEvent):
            new_brightness = event.payload.data.new_state["attributes"]["brightness"]
            if new_brightness == max_brightness:
                event_gate.set()

        event_gate = asyncio.Event()
        await proxy.bus.on_state_change(
            entity_id="light.*", handler=handler, changed=False, name="test_writes_serialized"
        )
        # Send many concurrent state change events
        events = []
        for i in range(20):
            if i > max_brightness:
                max_brightness = i
            light_dict = make_light_state_dict("light.test", "on", brightness=i)
            event = make_full_state_change_event("light.test", light_dict, light_dict)
            events.append(event)

        await asyncio.gather(*[hassette.send_event(event) for event in events])
        await asyncio.wait_for(event_gate.wait(), timeout=1.0)

        # Final state should be consistent (last update wins)
        state = proxy.states.get("light.test")
        assert state is not None
        assert isinstance(state, dict)
        assert state["attributes"]["brightness"] == max_brightness

    async def test_read_during_write_sees_consistent_state(self, hassette_with_state_proxy: "HassetteHarness") -> None:
        """Reads during writes see a consistent state snapshot."""
        hassette = hassette_with_state_proxy
        proxy = hassette.state_proxy

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
                await hassette.send_event(event)
                await asyncio.sleep(0.01)

        # Run reads and writes concurrently
        await asyncio.gather(continuous_read(), continuous_write())

        # All reads should return valid brightness values
        assert all(isinstance(b, (int, float)) for b in read_results)
        assert len(read_results) > 0


class TestStateProxyPollNonOverlap:
    """AC#13 / FR#15: the state-proxy poll job never runs load_cache concurrently.

    Asserts scheduler-level single-mode suppression, not just the internal
    lock serializing concurrent entries. When a poll invocation is still in
    flight as the next tick becomes due, the guard's suppressed counter
    increments and load_cache is not entered a second time.
    """

    async def test_overrunning_poll_does_not_run_load_cache_concurrently(
        self, hassette_with_state_proxy: "HassetteHarness", monkeypatch
    ) -> None:
        """AC#13: an overrunning load_cache poll is suppressed at the scheduler level.

        Drives an overrun by holding load_cache open (asyncio.Event gate),
        dispatching a second tick while the first is in flight, and asserting:
        - guard.suppressed >= 1 (scheduler-level suppression, not just lock)
        - concurrent entry count never exceeds 1
        """
        monkeypatch.setattr(hassette_with_state_proxy.hassette.config, "disable_state_proxy_polling", False)

        proxy = hassette_with_state_proxy.state_proxy
        # The poll job is registered via the state proxy's own child Scheduler,
        # which shares the harness's top-level SchedulerService.
        scheduler_service = proxy.scheduler.scheduler_service

        # A proper shutdown/initialize cycle with polling now enabled ensures a
        # fresh ScheduledJob with _dequeued=False.  Calling on_initialize() directly
        # a second time hits if_exists="skip" which returns the old dequeued job
        # (whose _dequeued flag is True), making dispatch_and_log a no-op.
        await proxy.shutdown()
        await proxy.initialize()

        assert proxy.poll_job is not None, "poll_job should be registered when polling is enabled"
        poll_job = proxy.poll_job

        # Instrument load_cache to gate execution and count concurrent entries.
        gate = asyncio.Event()
        entered = asyncio.Event()
        concurrent_entries = [0]
        max_concurrent_entries = [0]

        original_job_callable = poll_job.job

        async def gated_load_cache() -> None:
            concurrent_entries[0] += 1
            max_concurrent_entries[0] = max(max_concurrent_entries[0], concurrent_entries[0])
            entered.set()
            try:
                await gate.wait()
                await original_job_callable()
            finally:
                concurrent_entries[0] -= 1

        # Replace the stored callable on the job object so dispatch_and_log invokes
        # our instrumented version (job.job is the bound method stored at registration).
        poll_job.job = gated_load_cache

        # Freeze time at the first due tick.
        frozen_time = poll_job.next_run.add(seconds=1)

        with patch("hassette.utils.date_utils.now", side_effect=lambda: frozen_time):
            # Dispatch tick 1 in a background task — will block inside gated_load_cache.
            dispatch1 = asyncio.create_task(scheduler_service.dispatch_and_log(poll_job))
            try:
                # Wait until gated_load_cache is actually executing (spawned task has started).
                await asyncio.wait_for(entered.wait(), timeout=2.0)
                assert concurrent_entries[0] == 1, "First poll should be in flight"

                # After dispatch-time reschedule, poll_job is re-enqueued on the heap.
                # Get it — it's the same object cycled back.
                all_jobs = await scheduler_service.get_all_jobs()
                next_poll = next((j for j in all_jobs if j is poll_job), None)
                assert next_poll is not None, "poll_job should have been re-enqueued (dispatch-time reschedule, FR#1)"

                # Move time forward past the second tick.
                frozen_time = next_poll.next_run.add(seconds=1)

                # Dispatch tick 2 inline — guard should suppress (single mode, AC#13).
                await scheduler_service.dispatch_and_log(next_poll)

                # The guard suppressed the second invocation at the scheduler level.
                assert poll_job.guard.suppressed >= 1, (
                    f"Expected guard.suppressed >= 1 (single-mode scheduler suppression, AC#13), "
                    f"got {poll_job.guard.suppressed}"
                )

                # load_cache was never entered by both ticks concurrently.
                assert max_concurrent_entries[0] <= 1, (
                    f"load_cache entered concurrently (max_concurrent={max_concurrent_entries[0]}); "
                    "scheduler-level single-mode guard should prevent this (AC#13)"
                )
            finally:
                # Always unblock and drain the first dispatch, even if an assertion
                # above failed — otherwise the blocked background task and the
                # patched callable leak into later tests. Cleanup runs while the
                # clock is still frozen, so run_job logs no behind-schedule warning.
                poll_job.job = original_job_callable
                gate.set()
                with contextlib.suppress(asyncio.CancelledError, TimeoutError):
                    await asyncio.wait_for(dispatch1, timeout=2.0)
