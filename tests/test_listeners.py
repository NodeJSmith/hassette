import asyncio
import inspect
import json
import random
from dataclasses import dataclass
from pathlib import Path

import pytest

from hassette import dependencies as D
from hassette.bus.listeners import HandlerAdapter, Listener
from hassette.events import Event, StateChangeEvent, create_event_from_hass
from hassette.exceptions import InvalidDependencyReturnTypeError
from hassette.models import states
from hassette.task_bucket import TaskBucket


@pytest.fixture(scope="session")
def state_change_events(test_data_path: Path) -> list[StateChangeEvent]:
    """Load state change events from test data file."""
    events = []
    with open(test_data_path / "state_change_events.jsonl") as f:
        for line in f:
            if line.strip():
                # Strip trailing comma if present (JSONL files may have them)
                line = line.strip().rstrip(",")
                envelope = json.loads(line)
                event = create_event_from_hass(envelope)
                if isinstance(event, StateChangeEvent):
                    events.append(event)

    # randomize order
    random.shuffle(events)

    return events


@pytest.fixture(scope="session")
def state_change_events_with_new_state(
    state_change_events: list[StateChangeEvent],
) -> list[StateChangeEvent]:
    """Filter state change events to only those with a new state."""
    return [e for e in state_change_events if e.payload.data.new_state is not None]


@pytest.fixture(scope="session")
def state_change_events_with_old_state(
    state_change_events: list[StateChangeEvent],
) -> list[StateChangeEvent]:
    """Filter state change events to only those with an old state."""
    return [e for e in state_change_events if e.payload.data.old_state is not None]


@pytest.fixture
def state_change_events_with_both_states(
    state_change_events: list[StateChangeEvent],
) -> list[StateChangeEvent]:
    """Filter state change events to only those with both old and new states."""
    return [
        e for e in state_change_events if e.payload.data.old_state is not None and e.payload.data.new_state is not None
    ]


@dataclass(frozen=True, slots=True)
class MockEvent(Event[str]):
    """Mock event for testing."""

    @property
    def data(self) -> str:
        """Return payload for backward compatibility with tests."""
        return self.payload


def mock_event(data: str = "test") -> MockEvent:
    """Create a MockEvent with a topic and payload."""
    return MockEvent(topic="test_topic", payload=data)


def create_adapter(handler, bucket_fixture, **kwargs):
    """Helper to create HandlerAdapter with proper signature."""
    signature = inspect.signature(handler)
    handler_name = handler.__name__ if hasattr(handler, "__name__") else "test_handler"
    return HandlerAdapter(handler_name, handler, signature, bucket_fixture, **kwargs)


class TestHandlerAdapter:
    """Test HandlerAdapter functionality."""

    async def test_sync_handler_with_event(self, bucket_fixture: TaskBucket):
        """Test sync handler that expects an event."""
        calls = []

        def handler(event: MockEvent):
            calls.append(event.data)

        async_handler = bucket_fixture.make_async_adapter(handler)
        adapter = create_adapter(async_handler, bucket_fixture)

        event = mock_event("test_data")
        await adapter.call(event)
        assert calls == ["test_data"], "Handler should be called with event data"

    async def test_async_handler_with_event(self, bucket_fixture: TaskBucket):
        """Test async handler that expects an event."""
        calls = []

        async def handler(event: MockEvent):
            calls.append(event.data)

        adapter = create_adapter(handler, bucket_fixture)

        event = mock_event("test_data")
        await adapter.call(event)
        assert calls == ["test_data"], "Handler should be called with event data"

    async def test_sync_handler_no_event(self, bucket_fixture: TaskBucket):
        """Test sync handler that doesn't expect an event."""
        calls = []

        def handler():
            calls.append("called")

        async_handler = bucket_fixture.make_async_adapter(handler)
        adapter = create_adapter(async_handler, bucket_fixture)

        event = mock_event("test_data")
        await adapter.call(event)
        assert calls == ["called"], "Handler should be called without event data"

    async def test_async_handler_no_event(self, bucket_fixture: TaskBucket):
        """Test async handler that doesn't expect an event."""
        calls = []

        async def handler():
            calls.append("called")

        adapter = create_adapter(handler, bucket_fixture)

        event = mock_event("test_data")
        await adapter.call(event)
        assert calls == ["called"], "Handler should be called without event data"


