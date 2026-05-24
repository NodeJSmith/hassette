"""Unit tests for the HassetteCLIClient HTTP client wrapper."""

import json
from typing import Any

import httpx
import pytest
from pydantic import BaseModel

from hassette.cli.client import HassetteCLIClient
from hassette.config.config import HassetteConfig
from hassette.config.models import WebApiConfig
from hassette.test_utils.web_helpers import make_manifest_list_response, make_manifest_response
from hassette.web.models import AppInstanceResponse
from tests.unit.cli.conftest import capture_stderr

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class SimpleModel(BaseModel):
    value: str


def make_transport(
    status_code: int = 200,
    body: Any = None,
    *,
    raise_exc: type[Exception] | None = None,
) -> httpx.MockTransport:
    """Build an httpx.MockTransport that returns a fixed response."""
    if raise_exc is not None:

        def handler(request: httpx.Request) -> httpx.Response:
            raise raise_exc(f"mocked: {request.url}")

        return httpx.MockTransport(handler)

    json_body = json.dumps(body if body is not None else {})

    def _fixed_response(_req: httpx.Request) -> httpx.Response:
        return httpx.Response(
            status_code,
            content=json_body.encode(),
            headers={"content-type": "application/json"},
        )

    return httpx.MockTransport(_fixed_response)


def _make_config(host: str = "127.0.0.1", port: int = 8126) -> HassetteConfig:
    return HassetteConfig(token=None, web_api=WebApiConfig(host=host, port=port))


def _make_manifest_list(instances: list[AppInstanceResponse]):
    manifest = make_manifest_response(instance_count=len(instances), instances=instances)
    return make_manifest_list_response(manifests=[manifest])


# ---------------------------------------------------------------------------
# Base URL construction & address substitution
# ---------------------------------------------------------------------------


class TestBaseUrl:
    def test_default_address(self) -> None:
        config = _make_config("127.0.0.1", 8126)
        client = HassetteCLIClient(config, json_mode=False)
        assert client.base_url == "http://127.0.0.1:8126"

    def test_bind_all_ipv4_substituted(self) -> None:
        config = _make_config("0.0.0.0", 8126)
        client = HassetteCLIClient(config, json_mode=False)
        assert client.base_url == "http://127.0.0.1:8126"

    def test_bind_all_ipv6_substituted(self) -> None:
        config = _make_config("::", 8080)
        client = HassetteCLIClient(config, json_mode=False)
        assert client.base_url == "http://[::1]:8080"

    def test_non_default_host_port(self) -> None:
        config = _make_config("192.168.1.5", 9000)
        client = HassetteCLIClient(config, json_mode=False)
        assert client.base_url == "http://192.168.1.5:9000"


# ---------------------------------------------------------------------------
# Successful deserialization
# ---------------------------------------------------------------------------


class TestSuccessfulRequests:
    def test_returns_deserialized_pydantic_model(self) -> None:
        config = _make_config()
        transport = make_transport(200, {"value": "hello"})
        client = HassetteCLIClient(config, json_mode=False, transport=transport)
        result = client.get("/test", SimpleModel)
        assert isinstance(result, SimpleModel)
        assert result.value == "hello"

    def test_returns_dict_for_dict_response(self) -> None:
        config = _make_config()
        body = {"light": {"turn_on": {"description": "Turn on light"}}}
        transport = make_transport(200, body)
        client = HassetteCLIClient(config, json_mode=False, transport=transport)
        result = client.get("/api/services", dict)
        assert isinstance(result, dict)
        assert "light" in result


# ---------------------------------------------------------------------------
# HTTP error handling (human mode)
# ---------------------------------------------------------------------------


class TestHttpErrorsHumanMode:
    def test_404_exits_with_code_1(self, capsys: pytest.CaptureFixture[str]) -> None:
        config = _make_config()
        transport = make_transport(404, {"detail": "Not found"})
        client = HassetteCLIClient(config, json_mode=False, transport=transport)
        with pytest.raises(SystemExit) as exc_info:
            client.get("/api/missing", SimpleModel)
        assert exc_info.value.code == 1

    def test_404_prints_to_stderr(self) -> None:
        config = _make_config()
        transport = make_transport(404, {"detail": "Not found"})
        client = HassetteCLIClient(config, json_mode=False, transport=transport)
        with capture_stderr() as buf, pytest.raises(SystemExit):
            client.get("/api/missing", SimpleModel)
        assert len(buf.getvalue()) > 0

    def test_500_exits_with_code_1(self) -> None:
        config = _make_config()
        transport = make_transport(500, {"detail": "Internal server error"})
        client = HassetteCLIClient(config, json_mode=False, transport=transport)
        with pytest.raises(SystemExit) as exc_info:
            client.get("/api/crash", SimpleModel)
        assert exc_info.value.code == 1

    def test_nothing_on_stdout_for_http_error_human_mode(self, capsys: pytest.CaptureFixture[str]) -> None:
        config = _make_config()
        transport = make_transport(503, {"detail": "Service unavailable"})
        client = HassetteCLIClient(config, json_mode=False, transport=transport)
        with pytest.raises(SystemExit):
            client.get("/api/health", SimpleModel)
        captured = capsys.readouterr()
        assert captured.out == ""


