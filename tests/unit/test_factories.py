"""Unit tests for the 7 shared factories added to hassette.test_utils.factories.

Covers make_scheduled_job, make_mock_executor, make_mock_event,
make_recording_api, make_hassette_event, make_hass_event, and make_mock_parent.
"""

from unittest.mock import AsyncMock, MagicMock

import pytest

from hassette.events.base import Event, HassettePayload, HassPayload
from hassette.scheduler.classes import ScheduledJob
from hassette.scheduler.triggers import After
from hassette.test_utils.factories import (
    make_hass_event,
    make_hassette_event,
    make_mock_event,
    make_mock_executor,
    make_mock_parent,
    make_recording_api,
    make_scheduled_job,
)
from hassette.test_utils.helpers import make_light_state_dict
from hassette.test_utils.recording_api import RecordingApi


class TestMakeScheduledJob:
    def test_defaults(self):
        job = make_scheduled_job()
        assert isinstance(job, ScheduledJob)
        assert job.owner_id == "test_owner"
        assert job.name == "test_job"
        assert job.job() is None
        assert job.trigger is None
        assert job.mode is not None

    def test_overrides(self):
        trigger = After(seconds=30)
        job = make_scheduled_job(
            owner_id="custom_owner",
            name="custom_job",
            trigger=trigger,
            group="my_group",
            jitter=1.5,
            timeout=10.0,
            db_id=42,
        )
        assert job.owner_id == "custom_owner"
        assert job.name == "custom_job"
        assert job.trigger is trigger
        assert job.group == "my_group"
        assert job.jitter == 1.5
        assert job.timeout == 10.0
        assert job.db_id == 42

    def test_custom_job_callable(self):
        calls = []
        job = make_scheduled_job(job=lambda: calls.append(1))
        job.job()
        assert calls == [1]


class TestMakeMockExecutor:
    async def test_execute_is_awaitable(self):
        executor = make_mock_executor()
        assert isinstance(executor, MagicMock)
        assert isinstance(executor.execute, AsyncMock)
        await executor.execute()


class TestMakeMockEvent:
    def test_spec_is_event(self):
        event = make_mock_event()
        assert isinstance(event, MagicMock)
        with pytest.raises(AttributeError):
            _ = event.not_a_real_event_attribute


class TestMakeRecordingApi:
    def test_returns_recording_api_with_no_states(self):
        api = make_recording_api()
        assert isinstance(api, RecordingApi)

    async def test_seeded_states_are_readable(self):
        state = make_light_state_dict(entity_id="light.kitchen")
        api = make_recording_api(states={"light.kitchen": state})
        result = await api.get_state("light.kitchen")
        assert result.entity_id == "light.kitchen"


class TestMakeHassetteEvent:
    def test_defaults(self):
        event = make_hassette_event()
        assert isinstance(event, Event)
        assert event.topic == "hassette.ready"
        assert isinstance(event.payload, HassettePayload)
        assert event.payload.data is None

    def test_overrides(self):
        event = make_hassette_event(topic="hassette.custom", data={"foo": "bar"})
        assert event.topic == "hassette.custom"
        assert event.payload.data == {"foo": "bar"}


class TestMakeHassEvent:
    def test_defaults(self):
        event = make_hass_event()
        assert isinstance(event, Event)
        assert event.topic == "hass.state_changed"
        assert isinstance(event.payload, HassPayload)
        assert event.payload.event_type == "state_changed"
        assert event.payload.origin == "LOCAL"
        assert event.payload.context.id == "ctx-test"

    def test_overrides(self):
        event = make_hass_event(
            event_type="zha_event",
            data={"device": "switch"},
            origin="REMOTE",
            context_id="ctx-custom",
        )
        assert event.topic == "hass.zha_event"
        assert event.payload.event_type == "zha_event"
        assert event.payload.data == {"device": "switch"}
        assert event.payload.origin == "REMOTE"
        assert event.payload.context.id == "ctx-custom"


class TestMakeMockParent:
    def test_defaults(self):
        parent = make_mock_parent()
        assert parent.app_key == "test_app"
        assert parent.index == 0
        assert parent.unique_name == "test_app.0"
        assert parent.source_tier == "app"
        assert parent.class_name == "TestApp"
        assert parent.app_config is None

    def test_overrides(self):
        app_config = MagicMock()
        parent = make_mock_parent(
            app_key="other_app",
            index=2,
            unique_name="other_app.2",
            source_tier="framework",
            class_name="OtherApp",
            app_config=app_config,
        )
        assert parent.app_key == "other_app"
        assert parent.index == 2
        assert parent.unique_name == "other_app.2"
        assert parent.source_tier == "framework"
        assert parent.class_name == "OtherApp"
        assert parent.app_config is app_config