class TestDebounceLogic:
    """Test debounce functionality."""

    async def test_debounce_delays_execution(self, bucket_fixture: TaskBucket):
        """Test that debounce delays execution until quiet period."""
        calls = []

        def handler(event: MockEvent):
            calls.append(event.data)

        async_handler = bucket_fixture.make_async_adapter(handler)
        adapter = create_adapter(async_handler, bucket_fixture, debounce=0.1)

        # Fire multiple events quickly
        event1 = mock_event("first")
        event2 = mock_event("second")
        event3 = mock_event("third")

        await adapter.call(event1)
        await adapter.call(event2)
        await adapter.call(event3)

        await asyncio.sleep(0)

        # Nothing should be called immediately
        assert calls == [], "No calls should be made immediately due to debounce"

        # Wait for debounce period plus some buffer
        await asyncio.sleep(0.2)

        # Only the last event should be processed
        assert calls == ["third"], "Only the last event should be processed after debounce"

    async def test_debounce_with_no_event_handler(self, bucket_fixture: TaskBucket):
        """Test debounce with handler that doesn't expect event."""
        calls = []

        def handler():
            calls.append("called")

        async_handler = bucket_fixture.make_async_adapter(handler)
        adapter = create_adapter(async_handler, bucket_fixture, debounce=0.1)

        # Fire multiple events quickly
        event = mock_event("data")
        await adapter.call(event)
        await adapter.call(event)
        await adapter.call(event)

        # Wait for debounce period
        await asyncio.sleep(0.2)

        # Should be called once
        assert calls == ["called"], "Handler should be called only once after debounce"

    async def test_debounce_cancels_previous_calls(self, bucket_fixture: TaskBucket):
        """Test that new debounce calls cancel previous pending calls."""
        calls = []

        async def handler(event: MockEvent):
            calls.append(event.data)

        adapter = create_adapter(handler, bucket_fixture, debounce=0.2)

        # First call
        await adapter.call(mock_event("first"))
        await asyncio.sleep(0.1)  # Wait 100ms
        assert adapter._debounce_task is not None, "Debounce task should be created"
        assert not adapter._debounce_task.done(), "Debounce task should still be pending"

        # Second call should cancel first
        await adapter.call(mock_event("second"))
        await asyncio.sleep(0.1)  # Wait another 100ms
        assert adapter._debounce_task is not None, "Debounce task should be created"
        assert not adapter._debounce_task.done(), "Debounce task should still be pending"

        # Third call should cancel second
        await adapter.call(mock_event("third"))

        # Wait for final debounce period
        await asyncio.sleep(0.3)

        # Only the last call should execute
        assert calls == ["third"], "Only the last call should be processed after debounce"
        assert adapter._debounce_task.done(), "Debounce task should be completed"