# ---------------------------------------------------------------------------
# HTTP error handling (json mode)
# ---------------------------------------------------------------------------


class TestHttpErrorsJsonMode:
    def test_404_json_error_structure(self, capsys: pytest.CaptureFixture[str]) -> None:
        config = _make_config()
        transport = make_transport(404, {"detail": "Not found"})
        client = HassetteCLIClient(config, json_mode=True, transport=transport)
        with pytest.raises(SystemExit) as exc_info:
            client.get("/api/missing", SimpleModel)
        assert exc_info.value.code == 1
        captured = capsys.readouterr()
        parsed = json.loads(captured.out)
        assert parsed["error"] is True
        assert parsed["status"] == 404
        assert "detail" in parsed

    def test_json_mode_error_nothing_on_stderr(self, capsys: pytest.CaptureFixture[str]) -> None:
        config = _make_config()
        transport = make_transport(500, {"detail": "boom"})
        client = HassetteCLIClient(config, json_mode=True, transport=transport)
        with pytest.raises(SystemExit):
            client.get("/api/crash", SimpleModel)
        captured = capsys.readouterr()
        # In json mode, error goes to stdout only
        parsed = json.loads(captured.out)
        assert parsed["error"] is True


# ---------------------------------------------------------------------------
# Network errors (connection refused / timeout)
# ---------------------------------------------------------------------------


class TestNetworkErrors:
    def test_connection_refused_exits_code_2(self) -> None:
        config = _make_config()
        transport = make_transport(raise_exc=httpx.ConnectError)
        client = HassetteCLIClient(config, json_mode=False, transport=transport)
        with pytest.raises(SystemExit) as exc_info:
            client.get("/api/health", SimpleModel)
        assert exc_info.value.code == 2

    def test_connection_refused_mentions_address_stderr(self) -> None:
        config = _make_config("127.0.0.1", 8126)
        transport = make_transport(raise_exc=httpx.ConnectError)
        client = HassetteCLIClient(config, json_mode=False, transport=transport)
        with capture_stderr() as buf, pytest.raises(SystemExit):
            client.get("/api/health", SimpleModel)
        output = buf.getvalue()
        assert "127.0.0.1" in output or "8126" in output

    def test_timeout_exits_code_2(self) -> None:
        config = _make_config()
        transport = make_transport(raise_exc=httpx.TimeoutException)
        client = HassetteCLIClient(config, json_mode=False, transport=transport)
        with pytest.raises(SystemExit) as exc_info:
            client.get("/api/health", SimpleModel)
        assert exc_info.value.code == 2

    def test_timeout_json_mode_null_status(self, capsys: pytest.CaptureFixture[str]) -> None:
        config = _make_config()
        transport = make_transport(raise_exc=httpx.TimeoutException)
        client = HassetteCLIClient(config, json_mode=True, transport=transport)
        with pytest.raises(SystemExit):
            client.get("/api/health", SimpleModel)
        captured = capsys.readouterr()
        parsed = json.loads(captured.out)
        assert parsed["error"] is True
        assert parsed["status"] is None
        assert "detail" in parsed

    def test_connection_refused_json_mode_null_status(self, capsys: pytest.CaptureFixture[str]) -> None:
        config = _make_config()
        transport = make_transport(raise_exc=httpx.ConnectError)
        client = HassetteCLIClient(config, json_mode=True, transport=transport)
        with pytest.raises(SystemExit):
            client.get("/api/health", SimpleModel)
        captured = capsys.readouterr()
        parsed = json.loads(captured.out)
        assert parsed["error"] is True
        assert parsed["status"] is None


# ---------------------------------------------------------------------------
# App-key URL routing
# ---------------------------------------------------------------------------


class TestAppKeyRouting:
    def test_no_app_uses_global_listener_url(self) -> None:
        config = _make_config()
        captured_urls: list[str] = []

        def handler(request: httpx.Request) -> httpx.Response:
            captured_urls.append(str(request.url))
            return httpx.Response(200, content=b"[]", headers={"content-type": "application/json"})

        client = HassetteCLIClient(config, json_mode=False, transport=httpx.MockTransport(handler))
        client.get_with_app_routing(
            global_path="/api/bus/listeners",
            per_app_path_template="/api/telemetry/app/{app_key}/listeners",
            model=list,
            app_key=None,
        )
        assert any("/api/bus/listeners" in u for u in captured_urls)

    def test_app_key_uses_per_app_listener_url(self) -> None:
        config = _make_config()
        captured_urls: list[str] = []

        def handler(request: httpx.Request) -> httpx.Response:
            captured_urls.append(str(request.url))
            return httpx.Response(200, content=b"[]", headers={"content-type": "application/json"})

        client = HassetteCLIClient(config, json_mode=False, transport=httpx.MockTransport(handler))
        client.get_with_app_routing(
            global_path="/api/bus/listeners",
            per_app_path_template="/api/telemetry/app/{app_key}/listeners",
            model=list,
            app_key="my_app",
        )
        assert any("/api/telemetry/app/my_app/listeners" in u for u in captured_urls)


