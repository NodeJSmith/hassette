"""Unit tests for the EventCapture test utility contract."""

from hassette.test_utils import make_hassette_event, make_mock_hassette
from hassette.test_utils.event_capture import EventCapture
from hassette.types import Topic


class TestEventCaptureEmpty:
    def test_empty_capture_has_no_events(self) -> None:
        capture = EventCapture()

        assert capture.events == []
        assert capture.topics == []
        assert capture.by_topic(Topic.HASSETTE_EVENT_SERVICE_STATUS) == []
        assert capture.payloads(Topic.HASSETTE_EVENT_SERVICE_STATUS) == []


class TestEventCaptureInstall:
    async def test_records_events_in_order(self) -> None:
        hassette = make_mock_hassette(sealed=False)
        capture = EventCapture()
        capture.install(hassette)

        first = make_hassette_event(topic=Topic.HASSETTE_EVENT_SERVICE_STATUS, data="first")
        second = make_hassette_event(topic=Topic.HASSETTE_EVENT_APP_STATE_CHANGED, data="second")

        await hassette.send_event(first)
        await hassette.send_event(second)

        assert capture.events == [first, second]


class TestEventCaptureByTopic:
    async def test_filters_matching_events(self) -> None:
        hassette = make_mock_hassette(sealed=False)
        capture = EventCapture()
        capture.install(hassette)

        status_event = make_hassette_event(topic=Topic.HASSETTE_EVENT_SERVICE_STATUS, data="status")
        app_event = make_hassette_event(topic=Topic.HASSETTE_EVENT_APP_STATE_CHANGED, data="app")

        await hassette.send_event(status_event)
        await hassette.send_event(app_event)

        assert capture.by_topic(Topic.HASSETTE_EVENT_SERVICE_STATUS) == [status_event]
        assert capture.by_topic(Topic.HASSETTE_EVENT_APP_STATE_CHANGED) == [app_event]

    async def test_returns_empty_for_unmatched_topic(self) -> None:
        hassette = make_mock_hassette(sealed=False)
        capture = EventCapture()
        capture.install(hassette)

        await hassette.send_event(make_hassette_event(topic=Topic.HASSETTE_EVENT_SERVICE_STATUS, data="status"))

        assert capture.by_topic(Topic.HASSETTE_EVENT_APP_STATE_CHANGED) == []
        assert capture.by_topic("hassette.event.unknown_topic") == []


class TestEventCapturePayloads:
    async def test_extracts_payload_data_in_order(self) -> None:
        hassette = make_mock_hassette(sealed=False)
        capture = EventCapture()
        capture.install(hassette)

        await hassette.send_event(make_hassette_event(topic=Topic.HASSETTE_EVENT_SERVICE_STATUS, data="one"))
        await hassette.send_event(make_hassette_event(topic=Topic.HASSETTE_EVENT_SERVICE_STATUS, data="two"))
        await hassette.send_event(make_hassette_event(topic=Topic.HASSETTE_EVENT_APP_STATE_CHANGED, data="other"))

        assert capture.payloads(Topic.HASSETTE_EVENT_SERVICE_STATUS) == ["one", "two"]


class TestEventCaptureTopics:
    async def test_returns_topic_strings_in_order(self) -> None:
        hassette = make_mock_hassette(sealed=False)
        capture = EventCapture()
        capture.install(hassette)

        await hassette.send_event(make_hassette_event(topic=Topic.HASSETTE_EVENT_SERVICE_STATUS, data=None))
        await hassette.send_event(make_hassette_event(topic=Topic.HASSETTE_EVENT_APP_STATE_CHANGED, data=None))

        assert capture.topics == [
            str(Topic.HASSETTE_EVENT_SERVICE_STATUS),
            str(Topic.HASSETTE_EVENT_APP_STATE_CHANGED),
        ]


class TestEventCaptureCapturing:
    async def test_installs_and_restores_send_event(self) -> None:
        hassette = make_mock_hassette(sealed=False)
        original_send_event = hassette.send_event

        with EventCapture.capturing(hassette) as capture:
            assert hassette.send_event is not original_send_event
            await hassette.send_event(make_hassette_event(topic=Topic.HASSETTE_EVENT_SERVICE_STATUS, data="x"))

        assert hassette.send_event is original_send_event
        assert capture.by_topic(Topic.HASSETTE_EVENT_SERVICE_STATUS)