class TestThrottleLogic:
    """Test throttle functionality."""

    async def test_throttle_limits_execution_frequency(self, bucket_fixture: TaskBucket):
        """Test that throttle limits how often handler is called."""
        calls = []

        def handler(event: MockEvent):
            calls.append(event.data)

        async_handler = bucket_fixture.make_async_adapter(handler)
        adapter = create_adapter(async_handler, bucket_fixture, throttle=0.1)

        # First call should execute immediately
        await adapter.call(mock_event("first"))
        assert calls == ["first"], "First call should be executed immediately"

        # Subsequent calls within throttle period should be ignored
        await adapter.call(mock_event("second"))
        await adapter.call(mock_event("third"))
        assert calls == ["first"], "Subsequent calls should be ignored"

        # Wait for throttle period to pass
        await asyncio.sleep(0.15)

        # Now a new call should work
        await adapter.call(mock_event("fourth"))
        assert calls == ["first", "fourth"], "Fourth call should be executed after throttle period"

    async def test_throttle_with_no_event_handler(self, bucket_fixture: TaskBucket):
        """Test throttle with handler that doesn't expect event."""
        calls = []
        test_string = "called"

        def handler():
            nonlocal test_string
            calls.append(test_string)

        async_handler = bucket_fixture.make_async_adapter(handler)
        adapter = create_adapter(async_handler, bucket_fixture, throttle=0.1)

        # First call executes
        await adapter.call(mock_event("data"))
        assert calls == ["called"], "First call should be executed immediately"

        # Subsequent calls are throttled
        test_string = "called while throttled"
        await adapter.call(mock_event("data"))
        await adapter.call(mock_event("data"))
        assert calls == ["called"], "Subsequent calls should be ignored"

        # After throttle period
        test_string = "called after throttle"
        await asyncio.sleep(0.15)
        await adapter.call(mock_event("data"))
        assert calls == ["called", "called after throttle"], "Second call should be executed after throttle period"

    async def test_throttle_tracks_time_correctly(self, bucket_fixture: TaskBucket):
        """Test that throttle timing works correctly."""
        calls = []

        async def handler(event: MockEvent):
            calls.append(event.data)

        adapter = create_adapter(handler, bucket_fixture, throttle=0.05)

        # Series of calls with different timing
        await adapter.call(mock_event("1"))
        assert calls == ["1"]

        await asyncio.sleep(0.03)  # 30ms - should be throttled
        await adapter.call(mock_event("2"))
        assert calls == ["1"]

        await asyncio.sleep(0.03)  # Total 60ms - should work now
        await adapter.call(mock_event("3"))
        assert calls == ["1", "3"]


class TestListenerIntegration:
    """Test Listener integration with HandlerAdapter."""

    async def test_listener_with_debounce(self, bucket_fixture: TaskBucket):
        """Test Listener using debounce."""
        calls = []

        def handler(event: MockEvent):
            calls.append(event.data)

        listener = Listener.create(
            task_bucket=bucket_fixture,
            owner="test",
            topic="test_topic",
            handler=handler,
            debounce=0.1,
        )

        # Multiple rapid calls
        await listener.invoke(mock_event("1"))
        await listener.invoke(mock_event("2"))
        await listener.invoke(mock_event("3"))

        # Wait for debounce period
        await asyncio.sleep(0.2)

        # Only last event processed
        assert calls == ["3"], "Only the last event should be processed after debounce"

    async def test_listener_with_throttle(self, bucket_fixture: TaskBucket):
        """Test Listener using throttle."""
        calls = []

        def handler(event: MockEvent):
            calls.append(event.data)

        listener = Listener.create(
            task_bucket=bucket_fixture,
            owner="test",
            topic="test_topic",
            handler=handler,
            throttle=0.1,
        )

        # Multiple rapid calls
        await listener.invoke(mock_event("1"))
        await listener.invoke(mock_event("2"))
        await listener.invoke(mock_event("3"))

        # Only first should execute immediately
        assert calls == ["1"], "First call should be executed immediately"

        # Wait for throttle period
        await asyncio.sleep(0.15)

        # Now another call should work
        await listener.invoke(mock_event("4"))
        assert calls == ["1", "4"], "Second call should be executed after throttle period"

    async def test_listener_without_rate_limiting(self, bucket_fixture: TaskBucket):
        """Test Listener without debounce or throttle."""
        calls = []

        def handler(event: MockEvent):
            calls.append(event.data)

        listener = Listener.create(
            task_bucket=bucket_fixture,
            owner="test",
            topic="test_topic",
            handler=handler,
        )

        # All calls should execute immediately
        await listener.invoke(mock_event("1"))
        await listener.invoke(mock_event("2"))
        await listener.invoke(mock_event("3"))

        assert calls == ["1", "2", "3"], "All calls should be executed immediately"

    async def test_cannot_specify_both_debounce_and_throttle(self, bucket_fixture: TaskBucket):
        """Test that specifying both debounce and throttle raises an error."""

        def handler(event):
            pass

        with pytest.raises(ValueError, match="Cannot specify both 'debounce' and 'throttle'"):
            Listener.create(
                task_bucket=bucket_fixture,
                owner="test",
                topic="test_topic",
                handler=handler,
                debounce=0.1,
                throttle=0.1,
            )