# ---------------------------------------------------------------------------
# --instance flag
# ---------------------------------------------------------------------------


class TestInstanceRouting:
    def test_integer_instance_passes_index_as_query_param(self) -> None:
        config = _make_config()
        captured_urls: list[str] = []

        def handler(request: httpx.Request) -> httpx.Response:
            captured_urls.append(str(request.url))
            return httpx.Response(200, content=b"[]", headers={"content-type": "application/json"})

        client = HassetteCLIClient(config, json_mode=False, transport=httpx.MockTransport(handler))
        client.get_with_app_routing(
            global_path="/api/bus/listeners",
            per_app_path_template="/api/telemetry/app/{app_key}/listeners",
            model=list,
            app_key="my_app",
            instance="1",
        )
        assert any("instance_index=1" in u for u in captured_urls)

    def test_name_instance_resolves_to_index(self) -> None:
        config = _make_config()
        call_count = 0
        instances = [
            AppInstanceResponse(
                app_key="my_app", index=0, instance_name="default", class_name="MyApp", status="running"
            ),
            AppInstanceResponse(
                app_key="my_app", index=1, instance_name="office", class_name="MyApp", status="running"
            ),
        ]
        manifest_list = _make_manifest_list(instances)

        def handler(request: httpx.Request) -> httpx.Response:
            nonlocal call_count
            call_count += 1
            if "/api/apps/manifests" in str(request.url):
                return httpx.Response(
                    200,
                    content=manifest_list.model_dump_json().encode(),
                    headers={"content-type": "application/json"},
                )
            return httpx.Response(200, content=b"[]", headers={"content-type": "application/json"})

        captured_urls: list[str] = []
        original_handler = handler

        def tracking_handler(request: httpx.Request) -> httpx.Response:
            captured_urls.append(str(request.url))
            return original_handler(request)

        client = HassetteCLIClient(config, json_mode=False, transport=httpx.MockTransport(tracking_handler))
        client.get_with_app_routing(
            global_path="/api/bus/listeners",
            per_app_path_template="/api/telemetry/app/{app_key}/listeners",
            model=list,
            app_key="my_app",
            instance="office",
        )
        assert any("instance_index=1" in u for u in captured_urls)

    def test_unknown_instance_name_exits_nonzero(self) -> None:
        config = _make_config()
        instances = [
            AppInstanceResponse(
                app_key="my_app", index=0, instance_name="default", class_name="MyApp", status="running"
            ),
        ]
        manifest_list = _make_manifest_list(instances)

        def handler(request: httpx.Request) -> httpx.Response:
            if "/api/apps/manifests" in str(request.url):
                return httpx.Response(
                    200,
                    content=manifest_list.model_dump_json().encode(),
                    headers={"content-type": "application/json"},
                )
            return httpx.Response(200, content=b"[]", headers={"content-type": "application/json"})

        client = HassetteCLIClient(config, json_mode=False, transport=httpx.MockTransport(handler))
        with pytest.raises(SystemExit) as exc_info:
            client.get_with_app_routing(
                global_path="/api/bus/listeners",
                per_app_path_template="/api/telemetry/app/{app_key}/listeners",
                model=list,
                app_key="my_app",
                instance="nonexistent",
            )
        assert exc_info.value.code != 0
        client2 = HassetteCLIClient(config, json_mode=False, transport=httpx.MockTransport(handler))
        with capture_stderr() as buf, pytest.raises(SystemExit):
            client2.get_with_app_routing(
                global_path="/api/bus/listeners",
                per_app_path_template="/api/telemetry/app/{app_key}/listeners",
                model=list,
                app_key="my_app",
                instance="nonexistent",
            )
        assert "default" in buf.getvalue()

    def test_instance_without_app_exits_nonzero(self) -> None:
        config = _make_config()
        transport = make_transport(200, [])
        client = HassetteCLIClient(config, json_mode=False, transport=transport)
        with capture_stderr() as buf, pytest.raises(SystemExit) as exc_info:
            client.get_with_app_routing(
                global_path="/api/bus/listeners",
                per_app_path_template="/api/telemetry/app/{app_key}/listeners",
                model=list,
                app_key=None,
                instance="office",
            )
        assert exc_info.value.code != 0
        assert "--app" in buf.getvalue()
