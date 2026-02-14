"""Tests for ListenerMetrics aggregate counter dataclass."""

from hassette.bus.metrics import ListenerMetrics


class TestListenerMetricsDefaults:
    def test_initial_state(self) -> None:
        m = ListenerMetrics(listener_id=1, owner="my_app", topic="hass.event.state_changed", handler_name="on_light")
        assert m.total_invocations == 0
        assert m.successful == 0
        assert m.failed == 0
        assert m.di_failures == 0
        assert m.cancelled == 0
        assert m.total_duration_ms == 0.0
        assert m.min_duration_ms == 0.0
        assert m.max_duration_ms == 0.0
        assert m.last_invoked_at is None
        assert m.last_error_message is None
        assert m.last_error_type is None


class TestRecordSuccess:
    def test_single_success(self) -> None:
        m = ListenerMetrics(listener_id=1, owner="app", topic="t", handler_name="h")
        m.record_success(10.0)
        assert m.total_invocations == 1
        assert m.successful == 1
        assert m.total_duration_ms == 10.0
        assert m.min_duration_ms == 10.0
        assert m.max_duration_ms == 10.0
        assert m.last_invoked_at is not None

    def test_multiple_successes_update_min_max(self) -> None:
        m = ListenerMetrics(listener_id=1, owner="app", topic="t", handler_name="h")
        m.record_success(5.0)
        m.record_success(15.0)
        m.record_success(10.0)
        assert m.total_invocations == 3
        assert m.successful == 3
        assert m.min_duration_ms == 5.0
        assert m.max_duration_ms == 15.0
        assert m.total_duration_ms == 30.0


class TestRecordError:
    def test_single_error(self) -> None:
        m = ListenerMetrics(listener_id=1, owner="app", topic="t", handler_name="h")
        m.record_error(8.0, "boom", "ValueError")
        assert m.total_invocations == 1
        assert m.failed == 1
        assert m.successful == 0
        assert m.last_error_message == "boom"
        assert m.last_error_type == "ValueError"
        assert m.total_duration_ms == 8.0

    def test_error_updates_timing(self) -> None:
        m = ListenerMetrics(listener_id=1, owner="app", topic="t", handler_name="h")
        m.record_success(5.0)
        m.record_error(20.0, "fail", "RuntimeError")
        assert m.max_duration_ms == 20.0
        assert m.min_duration_ms == 5.0


class TestRecordDiFailure:
    def test_di_failure(self) -> None:
        m = ListenerMetrics(listener_id=1, owner="app", topic="t", handler_name="h")
        m.record_di_failure(3.0, "bad sig", "DependencyInjectionError")
        assert m.total_invocations == 1
        assert m.di_failures == 1
        assert m.failed == 0  # DI failures are separate from general failures
        assert m.last_error_message == "bad sig"
        assert m.last_error_type == "DependencyInjectionError"


class TestRecordCancelled:
    def test_cancelled(self) -> None:
        m = ListenerMetrics(listener_id=1, owner="app", topic="t", handler_name="h")
        m.record_cancelled(2.0)
        assert m.total_invocations == 1
        assert m.cancelled == 1
        assert m.successful == 0
        assert m.failed == 0


class TestAvgDurationMs:
    def test_zero_invocations(self) -> None:
        m = ListenerMetrics(listener_id=1, owner="app", topic="t", handler_name="h")
        assert m.avg_duration_ms == 0.0

    def test_computed_average(self) -> None:
        m = ListenerMetrics(listener_id=1, owner="app", topic="t", handler_name="h")
        m.record_success(10.0)
        m.record_success(20.0)
        assert m.avg_duration_ms == 15.0

    def test_includes_errors_in_average(self) -> None:
        m = ListenerMetrics(listener_id=1, owner="app", topic="t", handler_name="h")
        m.record_success(10.0)
        m.record_error(30.0, "err", "E")
        assert m.avg_duration_ms == 20.0


class TestToDict:
    def test_serialization(self) -> None:
        m = ListenerMetrics(listener_id=42, owner="my_app", topic="hass.event.state_changed", handler_name="on_light")
        m.record_success(10.0)
        d = m.to_dict()
        assert d["listener_id"] == 42
        assert d["owner"] == "my_app"
        assert d["topic"] == "hass.event.state_changed"
        assert d["handler_name"] == "on_light"
        assert d["total_invocations"] == 1
        assert d["successful"] == 1
        assert d["failed"] == 0
        assert d["di_failures"] == 0
        assert d["cancelled"] == 0
        assert d["avg_duration_ms"] == 10.0
        assert d["min_duration_ms"] == 10.0
        assert d["max_duration_ms"] == 10.0
        assert d["total_duration_ms"] == 10.0
        assert d["last_invoked_at"] is not None
        assert d["last_error_message"] is None
        assert d["last_error_type"] is None

    def test_empty_metrics_serialization(self) -> None:
        m = ListenerMetrics(listener_id=1, owner="app", topic="t", handler_name="h")
        d = m.to_dict()
        assert d["total_invocations"] == 0
        assert d["avg_duration_ms"] == 0.0
        assert d["last_invoked_at"] is None


class TestMixedOperations:
    def test_mixed_operations(self) -> None:
        m = ListenerMetrics(listener_id=1, owner="app", topic="t", handler_name="h")
        m.record_success(10.0)
        m.record_error(20.0, "err", "ValueError")
        m.record_di_failure(5.0, "bad", "DependencyInjectionError")
        m.record_cancelled(3.0)
        assert m.total_invocations == 4
        assert m.successful == 1
        assert m.failed == 1
        assert m.di_failures == 1
        assert m.cancelled == 1
        assert m.min_duration_ms == 3.0
        assert m.max_duration_ms == 20.0
        assert m.total_duration_ms == 38.0
        assert m.avg_duration_ms == 9.5