class TestDependencyValidationErrors:
    """Test that listeners properly handle dependency resolution errors."""

    async def test_required_state_with_none_raises_error(self, bucket_fixture: TaskBucket):
        """Test that using StateNew with None value raises CallListenerError."""

        from hassette import dependencies as D
        from hassette.events import StateChangeEvent

        # Create a mock StateChangeEvent where new_state is None
        from hassette.events.base import HassPayload
        from hassette.events.hass.hass import StateChangePayload
        from hassette.exceptions import CallListenerError
        from hassette.models import states

        payload = HassPayload(
            event_type="state_changed",
            data=StateChangePayload(entity_id="test.entity", old_state=None, new_state=None),
            origin="LOCAL",
            time_fired="2024-01-01T00:00:00+00:00",
            context={"id": "test", "parent_id": None, "user_id": None},
        )
        event = StateChangeEvent(topic="hass.event.state_changed", payload=payload)

        calls = []

        def handler(new_state: D.StateNew[states.BaseState]):
            calls.append(new_state)

        async_handler = bucket_fixture.make_async_adapter(handler)
        adapter = create_adapter(async_handler, bucket_fixture)

        # Should raise CallListenerError wrapping InvalidDependencyReturnTypeError
        with pytest.raises(CallListenerError) as exc_info:
            await adapter.call(event)

        assert isinstance(exc_info.value.__cause__, InvalidDependencyReturnTypeError)
        assert len(calls) == 0  # Handler should not be called

    async def test_maybe_state_with_none_succeeds(self, bucket_fixture: TaskBucket):
        """Test that using MaybeStateNew with None value succeeds."""

        from hassette import dependencies as D
        from hassette.events import StateChangeEvent
        from hassette.events.base import HassPayload
        from hassette.events.hass.hass import StateChangePayload
        from hassette.models import states

        payload = HassPayload(
            event_type="state_changed",
            data=StateChangePayload(entity_id="test.entity", old_state=None, new_state=None),
            origin="LOCAL",
            time_fired="2024-01-01T00:00:00+00:00",
            context={"id": "test", "parent_id": None, "user_id": None},
        )
        event = StateChangeEvent(topic="hass.event.state_changed", payload=payload)

        calls = []

        def handler(new_state: D.MaybeStateNew[states.BaseState]):
            calls.append(new_state)

        async_handler = bucket_fixture.make_async_adapter(handler)
        adapter = create_adapter(async_handler, bucket_fixture)

        # Should succeed
        await adapter.call(event)

        assert len(calls) == 1
        assert calls[0] is None

    async def test_mixed_maybe_and_required_all_succeed(self, bucket_fixture: TaskBucket):
        """Test handler with both Maybe and required deps when all resolve."""

        from hassette import dependencies as D
        from hassette.events import StateChangeEvent
        from hassette.events.base import HassPayload
        from hassette.events.hass.hass import StateChangePayload
        from hassette.models import states
        from hassette.models.states.base import BaseState

        # Create mock states
        old_state = BaseState(
            entity_id="test.entity",
            value="off",
            last_changed="2024-01-01T00:00:00+00:00",
            last_reported="2024-01-01T00:00:00+00:00",
            last_updated="2024-01-01T00:00:00+00:00",
            context={"id": "test", "parent_id": None, "user_id": None},
            attributes={},
        )
        new_state = BaseState(
            entity_id="test.entity",
            value="on",
            last_changed="2024-01-01T00:00:01+00:00",
            last_reported="2024-01-01T00:00:01+00:00",
            last_updated="2024-01-01T00:00:01+00:00",
            context={"id": "test2", "parent_id": None, "user_id": None},
            attributes={},
        )

        payload = HassPayload(
            event_type="state_changed",
            data=StateChangePayload(entity_id="test.entity", old_state=old_state, new_state=new_state),
            origin="LOCAL",
            time_fired="2024-01-01T00:00:01+00:00",
            context={"id": "test", "parent_id": None, "user_id": None},
        )
        event = StateChangeEvent(topic="hass.event.state_changed", payload=payload)

        results = []

        def handler(
            new_state: D.StateNew[states.BaseState],  # Required, present
            old_state: D.MaybeStateOld[states.BaseState],  # Optional, present
            entity_id: D.EntityId,  # Required, present
        ):
            results.append((new_state, old_state, entity_id))

        async_handler = bucket_fixture.make_async_adapter(handler)
        adapter = create_adapter(async_handler, bucket_fixture)

        await adapter.call(event)

        assert len(results) == 1
        new, old, eid = results[0]
        assert new is not None
        assert old is not None
        assert eid == "test.entity"

    async def test_multiple_required_deps_first_fails(self, bucket_fixture: TaskBucket):
        """Test that if first required dep fails, handler is not called."""

        from hassette import dependencies as D
        from hassette.events import StateChangeEvent
        from hassette.events.base import HassPayload
        from hassette.events.hass.hass import StateChangePayload
        from hassette.exceptions import CallListenerError
        from hassette.models import states

        payload = HassPayload(
            event_type="state_changed",
            data=StateChangePayload(entity_id="test.entity", old_state=None, new_state=None),
            origin="LOCAL",
            time_fired="2024-01-01T00:00:00+00:00",
            context={"id": "test", "parent_id": None, "user_id": None},
        )
        event = StateChangeEvent(topic="hass.event.state_changed", payload=payload)

        calls = []

        def handler(
            new_state: D.StateNew[states.BaseState],  # Will fail
            entity_id: D.EntityId,  # Would succeed
        ):
            calls.append((new_state, entity_id))

        async_handler = bucket_fixture.make_async_adapter(handler)
        adapter = create_adapter(async_handler, bucket_fixture)

        with pytest.raises(CallListenerError):
            await adapter.call(event)

        assert len(calls) == 0


class TestDependencyInjectionHandlesTypeConversion:
    """Test that dependency injection handles type conversion correctly."""

    async def test_state_conversion(self, bucket_fixture: TaskBucket, state_change_events: list[StateChangeEvent]):
        """Test that StateNew converts BaseState to domain-specific state type."""

        light_event = next((e for e in state_change_events if e.payload.data.domain == "light"), None)

        assert light_event is not None, "No light domain event found in test data"

        results = []

        def handler(new_state: D.StateNew[states.LightState]):
            results.append(new_state)

        async_handler = bucket_fixture.make_async_adapter(handler)
        adapter = create_adapter(async_handler, bucket_fixture)

        await adapter.call(light_event)

        assert len(results) == 1
        light_state = results[0]
        assert isinstance(light_state, states.LightState), "State should be converted to LightState"
        assert light_state.entity_id.startswith("light."), "Entity ID should have light domain"

    async def test_annotated_as_base_state_stays_base_state(
        self, bucket_fixture: TaskBucket, state_change_events: list[StateChangeEvent]
    ):
        """Test that StateNew[BaseState] returns BaseState without conversion."""

        light_event = next((e for e in state_change_events if e.payload.data.domain == "light"), None)

        assert light_event is not None, "No light domain event found in test data"

        results = []

        def handler(new_state: D.StateNew[states.BaseState]):
            results.append(new_state)

        async_handler = bucket_fixture.make_async_adapter(handler)
        adapter = create_adapter(async_handler, bucket_fixture)

        await adapter.call(light_event)

        assert len(results) == 1
        state = results[0]
        assert isinstance(state, states.BaseState), "State should be BaseState"
        assert state.entity_id.startswith("light."), "Entity ID should have light domain"

    async def test_maybe_state_conversion(
        self, bucket_fixture: TaskBucket, state_change_events: list[StateChangeEvent]
    ):
        """Test that MaybeStateNew converts BaseState to domain-specific state type."""

        sensor_event = next((e for e in state_change_events if e.payload.data.domain == "sensor"), None)

        assert sensor_event is not None, "No sensor domain event found in test data"

        results = []

        def handler(new_state: D.MaybeStateNew[states.SensorState]):
            results.append(new_state)

        async_handler = bucket_fixture.make_async_adapter(handler)
        adapter = create_adapter(async_handler, bucket_fixture)

        await adapter.call(sensor_event)

        assert len(results) == 1
        sensor_state = results[0]
        assert isinstance(sensor_state, states.SensorState), "State should be converted to SensorState"
        assert sensor_state.entity_id.startswith("sensor."), "Entity ID should have sensor domain"

    async def test_maybe_state_as_base_state_stays_base_state(
        self, bucket_fixture: TaskBucket, state_change_events: list[StateChangeEvent]
    ):
        """Test that MaybeStateNew[BaseState] returns BaseState without conversion."""

        sensor_event = next((e for e in state_change_events if e.payload.data.domain == "sensor"), None)

        assert sensor_event is not None, "No sensor domain event found in test data"

        results = []

        def handler(new_state: D.MaybeStateNew[states.BaseState]):
            results.append(new_state)

        async_handler = bucket_fixture.make_async_adapter(handler)
        adapter = create_adapter(async_handler, bucket_fixture)

        await adapter.call(sensor_event)

        assert len(results) == 1
        state = results[0]
        assert isinstance(state, states.BaseState), "State should be BaseState"
        assert state.entity_id.startswith("sensor."), "Entity ID should have sensor domain"

    @pytest.mark.parametrize(
        "event_fixture_name",
        [
            "state_change_events_with_new_state",
            "state_change_events_with_old_state",
            "state_change_events_with_both_states",
        ],
        ids=[
            "new_state_only",
            "old_state_only",
            "new_and_old_state",
        ],
    )
    async def test_old_state_new_state_converted_correctly(
        self, bucket_fixture: TaskBucket, event_fixture_name: str, request: pytest.FixtureRequest
    ):
        """Test that both old and new states are converted correctly."""
        state_change_events = request.getfixturevalue(event_fixture_name)

        input_button_event = next((e for e in state_change_events if e.payload.data.domain == "input_button"), None)

        assert input_button_event is not None, "No InputButtonState domain event found in test data"

        results = []

        def handler_new_maybe_old(
            new_state: D.StateNew[states.InputButtonState],
            old_state: D.MaybeStateOld[states.InputButtonState],
        ):
            results.append((new_state, old_state))

        def handle_new_and_old(
            new_state: D.StateNew[states.InputButtonState],
            old_state: D.StateOld[states.InputButtonState],
        ):
            results.append((new_state, old_state))

        def handle_maybe_new_and_old(
            new_state: D.MaybeStateNew[states.InputButtonState],
            old_state: D.StateOld[states.InputButtonState],
        ):
            results.append((new_state, old_state))

        if event_fixture_name == "state_change_events_with_new_state":
            handler = handler_new_maybe_old
        elif event_fixture_name == "state_change_events_with_old_state":
            handler = handle_maybe_new_and_old
        else:
            handler = handle_new_and_old

        async_handler = bucket_fixture.make_async_adapter(handler)
        adapter = create_adapter(async_handler, bucket_fixture)

        await adapter.call(input_button_event)

        assert len(results) == 1
        new_state, old_state = results[0]

        if event_fixture_name in ["state_change_events_with_new_state", "state_change_events_with_both_states"]:
            assert isinstance(new_state, states.InputButtonState), "New state should be InputButtonState"

        if event_fixture_name in ["state_change_events_with_old_state", "state_change_events_with_both_states"]:
            assert isinstance(old_state, states.InputButtonState), "Old state should be InputButtonState"
